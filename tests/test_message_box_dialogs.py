"""Tests for frameless message box shortcuts and repeat-checkbox UX."""

from unittest.mock import patch

from PyQt6.QtGui import QKeySequence, QShortcut
from PyQt6.QtWidgets import QDialog

from src.design_system.message_box import ask_save_discard_cancel, ask_yes_no


def test_ask_yes_no_binds_n_y_and_s_shortcuts(qapp):
    sequences = []
    real_init = QShortcut.__init__

    def capture_init(self, sequence, parent, *args, **kwargs):
        real_init(self, sequence, parent, *args, **kwargs)
        sequences.append(QKeySequence(sequence).toString())

    with patch.object(QShortcut, "__init__", capture_init):
        with patch.object(QDialog, "exec", return_value=QDialog.DialogCode.Rejected):
            ask_yes_no(None, "Close tab?", "Are you sure?")

    assert "N" in sequences
    assert "Y" in sequences
    assert "S" in sequences


def test_ask_yes_no_repeat_checkbox_returns_tuple(qapp):
    with patch.object(QDialog, "exec", return_value=QDialog.DialogCode.Rejected):
        result, checked = ask_yes_no(
            None,
            "Close tab?",
            "Are you sure?",
            repeat_checkbox_label="Apply to all tabs",
        )
    assert result is False
    assert checked is False


def test_ask_save_discard_cancel_repeat_checkbox_returns_tuple(qapp):
    with patch.object(QDialog, "exec", return_value=QDialog.DialogCode.Accepted):
        result, checked = ask_save_discard_cancel(
            None,
            "Unsaved",
            "Save changes?",
            repeat_checkbox_label="Apply to all tabs",
        )
    assert result == "cancel"
    assert checked is False


def test_ask_save_discard_cancel_without_checkbox_returns_plain_value(qapp):
    with patch.object(QDialog, "exec", return_value=QDialog.DialogCode.Rejected):
        result = ask_save_discard_cancel(None, "Unsaved", "Save changes?")
    assert result == "cancel"
