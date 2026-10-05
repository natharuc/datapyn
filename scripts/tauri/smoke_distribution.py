"""Verify all driver/dialect/authentication dependencies in the actual runtime."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import tempfile

from smoke_runtime import RuntimeClient, result_page


def smoke(executable=None, timeout=90):
    with tempfile.TemporaryDirectory(prefix="datapyn-distribution-") as directory:
        root = Path(directory)
        keys = {"DATAPYN_RUNTIME_STATE_PATH": str(root / "workspace"),
                "DATAPYN_WORKSPACE_PATH": str(root / "workspace"),
                "DATAPYN_RUNTIME_DATA_DIR": str(root / "packages"),
                "DATAPYN_SNAPSHOT_ROOT": str(root / "snapshots")}
        previous = {key: os.environ.get(key) for key in keys}
        os.environ.update(keys)
        client = None
        try:
            client = RuntimeClient(executable, timeout)
            assert client.request("system.info")["capabilities"]["qt_required"] is False
            client.request("session.create", {"session_id": "distribution"})
            client.event("session.ready", session_id="distribution")
            code = """import json, importlib, importlib.util, importlib.metadata, os, sys, pandas as pd
from pathlib import Path
from datapyn_runtime.distribution import verify_runtime_distribution
report = verify_runtime_distribution()
backend_module, backend_class = {
    'win32': ('keyring.backends.Windows', 'WinVaultKeyring'),
    'linux': ('keyring.backends.SecretService', 'Keyring'),
    'darwin': ('keyring.backends.macOS', 'Keyring'),
}[sys.platform]
backend = getattr(importlib.import_module(backend_module), backend_class)()
report['keyring_backend'] = backend_module
if sys.platform == 'linux':
    import secretstorage, jeepney
    report['keyring_dependencies'] = {name: importlib.metadata.version(name) for name in ('SecretStorage', 'jeepney')}
if sys.platform in ('darwin', 'linux'):
    from src.database.database_connector import _create_sqlserver_mfa_credential
    credential = _create_sqlserver_mfa_credential('offline.example')
    try:
        cache = credential._initialize_cache()
        cae_cache = credential._initialize_cache(is_cae=True)
        assert cache.is_encrypted and cae_cache.is_encrypted
        assert cache._persistence._service_name == 'DataPyn.Tauri.SQLServer'
        assert cache._persistence._account_name != cae_cache._persistence._account_name
        assert Path(cache._persistence.get_location()).is_relative_to(Path(os.environ['DATAPYN_WORKSPACE_PATH']))
        report['mfa_native_cache_isolated'] = True
    finally:
        credential.close()
# Do not call priority/get_password/set_password or connect to the desktop bus.
if getattr(sys, 'frozen', False):
    assert importlib.util.find_spec('PyQt6') is None, 'Qt leaked into the desktop runtime'
pd.DataFrame({'report': [json.dumps(report)]})"""
            finished = client.execute("distribution", "drivers", "python", code)
            report = json.loads(result_page(client, "distribution", finished)["rows"][0][0])
            assert set(report["databases"]) == {"sqlserver", "mysql", "mariadb", "postgresql", "databricks", "sqlite"}
            if executable:
                assert report["frozen"] is True
            print(json.dumps({"status": "passed", **report}, indent=2))
            return report
        finally:
            if client:
                client.close()
            for key, value in previous.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--executable")
    parser.add_argument("--timeout", type=float, default=90)
    args = parser.parse_args()
    smoke(args.executable, args.timeout)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
