"""Small immutable metadata keys; typing an expression never reloads a catalog."""

from __future__ import annotations

import re

_NOISE = re.compile(r"--[^\n]*|/\*.*?(?:\*/|$)|'(?:''|[^'])*(?:'|$)", re.DOTALL)
_IDENTIFIER = r'(?:\[(?:\]\]|[^\]])+\]|`(?:``|[^`])+`|"(?:""|[^"])+"|[#\w$]+)'
_PATH = _IDENTIFIER + r'(?:\s*\.\s*(?:\.\s*)?' + _IDENTIFIER + r')*'
_RELATION = re.compile(r'\b(?:FROM|JOIN|UPDATE|INTO|TABLE)\s+(' + _PATH + r')', re.IGNORECASE)
_DOTTED = re.compile(r'(?<![\w$#])(' + _PATH + r')\s*\.', re.IGNORECASE)
_PART = re.compile(_IDENTIFIER)


def _parts(path):
    path = re.sub(r"\.\s*\.", ".dbo.", path)
    return tuple(part[1:-1].replace(part[-1] * 2, part[-1]).casefold()
                 if part[:1] in {'[', '`', '"'} else part.casefold()
                 for part in _PART.findall(path))


def metadata_signature(code):
    cleaned = _NOISE.sub(" ", code or "")
    references = {_parts(match.group(1)) for match in _RELATION.finditer(cleaned)}
    # Only the prefix ending at a dot matters. The partial field to its right
    # changes on every key and cannot introduce new database metadata.
    prefixes = {_parts(match.group(1)) for match in _DOTTED.finditer(cleaned)}
    routines = bool(re.search(r"\b(?:EXEC|EXECUTE|CALL)\s", cleaned, re.IGNORECASE))
    return tuple(sorted(references)), tuple(sorted(prefixes)), routines


def changes_metadata(code):
    return bool(re.search(r"\b(?:CREATE|ALTER|DROP|RENAME)\s+(?:(?:OR\s+REPLACE|TEMP|TEMPORARY)\s+)?(?:TABLE|VIEW|SCHEMA|DATABASE|CATALOG|FUNCTION|PROCEDURE|INDEX)\b", _NOISE.sub(" ", code or ""), re.IGNORECASE))
