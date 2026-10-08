"""Расстановка смены: наряд, проверки (допуск, исправность, статус забоя), перестановки, табло «Смена сейчас»."""
from __future__ import annotations

import math
from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from common import i18n
from common.bus import publish
from common.db import get_db
from common.models import (
    Alert,
    Assignment,
    DevPassport,
    Face,
    Machine,
    Permit,
    Person,
    Reassignment,
    RingDesign,
    ShiftOrder,
    Stope,
    Working,
    WorkKind,
)
from common.timeutil import current_shift, shift_bounds, shift_config, to_tz, utcnow
from core import geometry as g

from .. import qualify as q
from ..deps import CurrentUser, audit, require
from ..svc import active_mine, get_setting

router = APIRouter(prefix="/api/dispatch", tags=["dispatch"])
VIEW = require("dispatch.view")
EDIT = require("dispatch.edit")

WORK_MACHINE = {"drilling": "dev_drill", "ring_drilling": "ring_drill", "mucking": "lhd", "charging": "charger",
                "support": "bolter", "aux": "aux"}
WORK_FACE_STATUS = {
    "drilling": {"ready", "drilling"}, "ring_drilling": {"ready", "drilling"}, "charging": {"accepted", "charged"},
    "mucking": {"blasted", "ventilation", "mucking", "draw"}, "scaling": {"mucking", "scaling"},
    "support": {"scaling", "support"}, "survey": {"support", "surveyed", "draw", "cms"}, "supervision": None,
    "aux": None,
}
WORK_TYPES = list(WORK_FACE_STATUS)
WORK_FACE_KIND = {"drilling": "dev", "ring_drilling": "stope"}  # проходка — проходческие забои, веера — камеры
DRILL_DRIVE_OK = {"done"}  # буровая выработка пройдена — из нее можно бурить веера
DIRECTIONS = ("down", "up")


def ring_options(db: Session, face: Face) -> list[dict]:
    """Варианты бурения камеры: нисходящие — из верхней выработки, восходящие — из нижней;
    проект вееров этого направления и буровая выработка с ее статусом."""
    st = db.get(Stope, face.stope_id) if face.stope_id else None
    if not st:
        return []
    designs = [r for r in db.scalars(select(RingDesign).where(RingDesign.stope_id == st.id).order_by(RingDesign.id))
               if r.status != "archived"]
    out = []
    for d in DIRECTIONS:
        drive_id = st.upper_drive_id if d == "down" else st.drive_id
        mine_ = [r for r in designs if (r.input or {}).get("direction", "up") == d]
        rd = next((r for r in mine_ if r.id == face.ring_design_id), None) or \
            next((r for r in reversed(mine_) if r.status == "approved"), None) or (mine_[-1] if mine_ else None)
        out.append({"direction": d, "drive": db.get(Working, drive_id) if drive_id else None, "design": rd})
    return out


def default_direction(db: Session, face: Face | None) -> str | None:
    if not face or face.kind != "stope":
        return None
    rd = db.get(RingDesign, face.ring_design_id) if face.ring_design_id else None
    return (rd.input or {}).get("direction", "up") if rd else "up"


def ring_issues(db: Session, face: Face, direction: str, lang: str) -> tuple[list[dict], dict | None]:
    """Спроектированы ли веера этого направления и допускает ли буровая выработка бурение."""
    opt = next((o for o in ring_options(db, face) if o["direction"] == direction), None)
    dirl = i18n.t(f"dispatch.dir_gen.{direction}", lang)
    if direction not in DIRECTIONS or not opt:
        return [{"level": "error", "code": "bad_direction", "params": {"face": face.name}}], None
    out = []
    if not opt["design"]:
        out.append({"level": "error", "code": "rings_not_designed", "params": {"face": face.name, "dir": dirl}})
    if not opt["drive"]:
        out.append({"level": "error", "code": "drill_drive_missing", "params": {"face": face.name, "dir": dirl}})
    elif opt["drive"].status not in DRILL_DRIVE_OK:
        out.append({"level": "error", "code": "drill_drive_status",
                    "params": {"drive": opt["drive"].name, "status": i18n.t(f"workings.status.{opt['drive'].status}", lang)}})
    return out, opt


def face_label(db: Session, face: Face | None, direction: str | None, lang: str) -> str:
    """«Камера −225/−200.6 · восходящие (из БДО −225.6)»."""
    if not face:
        return ""
    if face.kind != "stope" or not direction:
        return face.name
    opt = next((o for o in ring_options(db, face) if o["direction"] == direction), None)
    drive = opt["drive"].name if opt and opt["drive"] else "—"
    return i18n.t("dispatch.ring_target", lang, face=face.name, dir=i18n.t(f"dispatch.dir.{direction}", lang), drive=drive)


def work_types(db: Session) -> list[str]:
    """Виды работ наряда: встроенные + добавленные в справочник «Виды допусков» (без привязки к статусу забоя)."""
    extra = [w.code for w in db.scalars(select(WorkKind).where(WorkKind.active.is_(True), WorkKind.assignable.is_(True)))
             if w.code not in WORK_FACE_STATUS]
    return WORK_TYPES + extra


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def face_position(db: Session, f: Face) -> list | None:
    if f.working_id:
        w = db.get(Working, f.working_id)
        return g.point_at(w.axis, f.chainage) if w else None
    if f.stope_id:
        s = db.get(Stope, f.stope_id)
        gm = s.geometry
        return [(gm["x_fw"] + gm["x_hw"]) / 2, (gm["y0"] + gm["y1"]) / 2, s.level_bottom]
    return None


