"""
🎨 Component Playground - DataPyn
===================================

Teste componentes PyQt6 em tempo real!

USO:
    python playground.py                    # Testa o componente padrão
    python playground.py SessionTabs        # Testa componente específico
    python playground.py --list             # Lista componentes disponíveis
    python playground.py --watch            # Hot reload (recarrega ao salvar)

TECLAS:
    F5      = Recarregar componente
    Ctrl+Q  = Sair
    Ctrl+T  = Trocar tema (dark/light)
"""

import sys
import os
import importlib
import argparse
from pathlib import Path

# Adicionar src ao path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QComboBox, QPushButton, QScrollArea, QFrame, QSplitter,
    QTextEdit, QGroupBox
)
from PyQt6.QtCore import Qt, QTimer, QFileSystemWatcher
from PyQt6.QtGui import QShortcut, QKeySequence, QFont

# Importar theme manager
try:
    from themes.theme_manager import ThemeManager
    HAS_THEME = True
except ImportError:
    HAS_THEME = False
    ThemeManager = None


# === REGISTRO DE COMPONENTES ===

COMPONENTS = {
    # Botões
    "StyledButton": ("ui.components.buttons", "StyledButton"),
    "PrimaryButton": ("ui.components.buttons", "PrimaryButton"),
    "SecondaryButton": ("ui.components.buttons", "SecondaryButton"),
    "DangerButton": ("ui.components.buttons", "DangerButton"),
    "SuccessButton": ("ui.components.buttons", "SuccessButton"),
    "GhostButton": ("ui.components.buttons", "GhostButton"),
    "IconButton": ("ui.components.buttons", "IconButton"),
    
    # Inputs
    "StyledLineEdit": ("ui.components.inputs", "StyledLineEdit"),
    "StyledTextEdit": ("ui.components.inputs", "StyledTextEdit"),
    "StyledComboBox": ("ui.components.inputs", "StyledComboBox"),
    "StyledSpinBox": ("ui.components.inputs", "StyledSpinBox"),
    "StyledCheckBox": ("ui.components.inputs", "StyledCheckBox"),
    "SearchInput": ("ui.components.inputs", "SearchInput"),
    "FormField": ("ui.components.inputs", "FormField"),
    
    # Painéis
    "OutputPanel": ("ui.components.output_panel", "OutputPanel"),
    "VariablesPanel": ("ui.components.variables_panel", "VariablesPanel"),
    "BottomTabs": ("ui.components.bottom_tabs", "BottomTabs"),
    "ResultsViewer": ("ui.components.results_viewer", "ResultsViewer"),
    
    # Estrutura
    "SessionTabs": ("ui.components.session_tabs", "SessionTabs"),
    "MainToolbar": ("ui.components.toolbar", "MainToolbar"),
    "MainStatusBar": ("ui.components.statusbar", "MainStatusBar"),
    "ConnectionPanel": ("ui.components.connection_panel", "ConnectionPanel"),
    "EditorHeader": ("ui.components.editor_header", "EditorHeader"),
}


