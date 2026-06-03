import json
import os
import subprocess
import sys
from pathlib import Path

from datapyn_runtime.executor import SqlExecutor
from datapyn_runtime.rpc import JsonRpcServer, request

RUNTIME_ROOT = Path(__file__).resolve().parents[1]
RUNTIME_SRC = RUNTIME_ROOT / "src"


def test_ping_handler():
    server = JsonRpcServer()
    server.register("ping", lambda _p: {"ok": True})
    out = server.handle(json.loads(request("ping")))
    assert out is not None
    assert out["result"]["ok"] is True


def test_execute_sql_select_1():
    result = SqlExecutor().execute_sql("SELECT 1 AS n")
    assert result["row_count"] == 1
    assert result["columns"] == ["n"]
    assert result["rows"][0][0] == 1


def test_stdio_subprocess_ping_and_execute():
    cmd = [sys.executable, "-m", "datapyn_runtime"]
    env = os.environ.copy()
    env["PYTHONPATH"] = str(RUNTIME_SRC)
    proc = subprocess.Popen(
        cmd,
        cwd=RUNTIME_ROOT,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
    )
    assert proc.stdin and proc.stdout

    def call(method: str, params: dict | None = None) -> dict:
        line = request(method, params, msg_id=1) + "\n"
        proc.stdin.write(line)
        proc.stdin.flush()
        response_line = proc.stdout.readline()
        return json.loads(response_line)

    ping = call("ping")
    assert ping["result"]["ok"] is True

    sql = call("execute_sql", {"sql": "SELECT 42 AS answer"})
    assert sql["result"]["rows"][0][0] == 42

    proc.stdin.write(request("shutdown") + "\n")
    proc.stdin.close()
    proc.wait(timeout=5)
