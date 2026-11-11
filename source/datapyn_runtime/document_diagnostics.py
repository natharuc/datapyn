"""Bounded offline validation for document SQL dialects, without fake T-SQL."""

import re


def validate(code, document, params, context, expired):
    from sqlglot import Dialect
    from sqlglot.errors import TokenError
    from .mongo_sql import MAX_QUERY_BYTES, UnsupportedMongoSql, compile_query
    from .sql_context import sql_code_mask

    locale = params.get("locale")
    schema = context.get("schema") or {}
    capabilities = context.get("capabilities") or schema.get("capabilities") or {}
    db_type = str(params.get("db_type") or schema.get("db_type") or "").lower()
    dialect = capabilities.get("sql_dialect") or db_type
    if db_type == "cosmosdb" and schema.get("cosmos_api") == "mongodb":
        dialect = "mongodb"
    if dialect == "mongodb":
        if len(code.encode("utf-8")) > MAX_QUERY_BYTES or expired():
            return [], True, "MongoDB SQL: validation limited to 128 KiB."
        mask = sql_code_mask(code, "")
        # Diagnostics validate syntax, not the current input values of binds.
        names = re.findall(r"(?<![\w:@]):([A-Za-z_]\w*)|(?<![\w@])@([A-Za-z_]\w*)", mask)
        bindings = {first or second: 1 for first, second in names}
        try:
            compile_query(code, bindings, database=str(schema.get("database") or ""))
        except UnsupportedMongoSql as error:
            details = getattr(error.__cause__, "errors", None)
            start, end = 0, min(len(code), max(1, len(code.split("\n", 1)[0])))
            if details:
                detail = details[0]
                end = document.offset(detail.get("line"), int(detail.get("col") or 1) + 1)
                start = max(0, end - len(detail.get("highlight") or ""))
            message = str(error) if locale == "pt-BR" else (
                "MongoDB SQL: invalid or unsupported query. Use SELECT fields, WHERE, ORDER BY and LIMIT/OFFSET.")
            return [document.marker(start, end, message)], False, None
        return [], False, None

    # Cosmos SQL includes SELECT VALUE, JSON objects, array joins and property
    # access that generic SQL parsers cannot faithfully validate. Check lexical
    # structure only; the service remains authoritative for its native dialect.
    message = ("Validação local parcial do dialeto Cosmos DB." if locale == "pt-BR"
               else "Partial local validation of the Cosmos DB dialect.")
    if len(code) > 256 * 1024 or expired():
        return [], True, message
    try:
        tokens = Dialect.get_or_raise("").tokenize(code)
    except TokenError:
        text = "SQL: string, comentário ou identificador não fechado." if locale == "pt-BR" else "SQL: unclosed string, comment or identifier."
        return [document.marker(0, 1, text)], False, None
    if len(tokens) > 30_000:
        return [], True, message
    opening = {"L_PAREN": "R_PAREN", "L_BRACKET": "R_BRACKET", "L_BRACE": "R_BRACE"}
    closing = set(opening.values())
    stack = []
    for token in tokens:
        if expired():
            return [], True, message
        name = token.token_type.name
        if name in opening:
            stack.append((opening[name], token))
            if len(stack) > 100:
                return [], True, message
        elif name in closing:
            if not stack or stack[-1][0] != name:
                text = "SQL: fechamento inesperado." if locale == "pt-BR" else "SQL: unexpected closing delimiter."
                return [document.marker(token.start, token.end + 1, text)], False, None
            stack.pop()
    if stack:
        token = stack[-1][1]
        text = "SQL: delimitador não fechado." if locale == "pt-BR" else "SQL: unclosed delimiter."
        return [document.marker(token.start, token.end + 1, text)], False, None
    return [], True, message
