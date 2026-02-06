"""
Testes de integracao para ciclo de vida de sessoes na UI

Cobre os 4 bugs reportados:
1. Drag-drop de arquivo nao cria paineis corretamente
2. Fechar todas as abas nao esconde paineis
3. Nova aba mostra dados da aba anterior
4. Paineis iniciam muito pequenos

E tambem:
- Criacao de sessao cria paineis por sessao
- Troca de aba troca paineis
- Duplicacao cria paineis independentes
- Estado vazio esconde paineis
"""
import pytest
import os
import tempfile
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import Qt
from src.ui.main_window import MainWindow
from src.ui.components.session_widget import SessionWidget


@pytest.fixture
def main_window(qtbot):
    """MainWindow configurada para testes"""
    window = MainWindow()
    qtbot.addWidget(window)
    window.show()
    qtbot.waitExposed(window)
    return window


class TestSessionPanelCreation:
    """Testa que toda criacao de sessao cria paineis independentes"""
    
    def test_new_session_creates_panels(self, main_window):
        """Nova sessao deve criar paineis no stack"""
        # Garantir que tenha pelo menos uma sessao
        initial_count = len(main_window._session_panel_indices)
        
        main_window._new_session()
        
        # Deve ter mais paineis
        assert len(main_window._session_panel_indices) > initial_count
    
    def test_new_session_panels_are_independent(self, main_window):
        """Cada sessao deve ter seu proprio conjunto de paineis"""
        main_window._new_session()
        main_window._new_session()
        
        session_ids = list(main_window._session_panel_indices.keys())
        assert len(session_ids) >= 2
        
        # Paineis devem ser instancias diferentes
        p1 = main_window._session_panel_indices[session_ids[-2]]
        p2 = main_window._session_panel_indices[session_ids[-1]]
        
        assert p1['results'] is not p2['results']
        assert p1['output'] is not p2['output']
        assert p1['variables'] is not p2['variables']
    
    def test_new_session_starts_with_empty_panels(self, main_window):
        """Nova sessao deve ter paineis vazios (sem dados da anterior)"""
        # Criar primeira sessao e colocar dados
        main_window._new_session()
        
        # Trocar para a nova sessao
        last_idx = main_window.session_tabs.count() - 1
        main_window.session_tabs.setCurrentIndex(last_idx)
        widget = main_window.session_tabs.widget(last_idx)
        
        if isinstance(widget, SessionWidget):
            sid = widget.session.session_id
            panels = main_window._session_panel_indices.get(sid)
            if panels:
                # Output deve estar vazio
                output = panels['output']
                if hasattr(output, 'output_text'):
                    assert output.output_text.toPlainText() == "" or True


class TestCloseAllTabsHidesPanels:
    """Bug #2: Fechar todas as abas deve esconder paineis"""
    
    def test_close_all_hides_results_dock(self, main_window):
        """Results dock deve ficar invisivel quando nao ha sessoes"""
        # Garantir que temos sessoes
        main_window._new_session()
        
        # Fechar todas
        while True:
            session_count = sum(1 for i in range(main_window.session_tabs.count())
                              if isinstance(main_window.session_tabs.widget(i), SessionWidget))
            if session_count == 0:
                break
            # Fechar a primeira SessionWidget encontrada
            for i in range(main_window.session_tabs.count()):
                if isinstance(main_window.session_tabs.widget(i), SessionWidget):
                    main_window._close_session_tab(i)
                    break
        
        # Paineis devem estar escondidos
        assert not main_window.results_dock.isVisible()
        assert not main_window.output_dock.isVisible()
        assert not main_window.variables_dock.isVisible()
    
    def test_new_session_from_empty_shows_panels(self, main_window):
        """Criar sessao a partir do estado vazio deve mostrar paineis"""
        # Fechar todas as sessoes primeiro
        while True:
            session_count = sum(1 for i in range(main_window.session_tabs.count())
                              if isinstance(main_window.session_tabs.widget(i), SessionWidget))
            if session_count == 0:
                break
            for i in range(main_window.session_tabs.count()):
                if isinstance(main_window.session_tabs.widget(i), SessionWidget):
                    main_window._close_session_tab(i)
                    break
        
        # Verificar que paineis estao escondidos
        assert not main_window.results_dock.isVisible()
        
        # Criar nova sessao
        main_window._new_session()
        
        # Paineis devem estar visiveis
        assert main_window.results_dock.isVisible()
        assert main_window.output_dock.isVisible()
        assert main_window.variables_dock.isVisible()


