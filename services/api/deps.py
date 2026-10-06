"""Зависимости API: текущий пользователь (JWT или внутренний токен сервисов), проверка прав, аудит."""
from __future__ import annotations

from dataclasses import dataclass, field

from fastapi import Depends, Header, HTTPException, Request
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from common.db import get_db
from common.models import AuditLog, Role, User
from common.permissions import PERMISSIONS
from common.security import decode_token
from common.settings import get_settings

oauth2 = OAuth2PasswordBearer(tokenUrl="/api/auth/token", auto_error=False)


@dataclass
class CurrentUser:
    id: int | None
    username: str
    role: str
    permissions: set[str] = field(default_factory=set)
    lang: str = "ru"
    tz: str = "UTC"
    full_name: str = ""
    service: bool = False

    def can(self, perm: str) -> bool:
        return perm in self.permissions


def get_current_user(request: Request, token: str | None = Depends(oauth2), db: Session = Depends(get_db),
                     x_internal_token: str | None = Header(default=None)) -> CurrentUser:
    if x_internal_token and x_internal_token == get_settings().internal_token:
        name = request.headers.get("x-acting-user", "emulator")
        return CurrentUser(None, name, "service", set(PERMISSIONS), service=True)
    if not token:
        raise HTTPException(401, "errors.not_authenticated")
    try:
        data = decode_token(token)
    except Exception:
        raise HTTPException(401, "errors.token_invalid")
    user = db.get(User, int(data["sub"]))
    if not user or not user.active:
        raise HTTPException(401, "errors.user_inactive")
    role = db.get(Role, user.role_id)
    return CurrentUser(user.id, user.username, role.name if role else "", set(role.permissions if role else []),
                       user.lang, user.tz, user.full_name)


def require(*perms: str):
    """Требуется хотя бы одно из прав."""

    def dep(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
        if not any(user.can(p) for p in perms):
            raise HTTPException(403, "errors.forbidden")
        return user

    return dep


def audit(db: Session, user: CurrentUser, action: str, entity: str = "", entity_id="", details: dict | None = None,
          commit: bool = False) -> None:
    db.add(AuditLog(user_id=user.id, username=user.username, action=action, entity=entity, entity_id=str(entity_id),
                    details=details or {}))
    if commit:
        db.commit()
