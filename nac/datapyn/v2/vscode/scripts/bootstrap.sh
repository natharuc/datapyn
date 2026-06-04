#!/usr/bin/env bash
# Clone Code-OSS and wire DataPyn built-in extension + product branding.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
V2_ROOT="$(cd "$ROOT/.." && pwd)"
CHECKOUT="${VSCODE_CHECKOUT:-$ROOT/checkout}"
VSCODE_REMOTE="${VSCODE_REPO:-https://github.com/microsoft/vscode.git}"
VSCODE_REF="${VSCODE_REF:-main}"
EXT_SRC="$V2_ROOT/extension"
EXT_DEST="$CHECKOUT/extensions/datapyn"

echo "[datapyn-v2] VS Code checkout: $CHECKOUT"

if [[ ! -d "$CHECKOUT/.git" ]]; then
  echo "[datapyn-v2] Cloning $VSCODE_REMOTE @ $VSCODE_REF ..."
  git clone --depth 1 --branch "$VSCODE_REF" "$VSCODE_REMOTE" "$CHECKOUT"
else
  echo "[datapyn-v2] Checkout already exists, skipping clone"
fi

if [[ ! -d "$EXT_SRC" ]]; then
  echo "[datapyn-v2] ERROR: built-in extension source not found: $EXT_SRC" >&2
  exit 1
fi

echo "[datapyn-v2] Linking built-in extension -> extensions/datapyn"
mkdir -p "$CHECKOUT/extensions"
rm -rf "$EXT_DEST"
ln -sfn "$EXT_SRC" "$EXT_DEST"

echo "[datapyn-v2] Merging product.json (DataPyn branding)"
python3 "$ROOT/scripts/merge_product_json.py" "$ROOT/product.json" "$CHECKOUT/product.json"

echo "[datapyn-v2] Bootstrap done."
echo "  Next: cd $CHECKOUT && yarn && yarn compile"
echo "  Run:  $CHECKOUT/scripts/code.sh   (Linux)  or  scripts\\\\code.bat  (Windows)"
