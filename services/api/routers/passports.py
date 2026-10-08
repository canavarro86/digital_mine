"""Паспорта БВР: библиотека врубов, типовые паспорта (версии, согласование, назначение, автоподбор),
паспорт на проходку забоя (расчет, редактор, утверждение, экспорт PDF/DXF/CSV)."""
from __future__ import annotations

import copy

from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from common import i18n, storage
from common.db import get_db
from common.models import (
    CutTemplate,
    DevPassport,
    Explosive,
    Face,
    InitiationDevice,
    Mine,
    TypicalPassport,
    TypicalPassportVersion,
    Working,
)
from common.timeutil import to_tz, utcnow
from common.web import attachment
from core import exporters, passport
from core import geometry as g

from ..deps import CurrentUser, audit, require
from ..svc import active_mine, calc, explosive_dict, geology_at

router = APIRouter(prefix="/api/passports", tags=["passports"])
VIEW = require("passports.view")
EDIT = require("passports.edit")
STATUS_FLOW = {"draft": {"review", "archived"}, "review": {"approved", "draft"}, "approved": {"archived", "draft"},
               "archived": {"draft"}}


# ---------------- расчет ----------------
def compute(inp: dict) -> dict:
    res = calc("/calc/passport/design", {"input": inp}, lambda: passport.design(inp))
    errs = [w for w in res.get("warnings", []) if w["level"] == "error"]
    if errs:
        raise HTTPException(400, {"code": "errors." + errs[0]["code"], "params": errs[0].get("params", {}),
                                  "issues": errs})
    return res


def evaluate(result: dict) -> dict:
    return calc("/calc/passport/evaluate", {"result": result}, lambda: passport.evaluate(copy.deepcopy(result)))


def build_input(db: Session, base: dict, working: Working | None, chainage: float | None) -> dict:
    """Исходные данные: сечение выработки, порода интервала, ВВ из справочника, станок."""
    inp = copy.deepcopy(base or {})
    if working is not None:
        inp.setdefault("section", {k: v for k, v in (working.section or {}).items()
                                   if k in ("shape", "width", "height", "arch_height", "top_width", "contour")})
        geo = geology_at(db, working, chainage)
        rock = {k: geo.get(k) for k in ("f", "fracture_cat", "density", "water", "cleavage")}
        rock.update({"rock_name": geo.get("rock_name"), "source": geo.get("priority")})
        inp["rock"] = {**rock, **{k: v for k, v in (base or {}).get("rock_override", {}).items() if v is not None}}
    for key in ("explosive", "contour_explosive"):
        eid = inp.pop(f"{key}_id", None)
        if eid:
            e = db.get(Explosive, int(eid))
            if e:
                inp[key] = explosive_dict(e)
    did = inp.pop("initiation_device_id", None)
    if did:
        d = db.get(InitiationDevice, int(did))
        if d:
            inp["initiation_device"] = d.as_dict()
            inp["initiation"] = "edd" if d.kind == "edd" else "nonel"
    if "explosive" not in inp:
        e = db.scalar(select(Explosive).where(Explosive.type == "emulsion"))
        inp["explosive"] = explosive_dict(e)
    inp.setdefault("hole_depth", 3.8)
    inp.setdefault("hole_diameter", 45)
    inp.setdefault("empty_diameter", 102)
    inp.setdefault("cut", {"type": "prismatic"})
    inp.setdefault("initiation", "edd")
    inp.setdefault("drill", {"booms": 2, "drill_rate_mph": 90, "setup_h": 0.5})
    return inp


# ---------------- врубы ----------------
@router.get("/cuts")
def cuts(db: Session = Depends(get_db), _: CurrentUser = Depends(VIEW)):
    return [c.as_dict() for c in db.scalars(select(CutTemplate).order_by(CutTemplate.id))]


@router.post("/cuts")
def create_cut(body: dict, db: Session = Depends(get_db), user: CurrentUser = Depends(EDIT)):
    c = CutTemplate(name=body["name"], type=body.get("type", "custom"), params=body.get("params", {}),
                    holes=body.get("holes", []))
    db.add(c)
    audit(db, user, "cut_create", "cut", body["name"])
    db.commit()
    return c.as_dict()


