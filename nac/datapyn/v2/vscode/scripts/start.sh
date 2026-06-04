#!/usr/bin/env bash
# Build (if needed) and start DataPyn fork.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CHECKOUT="${VSCODE_CHECKOUT:-$ROOT/checkout}"
LOG="${DATAPYN_LOG:-/tmp/datapyn-app.log}"
PIDFILE="${DATAPYN_PIDFILE:-/tmp/datapyn-app.pid}"
USER_DATA="${DATAPYN_USER_DATA:-/tmp/datapyn-fork-data}"
FOREGROUND="${DATAPYN_FOREGROUND:-0}"
# Lite = disable built-in Copilot (Agent Host + GPU stress on VMs without auth)
LITE="${DATAPYN_LITE:-0}"
FRESH="${DATAPYN_FRESH:-0}"

# shellcheck source=/dev/null
. "$ROOT/scripts/use-node.sh"
"$ROOT/scripts/ensure-compiled.sh"

export DISPLAY="${DISPLAY:-:1}"
if ! xdpyinfo -display "$DISPLAY" >/dev/null 2>&1; then
  echo "[datapyn-v2] ERROR: DISPLAY $DISPLAY not available. Use desktop VM or export DISPLAY=:1" >&2
  exit 1
fi

export PATH="$(dirname "$DATAPYN_NODE"):$PATH"
export NODE_ENV=development
export VSCODE_DEV=1
export VSCODE_CLI=1
export VSCODE_SKIP_PRELAUNCH=1
export ELECTRON_ENABLE_LOGGING=1
export ELECTRON_DISABLE_SANDBOX=1
unset DBUS_SESSION_BUS_ADDRESS 2>/dev/null || true
export LIBGL_ALWAYS_SOFTWARE=1
export ELECTRON_OZONE_PLATFORM_HINT=x11

stop_datapyn() {
  pkill -f "$CHECKOUT/.build/electron/datapyn" 2>/dev/null || true
  pkill -f "$CHECKOUT/.build/electron/Code" 2>/dev/null || true
  sleep 3
}

stop_datapyn

if [[ "$FRESH" == "1" ]]; then
  rm -rf "$USER_DATA"
  echo "[datapyn-v2] Fresh profile: $USER_DATA"
fi
mkdir -p "$USER_DATA"

NAME="$("$DATAPYN_NODE" -p "require('./product.json').applicationName" "$CHECKOUT")"
EXE="$CHECKOUT/.build/electron/$NAME"

build_args() {
  local lite_mode="$1"
  ARGS=(
    "$CHECKOUT"
    --disable-extension=vscode.vscode-api-tests
    --disable-gpu
    --disable-gpu-compositing
    --in-process-gpu
    --enable-unsafe-swiftshader
    --no-sandbox
    --disable-dev-shm-usage
    --ozone-platform=x11
    --user-data-dir="$USER_DATA"
  )
  if [[ "$lite_mode" == "1" ]]; then
    ARGS+=(--disable-extension=GitHub.copilot-chat)
    echo "[datapyn-v2] Lite mode: Copilot Chat disabled (VM-friendly)" >&2
  fi
  ARGS+=("$@")
}

health_check() {
  local pid="$1"
  local wait_secs="${2:-10}"
  local i
  for ((i = 0; i < wait_secs; i++)); do
    if ! kill -0 "$pid" 2>/dev/null; then
      return 1
    fi
    if grep -q 'launch-failed, code: 1002' "$LOG" 2>/dev/null; then
      if [[ "$(tail -1 "$LOG" | wc -c)" -gt 0 ]]; then
        if tail -20 "$LOG" | grep -q 'launch-failed, code: 1002'; then
          return 2
        fi
      fi
    fi
    sleep 1
  done
  return 0
}

run_background() {
  local lite_mode="$1"
  build_args "$lite_mode"
  {
    echo "=== $(date -Iseconds) Starting DataPyn (lite=$lite_mode) ==="
    echo "DISPLAY=$DISPLAY EXE=$EXE USER_DATA=$USER_DATA"
    "$EXE" "${ARGS[@]}"
  } >>"$LOG" 2>&1 &
  echo $! >"$PIDFILE"
}

launch_foreground() {
  local lite_mode="$1"
  build_args "$lite_mode"
  echo "[datapyn-v2] DISPLAY=$DISPLAY (lite=$lite_mode)"
  echo "[datapyn-v2] $EXE"
  exec "$EXE" "${ARGS[@]}"
}

if [[ "$FOREGROUND" == "1" ]]; then
  echo "[datapyn-v2] Foreground. dbus warnings are usually harmless."
  launch_foreground "$LITE"
fi

: >"$LOG"
run_background "$LITE"
PID=$(cat "$PIDFILE")
HC=$(health_check "$PID" 12 || true)
if [[ "$HC" == "2" ]] && [[ "$LITE" != "1" ]]; then
  echo "[datapyn-v2] launch-failed (1002) — retrying with lite profile..." >&2
  stop_datapyn
  rm -rf "$USER_DATA/GPUCache" "$USER_DATA/CachedData" 2>/dev/null || true
  : >>"$LOG"
  run_background 1
  PID=$(cat "$PIDFILE")
  HC=$(health_check "$PID" 12 || true)
fi

if [[ "$HC" == "1" ]] || [[ "$HC" == "2" ]]; then
  echo "[datapyn-v2] Failed to start (GPU/renderer). Try:" >&2
  echo "  DATAPYN_FRESH=1 DATAPYN_LITE=1 ./scripts/start.sh" >&2
  echo "  ./scripts/reset-profile.sh && DATAPYN_LITE=1 ./scripts/start.sh" >&2
  tail -40 "$LOG" >&2
  exit 1
fi

echo "[datapyn-v2] Running PID=$PID"
echo "[datapyn-v2] Log: tail -f $LOG"
echo "[datapyn-v2] Stop: ./scripts/stop.sh  (or kill $PID)"
