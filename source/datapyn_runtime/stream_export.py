"""Bounded SQL downloads using the existing driver stream writers.

All result sets are staged beside the chosen destination. A failed or cancelled
query never truncates that destination, and generated extra filenames do not
replace existing files unless the caller explicitly permits that overwrite.
"""

from __future__ import annotations

import codecs
import json
import os
from pathlib import Path
import re
import sqlite3
import shutil
import uuid

from src.database.query_stream_exporter import (
    STREAM_EXPORT_CHUNK_ROWS,
    StreamExportResult,
    iter_rows_chunked,
    make_result_path,
    normalize_csv_options,
    stream_result_set_to_file,
)


def _destination(value, export_format):
    if export_format not in {"csv", "parquet"}:
        raise ValueError("Streaming downloads support CSV or Parquet")
    if not isinstance(value, (str, Path)) or not str(value).strip():
        raise ValueError("Choose a destination file")
    path = Path(value).expanduser().resolve()
    if not path.parent.is_dir():
        raise FileNotFoundError("The destination directory does not exist")
    if path.is_dir():
        raise ValueError("The destination must be a file")
    if path.suffix.lower() != "." + export_format:
        raise ValueError(f"Choose a .{export_format} destination")
    return path


def _options(value):
    if value is not None and not isinstance(value, dict):
        raise ValueError("Download options must be an object")
    options = dict(value or {})
    csv = normalize_csv_options(options)
    if not isinstance(csv["sep"], str) or len(csv["sep"]) != 1 or csv["sep"] in "\r\n\0":
        raise ValueError("The CSV delimiter must be one printable character")
    if csv["decimal"] not in {".", ","}:
        raise ValueError("Choose a dot or comma decimal separator")
    codecs.lookup(csv["encoding"])
    if not isinstance(csv["header"], bool):
        raise ValueError("CSV header must be enabled or disabled")
    token = options.get("stage_id") or uuid.uuid4().hex
    if not isinstance(token, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", token):
        raise ValueError("Invalid download staging identifier")
    return options, csv, token


def _stage_base(destination, token):
    return destination.parent / f".datapyn-export-{token}{destination.suffix}"


def cleanup(path, stage_id):
    """The supervisor can clean this request's stages after killing its kernel."""
    destination = Path(path).expanduser().resolve()
    if not isinstance(stage_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", stage_id):
        raise ValueError("Invalid download staging identifier")
    prefix = f".datapyn-export-{stage_id}"
    _recover_commit(destination, stage_id)
    for item in destination.parent.glob(f"{prefix}*"):
        # Exact token boundary prevents one request from deleting another.
        if re.fullmatch(re.escape(prefix) + r"(?:_\d+)?(?:-upgrade-[A-Za-z0-9_-]+)?\.(?:csv|parquet)", item.name):
            if item.parent.resolve() != destination.parent or item.is_symlink():
                continue
            if item.is_file():
                item.unlink(missing_ok=True)


def _journal_path(destination, token):
    return destination.parent / f".datapyn-export-{token}.journal.json"


def _write_journal(path, journal):
    temporary = path.with_suffix(".tmp")
    with temporary.open("w", encoding="utf-8") as output:
        json.dump(journal, output, ensure_ascii=False)
        output.flush()
        os.fsync(output.fileno())
    os.replace(temporary, path)


def _recover_commit(destination, token):
    journal_path = _journal_path(destination, token)
    if not journal_path.exists():
        journal_path.with_suffix(".tmp").unlink(missing_ok=True)
        return
    if journal_path.is_symlink() or journal_path.stat().st_size > 1024 * 1024:
        raise ValueError("Invalid download commit journal")
    journal = json.loads(journal_path.read_text(encoding="utf-8"))
    phase, entries = journal.get("phase"), journal.get("files")
    if phase not in {"preparing", "ready", "committed"} or not isinstance(entries, list) or not 2 <= len(entries) <= 1000:
        raise ValueError("Invalid download commit journal")
    validated = []
    for index, entry in enumerate(entries, start=1):
        target = make_result_path(destination, index, destination.suffix.lstrip("."))
        backup = destination.parent / f".datapyn-backup-{token}_{index}{destination.suffix}"
        if not isinstance(entry, dict) or entry.get("target") != target.name or entry.get("backup") != backup.name or not isinstance(entry.get("had_original"), bool):
            raise ValueError("Invalid download commit journal paths")
        if target.is_symlink() or backup.is_symlink():
            raise ValueError("Invalid download commit journal paths")
        validated.append((target, backup, entry["had_original"]))
    if phase == "ready":
        # Every backup is complete before this phase can be published. Replace
        # originals atomically, including after a hard kernel/process kill.
        for target, backup, had_original in validated:
            if had_original:
                if backup.exists():
                    os.replace(backup, target)
                elif not target.exists():
                    raise RuntimeError("The original download file could not be recovered")
            else:
                target.unlink(missing_ok=True)
    for _, backup, _ in validated:
        backup.unlink(missing_ok=True)
    journal_path.unlink(missing_ok=True)
    journal_path.with_suffix(".tmp").unlink(missing_ok=True)


def _commit(stages, destinations, overwrite_additional, token):
    for index, target in enumerate(destinations):
        if target.is_symlink():
            raise ValueError("Generated result filenames cannot overwrite symbolic links")
        if target.exists() and (target.is_dir() or (index > 0 and not overwrite_additional)):
            raise FileExistsError(f"An additional result file already exists: {target.name}. Choose another destination.")
    if not stages:
        return
    if len(stages) == 1:
        # Replacing one file is a single atomic operation: the old destination
        # remains present until the complete stage replaces it.
        os.replace(stages[0], destinations[0])
        return
    if len(stages) > 1000:
        raise ValueError("A download supports at most 1000 result files")
    destination = destinations[0]
    journal_path = _journal_path(destination, token)
    journal = {"phase": "preparing", "files": [
        {"target": target.name, "backup": f".datapyn-backup-{token}_{index}{destination.suffix}", "had_original": target.exists()}
        for index, target in enumerate(destinations, start=1)]}
    _write_journal(journal_path, journal)
    try:
        for target, entry in zip(destinations, journal["files"]):
            if entry["had_original"]:
                shutil.copyfile(target, destination.parent / entry["backup"])
        journal["phase"] = "ready"
        _write_journal(journal_path, journal)
        pairs = list(zip(stages, destinations))
        # Additional results first; the explicitly chosen primary file last.
        for staged, target in [*pairs[1:], pairs[0]]:
            os.replace(staged, target)
        journal["phase"] = "committed"
        _write_journal(journal_path, journal)
    except BaseException:
        _recover_commit(destination, token)
        raise
    _recover_commit(destination, token)


def _sqlite_statements(query):
    buffer = ""
    for character in query:
        buffer += character
        if character == ";" and sqlite3.complete_statement(buffer):
            yield buffer
            buffer = ""
    if buffer.strip():
        yield buffer


def _sqlite_stream(connector, query, base, export_format, parameters, csv_options,
                   progress, is_cancelled):
    if isinstance(parameters, list):
        from src.utils.sql_parameter_service import prepare_generic_sql

        prepared = prepare_generic_sql(query, parameters)
        query, parameters = prepared.query, prepared.params
    result = StreamExportResult()
    try:
        for statement in _sqlite_statements(query):
            if is_cancelled and is_cancelled():
                result.cancelled = True
                break
            cursor = connector.connection.execute(statement, parameters or {})
            try:
                if not cursor.description:
                    continue
                columns = [column[0] for column in cursor.description]
                index = len(result.files) + 1
                staged = make_result_path(base, index, export_format)
                rows = 0

                def on_chunk(count):
                    nonlocal rows
                    rows += count
                    progress(index, rows, staged.stat().st_size if staged.exists() else 0)

                count = stream_result_set_to_file(
                    columns, iter_rows_chunked(cursor, STREAM_EXPORT_CHUNK_ROWS),
                    path=staged, export_format=export_format, csv_options=csv_options,
                    on_chunk=on_chunk, is_cancelled=is_cancelled,
                )
                if count < 0 or (is_cancelled and is_cancelled()):
                    result.cancelled = True
                    break
                result.files.append(staged)
                result.row_counts.append(count)
                result.columns_per_file.append(columns)
            finally:
                cursor.close()
        if result.cancelled:
            connector.connection.rollback()
        else:
            connector.connection.commit()
    except BaseException:
        connector.connection.rollback()
        raise
    return result


def run(connector, query, *, path, export_format="csv", parameters=None,
        options=None, on_progress=None, is_cancelled=None):
    """Execute and stream SQL; ``on_progress`` receives JSON-safe dictionaries."""
    if connector is None:
        raise ConnectionError("Connect this block to a database first")
    if not isinstance(query, str) or not query.strip():
        raise ValueError("Enter a SQL query to download")
    destination = _destination(path, export_format)
    options, csv_options, token = _options(options)
    base = _stage_base(destination, token)
    if any(destination.parent.glob(f".datapyn-export-{token}*")):
        raise FileExistsError("This download staging identifier is already in use")
    progress_rows = {}

    def progress(index, rows, size_bytes):
        progress_rows[index] = rows
        if on_progress:
            on_progress({"file_index": index, "path": str(make_result_path(destination, index, export_format)),
                         "rows": rows, "size_bytes": size_bytes, "total_rows": sum(progress_rows.values())})

    try:
        if hasattr(connector, "stream_query_to_files"):
            result = connector.stream_query_to_files(
                query, base_path=base, export_format=export_format, parameters=parameters,
                csv_options=csv_options, on_progress=progress, is_cancelled=is_cancelled,
            )
        elif getattr(connector, "db_type", None) == "sqlite" and hasattr(connector, "connection"):
            result = _sqlite_stream(connector, query, base, export_format, parameters, csv_options,
                                    progress, is_cancelled)
        else:
            raise TypeError("This database driver does not support streaming downloads")
        if result.cancelled or (is_cancelled and is_cancelled()):
            return {"files": [], "total_rows": 0, "cancelled": True, "errors": list(result.errors)}
        if result.errors:
            raise RuntimeError("; ".join(result.errors))
        final_paths = [make_result_path(destination, index, export_format) for index in range(1, len(result.files) + 1)]
        _commit(result.files, final_paths, bool(options.get("overwrite_additional", False)), token)
        files = [{"path": str(final), "rows": rows, "columns": columns, "size_bytes": final.stat().st_size}
                 for final, rows, columns in zip(final_paths, result.row_counts, result.columns_per_file)]
        return {"files": files, "total_rows": result.total_rows, "cancelled": False, "errors": []}
    finally:
        cleanup(destination, token)
