"""Real stdio/child-process RPCs against an isolated loopback SSH server."""

import json

import paramiko

from test_runtime import client  # noqa: F401
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
