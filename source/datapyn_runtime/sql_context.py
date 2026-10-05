"""Small immutable metadata keys; typing an expression never reloads a catalog."""

from __future__ import annotations

import re

_IDENTIFIER = r'(?:\[(?:\]\]|[^\]])+\]|`(?:``|[^`])+`|"(?:""|[^"])+"|[#\w$]+)'
_PATH = _IDENTIFIER + r'(?:\s*\.\s*(?:\.\s*)?' + _IDENTIFIER + r')*'
_RELATION = re.compile(r'\b(?:FROM|JOIN|UPDATE|INTO|TABLE)\s+(' + _PATH + r')', re.IGNORECASE)
_DOTTED = re.compile(r'(?<![\w$#])(' + _PATH + r')\s*\.', re.IGNORECASE)
_PART = re.compile(_IDENTIFIER)


def lexical_spans(code, db_type=""):
    """Yield comments, literals and quoted names without confusing their contents.

    Offsets are preserved so a semicolon inside a comment/name cannot split a
    statement, and the editor can distinguish an unfinished name from a string.
    """
    index, size = 0, len(code)
    while index < size:
        start, char = index, code[index]
        if code.startswith("--", index) or (char == "#" and db_type in {"mysql", "mariadb"}):
            end = code.find("\n", index)
            index = size if end < 0 else end
            yield start, index, "comment", end >= 0
        elif code.startswith("/*", index):
            index += 2
            depth = 1
            while index < size and depth:
                if code.startswith("/*", index):
                    depth += 1
                    index += 2
                elif code.startswith("*/", index):
                    depth -= 1
                    index += 2
                else:
                    index += 1
            yield start, index, "comment", depth == 0
        elif char in {"'", '"', "`", "["}:
            kind = "literal" if char == "'" else "identifier"
            closing = "]" if char == "[" else char
            postgres_escape = db_type in {"", "postgres", "postgresql"} and start > 0 and code[start - 1] in {"E", "e"} and (start < 2 or not re.match(r"[\w$]", code[start - 2]))
            databricks_raw = db_type == "databricks" and start > 0 and code[start - 1] in {"R", "r"} and (start < 2 or not re.match(r"[\w$]", code[start - 2]))
            escapes_backslash = db_type in {"mysql", "mariadb"} or (db_type == "databricks" and not databricks_raw) or postgres_escape
            index += 1
            closed = False
            while index < size:
                if code[index] == closing:
                    index += 1
                    if index < size and code[index] == closing:
                        index += 1
                        continue
                    closed = True
                    break
                if code[index] == "\\" and (kind == "literal" or (db_type == "databricks" and char == '"')) and escapes_backslash:
                    index += 1
                index += 1
            index = min(index, size)
            yield start, index, kind, closed
        elif char == "$" and db_type in {"", "postgres", "postgresql"} and (match := re.match(r"\$(?:[A-Za-z_]\w*)?\$", code[index:])):
            delimiter = match.group()
            end = code.find(delimiter, index + len(delimiter))
            index = size if end < 0 else end + len(delimiter)
            yield start, index, "literal", end >= 0
        else:
            index += 1


def sql_code_mask(code, db_type="", *, identifiers=False):
    """Replace noise with spaces while retaining newlines and cursor offsets."""
    masked = list(code)
    for start, end, kind, _closed in lexical_spans(code, db_type):
        if kind == "identifier" and not identifiers:
            continue
        masked[start:end] = ["\n" if char == "\n" else " " for char in code[start:end]]
    return "".join(masked)


def sql_statement_boundaries(code, db_type=""):
    masked = sql_code_mask(code, db_type, identifiers=True)
    boundaries = [(match.start(), match.end()) for match in re.finditer(";", masked)]
    if db_type in {"sqlserver", "mssql"}:
        boundaries.extend((match.start(), match.end()) for match in re.finditer(r"(?im)^[ \t]*GO(?:[ \t]+\d+)?[ \t]*(?=\n|$)", masked))
    return sorted(boundaries)


def sql_statements(code, db_type=""):
    """Split ordinary statements without treating quoted text as SQL syntax."""
    if db_type == "databricks" and re.match(r"\s*(?:BEGIN\b|CREATE\s+(?:OR\s+REPLACE\s+)?(?:PROCEDURE|FUNCTION)\b)", sql_code_mask(code, db_type, identifiers=True), re.IGNORECASE):
        # Databricks scripting/routine bodies are a single server statement.
        # Their internal semicolons must retain the original execution unit.
        return [code.strip()]
    start = 0
    statements = []
    for left, right in sql_statement_boundaries(code, db_type):
        statement = code[start:left].strip()
        if sql_code_mask(statement, db_type, identifiers=True).strip():
            statements.append(statement)
        start = right
    statement = code[start:].strip()
    if sql_code_mask(statement, db_type, identifiers=True).strip():
        statements.append(statement)
    return statements


