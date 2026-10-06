"""Сервис alerts: правила раздела 16 (диспетчер, инженер, администратор) → таблица alerts + Telegram.
Проверка раз в 30 с; алерт закрывается автоматически, когда условие пропало."""
from __future__ import annotations

import asyncio
import logging
from datetime import timedelta

import httpx
from sqlalchemy import select

from common import i18n
from common.db import session_scope
from common.models import Alert, Analysis, Assignment, ChargeLog, DrillReport, Face, Machine, Permit, Person, Setting, ShiftOrder
from common.security import decrypt
from common.settings import get_settings
from common.timeutil import current_shift, utcnow
from common.web import EVENTS, create_app

log = logging.getLogger("alerts")
app = create_app("alerts")
INTERVAL = 30
DRILL_WORK = ("drilling", "ring_drilling")


def _setting(db, key: str, default=None):
    s = db.get(Setting, key)
    return (s.value or {}).get("v", default) if s else default


def _aware(dt):
    from datetime import timezone

    return dt if dt is None or dt.tzinfo else dt.replace(tzinfo=timezone.utc)


class Ctx:
    def __init__(self, db):
        self.db = db
        self.th = _setting(db, "alerts", {}) or {}
        from common.models import Mine

        m = db.scalar(select(Mine).where(Mine.active.is_(True))) or db.scalar(select(Mine))
        self.mine = m
        self.shift = current_shift(m.config) if m else None
        self.found: dict[str, dict] = {}
        emu = _setting(db, "emulator", {}) or {}
        # при работающем эмуляторе длительности сжаты — пороги времени масштабируются его скоростью
        self.time_scale = float(emu.get("speed", 1)) if emu.get("running") else 1.0

    def fire(self, rule: str, audience: str, key: str, params: dict, severity: str = "warning", entity: str = "",
             actions: list | None = None) -> None:
        self.found[f"{rule}:{key}"] = {"rule": rule, "audience": audience, "params": params, "severity": severity,
                                       "entity": entity, "actions": actions or []}


# ---------------- диспетчер ----------------
def _active_assignments(c: Ctx) -> list[Assignment]:
    if not c.shift:
        return []
    o = c.db.scalar(select(ShiftOrder).where(ShiftOrder.mine_id == c.mine.id, ShiftOrder.date == c.shift["date"],
                                             ShiftOrder.shift_no == c.shift["shift_no"]))
    if not o:
        return []
    return list(c.db.scalars(select(Assignment).where(Assignment.order_id == o.id, Assignment.active.is_(True))))


