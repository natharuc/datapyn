"""Tests for single-instance file forwarding."""

from __future__ import annotations

import json

from src.services.single_instance import (
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
