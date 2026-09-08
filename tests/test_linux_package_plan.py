"""Focused contract tests for the shared Linux packaging command."""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
PACKAGE_SCRIPT = ROOT / "scripts/linux/package.sh"


def run_package(*args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    process_env = os.environ.copy()
    if env:
        process_env.update(env)
    return subprocess.run(
        ["bash", str(PACKAGE_SCRIPT), *args],
        cwd=ROOT,
        env=process_env,
        text=True,
        capture_output=True,
        check=False,
    )


def test_artifact_plan_has_canonical_versioned_and_stable_names() -> None:
    result = run_package("--print-plan", "1.57.0")

    assert result.returncode == 0, result.stderr
    plan = dict(line.split("=", 1) for line in result.stdout.splitlines())
    assert plan == {
        "deb_versioned": "datapyn_1.57.0_amd64.deb",
        "deb_stable": "datapyn_amd64.deb",
        "rpm_versioned": "datapyn-1.57.0-1.x86_64.rpm",
        "rpm_stable": "datapyn-x86_64.rpm",
        "pacman_versioned": "datapyn-1.57.0-1-x86_64.pkg.tar.zst",
        "pacman_stable": "datapyn-x86_64.pkg.tar.zst",
        "appimage_versioned": "DataPyn-1.57.0-x86_64.AppImage",
        "appimage_stable": "DataPyn-x86_64.AppImage",
        "tar_versioned": "DataPyn-1.57.0-linux-x86_64.tar.gz",
        "tar_stable": "DataPyn-linux-x86_64.tar.gz",
    }


def test_shared_stage_contains_payload_and_desktop_integration(tmp_path: Path) -> None:
    dist_dir = tmp_path / "dist" / "DataPyn"
    stage_dir = tmp_path / "pkg"
    dist_dir.mkdir(parents=True)
    (dist_dir / "DataPyn").write_text("fixture payload", encoding="utf-8")

    command = f"source {shlex.quote(str(PACKAGE_SCRIPT))}; stage_payload"
    result = subprocess.run(
        ["bash", "-c", command],
        cwd=ROOT,
        env={
            **os.environ,
            "DATAPYN_PACKAGE_DIST_DIR": str(dist_dir),
            "DATAPYN_PACKAGE_STAGE_DIR": str(stage_dir),
        },
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    expected_files = (
        "opt/datapyn/DataPyn",
        "opt/datapyn/datapyn-wrapper.sh",
        "opt/datapyn/datapyn_logo.svg",
        "usr/share/applications/datapyn.desktop",
        "usr/share/mime/packages/datapyn-workspace.xml",
    )
    for relative_path in expected_files:
        assert (stage_dir / relative_path).is_file(), relative_path
    assert os.access(stage_dir / "opt/datapyn/datapyn-wrapper.sh", os.X_OK)


def test_missing_bundle_fails_with_existing_message_and_no_outputs(tmp_path: Path) -> None:
    output_dir = tmp_path / "output"
    result = run_package(
        "1.57.0",
        env={
            "DATAPYN_PACKAGE_DIST_DIR": str(tmp_path / "missing" / "DataPyn"),
            "DATAPYN_PACKAGE_OUTPUT_DIR": str(output_dir),
            "DATAPYN_PACKAGE_STAGE_DIR": str(tmp_path / "pkg"),
        },
    )

    assert result.returncode == 1
    assert result.stderr.strip() == "error: dist/DataPyn not found. Run PyInstaller first."
    assert not output_dir.exists()


@pytest.mark.parametrize(
    ("family", "required", "recommended"),
    (
        (
            "deb",
            {
                "libgl1",
                "libegl1",
                "libxkbcommon0",
                "libxkbcommon-x11-0",
                "libdbus-1-3",
                "libxcb-cursor0",
                "libxcb-icccm4",
                "libxcb-image0",
                "libxcb-keysyms1",
                "libxcb-randr0",
                "libxcb-render-util0",
                "libxcb-xinerama0",
                "libxcb-xfixes0",
                "libnss3",
                "libnspr4",
                "libgbm1",
                "libasound2",
                "libdrm2",
                "libxcomposite1",
                "libxdamage1",
                "libxrandr2",
                "libxss1",
                "libxtst6",
                "libatk1.0-0",
                "libatk-bridge2.0-0",
                "libcups2",
                "libpango-1.0-0",
            },
            {"libsecret-1-0", "unixodbc"},
        ),
        (
            "rpm",
            {
                "mesa-libGL",
                "mesa-libEGL",
                "libxkbcommon",
                "libxkbcommon-x11",
                "dbus-libs",
                "xcb-util-cursor",
                "xcb-util-wm",
                "xcb-util-image",
                "xcb-util-keysyms",
                "libxcb",
                "xcb-util-renderutil",
                "nss",
                "nspr",
                "mesa-libgbm",
                "alsa-lib",
                "libdrm",
                "libXcomposite",
                "libXdamage",
                "libXrandr",
                "libXScrnSaver",
                "libXtst",
                "atk",
                "at-spi2-atk",
                "cups-libs",
                "pango",
            },
            {"libsecret", "unixODBC"},
        ),
        (
            "pacman",
            {
                "mesa",
                "libxkbcommon",
                "libxkbcommon-x11",
                "dbus",
                "xcb-util-cursor",
                "xcb-util-wm",
                "xcb-util-image",
                "xcb-util-keysyms",
                "libxcb",
                "xcb-util-renderutil",
                "nss",
                "nspr",
                "alsa-lib",
                "libdrm",
                "libxcomposite",
                "libxdamage",
                "libxrandr",
                "libxss",
                "libxtst",
                "atk",
                "at-spi2-core",
                "libcups",
                "pango",
            },
            {"libsecret", "unixodbc"},
        ),
    ),
)
def test_target_dependency_mapping_is_complete(
    family: str, required: set[str], recommended: set[str]
) -> None:
    result = run_package("--print-dependencies", family)

    assert result.returncode == 0, result.stderr
    dependencies = {
        line.split("=", 1)[1]
        for line in result.stdout.splitlines()
        if line.startswith("depends=")
    }
    recommendations = {
        line.split("=", 1)[1]
        for line in result.stdout.splitlines()
        if line.startswith("recommends=")
    }
    assert dependencies == required
    assert recommendations == recommended


def test_unmapped_dependency_capability_fails_target_mapping() -> None:
    command = f"source {shlex.quote(str(PACKAGE_SCRIPT))}; map_dependency rpm missing_capability"
    result = subprocess.run(
        ["bash", "-c", command],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode != 0
    assert "missing rpm dependency mapping for capability: missing_capability" in result.stderr


@pytest.mark.integration
def test_native_package_metadata_and_aliases(tmp_path: Path) -> None:
    required_tools = ("fpm", "dpkg-deb", "rpm", "rpmbuild", "pacman", "zstd")
    missing_tools = [tool for tool in required_tools if shutil.which(tool) is None]
    if missing_tools:
        pytest.skip(f"native packaging toolchain unavailable: {', '.join(missing_tools)}")

    dist_dir = tmp_path / "dist" / "DataPyn"
    output_dir = tmp_path / "output"
    stage_dir = tmp_path / "pkg"
    dist_dir.mkdir(parents=True)
    executable = dist_dir / "DataPyn"
    executable.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    executable.chmod(0o755)

    result = run_package(
        "1.57.0",
        env={
            "DATAPYN_PACKAGE_DIST_DIR": str(dist_dir),
            "DATAPYN_PACKAGE_OUTPUT_DIR": str(output_dir),
            "DATAPYN_PACKAGE_STAGE_DIR": str(stage_dir),
        },
    )
    assert result.returncode == 0, result.stderr

    versioned = (
        "datapyn_1.57.0_amd64.deb",
        "datapyn-1.57.0-1.x86_64.rpm",
        "datapyn-1.57.0-1-x86_64.pkg.tar.zst",
        "DataPyn-1.57.0-linux-x86_64.tar.gz",
    )
    aliases = (
        "datapyn_amd64.deb",
        "datapyn-x86_64.rpm",
        "datapyn-x86_64.pkg.tar.zst",
        "DataPyn-linux-x86_64.tar.gz",
    )
    for filename in (*versioned, *aliases):
        assert (output_dir / filename).is_file(), filename
    for source, alias in zip(versioned, aliases, strict=True):
        assert (output_dir / source).read_bytes() == (output_dir / alias).read_bytes()

    deb_metadata = subprocess.run(
        ["dpkg-deb", "--field", str(output_dir / versioned[0])],
        text=True,
        capture_output=True,
        check=True,
    ).stdout
    assert "Version: 1.57.0" in deb_metadata
    assert "Architecture: amd64" in deb_metadata

    rpm_metadata = subprocess.run(
        ["rpm", "-qp", "--queryformat", "%{VERSION} %{ARCH}", str(output_dir / versioned[1])],
        text=True,
        capture_output=True,
        check=True,
    ).stdout
    assert rpm_metadata == "1.57.0 x86_64"

    pacman_metadata = subprocess.run(
        ["pacman", "-Qip", str(output_dir / versioned[2])],
        text=True,
        capture_output=True,
        check=True,
    ).stdout
    assert "Version        : 1.57.0-1" in pacman_metadata
    assert "Architecture   : x86_64" in pacman_metadata
