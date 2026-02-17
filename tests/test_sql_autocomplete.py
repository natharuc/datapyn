"""
Tests for SqlAutoCompleteService - contextual SQL autocomplete.

Tests cover:
- Context detection (FROM/JOIN -> tables, SELECT/WHERE -> columns, dot -> specific table)
- Schema-based completions (tables, columns, databases)
- Alias resolution (FROM users u -> u.name suggests users columns)
- Edge cases (empty text, no schema, comments, string literals)
"""

import pytest

from source.src.services.sql_autocomplete_service import (
    SqlAutoCompleteService,
    CAT_KEYWORD,
    CAT_TABLE,
    CAT_COLUMN,
    CAT_DATABASE,
    CAT_FUNCTION,
    CTX_TABLE,
    CTX_COLUMN,
    CTX_DOT,
    CTX_DATABASE,
    CTX_DEFAULT,
)


# ---- Fixtures ----

@pytest.fixture
def schema():
    """A realistic schema dict for testing."""
    return {
        "tables": [
            {"name": "users", "schema": "dbo", "type": "TABLE"},
            {"name": "orders", "schema": "dbo", "type": "TABLE"},
            {"name": "products", "schema": "dbo", "type": "TABLE"},
            {"name": "v_active_users", "schema": "dbo", "type": "VIEW"},
        ],
        "columns": {
            "users": [
                {"name": "id", "type": "int"},
                {"name": "name", "type": "varchar"},
                {"name": "email", "type": "varchar"},
                {"name": "created_at", "type": "datetime"},
            ],
            "orders": [
                {"name": "id", "type": "int"},
                {"name": "user_id", "type": "int"},
                {"name": "total", "type": "decimal"},
                {"name": "status", "type": "varchar"},
            ],
            "products": [
                {"name": "id", "type": "int"},
                {"name": "name", "type": "varchar"},
                {"name": "price", "type": "decimal"},
            ],
        },
        "database": "testdb",
        "databases": ["testdb", "master", "tempdb"],
    }


@pytest.fixture
def service(schema):
    """SqlAutoCompleteService with schema loaded."""
    svc = SqlAutoCompleteService()
    svc.set_schema(schema)
    return svc


@pytest.fixture
def empty_service():
    """SqlAutoCompleteService with no schema."""
    return SqlAutoCompleteService()


# ---- Helper ----

def names(completions):
    """Extract just the names from completion tuples."""
    return [c[0] for c in completions]


def categories(completions):
    """Extract just the categories from completion tuples."""
    return [c[1] for c in completions]


# ==============================================================
# Context Detection
# ==============================================================

class TestContextDetection:
    """Test _detect_context identifies the right SQL context."""

    def test_empty_text_returns_default(self, service):
        ctx, arg = service._detect_context("")
        assert ctx == CTX_DEFAULT

    def test_after_from(self, service):
        ctx, arg = service._detect_context("SELECT * FROM ")
        assert ctx == CTX_TABLE

    def test_after_join(self, service):
        ctx, arg = service._detect_context("SELECT * FROM users JOIN ")
        assert ctx == CTX_TABLE

    def test_after_inner_join(self, service):
        ctx, arg = service._detect_context("SELECT * FROM users INNER JOIN ")
        assert ctx == CTX_TABLE

    def test_after_left_join(self, service):
        ctx, arg = service._detect_context("SELECT * FROM users LEFT JOIN ")
        assert ctx == CTX_TABLE

    def test_after_left_outer_join(self, service):
        ctx, arg = service._detect_context("SELECT * FROM users LEFT OUTER JOIN ")
        assert ctx == CTX_TABLE

    def test_after_into(self, service):
        ctx, arg = service._detect_context("INSERT INTO ")
        assert ctx == CTX_TABLE

    def test_after_update(self, service):
        ctx, arg = service._detect_context("UPDATE ")
        assert ctx == CTX_TABLE

    def test_after_select(self, service):
        ctx, arg = service._detect_context("SELECT ")
        assert ctx == CTX_COLUMN

    def test_after_where(self, service):
        ctx, arg = service._detect_context("SELECT * FROM users WHERE ")
        assert ctx == CTX_COLUMN

    def test_after_on(self, service):
        ctx, arg = service._detect_context(
            "SELECT * FROM users JOIN orders ON "
        )
        assert ctx == CTX_COLUMN

    def test_after_order_by(self, service):
        ctx, arg = service._detect_context("SELECT * FROM users ORDER BY ")
        assert ctx == CTX_COLUMN

    def test_after_group_by(self, service):
        ctx, arg = service._detect_context("SELECT * FROM users GROUP BY ")
        assert ctx == CTX_COLUMN

    def test_after_set(self, service):
        ctx, arg = service._detect_context("UPDATE users SET ")
        assert ctx == CTX_COLUMN

    def test_after_having(self, service):
        ctx, arg = service._detect_context(
            "SELECT count(*) FROM users GROUP BY name HAVING "
        )
        assert ctx == CTX_COLUMN

    def test_after_and(self, service):
        ctx, arg = service._detect_context("SELECT * FROM users WHERE id = 1 AND ")
        assert ctx == CTX_COLUMN

    def test_after_or(self, service):
        ctx, arg = service._detect_context("SELECT * FROM users WHERE id = 1 OR ")
        assert ctx == CTX_COLUMN

    def test_dot_context(self, service):
        ctx, arg = service._detect_context("SELECT u.")
        assert ctx == CTX_DOT
        assert arg == "u"

    def test_dot_context_table_name(self, service):
        ctx, arg = service._detect_context("SELECT users.")
        assert ctx == CTX_DOT
        assert arg == "users"

    def test_dot_partial_word(self, service):
        ctx, arg = service._detect_context("SELECT u.na")
        assert ctx == CTX_DOT
        assert arg == "u"

    def test_use_database(self, service):
        ctx, arg = service._detect_context("USE ")
        assert ctx == CTX_DATABASE

    def test_after_table_keyword(self, service):
        ctx, arg = service._detect_context("CREATE TABLE ")
        assert ctx == CTX_TABLE

    def test_after_drop_table(self, service):
        ctx, arg = service._detect_context("DROP TABLE ")
        assert ctx == CTX_TABLE


