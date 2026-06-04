"""
Legacy import path — Pynia owns agent prompts.

Prefer: src.services.pynia.system_prompt
"""

from src.services.pynia.system_prompt import (  # noqa: F401
    build_context_section,
    build_request_prompt,
    build_system_prompt,
)

# Backward-compatible alias
SYSTEM_PROMPT_TEMPLATE = "{tools_list}"


def build_tools_list(tools: list) -> str:
    """Build categorized tool list (only when embedding catalog in prompt)."""
    categories = {
        "READ": ["datapyn_snapshot", "datapyn_inspect"],
        "EXECUTE": ["datapyn_query", "datapyn_run"],
        "EDIT": ["datapyn_edit", "datapyn_blocks"],
        "DATA": ["datapyn_database"],
        "CHARTS": ["datapyn_chart"],
        "META": ["datapyn_notify"],
    }
    tool_map = {t["name"]: t for t in tools}
    lines = ["## AVAILABLE TOOLS"]
    for category, tool_names in categories.items():
        lines.append(f"\n### {category}")
        for name in tool_names:
            schema = tool_map.get(name)
            if schema:
                desc = schema.get("description", "")
                if len(desc) > 100:
                    desc = desc[:97] + "..."
                lines.append(f"- **{name}**: {desc}")
    lines.append(f"\nTotal: {len(tools)} tools.")
    return "\n".join(lines)
