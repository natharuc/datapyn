"""Real TDS PRELOGIN/TLS/NTLM traffic on loopback, including SSH and routing.

This endpoint validates an NTLM exchange, then sends the small protocol result
needed by the real python-tds connection. It is not an installed SQL Server or
a domain service and never uses user/system credentials.
"""

import socket
import socketserver
import ssl
import struct
import threading
from concurrent.futures import ThreadPoolExecutor

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
import pytest
import spnego
from spnego.channel_bindings import GssChannelBindings
from spnego.exceptions import NegotiateOptions

from src.database.sqlserver_network_auth import (
    SqlServerNetworkAuthError, connect_network, network_connect_options,
)
from datapyn_runtime.ssh_tunnel import SshTunnel
from test_ssh_database import database_tls_server  # noqa: F401
from test_ssh_tunnel import local_ssh, trust  # noqa: F401


def _read_exact(stream, size):
    result = bytearray()
    while len(result) < size:
        chunk = stream.recv(size - len(result))
        if not chunk:
            raise EOFError()
        result.extend(chunk)
    return bytes(result)


def _packet(kind, data):
    return struct.pack(">BBHHBB", kind, 1, len(data) + 8, 0, 1, 0) + data


def _read_packet(stream):
    data = bytearray()
    while True:
        header = _read_exact(stream, 8)
        kind, final, length, _spid, _id, _window = struct.unpack(">BBHHBB", header)
        data.extend(_read_exact(stream, length - 8))
        if final & 1:
            return kind, bytes(data)


class TdsTlsStream:
    def __init__(self, stream, context):
        self.stream, self.incoming, self.outgoing = stream, ssl.MemoryBIO(), ssl.MemoryBIO()
        self.tls = context.wrap_bio(self.incoming, self.outgoing, server_side=True)
        while True:
            try:
                self.tls.do_handshake()
            except ssl.SSLWantReadError:
                self._flush(wrapped=True)
                kind, chunk = _read_packet(stream)
                assert kind == 18
                self.incoming.write(chunk)
            else:
                self._flush(wrapped=True)
                break

    def _flush(self, wrapped=False):
        while self.outgoing.pending:
            data = self.outgoing.read()
            self.stream.sendall(_packet(18, data) if wrapped else data)

    def recv(self, size):
        while True:
            try:
                return self.tls.read(size)
            except ssl.SSLWantReadError:
                data = self.stream.recv(65536)
                if not data:
                    return b""
                self.incoming.write(data)

    def sendall(self, data):
        self.tls.write(data)
        self._flush()


def _done(rows=0):
    return b"\xfd" + struct.pack("<HHq", 0x10 if rows else 0, 0, rows)


def _login_ack():
    name = "DataPyn test endpoint"
    content = b"\x01" + struct.pack(">I", 0x74000004) + bytes([len(name)]) + name.encode("utf-16le") + struct.pack(">I", 0x10000001)
    return b"\xad" + struct.pack("<H", len(content)) + content


def _routing():
    name = "must-not-open.invalid"
    route = b"\x00" + struct.pack("<HH", 1433, len(name)) + name.encode("utf-16le")
    content = b"\x14" + struct.pack("<H", len(route)) + route + b"\0\0"
    return b"\xe3" + struct.pack("<H", len(content)) + content


def _info(message, severity=0):
    payload = struct.pack("<IBBH", 0, 1, severity, len(message)) + message.encode("utf-16le") + b"\0\0" + struct.pack("<I", 1)
    return b"\xab" + struct.pack("<H", len(payload)) + payload


