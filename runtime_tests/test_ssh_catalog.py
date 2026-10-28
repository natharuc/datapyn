"""SSH credentials and server trust survive catalog/worker boundaries safely."""

from copy import deepcopy
import json

import pytest

from datapyn_runtime.connection_catalog import ConnectionCatalog, CredentialStore, without_secrets
from datapyn_runtime.database import connection_test_config
from datapyn_runtime.errors import serialize_runtime_error
from datapyn_runtime.ssh_tunnel import SshTunnelError
from test_connection_catalog import Secrets


@pytest.fixture
def catalog(tmp_path):
    return ConnectionCatalog(tmp_path / "connections.json", Secrets())


def profile(**ssh):
    return {"name": "STG", "config": {"db_type": "postgresql", "host": "127.0.0.1", "port": 5433,
            "database": "docfis", "username": "db-user", "sslmode": "verify-full",
            "ssh": {"enabled": True, "host": "vps.example", "port": 22, "username": "ssh-user",
                    "auth_method": "password", **ssh}}}


def test_ssh_secrets_are_separate_and_never_exported(catalog):
    saved = catalog.save_connection(profile(password="ssh-secret"), password="db-secret", save_password=True)
    identifier = saved["id"]
    assert saved["has_password"] and saved["has_ssh_password"]
    assert not saved["has_ssh_passphrase"]
    assert catalog.credentials.get(identifier) == {"password": "db-secret"}
    assert catalog.credentials.get(f"{identifier}:ssh")["password"] == "ssh-secret"
    config = catalog.config(identifier)
    assert config["password"] == "db-secret" and config["ssh"]["password"] == "ssh-secret"
    assert config["sslmode"] == "verify-full"
    for public in (saved, catalog.list(), catalog.export_document("tauri"), catalog.export_document("pyqt6")):
        assert "ssh-secret" not in json.dumps(public) and "db-secret" not in json.dumps(public)
    assert "ssh-secret" not in catalog.path.read_text()
    exported = catalog.dispatch("connections.export_config", {"connection_id": identifier, "include_password": True})
    assert exported["config"]["password"] == "db-secret"
    assert "password" not in exported["config"]["ssh"]


def test_blank_edit_and_group_move_preserve_ssh_credentials(catalog):
    saved = catalog.save_connection(profile(password="ssh-secret"))
    saved["config"]["ssh"]["password"] = ""
    updated = catalog.save_connection(saved, ssh_password="", save_ssh_credentials=True)
    assert updated["has_ssh_password"]
    assert catalog.config(saved["id"])["ssh"]["password"] == "ssh-secret"
    group = catalog.save_group({"name": "Production"})
    moved = catalog.dispatch("connections.move", {"connection_id": saved["id"], "group_id": group["id"]})
    assert moved["has_ssh_password"] and catalog.config(saved["id"])["ssh"]["password"] == "ssh-secret"


@pytest.mark.parametrize("change", [{"host": "another.example"}, {"port": 2222}, {"username": "other"},
                                   {"auth_method": "private_key", "private_key_path": "key.pem"}])
def test_changing_ssh_identity_never_reuses_old_password(catalog, change):
    saved = catalog.save_connection(profile(password="old-secret"))
    saved["config"]["ssh"].update(change)
    edited = catalog.save_connection(saved)
    assert not edited["has_ssh_password"] and not edited["has_ssh_passphrase"]
    assert not catalog.config(saved["id"])["ssh"].get("password")
    assert not catalog.credentials.get(f"{saved['id']}:ssh")


def test_changing_private_key_path_clears_its_passphrase(catalog):
    saved = catalog.save_connection(profile(auth_method="private_key", private_key_path="first.pem", passphrase="phrase"))
    assert saved["has_ssh_passphrase"]
    saved["config"]["ssh"]["private_key_path"] = "second.pem"
    edited = catalog.save_connection(saved)
    assert not edited["has_ssh_passphrase"] and "passphrase" not in catalog.config(saved["id"])["ssh"]


def test_disk_tampering_cannot_send_saved_secret_to_another_ssh_host(catalog):
    saved = catalog.save_connection(profile(password="pinned-secret"))
    catalog.data["connections"][0]["config"]["ssh"]["host"] = "attacker.example"
    assert "password" not in catalog.config(saved["id"])["ssh"]


