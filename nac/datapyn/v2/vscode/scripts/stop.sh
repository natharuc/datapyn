#!/usr/bin/env bash
set -euo pipefail
CHECKOUT="${VSCODE_CHECKOUT:-$(cd "$(dirname "$0")/.." && pwd)/checkout}"
pkill -f "$CHECKOUT/.build/electron/datapyn" 2>/dev/null || true
sleep 2
echo "[datapyn-v2] Stopped DataPyn fork"
