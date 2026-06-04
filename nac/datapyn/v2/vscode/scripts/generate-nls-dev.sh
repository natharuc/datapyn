#!/usr/bin/env bash
# Dev fallback: esbuild transpile does not emit nls.* — create minimal English pack in out/.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT="${VSCODE_OUT:-$ROOT/checkout/out}"

mkdir -p "$OUT"
echo '[]' > "$OUT/nls.messages.json"
echo '[]' > "$OUT/nls.keys.json"
echo '{}' > "$OUT/nls.metadata.json"
printf '%s\n' '/*---------------------------------------------------------
 * Copyright (C) Microsoft Corporation. All rights reserved.
 *--------------------------------------------------------*/
globalThis._VSCODE_NLS_MESSAGES=[];' > "$OUT/nls.messages.js"

echo "[datapyn-v2] Wrote dev NLS stubs in $OUT"
