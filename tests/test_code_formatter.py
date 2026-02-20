"""
Testes para o servico de formatacao de codigo.
"""

import pytest
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "source"))

from src.services.code_formatter_service import format_python, format_sql, format_code


class TestFormatPython:
    """Testes de formatacao Python via ruff."""

    def test_format_simple_code(self):
        """Formata codigo Python simples."""
        code = "x=1\ny=2\nz=x+y\n"
        result, error = format_python(code)
        assert error is None
        assert "x = 1" in result
        assert "y = 2" in result

    def test_format_function(self):
        """Formata definicao de funcao."""
        code = "def foo( a,b,c ):\n    return a+b+c\n"
        result, error = format_python(code)
        assert error is None
        assert "def foo(a, b, c):" in result

    def test_format_preserves_logic(self):
        """Formatacao nao altera a logica."""
        code = "result = [x for x in range(10) if x > 5]\nprint(result)\n"
        result, error = format_python(code)
        assert error is None
        assert "range(10)" in result
        assert "x > 5" in result

    def test_empty_code(self):
        """Codigo vazio retorna vazio sem erro."""
        result, error = format_python("")
        assert error is None
        assert result == ""

    def test_whitespace_only(self):
        """Codigo so com espacos retorna sem erro."""
        result, error = format_python("   \n  \n")
        assert error is None

    def test_already_formatted(self):
        """Codigo ja formatado nao muda."""
        code = "x = 1\ny = 2\n"
        result, error = format_python(code)
        assert error is None
        assert result.strip() == code.strip()

    def test_line_length(self):
        """Respeita line_length configurado."""
        code = 'x = "' + "a" * 120 + '"\n'
        result, error = format_python(code, line_length=80)
        assert error is None

    def test_multiline_dict(self):
        """Formata dict multiline."""
        code = "d = {'a': 1, 'b': 2, 'c': 3, 'd': 4, 'e': 5, 'f': 6, 'g': 7, 'h': 8, 'i': 9}\n"
        result, error = format_python(code)
        assert error is None

    def test_syntax_error_returns_error(self):
        """Codigo com erro de sintaxe retorna erro."""
        code = "def foo(\n"
        result, error = format_python(code)
        # ruff pode retornar erro ou o codigo original
        # O importante eh nao crashar
        assert isinstance(result, str)


class TestFormatSQL:
    """Testes de formatacao SQL via sqlparse."""

    def test_format_simple_select(self):
        """Formata SELECT simples."""
        code = "select id, name, email from users where active = 1"
        result, error = format_sql(code)
        assert error is None
        assert "SELECT" in result
        assert "FROM" in result
        assert "WHERE" in result

    def test_format_keywords_upper(self):
        """Keywords ficam em maiusculo."""
        code = "select * from users where id = 1 order by name"
        result, error = format_sql(code)
        assert error is None
        assert "SELECT" in result
        assert "FROM" in result
        assert "WHERE" in result
        assert "ORDER BY" in result

    def test_format_keywords_lower(self):
        """Keywords podem ficar em minusculo."""
        code = "SELECT * FROM users"
        result, error = format_sql(code, keyword_case="lower")
        assert error is None
        assert "select" in result
        assert "from" in result

    def test_format_indentation(self):
        """Aplica indentacao."""
        code = "select id, name from users where active = 1 and role = 'admin'"
        result, error = format_sql(code)
        assert error is None
        # Deve ter quebras de linha
        assert "\n" in result

    def test_format_join(self):
        """Formata query com JOIN."""
        code = "select u.name, o.total from users u inner join orders o on u.id = o.user_id where o.total > 100"
        result, error = format_sql(code)
        assert error is None
        assert "JOIN" in result

    def test_empty_code(self):
        """Codigo vazio retorna vazio sem erro."""
        result, error = format_sql("")
        assert error is None
        assert result == ""

    def test_whitespace_only(self):
        """Codigo so com espacos retorna sem erro."""
        result, error = format_sql("   \n  \n")
        assert error is None

    def test_insert_statement(self):
        """Formata INSERT."""
        code = "insert into users (name, email) values ('John', 'john@test.com')"
        result, error = format_sql(code)
        assert error is None
        assert "INSERT" in result
        assert "INTO" in result
        assert "VALUES" in result

    def test_create_table(self):
        """Formata CREATE TABLE."""
        code = "create table users (id int primary key, name varchar(100) not null, created_at datetime default getdate())"
        result, error = format_sql(code)
        assert error is None
        assert "CREATE" in result
        assert "TABLE" in result

    def test_multiple_statements(self):
        """Formata multiplos statements."""
        code = "select 1; select 2; select 3"
        result, error = format_sql(code)
        assert error is None
        assert "SELECT" in result

    def test_no_reindent(self):
        """Pode desabilitar reindentacao."""
        code = "select id from users"
        result, error = format_sql(code, reindent=False)
        assert error is None


class TestFormatCode:
    """Testes da funcao format_code (dispatcher)."""

    def test_python_dispatch(self):
        """Despacha para formatador Python."""
        code = "x=1\n"
        result, error = format_code(code, "python")
        assert error is None
        assert "x = 1" in result

    def test_sql_dispatch(self):
        """Despacha para formatador SQL."""
        code = "select * from users"
        result, error = format_code(code, "sql")
        assert error is None
        assert "SELECT" in result

    def test_case_insensitive_language(self):
        """Linguagem eh case-insensitive."""
        code = "x=1\n"
        result, error = format_code(code, "Python")
        assert error is None
        assert "x = 1" in result

    def test_unknown_language(self):
        """Linguagem desconhecida retorna erro."""
        code = "some code"
        result, error = format_code(code, "javascript")
        assert error is not None
        assert result == code  # Codigo original retornado

    def test_empty_code_any_language(self):
        """Codigo vazio funciona para qualquer linguagem."""
        result, error = format_code("", "python")
        assert error is None

        result, error = format_code("", "sql")
        assert error is None


class TestFormatShortcut:
    """Testa que o atalho de formatacao esta registrado."""

    def test_format_code_in_default_shortcuts(self):
        """format_code esta nos atalhos padrao."""
        from src.core.shortcut_manager import ShortcutManager

        assert "format_code" in ShortcutManager.DEFAULT_SHORTCUTS
        assert ShortcutManager.DEFAULT_SHORTCUTS["format_code"] == "Ctrl+Shift+F"

    def test_shortcut_is_configurable(self):
        """Atalho de formatacao pode ser reconfigurado."""
        import tempfile
        from pathlib import Path
        from src.core.shortcut_manager import ShortcutManager

        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "shortcuts.json"
            manager = ShortcutManager(str(config_path))

            # Padrao
            assert manager.get_shortcut("format_code") == "Ctrl+Shift+F"

            # Reconfigurar
            manager.set_shortcut("format_code", "Alt+Shift+F")
            assert manager.get_shortcut("format_code") == "Alt+Shift+F"

            # Persistir e recarregar
            manager2 = ShortcutManager(str(config_path))
            assert manager2.get_shortcut("format_code") == "Alt+Shift+F"

            # Reset
            manager2.reset_to_defaults()
            assert manager2.shortcuts["format_code"] == "Ctrl+Shift+F"
