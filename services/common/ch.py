"""ClickHouse: клиент и схема аналитических таблиц."""
from __future__ import annotations

import logging
from functools import lru_cache

from .settings import get_settings

log = logging.getLogger("clickhouse")

SCHEMA = [
    """CREATE TABLE IF NOT EXISTS events (
        ts DateTime64(3, 'UTC'), type LowCardinality(String), entity String, machine String,
        person String, face String, value Float64, payload String
    ) ENGINE = MergeTree ORDER BY (type, ts) TTL toDateTime(ts) + INTERVAL 90 DAY""",
    """CREATE TABLE IF NOT EXISTS telemetry (
        ts DateTime64(3, 'UTC'), machine String, machine_type LowCardinality(String),
        status LowCardinality(String), face String, operator String, x Float32, y Float32, z Float32,
        engine_hours Float32
    ) ENGINE = MergeTree ORDER BY (machine, ts) TTL toDateTime(ts) + INTERVAL 30 DAY""",
    """CREATE TABLE IF NOT EXISTS drilling (
        ts DateTime64(3, 'UTC'), machine String, machine_type LowCardinality(String), operator String,
        face String, kind LowCardinality(String), hole String, design_length Float32, length Float32,
        deviation_pct Float32, angle_dev_deg Float32, rate_mph Float32
    ) ENGINE = MergeTree ORDER BY (machine, ts)""",
    """CREATE TABLE IF NOT EXISTS cycles (
        ts DateTime64(3, 'UTC'), face String, working String, level Float32, cycle UInt32,
        machine String, operator String, advance Float32, design_advance Float32, kish Float32,
        overbreak_pct Float32, extra_m3 Float32, extra_t Float32, extra_cost Float32,
        explosive_plan_kg Float32, explosive_fact_kg Float32, half_cast_pct Float32, cause LowCardinality(String)
    ) ENGINE = MergeTree ORDER BY (face, ts)""",
    """CREATE TABLE IF NOT EXISTS stopes (
        ts DateTime64(3, 'UTC'), stope String, level Float32, blasted_t Float32, dilution_t Float32,
        dilution_pct Float32, loss_t Float32, loss_pct Float32, elos_hw Float32, elos_fw Float32,
        result_usd Float32, explosive_plan_kg Float32, explosive_fact_kg Float32, cause LowCardinality(String)
    ) ENGINE = MergeTree ORDER BY (stope, ts)""",
    """CREATE TABLE IF NOT EXISTS dispatch (
        ts DateTime64(3, 'UTC'), kind LowCardinality(String), machine String, person String,
        face String, detail String
    ) ENGINE = MergeTree ORDER BY (kind, ts)""",
    """CREATE TABLE IF NOT EXISTS ai (
        ts DateTime64(3, 'UTC'), username String, module LowCardinality(String), provider LowCardinality(String),
        model String, tokens_in UInt32, tokens_out UInt32, cost Float32, cache_hit UInt8
    ) ENGINE = MergeTree ORDER BY ts""",
    """CREATE TABLE IF NOT EXISTS face_status (
        ts DateTime64(3, 'UTC'), face String, kind LowCardinality(String), status LowCardinality(String),
        username String
    ) ENGINE = MergeTree ORDER BY (face, ts)""",
]


@lru_cache
def client():
    import clickhouse_connect

    s = get_settings()
    return clickhouse_connect.get_client(host=s.ch_host, port=8123, username=s.ch_user, password=s.ch_password,
                                         database=s.ch_database, connect_timeout=5, send_receive_timeout=30)


def ensure_schema() -> None:
    import clickhouse_connect

    st = get_settings()
    boot = clickhouse_connect.get_client(host=st.ch_host, port=8123, username=st.ch_user, password=st.ch_password,
                                         connect_timeout=5)
    boot.command(f"CREATE DATABASE IF NOT EXISTS {st.ch_database}")
    client.cache_clear()
    c = client()
    for ddl in SCHEMA:
        c.command(ddl)
    drop_yo(c)


def drop_yo(c) -> None:
    """«е» с точками (U+0451/U+0401) в продукте не используется: в накопленных событиях — замена на «е».
    Мутация запускается только для столбцов, где буква есть (ключи сортировки не меняются)."""
    yo, big = chr(0x451), chr(0x401)
    cols = c.query("SELECT table, name FROM system.columns WHERE database = currentDatabase() "
                   "AND type LIKE '%String%' AND is_in_sorting_key = 0").result_rows
    for table, col in cols:
        has = f"position(`{col}`, '{yo}') > 0 OR position(`{col}`, '{big}') > 0"
        try:
            if c.query(f"SELECT count() FROM `{table}` WHERE {has}").result_rows[0][0]:
                c.command(f"ALTER TABLE `{table}` UPDATE `{col}` = replaceAll(replaceAll(`{col}`, '{yo}', 'е'), "
                          f"'{big}', '{chr(0x415)}') WHERE {has}")
        except Exception as e:  # не мешает запуску сервиса
            log.warning("clickhouse %s.%s: %s", table, col, e)


def query(sql: str, params: dict | None = None) -> list[dict]:
    r = client().query(sql, parameters=params or {})
    return [dict(zip(r.column_names, row)) for row in r.result_rows]