# ---------------- типовые ----------------
def _tp_out(tp: TypicalPassport, full: bool = False) -> dict:
    d = tp.as_dict()
    if not full:
        d.pop("design")
        d.pop("input")
    return d


@router.get("/typical")
def typical_list(status: str | None = None, db: Session = Depends(get_db), _: CurrentUser = Depends(VIEW)):
    q = select(TypicalPassport).order_by(TypicalPassport.number)
    if status:
        q = q.where(TypicalPassport.status == status)
    return [_tp_out(t) for t in db.scalars(q)]


@router.get("/typical/{tid}")
def typical_get(tid: int, db: Session = Depends(get_db), _: CurrentUser = Depends(VIEW)):
    tp = db.get(TypicalPassport, tid)
    if not tp:
        raise HTTPException(404, "errors.not_found")
    d = _tp_out(tp, full=True)
    d["versions"] = [v.as_dict() for v in db.scalars(select(TypicalPassportVersion).where(
        TypicalPassportVersion.passport_id == tid).order_by(TypicalPassportVersion.version.desc()))]
    return d


def _diff(a: dict, b: dict, prefix: str = "") -> list[dict]:
    out = []
    for k in sorted(set(a) | set(b)):
        va, vb = a.get(k), b.get(k)
        if isinstance(va, dict) and isinstance(vb, dict) and k not in ("explosive", "contour_explosive"):
            out += _diff(va, vb, f"{prefix}{k}.")
        elif k in ("explosive", "contour_explosive"):
            na, nb = (va or {}).get("name"), (vb or {}).get("name")
            if na != nb:
                out.append({"field": prefix + k, "was": na, "now": nb})
        elif va != vb:
            out.append({"field": prefix + k, "was": va, "now": vb})
    return out


@router.post("/typical")
def typical_create(body: dict, db: Session = Depends(get_db), user: CurrentUser = Depends(EDIT)):
    """Создать типовой: из паспорта забоя (from_dev_id), по исходным данным (input) или «вручную» (только параметры)."""
    if body.get("from_dev_id"):
        dp = db.get(DevPassport, int(body["from_dev_id"]))
        inp, res = dp.input, dp.design
    elif body.get("input"):
        inp = build_input(db, body["input"], None, None)
        res = compute(inp)
    else:
        inp, res = {}, {"indicators": body.get("indicators", {})}
    sec = inp.get("section") or body.get("section") or {}
    tp = TypicalPassport(mine_id=active_mine(db).id, number=body["number"], name=body.get("name", body["number"]),
                         working_type=body.get("working_type", "fwd"), section=g.section_info(sec) if sec else {},
                         f_min=float(body.get("f_min", 0)), f_max=float(body.get("f_max", 20)),
                         water=body.get("water", ["dry", "damp"]),
                         explosive_id=(inp.get("explosive") or {}).get("id"), input=inp, design=res,
                         indicators=res.get("indicators", {}), status="draft", created_by=user.username,
                         assigned=body.get("assigned", {}))
    db.add(tp)
    db.flush()
    db.add(TypicalPassportVersion(passport_id=tp.id, version=1, data={"input": inp, "indicators": tp.indicators},
                                  changed_by=user.username, note=body.get("note", "")))
    audit(db, user, "typical_create", "typical", tp.number)
    db.commit()
    return _tp_out(tp)


@router.put("/typical/{tid}")
def typical_update(tid: int, body: dict, db: Session = Depends(get_db), user: CurrentUser = Depends(EDIT)):
    tp = db.get(TypicalPassport, tid)
    if not tp:
        raise HTTPException(404, "errors.not_found")
    old_input = copy.deepcopy(tp.input)
    changes = []
    for k in ("name", "number", "working_type", "f_min", "f_max", "water", "assigned"):
        if k in body and body[k] != getattr(tp, k):
            changes.append({"field": k, "was": getattr(tp, k), "now": body[k]})
            setattr(tp, k, body[k])
    if body.get("input"):
        inp = build_input(db, {**old_input, **body["input"]}, None, None)
        res = compute(inp)
        changes += _diff(old_input, inp)
        tp.input, tp.design, tp.indicators = inp, res, res["indicators"]
        tp.section = g.section_info(inp["section"])
    if not changes:
        return _tp_out(tp)
    tp.version += 1
    if tp.status == "approved":
        tp.status = "draft"  # изменение утвержденного → новая версия на согласование
    db.add(TypicalPassportVersion(passport_id=tp.id, version=tp.version, data={"input": tp.input, "indicators": tp.indicators},
                                  changes=changes, changed_by=user.username, note=body.get("note", "")))
    audit(db, user, "typical_update", "typical", tid, {"version": tp.version, "changes": len(changes)})
    db.commit()
    return _tp_out(tp)


