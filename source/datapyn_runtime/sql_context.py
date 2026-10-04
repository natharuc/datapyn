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
            escapes_backslash = db_type in {"mysql", "mariadb"} or postgres_escape
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
                if code[index] == "\\" and kind == "literal" and escapes_backslash:
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


def metadata_signature(code):
    cleaned = sql_code_mask(code or "")
    references = {_parts(match.group(1)) for match in _RELATION.finditer(cleaned)}
    # Only the prefix ending at a dot matters. The partial field to its right
    # changes on every key and cannot introduce new database metadata.
    prefixes = {_parts(match.group(1)) for match in _DOTTED.finditer(cleaned)}
    routines = bool(re.search(r"\b(?:EXEC|EXECUTE|CALL)\s", cleaned, re.IGNORECASE))
    return tuple(sorted(references)), tuple(sorted(prefixes)), routines


def changes_metadata(code):
    return bool(re.search(r"\b(?:CREATE|ALTER|DROP|RENAME)\s+(?:(?:OR\s+REPLACE|TEMP|TEMPORARY)\s+)?(?:TABLE|VIEW|SCHEMA|DATABASE|CATALOG|FUNCTION|PROCEDURE|INDEX)\b", sql_code_mask(code or ""), re.IGNORECASE))
