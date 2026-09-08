from __future__ import annotations

from dataclasses import dataclass
from unittest.mock import MagicMock, patch

import pytest

from src.ui.main_window._schema import SchemaMixin


@dataclass
class _DummyBlock:
    _sql_schema: dict
    _database_name: str | None = None

    def get_sql_schema(self) -> dict:
        return self._sql_schema

    def set_sql_schema(self, schema: dict) -> None:
        self._sql_schema = schema or {}

    def get_database_name(self) -> str | None:
        return self._database_name


def test_postgresql_patch_block_schema_context_sets_current_schema():
    mixin = SchemaMixin()

    initial = {
        "db_type": "postgresql",
        "database": "real_db",
        "current_schema": "",
        "current_context": "",
        "tables": [],
        "columns": {},
    }
    block = _DummyBlock(_sql_schema=initial)

    mixin._patch_block_schema_context(block, "my_schema")

    updated = block.get_sql_schema()
    assert updated["database"] == "real_db"  # real database must remain
    assert updated["current_schema"] == "my_schema"
    assert updated["current_context"] == "my_schema"


def test_postgresql_schema_match_uses_current_schema_not_database():
    mixin = SchemaMixin()
    block = _DummyBlock(
        _sql_schema={"db_type": "postgresql", "database": "azdo_metrics"},
        _database_name="metrics",
    )
    schema = {
        "db_type": "postgresql",
        "database": "azdo_metrics",
        "requested_context": "azdo_metrics",
        "connection_context": "azdo_metrics",
        "current_schema": "metrics",
    }
    assert mixin._schema_matches_block_database(block, schema) is True

    schema["current_schema"] = "public"
    assert mixin._schema_matches_block_database(block, schema) is False


def test_postgresql_available_databases_are_schemas():
    mixin = SchemaMixin()
    schema = {
        "db_type": "postgresql",
        "databases": ["azdo_metrics"],
        "schemas": ["public", "metrics"],
        "tables": [],
    }
    assert mixin._available_databases_from_schema(schema, "postgresql") == [
        "public",
        "metrics",
    ]


def test_postgresql_change_database_keeps_real_database():
    from src.database.database_connector import DatabaseConnector

    connector = DatabaseConnector()
    connector.db_type = "postgresql"
    connector.engine = MagicMock()
    connector.connection_params = {
        "database": "azdo_metrics",
        "postgresql_schema": "public",
    }

    conn_cm = MagicMock()
    conn = MagicMock()
    conn_cm.__enter__.return_value = conn
    conn_cm.__exit__.return_value = None
    connector.engine.connect.return_value = conn_cm

    assert connector.change_database("metrics") is True
    assert connector.connection_params["database"] == "azdo_metrics"
    assert connector.connection_params["postgresql_schema"] == "metrics"
    assert connector.get_current_schema() == "metrics"
    conn.execute.assert_called()
    executed = str(conn.execute.call_args[0][0])
    assert "search_path" in executed.lower()
    assert "metrics" in executed


def test_resolve_block_database_targets_postgresql(qapp):
    from src.core.session import Session
    from src.ui.components.session_widget import SessionWidget

    session = Session("pg-targets", title="pg")
    widget = SessionWidget(session)
    config = {"db_type": "postgresql", "database": "azdo_metrics"}
    connect_db, context = widget._resolve_block_database_targets(
        config, "metrics", None
    )
    assert connect_db == "azdo_metrics"
    assert context == "metrics"
    widget.close()


def test_connect_connector_from_config_postgresql_uses_real_db_and_schema():
    from src.database.block_connector_pool import connect_connector_from_config

    connector = MagicMock()
    connector.is_connected.return_value = True
    config = {
        "db_type": "postgresql",
        "host": "localhost",
        "port": 5432,
        "database": "azdo_metrics",
        "username": "u",
        "password": "",
        "schema": "public",
    }

    with patch(
        "src.database.block_connector_pool.DatabaseConnector", return_value=connector
    ):
        connect_connector_from_config(
            config,
            database="metrics",  # must not become connect database
            database_context="metrics",
        )

    kwargs = connector.connect.call_args.kwargs
    assert kwargs["database"] == "azdo_metrics"
    assert kwargs["schema"] == "metrics"