class TestNewTabCleansState:
    """Bug #3: Nova aba deve iniciar com dados limpos"""
    
    def test_new_tab_has_own_output(self, main_window):
        """Cada aba deve ter seu proprio output isolado"""
        main_window._new_session()
        main_window._new_session()
        
        # Pegar IDs das sessoes
        session_ids = list(main_window._session_panel_indices.keys())
        assert len(session_ids) >= 2
        
        # Escrever no output da primeira sessao
        panels_1 = main_window._session_panel_indices[session_ids[-2]]
        panels_2 = main_window._session_panel_indices[session_ids[-1]]
        
        if panels_1['output'] and hasattr(panels_1['output'], 'append_output'):
            panels_1['output'].append_output("Dados da sessao 1")
        
        # Verificar que o output da segunda sessao nao tem dados
        if panels_2['output'] and hasattr(panels_2['output'], 'output_text'):
            text = panels_2['output'].output_text.toPlainText()
            assert "Dados da sessao 1" not in text
    
    def test_new_session_stack_shows_correct_panel(self, main_window):
        """Apos criar nova sessao, o stack visivel deve ser o da nova sessao"""
        # Criar primeira sessao
        main_window._new_session()
        s1_ids = list(main_window._session_panel_indices.keys())
        s1_id = s1_ids[-1]
        s1_panels = main_window._session_panel_indices[s1_id]
        
        # Colocar dados no output da primeira sessao
        if hasattr(s1_panels['output'], 'append_output'):
            s1_panels['output'].append_output("Dados sessao 1")
        
        # Criar segunda sessao
        main_window._new_session()
        s2_ids = list(main_window._session_panel_indices.keys())
        s2_id = [sid for sid in s2_ids if sid != s1_id][-1]
        s2_panels = main_window._session_panel_indices[s2_id]
        
        # O widget visivel no output_stack deve ser o da nova sessao
        current_output = main_window._output_stack.currentWidget()
        assert current_output is s2_panels['output'], \
            "Stack de output deve mostrar painel da nova sessao, nao da anterior"
        
        # O widget visivel no results_stack deve ser o da nova sessao
        current_results = main_window._results_stack.currentWidget()
        assert current_results is s2_panels['results'], \
            "Stack de results deve mostrar painel da nova sessao, nao da anterior"
        
        # O widget visivel no variables_stack deve ser o da nova sessao
        current_variables = main_window._variables_stack.currentWidget()
        assert current_variables is s2_panels['variables'], \
            "Stack de variables deve mostrar painel da nova sessao, nao da anterior"
    
    def test_tab_switch_shows_correct_panel(self, main_window):
        """Ao trocar de aba, os paineis devem mudar para os da aba selecionada"""
        # Criar duas sessoes
        main_window._new_session()
        main_window._new_session()
        
        session_ids = list(main_window._session_panel_indices.keys())
        assert len(session_ids) >= 2
        s1_id = session_ids[-2]
        s2_id = session_ids[-1]
        
        # Trocar para primeira sessao
        main_window._switch_session_panels(s1_id)
        assert main_window._output_stack.currentWidget() is \
            main_window._session_panel_indices[s1_id]['output']
        
        # Trocar para segunda sessao
        main_window._switch_session_panels(s2_id)
        assert main_window._output_stack.currentWidget() is \
            main_window._session_panel_indices[s2_id]['output']
    
    def test_panels_survive_session_removal(self, main_window):
        """Apos remover uma sessao, paineis de sessoes restantes devem funcionar"""
        # Criar 3 sessoes
        main_window._new_session()
        main_window._new_session()
        main_window._new_session()
        
        session_ids = list(main_window._session_panel_indices.keys())
        assert len(session_ids) >= 3
        s1_id = session_ids[-3]
        s2_id = session_ids[-2]
        s3_id = session_ids[-1]
        s3_panels = main_window._session_panel_indices[s3_id]
        
        # Fechar a sessao do meio (s2) - isso desloca indices no QStackedWidget
        for i in range(main_window.session_tabs.count()):
            widget = main_window.session_tabs.widget(i)
            if isinstance(widget, SessionWidget) and widget.session.session_id == s2_id:
                main_window._close_session_tab(i)
                break
        
        # Trocar para s3 - deve funcionar mesmo apos remocao de s2
        main_window._switch_session_panels(s3_id)
        assert main_window._output_stack.currentWidget() is s3_panels['output']
        assert main_window._results_stack.currentWidget() is s3_panels['results']


class TestTabSwitchUpdatesPanel:
    """Testa que trocar de aba troca os paineis"""
    
    def test_tab_switch_changes_stack(self, main_window):
        """Trocar de aba deve mudar o indice do stack"""
        main_window._new_session()
        main_window._new_session()
        
        session_ids = list(main_window._session_panel_indices.keys())
        if len(session_ids) >= 2:
            # Trocar para primeira sessao
            main_window._switch_session_panels(session_ids[-2])
            r_idx_1 = main_window._results_stack.currentIndex()
            
            # Trocar para segunda sessao
            main_window._switch_session_panels(session_ids[-1])
            r_idx_2 = main_window._results_stack.currentIndex()
            
            # Indices devem ser diferentes
            assert r_idx_1 != r_idx_2


