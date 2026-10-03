"""Core exports loaded on demand so pure data modules do not import Qt."""

from importlib import import_module

_EXPORTS = {
    "ResultsManager": ".results_manager",
    "ShortcutManager": ".shortcut_manager",
    "WorkspaceManager": ".workspace_manager",
    "ThemeManager": ".theme_manager",
    "Session": ".session",
    "SessionManager": ".session_manager",
}
__all__ = list(_EXPORTS)


def __getattr__(name):
    module = _EXPORTS.get(name)
    if module is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(import_module(module, __name__), name)
    globals()[name] = value
    return value
