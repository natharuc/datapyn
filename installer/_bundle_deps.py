"""
Stdlib imports for windows_installer.py (loaded via exec_module from PyInstaller datas).

PyInstaller only traces the entry script graph; modules shipped as data files must
pull their dependencies explicitly.
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional
from urllib.request import Request, urlopen

if sys.platform == "win32":
    import winreg  # noqa: F401

__all__ = [
    "json",
    "logging",
    "os",
    "re",
    "shutil",
    "subprocess",
    "tempfile",
    "zipfile",
    "dataclass",
    "Path",
    "Callable",
    "Optional",
    "Request",
    "urlopen",
]
