"""Сервис api: основное API системы (раздел 3.2). Документация — /api/docs."""
from __future__ import annotations

import logging

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse

from common.web import create_app

from .routers import (
    admin,
    ai,
    alerts,
    auth,
    catalogs,
    dispatch,
    emulator,
    mine,
    passports,
    reports,
    rings,
    system,
    workflow,
    workings,
)

log = logging.getLogger("api")
app = create_app("UG Blast Loop API", docs_url="/api/docs", openapi_url="/api/openapi.json", redoc_url=None)
for r in (auth, admin, system, mine, workings, catalogs, passports, rings, dispatch, workflow, alerts, reports, ai,
          emulator):
    app.include_router(r.router)


@app.exception_handler(HTTPException)
async def http_error(request: Request, exc: HTTPException):
    detail = exc.detail
    if isinstance(detail, str):
        detail = {"code": detail, "params": {}}
    return JSONResponse({"detail": detail}, status_code=exc.status_code)


@app.on_event("startup")
def startup() -> None:
    """Миграции и начальные данные до приёма запросов (идемпотентно, с блокировкой в PostgreSQL)."""
    import time

    from .bootstrap import run_all

    for attempt in range(30):
        try:
            log.info("bootstrap: %s", run_all())
            return
        except Exception as e:  # база ещё не готова
            log.warning("bootstrap попытка %d: %s", attempt + 1, e)
            time.sleep(5)
    raise RuntimeError("bootstrap failed")
