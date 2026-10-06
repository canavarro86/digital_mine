"""Резервное копирование файлов MinIO через S3-API: python -m api.objects backup > files.tgz / restore < files.tgz"""
from __future__ import annotations

import io
import sys
import tarfile

from common import storage
from common.settings import get_settings


def backup() -> None:
    c = storage._client()
    bucket = get_settings().minio_bucket
    with tarfile.open(fileobj=sys.stdout.buffer, mode="w|gz") as tar:
        if c is None:
            return
        for obj in c.list_objects(bucket, recursive=True):
            data = storage.get(obj.object_name)
            info = tarfile.TarInfo(obj.object_name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))


def restore() -> None:
    with tarfile.open(fileobj=sys.stdin.buffer, mode="r|gz") as tar:
        for m in tar:
            if m.isfile():
                storage.put(m.name, tar.extractfile(m).read())


if __name__ == "__main__":
    {"backup": backup, "restore": restore}[sys.argv[1]]()
