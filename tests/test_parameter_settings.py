"""Tests for the shared parameter delimiter settings layer."""

from __future__ import annotations

from PyQt6.QtCore import QSettings

from src.core.parameter_settings import (
    DEFAULT_SHARED_PARAMETER_DELIMITER,
    get_shared_parameter_delimiter,
    get_shared_parameter_delimiter_tokens,
    parse_delimiter_template,
    set_shared_parameter_delimiter,
)


def _clear_setting():
    QSettings("DataPyn", "DataPyn").remove("parameters/shared_delimiter")


def test_default_is_double_brace_template(qtbot):
    _clear_setting()
    assert get_shared_parameter_delimiter() == DEFAULT_SHARED_PARAMETER_DELIMITER
    assert get_shared_parameter_delimiter() == "{{name}}"


def test_tokens_match_double_brace_by_default(qtbot):
    _clear_setting()
    assert get_shared_parameter_delimiter_tokens() == ("{{", "}}")


def test_set_and_get_round_trip(qtbot):
    _clear_setting()
    set_shared_parameter_delimiter("::name::")
    assert get_shared_parameter_delimiter() == "::name::"
    assert get_shared_parameter_delimiter_tokens() == ("::", "::")
    _clear_setting()


def test_single_brace_round_trip(qtbot):
    _clear_setting()
    set_shared_parameter_delimiter("{name}")
    assert get_shared_parameter_delimiter() == "{name}"
    assert get_shared_parameter_delimiter_tokens() == ("{", "}")
    _clear_setting()


def test_custom_delimiter_round_trip(qtbot):
    _clear_setting()
    set_shared_parameter_delimiter("$name$")
    assert get_shared_parameter_delimiter() == "$name$"
    assert get_shared_parameter_delimiter_tokens() == ("$", "$")
    _clear_setting()


def test_legacy_preset_key_migrated_on_read(qtbot):
    _clear_setting()
    QSettings("DataPyn", "DataPyn").setValue(
        "parameters/shared_delimiter", "double_colon"
    )
    assert get_shared_parameter_delimiter() == "::name::"
    assert get_shared_parameter_delimiter_tokens() == ("::", "::")
    _clear_setting()


def test_invalid_template_tokens_fall_back_to_default(qtbot):
    _clear_setting()
    set_shared_parameter_delimiter("bogus")
    assert get_shared_parameter_delimiter() == "bogus"
    assert get_shared_parameter_delimiter_tokens() == ("{{", "}}")
    _clear_setting()


def test_empty_value_falls_back_to_default(qtbot):
    _clear_setting()
    set_shared_parameter_delimiter("")
    assert get_shared_parameter_delimiter() == DEFAULT_SHARED_PARAMETER_DELIMITER
    _clear_setting()


def test_parse_delimiter_template(qtbot):
    assert parse_delimiter_template("{{name}}") == ("{{", "}}")
    assert parse_delimiter_template("{name}") == ("{", "}")
    assert parse_delimiter_template("::name::") == ("::", "::")
    assert parse_delimiter_template("name") is None
    assert parse_delimiter_template("{{name") is None
    assert parse_delimiter_template("{{name}}{{name}}") is None