def face_drill_hours(db: Session, f: Face, machine: Machine | None) -> float:
    """Оценка времени бурения забоя по паспорту и параметрам машины: чистое бурение, перестановки, установка."""
    params = (machine.params if machine else {}) or {}
    rate = float(params.get("drill_rate_mph") or (90 if f.kind == "dev" else 35))
    booms = max(float(params.get("booms") or (2 if f.kind == "dev" else 1)), 1)
    setup = float(params.get("setup_h") or 0.5)
    repos_h = float(params.get("reposition_min") or 0) / 60
    if f.kind == "dev" and f.passport_id:
        dp = db.get(DevPassport, f.passport_id)
        ind = (dp.indicators or {}) if dp else {}
        m, n = float(ind.get("drill_m", 180)), float(ind.get("holes_total", 60))
    elif f.ring_design_id:
        rd = db.get(RingDesign, f.ring_design_id)
        ind = (rd.indicators or {}) if rd else {}
        k = 2 / max(float(ind.get("rings", 1)), 1)  # 2 веера за смену
        m, n = float(ind.get("drill_m", 300)) * k, float(ind.get("holes", 20)) * k
    else:
        m, n = 180, 60
    return round(m / (rate * booms) + n * repos_h / booms + setup, 2)


def face_charge_hours(db: Session, f: Face) -> float:
    """Оценка времени заряжания: масса ВВ по паспорту / производительность зарядной машины рудника."""
    if f.kind == "dev" and f.passport_id:
        dp = db.get(DevPassport, f.passport_id)
        kg = float((dp.indicators or {}).get("explosive_kg", 200)) if dp else 200
    elif f.ring_design_id:
        rd = db.get(RingDesign, f.ring_design_id)
        ind = (rd.indicators or {}) if rd else {}
        kg = float(ind.get("explosive_kg", 2000)) * 2 / max(float(ind.get("rings", 1)), 1)
    else:
        kg = 200
    ch = db.scalar(select(Machine).where(Machine.type == "charger", Machine.status.in_(("working", "idle"))))
    rate = float(((ch.params or {}).get("charge_kg_min") if ch else None) or 7)
    return round(kg / (rate * 60) + 0.3, 2)  # + установка зарядной машины


def blast_fit(db: Session, f: Face, machine: Machine | None, now: datetime | None = None) -> dict:
    """Успеют ли обурить и зарядить забой до ближайшего окна ВР текущей смены."""
    from core import shifts as sh

    cfg = active_mine(db).config
    tz = cfg.get("timezone", "UTC")
    now = now or utcnow()
    sc = shift_config(cfg)
    cur = sh.current(sc, now, tz)
    nxt = next((w for w in sh.windows(sc, cur["date"], cur["shift_no"], tz) if w["start"] > now), None)
    need = face_drill_hours(db, f, machine) + face_charge_hours(db, f)
    if not nxt:
        return {"fits_blast": False, "carry_over": True, "need_h": round(need, 2), "blast_at": None}
    left = (nxt["start"] - now).total_seconds() / 3600
    return {"fits_blast": need <= left, "carry_over": need > left, "need_h": round(need, 2),
            "blast_at": to_tz(nxt["start"], tz).strftime("%H:%M")}


def machine_face_issues(db: Session, machine: Machine, face: Face, drive: Working | None = None) -> list[dict]:
    """Машина и забой: диаметр и длина шпуров паспорта — в диапазоне машины; габариты и зона обуривания —
    по сечению выработки. Проверяется только то, что задано в параметрах машины."""
    pr = machine.params or {}
    num = lambda k: float(pr[k]) if isinstance(pr.get(k), (int, float)) else None  # noqa: E731
    out: list[dict] = []
    base = {"machine": machine.label, "face": face.name}
    d = length = None
    if face.kind == "dev" and face.passport_id:
        dp = db.get(DevPassport, face.passport_id)
        if dp:
            d = (dp.input or {}).get("hole_diameter")
            holes = (dp.design or {}).get("holes") or []
            length = max((h.get("length") or 0 for h in holes), default=None) or (dp.input or {}).get("hole_depth")
    elif face.ring_design_id:
        rd = db.get(RingDesign, face.ring_design_id)
        if rd:
            d = (rd.input or {}).get("hole_diameter")
            length = max((h.get("length") or 0 for r in (rd.design or {}).get("rings", []) for h in r.get("holes", [])),
                         default=None)
    dmin, dmax, lmax = num("dia_min"), num("dia_max"), num("max_length")
    if d and dmin is not None and dmax is not None and not dmin <= float(d) <= dmax:
        out.append({"level": "error", "code": "passport_diameter_range",
                    "params": {**base, "d": d, "min": dmin, "max": dmax}})
    if length and lmax is not None and float(length) > lmax + 1e-6:
        out.append({"level": "error", "code": "passport_length_over",
                    "params": {**base, "length": round(float(length), 2), "max": lmax}})
    w = db.get(Working, face.working_id) if face.kind == "dev" and face.working_id else drive  # веера — буровая выработка
    if w and w.section:
        sec = g.section_info(w.section)
        sw, sh = sec["width"], sec["height"]
        mw, mh = num("width_m"), num("height_m")
        if (mw and mw >= sw) or (mh and mh >= sh):
            out.append({"level": "error", "code": "machine_too_big",
                        "params": {**base, "mw": mw or "—", "mh": mh or "—", "sw": sw, "sh": sh}})
        cwmax, chmax, cwmin, chmin = num("cover_w_max"), num("cover_h_max"), num("cover_w_min"), num("cover_h_min")
        if (cwmax and sw > cwmax) or (chmax and sh > chmax):
            out.append({"level": "error", "code": "coverage_too_small",
                        "params": {**base, "sw": sw, "sh": sh, "cw": cwmax or "—", "ch": chmax or "—"}})
        if (cwmin and sw < cwmin) or (chmin and sh < chmin):
            out.append({"level": "error", "code": "section_below_min",
                        "params": {**base, "sw": sw, "sh": sh, "cw": cwmin or "—", "ch": chmin or "—"}})
    return out


