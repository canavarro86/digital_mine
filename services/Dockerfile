# syntax=docker/dockerfile:1
# Единый образ Python-сервисов: api, calc, importer, analyzer, emulator, ingest, alerts.
# Сервис выбирается командой запуска (см. charts/digital-mine/values.yaml).

# --- LibreDWG (DWG -> DXF): в Debian trixie пакета нет, собираем из исходников ---
FROM python:3.12.15-slim-trixie AS libredwg
ARG LIBREDWG_VERSION=0.14
RUN apt-get update && apt-get install -y --no-install-recommends build-essential pkg-config curl xz-utils ca-certificates \
    && rm -rf /var/lib/apt/lists/*
RUN curl -fsSL https://github.com/LibreDWG/libredwg/releases/download/${LIBREDWG_VERSION}/libredwg-${LIBREDWG_VERSION}.tar.xz | tar xJ -C /tmp \
    && cd /tmp/libredwg-${LIBREDWG_VERSION} \
    && ./configure --prefix=/opt/libredwg --disable-bindings --disable-static CFLAGS="-O2" >/dev/null \
    && make -j"$(nproc)" >/dev/null && make install >/dev/null \
    && rm -rf /tmp/libredwg-* /opt/libredwg/share /opt/libredwg/include \
    && find /opt/libredwg/bin -type f ! -name 'dwg2dxf' ! -name 'dwgread' -delete

# --- Рабочий образ ---
FROM python:3.12.15-slim-trixie AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 \
    PATH=/opt/libredwg/bin:$PATH LD_LIBRARY_PATH=/opt/libredwg/lib \
    DM_ROOT=/app PYTHONPATH=/app/services
RUN apt-get update && apt-get install -y --no-install-recommends \
      libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz-subset0 fonts-dejavu-core fonts-liberation2 curl \
    && rm -rf /var/lib/apt/lists/*
COPY --from=libredwg /opt/libredwg /opt/libredwg
COPY services/requirements.txt /tmp/requirements.txt
RUN pip install --root-user-action=ignore -r /tmp/requirements.txt
WORKDIR /app
COPY config ./config
COPY locales ./locales
COPY prompts ./prompts
COPY services ./services
RUN useradd -u 1000 -m dm && mkdir -p /data && chown dm /data
USER 1000
EXPOSE 8000
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]

# --- Образ для тестов и линтера ---
FROM runtime AS test
COPY services/requirements-dev.txt /tmp/requirements-dev.txt
USER 0
RUN pip install --root-user-action=ignore -r /tmp/requirements-dev.txt
USER 1000
COPY tests ./tests
# README — для проверки текстов продукта (tests/test_locales.py)
COPY README.md ./README.md
CMD ["pytest", "-q", "tests"]
