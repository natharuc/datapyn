"""Load windows_installer without importing src.services (avoids pandas, PyQt WebEngine, etc.)."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType


def _module_path() -> Path:
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS) / "src" / "services" / "windows_installer.py"
    root = Path(__file__).resolve().parents[1]
    return root / "source" / "src" / "services" / "windows_installer.py"


def load_windows_installer() -> ModuleType:
    path = _module_path()
    if not path.is_file():
        raise FileNotFoundError(f"windows_installer.py not found: {path}")

    spec = importlib.util.spec_from_file_location("datapyn_windows_installer", path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load installer module from {path}")

    module = importlib.util.module_from_spec(spec)
    sys.modules["datapyn_windows_installer"] = module
    spec.loader.exec_module(module)
    return module
