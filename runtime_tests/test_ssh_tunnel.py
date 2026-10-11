"""SSH lifecycle tests use a real, isolated Paramiko server on loopback."""

import base64
import json
import select
import socket
import socketserver
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import paramiko
import pytest

from datapyn_runtime.ssh_tunnel import SshTrustStore, SshTunnel, SshTunnelError, fingerprint


class Echo(socketserver.BaseRequestHandler):
    def handle(self):
        while data := self.request.recv(65536):
            self.request.sendall(data)


class EchoServer(socketserver.ThreadingTCPServer):
    daemon_threads = True


class LocalSshServer:
    def __init__(self, destination_port):
        self.key = paramiko.RSAKey.generate(2048)
        self.user_key = paramiko.RSAKey.generate(2048)
        self.listener = socket.socket()
        self.listener.bind(("127.0.0.1", 0))
        self.listener.listen()
        self.listener.settimeout(0.1)
        self.port = self.listener.getsockname()[1]
        self.destination_port = destination_port
        self.auth = []
        self.destinations = []
        self.transports = []
        self.closed = threading.Event()
        self.thread = threading.Thread(target=self._accept, daemon=True)
        self.thread.start()

    def _accept(self):
        while not self.closed.is_set():
            try:
                stream, _ = self.listener.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            threading.Thread(target=self._session, args=(stream,), daemon=True).start()

    def _session(self, stream):
        owner = self
        destinations = {}

        class Server(paramiko.ServerInterface):
            def get_allowed_auths(self, username):
                return "password,publickey"

            def check_auth_password(self, username, password):
                owner.auth.append((username, "password"))
                return paramiko.AUTH_SUCCESSFUL if username == "tester" and password == "ssh-secret" else paramiko.AUTH_FAILED

            def check_auth_publickey(self, username, key):
                owner.auth.append((username, "private_key"))
                return paramiko.AUTH_SUCCESSFUL if username == "tester" and key == owner.user_key else paramiko.AUTH_FAILED

            def check_channel_direct_tcpip_request(self, channel_id, origin, destination):
                owner.destinations.append(destination)
                if destination != ("db.remote.invalid", owner.destination_port):
                    return paramiko.OPEN_FAILED_CONNECT_FAILED
                try:
                    destinations[channel_id] = socket.create_connection(("127.0.0.1", owner.destination_port), timeout=2)
                    return paramiko.OPEN_SUCCEEDED
                except OSError:
                    return paramiko.OPEN_FAILED_CONNECT_FAILED

        transport = paramiko.Transport(stream)
        self.transports.append(transport)
        transport.add_server_key(self.key)
        try:
            transport.start_server(server=Server())
            while not self.closed.is_set() and transport.is_active():
                channel = transport.accept(0.1)
                if channel is not None:
                    destination = destinations.pop(channel.get_id())
                    threading.Thread(target=self._bridge, args=(channel, destination), daemon=True).start()
        except Exception:
            pass
        finally:
            transport.close()
            for destination in destinations.values():
                destination.close()

    def _bridge(self, channel, destination):
        try:
            while not self.closed.is_set():
                readable, _, _ = select.select([channel, destination], [], [], 0.1)
                for source in readable:
                    data = source.recv(65536)
                    if not data:
                        return
                    (destination if source is channel else channel).sendall(data)
        except (OSError, EOFError):
            pass
        finally:
            try:
                channel.close()
            except Exception:
                pass
            destination.close()

    def close(self):
        self.closed.set()
        self.listener.close()
        for transport in self.transports:
            transport.close()
        self.thread.join(timeout=1)

    def details(self):
        return {"host": "127.0.0.1", "port": self.port, "key_type": self.key.get_name(),
                "public_key": self.key.get_base64(), "fingerprint": fingerprint(self.key)}

    def config(self, **kwargs):
        return {"enabled": True, "host": "127.0.0.1", "port": self.port, "username": "tester",
                "auth_method": "password", "password": "ssh-secret", **kwargs}


@pytest.fixture
def local_ssh():
    echo = EchoServer(("127.0.0.1", 0), Echo)
    thread = threading.Thread(target=echo.serve_forever, daemon=True)
    thread.start()
    ssh = LocalSshServer(echo.server_address[1])
    try:
        yield ssh
    finally:
        ssh.close()
        echo.shutdown()
        echo.server_close()
        thread.join(timeout=1)


