"""Tests for the shared parameter delimiter settings layer."""

from __future__ import annotations

from PyQt6.QtCore import QSettings

from src.core.parameter_settings import (
    DEFAULT_SHARED_PARAMETER_DELIMITER,
    SHARED_PARAMETER_DELIMITERS,
    get_shared_parameter_delimiter,
    get_shared_parameter_delimiter_tokens,
    set_shared_parameter_delimiter,
)


def _clear_setting():
    QSettings("DataPyn", "DataPyn").remove("parameters/shared_delimiter")


def test_default_is_double_brace(qtbot):
    _clear_setting()
    assert get_shared_parameter_delimiter() == DEFAULT_SHARED_PARAMETER_DELIMITER
    assert get_shared_parameter_delimiter() == "double_brace"


def test_tokens_match_double_brace_preset_by_default(qtbot):
    _clear_setting()
    assert get_shared_parameter_delimiter_tokens() == ("{{", "}}")


def test_set_and_get_round_trip(qtbot):
    _clear_setting()
    set_shared_parameter_delimiter("double_colon")
    assert get_shared_parameter_delimiter() == "double_colon"
    assert get_shared_parameter_delimiter_tokens() == ("::", "::")
    _clear_setting()


def test_single_brace_round_trip(qtbot):
    _clear_setting()
    set_shared_parameter_delimiter("single_brace")
    assert get_shared_parameter_delimiter() == "single_brace"
    assert get_shared_parameter_delimiter_tokens() == ("{", "}")
    _clear_setting()


def test_unknown_key_falls_back_to_default(qtbot):
    _clear_setting()
    QSettings("DataPyn", "DataPyn").setValue(
        "parameters/shared_delimiter", "bogus_preset"
    )
    assert get_shared_parameter_delimiter() == DEFAULT_SHARED_PARAMETER_DELIMITER
    assert get_shared_parameter_delimiter_tokens() == ("{{", "}}")
    _clear_setting()


def test_set_unknown_key_persists_default(qtbot):
    _clear_setting()
    set_shared_parameter_delimiter("bogus_preset")
    assert get_shared_parameter_delimiter() == DEFAULT_SHARED_PARAMETER_DELIMITER
    _clear_setting()


def test_all_presets_have_symmetric_tokens(qtbot):
    for open_t, close_t in SHARED_PARAMETER_DELIMITERS.values():
        assert open_t, "open token must be non-empty"
        assert close_t, "close token must be non-empty"
