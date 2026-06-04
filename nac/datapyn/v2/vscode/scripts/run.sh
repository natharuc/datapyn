#!/usr/bin/env bash
# Launch DataPyn fork in foreground (attached terminal).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
export DATAPYN_FOREGROUND=1
exec "$ROOT/scripts/start.sh" "$@"
