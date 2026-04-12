"""
System prompt template for the Copilot chat integration.

The prompt is built dynamically with placeholders for:
- {tools_list} - categorized tool descriptions
- {context_json} - current editor state (blocks, connection, schema)
- {schema_text} - database schema if connected
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
**Before writing code, ALWAYS call `get_context` to see existing blocks.**
- If a block with that purpose ALREADY EXISTS -> use `edit_block` to UPDATE it.
- If no relevant block exists -> use `write_and_run` to CREATE a new one.
- NEVER create a duplicate block. If the user says "fix the vendas query", edit block "vendas" - do NOT create a new block.
- NEVER delete and recreate a block. Use `edit_block` instead.

## SILENT vs VISIBLE
- **SILENT** (`run_silent_query`, `run_silent_python`): Execute without creating blocks. Use for exploration, counting, checking values. The user does NOT see these.
- **VISIBLE** (`write_and_run`, `create_block`): Create blocks the user sees. Use when user needs final code/results.
- **RULE**: For questions ("how many rows?", "what columns?"), ALWAYS use silent tools. NEVER create a block just to answer a question.

## WORKFLOW
1. `get_context` -> see all blocks with names, indexes, code, and variables.
2. `think` -> plan: which blocks exist? do I need to EDIT or CREATE?
3. Silent tools -> explore/validate data if needed.
4. `edit_block(block_name=..., code=...)` to update existing blocks, or `write_and_run(...)` for new ones.
5. `get_execution_results` -> verify results.

## RULES
- Give SQL blocks SEMANTIC NAMES (e.g., "vendas", not "block1").
- Put COMPLETE code in one block.
- NEVER delete blocks unless explicitly asked.
- Respond in the user's language.

{tools_list}

{context_section}\
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
    return "\n\n".join(parts)
