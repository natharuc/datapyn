"""Database routing, TLS identity and failure cleanup over native SSH."""

from datetime import datetime, timedelta, timezone
import socket
import socketserver
import ssl
import struct
import threading
from unittest.mock import MagicMock
from urllib.parse import unquote_plus

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
import pytest
import sqlalchemy

from datapyn_runtime.ssh_tunnel import SshTunnelError
from src.database import database_connector as module
from test_ssh_tunnel import local_ssh, trust


@pytest.fixture
def fake_tunnel(monkeypatch):
    class Tunnel:
        instances = []
        local_host = "127.0.0.1"
        local_port = 49123
        error = None

        def __init__(self, config, host, port, **kwargs):
            self.destination = (host, port)
            self.trust_path = kwargs["trust_store"].path
            self.started = False
            self.closed = False
            self.instances.append(self)

        def start(self):
            self.started = True
            return self

        def close(self):
            self.closed = True

        def is_alive(self):
            return self.started and not self.closed

    monkeypatch.setattr("datapyn_runtime.ssh_tunnel.SshTunnel", Tunnel)
    return Tunnel


def test_postgres_driver_routes_by_hostaddr_and_preserves_tls_hostname(monkeypatch, fake_tunnel, tmp_path):
    engine = MagicMock()
    factory = MagicMock(return_value=engine)
    monkeypatch.setattr(module, "create_engine", factory)
    connection = module.DatabaseConnector()
    config = {"enabled": True, "host": "ssh.example", "username": "ssh-user", "password": "ssh-secret"}
    trust_path = tmp_path / "trust.json"
    assert connection.connect("postgresql", "postgres.internal.example", 5432, "docfis", "db-user", "db-secret",
                              ssh=config, _ssh_trust_path=str(trust_path), sslmode="verify-full", sslrootcert="ca.pem", sslcert="client.pem", sslkey="client.key")
    url = sqlalchemy.engine.make_url(factory.call_args.args[0])
    args = factory.call_args.kwargs["connect_args"]
    assert (url.host, url.port) == ("postgres.internal.example", 49123)
    assert args["hostaddr"] == "127.0.0.1"
    assert (args["sslmode"], args["sslrootcert"], args["sslcert"], args["sslkey"]) == ("verify-full", "ca.pem", "client.pem", "client.key")
    assert connection.connection_params["host"] == "postgres.internal.example"
    assert connection.connection_params["port"] == 5432
    assert connection._connection_config["host"] == "postgres.internal.example"
    assert connection._connection_config["port"] == 5432
    assert connection._connection_config["ssh"] == config
    assert fake_tunnel.instances[0].destination == ("postgres.internal.example", 5432)
    assert fake_tunnel.instances[0].trust_path == trust_path
    connection.disconnect()
    assert fake_tunnel.instances[0].closed


@pytest.mark.parametrize("error", [RuntimeError("database login failed"), KeyboardInterrupt()])
def test_database_failure_or_cancellation_closes_tunnel_and_engine(monkeypatch, fake_tunnel, error):
    engine = MagicMock()
    engine.connect.side_effect = error
    monkeypatch.setattr(module, "create_engine", lambda *args, **kwargs: engine)
    connection = module.DatabaseConnector()
    with pytest.raises(type(error)):
        connection.connect("postgresql", "db.example", 5432, "db", ssh={"enabled": True})
    assert fake_tunnel.instances[0].closed
    engine.dispose.assert_called_once()
    assert not connection.is_connected()


def test_engine_creation_failure_cleans_tunnel_without_direct_retry(monkeypatch, fake_tunnel):
    factory = MagicMock(side_effect=RuntimeError("driver failed"))
    monkeypatch.setattr(module, "create_engine", factory)
    connection = module.DatabaseConnector()
    with pytest.raises(RuntimeError, match="driver failed"):
        connection.connect("postgresql", "db.example", 5432, "db", ssh={"enabled": True})
    assert fake_tunnel.instances[0].closed
    assert factory.call_count == 1