def test_ssh_clone_and_delete_own_independent_secrets(catalog):
    saved = catalog.save_connection(profile(auth_method="private_key", private_key_path="key.pem", passphrase="phrase"))
    clone = catalog.dispatch("connections.clone", {"connection_id": saved["id"]})
    assert clone["has_ssh_passphrase"] and catalog.config(clone["id"])["ssh"]["passphrase"] == "phrase"
    catalog.dispatch("connections.delete", {"connection_id": saved["id"]})
    assert not catalog.credentials.get(f"{saved['id']}:ssh")
    assert catalog.config(clone["id"])["ssh"]["passphrase"] == "phrase"


def test_ssh_credential_choice_is_independent_of_database_password(catalog):
    saved = catalog.save_connection(profile(password="ssh-secret"), password="db-secret", save_password=True)
    edited = catalog.save_connection(saved, save_password=False)
    assert not edited["has_password"] and edited["has_ssh_password"]
    edited = catalog.save_connection(edited, save_ssh_credentials=False)
    assert not edited["has_ssh_password"] and not catalog.credentials.get(f"{saved['id']}:ssh")


def test_disabled_ssh_is_backward_compatible_and_does_not_require_keyring(catalog, monkeypatch):
    monkeypatch.setattr(catalog.credentials, "set", lambda *_: pytest.fail("disabled SSH must not touch keyring"))
    saved = catalog.save_connection(profile(enabled=False), save_ssh_credentials=False)
    assert not saved["has_ssh_password"]


def test_ssh_import_removes_credentials_only_after_document_validates(catalog):
    saved = catalog.save_connection(profile(password="before"))
    imported = profile(password="untrusted-import", passphrase="untrusted-phrase")
    document = {"version": 1, "connections": [imported, {"name": "bad", "config": {"db_type": "unknown"}}], "groups": []}
    with pytest.raises(ValueError):
        catalog.import_document(document)
    assert catalog.config(saved["id"])["ssh"]["password"] == "before"
    document["connections"].pop()
    result = catalog.import_document(document)
    assert not result["passwords_imported"]
    public = result["catalog"]["connections"][0]
    assert not public["has_ssh_password"] and not public["has_ssh_passphrase"]
    assert not catalog.credentials.get(f"{saved['id']}:ssh")
    assert "untrusted-import" not in catalog.path.read_text()


def test_failed_catalog_write_rolls_back_ssh_credential_replacement(catalog, monkeypatch):
    saved = catalog.save_connection(profile(password="before"))
    monkeypatch.setattr(catalog, "_save", lambda: (_ for _ in ()).throw(OSError("disk full")))
    with pytest.raises(OSError, match="disk full"):
        catalog.save_connection(saved, ssh_password="after")
    assert catalog.config(saved["id"])["ssh"]["password"] == "before"


@pytest.mark.parametrize("module", ["keyrings.alt.file", "keyring.backends.null", "keyring.backends.fail", "custom.unknown"])
def test_credential_store_refuses_plaintext_or_unknown_backends(monkeypatch, module):
    import keyring
    backend = type("Backend", (), {"__module__": module, "priority": 1})()
    monkeypatch.setattr(keyring, "get_keyring", lambda: backend)
    with pytest.raises(RuntimeError, match="Secure OS credential storage"):
        CredentialStore().set("id:ssh", {"password": "secret"})


def test_secure_backend_is_selected_without_using_global_fallback(monkeypatch):
    import keyring
    stored = {}
    backend = type("Backend", (), {"__module__": "keyring.backends.Windows", "priority": 1,
                                  "set_password": lambda _, service, name, value: stored.update({name: value}),
                                  "get_password": lambda _, service, name: stored.get(name)})()
    monkeypatch.setattr(keyring, "get_keyring", lambda: backend)
    store = CredentialStore()
    store.set("id:ssh", {"password": "secret"})
    assert store.get("id:ssh") == {"password": "secret"}


@pytest.mark.parametrize("changed", [False, True])
def test_draft_test_preserves_credentials_only_for_same_ssh_identity(changed):
    stored = profile(password="stored-ssh")["config"]
    stored["password"] = "stored-db"
    draft = deepcopy(stored)
    draft["ssh"]["password"] = ""
    draft["password"] = ""
    if changed:
        draft["ssh"]["host"] = "other.example"
    merged = connection_test_config({"_connection_config": stored, "config": draft})
    assert merged["password"] == "stored-db"
    assert merged["ssh"].get("password") == (None if changed else "stored-ssh")
    assert stored["ssh"]["password"] == "stored-ssh"


