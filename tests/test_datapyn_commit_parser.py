"""Tests for the DataPyn semantic-release commit parser."""

from types import SimpleNamespace

import pytest

from scripts.datapyn_commit_parser import DatapynCommitParser


def _commit(message: str, *, parents=1):
    return SimpleNamespace(message=message, parents=[object()] * parents, hexsha="abc12345")


@pytest.fixture
def parser():
    return DatapynCommitParser()


class TestDatapynCommitParser:
    def test_conventional_feat_is_minor(self, parser):
        result = parser.parse_commit(_commit("feat(copilot): add image attachments"))
        assert result.bump.name == "MINOR"

    def test_conventional_fix_is_patch(self, parser):
        result = parser.parse_commit(_commit("fix(results): format epoch nanoseconds"))
        assert result.bump.name == "PATCH"

    def test_refactor_is_patch(self, parser):
        result = parser.parse_commit(_commit("refactor(ui): simplify tab switching"))
        assert result.bump.name == "PATCH"

    def test_ci_does_not_release(self, parser):
        result = parser.parse_commit(_commit("ci(release): fail when MSI is skipped"))
        assert result.bump.name == "NO_RELEASE"

    def test_imperative_add_is_minor(self, parser):
        result = parser.parse_commit(_commit("Add Summarize dock panel for grid selection"))
        assert result.bump.name == "MINOR"

    def test_imperative_improve_is_patch(self, parser):
        result = parser.parse_commit(
            _commit("Improve grid performance, Summarize UX, and async database switching.")
        )
        assert result.bump.name == "PATCH"

    def test_merge_commit_uses_pr_title(self, parser):
        message = (
            "Merge pull request #105 from natharuc/feat/summarize-panel\n\n"
            "Summarize panel and async Copilot/Monaco"
        )
        result = parser.parse_commit(_commit(message, parents=2))
        assert result.bump.name == "PATCH"

    def test_delete_file_is_patch(self, parser):
        result = parser.parse_commit(_commit("Delete .pytest_fullsuite_latest.txt"))
        assert result.bump.name == "PATCH"
