#!/bin/bash
# Post-install: cria symlink, registra MIME .dpw e atualiza desktop database.
set -e

ln -sf /opt/datapyn/DataPyn /usr/local/bin/datapyn

if command -v update-mime-database &> /dev/null; then
    update-mime-database /usr/share/mime 2>/dev/null || true
fi

if command -v xdg-mime &> /dev/null; then
    xdg-mime default datapyn.desktop application/x-datapyn-workspace 2>/dev/null || true
fi

if command -v update-desktop-database &> /dev/null; then
    update-desktop-database /usr/share/applications 2>/dev/null || true
fi
