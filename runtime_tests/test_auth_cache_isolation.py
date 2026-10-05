from pathlib import Path
from types import SimpleNamespace

import pytest

from src.database import database_connector as connector


@pytest.mark.parametrize("workspace", [None, ""])
def test_legacy_entra_cache_name_is_unchanged_without_explicit_workspace(monkeypatch, workspace):
    if workspace is None:
        monkeypatch.delenv("DATAPYN_WORKSPACE_PATH", raising=False)
    else:
        monkeypatch.setenv("DATAPYN_WORKSPACE_PATH", workspace)
    assert connector._get_sqlserver_entra_cache_name("tenant.database.windows.net:1433/sql") == (
        "datapyn_sqlserver_tenant_database_windows_net_1433_sql"
    )


def test_tauri_entra_cache_is_stable_and_distinct_from_legacy(monkeypatch, tmp_path):
    host = "tenant.database.windows.net"
    monkeypatch.delenv("DATAPYN_WORKSPACE_PATH", raising=False)
    legacy = connector._get_sqlserver_entra_cache_name(host)
    monkeypatch.setenv("DATAPYN_WORKSPACE_PATH", str(tmp_path / "profile"))
    name = connector._get_sqlserver_entra_cache_name(host)
    assert name.startswith("datapyn_tauri_sqlserver_")
    assert name != legacy
    assert connector._get_sqlserver_entra_cache_name(host) == name
    assert not (tmp_path / "profile").exists(), "Computing a cache name must not create a profile"


def test_tauri_entra_profiles_have_distinct_encrypted_cache_names(monkeypatch, tmp_path):
    host = "tenant.database.windows.net"
    monkeypatch.setenv("DATAPYN_WORKSPACE_PATH", str(tmp_path / "first"))
    first = connector._get_sqlserver_entra_cache_name(host)
    monkeypatch.setenv("DATAPYN_WORKSPACE_PATH", str(tmp_path / "second"))
    assert connector._get_sqlserver_entra_cache_name(host) != first