def test_disconnect_closes_ssh_even_if_engine_disposal_fails(fake_tunnel):
    connection = module.DatabaseConnector()
    connection.engine = MagicMock()
    connection.engine.dispose.side_effect = RuntimeError("dispose failed")
    tunnel = fake_tunnel({}, "db.example", 5432, trust_store=MagicMock())
    connection._ssh_tunnel = tunnel
    with pytest.raises(RuntimeError, match="dispose failed"):
        connection.disconnect()
    assert tunnel.closed and connection.engine is None


def test_force_disconnect_closes_tunnel_even_when_driver_cannot_dispose(fake_tunnel):
    connection = module.DatabaseConnector()
    connection.engine = MagicMock()
    connection.engine.dispose.side_effect = RuntimeError("dispose failed")
    tunnel = fake_tunnel({}, "db.example", 5432, trust_store=MagicMock())
    connection._ssh_tunnel = tunnel
    connection.force_disconnect()
    assert tunnel.closed and connection.engine is None and not connection.is_connected()


def test_admin_cancel_connection_keeps_ssh_options_and_never_uses_direct_helper(monkeypatch):
    parent = module.DatabaseConnector()
    config = {"db_type": "mysql", "host": "db.internal", "port": 3306, "database": "data",
              "password": "db-secret", "ssh": {"enabled": True, "host": "ssh.example", "password": "ssh-secret"},
              "_ssh_trust_path": "trusted.json", "ssl_verify_identity": True}
    parent._connection_config = config
    admin = MagicMock()
    factory = MagicMock(return_value=admin)
    direct = MagicMock(side_effect=AssertionError("Must never connect directly"))
    monkeypatch.setattr(module, "DatabaseConnector", factory)
    monkeypatch.setattr("src.database.block_connector_pool.connect_connector_from_config", direct)
    created, raw = parent._spawn_admin_connection()
    assert created is admin and raw is admin.engine.raw_connection.return_value
    admin.connect.assert_called_once_with(**config)
    direct.assert_not_called()


def test_reconfiguring_ssh_connection_as_direct_closes_old_tunnel(monkeypatch, fake_tunnel):
    connection = module.DatabaseConnector()
    connection.engine = MagicMock()
    old = fake_tunnel({}, "db.example", 5432, trust_store=MagicMock())
    connection._ssh_tunnel = old
    factory = MagicMock(return_value=MagicMock())
    monkeypatch.setattr(module, "create_engine", factory)
    assert connection.connect("postgresql", "db.example", 5432, "db", ssh={"enabled": False})
    assert old.closed and connection._ssh_tunnel is None
    assert sqlalchemy.engine.make_url(factory.call_args.args[0]).port == 5432


def test_ssh_disabled_preserves_direct_connection_and_tls_options(monkeypatch, fake_tunnel):
    engine = MagicMock()
    factory = MagicMock(return_value=engine)
    monkeypatch.setattr(module, "create_engine", factory)
    connection = module.DatabaseConnector()
    assert connection.connect("postgresql", "db.example", 5432, "db", ssh={"enabled": False}, sslmode="require")
    url = sqlalchemy.engine.make_url(factory.call_args.args[0])
    assert (url.host, url.port) == ("db.example", 5432)
    assert "hostaddr" not in factory.call_args.kwargs["connect_args"]
    assert factory.call_args.kwargs["connect_args"]["sslmode"] == "require"
    assert fake_tunnel.instances == []


def test_sqlserver_preserves_remote_certificate_identity_with_driver_18(monkeypatch, fake_tunnel):
    factory = MagicMock(return_value=MagicMock())
    monkeypatch.setattr(module, "create_engine", factory)
    connection = module.DatabaseConnector()
    assert connection.connect("sqlserver", "sql.example", 1433, "db", "user", "secret",
                              ssh={"enabled": True}, driver="ODBC Driver 18 for SQL Server")
    odbc = unquote_plus(factory.call_args.args[0])
    assert "SERVER=127.0.0.1,49123" in odbc
    assert "HostNameInCertificate={sql.example}" in odbc
    assert "TrustServerCertificate=yes" not in odbc
    connection.disconnect()