def rules_dispatcher(c: Ctx, asg: list[Assignment]) -> None:
    from api import qualify as q
    from api.routers.dispatch import blast_fit, face_drill_hours, face_position  # общая логика с API

    db = c.db
    now = utcnow()
    left_h = (c.shift["end"] - now).total_seconds() / 3600
    faces = {f.id: f for f in db.scalars(select(Face))}
    machines = {m.id: m for m in db.scalars(select(Machine))}
    people = {p.id: p for p in db.scalars(select(Person))}
    busy = {a.face_id for a in asg if a.work_type in DRILL_WORK}
    L = q.Labels(db, "ru")
    permits = q.permits_by_person(db)
    for a in asg:
        f, m = faces.get(a.face_id), machines.get(a.machine_id)
        p = people.get(a.person_id)
        # 1. буровая свободна раньше конца смены
        if a.work_type in DRILL_WORK and f and m and f.status not in ("ready", "drilling"):
            kind = q.fleet_types().get(m.type, {}).get("faces") or "dev"
            pos0 = face_position(db, f)
            cands = []
            for rf in faces.values():
                if rf.status != "ready" or rf.kind != kind or rf.id in busy:
                    continue
                hrs = face_drill_hours(db, rf, m)
                pos = face_position(db, rf)
                dist = sum((x - y) ** 2 for x, y in zip(pos0, pos)) ** 0.5 if pos0 and pos else None
                cands.append({"face_id": rf.id, "name": rf.name, "priority": rf.priority, "hours": hrs,
                              "distance_m": round(dist) if dist is not None else None, **blast_fit(db, rf, m, now)})
            fits = [x for x in cands if x["hours"] <= left_h]
            if fits:
                fits.sort(key=lambda x: (x["priority"], x["distance_m"] or 0))
                c.fire("rig_free_early", "dispatcher", f"{a.id}",
                       {"machine": m.label, "face": f.name, "left_h": round(left_h, 1), "next": fits[0]["name"],
                        "candidates": fits[:5], "assignment_id": a.id}, "warning", m.label,
                       [{"type": "reassign", "assignment_id": a.id}])
        # 5. нет действующего допуска на машину (модель или тип) и на вид работ
        if p:
            errs = [i for i in q.person_permit_issues(L, p, m, a.work_type, now, permits.get(p.id, []))
                    if i["level"] == "error"]
            if errs:
                c.fire("no_permit", "dispatcher", f"{a.id}", {"person": p.full_name, "machine": m.label if m else "",
                                                              "what": "; ".join(i["params"]["what"] for i in errs)},
                       "critical", p.full_name, [{"type": "replace_person", "assignment_id": a.id}])
        # 6. машина в ремонте назначена
        if m and m.status in ("repair", "maintenance"):
            c.fire("machine_in_repair", "dispatcher", f"{a.id}", {"machine": m.label, "status": m.status}, "critical",
                   m.label, [{"type": "replace_machine", "assignment_id": a.id}])
    # 2. машина простаивает (нет телеметрии больше N минут)
    idle_min = max(2.0, float(c.th.get("machine_idle_minutes", 30)) / c.time_scale)
    try:
        from common import ch

        rows = ch.query("SELECT machine, max(ts) AS last, argMax(status, ts) AS st FROM telemetry "
                        "WHERE ts > now() - INTERVAL 1 DAY GROUP BY machine")
        last = {r["machine"]: r for r in rows}
        for a in asg:
            m = machines.get(a.machine_id)
            if not m or m.label not in last:  # телеметрия идёт по названию машины
                continue
            r = last[m.label]
            age = (now - _aware(r["last"])).total_seconds() / 60
            if age > idle_min or r["st"] == "idle_long":
                c.fire("machine_idle", "dispatcher", m.number, {"machine": m.label, "minutes": round(age)}, "warning",
                       m.label, [{"type": "idle_reason", "machine": m.number}])
    except Exception as e:
        log.debug("clickhouse: %s", e)
    # 7. планирование наряда: нет ни одного допущенного человека на модель исправной машины в смене
    from api.routers.dispatch import permit_coverage
    from common.timeutil import shift_bounds

    cur = (c.shift["date"], c.shift["shift_no"])
    for o in db.scalars(select(ShiftOrder).where(ShiftOrder.mine_id == c.mine.id, ShiftOrder.status != "closed",
                                                 ShiftOrder.date >= c.shift["date"])):
        if (o.date, o.shift_no) < cur:
            continue
        for gap in permit_coverage(db, L, o, shift_bounds(c.mine.config, o.date, o.shift_no)[0]):
            c.fire("no_qualified_staff", "dispatcher", f"{o.id}:{gap['type']}:{gap['model_id']}",
                   {"machine": gap["machine"], "shift_no": o.shift_no, "date": o.date}, "warning", gap["machine"],
                   [{"type": "open_staff"}])
    # 8. Забой заряжен, а окно ВР прошло → «Ждёт ВР», алерт с ближайшим окном
    from api.deps import CurrentUser
    from api.routers.workflow import _set_status
    from common.timeutil import shift_config, to_tz
    from core import shifts as shm

    tz = c.mine.config.get("timezone", "UTC")
    sc = shift_config(c.mine.config)
    system = CurrentUser(None, "system", "service", set(), service=True)
    for f in faces.values():
        if f.status == "charged" and f.status_since and shm.windows_between(sc, _aware(f.status_since), now, tz):
            _set_status(db, f, "wait_blast", system, "окно ВР прошло — взрыв перенесён")
        if f.status == "wait_blast":
            nxt = shm.next_window(sc, now, tz)
            c.fire("blast_moved", "dispatcher", f"{f.id}:{f.cycle_no}",
                   {"face": f.name, "next": to_tz(nxt["start"], tz).strftime("%H:%M") if nxt else "—",
                    "next_date": to_tz(nxt["start"], tz).strftime("%d.%m") if nxt else ""}, "warning", f.name)
    # 3. забой ждёт взрывников
    wait_h = float(c.th.get("blasters_wait_hours", 2)) / c.time_scale
    for f in faces.values():
        if f.status == "handed" and f.status_since and (now - _aware(f.status_since)).total_seconds() / 3600 > wait_h:
            c.fire("blasters_wait", "dispatcher", f"{f.id}:{f.cycle_no}",
                   {"face": f.name, "hours": round((now - _aware(f.status_since)).total_seconds() / 3600 * c.time_scale, 1)},
                   "warning",
                   f.name, [{"type": "notify"}])
    # 4. нет готовых забоев на следующую смену
    drills = [m for m in machines.values() if m.type == "dev_drill" and m.status in ("working", "idle")]
    ready = [f for f in faces.values() if f.kind == "dev" and f.status == "ready"]
    if len(ready) < len(drills):
        bott = {}
        for f in faces.values():
            if f.kind == "dev" and f.status in ("mucking", "scaling", "support", "surveyed", "blasted", "ventilation", "handed"):
                bott[f.status] = bott.get(f.status, 0) + 1
        c.fire("no_ready_faces", "dispatcher", c.shift["date"] + str(c.shift["shift_no"]),
               {"ready": len(ready), "drills": len(drills),
                "bottlenecks": ", ".join(f"{i18n.t('workflow.status.' + k, 'ru')}: {v}" for k, v in bott.items())},
               "info", "", [{"type": "show_bottlenecks"}])


