"""Bounded, offline classification of SQL which can destroy or replace data.

This is an execution confirmation aid, not an SQL validator or Python sandbox.
Queries are never sent to a database here. Strings/comments and quoted names do
not become SQL commands, while unsupported executable commands fail closed.
"""

from __future__ import annotations

import ast
from functools import lru_cache
import re

MAX_CODE_BYTES = 1024 * 1024
MAX_PARSE_CHARACTERS = 64 * 1024
MAX_PARSE_TOKENS = 6000
MAX_PARSE_DEPTH = 80
MAX_RISKS = 1000
MAX_PREVIEW = 500

_DIALECTS = {"sqlserver": "tsql", "mssql": "tsql", "postgresql": "postgres", "mariadb": "mysql"}
_OPAQUE = {"EXEC", "EXECUTE", "CALL", "DO", "PREPARE", "DEALLOCATE"}
_WHOLE_OBJECT = {"TRUNCATE", "DROP", "REPLACE", "INSERT OVERWRITE", "CREATE OR REPLACE", "RESTORE", "VACUUM"}
_DDL_KINDS = {"TABLE", "VIEW", "DATABASE", "SCHEMA", "INDEX", "FUNCTION", "PROCEDURE", "TRIGGER", "ROLE", "USER",
              "SEQUENCE", "MATERIALIZED", "CATALOG", "VOLUME", "PARTITION", "POLICY", "CONSTRAINT", "COLUMN"}
_PROCEDURAL = {"BEGIN", "THEN", "ELSE", "DO", "LOOP"}
_QUERY_OPERANDS = {"SELECT", "DISTINCT", "ALL", ",", "+", "-", "*", "/", "=", "AND", "OR"}
_SAFE_UNKNOWN_PREFIXES = {"SELECT", "WITH", "VALUES", "SHOW", "EXPLAIN", "DESCRIBE", "DESC", "USE", "SET", "RESET",
                          "BEGIN", "START", "COMMIT", "ROLLBACK", "SAVEPOINT", "RELEASE", "END", "DECLARE", "PRINT", "RETURN"}
_OPAQUE_FUNCTIONS = {"DBLINK_EXEC", "OPENQUERY", "OPENROWSET", "LO_UNLINK", "PG_TERMINATE_BACKEND", "PG_CANCEL_BACKEND"}
_ADMIN_COMMANDS = {"DBCC", "BACKUP", "REPAIR"}
_POTENTIAL_COMMANDS = {"DELETE", "UPDATE", "DROP", "ALTER", "TRUNCATE", "MERGE", "REPLACE", "OVERWRITE", "VACUUM",
                       "RESTORE", "RENAME", "REVOKE", "GRANT", "COPY", "PRAGMA"} | _OPAQUE | _OPAQUE_FUNCTIONS | _ADMIN_COMMANDS


def _validate(code):
    if not isinstance(code, str) or len(code.encode("utf-8")) > MAX_CODE_BYTES:
        raise ValueError("code must be a string of at most 1 MiB")


def _preview(code):
    return re.sub(r"\s+", " ", code).strip()[:MAX_PREVIEW]


def _risk(statement, operation, target, has_where, preview):
    return {"statement": statement, "operation": operation, "target": target or "",
            "has_where": bool(has_where),
            "unfiltered": operation in _WHOLE_OBJECT or operation in {"DELETE", "UPDATE"} and not has_where,
            "preview": _preview(preview)}


@lru_cache(maxsize=16)
def _tokenizer_class(name):
    from sqlglot import Dialect

    # Preserve dialect quoting/escapes, but never let an opaque command swallow
    # the remaining executable text as one synthetic string token.
    base = type(Dialect.get_or_raise(name).tokenizer())
    return type(f"Safety{base.__name__}", (base,), {"COMMANDS": set()})


def _target(expression, dialect):
    from sqlglot import exp

    while isinstance(expression, exp.Schema) or type(expression).__name__ in {"StoredProcedure", "UserDefinedFunction"}:
        expression = expression.this
    if isinstance(expression, exp.Table):
        return ".".join(part.sql(dialect=dialect) for part in expression.parts)[:300]
    if isinstance(expression, exp.Expression):
        return expression.sql(dialect=dialect, comments=False)[:300]
    return str(expression or "")[:300]