def changes_sql_context(code, db_type=""):
    """Identify scripts needing one post-execution context probe.

    This is a trigger, never a prediction of success or the resulting context.
    The driver reads the real database/schema on the connection that ran SQL.
    """
    engine = str(db_type or "").lower()
    cleaned = sql_code_mask(code or "", engine, identifiers=True)
    if engine in {"sqlserver", "mssql", "mysql", "mariadb", "databricks"}:
        return bool(re.search(r"\bUSE\s+", cleaned, re.IGNORECASE))
    if engine in {"postgres", "postgresql"}:
        # Restore only the quoted setting name, never arbitrary quoted SQL.
        names = list(cleaned)
        for start, end, kind, _closed in lexical_spans(code or "", engine):
            if kind == "identifier" and code[start:end].casefold() == '"search_path"':
                names[start:end] = code[start:end]
        names = "".join(names)
        if re.search(r'\b(?:SET\s+(?:(?:SESSION|LOCAL)\s+)?(?:(?:search_path|"search_path")\s*(?:TO|=)|SCHEMA\b)|RESET\s+(?:search_path|ALL)\b|DISCARD\s+ALL\b)', names, re.IGNORECASE):
            return True
        return any(re.match(r"\s*'search_path'\s*,", code[match.end():], re.IGNORECASE)
                   for match in re.finditer(r"\bset_config\s*\(", cleaned, re.IGNORECASE))
    return False


def sql_cursor_blocked(code, offset, db_type=""):
    for start, end, kind, closed in lexical_spans(code, db_type):
        if start < offset < end or (offset == end and (not closed or (kind == "comment" and code[end:end + 1] == "\n"))):
            return kind != "identifier"
        if start >= offset:
            break
    return False


def _parts(path):
    path = re.sub(r"\.\s*\.", ".dbo.", path)
    return tuple(part[1:-1].replace(part[-1] * 2, part[-1]).casefold()
                 if part[:1] in {'[', '`', '"'} else part.casefold()
                 for part in _PART.findall(path))


def _comma_relations(code, db_type):
    """Use the existing dialect lexer for comma-separated FROM sources."""
    if "," not in code:
        return set()
    from sqlglot import Dialect
    from sqlglot.tokens import TokenType
    dialect = {"sqlserver": "tsql", "postgresql": "postgres", "mariadb": "mysql"}.get(db_type, db_type or "tsql")
    # An unfinished quoted field must not hide valid FROM sources to its left.
    masked = list(code)
    for start, end, kind, closed in lexical_spans(code, db_type):
        if kind == "identifier" and not closed:
            masked[start:end] = [" " if char != "\n" else "\n" for char in code[start:end]]
    cleaned = "".join(masked)
    try:
        tokens = Dialect.get_or_raise(dialect).tokenizer().tokenize(cleaned)
    except Exception:
        return set()
    identifiers = {TokenType.VAR, TokenType.IDENTIFIER}
    ending = {TokenType.WHERE, TokenType.GROUP_BY, TokenType.ORDER_BY, TokenType.HAVING,
              TokenType.QUALIFY, TokenType.LIMIT, TokenType.OFFSET, TokenType.UNION,
              TokenType.EXCEPT, TokenType.INTERSECT, TokenType.RETURNING, TokenType.SET,
              TokenType.VALUES, TokenType.SEMICOLON, TokenType.SELECT}
    depth, from_depths, references = 0, set(), set()
    for index, token in enumerate(tokens):
        kind = token.token_type
        if kind == TokenType.L_PAREN:
            depth += 1
        elif kind == TokenType.R_PAREN:
            from_depths.discard(depth)
            depth = max(0, depth - 1)
        elif kind == TokenType.FROM:
            from_depths.add(depth)
        elif kind in ending:
            from_depths.discard(depth)
        elif kind == TokenType.COMMA and depth in from_depths:
            cursor = index + 1
            if cursor >= len(tokens) or tokens[cursor].token_type not in identifiers:
                continue
            start, end = tokens[cursor].start, tokens[cursor].end + 1
            cursor += 1
            while cursor < len(tokens) and tokens[cursor].token_type == TokenType.DOT:
                cursor += 1
                if cursor < len(tokens) and tokens[cursor].token_type == TokenType.DOT:
                    cursor += 1  # SQL Server database..table.
                if cursor >= len(tokens) or tokens[cursor].token_type not in identifiers:
                    break
                end = tokens[cursor].end + 1
                cursor += 1
            references.add(_parts(cleaned[start:end]))
    return references


def metadata_signature(code, db_type=""):
    cleaned = sql_code_mask(code or "", db_type)
    references = {_parts(match.group(1)) for match in _RELATION.finditer(cleaned)}
    references.update(_comma_relations(cleaned, db_type))
    # Only the prefix ending at a dot matters. The partial field to its right
    # changes on every key and cannot introduce new database metadata.
    prefixes = {_parts(match.group(1)) for match in _DOTTED.finditer(cleaned)}
    routines = bool(re.search(r"\b(?:EXEC|EXECUTE|CALL)\s", cleaned, re.IGNORECASE))
    return tuple(sorted(references)), tuple(sorted(prefixes)), routines


def changes_metadata(code):
    return bool(re.search(r"\b(?:CREATE|ALTER|DROP|RENAME)\s+(?:(?:OR\s+REPLACE|TEMP|TEMPORARY)\s+)?(?:TABLE|VIEW|SCHEMA|DATABASE|CATALOG|FUNCTION|PROCEDURE|INDEX)\b", sql_code_mask(code or ""), re.IGNORECASE))
