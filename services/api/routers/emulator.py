"""Пульт эмулятора (только admin): прокси к сервису emulator."""
from __future__ import annotations

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from common.db import get_db
from common.settings import get_settings

from ..deps import CurrentUser, audit, require

router = APIRouter(prefix="/api/emulator", tags=["emulator"])
ADMIN = require("console.use")


async def _call(method: str, path: str, body: dict | None = None):
    s = get_settings()
    try:
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.request(method, s.emulator_url + "/emulator" + path, json=body,
                                headers={"x-internal-token": s.internal_token})
            return r.json()
    except httpx.HTTPError:
        raise HTTPException(503, "errors.emulator_unavailable")


@router.get("/state")
async def state(_: CurrentUser = Depends(ADMIN)):
    return await _call("GET", "/state")


def demo_reset(db: Session, user: CurrentUser | None = None) -> dict:
    """«Сброс демо-рудника»: эмулятор останавливается, рудник и вся работа по нему — в исходное состояние,
    горные события ClickHouse очищаются; эмулятор запускается снова с прежними скоростью и сценариями."""
    from common import ch

    from ..loader import reset_demo

    s = get_settings()
    h = {"x-internal-token": s.internal_token}
    emu = None
    with httpx.Client(base_url=s.emulator_url + "/emulator", headers=h, timeout=60) as c:
        try:
            emu = c.get("/state").json()
            c.post("/pause", json={})
        except httpx.HTTPError:
            emu = None  # эмулятор недоступен — рудник все равно сбрасывается
    res = reset_demo(db, s.mines_dir)
    try:
        for t in ("events", "telemetry", "drilling", "cycles", "stopes", "dispatch", "face_status"):
            ch.client().command(f"TRUNCATE TABLE IF EXISTS {t}")
        res["clickhouse"] = "cleared"
    except Exception as e:  # ClickHouse недоступен — не мешает сбросу рудника
        res["clickhouse"] = f"skipped: {e}"
    if emu is not None:
        with httpx.Client(base_url=s.emulator_url + "/emulator", headers=h, timeout=60) as c:
            c.post("/reset", json={})
            c.post("/scenarios", json=emu.get("scenarios") or {})
            c.post("/auto", json={"auto_dispatch": emu.get("auto_dispatch", True)})
            if emu.get("running"):
                c.post("/start", json={"speed": emu.get("speed", 60)})
        res["emulator"] = {"restarted": bool(emu.get("running")), "speed": emu.get("speed")}
    if user:
        audit(db, user, "demo_reset", "mine", res["mine"], res, commit=True)
    return res


@router.post("/demo-reset")
def demo_reset_route(db: Session = Depends(get_db), user: CurrentUser = Depends(ADMIN)):
    return demo_reset(db, user)


@router.post("/{action}")
async def action(action: str, request: Request, db: Session = Depends(get_db), user: CurrentUser = Depends(ADMIN)):
    if action not in ("start", "pause", "reset", "speed", "scenarios", "load", "backfill", "auto"):
        raise HTTPException(404, "errors.not_found")
    body = await request.json() if (await request.body()) else {}
    audit(db, user, f"emulator_{action}", "emulator", "", body, commit=True)
    return await _call("POST", f"/{action}", body)
