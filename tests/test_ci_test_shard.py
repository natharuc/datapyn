"""CI test sharding helper."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.ci_test_shard import CI_IGNORED_MODULES, collect_ci_test_files, shard_files


def test_ci_shard_covers_all_modules_without_duplicates():
    tests_dir = __import__("pathlib").Path("tests")
    all_files = collect_ci_test_files(tests_dir)
    assert len(all_files) >= 50

    shards = 3
    seen: set[str] = set()
    for shard in range(shards):
        picked = shard_files(all_files, shard, shards)
        assert picked, f"shard {shard} must not be empty"
        for path in picked:
            assert path.name not in seen, path.name
            seen.add(path.name)

    assert seen == {p.name for p in all_files}


def test_ignored_modules_match_ci_script():
    assert "test_gui.py" in CI_IGNORED_MODULES
    assert "test_monaco_editor.py" in CI_IGNORED_MODULES
    assert "test_pynia_acp_live.py" in CI_IGNORED_MODULES


def test_shard_output_is_one_path_per_line():
    import subprocess

    repo = Path(__file__).resolve().parent.parent
    result = subprocess.run(
        ["uv", "run", "python", "scripts/ci_test_shard.py", "0", "3"],
        capture_output=True,
        text=True,
        check=True,
        cwd=repo,
    )
    lines = [line for line in result.stdout.strip().splitlines() if line]
    assert len(lines) >= 30
    for line in lines:
        assert " " not in line
        assert Path(line).name.startswith("test_")