class ComponentPlayground(QMainWindow):
    """Janela principal do playground"""
    
    def __init__(self, initial_component: str = None, watch_mode: bool = False):
        super().__init__()
        
        self.current_component = None
        self.current_widget = None
        self.watch_mode = watch_mode
        self.theme_manager = ThemeManager() if HAS_THEME else None
        self.current_theme_index = 0
        
        # Estado salvo do componente para hot reload
        self._saved_state = {}
        
        self._setup_ui()
        self._setup_shortcuts()
        self._setup_watcher()
        self._apply_theme()
        
        # Carregar componente inicial
        if initial_component and initial_component in COMPONENTS:
            self.component_selector.setCurrentText(initial_component)
            self._load_component(initial_component)
        else:
            self._load_component(list(COMPONENTS.keys())[0])
    
    def _setup_ui(self):
        """Configura interface"""
        self.setWindowTitle("🎨 Component Playground - DataPyn")
        self.setMinimumSize(1000, 700)
        
        # Widget central
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)
        
        # === TOOLBAR ===
        toolbar = QWidget()
        toolbar_layout = QHBoxLayout(toolbar)
        toolbar_layout.setContentsMargins(0, 0, 0, 0)
        
        # Selector de componente
        toolbar_layout.addWidget(QLabel("Componente:"))
        self.component_selector = QComboBox()
        self.component_selector.addItems(sorted(COMPONENTS.keys()))
        self.component_selector.currentTextChanged.connect(self._load_component)
        self.component_selector.setMinimumWidth(200)
        toolbar_layout.addWidget(self.component_selector)
        
        toolbar_layout.addSpacing(20)
        
        # Botões
        self.btn_reload = QPushButton("🔄 Recarregar (F5)")
        self.btn_reload.clicked.connect(self._reload_component)
        toolbar_layout.addWidget(self.btn_reload)
        
        self.btn_theme = QPushButton("🎨 Trocar Tema (Ctrl+T)")
        self.btn_theme.clicked.connect(self._toggle_theme)
        toolbar_layout.addWidget(self.btn_theme)
        
        # Watch mode indicator
        self.watch_label = QLabel("👁️ Watch Mode ON" if self.watch_mode else "")
        self.watch_label.setStyleSheet("color: #4ec9b0; font-weight: bold;")
        toolbar_layout.addWidget(self.watch_label)
        
        toolbar_layout.addStretch()
        
        # Info do componente
        self.info_label = QLabel("")
        self.info_label.setStyleSheet("color: #808080;")
        toolbar_layout.addWidget(self.info_label)
        
        layout.addWidget(toolbar)
        
        # === ÁREA PRINCIPAL ===
        splitter = QSplitter(Qt.Orientation.Horizontal)
        
        # Preview do componente
        preview_group = QGroupBox("Preview")
        preview_layout = QVBoxLayout(preview_group)
        
        self.preview_scroll = QScrollArea()
        self.preview_scroll.setWidgetResizable(True)
        self.preview_scroll.setMinimumWidth(500)
        
        self.preview_container = QWidget()
        self.preview_layout = QVBoxLayout(self.preview_container)
        self.preview_layout.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self.preview_scroll.setWidget(self.preview_container)
        
        preview_layout.addWidget(self.preview_scroll)
        splitter.addWidget(preview_group)
        
        # Painel lateral
        side_panel = QWidget()
        side_layout = QVBoxLayout(side_panel)
        side_layout.setContentsMargins(0, 0, 0, 0)
        
        # Log de eventos
        log_group = QGroupBox("📋 Log de Eventos")
        log_layout = QVBoxLayout(log_group)
        
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setFont(QFont("Consolas", 9))
        self.log_text.setMaximumHeight(200)
        log_layout.addWidget(self.log_text)
        
        btn_clear_log = QPushButton("Limpar Log")
        btn_clear_log.clicked.connect(self.log_text.clear)
        log_layout.addWidget(btn_clear_log)
        
        side_layout.addWidget(log_group)
        
        # Ações do componente
        actions_group = QGroupBox("⚡ Ações de Teste")
        self.actions_layout = QVBoxLayout(actions_group)
        side_layout.addWidget(actions_group)
        
        side_layout.addStretch()
        splitter.addWidget(side_panel)
        
        splitter.setSizes([700, 300])
        layout.addWidget(splitter)
        
        # === STATUS BAR ===
        self.statusBar().showMessage("Pronto. Pressione F5 para recarregar.")
    
    def _setup_shortcuts(self):
        """Configura atalhos"""
        QShortcut(QKeySequence("F5"), self, self._reload_component)
        QShortcut(QKeySequence("Ctrl+Q"), self, self.close)
        QShortcut(QKeySequence("Ctrl+T"), self, self._toggle_theme)
    
    def _setup_watcher(self):
        """Configura file watcher para hot reload"""
        self.watcher = QFileSystemWatcher(self)
        self.watcher.fileChanged.connect(self._on_file_changed)
        
        if self.watch_mode:
            # Observar pasta de componentes
            components_path = Path(__file__).parent / "src" / "ui" / "components"
            if components_path.exists():
                for py_file in components_path.glob("*.py"):
                    self.watcher.addPath(str(py_file))
                self._log("👁️ Observando mudanças em: " + str(components_path))
    
    def _on_file_changed(self, path: str):
        """Quando um arquivo muda"""
        self._log(f"📝 Arquivo modificado: {Path(path).name}")
        
        # Re-adicionar ao watcher (alguns editores removem)
        if path not in self.watcher.files():
            self.watcher.addPath(path)
        
        # Recarregar após breve delay
        QTimer.singleShot(500, self._reload_component)
    
    def _apply_theme(self):
        """Aplica tema"""
        if self.theme_manager:
            colors = self.theme_manager.get_app_colors()
            self.setStyleSheet(f"""
                QMainWindow, QWidget {{
                    background-color: {colors['background']};
                    color: {colors['foreground']};
                }}
                QGroupBox {{
                    border: 1px solid {colors['border']};
                    border-radius: 4px;
                    margin-top: 10px;
                    padding-top: 10px;
                    font-weight: bold;
                }}
                QGroupBox::title {{
                    subcontrol-origin: margin;
                    left: 10px;
                    padding: 0 5px;
                }}
                QPushButton {{
                    background-color: {colors['button']};
                    color: {colors['foreground']};
                    border: 1px solid {colors['border']};
                    padding: 6px 12px;
                    border-radius: 4px;
                }}
                QPushButton:hover {{
                    background-color: {colors['button_hover']};
                }}
                QComboBox {{
                    background-color: {colors['input_background']};
                    color: {colors['foreground']};
                    border: 1px solid {colors['border']};
                    padding: 5px;
                    border-radius: 4px;
                }}
                QTextEdit {{
                    background-color: {colors['input_background']};
                    color: {colors['foreground']};
                    border: 1px solid {colors['border']};
                }}
                QScrollArea {{
                    border: 1px solid {colors['border']};
                }}
            """)
        else:
            # Tema escuro padrão
            self.setStyleSheet("""
                QMainWindow, QWidget {
                    background-color: #1e1e1e;
                    color: #cccccc;
                }
                QGroupBox {
                    border: 1px solid #3e3e42;
                    border-radius: 4px;
                    margin-top: 10px;
                    padding-top: 10px;
                    font-weight: bold;
                }
                QPushButton {
                    background-color: #0e639c;
                    color: white;
                    border: none;
                    padding: 6px 12px;
                    border-radius: 4px;
                }
                QPushButton:hover {
                    background-color: #1177bb;
                }
                QComboBox, QTextEdit {
                    background-color: #3c3c3c;
                    color: #cccccc;
                    border: 1px solid #3e3e42;
                    padding: 5px;
                }
            """)
    
    def _toggle_theme(self):
        """Alterna entre temas"""
        if self.theme_manager:
            themes = self.theme_manager.get_available_themes()
            self.current_theme_index = (self.current_theme_index + 1) % len(themes)
            theme_name = themes[self.current_theme_index]
            self.theme_manager.set_theme(theme_name)
            self._apply_theme()
            self._reload_component()
            self._log(f"🎨 Tema alterado para: {theme_name}")
    
    def _load_component(self, name: str, restore_state: bool = False):
        """Carrega um componente"""
        if name not in COMPONENTS:
            self._log(f"❌ Componente não encontrado: {name}")
            return
        
        self.current_component = name
        module_path, class_name = COMPONENTS[name]
        
        try:
            # Importar/reimportar módulo
            full_module = module_path
            if full_module in sys.modules:
                module = importlib.reload(sys.modules[full_module])
            else:
                module = importlib.import_module(full_module)
            
            # Obter classe
            component_class = getattr(module, class_name)
            
            # Salvar estado antes de destruir
            if self.current_widget and restore_state:
                self._save_component_state()
            
            # Limpar preview anterior
            if self.current_widget:
                self.current_widget.setParent(None)
                self.current_widget.deleteLater()
            
            # Criar instância
            try:
                # Tentar com theme_manager
                self.current_widget = component_class(theme_manager=self.theme_manager)
            except TypeError:
                # Sem theme_manager
                try:
                    self.current_widget = component_class()
                except Exception as e:
                    self._log(f"⚠️ Erro ao criar: {e}")
                    return
            
            # Adicionar ao preview
            self.preview_layout.addWidget(self.current_widget)
            
            # Conectar sinais para log
            self._connect_signals(self.current_widget)
            
            # Restaurar estado se solicitado
            if restore_state and self._saved_state:
                self._restore_component_state()
            
            # Atualizar info
            self.info_label.setText(f"{module_path}.{class_name}")
            self.statusBar().showMessage(f"✅ Componente carregado: {name}")
            self._log(f"✅ Carregado: {name}" + (" (estado restaurado)" if restore_state and self._saved_state else ""))
            
            # Criar ações de teste
            self._create_test_actions(name)
            
        except Exception as e:
            self._log(f"❌ Erro ao carregar {name}: {e}")
            import traceback
            self._log(traceback.format_exc())
    
    def _reload_component(self):
        """Recarrega componente atual mantendo estado"""
        if self.current_component:
            self._log("🔄 Recarregando (mantendo estado)...")
            self._load_component(self.current_component, restore_state=True)
    
    def _save_component_state(self):
        """Salva estado do componente atual"""
        if not self.current_widget:
            return
        
        self._saved_state = {
            'component': self.current_component,
            'data': {}
        }
        
        widget = self.current_widget
        state = self._saved_state['data']
        
        try:
            # === QTabWidget / SessionTabs ===
            if hasattr(widget, 'count') and hasattr(widget, 'tabText'):
                tabs = []
                for i in range(widget.count()):
                    tab_data = {
                        'text': widget.tabText(i),
                        'tooltip': widget.tabToolTip(i) if hasattr(widget, 'tabToolTip') else '',
                    }
                    # Tentar salvar conteúdo do widget interno
                    tab_widget = widget.widget(i)
                    if tab_widget:
                        if hasattr(tab_widget, 'text'):
                            tab_data['content'] = tab_widget.text()
                        elif hasattr(tab_widget, 'toPlainText'):
                            tab_data['content'] = tab_widget.toPlainText()
                    tabs.append(tab_data)
                state['tabs'] = tabs
                state['current_index'] = widget.currentIndex()
            
            # === QLineEdit / SearchInput ===
            if hasattr(widget, 'text') and callable(widget.text):
                try:
                    state['text'] = widget.text()
                except:
                    pass
            
            # === QTextEdit / OutputPanel ===
            if hasattr(widget, 'toHtml'):
                state['html'] = widget.toHtml()
            elif hasattr(widget, 'toPlainText'):
                state['plain_text'] = widget.toPlainText()
            
            # === OutputPanel específico ===
            if hasattr(widget, 'output_text'):
                state['output_html'] = widget.output_text.toHtml()
            
            # === VariablesPanel ===
            if hasattr(widget, 'model') and hasattr(widget.model, '_variables'):
                state['variables'] = widget.model._variables.copy()
            
            # === ResultsViewer / BottomTabs ===
            if hasattr(widget, 'results_viewer'):
                rv = widget.results_viewer
                if hasattr(rv, '_current_df') and rv._current_df is not None:
                    state['dataframe'] = rv._current_df.copy()
                    state['df_name'] = getattr(rv, '_current_name', 'df')
            
            # === QComboBox ===
            if hasattr(widget, 'currentText'):
                state['combo_text'] = widget.currentText()
                state['combo_index'] = widget.currentIndex()
            
            # === QCheckBox ===
            if hasattr(widget, 'isChecked'):
                state['checked'] = widget.isChecked()
            
            # === QSpinBox ===
            if hasattr(widget, 'value') and not hasattr(widget, 'text'):
                state['value'] = widget.value()
            
            self._log(f"💾 Estado salvo: {list(state.keys())}")
            
        except Exception as e:
            self._log(f"⚠️ Erro ao salvar estado: {e}")
    
    def _restore_component_state(self):
        """Restaura estado no novo componente"""
        if not self.current_widget or not self._saved_state:
            return
        
        if self._saved_state.get('component') != self.current_component:
            self._log("⚠️ Componente diferente, estado não restaurado")
            return
        
        widget = self.current_widget
        state = self._saved_state.get('data', {})
        
        try:
            # === QTabWidget / SessionTabs ===
            if 'tabs' in state and hasattr(widget, 'addTab'):
                # Limpar tabs existentes
                while widget.count() > 0:
                    widget.removeTab(0)
                
                # Recriar tabs
                for tab_data in state['tabs']:
                    # Criar widget placeholder
                    tab_widget = QLabel(tab_data.get('content', ''))
                    widget.addTab(tab_widget, tab_data['text'])
                    if tab_data.get('tooltip'):
                        widget.setTabToolTip(widget.count() - 1, tab_data['tooltip'])
                
                # Restaurar índice
                if 'current_index' in state and state['current_index'] < widget.count():
                    widget.setCurrentIndex(state['current_index'])
            
            # === QLineEdit ===
            if 'text' in state and hasattr(widget, 'setText'):
                widget.setText(state['text'])
            
            # === QTextEdit ===
            if 'html' in state and hasattr(widget, 'setHtml'):
                widget.setHtml(state['html'])
            elif 'plain_text' in state and hasattr(widget, 'setPlainText'):
                widget.setPlainText(state['plain_text'])
            
            # === OutputPanel ===
            if 'output_html' in state and hasattr(widget, 'output_text'):
                widget.output_text.setHtml(state['output_html'])
            
            # === VariablesPanel ===
            if 'variables' in state and hasattr(widget, 'model'):
                widget.model._variables = state['variables']
                widget.model.layoutChanged.emit()
            
            # === ResultsViewer / BottomTabs ===
            if 'dataframe' in state:
                df = state['dataframe']
                name = state.get('df_name', 'df')
                if hasattr(widget, 'set_results'):
                    widget.set_results(df, name)
                elif hasattr(widget, 'set_data'):
                    widget.set_data(df)
            
            # === QComboBox ===
            if 'combo_index' in state and hasattr(widget, 'setCurrentIndex'):
                widget.setCurrentIndex(state['combo_index'])
            
            # === QCheckBox ===
            if 'checked' in state and hasattr(widget, 'setChecked'):
                widget.setChecked(state['checked'])
            
            # === QSpinBox ===
            if 'value' in state and hasattr(widget, 'setValue'):
                widget.setValue(state['value'])
            
            self._log(f"♻️ Estado restaurado: {list(state.keys())}")
            
        except Exception as e:
            self._log(f"⚠️ Erro ao restaurar estado: {e}")
    
    def _connect_signals(self, widget):
        """Conecta sinais do widget para log"""
        # Procurar por sinais comuns
        for attr_name in dir(widget):
            if attr_name.startswith('_'):
                continue
            try:
                attr = getattr(widget, attr_name)
                if hasattr(attr, 'connect') and hasattr(attr, 'emit'):
                    # É um sinal
                    signal_name = attr_name
                    attr.connect(lambda *args, name=signal_name: self._log_signal(name, args))
            except:
                pass
    
    def _log_signal(self, name: str, args):
        """Log de sinal emitido"""
        args_str = ", ".join(repr(a)[:50] for a in args) if args else ""
        self._log(f"📡 {name}({args_str})")
    
    def _log(self, message: str):
        """Adiciona mensagem ao log"""
        from datetime import datetime
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.log_text.append(f"[{timestamp}] {message}")
        
        # Auto-scroll
        scrollbar = self.log_text.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())
    
    def _create_test_actions(self, name: str):
        """Cria botões de ação específicos para cada componente"""
        # Limpar ações anteriores
        while self.actions_layout.count():
            item = self.actions_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        
        # Ações específicas por componente
        if name in ("OutputPanel",):
            self._add_action("Log Info", lambda: self.current_widget.append("Mensagem de info", "info"))
            self._add_action("Log Success", lambda: self.current_widget.append("Operação bem sucedida!", "success"))
            self._add_action("Log Warning", lambda: self.current_widget.append("Aviso importante", "warning"))
            self._add_action("Log Error", lambda: self.current_widget.append("Erro crítico!", "error"))
            self._add_action("Limpar", lambda: self.current_widget.clear())
        
        elif name in ("VariablesPanel",):
            self._add_action("Adicionar Variáveis", lambda: self.current_widget.set_variables({
                'df': __import__('pandas').DataFrame({'a': [1,2,3]}),
                'nome': "teste",
                'lista': [1, 2, 3, 4, 5],
                'numero': 42,
            }))
            self._add_action("Limpar", lambda: self.current_widget.clear())
        
        elif name in ("ResultsViewer", "BottomTabs"):
            import pandas as pd
            self._add_action("Mostrar DataFrame", lambda: self._show_test_dataframe())
            self._add_action("Limpar", lambda: self.current_widget.clear() if hasattr(self.current_widget, 'clear') else None)
        
        elif "Button" in name:
            self._add_action("Habilitar", lambda: self.current_widget.setEnabled(True))
            self._add_action("Desabilitar", lambda: self.current_widget.setEnabled(False))
            self._add_action("Mudar Texto", lambda: self.current_widget.setText("Novo Texto!"))
        
        elif name in ("SessionTabs",):
            self._add_action("Add Tab", lambda: self.current_widget.addTab(QLabel("Nova Aba"), "Tab Nova"))
            self._add_action("Remove Tab", lambda: self.current_widget.removeTab(0) if self.current_widget.count() > 0 else None)
        
        elif name in ("MainToolbar",):
            self._add_action("Habilitar Tudo", lambda: [btn.setEnabled(True) for btn in self.current_widget.findChildren(QPushButton)])
            self._add_action("Desabilitar Tudo", lambda: [btn.setEnabled(False) for btn in self.current_widget.findChildren(QPushButton)])
        
        # Ação genérica
        self._add_action("Imprimir Propriedades", self._print_widget_properties)
    
    def _add_action(self, label: str, callback):
        """Adiciona botão de ação"""
        btn = QPushButton(label)
        btn.clicked.connect(callback)
        self.actions_layout.addWidget(btn)
    
    def _show_test_dataframe(self):
        """Mostra DataFrame de teste"""
        import pandas as pd
        df = pd.DataFrame({
            'ID': range(1, 101),
            'Nome': [f'Item {i}' for i in range(1, 101)],
            'Valor': [i * 10.5 for i in range(1, 101)],
            'Ativo': [i % 2 == 0 for i in range(1, 101)],
        })
        
        if hasattr(self.current_widget, 'set_data'):
            self.current_widget.set_data(df)
        elif hasattr(self.current_widget, 'set_results'):
            self.current_widget.set_results(df, "test_df")
        elif hasattr(self.current_widget, 'display_dataframe'):
            self.current_widget.display_dataframe(df, "test_df")
        
        self._log(f"📊 DataFrame com {len(df)} linhas exibido")
    
    def _print_widget_properties(self):
        """Imprime propriedades do widget"""
        if not self.current_widget:
            return
        
        self._log("--- Propriedades ---")
        self._log(f"Tipo: {type(self.current_widget).__name__}")
        self._log(f"Tamanho: {self.current_widget.size().width()}x{self.current_widget.size().height()}")
        self._log(f"Visível: {self.current_widget.isVisible()}")
        self._log(f"Habilitado: {self.current_widget.isEnabled()}")
        
        # Listar métodos públicos
        methods = [m for m in dir(self.current_widget) if not m.startswith('_') and callable(getattr(self.current_widget, m, None))]
        self._log(f"Métodos: {len(methods)}")


def list_components():
    """Lista componentes disponíveis"""
    print("\n🎨 Componentes Disponíveis:\n")
    
    categories = {}
    for name, (module, _) in COMPONENTS.items():
        cat = module.split('.')[-1].replace('_', ' ').title()
        if cat not in categories:
            categories[cat] = []
        categories[cat].append(name)
    
    for cat, items in sorted(categories.items()):
        print(f"  📁 {cat}:")
        for item in sorted(items):
            print(f"      • {item}")
    
    print(f"\n  Total: {len(COMPONENTS)} componentes\n")


def main():
    parser = argparse.ArgumentParser(description="Component Playground - DataPyn")
    parser.add_argument("component", nargs="?", help="Nome do componente para carregar")
    parser.add_argument("--list", "-l", action="store_true", help="Lista componentes disponíveis")
    parser.add_argument("--watch", "-w", action="store_true", help="Modo watch (hot reload)")
    
    args = parser.parse_args()
    
    if args.list:
        list_components()
        return
    
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    
    window = ComponentPlayground(
        initial_component=args.component,
        watch_mode=args.watch
    )
    window.show()
    
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
