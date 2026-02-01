# 🔄 Guia de Migração - Código Antigo → Novo

Este documento explica como **migrar código existente** para a nova arquitetura refatorada.

---

## 📋 Checklist de Migração

Para cada componente/arquivo:

- [ ] **Workers**: Mover de `main_window.py` para `src/workers/`
- [ ] **Lógica de negócio**: Extrair para `src/services/`
- [ ] **Estilos**: Substituir CSS inline por componentes do `design_system`
- [ ] **Estado**: Usar `ApplicationState` ao invés de variáveis de instância
- [ ] **Threading**: Usar workers extraídos ao invés de inline

---

## 🔧 Padrões de Migração

### 1. Workers (Threading)

#### ❌ **ANTES** (main_window.py)

```python
class SqlWorker(QObject):
    finished = pyqtSignal(object, str)
    
    def __init__(self, connector, query):
        super().__init__()
        self.connector = connector
        self.query = query
    
    def run(self):
        try:
            df = self.connector.execute_query(self.query)
            self.finished.emit(df, '')
        except Exception as e:
            self.finished.emit(None, str(e))

# Uso:
worker = SqlWorker(connector, query)
thread = QThread()
worker.moveToThread(thread)
# ... configuração complexa
```

#### ✅ **DEPOIS** (usando workers extraídos)

```python
from src.workers import SqlExecutionWorker, execute_worker

# Uso simplificado:
worker = SqlExecutionWorker(connector, query)
worker.result_ready.connect(on_result)
worker.error.connect(on_error)

thread = execute_worker(worker)  # Helper cuida de tudo
```

**Ações**:
1. **Deletar** classes de worker de `main_window.py`
2. **Importar** de `src.workers`
3. **Usar** helper `execute_worker()`

---

### 2. Services (Lógica de Negócio)

#### ❌ **ANTES** (lógica na UI)

```python
class MainWindow(QMainWindow):
    def execute_query(self):
        query = self.editor.get_code()
        
        # Lógica misturada na UI
        if not query.strip():
            QMessageBox.warning(self, "Erro", "Query vazia")
            return
        
        conn = self.connection_manager.get_active()
        if not conn:
            QMessageBox.warning(self, "Erro", "Sem conexão")
            return
        
        # Threading inline
        worker = SqlWorker(conn, query)
        # ... setup complexo
```

#### ✅ **DEPOIS** (usando services)

```python
from src.services import QueryService

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.query_service = QueryService()
    
    def execute_query(self):
        query = self.editor.get_code()
        
        # Service cuida de validação, threading, etc.
        self.query_service.execute_query(
            query,
            on_success=self.on_query_success,
            on_error=self.on_query_error,
            on_started=lambda: self.show_loading("Executando query..."),
            on_finished=self.hide_loading
        )
    
    def on_query_success(self, result: QueryResult):
        self.results_viewer.show_dataframe(result.dataframe)
        self.statusbar.showMessage(f"{result.row_count} linhas em {result.execution_time:.2f}s")
    
    def on_query_error(self, error: str):
        QMessageBox.critical(self, "Erro SQL", error)
```

**Vantagens**:
- ✅ UI mais limpa
- ✅ Lógica testável separadamente
- ✅ Callbacks claros
- ✅ Menos código duplicado

---

### 3. Estado Centralizado

#### ❌ **ANTES** (estado disperso)

```python
class MainWindow(QMainWindow):
    def __init__(self):
        self.active_connection = None
        self.sessions = {}
        self.namespace = {}
        self.current_session = None
    
    def set_connection(self, name):
        self.active_connection = name
        self.update_ui()  # Manual
    
    def add_variable(self, name, value):
        self.namespace[name] = value
        self.variables_viewer.refresh()  # Manual
```

#### ✅ **DEPOIS** (ApplicationState)