# ---------------- инженер ----------------
def rules_engineer(c: Ctx) -> None:
    db = c.db
    now = utcnow()
    th = c.th
    faces = {f.id: f for f in db.scalars(select(Face))}
    recent = list(db.scalars(select(Analysis).where(Analysis.created_at >= now - timedelta(days=2))
                             .order_by(Analysis.id.desc())))
    by_face: dict[int, list[Analysis]] = {}
    for a in recent:
        by_face.setdefault(a.face_id, []).append(a)
    kmin = float(th.get("kish_min", 0.8))
    for fid, lst in by_face.items():
        f = faces.get(fid)
        name = f.name if f else str(fid)
        dev = [a for a in lst if a.kind == "dev"]
        if len(dev) >= 2 and all((a.result.get("kish") or 1) < kmin for a in dev[:2]):
            c.fire("kish_low", "engineer", f"{fid}:{dev[0].cycle_no}", {"face": name, "kish": dev[0].result["kish"],
                                                                          "min": kmin}, "warning", name)
        if dev and dev[0].result.get("overbreak_pct", 0) > float(th.get("overbreak_pct_max", 15)):
            c.fire("overbreak_high", "engineer", f"{fid}:{dev[0].cycle_no}",
                   {"face": name, "pct": dev[0].result["overbreak_pct"], "extra_t": dev[0].result.get("extra_t"),
                    "cost": dev[0].result.get("extra_cost")}, "warning", name)
        st = [a for a in lst if a.kind == "stope"]
        if st:
            el = max(st[0].result.get("elos_hw", 0), st[0].result.get("elos_fw", 0))
            if el > float(th.get("elos_max_m", 1.0)):
                c.fire("elos_high", "engineer", f"{fid}:{st[0].cycle_no}", {"stope": name, "elos": round(el, 2)},
                       "warning", name)
    day_t = sum(a.result.get("extra_t", 0) for a in recent if a.kind == "dev" and a.created_at and
                _aware(a.created_at) >= now - timedelta(days=1))
    if day_t > float(th.get("extra_rock_t_per_day_max", 150)):
        c.fire("extra_rock_day", "engineer", now.strftime("%Y-%m-%d"), {"t": round(day_t)}, "warning")
    for r in db.scalars(select(DrillReport).where(DrillReport.received_at >= now - timedelta(days=1))):
        if r.summary.get("mean_deviation_pct", 0) > float(th.get("drill_deviation_pct_max", 3)):
            f = faces.get(r.face_id)
            c.fire("drill_deviation", "engineer", f"{r.id}", {"face": f.name if f else "", "pct": r.summary["mean_deviation_pct"]},
                   "warning", f.name if f else "")
    for cl in db.scalars(select(ChargeLog).where(ChargeLog.created_at >= now - timedelta(days=1))):
        if cl.summary.get("over_pct", 0) > float(th.get("charge_over_pct_max", 10)):
            f = faces.get(cl.face_id)
            c.fire("charge_over", "engineer", f"{cl.id}", {"face": f.name if f else "", "pct": cl.summary["over_pct"]},
                   "warning", f.name if f else "")
    # предупреждение о допусках за 14 дней
    from api import qualify as q

    L = q.Labels(db, "ru")
    warn = int(th.get("permit_warn_days", 14))
    people = {p.id: p for p in db.scalars(select(Person))}
    for pm in db.scalars(select(Permit)):
        vt = _aware(pm.valid_to)
        if now <= vt < now + timedelta(days=warn):
            p = people.get(pm.person_id)
            c.fire("permit_expiring", "engineer", f"{pm.id}", {"person": p.full_name if p else "",
                                                               "target": L.target_label(pm.kind, pm.target),
                                                               "days": (vt - now).days}, "info", p.full_name if p else "")


