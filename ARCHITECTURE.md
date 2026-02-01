# 🏗️ Arquitetura Refatorada - DataPyn

## 📋 Visão Geral

A aplicação foi completamente reestruturada seguindo **princípios de Clean Architecture, SOLID e Design System moderno** (inspirado em shadcn/ui).

### Objetivos Alcançados ✅

- ✅ **Separação clara de responsabilidades** (UI / Lógica / Dados)
- ✅ **Estado centralizado** (Single Source of Truth)
- ✅ **Threading desacoplado** da UI
- ✅ **Design System consistente** (tokens, componentes reutilizáveis)
- ✅ **Código testável e manutenível**
- ✅ **Performance** (operações pesadas em background)

---

## 📁 Nova Estrutura de Pastas

```
src/
├── design_system/       # Sistema de design (tokens + componentes base)
│   ├── __init__.py
│   ├── tokens.py        # Cores, tipografia, espaçamentos, sombras
│   ├── button.py        # Componente Button
│   ├── input.py         # Componente Input/FormField
│   ├── panel.py         # Componente Panel/PanelGroup
│   └── loading.py       # Componentes de Loading/Progress
│
├── state/               # Gerenciamento de estado centralizado
│   ├── __init__.py
│   └── app_state.py     # ApplicationState (singleton)
│
├── services/            # Camada de lógica de negócio
│   ├── __init__.py
│   ├── query_service.py           # Serviço de queries SQL
│   ├── python_execution_service.py # Serviço de execução Python
│   └── connection_service.py      # Serviço de conexões
│
├── workers/             # Workers para threading (background)
│   └── __init__.py      # SqlExecutionWorker, PythonExecutionWorker, etc.
│
├── database/            # Camada de dados (mantida)
│   ├── connection_manager.py
│   └── database_connector.py
│
├── editors/             # Editores de código (mantidos)
│   ├── unified_editor.py
│   ├── sql_editor.py
│   └── python_editor.py
│
├── ui/                  # Interface de usuário
│   ├── components/      # Componentes UI específicos
│   │   ├── results_viewer.py
│   │   ├── session_tabs.py
│   │   ├── connection_panel.py
│   │   ├── toolbar.py
│   │   └── statusbar.py
│   ├── dialogs/         # Diálogos
│   │   ├── connection_edit_dialog.py
│   │   ├── connections_manager_dialog.py
│   │   └── settings_dialog.py
│   └── main_window.py   # Janela principal
│
└── core/                # Componentes core (mantidos/refatorados)
    ├── mixed_executor.py
    ├── results_manager.py
    ├── workspace_manager.py
    ├── session_manager.py
    ├── shortcut_manager.py
    └── theme_manager.py
```

---

## 🎯 Camadas da Aplicação

### 1️⃣ **Design System** (`src/design_system/`)

**Responsabilidade**: Tokens visuais e componentes UI base reutilizáveis.

#### Tokens (`tokens.py`)
- **Cores**: Paletas dark/light com cores semânticas
- **Tipografia**: Famílias, tamanhos, pesos
- **Espaçamentos**: Sistema consistente (4px, 8px, 12px, etc.)
- **Bordas**: Border radius padronizados
- **Sombras**: Elevações visuais

```python
from src.design_system import get_colors, TYPOGRAPHY, SPACING

colors = get_colors()  # Retorna paleta do tema ativo
print(colors.interactive_primary)  # "#0e639c"
```

#### Componentes Base
- **Button**: Primary, Secondary, Danger, Success, Ghost
  - Estados: normal, hover, active, disabled, loading
  - Tamanhos: sm, md, lg
  
- **Input/FormField**: Campos de formulário com validação
  - Estados: normal, focus, error, disabled
  
- **Panel**: Agrupamento visual (similar a Card)
  - Com/sem título, bordas, elevação
  
- **Loading**: Spinners, progress bars, overlays

**Princípios**:
- ✅ Componentes **não conhecem** lógica de negócio
- ✅ Apenas **recebem props** e **emitem eventos**
- ✅ Estilos vêm de **tokens centralizados**
- ✅ Todos seguem o **mesmo padrão visual**

---

### 2️⃣ **State Management** (`src/state/`)

**Responsabilidade**: Estado global da aplicação (Single Source of Truth).

#### ApplicationState (`app_state.py`)

