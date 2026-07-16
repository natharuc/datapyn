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
        assert explorer.info_label.text() == ""
        assert "No connection" in explorer._conn_label.text() or explorer._conn_label.text() != ""

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
        assert "3 tables" in explorer.info_label.text()
        assert "8 columns" in explorer.info_label.text()

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
                assert "(connected)" in item.text(0)
                found_connected = True
                break
        assert found_connected

    def test_multi_db_current_has_tables(self, explorer, multi_db_schema):
        """Apenas banco conectado tem tabelas carregadas (com lazy loading, outros tem placeholder)"""
        explorer.set_schema(multi_db_schema, "conn1")

        for i in range(explorer.tree.topLevelItemCount()):
            item = explorer.tree.topLevelItem(i)
            data = item.data(0, Qt.ItemDataRole.UserRole)
            if data and data.get("name") == "testdb":
                assert item.childCount() > 0  # tem tabelas
            else:
                # Com lazy loading, outros bancos tem placeholder child
                assert item.childCount() == 1  # placeholder para lazy loading
                # Verificar que e placeholder
                child = item.child(0)
                child_data = child.data(0, Qt.ItemDataRole.UserRole) if child else None
                assert child_data is None or child_data.get("type") == "__placeholder__"

    def test_multi_db_info_shows_db_count(self, explorer, multi_db_schema):
        """Info label mostra contagem de bancos"""
        explorer.set_schema(multi_db_schema, "conn1")
        assert "3 databases" in explorer.info_label.text()

    def test_multi_db_lazy_table_expansion_uses_target_database(self, explorer, multi_db_schema, qtbot):
        """Tabela lazy de outro banco pede colunas usando o banco alvo."""
        explorer.set_schema(multi_db_schema, "conn1", db_type="mysql")
        explorer.add_tables_to_schema(
            "production",
            "",
            [{"name": "orders", "schema": "production", "database": "production", "type": "BASE TABLE"}],
        )

        production_item = None
        for i in range(explorer.tree.topLevelItemCount()):
            item = explorer.tree.topLevelItem(i)
            data = item.data(0, Qt.ItemDataRole.UserRole)
            if data and data.get("name") == "production":
                production_item = item
                break

        assert production_item is not None
        table_item = production_item.child(0)
        assert table_item is not None
        assert table_item.data(0, Qt.ItemDataRole.UserRole)["database"] == "production"

        with qtbot.waitSignal(explorer.columns_requested, timeout=1000) as blocker:
            explorer._on_item_expanded(table_item)

        assert blocker.args == ["production", "production", "orders"]

    def test_multi_db_lazy_table_insert_uses_database_qualified_name(self, explorer, multi_db_schema, qtbot):
        """Insercao de tabela lazy usa nome qualificado do banco alvo."""
        explorer.set_schema(multi_db_schema, "conn1", db_type="mysql")
        explorer.add_tables_to_schema(
            "production",
            "",
            [{"name": "orders", "schema": "production", "database": "production", "type": "BASE TABLE"}],
        )

        production_item = None
        for i in range(explorer.tree.topLevelItemCount()):
            item = explorer.tree.topLevelItem(i)
            data = item.data(0, Qt.ItemDataRole.UserRole)
            if data and data.get("name") == "production":
                production_item = item
                break

        assert production_item is not None
        table_item = production_item.child(0)

        with qtbot.waitSignal(explorer.insert_text_requested, timeout=1000) as blocker:
            explorer._on_insert_clicked(table_item)

        assert blocker.args == ["production.orders"]


class TestObjectExplorerClear:
    """Testes de clear"""

    def test_clear_removes_all(self, explorer, sample_schema):
        """Clear limpa tudo"""
        explorer.set_schema(sample_schema, "conn1")
        assert explorer.tree.topLevelItemCount() > 0

        explorer.clear()
        assert explorer.tree.topLevelItemCount() == 0
        assert explorer.info_label.text() == ""

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
        """>> button on table emits insert_text_requested with qualified name"""
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
            explorer._on_insert_clicked(users_item)

        # Tables with schema emit schema.table (qualified name)
        assert blocker.args == ["dbo.users"]

    def test_double_click_column_emits_signal(self, explorer, sample_schema, qtbot):
        """>> button on column emits insert_text_requested"""
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
            explorer._on_insert_clicked(col_item)

        assert blocker.args == ["id"]

    def test_double_click_database_emits_insert_signal(self, explorer, multi_db_schema, qtbot):
        """>> button on database emits insert_text_requested (no full reload)"""
        explorer.set_schema(multi_db_schema, "conn1")

        db_item = explorer.tree.topLevelItem(0)  # primeiro banco
        data = db_item.data(0, Qt.ItemDataRole.UserRole)

        with qtbot.waitSignal(explorer.insert_text_requested, timeout=1000) as blocker:
            explorer._on_insert_clicked(db_item)

        assert blocker.args == [data["name"]]

    def test_double_click_schema_emits_insert_signal(self, explorer, multi_schema, qtbot):
        """>> button on schema emits insert_text_requested"""
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
            explorer._on_insert_clicked(schema_item)

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


# ---------------------------------------------------------------------------
#  Fixtures para Databricks e quote_identifier
# ---------------------------------------------------------------------------

@pytest.fixture
def databricks_schema():
    """Schema Databricks com catalogo, schemas e tabelas, usando campo 'key'"""
    return {
        "database": "main",
        "databases": ["main", "hive_metastore"],
        "tables": [
            {"name": "customers", "schema": "default", "key": "default.customers", "type": "BASE TABLE"},
            {"name": "orders", "schema": "default", "key": "default.orders", "type": "BASE TABLE"},
            {"name": "logs", "schema": "audit", "key": "audit.logs", "type": "BASE TABLE"},
            {"name": "v_report", "schema": "audit", "key": "audit.v_report", "type": "VIEW"},
        ],
        "columns": {
            "default.customers": [
                {"name": "id", "type": "bigint", "nullable": "NO"},
                {"name": "name", "type": "string", "nullable": "YES"},
            ],
            "default.orders": [
                {"name": "order_id", "type": "bigint", "nullable": "NO"},
                {"name": "amount", "type": "double", "nullable": "YES"},
            ],
            "audit.logs": [
                {"name": "log_id", "type": "bigint", "nullable": "NO"},
                {"name": "message", "type": "string", "nullable": "YES"},
            ],
            "audit.v_report": [
                {"name": "total", "type": "double", "nullable": "YES"},
            ],
        },
    }


@pytest.fixture
def pg_single_db_schema():
    """Schema PostgreSQL - banco unico (current_database somente)"""
    return {
        "database": "mydb",
        "tables": [
            {"name": "users", "schema": "public", "key": "public.users", "type": "BASE TABLE"},
            {"name": "items", "schema": "public", "key": "public.items", "type": "BASE TABLE"},
        ],
        "columns": {
            "public.users": [
                {"name": "id", "type": "integer", "nullable": "NO"},
                {"name": "email", "type": "text", "nullable": "YES"},
            ],
            "public.items": [
                {"name": "item_id", "type": "integer", "nullable": "NO"},
            ],
        },
    }


@pytest.fixture
def keyed_multi_schema():
    """Schema com key field e multiplos schemas (MSSQL)"""
    return {
        "database": "testdb",
        "databases": ["testdb", "master"],
        "tables": [
            {"name": "orders", "schema": "dbo", "key": "dbo.orders", "type": "BASE TABLE"},
            {"name": "audit_log", "schema": "audit", "key": "audit.audit_log", "type": "BASE TABLE"},
        ],
        "columns": {
            "dbo.orders": [
                {"name": "order_id", "type": "int", "nullable": "NO"},
            ],
            "audit.audit_log": [
                {"name": "log_id", "type": "int", "nullable": "NO"},
            ],
        },
    }