def check_assignment(db: Session, person: Person | None, machine: Machine | None, face: Face | None, work_type: str,
                     when: datetime, exclude_assignment: int | None = None, order_id: int | None = None,
                     lang: str = "ru", L: q.Labels | None = None, direction: str | None = None) -> list[dict]:
    issues: list[dict] = []
    if work_type not in work_types(db):
        issues.append({"level": "error", "code": "bad_work_type"})
        return issues
    L = L or q.Labels(db, lang)
    need = WORK_MACHINE.get(work_type)
    works = q.type_works(db)
    types = q.fleet_types()
    drive = None
    # забой должен подходить виду работ, машина — виду работ и забою
    if face and WORK_FACE_KIND.get(work_type) and face.kind != WORK_FACE_KIND[work_type]:
        issues.append({"level": "error", "code": "work_face_mismatch",
                       "params": {"face": face.name, "work": L.work_label(work_type),
                                  "face_kind": i18n.t(f"dispatch.face_kind.{face.kind}", lang)}})
    if face and face.kind == "stope" and work_type == "ring_drilling":
        ri, opt = ring_issues(db, face, direction or default_direction(db, face), lang)
        issues += ri
        drive = opt["drive"] if opt else None
    if machine:
        if machine.type not in works or work_type not in works[machine.type]:
            issues.append({"level": "error", "code": "machine_wrong_type",
                           "params": {"machine": machine.label, "type": L.type_label(machine.type),
                                      "work": L.work_label(work_type)}})
        mk = types.get(machine.type, {}).get("faces")
        if face and mk and face.kind != mk:
            issues.append({"level": "error", "code": "face_kind_mismatch",
                           "params": {"machine": machine.label, "type": L.type_label(machine.type).lower(),
                                      "face": face.name, "face_kind": i18n.t(f"dispatch.face_kind_acc.{face.kind}", lang)}})
        if machine.status in ("repair", "maintenance"):
            issues.append({"level": "error", "code": "machine_in_repair", "params": {"machine": machine.label,
                                                                                     "status": machine.status}})
        if face and work_type in ("drilling", "ring_drilling") and (not mk or face.kind == mk):
            issues += machine_face_issues(db, machine, face, drive)
    elif need:
        issues.append({"level": "warning", "code": "machine_missing"})
    if person:
        warn = int((get_setting(db, "alerts") or {}).get("permit_warn_days", 14))
        permits = db.scalars(select(Permit).where(Permit.person_id == person.id)).all()
        issues += q.person_permit_issues(L, person, machine, work_type, when, permits, warn)
        if L.is_trainee(person):
            mentor = db.get(Person, person.mentor_id) if person.mentor_id else None
            if not mentor:
                issues.append({"level": "error", "code": "trainee_no_mentor", "params": {"person": person.full_name}})
            elif order_id and not db.scalar(select(Assignment).where(
                    Assignment.order_id == order_id, Assignment.active.is_(True), Assignment.person_id == mentor.id)):
                issues.append({"level": "error", "code": "trainee_mentor_absent",
                               "params": {"person": person.full_name, "mentor": mentor.full_name}})
    if person and order_id:
        bi = blast_in_progress(db, order_id, lang)
        if bi:
            issues.append({"level": "error", "code": "blast_in_progress", "params": bi})
    allowed = WORK_FACE_STATUS.get(work_type)
    if face and allowed and face.status not in allowed:
        code = "face_not_supported" if work_type in ("drilling", "ring_drilling") else "face_wrong_status"
        issues.append({"level": "error", "code": code, "params": {"face": face.name, "status": face.status}})
    if order_id:
        qa = select(Assignment).where(Assignment.order_id == order_id, Assignment.active.is_(True))
        for a in db.scalars(qa):
            if a.id == exclude_assignment:
                continue
            if person and a.person_id == person.id:
                issues.append({"level": "error", "code": "person_busy", "params": {"person": person.full_name}})
            if machine and a.machine_id == machine.id:
                # стажер работает на машине наставника — это не занятость машины
                shared = person is not None and ((L.is_trainee(person) and person.mentor_id == a.person_id)
                                                 or _is_trainee_of(db, L, a.person_id, person))
                if not shared:
                    issues.append({"level": "error", "code": "machine_busy", "params": {"machine": machine.label}})
    return issues


