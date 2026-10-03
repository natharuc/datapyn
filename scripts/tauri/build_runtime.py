"""Build the native Python sidecar expected by Tauri externalBin."""
from __future__ import annotations

import argparse
import importlib.util
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]


def host_target() -> str:
    rustc = shutil.which("rustc")
    if rustc:
        output = subprocess.run([rustc, "-vV"], check=True, text=True, capture_output=True).stdout
        match = re.search(r"^host: (.+)$", output, re.MULTILINE)
        if match:
            return match.group(1).strip()
    machine = platform.machine().lower()
    architecture = {"amd64": "x86_64", "x86_64": "x86_64", "aarch64": "aarch64", "arm64": "aarch64"}.get(machine)
    systems = {"win32": "pc-windows-msvc", "darwin": "apple-darwin", "linux": "unknown-linux-gnu"}
    if not architecture or sys.platform not in systems:
        raise RuntimeError("Target não detectado. Instale Rust e execute em uma plataforma suportada.")
    return f"{architecture}-{systems[sys.platform]}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", help="Rust host triple; cross-compilation of the Python runtime is not supported")
    parser.add_argument("--smoke", action="store_true", help="Check SQL/Python, cancellation and fresh-session recovery in the frozen sidecar")
    args = parser.parse_args()
    native_target = host_target()
    target = args.target or native_target
    if target != native_target:
        parser.error(f"PyInstaller precisa de build nativo: host={native_target}, solicitado={target}.")
    if not (ROOT / "source/datapyn_runtime/__main__.py").is_file():
        parser.error("Runtime ausente em source/datapyn_runtime.")
    if importlib.util.find_spec("PyInstaller") is None:
        parser.error("PyInstaller ausente. Execute uv sync --dev ou use o Python da .venv.")

    output_root = ROOT / "build/tauri-runtime" / target
    env = os.environ.copy()
    env["MPLBACKEND"] = "Agg"
    env["PYTHONPATH"] = os.pathsep.join(filter(None, [str(ROOT / "source"), env.get("PYTHONPATH")]))
    command = [
        sys.executable, "-m", "PyInstaller", str(ROOT / "scripts/tauri/runtime.spec"),
        "--noconfirm", "--clean", "--distpath", str(output_root / "dist"), "--workpath", str(output_root / "work"),
    ]
    subprocess.run(command, cwd=ROOT, env=env, check=True)
    suffix = ".exe" if sys.platform == "win32" else ""
    built = output_root / "dist" / f"datapyn-runtime{suffix}"
    if args.smoke:
        subprocess.run([sys.executable, str(ROOT / "scripts/tauri/smoke_runtime.py"), "--executable", str(built)], cwd=ROOT, env=env, check=True)
    destination = ROOT / "desktop/src-tauri/binaries" / f"datapyn-runtime-{target}{suffix}"
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(built, destination)
    print(f"Sidecar: {destination}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (RuntimeError, subprocess.CalledProcessError) as error:
        print(f"Falha ao empacotar runtime: {error}", file=sys.stderr)
        raise SystemExit(1) from error