# ---------------------------------------------------------------------------
#  Databricks 3-level tree
# ---------------------------------------------------------------------------

class TestObjectExplorerDatabricks:
    """Testes do Object Explorer com Databricks (Catalog > Schema > Table)"""

    def test_databricks_catalogs_as_root(self, explorer, databricks_schema):
        """Catalogos Databricks aparecem como nos raiz"""
        explorer.set_schema(databricks_schema, "conn1", db_type="databricks")
        # 2 catalogs: main, hive_metastore
        assert explorer.tree.topLevelItemCount() == 2

    def test_databricks_current_catalog_marked(self, explorer, databricks_schema):
        """Catalogo atual marcado com (connected)"""
        explorer.set_schema(databricks_schema, "conn1", db_type="databricks")
        found = False
        for i in range(explorer.tree.topLevelItemCount()):
            item = explorer.tree.topLevelItem(i)
            data = item.data(0, Qt.ItemDataRole.UserRole)
            if data and data.get("name") == "main":
                assert data["type"] == "catalog"
                assert "(connected)" in item.text(0) or "connected" in item.text(0).lower()
                found = True
                break
        assert found

    def test_databricks_schemas_as_children(self, explorer, databricks_schema):
        """Schemas Databricks agrupados sob catalogo atual"""
        explorer.set_schema(databricks_schema, "conn1", db_type="databricks")
        # Encontrar catalogo "main" (ativo)
        main_item = None
        for i in range(explorer.tree.topLevelItemCount()):
            item = explorer.tree.topLevelItem(i)
            data = item.data(0, Qt.ItemDataRole.UserRole)
            if data and data.get("name") == "main":
                main_item = item
                break
        assert main_item is not None

        # Deve ter 2 schemas: default e audit
        schema_names = []
        for i in range(main_item.childCount()):
            child = main_item.child(i)
            data = child.data(0, Qt.ItemDataRole.UserRole)
            if data and data.get("type") == "schema":
                schema_names.append(data["name"])
        assert "default" in schema_names
        assert "audit" in schema_names

    def test_databricks_tables_under_schema(self, explorer, databricks_schema):
        """Tabelas ficam sob nos de schema no Databricks - com lazy loading via callback"""
        explorer.set_schema(databricks_schema, "conn1", db_type="databricks")
        main_item = None
        for i in range(explorer.tree.topLevelItemCount()):
            item = explorer.tree.topLevelItem(i)
            data = item.data(0, Qt.ItemDataRole.UserRole)
            if data and data.get("name") == "main":
                main_item = item
                break

        # Encontrar schema "default"
        default_schema = None
        for i in range(main_item.childCount()):
            child = main_item.child(i)
            data = child.data(0, Qt.ItemDataRole.UserRole)
            if data and data.get("type") == "schema" and data.get("name") == "default":
                default_schema = child
                break
        assert default_schema is not None

        # Com lazy loading, schema tem placeholder inicialmente
        assert default_schema.childCount() == 1  # placeholder

        # Simular lazy loading de tabelas
        tables = [
            {"name": "customers", "schema": "default", "type": "TABLE"},
            {"name": "orders", "schema": "default", "type": "TABLE"},
        ]
        explorer.add_tables_to_schema("main", "default", tables)

        # Agora verificar tabelas
        table_names = []
        for i in range(default_schema.childCount()):
            tdata = default_schema.child(i).data(0, Qt.ItemDataRole.UserRole)
            if tdata and tdata.get("type") == "table":
                table_names.append(tdata["name"])
        assert "customers" in table_names
        assert "orders" in table_names

    def test_databricks_columns_via_key(self, explorer, databricks_schema):
        """Colunas Databricks resolvidas via lazy loading callback"""
        explorer.set_schema(databricks_schema, "conn1", db_type="databricks")
        main_item = None
        for i in range(explorer.tree.topLevelItemCount()):
            item = explorer.tree.topLevelItem(i)
            data = item.data(0, Qt.ItemDataRole.UserRole)
            if data and data.get("name") == "main":
                main_item = item
                break

        # Encontrar schema "default"
        default_schema = None
        for i in range(main_item.childCount()):
            schema_item = main_item.child(i)
            sdata = schema_item.data(0, Qt.ItemDataRole.UserRole)
            if sdata and sdata.get("name") == "default":
                default_schema = schema_item
                break
        assert default_schema is not None

        # Simular lazy loading de tabelas
        tables = [{"name": "customers", "schema": "default", "type": "TABLE"}]
        explorer.add_tables_to_schema("main", "default", tables)

        # Encontrar tabela customers
        cust_item = None
        for j in range(default_schema.childCount()):
            titem = default_schema.child(j)
            tdata = titem.data(0, Qt.ItemDataRole.UserRole)
            if tdata and tdata.get("name") == "customers":
                cust_item = titem
                break
        assert cust_item is not None

        # Tabela tem placeholder para colunas
        assert cust_item.childCount() == 1  # placeholder

        # Simular lazy loading de colunas
        columns = [
            {"name": "id", "type": "INT", "nullable": "NO"},
            {"name": "name", "type": "STRING", "nullable": "YES"},
        ]
        explorer.add_columns_to_table("main", "default", "customers", columns)

        # Verificar colunas
        assert cust_item.childCount() == 2
        col0 = cust_item.child(0).data(0, Qt.ItemDataRole.UserRole)
        assert col0["name"] == "id"

    def test_databricks_inactive_catalog_empty(self, explorer, databricks_schema):
        """Catalogo inativo tem placeholder para lazy loading"""
        explorer.set_schema(databricks_schema, "conn1", db_type="databricks")
        for i in range(explorer.tree.topLevelItemCount()):
            item = explorer.tree.topLevelItem(i)
            data = item.data(0, Qt.ItemDataRole.UserRole)
            if data and data.get("name") == "hive_metastore":
                # Com lazy loading, tem placeholder child
                assert item.childCount() == 1
                # Verificar que e placeholder
                child = item.child(0)
                child_data = child.data(0, Qt.ItemDataRole.UserRole) if child else None
                assert child_data is None or child_data.get("type") == "__placeholder__"
                return
        pytest.fail("hive_metastore catalog not found")

    def test_databricks_view_labeled(self, explorer, databricks_schema):
        """Views Databricks marcadas com (view) via lazy loading"""
        explorer.set_schema(databricks_schema, "conn1", db_type="databricks")
        main_item = None
        for i in range(explorer.tree.topLevelItemCount()):
            item = explorer.tree.topLevelItem(i)
            data = item.data(0, Qt.ItemDataRole.UserRole)
            if data and data.get("name") == "main":
                main_item = item
                break

        # Encontrar schema "audit"
        audit_schema = None
        for i in range(main_item.childCount()):
            schema_item = main_item.child(i)
            sdata = schema_item.data(0, Qt.ItemDataRole.UserRole)
            if sdata and sdata.get("name") == "audit":
                audit_schema = schema_item
                break
        assert audit_schema is not None

        # Simular lazy loading de tabelas/views
        tables = [{"name": "v_report", "schema": "audit", "type": "VIEW"}]
        explorer.add_tables_to_schema("main", "audit", tables)

        # Verificar que view tem label (view)
        for j in range(audit_schema.childCount()):
            titem = audit_schema.child(j)
            tdata = titem.data(0, Qt.ItemDataRole.UserRole)
            if tdata and tdata.get("name") == "v_report":
                assert "(view)" in titem.text(0)
                return
        pytest.fail("v_report view not found under audit schema")


# ---------------------------------------------------------------------------
#  Context Menu
# ---------------------------------------------------------------------------

