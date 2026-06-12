"""Tests for Pynia multi-provider agent layer."""

import json
from unittest.mock import MagicMock, patch

import pytest
from PyQt6.QtWidgets import QApplication

from src.services.pynia.agent_client import PyniaAgentClient
from src.services.pynia.openai_agent_loop import run_openai_agent_turn
from src.services.pynia.settings import get_pynia_settings, set_provider_secret
from src.services.pynia.types import PROVIDERS


@pytest.fixture
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


class TestPyniaAgentClient:
    def test_token_worker_has_no_parent_for_move_to_thread(self, qapp):
        """TokenAgentWorker must be parentless so chat/verify run off the UI thread."""
        from PyQt6.QtCore import QThread
        from src.services.pynia.providers.token_worker import TokenAgentWorker

        worker = TokenAgentWorker("openai")
        assert worker.parent() is None
        thread = QThread()
        worker.moveToThread(thread)
        assert worker.thread() is thread
        thread.quit()
        thread.wait(1000)

    def test_refresh_metadata_skips_while_token_worker_running(self, qapp):
        set_provider_secret("openai", "sk-test")
        client = PyniaAgentClient()
        client.set_provider("openai")
        client._token_thread = MagicMock()
        client._token_thread.isRunning.return_value = True

        with patch.object(client, "_start_token_worker") as start_worker:
            client.refresh_metadata()
            start_worker.assert_not_called()

        set_provider_secret("openai", "")

    def test_cancel_waits_for_token_worker_shutdown(self, qapp):
        set_provider_secret("openai", "sk-test")
        client = PyniaAgentClient()
        client.set_provider("openai")
        client._token_worker_mode = "chat"
        client._token_thread = MagicMock()
        client._token_thread.isRunning.return_value = True

        with patch(
            "src.utils.qt_threading.stop_qthread",
            return_value=True,
        ) as stop_thread:
            client.cancel()
            stop_thread.assert_called_once()
            assert client._token_worker is None
            assert client._token_thread is None

        set_provider_secret("openai", "")

    def test_apply_connector_from_settings_emits_authenticated_for_new_token(self, qapp):
        set_provider_secret("openai", "sk-test")
        client = PyniaAgentClient()
        client.set_provider("openai")
        client._is_authenticated = False

        with patch.object(client, "authenticated") as auth_emit:
            client.apply_connector_from_settings("openai")
            auth_emit.assert_called_once()

        set_provider_secret("openai", "")

    def test_cached_models_restored_on_init(self, qapp):
        settings = get_pynia_settings()
        cached = [
            {"id": "openai/gpt-4o", "name": "GPT-4o", "multiplier": 1.0},
            {"id": "anthropic/claude-sonnet-4.6", "name": "Claude Sonnet 4.6", "multiplier": 1.0},
            {"id": "moonshotai/kimi-k2", "name": "Kimi K2", "multiplier": 1.0},
        ]
        settings.set_cached_models("openrouter", cached)
        set_provider_secret("openrouter", "sk-or-test")
        client = PyniaAgentClient()
        client.set_provider("openrouter")
        assert len(client.available_models()) == 3
        assert client.available_models()[2]["id"] == "moonshotai/kimi-k2"
        set_provider_secret("openrouter", "")
        settings.set_cached_models("openrouter", [])


class TestOpenRouterModels:
    def test_openrouter_price_label(self):
        from src.services.pynia.openai_agent_loop import _openrouter_price_label

        label = _openrouter_price_label(
            {"pricing": {"prompt": "0.0000025", "completion": "0.00001"}}
        )
        assert "in" in label and "out" in label
        assert "$" in label

    def test_fetch_openrouter_models_filters_and_prices(self, monkeypatch):
        from src.services.pynia.openai_agent_loop import fetch_openai_models

        class FakeResp:
            status_code = 200

            def json(self):
                return {
                    "data": [
                        {
                            "id": "openai/text-embedding-3-small",
                            "name": "Embed",
                            "architecture": {"output_modalities": ["embedding"]},
                        },
                        {
                            "id": "anthropic/claude-sonnet-4.6",
                            "name": "Claude Sonnet 4.6",
                            "architecture": {"output_modalities": ["text"]},
                            "pricing": {"prompt": "0.000003", "completion": "0.000015"},
                            "context_length": 200000,
                        },
                    ]
                }

        monkeypatch.setattr(
            "requests.get",
            lambda *args, **kwargs: FakeResp(),
        )
        models = fetch_openai_models(
            "https://openrouter.ai/api/v1",
            "sk-or-test",
            provider_id="openrouter",
        )
        assert len(models) == 1
        assert models[0]["id"] == "anthropic/claude-sonnet-4.6"
        assert models[0].get("price_label")
        assert "context_length" in models[0]


