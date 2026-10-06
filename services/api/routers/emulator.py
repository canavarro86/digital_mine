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


@router.post("/{action}")
async def action(action: str, request: Request, db: Session = Depends(get_db), user: CurrentUser = Depends(ADMIN)):
    if action not in ("start", "pause", "reset", "speed", "scenarios", "load", "backfill", "auto"):
        raise HTTPException(404, "errors.not_found")
    body = await request.json() if (await request.body()) else {}
    audit(db, user, f"emulator_{action}", "emulator", "", body, commit=True)
    return await _call("POST", f"/{action}", body)
