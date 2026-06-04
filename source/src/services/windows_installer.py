"""
Windows install/update helpers for DataPyn release ZIP artifacts.

Replaces MSI-based installation: downloads a PyInstaller folder archive from
GitHub Releases, extracts to the user profile, registers uninstall info, and
creates Start Menu / Desktop shortcuts.
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
from datetime import date

if sys.platform == "win32":
    import winreg
else:
    winreg = None  # type: ignore[misc, assignment]
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional
from urllib.request import Request, urlopen

logger = logging.getLogger(__name__)

APP_NAME = "DataPyn"
REGISTRY_KEY = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\DataPyn"
REGISTRY_DELETE_ARG = rf"HKCU\{REGISTRY_KEY}"
ICON_FILE_NAME = "datapyn-logo.ico"
EXE_NAME = "DataPyn.exe"
DEFAULT_INSTALL_DIR = Path(os.environ.get("LOCALAPPDATA", "")) / "DataPyn"
GITHUB_OWNER = "natharuc"
GITHUB_REPO = "datapyn"
ZIP_ASSET_PATTERN = re.compile(r"^DataPyn-[\d.]+(?:-[\w.]+)?-windows\.zip$", re.I)
SETUP_ASSET_PATTERN = re.compile(r"^DataPyn-Setup(?:-[\d.]+)?\.exe$", re.I)
VERSION_FILE = "installed.json"


@dataclass(frozen=True)
class ReleaseAsset:
    name: str
    download_url: str
    size: int = 0


@dataclass(frozen=True)
class GitHubRelease:
    tag_name: str
    version: str
    body: str
    zip_asset: ReleaseAsset
    setup_asset: Optional[ReleaseAsset] = None


ProgressCallback = Callable[[int, str], None]


def normalize_version(tag_or_version: str) -> str:
    value = (tag_or_version or "").strip()
    if value.lower().startswith("v"):
        value = value[1:]
    return value.split("-")[0]


def compare_versions(latest: str, current: str) -> int:
    """Return 1 if latest > current, -1 if older, 0 if equal."""

    def parts(v: str) -> list[int]:
        clean = normalize_version(v)
        nums = []
        for piece in clean.split("."):
            try:
                nums.append(int(piece))
            except ValueError:
                nums.append(0)
        while len(nums) < 3:
            nums.append(0)
        return nums[:3]

    left, right = parts(latest), parts(current)
    if left > right:
        return 1
    if left < right:
        return -1
    return 0


def is_newer_version(latest: str, current: str) -> bool:
    return compare_versions(latest, current) > 0


def fetch_latest_release(
    owner: str = GITHUB_OWNER,
    repo: str = GITHUB_REPO,
    timeout: float = 30.0,
) -> GitHubRelease:
    url = f"https://api.github.com/repos/{owner}/{repo}/releases/latest"
    request = Request(url, headers={"Accept": "application/vnd.github+json", "User-Agent": APP_NAME})
    with urlopen(request, timeout=timeout) as response:
        data = json.loads(response.read().decode("utf-8"))

    zip_asset = None
    setup_asset = None
    for asset in data.get("assets", []):
        name = asset.get("name", "")
        if ZIP_ASSET_PATTERN.match(name):
            zip_asset = ReleaseAsset(name=name, download_url=asset["browser_download_url"], size=asset.get("size", 0))
        elif SETUP_ASSET_PATTERN.match(name):
            setup_asset = ReleaseAsset(
                name=name, download_url=asset["browser_download_url"], size=asset.get("size", 0)
            )

    if zip_asset is None:
        raise RuntimeError("No Windows ZIP artifact found in the latest release")

    tag = data.get("tag_name", "")
    return GitHubRelease(
        tag_name=tag,
        version=normalize_version(tag),
        body=data.get("body", "") or "",
        zip_asset=zip_asset,
        setup_asset=setup_asset,
    )


def download_file(
    url: str,
    destination: Path,
    on_progress: Optional[ProgressCallback] = None,
    timeout: float = 120.0,
) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    request = Request(url, headers={"User-Agent": APP_NAME})
    with urlopen(request, timeout=timeout) as response:
        total = int(response.headers.get("Content-Length", 0) or 0)
        downloaded = 0
        chunk_size = 1024 * 256
        with destination.open("wb") as handle:
            while True:
                chunk = response.read(chunk_size)
                if not chunk:
                    break
                handle.write(chunk)
                downloaded += len(chunk)
                if on_progress and total > 0:
                    pct = min(100, int(downloaded * 100 / total))
                    on_progress(pct, f"Downloading… {pct}%")

    if on_progress:
        on_progress(100, "Download complete")
    return destination


def get_install_dir() -> Optional[Path]:
    if sys.platform == "win32" and winreg is not None:
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, REGISTRY_KEY) as key:
                value, _ = winreg.QueryValueEx(key, "InstallLocation")
                if value:
                    path = Path(value)
                    if path.is_dir():
                        return path
        except OSError:
            pass

    if DEFAULT_INSTALL_DIR.is_dir() and (DEFAULT_INSTALL_DIR / EXE_NAME).exists():
        return DEFAULT_INSTALL_DIR
    return None


def detect_existing_installation() -> tuple[bool, Path, Optional[str]]:
    """
    Returns (is_installed, install_dir, version).

    Detects registry, installed.json, or DataPyn.exe under the default folder.
    """
    root = get_install_dir()
    if root is None and DEFAULT_INSTALL_DIR.is_dir():
        if (DEFAULT_INSTALL_DIR / EXE_NAME).is_file() or (DEFAULT_INSTALL_DIR / VERSION_FILE).is_file():
            root = DEFAULT_INSTALL_DIR
    if root is None:
        return False, DEFAULT_INSTALL_DIR, None

    version = read_installed_version(root)
    installed = (root / EXE_NAME).is_file() or version is not None
    return installed, root, version


def read_installed_version(install_dir: Optional[Path] = None) -> Optional[str]:
    root = install_dir or get_install_dir()
    if root is None:
        return None
    manifest = root / VERSION_FILE
    if manifest.is_file():
        try:
            payload = json.loads(manifest.read_text(encoding="utf-8"))
            return normalize_version(str(payload.get("version", "")))
        except (json.JSONDecodeError, OSError):
            pass
    if sys.platform == "win32" and winreg is not None:
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, REGISTRY_KEY) as key:
                value, _ = winreg.QueryValueEx(key, "DisplayVersion")
                return normalize_version(str(value))
        except OSError:
            pass
    return None


def write_installed_version(install_dir: Path, version: str) -> None:
    payload = {"version": normalize_version(version), "app": APP_NAME}
    (install_dir / VERSION_FILE).write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _resolve_zip_root(temp_dir: Path) -> Path:
    entries = [p for p in temp_dir.iterdir() if p.name not in ("__MACOSX",)]
    if len(entries) == 1 and entries[0].is_dir():
        inner = entries[0]
        if (inner / "DataPyn.exe").exists():
            return inner
    if (temp_dir / "DataPyn.exe").exists():
        return temp_dir
    for candidate in entries:
        if candidate.is_dir() and (candidate / "DataPyn.exe").exists():
            return candidate
    raise RuntimeError("ZIP does not contain DataPyn.exe")


def wait_for_datapyn_exit(timeout_sec: int = 180) -> bool:
    """Block until DataPyn.exe is not running (used by deferred update)."""
    import time

    deadline = time.monotonic() + timeout_sec
    while time.monotonic() < deadline:
        try:
            result = subprocess.run(
                ["tasklist", "/FI", f"IMAGENAME eq {EXE_NAME}", "/NH"],
                capture_output=True,
                text=True,
                creationflags=_no_window_flags(),
            )
            if EXE_NAME.lower() not in (result.stdout or "").lower():
                return True
        except Exception:
            return True
        time.sleep(1)
    return False


def install_from_zip(
    zip_path: Path,
    install_dir: Path,
    version: str,
    on_progress: Optional[ProgressCallback] = None,
) -> Path:
    if not zip_path.is_file():
        raise FileNotFoundError(zip_path)

    install_dir = Path(install_dir)
    install_dir.parent.mkdir(parents=True, exist_ok=True)
    backup_dir = install_dir.with_name(install_dir.name + ".old")
    staging_dir = install_dir.with_name(install_dir.name + ".staging")

    if on_progress:
        on_progress(5, "Preparing installation…")

    extract_parent = Path(tempfile.mkdtemp(prefix="datapyn-install-"))
    try:
        with zipfile.ZipFile(zip_path, "r") as archive:
            if on_progress:
                on_progress(15, "Extracting files…")
            archive.extractall(extract_parent)

        source_root = _resolve_zip_root(extract_parent)
        if staging_dir.exists():
            shutil.rmtree(staging_dir, ignore_errors=True)

        if on_progress:
            on_progress(50, "Copying application files…")
        shutil.copytree(source_root, staging_dir)

        if not (staging_dir / EXE_NAME).exists():
            raise RuntimeError(f"{EXE_NAME} missing after extract")

        if install_dir.exists():
            if on_progress:
                on_progress(70, "Updating existing installation…")
            if backup_dir.exists():
                shutil.rmtree(backup_dir, ignore_errors=True)
            try:
                install_dir.rename(backup_dir)
            except OSError as exc:
                raise RuntimeError(
                    f"Cannot replace installation while {EXE_NAME} is in use. "
                    "Close DataPyn and try again."
                ) from exc

        staging_dir.rename(install_dir)

        write_installed_version(install_dir, version)
        register_uninstall(install_dir, version)
        create_shortcuts(install_dir / EXE_NAME)

        if backup_dir.exists():
            shutil.rmtree(backup_dir, ignore_errors=True)

        if on_progress:
            on_progress(100, "Installation complete")

        return install_dir / EXE_NAME
    except Exception:
        if staging_dir.exists() and not (install_dir / EXE_NAME).exists():
            shutil.rmtree(staging_dir, ignore_errors=True)
        if backup_dir.exists() and not (install_dir / EXE_NAME).exists():
            if install_dir.exists():
                shutil.rmtree(install_dir, ignore_errors=True)
            backup_dir.rename(install_dir)
        raise
    finally:
        shutil.rmtree(extract_parent, ignore_errors=True)
        if staging_dir.exists():
            shutil.rmtree(staging_dir, ignore_errors=True)


def _no_window_flags() -> int:
    return getattr(subprocess, "CREATE_NO_WINDOW", 0)


def _source_brand_icon() -> Optional[Path]:
    candidates: list[Path] = []
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        candidates.append(Path(sys._MEIPASS) / "src" / "assets" / ICON_FILE_NAME)
    candidates.append(Path(__file__).resolve().parent.parent / "assets" / ICON_FILE_NAME)
    for path in candidates:
        if path.is_file():
            return path
    return None


def _ensure_brand_icon(install_dir: Path, exe_path: Path) -> Path:
    """Copy .ico beside the app when possible; used for Apps & Features icon."""
    install_dir = Path(install_dir)
    dest = install_dir / ICON_FILE_NAME
    if dest.is_file():
        return dest

    for src in (
        install_dir / "src" / "assets" / ICON_FILE_NAME,
        _source_brand_icon(),
    ):
        if src is None or not Path(src).is_file():
            continue
        try:
            shutil.copy2(src, dest)
            return dest
        except OSError as exc:
            logger.warning("Could not copy icon to install dir: %s", exc)
    return exe_path


def _display_icon_value(icon_path: Path) -> str:
    return f"{icon_path},0"


def _delete_uninstall_registry() -> None:
    if sys.platform != "win32":
        return
    if winreg is not None:
        try:
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, REGISTRY_KEY)
            return
        except OSError:
            pass
    subprocess.run(
        ["reg", "delete", REGISTRY_DELETE_ARG, "/f"],
        check=False,
        creationflags=_no_window_flags(),
    )


def _build_uninstall_command(install_dir: Path) -> str:
    """One-shot uninstall for Settings (registry removed before folder delete)."""
    root = str(install_dir)
    return (
        f'cmd.exe /c reg delete "{REGISTRY_DELETE_ARG}" /f '
        f"&& taskkill /IM {EXE_NAME} /F "
        f'&& rmdir /s /q "{root}"'
    )


def _write_uninstall_cmd(install_dir: Path) -> Path:
    install_dir = Path(install_dir)
    script = install_dir / "uninstall.cmd"
    script.write_text(
        "\r\n".join(
            [
                "@echo off",
                f'reg delete "{REGISTRY_DELETE_ARG}" /f >nul 2>&1',
                f"taskkill /IM {EXE_NAME} /F >nul 2>&1",
                f'rmdir /s /q "{install_dir}"',
                "echo DataPyn foi removido.",
                "pause",
            ]
        ),
        encoding="utf-8",
    )
    return script


def register_uninstall(install_dir: Path, version: str) -> None:
    install_dir = Path(install_dir)
    exe_path = install_dir / EXE_NAME
    icon_path = _ensure_brand_icon(install_dir, exe_path)
    _write_uninstall_cmd(install_dir)

    if sys.platform != "win32" or winreg is None:
        return

    uninstall_string = _build_uninstall_command(install_dir)
    install_date = int(date.today().strftime("%Y%m%d"))

    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, REGISTRY_KEY) as key:
        winreg.SetValueEx(key, "DisplayName", 0, winreg.REG_SZ, APP_NAME)
        winreg.SetValueEx(key, "DisplayVersion", 0, winreg.REG_SZ, normalize_version(version))
        winreg.SetValueEx(key, "Publisher", 0, winreg.REG_SZ, "natharuc")
        winreg.SetValueEx(key, "InstallLocation", 0, winreg.REG_SZ, str(install_dir))
        winreg.SetValueEx(key, "DisplayIcon", 0, winreg.REG_SZ, _display_icon_value(icon_path))
        winreg.SetValueEx(key, "InstallDate", 0, winreg.REG_DWORD, install_date)
        winreg.SetValueEx(key, "UninstallString", 0, winreg.REG_SZ, uninstall_string)
        winreg.SetValueEx(key, "QuietUninstallString", 0, winreg.REG_SZ, uninstall_string)
        winreg.SetValueEx(key, "NoModify", 0, winreg.REG_DWORD, 1)
        winreg.SetValueEx(key, "NoRepair", 0, winreg.REG_DWORD, 1)


def create_shortcuts(target_exe: Path) -> None:
    target_exe = Path(target_exe)
    work_dir = str(target_exe.parent)
    target = str(target_exe)
    start_menu = Path(os.environ.get("APPDATA", "")) / "Microsoft" / "Windows" / "Start Menu" / "Programs"
    desktop = Path(os.environ.get("USERPROFILE", "")) / "Desktop"

    for folder, label in ((start_menu, APP_NAME), (desktop, APP_NAME)):
        if not folder.exists():
            continue
        shortcut = folder / f"{label}.lnk"
        _create_shortcut_ps(target, work_dir, shortcut)


def _create_shortcut_ps(target: str, work_dir: str, shortcut: Path) -> None:
    script = (
        "$shell = New-Object -ComObject WScript.Shell; "
        f"$s = $shell.CreateShortcut('{shortcut}'); "
        f"$s.TargetPath = '{target}'; "
        f"$s.WorkingDirectory = '{work_dir}'; "
        f"$s.IconLocation = '{target},0'; "
        "$s.Save()"
    )
    subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
        check=False,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )


def uninstall(install_dir: Optional[Path] = None) -> bool:
    root = install_dir or get_install_dir()
    if root is None:
        return False

    _delete_uninstall_registry()

    try:
        subprocess.run(
            ["taskkill", "/IM", EXE_NAME, "/F"],
            check=False,
            creationflags=_no_window_flags(),
        )
    except Exception:
        pass
    try:
        shutil.rmtree(root, ignore_errors=True)
    except OSError as exc:
        logger.error("Uninstall failed: %s", exc)
        return False
    for folder in (
        Path(os.environ.get("APPDATA", "")) / "Microsoft" / "Windows" / "Start Menu" / "Programs",
        Path(os.environ.get("USERPROFILE", "")) / "Desktop",
    ):
        link = folder / f"{APP_NAME}.lnk"
        if link.exists():
            link.unlink(missing_ok=True)
    return True


def launch_application(exe_path: Path) -> None:
    subprocess.Popen([str(exe_path)], cwd=str(exe_path.parent), creationflags=subprocess.DETACHED_PROCESS)


def install_latest_release(
    install_dir: Path,
    on_progress: Optional[ProgressCallback] = None,
) -> tuple[Path, GitHubRelease]:
    release = fetch_latest_release()
    temp_zip = Path(tempfile.gettempdir()) / release.zip_asset.name
    download_file(release.zip_asset.download_url, temp_zip, on_progress=on_progress)
    exe = install_from_zip(temp_zip, install_dir, release.version, on_progress=on_progress)
    try:
        temp_zip.unlink(missing_ok=True)
    except OSError:
        pass
    return exe, release


def repair_installation(
    install_dir: Optional[Path] = None,
    on_progress: Optional[ProgressCallback] = None,
) -> tuple[Path, str]:
    """
    Re-download the latest release and replace files in the existing install folder.

    Waits for DataPyn.exe to exit before replacing files.
    """
    installed, target, _version = detect_existing_installation()
    root = Path(install_dir) if install_dir else target
    if not installed and not root.is_dir():
        raise RuntimeError("DataPyn is not installed — use a fresh install instead.")

    if on_progress:
        on_progress(2, "Aguardando o DataPyn encerrar…")
    if not wait_for_datapyn_exit():
        raise RuntimeError(f"Close {EXE_NAME} before repairing the installation.")

    if on_progress:
        on_progress(5, "Baixando a versão mais recente…")
    exe, release = install_latest_release(root, on_progress=on_progress)
    return exe, release.version


def apply_downloaded_update(zip_path: Path, version: str, install_dir: Optional[Path] = None) -> Path:
    root = install_dir or get_install_dir() or DEFAULT_INSTALL_DIR
    return install_from_zip(zip_path, root, version)


def _download_setup_helper() -> Optional[Path]:
    try:
        release = fetch_latest_release()
        if not release.setup_asset:
            return None
        dest = Path(tempfile.gettempdir()) / release.setup_asset.name
        download_file(release.setup_asset.download_url, dest)
        return dest if dest.is_file() else None
    except Exception as exc:
        logger.warning("Could not download setup helper: %s", exc)
        return None


def launch_deferred_zip_update(
    zip_path: Path, version: str, install_dir: Optional[Path] = None
) -> bool:
    """
    Apply a ZIP update after DataPyn.exe exits.

    Must be used from the running app before quit — never call install_from_zip in-process.
    """
    zip_path = Path(zip_path).resolve()
    if not zip_path.is_file():
        logger.error("Update ZIP not found: %s", zip_path)
        return False

    root = Path(install_dir or get_install_dir() or DEFAULT_INSTALL_DIR)
    ver = normalize_version(version)
    setup_exe = _download_setup_helper()
    if not setup_exe:
        logger.error("DataPyn-Setup.exe not available for deferred update")
        return False

    script = Path(tempfile.gettempdir()) / f"datapyn-apply-update-{ver}.cmd"
    script.write_text(
        "\r\n".join(
            [
                "@echo off",
                "setlocal",
                ":wait",
                f'tasklist /FI "IMAGENAME eq {EXE_NAME}" 2>nul | find /I "{EXE_NAME}" >nul',
                "if %errorlevel%==0 (",
                "  timeout /t 1 /nobreak >nul",
                "  goto wait",
                ")",
                f'"{setup_exe}" --update "{zip_path}" --version {ver} --dir "{root}"',
                f'del /f /q "{script}" 2>nul',
            ]
        ),
        encoding="utf-8",
    )

    subprocess.Popen(
        ["cmd.exe", "/c", str(script)],
        creationflags=subprocess.DETACHED_PROCESS | _no_window_flags(),
        close_fds=True,
    )
    logger.info("Deferred update scheduled via %s", script)
    return True


def run_setup_for_update(zip_path: Path, version: str, install_dir: Optional[Path] = None) -> bool:
    """Schedule ZIP update after the application exits."""
    return launch_deferred_zip_update(zip_path, version, install_dir)


def parse_cli_args(argv: list[str]) -> dict[str, str]:
    flags: dict[str, str] = {}
    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg in ("--uninstall", "--repair"):
            flags[arg] = "1"
            i += 1
            continue
        if arg in ("--update", "--dir", "--version") and i + 1 < len(argv):
            flags[arg] = argv[i + 1]
            i += 2
            continue
        i += 1
    return flags


def find_windows_zip_asset(assets: list[dict]) -> Optional[ReleaseAsset]:
    for asset in assets or []:
        name = asset.get("name", "")
        if ZIP_ASSET_PATTERN.match(name):
            return ReleaseAsset(
                name=name,
                download_url=asset.get("browser_download_url", ""),
                size=int(asset.get("size", 0) or 0),
            )
    return None