def blast_in_progress(db: Session, order_id: int | None, lang: str = "ru") -> dict | None:
    """Идет окно ВР, а наряд — на текущую смену → людей в забои не назначают («Идут ВР до 08:00»).
    Зона ВР «весь рудник»; варианты «горизонт» и «взрываемые забои» заложены в настройку blast_zone и пока
    действуют так же, как «весь рудник» (безопасная сторона)."""
    from core import shifts as sh

    cfg = active_mine(db).config
    tz = cfg.get("timezone", "UTC")
    now = utcnow()
    sc = shift_config(cfg)
    reentry = int(sc.get("reentry_min", 0))
    # окно ВР идет сейчас или кончилось, но время допуска людей после ВР еще не прошло
    w = sh.window_at(sc, now, tz) or sh.window_at(sc, now - timedelta(minutes=reentry), tz)
    if not w or now >= w["end"] + timedelta(minutes=reentry):
        return None
    o = db.get(ShiftOrder, order_id) if order_id else None
    cur = current_shift(cfg, now)
    if not o or (o.date, o.shift_no) != (cur["date"], cur["shift_no"]):
        return None
    until = w["end"] + timedelta(minutes=reentry)
    return {"until": to_tz(until, tz).strftime("%H:%M"), "zone": sc.get("blast_zone", "mine")}


def _is_trainee_of(db: Session, L: q.Labels, other_id: int | None, person: Person | None) -> bool:
    """Наставник может работать на той же машине, что и его стажер."""
    other = db.get(Person, other_id) if other_id else None
    return bool(other and person and L.is_trainee(other) and other.mentor_id == person.id)


def suggestions(db: Session, issues: list[dict], machine: Machine | None, work_type: str, when: datetime,
                order_id: int | None, L: q.Labels | None = None) -> dict:
    """Предложения замены: человек с действующими допусками на эту машину и работу, исправная машина того же типа."""
    L = L or q.Labels(db)
    busy_p, busy_m = set(), set()
    if order_id:
        for a in db.scalars(select(Assignment).where(Assignment.order_id == order_id, Assignment.active.is_(True))):
            busy_p.add(a.person_id)
            busy_m.add(a.machine_id)
    out: dict = {}
    codes = {i["code"] for i in issues}
    mtype = machine.type if machine else WORK_MACHINE.get(work_type)
    if codes & {"no_permit", "permit_expired", "person_busy", "trainee_no_mentor", "trainee_mentor_absent"}:
        permits = q.permits_by_person(db)
        out["persons"] = [{"id": p.id, "full_name": p.full_name} for p in db.scalars(select(Person).where(Person.active.is_(True)))
                          if p.id not in busy_p and not L.is_trainee(p)
                          and q.qualified(L, permits.get(p.id, []), machine, work_type, when)][:5]
    if codes & {"machine_in_repair", "machine_busy", "passport_diameter_range", "passport_length_over", "machine_too_big",
                "coverage_too_small", "section_below_min"} and mtype:
        out["machines"] = [{"id": m.id, "number": m.label} for m in db.scalars(select(Machine).where(
            Machine.type == mtype, Machine.status.in_(("working", "idle")))) if m.id not in busy_m
            and (not machine or m.id != machine.id)][:5]
    return out


def _order_out(db: Session, o: ShiftOrder, mine_cfg: dict, lang: str = "ru") -> dict:
    d = o.as_dict()
    L = q.Labels(db, lang)
    people = {p.id: p for p in db.scalars(select(Person))}
    machines = {m.id: m for m in db.scalars(select(Machine))}
    faces = {f.id: f for f in db.scalars(select(Face))}
    start, end = shift_bounds(mine_cfg, o.date, o.shift_no)
    rows = []
    for a in db.scalars(select(Assignment).where(Assignment.order_id == o.id).order_by(Assignment.id)):
        r = a.as_dict()
        p, m, f = people.get(a.person_id), machines.get(a.machine_id), faces.get(a.face_id)
        r.update(person_name=p.full_name if p else "", machine_number=m.label if m else "",
                 face_name=face_label(db, f, a.direction, lang),
                 face_status=f.status if f else "", machine_status=m.status if m else "",
                 work_label=L.work_label(a.work_type))
        if a.active:
            r["issues"] = check_assignment(db, p, m, f, a.work_type, start, a.id, o.id, lang, L, a.direction)
        rows.append(r)
    d["assignments"] = rows
    d["start"], d["end"] = start.isoformat(), end.isoformat()
    d["coverage"] = permit_coverage(db, L, o, start)
    return d


def permit_coverage(db: Session, L: q.Labels, o: ShiftOrder, when: datetime) -> list[dict]:
    """Модели исправных машин рудника, на которые в этой смене нет ни одного допущенного человека."""
    permits = q.permits_by_person(db)
    people = [p for p in db.scalars(select(Person).where(Person.active.is_(True), Person.shift == o.shift_no))
              if not L.is_trainee(p)]
    out, seen = [], set()
    for m in db.scalars(select(Machine).where(Machine.status.in_(("working", "idle"))).order_by(Machine.id)):
        key = (m.type, m.model_id)
        if key in seen:
            continue
        seen.add(key)
        targets = q.machine_targets(m)
        if not any(any(x.kind == "machine" and x.target in targets and q.aware(x.valid_to) >= when
                       for x in permits.get(p.id, [])) for p in people):
            out.append({"machine": L.machine_requirement(m), "shift_no": o.shift_no, "type": m.type, "model_id": m.model_id})
    return out