```python
from src.state import ApplicationState

class MainWindow(QMainWindow):
    def __init__(self):
        self.app_state = ApplicationState.instance()
        
        # Observar mudanças
        self.app_state.connection_changed.connect(self.on_connection_changed)
        self.app_state.variable_added.connect(self.on_variable_added)
    
    def set_connection(self, name):
        # Estado cuida de notificar observers
        self.app_state.set_active_connection(name)
    
    def on_connection_changed(self, name):
        # UI atualiza automaticamente via signal
        self.update_connection_ui(name)
    
    def add_variable(self, name, value):
        self.app_state.set_variable(name, value)
        # Variables viewer se atualiza automaticamente (observer)
```

**Vantagens**:
- ✅ Single source of truth
- ✅ UI sempre sincronizada
- ✅ Mudanças rastreáveis
- ✅ Fácil de debugar

---

### 4. Componentes UI (Design System)

#### ❌ **ANTES** (estilos inline)

```python
# Cada botão com estilo próprio
execute_btn = QPushButton("Executar")
execute_btn.setStyleSheet("""
    QPushButton {
        background-color: #0e639c;
        color: white;
        padding: 6px 16px;
        border-radius: 3px;
    }
    QPushButton:hover {
        background-color: #1177bb;
    }
""")

cancel_btn = QPushButton("Cancelar")
cancel_btn.setStyleSheet("""
    QPushButton {
        background-color: #3c3c3c;
        color: #cccccc;
        padding: 6px 16px;
    }
""")
```

#### ✅ **DEPOIS** (componentes padronizados)

```python
from src.design_system import PrimaryButton, SecondaryButton

execute_btn = PrimaryButton("Executar", icon="fa.play")
cancel_btn = SecondaryButton("Cancelar")
```

**Vantagens**:
- ✅ Código muito mais limpo
- ✅ Estilos consistentes
- ✅ Tema muda automaticamente
- ✅ Menos código duplicado

---

### 5. Painéis e Layouts

#### ❌ **ANTES**

```python
results_panel = QWidget()
layout = QVBoxLayout(results_panel)

title = QLabel("Resultados")
title.setStyleSheet("font-size: 16px; font-weight: bold; color: #cccccc;")
layout.addWidget(title)

# Separador
separator = QFrame()
separator.setFrameShape(QFrame.Shape.HLine)
layout.addWidget(separator)

content = QTableView()
layout.addWidget(content)

results_panel.setStyleSheet("background-color: #1e1e1e; border: 1px solid #3e3e42;")
```

#### ✅ **DEPOIS**

```python
from src.design_system import Panel

results_panel = Panel(title="Resultados")
results_panel.set_content(QTableView())
```

**Vantagens**:
- ✅ 1 linha vs 12 linhas
- ✅ Visual consistente
- ✅ Menos chance de erro

---

### 6. Loading States

#### ❌ **ANTES**

```python
def execute_query(self):
    # Sem feedback visual claro
    self.statusbar.showMessage("Executando...")
    # Query executa
    self.statusbar.showMessage("Pronto")
```

#### ✅ **DEPOIS**

```python
from src.design_system import LoadingOverlay

def __init__(self):
    self.loading_overlay = LoadingOverlay(self)

def execute_query(self):
    self.query_service.execute_query(
        query,
        on_started=lambda: self.loading_overlay.show_loading("Executando query..."),
        on_finished=self.loading_overlay.hide_loading,
        on_success=self.on_result
    )
```

**Vantagens**:
- ✅ Feedback visual profissional
- ✅ Usuário sabe que algo está acontecendo
- ✅ UI não parece travada

---

## 📝 Exemplo Completo: Migrar Botão de Execução

### ❌ **ANTES**

