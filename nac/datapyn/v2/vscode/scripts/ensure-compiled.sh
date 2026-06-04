#!/usr/bin/env bash
# Ensure VS Code fork out/ is complete enough to launch (fixes ERR_MODULE_NOT_FOUND nls.js).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CHECKOUT="${VSCODE_CHECKOUT:-$ROOT/checkout}"

MARKERS=(
  "$CHECKOUT/out/vs/nls.js"
  "$CHECKOUT/out/nls.messages.json"
  "$CHECKOUT/out/vs/code/electron-browser/workbench/workbench.js"
  "$CHECKOUT/.build/electron/datapyn"
)

missing=0
for f in "${MARKERS[@]}"; do
  if [[ ! -e "$f" ]]; then
    echo "[datapyn-v2] Missing: $f" >&2
    missing=1
  fi
done

if [[ "$missing" -eq 0 ]]; then
  echo "[datapyn-v2] Compile output OK"
  exit 0
fi

echo "[datapyn-v2] Incomplete build — running transpile + electron..." >&2
# shellcheck source=/dev/null
. "$ROOT/scripts/use-node.sh"

NPM="${DATAPYN_NODE%/*}/npm"
cd "$CHECKOUT"
export npm_config_user_agent="npm/11.0.0"
"$DATAPYN_NODE" build/next/index.ts transpile
"$ROOT/scripts/generate-nls-dev.sh"
"$NPM" run electron

for f in "${MARKERS[@]}"; do
  if [[ ! -e "$f" ]]; then
    echo "[datapyn-v2] Still missing after repair: $f" >&2
    echo "[datapyn-v2] Run: cd $ROOT && ./scripts/build.sh" >&2
    exit 1
  fi
done
echo "[datapyn-v2] Repair OK"
