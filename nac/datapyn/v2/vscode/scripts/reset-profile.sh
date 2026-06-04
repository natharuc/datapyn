#!/usr/bin/env bash
# Reset DataPyn fork user profile (fixes GPU cache / corrupted state after crash).
set -euo pipefail
USER_DATA="${DATAPYN_USER_DATA:-/tmp/datapyn-fork-data}"
pkill -f '.build/electron/datapyn' 2>/dev/null || true
sleep 2
rm -rf "$USER_DATA"
echo "[datapyn-v2] Removed profile: $USER_DATA"
