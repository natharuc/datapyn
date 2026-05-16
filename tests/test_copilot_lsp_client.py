from unittest.mock import MagicMock

from src.services.copilot.copilot_lsp_client import CopilotLSPClient


def _make_client() -> CopilotLSPClient:
    client = CopilotLSPClient("mock-server")
    client._send_request = MagicMock()
    client._send_notification = MagicMock()
    return client


def _make_process(poll_values):
    process = MagicMock()
    process.poll.side_effect = poll_values
    process.wait = MagicMock(side_effect=AssertionError("wait() should not be called during stop()"))
    process.stdin = MagicMock()
    process.stdout = MagicMock()
    process.stderr = MagicMock()
    return process


class TestCopilotLSPClientStop:
    def test_stop_terminates_process_without_waiting(self):
        client = _make_client()
        process = _make_process([None, 0])
        client._process = process

        client.stop()

        client._send_request.assert_called_once_with("shutdown", {})
        client._send_notification.assert_called_once_with("exit", {})
        process.terminate.assert_called_once()
        process.kill.assert_not_called()
        process.wait.assert_not_called()

    def test_stop_kills_process_if_it_stays_running(self):
        client = _make_client()
        process = _make_process([None, None])
        client._process = process

        client.stop()

        process.terminate.assert_called_once()
        process.kill.assert_called_once()
        process.wait.assert_not_called()

    def test_cleanup_delegates_to_stop(self):
        client = CopilotLSPClient("mock-server")
        client.stop = MagicMock()

        client.cleanup()

        client.stop.assert_called_once_with()
