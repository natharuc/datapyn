"""Explicit SQL Server network authentication, separate from SQL logins.

Microsoft ODBC uses an existing OS identity for Trusted_Connection.  This
adapter uses a fresh SPNEGO context for each physical TDS connection so an
explicit network account never becomes a SQL username or another tab's login.
"""

from __future__ import annotations

import importlib.util
import importlib.metadata
import ipaddress
import os
from pathlib import Path
import socket
import sys
import threading
import uuid


class SqlServerNetworkAuthError(ConnectionError):
    def __init__(self, message: str, *, code="sqlserver_auth_configuration"):
        super().__init__(message)
        self.code = code


def sqlserver_authentication_capabilities() -> dict:
    platform = "windows" if sys.platform == "win32" else "macos" if sys.platform == "darwin" else "linux"
    modes = ["sql_password"]
    if platform == "windows":
        modes.append("windows")
    modes.extend(("ntlm", "kerberos", "entra_mfa"))
    kerberos_available = (
        importlib.util.find_spec("sspilib") is not None if platform == "windows"
        else all(importlib.util.find_spec(name) is not None for name in ("gssapi", "krb5"))
    )
    return {"platform": platform, "modes": modes, "kerberos_available": kerberos_available,
            "network_tls_ca_field": "ssl_ca"}


def _credentials(auth_mode: str, username: str, password: str) -> tuple[str, str]:
    user = str(username or "").strip()
    if not user or not password:
        raise SqlServerNetworkAuthError("Informe o usuário e a senha de rede para autenticação " + auth_mode.upper() + ".")
    if auth_mode == "ntlm" and ("\\" not in user or not all(user.split("\\", 1))):
        raise SqlServerNetworkAuthError("Para NTLM, informe o usuário no formato DOMÍNIO\\usuário.")
    if auth_mode == "kerberos" and ("@" not in user or not all(user.rsplit("@", 1))):
        raise SqlServerNetworkAuthError("Para Kerberos, informe o principal no formato usuário@REALM.")
    return user, str(password)


def network_connect_options(auth_mode: str, host: str, port: int, username: str, password: str, **kwargs) -> dict:
    """Validate before any socket/credential request and keep secrets out of URLs."""
    if auth_mode not in {"ntlm", "kerberos"}:
        raise SqlServerNetworkAuthError("Método de autenticação de rede inválido.")
    user, secret = _credentials(auth_mode, username, password)
    if "(localdb)" in str(host).lower() or "\\" in str(host):
        raise SqlServerNetworkAuthError("NTLM/Kerberos requerem o endereço TCP e a porta do SQL Server, sem instância nomeada.")
    encryption = str(kwargs.get("encrypt") if kwargs.get("encrypt") is not None else "yes").lower().strip()
    if encryption not in {"true", "yes", "mandatory"}:
        raise SqlServerNetworkAuthError("NTLM/Kerberos requerem TLS (Encrypt=yes). TDS 8.0/Encrypt=strict não está disponível neste driver.")
    if not isinstance(kwargs.get("trust_server_certificate", False), bool):
        raise SqlServerNetworkAuthError("Confiar no certificado deve ser um valor booleano.")
    import certifi
    ca = str(kwargs.get("ssl_ca") or certifi.where())
    if not Path(ca).is_file():
        raise SqlServerNetworkAuthError("O arquivo CA PEM do SQL Server não foi encontrado.")
    return {"_datapyn_auth_mode": auth_mode, "_datapyn_username": user,
            "_datapyn_password": secret, "_datapyn_server_host": str(kwargs.get("_ssh_original_host") or host),
            "_datapyn_server_port": int(kwargs.get("_ssh_original_port") or port),
            "_datapyn_route_host": str(host), "_datapyn_route_port": int(port),
            "_datapyn_trust_certificate": bool(kwargs.get("trust_server_certificate")),
            "cafile": ca,
            "enc_login_only": False, "login_timeout": 15, "disable_connect_retry": True,
            "pooling": False, "appname": "DataPyn"}


