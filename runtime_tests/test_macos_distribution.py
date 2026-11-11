"""Validate macOS release checks without installing packages on the test host."""

import hashlib
import importlib.util
import io
import json
from pathlib import Path
import struct
import sys
from types import SimpleNamespace

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts" / "tauri"


def load_script(name):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


compatibility = load_script("macos_compatibility")
prerequisites = load_script("macos_prerequisites")


def macho(minimum=(14, 0, 0), *, sdk=(26, 0, 0), cpu=compatibility.ARM64, legacy=False):
    def packed(value):
        return value[0] << 16 | value[1] << 8 | value[2]

    if minimum is None:
        command = b""
    elif legacy:
        command = struct.pack("<IIII", 0x24, 16, packed(minimum), packed(sdk))
    else:
        command = struct.pack("<IIIIII", 0x32, 24, 1, packed(minimum), packed(sdk), 0)
    header = struct.pack("<IIIIIIII", 0xFEEDFACF, cpu, 0, 2, bool(command), len(command), 0, 0)
    return header + command


@pytest.mark.parametrize("minimum", [(11, 0, 0), (14, 0, 0)])
@pytest.mark.parametrize("legacy", [False, True])
def test_minimum_uses_deployment_target_instead_of_sdk(minimum, legacy):
    assert compatibility.check_macho(macho(minimum, legacy=legacy), "library") == 1


def test_incompatible_library_explains_minimum_requirement():
    with pytest.raises(ValueError, match=r"library: requires macOS 15.0.0"):
        compatibility.check_macho(macho((15, 0, 0)), "library")


def test_arm64_binary_without_version_cannot_pass():
    with pytest.raises(ValueError, match="missing macOS deployment target"):
        compatibility.check_macho(macho(None), "library")


def test_non_macho_data_is_ignored_but_cannot_be_the_runtime():
    assert compatibility.check_macho(b"plain data", "data") == 0
    with pytest.raises(ValueError, match="no arm64"):
        compatibility.check_macho(b"MZ\0\0", "runtime", require_arm64=True)


@pytest.mark.parametrize("wide", [False, True])
def test_universal_binary_checks_arm64_slice(wide):
    intel = macho((15, 0, 0), cpu=0x01000007)
    arm = macho()
    record_size = 32 if wide else 20
    offset = 8 + record_size * 2
    records = b""
    for cpu, binary in [(0x01000007, intel), (compatibility.ARM64, arm)]:
        values = (cpu, 0, offset, len(binary), 0)
        if wide:
            values += (0,)
        records += struct.pack(">IIQQII" if wide else ">IIIII", *values)
        offset += len(binary)
    binary = struct.pack(">II", 0xCAFEBABF if wide else 0xCAFEBABE, 2) + records + intel + arm
    assert compatibility.check_macho(binary, "universal", require_arm64=True) == 1


@pytest.mark.parametrize("binary", [macho()[:20], macho()[:-1], struct.pack(">II", 0xCAFEBABE, 9)])
def test_malformed_macho_is_rejected(binary):
    with pytest.raises(ValueError, match="Truncated"):
        compatibility.check_macho(binary, "broken")


@pytest.mark.parametrize("name,typecode", [("libodbc.2.dylib", "b"), ("tools/uv", "x"), ("tools/ruff", "x")])
def test_embedded_carchive_library_and_tools_are_checked(tmp_path, monkeypatch, name, typecode):
    runtime = tmp_path / "datapyn-runtime"
    runtime.write_bytes(macho())
    archive = SimpleNamespace(
        toc={name: (0, 0, 0, 0, typecode)},
        extract=lambda name: macho((15, 0, 0)),
    )
    import PyInstaller.archive.readers

    monkeypatch.setattr(PyInstaller.archive.readers, "CArchiveReader", lambda path: archive)
    with pytest.raises(ValueError, match=r"datapyn-runtime!.*: requires macOS 15"):
        compatibility.check_runtime(runtime)


def test_bundle_checks_frameworks_and_main_binary(tmp_path):
    bundle = tmp_path / "DataPyn.app"
    binary = bundle / "Contents" / "MacOS" / "DataPyn"
    binary.parent.mkdir(parents=True)
    binary.write_bytes(macho())
    framework = bundle / "Contents" / "Frameworks" / "bad.dylib"
    framework.parent.mkdir()
    framework.write_bytes(macho((15, 0, 0)))
    with pytest.raises(ValueError, match=r"bad.dylib: requires macOS 15"):
        compatibility.check_bundle(bundle)


