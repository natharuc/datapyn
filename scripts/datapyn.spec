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

datas = assets_datas + [
    # Monaco Editor - HTML + VS loader/workers
    (os.path.join(ROOT_DIR, 'source', 'src', 'editors', 'monaco'), os.path.join('monaco')),
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
    excludes=[
        # Test frameworks and dev tools
        'pytest',
        'pytest_cov',
        'pytest_qt',
        'pytest_subtests',
        'pytest_env',
        'pytest_timeout',
        '_pytest',
        'py.test',
        'unittest',
        'unittest.mock',
        'doctest',
        # Build tools
        'setuptools',
        'pip',
        'wheel',
        # NOT 'distutils' - PyInstaller has a pre_safe_import_module hook
        # that aliases distutils -> setuptools._distutils on Python 3.12+.
        # Excluding it causes ValueError in the alias_module step.
        # Documentation
        'sphinx',
        'pydoc',
        # Development
        'IPython',
        'jupyter',
        'notebook',
        # Unused standard library modules
        'tkinter',
        'turtle',
        'curses',
        'pydoc_data',
        'test',
        'lib2to3',
        'xmlrpc',
        # Unused data science tools (not used in the app)
        'scipy',
        'sklearn',
        'statsmodels',
        'seaborn',
        # Additional unused modules
        'email',  # Se não usado
        'ftplib',
        'telnetlib',
        'poplib',
        'imaplib',
        'smtplib',
        'asynchat',
        'asyncore',
        # Compiler and internals
        'compiler',
        'pdb',
        'bdb',
        'cProfile',
        'profile',
        'pstats',
        'timeit',
        # Unused encodings (keep utf-8, latin1, ascii)
        'encodings.cp037',
        'encodings.cp424',
        'encodings.cp437',
        'encodings.cp500',
        'encodings.cp720',
        'encodings.cp737',
        'encodings.cp775',
        'encodings.cp850',
        'encodings.cp852',
        'encodings.cp855',
        'encodings.cp856',
        'encodings.cp857',
        'encodings.cp858',
        'encodings.cp860',
        'encodings.cp861',
        'encodings.cp862',
        'encodings.cp863',
        'encodings.cp864',
        'encodings.cp865',
        'encodings.cp866',
        'encodings.cp869',
        'encodings.cp874',
        'encodings.cp875',
        'encodings.cp932',
        'encodings.cp949',
        'encodings.cp950',
        'encodings.cp1006',
        'encodings.cp1026',
        'encodings.cp1140',
        'encodings.cp1250',
        'encodings.cp1251',
        'encodings.cp1252',
        'encodings.cp1253',
        'encodings.cp1254',
        'encodings.cp1255',
        'encodings.cp1256',
        'encodings.cp1257',
        'encodings.cp1258',
    ],
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
    strip=True,  # Strip binaries to reduce size
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
    strip=True,  # Strip binaries in collection as well
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