@router.get("/order")
def get_order(date_: str | None = Query(None, alias="date"), shift_no: int | None = None, db: Session = Depends(get_db),
              user: CurrentUser = Depends(VIEW)):
    m = active_mine(db)
    sh = current_shift(m.config)
    d, n = date_ or sh["date"], shift_no or sh["shift_no"]
    o = db.scalar(select(ShiftOrder).where(ShiftOrder.mine_id == m.id, ShiftOrder.date == d, ShiftOrder.shift_no == n))
    return {"date": d, "shift_no": n, "current": {"date": sh["date"], "shift_no": sh["shift_no"]},
            "order": _order_out(db, o, m.config, user.lang) if o else None, "work_types": work_types(db)}


def _prev_shift(cfg: dict, d: str, n: int) -> tuple[str, int]:
    from core import shifts

    return shifts.previous(shift_config(cfg), d, n, cfg.get("timezone", "UTC"))


@router.post("/order")
def create_order(body: dict, db: Session = Depends(get_db), user: CurrentUser = Depends(EDIT)):
    """Создать наряд; copy=yesterday — копия того же номера смены вчера, copy=previous — предыдущей смены."""
    m = active_mine(db)
    sh = current_shift(m.config)
    d, n = body.get("date") or sh["date"], int(body.get("shift_no") or sh["shift_no"])
    if db.scalar(select(ShiftOrder).where(ShiftOrder.mine_id == m.id, ShiftOrder.date == d, ShiftOrder.shift_no == n)):
        raise HTTPException(400, "errors.order_exists")
    o = ShiftOrder(mine_id=m.id, date=d, shift_no=n, status="draft", created_by=user.username)
    db.add(o)
    db.flush()
    copied, skipped = 0, []
    if body.get("copy"):
        if body["copy"] == "yesterday":
            sd, sn = (date.fromisoformat(d) - timedelta(days=1)).isoformat(), n
        else:
            sd, sn = _prev_shift(m.config, d, n)
        src = db.scalar(select(ShiftOrder).where(ShiftOrder.mine_id == m.id, ShiftOrder.date == sd, ShiftOrder.shift_no == sn))
        if src:
            # каждая строка проверяется заново (допуски, исправность, статус забоя); стажеры — после наставников
            when = shift_bounds(m.config, d, n)[0]
            L = q.Labels(db, user.lang)
            rows = list(db.scalars(select(Assignment).where(Assignment.order_id == src.id, Assignment.active.is_(True))))
            people = {p.id: p for p in db.scalars(select(Person))}
            rows.sort(key=lambda a: (a.person_id in people and L.is_trainee(people[a.person_id]), a.id))
            for a in rows:
                p, mc, f = people.get(a.person_id), db.get(Machine, a.machine_id) if a.machine_id else None, \
                    db.get(Face, a.face_id) if a.face_id else None
                issues = check_assignment(db, p, mc, f, a.work_type, when, None, o.id, user.lang, L, a.direction)
                errs = [i for i in issues if i["level"] == "error"]
                if errs:
                    skipped.append({"person": p.full_name if p else "", "machine": mc.label if mc else "",
                                    "face": f.name if f else "", "issues": errs})
                    continue
                db.add(Assignment(order_id=o.id, person_id=a.person_id, machine_id=a.machine_id, face_id=a.face_id,
                                  work_type=a.work_type, direction=a.direction))
                db.flush()
                copied += 1
    audit(db, user, "order_create", "order", o.id, {"date": d, "shift_no": n, "copied": copied, "skipped": len(skipped)})
    db.commit()
    return {**_order_out(db, o, m.config, user.lang), "copied": copied, "skipped": skipped}


@router.post("/order/{oid}/status")
def order_status(oid: int, body: dict, db: Session = Depends(get_db), user: CurrentUser = Depends(EDIT)):
    o = db.get(ShiftOrder, oid)
    if not o:
        raise HTTPException(404, "errors.not_found")
    o.status = body["status"]
    audit(db, user, "order_status", "order", oid, body)
    db.commit()
    return {"ok": True}


@router.post("/check")
def check(body: dict, db: Session = Depends(get_db), user: CurrentUser = Depends(VIEW)):
    m = active_mine(db)
    o = db.get(ShiftOrder, int(body["order_id"])) if body.get("order_id") else None
    when = shift_bounds(m.config, o.date, o.shift_no)[0] if o else utcnow()
    p = db.get(Person, int(body["person_id"])) if body.get("person_id") else None
    mc = db.get(Machine, int(body["machine_id"])) if body.get("machine_id") else None
    f = db.get(Face, int(body["face_id"])) if body.get("face_id") else None
    issues = check_assignment(db, p, mc, f, body.get("work_type", "drilling"), when, body.get("assignment_id"),
                              o.id if o else None, user.lang, direction=body.get("direction"))
    return {"issues": issues, "suggestions": suggestions(db, issues, mc, body.get("work_type", "drilling"), when,
                                                          o.id if o else None)}


