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
from urllib.request import Request, urlopen

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


def download_bottle(formula: str, directory: Path) -> Path:
    version, digest = BOTTLES[formula]
    path = directory / f"{formula}--{version}.{BOTTLE_TAG}.bottle.tar.gz"
    # These are public Homebrew artifacts. Obtain an anonymous pull grant;
    # never use the repository's GitHub token or depend on the latest formula.
    token_url = f"https://ghcr.io/token?service=ghcr.io&scope=repository:homebrew/core/{formula}:pull"
    with urlopen(token_url, timeout=30) as response:
        token = json.load(response)["token"]
    request = Request(
        f"https://ghcr.io/v2/homebrew/core/{formula}/blobs/sha256:{digest}",
        headers={"Authorization": f"Bearer {token}"},
    )
    with urlopen(request, timeout=30) as response, path.open("wb") as destination:
        shutil.copyfileobj(response, destination)
    verify_bottle(path, digest)
    print(f"Downloaded and verified {formula} {version} ({BOTTLE_TAG})")
    return path


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

    def run(*arguments: str, cwd: Path | None = None) -> str:
        try:
            result = subprocess.run([brew, *arguments], check=True, text=True, capture_output=True, env=env, cwd=cwd)
        except subprocess.CalledProcessError as error:
            detail = "\n".join(part for part in (error.stdout, error.stderr) if part)
            raise RuntimeError(f"Homebrew {' '.join(arguments)} failed:\n{detail[-6000:]}") from error
        if arguments[0] in {"install", "uninstall"}:
            detail = "\n".join(part for part in (result.stdout, result.stderr) if part)
            print(f"Homebrew {' '.join(arguments)}:\n{detail[-6000:]}")
        return result.stdout.strip()

    print(run("--version"))
    if run("--prefix") != "/opt/homebrew":
        raise RuntimeError("Expected the native GitHub runner Homebrew prefix /opt/homebrew")
    runner_temp = Path(os.environ.get("RUNNER_TEMP", ""))
    if not runner_temp.is_absolute() or not runner_temp.is_dir():
        raise RuntimeError("RUNNER_TEMP must name the disposable runner's existing absolute temporary directory")
    bottle_directory = runner_temp / "datapyn-sonoma-bottles"
    bottle_directory.mkdir(exist_ok=True)
    cached = {formula: download_bottle(formula, bottle_directory) for formula in BOTTLES}

    # Validate every download before replacing any preinstalled formula. This
    # uninstall is deliberately restricted to the two named CI dependencies.
    installed = json.loads(run("info", "--json=v2", *BOTTLES))["formulae"]
    existing = {formula["name"] for formula in installed if formula.get("installed")}
    for formula in reversed(BOTTLES):
        if formula in existing:
            run("uninstall", "--ignore-dependencies", formula)
    for formula in BOTTLES:
        # Homebrew's tap preflight interprets an absolute /Users/... path as
        # a tap before selecting the bottle loader. Explicit ./ paths bypass
        # tap parsing while preserving its supported local-bottle handling.
        run("install", "--force-bottle", "--no-ask", f"./{cached[formula].name}", cwd=bottle_directory)

    for library in (
        Path("/opt/homebrew/opt/libtool/lib/libltdl.7.dylib"),
        Path("/opt/homebrew/opt/unixodbc/lib/libodbc.2.dylib"),
        Path("/opt/homebrew/opt/unixodbc/lib/libodbcinst.2.dylib"),
    ):
        check_file(library, require_arm64=True)
    print("Verified Sonoma arm64 unixODBC/libltdl; Kerberos wheels use the macOS GSS/Heimdal frameworks")


if __name__ == "__main__":
    prepare()
