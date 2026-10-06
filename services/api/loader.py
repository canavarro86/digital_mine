"""Загрузка пакета рудника (mines/<имя>/) в PostgreSQL."""
from __future__ import annotations

import logging
from datetime import timedelta
from pathlib import Path

import yaml
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from common.models import (
    CutTemplate,
    DevPassport,
    Explosive,
    Face,
    GeologyAssignment,
    Machine,
    Mine,
    Orebody,
    Permit,
    Person,
    RingDesign,
    RockType,
    Stope,
    TypicalPassport,
    TypicalPassportVersion,
    Working,
)
from common.timeutil import utcnow
from core import geometry as g
from core import importers, passport, rings
from core.planning import OrebodyModel

from . import qualify
from .svc import explosive_dict

log = logging.getLogger("loader")


def _yaml(p: Path) -> dict:
    if not p.exists():
        return {}
    with open(p, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def load_package(db: Session, path: Path, activate: bool = True) -> Mine:
    cfg = _yaml(path / "mine.yaml")
    code = cfg.get("code") or path.name
    mine = db.scalar(select(Mine).where(Mine.code == code))
    if mine:
        return mine
    if activate:
        for m in db.scalars(select(Mine)).all():
            m.active = False
    mine = Mine(code=code, name=cfg.get("name", code), path=str(path), config=cfg, active=activate)
    db.add(mine)
    db.flush()
    log.info("Загрузка рудника %s из %s", code, path)

    # выработки
    csv_path = path / "geometry" / "workings.csv"
    by_name: dict[str, Working] = {}
    if csv_path.exists():
        parsed = importers.parse("workings.csv", csv_path.read_bytes())
        for w in importers.polylines_to_workings(parsed):
            row = Working(mine_id=mine.id, name=w["name"], type=w["type"],
                          level=w["level"] if w["type"] != "ramp" else None, status=w["status"], source="demo",
                          axis=w["axis"], section=w["section"], direction=w.get("direction") or "", seq=w.get("seq"),
                          props={"face_chainage": w.get("face_chainage")} if w.get("face_chainage") else {})
            db.add(row)
            by_name[w["name"]] = row
    for dxf in sorted((path / "geometry").glob("*.dxf")) if not csv_path.exists() else []:
        parsed = importers.parse(dxf.name, dxf.read_bytes())
        for w in importers.polylines_to_workings(parsed):
            row = Working(mine_id=mine.id, name=w["name"], type=w["type"], level=w["level"], status="done",
                          source="import", axis=w["axis"], section=w["section"])
            db.add(row)
            by_name[w["name"]] = row
    db.flush()

    # камеры
    for s in _yaml(path / "geometry" / "stopes.yaml").get("stopes", []):
        drive = by_name.get(s.get("drive") or "")
        upper = by_name.get(s.get("upper_drive") or "")
        db.add(Stope(mine_id=mine.id, name=s["name"], level_bottom=s["level_bottom"], level_top=s["level_top"],
                     drive_id=drive.id if drive else None, upper_drive_id=upper.id if upper else None,
                     geometry=s["geometry"], grades=s.get("grades") or {}, status=s.get("status", "planned")))
    if cfg.get("orebody_model"):
        db.add(Orebody(mine_id=mine.id, name="Жила", mesh=OrebodyModel(cfg["orebody_model"]).mesh(dy=25, dz=15),
                       props={"model": cfg["orebody_model"], "grades": cfg.get("grades", {})}))
    elif (path / "geometry" / "orebody.obj").exists():
        parsed = importers.parse("orebody.obj", (path / "geometry" / "orebody.obj").read_bytes())
        db.add(Orebody(mine_id=mine.id, name="Orebody", mesh=parsed["meshes"][0]))
    db.flush()

    # геология
    rocks = {r.code: r for r in db.scalars(select(RockType)).all()}
    geo = _yaml(path / "geology" / "zones.yaml")
    if geo.get("default_rock") in rocks:
        db.add(GeologyAssignment(mine_id=mine.id, target="mine", name="По умолчанию",
                                 rock_type_id=rocks[geo["default_rock"]].id))
    if geo.get("ore_rock") in rocks:
        for st in db.scalars(select(Stope).where(Stope.mine_id == mine.id)).all():
            db.add(GeologyAssignment(mine_id=mine.id, target="stope", name=st.name, stope_id=st.id,
                                     rock_type_id=rocks[geo["ore_rock"]].id))
    for a in geo.get("assignments", []):
        w = by_name.get(a.get("working") or "")
        db.add(GeologyAssignment(mine_id=mine.id, target=a["target"], name=a.get("name", ""),
                                 working_id=w.id if w else None, ch_from=a.get("ch_from"), ch_to=a.get("ch_to"),
                                 zone=a.get("zone") or {}, rock_type_id=rocks[a["rock"]].id if a.get("rock") in rocks else None,
                                 overrides=a.get("overrides") or {}))
    db.flush()

    # флот и персонал (пакеты прежней версии без моделей и профессий дополняет qualify.migrate_patch01)
    for m in _yaml(path / "fleet.yaml").get("fleet", []):
        if db.scalar(select(Machine).where(Machine.mine_id == mine.id, Machine.number == str(m["number"]))):
            continue
        mm = qualify.match_model(db, m.get("manufacturer", ""), m.get("model", ""), m.get("type", ""))
        row = Machine(mine_id=mine.id, **{**m, "number": str(m["number"])})
        if mm and "name" in m:
            row.model_id, row.manufacturer, row.model = mm.id, mm.manufacturer, mm.model
            row.params = {**mm.params, **(m.get("params") or {})}
        db.add(row)
    now = utcnow()
    mentors: dict[str, str] = {}  # стажёр → наставник (табельные номера)
    for p in _yaml(path / "staff.yaml").get("staff", []):
        if db.scalar(select(Person).where(Person.tab_no == p["tab_no"])):
            continue
        permits = p.pop("permits", [])
        if p.get("mentor_tab"):
            mentors[p["tab_no"]] = p.pop("mentor_tab")
        if p.get("professions"):
            p.setdefault("profession", p["professions"][0])
        person = Person(mine_id=mine.id, **p)
        db.add(person)
        db.flush()
        for pm in permits:
            pm = qualify.resolve_target(db, pm)
            db.add(Permit(person_id=person.id, kind=pm["kind"], target=pm["target"], number=pm.get("number", ""),
                          valid_to=now + timedelta(days=int(pm["days_valid"])),
                          issued_at=now - timedelta(days=int(pm.get("days_issued", 365)))))
    db.flush()
    for tab, mentor_tab in mentors.items():
        trainee = db.scalar(select(Person).where(Person.tab_no == tab))
        mentor = db.scalar(select(Person).where(Person.tab_no == mentor_tab))
        if trainee and mentor:
            trainee.mentor_id = mentor.id
    db.flush()

    # типовые паспорта
    expl = {e.code: explosive_dict(e) for e in db.scalars(select(Explosive)).all()}
    tp_cfg = _yaml(path / "passports" / "typical.yaml")
    std = cfg.get("standard_passports") or {}
    tps: dict[str, TypicalPassport] = {}
    for tp in tp_cfg.get("passports", []):
        e = expl.get(tp["explosive"]) or next(iter(expl.values()))
        inp = {"section": tp["section"], "rock": {"f": tp["rock_f"], "fracture_cat": tp["fracture_cat"], "density": 2.75,
                                                  "water": "dry"},
               "explosive": e, "contour_explosive": expl.get(tp.get("contour_explosive")) or e,
               "hole_depth": tp["hole_depth"], "hole_diameter": 45, "empty_diameter": 102,
               "cut": {"type": "prismatic"}, "initiation": "edd", "drill": {"booms": 2, "drill_rate_mph": 90, "setup_h": 0.5}}
        res = passport.design(inp)
        row = TypicalPassport(mine_id=mine.id, number=tp["number"], name=tp["name"], working_type=tp["working_type"],
                              section=g.section_info(tp["section"]), f_min=tp["f_min"], f_max=tp["f_max"],
                              water=tp["water"], explosive_id=e.get("id"), input=inp, design=res,
                              indicators=res["indicators"], version=1, status="approved", approved_by="engineer",
                              approved_at=now, created_by="system",
                              assigned={"working_types": [wt for wt, num in std.items() if num == tp["number"]]})
        db.add(row)
        db.flush()
        db.add(TypicalPassportVersion(passport_id=row.id, version=1, data={"input": inp, "indicators": res["indicators"]},
                                      changed_by="system", note="Загружен из пакета рудника"))
        tps[tp["number"]] = row
    db.flush()

    # забои: выработки в проходке и активные камеры
    for w in by_name.values():
        if w.status != "driving":
            continue
        ch = float((w.props or {}).get("face_chainage") or 0)
        tp = tps.get(std.get(w.type, "")) or next(iter(tps.values()), None)
        face = Face(mine_id=mine.id, kind="dev", working_id=w.id, name=w.name, status="ready", chainage=ch,
                    priority=3 if w.type == "fwd" else 5)
        db.add(face)
        db.flush()
        if tp:
            geo_at = None
            try:
                from .svc import geology_at

                geo_at = geology_at(db, w, ch)
            except Exception:
                geo_at = None
            inp = dict(tp.input)
            if geo_at:
                inp["rock"] = {k: geo_at.get(k) for k in ("f", "fracture_cat", "density", "water", "cleavage")}
                inp["rock"].update(rock_name=geo_at.get("rock_name"), source=geo_at.get("priority"))
            res = passport.design(inp)
            dp = DevPassport(working_id=w.id, number=f"{tp.number}/{w.id}", name=f"{tp.name} — {w.name}",
                             status="approved", typical_id=tp.id, input=inp, design=res, indicators=res["indicators"],
                             signatures={"made": "Инженер БВР", "approved": "Главный инженер"}, created_by="system")
            db.add(dp)
            db.flush()
            face.passport_id = dp.id
    ring_cfg = tp_cfg.get("rings") or {}
    re_ = expl.get(ring_cfg.get("explosive", "EMUL_BULK")) or next(iter(expl.values()))
    for st in db.scalars(select(Stope).where(Stope.mine_id == mine.id, Stope.status == "active")).all():
        inp = {"explosive": re_, "rock": {"f": 12, "density": 2.9, "water": "dry"},
               "hole_diameter": ring_cfg.get("hole_diameter", 89), "direction": ring_cfg.get("direction", "up"),
               "standoff": ring_cfg.get("standoff", 0.7), "initiation": "edd", "ring_interval_ms": 75}
        res = rings.design_rings(inp, {"id": st.id, "geometry": st.geometry, "level_bottom": st.level_bottom,
                                       "level_top": st.level_top})
        rd = RingDesign(stope_id=st.id, name=f"Веера {st.name}", status="approved", input=inp, design=res,
                        indicators=res["indicators"], created_by="system")
        db.add(rd)
        db.flush()
        if st.upper_drive_id:  # камеру можно бурить и нисходящими веерами из верхней выработки
            inp_d = {**inp, "direction": "down"}
            res_d = rings.design_rings(inp_d, {"id": st.id, "geometry": st.geometry, "level_bottom": st.level_bottom,
                                               "level_top": st.level_top})
            db.add(RingDesign(stope_id=st.id, name=f"Веера {st.name} (нисходящие)", status="approved", input=inp_d,
                              design=res_d, indicators=res_d["indicators"], created_by="system"))
        db.add(Face(mine_id=mine.id, kind="stope", stope_id=st.id, name=st.name, status="ready", ring_design_id=rd.id,
                    priority=4))
    db.commit()
    return mine


def seed_reference(db: Session, root: Path) -> None:
    """Справочники из config/: ВВ, СИ, породы, библиотека врубов (только при пустой базе)."""
    from common.models import InitiationDevice

    with open(root / "config" / "explosives.yaml", encoding="utf-8") as f:
        ex = yaml.safe_load(f)
    if not db.scalar(select(Explosive).limit(1)):
        for e in ex.get("explosives", []):
            db.add(Explosive(builtin=True, **e))
        for d in ex.get("initiation", []):
            db.add(InitiationDevice(builtin=True, **d))
    with open(root / "config" / "rocks.yaml", encoding="utf-8") as f:
        rk = yaml.safe_load(f)
    if not db.scalar(select(RockType).limit(1)):
        for r in rk.get("rocks", []):
            r = dict(r)
            db.add(RockType(**r))
    qualify.seed_catalogs(db)
    if not db.scalar(select(CutTemplate).limit(1)):
        for name, t, params in [
            ("Призматический, 1 холостой Ø102", "prismatic", {"n_empty": 1, "empty_diameter": 102}),
            ("Призматический, 2 холостых Ø102", "prismatic", {"n_empty": 2, "empty_diameter": 102}),
            ("Щелевой, 2 холостых Ø102", "slot", {"n_empty": 2, "empty_diameter": 102}),
            ("Спиральный, 1 холостой Ø127", "spiral", {"n_empty": 1, "empty_diameter": 127}),
            ("Клиновой (V-образный)", "wedge", {}),
            ("Пирамидальный", "pyramid", {}),
        ]:
            db.add(CutTemplate(name=name, type=t, params=params, builtin=True))
    db.commit()


def reset_mine(db: Session, mine: Mine) -> None:
    """Удаление рудника из базы (для повторной загрузки пакета)."""
    for model in (Working, Stope, Orebody, GeologyAssignment, Face):
        db.execute(delete(model).where(model.mine_id == mine.id))
    db.delete(mine)
    db.commit()
