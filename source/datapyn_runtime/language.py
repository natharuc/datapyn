"""Qt-free editor intelligence on immutable namespace/schema snapshots."""

from __future__ import annotations

from dataclasses import asdict
from itertools import islice
import json
import os
from pathlib import Path
import subprocess
import sys
import threading

MAX_DOCUMENT_BYTES = 1024 * 1024
_JEDI_LOCK = threading.RLock()
_JEDI_ENVIRONMENT = None


def initialize_completion_worker():
    """Initialize native inference libraries on the owned worker's main thread."""
    global _JEDI_ENVIRONMENT
    from .desktop_services import enable_user_packages
    enable_user_packages()
    import numpy
    import pandas
    import polars
    import jedi
    _JEDI_ENVIRONMENT = jedi.InterpreterEnvironment()


def namespace_snapshot(namespace):
    variables = {}
    for name, value in list(namespace.items()):
        if not isinstance(name, str) or name.startswith("_") or not name.isidentifier():
            continue
        value_type = type(value)
        item = {"type": type.__getattribute__(value_type, "__name__")}
        module = type.__getattribute__(value_type, "__module__")
        # Inspect only known data containers. User-defined attributes can run
        # arbitrary Python, including properties that block indefinitely.
        columns = value.columns if item["type"] == "DataFrame" and module.startswith(("pandas.", "polars.")) else None
        if columns is not None:
            item["columns"] = [str(column) for column in islice(columns, 100)]
        variables[name] = item
        if len(variables) >= 1000:
            break
    return variables


def _namespace_header(variables):
    lines = ["import pandas as pd", "import numpy as np", "import polars as pl"]
    for name, metadata in variables.items():
        if not name.isidentifier() or name.startswith("_"):
            continue
        kind = metadata.get("type") if isinstance(metadata, dict) else str(metadata)
        if kind == "DataFrame":
            lines.append(f"{name} = pd.DataFrame(columns={json.dumps(metadata.get('columns', []), ensure_ascii=True)})")
        elif kind == "Series":
            lines.append(f"{name}: pd.Series = pd.Series(dtype='object')")
        elif kind == "ndarray":
            lines.append(f"{name}: np.ndarray = np.array([])")
        elif kind in {"list", "dict", "str", "int", "float", "bool", "set", "tuple"}:
            lines.append(f"{name}: {kind} = {kind}()")
    return "\n".join(lines) + "\n"


def _python_complete_unlocked(code, line, column, variables):
    import jedi
    header = _namespace_header(variables)
    environment = _JEDI_ENVIRONMENT
    if environment is None and getattr(sys, "frozen", False):
        # A frozen application executable cannot run Jedi's Python script
        # subprocess. The owned completion process supplies native inference.
        environment = jedi.InterpreterEnvironment()
    script = jedi.Script(header + code, environment=environment)
    items, seen = [], set()
    for item in script.complete(line + header.count("\n"), column)[:200]:
        if item.name in seen or item.name.startswith("__"):
            continue
        seen.add(item.name)
        # Signature resolution can execute expensive static inference for third
        # party libraries. Resolve it only when the user requests hover later.
        items.append({"label": item.name, "kind": item.type or "variable", "detail": item.description or "", "insert_text": item.name})
    return items


def _python_complete(code, line, column, variables):
    # Jedi/parso reuse parser state by default. One lock protects that cache
    # while other workers can still format, validate or test connections.
    with _JEDI_LOCK:
        return _python_complete_unlocked(code, line, column, variables)