# ==============================================================
# Completions Output
# ==============================================================

class TestCompletions:
    """Test get_completions returns correct items."""

    def test_empty_text_shows_keywords(self, service):
        result = service.get_completions("", 0, 0)
        n = names(result)
        assert "SELECT" in n
        assert "select" in n
        assert "FROM" in n
        assert "from" in n
        assert "WHERE" in n
        assert "where" in n

    def test_from_shows_tables(self, service):
        result = service.get_completions("SELECT * FROM ", 0, 14)
        n = names(result)
        assert "users" in n
        assert "orders" in n
        assert "products" in n
        assert "v_active_users" in n
        # Should NOT contain keywords in table context
        cats = set(categories(result))
        assert cats == {CAT_TABLE}

    def test_select_shows_columns_and_tables(self, service):
        result = service.get_completions("SELECT ", 0, 7)
        n = names(result)
        # Should have column names
        assert "id" in n
        assert "name" in n
        assert "email" in n
        # Should also have table names (for qualification)
        assert "users" in n

    def test_where_shows_columns(self, service):
        result = service.get_completions("SELECT * FROM users WHERE ", 0, 25)
        n = names(result)
        assert "id" in n
        assert "name" in n

    def test_dot_shows_table_columns(self, service):
        result = service.get_completions("SELECT users.", 0, 13)
        n = names(result)
        assert "id" in n
        assert "name" in n
        assert "email" in n
        assert "created_at" in n
        # Should NOT contain columns from other tables
        assert "total" not in n
        assert "price" not in n

    def test_dot_shows_aliased_table_columns(self, service):
        sql = "SELECT u. FROM users u"
        result = service.get_completions(sql, 0, 9)
        n = names(result)
        assert "id" in n
        assert "name" in n
        assert "email" in n

    def test_dot_alias_with_as(self, service):
        sql = "SELECT u. FROM users AS u"
        result = service.get_completions(sql, 0, 9)
        n = names(result)
        assert "id" in n
        assert "name" in n

    def test_dot_partial_filters_context(self, service):
        """Even with partial word after dot, should return table columns."""
        sql = "SELECT users.na"
        result = service.get_completions(sql, 0, 15)
        n = names(result)
        # Service returns all columns for users table; filtering is done by QsciAPIs
        assert "name" in n
        assert "id" in n

    def test_join_shows_tables(self, service):
        sql = "SELECT * FROM users JOIN "
        result = service.get_completions(sql, 0, 25)
        n = names(result)
        assert "orders" in n
        assert "products" in n

    def test_use_shows_databases(self, service):
        result = service.get_completions("USE ", 0, 4)
        n = names(result)
        assert "testdb" in n
        assert "master" in n
        assert "tempdb" in n

    def test_default_shows_keywords_and_tables(self, service):
        result = service.get_completions("S", 0, 1)
        n = names(result)
        # Keywords (both cases)
        assert "SELECT" in n
        assert "select" in n
        # Tables
        assert "users" in n

    def test_multiline_from(self, service):
        sql = "SELECT\n  *\nFROM "
        result = service.get_completions(sql, 2, 5)
        n = names(result)
        assert "users" in n

    def test_multiline_where(self, service):
        sql = "SELECT *\nFROM users\nWHERE "
        result = service.get_completions(sql, 2, 6)
        n = names(result)
        assert "id" in n
        assert "name" in n


