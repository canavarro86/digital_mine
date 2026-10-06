"""Сервис ingest: события из NATS JetStream → ClickHouse (пакетная вставка). Несколько копий делят durable-консьюмер (HPA)."""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone

from prometheus_client import Gauge

from common import ch
from common.bus import STREAM, connect
from common.web import EVENTS, QUEUE, create_app

log = logging.getLogger("ingest")
app = create_app("ingest")
LAG = Gauge("dm_ingest_lag_seconds", "Задержка обработки событий (сейчас − время события)")
BATCH = 500

TABLES = {
    "telemetry": ("telemetry", ["ts", "machine", "machine_type", "status", "face", "operator", "x", "y", "z", "engine_hours"]),
    "drill_hole": ("drilling", ["ts", "machine", "machine_type", "operator", "face", "kind", "hole", "design_length",
                                "length", "deviation_pct", "angle_dev_deg", "rate_mph"]),
    "cycle": ("cycles", ["ts", "face", "working", "level", "cycle", "machine", "operator", "advance", "design_advance",
                         "kish", "overbreak_pct", "extra_m3", "extra_t", "extra_cost", "explosive_plan_kg",
                         "explosive_fact_kg", "half_cast_pct", "cause"]),
    "stope": ("stopes", ["ts", "stope", "level", "blasted_t", "dilution_t", "dilution_pct", "loss_t", "loss_pct", "elos_hw",
                         "elos_fw", "result_usd", "explosive_plan_kg", "explosive_fact_kg", "cause"]),
    "ai": ("ai", ["ts", "username", "module", "provider", "model", "tokens_in", "tokens_out", "cost", "cache_hit"]),
    "face_status": ("face_status", ["ts", "face", "kind", "status", "username"]),
}
DISPATCH = {"assign", "reassign", "idle", "idle_reason"}
NUM = {"x", "y", "z", "engine_hours", "design_length", "length", "deviation_pct", "angle_dev_deg", "rate_mph", "level",
       "cycle", "advance", "design_advance", "kish", "overbreak_pct", "extra_m3", "extra_t", "extra_cost",
       "explosive_plan_kg", "explosive_fact_kg", "half_cast_pct", "blasted_t", "dilution_t", "dilution_pct", "loss_t",
       "loss_pct", "elos_hw", "elos_fw", "result_usd", "tokens_in", "tokens_out", "cost", "cache_hit"}
INTS = {"cycle", "tokens_in", "tokens_out", "cache_hit"}


def _ts(v) -> datetime:
    try:
        d = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except ValueError:
        return datetime.now(timezone.utc)


def _val(col: str, v):
    if col == "ts":
        return _ts(v)
    if col in NUM:
        try:
            x = float(v or 0)
        except (TypeError, ValueError):
            x = 0.0
        return int(x) if col in INTS else x
    return "" if v is None else str(v)


def rows_for(events: list[dict]) -> dict[str, tuple[list[str], list[list]]]:
    out: dict[str, tuple[list[str], list[list]]] = {}
    for e in events:
        t = e.get("type", "")
        if t in TABLES:
            table, cols = TABLES[t]
            out.setdefault(table, (cols, []))[1].append([_val(c, e.get(c)) for c in cols])
        if t in DISPATCH:
            cols = ["ts", "kind", "machine", "person", "face", "detail"]
            out.setdefault("dispatch", (cols, []))[1].append([_ts(e.get("ts")), t, str(e.get("machine", "")),
                                                              str(e.get("person", "")), str(e.get("face", "")),
                                                              str(e.get("detail", e.get("work", "")))])
        if t != "telemetry":
            cols = ["ts", "type", "entity", "machine", "person", "face", "value", "payload"]
            out.setdefault("events", (cols, []))[1].append([
                _ts(e.get("ts")), t, str(e.get("stope") or e.get("face") or e.get("working") or ""),
                str(e.get("machine", "")), str(e.get("person") or e.get("operator") or e.get("username") or ""),
                str(e.get("face", "")), float(e.get("value") or 0), json.dumps(e, ensure_ascii=False)[:4000]])
    return out


async def worker() -> None:
    while True:
        try:
            await asyncio.to_thread(ch.ensure_schema)
            nc, js = await connect()
            sub = await js.pull_subscribe("dm.>", durable="ingest", stream=STREAM)
            log.info("ingest: подписка на %s", STREAM)
            client = ch.client()
            while True:
                try:
                    msgs = await sub.fetch(BATCH, timeout=2)
                except asyncio.TimeoutError:
                    msgs = []
                if msgs:
                    events = []
                    for m in msgs:
                        try:
                            events.append(json.loads(m.data))
                        except ValueError:
                            pass
                    for table, (cols, rows) in rows_for(events).items():
                        await asyncio.to_thread(client.insert, table, rows, column_names=cols)
                    for m in msgs:
                        await m.ack()
                    EVENTS.labels("ingest", "processed").inc(len(msgs))
                    last = max((_ts(e.get("ts")) for e in events), default=None)
                    if last:
                        LAG.set(max(0.0, (datetime.now(timezone.utc) - last).total_seconds()))
                else:
                    LAG.set(0)
                try:
                    info = await sub.consumer_info()
                    QUEUE.labels("ingest", "dm").set(info.num_pending)
                except Exception:
                    pass
        except Exception as e:
            log.warning("ingest: ошибка %s, переподключение через 5 с", e)
            await asyncio.sleep(5)


@app.on_event("startup")
async def start() -> None:
    asyncio.get_event_loop().create_task(worker())
