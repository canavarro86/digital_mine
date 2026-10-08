"""Инициализация: миграции, роли и пользователи, справочники, демо-рудник, ClickHouse, пользователи Grafana.

Запуск: python -m api.bootstrap [--start-emulator]. Вызывается и при старте api (идемпотентно).
"""
from __future__ import annotations

import argparse
import logging
import threading
import time
from pathlib import Path

import httpx
from sqlalchemy import select, text

from common.db import get_engine, session_scope
from common.models import Role, User
from common.permissions import BUILTIN_ROLES, DEMO_USERS
from common.security import hash_password
from common.settings import get_settings, load_yaml
from common.web import setup_logging

log = logging.getLogger("bootstrap")


def migrate() -> None:
    from alembic import command
    from alembic.config import Config

    here = Path(__file__).parent
    cfg = Config()
    cfg.set_main_option("script_location", str(here / "migrations"))
    eng = get_engine()
    if eng.dialect.name == "postgresql":
        with eng.connect() as c:
            c.execute(text("SELECT pg_advisory_lock(424242)"))
            try:
                cfg.attributes["connection"] = c
                command.upgrade(cfg, "head")
                c.commit()
            finally:
                c.execute(text("SELECT pg_advisory_unlock(424242)"))
                c.commit()
    else:
        from common.models import Base

        Base.metadata.create_all(eng)


def seed_users() -> None:
    with session_scope() as db:
        roles = {}
        for name, r in BUILTIN_ROLES.items():
            role = db.scalar(select(Role).where(Role.name == name))
            if not role:
                role = Role(name=name, title=r["title"], permissions=r["permissions"], builtin=True,
                            grafana_role=r["grafana_role"])
                db.add(role)
            else:  # встроенные роли получают новые права при обновлении системы
                role.permissions = sorted(set(role.permissions) | set(r["permissions"]))
            db.flush()
            roles[name] = role
        tz = load_yaml("settings.yaml").get("default_user_timezone", "Asia/Bangkok")
        for u in DEMO_USERS:
            if not db.scalar(select(User).where(User.username == u["username"])):
                db.add(User(username=u["username"], password_hash=hash_password(u["password"]),
                            role_id=roles[u["role"]].id, full_name=u["full_name"], lang=u["lang"], tz=tz,
                            must_change_password=True))


def seed_settings() -> None:
    from .svc import get_setting, set_setting

    with session_scope() as db:
        st = load_yaml("settings.yaml")
        for key in ("default_language", "ai", "telegram", "alerts", "emulator"):
            if get_setting(db, key) is None:
                set_setting(db, key, st.get(key))
        if get_setting(db, "economics") is None:
            set_setting(db, "economics", load_yaml("economics.yaml"))
        if get_setting(db, "mines_path") is None:
            set_setting(db, "mines_path", st.get("mines_path", "mines"))


def seed_mine() -> dict:
    from common.models import Mine
    from core import mine_gen

    from .loader import load_package, seed_reference

    s = get_settings()
    with session_scope() as db:
        seed_reference(db, s.root)
        if db.scalar(select(Mine).limit(1)):
            return {"mine": "exists"}
        path = s.mines_dir / "default_mine"
        if not (path / "mine.yaml").exists():
            log.info("Генерация демо-рудника в %s", path)
            mine_gen.generate(path)
        m = load_package(db, path)
        return {"mine": m.code}


def migrate_data() -> dict:
    """Перенос данных прежней версии: модели машин, профессии, допуски по умолчанию — с отчетом."""
    from .qualify import migrate_patch01

    with session_scope() as db:
        return migrate_patch01(db)


def ensure_clickhouse() -> None:
    try:
        from common import ch

        ch.ensure_schema()
        log.info("ClickHouse: схема готова")
    except Exception as e:
        log.warning("ClickHouse недоступен: %s", e)


def _grafana_hash(password: str, salt: str) -> str:
    """Хэш пароля в формате Grafana (util.EncodePassword): PBKDF2-SHA256, 10000 итераций, 50 байт, hex."""
    import hashlib

    return hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 10000, 50).hex()


def _set_grafana_passwords(users: list[dict]) -> None:
    """Пароли короче 4 символов (политика Grafana) записываются прямо в базу Grafana (PostgreSQL)."""
    import psycopg

    s = get_settings()
    with psycopg.connect(host=s.pg_host, user=s.pg_user, password=s.pg_password, dbname="grafana", connect_timeout=5) as c:
        for u in users:
            row = c.execute('SELECT salt FROM "user" WHERE login = %s', (u["username"],)).fetchone()
            if row:
                c.execute('UPDATE "user" SET password = %s WHERE login = %s', (_grafana_hash(u["password"], row[0]), u["username"]))
        c.commit()


def sync_grafana_users(retries: int = 30) -> None:
    """Те же пользователи и пароли в Grafana: admin → Admin, engineer → Editor, dispatcher → Viewer."""
    import secrets as _secrets

    s = get_settings()
    if not s.grafana_admin_password:
        return
    auth = (s.grafana_admin_user, s.grafana_admin_password)
    roles = {name: r["grafana_role"] for name, r in BUILTIN_ROLES.items()}
    others = [u for u in DEMO_USERS if u["username"] != s.grafana_admin_user]
    for attempt in range(retries):
        try:
            with httpx.Client(base_url=s.grafana_url, auth=auth, timeout=10) as c:
                if c.get("/api/health").status_code != 200:
                    raise RuntimeError("grafana not ready")
                for u in others:
                    r = c.get("/api/users/lookup", params={"loginOrEmail": u["username"]})
                    if r.status_code == 404:
                        c.post("/api/admin/users", json={"name": u["full_name"], "login": u["username"],
                                                          "email": f"{u['username']}@digital-mine.local",
                                                          "password": "tmp-" + _secrets.token_hex(8)}).raise_for_status()
                        r = c.get("/api/users/lookup", params={"loginOrEmail": u["username"]})
                    c.patch(f"/api/org/users/{r.json()['id']}", json={"role": roles[u["role"]]})
            _set_grafana_passwords(others)
            log.info("Grafana: пользователи синхронизированы")
            return
        except Exception as e:
            log.info("Grafana пока недоступна (%s), попытка %d", e, attempt + 1)
            time.sleep(10)


def _seed_all() -> dict:
    migrate()
    seed_users()
    seed_settings()
    res = seed_mine()
    res["migrated"] = migrate_data()
    ensure_clickhouse()
    return res


def run_all(background_grafana: bool = True) -> dict:
    eng = get_engine()
    if eng.dialect.name == "postgresql":
        # несколько реплик api стартуют одновременно: начальные данные заполняет одна, остальные ждут
        with eng.connect() as c:
            c.execute(text("SELECT pg_advisory_lock(424243)"))
            c.commit()
            try:
                res = _seed_all()
            finally:
                c.execute(text("SELECT pg_advisory_unlock(424243)"))
                c.commit()
    else:
        res = _seed_all()
    if background_grafana:
        threading.Thread(target=sync_grafana_users, daemon=True, name="grafana-users").start()
    else:
        sync_grafana_users(retries=6)
    return res


def main() -> None:
    setup_logging()
    ap = argparse.ArgumentParser()
    ap.add_argument("--start-emulator", action="store_true")
    a = ap.parse_args()
    res = run_all(background_grafana=False)
    print("bootstrap:", res)
    if a.start_emulator:
        s = get_settings()
        r = httpx.post(s.emulator_url + "/emulator/start", json={"speed": 60}, timeout=30,
                       headers={"x-internal-token": s.internal_token})
        print("emulator:", r.status_code, r.text[:200])


if __name__ == "__main__":
    main()