@pytest.mark.parametrize(
    "system,machine,actions,runner",
    [("win32", "AMD64", "true", "github-hosted"),
     ("darwin", "x86_64", "true", "github-hosted"),
     ("darwin", "arm64", "true", "self-hosted"),
     ("darwin", "arm64", "false", "github-hosted")],
)
def test_prerequisites_never_modify_user_or_wrong_architecture_hosts(monkeypatch, system, machine, actions, runner):
    monkeypatch.setattr(prerequisites.sys, "platform", system)
    monkeypatch.setattr(prerequisites.platform, "machine", lambda: machine)
    monkeypatch.setenv("GITHUB_ACTIONS", actions)
    monkeypatch.setenv("RUNNER_ENVIRONMENT", runner)
    monkeypatch.setattr(prerequisites.shutil, "which", lambda _: pytest.fail("brew must not be called"))
    with pytest.raises(RuntimeError, match="only modifies disposable"):
        prerequisites.prepare()


def test_bottle_checksum_must_match_before_installation(tmp_path):
    bottle = tmp_path / "library.bottle.tar.gz"
    bottle.write_bytes(b"wrong archive")
    with pytest.raises(RuntimeError, match="checksum mismatch"):
        prerequisites.verify_bottle(bottle, "0" * 64)
    prerequisites.verify_bottle(bottle, hashlib.sha256(b"wrong archive").hexdigest())


def test_runner_downloads_pinned_bottles_before_replacing_only_ci_dependencies(tmp_path, monkeypatch):
    calls = []
    bottles = {}
    monkeypatch.setattr(prerequisites, "require_disposable_runner", lambda: None)
    monkeypatch.setattr(prerequisites.shutil, "which", lambda _: "/opt/homebrew/bin/brew")
    monkeypatch.setattr(prerequisites, "check_file", lambda path, **kwargs: 1)
    monkeypatch.setenv("RUNNER_TEMP", str(tmp_path))

    def download(formula, directory):
        bottles[formula] = str(directory / f"{formula}.bottle.tar.gz")
        calls.append(["download", formula])
        return Path(bottles[formula])

    monkeypatch.setattr(prerequisites, "download_bottle", download)

    def run(command, **kwargs):
        args = command[1:]
        calls.append(args)
        assert kwargs["check"] is True
        assert kwargs["env"]["HOMEBREW_NO_AUTO_UPDATE"] == "1"
        assert kwargs["env"]["HOMEBREW_DEVELOPER"] == "1"
        if args == ["--version"]:
            output = "Homebrew 7"
        elif args == ["--prefix"]:
            output = "/opt/homebrew"
        elif args[0] == "info":
            output = json.dumps({"formulae": [{"name": name, "installed": [{"version": "new"}]} for name in prerequisites.BOTTLES]})
        else:
            output = ""
        if args[0] == "install":
            assert args[-1].startswith("./")
            assert kwargs["cwd"] == tmp_path / "datapyn-sonoma-bottles"
            assert (kwargs["cwd"] / args[-1]) in map(Path, bottles.values())
        return SimpleNamespace(stdout=output, stderr="")

    monkeypatch.setattr(prerequisites.subprocess, "run", run)
    prerequisites.prepare()
    assert calls[2:4] == [["download", "libtool"], ["download", "unixodbc"]]
    assert not any(command[0] in {"fetch", "--cache"} for command in calls)
    assert calls[-4:] == [
        ["uninstall", "--ignore-dependencies", "unixodbc"],
        ["uninstall", "--ignore-dependencies", "libtool"],
        ["install", "--force-bottle", "--no-ask", "./libtool.bottle.tar.gz"],
        ["install", "--force-bottle", "--no-ask", "./unixodbc.bottle.tar.gz"],
    ]


def test_download_uses_public_pinned_blob_and_checks_actual_bytes(tmp_path, monkeypatch):
    payload = b"public bottle fixture"
    digest = hashlib.sha256(payload).hexdigest()
    monkeypatch.setattr(prerequisites, "BOTTLES", {"libtool": ("2.6.2", digest)})
    requests = []

    def open_url(request, **kwargs):
        requests.append(request)
        assert kwargs["timeout"] == 30
        if isinstance(request, str):
            return io.BytesIO(b'{"token":"anonymous-public-pull"}')
        assert request.get_header("Authorization") == "Bearer anonymous-public-pull"
        return io.BytesIO(payload)

    monkeypatch.setattr(prerequisites, "urlopen", open_url)
    path = prerequisites.download_bottle("libtool", tmp_path)
    assert path.name == "libtool--2.6.2.arm64_sonoma.bottle.tar.gz"
    assert path.read_bytes() == payload
    assert requests[1].full_url == f"https://ghcr.io/v2/homebrew/core/libtool/blobs/sha256:{digest}"


def test_corrupted_download_cannot_proceed_to_installation(tmp_path, monkeypatch):
    monkeypatch.setattr(prerequisites, "urlopen", lambda request, **kwargs: io.BytesIO(
        b'{"token":"anonymous"}' if isinstance(request, str) else b"corrupted bottle"
    ))
    with pytest.raises(RuntimeError, match="checksum mismatch"):
        prerequisites.download_bottle("libtool", tmp_path)
