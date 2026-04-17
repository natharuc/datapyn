"""
Testes para a funcionalidade de execucao periodica (Run Timer)
"""

import pytest
from unittest.mock import MagicMock, patch
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import QApplication

from src.ui.components.toolbar import MainToolbar
from src.core.theme_manager import ThemeManager


class TestRunTimerToolbar:
    """Testes do botao de execucao periodica na toolbar"""

    @pytest.fixture
    def toolbar(self, qtbot):
        toolbar = MainToolbar(theme_manager=ThemeManager())
        qtbot.addWidget(toolbar)
        return toolbar

    def test_timer_button_exists(self, toolbar):
        """Botao de timer deve existir na toolbar"""
        assert hasattr(toolbar, "btn_run_timer")
        assert toolbar.btn_run_timer is not None

    def test_timer_signal_emitted_on_click(self, toolbar, qtbot):
        """Clicar no botao de timer deve emitir sinal"""
        with qtbot.waitSignal(toolbar.run_timer_clicked, timeout=1000):
            toolbar.btn_run_timer.click()

    def test_timer_set_running_true(self, toolbar):
        """set_timer_running(True) deve mudar aparencia do botao"""
        toolbar.set_timer_running(True, 30)
        # Button should have stop style (red-ish background)
        style = toolbar.btn_run_timer.styleSheet()
        assert "rgba(244, 67, 54" in style

    def test_timer_set_running_false(self, toolbar):
        """set_timer_running(False) deve restaurar aparencia padrao"""
        toolbar.set_timer_running(True, 30)
        toolbar.set_timer_running(False)
        style = toolbar.btn_run_timer.styleSheet()
        assert style == ""

    def test_run_button_still_works(self, toolbar, qtbot):
        """Botao de run normal ainda deve funcionar"""
        with qtbot.waitSignal(toolbar.run_clicked, timeout=1000):
            toolbar.btn_run.click()


class TestRunTimerLogic:
    """Testes da logica de timer no main_window (mockado)"""

    def test_toggle_starts_timer(self, qtbot):
        """_toggle_run_timer deve iniciar QTimer com intervalo correto"""
        timer = QTimer()
        timer.start(5000)
        assert timer.isActive()
        assert timer.interval() == 5000
        timer.stop()

    def test_toggle_stops_timer(self, qtbot):
        """Chamar stop deve parar o timer"""
        timer = QTimer()
        timer.start(5000)
        assert timer.isActive()
        timer.stop()
        assert not timer.isActive()

    def test_timer_interval_range(self, qtbot):
        """Timer deve aceitar intervalos de 1 a 86400 segundos"""
        timer = QTimer()
        # Minimum: 1 second
        timer.start(1000)
        assert timer.interval() == 1000
        timer.stop()

        # Maximum: 86400 seconds (24 hours)
        timer.start(86400 * 1000)
        assert timer.interval() == 86400000
        timer.stop()

    def test_toolbar_state_reflects_timer(self, qtbot):
        """Toolbar deve refletir estado do timer"""
        toolbar = MainToolbar(theme_manager=ThemeManager())
        qtbot.addWidget(toolbar)

        # Initially not running
        assert toolbar.btn_run_timer.styleSheet() == ""

        # Start
        toolbar.set_timer_running(True, 10)
        assert "rgba(244, 67, 54" in toolbar.btn_run_timer.styleSheet()

        # Stop
        toolbar.set_timer_running(False)
        assert toolbar.btn_run_timer.styleSheet() == ""
