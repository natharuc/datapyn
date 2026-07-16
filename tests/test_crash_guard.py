"""Crash guard — global exception interceptor tests."""

import sys
import threading

import pytest


def test_install_sets_excepthooks(qapp):
    from src.core import crash_guard

    crash_guard._installed = False
    crash_guard.install_crash_guard(qapp)

    assert sys.excepthook is crash_guard._handle_exception
    assert threading.excepthook is crash_guard._thread_excepthook
    assert crash_guard._installed is True

    # Idempotent.
    crash_guard.install_crash_guard(qapp)
    assert crash_guard._installed is True

    crash_guard._installed = False
    crash_guard._app_ref = None
    sys.excepthook = sys.__excepthook__
    try:
        threading.excepthook = threading.__excepthook__
    except Exception:
        pass


def test_signature_is_stable_across_line_numbers():
    from src.core import crash_guard

    tb_a = (
        'Traceback (most recent call last):\n'
        '  File "source/foo.py", line 12, in bar\n'
        '    raise ValueError("boom")\n'
        'ValueError: boom\n'
    )
    tb_b = (
        'Traceback (most recent call last):\n'
        '  File "source/foo.py", line 999, in bar\n'
        '    raise ValueError("boom")\n'
        'ValueError: boom\n'
    )
    assert crash_guard._signature(tb_a) == crash_guard._signature(tb_b)


def test_signature_differs_for_different_files():
    from src.core import crash_guard

    tb_a = 'File "source/foo.py", line 1, in bar\nValueError: boom\n'
    tb_b = 'File "source/other.py", line 1, in bar\nValueError: boom\n'
    assert crash_guard._signature(tb_a) != crash_guard._signature(tb_b)


def test_handle_exception_records_and_schedules_dialog(qapp, monkeypatch):
    from src.core import crash_guard

    crash_guard._installed = False
    crash_guard.install_crash_guard(qapp)

    recorded = []
    scheduled = []

    monkeypatch.setattr(crash_guard, "_record_crash", lambda *a, **k: recorded.append((a, k)))
    monkeypatch.setattr(crash_guard, "_show_crash_dialog_on_ui", lambda *a: scheduled.append(a))

    try:
        raise RuntimeError("kaboom")
    except RuntimeError:
        crash_guard._handle_exception(*sys.exc_info())

    assert len(recorded) == 1
    assert len(scheduled) == 1
    assert "RuntimeError: kaboom" in scheduled[0][0]

    crash_guard._installed = False
    crash_guard._app_ref = None
    sys.excepthook = sys.__excepthook__
    try:
        threading.excepthook = threading.__excepthook__
    except Exception:
        pass


def test_notify_wrapper_records_and_returns_false(qapp, monkeypatch):
    from src.core import crash_guard

    def fake_notify(self, receiver, event):
        raise RuntimeError("notify boom")

    recorded = []
    monkeypatch.setattr(crash_guard, "_record_crash", lambda *a, **k: recorded.append((a, k)))
    monkeypatch.setattr(crash_guard, "_show_crash_dialog_on_ui", lambda *a: None)

    wrapper = crash_guard._make_notify_wrapper(fake_notify)
    result = wrapper(qapp, None, None)

    assert result is False
    assert len(recorded) == 1
    assert recorded[0][1]["source"] == "QApplication.notify"
