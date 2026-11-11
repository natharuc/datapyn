"""SQL subset compiled to a read-only server-side aggregation pipeline."""

import time
from itertools import islice

from .document_connector import DocumentConnector, DocumentDatabaseError


class MongoDBConnector(DocumentConnector):
    def __init__(self, config):
        super().__init__(config)
        self.client = None

    def connect(self):
        from pymongo import MongoClient
        options = {"serverSelectionTimeoutMS": 5000, "connectTimeoutMS": 5000,
                   "socketTimeoutMS": int(min(self.timeout, 30) * 1000),
                   "retryReads": False, "retryWrites": False, "max_adaptive_retries": 0, "tz_aware": True}
        if self.config.get("username"):
            options.update(username=self.config["username"], password=self.config.get("password", ""))
        if self.config.get("auth_source"):
            options["authSource"] = self.config["auth_source"]
        if self.config.get("ca_certificate"):
            options["tlsCAFile"] = self.config["ca_certificate"]
        try:
            self.client = MongoClient(self.config["mongodb_uri"], **options)
            self.client.admin.command("ping")
        except Exception as error:
            self._failure(error, submitted=False)
        self._connected = True

    def iter_batches(self, query, parameters=None):
        from .mongo_sql import compile_query
        compiled = compile_query(query, parameters, database=self.connection_params["database"])
        if not compiled.database:
            raise ValueError("Choose a database before running this query")
        self.columns = compiled.columns
        if compiled.limit_zero:
            return
        cursor = None
        deadline = time.monotonic() + self.timeout
        try:
            cursor = self.client[compiled.database][compiled.collection].aggregate(
                compiled.pipeline, batchSize=1000, maxTimeMS=int(self.timeout * 1000), allowDiskUse=False)
            rows = []
            for row in cursor:
                rows.append(row)
                if len(rows) >= 1000:
                    yield rows
                    rows = []
                    if time.monotonic() >= deadline:
                        raise DocumentDatabaseError("The query exceeded its time limit. The query was not repeated.", status_code=408)
            if rows:
                yield rows
        except Exception as error:
            self._failure(error, submitted=True)
        finally:
            if cursor is not None:
                cursor.close()

    def databases(self):
        try:
            return self.client.list_database_names(authorizedDatabases=True)
        except Exception as error:
            self._failure(error, submitted=False)

    def collections(self, database):
        cursor = None
        try:
            cursor = self.client[database].list_collections(nameOnly=True, cursor={"batchSize": 200}, maxTimeMS=5000)
            return [item["name"] for item in islice(cursor, 5000)]
        except Exception as error:
            self._failure(error, submitted=False)
        finally:
            if cursor is not None:
                cursor.close()

    def sample(self, database, collection):
        cursor = None
        try:
            cursor = self.client[database][collection].find({}, limit=100, batch_size=20, max_time_ms=5000)
            for document in islice(cursor, 100):
                yield document
        except Exception as error:
            self._failure(error, submitted=False)
        finally:
            if cursor is not None:
                cursor.close()

    def disconnect(self):
        super().disconnect()
        if self.client is not None:
            self.client.close()
            self.client = None
