"""Contract tests for Linux release metadata, checksums, and workflow parity."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
PACKAGE_SCRIPT = ROOT / "scripts/linux/package.sh"
RELEASE_WORKFLOW = ROOT / ".github/workflows/release.yml"
DRY_RUN_WORKFLOW = ROOT / ".github/workflows/release-linux.yml"
VERSION = "1.57.0"
TAG = "v1.57.0"

VERSIONED = (
    f"datapyn_{VERSION}_amd64.deb",
    f"datapyn-{VERSION}-1.x86_64.rpm",
    f"datapyn-{VERSION}-1-x86_64.pkg.tar.zst",
    f"DataPyn-{VERSION}-x86_64.AppImage",
    f"DataPyn-{VERSION}-linux-x86_64.tar.gz",
)
ALIASES = (
    "datapyn_amd64.deb",
    "datapyn-x86_64.rpm",
    "datapyn-x86_64.pkg.tar.zst",
    "DataPyn-x86_64.AppImage",
    "DataPyn-linux-x86_64.tar.gz",
)
RELEASE_METADATA = ("DataPyn-linux-artifacts.json", "SHA256SUMS")
ALL_RELEASE_ASSETS = (*VERSIONED, *ALIASES, *RELEASE_METADATA)


def run_package(
    *args: str,
    output_dir: Path | None = None,
    check: bool = False,
) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    if output_dir is not None:
        env["DATAPYN_PACKAGE_OUTPUT_DIR"] = str(output_dir)
    result = subprocess.run(
        ["bash", str(PACKAGE_SCRIPT), *args],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=check,
    )
    return result


def seed_release(output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    for index, (versioned, alias) in enumerate(zip(VERSIONED, ALIASES, strict=True)):
        payload = f"fixture-{index}\n".encode()
        (output_dir / versioned).write_bytes(payload)
        (output_dir / alias).write_bytes(payload)


def generate_fixture(output_dir: Path) -> None:
    result = run_package(
        "--generate-release-metadata",
        VERSION,
        TAG,
        output_dir=output_dir,
    )
    assert result.returncode == 0, result.stderr


def test_release_asset_list_contains_versioned_alias_metadata_set() -> None:
    result = run_package("--print-release-assets", VERSION)

    assert result.returncode == 0, result.stderr
    assert tuple(result.stdout.splitlines()) == ALL_RELEASE_ASSETS


def test_manifest_and_checksums_describe_complete_fixture(tmp_path: Path) -> None:
    seed_release(tmp_path)
    generate_fixture(tmp_path)

    manifest = json.loads((tmp_path / RELEASE_METADATA[0]).read_text(encoding="utf-8"))
    assert set(manifest) == {
        "schema_version",
        "product",
        "version",
        "release_tag",
        "architecture",
        "artifacts",
    }
    assert manifest["schema_version"] == 1
    assert manifest["product"] == "DataPyn"
    assert manifest["version"] == VERSION
    assert manifest["release_tag"] == TAG
    assert manifest["architecture"] == "x86_64"
    assert [artifact["filename"] for artifact in manifest["artifacts"]] == list(VERSIONED)

    checksums = {
        filename: digest
        for digest, filename in (
            line.split(maxsplit=1)
            for line in (tmp_path / RELEASE_METADATA[1]).read_text(encoding="utf-8").splitlines()
        )
    }
    for artifact in manifest["artifacts"]:
        digest = hashlib.sha256((tmp_path / artifact["filename"]).read_bytes()).hexdigest()
        assert artifact["sha256"] == digest
        assert checksums[artifact["filename"]] == digest
        assert artifact["download_url"].endswith(f"/{TAG}/{artifact['filename']}")

    validation = run_package("--validate-release", VERSION, TAG, output_dir=tmp_path)
    assert validation.returncode == 0, validation.stderr


def test_appimage_manifest_declares_fuse3_and_portable_mode(tmp_path: Path) -> None:
    seed_release(tmp_path)
    generate_fixture(tmp_path)

    manifest = json.loads((tmp_path / RELEASE_METADATA[0]).read_text(encoding="utf-8"))
    appimage = next(item for item in manifest["artifacts"] if item["format"] == "appimage")
    assert appimage["distro_family"] == "universal"
    assert appimage["requires"] == ["fuse3"]
    assert appimage["install_mode"] == "portable"


def test_missing_artifact_blocks_metadata_generation(tmp_path: Path) -> None:
    seed_release(tmp_path)
    (tmp_path / VERSIONED[1]).unlink()

    result = run_package("--generate-release-metadata", VERSION, TAG, output_dir=tmp_path)

    assert result.returncode != 0
    assert VERSIONED[1] in result.stderr
    assert not (tmp_path / RELEASE_METADATA[0]).exists()
    assert not (tmp_path / RELEASE_METADATA[1]).exists()


def test_missing_packager_blocks_upload_ready_output(tmp_path: Path) -> None:
    dist_dir = tmp_path / "dist" / "DataPyn"
    output_dir = tmp_path / "output"
    dist_dir.mkdir(parents=True)
    (dist_dir / "DataPyn").write_bytes(b"fixture executable")
    command_bin = tmp_path / "bin"
    command_bin.mkdir()
    for command in ("bash", "mkdir", "rm"):
        (command_bin / command).symlink_to(Path("/usr/bin") / command)

    result = subprocess.run(
        ["bash", str(PACKAGE_SCRIPT), VERSION],
        cwd=ROOT,
        env={
            **os.environ,
            "PATH": str(command_bin),
            "DATAPYN_PACKAGE_DIST_DIR": str(dist_dir),
            "DATAPYN_PACKAGE_OUTPUT_DIR": str(output_dir),
        },
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode != 0
    assert "required executable 'fpm' is missing" in result.stderr
    assert not any((output_dir / filename).exists() for filename in ALL_RELEASE_ASSETS)


def test_missing_checksum_blocks_release_validation(tmp_path: Path) -> None:
    seed_release(tmp_path)
    generate_fixture(tmp_path)
    checksum_path = tmp_path / RELEASE_METADATA[1]
    checksum_path.write_text(
        "\n".join(
            line
            for line in checksum_path.read_text(encoding="utf-8").splitlines()
            if VERSIONED[2] not in line
        )
        + "\n",
        encoding="utf-8",
    )

    result = run_package("--validate-release", VERSION, TAG, output_dir=tmp_path)

    assert result.returncode != 0
    assert VERSIONED[2] in result.stderr


def test_stable_aliases_must_be_byte_identical(tmp_path: Path) -> None:
    seed_release(tmp_path)
    generate_fixture(tmp_path)
    (tmp_path / ALIASES[0]).write_bytes(b"changed alias")

    result = run_package("--validate-release", VERSION, TAG, output_dir=tmp_path)

    assert result.returncode != 0
    assert ALIASES[0] in result.stderr


@pytest.mark.parametrize(
    ("field", "value", "needle"),
    (
        ("download_url", "http://example.invalid/file", "download_url"),
        ("format", "", "format"),
        ("sha256", "A" * 64, "sha256"),
    ),
)
def test_invalid_manifest_fields_fail_validation(
    tmp_path: Path, field: str, value: str, needle: str
) -> None:
    seed_release(tmp_path)
    generate_fixture(tmp_path)
    manifest_path = tmp_path / RELEASE_METADATA[0]
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["artifacts"][0][field] = value
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    result = run_package("--validate-release", VERSION, TAG, output_dir=tmp_path)

    assert result.returncode != 0
    assert needle in result.stderr


def test_additive_future_manifest_entry_remains_valid(tmp_path: Path) -> None:
    seed_release(tmp_path)
    generate_fixture(tmp_path)
    future_filename = f"DataPyn-{VERSION}-future.tar.zst"
    future_payload = b"future-format-fixture"
    (tmp_path / future_filename).write_bytes(future_payload)
    future_digest = hashlib.sha256(future_payload).hexdigest()
    manifest_path = tmp_path / RELEASE_METADATA[0]
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["artifacts"].append(
        {
            "id": "future-format",
            "format": "future",
            "distro_family": "future",
            "display_name": "Future Linux format",
            "filename": future_filename,
            "download_url": f"https://github.com/natharuc/datapyn/releases/download/{TAG}/{future_filename}",
            "sha256": future_digest,
            "requires": [],
            "install_mode": "native-package",
        }
    )
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    checksum_path = tmp_path / RELEASE_METADATA[1]
    checksum_path.write_text(
        checksum_path.read_text(encoding="utf-8") + f"{future_digest}  {future_filename}\n",
        encoding="utf-8",
    )

    result = run_package("--validate-release", VERSION, TAG, output_dir=tmp_path)

    assert result.returncode == 0, result.stderr


def test_release_metadata_isolated_by_output_directory(tmp_path: Path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    seed_release(first)
    seed_release(second)

    generate_fixture(first)
    generate_fixture(second)

    assert (first / RELEASE_METADATA[0]).read_bytes() == (second / RELEASE_METADATA[0]).read_bytes()
    assert (first / RELEASE_METADATA[1]).read_bytes() == (second / RELEASE_METADATA[1]).read_bytes()
    assert not (first / "partial-upload-marker").exists()
    assert not (second / "partial-upload-marker").exists()


def test_main_and_dry_run_workflows_share_assets_and_dry_run_never_publishes() -> None:
    main = RELEASE_WORKFLOW.read_text(encoding="utf-8")
    dry_run = DRY_RUN_WORKFLOW.read_text(encoding="utf-8")

    assert "bash scripts/linux/package.sh --print-release-assets" in main
    assert "bash scripts/linux/package.sh --print-release-assets" in dry_run
    assert main.count("steps.release_assets.outputs.files") >= 2
    assert dry_run.count("steps.release_assets.outputs.files") >= 2
    assert "id: release_assets" in main
    assert "id: release_assets" in dry_run
    assert "softprops/action-gh-release" in main
    assert "softprops/action-gh-release" not in dry_run
    assert "--validate-release" in main
    assert "--validate-release" in dry_run
