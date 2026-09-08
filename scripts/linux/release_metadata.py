#!/usr/bin/env python3
"""Build and validate the Linux release manifest and checksum list.

This module is intentionally dependency-free.  ``package.sh`` owns the build order and invokes
this helper only after the five versioned artifacts and their stable aliases exist.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import tempfile
from pathlib import Path
from typing import Any, Iterable


PRODUCT = "DataPyn"
ARCHITECTURE = "x86_64"
SCHEMA_VERSION = 1
MANIFEST_FILENAME = "DataPyn-linux-artifacts.json"
CHECKSUMS_FILENAME = "SHA256SUMS"
DEFAULT_REPOSITORY = "natharuc/datapyn"

TOP_LEVEL_FIELDS = {
    "schema_version",
    "product",
    "version",
    "release_tag",
    "architecture",
    "artifacts",
}
ARTIFACT_FIELDS = {
    "id",
    "format",
    "distro_family",
    "display_name",
    "filename",
    "download_url",
    "sha256",
    "requires",
    "install_mode",
}
KNOWN_FORMATS = {"deb", "rpm", "pacman", "appimage", "tar.gz"}
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
VERSION_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9.+~:_-]*$")
TAG_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9.+~:/_-]*$")
REPOSITORY_RE = re.compile(r"^[^/\s]+/[^/\s]+$")


class MetadataError(ValueError):
    """A named release metadata or completeness failure."""


def expected_artifacts(version: str) -> list[dict[str, Any]]:
    """Return the required five artifact definitions for *version*."""

    return [
        {
            "id": "debian-amd64",
            "format": "deb",
            "distro_family": "debian",
            "display_name": "Ubuntu/Debian (.deb)",
            "filename": f"datapyn_{version}_amd64.deb",
            "stable_alias": "datapyn_amd64.deb",
            "requires": [],
            "install_mode": "native-package",
        },
        {
            "id": "fedora-rpm",
            "format": "rpm",
            "distro_family": "rpm",
            "display_name": "Fedora/RHEL/openSUSE (.rpm)",
            "filename": f"datapyn-{version}-1.x86_64.rpm",
            "stable_alias": "datapyn-x86_64.rpm",
            "requires": [],
            "install_mode": "native-package",
        },
        {
            "id": "arch-pacman",
            "format": "pacman",
            "distro_family": "arch",
            "display_name": "Arch/Manjaro (.pkg.tar.zst)",
            "filename": f"datapyn-{version}-1-x86_64.pkg.tar.zst",
            "stable_alias": "datapyn-x86_64.pkg.tar.zst",
            "requires": [],
            "install_mode": "native-package",
        },
        {
            "id": "universal-appimage",
            "format": "appimage",
            "distro_family": "universal",
            "display_name": "Universal Linux (AppImage, FUSE3)",
            "filename": f"DataPyn-{version}-x86_64.AppImage",
            "stable_alias": "DataPyn-x86_64.AppImage",
            "requires": ["fuse3"],
            "install_mode": "portable",
        },
        {
            "id": "other-linux-tarball",
            "format": "tar.gz",
            "distro_family": "generic",
            "display_name": "Other Linux (.tar.gz)",
            "filename": f"DataPyn-{version}-linux-x86_64.tar.gz",
            "stable_alias": "DataPyn-linux-x86_64.tar.gz",
            "requires": [],
            "install_mode": "manual-extract",
        },
    ]


def versioned_filenames(version: str) -> list[str]:
    return [artifact["filename"] for artifact in expected_artifacts(version)]


def stable_aliases(version: str) -> list[str]:
    return [artifact["stable_alias"] for artifact in expected_artifacts(version)]


def release_asset_filenames(version: str) -> list[str]:
    """Return the exact files that the release workflows must upload."""

    return [
        *versioned_filenames(version),
        *stable_aliases(version),
        MANIFEST_FILENAME,
        CHECKSUMS_FILENAME,
    ]


def validate_version(version: str) -> None:
    if not VERSION_RE.fullmatch(version):
        raise MetadataError(f"invalid release version: {version}")


def normalize_release_tag(version: str, release_tag: str | None) -> str:
    tag = release_tag or os.environ.get("DATAPYN_RELEASE_TAG") or f"v{version}"
    if not TAG_RE.fullmatch(tag):
        raise MetadataError(f"invalid release tag: {tag}")
    return tag


def normalize_repository(repository: str | None) -> str:
    value = repository or os.environ.get("GITHUB_REPOSITORY") or DEFAULT_REPOSITORY
    if not REPOSITORY_RE.fullmatch(value):
        raise MetadataError(f"invalid GitHub repository: {value}")
    return value


def release_url(repository: str, release_tag: str, filename: str) -> str:
    return f"https://github.com/{repository}/releases/download/{release_tag}/{filename}"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as exc:
        raise MetadataError(f"cannot read release artifact {path.name}: {exc}") from exc
    return digest.hexdigest()


def _require_file(output_dir: Path, filename: str, *, label: str = "artifact") -> Path:
    path = output_dir / filename
    if not path.is_file():
        raise MetadataError(f"missing required Linux release {label}: {filename}")
    if path.stat().st_size == 0:
        raise MetadataError(f"required Linux release {label} is empty: {filename}")
    return path


def validate_artifact_set(output_dir: Path, version: str) -> None:
    """Validate versioned artifacts and byte-identical stable aliases."""

    definitions = expected_artifacts(version)
    for artifact in definitions:
        versioned = _require_file(output_dir, artifact["filename"])
        alias = _require_file(output_dir, artifact["stable_alias"], label="stable alias")
        try:
            same_bytes = versioned.read_bytes() == alias.read_bytes()
        except OSError as exc:
            raise MetadataError(f"cannot compare stable alias {artifact['stable_alias']}: {exc}") from exc
        if not same_bytes:
            raise MetadataError(
                f"stable alias is not byte-identical to {artifact['filename']}: {artifact['stable_alias']}"
            )


def _manifest_artifact(artifact: dict[str, Any], output_dir: Path, repository: str, release_tag: str) -> dict[str, Any]:
    filename = artifact["filename"]
    path = _require_file(output_dir, filename)
    return {
        "id": artifact["id"],
        "format": artifact["format"],
        "distro_family": artifact["distro_family"],
        "display_name": artifact["display_name"],
        "filename": filename,
        "download_url": release_url(repository, release_tag, filename),
        "sha256": sha256_file(path),
        "requires": artifact["requires"],
        "install_mode": artifact["install_mode"],
    }


def build_manifest(
    output_dir: Path,
    version: str,
    release_tag: str | None = None,
    repository: str | None = None,
) -> dict[str, Any]:
    """Build and atomically write the manifest and versioned checksum list."""

    validate_version(version)
    tag = normalize_release_tag(version, release_tag)
    repo = normalize_repository(repository)
    output_dir = output_dir.resolve()
    if not output_dir.is_dir():
        raise MetadataError(f"release output directory is missing: {output_dir}")

    validate_artifact_set(output_dir, version)
    artifacts = [_manifest_artifact(item, output_dir, repo, tag) for item in expected_artifacts(version)]
    manifest: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "product": PRODUCT,
        "version": version,
        "release_tag": tag,
        "architecture": ARCHITECTURE,
        "artifacts": artifacts,
    }
    checksum_text = "".join(f"{item['sha256']}  {item['filename']}\n" for item in artifacts)
    _atomic_write(output_dir / CHECKSUMS_FILENAME, checksum_text)
    _atomic_write(
        output_dir / MANIFEST_FILENAME,
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
    )
    return manifest


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary:
            temporary.write(content)
            temporary.flush()
            os.fsync(temporary.fileno())
            temporary_path = Path(temporary.name)
        os.replace(temporary_path, path)
    except OSError as exc:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
        raise MetadataError(f"cannot write {path.name}: {exc}") from exc


def _validate_sha256(label: str, value: Any) -> str:
    if not isinstance(value, str) or not SHA256_RE.fullmatch(value):
        raise MetadataError(f"{label} must be a lowercase 64-character SHA-256 value")
    return value


def _load_manifest(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise MetadataError(f"missing release manifest: {path.name}")
    try:
        with path.open(encoding="utf-8") as stream:
            document = json.load(stream)
    except (OSError, json.JSONDecodeError) as exc:
        raise MetadataError(f"cannot parse release manifest {path.name}: {exc}") from exc
    if not isinstance(document, dict):
        raise MetadataError("release manifest must be a JSON object")
    return document


def _load_checksums(path: Path) -> dict[str, str]:
    if not path.is_file():
        raise MetadataError(f"missing release checksum file: {path.name}")
    entries: dict[str, str] = {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise MetadataError(f"cannot read release checksum file {path.name}: {exc}") from exc
    for line_number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        parts = line.split(maxsplit=1)
        if len(parts) != 2 or not SHA256_RE.fullmatch(parts[0]):
            raise MetadataError(f"invalid SHA-256 entry on line {line_number} of {path.name}")
        filename = parts[1]
        if filename.startswith("*"):
            filename = filename[1:]
        if not filename or filename in entries:
            raise MetadataError(f"duplicate or empty checksum filename on line {line_number} of {path.name}")
        entries[filename] = parts[0]
    return entries


def _validate_field_shape(index: int, artifact: Any) -> dict[str, Any]:
    prefix = f"manifest artifacts[{index}]"
    if not isinstance(artifact, dict):
        raise MetadataError(f"{prefix} must be an object")
    if set(artifact) != ARTIFACT_FIELDS:
        missing = sorted(ARTIFACT_FIELDS - set(artifact))
        extra = sorted(set(artifact) - ARTIFACT_FIELDS)
        detail: list[str] = []
        if missing:
            detail.append(f"missing fields: {', '.join(missing)}")
        if extra:
            detail.append(f"unexpected fields: {', '.join(extra)}")
        raise MetadataError(f"{prefix} has invalid fields ({'; '.join(detail)})")
    for field in ("id", "format", "distro_family", "display_name", "filename", "install_mode"):
        if not isinstance(artifact[field], str) or not artifact[field].strip():
            raise MetadataError(f"{prefix}.{field} must be a non-empty string")
    if not isinstance(artifact["requires"], list) or not all(
        isinstance(requirement, str) and requirement for requirement in artifact["requires"]
    ):
        raise MetadataError(f"{prefix}.requires must be an array of non-empty strings")
    if "/" in artifact["filename"] or "\\" in artifact["filename"] or artifact["filename"] in {".", ".."}:
        raise MetadataError(f"{prefix}.filename must be a release filename, not a path")
    if not isinstance(artifact["download_url"], str) or not artifact["download_url"].startswith("https://"):
        raise MetadataError(f"{prefix}.download_url must be an HTTPS URL")
    _validate_sha256(f"{prefix}.sha256", artifact["sha256"])
    return artifact


def _validate_manifest_shape(
    document: dict[str, Any],
    output_dir: Path,
    version: str,
    release_tag: str,
    repository: str,
) -> list[dict[str, Any]]:
    if set(document) != TOP_LEVEL_FIELDS:
        missing = sorted(TOP_LEVEL_FIELDS - set(document))
        extra = sorted(set(document) - TOP_LEVEL_FIELDS)
        detail: list[str] = []
        if missing:
            detail.append(f"missing fields: {', '.join(missing)}")
        if extra:
            detail.append(f"unexpected fields: {', '.join(extra)}")
        raise MetadataError(f"release manifest has invalid fields ({'; '.join(detail)})")
    if document["schema_version"] != SCHEMA_VERSION:
        raise MetadataError(f"release manifest schema_version must be {SCHEMA_VERSION}")
    if document["product"] != PRODUCT:
        raise MetadataError(f"release manifest product must be {PRODUCT}")
    if document["version"] != version:
        raise MetadataError(f"release manifest version does not match {version}")
    if document["release_tag"] != release_tag:
        raise MetadataError(f"release manifest release_tag does not match {release_tag}")
    if document["architecture"] != ARCHITECTURE:
        raise MetadataError(f"release manifest architecture must be {ARCHITECTURE}")
    if not isinstance(document["artifacts"], list) or not document["artifacts"]:
        raise MetadataError("release manifest artifacts must be a non-empty array")

    artifacts = [_validate_field_shape(index, artifact) for index, artifact in enumerate(document["artifacts"])]
    ids = [artifact["id"] for artifact in artifacts]
    filenames = [artifact["filename"] for artifact in artifacts]
    if len(ids) != len(set(ids)):
        raise MetadataError("release manifest artifact ids must be unique")
    if len(filenames) != len(set(filenames)):
        raise MetadataError("release manifest artifact filenames must be unique")

    expected = expected_artifacts(version)
    by_id = {artifact["id"]: artifact for artifact in artifacts}
    for required in expected:
        actual = by_id.get(required["id"])
        if actual is None:
            raise MetadataError(f"release manifest is missing required artifact: {required['filename']}")
        for field in ("format", "distro_family", "display_name", "filename", "requires", "install_mode"):
            if actual[field] != required[field]:
                raise MetadataError(
                    f"release manifest {required['id']}.{field} does not match the required {required[field]}"
                )

    expected_url_prefix = f"https://github.com/{repository}/releases/download/{release_tag}/"
    for index, artifact in enumerate(artifacts):
        prefix = f"manifest artifacts[{index}]"
        expected_url = f"{expected_url_prefix}{artifact['filename']}"
        if artifact["download_url"] != expected_url:
            raise MetadataError(f"{prefix}.download_url does not point to the versioned release filename")
        _require_file(output_dir, artifact["filename"])
        actual_digest = sha256_file(output_dir / artifact["filename"])
        if artifact["sha256"] != actual_digest:
            raise MetadataError(f"{prefix}.sha256 does not match {artifact['filename']}")
    return artifacts


def validate_release(
    output_dir: Path,
    version: str,
    release_tag: str | None = None,
    repository: str | None = None,
) -> dict[str, Any]:
    """Validate the complete local release boundary and return its manifest."""

    validate_version(version)
    tag = normalize_release_tag(version, release_tag)
    repo = normalize_repository(repository)
    output_dir = output_dir.resolve()
    if not output_dir.is_dir():
        raise MetadataError(f"release output directory is missing: {output_dir}")

    validate_artifact_set(output_dir, version)
    document = _load_manifest(output_dir / MANIFEST_FILENAME)
    artifacts = _validate_manifest_shape(document, output_dir, version, tag, repo)
    checksums = _load_checksums(output_dir / CHECKSUMS_FILENAME)
    for artifact in artifacts:
        filename = artifact["filename"]
        checksum = checksums.get(filename)
        if checksum is None:
            raise MetadataError(f"missing checksum for {filename} in {CHECKSUMS_FILENAME}")
        if checksum != artifact["sha256"]:
            raise MetadataError(f"checksum does not match manifest for {filename}")
        actual_digest = sha256_file(output_dir / filename)
        if checksum != actual_digest:
            raise MetadataError(f"checksum does not match file {filename}")
    return document


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("build", "validate", "print-assets"))
    parser.add_argument("--output-dir", type=Path, default=Path.cwd())
    parser.add_argument("--version", required=True)
    parser.add_argument("--release-tag")
    parser.add_argument("--repository")
    return parser


def _run(args: argparse.Namespace) -> int:
    if args.action == "print-assets":
        validate_version(args.version)
        print("\n".join(release_asset_filenames(args.version)))
        return 0

    if args.action == "build":
        build_manifest(args.output_dir, args.version, args.release_tag, args.repository)
        print(f"Generated {MANIFEST_FILENAME} and {CHECKSUMS_FILENAME}")
        return 0

    validate_release(args.output_dir, args.version, args.release_tag, args.repository)
    print(f"Validated complete Linux release: {args.version}")
    return 0


def main(argv: Iterable[str] | None = None) -> int:
    parser = _build_parser()
    try:
        return _run(parser.parse_args(list(argv) if argv is not None else None))
    except MetadataError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
