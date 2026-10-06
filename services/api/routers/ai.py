"""Модуль ИИ: только по кнопке. Сжатая сводка → предпросмотр (размер, $) → отправка → ответ
«проблемы → причины → правки → эффект». Кэш, бюджет на месяц, лимит в сутки, журнал, демо-режим без ключа."""
from __future__ import annotations

import copy
import hashlib
import json
import logging
from datetime import timedelta

import httpx
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from common.bus import publish
from common.db import get_db
from common.models import AiRequest, Analysis, DevPassport, Explosive, PassportRecalc, RingDesign
from common.security import decrypt
from common.settings import get_settings
from common.timeutil import utcnow
from core import analysis as an
from core import passport

from ..deps import CurrentUser, audit, require
from ..svc import explosive_dict, get_setting
from .passports import compute
from .reports import period_report

router = APIRouter(prefix="/api/ai", tags=["ai"])
USE = require("ai.use")
log = logging.getLogger("ai")
MODULES = ("dev_passport", "dev_recalc", "dev_cycle", "rings", "stope_result", "mine_summary")
EST_OUT_TOKENS = 1500


def _cfg(db: Session) -> dict:
    return get_setting(db, "ai") or {}


def _price(cfg: dict, provider: str, model: str) -> tuple[float, float]:
    p = ((cfg.get("providers") or {}).get(provider) or {}).get("models", {}).get(model) or {}
    return float(p.get("price_in", 0)), float(p.get("price_out", 0))


def _provider(cfg: dict) -> tuple[str, str, str]:
    """(провайдер, модель, ключ). Без ключа — демо-режим."""
    prov = cfg.get("provider") or "demo"
    pc = (cfg.get("providers") or {}).get(prov) or {}
    key = decrypt(pc["api_key_enc"]) if pc.get("api_key_enc") else ""
    if prov == "demo" or not key:
        return "demo", "demo", ""
    return prov, cfg.get("model") or pc.get("default_model") or next(iter(pc.get("models", {})), ""), key


def summary(db: Session, module: str, entity_id: str) -> dict:
    """Сжатая сводка (JSON с параметрами и итогами) — не сырые файлы и не облака точек."""
    if module == "dev_passport":
        dp = db.get(DevPassport, int(entity_id))
        return {"module": module, "passport": dp.number, **passport.summary_for_ai(dp.design)}
    if module == "dev_recalc":
        rc = db.get(PassportRecalc, int(entity_id))
        return {"module": module, **passport.summary_for_ai(rc.result)}
    if module in ("dev_cycle", "stope_result"):
        a = db.get(Analysis, int(entity_id))
        return {"module": module, "cycle": a.cycle_no, **an.summary_for_ai(a.result)}
    if module == "rings":
        rd = db.get(RingDesign, int(entity_id))
        d = rd.design
        return {"module": module, "params": d["params"], "indicators": d["indicators"], "warnings": d.get("warnings"),
                "input": {k: v for k, v in d["input"].items() if k != "explosive"},
                "explosive": d["input"]["explosive"].get("name"),
                "ring1": [{k: h[k] for k in ("id", "length", "angle", "uncharged", "charge_kg")} for h in d["rings"][0]["holes"]]
                if d["rings"] else []}
    if module == "mine_summary":
        r = period_report(db, "month" if entity_id == "month" else "day", None, None)
        r.pop("cycles", None)
        return {"module": module, **r}
    raise HTTPException(400, "errors.bad_module")


def _prompt(module: str, lang: str, data: dict) -> tuple[str, str]:
    root = get_settings().prompts_dir
    p = root / f"{module}.{lang}.md"
    if not p.exists():
        p = root / f"{module}.en.md"
    tpl = p.read_text(encoding="utf-8")
    system, _, user_tpl = tpl.partition("\n---\n")
    return system.strip(), user_tpl.replace("{summary}", json.dumps(data, ensure_ascii=False, indent=1, default=str))


def _usage(db: Session) -> dict:
    now = utcnow()
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    spent = db.scalar(select(func.coalesce(func.sum(AiRequest.cost), 0)).where(AiRequest.ts >= month_start)) or 0
    today = db.scalar(select(func.count()).select_from(AiRequest).where(AiRequest.ts >= now - timedelta(days=1),
                                                                        AiRequest.cache_hit.is_(False))) or 0
    cfg = _cfg(db)
    budget = float(cfg.get("monthly_budget_usd", 0) or 0)
    return {"spent_usd": round(float(spent), 4), "budget_usd": budget, "left_usd": round(budget - float(spent), 4),
            "requests_24h": today, "max_requests_per_day": int(cfg.get("max_requests_per_day", 50) or 0)}


