"""Service exports loaded on demand for both desktop hosts."""

from importlib import import_module

_EXPORTS = {
    "QueryService": ".query_service",
    "QueryResult": ".query_service",
    "PythonExecutionService": ".python_execution_service",
    "PythonExecutionResult": ".python_execution_service",
    "ConnectionService": ".connection_service",
    "ConnectionConfig": ".connection_service",
    "SessionLifecycleService": ".session_lifecycle_service",
    "PanelManager": ".panel_manager",
    "PanelSet": ".panel_manager",
    "FileImportService": ".file_import_service",
    "PackageManagerService": ".package_manager_service",
    "PackageInfo": ".package_manager_service",
    "PackageOperationResult": ".package_manager_service",
    "AutoUpdateService": ".auto_update_service",
}
__all__ = list(_EXPORTS)


def __getattr__(name):
    module = _EXPORTS.get(name)
    if module is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(import_module(module, __name__), name)
    globals()[name] = value
    return value
