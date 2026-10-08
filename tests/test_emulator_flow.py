"""Эмулятор против API (SQLite): за 10 минут на ×60 проходит полный цикл проходки вне окна ВР по реальным часам —
наряд с буровыми, анализ, проходка в метрах, КИШ и лишняя порода в отчете «за сутки»."""
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

SPEED = 60
TICK_S = 2.0  # реальный шаг цикла эмулятора


@pytest.fixture(scope="module")
def client():
    """Своя база в памяти: эмулятор двигает забои и наряд, остальные модули тестов этого не ждут —
    после модуля следующие тоже начинают с новой базы (bootstrap создает демо-рудник заново)."""
    from api.main import app
    from common import db

    def fresh():
        db.get_engine().dispose()
        db.get_engine.cache_clear()
        db._factory.cache_clear()

    fresh()
    try:
        with TestClient(app) as c:
            yield c
    finally:
        fresh()


class SyncApi:
    """Тот же интерфейс, что emulator.main.Api, поверх TestClient (служебный токен, x-acting-user)."""

    def __init__(self, c):
        from common.settings import get_settings

        self.c = c
        self.h = {"x-internal-token": get_settings().internal_token, "x-acting-user": "emulator"}

    async def get(self, path, **params):
        r = self.c.get(path, params=params, headers=self.h)
        r.raise_for_status()
        return r.json()

    async def post(self, path, body=None, ok=(200,), as_user="emulator"):
        r = self.c.post(path, json=body or {}, headers={**self.h, "x-acting-user": as_user})
        if r.status_code not in ok:
            return {"_error": r.status_code, **(r.json() if r.headers.get("content-type", "").startswith("application/json") else {})}
        return r.json()

    async def put(self, path, body):
        return self.c.put(path, json=body, headers=self.h).json()


def _emulator(client):
    from emulator.main import Emulator

    emu = Emulator()
    emu.api = SyncApi(client)
    emu.speed = SPEED
    emu.running = True
    return emu


def _outside_blast_window(client, h):
    """Одна смена на сутки, окно ВР закончилось час назад: сейчас по часам рудника взрывать нельзя."""
    from datetime import datetime
    from zoneinfo import ZoneInfo

    tz = client.get("/api/mine", headers=h).json()["config"]["timezone"]
    now = datetime.now(ZoneInfo(tz))
    hm = lambda d: d.strftime("%H:%M")  # noqa: E731
    r = client.put("/api/mine/config", json={"shifts": {
        "table": [{"no": 1, "start": "00:00", "end": "00:00"}], "reentry_min": 0,
        "blast_windows": [{"shift": 1, "start": hm(now - timedelta(hours=2)), "end": hm(now - timedelta(hours=1))}]}},
        headers=h)
    assert r.status_code == 200, r.text


def test_emulator_ten_minutes_x60_gives_reports(client):
    import asyncio

    emu = _emulator(client)
    api = emu.api
    E = {**api.h, "x-acting-user": "emulator-engineer"}
    _outside_blast_window(client, E)
    asyncio.run(emu.save_runtime())  # эмулятор запущен с ускорением — так его видят api и alerts
    assert not client.get("/api/mine/shifts", headers=E).json()["blast_now"]

    async def run():
        for _ in range(int(10 * 60 / TICK_S)):
            await emu.tick(TICK_S * SPEED / 3600, telemetry=False)

    asyncio.run(run())
    assert emu.stats["errors"] == 0
    # наряд на текущую смену с буровыми
    order = client.get("/api/dispatch/order", headers=E).json()["order"]
    assert order and any(a["active"] and a["work_type"] == "drilling" for a in order["assignments"]), order
    # циклы дошли до анализа, вне реального окна ВР — взрывы по сжатому окну эмулятора
    assert emu.stats["cycles"] >= 1, emu.state()["log"][:20]
    faces = client.get("/api/workflow/faces", headers=E).json()
    assert any(f["kind"] == "dev" and f["cycle_no"] >= 2 for f in faces)
    rep = client.get("/api/reports/period", params={"period": "day"}, headers=E).json()
    dev = rep["development"]
    assert dev["cycles"] >= 1 and dev["advance_m"] > 0 and dev["kish"] and dev["extra_t"] > 0, dev
    assert rep["cycles"] and rep["blasting"]["outside_window"] == 0


