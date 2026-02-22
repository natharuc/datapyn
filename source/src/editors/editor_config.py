"""
Editor configuration.

Monaco Editor is the sole editor backend.
Provides ghost text for inline completions from Copilot.
"""

from .monaco import MonacoEditor


def init_editor_backend() -> None:
    """Initialize editor backend (no-op, Monaco is always used)."""
    pass


def set_editor_backend(backend: str) -> None:
    """Set the editor backend (deprecated - Monaco is always used)."""
    if backend != "monaco":
        import logging
        logging.warning(f"Editor backend '{backend}' ignored - Monaco is the only supported backend")


def get_editor_backend() -> str:
    """Return the current editor backend name."""
    return "monaco"


def get_code_editor_class():
    """
    Returns the editor class.

    Returns:
        MonacoEditor
    """
    return MonacoEditor


def is_monaco_enabled() -> bool:
    """Check if Monaco editor is enabled (always True)."""
    return True
