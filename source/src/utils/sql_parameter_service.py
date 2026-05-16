"""SQL custom parameter parsing, validation, and DB-specific preparation."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Callable, Iterable
import re
import uuid

from src.language import S


PARAMETER_ID_PREFIX = "sqlparam:"
SQL_PARAMETER_TYPES = ("text", "integer", "decimal", "boolean", "date", "datetime", "uuid")
INPUT_KINDS = ("value", "choice", "multi_choice")
_DEFAULT_EMPTY_ALIASES = {"empty", "vazio", "''", '""'}
_DEFAULT_NULL_ALIASES = {"null", "nulo", "none"}
_DEFAULT_TODAY_ALIASES = {"today", "hoje", "current_date"}
_DEFAULT_NOW_ALIASES = {"now", "agora", "current_timestamp"}
_COMPARISON_OPERATORS = r"(?:=|<>|!=|<=|>=|<|>|LIKE|ILIKE)"
_IDENTIFIER_PATTERN = r"[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*){0,2}"
_SQL_KEYWORDS = {
    "where",
    "on",
    "group",
    "order",
    "having",
    "limit",
    "offset",
    "inner",
    "left",
    "right",
    "full",
    "cross",
    "join",
    "union",
}


@dataclass(frozen=True)
class SqlParameterToken:
    """A parameter token found in SQL text."""

    id: str
    name: str
    token: str
    start: int
    end: int
    order: int


@dataclass
class PreparedSql:
    """Prepared SQL text and bind values for a DB execution call."""

    query: str
    params: Any = field(default_factory=dict)


class SqlParameterError(ValueError):
    """Raised when SQL custom parameters cannot be prepared safely."""


def parameter_id(name: str) -> str:
    """Return a stable internal id for a visible parameter name."""
    clean_name = normalize_parameter_name(name)
    return f"{PARAMETER_ID_PREFIX}{clean_name.lower()}"


def normalize_parameter_name(name: str) -> str:
    """Normalize a user-visible parameter name, without the @ prefix."""
    value = str(name or "").strip()
    if value.startswith("@"):
        value = value[1:]
    return value


def default_parameter_definition(name: str, order: int = 0, sql_type: str = "text") -> dict[str, Any]:
    """Build a default UI/model definition for a detected parameter."""
    clean_name = normalize_parameter_name(name)
    normalized_type = str(sql_type or "text")
    if normalized_type not in SQL_PARAMETER_TYPES:
        normalized_type = "text"
    return {
        "id": parameter_id(clean_name),
        "name": clean_name,
        "label": "",
        "order": order,
        "sql_type": normalized_type,
        "input_kind": "value",
        "value": "",
        "default_value": "",
        "required": True,
        "options": [],
        "multi_select": False,
        "type_source": "default",
    }


def _scan_sql_parameters(sql: str, replacer: Callable[[str, str, int, int], str] | None = None) -> tuple[list[SqlParameterToken], str]:
    """Scan SQL text for @name parameters, optionally replacing each token."""
    text = sql or ""
    tokens: list[SqlParameterToken] = []
    seen: set[str] = set()
    output: list[str] = []
    index = 0
    length = len(text)

    def append_literal(start: int, end: int) -> None:
        if replacer is not None:
            output.append(text[start:end])

    while index < length:
        char = text[index]

        if char == "'":
            start = index
            index += 1
            while index < length:
                if text[index] == "'":
                    if index + 1 < length and text[index + 1] == "'":
                        index += 2
                        continue
                    index += 1
                    break
                index += 1
            append_literal(start, index)
            continue

        if char == '"':
            start = index
            index += 1
            while index < length:
                if text[index] == '"':
                    if index + 1 < length and text[index + 1] == '"':
                        index += 2
                        continue
                    index += 1
                    break
                index += 1
            append_literal(start, index)
            continue

        if char == "[":
            start = index
            index += 1
            while index < length:
                if text[index] == "]":
                    index += 1
                    break
                index += 1
            append_literal(start, index)
            continue

        if char == "`":
            start = index
            index += 1
            while index < length:
                if text[index] == "`":
                    index += 1
                    break
                index += 1
            append_literal(start, index)
            continue

        if char == "-" and index + 1 < length and text[index + 1] == "-":
            start = index
            newline = text.find("\n", index + 2)
            index = length if newline == -1 else newline + 1
            append_literal(start, index)
            continue

        if char == "#":
            start = index
            newline = text.find("\n", index + 1)
            index = length if newline == -1 else newline + 1
            append_literal(start, index)
            continue

        if char == "/" and index + 1 < length and text[index + 1] == "*":
            start = index
            end = text.find("*/", index + 2)
            index = length if end == -1 else end + 2
            append_literal(start, index)
            continue

        if char == "@":
            if index + 1 < length and text[index + 1] == "@":
                append_literal(index, index + 2)
                index += 2
                continue
            match = re.match(r"@([A-Za-z_][A-Za-z0-9_]*)", text[index:])
            if match:
                token_text = match.group(0)
                name = match.group(1)
                pid = parameter_id(name)
                if pid not in seen:
                    seen.add(pid)
                    tokens.append(
                        SqlParameterToken(
                            id=pid,
                            name=name,
                            token=token_text,
                            start=index,
                            end=index + len(token_text),
                            order=len(tokens),
                        )
                    )
                if replacer is not None:
                    output.append(replacer(name, token_text, index, index + len(token_text)))
                index += len(token_text)
                continue

        append_literal(index, index + 1)
        index += 1

    return tokens, "".join(output) if replacer is not None else text


def extract_sql_parameter_tokens(sql: str) -> list[SqlParameterToken]:
    """Return unique custom parameter tokens in first-seen order."""
    tokens, _ = _scan_sql_parameters(sql)
    return tokens


def extract_sql_parameter_names(sql: str) -> list[str]:
    """Return visible parameter names in first-seen order."""
    return [token.name for token in extract_sql_parameter_tokens(sql)]


def normalize_parameter_definition(definition: dict[str, Any], order: int | None = None) -> dict[str, Any]:
    """Normalize persisted/UI parameter data to the current schema."""
    name = normalize_parameter_name(definition.get("name") or definition.get("token") or definition.get("id", ""))
    if name.startswith(PARAMETER_ID_PREFIX):
        name = name[len(PARAMETER_ID_PREFIX):]
    if not name:
        name = "param"

    label = str(definition.get("label") or "").strip()

    sql_type = str(definition.get("sql_type") or "text")
    if sql_type not in SQL_PARAMETER_TYPES:
        sql_type = "text"

    input_kind = str(definition.get("input_kind") or "value")
    if input_kind not in INPUT_KINDS:
        input_kind = "value"

    options = definition.get("options") or []
    if isinstance(options, str):
        options = [item.strip() for item in options.split(",") if item.strip()]
    elif not isinstance(options, list):
        options = list(options) if isinstance(options, Iterable) else []

    value = definition.get("value", "")
    if isinstance(value, tuple):
        value = list(value)

    default_value = definition.get("default_value", "")
    if isinstance(default_value, tuple):
        default_value = list(default_value)

    type_source = str(definition.get("type_source") or "").strip().lower()
    if type_source not in {"default", "name", "schema", "manual"}:
        type_source = "manual" if str(definition.get("sql_type") or "").strip() not in {"", "text"} else "default"
    if type_source != "manual":
        inferred_name_type = _infer_type_from_name(name)
        auto_default_aliases = {""}

        raw_default_value = str(default_value or "").strip().lower() if not isinstance(default_value, (list, tuple, set)) else ""
        if type_source == "default" and sql_type != "text":
            type_source = "manual"
        elif type_source == "name" and inferred_name_type != sql_type:
            type_source = "manual"
        elif raw_default_value not in auto_default_aliases:
            type_source = "manual"

    normalized = default_parameter_definition(name, int(definition.get("order", order or 0) or 0))
    normalized.update(
        {
            "id": definition.get("id") or parameter_id(name),
            "name": name,
            "label": label,
            "order": int(definition.get("order", order if order is not None else normalized["order"]) or 0),
            "sql_type": sql_type,
            "input_kind": input_kind,
            "value": value,
            "default_value": _normalize_default_value(default_value, sql_type),
            "required": bool(definition.get("required", True)),
            "options": [str(item) for item in options],
            "multi_select": bool(definition.get("multi_select", input_kind == "multi_choice")),
            "type_source": type_source,
        }
    )
    if normalized["input_kind"] == "multi_choice":
        normalized["multi_select"] = True
    return normalized


def merge_parameter_definitions(
    sql: str,
    existing: list[dict[str, Any]] | None = None,
    sql_schema: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Merge detected SQL tokens with existing user configuration."""
    tokens = extract_sql_parameter_tokens(sql)
    existing_by_id = {
        normalize_parameter_definition(item).get("id"): normalize_parameter_definition(item)
        for item in (existing or [])
        if isinstance(item, dict)
    }
    merged: list[dict[str, Any]] = []
    for token in tokens:
        current = existing_by_id.get(token.id)
        inferred = _inferred_parameter_defaults(token, sql, sql_schema)
        if current:
            current = dict(current)
            current["name"] = token.name
            current["order"] = int(current.get("order", token.order))
            if current.get("type_source") != "manual":
                current["sql_type"] = inferred["sql_type"]
                current["default_value"] = inferred["default_value"]
                current["type_source"] = inferred["type_source"]
        else:
            current = default_parameter_definition(token.name, token.order, inferred["sql_type"])
            current["default_value"] = inferred["default_value"]
            current["type_source"] = inferred["type_source"]
        merged.append(current)

    return sorted(merged, key=lambda item: int(item.get("order", 0)))


