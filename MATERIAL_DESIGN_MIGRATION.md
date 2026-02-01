# Migração para Material Design

## ✅ Concluído

### 1. Instalação de Bibliotecas
- **qt-material**: Tema Material Design para PyQt6
- **qtawesome**: Biblioteca de ícones (Material Design Icons, Font Awesome, etc.)

### 2. Aplicação do Tema Global
**Arquivo**: `main.py`

```python
from qt_material import apply_stylesheet

apply_stylesheet(app, theme='dark_blue.xml', extra={
    'danger': '#dc3545',
    'warning': '#ffc107',
    'success': '#28a745',
    'primaryColor': '#0d6efd'
})
```

### 3. Componentes Convertidos

#### **Toolbar** (`src/ui/components/toolbar.py`)
- ✅ Substituído emojis por ícones Material Design
- ✅ Botões com `QPushButton` + `qtawesome.icon()`
- Ícones usados:
  - `mdi.tab-plus` - Nova sessão
  - `mdi.database-plus` - Nova conexão
  - `mdi.play-circle` (verde) - Executar

#### **StatusBar** (`src/ui/components/statusbar.py`)
- ✅ Removido custom styling
- ✅ Ícones de conexão com status visual
- Ícones usados:
  - `mdi.database-check` (verde) - Conectado
  - `mdi.database-off` (cinza) - Desconectado

#### **Connection Panel** (`src/ui/components/connection_panel.py`)
- ✅ Removido design system custom
- ✅ Botões com ícones Material
- Ícones usados:
  - `mdi.link-off` - Desconectar
  - `mdi.plus-circle` - Nova conexão
  - `mdi.cog` - Gerenciar conexões

---

## 🔄 Próximos Passos

### Fase 1: Diálogos (Alta Prioridade)
Arquivos que precisam de conversão:

1. **`src/ui/dialogs/connection_edit_dialog.py`**
   - Formulário de edição de conexão
   - Ícones sugeridos: `mdi.database-edit`, `mdi.server`, `mdi.account`
   - Remover custom styling
   - Usar componentes Qt padrão com tema Material

2. **`src/ui/dialogs/connections_manager_dialog.py`**
   - Lista de conexões salvas
   - Ícones sugeridos: `mdi.database-settings`, `mdi.pencil`, `mdi.delete`
   - Botões de ação com ícones

3. **`src/ui/dialogs/settings_dialog.py`**
   - Configurações gerais
   - Ícones sugeridos: `mdi.cog`, `mdi.palette`, `mdi.format-font`

### Fase 2: Visualizadores de Dados
4. **`src/ui/components/results_viewer.py`**
   - Grid de resultados
   - Ícones sugeridos: `mdi.table-eye`, `mdi.chart-bar`, `mdi.export`

5. **`src/ui/components/variables_panel.py`**
   - Painel de variáveis Python
   - Ícones sugeridos: `mdi.variable`, `mdi.code-braces`

### Fase 3: Gerenciamento de Sessões
6. **`src/ui/components/session_tabs.py`**
   - Abas de sessões SQL/Python
   - Ícones sugeridos: `mdi.tab`, `mdi.close`, `mdi.file-code`

7. **`src/ui/components/session_widget.py`**
   - Widget de sessão individual

---

## 📖 Guia de Ícones Material Design

### Banco de Dados
- `mdi.database` - Banco genérico
- `mdi.database-plus` - Adicionar conexão
- `mdi.database-check` - Conectado
- `mdi.database-off` - Desconectado
- `mdi.database-edit` - Editar conexão
- `mdi.database-settings` - Configurações DB
- `mdi.server` - Servidor

### Ações
- `mdi.play-circle` - Executar
- `mdi.stop` - Parar
- `mdi.refresh` - Atualizar
- `mdi.content-save` - Salvar
- `mdi.delete` - Excluir
- `mdi.pencil` - Editar

