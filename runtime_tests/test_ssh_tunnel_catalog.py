"""Reusable SSH endpoints preserve secrets, identity and references across profiles."""

from copy import deepcopy
import json
from pathlib import Path
import time

import pytest

from datapyn_runtime.connection_catalog import ConnectionCatalog, ssh_identity
from datapyn_runtime.database import connection_test_config
from datapyn_runtime.ssh_tunnel import SshTunnelError, SshTrustStore, test_tunnel as authenticate_tunnel
from datapyn_runtime.supervisor import Supervisor
from test_connection_catalog import Secrets
from test_ssh_tunnel import local_ssh  # noqa: F401


@pytest.fixture
def catalog(tmp_path):
    return ConnectionCatalog(tmp_path / "connections.json", Secrets())


def tunnel_config(**values):
    return {"enabled": True, "host": "vps.example", "port": 22, "username": "account",
            "auth_method": "password", **values}


def create_tunnel(catalog, **values):
    return catalog.save_tunnel({"name": "VPS", "config": tunnel_config(**values)})


def connection(tunnel_id, name="Database"):
    return {"name": name, "config": {"db_type": "postgresql", "host": "db.example", "port": 5432,
            "database": "reporting", "username": "database-user", "ssh_tunnel_id": tunnel_id}}


def broker(catalog):
    supervisor = Supervisor.__new__(Supervisor)
    supervisor._catalog = catalog
    supervisor.profile_path = catalog.path.parent
    return supervisor


def test_reusable_tunnel_credentials_and_reference_are_independent(catalog):
    tunnel = create_tunnel(catalog, password="ssh-secret")
    first = catalog.save_connection(connection(tunnel["id"]), password="db-secret", save_password=True)
    second = catalog.save_connection(connection(tunnel["id"], "Another"))
    assert "ssh" not in first["config"] and first["config"]["ssh_tunnel_id"] == tunnel["id"]
    assert catalog.config(first["id"])["ssh"]["password"] == "ssh-secret"
    assert catalog.config(second["id"])["ssh"]["password"] == "ssh-secret"
    assert catalog.config(first["id"])["password"] == "db-secret"
    assert catalog.credentials.get(first["id"]) == {"password": "db-secret"}
    assert not catalog.credentials.get(f"{first['id']}:ssh")
    assert "secret" not in catalog.path.read_text() and "secret" not in json.dumps(catalog.list())


def test_blank_tunnel_edit_preserves_secret_and_updates_revision(catalog):
    tunnel = create_tunnel(catalog, password="before")
    revision = tunnel["updated_at"]
    tunnel["name"] = "Renamed"
    tunnel["config"]["password"] = ""
    edited = catalog.save_tunnel(tunnel, password="")
    assert edited["has_password"] and edited["updated_at"] != revision
    assert catalog.tunnel_config(tunnel["id"])["password"] == "before"


def test_private_key_tunnel_keeps_only_passphrase_and_clears_on_path_change(catalog):
    tunnel = create_tunnel(catalog, auth_method="private_key", private_key_path="first.pem", passphrase="phrase", password="unused")
    assert tunnel["has_passphrase"] and not tunnel["has_password"]
    assert catalog.tunnel_config(tunnel["id"])["passphrase"] == "phrase"
    assert "password" not in catalog.tunnel_config(tunnel["id"])
    tunnel["config"]["private_key_path"] = "second.pem"
    assert not catalog.save_tunnel(tunnel)["has_passphrase"]


def test_tunnel_delete_rolls_back_json_and_keyring_failure(catalog, monkeypatch):
    tunnel = create_tunnel(catalog, password="secret")
    before = catalog.list()
    monkeypatch.setattr(catalog, "_save", lambda: (_ for _ in ()).throw(OSError("disk full")))
    with pytest.raises(OSError, match="disk full"):
        catalog.dispatch("ssh.tunnels.delete", {"tunnel_id": tunnel["id"]})
    assert catalog.list() == before and catalog.tunnel_config(tunnel["id"])["password"] == "secret"


@pytest.mark.parametrize("change", [{"host": "other.example"}, {"port": 2222}, {"username": "other"},
                                   {"auth_method": "private_key", "private_key_path": "new.pem"}])
