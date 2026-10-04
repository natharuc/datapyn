"""Make standalone SQL files executable with the same validated parameters."""

from bisect import bisect_right
import re


def _protected_ranges(code, dialect):
    ranges, position = [], 0
    while position < len(code):
        start = position
        char = code[position]
        if char in "'\"`[":
            close = "]" if char == "[" else char
            position += 1
            while position < len(code):
                if code[position] == "\\" and dialect in {"mysql", "mariadb", "databricks"}:
                    position += 2
                elif code[position] == close:
                    position += 1
                    if position < len(code) and code[position] == close:
                        position += 1
                    else:
                        break
                else:
                    position += 1
        elif code.startswith("--", position) or char == "#" and dialect in {"mysql", "mariadb"}:
            newline = code.find("\n", position)
            position = len(code) if newline < 0 else newline + 1
        elif code.startswith("/*", position):
            position, depth = position + 2, 1
            while position < len(code) and depth:
                if code.startswith("/*", position):
                    depth += 1
                    position += 2
                elif code.startswith("*/", position):
                    depth -= 1
                    position += 2
                else:
                    position += 1
        elif char == "$" and dialect in {"postgres", "postgresql"} and (match := re.match(r"\$(?:[A-Za-z_]\w*)?\$", code[position:])):
            marker = match.group()
            end = code.find(marker, position + len(marker))
            position = len(code) if end < 0 else end + len(marker)
        else:
            position += 1
            continue
        ranges.append((start, position))
    return ranges


def literal_sql(code, parameters, dialect):
    if not parameters:
        return code
    from src.utils.sql_parameter_service import (prepare_generic_sql, validate_and_convert_parameters,
                                                parameter_id, shared_parameter_id,
                                                _scan_sql_parameters, _scan_shared_parameters)
    from .sql_export import value_literal
    # Reuse validation of multi-value IN contexts and required parameter values.
    prepare_generic_sql(code, parameters)
    converted, errors = validate_and_convert_parameters(code, parameters)
    if errors:
        raise ValueError("; ".join(errors))
    by_id = {parameter["id"]: parameter for parameter in converted}
    def replace(name, token, start, end, shared=False):
        parameter = by_id.get(shared_parameter_id(name) if shared else parameter_id(name))
        if parameter is None:
            return token
        value = parameter.get("converted_value")
        return ", ".join(value_literal(item, dialect) for item in value) if isinstance(value, list) else value_literal(value, dialect)
    _, prepared = _scan_sql_parameters(code, replace)
    ranges = _protected_ranges(prepared, dialect)
    starts = [start for start, _end in ranges]
    def shared(name, token, start, end):
        index = bisect_right(starts, start) - 1
        if index >= 0 and start < ranges[index][1]:
            return token
        return replace(name, token, start, end, shared=True)
    _, prepared = _scan_shared_parameters(prepared, shared)
    return prepared
