#!/usr/bin/env bash
# Собирает образы сервисов локально и загружает их в кластер (до CI/CD).
# Импорт: docker save --platform linux/amd64 → ctr import в узле k3d (k3d image import не работает
# с хранилищем containerd в Docker 29 — «content digest not found», см. README, раздел «Решения»).
source "$(dirname "$0")/lib.sh"
only="${1:-all}"
if [ "$only" = all ] || [ "$only" = py ]; then
  step "Сборка образа Python-сервисов ($PY_IMAGE:$IMAGE_TAG)"
  docker build --provenance=false --sbom=false -f services/Dockerfile --target runtime -t "$PY_IMAGE:$IMAGE_TAG" .
fi
if [ "$only" = all ] || [ "$only" = web ]; then
  step "Сборка образа интерфейса ($WEB_IMAGE:$IMAGE_TAG)"
  docker build --provenance=false --sbom=false -f services/web/Dockerfile -t "$WEB_IMAGE:$IMAGE_TAG" .
fi
if cluster_exists; then
  step "Загрузка образов в кластер"
  for img in "$PY_IMAGE:$IMAGE_TAG" "$WEB_IMAGE:$IMAGE_TAG"; do
    case "$only:$img" in all:*|py:$PY_IMAGE*|web:$WEB_IMAGE*) ;; *) continue;; esac
    docker save --platform linux/amd64 "$img" | docker exec -i "k3d-$CLUSTER-server-0" ctr -n k8s.io images import --no-unpack=false - >/dev/null
    c_ok "$img"
  done
fi