def test_tunnel_identity_change_clears_previous_secret(catalog, change):
    tunnel = create_tunnel(catalog, password="before")
    tunnel["config"].update(change)
    edited = catalog.save_tunnel(tunnel)
    assert not edited["has_password"] and not edited["has_passphrase"]
    assert not catalog.credentials.get(catalog.tunnel_credential_id(tunnel["id"]))


def test_tunnel_disk_tampering_cannot_reuse_secret(catalog):
    tunnel = create_tunnel(catalog, password="secret")
    catalog.data["ssh_tunnels"][0]["config"]["host"] = "attacker.example"
    assert not catalog.tunnel_config(tunnel["id"]).get("password")


def test_save_tunnel_rolls_back_disk_failure_and_secret(catalog, monkeypatch):
    tunnel = create_tunnel(catalog, password="before")
    before = deepcopy(catalog.data)
    monkeypatch.setattr(catalog, "_save", lambda: (_ for _ in ()).throw(OSError("disk full")))
    with pytest.raises(OSError, match="disk full"):
        catalog.save_tunnel(tunnel, password="after")
    assert catalog.data == before and catalog.tunnel_config(tunnel["id"])["password"] == "before"


def test_deleting_tunnel_protects_saved_connections_and_clone(catalog):
    tunnel = create_tunnel(catalog, password="secret")
    saved = catalog.save_connection(connection(tunnel["id"]))
    clone = catalog.dispatch("connections.clone", {"connection_id": saved["id"]})
    catalog.dispatch("connections.delete", {"connection_id": saved["id"]})
    with pytest.raises(ValueError, match="em uso"):
        catalog.dispatch("ssh.tunnels.delete", {"tunnel_id": tunnel["id"]})
    assert catalog.config(clone["id"])["ssh"]["password"] == "secret"
    clone["config"]["ssh_tunnel_id"] = None
    catalog.save_connection(clone)
    catalog.dispatch("ssh.tunnels.delete", {"tunnel_id": tunnel["id"]})
    assert not catalog.data["ssh_tunnels"] and not catalog.credentials.get(catalog.tunnel_credential_id(tunnel["id"]))


def test_reference_is_authoritative_over_stale_embedded_config(catalog):
    tunnel = create_tunnel(catalog, password="current-secret")
    draft = connection(tunnel["id"])["config"]
    draft["ssh"] = tunnel_config(host="stale.example", password="old-secret")
    result = broker(catalog)._route({"config": draft})["config"]
    assert result["ssh"]["host"] == "vps.example" and result["ssh"]["password"] == "current-secret"
    assert result["_ssh_catalog_path"] == str(catalog.path)
    draft["ssh_tunnel_id"] = "missing"
    with pytest.raises(SshTunnelError) as error:
        broker(catalog)._route({"config": draft})
    assert error.value.code == "ssh_tunnel_missing"
    draft["ssh_tunnel_id"] = None
    result = broker(catalog)._route({"config": draft})["config"]
    assert "ssh" not in result and "_ssh_catalog_path" not in result


@pytest.mark.parametrize("reference", ["connection_id", "credential_connection_id"])
def test_test_and_transient_reconnect_resolve_database_and_ssh_separately(catalog, reference):
    tunnel = create_tunnel(catalog, password="ssh-secret")
    saved = catalog.save_connection(connection(tunnel["id"]), password="db-secret", save_password=True)
    draft = deepcopy(saved["config"])
    draft.update(password="", database="different-context")
    result = connection_test_config(broker(catalog)._route({reference: saved["id"], "config": draft}))
    assert result["password"] == "db-secret" and result["ssh"]["password"] == "ssh-secret"
    result = connection_test_config(broker(catalog)._route({reference: saved["id"], "config": draft,
                                                          "resolve_database_password": False}))
    assert result.get("password", "") == "" and result["ssh"]["password"] == "ssh-secret"