Singleton que centraliza:
- **Conexões ativas** (nome, tipo, status)
- **Sessões abertas** (abas de código)
- **Namespace Python** (variáveis compartilhadas)
- **Configurações** (tema, fonte, etc.)

**Padrão Observer**: Emite sinais quando estado muda.

```python
from src.state import ApplicationState

state = ApplicationState.instance()

# Observar mudanças
state.connection_changed.connect(on_connection_changed)

# Modificar estado
state.set_active_connection("my_db")
state.set_variable("df", dataframe)
```

**Por que?**
- ✅ **Uma fonte de verdade** para todo o estado
- ✅ **Mudanças rastreáveis** via signals
- ✅ **UI sempre sincronizada** com estado
- ✅ **Fácil de testar** (mock do estado)

---

### 3️⃣ **Services** (`src/services/`)

**Responsabilidade**: Lógica de negócio pura, desacoplada da UI.

#### QueryService
Executa queries SQL:
- Valida query
- Executa via worker (async)
- Atualiza estado
- Mantém histórico

```python
from src.services import QueryService

service = QueryService()
service.execute_query(
    "SELECT * FROM users",
    on_success=handle_result,
    on_error=handle_error
)
```

#### PythonExecutionService
Executa código Python:
- Valida sintaxe
- Executa via worker (async)
- Captura stdout/stderr
- Sincroniza namespace com estado

#### ConnectionService
Gerencia conexões:
- Conecta via worker (async)
- Testa conexões
- Sincroniza com estado

**Vantagens**:
- ✅ **UI não conhece detalhes** de execução
- ✅ **Lógica reutilizável** (CLI, testes, etc.)
- ✅ **Fácil de testar** isoladamente
- ✅ **Callbacks claros** para UI

---

### 4️⃣ **Workers** (`src/workers/`)

**Responsabilidade**: Executar operações pesadas em threads separadas.

Todos os workers:
- ✅ **Herdam de BaseWorker**
- ✅ **Emitem signals** (started, finished, error)
- ✅ **Nunca manipulam UI** diretamente
- ✅ **Executam em QThread**

Workers disponíveis:
- `SqlExecutionWorker`
- `DatabaseConnectionWorker`
- `PythonExecutionWorker`
- `MixedSyntaxExecutionWorker`
- `DataFrameOperationWorker`

```python
from src.workers import SqlExecutionWorker, execute_worker

worker = SqlExecutionWorker(connector, query)
worker.result_ready.connect(on_result)
worker.error.connect(on_error)

thread = execute_worker(worker)  # Helper function
```

**Por que separar?**
- ✅ **UI nunca trava** (operações pesadas em background)
- ✅ **Código limpo** (worker não conhece UI)
- ✅ **Reutilizável** (mesmos workers para diferentes UIs)

---

### 5️⃣ **UI Components** (`src/ui/components/`)

**Responsabilidade**: Componentes UI específicos da aplicação.

Diferença de `design_system`:
- **design_system**: Componentes **genéricos** (Button, Input, Panel)
- **ui/components**: Componentes **específicos** (ResultsViewer, ConnectionPanel)

Exemplos:
- `ResultsViewer`: Exibe DataFrames
- `SessionTabs`: Gerencia abas de código
- `ConnectionPanel`: Painel de conexões
- `MainToolbar`: Toolbar principal

**Regras**:
- ✅ Usam componentes do `design_system`
- ✅ Conectam-se a **services** para ações
- ✅ Observam **ApplicationState** para atualizar UI
- ✅ **Não contêm lógica** de negócio

---

## 🔄 Fluxo de Dados

### Exemplo: Executar Query SQL

```
┌─────────────┐
│ UI (Button) │ Usuário clica "Executar"
└──────┬──────┘
       │
       ▼
┌─────────────────┐
│ QueryService    │ service.execute_query(...)
└────────┬────────┘
         │
         ▼
┌──────────────────────┐
│ SqlExecutionWorker   │ Executa em background thread
└──────────┬───────────┘
           │
           ▼
┌─────────────────────┐
│ Signal: result_ready │
└──────────┬──────────┘
           │
           ▼
┌─────────────────────┐
│ ApplicationState    │ state.set_variable("result", df)
└──────────┬──────────┘
           │
           ▼ (signal: variable_changed)
┌─────────────────────┐
│ ResultsViewer (UI)  │ Atualiza tabela visual
└─────────────────────┘
```

