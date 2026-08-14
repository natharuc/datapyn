"""Prompt helpers for ACP ghost-text autocomplete."""

from __future__ import annotations

from typing import Any, Dict, Optional

SYSTEM_PROMPT = (
    "You are Pynia, an inline code-completion engine inside the DataPyn IDE. "
    "Continue the code at <CURSOR>.\n"
    "- Output ONLY the raw text to insert at <CURSOR> — it MAY span multiple lines.\n"
    "- No markdown, no code fences, no comments explaining, no restating existing code.\n"
    "- Match the surrounding style/indentation and the given language.\n"
    "- Use the provided schema/variables when relevant. If nothing sensible fits, output nothing.\n"
    "- For Python DataFrames, use ONLY column names listed in Context — never invent columns."
)


def build_inline_prompt(
    *,
    language: str,
    prefix: str,
    suffix: str,
    context: str = "",
) -> str:
    """Build a fill-in-the-middle completion prompt for an ACP agent."""
    prefix_trunc = prefix[-2000:] if len(prefix) > 2000 else prefix
    suffix_trunc = suffix[:500] if len(suffix) > 500 else suffix
    ctx = ""
    if context:
        ctx_block = context[:2000] if len(context) > 2000 else context
        label = "Database schema" if language == "sql" else "Context"
        ctx = f"{label}:\n{ctx_block}\n\n"
    return (
        f"{ctx}"
        f"Complete the following {language} code at <CURSOR>. "
        f"Output only the text to insert (may be multiple lines):\n\n"
        f"```{language}\n{prefix_trunc}<CURSOR>{suffix_trunc}\n```"
    )


def build_inline_context(
    language: str,
    *,
    database_context: str = "",
    python_namespace_objects: Optional[Dict[str, Any]] = None,
    python_namespace: Optional[Dict[str, str]] = None,
    blocks_code_context: str = "",
) -> str:
    """Build session context for inline completion (run off the UI thread)."""
    if language == "sql":
        return database_context or ""
    if language == "python":
        from src.editors.completion_context import describe_namespace_dataframes

        parts: list[str] = []
        ns_objects = python_namespace_objects or {}
        ns_types = python_namespace or {}
        df_schema = describe_namespace_dataframes(ns_objects)
        if df_schema.strip():
            parts.append(df_schema.strip())
        elif ns_types:
            rows = [
                f"  {name}: {type_name}"
                for name, type_name in sorted(ns_types.items())
            ]
            parts.append("Available variables:\n" + "\n".join(rows))
        if blocks_code_context.strip():
            parts.append("Other blocks in this tab:\n" + blocks_code_context.strip())
        return "\n\n".join(parts)
    return ""


def clean_completion_text(text: str, prefix: str, suffix: str) -> str:
    """Normalize model output to ghost-text insertion."""
    if not text:
        return ""
    cleaned = text.strip()
    if cleaned.startswith("```"):
        lines = cleaned.split("\n")
        if len(lines) >= 2 and lines[-1].strip().startswith("```"):
            cleaned = "\n".join(lines[1:-1])
        elif len(lines) >= 2:
            cleaned = "\n".join(lines[1:])
    cleaned = cleaned.replace("<CURSOR>", "").strip()
    if prefix and cleaned.startswith(prefix) and suffix and cleaned.endswith(suffix):
        cleaned = cleaned[len(prefix) : len(cleaned) - len(suffix)]
    if prefix and cleaned.startswith(prefix[-80:]):
        cleaned = cleaned[len(prefix[-80:]) :]
    while cleaned.endswith("\n"):
        cleaned = cleaned[:-1]
    return cleaned
