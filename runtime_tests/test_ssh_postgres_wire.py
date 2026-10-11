"""Real psycopg2/SQLAlchemy authentication and queries through real SSH/TLS.

The small PostgreSQL wire endpoint runs exclusively on temporary loopback ports.
It implements the startup/query messages the production driver consumes; no
driver, socket, tunnel or SQLAlchemy engine is mocked.
"""

import socket
import socketserver
import ssl
import struct
import threading

import pytest

from src.database.database_connector import DatabaseConnector
from test_ssh_database import _read_exact, database_tls_server
from test_ssh_tunnel import local_ssh, trust


def message(kind, payload=b""):
    return kind + struct.pack("!I", len(payload) + 4) + payload


def rows(columns, values):
    description = struct.pack("!h", len(columns))
    for name, oid in columns:
        description += name.encode() + b"\0" + struct.pack("!IhIhih", 0, 0, oid, 4 if oid == 23 else -1, -1, 0)
    output = message(b"T", description)
    for row in values:
        payload = struct.pack("!h", len(row))
        for value in row:
            if value is None:
                payload += struct.pack("!i", -1)
            else:
                encoded = str(value).encode("utf-8")
                payload += struct.pack("!I", len(encoded)) + encoded
        output += message(b"D", payload)
    return output + message(b"C", f"SELECT {len(values)}".encode() + b"\0")


def read_message(stream):
    kind = _read_exact(stream, 1)
    if not kind:
        return None, None
    header = _read_exact(stream, 4)
    if len(header) != 4:
        return None, None
    size = struct.unpack("!I", header)[0]
    return kind, _read_exact(stream, size - 4)


class PostgresWireServer(socketserver.ThreadingTCPServer):
    daemon_threads = True

    def __init__(self, tls_context):
        owner = self
        self.accepted_logins = 0
        self.rejected_logins = 0
        self.queries = []
        self.active_streams = set()
        self.lock = threading.RLock()
        self.wire_errors = []

        class Handler(socketserver.BaseRequestHandler):
            def handle(self):
                stream = self.request
                with owner.lock:
                    owner.active_streams.add(stream)
                try:
                    stream.settimeout(3)
                    ssl_request = _read_exact(stream, 8)
                    if not ssl_request:
                        return  # The SSH destination probe disconnects.
                    if ssl_request != struct.pack("!II", 8, 80877103):
                        raise ValueError("Expected TLS request")
                    stream.sendall(b"S")
                    original = stream
                    stream = tls_context.wrap_socket(stream, server_side=True)
                    with owner.lock:
                        owner.active_streams.discard(original)
                        owner.active_streams.add(stream)
                    header = _read_exact(stream, 4)
                    if len(header) != 4:
                        return
                    startup = _read_exact(stream, struct.unpack("!I", header)[0] - 4)
                    if not startup or struct.unpack("!I", startup[:4])[0] != 196608:
                        raise ValueError("Expected PostgreSQL 3 startup")
                    stream.sendall(message(b"R", struct.pack("!I", 3)))
                    kind, password = read_message(stream)
                    if kind != b"p" or password != b"pg-secret\0":
                        with owner.lock:
                            owner.rejected_logins += 1
                        error = b"SFATAL\0VFATAL\0C28P01\0Mpassword authentication failed\0\0"
                        stream.sendall(message(b"E", error))
                        return
                    with owner.lock:
                        owner.accepted_logins += 1
                    startup_reply = message(b"R", struct.pack("!I", 0))
                    for key, value in {"server_version": "15.0", "server_encoding": "UTF8", "client_encoding": "UTF8",
                                       "DateStyle": "ISO, MDY", "TimeZone": "UTC", "integer_datetimes": "on",
                                       "standard_conforming_strings": "on"}.items():
                        startup_reply += message(b"S", key.encode() + b"\0" + value.encode() + b"\0")
                    startup_reply += message(b"K", struct.pack("!II", 12345, 67890)) + message(b"Z", b"I")
                    stream.sendall(startup_reply)
                    transaction = False
                    while True:
                        kind, payload = read_message(stream)
                        if kind is None or kind == b"X":
                            return
                        if kind != b"Q":
                            raise ValueError("Unexpected wire message")
                        query = payload.rstrip(b"\0").decode("utf-8")
                        with owner.lock:
                            owner.queries.append(query)
                        normalized = " ".join(query.lower().strip().rstrip(";").split())
                        if normalized in {"begin", "begin transaction"}:
                            transaction = True
                            response = message(b"C", b"BEGIN\0")
                        elif normalized in {"rollback", "commit"}:
                            transaction = False
                            response = message(b"C", normalized.upper().encode() + b"\0")
                        elif normalized.startswith("set "):
                            response = message(b"C", b"SET\0")
                        elif "pg_catalog.version()" in normalized:
                            response = rows([("version", 25)], [("PostgreSQL 15.0 on local wire test, compiled for tests",)])
                        elif "current_schema()" in normalized:
                            response = rows([("current_schema", 25)], [("public",)])
                        elif normalized == "show transaction isolation level":
                            response = rows([("transaction_isolation", 25)], [("read committed",)])
                        elif normalized == "show standard_conforming_strings":
                            response = rows([("standard_conforming_strings", 25)], [("on",)])
                        elif "pg_type" in normalized and "hstore" in normalized:
                            response = rows([("oid", 23), ("typarray", 23)], [])
                        elif normalized == "select 1":
                            response = rows([("?column?", 23)], [(1,)])
                        else:
                            raise ValueError(f"Unexpected test query: {query}")
                        stream.sendall(response + message(b"Z", b"T" if transaction else b"I"))
                except (OSError, ssl.SSLError):
                    pass
                except Exception as exc:
                    owner.wire_errors.append(type(exc).__name__)
                finally:
                    stream.close()
                    with owner.lock:
                        owner.active_streams.discard(stream)

        super().__init__(("127.0.0.1", 0), Handler)

    def close(self):
        self.shutdown()
        self.server_close()
        with self.lock:
            connections = list(self.active_streams)
        for stream in connections:
            try:
                stream.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            stream.close()