def _ast_risks(expressions, dialect, statement, preview):
    from sqlglot import exp

    risks = []
    opaque = False
    for root in expressions:
        if root is None:
            continue
        for node in root.walk():
            name = type(node).__name__
            operation, target, has_where = None, "", False
            # ALTER actions and MERGE branches are already represented by the
            # owning command; they are not separate unfiltered statements.
            if node is not root and node.find_ancestor(exp.Alter, exp.Merge) is not None:
                continue
            if isinstance(node, (exp.Delete, exp.Update)):
                operation = name.upper()
                target = _target(node.this, dialect)
                has_where = node.args.get("where") is not None and node.args.get("where") is not False
            elif isinstance(node, (exp.Drop, exp.Alter, exp.Merge)):
                operation, target = name.upper(), _target(node.this, dialect)
            elif isinstance(node, exp.TruncateTable):
                operation = "TRUNCATE"
                target = ", ".join(_target(item, dialect) for item in node.expressions)[:300]
            elif isinstance(node, exp.Insert):
                conflict = node.args.get("conflict")
                action = str(conflict.args.get("action") or "").upper() if conflict is not None else ""
                if node.args.get("overwrite"):
                    operation = "INSERT OVERWRITE"
                elif "UPDATE" in action:
                    operation = "UPSERT"
                elif node.args.get("alternative") and str(node.args["alternative"]).upper() == "REPLACE":
                    operation = "REPLACE"
                target = _target(node.this, dialect)
            elif isinstance(node, exp.Create) and node.args.get("replace"):
                operation, target = "CREATE OR REPLACE", _target(node.this, dialect)
            elif name in {"ExecuteSql", "Execute", "Call", "Revoke", "Grant", "RenameTable"}:
                operation = {"ExecuteSql": "EXECUTE", "RenameTable": "RENAME"}.get(name, name.upper())
                target = _target(node.args.get("this") or node.args.get("securable"), dialect)
            elif isinstance(node, exp.Anonymous) and node.name.upper() in _OPAQUE_FUNCTIONS:
                operation, target = "EXECUTE", node.name
            elif isinstance(node, exp.Copy) and any(isinstance(item, exp.Identifier) and item.name.upper() == "PROGRAM"
                                                   for item in node.args.get("files") or []):
                operation, target = "EXECUTE", _target(node.this, dialect)
            elif isinstance(node, exp.Pragma) and re.search(r"\bPRAGMA\b[^;]*=", preview, re.IGNORECASE):
                operation, target = "PRAGMA", _target(node.this.this, dialect)
            elif isinstance(node, exp.Command):
                opaque = True
            if operation:
                risks.append(_risk(statement, operation, target, has_where, preview))
    return risks, opaque


def _token_target(tokens, index, code):
    """A short original identifier path for unsupported dialect statements."""
    if index >= len(tokens):
        return ""
    if tokens[index].text.upper() == "TOP":
        index += 1
        if index < len(tokens) and tokens[index].token_type.name == "L_PAREN":
            depth = 1
            index += 1
            while index < len(tokens) and depth:
                depth += 1 if tokens[index].token_type.name == "L_PAREN" else -1 if tokens[index].token_type.name == "R_PAREN" else 0
                index += 1
        else:
            index += 1
        if index < len(tokens) and tokens[index].text.upper() == "PERCENT":
            index += 1
    while index < len(tokens) and tokens[index].text.upper() in {"FROM", "INTO", "TABLE", "DATABASE", "IF", "NOT", "EXISTS", "ONLY"}:
        index += 1
    if index >= len(tokens) or tokens[index].token_type.name in {"L_PAREN", "STRING", "NATIONAL_STRING", "RAW_STRING", "HEREDOC_STRING"}:
        return ""
    start, end = tokens[index].start, tokens[index].end + 1
    index += 1
    while index < len(tokens) and tokens[index].token_type.name == "DOT":
        end = tokens[index].end + 1
        index += 1
        if index < len(tokens):
            end = tokens[index].end + 1
            index += 1
    return code[start:end][:300]


