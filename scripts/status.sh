#!/usr/bin/env bash
source "$(dirname "$0")/lib.sh"
if ! cluster_exists; then c_warn "Кластер $CLUSTER не создан (make up)"; exit 0; fi
step "Контейнеры k3d"
docker stats --no-stream --format 'table {{.Name}}\t{{.MemUsage}}\t{{.CPUPerc}}' $(docker ps --filter "name=k3d-$CLUSTER" -q)
step "Поды"
kubectl get pods -A -o wide --no-headers | awk '{printf "%-14s %-48s %-10s %s\n",$1,$2,$4,$5}'
step "Память подов (metrics-server)"
kubectl top pods -A --no-headers 2>/dev/null | sort -k4 -h -r | awk '{printf "%-14s %-48s %8s %8s\n",$1,$2,$3,$4; s+=$4} END {printf "%-63s %8s Mi\n","ИТОГО (поды)",s}' || c_warn "метрики ещё не собраны"
step "HPA"
kubectl get hpa -n "$NS" 2>/dev/null
step "Helm-релизы"
helm list -A
