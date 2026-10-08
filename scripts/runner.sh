#!/usr/bin/env bash
# Self-hosted runner GitHub Actions в Docker-контейнере (сеть host: доступ к 127.0.0.1:6550 и :9999).
# Права в кластере — только namespace digital-mine (ServiceAccount ci-deployer).
#   bash scripts/runner.sh <REGISTRATION_TOKEN>   — токен: Settings → Actions → Runners → New self-hosted runner
#   bash scripts/runner.sh stop                   — остановить и удалить runner
source "$(dirname "$0")/lib.sh"
RUNNER_VERSION=2.337.0
NAME=digital-mine-runner
REPO_URL="${REPO_URL:-https://github.com/canavarro86/digital_mine}"
if [ "${1:-}" = stop ]; then docker rm -f "$NAME" >/dev/null 2>&1 && c_ok "runner удален"; exit 0; fi
TOKEN="${1:?Укажите токен регистрации раннера}"
step "Учетная запись Kubernetes для CI"
kubectl apply -f deploy/runner/rbac.yaml >/dev/null
SA_TOKEN=$(kubectl -n "$NS" create token ci-deployer --duration=8760h)
CA=$(kubectl config view --raw -o jsonpath='{.clusters[0].cluster.certificate-authority-data}')
mkdir -p .secrets/runner && chmod 711 .secrets/runner
cat > .secrets/runner/kubeconfig <<EOK
apiVersion: v1
kind: Config
clusters: [{name: k3d, cluster: {server: "https://127.0.0.1:$API_PORT", certificate-authority-data: $CA}}]
users: [{name: ci-deployer, user: {token: $SA_TOKEN}}]
contexts: [{name: ci, context: {cluster: k3d, user: ci-deployer, namespace: $NS}}]
current-context: ci
EOK
chmod 644 .secrets/runner/kubeconfig
c_ok "kubeconfig CI: .secrets/runner/kubeconfig (только namespace $NS)"
step "Контейнер runner'а"
docker rm -f "$NAME" >/dev/null 2>&1 || true
docker run -d --name "$NAME" --restart unless-stopped --network host \
  --label app=digital-mine-runner \
  -v "$ROOT/.secrets/runner:/runner-secrets:ro" \
  -v "$HOME/.local/bin/helm:/usr/local/bin/helm:ro" \
  -v "$HOME/.local/bin/kubectl:/usr/local/bin/kubectl:ro" \
  -e RUNNER_TOKEN="$TOKEN" -e REPO_URL="$REPO_URL" \
  "ghcr.io/actions/actions-runner:$RUNNER_VERSION" \
  bash -c './config.sh --unattended --replace --url "$REPO_URL" --token "$RUNNER_TOKEN" --name digital-mine-home --labels digital-mine --work _work && ./run.sh'
sleep 8
docker logs --tail 5 "$NAME"
c_ok "runner запущен (метка digital-mine)"
