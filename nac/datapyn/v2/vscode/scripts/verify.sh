#!/usr/bin/env bash
# Quick diagnostics for DataPyn v2 fork setup.
set -uo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
V2_ROOT="$(cd "$ROOT/.." && pwd)"
CHECKOUT="${VSCODE_CHECKOUT:-$ROOT/checkout}"
ok=0
fail=0

check() {
  if eval "$2"; then
    echo "  OK   $1"
    ok=$((ok + 1))
  else
    echo "  FAIL $1"
    fail=$((fail + 1))
  fi
}

echo "=== DataPyn v2 verify ==="

check "checkout exists" "[[ -d '$CHECKOUT' ]]"
check "nvm installed" "[[ -s \"\${NVM_DIR:-$HOME/.nvm}/nvm.sh\" ]]"
if [[ -s "${NVM_DIR:-$HOME/.nvm}/nvm.sh" ]]; then
  # shellcheck source=/dev/null
  . "${NVM_DIR:-$HOME/.nvm}/nvm.sh"
  check "Node 24 (nvm)" "[[ \"\$(nvm version 2>/dev/null)\" == v24* ]] || [[ -x \"$HOME/.nvm/versions/node/v24.15.0/bin/node\" ]]"
fi
check "out/vs/nls.js" "[[ -f '$CHECKOUT/out/vs/nls.js' ]]"
check "out/nls.messages.json" "[[ -f '$CHECKOUT/out/nls.messages.json' ]]"
check "electron binary" "[[ -x '$CHECKOUT/.build/electron/datapyn' ]]"
check "built-in extension out" "[[ -f '$V2_ROOT/extension/out/extension.js' ]]"
check "runtime venv" "[[ -d '$V2_ROOT/runtime/.venv' ]]"
check "uv" "command -v uv >/dev/null"
check "datapyn symlink" "[[ -L '$CHECKOUT/extensions/datapyn' ]]"

echo "---"
echo "OK=$ok FAIL=$fail"
if [[ "$fail" -gt 0 ]]; then
  echo "Fix: cd $ROOT && ./scripts/bootstrap.sh && ./scripts/build.sh"
  exit 1
fi
echo "Ready: ./scripts/run.sh"
