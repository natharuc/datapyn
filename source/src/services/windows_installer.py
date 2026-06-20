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


def resolve_update_install_dir() -> Path:
    """Install folder for in-place updates (prefer the running frozen EXE directory)."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    found = get_install_dir()
    if found is not None:
        return found
    return DEFAULT_INSTALL_DIR


def _append_update_log(message: str) -> None:
    try:
        from datetime import datetime

        log_path = Path(tempfile.gettempdir()) / "datapyn-update.log"
        line = f"{datetime.now().isoformat(timespec='seconds')} {message}\n"
        with log_path.open("a", encoding="utf-8") as handle:
            handle.write(line)
    except OSError:
        pass


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


def _datapyn_process_pids(exclude_pid: Optional[int] = None) -> list[int]:
    """Return PIDs of running DataPyn.exe instances, optionally excluding one PID."""
    if sys.platform != "win32":
        return []
    try:
        result = subprocess.run(
            ["tasklist", "/FI", f"IMAGENAME eq {EXE_NAME}", "/FO", "CSV", "/NH"],
            capture_output=True,
            text=True,
            creationflags=_no_window_flags(),
        )
        pids: list[int] = []
        for line in (result.stdout or "").splitlines():
            line = line.strip()
            if not line or "INFO:" in line.upper():
                continue
            parts = line.split(",")
            if len(parts) < 2:
                continue
            try:
                pid = int(parts[1].strip().strip('"'))
            except ValueError:
                continue
            if exclude_pid is None or pid != exclude_pid:
                pids.append(pid)
        return pids
    except Exception:
        return []


def _process_is_running(pid: int) -> bool:
    """Return True when *pid* refers to a live process."""
    if pid <= 0:
        return False
    if sys.platform == "win32":
        try:
            result = subprocess.run(
                ["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
                capture_output=True,
                text=True,
                creationflags=_no_window_flags(),
            )
            line = (result.stdout or "").strip()
            if not line or "INFO:" in line.upper():
                return False
            return f'"{pid}"' in line or f",{pid}," in line.replace(" ", "")
        except Exception:
            return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    else:
        return True


def wait_for_process_exit(pid: int, timeout_sec: int = 180) -> bool:
    """Block until the process *pid* is no longer running."""
    import time

    if pid <= 0:
        return True
    deadline = time.monotonic() + timeout_sec
    while time.monotonic() < deadline:
        if not _process_is_running(pid):
            return True
        time.sleep(0.5)
    return False


def wait_for_datapyn_exit(timeout_sec: int = 180, exclude_pid: Optional[int] = None) -> bool:
    """Block until no other DataPyn.exe instance is running (excludes updater PID)."""
    import time

    excluded = exclude_pid if exclude_pid is not None else os.getpid()
    deadline = time.monotonic() + timeout_sec
    while time.monotonic() < deadline:
        if not _datapyn_process_pids(exclude_pid=excluded):
            return True
        time.sleep(0.5)
    return False


def _install_locked_message(pids: list[int], *, extra: str = "") -> str:
    """User-facing error when the install folder cannot be replaced."""
    base = (
        "Não foi possível substituir a instalação — arquivos do DataPyn ainda estão em uso. "
        "Feche o DataPyn e tente novamente."
    )
    if pids:
        base += f" Processos {EXE_NAME} (PID): {', '.join(str(pid) for pid in pids)}."
    if extra:
        base += f" {extra}"
    return base


def _updater_runs_from_install_dir(install_dir: Path) -> bool:
    """True when this process runs from inside the install folder (locks files on rename)."""
    try:
        exe = Path(sys.executable).resolve()
        root = Path(install_dir).resolve()
        return root == exe.parent or root in exe.parents
    except OSError:
        return False


def _robocopy_mirror(source: Path, dest: Path) -> None:
    """Mirror *source* into *dest* on Windows (handles files in use more gracefully)."""
    dest.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        [
            "robocopy",
            str(source),
            str(dest),
            "/MIR",
            "/R:3",
            "/W:2",
            "/NFL",
            "/NDL",
            "/NJH",
            "/NJS",
            "/nc",
            "/ns",
            "/np",
        ],
        capture_output=True,
        text=True,
        creationflags=_no_window_flags(),
    )
    if result.returncode >= 8:
        detail = ((result.stdout or "") + (result.stderr or "")).strip()[-400:]
        raise OSError(f"robocopy failed ({result.returncode}): {detail}")


def _sync_dir_contents(source: Path, dest: Path) -> None:
    """Copy new files over an existing install folder without renaming the root."""
    source = Path(source)
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)

    for src_path in source.rglob("*"):
        rel = src_path.relative_to(source)
        dst_path = dest / rel
        if src_path.is_dir():
            dst_path.mkdir(parents=True, exist_ok=True)
            continue
        dst_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src_path, dst_path)

    for dst_path in sorted(dest.rglob("*"), reverse=True):
        rel = dst_path.relative_to(dest)
        if (source / rel).exists():
            continue
        if dst_path.is_dir():
            try:
                dst_path.rmdir()
            except OSError:
                pass
        else:
            dst_path.unlink(missing_ok=True)


def _replace_installation(
    install_dir: Path,
    staging_dir: Path,
    backup_dir: Path,
    *,
    on_progress: Optional[ProgressCallback] = None,
) -> None:
    """Swap an existing install tree for *staging_dir*, waiting for locks to clear."""
    import os
    import time

    exclude = os.getpid()

    if on_progress:
        on_progress(68, "Aguardando o DataPyn encerrar…")
    if not wait_for_datapyn_exit(timeout_sec=120, exclude_pid=exclude):
        raise RuntimeError(_install_locked_message(_datapyn_process_pids(exclude_pid=exclude)))

    if backup_dir.exists():
        shutil.rmtree(backup_dir, ignore_errors=True)

    force_in_place = _updater_runs_from_install_dir(install_dir)
    last_rename_error: Optional[OSError] = None

    if not force_in_place:
        for _attempt in range(30):
            try:
                install_dir.rename(backup_dir)
                staging_dir.rename(install_dir)
                shutil.rmtree(backup_dir, ignore_errors=True)
                return
            except OSError as exc:
                last_rename_error = exc
                time.sleep(1)
        force_in_place = True

    if on_progress:
        on_progress(72, "Substituindo arquivos da instalação…")
    try:
        if sys.platform == "win32":
            _robocopy_mirror(staging_dir, install_dir)
        else:
            _sync_dir_contents(staging_dir, install_dir)
    except OSError as exc:
        raise RuntimeError(
            _install_locked_message(
                _datapyn_process_pids(exclude_pid=exclude),
                extra="Feche o instalador se ele estiver aberto na pasta do DataPyn.",
            )
        ) from (last_rename_error or exc)

    shutil.rmtree(staging_dir, ignore_errors=True)
    if backup_dir.exists():
        shutil.rmtree(backup_dir, ignore_errors=True)


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
            _replace_installation(
                install_dir, staging_dir, backup_dir, on_progress=on_progress
            )
        else:
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


def _find_local_setup_helper(install_dir: Path) -> Optional[Path]:
    """Locate DataPyn-Setup.exe beside the installed application."""
    root = Path(install_dir)
    for candidate in (
        root / "DataPyn-Setup.exe",
        *sorted(root.glob("DataPyn-Setup*.exe")),
    ):
        if candidate.is_file():
            return candidate
    return None


def _download_setup_helper() -> Optional[Path]:
    cached = Path(tempfile.gettempdir()) / "DataPyn-Setup.exe"
    if cached.is_file() and cached.stat().st_size > 0:
        return cached

    try:
        release = fetch_latest_release()
        if not release.setup_asset:
            return None
        dest = cached
        download_file(release.setup_asset.download_url, dest, timeout=180.0)
        return dest if dest.is_file() else None
    except Exception as exc:
        logger.warning("Could not download setup helper: %s", exc)
        return None


def _cache_setup_in_install_dir(install_dir: Path, setup_exe: Path) -> Path:
    """Keep DataPyn-Setup.exe beside the app so offline one-click updates work."""
    install_dir = Path(install_dir)
    setup_exe = Path(setup_exe)
    if not setup_exe.is_file():
        return setup_exe
    dest = install_dir / "DataPyn-Setup.exe"
    if dest.resolve() == setup_exe.resolve():
        return dest
    try:
        if not dest.is_file() or dest.stat().st_size != setup_exe.stat().st_size:
            shutil.copy2(setup_exe, dest)
            logger.info("Cached setup helper at %s", dest)
        return dest
    except OSError as exc:
        logger.warning("Could not cache setup helper in %s: %s", install_dir, exc)
        return setup_exe


def _resolve_setup_helper(install_dir: Path) -> Optional[Path]:
    local = _find_local_setup_helper(install_dir)
    if local is not None:
        return local
    downloaded = _download_setup_helper()
    if downloaded is None:
        return None
    return _cache_setup_in_install_dir(install_dir, downloaded)


def _hidden_startupinfo() -> Optional[subprocess.STARTUPINFO]:
    if sys.platform != "win32":
        return None
    info = subprocess.STARTUPINFO()
    info.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    info.wShowWindow = subprocess.SW_HIDE
    return info


def _gui_subprocess_executable(executable: str) -> str:
    """Prefer pythonw.exe on Windows so dev updates never flash a console."""
    if sys.platform != "win32":
        return executable
    exe = Path(executable)
    if exe.name.lower() == "python.exe":
        pythonw = exe.with_name("pythonw.exe")
        if pythonw.is_file():
            return str(pythonw)
    return executable


def _spawn_detached(command: list[str], cwd: Path) -> None:
    """Launch a GUI child that survives after DataPyn.exe exits."""
    if sys.platform == "win32":
        launch_cmd = list(command)
        launch_cmd[0] = _gui_subprocess_executable(launch_cmd[0])
        creationflags = _no_window_flags()
        creationflags |= getattr(subprocess, "DETACHED_PROCESS", 0x00000008)
        creationflags |= getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200)
        stderr_target: int | object = subprocess.DEVNULL
        if "--apply-update" in launch_cmd:
            updater_log = Path(tempfile.gettempdir()) / "datapyn-updater.log"
            _append_update_log(f"Spawn detached: {' '.join(launch_cmd)}")
            stderr_target = updater_log.open("a", encoding="utf-8")
        subprocess.Popen(
            launch_cmd,
            cwd=str(cwd),
            creationflags=creationflags,
            startupinfo=_hidden_startupinfo(),
            close_fds=True,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=stderr_target,
        )
        return
    subprocess.Popen(
        command,
        cwd=str(cwd),
        close_fds=True,
        start_new_session=True,
    )


def _powershell_wait_for_exit_block() -> str:
    return """
    Log 'Waiting for DataPyn to exit...'
    while (Get-Process -Name 'DataPyn' -ErrorAction SilentlyContinue) { Start-Sleep -Seconds 1 }
