"""Вход (JWT), профиль, смена пароля."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from common.db import get_db
from common.models import Role, User
from common.security import hash_password, make_token, verify_password

from ..deps import CurrentUser, audit, get_current_user

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/token")
def login(form: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    u = db.scalar(select(User).where(User.username == form.username))
    if not u or not u.active or not verify_password(form.password, u.password_hash):
        raise HTTPException(401, "errors.bad_credentials")
    role = db.get(Role, u.role_id)
    db.add_all([])
    audit(db, CurrentUser(u.id, u.username, role.name), "login", "user", u.id, commit=True)
    return {"access_token": make_token(u.id, u.username, role.name), "token_type": "bearer"}


@router.get("/me")
def me(user: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)):
    u = db.get(User, user.id) if user.id else None
    role = db.scalar(select(Role).where(Role.name == user.role))
    return {"id": user.id, "username": user.username, "full_name": user.full_name, "role": user.role,
            "role_title": role.title if role else {}, "permissions": sorted(user.permissions), "lang": user.lang,
            "tz": user.tz, "must_change_password": bool(u and u.must_change_password)}


class ProfileIn(BaseModel):
    lang: str | None = None
    tz: str | None = None
    full_name: str | None = None


@router.patch("/profile")
def profile(body: ProfileIn, user: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)):
    u = db.get(User, user.id)
    if not u:
        raise HTTPException(400, "errors.service_user")
    if body.tz:
        from zoneinfo import ZoneInfo

        try:
            ZoneInfo(body.tz)
        except Exception:
            raise HTTPException(400, "errors.bad_timezone")
        u.tz = body.tz
    if body.lang:
        u.lang = body.lang
    if body.full_name is not None:
        u.full_name = body.full_name
    audit(db, user, "profile", "user", u.id, body.model_dump(exclude_none=True))
    db.commit()
    return {"ok": True}


class PasswordIn(BaseModel):
    old_password: str
    new_password: str


@router.post("/password")
def change_password(body: PasswordIn, user: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)):
    u = db.get(User, user.id)
    if not u or not verify_password(body.old_password, u.password_hash):
        raise HTTPException(400, "errors.bad_old_password")
    if len(body.new_password) < 6:
        raise HTTPException(400, "errors.password_too_short")
    u.password_hash = hash_password(body.new_password)
    u.must_change_password = False
    audit(db, user, "password_change", "user", u.id)
    db.commit()
    return {"ok": True}
