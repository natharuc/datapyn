"""Tests for Copilot chat #tab/#block reference resolution."""

from types import SimpleNamespace


class FakeBlock:
    def __init__(self, name, language, code):
        self._name = name
        self._language = language
        self._code = code

    def get_block_name(self):
        return self._name

    def get_language(self):
        return self._language

    def get_code(self):
        return self._code


class FakeEditor:
    def __init__(self, blocks):
        self.blocks = blocks

    def get_blocks(self):
        return self.blocks


class FakeTabs:
    def __init__(self, widgets, titles):
        self._widgets = widgets
        self._titles = titles
        self._current_index = 0

    def count(self):
        return len(self._widgets)

    def widget(self, index):
        return self._widgets[index]

    def currentIndex(self):
        return self._current_index

    def tabText(self, index):
        return self._titles[index]


def make_main_window():
    sales = SimpleNamespace(
        session=SimpleNamespace(title="Sales", session_id="tab-sales", connection_name="prod"),
        editor=FakeEditor([
            FakeBlock("orders", "sql", "SELECT * FROM orders"),
            FakeBlock("chart", "python", "orders.head()"),
        ]),
    )
    finance = SimpleNamespace(
        session=SimpleNamespace(title="Finance", session_id="tab-finance", connection_name="dw"),
        editor=FakeEditor([FakeBlock("payments", "sql", "SELECT * FROM payments")]),
    )
    return SimpleNamespace(session_tabs=FakeTabs([sales, finance], ["Sales", "Finance"]))


def test_parse_finds_tab_and_block_references():
    from src.services.copilot.reference_resolver import ReferenceResolver

    refs = ReferenceResolver().parse("compare #tab2 with #block:orders and #block1")

    assert refs == [
        {"reference": "#tab2", "type": "tab", "index": 1, "name": ""},
        {"reference": "#block:orders", "type": "block", "index": None, "name": "orders"},
        {"reference": "#block1", "type": "block", "index": 0, "name": ""},
    ]


def test_suggestions_include_tabs_and_current_blocks():
    from src.services.copilot.reference_resolver import ReferenceResolver

    resolver = ReferenceResolver(make_main_window())

    suggestions = resolver.suggestions("#")
    insert_texts = {item["insert_text"] for item in suggestions}

    assert "#tab1" in insert_texts
    assert "#tab2" in insert_texts
    assert "#block1" in insert_texts
    assert "#block:orders" in insert_texts


def test_resolve_tab_returns_blocks_with_code_preview():
    from src.services.copilot.reference_resolver import ReferenceResolver

    resolved = ReferenceResolver(make_main_window()).resolve("#tab:Finance")

    assert resolved["ok"] is True
    assert resolved["type"] == "tab"
    assert resolved["title"] == "Finance"
    assert resolved["session_id"] == "tab-finance"
    assert resolved["blocks"][0]["code_preview"] == "SELECT * FROM payments"


def test_resolve_block_by_name_uses_current_tab():
    from src.services.copilot.reference_resolver import ReferenceResolver

    resolved = ReferenceResolver(make_main_window()).resolve("#block:orders")

    assert resolved["ok"] is True
    assert resolved["type"] == "block"
    assert resolved["name"] == "orders"
    assert resolved["code_preview"] == "SELECT * FROM orders"


def test_resolved_block_is_full_code_attachment():
    """#block refs are user attachments — full (bounded) code, not a preview."""
    from src.services.copilot.reference_resolver import ReferenceResolver

    big_code = "\n".join(f"-- line {i}" for i in range(1, 501))
    mw = SimpleNamespace(
        session_tabs=FakeTabs(
            [SimpleNamespace(
                session=SimpleNamespace(title="T", session_id="t1", connection_name=""),
                editor=FakeEditor([FakeBlock("gecon", "sql", big_code)]),
            )],
            ["T"],
        )
    )
    resolved = ReferenceResolver(mw).resolve("#block:gecon")

    assert resolved["ok"] is True
    assert resolved["is_user_attachment"] is True
    assert "-- line 400" in resolved["code"]          # well beyond the 800-char preview
    assert "-- line 401" not in resolved["code"]      # bounded at 400 lines
    assert "code_note" in resolved

    small = ReferenceResolver(make_main_window()).resolve("#block1")
    assert small["code"] == "SELECT * FROM orders"
    assert "code_note" not in small


def test_attached_references_directive_prioritizes_refs():
    from src.services.pynia.focus_context import attached_references_directive

    text = attached_references_directive([
        {"ok": True, "type": "block", "name": "gecon", "language": "sql", "lines": 94},
        {"ok": False, "type": "block", "reference": "#block9", "error": "Block not found."},
        {"ok": True, "type": "tab", "title": "GECON x SUN.dpw"},
    ])
    assert "gecon" in text
    assert "GECON x SUN.dpw" in text
    assert "highest priority" in text
    assert "#block9" not in text

    assert attached_references_directive([]) == ""
    assert attached_references_directive(None) == ""
    assert attached_references_directive([{"ok": False, "type": "block"}]) == ""