@router.post("/typical/{tid}/status")
def typical_status(tid: int, body: dict, db: Session = Depends(get_db), user: CurrentUser = Depends(EDIT)):
    tp = db.get(TypicalPassport, tid)
    new = body["status"]
    if not tp or new not in STATUS_FLOW.get(tp.status, set()):
        raise HTTPException(400, "errors.bad_transition")
    if new == "approved":
        if not user.can("passports.approve"):
            raise HTTPException(403, "errors.forbidden")
        tp.approved_by, tp.approved_at = user.username, utcnow()
    tp.status = new
    audit(db, user, "typical_status", "typical", tid, {"status": new})
    db.commit()
    return _tp_out(tp)


@router.post("/typical/{tid}/attachment")
async def typical_attachment(tid: int, file: UploadFile = File(...), db: Session = Depends(get_db),
                             user: CurrentUser = Depends(EDIT)):
    tp = db.get(TypicalPassport, tid)
    if not tp:
        raise HTTPException(404, "errors.not_found")
    key = storage.put(f"passports/typical/{tid}/{file.filename}", await file.read())
    tp.attachments = list(tp.attachments or []) + [{"name": file.filename, "key": key, "ts": utcnow().isoformat()}]
    audit(db, user, "typical_attach", "typical", tid, {"file": file.filename})
    db.commit()
    return {"ok": True}


@router.get("/typical/{tid}/attachment/{idx}")
def typical_attachment_get(tid: int, idx: int, db: Session = Depends(get_db), _: CurrentUser = Depends(VIEW)):
    tp = db.get(TypicalPassport, tid)
    a = (tp.attachments or [])[idx]
    return Response(storage.get(a["key"]), headers=attachment(f"{a['name']}"))


@router.get("/suggest")
def suggest(working_id: int, chainage: float | None = None, db: Session = Depends(get_db),
            _: CurrentUser = Depends(VIEW)):
    """Подбор типового по типу выработки, сечению и геологии интервала."""
    w = db.get(Working, working_id)
    if not w:
        raise HTTPException(404, "errors.not_found")
    geo = geology_at(db, w, chainage)
    area = (w.section or {}).get("area") or g.section_area(w.section or {})
    out = []
    for tp in db.scalars(select(TypicalPassport).where(TypicalPassport.status == "approved")):
        score = 0.0
        reasons = []
        assigned = tp.assigned or {}
        if working_id in (assigned.get("working_ids") or []):
            score += 5
            reasons.append("assigned_working")
        if any(iv.get("working_id") == working_id and iv.get("ch_from", 0) <= (chainage or 0) <= iv.get("ch_to", 0)
               for iv in assigned.get("intervals") or []):
            score += 6
            reasons.append("assigned_interval")
        if tp.working_type == w.type or w.type in (assigned.get("working_types") or []):
            score += 2
            reasons.append("type")
        if tp.f_min <= float(geo.get("f", 10)) <= tp.f_max:
            score += 2
            reasons.append("f")
        else:
            score -= 2
        if geo.get("water", "dry") in (tp.water or []):
            score += 1
            reasons.append("water")
        else:
            score -= 5
            reasons.append("water_mismatch")
        tarea = (tp.section or {}).get("area", 0)
        score -= abs(tarea - area) / max(area, 1) * 4
        out.append({"id": tp.id, "number": tp.number, "name": tp.name, "score": round(score, 2), "reasons": reasons,
                    "area": tarea})
    out.sort(key=lambda x: -x["score"])
    return {"geology": geo, "area": round(area, 2), "candidates": out}


