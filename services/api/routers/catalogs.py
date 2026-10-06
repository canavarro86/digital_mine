"""Справочники: геология (породы, назначения), ВВ и средства инициирования, флот, персонал и допуски."""
from __future__ import annotations

import mimetypes
from datetime import datetime, timezone
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from common import storage
from common.db import get_db
from common.models import (
    Explosive,
    GeologyAssignment,
    InitiationDevice,
    Machine,
    MachineModel,
    Permit,
    Person,
    Profession,
    RockType,
    Stope,
    Working,
    WorkKind,
)
from common.settings import load_yaml
from core import explosives as exlib

from .. import qualify as q
from ..deps import CurrentUser, audit, require
from ..svc import active_mine, explosive_dict, geology_at, get_setting, set_setting

router = APIRouter(prefix="/api", tags=["catalogs"])


def _crud_update(obj, body: dict, fields) -> None:
    for k in fields:
        if k in body:
            setattr(obj, k, body[k])


# ---------------- геология ----------------
ROCK_FIELDS = ("code", "name", "kind", "f", "ucs", "density", "fracture_cat", "fracture_spacing", "rqd", "rmr", "q",
               "water", "inflow_lpm", "grades", "extra")


@router.get("/geology/meta")
def geology_meta(_: CurrentUser = Depends(require("geology.view"))):
    return load_yaml("rocks.yaml")


@router.get("/geology/rocks")
def rocks(db: Session = Depends(get_db), _: CurrentUser = Depends(require("geology.view"))):
    return [r.as_dict() for r in db.scalars(select(RockType).order_by(RockType.id))]


@router.post("/geology/rocks")
def create_rock(body: dict, db: Session = Depends(get_db), user: CurrentUser = Depends(require("geology.edit"))):
    r = RockType(**{k: body[k] for k in ROCK_FIELDS if k in body})
    db.add(r)
    audit(db, user, "rock_create", "rock", body.get("code"))
    db.commit()
    return r.as_dict()


@router.put("/geology/rocks/{rid}")
def update_rock(rid: int, body: dict, db: Session = Depends(get_db), user: CurrentUser = Depends(require("geology.edit"))):
    r = db.get(RockType, rid)
    if not r:
        raise HTTPException(404, "errors.not_found")
    _crud_update(r, body, ROCK_FIELDS)
    audit(db, user, "rock_update", "rock", rid)
    db.commit()
    return r.as_dict()


@router.get("/geology/assignments")
def assignments(working_id: int | None = None, db: Session = Depends(get_db),
                _: CurrentUser = Depends(require("geology.view"))):
    m = active_mine(db)
    q = select(GeologyAssignment).where(GeologyAssignment.mine_id == m.id)
    if working_id:
        q = q.where(GeologyAssignment.working_id == working_id)
    names = {w.id: w.name for w in db.scalars(select(Working).where(Working.mine_id == m.id))}
    out = []
    for a in db.scalars(q.order_by(GeologyAssignment.id)):
        d = a.as_dict()
        d["working_name"] = names.get(a.working_id)
        out.append(d)
    return out


ASSIGN_FIELDS = ("target", "name", "working_id", "ch_from", "ch_to", "stope_id", "zone", "rock_type_id", "overrides")


@router.post("/geology/assignments")
def create_assignment(body: dict, db: Session = Depends(get_db), user: CurrentUser = Depends(require("geology.edit"))):
    m = active_mine(db)
    if body.get("target") not in ("interval", "working", "zone", "stope", "mine"):
        raise HTTPException(400, "errors.bad_target")
    if body["target"] == "interval" and (body.get("ch_from") is None or body.get("ch_to") is None):
        raise HTTPException(400, "errors.interval_required")
    a = GeologyAssignment(mine_id=m.id, **{k: body[k] for k in ASSIGN_FIELDS if k in body})
    db.add(a)
    audit(db, user, "geology_assign", "geology", body.get("name"), body)
    db.commit()
    return a.as_dict()


