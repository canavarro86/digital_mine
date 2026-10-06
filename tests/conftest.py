"""Тесты запускаются в образе сервисов (make test): PYTHONPATH=services, DM_ROOT — корень репозитория."""
import os
import shutil
import sys
import tempfile
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "services"))
_TMP = Path(tempfile.mkdtemp(prefix="dm-test-"))
for d in ("config", "locales", "prompts"):
    shutil.copytree(ROOT / d, _TMP / d)
(_TMP / "mines").mkdir()
os.environ["DM_ROOT"] = str(_TMP)  # всегда временная копия: в образе DM_ROOT=/app только для чтения
os.environ["DM_DATABASE_URL"] = "sqlite://"
os.environ.setdefault("DM_SERVICE", "test")


@pytest.fixture(scope="session")
def expl():
    data = yaml.safe_load((ROOT / "config" / "explosives.yaml").read_text(encoding="utf-8"))
    return {e["code"]: e for e in data["explosives"]}


@pytest.fixture(scope="session")
def econ():
    return yaml.safe_load((ROOT / "config" / "economics.yaml").read_text(encoding="utf-8"))
