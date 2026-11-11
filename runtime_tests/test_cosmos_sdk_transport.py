"""Exercise the real Cosmos SDK's retry loops over an isolated fake transport."""

import base64
import json
from urllib.parse import urlsplit

from azure.core.exceptions import ServiceRequestError, ServiceResponseError
from azure.core.pipeline.transport import HttpResponse, HttpTransport
import pytest

from datapyn_runtime.cosmos_connector import CosmosConnector
from datapyn_runtime.document_connector import DocumentDatabaseError
from src.database.connection_recovery import ConnectionLostError


class _Response(HttpResponse):
    def __init__(self, request, status, body, continuation=None):
        super().__init__(request, None)
        self.internal_response = self
        self.status_code = status
        self.reason = "isolated test response"
        self.headers = {"content-type": "application/json", "x-ms-activity-id": "isolated",
                        "x-ms-request-charge": "1", "x-ms-retry-after-ms": "1"}
        if continuation is not None:
            self.headers["x-ms-continuation"] = continuation
        self._data = json.dumps(body).encode()
        self.closed = False

    def body(self):
        return self._data

    def close(self):
        self.closed = True

    def stream_download(self, pipeline, **kwargs):
        return iter([self._data])


class _Transport(HttpTransport):
    def __init__(self):
        self.failure = None
        self.query_attempts = 0
        self.responses = []
        self.closed = False
        self.pages = None
        self.queries = []

    def open(self):
        pass

    def close(self):
        self.closed = True

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def send(self, request, **kwargs):
        path = urlsplit(request.url).path.rstrip("/")
        if request.method == "POST":
            self.query_attempts += 1
            self.queries.append((json.loads(request.body), dict(request.headers)))
            if isinstance(self.failure, Exception):
                raise self.failure
            if self.failure:
                response = _Response(request, self.failure, {"code": "isolated-error", "message": "private-server-details"})
                self.responses.append(response)
                return response
            if self.pages is not None:
                documents, continuation = self.pages.pop(0)
                response = _Response(request, 200, {"Documents": documents, "_count": len(documents)}, continuation)
                self.responses.append(response)
                return response
        if not path:
            body = {"id": "isolated", "_rid": "isolated", "enableMultipleWriteLocations": False,
                    "writableLocations": [{"name": "isolated", "databaseAccountEndpoint": "https://account.invalid/"}],
                    "readableLocations": [{"name": "isolated", "databaseAccountEndpoint": "https://account.invalid/"}],
                    "userConsistencyPolicy": {"defaultConsistencyLevel": "Session"}}
        elif path.endswith("/colls/cases"):
            body = {"id": "cases", "_rid": "cases-rid", "_self": "dbs/test/colls/cases/",
                    "partitionKey": {"paths": ["/pk"], "kind": "Hash", "version": 2}}
        elif path.endswith("/pkranges"):
            body = {"PartitionKeyRanges": [{"id": "0", "minInclusive": "", "maxExclusive": "FF"}], "_count": 1}
        elif request.method == "POST":
            body = {"Documents": [{"id": "one", "value": 1}], "_count": 1}
        else:
            body = {"id": "test", "_rid": "test-rid", "_self": "dbs/test/"}
        response = _Response(request, 200, body)
        self.responses.append(response)
        return response


@pytest.fixture
def cosmos(monkeypatch):
    import azure.core.pipeline.transport
    transport = _Transport()
    monkeypatch.setattr(azure.core.pipeline.transport, "RequestsTransport", lambda **kwargs: transport)
    adapter = CosmosConnector({"db_type": "cosmosdb", "cosmos_api": "nosql",
                               "endpoint": "https://account.invalid", "auth_mode": "key",
                               "account_key": base64.b64encode(b"isolated-synthetic-key").decode(),
                               "database": "test", "container": "cases"})
    adapter.connect()
    try:
        yield adapter, transport
    finally:
        adapter.disconnect()
        assert transport.closed


def test_actual_sdk_throttle_and_connection_retry_budgets_are_zero(cosmos):
    adapter, _ = cosmos
    policy = adapter.client.client_connection.connection_policy
    assert policy.RetryOptions.MaxRetryAttemptCount == 0
    assert policy.RetryOptions.MaxWaitTimeInSeconds == 0
    assert policy.ConnectionRetryConfiguration.total_retries == 0
    assert policy.ConnectionRetryConfiguration.connect_retries == 0
    assert policy.ConnectionRetryConfiguration.read_retries == 0
    assert policy.ConnectionRetryConfiguration.status_retries == 0


def test_actual_sdk_runs_select_value_with_bound_parameters_and_empty_continuation_page(cosmos):
    adapter, transport = cosmos
    transport.pages = [([], "isolated-next"), ([7], None)]
    frame = adapter.execute_query("SELECT VALUE c.value FROM c WHERE c.name = @name", {"name": "$not-an-operator"})
    assert frame.to_dict(orient="records") == [{"value": 7}]
    assert transport.query_attempts == 2
    body, headers = transport.queries[0]
    assert body["query"] == "SELECT VALUE c.value FROM c WHERE c.name = @name"
    assert body["parameters"] == [{"name": "@name", "value": "$not-an-operator"}]
    assert transport.queries[1][1]["x-ms-continuation"] == "isolated-next"
    assert adapter.last_request_charge == 2


@pytest.mark.parametrize("status", [401, 403, 429, 500, 503])
def test_actual_sdk_does_not_replay_query_on_http_failure(cosmos, status):
    adapter, transport = cosmos
    transport.failure = status
    with pytest.raises(DocumentDatabaseError) as captured:
        list(adapter.iter_batches("SELECT * FROM c"))
    assert transport.query_attempts == 1
    assert captured.value.status_code == status
    assert "private-server-details" not in str(captured.value)
    assert transport.responses[-1].closed


@pytest.mark.parametrize("error", [ServiceRequestError("private-network-details"),
                                    ServiceResponseError("private-timeout-details")])
def test_actual_sdk_does_not_replay_after_transport_interruption(cosmos, error):
    adapter, transport = cosmos
    transport.failure = error
    with pytest.raises(ConnectionLostError) as captured:
        list(adapter.iter_batches("SELECT * FROM c"))
    assert transport.query_attempts == 1
    assert captured.value.details["submitted"] is True
    assert "private" not in str(captured.value)
