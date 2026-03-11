"""
Package Manager Service - package management via uv

Responsibilities:
- List installed packages
- Search packages on PyPI
- Install/uninstall packages
- Check versions
- Manage virtual environment for package isolation
"""

import os
import subprocess
import sys
import shutil
import json
import logging
import urllib.request
import urllib.error
import urllib.parse
from pathlib import Path
from typing import List, Optional, Dict, Any, Tuple
from dataclasses import dataclass, field

from PyQt6.QtCore import QSettings

logger = logging.getLogger(__name__)

# CREATE_NO_WINDOW exists only on Windows
# On Linux uses 0 (no special flags)
CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def _get_project_root() -> Path:
    """Return the project root directory (where pyproject.toml lives)."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    current = Path(__file__).resolve().parent
    for _ in range(10):
        if (current / "pyproject.toml").exists():
            return current
        parent = current.parent
        if parent == current:
            break
        current = parent
    return Path.cwd()


def _get_appdata_venv_dir() -> Path:
    """Return venv directory inside user app data (for frozen/EXE mode).

    Windows: %APPDATA%/datapyn/venv
    macOS:   ~/Library/Application Support/datapyn/venv
    Linux:   $XDG_DATA_HOME/datapyn/venv  (default ~/.local/share/datapyn/venv)
    """
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    return base / "datapyn" / "venv"


def _venv_python_path(venv_path: Path) -> Path:
    """Return the Python executable path inside a venv."""
    if sys.platform == "win32":
        return venv_path / "Scripts" / "python.exe"
    return venv_path / "bin" / "python"


def _find_or_create_venv() -> Tuple[Path, str]:
    """Locate or create the virtual environment for package operations.

    Strategy:
    1. If the current process is already running inside a venv
       (sys.prefix != sys.base_prefix), use that venv.
    2. In dev mode, look for .venv at the project root.
    3. In frozen mode (PyInstaller EXE), use %APPDATA%/datapyn/venv.
    4. If the venv does not exist, create it automatically.

    Returns:
        Tuple of (venv_root_path, venv_python_executable_path).
    """
    is_frozen = getattr(sys, "frozen", False)

    # 1. Already running inside a venv (dev mode)
    if not is_frozen and sys.prefix != sys.base_prefix:
        venv_path = Path(sys.prefix)
        venv_python = _venv_python_path(venv_path)
        if venv_python.exists():
            logger.info(f"Using active venv: {venv_path}")
            return venv_path, str(venv_python)

    # 2/3. Determine target venv directory
    if is_frozen:
        venv_path = _get_appdata_venv_dir()
    else:
        venv_path = _get_project_root() / ".venv"

    venv_python = _venv_python_path(venv_path)

    if venv_python.exists():
        logger.info(f"Using existing venv: {venv_path}")
        return venv_path, str(venv_python)

    # 4. Create venv automatically
    logger.info(f"Venv not found at {venv_path}, creating automatically...")
    venv_path.parent.mkdir(parents=True, exist_ok=True)

    uv = shutil.which("uv")
    try:
        if uv:
            subprocess.run(
                [uv, "venv", str(venv_path)],
                capture_output=True, text=True, timeout=60,
                creationflags=CREATE_NO_WINDOW,
            )
        else:
            base_python = shutil.which("python3") or shutil.which("python") or "python"
            subprocess.run(
                [base_python, "-m", "venv", str(venv_path)],
                capture_output=True, text=True, timeout=60,
                creationflags=CREATE_NO_WINDOW,
            )
    except Exception as e:
        logger.error(f"Failed to create venv: {e}")

    venv_python = _venv_python_path(venv_path)
    if venv_python.exists():
        logger.info(f"Venv created successfully: {venv_path}")
    else:
        logger.warning(f"Venv python not found after creation attempt: {venv_python}")

    return venv_path, str(venv_python)


def _find_uv_executable() -> Optional[str]:
    """Return uv executable path if available."""
    uv = shutil.which("uv")
    if uv:
        return uv
    return None



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
        self._venv_path, self._venv_python = _find_or_create_venv()
        self._ensure_site_packages_in_path()

    @property
    def venv_path(self) -> str:
        """Return the virtual environment root path as string."""
        return str(self._venv_path)

    def _get_site_packages_path(self) -> Optional[Path]:
        """Return the site-packages directory inside the venv."""
        # Windows layout: Lib/site-packages
        candidate = self._venv_path / "Lib" / "site-packages"
        if candidate.exists():
            return candidate
        # Linux/macOS layout: lib/pythonX.Y/site-packages
        for candidate in self._venv_path.glob("lib/python*/site-packages"):
            if candidate.exists():
                return candidate
        return None

    def _ensure_site_packages_in_path(self):
        """Add the venv site-packages to sys.path so that packages installed
        via the Package Manager are importable by PythonWorker (exec/eval).

        In dev mode the venv is already active and sys.path is correct.
        In frozen mode (PyInstaller EXE) the venv lives in AppData and
        its site-packages is NOT on sys.path by default.
        """
        sp = self._get_site_packages_path()
        if sp is None:
            return
        sp_str = str(sp)
        if sp_str not in sys.path:
            sys.path.insert(0, sp_str)
            logger.info(f"Added venv site-packages to sys.path: {sp_str}")
        # On Windows, native extensions (.pyd) may need DLL search paths.
        # Add the Scripts directory so that DLLs bundled with packages are found.
        if sys.platform == "win32" and hasattr(os, "add_dll_directory"):
            scripts_dir = self._venv_path / "Scripts"
            if scripts_dir.exists():
                try:
                    os.add_dll_directory(str(scripts_dir))
                except OSError:
                    pass

    def _refresh_import_system(self):
        """Refresh Python import machinery after installing/uninstalling a package.

        Clears the import finder caches so that newly installed packages
        are discoverable and uninstalled packages stop being importable.
        """
        import importlib
        importlib.invalidate_caches()
        # Ensure site-packages is still on sys.path
        self._ensure_site_packages_in_path()

    def _build_env(self) -> Dict[str, str]:
        """Build environment dict with VIRTUAL_ENV set and PATH adjusted."""
        env = os.environ.copy()
        env["VIRTUAL_ENV"] = str(self._venv_path)
        if sys.platform == "win32":
            scripts_dir = str(self._venv_path / "Scripts")
        else:
            scripts_dir = str(self._venv_path / "bin")
        env["PATH"] = scripts_dir + os.pathsep + env.get("PATH", "")
        # Remove PYTHONHOME if set (can interfere with venv)
        env.pop("PYTHONHOME", None)
        return env

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
        Always targets the managed virtual environment via --python flag.
        Appends --extra-index-url for each configured custom source.
        """
        if self._uv_executable:
            cmd = [self._uv_executable, "pip"] + pip_args + ["--python", self._venv_python]
        else:
            cmd = [self._venv_python, "-m", "pip"] + pip_args + ["--disable-pip-version-check"]

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
                env=self._build_env(),
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
        Uses HTTP Basic Auth header for authenticated sources.
        Returns PackageInfo with basic data if found in any source.
        """
        import base64
        import re

        sources = self.get_sources()
        if not sources:
            return []

        normalized = query.lower().replace("_", "-").replace(".", "-")

        for source in sources:
            source_url = source.get("url", "")
            if not source_url:
                continue
            try:
                # PEP 503: /{package}/ lists available files
                base = source_url.rstrip("/")
                probe_url = f"{base}/{normalized}/"
                req = urllib.request.Request(probe_url, headers={"Accept": "text/html"})

                # Add Basic Auth header if credentials available
                username = source.get("username", "")
                password = source.get("password", "")
                if username and password:
                    credentials = base64.b64encode(f"{username}:{password}".encode()).decode()
                    req.add_header("Authorization", f"Basic {credentials}")

                with urllib.request.urlopen(req, timeout=10) as response:
                    body = response.read().decode("utf-8", errors="replace")

                # PEP 503: page must contain <a href> links to actual files
                # (.tar.gz, .whl, .zip, .egg). URLs may have #hash fragments.
                file_links = re.findall(
                    r'<a\s+href=["\'][^"\']*\.(?:tar\.gz|whl|zip|egg)(?:[#"\'\s>])',
                    body,
                    re.IGNORECASE,
                )
                if not file_links:
                    logger.debug(f"Package '{query}' page on {source_url} has no download links")
                    continue

                # Extract version from filenames (e.g. mag_autatu-1.2.3.tar.gz)
                # PEP 503: dashes, underscores and dots are interchangeable in names
                name_re = re.escape(normalized).replace(r"\-", "[-_.]")
                version_pattern = re.compile(
                    rf"{name_re}[_-](\d+(?:\.\d+)*)(?:[_.-])",
                    re.IGNORECASE,
                )
                versions = version_pattern.findall(body)
                latest = max(versions, key=lambda v: [int(x) for x in v.split(".")], default="") if versions else ""

                return [
                    PackageInfo(
                        name=query,
                        version=installed.version if installed else "",
                        latest_version=latest,
                        installed=bool(installed),
                        summary=f"Found on {source_url}",
                        author="",
                    )
                ]
            except urllib.error.HTTPError as e:
                if e.code == 404:
                    logger.debug(f"Package '{query}' not found on source {source_url}")
                    continue
                logger.warning(f"Error probing source {source_url}: {e}")
                continue
            except Exception as e:
                logger.warning(f"Error probing source {source_url}: {e}")
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
                env=self._build_env(),
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
                env=self._build_env(),
            )

            if result.returncode == 0:
                self._refresh_import_system()
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
            "pyqt6-webengine",
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
                env=self._build_env(),
            )

            if result.returncode == 0:
                self._refresh_import_system()
                return PackageOperationResult(
                    success=True,
                    package_name=package_name,
                    operation="uninstall",
                    message=f"Package '{package_name}' removed successfully.",
                )

            # Packages installed via `uv sync` may lack RECORD files.
            # When uv fails with a RECORD error, remove the package
            # directories manually from site-packages as a fallback.
            stderr = result.stderr or ""
            if "RECORD" in stderr and self._uv_executable:
                logger.warning(
                    f"uv uninstall failed due to missing RECORD for '{package_name}', "
                    "attempting manual removal from site-packages"
                )
                manual_result = self._manual_uninstall(package_name)
                if manual_result:
                    return manual_result

            return PackageOperationResult(
                success=False,
                package_name=package_name,
                operation="uninstall",
                error=stderr or "Unknown error during uninstall.",
            )
        except Exception as e:
            return PackageOperationResult(success=False, package_name=package_name, operation="uninstall", error=str(e))

    def _manual_uninstall(self, package_name: str) -> Optional[PackageOperationResult]:
        """Manually remove a package from site-packages when RECORD is missing.

        Packages installed via `uv sync` (from pyproject.toml) do not always
        write a RECORD file, which causes `uv pip uninstall` to fail. This
        method finds and removes the package's directories directly.

        Returns a successful PackageOperationResult, or None if removal failed.
        """
        import re
        import shutil as _shutil

        site_packages = self._venv_path / "Lib" / "site-packages"
        if not site_packages.exists():
            # Linux/macOS layout
            for candidate in self._venv_path.glob("lib/python*/site-packages"):
                site_packages = candidate
                break

        if not site_packages.exists():
            logger.error(f"site-packages not found in venv: {self._venv_path}")
            return None

        # Normalize: PEP 503 - dashes, underscores and dots are equivalent
        # First replace separators with a single canonical form, then escape, then
        # replace the canonical form with a character class that matches all variants.
        canonical = re.sub(r"[-_.]+", "_", package_name.lower())
        escaped = re.escape(canonical)
        normalized = escaped.replace("_", "[-_.]+")
        pattern = re.compile(rf"^{normalized}(-\d|\.dist-info|\.data)", re.IGNORECASE)

        # Also match the top-level package directory (e.g. "fastexcel/")
        simple_name = canonical

        removed = []
        for item in site_packages.iterdir():
            name_lower = item.name.lower()
            if pattern.match(name_lower) or name_lower == simple_name:
                try:
                    if item.is_dir():
                        _shutil.rmtree(item)
                    else:
                        item.unlink()
                    removed.append(item.name)
                    logger.info(f"Manually removed: {item}")
                except Exception as e:
                    logger.error(f"Failed to remove {item}: {e}")

        if removed:
            self._refresh_import_system()
            return PackageOperationResult(
                success=True,
                package_name=package_name,
                operation="uninstall",
                message=f"Package '{package_name}' removed successfully.",
            )

        logger.warning(f"No directories found for '{package_name}' in {site_packages}")
        return None

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
                env=self._build_env(),
            )

            if result.returncode == 0:
                self._refresh_import_system()
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
                env=self._build_env(),
            )
            return result.returncode == 0
        except Exception:
            return False
