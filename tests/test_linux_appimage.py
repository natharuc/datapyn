"""Focused contract tests for the x86_64 FUSE3 AppImage path."""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
PACKAGE_SCRIPT = ROOT / "scripts/linux/package.sh"
APPIMAGE_RUN = ROOT / "scripts/linux/datapyn-appimage-apprun.sh"


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


def test_appimage_metadata_declares_portable_x86_64_fuse3_contract() -> None:
    result = run_package("--print-appimage-metadata", "1.57.0")

    assert result.returncode == 0, result.stderr
    metadata = dict(line.split("=", 1) for line in result.stdout.splitlines())
    assert metadata == {
        "appimage_format": "appimage",
        "appimage_distro_family": "universal",
        "appimage_architecture": "x86_64",
        "appimage_display_name": "Universal Linux (AppImage, FUSE3)",
        "appimage_filename": "DataPyn-1.57.0-x86_64.AppImage",
        "appimage_stable_alias": "DataPyn-x86_64.AppImage",
        "appimage_requires": "fuse3",
        "appimage_install_mode": "portable",
        "appimage_runtime": "type2",
        "appimage_runtime_version": "20251108",
        "appimage_runtime_sha256": "2fca8b443c92510f1483a883f60061ad09b46b978b2631c807cd873a47ec260d",
        "appimage_builder_version": "1.9.1",
        "appimage_builder_sha256": "ed4ce84f0d9caff66f50bcca6ff6f35aae54ce8135408b3fa33abfc3cb384eb0",
    }


def test_fuse2_only_policy_is_rejected() -> None:
    result = run_package("--validate-fuse-policy", "fuse3 libfuse2")

    assert result.returncode != 0
    assert "FUSE2-only AppImage policy is rejected" in result.stderr


def test_fuse3_policy_accepts_fusermount3_without_fuse2() -> None:
    result = run_package("--validate-fuse-policy", "fuse3 fusermount3")

    assert result.returncode == 0, result.stderr


def _run_fuse3_environment_check(
    tmp_path: Path,
    commands: dict[str, str],
) -> subprocess.CompletedProcess[str]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()

    for utility in ("dirname", "grep", "pwd"):
        utility_path = shutil.which(utility)
        assert utility_path is not None, f"required test utility is unavailable: {utility}"
        (bin_dir / utility).symlink_to(utility_path)

    for name, contents in commands.items():
        command_path = bin_dir / name
        command_path.write_text(contents, encoding="utf-8")
        command_path.chmod(0o755)

    environment = os.environ.copy()
    environment["PATH"] = str(bin_dir)
    environment.pop("DATAPYN_APPIMAGE_FUSE_POLICY", None)
    bash = shutil.which("bash")
    assert bash is not None, "bash is required for the shell gate test"
    return subprocess.run(
        [bash, str(PACKAGE_SCRIPT), "--validate-fuse3-environment"],
        cwd=ROOT,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )


def test_ut028_fuse3_environment_accepts_coexisting_legacy_command(tmp_path: Path) -> None:
    result = _run_fuse3_environment_check(
        tmp_path,
        {"fusermount3": "", "fusermount": ""},
    )

    assert result.returncode == 0, result.stderr


def test_ut028_fuse3_environment_ignores_legacy_packages(tmp_path: Path) -> None:
    result = _run_fuse3_environment_check(
        tmp_path,
        {
            "fusermount3": "",
            "dpkg-query": "#!/bin/sh\nprintf '%s\\n' 'install ok installed'\n",
        },
    )

    assert result.returncode == 0, result.stderr


def test_ut028_fuse3_environment_rejects_missing_fusermount3(tmp_path: Path) -> None:
    result = _run_fuse3_environment_check(tmp_path, {"fusermount": ""})

    assert result.returncode != 0
    assert "required executable 'fusermount3' is missing" in result.stderr


def _controlled_fuse3_environment_error(
    command_lookup: Callable[[str], str | None] = shutil.which,
    fuse_device: Path = Path("/dev/fuse"),
) -> str | None:
    missing: list[str] = []
    if command_lookup("fusermount3") is None:
        missing.append("fusermount3")
    if not fuse_device.exists():
        missing.append("/dev/fuse")
    if not missing:
        return None
    return "controlled FUSE3 mount environment is unavailable; missing: " + ", ".join(missing)


def _require_controlled_fuse3_environment() -> None:
    error = _controlled_fuse3_environment_error()
    if error:
        pytest.fail(error)