def _format_python(code, options):
    from src.services.code_formatter_service import format_python
    line_length = int(options.get("line_length", 88))
    if not 40 <= line_length <= 320:
        raise ValueError("line_length must be between 40 and 320")
    if not getattr(sys, "frozen", False):
        return format_python(code, line_length=line_length)
    # Frozen executables cannot invoke themselves with `-m ruff`.
    root = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    candidates = [root / "ruff.exe", root / "ruff", root / "ruff" / "ruff.exe", root / "ruff" / "ruff"]
    executable = next((candidate for candidate in candidates if candidate.is_file()), None)
    if executable is None:
        return code, "The bundled Python formatter is unavailable"
    result = subprocess.run([str(executable), "format", "--line-length", str(line_length), "-"],
                            input=code, capture_output=True, text=True, timeout=10,
                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    return (result.stdout, None) if result.returncode == 0 else (code, result.stderr.strip())


def dispatch(method, params, context=None):
    from src.core.parameter_settings import use_shared_parameter_delimiter
    with use_shared_parameter_delimiter(params.get("shared_delimiter", "{{name}}")):
        return _dispatch(method, params, context)


def _dispatch(method, params, context=None):
    context = context or {}
    if method == "parameters.scan":
        from src.utils.sql_parameter_service import merge_parameter_definitions, merge_shared_parameter_definitions
        code = params.get("code", "")
        codes = params.get("codes", [code])
        if not isinstance(code, str) or not isinstance(codes, list) or len(codes) > 500 or any(not isinstance(item, str) for item in codes):
            raise ValueError("code must be a string and codes a list of at most 500 strings")
        if sum(len(item.encode("utf-8")) for item in codes) > MAX_DOCUMENT_BYTES:
            raise ValueError("Parameter source exceeds 1 MiB")
        # A caller that supplies only codes scans the first block for local params.
        if not code and codes:
            code = codes[0]
        for field in ("sql_parameters", "shared_parameters"):
            if params.get(field) is not None and not isinstance(params[field], list):
                raise ValueError(f"{field} must be a list")
        schema = context.get("schema") or {}
        return {"sql_parameters": merge_parameter_definitions(code, params.get("sql_parameters"), schema),
                "shared_parameters": merge_shared_parameter_definitions(codes, params.get("shared_parameters"), [schema])}
    code = params.get("code")
    if not isinstance(code, str) or len(code.encode("utf-8")) > MAX_DOCUMENT_BYTES:
        raise ValueError("code must be a string of at most 1 MiB")
    language = params.get("language")
    if language not in {"python", "sql"}:
        raise ValueError("language must be python or sql")
    schema = context.get("schema") or {}
    variables = context.get("variables") or {}
    if method == "language.complete":
        line, column = params.get("line"), params.get("column")
        if isinstance(line, bool) or not isinstance(line, int) or line < 1:
            raise ValueError("line must be a positive integer")
        if isinstance(column, bool) or not isinstance(column, int) or column < 1:
            raise ValueError("column must be a positive integer")
        if language == "python":
            items = _python_complete(code, line, column - 1, variables)
        else:
            from src.services.sql_autocomplete_service import SqlAutoCompleteService
            service = SqlAutoCompleteService()
            service.set_schema(schema)
            items = [{"label": label, "kind": kind, "detail": detail, "insert_text": label}
                     for label, kind, detail in service.get_completions(code, line - 1, column - 1)[:500]]
        return {"items": items, "context_version": context.get("version", 0)}
    if method == "language.diagnostics":
        from src.services.syntax_validator import validate_code
        # A partial lazy schema has no columns for unreferenced tables. Syntax
        # and names from the session remain useful without false schema errors.
        complete_schema = schema if context.get("schema_complete", False) else None
        markers = validate_code(language, code, db_type=schema.get("db_type"), schema=complete_schema,
                                namespace=variables if language == "python" else None)
        return {"markers": [asdict(marker) for marker in markers[:200]]}
    if method == "language.format":
        options = params.get("options") or {}
        if not isinstance(options, dict):
            raise ValueError("options must be an object")
        if language == "python":
            formatted, error = _format_python(code, options)
        else:
            from src.services.code_formatter_service import format_sql
            allowed = {key: value for key, value in options.items()
                       if key in {"keyword_case", "identifier_case", "indent_width", "reindent", "strip_comments"}}
            formatted, error = format_sql(code, **allowed)
        return {"code": formatted, "error": error}
    raise ValueError(f"Unknown language method: {method}")
