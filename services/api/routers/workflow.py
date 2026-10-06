"""Рабочий процесс забоя: статусы и переходы по ролям, отчёт буровой, пересчёт паспорта и замедлений по факту,
журнал заряжания, скан, анализ. Проходка (dev) и очистной блок (stope)."""
from __future__ import annotations

import copy
import math

import httpx
import numpy as np
from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from common import storage
from common.bus import publish
from common.db import get_db
from common.models import (
    Analysis,
    Assignment,
    ChargeLog,
    DevPassport,
    DrillReport,
    Face,
    FaceEvent,
    Machine,
    PassportRecalc,
    Person,
    RingDesign,
    Scan,
    Stope,
    Working,
)
from common.permissions import DEV_FLOW, STOPE_FLOW, TRANSITION_PERM
from common.settings import get_settings
from common.timeutil import shift_config, to_tz, utcnow
from common.web import attachment
from core import analysis as an
from core import geometry as g
from core import importers, passport, rings, scans

from ..deps import CurrentUser, audit, get_current_user, require
from ..svc import active_mine, analyzer, calc, economics, geology_at

router = APIRouter(prefix="/api/workflow", tags=["workflow"])
VIEW = require("dispatch.view", "workings.view")


def flow(face: Face) -> list[str]:
    return DEV_FLOW if face.kind == "dev" else STOPE_FLOW


def next_statuses(face: Face) -> list[str]:
    fl = flow(face)
    if face.status in ("done",):
        return []
    if face.status in ("charged", "wait_blast"):  # взрыв в окне ВР; окно прошло — «Ждёт ВР»
        return ["blasted", "wait_blast"] if face.status == "charged" else ["blasted"]
    i = fl.index(face.status) if face.status in fl else -1
    if i == len(fl) - 1:
        return ["ready"]
    return [fl[i + 1]]


def blast_window_check(db: Session, f: Face, body: dict, user: CurrentUser) -> str:
    """«Взорван» ставится только внутри окна ВР. Вне окна — только администратор с обязательной причиной
    (пишется в журнал забоя и аудит). Возвращает комментарий к событию."""
    from core import shifts as sh

    cfg = active_mine(db).config
    tz = cfg.get("timezone", "UTC")
    sc = shift_config(cfg)
    now = utcnow()
    if sh.window_at(sc, now, tz):
        return body.get("comment", "")
    reason = (body.get("override_reason") or "").strip()
    if user.can("users.manage") and not user.service and reason:
        audit(db, user, "blast_outside_window", "face", f.id, {"reason": reason, "cycle": f.cycle_no})
        return f"ВР вне окна: {reason}"
    nxt = sh.next_window(sc, now, tz)
    raise HTTPException(400, {"code": "errors.blast_outside_window" if not user.can("users.manage") or user.service
                              else "errors.blast_override_reason",
                              "params": {"next": to_tz(nxt["start"], tz).strftime("%H:%M") if nxt else "—",
                                         "next_date": to_tz(nxt["start"], tz).strftime("%d.%m") if nxt else ""}})


def _face_out(db: Session, f: Face, tz: str, user_tz: str) -> dict:
    d = f.as_dict()
    w = db.get(Working, f.working_id) if f.working_id else None
    s = db.get(Stope, f.stope_id) if f.stope_id else None
    d["working"] = {"id": w.id, "name": w.name, "level": w.level, "type": w.type,
                    "length": round(g.axis_length(w.axis), 1)} if w else None
    d["stope"] = {"id": s.id, "name": s.name, "level_bottom": s.level_bottom} if s else None
    d["level"] = w.level if w else (s.level_bottom if s else None)
    since = f.status_since
    d["since_mine"] = to_tz(since, tz).strftime("%d.%m %H:%M") if since else None
    d["since_user"] = to_tz(since, user_tz).strftime("%d.%m %H:%M") if since else None
    d["chainage_label"] = g.format_chainage(f.chainage)
    return d


