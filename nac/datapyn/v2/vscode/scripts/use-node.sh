#!/usr/bin/env bash
# Load Node version required by VS Code checkout (.nvmrc). Must be sourced.
set -euo pipefail

_SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
ROOT="$(cd "$_SCRIPT_DIR/.." && pwd)"
CHECKOUT="${VSCODE_CHECKOUT:-$ROOT/checkout}"
NVMRC="$CHECKOUT/.nvmrc"

if [[ ! -f "$NVMRC" ]]; then
  echo "[datapyn-v2] WARN: no .nvmrc in checkout" >&2
  return 0 2>/dev/null || exit 0
fi

REQUIRED="$(tr -d '[:space:]' < "$NVMRC")"
export NVM_DIR="${NVM_DIR:-$HOME/.nvm}"

if [[ ! -s "$NVM_DIR/nvm.sh" ]]; then
  echo "[datapyn-v2] ERROR: nvm not found. Install nvm and run: nvm install $REQUIRED" >&2
  return 1 2>/dev/null || exit 1
fi

# shellcheck source=/dev/null
. "$NVM_DIR/nvm.sh"
nvm install "$REQUIRED" >/dev/null

# nvm which/current can resolve to /exec-daemon/node on cloud VMs; use explicit version path.
NODE_DIR="$NVM_DIR/versions/node/v$REQUIRED/bin"
NODE_BIN="$NODE_DIR/node"
if [[ ! -x "$NODE_BIN" ]]; then
  # fallback: match installed minors (e.g. 24.16.0 when .nvmrc says 24.15.0)
  NODE_DIR="$(find "$NVM_DIR/versions/node" -maxdepth 2 -path "*/bin/node" 2>/dev/null | head -1 | xargs dirname)"
  NODE_BIN="$NODE_DIR/node"
fi
if [[ ! -x "$NODE_BIN" ]]; then
  echo "[datapyn-v2] ERROR: Node $REQUIRED not installed under nvm" >&2
  return 1 2>/dev/null || exit 1
fi
# Cloud VMs often prepend /exec-daemon (Node 22); VS Code requires .nvmrc major.
_clean_path="$(echo "$PATH" | tr ':' '\n' | grep -v 'exec-daemon' | tr '\n' ':' | sed 's/:$//')"
export PATH="$NODE_DIR:$_clean_path"
export DATAPYN_NODE="$NODE_BIN"
hash -r 2>/dev/null || true
unset -f command 2>/dev/null || true

if ! corepack enable >/dev/null 2>&1; then
  npm install -g yarn >/dev/null 2>&1 || true
fi
corepack prepare yarn@1.22.22 --activate >/dev/null 2>&1 || true

echo "[datapyn-v2] Using Node $($DATAPYN_NODE -v) at $DATAPYN_NODE"
echo "[datapyn-v2] yarn: $(command -v yarn 2>/dev/null || echo 'missing')"
