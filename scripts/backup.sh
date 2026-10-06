#!/usr/bin/env bash
# make backup: PostgreSQL (pg_dump), ClickHouse (таблицы в Native), MinIO (файлы), пакеты рудников → backups/<дата>/
source "$(dirname "$0")/lib.sh"
set -a; source .secrets/services.env; set +a
DIR="backups/$(date +%Y%m%d-%H%M%S)"
mkdir -p "$DIR"
step "PostgreSQL"
kubectl -n "$NS" exec postgres-0 -- env PGPASSWORD="$PG_PASSWORD" pg_dump -U "$PG_USER" -d "$PG_DATABASE" -Fc > "$DIR/postgres.dump"
c_ok "$(du -h "$DIR/postgres.dump" | cut -f1)"
step "ClickHouse"
mkdir -p "$DIR/clickhouse"
for t in $(kubectl -n "$NS" exec clickhouse-0 -- clickhouse-client -u "$CH_USER" --password "$CH_PASSWORD" -d mine -q "SHOW TABLES"); do
  kubectl -n "$NS" exec clickhouse-0 -- clickhouse-client -u "$CH_USER" --password "$CH_PASSWORD" -d mine -q "SELECT * FROM $t FORMAT Native" > "$DIR/clickhouse/$t.native"
done
c_ok "$(ls "$DIR/clickhouse" | wc -l) таблиц"
step "MinIO"
kubectl -n "$NS" exec deploy/api -- python -m api.objects backup > "$DIR/minio.tgz"
c_ok "$(tar tzf "$DIR/minio.tgz" | wc -l) файлов"
step "Пакеты рудников"
tar czf "$DIR/mines.tgz" mines
c_ok "Резервная копия: $DIR"
