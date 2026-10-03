import importlib
import json
import sys
import threading
import time
import types

import pytest

from datapyn_runtime.desktop_services import PackageService, enable_user_packages, package_site


def test_packages_do_not_create_environment_or_install_on_list(tmp_path, monkeypatch):
    monkeypatch.setenv("DATAPYN_RUNTIME_DATA_DIR", str(tmp_path))
    service = PackageService(lambda _: None)
    value = service.list()
    assert any(item["name"].lower() == "pandas" for item in value["packages"])
    assert not service.python.exists()
    assert value["environment"]["ready"] is False
    assert not tmp_path.exists() or not list(tmp_path.iterdir())


def test_extra_sources_preserve_credentials_only_in_keyring(tmp_path, monkeypatch):
    monkeypatch.setenv("DATAPYN_RUNTIME_DATA_DIR", str(tmp_path))
    secrets = {}
    monkeypatch.setitem(sys.modules, "keyring", types.SimpleNamespace(set_password=lambda service, identifier, password: secrets.update({identifier:password})))
    service = PackageService(lambda _: None)
    rows = service.sources([{"url":"https://packages.example/simple", "username":"developer", "password":"do-not-write-to-json", "save_password":True}])
    assert rows[0]["has_password"]
    assert secrets[rows[0]["id"]] == "do-not-write-to-json"
    assert "do-not-write-to-json" not in service.config.read_text()
    assert service.sources()[0]["id"] == rows[0]["id"]
    assert service.sources([{**rows[0], "username":"developer-2"}])[0]["has_password"]


def test_kernel_can_import_extensions_without_changing_baseline_environment(tmp_path, monkeypatch):
    monkeypatch.setenv("DATAPYN_RUNTIME_DATA_DIR", str(tmp_path))
    path = package_site(); path.mkdir(parents=True)
    (path / "datapyn_extension_probe.py").write_text("answer = 42\n")
    old_path = sys.path[:]
    try:
        enable_user_packages()
        assert importlib.import_module("datapyn_extension_probe").answer == 42
    finally:
        sys.path[:] = old_path
        sys.modules.pop("datapyn_extension_probe", None)


def test_package_command_shutdown_terminates_process_instead_of_waiting_for_timeout(tmp_path, monkeypatch):
    monkeypatch.setenv("DATAPYN_RUNTIME_DATA_DIR", str(tmp_path))
    service = PackageService(lambda _: None)
    errors = []
    def run():
        try: service._run([sys.executable, "-c", "import time;time.sleep(120)"])
        except Exception as exc: errors.append(exc)
    worker = threading.Thread(target=run); worker.start()
    deadline = time.monotonic() + 5
    while not service.processes and time.monotonic() < deadline: time.sleep(.01)
    assert service.processes
    started = time.monotonic(); service.close(); worker.join(timeout=5)
    assert not worker.is_alive()
    assert time.monotonic() - started < 5
    assert errors


@pytest.mark.parametrize("name", ["-rrequirements.txt", "pkg;rm", "../package", "https://repo", ""])
def test_package_names_are_arguments_not_options(name):
    with pytest.raises(ValueError): PackageService._name(name)