def test_object_explorer_postgresql_groups_duplicate_table_names(qapp, qtbot):
    from PyQt6.QtCore import Qt
    from PyQt6.QtWidgets import QMainWindow

    from src.ui.components.object_explorer_panel import ObjectExplorerPanel

    main = QMainWindow()
    qtbot.addWidget(main)
    panel = ObjectExplorerPanel()
    main.setCentralWidget(panel)
    main.show()
    qtbot.waitExposed(main)

    schema = {
        "db_type": "postgresql",
        "database": "azdo_metrics",
        "databases": ["azdo_metrics"],
        "schemas": ["metrics", "public"],
        "current_schema": "metrics",
        "tables": [
            {"name": "__EFMigrationsHistory", "schema": "metrics", "type": "TABLE"},
            {"name": "__EFMigrationsHistory", "schema": "public", "type": "TABLE"},
            {"name": "GlobalMilestones", "schema": "metrics", "type": "TABLE"},
        ],
        "columns": {},
    }
    panel.set_schema(schema, "azdo_metrics", db_type="postgresql")

    assert panel.tree.topLevelItemCount() == 1
    db_item = panel.tree.topLevelItem(0)
    assert db_item.text(0) == "azdo_metrics"

    schema_names = []
    for i in range(db_item.childCount()):
        child = db_item.child(i)
        role = child.data(0, Qt.ItemDataRole.UserRole) or {}
        assert role.get("type") == "schema"
        schema_names.append(role.get("name"))
        table_names = [child.child(j).text(0) for j in range(child.childCount())]
        assert table_names.count("__EFMigrationsHistory") <= 1

    assert "metrics" in schema_names
    assert "public" in schema_names
    # No flat table duplicates under the database root
    for i in range(db_item.childCount()):
        role = db_item.child(i).data(0, Qt.ItemDataRole.UserRole) or {}
        assert role.get("type") != "table"


def test_connection_edit_dialog_postgresql_shows_schema_default(qapp, qtbot):
    from src.ui.dialogs.connection_edit_dialog import ConnectionEditDialog

    dlg = ConnectionEditDialog(
        connection_name="azdo",
        config={
            "db_type": "postgresql",
            "host": "localhost",
            "port": 5432,
            "database": "azdo_metrics",
        },
    )
    qtbot.addWidget(dlg)
    assert not dlg.txt_schema.isHidden()
    assert dlg.txt_schema.text() == "public"
    _name, config = dlg.get_result()
    assert config["db_type"] == "postgresql"
    assert config["schema"] == "public"
    dlg.close()


def test_connection_edit_dialog_postgresql_keeps_custom_schema(qapp, qtbot):
    from src.ui.dialogs.connection_edit_dialog import ConnectionEditDialog

    dlg = ConnectionEditDialog(
        connection_name="azdo",
        config={
            "db_type": "postgresql",
            "host": "localhost",
            "port": 5432,
            "database": "azdo_metrics",
            "schema": "metrics",
        },
    )
    qtbot.addWidget(dlg)
    assert dlg.txt_schema.text() == "metrics"
    dlg.txt_schema.setText("metrics")
    _name, config = dlg.get_result()
    assert config["schema"] == "metrics"
    dlg.close()