@router.put("/geology/assignments/{aid}")
def update_assignment(aid: int, body: dict, db: Session = Depends(get_db),
                      user: CurrentUser = Depends(require("geology.edit"))):
    a = db.get(GeologyAssignment, aid)
    if not a:
        raise HTTPException(404, "errors.not_found")
    _crud_update(a, body, ASSIGN_FIELDS)
    audit(db, user, "geology_update", "geology", aid, body)
    db.commit()
    return a.as_dict()


@router.delete("/geology/assignments/{aid}")
def delete_assignment(aid: int, db: Session = Depends(get_db), user: CurrentUser = Depends(require("geology.edit"))):
    a = db.get(GeologyAssignment, aid)
    if a:
        db.delete(a)
        audit(db, user, "geology_delete", "geology", aid)
        db.commit()
    return {"ok": True}


@router.get("/geology/at")
def geology_point(working_id: int | None = None, chainage: float | None = None, stope_id: int | None = None,
                  db: Session = Depends(get_db), _: CurrentUser = Depends(require("geology.view"))):
    w = db.get(Working, working_id) if working_id else None
    s = db.get(Stope, stope_id) if stope_id else None
    if not w and not s:
        raise HTTPException(400, "errors.target_required")
    return geology_at(db, w, chainage, s)


# ---------------- ВВ ----------------
EXPL_FIELDS = ("code", "name", "manufacturer", "type", "density_min", "density_max", "vod", "rws", "rbs", "heat", "gas",
               "water_resistance", "crit_diameter", "min_diameter", "cart_diameter", "cart_length", "cart_mass", "price")


@router.get("/explosives")
def explosives(db: Session = Depends(get_db), _: CurrentUser = Depends(require("explosives.view"))):
    return [explosive_dict(e) for e in db.scalars(select(Explosive).order_by(Explosive.id))]


@router.post("/explosives")
def create_explosive(body: dict, db: Session = Depends(get_db), user: CurrentUser = Depends(require("explosives.edit"))):
    if body.get("density_min", 0) > body.get("density_max", 0):
        raise HTTPException(400, "errors.density_range")
    e = Explosive(**{k: body[k] for k in EXPL_FIELDS if k in body})
    db.add(e)
    audit(db, user, "explosive_create", "explosive", body.get("code"))
    db.commit()
    return explosive_dict(e)


@router.put("/explosives/{eid}")
def update_explosive(eid: int, body: dict, db: Session = Depends(get_db),
                     user: CurrentUser = Depends(require("explosives.edit"))):
    e = db.get(Explosive, eid)
    if not e:
        raise HTTPException(404, "errors.not_found")
    _crud_update(e, body, EXPL_FIELDS)
    audit(db, user, "explosive_update", "explosive", eid)
    db.commit()
    return explosive_dict(e)


@router.get("/initiation")
def initiation(db: Session = Depends(get_db), _: CurrentUser = Depends(require("explosives.view"))):
    return [d.as_dict() for d in db.scalars(select(InitiationDevice).order_by(InitiationDevice.id))]


@router.post("/initiation")
def create_initiation(body: dict, db: Session = Depends(get_db), user: CurrentUser = Depends(require("explosives.edit"))):
    d = InitiationDevice(**{k: body[k] for k in ("code", "name", "kind", "props", "price") if k in body})
    db.add(d)
    audit(db, user, "initiation_create", "initiation", body.get("code"))
    db.commit()
    return d.as_dict()


@router.put("/initiation/{did}")
def update_initiation(did: int, body: dict, db: Session = Depends(get_db),
                      user: CurrentUser = Depends(require("explosives.edit"))):
    d = db.get(InitiationDevice, did)
    if not d:
        raise HTTPException(404, "errors.not_found")
    _crud_update(d, body, ("code", "name", "kind", "props", "price"))
    audit(db, user, "initiation_update", "initiation", did)
    db.commit()
    return d.as_dict()


