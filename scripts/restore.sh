#!/usr/bin/env bash
# make restore b=backups/<папка>
source "$(dirname "$0")/lib.sh"
DIR="${1:?укажите папку: make restore b=backups/<дата>}"
set -a; source .secrets/services.env; set +a
step "PostgreSQL"
kubectl -n "$NS" scale deploy api alerts emulator --replicas=0 >/dev/null
kubectl -n "$NS" exec -i postgres-0 -- env PGPASSWORD="$PG_PASSWORD" pg_restore -U "$PG_USER" -d "$PG_DATABASE" --clean --if-exists < "$DIR/postgres.dump" || true
step "ClickHouse"
for f in "$DIR"/clickhouse/*.native; do
  t=$(basename "$f" .native)
  kubectl -n "$NS" exec clickhouse-0 -- clickhouse-client -u "$CH_USER" --password "$CH_PASSWORD" -d mine -q "TRUNCATE TABLE IF EXISTS $t"
  kubectl -n "$NS" exec -i clickhouse-0 -- clickhouse-client -u "$CH_USER" --password "$CH_PASSWORD" -d mine -q "INSERT INTO $t FORMAT Native" < "$f"
done
step "MinIO и рудники"
tar xzf "$DIR/mines.tgz"
kubectl -n "$NS" scale deploy api alerts emulator --replicas=1 >/dev/null
kubectl -n "$NS" rollout status deploy/api --timeout=600s >/dev/null
[ -s "$DIR/minio.tgz" ] && kubectl -n "$NS" exec -i deploy/api -- python -m api.objects restore < "$DIR/minio.tgz"
c_ok "Восстановлено из $DIR"