### Arquivos
- `mdi.file-code` - Arquivo de código
- `mdi.file-document` - Documento
- `mdi.folder` - Pasta

### Status
- `mdi.check-circle` - Sucesso
- `mdi.alert-circle` - Atenção
- `mdi.information` - Info
- `mdi.close-circle` - Erro

### Navegação
- `mdi.tab` - Aba
- `mdi.tab-plus` - Nova aba
- `mdi.close` - Fechar
- `mdi.menu` - Menu

### UI
- `mdi.cog` - Configurações
- `mdi.palette` - Tema/Cores
- `mdi.format-font` - Fonte
- `mdi.eye` - Visualizar
- `mdi.table-eye` - Visualizar tabela

---

## 🎨 Como Usar Ícones

### Exemplo Básico
```python
import qtawesome as qta
from PyQt6.QtWidgets import QPushButton

# Botão com ícone
btn = QPushButton(" Executar")
btn.setIcon(qta.icon('mdi.play-circle', color='#4caf50'))
```

### Ícone Colorido
```python
# Verde (sucesso)
icon_success = qta.icon('mdi.check-circle', color='#4caf50')

# Vermelho (erro)
icon_error = qta.icon('mdi.alert-circle', color='#f44336')

# Azul (info)
icon_info = qta.icon('mdi.information', color='#2196f3')
```

### Botão com objectName para Material Theme
```python
btn = QPushButton(" Conectar")
btn.setIcon(qta.icon('mdi.database-plus', color='white'))
btn.setObjectName("primary")  # Aplica estilo primary do tema
```

Valores possíveis:
- `"primary"` - Azul
- `"danger"` - Vermelho
- `"success"` - Verde
- `"warning"` - Amarelo

---

## 🗑️ Código Legado a Remover

### Design System Custom
Após conversão completa, estes arquivos podem ser arquivados:

- `src/design_system/tokens.py`
- `src/design_system/button.py`
- `src/design_system/input.py`
- `src/design_system/panel.py`
- `src/design_system/loading.py`

**Motivo**: qt-material já fornece todos esses componentes estilizados.

### Imports Antigos
Remover imports como:
```python
from src.design_system import PrimaryButton, SecondaryButton, DangerButton
from src.design_system import get_colors, TYPOGRAPHY, SPACING
```

Substituir por componentes Qt padrão + tema Material.

---

## 🧪 Checklist de Conversão

Para cada componente:

- [ ] Remover imports de `src.design_system`
- [ ] Substituir botões custom por `QPushButton` com ícones
- [ ] Remover `setStyleSheet()` custom (deixar tema cuidar)
- [ ] Trocar emojis por ícones `qtawesome`
- [ ] Usar `setObjectName()` para variantes (primary, danger, etc.)
- [ ] Testar visualmente com tema dark_blue

---

## 📝 Notas Técnicas

### Tamanhos de Ícones
```python
# Tamanho padrão
icon.pixmap(16, 16)  # StatusBar

# Tamanho médio
icon.pixmap(24, 24)  # Toolbar

# Tamanho grande
icon.pixmap(32, 32)  # Dialogs
```

### Tema Customizado
O tema `dark_blue.xml` foi customizado com:
```python
extra={
    'danger': '#dc3545',    # Bootstrap danger
    'warning': '#ffc107',   # Bootstrap warning
    'success': '#28a745',   # Bootstrap success
    'primaryColor': '#0d6efd'  # Bootstrap primary
}
```

### Performance
- Ícones são cacheados automaticamente pelo qtawesome
- Não há impacto de performance em usar ícones vs emojis
- Material theme CSS é aplicado uma vez no startup

---

## 🎯 Objetivo Final

Interface moderna, profissional e consistente:
- ✅ Tema Material Design unificado
- ✅ Ícones vetoriais profissionais
- ✅ Sem emojis ou styling custom
- ✅ Componentes Qt nativos + tema
- ✅ Código limpo e manutenível
