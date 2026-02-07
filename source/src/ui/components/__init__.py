"""
Componentes de UI reutilizáveis do DataPyn

Estrutura:
- buttons.py: Botões estilizados (PrimaryButton, SecondaryButton, etc)
- inputs.py: Campos de entrada (StyledLineEdit, StyledComboBox, etc)
- toolbar.py: Toolbar principal
- statusbar.py: Barra de status
- connection_panel.py: Painel lateral de conexões
- session_tabs.py: Tabs de sessão
- editor_header.py: Header do editor com atalhos
- results_viewer.py: Visualizador de resultados
- session_widget.py: Widget completo de sessão
"""

# Botões
from .buttons import (
    DangerButton,
    GhostButton,
    IconButton,
    PrimaryButton,
    SecondaryButton,
    StyledButton,
    SuccessButton,
    ToolbarButton,
)

# Connection Panel
from .connection_panel import ActiveConnectionWidget, ConnectionItem, ConnectionPanel, ConnectionsList

# Editor Header
from .editor_header import EditorHeader

# Inputs
from .inputs import (
    FormField,
    SearchInput,
    StyledCheckBox,
    StyledComboBox,
    StyledLabel,
    StyledLineEdit,
    StyledSpinBox,
    StyledTextEdit,
)

# Results Viewer
from .results_viewer import CSVExportDialog, PandasModel, ResultsViewer

# Session Tabs
from .session_tabs import SessionTabBar, SessionTabs

# Session Widget
from .session_widget import SessionWidget

# StatusBar
from .statusbar import MainStatusBar

# Toolbar
from .toolbar import MainToolbar

__all__ = [
    # Buttons
    "StyledButton",
    "PrimaryButton",
    "SecondaryButton",
    "DangerButton",
    "SuccessButton",
    "GhostButton",
    "ToolbarButton",
    "IconButton",
    # Inputs
    "StyledLineEdit",
    "StyledTextEdit",
    "StyledSpinBox",
    "StyledComboBox",
    "StyledCheckBox",
    "StyledLabel",
    "FormField",
    "SearchInput",
    # Layout Components
    "MainToolbar",
    "MainStatusBar",
    "ConnectionPanel",
    "ConnectionItem",
    "ActiveConnectionWidget",
    "ConnectionsList",
    "SessionTabs",
    "SessionTabBar",
    "EditorHeader",
    # Data Components
    "ResultsViewer",
    "CSVExportDialog",
    "PandasModel",
    "SessionWidget",
]
