"""Веера (очистная выемка): проект, экспорт PDF/DXF/CSV; поправочные скважины и окупаемость; итоги камеры."""
from __future__ import annotations

import copy

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from common import i18n
from common.db import get_db
from common.models import Analysis, CorrectionPlan, Explosive, Face, RingDesign, Scan, Stope, Working
from common.timeutil import to_tz, utcnow
from common.web import attachment
from core import exporters, rings

from ..deps import CurrentUser, audit, require
from ..svc import active_mine, calc, economics, explosive_dict, geology_at

router = APIRouter(prefix="/api/rings", tags=["rings"])
VIEW = require("passports.view")
EDIT = require("passports.edit")


def _stope_dict(s: Stope) -> dict:
    return {"id": s.id, "name": s.name, "geometry": s.geometry, "level_bottom": s.level_bottom,
            "level_top": s.level_top, "grades": s.grades}


@router.get("/stopes")
def stopes(db: Session = Depends(get_db), _: CurrentUser = Depends(VIEW)):
    m = active_mine(db)
    designs = {}
    for r in db.scalars(select(RingDesign).order_by(RingDesign.id)):
        designs.setdefault(r.stope_id, []).append({"id": r.id, "name": r.name, "status": r.status})
    faces = {f.stope_id: f for f in db.scalars(select(Face).where(Face.kind == "stope"))}
    drives = {w.id: w.name for w in db.scalars(select(Working).where(Working.type == "xc"))}
    out = []
    for s in db.scalars(select(Stope).where(Stope.mine_id == m.id).order_by(Stope.level_bottom.desc(), Stope.id)):
        d = s.as_dict()
        d["designs"] = designs.get(s.id, [])
        d["drive_name"] = drives.get(s.drive_id)
        f = faces.get(s.id)
        d["face"] = {"id": f.id, "status": f.status} if f else None
        out.append(d)
    return out


@router.get("/stopes/{sid}")
def stope(sid: int, db: Session = Depends(get_db), _: CurrentUser = Depends(VIEW)):
    s = db.get(Stope, sid)
    if not s:
        raise HTTPException(404, "errors.not_found")
    d = s.as_dict()
    d["geology"] = geology_at(db, stope=s)
    d["designs"] = [r.as_dict() for r in db.scalars(select(RingDesign).where(RingDesign.stope_id == sid))]
    d["analyses"] = [a.as_dict() for a in db.scalars(select(Analysis).where(Analysis.stope_id == sid)
                                                     .order_by(Analysis.id.desc()))]
    d["corrections"] = [c.as_dict() for c in db.scalars(select(CorrectionPlan).where(CorrectionPlan.stope_id == sid)
                                                        .order_by(CorrectionPlan.id.desc()))]
    d["scans"] = [{"id": sc.id, "cycle_no": sc.cycle_no, "created_at": sc.created_at.isoformat()}
                  for sc in db.scalars(select(Scan).where(Scan.stope_id == sid).order_by(Scan.id.desc()))]
    return d


def _design(db: Session, s: Stope, body: dict) -> dict:
    inp = copy.deepcopy(body)
    e = db.get(Explosive, int(inp.pop("explosive_id"))) if inp.get("explosive_id") else \
        db.scalar(select(Explosive).where(Explosive.type == "emulsion"))
    inp["explosive"] = explosive_dict(e)
    geo = geology_at(db, stope=s)
    inp["rock"] = {k: geo.get(k) for k in ("f", "density", "water", "fracture_cat")}
    sd = _stope_dict(s)
    res = calc("/calc/rings/design", {"input": inp, "stope": sd}, lambda: rings.design_rings(inp, sd))
    errs = [w for w in res.get("warnings", []) if w["level"] == "error"]
    if errs:
        raise HTTPException(400, {"code": "errors." + errs[0]["code"], "params": errs[0].get("params", {})})
    return res


@router.post("/stopes/{sid}/design")
def design(sid: int, body: dict, db: Session = Depends(get_db), user: CurrentUser = Depends(EDIT)):
    s = db.get(Stope, sid)
    if not s:
        raise HTTPException(404, "errors.not_found")
    res = _design(db, s, body)
    if body.get("preview"):
        return res
    rd = RingDesign(stope_id=sid, name=body.get("name") or f"Веера {s.name}", status="draft", input=res["input"],
                    design=res, indicators=res["indicators"], created_by=user.username)
    db.add(rd)
    audit(db, user, "rings_create", "stope", sid, {"direction": body.get("direction")})
    db.commit()
    return rd.as_dict()


@router.get("/designs/{rid}")
def get_design(rid: int, db: Session = Depends(get_db), _: CurrentUser = Depends(VIEW)):
    rd = db.get(RingDesign, rid)
    if not rd:
        raise HTTPException(404, "errors.not_found")
    d = rd.as_dict()
    s = db.get(Stope, rd.stope_id)
    d["stope"] = _stope_dict(s)
    return d


@router.post("/designs/{rid}/status")
def design_status(rid: int, body: dict, db: Session = Depends(get_db), user: CurrentUser = Depends(EDIT)):
    rd = db.get(RingDesign, rid)
    if not rd:
        raise HTTPException(404, "errors.not_found")
    if body["status"] == "approved":
        if not user.can("passports.approve"):
            raise HTTPException(403, "errors.forbidden")
        f = db.scalar(select(Face).where(Face.stope_id == rd.stope_id))
        if f:
            f.ring_design_id = rd.id
    rd.status = body["status"]
    audit(db, user, "rings_status", "rings", rid, body)
    db.commit()
    return rd.as_dict()


