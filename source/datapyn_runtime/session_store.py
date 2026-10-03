"""Transactional private session drafts; public .dpw files remain unchanged."""

from __future__ import annotations

from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import tempfile
import threading
import time
import uuid

DATABASE_NAME = "workspace_sessions.sqlite3"
LEGACY_NAME = "workspace_state.json"
MAX_STATE_BYTES = 16 * 1024 * 1024
MAX_DOCUMENTS = 1000
SCHEMA_VERSION = 1
RESERVED_METADATA = frozenset({"documents", "saved_at"})
IDENTIFIER = re.compile(r"[A-Za-z0-9_-]{1,128}\Z")


class SessionStoreError(ValueError):
    """Do not replace an unreadable store with an empty workspace."""


def safe_wal_version(version=None):
    # https://www.sqlite.org/wal.html#walreset: the WAL-reset fix was backported
    # to 3.44.6 and 3.50.7; intervening branches remain affected.
    version = version or sqlite3.sqlite_version_info
    return version >= (3, 51, 3) or version[:2] == (3, 50) and version >= (3, 50, 7) or version[:2] == (3, 44) and version >= (3, 44, 6)


def _json(value):
    try:
        text = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError, RecursionError) as error:
        raise ValueError("Workspace data must be finite JSON") from error
    size = len(text.encode("utf-8"))
    if size > MAX_STATE_BYTES:
        raise ValueError("Workspace data exceeds 16 MiB")
    return text, hashlib.sha256(text.encode("utf-8")).hexdigest(), size


def _identifier(value):
    if not isinstance(value, str) or not IDENTIFIER.fullmatch(value):
        raise ValueError("Session IDs require 1 to 128 letters, numbers, underscores or hyphens")
    return value


def _decode(text, digest):
    if hashlib.sha256(text.encode("utf-8")).hexdigest() != digest:
        raise SessionStoreError("Session storage checksum failed; the existing files were preserved")
    try:
        return json.loads(text)
    except (TypeError, ValueError, RecursionError) as error:
        raise SessionStoreError("Session storage contains invalid JSON; the existing files were preserved") from error


def _metadata(value):
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        raise ValueError("Workspace metadata must be an object with string keys")
    if RESERVED_METADATA.intersection(value):
        raise ValueError("documents and saved_at are reserved metadata fields")
    if "activeIndex" in value:
        active = value["activeIndex"]
        if isinstance(active, bool) or not isinstance(active, int) or not 0 <= active < MAX_DOCUMENTS:
            raise ValueError("activeIndex must be between 0 and 999")
    for key in ("preferences", "shortcuts", "layout"):
        if key in value and not isinstance(value[key], dict):
            raise ValueError(f"{key} must be an object")
    return value


def _record(record, *, require_document=False):
    if not isinstance(record, dict):
        raise ValueError("Each open analysis requires a document record")
    _identifier(record.get("sessionId"))
    if require_document or "document" in record:
        if not isinstance(record.get("document"), dict):
            raise ValueError("Each open analysis requires its document object")
    if "title" in record and not isinstance(record["title"], str):
        raise ValueError("Analysis titles must be strings")
    removed = record.get("remove_header", [])
    if not isinstance(removed, list) or len(removed) > 4096 or any(not isinstance(key, str) or key in {"sessionId", "document", "remove_header"} for key in removed):
        raise ValueError("remove_header must list removable header fields")
    if any(key in record for key in removed):
        raise ValueError("A header field cannot be set and removed together")
    _json(record)
    return record