# ---------------- паспорт на забой ----------------
def _dp_out(dp: DevPassport, db: Session) -> dict:
    d = dp.as_dict()
    w = db.get(Working, dp.working_id) if dp.working_id else None
    d["working_name"] = w.name if w else ""
    return d


@router.get("/dev")
def dev_list(working_id: int | None = None, db: Session = Depends(get_db), _: CurrentUser = Depends(VIEW)):
    q = select(DevPassport).order_by(DevPassport.id.desc())
    if working_id:
        q = q.where(DevPassport.working_id == working_id)
    names = {w.id: w.name for w in db.scalars(select(Working))}
    return [{"id": p.id, "number": p.number, "name": p.name, "status": p.status, "working_id": p.working_id,
             "working_name": names.get(p.working_id), "version": p.version, "indicators": p.indicators,
             "parent_id": p.parent_id, "updated_at": p.updated_at.isoformat() if p.updated_at else None}
            for p in db.scalars(q.limit(300))]


@router.get("/dev/{pid}")
def dev_get(pid: int, db: Session = Depends(get_db), _: CurrentUser = Depends(VIEW)):
    dp = db.get(DevPassport, pid)
    if not dp:
        raise HTTPException(404, "errors.not_found")
    return _dp_out(dp, db)


@router.post("/dev")
def dev_create(body: dict, db: Session = Depends(get_db), user: CurrentUser = Depends(EDIT)):
    """Новый паспорт на забой: из типового (typical_id) или по исходным данным."""
    w = db.get(Working, int(body["working_id"])) if body.get("working_id") else None
    face = db.scalar(select(Face).where(Face.working_id == w.id)) if w else None
    ch = body.get("chainage", face.chainage if face else 0)
    base = {}
    tp = None
    if body.get("typical_id"):
        tp = db.get(TypicalPassport, int(body["typical_id"]))
        base = copy.deepcopy(tp.input)
        base.pop("rock", None)
        base.pop("section", None)
    base.update(body.get("input") or {})
    inp = build_input(db, base, w, ch)
    res = compute(inp)
    n = len(db.scalars(select(DevPassport.id).where(DevPassport.working_id == (w.id if w else None))).all()) + 1
    dp = DevPassport(working_id=w.id if w else None, number=body.get("number") or f"П-{w.id if w else 0}-{n}",
                     name=body.get("name") or (f"{w.name}" if w else "Паспорт"), status="draft",
                     typical_id=tp.id if tp else None, input=inp, design=res, indicators=res["indicators"],
                     signatures={"made": user.full_name or user.username}, created_by=user.username)
    db.add(dp)
    audit(db, user, "dev_create", "dev_passport", dp.number, {"working_id": dp.working_id})
    db.commit()
    return _dp_out(dp, db)


@router.put("/dev/{pid}")
def dev_update(pid: int, body: dict, db: Session = Depends(get_db), user: CurrentUser = Depends(EDIT)):
    """input — пересчет раскладки; holes — сохранение отредактированных шпуров (с пересчетом показателей)."""
    dp = db.get(DevPassport, pid)
    if not dp:
        raise HTTPException(404, "errors.not_found")
    if body.get("input"):
        w = db.get(Working, dp.working_id) if dp.working_id else None
        face = db.scalar(select(Face).where(Face.working_id == dp.working_id)) if w else None
        inp = build_input(db, {**{k: v for k, v in dp.input.items() if k not in ("rock",)}, **body["input"]}, w,
                          face.chainage if face else None)
        if not w:
            inp["rock"] = {**dp.input.get("rock", {}), **body["input"].get("rock_override", {})}
        res = compute(inp)
        dp.input, dp.design, dp.indicators = inp, res, res["indicators"]
    elif body.get("holes") is not None:
        res = copy.deepcopy(dp.design)
        res["holes"] = body["holes"]
        res = evaluate(res)
        dp.design, dp.indicators = res, res["indicators"]
    for k in ("name", "number", "signatures"):
        if k in body:
            setattr(dp, k, body[k])
    dp.version += 1
    if dp.status == "approved":
        dp.status = "draft"
    audit(db, user, "dev_update", "dev_passport", pid, {"version": dp.version})
    db.commit()
    return _dp_out(dp, db)


