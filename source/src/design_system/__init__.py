"""
Design System - Sistema de design centralizado

Exporta tokens, componentes base e utilities
"""

from .tokens import (
    ColorPalette,
    Typography,
    Spacing,
    Radius,
    Shadow,
    DARK_COLORS,
    LIGHT_COLORS,
    TYPOGRAPHY,
    SPACING,
    RADIUS,
    SHADOW,
    get_colors,
    get_theme,
    set_theme,
    # New additions
    StateColors,
    ChartColors,
    get_state_colors,
    get_chart_colors,
    # Stylesheet generators
    get_button_stylesheet,
    get_input_stylesheet,
    get_combobox_stylesheet,
    get_panel_stylesheet,
    get_statusbar_connected_stylesheet,
    get_statusbar_disconnected_stylesheet,
    get_dock_stylesheet,
    get_tab_stylesheet,
    get_scrollbar_stylesheet,
    get_table_stylesheet,
    get_list_stylesheet,
    get_tree_stylesheet,
    get_groupbox_stylesheet,
    get_checkbox_stylesheet,
    get_dialog_base_stylesheet,
)

from .button import (
    Button,
    PrimaryButton,
    SecondaryButton,
    DangerButton,
    SuccessButton,
    GhostButton,
)

from .input import (
    Input,
    FormField,
)

from .panel import (
    Panel,
    PanelGroup,
)

from .loading import (
    LoadingSpinner,
    ProgressIndicator,
    LoadingOverlay,
)

from .icon_button import (
    IconButton,
    PlayButton,
    StopButton,
    CloseButton,
    AddButton,
    RefreshButton,
    SettingsButton,
)

from .status_badge import (
    BadgeState,
    StatusBadge,
    ExecutionStatusBadge,
    ConnectionStatusBadge,
)

from .headers import (
    SectionHeader,
    DialogHeader,
    Divider,
    VerticalDivider,
    ButtonBar,
    Card,
    EmptyState,
)

from .dialog import (
    BaseDialog,
    ConfirmDialog,
    InputDialog,
    MessageDialog,
)

from .stylesheet import (
    get_main_window_stylesheet,
    get_dock_widget_stylesheet,
    get_bottom_dock_stylesheet,
    get_tab_widget_stylesheet,
    get_execution_label_stylesheet,
    get_connection_status_stylesheet,
    get_empty_state_stylesheet,
    get_start_button_stylesheet,
)

__all__ = [
    # Tokens
    "ColorPalette",
    "Typography",
    "Spacing",
    "Radius",
    "Shadow",
    "DARK_COLORS",
    "LIGHT_COLORS",
    "TYPOGRAPHY",
    "SPACING",
    "RADIUS",
    "SHADOW",
    "get_colors",
    "get_theme",
    "set_theme",
    # State and Chart Colors
    "StateColors",
    "ChartColors",
    "get_state_colors",
    "get_chart_colors",
    # Stylesheet Generators
    "get_button_stylesheet",
    "get_input_stylesheet",
    "get_combobox_stylesheet",
    "get_panel_stylesheet",
    "get_statusbar_connected_stylesheet",
    "get_statusbar_disconnected_stylesheet",
    "get_dock_stylesheet",
    "get_tab_stylesheet",
    "get_scrollbar_stylesheet",
    "get_table_stylesheet",
    "get_list_stylesheet",
    "get_tree_stylesheet",
    "get_groupbox_stylesheet",
    "get_checkbox_stylesheet",
    "get_dialog_base_stylesheet",
    # Buttons
    "Button",
    "PrimaryButton",
    "SecondaryButton",
    "DangerButton",
    "SuccessButton",
    "GhostButton",
    # Inputs
    "Input",
    "FormField",
    # Panels
    "Panel",
    "PanelGroup",
    # Loading
    "LoadingSpinner",
    "ProgressIndicator",
    "LoadingOverlay",
    # Icon Buttons
    "IconButton",
    "PlayButton",
    "StopButton",
    "CloseButton",
    "AddButton",
    "RefreshButton",
    "SettingsButton",
    # Status Badges
    "BadgeState",
    "StatusBadge",
    "ExecutionStatusBadge",
    "ConnectionStatusBadge",
    # Headers and Layout
    "SectionHeader",
    "DialogHeader",
    "Divider",
    "VerticalDivider",
    "ButtonBar",
    "Card",
    "EmptyState",
    # Dialogs
    "BaseDialog",
    "ConfirmDialog",
    "InputDialog",
    "MessageDialog",
    # Application Stylesheets
    "get_main_window_stylesheet",
    "get_dock_widget_stylesheet",
    "get_bottom_dock_stylesheet",
    "get_tab_widget_stylesheet",
    "get_execution_label_stylesheet",
    "get_connection_status_stylesheet",
    "get_empty_state_stylesheet",
    "get_start_button_stylesheet",
]
