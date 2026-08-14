"""One ACP subprocess per agent id, shared by that agent's tab sessions."""

from __future__ import annotations

import logging
import threading
from typing import Optional

from PyQt6.QtCore import QObject, QThread, Qt, pyqtSignal

from .catalog import get_agent, resolve_launch
from .client import AcpClient

logger = logging.getLogger(__name__)


def _client_version() -> str:
    try:
        from importlib.metadata import version

        return version("DataPyn")
    except Exception:
        return "0.0.0"


class AcpProcessPool(QObject):
    """Lazily spawn one AcpClient per agent_id."""

    client_started = pyqtSignal(str)
    client_stopped = pyqtSignal(str)
    stderr_line = pyqtSignal(str, str)  # agent_id, line
    _create_client = pyqtSignal(str, dict, object)

    def __init__(self, parent: Optional[QObject] = None):
        super().__init__(parent)
        self._clients: dict[str, AcpClient] = {}
        self._session_counts: dict[str, int] = {}
        self._start_lock = threading.Lock()
        self._create_client.connect(self._on_create_client, Qt.ConnectionType.QueuedConnection)

    def get(self, agent_id: str) -> Optional[AcpClient]:
        return self._clients.get(agent_id)

    def clients(self) -> list[AcpClient]:
        return [client for client in self._clients.values() if client is not None]

    def acquire(
        self,
        agent_id: str,
        *,
        cwd: str,
        extra_env: Optional[dict[str, str]] = None,
        extra_args: Optional[list[str]] = None,
    ) -> AcpClient:
        """Return a running client. Does not change the retain count."""
        extra_args = list(extra_args or [])
        with self._start_lock:
            spec = get_agent(agent_id)
            if spec is None:
                raise RuntimeError(f"Unknown agent: {agent_id}")
            launch = resolve_launch(spec)
            if launch is None:
                raise RuntimeError(f"Agent {spec.label} is not installed")
            command, args = launch
            args = list(args) + extra_args
            key = (command, tuple(args), cwd)
            existing = self._clients.get(agent_id)
            if existing and existing.is_running and getattr(existing, "_launch_key", None) == key:
                return existing
            if existing:
                try:
                    existing.stop()
                except Exception:
                    pass

            client = existing or self._make_client(agent_id)
            self._clients[agent_id] = client
            client.start(command, args, cwd=cwd, env=extra_env)
            client._launch_key = key
            client.initialize(client_name="DataPyn", client_version=_client_version())
            if spec.auth_method_id:
                try:
                    client.authenticate(spec.auth_method_id)
                except Exception as exc:
                    logger.info("ACP authenticate for %s skipped/failed: %s", agent_id, exc)
            self.client_started.emit(agent_id)
            return client

    def _make_client(self, agent_id: str) -> AcpClient:
        """Create the QObject on the pool's Qt thread (never from a worker)."""
        if QThread.currentThread() == self.thread():
            return self._new_client(agent_id)
        event = threading.Event()
        box: dict = {}
        self._create_client.emit(agent_id, box, event)
        if not event.wait(timeout=15):
            raise RuntimeError("Timed out creating ACP client on the UI thread")
        if box.get("error"):
            raise box["error"]
        client = box.get("client")
        if client is None:
            raise RuntimeError("ACP client was not created")
        return client

    def _on_create_client(self, agent_id: str, box: dict, event: object) -> None:
        try:
            box["client"] = self._new_client(agent_id)
        except Exception as exc:
            box["error"] = exc
        finally:
            event.set()

    def _new_client(self, agent_id: str) -> AcpClient:
        client = AcpClient(agent_id, parent=self)
        client.stderr_line.connect(lambda line, aid=agent_id: self.stderr_line.emit(aid, line))
        client.process_exited.connect(lambda _code, aid=agent_id: self._on_exit(aid))
        return client

    def retain(self, agent_id: str) -> None:
        self._session_counts[agent_id] = self._session_counts.get(agent_id, 0) + 1

    def release_session(self, agent_id: str) -> None:
        count = self._session_counts.get(agent_id, 0) - 1
        if count > 0:
            self._session_counts[agent_id] = count
            return
        self._session_counts[agent_id] = 0
        self.stop(agent_id)

    def stop(self, agent_id: str) -> None:
        client = self._clients.pop(agent_id, None)
        self._session_counts.pop(agent_id, None)
        if client:
            client.stop()
            self.client_stopped.emit(agent_id)

    def stop_all(self) -> None:
        for agent_id in list(self._clients):
            self.stop(agent_id)

    def _on_exit(self, agent_id: str) -> None:
        if agent_id in self._clients:
            self._clients.pop(agent_id, None)
            self._session_counts.pop(agent_id, None)
            self.client_stopped.emit(agent_id)
