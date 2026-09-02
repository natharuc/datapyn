#!/bin/bash
# Create a UDZO DMG from dist/DataPyn.app.
# Usage: scripts/macos/package_dmg.sh <version>
set -euo pipefail

VERSION="${1:?version required (e.g. 1.55.0)}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

APP="dist/DataPyn.app"
if [ ! -d "$APP" ]; then
  echo "error: $APP not found. Run PyInstaller first." >&2
  exit 1
fi

DMG_VERSIONED="DataPyn-${VERSION}-macos-arm64.dmg"
DMG_STABLE="DataPyn-macos-arm64.dmg"
rm -f "$DMG_VERSIONED" "$DMG_STABLE"

STAGE="$(mktemp -d)"
cleanup() { rm -rf "$STAGE"; }
trap cleanup EXIT

cp -R "$APP" "$STAGE/DataPyn.app"
ln -s /Applications "$STAGE/Applications"

hdiutil create \
  -volname "DataPyn" \
  -srcfolder "$STAGE" \
  -ov \
  -format UDZO \
  "$DMG_VERSIONED"

cp "$DMG_VERSIONED" "$DMG_STABLE"
ls -lh "$DMG_VERSIONED" "$DMG_STABLE"
