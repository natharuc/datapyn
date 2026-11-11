"""Shared lifecycle and bounded result assembly for read-only SDK adapters."""

from collections import OrderedDict
from contextlib import closing
import pickle
import tempfile
import time

from .database_capabilities import capabilities_for
from .document_config import normalize_document_config


class DocumentDatabaseError(Exception):
    code = "document_query_failed"

    def __init__(self, message, *, status_code=None, provider_code=None):
        super().__init__(message)
        self.status_code = status_code
        self.provider_code = provider_code


def converted(value):
    """Keep original nested documents and exact BSON decimal values in frames."""
    if type(value).__module__.startswith("bson.decimal128"):
        return value.to_decimal()
    if isinstance(value, dict):
        return {str(key): converted(item) for key, item in value.items()}
    if isinstance(value, list):
        return [converted(item) for item in value]
    return value


class DocumentConnector:
    engine = None
    automatic_transactions = True
    has_temporary_tables = False
    command_result_callback = None

    def __init__(self, config):
        self.config = normalize_document_config(config)
        self.db_type = self.config["db_type"]
        # Preserve the requested mode in scope identity. No document adapter
        # opens a manual transaction, even when the global SQL mode is manual.
        self.automatic_transactions = self.config.get("automatic_transactions", True)
        self.connection_params = {key: self.config.get(key, "") for key in
                                  ("host", "port", "username", "database", "schema", "container", "cosmos_api")}
        self.capabilities = capabilities_for(self.db_type, self.config)
        self._connected = False
        self._lost = False
        self.columns = None
        self.last_request_charge = 0.0
        timeout = self.config.get("query_timeout", self.config.get("timeout_seconds", 60))
        try:
            self.timeout = min(3600.0, max(1.0, float(timeout)))
        except (ValueError, TypeError):
            raise ValueError("Query timeout must be a number of seconds") from None

    def is_connected(self):
        return self._connected and not self._lost

    def validate_connection_for_execution(self):
        if not self.is_connected():
            from src.database.connection_recovery import ConnectionLostError
            raise ConnectionLostError(acknowledgement_required=False, submitted=False)

    def get_connection_recovery_state(self):
        return {"required": self._lost or not self._connected, "acknowledgement_required": False,
                "session_state_lost": False, "submitted": self._lost}

    def get_transaction_state(self):
        return {"automatic_transactions": self.automatic_transactions, "pending": False, "state": "idle", "supported": False}

    def has_pending_transaction(self):
        return False

    def get_last_command_results(self):
        return []

    def _failure(self, error, *, submitted):
        """Never attach raw SDK requests, response bodies or credentials to errors."""
        from src.database.connection_recovery import ConnectionLostError
        if isinstance(error, ConnectionLostError):
            raise error from None
        name, module = type(error).__name__, type(error).__module__
        status = getattr(error, "status_code", None)
        code = getattr(error, "code", None)
        details = getattr(error, "details", None)
        if isinstance(details, dict):
            code = details.get("code", code)
        if isinstance(error, DocumentDatabaseError):
            raise error from None
        if status == 429 or code in {16500, "16500"}:
            raise DocumentDatabaseError("Request limit reached. Wait briefly and run the query again.", status_code=429, provider_code=code) from None
        if status in {401, 403} or code in {13, 18}:
            raise DocumentDatabaseError("Authentication failed. Check the credentials." if status == 401 or code == 18
                                        else "Access denied. Check permissions for this database and collection.",
                                        status_code=401 if code == 18 else status or 403, provider_code=code) from None
        if status == 404 or code == 26:
            raise DocumentDatabaseError("The requested database, container or index was not found.", status_code=404, provider_code=code) from None
        if name in {"ExecutionTimeout", "NetworkTimeout", "ReadTimeout", "Timeout", "ServiceResponseTimeoutError", "CosmosClientTimeoutError"} or code in {50, 262}:
            raise DocumentDatabaseError("The query exceeded its time limit. The query was not repeated.", status_code=408, provider_code=code) from None
        try:
            text = str(error).lower()[:8192]
        except Exception:
            text = ""
        if name in {"SSLError", "CertificateError", "SSLCertVerificationError"} or any(token in text for token in (
                "certificate verify failed", "certificate verification failed", "hostname mismatch", "self signed certificate")):
            raise DocumentDatabaseError("TLS certificate verification failed. Check the server certificate and CA configuration.", status_code=495) from None
        from pymongo.errors import ConnectionFailure
        transport = (isinstance(error, (ConnectionResetError, ConnectionAbortedError, BrokenPipeError, ConnectionFailure))
                     or module.startswith("requests") and name in {"ConnectionError", "ConnectTimeout"}
                     or module.startswith("azure") and name in {"ServiceRequestError", "ServiceResponseError"})
        if transport:
            self._lost = True
            raise ConnectionLostError(acknowledgement_required=False, submitted=submitted) from None
        # Validation messages are ours, before submission. SDK exceptions can
        # contain entire documents/headers; never include their repr/str here.
        if isinstance(error, ValueError) and not submitted:
            raise error from None
        raise DocumentDatabaseError("The database rejected the query. Check its syntax and supported operators.",
                                    status_code=status or 400, provider_code=code) from None

    @staticmethod
    def _check_mode(automatic_transactions):
        if automatic_transactions is not None and not isinstance(automatic_transactions, bool):
            raise ValueError("automatic_transactions must be a boolean")

    def iter_batches(self, query, parameters=None):
        raise NotImplementedError

    def execute_query(self, query, parameters=None, *, automatic_transactions=None):
        self._check_mode(automatic_transactions)
        import pandas as pd
        self.last_request_charge = 0.0
        frames = []
        iterator = self.iter_batches(query, parameters)
        with closing(iterator):
            for rows in iterator:
                # dtype=object avoids rounding 64-bit integers with nulls and
                # retains Decimal/BSON/nested values; the UI only gets pages.
                if rows:
                    frames.append(pd.DataFrame([converted(row) for row in rows], dtype=object))
                time.sleep(0)
        if not frames:
            result = pd.DataFrame(columns=self.columns or [])
            result.attrs["datapyn_document_result"] = True
            return result
        result = frames[0] if len(frames) == 1 else pd.concat(frames, ignore_index=True, sort=False)
        if self.columns is not None:
            result = result.reindex(columns=self.columns)
        result.attrs["datapyn_document_result"] = True
        return result

    def stream_query_to_files(self, query, *, base_path, export_format, parameters=None,
                              csv_options=None, on_progress=None, is_cancelled=None):
        """Spool private batches so late document fields cannot be dropped."""
        from src.database.query_stream_exporter import StreamExportResult, stream_result_set_to_file
        result, names, total = StreamExportResult(), OrderedDict(), 0
        iterator = self.iter_batches(query, parameters)
        # This file only contains objects produced by our own SDK iterator.
        # No external pickle is accepted, and it never crosses IPC/WebView.
        with tempfile.TemporaryFile() as spool, closing(iterator):
            for rows in iterator:
                if is_cancelled and is_cancelled():
                    result.cancelled = True
                    return result
                normalized = [converted(row) for row in rows]
                for row in normalized:
                    names.update((name, None) for name in row)
                total += len(normalized)
                pickle.dump(normalized, spool, protocol=5)
            columns = list(self.columns) if self.columns is not None else list(names)
            spool.seek(0)

            def chunks():
                from .values import document_json
                while True:
                    try:
                        batch = pickle.load(spool)
                    except EOFError:
                        return
                    def cell(value):
                        return document_json(value) if isinstance(value, (dict, list, tuple)) else value
                    yield columns, [[cell(row.get(name)) for name in columns] for row in batch]

            written = 0
            def advanced(count):
                nonlocal written
                written += count
                if on_progress:
                    on_progress(1, written, base_path.stat().st_size if base_path.exists() else 0)
            count = stream_result_set_to_file(columns, chunks(), path=base_path,
                                               export_format=export_format, csv_options=csv_options,
                                               on_chunk=advanced, is_cancelled=is_cancelled)
            if count < 0 or is_cancelled and is_cancelled():
                result.cancelled = True
            else:
                result.files.append(base_path)
                result.row_counts.append(count)
                result.columns_per_file.append(columns)
        return result

    def disconnect(self):
        self._connected = False


def connect_document(config):
    kind = str(config.get("db_type", "")).lower()
    if kind == "elasticsearch":
        from .elasticsearch_connector import ElasticsearchConnector
        adapter = ElasticsearchConnector(config)
    elif kind == "mongodb" or kind == "cosmosdb" and config.get("cosmos_api") == "mongodb":
        from .mongodb_connector import MongoDBConnector
        adapter = MongoDBConnector(config)
    else:
        from .cosmos_connector import CosmosConnector
        adapter = CosmosConnector(config)
    try:
        adapter.connect()
        return adapter
    except BaseException:
        try:
            adapter.disconnect()
        except Exception:
            pass
        raise
