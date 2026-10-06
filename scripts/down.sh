#!/usr/bin/env bash
# make down: удаляет кластер, образы проекта, пароли и кэш. Резервные копии backups/ сохраняются.
source "$(dirname "$0")/lib.sh"
if cluster_exists; then k3d cluster delete "$CLUSTER"; c_ok "Кластер $CLUSTER удалён"; else c_ok "Кластера нет"; fi
for img in $(docker images --format '{{.Repository}}:{{.Tag}}' | grep -E "^(${PY_IMAGE}|${WEB_IMAGE}|ghcr.io/canavarro86/digital-mine-(py|web)):" || true); do docker rmi "$img" >/dev/null && c_ok "Образ $img удалён"; done
docker ps -a --filter "label=app=digital-mine-runner" -q | xargs -r docker rm -f >/dev/null
rm -rf .secrets .cache mines/default_mine
c_ok "Пароли (.secrets), кэш (.cache) и сгенерированный демо-рудник удалены. backups/ сохранены."