def normalize_state(value, seed, previous_order=()):
    if not isinstance(value, dict) or not isinstance(value.get("documents", []), list):
        raise ValueError("Workspace state requires a document list")
    if len(value.get("documents", [])) > MAX_DOCUMENTS:
        raise ValueError("Workspaces support at most 1000 open analyses")
    metadata = _metadata({key: item for key, item in value.items() if key not in RESERVED_METADATA})
    metadata.setdefault("activeIndex", 0)
    documents, seen = [], set()
    explicit_ids = {_identifier(record["sessionId"]) for record in value.get("documents", [])
                    if isinstance(record, dict) and record.get("sessionId")}
    for index, record in enumerate(value.get("documents", [])):
        if not isinstance(record, dict):
            raise ValueError("Each open analysis requires a document record")
        record = dict(record)
        if not record.get("sessionId"):
            # JSON-era drafts stored identity inside the public desktop extras.
            # Preserve it to retain association with private Parquet/Pynia data.
            payload = record.get("document")
            desktop = payload.get("desktop") if isinstance(payload, dict) else None
            embedded = desktop.get("session_id") if isinstance(desktop, dict) else None
            def available(identifier):
                return isinstance(identifier, str) and IDENTIFIER.fullmatch(identifier) and identifier not in seen and identifier not in explicit_ids
            if available(embedded):
                record["sessionId"] = embedded
            elif index < len(previous_order) and available(previous_order[index]):
                record["sessionId"] = previous_order[index]
            else:
                salt = 0
                identifier = uuid.uuid5(uuid.NAMESPACE_URL, f"datapyn:{seed}:{index}").hex
                while not available(identifier):
                    salt += 1
                    identifier = uuid.uuid5(uuid.NAMESPACE_URL, f"datapyn:{seed}:{index}:{salt}").hex
                record["sessionId"] = identifier
        _record(record, require_document=True)
        if record["sessionId"] in seen:
            raise ValueError("Open analyses must have unique session IDs")
        seen.add(record["sessionId"])
        documents.append(record)
    _json({**metadata, "documents": documents})
    return documents, metadata


@contextmanager
def _bootstrap_lock(path):
    """OS-released lock prevents two processes from publishing initial databases."""
    with path.open("a+b") as stream:
        if stream.seek(0, os.SEEK_END) == 0:
            stream.write(b"0"); stream.flush()
        stream.seek(0)
        if os.name == "nt":
            import msvcrt
            msvcrt.locking(stream.fileno(), msvcrt.LK_LOCK, 1)
        else:
            import fcntl
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            stream.seek(0)
            if os.name == "nt":
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


SCHEMA = """
CREATE TABLE documents(session_id TEXT PRIMARY KEY, payload_hash TEXT NOT NULL,
 payload_bytes INTEGER NOT NULL, updated_revision INTEGER NOT NULL, payload_json TEXT NOT NULL);
CREATE TABLE document_headers(session_id TEXT PRIMARY KEY REFERENCES documents(session_id) ON DELETE CASCADE,
 header_hash TEXT NOT NULL, header_bytes INTEGER NOT NULL, updated_revision INTEGER NOT NULL, header_json TEXT NOT NULL);
CREATE TABLE document_order(position INTEGER PRIMARY KEY, session_id TEXT NOT NULL UNIQUE REFERENCES documents(session_id) ON DELETE CASCADE);
CREATE TABLE workspace_metadata(key TEXT PRIMARY KEY, value_hash TEXT NOT NULL,
 value_bytes INTEGER NOT NULL, updated_revision INTEGER NOT NULL, value_json TEXT NOT NULL);
CREATE TABLE store_control(id INTEGER PRIMARY KEY CHECK(id=1), initialized INTEGER NOT NULL,
 revision INTEGER NOT NULL, saved_at REAL, document_count INTEGER NOT NULL,
 metadata_count INTEGER NOT NULL, stored_bytes INTEGER NOT NULL, order_hash TEXT NOT NULL,
 migration_source_hash TEXT);
INSERT INTO store_control VALUES(1,0,0,NULL,0,0,0,'',NULL);
PRAGMA user_version=1;
"""


@contextmanager
def _read_snapshot(connection):
    own_transaction = not connection.in_transaction
    if own_transaction:
        connection.execute("BEGIN")
    try:
        yield
    finally:
        if own_transaction:
            connection.rollback()


