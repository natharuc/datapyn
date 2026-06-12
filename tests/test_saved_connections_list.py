"""Saved connections list search and picker."""

from src.ui.components.saved_connections_list import build_connection_search_text


class TestBuildConnectionSearchText:
    def test_includes_name_and_group(self):
        blob = build_connection_search_text(
            "LOCAL",
            {"group": "MAG", "db_type": "mysql", "host": "10.0.0.1", "database": "app"},
        )
        assert "local" in blob
        assert "mag" in blob

    def test_includes_host_database_type_username_port(self):
        blob = build_connection_search_text(
            "PROD",
            {
                "group": "",
                "host": "prod-sql-host-01",
                "database": "Gecon",
                "db_type": "sqlserver",
                "username": "admin@corp.com",
                "port": 1433,
            },
        )
        assert "prod-sql-host-01" in blob
        assert "gecon" in blob
        assert "sqlserver" in blob
        assert "admin@corp.com" in blob
        assert "1433" in blob

    def test_includes_databricks_http_path(self):
        blob = build_connection_search_text(
            "DBX",
            {"db_type": "databricks", "http_path": "/sql/1.0/endpoints/abc"},
        )
        assert "databricks" in blob
        assert "/sql/1.0/endpoints/abc" in blob

    def test_query_matches_host(self):
        blob = build_connection_search_text("X", {"host": "unique-host-42"})
        assert "unique-host-42" in blob
        assert "unique-host" in blob