def connect_network(*args, **options):
    """Use the pinned TDS transport without its automatic direct redirects.

    python-tds.connect follows a server routing token using a fresh direct
    socket. Its public interface has no switch for that behavior. Construct
    only the login/socket for the selected endpoint; a redirect fails closed.
    All private interfaces below are pinned to python-tds 1.17.1 and exercised
    by wire-level tests as well as packaged-runtime verification.
    """
    import pytds
    from pytds import lcid, tds_base, tz
    from pytds.connection import NonMarsConnection
    from pytds.row_strategies import tuple_row_strategy
    from pytds.tds_socket import _TdsSocket

    if importlib.metadata.version("python-tds") != "1.17.1":
        raise SqlServerNetworkAuthError("A versão do driver TDS não é compatível com este adaptador. Restaure o runtime do DataPyn.",
                                        code="sqlserver_auth_unavailable")

    options = dict(options)
    autocommit = options.pop("autocommit", False)
    if not isinstance(autocommit, bool):
        raise TypeError("autocommit must be a boolean")
    mode = options.pop("_datapyn_auth_mode")
    user = options.pop("_datapyn_username")
    password = options.pop("_datapyn_password")
    host = options.pop("_datapyn_server_host")
    port = options.pop("_datapyn_server_port")
    route_host = options.pop("_datapyn_route_host")
    route_port = options.pop("_datapyn_route_port")
    trust_certificate = options.pop("_datapyn_trust_certificate")
    # UID/PWD from SQLAlchemy's URL are never allowed to select SQL auth.
    options.pop("user", None)
    options.pop("password", None)
    if mode == "kerberos" and not sqlserver_authentication_capabilities()["kerberos_available"]:
        raise SqlServerNetworkAuthError(
            "Kerberos indisponível: instale/configure as bibliotecas Kerberos do sistema e o realm/KDC. "
            "O DataPyn não substituirá Kerberos por NTLM ou login SQL.", code="sqlserver_auth_unavailable")
    login = tds_base._TdsLogin()
    login.client_host_name = socket.gethostname()[:128]
    login.library = "Python TDS Library / DataPyn"
    login.app_name = "DataPyn"
    login.server_name = host.encode("idna").decode("ascii")
    login.port = port
    login.database = options.get("database", "")
    login.client_lcid = lcid.LANGID_ENGLISH_US
    login.pid, login.client_id = os.getpid(), uuid.getnode()
    login.cafile = options["cafile"]
    login.enc_flag = pytds.PreLoginEnc.ENCRYPT_ON
    # Host verification lives in the per-connection OpenSSL callback. The
    # upstream helper accepts CN before SAN and mishandles multiple SANs.
    login.validate_host = False
    login.enc_login_only = False
    login.client_tz = tz.local
    login.bytes_to_unicode = True
    login.option_flag2 = tds_base.TDS_ODBC_ON
    login.connect_timeout = options.get("login_timeout", 15)
    login.query_timeout = options.get("timeout")
    login.tls_ctx = _tls_context(login.cafile, login.server_name, trust_certificate)
    tds_socket = None
    auth = _NetworkAuth(mode, user, password, login.server_name, port,
                        lambda: tds_socket.sock._tls_conn.get_peer_certificate())
    login.auth = auth
    stream = socket.create_connection((route_host, route_port), timeout=login.connect_timeout)
    try:
        stream.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        stream.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
        stream.settimeout(login.connect_timeout)
        tds_socket = _TdsSocket(sock=stream, login=login, row_strategy=tuple_row_strategy,
                                autocommit=autocommit, isolation_level=0)
        tds_socket.main_session._writer = _SerializedTdsWriter(tds_socket.main_session._writer, stream, tds_socket)
        route = tds_socket.login()
        if route is not None:
            raise SqlServerNetworkAuthError(
                "O SQL Server solicitou um redirecionamento de rede. Cadastre o endpoint final; "
                "a conexão não será desviada para fora do destino ou túnel selecionado.",
                code="sqlserver_routing_blocked")
        if not autocommit:
            tds_socket.main_session.begin_tran()
        tds_socket.sock.settimeout(login.query_timeout)
        return NonMarsConnection(pooling=False, key=(), tds_socket=tds_socket)
    except BaseException:
        if tds_socket is not None:
            try:
                tds_socket.close()
            except Exception:
                pass
        stream.close()
        raise


