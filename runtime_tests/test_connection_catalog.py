from __future__ import annotations

from copy import deepcopy
import json

import pytest

from datapyn_runtime.connection_catalog import ConnectionCatalog


class Secrets:
    def __init__(self):
        self.values = {}

    def get(self, identifier):
        return deepcopy(self.values.get(identifier, {}))

    def set(self, identifier, value):
        self.values[identifier] = deepcopy(value)

    def delete(self, identifier):
        self.values.pop(identifier, None)


@pytest.fixture
def catalog(tmp_path):
    return ConnectionCatalog(tmp_path / "preview.json", Secrets())


def profile(name="database", group_id=None):
    return {"name": name, "group_id": group_id, "favorite": True,
            "config": {"db_type": "sqlite", "database": ":memory:"}}


def test_password_never_crosses_catalog_or_export_and_edit_preserves_it(catalog, tmp_path):
    saved = catalog.save_connection(profile(), password="secret", save_password=True)
    assert saved["has_password"]
    assert catalog.config(saved["id"])["password"] == "secret"
    assert "secret" not in catalog.path.read_text()
    saved["config"]["database"] = "other.sqlite"
    edited = catalog.save_connection(saved, save_password=True)
    assert edited["has_password"] and catalog.config(saved["id"])["password"] == "secret"
    path = tmp_path / "export.json"
    result = catalog.dispatch("connections.export", {"path": str(path)})
    assert not result["passwords_included"] and "secret" not in path.read_text()
    assert not json.loads(path.read_text())["connections"][0]["has_password"]
    catalog.save_connection(edited, save_password=False)
    assert not catalog.config(saved["id"]).get("password")


def test_nested_groups_ids_survive_rename_and_prevent_cycles(catalog):
    parent = catalog.save_group({"name": "production"})
    child = catalog.save_group({"name": "reporting", "parent_id": parent["id"]})
    saved = catalog.save_connection(profile(group_id=child["id"]))
    catalog.save_group({**parent, "name": "prod"})
    assert catalog.resolve_ref("reporting", "database") == saved["id"]
    with pytest.raises(ValueError, match="ancestors"):
        catalog.save_group({**parent, "parent_id": child["id"]})
    assert catalog.list()["groups"][0]["parent_id"] is None


def test_duplicate_names_are_group_aware_and_delete_does_not_overwrite(catalog):
    group = catalog.save_group({"name": "group"})
    root = catalog.save_connection(profile())
    nested = catalog.save_connection(profile(group_id=group["id"]))
    with pytest.raises(ValueError, match="already exists"):
        catalog.save_connection(profile("DATABASE"))
    with pytest.raises(ValueError, match="ambiguous"):
        catalog.resolve_ref(None, "database")
    catalog.dispatch("groups.delete", {"group_id": group["id"]})
    profiles = catalog.list()["connections"]
    assert {p["name"] for p in profiles} == {"database", "database (2)"}
    assert {p["id"] for p in profiles} == {root["id"], nested["id"]}


def test_move_clone_reorder_and_reload(catalog):
    group = catalog.save_group({"name": "folder"})
    saved = catalog.save_connection(profile(), password="pw", save_password=True)
    copied = catalog.dispatch("connections.clone", {"connection_id": saved["id"]})
    assert copied["id"] != saved["id"] and copied["favorite"]
    assert catalog.config(copied["id"])["password"] == "pw"
    moved = catalog.dispatch("connections.move", {"connection_id": copied["id"], "group_id": group["id"], "name": "moved"})
    assert moved["group_id"] == group["id"]
    catalog.dispatch("connections.reorder", {"connection_ids": [copied["id"], saved["id"]]})
    reloaded = ConnectionCatalog(catalog.path, catalog.credentials)
    assert next(p for p in reloaded.list()["connections"] if p["id"] == copied["id"])["order"] == 0


@pytest.mark.parametrize("nested", [False, True])
def test_explicit_legacy_import_preserves_same_name_profiles_and_secrets(catalog, tmp_path, nested):
    config = {"db_type": "postgresql", "host": "localhost", "database": "db", "group": "legacy", "password": "legacy-secret"}
    connections = {"legacy": {"db": config}} if nested else {"db": config}
    legacy = tmp_path / "connections-legacy.json"
    legacy.write_text(json.dumps({"groups": {"legacy": {"color": "#abc"}}, "connections": connections}))
    result = catalog.dispatch("connections.import", {"path": str(legacy)})
    assert result["imported_connections"] == 1
    saved = result["catalog"]["connections"][0]
    assert saved["config"]["schema"] == "public"
    assert saved["has_password"] and catalog.config(saved["id"])["password"] == "legacy-secret"
    assert "legacy-secret" not in catalog.path.read_text()
    catalog.dispatch("connections.import", {"path": str(legacy)})
    assert {p["name"] for p in catalog.list()["connections"]} == {"db", "db (2)"}


def test_bad_import_rolls_back_without_losing_existing_profiles(catalog, tmp_path):
    catalog.save_connection(profile())
    initial = catalog.list()
    path = tmp_path / "broken.json"
    path.write_text(json.dumps({"version": 1, "groups": [{"id": "a", "name": "a", "parent_id": "b"}], "connections": []}))
    with pytest.raises(ValueError, match="cycle"):
        catalog.import_file(str(path))
    assert catalog.list() == initial


def test_reorder_rejects_duplicate_or_unknown_identifiers(catalog):
    saved = catalog.save_connection(profile())
    with pytest.raises(ValueError):
        catalog.dispatch("connections.reorder", {"connection_ids": [saved["id"], saved["id"]]})
    with pytest.raises(ValueError):
        catalog.dispatch("connections.reorder", {"connection_ids": ["unknown"]})


def test_import_failure_after_valid_group_rolls_back_everything(catalog, tmp_path):
    catalog.save_connection(profile())
    initial = catalog.list()
    path = tmp_path / "invalid-group.json"
    path.write_text(json.dumps({"version": 1, "groups": [{"id": "ok", "name": "valid"}, {"id": "bad", "name": ""}], "connections": []}))
    with pytest.raises(ValueError):
        catalog.import_file(str(path))
    assert catalog.list() == initial
    assert json.loads(catalog.path.read_text()) == initial
