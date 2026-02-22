# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec file para DataPyn
Execute: pyinstaller datapyn.spec
"""

import os
import sys
from PyInstaller.utils.hooks import collect_data_files, collect_submodules, collect_all

# Diretorio raiz do projeto (um nivel acima de scripts/)
ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(SPEC), '..'))

block_cipher = None

# Coletar pacote mariadb completo (inclui .pyd nativo + constants)
# Filtramos apenas binarios e dados essenciais, excluindo docs e testes
_mariadb_datas, _mariadb_binaries, _mariadb_hiddenimports = collect_all('mariadb')
# Filtrar dados do mariadb para excluir documentacao e arquivos desnecessarios
_mariadb_datas = [(src, dst) for src, dst in _mariadb_datas 
                  if not any(x in src.lower() for x in ['.md', '.txt', '.rst', 'test', 'doc', 'license', 'readme'])]

# Coletar todos os submódulos necessários
hiddenimports = [
    'PyQt6',
    'PyQt6.QtCore',
    'PyQt6.QtGui', 
    'PyQt6.QtWidgets',
    'PyQt6.QtSvg',
    'PyQt6.Qsci',
    'pandas',
    'numpy',
    'pyodbc',
    'sqlalchemy',
    'json',
    'yaml',
    # Database drivers
    'psycopg2',
    'pymysql',
] + _mariadb_hiddenimports

# Dados adicionais (assets)
# Destino 'src/assets' para que _MEIPASS atua como equivalente do diretorio source/
# Filtramos apenas arquivos necessarios (excluindo .md, .txt, .rst, etc)
import glob
assets_files = []
for ext in ['*.ico', '*.svg', '*.png', '*.jpg']:
    assets_files.extend(glob.glob(os.path.join(ROOT_DIR, 'source', 'src', 'assets', '**', ext), recursive=True))

assets_datas = [(f, os.path.join('src', 'assets', os.path.relpath(os.path.dirname(f), os.path.join(ROOT_DIR, 'source', 'src', 'assets')))) 
                for f in assets_files]

# Language files (i18n JSON translations)
language_dir = os.path.join(ROOT_DIR, 'source', 'src', 'language')
language_datas = [(f, os.path.join('src', 'language'))
                  for f in glob.glob(os.path.join(language_dir, '*.json'))]

# Monaco Editor HTML templates
monaco_dir = os.path.join(ROOT_DIR, 'source', 'src', 'editors', 'monaco')
monaco_datas = [(f, os.path.join('src', 'editors', 'monaco'))
                for f in glob.glob(os.path.join(monaco_dir, '*.html'))]

# Copilot chat templates (in ui/components directory)
chat_templates_dir = os.path.join(ROOT_DIR, 'source', 'src', 'ui', 'components')
chat_datas = [(f, os.path.join('src', 'ui', 'components'))
              for f in glob.glob(os.path.join(chat_templates_dir, 'chat_template*.html'))]

# Copilot SDK CLI binary (copilot.exe for Windows)
# The SDK requires the CLI to be available at runtime
import site
_site_packages = None
for sp in site.getsitepackages():
    if os.path.isdir(os.path.join(sp, 'copilot', 'bin')):
        _site_packages = sp
        break
if not _site_packages:
    # Fallback to venv site-packages
    _site_packages = os.path.join(ROOT_DIR, '.venv', 'Lib', 'site-packages')
_copilot_bin = os.path.join(_site_packages, 'copilot', 'bin')
copilot_cli_datas = []
if os.path.isdir(_copilot_bin):
    for f in glob.glob(os.path.join(_copilot_bin, '*')):
        copilot_cli_datas.append((f, os.path.join('copilot', 'bin')))

datas = assets_datas + language_datas + monaco_datas + chat_datas + copilot_cli_datas + [
    # pyproject.toml para leitura de versao
    (os.path.join(ROOT_DIR, 'pyproject.toml'), '.'),
] + _mariadb_datas

a = Analysis(
    [os.path.join(ROOT_DIR, 'source', 'main.py')],
    pathex=[ROOT_DIR],
    binaries=[] + _mariadb_binaries,
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
    strip=False,  # strip is a Unix tool, not available on Windows
    upx=True,
    upx_exclude=[
        # Exclude files that don't compress well or may cause issues
        'vcruntime*.dll',
        'python*.dll',
        'Qt6Core.dll',
        'Qt6Gui.dll',
        'Qt6Widgets.dll',
    ],
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
    strip=False,  # strip is a Unix tool, not available on Windows
    upx=True,
    upx_exclude=[
        # Exclude files that don't compress well or may cause issues
        'vcruntime*.dll',
        'python*.dll',
        'Qt6Core.dll',
        'Qt6Gui.dll',
        'Qt6Widgets.dll',
    ],
    name='DataPyn',
)
