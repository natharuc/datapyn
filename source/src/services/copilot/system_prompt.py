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
        "OBSERVE": [
            "get_context", "list_blocks", "inspect_block", "get_block_code",
            "resolve_reference", "get_tab_context", "get_block_result",
        ],
        "SILENT": ["run_silent_query", "run_silent_python"],
        "VISIBLE": ["write_and_run", "create_block", "execute_block"],
        "EDIT": ["edit_block", "edit_block_lines", "replace_selection"],
        "DATABASE": ["read_schema", "list_tables", "sample_data", "connect_database"],
        "CHARTS": ["list_visualizations", "create_visualization", "edit_visualization"],
        "META": ["think", "notify_user", "create_tab"],
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
