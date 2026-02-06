# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec file para DataPyn
Execute: pyinstaller datapyn.spec
"""

import os
import sys
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

# Diretorio raiz do projeto (um nivel acima de scripts/)
ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(SPEC), '..'))

block_cipher = None

# Coletar todos os submódulos necessários
hiddenimports = [
    'PyQt6',
    'PyQt6.QtCore',
    'PyQt6.QtGui', 
    'PyQt6.QtWidgets',
    'PyQt6.Qsci',
    'pandas',
    'numpy',
    'pyodbc',
    'sqlalchemy',
    'json',
    'yaml',
]

# Dados adicionais (assets)
# Destino 'src/assets' para que _MEIPASS atue como equivalente do diretorio source/
datas = [
    (os.path.join(ROOT_DIR, 'source', 'src', 'assets', '*'), os.path.join('src', 'assets')),
]

a = Analysis(
    [os.path.join(ROOT_DIR, 'source', 'main.py')],
    pathex=[ROOT_DIR],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='DataPyn',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,  # False = sem console (aplicacao GUI)
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=os.path.join(ROOT_DIR, 'source', 'src', 'assets', 'datapyn-logo.ico'),  # Icone do EXE
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='DataPyn',
)
