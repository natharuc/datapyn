"""Contract tests for README Linux artifact and AppImage guidance."""

from __future__ import annotations

import importlib.util
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
README = ROOT / "README.md"
METADATA_HELPER = ROOT / "scripts/linux/release_metadata.py"
VERSION = "1.57.0"
TAG = "v1.57.0"

DOCUMENTED_FILENAME = re.compile(
    r"(?<![A-Za-z0-9_.-])(?:\./)?(?P<filename>"
    r"(?:datapyn_[A-Za-z0-9.+~:_-]+_amd64\.deb|datapyn_amd64\.deb|"
    r"datapyn-[A-Za-z0-9.+~:_-]+-1\.x86_64\.rpm|datapyn-x86_64\.rpm|"
    r"datapyn-[A-Za-z0-9.+~:_-]+-1-x86_64\.pkg\.tar\.zst|datapyn-x86_64\.pkg\.tar\.zst|"
    r"DataPyn-[A-Za-z0-9.+~:_-]+-x86_64\.AppImage|DataPyn-x86_64\.AppImage|"
    r"DataPyn-[A-Za-z0-9.+~:_-]+-linux-x86_64\.tar\.gz|DataPyn-linux-x86_64\.tar\.gz)"
    r")"
)


def load_metadata_helper():
    spec = importlib.util.spec_from_file_location("linux_release_metadata", METADATA_HELPER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def documented_filenames(text: str) -> set[str]:
    return {
        match.group("filename").replace("VERSION", VERSION)
        for match in DOCUMENTED_FILENAME.finditer(text)
    }


def generated_manifest(tmp_path: Path) -> dict[str, object]:
    metadata = load_metadata_helper()
    definitions = metadata.expected_artifacts(VERSION)
    for index, artifact in enumerate(definitions):
        payload = f"fixture-{index}\n".encode()
        (tmp_path / artifact["filename"]).write_bytes(payload)
        (tmp_path / artifact["stable_alias"]).write_bytes(payload)

    metadata.build_manifest(tmp_path, VERSION, TAG, "natharuc/datapyn")
    return json.loads((tmp_path / metadata.MANIFEST_FILENAME).read_text(encoding="utf-8"))


def manifest_filenames(manifest: dict[str, object]) -> set[str]:
    versioned = {artifact["filename"] for artifact in manifest["artifacts"]}
    aliases = {
        artifact["stable_alias"]
        for artifact in load_metadata_helper().expected_artifacts(VERSION)
    }
    return versioned | aliases


def test_readme_lists_required_labels_and_fuse3_guidance(tmp_path: Path) -> None:
    readme = README.read_text(encoding="utf-8")
    manifest = generated_manifest(tmp_path)
    labels = {artifact["display_name"] for artifact in manifest["artifacts"]}

    assert all(label in readme for label in labels)
    assert "x86_64" in readme
    assert "amd64" in readme
    assert "FUSE3" in readme
    assert "fusermount3" in readme
    assert "chmod +x" in readme
    assert "--appimage-extract-and-run" in readme
    assert "libfuse2" not in readme.lower()
    assert "libfuse2t64" not in readme.lower()


def test_documented_linux_filenames_exist_in_generated_manifest(tmp_path: Path) -> None:
    readme = README.read_text(encoding="utf-8")
    manifest = generated_manifest(tmp_path)

    assert documented_filenames(readme) == manifest_filenames(manifest)


def test_missing_documented_filename_is_reported(tmp_path: Path) -> None:
    manifest = generated_manifest(tmp_path)
    documented = documented_filenames(README.read_text(encoding="utf-8"))
    missing = "datapyn-9.99.9-1.x86_64.rpm"
    documented.add(missing)

    absent = sorted(documented - manifest_filenames(manifest))

    assert absent == [missing]
