"""Real Parquet packages, original PyQt reader/writer and atomic failure paths."""

import ast
import json
import logging
from pathlib import Path

import pandas as pd
import polars as pl
import pytest

from datapyn_runtime import variable_archive as archive
from datapyn_runtime.export_control import ExportCancelled
from datapyn_runtime.kernel import ResultStore, MAX_RESULT_HANDLES
from src.utils.data_formats import PARQUET_COMPRESSION


@pytest.fixture
def context():
    return {"clientes": pd.DataFrame({"nome": ["João", "Ana"], "saldo": [1.25, None]}, index=[8, 9]),
            "vendas": pl.DataFrame({"id": [2**60, 2**60 + 1], "texto": ["a;b", "c\nd"]})}, ResultStore(pd, pl)


def legacy_function(name):
    # Execute the actual legacy functions without importing its Qt settings.
    path = Path(__file__).resolve().parents[1] / "source/src/core/session_result_storage.py"
    function = next(node for node in ast.parse(path.read_text(encoding="utf-8")).body if isinstance(node, ast.FunctionDef) and node.name == name)
    namespace = {"Path": Path, "VariableMap": dict, "pd": pd, "json": json,
                 "MANIFEST_NAME": "manifest.json", "PARQUET_COMPRESSION": PARQUET_COMPRESSION, "logger": logging.getLogger(__name__)}
    exec(compile(ast.Module(body=[function], type_ignores=[]), str(path), "exec"), namespace)
    return namespace[name]


