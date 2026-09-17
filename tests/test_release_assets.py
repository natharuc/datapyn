"""Contract tests for versioned-only Windows, Linux docs, and macOS release assets."""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RELEASE_WORKFLOW = ROOT / ".github/workflows/release.yml"
INSTALLER_README = ROOT / "installer/README.md"

LINUX_VERSIONED = (
    "datapyn_{version}_amd64.deb",
    "datapyn-{version}-1.x86_64.rpm",
    "datapyn-{version}-1-x86_64.pkg.tar.zst",
    "DataPyn-{version}-x86_64.AppImage",
    "DataPyn-{version}-linux-x86_64.tar.gz",
)
LINUX_METADATA = ("DataPyn-linux-artifacts.json", "SHA256SUMS")
WINDOWS_RELEASE_ARTIFACTS = (
    "DataPyn-{version}-windows.zip",
    "DataPyn-Setup.exe",
)


def _strip_comments(text: str) -> str:
    lines = []
    for line in text.splitlines():
        if line.lstrip().startswith("#"):
            continue
        lines.append(line)
    return "\n".join(lines)


def _parse_scalar(raw: str) -> str:
    value = raw.strip()
    if (value.startswith("'") and value.endswith("'")) or (
        value.startswith('"') and value.endswith('"')
    ):
        return value[1:-1]
    return value


def load_workflow_yaml(path: Path) -> dict:
    """Parse a GitHub Actions workflow YAML document into mappings and sequences."""

    return _parse_yaml_mapping(_strip_comments(path.read_text(encoding="utf-8")).splitlines())


def _parse_yaml_mapping(lines: list[str], indent: int = 0) -> dict:
    result: dict[str, object] = {}
    index = 0
    while index < len(lines):
        line = lines[index]
        if not line.strip():
            index += 1
            continue
        current = len(line) - len(line.lstrip(" "))
        if current < indent:
            break
        if current > indent:
            raise AssertionError(f"unexpected indent {current} (expected {indent}): {line!r}")
        stripped = line.strip()
        if stripped.startswith("- "):
            raise AssertionError(f"sequence item where mapping expected: {line!r}")
        key, sep, rest = stripped.partition(":")
        if not sep:
            raise AssertionError(f"mapping line missing colon: {line!r}")
        key = key.strip()
        rest = rest.strip()
        if rest == "|":
            block, index = _parse_block_scalar(lines, index + 1, indent + 2)
            result[key] = block
            continue
        if rest:
            result[key] = _parse_scalar(rest)
            index += 1
            continue
        next_index = _next_content(lines, index + 1)
        if next_index is None:
            result[key] = {}
            index += 1
            continue
        next_line = lines[next_index]
        next_indent = len(next_line) - len(next_line.lstrip(" "))
        if next_indent <= indent:
            result[key] = {}
            index += 1
            continue
        if next_line.lstrip().startswith("- "):
            value, index = _parse_yaml_sequence(lines, next_indent, next_index)
        else:
            value = _parse_yaml_mapping(lines[next_index:], next_indent)
            consumed = _consumed_mapping_lines(lines, next_index, next_indent)
            index = next_index + consumed
        result[key] = value
    return result


def _consumed_mapping_lines(lines: list[str], start: int, indent: int) -> int:
    used = 0
    index = start
    while index < len(lines):
        line = lines[index]
        if not line.strip():
            used += 1
            index += 1
            continue
        current = len(line) - len(line.lstrip(" "))
        if current < indent:
            break
        used += 1
        index += 1
    return used


def _parse_yaml_sequence(lines: list[str], indent: int, start: int) -> tuple[list[object], int]:
    items: list[object] = []
    index = start
    while index < len(lines):
        line = lines[index]
        if not line.strip():
            index += 1
            continue
        current = len(line) - len(line.lstrip(" "))
        if current < indent:
            break
        stripped = line.strip()
        if not stripped.startswith("- "):
            break
        item_body = stripped[2:]
        item_indent = current + 2
        if ": " in item_body or item_body.endswith(":"):
            nested_lines = [" " * item_indent + item_body]
            index += 1
            while index < len(lines):
                follow = lines[index]
                if not follow.strip():
                    nested_lines.append(follow)
                    index += 1
                    continue
                follow_indent = len(follow) - len(follow.lstrip(" "))
                if follow_indent < item_indent:
                    break
                nested_lines.append(follow)
                index += 1
            items.append(_parse_yaml_mapping(nested_lines, item_indent))
            continue
        items.append(_parse_scalar(item_body))
        index += 1
    return items, index


