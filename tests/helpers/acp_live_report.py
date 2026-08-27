"""Format the local ACP live-test report shown to the developer."""

from __future__ import annotations

from dataclasses import dataclass, field

from src.services.pynia.acp.agent import LIVE_TEST_COMMAND, FixStep, GrantResult


@dataclass
class LiveAgentOutcome:
    agent_id: str
    grant: GrantResult | None = None
    ping: str = ""
    error: str = ""
    extra_steps: list[FixStep] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return bool(self.grant and self.grant.ok and not self.error)


def format_live_report(outcomes: list[LiveAgentOutcome]) -> str:
    lines = ["=== Pynia ACP live report ==="]
    failed = False
    all_steps: list[FixStep] = []
    for item in outcomes:
        grant = item.grant
        if grant is None:
            failed = True
            lines.append(f"{item.agent_id:<8} FAIL  {item.error or 'no grant result'}")
            continue
        models = "hidden" if not grant.models else str(len(grant.models))
        reasoning = "hidden" if not grant.reasoning else str(len(grant.reasoning))
        ping = item.ping or "-"
        if item.ok:
            lines.append(
                f"{item.agent_id:<8} OK    models={models}  reasoning={reasoning}  ping={ping}"
            )
            continue
        failed = True
        status = grant.status if not grant.ok else "check_failed"
        detail = item.error or grant.detail or status
        lines.append(f"{item.agent_id:<8} FAIL  {status}  models={models}  reasoning={reasoning}  ping={ping}")
        if detail:
            lines.append(f"         {detail}")
        for step in list(grant.steps) + item.extra_steps:
            if step.command:
                all_steps.append(step)
                lines.append(f"         $ {step.command}")
                lines.append(f"           {step.description}")
            else:
                lines.append(f"         {step.description}")
    lines.append("")
    if failed:
        lines.append("When you finish the steps above, re-run:")
    else:
        lines.append("All agents passed. Re-run anytime with:")
    lines.append(f"  {LIVE_TEST_COMMAND}")
    return "\n".join(lines)
