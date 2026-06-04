from src.editors.completion_context import (
    build_python_lsp_preamble,
    build_sibling_block_completions,
    collect_blocks_code_context,
    collect_global_imports,
)


class _FakeBlock:
    def __init__(self, lang, code, name=""):
        self._lang = lang
        self._code = code
        self._name = name

    def get_language(self):
        return self._lang

    def get_code(self):
        return self._code

    def get_block_name(self):
        return self._name


def test_collect_global_imports_dedupes():
    blocks = [
        _FakeBlock("python", "import pandas as pd\n"),
        _FakeBlock("python", "import pandas as pd\nimport numpy as np\n"),
    ]
    assert "import pandas as pd" in collect_global_imports(blocks)
    assert collect_global_imports(blocks).count("import pandas as pd") == 1


def test_collect_blocks_code_context_excludes_current():
    blocks = [
        _FakeBlock("sql", "SELECT 1", "sales"),
        _FakeBlock("python", "x = 1\n", "prep"),
        _FakeBlock("python", "y = 2\n", "main"),
    ]
    ctx = collect_blocks_code_context(blocks, current_block=blocks[2])
    assert "sales" in ctx
    assert "prep" in ctx
    assert "y = 2" not in ctx


def test_sibling_block_completions_multiline():
    blocks = [
        _FakeBlock("python", "def foo():\n    return 1\n", "calc"),
        _FakeBlock("python", "x = 2\n", "main"),
    ]
    items = build_sibling_block_completions(blocks, current_block=blocks[1], target_language="python")
    assert len(items) == 1
    assert "def foo():" in items[0]["insertText"]
    assert items[0]["insertText"].endswith("\n")
    assert items[0]["category"] == "block"


def test_python_lsp_preamble_line_offset():
    preamble, offset = build_python_lsp_preamble(
        global_imports="import os",
        namespace={"df": "DataFrame"},
        blocks_code_context="# block a",
    )
    combined = preamble + "cursor_here = 1\n"
    assert offset == len(preamble.splitlines())
    assert combined.splitlines()[offset].startswith("cursor_here")
