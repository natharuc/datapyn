"""Types for Pynia explore subagents."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List


@dataclass
class ExploreTask:
    """One parallel explore subagent job."""

    task_id: str
    instruction: str
    context: str = ""
    max_tool_rounds: int = 2


@dataclass
class ExploreTaskResult:
    """Result returned to the main agent."""

    task_id: str
    summary: str
    ok: bool = True
    tool_trace: List[Dict[str, Any]] = field(default_factory=list)
