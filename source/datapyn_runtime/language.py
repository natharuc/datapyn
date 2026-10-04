"""Qt-free editor intelligence on immutable namespace/schema snapshots."""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import asdict
from functools import lru_cache
from itertools import islice
import json
import keyword
from pathlib import Path
import re
import subprocess
import sys
import threading
import types

MAX_DOCUMENT_BYTES = 1024 * 1024
_JEDI_LOCK = threading.RLock()
_JEDI_ENVIRONMENT = None
_SQL_LOCK = threading.RLock()
_SQL_SERVICES = OrderedDict()
_PYTHON_RESULTS = OrderedDict()
_PYTHON_CACHE_BYTES = 0
MAX_COMPLETION_CACHE_BYTES = 4 * MAX_DOCUMENT_BYTES


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
        if value_type is types.ModuleType:
            item["module"] = types.ModuleType.__getattribute__(value, "__name__")
        elif value_type in {types.FunctionType, types.BuiltinFunctionType}:
            item["module"] = object.__getattribute__(value, "__module__")
            item["qualname"] = object.__getattribute__(value, "__name__")
        elif value_type is type:
            item["module"] = type.__getattribute__(value, "__module__")
            item["qualname"] = type.__getattribute__(value, "__name__")
        for field in ("module", "qualname"):
            if field in item and type(item[field]) is not str:
                item.pop(field)
        # Inspect only known data containers. User-defined attributes can run
        # arbitrary Python, including properties that block indefinitely.
        pandas = sys.modules.get("pandas")
        polars = sys.modules.get("polars")
        dataframe_types = tuple(container.__dict__.get("DataFrame") for container in (pandas, polars) if container is not None)
        columns = value.columns if value_type in dataframe_types else None
        if columns is not None:
            item["columns"] = [str(column) for column in islice(columns, 1000) if type(column) in {str, int, float, bool, type(None)}]
            item["module"] = module
        elif item["type"] in {"Series", "ndarray"} and module.startswith(("pandas.", "polars.", "numpy")):
            item["module"] = module
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
        metadata = metadata if isinstance(metadata, dict) else {"type": kind}
        module = metadata.get("module") or ""
        valid_module = isinstance(module, str) and module != "__main__" and all(part.isidentifier() for part in module.split("."))
        if kind == "DataFrame":
            if module.startswith("polars."):
                lines.append(f"{name}: pl.DataFrame = pl.DataFrame()")
            else:
                lines.append(f"{name}: pd.DataFrame = pd.DataFrame(columns={json.dumps(metadata.get('columns', []), ensure_ascii=True)})")
        elif kind == "Series":
            lines.append(f"{name}: pl.Series = pl.Series()" if module.startswith("polars.") else f"{name}: pd.Series = pd.Series(dtype='object')")
        elif kind == "ndarray":
            lines.append(f"{name}: np.ndarray = np.array([])")
        elif kind in {"list", "dict", "str", "int", "float", "bool", "set", "tuple"}:
            lines.append(f"{name}: {kind} = {kind}()")
        elif kind == "module" and valid_module:
            lines.append(f"import {module} as {name}")
        elif kind in {"function", "builtin_function_or_method", "type"} and valid_module and str(metadata.get("qualname", "")).isidentifier():
            lines.append(f"from {module} import {metadata['qualname']} as {name}")
    return "\n".join(lines) + "\n"


def _python_complete_unlocked(code, line, column, variables, preamble="", global_imports=""):
    import jedi
    items, seen, string_key = _python_snapshot_completions(code, line, column, variables)
    if string_key:
        return items
    header = "\n".join(part for part in (_safe_context_source(global_imports), _safe_context_source(preamble), _namespace_header(variables)) if part).rstrip() + "\n"
    environment = _JEDI_ENVIRONMENT
    if environment is None and getattr(sys, "frozen", False):
        # A frozen application executable cannot run Jedi's Python script
        # subprocess. The owned completion process supplies native inference.
        environment = jedi.InterpreterEnvironment()
    script = jedi.Script(header + code, environment=environment)
    for item in script.complete(line + header.count("\n"), column)[:200]:
        if item.name in seen or item.name.startswith("__"):
            continue
        seen.add(item.name)
        # Signature resolution can execute expensive static inference for third
        # party libraries. Resolve it only when the user requests hover later.
        items.append({"label": item.name, "kind": item.type or "variable", "detail": item.description or "", "insert_text": item.name})
    # Modules, user functions and objects with an unknown type still belong in
    # the namespace list. Their attributes are never inspected in the kernel.
    before = code.split("\n")[line - 1][:column]
    token = re.search(r"(?<![\w.])([A-Za-z_][\w]*)?$", before)
    if token and not _inside_python_string(before):
        prefix = token.group(1) or ""
        for name, metadata in variables.items():
            if name not in seen and name.isidentifier() and name.startswith(prefix):
                items.append({"label": name, "kind": "variable", "detail": str(metadata.get("type", "") if isinstance(metadata, dict) else metadata), "insert_text": name})
    return items[:500]