# ---------------- технические ----------------
def rules_tech(c: Ctx) -> None:
    s = get_settings()
    th = c.th
    queries = {
        "service_down": 'up{namespace="digital-mine"} == 0',
        "latency": f'max(dm_ingest_lag_seconds) > {float(th.get("tech_latency_s", 60))}',
        "pod_memory": ('max by (pod) (container_memory_working_set_bytes{namespace=~"digital-mine|monitoring",container!=""} '
                       '/ on (pod, container) group_left kube_pod_container_resource_limits{resource="memory"}) * 100 > '
                       f'{float(th.get("tech_pod_memory_pct", 90))}'),
        "disk": ('max by (mountpoint) (100 - node_filesystem_avail_bytes{fstype!~"tmpfs|overlay"} * 100 / '
                 f'node_filesystem_size_bytes{{fstype!~"tmpfs|overlay"}}) > {float(th.get("tech_disk_pct", 85))}'),
    }
    for rule, q in queries.items():
        try:
            r = httpx.get(f"{s.prometheus_url}/api/v1/query", params={"query": q}, timeout=5).json()
            for x in r["data"]["result"]:
                lab = x["metric"]
                ent = lab.get("app_kubernetes_io_component") or lab.get("pod") or lab.get("mountpoint") or lab.get("job", "")
                c.fire(f"tech_{rule}", "admin", ent or rule, {"entity": ent, "value": round(float(x["value"][1]), 1)},
                       "critical", ent)
        except Exception as e:
            log.debug("prometheus %s: %s", rule, e)


# ---------------- цикл ----------------
def telegram(db, alerts: list[Alert]) -> None:
    tg = _setting(db, "telegram", {}) or {}
    s = get_settings()
    token = decrypt(tg["bot_token_enc"]) if tg.get("bot_token_enc") else s.telegram_bot_token
    chat = tg.get("chat_id") or s.telegram_chat_id
    lang = _setting(db, "default_language", "ru") or "ru"
    if not token or not chat or not tg.get("enabled", bool(s.telegram_bot_token)):
        return
    for a in alerts:
        text = f"⚠ {i18n.t(f'alerts.rules.{a.rule}.title', lang, **a.params)}\n{i18n.t(f'alerts.rules.{a.rule}.text', lang, **a.params)}"
        try:
            httpx.post(f"https://api.telegram.org/bot{token}/sendMessage", json={"chat_id": chat, "text": text}, timeout=10)
            a.notified = True
        except Exception as e:
            log.warning("telegram: %s", e)


def evaluate() -> dict:
    with session_scope() as db:
        c = Ctx(db)
        if not c.mine:
            return {}
        asg = _active_assignments(c)
        for fn in (lambda: rules_dispatcher(c, asg), lambda: rules_engineer(c), lambda: rules_tech(c)):
            try:
                fn()
            except Exception:
                log.exception("rule group failed")
        open_rows = {a.dedup_key: a for a in db.scalars(select(Alert).where(Alert.status.in_(("open", "ack"))))}
        new = []
        for key, d in c.found.items():
            if key in open_rows:
                open_rows[key].params = d["params"]
                continue
            recent = db.scalar(select(Alert).where(Alert.dedup_key == key, Alert.status == "resolved",
                                                   Alert.resolved_at >= utcnow() - timedelta(minutes=30)))
            if recent:
                continue
            a = Alert(rule=d["rule"], audience=d["audience"], severity=d["severity"], params=d["params"],
                      entity=d["entity"], dedup_key=key, actions=d["actions"])
            db.add(a)
            new.append(a)
        for key, a in open_rows.items():
            if key not in c.found and a.rule not in ("blasters_wait",):
                a.status, a.resolved_by, a.resolved_at = "resolved", "system", utcnow()
        db.flush()
        telegram(db, new)
        EVENTS.labels("alerts", "fired").inc(len(new))
        return {"new": len(new), "active": len(c.found)}


async def loop() -> None:
    await asyncio.sleep(20)
    while True:
        try:
            res = await asyncio.to_thread(evaluate)
            if res.get("new"):
                log.info("alerts: %s", res)
        except Exception:
            log.exception("alerts loop")
        await asyncio.sleep(INTERVAL)


@app.on_event("startup")
async def start() -> None:
    asyncio.get_event_loop().create_task(loop())


@app.post("/alerts/evaluate")
def run_now():
    return evaluate()