class _SerializedTdsWriter:
    """Keep every multipart request atomic with respect to Attention writes.

    Only writes are protected. The worker remains the sole response reader,
    so cancelling a query waiting for data never waits for a read lock.
    """

    def __init__(self, writer, stream, connection):
        object.__setattr__(self, "_writer", writer)
        object.__setattr__(self, "_lock", threading.RLock())
        object.__setattr__(self, "_stream", stream)
        object.__setattr__(self, "_connection", connection)
        object.__setattr__(self, "_owner", None)

    def __getattr__(self, name):
        value = getattr(self._writer, name)
        if not callable(value):
            return value
        def write_method(*args, **kwargs):
            try:
                return value(*args, **kwargs)
            except BaseException:
                self._failed_request()
                raise
        return write_method

    def __setattr__(self, name, value):
        setattr(self._writer, name, value)

    def begin_packet(self, kind):
        self._lock.acquire()
        object.__setattr__(self, "_owner", threading.get_ident())
        try:
            self._writer.begin_packet(kind)
        except BaseException:
            self._failed_request()
            raise

    def flush(self):
        if self._owner != threading.get_ident():
            self._lock.acquire()
            object.__setattr__(self, "_owner", threading.get_ident())
        try:
            return self._writer.flush()
        except BaseException:
            self._failed_request()
            raise
        finally:
            self._release_request()

    def write(self, data):
        # The pinned driver writes follow-up SSPI tokens without calling
        # begin_packet again. Protect that stream until its flush as well.
        if self._owner != threading.get_ident():
            self._lock.acquire()
            object.__setattr__(self, "_owner", threading.get_ident())
        try:
            return self._writer.write(data)
        except BaseException:
            self._failed_request()
            raise

    def _release_request(self):
        if self._owner == threading.get_ident():
            object.__setattr__(self, "_owner", None)
            self._lock.release()

    def _failed_request(self):
        try:
            self.abort_transport()
        finally:
            self._release_request()

    def abort_transport(self):
        # A blocking multipart send owns the writer; do not overwrite its
        # packet type/position or wait indefinitely. Interrupt that physical
        # transport; the query worker invalidates it before pool reuse.
        self._connection._datapyn_aborted = True
        try:
            self._stream.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        try:
            self._stream.close()
        except OSError:
            pass


def interrupt_network_cursor(cursor):
    from pytds import tds_base

    session = getattr(cursor, "_session", None)
    if session is None:
        return
    writer = session._writer
    if not isinstance(writer, _SerializedTdsWriter):
        raise SqlServerNetworkAuthError("O cancelamento não encontrou o transporte TDS protegido.")
    if not writer._lock.acquire(blocking=False):
        writer.abort_transport()
        return
    try:
        if not session.in_cancel and getattr(session, "state", None) != tds_base.TDS_IDLE:
            # Set the flag before sending; a fast Attention ACK must not
            # clear it and then be overwritten by the cancelling thread.
            session.in_cancel = True
            try:
                writer.begin_packet(tds_base.PacketType.CANCEL)
                writer.flush()
            except Exception:
                writer.abort_transport()
                raise
    finally:
        writer._lock.release()


