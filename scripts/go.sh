#!/usr/bin/env bash
# Stock Terminal v5.0 — Linux / macOS launch helper
# Usage:
#   ./scripts/go.sh                 rebuild + restart + browser
#   ./scripts/go.sh pull            git pull, then same
#   ./scripts/go.sh pull <branch>   checkout branch + pull + same
#   ./scripts/go.sh rebuild         rebuild + restart, no browser
set -euo pipefail

MODE="${1:-run}"
TARGET_BRANCH="${2:-}"
OPEN_BROWSER=1
if [[ "${MODE}" == "rebuild" ]]; then OPEN_BROWSER=0; fi

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
PY="${PYTHON:-python3}"
PORT=18432
URL="http://127.0.0.1:${PORT}/stock_terminal_v2.html#pulse"

echo
echo "============================================"
echo " Stock Terminal v5.0"
echo " ${URL}"
echo "============================================"
echo " repo: ${ROOT}"
if git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  echo " branch: $(git branch --show-current 2>/dev/null || echo '?')"
fi
echo

if [[ "${MODE}" == "pull" ]]; then
  echo "[1/4] git pull"
  if [[ -n "${TARGET_BRANCH}" ]]; then
    git fetch origin "${TARGET_BRANCH}" || true
    git checkout "${TARGET_BRANCH}"
    git pull --ff-only origin "${TARGET_BRANCH}" || git pull --ff-only || true
  else
    git pull --ff-only || git pull || true
  fi
fi

echo "[build] python build_v2.py"
"${PY}" build_v2.py

echo "[stop] free port ${PORT}"
if command -v fuser >/dev/null 2>&1; then
  fuser -k "${PORT}/tcp" 2>/dev/null || true
elif command -v lsof >/dev/null 2>&1; then
  PIDS="$(lsof -tiTCP:${PORT} -sTCP:LISTEN 2>/dev/null || true)"
  if [[ -n "${PIDS}" ]]; then
    # shellcheck disable=SC2086
    kill ${PIDS} 2>/dev/null || true
    sleep 0.4
  fi
fi
sleep 0.3

mkdir -p "${ROOT}/logs"
echo "[start] server/server.py → 127.0.0.1:${PORT}"
nohup "${PY}" server/server.py >"${ROOT}/logs/server_go.log" 2>&1 &
disown || true
sleep 0.8

# health wait
for i in 1 2 3 4 5 6 7 8 9 10; do
  if curl -sf "http://127.0.0.1:${PORT}/selftest" >/dev/null 2>&1 \
     || curl -sf "http://127.0.0.1:${PORT}/stock_terminal_v2.html" >/dev/null 2>&1; then
    echo "[ok] server up (${i})"
    break
  fi
  sleep 0.4
done

if [[ "${OPEN_BROWSER}" == "1" ]]; then
  if command -v xdg-open >/dev/null 2>&1; then
    xdg-open "${URL}" >/dev/null 2>&1 || true
  elif command -v open >/dev/null 2>&1; then
    open "${URL}" || true
  else
    echo "Open browser: ${URL}"
  fi
fi

echo
echo "Done. Ctrl+F5 after page load."
echo "Log: ${ROOT}/logs/server_go.log"