class SessionStore:
    def __init__(self, directory):
        self.directory = Path(directory).resolve()
        self.directory.mkdir(parents=True, exist_ok=True)
        self.path = self.directory / DATABASE_NAME
        self.lock = threading.RLock()
        with _bootstrap_lock(self.directory / (DATABASE_NAME + ".lock")):
            if not self.path.exists():
                self._bootstrap()
        if not self.path.is_file() or self.path.stat().st_size < 100:
            raise SessionStoreError("Session storage is incomplete; the existing files were preserved")
        try:
            self.connection = sqlite3.connect(self.path, timeout=5, isolation_level=None, check_same_thread=False)
            self.connection.row_factory = sqlite3.Row
            if self.connection.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                raise SessionStoreError("Session storage integrity failed; the existing files were preserved")
            if self.connection.execute("PRAGMA user_version").fetchone()[0] != SCHEMA_VERSION:
                raise SessionStoreError("Unsupported session storage version; the existing files were preserved")
            self.connection.execute("PRAGMA foreign_keys=ON")
            if self.connection.execute("PRAGMA foreign_key_check").fetchone() is not None:
                raise SessionStoreError("Session storage references are damaged; the existing files were preserved")
            self.journal_mode = self.connection.execute("PRAGMA journal_mode=" + ("WAL" if safe_wal_version() else "DELETE")).fetchone()[0]
            # FULL is durable in WAL; EXTRA also syncs journal deletion in
            # rollback mode (https://www.sqlite.org/pragma.html#pragma_synchronous).
            self.connection.execute("PRAGMA synchronous=" + ("FULL" if self.journal_mode == "wal" else "EXTRA"))
            self.connection.execute("PRAGMA busy_timeout=5000")
            self.connection.execute("PRAGMA wal_autocheckpoint=1000")
            with _read_snapshot(self.connection):
                self._verify()
        except (sqlite3.Error, SessionStoreError) as error:
            if hasattr(self, "connection"):
                self.connection.close()
            if isinstance(error, SessionStoreError):
                raise
            raise SessionStoreError("Session storage cannot be opened; the existing files were preserved") from error

    def _bootstrap(self):
        legacy = self.directory / LEGACY_NAME
        state, source_hash = None, None
        if legacy.exists():
            if not legacy.is_file() or legacy.stat().st_size > MAX_STATE_BYTES:
                raise SessionStoreError("The previous workspace draft is invalid or exceeds 16 MiB; it was preserved")
            try:
                content = legacy.read_bytes()
                state = json.loads(content.decode("utf-8-sig"))
                normalize_state(state, str(self.directory))
                source_hash = hashlib.sha256(content).hexdigest()
            except (ValueError, UnicodeError, RecursionError) as error:
                raise SessionStoreError("The previous workspace draft cannot be restored; it was preserved") from error
        handle, temporary = tempfile.mkstemp(prefix=f".{DATABASE_NAME}.boot-", suffix=".sqlite3", dir=self.directory)
        os.close(handle)
        temporary = Path(temporary)
        connection = sqlite3.connect(temporary, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=DELETE")
        connection.execute("PRAGMA synchronous=EXTRA")
        connection.execute("PRAGMA foreign_keys=ON")
        try:
            connection.executescript(SCHEMA)
            if state is not None:
                self._save(connection, state, source_hash=source_hash)
            connection.close()
            os.replace(temporary, self.path)
        finally:
            connection.close()
            temporary.unlink(missing_ok=True)
            Path(str(temporary) + "-journal").unlink(missing_ok=True)

    def _control(self, connection=None):
        connection = connection or self.connection
        row = connection.execute("SELECT * FROM store_control WHERE id=1").fetchone()
        if row is None:
            raise SessionStoreError("Session storage metadata is missing; the existing files were preserved")
        return row

    def _verify(self):
        control = self._control()
        counts = [self.connection.execute(f"SELECT count(*) FROM {table}").fetchone()[0] for table in ("documents", "document_headers", "document_order", "workspace_metadata")]
        if counts[:3] != [control["document_count"]] * 3 or counts[3] != control["metadata_count"] or control["document_count"] > MAX_DOCUMENTS:
            raise SessionStoreError("Session storage document counts are inconsistent; the existing files were preserved")
        if not control["initialized"] and any(counts):
            raise SessionStoreError("Session storage initialization is inconsistent; the existing files were preserved")

    def load(self):
        with self.lock, _read_snapshot(self.connection):
            try:
                self._verify()
                control = self._control()
                if not control["initialized"]:
                    return None
                rows = self.connection.execute("SELECT position,session_id FROM document_order ORDER BY position").fetchall()
                order = [row["session_id"] for row in rows]
                if [row["position"] for row in rows] != list(range(len(rows))) or _json(order)[1] != control["order_hash"]:
                    raise SessionStoreError("Session storage order is damaged; the existing files were preserved")
                documents = []
                for row in self.connection.execute("SELECT d.*,h.header_json,h.header_hash FROM document_order o JOIN documents d USING(session_id) JOIN document_headers h USING(session_id) ORDER BY o.position"):
                    header = _decode(row["header_json"], row["header_hash"])
                    payload = _decode(row["payload_json"], row["payload_hash"])
                    record = {**header, "document": payload}
                    _record(record, require_document=True)
                    if record["sessionId"] != row["session_id"]:
                        raise SessionStoreError("Session storage identity is damaged; the existing files were preserved")
                    documents.append(record)
                metadata = {row["key"]: _decode(row["value_json"], row["value_hash"]) for row in self.connection.execute("SELECT * FROM workspace_metadata")}
                _metadata(metadata)
                return {**metadata, "documents": documents, "saved_at": control["saved_at"]}
            except (sqlite3.Error, TypeError, ValueError) as error:
                if isinstance(error, SessionStoreError):
                    raise
                raise SessionStoreError("Session storage cannot be restored; the existing files were preserved") from error

    def snapshot(self):
        with self.lock, _read_snapshot(self.connection):
            return {"state": self.load(), **self.info()}

    def info(self):
        with self.lock:
            control = self._control()
            return {"revision": control["revision"], "journal_mode": self.journal_mode, "storage": "sqlite", "saved_at": control["saved_at"]}

    def _put(self, connection, table, identifier, value, revision):
        prefix, key = ("payload", "session_id") if table == "documents" else ("header", "session_id") if table == "document_headers" else ("value", "key")
        text, digest, size = _json(value)
        existing = connection.execute(f"SELECT {prefix}_hash FROM {table} WHERE {key}=?", (identifier,)).fetchone()
        if existing and existing[0] == digest:
            return 0
        connection.execute(f"INSERT INTO {table}({key},{prefix}_json,{prefix}_hash,{prefix}_bytes,updated_revision) VALUES(?,?,?,?,?) ON CONFLICT({key}) DO UPDATE SET {prefix}_json=excluded.{prefix}_json,{prefix}_hash=excluded.{prefix}_hash,{prefix}_bytes=excluded.{prefix}_bytes,updated_revision=excluded.updated_revision", (identifier, text, digest, size, revision))
        return 1

    def _apply(self, connection, params, *, source_hash=None):
        upserts, removes = params.get("upserts", []), params.get("removes", [])
        if not isinstance(upserts, list) or len(upserts) > MAX_DOCUMENTS or not isinstance(removes, list) or len(removes) > MAX_DOCUMENTS:
            raise ValueError("Workspace patches support at most 1000 analyses")
        upserts = [_record(record) for record in upserts]
        upsert_ids = [record["sessionId"] for record in upserts]
        removes = [_identifier(identifier) for identifier in removes]
        if len(set(upsert_ids)) != len(upsert_ids) or len(set(removes)) != len(removes) or set(upsert_ids).intersection(removes):
            raise ValueError("Workspace patch IDs must be unique and cannot be removed and upserted together")
        metadata = _metadata(params.get("metadata", {}))
        _json(metadata)
        removed_metadata = params.get("remove_metadata", [])
        if not isinstance(removed_metadata, list) or len(removed_metadata) > 4096 or any(not isinstance(key, str) or key in RESERVED_METADATA or key == "activeIndex" for key in removed_metadata):
            raise ValueError("remove_metadata must list workspace metadata fields")
        if set(removed_metadata).intersection(metadata):
            raise ValueError("A metadata field cannot be set and removed together")
        control = self._control(connection)
        expected = params.get("expected_revision")
        if expected is not None and (isinstance(expected, bool) or not isinstance(expected, int) or expected != control["revision"]):
            raise ValueError("Workspace changed since the last acknowledged save; reload before overwriting")
        revision = control["revision"] + 1
        old_order = [row[0] for row in connection.execute("SELECT session_id FROM document_order ORDER BY position")]
        deleted = 0
        for identifier in removes:
            deleted += connection.execute("DELETE FROM documents WHERE session_id=?", (identifier,)).rowcount
        payloads = headers = 0
        changed_ids = set()
        for record in upserts:
            identifier = record["sessionId"]
            existing = connection.execute("SELECT header_json,header_hash FROM document_headers WHERE session_id=?", (identifier,)).fetchone()
            if "document" in record:
                payload_change = self._put(connection, "documents", identifier, record["document"], revision)
                header = {key: value for key, value in record.items() if key not in {"document", "remove_header"}}
                payloads += payload_change
            else:
                if not existing:
                    raise ValueError("A header-only update requires an existing session")
                header = {**_decode(existing[0], existing[1]), **{key: value for key, value in record.items() if key != "remove_header"}}
                payload_change = 0
            for key in record.get("remove_header", []):
                header.pop(key, None)
            header_change = self._put(connection, "document_headers", identifier, header, revision)
            headers += header_change
            if payload_change or header_change:
                changed_ids.add(identifier)
        current = {row[0] for row in connection.execute("SELECT session_id FROM documents")}
        if len(current) > MAX_DOCUMENTS:
            raise ValueError("Workspaces support at most 1000 open analyses")
        order = params.get("order")
        if order is None:
            order = [identifier for identifier in old_order if identifier in current]
            order += [identifier for identifier in upsert_ids if identifier not in order]
        if not isinstance(order, list) or len(order) != len(current):
            raise ValueError("Workspace order must contain every remaining session exactly once")
        order = [_identifier(identifier) for identifier in order]
        if len(set(order)) != len(order) or set(order) != current:
            raise ValueError("Workspace order must contain every remaining session exactly once")
        order_changed = order != old_order
        if order_changed:
            connection.execute("DELETE FROM document_order")
            connection.executemany("INSERT INTO document_order(position,session_id) VALUES(?,?)", enumerate(order))
        changed_metadata = 0
        for key in removed_metadata:
            changed_metadata += connection.execute("DELETE FROM workspace_metadata WHERE key=?", (key,)).rowcount
        for key, value in metadata.items():
            changed_metadata += self._put(connection, "workspace_metadata", key, value, revision)
        if connection.execute("SELECT 1 FROM workspace_metadata WHERE key='activeIndex'").fetchone() is None:
            changed_metadata += self._put(connection, "workspace_metadata", "activeIndex", 0, revision)
        stored_bytes = sum(connection.execute(f"SELECT COALESCE(sum({prefix}_bytes),0) FROM {table}").fetchone()[0] for table, prefix in (("documents", "payload"), ("document_headers", "header"), ("workspace_metadata", "value")))
        stored_bytes += sum(_json(row[0])[2] + 2 for row in connection.execute("SELECT key FROM workspace_metadata"))
        if stored_bytes + len(_json(order)[0].encode("utf-8")) > MAX_STATE_BYTES:
            raise ValueError("Workspace data exceeds 16 MiB")
        changed = not control["initialized"] or bool(changed_ids or deleted or changed_metadata or order_changed)
        saved_at = time.time() if changed else control["saved_at"]
        if changed:
            connection.execute("UPDATE store_control SET initialized=1,revision=?,saved_at=?,document_count=?,metadata_count=(SELECT count(*) FROM workspace_metadata),stored_bytes=?,order_hash=?,migration_source_hash=COALESCE(?,migration_source_hash) WHERE id=1", (revision, saved_at, len(order), stored_bytes, _json(order)[1], source_hash))
        return {"saved_at": saved_at, "revision": revision if changed else control["revision"], "changed_documents": len(changed_ids), "changed_payloads": payloads, "changed_headers": headers, "removed_documents": deleted, "changed_metadata": changed_metadata, "order_changed": order_changed}

    def _save(self, connection, value, *, source_hash=None):
        connection.execute("BEGIN IMMEDIATE")
        try:
            old_order = [row[0] for row in connection.execute("SELECT session_id FROM document_order ORDER BY position")]
            documents, metadata = normalize_state(value, str(self.directory), old_order)
            identifiers = [record["sessionId"] for record in documents]
            old_metadata = [row[0] for row in connection.execute("SELECT key FROM workspace_metadata")]
            result = self._apply(connection, {"upserts": documents, "removes": [identifier for identifier in old_order if identifier not in identifiers], "order": identifiers, "metadata": metadata, "remove_metadata": [key for key in old_metadata if key not in metadata]}, source_hash=source_hash)
            connection.commit()
            return result
        except BaseException:
            connection.rollback()
            raise

    def _transaction(self, connection, params, *, source_hash=None):
        connection.execute("BEGIN IMMEDIATE")
        try:
            result = self._apply(connection, params, source_hash=source_hash)
            connection.commit()
            return result
        except BaseException:
            connection.rollback()
            raise

    def save(self, value):
        with self.lock:
            return self._save(self.connection, value)

    def patch(self, params):
        with self.lock:
            return self._transaction(self.connection, params)

    def checkpoint(self):
        with self.lock:
            if self.journal_mode == "wal":
                busy, frames, checkpointed = self.connection.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
                return {"busy": bool(busy), "frames": frames, "checkpointed": checkpointed}
            return {"busy": False, "frames": 0, "checkpointed": 0}

    def close(self):
        with self.lock:
            self.checkpoint()
            self.connection.close()