@router.get("/faces")
def faces(kind: str | None = None, status: str | None = None, level: float | None = None, db: Session = Depends(get_db),
          user: CurrentUser = Depends(VIEW)):
    m = active_mine(db)
    tz = m.config.get("timezone", "UTC")
    q = select(Face).where(Face.mine_id == m.id).order_by(Face.kind, Face.priority, Face.id)
    if kind:
        q = q.where(Face.kind == kind)
    if status:
        q = q.where(Face.status == status)
    active = {a.face_id: a for a in db.scalars(select(Assignment).where(Assignment.active.is_(True)))}
    people = {p.id: p.full_name for p in db.scalars(select(Person))}
    machines = {x.id: x.label for x in db.scalars(select(Machine))}
    out = []
    for f in db.scalars(q):
        d = _face_out(db, f, tz, user.tz)
        if level is not None and d["level"] != level:
            continue
        a = active.get(f.id)
        d["assignment"] = {"person": people.get(a.person_id), "machine": machines.get(a.machine_id),
                           "work_type": a.work_type} if a else None
        d["next"] = next_statuses(f)
        out.append(d)
    return out


@router.get("/faces/{fid}")
def face_detail(fid: int, db: Session = Depends(get_db), user: CurrentUser = Depends(VIEW)):
    f = db.get(Face, fid)
    if not f:
        raise HTTPException(404, "errors.not_found")
    m = active_mine(db)
    tz = m.config.get("timezone", "UTC")
    d = _face_out(db, f, tz, user.tz)
    d["events"] = [{**e.as_dict(), "ts_mine": to_tz(e.ts, tz).strftime("%d.%m.%Y %H:%M"),
                    "ts_user": to_tz(e.ts, user.tz).strftime("%d.%m.%Y %H:%M")}
                   for e in db.scalars(select(FaceEvent).where(FaceEvent.face_id == fid).order_by(FaceEvent.id.desc()).limit(200))]
    cyc = f.cycle_no

    def last(model):
        return db.scalar(select(model).where(model.face_id == fid, model.cycle_no == cyc).order_by(model.id.desc()))

    for key, model in (("drill_report", DrillReport), ("recalc", PassportRecalc), ("charge_log", ChargeLog),
                       ("scan", Scan), ("analysis", Analysis)):
        row = last(model)
        d[key] = row.as_dict() if row else None
    if f.passport_id:
        dp = db.get(DevPassport, f.passport_id)
        d["passport"] = {"id": dp.id, "number": dp.number, "status": dp.status, "indicators": dp.indicators,
                         "design": dp.design} if dp else None
    if f.ring_design_id:
        rd = db.get(RingDesign, f.ring_design_id)
        d["rings"] = {"id": rd.id, "name": rd.name, "indicators": rd.indicators, "design": rd.design} if rd else None
    nxt = next_statuses(f)
    d["next"] = [{"status": s, "allowed": user.can(TRANSITION_PERM.get(s, "workflow.transition"))} for s in nxt]
    d["history"] = [a.as_dict() for a in db.scalars(select(Analysis).where(Analysis.face_id == fid)
                                                   .order_by(Analysis.id.desc()).limit(30))]
    return d


def _set_status(db: Session, f: Face, to: str, user: CurrentUser, comment: str = "") -> None:
    db.add(FaceEvent(face_id=f.id, cycle_no=f.cycle_no, from_status=f.status, to_status=to, username=user.username,
                     comment=comment))
    frm = f.status
    f.status, f.status_since = to, utcnow()
    db.flush()
    publish("dm.face.status", "face_status", {"face": f.name, "kind": f.kind, "from": frm, "status": to,
                                              "username": user.username, "cycle": f.cycle_no})


