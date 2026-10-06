"""Общие функции API: активный рудник, геология по пикету, экономика, вызовы сервисов calc/importer/analyzer."""
from __future__ import annotations

import logging
from typing import Any, Callable

import httpx
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from common.models import Explosive, GeologyAssignment, Mine, RockType, Setting, Stope, Working
from common.settings import get_settings, load_yaml
from core import geometry as g

log = logging.getLogger("api")


# ---------------- настройки ----------------
def get_setting(db: Session, key: str, default: Any = None) -> Any:
    s = db.get(Setting, key)
    return s.value.get("v", default) if s and isinstance(s.value, dict) and "v" in s.value else (s.value if s else default)


def set_setting(db: Session, key: str, value: Any) -> None:
    s = db.get(Setting, key)
    if s:
        s.value = {"v": value}
    else:
        db.add(Setting(key=key, value={"v": value}))


def active_mine(db: Session) -> Mine:
    m = db.scalar(select(Mine).where(Mine.active.is_(True)))
    if not m:
        m = db.scalar(select(Mine).order_by(Mine.id))
    if not m:
        raise HTTPException(404, "errors.no_mine")
    return m


def economics(db: Session, mine: Mine | None = None) -> dict:
    econ = get_setting(db, "economics") or load_yaml("economics.yaml")
    if mine:
        econ = dict(econ)
        econ["currency"] = mine.config.get("currency", econ.get("currency", "USD"))
        econ["costs"] = {**econ.get("costs", {}), **(mine.config.get("costs") or {})}
    return econ


def ramp_axis(db: Session, mine_id: int) -> list:
    r = db.scalar(select(Working).where(Working.mine_id == mine_id, Working.type == "ramp").order_by(Working.id))
    if not r:
        raise HTTPException(400, "errors.no_ramp")
    return r.axis


# ---------------- геология ----------------
ROCK_FIELDS = ("f", "ucs", "density", "fracture_cat", "fracture_spacing", "rqd", "rmr", "q", "water", "inflow_lpm",
               "kind")


def _rock_dict(r: RockType | None) -> dict:
    if not r:
        return {}
    d = {k: getattr(r, k) for k in ROCK_FIELDS}
    d.update({"rock_id": r.id, "rock_code": r.code, "rock_name": r.name, "grades": r.grades or {}, **(r.extra or {})})
    return d


def _in_zone(zone: dict, p: list) -> bool:
    mn, mx = zone.get("min"), zone.get("max")
    return bool(mn and mx and all(mn[i] <= p[i] <= mx[i] for i in range(3)))


def geology_at(db: Session, working: Working | None = None, chainage: float | None = None,
               stope: Stope | None = None, point: list | None = None) -> dict:
    """Свойства пород с приоритетом: интервал > выработка > камера/3D-зона > рудник по умолчанию."""
    mine_id = working.mine_id if working else stope.mine_id if stope else None
    rows = db.scalars(select(GeologyAssignment).where(GeologyAssignment.mine_id == mine_id)).all()
    rocks = {r.id: r for r in db.scalars(select(RockType)).all()}
    if point is None:
        if working is not None:
            point = g.point_at(working.axis, chainage or 0)
        elif stope is not None:
            gm = stope.geometry
            point = [(gm["x_fw"] + gm["x_hw"]) / 2, (gm["y0"] + gm["y1"]) / 2,
                     (stope.level_bottom + stope.level_top) / 2]
    layers: list[tuple[str, GeologyAssignment]] = []
    for a in rows:
        if a.target == "mine":
            layers.append(("mine", a))
    for a in rows:
        if a.target == "zone" and point is not None and _in_zone(a.zone, point):
            layers.append(("zone", a))
        if a.target == "stope" and stope is not None and a.stope_id == stope.id:
            layers.append(("zone", a))
    if working is not None:
        for a in rows:
            if a.target == "working" and a.working_id == working.id:
                layers.append(("working", a))
        if chainage is not None:
            for a in rows:
                if a.target == "interval" and a.working_id == working.id and (a.ch_from or 0) <= chainage <= (a.ch_to or 0):
                    layers.append(("interval", a))
    out: dict = {"source": [], "faults": []}
    for src, a in layers:
        if a.rock_type_id and a.rock_type_id in rocks:
            out.update(_rock_dict(rocks[a.rock_type_id]))
        ov = dict(a.overrides or {})
        faults = ov.pop("faults", None)
        if faults:
            out["faults"] = out["faults"] + faults
        out.update(ov)
        out["source"].append({"level": src, "id": a.id, "name": a.name})
    out["priority"] = out["source"][-1]["level"] if out["source"] else "none"
    out.setdefault("f", 10)
    out.setdefault("density", 2.7)
    out.setdefault("fracture_cat", 3)
    out.setdefault("water", "dry")
    out["cleavage"] = any(f.get("type") == "cleavage" for f in out["faults"])
    return out


def explosive_dict(e: Explosive) -> dict:
    return {c.key: getattr(e, c.key) for c in e.__table__.columns}


# ---------------- сервисы ----------------
def remote(service_url: str, path: str, payload: dict, fallback: Callable[[], Any], timeout: float = 60) -> Any:
    """POST в соседний сервис; если недоступен — локальный расчёт той же библиотекой (тесты, деградация)."""
    if get_settings().db_url.startswith("sqlite"):
        return fallback()
    try:
        r = httpx.post(service_url + path, json=payload, timeout=timeout)
        if r.status_code == 200:
            return r.json()
        if r.status_code in (400, 422):
            raise HTTPException(400, r.json().get("detail", "errors.calc_failed"))
        log.warning("remote %s%s → %s", service_url, path, r.status_code)
    except httpx.HTTPError as e:
        log.warning("remote %s%s недоступен: %s", service_url, path, e)
    return fallback()


def calc(path: str, payload: dict, fallback: Callable[[], Any]) -> Any:
    return remote(get_settings().calc_url, path, payload, fallback)


def analyzer(path: str, payload: dict, fallback: Callable[[], Any]) -> Any:
    return remote(get_settings().analyzer_url, path, payload, fallback, timeout=120)
