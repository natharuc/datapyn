"""Engine namespace levels (catalog/schema vs single database)."""

from __future__ import annotations

from dataclasses import dataclass

CATALOG_PREFIX = "CATALOG:"
SCHEMA_PREFIX = "SCHEMA:"

NAMESPACE_LEVELS: dict[str, tuple[str, ...]] = {
    "databricks": ("catalog", "schema"),
    "sqlserver": ("database",),
    "mssql": ("database",),
    "mysql": ("database",),
    "mariadb": ("database",),
    "postgresql": ("database",),
}


@dataclass(frozen=True)
class NamespaceContext:
    """Parsed execution context for a connection."""

    catalog: str = ""
    schema: str = ""
    database: str = ""
    catalog_only: bool = False
    schema_only: bool = False

    @property
    def formatted(self) -> str:
        if self.catalog and self.schema:
            return f"{self.catalog}.{self.schema}"
        return self.catalog or self.schema or self.database


def namespace_levels(db_type: str) -> tuple[str, ...]:
    return NAMESPACE_LEVELS.get(str(db_type or "").lower(), ("database",))


def has_dual_namespace(db_type: str) -> bool:
    return len(namespace_levels(db_type)) >= 2


def lookup_ci(mapping: dict | None, key: str, default=None):
    """Case-insensitive dict lookup preserving the original mapped value."""
    if not mapping:
        return default
    if key in mapping:
        return mapping[key]
    needle = str(key or "").lower()
    if not needle:
        return default
    for existing, value in mapping.items():
        if str(existing).lower() == needle:
            return value
    return default


def is_known_catalog(name: str, catalogs: list | None = None, catalog_schemas: dict | None = None) -> bool:
    needle = str(name or "").strip().lower()
    if not needle:
        return False
    for catalog in catalogs or []:
        if str(catalog).lower() == needle:
            return True
    for catalog in (catalog_schemas or {}):
        if str(catalog).lower() == needle:
            return True
    return False


def schemas_for_catalog(catalog_schemas: dict | None, catalog: str) -> list[str]:
    values = lookup_ci(catalog_schemas, catalog, []) or []
    result = []
    seen = set()
    for schema_name in values:
        text = str(schema_name or "").strip()
        key = text.lower()
        if not text or key in seen:
            continue
        seen.add(key)
        result.append(text)
    return result


def resolve_schema_after_catalog_change(
    catalog_schemas: dict | None,
    catalog: str,
    current_schema: str = "",
    *,
    fallback: str = "default",
) -> str:
    """Pick a schema that exists in ``catalog``, preferring the current one."""
    available = schemas_for_catalog(catalog_schemas, catalog)
    current = str(current_schema or "").strip()
    if current and any(item.lower() == current.lower() for item in available):
        return next(item for item in available if item.lower() == current.lower())
    if fallback and any(item.lower() == fallback.lower() for item in available):
        return next(item for item in available if item.lower() == fallback.lower())
    if available:
        return available[0]
    return current or fallback


def format_context(catalog: str, schema: str) -> str:
    catalog = str(catalog or "").strip()
    schema = str(schema or "").strip()
    if catalog and schema:
        return f"{catalog}.{schema}"
    return catalog or schema


def parse_context(
    db_type: str,
    value: str | None,
    *,
    current_catalog: str = "",
    current_schema: str = "",
    current_database: str = "",
) -> NamespaceContext:
    """Parse a block/OE/USE context string.

    Databricks accepts ``catalog.schema``, ``CATALOG:`` / ``SCHEMA:`` prefixes,
    or a bare name (treated as a catalog switch that keeps the current schema).
    Other engines keep a single database name.
    """
    raw = str(value or "").strip()
    engine = str(db_type or "").lower()
    current_catalog = str(current_catalog or "").strip()
    current_schema = str(current_schema or "").strip()
    current_database = str(current_database or "").strip()

    if engine != "databricks":
        return NamespaceContext(database=raw or current_database)

    if not raw:
        return NamespaceContext(
            catalog=current_catalog,
            schema=current_schema,
        )

    if raw.upper().startswith(CATALOG_PREFIX):
        catalog = raw[len(CATALOG_PREFIX):].strip()
        return NamespaceContext(
            catalog=catalog,
            schema=current_schema,
            catalog_only=True,
        )
    if raw.upper().startswith(SCHEMA_PREFIX):
        schema = raw[len(SCHEMA_PREFIX):].strip()
        return NamespaceContext(
            catalog=current_catalog,
            schema=schema,
            schema_only=True,
        )

    parts = [part.strip() for part in raw.split(".") if part.strip()]
    if len(parts) >= 2:
        return NamespaceContext(catalog=parts[0], schema=parts[1])
    return NamespaceContext(
        catalog=parts[0] if parts else current_catalog,
        schema=current_schema,
        catalog_only=True,
    )