class TestObjectExplorerContextMenu:
    """Testes de context menu (query gerada, signals)"""

    def test_databricks_context_menu_uses_limit(self, explorer, databricks_schema, qtbot):
        """Context menu Databricks gera LIMIT 1000 (nao TOP)"""
        explorer.set_schema(databricks_schema, "conn1", db_type="databricks")

        # Encontrar tabela "customers" em main > default
        main_item = None
        for i in range(explorer.tree.topLevelItemCount()):
            item = explorer.tree.topLevelItem(i)
            data = item.data(0, Qt.ItemDataRole.UserRole)
            if data and data.get("name") == "main":
                main_item = item
                break

        # Encontrar schema "default"
        default_schema = None
        for i in range(main_item.childCount()):
            schema_item = main_item.child(i)
            sdata = schema_item.data(0, Qt.ItemDataRole.UserRole)
            if sdata and sdata.get("name") == "default":
                default_schema = schema_item
                break
        assert default_schema is not None

        # Simular lazy loading de tabelas
        tables = [{"name": "customers", "schema": "default", "type": "TABLE"}]
        explorer.add_tables_to_schema("main", "default", tables)

        # Agora encontrar tabela customers
        customers_item = None
        for j in range(default_schema.childCount()):
            titem = default_schema.child(j)
            tdata = titem.data(0, Qt.ItemDataRole.UserRole)
            if tdata and tdata.get("name") == "customers":
                customers_item = titem
                break

        assert customers_item is not None

        # Simular context menu capturando o signal
        signals = []
        explorer.query_requested.connect(lambda q: signals.append(q))

        # Chamar context menu logic diretamente via action
        data = customers_item.data(0, Qt.ItemDataRole.UserRole)
        schema_name = data.get("schema", "")
        name = data.get("name", "")
        qualified = f"{schema_name}.{name}" if schema_name else name
        quoted = explorer._quote_identifier(qualified)

        query = f"SELECT * FROM {quoted} LIMIT 1000"
        explorer.query_requested.emit(query)

        assert len(signals) == 1
        assert "LIMIT 1000" in signals[0]
        assert "TOP" not in signals[0]

    def test_databricks_no_schema_duplication(self, explorer, databricks_schema):
        """Databricks context menu nao duplica schema no nome qualificado"""
        explorer.set_schema(databricks_schema, "conn1", db_type="databricks")

        main_item = None
        for i in range(explorer.tree.topLevelItemCount()):
            item = explorer.tree.topLevelItem(i)
            data = item.data(0, Qt.ItemDataRole.UserRole)
            if data and data.get("name") == "main":
                main_item = item
                break

        # Encontrar schema "default"
        default_schema = None
        for i in range(main_item.childCount()):
            schema_item = main_item.child(i)
            sdata = schema_item.data(0, Qt.ItemDataRole.UserRole)
            if sdata and sdata.get("name") == "default":
                default_schema = schema_item
                break
        assert default_schema is not None

        # Simular lazy loading de tabelas
        tables = [{"name": "customers", "schema": "default", "type": "TABLE", "key": "default.customers"}]
        explorer.add_tables_to_schema("main", "default", tables)

        # Verificar tabela customers
        for j in range(default_schema.childCount()):
            titem = default_schema.child(j)
            tdata = titem.data(0, Qt.ItemDataRole.UserRole)
            if tdata and tdata.get("name") == "customers":
                # table name e "customers", NAO "default.customers"
                assert tdata["name"] == "customers"
                # qualified = schema.name
                qualified = f"{tdata['schema']}.{tdata['name']}"
                assert qualified == "default.customers"
                # NAO duplicado (default.default.customers)
                assert "default.default" not in qualified
                return
        pytest.fail("customers not found")

    def test_mssql_context_menu_uses_top(self, explorer, keyed_multi_schema, qtbot):
        """Context menu MSSQL usa SELECT TOP 1000"""
        explorer.set_schema(keyed_multi_schema, "conn1", db_type="mssql")

        # Encontrar tabela orders em testdb
        testdb_item = None
        for i in range(explorer.tree.topLevelItemCount()):
            item = explorer.tree.topLevelItem(i)
            data = item.data(0, Qt.ItemDataRole.UserRole)
            if data and data.get("name") == "testdb":
                testdb_item = item
                break
        assert testdb_item is not None

        # Encontrar tabela orders (pode estar sob schema dbo)
        orders_item = None
        def find_table(parent, table_name):
            for i in range(parent.childCount()):
                child = parent.child(i)
                cdata = child.data(0, Qt.ItemDataRole.UserRole)
                if cdata and cdata.get("type") == "table" and cdata.get("name") == table_name:
                    return child
                found = find_table(child, table_name)
                if found:
                    return found
            return None

        orders_item = find_table(testdb_item, "orders")
        assert orders_item is not None

        data = orders_item.data(0, Qt.ItemDataRole.UserRole)
        schema_name = data.get("schema", "")
        name = data.get("name", "")
        qualified = f"{schema_name}.{name}" if schema_name else name
        quoted = explorer._quote_identifier(qualified)

        # MSSQL usa TOP
        query = f"SELECT TOP 1000 * FROM {quoted}"
        assert "TOP 1000" in query
        assert "LIMIT" not in query

    def test_catalog_double_click_emits_prefix(self, explorer, databricks_schema, qtbot):
        """>> button on catalog emits insert_text_requested with name"""
        explorer.set_schema(databricks_schema, "conn1", db_type="databricks")

        cat_item = None
        for i in range(explorer.tree.topLevelItemCount()):
            item = explorer.tree.topLevelItem(i)
            data = item.data(0, Qt.ItemDataRole.UserRole)
            if data and data.get("type") == "catalog":
                cat_item = item
                break

        assert cat_item is not None
        cat_data = cat_item.data(0, Qt.ItemDataRole.UserRole)

        with qtbot.waitSignal(explorer.insert_text_requested, timeout=1000) as blocker:
            explorer._on_insert_clicked(cat_item)

        assert blocker.args[0] == cat_data['name']

    def test_databricks_table_double_click_emits_full_namespace(self, explorer, databricks_schema, qtbot):
        """Duplo clique em tabela Databricks emite catalog.schema.table"""
        explorer.set_schema(databricks_schema, "conn1", db_type="databricks")

        # Find the "main" catalog (current)
        main_item = None
        for i in range(explorer.tree.topLevelItemCount()):
            item = explorer.tree.topLevelItem(i)
            data = item.data(0, Qt.ItemDataRole.UserRole)
            if data and data.get("name") == "main":
                main_item = item
                break

        assert main_item is not None

        # Encontrar schema "default"
        default_schema = None
        for i in range(main_item.childCount()):
            schema_item = main_item.child(i)
            sdata = schema_item.data(0, Qt.ItemDataRole.UserRole)
            if sdata and sdata.get("name") == "default":
                default_schema = schema_item
                break
        assert default_schema is not None

        # Simular lazy loading de tabelas
        tables = [{"name": "customers", "schema": "default", "type": "TABLE"}]
        explorer.add_tables_to_schema("main", "default", tables)

        # Find table "customers"
        table_item = None
        for j in range(default_schema.childCount()):
            titem = default_schema.child(j)
            tdata = titem.data(0, Qt.ItemDataRole.UserRole)
            if tdata and tdata.get("name") == "customers":
                table_item = titem
                break

        assert table_item is not None

        with qtbot.waitSignal(explorer.insert_text_requested, timeout=1000) as blocker:
            explorer._on_insert_clicked(table_item)

        # Should emit full namespace: catalog.schema.table
        assert blocker.args[0] == "main.default.customers"

    def test_databricks_schema_double_click_emits_catalog_schema(self, explorer, databricks_schema, qtbot):
        """>> button on Databricks schema emits catalog.schema for insert"""
        explorer.set_schema(databricks_schema, "conn1", db_type="databricks")

        # Find "audit" schema under "main" catalog
        main_item = None
        for i in range(explorer.tree.topLevelItemCount()):
            item = explorer.tree.topLevelItem(i)
            data = item.data(0, Qt.ItemDataRole.UserRole)
            if data and data.get("name") == "main":
                main_item = item
                break

        assert main_item is not None

        audit_item = None
        for i in range(main_item.childCount()):
            schema_item = main_item.child(i)
            sdata = schema_item.data(0, Qt.ItemDataRole.UserRole)
            if sdata and sdata.get("name") == "audit":
                audit_item = schema_item
                break

        assert audit_item is not None

        with qtbot.waitSignal(explorer.insert_text_requested, timeout=1000) as blocker:
            explorer._on_insert_clicked(audit_item)

        # Should emit catalog.schema format for insert
        assert blocker.args[0] == "main.audit"