@router.get("/candidates")
def candidates(work_type: str = "drilling", order_id: int | None = None, machine_id: int | None = None,
               person_id: int | None = None, assignment_id: int | None = None, db: Session = Depends(get_db),
               user: CurrentUser = Depends(VIEW)):
    """Списки окна «Назначить»: люди с допусками на выбранные машину и работу — первыми, остальные с причиной;
    машины, на которые у выбранного человека есть допуск, — первыми. Причины — на языке пользователя."""
    m = active_mine(db)
    o = db.get(ShiftOrder, order_id) if order_id else None
    when = shift_bounds(m.config, o.date, o.shift_no)[0] if o else utcnow()
    L = q.Labels(db, user.lang)
    warn = int((get_setting(db, "alerts") or {}).get("permit_warn_days", 14))
    permits = q.permits_by_person(db)
    busy_p, busy_m = {}, {}
    if o:
        for a in db.scalars(select(Assignment).where(Assignment.order_id == o.id, Assignment.active.is_(True))):
            if a.id != assignment_id:
                busy_p[a.person_id], busy_m[a.machine_id] = a, a
    mc = db.get(Machine, machine_id) if machine_id else None
    person = db.get(Person, person_id) if person_id else None
    tr = lambda i: i18n.t("errors." + i["code"], user.lang, **(i.get("params") or {}))  # noqa: E731
    persons = []
    for p in db.scalars(select(Person).where(Person.active.is_(True)).order_by(Person.full_name)):
        reasons = [tr(i) for i in q.person_permit_issues(L, p, mc, work_type, when, permits.get(p.id, []), warn)
                   if i["level"] == "error"]
        if L.is_trainee(p):
            mentor_on = p.mentor_id in busy_p
            if not mentor_on:
                reasons.append(tr({"code": "trainee_mentor_absent" if p.mentor_id else "trainee_no_mentor",
                                   "params": {"person": p.full_name, "mentor": (db.get(Person, p.mentor_id).full_name
                                                                                if p.mentor_id else "")}}))
        if p.id in busy_p:
            reasons.append(tr({"code": "person_busy", "params": {"person": p.full_name}}))
        persons.append({"id": p.id, "full_name": p.full_name, "professions": [L.prof_label(c) for c in p.professions or []],
                        "shift": p.shift, "ok": not reasons, "reasons": reasons})
    works = q.type_works(db)
    machines = []
    for x in db.scalars(select(Machine).order_by(Machine.type, Machine.id)):
        reasons = []
        if work_type not in works.get(x.type, []):
            continue  # машина не выполняет эту работу — в списке не показывается
        if x.status in ("repair", "maintenance"):
            reasons.append(tr({"code": "machine_in_repair", "params": {"machine": x.label, "status": i18n.t(
                f"fleet.status.{x.status}", user.lang)}}))
        if x.id in busy_m and not (person and _is_trainee_of(db, L, busy_m[x.id].person_id, person)) \
                and not (person and L.is_trainee(person) and person.mentor_id == busy_m[x.id].person_id):
            reasons.append(tr({"code": "machine_busy", "params": {"machine": x.label}}))
        if person:
            reasons += [tr(i) for i in q.person_permit_issues(L, person, x, work_type, when, permits.get(person.id, []), warn,
                                                              kinds=("machine",)) if i["level"] == "error"]
        machines.append({"id": x.id, "label": x.label, "model": L.machine_requirement(x), "type": x.type,
                         "status": x.status, "ok": not reasons, "reasons": list(dict.fromkeys(reasons))})
    persons.sort(key=lambda r: (not r["ok"], r["shift"] != (o.shift_no if o else r["shift"]), r["full_name"]))
    machines.sort(key=lambda r: (not r["ok"], r["label"]))
    return {"persons": persons, "machines": machines, "faces": face_candidates(db, work_type, mc, user.lang)}


def face_candidates(db: Session, work_type: str, mc: Machine | None, lang: str) -> list[dict]:
    """Забои для вида работ и машины: проходка — проходческие забои, веера — камера + направление
    (буровая выработка подставляется из проекта вееров). Неподходящие по статусу — с причиной."""
    allowed = WORK_FACE_STATUS.get(work_type)
    kind = WORK_FACE_KIND.get(work_type)
    mk = q.fleet_types().get(mc.type, {}).get("faces") if mc else None
    tr = lambda i: i18n.t("errors." + i["code"], lang, **(i.get("params") or {}))  # noqa: E731
    out = []
    for f in db.scalars(select(Face).where(Face.mine_id == active_mine(db).id).order_by(Face.priority, Face.name)):
        if f.status == "done" or (kind and f.kind != kind) or (mk and f.kind != mk):
            continue
        base = [] if not allowed or f.status in allowed else [
            tr({"code": "face_not_supported" if kind else "face_wrong_status",
                "params": {"face": f.name, "status": i18n.t(f"workflow.status.{f.status}", lang)}})]
        if f.kind == "stope" and work_type == "ring_drilling":
            for d in DIRECTIONS:
                ri, _ = ring_issues(db, f, d, lang)
                reasons = base + [tr(i) for i in ri]
                out.append({"key": f"{f.id}:{d}", "face_id": f.id, "direction": d, "label": face_label(db, f, d, lang),
                            "status": f.status, "ok": not reasons, "reasons": reasons})
        else:
            out.append({"key": str(f.id), "face_id": f.id, "direction": None, "label": f.name, "status": f.status,
                        "ok": not base, "reasons": base})
    out.sort(key=lambda r: not r["ok"])
    return out


