"""Пользователи, роли, журнал аудита (только администратор)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from common.db import get_db
from common.models import AuditLog, Role, User
from common.permissions import PERMISSIONS
from common.security import hash_password

from ..deps import CurrentUser, audit, require

router = APIRouter(prefix="/api/admin", tags=["admin"])
ADMIN = require("users.manage")


@router.get("/permissions")
def permissions(_: CurrentUser = Depends(ADMIN)):
    return PERMISSIONS


@router.get("/roles")
def roles(db: Session = Depends(get_db), _: CurrentUser = Depends(require("users.manage", "dispatch.view"))):
    return [r.as_dict() for r in db.scalars(select(Role).order_by(Role.id))]


class RoleIn(BaseModel):
    name: str
    title: dict = {}
    permissions: list[str] = []
    grafana_role: str = "Viewer"


@router.post("/roles")
def create_role(body: RoleIn, db: Session = Depends(get_db), user: CurrentUser = Depends(ADMIN)):
    if db.scalar(select(Role).where(Role.name == body.name)):
        raise HTTPException(400, "errors.exists")
    bad = set(body.permissions) - set(PERMISSIONS)
    if bad:
        raise HTTPException(400, "errors.unknown_permission")
    r = Role(name=body.name, title=body.title or {"ru": body.name}, permissions=body.permissions,
             grafana_role=body.grafana_role)
    db.add(r)
    audit(db, user, "role_create", "role", body.name, body.model_dump())
    db.commit()
    return r.as_dict()


@router.put("/roles/{rid}")
def update_role(rid: int, body: RoleIn, db: Session = Depends(get_db), user: CurrentUser = Depends(ADMIN)):
    r = db.get(Role, rid)
    if not r:
        raise HTTPException(404, "errors.not_found")
    if r.name == "admin" and "users.manage" not in body.permissions:
        raise HTTPException(400, "errors.admin_lockout")
    r.title, r.permissions, r.grafana_role = body.title or r.title, body.permissions, body.grafana_role
    if not r.builtin:
        r.name = body.name
    audit(db, user, "role_update", "role", rid, body.model_dump())
    db.commit()
    return r.as_dict()


@router.delete("/roles/{rid}")
def delete_role(rid: int, db: Session = Depends(get_db), user: CurrentUser = Depends(ADMIN)):
    r = db.get(Role, rid)
    if not r or r.builtin:
        raise HTTPException(400, "errors.builtin_role")
    if db.scalar(select(func.count()).select_from(User).where(User.role_id == rid)):
        raise HTTPException(400, "errors.role_in_use")
    db.delete(r)
    audit(db, user, "role_delete", "role", rid)
    db.commit()
    return {"ok": True}


@router.get("/users")
def users(db: Session = Depends(get_db), _: CurrentUser = Depends(ADMIN)):
    out = []
    for u in db.scalars(select(User).order_by(User.id)):
        d = u.as_dict()
        d.pop("password_hash")
        out.append(d)
    return out


class UserIn(BaseModel):
    username: str
    password: str | None = None
    full_name: str = ""
    role_id: int
    lang: str = "ru"
    tz: str = "Asia/Bangkok"
    active: bool = True


@router.post("/users")
def create_user(body: UserIn, db: Session = Depends(get_db), user: CurrentUser = Depends(ADMIN)):
    if db.scalar(select(User).where(User.username == body.username)):
        raise HTTPException(400, "errors.exists")
    if not body.password or len(body.password) < 2:
        raise HTTPException(400, "errors.password_too_short")
    u = User(username=body.username, password_hash=hash_password(body.password), full_name=body.full_name,
             role_id=body.role_id, lang=body.lang, tz=body.tz, active=body.active, must_change_password=True)
    db.add(u)
    audit(db, user, "user_create", "user", body.username, {"role_id": body.role_id})
    db.commit()
    return {"id": u.id}


@router.put("/users/{uid}")
def update_user(uid: int, body: UserIn, db: Session = Depends(get_db), user: CurrentUser = Depends(ADMIN)):
    u = db.get(User, uid)
    if not u:
        raise HTTPException(404, "errors.not_found")
    u.full_name, u.role_id, u.lang, u.tz, u.active = body.full_name, body.role_id, body.lang, body.tz, body.active
    if body.password:
        u.password_hash = hash_password(body.password)
        u.must_change_password = True
    audit(db, user, "user_update", "user", uid, {"role_id": body.role_id, "active": body.active,
                                                  "password_reset": bool(body.password)})
    db.commit()
    return {"ok": True}


@router.get("/audit")
def audit_log(limit: int = 200, username: str | None = None, db: Session = Depends(get_db),
              _: CurrentUser = Depends(ADMIN)):
    q = select(AuditLog).order_by(AuditLog.id.desc()).limit(min(limit, 2000))
    if username:
        q = q.where(AuditLog.username == username)
    return [a.as_dict() for a in db.scalars(q)]
