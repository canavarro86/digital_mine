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


# «е» с точками в продукте не используется: интерфейс, языки, демо-данные, тексты алертов и отчетов, README
YO = ("ё", "Ё")
TEXT = {".py", ".json", ".yaml", ".yml", ".ts", ".tsx", ".css", ".html", ".md", ".txt", ".xml", ".csv", ".j2", ".sh"}
SKIP = {"node_modules", "dist", "__pycache__", ".pytest_cache", ".ruff_cache", "test-results"}


def _yo_lines(p: Path) -> list[str]:
    return [f"{p.relative_to(ROOT) if p.is_relative_to(ROOT) else p.name}:{n}: {line.strip()[:80]}"
            for n, line in enumerate(p.read_text(encoding="utf-8", errors="ignore").splitlines(), 1)
            if any(y in line for y in YO)]


def _product_files():
    yield ROOT / "README.md"
    for d in ("locales", "config", "prompts", "services"):
        for p in (ROOT / d).rglob("*"):
            if p.is_file() and p.suffix in TEXT and not SKIP & set(p.parts):
                yield p


def test_no_yo_in_product():
    assert (ROOT / "README.md").is_file(), "README.md должен быть в образе тестов"
    files = list(_product_files())
    assert any(p.parts[-2:] == ("core", "mine_gen.py") for p in files)  # демо-рудник
    assert any(p.parts[-2:] == ("locales", "es.json") for p in files)
    bad = [x for p in files for x in _yo_lines(p)]
    assert not bad, "буква «е» с точками:\n" + "\n".join(bad[:30])


def test_no_yo_in_generated_demo_mine(tmp_path):
    from core import mine_gen

    mine_gen.generate(tmp_path)
    bad = [x for p in tmp_path.rglob("*") if p.is_file() for x in _yo_lines(p)]
    assert not bad, bad