def _fallback_risks(tokens, code, statement):
    """Conservative command detection when syntax cannot be fully parsed.

    Command-specific prefixes avoid treating SELECT aliases or string contents
    as mutations. Parenthesis depth scopes WHERE to the actual mutation.
    """
    result, depth, candidates, has_merge = [], 0, [], False
    insert_at_depth, insert_targets, target_overrides = {}, {}, {}
    depths = []
    for token in tokens:
        depths.append(depth)
        if token.token_type.name == "L_PAREN":
            depth += 1
        elif token.token_type.name == "R_PAREN":
            depth = max(0, depth - 1)
    # UPDATE may occur after IF/BEGIN without statement separators. Precompute
    # whether SET follows at its own depth instead of rescanning each suffix.
    update_has_set, depths_with_set = {}, set()
    for index in range(len(tokens) - 1, -1, -1):
        token = tokens[index]
        if token.token_type.name in {"STRING", "NATIONAL_STRING", "RAW_STRING", "HEREDOC_STRING", "IDENTIFIER"}:
            continue
        word = token.text.upper()
        if word == "UPDATE":
            update_has_set[index] = depths[index] in depths_with_set
        elif word == "SET":
            depths_with_set.add(depths[index])
    for index, token in enumerate(tokens):
        kind, word = token.token_type.name, token.text.upper()
        if kind in {"STRING", "NATIONAL_STRING", "RAW_STRING", "HEREDOC_STRING", "IDENTIFIER"}:
            continue
        previous = tokens[index - 1].text.upper() if index else ""
        if previous in {"AS", "."}:
            continue
        next_word = tokens[index + 1].text.upper() if index + 1 < len(tokens) else ""
        next_kind = tokens[index + 1].token_type.name if index + 1 < len(tokens) else ""
        at_start = index == 0 or previous in _PROCEDURAL or previous == ";"
        operation = None
        if word == "INSERT":
            insert_at_depth[depths[index]] = index
            insert_targets[depths[index]] = index + 1
        elif word == "INTO" and depths[index] in insert_at_depth:
            insert_targets[depths[index]] = index + 1
        if word == "DELETE" and previous not in _QUERY_OPERANDS and (at_start or next_word in {"FROM", "TOP", "LOW_PRIORITY", "QUICK", "IGNORE"}
                                  or next_kind in {"VAR", "IDENTIFIER"}):
            operation = "DELETE"
        elif word == "UPDATE" and previous in {"DO", "KEY"} and depths[index] in insert_at_depth:
            operation = "UPSERT"
            target_overrides[index] = insert_targets[depths[index]]
        elif word == "UPDATE" and previous not in _QUERY_OPERANDS and (at_start or next_kind in {"VAR", "IDENTIFIER"}):
            if at_start or update_has_set.get(index):
                operation = "UPDATE"
        elif word in {"DROP", "ALTER", "TRUNCATE"} and (at_start or next_word in _DDL_KINDS):
            if word == "ALTER" and index >= 2 and previous == "OR" and tokens[index - 2].text.upper() == "CREATE":
                continue
            if word == "DROP" and next_word in {"COLUMN", "CONSTRAINT", "PARTITION"} and candidates and candidates[-1][1] == "ALTER":
                continue
            operation = word
        elif word == "MERGE" and (at_start or next_word in {"INTO", "TOP"}):
            operation = word
        elif word == "REPLACE" and (at_start or next_word == "INTO"):
            operation = word
        elif word in {"VACUUM", "RESTORE", "RENAME", "REVOKE", "GRANT"} and (at_start or next_word in _DDL_KINDS):
            operation = word
        elif word in _ADMIN_COMMANDS and previous not in _QUERY_OPERANDS and (at_start or next_word not in {"FROM", "WHERE", ","}):
            operation = word
        elif word in _OPAQUE_FUNCTIONS and next_kind == "L_PAREN":
            operation = "EXECUTE"
            target_overrides[index] = index
        elif word in _OPAQUE and (at_start or word in {"EXEC", "EXECUTE", "CALL"} and previous not in _QUERY_OPERANDS):
            operation = "EXECUTE" if word == "EXEC" else word
        elif word == "INSERT" and next_word == "OVERWRITE":
            operation = "INSERT OVERWRITE"
        elif word == "CREATE" and next_word == "OR" and index + 2 < len(tokens) and tokens[index + 2].text.upper() in {"REPLACE", "ALTER"}:
            operation = "CREATE OR REPLACE"
        if operation:
            if operation in {"DELETE", "UPDATE"} and has_merge:
                continue
            candidates.append((index, operation))
            has_merge = has_merge or operation == "MERGE"
    for offset, (index, operation) in enumerate(candidates):
        following = candidates[offset + 1][0] if offset + 1 < len(candidates) else len(tokens)
        own_depth = depths[index]
        has_where = False
        if operation in {"DELETE", "UPDATE"}:
            for position in range(index + 1, following):
                if depths[position] < own_depth:
                    break
                if depths[position] == own_depth:
                    if tokens[position].text.upper() in {"SELECT", "INSERT", "CREATE", "PRINT", "RETURN"}:
                        break
                    if tokens[position].token_type.name == "WHERE":
                        has_where = True
                        break
        target_index = index + 1
        if operation == "INSERT OVERWRITE":
            target_index += 1
        elif operation == "CREATE OR REPLACE":
            target_index += 3
        elif operation in {"DROP", "ALTER", "TRUNCATE"} and target_index < len(tokens) and tokens[target_index].text.upper() in _DDL_KINDS:
            target_index += 1
        target = _token_target(tokens, target_overrides.get(index, target_index), code)
        end = tokens[following].start if following < len(tokens) else len(code)
        result.append(_risk(statement, operation, target, has_where, code[token_start: end]
                            if (token_start := tokens[index].start) >= 0 else code))
    return result


