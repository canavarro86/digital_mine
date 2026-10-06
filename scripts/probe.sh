#!/usr/bin/env bash
# Замер простоя при деплое: опрос API (через Traefik → api → PostgreSQL) и интерфейса каждые 0,2 с,
# пока не нажат Ctrl+C или не истекло DURATION секунд. Итог: сколько запросов, сколько не 200.
# Запуск: bash scripts/probe.sh [DURATION=600], затем пуш в main (или make deploy) в другом терминале.
source "$(dirname "$0")/lib.sh"
DURATION="${1:-600}"
BASE="http://127.0.0.1:$HTTP_PORT"
LOG="$ROOT/.cache/probe-$(date +%Y%m%d-%H%M%S).log"
mkdir -p "$ROOT/.cache"
total=0 fail=0
summary() {
  echo
  c_ok "Запросов: $total, ошибок: $fail (лог ошибок: $LOG)"
  exit 0
}
trap summary INT TERM
end=$(( $(date +%s) + DURATION ))
while [ "$(date +%s)" -lt "$end" ]; do
  for url in "$BASE/api/i18n/languages" "$BASE/"; do
    code=$(curl -s -o /dev/null -m 5 -w '%{http_code}' "$url" || true)
    total=$((total + 1))
    if [ "$code" != 200 ]; then
      fail=$((fail + 1))
      echo "$(date +%T) $code $url" | tee -a "$LOG"
    fi
  done
  sleep 0.2
done
summary
