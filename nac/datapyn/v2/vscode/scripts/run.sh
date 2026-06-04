#!/usr/bin/env bash
# Launch DataPyn VS Code fork (dev build).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CHECKOUT="${VSCODE_CHECKOUT:-$ROOT/checkout}"

if [[ ! -d "$CHECKOUT" ]]; then
  echo "[datapyn-v2] Run bootstrap + build first." >&2
  exit 1
fi

# shellcheck source=/dev/null
. "$ROOT/scripts/use-node.sh"

"$ROOT/scripts/ensure-compiled.sh"

export DISPLAY="${DISPLAY:-:1}"
export PATH="$(dirname "$DATAPYN_NODE"):$PATH"
export ELECTRON_ENABLE_LOGGING="${ELECTRON_ENABLE_LOGGING:-1}"
USER_DATA="${DATAPYN_USER_DATA:-/tmp/datapyn-fork-data}"
mkdir -p "$USER_DATA"

cd "$CHECKOUT"
exec ./scripts/code.sh \
  --disable-gpu \
  --no-sandbox \
  --user-data-dir "$USER_DATA" \
  "$@"
