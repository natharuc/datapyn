#!/usr/bin/env bash
# System packages for building/running VS Code on Ubuntu/Debian (CI-aligned).
set -euo pipefail

if ! command -v apt-get >/dev/null 2>&1; then
  echo "[datapyn-v2] apt-get not found; install VS Code build deps manually" >&2
  exit 0
fi

echo "[datapyn-v2] Installing Linux build dependencies (sudo)..."
sudo apt-get update -qq
sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -qq \
  build-essential \
  pkg-config \
  libx11-dev libxkbfile-dev libsecret-1-dev libkrb5-dev \
  libgtk-3-dev libgbm-dev libnss3-dev libasound2-dev \
  python3 python-is-python3 \
  fakeroot \
  >/dev/null

echo "[datapyn-v2] Linux deps installed."