@pytest.fixture
def trust(tmp_path):
    return SshTrustStore(tmp_path / "ssh-known-hosts.json")


def create_tunnel(server, trust, **config):
    return SshTunnel(server.config(**config), "db.remote.invalid", server.destination_port, trust_store=trust)


def exchange(tunnel, data=b"database-test"):
    with socket.create_connection((tunnel.local_host, tunnel.local_port), timeout=2) as stream:
        stream.sendall(data)
        return stream.recv(len(data))


def test_unknown_host_is_challenged_before_sending_credentials(local_ssh, trust):
    tunnel = create_tunnel(local_ssh, trust)
    with pytest.raises(SshTunnelError) as caught:
        tunnel.start()
    assert caught.value.code == "ssh_host_key_unknown"
    assert caught.value.details == local_ssh.details()
    assert local_ssh.auth == []
    assert local_ssh.destinations == []
    assert not trust.path.exists()
    assert not tunnel.is_alive()


def test_confirmation_pins_key_and_password_tunnel_resolves_destination_on_server(local_ssh, trust):
    trust.confirm(local_ssh.details())
    with create_tunnel(local_ssh, trust) as tunnel:
        assert tunnel.local_host == "127.0.0.1" and tunnel.local_port > 0
        assert exchange(tunnel) == b"database-test"
        assert local_ssh.destinations == [("db.remote.invalid", local_ssh.destination_port)] * 2
        assert local_ssh.auth == [("tester", "password")]
        assert tunnel._config == {}
        port = tunnel.local_port
    assert not tunnel.is_alive()
    with pytest.raises(OSError):
        socket.create_connection(("127.0.0.1", port), timeout=0.2)


def test_host_key_changes_are_blocked_before_auth_and_cannot_be_reconfirmed(local_ssh, trust):
    old = paramiko.RSAKey.generate(2048)
    details = {**local_ssh.details(), "public_key": old.get_base64(), "fingerprint": fingerprint(old)}
    trust.confirm(details)
    with pytest.raises(SshTunnelError) as caught:
        create_tunnel(local_ssh, trust).start()
    assert caught.value.code == "ssh_host_key_changed"
    assert caught.value.details["expected_fingerprint"] == fingerprint(old)
    assert local_ssh.auth == []
    with pytest.raises(SshTunnelError, match="mudou"):
        trust.confirm(local_ssh.details())
    assert json.loads(trust.path.read_text())["hosts"][f"[127.0.0.1]:{local_ssh.port}"]["fingerprint"] == fingerprint(old)


@pytest.mark.parametrize("mutation", ["fingerprint", "public_key", "key_type"])
def test_confirmation_rejects_tampered_public_material(local_ssh, trust, mutation):
    details = local_ssh.details()
    details[mutation] = "invalid"
    with pytest.raises(SshTunnelError) as caught:
        trust.confirm(details)
    assert caught.value.code == "ssh_trust_invalid"
    assert not trust.path.exists()


def test_corrupted_trust_file_fails_closed(local_ssh, trust):
    trust.path.write_text("{bad json")
    with pytest.raises(SshTunnelError) as caught:
        create_tunnel(local_ssh, trust).start()
    assert caught.value.code == "ssh_trust_invalid"
    assert local_ssh.auth == []


@pytest.mark.parametrize("passphrase", [None, "key-secret"])
def test_private_key_authentication_plain_and_encrypted(local_ssh, trust, tmp_path, passphrase):
    trust.confirm(local_ssh.details())
    key_path = tmp_path / "private.pem"
    local_ssh.user_key.write_private_key_file(str(key_path), password=passphrase)
    with create_tunnel(local_ssh, trust, auth_method="private_key", private_key_path=str(key_path), passphrase=passphrase) as tunnel:
        assert exchange(tunnel) == b"database-test"
    assert local_ssh.auth == [("tester", "private_key")]


def test_wrong_private_key_passphrase_is_safe_and_releases_transport(local_ssh, trust, tmp_path, caplog):
    trust.confirm(local_ssh.details())
    key_path = tmp_path / "private.pem"
    local_ssh.user_key.write_private_key_file(str(key_path), password="key-secret")
    tunnel = create_tunnel(local_ssh, trust, auth_method="private_key", private_key_path=str(key_path), passphrase="wrong-private-secret")
    with pytest.raises(SshTunnelError) as caught:
        tunnel.start()
    assert caught.value.code == "ssh_key_invalid"
    assert not tunnel.is_alive()
    assert local_ssh.auth == []
    assert "wrong-private-secret" not in str(caught.value) + caplog.text


