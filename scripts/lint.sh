#!/usr/bin/env bash
# make lint: ruff (Python), eslint + tsc (интерфейс), helm lint и kubeconform (чарт)
source "$(dirname "$0")/lib.sh"
rc=0
if [ "${1:-all}" != chart ]; then
  step "ruff"
  docker run --rm -u "$(id -u)" -e RUFF_CACHE_DIR=/tmp/rc -v "$ROOT/services:/s" -w /s python:3.12.15-slim-trixie \
    sh -c "pip install -q --root-user-action=ignore ruff==0.16.10 >/dev/null 2>&1; ruff check ." || rc=1
  step "eslint + tsc"
  docker run --rm -u "$(id -u)" -e HOME=/tmp -v "$ROOT/services/web:/web" -w /web node:22.23.3-alpine3.24 \
    sh -c "npm ci --no-audit --no-fund >/dev/null 2>&1 || true; npx eslint src && npx tsc -b" || rc=1
fi
step "helm lint + kubeconform"
helm lint charts/digital-mine || rc=1
helm template digital-mine charts/digital-mine | kubeconform -strict -summary -ignore-missing-schemas || rc=1
helm template ch deploy/charts/clickhouse -f deploy/values/clickhouse.yaml | kubeconform -strict -summary || rc=1
exit $rc
