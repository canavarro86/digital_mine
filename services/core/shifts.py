"""Смены и график взрывных работ.

Таблица смен: [{"no": 1, "start": "07:00", "end": "15:00"}, ...] по времени рудника; смена может переходить через
полночь и относится к дате своего начала. Окна ВР: [{"shift": 1, "start": "14:00", "end": "15:00", "note": "..."}].
Все проверки возвращают коды и параметры ошибок — тексты в locales (errors.shift_*, errors.blast_window_*).
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

DAY = 1440


def to_min(hhmm: str) -> int:
    h, m = (int(x) for x in str(hhmm).split(":"))
    if not (0 <= h <= 24 and 0 <= m < 60) or h * 60 + m > DAY:
        raise ValueError(hhmm)
    return (h * 60 + m) % DAY


def fmt(m: int) -> str:
    m %= DAY
    return f"{m // 60:02d}:{m % 60:02d}"


def duration(start: str, end: str) -> int:
    """Длительность интервала в минутах; конец не позже начала — переход через полночь (00:00–00:00 — сутки)."""
    d = (to_min(end) - to_min(start)) % DAY
    return d or DAY


def default_table(count: int, first_start: str = "00:00") -> list[dict]:
    """Сутки поровну от начала первой смены: 3 смены — по 8 ч, 2 — по 12 ч, 4 — по 6 ч."""
    count = max(1, min(4, int(count)))
    s0, step = to_min(first_start), DAY // count
    return [{"no": i + 1, "start": fmt(s0 + i * step), "end": fmt(s0 + (i + 1) * step)} for i in range(count)]


def default_windows(table: list[dict]) -> list[dict]:
    """По умолчанию одно окно ВР на смену — последний час смены."""
    return [{"shift": r["no"], "start": fmt(to_min(r["end"]) - 60), "end": r["end"], "note": "blast_vent"} for r in table]


def from_config(cfg: dict) -> dict:
    """Настройки смен рудника (mine.yaml → shifts) с совместимостью со старым форматом count/start/hours."""
    s = dict(cfg or {})
    table = s.get("table")
    if not table:
        count, start, hours = int(s.get("count", 2)), s.get("start", "08:00"), float(s.get("hours", 12))
        s0 = to_min(start)
        table = [{"no": i + 1, "start": fmt(s0 + int(i * hours * 60)), "end": fmt(s0 + int((i + 1) * hours * 60))}
                 for i in range(count)]
    windows = s.get("blast_windows")
    if windows is None:
        windows = default_windows(table)
    return {"count": len(table), "table": table, "blast_windows": windows,
            "ventilation_min": int(s.get("ventilation_min", 30)), "reentry_min": int(s.get("reentry_min", 30)),
            "blast_zone": s.get("blast_zone", "mine")}


# ---------------- проверки ----------------
def validate_table(table: list[dict]) -> list[dict]:
    """Покрытие 24 ч: разрывы и пересечения между соседними сменами, сумма длительностей.
    field — что подсветить: {"row": индекс, "key": "start"|"end"}."""
    errs: list[dict] = []
    if not 1 <= len(table) <= 4:
        return [{"code": "shift_count", "params": {"n": len(table)}}]
    rows = []
    for i, r in enumerate(table):
        try:
            rows.append((r["no"], to_min(r["start"]), duration(r["start"], r["end"]), r))
        except (KeyError, ValueError):
            errs.append({"code": "shift_time", "params": {"n": r.get("no", i + 1)}, "field": {"row": i, "key": "start"}})
    if errs:
        return errs
    total = sum(d for _, _, d, _ in rows)
    n = len(rows)
    for i in range(n):
        no, s, d, r = rows[i]
        no2, s2, _, r2 = rows[(i + 1) % n]
        if n == 1:
            break
        delta = (s2 - s) % DAY
        if delta < d:  # следующая смена начинается раньше, чем кончилась эта
            ov = d - delta
            errs.append({"code": "shift_overlap", "params": {"a": no, "b": no2, "minutes": ov, "from": r2["start"],
                                                             "to": fmt(s2 + ov)},
                         "field": {"row": (i + 1) % n, "key": "start"}})
        elif delta > d:
            errs.append({"code": "shift_gap", "params": {"a": no, "b": no2, "end": r["end"], "start": r2["start"],
                                                         "minutes": delta - d},
                         "field": {"row": (i + 1) % n, "key": "start"}})
    if total != DAY:
        errs.append({"code": "shift_total", "params": {"minutes": total, "missing": DAY - total}})
    return errs


def validate_windows(table: list[dict], windows: list[dict]) -> list[dict]:
    """Окно ВР лежит внутри своей смены (с учетом перехода через полночь); окна смены не пересекаются."""
    by_no = {r["no"]: r for r in table}
    errs = []
    seen: dict[int, list[tuple[int, int]]] = {}
    for i, w in enumerate(windows):
        r = by_no.get(w.get("shift"))
        if not r:
            errs.append({"code": "blast_window_shift", "params": {"n": w.get("shift")}, "field": {"row": i, "key": "shift"}})
            continue
        try:
            s0, d = to_min(r["start"]), duration(r["start"], r["end"])
            ws, wd = (to_min(w["start"]) - s0) % DAY, duration(w["start"], w["end"])
        except (KeyError, ValueError):
            errs.append({"code": "shift_time", "params": {"n": w.get("shift")}, "field": {"row": i, "key": "start"}})
            continue
        if ws + wd > d or wd >= DAY:
            errs.append({"code": "blast_window_outside", "params": {"n": r["no"], "start": w["start"], "end": w["end"],
                                                                    "shift_start": r["start"], "shift_end": r["end"]},
                         "field": {"row": i, "key": "start"}})
            continue
        for a, b in seen.get(r["no"], []):
            if ws < b and a < ws + wd:
                errs.append({"code": "blast_window_overlap", "params": {"n": r["no"], "start": w["start"]},
                             "field": {"row": i, "key": "start"}})
        seen.setdefault(r["no"], []).append((ws, ws + wd))
    return errs


def validate(cfg: dict) -> list[dict]:
    errs = [{**e, "section": "table"} for e in validate_table(cfg["table"])]
    if not errs:
        errs += [{**e, "section": "windows"} for e in validate_windows(cfg["table"], cfg["blast_windows"])]
    for k in ("ventilation_min", "reentry_min"):
        if int(cfg.get(k, 0)) < 0:
            errs.append({"code": "shift_negative", "params": {"field": k}, "section": "params"})
    if cfg.get("blast_zone", "mine") not in ("mine", "level", "faces"):
        errs.append({"code": "blast_zone", "params": {}, "section": "params"})
    return errs


# ---------------- время ----------------
def _at(d: date, hhmm: str, tz: ZoneInfo) -> datetime:
    m = to_min(hhmm)
    return datetime(d.year, d.month, d.day, tzinfo=tz) + timedelta(minutes=m)


def bounds(cfg: dict, shift_date: str, no: int, tz_name: str) -> tuple[datetime, datetime]:
    """Начало и конец смены (UTC): смена относится к дате своего начала."""
    tz = ZoneInfo(tz_name)
    r = next((x for x in cfg["table"] if x["no"] == no), cfg["table"][-1])
    start = _at(date.fromisoformat(shift_date), r["start"], tz)
    end = start + timedelta(minutes=duration(r["start"], r["end"]))
    return start.astimezone(timezone.utc), end.astimezone(timezone.utc)


def current(cfg: dict, now: datetime, tz_name: str) -> dict:
    """Смена, в которую попадает момент now: номер, дата начала, границы."""
    local = now.astimezone(ZoneInfo(tz_name))
    best = None
    for back in (0, 1):
        d = (local - timedelta(days=back)).date()
        for r in cfg["table"]:
            s, e = bounds(cfg, d.isoformat(), r["no"], tz_name)
            if s <= now < e and (best is None or s > best[1]):
                best = (d.isoformat(), s, e, r["no"])
    if best is None:  # таблица с разрывом (не сохраняется, но на всякий случай) — ближайшая начавшаяся смена
        cands = [(bounds(cfg, (local - timedelta(days=b)).date().isoformat(), r["no"], tz_name), r["no"], b)
                 for b in (0, 1) for r in cfg["table"]]
        (s, e), no, b = max((c for c in cands if c[0][0] <= now), key=lambda c: c[0][0])
        best = ((local - timedelta(days=b)).date().isoformat(), s, e, no)
    d, s, e, no = best
    return {"date": d, "shift_no": no, "start": s, "end": e}


def previous(cfg: dict, shift_date: str, no: int, tz_name: str) -> tuple[str, int]:
    """Смена, которая кончается в момент начала этой."""
    s, _ = bounds(cfg, shift_date, no, tz_name)
    prev = current(cfg, s - timedelta(minutes=1), tz_name)
    return prev["date"], prev["shift_no"]


def windows(cfg: dict, shift_date: str, no: int, tz_name: str) -> list[dict]:
    """Окна ВР смены (UTC) в порядке времени."""
    tz = ZoneInfo(tz_name)
    s, _ = bounds(cfg, shift_date, no, tz_name)
    s_local = s.astimezone(tz)
    r = next((x for x in cfg["table"] if x["no"] == no), None)
    out = []
    for w in cfg["blast_windows"]:
        if w.get("shift") != no or not r:
            continue
        off = (to_min(w["start"]) - to_min(r["start"])) % DAY
        ws = s_local + timedelta(minutes=off)
        out.append({"start": ws.astimezone(timezone.utc),
                    "end": (ws + timedelta(minutes=duration(w["start"], w["end"]))).astimezone(timezone.utc),
                    "note": w.get("note", "")})
    return sorted(out, key=lambda x: x["start"])


def window_at(cfg: dict, now: datetime, tz_name: str) -> dict | None:
    """Окно ВР, которое идет сейчас (в текущей или предыдущей смене)."""
    sh = current(cfg, now, tz_name)
    for d, n in ((sh["date"], sh["shift_no"]), previous(cfg, sh["date"], sh["shift_no"], tz_name)):
        for w in windows(cfg, d, n, tz_name):
            if w["start"] <= now < w["end"]:
                return {**w, "date": d, "shift_no": n}
    return None


def next_window(cfg: dict, after: datetime, tz_name: str, days: int = 3) -> dict | None:
    """Ближайшее окно ВР, которое начинается не раньше момента after."""
    sh = current(cfg, after, tz_name)
    d0 = date.fromisoformat(sh["date"])
    found = []
    for k in range(-1, days + 1):
        d = (d0 + timedelta(days=k)).isoformat()
        for r in cfg["table"]:
            for w in windows(cfg, d, r["no"], tz_name):
                if w["start"] >= after:
                    found.append({**w, "date": d, "shift_no": r["no"]})
    return min(found, key=lambda w: w["start"]) if found else None


def windows_between(cfg: dict, t0: datetime, t1: datetime, tz_name: str) -> list[dict]:
    """Окна ВР, закончившиеся в интервале (t0, t1]."""
    sh = current(cfg, t0, tz_name)
    d0 = date.fromisoformat(sh["date"])
    out = []
    span = max(1, (t1 - t0).days + 2)
    for k in range(-1, span + 1):
        d = (d0 + timedelta(days=k)).isoformat()
        for r in cfg["table"]:
            for w in windows(cfg, d, r["no"], tz_name):
                if t0 < w["end"] <= t1:
                    out.append({**w, "date": d, "shift_no": r["no"]})
    return sorted(out, key=lambda w: w["end"])
