"""Lazy compatibility exports; pure protocols do not load a desktop frontend."""
from importlib import import_module

_EXPORTS = {'PyniaAcpHost': ('.acp.host', 'PyniaAcpHost'), 'AGENT_IDS': ('.acp.catalog', 'AGENT_IDS'), 'AgentId': ('.acp.catalog', 'AgentId'), 'get_agent': ('.acp.catalog', 'get_agent'), 'list_agents': ('.acp.catalog', 'list_agents'), 'get_pynia_settings': ('.settings', 'get_pynia_settings'), 'reset_pynia_settings': ('.settings', 'reset_pynia_settings')}
__all__ = list(_EXPORTS)

def __getattr__(name):
    if name not in _EXPORTS:
        raise AttributeError(name)
    module, attribute = _EXPORTS[name]
    value = getattr(import_module(module, __name__), attribute)
    globals()[name] = value
    return value
