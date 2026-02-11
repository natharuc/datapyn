"""
Setup script para gerar instalador MSI do DataPyn usando cx_Freeze
"""
import sys
from pathlib import Path
from cx_Freeze import setup, Executable

# Diretorio raiz do projeto
ROOT_DIR = Path(__file__).parent.parent

# Opcoes de build
build_exe_options = {
    "packages": [
        "PyQt6",
        "PyQt6.QtCore",
        "PyQt6.QtGui",
        "PyQt6.QtWidgets",
        "PyQt6.Qsci",
        "pandas",
        "numpy",
        "sqlalchemy",
        "psycopg2",
        "pymysql",
        "mariadb",
        "pyodbc",
        "matplotlib",
        "openpyxl",
        "polars",
        "pyarrow",
        "cryptography",
        "keyring",
    ],
    "excludes": [
        "tkinter",
        "unittest",
        "email",
        "http",
        "xml",
        "pydoc",
    ],
    "include_files": [
        (str(ROOT_DIR / "source" / "src" / "assets"), "lib/src/assets"),
        (str(ROOT_DIR / "source" / "src" / "editors" / "monaco"), "lib/monaco"),
    ],
    "optimize": 2,
}

# Opcoes do instalador MSI
bdist_msi_options = {
    "upgrade_code": "{550CD338-127B-4152-A131-C0E375667D77}",  # GUID unico do DataPyn
    "add_to_path": False,
    "initial_target_dir": r"[ProgramFilesFolder]\DataPyn",
    "install_icon": str(ROOT_DIR / "source" / "src" / "assets" / "datapyn-logo.ico"),
}

# Definicao do executavel
executables = [
    Executable(
        script=str(ROOT_DIR / "source" / "main.py"),
        base="Win32GUI",  # GUI application (no console)
        target_name="DataPyn.exe",
        icon=str(ROOT_DIR / "source" / "src" / "assets" / "datapyn-logo.ico"),
        shortcut_name="DataPyn",
        shortcut_dir="ProgramMenuFolder",
    )
]

setup(
    name="DataPyn",
    version="1.0.0",
    description="IDE moderna para consultas SQL com Python integrado",
    author="DataPyn Team",
    options={
        "build_exe": build_exe_options,
        "bdist_msi": bdist_msi_options,
    },
    executables=executables,
)
