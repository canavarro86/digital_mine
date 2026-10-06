# Общие переменные и функции скриптов. Подключается через: source scripts/lib.sh
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
export PATH="$HOME/.local/bin:$PATH"
export KUBECONFIG="$ROOT/.secrets/kubeconfig"
export HELM_CONFIG_HOME="$ROOT/.cache/helm/config" HELM_CACHE_HOME="$ROOT/.cache/helm/cache" HELM_DATA_HOME="$ROOT/.cache/helm/data"
unset HTTP_PROXY HTTPS_PROXY http_proxy https_proxy ALL_PROXY all_proxy
CLUSTER="${CLUSTER_NAME:-digital-mine}"
NS="${NAMESPACE:-digital-mine}"
HTTP_PORT="${HTTP_PORT:-9999}"
API_PORT="${API_PORT:-6550}"
K3S_IMAGE="rancher/k3s:v1.35.5-k3s1"
IMAGE_TAG="${IMAGE_TAG:-dev}"
PY_IMAGE="digital-mine-py"
WEB_IMAGE="digital-mine-web"
c_ok()   { printf '\033[32m✔ %s\033[0m\n' "$*"; }
c_warn() { printf '\033[33m⚠ %s\033[0m\n' "$*"; }
c_err()  { printf '\033[31m✘ %s\033[0m\n' "$*" >&2; }
step()   { printf '\n\033[1;36m== %s ==\033[0m\n' "$*"; }
cluster_exists() { k3d cluster list -o json 2>/dev/null | grep -q "\"name\":\"$CLUSTER\""; }
