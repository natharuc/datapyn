"""
Execution context for Pynia — the last error and the result the user is
currently looking at.

This is injected into every chat turn so Pynia can answer "why did my query
fail?" and "chart this result" without spending a tool round guessing. The
data already exists in the OutputPanel (structured LogEntry) and the
ResultsViewer (current grid + chartable sources); we just surface a bounded
summary of it.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

_MAX_PREVIEW_ROWS = 5
_MAX_PREVIEW_CHARS = 1500
_MAX_COLUMNS = 40


def _panels_for_session(main_window, session_id: str):
    """Return (output_panel, results_viewer) for the targeted session.

    Falls back to the globally-active panels when the session can't be
    resolved (the active session is normally the one the user is chatting
    about anyway).
    """
    output_panel = None
    results_viewer = None
    indices = getattr(main_window, "_session_panel_indices", None)
    if session_id and isinstance(indices, dict):
        info = indices.get(session_id)
        if info:
            output_panel = info.get("output")
            results_viewer = info.get("results")
    if output_panel is None:
        output_panel = getattr(main_window, "global_output_panel", None)
    if results_viewer is None:
        results_viewer = getattr(main_window, "global_results_viewer", None)
    return output_panel, results_viewer


def _active_result_summary(results_viewer) -> Optional[Dict[str, Any]]:
    """Summarize the grid the user is currently looking at."""
    if results_viewer is None:
        return None

    summary: Dict[str, Any] = {}
    df = getattr(results_viewer, "current_df", None)
    if df is not None and getattr(df, "empty", True) is False:
        try:
            columns = [str(c) for c in df.columns][:_MAX_COLUMNS]
            summary["rows"] = int(len(df))
            summary["columns"] = columns
            if len(df.columns) > _MAX_COLUMNS:
                summary["columns_truncated"] = int(len(df.columns) - _MAX_COLUMNS)
            preview = df.head(_MAX_PREVIEW_ROWS).to_string(max_cols=12)
            if len(preview) > _MAX_PREVIEW_CHARS:
                preview = preview[:_MAX_PREVIEW_CHARS] + " ..."
            summary["preview"] = preview
        except Exception as exc:  # pragma: no cover - defensive
            logger.debug("Pynia execution_context: result preview failed: %s", exc)

    # Chartable sources (label + numeric columns) — exactly the input
    # datapyn_chart needs, so "chart this result" is a one-shot.
    if hasattr(results_viewer, "list_visualizations"):
        try:
            sources = results_viewer.list_visualizations().get("sources") or []
            if sources:
                summary["chart_sources"] = sources[:8]
        except Exception as exc:  # pragma: no cover - defensive
            logger.debug("Pynia execution_context: list_visualizations failed: %s", exc)

    return summary or None


def build_execution_context(main_window, session_id: str = "") -> Optional[Dict[str, Any]]:
    """Build the bounded ``execution_state`` block for a chat turn."""
    if main_window is None:
        return None

    try:
        output_panel, results_viewer = _panels_for_session(main_window, session_id)
    except Exception as exc:  # pragma: no cover - defensive
        logger.debug("Pynia execution_context: panel lookup failed: %s", exc)
        return None

    state: Dict[str, Any] = {}

    if output_panel is not None and hasattr(output_panel, "get_last_error"):
        try:
            last_error = output_panel.get_last_error()
            if last_error:
                state["last_error"] = last_error
        except Exception as exc:  # pragma: no cover - defensive
            logger.debug("Pynia execution_context: last_error failed: %s", exc)

    active_result = _active_result_summary(results_viewer)
    if active_result:
        state["active_result"] = active_result

    return state or None
