"""Native SQL endpoints: read-only validation and bound parameter envelopes."""

from .sql_context import sql_statements


def read_query(query, parameters=None, *, provider):
    if not isinstance(query, str) or not query.strip() or len(query.encode("utf-8")) > 1024 * 1024:
        raise ValueError("Enter a SELECT query of at most 1 MiB")
    statements = sql_statements(query, "")
    if len(statements) != 1:
        raise ValueError("Run one SELECT query at a time for this database")
    from .sql_context import sql_code_mask
    masked = sql_code_mask(query, "", identifiers=True).lstrip()
    if not masked.upper().startswith("SELECT") or len(masked) > 6 and (masked[6].isalnum() or masked[6] == "_"):
        raise ValueError("This connection accepts read-only SELECT queries")
    if not parameters:
        return query, []
    from src.utils.sql_parameter_service import prepare_generic_sql
    if isinstance(parameters, list):
        prepared = prepare_generic_sql(query, parameters)
        query, values = prepared.query, prepared.params
    elif isinstance(parameters, dict):
        values = parameters
    else:
        raise ValueError("Query parameters must be definitions or a dictionary")
    # Match named binds only in executable SQL, never in strings/comments.
    import re
    mask = sql_code_mask(query, "", identifiers=True)
    replacements, output = [], []
    for match in re.finditer(r"(?<![\w:@]):([A-Za-z_]\w*)|(?<![\w@])@([A-Za-z_]\w*)", mask):
        name = match.group(1) or match.group(2)
        if name not in values:
            raise ValueError(f"Missing parameter: {name}")
        if provider == "elasticsearch":
            replacements.append((match.start(), match.end(), "?"))
            output.append(values[name])
        else:
            replacements.append((match.start(), match.end(), "@" + name))
            if not any(item["name"] == "@" + name for item in output):
                output.append({"name": "@" + name, "value": values[name]})
    for start, end, token in reversed(replacements):
        query = query[:start] + token + query[end:]
    return query, output
