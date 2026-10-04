"""Public Parquet packages compatible with the PyQt manifest v2 format.

Frames stay in the session kernel. Every source is validated/read before an
import changes the namespace; exports publish the manifest only after all files
are written and roll back an interrupted publication.
"""

from __future__ import annotations

import json
import keyword
import os
from pathlib import Path
import re
import tempfile

from .values import describe_variables
from .export_control import ExportControl, ExportCancelled
from src.utils.data_formats import PARQUET_COMPRESSION

METHODS = frozenset({"variable.archive.list", "variable.archive.export", "variable.archive.import"})
MAX_VARIABLES = 10_000
MAX_MANIFEST_BYTES = 4 * 1024 * 1024
RESERVED = frozenset({"pd", "np", "pl", "plt", "display", "db_engine", "db_type", "db_database", "db_host", "db_username"})


def _name(name):
    if not isinstance(name, str) or not name.isidentifier() or keyword.iskeyword(name) or name.startswith("_") or name in RESERVED:
        raise ValueError("Use a valid public Python variable name")
    return name


def _path(value):
    if not isinstance(value, str) or not value.strip():
        raise ValueError("Choose a Parquet file or package directory")
    path = Path(value).expanduser()
    if path.is_symlink():
        raise ValueError("Choose a regular file or directory")
    return path.resolve()


def _kind(value, store):
    if isinstance(value, store.pd.DataFrame):
        return "pandas_frame"
    if isinstance(value, store.pd.Series):
        return "pandas_series"
    if isinstance(value, store.pl.DataFrame):
        return "polars_frame"
    if isinstance(value, store.pl.Series):
        return "polars_series"
    return None


def list_variables(namespace, store):
    variables = []
    for name, value in namespace.items():
        try:
            _name(name)
        except ValueError:
            continue
        kind = _kind(value, store)
        if kind:
            variables.append({"name": name, "type": type(value).__name__, "kind": kind,
                              "row_count": len(value), "column_count": 1 if kind.endswith("series") else len(value.columns)})
            if len(variables) > MAX_VARIABLES:
                raise ValueError(f"A package supports at most {MAX_VARIABLES:,} variables")
    return {"variables": variables, "total": len(variables)}


def _overwrite(params):
    overwrite = params.get("overwrite", False)
    if not isinstance(overwrite, bool):
        raise ValueError("overwrite must be enabled or disabled")
    return overwrite


def _selected(params, namespace, store):
    names = params.get("names")
    if names is None:
        names = [item["name"] for item in list_variables(namespace, store)["variables"]]
    if not isinstance(names, list) or not 1 <= len(names) <= MAX_VARIABLES:
        raise ValueError("Select at least one DataFrame or Series")
    selected = []
    seen = set()
    for name in names:
        _name(name)
        if name in seen:
            raise ValueError("Select each variable only once")
        seen.add(name)
        if name not in namespace or not _kind(namespace[name], store):
            raise ValueError(f"Variable is unavailable or is not a DataFrame/Series: {name}")
        selected.append((name, namespace[name], _kind(namespace[name], store)))
    return selected


def _check_cancel(is_cancelled):
    if is_cancelled and is_cancelled():
        raise ExportCancelled("Variable export cancelled")


def _write_frame(value, kind, path, store):
    if kind.startswith("polars"):
        # Native Polars Parquet avoids copying a second pandas frame.
        frame = value.to_frame() if kind.endswith("series") else value
        frame.write_parquet(path, compression=PARQUET_COMPRESSION)
    else:
        frame = value.to_frame() if kind.endswith("series") else value
        frame.to_parquet(path, index=False, compression=PARQUET_COMPRESSION)


def _publish(stage, destination, filenames, overwrite, is_cancelled):
    created = not destination.exists()
    destination.mkdir(exist_ok=True)
    backups = stage / "originals"
    backups.mkdir()
    published = []
    try:
        for filename in filenames:
            target = destination / filename
            if target.is_symlink() or target.is_dir():
                raise ValueError(f"The destination is not a regular file: {filename}")
            if target.exists() and not overwrite:
                raise FileExistsError(f"The package destination already contains {filename}")
        for filename in filenames:
            _check_cancel(is_cancelled)
            target = destination / filename
            original = backups / filename
            if target.exists() and not overwrite:
                raise FileExistsError(f"The package destination already contains {filename}")
            if target.exists():
                os.replace(target, original)
            published.append((target, original))
            os.replace(stage / filename, target)
    except BaseException:
        for target, original in reversed(published):
            if original.exists():
                os.replace(original, target)
            else:
                target.unlink(missing_ok=True)
        if created:
            try:
                destination.rmdir()
            except OSError:
                pass
        raise


