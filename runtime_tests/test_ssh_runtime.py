"""Real stdio/child-process RPCs against an isolated loopback SSH server."""

import json
import socket

import paramiko

from test_runtime import client  # noqa: F401
from test_connection_concurrency import send
from test_ssh_tunnel import local_ssh  # noqa: F401


def database_config(server):
    return {"db_type": "postgresql", "host": "db.remote.invalid", "port": server.destination_port,
            "database": "fixture", "username": "fixture", "ssh": server.config()}


def test_connection_test_surfaces_first_server_identity_without_authentication(client, local_ssh):
    response = client.response("connection.test", {"test_id": "ssh-first", "config": database_config(local_ssh)})
    assert response["error"]["code"] == "ssh_host_key_unknown"
    assert response["error"]["details"] == local_ssh.details()
    assert local_ssh.auth == []
    assert "ssh-secret" not in json.dumps(response)
    assert client.request("system.info")["protocol_version"] == 1


def test_kernel_connection_and_block_override_report_actionable_trust_error(client, local_ssh):
    session = client.session()
    config = database_config(local_ssh)
    response = client.response("connection.connect", {"session_id": session, "config": config})
    assert response["error"]["code"] == "ssh_host_key_unknown"
    assert response["error"]["details"] == local_ssh.details()
    config["ssh"].pop("password")
    saved = client.request("connections.save", {"connection": {"name": "SSH override", "config": config}})
    finished = client.execute("SELECT 1", "ssh-block-override", language="sql", connection_id=saved["id"])
    assert finished["status"] == "failed" and finished["error_code"] == "ssh_host_key_unknown"
    assert finished["error_details"] == local_ssh.details()
    assert "Testar conexão" in finished["error"] and local_ssh.auth == []
    assert "ssh-secret" not in json.dumps(finished)


def test_broker_trust_rpc_pins_first_key_and_blocks_later_change(client, local_ssh):
    config = database_config(local_ssh)
    challenge = client.response("connection.test", {"config": config})["error"]
    assert challenge["code"] == "ssh_host_key_unknown"
    assert client.request("ssh.host_key.trust", {"details": challenge["details"]}) == local_ssh.details()
    local_ssh.key = paramiko.RSAKey.generate(2048)
    blocked = client.response("connection.test", {"config": config})["error"]
    assert blocked["code"] == "ssh_host_key_changed"
    assert blocked["details"]["expected_fingerprint"] == challenge["details"]["fingerprint"]
    refused = client.response("ssh.host_key.trust", {"details": blocked["details"]})["error"]
    assert refused["code"] == "ssh_host_key_changed" and local_ssh.auth == []


def test_reusable_tunnel_rpc_test_authenticates_without_database_socket(client, local_ssh):
    public = local_ssh.config()
    public.pop("password")
    tunnel = client.request("ssh.tunnels.save", {"tunnel": {"name": "Local fixture", "config": public}})
    assert not tunnel["has_password"]
    assert client.request("ssh.tunnels.list")["ssh_tunnels"] == [tunnel]
    assert client.request("connections.list")["ssh_tunnels"] == [tunnel]
    params = {"tunnel_id": tunnel["id"], "config": local_ssh.config(), "test_id": "ssh-standalone"}
    challenge = client.response("ssh.tunnels.test", params)["error"]
    assert challenge["code"] == "ssh_host_key_unknown" and challenge["details"] == local_ssh.details()
    assert local_ssh.auth == []
    client.request("ssh.host_key.trust", {"details": challenge["details"]})
    result = client.request("ssh.tunnels.test", params)
    assert result["success"] and local_ssh.auth == [("tester", "password")] and local_ssh.destinations == []
    connection = client.request("connections.save", {"connection": {"name": "Uses tunnel", "config": {
        "db_type": "postgresql", "host": "db.remote.invalid", "port": local_ssh.destination_port,
        "database": "fixture", "ssh_tunnel_id": tunnel["id"]}}})
    assert "ssh" not in connection["config"]
    refused = client.response("ssh.tunnels.delete", {"tunnel_id": tunnel["id"]})
    assert refused["error"]["code"] == "invalid_params" and "em uso" in refused["error"]["message"]
    client.request("connections.delete", {"connection_id": connection["id"]})
    assert client.request("ssh.tunnels.delete", {"tunnel_id": tunnel["id"]}) == {"ssh_tunnels": []}


def test_standalone_ssh_test_is_cancellable_without_blocking_runtime(client):
    with socket.socket() as stalled:
        stalled.bind(("127.0.0.1", 0))
        stalled.listen()
        params = {"test_id": "cancel-ssh", "config": {"host": "127.0.0.1", "port": stalled.getsockname()[1],
                  "username": "fixture", "auth_method": "password", "password": "temporary"}}
        request_id = send(client, "ssh.tunnels.test", params)
        assert client.request("system.info")["protocol_version"] == 1
        assert client.request("connection.test_cancel", {"test_id": "cancel-ssh"})["status"] == "cancelling"
        result = client.wait(lambda message: message.get("id") == request_id)
        assert result["error"]["code"] == "cancelled"
        assert client.request("system.info")["protocol_version"] == 1