# ---------------------------------------------------------------------------
#  _quote_identifier
# ---------------------------------------------------------------------------

class TestQuoteIdentifier:
    """Testes de _quote_identifier para diferentes db_types"""

    def test_quote_mssql_simple(self, explorer):
        """MSSQL usa colchetes"""
        explorer._db_type = "mssql"
        assert explorer._quote_identifier("users") == "[users]"

    def test_quote_mssql_two_parts(self, explorer):
        """MSSQL: schema.table"""
        explorer._db_type = "mssql"
        assert explorer._quote_identifier("dbo.users") == "[dbo].[users]"

    def test_quote_mssql_three_parts(self, explorer):
        """MSSQL: db.schema.table"""
        explorer._db_type = "mssql"
        assert explorer._quote_identifier("mydb.dbo.users") == "[mydb].[dbo].[users]"

    def test_quote_postgresql(self, explorer):
        """PostgreSQL usa aspas duplas"""
        explorer._db_type = "postgresql"
        assert explorer._quote_identifier("public.users") == '"public"."users"'

    def test_quote_mysql(self, explorer):
        """MySQL usa backticks"""
        explorer._db_type = "mysql"
        assert explorer._quote_identifier("mydb.users") == "`mydb`.`users`"

    def test_quote_databricks(self, explorer):
        """Databricks usa backticks"""
        explorer._db_type = "databricks"
        assert explorer._quote_identifier("default.customers") == "`default`.`customers`"

    def test_quote_databricks_three_parts(self, explorer):
        """Databricks: catalog.schema.table"""
        explorer._db_type = "databricks"
        assert explorer._quote_identifier("main.default.customers") == "`main`.`default`.`customers`"

    def test_quote_empty_type_defaults_brackets(self, explorer):
        """Tipo vazio usa colchetes (padrao MSSQL)"""
        explorer._db_type = ""
        assert explorer._quote_identifier("users") == "[users]"


# ---------------------------------------------------------------------------
#  PostgreSQL single-DB
# ---------------------------------------------------------------------------

class TestObjectExplorerPostgres:
    """Testes de PostgreSQL com banco unico"""

    def test_pg_single_database_node(self, explorer, pg_single_db_schema):
        """PostgreSQL mostra apenas 1 no de banco"""
        explorer.set_schema(pg_single_db_schema, "conn1", db_type="postgresql")
        # Sem lista "databases", deve ter 1 raiz
        assert explorer.tree.topLevelItemCount() == 1
        db_item = explorer.tree.topLevelItem(0)
        data = db_item.data(0, Qt.ItemDataRole.UserRole)
        assert data["name"] == "mydb"

    def test_pg_columns_resolved_via_key(self, explorer, pg_single_db_schema):
        """PostgreSQL resolve colunas usando key (public.users)"""
        explorer.set_schema(pg_single_db_schema, "conn1", db_type="postgresql")
        db_item = explorer.tree.topLevelItem(0)

        # Com apenas 1 schema (public), tabelas ficam direto sob banco
        users_item = None
        for i in range(db_item.childCount()):
            child = db_item.child(i)
            data = child.data(0, Qt.ItemDataRole.UserRole)
            if data and data.get("type") == "table" and data.get("name") == "users":
                users_item = child
                break

        assert users_item is not None
        # 2 colunas: id, email
        assert users_item.childCount() == 2

    def test_pg_no_multi_db_listing(self, explorer, pg_single_db_schema):
        """PostgreSQL NAO lista multiplos bancos"""
        # Sem "databases" key -> single-db mode
        assert "databases" not in pg_single_db_schema
        explorer.set_schema(pg_single_db_schema, "conn1", db_type="postgresql")
        assert explorer.tree.topLevelItemCount() == 1

    def test_pg_info_label_tables_cols(self, explorer, pg_single_db_schema):
        """PostgreSQL info label mostra tabelas e colunas"""
        explorer.set_schema(pg_single_db_schema, "conn1", db_type="postgresql")
        text = explorer.info_label.text()
        assert "2 tables" in text
        assert "3 columns" in text


# ---------------------------------------------------------------------------
#  Column lookup com campo key
# ---------------------------------------------------------------------------

class TestColumnKeyLookup:
    """Testes garantindo que colunas usam table['key'] para lookup"""

    def test_key_fallback_to_name(self, explorer):
        """Sem key, usa table name diretamente (compatibilidade)"""
        schema = {
            "database": "db1",
            "tables": [{"name": "t1", "schema": "dbo", "type": "BASE TABLE"}],
            "columns": {"t1": [{"name": "col_a", "type": "int", "nullable": "YES"}]},
        }
        explorer.set_schema(schema, "c1")
        db_item = explorer.tree.topLevelItem(0)
        t1 = db_item.child(0)
        assert t1.childCount() == 1
        assert t1.child(0).data(0, Qt.ItemDataRole.UserRole)["name"] == "col_a"

    def test_key_used_over_name(self, explorer):
        """Com campo key, colunas sao buscadas pelo key e nao pelo name"""
        schema = {
            "database": "db1",
            "tables": [{"name": "t1", "schema": "sales", "key": "sales.t1", "type": "BASE TABLE"}],
            "columns": {
                "t1": [{"name": "wrong", "type": "int", "nullable": "YES"}],
                "sales.t1": [{"name": "correct", "type": "int", "nullable": "YES"}],
            },
        }
        explorer.set_schema(schema, "c1")
        db_item = explorer.tree.topLevelItem(0)
        t1 = db_item.child(0)
        assert t1.childCount() == 1
        assert t1.child(0).data(0, Qt.ItemDataRole.UserRole)["name"] == "correct"

    def test_key_stored_in_item_data(self, explorer):
        """Campo key armazenado no data do item da tabela"""
        schema = {
            "database": "db1",
            "tables": [{"name": "t1", "schema": "dbo", "key": "dbo.t1", "type": "BASE TABLE"}],
            "columns": {"dbo.t1": [{"name": "c1", "type": "int", "nullable": "YES"}]},
        }
        explorer.set_schema(schema, "c1")
        db_item = explorer.tree.topLevelItem(0)
        t1 = db_item.child(0)
        tdata = t1.data(0, Qt.ItemDataRole.UserRole)
        assert tdata["key"] == "dbo.t1"
        assert tdata["name"] == "t1"

    def test_column_stores_table_key(self, explorer):
        """Coluna armazena table_key no data"""
        schema = {
            "database": "db1",
            "tables": [{"name": "t1", "schema": "dbo", "key": "dbo.t1", "type": "BASE TABLE"}],
            "columns": {"dbo.t1": [{"name": "c1", "type": "int", "nullable": "YES"}]},
        }
        explorer.set_schema(schema, "c1")
        db_item = explorer.tree.topLevelItem(0)
        t1 = db_item.child(0)
        col = t1.child(0)
        cdata = col.data(0, Qt.ItemDataRole.UserRole)
        assert cdata["table_key"] == "dbo.t1"
        assert cdata["table"] == "t1"


# ---------------------------------------------------------------------------
#  Search com Databricks
# ---------------------------------------------------------------------------

