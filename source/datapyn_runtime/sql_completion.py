"""Runtime SQL adapter preserving physical identifier spelling."""

from src.services.sql_autocomplete_service import DEFAULT_SCHEMA_PRIORITY, SqlAutoCompleteService


class RuntimeSqlAutoCompleteService(SqlAutoCompleteService):
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
        def rank(entry):
            catalog = self._normalize_name(entry["catalog"])
            schema = self._normalize_name(entry["schema"])
            catalog_rank = 0 if catalog_name and catalog == self._normalize_name(catalog_name) else 1 if current_catalog and catalog == current_catalog else 2 if not catalog else 3
            schema_rank = 0 if schema_name and schema == self._normalize_name(schema_name) else 1 if self._schema_db_type == "databricks" and current_schema and schema == current_schema else 2 if schema in DEFAULT_SCHEMA_PRIORITY else 3 if not schema else 4
            return catalog_rank, schema_rank, DEFAULT_SCHEMA_PRIORITY.index(schema) if schema in DEFAULT_SCHEMA_PRIORITY else 0, entry["detail"]
        return min(exact, key=rank)
