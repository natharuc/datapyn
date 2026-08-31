"""Tests for single-instance file forwarding."""

from __future__ import annotations

import json
from unittest.mock import MagicMock

from src.services.single_instance import (
    _CONNECT_MS,
    decode_open_files_message,
    encode_open_files_message,
    single_instance_socket_name,
)


class TestSingleInstanceMessages:
    def test_roundtrip_paths_and_focus(self):
        raw = encode_open_files_message([r"C:\work\foo.dpw", r"D:\bar.sql"], focus=True)
        paths, focus = decode_open_files_message(raw)
        assert paths == [r"C:\work\foo.dpw", r"D:\bar.sql"]
        assert focus is True

    def test_decode_empty_payload(self):
        paths, focus = decode_open_files_message(b"")
        assert paths == []
        assert focus is True

    def test_decode_ignores_empty_path_entries(self):
        raw = json.dumps({"paths": ["", "ok.dpw"], "focus": False}).encode("utf-8")
        paths, focus = decode_open_files_message(raw)
        assert paths == ["ok.dpw"]
        assert focus is False


class TestSingleInstanceSocketName:
    def test_socket_name_is_stable_string(self):
        name = single_instance_socket_name()
        assert name.startswith("datapyn-ide-")
        assert single_instance_socket_name() == name

    def test_connect_timeout_is_short_for_cold_start(self):
        assert _CONNECT_MS <= 250


class TestSecondInstanceFocus:
    def test_focus_callback_uses_focus_window_not_show_normal(self):
        """Second-instance focus must keep maximized geometry (no showNormal)."""
        window = MagicMock()

        def _on_second_instance(paths: list[str], focus: bool) -> None:
            if paths:
                window.open_startup_files(paths)
            if focus:
                window._focus_window()

        _on_second_instance([], True)
        window._focus_window.assert_called_once_with()
        window.showNormal.assert_not_called()
        window.open_startup_files.assert_not_called()

        window.reset_mock()
        _on_second_instance([r"C:\a.sql"], True)
        window.open_startup_files.assert_called_once_with([r"C:\a.sql"])
        window._focus_window.assert_called_once_with()
        window.showNormal.assert_not_called()

    def test_main_second_instance_handler_does_not_call_show_normal(self):
        from pathlib import Path

        text = Path("source/main.py").read_text(encoding="utf-8")
        start = text.index("def _on_second_instance")
        end = text.index("install_single_instance_server(app", start)
        snippet = text[start:end]
        assert "window._focus_window()" in snippet
        assert "window.showNormal" not in snippet

    def test_main_opens_cli_files_before_deferred_restore(self):
        from pathlib import Path

        text = Path("source/main.py").read_text(encoding="utf-8")
        assert "defer_session_restore=bool(startup_files)" in text
        assert "delay_ms=0" in text
        open_at = text.index("window.open_startup_files(startup_files)")
        restore_at = text.index("window._restore_sessions()")
        assert open_at < restore_at