def test_update_connection_config_persists_postgresql_schema(tmp_path):
    from src.database.connection_manager import ConnectionManager

    manager = ConnectionManager(config_path=str(tmp_path / "connections.json"))
    manager.save_connection_config(
        name="azdo",
        db_type="postgresql",
        host="localhost",
        port=5432,
        database="azdo_metrics",
        schema="public",
    )
    manager.update_connection_config(
        "",
        "azdo",
        "azdo",
        "postgresql",
        "localhost",
        5432,
        "azdo_metrics",
        schema="metrics",
    )
    saved = manager.get_connection_config("", "azdo")
    assert saved["schema"] == "metrics"

    # Omitting schema on update must not reset it to public.
    manager.update_connection_config(
        "",
        "azdo",
        "azdo",
        "postgresql",
        "localhost",
        5432,
        "azdo_metrics",
    )
    saved = manager.get_connection_config("", "azdo")
    assert saved["schema"] == "metrics"


def test_postgresql_chip_shows_schema_not_database(qapp):
    from src.editors.code_block import CodeBlock

    block = CodeBlock(default_language="sql")
    block.set_connection_name("azdo", "postgresql")
    block._database_name = "azdo_metrics"
    block.set_sql_schema(
        {
            "db_type": "postgresql",
            "database": "azdo_metrics",
            "databases": ["azdo_metrics"],
            "current_schema": "metrics",
            "schemas": ["metrics", "public"],
        }
    )
    assert block.db_panel.isHidden()
    assert not block.catalog_panel.isHidden()
    assert not block.schema_panel.isHidden()
    assert block.catalog_panel._kind == "database"
    assert block.schema_panel._kind == "schema"
    assert block.catalog_panel.name_label.text() == "azdo_metrics"
    assert block.schema_panel.name_label.text() == "metrics"
    assert block.get_database_name() is None


def test_postgresql_set_database_name_rejects_real_database(qapp):
    from src.editors.code_block import CodeBlock

    block = CodeBlock(default_language="sql")
    block.set_connection_name("azdo", "postgresql")
    block.set_sql_schema(
        {
            "db_type": "postgresql",
            "database": "azdo_metrics",
            "databases": ["azdo_metrics"],
            "current_schema": "public",
            "schemas": ["metrics", "public"],
        }
    )
    block.set_database_name("azdo_metrics")
    assert block.get_database_name() is None
    assert block.schema_panel.name_label.text() == "public"

    block.set_database_name("metrics")
    assert block.get_database_name() == "metrics"
    assert block.schema_panel.name_label.text() == "metrics"


def test_postgresql_change_database_ignores_real_database_name():
    from src.database.database_connector import DatabaseConnector

    connector = DatabaseConnector()
    connector.db_type = "postgresql"
    connector.engine = MagicMock()
    connector.connection_params = {
        "database": "azdo_metrics",
        "postgresql_schema": "public",
    }

    assert connector.change_database("azdo_metrics") is True
    assert connector.connection_params["postgresql_schema"] == "public"
    connector.engine.connect.assert_not_called()


def test_get_connector_switch_chip_value_postgresql_is_schema():
    from src.database.database_connector import get_connector_switch_chip_value

    connector = MagicMock()
    connector.db_type = "postgresql"
    connector.get_current_schema.return_value = "metrics"
    connector.get_current_database_context.return_value = "azdo_metrics"
    connector.get_current_database.return_value = "azdo_metrics"

    assert get_connector_switch_chip_value(connector) == "metrics"


def test_postgresql_search_path_sql_quotes_ident():
    from src.database.database_connector import DatabaseConnector

    assert DatabaseConnector._postgresql_search_path_sql("metrics") == 'SET search_path TO "metrics"'
    assert DatabaseConnector._postgresql_search_path_sql('a"b') == 'SET search_path TO "a""b"'


def test_postgresql_connection_string_includes_search_path():
    from src.database.database_connector import DatabaseConnector

    connector = DatabaseConnector()
    _url, connect_args = connector._build_connection_string(
        "postgresql",
        "localhost",
        5432,
        "azdo_metrics",
        "user",
        "pass",
        schema="metrics",
    )
    assert "search_path=metrics" in str(connect_args.get("options") or "")
