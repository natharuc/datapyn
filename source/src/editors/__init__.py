"""
Editors package.

NOTE: Do NOT add top-level imports of CodeBlock or BlockEditor here.
code_block.py imports editor_config which imports monaco, creating a
circular dependency that deadlocks Python's import machinery.

Import directly from the submodules instead:
    from src.editors.code_block import CodeBlock
    from src.editors.block_editor import BlockEditor
    from src.editors.interfaces import ICodeEditor
    from src.editors.editor_config import get_code_editor_class
"""

from .interfaces import ICodeEditor

__all__ = [
    "ICodeEditor",
]


def __getattr__(name):
    """Lazy imports to avoid circular dependency."""
    if name == "CodeBlock":
        from .code_block import CodeBlock
        return CodeBlock
    if name == "BlockEditor":
        from .block_editor import BlockEditor
        return BlockEditor
    if name == "MonacoEditor":
        try:
            from .monaco import MonacoEditor
            return MonacoEditor
        except ImportError:
            return None
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