@router.get("/designs/{rid}/export/{fmt}")
def export(rid: int, fmt: str, lang: str = "ru", db: Session = Depends(get_db), user: CurrentUser = Depends(VIEW)):
    rd = db.get(RingDesign, rid)
    if not rd:
        raise HTTPException(404, "errors.not_found")
    s = db.get(Stope, rd.stope_id)
    m = active_mine(db)
    audit(db, user, "rings_export", "rings", rid, {"fmt": fmt}, commit=True)
    if fmt == "pdf":
        from core.pdf import rings_pdf

        date = to_tz(utcnow(), m.config.get("timezone", "UTC")).strftime("%d.%m.%Y %H:%M")
        data = rings_pdf(rd.design, lambda k: i18n.t(k, lang), {"stope": s.name, "mine": m.name, "date": date})
        return Response(data, media_type="application/pdf", headers=attachment(f"rings_{rid}_{lang}.pdf"))
    if fmt == "dxf":
        return Response(exporters.rings_dxf(rd.design, s.name), media_type="application/dxf",
                        headers=attachment(f"rings_{rid}.dxf"))
    if fmt == "csv":
        return Response(rings.holes_csv(rd.design), media_type="text/csv",
                        headers=attachment(f"rings_{rid}_simba.csv"))
    raise HTTPException(400, "errors.unsupported_format")


# ---------------- поправочные скважины ----------------
@router.post("/stopes/{sid}/correction")
def correction(sid: int, body: dict, db: Session = Depends(get_db), user: CurrentUser = Depends(EDIT)):
    """По последнему анализу CMS: зоны недобора → поправочные скважины, тонны/металл, затраты, решение."""
    s = db.get(Stope, sid)
    an = db.scalar(select(Analysis).where(Analysis.stope_id == sid).order_by(Analysis.id.desc()))
    if not s or not an:
        raise HTTPException(400, "errors.no_analysis")
    zones = an.result.get("underbreak_zones") or []
    if not zones:
        raise HTTPException(400, "errors.no_underbreak")
    e = db.get(Explosive, int(body["explosive_id"])) if body.get("explosive_id") else \
        db.scalar(select(Explosive).where(Explosive.type == "emulsion"))
    inp = {"explosive": explosive_dict(e), "hole_diameter": body.get("hole_diameter", 76),
           "density": geology_at(db, stope=s).get("density", 2.9), "drill_rate_mph": body.get("drill_rate_mph", 35)}
    econ = economics(db, active_mine(db))
    sd = _stope_dict(s)
    res = calc("/calc/rings/correction", {"stope": sd, "zones": zones, "input": inp, "economics": econ},
               lambda: rings.correction(sd, zones, inp, econ, s.grades))
    cp = CorrectionPlan(stope_id=sid, scan_id=None, design={"holes": res["holes"], "input": inp},
                        economics={k: v for k, v in res.items() if k != "holes"}, status="proposed")
    db.add(cp)
    audit(db, user, "correction_create", "stope", sid, {"decision": res["decision"], "profit": res["profit_usd"]})
    db.commit()
    return cp.as_dict()


@router.post("/corrections/{cid}/status")
def correction_status(cid: int, body: dict, db: Session = Depends(get_db), user: CurrentUser = Depends(EDIT)):
    cp = db.get(CorrectionPlan, cid)
    if not cp:
        raise HTTPException(404, "errors.not_found")
    cp.status = body["status"]  # accepted / rejected / done
    if body["status"] == "done":
        # после повторного скана: сколько добрано (по сравнению объемов недобора)
        an = db.scalar(select(Analysis).where(Analysis.stope_id == cp.stope_id).order_by(Analysis.id.desc()))
        before = float(cp.economics.get("volume_m3", 0))
        after = sum(float(z["volume_m3"]) for z in (an.result.get("underbreak_zones") or [])) if an else before
        dens = float(cp.design.get("input", {}).get("density", 2.9))
        cp.result = {"recovered_m3": round(max(before - after, 0), 1), "recovered_t": round(max(before - after, 0) * dens, 1),
                     "remaining_m3": round(after, 1), "ts": utcnow().isoformat()}
    audit(db, user, "correction_status", "correction", cid, body)
    db.commit()
    return cp.as_dict()


@router.post("/stopes/{sid}/activate")
def activate(sid: int, body: dict | None = None, db: Session = Depends(get_db), user: CurrentUser = Depends(EDIT)):
    """Ввести камеру в работу: проект вееров по умолчанию (утвержден) и очистной блок в рабочем процессе."""
    s = db.get(Stope, sid)
    if not s:
        raise HTTPException(404, "errors.not_found")
    if db.scalar(select(Face).where(Face.stope_id == sid, Face.status != "done")):
        raise HTTPException(400, "errors.exists")
    params = {"hole_diameter": 89, "direction": "up", "standoff": 0.7, "initiation": "edd", "ring_interval_ms": 75,
              **(body or {})}
    res = _design(db, s, params)
    rd = RingDesign(stope_id=sid, name=f"Веера {s.name}", status="approved", input=res["input"], design=res,
                    indicators=res["indicators"], created_by=user.username)
    db.add(rd)
    db.flush()
    f = Face(mine_id=s.mine_id, kind="stope", stope_id=sid, name=s.name, status="ready", ring_design_id=rd.id, priority=4)
    db.add(f)
    s.status = "active"
    audit(db, user, "stope_activate", "stope", sid)
    db.commit()
    return {"face_id": f.id, "ring_design_id": rd.id}
