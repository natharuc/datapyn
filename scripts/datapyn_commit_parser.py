"""DataPyn commit parser for python-semantic-release.

Extends the conventional parser so CI releases match how this repo actually commits:
- All standard Conventional Commit types are mapped to semver bumps.
- GitHub merge commits parse the PR title/body (not ignored).
- Imperative free-form subjects (e.g. "Add Summarize panel") map to a bump level.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, ClassVar, Tuple

from semantic_release.commit_parser.conventional.options import (
    ConventionalCommitParserOptions,
)
from semantic_release.commit_parser.conventional.parser import ConventionalCommitParser
from semantic_release.commit_parser.token import ParseResult, ParsedCommit
from semantic_release.commit_parser.util import force_str
from semantic_release.enums import LevelBump

if TYPE_CHECKING:
    from git.objects.commit import Commit


@dataclass
class DatapynCommitParserOptions(ConventionalCommitParserOptions):
    """Parser options tuned for DataPyn release policy."""

    minor_tags: Tuple[str, ...] = ("feat",)
    patch_tags: Tuple[str, ...] = ("fix", "perf", "refactor", "revert", "build")
    other_allowed_tags: Tuple[str, ...] = ("chore", "ci", "docs", "style", "test")
    ignore_merge_commits: bool = False
    parse_squash_commits: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "allowed_tags",
            (*self.minor_tags, *self.patch_tags, *self.other_allowed_tags),
        )
        super().__post_init__()


# Imperative subjects common in this repo when agents skip the type: prefix.
_MINOR_SUBJECT = re.compile(
    r"^(?:add|implement|introduce|support|enable)\b",
    re.IGNORECASE,
)
_PATCH_SUBJECT = re.compile(
    r"^(?:fix|improve|make|update|remove|handle|optimize|refactor|restore|prevent|"
    r"avoid|allow|merge|delete|correct|resolve|adjust|reduce|increase|speed|async|"
    r"defer|stabilize|harden|guard|summarize)\b",
    re.IGNORECASE,
)
_MERGE_PREFIX = re.compile(r"^Merge pull request #\d+ from .+$", re.IGNORECASE | re.MULTILINE)


class DatapynCommitParser(ConventionalCommitParser):
    """Conventional parser plus merge-body and imperative-subject fallbacks."""

    parser_options = DatapynCommitParserOptions

    _HEURISTIC_MINOR: ClassVar[LevelBump] = LevelBump.MINOR
    _HEURISTIC_PATCH: ClassVar[LevelBump] = LevelBump.PATCH

    @classmethod
    def get_default_options(cls) -> DatapynCommitParserOptions:
        return DatapynCommitParserOptions()

    def __init__(self, options: DatapynCommitParserOptions | None = None) -> None:
        super().__init__(options or DatapynCommitParserOptions())

    def parse_commit(self, commit: "Commit") -> ParseResult:
        result = super().parse_commit(commit)
        if isinstance(result, ParsedCommit):
            return result

        message = force_str(commit.message).strip()
        for candidate in self._candidate_messages(message):
            if parsed := self.parse_message(candidate):
                return ParsedCommit.from_parsed_message_result(commit, parsed)

            heuristic = self._heuristic_bump(candidate)
            if heuristic is not LevelBump.NO_RELEASE:
                return ParsedCommit(
                    bump=heuristic,
                    type="heuristic",
                    scope="",
                    descriptions=[candidate],
                    breaking_descriptions=[],
                    commit=commit,
                )

        return result

    def _candidate_messages(self, message: str) -> list[str]:
        lines = [line.strip() for line in message.splitlines() if line.strip()]
        candidates: list[str] = []

        if lines:
            candidates.append(lines[0])

        if len(lines) > 1 and _MERGE_PREFIX.match(lines[0]):
            candidates.extend(lines[1:])

        # De-duplicate while preserving order.
        seen: set[str] = set()
        ordered: list[str] = []
        for item in candidates:
            if item not in seen:
                seen.add(item)
                ordered.append(item)
        return ordered

    @classmethod
    def _heuristic_bump(cls, subject: str) -> LevelBump:
        if _MINOR_SUBJECT.match(subject):
            return cls._HEURISTIC_MINOR
        if _PATCH_SUBJECT.match(subject):
            return cls._HEURISTIC_PATCH
        return LevelBump.NO_RELEASE
