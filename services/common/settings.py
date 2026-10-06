"""Настройки сервисов из переменных окружения (Secret dm-secrets + values чарта)."""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default)


class Settings(BaseModel):
    service: str = _env("DM_SERVICE", "api")
    version: str = _env("DM_VERSION", "dev")
    root: Path = Path(_env("DM_ROOT", str(Path(__file__).resolve().parents[2])))
    log_level: str = _env("DM_LOG_LEVEL", "INFO")
    # PostgreSQL
    database_url: str = _env("DM_DATABASE_URL", "")
    pg_host: str = _env("DM_PG_HOST", "postgres")
    pg_user: str = _env("PG_USER", "dm")
    pg_password: str = _env("PG_PASSWORD", "")
    pg_database: str = _env("PG_DATABASE", "dm")
    # ClickHouse
    ch_host: str = _env("DM_CH_HOST", "clickhouse")
    ch_user: str = _env("CH_USER", "dm")
    ch_password: str = _env("CH_PASSWORD", "")
    ch_database: str = _env("DM_CH_DATABASE", "mine")
    # MinIO
    minio_endpoint: str = _env("DM_MINIO_ENDPOINT", "minio:9000")
    minio_user: str = _env("rootUser", "")
    minio_password: str = _env("rootPassword", "")
    minio_bucket: str = _env("DM_MINIO_BUCKET", "digital-mine")
    # NATS
    nats_url: str = _env("DM_NATS_URL", "nats://nats:4222")
    # Безопасность
    jwt_secret: str = _env("JWT_SECRET", "dev-secret-change-me-please-0123456789")
    fernet_key: str = _env("FERNET_KEY", "")
    internal_token: str = _env("INTERNAL_TOKEN", "dev-internal")
    jwt_hours: int = int(_env("DM_JWT_HOURS", "12"))
    # Соседние сервисы
    calc_url: str = _env("DM_CALC_URL", "http://calc:8000")
    importer_url: str = _env("DM_IMPORTER_URL", "http://importer:8000")
    analyzer_url: str = _env("DM_ANALYZER_URL", "http://analyzer:8000")
    emulator_url: str = _env("DM_EMULATOR_URL", "http://emulator:8000")
    api_url: str = _env("DM_API_URL", "http://api:8000")
    prometheus_url: str = _env("DM_PROMETHEUS_URL", "http://prometheus-server.monitoring.svc")
    grafana_url: str = _env("DM_GRAFANA_URL", "http://grafana.monitoring.svc/grafana")
    grafana_admin_user: str = _env("GRAFANA_ADMIN_USER", "admin")
    grafana_admin_password: str = _env("GRAFANA_ADMIN_PASSWORD", "")
    telegram_bot_token: str = _env("DM_TELEGRAM_BOT_TOKEN", "")
    telegram_chat_id: str = _env("DM_TELEGRAM_CHAT_ID", "")

    @property
    def db_url(self) -> str:
        if self.database_url:
            return self.database_url
        return f"postgresql+psycopg://{self.pg_user}:{self.pg_password}@{self.pg_host}:5432/{self.pg_database}"

    @property
    def config_dir(self) -> Path:
        return self.root / "config"

    @property
    def locales_dir(self) -> Path:
        return self.root / "locales"

    @property
    def prompts_dir(self) -> Path:
        return self.root / "prompts"

    @property
    def mines_dir(self) -> Path:
        return self.root / "mines"


@lru_cache
def get_settings() -> Settings:
    return Settings()


def load_yaml(name: str) -> dict:
    import yaml

    path = get_settings().config_dir / name
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}
