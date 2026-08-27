"""Select test modules for a CI matrix shard (no pytest-xdist — Qt/WebEngine safe)."""

from __future__ import annotations

import argparse
from pathlib import Path

# Keep in sync with scripts/ci_pytest.sh / .github/workflows/tests.yml
CI_IGNORED_MODULES = frozenset(
    {
        "test_visual_manual.py",
        "test_gui.py",
        "test_file_operations.py",
        "test_usability.py",
        "test_ui_integration.py",
        "test_monaco_editor.py",
        "test_shortcuts.py",
        "test_session_panels_integration.py",
        "test_file_management_feedback.py",
        "test_export_script.py",
        "test_jupyter_import.py",
        "test_context_menu.py",
        "test_package_manager.py",
        "test_new_features.py",
        "test_block_editor.py",
        "test_block_connection.py",
        "test_block_database.py",
        "test_block_namespace.py",
        "test_new_tab_connection.py",
        "test_session_restoration.py",
        "test_python_output_e2e.py",
        # Live ACP CLIs need local auth; never run on GitHub Actions.
        "test_pynia_acp_live.py",
    }
)


def collect_ci_test_files(tests_dir: Path) -> list[Path]:
    files = sorted(tests_dir.glob("test_*.py"))
    return [p for p in files if p.name not in CI_IGNORED_MODULES]


def shard_files(files: list[Path], shard: int, shards: int) -> list[Path]:
    if shard < 0 or shard >= shards:
        raise ValueError(f"shard must be in [0, {shards - 1}], got {shard}")
    return [path for index, path in enumerate(files) if index % shards == shard]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("shard", type=int, help="0-based shard index")
    parser.add_argument("shards", type=int, help="total shard count")
    parser.add_argument(
        "--tests-dir",
        type=Path,
        default=Path("tests"),
        help="tests directory (default: tests)",
    )
    args = parser.parse_args()
    if args.shards < 1:
        raise SystemExit("shards must be >= 1")

    picked = shard_files(collect_ci_test_files(args.tests_dir), args.shard, args.shards)
    if not picked:
        raise SystemExit(f"shard {args.shard}/{args.shards} has no test files")

    # One path per line so ci_pytest.sh mapfile splits into separate pytest args.
    print("\n".join(str(p) for p in picked))


if __name__ == "__main__":
    main()