def _apply_direction(db: Session, f: Face | None, work: str, direction: str | None) -> str | None:
    """Направление вееров сохраняется в назначении; проект вееров забоя переключается на это направление."""
    if not f or f.kind != "stope" or work != "ring_drilling":
        return None
    direction = direction or default_direction(db, f)
    opt = next((o for o in ring_options(db, f) if o["direction"] == direction), None)
    if opt and opt["design"] and f.status == "ready" and f.ring_design_id != opt["design"].id:
        f.ring_design_id = opt["design"].id
    return direction


@router.post("/order/{oid}/assign")
def assign(oid: int, body: dict, db: Session = Depends(get_db), user: CurrentUser = Depends(EDIT)):
    m = active_mine(db)
    o = db.get(ShiftOrder, oid)
    if not o:
        raise HTTPException(404, "errors.not_found")
    when = shift_bounds(m.config, o.date, o.shift_no)[0]
    p = db.get(Person, int(body["person_id"])) if body.get("person_id") else None
    mc = db.get(Machine, int(body["machine_id"])) if body.get("machine_id") else None
    f = db.get(Face, int(body["face_id"])) if body.get("face_id") else None
    issues = check_assignment(db, p, mc, f, body["work_type"], when, None, oid, user.lang, direction=body.get("direction"))
    errs = [i for i in issues if i["level"] == "error"]
    if errs:
        raise HTTPException(400, {"code": "errors." + errs[0]["code"], "params": errs[0].get("params", {}),
                                  "issues": issues, "suggestions": suggestions(db, issues, mc, body["work_type"], when, oid)})
    a = Assignment(order_id=oid, person_id=p.id if p else None, machine_id=mc.id if mc else None,
                   face_id=f.id if f else None, work_type=body["work_type"],
                   direction=_apply_direction(db, f, body["work_type"], body.get("direction")))
    db.add(a)
    if mc and f and f.working_id:
        mc.working_id = f.working_id
    audit(db, user, "assign", "order", oid, body)
    db.commit()
    publish("dm.dispatch.assign", "assign", {"machine": mc.label if mc else "", "person": p.full_name if p else "",
                                             "face": face_label(db, f, a.direction, "ru"), "work": body["work_type"]})
    return {"id": a.id, "issues": issues}


@router.delete("/assignments/{aid}")
def unassign(aid: int, db: Session = Depends(get_db), user: CurrentUser = Depends(EDIT)):
    a = db.get(Assignment, aid)
    if a:
        db.delete(a)
        audit(db, user, "unassign", "assignment", aid)
        db.commit()
    return {"ok": True}


@router.post("/reassign")
def reassign(body: dict, db: Session = Depends(get_db), user: CurrentUser = Depends(require("dispatch.edit",
                                                                                            "alerts.dispatch.act"))):
    """Перестановка в течение смены: человек на другую машину / машина в другой забой. Фиксируется время и автор."""
    m = active_mine(db)
    old = db.get(Assignment, int(body["assignment_id"]))
    if not old or not old.active:
        raise HTTPException(400, "errors.assignment_inactive")
    person_id = body.get("person_id", old.person_id)
    machine_id = body.get("machine_id", old.machine_id)
    face_id = body.get("face_id", old.face_id)
    work = body.get("work_type") or old.work_type
    p = db.get(Person, person_id) if person_id else None
    mc = db.get(Machine, machine_id) if machine_id else None
    f = db.get(Face, face_id) if face_id else None
    if f and work in ("drilling", "ring_drilling") and f.kind == "stope":
        work = "ring_drilling"
    direction = body.get("direction") or (old.direction if face_id == old.face_id and work == old.work_type else None)
    issues = check_assignment(db, p, mc, f, work, utcnow(), old.id, old.order_id, user.lang, direction=direction)
    errs = [i for i in issues if i["level"] == "error"]
    if errs:
        raise HTTPException(400, {"code": "errors." + errs[0]["code"], "params": errs[0].get("params", {}), "issues": issues})
    now = utcnow()
    old.active, old.ended_at = False, now
    new = Assignment(order_id=old.order_id, person_id=person_id, machine_id=machine_id, face_id=face_id, work_type=work,
                     started_at=now, direction=_apply_direction(db, f, work, direction))
    db.add(new)
    db.flush()
    change = {k: {"from": getattr(old, k), "to": v} for k, v in
              (("person_id", person_id), ("machine_id", machine_id), ("face_id", face_id), ("work_type", work),
               ("direction", new.direction))
              if getattr(old, k) != v}
    db.add(Reassignment(assignment_id=old.id, new_assignment_id=new.id, username=user.username, change=change,
                        reason=body.get("reason", "")))
    if mc and f and f.working_id:
        mc.working_id = f.working_id
    if body.get("alert_id"):
        al = db.get(Alert, int(body["alert_id"]))
        if al:
            al.status, al.resolved_by, al.resolved_at = "resolved", user.username, now
    audit(db, user, "reassign", "assignment", old.id, {"change": change, "alert_id": body.get("alert_id")})
    db.commit()
    publish("dm.dispatch.reassign", "reassign", {"machine": mc.label if mc else "", "person": p.full_name if p else "",
                                                 "face": f.name if f else "", "detail": str(change)})
    return {"id": new.id, "change": change, "ts": to_tz(now, m.config.get("timezone", "UTC")).isoformat()}


