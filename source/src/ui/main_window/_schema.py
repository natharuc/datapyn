"""
SchemaMixin - Schema loading, Object Explorer updates, variable panel interactions.
"""

from __future__ import annotations

import hashlib
import logging
import time

import pandas as pd
from PyQt6 import sip
from PyQt6.QtCore import Qt, QThread, QTimer
from src.language import S
from src.core.connection_ref import ConnectionRef
from src.services.cross_database_schema import (
    collect_sql_text_from_widget,
    extract_referenced_catalogs,
    extract_referenced_table_refs,
    prepare_editor_sql_schema,
    schema_has_columns_for_table,
)
from src.services.schema_service import (
    SCHEMA_BUSY_SENTINEL,
    SCHEMA_LAZY_AUTOCOMPLETE,
    SCHEMA_LAZY_FULL,
    is_schema_busy_result,
    schema_cache_identity,
)

logger = logging.getLogger(__name__)

_EDITOR_REF_FROM_SQL = object()
_EDITOR_REF_ALL_LAZY = object()
_SCHEMA_BUSY_COOLDOWN_SEC = 5.0


class SchemaMixin:
    """Handles schema loading, OE updates, block schema, variable panel."""

    @staticmethod
    def _schema_object_is_invalid(obj) -> bool:
        if obj is None:
            return True
        try:
            if getattr(obj, "_is_closing", False):
                return True
            return bool(sip.isdeleted(obj))
        except RuntimeError:
            return True
        except TypeError:
            return False

    def _connection_ref_for_session(self, session) -> ConnectionRef | None:
        if session is None:
            return None
        name = getattr(session, "connection_name", "") or ""
        if not name:
            return None
        group = getattr(session, "connection_group", "") or ""
        return ConnectionRef(group=group, name=name)

    def _effective_connection_for_block(self, block=None, session=None) -> tuple[str, str]:
        """Return (connection_group, connection_name) for a block or session."""
        if block and hasattr(block, "get_connection_name"):
            block_name = block.get_connection_name()
            if block_name:
                block_group = ""
                if hasattr(block, "get_connection_group"):
                    block_group = block.get_connection_group() or ""
                return block_group, block_name
        if session:
            return (
                getattr(session, "connection_group", "") or "",
                getattr(session, "connection_name", "") or "",
            )
        return "", ""

    def _get_connection_config(self, connection_group: str = "", connection_name: str = ""):
        if not connection_name:
            return None
        return self.connection_manager.get_connection_config(connection_group, connection_name)

    def _get_connection_db_type(
        self, connection_name: str, connection_group: str = ""
    ) -> str:
        config = self._get_connection_config(connection_group, connection_name)
        return config.get("db_type", "") if config else ""

    def _resolve_live_connector(
        self, connection_group: str, connection_name: str, session=None
    ):
        connector = None
        if session is not None:
            connector = getattr(session, "connector", None)
            if connector and self._connector_is_connected(connector):
                return connector
        get_connection = getattr(self.connection_manager, "get_connection", None)
        if callable(get_connection):
            connector = get_connection(connection_group, connection_name)
        if connector and self._connector_is_connected(connector):
            return connector
        return None

    def _run_with_metadata_connector(self, session_id: str, callback):
        """Invoke callback(connector, group, name) when a live connector is available."""
        widget = self._session_widgets.get(session_id) if hasattr(self, "_session_widgets") else None
        if not widget or not hasattr(widget, "session"):
            return
        session = widget.session
        ref = self._connection_ref_for_session(session)
        if ref is None:
            return

        connector = self._resolve_live_connector(ref.group, ref.name, session=session)
        if connector is not None:
            callback(connector, ref.group, ref.name)
            return

        ensure = getattr(widget, "ensure_connector_for_metadata", None)
        if callable(ensure):
            ensure(lambda conn: callback(conn, ref.group, ref.name))
            return

        callback(None, ref.group, ref.name)

    def _pending_oe_key(self, session_id: str, *parts):
        return (session_id, *parts)

    def _pop_pending_oe_session(self, pending: dict, key) -> str:
        value = pending.pop(key, None)
        if isinstance(value, tuple) and len(value) == 2:
            return value[1]
        return value or ""

    @staticmethod
    def _connector_is_connected(connector) -> bool:
        """Check if a connector is connected, handling both method and property forms."""
        ic = getattr(connector, "is_connected", None)
        if ic is None:
            return False
        return ic() if callable(ic) else bool(ic)

    def _schema_busy_cooldown_key_tables(self, catalog_name: str, schema_name: str) -> tuple:
        return ("tables", catalog_name, schema_name)

    def _schema_busy_cooldown_key_columns(
        self, catalog_name: str, schema_name: str, table_name: str
    ) -> tuple:
        return ("columns", catalog_name, schema_name, table_name)

    def _is_schema_request_on_cooldown(self, key: tuple) -> bool:
        cooldowns = getattr(self, "_schema_busy_cooldowns", {})
        return time.monotonic() < cooldowns.get(key, 0.0)

    def _set_schema_request_cooldown(self, key: tuple, ttl: float = _SCHEMA_BUSY_COOLDOWN_SEC) -> None:
        if not hasattr(self, "_schema_busy_cooldowns"):
            self._schema_busy_cooldowns = {}
        self._schema_busy_cooldowns[key] = time.monotonic() + ttl

    def _stop_cross_database_schema_sync(self, session_id: str) -> None:
        """Cancel a pending debounced cross-database schema sync for a session."""
        timers = getattr(self, "_cross_db_schema_timers", None)
        if not timers:
            return
        timer = timers.pop(session_id, None)
        if timer is not None:
            try:
                timer.stop()
            except RuntimeError:
                pass

    def _on_oe_databases_requested(self):
        """Load all server databases when the lazy OE node is expanded."""
        sid = self._session_id_for_object_explorer_sender() or self._get_active_session_id()
        if not sid:
            return

        def _load(connector, _group, connection_name):
            self._schema_service.load_databases(connector, connection_name, session_id=sid)

        self._run_with_metadata_connector(sid, _load)

    # DB types that expose a server-wide database/catalog list worth fetching
    # automatically so the per-block database dropdown is populated.
    _SERVER_DB_LIST_TYPES = frozenset(("mssql", "sqlserver", "mysql", "mariadb", "databricks", "postgresql"))

    def _maybe_auto_request_databases(
        self,
        schema: dict,
        connection_name: str,
        db_type: str,
        session_id: str,
        connection_group: str = "",
    ) -> None:
        """Fallback: if connect schema did not include databases, fetch them once.

        Autocomplete/minimal now preload the switch list in SchemaWorker; this
        remains a safety net when the list is still empty (failed query, race).
        """
        if not connection_name or not session_id:
            return
        if not schema.get("lazy"):
            return
        if schema.get("databases"):
            return
        if str(db_type or "").lower() not in self._SERVER_DB_LIST_TYPES:
            return

        if not hasattr(self, "_auto_db_list_requested"):
            self._auto_db_list_requested = set()
        identity = schema_cache_identity(connection_name, connection_group)
        key = (identity, session_id)
        if key in self._auto_db_list_requested:
            return
        self._auto_db_list_requested.add(key)

        def _load(connector, group, name):
            self._schema_service.load_databases(connector, name, session_id=session_id)

        self._run_with_metadata_connector(session_id, _load)

    def _session_connection_group(self, session_id: str) -> str:
        widget = self._session_widgets.get(session_id) if hasattr(self, "_session_widgets") else None
        session = getattr(widget, "session", None) if widget else None
        return getattr(session, "connection_group", "") or "" if session else ""

    def _on_databases_loaded(self, connection_name: str, session_id: str, databases: list):
        """Merge on-demand database list into cached schema and refresh OE."""
        if not connection_name or not isinstance(databases, list):
            return

        sid = session_id or self._get_active_session_id() or ""
        connection_group = self._session_connection_group(sid)
        cached = self._schema_service.get_cached_schema(
            connection_name, session_id=sid, connection_group=connection_group
        ) or {}
        if not isinstance(cached, dict):
            cached = {}
        merged = dict(cached)
        merged["databases"] = list(databases)
        merged["lazy"] = True
        self._schema_service.update_cached_schema(
            connection_name, merged, session_id=sid, connection_group=connection_group
        )

        if sid and hasattr(self, "_session_explorers"):
            explorer = self._session_explorers.get(sid)
            if explorer:
                db_type = self._get_connection_db_type(connection_name, connection_group)
                explorer.set_schema(merged, connection_name, db_type=db_type)
                explorer.add_databases(databases)

        if sid:
            self._apply_schema_to_session_blocks(
                sid,
                connection_name,
                merged,
                db_type=self._get_connection_db_type(connection_name, connection_group),
                connection_group=connection_group,
            )

    def _store_pending_oe_request(self, attr_name: str, key, session_id: str) -> None:
        pending = getattr(self, attr_name, None)
        if pending is None:
            pending = {}
            setattr(self, attr_name, pending)
        pending[key] = session_id

    def _on_oe_schemas_requested(self, catalog_name: str):
        """Load schemas for a Databricks catalog (lazy loading)."""
        sid = self._session_id_for_object_explorer_sender() or self._get_active_session_id()
        if not sid:
            return

        def _load(connector, _group, connection_name):
            self._store_pending_oe_request(
                "_pending_oe_schema_requests",
                self._pending_oe_key(sid, catalog_name),
                sid,
            )
            self._schema_service.load_schemas_for_catalog(
                connector, connection_name, catalog_name
            )

        self._run_with_metadata_connector(sid, _load)

    def _on_schemas_loaded(self, catalog_name: str, schemas: list):
        """Callback when schemas are loaded for a catalog."""
        pending = getattr(self, "_pending_oe_schema_requests", {})
        sid = ""
        request_key = None
        for key, pending_sid in list(pending.items()):
            if (
                isinstance(key, tuple)
                and len(key) >= 2
                and key[-1] == catalog_name
                and pending_sid
            ):
                sid = pending.pop(key, "")
                request_key = key
                break
        if not sid:
            return
        explorer = self._session_explorers.get(sid)
        if explorer:
            explorer.add_schemas_to_catalog(catalog_name, schemas)

        cross_db = getattr(self, "_pending_cross_db_table_schemas", {}) or {}
        schema_targets = cross_db.pop((sid, catalog_name), None)
        if schema_targets is not None and explorer:
            widget = self._session_widgets.get(sid)
            session = getattr(widget, "session", None) if widget else None
            ref = self._connection_ref_for_session(session)
            if ref is None:
                return

            def _load_tables(connector, _group, connection_name):
                for schema_name in sorted(schema_targets):
                    self._store_pending_oe_request(
                        "_pending_oe_table_requests",
                        self._pending_oe_key(sid, catalog_name, schema_name),
                        sid,
                    )
                    self._schema_service.load_tables_for_schema(
                        connector, connection_name, catalog_name, schema_name
                    )

            self._run_with_metadata_connector(sid, _load_tables)

    def _on_oe_tables_requested(self, catalog_name: str, schema_name: str):
        """Load tables for a schema (lazy loading)."""
        cooldown_key = self._schema_busy_cooldown_key_tables(catalog_name, schema_name)
        if self._is_schema_request_on_cooldown(cooldown_key):
            return

        sid = self._session_id_for_object_explorer_sender() or self._get_active_session_id()
        if not sid:
            return

        def _load(connector, _group, connection_name):
            self._store_pending_oe_request(
                "_pending_oe_table_requests",
                self._pending_oe_key(sid, catalog_name, schema_name),
                sid,
            )
            self._schema_service.load_tables_for_schema(
                connector, connection_name, catalog_name, schema_name
            )

        self._run_with_metadata_connector(sid, _load)

    def _on_tables_loaded(self, catalog_name: str, schema_name: str, tables: list):
        """Callback when tables are loaded for a schema."""
        pending = getattr(self, "_pending_oe_table_requests", {})
        sid = ""
        match_key = None
        for key, pending_sid in list(pending.items()):
            if (
                isinstance(key, tuple)
                and len(key) >= 3
                and key[-2:] == (catalog_name, schema_name)
            ):
                sid = pending.pop(key, "")
                match_key = key
                break
        if is_schema_busy_result(tables):
            self._set_schema_request_cooldown(
                self._schema_busy_cooldown_key_tables(catalog_name, schema_name)
            )
            if sid:
                explorer = self._session_explorers.get(sid)
                if explorer:
                    explorer.notify_schema_busy(
                        self._schema_busy_cooldown_key_tables(catalog_name, schema_name),
                        retry_callback=lambda: self._retry_oe_tables_for_session(
                            sid, catalog_name, schema_name
                        ),
                    )
            return
        if not sid:
            return
        explorer = self._session_explorers.get(sid)
        if explorer:
            explorer.add_tables_to_schema(catalog_name, schema_name, tables)

    def _on_oe_columns_requested(self, catalog_name: str, schema_name: str, table_name: str):
        """Load columns for a table (lazy loading)."""
        cooldown_key = self._schema_busy_cooldown_key_columns(
            catalog_name, schema_name, table_name
        )
        if self._is_schema_request_on_cooldown(cooldown_key):
            return

        sid = self._session_id_for_object_explorer_sender() or self._get_active_session_id()
        if not sid:
            return

        def _load(connector, _group, connection_name):
            self._store_pending_oe_request(
                "_pending_oe_column_requests",
                self._pending_oe_key(sid, catalog_name, schema_name, table_name),
                sid,
            )
            self._schema_service.load_columns_for_table(
                connector, connection_name, catalog_name, schema_name, table_name
            )

        self._run_with_metadata_connector(sid, _load)

    def _on_columns_loaded(self, catalog_name: str, schema_name: str, table_name: str, columns: list):
        """Callback when columns are loaded for a table."""
        pending = getattr(self, "_pending_oe_column_requests", {})
        sid = ""
        for key, pending_sid in list(pending.items()):
            if (
                isinstance(key, tuple)
                and len(key) >= 4
                and key[-3:] == (catalog_name, schema_name, table_name)
            ):
                sid = pending.pop(key, "")
                break
        if is_schema_busy_result(columns):
            self._set_schema_request_cooldown(
                self._schema_busy_cooldown_key_columns(catalog_name, schema_name, table_name)
            )
            if sid:
                explorer = self._session_explorers.get(sid)
                if explorer:
                    explorer.notify_schema_busy(
                        self._schema_busy_cooldown_key_columns(
                            catalog_name, schema_name, table_name
                        ),
                        retry_callback=lambda: self._retry_oe_columns_for_session(
                            sid, catalog_name, schema_name, table_name
                        ),
                    )
            return
        if not sid:
            return
        explorer = self._session_explorers.get(sid)
        if explorer:
            explorer.add_columns_to_table(catalog_name, schema_name, table_name, columns)

    def _clear_pending_object_explorer_requests(self, session_id: str):
        """Drop stale lazy-load requests for a session after a full schema refresh."""
        if not session_id:
            return

        for attr_name in (
            "_pending_oe_schema_requests",
            "_pending_oe_table_requests",
            "_pending_oe_column_requests",
        ):
            pending = getattr(self, attr_name, None)
            if not isinstance(pending, dict):
                continue

            stale_keys = [
                key for key, pending_session_id in pending.items()
                if pending_session_id == session_id
                and isinstance(key, tuple)
                and key
                and key[0] == session_id
            ]
            for key in stale_keys:
                pending.pop(key, None)

    def _retry_oe_tables_for_session(self, session_id: str, catalog_name: str, schema_name: str) -> None:
        def _load(connector, _group, connection_name):
            self._store_pending_oe_request(
                "_pending_oe_table_requests",
                self._pending_oe_key(session_id, catalog_name, schema_name),
                session_id,
            )
            self._schema_service.load_tables_for_schema(
                connector, connection_name, catalog_name, schema_name
            )

        self._run_with_metadata_connector(session_id, _load)

    def _retry_oe_columns_for_session(
        self, session_id: str, catalog_name: str, schema_name: str, table_name: str
    ) -> None:
        def _load(connector, _group, connection_name):
            self._store_pending_oe_request(
                "_pending_oe_column_requests",
                self._pending_oe_key(session_id, catalog_name, schema_name, table_name),
                session_id,
            )
            self._schema_service.load_columns_for_table(
                connector, connection_name, catalog_name, schema_name, table_name
            )

        self._run_with_metadata_connector(session_id, _load)

    def _session_id_for_object_explorer_sender(self) -> str:
        sender = self.sender()
        if not sender or not hasattr(self, "_session_explorers"):
            return ""
        for session_id, explorer in self._session_explorers.items():
            if explorer is sender:
                return session_id
        return ""

    def _on_object_explorer_schema_changed(self, session_id: str, schema: dict):
        """Refresh editor autocomplete when Object Explorer lazy metadata changes."""
        if not session_id or not isinstance(schema, dict):
            return

        explorer = self._session_explorers.get(session_id) if hasattr(self, "_session_explorers") else None
        if not explorer:
            return

        connection_name = getattr(explorer, "_current_connection", "") or ""
        if not connection_name:
            return

        connection_group = self._session_connection_group(session_id)
        db_type = getattr(explorer, "_db_type", "") or self._get_connection_db_type(
            connection_name, connection_group
        )
        editor_schema = self._editor_schema_for_session(
            schema,
            session_id=session_id,
            db_type=db_type,
            referenced_mode=_EDITOR_REF_ALL_LAZY,
        )
        self._schema_service.update_cached_schema(
            connection_name,
            editor_schema,
            session_id=session_id,
            connection_group=connection_group,
        )
        self._apply_schema_to_session_blocks(
            session_id,
            connection_name,
            schema,
            db_type=db_type,
            referenced_mode=_EDITOR_REF_ALL_LAZY,
            connection_group=connection_group,
        )

    def _collect_session_sql_text(self, session_id: str) -> str:
        widget = self._session_widgets.get(session_id) if hasattr(self, "_session_widgets") else None
        if not widget:
            return ""
        return collect_sql_text_from_widget(widget)

    def _editor_schema_for_session(
        self,
        schema: dict,
        *,
        session_id: str,
        db_type: str,
        referenced_mode=_EDITOR_REF_FROM_SQL,
    ) -> dict:
        if referenced_mode is _EDITOR_REF_FROM_SQL:
            sql_text = self._collect_session_sql_text(session_id) if session_id else ""
            referenced_catalogs = extract_referenced_catalogs(
                sql_text,
                current_database=str(schema.get("database", "") or ""),
                db_type=db_type,
            )
        elif referenced_mode is _EDITOR_REF_ALL_LAZY:
            referenced_catalogs = None
        else:
            referenced_catalogs = referenced_mode
        return prepare_editor_sql_schema(
            schema,
            db_type=db_type,
            referenced_catalogs=referenced_catalogs,
        )

    def _session_widget_is_alive(self, widget) -> bool:
        if widget is None:
            return False
        try:
            from PyQt6 import sip
            if sip.isdeleted(widget):
                return False
        except Exception:
            pass
        session = getattr(widget, "session", None)
        session_id = getattr(session, "session_id", None) if session else None
        if not session_id:
            return False
        widgets = getattr(self, "_session_widgets", None)
        if isinstance(widgets, dict) and session_id not in widgets:
            return False
        tabs = getattr(self, "session_tabs", None)
        if tabs is not None:
            try:
                for index in range(tabs.count()):
                    if tabs.widget(index) is widget:
                        return True
                return False
            except RuntimeError:
                return False
        return True

    def _schedule_cross_database_schema_sync(self, widget) -> None:
        """Debounce lazy metadata loads for databases referenced in SQL text."""
        if not self._session_widget_is_alive(widget):
            return
        if not widget or not hasattr(widget, "session") or not widget.session:
            return

        session_id = widget.session.session_id
        timers = getattr(self, "_cross_db_schema_timers", None)
        if timers is None:
            timers = {}
            self._cross_db_schema_timers = timers

        existing = timers.pop(session_id, None)
        if existing is not None:
            try:
                existing.stop()
            except RuntimeError:
                pass

        timer = QTimer(self)
        timer.setSingleShot(True)

        def run_sync(sid=session_id, w=widget):
            timers.pop(sid, None)
            if not self._session_widget_is_alive(w):
                return
            self._sync_cross_database_schema_for_widget(w)

        timer.timeout.connect(run_sync)
        timers[session_id] = timer
        timer.start(400)

    def _sync_cross_database_schema_for_widget(self, widget) -> None:
        if not self._session_widget_is_alive(widget):
            return
        session = getattr(widget, "session", None)
        if not session:
            return

        session_id = session.session_id
        connection_name = getattr(session, "connection_name", "") or ""
        connection_group = getattr(session, "connection_group", "") or ""
        if not connection_name:
            return

        db_type = self._get_connection_db_type(connection_name, connection_group)

        sql_text = collect_sql_text_from_widget(widget)
        if not sql_text.strip():
            return

        sql_hash = hashlib.md5(sql_text.encode("utf-8", errors="replace")).hexdigest()
        hashes = getattr(self, "_cross_db_schema_sql_hashes", None)
        if hashes is None:
            hashes = {}
            self._cross_db_schema_sql_hashes = hashes
        if hashes.get(session_id) == sql_hash:
            return

        explorer = self._session_explorers.get(session_id) if hasattr(self, "_session_explorers") else None
        oe_schema = getattr(explorer, "_current_schema", None) if explorer else None
        cached = self._schema_service.get_cached_schema(
            connection_name,
            session_id=session_id,
            connection_group=connection_group,
        )
        base_schema = oe_schema if isinstance(oe_schema, dict) else cached

        current_database = ""
        if isinstance(base_schema, dict):
            current_database = str(base_schema.get("database", "") or "")

        referenced_catalogs = extract_referenced_catalogs(
            sql_text,
            current_database=current_database,
            db_type=db_type,
        )
        table_refs = extract_referenced_table_refs(
            sql_text,
            current_database=current_database,
            db_type=db_type,
        )
        if not referenced_catalogs and not table_refs:
            return

        def _sync(connector, _group, conn_name):
            is_query_busy = getattr(connector, "is_query_busy", None)
            if callable(is_query_busy) and is_query_busy():
                return

            loaded_catalogs = set()
            if isinstance(base_schema, dict):
                for table in base_schema.get("tables", []) or []:
                    if isinstance(table, dict):
                        db_name = str(table.get("database", "") or table.get("catalog", "") or "")
                        if db_name:
                            loaded_catalogs.add(db_name.lower())

            server_databases = set()
            if isinstance(base_schema, dict):
                server_databases = {
                    str(name).lower()
                    for name in (base_schema.get("databases", []) or [])
                    if name
                }

            table_requests = getattr(self, "_pending_oe_table_requests", None)
            if table_requests is None:
                table_requests = {}
                self._pending_oe_table_requests = table_requests

            column_requests = getattr(self, "_pending_oe_column_requests", None)
            if column_requests is None:
                column_requests = {}
                self._pending_oe_column_requests = column_requests

            refs_by_catalog: dict[str, set[str]] = {}
            for catalog_name, schema_name, _table_name in table_refs:
                if catalog_name and schema_name:
                    refs_by_catalog.setdefault(catalog_name, set()).add(schema_name)

            if db_type == "databricks":
                cross_db_schemas = getattr(self, "_pending_cross_db_table_schemas", None)
                if cross_db_schemas is None:
                    cross_db_schemas = {}
                    self._pending_cross_db_table_schemas = cross_db_schemas

                for catalog_name in sorted(referenced_catalogs):
                    catalog_lower = catalog_name.lower()
                    if catalog_lower == (current_database or "").lower():
                        continue
                    if server_databases and catalog_lower not in server_databases:
                        continue
                    if catalog_lower in loaded_catalogs and not refs_by_catalog.get(catalog_name):
                        continue

                    schema_targets = refs_by_catalog.get(catalog_name, set())
                    if schema_targets:
                        for schema_name in sorted(schema_targets):
                            request_key = self._pending_oe_key(
                                session_id, catalog_name, schema_name
                            )
                            if table_requests.get(request_key) == session_id:
                                continue
                            cooldown_key = self._schema_busy_cooldown_key_tables(
                                catalog_name, schema_name
                            )
                            if self._is_schema_request_on_cooldown(cooldown_key):
                                continue
                            table_requests[request_key] = session_id
                            self._schema_service.load_tables_for_schema(
                                connector,
                                conn_name,
                                catalog_name,
                                schema_name,
                            )
                    else:
                        targets = refs_by_catalog.get(catalog_name, set())
                        if targets:
                            cross_db_schemas[(session_id, catalog_name)] = set(targets)
                        schema_request_key = self._pending_oe_key(session_id, catalog_name)
                        if table_requests.get(schema_request_key) == session_id:
                            continue
                        table_requests[schema_request_key] = session_id
                        self._schema_service.load_schemas_for_catalog(
                            connector, conn_name, catalog_name
                        )
            else:
                for catalog_name in sorted(referenced_catalogs):
                    catalog_lower = catalog_name.lower()
                    if catalog_lower == (current_database or "").lower():
                        continue
                    if server_databases and catalog_lower not in server_databases:
                        continue
                    if catalog_lower in loaded_catalogs:
                        continue

                    request_key = self._pending_oe_key(session_id, catalog_name, "")
                    if table_requests.get(request_key) == session_id:
                        continue
                    cooldown_key = self._schema_busy_cooldown_key_tables(catalog_name, "")
                    if self._is_schema_request_on_cooldown(cooldown_key):
                        continue
                    table_requests[request_key] = session_id
                    self._schema_service.load_tables_for_schema(
                        connector,
                        conn_name,
                        catalog_name,
                        "",
                    )

            for catalog_name, schema_name, table_name in table_refs:
                if not table_name:
                    continue
                if catalog_name and catalog_name.lower() == (current_database or "").lower():
                    continue
                if isinstance(base_schema, dict) and schema_has_columns_for_table(
                    base_schema, catalog_name, schema_name, table_name
                ):
                    continue

                request_key = self._pending_oe_key(
                    session_id, catalog_name, schema_name, table_name
                )
                if column_requests.get(request_key) == session_id:
                    continue
                cooldown_key = self._schema_busy_cooldown_key_columns(
                    catalog_name, schema_name, table_name
                )
                if self._is_schema_request_on_cooldown(cooldown_key):
                    continue
                column_requests[request_key] = session_id
                self._schema_service.load_columns_for_table(
                    connector,
                    conn_name,
                    catalog_name,
                    schema_name,
                    table_name,
                )

            hashes[session_id] = sql_hash

        self._run_with_metadata_connector(session_id, _sync)

    def _block_schema_database(self, block) -> str:
        """Current database label on a block's autocomplete schema, if any."""
        if hasattr(block, "get_sql_schema"):
            schema = block.get_sql_schema()
        else:
            schema = getattr(block, "_sql_schema", None) or {}
        if not isinstance(schema, dict):
            return ""
        return schema.get("database", "") or ""

    @staticmethod
    def _database_context_matches(expected: str, actual: str) -> bool:
        expected = str(expected or "").strip().lower()
        actual = str(actual or "").strip().lower()
        if not expected or not actual:
            return not expected
        for prefix in ("catalog:", "schema:"):
            if expected.startswith(prefix):
                expected = expected[len(prefix):]
            if actual.startswith(prefix):
                actual = actual[len(prefix):]
        return (
            expected == actual
            or expected.endswith(f".{actual}")
            or actual.endswith(f".{expected}")
            or expected.split(".")[-1] == actual.split(".")[-1]
        )

    def _schema_matches_block_database(self, block, schema: dict) -> bool:
        """Reject a schema response that belongs to an older block database."""
        if not block or not isinstance(schema, dict):
            return False
        target = (
            block.get_database_name()
            if hasattr(block, "get_database_name")
            else ""
        )
        if not target:
            return True
        db_type = str(schema.get("db_type") or "").lower()
        if db_type == "postgresql":
            # Block chip stores the schema (search_path), while requested/connection
            # context remain the real database name.
            incoming_schema = str(schema.get("current_schema") or "").strip()
            return self._database_context_matches(target, incoming_schema)
        incoming = (
            schema.get("requested_context")
            or schema.get("connection_context")
            or schema.get("current_context")
            or schema.get("database", "")
        )
        return self._database_context_matches(target, incoming)

    def _report_schema_feedback(self, schema: dict, schema_label: str) -> None:
        tables_total = len(schema.get("tables") or [])
        cols_total = sum(len(v) for v in (schema.get("columns") or {}).values())
        if schema.get("metadata_loaded") is True:
            self._log_info(
                S.log.schema_loaded.format(
                    name=schema_label,
                    tables=tables_total,
                    cols=cols_total,
                )
            )
            self.statusBar().showMessage(
                S.status.schema_loaded.format(
                    name=schema_label,
                    tables=tables_total,
                    cols=cols_total,
                ),
                5000,
            )
        else:
            context_message = f"Schema context loaded: {schema_label}"
            self._log_info(context_message)
            self.statusBar().showMessage(context_message, 5000)

    def _should_apply_session_schema_to_block(self, block, editor_schema: dict) -> bool:
        """Skip session-wide schema when the block already targets another database."""
        if not block or not isinstance(editor_schema, dict):
            return False
        if not self._schema_matches_block_database(block, editor_schema):
            return False
        incoming_db = editor_schema.get("database", "") or ""
        block_db = self._block_schema_database(block)
        if block_db and incoming_db and block_db != incoming_db:
            return False
        return True

    def _clear_sql_autocomplete_for_connection(self, widget, connection_name: str):
        """Clear Monaco SQL autocomplete for blocks affected by a database switch."""
        if not widget or not connection_name or not hasattr(widget, "editor") or not widget.editor:
            return

        editor = widget.editor
        session_conn = ""
        if hasattr(widget, "session") and widget.session:
            session_conn = getattr(widget.session, "connection_name", "") or ""

        if session_conn == connection_name:
            if hasattr(editor, "set_sql_schema"):
                editor.set_sql_schema({})
            elif hasattr(editor, "_sql_schema"):
                editor._sql_schema = {}
            if hasattr(editor, "set_database_context"):
                editor.set_database_context("")

        get_blocks = getattr(editor, "get_blocks", None)
        blocks = get_blocks() if callable(get_blocks) else []
        for block in blocks:
            block_lang = block.get_language() if hasattr(block, "get_language") else ""
            if block_lang != "sql":
                continue

            block_conn = block.get_connection_name() if hasattr(block, "get_connection_name") else None
            should_clear = block_conn == connection_name if block_conn else session_conn == connection_name
            if not should_clear:
                continue

            if hasattr(block, "set_sql_schema"):
                block.set_sql_schema({})
            elif hasattr(block, "editor") and hasattr(block.editor, "set_sql_schema"):
                block.editor.set_sql_schema({})

    def _available_databases_from_schema(self, schema: dict, db_type: str = "") -> list:
        db_type = str(db_type or schema.get("db_type") or "").lower()
        if db_type == "postgresql":
            # Chip lists schemas (search_path), not databases.
            schemas = list(schema.get("schemas", []) or [])
            if schemas:
                return schemas
            # Fallback: derive unique schemas from loaded tables.
            derived = sorted({
                str(table.get("schema") or "")
                for table in (schema.get("tables", []) or [])
                if table.get("schema")
            })
            return derived or list(schema.get("databases", []) or [])

        all_databases = list(schema.get("databases", []) or [])
        if db_type != "databricks":
            return all_databases

        values = set(all_databases)
        catalog_schemas = schema.get("catalog_schemas", {}) or {}
        for catalog, schemas in catalog_schemas.items():
            for schema_name in schemas or []:
                if catalog and schema_name:
                    values.add(f"{catalog}.{schema_name}")

        current_catalog = schema.get("database", "")
        for table in schema.get("tables", []) or []:
            catalog = table.get("catalog") or current_catalog
            schema_name = table.get("schema", "")
            if catalog and schema_name:
                values.add(f"{catalog}.{schema_name}")

        return sorted(value for value in values if value)

    def _apply_schema_to_session_blocks(
        self,
        session_id: str,
        connection_name: str,
        schema: dict,
        db_type: str = "",
        *,
        referenced_mode=_EDITOR_REF_FROM_SQL,
        connection_group: str = "",
    ):
        widget = self._session_widgets.get(session_id)
        if not widget or not hasattr(widget, "editor") or not widget.editor:
            return

        session_conn = ""
        if hasattr(widget, "session") and widget.session:
            session_conn = getattr(widget.session, "connection_name", "") or ""
            if not connection_group:
                connection_group = getattr(widget.session, "connection_group", "") or ""

        available_databases = self._available_databases_from_schema(schema, db_type)

        editor_schema = self._editor_schema_for_session(
            schema,
            session_id=session_id,
            db_type=db_type,
            referenced_mode=referenced_mode,
        )

        schema_context = self._build_schema_context(editor_schema, connection_name)
        if session_conn == connection_name:
            if hasattr(widget.editor, "set_sql_schema"):
                widget.editor.set_sql_schema(editor_schema)
            if hasattr(widget.editor, "set_database_context"):
                widget.editor.set_database_context(schema_context)

        for block in widget.editor.get_blocks():
            block_lang = block.get_language() if hasattr(block, "get_language") else ""
            if block_lang != "sql":
                continue

            block_conn = block.get_connection_name() if hasattr(block, "get_connection_name") else None
            uses_connection = (block_conn == connection_name) or (not block_conn and session_conn == connection_name)
            if not uses_connection:
                continue
            if not self._should_apply_session_schema_to_block(block, editor_schema):
                continue

            self._apply_schema_to_block(
                block,
                editor_schema,
                db_type=db_type,
                connection_name=connection_name,
            )

    def _load_schema_with_loading(
        self,
        connector,
        connection_name: str,
        session_id: str = "",
        *,
        lazy: bool = True,
        lazy_mode: str | None = None,
        connection_group: str = "",
    ):
        """Load schema and show loading indicator in Object Explorer.
        
        Args:
            connector: DatabaseConnector with active connection
            connection_name: Connection name
            session_id: Session ID for per-session cache (optional, defaults to active)
            lazy: When True, only load current database context (default on connect)
            lazy_mode: Override lazy level (minimal | autocomplete | full).
                When omitted and lazy=True, loads tables/columns for offline
                autocomplete (SCHEMA_LAZY_AUTOCOMPLETE).
        """
        # Get or CREATE the explorer for the current session (important: _get_session_explorer creates if needed)
        sid = session_id or self._get_active_session_id()
        if sid and not connection_group:
            connection_group = self._session_connection_group(sid)
        if sid:
            explorer = self._get_session_explorer(sid)
            explorer.set_loading(True, S.object_explorer.loading)
            self._switch_session_explorer(sid)

        # Show Object Explorer dock if hidden (so user sees the loading)
        if hasattr(self, 'object_explorer_dock') and not self.object_explorer_dock.isVisible():
            self.object_explorer_dock.show()
            # Update menu checkmark
            if hasattr(self, 'object_explorer_action'):
                self.object_explorer_action.setChecked(True)

        self._schema_service.load_schema(
            connector,
            connection_name,
            session_id=sid or "",
            connection_group=connection_group,
            lazy=lazy,
            lazy_mode=lazy_mode if lazy_mode is not None else (
                SCHEMA_LAZY_AUTOCOMPLETE if lazy else None
            ),
        )

    def _reload_schema(self):
        """Reloads the SQL schema from the focused block connection (or session).

        Usa a conexao do bloco focado se ele tiver conexao customizada,
        caso contrario usa a conexao da sessao ativa.
        """
        widget = self._get_current_session_widget()
        if not widget:
            self.statusBar().showMessage(S.status.no_active_session, 3000)
            return

        # Determine connection: focused block or session
        connection_name = None
        connection_group = ""
        connector = None

        focused_block = widget.editor.get_focused_block()
        if focused_block:
            connection_group, connection_name = self._effective_connection_for_block(
                focused_block, widget.session
            )
            if connection_name and focused_block.get_connection_name():
                connector = self.connection_manager.get_connection(
                    connection_group, connection_name
                )

        if not connection_name:
            # Use session connection
            if widget.session.is_connected and widget.session.connection_name:
                connection_group = getattr(widget.session, "connection_group", "") or ""
                connection_name = widget.session.connection_name
                connector = widget.session.connector

        if not connection_name:
            self.statusBar().showMessage(S.status.no_active_connection_reload, 3000)
            return

        # Get session_id for per-session cache
        sid = widget.session.session_id if hasattr(widget, "session") else ""

        # Invalidate cache and reload (per-session)
        self._schema_service.invalidate_cache(
            connection_name, session_id=sid, connection_group=connection_group
        )
        self.statusBar().showMessage(S.status.reloading_schema.format(name=connection_name), 5000)

        if connector and self._connector_is_connected(connector):
            self._load_schema_with_loading(
                connector,
                connection_name,
                session_id=sid,
                connection_group=connection_group,
                lazy=False,
                lazy_mode=SCHEMA_LAZY_FULL,
            )
        else:
            # Need to get connector from ConnectionManager
            from src.database.connection_manager import ConnectionManager
            manager = ConnectionManager()
            conn = manager.get_connection(connection_group, connection_name)
            if conn and self._connector_is_connected(conn):
                self._load_schema_with_loading(
                    conn,
                    connection_name,
                    session_id=sid,
                    connection_group=connection_group,
                    lazy=False,
                    lazy_mode=SCHEMA_LAZY_FULL,
                )
            else:
                self.statusBar().showMessage(S.status.connection_not_active.format(name=connection_name), 3000)

    def _on_schema_loaded(
        self,
        schema: dict,
        connection_name: str,
        session_id: str = "",
        block_key: str = "",
    ):
        """Callback when database schema is loaded by SchemaService.

        Distribui o schema para os blocos SQL que usam
        a conexao correspondente.
        Se connection_name e a conexao da sessao, aplica aos blocos sem conexao customizada.
        Se connection_name e uma conexao de bloco especifico, aplica so a esse bloco.
        
        Args:
            schema: Loaded schema dict
            connection_name: Connection name
            session_id: Session ID that requested the schema (for isolation)
            block_key: Isolated SQL block id (per-block database context)
        """
        if self._schema_object_is_invalid(self):
            return
        # Guard against invalid data (e.g., Mock objects in tests)
        if not isinstance(schema, dict) or not isinstance(connection_name, str):
            return

        schema_label = (
            schema.get("database")
            or schema.get("current_context")
            or connection_name
        )

        if not session_id:
            return
        connection_group = self._session_connection_group(session_id)
        requesting_sid = session_id
        db_type = self._get_connection_db_type(connection_name, connection_group)
        self._clear_pending_object_explorer_requests(requesting_sid)

        if block_key:
            target_block = self._find_block_by_key(block_key, requesting_sid)
            if target_block is not None and not self._schema_object_is_invalid(target_block):
                if not self._schema_matches_block_database(target_block, schema):
                    return
                self._report_schema_feedback(schema, schema_label)
                self._apply_schema_to_block(
                    target_block,
                    schema,
                    db_type=db_type,
                    connection_name=connection_name,
                )
                self._update_oe_for_block_connection(target_block, connection_name, schema)
            return

        self._report_schema_feedback(schema, schema_label)

        # Defer heavy Monaco/schema propagation to the next event-loop tick
        QTimer.singleShot(
            0,
            lambda s=schema, cn=connection_name, db=db_type, rs=requesting_sid: self._apply_loaded_schema_to_blocks(
                s, cn, db_type=db, requesting_sid=rs,
            ),
        )

        # Safety net if connect autocomplete did not populate databases.
        self._maybe_auto_request_databases(
            schema, connection_name, db_type, requesting_sid, connection_group
        )

        # Update Object Explorer for the session that REQUESTED this schema
        if hasattr(self, "_session_explorers"):
            if requesting_sid:
                explorer = self._get_session_explorer(requesting_sid)
                explorer.set_schema(schema, connection_name, db_type=db_type)
                if not hasattr(self, "_oe_current_connection"):
                    self._oe_current_connection = {}
                self._oe_current_connection[requesting_sid] = connection_name

            current_widget = self._get_current_session_widget()
            if (
                not self._schema_object_is_invalid(current_widget)
                and not getattr(current_widget, "_is_closing", False)
                and hasattr(current_widget, "session")
            ):
                active_sid = current_widget.session.session_id
                self._switch_session_explorer(active_sid)
                if requesting_sid == active_sid:
                    self.object_explorer_dock.show()

        self._maybe_warm_databricks_catalog_schemas(
            schema, connection_name, db_type, requesting_sid, connection_group
        )

    def _maybe_warm_databricks_catalog_schemas(
        self,
        schema: dict,
        connection_name: str,
        db_type: str,
        session_id: str,
        connection_group: str = "",
    ):
        if str(db_type or schema.get("db_type") or "").lower() != "databricks":
            return
        sid = session_id or ""
        if not sid:
            return
        catalogs = list(schema.get("databases") or [])
        if len(catalogs) <= 1:
            return
        current_catalog = str(schema.get("database") or "")
        already = getattr(self, "_databricks_schema_warm_done", set())
        warm_key = (sid, connection_name)
        if warm_key in already:
            return
        already.add(warm_key)
        self._databricks_schema_warm_done = already

        def _load(connector, _group, name):
            if connector is None:
                already.discard(warm_key)
                return
            self._schema_service.warm_catalog_schemas(
                connector,
                name,
                catalogs,
                skip_catalog=current_catalog,
                session_id=sid,
            )

        self._run_with_metadata_connector(sid, _load)

    def _on_catalog_schemas_warmed(self, payload: dict):
        if not isinstance(payload, dict):
            return
        sid = str(payload.get("session_id") or "")
        connection_name = str(payload.get("connection_name") or "")
        loaded = payload.get("loaded") or {}
        remaining = list(payload.get("remaining") or [])
        if not sid:
            return
        explorer = self._session_explorers.get(sid) if hasattr(self, "_session_explorers") else None
        if explorer:
            for catalog_name, schemas in loaded.items():
                explorer.add_schemas_to_catalog(catalog_name, schemas)
        widget = self._session_widgets.get(sid) if hasattr(self, "_session_widgets") else None
        connection_group = self._session_connection_group(sid)
        cached = None
        if connection_name:
            cached = self._schema_service.get_cached_schema(
                connection_name, session_id=sid, connection_group=connection_group
            )
        if cached and loaded:
            catalog_schemas = cached.setdefault("catalog_schemas", {})
            for catalog_name, schemas in loaded.items():
                existing = set(catalog_schemas.get(catalog_name, []) or [])
                for schema_name in schemas or []:
                    if schema_name:
                        existing.add(str(schema_name))
                catalog_schemas[catalog_name] = sorted(existing)
            self._schema_service.update_cached_schema(
                connection_name, cached, session_id=sid, connection_group=connection_group
            )
            db_type = self._get_connection_db_type(connection_name, connection_group)
            self._apply_schema_to_session_blocks(
                sid,
                connection_name,
                cached,
                db_type=db_type,
                connection_group=connection_group,
            )
        if remaining:
            def _retry(connector, _group, name):
                if connector is None:
                    return
                self._schema_service.warm_catalog_schemas(
                    connector,
                    name,
                    remaining,
                    session_id=sid,
                )

            QTimer.singleShot(
                1500,
                lambda: self._run_with_metadata_connector(sid, _retry),
            )

    def request_databricks_namespace(self, block, catalog: str, schema: str = "", session_widget=None):
        """Load schemas or tables for a catalog.schema typed in the SQL editor."""
        catalog = str(catalog or "").strip()
        schema = str(schema or "").strip()
        if not catalog:
            return
        sid = ""
        if session_widget is not None:
            sid = getattr(getattr(session_widget, "session", None), "session_id", "") or ""
        if not sid:
            sid = self._get_active_session_id() or ""
        if not sid:
            return
        key = (sid, catalog.lower(), schema.lower())
        in_flight = getattr(self, "_databricks_namespace_fetches", set())
        if key in in_flight:
            return
        in_flight.add(key)
        self._databricks_namespace_fetches = in_flight

        def _load(connector, _group, connection_name):
            if connector is None:
                in_flight.discard(key)
                return
            if not schema:
                self._store_pending_oe_request(
                    "_pending_oe_schema_requests",
                    self._pending_oe_key(sid, catalog),
                    sid,
                )
                self._schema_service.load_schemas_for_catalog(connector, connection_name, catalog)
            else:
                self._store_pending_oe_request(
                    "_pending_oe_table_requests",
                    self._pending_oe_key(sid, catalog, schema),
                    sid,
                )
                self._schema_service.load_tables_for_schema(
                    connector, connection_name, catalog, schema
                )
            QTimer.singleShot(8000, lambda: in_flight.discard(key))

        self._run_with_metadata_connector(sid, _load)

    def _apply_loaded_schema_to_blocks(
        self,
        schema: dict,
        connection_name: str,
        *,
        db_type: str = "",
        requesting_sid: str = "",
    ):
        """Apply loaded schema to SQL blocks without blocking the schema_loaded handler."""
        if self._schema_object_is_invalid(self):
            return
        all_databases = self._available_databases_from_schema(schema, db_type)

        for widget in self._session_widgets.values():
            if self._schema_object_is_invalid(widget):
                continue
            if not (hasattr(widget, "editor") and widget.editor):
                continue
            if self._schema_object_is_invalid(widget.editor):
                continue

            session_conn = ""
            sid = ""
            if hasattr(widget, "session") and widget.session:
                session_conn = getattr(widget.session, "connection_name", "") or ""
                sid = widget.session.session_id

            if requesting_sid and sid != requesting_sid:
                continue

            editor_schema = self._editor_schema_for_session(
                schema,
                session_id=sid,
                db_type=db_type,
            )
            schema_context = self._build_schema_context(editor_schema, connection_name)

            if session_conn == connection_name:
                if hasattr(widget.editor, "set_sql_schema"):
                    widget.editor.set_sql_schema(editor_schema)
                if hasattr(widget.editor, "set_database_context"):
                    widget.editor.set_database_context(schema_context)

            for block in widget.editor.get_blocks():
                if self._schema_object_is_invalid(block):
                    continue
                block_lang = block.get_language() if hasattr(block, "get_language") else ""
                if block_lang != "sql":
                    continue

                block_conn = block.get_connection_name() if hasattr(block, "get_connection_name") else None

                uses_connection = (block_conn == connection_name) or (
                    not block_conn and session_conn == connection_name
                )
                if not uses_connection:
                    continue
                if not self._should_apply_session_schema_to_block(block, editor_schema):
                    continue

                self._apply_schema_to_block(
                    block,
                    editor_schema,
                    db_type=db_type,
                    connection_name=connection_name,
                )

        if requesting_sid and hasattr(self.connection_manager, "get_connection"):
            widget = self._session_widgets.get(requesting_sid)
            if widget:
                QTimer.singleShot(0, lambda w=widget: self._sync_cross_database_schema_for_widget(w))

    def _build_schema_context(self, schema: dict, connection_name: str) -> str:
        """Build text context from schema for Copilot inline completions.
        
        Returns a compact representation of tables and columns that fits
        within token limits while providing useful context.
        """
        tables = schema.get("tables", [])
        columns = schema.get("columns", {})
        db_name = schema.get("database", connection_name)
        
        lines = [f"Database: {db_name}", f"Tables ({len(tables)}):"]
        
        for table in tables[:30]:  # Limit to first 30 tables
            table_name = table.get("name", "")
            table_schema = table.get("schema", "")
            table_catalog = table.get("catalog", "")
            table_key = table.get("key", "")
            fallback_key = f"{table_schema}.{table_name}" if table_schema else table_name
            full_key = ".".join(part for part in (table_catalog, table_schema, table_name) if part)
            table_cols = columns.get(table_key, []) or columns.get(full_key, []) or columns.get(fallback_key, []) or columns.get(table_name, [])
            col_names = [c.get("name", "") for c in table_cols[:10]]  # First 10 cols
            if len(table_cols) > 10:
                col_names.append(f"... +{len(table_cols) - 10} more")
            display_name = full_key or fallback_key or table_name
            lines.append(f"  {display_name}: {', '.join(col_names)}")
        
        if len(tables) > 30:
            lines.append(f"  ... +{len(tables) - 30} more tables")
        
        return "\n".join(lines)

    def _on_schema_error(self, error_msg: str):
        """Handle schema loading error — show feedback in OE panel."""
        sid = self._get_active_session_id()
        if sid and hasattr(self, "_session_explorers"):
            explorer = self._session_explorers.get(sid)
            if explorer:
                explorer.set_error(S.object_explorer.schema_error)
        self.statusBar().showMessage(f"Schema: {error_msg}", 5000)

    def _update_oe_for_session(self, widget):
        """Update Object Explorer to show the effective connection for a session/tab.

        Called when switching tabs. Determines the effective connection
        (focused block's connection or session connection) and updates OE.
        """
        if not widget or not hasattr(widget, "session"):
            return

        session = widget.session
        sid = session.session_id

        connection_group, effective_conn = self._effective_connection_for_block(
            widget.editor.get_last_focused_block()
            if hasattr(widget, "editor")
            else None,
            session,
        )

        if not effective_conn:
            # No connection - clear OE or show empty
            explorer = self._get_session_explorer(sid)
            explorer.clear()
            return

        # Check if OE is already showing this connection
        if not hasattr(self, "_oe_current_connection"):
            self._oe_current_connection = {}

        current_oe_conn = self._oe_current_connection.get(sid)
        if current_oe_conn == effective_conn:
            return  # Already showing correct schema

        # Update tracking
        self._oe_current_connection[sid] = effective_conn

        # Try cache first (per-session cache)
        cached = self._schema_service.get_cached_schema(
            effective_conn, session_id=sid, connection_group=connection_group
        )
        if cached:
            db_type = self._get_connection_db_type(effective_conn, connection_group)

            explorer = self._get_session_explorer(sid)
            explorer.set_schema(cached, effective_conn, db_type=db_type)
            return

        # Need to load schema - get connector from session (NOT shared cache!)
        connector = getattr(session, "connector", None)
        if not connector or not self._connector_is_connected(connector):
            # Fallback to connection_manager for per-block connections
            connector = self.connection_manager.get_connection(
                connection_group, effective_conn
            )
        if connector and self._connector_is_connected(connector):
            self._load_schema_with_loading(
                connector,
                effective_conn,
                session_id=sid,
                connection_group=connection_group,
            )

    def _on_block_focused(self, block, widget):
        """Called when a block gains focus. Updates Object Explorer to show the
        schema for the block's connection (or session connection if block has none).

        This makes the OE follow the 'focused connection' — per-block or per-session.
        """
        if hasattr(self, "_copilot_chat_panel") and self._copilot_chat_panel:
            try:
                self._copilot_chat_panel.notify_block_focused(block)
            except Exception:
                pass
        if not block or not widget:
            return

        session = getattr(widget, "session", None)
        if not session:
            return

        sid = session.session_id

        connection_group, effective_conn = self._effective_connection_for_block(block, session)
        if not effective_conn:
            return

        # Track what the OE is currently showing for this session to avoid unnecessary reloads
        if not hasattr(self, "_oe_current_connection"):
            self._oe_current_connection = {}  # session_id -> connection_name

        current_oe_conn = self._oe_current_connection.get(sid)
        if current_oe_conn == effective_conn:
            return  # Already showing the right schema

        # Update tracking
        self._oe_current_connection[sid] = effective_conn

        # Try to get schema from cache first (per-session cache)
        cached = self._schema_service.get_cached_schema(
            effective_conn, session_id=sid, connection_group=connection_group
        )
        if cached:
            db_type = self._get_connection_db_type(effective_conn, connection_group)

            explorer = self._get_session_explorer(sid)
            explorer.set_schema(cached, effective_conn, db_type=db_type)
            return

        # If not cached, schema loads on first autocomplete request (lazy)
        if block.get_connection_name() if hasattr(block, "get_connection_name") else None:
            return

    def request_lazy_schema_for_completion(self, block, session_widget) -> None:
        """Load tables/columns/routines when Monaco autocomplete needs schema."""
        if block is None or session_widget is None:
            return

        session = getattr(session_widget, "session", None)
        if session is None:
            return

        block_conn = block.get_connection_name() if hasattr(block, "get_connection_name") else None
        connection_group, connection_name = self._effective_connection_for_block(block, session)
        if not connection_name:
            return

        sid = session.session_id
        block_key = block.get_block_key() if hasattr(block, "get_block_key") else ""
        cached = self._schema_service.get_cached_schema(
            connection_name,
            session_id=sid,
            block_key=block_key,
            connection_group=connection_group,
        )
        if cached and cached.get("tables"):
            return

        connector = None
        if block_conn and hasattr(session_widget, "_peek_sql_connector_for_block"):
            connector = session_widget._peek_sql_connector_for_block(block, block_conn, None)
        if connector is None or not self._connector_is_connected(connector):
            connector = getattr(session, "connector", None)
        if connector is None or not self._connector_is_connected(connector):
            connector = self.connection_manager.get_connection(
                connection_group, connection_name
            )
        if connector is None or not self._connector_is_connected(connector):
            return

        self._schema_service.load_schema(
            connector,
            connection_name,
            session_id=sid,
            block_key=block_key,
            connection_group=connection_group,
            lazy_mode=SCHEMA_LAZY_AUTOCOMPLETE,
        )

    def request_databases_for_block(self, block, session_widget) -> None:
        """Load the server database list when a block's empty dropdown is clicked.

        This is the self-heal fallback for the lazy-connect path: the auto-request
        in ``_on_schema_loaded`` may not have completed (or the connector was not
        ready yet), so clicking the empty dropdown triggers the cheap single-query
        database list load on demand. Results are merged back into the cached
        schema and pushed to every block of the session via ``_on_databases_loaded``.
        """
        if block is None or session_widget is None:
            return

        session = getattr(session_widget, "session", None)
        if session is None:
            return

        block_conn = block.get_connection_name() if hasattr(block, "get_connection_name") else None
        connection_group, connection_name = self._effective_connection_for_block(block, session)
        if not connection_name:
            return

        sid = session.session_id
        cached = self._schema_service.get_cached_schema(
            connection_name, session_id=sid, connection_group=connection_group
        ) or {}
        if cached.get("databases"):
            return  # already populated

        connector = None
        if block_conn and hasattr(session_widget, "_peek_sql_connector_for_block"):
            connector = session_widget._peek_sql_connector_for_block(block, block_conn, None)
        if connector is None or not self._connector_is_connected(connector):
            connector = getattr(session, "connector", None)
        if connector is None or not self._connector_is_connected(connector):
            connector = self.connection_manager.get_connection(
                connection_group, connection_name
            )
        if connector is None or not self._connector_is_connected(connector):
            return

        self._schema_service.load_databases(connector, connection_name, session_id=sid)

    def _on_block_connection_changed(
        self,
        block,
        connection_name: str,
        *,
        session_widget=None,
    ):
        """Callback when an individual block connection changes.

        Loads schema from new connection and applies to block (in background).
        Also updates Object Explorer if this block is focused.
        This works independently of the session connection - the block can have
        its own connection even if the session is not connected.
        """
        if not connection_name:
            return

        # Try to get session_id from current widget for per-session cache
        sid = ""
        connection_group = ""
        current_widget = session_widget or self._get_current_session_widget()
        if (
            self._schema_object_is_invalid(current_widget)
            or self._schema_object_is_invalid(block)
        ):
            return
        if hasattr(current_widget, "session"):
            sid = current_widget.session.session_id
            connection_group = getattr(current_widget.session, "connection_group", "") or ""
        if block and hasattr(block, "get_connection_name") and block.get_connection_name():
            if hasattr(block, "get_connection_group"):
                connection_group = block.get_connection_group() or connection_group

        block_key = block.get_block_key() if hasattr(block, "get_block_key") else ""
        # Check cache first - if available, apply immediately (per-block cache)
        cached = self._schema_service.get_cached_schema(
            connection_name,
            session_id=sid,
            block_key=block_key,
            connection_group=connection_group,
        )
        if cached:
            db_type = self._get_connection_db_type(connection_name, connection_group)
            self._apply_schema_to_block(
                block,
                cached,
                db_type=db_type,
                connection_name=connection_name,
            )
            # Update OE if this is the focused block
            self._update_oe_for_block_connection(block, connection_name, cached)
            return

        # Need to load schema in background
        self._load_schema_for_block(
            block,
            connection_name,
            connection_group,
            session_id=sid,
            session_widget=current_widget,
        )

    def _apply_schema_to_block(
        self,
        block,
        schema: dict,
        db_type: str = "",
        connection_name: str = "",
    ):
        """Apply schema to a single block's Monaco autocomplete (isolated per block).

        Args:
            block: The CodeBlock to update
            schema: Schema dict with tables, columns, databases
            db_type: Database type (e.g., 'databricks') for special handling
            connection_name: Connection name for inline-completion context text
        """
        if self._schema_object_is_invalid(block):
            return
        if db_type and isinstance(schema, dict):
            schema = {**schema, "db_type": db_type or schema.get("db_type", "")}
        if hasattr(block, "set_sql_schema"):
            block.set_sql_schema(schema)
        elif hasattr(block, "editor") and hasattr(block.editor, "set_sql_schema"):
            block.editor.set_sql_schema(schema)
        if connection_name and hasattr(block, "set_database_context"):
            block.set_database_context(self._build_schema_context(schema, connection_name))
        resolved_db_type = str(db_type or schema.get("db_type") or "").lower()
        if hasattr(block, "set_available_databases"):
            all_databases = self._available_databases_from_schema(schema, resolved_db_type)
            block.set_available_databases(all_databases)
        if hasattr(block, "set_namespace_options") and resolved_db_type == "databricks":
            block.set_namespace_options(
                schema.get("databases") or [],
                schema.get("catalog_schemas") or {},
            )
        if resolved_db_type == "postgresql" and hasattr(block, "_sync_postgresql_schema_chip"):
            block._sync_postgresql_schema_chip()

    def _update_oe_for_block_connection(self, block, connection_name: str, schema: dict):
        """Update Object Explorer if the given block is currently focused.

        Called when a block's connection changes or when schema loads for a block.
        """
        current_widget = self._get_current_session_widget()
        if (
            self._schema_object_is_invalid(current_widget)
            or getattr(current_widget, "_is_closing", False)
            or not hasattr(current_widget, "editor")
            or not hasattr(current_widget.editor, "get_focused_block")
        ):
            return

        focused = current_widget.editor.get_focused_block()
        if focused is not block:
            return  # Only update OE if this block is focused

        session = current_widget.session
        sid = getattr(session, "session_id", None)
        if not sid:
            return

        connection_group, _ = self._effective_connection_for_block(block, session)
        db_type = self._get_connection_db_type(connection_name, connection_group)

        explorer = self._get_session_explorer(sid)
        explorer.set_schema(schema, connection_name, db_type=db_type)

        # Update tracking
        if not hasattr(self, "_oe_current_connection"):
            self._oe_current_connection = {}
        self._oe_current_connection[sid] = connection_name

    def _load_schema_for_block(
        self,
        block,
        connection_name: str,
        connection_group: str = "",
        *,
        session_id: str = "",
        session_widget=None,
    ):
        """Load schema in background and apply to specific block when ready."""
        if (
            self._schema_object_is_invalid(self)
            or self._schema_object_is_invalid(block)
            or (
                session_widget is not None
                and self._schema_object_is_invalid(session_widget)
            )
        ):
            return
        try:
            from src.database.connection_manager import ConnectionManager
            from src.workers import BlockConnectionWorker

            manager = ConnectionManager()
            if not connection_group and block and hasattr(block, "get_connection_group"):
                connection_group = block.get_connection_group() or ""
            config = manager.get_connection_config(connection_group, connection_name)
            if not config:
                self._log_info(f"Connection config not found: {connection_name}")
                return

            self.statusBar().showMessage(
                f"Loading schema for {connection_name}...", 5000
            )

            # Capture the originating session instead of resolving the active
            # tab again when the worker finishes.
            sid = session_id or ""
            if not sid and session_widget is not None:
                sid = getattr(
                    getattr(session_widget, "session", None),
                    "session_id",
                    "",
                )
            if not sid:
                sid = self._get_active_session_id() or ""
            block_key = block.get_block_key() if hasattr(block, "get_block_key") else ""

            thread = QThread()
            database_name = block.get_database_name() if hasattr(block, "get_database_name") else ""
            connect_database = database_name or config["database"]
            database_context = ""
            db_type = str(config.get("db_type") or "").lower()
            if db_type == "databricks":
                connect_database = config["database"]
                database_context = database_name or ""
            elif db_type == "postgresql":
                # PostgreSQL: the block "database" switch is actually schema
                # (search_path). The connector itself must still connect to the
                # real database to avoid treating the schema name as database.
                connect_database = config["database"]
                database_context = ""

            worker = BlockConnectionWorker(
                db_type=config["db_type"],
                host=config["host"],
                port=config["port"],
                database=connect_database,
                username=config.get("username", ""),
                password=config.get("password", ""),
                use_windows_auth=config.get("use_windows_auth", False),
                sqlserver_auth_mode=config.get("sqlserver_auth_mode", ""),
                trust_server_certificate=config.get("trust_server_certificate", False),
                http_path=config.get("http_path", ""),
                database_context=database_context,
                schema=config.get("schema") or config.get("databricks_schema") or "",
            )
            worker.moveToThread(thread)

            # When connection is ready, load schema (also in background via SchemaService)
            def on_connection_ready(connector, session_id=sid):
                if (
                    self._schema_object_is_invalid(self)
                    or self._schema_object_is_invalid(block)
                    or (
                        session_widget is not None
                        and (
                            self._schema_object_is_invalid(session_widget)
                            or getattr(session_widget, "_is_closing", False)
                        )
                    )
                ):
                    return
                if (
                    session_widget is not None
                    and block_key
                    and hasattr(session_widget, "_block_connector_pool")
                ):
                    session_widget._block_connector_pool.register(
                        block_key,
                        connection_group,
                        connection_name,
                        connector,
                    )
                self._schema_service.load_schema(
                    connector,
                    connection_name,
                    session_id=session_id,
                    block_key=block_key,
                    connection_group=connection_group,
                    lazy_mode=SCHEMA_LAZY_AUTOCOMPLETE,
                    database_context=database_context,
                )

            thread.started.connect(worker.run)
            worker.connection_ready.connect(on_connection_ready)
            worker.error.connect(
                lambda msg: self._log_info(f"Error connecting for block schema ({connection_name}): {msg}")
            )
            worker.finished.connect(thread.quit)
            thread.finished.connect(lambda: self._remove_worker_thread(thread))

            self._worker_threads.append((thread, worker))
            self._adopt_background_thread(thread, worker)
            thread.start()
        except Exception as e:
            self._log_info(f"Error loading schema for block ({connection_name}): {e}")

    def _find_block_by_key(self, block_key: str, session_id: str = "") -> object | None:
        if not block_key:
            return None
        widgets = []
        if session_id and session_id in getattr(self, "_session_widgets", {}):
            widgets = [self._session_widgets[session_id]]
        else:
            widgets = list(getattr(self, "_session_widgets", {}).values())
        for widget in widgets:
            if self._schema_object_is_invalid(widget) or getattr(widget, "_is_closing", False):
                continue
            editor = getattr(widget, "editor", None)
            if editor is None or self._schema_object_is_invalid(editor):
                continue
            for candidate in editor.get_blocks():
                if self._schema_object_is_invalid(candidate):
                    continue
                if getattr(candidate, "get_block_key", lambda: "")() == block_key:
                    return candidate
        return None

    def _load_schema_for_block_connector(
        self,
        block,
        connector,
        connection_name: str,
        session_id: str = "",
    ) -> None:
        """Reload IntelliSense schema from a block's isolated connector."""
        if not block or not connector or not connection_name:
            return
        block_key = block.get_block_key() if hasattr(block, "get_block_key") else ""
        sid = session_id or self._get_active_session_id() or ""
        connection_group = ""
        if hasattr(block, "get_connection_group"):
            connection_group = block.get_connection_group() or ""

        if sid:
            explorer = self._get_session_explorer(sid)
            explorer.set_loading(True, S.object_explorer.loading)
            self._switch_session_explorer(sid)

        self._schema_service.invalidate_cache(
            connection_name,
            session_id=sid,
            block_key=block_key,
            connection_group=connection_group,
        )
        self._schema_service.load_schema(
            connector,
            connection_name,
            session_id=sid,
            block_key=block_key,
            connection_group=connection_group,
            lazy_mode=SCHEMA_LAZY_FULL,
        )

    def _set_block_namespace_switching(self, block, switching: bool) -> None:
        setter = getattr(block, "set_namespace_switching", None)
        if callable(setter):
            setter(switching)

    def _peek_live_block_connector(
        self,
        block,
        session_widget,
        connection_group: str,
        connection_name: str,
    ):
        """Return a live connector without applying USE (never opens a new connection)."""
        block_key = block.get_block_key() if hasattr(block, "get_block_key") else ""
        pool = getattr(session_widget, "_block_connector_pool", None) if session_widget else None
        if pool is not None and block_key:
            peek = getattr(pool, "peek_connected", None)
            if callable(peek):
                connector = peek(block_key, connection_group, connection_name)
                if connector is not None:
                    return connector

        block_conn = block.get_connection_name() if hasattr(block, "get_connection_name") else None
        if block_conn:
            return None
        session = getattr(session_widget, "session", None) if session_widget else None
        connector = getattr(session, "connector", None)
        if connector is not None and self._connector_is_connected(connector):
            return connector
        return None

    def _patch_block_schema_context(self, block, database_name: str) -> None:
        """Update catalog/schema fields in-place so autocomplete follows USE immediately."""
        getter = getattr(block, "get_sql_schema", None)
        setter = getattr(block, "set_sql_schema", None)
        if not callable(getter) or not callable(setter):
            return
        schema = getter() or {}
        if not schema:
            return
        from src.database.namespace import has_dual_namespace, parse_context

        updated = dict(schema)
        db_type = str(schema.get("db_type") or "")
        if has_dual_namespace(db_type):
            ctx = parse_context(db_type, database_name)
            if ctx.catalog:
                updated["database"] = ctx.catalog
            if ctx.schema:
                updated["current_schema"] = ctx.schema
            updated["current_context"] = database_name
        else:
            if db_type == "postgresql":
                # PostgreSQL block chip represents a schema (search_path).
                # Keep the real DB in `database` and reflect the chosen schema
                # via `current_schema` / `current_context`.
                updated["current_schema"] = database_name
                updated["current_context"] = database_name
            else:
                updated["database"] = database_name
        setter(updated)

    def _maybe_set_explorer_loading_for_block(self, session_widget, block, session_id: str) -> None:
        if not session_id or session_widget is None:
            return
        editor = getattr(session_widget, "editor", None)
        focused = None
        if editor is not None:
            for name in ("get_last_focused_block", "get_focused_block"):
                getter = getattr(editor, name, None)
                if callable(getter):
                    focused = getter()
                    break
        if focused is not block:
            return
        explorer = (
            self._get_session_explorer(session_id)
            if hasattr(self, "_get_session_explorer")
            else None
        )
        if explorer is not None and hasattr(explorer, "set_loading"):
            explorer.set_loading(True, S.object_explorer.loading)

    def _on_block_database_changed(
        self,
        block,
        database_name: str,
        *,
        session_widget=None,
    ):
        """Callback when a block's database is changed.

        Switches the database of the block's connection (or session connection)
        and reloads schema for the new database to update IntelliSense.
        """
        if not database_name or block is None:
            return

        current_widget = session_widget or self._get_current_session_widget()
        if (
            self._schema_object_is_invalid(block)
            or self._schema_object_is_invalid(current_widget)
        ):
            return
        session = current_widget.session if current_widget and hasattr(current_widget, "session") else None

        connection_group, connection_name = self._effective_connection_for_block(block, session)
        if not connection_name:
            self.statusBar().showMessage(S.status.no_active_connection, 3000)
            return

        block_key = block.get_block_key() if hasattr(block, "get_block_key") else ""
        self._schema_service.invalidate_cache(
            connection_name,
            session_id=getattr(session, "session_id", "") if session else "",
            block_key=block_key,
            connection_group=connection_group,
        )

        try:
            self._set_block_namespace_switching(block, True)
            self._switch_block_database_background(
                block,
                connection_name,
                database_name,
                session_widget=current_widget,
                connection_group=connection_group,
            )
        except Exception as exc:
            self._set_block_namespace_switching(block, False)
            logger.warning("Block database change failed: %s", exc)
            self.statusBar().showMessage(str(exc)[:80], 5000)
            if current_widget is not None and hasattr(current_widget, "append_output"):
                current_widget.append_output(f"[Connection] {exc}", error=True)

    def _on_completion_log(self, message: str, level: str):
        """Handle autocomplete/completion log messages.
        
        Forwards to Copilot output panel so users can see what's happening.
        """
        if not hasattr(self, "_copilot_output_panel") or not self._copilot_output_panel:
            return
        
        output = self._copilot_output_panel
        if level == "error":
            output.log_error(message)
        elif level == "debug":
            # Only log debug when panel is visible (avoid spam)
            if hasattr(self, "copilot_output_dock") and self.copilot_output_dock.isVisible():
                output.log_info(message)
        else:
            output.log_info(message)

    def _on_cursor_position_changed(self, line: int, column: int):
        """Handle cursor position change from editor (updates statusbar)."""
        if hasattr(self, "main_statusbar"):
            self.main_statusbar.set_cursor_position(line, column)

    def _reload_block_schema_after_switch(
        self,
        block,
        connector,
        connection_name: str,
        database_name: str,
        session_widget=None,
        connection_group: str = "",
        session_id: str = "",
    ) -> None:
        """Reload autocomplete schema after a successful USE / reconnect."""
        self._set_block_namespace_switching(block, False)
        self._patch_block_schema_context(block, database_name)
        db_type = str(self._get_connection_db_type(connection_name, connection_group) or "").lower()
        block_key = block.get_block_key() if hasattr(block, "get_block_key") else ""
        self._schema_service.invalidate_cache(
            connection_name,
            session_id=session_id,
            block_key=block_key,
            connection_group=connection_group,
        )
        database_context_for_service = database_name
        if db_type == "postgresql":
            # For PostgreSQL the block's "database_name" is the chosen schema
            # (search_path). SchemaService caching expects the real DB context.
            # Tables/columns do not change — avoid OE "Loading schema..." overlay.
            try:
                getter = getattr(connector, "get_current_database", None)
                database_context_for_service = (
                    str(getter() or "") if callable(getter) else ""
                )
            except Exception:
                database_context_for_service = ""
            # Reflect active schema on OE immediately from the patched block schema.
            if session_id and hasattr(self, "_session_explorers"):
                explorer = self._session_explorers.get(session_id)
                if explorer is not None and hasattr(explorer, "_current_schema"):
                    oe_schema = dict(getattr(explorer, "_current_schema") or {})
                    if oe_schema:
                        oe_schema["current_schema"] = database_name
                        oe_schema["db_type"] = "postgresql"
                        explorer.set_schema(
                            oe_schema, connection_name, db_type="postgresql"
                        )
        else:
            self._maybe_set_explorer_loading_for_block(session_widget, block, session_id)
        self._schema_service.load_schema(
            connector,
            connection_name,
            session_id=session_id,
            block_key=block_key,
            connection_group=connection_group,
            lazy_mode=SCHEMA_LAZY_AUTOCOMPLETE,
            database_context=database_context_for_service,
        )
        self.statusBar().showMessage(
            S.status.database_changed.format(name=database_name), 3000
        )

    def _switch_block_database_via_use(
        self,
        block,
        connector,
        connection_name: str,
        database_name: str,
        session_widget=None,
        connection_group: str = "",
        session_id: str = "",
    ) -> None:
        """Switch catalog/schema with USE on an existing connector."""
        from src.workers import DatabaseSwitchWorker

        thread = QThread()
        worker = DatabaseSwitchWorker(connector, database_name)
        worker.moveToThread(thread)

        def on_switch_success(_db, session_id=session_id):
            if (
                self._schema_object_is_invalid(self)
                or self._schema_object_is_invalid(block)
                or (
                    session_widget is not None
                    and (
                        self._schema_object_is_invalid(session_widget)
                        or getattr(session_widget, "_is_closing", False)
                    )
                )
            ):
                return
            self._reload_block_schema_after_switch(
                block,
                connector,
                connection_name,
                database_name,
                session_widget=session_widget,
                connection_group=connection_group,
                session_id=session_id,
            )

        def on_switch_error(msg: str, widget=session_widget):
            self._set_block_namespace_switching(block, False)
            short = (msg or "Database switch failed")[:120]
            self.statusBar().showMessage(f"Error: {short[:50]}", 5000)
            if widget is not None and hasattr(widget, "append_output"):
                widget.append_output(short, error=True)

        thread.started.connect(worker.run)
        worker.switch_success.connect(on_switch_success)
        worker.error.connect(on_switch_error)
        worker.finished.connect(thread.quit)
        thread.finished.connect(lambda: self._remove_worker_thread(thread))

        self._worker_threads.append((thread, worker))
        self._adopt_background_thread(thread, worker)
        thread.start()

    def _switch_block_database_background(
        self,
        block,
        connection_name: str,
        database_name: str,
        session_widget=None,
        connection_group: str = "",
    ):
        """Switch database for a block connection in background (never blocks UI)."""
        if (
            self._schema_object_is_invalid(self)
            or self._schema_object_is_invalid(block)
            or (
                session_widget is not None
                and self._schema_object_is_invalid(session_widget)
            )
        ):
            self._set_block_namespace_switching(block, False)
            return
        from src.database.connection_manager import ConnectionManager
        from src.workers import BlockConnectionWorker

        manager = ConnectionManager()
        if not connection_group and block and hasattr(block, "get_connection_group"):
            connection_group = block.get_connection_group() or ""
        config = manager.get_connection_config(connection_group, connection_name)
        if not config:
            self._set_block_namespace_switching(block, False)
            self._log_info(f"Connection config not found: {connection_name}")
            return

        self.statusBar().showMessage(
            f"Switching to database {database_name}...", 5000
        )

        # Capture the originating session instead of resolving the active tab
        # again when the worker completes.
        sid = ""
        if session_widget is not None and hasattr(session_widget, "session"):
            sid = getattr(session_widget.session, "session_id", "") or ""
        if not sid:
            sid = self._get_active_session_id() or ""

        live_connector = self._peek_live_block_connector(
            block, session_widget, connection_group, connection_name
        )
        if live_connector is not None:
            self._switch_block_database_via_use(
                block,
                live_connector,
                connection_name,
                database_name,
                session_widget=session_widget,
                connection_group=connection_group,
                session_id=sid,
            )
            return

        # Create connection with the NEW database
        thread = QThread()
        connect_database = database_name
        database_context = ""
        db_type_conn = str(config.get("db_type") or "").lower()
        if db_type_conn == "databricks":
            connect_database = config["database"]
            database_context = database_name
        elif db_type_conn == "postgresql":
            # For PostgreSQL the chip value is schema (search_path), not the real database.
            connect_database = config["database"]
            database_context = database_name

        worker = BlockConnectionWorker(
            db_type=config["db_type"],
            host=config["host"],
            port=config["port"],
            database=connect_database,
            username=config.get("username", ""),
            password=config.get("password", ""),
            use_windows_auth=config.get("use_windows_auth", False),
            sqlserver_auth_mode=config.get("sqlserver_auth_mode", ""),
            trust_server_certificate=config.get("trust_server_certificate", False),
            http_path=config.get("http_path", ""),
            database_context=database_context,
            schema=(
                database_name
                if db_type_conn == "postgresql" and database_name
                else (config.get("schema") or config.get("databricks_schema") or "")
            ),
        )
        worker.moveToThread(thread)

        def on_connection_ready(connector, session_id=sid):
            if (
                self._schema_object_is_invalid(self)
                or self._schema_object_is_invalid(block)
                or (
                    session_widget is not None
                    and (
                        self._schema_object_is_invalid(session_widget)
                        or getattr(session_widget, "_is_closing", False)
                    )
                )
            ):
                return
            block_key = block.get_block_key() if hasattr(block, "get_block_key") else ""
            if (
                session_widget is not None
                and block_key
                and hasattr(session_widget, "_block_connector_pool")
            ):
                session_widget._block_connector_pool.register(
                    block_key,
                    connection_group,
                    connection_name,
                    connector,
                )

            self._reload_block_schema_after_switch(
                block,
                connector,
                connection_name,
                database_name,
                session_widget=session_widget,
                connection_group=connection_group,
                session_id=session_id,
            )

        thread.started.connect(worker.run)
        worker.connection_ready.connect(on_connection_ready)
        def _on_block_db_error(msg: str, widget=session_widget):
            self._set_block_namespace_switching(block, False)
            short = (msg or "Connection failed")[:120]
            self.statusBar().showMessage(f"Error: {short[:50]}", 5000)
            if widget is not None and hasattr(widget, "append_output"):
                widget.append_output(short, error=True)

        worker.error.connect(_on_block_db_error)
        worker.finished.connect(thread.quit)
        thread.finished.connect(lambda: self._remove_worker_thread(thread))

        self._worker_threads.append((thread, worker))
        self._adopt_background_thread(thread, worker)
        thread.start()

    def _on_insert_variable_in_editor(self, var_name: str):
        """Inserts variable name in the focused editor of the active session"""
        current_widget = self._get_current_session_widget()
        if current_widget and hasattr(current_widget, "editor"):
            editor = current_widget.editor
            block = (
                editor.get_last_focused_block()
                if hasattr(editor, "get_last_focused_block")
                else editor.get_focused_block()
            )
            if block and hasattr(block, "editor") and hasattr(block.editor, "insert_text_at_cursor"):
                block.editor.insert_text_at_cursor(var_name)
                block.editor.setFocus()

    def _on_delete_variable(self, var_name: str):
        """Removes variable from the active session namespace"""
        current_widget = self._get_current_session_widget()
        if current_widget and hasattr(current_widget, "session"):
            ns = current_widget.session.namespace
            if var_name in ns:
                del ns[var_name]
                current_widget.session.variables_changed.emit(ns)

    def _on_show_variable_in_results(self, var_name: str, value):
        """Displays a DataFrame or Series in the active session's Results panel"""
        import pandas as pd

        if isinstance(value, pd.Series):
            df = value.to_frame(name=var_name)
        elif isinstance(value, pd.DataFrame):
            df = value
        else:
            return

        current_widget = self._get_current_session_widget()
        if not current_widget:
            return

        session_id = current_widget.session.session_id
        info = self._session_panel_indices.get(session_id)
        viewer = info["results"] if info else None

        if viewer:
            viewer.display_dataframe(df, var_name)
            self.show_panel("results")

    def _push_python_namespace(self, namespace: dict):
        """Sends updated Python namespace to code editors.

        Chamado apos execucao Python para alimentar autocomplete.
        """
        # Construir mapa varName -> typeName
        ns_types = {}
        for key, value in namespace.items():
            if key.startswith("_"):
                continue
            # Pular modulos internos e funcoes builtin
            type_name = type(value).__name__
            if type_name in ("module",):
                ns_types[key] = "module"
            elif type_name in ("function", "builtin_function_or_method"):
                ns_types[key] = "function"
            elif type_name == "type":
                ns_types[key] = "class"
            else:
                ns_types[key] = type_name

        current_widget = self._get_current_session_widget()
        if current_widget and hasattr(current_widget, "editor") and hasattr(
            current_widget.editor, "refresh_completion_context"
        ):
            current_widget.editor.refresh_completion_context()
