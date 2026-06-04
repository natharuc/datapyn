"""Automatic structure summaries for large DataPyn blocks (reduces inspect loops)."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

# Lines above this → attach structure outline to context (no extra tool call).
LARGE_BLOCK_LINE_THRESHOLD = 120


def block_structure_summary(code: str, language: str = "unknown") -> Dict[str, Any]:
    """Outline from static analysis (same heuristics as inspect_block structure)."""
    from src.services.copilot.mcp_tools import _infer_block_hints, _inspect_block_structure

    if not (code or "").strip():
        return {}
    structure = _inspect_block_structure(code, language)
    hints = _infer_block_hints(code, language)
    if hints:
        structure.setdefault("hints", hints)
    line_count = len(code.splitlines())
    structure["line_count"] = line_count
    if line_count > LARGE_BLOCK_LINE_THRESHOLD:
        structure["reading_hint"] = (
            f"Large block ({line_count} lines). Use focused_block_detail and structure below; "
            "at most one datapyn_inspect with around= if you need a specific section."
        )
    return structure


def enrich_focus_detail(focus: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Add structure outline to focused_block_detail so the model skips structure inspect."""
    if not focus:
        return focus
    out = dict(focus)
    code = out.get("code") or ""
    language = out.get("language") or "unknown"
    lines = int(out.get("lines") or len(code.splitlines()))
    if lines >= 80 or len(code) > 4000:
        summary = block_structure_summary(code, language)
        if summary:
            out["structure_summary"] = summary
    return out


def enrich_block_info_entry(
    *,
    name: str,
    language: str,
    code: str,
    lines: int,
    hints: List[str],
    focused: bool,
    index: int,
) -> Dict[str, Any]:
    """Add outline to block list entries for large blocks."""
    entry: Dict[str, Any] = {
        "index": index,
        "name": name,
        "language": language,
        "focused": focused,
        "lines": lines,
        "hints": hints,
        "code_preview": code[:160] + "..." if len(code) > 160 else code,
    }
    if lines >= LARGE_BLOCK_LINE_THRESHOLD and not focused:
        outline = block_structure_summary(code, language)
        if outline:
            entry["structure_summary"] = {
                k: outline[k]
                for k in (
                    "hints",
                    "html_element_ids",
                    "js_functions",
                    "python_functions",
                    "css_classes",
                    "reading_hint",
                    "line_count",
                )
                if k in outline
            }
    return entry