"""


def _powershell_setup_update_script(
    setup_exe: Path, zip_path: Path, version: str, install_dir: Path
) -> str:
    """Hidden deferred update via DataPyn-Setup.exe (no cmd.exe / find)."""
    setup = str(setup_exe).replace("'", "''")
    zp = str(zip_path).replace("'", "''")
    idir = str(install_dir).replace("'", "''")
    ver = normalize_version(version)
    return f"""
$ErrorActionPreference = 'Stop'
$setup = '{setup}'
$zip = '{zp}'
$installDir = '{idir}'
$version = '{ver}'
$log = Join-Path $env:TEMP 'datapyn-update.log'
function Log($msg) {{ Add-Content -Path $log -Value "$(Get-Date -Format o) $msg" }}
try {{
{_powershell_wait_for_exit_block()}
    Log "Running setup update ($setup)"
    $args = @('--update', $zip, '--version', $version, '--dir', $installDir)
    $proc = Start-Process -FilePath $setup -ArgumentList $args -Wait -PassThru -WindowStyle Normal
    if ($proc.ExitCode -ne 0) {{
        throw "Setup exited with code $($proc.ExitCode)"
    }}
    Log 'Setup update complete'
}} catch {{
    Log "ERROR: $($_.Exception.Message)"
    exit 1
}}
"""


def _powershell_apply_update_script(zip_path: Path, version: str, install_dir: Path) -> str:
    """PowerShell fallback — extract ZIP and swap install dir after app exits."""
    zp = str(zip_path).replace("'", "''")
    idir = str(install_dir).replace("'", "''")
    ver = normalize_version(version)
    return f"""