def test_legacy_tunnels_migrate_without_losing_distinct_secrets(catalog):
    for index, secret in enumerate(["first", "first", "second"]):
        draft = connection(None, str(index))
        draft["config"].pop("ssh_tunnel_id")
        draft["config"]["ssh"] = tunnel_config(password=secret)
        catalog.save_connection(draft)
    reloaded = ConnectionCatalog(catalog.path, catalog.credentials)
    assert len(reloaded.data["ssh_tunnels"]) == 2
    refs = [item["config"]["ssh_tunnel_id"] for item in reloaded.data["connections"]]
    assert refs[0] == refs[1] and refs[0] != refs[2]
    for item, secret in zip(reloaded.data["connections"], ["first", "first", "second"]):
        assert "ssh" not in item["config"] and not item["has_ssh_password"]
        assert reloaded.config(item["id"])["ssh"]["password"] == secret
        assert not catalog.credentials.get(f"{item['id']}:ssh")
    assert "first" not in catalog.path.read_text() and "second" not in catalog.path.read_text()
    assert ConnectionCatalog(catalog.path, catalog.credentials).list() == reloaded.list()


def test_failed_migration_keeps_original_catalog_and_credentials(catalog, monkeypatch):
    draft = connection(None)
    draft["config"].pop("ssh_tunnel_id")
    draft["config"]["ssh"] = tunnel_config(password="preserved")
    catalog.save_connection(draft)
    before, secrets = catalog.path.read_bytes(), deepcopy(catalog.credentials.values)
    monkeypatch.setattr(ConnectionCatalog, "_save", lambda _: (_ for _ in ()).throw(OSError("disk full")))
    with pytest.raises(OSError, match="disk full"):
        ConnectionCatalog(catalog.path, catalog.credentials)
    assert catalog.path.read_bytes() == before and catalog.credentials.values == secrets


@pytest.mark.parametrize("format_name", ["tauri", "pyqt6"])
def test_portable_tunnel_export_import_remaps_ids_without_secrets(catalog, tmp_path, format_name):
    tunnel = create_tunnel(catalog, password="private")
    catalog.save_connection(connection(tunnel["id"]))
    exported = catalog.export_document(format_name)
    assert not exported["ssh_tunnels"][0]["has_password"] and "private" not in json.dumps(exported)
    destination = ConnectionCatalog(tmp_path / "imported.json", Secrets())
    destination.import_document(exported)
    copied = destination.list()["ssh_tunnels"][0]
    assert copied["id"] != tunnel["id"] and not copied["has_password"]
    assert destination.list()["connections"][0]["config"]["ssh_tunnel_id"] == copied["id"]
    assert destination.config(destination.data["connections"][0]["id"])["ssh"]["host"] == "vps.example"


def test_invalid_import_rolls_back_without_keyring_access(catalog, monkeypatch):
    tunnel = create_tunnel(catalog, password="preserved")
    catalog.save_connection(connection(tunnel["id"]))
    before = catalog.list()
    monkeypatch.setattr(catalog.credentials, "get", lambda *_: pytest.fail("Import validation must not read credentials"))
    exported = catalog.export_document("tauri")
    exported["connections"][0]["config"]["ssh_tunnel_id"] = "missing"
    with pytest.raises(ValueError, match="unknown SSH tunnel"):
        catalog.import_document(exported)
    assert catalog.list() == before


def test_legacy_import_migrates_without_looking_up_existing_secrets(catalog, monkeypatch):
    create_tunnel(catalog, password="preserved")
    monkeypatch.setattr(catalog.credentials, "get", lambda *_: pytest.fail("Import preview must not read credentials"))
    draft = connection(None, "Imported")
    draft["config"].pop("ssh_tunnel_id")
    draft["config"]["ssh"] = tunnel_config(password="untrusted")
    outcome = catalog.import_document({"version": 1, "groups": [], "connections": [draft]})
    assert "ssh_tunnel_id" in outcome["catalog"]["connections"][0]["config"]
    assert len(outcome["catalog"]["ssh_tunnels"]) == 2 and "untrusted" not in catalog.path.read_text()


def test_standalone_test_is_ssh_authentication_only(local_ssh, tmp_path):
    trust = SshTrustStore(tmp_path / "trust.json")
    params = {"config": local_ssh.config(), "_ssh_trust_path": str(trust.path)}
    with pytest.raises(SshTunnelError) as challenge:
        authenticate_tunnel(params)
    assert challenge.value.code == "ssh_host_key_unknown" and local_ssh.auth == []
    trust.confirm(challenge.value.details)
    assert authenticate_tunnel(params)["success"]
    assert local_ssh.auth == [("tester", "password")] and local_ssh.destinations == []
    deadline = time.monotonic() + 2
    while any(transport.is_active() for transport in local_ssh.transports) and time.monotonic() < deadline:
        time.sleep(0.01)
    assert all(not transport.is_active() for transport in local_ssh.transports)