def test_draft_test_replacement_credentials_and_auth_switch():
    stored = profile(password="old")["config"]
    draft = profile(auth_method="private_key", private_key_path="key.pem", passphrase="new")["config"]
    merged = connection_test_config({"_connection_config": stored, "config": draft})
    assert merged["ssh"]["passphrase"] == "new" and "password" not in merged["ssh"]


def test_error_envelope_retains_only_public_server_challenge():
    details = {"host": "vps.example", "port": 22, "key_type": "ssh-ed25519", "public_key": "PUBLIC",
               "fingerprint": "SHA256:abc", "password": "secret", "passphrase": "secret", "debug": "private"}
    result = serialize_runtime_error(SshTunnelError("Confirm server identity", code="ssh_host_key_unknown", details=details))
    assert result["code"] == "ssh_host_key_unknown" and result["details"]["public_key"] == "PUBLIC"
    assert "secret" not in json.dumps(result) and "debug" not in result["details"]
    assert "_ssh_trust_path" not in without_secrets({"_ssh_trust_path": "private/profile.json"})


def test_background_worker_preserves_ssh_challenge(monkeypatch):
    from datapyn_runtime import background, database
    monkeypatch.setattr(background, "initialize_kernel_group", lambda: None)
    monkeypatch.setattr(background, "isolate_kernel_output", lambda: None)
    error = SshTunnelError("Confirm server", code="ssh_host_key_unknown", details={"host": "vps.example", "port": 22})
    monkeypatch.setattr(database, "test_connection", lambda _: (_ for _ in ()).throw(error))
    class Pipe:
        message = None
        def send(self, message):
            self.message = message
        def close(self):
            pass
    pipe = Pipe()
    background._task_main("connection.test", {}, {}, pipe)
    assert pipe.message["error"]["code"] == "ssh_host_key_unknown"
    assert pipe.message["error"]["details"]["host"] == "vps.example"


def test_broker_overrides_user_trust_path_and_keeps_profile_isolation(catalog, tmp_path):
    from datapyn_runtime.supervisor import Supervisor
    supervisor = Supervisor.__new__(Supervisor)
    supervisor._catalog = catalog
    supervisor.profile_path = tmp_path / "profile-A"
    source = profile()["config"]
    source["_ssh_trust_path"] = "attacker.json"
    routed = supervisor._route({"config": source})
    assert routed["config"]["_ssh_trust_path"] == str(supervisor.profile_path / "ssh_known_hosts.json")
    assert source["_ssh_trust_path"] == "attacker.json"
    saved = catalog.save_connection(profile(password="secret"))
    routed = supervisor._route({"connection_id": saved["id"]})
    assert routed["_connection_config"]["ssh"]["password"] == "secret"
    assert routed["_connection_config"]["_ssh_trust_path"] == str(supervisor.profile_path / "ssh_known_hosts.json")


def test_broker_preserves_structured_ssh_errors_even_when_they_are_oserrors(tmp_path):
    from datapyn_runtime.supervisor import Supervisor
    supervisor = Supervisor.__new__(Supervisor)
    responses = []
    supervisor.emit = responses.append
    error = SshTunnelError("Changed server key", code="ssh_host_key_changed",
                           details={"host": "vps.example", "port": 22, "expected_fingerprint": "SHA256:old"})
    supervisor.dispatch = lambda *_: (_ for _ in ()).throw(error)
    supervisor.receive({"id": 7, "method": "ssh.host_key.trust", "params": {}})
    assert responses[0]["error"]["code"] == "ssh_host_key_changed"
    assert responses[0]["error"]["details"]["expected_fingerprint"] == "SHA256:old"


def test_broker_host_key_trust_rpc_uses_its_profile_store(tmp_path, monkeypatch):
    from datapyn_runtime.supervisor import Supervisor
    import datapyn_runtime.ssh_tunnel as ssh
    supervisor = Supervisor.__new__(Supervisor)
    supervisor.profile_path = tmp_path / "isolated-profile"
    details = {"host": "vps.example", "port": 22, "fingerprint": "SHA256:abc"}
    captured = []
    class TrustStore:
        def __init__(self, path):
            captured.append(path)
        def confirm(self, provided):
            assert provided == details
            return provided
    monkeypatch.setattr(ssh, "SshTrustStore", TrustStore)
    assert supervisor.dispatch("ssh.host_key.trust", {"details": details}, 8) == details
    assert captured == [supervisor.profile_path / "ssh_known_hosts.json"]