# ==============================================================
# Alias Resolution
# ==============================================================

class TestAliasResolution:
    """Test _resolve_aliases correctly parses FROM/JOIN clauses."""

    def test_simple_alias(self, service):
        aliases = service._resolve_aliases("SELECT * FROM users u")
        assert aliases.get("u") == "users"

    def test_alias_with_as(self, service):
        aliases = service._resolve_aliases("SELECT * FROM users AS u")
        assert aliases.get("u") == "users"

    def test_join_alias(self, service):
        sql = "SELECT * FROM users u JOIN orders o ON u.id = o.user_id"
        aliases = service._resolve_aliases(sql)
        assert aliases.get("u") == "users"
        assert aliases.get("o") == "orders"

    def test_left_join_alias(self, service):
        sql = "SELECT * FROM users u LEFT JOIN orders o ON u.id = o.user_id"
        aliases = service._resolve_aliases(sql)
        assert aliases.get("u") == "users"
        assert aliases.get("o") == "orders"

    def test_no_alias(self, service):
        aliases = service._resolve_aliases("SELECT * FROM users")
        # Table name maps to itself
        assert aliases.get("users") == "users"

    def test_case_insensitive_alias(self, service):
        aliases = service._resolve_aliases("SELECT * FROM Users U")
        assert aliases.get("u") == "Users"

    def test_keyword_not_treated_as_alias(self, service):
        sql = "SELECT * FROM users WHERE id = 1"
        aliases = service._resolve_aliases(sql)
        assert "where" not in aliases or aliases.get("where") is None
        # 'WHERE' should not be an alias


# ==============================================================
# Edge Cases
# ==============================================================

class TestEdgeCases:
    """Test edge cases and robustness."""

    def test_no_schema_keywords_only(self, empty_service):
        result = empty_service.get_completions("SELECT ", 0, 7)
        # Should still return something (tables list will be empty)
        n = names(result)
        # Column context with no schema -> tables (empty) + columns (empty)
        # Should at least not crash
        assert isinstance(result, list)

    def test_no_schema_from(self, empty_service):
        result = empty_service.get_completions("SELECT * FROM ", 0, 14)
        # No tables to suggest but should not crash
        assert result == []

    def test_comment_ignored(self, service):
        sql = "SELECT * -- comment\nFROM "
        result = service.get_completions(sql, 1, 5)
        n = names(result)
        assert "users" in n

    def test_block_comment_ignored(self, service):
        sql = "SELECT * /* block comment */ FROM "
        result = service.get_completions(sql, 0, 33)
        n = names(result)
        assert "users" in n

    def test_string_literal_ignored(self, service):
        sql = "SELECT * FROM users WHERE name = 'FROM' AND "
        result = service.get_completions(sql, 0, 44)
        n = names(result)
        # Should be in column context (AND), not table context (FROM inside string)
        assert "id" in n

    def test_dot_unknown_table(self, service):
        """Dot on unknown table/alias returns all columns as fallback."""
        sql = "SELECT xxx."
        result = service.get_completions(sql, 0, 11)
        # Should return all columns as fallback
        n = names(result)
        assert len(n) > 0  # at least some columns

    def test_set_schema_none(self, service):
        service.set_schema(None)
        assert service.get_schema() == {}

    def test_set_schema_empty(self, service):
        service.set_schema({})
        result = service.get_completions("SELECT * FROM ", 0, 14)
        assert result == []

    def test_table_as_string(self):
        """Schema where tables are strings instead of dicts."""
        svc = SqlAutoCompleteService()
        svc.set_schema({
            "tables": ["users", "orders"],
            "columns": {
                "users": [{"name": "id", "type": "int"}],
            },
        })
        result = svc.get_completions("SELECT * FROM ", 0, 14)
        n = names(result)
        assert "users" in n
        assert "orders" in n

    def test_column_as_string(self):
        """Schema where columns are strings instead of dicts."""
        svc = SqlAutoCompleteService()
        svc.set_schema({
            "tables": [{"name": "t1", "schema": "", "type": "TABLE"}],
            "columns": {"t1": ["col_a", "col_b"]},
        })
        result = svc.get_completions("SELECT t1.", 0, 10)
        n = names(result)
        assert "col_a" in n
        assert "col_b" in n

    def test_cursor_beyond_text(self, service):
        """Cursor position beyond text length should not crash."""
        result = service.get_completions("SELECT", 10, 0)
        # Should return the full text (graceful handling)
        assert isinstance(result, list)

    def test_lowercase_from_suggests_real_case_table(self):
        """Typing 'select * from pre' should suggest 'Premio' in real case.

        The matching is case-insensitive (handled by QsciScintilla),
        but the suggestion text must preserve the real case from the schema,
        because some databases are case-sensitive.
        """
        svc = SqlAutoCompleteService()
        svc.set_schema({
            "tables": [
                {"name": "Premio", "schema": "dbo", "type": "TABLE"},
                {"name": "Clientes", "schema": "dbo", "type": "TABLE"},
            ],
            "columns": {},
        })
        result = svc.get_completions("select * from pre", 0, 17)
        n = names(result)
        # Must suggest real case: "Premio", NOT "premio"
        assert "Premio" in n
        assert "premio" not in n

    def test_table_columns_preserve_real_case(self):
        """Columns must preserve real case from schema."""
        svc = SqlAutoCompleteService()
        svc.set_schema({
            "tables": [{"name": "Premio", "schema": "dbo", "type": "TABLE"}],
            "columns": {
                "Premio": [
                    {"name": "IdPremio", "type": "int"},
                    {"name": "NomePremio", "type": "varchar"},
                ],
            },
        })
        result = svc.get_completions("SELECT Premio.", 0, 14)
        n = names(result)
        assert "IdPremio" in n
        assert "NomePremio" in n
        assert "idpremio" not in n
        assert "nomepremio" not in n

    def test_lowercase_keywords_returned(self, service):
        """Keywords should be available in both cases."""
        result = service.get_completions("", 0, 0)
        n = names(result)
        assert "SELECT" in n
        assert "select" in n
        assert "INSERT" in n
        assert "insert" in n