def test_sqlserver_old_driver_cannot_silently_disable_certificate_validation(monkeypatch, fake_tunnel):
    factory = MagicMock()
    monkeypatch.setattr(module, "create_engine", factory)
    connection = module.DatabaseConnector()
    with pytest.raises(SshTunnelError) as caught:
        connection.connect("sqlserver", "sql.example", 1433, "db", ssh={"enabled": True}, driver="ODBC Driver 17 for SQL Server")
    assert caught.value.code == "ssh_tls_unsupported"
    factory.assert_not_called()
    assert fake_tunnel.instances[0].closed


def test_sqlserver_encryption_option_cannot_inject_a_certificate_bypass():
    connection = module.DatabaseConnector()
    with pytest.raises(ValueError, match="Encrypt option"):
        connection._build_connection_string("sqlserver", "sql.example", 1433, "db", "user", "secret",
                                            driver="ODBC Driver 18 for SQL Server", encrypt="no;TrustServerCertificate=yes")


@pytest.mark.parametrize("db_type,host", [("databricks", "warehouse.example"), ("sqlserver", "(localdb)\\MSSQLLocalDB"), ("sqlserver", "sql.example\\INSTANCE")])
def test_unsupported_tunnel_targets_fail_before_attempting_ssh(fake_tunnel, db_type, host):
    connection = module.DatabaseConnector()
    with pytest.raises(SshTunnelError) as caught:
        connection.connect(db_type, host, 443, "db", ssh={"enabled": True})
    assert caught.value.code == "ssh_database_unsupported"
    assert fake_tunnel.instances == []


def _read_exact(stream, size):
    parts = bytearray()
    while len(parts) < size:
        data = stream.recv(size - len(parts))
        if not data:
            return bytes(parts)
        parts.extend(data)
    return bytes(parts)


def _mysql_packet(payload, sequence):
    return struct.pack("<I", len(payload))[:3] + bytes([sequence]) + payload


