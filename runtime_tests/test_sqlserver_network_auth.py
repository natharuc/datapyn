"""SQL Server auth selects the real protocol, with no network/OS credentials."""

from types import SimpleNamespace
from unittest.mock import MagicMock
import traceback
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import create_engine

from src.database import database_connector as connector_module
from src.database import sqlserver_network_auth as module


@pytest.mark.parametrize("platform,windows", [("win32", True), ("linux", False), ("darwin", False)])
def test_authentication_capabilities_and_windows_eligibility(monkeypatch, platform, windows):
    monkeypatch.setattr(module.sys, "platform", platform)
    capabilities = module.sqlserver_authentication_capabilities()
    assert ("windows" in capabilities["modes"]) is windows
    assert all(mode in capabilities["modes"] for mode in ("ntlm", "kerberos", "sql_password", "entra_mfa"))
    if not windows:
        with pytest.raises(module.SqlServerNetworkAuthError, match="apenas no Windows"):
            connector_module.DatabaseConnector()._build_connection_string(
                "sqlserver", "server.example", 1433, "sample", "user", "secret",
                driver="ODBC Driver 18 for SQL Server", sqlserver_auth_mode="windows")


@pytest.mark.parametrize("auth,user", [("ntlm", r"DOMAIN\account"), ("kerberos", "account@DOMAIN.EXAMPLE")])
def test_network_auth_dialect_is_offline_and_password_never_in_url(auth, user):
    url, options = connector_module.DatabaseConnector()._build_connection_string(
        "sqlserver", "sql.example", 1433, "sample", user, "network-only-secret",
        sqlserver_auth_mode=auth, trust_server_certificate=True)
    assert url.drivername == "mssql+datapyn_tds"
    assert url.username is None and url.password is None
    assert "network-only-secret" not in str(url)
    assert options["_datapyn_auth_mode"] == auth
    assert options["_datapyn_username"] == user
    assert options["_datapyn_password"] == "network-only-secret"
    engine = create_engine(url, connect_args=options)
    try:
        assert engine.dialect.name == "mssql" and engine.dialect.driver == "datapyn_tds"
        assert engine.pool.checkedout() == 0
    finally:
        engine.dispose()


@pytest.mark.parametrize("mode,user,password,hint", [
    ("ntlm", "user", "secret", "DOMÍNIO"), ("ntlm", "DOMAIN\\", "secret", "DOMÍNIO"),
    ("kerberos", "user", "secret", "REALM"), ("kerberos", "user@", "secret", "REALM"),
    ("ntlm", r"DOMAIN\user", "", "senha"), ("kerberos", "", "secret", "usuário"),
])
def test_missing_or_ambiguous_network_credentials_fail_before_io(monkeypatch, mode, user, password, hint):
    network = MagicMock(side_effect=AssertionError("Must validate before socket"))
    monkeypatch.setattr(module.socket, "create_connection", network)
    with pytest.raises(module.SqlServerNetworkAuthError, match=hint):
        module.network_connect_options(mode, "sql.example", 1433, user, password)
    network.assert_not_called()


@pytest.mark.parametrize("encryption", [False, "no", "optional", "strict"])
def test_explicit_network_auth_never_disables_tls_or_downgrades_tds(encryption):
    with pytest.raises(module.SqlServerNetworkAuthError, match="TLS"):
        module.network_connect_options("ntlm", "sql.example", 1433, r"DOMAIN\user", "secret", encrypt=encryption)


def test_missing_kerberos_provider_does_not_attempt_ntlm_sql_or_socket(monkeypatch):
    monkeypatch.setattr(module, "sqlserver_authentication_capabilities", lambda: {"kerberos_available": False})
    network = MagicMock(side_effect=AssertionError("No connection before prerequisite"))
    monkeypatch.setattr(module.socket, "create_connection", network)
    options = module.network_connect_options("kerberos", "sql.example", 1433, "user@DOMAIN.EXAMPLE", "secret")
    with pytest.raises(module.SqlServerNetworkAuthError) as error:
        module.connect_network(database="sample", **options)
    assert error.value.code == "sqlserver_auth_unavailable"
    network.assert_not_called()


