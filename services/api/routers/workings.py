"""Планируемые выработки: список, ручное добавление, мастер «Новый горизонт», подэтажи, замена планом проектировщиков."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from common.bus import publish
from common.db import get_db
from common.models import DevPassport, Face, ImportJob, Stope, Working
from core import geometry as g
from core import importers, planning

from ..deps import CurrentUser, audit, require
from ..svc import active_mine, geology_at, ramp_axis

router = APIRouter(prefix="/api/workings", tags=["workings"])
VIEW = require("workings.view")
EDIT = require("workings.edit")


def _out(w: Working, light: bool = False) -> dict:
    d = w.as_dict()
    d.update(planning.describe(d))
    d["chainage_label"] = g.format_chainage(planning.describe(d)["length"])
    if light:
        d.pop("axis")
    return d


@router.get("")
def list_workings(level: float | None = None, type: str | None = None, status: str | None = None,
                  db: Session = Depends(get_db), _: CurrentUser = Depends(VIEW)):
    m = active_mine(db)
    q = select(Working).where(Working.mine_id == m.id).order_by(Working.level.desc().nulls_first(), Working.type,
                                                                 Working.seq, Working.id)
    if level is not None:
        q = q.where(Working.level == level)
    if type:
        q = q.where(Working.type == type)
    if status:
        q = q.where(Working.status == status)
    return [_out(w, light=True) for w in db.scalars(q)]


@router.get("/{wid}")
def get_working(wid: int, db: Session = Depends(get_db), _: CurrentUser = Depends(VIEW)):
    w = db.get(Working, wid)
    if not w:
        raise HTTPException(404, "errors.not_found")
    d = _out(w)
    L = planning.describe(d)["length"]
    d["geology_profile"] = [{"ch": ch, **{k: v for k, v in geology_at(db, w, ch).items() if k in
                                          ("f", "fracture_cat", "water", "rock_name", "priority", "cleavage")}}
                            for ch in [round(x, 1) for x in [i * 10.0 for i in range(int(L // 10) + 1)]]]
    d["faces"] = [f.as_dict() for f in db.scalars(select(Face).where(Face.working_id == wid))]
    d["passports"] = [{"id": p.id, "number": p.number, "status": p.status}
                      for p in db.scalars(select(DevPassport).where(DevPassport.working_id == wid))]
    return d


@router.post("")
def create_manual(body: dict, db: Session = Depends(get_db), user: CurrentUser = Depends(EDIT)):
    m = active_mine(db)
    w = planning.manual_working(body)
    row = Working(mine_id=m.id, name=w["name"], type=w["type"], level=w["level"], status=w["status"], source="system",
                  axis=w["axis"], section=w["section"])
    db.add(row)
    audit(db, user, "working_create", "working", w["name"], {"manual": True})
    db.commit()
    return _out(row)


@router.put("/{wid}")
def update_working(wid: int, body: dict, db: Session = Depends(get_db), user: CurrentUser = Depends(EDIT)):
    w = db.get(Working, wid)
    if not w:
        raise HTTPException(404, "errors.not_found")
    old_status = w.status
    for k in ("name", "type", "level", "status", "axis", "typical_passport_id", "direction"):
        if k in body:
            setattr(w, k, body[k])
    if "section" in body:
        w.section = g.section_info(body["section"])
    if body.get("status") and body["status"] not in planning.STATUSES:
        raise HTTPException(400, "errors.bad_status")
    if w.status == "driving" and old_status != "driving" and not db.scalar(select(Face).where(Face.working_id == w.id)):
        db.add(Face(mine_id=w.mine_id, kind="dev", working_id=w.id, name=w.name, status="ready", chainage=0))
    audit(db, user, "working_update", "working", wid, {k: body[k] for k in body if k != "axis"})
    db.commit()
    if old_status != w.status:
        publish("dm.working.status", "working_status", {"working": w.name, "from": old_status, "to": w.status})
    return _out(w)


@router.delete("/{wid}")
def delete_working(wid: int, db: Session = Depends(get_db), user: CurrentUser = Depends(EDIT)):
    w = db.get(Working, wid)
    if not w:
        raise HTTPException(404, "errors.not_found")
    if w.status != "planned":
        raise HTTPException(400, "errors.only_planned_delete")
    db.delete(w)
    audit(db, user, "working_delete", "working", wid, {"name": w.name})
    db.commit()
    return {"ok": True}


def _save(db: Session, mine_id: int, items: list[dict]) -> list[int]:
    ids = []
    for w in items:
        row = Working(mine_id=mine_id, name=w["name"], type=w["type"], level=w["level"], status="planned",
                      source="system", axis=w["axis"], section=w["section"], direction=w.get("direction", ""),
                      seq=w.get("seq"), attach_chainage=w.get("attach_chainage"))
        db.add(row)
        db.flush()
        ids.append(row.id)
    return ids


@router.post("/wizard/level")
def wizard_level(body: dict, db: Session = Depends(get_db), user: CurrentUser = Depends(EDIT)):
    """Мастер «Новый горизонт». preview=true — только расчёт для показа; иначе сохранение."""
    m = active_mine(db)
    lvl = float(body["level"])
    exists = db.scalar(select(Working).where(Working.mine_id == m.id, Working.level == lvl, Working.type == "access"))
    attach = body.get("attach") or {}
    axis = ramp_axis(db, m.id)
    if attach.get("working_id"):
        base = db.get(Working, int(attach["working_id"]))
        axis = base.axis if base else axis
    try:
        items = planning.new_level(m.config, axis, body, body.get("lang") or m.config.get("default_language", "ru"))
    except ValueError as e:
        raise HTTPException(400, f"errors.{e}")
    if body.get("preview", True):
        return {"exists": bool(exists), "items": [{**w, **planning.describe(w)} for w in items]}
    if exists and not body.get("force"):
        raise HTTPException(400, "errors.level_exists")
    ids = _save(db, m.id, items)
    audit(db, user, "wizard_level", "mine", m.id, {"level": lvl, "count": len(ids)})
    db.commit()
    return {"created": len(ids), "ids": ids}


@router.post("/wizard/sublevels")
def wizard_sublevels(body: dict, db: Session = Depends(get_db), user: CurrentUser = Depends(EDIT)):
    m = active_mine(db)
    existing = {round(w.level) for w in db.scalars(select(Working).where(Working.mine_id == m.id,
                                                                          Working.type == "access"))}
    try:
        items = planning.generate_sublevels(m.config, ramp_axis(db, m.id), float(body["level_from"]),
                                            float(body["level_to"]), body, m.config.get("default_language", "ru"),
                                            existing)
    except ValueError as e:
        raise HTTPException(400, f"errors.{e}")
    if body.get("preview", True):
        levels = sorted({w["level"] for w in items}, reverse=True)
        return {"levels": levels, "count": len(items), "items": [{**w, **planning.describe(w)} for w in items]}
    ids = _save(db, m.id, items)
    audit(db, user, "wizard_sublevels", "mine", m.id, {"from": body["level_from"], "to": body["level_to"],
                                                        "count": len(ids)})
    db.commit()
    return {"created": len(ids)}


@router.post("/designer/compare")
def designer_compare(body: dict, db: Session = Depends(get_db), _: CurrentUser = Depends(EDIT)):
    """Сравнение «плана проектировщиков» (загруженный файл) с выработками системы."""
    m = active_mine(db)
    job = db.get(ImportJob, int(body["job_id"]))
    if not job:
        raise HTTPException(404, "errors.not_found")
    plan = importers.polylines_to_workings(job.parsed, body.get("layer_map"), body.get("offset"))
    q = select(Working).where(Working.mine_id == m.id)
    if body.get("only_planned", True):
        q = q.where(Working.source.in_(("system", "designer")))
    system = [w.as_dict() for w in db.scalars(q)]
    levels = {p["level"] for p in plan}
    system = [w for w in system if w["level"] in levels]
    res = planning.compare_plan(system, plan, float(body.get("tol_match", 0.5)), float(body.get("tol_geo", 15)))
    for r in res:
        if r.get("plan"):
            r["plan"] = {k: r["plan"][k] for k in ("name", "type", "level", "axis")}
    counts = {s: sum(1 for r in res if r["status"] == s) for s in ("match", "shifted", "new", "missing")}
    return {"counts": counts, "items": res}


@router.post("/designer/replace")
def designer_replace(body: dict, db: Session = Depends(get_db), user: CurrentUser = Depends(EDIT)):
    """Замена: геометрия из плана, id выработки сохраняется — паспорта, забои и факт остаются привязанными."""
    cmp = designer_compare(body, db, user)
    m = active_mine(db)
    replaced, created = 0, 0
    accept = set(body.get("accept") or ["match", "shifted", "new"])
    for r in cmp["items"]:
        if r["status"] not in accept or r["status"] == "missing":
            continue
        p = r["plan"]
        if r["working_id"]:
            w = db.get(Working, r["working_id"])
            w.props = dict(w.props or {}, system_axis=w.axis, replaced_from_job=body["job_id"], shift_m=r["shift_m"])
            w.axis = p["axis"]
            w.source = "designer"
            w.name = p["name"] if body.get("take_names") else w.name
            replaced += 1
        else:
            sec = planning.default_sections(m.config).get(p["type"], {"shape": "arch", "width": 4.5, "height": 4.5})
            db.add(Working(mine_id=m.id, name=p["name"], type=p["type"], level=p["level"], status="planned",
                           source="designer", axis=p["axis"], section=g.section_info(sec)))
            created += 1
    audit(db, user, "designer_replace", "mine", m.id, {"job": body["job_id"], "replaced": replaced, "created": created})
    db.commit()
    return {"replaced": replaced, "created": created, "counts": cmp["counts"]}


@router.get("/stopes/all")
def stopes(db: Session = Depends(get_db), _: CurrentUser = Depends(VIEW)):
    m = active_mine(db)
    return [s.as_dict() for s in db.scalars(select(Stope).where(Stope.mine_id == m.id).order_by(Stope.level_bottom.desc(),
                                                                                              Stope.id))]
