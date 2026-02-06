"""
Testes para PanelManager

Cobre: criacao/remocao de paineis por sessao,
troca de sessao, visibilidade, tamanhos minimos.
"""
import pytest
from unittest.mock import MagicMock, patch
from PyQt6.QtWidgets import QStackedWidget, QDockWidget, QWidget, QMainWindow
from PyQt6.QtCore import Qt
from src.services.panel_manager import PanelManager, PanelSet


@pytest.fixture
def panel_manager(qtbot):
    """PanelManager configurado com stacks e docks mock"""
    pm = PanelManager()
    
    # Criar main window temporaria para hospedar docks
    main = QMainWindow()
    qtbot.addWidget(main)
    main.show()
    qtbot.waitExposed(main)
    
    results_stack = QStackedWidget()
    output_stack = QStackedWidget()
    variables_stack = QStackedWidget()
    
    results_dock = QDockWidget("Results", main)
    output_dock = QDockWidget("Output", main)
    variables_dock = QDockWidget("Variables", main)
    
    results_dock.setWidget(results_stack)
    output_dock.setWidget(output_stack)
    variables_dock.setWidget(variables_stack)
    
    main.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, results_dock)
    main.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, output_dock)
    main.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, variables_dock)
    
    pm.setup(
        results_stack=results_stack,
        output_stack=output_stack,
        variables_stack=variables_stack,
        results_dock=results_dock,
        output_dock=output_dock,
        variables_dock=variables_dock,
        results_factory=lambda: QWidget(),
        output_factory=lambda: QWidget(),
        variables_factory=lambda: QWidget(),
    )
    
    pm._main = main
    return pm


class TestPanelManagerCreation:
    """Testes de criacao de paineis"""
    
    def test_create_panels_returns_panel_set(self, panel_manager):
        """Criar paineis retorna PanelSet"""
        ps = panel_manager.create_panels("session_1")
        
        assert isinstance(ps, PanelSet)
        assert ps.results is not None
        assert ps.output is not None
        assert ps.variables is not None
    
    def test_create_panels_adds_to_stacks(self, panel_manager):
        """Paineis adicionados aos stacks"""
        ps = panel_manager.create_panels("session_1")
        
        assert ps.results_idx >= 0
        assert ps.output_idx >= 0
        assert ps.variables_idx >= 0
    
    def test_create_panels_idempotent(self, panel_manager):
        """Criar paineis para mesma sessao retorna mesmo set"""
        ps1 = panel_manager.create_panels("session_1")
        ps2 = panel_manager.create_panels("session_1")
        
        assert ps1 is ps2
    
    def test_create_multiple_session_panels(self, panel_manager):
        """Criar paineis para multiplas sessoes"""
        ps1 = panel_manager.create_panels("session_1")
        ps2 = panel_manager.create_panels("session_2")
        
        assert ps1 is not ps2
        assert ps1.results is not ps2.results
        assert ps1.output is not ps2.output


class TestPanelManagerRemoval:
    """Testes de remocao de paineis"""
    
    def test_remove_panels(self, panel_manager):
        """Remover paineis de uma sessao"""
        panel_manager.create_panels("session_1")
        assert panel_manager.has_panels
        
        panel_manager.remove_panels("session_1")
        assert not panel_manager.has_panels
    
    def test_remove_nonexistent_panels(self, panel_manager):
        """Remover paineis inexistentes nao causa erro"""
        panel_manager.remove_panels("nonexistent")
    
    def test_remove_clears_active(self, panel_manager):
        """Remover sessao ativa limpa referencia"""
        panel_manager.create_panels("session_1")
        panel_manager.switch_to("session_1")
        assert panel_manager.active_session_id == "session_1"
        
        panel_manager.remove_panels("session_1")
        assert panel_manager.active_session_id is None


class TestPanelManagerSwitching:
    """Testes de troca de paineis"""
    
    def test_switch_to_session(self, panel_manager):
        """Trocar para sessao existente"""
        panel_manager.create_panels("session_1")
        panel_manager.create_panels("session_2")
        
        panel_manager.switch_to("session_1")
        assert panel_manager.active_session_id == "session_1"
        
        panel_manager.switch_to("session_2")
        assert panel_manager.active_session_id == "session_2"
    
    def test_switch_to_nonexistent(self, panel_manager):
        """Trocar para sessao inexistente nao altera estado"""
        panel_manager.create_panels("session_1")
        panel_manager.switch_to("session_1")
        
        panel_manager.switch_to("nonexistent")
        # Nao muda o ativo
        assert panel_manager.active_session_id == "session_1"
    
    def test_active_panels_after_switch(self, panel_manager):
        """Paineis ativos corretos apos troca"""
        ps1 = panel_manager.create_panels("session_1")
        ps2 = panel_manager.create_panels("session_2")
        
        panel_manager.switch_to("session_1")
        assert panel_manager.active_results is ps1.results
        assert panel_manager.active_output is ps1.output
        assert panel_manager.active_variables is ps1.variables
        
        panel_manager.switch_to("session_2")
        assert panel_manager.active_results is ps2.results
        assert panel_manager.active_output is ps2.output
        assert panel_manager.active_variables is ps2.variables


class TestPanelManagerVisibility:
    """Testes de visibilidade dos paineis"""
    
    def test_hide_all(self, panel_manager):
        """Esconder todos os docks"""
        panel_manager.hide_all()
        
        assert not panel_manager._results_dock.isVisible()
        assert not panel_manager._output_dock.isVisible()
        assert not panel_manager._variables_dock.isVisible()
    
    def test_show_all(self, panel_manager):
        """Mostrar todos os docks"""
        panel_manager.hide_all()
        panel_manager.show_all()
        
        assert panel_manager._results_dock.isVisible()
        assert panel_manager._output_dock.isVisible()
        assert panel_manager._variables_dock.isVisible()
    
    def test_show_panel_by_name(self, panel_manager):
        """Mostrar painel especifico por nome"""
        panel_manager.hide_all()
        
        panel_manager.show_panel('results')
        assert panel_manager._results_dock.isVisible()


class TestPanelManagerSizes:
    """Testes de tamanhos minimos"""
    
    def test_minimum_dock_height(self, panel_manager):
        """Docks tem altura minima"""
        assert panel_manager._results_dock.minimumHeight() >= PanelManager.MIN_DOCK_HEIGHT
        assert panel_manager._output_dock.minimumHeight() >= PanelManager.MIN_DOCK_HEIGHT
    
    def test_minimum_dock_width_variables(self, panel_manager):
        """Dock de variaveis tem largura minima"""
        assert panel_manager._variables_dock.minimumWidth() >= PanelManager.MIN_DOCK_WIDTH


class TestPanelManagerCleanup:
    """Testes de cleanup"""
    
    def test_cleanup_removes_all(self, panel_manager):
        """Cleanup remove todos os paineis"""
        panel_manager.create_panels("session_1")
        panel_manager.create_panels("session_2")
        panel_manager.create_panels("session_3")
        
        panel_manager.cleanup()
        assert not panel_manager.has_panels
    
    def test_get_panels_by_session(self, panel_manager):
        """Buscar paineis por session_id"""
        ps1 = panel_manager.create_panels("session_1")
        
        found = panel_manager.get_panels("session_1")
        assert found is ps1
        
        not_found = panel_manager.get_panels("nonexistent")
        assert not_found is None
