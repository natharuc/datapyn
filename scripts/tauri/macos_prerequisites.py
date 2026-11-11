"""Install macOS 14-compatible build libraries on disposable GitHub runners."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys

from macos_compatibility import check_file

BOTTLE_TAG = "arm64_sonoma"
# Pin both the ODBC manager and its native libltdl dependency. A bottle chosen
# for the macOS 15 runner would silently raise the distributed runtime minimum.
BOTTLES = {
    "libtool": ("2.6.2", "6d51bf4ccdbc2a0cb7c23d71edc885130c955193ce6f388ab77411f8ebd4305a"),
    "unixodbc": ("2.3.14", "39f022a55a502b3b1d46769705cc46c4aa9f9206b902558ed56cd47aab3d54d8"),
}


def require_disposable_runner() -> None:
    if not (
        sys.platform == "darwin"
        and platform.machine().lower() == "arm64"
        and os.environ.get("GITHUB_ACTIONS") == "true"
        and os.environ.get("RUNNER_ENVIRONMENT") == "github-hosted"
    ):
        raise RuntimeError("This helper only modifies disposable GitHub-hosted macOS arm64 runners")


def verify_bottle(path: Path, expected_sha256: str) -> None:
    if not path.is_file():
        raise RuntimeError(f"Homebrew did not cache the expected bottle: {path}")
    with path.open("rb") as handle:
        digest = hashlib.file_digest(handle, "sha256").hexdigest()
    if digest != expected_sha256:
        raise RuntimeError(f"Bottle checksum mismatch for {path.name}; update the reviewed Sonoma bottle pin")


def prepare() -> None:
    require_disposable_runner()
    brew = shutil.which("brew")
    if not brew:
        raise RuntimeError("Native arm64 Homebrew is required")
    env = {
        **os.environ,
        "HOMEBREW_NO_AUTO_UPDATE": "1",
        "HOMEBREW_NO_INSTALL_CLEANUP": "1",
        "HOMEBREW_NO_ANALYTICS": "1",
    }

    def run(*arguments: str) -> str:
        try:
            result = subprocess.run([brew, *arguments], check=True, text=True, capture_output=True, env=env)
        except subprocess.CalledProcessError as error:
            detail = "\n".join(part for part in (error.stdout, error.stderr) if part)
            raise RuntimeError(f"Homebrew {' '.join(arguments)} failed:\n{detail[-6000:]}") from error
        return result.stdout.strip()

    if run("--prefix") != "/opt/homebrew":
        raise RuntimeError("Expected the native GitHub runner Homebrew prefix /opt/homebrew")
    cached = {}
    for formula, (_, digest) in BOTTLES.items():
        run("fetch", "--force", f"--bottle-tag={BOTTLE_TAG}", formula)
        path = Path(run("--cache", f"--bottle-tag={BOTTLE_TAG}", formula))
        verify_bottle(path, digest)
        cached[formula] = path

    # Validate every download before replacing any preinstalled formula. This
    # uninstall is deliberately restricted to the two named CI dependencies.
    installed = json.loads(run("info", "--json=v2", *BOTTLES))["formulae"]
    existing = {formula["name"] for formula in installed if formula.get("installed")}
    for formula in reversed(BOTTLES):
        if formula in existing:
            run("uninstall", "--ignore-dependencies", formula)
    for formula in BOTTLES:
        run("install", "--force-bottle", str(cached[formula]))

    for library in (
        Path("/opt/homebrew/opt/libtool/lib/libltdl.7.dylib"),
        Path("/opt/homebrew/opt/unixodbc/lib/libodbc.2.dylib"),
        Path("/opt/homebrew/opt/unixodbc/lib/libodbcinst.2.dylib"),
    ):
        check_file(library, require_arm64=True)
    print("Verified Sonoma arm64 unixODBC/libltdl; Kerberos wheels use the macOS GSS/Heimdal frameworks")


if __name__ == "__main__":
    prepare()
