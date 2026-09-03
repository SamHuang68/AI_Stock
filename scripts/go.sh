#!/usr/bin/env bash
# Stock Terminal v5.0 — Linux / macOS launch helper (tip UX only)
# Usage:
#   ./scripts/go.sh                 rebuild + restart + browser
#   ./scripts/go.sh pull            git pull TIP_BRANCH, then same
#   ./scripts/go.sh pull <branch>   checkout branch + pull + same (legacy blocked)
#   ./scripts/go.sh rebuild         rebuild + restart, no browser
# Override (not recommended): FORCE_LEGACY=1
set -euo pipefail

MODE="${1:-run}"
TARGET_BRANCH="${2:-}"
OPEN_BROWSER=1
if [[ "${MODE}" == "rebuild" ]]; then OPEN_BROWSER=0; fi

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
PY="${PYTHON:-python3}"
PORT=18432
# tip UX：永遠開總覽，勿開無 hash 的舊圖表殼
URL="http://127.0.0.1:${PORT}/#pulse"

TIP_BRANCH="cursor/st51-docs-ux-on-tip-3497"
if [[ -f "${ROOT}/TIP_BRANCH" ]]; then
  TIP_BRANCH="$(tr -d '[:space:]' < "${ROOT}/TIP_BRANCH")"
fi
ST_VER="5.0"
if [[ -f "${ROOT}/VERSION" ]]; then
  ST_VER="$(tr -d '[:space:]' < "${ROOT}/VERSION")"
fi

is_legacy_branch() {
  case "$1" in
    main|master|cursor/http-client-pool-3497|cursor/range-period-change-b5cf) return 0 ;;
    *) return 1 ;;
  esac
}

CUR_BRANCH="$(git branch --show-current 2>/dev/null || echo '')"

echo
echo "============================================"
echo " Stock Terminal v${ST_VER}  - tip UX"
echo " ${URL}"
echo "============================================"
echo " repo: ${ROOT}"
echo " tip:  ${TIP_BRANCH}"
echo " branch: ${CUR_BRANCH:-?}"
echo

if [[ "${MODE}" != "pull" && "${FORCE_LEGACY:-}" != "1" ]]; then
  if is_legacy_branch "${CUR_BRANCH}"; then
    echo "[BLOCK] Current branch is NOT tip UX: ${CUR_BRANCH}"
    echo "        Tip UX only. Switch with:"
    echo "          ./scripts/go.sh pull ${TIP_BRANCH}"
    exit 2
  fi
fi

if [[ "${MODE}" == "pull" ]]; then
  if [[ -z "${TARGET_BRANCH}" ]]; then
    TARGET_BRANCH="${TIP_BRANCH}"
  fi
  if [[ "${FORCE_LEGACY:-}" != "1" ]] && is_legacy_branch "${TARGET_BRANCH}"; then
    echo "[BLOCK] Refusing checkout of legacy branch: ${TARGET_BRANCH}"
    echo "        That line drops tip UX back to old UI. Tip only:"
    echo "          ./scripts/go.sh pull ${TIP_BRANCH}"
    exit 2
  fi
  echo "[1/4] git fetch / pull → ${TARGET_BRANCH}"
  if git diff --quiet 2>/dev/null && git diff --cached --quiet 2>/dev/null; then
    :
  else
    echo "       stash local changes"
    git stash push -m "auto: go.sh pull before switch" || true
  fi
  git fetch origin "${TARGET_BRANCH}" || git fetch origin || true
  git checkout "${TARGET_BRANCH}"
  git merge --ff-only "origin/${TARGET_BRANCH}" 2>/dev/null \
    || git pull --ff-only origin "${TARGET_BRANCH}" 2>/dev/null \
    || git pull --ff-only || true
  CUR_BRANCH="$(git branch --show-current 2>/dev/null || echo '')"
  echo "       now on: ${CUR_BRANCH}"
fi

echo "[build] python build_v2.py"
"${PY}" build_v2.py

# tip UX 契約：建置產物必須含 shell_v5 / pulse_v5
if ! grep -q 'shell_v5.js' "${ROOT}/stock_terminal_v2.html" \
  || ! grep -q 'pulse_v5.js' "${ROOT}/stock_terminal_v2.html"; then
  echo "[FAIL] built HTML missing tip UX modules (shell_v5 / pulse_v5)"
  exit 1
fi

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

for i in 1 2 3 4 5 6 7 8 9 10; do
  if curl -sf "http://127.0.0.1:${PORT}/selftest" >/dev/null 2>&1 \
     || curl -sf "http://127.0.0.1:${PORT}/" >/dev/null 2>&1; then
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
echo "Done. Tip UX only — Ctrl+F5 after page load."
echo "Log: ${ROOT}/logs/server_go.log"
echo "Must see console: [shell-v5] Stock Terminal ${ST_VER} · route=pulse"
