"""Lazy compatibility exports; pure protocols do not load a desktop frontend."""
from importlib import import_module

_EXPORTS = {'AGENT_IDS': ('.catalog', 'AGENT_IDS'), 'AgentSpec': ('.catalog', 'AgentSpec'), 'GrantResult': ('.agent', 'GrantResult'), 'IAcpAgent': ('.agent', 'IAcpAgent'), 'create_acp_agent': ('.agents.factory', 'create_acp_agent'), 'get_agent': ('.catalog', 'get_agent'), 'list_agents': ('.catalog', 'list_agents'), 'TabChatState': ('.binding', 'TabChatState'), 'PyniaAcpHost': ('.host', 'PyniaAcpHost'), 'AcpProcessPool': ('.pool', 'AcpProcessPool'), 'AcpSessionService': ('.service', 'AcpSessionService')}
__all__ = list(_EXPORTS)

def __getattr__(name):
    if name not in _EXPORTS:
        raise AttributeError(name)
    module, attribute = _EXPORTS[name]
    value = getattr(import_module(module, __name__), attribute)
    globals()[name] = value
    return value
