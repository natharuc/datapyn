"""Tests for Pynia brand asset helpers."""

from src.assets.pynia_branding import (
    PYNIA_LOGO_PATH,
    load_pynia_icon,
    load_pynia_logo,
    pynia_logo_data_uri,
)


def test_pynia_logo_file_exists():
    assert PYNIA_LOGO_PATH.is_file()


def test_load_pynia_logo_returns_icon(qapp):
    icon = load_pynia_logo(32)
    assert icon is not None
    assert not icon.pixmap(32, 32).isNull()


def test_pynia_logo_data_uri():
    uri = pynia_logo_data_uri()
    assert uri.startswith("data:image/svg+xml;base64,")


def test_load_pynia_icon_prefers_logo(qapp):
    icon = load_pynia_icon(24)
    assert icon is not None
