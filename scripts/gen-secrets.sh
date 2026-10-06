#!/usr/bin/env bash
# Генерирует пароли сервисов в .secrets/ (один раз) и создаёт Secret dm-secrets в кластере.
source "$(dirname "$0")/lib.sh"
mkdir -p .secrets && chmod 700 .secrets
F=.secrets/services.env
rnd() { head -c 32 /dev/urandom | base64 | tr -dc 'A-Za-z0-9' | head -c "${1:-24}"; }
if [ ! -f "$F" ]; then
  FERNET=$(head -c 32 /dev/urandom | base64 | tr '+/' '-_')
  cat > "$F" <<EOT
PG_SUPERUSER=postgres
PG_SUPERUSER_PASSWORD=$(rnd)
PG_DATABASE=dm
PG_USER=dm
PG_PASSWORD=$(rnd)
CH_USER=dm
CH_PASSWORD=$(rnd)
rootUser=dmminio
rootPassword=$(rnd 32)
JWT_SECRET=$(rnd 48)
FERNET_KEY=$FERNET
INTERNAL_TOKEN=$(rnd 32)
GRAFANA_ADMIN_USER=admin
GRAFANA_ADMIN_PASSWORD=as
EOT
  chmod 600 "$F"
  c_ok "Пароли сгенерированы: $F"
else
  c_ok "Пароли уже есть: $F"
fi
for ns in "$NS" monitoring; do
  kubectl create namespace "$ns" --dry-run=client -o yaml | kubectl apply -f - >/dev/null
  kubectl -n "$ns" create secret generic dm-secrets --from-env-file="$F" --dry-run=client -o yaml | kubectl apply -f - >/dev/null
done
c_ok "Secret dm-secrets создан в $NS и monitoring"