@router.post("/explosives/check")
def check_explosive(body: dict, db: Session = Depends(get_db), _: CurrentUser = Depends(require("explosives.view"))):
    """Проверка ВВ на интервал: диаметр не меньше критического, водоустойчивость против обводнённости."""
    e = db.get(Explosive, int(body["explosive_id"]))
    if not e:
        raise HTTPException(404, "errors.not_found")
    water = body.get("water")
    if body.get("working_id"):
        geo = geology_at(db, db.get(Working, int(body["working_id"])), body.get("chainage"))
        water = geo.get("water", water)
    d = float(body.get("diameter", 45))
    issues = exlib.check(explosive_dict(e), d, water or "dry")
    alts = [] if not issues else [{"id": x["id"], "name": x["name"]} for x in
                                  exlib.suggest_for_water([explosive_dict(x) for x in db.scalars(select(Explosive))],
                                                          water or "dry", d)[:3]]
    return {"ok": not any(i["level"] == "error" for i in issues), "water": water, "issues": issues,
            "kg_per_m": round(exlib.kg_per_m(explosive_dict(e), d), 3), "alternatives": alts}


# ---------------- флот: модели ----------------
MODEL_FIELDS = ("manufacturer", "model", "short_name", "type", "params", "verify", "note", "active")


def _check_type(t: str | None) -> None:
    if t not in q.fleet_types():
        raise HTTPException(400, "errors.bad_machine_type")


def _model_out(m: MachineModel, used: dict[int, int]) -> dict:
    d = m.as_dict()
    d["label"] = q.model_label(m)
    d["machines"] = used.get(m.id, 0)
    return d


def _model_usage(db: Session) -> dict[int, int]:
    used: dict[int, int] = {}
    for mc in db.scalars(select(Machine).where(Machine.model_id.is_not(None))):
        used[mc.model_id] = used.get(mc.model_id, 0) + 1
    return used


@router.get("/fleet/meta")
def fleet_meta(_: CurrentUser = Depends(require("fleet.view", "dispatch.view", "staff.view"))):
    """Типы машин и описание параметров (единица, тип поля) для окна «Машина» и справочника моделей."""
    return {"types": q.fleet_types(), "params": q.fleet_params()}


@router.get("/fleet/type-works")
def get_type_works(db: Session = Depends(get_db), _: CurrentUser = Depends(require("fleet.view", "dispatch.view"))):
    """Допустимые виды работ по типам машин: какая машина на какую работу назначается."""
    return q.type_works(db)


@router.put("/fleet/type-works")
def put_type_works(body: dict, db: Session = Depends(get_db), user: CurrentUser = Depends(require("fleet.edit"))):
    types = q.fleet_types()
    known = {w.code for w in db.scalars(select(WorkKind))}
    out = {}
    for t, works in body.items():
        if t not in types:
            raise HTTPException(400, "errors.bad_machine_type")
        bad = [w for w in works or [] if w not in known]
        if bad:
            raise HTTPException(400, {"code": "errors.bad_permit_target", "params": {"target": bad[0]}})
        out[t] = list(dict.fromkeys(works or []))
    set_setting(db, "fleet_type_works", {**q.type_works(db), **out})
    audit(db, user, "fleet_type_works", "fleet", "", out)
    db.commit()
    return q.type_works(db)


@router.get("/fleet/models")
def machine_models(db: Session = Depends(get_db), _: CurrentUser = Depends(require("fleet.view", "staff.view"))):
    used = _model_usage(db)
    return [_model_out(m, used) for m in db.scalars(select(MachineModel).order_by(MachineModel.type, MachineModel.manufacturer,
                                                                                    MachineModel.model))]


@router.post("/fleet/models")
def create_model(body: dict, db: Session = Depends(get_db), user: CurrentUser = Depends(require("fleet.edit"))):
    _check_type(body.get("type"))
    if not (body.get("model") or "").strip():
        raise HTTPException(400, "errors.model_required")
    if db.scalar(select(MachineModel).where(MachineModel.manufacturer == body.get("manufacturer", ""),
                                            MachineModel.model == body["model"])):
        raise HTTPException(400, "errors.exists")
    m = MachineModel(**{k: body[k] for k in MODEL_FIELDS if k in body})
    m.params = {**q.fleet_types()[m.type].get("defaults", {}), **(body.get("params") or {})}
    db.add(m)
    audit(db, user, "model_create", "machine_model", body["model"])
    db.commit()
    return _model_out(m, {})