def test_tauri_entra_cache_normalizes_equivalent_workspace_paths(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("DATAPYN_WORKSPACE_PATH", "profile")
    expected = connector._get_sqlserver_entra_cache_name("tenant.database.windows.net")
    for path in (tmp_path / "profile", tmp_path / "profile" / ".." / "profile"):
        monkeypatch.setenv("DATAPYN_WORKSPACE_PATH", str(path))
        assert connector._get_sqlserver_entra_cache_name("tenant.database.windows.net") == expected


def test_tauri_entra_cache_normalizes_host_case_but_does_not_collide_after_sanitizing(monkeypatch, tmp_path):
    monkeypatch.setenv("DATAPYN_WORKSPACE_PATH", str(tmp_path))
    expected = connector._get_sqlserver_entra_cache_name("tenant.database.windows.net")
    assert connector._get_sqlserver_entra_cache_name(" TENANT.DATABASE.WINDOWS.NET ") == expected
    assert connector._get_sqlserver_entra_cache_name("tenant_database_windows_net") != expected
    assert connector._get_sqlserver_entra_cache_name("another.database.windows.net") != expected


def test_tauri_authentication_record_stays_in_its_own_profile(monkeypatch, tmp_path):
    workspace = tmp_path / "profile with spaces"
    monkeypatch.setenv("DATAPYN_WORKSPACE_PATH", str(workspace))
    host = "tenant.database.windows.net:1433/sql"
    record = connector._get_sqlserver_auth_record_path(host)
    assert record.parent == workspace / "oauth_cache"
    assert record.name == connector._get_sqlserver_entra_cache_name(host) + "_auth_record.json"
    assert record.is_relative_to(workspace)
    assert not record.exists()


def test_browser_credential_receives_isolated_cache_without_authentication(monkeypatch, tmp_path):
    import azure.identity

    monkeypatch.setenv("DATAPYN_WORKSPACE_PATH", str(tmp_path))
    captured = {}

    def credential(**kwargs):
        captured.update(kwargs)
        return object()

    monkeypatch.setattr(azure.identity, "InteractiveBrowserCredential", credential)
    result = connector._create_sqlserver_mfa_credential("tenant.database.windows.net", "example", "tenant")
    assert result is not None
    assert captured["cache_persistence_options"].name == connector._get_sqlserver_entra_cache_name("tenant.database.windows.net")
    assert captured["login_hint"] == "example"
    assert captured["tenant_id"] == "tenant"


def test_tauri_entra_cache_expands_home_paths(monkeypatch, tmp_path):
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    monkeypatch.setenv("DATAPYN_WORKSPACE_PATH", str(tmp_path / "profile"))
    absolute = connector._get_sqlserver_entra_cache_name("tenant.database.windows.net")
    # expanduser() uses the OS home environment; provide both OS conventions.
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.setenv("DATAPYN_WORKSPACE_PATH", "~/profile")
    assert connector._get_sqlserver_entra_cache_name("tenant.database.windows.net") == absolute


def test_macos_tauri_cache_isolates_keychain_items_and_cae_without_reading_secrets(monkeypatch, tmp_path):
    import azure.identity
    import msal_extensions

    calls = []

    class KeychainPersistence:
        is_encrypted = True

        def __init__(self, location, service, account):
            self.location, self.service, self.account = location, service, account
            calls.append(self)

        def get_location(self):
            return self.location

        def load(self):
            pytest.fail("Constructing a cache must not read the user's Keychain")

        def save(self, value):
            pytest.fail("Constructing a cache must not write the user's Keychain")

    monkeypatch.setattr(msal_extensions, "KeychainPersistence", KeychainPersistence)
    monkeypatch.setattr(connector, "sys", SimpleNamespace(platform="darwin"))
    workspace = tmp_path / "first profile"
    monkeypatch.setenv("DATAPYN_WORKSPACE_PATH", str(workspace))
    credential = connector._create_sqlserver_mfa_credential("tenant.database.windows.net")
    try:
        assert isinstance(credential, azure.identity.InteractiveBrowserCredential)
        cache = credential._initialize_cache()
        cae_cache = credential._initialize_cache(is_cae=True)
        assert credential._cache is cache
        assert credential._cae_cache is cae_cache
        assert cache.is_encrypted and cae_cache.is_encrypted
        assert calls[0].service == calls[1].service == "DataPyn.Tauri.SQLServer"
        assert calls[0].account != calls[1].account
        assert calls[0].account.endswith("_nocae") and calls[1].account.endswith("_cae")
        assert all(Path(call.location).is_relative_to(workspace) for call in calls)
    finally:
        credential.close()

    monkeypatch.setenv("DATAPYN_WORKSPACE_PATH", str(tmp_path / "second profile"))
    second = connector._create_sqlserver_mfa_credential("tenant.database.windows.net")
    try:
        second._initialize_cache()
        assert calls[-1].account not in {calls[0].account, calls[1].account}
    finally:
        second.close()


@pytest.mark.parametrize("platform, workspace", [("win32", True), ("linux", False), ("darwin", False)])
def test_platforms_and_legacy_keep_the_original_browser_credential(monkeypatch, tmp_path, platform, workspace):
    import azure.identity

    monkeypatch.setattr(connector, "sys", SimpleNamespace(platform=platform))
    if workspace:
        monkeypatch.setenv("DATAPYN_WORKSPACE_PATH", str(tmp_path))
    else:
        monkeypatch.delenv("DATAPYN_WORKSPACE_PATH", raising=False)
    captured = {}
    expected = object()

    def credential(**kwargs):
        captured.update(kwargs)
        return expected

    monkeypatch.setattr(azure.identity, "InteractiveBrowserCredential", credential)
    assert connector._create_sqlserver_mfa_credential("tenant.database.windows.net") is expected
    assert captured["cache_persistence_options"].allow_unencrypted_storage is False


@pytest.fixture
def secret_service(monkeypatch):
    from keyring.backends import SecretService

    class Backend:
        def __init__(self):
            self.values = {}
            self.fail = None
            self.operations = []

        def set_password(self, service, account, content):
            self.operations.append(("save", service, account))
            if self.fail:
                raise self.fail
            self.values[service, account] = content

        def get_password(self, service, account):
            self.operations.append(("load", service, account))
            if self.fail:
                raise self.fail
            return self.values.get((service, account))

    backend = Backend()
    monkeypatch.setattr(SecretService, "Keyring", lambda: backend)
    return backend


def test_linux_token_persistence_stores_secrets_only_in_native_keyring(tmp_path, secret_service):
    from msal_extensions.persistence import BasePersistence

    path = tmp_path / "token-cache.signal"
    persistence = connector._create_sqlserver_tauri_linux_persistence(path, "isolated-account")
    assert isinstance(persistence, BasePersistence)
    assert persistence.is_encrypted
    assert persistence.get_location() == str(path)
    assert not path.exists() and secret_service.operations == []
    persistence.save("private token cache")
    assert secret_service.values == {("DataPyn.Tauri.SQLServer", "isolated-account"): "private token cache"}
    assert path.read_bytes() == b"", "The signal file must never contain access or refresh tokens"
    assert persistence.time_last_modified() > 0
    assert persistence.load() == "private token cache"


def test_linux_token_persistence_missing_items_match_msal_contract(tmp_path, secret_service):
    from msal_extensions.persistence import PersistenceNotFound

    path = tmp_path / "absent.signal"
    persistence = connector._create_sqlserver_tauri_linux_persistence(path, "isolated-account")
    with pytest.raises(PersistenceNotFound):
        persistence.load()
    with pytest.raises(PersistenceNotFound):
        persistence.time_last_modified()
    assert not path.exists()


@pytest.mark.parametrize("operation", ["save", "load"])
def test_linux_secret_service_failures_never_fall_back_to_plaintext(tmp_path, secret_service, operation):
    path = tmp_path / "unavailable.signal"
    persistence = connector._create_sqlserver_tauri_linux_persistence(path, "isolated-account")
    secret_service.fail = RuntimeError("Secret Service is locked or unavailable")
    with pytest.raises(RuntimeError, match="Secret Service is locked or unavailable"):
        if operation == "save":
            persistence.save("private token cache")
        else:
            persistence.load()
    assert not path.exists()
    assert secret_service.values == {}


def test_linux_token_cache_uses_msal_locking_and_reloads_between_instances(tmp_path, secret_service):
    from msal_extensions import PersistedTokenCache

    path = tmp_path / "shared.signal"
    first = PersistedTokenCache(connector._create_sqlserver_tauri_linux_persistence(path, "isolated-account"))
    second = PersistedTokenCache(connector._create_sqlserver_tauri_linux_persistence(path, "isolated-account"))
    first.modify("AccessToken", {}, {"secret": "private token cache", "home_account_id": "example", "expires_on": "9999999999"})
    assert list(second.search("AccessToken"))[0]["secret"] == "private token cache"
    assert "private token cache" not in path.read_text()
    assert first.is_encrypted and second.is_encrypted
    assert Path(first._lock_location).parent == tmp_path


def test_linux_browser_cache_isolates_profiles_hosts_and_cae_without_secret_access(monkeypatch, tmp_path, secret_service):
    import msal_extensions

    def forbidden(*args, **kwargs):
        pytest.fail("Tauri must not initialize the SDK's PyGObject/libsecret persistence")

    monkeypatch.setattr(msal_extensions, "LibsecretPersistence", forbidden)
    monkeypatch.setattr(connector, "sys", SimpleNamespace(platform="linux"))
    credentials = []
    caches = []
    try:
        for profile, host in (("first", "tenant.database.windows.net"), ("second", "tenant.database.windows.net"),
                              ("first", "another.database.windows.net")):
            workspace = tmp_path / profile
            monkeypatch.setenv("DATAPYN_WORKSPACE_PATH", str(workspace))
            credential = connector._create_sqlserver_mfa_credential(host)
            credentials.append(credential)
            for is_cae in (False, True):
                cache = credential._initialize_cache(is_cae)
                caches.append(cache)
                assert cache.is_encrypted
                assert cache._persistence._service_name == "DataPyn.Tauri.SQLServer"
                assert Path(cache._persistence.get_location()).is_relative_to(workspace)
        assert len({cache._persistence._account_name for cache in caches}) == 6
        assert secret_service.operations == [], "Constructors must not open or query a real cofre"
    finally:
        for credential in credentials:
            credential.close()
