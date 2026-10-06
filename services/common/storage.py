"""Файлы в MinIO (S3). Без MinIO (тесты) — локальная папка /tmp/dm-files."""
from __future__ import annotations

import io
import logging
from functools import lru_cache
from pathlib import Path

from .settings import get_settings

log = logging.getLogger("storage")
LOCAL = Path("/tmp/dm-files")


@lru_cache
def _client():
    s = get_settings()
    if not s.minio_user:
        return None
    from minio import Minio

    c = Minio(s.minio_endpoint, access_key=s.minio_user, secret_key=s.minio_password, secure=False)
    if not c.bucket_exists(s.minio_bucket):
        c.make_bucket(s.minio_bucket)
    return c


def put(key: str, data: bytes, content_type: str = "application/octet-stream") -> str:
    c = _client()
    if c is None:
        p = LOCAL / key
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
        return key
    c.put_object(get_settings().minio_bucket, key, io.BytesIO(data), len(data), content_type=content_type)
    return key


def get(key: str) -> bytes:
    c = _client()
    if c is None:
        return (LOCAL / key).read_bytes()
    r = c.get_object(get_settings().minio_bucket, key)
    try:
        return r.read()
    finally:
        r.close()
        r.release_conn()
