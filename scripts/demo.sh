#!/usr/bin/env bash
# make demo: запускает эмулятор (скорость ×60, все сценарии в слабой силе)
source "$(dirname "$0")/lib.sh"
kubectl -n "$NS" exec deploy/api -- python -m api.bootstrap --start-emulator
c_ok "Эмулятор запущен. Пульт: http://127.0.0.1:$HTTP_PORT/console"
