"""Lazy compatibility exports; pure protocols do not load a desktop frontend."""
from importlib import import_module

_EXPORTS = {'PyniaToolRegistry': ('.registry', 'PyniaToolRegistry')}
__all__ = list(_EXPORTS)

def __getattr__(name):
    if name not in _EXPORTS:
        raise AttributeError(name)
    module, attribute = _EXPORTS[name]
    value = getattr(import_module(module, __name__), attribute)
    globals()[name] = value
    return value