def test_pool_releases_every_connection_when_one_disconnect_fails():
    from datapyn_runtime.database import ConnectorPool
    closed = []
    class Connector:
        def __init__(self, name):
            self.name = name
        def disconnect(self):
            closed.append(self.name)
            if self.name == "first":
                raise OSError("database close failed")
    pool = ConnectorPool()
    pool.items[("a", "first")] = Connector("first")
    pool.items[("b", "second")] = Connector("second")
    with pytest.raises(OSError):
        pool.disconnect()
    assert closed == ["first", "second"] and not pool.items


def test_configuration_transfer_never_imports_or_exports_host_trust(catalog, tmp_path):
    from datapyn_runtime.configurations import ConfigurationTransfer
    transfer = ConfigurationTransfer(catalog.path.parent / "workspace", catalog)
    source = tmp_path / "external-configuration"
    source.mkdir()
    (source / "SSH_KNOWN_HOSTS.json").write_text('{"version":1,"hosts":{"blindly-trusted":{}}}')
    (source / "ssh-known-hosts.json").write_text('{"version":1,"hosts":{}}')
    (source / "extension.json").write_text('{"keep":true}')
    preview = transfer.inspect({"path": str(source)})
    assert {"SSH_KNOWN_HOSTS.json", "ssh-known-hosts.json"}.issubset(preview["excluded_files"])
    transfer.import_folder({"path": str(source), "preview_token": preview["preview_token"]})
    assert not (transfer.workspace / "ssh_known_hosts.json").exists()
    assert not (transfer.archive / "SSH_KNOWN_HOSTS.json").exists()
    # Even archives created by older versions cannot turn a pin into portable settings.
    (transfer.archive / "ssh_known_hosts.json").write_text('{"hosts":{"unsafe":{}}}')
    exported = tmp_path / "exported"
    transfer.export_folder({"path": str(exported)})
    assert not (exported / "ssh_known_hosts.json").exists()
    assert (exported / "extension.json").read_text() == '{"keep":true}'


@pytest.mark.parametrize("auth", ["password", "private_key"])
def test_transient_reconnect_uses_saved_ssh_secret_without_reverting_to_saved_config(catalog, tmp_path, monkeypatch, auth):
    from datapyn_runtime.supervisor import Supervisor
    import datapyn_runtime.database as database
    secret = "password" if auth == "password" else "passphrase"
    initial = profile(auth_method=auth, private_key_path="key.pem", **{secret: "ssh-secret"})
    saved = catalog.save_connection(initial, password="db-secret", save_password=True)
    draft = deepcopy(saved["config"])
    draft["password"] = ""
    draft["ssh"][secret] = ""
    draft["database"] = "another-focused-database"
    supervisor = Supervisor.__new__(Supervisor)
    supervisor._catalog, supervisor.profile_path = catalog, tmp_path
    routed = supervisor._route({"credential_connection_id": saved["id"], "config": draft})
    assert "connection_id" not in routed and "credential_connection_id" not in routed
    assert routed["_connection_config"]["database"] == "another-focused-database"
    assert routed["_connection_config"]["ssh"][secret] == "ssh-secret"
    assert routed["_connection_config"]["password"] == "db-secret"
    captured = []
    monkeypatch.setattr(database, "connect", lambda config: captured.append(deepcopy(config)) or object())
    pool = database.ConnectorPool()
    pool.activate(routed, default=True)
    assert pool.default_id is None and pool.active_key[0] == "transient"
    assert captured[0]["ssh"][secret] == "ssh-secret" and captured[0]["database"] == draft["database"]