def test_package_is_readable_by_actual_pyqt_reader_and_retains_manifest_v2(context, tmp_path):
    namespace, store = context
    destination = tmp_path / "pacote"
    response = archive.export_variables({"path": str(destination)}, namespace, store)
    assert response["count"] == 2 and response["names"] == ["clientes", "vendas"]
    manifest = json.loads((destination / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["version"] == 2
    assert manifest["variables"][0] == {"name": "clientes", "file": "0.parquet"}
    restored = legacy_function("_load_manifest_directory")(destination)
    pd.testing.assert_frame_equal(restored["clientes"], namespace["clientes"].reset_index(drop=True))
    pd.testing.assert_frame_equal(restored["vendas"], namespace["vendas"].to_pandas())
    assert not list(tmp_path.glob(".datapyn-archive-*"))


def test_imports_package_produced_by_actual_pyqt_writer(context, tmp_path):
    namespace, _ = context
    legacy_function("export_variables_to_path")(tmp_path / "legado", {"clientes": namespace["clientes"], "vendas": namespace["vendas"].to_pandas()})
    restored, store = {}, ResultStore(pd, pl)
    response = archive.import_variables({"path": str(tmp_path / "legado")}, restored, store)
    assert response["names"] == ["clientes", "vendas"]
    assert [result["variable_name"] for result in response["results"]] == response["names"]
    pd.testing.assert_frame_equal(restored["clientes"], namespace["clientes"].reset_index(drop=True))
    assert restored["vendas"].iloc[1, 0] == 2**60 + 1


def test_polars_exports_use_native_writer_and_series_types_restore(context, tmp_path, monkeypatch):
    namespace, store = context
    namespace["serie"] = pd.Series([1, None], dtype="Int64", name="quantidade")
    namespace["polars_serie"] = pl.Series("valor", [1, None])
    def forbidden(*args, **kwargs):
        raise AssertionError("Polars export must not copy the frame to pandas")
    with monkeypatch.context() as patch:
        patch.setattr(pl.DataFrame, "to_pandas", forbidden)
        archive.export_variables({"path": str(tmp_path / "pacote")}, namespace, store)
    restored = {}
    archive.import_variables({"path": str(tmp_path / "pacote")}, restored, ResultStore(pd, pl))
    assert isinstance(restored["vendas"], pl.DataFrame)
    assert isinstance(restored["polars_serie"], pl.Series) and restored["polars_serie"].name == "valor"
    pd.testing.assert_series_equal(restored["serie"], namespace["serie"])


def test_single_file_and_plain_directory_import(context, tmp_path):
    namespace, store = context
    destination = tmp_path / "2026 dados.parquet"
    archive.export_variables({"path": str(destination), "names": ["clientes"]}, namespace, store)
    restored = {}
    archive.import_variables({"path": str(destination)}, restored, ResultStore(pd, pl))
    assert "df_2026_dados" in restored
    folder = tmp_path / "simples"
    folder.mkdir()
    namespace["clientes"].to_parquet(folder / "cliente.parquet", index=False)
    archive.import_variables({"path": str(folder)}, restored, ResultStore(pd, pl))
    assert "cliente" in restored
    with pytest.raises(ValueError, match="multiple"):
        archive.export_variables({"path": str(destination)}, namespace, store)


def test_cancelled_or_failed_write_preserves_existing_package(context, tmp_path, monkeypatch):
    namespace, store = context
    destination = tmp_path / "pacote"
    archive.export_variables({"path": str(destination)}, namespace, store)
    originals = {file.name: file.read_bytes() for file in destination.iterdir()}
    seen = []
    original_write = archive._write_frame
    def written_first(*args):
        original_write(*args)
        seen.append("frame")
    with monkeypatch.context() as patch:
        patch.setattr(archive, "_write_frame", written_first)
        with pytest.raises(ExportCancelled):
            archive.export_variables({"path": str(destination), "overwrite": True}, namespace, store, cancelled=lambda: bool(seen))
    assert seen == ["frame"]
    replace = archive.os.replace
    def fail_manifest(source, target):
        if Path(source).name == "manifest.json" and ".datapyn-archive-" in str(source) and "originals" not in str(source):
            raise OSError("disk full")
        return replace(source, target)
    with monkeypatch.context() as patch:
        patch.setattr(archive.os, "replace", fail_manifest)
        with pytest.raises(OSError, match="disk full"):
            archive.export_variables({"path": str(destination), "overwrite": True}, namespace, store)
    assert {file.name: file.read_bytes() for file in destination.iterdir()} == originals
    assert not list(tmp_path.glob(".datapyn-archive-*"))


def test_invalid_package_and_name_collisions_never_import_partial_namespace(context, tmp_path):
    namespace, store = context
    destination = tmp_path / "pacote"
    archive.export_variables({"path": str(destination)}, namespace, store)
    restored = {"vendas": "preservado"}
    with pytest.raises(ValueError, match="already exists"):
        archive.import_variables({"path": str(destination)}, restored, ResultStore(pd, pl))
    assert restored == {"vendas": "preservado"}
    (destination / "1.parquet").write_bytes(b"invalid parquet")
    with pytest.raises(Exception):
        archive.import_variables({"path": str(destination), "overwrite": True}, restored, ResultStore(pd, pl))
    assert restored == {"vendas": "preservado"}


@pytest.mark.parametrize("entry", [{"name": "db_engine", "file": "0.parquet"}, {"name": "df", "file": "../0.parquet"}, {"name": "df", "file": "C:\\0.parquet"}])
def test_manifest_rejects_protected_names_and_external_paths(context, tmp_path, entry):
    namespace, store = context
    archive.export_variables({"path": str(tmp_path / "pacote")}, namespace, store)
    (tmp_path / "pacote/manifest.json").write_text(json.dumps({"version": 2, "variables": [entry]}))
    with pytest.raises(ValueError):
        archive.import_variables({"path": str(tmp_path / "pacote")}, {}, ResultStore(pd, pl))


def test_many_variables_return_only_retained_handles(tmp_path):
    namespace = {f"df_{index}": pd.DataFrame({"v": [index]}) for index in range(MAX_RESULT_HANDLES + 3)}
    archive.export_variables({"path": str(tmp_path / "pacote")}, namespace, ResultStore(pd, pl))
    restored, store = {}, ResultStore(pd, pl)
    response = archive.import_variables({"path": str(tmp_path / "pacote")}, restored, store)
    assert response["count"] == len(restored) == len(namespace)
    assert len(response["results"]) == MAX_RESULT_HANDLES
    assert all(result["result_id"] in store.frames for result in response["results"])


def test_inventory_excludes_lazy_and_reserved_variables(context):
    namespace, store = context
    namespace.update({"_secret": namespace["clientes"], "db_engine": namespace["clientes"], "lazy": pl.LazyFrame({"x": [1]}), "scalar": 1})
    response = archive.dispatch("variable.archive.list", {}, namespace, store)
    assert response["total"] == 2 and [item["name"] for item in response["variables"]] == ["clientes", "vendas"]
