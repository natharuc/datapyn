"""
Persist session DataFrame variables as Parquet for optional restore on startup.

Snapshots user variables from the session namespace (not the results grid).
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import tempfile
import threading
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
from PyQt6.QtCore import QSettings

logger = logging.getLogger(__name__)

SETTINGS_ORG = "DataPyn"
SETTINGS_APP = "DataPyn"
KEY_ENABLED = "session_results/enabled"
KEY_MAX_SIZE_MB = "session_results/max_size_mb"

DEFAULT_MAX_SIZE_MB = 50
MANIFEST_NAME = "manifest.json"
PARQUET_COMPRESSION = "snappy"
SKIP_VARIABLE_NAMES = frozenset({"pd", "np", "plt"})

ResultItem = Tuple[str, pd.DataFrame]
VariableMap = Dict[str, pd.DataFrame]


def _settings() -> QSettings:
    return QSettings(SETTINGS_ORG, SETTINGS_APP)


def is_session_result_restore_enabled() -> bool:
    return bool(_settings().value(KEY_ENABLED, False, type=bool))


def get_session_result_max_size_mb() -> int:
    try:
        value = int(_settings().value(KEY_MAX_SIZE_MB, DEFAULT_MAX_SIZE_MB))
    except (TypeError, ValueError):
        value = DEFAULT_MAX_SIZE_MB
    return max(1, min(value, 10_000))


def get_session_result_max_size_bytes() -> int:
    return get_session_result_max_size_mb() * 1024 * 1024


def set_session_result_restore_enabled(enabled: bool) -> None:
    _settings().setValue(KEY_ENABLED, bool(enabled))


def set_session_result_max_size_mb(mb: int) -> None:
    _settings().setValue(KEY_MAX_SIZE_MB, max(1, min(int(mb), 10_000)))


def _current_workspace_path() -> str:
    from src.core.workspace_service import get_workspace_service

    try:
        return str(get_workspace_service().current_workspace.resolve())
    except OSError:
        return str(get_workspace_service().current_workspace)


def _storage_root() -> Path:
    """Local app cache — avoids workspace folders (e.g. OneDrive) that may deny writes."""
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA") or os.environ.get("TEMP") or tempfile.gettempdir()
    else:
        base = os.environ.get("XDG_CACHE_HOME") or os.path.join(
            os.path.expanduser("~"), ".cache"
        )
        if not base:
            base = tempfile.gettempdir()

    root = Path(base) / "DataPyn" / "session_snapshots"
    try:
        root.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        logger.warning("Failed to create session snapshot root %s: %s", root, exc)
        fallback = Path(tempfile.gettempdir()) / "DataPyn" / "session_snapshots"
        fallback.mkdir(parents=True, exist_ok=True)
        return fallback
    return root


def get_session_snapshots_root() -> Path:
    """Return the directory where per-session variable snapshots are stored."""
    return _storage_root()


def _session_dir(session_id: str) -> Path:
    safe_id = str(session_id or "").strip()
    if not safe_id:
        raise ValueError("session_id is required")
    return _storage_root() / safe_id


def _dir_size(path: Path) -> int:
    total = 0
    if not path.exists():
        return 0
    for child in path.rglob("*"):
        if child.is_file():
            try:
                total += child.stat().st_size
            except OSError:
                pass
    return total


def _to_pandas_dataframe(value: Any) -> Optional[pd.DataFrame]:
    if isinstance(value, pd.DataFrame):
        return value
    try:
        import polars as pl

        if isinstance(value, pl.DataFrame):
            return value.to_pandas()
    except ImportError:
        pass
    return None


def format_storage_size(num_bytes: int) -> str:
    if num_bytes < 1024:
        return f"{num_bytes} B"
    if num_bytes < 1024 * 1024:
        return f"{num_bytes / 1024:.1f} KB"
    return f"{num_bytes / (1024 * 1024):.2f} MB"


def _read_manifest_file(manifest_path: Path) -> Optional[dict]:
    try:
        with open(manifest_path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        return data if isinstance(data, dict) else None
    except (OSError, json.JSONDecodeError):
        return None


def _manifest_workspace_matches(manifest: dict) -> bool:
    stored = manifest.get("workspace")
    if not stored:
        return True
    try:
        return Path(str(stored)).resolve() == Path(_current_workspace_path()).resolve()
    except OSError:
        return str(stored) == _current_workspace_path()


def has_persisted_snapshot(session_id: str) -> bool:
    session_path = _session_dir(session_id)
    manifest_path = session_path / MANIFEST_NAME
    if not manifest_path.is_file():
        return False
    manifest = _read_manifest_file(manifest_path)
    return manifest is not None and _manifest_workspace_matches(manifest)


def get_session_disk_size(session_id: str) -> int:
    return _dir_size(_session_dir(session_id))


def get_snapshot_variable_sizes(session_id: str) -> Dict[str, int]:
    """Return on-disk Parquet file sizes keyed by variable name."""
    if not has_persisted_snapshot(session_id):
        return {}

    session_path = _session_dir(session_id)
    manifest_path = session_path / MANIFEST_NAME
    if not manifest_path.is_file():
        return {}

    sizes: Dict[str, int] = {}
    try:
        with open(manifest_path, "r", encoding="utf-8") as handle:
            manifest = json.load(handle)
        raw_items = manifest.get("variables") or manifest.get("items", [])
        if not isinstance(raw_items, list):
            return sizes
        for entry in raw_items:
            if not isinstance(entry, dict):
                continue
            var_name = str(entry.get("name") or entry.get("label") or "").strip()
            file_name = str(entry.get("file", "")).strip()
            if not var_name or not file_name:
                continue
            parquet_path = session_path / file_name
            if parquet_path.is_file():
                try:
                    sizes[var_name] = parquet_path.stat().st_size
                except OSError:
                    pass
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("Failed to read variable sizes for %s: %s", session_id, exc)
    return sizes


def get_total_storage_bytes() -> int:
    root = _storage_root()
    if not root.exists():
        return 0
    total = 0
    for child in root.iterdir():
        if child.is_dir():
            total += _dir_size(child)
    return total


def list_session_snapshots() -> List[Dict[str, Any]]:
    """Inventory of on-disk variable snapshots keyed by session id."""
    root = _storage_root()
    if not root.exists():
        return []

    entries: List[Dict[str, Any]] = []
    for child in sorted(root.iterdir(), key=lambda p: p.name):
        if not child.is_dir():
            continue
        manifest_path = child / MANIFEST_NAME
        if not manifest_path.is_file():
            continue
        variable_count = 0
        try:
            with open(manifest_path, "r", encoding="utf-8") as handle:
                manifest = json.load(handle)
            raw = manifest.get("variables") or manifest.get("items", [])
            if isinstance(raw, list):
                variable_count = len(raw)
        except (OSError, json.JSONDecodeError):
            variable_count = 0
        entries.append(
            {
                "session_id": child.name,
                "size_bytes": _dir_size(child),
                "variable_count": variable_count,
            }
        )
    return entries


def _load_manifest_directory(session_path: Path) -> VariableMap:
    manifest_path = session_path / MANIFEST_NAME
    if manifest_path.is_file():
        with open(manifest_path, "r", encoding="utf-8") as handle:
            manifest = json.load(handle)
        raw_items = manifest.get("variables") or manifest.get("items", [])
        if isinstance(raw_items, list):
            loaded: VariableMap = {}
            for entry in raw_items:
                if not isinstance(entry, dict):
                    continue
                var_name = str(entry.get("name") or entry.get("label") or "").strip()
                file_name = str(entry.get("file", "")).strip()
                if not var_name or not file_name:
                    continue
                parquet_path = session_path / file_name
                if parquet_path.is_file():
                    loaded[var_name] = pd.read_parquet(parquet_path)
            if loaded:
                return loaded

    loaded: VariableMap = {}
    for parquet_path in sorted(session_path.glob("*.parquet")):
        try:
            loaded[parquet_path.stem] = pd.read_parquet(parquet_path)
        except Exception as exc:
            logger.warning("Failed to read %s: %s", parquet_path, exc)
    return loaded


def export_variables_to_path(path: Path, variables: VariableMap) -> int:
    """Export DataFrame variables to a .parquet file or folder with manifest."""
    target = Path(path)
    if not variables:
        return 0

    if target.suffix.lower() == ".parquet" and len(variables) == 1:
        name, frame = next(iter(variables.items()))
        frame.to_parquet(target, index=False, compression=PARQUET_COMPRESSION)
        return 1

    target.mkdir(parents=True, exist_ok=True)
    manifest_items: List[dict[str, str]] = []
    for index, (var_name, frame) in enumerate(variables.items()):
        file_name = f"{index}.parquet"
        frame.to_parquet(
            target / file_name,
            index=False,
            compression=PARQUET_COMPRESSION,
        )
        manifest_items.append({"name": var_name, "file": file_name})

    manifest = {"version": 2, "variables": manifest_items}
    with open(target / MANIFEST_NAME, "w", encoding="utf-8") as handle:
        json.dump(manifest, handle, ensure_ascii=False)
    return len(variables)


def import_variables_from_path(path: Path) -> VariableMap:
    """Load DataFrame variables from a parquet file or snapshot folder."""
    source = Path(path)
    if not source.exists():
        return {}

    if source.is_file() and source.suffix.lower() == ".parquet":
        return {source.stem: pd.read_parquet(source)}

    if source.is_dir():
        return _load_manifest_directory(source)

    return {}


def extract_dataframe_variables(namespace: Dict[str, Any]) -> List[ResultItem]:
    """Collect user DataFrame variables from a session namespace."""
    if not namespace:
        return []

    items: List[ResultItem] = []
    for name, value in namespace.items():
        if not name or str(name).startswith("_") or name in SKIP_VARIABLE_NAMES:
            continue
        frame = _to_pandas_dataframe(value)
        if frame is not None:
            items.append((str(name), frame))
    return items


class SessionResultStorage:
    """Read/write session DataFrame variables as compact Parquet files."""

    @staticmethod
    def delete(session_id: str) -> None:
        path = _session_dir(session_id)
        if path.exists():
            try:
                shutil.rmtree(path)
            except OSError as exc:
                logger.warning("Failed to delete session variables for %s: %s", session_id, exc)

    @staticmethod
    def load(session_id: str, *, require_enabled: bool = True) -> Optional[VariableMap]:
        if require_enabled and not is_session_result_restore_enabled():
            return None

        if not has_persisted_snapshot(session_id):
            return None

        session_path = _session_dir(session_id)
        try:
            loaded = _load_manifest_directory(session_path)
        except Exception as exc:
            logger.warning("Invalid session variable snapshot for %s: %s", session_id, exc)
            SessionResultStorage.delete(session_id)
            return None

        return loaded or None

    @staticmethod
    def save(session_id: str, items: List[ResultItem]) -> bool:
        if not is_session_result_restore_enabled():
            return False
        if not items:
            SessionResultStorage.delete(session_id)
            return True

        session_path = _session_dir(session_id)
        storage_root = _storage_root()
        temp_path = storage_root / f".{session_id}.{uuid.uuid4().hex}.tmp"

        try:
            if temp_path.exists():
                shutil.rmtree(temp_path, ignore_errors=True)
            temp_path.mkdir(parents=True, exist_ok=True)

            manifest_items: List[dict[str, str]] = []
            for index, (var_name, df) in enumerate(items):
                file_name = f"{index}.parquet"
                parquet_path = temp_path / file_name
                frame = df if isinstance(df, pd.DataFrame) else pd.DataFrame(df)
                frame.to_parquet(
                    parquet_path,
                    index=False,
                    compression=PARQUET_COMPRESSION,
                )
                manifest_items.append({"name": var_name, "file": file_name})

            manifest = {
                "version": 2,
                "session_id": session_id,
                "workspace": _current_workspace_path(),
                "variables": manifest_items,
            }
            with open(temp_path / MANIFEST_NAME, "w", encoding="utf-8") as handle:
                json.dump(manifest, handle, ensure_ascii=False)

            size_bytes = _dir_size(temp_path)
            max_bytes = get_session_result_max_size_bytes()
            if size_bytes > max_bytes:
                logger.info(
                    "Session %s variables (%d bytes) exceed limit (%d bytes); skipping persist",
                    session_id,
                    size_bytes,
                    max_bytes,
                )
                shutil.rmtree(temp_path)
                return False

            if session_path.exists():
                shutil.rmtree(session_path, ignore_errors=True)
            temp_path.replace(session_path)
            return True
        except Exception as exc:
            logger.warning("Failed to persist session variables for %s: %s", session_id, exc)
            if temp_path.exists():
                shutil.rmtree(temp_path, ignore_errors=True)
            return False

    @staticmethod
    def save_from_namespace(session_id: str, namespace: Dict[str, Any]) -> bool:
        return SessionResultStorage.save(session_id, extract_dataframe_variables(namespace))

    @staticmethod
    def save_from_namespace_async(session_id: str, namespace: Dict[str, Any]) -> None:
        if not is_session_result_restore_enabled():
            return

        items = extract_dataframe_variables(namespace)
        if not items:
            SessionResultStorage.delete(session_id)
            return

        payload: List[ResultItem] = []
        for name, df in items:
            try:
                payload.append((name, df.copy()))
            except Exception:
                payload.append((name, df))

        def _worker() -> None:
            SessionResultStorage.save(session_id, payload)

        threading.Thread(
            target=_worker,
            name=f"session-variables-{session_id}",
            daemon=True,
        ).start()