@router.post("/faces/{fid}/transition")
def transition(fid: int, body: dict, db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_user)):
    f = db.get(Face, fid)
    if not f:
        raise HTTPException(404, "errors.not_found")
    to = body["to"]
    if to not in next_statuses(f):
        raise HTTPException(400, {"code": "errors.bad_transition", "params": {"from": f.status, "to": to}})
    if not user.can(TRANSITION_PERM.get(to, "workflow.transition")):
        raise HTTPException(403, "errors.forbidden")
    cyc = f.cycle_no
    # предпосылки
    if to == "recalculated" and not db.scalar(select(PassportRecalc.id).where(PassportRecalc.face_id == fid,
                                                                               PassportRecalc.cycle_no == cyc)):
        recalc(fid, db, user, auto=True)
    if to == "charged" and not db.scalar(select(ChargeLog.id).where(ChargeLog.face_id == fid, ChargeLog.cycle_no == cyc)):
        raise HTTPException(400, "errors.no_charge_log")
    if to in ("surveyed", "cms") and not db.scalar(select(Scan.id).where(Scan.face_id == fid, Scan.cycle_no == cyc)):
        raise HTTPException(400, "errors.no_scan")
    if to == "analyzed" and not db.scalar(select(Analysis.id).where(Analysis.face_id == fid, Analysis.cycle_no == cyc)):
        analyze(fid, db, user, auto=True)
        db.refresh(f)
        if f.status == "analyzed":
            db.commit()
            return {"status": f.status}
    if to == "ready" and f.status == "analyzed":
        last = db.scalar(select(Analysis).where(Analysis.face_id == fid, Analysis.cycle_no == cyc).order_by(Analysis.id.desc()))
        _set_status(db, f, "ready", user, body.get("comment", ""))
        f.cycle_no += 1
        if f.kind == "dev":
            f.chainage = round(f.chainage + float((last.result if last else {}).get("advance", 0)), 2)
            w = db.get(Working, f.working_id)
            if w and f.chainage >= g.axis_length(w.axis) - 0.5:
                w.status, f.status = "done", "done"
        else:
            s = db.get(Stope, f.stope_id)
            if s:
                s.status = "mined"
            f.status = "done"
        audit(db, user, "face_transition", "face", fid, {"to": "ready", "cycle": f.cycle_no})
        db.commit()
        return {"status": f.status, "cycle_no": f.cycle_no}
    if to == "blasted":
        body = {**body, "comment": blast_window_check(db, f, body, user)}
    if to == "drilling" and f.working_id:
        w = db.get(Working, f.working_id)
        if w and w.status == "planned":
            w.status = "driving"
    _set_status(db, f, to, user, body.get("comment", ""))
    audit(db, user, "face_transition", "face", fid, {"to": to})
    db.commit()
    return {"status": f.status}


# ---------------- отчёт буровой ----------------
def normalize_dev_holes(design: dict, holes: list[dict]) -> list[dict]:
    """Факт по шпурам → координаты устья/конца, отклонение от паспорта (% длины)."""
    by = {h["id"]: h for h in design["holes"]}
    cc = passport.contour_centroid(design)
    depth = float(design["input"].get("hole_depth", 3.8))
    out = []
    for a in holes:
        d = by.get(int(a["id"]))
        if not d:
            continue
        L = float(a.get("length") or d.get("length", depth))
        drilled = bool(a.get("drilled", True))
        dtx, dty = passport.design_toe(d, cc, depth)
        cx = a.get("collar_x") if a.get("collar_x") is not None else d["x"]
        cy = a.get("collar_y") if a.get("collar_y") is not None else d["y"]
        tx = a.get("toe_x") if a.get("toe_x") is not None else dtx + (cx - d["x"])
        ty = a.get("toe_y") if a.get("toe_y") is not None else dty + (cy - d["y"])
        dev_m = math.hypot(tx - dtx, ty - dty)
        out.append({"id": d["id"], "type": d["type"], "collar_x": cx, "collar_y": cy, "toe_x": tx, "toe_y": ty,
                    "length": L, "design_length": d.get("length", depth), "drilled": drilled,
                    "deviation_m": round(dev_m, 3), "deviation_pct": round(dev_m / max(L, 0.1) * 100, 2),
                    "length_dev_pct": round((L - d.get("length", depth)) / d.get("length", depth) * 100, 1)})
    seen = {o["id"] for o in out}
    for d in design["holes"]:
        if d["id"] not in seen and d["type"] != "empty":
            out.append({"id": d["id"], "type": d["type"], "drilled": False, "length": 0, "deviation_pct": 0})
    return sorted(out, key=lambda h: h["id"])


def _summary(holes: list[dict]) -> dict:
    dr = [h for h in holes if h.get("drilled", True)]
    return {"holes": len(holes), "drilled": len(dr), "not_drilled": len(holes) - len(dr),
            "drill_m": round(sum(h.get("length", 0) for h in dr), 1),
            "mean_deviation_pct": round(float(np.mean([h.get("deviation_pct", 0) for h in dr])), 2) if dr else 0,
            "max_deviation_pct": round(max((h.get("deviation_pct", 0) for h in dr), default=0), 2)}