@router.get("/usage")
def usage(db: Session = Depends(get_db), _: CurrentUser = Depends(USE)):
    cfg = _cfg(db)
    prov, model, _k = _provider(cfg)
    return {**_usage(db), "provider": prov, "model": model}


@router.post("/preview")
def preview(body: dict, db: Session = Depends(get_db), user: CurrentUser = Depends(USE)):
    module, eid = body["module"], str(body["entity_id"])
    lang = body.get("lang") or user.lang
    data = summary(db, module, eid)
    system, prompt = _prompt(module, lang, data)
    cfg = _cfg(db)
    prov, model, _k = _provider(cfg)
    chars = len(system) + len(prompt)
    tin = int(chars / 3.2)
    pin, pout = _price(cfg, prov, model)
    cost = tin * pin / 1e6 + EST_OUT_TOKENS * pout / 1e6
    h = _hash(module, eid, data, lang, model)
    cached = db.scalar(select(AiRequest).where(AiRequest.input_hash == h, AiRequest.status == "ok").limit(1))
    u = _usage(db)
    blocked = None
    if not cached:
        if u["budget_usd"] <= 0 or (prov != "demo" and u["left_usd"] < cost):
            blocked = "budget"
        elif u["max_requests_per_day"] and u["requests_24h"] >= u["max_requests_per_day"]:
            blocked = "daily_limit"
    return {"module": module, "entity_id": eid, "provider": prov, "model": model, "lang": lang, "system": system,
            "prompt": prompt, "chars": chars, "tokens_in_est": tin, "tokens_out_est": EST_OUT_TOKENS,
            "cost_est_usd": round(cost, 4), "cached": bool(cached), "blocked": blocked, "usage": u}


def _hash(module: str, eid: str, data: dict, lang: str, model: str) -> str:
    return hashlib.sha256(json.dumps([module, eid, data, lang, model], sort_keys=True, default=str).encode()).hexdigest()


def _parse(text: str) -> dict:
    s = text.strip()
    if "```" in s:
        s = s.split("```")[1]
        s = s[s.find("{"):]
    s = s[s.find("{"): s.rfind("}") + 1]
    try:
        return json.loads(s)
    except ValueError:
        return {"problems": [], "causes": [], "changes": [], "effect": text[:2000]}


def call_provider(prov: str, model: str, key: str, system: str, prompt: str, cfg: dict) -> tuple[dict, int, int]:
    if prov == "anthropic":
        import anthropic

        client = anthropic.Anthropic(api_key=key, timeout=180.0)
        resp = client.beta.messages.create(
            model=model, max_tokens=16000, system=system,
            messages=[{"role": "user", "content": prompt}],
            betas=["server-side-fallback-2026-07-01"], fallbacks="default",
            output_config={"effort": "medium"},
        )
        if resp.stop_reason == "refusal":
            raise HTTPException(502, "errors.ai_refused")
        text = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")
        return _parse(text), resp.usage.input_tokens, resp.usage.output_tokens
    url = ((cfg.get("providers") or {}).get(prov) or {}).get("url")
    if not url:
        raise HTTPException(400, "errors.ai_provider")
    r = httpx.post(url, headers={"Authorization": f"Bearer {key}"}, timeout=180, json={
        "model": model, "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}],
        "response_format": {"type": "json_object"}})
    if r.status_code != 200:
        raise HTTPException(502, {"code": "errors.ai_http", "params": {"status": r.status_code}})
    j = r.json()
    u = j.get("usage", {})
    return _parse(j["choices"][0]["message"]["content"]), int(u.get("prompt_tokens", 0)), int(u.get("completion_tokens", 0))


def demo_answer(module: str, lang: str, data: dict) -> dict:
    p = get_settings().prompts_dir / f"demo.{lang}.json"
    if not p.exists():
        p = get_settings().prompts_dir / "demo.en.json"
    demo = json.loads(p.read_text(encoding="utf-8"))
    ans = copy.deepcopy(demo.get(module) or demo["dev_passport"])
    ans["demo"] = True
    return ans