def test_emulator_blast_outside_window_only_when_accelerated(client):
    """Сжатое окно ВР — только для служебного эмулятора и только пока он ускорен; людям — по-прежнему окно."""
    import asyncio

    from common.db import session_scope
    from common.models import Face
    from common.timeutil import utcnow

    emu = _emulator(client)
    api = emu.api
    _outside_blast_window(client, {**api.h, "x-acting-user": "emulator-engineer"})
    with session_scope() as db:
        f = next(x for x in db.query(Face).all() if x.kind == "dev" and x.status not in ("done",))
        fid, f.status, f.status_since = f.id, "charged", utcnow()
    body = {"to": "blasted", "emulated_window": True}
    emu.speed = 1
    asyncio.run(emu.save_runtime())
    r = client.post(f"/api/workflow/faces/{fid}/transition", json=body, headers={**api.h, "x-acting-user": "emulator-blaster"})
    assert r.status_code == 400 and r.json()["detail"]["code"] == "errors.blast_outside_window"
    emu.speed = SPEED
    asyncio.run(emu.save_runtime())
    r = client.post(f"/api/workflow/faces/{fid}/transition", json=body, headers={**api.h, "x-acting-user": "someone"})
    assert r.status_code == 400
    r = client.post(f"/api/workflow/faces/{fid}/transition", json=body, headers={**api.h, "x-acting-user": "emulator-blaster"})
    assert r.status_code == 200, r.text


def test_emulator_fills_order_after_shift_change(client):
    """Новая смена: копия наряда отбросила строки (забои не готовы к бурению, шли ВР) — эмулятор
    расставляет свободные буровые на следующих шагах, а не один раз за смену."""
    import asyncio

    from common.db import session_scope
    from common.models import Assignment, ShiftOrder

    emu = _emulator(client)
    api = emu.api
    D = {**api.h, "x-acting-user": "emulator-dispatcher"}
    _outside_blast_window(client, D)
    cur = client.get("/api/dispatch/order", headers=D).json()
    with session_scope() as db:  # пустой наряд текущей смены, как после отброшенной копии
        o = db.query(ShiftOrder).filter_by(date=cur["date"], shift_no=cur["shift_no"]).first()
        if o:
            db.query(Assignment).filter_by(order_id=o.id).delete()
        else:
            db.add(ShiftOrder(mine_id=1, date=cur["date"], shift_no=cur["shift_no"], status="draft", created_by="t"))
    emu.order_key = (cur["date"], cur["shift_no"])  # смену эмулятор уже «видел»
    asyncio.run(emu.ensure_order())
    order = client.get("/api/dispatch/order", headers=D).json()["order"]
    assert any(a["active"] and a["work_type"] in ("drilling", "ring_drilling") for a in order["assignments"]), order


def test_ready_faces_puts_incompatible_last(client):
    from common.db import session_scope
    from common.models import Machine

    api = SyncApi(client)
    with session_scope() as db:
        simba = next(m.id for m in db.query(Machine).all() if m.type == "ring_drill" and m.status in ("working", "idle"))
    rf = client.get("/api/dispatch/ready-faces", params={"machine_id": simba}, headers=api.h).json()["faces"]
    assert all("ok" in x and "issues" in x for x in rf)
    oks = [x["ok"] for x in rf]
    assert oks == sorted(oks, reverse=True)  # совместимые с машиной — первыми
    assert all(x["issues"] for x in rf if not x["ok"])


def test_done_face_replaced_once(client):
    """Законченная камера вводит в работу одну следующую — не новую на каждом шаге и не после рестарта эмулятора."""
    import asyncio

    from common.db import session_scope
    from common.models import Face

    emu = _emulator(client)
    calls = []

    async def replace(f):
        calls.append(f["id"])

    emu.replace_done = replace
    with session_scope() as db:
        f = next(x for x in db.query(Face).all() if x.kind == "stope" and x.status == "ready")
        fid, f.status = f.id, "analyzed"
    face = lambda st, cyc: {"id": fid, "status": st, "cycle_no": cyc, "kind": "stope"}  # noqa: E731
    board = {"rows": []}

    async def run():
        await emu.step_faces([face("analyzed", 1)], board, 0.0)
        for _ in range(5):
            await emu.step_faces([face("done", 2)], board, 0.0)

    asyncio.run(run())
    assert calls == [fid]
    fresh = _emulator(client)  # после рестарта законченный забой уже «done» — не заменяется повторно
    fresh.replace_done = replace
    asyncio.run(fresh.step_faces([face("done", 2)], board, 0.0))
    assert calls == [fid]
