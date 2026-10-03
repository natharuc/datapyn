"""Lazy introspection with bounded per-connector caches and dialect-aware SQL."""

from __future__ import annotations

from collections import OrderedDict
from copy import deepcopy
import json
import time

from .database import SQLiteConnector


def quote(db_type, *parts):
    if db_type == "sqlserver":
        return ".".join("[" + str(part).replace("]", "]]") + "]" for part in parts if part)
    if db_type in {"mysql", "mariadb", "databricks"}:
        return ".".join("`" + str(part).replace("`", "``") + "`" for part in parts if part)
    return ".".join('"' + str(part).replace('"', '""') + '"' for part in parts if part)


def literal(value):
    return "'" + str(value).replace("'", "''") + "'"


class ObjectExplorer:
    def __init__(self, connector):
        self.connector = connector
        self.cache = OrderedDict()
        self.column_cache = OrderedDict()

    @property
    def db_type(self):
        return self.connector.db_type

    def context(self):
        config = self.connector.connection_params
        database = config.get("database", "")
        schema = config.get("schema", "")
        if self.db_type == "sqlite":
            schema = "main"
        elif self.db_type == "postgresql":
            schema = schema or "public"
        elif self.db_type == "sqlserver":
            schema = schema or "dbo"
        elif self.db_type in {"mysql", "mariadb"}:
            schema = schema or database
        for method, key in (("get_current_database", "database"), ("get_current_schema", "schema")):
            getter = getattr(self.connector, method, None)
            if callable(getter):
                try:
                    value = getter()
                    if value:
                        if key == "database":
                            database = value
                        else:
                            schema = value
                except Exception:
                    pass
        return {"db_type": self.db_type, "database": str(database), "schema": str(schema)}

    def _cached(self, key, loader, refresh=False):
        now = time.monotonic()
        if not refresh and key in self.cache and now - self.cache[key][0] < 60:
            self.cache.move_to_end(key)
            return deepcopy(self.cache[key][1])
        value = loader()
        self.cache[key] = (now, value)
        while len(self.cache) > 256:
            self.cache.popitem(last=False)
        return deepcopy(value)

    def _records(self, query):
        frame = self.connector.execute_query(query)
        if isinstance(frame, list):
            frame = frame[0]
        return [{str(key).lower(): value for key, value in row.items()} for row in frame.to_dict("records")]

    def _node(self, name, kind, *, schema="", database="", children=False, category=None, **fields):
        key = json.dumps([database, schema, kind, name, category], separators=(",", ":"))
        return {"id": key, "name": str(name), "kind": kind, "has_children": children,
                "schema": schema, "database": database,
                "qualified_name": quote(self.db_type, schema, name) if kind in {"table", "view", "procedure", "function"} else "",
                **({"category": category} if category else {}), **fields}

    def databases(self):
        if self.db_type == "sqlite":
            return [row[1] for row in self.connector.connection.execute("PRAGMA database_list")]
        if self.db_type == "postgresql":
            return [self.context()["database"]]  # PostgreSQL schema chip, database requires reconnect.
        query = "SELECT name FROM sys.databases WHERE state_desc='ONLINE' ORDER BY name" if self.db_type == "sqlserver" else "SHOW CATALOGS" if self.db_type == "databricks" else "SHOW DATABASES"
        frame = self.connector.execute_query(query)
        return [str(value) for value in frame.iloc[:, 0].tolist()][:5000]

    def schemas(self, database=""):
        if self.db_type == "sqlite":
            aliases = [row[1] for row in self.connector.connection.execute("PRAGMA database_list")]
            return [database] if database in aliases else aliases
        if self.db_type in {"mysql", "mariadb"}:
            return [database or self.context()["database"]]
        if self.db_type == "databricks":
            frame = self.connector.execute_query(f"SHOW SCHEMAS IN {quote(self.db_type, database or self.context()['database'])}")
            return [str(value) for value in frame.iloc[:, 0].tolist() if str(value) != "information_schema"][:5000]
        from sqlalchemy import inspect
        return [str(value) for value in inspect(self.connector.engine).get_schema_names()
                if str(value) not in {"information_schema", "pg_catalog", "pg_toast"} and not str(value).startswith("pg_temp")][:5000]

    def objects(self, schema, category):
        if category in {"table", "view"}:
            from sqlalchemy import inspect
            inspector = inspect(self.connector.engine)
            names = inspector.get_table_names(schema=schema) if category == "table" else inspector.get_view_names(schema=schema)
            return [self._node(name, category, schema=schema, database=self.context()["database"], children=True) for name in sorted(names)[:10000]]
        if self.db_type == "sqlite":
            return []
        routine_type = "PROCEDURE" if category == "procedure" else "FUNCTION"
        if self.db_type == "sqlserver":
            types = "'P','PC'" if category == "procedure" else "'FN','IF','TF','FS','FT'"
            query = f"SELECT o.name FROM sys.objects o JOIN sys.schemas s ON s.schema_id=o.schema_id WHERE s.name={literal(schema)} AND o.type IN ({types}) ORDER BY o.name"
        else:
            query = f"SELECT routine_name AS name FROM information_schema.routines WHERE routine_schema={literal(schema)} AND routine_type={literal(routine_type)} ORDER BY routine_name"
        return [self._node(str(row["name"]), category, schema=schema, database=self.context()["database"], children=False) for row in self._records(query)][:10000]

    def columns(self, name, schema=""):
        key = (schema, name)
        def load():
            from sqlalchemy import inspect
            columns = inspect(self.connector.engine).get_columns(name, schema=schema or None)
            return [{"name": str(item["name"]), "dtype": str(item["type"]),
                     "type": str(item["type"]), "nullable": bool(item.get("nullable", True)),
                     "default": str(item["default"]) if item.get("default") is not None else None} for item in columns]
        value = self._cached(("columns", *key), load)
        self.column_cache[key] = value
        self.column_cache.move_to_end(key)
        while len(self.column_cache) > 128:
            self.column_cache.popitem(last=False)
        return value

    def list(self, params):
        node = params.get("node") or {}
        if not isinstance(node, dict):
            raise ValueError("node must be an object")
        kind, name = node.get("kind", "root"), str(node.get("name", ""))
        context = self.context()
        database = str(node.get("database") or params.get("database") or context["database"])
        schema = str(node.get("schema") or params.get("schema") or context["schema"])
        if kind == "root":
            loader = lambda: [self._node(value, "database", database=value, children=True) for value in self.databases()]
        elif kind == "database":
            database = name or database
            loader = lambda: [self._node(value, "schema", database=database, schema=value, children=True) for value in self.schemas(database)]
        elif kind == "schema":
            schema = name or schema
            loader = lambda: [self._node(label, "category", database=database, schema=schema, children=True, category=category)
                              for label, category in (("Tables", "table"), ("Views", "view"), ("Procedures", "procedure"), ("Functions", "function"))]
        elif kind == "category":
            category = node.get("category", name.lower().rstrip("s"))
            if category not in {"table", "view", "procedure", "function"}:
                raise ValueError("Unknown object category")
            loader = lambda: self.objects(schema, category)
        elif kind in {"table", "view"}:
            loader = lambda: [self._node(column["name"], "column", database=database, schema=schema, **{k: v for k, v in column.items() if k != "name"})
                              for column in self.columns(name, schema)]
        else:
            loader = lambda: []
        nodes = self._cached((kind, name, database, schema, node.get("category")), loader, bool(params.get("refresh")))
        return {"nodes": nodes, "context": context}

    def details(self, params):
        name = params.get("name")
        if not isinstance(name, str) or not name:
            raise ValueError("name must be a nonempty string")
        schema = str(params.get("schema") or self.context()["schema"])
        return self._cached(("details", schema, name, params.get("kind", "table")),
                            lambda: self._details(params, name, schema), bool(params.get("refresh")))

    def _details(self, params, name, schema):
        if isinstance(self.connector, SQLiteConnector):
            from sqlalchemy import inspect
            inspector = inspect(self.connector.engine)
            definition = self.connector.connection.execute(f"SELECT sql FROM {quote('sqlite', schema, 'sqlite_master')} WHERE name=?", (name,)).fetchone()
            return {"name": name, "schema": schema, "db_type": "sqlite", "columns": self.columns(name, schema),
                    "indexes": inspector.get_indexes(name, schema=schema), "primary_key": inspector.get_pk_constraint(name, schema=schema),
                    "foreign_keys": inspector.get_foreign_keys(name, schema=schema),
                    "definition": definition[0] if definition else "", "kind": params.get("kind", "table")}
        from src.services.entity_metadata_service import EntityMetadataService
        result = EntityMetadataService().fetch_entity_info(self.connector, quote(self.db_type, schema, name))
        result.update({"name": name, "schema": schema, "kind": params.get("kind", "table")})
        if not result.get("definition"):
            result.update(self.definition(name, schema, params.get("kind", "table"), result))
        return result

    def definition(self, name, schema, kind, metadata):
        entity = quote(self.db_type, schema, name)
        query = None
        if self.db_type in {"mysql", "mariadb"}:
            query = f"SHOW CREATE {kind.upper()} {entity}"
        elif self.db_type == "databricks" and kind in {"table", "view"}:
            query = f"SHOW CREATE TABLE {entity}"
        elif self.db_type == "sqlserver" and kind in {"view", "procedure", "function"}:
            query = f"SELECT OBJECT_DEFINITION(OBJECT_ID(N{literal(entity)})) AS definition"
        elif self.db_type == "postgresql" and kind == "view":
            query = f"SELECT pg_get_viewdef({literal(entity)}::regclass, true) AS definition"
        elif self.db_type == "postgresql" and kind in {"function", "procedure"}:
            query = ("SELECT pg_get_functiondef(p.oid) AS definition FROM pg_proc p "
                     "JOIN pg_namespace n ON n.oid=p.pronamespace "
                     f"WHERE n.nspname={literal(schema)} AND p.proname={literal(name)} ORDER BY p.oid LIMIT 10")
        if query:
            try:
                records = self._records(query)
                definitions = []
                for row in records:
                    value = next((value for key, value in row.items() if ("create" in key or key in {"definition", "createtab_stmt"}) and isinstance(value, str)), None)
                    if value:
                        definitions.append(f"CREATE OR REPLACE VIEW {entity} AS\n{value.rstrip(';')};" if self.db_type == "postgresql" and kind == "view" else value)
                if definitions:
                    return {"definition": "\n\n".join(definitions), "definition_is_generated": False}
            except Exception:
                pass  # Definition permissions must not hide available metadata.
        if kind == "table" and metadata.get("columns"):
            from src.services.entity_metadata_service import build_display_data_type
            lines = []
            for column in metadata["columns"]:
                data_type = build_display_data_type(column, self.db_type)
                if not data_type:
                    return {"definition": "", "definition_warning": f"The driver did not supply a data type for {column['name']}"}
                nullable = column.get("nullable", "YES")
                not_null = nullable is False or str(nullable).upper() in {"NO", "FALSE", "0"}
                declaration = f"    {quote(self.db_type, column['name'])} {data_type}"
                identity = column.get("identity") or column.get("is_identity")
                if identity:
                    if self.db_type == "sqlserver":
                        details = identity if isinstance(identity, dict) else {}
                        declaration += f" IDENTITY({int(details.get('start', 1))},{int(details.get('increment', 1))})"
                    elif self.db_type == "postgresql":
                        declaration += " GENERATED ALWAYS AS IDENTITY" if isinstance(identity, dict) and identity.get("always") else " GENERATED BY DEFAULT AS IDENTITY"
                    elif self.db_type in {"mysql", "mariadb"}:
                        declaration += " AUTO_INCREMENT"
                declaration += " NOT NULL" if not_null else " NULL"
                default = column.get("default") or column.get("column_default")
                if default is not None and str(default).strip() and not identity:
                    declaration += f" DEFAULT {default}"
                lines.append(declaration)
            primary = (metadata.get("primary_key") or {}).get("constrained_columns")
            if not primary:
                primary_index = next((index for index in metadata.get("indexes", []) if index.get("primary")), {})
                primary = primary_index.get("columns")
                if isinstance(primary, str):
                    parts = [part.strip() for part in primary.split(",")]
                    names = {column["name"] for column in metadata["columns"]}
                    primary = parts if all(part in names for part in parts) else None
            if isinstance(primary, (list, tuple)) and primary:
                lines.append("    PRIMARY KEY (" + ", ".join(quote(self.db_type, column) for column in primary) + ")")
            return {"definition": f"CREATE TABLE {entity} (\n" + ",\n".join(lines) + "\n);",
                    "definition_is_generated": True}
        return {"definition": ""}

    def query(self, params):
        name = params.get("name")
        if not isinstance(name, str) or not name:
            raise ValueError("name must be a nonempty string")
        schema = str(params.get("schema") or self.context()["schema"])
        limit = params.get("limit", 1000)
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 100000:
            raise ValueError("limit must be between 1 and 100000")
        entity = quote(self.db_type, schema, name)
        if params.get("kind") == "procedure":
            code = f"EXEC {entity};" if self.db_type == "sqlserver" else f"CALL {entity}();"
        elif self.db_type == "sqlserver":
            code = f"SELECT TOP ({limit}) *\nFROM {entity};"
        else:
            code = f"SELECT *\nFROM {entity}\nLIMIT {limit};"
        return {"code": code, "language": "sql"}

    def completion_schema(self, code=""):
        context = self.context()
        schema = context["schema"]
        schemas = self._cached(("schemas", context["database"]), lambda: self.schemas(context["database"]))
        requested_schemas = [schema]
        import re
        for candidate in schemas:
            if candidate != schema and re.search(r"(?i)(?<![\w])(?:\[|`|\")?" + re.escape(candidate) + r"(?:\]|`|\")?\s*\.", code or ""):
                requested_schemas.append(candidate)
        tables = []
        for candidate in requested_schemas[:8]:
            tables.extend(self._cached(("completion_tables", candidate), lambda candidate=candidate: self.objects(candidate, "table") + self.objects(candidate, "view")))
        # Fetch columns only for relations actually referenced by the document.
        for table in tables:
            if code and re.search(r"(?i)(?<![\w])" + re.escape(table["name"]) + r"(?![\w])", code):
                self.columns(table["name"], table["schema"])
        catalog = context["database"] if self.db_type == "databricks" else ""
        result = {**context, "current_schema": schema, "databases": self._cached(("databases",), self.databases),
                  "schemas": schemas,
                  "tables": [{"name": t["name"], "schema": t["schema"], "catalog": catalog, "key": ".".join(part for part in (catalog, t["schema"], t["name"]) if part), "type": t["kind"].upper()} for t in tables],
                  "columns": {".".join(part for part in (catalog, s, name) if part): columns for (s, name), columns in self.column_cache.items()},
                  "routines": [], "metadata_loaded": True}
        if re.search(r"(?i)\b(?:EXEC|EXECUTE|CALL)\s", code or ""):
            for candidate in requested_schemas[:8]:
                for kind in ("procedure", "function"):
                    for routine in self._cached(("routines", candidate, kind), lambda candidate=candidate, kind=kind: self.objects(candidate, kind)):
                        result["routines"].append({"name": routine["name"], "schema": candidate, "type": kind.upper()})
        return result

    def dispatch(self, method, params):
        if method == "explorer.list":
            return self.list(params)
        if method == "explorer.details":
            return self.details(params)
        if method == "explorer.query":
            return self.query(params)
        raise ValueError(f"Unknown explorer method: {method}")