@pytest.mark.parametrize("change", ["ssh-host", "ssh-user", "ssh-auth", "database-host", "database-user"])
def test_transient_credential_reference_never_reads_secrets_for_a_different_identity(catalog, tmp_path, monkeypatch, change):
    from datapyn_runtime.supervisor import Supervisor
    saved = catalog.save_connection(profile(password="ssh-secret"), password="db-secret", save_password=True)
    draft = deepcopy(saved["config"])
    draft["password"] = ""
    draft["ssh"]["password"] = ""
    if change == "ssh-host":
        draft["ssh"]["host"] = "another-vps.example"
    elif change == "ssh-user":
        draft["ssh"]["username"] = "another-user"
    elif change == "ssh-auth":
        draft["ssh"].update(auth_method="private_key", private_key_path="new.pem")
    elif change == "database-host":
        draft["host"] = "another-db.example"
    else:
        draft["username"] = "another-db-user"
    reads = []
    read = catalog.credentials.get
    monkeypatch.setattr(catalog.credentials, "get", lambda key: reads.append(key) or read(key))
    supervisor = Supervisor.__new__(Supervisor)
    supervisor._catalog, supervisor.profile_path = catalog, tmp_path
    resolved = supervisor._route({"credential_connection_id": saved["id"], "config": draft})["_connection_config"]
    assert not resolved.get("password") and saved["id"] not in reads
    if change.startswith("ssh-"):
        assert not resolved["ssh"].get("password") and not resolved["ssh"].get("passphrase")
        assert reads == []
    else:
        assert resolved["ssh"]["password"] == "ssh-secret" and reads == [f"{saved['id']}:ssh"]


@pytest.mark.parametrize("reference", ["connection_id", "credential_connection_id"])
def test_pasted_database_credentials_do_not_disable_saved_ssh_lookup(catalog, tmp_path, monkeypatch, reference):
    from datapyn_runtime.supervisor import Supervisor
    saved = catalog.save_connection(profile(password="ssh-secret"), password="old-db-secret", save_password=True)
    draft = deepcopy(saved["config"])
    draft["password"] = "new-pasted-secret"
    draft["ssh"]["password"] = ""
    reads = []
    read = catalog.credentials.get
    monkeypatch.setattr(catalog.credentials, "get", lambda key: reads.append(key) or read(key))
    supervisor = Supervisor.__new__(Supervisor)
    supervisor._catalog, supervisor.profile_path = catalog, tmp_path
    routed = supervisor._route({reference: saved["id"], "config": draft, "resolve_database_password": False})
    resolved = connection_test_config(routed)
    assert resolved["password"] == "new-pasted-secret" and resolved["ssh"]["password"] == "ssh-secret"
    assert reads == [f"{saved['id']}:ssh"]


def test_disabled_ssh_and_missing_ssh_do_not_read_or_inherit_old_ssh_credentials(catalog, tmp_path, monkeypatch):
    from datapyn_runtime.supervisor import Supervisor
    saved = catalog.save_connection(profile(password="ssh-secret"), password="db-secret", save_password=True)
    monkeypatch.setattr(catalog.credentials, "get", lambda _: pytest.fail("disabled/different target must not read stored credentials"))
    supervisor = Supervisor.__new__(Supervisor)
    supervisor._catalog, supervisor.profile_path = catalog, tmp_path
    for missing in (False, True):
        draft = deepcopy(saved["config"])
        if missing:
            draft.pop("ssh")
        else:
            draft["ssh"]["enabled"] = False
        resolved = supervisor._route({"credential_connection_id": saved["id"], "config": draft})["_connection_config"]
        assert not resolved.get("password")
        if missing:
            assert "ssh" not in resolved
        else:
            assert not resolved["ssh"]["enabled"] and not resolved["ssh"].get("password")


@pytest.mark.parametrize("default", [False, True])
def test_reconnect_replaces_dead_ssh_transport_and_preserves_default_focus(monkeypatch, default):
    import datapyn_runtime.database as database
    class Tunnel:
        alive = True
        def is_alive(self):
            return self.alive
    class Connector:
        def __init__(self):
            self._ssh_tunnel = Tunnel()
            self.closed = False
        def disconnect(self):
            self.closed = True
            self._ssh_tunnel.alive = False
    opened = []
    def connect(config):
        connector = Connector()
        opened.append((deepcopy(config), connector))
        return connector
    monkeypatch.setattr(database, "connect", connect)
    pool = database.ConnectorPool()
    config = profile(password="ssh-secret")["config"]
    params = {"connection_id": "saved", "_connection_config": config, "database": "focused", "schema": "reporting"}
    previous = pool.activate(params, default=True)
    previous_key = pool.active_key
    pool.explorers[previous_key] = object()
    pool.block_affinity["block"] = previous_key
    previous._ssh_tunnel.alive = False
    replacement = pool.activate(params, default=default)
    assert replacement is not previous and previous.closed and len(opened) == 2
    assert opened[1][0]["database"] == "focused" and opened[1][0]["schema"] == "reporting"
    assert pool.default_id == "saved" and pool.default_active_key == pool.active_key == previous_key
    assert pool.default_config["database"] == "focused" and pool.default_config["schema"] == "reporting"
    assert previous_key not in pool.explorers and pool.block_affinity["block"] == previous_key
    assert pool.activate(params) is replacement and len(opened) == 2