@pytest.mark.parametrize(
    ("command_path", "fuse_device", "missing"),
    [
        (None, Path("/dev/fuse"), "fusermount3"),
        ("/usr/bin/fusermount3", Path("/dev/null/datapyn-fuse"), "/dev/fuse"),
    ],
)
def test_it010_missing_controlled_fuse3_prerequisite_fails(
    command_path: str | None,
    fuse_device: Path,
    missing: str,
) -> None:
    error = _controlled_fuse3_environment_error(
        command_lookup=lambda _name: command_path,
        fuse_device=fuse_device,
    )

    assert error is not None
    assert missing in error
    assert "skipped" not in error


def test_pinned_tool_checksum_rejects_changed_bytes(tmp_path: Path) -> None:
    changed_tool = tmp_path / "appimagetool"
    changed_tool.write_bytes(b"changed pinned tool")
    command = (
        f"source {shlex.quote(str(PACKAGE_SCRIPT))}; "
        f"verify_pinned_file builder {shlex.quote(str(changed_tool))} {'0' * 64}"
    )

    result = subprocess.run(
        ["bash", "-c", command],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode != 0
    assert "builder checksum mismatch" in result.stderr


def test_appdir_uses_shared_payload_and_local_desktop_paths(tmp_path: Path) -> None:
    dist_dir = tmp_path / "dist" / "DataPyn"
    stage_dir = tmp_path / "pkg"
    appdir = tmp_path / "AppDir"
    dist_dir.mkdir(parents=True)
    executable = dist_dir / "DataPyn"
    executable.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    executable.chmod(0o755)

    command = f"source {shlex.quote(str(PACKAGE_SCRIPT))}; stage_payload; prepare_appimage_dir; validate_appdir"
    result = subprocess.run(
        ["bash", "-c", command],
        cwd=ROOT,
        env={
            **os.environ,
            "DATAPYN_PACKAGE_DIST_DIR": str(dist_dir),
            "DATAPYN_PACKAGE_STAGE_DIR": str(stage_dir),
            "DATAPYN_PACKAGE_APPDIR": str(appdir),
        },
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert (appdir / "AppRun").stat().st_mode & 0o111
    assert (appdir / "usr/bin/DataPyn").is_file()
    assert (appdir / "datapyn.desktop").read_text(encoding="utf-8").find("Exec=DataPyn %F") >= 0
    assert "Icon=datapyn_logo" in (appdir / "datapyn.desktop").read_text(encoding="utf-8")
    assert (appdir / "datapyn_logo.svg").is_file()


def test_apprun_forwards_environment_and_arguments(tmp_path: Path) -> None:
    appdir = tmp_path / "AppDir"
    payload_dir = appdir / "usr/bin"
    payload_dir.mkdir(parents=True)
    payload = payload_dir / "DataPyn"
    payload.write_text(
        "#!/bin/sh\n"
        "printf 'sandbox=%s\\n' \"$QTWEBENGINE_DISABLE_SANDBOX\"\n"
        "printf 'flags=%s\\n' \"$QTWEBENGINE_CHROMIUM_FLAGS\"\n"
        "for arg in \"$@\"; do printf 'arg=%s\\n' \"$arg\"; done\n",
        encoding="utf-8",
    )
    payload.chmod(0o755)
    app_run = appdir / "AppRun"
    shutil.copy2(APPIMAGE_RUN, app_run)
    app_run.chmod(0o755)

    result = subprocess.run(
        [str(app_run), "first", "two words", "--flag=value"],
        cwd=ROOT,
        env={**os.environ, "QTWEBENGINE_CHROMIUM_FLAGS": "--custom-flag"},
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == [
        "sandbox=1",
        "flags=--custom-flag",
        "arg=first",
        "arg=two words",
        "arg=--flag=value",
    ]


def _appimage_toolchain_available() -> tuple[str, str] | None:
    tool = os.environ.get("DATAPYN_APPIMAGE_TOOL") or shutil.which("appimagetool")
    runtime = os.environ.get("DATAPYN_APPIMAGE_RUNTIME")
    if not tool or not runtime:
        return None
    if not Path(tool).is_file() or not Path(runtime).is_file():
        return None
    return tool, runtime


@pytest.fixture(scope="module")
def fixture_appimage(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, Path | None]:
    packaged_artifact = os.environ.get("DATAPYN_APPIMAGE_SMOKE_ARTIFACT")
    if packaged_artifact:
        artifact = Path(packaged_artifact)
        if not artifact.is_file():
            pytest.fail(f"package.sh AppImage artifact is missing: {artifact}")
        if not artifact.stat().st_mode & 0o111:
            pytest.fail(f"package.sh AppImage artifact is not executable: {artifact}")
        smoke_log = os.environ.get("DATAPYN_APPIMAGE_SMOKE_LOG")
        return artifact, Path(smoke_log) if smoke_log else None

    toolchain = _appimage_toolchain_available()
    if toolchain is None:
        pytest.skip("pinned AppImage builder/runtime are not available")

    root = tmp_path_factory.mktemp("appimage")
    dist_dir = root / "dist" / "DataPyn"
    output_dir = root / "output"
    stage_dir = root / "pkg"
    appdir = root / "AppDir"
    smoke_log = root / "smoke.log"
    dist_dir.mkdir(parents=True)
    executable = dist_dir / "DataPyn"
    executable.write_text(
        "#!/bin/sh\n"
        ": \"${DATAPYN_APPIMAGE_SMOKE_LOG:?}\"\n"
        ": > \"$DATAPYN_APPIMAGE_SMOKE_LOG\"\n"
        "printf 'sandbox=%s\\n' \"$QTWEBENGINE_DISABLE_SANDBOX\" >> \"$DATAPYN_APPIMAGE_SMOKE_LOG\"\n"
        "printf 'flags=%s\\n' \"$QTWEBENGINE_CHROMIUM_FLAGS\" >> \"$DATAPYN_APPIMAGE_SMOKE_LOG\"\n"
        "for arg in \"$@\"; do printf 'arg=%s\\n' \"$arg\" >> \"$DATAPYN_APPIMAGE_SMOKE_LOG\"; done\n",
        encoding="utf-8",
    )
    executable.chmod(0o755)

    result = run_package(
        "--appimage-only",
        "1.57.0",
        env={
            "DATAPYN_PACKAGE_DIST_DIR": str(dist_dir),
            "DATAPYN_PACKAGE_OUTPUT_DIR": str(output_dir),
            "DATAPYN_PACKAGE_STAGE_DIR": str(stage_dir),
            "DATAPYN_PACKAGE_APPDIR": str(appdir),
            "DATAPYN_APPIMAGE_SMOKE_LOG": str(smoke_log),
        },
    )
    assert result.returncode == 0, result.stderr
    artifact = output_dir / "DataPyn-1.57.0-x86_64.AppImage"
    assert artifact.is_file()
    assert artifact.stat().st_mode & 0o111
    assert (output_dir / "DataPyn-x86_64.AppImage").read_bytes() == artifact.read_bytes()
    return artifact, smoke_log


@pytest.mark.integration
def test_appimage_extract_and_run_fallback_forwards_arguments(
    fixture_appimage: tuple[Path, Path | None],
) -> None:
    artifact, smoke_log = fixture_appimage
    arguments = ("first", "two words") if smoke_log else ("first", "two words", "--help")
    result = run_package(
        "--smoke-appimage-extract-and-run",
        str(artifact),
        *arguments,
        env={"DATAPYN_APPIMAGE_SMOKE_LOG": str(smoke_log)} if smoke_log else None,
    )

    assert result.returncode == 0, result.stderr
    if smoke_log:
        assert smoke_log.read_text(encoding="utf-8").splitlines() == [
            "sandbox=1",
            "flags=--no-sandbox",
            "arg=first",
            "arg=two words",
        ]
    else:
        assert "DataPyn" in (result.stdout + result.stderr)


@pytest.mark.integration
def test_appimage_normal_fuse3_smoke_with_fuse3_mount(request: pytest.FixtureRequest) -> None:
    packaged_artifact = os.environ.get("DATAPYN_APPIMAGE_SMOKE_ARTIFACT")
    if packaged_artifact:
        # Release workflows set the already-built artifact before entering the strict smoke path;
        # validate prerequisites before resolving the fixture so a missing device cannot skip.
        _require_controlled_fuse3_environment()

    artifact, smoke_log = request.getfixturevalue("fixture_appimage")
    if not packaged_artifact:
        _require_controlled_fuse3_environment()
    arguments = ("first", "two words") if smoke_log else ("first", "two words", "--help")
    result = run_package(
        "--smoke-appimage",
        str(artifact),
        *arguments,
        env={"DATAPYN_APPIMAGE_SMOKE_LOG": str(smoke_log)} if smoke_log else None,
    )

    assert result.returncode == 0, result.stderr
    if smoke_log:
        assert "arg=two words" in smoke_log.read_text(encoding="utf-8")
    else:
        assert "DataPyn" in (result.stdout + result.stderr)