def _python_complete(code, line, column, variables, preamble="", global_imports=""):
    # Jedi/parso reuse parser state by default. One lock protects that cache
    # while other workers can still format, validate or test connections.
    with _JEDI_LOCK:
        global _PYTHON_CACHE_BYTES
        key = (code, line, column, preamble, global_imports, json.dumps(variables, sort_keys=True, separators=(",", ":")))
        if key in _PYTHON_RESULTS:
            _PYTHON_RESULTS.move_to_end(key)
            return [dict(item) for item in _PYTHON_RESULTS[key][1]]
        result = _python_complete_unlocked(code, line, column, variables, preamble, global_imports)
        cost = sum(len(part.encode("utf-8")) for part in (code, preamble, global_imports, key[-1]))
        _PYTHON_RESULTS[key] = (cost, result)
        _PYTHON_CACHE_BYTES += cost
        while len(_PYTHON_RESULTS) > 64 or _PYTHON_CACHE_BYTES > MAX_COMPLETION_CACHE_BYTES:
            _old_key, (old_cost, _old_items) = _PYTHON_RESULTS.popitem(last=False)
            _PYTHON_CACHE_BYTES -= old_cost
        return [dict(item) for item in result]


def _inside_python_string(before):
    # Tokenize tolerates incomplete strings poorly; this lightweight scan is
    # only a guard for adding plain namespace names, never an inference engine.
    return bool(re.search(r"(?:^|[^\\])(?:'[^'\n]*|\"[^\"\n]*)$", before))


@lru_cache(maxsize=8)
def _safe_context_source(source):
    """Malformed peer blocks cannot absorb the active block in an open string."""
    import ast
    for _attempt in range(3):
        try:
            ast.parse(source)
            return source
        except SyntaxError as exc:
            source = "\n".join(source.splitlines()[:max(0, (exc.lineno or 1) - 1)])
    return ""


def _python_snapshot_completions(code, line, column, variables):
    current = code.split("\n")[line - 1]
    before = current[:column]
    member = re.search(r"(?<![\w.])([A-Za-z_]\w*)\.([\w]*)$", before)
    subscript = re.search(r"(?<![\w.])([A-Za-z_]\w*)\[\s*(['\"])((?:\\.|[^\\'\"\n])*)$", before)
    match = subscript or member
    metadata = variables.get(match.group(1)) if match else None
    if not isinstance(metadata, dict) or metadata.get("type") != "DataFrame":
        return [], set(), bool(subscript)
    prefix = match.group(3) if subscript else match.group(2)
    if subscript:
        try:
            import ast
            prefix = ast.literal_eval(match.group(2) + prefix + match.group(2))
        except (ValueError, SyntaxError):
            pass
    items, seen = [], set()
    for value in metadata.get("columns", []):
        name = str(value)
        if name in seen or not name.startswith(prefix) or (not subscript and (not name.isidentifier() or keyword.iskeyword(name))):
            continue
        seen.add(name)
        item = {"label": name, "kind": "field", "detail": f"{match.group(1)} column", "insert_text": name}
        if subscript:
            quote = match.group(2)
            item["insert_text"] = name.replace("\\", "\\\\").replace(quote, "\\" + quote).replace("\n", "\\n").replace("\r", "\\r")
            suffix = re.match(r"(?:\\.|[^\\'\"\n])*", current[column:]).group(0)
            item["start_column"] = len(current[:match.start(3)].encode("utf-16-le")) // 2 + 1
            item["end_column"] = len(current[:column + len(suffix)].encode("utf-16-le")) // 2 + 1
        items.append(item)
    return items, seen, bool(subscript)