@pytest.fixture
def tds_endpoint(database_tls_server, monkeypatch, tmp_path):
    credentials = tmp_path / "ntlm-test-users"
    credentials.write_text("TEST:account:network-secret\nTEST:second:second-secret\n", encoding="utf-8")
    monkeypatch.setenv("NTLM_USER_FILE", str(credentials))
    context = database_tls_server["context"]
    context.maximum_version = ssl.TLSVersion.TLSv1_2
    certificate = x509.load_pem_x509_certificate(open(database_tls_server["certificate"], "rb").read())
    digest = hashes.Hash(hashes.SHA256())
    digest.update(certificate.public_bytes(serialization.Encoding.DER))
    bindings = GssChannelBindings(application_data=b"tls-server-end-point:" + digest.finalize())
    state = {"authenticated": [], "errors": [], "routing": False, "queries": [], "packets": [], "logins": [],
             "waiting": threading.Event(), "cancelled": 0}

    class Handler(socketserver.BaseRequestHandler):
        def handle(self):
            self.request.settimeout(4)
            try:
                kind, _ = _read_packet(self.request)
                assert kind == 18
                # Server announces that the entire TDS connection uses TLS.
                self.request.sendall(_packet(4, b"\x01\x00\x06\x00\x01\xff\x01"))
                stream = TdsTlsStream(self.request, context)
                kind, login = _read_packet(stream)
                assert kind == 16
                # LOGIN7 integrated-security flag; SQL UID/PWD fields empty.
                assert login[25] & 0x80
                assert struct.unpack_from("<HHHH", login, 40) == (0, 0, 0, 0)
                state["logins"].append(login)
                offset, size = struct.unpack_from("<HH", login, 78)
                auth = spnego.server(protocol="ntlm", channel_bindings=bindings,
                                     options=NegotiateOptions.use_ntlm)
                challenge = auth.step(login[offset:offset + size])
                stream.sendall(_packet(4, b"\xed" + struct.pack("<H", len(challenge)) + challenge))
                kind, response = _read_packet(stream)
                assert kind in {16, 17}
                auth.step(response)
                assert auth.complete
                state["authenticated"].append(auth.client_principal)
                db_offset, db_size = struct.unpack_from("<HH", login, 68)
                db = login[db_offset:db_offset + db_size * 2]
                database_environment = b""
                if db_size:
                    environment = b"\x01" + bytes([db_size]) + db + b"\0"
                    database_environment = b"\xe3" + struct.pack("<H", len(environment)) + environment
                stream.sendall(_packet(4, _login_ack() + database_environment + (_routing() if state["routing"] else b"") + _done()))
                if state["routing"]:
                    return
                while True:
                    kind, query = _read_packet(stream)
                    if kind == 14:
                        header_size = struct.unpack_from("<I", query)[0]
                        operation = struct.unpack_from("<H", query, header_size)[0]
                        transaction = (b"\x08\x08" + struct.pack("<Q", 1) + b"\0" if operation == 5
                                       else bytes([9 if operation == 7 else 10, 0, 8]) + struct.pack("<Q", 1))
                        stream.sendall(_packet(4, b"\xe3" + struct.pack("<H", len(transaction)) + transaction + _done()))
                        continue
                    if kind == 6:  # Attention/cancellation response
                        state["cancelled"] += 1
                        stream.sendall(_packet(4, b"\xfd" + struct.pack("<HHq", 0x20, 0, 0)))
                        continue
                    assert kind in {1, 3}
                    header_size = struct.unpack_from("<I", query)[0]
                    state["queries"].append(query[header_size:].decode("utf-16le") if kind == 1 else "SELECT parameterized RPC")
                    state["packets"].append(query)
                    def contains(word):
                        return word.encode("utf-16le") in query
                    if contains("WAITFOR"):
                        state["waiting"].set()
                        continue
                    if contains("CREATE TABLE") or contains("INSERT INTO") or contains("USE ["):
                        stream.sendall(_packet(4, _done(1)))
                    else:
                        value = ("dbo" if contains("schema_name()") or contains("SCHEMA_NAME()")
                                 else "READ COMMITTED" if contains("transaction_isolation_level")
                                 else "test max support" if contains("test max support") else None)
                        if value is not None:
                            column = b"\x81\x01\x00" + struct.pack("<IH", 0, 1) + b"\xe7\xa0\x0f\x09\x04\xd0\x00\x34\x01v\0"
                            data = value.encode("utf-16le")
                            row = b"\xd1" + struct.pack("<H", len(data)) + data
                        else:
                            column = b"\x81\x01\x00" + struct.pack("<IH", 0, 1) + b"\x26\x04\x01v\0"
                            row = b"\xd1\x00" if contains("OBJECT_ID") else b"\xd1\x04" + struct.pack("<i", 1)
                        messages = _info("first progress") + _info("second progress", severity=10) if contains("PRINT") else b""
                        stream.sendall(_packet(4, messages + column + row + _done(1)))
            except (EOFError, OSError, ssl.SSLError):
                pass
            except Exception as error:
                state["errors"].append(repr(error))

    class Server(socketserver.ThreadingTCPServer):
        daemon_threads = True

    endpoint = Server(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=endpoint.serve_forever, daemon=True)
    thread.start()
    try:
        yield {"state": state, "port": endpoint.server_address[1], "tls": database_tls_server}
    finally:
        endpoint.shutdown()
        endpoint.server_close()
        thread.join(timeout=1)


