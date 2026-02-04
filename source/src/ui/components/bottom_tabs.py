"""
Bottom Tabs - Container de abas inferiores

Contém as abas de Resultados, Output e Variáveis.
"""
from PyQt6.QtWidgets import QTabWidget, QWidget
from PyQt6.QtCore import pyqtSignal
import qtawesome as qta
from typing import Optional
import pandas as pd

from .results_viewer import ResultsViewer
from .output_panel import OutputPanel
from .variables_panel import VariablesPanel


class BottomTabs(QTabWidget):
    """Container com abas de resultados, output e variáveis"""
    
    # Sinais
    tab_changed = pyqtSignal(int)  # index
    
    def __init__(self, theme_manager=None, parent=None):
        super().__init__(parent)
        
        self.theme_manager = theme_manager
        self._setup_ui()
        self._setup_style()
        self._connect_signals()
    
    def _setup_ui(self):
        """Configura UI"""
        # Tab: Resultados
        self.results_viewer = ResultsViewer(theme_manager=self.theme_manager)
        self.addTab(self.results_viewer, "Resultados")
        self.setTabIcon(0, qta.icon('mdi.table-eye', color='#64b5f6'))
        
        # Tab: Output/Logs
        self.output_panel = OutputPanel(theme_manager=self.theme_manager)
        self.addTab(self.output_panel, "Output")
        self.setTabIcon(1, qta.icon('mdi.console', color='#64b5f6'))
        
        # Tab: Variáveis
        self.variables_panel = VariablesPanel(theme_manager=self.theme_manager)
        self.addTab(self.variables_panel, "Variáveis")
        self.setTabIcon(2, qta.icon('mdi.variable', color='#64b5f6'))
    
    def _setup_style(self):
        """Configura estilo"""
        self._apply_theme()
    
    def _apply_theme(self):
        """Aplica o tema atual"""
        if self.theme_manager:
            colors = self.theme_manager.get_app_colors()
            bg = colors.get('background', '#1e1e1e')
            fg = colors.get('foreground', '#d4d4d4')
            border = colors.get('border', '#3e3e42')
            secondary = colors.get('secondary', '#2d2d30')
        else:
            bg = '#1e1e1e'
            fg = '#d4d4d4'
            border = '#3e3e42'
            secondary = '#2d2d30'
        
        self.setStyleSheet(f"""
            QTabWidget::pane {{
                border: 1px solid {border};
                background-color: {bg};
                border-top: none;
            }}
            QTabBar::tab {{
                background-color: {secondary};
                color: #808080;
                padding: 8px 16px;
                border: 1px solid {border};
                border-bottom: none;
                margin-right: 2px;
            }}
            QTabBar::tab:selected {{
                background-color: {bg};
                color: {fg};
            }}
            QTabBar::tab:hover:!selected {{
                background-color: {border};
                color: #cccccc;
            }}
        """)
    
    def _connect_signals(self):
        """Conecta sinais"""
        self.currentChanged.connect(self.tab_changed.emit)
    
    def set_theme_manager(self, theme_manager):
        """Define theme manager para todos os componentes"""
        self.theme_manager = theme_manager
        self._apply_theme()
        self.results_viewer.set_theme_manager(theme_manager)
        self.output_panel.set_theme_manager(theme_manager)
        self.variables_panel.set_theme_manager(theme_manager)
    
    # === Métodos de conveniência para Resultados ===
    
    def set_results(self, df: Optional[pd.DataFrame], var_name: str = "df"):
        """Define dados nos resultados"""
        self.results_viewer.display_dataframe(df, var_name)
        self.show_results()
    
    def clear_results(self):
        """Limpa resultados"""
        self.results_viewer.clear()
    
    def show_results(self):
        """Mostra aba de resultados"""
        self.setCurrentWidget(self.results_viewer)
    
    # === Métodos de conveniência para Output ===
    
    def log(self, text: str):
        """Adiciona log"""
        self.output_panel.log(text)
    
    def log_success(self, text: str):
        """Adiciona log de sucesso"""
        self.output_panel.success(text)
    
    def log_warning(self, text: str):
        """Adiciona log de warning"""
        self.output_panel.warning(text)
    
    def log_error(self, text: str):
        """Adiciona log de erro"""
        self.output_panel.error(text)
        self.show_output()
    
    def append_output(self, text: str, error: bool = False):
        """Compatibilidade com código antigo"""
        self.output_panel.append_output(text, error)
    
    def clear_output(self):
        """Limpa output"""
        self.output_panel.clear()
    
    def show_output(self):
        """Mostra aba de output"""
        self.setCurrentWidget(self.output_panel)
    
    # === Métodos de conveniência para Variáveis ===
    
    def set_variables(self, namespace: dict):
        """Define variáveis"""
        self.variables_panel.set_variables(namespace)
    
    def clear_variables(self):
        """Limpa variáveis"""
        self.variables_panel.clear()
    
    def show_variables(self):
        """Mostra aba de variáveis"""
        self.setCurrentWidget(self.variables_panel)
    
    # === Métodos gerais ===
    
    def clear_all(self):
        """Limpa todos os painéis"""
        self.clear_results()
        self.clear_output()
        self.clear_variables()
    
    # === Compatibilidade com código antigo ===
    
    @property
    def output_text(self):
        """Compatibilidade: retorna o text_edit do output"""
        return self.output_panel.text_edit
    
    @property 
    def variables_viewer(self):
        """Compatibilidade: retorna o variables_panel"""
        return self.variables_panel
