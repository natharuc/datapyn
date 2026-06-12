"""Regression: frameless dialogs must survive open/close cycles."""

from PyQt6.QtWidgets import QDialog, QMainWindow, QVBoxLayout, QWidget

from src.design_system.frameless_dialog import install_frameless_shell


def _open_and_close_settings_like_dialog(window, qapp):
    dialog = QDialog(window)
    install_frameless_shell(dialog, "Settings", min_width=400, min_height=300)
    dialog.show()
    qapp.processEvents()
    backdrop = window.findChild(QWidget, "modalBackdrop")
    assert backdrop is not None
    assert backdrop.isVisible()
    dialog.close()
    qapp.processEvents()
    assert window.findChild(QWidget, "modalBackdrop") is None


def test_frameless_dialog_reopens_without_backdrop_leak(qapp):
    window = QMainWindow()
    window.setCentralWidget(QWidget())
    window.resize(800, 600)
    window.show()
    qapp.processEvents()

    _open_and_close_settings_like_dialog(window, qapp)
    _open_and_close_settings_like_dialog(window, qapp)

    window.close()


def test_backdrop_not_shown_after_rapid_close(qapp):
    """Pending show timer must not resurrect backdrop after the dialog closed."""
    window = QMainWindow()
    window.setCentralWidget(QWidget())
    window.resize(800, 600)
    window.show()
    qapp.processEvents()

    dialog = QDialog(window)
    install_frameless_shell(dialog, "Rapid", min_width=320, min_height=160)
    dialog.show()
    qapp.processEvents()
    dialog.close()
    qapp.processEvents()
    assert window.findChild(QWidget, "modalBackdrop") is None

    # Process any deferred backdrop show from the first dialog.
    qapp.processEvents()
    assert window.findChild(QWidget, "modalBackdrop") is None

    window.close()
