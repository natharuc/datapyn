"""
Package Manager Service - pip package management

Responsibilities:
- List installed packages
- Search packages on PyPI
- Install/uninstall packages
- Check versions
"""

import subprocess
import sys
import shutil
import json
import logging
from typing import List, Optional, Dict, Any
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# CREATE_NO_WINDOW exists only on Windows
# On Linux uses 0 (no special flags)
CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def _find_python_executable() -> str:
    """
    Return Python interpreter path.

    In frozen mode (PyInstaller), sys.executable points to packaged EXE,
    not to Python. In this case, search for python in system PATH.
    """
    if getattr(sys, "frozen", False):
        python = shutil.which("python") or shutil.which("python3")
        if python:
            return python
        return "python"
    return sys.executable


@dataclass
class PackageInfo:
    """Package information"""

    name: str
    version: str = ""
    summary: str = ""
    author: str = ""
    latest_version: str = ""
    installed: bool = False

    @property
    def has_update(self) -> bool:
        """Check if update is available"""
        if not self.latest_version or not self.version:
            return False
        return self.version != self.latest_version


@dataclass
class PackageOperationResult:
    """Package operation result"""

    success: bool
    package_name: str
    operation: str  # 'install', 'uninstall', 'update'
    message: str = ""
    error: str = ""


