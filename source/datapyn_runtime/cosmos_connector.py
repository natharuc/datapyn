"""Cosmos API for NoSQL: native SQL with explicit database/container focus."""

import time
from itertools import islice

from .document_connector import DocumentConnector, DocumentDatabaseError
from .document_sql import read_query


class CosmosConnector(DocumentConnector):
    def __init__(self, config):
        super().__init__(config)
        self.client = None
        self.credential = None
        self._query_in_progress = False

    def connect(self):
        from azure.cosmos import CosmosClient
        from azure.cosmos.documents import ConnectionPolicy, RetryOptions
        from .cosmos_transport import no_replay_transport
        if self.config.get("auth_mode") == "entra":
            from azure.identity import InteractiveBrowserCredential
            self.credential = InteractiveBrowserCredential(tenant_id=self.config.get("tenant_id") or "organizations")
            credential = self.credential
        else:
            credential = self.config.get("account_key")
            if not credential:
                raise ValueError("Enter the Cosmos DB account key or select Microsoft Entra authentication")
        try:
            policy = ConnectionPolicy()
            # retry_total=0 alone is ignored by the SDK's throttle options
            # builder (zero falls through to its default of nine retries).
            policy.RetryOptions = RetryOptions(max_retry_attempt_count=0, max_wait_time_in_seconds=0)
            self.client = CosmosClient(self.config["endpoint"], credential=credential,
                                       connection_policy=policy, transport=no_replay_transport(self),
                                       connection_verify=self.config.get("ca_certificate") or True,
                                       connection_timeout=5, read_timeout=min(self.timeout, 30),
                                       retry_total=0, retry_connect=0, retry_read=0, retry_status=0)
            database = self.connection_params["database"]
            if database:
                db = self.client.get_database_client(database)
                db.read()
                if self.connection_params["container"]:
                    db.get_container_client(self.connection_params["container"]).read()
            else:
                # A small first page verifies account access without scanning.
                next(iter(self.client.list_databases(max_item_count=1)), None)
        except Exception as error:
            self._failure(error, submitted=False)
        self._connected = True

    def _container(self):
        database, container = self.connection_params["database"], self.connection_params["container"]
        if not database or not container:
            raise ValueError("Choose a Cosmos DB database and container before running the query")
        return self.client.get_database_client(database).get_container_client(container)

    def iter_batches(self, query, parameters=None):
        query, bound = read_query(query, parameters, provider="cosmosdb")
        container = self._container()
        self.columns = None
        deadline = time.monotonic() + self.timeout
        def charge(headers, _response):
            try:
                self.last_request_charge += float(headers.get("x-ms-request-charge", 0))
            except (ValueError, TypeError):
                pass
        options = {"parameters": bound, "max_item_count": 1000, "response_hook": charge,
                   "enable_cross_partition_query": True, "timeout": self.timeout}
        if self.config.get("partition_key") is not None and self.config.get("partition_key") != "":
            options["partition_key"] = self.config["partition_key"]
        try:
            self._query_in_progress = True
            pages = container.query_items(query=query, **options).by_page()
            for page in pages:
                if time.monotonic() >= deadline:
                    raise DocumentDatabaseError("The query exceeded its time limit. The query was not repeated.", status_code=408)
                # by_page can yield empty pages with a continuation token.
                rows = []
                for item in page:
                    rows.append(item if isinstance(item, dict) else {"value": item})
                    if len(rows) >= 1000:
                        yield rows
                        rows = []
                if rows:
                    yield rows
        except Exception as error:
            self._failure(error, submitted=True)
        finally:
            self._query_in_progress = False

    def databases(self):
        try:
            return [item["id"] for item in islice(self.client.list_databases(max_item_count=200), 1000)]
        except Exception as error:
            self._failure(error, submitted=False)

    def collections(self, database):
        try:
            return [item["id"] for item in islice(self.client.get_database_client(database).list_containers(max_item_count=200), 5000)]
        except Exception as error:
            self._failure(error, submitted=False)

    def sample(self, database, collection):
        try:
            target = self.client.get_database_client(database).get_container_client(collection)
            yield from islice(target.query_items(query="SELECT TOP 100 * FROM c", enable_cross_partition_query=True,
                                                max_item_count=20, timeout=5), 100)
        except Exception as error:
            self._failure(error, submitted=False)

    def disconnect(self):
        super().disconnect()
        if self.client is not None:
            self.client.close()
            self.client = None
        if self.credential is not None:
            self.credential.close()
            self.credential = None
