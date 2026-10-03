"""Exercise the real NDJSON runtime in source or frozen mode, without a GUI."""
from __future__ import annotations

import argparse
from collections import deque
import json
import os
from pathlib import Path
import queue
import re
import signal
import subprocess
import sys
import threading
import time
from typing import Callable

ROOT = Path(__file__).resolve().parents[2]


class RuntimeClient:
    def __init__(self, executable: str | None, timeout: float):
        env = os.environ.copy()
        if executable:
            # A frozen smoke must resolve its bundled modules, independently of
            # the checkout's source tree or an existing Python installation.
            env.pop("PYTHONPATH", None)
            env.pop("DATAPYN_RUNTIME_PYTHON", None)
            env.pop("DATAPYN_REPO_ROOT", None)
        else:
            env["PYTHONPATH"] = os.pathsep.join(filter(None, [str(ROOT / "source"), env.get("PYTHONPATH")]))
        env["PYTHONUNBUFFERED"] = "1"
        env["MPLBACKEND"] = "Agg"
        command = [str(Path(executable).resolve())] if executable else [sys.executable, "-u", "-m", "datapyn_runtime"]
        self.process = subprocess.Popen(
            command, cwd=ROOT, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding="utf-8", bufsize=1,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
            start_new_session=sys.platform != "win32",
        )
        self.timeout = timeout
        self.sequence = 0
        self.messages: queue.Queue = queue.Queue()
        self.pending: list[dict] = []
        self.diagnostics: deque[str] = deque(maxlen=60)
        threading.Thread(target=self._read_stdout, daemon=True).start()
        threading.Thread(target=self._read_stderr, daemon=True).start()

    def _read_stdout(self):
        try:
            for line in self.process.stdout:
                try:
                    self.messages.put(json.loads(line))
                except json.JSONDecodeError:
                    self.messages.put({"_protocol_error": f"stdout não é NDJSON: {line[:200]}"})
        finally:
            self.messages.put({"_eof": True})

    def _read_stderr(self):
        for line in self.process.stderr:
            self.diagnostics.append(line.rstrip())

    def wait(self, predicate: Callable[[dict], bool], timeout: float | None = None) -> dict:
        for index, message in enumerate(self.pending):
            if predicate(message):
                return self.pending.pop(index)
        deadline = time.monotonic() + (self.timeout if timeout is None else timeout)
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError(f"Runtime não respondeu. stderr: {' | '.join(self.diagnostics)}")
            try:
                message = self.messages.get(timeout=remaining)
            except queue.Empty as error:
                raise TimeoutError(f"Runtime não respondeu. stderr: {' | '.join(self.diagnostics)}") from error
            if "_protocol_error" in message:
                raise AssertionError(message["_protocol_error"])
            if message.get("_eof"):
                raise RuntimeError(f"Runtime encerrou antes da resposta. stderr: {' | '.join(self.diagnostics)}")
            if predicate(message):
                return message
            self.pending.append(message)

    def request(self, method: str, params: dict | None = None, timeout: float | None = None):
        self.sequence += 1
        request_id = self.sequence
        payload = {"id": request_id, "method": method, "params": params or {}}
        self.process.stdin.write(json.dumps(payload) + "\n")
        self.process.stdin.flush()
        response = self.wait(lambda item: item.get("id") == request_id, timeout)
        if "error" in response:
            raise AssertionError(f"{method}: {response['error']}")
        return response["result"]

    def event(self, name: str, execution_id: str | None = None, session_id: str | None = None):
        return self.wait(lambda item: item.get("event") == name
                         and (execution_id is None or item.get("payload", {}).get("execution_id") == execution_id)
                         and (session_id is None or item.get("payload", {}).get("session_id") == session_id))["payload"]

    def execute(self, session_id: str, execution_id: str, language: str, code: str, variable_name: str = "") -> dict:
        params = {"session_id": session_id, "execution_id": execution_id, "language": language, "code": code}
        if variable_name:
            params["variable_name"] = variable_name
        self.request("execution.run", params)
        finished = self.event("execution.finished", execution_id=execution_id)
        if finished.get("status") != "succeeded":
            raise AssertionError(f"Execução {execution_id}: {finished}")
        return finished

    def close(self):
        if self.process.poll() is None:
            try:
                self.request("system.shutdown", timeout=10)
            except (AssertionError, RuntimeError, TimeoutError, OSError):
                pass
            try:
                self.process.stdin.close()
                self.process.wait(timeout=15)
            except (OSError, subprocess.TimeoutExpired):
                if sys.platform == "win32":
                    subprocess.run(["taskkill", "/PID", str(self.process.pid), "/T", "/F"],
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), check=False)
                else:
                    try:
                        os.killpg(self.process.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                self.process.wait(timeout=10)
        for stream in (self.process.stdin, self.process.stdout, self.process.stderr):
            if stream and not stream.closed:
                stream.close()


def result_page(client: RuntimeClient, session_id: str, finished: dict) -> dict:
    descriptors = finished.get("results", [])
    result_id = next((item.get("result_id") for item in descriptors if item.get("result_id")), None)
    if not result_id:
        raise AssertionError(f"Sem resultado paginável: {finished}")
    return client.request("result.page", {"session_id": session_id, "result_id": result_id, "offset": 0, "limit": 50})


def first_value(page: dict):
    rows = page.get("rows", [])
    if not rows:
        raise AssertionError(f"Resultado vazio: {page}")
    return next(iter(rows[0].values())) if isinstance(rows[0], dict) else rows[0][0]


def process_alive(pid: int) -> bool:
    if sys.platform == "win32":
        import ctypes

        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.argtypes = [ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]
        kernel.OpenProcess.restype = ctypes.c_void_p
        kernel.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
        kernel.WaitForSingleObject.restype = ctypes.c_ulong
        kernel.CloseHandle.argtypes = [ctypes.c_void_p]
        handle = kernel.OpenProcess(0x00100000, False, pid)  # SYNCHRONIZE
        if not handle:
            if ctypes.get_last_error() == 87:  # ERROR_INVALID_PARAMETER: exited
                return False
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            return kernel.WaitForSingleObject(handle, 0) == 258  # WAIT_TIMEOUT
        finally:
            kernel.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


def terminate_owned_child(pid: int):
    """Clean up only the subprocess created by this smoke if a check fails."""
    if not process_alive(pid):
        return
    if sys.platform == "win32":
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), check=False)
    else:
        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass


