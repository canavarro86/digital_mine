#!/usr/bin/env bash
# make test: pytest (в образе сервисов), Vitest (интерфейс), helm lint + kubeconform (чарт)
source "$(dirname "$0")/lib.sh"
rc=0
step "pytest"
docker build -q --provenance=false -f services/Dockerfile --target test -t digital-mine-test:local . >/dev/null
docker run --rm -e HOME=/tmp -v "$ROOT/tests:/app/tests:ro" digital-mine-test:local python -m pytest -q -p no:cacheprovider tests || rc=1
step "Vitest"
docker run --rm -u "$(id -u)" -e HOME=/tmp -v "$ROOT/services/web:/web" -w /web node:22.23.3-alpine3.24 \
  sh -c "npm ci --no-audit --no-fund >/dev/null 2>&1 || true; npx vitest run" || rc=1
step "Helm-чарт"
bash scripts/lint.sh chart || rc=1
[ $rc -eq 0 ] && c_ok "Все тесты прошли" || c_err "Есть ошибки"
exit $rc