def test_unvalidated_tds_version_fails_before_any_socket(monkeypatch):
    monkeypatch.setattr(module.importlib.metadata, "version", lambda _name: "future-unvalidated")
    network = MagicMock(side_effect=AssertionError("No network with incompatible private API"))
    monkeypatch.setattr(module.socket, "create_connection", network)
    options = module.network_connect_options("ntlm", "sql.example", 1433, r"DOMAIN\user", "secret")
    with pytest.raises(module.SqlServerNetworkAuthError, match="versão do driver"):
        module.connect_network(database="sample", **options)
    network.assert_not_called()


def test_network_driver_keeps_ssh_endpoint_and_original_tls_spn_names():
    url, options = connector_module.DatabaseConnector()._build_connection_string(
        "sqlserver", "127.0.0.1", 49881, "sample", r"DOMAIN\user", "secret",
        sqlserver_auth_mode="ntlm", _ssh_original_host="remote.sql.example", _ssh_original_port=1433)
    assert (url.host, url.port) == ("127.0.0.1", 49881)
    assert (options["_datapyn_route_host"], options["_datapyn_route_port"]) == ("127.0.0.1", 49881)
    assert (options["_datapyn_server_host"], options["_datapyn_server_port"]) == ("remote.sql.example", 1433)


def test_parameter_adapter_preserves_literal_comments_and_identifier_question_marks():
    query = "DECLARE @v INT = ?; SELECT '?' AS [x?], '100%' WHERE x = ? /* ? */ -- ?\n"
    sql, values = module.qmark_to_pyformat(query, [10, 20])
    assert sql == "DECLARE @v INT = %s; SELECT '?' AS [x?], '100%%' WHERE x = %s /* ? */ -- ?\n"
    assert values == (10, 20)
    with pytest.raises(ValueError, match="parameter count"):
        module.qmark_to_pyformat("SELECT ?", [])


def test_raw_execution_parameters_retain_existing_odbc_and_tds_forms():
    connector = connector_module.DatabaseConnector()
    cursor = MagicMock()
    connector.engine = SimpleNamespace(dialect=SimpleNamespace(driver="pyodbc"))
    connector._execute_sqlserver_cursor(cursor, "SELECT ?", [7])
    cursor.execute.assert_called_once_with("SELECT ?", 7)
    cursor.reset_mock()
    connector.engine.dialect.driver = "datapyn_tds"
    connector._execute_sqlserver_cursor(cursor, "SELECT ?", [7])
    cursor.execute.assert_called_once_with("SELECT %s", (7,))


def test_tds_auth_dialect_correctly_sets_autocommit_and_executes_raw_hooks():
    from src.database.sqlserver_network_auth import register_network_dialect
    register_network_dialect()
    from src.database.sqlserver_network_dialect import DataPynTdsDialect
    dialect = DataPynTdsDialect()
    connection = SimpleNamespace(autocommit=False)
    dialect.set_isolation_level(connection, "AUTOCOMMIT")
    assert connection.autocommit is True
    cursor = MagicMock()
    dialect.do_execute(cursor, "SELECT 1", (), context=None)
    cursor.execute.assert_called_once_with("SELECT 1", ())


def test_network_dbapi_error_types_cover_batch_results_and_exports():
    import pyodbc
    import pytds
    connector = connector_module.DatabaseConnector()
    connector.engine = SimpleNamespace(dialect=SimpleNamespace(driver="datapyn_tds"))
    assert connector._sqlserver_driver_errors() == (pyodbc.Error, pytds.Error)


@pytest.mark.parametrize("ssl_ca", ["missing-ca.pem"])
def test_missing_ca_fails_clearly(ssl_ca):
    with pytest.raises(module.SqlServerNetworkAuthError, match="CA PEM"):
        module.network_connect_options("ntlm", "sql.example", 1433, r"DOMAIN\user", "secret", ssl_ca=ssl_ca)