@router.post("/faces/{fid}/drill-report")
def drill_report(fid: int, body: dict, db: Session = Depends(get_db), user: CurrentUser = Depends(require("workflow.transition"))):
    f = db.get(Face, fid)
    if not f:
        raise HTTPException(404, "errors.not_found")
    holes = body.get("holes") or []
    if f.kind == "dev":
        dp = db.get(DevPassport, f.passport_id) if f.passport_id else None
        if not dp:
            raise HTTPException(400, "errors.no_passport")
        holes = normalize_dev_holes(dp.design, holes)
    rep = DrillReport(face_id=fid, cycle_no=f.cycle_no, machine_id=body.get("machine_id"), person_id=body.get("person_id"),
                      source=body.get("source", "manual"), holes=holes,
                      summary={**_summary(holes), **({"scenario": body["scenario"]} if body.get("scenario") else {})},
                      file_key=body.get("file_key", ""))
    db.add(rep)
    if f.status in ("ready", "drilling"):
        if f.status == "ready":
            _set_status(db, f, "drilling", user, "auto")
        _set_status(db, f, "drilled", user, body.get("comment", "drill report"))
    audit(db, user, "drill_report", "face", fid, {"source": rep.source, **rep.summary})
    db.commit()
    mc = db.get(Machine, rep.machine_id) if rep.machine_id else None
    pr = db.get(Person, rep.person_id) if rep.person_id else None
    for h in holes:
        if h.get("drilled", True):
            publish("dm.drill.hole", "drill_hole", {"machine": mc.label if mc else "", "machine_type": mc.type if mc else "",
                                                    "operator": pr.full_name if pr else "", "face": f.name, "kind": f.kind,
                                                    "hole": str(h.get("id")), "design_length": h.get("design_length", 0),
                                                    "length": h.get("length", 0), "deviation_pct": h.get("deviation_pct", 0)})
    return rep.as_dict()


@router.post("/faces/{fid}/drill-report/file")
async def drill_report_file(fid: int, file: UploadFile = File(...), machine_id: int | None = Form(None),
                            person_id: int | None = Form(None), db: Session = Depends(get_db),
                            user: CurrentUser = Depends(require("workflow.transition"))):
    """Файл со станка или с флешки: CSV или IREDES XML."""
    data = await file.read()
    parsed = importers.parse(file.filename, data)
    if parsed.get("kind") != "drill_log":
        raise HTTPException(400, "errors.not_drill_log")
    key = storage.put(f"drill_logs/{fid}/{file.filename}", data)
    holes = parsed["holes"]
    mc = None
    if not machine_id and parsed.get("meta", {}).get("EquipmentId"):
        eq = parsed["meta"]["EquipmentId"]  # в логе станка — номер или название машины
        mc = db.scalar(select(Machine).where(Machine.number == eq)) or db.scalar(select(Machine).where(Machine.name == eq))
    return drill_report(fid, {"holes": holes, "machine_id": machine_id or (mc.id if mc else None), "person_id": person_id,
                              "source": "file", "file_key": key}, db, user)


# ---------------- пересчёт по факту ----------------
@router.post("/faces/{fid}/recalc")
def recalc(fid: int, db: Session = Depends(get_db), user: CurrentUser = Depends(require("recalc.edit")), auto: bool = False):
    f = db.get(Face, fid)
    rep = db.scalar(select(DrillReport).where(DrillReport.face_id == fid, DrillReport.cycle_no == f.cycle_no)
                    .order_by(DrillReport.id.desc())) if f else None
    if not f or not rep:
        raise HTTPException(400, "errors.no_drill_report")
    if f.kind == "dev":
        dp = db.get(DevPassport, f.passport_id)
        res = calc("/calc/passport/recalc", {"result": dp.design, "actual": rep.holes},
                   lambda: passport.recalc_actual(dp.design, rep.holes))
        pid = dp.id
    else:
        rd = db.get(RingDesign, f.ring_design_id)
        res = calc("/calc/rings/recalc", {"result": rd.design, "actual": rep.holes},
                   lambda: rings.recalc_actual(rd.design, rep.holes))
        pid = rd.id
    rc = PassportRecalc(face_id=fid, cycle_no=f.cycle_no, passport_id=pid, result=res, created_by=user.username)
    db.add(rc)
    if not auto and f.status == "drilled":
        _set_status(db, f, "recalculated", user, "recalc")
    audit(db, user, "recalc", "face", fid, res.get("recalc", {}))
    db.commit()
    return rc.as_dict()


