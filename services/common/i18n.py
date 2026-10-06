"""Мультиязычность: тексты только в locales/<язык>.json. Нет перевода → английский + запись в лог."""
from __future__ import annotations

import json
import logging
import re
from functools import lru_cache
from pathlib import Path

from .settings import get_settings

log = logging.getLogger("i18n")
FALLBACK = "en"
_missing: set[tuple[str, str]] = set()


def locales_dir() -> Path:
    return get_settings().locales_dir


def available_languages() -> list[dict]:
    """Список языков строится по файлам в папке locales (glossary.* не считаются)."""
    out = []
    for p in sorted(locales_dir().glob("*.json")):
        if p.stem.startswith("glossary"):
            continue
        data = load(p.stem)
        out.append({"code": p.stem, "name": data.get("_meta", {}).get("name", p.stem)})
    return out


@lru_cache(maxsize=32)
def _load_file(lang: str, mtime: float) -> dict:
    with open(locales_dir() / f"{lang}.json", encoding="utf-8") as f:
        return json.load(f)


def load(lang: str) -> dict:
    p = locales_dir() / f"{lang}.json"
    if not p.exists():
        return {}
    return _load_file(lang, p.stat().st_mtime)


def flatten(d: dict, prefix: str = "") -> dict[str, str]:
    out: dict[str, str] = {}
    for k, v in d.items():
        key = f"{prefix}.{k}" if prefix else k
        if isinstance(v, dict):
            out.update(flatten(v, key))
        else:
            out[key] = v
    return out


def merged(lang: str) -> dict:
    """Словарь языка, дополненный английским там, где нет перевода."""
    base = load(FALLBACK)
    if lang == FALLBACK:
        return base
    return _deep_merge(base, load(lang))


def _deep_merge(a: dict, b: dict) -> dict:
    out = dict(a)
    for k, v in b.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def _lookup(d: dict, key: str):
    cur = d
    for part in key.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return None
        cur = cur[part]
    return cur if isinstance(cur, str) else None


def t(key: str, lang: str = "ru", **params) -> str:
    text = _lookup(load(lang), key)
    if text is None:
        if (lang, key) not in _missing:
            _missing.add((lang, key))
            log.warning("missing translation lang=%s key=%s", lang, key)
        text = _lookup(load(FALLBACK), key) or key
    if not params:
        return text
    # формат i18next: {{name}} — общий для интерфейса и сервера
    return re.sub(r"\{\{\s*(\w+)\s*\}\}", lambda m: str(params.get(m.group(1), m.group(0))), text)


def missing_keys() -> list[str]:
    return sorted(f"{lang}:{key}" for lang, key in _missing)
