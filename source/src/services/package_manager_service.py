"""
Package Manager Service - package management via uv

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
import urllib.request
import urllib.error
import urllib.parse
from typing import List, Optional, Dict, Any
from dataclasses import dataclass, field

from PyQt6.QtCore import QSettings

logger = logging.getLogger(__name__)

# CREATE_NO_WINDOW exists only on Windows
# On Linux uses 0 (no special flags)
CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def _find_uv_executable() -> Optional[str]:
    """
    Return uv executable path if available.
    """
    uv = shutil.which("uv")
    if uv:
        return uv
    return None


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
    Service for Python package management via uv (with pip fallback).

    Allows listing, searching, installing and uninstalling packages.
    Prefers uv for speed; falls back to pip if uv is not available.
    Supports extra index URLs (custom package sources).
    """

    SETTINGS_KEY = "DataPyn/PackageManager"

    def __init__(self):
        self._uv_executable = _find_uv_executable()
        self._python_executable = _find_python_executable()

    # --- Package sources management ---

    def get_sources(self) -> List[Dict[str, str]]:
        """
        Return list of configured package sources.

        Each source is a dict with keys: url, username, password.
        Migrates from old plain-URL format if needed.
        """
        settings = QSettings("DataPyn", "PackageManager")
        raw = settings.value("sources_v2", None)

        if raw is not None:
            if isinstance(raw, list):
                return raw
            return []

        # Migrate from old format (plain URL list)
        old_urls = settings.value("extra_index_urls", [])
        if isinstance(old_urls, str):
            old_urls = [old_urls] if old_urls else []
        if old_urls:
            sources = [{"url": u.strip(), "username": "", "password": ""} for u in old_urls if u.strip()]
            self.set_sources(sources)
            settings.remove("extra_index_urls")
            return sources
        return []

    def set_sources(self, sources: List[Dict[str, str]]):
        """Persist the list of package sources."""
        settings = QSettings("DataPyn", "PackageManager")
        clean = []
        for s in sources:
            url = s.get("url", "").strip()
            if not url:
                continue
            clean.append({
                "url": url,
                "username": s.get("username", "").strip(),
                "password": s.get("password", ""),
            })
        settings.setValue("sources_v2", clean)

    @staticmethod
    def build_authenticated_url(source: Dict[str, str]) -> str:
        """
        Build a URL with embedded credentials for pip/uv.

        If username and password are provided, inserts them into the URL
        as https://user:pass@host/path.
        """
        url = source.get("url", "")
        username = source.get("username", "")
        password = source.get("password", "")
        if not username or not password:
            return url
        try:
            parsed = urllib.parse.urlparse(url)
            # Encode special characters in credentials
            encoded_user = urllib.parse.quote(username, safe="")
            encoded_pass = urllib.parse.quote(password, safe="")
            netloc = f"{encoded_user}:{encoded_pass}@{parsed.hostname}"
            if parsed.port:
                netloc += f":{parsed.port}"
            authenticated = parsed._replace(netloc=netloc)
            return urllib.parse.urlunparse(authenticated)
        except Exception:
            logger.warning("Failed to build authenticated URL, using plain URL")
            return url

    def _build_cmd(self, pip_args: List[str]) -> List[str]:
        """
        Build command list for pip operations.
        Uses 'uv pip ...' if uv is available, otherwise 'python -m pip ...'.
        Appends --extra-index-url for each configured custom source.
        """
        if self._uv_executable:
            cmd = [self._uv_executable, "pip"] + pip_args
        else:
            cmd = [self._python_executable, "-m", "pip"] + pip_args + ["--disable-pip-version-check"]

        # Append extra index URLs (with embedded credentials if configured)
        for source in self.get_sources():
            auth_url = self.build_authenticated_url(source)
            if auth_url:
                cmd.extend(["--extra-index-url", auth_url])

        return cmd

    def list_installed(self) -> List[PackageInfo]:
        """List all installed packages"""
        try:
            cmd = self._build_cmd(["list", "--format=json"])
            result = subprocess.run(
                cmd,
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
        Search packages on PyPI and configured extra sources.

        First tries the public PyPI JSON API. If not found (404),
        probes each configured extra source via PEP 503 Simple API.
        Returns empty list only when the package is not found in ANY source.
        """
        if not query or len(query) < 2:
            return []

        # Check if installed
        installed_packages = {p.name.lower(): p for p in self.list_installed()}
        installed = installed_packages.get(query.lower())

        # 1) Try PyPI first
        result = self._search_on_pypi(query, installed)
        if result:
            return result

        # 2) Try configured extra sources
        result = self._search_on_extra_sources(query, installed)
        if result:
            return result

        logger.info(f"Package '{query}' not found on PyPI or any configured source")
        return []

    def _search_on_pypi(self, query: str, installed: Optional[PackageInfo] = None) -> List[PackageInfo]:
        """Search package on the public PyPI JSON API."""
        try:
            url = f"https://pypi.org/pypi/{query}/json"
            req = urllib.request.Request(url, headers={"Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=10) as response:
                data = json.loads(response.read().decode("utf-8"))

            info = data.get("info", {})
            latest = info.get("version", "")

            return [
                PackageInfo(
                    name=info.get("name", query),
                    version=installed.version if installed else "",
                    latest_version=latest,
                    installed=bool(installed),
                    summary=info.get("summary", ""),
                    author=info.get("author", "") or info.get("author_email", ""),
                )
            ]
        except urllib.error.HTTPError as e:
            if e.code == 404:
                logger.info(f"Package '{query}' not found on PyPI")
                return []
            logger.error(f"Error in PyPI search: {e}")
            return []
        except Exception as e:
            logger.error(f"Error in PyPI search: {e}")
            return []

    def _search_on_extra_sources(self, query: str, installed: Optional[PackageInfo] = None) -> List[PackageInfo]:
        """
        Probe configured extra sources via PEP 503 Simple API.

        Checks {source_url}/{package}/ for a valid response.
        Returns PackageInfo with basic data if found in any source.
        """
        sources = self.get_sources()
        if not sources:
            return []

        normalized = query.lower().replace("_", "-").replace(".", "-")

        for source in sources:
            auth_url = self.build_authenticated_url(source)
            if not auth_url:
                continue
            try:
                # PEP 503: /{package}/ lists available files
                base = auth_url.rstrip("/")
                probe_url = f"{base}/{normalized}/"
                req = urllib.request.Request(probe_url, headers={"Accept": "text/html"})
                with urllib.request.urlopen(req, timeout=10) as response:
                    body = response.read().decode("utf-8", errors="replace")

                # Extract version from filenames (e.g. mag_autatu-1.2.3.tar.gz)
                import re
                version_pattern = re.compile(
                    rf"{re.escape(normalized)}[_-](\d+(?:\.\d+)*)(?:[_.-])",
                    re.IGNORECASE,
                )
                versions = version_pattern.findall(body)
                latest = max(versions, key=lambda v: [int(x) for x in v.split(".")], default="") if versions else ""

                source_label = source.get("url", "private source")
                return [
                    PackageInfo(
                        name=query,
                        version=installed.version if installed else "",
                        latest_version=latest,
                        installed=bool(installed),
                        summary=f"Found on {source_label}",
                        author="",
                    )
                ]
            except urllib.error.HTTPError as e:
                if e.code == 404:
                    logger.debug(f"Package '{query}' not found on source {source.get('url', '')}")
                    continue
                logger.warning(f"Error probing source {source.get('url', '')}: {e}")
                continue
            except Exception as e:
                logger.warning(f"Error probing source {source.get('url', '')}: {e}")
                continue

        return []

    def get_package_info(self, package_name: str) -> Optional[PackageInfo]:
        """Get detailed information of an installed package"""
        try:
            cmd = self._build_cmd(["show", package_name])
            result = subprocess.run(
                cmd,
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
        """Install a package via uv/pip"""
        target = f"{package_name}=={version}" if version else package_name
        try:
            cmd = self._build_cmd(["install", target])
            result = subprocess.run(
                cmd,
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
        """Uninstall a package via uv/pip"""
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
            cmd = self._build_cmd(["uninstall", package_name])
            # uv pip uninstall does not need -y flag
            if not self._uv_executable:
                cmd.insert(-1, "-y")  # pip needs -y before package name
            result = subprocess.run(
                cmd,
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
            cmd = self._build_cmd(["install", "--upgrade", package_name])
            result = subprocess.run(
                cmd,
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
            cmd = self._build_cmd(["show", package_name])
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=10,
                creationflags=CREATE_NO_WINDOW,
            )
            return result.returncode == 0
        except Exception:
            return False
