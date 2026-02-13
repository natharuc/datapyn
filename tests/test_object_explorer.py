"""
Testes para ObjectExplorerPanel

Cobre: construcao de arvore, set_schema, clear,
context menu, duplo clique, sinais emitidos.
"""

import pytest
from unittest.mock import MagicMock, patch
from PyQt6.QtWidgets import QMainWindow, QTreeWidgetItem
from PyQt6.QtCore import Qt
from src.ui.components.object_explorer_panel import ObjectExplorerPanel


@pytest.fixture
def sample_schema():
    """Schema de exemplo para testes"""
    return {
        "database": "testdb",
        "tables": [
            {"name": "users", "schema": "dbo", "type": "BASE TABLE"},
            {"name": "orders", "schema": "dbo", "type": "BASE TABLE"},
            {"name": "v_summary", "schema": "dbo", "type": "VIEW"},
        ],
        "columns": {
            "users": [
                {"name": "id", "type": "int", "nullable": "NO"},
                {"name": "name", "type": "varchar", "nullable": "YES"},
                {"name": "email", "type": "varchar", "nullable": "YES"},
            ],
            "orders": [
                {"name": "order_id", "type": "int", "nullable": "NO"},
                {"name": "user_id", "type": "int", "nullable": "NO"},
                {"name": "total", "type": "decimal", "nullable": "YES"},
            ],
            "v_summary": [
                {"name": "user_name", "type": "varchar", "nullable": "YES"},
                {"name": "order_count", "type": "int", "nullable": "YES"},
            ],
        },
    }


@pytest.fixture
def multi_schema():
    """Schema com multiplos schemas (para testar agrupamento)"""
    return {
        "database": "testdb",
        "tables": [
            {"name": "users", "schema": "dbo", "type": "BASE TABLE"},
            {"name": "logs", "schema": "audit", "type": "BASE TABLE"},
        ],
        "columns": {
            "users": [
                {"name": "id", "type": "int", "nullable": "NO"},
            ],
            "logs": [
                {"name": "log_id", "type": "int", "nullable": "NO"},
            ],
        },
    }


@pytest.fixture
def explorer(qtbot):
    """ObjectExplorerPanel para testes"""
    main = QMainWindow()
    qtbot.addWidget(main)
    panel = ObjectExplorerPanel()
    main.setCentralWidget(panel)
    main.show()
    qtbot.waitExposed(main)
    panel._test_main = main  # manter referencia para nao ser coletado
    return panel


class TestObjectExplorerCreation:
    """Testes de criacao do painel"""

    def test_panel_created(self, explorer):
        """Painel criado com sucesso"""
        assert explorer is not None
        assert explorer.tree is not None

    def test_initial_state_empty(self, explorer):
        """Estado inicial sem dados"""
        assert explorer.tree.topLevelItemCount() == 0
        assert explorer.info_label.text() == "Nenhuma conexao"

    def test_has_refresh_button(self, explorer):
        """Botao refresh existe"""
        assert explorer.btn_refresh is not None


class TestObjectExplorerSetSchema:
    """Testes de set_schema e construcao de arvore"""

    def test_set_schema_builds_tree(self, explorer, sample_schema):
        """set_schema constroi arvore corretamente"""
        explorer.set_schema(sample_schema, "conn1")

        # Deve ter 1 item raiz (banco)
        assert explorer.tree.topLevelItemCount() == 1

        db_item = explorer.tree.topLevelItem(0)
        assert db_item is not None
        assert "testdb" in db_item.text(0)

    def test_set_schema_shows_tables(self, explorer, sample_schema):
        """Tabelas aparecem na arvore"""
        explorer.set_schema(sample_schema, "conn1")

        db_item = explorer.tree.topLevelItem(0)
        # Com apenas um schema, tabelas ficam diretamente sob o banco
        table_names = []
        for i in range(db_item.childCount()):
            child = db_item.child(i)
            data = child.data(0, Qt.ItemDataRole.UserRole)
            if data and data.get("type") == "table":
                table_names.append(data["name"])

        assert "users" in table_names
        assert "orders" in table_names

    def test_set_schema_shows_columns(self, explorer, sample_schema):
        """Colunas aparecem sob tabelas"""
        explorer.set_schema(sample_schema, "conn1")

        db_item = explorer.tree.topLevelItem(0)
        # Encontrar tabela "users"
        users_item = None
        for i in range(db_item.childCount()):
            child = db_item.child(i)
            data = child.data(0, Qt.ItemDataRole.UserRole)
            if data and data.get("type") == "table" and data.get("name") == "users":
                users_item = child
                break

        assert users_item is not None
        # Users tem 3 colunas
        assert users_item.childCount() == 3

        # Verificar primeira coluna
        col_item = users_item.child(0)
        data = col_item.data(0, Qt.ItemDataRole.UserRole)
        assert data["type"] == "column"
        assert data["name"] == "id"
        assert data["data_type"] == "int"

    def test_set_schema_views_labeled(self, explorer, sample_schema):
        """Views sao identificadas com label (view)"""
        explorer.set_schema(sample_schema, "conn1")

        db_item = explorer.tree.topLevelItem(0)
        view_found = False
        for i in range(db_item.childCount()):
            child = db_item.child(i)
            data = child.data(0, Qt.ItemDataRole.UserRole)
            if data and data.get("type") == "table" and data.get("name") == "v_summary":
                assert "(view)" in child.text(0)
                view_found = True
                break

        assert view_found

    def test_set_schema_updates_info(self, explorer, sample_schema):
        """Info label atualizado apos set_schema"""
        explorer.set_schema(sample_schema, "conn1")
        assert "3 tabelas" in explorer.info_label.text()
        assert "8 colunas" in explorer.info_label.text()

    def test_set_schema_multiple_schemas(self, explorer, multi_schema):
        """Multiplos schemas criam nos intermediarios"""
        explorer.set_schema(multi_schema, "conn1")

        db_item = explorer.tree.topLevelItem(0)
        # Com 2 schemas, deve criar nos de schema
        schema_names = []
        for i in range(db_item.childCount()):
            child = db_item.child(i)
            data = child.data(0, Qt.ItemDataRole.UserRole)
            if data and data.get("type") == "schema":
                schema_names.append(data["name"])

        assert "dbo" in schema_names
        assert "audit" in schema_names

    def test_db_item_expanded_by_default(self, explorer, sample_schema):
        """Item do banco expandido por padrao"""
        explorer.set_schema(sample_schema, "conn1")

        db_item = explorer.tree.topLevelItem(0)
        assert db_item.isExpanded()