@pytest.fixture
def database_tls_server(tmp_path):
    """A TLS-capable PostgreSQL/MySQL endpoint rejects auth after handshake.

    Using the real drivers proves name verification/SNI cross SSH forwarding;
    no actual data service, container, credentials or production is involved.
    """
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "db.remote.invalid")])
    certificate = (x509.CertificateBuilder().subject_name(subject).issuer_name(subject).public_key(private.public_key())
                   .serial_number(x509.random_serial_number()).not_valid_before(datetime.now(timezone.utc) - timedelta(days=1))
                   .not_valid_after(datetime.now(timezone.utc) + timedelta(days=1))
                   .add_extension(x509.SubjectAlternativeName([x509.DNSName("db.remote.invalid")]), critical=False)
                   .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True).sign(private, hashes.SHA256()))
    key_path, cert_path = tmp_path / "server.key", tmp_path / "server.crt"
    key_path.write_bytes(private.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.TraditionalOpenSSL, serialization.NoEncryption()))
    cert_path.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(cert_path, key_path)
    sni, handshakes = [], []
    context.set_servername_callback(lambda stream, name, ssl_context: sni.append(name))
    servers = []

    def start(protocol):
        class Handler(socketserver.BaseRequestHandler):
            def handle(self):
                stream = self.request
                try:
                    stream.settimeout(2)
                    if protocol == "postgresql":
                        data = _read_exact(stream, 8)
                        if not data:  # SSH destination probe closes immediately.
                            return
                        assert data == struct.pack("!II", 8, 80877103)
                        stream.sendall(b"S")
                    else:
                        from pymysql.constants import CLIENT
                        caps = CLIENT.SSL | CLIENT.PROTOCOL_41 | CLIENT.SECURE_CONNECTION | CLIENT.PLUGIN_AUTH
                        handshake = (b"\x0a8.0.0-local\0" + struct.pack("<I", 1) + b"salt1234\0" + struct.pack("<H", caps & 65535)
                                     + b"\x21" + struct.pack("<H", 2) + struct.pack("<H", caps >> 16) + b"\x15" + b"\0" * 10
                                     + b"abcdefghijkl\0mysql_native_password\0")
                        stream.sendall(_mysql_packet(handshake, 0))
                        header = _read_exact(stream, 4)
                        if not header:
                            return
                        size = int.from_bytes(header[:3], "little")
                        request = _read_exact(stream, size)
                        assert len(request) == 32 and struct.unpack("<I", request[:4])[0] & CLIENT.SSL
                    stream = context.wrap_socket(stream, server_side=True)
                    handshakes.append(protocol)
                    if protocol == "postgresql":
                        header = _read_exact(stream, 4)
                        if len(header) != 4:
                            return
                        size = struct.unpack("!I", header)[0]
                        _read_exact(stream, size - 4)
                        error = b"SERROR\0VERROR\0C28000\0Mtest database authentication\0\0"
                        stream.sendall(b"E" + struct.pack("!I", len(error) + 4) + error)
                    else:
                        header = _read_exact(stream, 4)
                        _read_exact(stream, int.from_bytes(header[:3], "little"))
                        error = b"\xff" + struct.pack("<H", 1045) + b"#28000test database authentication"
                        stream.sendall(_mysql_packet(error, 3))
                except (OSError, ssl.SSLError):
                    pass
                finally:
                    stream.close()

        class Server(socketserver.ThreadingTCPServer):
            daemon_threads = True

        server = Server(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        servers.append((server, thread))
        return server.server_address[1]

    try:
        yield {"start": start, "certificate": str(cert_path), "context": context, "sni": sni, "handshakes": handshakes}
    finally:
        for server, thread in servers:
            server.shutdown()
            server.server_close()
            thread.join(timeout=1)


@pytest.mark.parametrize("db_type", ["postgresql", "mysql", "mariadb"])
def test_real_driver_validates_remote_tls_hostname_through_ssh(local_ssh, trust, database_tls_server, db_type):
    protocol = "postgresql" if db_type == "postgresql" else "mysql"
    local_ssh.destination_port = database_tls_server["start"](protocol)
    trust.confirm(local_ssh.details())
    connection = module.DatabaseConnector()
    tls = ({"sslmode": "verify-full", "sslrootcert": database_tls_server["certificate"], "gssencmode": "disable"}
           if db_type == "postgresql" else {"ssl_ca": database_tls_server["certificate"], "ssl_verify_cert": True, "ssl_verify_identity": True})
    with pytest.raises(Exception, match="test database authentication"):
        connection.connect(db_type, "db.remote.invalid", local_ssh.destination_port, "test", "test", "test",
                           ssh=local_ssh.config(), _ssh_trust_path=str(trust.path), **tls)
    assert database_tls_server["sni"] == ["db.remote.invalid"]
    assert database_tls_server["handshakes"] == [protocol]
    assert not connection.is_connected() and connection._ssh_tunnel is None


@pytest.mark.parametrize("db_type", ["postgresql", "mysql", "mariadb"])
def test_real_driver_rejects_remote_certificate_hostname_mismatch(local_ssh, trust, database_tls_server, db_type):
    protocol = "postgresql" if db_type == "postgresql" else "mysql"
    local_ssh.destination_port = database_tls_server["start"](protocol)
    trust.confirm(local_ssh.details())
    connection = module.DatabaseConnector()
    tls = ({"sslmode": "verify-full", "sslrootcert": database_tls_server["certificate"], "gssencmode": "disable"}
           if db_type == "postgresql" else {"ssl_ca": database_tls_server["certificate"], "ssl_verify_cert": True, "ssl_verify_identity": True})
    # The remote SSH fixture routes this accepted hostname; the CA trusts a
    # different name, so validation must reject before any DB auth succeeds.
    # Map only the certificate identity locally in the builder, retaining the
    # server's known forwarding destination for this deliberate negative case.
    original_build = connection._build_connection_string

    def wrong_identity(db, host, port, *args, **kwargs):
        return original_build(db, "wrong.remote.invalid", port, *args, **kwargs)

    connection._build_connection_string = wrong_identity
    with pytest.raises(Exception) as caught:
        connection.connect(db_type, "db.remote.invalid", local_ssh.destination_port, "test", "test", "test",
                           ssh=local_ssh.config(), _ssh_trust_path=str(trust.path), **tls)
    assert "certificate" in str(caught.value).lower()
    assert "test database authentication" not in str(caught.value)
    assert not connection.is_connected()
