"""Тексты интерфейса: названия меню и языка — рабочие, без тестовых правок."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _ru() -> dict:
    return json.loads((ROOT / "locales" / "ru.json").read_text(encoding="utf-8"))


def test_ru_menu_names():
    ru = _ru()
    assert ru["_meta"]["name"] == "Русский"
    g = ru["menu"]["groups"]
    assert (g["work"], g["mine"], g["blasting"], g["analytics"]) == ("Работа", "Рудник", "БВР", "Анализ")
    assert ru["menu"]["dashboard"] == "Дашборд"
