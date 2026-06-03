"""Runtime service: register handlers and run on stdio."""

from __future__ import annotations

from typing import Any, Dict

from datapyn_runtime.executor import SqlExecutor
from datapyn_runtime.rpc import JsonRpcServer


def build_server() -> JsonRpcServer:
    executor = SqlExecutor()
    server = JsonRpcServer()

    server.register("ping", lambda _params: {"ok": True, "version": "0.1.0"})
    server.register("shutdown", _shutdown)

    def execute_sql(params: Dict[str, Any]) -> Dict[str, Any]:
        sql = params.get("sql", "SELECT 1")
        return executor.execute_sql(str(sql))

    server.register("execute_sql", execute_sql)
    return server


def _shutdown(_params: Dict[str, Any]) -> Dict[str, Any]:
    return {"ok": True}


def run_stdio() -> None:
    build_server().run_stdio()