def _parse_block_scalar(lines: list[str], start: int, indent: int) -> tuple[str, int]:
    collected: list[str] = []
    index = start
    while index < len(lines):
        line = lines[index]
        if not line.strip():
            collected.append("")
            index += 1
            continue
        current = len(line) - len(line.lstrip(" "))
        if current < indent:
            break
        collected.append(line[indent:])
        index += 1
    while collected and collected[-1] == "":
        collected.pop()
    return "\n".join(collected), index


def _next_content(lines: list[str], start: int) -> int | None:
    for index in range(start, len(lines)):
        if lines[index].strip():
            return index
    return None


def _files_list(files_value: str) -> list[str]:
    return [line.strip() for line in files_value.splitlines() if line.strip()]


def test_windows_release_uploads_single_setup() -> None:
    workflow = load_workflow_yaml(RELEASE_WORKFLOW)
    job = workflow["jobs"]["build-windows-release"]
    release_step = next(
        step
        for step in job["steps"]
        if str(step.get("uses", "")).startswith("softprops/action-gh-release")
    )
    assert _files_list(release_step["with"]["files"]) == [
        "DataPyn-${{ needs.release.outputs.version }}-windows.zip",
        "DataPyn-Setup.exe",
    ]
    for step in job["steps"]:
        assert "DataPyn-Setup-" not in str(step)


def test_installer_readme_lists_versioned_assets_only() -> None:
    text = INSTALLER_README.read_text(encoding="utf-8")
    artifacts_section = text[text.index("## Release artifacts") :]
    next_heading = artifacts_section.find("\n## ", 1)
    if next_heading != -1:
        artifacts_section = artifacts_section[:next_heading]

    windows_section, linux_and_macos = artifacts_section.split("Linux (amd64, built on Ubuntu 22.04):")
    linux_section, _ = linux_and_macos.split("macOS (Apple Silicon, unsigned):")
    assert set(re.findall(r"`([^`]+)`", windows_section)) == set(WINDOWS_RELEASE_ARTIFACTS)
    assert set(re.findall(r"`([^`]+)`", linux_section)) == {
        *LINUX_VERSIONED,
        *LINUX_METADATA,
    }


def test_macos_dmg_package_writes_versioned_name_only(tmp_path: Path) -> None:
    tree = tmp_path / "tree"
    script_dir = tree / "scripts" / "macos"
    script_dir.mkdir(parents=True)
    script = script_dir / "package_dmg.sh"
    script.write_text(
        (ROOT / "scripts/macos/package_dmg.sh").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    script.chmod(0o755)
    app = tree / "dist" / "DataPyn.app"
    app.mkdir(parents=True)
    (app / "Contents").mkdir()
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    hdiutil = fake_bin / "hdiutil"
    hdiutil.write_text(
        "#!/usr/bin/env bash\nprintf 'stub-dmg\\n' > \"${!#}\"\n",
        encoding="utf-8",
    )
    hdiutil.chmod(0o755)

    result = subprocess.run(
        ["bash", str(script), "1.57.0"],
        cwd=tree,
        env={**os.environ, "PATH": f"{fake_bin}:{os.environ.get('PATH', os.defpath)}"},
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert (tree / "DataPyn-1.57.0-macos-arm64.dmg").is_file()
    assert not (tree / "DataPyn-macos-arm64.dmg").exists()


def test_macos_release_uploads_versioned_dmg_only() -> None:
    workflow = load_workflow_yaml(RELEASE_WORKFLOW)
    job = workflow["jobs"]["build-macos-release"]
    release_step = next(
        step
        for step in job["steps"]
        if str(step.get("uses", "")).startswith("softprops/action-gh-release")
    )
    assert _files_list(release_step["with"]["files"]) == [
        "DataPyn-${{ needs.release.outputs.version }}-macos-arm64.dmg",
    ]


def test_docs_name_versioned_dmg_only() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    installer = INSTALLER_README.read_text(encoding="utf-8")
    assert "DataPyn-VERSION-macos-arm64.dmg" in readme
    assert "DataPyn-{version}-macos-arm64.dmg" in installer
    assert "DataPyn-macos-arm64.dmg" not in readme
    assert "DataPyn-macos-arm64.dmg" not in installer