class TestPyniaSecrets:
    def test_set_provider_secret_reads_fallback_immediately(self, monkeypatch):
        started = []
        monkeypatch.setattr(
            "src.services.pynia.settings.threading.Thread",
            lambda *args, **kwargs: MagicMock(start=lambda: started.append(1)),
        )
        set_provider_secret("openai", "instant-token")
        from src.services.pynia.settings import get_provider_secret

        assert get_provider_secret("openai") == "instant-token"
        assert started == [1]
        set_provider_secret("openai", "")


class TestPyniaSettings:
    def test_provider_defaults(self):
        assert "openai" in PROVIDERS
        assert PROVIDERS["openai"].auth_kind == "api_token"
        assert PROVIDERS["copilot"].auth_kind == "device_mfa"

    def test_token_storage_roundtrip(self):
        set_provider_secret("openai", "test-token-xyz")
        from src.services.pynia.settings import get_provider_secret

        assert get_provider_secret("openai") == "test-token-xyz"
        set_provider_secret("openai", "")


class TestOpenAIAgentLoop:
    def test_tool_loop_executes_and_continues(self):
        chunks = []
        tool_calls = []
        tool_results = []

        def execute_tool(name, args):
            tool_results.append((name, args))
            return "ok-result"

        sse_lines = [
            'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"id":"c1","function":{"name":"datapyn_notify","arguments":"{\\"title\\":\\"t\\",\\"message\\":\\"hi\\"}"}}]}}]}',
            "data: [DONE]",
        ]

        class FakeResp:
            status_code = 200
            text = ""

            def iter_lines(self):
                for line in sse_lines:
                    yield line.encode("utf-8")

        second_sse = [
            'data: {"choices":[{"delta":{"content":"Done."}}]}',
            "data: [DONE]",
        ]

        call_count = {"n": 0}

        def fake_post(*_args, **_kwargs):
            call_count["n"] += 1
            resp = FakeResp()
            if call_count["n"] == 1:
                resp.iter_lines = lambda: (line.encode("utf-8") for line in sse_lines)
            else:
                resp.iter_lines = lambda: (line.encode("utf-8") for line in second_sse)
            return resp

        with (
            patch("src.services.pynia.agent_loop_policy.FORCE_ANSWER_AFTER_ROUND", 1),
            patch("requests.post", side_effect=fake_post),
        ):
            final = run_openai_agent_turn(
                base_url="https://api.example.com/v1",
                api_key="key",
                model="gpt-4o",
                messages=[{"role": "user", "content": "hello"}],
                tools=[
                    {
                        "type": "function",
                        "function": {
                            "name": "datapyn_notify",
                            "description": "notify",
                            "parameters": {"type": "object", "properties": {}},
                        },
                    }
                ],
                attachments=None,
                execute_tool=execute_tool,
                on_chunk=chunks.append,
                on_tool_call=lambda n, a, i: tool_calls.append((n, a, i)),
                on_tool_result=lambda n, r, i: None,
                is_cancelled=lambda: False,
            )

        assert tool_calls
        assert tool_results
        assert "Done." in final


@pytest.mark.qt
class TestPyniaAgentClient:
    def test_set_provider_emits_signal(self, qtbot):
        from src.services.pynia.agent_client import PyniaAgentClient

        client = PyniaAgentClient()
        start_provider = client.provider_id
        target = "anthropic" if start_provider != "anthropic" else "openai"
        with qtbot.waitSignal(client.provider_changed, timeout=1000):
            client.set_provider(target)
        assert client.provider_id == target
        client.cleanup()
