"""Tests for GitHub account discovery and picker payload."""

from unittest.mock import patch

from src.services.copilot.copilot_accounts import (
    build_account_picker_payload,
    normalize_known_accounts,
)


class TestNormalizeKnownAccounts:
    def test_deduplicates_and_normalizes(self):
        raw = [
            {"username": "alice", "last_used": "2026-01-02T00:00:00Z"},
            {"username": "alice", "last_used": "2026-01-03T00:00:00Z"},
            {"username": "", "last_used": "2026-01-01T00:00:00Z"},
            "invalid",
        ]
        result = normalize_known_accounts(raw)
        assert len(result) == 1
        assert result[0]["username"] == "alice"


class TestBuildAccountPickerPayload:
    def test_merges_datapyn_history_with_gh_accounts(self):
        known = [{"username": "old-user", "last_used": "2026-01-01T00:00:00Z"}]
        gh_accounts = [
            {"username": "alice", "ready": True, "active": True},
            {"username": "bob", "ready": False, "active": False},
        ]
        payload = build_account_picker_payload(
            known,
            current_username="alice",
            gh_accounts=gh_accounts,
        )
        by_user = {item["username"]: item for item in payload["accounts"]}
        assert payload["current"] == "alice"
        assert by_user["alice"]["ready"] is True
        assert by_user["alice"]["active"] is True
        assert by_user["bob"]["ready"] is False
        assert by_user["old-user"]["ready"] is False
        assert by_user["old-user"]["source"] == "datapyn"

    def test_current_user_is_first(self):
        gh_accounts = [
            {"username": "alice", "ready": True, "active": False},
            {"username": "bob", "ready": True, "active": True},
        ]
        payload = build_account_picker_payload(
            [{"username": "alice", "last_used": "2026-01-01T00:00:00Z"}],
            current_username="alice",
            gh_accounts=gh_accounts,
        )
        assert payload["accounts"][0]["username"] == "alice"


class TestPrepareChatAccountSwitch:
    def test_marks_selected_account_for_reconnect(self):
        from src.services.copilot.copilot_auth_service import CopilotAuthService

        auth = CopilotAuthService()
        settings = auth._settings
        gh_accounts = [{"username": "alice", "ready": True, "active": True}]

        with patch("src.services.copilot.copilot_accounts.list_gh_accounts", return_value=gh_accounts):
            with patch.object(settings, "mark_chat_account_selected") as mark_selected:
                ok, message, mode = auth.prepare_chat_account_switch("alice")

        assert ok is True
        assert message == ""
        assert mode == "reconnect"
        mark_selected.assert_called_once_with("alice")