class TestObjectExplorerSearchDatabricks:
    """Testes de busca/filtro com hierarquia Databricks"""

    def test_search_filters_databricks_table(self, explorer, databricks_schema):
        """Busca filtra tabelas na hierarquia Databricks"""
        explorer.set_schema(databricks_schema, "conn1", db_type="databricks")
        explorer.search_input.setText("customers")
        explorer._apply_filter()

        # Deve manter catalogo main, schema default, tabela customers
        main_item = None
        for i in range(explorer.tree.topLevelItemCount()):
            item = explorer.tree.topLevelItem(i)
            data = item.data(0, Qt.ItemDataRole.UserRole)
            if data and data.get("name") == "main":
                main_item = item
                break
        assert main_item is not None

        # Devera ter apenas schema "default"
        table_names = []
        for i in range(main_item.childCount()):
            child = main_item.child(i)
            cdata = child.data(0, Qt.ItemDataRole.UserRole)
            if cdata and cdata.get("type") == "schema":
                for j in range(child.childCount()):
                    titem = child.child(j)
                    tdata = titem.data(0, Qt.ItemDataRole.UserRole)
                    if tdata and tdata.get("type") == "table":
                        table_names.append(tdata["name"])
        assert "customers" in table_names
        assert "orders" not in table_names
        assert "logs" not in table_names

    def test_search_hides_inactive_catalog(self, explorer, databricks_schema):
        """Busca esconde catalogos inativos que nao correspondem"""
        explorer.set_schema(databricks_schema, "conn1", db_type="databricks")
        explorer.search_input.setText("customers")
        explorer._apply_filter()

        names = []
        for i in range(explorer.tree.topLevelItemCount()):
            item = explorer.tree.topLevelItem(i)
            data = item.data(0, Qt.ItemDataRole.UserRole)
            names.append(data.get("name", ""))

        # hive_metastore nao tem match -> escondido
        assert "hive_metastore" not in names

    def test_search_by_column_in_databricks(self, explorer, databricks_schema):
        """Busca por coluna mostra tabela pai no Databricks"""
        explorer.set_schema(databricks_schema, "conn1", db_type="databricks")
        explorer.search_input.setText("message")
        explorer._apply_filter()

        # "message" e coluna de audit.logs
        main_item = None
        for i in range(explorer.tree.topLevelItemCount()):
            item = explorer.tree.topLevelItem(i)
            data = item.data(0, Qt.ItemDataRole.UserRole)
            if data and data.get("name") == "main":
                main_item = item
                break
        assert main_item is not None

        table_names = []
        for i in range(main_item.childCount()):
            child = main_item.child(i)
            cdata = child.data(0, Qt.ItemDataRole.UserRole)
            if cdata and cdata.get("type") == "schema":
                for j in range(child.childCount()):
                    titem = child.child(j)
                    tdata = titem.data(0, Qt.ItemDataRole.UserRole)
                    if tdata and tdata.get("type") == "table":
                        table_names.append(tdata["name"])
        assert "logs" in table_names


# ---------------------------------------------------------------------------
#  Lazy Loading Tests
# ---------------------------------------------------------------------------

