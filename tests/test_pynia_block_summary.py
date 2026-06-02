"""Block structure summaries for context injection."""

from src.services.pynia.block_summary import (
    block_structure_summary,
    enrich_focus_detail,
)


def test_block_structure_summary_finds_python_functions():
    code = "def render_panel():\n    pass\n\ndef update_summary():\n    return 1\n"
    s = block_structure_summary(code, "python")
    assert "render_panel" in s.get("python_functions", [])
    assert s.get("line_count") == 5


def test_enrich_focus_detail_adds_structure_for_large_block():
    focus = {
        "name": "block4",
        "language": "python",
        "lines": 200,
        "code": "def a():\n pass\n" + ("x = 1\n" * 200),
        "hints": ["generates_html"],
    }
    out = enrich_focus_detail(focus)
    assert "structure_summary" in out
    assert out["structure_summary"].get("reading_hint")
