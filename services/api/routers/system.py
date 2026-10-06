"""Языки, системные настройки (ИИ, Telegram, пороги алертов, экономика), экспорт/импорт настроек, платформа."""
from __future__ import annotations

import json

import httpx
from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from common import i18n
from common.db import get_db
from common.models import Mine, Setting
from common.security import decrypt, encrypt
from common.settings import get_settings
from common.timeutil import current_shift, utcnow
from common.web import attachment

from ..deps import CurrentUser, audit, get_current_user, require
from ..svc import active_mine, get_setting, set_setting

router = APIRouter(prefix="/api", tags=["system"])

EDITABLE = ("default_language", "ai", "telegram", "alerts", "economics", "emulator", "mines_path", "edd_template")


@router.get("/i18n/languages")
def languages():
    return i18n.available_languages()


@router.get("/i18n/{lang}")
def translations(lang: str):
    if lang not in {x["code"] for x in i18n.available_languages()}:
        raise HTTPException(404, "errors.not_found")
    return i18n.merged(lang)


@router.post("/i18n/missing")
def report_missing(body: dict):
    """Интерфейс сообщает о ключах без перевода — пишем в лог (раздел 4.1)."""
    import logging

    for k in (body.get("keys") or [])[:50]:
        logging.getLogger("i18n").warning("missing translation lang=%s key=%s", body.get("lang"), k)
    return {"ok": True}


@router.get("/clock")
def clock(db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_user)):
    m = active_mine(db)
    sh = current_shift(m.config)
    from .mine import shifts_state

    st = shifts_state(m.config)
    return {"utc": utcnow().isoformat(), "mine_tz": m.config.get("timezone", "UTC"), "user_tz": user.tz,
            "mine_name": m.name, "country": m.config.get("country", ""),
            "shift": {k: (v.isoformat() if hasattr(v, "isoformat") else v) for k, v in sh.items()},
            "blast": {"windows": st["current"]["windows"], "now": st["blast_now"], "next": st["next_blast"],
                      "reentry_min": st["reentry_min"]}}


def _mask_ai(ai: dict) -> dict:
    ai = json.loads(json.dumps(ai or {}))
    for p in (ai.get("providers") or {}).values():
        if p.get("api_key_enc"):
            p["api_key_set"] = True
            p.pop("api_key_enc")
    return ai


@router.get("/settings")
def get_settings_all(db: Session = Depends(get_db), _: CurrentUser = Depends(require("system.settings"))):
    out = {k: get_setting(db, k) for k in EDITABLE}
    out["ai"] = _mask_ai(out["ai"])
    if out.get("telegram", {}) and out["telegram"].get("bot_token_enc"):
        out["telegram"] = dict(out["telegram"], bot_token_set=True)
        out["telegram"].pop("bot_token_enc")
    return out


@router.put("/settings/{key}")
def put_setting(key: str, body: dict, db: Session = Depends(get_db), user: CurrentUser = Depends(require("system.settings"))):
    if key not in EDITABLE:
        raise HTTPException(400, "errors.unknown_setting")
    value = body.get("value")
    if key == "ai":
        old = get_setting(db, "ai") or {}
        for name, p in (value.get("providers") or {}).items():
            new_key = p.pop("api_key", None)
            p.pop("api_key_set", None)
            if new_key:
                p["api_key_enc"] = encrypt(new_key)
            elif (old.get("providers") or {}).get(name, {}).get("api_key_enc") and not p.pop("clear_key", False):
                p["api_key_enc"] = old["providers"][name]["api_key_enc"]
    if key == "telegram":
        old = get_setting(db, "telegram") or {}
        tok = value.pop("bot_token", None)
        value.pop("bot_token_set", None)
        if tok:
            value["bot_token_enc"] = encrypt(tok)
        elif old.get("bot_token_enc"):
            value["bot_token_enc"] = old["bot_token_enc"]
    set_setting(db, key, value)
    audit(db, user, "settings_update", "settings", key, {"key": key})
    db.commit()
    return {"ok": True}


@router.get("/settings/export")
def export_settings(db: Session = Depends(get_db), user: CurrentUser = Depends(require("system.settings"))):
    data = {s.key: s.value for s in db.scalars(select(Setting))}
    for k in ("ai", "telegram"):  # ключи не выгружаются
        if k in data:
            data[k] = json.loads(json.dumps(data[k]).replace("_enc\"", "_enc_removed\""))
    data["mines"] = [{"code": m.code, "config": m.config} for m in db.scalars(select(Mine))]
    audit(db, user, "settings_export", "settings", "", commit=True)
    return Response(json.dumps(data, ensure_ascii=False, indent=2), media_type="application/json",
                    headers=attachment("digital_mine_settings.json"))


@router.post("/settings/import")
def import_settings(body: dict, db: Session = Depends(get_db), user: CurrentUser = Depends(require("system.settings"))):
    n = 0
    for k, v in body.items():
        if k in EDITABLE and k not in ("ai", "telegram"):
            set_setting(db, k, v.get("v", v) if isinstance(v, dict) else v)
            n += 1
    for m in body.get("mines", []):
        mine = db.scalar(select(Mine).where(Mine.code == m["code"]))
        if mine:
            mine.config = m["config"]
            n += 1
    audit(db, user, "settings_import", "settings", "", {"count": n})
    db.commit()
    return {"imported": n}


def telegram_config(db: Session) -> tuple[str, str]:
    s = get_settings()
    tg = get_setting(db, "telegram") or {}
    token = decrypt(tg["bot_token_enc"]) if tg.get("bot_token_enc") else s.telegram_bot_token
    return token, tg.get("chat_id") or s.telegram_chat_id


@router.get("/platform")
def platform(_: CurrentUser = Depends(require("alerts.admin.view", "system.settings"))):
    """Состояние сервисов по Prometheus (up, память, перезапуски)."""
    s = get_settings()
    q = {
        "up": 'up{namespace="digital-mine"}',
        "memory": 'sum by (pod) (container_memory_working_set_bytes{namespace=~"digital-mine|monitoring",container!=""})',
        "replicas": 'kube_horizontalpodautoscaler_status_current_replicas{namespace="digital-mine"}',
        "total": 'sum(container_memory_working_set_bytes{container!=""})',
    }
    out = {}
    for k, expr in q.items():
        try:
            r = httpx.get(f"{s.prometheus_url}/api/v1/query", params={"query": expr}, timeout=5).json()
            out[k] = [{"labels": x["metric"], "value": float(x["value"][1])} for x in r["data"]["result"]]
        except Exception as e:
            out[k] = {"error": str(e)}
    return out
