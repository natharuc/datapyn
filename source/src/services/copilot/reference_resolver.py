"""Resolve DataPyn chat references such as #tab1 and #block:query."""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple


REFERENCE_RE = re.compile(r"#(?P<kind>tab|block)(?::(?P<named>[^\s#]+)|(?P<index>\d+))?", re.IGNORECASE)


class ReferenceResolver:
    """Build autocomplete suggestions and safe context snapshots for chat refs."""

    def __init__(self, main_window: Any = None, pinned_session_id: Optional[str] = None):
        self._main_window = main_window
        self._pinned_session_id = pinned_session_id or ""

    def parse(self, text: str) -> List[Dict[str, Any]]:
        refs = []
        for match in REFERENCE_RE.finditer(text or ""):
            kind = match.group("kind").lower()
            index = match.group("index")
            named = match.group("named")
            refs.append({
                "reference": match.group(0),
                "type": kind,
                "index": max(int(index) - 1, 0) if index is not None else None,
                "name": named or "",
            })
        return refs

    def suggestions(self, query: str = "") -> List[Dict[str, Any]]:
        query = (query or "#").lower()
        suggestions: List[Dict[str, Any]] = []
        if query in ("#", "#t", "#ta") or query.startswith("#tab"):
            suggestions.extend(self._tab_suggestions())
        if query in ("#", "#b", "#bl") or query.startswith("#block"):
            suggestions.extend(self._block_suggestions())
        if len(query) > 1:
            needle = query[1:]
            suggestions = [s for s in suggestions if needle in s["insert_text"].lower() or needle in s["label"].lower()]
        return suggestions[:30]

    def resolve(self, reference: str) -> Dict[str, Any]:
        parsed = self.parse(reference)
        if not parsed:
            return {"ok": False, "reference": reference, "error": "Invalid reference."}
        target = parsed[0]
        if target["type"] == "tab":
            return self._resolve_tab(target)
        if target["type"] == "block":
            return self._resolve_block(target)
        return {"ok": False, "reference": reference, "error": "Unsupported reference type."}

    def resolve_many(self, references: List[str]) -> List[Dict[str, Any]]:
        return [self.resolve(ref) for ref in references]

    def context_snapshot(self) -> Dict[str, Any]:
        return {
            "tabs": self._tab_suggestions(include_code=False),
            "current_blocks": self._block_suggestions(include_code=True),
        }

    def _session_tabs(self):
        mw = self._main_window
        return getattr(mw, "session_tabs", None) if mw else None

    def _current_session_widget(self):
        mw = self._main_window
        if self._pinned_session_id and mw and hasattr(mw, "_session_widgets"):
            widget = mw._session_widgets.get(self._pinned_session_id)
            if widget:
                return widget
        tabs = self._session_tabs()
        if not tabs:
            return None
        index = tabs.currentIndex()
        return tabs.widget(index) if index >= 0 else None

    def _tab_count(self) -> int:
        tabs = self._session_tabs()
        try:
            return tabs.count() if tabs else 0
        except Exception:
            return 0

    def _tab_widget(self, index: int):
        tabs = self._session_tabs()
        try:
            return tabs.widget(index) if tabs and 0 <= index < tabs.count() else None
        except Exception:
            return None

    def _tab_title(self, index: int, widget: Any = None) -> str:
        tabs = self._session_tabs()
        title = ""
        try:
            title = tabs.tabText(index) if tabs else ""
        except Exception:
            title = ""
        session = getattr(widget, "session", None) if widget else None
        return title or getattr(session, "title", "") or f"Tab {index + 1}"

    def _blocks_for_widget(self, widget: Any) -> List[Any]:
        editor = getattr(widget, "editor", None) or getattr(widget, "block_editor", None)
        if not editor:
            return []
        if hasattr(editor, "get_blocks"):
            try:
                return list(editor.get_blocks())
            except Exception:
                pass
        return list(getattr(editor, "blocks", []) or [])

    def _block_summary(self, block: Any, index: int, include_code: bool = True) -> Dict[str, Any]:
        code = ""
        try:
            code = block.get_code() if hasattr(block, "get_code") else ""
        except Exception:
            code = ""
        name = ""
        try:
            name = block.get_block_name() if hasattr(block, "get_block_name") else ""
        except Exception:
            name = ""
        language = ""
        try:
            language = block.get_language() if hasattr(block, "get_language") else ""
        except Exception:
            language = ""
        summary = {
            "index": index,
            "name": name or f"block{index + 1}",
            "language": language or "unknown",
            "lines": len(code.splitlines()) if code else 0,
        }
        if include_code:
            summary["code_preview"] = code[:800] + ("..." if len(code) > 800 else "")
        return summary

    def _tab_suggestions(self, include_code: bool = False) -> List[Dict[str, Any]]:
        items = []
        for index in range(self._tab_count()):
            widget = self._tab_widget(index)
            if widget is None or not hasattr(widget, "session"):
                continue
            blocks = self._blocks_for_widget(widget)
            session = getattr(widget, "session", None)
            items.append({
                "type": "tab",
                "reference": f"#tab{index + 1}",
                "insert_text": f"#tab{index + 1}",
                "label": self._tab_title(index, widget),
                "detail": f"{len(blocks)} blocks",
                "tab_index": index,
                "session_id": getattr(session, "session_id", ""),
                "blocks": [self._block_summary(block, i, include_code) for i, block in enumerate(blocks)] if include_code else [],
            })
        return items

    def _block_suggestions(self, include_code: bool = False) -> List[Dict[str, Any]]:
        widget = self._current_session_widget()
        blocks = self._blocks_for_widget(widget)
        items = []
        for index, block in enumerate(blocks):
            summary = self._block_summary(block, index, include_code)
            items.append({
                "type": "block",
                "reference": f"#block{index + 1}",
                "insert_text": f"#block{index + 1}",
                "label": summary["name"],
                "detail": f"{summary['language']}, {summary['lines']} lines",
                "block_index": index,
                **summary,
            })
            if summary["name"] and summary["name"] != f"block{index + 1}":
                items.append({
                    "type": "block",
                    "reference": f"#block:{summary['name']}",
                    "insert_text": f"#block:{summary['name']}",
                    "label": summary["name"],
                    "detail": "by name",
                    "block_index": index,
                    **summary,
                })
        return items

    def _resolve_tab(self, target: Dict[str, Any]) -> Dict[str, Any]:
        if target.get("index") is not None:
            index = int(target["index"])
            widget = self._tab_widget(index)
            if widget is None:
                return {"ok": False, "reference": target["reference"], "error": "Tab not found."}
            return self._tab_snapshot(index, widget)

        name = (target.get("name") or "").lower()
        for index in range(self._tab_count()):
            widget = self._tab_widget(index)
            if self._tab_title(index, widget).lower() == name:
                return self._tab_snapshot(index, widget)
        return {"ok": False, "reference": target["reference"], "error": "Tab not found."}

    def _tab_snapshot(self, index: int, widget: Any) -> Dict[str, Any]:
        session = getattr(widget, "session", None)
        return {
            "ok": True,
            "type": "tab",
            "reference": f"#tab{index + 1}",
            "tab_index": index,
            "title": self._tab_title(index, widget),
            "session_id": getattr(session, "session_id", ""),
            "connection_name": getattr(session, "connection_name", "") or "",
            "blocks": [self._block_summary(block, i, include_code=True) for i, block in enumerate(self._blocks_for_widget(widget))],
        }

    def _resolve_block(self, target: Dict[str, Any]) -> Dict[str, Any]:
        widget = self._current_session_widget()
        blocks = self._blocks_for_widget(widget)
        if target.get("index") is not None:
            index = int(target["index"])
            if 0 <= index < len(blocks):
                return self._block_snapshot(index, blocks[index], widget)
            return {"ok": False, "reference": target["reference"], "error": "Block not found."}

        name = (target.get("name") or "").lower()
        for index, block in enumerate(blocks):
            summary = self._block_summary(block, index, include_code=False)
            if summary["name"].lower() == name:
                return self._block_snapshot(index, block, widget)
        return {"ok": False, "reference": target["reference"], "error": "Block not found."}

    _ATTACH_MAX_LINES = 400
    _ATTACH_MAX_CHARS = 24_000

    def _bounded_code(self, block: Any) -> Tuple[str, str]:
        """Full block code bounded for prompt injection. Returns (code, note)."""
        try:
            code = block.get_code() if hasattr(block, "get_code") else ""
        except Exception:
            code = ""
        if not code:
            return "", ""
        lines = code.splitlines()
        note = ""
        if len(lines) > self._ATTACH_MAX_LINES:
            hidden = len(lines) - self._ATTACH_MAX_LINES
            code = "\n".join(lines[: self._ATTACH_MAX_LINES])
            note = (
                f"Truncated: {hidden} more lines — use datapyn_inspect with "
                "around=/start_line for the rest."
            )
        if len(code) > self._ATTACH_MAX_CHARS:
            code = code[: self._ATTACH_MAX_CHARS]
            note = note or "Truncated for size — use datapyn_inspect for the rest."
        return code, note

    def _block_snapshot(self, index: int, block: Any, widget: Any) -> Dict[str, Any]:
        session = getattr(widget, "session", None) if widget else None
        snapshot = self._block_summary(block, index, include_code=True)
        # Explicitly referenced blocks are user attachments — ship the full
        # (bounded) code so the agent can act without an inspect round.
        code, note = self._bounded_code(block)
        if code:
            snapshot["code"] = code
            if note:
                snapshot["code_note"] = note
        snapshot.update({
            "ok": True,
            "type": "block",
            "reference": f"#block{index + 1}",
            "block_index": index,
            "session_id": getattr(session, "session_id", ""),
            "tab_title": getattr(session, "title", ""),
            "is_user_attachment": True,
        })
        return snapshot
