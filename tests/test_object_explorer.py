"""
Testes para ObjectExplorerPanel

Cobre: construcao de arvore, set_schema, clear,
context menu, duplo clique, sinais emitidos,
busca/filtro, multiplos bancos, troca de banco.
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
def multi_db_schema():
    """Schema com lista de multiplos bancos do servidor"""
    return {
        "database": "testdb",
        "databases": ["master", "testdb", "production"],
        "tables": [
            {"name": "users", "schema": "dbo", "type": "BASE TABLE"},
        ],
        "columns": {
            "users": [
                {"name": "id", "type": "int", "nullable": "NO"},
                {"name": "name", "type": "varchar", "nullable": "YES"},
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

    def test_has_search_input(self, explorer):
        """Campo de busca existe"""
        assert explorer.search_input is not None
        assert explorer.search_input.placeholderText() != ""


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


class TestObjectExplorerMultipleDatabases:
    """Testes de exibicao de multiplos bancos"""

    def test_multi_db_shows_all_databases(self, explorer, multi_db_schema):
        """Todos os bancos do servidor aparecem como nos raiz"""
        explorer.set_schema(multi_db_schema, "conn1")

        # Deve ter 3 nos raiz (3 bancos)
        assert explorer.tree.topLevelItemCount() == 3

    def test_multi_db_current_marked(self, explorer, multi_db_schema):
        """Banco conectado esta marcado com (conectado)"""
        explorer.set_schema(multi_db_schema, "conn1")

        found_connected = False
        for i in range(explorer.tree.topLevelItemCount()):
            item = explorer.tree.topLevelItem(i)
            data = item.data(0, Qt.ItemDataRole.UserRole)
            if data and data.get("name") == "testdb":
                assert "(conectado)" in item.text(0)
                found_connected = True
                break
        assert found_connected

    def test_multi_db_current_has_tables(self, explorer, multi_db_schema):
        """Apenas banco conectado tem tabelas carregadas"""
        explorer.set_schema(multi_db_schema, "conn1")

        for i in range(explorer.tree.topLevelItemCount()):
            item = explorer.tree.topLevelItem(i)
            data = item.data(0, Qt.ItemDataRole.UserRole)
            if data and data.get("name") == "testdb":
                assert item.childCount() > 0  # tem tabelas
            else:
                assert item.childCount() == 0  # sem tabelas

    def test_multi_db_info_shows_db_count(self, explorer, multi_db_schema):
        """Info label mostra contagem de bancos"""
        explorer.set_schema(multi_db_schema, "conn1")
        assert "3 bancos" in explorer.info_label.text()


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

    def test_clear_resets_search(self, explorer, sample_schema):
        """Clear limpa campo de busca"""
        explorer.set_schema(sample_schema, "conn1")
        explorer.search_input.setText("users")
        explorer.clear()
        assert explorer.search_input.text() == ""


class TestObjectExplorerSearch:
    """Testes do campo de busca"""

    def test_search_filters_tables(self, explorer, sample_schema):
        """Buscar filtra tabelas pelo nome"""
        explorer.set_schema(sample_schema, "conn1")
        explorer.search_input.setText("users")
        explorer._apply_filter()  # Aplicar filtro imediatamente (sem debounce)

        db_item = explorer.tree.topLevelItem(0)
        visible_tables = []
        for i in range(db_item.childCount()):
            child = db_item.child(i)
            data = child.data(0, Qt.ItemDataRole.UserRole)
            if data and data.get("type") == "table":
                visible_tables.append(data["name"])

        assert "users" in visible_tables
        assert "orders" not in visible_tables

    def test_search_filters_by_column(self, explorer, sample_schema):
        """Buscar por nome de coluna mostra tabela pai"""
        explorer.set_schema(sample_schema, "conn1")
        explorer.search_input.setText("email")
        explorer._apply_filter()

        db_item = explorer.tree.topLevelItem(0)
        visible_tables = []
        for i in range(db_item.childCount()):
            child = db_item.child(i)
            data = child.data(0, Qt.ItemDataRole.UserRole)
            if data and data.get("type") == "table":
                visible_tables.append(data["name"])

        assert "users" in visible_tables  # tem coluna "email"
        assert "orders" not in visible_tables

    def test_search_filters_columns_individually(self, explorer, sample_schema):
        """Buscar filtra colunas individualmente dentro de cada tabela"""
        explorer.set_schema(sample_schema, "conn1")
        explorer.search_input.setText("email")
        explorer._apply_filter()

        db_item = explorer.tree.topLevelItem(0)
        # Encontrar tabela users
        users_item = None
        for i in range(db_item.childCount()):
            child = db_item.child(i)
            data = child.data(0, Qt.ItemDataRole.UserRole)
            if data and data.get("type") == "table" and data.get("name") == "users":
                users_item = child
                break

        assert users_item is not None
        # So coluna "email" deve aparecer, nao "id" ou "name"
        col_names = []
        for i in range(users_item.childCount()):
            col_data = users_item.child(i).data(0, Qt.ItemDataRole.UserRole)
            col_names.append(col_data["name"])
        assert "email" in col_names
        assert "id" not in col_names

    def test_search_empty_shows_all(self, explorer, sample_schema):
        """Busca vazia mostra todas as tabelas"""
        explorer.set_schema(sample_schema, "conn1")
        explorer.search_input.setText("users")
        explorer._apply_filter()
        explorer.search_input.setText("")  # limpar busca
        explorer._apply_filter()

        db_item = explorer.tree.topLevelItem(0)
        visible_tables = []
        for i in range(db_item.childCount()):
            child = db_item.child(i)
            data = child.data(0, Qt.ItemDataRole.UserRole)
            if data and data.get("type") == "table":
                visible_tables.append(data["name"])

        assert len(visible_tables) == 3  # todas as tabelas

    def test_search_hides_empty_databases(self, explorer, multi_db_schema):
        """Filtro ativo esconde bancos sem conteudo correspondente"""
        explorer.set_schema(multi_db_schema, "conn1")
        explorer.search_input.setText("users")
        explorer._apply_filter()

        # Bancos sem match devem ser escondidos
        visible_dbs = []
        for i in range(explorer.tree.topLevelItemCount()):
            item = explorer.tree.topLevelItem(i)
            data = item.data(0, Qt.ItemDataRole.UserRole)
            visible_dbs.append(data["name"])

        # Apenas testdb deve aparecer (tem tabela users)
        assert "testdb" in visible_dbs
        assert "master" not in visible_dbs
        assert "production" not in visible_dbs


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

    def test_double_click_database_emits_switch_signal(self, explorer, multi_db_schema, qtbot):
        """Duplo clique em banco emite database_switch_requested"""
        explorer.set_schema(multi_db_schema, "conn1")

        db_item = explorer.tree.topLevelItem(0)  # primeiro banco
        data = db_item.data(0, Qt.ItemDataRole.UserRole)

        with qtbot.waitSignal(explorer.database_switch_requested, timeout=1000) as blocker:
            explorer._on_double_click(db_item, 0)

        assert blocker.args == [data["name"]]

    def test_double_click_schema_emits_insert_signal(self, explorer, multi_schema, qtbot):
        """Duplo clique em schema emite insert_text_requested"""
        explorer.set_schema(multi_schema, "conn1")

        db_item = explorer.tree.topLevelItem(0)
        schema_item = None
        for i in range(db_item.childCount()):
            child = db_item.child(i)
            data = child.data(0, Qt.ItemDataRole.UserRole)
            if data and data.get("type") == "schema":
                schema_item = child
                break

        assert schema_item is not None
        schema_data = schema_item.data(0, Qt.ItemDataRole.UserRole)

        with qtbot.waitSignal(explorer.insert_text_requested, timeout=1000) as blocker:
            explorer._on_double_click(schema_item, 0)

        assert blocker.args == [schema_data["name"]]


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
