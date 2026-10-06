"""Пароли (bcrypt), JWT, шифрование ключей ИИ (Fernet)."""
from __future__ import annotations

import base64
import hashlib
from datetime import timedelta

import bcrypt
import jwt
from cryptography.fernet import Fernet

from .settings import get_settings
from .timeutil import utcnow


def hash_password(pw: str) -> str:
    return bcrypt.hashpw(pw.encode(), bcrypt.gensalt(rounds=10)).decode()


def verify_password(pw: str, h: str) -> bool:
    try:
        return bcrypt.checkpw(pw.encode(), h.encode())
    except ValueError:
        return False


def make_token(user_id: int, username: str, role: str) -> str:
    s = get_settings()
    payload = {"sub": str(user_id), "usr": username, "role": role, "exp": utcnow() + timedelta(hours=s.jwt_hours)}
    return jwt.encode(payload, s.jwt_secret, algorithm="HS256")


def decode_token(token: str) -> dict:
    return jwt.decode(token, get_settings().jwt_secret, algorithms=["HS256"])


def _fernet() -> Fernet:
    key = get_settings().fernet_key
    if not key:
        key = base64.urlsafe_b64encode(hashlib.sha256(get_settings().jwt_secret.encode()).digest()).decode()
    return Fernet(key.encode())


def encrypt(text: str) -> str:
    return _fernet().encrypt(text.encode()).decode() if text else ""


def decrypt(token: str) -> str:
    return _fernet().decrypt(token.encode()).decode() if token else ""
