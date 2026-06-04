#!/usr/bin/env bash
# Build (if needed) and start DataPyn fork.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CHECKOUT="${VSCODE_CHECKOUT:-$ROOT/checkout}"
LOG="${DATAPYN_LOG:-/tmp/datapyn-app.log}"
PIDFILE="${DATAPYN_PIDFILE:-/tmp/datapyn-app.pid}"
USER_DATA="${DATAPYN_USER_DATA:-/tmp/datapyn-fork-data}"
FOREGROUND="${DATAPYN_FOREGROUND:-0}"

# shellcheck source=/dev/null
. "$ROOT/scripts/use-node.sh"
"$ROOT/scripts/ensure-compiled.sh"

export DISPLAY="${DISPLAY:-:1}"
export PATH="$(dirname "$DATAPYN_NODE"):$PATH"
export NODE_ENV=development
export VSCODE_DEV=1
export VSCODE_CLI=1
export VSCODE_SKIP_PRELAUNCH=1
export ELECTRON_ENABLE_LOGGING=1
unset DBUS_SESSION_BUS_ADDRESS 2>/dev/null || true
export LIBGL_ALWAYS_SOFTWARE=1
export ELECTRON_OZONE_PLATFORM_HINT=x11

pkill -f "$CHECKOUT/.build/electron/datapyn" 2>/dev/null || true
sleep 1
mkdir -p "$USER_DATA"

NAME="$("$DATAPYN_NODE" -p "require('./product.json').applicationName" "$CHECKOUT")"
EXE="$CHECKOUT/.build/electron/$NAME"

ARGS=(
  "$CHECKOUT"
  --disable-extension=vscode.vscode-api-tests
  --disable-gpu
  --no-sandbox
  --disable-dev-shm-usage
  --ozone-platform=x11
  --user-data-dir="$USER_DATA"
  "$@"
)

launch() {
  echo "[datapyn-v2] DISPLAY=$DISPLAY"
  echo "[datapyn-v2] $EXE"
  exec "$EXE" "${ARGS[@]}"
}

if [[ "$FOREGROUND" == "1" ]]; then
  echo "[datapyn-v2] Foreground (Ctrl+C to stop). dbus warnings are usually harmless."
  launch
fi

{
  echo "=== $(date -Iseconds) Starting DataPyn ==="
  echo "DISPLAY=$DISPLAY EXE=$EXE"
  "$EXE" "${ARGS[@]}"
} >>"$LOG" 2>&1 &

echo $! >"$PIDFILE"
sleep 3
if kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then
  echo "[datapyn-v2] Running PID=$(cat "$PIDFILE")"
  echo "[datapyn-v2] Log: tail -f $LOG"
  echo "[datapyn-v2] Stop: kill \$(cat $PIDFILE)"
else
  echo "[datapyn-v2] Process exited — last log lines:" >&2
  tail -30 "$LOG" >&2
  exit 1
fi
