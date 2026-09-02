#!/usr/bin/env python3
"""Rasterize datapyn_logo.svg into datapyn.icns (macOS iconutil)."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SVG = ROOT / "source" / "src" / "assets" / "datapyn_logo.svg"
OUT = ROOT / "source" / "src" / "assets" / "datapyn.icns"

SIZES = {
    "icon_16x16.png": 16,
    "icon_16x16@2x.png": 32,
    "icon_32x32.png": 32,
    "icon_32x32@2x.png": 64,
    "icon_128x128.png": 128,
    "icon_128x128@2x.png": 256,
    "icon_256x256.png": 256,
    "icon_256x256@2x.png": 512,
    "icon_512x512.png": 512,
    "icon_512x512@2x.png": 1024,
}


def main() -> int:
    if sys.platform != "darwin":
        print("generate_icns.py requires macOS (iconutil).", file=sys.stderr)
        return 1
    if not SVG.is_file():
        print(f"Missing SVG: {SVG}", file=sys.stderr)
        return 1

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    from PyQt6.QtGui import QImage, QPainter
    from PyQt6.QtSvg import QSvgRenderer
    from PyQt6.QtWidgets import QApplication

    app = QApplication(sys.argv)
    renderer = QSvgRenderer(str(SVG))
    if not renderer.isValid():
        print(f"Invalid SVG: {SVG}", file=sys.stderr)
        return 1

    iconset = Path(tempfile.mkdtemp(suffix=".iconset"))
    try:
        rasters: dict[int, QImage] = {}
        for px in sorted(set(SIZES.values())):
            image = QImage(px, px, QImage.Format.Format_ARGB32)
            image.fill(0)
            painter = QPainter(image)
            renderer.render(painter)
            painter.end()
            rasters[px] = image
        for name, px in SIZES.items():
            rasters[px].save(str(iconset / name), "PNG")
        subprocess.run(
            ["iconutil", "-c", "icns", str(iconset), "-o", str(OUT)],
            check=True,
        )
        print(f"Wrote {OUT}")
        return 0
    finally:
        app.quit()
        shutil.rmtree(iconset, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
