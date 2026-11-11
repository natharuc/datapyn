"""Lazy document metadata, sharing the desktop's existing explorer protocol."""

from collections import OrderedDict
from copy import deepcopy
import json
import time
from itertools import islice

from .database_capabilities import capabilities_for


class DocumentExplorer:
    def __init__(self, connector):
        self.connector = connector
        self.cache = OrderedDict()
        self.column_cache = OrderedDict()

    @property
    def db_type(self):
        return self.connector.db_type

    @property
    def cosmos_nosql(self):
        return self.db_type == "cosmosdb" and self.connector.config.get("cosmos_api") != "mongodb"

    def context(self):
        config = self.connector.connection_params
        result = {"db_type": self.db_type, "database": str(config.get("database") or ""), "schema": ""}
        if self.cosmos_nosql:
            result["container"] = str(config.get("container") or "")
        return result

    def _cached(self, key, loader, refresh=False):
        current = self.cache.get(key)
        if not refresh and current is not None and time.monotonic() - current[0] < 60:
            self.cache.move_to_end(key)
            return deepcopy(current[1])
        result = loader()
        self.cache[key] = time.monotonic(), result
        while len(self.cache) > 256:
            self.cache.popitem(last=False)
        return deepcopy(result)

    def _node(self, name, kind, *, database="", children=False, **fields):
        return {"id": json.dumps([database, kind, name], separators=(",", ":")), "name": name,
                "kind": kind, "has_children": children, "database": database, "schema": "",
                "qualified_name": name, **fields}

    def databases(self):
        if self.db_type == "elasticsearch":
            return []
        try:
            return list(islice(self.connector.databases(), 1000))
        except Exception:
            # A user can query their configured database without account-wide
            # listing privileges. Do not invent accessible peers.
            database = self.context()["database"]
            if database:
                return [database]
            raise

    def _collections(self, database):
        return list(islice(self.connector.indices() if self.db_type == "elasticsearch" else self.connector.collections(database), 5000))

    def columns(self, name, database="", *, refresh=False):
        def load():
            if self.db_type == "elasticsearch":
                return self.connector.fields(name)
            documents = self.connector.sample(database or self.context()["database"], name)
            fields = {}
            def walk(item, prefix="", depth=0):
                if depth > 8 or len(fields) >= 1000 or not isinstance(item, dict):
                    return
                for key, value in item.items():
                    if len(fields) >= 1000:
                        return
                    path = prefix + str(key)
                    kind = "null" if value is None else type(value).__name__
                    if path in fields and fields[path]["dtype"] != kind:
                        fields[path]["dtype"] = "mixed"
                    else:
                        fields.setdefault(path, {"name": path, "dtype": kind, "nullable": True,
                                                 "inferred": True, "partial": True})
                    if isinstance(value, dict):
                        walk(value, path + ".", depth + 1)
            deadline = time.monotonic() + 5
            try:
                for document in islice(documents, 100):
                    walk(document)
                    if len(fields) >= 1000 or time.monotonic() >= deadline:
                        break
            finally:
                close = getattr(documents, "close", None)
                if callable(close):
                    close()
            return list(fields.values())
        return self._cached(("columns", database, name), load, refresh)

    def list(self, params):
        node = params.get("node") or {}
        kind = node.get("kind", "root")
        database = str(node.get("database") or params.get("database") or self.context()["database"])
        refresh = bool(params.get("refresh"))
        if kind == "root" and self.db_type != "elasticsearch":
            nodes = [self._node(name, "database", database=name, children=True)
                     for name in self._cached(("databases",), self.databases, refresh)]
        elif kind in {"root", "database"}:
            if kind == "database":
                database = str(node.get("name") or database)
            names = self._cached(("collections", database), lambda: self._collections(database), refresh)
            nodes = [self._node(name, "table", database=database, children=True,
                                object_type="index" if self.db_type == "elasticsearch" else "container" if self.cosmos_nosql else "collection") for name in names]
        elif kind in {"table", "collection", "container", "index"}:
            names = self.columns(str(node.get("name", "")), database, refresh=refresh)
            nodes = [self._node(column["name"], "column", database=database,
                                **{key: value for key, value in column.items() if key != "name"}) for column in names]
        else:
            nodes = []
        return {"nodes": nodes, "context": self.context()}

    def details(self, params):
        name = params.get("name")
        if not isinstance(name, str) or not name:
            raise ValueError("Choose an index, container or collection")
        database = str(params.get("database") or self.context()["database"])
        return {"name": name, "kind": "table", "db_type": self.db_type, "database": database, "schema": "",
                "columns": self.columns(name, database, refresh=bool(params.get("refresh"))),
                "indexes": [], "definition": "", "metadata_partial": True}

    def query(self, params):
        name = params.get("name")
        if not isinstance(name, str) or not name:
            raise ValueError("Choose an index, container or collection")
        limit = params.get("limit", 1000)
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 100000:
            raise ValueError("limit must be between 1 and 100000")
        if params.get("mode", "select") != "select":
            raise ValueError("Only SELECT templates are available for this connection")
        database = str(params.get("database") or self.context()["database"])
        if self.cosmos_nosql:
            return {"code": f"SELECT TOP {limit} * FROM c", "language": "sql", "database": database, "container": name}
        quoted = '"' + name.replace('"', '""') + '"'
        if self.db_type != "elasticsearch" and database and database != self.context()["database"]:
            quoted = '"' + database.replace('"', '""') + '".' + quoted
        return {"code": f"SELECT * FROM {quoted} LIMIT {limit}", "language": "sql", "database": database}

    def completion_schema(self, code=""):
        context = self.context()
        database = context["database"]
        names = self._cached(("collections", database), lambda: self._collections(database)) if database or self.db_type == "elasticsearch" else []
        tables, columns = [], {}
        from .sql_context import _RELATION, _PART, sql_code_mask
        masked = sql_code_mask((code or "")[:128 * 1024], self.db_type)
        references = []
        for match in islice(_RELATION.finditer(masked), 4):
            parts = []
            for part in _PART.findall(match.group(1)):
                parts.append(part[1:-1].replace(part[-1] * 2, part[-1]) if part[0] in '["`' else part)
            references.append(tuple(parts))
        referenced_names = {path[-1] for path in references if len(path) == 1 or len(path) == 2 and path[0] == database}
        for name in names:
            tables.append({"name": name, "schema": "", "catalog": "", "key": name, "type": "TABLE", "database": database})
            # Column discovery is limited to referenced relations or the chosen
            # Cosmos container. Typing always works on an immutable snapshot.
            referenced = name in referenced_names
            selected = self.cosmos_nosql and name == context.get("container")
            if referenced or selected:
                columns[name] = self.columns(name, database)
        if not self.cosmos_nosql and self.db_type != "elasticsearch":
            for path in dict.fromkeys(references):
                if len(path) != 2:
                    continue
                target_database, name = path
                key = target_database + "." + name
                tables.append({"name": name, "schema": target_database, "catalog": "", "key": key,
                               "type": "TABLE", "database": target_database})
                columns[key] = columns.get(name) if target_database == database and name in columns else self.columns(name, target_database)
        if self.cosmos_nosql and context.get("container"):
            container = context["container"]
            columns["c"] = columns.get(container) or self.columns(container, database)
            tables.append({"name": "c", "schema": "", "catalog": "", "key": "c", "type": "TABLE", "virtual": True})
        return {**context, "current_schema": "", "schemas": [], "databases": self._cached(("databases",), self.databases),
                "tables": tables, "columns": columns, "routines": [], "metadata_loaded": True,
                "metadata_partial": True, "capabilities": capabilities_for(self.db_type, self.connector.config)}

    def dispatch(self, method, params):
        if method == "explorer.list":
            return self.list(params)
        if method == "explorer.details":
            return self.details(params)
        if method == "explorer.query":
            return self.query(params)
        if method == "explorer.use_database":
            return {"database": params.get("database", ""), "schema": "", "container": params.get("container", "")}
        raise ValueError("Unsupported object explorer operation")


def explorer_for(connector):
    from .database_capabilities import DOCUMENT_DATABASES
    if connector.db_type in DOCUMENT_DATABASES:
        return DocumentExplorer(connector)
    from .explorer import ObjectExplorer
    return ObjectExplorer(connector)
