"""
Code formatting service.

Formats Python (via ruff) and SQL (via sqlparse).
"""

import subprocess
import sys
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# Hide console window on Windows
_CREATE_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0


def format_python(code: str, line_length: int = 88) -> tuple[str, str | None]:
    """Format Python code using ruff format.

    Args:
        code: Python code to format.
        line_length: Maximum line length.

    Returns:
        Tuple (formatted_code, error).
        If error is None, formatting was successful.
    """
    if not code.strip():
        return code, None

    try:
        # Find ruff in same Python environment
        venv_dir = Path(sys.executable).parent
        ruff_exe = venv_dir / "ruff.exe" if sys.platform == "win32" else venv_dir / "ruff"

        if not ruff_exe.exists():
            # Try via python -m ruff
            ruff_cmd = [sys.executable, "-m", "ruff"]
        else:
            ruff_cmd = [str(ruff_exe)]

        result = subprocess.run(
            [*ruff_cmd, "format", "--line-length", str(line_length), "-"],
            input=code,
            capture_output=True,
            text=True,
            timeout=10,
            creationflags=_CREATE_NO_WINDOW,
        )

        if result.returncode == 0:
            return result.stdout, None
        else:
            err_msg = result.stderr.strip() or "Unknown ruff error"
            logger.warning("Ruff format failed: %s", err_msg)
            return code, err_msg

    except FileNotFoundError:
        return code, "ruff not found. Install with: pip install ruff"
    except subprocess.TimeoutExpired:
        return code, "Timeout formatting (>10s)"
    except Exception as e:
        return code, str(e)


def format_sql(
    code: str,
    keyword_case: str = "upper",
    identifier_case: str | None = None,
    indent_width: int = 4,
    reindent: bool = True,
    strip_comments: bool = False,
) -> tuple[str, str | None]:
    """Format SQL code using sqlparse.

    Args:
        code: SQL code to format.
        keyword_case: Keyword case ('upper', 'lower', 'capitalize').
        identifier_case: Identifier case (None = don't change).
        indent_width: Indentation width.
        reindent: Whether to reindent code.
        strip_comments: Whether to remove comments.

    Returns:
        Tuple (formatted_code, error).
        If error is None, formatting was successful.
    """
    if not code.strip():
        return code, None

    try:
        import sqlparse

        formatted = sqlparse.format(
            code,
            keyword_case=keyword_case,
            identifier_case=identifier_case,
            reindent=reindent,
            indent_width=indent_width,
            strip_comments=strip_comments,
        )
        return formatted, None

    except ImportError:
        return code, "sqlparse not found. Install with: pip install sqlparse"
    except Exception as e:
        return code, str(e)


def format_code(code: str, language: str) -> tuple[str, str | None]:
    """Format code according to language.

    Args:
        code: Code to format.
        language: Language ('python', 'sql', 'cross').

    Returns:
        Tuple (formatted_code, error).
    """
    language = language.lower()

    if language == "python":
        return format_python(code)
    elif language == "sql":
        return format_sql(code)
    else:
        return code, f"Formatter not available for '{language}'"