@pytest.fixture
def postgres_wire(database_tls_server):
    server = PostgresWireServer(database_tls_server["context"])
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.close()
        thread.join(timeout=1)


def connect_postgres(connection, ssh, trust, endpoint, tls, password="pg-secret"):
    return connection.connect("postgresql", "db.remote.invalid", endpoint.server_address[1], "docfis", "pg-test", password,
                              ssh=ssh.config(), _ssh_trust_path=str(trust.path),
                              sslmode="verify-full", sslrootcert=tls["certificate"], gssencmode="disable")


def test_real_postgres_authentication_select_and_disconnect_through_ssh(local_ssh, trust, postgres_wire, database_tls_server):
    local_ssh.destination_port = postgres_wire.server_address[1]
    trust.confirm(local_ssh.details())
    connection = DatabaseConnector()
    try:
        assert connect_postgres(connection, local_ssh, trust, postgres_wire, database_tls_server)
        assert connection.is_connected()
        tunnel = connection._ssh_tunnel
        result = connection.execute_query("SELECT 1")
        assert result.iloc[0, 0] == 1
        assert postgres_wire.accepted_logins == 1
        assert sum(query.strip().upper() == "SELECT 1" for query in postgres_wire.queries) >= 2
        assert postgres_wire.wire_errors == []
        assert database_tls_server["sni"] == ["db.remote.invalid"]
        assert connection.connection_params["host"] == "db.remote.invalid"
        assert connection.connection_params["port"] == postgres_wire.server_address[1]
        port = tunnel.local_port
    finally:
        connection.disconnect()
    assert not tunnel.is_alive() and not connection.is_connected()
    with pytest.raises(OSError):
        socket.create_connection(("127.0.0.1", port), timeout=0.2)


def test_real_postgres_wrong_database_password_cleans_authenticated_ssh(local_ssh, trust, postgres_wire, database_tls_server, caplog):
    local_ssh.destination_port = postgres_wire.server_address[1]
    trust.confirm(local_ssh.details())
    connection = DatabaseConnector()
    with pytest.raises(Exception, match="password authentication failed"):
        connect_postgres(connection, local_ssh, trust, postgres_wire, database_tls_server, password="wrong-pg-secret")
    assert postgres_wire.rejected_logins == 1 and postgres_wire.accepted_logins == 0
    assert local_ssh.auth == [("tester", "password")]
    assert postgres_wire.queries == []
    assert postgres_wire.wire_errors == []
    assert connection._ssh_tunnel is None and not connection.is_connected()
    assert "wrong-pg-secret" not in caplog.text and "ssh-secret" not in caplog.text