def smoke(executable: str | None, timeout: float):
    client = RuntimeClient(executable, timeout)
    owned_child = None
    try:
        session = client.request("session.create")["session_id"]
        client.request("connection.connect", {"session_id": session, "config": {"db_type": "sqlite", "database": ":memory:"}})
        sql = client.execute(session, "smoke-sql", "sql", "SELECT 1 AS value", "df")
        assert first_value(result_page(client, session, sql)) == 1
        python = client.execute(session, "smoke-python", "python", "pd.DataFrame({'value': [int(df['value'].sum()) + 1]})")
        assert first_value(result_page(client, session, python)) == 2

        second = client.request("session.create")["session_id"]
        loop_code = """import os, subprocess
command = [os.environ['COMSPEC'], '/d', '/c', 'ping -n 121 127.0.0.1 >nul'] if os.name == 'nt' else ['sleep', '120']
child = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=0x08000000 if os.name == 'nt' else 0)
print('smoke-child:' + str(child.pid), flush=True)
while True:
    pass
"""
        client.request("execution.run", {"session_id": session, "execution_id": "smoke-loop", "language": "python", "code": loop_code})
        client.event("execution.started", execution_id="smoke-loop")
        output = ""
        while owned_child is None:
            output += client.event("execution.output", execution_id="smoke-loop").get("text", "")
            match = re.search(r"smoke-child:(\d+)", output)
            if match:
                owned_child = int(match.group(1))
        assert process_alive(owned_child), "Smoke subprocess did not start"
        independent = client.execute(second, "smoke-independent", "python", "pd.DataFrame({'value': [42]})")
        assert first_value(result_page(client, second, independent)) == 42
        client.request("execution.cancel", {"session_id": session, "execution_id": "smoke-loop"})
        reset = client.event("session.reset", session_id=session)
        assert reset.get("namespace_lost") is True
        deadline = time.monotonic() + 10
        while process_alive(owned_child) and time.monotonic() < deadline:
            time.sleep(0.05)
        assert not process_alive(owned_child), "Cancellation left a user subprocess running"
        recovered = client.execute(session, "smoke-recovered", "python", "pd.DataFrame({'value': [7]})")
        assert first_value(result_page(client, session, recovered)) == 7
    finally:
        client.close()
        if owned_child is not None:
            terminate_owned_child(owned_child)
    print("Runtime smoke: SQL -> DataFrame -> Python; independent session; cancel, child cleanup and recovery OK.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--executable", help="Frozen sidecar; default is the current Python with -m datapyn_runtime")
    parser.add_argument("--timeout", type=float, default=60, help="Deadline in seconds for each response or event")
    args = parser.parse_args()
    smoke(args.executable, args.timeout)


if __name__ == "__main__":
    main()