def filter_parameters_for_query(query: str, parameters: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    """Return parameter definitions that are present in the provided SQL text."""
    token_ids = [token.id for token in extract_sql_parameter_tokens(query)]
    by_id = {normalize_parameter_definition(item)["id"]: normalize_parameter_definition(item) for item in (parameters or [])}
    filtered = []
    for order, pid in enumerate(token_ids):
        item = by_id.get(pid)
        if item:
            item = dict(item)
            item["order"] = order
            filtered.append(item)
    return filtered


def _is_empty_value(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return value.strip() == ""
    if isinstance(value, (list, tuple, set)):
        return len(value) == 0
    return False


def parameter_has_default(parameter: dict[str, Any]) -> bool:
    """Return True when a parameter has a configured default fallback."""
    normalized = normalize_parameter_definition(parameter)
    default_value = normalized.get("default_value")
    if isinstance(default_value, (list, tuple, set)):
        return len(default_value) > 0
    return str(default_value or "").strip() != ""


def resolve_parameter_default_value(parameter: dict[str, Any], for_display: bool = False) -> Any:
    """Resolve the configured default value to a runtime/display value."""
    normalized = normalize_parameter_definition(parameter)
    default_value = normalized.get("default_value")
    if isinstance(default_value, (list, tuple, set)):
        values = [item for item in default_value if not _is_empty_value(item)]
        return values if normalized.get("input_kind") == "multi_choice" else (values[0] if values else "")

    raw_value = str(default_value or "").strip()
    if not raw_value:
        return ""

    lowered = raw_value.lower()
    if lowered in _DEFAULT_EMPTY_ALIASES or lowered in _DEFAULT_NULL_ALIASES:
        return ""
    if lowered in _DEFAULT_TODAY_ALIASES:
        today = date.today()
        return today.isoformat() if for_display else today
    if lowered in _DEFAULT_NOW_ALIASES:
        current = datetime.now().replace(microsecond=0)
        return current.isoformat() if for_display else current
    if normalized.get("input_kind") == "multi_choice":
        return [item.strip() for item in raw_value.split(",") if item.strip()]
    return raw_value


def resolve_parameter_value(parameter: dict[str, Any]) -> Any:
    """Return the explicit value or the configured default fallback."""
    normalized = normalize_parameter_definition(parameter)
    explicit_value = normalized.get("value")
    if not _is_empty_value(explicit_value):
        return explicit_value
    return resolve_parameter_default_value(normalized)


def _split_list_value(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        return [item for item in value if not _is_empty_value(item)]
    return [item.strip() for item in str(value).split(",") if item.strip()]


def _convert_scalar_value(value: Any, sql_type: str) -> Any:
    if _is_empty_value(value):
        return None
    if sql_type == "integer":
        return int(str(value).strip())
    if sql_type == "decimal":
        try:
            return Decimal(str(value).strip())
        except InvalidOperation as exc:
            raise ValueError(str(exc)) from exc
    if sql_type == "boolean":
        if isinstance(value, bool):
            return value
        lowered = str(value).strip().lower()
        if lowered in {"1", "true", "yes", "y", "sim", "s"}:
            return True
        if lowered in {"0", "false", "no", "n", "nao", "não"}:
            return False
        raise ValueError(f"Invalid boolean: {value}")
    if sql_type == "date":
        if isinstance(value, date) and not isinstance(value, datetime):
            return value
        return date.fromisoformat(str(value).strip())
    if sql_type == "datetime":
        if isinstance(value, datetime):
            return value
        return datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
    if sql_type == "uuid":
        return str(uuid.UUID(str(value).strip()))
    return str(value)


def parameter_is_multi(parameter: dict[str, Any]) -> bool:
    normalized = normalize_parameter_definition(parameter)
    return normalized.get("input_kind") == "multi_choice" or bool(normalized.get("multi_select"))


def _default_value_for_sql_type(sql_type: str) -> str:
    return ""


def _normalize_default_value(value: Any, sql_type: str) -> Any:
    if isinstance(value, str):
        stripped = value.strip()
        return stripped
    if value is None:
        return ""
    return value


def _inferred_parameter_defaults(
    token: SqlParameterToken,
    sql: str,
    sql_schema: dict[str, Any] | None,
) -> dict[str, Any]:
    inferred_type, source = _infer_parameter_type(token, sql, sql_schema)
    inferred_type = inferred_type or "text"
    return {
        "sql_type": inferred_type,
        "default_value": "",
        "type_source": source or "default",
    }


def _infer_parameter_type(
    token: SqlParameterToken,
    sql: str,
    sql_schema: dict[str, Any] | None,
) -> tuple[str | None, str | None]:
    schema_type = _infer_type_from_schema(token, sql, sql_schema)
    if schema_type:
        return schema_type, "schema"

    name_type = _infer_type_from_name(token.name)
    if name_type:
        return name_type, "name"

    return None, None


def _infer_type_from_name(name: str) -> str | None:
    normalized = normalize_parameter_name(name)
    spaced = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", normalized)
    lowered = spaced.lower()
    name_parts = [part for part in re.split(r"[\s_\-]+", lowered) if part]
    if any(part in {"data", "date"} for part in name_parts):
        return "date"
    if any(part in {"valor", "value"} for part in name_parts):
        return "decimal"
    if any(part in {"name", "nome", "descricao", "description"} for part in name_parts):
        return "text"
    return None


def _infer_type_from_schema(
    token: SqlParameterToken,
    sql: str,
    sql_schema: dict[str, Any] | None,
) -> str | None:
    if not sql_schema or not isinstance(sql_schema, dict):
        return None

    column_reference = _column_reference_for_token(sql, token)
    if not column_reference:
        return None

    alias_map = _extract_table_aliases(sql)
    table_reference = ""
    column_name = column_reference
    if "." in column_reference:
        parts = column_reference.split(".")
        table_reference = ".".join(parts[:-1])
        column_name = parts[-1]

    mapped_types = _schema_types_for_column(sql_schema, alias_map, table_reference, column_name)
    if len(mapped_types) == 1:
        return next(iter(mapped_types))
    return None


def _column_reference_for_token(sql: str, token: SqlParameterToken) -> str:
    before = sql[max(0, token.start - 200):token.start]
    after = sql[token.end:min(len(sql), token.end + 200)]

    before_patterns = (
        rf"({_IDENTIFIER_PATTERN})\s*{_COMPARISON_OPERATORS}\s*$",
        rf"({_IDENTIFIER_PATTERN})\s+IN\s*\(\s*$",
        rf"({_IDENTIFIER_PATTERN})\s+BETWEEN\s*$",
    )
    for pattern in before_patterns:
        match = re.search(pattern, before, flags=re.IGNORECASE)
        if match:
            return match.group(1)

    after_patterns = (
        rf"^\s*{_COMPARISON_OPERATORS}\s*({_IDENTIFIER_PATTERN})",
        rf"^\s+AND\s+({_IDENTIFIER_PATTERN})",
    )
    for pattern in after_patterns:
        match = re.search(pattern, after, flags=re.IGNORECASE)
        if match:
            return match.group(1)

    return ""


def _extract_table_aliases(sql: str) -> dict[str, str]:
    alias_map: dict[str, str] = {}
    pattern = rf"\b(?:FROM|JOIN|UPDATE|INTO)\s+({_IDENTIFIER_PATTERN})(?:\s+(?:AS\s+)?([A-Za-z_][A-Za-z0-9_]*))?"
    for match in re.finditer(pattern, sql or "", flags=re.IGNORECASE):
        table_name = match.group(1)
        alias = (match.group(2) or "").strip()
        if alias and alias.lower() not in _SQL_KEYWORDS:
            alias_map[alias.lower()] = table_name
    return alias_map


def _schema_types_for_column(
    sql_schema: dict[str, Any],
    alias_map: dict[str, str],
    table_reference: str,
    column_name: str,
) -> set[str]:
    columns = sql_schema.get("columns") or {}
    if not isinstance(columns, dict):
        return set()

    normalized_column_name = str(column_name or "").strip().lower()
    if not normalized_column_name:
        return set()

    candidate_table_keys: set[str] = set()
    if table_reference:
        resolved_reference = alias_map.get(table_reference.lower(), table_reference)
        candidate_table_keys.update(_matching_table_keys(columns, resolved_reference))
        candidate_table_keys.update(_matching_table_keys(columns, table_reference))
    else:
        candidate_table_keys.update(columns.keys())

    mapped_types: set[str] = set()
    for table_key in candidate_table_keys:
        for column in columns.get(table_key) or []:
            if not isinstance(column, dict):
                continue
            if str(column.get("name") or "").strip().lower() != normalized_column_name:
                continue
            mapped_type = _map_column_type_to_parameter_type(column.get("type") or column.get("display_type") or "")
            if mapped_type:
                mapped_types.add(mapped_type)
    return mapped_types


def _matching_table_keys(columns: dict[str, Any], reference: str) -> set[str]:
    normalized_reference = str(reference or "").strip().lower()
    if not normalized_reference:
        return set()
    return {
        key
        for key in columns.keys()
        if str(key).strip().lower() == normalized_reference
        or str(key).strip().lower().endswith(f".{normalized_reference}")
    }


def _map_column_type_to_parameter_type(column_type: Any) -> str:
    lowered = str(column_type or "").strip().lower()
    if not lowered:
        return "text"
    if "timestamp" in lowered or "datetime" in lowered:
        return "datetime"
    if "date" in lowered:
        return "date"
    if any(token in lowered for token in ("decimal", "numeric", "money", "float", "double", "real", "number")):
        return "decimal"
    if any(token in lowered for token in ("bigint", "smallint", "tinyint", "int")):
        return "integer"
    if any(token in lowered for token in ("bool", "boolean", "bit")):
        return "boolean"
    if any(token in lowered for token in ("uuid", "uniqueidentifier")):
        return "uuid"
    return "text"


def _error_missing_value(parameter_name: str) -> str:
    return S.sql_parameters.error_missing_value.format(name=parameter_name)


def _error_invalid_option(parameter_name: str, value: str) -> str:
    return S.sql_parameters.error_invalid_option.format(name=parameter_name, value=value)


def _error_conversion(parameter_name: str, error: Exception) -> str:
    return S.sql_parameters.error_conversion.format(name=parameter_name, error=error)


def _error_multi_requires_in(parameter_name: str) -> str:
    return S.sql_parameters.error_multi_requires_in.format(name=parameter_name)


def validate_and_convert_parameters(
    query: str,
    parameters: list[dict[str, Any]] | None,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Validate parameters for a SQL query and return converted values or errors."""
    used = filter_parameters_for_query(query, parameters)
    errors: list[str] = []
    converted: list[dict[str, Any]] = []

    for item in used:
        normalized = normalize_parameter_definition(item)
        value = resolve_parameter_value(normalized)
        parameter_name = normalized["name"]

        if normalized.get("required", True) and _is_empty_value(value) and not parameter_has_default(normalized):
            errors.append(_error_missing_value(parameter_name))
            continue

        try:
            if parameter_is_multi(normalized):
                values = _split_list_value(value)
                if normalized.get("required", True) and not values and not parameter_has_default(normalized):
                    errors.append(_error_missing_value(parameter_name))
                    continue
                options = normalized.get("options") or []
                if options:
                    invalid = [str(option) for option in values if str(option) not in {str(item) for item in options}]
                    if invalid:
                        errors.append(_error_invalid_option(parameter_name, ", ".join(invalid)))
                        continue
                normalized["converted_value"] = [
                    _convert_scalar_value(value_item, normalized.get("sql_type", "text"))
                    for value_item in values
                ]
            else:
                options = normalized.get("options") or []
                if normalized.get("input_kind") == "choice" and options and str(value) not in {str(item) for item in options}:
                    errors.append(_error_invalid_option(parameter_name, str(value)))
                    continue
                normalized["converted_value"] = _convert_scalar_value(value, normalized.get("sql_type", "text"))
        except Exception as exc:
            errors.append(_error_conversion(parameter_name, exc))
            continue

        converted.append(normalized)

    return converted, errors


def _definition_map(parameters: list[dict[str, Any]] | None) -> dict[str, dict[str, Any]]:
    converted, errors = validate_and_convert_parameters(" ".join(f"@{normalize_parameter_definition(p)['name']}" for p in (parameters or [])), parameters)
    if errors:
        raise SqlParameterError("; ".join(errors))
    return {item["id"]: item for item in converted}


def _has_in_context(query: str, token_name: str) -> bool:
    return re.search(rf"\bIN\s*\(\s*@{re.escape(token_name)}\s*\)", query, flags=re.IGNORECASE) is not None


def prepare_generic_sql(query: str, parameters: list[dict[str, Any]] | None) -> PreparedSql:
    """Prepare SQLAlchemy-compatible named binds from DataPyn @parameters."""
    converted, errors = validate_and_convert_parameters(query, parameters)
    if errors:
        raise SqlParameterError("; ".join(errors))
    by_id = {item["id"]: item for item in converted}
    bind_values: dict[str, Any] = {}

    def replace(name: str, token: str, start: int, end: int) -> str:
        pid = parameter_id(name)
        parameter = by_id.get(pid)
        if not parameter:
            return token
        bind_name = normalize_parameter_name(parameter["name"])
        value = parameter.get("converted_value")
        if parameter_is_multi(parameter):
            if not _has_in_context(query, parameter["name"]):
                raise SqlParameterError(_error_multi_requires_in(parameter["name"]))
            placeholders = []
            for idx, item_value in enumerate(value or []):
                expanded_name = f"{bind_name}_{idx}"
                bind_values[expanded_name] = item_value
                placeholders.append(f":{expanded_name}")
            if not placeholders:
                raise SqlParameterError(_error_missing_value(parameter["name"]))
            return ", ".join(placeholders)
        bind_values[bind_name] = value
        return f":{bind_name}"

    _, prepared_query = _scan_sql_parameters(query, replace)
    return PreparedSql(query=prepared_query, params=bind_values)


def sqlserver_type_name(sql_type: str) -> str:
    """Map DataPyn parameter type to SQL Server declaration type."""
    return {
        "text": "NVARCHAR(MAX)",
        "integer": "INT",
        "decimal": "DECIMAL(18, 6)",
        "boolean": "BIT",
        "date": "DATE",
        "datetime": "DATETIME2",
        "uuid": "UNIQUEIDENTIFIER",
    }.get(sql_type, "NVARCHAR(MAX)")


def prepare_sqlserver_batch(batch: str, parameters: list[dict[str, Any]] | None) -> PreparedSql:
    """Prepare a SQL Server batch with DECLARE statements and pyodbc params."""
    converted, errors = validate_and_convert_parameters(batch, parameters)
    if errors:
        raise SqlParameterError("; ".join(errors))
    by_id = {item["id"]: item for item in converted}
    declarations: list[str] = []
    declaration_values: list[Any] = []
    inline_values: list[Any] = []
    declared: set[str] = set()

    def replace(name: str, token: str, start: int, end: int) -> str:
        pid = parameter_id(name)
        parameter = by_id.get(pid)
        if not parameter:
            return token
        if parameter_is_multi(parameter):
            if not _has_in_context(batch, parameter["name"]):
                raise SqlParameterError(_error_multi_requires_in(parameter["name"]))
            values = parameter.get("converted_value") or []
            if not values:
                raise SqlParameterError(_error_missing_value(parameter["name"]))
            inline_values.extend(values)
            return ", ".join("?" for _ in values)
        if pid not in declared:
            declared.add(pid)
            declarations.append(f"DECLARE @{parameter['name']} {sqlserver_type_name(parameter.get('sql_type', 'text'))} = ?;")
            declaration_values.append(parameter.get("converted_value"))
        return token

    _, prepared_batch = _scan_sql_parameters(batch, replace)
    if declarations:
        prepared_batch = "\n".join(declarations) + "\n" + prepared_batch
    return PreparedSql(query=prepared_batch, params=declaration_values + inline_values)


def prepare_databricks_sql(query: str, parameters: list[dict[str, Any]] | None) -> PreparedSql:
    """Prepare Databricks SQL using named parameters where supported."""
    return prepare_generic_sql(query, parameters)
