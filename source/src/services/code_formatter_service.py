"""
Servico de formatacao de codigo.

Formata Python (via ruff) e SQL (via sqlparse).
"""

import subprocess
import sys
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def format_python(code: str, line_length: int = 88) -> tuple[str, str | None]:
    """Formata codigo Python usando ruff format.

    Args:
        code: Codigo Python a formatar.
        line_length: Comprimento maximo da linha.

    Returns:
        Tupla (codigo_formatado, erro).
        Se erro for None, a formatacao foi bem-sucedida.
    """
    if not code.strip():
        return code, None

    try:
        # Encontrar ruff no mesmo ambiente do Python
        venv_dir = Path(sys.executable).parent
        ruff_exe = venv_dir / "ruff.exe" if sys.platform == "win32" else venv_dir / "ruff"

        if not ruff_exe.exists():
            # Tentar via python -m ruff
            ruff_cmd = [sys.executable, "-m", "ruff"]
        else:
            ruff_cmd = [str(ruff_exe)]

        result = subprocess.run(
            [*ruff_cmd, "format", "--line-length", str(line_length), "-"],
            input=code,
            capture_output=True,
            text=True,
            timeout=10,
        )

        if result.returncode == 0:
            return result.stdout, None
        else:
            err_msg = result.stderr.strip() or "Erro desconhecido no ruff"
            logger.warning("Ruff format falhou: %s", err_msg)
            return code, err_msg

    except FileNotFoundError:
        return code, "ruff nao encontrado. Instale com: pip install ruff"
    except subprocess.TimeoutExpired:
        return code, "Timeout ao formatar (>10s)"
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
    """Formata codigo SQL usando sqlparse.

    Args:
        code: Codigo SQL a formatar.
        keyword_case: Case das keywords ('upper', 'lower', 'capitalize').
        identifier_case: Case dos identificadores (None = nao altera).
        indent_width: Largura da indentacao.
        reindent: Se deve reindentar o codigo.
        strip_comments: Se deve remover comentarios.

    Returns:
        Tupla (codigo_formatado, erro).
        Se erro for None, a formatacao foi bem-sucedida.
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
        return code, "sqlparse nao encontrado. Instale com: pip install sqlparse"
    except Exception as e:
        return code, str(e)


def format_code(code: str, language: str) -> tuple[str, str | None]:
    """Formata codigo de acordo com a linguagem.

    Args:
        code: Codigo a formatar.
        language: Linguagem ('python', 'sql', 'cross').

    Returns:
        Tupla (codigo_formatado, erro).
    """
    language = language.lower()

    if language == "python":
        return format_python(code)
    elif language in ("sql", "cross"):
        return format_sql(code)
    else:
        return code, f"Formatador nao disponivel para '{language}'"