@router.put("/fleet/models/{mid}")
def update_model(mid: int, body: dict, db: Session = Depends(get_db), user: CurrentUser = Depends(require("fleet.edit"))):
    m = db.get(MachineModel, mid)
    if not m:
        raise HTTPException(404, "errors.not_found")
    if "type" in body and body["type"] != m.type:
        _check_type(body["type"])
        if _model_usage(db).get(mid):
            raise HTTPException(400, "errors.model_in_use")
    _crud_update(m, body, MODEL_FIELDS)
    audit(db, user, "model_update", "machine_model", mid, {k: body[k] for k in body if k in MODEL_FIELDS})
    db.commit()
    return _model_out(m, _model_usage(db))


@router.delete("/fleet/models/{mid}")
def delete_model(mid: int, db: Session = Depends(get_db), user: CurrentUser = Depends(require("fleet.edit"))):
    m = db.get(MachineModel, mid)
    if m:
        if _model_usage(db).get(mid):
            raise HTTPException(400, "errors.model_in_use")
        db.delete(m)
        audit(db, user, "model_delete", "machine_model", mid)
        db.commit()
    return {"ok": True}


# ---------------- флот: машины ----------------
MACHINE_FIELDS = ("number", "name", "type", "model_id", "model", "manufacturer", "year", "params", "status", "engine_hours",
                  "working_id")


@router.get("/fleet/types")
def fleet_types(_: CurrentUser = Depends(require("fleet.view"))):
    return q.fleet_types()


@router.get("/fleet")
def fleet(db: Session = Depends(get_db), user: CurrentUser = Depends(require("fleet.view", "dispatch.view"))):
    names = {w.id: w.name for w in db.scalars(select(Working))}
    models = {m.id: m for m in db.scalars(select(MachineModel))}
    out = []
    for mc in db.scalars(select(Machine).order_by(Machine.type, Machine.id)):
        d = q.machine_dict(mc, models, user.lang)
        d["working_name"] = names.get(mc.working_id)
        out.append(d)
    return out


def _apply_machine(db: Session, mc: Machine, body: dict, mine_id: int) -> None:
    """Модель из справочника задаёт тип и параметры; поля машины переопределяют их (износ, модернизация).
    Без модели — нестандартная установка: тип и параметры вводятся вручную."""
    number = str(body.get("number", mc.number) or "").strip()
    if not number:
        raise HTTPException(400, "errors.number_required")
    dup = db.scalar(select(Machine).where(Machine.mine_id == mine_id, Machine.number == number, Machine.id != (mc.id or 0)))
    if dup:
        raise HTTPException(400, {"code": "errors.machine_number_exists", "params": {"number": number, "machine": dup.label}})
    is_new = mc.id is None
    model_changed = "model_id" in body and body["model_id"] != mc.model_id
    _crud_update(mc, {**body, "number": number}, [f for f in MACHINE_FIELDS if f not in ("params", "type", "model_id")])
    m = db.get(MachineModel, int(body["model_id"])) if body.get("model_id") else None
    if "model_id" in body and body["model_id"] and not m:
        raise HTTPException(400, "errors.not_found")
    if "model_id" in body:
        mc.model_id = m.id if m else None
    elif mc.model_id:
        m = db.get(MachineModel, mc.model_id)
    if m:
        mc.type, mc.manufacturer, mc.model = m.type, m.manufacturer, m.model
    else:
        if "type" in body:
            mc.type = body["type"]
        _check_type(mc.type)
    # параметры: при новой машине или смене модели — от модели (или типа), иначе — текущие; поверх — присланные
    if is_new or model_changed:
        base = dict(m.params) if m else dict(q.fleet_types()[mc.type].get("defaults", {}))
    else:
        base = dict(mc.params or {})
    mc.params = {**base, **(body.get("params") or {})}
    if not (body.get("name") or "").strip() and (is_new or model_changed or not mc.name):
        mc.name = q.auto_name(number, m, q.Labels(db).type_label(mc.type), mc.model)