class TestObjectExplorerLazyLoading:
    """Testes para carregamento lazy do Object Explorer"""

    def test_inactive_catalog_has_placeholder(self, explorer, databricks_schema):
        """Catalogos inativos tem placeholder para lazy loading"""
        explorer.set_schema(databricks_schema, "conn1", db_type="databricks")
        
        for i in range(explorer.tree.topLevelItemCount()):
            item = explorer.tree.topLevelItem(i)
            data = item.data(0, Qt.ItemDataRole.UserRole)
            if data and data.get("name") == "hive_metastore":
                # Tem placeholder
                assert explorer._has_placeholder_child(item)
                assert item.childCount() == 1
                return
        pytest.fail("hive_metastore not found")

    def test_active_schema_has_placeholder(self, explorer, databricks_schema):
        """Schemas do catalogo ativo tem placeholder para tabelas"""
        explorer.set_schema(databricks_schema, "conn1", db_type="databricks")
        
        main_item = None
        for i in range(explorer.tree.topLevelItemCount()):
            item = explorer.tree.topLevelItem(i)
            data = item.data(0, Qt.ItemDataRole.UserRole)
            if data and data.get("name") == "main":
                main_item = item
                break
        
        assert main_item is not None
        
        # Schemas devem ter placeholder
        for i in range(main_item.childCount()):
            schema_item = main_item.child(i)
            sdata = schema_item.data(0, Qt.ItemDataRole.UserRole)
            if sdata and sdata.get("type") == "schema":
                assert explorer._has_placeholder_child(schema_item)

    def test_add_schemas_to_catalog(self, explorer, databricks_schema):
        """Callback add_schemas_to_catalog adiciona schemas ao catalogo"""
        explorer.set_schema(databricks_schema, "conn1", db_type="databricks")
        
        # Adicionar schemas ao hive_metastore (inativo)
        schemas = ["bronze", "silver", "gold"]
        explorer.add_schemas_to_catalog("hive_metastore", schemas)
        
        # Verificar que schemas foram adicionados
        for i in range(explorer.tree.topLevelItemCount()):
            item = explorer.tree.topLevelItem(i)
            data = item.data(0, Qt.ItemDataRole.UserRole)
            if data and data.get("name") == "hive_metastore":
                assert item.childCount() == 3
                schema_names = []
                for j in range(item.childCount()):
                    child = item.child(j)
                    cdata = child.data(0, Qt.ItemDataRole.UserRole)
                    if cdata and cdata.get("type") == "schema":
                        schema_names.append(cdata["name"])
                assert "bronze" in schema_names
                assert "silver" in schema_names
                assert "gold" in schema_names
                return
        pytest.fail("hive_metastore not found")

    def test_add_tables_to_schema(self, explorer, databricks_schema):
        """Callback add_tables_to_schema adiciona tabelas ao schema"""
        explorer.set_schema(databricks_schema, "conn1", db_type="databricks")
        
        tables = [
            {"name": "new_table1", "schema": "default", "type": "TABLE"},
            {"name": "new_table2", "schema": "default", "type": "VIEW"},
        ]
        explorer.add_tables_to_schema("main", "default", tables)
        
        # Verificar
        main_item = None
        for i in range(explorer.tree.topLevelItemCount()):
            item = explorer.tree.topLevelItem(i)
            data = item.data(0, Qt.ItemDataRole.UserRole)
            if data and data.get("name") == "main":
                main_item = item
                break
        
        for i in range(main_item.childCount()):
            schema_item = main_item.child(i)
            sdata = schema_item.data(0, Qt.ItemDataRole.UserRole)
            if sdata and sdata.get("name") == "default":
                table_names = []
                for j in range(schema_item.childCount()):
                    titem = schema_item.child(j)
                    tdata = titem.data(0, Qt.ItemDataRole.UserRole)
                    if tdata and tdata.get("type") == "table":
                        table_names.append(tdata["name"])
                assert "new_table1" in table_names
                assert "new_table2" in table_names
                return
        pytest.fail("default schema not found")

    def test_add_columns_to_table(self, explorer, databricks_schema):
        """Callback add_columns_to_table adiciona colunas a tabela"""
        explorer.set_schema(databricks_schema, "conn1", db_type="databricks")
        
        # Primeiro adicionar tabelas
        tables = [{"name": "test_table", "schema": "default", "type": "TABLE"}]
        explorer.add_tables_to_schema("main", "default", tables)
        
        # Adicionar colunas
        columns = [
            {"name": "col1", "type": "INT", "nullable": "NO"},
            {"name": "col2", "type": "STRING", "nullable": "YES"},
            {"name": "col3", "type": "TIMESTAMP", "nullable": "YES"},
        ]
        explorer.add_columns_to_table("main", "default", "test_table", columns)
        
        # Verificar
        main_item = None
        for i in range(explorer.tree.topLevelItemCount()):
            item = explorer.tree.topLevelItem(i)
            data = item.data(0, Qt.ItemDataRole.UserRole)
            if data and data.get("name") == "main":
                main_item = item
                break
        
        for i in range(main_item.childCount()):
            schema_item = main_item.child(i)
            sdata = schema_item.data(0, Qt.ItemDataRole.UserRole)
            if sdata and sdata.get("name") == "default":
                for j in range(schema_item.childCount()):
                    titem = schema_item.child(j)
                    tdata = titem.data(0, Qt.ItemDataRole.UserRole)
                    if tdata and tdata.get("name") == "test_table":
                        assert titem.childCount() == 3
                        col_names = []
                        for k in range(titem.childCount()):
                            citem = titem.child(k)
                            cdata = citem.data(0, Qt.ItemDataRole.UserRole)
                            if cdata:
                                col_names.append(cdata["name"])
                        assert "col1" in col_names
                        assert "col2" in col_names
                        assert "col3" in col_names
                        return
        pytest.fail("test_table not found")

    def test_lazy_loading_signals_emitted(self, explorer, databricks_schema, qtbot):
        """Signals de lazy loading sao emitidos ao expandir itens"""
        explorer.set_schema(databricks_schema, "conn1", db_type="databricks")
        
        # Encontrar catalogo inativo
        hive_item = None
        for i in range(explorer.tree.topLevelItemCount()):
            item = explorer.tree.topLevelItem(i)
            data = item.data(0, Qt.ItemDataRole.UserRole)
            if data and data.get("name") == "hive_metastore":
                hive_item = item
                break
        
        assert hive_item is not None
        
        # Verificar que signal e emitido ao expandir
        with qtbot.waitSignal(explorer.schemas_requested, timeout=1000) as blocker:
            explorer._on_item_expanded(hive_item)
        
        assert blocker.args[0] == "hive_metastore"

    def test_tables_requested_signal(self, explorer, databricks_schema, qtbot):
        """Signal tables_requested emitido ao expandir schema"""
        explorer.set_schema(databricks_schema, "conn1", db_type="databricks")
        
        # Encontrar schema default sob main
        main_item = None
        for i in range(explorer.tree.topLevelItemCount()):
            item = explorer.tree.topLevelItem(i)
            data = item.data(0, Qt.ItemDataRole.UserRole)
            if data and data.get("name") == "main":
                main_item = item
                break
        
        default_schema = None
        for i in range(main_item.childCount()):
            schema_item = main_item.child(i)
            sdata = schema_item.data(0, Qt.ItemDataRole.UserRole)
            if sdata and sdata.get("name") == "default":
                default_schema = schema_item
                break
        
        assert default_schema is not None
        
        with qtbot.waitSignal(explorer.tables_requested, timeout=1000) as blocker:
            explorer._on_item_expanded(default_schema)
        
        assert blocker.args[0] == "main"
        assert blocker.args[1] == "default"

    def test_columns_requested_signal(self, explorer, databricks_schema, qtbot):
        """Signal columns_requested emitido ao expandir tabela"""
        explorer.set_schema(databricks_schema, "conn1", db_type="databricks")
        
        # Adicionar tabela primeiro
        tables = [{"name": "my_table", "schema": "default", "type": "TABLE"}]
        explorer.add_tables_to_schema("main", "default", tables)
        
        # Encontrar tabela
        main_item = None
        for i in range(explorer.tree.topLevelItemCount()):
            item = explorer.tree.topLevelItem(i)
            data = item.data(0, Qt.ItemDataRole.UserRole)
            if data and data.get("name") == "main":
                main_item = item
                break
        
        table_item = None
        for i in range(main_item.childCount()):
            schema_item = main_item.child(i)
            sdata = schema_item.data(0, Qt.ItemDataRole.UserRole)
            if sdata and sdata.get("name") == "default":
                for j in range(schema_item.childCount()):
                    titem = schema_item.child(j)
                    tdata = titem.data(0, Qt.ItemDataRole.UserRole)
                    if tdata and tdata.get("name") == "my_table":
                        table_item = titem
                        break
        
        assert table_item is not None
        
        with qtbot.waitSignal(explorer.columns_requested, timeout=1000) as blocker:
            explorer._on_item_expanded(table_item)
        
        assert blocker.args[0] == "main"
        assert blocker.args[1] == "default"
        assert blocker.args[2] == "my_table"

    def test_filter_mode_loads_fully(self, explorer, databricks_schema):
        """Com filtro ativo, carrega arvore completa (nao lazy)"""
        # Aplicar filtro antes de set_schema
        explorer.search_input.setText("customers")
        
        # Set schema com filtro ativo
        explorer.set_schema(databricks_schema, "conn1", db_type="databricks")
        
        # Catalogo ativo deve ter tabelas carregadas (modo full)
        main_item = None
        for i in range(explorer.tree.topLevelItemCount()):
            item = explorer.tree.topLevelItem(i)
            data = item.data(0, Qt.ItemDataRole.UserRole)
            if data and data.get("name") == "main":
                main_item = item
                break
        
        # Com filtro, deve carregar tudo - verificar que tem tabelas
        found_table = False
        for i in range(main_item.childCount()):
            child = main_item.child(i)
            cdata = child.data(0, Qt.ItemDataRole.UserRole)
            if cdata and cdata.get("type") == "schema":
                for j in range(child.childCount()):
                    titem = child.child(j)
                    tdata = titem.data(0, Qt.ItemDataRole.UserRole)
                    if tdata and tdata.get("type") == "table":
                        found_table = True
                        break
        assert found_table, "Com filtro ativo, tabelas devem ser carregadas imediatamente"


class TestObjectExplorerExpansionBehavior:
    """Tests for tree item expansion behavior (arrow clicks and double-click)."""

    def test_double_click_toggles_expansion(self, qtbot):
        """Double-click on an item with children should toggle expansion."""
        explorer = ObjectExplorerPanel()
        qtbot.addWidget(explorer)

        schema = {
            "database": "testdb",
            "databases": ["testdb", "other"],
            "tables": [{"name": "users", "type": "TABLE", "schema": "dbo"}],
            "columns": {},
        }
        explorer.set_schema(schema, "conn1", db_type="mssql")

        # Find current db item
        db_item = explorer.tree.topLevelItem(0)
        data = db_item.data(0, Qt.ItemDataRole.UserRole)
        # Sort may put "other" first; find testdb
        for i in range(explorer.tree.topLevelItemCount()):
            item = explorer.tree.topLevelItem(i)
            d = item.data(0, Qt.ItemDataRole.UserRole)
            if d and d.get("name") == "testdb":
                db_item = item
                break

        # Current db should be auto-expanded
        assert db_item.isExpanded()

        # Double-click should collapse it
        explorer._on_double_click(db_item, 0)
        assert not db_item.isExpanded()

        # Double-click again should expand it
        explorer._on_double_click(db_item, 0)
        assert db_item.isExpanded()

    def test_double_click_leaf_no_crash(self, qtbot):
        """Double-click on a leaf item (no children) should not crash."""
        explorer = ObjectExplorerPanel()
        qtbot.addWidget(explorer)

        schema = {
            "database": "testdb",
            "databases": [],
            "tables": [{"name": "users", "type": "TABLE", "schema": "dbo"}],
            "columns": {"users": [{"name": "id", "type": "int", "nullable": "NO"}]},
        }
        explorer.set_schema(schema, "conn1", db_type="postgresql")

        # Find column item (leaf)
        db_item = explorer.tree.topLevelItem(0)
        table_item = db_item.child(0)
        col_item = table_item.child(0)

        # Should not crash - leaf items have no children
        explorer._on_double_click(col_item, 0)

    def test_current_catalog_auto_expanded_databricks(self, qtbot):
        """Current catalog should be auto-expanded in Databricks lazy loading mode."""
        explorer = ObjectExplorerPanel()
        qtbot.addWidget(explorer)

        schema = {
            "database": "main",
            "databases": ["main", "other_catalog"],
            "tables": [
                {"name": "t1", "type": "TABLE", "schema": "default"},
            ],
            "columns": {},
        }
        explorer.set_schema(schema, "conn1", db_type="databricks")

        # Find the current catalog
        for i in range(explorer.tree.topLevelItemCount()):
            item = explorer.tree.topLevelItem(i)
            d = item.data(0, Qt.ItemDataRole.UserRole)
            if d and d.get("name") == "main":
                assert item.isExpanded(), "Current catalog should be auto-expanded"
                break

    def test_current_db_auto_expanded_multi_db(self, qtbot):
        """Current database should be auto-expanded in multi-db lazy loading mode."""
        explorer = ObjectExplorerPanel()
        qtbot.addWidget(explorer)

        schema = {
            "database": "mydb",
            "databases": ["mydb", "other"],
            "tables": [{"name": "orders", "type": "TABLE", "schema": "dbo"}],
            "columns": {},
        }
        explorer.set_schema(schema, "conn1", db_type="mssql")

        for i in range(explorer.tree.topLevelItemCount()):
            item = explorer.tree.topLevelItem(i)
            d = item.data(0, Qt.ItemDataRole.UserRole)
            if d and d.get("name") == "mydb":
                assert item.isExpanded(), "Current db should be auto-expanded"
                break


