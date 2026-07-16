"""Crash reporter service — gh dedupe / create / browser fallback tests."""

from unittest.mock import patch

import pytest


def test_browser_fallback_when_gh_missing():
    from src.services import crash_reporter_service as svc

    with (
        patch.object(svc, "_gh_executable", return_value=""),
        patch.object(svc, "_browser_fallback", return_value="https://example/issue") as fb,
    ):
        url, error = svc.report_crash(
            traceback_text="tb", signature="abc123", summary="Boom"
        )

    assert url == "https://example/issue"
    assert error is None
    fb.assert_called_once()
    title, body = fb.call_args.args
    assert "datapyn-crash:abc123" in title
    assert body == "tb"


def test_browser_fallback_when_gh_not_logged_in():
    from src.services import crash_reporter_service as svc

    with (
        patch.object(svc, "_gh_executable", return_value="/usr/bin/gh"),
        patch.object(svc, "_is_gh_logged_in", return_value=False),
        patch.object(svc, "_browser_fallback", return_value="https://example/issue") as fb,
    ):
        url, error = svc.report_crash(
            traceback_text="tb", signature="abc123", summary="Boom"
        )

    assert url == "https://example/issue"
    assert error is None
    fb.assert_called_once()


def test_dedupe_comments_on_existing_issue():
    from src.services import crash_reporter_service as svc

    with (
        patch.object(svc, "_gh_executable", return_value="/usr/bin/gh"),
        patch.object(svc, "_is_gh_logged_in", return_value=True),
        patch.object(svc, "_find_existing_issue", return_value=42),
        patch.object(svc, "_comment_issue", return_value="https://github.com/natharuc/datapyn/issues/42") as comment,
        patch.object(svc, "_create_issue") as create,
    ):
        url, error = svc.report_crash(
            traceback_text="tb", signature="abc123", summary="Boom"
        )

    assert url == "https://github.com/natharuc/datapyn/issues/42"
    assert error is None
    comment.assert_called_once()
    create.assert_not_called()
    # The comment body must include the signature marker.
    assert "datapyn-crash:abc123" in comment.call_args.args[1]


def test_creates_new_issue_when_no_match():
    from src.services import crash_reporter_service as svc

    with (
        patch.object(svc, "_gh_executable", return_value="/usr/bin/gh"),
        patch.object(svc, "_is_gh_logged_in", return_value=True),
        patch.object(svc, "_find_existing_issue", return_value=None),
        patch.object(svc, "_create_issue", return_value="https://github.com/natharuc/datapyn/issues/7") as create,
        patch.object(svc, "_comment_issue") as comment,
    ):
        url, error = svc.report_crash(
            traceback_text="tb", signature="abc123", summary="Boom"
        )

    assert url == "https://github.com/natharuc/datapyn/issues/7"
    assert error is None
    create.assert_called_once()
    comment.assert_not_called()
    title, body = create.call_args.args
    assert "datapyn-crash:abc123" in title
    assert body == "tb"


def test_browser_fallback_when_create_fails():
    from src.services import crash_reporter_service as svc

    with (
        patch.object(svc, "_gh_executable", return_value="/usr/bin/gh"),
        patch.object(svc, "_is_gh_logged_in", return_value=True),
        patch.object(svc, "_find_existing_issue", return_value=None),
        patch.object(svc, "_create_issue", return_value=None),
        patch.object(svc, "_browser_fallback", return_value="https://example/issue") as fb,
    ):
        url, error = svc.report_crash(
            traceback_text="tb", signature="abc123", summary="Boom"
        )

    assert url == "https://example/issue"
    assert error is None
    fb.assert_called_once()


def test_browser_fallback_url_is_quoted():
    from src.services import crash_reporter_service as svc

    with patch.object(svc.webbrowser, "open") as wb:
        url = svc._browser_fallback("Boom [x]", "line 1\nline 2")

    assert "github.com/natharuc/datapyn/issues/new" in url
    assert "title=Boom%20%5Bx%5D" in url
    wb.assert_called_once_with(url)
