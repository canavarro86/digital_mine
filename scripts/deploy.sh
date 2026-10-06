#!/usr/bin/env bash
# Ставит/обновляет все helm-релизы. Аргументы передаются helmfile (например: -l tier=app).
source "$(dirname "$0")/lib.sh"
export IMAGE_TAG
if [ $# -eq 0 ]; then
  # данные → база Grafana → мониторинг и наши сервисы
  helmfile -f deploy/helmfile.yaml --concurrency 2 -l tier=data sync --skip-diff-on-install
  set -a; source .secrets/services.env; set +a
  kubectl -n "$NS" exec postgres-0 -- env PGPASSWORD="$PG_SUPERUSER_PASSWORD" psql -U "$PG_SUPERUSER" -tc \
    "SELECT 1 FROM pg_database WHERE datname='grafana'" | grep -q 1 || \
    kubectl -n "$NS" exec postgres-0 -- env PGPASSWORD="$PG_SUPERUSER_PASSWORD" psql -U "$PG_SUPERUSER" -c "CREATE DATABASE grafana OWNER $PG_USER" >/dev/null
  helmfile -f deploy/helmfile.yaml --concurrency 2 -l tier=monitoring -l tier=app sync --skip-diff-on-install
else
  helmfile -f deploy/helmfile.yaml --concurrency 2 sync --skip-diff-on-install "$@"
fi
# новые образы с тем же тегом dev: перезапуск подов
if [ "$IMAGE_TAG" = "dev" ]; then kubectl -n "$NS" rollout restart deploy >/dev/null 2>&1 || true; fi
