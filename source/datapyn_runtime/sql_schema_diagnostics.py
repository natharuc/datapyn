"""Advisory SQL name checks over parsed ASTs and cached schema snapshots."""

from collections import OrderedDict
from hashlib import sha256
import json
import threading
from types import SimpleNamespace

MAX_SCHEMA_ITEMS = 20_000
MAX_SCHEMA_CACHE_BYTES = 4 * 1024 * 1024
_INDEXES = OrderedDict()
_INDEX_BYTES = 0
_INDEX_LOCK = threading.RLock()


def _service(context, expired):
    """Content/version keys prevent stale indexes after in-place snapshot edits."""
    global _INDEX_BYTES
    from .sql_completion import RuntimeSqlAutoCompleteService
    schema = context.get("schema") or {}
    snapshot = {key: schema.get(key, "") for key in ("db_type", "database", "current_schema")}
    snapshot["tables"], snapshot["columns"] = [], {}
    count = 0
    for table in schema.get("tables") or []:
        count += 1
        if count > MAX_SCHEMA_ITEMS or count % 256 == 0 and expired():
            return None
        snapshot["tables"].append({key: table[key] for key in ("name", "key", "schema", "catalog", "database", "temporary", "type") if key in table}
                                  if isinstance(table, dict) else str(table))
    for key, columns in (schema.get("columns") or {}).items():
        selected = []
        for column in columns or []:
            count += 1
            if count > MAX_SCHEMA_ITEMS or count % 256 == 0 and expired():
                return None
            if isinstance(column, dict):
                selected.append({"name": str(column.get("name") or "")})
        snapshot["columns"][str(key)] = selected
    fingerprint = json.dumps(snapshot, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    cost = len(fingerprint)
    if cost > MAX_SCHEMA_CACHE_BYTES or expired():
        return None
    key = (context.get("version", 0), sha256(fingerprint).digest())
    with _INDEX_LOCK:
        if key in _INDEXES:
            _INDEXES.move_to_end(key)
            return _INDEXES[key][1]
        service = RuntimeSqlAutoCompleteService()
        service.set_schema(snapshot)
        _INDEXES[key] = (cost, service)
        _INDEX_BYTES += cost
        while len(_INDEXES) > 4 or _INDEX_BYTES > MAX_SCHEMA_CACHE_BYTES:
            _, (old_cost, _) = _INDEXES.popitem(last=False)
            _INDEX_BYTES -= old_cost
        return service


class SchemaWarnings:
    def __init__(self, context, document, locale, expired, maximum):
        self.enabled = bool(context.get("schema_complete") and context.get("schema"))
        self.service = _service(context, expired) if self.enabled else None
        self.partial = self.enabled and self.service is None
        self.document, self.locale, self.expired, self.maximum = document, locale, expired, maximum
        self.state = {"relation_sources": [], "relation_lookup": {}, "variables": {}}
        self.seen = set()
        self.markers = []

    def _warning(self, node, offset, english, portuguese, *, identifier=None):
        if len(self.markers) >= self.maximum:
            self.partial = True
            return
        identifier = identifier if identifier is not None else getattr(node, "this", None)
        metadata = getattr(identifier, "meta", None) or getattr(node, "meta", None) or {}
        if "start" not in metadata:
            return
        start, end = offset + int(metadata["start"]), offset + int(metadata.get("end", metadata["start"])) + 1
        message = portuguese if self.locale == "pt-BR" else english
        key = (start, end, message)
        if key not in self.seen:
            self.seen.add(key)
            self.markers.append(self.document.marker(start, end, message, "warning"))

    def _entry(self, table):
        service = self.service
        if service._schema_db_type in {"postgres", "postgresql"}:
            table = table.copy()
            for name in ("this", "db", "catalog"):
                identifier = table.args.get(name)
                if identifier is not None and isinstance(identifier.this, str) and not identifier.args.get("quoted"):
                    identifier.set("this", identifier.this.lower())
        return service._find_schema_entry(table.name, table.db, table.catalog)

    def _physical_loaded(self, table):
        service = self.service
        names = service._relation_lookup_names(service._table_identifier_from_expression(table))
        if any(name in self.state["relation_lookup"] for name in names):
            return True
        entry = self._entry(table)
        if entry is None:
            return False
        return any(key in service._schema["columns"] for key in (entry["key"], entry["detail"], entry["name"]))

    def add(self, expressions, offset):
        if self.service is None:
            return
        from sqlglot import exp
        from sqlglot.optimizer.scope import Scope, traverse_scope
        service = self.service
        for expression in expressions:
            if expression is None:
                continue
            if self.expired():
                self.partial = True
                return
            # Reuse the same script-state registrations as autocomplete, over
            # these already-parsed statements. No growing previous-SQL parse.
            if isinstance(expression, exp.Create):
                service._register_create_relation(expression, self.state)
                continue
            if isinstance(expression, exp.Declare):
                service._register_declared_symbols(expression, self.state)
                continue
            if isinstance(expression, exp.Select) and expression.args.get("into"):
                service._register_select_into_relation(expression, self.state)
            output_cache, relation_cache, loaded_cache = {}, {}, {}
            scopes = list(traverse_scope(expression))
            # sqlglot's query-scope walker excludes simple UPDATE/DELETE/INSERT
            # ASTs. Reuse their physical sources without reparsing; complex DML
            # containing subqueries remains conservative.
            if not scopes and isinstance(expression, (exp.Update, exp.Delete, exp.Insert)) and not next(expression.find_all(exp.Select), None):
                selected_sources = {table.alias_or_name: (table, table) for table in expression.find_all(exp.Table)}
                scopes = [SimpleNamespace(expression=expression, selected_sources=selected_sources,
                                          columns=list(expression.find_all(exp.Column)), parent=None)]

            def relations(scope):
                if id(scope) not in relation_cache:
                    relation_cache[id(scope)] = service._resolve_scope_sources(scope, self.state, output_cache)
                return relation_cache[id(scope)]

            def loaded(source):
                if isinstance(source, exp.Table):
                    return self._physical_loaded(source)
                if isinstance(source, Scope):
                    if id(source) not in loaded_cache:
                        loaded_cache[id(source)] = False  # Recursive CTEs are conservative.
                        loaded_cache[id(source)] = all(loaded(selected[1]) for selected in source.selected_sources.values())
                    return loaded_cache[id(source)]
                return False

            for scope in scopes:
                if self.expired():
                    self.partial = True
                    return
                sources, lookup = relations(scope)
                selected = scope.selected_sources
                for _, (_, source) in selected.items():
                    if not isinstance(source, exp.Table):
                        continue
                    table_name = service._table_identifier_from_expression(source)
                    if not table_name or isinstance(source.this, exp.Parameter):
                        continue
                    if self._entry(source) is not None or any(name in self.state["relation_lookup"] for name in service._relation_lookup_names(table_name)):
                        continue
                    # A snapshot from the active database cannot prove that an
                    # object in a different catalog is absent.
                    if source.catalog and source.catalog != service._schema.get("database"):
                        continue
                    self._warning(source, offset, f"Unknown table '{table_name}'",
                                  f"Tabela não encontrada nos metadados carregados: {table_name}")
                for column in scope.columns:
                    if not column.name or column.name == "*":
                        continue
                    qualifier, relation, found_scope = column.table, None, scope
                    while found_scope is not None:
                        scope_relations, scope_lookup = relations(found_scope)
                        relation = scope_lookup.get(service._normalize_relation_key(qualifier)) if qualifier else None
                        if relation is not None or not qualifier:
                            break
                        # Known-but-unloaded sources must not become alias errors.
                        if qualifier in found_scope.selected_sources:
                            break
                        found_scope = found_scope.parent
                    if qualifier and relation is None:
                        ancestor = scope
                        known_alias = False
                        while ancestor is not None:
                            known_alias |= qualifier in ancestor.selected_sources
                            ancestor = ancestor.parent
                        if not known_alias:
                            self._warning(column, offset, f"Unknown table or alias '{qualifier}'",
                                          f"Tabela ou alias não encontrado neste escopo: {qualifier}",
                                          identifier=column.args.get("table"))
                        continue
                    target_scope = found_scope or scope
                    if qualifier:
                        candidates = [(alias, source) for alias, (_, source) in target_scope.selected_sources.items()
                                      if service._normalize_relation_key(alias) in relation.get("lookup_names", set())]
                        if not candidates or not all(loaded(source) for _, source in candidates):
                            continue
                        active_relations = [relation]
                    else:
                        if not selected or not all(loaded(source) for _, source in selected.values()):
                            continue
                        active_relations = sources
                    if service._find_column_definition(active_relations, qualifier, column.name) is None:
                        name = f"{qualifier}.{column.name}" if qualifier else column.name
                        self._warning(column, offset, f"Unknown column '{name}'",
                                      f"Coluna não encontrada nos metadados carregados: {name}")
