"""In-process SSH forwarding with explicit, pinned server trust.

Only the broker confirms keys. Session kernels read the same atomic trust file;
they never enroll or replace a server key while connecting.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
from pathlib import Path
import select
import socket
import tempfile
import threading

from .paths import workspace_root


class SshTunnelError(ConnectionError):
    """A safe UI error; raw SSH exceptions and credentials are never included."""

    def __init__(self, message: str, *, code: str, details: dict | None = None):
        super().__init__(message)
        self.code = code
        self.details = dict(details or {})


def _host(value) -> str:
    host = str(value or "").strip()
    if not host or len(host) > 253 or any(character.isspace() for character in host) or any(c in host for c in "\x00;,/\\"):
        raise SshTunnelError("Informe um servidor SSH ou destino de banco válido.", code="ssh_config_invalid")
    return host


def _port(value) -> int:
    try:
        port = int(value)
        if isinstance(value, bool) or not 1 <= port <= 65535:
            raise ValueError()
        return port
    except (ValueError, TypeError):
        raise SshTunnelError("A porta deve estar entre 1 e 65535.", code="ssh_config_invalid") from None


def fingerprint(key) -> str:
    return "SHA256:" + base64.b64encode(hashlib.sha256(key.asbytes()).digest()).decode("ascii").rstrip("=")


def _key_details(host: str, port: int, key) -> dict:
    return {"host": host, "port": port, "key_type": key.get_name(),
            "public_key": key.get_base64(), "fingerprint": fingerprint(key)}


_TRUST_LOCK = threading.RLock()


class SshTrustStore:
    def __init__(self, path: str | Path | None = None):
        self.path = Path(path) if path is not None else workspace_root() / "ssh_known_hosts.json"

    @staticmethod
    def _identity(host: str, port: int) -> str:
        return f"[{host.lower().rstrip('.')}]:{port}"

    def _read(self) -> dict:
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(value, dict) or value.get("version") != 1 or not isinstance(value.get("hosts"), dict):
                raise ValueError()
            return value
        except FileNotFoundError:
            return {"version": 1, "hosts": {}}
        except (OSError, ValueError, TypeError):
            raise SshTunnelError("Não foi possível ler os servidores SSH confiáveis.", code="ssh_trust_invalid") from None

    def verify(self, host: str, port: int, key) -> None:
        details = _key_details(_host(host), _port(port), key)
        saved = self._read()["hosts"].get(self._identity(host, port))
        if saved is None:
            raise SshTunnelError("Confirme a fingerprint deste servidor SSH antes de conectar.",
                                 code="ssh_host_key_unknown", details=details)
        if not isinstance(saved, dict) or not isinstance(saved.get("public_key"), str):
            raise SshTunnelError("O registro de confiança SSH está inválido.", code="ssh_trust_invalid")
        if saved.get("key_type") != details["key_type"] or not hmac.compare_digest(saved["public_key"], details["public_key"]):
            details["expected_fingerprint"] = str(saved.get("fingerprint") or "")
            raise SshTunnelError("A chave do servidor SSH mudou. A conexão foi bloqueada.",
                                 code="ssh_host_key_changed", details=details)

    def confirm(self, details: dict) -> dict:
        import paramiko

        try:
            host, port = _host(details.get("host")), _port(details.get("port"))
            public_key = details.get("public_key")
            if not isinstance(public_key, str) or len(public_key) > 16384:
                raise ValueError()
            raw = base64.b64decode(public_key, validate=True)
            key = paramiko.PKey.from_type_string(str(details.get("key_type") or ""), raw)
            validated = _key_details(host, port, key)
            supplied_fingerprint = details.get("fingerprint")
            if not isinstance(supplied_fingerprint, str) or not hmac.compare_digest(validated["fingerprint"], supplied_fingerprint):
                raise ValueError()
        except SshTunnelError:
            raise
        except Exception:
            raise SshTunnelError("A fingerprint SSH informada é inválida.", code="ssh_trust_invalid") from None

        with _TRUST_LOCK:
            store = self._read()
            identity = self._identity(host, port)
            if identity in store["hosts"]:
                self.verify(host, port, key)
                return validated
            store["hosts"][identity] = validated
            temporary = None
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                descriptor, temporary = tempfile.mkstemp(prefix=".ssh-known-hosts-", dir=self.path.parent)
                with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                    json.dump(store, handle, ensure_ascii=True)
                    handle.flush()
                    os.fsync(handle.fileno())
                os.chmod(temporary, 0o600)
                os.replace(temporary, self.path)
            except OSError:
                raise SshTunnelError("Não foi possível salvar a confiança SSH.", code="ssh_trust_invalid") from None
            finally:
                if temporary and os.path.exists(temporary):
                    os.unlink(temporary)
        return validated


class SshTunnel:
    """One authenticated transport and an ephemeral IPv4 loopback listener."""

    local_host = "127.0.0.1"

    def __init__(self, config: dict, target_host: str, target_port: int, *, trust_store: SshTrustStore | None = None):
        self._config = dict(config)
        self.host, self.port = _host(config.get("host")), _port(config.get("port", 22))
        self.target_host, self.target_port = _host(target_host), _port(target_port)
        self.username = str(config.get("username") or "").strip()
        self.auth_method = str(config.get("auth_method") or "password")
        if not self.username or self.auth_method not in {"password", "private_key"}:
            raise SshTunnelError("Informe o usuário e a autenticação SSH.", code="ssh_config_invalid")
        self.trust_store = trust_store or SshTrustStore()
        self.local_port = 0
        self._transport = None
        self._socket = None
        self._listener = None
        self._thread = None
        self._closed = threading.Event()
        self._lock = threading.RLock()
        self._streams = set()
        self.error: SshTunnelError | None = None

    def start(self, *, authentication_only: bool = False) -> SshTunnel:
        import paramiko

        try:
            self._ensure_open()
            self._socket = socket.create_connection((self.host, self.port), timeout=15)
            self._ensure_open()
            self._transport = paramiko.Transport(self._socket)
            self._transport.banner_timeout = 15
            self._transport.auth_timeout = 15
            self._transport.start_client(timeout=15)
            self._ensure_open()
            # Authentication must never be sent before explicit server trust.
            self.trust_store.verify(self.host, self.port, self._transport.get_remote_server_key())
            if self.auth_method == "private_key":
                try:
                    path = Path(str(self._config.get("private_key_path") or "")).expanduser()
                    if not path.is_file():
                        raise ValueError()
                    passphrase = self._config.get("passphrase") or None
                    # Paramiko 5 forwards this value to cryptography, whose key
                    # loaders require bytes even though from_path annotates str.
                    key = paramiko.PKey.from_path(path, password=passphrase.encode("utf-8") if passphrase is not None else None)
                except Exception:
                    raise SshTunnelError("Não foi possível abrir a chave SSH. Verifique o arquivo e a passphrase.", code="ssh_key_invalid") from None
                self._transport.auth_publickey(self.username, key)
            else:
                password = self._config.get("password")
                if not isinstance(password, str) or not password:
                    raise SshTunnelError("Informe a senha SSH.", code="ssh_config_invalid")
                self._transport.auth_password(self.username, password, fallback=False)
            self._ensure_open()
            if not self._transport.is_authenticated():
                raise SshTunnelError("O servidor SSH exige outra etapa de autenticação.", code="ssh_auth_failed")
            self._transport.set_keepalive(30)
            if authentication_only:
                # Settings tests verify only this reusable SSH endpoint/account.
                # No database destination, listener or SQL command is involved.
                return self
            # The server resolves the database name. Reject a denied/unreachable
            # destination now, before opening a database socket on the client.
            try:
                probe = self._transport.open_channel("direct-tcpip", (self.target_host, self.target_port), (self.local_host, 0), timeout=15)
                probe.close()
            except Exception:
                self._ensure_open()
                raise self._destination_error() from None
            self._listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self._listener.bind((self.local_host, 0))
            self._listener.listen(32)
            self._listener.settimeout(0.2)
            self._ensure_open()
            self.local_port = self._listener.getsockname()[1]
            self._thread = threading.Thread(target=self._accept, name="datapyn-ssh-forward", daemon=True)
            self._thread.start()
            self._ensure_open()
            return self
        except SshTunnelError:
            self.close()
            raise
        except paramiko.AuthenticationException:
            cancelled = self._closed.is_set()
            self.close()
            if cancelled:
                raise SshTunnelError("A conexão SSH foi cancelada.", code="ssh_cancelled") from None
            raise SshTunnelError("A autenticação SSH falhou. Verifique o usuário e as credenciais.", code="ssh_auth_failed") from None
        except Exception:
            cancelled = self._closed.is_set()
            self.close()
            if cancelled:
                raise SshTunnelError("A conexão SSH foi cancelada.", code="ssh_cancelled") from None
            raise SshTunnelError("Não foi possível conectar ao servidor SSH. Verifique o endereço, a porta e a rede.", code="ssh_connect_failed") from None
        finally:
            # Do not retain a second copy of the supplied credentials/config.
            self._config.clear()

    def _ensure_open(self) -> None:
        if self._closed.is_set():
            raise SshTunnelError("A conexão SSH foi cancelada.", code="ssh_cancelled")

    def _destination_error(self) -> SshTunnelError:
        return SshTunnelError("O servidor SSH não conseguiu acessar o banco. Verifique o host e a porta vistos pela VPS; nomes de containers podem não resolver fora da rede Docker.",
                              code="ssh_destination_failed", details={"host": self.target_host, "port": self.target_port})

    def is_alive(self) -> bool:
        return not self._closed.is_set() and self._transport is not None and self._transport.is_active() and self._transport.is_authenticated()

    def _accept(self) -> None:
        while not self._closed.is_set():
            if not self.is_alive():
                self.error = SshTunnelError("A conexão com o servidor SSH foi interrompida.", code="ssh_connection_lost")
                self.close()
                break
            try:
                stream, origin = self._listener.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            with self._lock:
                if self._closed.is_set():
                    stream.close()
                    break
                self._streams.add(stream)
            threading.Thread(target=self._forward, args=(stream, origin), name="datapyn-ssh-stream", daemon=True).start()

    def _forward(self, stream: socket.socket, origin: tuple) -> None:
        channel = None
        try:
            try:
                channel = self._transport.open_channel("direct-tcpip", (self.target_host, self.target_port), origin, timeout=15)
            except Exception:
                if not self._closed.is_set():
                    self.error = self._destination_error() if self.is_alive() else SshTunnelError("A conexão com o servidor SSH foi interrompida.", code="ssh_connection_lost")
                return
            with self._lock:
                if self._closed.is_set():
                    return
                self._streams.add(channel)
            while not self._closed.is_set():
                readable, _, _ = select.select([stream, channel], [], [], 0.2)
                if stream in readable:
                    data = stream.recv(65536)
                    if not data:
                        break
                    channel.sendall(data)
                if channel in readable:
                    data = channel.recv(65536)
                    if not data:
                        break
                    stream.sendall(data)
        except Exception:
            # A database may reset its socket after rejecting auth/TLS. That
            # must retain the driver's precise error, rather than misreporting
            # a remote destination failure on a healthy SSH transport.
            if not self._closed.is_set() and not self.is_alive():
                self.error = SshTunnelError("A conexão com o servidor SSH foi interrompida.", code="ssh_connection_lost")
        finally:
            for connection in (channel, stream):
                if connection is not None:
                    try:
                        connection.close()
                    except Exception:
                        pass
                    with self._lock:
                        self._streams.discard(connection)

    def close(self) -> None:
        self._closed.set()
        with self._lock:
            connections = list(self._streams)
            self._streams.clear()
        for connection in (self._listener, *connections, self._transport, self._socket):
            if connection is not None:
                try:
                    connection.close()
                except Exception:
                    pass
        if self._thread is not None and self._thread is not threading.current_thread():
            self._thread.join(timeout=1)

    def __enter__(self):
        return self.start()

    def __exit__(self, *args):
        self.close()


def test_tunnel(params):
    config = params.get("config")
    if not isinstance(config, dict):
        raise ValueError("SSH config must be an object")
    tunnel = SshTunnel(config, "127.0.0.1", 1,
                       trust_store=SshTrustStore(params.get("_ssh_trust_path")))
    try:
        tunnel.start(authentication_only=True)
        return {"success": True, "message": "Conexão SSH autenticada. O destino do banco é validado no teste da conexão."}
    finally:
        tunnel.close()