def _options(endpoint, **kwargs):
    return network_connect_options("ntlm", "127.0.0.1", endpoint["port"], r"TEST\account", "network-secret",
                                   _ssh_original_host="db.remote.invalid", _ssh_original_port=1433,
                                   ssl_ca=endpoint["tls"]["certificate"], **kwargs)


def test_real_ntlm_tls_login_select_and_disconnect(tds_endpoint):
    connection = connect_network(database="", **_options(tds_endpoint))
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT %s", (1,))
            assert cursor.fetchone() == (1,)
        assert tds_endpoint["state"]["authenticated"] == [r"TEST\account"]
        assert "SELECT" in tds_endpoint["state"]["queries"][0]
        assert tds_endpoint["tls"]["sni"] == ["db.remote.invalid"]
        assert not tds_endpoint["state"]["errors"]
    finally:
        connection.close()


def test_real_ntlm_tls_through_ssh_uses_original_database_identity(local_ssh, trust, tds_endpoint):
    local_ssh.destination_port = tds_endpoint["port"]
    trust.confirm(local_ssh.details())
    tunnel = SshTunnel(local_ssh.config(), "db.remote.invalid", tds_endpoint["port"], trust_store=trust).start()
    options = _options(tds_endpoint)
    options["_datapyn_route_host"], options["_datapyn_route_port"] = tunnel.local_host, tunnel.local_port
    try:
        connection = connect_network(database="", **options)
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
                assert cursor.fetchone() == (1,)
        finally:
            connection.close()
        assert tds_endpoint["state"]["authenticated"] == [r"TEST\account"]
        assert tds_endpoint["tls"]["sni"] == ["db.remote.invalid"]
        assert ("db.remote.invalid", tds_endpoint["port"]) in local_ssh.destinations
        assert not tds_endpoint["state"]["errors"]
    finally:
        tunnel.close()


def test_real_tds_routing_cannot_escape_selected_endpoint(tds_endpoint, monkeypatch):
    tds_endpoint["state"]["routing"] = True
    original = socket.create_connection
    opened = []
    def limited(endpoint, *args, **kwargs):
        opened.append(endpoint)
        assert endpoint == ("127.0.0.1", tds_endpoint["port"]), "Routing must never open a direct socket"
        return original(endpoint, *args, **kwargs)
    monkeypatch.setattr(socket, "create_connection", limited)
    with pytest.raises(SqlServerNetworkAuthError) as error:
        connect_network(database="", **_options(tds_endpoint))
    assert error.value.code == "sqlserver_routing_blocked"
    assert opened == [("127.0.0.1", tds_endpoint["port"])]
    assert tds_endpoint["state"]["authenticated"] == [r"TEST\account"]


def test_tls_name_mismatch_stops_before_network_credentials(tds_endpoint):
    options = _options(tds_endpoint)
    options["_datapyn_server_host"] = "wrong.remote.invalid"
    with pytest.raises(Exception, match="certificate verify failed"):
        connect_network(database="", **options)
    assert tds_endpoint["state"]["authenticated"] == []
    assert tds_endpoint["state"]["logins"] == []


