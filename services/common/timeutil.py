"""Время: в базе UTC; смены и отчеты — по часовому поясу рудника."""
from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def to_tz(dt: datetime, tz: str) -> datetime:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(ZoneInfo(tz))


def shift_config(mine_cfg: dict) -> dict:
    """Таблица смен и график ВР рудника (core.shifts), старый формат count/start/hours поддерживается."""
    from core import shifts

    return shifts.from_config(mine_cfg.get("shifts") or {})


def current_shift(mine_cfg: dict, now: datetime | None = None) -> dict:
    """Номер смены, дата смены (дата ее начала) и границы (UTC) по времени рудника."""
    from core import shifts

    tz = mine_cfg.get("timezone", "UTC")
    now = now or utcnow()
    sh = shifts.current(shift_config(mine_cfg), now, tz)
    return {**sh, "start_local": to_tz(sh["start"], tz).isoformat(), "end_local": to_tz(sh["end"], tz).isoformat(),
            "tz": tz}


def shift_bounds(mine_cfg: dict, shift_date: str, shift_no: int) -> tuple[datetime, datetime]:
    from core import shifts

    return shifts.bounds(shift_config(mine_cfg), shift_date, shift_no, mine_cfg.get("timezone", "UTC"))