def export_variables(params, namespace, store, *, progress=None, cancelled=None):
    selected = _selected(params, namespace, store)
    destination, overwrite = _path(params.get("path")), _overwrite(params)
    if not destination.parent.is_dir():
        raise FileNotFoundError("The destination parent directory does not exist")
    single = destination.suffix.lower() == ".parquet"
    if single and len(selected) != 1:
        raise ValueError("Choose a directory to export multiple variables")
    if single and destination.exists() and not overwrite:
        raise FileExistsError("The destination file already exists")
    if (single and destination.is_dir()) or (not single and destination.exists() and not destination.is_dir()):
        raise ValueError("Choose a Parquet file or package directory")
    if not single and destination.exists():
        # Reject collisions before spending time encoding a large notebook.
        for filename in [f"{index}.parquet" for index in range(len(selected))] + ["manifest.json"]:
            target = destination / filename
            if target.is_symlink() or target.is_dir():
                raise ValueError(f"The destination is not a regular file: {filename}")
            if target.exists() and not overwrite:
                raise FileExistsError(f"The package destination already contains {filename}")
    control = ExportControl(len(selected), progress, cancelled)
    with tempfile.TemporaryDirectory(prefix=".datapyn-archive-", dir=destination.parent) as directory:
        stage = Path(directory)
        entries = []
        for index, (name, value, kind) in enumerate(selected):
            control.check()
            filename = f"{index}.parquet"
            _write_frame(value, kind, stage / filename, store)
            entry = {"name": name, "file": filename}
            # Extra keys are ignored by the PyQt reader. A plain pandas frame
            # retains the exact legacy entry; other kinds can restore their type.
            if kind != "pandas_frame":
                entry["kind"] = kind
                if kind.endswith("series"):
                    series_name = value.name
                    if series_name is None or isinstance(series_name, (str, int, float, bool)):
                        entry["series_name"] = series_name
            entries.append(entry)
            control.advance(index + 1)
        control.check()
        size = sum((stage / entry["file"]).stat().st_size for entry in entries)
        if single:
            if destination.exists() and not overwrite:
                raise FileExistsError("The destination file already exists")
            os.replace(stage / "0.parquet", destination)
        else:
            (stage / "manifest.json").write_text(json.dumps({"version": 2, "variables": entries}, ensure_ascii=False, indent=2), encoding="utf-8")
            _publish(stage, destination, [entry["file"] for entry in entries] + ["manifest.json"], overwrite, control.check)
    control.complete()
    return {"path": str(destination), "names": [name for name, _, _ in selected], "count": len(selected), "size_bytes": size}


def _file_name(path):
    name = re.sub(r"\W+", "_", path.stem.lower(), flags=re.UNICODE).strip("_") or "df"
    if name[0].isdigit() or keyword.iskeyword(name) or name in RESERVED:
        name = "df_" + name
    return _name(name)


def _read_entries(source, variable_name=None):
    if source.is_file():
        if source.suffix.lower() != ".parquet":
            raise ValueError("Choose a .parquet file or a package directory")
        return [{"name": _name(variable_name) if variable_name else _file_name(source), "file": source.name}], source.parent
    if not source.is_dir():
        raise FileNotFoundError("The package does not exist")
    manifest_path = source / "manifest.json"
    if manifest_path.exists():
        if manifest_path.is_symlink() or manifest_path.stat().st_size > MAX_MANIFEST_BYTES:
            raise ValueError("Invalid package manifest")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
        if not isinstance(manifest, dict) or manifest.get("version", 1) not in {1, 2}:
            raise ValueError("Unsupported package manifest")
        entries = manifest.get("variables") or manifest.get("items", [])
    else:
        entries = [{"name": _file_name(file), "file": file.name} for file in sorted(source.glob("*.parquet"))]
    if not isinstance(entries, list) or not 1 <= len(entries) <= MAX_VARIABLES:
        raise ValueError("The package must contain DataFrames or Series")
    return entries, source


def import_variables(params, namespace, store, *, progress=None, cancelled=None):
    source, overwrite = _path(params.get("path")), _overwrite(params)
    entries, root = _read_entries(source, params.get("variable_name"))
    validated, seen = [], set()
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError("Invalid package variable")
        name = _name(entry.get("name") or entry.get("label"))
        if name in seen:
            raise ValueError("Duplicate package variable name")
        seen.add(name)
        if name in namespace and not overwrite:
            raise ValueError(f"Variable already exists: {name}; enable overwrite to replace it")
        filename = entry.get("file")
        if not isinstance(filename, str) or not filename or "/" in filename or "\\" in filename or ":" in filename or filename in {".", ".."} or not filename.lower().endswith(".parquet"):
            raise ValueError("Invalid package frame path")
        file = root / filename
        if file.is_symlink() or not file.is_file() or file.resolve().parent != root:
            raise ValueError("Package frames must be regular files inside the package")
        kind = entry.get("kind", "pandas_frame")
        if kind not in {"pandas_frame", "pandas_series", "polars_frame", "polars_series"}:
            raise ValueError("Unsupported package variable kind")
        validated.append((name, file, kind, entry))
    prepared = []
    control = ExportControl(len(validated), progress, cancelled)
    for index, (name, file, kind, entry) in enumerate(validated):
        control.check()
        if kind.startswith("polars"):
            value = store.pl.read_parquet(file)
            if kind.endswith("series"):
                if value.width != 1:
                    raise ValueError("A Series package must contain exactly one column")
                value = value.to_series()
                if isinstance(entry.get("series_name"), str):
                    value = value.rename(entry["series_name"])
        else:
            value = store.pd.read_parquet(file)
            if kind.endswith("series"):
                if len(value.columns) != 1:
                    raise ValueError("A Series package must contain exactly one column")
                value = value.iloc[:, 0]
                value.name = entry.get("series_name")
        prepared.append((name, value))
        control.advance(index + 1)
    control.check()
    results = []
    # Only retained result handles can be returned. Every variable is imported;
    # the inspector can register another result lazily when the user opens it.
    from .kernel import MAX_RESULT_HANDLES
    for index, (name, value) in enumerate(prepared):
        namespace[name] = value
        if index >= len(prepared) - MAX_RESULT_HANDLES:
            results.append(store.register(value, name))
    control.complete()
    return {"names": [name for name, _ in prepared], "count": len(prepared), "results": results,
            "variables": describe_variables(namespace)}


def dispatch(method, params, namespace, store, **callbacks):
    if method == "variable.archive.list":
        return list_variables(namespace, store)
    if method == "variable.archive.export":
        return export_variables(params, namespace, store, **callbacks)
    if method == "variable.archive.import":
        return import_variables(params, namespace, store, **callbacks)
    raise ValueError(f"Unknown variable archive method: {method}")
