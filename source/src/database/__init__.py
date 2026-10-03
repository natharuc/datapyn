"""Database exports without eagerly importing workspace or UI services."""

from importlib import import_module

_EXPORTS = {
    "ConnectionManager": ".connection_manager",
    "DatabaseConnector": ".database_connector",
}
__all__ = list(_EXPORTS)


def __getattr__(name):
    module = _EXPORTS.get(name)
    if module is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(import_module(module, __name__), name)
    globals()[name] = value
    return value
