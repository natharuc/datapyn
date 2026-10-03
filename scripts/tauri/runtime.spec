# -*- mode: python ; coding: utf-8 -*-
"""Headless onefile runtime; no Qt frontend or GUI Matplotlib backend."""
from pathlib import Path

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
]
for package in ("datapyn_runtime", "sqlalchemy.dialects", "mysql.connector", "databricks.sqlalchemy", "keyring.backends"):
    hiddenimports += collect_submodules(package)

datas = [(str(path), "src/language") for path in (ROOT / "source/src/language").glob("*.json")]
for package in ("pandas", "polars", "pyarrow", "matplotlib", "plotly", "databricks.sql", "azure.identity"):
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
