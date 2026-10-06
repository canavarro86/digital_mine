"""Фабрика FastAPI-приложений: /healthz, /metrics, JSON-логи, счётчики запросов."""
from __future__ import annotations

import json
import logging
import sys
import time

from fastapi import FastAPI, Request, Response
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, Histogram, generate_latest

from .settings import get_settings

REQUESTS = Counter("dm_http_requests_total", "HTTP-запросы", ["service", "method", "path", "status"])
ERRORS = Counter("dm_http_errors_total", "HTTP-ошибки (5xx)", ["service", "path"])
LATENCY = Histogram("dm_http_request_seconds", "Время ответа", ["service", "path"],
                    buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30))
EVENTS = Counter("dm_events_total", "События (опубликовано/обработано)", ["service", "kind"])
QUEUE = Gauge("dm_queue_pending", "Длина очереди", ["service", "queue"])
UP_INFO = Gauge("dm_service_info", "Версия сервиса", ["service", "version"])


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        data = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(record.created)) + "Z",
            "level": record.levelname,
            "service": get_settings().service,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        if record.exc_info:
            data["exc"] = self.formatException(record.exc_info)
        return json.dumps(data, ensure_ascii=False)


def setup_logging() -> None:
    root = logging.getLogger()
    if getattr(root, "_dm_configured", False):
        return
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root.handlers = [handler]
    root.setLevel(get_settings().log_level)
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    root._dm_configured = True  # type: ignore[attr-defined]


def _route_path(request: Request) -> str:
    route = request.scope.get("route")
    return getattr(route, "path", None) or "unmatched"


def create_app(title: str, **kwargs) -> FastAPI:
    setup_logging()
    s = get_settings()
    app = FastAPI(title=title, version=s.version, **kwargs)
    UP_INFO.labels(s.service, s.version).set(1)

    @app.middleware("http")
    async def metrics_mw(request: Request, call_next):
        start = time.perf_counter()
        status = 500
        try:
            response = await call_next(request)
            status = response.status_code
            return response
        finally:
            path = _route_path(request)
            if path not in ("/metrics", "/healthz"):
                REQUESTS.labels(s.service, request.method, path, str(status)).inc()
                LATENCY.labels(s.service, path).observe(time.perf_counter() - start)
                if status >= 500:
                    ERRORS.labels(s.service, path).inc()

    @app.get("/healthz", include_in_schema=False)
    def healthz():
        return {"status": "ok", "service": s.service, "version": s.version}

    @app.get("/metrics", include_in_schema=False)
    def metrics():
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

    return app


def attachment(filename: str) -> dict[str, str]:
    """Заголовок скачивания с именем в UTF-8 (RFC 5987) и ASCII-запасным вариантом."""
    from urllib.parse import quote

    ascii_name = filename.encode("ascii", "ignore").decode() or "file"
    ascii_name = "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in ascii_name)
    return {"Content-Disposition": f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(filename)}"}
