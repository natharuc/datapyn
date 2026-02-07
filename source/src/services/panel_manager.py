"""
PanelManager - Servico centralizado para gerenciamento de paineis inferiores

Responsavel por:
- Criar/remover conjuntos de paineis (Results, Output, Variables) por sessao
- Trocar paineis ativos ao mudar de sessao
- Esconder/mostrar paineis quando nao ha sessoes
- Garantir tamanhos iniciais visiveis

Principio: Toda manipulacao de paineis DEVE passar por este servico.
"""
from typing import Optional, Dict, Any
from PyQt6.QtWidgets import QStackedWidget, QDockWidget, QMainWindow
from PyQt6.QtCore import Qt, QObject


class PanelSet:
    """Conjunto de paineis para uma sessao."""
    __slots__ = ('results', 'output', 'variables',
                 'results_idx', 'output_idx', 'variables_idx')
    
    def __init__(self, results, output, variables,
                 results_idx: int, output_idx: int, variables_idx: int):
        self.results = results
        self.output = output
        self.variables = variables
        self.results_idx = results_idx
        self.output_idx = output_idx
        self.variables_idx = variables_idx


class PanelManager(QObject):
    """
    Gerencia os paineis dockable (Results, Output, Variables).
    
    Cada sessao possui seu proprio conjunto de paineis. Este servico
    gerencia a criacao, remocao, visibilidade e troca entre eles.
    """
    
    # Tamanhos minimos para paineis (garante visibilidade)
    MIN_DOCK_HEIGHT = 180
    MIN_DOCK_WIDTH = 200
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self._panel_sets: Dict[str, PanelSet] = {}
        
        # Stacks (serao configurados via setup)
        self._results_stack: Optional[QStackedWidget] = None
        self._output_stack: Optional[QStackedWidget] = None
        self._variables_stack: Optional[QStackedWidget] = None
        
        # Docks (serao configurados via setup)
        self._results_dock: Optional[QDockWidget] = None
        self._output_dock: Optional[QDockWidget] = None
        self._variables_dock: Optional[QDockWidget] = None
        
        # Factories para criar paineis
        self._results_factory = None
        self._output_factory = None
        self._variables_factory = None
        
        self._active_session_id: Optional[str] = None
    
    def setup(self, results_stack: QStackedWidget, output_stack: QStackedWidget,
              variables_stack: QStackedWidget,
              results_dock: QDockWidget, output_dock: QDockWidget,
              variables_dock: QDockWidget,
              results_factory=None, output_factory=None, variables_factory=None):
        """
        Configura o PanelManager com as dependencias da UI.
        
        Args:
            *_stack: QStackedWidgets que contem os paineis
            *_dock: QDockWidgets que hospedam os stacks
            *_factory: Funcoes que criam novos paineis
        """
        self._results_stack = results_stack
        self._output_stack = output_stack
        self._variables_stack = variables_stack
        self._results_dock = results_dock
        self._output_dock = output_dock
        self._variables_dock = variables_dock
        self._results_factory = results_factory
        self._output_factory = output_factory
        self._variables_factory = variables_factory
        
        # Configurar tamanhos minimos nos docks
        self._apply_minimum_sizes()
    
    def _apply_minimum_sizes(self):
        """Aplica tamanhos minimos nos docks para garantir visibilidade."""
        for dock in [self._results_dock, self._output_dock]:
            if dock:
                dock.setMinimumHeight(self.MIN_DOCK_HEIGHT)
        if self._variables_dock:
            self._variables_dock.setMinimumWidth(self.MIN_DOCK_WIDTH)
            self._variables_dock.setMinimumHeight(self.MIN_DOCK_HEIGHT)
    
    def create_panels(self, session_id: str) -> PanelSet:
        """
        Cria conjunto de paineis para uma sessao.
        
        Returns:
            PanelSet com os paineis criados
        """
        if session_id in self._panel_sets:
            return self._panel_sets[session_id]
        
        results = self._results_factory() if self._results_factory else None
        output = self._output_factory() if self._output_factory else None
        variables = self._variables_factory() if self._variables_factory else None
        
        r_idx = self._results_stack.addWidget(results) if results else -1
        o_idx = self._output_stack.addWidget(output) if output else -1
        v_idx = self._variables_stack.addWidget(variables) if variables else -1
        
        panel_set = PanelSet(results, output, variables, r_idx, o_idx, v_idx)
        self._panel_sets[session_id] = panel_set
        
        return panel_set
    
    def remove_panels(self, session_id: str):
        """Remove conjunto de paineis de uma sessao."""
        panel_set = self._panel_sets.pop(session_id, None)
        if not panel_set:
            return
        
        if panel_set.results:
            self._results_stack.removeWidget(panel_set.results)
            panel_set.results.deleteLater()
        if panel_set.output:
            self._output_stack.removeWidget(panel_set.output)
            panel_set.output.deleteLater()
        if panel_set.variables:
            self._variables_stack.removeWidget(panel_set.variables)
            panel_set.variables.deleteLater()
        
        # Se removeu a sessao ativa, limpar referencia
        if self._active_session_id == session_id:
            self._active_session_id = None
    
    def switch_to(self, session_id: str):
        """Troca para exibir os paineis da sessao especificada.
        
        Usa setCurrentWidget() em vez de setCurrentIndex() para evitar
        bugs com indices invalidos apos remocao de widgets do stack.
        """
        panel_set = self._panel_sets.get(session_id)
        if not panel_set:
            return
        
        self._active_session_id = session_id
        
        if panel_set.results:
            self._results_stack.setCurrentWidget(panel_set.results)
        if panel_set.output:
            self._output_stack.setCurrentWidget(panel_set.output)
        if panel_set.variables:
            self._variables_stack.setCurrentWidget(panel_set.variables)
    
    def hide_all(self):
        """Esconde todos os docks de paineis (estado vazio)."""
        for dock in [self._results_dock, self._output_dock, self._variables_dock]:
            if dock:
                dock.hide()
    
    def show_all(self):
        """Mostra todos os docks de paineis."""
        for dock in [self._results_dock, self._output_dock, self._variables_dock]:
            if dock:
                dock.show()
    
    def show_panel(self, name: str):
        """Mostra painel especifico."""
        dock_map = {
            'results': self._results_dock,
            'output': self._output_dock,
            'variables': self._variables_dock,
        }
        dock = dock_map.get(name)
        if dock:
            dock.show()
            dock.raise_()
    
    @property
    def active_session_id(self) -> Optional[str]:
        return self._active_session_id
    
    def get_active_panels(self) -> Optional[PanelSet]:
        """Retorna os paineis da sessao ativa."""
        if self._active_session_id:
            return self._panel_sets.get(self._active_session_id)
        return None
    
    def get_panels(self, session_id: str) -> Optional[PanelSet]:
        """Retorna os paineis de uma sessao especifica."""
        return self._panel_sets.get(session_id)
    
    @property
    def active_results(self):
        """Retorna o ResultsViewer da sessao ativa."""
        ps = self.get_active_panels()
        return ps.results if ps else None
    
    @property
    def active_output(self):
        """Retorna o OutputPanel da sessao ativa."""
        ps = self.get_active_panels()
        return ps.output if ps else None
    
    @property
    def active_variables(self):
        """Retorna o VariablesPanel da sessao ativa."""
        ps = self.get_active_panels()
        return ps.variables if ps else None
    
    @property
    def has_panels(self) -> bool:
        """Retorna True se ha paineis registrados."""
        return len(self._panel_sets) > 0
    
    def cleanup(self):
        """Remove todos os paineis. Usado ao fechar a aplicacao."""
        for session_id in list(self._panel_sets.keys()):
            self.remove_panels(session_id)