@router.post("/assignments/{aid}/progress")
def progress(aid: int, body: dict, db: Session = Depends(get_db), _: CurrentUser = Depends(require("workflow.transition"))):
    a = db.get(Assignment, aid)
    if not a:
        raise HTTPException(404, "errors.not_found")
    a.progress = {**(a.progress or {}), **body}
    db.commit()
    return {"ok": True}


@router.get("/board")
def board(level: float | None = None, work_type: str | None = None, db: Session = Depends(get_db),
          user: CurrentUser = Depends(VIEW)):
    """Табло «Смена сейчас»."""
    m = active_mine(db)
    tz = m.config.get("timezone", "UTC")
    sh = current_shift(m.config)
    o = db.scalar(select(ShiftOrder).where(ShiftOrder.mine_id == m.id, ShiftOrder.date == sh["date"],
                                           ShiftOrder.shift_no == sh["shift_no"]))
    rows = []
    if o:
        people = {p.id: p for p in db.scalars(select(Person))}
        machines = {x.id: x for x in db.scalars(select(Machine))}
        faces = {x.id: x for x in db.scalars(select(Face))}
        works = {x.id: x for x in db.scalars(select(Working))}
        for a in db.scalars(select(Assignment).where(Assignment.order_id == o.id, Assignment.active.is_(True))):
            f = faces.get(a.face_id)
            w = works.get(f.working_id) if f and f.working_id else None
            lvl = w.level if w else (db.get(Stope, f.stope_id).level_bottom if f and f.stope_id else None)
            if level is not None and lvl != level:
                continue
            if work_type and a.work_type != work_type:
                continue
            pr = a.progress or {}
            eta = pr.get("eta")
            rows.append({
                "assignment_id": a.id, "person": people[a.person_id].full_name if a.person_id in people else "",
                "machine": machines[a.machine_id].label if a.machine_id in machines else "",
                "machine_id": a.machine_id, "person_id": a.person_id,
                "machine_type": machines[a.machine_id].type if a.machine_id in machines else "",
                "face": face_label(db, f, a.direction, user.lang), "face_id": f.id if f else None,
                "face_status": f.status if f else "",
                "level": lvl, "work_type": a.work_type, "progress": pr,
                "eta_mine": to_tz(datetime.fromisoformat(eta), tz).strftime("%H:%M") if eta else None,
                "eta_user": to_tz(datetime.fromisoformat(eta), user.tz).strftime("%H:%M") if eta else None,
            })
    return {"shift": {k: (v.isoformat() if hasattr(v, "isoformat") else v) for k, v in sh.items()},
            "order_id": o.id if o else None, "rows": rows}


@router.get("/ready-faces")
def ready_faces(machine_id: int | None = None, face_id: int | None = None, db: Session = Depends(get_db),
                _: CurrentUser = Depends(VIEW)):
    """Забои «Готов к бурению» по приоритету и расстоянию от текущего забоя машины; хватит ли времени до конца смены."""
    m = active_mine(db)
    sh = current_shift(m.config)
    mc = db.get(Machine, machine_id) if machine_id else None
    kind = (q.fleet_types().get(mc.type, {}).get("faces") if mc else None) or "dev"
    origin = None
    if face_id:
        f0 = db.get(Face, face_id)
        origin = face_position(db, f0) if f0 else None
    busy = {a.face_id for a in db.scalars(select(Assignment).where(Assignment.active.is_(True),
                                                                   Assignment.work_type.in_(("drilling", "ring_drilling"))))}
    left_h = max(0.0, (sh["end"] - utcnow()).total_seconds() / 3600)
    out = []
    for f in db.scalars(select(Face).where(Face.mine_id == m.id, Face.status == "ready", Face.kind == kind)):
        if f.id in busy:
            continue
        pos = face_position(db, f)
        dist = math.dist(origin, pos) if origin and pos else None
        hours = face_drill_hours(db, f, mc)
        # машина и забой несовместимы (диаметр, длина, габариты, буровая выработка камеры) — в конец списка с причиной
        issues = [i for i in check_assignment(db, None, mc, f, "drilling" if f.kind == "dev" else "ring_drilling",
                                              utcnow()) if i["level"] == "error"] if mc else []
        out.append({"face_id": f.id, "name": f.name, "priority": f.priority, "distance_m": round(dist, 0) if dist else None,
                    "drill_hours": hours, "fits_shift": hours <= left_h, "ok": not issues,
                    "issues": [i["code"] for i in issues], **blast_fit(db, f, mc)})
    out.sort(key=lambda r: (not r["ok"], r["priority"], r["distance_m"] or 0))
    return {"left_hours": round(left_h, 2), "faces": out}


@router.get("/reassignments")
def reassignments(limit: int = 100, db: Session = Depends(get_db), _: CurrentUser = Depends(VIEW)):
    return [r.as_dict() for r in db.scalars(select(Reassignment).order_by(Reassignment.id.desc()).limit(limit))]
