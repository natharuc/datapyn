#!/bin/sh
# AppImage entrypoint for the PyInstaller onedir bundle.
# Keep this environment contract in sync with datapyn-wrapper.sh.
APPDIR="$(CDPATH= cd -- "$(dirname -- "$(readlink -f -- "$0")")" && pwd)"

export QTWEBENGINE_DISABLE_SANDBOX=1
export QTWEBENGINE_CHROMIUM_FLAGS="${QTWEBENGINE_CHROMIUM_FLAGS:---no-sandbox}"

exec "$APPDIR/usr/bin/DataPyn" "$@"
