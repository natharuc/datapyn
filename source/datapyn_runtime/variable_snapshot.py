"""Opt-in Parquet snapshots, isolated by workspace with an atomic generation pointer."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import time
import uuid

from .data_tools import atomic_destination, RUNTIME_VARIABLES
from .values import describe_variables
from src.utils.data_formats import PARQUET_COMPRESSION

METHODS = frozenset({"snapshot.settings.get", "snapshot.settings.set", "snapshot.list", "snapshot.save", "snapshot.restore", "snapshot.delete"})
DEFAULT_SETTINGS = {"enabled": False, "restore_on_startup": True, "max_size_mb": 50}


def _workspace():
    return Path(os.environ.get("DATAPYN_WORKSPACE_PATH", str(Path.home() / ".datapyn-tauri-preview"))).expanduser().resolve()


def _root():
    workspace = hashlib.sha256(str(_workspace()).encode()).hexdigest()[:24]
    base = os.environ.get("DATAPYN_SNAPSHOT_ROOT")
    if not base:
        cache = os.environ.get("LOCALAPPDATA") if os.name == "nt" else os.environ.get("XDG_CACHE_HOME", str(Path.home() / ".cache"))
        base = str(Path(cache or str(Path.home() / ".cache")) / "DataPynTauriPreview" / "session_snapshots")
    path = (Path(base).expanduser().resolve() / workspace)
    path.mkdir(parents=True, exist_ok=True)
    return path


def settings_get(params=None):
    path = _workspace() / "snapshot_settings.json"
    settings = dict(DEFAULT_SETTINGS)
    if path.is_file():
        value = json.loads(path.read_text(encoding="utf-8"))
        settings.update({key: value[key] for key in DEFAULT_SETTINGS if key in value})
    return _normalize(settings)


def _normalize(value):
    if not isinstance(value, dict):
        raise ValueError("Snapshot settings must be an object")
    size = value.get("max_size_mb", 50)
    if isinstance(size, bool) or not isinstance(size, int) or not 1 <= size <= 10_000:
        raise ValueError("Snapshot limit must be between 1 and 10000 MiB")
    return {"enabled": bool(value.get("enabled", False)), "restore_on_startup": bool(value.get("restore_on_startup", True)), "max_size_mb": size}


def settings_set(params):
    settings = _normalize(params.get("settings", params))
    path = _workspace() / "snapshot_settings.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    with atomic_destination(path) as temporary:
        temporary.write_text(json.dumps(settings), encoding="utf-8")
    return settings


def _session_path(session_id, create=False):
    if not isinstance(session_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", session_id):
        raise ValueError("Invalid snapshot session ID")
    root = _root().resolve()
    path = (root / session_id).resolve()
    if path.parent != root:
        raise ValueError("Snapshot path must stay inside the cache")
    if create:
        path.mkdir(exist_ok=True)
    return path


def _safe_remove(path, parent):
    target, parent = path.resolve(), parent.resolve()
    if target == parent or parent not in target.parents:
        raise ValueError("Refusing to remove a path outside the snapshot cache")
    if target.exists():
        shutil.rmtree(target)


def _current(session_id):
    session = _session_path(session_id)
    pointer = session / "current.json"
    if not pointer.is_file():
        return None
    generation = json.loads(pointer.read_text())["generation"]
    if not re.fullmatch(r"g-[0-9a-f]{32}", generation):
        raise ValueError("Invalid snapshot generation")
    path = (session / generation).resolve()
    if path.parent != session.resolve():
        raise ValueError("Invalid snapshot path")
    manifest = json.loads((path / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("workspace") != str(_workspace()) or manifest.get("session_id") != session_id:
        raise ValueError("Snapshot belongs to another workspace or session")
    return path, manifest


def list_snapshots(params=None):
    entries = []
    session_id = (params or {}).get("session_id")
    sessions = [_session_path(session_id)] if session_id else [path for path in _root().iterdir() if path.is_dir() and re.fullmatch(r"[A-Za-z0-9_-]{1,128}", path.name)]
    for session in sessions:
        try:
            current = _current(session.name)
            if current:
                _, manifest = current
                entries.append({"session_id": session.name, "saved_at": manifest["saved_at"], "size_bytes": manifest["size_bytes"],
                                "variables": [{key: item[key] for key in ("name", "kind", "row_count", "size_bytes")} for item in manifest["variables"]]})
        except (ValueError, KeyError, OSError, json.JSONDecodeError):
            entries.append({"session_id": session.name, "error": "Snapshot metadata is invalid; restore is unavailable"})
    return {"root": str(_root()), "snapshots": entries, "settings": settings_get()}


def save(params, namespace, store):
    settings = settings_get()
    if not settings["enabled"]:
        return {"saved": False, "reason": "disabled", "variables": []}
    session = _session_path(params["session_id"], create=True)
    max_bytes = settings["max_size_mb"] * 1024 * 1024
    frames = [(name, value) for name, value in namespace.items() if not name.startswith("_") and name not in RUNTIME_VARIABLES and store.is_frame(value)]
    if not frames:
        delete(params)
        return {"saved": True, "variables": [], "size_bytes": 0}
    generation = session / f"g-{uuid.uuid4().hex}"
    generation.mkdir()
    items, skipped, size_bytes = [], [], 0
    try:
        for index, (name, value) in enumerate(frames):
            if isinstance(value, store.pd.Series):
                frame, kind = value.to_frame(), "pandas_series"
            elif isinstance(value, store.pl.Series):
                frame, kind = value.to_frame(), "polars_series"
            elif isinstance(value, store.pl.DataFrame):
                frame, kind = value, "polars_frame"
            else:
                frame, kind = value, "pandas_frame"
            native = kind.startswith("polars_")
            memory_size = frame.estimated_size() if native else int(frame.memory_usage(deep=False).sum())
            if memory_size > max_bytes * 10:
                skipped.append({"name": name, "reason": "memory_limit"})
                continue
            file = generation / f"frame-{index:06d}.parquet"
            try:
                if native:
                    frame.write_parquet(file, compression=PARQUET_COMPRESSION)
                else:
                    frame.to_parquet(file, index=True, compression=PARQUET_COMPRESSION)
            except Exception:
                file.unlink(missing_ok=True)
                skipped.append({"name": name, "reason": "unsupported_parquet_type"})
                continue
            file_size = file.stat().st_size
            size_bytes += file_size
            if size_bytes > max_bytes:
                return {"saved": False, "reason": "size_limit", "size_bytes": size_bytes, "variables": [], "skipped": skipped}
            items.append({"name": name, "file": file.name, "kind": kind, "row_count": len(frame), "size_bytes": file_size,
                          "storage": "polars" if native else "pandas",
                          "series_name": value.name if kind == "pandas_series" else None})
        manifest = {"version": 2, "session_id": params["session_id"], "workspace": str(_workspace()), "saved_at": time.time(),
                    "variables": items, "size_bytes": size_bytes}
        (generation / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
        with atomic_destination(session / "current.json") as temporary:
            temporary.write_text(json.dumps({"generation": generation.name}), encoding="utf-8")
        for old in session.iterdir():
            if old.is_dir() and old != generation and re.fullmatch(r"g-[0-9a-f]{32}", old.name):
                _safe_remove(old, session)
        return {"saved": True, "size_bytes": size_bytes, "variables": items, "skipped": skipped}
    finally:
        pointer = session / "current.json"
        active = json.loads(pointer.read_text()).get("generation") if pointer.is_file() else None
        if active != generation.name:
            _safe_remove(generation, session)


def _pandas_frame(table, pd):
    import pyarrow as arrow
    frame = table.to_pandas(integer_object_nulls=True)
    metadata = table.schema.pandas_metadata or {}
    columns = {item["field_name"]: item for item in metadata.get("columns", [])}
    index_columns = metadata.get("index_columns", [])
    repaired = {}
    for level, field in enumerate(index_columns):
        if not isinstance(field, str):
            continue
        column = table[field]
        if arrow.types.is_integer(column.type) and column.null_count:
            # Arrow's index reconstruction separately infers float64 from
            # nullable ints, even when data columns use integer_object_nulls.
            values = column.to_pandas(integer_object_nulls=True)
            dtype = columns.get(field, {}).get("numpy_type", "object")
            if dtype not in {"Int8", "Int16", "Int32", "Int64", "UInt8", "UInt16", "UInt32", "UInt64"} and not dtype.endswith("[pyarrow]"):
                dtype = object
            repaired[level] = pd.Index(values, dtype=dtype, name=frame.index.names[level])
    if repaired:
        if len(index_columns) == 1:
            frame.index = repaired[0]
        else:
            levels = [repaired.get(level, frame.index.get_level_values(level)) for level in range(len(index_columns))]
            frame.index = pd.MultiIndex.from_arrays(levels, names=frame.index.names)
    return frame


def restore(params, namespace, store):
    if not settings_get()["enabled"]:
        return {"restored": False, "reason": "disabled", "results": [], "variables": describe_variables(namespace)}
    current = _current(params["session_id"])
    if not current:
        return {"restored": False, "reason": "not_found", "results": [], "variables": describe_variables(namespace)}
    path, manifest = current
    results, skipped = [], []
    prepared = []
    for item in manifest["variables"]:
        name = item["name"]
        if not isinstance(name, str) or not name.isidentifier() or name.startswith("_") or name in RUNTIME_VARIABLES:
            raise ValueError("Invalid snapshot variable name")
        file_name = item["file"]
        if not isinstance(file_name, str) or not re.fullmatch(r"frame-\d{6}\.parquet", file_name):
            raise ValueError("Invalid snapshot frame path")
        file = (path / file_name).resolve()
        if file.parent != path or file.stat().st_size > 1024 * 1024 * 1024:
            raise ValueError("Invalid snapshot frame")
        if name in namespace and not params.get("overwrite", False):
            skipped.append(name)
            continue
        kind = item.get("kind", "pandas_frame")
        if item.get("storage") == "polars":
            if kind not in {"polars_frame", "polars_series"}:
                raise ValueError("Invalid native snapshot kind")
            value = store.pl.read_parquet(file)
        else:
            # Nullable object integers become float64 in read_parquet's default
            # conversion, rounding values above 2**53 before paging can see them.
            # Arrow keeps the exact integers while preserving pandas index/dtype
            # metadata. Legacy Polars files were written through pandas as well.
            import pyarrow.parquet as parquet
            table = parquet.read_table(file)
            if kind.startswith("polars_"):
                value = store.pl.from_pandas(table.to_pandas(types_mapper=store.pd.ArrowDtype))
            else:
                value = _pandas_frame(table, store.pd)
        if kind == "pandas_series":
            value = value.iloc[:, 0]
            value.name = item.get("series_name")
        elif kind == "polars_series":
            value = value.to_series()
        prepared.append((name, value))
    for name, value in prepared:
        namespace[name] = value
        results.append(store.register(value, name))
    return {"restored": True, "results": results, "variables": describe_variables(namespace), "skipped": skipped}


def delete(params):
    path = _session_path(params["session_id"])
    _safe_remove(path, _root())
    return {"deleted": True, "session_id": params["session_id"]}


def dispatch(method, params, namespace=None, store=None):
    if method == "snapshot.settings.get":
        return settings_get(params)
    if method == "snapshot.settings.set":
        return settings_set(params)
    if method == "snapshot.list":
        return list_snapshots(params)
    if method == "snapshot.save":
        return save(params, namespace, store)
    if method == "snapshot.restore":
        return restore(params, namespace, store)
    if method == "snapshot.delete":
        return delete(params)
    raise ValueError(f"Unknown snapshot operation: {method}")