@router.get("/faces/{fid}/edd.csv")
def edd_csv(fid: int, db: Session = Depends(get_db), user: CurrentUser = Depends(require("recalc.edit", "workflow.blast"))):
    """Файл программирования ЭДД (общий формат; шаблон производителя — в настройках рудника edd_template)."""
    f = db.get(Face, fid)
    rc = db.scalar(select(PassportRecalc).where(PassportRecalc.face_id == fid, PassportRecalc.cycle_no == f.cycle_no)
                   .order_by(PassportRecalc.id.desc())) if f else None
    if not rc:
        raise HTTPException(400, "errors.no_recalc")
    tpl = active_mine(db).config.get("edd_template")
    if f.kind == "dev":
        data = passport.edd_program_csv(rc.result, tpl)
    else:
        rows = ["ring;hole;delay_ms"]
        for r in rc.result["rings"]:
            rows += [f"{r['no']};{h['id']};{h.get('delay_ms', 0)}" for h in r["holes"] if h.get("status") != "blocked"]
        data = "\n".join(rows) + "\n"
    audit(db, user, "edd_export", "face", fid, commit=True)
    return Response(data, media_type="text/csv",
                    headers=attachment(f"edd_{f.name}_c{f.cycle_no}.csv"))


# ---------------- заряжание ----------------
@router.post("/faces/{fid}/charge-log")
def charge_log(fid: int, body: dict, db: Session = Depends(get_db), user: CurrentUser = Depends(require("workflow.blast"))):
    f = db.get(Face, fid)
    if not f:
        raise HTTPException(404, "errors.not_found")
    holes = body.get("holes") or []
    rc = db.scalar(select(PassportRecalc).where(PassportRecalc.face_id == fid, PassportRecalc.cycle_no == f.cycle_no)
                   .order_by(PassportRecalc.id.desc()))
    plan = float((rc.result if rc else {}).get("indicators", {}).get("explosive_kg", 0))
    fact = sum(float(h.get("kg", 0)) for h in holes)
    summary = {"holes": len(holes), "charged": sum(1 for h in holes if h.get("status", "charged") == "charged"),
               "misfires": sum(1 for h in holes if h.get("status") == "misfire"),
               "not_charged": sum(1 for h in holes if h.get("status") == "not_charged"),
               "plan_kg": round(plan, 1), "fact_kg": round(fact, 1),
               "over_pct": round((fact - plan) / plan * 100, 1) if plan else 0}
    cl = ChargeLog(face_id=fid, cycle_no=f.cycle_no, holes=holes, summary=summary, created_by=user.username)
    db.add(cl)
    if f.status == "accepted" and body.get("complete", True):
        _set_status(db, f, "charged", user, "charge log")
    audit(db, user, "charge_log", "face", fid, summary)
    db.commit()
    publish("dm.charge", "charge", {"face": f.name, "kind": f.kind, "plan_kg": plan, "fact_kg": fact,
                                    "misfires": summary["misfires"]})
    return cl.as_dict()


# ---------------- скан ----------------
def _scan_context(db: Session, f: Face) -> dict:
    if f.kind == "dev":
        w = db.get(Working, f.working_id)
        return {"axis": w.axis, "ch_from": max(f.chainage - 1.0, 0), "ch_to": f.chainage + 6}
    s = db.get(Stope, f.stope_id)
    return {"stope": {"id": s.id, "geometry": s.geometry, "level_bottom": s.level_bottom, "level_top": s.level_top}}


