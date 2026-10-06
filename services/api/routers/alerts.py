"""Алерты: колокольчик и страница по ролям (диспетчер / инженер / администратор), подтверждение, действия."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from common import i18n
from common.db import get_db
from common.models import Alert
from common.timeutil import to_tz, utcnow

from ..deps import CurrentUser, audit, get_current_user
from ..svc import active_mine

router = APIRouter(prefix="/api/alerts", tags=["alerts"])
AUDIENCE_PERM = {"dispatcher": "alerts.dispatch.view", "engineer": "alerts.engineer.view", "admin": "alerts.admin.view"}


def audiences(user: CurrentUser) -> list[str]:
    return [a for a, p in AUDIENCE_PERM.items() if user.can(p)]


def render(a: Alert, lang: str, tz: str, user_tz: str) -> dict:
    d = a.as_dict()
    d["title"] = i18n.t(f"alerts.rules.{a.rule}.title", lang, **(a.params or {}))
    d["text"] = i18n.t(f"alerts.rules.{a.rule}.text", lang, **(a.params or {}))
    d["ts_mine"] = to_tz(a.ts, tz).strftime("%d.%m %H:%M")
    d["ts_user"] = to_tz(a.ts, user_tz).strftime("%d.%m %H:%M")
    return d


@router.get("")
def list_alerts(status: str | None = None, limit: int = 200, db: Session = Depends(get_db),
                user: CurrentUser = Depends(get_current_user)):
    aud = audiences(user)
    if not aud:
        return []
    tz = active_mine(db).config.get("timezone", "UTC")
    q = select(Alert).where(Alert.audience.in_(aud)).order_by(Alert.id.desc()).limit(min(limit, 1000))
    if status:
        q = q.where(Alert.status == status)
    return [render(a, user.lang, tz, user.tz) for a in db.scalars(q)]


@router.get("/count")
def count(db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_user)):
    aud = audiences(user)
    if not aud:
        return {"open": 0}
    n = db.scalar(select(func.count()).select_from(Alert).where(Alert.audience.in_(aud), Alert.status == "open"))
    return {"open": n or 0}


@router.post("/{aid}/status")
def set_status(aid: int, body: dict, db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_user)):
    a = db.get(Alert, aid)
    if not a or a.audience not in audiences(user):
        raise HTTPException(404, "errors.not_found")
    if a.audience == "dispatcher" and not user.can("alerts.dispatch.act"):
        raise HTTPException(403, "errors.forbidden")
    a.status = body["status"]
    if body["status"] == "resolved":
        a.resolved_by, a.resolved_at = user.username, utcnow()
    if body.get("reason"):
        a.params = {**(a.params or {}), "reason": body["reason"]}
    audit(db, user, "alert_status", "alert", aid, body)
    db.commit()
    return {"ok": True}