def _certificate_matches_hostname(certificate, hostname: str) -> bool:
    from cryptography import x509
    from cryptography.x509.oid import NameOID

    hostname = hostname.rstrip(".").casefold()
    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        address = None
    try:
        san = certificate.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
    except x509.ExtensionNotFound:
        # RFC 6125: CN is only used when a DNS SAN is absent; IPs require SAN.
        names = [] if address else [item.value for item in certificate.subject.get_attributes_for_oid(NameOID.COMMON_NAME)]
    else:
        if address:
            return address in san.get_values_for_type(x509.IPAddress)
        names = san.get_values_for_type(x509.DNSName)
    for name in names:
        name = name.rstrip(".").casefold()
        if name == hostname:
            return True
        if name.startswith("*.") and "*" not in name[2:] and len(name.split(".")) == len(hostname.split(".")):
            if hostname.split(".", 1)[1] == name[2:]:
                return True
    return False


def _tls_context(cafile: str, hostname: str, trust_certificate: bool):
    from OpenSSL import SSL

    context = SSL.Context(SSL.TLS_CLIENT_METHOD)
    context.set_min_proto_version(SSL.TLS1_2_VERSION)
    if trust_certificate:
        context.set_verify(SSL.VERIFY_NONE, lambda *_args: True)
    else:
        context.load_verify_locations(cafile)
        context.set_verify(SSL.VERIFY_PEER, lambda _conn, certificate, _error, depth, valid:
                           bool(valid and (depth != 0 or _certificate_matches_hostname(certificate.to_cryptography(), hostname))))
    return context


class _NetworkAuth:
    """Delay network credentials until TLS verification; support EPA binding."""

    def __init__(self, mode, username, password, hostname, port, certificate):
        self.mode, self.username, self.password = mode, username, password
        self.hostname, self.port, self.certificate = hostname, port, certificate
        self.context = None

    def create_packet(self):
        import spnego
        from cryptography.hazmat.primitives import hashes, serialization
        from spnego.channel_bindings import GssChannelBindings

        certificate = self.certificate().to_cryptography()
        algorithm = certificate.signature_hash_algorithm
        if algorithm is None or algorithm.name in {"md5", "sha1"}:
            algorithm = hashes.SHA256()
        digest = hashes.Hash(algorithm)
        digest.update(certificate.public_bytes(serialization.Encoding.DER))
        bindings = GssChannelBindings(application_data=b"tls-server-end-point:" + digest.finalize())
        try:
            self.context = spnego.client(username=self.username, password=self.password,
                                         protocol=self.mode, hostname=f"{self.hostname}:{self.port}",
                                         service="MSSQLSvc", channel_bindings=bindings)
            token = self.context.step()
            if not token:
                raise ValueError("Authentication provider did not generate a token")
            return token
        except Exception as error:
            raise SqlServerNetworkAuthError(
                "Não foi possível iniciar " + self.mode.upper() + ". Verifique as credenciais de rede, realm/KDC e SPN do SQL Server.",
            code="sqlserver_auth_failed") from None

    def handle_next(self, packet):
        try:
            return self.context.step(packet)
        except Exception:
            raise SqlServerNetworkAuthError(
                "A autenticação " + self.mode.upper() + " falhou. Verifique a senha, o domínio/realm e as políticas do servidor.",
                code="sqlserver_auth_failed") from None

    def close(self):
        self.context = None
        self.username = self.password = ""


def register_network_dialect() -> None:
    from sqlalchemy.dialects import registry
    registry.register("mssql.datapyn_tds", "src.database.sqlserver_network_dialect", "DataPynTdsDialect")


def qmark_to_pyformat(query: str, values) -> tuple[str, tuple]:
    """Adapt existing typed SQL parameters without touching quoted ? symbols."""
    from datapyn_runtime.sql_context import sql_code_mask

    values = tuple(values)
    masked = sql_code_mask(query, "sqlserver", identifiers=True)
    offsets = [index for index, char in enumerate(masked) if char == "?"]
    if len(offsets) != len(values):
        raise ValueError("SQL Server parameter count does not match its placeholders")
    pieces, start = [], 0
    for offset in offsets:
        pieces.extend((query[start:offset].replace("%", "%%"), "%s"))
        start = offset + 1
    pieces.append(query[start:].replace("%", "%%"))
    return "".join(pieces), values