def test_explicit_trust_certificate_keeps_tls_and_original_sni(tds_endpoint):
    options = _options(tds_endpoint, trust_server_certificate=True)
    options["_datapyn_server_host"] = "explicit-trust.remote.invalid"
    connection = connect_network(database="", **options)
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            assert cursor.fetchone() == (1,)
        assert tds_endpoint["state"]["authenticated"] == [r"TEST\account"]
        assert tds_endpoint["tls"]["sni"] == ["explicit-trust.remote.invalid"]
    finally:
        connection.close()


def test_parallel_physical_ntlm_connections_keep_independent_user_contexts(tds_endpoint):
    def open_and_select(index):
        options = _options(tds_endpoint)
        if index % 2:
            options["_datapyn_username"], options["_datapyn_password"] = r"TEST\second", "second-secret"
        connection = connect_network(database="", **options)
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
                return cursor.fetchone()
        finally:
            connection.close()
    with ThreadPoolExecutor(max_workers=4) as executor:
        assert list(executor.map(open_and_select, range(4))) == [(1,)] * 4
    assert sorted(tds_endpoint["state"]["authenticated"]) == [r"TEST\account", r"TEST\account", r"TEST\second", r"TEST\second"]
    assert len(tds_endpoint["state"]["queries"]) == 4
    assert not tds_endpoint["state"]["errors"]


def test_real_tds_sqlalchemy_connector_batches_temp_export_and_cancel(local_ssh, trust, tds_endpoint):
    import pandas as pd
    from src.database.database_connector import DatabaseConnector
    from datapyn_runtime.table_export import export_table

    local_ssh.destination_port = tds_endpoint["port"]
    trust.confirm(local_ssh.details())
    connector = DatabaseConnector()
    assert connector.connect("sqlserver", "db.remote.invalid", tds_endpoint["port"], "sample", r"TEST\account", "network-secret",
                             sqlserver_auth_mode="ntlm", ssl_ca=tds_endpoint["tls"]["certificate"],
                             ssh=local_ssh.config(), _ssh_trust_path=str(trust.path))
    try:
        assert connector.execute_query("SELECT 1").iloc[0, 0] == 1
        results = connector.execute_query("SELECT 1\nGO\nSELECT 1")
        assert len(results) == 2 and all(frame.iloc[0, 0] == 1 for frame in results)
        assert connector.execute_query("PRINT 'progress'; SELECT 1").iloc[0, 0] == 1
        exported = export_table(pd.DataFrame({"value": [1, 2, 3], "label": ["a", "b", "c"]}),
                                {"table": "#network_test", "temporary": True, "chunksize": 100}, connector)
        assert exported["row_count"] == 3
        assert connector.has_temporary_tables and connector.execute_query("SELECT 1").iloc[0, 0] == 1
        with connector.engine.connect() as connection:
            # The custom dialect's autocommit path uses pytds's property.
            connection.execution_options(isolation_level="AUTOCOMMIT")
            assert connection.connection.autocommit is True
        assert any("CREATE TABLE".encode("utf-16le") in packet for packet in tds_endpoint["state"]["packets"])
        assert any("INSERT INTO".encode("utf-16le") in packet for packet in tds_endpoint["state"]["packets"])
        from src.database.database_connector import OperationCancelled
        with ThreadPoolExecutor(max_workers=1) as executor:
            execution = executor.submit(connector.execute_query, "WAITFOR DELAY '00:00:20'")
            assert tds_endpoint["state"]["waiting"].wait(2)
            cancelled_before = tds_endpoint["state"]["cancelled"]
            connector.cancel_query()
            with pytest.raises(OperationCancelled):
                execution.result(timeout=2)
        assert tds_endpoint["state"]["cancelled"] == cancelled_before + 1
        assert not tds_endpoint["state"]["errors"]
    finally:
        tunnel = connector._ssh_tunnel
        connector.disconnect()
        assert not tunnel.is_alive()