@router.post("/fleet")
def create_machine(body: dict, db: Session = Depends(get_db), user: CurrentUser = Depends(require("fleet.edit"))):
    mine_id = active_mine(db).id
    mc = Machine(mine_id=mine_id, number="", type=body.get("type") or "", params={})
    _apply_machine(db, mc, body, mine_id)
    db.add(mc)
    audit(db, user, "machine_create", "machine", mc.number, {"name": mc.name, "model_id": mc.model_id})
    db.commit()
    return q.machine_dict(mc, {m.id: m for m in db.scalars(select(MachineModel))}, user.lang)


@router.put("/fleet/{mid}")
def update_machine(mid: int, body: dict, db: Session = Depends(get_db),
                   user: CurrentUser = Depends(require("fleet.edit", "dispatch.edit"))):
    mc = db.get(Machine, mid)
    if not mc:
        raise HTTPException(404, "errors.not_found")
    if user.can("fleet.edit"):
        _apply_machine(db, mc, body, mc.mine_id or active_mine(db).id)
        changed = {k: body[k] for k in body if k in MACHINE_FIELDS}
    else:
        _crud_update(mc, body, ("status",))
        changed = {k: body[k] for k in body if k == "status"}
    audit(db, user, "machine_update", "machine", mid, changed)
    db.commit()
    return q.machine_dict(mc, {m.id: m for m in db.scalars(select(MachineModel))}, user.lang)


# ---------------- персонал: справочники ----------------
def _title_body(body: dict, lang: str) -> dict:
    t = body.get("title")
    if isinstance(t, str):
        t = {lang: t}
    if not t or not any((v or "").strip() for v in t.values()):
        raise HTTPException(400, "errors.title_required")
    return t


def _check_permit_target(db: Session, kind: str, target: str) -> None:
    if kind == "machine":
        if target.startswith("model:"):
            if not (target[6:].isdigit() and db.get(MachineModel, int(target[6:]))):
                raise HTTPException(400, "errors.bad_permit_target")
        elif target not in q.fleet_types():
            raise HTTPException(400, "errors.bad_permit_target")
    elif kind == "work":
        if not db.scalar(select(WorkKind).where(WorkKind.code == target)):
            raise HTTPException(400, "errors.bad_permit_target")
    else:
        raise HTTPException(400, "errors.bad_permit_target")


@router.get("/staff/permit-targets")
def permit_targets(db: Session = Depends(get_db), user: CurrentUser = Depends(require("staff.view", "dispatch.view"))):
    """На что выдаётся допуск: тип машины, модель (справочник моделей), вид работ — с подписями."""
    L = q.Labels(db, user.lang)
    return {
        "machine_types": [{"target": k, "label": L.type_label(k)} for k in q.fleet_types()],
        "models": [{"target": f"model:{m.id}", "label": q.model_label(m), "manufacturer": m.manufacturer, "type": m.type}
                   for m in sorted(L.models.values(), key=lambda m: (m.type, m.manufacturer, m.model)) if m.active],
        "works": [{"target": w.code, "label": q.title(w.title, user.lang), "requires_permit": w.requires_permit,
                   "assignable": w.assignable} for w in L.works.values() if w.active],
    }


@router.get("/staff/work-kinds")
def work_kinds(db: Session = Depends(get_db), _: CurrentUser = Depends(require("staff.view", "dispatch.view"))):
    return [w.as_dict() for w in db.scalars(select(WorkKind).order_by(WorkKind.id))]


@router.post("/staff/work-kinds")
def create_work_kind(body: dict, db: Session = Depends(get_db), user: CurrentUser = Depends(require("staff.edit"))):
    code = (body.get("code") or "").strip()
    if not code or not code.replace("_", "").isalnum():
        raise HTTPException(400, "errors.bad_code")
    if db.scalar(select(WorkKind).where(WorkKind.code == code)):
        raise HTTPException(400, "errors.exists")
    w = WorkKind(code=code, title=_title_body(body, user.lang), requires_permit=body.get("requires_permit", True),
                 assignable=body.get("assignable", True))
    db.add(w)
    audit(db, user, "work_kind_create", "work_kind", code)
    db.commit()
    return w.as_dict()


