#!/bin/bash
# Post-install: cria symlink e atualiza desktop database.
set -e

ln -sf /opt/datapyn/DataPyn /usr/local/bin/datapyn

if command -v update-desktop-database &> /dev/null; then
    update-desktop-database /usr/share/applications 2>/dev/null || true
fi