@router.post("/send")
def send(body: dict, db: Session = Depends(get_db), user: CurrentUser = Depends(USE)):
    pv = preview(body, db, user)
    if pv["blocked"]:
        raise HTTPException(400, f"errors.ai_{pv['blocked']}")
    data = summary(db, pv["module"], pv["entity_id"])
    h = _hash(pv["module"], pv["entity_id"], data, pv["lang"], pv["model"])
    cfg = _cfg(db)
    cached = db.scalar(select(AiRequest).where(AiRequest.input_hash == h, AiRequest.status == "ok")
                       .order_by(AiRequest.id.desc()).limit(1))
    if cached:
        req = AiRequest(username=user.username, module=pv["module"], entity_id=pv["entity_id"], provider=cached.provider,
                        model=cached.model, lang=pv["lang"], input_hash=h, cache_hit=True, demo=cached.demo,
                        request={"cached_from": cached.id}, response=cached.response)
    else:
        prov, model, key = _provider(cfg)
        if prov == "demo":
            resp, tin, tout = demo_answer(pv["module"], pv["lang"], data), pv["tokens_in_est"], EST_OUT_TOKENS
            cost, demo = 0.0, True
        else:
            resp, tin, tout = call_provider(prov, model, key, pv["system"], pv["prompt"], cfg)
            pin, pout = _price(cfg, prov, model)
            cost, demo = tin * pin / 1e6 + tout * pout / 1e6, False
        req = AiRequest(username=user.username, module=pv["module"], entity_id=pv["entity_id"], provider=prov, model=model,
                        lang=pv["lang"], input_hash=h, tokens_in=tin, tokens_out=tout, cost=round(cost, 6), demo=demo,
                        request={"system": pv["system"][:4000], "prompt_chars": pv["chars"]}, response=resp)
    db.add(req)
    audit(db, user, "ai_request", "ai", pv["module"], {"cache": req.cache_hit, "cost": req.cost})
    db.commit()
    publish("dm.ai", "ai", {"username": user.username, "module": req.module, "provider": req.provider, "model": req.model,
                            "tokens_in": req.tokens_in, "tokens_out": req.tokens_out, "cost": req.cost,
                            "cache_hit": int(req.cache_hit)})
    return req.as_dict()


@router.get("/requests")
def requests(limit: int = 100, db: Session = Depends(get_db), _: CurrentUser = Depends(USE)):
    return [r.as_dict() for r in db.scalars(select(AiRequest).order_by(AiRequest.id.desc()).limit(limit))]


PARAM_MAP = {"hole_depth": "hole_depth", "глубина": "hole_depth", "depth": "hole_depth", "hole_diameter": "hole_diameter",
             "empty_diameter": "empty_diameter", "cut.type": "cut.type", "cut_type": "cut.type",
             "cut.n_empty": "cut.n_empty", "n_empty": "cut.n_empty", "contour_blasting": "contour_blasting",
             "lookout_deg": "lookout_deg", "initiation": "initiation", "explosive": "explosive"}


@router.post("/requests/{rid}/decision")
def decision(rid: int, body: dict, db: Session = Depends(get_db), user: CurrentUser = Depends(USE)):
    """«Применить к копии паспорта» / «Отклонить». Копию утверждает инженер."""
    req = db.get(AiRequest, rid)
    if not req:
        raise HTTPException(404, "errors.not_found")
    if body["decision"] == "rejected":
        req.decision = "rejected"
        audit(db, user, "ai_reject", "ai", rid)
        db.commit()
        return {"ok": True}
    if req.module not in ("dev_passport", "dev_recalc"):
        raise HTTPException(400, "errors.ai_apply_unsupported")
    if not user.can("passports.edit"):
        raise HTTPException(403, "errors.forbidden")
    if req.module == "dev_passport":
        src = db.get(DevPassport, int(req.entity_id))
    else:
        rc = db.get(PassportRecalc, int(req.entity_id))
        src = db.get(DevPassport, rc.passport_id)
    inp = copy.deepcopy(src.input)
    applied = []
    for ch in (req.response or {}).get("changes", []):
        key = PARAM_MAP.get(str(ch.get("param", "")).strip())
        if not key or ch.get("now") in (None, ""):
            continue
        val = ch["now"]
        if key == "explosive":
            e = db.scalar(select(Explosive).where(Explosive.name.ilike(f"%{val}%")))
            if not e:
                continue
            inp["explosive"] = explosive_dict(e)
        elif key.startswith("cut."):
            inp.setdefault("cut", {})[key.split(".")[1]] = val if key == "cut.type" else int(float(val))
        elif key in ("contour_blasting",):
            inp[key] = str(val).lower() in ("true", "1", "да", "yes", "sí", "si")
        elif key == "initiation":
            inp[key] = val
        else:
            inp[key] = float(val)
        applied.append({"param": key, "was": ch.get("was"), "now": val})
    res = compute(inp)
    new = DevPassport(working_id=src.working_id, number=f"{src.number}-ИИ", name=f"{src.name} (ИИ, копия)", status="draft",
                      typical_id=src.typical_id, parent_id=src.id, input=inp, design=res, indicators=res["indicators"],
                      signatures={"made": user.username, "note": f"AI #{rid}"}, created_by=user.username)
    db.add(new)
    req.decision = "applied"
    audit(db, user, "ai_apply", "ai", rid, {"applied": applied})
    db.commit()
    return {"passport_id": new.id, "applied": applied}