@router.put("/staff/work-kinds/{wid}")
def update_work_kind(wid: int, body: dict, db: Session = Depends(get_db), user: CurrentUser = Depends(require("staff.edit"))):
    w = db.get(WorkKind, wid)
    if not w:
        raise HTTPException(404, "errors.not_found")
    if "title" in body:
        w.title = {**(w.title or {}), **_title_body(body, user.lang)}
    _crud_update(w, body, ("requires_permit", "assignable", "active"))
    audit(db, user, "work_kind_update", "work_kind", wid, body)
    db.commit()
    return w.as_dict()


@router.get("/staff/professions")
def professions(db: Session = Depends(get_db), user: CurrentUser = Depends(require("staff.view", "dispatch.view"))):
    L = q.Labels(db, user.lang)
    out = []
    for p in db.scalars(select(Profession).order_by(Profession.id)):
        d = p.as_dict()
        d["label"] = q.title(p.title, user.lang)
        d["permits"] = [{**x, "label": L.target_label(x["kind"], x["target"])} for x in p.permits or []]
        out.append(d)
    return out


def _prof_permits(db: Session, body: dict) -> list:
    out = []
    for x in body.get("permits") or []:
        _check_permit_target(db, x.get("kind", ""), x.get("target", ""))
        out.append({"kind": x["kind"], "target": x["target"]})
    return out


@router.post("/staff/professions")
def create_profession(body: dict, db: Session = Depends(get_db), user: CurrentUser = Depends(require("staff.edit"))):
    t = _title_body(body, user.lang)
    code = (body.get("code") or "").strip() or f"prof_{(db.scalar(select(func.max(Profession.id))) or 0) + 1}"
    if db.scalar(select(Profession).where(Profession.code == code)):
        raise HTTPException(400, "errors.exists")
    p = Profession(code=code, title=t, permits=_prof_permits(db, body), trainee=bool(body.get("trainee")))
    db.add(p)
    audit(db, user, "profession_create", "profession", code)
    db.commit()
    return p.as_dict()


@router.put("/staff/professions/{pid}")
def update_profession(pid: int, body: dict, db: Session = Depends(get_db), user: CurrentUser = Depends(require("staff.edit"))):
    p = db.get(Profession, pid)
    if not p:
        raise HTTPException(404, "errors.not_found")
    if "title" in body:
        p.title = {**(p.title or {}), **_title_body(body, user.lang)}
    if "permits" in body:
        p.permits = _prof_permits(db, body)
    _crud_update(p, body, ("trainee", "active"))
    audit(db, user, "profession_update", "profession", pid, body)
    db.commit()
    return p.as_dict()


# ---------------- персонал ----------------
PERSON_FIELDS = ("full_name", "tab_no", "professions", "mentor_id", "crew", "shift", "contacts", "active")


def _permit_out(L: q.Labels, p: Permit, warn: int) -> dict:
    d = p.as_dict()
    d["state"] = q.permit_state(p.valid_to, warn)
    d["label"] = L.target_label(p.kind, p.target)
    d["has_file"] = bool(p.file_key)
    d.pop("file_key", None)
    return d