def test_broker_standalone_test_merges_only_same_identity_and_pins_profile(catalog):
    tunnel = create_tunnel(catalog, password="preserved")
    supervisor = broker(catalog)
    calls = []
    class Background:
        def submit(self, *args):
            calls.append(args)
    supervisor.background = Background()
    params = {"tunnel_id": tunnel["id"], "config": {**tunnel["config"], "password": ""}, "test_id": "test"}
    supervisor.dispatch("ssh.tunnels.test", params, 4)
    routed = calls[-1][2]
    assert routed["config"]["password"] == "preserved"
    assert routed["_ssh_trust_path"] == str(catalog.path.parent / "ssh_known_hosts.json")
    params["config"]["host"] = "other.example"
    supervisor.dispatch("ssh.tunnels.test", params, 5)
    assert not calls[-1][2]["config"].get("password")


def test_testing_changed_tunnel_identity_does_not_read_stored_secrets(catalog, monkeypatch):
    tunnel = create_tunnel(catalog, password="preserved")
    supervisor = broker(catalog)
    class Background:
        def submit(self, *args):
            assert not args[2]["config"].get("password")
    supervisor.background = Background()
    monkeypatch.setattr(catalog.credentials, "get", lambda *_: pytest.fail("A new SSH identity cannot read previous credentials"))
    supervisor.dispatch("ssh.tunnels.test", {"tunnel_id": tunnel["id"], "config": {**tunnel["config"], "host": "another"}}, 8)


def test_configuration_folder_roundtrip_preserves_reusable_references_without_credentials(tmp_path):
    from datapyn_runtime.configurations import ConfigurationTransfer
    catalog = ConnectionCatalog(tmp_path / "source-workspace" / "connections.json", Secrets())
    tunnel = create_tunnel(catalog, password="private-secret")
    catalog.save_connection(connection(tunnel["id"]))
    transfer = ConfigurationTransfer(catalog.path.parent, catalog)
    source = tmp_path / "portable"
    transfer.export_folder({"path": str(source)})
    document = json.loads((source / "connections.json").read_text())
    assert "private-secret" not in json.dumps(document) and not document["ssh_tunnels"][0]["has_password"]
    destination = ConnectionCatalog(tmp_path / "destination" / "connections.json", Secrets())
    other = ConfigurationTransfer(destination.path.parent, destination)
    preview = other.inspect({"path": str(source)})
    outcome = other.import_folder({"path": str(source), "preview_token": preview["preview_token"]})
    tunnel = outcome["catalog"]["ssh_tunnels"][0]
    assert not tunnel["has_password"] and outcome["catalog"]["connections"][0]["config"]["ssh_tunnel_id"] == tunnel["id"]


@pytest.mark.parametrize("default", [False, True])
def test_pool_refreshes_default_and_block_only_tunnel_revisions(catalog, monkeypatch, default):
    import datapyn_runtime.database as database
    import datapyn_runtime.connection_catalog as catalog_module
    monkeypatch.setattr(catalog_module, "CredentialStore", lambda: catalog.credentials)
    tunnel = create_tunnel(catalog, password="before")
    routed = broker(catalog)._route({"config": connection(tunnel["id"])["config"]})
    opened = []
    class Connector:
        closed = False
        def disconnect(self):
            self.closed = True
    monkeypatch.setattr(database, "connect", lambda config: opened.append((deepcopy(config), Connector())) or opened[-1][1])
    pool = database.ConnectorPool()
    first = pool.activate(routed, default=default)
    catalog.save_tunnel(tunnel, password="after")
    replacement = pool.activate({})
    assert first.closed and replacement is not first and len(opened) == 2
    assert opened[-1][0]["ssh"]["password"] == "after"
    if default:
        assert pool.default_active_key == pool.active_key and pool.default_config["ssh"]["password"] == "after"
    catalog.dispatch("ssh.tunnels.delete", {"tunnel_id": tunnel["id"]})
    with pytest.raises(SshTunnelError):
        pool.activate({})
    assert replacement.closed and not pool.items