def test_auth_failure_never_opens_listener_and_does_not_echo_password(local_ssh, trust, caplog):
    trust.confirm(local_ssh.details())
    tunnel = create_tunnel(local_ssh, trust, password="wrong-private-secret")
    with pytest.raises(SshTunnelError) as caught:
        tunnel.start()
    assert caught.value.code == "ssh_auth_failed"
    assert not tunnel.is_alive() and tunnel.local_port == 0
    assert local_ssh.destinations == []
    assert "wrong-private-secret" not in str(caught.value) + caplog.text


def test_unreachable_remote_database_is_reported_without_direct_fallback(local_ssh, trust):
    trust.confirm(local_ssh.details())
    tunnel = SshTunnel(local_ssh.config(), "docker-not-on-host.invalid", local_ssh.destination_port, trust_store=trust)
    with pytest.raises(SshTunnelError) as caught:
        tunnel.start()
    assert caught.value.code == "ssh_destination_failed"
    assert "Docker" in str(caught.value)
    assert tunnel.local_port == 0 and not tunnel.is_alive()


def test_concurrent_tunnels_get_distinct_ports_and_disconnect_independently(local_ssh, trust):
    trust.confirm(local_ssh.details())
    tunnels = [create_tunnel(local_ssh, trust) for _ in range(4)]
    try:
        with ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(lambda tunnel: tunnel.start(), tunnels))
        assert len({tunnel.local_port for tunnel in tunnels}) == 4
        for tunnel in tunnels:
            assert exchange(tunnel) == b"database-test"
        tunnels[0].close()
        assert exchange(tunnels[1]) == b"database-test"
    finally:
        for tunnel in tunnels:
            tunnel.close()


def test_server_drop_closes_listener_and_live_streams(local_ssh, trust):
    trust.confirm(local_ssh.details())
    tunnel = create_tunnel(local_ssh, trust).start()
    stream = socket.create_connection((tunnel.local_host, tunnel.local_port), timeout=2)
    try:
        stream.sendall(b"ok")
        assert stream.recv(2) == b"ok"
        local_ssh.close()
        deadline = time.monotonic() + 2
        while not tunnel._closed.is_set() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert tunnel._closed.is_set() and not tunnel.is_alive()
        assert tunnel.error.code == "ssh_connection_lost"
        assert stream.recv(1) == b""
        with pytest.raises(OSError):
            socket.create_connection((tunnel.local_host, tunnel.local_port), timeout=0.2)
    finally:
        stream.close()
        tunnel.close()


def test_cancel_before_start_does_not_attempt_network(local_ssh, trust):
    tunnel = create_tunnel(local_ssh, trust)
    tunnel.close()
    with pytest.raises(SshTunnelError) as caught:
        tunnel.start()
    assert caught.value.code == "ssh_cancelled"
    assert local_ssh.auth == [] and local_ssh.transports == []


def test_cancel_during_handshake_interrupts_network_and_releases_socket(trust):
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    listener.settimeout(2)
    tunnel = SshTunnel({"host": "127.0.0.1", "port": listener.getsockname()[1], "username": "tester", "password": "ssh-secret"},
                       "db.remote.invalid", 5432, trust_store=trust)
    peer = None
    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(tunnel.start)
            peer, _ = listener.accept()
            # Hold the server before its SSH banner. Cancelling closes the
            # socket immediately rather than waiting for the banner timeout.
            tunnel.close()
            with pytest.raises(SshTunnelError) as caught:
                future.result(timeout=2)
            assert caught.value.code == "ssh_cancelled"
        assert tunnel.local_port == 0 and not tunnel.is_alive()
        assert tunnel._socket.fileno() == -1
    finally:
        if peer is not None:
            peer.close()
        listener.close()


def test_trust_confirmation_is_idempotent_and_contains_no_secrets(local_ssh, trust):
    assert trust.confirm(local_ssh.details()) == trust.confirm(local_ssh.details())
    payload = trust.path.read_text()
    assert "ssh-secret" not in payload and "tester" not in payload
    assert len(json.loads(payload)["hosts"]) == 1
    assert base64.b64decode(local_ssh.details()["public_key"])
