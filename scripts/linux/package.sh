#!/bin/bash
# Package the PyInstaller onedir as .deb + tar.gz.
# Usage: scripts/linux/package.sh <version>
# Expects dist/DataPyn/ from: uv run pyinstaller scripts/datapyn.spec --clean
set -euo pipefail

VERSION="${1:?version required (e.g. 1.55.0)}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

if [ ! -d dist/DataPyn ]; then
  echo "error: dist/DataPyn not found. Run PyInstaller first." >&2
  exit 1
fi

rm -rf pkg
mkdir -p pkg/opt/datapyn
mkdir -p pkg/usr/share/applications
mkdir -p pkg/usr/share/mime/packages

cp -a dist/DataPyn/. pkg/opt/datapyn/
cp scripts/linux/datapyn.desktop pkg/usr/share/applications/
cp scripts/linux/datapyn-workspace.xml pkg/usr/share/mime/packages/
install -m 755 scripts/linux/datapyn-wrapper.sh pkg/opt/datapyn/datapyn-wrapper.sh

if [ ! -f pkg/opt/datapyn/datapyn_logo.svg ]; then
  cp source/src/assets/datapyn_logo.svg pkg/opt/datapyn/datapyn_logo.svg
fi

DEB_VERSIONED="datapyn_${VERSION}_amd64.deb"
DEB_STABLE="datapyn_amd64.deb"
TAR_VERSIONED="DataPyn-${VERSION}-linux-x86_64.tar.gz"
TAR_STABLE="DataPyn-linux-x86_64.tar.gz"

rm -f "$DEB_VERSIONED" "$DEB_STABLE" "$TAR_VERSIONED" "$TAR_STABLE"

fpm -s dir -t deb \
  -n datapyn \
  -v "$VERSION" \
  --description "DataPyn - SQL + Python IDE for data analysis" \
  --url "https://github.com/${GITHUB_REPOSITORY:-natharuc/datapyn}" \
  --license "MIT" \
  --after-install scripts/linux/postinst.sh \
  --before-remove scripts/linux/prerm.sh \
  --depends libgl1 \
  --depends libegl1 \
  --depends libxkbcommon0 \
  --depends libxkbcommon-x11-0 \
  --depends libdbus-1-3 \
  --depends libxcb-cursor0 \
  --depends libxcb-icccm4 \
  --depends libxcb-image0 \
  --depends libxcb-keysyms1 \
  --depends libxcb-randr0 \
  --depends libxcb-render-util0 \
  --depends libxcb-xinerama0 \
  --depends libxcb-xfixes0 \
  --depends libnss3 \
  --depends libnspr4 \
  --depends libgbm1 \
  --depends libasound2 \
  --depends libdrm2 \
  --depends libxcomposite1 \
  --depends libxdamage1 \
  --depends libxrandr2 \
  --depends libxss1 \
  --depends libxtst6 \
  --depends libatk1.0-0 \
  --depends libatk-bridge2.0-0 \
  --depends libcups2 \
  --depends libpango-1.0-0 \
  --deb-recommends libsecret-1-0 \
  --deb-recommends unixodbc \
  -C pkg \
  -p "$DEB_VERSIONED" \
  .

cp "$DEB_VERSIONED" "$DEB_STABLE"
tar -czf "$TAR_VERSIONED" -C dist DataPyn
cp "$TAR_VERSIONED" "$TAR_STABLE"

echo "Created:"
ls -lh "$DEB_VERSIONED" "$DEB_STABLE" "$TAR_VERSIONED" "$TAR_STABLE"