$ErrorActionPreference = 'Stop'
$zip = '{zp}'
$installDir = '{idir}'
$version = '{ver}'
$exeName = '{EXE_NAME}'
$log = Join-Path $env:TEMP 'datapyn-update.log'
function Log($msg) {{ Add-Content -Path $log -Value "$(Get-Date -Format o) $msg" }}
try {{
{_powershell_wait_for_exit_block()}
    $extractRoot = Join-Path $env:TEMP ("datapyn-update-extract-" + $version)
    if (Test-Path $extractRoot) {{ Remove-Item -Recurse -Force $extractRoot }}
    New-Item -ItemType Directory -Path $extractRoot | Out-Null
    Log "Extracting $zip"
    Expand-Archive -LiteralPath $zip -DestinationPath $extractRoot -Force
    $sourceRoot = $extractRoot
    $entries = @(Get-ChildItem -LiteralPath $extractRoot | Where-Object {{ $_.Name -ne '__MACOSX' }})
    if ($entries.Count -eq 1 -and $entries[0].PSIsContainer) {{
        $inner = $entries[0].FullName
        if (Test-Path (Join-Path $inner $exeName)) {{ $sourceRoot = $inner }}
    }}
    if (-not (Test-Path (Join-Path $sourceRoot $exeName))) {{
        foreach ($c in $entries) {{
            if ($c.PSIsContainer -and (Test-Path (Join-Path $c.FullName $exeName))) {{
                $sourceRoot = $c.FullName
                break
            }}
        }}
    }}
    if (-not (Test-Path (Join-Path $sourceRoot $exeName))) {{
        throw 'ZIP does not contain DataPyn.exe'
    }}
    $staging = "$installDir.staging"
    $backup = "$installDir.old"
    if (Test-Path $staging) {{ Remove-Item -Recurse -Force $staging }}
    Log 'Copying application files'
    Copy-Item -LiteralPath $sourceRoot -Destination $staging -Recurse -Force
    if (-not (Test-Path (Join-Path $staging $exeName))) {{
        throw 'DataPyn.exe missing after extract'
    }}
    if (Test-Path $installDir) {{
        if (Test-Path $backup) {{ Remove-Item -Recurse -Force $backup }}
        Rename-Item -LiteralPath $installDir -NewName (Split-Path $backup -Leaf)
    }}
    Rename-Item -LiteralPath $staging -NewName (Split-Path $installDir -Leaf)
    @{{ version = $version; app = '{APP_NAME}' }} | ConvertTo-Json | Set-Content -Path (Join-Path $installDir 'installed.json') -Encoding UTF8
    $exePath = Join-Path $installDir $exeName
    Log "Launching $exePath"
    Start-Process -FilePath $exePath -WorkingDirectory $installDir
    if (Test-Path $backup) {{ Remove-Item -Recurse -Force $backup -ErrorAction SilentlyContinue }}
    Remove-Item -Recurse -Force $extractRoot -ErrorAction SilentlyContinue
    Log 'Update complete'
}} catch {{
    Log "ERROR: $($_.Exception.Message)"
    exit 1
}}
"""


def _run_hidden_powershell_script(script_body: str, script_filename: str) -> tuple[bool, str]:
    """Launch a .ps1 update helper without showing cmd.exe or Windows Terminal."""
    if sys.platform != "win32":
        return False, "Deferred ZIP update is only supported on Windows"

    script_path = Path(tempfile.gettempdir()) / script_filename
    try:
        script_path.write_text(script_body, encoding="utf-8")
    except OSError as exc:
        return False, f"Could not write update script: {exc}"

    subprocess.Popen(
        [
            "powershell.exe",
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-WindowStyle",
            "Hidden",
            "-File",
            str(script_path),
        ],
        creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP | _no_window_flags(),
        close_fds=True,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    logger.info("Deferred update scheduled via PowerShell %s", script_path)
    return True, ""


def _launch_powershell_deferred_update(
    zip_path: Path, version: str, install_dir: Path
) -> tuple[bool, str]:
    ver = normalize_version(version)
    return _run_hidden_powershell_script(
        _powershell_apply_update_script(zip_path, ver, install_dir),
        f"datapyn-apply-update-{ver}.ps1",
    )


def launch_deferred_zip_update(
    zip_path: Path, version: str, install_dir: Optional[Path] = None
) -> tuple[bool, str]:
    """
    Apply a ZIP update after DataPyn.exe exits.

    Must be used from the running app before quit — never call install_from_zip in-process.
    """
    zip_path = Path(zip_path).resolve()
    if not zip_path.is_file():
        msg = f"Update ZIP not found: {zip_path}"
        logger.error(msg)
        return False, msg

    root = Path(install_dir or get_install_dir() or DEFAULT_INSTALL_DIR)
    ver = normalize_version(version)
    if not ver:
        return False, "Update version is required"

    setup_exe = _resolve_setup_helper(root)
    if setup_exe is not None:
        return _run_hidden_powershell_script(
            _powershell_setup_update_script(setup_exe, zip_path, ver, root),
            f"datapyn-setup-update-{ver}.ps1",
        )

    logger.warning("DataPyn-Setup.exe not found — using PowerShell ZIP apply")
    return _launch_powershell_deferred_update(zip_path, ver, root)


def _is_frozen_runtime() -> bool:
    """True when running as a PyInstaller bundle (not ``python main.py``)."""
    return bool(getattr(sys, "frozen", False))


def _stage_updater_executable(source_exe: Path, version: str) -> Path:
    """Copy the PyInstaller onedir bundle (exe + ``_internal``) to TEMP for ``--apply-update``.

    Copying only the EXE breaks at runtime: the frozen app looks for ``_internal/python*.dll``
    next to the executable (e.g. ``%TEMP%\\_internal`` when only the exe was copied).
    """
    source_exe = Path(source_exe).resolve()
    install_dir = source_exe.parent
    ver = normalize_version(version)
    staging_dir = Path(tempfile.gettempdir()) / f"DataPyn-Update-{ver}"

    legacy_exe = staging_dir.with_suffix(".exe")
    if legacy_exe.is_file():
        legacy_exe.unlink(missing_ok=True)

    if staging_dir.exists():
        shutil.rmtree(staging_dir, ignore_errors=True)
    staging_dir.mkdir(parents=True, exist_ok=True)

    dest_exe = staging_dir / EXE_NAME
    shutil.copy2(source_exe, dest_exe)

    internal_src = install_dir / "_internal"
    if internal_src.is_dir():
        shutil.copytree(internal_src, staging_dir / "_internal")

    _append_update_log(f"Staged updater at {dest_exe} (_internal={'yes' if internal_src.is_dir() else 'no'})")
    return dest_exe


def launch_setup_update(
    zip_path: Path, version: str, install_dir: Optional[Path] = None
) -> tuple[bool, str]:
    """Launch a staged DataPyn.exe with ``--apply-update`` (progress UI, then reopen)."""
    zip_path = Path(zip_path).resolve()
    if not zip_path.is_file():
        return False, f"Update ZIP not found: {zip_path}"

    root = Path(install_dir or resolve_update_install_dir())
    ver = normalize_version(version)
    if not ver:
        return False, "Update version is required"

    app_exe = root / EXE_NAME
    if not app_exe.is_file():
        _append_update_log(f"ERROR: {EXE_NAME} not found in {root}")
        return False, f"{EXE_NAME} not found in {root}"

    try:
        if _is_frozen_runtime():
            updater_exe = _stage_updater_executable(app_exe, ver)
            command = [
                str(updater_exe),
                "--apply-update",
                str(zip_path),
                "--version",
                ver,
                "--dir",
                str(root),
                "--parent-pid",
                str(os.getpid()),
            ]
            cwd = updater_exe.parent
            launcher = str(updater_exe)
        else:
            # Dev: run current source entrypoint (installed EXE may lack --apply-update).
            source_main = Path(__file__).resolve().parents[2] / "main.py"
            command = [
                sys.executable,
                str(source_main),
                "--apply-update",
                str(zip_path),
                "--version",
                ver,
                "--dir",
                str(root),
                "--parent-pid",
                str(os.getpid()),
            ]
            cwd = source_main.parent
            launcher = source_main

        _append_update_log(f"Launching in-app update v{ver} via {launcher}")
        _spawn_detached(command, cwd)
        logger.info("Launched in-app update (detached): %s -> v%s", zip_path, ver)
        return True, ""
    except OSError as exc:
        _append_update_log(f"ERROR: Could not launch updater: {exc}")
        return False, f"Could not launch updater: {exc}"


def run_setup_for_update(zip_path: Path, version: str, install_dir: Optional[Path] = None) -> bool:
    """Schedule ZIP update after the application exits."""
    ok, _msg = launch_deferred_zip_update(zip_path, version, install_dir)
    return ok


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