def test_dead_ssh_reconnect_never_reports_success_when_authentication_fails(monkeypatch):
    import datapyn_runtime.database as database
    class Tunnel:
        def is_alive(self):
            return False
    class Connector:
        _ssh_tunnel = Tunnel()
        def disconnect(self):
            raise OSError("old engine cleanup failure")
    pool = database.ConnectorPool()
    config = profile()["config"]
    key = pool._key("saved", config)
    pool.items[key] = Connector()
    pool.configs[key] = config
    pool.active_key = pool.default_active_key = key
    pool.default_config, pool.default_id = config, "saved"
    error = SshTunnelError("SSH authentication failed", code="ssh_auth_failed")
    monkeypatch.setattr(database, "connect", lambda _: (_ for _ in ()).throw(error))
    with pytest.raises(SshTunnelError, match="authentication failed") as rejected:
        pool.activate({"connection_id": "saved", "_connection_config": config}, default=True)
    assert rejected.value is error
    # Keep the dead lane's identity so the same tab can explicitly retry. It is
    # never returned as usable while its tunnel remains dead.
    assert list(pool.items) == [key] and pool.active_key == pool.default_active_key == key
    assert pool.last_recovery["phase"] == "error"
    assert pool.default_config == config and pool.default_id == "saved"


def test_ssh_block_only_connection_reconnects_without_a_default(monkeypatch):
    import datapyn_runtime.database as database
    class Tunnel:
        alive = True
        def is_alive(self):
            return self.alive
    class Connector:
        def __init__(self):
            self._ssh_tunnel = Tunnel()
        def disconnect(self):
            self._ssh_tunnel.alive = False
    opened = []
    monkeypatch.setattr(database, "connect", lambda _: opened.append(Connector()) or opened[-1])
    pool = database.ConnectorPool()
    first = pool.activate({"config": profile()["config"]})
    first._ssh_tunnel.alive = False
    assert pool.default_config is None
    replacement = pool.activate({})
    assert replacement is not first and len(opened) == 2 and pool.active_key[0] == "transient"


def test_direct_connection_cache_behavior_is_preserved(monkeypatch):
    import datapyn_runtime.database as database
    connector = object()
    opened = []
    monkeypatch.setattr(database, "connect", lambda _: opened.append(connector) or connector)
    pool = database.ConnectorPool()
    params = {"config": {"db_type": "postgresql", "host": "direct.example", "database": "db"}}
    assert pool.activate(params, default=True) is connector
    assert pool.activate(params, default=True) is connector
    assert pool.activate({}) is connector and len(opened) == 1


@pytest.mark.parametrize("closed", ["force-disconnected", "engine-lost"])
def test_cached_ssh_reconnects_after_force_disconnect_or_engine_loss(monkeypatch, closed):
    import datapyn_runtime.database as database
    class Tunnel:
        def is_alive(self):
            return True
    class Connector:
        def __init__(self):
            self._ssh_tunnel = Tunnel()
            self.engine = object()
            self.cleaned = False
        def is_connected(self):
            return self.engine is not None
        def disconnect(self):
            self._ssh_tunnel = self.engine = None
            self.cleaned = True
    opened = []
    monkeypatch.setattr(database, "connect", lambda _: opened.append(Connector()) or opened[-1])
    pool = database.ConnectorPool()
    params = {"config": profile()["config"]}
    previous = pool.activate(params, default=True)
    if closed == "force-disconnected":
        previous.disconnect()
    else:
        previous.engine = None
    replacement = pool.activate(params, default=True)
    assert replacement is not previous and replacement.is_connected()
    assert previous.cleaned and len(opened) == 2
