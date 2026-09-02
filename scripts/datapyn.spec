# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec file para DataPyn
Execute: pyinstaller scripts/datapyn.spec
"""

import glob
import os
import site
import sys
import sysconfig

from PyInstaller.utils.hooks import collect_all, collect_data_files, collect_submodules

# Diretorio raiz do projeto (um nivel acima de scripts/)
ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(SPEC), '..'))

block_cipher = None


def _collect_optional(module_name):
    """collect_all that returns empty lists when the package is not installed."""
    try:
        return collect_all(module_name)
    except Exception:
        return [], [], []


# mariadb C connector is optional (MariaDB connections use PyMySQL).
_mariadb_datas, _mariadb_binaries, _mariadb_hiddenimports = [], [], []
try:
    import mariadb  # noqa: F401
except ImportError:
    pass
else:
    _mariadb_datas, _mariadb_binaries, _mariadb_hiddenimports = collect_all('mariadb')
    _mariadb_datas = [
        (src, dst)
        for src, dst in _mariadb_datas
        if not any(x in src.lower() for x in ['.md', '.txt', '.rst', 'test', 'doc', 'license', 'readme'])
    ]

# Qt WebEngine (Monaco, Pynia chat) — plugins, locales, and resources.
_we_datas, _we_binaries, _we_hiddenimports = [], [], []
for _we_mod in ('PyQt6.QtWebEngineCore', 'PyQt6.QtWebEngineWidgets', 'PyQt6.QtWebEngine'):
    _d, _b, _h = _collect_optional(_we_mod)
    _we_datas += _d
    _we_binaries += _b
    _we_hiddenimports += _h

hiddenimports = [
    'PyQt6',
    'PyQt6.QtCore',
    'PyQt6.QtGui',
    'PyQt6.QtWidgets',
    'PyQt6.QtSvg',
    'PyQt6.QtWebEngineCore',
    'PyQt6.QtWebEngineWidgets',
    'PyQt6.QtWebEngine',
    'pandas',
    'numpy',
    'pyodbc',
    'sqlalchemy',
    'json',
    'yaml',
    'psycopg2',
    'pymysql',
] + _mariadb_hiddenimports + _we_hiddenimports + collect_submodules('qtawesome')

_qtawesome_datas = collect_data_files('qtawesome')

# Dados adicionais (assets)
# Destino 'src/assets' para que _MEIPASS atua como equivalente do diretorio source/
assets_files = []
for ext in ['*.ico', '*.svg', '*.png', '*.jpg', '*.icns']:
    assets_files.extend(
        glob.glob(os.path.join(ROOT_DIR, 'source', 'src', 'assets', '**', ext), recursive=True)
    )

assets_datas = [
    (
        f,
        os.path.join(
            'src',
            'assets',
            os.path.relpath(os.path.dirname(f), os.path.join(ROOT_DIR, 'source', 'src', 'assets')),
        ),
    )
    for f in assets_files
]

language_dir = os.path.join(ROOT_DIR, 'source', 'src', 'language')
language_datas = [
    (f, os.path.join('src', 'language')) for f in glob.glob(os.path.join(language_dir, '*.json'))
]

monaco_dir = os.path.join(ROOT_DIR, 'source', 'src', 'editors', 'monaco')
monaco_datas = [
    (f, os.path.join('src', 'editors', 'monaco')) for f in glob.glob(os.path.join(monaco_dir, '*.html'))
]

chat_templates_dir = os.path.join(ROOT_DIR, 'source', 'src', 'ui', 'components')
chat_datas = [
    (f, os.path.join('src', 'ui', 'components'))
    for f in glob.glob(os.path.join(chat_templates_dir, '*chat*.html'))
]

js_assets_dir = os.path.join(ROOT_DIR, 'source', 'src', 'ui', 'assets', 'js')
js_assets_datas = [
    (f, os.path.join('src', 'ui', 'assets', 'js')) for f in glob.glob(os.path.join(js_assets_dir, '*'))
]

css_assets_dir = os.path.join(ROOT_DIR, 'source', 'src', 'ui', 'assets', 'css')
css_assets_datas = [
    (f, os.path.join('src', 'ui', 'assets', 'css')) for f in glob.glob(os.path.join(css_assets_dir, '*'))
]


def _find_copilot_bin():
    candidates = []
    try:
        candidates.extend(site.getsitepackages())
    except Exception:
        pass
    try:
        candidates.append(sysconfig.get_paths()['purelib'])
    except Exception:
        pass
    py_tag = f'python{sys.version_info.major}.{sys.version_info.minor}'
    candidates.append(os.path.join(ROOT_DIR, '.venv', 'Lib', 'site-packages'))
    candidates.append(os.path.join(ROOT_DIR, '.venv', 'lib', py_tag, 'site-packages'))
    for sp in candidates:
        copilot_bin = os.path.join(sp, 'copilot', 'bin')
        if os.path.isdir(copilot_bin):
            return copilot_bin
    return None


copilot_cli_datas = []
_copilot_bin = _find_copilot_bin()
if _copilot_bin:
    for f in glob.glob(os.path.join(_copilot_bin, '*')):
        copilot_cli_datas.append((f, os.path.join('copilot', 'bin')))

_logo_svg = os.path.join(ROOT_DIR, 'source', 'src', 'assets', 'datapyn_logo.svg')
_logo_datas = [(_logo_svg, '.')] if os.path.isfile(_logo_svg) else []

datas = (
    assets_datas
    + language_datas
    + monaco_datas
    + chat_datas
    + js_assets_datas
    + css_assets_datas
    + copilot_cli_datas
    + _qtawesome_datas
    + _logo_datas
    + [
        (os.path.join(ROOT_DIR, 'pyproject.toml'), '.'),
    ]
    + _mariadb_datas
    + _we_datas
)

_icon_icns = os.path.join(ROOT_DIR, 'source', 'src', 'assets', 'datapyn.icns')
_icon_ico = os.path.join(ROOT_DIR, 'source', 'src', 'assets', 'datapyn-logo.ico')
if sys.platform == 'darwin' and os.path.isfile(_icon_icns):
    _app_icon = _icon_icns
elif os.path.isfile(_icon_ico):
    _app_icon = _icon_ico
else:
    _app_icon = None

a = Analysis(
    [os.path.join(ROOT_DIR, 'source', 'main.py')],
    pathex=[ROOT_DIR],
    binaries=[] + _mariadb_binaries + _we_binaries,
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
    upx_exclude=[
        'vcruntime*.dll',
        'python*.dll',
        'Qt6Core.dll',
        'Qt6Gui.dll',
        'Qt6Widgets.dll',
    ],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=_app_icon,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[
        'vcruntime*.dll',
        'python*.dll',
        'Qt6Core.dll',
        'Qt6Gui.dll',
        'Qt6Widgets.dll',
    ],
    name='DataPyn',
)

if sys.platform == 'darwin':
    app = BUNDLE(
        coll,
        name='DataPyn.app',
        icon=_app_icon,
        bundle_identifier='page.datapyn.app',
        info_plist={
            'CFBundleName': 'DataPyn',
            'CFBundleDisplayName': 'DataPyn',
            'CFBundleIdentifier': 'page.datapyn.app',
            'CFBundlePackageType': 'APPL',
            'NSHighResolutionCapable': True,
            'LSMinimumSystemVersion': '13.0',
            'NSPrincipalClass': 'NSApplication',
        },
    )
