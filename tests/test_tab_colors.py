#!/usr/bin/env python3
"""
Teste completo do sistema de cores de conexão por aba
"""
import sys
import pytest
from unittest.mock import Mock, patch
from PyQt6.QtWidgets import QApplication, QWidget
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor

from src.ui.components.session_tabs import SessionTabs, SessionTabBar


@pytest.fixture(scope="module")
def qapp():
    """Fixture para instância única do QApplication"""
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


class TestSessionTabBarColors:
    """Testes para o sistema de cores do SessionTabBar"""
    
    def test_tab_colors_initialization(self, qapp):
        """Testa inicialização do sistema de cores"""
        tab_bar = SessionTabBar()
        
        # Verifica se tem o atributo de cores
        assert hasattr(tab_bar, '_tab_colors')
        assert isinstance(tab_bar._tab_colors, dict)
        assert len(tab_bar._tab_colors) == 0
    
    def test_set_tab_connection_color(self, qapp):
        """Testa definição de cor para aba específica"""
        tab_bar = SessionTabBar()
        
        # Define cores para diferentes abas
        tab_bar.set_tab_connection_color(0, '#ff0000')
        tab_bar.set_tab_connection_color(1, '#00ff00')
        tab_bar.set_tab_connection_color(2, '#0000ff')
        
        # Verifica armazenamento correto
        assert tab_bar._tab_colors[0] == '#ff0000'
        assert tab_bar._tab_colors[1] == '#00ff00'
        assert tab_bar._tab_colors[2] == '#0000ff'
        assert len(tab_bar._tab_colors) == 3
    
    def test_clear_tab_connection_color(self, qapp):
        """Testa remoção de cor de aba específica"""
        tab_bar = SessionTabBar()
        
        # Define algumas cores
        tab_bar.set_tab_connection_color(0, '#ff0000')
        tab_bar.set_tab_connection_color(1, '#00ff00')
        tab_bar.set_tab_connection_color(2, '#0000ff')
        
        # Remove cor da aba 1
        tab_bar.clear_tab_connection_color(1)
        
        # Verifica remoção
        assert 1 not in tab_bar._tab_colors
        assert 0 in tab_bar._tab_colors
        assert 2 in tab_bar._tab_colors
        assert len(tab_bar._tab_colors) == 2
    
    def test_clear_nonexistent_color(self, qapp):
        """Testa remoção de cor de aba que não existe"""
        tab_bar = SessionTabBar()
        
        # Tenta remover cor de aba que não existe - não deve dar erro
        tab_bar.clear_tab_connection_color(99)
        assert len(tab_bar._tab_colors) == 0
    
    def test_update_existing_color(self, qapp):
        """Testa atualização de cor existente"""
        tab_bar = SessionTabBar()
        
        # Define cor inicial
        tab_bar.set_tab_connection_color(0, '#ff0000')
        assert tab_bar._tab_colors[0] == '#ff0000'
        
        # Atualiza cor
        tab_bar.set_tab_connection_color(0, '#00ff00')
        assert tab_bar._tab_colors[0] == '#00ff00'
        assert len(tab_bar._tab_colors) == 1


class TestSessionTabsColors:
    """Testes para integração do sistema de cores com SessionTabs"""
    
    def test_session_tabs_color_delegation(self, qapp):
        """Testa se SessionTabs delega corretamente para o TabBar"""
        tabs = SessionTabs()
        
        # Mock do tab_bar para verificar chamadas
        tabs.tab_bar = Mock()
        
        # Chama método do SessionTabs
        tabs.set_tab_connection_color(0, '#ff0000')
        
        # Verifica se delegou para o tab_bar
        tabs.tab_bar.set_tab_connection_color.assert_called_once_with(0, '#ff0000')
    
    def test_remove_session_clears_color(self, qapp):
        """Testa se remover aba limpa a cor automaticamente"""
        tabs = SessionTabs()
        
        # Adiciona algumas abas
        tabs.addTab(QWidget(), "Aba 1")
        tabs.addTab(QWidget(), "Aba 2")
        
        # Mock do clear_tab_connection_color para verificar chamada
        tabs.tab_bar.clear_tab_connection_color = Mock()
        
        # Remove aba
        tabs.remove_session(1)
        
        # Verifica se limpou a cor
        tabs.tab_bar.clear_tab_connection_color.assert_called_once_with(1)


class TestColorPersistence:
    """Testes para persistência das cores durante operações"""
    
    def test_colors_persist_across_operations(self, qapp):
        """Testa se cores persistem durante operações normais"""
        tab_bar = SessionTabBar()
        
        # Define cores
        colors = {0: '#ff0000', 1: '#00ff00', 2: '#0000ff'}
        for idx, color in colors.items():
            tab_bar.set_tab_connection_color(idx, color)
        
        # Simula mudança de aba ativa (não deve afetar cores)
        original_colors = tab_bar._tab_colors.copy()
        
        # Verifica se cores persistiram
        assert tab_bar._tab_colors == original_colors
        
        # Remove uma cor e verifica se outras persistem
        tab_bar.clear_tab_connection_color(1)
        expected = {0: '#ff0000', 2: '#0000ff'}
        assert tab_bar._tab_colors == expected


class TestVisualIntegration:
    """Testes para integração visual das cores"""
    
    @patch('PyQt6.QtGui.QPainter')
    def test_paint_event_handles_colors(self, mock_painter, qapp):
        """Testa se paintEvent maneja as cores corretamente"""
        tab_bar = SessionTabBar()
        
        # Define algumas cores
        tab_bar.set_tab_connection_color(0, '#ff0000')
        tab_bar.set_tab_connection_color(1, '#00ff00')
        
        # Mock do painter e rect
        mock_painter_instance = Mock()
        mock_painter.return_value.__enter__.return_value = mock_painter_instance
        
        # Mock do tabRect para retornar rect válido
        tab_bar.tabRect = Mock(return_value=Mock(isValid=Mock(return_value=True),
                                               left=Mock(return_value=0),
                                               right=Mock(return_value=100),
                                               bottom=Mock(return_value=30)))
        tab_bar.count = Mock(return_value=2)
        tab_bar.rect = Mock(return_value=Mock())
        
        # Mock do paintEvent pai
        with patch.object(SessionTabBar.__bases__[0], 'paintEvent'):
            # Simula evento de pintura
            from PyQt6.QtGui import QPaintEvent
            paint_event = Mock(spec=QPaintEvent)
            
            # Não deve dar erro
            try:
                tab_bar.paintEvent(paint_event)
                success = True
            except Exception as e:
                print(f"Erro no paintEvent: {e}")
                success = False
            
            assert success, "paintEvent deve executar sem erro"


if __name__ == '__main__':
    pytest.main([__file__, '-v'])