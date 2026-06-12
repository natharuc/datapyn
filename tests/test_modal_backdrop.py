"""Tests for modal dialog backdrop overlay."""

from PyQt6.QtWidgets import QDialog, QMainWindow, QVBoxLayout, QWidget

from src.design_system.frameless_dialog import install_frameless_shell


def test_modal_backdrop_shows_with_parent(qapp):
    window = QMainWindow()
    body = QWidget()
    window.setCentralWidget(body)
    window.resize(640, 480)
    window.show()
    qapp.processEvents()

    dialog = QDialog(window)
    install_frameless_shell(dialog, "Test", min_width=320, min_height=160)
    dialog.show()
    qapp.processEvents()

    backdrop = window.findChild(QWidget, "modalBackdrop")
    assert backdrop is not None
    assert backdrop.isVisible()

    dialog.close()
    qapp.processEvents()
    assert window.findChild(QWidget, "modalBackdrop") is None

    window.close()
