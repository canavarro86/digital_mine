#!/usr/bin/env bash
# Скачивает утилиты кластера в ~/.local/bin (без sudo, без прокси). Версии зафиксированы.
# Запуск: bash required.sh
set -euo pipefail
unset HTTP_PROXY HTTPS_PROXY http_proxy https_proxy ALL_PROXY all_proxy

K3D_VERSION=v5.9.0
KUBECTL_VERSION=v1.37.1
HELM_VERSION=v4.3.0
HELMFILE_VERSION=1.8.1
KUBECONFORM_VERSION=v0.8.0

BIN="$HOME/.local/bin"
mkdir -p "$BIN"
TMP=$(mktemp -d); trap 'rm -rf "$TMP"' EXIT

echo ">> k3d ${K3D_VERSION}"
curl -fL --retry 3 -o "$BIN/k3d" "https://github.com/k3d-io/k3d/releases/download/${K3D_VERSION}/k3d-linux-amd64"
chmod +x "$BIN/k3d"

echo ">> kubectl ${KUBECTL_VERSION}"
curl -fL --retry 3 -o "$BIN/kubectl" "https://dl.k8s.io/release/${KUBECTL_VERSION}/bin/linux/amd64/kubectl"
chmod +x "$BIN/kubectl"

echo ">> helm ${HELM_VERSION}"
curl -fL --retry 3 "https://get.helm.sh/helm-${HELM_VERSION}-linux-amd64.tar.gz" | tar xz -C "$TMP"
install -m755 "$TMP/linux-amd64/helm" "$BIN/helm"

echo ">> helmfile ${HELMFILE_VERSION}"
curl -fL --retry 3 "https://github.com/helmfile/helmfile/releases/download/v${HELMFILE_VERSION}/helmfile_${HELMFILE_VERSION}_linux_amd64.tar.gz" | tar xz -C "$TMP" helmfile
install -m755 "$TMP/helmfile" "$BIN/helmfile"

echo ">> kubeconform ${KUBECONFORM_VERSION}"
curl -fL --retry 3 "https://github.com/yannh/kubeconform/releases/download/${KUBECONFORM_VERSION}/kubeconform-linux-amd64.tar.gz" | tar xz -C "$TMP" kubeconform
install -m755 "$TMP/kubeconform" "$BIN/kubeconform"

echo
echo "===== Проверка ====="
"$BIN/k3d" version
"$BIN/kubectl" version --client
"$BIN/helm" version --short
"$BIN/helmfile" version 2>&1 | grep -i version | head -1
"$BIN/kubeconform" -v
echo
echo "Готово: все утилиты в $BIN"