def test_kerberos_context_uses_explicit_credentials_exact_protocol_and_tls_binding(monkeypatch):
    import spnego
    certificate = MagicMock()
    certificate.signature_hash_algorithm = None
    certificate.public_bytes.return_value = b"isolated-certificate"
    auth = module._NetworkAuth("kerberos", "alice@CORP.EXAMPLE", "network-secret", "sql.corp.example", 1433,
                               lambda: SimpleNamespace(to_cryptography=lambda: certificate))
    context = MagicMock()
    context.step.return_value = b"kerberos-token"
    factory = MagicMock(return_value=context)
    monkeypatch.setattr(spnego, "client", factory)
    assert auth.create_packet() == b"kerberos-token"
    fields = factory.call_args.kwargs
    assert fields["protocol"] == "kerberos"
    assert fields["username"] == "alice@CORP.EXAMPLE" and fields["password"] == "network-secret"
    assert fields["service"] == "MSSQLSvc" and fields["hostname"] == "sql.corp.example:1433"
    assert fields["channel_bindings"].application_data.startswith(b"tls-server-end-point:")
    auth.close()
    assert auth.context is None and auth.username == auth.password == ""


def test_auth_provider_error_does_not_expose_credentials_or_retry_protocol(monkeypatch):
    import spnego
    certificate = MagicMock()
    certificate.signature_hash_algorithm = None
    certificate.public_bytes.return_value = b"isolated-certificate"
    factory = MagicMock(side_effect=RuntimeError("Native failure network-secret"))
    monkeypatch.setattr(spnego, "client", factory)
    auth = module._NetworkAuth("kerberos", "alice@CORP.EXAMPLE", "network-secret", "sql.example", 1433,
                               lambda: SimpleNamespace(to_cryptography=lambda: certificate))
    with pytest.raises(module.SqlServerNetworkAuthError) as error:
        auth.create_packet()
    assert "network-secret" not in "".join(traceback.format_exception(error.value))
    assert factory.call_count == 1 and factory.call_args.kwargs["protocol"] == "kerberos"


def test_certificate_names_use_san_before_cn_and_support_multiple_san_and_ip():
    from cryptography import x509
    from cryptography.x509.oid import NameOID
    import ipaddress
    from datetime import datetime, timedelta, timezone
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import rsa
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "wrong-cn.example")])
    certificate = (x509.CertificateBuilder().subject_name(subject).issuer_name(subject).public_key(key.public_key())
                   .serial_number(x509.random_serial_number()).not_valid_before(datetime.now(timezone.utc))
                   .not_valid_after(datetime.now(timezone.utc) + timedelta(days=1))
                   .add_extension(x509.SubjectAlternativeName([x509.DNSName("first.example"), x509.DNSName("sql.example"),
                                                              x509.DNSName("*.corp.example"), x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]), False)
                   .sign(key, hashes.SHA256()))
    assert module._certificate_matches_hostname(certificate, "SQL.EXAMPLE")
    assert module._certificate_matches_hostname(certificate, "sql.corp.example")
    assert module._certificate_matches_hostname(certificate, "127.0.0.1")
    assert not module._certificate_matches_hostname(certificate, "wrong-cn.example")
    assert not module._certificate_matches_hostname(certificate, "deep.sql.corp.example")


def test_real_tds_cursor_messages_keep_print_and_low_severity_informative():
    from pytds.cursor import NonMarsCursor
    from pytds import tds_base
    cursor = NonMarsCursor.__new__(NonMarsCursor)
    messages = [{"marker": tds_base.TDS_INFO_TOKEN, "msgno": 0, "state": 1, "severity": severity,
                 "sql_state": None, "priv_msg_type": 0, "message": "progress", "server": "test",
                 "proc_name": "", "line_number": 1} for severity in (0, 10)]
    cursor._session = SimpleNamespace(messages=messages)
    connector = connector_module.DatabaseConnector()
    connector.engine = SimpleNamespace(dialect=SimpleNamespace(driver="datapyn_tds"))
    assert connector._sqlserver_deferred_error(cursor) is None
    messages.append({**messages[0], "marker": tds_base.TDS_ERROR_TOKEN, "severity": 16, "message": "real SQL failure"})
    assert connector._sqlserver_deferred_error(cursor) == "real SQL failure"


