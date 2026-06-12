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


class TestInlineCompletion:
    def test_extract_inline_completion_variants(self):
        f = CopilotLSPClient._extract_inline_completion
        assert f({"items": [{"insertText": "hello"}]}) == "hello"
        assert f({"items": [{"insertText": {"value": "x = 1"}}]}) == "x = 1"
        assert f([{"insertText": "abc"}]) == "abc"          # bare list form
        assert f({"items": [{"text": "fallback"}]}) == "fallback"
        assert f({"items": []}) == ""
        assert f(None) == ""

    def test_request_completion_uses_cycling_method(self):
        # getCompletionsCycling is the method this server actually answers
        # (verified live; inlineCompletion/getCompletions return empty).
        client = _make_client()
        client._initialized = True
        client._is_authenticated = True
        client._opened_uris.add("file:///x.py")
        client._documents["file:///x.py"] = {
            "text": "def f():\n    ",
            "version": 3,
            "language": "python",
        }

        client.request_completion("file:///x.py", 3, 5, 2)

        method = client._send_request.call_args[0][0]
        params = client._send_request.call_args[0][1]
        assert method == "getCompletionsCycling"
        assert params["doc"]["uri"] == "file:///x.py"
        assert params["doc"]["position"] == {"line": 5, "character": 2}
        assert params["doc"]["source"] == "def f():\n    "

    def test_extract_handles_cycling_response(self):
        f = CopilotLSPClient._extract_inline_completion
        resp = {"completions": [{"displayText": "if x:\n    pass", "text": "    if x:\n    pass"}]}
        # displayText (cursor-relative) is preferred over text (range-relative).
        assert f(resp) == "if x:\n    pass"

    def test_request_completion_lazy_opens_document(self):
        client = _make_client()
        client._initialized = True
        client._is_authenticated = True
        client._documents["file:///new.py"] = {
            "text": "print(1)",
            "version": 1,
            "language": "python",
        }
        # uri not in _opened_uris → should didOpen first

        client.request_completion("file:///new.py", 1, 0, 0)

        notif_methods = [c[0][0] for c in client._send_notification.call_args_list]
        assert "textDocument/didOpen" in notif_methods
        assert "file:///new.py" in client._opened_uris

    def test_mark_degraded_blocks_inline_completion(self):
        client = _make_client()
        client._initialized = True
        client._is_authenticated = True
        client.mark_degraded("ETIMEDOUT")

        assert client.is_degraded
        assert not client.completions_enabled

        client.request_completion("file:///x.py", 1, 0, 0)
        client._send_request.assert_not_called()

    def test_network_log_message_marks_degraded(self):
        client = _make_client()
        client._handle_notification(
            "window/logMessage",
            {"message": "FetchError: connect ETIMEDOUT", "type": 2},
        )
        assert client.is_degraded
