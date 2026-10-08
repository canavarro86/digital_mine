#!/usr/bin/env bash
# make up: кластер k3d + инфраструктура + наши сервисы на http://127.0.0.1:9999
source "$(dirname "$0")/lib.sh"
START=$(date +%s)

step "1. Проверки"
docker info >/dev/null 2>&1 || { c_err "Docker недоступен"; exit 1; }
c_ok "Docker $(docker version -f '{{.Server.Version}}')"
AVAIL=$(awk '/MemAvailable/{print int($2/1024)}' /proc/meminfo)
if [ "$AVAIL" -lt 5000 ]; then c_warn "Свободно ${AVAIL} МБ ОЗУ (< 5 ГБ). Стек займет ≈5 ГБ — закройте лишние программы (браузеры)."; else c_ok "Свободно ${AVAIL} МБ ОЗУ"; fi
if ! cluster_exists && ss -tln | grep -q ":$HTTP_PORT "; then c_err "Порт $HTTP_PORT занят другим процессом. Остановлено."; ss -tlnp | grep ":$HTTP_PORT "; exit 1; fi
c_ok "Порт $HTTP_PORT"

step "2. Утилиты"
for t in k3d kubectl helm helmfile kubeconform; do command -v $t >/dev/null || { bash scripts/install-tools.sh; break; }; done
c_ok "k3d, kubectl, helm, helmfile, kubeconform"

step "3. Кластер k3d $CLUSTER"
mkdir -p .secrets mines && chmod 700 .secrets
if cluster_exists; then
  c_ok "Кластер уже есть"; k3d cluster start "$CLUSTER" >/dev/null 2>&1 || true
else
  k3d cluster create "$CLUSTER" \
    --image "$K3S_IMAGE" \
    --api-port "127.0.0.1:$API_PORT" \
    -p "127.0.0.1:$HTTP_PORT:80@loadbalancer" \
    --volume "$ROOT/mines:/mnt/mines@server:0" \
    --k3s-arg "--kubelet-arg=eviction-hard=memory.available<200Mi,nodefs.available<5%@server:0" \
    --kubeconfig-update-default=false --kubeconfig-switch-context=false \
    --timeout 300s --wait
fi
k3d kubeconfig get "$CLUSTER" > .secrets/kubeconfig && chmod 600 .secrets/kubeconfig
kubectl wait --for=condition=Ready node --all --timeout=180s >/dev/null
c_ok "Кластер готов, kubeconfig: .secrets/kubeconfig"

step "4. Пароли сервисов"
bash scripts/gen-secrets.sh

step "5. Образы сервисов"
if [ "${SKIP_BUILD:-0}" = "1" ]; then c_warn "SKIP_BUILD=1 — сборка пропущена"; else bash scripts/build.sh; fi

step "6. Установка стека (helmfile)"
bash scripts/deploy.sh

step "7. Пользователи и демо-рудник"
kubectl -n "$NS" rollout status deploy/api --timeout=600s
kubectl -n "$NS" exec deploy/api -- python -m api.bootstrap

step "8. Готово за $(( ($(date +%s)-START)/60 )) мин"
cat <<EOT

  Система:        http://127.0.0.1:$HTTP_PORT/
  Описание API:   http://127.0.0.1:$HTTP_PORT/api/docs
  Grafana:        http://127.0.0.1:$HTTP_PORT/grafana
  Пульт:          http://127.0.0.1:$HTTP_PORT/console   (только admin)

  Пользователи:   admin / as  ·  engineer / en  ·  dispatcher / ds
  Пароли сервисов: cat .secrets/services.env
EOT
