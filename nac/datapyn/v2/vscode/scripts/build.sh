#!/usr/bin/env bash
# Build DataPyn VS Code fork (after bootstrap).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
V2_ROOT="$(cd "$ROOT/.." && pwd)"
CHECKOUT="${VSCODE_CHECKOUT:-$ROOT/checkout}"

if [[ ! -d "$CHECKOUT" ]]; then
  echo "[datapyn-v2] Run bootstrap first: $ROOT/scripts/bootstrap.sh" >&2
  exit 1
fi

echo "[datapyn-v2] Compile built-in extension"
cd "$V2_ROOT/extension"
npm install
npm run compile

echo "[datapyn-v2] Compile VS Code (this takes a long time on first run)"
cd "$CHECKOUT"
if ! command -v yarn >/dev/null 2>&1; then
  echo "[datapyn-v2] ERROR: yarn is required (Node 18+)." >&2
  exit 1
fi
yarn
yarn compile

echo "[datapyn-v2] Build finished. Launch: $CHECKOUT/scripts/code.sh"
