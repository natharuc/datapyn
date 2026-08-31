from src.database.namespace import (
    NamespaceContext,
    format_context,
    has_dual_namespace,
    is_known_catalog,
    lookup_ci,
    namespace_levels,
    parse_context,
    resolve_schema_after_catalog_change,
    schemas_for_catalog,
)


def test_namespace_levels_databricks_is_dual():
    assert namespace_levels("databricks") == ("catalog", "schema")
    assert has_dual_namespace("databricks")
    assert not has_dual_namespace("sqlserver")
    assert not has_dual_namespace("postgresql")


def test_parse_context_catalog_schema():
    ctx = parse_context("databricks", "mag_bronze.esim")
    assert ctx == NamespaceContext(catalog="mag_bronze", schema="esim")
    assert ctx.formatted == "mag_bronze.esim"
    assert format_context("mag_bronze", "esim") == "mag_bronze.esim"


def test_parse_context_prefixes_keep_the_other_level():
    catalog_only = parse_context(
        "databricks",
        "CATALOG:mag_bronze",
        current_catalog="main",
        current_schema="default",
    )
    assert catalog_only.catalog == "mag_bronze"
    assert catalog_only.schema == "default"
    assert catalog_only.catalog_only

    schema_only = parse_context(
        "databricks",
        "SCHEMA:esim",
        current_catalog="main",
        current_schema="default",
    )
    assert schema_only.catalog == "main"
    assert schema_only.schema == "esim"
    assert schema_only.schema_only


def test_parse_context_bare_name_is_catalog_not_schema():
    ctx = parse_context(
        "databricks",
        "mag_bronze",
        current_catalog="main",
        current_schema="default",
    )
    assert ctx.catalog == "mag_bronze"
    assert ctx.schema == "default"
    assert ctx.catalog_only
    assert not ctx.schema_only


def test_parse_context_non_databricks_is_database():
    ctx = parse_context("sqlserver", "AppDb")
    assert ctx.database == "AppDb"
    assert ctx.catalog == ""
    assert ctx.schema == ""


def test_lookup_ci_and_known_catalog():
    mapping = {"Main": ["default", "audit"]}
    assert lookup_ci(mapping, "main") == ["default", "audit"]
    assert schemas_for_catalog(mapping, "MAIN") == ["default", "audit"]
    assert is_known_catalog("main", ["hive_metastore"], mapping)
    assert not is_known_catalog("missing", ["hive_metastore"], mapping)


def test_resolve_schema_after_catalog_change():
    catalog_schemas = {
        "mag_bronze": ["esim", "default"],
        "main": ["default", "audit"],
    }
    assert resolve_schema_after_catalog_change(catalog_schemas, "mag_bronze", "esim") == "esim"
    assert resolve_schema_after_catalog_change(catalog_schemas, "main", "esim") == "default"
    assert resolve_schema_after_catalog_change(catalog_schemas, "other", "esim") == "esim"
