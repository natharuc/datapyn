# -*- mode: python ; coding: utf-8 -*-
"""Headless onefile runtime; no Qt frontend or GUI Matplotlib backend."""
from pathlib import Path
import shutil

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

ROOT = Path(SPEC).resolve().parents[2]

hiddenimports = [
    "datapyn_runtime",
    "datapyn_runtime.__main__",
    "src.database.database_connector",
    "src.database.query_stream_exporter",
    "src.utils.sql_parameter_service",
    "pandas",
    "numpy",
    "polars",
    "pyarrow",
    "pyarrow.parquet",
    "pyarrow.csv",
    "pyodbc",
    "pymssql",
    "psycopg2",
    "pymysql",
    "mysql.connector",
    "databricks.sql",
    "databricks.sqlalchemy",
    "azure.identity",
    "openpyxl",
    "fastexcel",
    "matplotlib.pyplot",
    "plotly.express",
    "plotly.graph_objects",
    "sqlparse",
    "sqlglot",
    "jedi",
    "jinja2",
    "cryptography",
    "keyring",
    "src.services.pynia.acp.client_transport",
    "src.services.pynia.acp.activity",
    "src.services.pynia.acp.mcp_helpers",
    "src.services.pynia.acp.permission",
    "src.services.pynia.acp.session_config",
    "src.services.pynia.acp.turn_context",
    "src.services.pynia.tools.definitions",
    "src.services.entity_metadata_service",
]
for package in ("datapyn_runtime", "sqlalchemy.dialects", "mysql.connector", "databricks.sqlalchemy", "keyring.backends", "plotly.graph_objs"):
    hiddenimports += collect_submodules(package)

datas = [(str(path), "src/language") for path in (ROOT / "source/src/language").glob("*.json")]
for executable in ("uv", "ruff"):
    tool_path = shutil.which(executable)
    if tool_path:
        datas.append((tool_path, "."))
    else:
        raise RuntimeError(f"{executable} is required to build the extensible desktop runtime")
for package in ("pandas", "polars", "pyarrow", "matplotlib", "plotly", "jedi", "parso", "databricks.sql", "azure.identity"):
    datas += collect_data_files(package)

analysis = Analysis(
    [str(ROOT / "scripts/tauri/runtime_entry.py")],
    pathex=[str(ROOT / "source")],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={"matplotlib": {"backends": ["Agg"]}},
    runtime_hooks=[],
    excludes=["PyQt6", "PyQt5", "PySide6", "PySide2", "qtawesome", "qt_material", "tkinter", "IPython", "pytest", "pandas.tests", "numpy.tests", "pyarrow.tests"],
    noarchive=False,
)
archive = PYZ(analysis.pure)
executable = EXE(
    archive,
    analysis.scripts,
    analysis.binaries,
    analysis.datas,
    [],
    name="datapyn-runtime",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
)