class PackageManagerService:
    """
    Service for Python package management via pip.

    Allows listing, searching, installing and uninstalling packages
    using pip from current Python interpreter.
    """

    def __init__(self):
        self._python_executable = _find_python_executable()

    def list_installed(self) -> List[PackageInfo]:
        """List all installed packages"""
        try:
            result = subprocess.run(
                [self._python_executable, "-m", "pip", "list", "--format=json", "--disable-pip-version-check"],
                capture_output=True,
                text=True,
                timeout=30,
                creationflags=CREATE_NO_WINDOW,
            )
            if result.returncode != 0:
                logger.error(f"Error listing packages: {result.stderr}")
                return []

            packages = json.loads(result.stdout)
            return [PackageInfo(name=pkg["name"], version=pkg.get("version", ""), installed=True) for pkg in packages]
        except Exception as e:
            logger.error(f"Error listing packages: {e}")
            return []

    def search_pypi(self, query: str) -> List[PackageInfo]:
        """
        Search packages on PyPI via pip index.

        Since pip search was disabled, we use pip index versions
        to check if a package exists, and complement with
        basic information.
        """
        if not query or len(query) < 2:
            return []

        try:
            # Try to get package info directly
            result = subprocess.run(
                [
                    self._python_executable,
                    "-m",
                    "pip",
                    "install",
                    f"{query}==randominvalidversion",
                    "--disable-pip-version-check",
                    "--dry-run",
                ],
                capture_output=True,
                text=True,
                timeout=30,
                creationflags=CREATE_NO_WINDOW,
            )
            # pip will list available versions in error
            stderr = result.stderr

            # Check if package exists
            if "No matching distribution" in stderr and "randominvalidversion" not in stderr:
                return []

            # Extract versions from error output
            versions = []
            import re

            # Pattern: "from versions: 1.0.0, 1.1.0, ..."
            match = re.search(r"from versions?:\s*(.+?)(?:\)|$)", stderr)
            if match:
                versions = [v.strip() for v in match.group(1).split(",")]

            latest = versions[-1] if versions else ""

            # Check if installed
            installed_packages = {p.name.lower(): p for p in self.list_installed()}
            installed = installed_packages.get(query.lower())

            return [
                PackageInfo(
                    name=query,
                    version=installed.version if installed else "",
                    latest_version=latest,
                    installed=bool(installed),
                    summary=f"Available versions: {', '.join(versions[-5:])}" if versions else "",
                )
            ]

        except Exception as e:
            logger.error(f"Error in PyPI search: {e}")
            return []

    def get_package_info(self, package_name: str) -> Optional[PackageInfo]:
        """Get detailed information of an installed package"""
        try:
            result = subprocess.run(
                [self._python_executable, "-m", "pip", "show", package_name, "--disable-pip-version-check"],
                capture_output=True,
                text=True,
                timeout=15,
                creationflags=CREATE_NO_WINDOW,
            )
            if result.returncode != 0:
                return None

            info = {}
            for line in result.stdout.splitlines():
                if ": " in line:
                    key, value = line.split(": ", 1)
                    info[key.strip()] = value.strip()

            return PackageInfo(
                name=info.get("Name", package_name),
                version=info.get("Version", ""),
                summary=info.get("Summary", ""),
                author=info.get("Author", ""),
                installed=True,
            )
        except Exception as e:
            logger.error(f"Error getting package info: {e}")
            return None

    def install_package(self, package_name: str, version: str = "") -> PackageOperationResult:
        """Install a package via pip"""
        target = f"{package_name}=={version}" if version else package_name
        try:
            result = subprocess.run(
                [self._python_executable, "-m", "pip", "install", target, "--disable-pip-version-check"],
                capture_output=True,
                text=True,
                timeout=120,
                creationflags=CREATE_NO_WINDOW,
            )

            if result.returncode == 0:
                return PackageOperationResult(
                    success=True,
                    package_name=package_name,
                    operation="install",
                    message=f"Package '{package_name}' installed successfully.",
                )
            else:
                return PackageOperationResult(
                    success=False,
                    package_name=package_name,
                    operation="install",
                    error=result.stderr or "Unknown error in installation.",
                )
        except subprocess.TimeoutExpired:
            return PackageOperationResult(
                success=False,
                package_name=package_name,
                operation="install",
                error="Timeout: installation took more than 2 minutes.",
            )
        except Exception as e:
            return PackageOperationResult(success=False, package_name=package_name, operation="install", error=str(e))

    def uninstall_package(self, package_name: str) -> PackageOperationResult:
        """Uninstall a package via pip"""
        # Protect essential packages
        protected = {
            "pip",
            "setuptools",
            "wheel",
            "pyqt6",
            "pyqt6-qt6",
            "pyqt6-sip",
            "qscintilla",
            "pyqt6-qscintilla",
        }
        if package_name.lower() in protected:
            return PackageOperationResult(
                success=False,
                package_name=package_name,
                operation="uninstall",
                error=f"Package '{package_name}' is protected and cannot be removed.",
            )

        try:
            result = subprocess.run(
                [self._python_executable, "-m", "pip", "uninstall", package_name, "-y", "--disable-pip-version-check"],
                capture_output=True,
                text=True,
                timeout=60,
                creationflags=CREATE_NO_WINDOW,
            )

            if result.returncode == 0:
                return PackageOperationResult(
                    success=True,
                    package_name=package_name,
                    operation="uninstall",
                    message=f"Package '{package_name}' removed successfully.",
                )
            else:
                return PackageOperationResult(
                    success=False,
                    package_name=package_name,
                    operation="uninstall",
                    error=result.stderr or "Unknown error during uninstall.",
                )
        except Exception as e:
            return PackageOperationResult(success=False, package_name=package_name, operation="uninstall", error=str(e))

    def update_package(self, package_name: str) -> PackageOperationResult:
        """Update a package to most recent version"""
        try:
            result = subprocess.run(
                [
                    self._python_executable,
                    "-m",
                    "pip",
                    "install",
                    "--upgrade",
                    package_name,
                    "--disable-pip-version-check",
                ],
                capture_output=True,
                text=True,
                timeout=120,
                creationflags=CREATE_NO_WINDOW,
            )

            if result.returncode == 0:
                return PackageOperationResult(
                    success=True,
                    package_name=package_name,
                    operation="update",
                    message=f"Package '{package_name}' updated successfully.",
                )
            else:
                return PackageOperationResult(
                    success=False,
                    package_name=package_name,
                    operation="update",
                    error=result.stderr or "Unknown error during update.",
                )
        except Exception as e:
            return PackageOperationResult(success=False, package_name=package_name, operation="update", error=str(e))

    def check_package_exists(self, package_name: str) -> bool:
        """Quickly check if a package is installed"""
        try:
            result = subprocess.run(
                [self._python_executable, "-m", "pip", "show", package_name, "--disable-pip-version-check"],
                capture_output=True,
                text=True,
                timeout=10,
                creationflags=CREATE_NO_WINDOW,
            )
            return result.returncode == 0
        except Exception:
            return False