def _expand_executable_comments(code, db_type):
    """MySQL version-comments are executable SQL, unlike normal comments."""
    if db_type not in {"mysql", "mariadb"}:
        return code
    from .sql_context import lexical_spans

    output = None
    for start, end, kind, closed in lexical_spans(code, db_type):
        if kind != "comment" or not closed:
            continue
        prefix = re.match(r"/\*(M)?!(?:\d{5,6})?\s*", code[start:end], re.IGNORECASE)
        if prefix is None or prefix[1] and db_type != "mariadb":
            continue
        if output is None:
            output = list(code)
        for left, right in ((start, start + prefix.end()), (end - 2, end)):
            output[left:right] = ["\n" if char == "\n" else " " for char in code[left:right]]
    return "".join(output) if output is not None else code


def analyze_sql(code, db_type=""):
    """Return every destructive operation, including filtered UPDATE/DELETE.

    Results are pure JSON dictionaries. `has_where` reports only the mutation's
    own WHERE, never whether the predicate really restricts the affected rows.
    Large/unsupported scripts use a linear lexical fallback instead of skipping
    validation or spending unbounded time parsing a complex AST.
    """
    _validate(code)
    from sqlglot import Dialect
    from sqlglot.errors import ParseError, TokenError
    from src.services.syntax_validator import _silence_sqlglot_warnings
    from .sql_context import sql_statements, sql_code_mask

    name = _DIALECTS.get(str(db_type or "").lower(), str(db_type or "tsql").lower())
    try:
        dialect = Dialect.get_or_raise(name)
    except ValueError:
        name, dialect = "tsql", Dialect.get_or_raise("tsql")
    code = _expand_executable_comments(code, str(db_type or "").lower())
    risks = []
    for statement, chunk in enumerate(sql_statements(code, "sqlserver" if name == "tsql" else name), 1):
        # sql_statements exposes original spans, not normalized/reformatted SQL.
        batch = chunk[0] if isinstance(chunk, tuple) else chunk
        if not batch.strip():
            continue
        try:
            tokens = _tokenizer_class(name)(dialect=dialect).tokenize(batch)
        except TokenError:
            # Invalid quoting cannot execute as a normal statement. Keep any
            # definitely executable command preceding that incomplete literal.
            masked = sql_code_mask(batch, str(db_type or ""), identifiers=True)
            tokens = _tokenizer_class(name)(dialect=dialect).tokenize(masked)
        if not tokens:
            continue
        if tokens[0].text.upper() in _SAFE_UNKNOWN_PREFIXES | {"INSERT", "CREATE"} and not any(
            item.token_type.name not in {"STRING", "NATIONAL_STRING", "RAW_STRING", "HEREDOC_STRING", "IDENTIFIER"}
            and item.text.upper() in _POTENTIAL_COMMANDS for item in tokens
        ):
            continue
        depth = maximum_depth = 0
        for token in tokens:
            depth += 1 if token.token_type.name == "L_PAREN" else -1 if token.token_type.name == "R_PAREN" else 0
            maximum_depth = max(maximum_depth, depth)
        parsed, opaque = [], True
        if len(batch) <= MAX_PARSE_CHARACTERS and len(tokens) <= MAX_PARSE_TOKENS and maximum_depth <= MAX_PARSE_DEPTH:
            try:
                with _silence_sqlglot_warnings():
                    expressions = dialect.parser().parse(tokens, batch)
                parsed, opaque = _ast_risks(expressions, name, statement, batch)
            except (ParseError, TokenError, RecursionError, ValueError, TypeError):
                pass
        # Some valid procedural T-SQL is parsed as harmless aliases (for
        # example IF 1=1 DELETE FROM t). Never rely solely on a successful AST.
        fallback = _fallback_risks(tokens, batch, statement)
        lexical_filters = {(item["operation"], item["target"]): item["has_where"] for item in fallback
                           if item["operation"] in {"DELETE", "UPDATE"}}
        for item in parsed:
            key = item["operation"], item["target"]
            if key in lexical_filters:
                item["has_where"] = lexical_filters[key]
                item["unfiltered"] = not item["has_where"]
        keys = {(item["operation"], item["target"]) for item in parsed}
        parsed.extend(item for item in fallback if (item["operation"], item["target"]) not in keys)
        if not parsed and opaque:
            first = tokens[0].text.upper()
            # Unknown executable dialect commands cannot be assumed read-only.
            # Common query/session-control prefixes remain unprompted.
            if first not in _SAFE_UNKNOWN_PREFIXES:
                parsed.append(_risk(statement, first if len(first) <= 30 else "SQL COMMAND", "", False, batch))
        risks.extend(parsed)
        if len(risks) > MAX_RISKS:
            return risks[:MAX_RISKS] + [_risk(statement, "ADDITIONAL SQL", "", False,
                                             "Additional destructive SQL statements require confirmation.")]
    return risks