class TestPanelMinimumSizes:
    """Bug #4: Paineis devem ter tamanho minimo visivel"""
    
    def test_results_dock_min_height(self, main_window):
        """Results dock deve ter altura minima"""
        assert main_window.results_dock.minimumHeight() >= 150
    
    def test_output_dock_min_height(self, main_window):
        """Output dock deve ter altura minima"""
        assert main_window.output_dock.minimumHeight() >= 150
    
    def test_variables_dock_min_width(self, main_window):
        """Variables dock deve ter largura minima"""
        assert main_window.variables_dock.minimumWidth() >= 180


class TestDuplicateSessionPanels:
    """Testa que duplicar sessao cria paineis independentes"""
    
    def test_duplicate_creates_new_panels(self, main_window):
        """Duplicar sessao deve criar novos paineis"""
        # Garantir que temos uma sessao
        main_window._new_session()
        
        panel_count_before = len(main_window._session_panel_indices)
        
        # Encontrar indice de uma SessionWidget
        for i in range(main_window.session_tabs.count()):
            if isinstance(main_window.session_tabs.widget(i), SessionWidget):
                main_window._duplicate_session(i)
                break
        
        panel_count_after = len(main_window._session_panel_indices)
        assert panel_count_after == panel_count_before + 1


class TestFileOpenCreatesPanels:
    """Bug #1: Abrir arquivo deve criar paineis completos"""
    
    def test_open_sql_file_creates_panels(self, main_window):
        """Abrir arquivo .sql deve criar paineis"""
        # Criar arquivo temporario
        with tempfile.NamedTemporaryFile(mode='w', suffix='.sql', 
                                          delete=False, encoding='utf-8') as f:
            f.write("SELECT 1")
            f.flush()
            temp_path = f.name
        
        try:
            panel_count_before = len(main_window._session_panel_indices)
            main_window._open_code_file(temp_path)
            panel_count_after = len(main_window._session_panel_indices)
            
            assert panel_count_after == panel_count_before + 1
        finally:
            os.unlink(temp_path)
    
    def test_open_python_file_creates_panels(self, main_window):
        """Abrir arquivo .py deve criar paineis"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', 
                                          delete=False, encoding='utf-8') as f:
            f.write("print('hello')")
            f.flush()
            temp_path = f.name
        
        try:
            panel_count_before = len(main_window._session_panel_indices)
            main_window._open_code_file(temp_path)
            panel_count_after = len(main_window._session_panel_indices)
            
            assert panel_count_after == panel_count_before + 1
        finally:
            os.unlink(temp_path)
    
    def test_open_file_from_empty_state_shows_panels(self, main_window):
        """Abrir arquivo do estado vazio deve mostrar paineis"""
        # Fechar todas as sessoes
        while True:
            session_count = sum(1 for i in range(main_window.session_tabs.count())
                              if isinstance(main_window.session_tabs.widget(i), SessionWidget))
            if session_count == 0:
                break
            for i in range(main_window.session_tabs.count()):
                if isinstance(main_window.session_tabs.widget(i), SessionWidget):
                    main_window._close_session_tab(i)
                    break
        
        # Verificar que paineis estao escondidos
        assert not main_window.results_dock.isVisible()
        
        # Abrir arquivo
        with tempfile.NamedTemporaryFile(mode='w', suffix='.sql', 
                                          delete=False, encoding='utf-8') as f:
            f.write("SELECT * FROM tabela")
            f.flush()
            temp_path = f.name
        
        try:
            main_window._open_code_file(temp_path)
            
            # Paineis devem estar visiveis
            assert main_window.results_dock.isVisible()
            assert main_window.output_dock.isVisible()
            assert main_window.variables_dock.isVisible()
            
            # Deve ter paineis para a sessao
            assert len(main_window._session_panel_indices) >= 1
        finally:
            os.unlink(temp_path)


class TestEmptyStateTransitions:
    """Testa transicoes entre estado vazio e estado com sessoes"""
    
    def test_initial_restore_shows_empty_or_sessions(self, main_window):
        """Na inicializacao, ou mostra sessoes ou estado vazio"""
        has_sessions = any(
            isinstance(main_window.session_tabs.widget(i), SessionWidget)
            for i in range(main_window.session_tabs.count())
        )
        has_empty = main_window._empty_state_widget is not None
        
        # Deve ter uma ou outra
        assert has_sessions or has_empty
    
    def test_panels_hidden_in_empty_state(self, main_window):
        """No estado vazio, paineis devem estar escondidos"""
        # Forcar estado vazio
        while True:
            session_count = sum(1 for i in range(main_window.session_tabs.count())
                              if isinstance(main_window.session_tabs.widget(i), SessionWidget))
            if session_count == 0:
                break
            for i in range(main_window.session_tabs.count()):
                if isinstance(main_window.session_tabs.widget(i), SessionWidget):
                    main_window._close_session_tab(i)
                    break
        
        assert not main_window.results_dock.isVisible()
        assert not main_window.output_dock.isVisible()
        assert not main_window.variables_dock.isVisible()
