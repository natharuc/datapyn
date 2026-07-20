"""Cross-database schema sync for Databricks."""

from src.services.cross_database_schema import (
    extract_referenced_catalogs,
    extract_referenced_table_refs,
)


def test_extract_referenced_catalogs_uses_databricks_dialect():
    sql = "SELECT * FROM hive_metastore.audit.events"
    refs = extract_referenced_catalogs(
        sql,
        current_database="main",
        db_type="databricks",
    )
    assert "hive_metastore" in refs


def test_extract_referenced_table_refs_returns_three_part_names():
    sql = "SELECT id FROM hive_metastore.audit.events e"
    refs = extract_referenced_table_refs(
        sql,
        current_database="main",
        db_type="databricks",
    )
    assert ("hive_metastore", "audit", "events") in refs