@router.post("/faces/{fid}/scan")
def scan_json(fid: int, body: dict, db: Session = Depends(get_db), user: CurrentUser = Depends(require("workflow.transition"))):
    """Скан в компактном виде (профили / карты стенок) — от эмулятора или внешней программы."""
    f = db.get(Face, fid)
    if not f:
        raise HTTPException(404, "errors.not_found")
    sc = Scan(face_id=fid, stope_id=f.stope_id, cycle_no=f.cycle_no, kind="face" if f.kind == "dev" else "cms",
              data=body["data"], file_key=body.get("file_key", ""))
    db.add(sc)
    target = "surveyed" if f.kind == "dev" else "cms"
    if target in next_statuses(f):
        _set_status(db, f, target, user, "scan")
    audit(db, user, "scan", "face", fid, {"kind": sc.kind})
    db.commit()
    return {"id": sc.id}


@router.post("/faces/{fid}/scan/file")
async def scan_file(fid: int, file: UploadFile = File(...), db: Session = Depends(get_db),
                    user: CurrentUser = Depends(require("workflow.transition"))):
    """Облако точек (LAS/LAZ/E57/PLY/XYZ) → профили забоя или карты стенок камеры (сервис importer)."""
    f = db.get(Face, fid)
    if not f:
        raise HTTPException(404, "errors.not_found")
    raw = await file.read()
    key = storage.put(f"scans/{fid}/{file.filename}", raw)
    ctx = _scan_context(db, f)
    s = get_settings()
    data = None
    if not s.db_url.startswith("sqlite"):
        try:
            import json

            r = httpx.post(s.importer_url + "/import/scan", files={"file": (file.filename, raw)},
                           data={"context": json.dumps(ctx), "kind": f.kind}, timeout=300)
            if r.status_code == 200:
                data = r.json()
        except httpx.HTTPError:
            data = None
    if data is None:
        pts = importers.parse(file.filename, raw)["points"]
        if f.kind == "dev":
            profs = scans.profiles_from_points(np.asarray(pts), ctx["axis"], ctx["ch_from"], ctx["ch_to"])
            data = {"kind": "face", "profiles": profs, "advance": 0}
        else:
            data = scans.cms_from_points(np.asarray(pts), ctx["stope"])
    if f.kind == "dev" and not data.get("advance"):
        rc = db.scalar(select(DrillReport).where(DrillReport.face_id == fid, DrillReport.cycle_no == f.cycle_no))
        if data.get("profiles"):
            data["advance"] = round(max(p["ch"] for p in data["profiles"]) - f.chainage, 2) if rc else 0
    return scan_json(fid, {"data": data, "file_key": key}, db, user)


# ---------------- анализ ----------------
@router.post("/faces/{fid}/analyze")
def analyze(fid: int, db: Session = Depends(get_db), user: CurrentUser = Depends(require("recalc.edit")), auto: bool = False):
    f = db.get(Face, fid)
    if not f:
        raise HTTPException(404, "errors.not_found")
    cyc = f.cycle_no

    def last(model):
        return db.scalar(select(model).where(model.face_id == fid, model.cycle_no == cyc).order_by(model.id.desc()))

    sc, dr, cl, rc = last(Scan), last(DrillReport), last(ChargeLog), last(PassportRecalc)
    if not sc:
        raise HTTPException(400, "errors.no_scan")
    m = active_mine(db)
    econ = economics(db, m)
    obs = (sc.data or {}).get("observations") or {}
    if f.kind == "dev":
        w = db.get(Working, f.working_id)
        geo = _with_obs(geology_at(db, w, f.chainage), obs)
        dp = db.get(DevPassport, f.passport_id)
        design = rc.result if rc else dp.design
        design = {**design, "holes": dp.design["holes"]} if rc else design
        payload = {"design": design, "scan": sc.data, "drill": dr.as_dict() if dr else None,
                   "charge": cl.as_dict() if cl else None, "geology": geo, "economics": econ}
        res = analyzer("/analyze/dev", payload, lambda: an.analyze_dev(design, sc.data, payload["drill"],
                                                                       payload["charge"], geo, econ))
    else:
        s = db.get(Stope, f.stope_id)
        geo = _with_obs(geology_at(db, stope=s), obs)
        geo.update({"ore_density": geo.get("density", 2.9), "waste_density": m.config.get("densities", {}).get("waste", 2.7)})
        rd = db.get(RingDesign, f.ring_design_id)
        sd = {"id": s.id, "geometry": s.geometry, "level_bottom": s.level_bottom, "level_top": s.level_top,
              "grades": s.grades}
        design = rc.result if rc else rd.design
        payload = {"stope": sd, "cms": sc.data, "design": design, "drill": dr.as_dict() if dr else None,
                   "charge": cl.as_dict() if cl else None, "geology": geo, "economics": econ}
        res = analyzer("/analyze/stope", payload, lambda: an.analyze_stope(sd, sc.data, design, payload["drill"],
                                                                           payload["charge"], geo, econ))
    scenario = (sc.data or {}).get("scenario") or {}
    a = Analysis(face_id=fid, stope_id=f.stope_id, cycle_no=cyc, kind=f.kind, result=res,
                 causes={"primary": res.get("primary_cause"), "shares": res.get("causes"), "groups": res.get("groups")},
                 scenario=scenario)
    db.add(a)
    if "analyzed" in next_statuses(f):
        _set_status(db, f, "analyzed", user, "analysis")
    audit(db, user, "analyze", "face", fid, {"primary": res.get("primary_cause")})
    db.commit()
    _publish_analysis(db, f, res, dr)
    return a.as_dict()