class TestObjectExplorerClear:
    """Testes de clear"""

    def test_clear_removes_all(self, explorer, sample_schema):
        """Clear limpa tudo"""
        explorer.set_schema(sample_schema, "conn1")
        assert explorer.tree.topLevelItemCount() > 0

        explorer.clear()
        assert explorer.tree.topLevelItemCount() == 0
        assert explorer.info_label.text() == "Nenhuma conexao"

    def test_clear_resets_schema(self, explorer, sample_schema):
        """Clear reseta schema interno"""
        explorer.set_schema(sample_schema, "conn1")
        explorer.clear()
        assert explorer._current_schema is None
        assert explorer._current_connection == ""


class TestObjectExplorerSignals:
    """Testes de sinais emitidos"""

    def test_double_click_table_emits_signal(self, explorer, sample_schema, qtbot):
        """Duplo clique em tabela emite insert_text_requested"""
        explorer.set_schema(sample_schema, "conn1")

        # Encontrar item da tabela "users"
        db_item = explorer.tree.topLevelItem(0)
        users_item = None
        for i in range(db_item.childCount()):
            child = db_item.child(i)
            data = child.data(0, Qt.ItemDataRole.UserRole)
            if data and data.get("type") == "table" and data.get("name") == "users":
                users_item = child
                break

        assert users_item is not None

        with qtbot.waitSignal(explorer.insert_text_requested, timeout=1000) as blocker:
            explorer._on_double_click(users_item, 0)

        assert blocker.args == ["users"]

    def test_double_click_column_emits_signal(self, explorer, sample_schema, qtbot):
        """Duplo clique em coluna emite insert_text_requested"""
        explorer.set_schema(sample_schema, "conn1")

        # Encontrar coluna "id" de users
        db_item = explorer.tree.topLevelItem(0)
        col_item = None
        for i in range(db_item.childCount()):
            child = db_item.child(i)
            data = child.data(0, Qt.ItemDataRole.UserRole)
            if data and data.get("type") == "table" and data.get("name") == "users":
                col_item = child.child(0)  # primeira coluna
                break

        assert col_item is not None

        with qtbot.waitSignal(explorer.insert_text_requested, timeout=1000) as blocker:
            explorer._on_double_click(col_item, 0)

        assert blocker.args == ["id"]

    def test_double_click_database_no_signal(self, explorer, sample_schema, qtbot):
        """Duplo clique em banco nao emite sinal"""
        explorer.set_schema(sample_schema, "conn1")

        db_item = explorer.tree.topLevelItem(0)
        # Nao deve emitir sinal para database
        with qtbot.assertNotEmitted(explorer.insert_text_requested):
            explorer._on_double_click(db_item, 0)


class TestObjectExplorerEmptySchema:
    """Testes com schema vazio"""

    def test_empty_schema(self, explorer):
        """Schema vazio"""
        explorer.set_schema({"tables": [], "columns": {}, "database": ""})
        db_item = explorer.tree.topLevelItem(0)
        assert db_item is not None
        assert db_item.childCount() == 0

    def test_none_schema(self, explorer):
        """Schema None"""
        explorer.set_schema(None)
        assert explorer.tree.topLevelItemCount() == 0

    def test_schema_no_columns(self, explorer):
        """Schema com tabelas mas sem colunas"""
        schema = {
            "database": "db",
            "tables": [{"name": "t1", "schema": "", "type": "BASE TABLE"}],
            "columns": {},
        }
        explorer.set_schema(schema)
        db_item = explorer.tree.topLevelItem(0)
        assert db_item.childCount() == 1

        table_item = db_item.child(0)
        assert table_item.childCount() == 0


class TestObjectExplorerNotNull:
    """Testes de NOT NULL em colunas"""

    def test_not_null_displayed(self, explorer, sample_schema):
        """Colunas NOT NULL exibidas corretamente"""
        explorer.set_schema(sample_schema, "conn1")

        db_item = explorer.tree.topLevelItem(0)
        for i in range(db_item.childCount()):
            child = db_item.child(i)
            data = child.data(0, Qt.ItemDataRole.UserRole)
            if data and data.get("type") == "table" and data.get("name") == "users":
                # Primeira coluna "id" e NOT NULL
                col_item = child.child(0)
                assert "NOT NULL" in col_item.text(0)
                # Segunda coluna "name" e nullable
                col_item2 = child.child(1)
                assert "NOT NULL" not in col_item2.text(0)
                break