**Vantagens**:
- ✅ **UI nunca trava** (thread separada)
- ✅ **Estado centralizado** (ApplicationState)
- ✅ **Fácil rastreabilidade** (signals)

---

## 🎨 Design System - Padrões Visuais

### Cores Semânticas

```python
# Ao invés de cores hardcoded:
button.setStyleSheet("background-color: #0e639c;")  # ❌

# Use tokens semânticos:
colors = get_colors()
button.setStyleSheet(f"background-color: {colors.interactive_primary};")  # ✅
```

### Componentes Consistentes

**Antes (código atual)**:
```python
# Cada botão com estilo diferente
btn1 = QPushButton("OK")
btn1.setStyleSheet("background: blue; padding: 8px;")

btn2 = QPushButton("Cancel")
btn2.setStyleSheet("background: gray; padding: 6px;")
```

**Depois (refatorado)**:
```python
# Componentes padronizados
from src.design_system import PrimaryButton, SecondaryButton

btn1 = PrimaryButton("OK")
btn2 = SecondaryButton("Cancel")
```

---

## 📝 Princípios SOLID Aplicados

### **SRP (Single Responsibility)**
- Cada classe tem **uma responsabilidade**
- `QueryService` → executa queries
- `ApplicationState` → gerencia estado
- `Button` → renderiza botão

### **OCP (Open/Closed)**
- Componentes **extensíveis sem modificação**
- Novos buttons via herança (`DangerButton`, `SuccessButton`)
- Novos workers via `BaseWorker`

### **DIP (Dependency Inversion)**
- UI depende de **abstrações** (services), não implementações
- Services usam **callbacks**, não conhecem UI específica

---

## 🚀 Próximos Passos

### Migração Gradual

**Fase 1** (Completa ✅):
- ✅ Design System criado
- ✅ State Management implementado
- ✅ Services extraídos
- ✅ Workers separados

**Fase 2** (Próximo):
- 🔄 Refatorar `MainWindow` para usar services
- 🔄 Substituir workers inline por workers extraídos
- 🔄 Migrar componentes para design system

**Fase 3**:
- 🔄 Refatorar dialogs (Connection, Settings)
- 🔄 Melhorar theme switching
- 🔄 Adicionar testes unitários

**Fase 4**:
- 🔄 Otimizações de performance
- 🔄 Feedback visual melhorado
- 🔄 Documentação completa

---

## 💡 Boas Práticas

### ✅ **FAZER**
- Usar componentes do `design_system`
- Conectar UI a `services`, não lógica direta
- Observar `ApplicationState` para mudanças
- Executar operações pesadas via `workers`
- Usar tokens de design (cores, espaçamentos)

### ❌ **NÃO FAZER**
- Colocar lógica de negócio em componentes UI
- Acessar banco de dados diretamente da UI
- Criar estilos CSS inline sem usar tokens
- Bloquear UI com operações síncronas
- Duplicar código entre componentes

---

## 📚 Referências

- **Design System**: Inspirado em [shadcn/ui](https://ui.shadcn.com/)
- **Arquitetura**: Clean Architecture (Robert C. Martin)
- **SOLID**: Princípios de OOP
- **State Management**: Pattern Observer (Qt Signals/Slots)

---

## 🎓 Para Novos Desenvolvedores

### Como criar um novo botão?

```python
from src.design_system import Button

btn = Button(
    "Meu Botão",
    variant="primary",  # primary, secondary, danger, success, ghost
    size="md",          # sm, md, lg
    icon="fa.save"      # Ícone FontAwesome (opcional)
)
btn.clicked_safe.connect(on_click)  # Só emite se não disabled/loading
```

### Como executar uma query?

```python
from src.services import QueryService

service = QueryService()
service.execute_query(
    "SELECT * FROM users WHERE active = 1",
    on_success=lambda result: print(f"Rows: {result.row_count}"),
    on_error=lambda err: print(f"Erro: {err}")
)
```

### Como adicionar variável ao namespace?

```python
from src.state import ApplicationState
import pandas as pd

state = ApplicationState.instance()
df = pd.DataFrame({"col": [1, 2, 3]})
state.set_variable("meu_df", df)  # Disponível em todo o app
```

---

**Última atualização**: Fevereiro 2026  
**Versão**: 2.0 (Refatorada)
