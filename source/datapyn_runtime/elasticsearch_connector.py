"""Elasticsearch SQL REST adapter; one request per page, without SQL replay."""

import time
import json
from datetime import datetime

from .document_connector import DocumentConnector, DocumentDatabaseError
from .document_sql import read_query


class ElasticsearchConnector(DocumentConnector):
    def __init__(self, config):
        super().__init__(config)
        self.session = None
        self.column_types = {}

    def connect(self):
        import requests
        self.session = requests.Session()
        self.session.verify = self.config.get("ca_certificate") or self.config.get("tls_verify", True)
        if self.config.get("auth_mode") == "api_key":
            if not self.config.get("api_key"):
                raise ValueError("Enter the Elasticsearch API key")
            self.session.headers["Authorization"] = "ApiKey " + str(self.config["api_key"])
        elif self.config.get("username"):
            self.session.auth = (self.config["username"], self.config.get("password", ""))
        try:
            # Verify the same SQL API used by execution, including its access
            # and licensing, rather than merely accepting a cluster HTTP ping.
            self._request("POST", "/_sql", {"query": "SELECT 1", "fetch_size": 1})
        except Exception as error:
            self._failure(error, submitted=False)
        self._connected = True

    def _request(self, method, path, body=None, *, deadline=None):
        remaining = max(0.1, deadline - time.monotonic()) if deadline is not None else self.timeout
        response = self.session.request(method, self.config["endpoint"] + path, json=body,
                                        timeout=(min(5, remaining), min(self.timeout, remaining)),
                                        allow_redirects=False, stream=True)
        try:
            if response.status_code >= 300:
                status = response.status_code
                messages = {400: "Elasticsearch rejected the SQL query. Check its syntax and field types.",
                            401: "Authentication failed. Check the Elasticsearch credentials.",
                            403: "Elasticsearch denied this SQL request. Check permissions and SQL availability.",
                            404: "The Elasticsearch SQL endpoint or index was not found.",
                            429: "Elasticsearch request limit reached. Wait briefly and run the query again."}
                raise DocumentDatabaseError(messages.get(status, "Elasticsearch could not complete the request."), status_code=status)
            payload = bytearray()
            for chunk in response.iter_content(chunk_size=64 * 1024):
                if deadline is not None and time.monotonic() >= deadline:
                    raise DocumentDatabaseError("The query exceeded its time limit. The query was not repeated.", status_code=408)
                payload.extend(chunk)
                if len(payload) > 32 * 1024 * 1024:
                    raise DocumentDatabaseError("An Elasticsearch response page exceeds 32 MiB. Select fewer fields or smaller documents.")
            data = json.loads(payload)
            if not isinstance(data, dict):
                raise DocumentDatabaseError("Elasticsearch returned an invalid SQL response")
            return data
        finally:
            response.close()

    def iter_batches(self, query, parameters=None):
        query, bound = read_query(query, parameters, provider="elasticsearch")
        self.columns = None
        cursor = None
        submitted = False
        deadline = time.monotonic() + self.timeout
        try:
            submitted = True
            page = self._request("POST", "/_sql", {"query": query, "params": bound, "fetch_size": 1000,
                                                       "request_timeout": f"{int(self.timeout)}s", "page_timeout": "1m"}, deadline=deadline)
            metadata = page.get("columns", [])
            if (not isinstance(metadata, list) or len(metadata) > 4096 or
                    any(not isinstance(column, dict) or not isinstance(column.get("name"), str) for column in metadata)):
                raise DocumentDatabaseError("Elasticsearch returned invalid result column metadata")
            self.columns = [column["name"] for column in metadata]
            if len(self.columns) != len(set(self.columns)):
                raise DocumentDatabaseError("Result columns must have distinct names. Add aliases to repeated fields.")
            self.column_types = {column["name"]: column.get("type", "unknown") for column in metadata}
            while True:
                cursor = page.get("cursor")
                rows = page.get("rows", [])
                if not isinstance(rows, list) or any(not isinstance(row, list) or len(row) != len(self.columns) for row in rows):
                    raise DocumentDatabaseError("Elasticsearch returned a row that does not match its column metadata")
                yield [dict(zip(self.columns, [self._typed_value(name, value) for name, value in zip(self.columns, row)])) for row in rows]
                if not cursor:
                    break
                if time.monotonic() >= deadline:
                    raise DocumentDatabaseError("The query exceeded its time limit. The query was not repeated.", status_code=408)
                page = self._request("POST", "/_sql", {"cursor": cursor, "request_timeout": f"{int(self.timeout)}s"}, deadline=deadline)
        except Exception as error:
            self._failure(error, submitted=submitted)
        finally:
            if cursor:
                try:
                    self._request("POST", "/_sql/close", {"cursor": cursor})
                except Exception:
                    pass  # Cursor expires after its bounded page timeout.

    def indices(self):
        try:
            result = self._request("GET", "/_resolve/index/*")
            return sorted({str(item["name"]) for category in ("indices", "aliases", "data_streams")
                           for item in result.get(category, []) if not str(item.get("name", "")).startswith(".")})
        except Exception as error:
            self._failure(error, submitted=False)

    def fields(self, name):
        from urllib.parse import quote
        try:
            data = self._request("GET", "/" + quote(name, safe="") + "/_mapping")
            fields = {}
            def walk(properties, prefix="", depth=0):
                if depth > 16 or len(fields) >= 1000:
                    return
                for key, item in properties.items():
                    if len(fields) >= 1000:
                        return
                    path = prefix + key
                    fields[path] = {"name": path, "dtype": item.get("type", "object"), "nullable": True}
                    if isinstance(item.get("properties"), dict):
                        walk(item["properties"], path + ".", depth + 1)
                    if isinstance(item.get("fields"), dict):
                        walk(item["fields"], path + ".", depth + 1)
            for index in data.values():
                walk(index.get("mappings", {}).get("properties", {}))
            return list(fields.values())
        except Exception as error:
            self._failure(error, submitted=False)

    def _typed_value(self, name, value):
        if value is None:
            return None
        kind = self.column_types.get(name)
        if kind in {"datetime", "date", "date_nanos"} and isinstance(value, str):
            try:
                return datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError:
                raise DocumentDatabaseError("Elasticsearch returned an invalid date value for a date-typed column") from None
        return value

    def disconnect(self):
        super().disconnect()
        if self.session is not None:
            self.session.close()
            self.session = None
