"""Runtime SQL adapter preserving physical identifier spelling."""

import re

from src.services.sql_autocomplete_service import (
    CTX_DOT, CURSOR_PLACEHOLDER, DEFAULT_SCHEMA_PRIORITY, SqlAutoCompleteService, StatementContext,
)

from .sql_context import lexical_spans, sql_code_mask, sql_cursor_blocked, sql_statement_boundaries

_NAME = r'(?:\[(?:\]\]|[^\]])+\]|`(?:``|[^`])+`|"(?:""|[^"])+"|[@#\w$]+)'
_TAIL = r'(?:\[(?:\]\]|[^\]])*|`(?:``|[^`])*|"(?:""|[^"])*|[@#\w$]*)'
_DOT = re.compile(r'(?<![\w$#])(' + _NAME + r'(?:\s*\.\s*' + _NAME + r')*)\s*\.\s*(' + _TAIL + r')$', re.UNICODE)


class RuntimeSqlAutoCompleteService(SqlAutoCompleteService):
    @classmethod
    def _split_identifier_parts(cls, value):
        text, parts, current = str(value or "").strip(), [], []
        index, closing = 0, ""
        while index < len(text):
            char = text[index]
            if closing:
                if char == closing:
                    if index + 1 < len(text) and text[index + 1] == closing:
                        current.append(closing)
                        index += 2
                        continue
                    closing = ""
                else:
                    current.append(char)
            elif char in {'[', '`', '"'} and not current:
                closing = "]" if char == "[" else char
            elif char == ".":
                if current:
                    parts.append("".join(current).strip())
                current = []
            else:
                current.append(char)
            index += 1
        if current:
            parts.append("".join(current).strip())
        return parts

    def _dot_completions(self, prefix, analysis):
        # A query alias wins over a schema/catalog with the same spelling.
        relation = analysis.get("scope_lookup", {}).get(self._normalize_relation_key(prefix))
        if self._schema_db_type in {"postgres", "postgresql"}:
            parts = re.findall(_NAME, prefix)
            qualifier = ".".join(self._split_identifier_parts(part)[0] if part.startswith('"') else part.lower() for part in parts)
            sources = analysis.get("scope_sources", [])
            exact = [source for source in sources if source.get("preferred_qualifier") == qualifier]
            if exact:
                relation = exact[-1]
            elif any(str(source.get("preferred_qualifier", "")).lower() == qualifier.lower() for source in sources):
                return []
        if relation is not None:
            return [(str(column["name"]), "column", str(column.get("display_type") or column.get("type") or relation.get("detail", "")))
                    for column in relation.get("columns", []) if column.get("name")]
        return super()._dot_completions(prefix, analysis)

    def _append_relation(self, relations, lookup, relation):
        if self._schema_db_type not in {"postgres", "postgresql"}:
            return super()._append_relation(relations, lookup, relation)
        if not any((existing.get("display_name"), existing.get("preferred_qualifier"), existing.get("source_type")) ==
                   (relation.get("display_name"), relation.get("preferred_qualifier"), relation.get("source_type")) for existing in relations):
            relations.append(relation)
        for name in relation.get("lookup_names", set()):
            lookup[name] = relation

    def _relation_from_source(self, alias, source_expression, source_object, script_state, output_cache, cte_names, cte_alias_columns):
        table_alias = source_expression.args.get("alias")
        identifier = table_alias.args.get("this") if table_alias is not None else None
        if self._schema_db_type in {"postgres", "postgresql"} and identifier is not None and not identifier.args.get("quoted"):
            alias = str(alias).lower()
        return super()._relation_from_source(alias, source_expression, source_object, script_state, output_cache, cte_names, cte_alias_columns)

    def completion_prefix(self, before):
        match = _DOT.search(self._strip_noise(before))
        tail = match.group(2) if match else None
        if tail is None:
            spans = list(lexical_spans(before, self._schema_db_type))
            if spans and spans[-1][1] == len(before) and spans[-1][2] == "identifier":
                tail = before[spans[-1][0]:]
            else:
                word = re.search(r"[\w@$#]+$", before)
                return word.group() if word else ""
        if tail[:1] in {'[', '`', '"'}:
            closing = "]" if tail[0] == "[" else tail[0]
            value = tail[1:]
            if value.endswith(closing) and not value.endswith(closing * 2):
                value = value[:-1]
            return value.replace(closing * 2, closing)
        return tail

    def get_completions(self, text, cursor_line, cursor_col):
        before = self._text_before_cursor(text, cursor_line, cursor_col)
        if sql_cursor_blocked(text, len(before), self._schema_db_type):
            return []
        return super().get_completions(text, cursor_line, cursor_col)

    def _strip_noise(self, text):
        return sql_code_mask(text, self._schema_db_type)

    def _statement_context(self, text, line, col):
        offset = len(self._text_before_cursor(text, line, col))
        start, end = 0, len(text)
        for left, right in sql_statement_boundaries(text, self._schema_db_type):
            if right <= offset:
                start = right
            elif left >= offset:
                end = left
                break
        return StatementContext(previous_sql=text[:start], statement_before_cursor=text[start:offset], statement_after_cursor=text[offset:end])

    def _split_sql_statements(self, sql):
        parts, start = [], 0
        for left, right in sql_statement_boundaries(sql, self._schema_db_type):
            parts.append(sql[start:left].strip())
            start = right
        parts.append(sql[start:].strip())
        return [part for part in parts if part]

    def _detect_context(self, cleaned_text):
        match = _DOT.search(cleaned_text.rstrip())
        if match:
            return CTX_DOT, match.group(1)
        return super()._detect_context(cleaned_text)

    def _inject_cursor_placeholder(self, statement_sql, cursor_offset, context):
        if context != CTX_DOT:
            return super()._inject_cursor_placeholder(statement_sql, cursor_offset, context)
        before, after = statement_sql[:cursor_offset], statement_sql[cursor_offset:]
        match = _DOT.search(self._strip_noise(before).rstrip())
        if match is None:
            return super()._inject_cursor_placeholder(statement_sql, cursor_offset, context)
        tail = match.group(2)
        if tail[:1] in {'[', '`', '"'}:
            closing = "]" if tail[0] == "[" else tail[0]
            # The placeholder replaces the user's entire partial identifier,
            # including a closing quote still to the right of the cursor.
            suffix = re.match(r'(?:' + re.escape(closing * 2) + r'|[^' + re.escape(closing) + r'])*' + re.escape(closing), after)
            if suffix and re.search(r"\s(?:FROM|JOIN|WHERE|GROUP|ORDER|HAVING|UNION)\b", suffix.group(), re.IGNORECASE):
                suffix = None
        else:
            suffix = re.match(r"[\w@$#]*", after)
        remainder = after[suffix.end():] if suffix else after
        return statement_sql[:match.start()] + match.group(1) + "." + CURSOR_PLACEHOLDER + remainder

    def _rebuild_schema_index(self):
        super()._rebuild_schema_index()
        temporary = {table.get("key", table.get("name")): table for table in self._schema.get("tables", [])
                     if isinstance(table, dict) and table.get("temporary")}
        if not temporary:
            return
        self._table_lookup = {}
        for entry in self._table_entries:
            metadata = temporary.get(entry["key"])
            if metadata:
                entry.update({"temporary": True, "schema": metadata.get("schema", ""), "catalog": ""})
                entry["detail"] = ".".join(part for part in (entry["schema"], entry["name"]) if part)
                entry["lookup_names"] = {self._normalize_relation_key(entry["name"]), self._normalize_relation_key(entry["key"])}
            for lookup in entry["lookup_names"]:
                self._table_lookup.setdefault(lookup, []).append(entry)

    def _relation_from_table_expression(self, table_expression, alias_name, script_state):
        if self._schema_db_type in {"postgres", "postgresql"}:
            # PostgreSQL folds unquoted identifiers. sqlglot keeps both their
            # original spelling and the quoted flag; never fold a quoted name.
            table_expression = table_expression.copy()
            for field in ("this", "db", "catalog"):
                identifier = table_expression.args.get(field)
                if identifier is not None and isinstance(identifier.args.get("this"), str) and not identifier.args.get("quoted"):
                    identifier.set("this", identifier.this.lower())
        return super()._relation_from_table_expression(table_expression, alias_name, script_state)

    def _find_schema_entry(self, table_name, schema_name="", catalog_name=""):
        keys = [table_name]
        if schema_name:
            keys.insert(0, f"{schema_name}.{table_name}")
        if catalog_name and schema_name:
            keys.insert(0, f"{catalog_name}.{schema_name}.{table_name}")
        if catalog_name and not schema_name:
            keys[:0] = [f"{catalog_name}..{table_name}", f"{catalog_name}.{table_name}"]
        candidates = []
        seen = set()
        for key in keys:
            for entry in self._table_lookup.get(self._normalize_relation_key(key), []):
                if id(entry) not in seen:
                    seen.add(id(entry))
                    candidates.append(entry)
        if not candidates:
            return None
        exact = [entry for entry in candidates
                 if table_name in {entry["name"], entry["detail"], entry["key"]}
                 and (not schema_name or schema_name == entry["schema"])
                 and (not catalog_name or catalog_name == entry["catalog"])]
        if not exact:
            if self._schema_db_type in {"postgres", "postgresql"}:
                return None
            fallback = super()._find_schema_entry(table_name, schema_name, catalog_name)
            if fallback is None:
                return None
            # A folded fallback is safe only when it identifies one physical
            # table within the same schema/catalog selected by the legacy rules.
            same_scope = [entry for entry in candidates
                          if self._normalize_name(entry["schema"]) == self._normalize_name(fallback["schema"])
                          and self._normalize_name(entry["catalog"]) == self._normalize_name(fallback["catalog"])]
            return fallback if len(same_scope) == 1 else None
        if not schema_name and not catalog_name:
            temporary = [entry for entry in exact if entry.get("temporary")]
            if temporary:
                return temporary[0] if len(temporary) == 1 else None
        current_catalog = self._normalize_name(self._schema.get("database", ""))
        current_schema = self._normalize_name(self._schema.get("current_schema", ""))
        literal_current_schema = str(self._schema.get("current_schema", ""))
        def rank(entry):
            catalog = self._normalize_name(entry["catalog"])
            schema = self._normalize_name(entry["schema"])
            catalog_rank = 0 if catalog_name and catalog == self._normalize_name(catalog_name) else 1 if current_catalog and catalog == current_catalog else 2 if not catalog else 3
            selected_schema = entry["schema"] == literal_current_schema if self._schema_db_type in {"postgres", "postgresql"} else schema == current_schema
            schema_rank = 0 if schema_name and schema == self._normalize_name(schema_name) else 1 if current_schema and selected_schema else 2 if schema in DEFAULT_SCHEMA_PRIORITY else 3 if not schema else 4
            return catalog_rank, schema_rank, DEFAULT_SCHEMA_PRIORITY.index(schema) if schema in DEFAULT_SCHEMA_PRIORITY else 0, entry["detail"]
        return min(exact, key=rank)
