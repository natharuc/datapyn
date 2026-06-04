"""Build autocomplete / LSP context from DataPyn in-memory session state."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from src.editors.code_block import CodeBlock


@dataclass
class SessionPythonContext:
    """Shared Python session context for Monaco + Copilot LSP."""

    global_imports: str
    blocks_code_context: str
    namespace: Dict[str, Any]


def _block_name(block: "CodeBlock") -> str:
    if hasattr(block, "get_block_name"):
        return (block.get_block_name() or "").strip()
    return ""


def collect_global_imports(blocks: List["CodeBlock"]) -> str:
    """Import lines from every Python block in the tab."""
    lines: List[str] = []
    for block in blocks:
        if block.get_language() != "python":
            continue
        code = block.get_code() if hasattr(block, "get_code") else ""
        for line in code.splitlines():
            stripped = line.strip()
            if stripped.startswith("import ") or stripped.startswith("from "):
                lines.append(stripped)
    return "\n".join(dict.fromkeys(lines))


def collect_blocks_code_context(
    blocks: List["CodeBlock"],
    *,
    current_block: Optional["CodeBlock"] = None,
    max_other_block_chars: int = 2500,
) -> str:
    """Summaries of other blocks: SQL DataFrames + Python block sources."""
    parts: List[str] = []
    for block in blocks:
        if block is current_block:
            continue
        lang = block.get_language()
        name = _block_name(block) or "block"
        code = (block.get_code() if hasattr(block, "get_code") else "").strip()
        if not code:
            continue
        if lang == "sql":
            parts.append(
                f"# Block '{name}' (SQL) creates DataFrame `{name}`:\n"
                f"# {code[:400]}"
            )
        elif lang == "python":
            snippet = code if len(code) <= max_other_block_chars else code[:max_other_block_chars] + "\n# ..."
            parts.append(f"# --- block '{name}' (python) ---\n{snippet}")
    return "\n\n".join(parts)


def collect_session_python_context(
    blocks: List["CodeBlock"],
    namespace: Dict[str, Any],
    *,
    current_block: Optional["CodeBlock"] = None,
) -> SessionPythonContext:
    return SessionPythonContext(
        global_imports=collect_global_imports(blocks),
        blocks_code_context=collect_blocks_code_context(blocks, current_block=current_block),
        namespace=namespace or {},
    )


def _namespace_preamble(namespace: Dict[str, Any]) -> str:
    if not namespace:
        return ""
    try:
        from src.services.jedi_completer import _build_namespace_header

        return _build_namespace_header(namespace)
    except Exception:
        return ""


def build_python_lsp_preamble(
    *,
    global_imports: str = "",
    namespace: Optional[Dict[str, Any]] = None,
    blocks_code_context: str = "",
) -> tuple[str, int]:
    """Preamble prepended to the block body for Copilot LSP (not shown in Monaco).

    Returns (preamble_text, line_offset) where line_offset is the 0-based line
    index of the first line of the editable block in the combined document.
    """
    sections: List[str] = ["# === DataPyn session context (not executed) ==="]

    if global_imports:
        sections.append(global_imports.strip())

    ns_block = _namespace_preamble(namespace or {})
    if ns_block.strip():
        sections.append(ns_block.strip())

    if blocks_code_context.strip():
        sections.append(blocks_code_context.strip())

    sections.append("# === current block ===")
    preamble = "\n\n".join(sections)
    if preamble and not preamble.endswith("\n"):
        preamble += "\n"
    line_offset = len(preamble.splitlines()) if preamble else 0
    return preamble, line_offset


def build_sql_lsp_preamble(database_context: str = "") -> tuple[str, int]:
    """Schema text as SQL comments for Copilot LSP."""
    if not database_context.strip():
        return "", 0
    lines = ["-- === DataPyn schema context ==="]
    for line in database_context.strip().splitlines():
        lines.append(f"-- {line}")
    lines.append("-- === current block ===")
    preamble = "\n".join(lines) + "\n"
    return preamble, len(preamble.splitlines())


def build_sibling_block_completions(
    blocks: List["CodeBlock"],
    current_block: Optional["CodeBlock"] = None,
    *,
    target_language: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Completion items that insert a full sibling block (multiline snippet)."""
    items: List[Dict[str, Any]] = []
    for block in blocks:
        if block is current_block:
            continue
        lang = block.get_language()
        if target_language and lang != target_language:
            continue
        code = (block.get_code() if hasattr(block, "get_code") else "").strip()
        if not code:
            continue
        name = _block_name(block) or "block"
        lines = code.count("\n") + 1
        first_line = code.splitlines()[0][:72]
        items.append(
            {
                "label": f"block: {name}",
                "kind": "snippet",
                "insertText": code if code.endswith("\n") else code + "\n",
                "detail": f"{lang} · {lines} lines · {first_line}",
                "category": "block",
                "blockName": name,
                "language": lang,
                "filterText": name,
            }
        )
    return items


def build_lsp_preamble_for_block(
    language: str,
    *,
    global_imports: str = "",
    namespace: Optional[Dict[str, Any]] = None,
    blocks_code_context: str = "",
    database_context: str = "",
) -> tuple[str, int]:
    if language == "sql":
        return build_sql_lsp_preamble(database_context)
    if language == "python":
        return build_python_lsp_preamble(
            global_imports=global_imports,
            namespace=namespace,
            blocks_code_context=blocks_code_context,
        )
    return "", 0