@router.get("/staff")
def staff(db: Session = Depends(get_db), user: CurrentUser = Depends(require("staff.view", "dispatch.view"))):
    warn = int((get_setting(db, "alerts") or {}).get("permit_warn_days", 14))
    L = q.Labels(db, user.lang)
    fleet_models: dict[str, set[int]] = {}
    for mc in db.scalars(select(Machine).where(Machine.model_id.is_not(None))):
        fleet_models.setdefault(mc.type, set()).add(mc.model_id)
    permits = q.permits_by_person(db)
    people = list(db.scalars(select(Person).order_by(Person.id)))
    names = {p.id: p.full_name for p in people}
    out = []
    for p in people:
        d = p.as_dict()
        own = [_permit_out(L, x, warn) for x in sorted(permits.get(p.id, []), key=lambda x: (x.kind, x.id))]
        d["permits"] = own
        d["permit_state"] = ("expired" if any(x["state"] == "expired" for x in own) else
                             "expiring" if any(x["state"] == "expiring" for x in own) else "valid")
        d["professions"] = p.professions or []
        d["profession_labels"] = [L.prof_label(c) for c in d["professions"]]
        d["trainee"] = L.is_trainee(p)
        d["mentor_name"] = names.get(p.mentor_id)
        # «Может работать на»: модели по действующим допускам (на модель или на тип — модели этого типа во флоте)
        can = []
        for x in own:
            if x["kind"] != "machine" or x["state"] == "expired":
                continue
            if x["target"].startswith("model:"):
                can.append(x["label"])
            else:
                ids = fleet_models.get(x["target"])
                can += [q.model_label(L.models[i]) for i in sorted(ids)] if ids else [x["label"]]
        d["can_work_on"] = list(dict.fromkeys(can))
        out.append(d)
    return out


def _parse_dt(v: str | None):
    if not v:
        return None
    dt = datetime.fromisoformat(v)
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _person_profs(db: Session, body: dict) -> None:
    if "professions" in body:
        codes = [c for c in body["professions"] or [] if c]
        known = {p.code for p in db.scalars(select(Profession))}
        if not codes or any(c not in known for c in codes):
            raise HTTPException(400, "errors.bad_profession")
        body["professions"] = list(dict.fromkeys(codes))
        body["profession"] = body["professions"][0]


def _add_permit(db: Session, pid: int, x: dict) -> Permit:
    _check_permit_target(db, x.get("kind", ""), x.get("target", ""))
    vt = _parse_dt(x.get("valid_to"))
    if not vt:
        raise HTTPException(400, "errors.valid_to_required")
    pm = Permit(person_id=pid, kind=x["kind"], target=x["target"], valid_to=vt, issued_at=_parse_dt(x.get("issued_at")),
                number=x.get("number", "") or "")
    db.add(pm)
    return pm


@router.post("/staff")
def create_person(body: dict, db: Session = Depends(get_db), user: CurrentUser = Depends(require("staff.edit"))):
    """Новый человек; permits — допуски по умолчанию его профессий (из окна «Человек», можно убрать или добавить)."""
    if db.scalar(select(Person).where(Person.tab_no == body.get("tab_no"))):
        raise HTTPException(400, "errors.exists")
    body = dict(body)
    body.setdefault("professions", [body["profession"]] if body.get("profession") else [])
    _person_profs(db, body)
    p = Person(mine_id=active_mine(db).id, profession=body["profession"],
               **{k: body[k] for k in PERSON_FIELDS if k in body})
    db.add(p)
    db.flush()
    for x in body.get("permits") or []:
        _add_permit(db, p.id, x)
    audit(db, user, "person_create", "person", body.get("tab_no"), {"professions": p.professions,
                                                                     "permits": len(body.get("permits") or [])})
    db.commit()
    return p.as_dict()


@router.put("/staff/{pid}")
def update_person(pid: int, body: dict, db: Session = Depends(get_db), user: CurrentUser = Depends(require("staff.edit"))):
    p = db.get(Person, pid)
    if not p:
        raise HTTPException(404, "errors.not_found")
    body = dict(body)
    _person_profs(db, body)
    if body.get("mentor_id") == pid:
        raise HTTPException(400, "errors.mentor_self")
    _crud_update(p, body, PERSON_FIELDS + ("profession",))
    audit(db, user, "person_update", "person", pid, {k: body[k] for k in body if k in PERSON_FIELDS})
    db.commit()
    return p.as_dict()


@router.post("/staff/{pid}/permits")
def add_permit(pid: int, body: dict, db: Session = Depends(get_db), user: CurrentUser = Depends(require("staff.edit"))):
    if not db.get(Person, pid):
        raise HTTPException(404, "errors.not_found")
    pm = _add_permit(db, pid, body)
    audit(db, user, "permit_add", "person", pid, {"kind": pm.kind, "target": pm.target, "valid_to": body["valid_to"],
                                                  "number": pm.number})
    db.commit()
    return pm.as_dict()


