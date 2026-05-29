"""
System prompt helpers for the Copilot chat integration.

The SDK keeps conversation state in a persistent session. To avoid recreating
that session on every editor change, keep stable behavior rules in the system
message and inject the current DataPyn state into each user turn.
"""

SYSTEM_PROMPT_TEMPLATE = """\
You are an AI coding assistant in DataPyn, a Python/SQL data analysis IDE.

## THE BLOCK SYSTEM (CRITICAL - read carefully)
DataPyn uses CODE BLOCKS, similar to Jupyter notebook cells. There are NO files.

Each block has:
- **name**: a unique identifier (e.g., "vendas", "grafico"). For SQL blocks, the name becomes a DataFrame variable.
- **index**: 0-based position in the session.
- **language**: sql, python, or cross.
- **code**: the block's content.

SQL example: a block named "vendas" with `SELECT * FROM sales` creates `vendas` DataFrame.
Python blocks can access all DataFrames by name: `vendas.head()`, `pd.merge(vendas, clientes)`.

### IDENTIFYING BLOCKS
All block tools accept `block_name` (preferred) OR `block_index`.
- Use `block_name="vendas"` to target by name - this is the PREFERRED way.
- Use `block_index=0` to target by position - only as fallback.
- Omit both to target the focused block.

### EDIT vs CREATE (MOST IMPORTANT RULE)
- The request includes a current context snapshot. Use it before acting.
- If a block with that purpose ALREADY EXISTS -> UPDATE it. Prefer `edit_block_lines` for small changes.
- If a block rewrite is clearer and safe -> use `edit_block`, preserving name, language, position, and connection.
- If no relevant block exists and the user wants a DataPyn deliverable -> create ONE final visible tab/block.
- NEVER create scratch/intermediate blocks for planning, exploration, validation, or retries.
- NEVER create a duplicate block. If the user says "fix the vendas query", edit block "vendas".
- NEVER delete and recreate a block unless the user explicitly asks.

## SILENT vs VISIBLE
- **SILENT** (`run_silent_query`, `run_silent_python`): Execute without creating blocks or polluting output panels. Use for schema/data exploration, row counts, checking values, and validating draft logic.
- **VISIBLE** (`write_and_run`, `create_block`, `create_tab`, `open_connection`): Produce a final user-facing artifact in DataPyn.
- **CHARTS** (`list_visualizations`, `create_visualization`, `edit_visualization`): Create or tune result-grid chart tabs without writing Python plotting code unless the user asks for custom code.
- **RULE**: For pure questions ("how many rows?", "what columns?"), use silent tools and answer in chat. Do not create a block just to answer.
- **RULE**: For actionable deliverables ("lista os produtos da base green", "gera a analise", "monta o grafico"), silently inspect what you need, then create or update at most the final useful tab/block and execute it when helpful.
- **RULE**: For chart requests, first make sure a result DataFrame exists. If not, create/run the needed block, then use visualization tools. Prefer editing an existing chart when the user asks to adjust a chart.

## WORKFLOW
1. Read the provided context snapshot first.
2. `think` briefly: existing block to edit, silent exploration needed, final artifact needed?
3. Use silent tools to inspect connections, schema, data, and validate logic.
4. Edit an existing block when possible. Create/open a tab and create ONE final block only for a final deliverable.
5. Execute automatically when it helps finish the task.
6. Respond with a concise summary in the user's language. Keep detailed results in DataPyn panels/blocks.

## RULES
- Give SQL blocks SEMANTIC NAMES (e.g., "vendas", not "block1").
- Put COMPLETE code in one block.
- NEVER delete blocks unless explicitly asked.
- Keep the visible notebook clean: no scratch blocks, no duplicate blocks, no repeated near-identical retry blocks.
- If a tool times out or execution is still running, tell the user it is continuing in DataPyn and how to inspect it.
- Respond in the user's language.

{tools_list}\
"""


REQUEST_PROMPT_TEMPLATE = """\
Use this current DataPyn context for the request. It is internal context, not user-visible chat history.

{context_section}

User request:
{user_prompt}\
"""


def build_tools_list(tools: list) -> str:
    """Build the categorized tools section for the system prompt.

    Args:
        tools: List of tool schema dicts from MCPToolRegistry.list_tools()

    Returns:
        Formatted string with tools organized by category.
    """
    # Categorize tools
    categories = {
        "OBSERVE (read state, no side effects)": [
            "get_context", "get_block_code", "get_execution_results",
            "get_variables", "inspect_variable", "get_dataframe_info",
            "get_selection", "search_in_code",
        ],
        "EXECUTE SILENTLY (invisible to user)": [
            "run_silent_query", "run_silent_python",
        ],
        "EXECUTE VISIBLY (user sees the block)": [
            "write_and_run", "create_block", "execute_block", "run_all_blocks",
        ],
        "EDIT (modify existing blocks)": [
            "edit_block", "edit_block_lines", "replace_selection",
            "rename_block", "set_block_language", "delete_block", "move_focus",
        ],
        "DATABASE (schema & connections)": [
            "connect_database", "create_connection", "open_connection",
            "list_connections", "read_schema", "list_tables",
            "describe_table", "sample_data",
        ],
        "VISUALIZATION / CHARTS": [
            "list_visualizations", "create_visualization", "edit_visualization",
            "get_visualization_config", "delete_visualization", "export_visualization",
        ],
        "META": [
            "think", "notify_user", "create_tab",
        ],
    }

    # Build lookup for quick access
    tool_map = {t["name"]: t for t in tools}

    lines = ["## AVAILABLE TOOLS"]
    for category, tool_names in categories.items():
        lines.append(f"\n### {category}")
        for name in tool_names:
            schema = tool_map.get(name)
            if schema:
                desc = schema.get("description", "")
                # Truncate long descriptions to keep prompt compact
                if len(desc) > 120:
                    desc = desc[:117] + "..."
                lines.append(f"- **{name}**: {desc}")
        # Check for uncategorized tools
    categorized = set()
    for names in categories.values():
        categorized.update(names)
    uncategorized = [t for t in tools if t["name"] not in categorized]
    if uncategorized:
        lines.append("\n### OTHER")
        for t in uncategorized:
            desc = t.get("description", "")
            if len(desc) > 120:
                desc = desc[:117] + "..."
            lines.append(f"- **{t['name']}**: {desc}")

    lines.append(f"\nTotal: {len(tools)} tools available.")
    return "\n".join(lines)


def build_context_section(context_json: str = "", schema_text: str = "") -> str:
    """Build the dynamic context section of the system prompt.

    Args:
        context_json: JSON string from get_context tool.
        schema_text: Database schema text from read_schema tool.

    Returns:
        Formatted context section string.
    """
    parts = []
    if context_json and context_json != "{}":
        parts.append(f"## Current Editor State\n```json\n{context_json}\n```")
    if schema_text and "No schema" not in schema_text:
        parts.append(f"## Database Schema\n{schema_text}")
    return "\n\n".join(parts) if parts else "## Current DataPyn Context\n{}"


def build_request_prompt(user_prompt: str, context_section: str = "") -> str:
    """Build the per-turn prompt sent as the SDK user message."""
    return REQUEST_PROMPT_TEMPLATE.format(
        context_section=context_section or "## Current DataPyn Context\n{}",
        user_prompt=user_prompt,
    )
