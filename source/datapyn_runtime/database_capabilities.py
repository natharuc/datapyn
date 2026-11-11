"""Small, public feature contract shared by the runtime and desktop."""

DOCUMENT_DATABASES = frozenset({"elasticsearch", "cosmosdb", "mongodb"})


def capabilities_for(db_type, config=None):
    kind = str(db_type or "").lower()
    config = config or {}
    documents = kind in DOCUMENT_DATABASES
    cosmos = kind == "cosmosdb" and config.get("cosmos_api", "nosql") != "mongodb"
    return {
        "query_language": "sql",
        "sql_dialect": "cosmosdb" if cosmos else "mongodb" if kind == "cosmosdb" else kind,
        "context_levels": ["database", "container"] if cosmos else [] if kind == "elasticsearch" else ["database"] if documents else ["database", "schema"],
        "metadata": True,
        "streaming": True,
        "sqlalchemy": not documents,
        "table_export": not documents,
        "temporary_tables": not documents,
        "manual_transactions": not documents,
        "ssh": kind in {"sqlserver", "postgresql", "mysql", "mariadb"},
        "read_only": documents,
    }