```python
class MainWindow(QMainWindow):
    def _create_toolbar(self):
        toolbar = QToolBar()
        
        # Botão com estilo inline
        run_btn = QPushButton("Executar")
        run_btn.setStyleSheet("""
            QPushButton {
                background-color: #2e7d32;
                color: white;
                padding: 8px 16px;
                border-radius: 4px;
            }
            QPushButton:hover {
                background-color: #388e3c;
            }
        """)
        run_btn.clicked.connect(self._execute_code)
        toolbar.addWidget(run_btn)
    
    def _execute_code(self):
        code = self.editor.get_code()
        
        # Validação inline
        if not code.strip():
            QMessageBox.warning(self, "Erro", "Código vazio")
            return
        
        # Threading inline
        worker = PythonWorker(code, self.namespace, False)
        thread = QThread()
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(thread.quit)
        worker.execution_complete.connect(self._on_result)
        thread.start()
        
        # Sem loading visual
    
    def _on_result(self, result, stdout, stderr):
        # Atualiza UI manualmente
        if result:
            self.output_viewer.setText(str(result))
        if stdout:
            self.output_viewer.append(stdout)
```

### ✅ **DEPOIS**

```python
from src.design_system import SuccessButton, LoadingOverlay
from src.services import PythonExecutionService

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.python_service = PythonExecutionService()
        self.loading_overlay = LoadingOverlay(self)
    
    def _create_toolbar(self):
        toolbar = QToolBar()
        
        # Componente padronizado
        run_btn = SuccessButton("Executar", icon="fa.play")
        run_btn.clicked_safe.connect(self._execute_code)
        toolbar.addWidget(run_btn)
    
    def _execute_code(self):
        code = self.editor.get_code()
        
        # Service cuida de tudo
        self.python_service.execute_code(
            code,
            on_success=self._on_result,
            on_error=self._on_error,
            on_started=lambda: self.loading_overlay.show_loading("Executando..."),
            on_finished=self.loading_overlay.hide_loading
        )
    
    def _on_result(self, result: PythonExecutionResult):
        # Atualização simplificada
        if result.result:
            self.output_viewer.setText(str(result.result))
        if result.stdout:
            self.output_viewer.append(result.stdout)
    
    def _on_error(self, error: str):
        QMessageBox.critical(self, "Erro Python", error)
```

**Melhorias**:
- ✅ 50% menos código
- ✅ Visual profissional (loading overlay)
- ✅ Lógica separada (service)
- ✅ Componente reutilizável (SuccessButton)
- ✅ Threading gerenciado pelo service
- ✅ Mais fácil de manter

---

## 🎯 Prioridades de Migração

### Alta Prioridade (fazer primeiro)

1. **Migrar workers** de `main_window.py` para `src/workers/`
2. **Extrair lógica** de execução para `services`
3. **Substituir botões** por componentes do design system

### Média Prioridade

4. **Migrar estado** para `ApplicationState`
5. **Adicionar loading states**
6. **Refatorar painéis** usando `Panel`

### Baixa Prioridade (polish)

7. **Melhorar feedback visual**
8. **Adicionar validações**
9. **Otimizações de performance**

---

## 🛠️ Como Proceder

### Passo a Passo

1. **Crie branch de feature**
   ```bash
   git checkout -b refactor/migrate-main-window
   ```

2. **Migre em pequenas partes**
   - Não refaça tudo de uma vez
   - Mantenha app funcionando
   - Commit frequente

3. **Teste após cada mudança**
   - Execute o app
   - Verifique funcionalidade
   - Garanta que nada quebrou

4. **Documente mudanças**
   - Comente código não óbvio
   - Atualize CHANGELOG.md

---

## 📚 Exemplos de Arquivos a Migrar

### Prioridade 1 (Essencial)
- [ ] `src/ui/main_window.py` (remover workers inline)
- [ ] `src/ui/components/toolbar.py` (usar design system)
- [ ] `src/ui/components/statusbar.py` (usar design system)

### Prioridade 2
- [ ] `src/ui/dialogs/connection_edit_dialog.py`
- [ ] `src/ui/dialogs/settings_dialog.py`
- [ ] `src/ui/components/results_viewer.py`

### Prioridade 3 (Polish)
- [ ] `src/core/theme_manager.py` (integrar com design system)
- [ ] `src/editors/unified_editor.py` (usar tokens de design)

---

**Qualquer dúvida, consulte**: [ARCHITECTURE.md](./ARCHITECTURE.md)
