#!/bin/sh
# Launch DataPyn with WebEngine sandbox disabled (required in the PyInstaller bundle).
export QTWEBENGINE_DISABLE_SANDBOX=1
export QTWEBENGINE_CHROMIUM_FLAGS="${QTWEBENGINE_CHROMIUM_FLAGS:---no-sandbox}"
exec /opt/datapyn/DataPyn "$@"
