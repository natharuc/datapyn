#!/usr/bin/env bash
# Run the normal AppImage smoke in a FUSE3-only container with the host device exposed.
set -euo pipefail

VERSION="${1:-}"
if [[ -z "$VERSION" ]]; then
  echo "error: release version is required" >&2
  exit 1
fi

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
ARTIFACT="DataPyn-${VERSION}-x86_64.AppImage"
ARTIFACT_PATH="$ROOT/$ARTIFACT"

if [[ ! -x "$ARTIFACT_PATH" ]]; then
  echo "error: package.sh AppImage artifact is missing or not executable: $ARTIFACT_PATH" >&2
  exit 1
fi

docker run --rm \
  --pull=always \
  --device /dev/fuse \
  --cap-add SYS_ADMIN \
  --security-opt apparmor=unconfined \
  --volume "$ROOT:/workspace:ro" \
  --env "DATAPYN_APPIMAGE_SMOKE_ARTIFACT=/workspace/$ARTIFACT" \
  --env DATAPYN_APPIMAGE_SMOKE_LOG= \
  --env QT_QPA_PLATFORM=offscreen \
  --env QTWEBENGINE_DISABLE_SANDBOX=1 \
  --env QTWEBENGINE_CHROMIUM_FLAGS=--no-sandbox \
  ubuntu:22.04 \
  bash -euc '
    export DEBIAN_FRONTEND=noninteractive
    apt-get update
    apt-get install -y --no-install-recommends \
      file \
      fuse3 \
      libasound2 \
      libatk-bridge2.0-0 \
      libatk1.0-0 \
      libdbus-1-3 \
      libdrm2 \
      libegl1 \
      libegl-mesa0 \
      libgbm1 \
      libgl1 \
      libglib2.0-0 \
      libnss3 \
      libnspr4 \
      libpango-1.0-0 \
      libx11-xcb1 \
      libxcb-cursor0 \
      libxcb-icccm4 \
      libxcb-image0 \
      libxcb-keysyms1 \
      libxcb-randr0 \
      libxcb-render-util0 \
      libxcb-shape0 \
      libxcb-xfixes0 \
      libxcb-xinerama0 \
      libxcomposite1 \
      libxdamage1 \
      libxkbcommon-x11-0 \
      libxkbcommon0 \
      libxrandr2 \
      libxrender1 \
      libxss1 \
      libxtst6 \
      libcups2 \
      python3-pytest

    test "$(uname -m)" = x86_64
    test -c /dev/fuse
    test -x "$(command -v fusermount3)"
    if command -v fusermount >/dev/null 2>&1; then
      fusermount_path="$(command -v fusermount)"
      fusermount_name="$(basename "$fusermount_path")"
      if ! {
        dpkg-query -S "$fusermount_path" 2>/dev/null
        dpkg-query -S "/bin/$fusermount_name" 2>/dev/null
      } | grep -q '^fuse3:'; then
        echo "error: controlled FUSE3 image unexpectedly contains legacy fusermount" >&2
        exit 1
      fi
    fi
    for package in fuse libfuse2 libfuse2t64; do
      if dpkg-query -W -f="${Status}\n" "$package" 2>/dev/null | grep -q "install ok installed"; then
        echo "error: controlled FUSE3 image unexpectedly contains $package" >&2
        exit 1
      fi
    done

    bash /workspace/scripts/linux/package.sh --validate-fuse3-environment
    python3 -m pytest \
      --noconftest \
      -p no:cacheprovider \
      -o addopts= \
      /workspace/tests/test_linux_appimage.py \
      -m integration \
      -k normal_fuse3 \
      -q
  '