@router.post("/dev/{pid}/evaluate")
def dev_evaluate(pid: int, body: dict, db: Session = Depends(get_db), _: CurrentUser = Depends(EDIT)):
    """Пересчет «сразу» при перетаскивании шпура в редакторе — без сохранения."""
    dp = db.get(DevPassport, pid)
    if not dp:
        raise HTTPException(404, "errors.not_found")
    res = copy.deepcopy(dp.design)
    res["holes"] = body["holes"]
    return evaluate(res)


@router.post("/dev/{pid}/status")
def dev_status(pid: int, body: dict, db: Session = Depends(get_db), user: CurrentUser = Depends(EDIT)):
    dp = db.get(DevPassport, pid)
    new = body["status"]
    if not dp or new not in STATUS_FLOW.get(dp.status, set()):
        raise HTTPException(400, "errors.bad_transition")
    sig = dict(dp.signatures or {})
    if new == "review":
        sig["checked"] = body.get("checked") or sig.get("checked", "")
    if new == "approved":
        if not user.can("passports.approve"):
            raise HTTPException(403, "errors.forbidden")
        sig["approved"] = user.full_name or user.username
        sig["approved_at"] = utcnow().isoformat()
        face = db.scalar(select(Face).where(Face.working_id == dp.working_id)) if dp.working_id else None
        if face and body.get("attach_to_face", True):
            face.passport_id = dp.id
    dp.status = new
    dp.signatures = sig
    audit(db, user, "dev_status", "dev_passport", pid, {"status": new})
    db.commit()
    return _dp_out(dp, db)


@router.post("/dev/{pid}/copy")
def dev_copy(pid: int, body: dict | None = None, db: Session = Depends(get_db), user: CurrentUser = Depends(EDIT)):
    dp = db.get(DevPassport, pid)
    if not dp:
        raise HTTPException(404, "errors.not_found")
    new = DevPassport(working_id=dp.working_id, number=f"{dp.number}-к", name=(body or {}).get("name") or f"{dp.name} (копия)",
                      status="draft", typical_id=dp.typical_id, parent_id=dp.id, input=copy.deepcopy(dp.input),
                      design=copy.deepcopy(dp.design), indicators=dp.indicators, signatures={"made": user.username},
                      created_by=user.username)
    db.add(new)
    audit(db, user, "dev_copy", "dev_passport", pid)
    db.commit()
    return _dp_out(new, db)


def _mine_date(db: Session) -> tuple[Mine, str]:
    m = active_mine(db)
    return m, to_tz(utcnow(), m.config.get("timezone", "UTC")).strftime("%d.%m.%Y %H:%M")


@router.get("/dev/{pid}/export/{fmt}")
def dev_export(pid: int, fmt: str, lang: str = "ru", db: Session = Depends(get_db), user: CurrentUser = Depends(VIEW)):
    dp = db.get(DevPassport, pid)
    if not dp:
        raise HTTPException(404, "errors.not_found")
    m, date = _mine_date(db)
    w = db.get(Working, dp.working_id) if dp.working_id else None
    fname = f"passport_{dp.number}".replace("/", "_")
    audit(db, user, "dev_export", "dev_passport", pid, {"fmt": fmt, "lang": lang}, commit=True)
    if fmt == "pdf":
        from core.pdf import passport_pdf

        data = passport_pdf(dp.as_dict(), dp.design, lambda k: i18n.t(k, lang),
                            {"mine": m.name, "working": w.name if w else "", "number": dp.number, "date": date,
                             "signatures": dp.signatures})
        return Response(data, media_type="application/pdf", headers=attachment(f"{fname}_{lang}.pdf"))
    if fmt == "dxf":
        return Response(exporters.passport_dxf(dp.design, f"{dp.number} {w.name if w else ''}"), media_type="application/dxf",
                        headers=attachment(f"{fname}.dxf"))
    if fmt == "csv":
        return Response(passport.holes_csv(dp.design), media_type="text/csv",
                        headers=attachment(f"{fname}_holes.csv"))
    raise HTTPException(400, "errors.unsupported_format")
