# -*- mode: python ; coding: utf-8 -*-
# Build: uv run pyinstaller installer/datapyn_setup.spec --clean

import os

ROOT = os.path.abspath(os.path.join(SPEC, "..", ".."))

a = Analysis(
    [os.path.join(ROOT, "installer", "main.py")],
    pathex=[os.path.join(ROOT, "source")],
    binaries=[],
    datas=[
        (os.path.join(ROOT, "source", "src", "assets", "datapyn_logo.svg"), "assets"),
    ],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["matplotlib", "pandas", "numpy", "PyQt6.QtWebEngineWidgets"],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="DataPyn-Setup",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=os.path.join(ROOT, "source", "src", "assets", "datapyn-logo.ico"),
)