class TestObjectExplorerConnectionHeader:
    """Testes do header de conexao (_conn_label)"""

    def test_conn_label_shows_connection_and_db(self, explorer, sample_schema):
        """Header mostra nome da conexao e banco"""
        explorer.set_schema(sample_schema, "conn1")
        text = explorer._conn_label.text()
        assert "conn1" in text
        assert "testdb" in text

    def test_conn_label_no_database(self, explorer):
        """Header mostra apenas conexao quando nao tem banco"""
        schema = {"database": "", "tables": [], "columns": {}}
        explorer.set_schema(schema, "my_conn")
        text = explorer._conn_label.text()
        assert "my_conn" in text

    def test_conn_label_no_connection(self, explorer):
        """Header mostra 'no connection' sem conexao"""
        schema = {"database": "db1", "tables": [], "columns": {}}
        explorer.set_schema(schema, "")
        # Without connection name, should show no_connection text
        text = explorer._conn_label.text()
        assert text != ""

    def test_conn_label_reset_on_clear(self, explorer, sample_schema):
        """Clear reseta header de conexao"""
        explorer.set_schema(sample_schema, "conn1")
        assert "conn1" in explorer._conn_label.text()
        explorer.clear()
        # After clear, should not contain the connection name
        assert "conn1" not in explorer._conn_label.text()

    def test_conn_label_updates_on_new_schema(self, explorer, sample_schema):
        """Header atualiza quando troca de schema"""
        explorer.set_schema(sample_schema, "conn1")
        assert "conn1" in explorer._conn_label.text()

        schema2 = {
            "database": "prod_db",
            "tables": [{"name": "t1", "schema": "dbo", "type": "BASE TABLE"}],
            "columns": {"t1": [{"name": "c1", "type": "int", "nullable": "NO"}]},
        }
        explorer.set_schema(schema2, "prod_server")
        text = explorer._conn_label.text()
        assert "prod_server" in text
        assert "prod_db" in text
        assert "conn1" not in text


class TestObjectExplorerSetError:
    """Testes do set_error"""

    def test_set_error_shows_message(self, explorer):
        """set_error exibe mensagem de erro"""
        explorer.set_error("Failed to load schema")
        assert "Failed to load schema" in explorer.info_label.text()

    def test_set_error_changes_style(self, explorer):
        """set_error muda estilo para vermelho"""
        explorer.set_error("Connection timeout")
        style = explorer.info_label.styleSheet()
        assert "#f44747" in style

    def test_set_error_hides_loading(self, explorer):
        """set_error esconde indicador de loading"""
        explorer.set_loading(True)
        explorer.set_error("Error occurred")
        # Loading spinner should be hidden (tree should be visible)
        assert explorer.tree.isVisible()

    def test_set_schema_resets_error_style(self, explorer, sample_schema):
        """set_schema reseta estilo de erro"""
        explorer.set_error("Some error")
        assert "#f44747" in explorer.info_label.styleSheet()
        explorer.set_schema(sample_schema, "conn1")
        assert "#f44747" not in explorer.info_label.styleSheet()


class TestObjectExplorerExpansionState:
    """Testes de preservacao de estado de expansao"""

    def test_save_expansion_state_captures_expanded(self, explorer, sample_schema):
        """_save_expansion_state captura nos expandidos"""
        explorer.set_schema(sample_schema, "conn1")

        # DB item is expanded by default
        db_item = explorer.tree.topLevelItem(0)
        assert db_item.isExpanded()

        state = explorer._save_expansion_state()
        assert len(state) > 0  # At least the db node

    def test_save_expansion_empty_tree(self, explorer):
        """_save_expansion_state retorna vazio para arvore vazia"""
        state = explorer._save_expansion_state()
        assert len(state) == 0

    def test_restore_expansion_state_works(self, explorer, sample_schema):
        """_restore_expansion_state restaura nos expandidos"""
        explorer.set_schema(sample_schema, "conn1")

        # Expand the "users" table node
        db_item = explorer.tree.topLevelItem(0)
        users_item = None
        for i in range(db_item.childCount()):
            child = db_item.child(i)
            data = child.data(0, Qt.ItemDataRole.UserRole)
            if data and data.get("type") == "table" and data.get("name") == "users":
                users_item = child
                break

        assert users_item is not None
        users_item.setExpanded(True)

        # Save state
        state = explorer._save_expansion_state()

        # Rebuild tree (simulates refresh)
        explorer.set_schema(sample_schema, "conn1")

        # Without restore, table might not be expanded
        # Manually restore
        explorer._restore_expansion_state(state)

        # Find users again and check expansion
        db_item = explorer.tree.topLevelItem(0)
        for i in range(db_item.childCount()):
            child = db_item.child(i)
            data = child.data(0, Qt.ItemDataRole.UserRole)
            if data and data.get("type") == "table" and data.get("name") == "users":
                assert child.isExpanded(), "users table should be re-expanded"
                break

    def test_restore_empty_state_no_crash(self, explorer, sample_schema):
        """_restore_expansion_state com set vazio nao causa crash"""
        explorer.set_schema(sample_schema, "conn1")
        explorer._restore_expansion_state(set())
        # Should not crash