def _literal_sql(node):
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left, right = _literal_sql(node.left), _literal_sql(node.right)
        if left is not None and right is not None:
            return left + right
    if isinstance(node, ast.JoinedStr) and all(isinstance(item, ast.Constant) and isinstance(item.value, str) for item in node.values):
        return "".join(item.value for item in node.values)
    if isinstance(node, ast.Call) and ((isinstance(node.func, ast.Name) and node.func.id == "text")
                                      or isinstance(node.func, ast.Attribute) and node.func.attr == "text") and node.args:
        return _literal_sql(node.args[0])
    return None


def analyze_python(code, db_type=""):
    """Review recognized SQL calls without evaluating Python or its arguments.

    Dynamic SQL calls require confirmation even when their text cannot be known
    statically. Arbitrary Python, external processes and network libraries are
    not sandboxed by this helper.
    """
    _validate(code)
    try:
        tree = ast.parse(code)
    except (SyntaxError, RecursionError):
        return []  # Python compiles the complete block before running it.
    risks = []
    methods = {"execute", "executemany", "executescript", "exec_driver_sql", "sql", "read_sql", "read_sql_query"}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = node.func.id if isinstance(node.func, ast.Name) else node.func.attr if isinstance(node.func, ast.Attribute) else ""
        keywords = {item.arg: item.value for item in node.keywords if item.arg is not None}
        if name == "to_sql":
            mode = keywords.get("if_exists")
            if mode is None or isinstance(mode, ast.Constant) and mode.value not in {"replace", "delete_rows"}:
                continue
            target = _literal_sql(node.args[0] if node.args else keywords.get("name")) or ""
            operation = {"replace": "REPLACE TABLE", "delete_rows": "DELETE"}.get(mode.value, "DYNAMIC SQL") if isinstance(mode, ast.Constant) else "DYNAMIC SQL"
            preview = ast.get_source_segment(code, node) or "SQL executed from Python"
            risks.append(_risk(node.lineno, operation, target, False, preview))
        elif name in methods:
            query = node.args[0] if node.args else next((keywords[key] for key in ("sql", "query", "statement", "operation") if key in keywords), None)
            text = _literal_sql(query)
            if text is None:
                preview = ast.get_source_segment(code, node) or "SQL executed from Python"
                risks.append(_risk(node.lineno, "DYNAMIC SQL", "", False, preview))
            else:
                for item in analyze_sql(text, db_type):
                    risks.append({**item, "statement": node.lineno})
        if len(risks) > MAX_RISKS:
            return risks[:MAX_RISKS] + [_risk(node.lineno, "ADDITIONAL SQL", "", False,
                                             "Additional SQL calls from Python require confirmation.")]
    return risks