@router.put("/staff/permits/{pmid}")
def update_permit(pmid: int, body: dict, db: Session = Depends(get_db), user: CurrentUser = Depends(require("staff.edit"))):
    """Правка допуска; сохранение снимает отметку «выдан автоматически — проверить»."""
    pm = db.get(Permit, pmid)
    if not pm:
        raise HTTPException(404, "errors.not_found")
    if "valid_to" in body:
        pm.valid_to = _parse_dt(body["valid_to"]) or pm.valid_to
    if "issued_at" in body:
        pm.issued_at = _parse_dt(body["issued_at"])
    if "number" in body:
        pm.number = body["number"] or ""
    pm.auto = False
    audit(db, user, "permit_update", "permit", pmid, body)
    db.commit()
    return pm.as_dict()


@router.delete("/staff/permits/{pmid}")
def delete_permit(pmid: int, db: Session = Depends(get_db), user: CurrentUser = Depends(require("staff.edit"))):
    pm = db.get(Permit, pmid)
    if pm:
        db.delete(pm)
        audit(db, user, "permit_delete", "permit", pmid, {"person_id": pm.person_id, "target": pm.target})
        db.commit()
    return {"ok": True}


@router.post("/staff/permits/{pmid}/file")
async def upload_permit_file(pmid: int, file: UploadFile = File(...), db: Session = Depends(get_db),
                             user: CurrentUser = Depends(require("staff.edit"))):
    pm = db.get(Permit, pmid)
    if not pm:
        raise HTTPException(404, "errors.not_found")
    data = await file.read()
    pm.file_key = storage.put(f"permits/{pm.person_id}/{pmid}/{file.filename}", data,
                              file.content_type or "application/octet-stream")
    audit(db, user, "permit_file", "permit", pmid, {"file": file.filename})
    db.commit()
    return {"ok": True}


@router.get("/staff/permits/{pmid}/file")
def permit_file(pmid: int, db: Session = Depends(get_db), _: CurrentUser = Depends(require("staff.view"))):
    pm = db.get(Permit, pmid)
    if not pm or not pm.file_key:
        raise HTTPException(404, "errors.not_found")
    name = pm.file_key.rsplit("/", 1)[-1]
    media = mimetypes.guess_type(name)[0] or "application/octet-stream"
    return Response(storage.get(pm.file_key), media_type=media,
                    headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(name)}"})


# ---------------- перенос данных прежней версии ----------------
@router.get("/migration/patch01")
def migration_report(db: Session = Depends(get_db), user: CurrentUser = Depends(require("fleet.view", "staff.view"))):
    """Что не распозналось при переносе и какие допуски выданы автоматически — с текущим состоянием."""
    rep = get_setting(db, q.REPORT_KEY) or {}
    L = q.Labels(db, user.lang)
    auto = {(p.person_id, p.kind, p.target): p for p in db.scalars(select(Permit).where(Permit.auto.is_(True)))}
    persons = []
    for r in rep.get("persons") or []:
        left = [{**x, "label": L.target_label(x["kind"], x["target"]),
                 "permit_id": auto[(r["id"], x["kind"], x["target"])].id if (r["id"], x["kind"], x["target"]) in auto else None}
                for x in r.get("auto_permits") or []]
        persons.append({**r, "auto_permits": left, "profession_labels": [L.prof_label(c) for c in r.get("professions") or []],
                        "pending": sum(1 for x in left if x["permit_id"])})
    machines = []
    for r in rep.get("machines") or []:
        mc = db.get(Machine, r["id"])
        machines.append({**r, "current_name": mc.label if mc else None,
                         "current_model": (q.model_label(L.models[mc.model_id]) if mc and mc.model_id in L.models else None),
                         "type_label": L.type_label(r["type"])})
    return {"ts": rep.get("ts"), "auto_permit_days": rep.get("auto_permit_days"), "machines": machines, "persons": persons}