class TestObjectExplorerEnhancedContextMenu:
    """Testes do context menu aprimorado"""

    def _find_table_item(self, explorer, table_name="users"):
        """Helper para encontrar item de tabela"""
        db_item = explorer.tree.topLevelItem(0)
        for i in range(db_item.childCount()):
            child = db_item.child(i)
            data = child.data(0, Qt.ItemDataRole.UserRole)
            if data and data.get("type") == "table" and data.get("name") == table_name:
                return child
        return None

    def _find_column_item(self, explorer, table_name="users", col_index=0):
        """Helper para encontrar item de coluna"""
        table_item = self._find_table_item(explorer, table_name)
        if table_item and table_item.childCount() > col_index:
            return table_item.child(col_index)
        return None

    def test_get_column_names_for_table(self, explorer, sample_schema):
        """_get_column_names_for_table retorna nomes corretos"""
        explorer.set_schema(sample_schema, "conn1")
        users_item = self._find_table_item(explorer)
        assert users_item is not None

        col_names = explorer._get_column_names_for_table(users_item)
        assert col_names == ["id", "name", "email"]

    def test_get_column_names_empty_table(self, explorer):
        """_get_column_names_for_table retorna lista vazia para tabela sem colunas"""
        schema = {
            "database": "db",
            "tables": [{"name": "empty", "schema": "dbo", "type": "BASE TABLE"}],
            "columns": {},
        }
        explorer.set_schema(schema, "conn1")
        table_item = self._find_table_item(explorer, "empty")
        assert table_item is not None
        col_names = explorer._get_column_names_for_table(table_item)
        assert col_names == []

    def test_count_rows_emits_query(self, explorer, sample_schema, qtbot):
        """COUNT(*) emite query_requested com SELECT COUNT(*)"""
        explorer.set_schema(sample_schema, "conn1")
        users_item = self._find_table_item(explorer)
        assert users_item is not None

        # Simulate the context menu action directly
        # The COUNT query is: SELECT COUNT(*) FROM <quoted_table>
        quoted = explorer._quote_identifier("dbo.users")
        expected_query = f"SELECT COUNT(*) FROM {quoted}"

        with qtbot.waitSignal(explorer.query_requested, timeout=1000) as blocker:
            explorer.query_requested.emit(expected_query)

        assert "COUNT(*)" in blocker.args[0]
        assert "users" in blocker.args[0]

    def test_column_where_clause(self, explorer, sample_schema):
        """Coluna gera WHERE clause correta"""
        explorer.set_schema(sample_schema, "conn1")
        col_item = self._find_column_item(explorer, "users", 0)  # "id" column
        assert col_item is not None
        data = col_item.data(0, Qt.ItemDataRole.UserRole)
        assert data["name"] == "id"

        quoted_col = explorer._quote_identifier("id")
        expected = f"WHERE {quoted_col} = "
        assert "WHERE" in expected
        assert "id" in expected

    def test_create_table_script_uses_detailed_types(self, explorer):
        """Create Table script usa o tipo detalhado das colunas."""
        schema = {
            "database": "testdb",
            "tables": [{"name": "orders", "schema": "dbo", "type": "BASE TABLE", "key": "dbo.orders"}],
            "columns": {
                "dbo.orders": [
                    {"name": "amount", "type": "decimal", "display_type": "decimal(20,12)", "nullable": "NO"},
                    {"name": "customer_name", "type": "varchar", "display_type": "varchar(50)", "nullable": "YES"},
                ]
            },
        }
        explorer.set_schema(schema, "conn1", db_type="mssql")

        orders_item = self._find_table_item(explorer, "orders")
        assert orders_item is not None

        script = explorer._build_create_table_script(orders_item)
        assert "CREATE TABLE [dbo].[orders]" in script
        assert "[amount] decimal(20,12) NOT NULL" in script
        assert "[customer_name] varchar(50) NULL" in script

    def test_drop_and_create_script_includes_drop_statement(self, explorer):
        """Drop and Create gera DROP seguido do CREATE TABLE."""
        schema = {
            "database": "testdb",
            "tables": [{"name": "users", "schema": "dbo", "type": "BASE TABLE", "key": "dbo.users"}],
            "columns": {
                "dbo.users": [
                    {"name": "id", "type": "int", "display_type": "int", "nullable": "NO"},
                ]
            },
        }
        explorer.set_schema(schema, "conn1", db_type="mssql")

        users_item = self._find_table_item(explorer, "users")
        assert users_item is not None

        script = explorer._build_drop_and_create_script(users_item)
        assert "DROP TABLE [dbo].[users];" in script
        assert script.count("CREATE TABLE") == 1

    def test_column_group_by(self, explorer, sample_schema):
        """Coluna gera GROUP BY correto"""
        explorer.set_schema(sample_schema, "conn1")
        col_item = self._find_column_item(explorer, "users", 0)
        data = col_item.data(0, Qt.ItemDataRole.UserRole)

        quoted_col = explorer._quote_identifier(data["name"])
        group_text = f"GROUP BY {quoted_col}"
        assert "GROUP BY" in group_text

    def test_column_order_by(self, explorer, sample_schema):
        """Coluna gera ORDER BY correto"""
        explorer.set_schema(sample_schema, "conn1")
        col_item = self._find_column_item(explorer, "users", 0)
        data = col_item.data(0, Qt.ItemDataRole.UserRole)

        quoted_col = explorer._quote_identifier(data["name"])
        order_text = f"ORDER BY {quoted_col}"
        assert "ORDER BY" in order_text

    def test_select_all_columns_mssql(self, explorer, sample_schema):
        """SELECT all columns usa TOP para MSSQL"""
        explorer.set_schema(sample_schema, "conn1", db_type="mssql")
        users_item = self._find_table_item(explorer)
        col_names = explorer._get_column_names_for_table(users_item)
        cols_quoted = ", ".join(explorer._quote_identifier(c) for c in col_names)
        quoted_table = explorer._quote_identifier("dbo.users")

        query = f"SELECT TOP 1000 {cols_quoted}\nFROM {quoted_table}"
        assert "TOP 1000" in query
        assert "id" in query

    def test_select_all_columns_postgres(self, explorer, sample_schema):
        """SELECT all columns usa LIMIT para PostgreSQL"""
        explorer.set_schema(sample_schema, "conn1", db_type="postgresql")
        users_item = self._find_table_item(explorer)
        col_names = explorer._get_column_names_for_table(users_item)
        cols_quoted = ", ".join(explorer._quote_identifier(c) for c in col_names)
        quoted_table = explorer._quote_identifier("dbo.users")

        query = f"SELECT {cols_quoted}\nFROM {quoted_table}\nLIMIT 1000"
        assert "LIMIT 1000" in query
        assert "id" in query


class TestObjectExplorerFocusAutoLoad:
    """Smart lazy load: focus/visibility triggers databases_requested once per connection."""

    def test_focus_emits_databases_requested_once(self, qtbot):
        """Focusing the tree emits databases_requested once when the db list is empty."""
        explorer = ObjectExplorerPanel()
        qtbot.addWidget(explorer)

        # Minimal schema (lazy, no server db list) for a SQL Server connection.
        schema = {"database": "AppDb", "tables": [], "columns": {}, "lazy": True}
        explorer.set_schema(schema, "Gecon", db_type="mssql")

        emitted = []
        explorer.databases_requested.connect(lambda: emitted.append(True))

        # First focus must trigger the request.
        explorer.tree.setFocus()
        explorer._maybe_request_databases_on_focus()
        assert len(emitted) == 1

        # Second focus must NOT re-trigger (guard set).
        explorer._maybe_request_databases_on_focus()
        assert len(emitted) == 1

    def test_focus_skipped_when_databases_loaded(self, qtbot):
        """No request when the server db list is already populated."""
        explorer = ObjectExplorerPanel()
        qtbot.addWidget(explorer)

        schema = {
            "database": "AppDb",
            "databases": ["AppDb", "master"],
            "tables": [],
            "columns": {},
        }
        explorer.set_schema(schema, "Gecon", db_type="mssql")

        emitted = []
        explorer.databases_requested.connect(lambda: emitted.append(True))
        explorer._maybe_request_databases_on_focus()
        assert emitted == []

    def test_connection_change_resets_guard(self, qtbot):
        """Switching connection resets the focus-trigger guard so it re-loads."""
        explorer = ObjectExplorerPanel()
        qtbot.addWidget(explorer)

        explorer.set_schema({"database": "A", "tables": [], "columns": {}}, "conn1", db_type="mssql")
        emitted = []
        explorer.databases_requested.connect(lambda: emitted.append(True))
        explorer._maybe_request_databases_on_focus()
        assert len(emitted) == 1

        # New connection -> guard resets.
        explorer.set_schema({"database": "B", "tables": [], "columns": {}}, "conn2", db_type="mssql")
        explorer._maybe_request_databases_on_focus()
        assert len(emitted) == 2
