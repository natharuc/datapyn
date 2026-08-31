"""Forward open-file requests to an already running DataPyn process."""

from __future__ import annotations

import getpass
import json
import logging
from collections.abc import Callable

from PyQt6.QtCore import QObject, QTimer
from PyQt6.QtNetwork import QLocalServer, QLocalSocket

logger = logging.getLogger(__name__)

# Cold-start probe: keep short so double-click open is not blocked when alone.
_CONNECT_MS = 200
_WRITE_MS = 2000


def single_instance_socket_name() -> str:
    """Stable per-user server id (short for Windows named pipes)."""
    user = getpass.getuser() or "default"
    return f"datapyn-ide-{user}"


def encode_open_files_message(paths: list[str], *, focus: bool = True) -> bytes:
    payload = {"paths": [str(path) for path in paths], "focus": bool(focus)}
    return json.dumps(payload, ensure_ascii=False).encode("utf-8")


def decode_open_files_message(data: bytes) -> tuple[list[str], bool]:
    if not data:
        return [], True
    obj = json.loads(data.decode("utf-8"))
    if not isinstance(obj, dict):
        return [], True
    raw_paths = obj.get("paths", [])
    paths = [str(path) for path in raw_paths if path] if isinstance(raw_paths, list) else []
    return paths, bool(obj.get("focus", True))


def try_forward_to_running_instance(paths: list[str], *, focus: bool = True) -> bool:
    """Send paths to the primary instance. True => exit this process."""
    socket = QLocalSocket()
    socket.connectToServer(single_instance_socket_name())
    if not socket.waitForConnected(_CONNECT_MS):
        return False

    try:
        socket.write(encode_open_files_message(paths, focus=focus))
        socket.flush()
        socket.waitForBytesWritten(_WRITE_MS)
        return True
    finally:
        socket.disconnectFromServer()


class SingleInstanceServer(QObject):
    """Listen for file-open requests from secondary DataPyn launches."""

    def __init__(
        self,
        on_open_files: Callable[[list[str], bool], None],
        parent: QObject | None = None,
    ):
        super().__init__(parent)
        self._on_open_files = on_open_files
        self._server = QLocalServer(self)
        self._server.newConnection.connect(self._handle_new_connection)

    def listen(self) -> bool:
        name = single_instance_socket_name()
        if self._server.listen(name):
            return True
        QLocalServer.removeServer(name)
        return self._server.listen(name)

    def _handle_new_connection(self) -> None:
        while self._server.hasPendingConnections():
            client = self._server.nextPendingConnection()
            if client is None:
                continue
            client.readyRead.connect(lambda c=client: self._read_client(c))

    def _read_client(self, client: QLocalSocket) -> None:
        data = bytes(client.readAll())
        client.disconnectFromServer()
        try:
            paths, focus = decode_open_files_message(data)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            logger.warning("Ignored malformed single-instance message: %s", exc)
            return
        QTimer.singleShot(0, lambda p=paths, f=focus: self._on_open_files(p, f))


def install_single_instance_server(
    app: QObject,
    on_open_files: Callable[[list[str], bool], None],
) -> SingleInstanceServer | None:
    server = SingleInstanceServer(on_open_files, app)
    if not server.listen():
        logger.warning("Single-instance server could not listen")
        return None
    app._datapyn_single_instance_server = server  # type: ignore[attr-defined]
    return server