# ==============================================================
# Functions
# ==============================================================

class TestFunctions:
    """Test that SQL functions are categorized correctly."""

    def test_functions_in_default(self, service):
        result = service.get_completions("", 0, 0)
        func_names = [c[0] for c in result if c[1] == CAT_FUNCTION]
        assert "COUNT" in func_names
        assert "count" in func_names
        assert "SUM" in func_names
        assert "AVG" in func_names

    def test_keywords_in_default(self, service):
        result = service.get_completions("", 0, 0)
        kw_names = [c[0] for c in result if c[1] == CAT_KEYWORD]
        assert "SELECT" in kw_names
        assert "select" in kw_names
        assert "FROM" in kw_names
        assert "from" in kw_names


# ==============================================================
# Complex Queries
# ==============================================================

class TestComplexQueries:
    """Test with more realistic, complex SQL queries."""

    def test_subquery_from(self, service):
        sql = "SELECT * FROM (SELECT id FROM users) sub JOIN "
        result = service.get_completions(sql, 0, len(sql))
        n = names(result)
        assert "orders" in n

    def test_multiple_joins(self, service):
        sql = (
            "SELECT u.name, o.total, p.price\n"
            "FROM users u\n"
            "JOIN orders o ON u.id = o.user_id\n"
            "JOIN products p ON o.product_id = p.id\n"
            "WHERE u."
        )
        result = service.get_completions(sql, 4, 8)
        n = names(result)
        assert "id" in n
        assert "name" in n
        assert "email" in n
        # Should NOT contain orders/products columns
        assert "total" not in n
        assert "price" not in n

    def test_insert_into_table(self, service):
        sql = "INSERT INTO "
        result = service.get_completions(sql, 0, 12)
        n = names(result)
        assert "users" in n

    def test_update_set_columns(self, service):
        sql = "UPDATE users SET "
        result = service.get_completions(sql, 0, 17)
        n = names(result)
        assert "name" in n

    def test_qualified_column_in_on(self, service):
        sql = "SELECT * FROM users u JOIN orders o ON o."
        result = service.get_completions(sql, 0, len(sql))
        n = names(result)
        assert "user_id" in n
        assert "total" in n

    def test_case_insensitive_table(self, service):
        """Dot on case-insensitive table name."""
        sql = "SELECT Users."
        result = service.get_completions(sql, 0, 13)
        n = names(result)
        assert "id" in n
        assert "name" in n
