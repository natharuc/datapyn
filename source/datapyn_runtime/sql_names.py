"""Quoted qualified names from user input, without splitting literal dots."""


def parts(value):
    if not isinstance(value, str) or not value.strip() or "\0" in value:
        raise ValueError("Choose a valid SQL object name")
    result, position = [], 0
    while position < len(value):
        while position < len(value) and value[position].isspace():
            position += 1
        if position == len(value):
            raise ValueError("SQL object names cannot contain empty parts")
        if value[position] in '["`':
            closing = ']' if value[position] == '[' else value[position]
            position += 1
            name = []
            while position < len(value):
                character = value[position]
                position += 1
                if character == closing:
                    if position < len(value) and value[position] == closing:
                        name.append(character)
                        position += 1
                    else:
                        break
                else:
                    name.append(character)
            else:
                raise ValueError("Unclosed SQL identifier quote")
            name = "".join(name)
            while position < len(value) and value[position].isspace():
                position += 1
            if position < len(value) and value[position] != '.':
                raise ValueError("Unexpected text after a quoted SQL identifier")
        else:
            end = value.find('.', position)
            if end < 0:
                end = len(value)
            name = value[position:end].strip()
            position = end
        if not name:
            raise ValueError("SQL object names cannot contain empty parts")
        result.append(name)
        if position < len(value):
            position += 1
            if position == len(value):
                raise ValueError("SQL object names cannot end with a dot")
    if len(result) > 3:
        raise ValueError("Use a table, schema.table or catalog.schema.table name")
    return result


def table_parts(table, schema=None, literal=False, schema_literal=False):
    if literal:
        if not isinstance(table, str) or not table.strip() or "\0" in table:
            raise ValueError("Choose a valid table name")
        names = [table.strip()]
    else:
        names = parts(table)
    if schema:
        schema_parts = [schema] if schema_literal else parts(schema)
        if len(names) > 1:
            if names[:-1] != schema_parts:
                raise ValueError("The schema field conflicts with the qualified table name")
        else:
            names = schema_parts + names
    return names
