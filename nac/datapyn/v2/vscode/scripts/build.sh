#!/usr/bin/env bash
# Build DataPyn VS Code fork (after bootstrap).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
V2_ROOT="$(cd "$ROOT/.." && pwd)"
CHECKOUT="${VSCODE_CHECKOUT:-$ROOT/checkout}"

# VS Code upstream requires Node major from checkout/.nvmrc (currently 24.x)
# shellcheck source=/dev/null
. "$ROOT/scripts/use-node.sh"

if [[ ! -d "$CHECKOUT" ]]; then
  echo "[datapyn-v2] Run bootstrap first: $ROOT/scripts/bootstrap.sh" >&2
  exit 1
fi

NPM="${DATAPYN_NODE%/*}/npm"
if [[ ! -x "$NPM" ]]; then
  NPM="$(command -v npm)"
fi

echo "[datapyn-v2] Compile built-in extension"
cd "$V2_ROOT/extension"
"$NPM" install
"$NPM" run compile

echo "[datapyn-v2] Install + compile VS Code (first run takes a long time)"
cd "$CHECKOUT"
echo "[datapyn-v2] npm $($NPM -v) + node $($DATAPYN_NODE -v)"

# Upstream vscode no longer supports yarn; npm must be < 12 (bundled with Node 24 is ok).
export npm_config_user_agent="npm/11.0.0"
"$NPM" install --no-audit --no-fund
"$NPM" run compile

echo "[datapyn-v2] Build finished. Launch: $CHECKOUT/scripts/code.sh"