def _with_obs(geo: dict, obs: dict) -> dict:
    """Наблюдения при съёмке (приток воды, кливаж, вывалы, отслоение висячего бока) дополняют геологию интервала."""
    geo = dict(geo)
    for k, v in obs.items():
        if k == "faults":
            geo["faults"] = list(geo.get("faults") or []) + list(v)
        else:
            geo[k] = v
    return geo


def _publish_analysis(db: Session, f: Face, res: dict, dr: DrillReport | None) -> None:
    mc = db.get(Machine, dr.machine_id) if dr and dr.machine_id else None
    pr = db.get(Person, dr.person_id) if dr and dr.person_id else None
    if f.kind == "dev":
        w = db.get(Working, f.working_id)
        publish("dm.cycle", "cycle", {"face": f.name, "working": w.name if w else "", "level": w.level if w else 0,
                                      "cycle": f.cycle_no, "machine": mc.label if mc else "",
                                      "operator": pr.full_name if pr else "", **{k: res.get(k, 0) for k in (
                                          "advance", "design_advance", "kish", "overbreak_pct", "extra_m3", "extra_t",
                                          "extra_cost", "explosive_plan_kg", "explosive_fact_kg", "half_cast_pct")},
                                      "cause": res.get("primary_cause", "")})
    else:
        s = db.get(Stope, f.stope_id)
        publish("dm.stope", "stope", {"stope": s.name, "level": s.level_bottom, **{k: res.get(k, 0) for k in (
            "blasted_t", "dilution_t", "dilution_pct", "loss_t", "loss_pct", "elos_hw", "elos_fw", "result_usd",
            "explosive_plan_kg", "explosive_fact_kg")}, "cause": res.get("primary_cause", "")})


@router.get("/analyses")
def analyses(limit: int = 200, kind: str | None = None, db: Session = Depends(get_db), _: CurrentUser = Depends(VIEW)):
    q = select(Analysis).order_by(Analysis.id.desc()).limit(limit)
    if kind:
        q = q.where(Analysis.kind == kind)
    faces = {f.id: f.name for f in db.scalars(select(Face))}
    return [{**a.as_dict(), "face_name": faces.get(a.face_id)} for a in db.scalars(q)]


@router.get("/scenario-check")
def scenario_check(db: Session = Depends(get_db), _: CurrentUser = Depends(VIEW)):
    """Сверка анализатора с эталонами эмулятора: доля правильно определённых причин."""
    rows = [a for a in db.scalars(select(Analysis).order_by(Analysis.id.desc()).limit(500)) if (a.scenario or {}).get("expected")]
    ok = sum(1 for a in rows if a.causes.get("primary") == a.scenario["expected"])
    by: dict[str, dict] = {}
    for a in rows:
        e = a.scenario["expected"]
        b = by.setdefault(e, {"total": 0, "ok": 0})
        b["total"] += 1
        b["ok"] += int(a.causes.get("primary") == e)
    return {"total": len(rows), "correct": ok, "accuracy": round(ok / len(rows), 3) if rows else None, "by_cause": by}


def copy_design(d: dict) -> dict:
    return copy.deepcopy(d)
