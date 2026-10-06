"""Шина событий NATS JetStream. Поток DM, темы dm.<тип>.<...>."""
from __future__ import annotations

import asyncio
import json
import logging
import threading
from datetime import datetime, timezone

from .settings import get_settings
from .web import EVENTS

log = logging.getLogger("bus")
STREAM = "DM"
SUBJECTS = ["dm.>"]


async def connect():
    import nats

    nc = await nats.connect(get_settings().nats_url, max_reconnect_attempts=-1, reconnect_time_wait=2,
                            connect_timeout=5)
    js = nc.jetstream()
    try:
        await js.add_stream(name=STREAM, subjects=SUBJECTS, max_bytes=512 * 1024 * 1024,
                            max_age=3 * 24 * 3600)
    except Exception as e:  # поток уже есть
        log.debug("add_stream: %s", e)
    return nc, js


def envelope(kind: str, data: dict) -> bytes:
    data = dict(data)
    data.setdefault("ts", datetime.now(timezone.utc).isoformat())
    data["type"] = kind
    return json.dumps(data, ensure_ascii=False, default=str).encode()


class SyncPublisher:
    """Публикация из синхронного кода (api): отдельный поток с собственным event loop."""

    def __init__(self) -> None:
        self._loop: asyncio.AbstractEventLoop | None = None
        self._js = None
        self._lock = threading.Lock()

    def _ensure(self) -> None:
        with self._lock:
            if self._loop:
                return
            loop = asyncio.new_event_loop()
            threading.Thread(target=loop.run_forever, daemon=True, name="nats-pub").start()
            self._loop = loop

            async def _c():
                _, js = await connect()
                self._js = js

            fut = asyncio.run_coroutine_threadsafe(_c(), loop)
            try:
                fut.result(timeout=10)
            except Exception as e:
                log.warning("NATS недоступен: %s", e)

    def publish(self, subject: str, kind: str, data: dict) -> None:
        try:
            self._ensure()
            if not self._js or not self._loop:
                return
            asyncio.run_coroutine_threadsafe(self._js.publish(subject, envelope(kind, data)), self._loop)
            EVENTS.labels(get_settings().service, "published").inc()
        except Exception as e:
            log.warning("publish %s: %s", subject, e)


publisher = SyncPublisher()


def publish(subject: str, kind: str, data: dict) -> None:
    if get_settings().db_url.startswith("sqlite"):  # тесты
        return
    publisher.publish(subject, kind, data)