def test_cancel_during_real_multipart_writer_aborts_without_corrupting_packet_type():
    from pytds.tds_writer import _TdsWriter
    from pytds import tds_base
    entered, released = threading.Event(), threading.Event()
    class BlockingTransport:
        closed = False
        packets = []
        def sendall(self, data):
            self.packets.append(bytes(data))
            entered.set()
            assert released.wait(2)
            if self.closed:
                raise OSError("transport interrupted")
        def shutdown(self, _how):
            self.closed = True
            released.set()
        def close(self):
            self.closed = True
            released.set()
    transport = BlockingTransport()
    connection = SimpleNamespace(_datapyn_aborted=False)
    original = _TdsWriter(transport=transport, bufsize=32, tds_session=SimpleNamespace())
    writer = module._SerializedTdsWriter(original, transport, connection)
    session = SimpleNamespace(_writer=writer, in_cancel=False)
    def put_cancel():
        writer.begin_packet(tds_base.PacketType.CANCEL)
        writer.flush()
        session.in_cancel = True
    session.put_cancel = put_cancel
    cursor = SimpleNamespace(_session=session)
    connector = connector_module.DatabaseConnector()
    connector.db_type = "sqlserver"
    connector.engine = SimpleNamespace(dialect=SimpleNamespace(driver="datapyn_tds"))
    connector._active_cursor = cursor
    def send_query():
        writer.begin_packet(tds_base.PacketType.QUERY)
        writer.write(b"multipart SQL" * 20)
        writer.flush()
    with ThreadPoolExecutor(max_workers=1) as executor:
        sending = executor.submit(send_query)
        assert entered.wait(1)
        connector.cancel_query()
        with pytest.raises(OSError, match="transport interrupted"):
            sending.result(timeout=1)
    assert transport.closed and connection._datapyn_aborted
    assert not session.in_cancel
    assert transport.packets and all(packet[0] == tds_base.PacketType.QUERY for packet in transport.packets)
    assert original._type == tds_base.PacketType.QUERY


def test_aborted_network_transport_is_invalidated_before_pool_reuse():
    physical = SimpleNamespace(_tds_socket=SimpleNamespace(_datapyn_aborted=True))
    raw = MagicMock(driver_connection=physical)
    connector = connector_module.DatabaseConnector()
    connector._close_sqlserver_raw_connection(raw)
    raw.invalidate.assert_called_once_with()
    raw.close.assert_called_once_with()


@pytest.mark.parametrize("method", ["write", "write_ucs2", "pack"])
def test_failed_real_multipart_write_discards_transport_and_releases_request_lock(method):
    import struct
    from pytds.tds_writer import _TdsWriter
    from pytds import tds_base
    class FailedTransport:
        closed = False
        def sendall(self, _data):
            raise OSError("server dropped while sending")
        def shutdown(self, _how):
            self.closed = True
        def close(self):
            self.closed = True
    transport = FailedTransport()
    connection = SimpleNamespace(_datapyn_aborted=False)
    writer = module._SerializedTdsWriter(_TdsWriter(transport, 32, SimpleNamespace()), transport, connection)
    writer.begin_packet(tds_base.PacketType.QUERY)
    with pytest.raises(OSError, match="server dropped"):
        if method == "write":
            writer.write(b"x" * 100)
        elif method == "write_ucs2":
            writer.write_ucs2("x" * 100)
        else:
            writer.pack(struct.Struct("100s"), b"x" * 100)
    assert transport.closed and connection._datapyn_aborted
    assert writer._owner is None
    def probe():
        acquired = writer._lock.acquire(blocking=False)
        if acquired:
            writer._lock.release()
        return acquired
    with ThreadPoolExecutor(max_workers=1) as executor:
        assert executor.submit(probe).result(timeout=1)