def _cursor_position(code, line, column):
    lines = code.split("\n")
    if isinstance(line, bool) or not isinstance(line, int) or not 1 <= line <= len(lines):
        raise ValueError("line must identify an existing document line")
    if isinstance(column, bool) or not isinstance(column, int) or column < 1:
        raise ValueError("column must be a positive UTF-16 position")
    units, result = 0, 0
    for character in lines[line - 1]:
        if units == column - 1:
            break
        units += 2 if ord(character) > 0xFFFF else 1
        result += 1
    if units != column - 1:
        raise ValueError("column must identify an existing UTF-16 character boundary")
    return result


def _dotted_suffix_index(names):
    groups = {}
    for name in names:
        if "." in name:
            groups.setdefault(name.rpartition(".")[2], []).append(name)
    return {tail: tuple(sorted(group, key=len, reverse=True)) for tail, group in groups.items()}


def _sql_complete(code, line, column, schema):
    from .sql_completion import RuntimeSqlAutoCompleteService
    from .explorer import quote
    with _SQL_LOCK:
        key = id(schema)
        cached = _SQL_SERVICES.get(key)
        if cached is None or cached[0] is not schema:
            service = RuntimeSqlAutoCompleteService()
            service.set_schema(schema)
            literal_names = {str(table.get("name", "")) for table in schema.get("tables", []) if isinstance(table, dict)}
            column_names = {str(column.get("name", "")) for columns in schema.get("columns", {}).values() for column in columns if isinstance(column, dict)}
            suffix_indexes = {"table": _dotted_suffix_index(literal_names), "column": _dotted_suffix_index(column_names)}
            cached = (schema, service, literal_names, column_names, suffix_indexes)
            _SQL_SERVICES[key] = cached
        _SQL_SERVICES.move_to_end(key)
        while len(_SQL_SERVICES) > 4:
            _SQL_SERVICES.popitem(last=False)
        db_type = str(schema.get("db_type", "")).lower()
        service = cached[1]
        literal_names = cached[2]
        column_names = cached[3]
        result = []
        before = code.split("\n")[line - 1][:column]
        prefix_match = re.search(r'(?:\[([^\]]*)|"([^"]*)|`([^`]*)|([@\w$]+))$', before)
        prefix = next((value for value in prefix_match.groups() if value is not None), "").casefold() if prefix_match else ""
        raw = service.get_completions(code, line - 1, column)
        if prefix:
            # Filter before the payload bound. A table beyond the first five
            # hundred catalog entries must still be discoverable by its name.
            def rank(item):
                label = item[0].casefold()
                parts = service._split_identifier_parts(item[0])
                bare = parts[-1].casefold() if parts else label
                if label.startswith(prefix) or bare.startswith(prefix):
                    return 0
                if prefix in label:
                    return 1
                characters = iter(label)
                return 2 if all(character in characters for character in prefix) else 3
            ranked = [(rank(item), item) for item in raw]
            raw = [item for priority, item in sorted(ranked, key=lambda entry: entry[0]) if priority < 3]
        for label, kind, detail in raw[:500]:
            insertion = label
            if kind in {"table", "column", "schema", "database", "routine"}:
                known_names = column_names if kind == "column" else literal_names if kind == "table" else set()
                if label in known_names:
                    parts = [label]
                else:
                    group = cached[4].get(kind, {}).get(label.rpartition(".")[2], ())
                    name = next((name for name in group if label.endswith("." + name)), None)
                    if name is not None:
                        parts = service._split_identifier_parts(label[:-len(name) - 1]) + [name]
                    else:
                        parts = service._split_identifier_parts(label)
                # Identifier quoting also covers dialect-specific reserved
                # words that are absent from a portable keyword suggestion list.
                insertion = quote("sqlserver" if db_type == "mssql" else db_type, *parts)
            result.append({"label": label, "kind": kind, "detail": detail, "category": kind, "insert_text": insertion})
        return result


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
        cursor = _cursor_position(code, line, column)
        if language == "python":
            preamble, imports = params.get("preamble") or "", params.get("global_imports") or ""
            if not isinstance(preamble, str) or not isinstance(imports, str) or sum(len(text.encode("utf-8")) for text in (code, preamble, imports)) > MAX_DOCUMENT_BYTES:
                raise ValueError("Combined Python document and context must be strings of at most 1 MiB")
            items = _python_complete(code, line, cursor, variables, preamble, imports)
        else:
            items = _sql_complete(code, line, cursor, schema)
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
