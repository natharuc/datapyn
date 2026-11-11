"""Fail-fast Cosmos transport; SDK failover must not replay submitted pages."""


def no_replay_transport(adapter):
    from azure.core.exceptions import ServiceRequestError, ServiceResponseError
    from azure.core.pipeline.transport import HttpTransport, RequestsTransport
    from .document_connector import DocumentDatabaseError

    class NoReplayTransport(HttpTransport):
        def __init__(self):
            self.inner = RequestsTransport(connection_timeout=5, read_timeout=min(adapter.timeout, 30))

        def open(self):
            self.inner.open()

        def close(self):
            self.inner.close()

        def __enter__(self):
            self.open()
            return self

        def __exit__(self, *args):
            self.close()

        def send(self, request, **kwargs):
            try:
                response = self.inner.send(request, **kwargs)
            except (ServiceRequestError, ServiceResponseError) as error:
                adapter._failure(error, submitted=adapter._query_in_progress)
            if response.status_code in {401, 403, 429} or response.status_code >= 500:
                status = response.status_code
                raw_response = getattr(response, "internal_response", response)
                close = getattr(raw_response, "close", None)
                if callable(close):
                    close()
                message = {401: "Authentication failed. Check the Cosmos DB credentials.",
                           403: "Access denied. Check permissions for this Cosmos DB account.",
                           429: "Cosmos DB request limit reached. Wait briefly and run the query again."}.get(
                               status, "Cosmos DB is temporarily unavailable. The query was not repeated.")
                # A domain exception bypasses Cosmos' independent regional and
                # throttle retry loops. 400/404/410 retain normal SDK handling
                # for query plans and partition/routing metadata.
                raise DocumentDatabaseError(message, status_code=status) from None
            return response

    return NoReplayTransport()