def test_pool_cached_catalog_does_not_read_keyring_for_each_query(catalog, monkeypatch):
    import datapyn_runtime.database as database
    import datapyn_runtime.connection_catalog as catalog_module
    monkeypatch.setattr(catalog_module, "CredentialStore", lambda: catalog.credentials)
    tunnel = create_tunnel(catalog, password="before")
    config = broker(catalog)._route({"config": connection(tunnel["id"])["config"]})["config"]
    reads = []
    original = catalog.credentials.get
    monkeypatch.setattr(catalog.credentials, "get", lambda key: reads.append(key) or original(key))
    class Connector:
        def disconnect(self):
            pass
    monkeypatch.setattr(database, "connect", lambda _: Connector())
    pool = database.ConnectorPool()
    for _ in range(12):
        resolved = pool._current_tunnel_config(config)
        assert resolved["ssh"]["password"] == "before"
    assert reads == [catalog.tunnel_credential_id(tunnel["id"])]
    catalog.save_tunnel(tunnel, password="after")
    reads.clear()
    assert pool._current_tunnel_config(config)["ssh"]["password"] == "after"
    assert reads == [catalog.tunnel_credential_id(tunnel["id"])]


def test_tunnel_revision_invalidation_does_not_change_other_default_connection(catalog, monkeypatch):
    import datapyn_runtime.database as database
    import datapyn_runtime.connection_catalog as catalog_module
    monkeypatch.setattr(catalog_module, "CredentialStore", lambda: catalog.credentials)
    tunnel = create_tunnel(catalog, password="before")
    first = catalog.save_connection(connection(tunnel["id"], "First"))
    second = catalog.save_connection(connection(tunnel["id"], "Second"))
    class Connector:
        closed = False
        def disconnect(self):
            self.closed = True
    monkeypatch.setattr(database, "connect", lambda _: Connector())
    pool = database.ConnectorPool()
    initial = pool.activate(broker(catalog)._route({"connection_id": first["id"]}), default=True)
    catalog.save_tunnel(tunnel, password="after")
    pool.activate(broker(catalog)._route({"connection_id": second["id"]}))
    assert initial.closed and pool.default_id == first["id"] and pool.default_active_key is None
    pool.activate({})
    assert pool.default_id == first["id"] and pool.active_key[0] == first["id"]


@pytest.mark.parametrize("include_credentials", [False, True])
def test_profile_clone_remaps_reusable_tunnels_and_never_copies_trust(tmp_path, monkeypatch, include_credentials):
    from datapyn_runtime import profiles
    import datapyn_runtime.connection_catalog as catalog_module
    root = tmp_path / "preview"
    monkeypatch.setenv("DATAPYN_RUNTIME_STATE_PATH", str(root))
    monkeypatch.setenv("DATAPYN_WORKSPACE_PATH", str(root))
    profiles.close_stores()
    profiles.list_profiles()
    secrets = Secrets()
    monkeypatch.setattr(catalog_module, "CredentialStore", lambda: secrets)
    catalog = ConnectionCatalog(root / "connections.json", secrets)
    tunnel = create_tunnel(catalog, password="ssh-secret")
    saved = catalog.save_connection(connection(tunnel["id"]))
    (root / "ssh_known_hosts.json").write_text('{"trust":true}')
    try:
        clone = profiles.clone({"profile_id": "default", "name": "Clone", "include_credentials": include_credentials})
        copied = ConnectionCatalog(Path(clone["path"]) / "connections.json", secrets)
        entry = copied.list()["ssh_tunnels"][0]
        assert entry["id"] != tunnel["id"] and entry["has_password"] is include_credentials
        assert copied.data["connections"][0]["id"] != saved["id"]
        assert copied.data["connections"][0]["config"]["ssh_tunnel_id"] == entry["id"]
        assert copied.config(copied.data["connections"][0]["id"])["ssh"].get("password") == ("ssh-secret" if include_credentials else None)
        assert not (Path(clone["path"]) / "ssh_known_hosts.json").exists()
    finally:
        profiles.close_stores()
