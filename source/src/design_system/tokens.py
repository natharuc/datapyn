"""
Design Tokens - Centralized design system

Inspired by shadcn/ui, defines all visual tokens of the application:
- Colors
- Typography
- Spacing
- Shadows
- Borders
- Animations
"""

from dataclasses import dataclass
from typing import Dict


@dataclass
class ColorPalette:
    """Semantic color palette"""

    # Backgrounds
    bg_primary: str
    bg_secondary: str
    bg_tertiary: str
    bg_elevated: str
    bg_overlay: str

    # Borders
    border_default: str
    border_muted: str
    border_strong: str

    # Text
    text_primary: str
    text_secondary: str
    text_tertiary: str
    text_disabled: str
    text_inverse: str

    # Interactive
    interactive_primary: str
    interactive_primary_hover: str
    interactive_primary_active: str
    interactive_secondary: str
    interactive_secondary_hover: str
    interactive_secondary_active: str

    # Semantic
    success: str
    success_hover: str
    success_active: str
    warning: str
    warning_hover: str
    warning_active: str
    danger: str
    danger_hover: str
    danger_active: str
    info: str
    info_hover: str
    info_active: str

    # Editor
    editor_bg: str
    editor_fg: str
    editor_selection: str
    editor_line_highlight: str
    editor_gutter_bg: str
    editor_gutter_fg: str


@dataclass
class Typography:
    """Typographic system"""

    # Families
    font_family_primary: str
    font_family_mono: str

    # Sizes (rem equivalents)
    text_xs: int  # 11px
    text_sm: int  # 12px
    text_base: int  # 14px
    text_lg: int  # 16px
    text_xl: int  # 18px
    text_2xl: int  # 20px
    text_3xl: int  # 24px

    # Weights
    font_regular: int
    font_medium: int
    font_semibold: int
    font_bold: int

    # Line heights
    leading_tight: float
    leading_normal: float
    leading_relaxed: float


@dataclass
class Spacing:
    """Consistent spacing system"""

    space_0: int  # 0px
    space_1: int  # 4px
    space_2: int  # 8px
    space_3: int  # 12px
    space_4: int  # 16px
    space_5: int  # 20px
    space_6: int  # 24px
    space_8: int  # 32px
    space_10: int  # 40px
    space_12: int  # 48px
    space_16: int  # 64px


@dataclass
class Radius:
    """Border radius"""

    radius_none: int
    radius_sm: int
    radius_md: int
    radius_lg: int
    radius_full: int


@dataclass
class Shadow:
    """Sombras"""

    shadow_none: str
    shadow_sm: str
    shadow_md: str
    shadow_lg: str
    shadow_xl: str


# =============================================================================
# DARK THEME (VS Code inspired)
# =============================================================================

DARK_COLORS = ColorPalette(
    # Backgrounds - VS Code style with subtle blue undertone
    bg_primary="#181a1f",
    bg_secondary="#1f2228",
    bg_tertiary="#282c34",
    bg_elevated="#353a45",
    bg_overlay="rgba(0, 0, 0, 0.65)",
    # Borders - subtle but visible
    border_default="#3a3f4b",
    border_muted="#2a2e38",
    border_strong="#50556b",
    # Text - high contrast for readability
    text_primary="#dcdee4",
    text_secondary="#a0a4b0",
    text_tertiary="#70758a",
    text_disabled="#50556b",
    text_inverse="#ffffff",
    # Interactive - modern blue accent (VS Code/GitHub style)
    interactive_primary="#3b82f6",
    interactive_primary_hover="#60a5fa",
    interactive_primary_active="#2563eb",
    interactive_secondary="#353a45",
    interactive_secondary_hover="#454b58",
    interactive_secondary_active="#2a2e38",
    # Semantic - vibrant but professional
    success="#22c55e",
    success_hover="#4ade80",
    success_active="#16a34a",
    warning="#f59e0b",
    warning_hover="#fbbf24",
    warning_active="#d97706",
    danger="#ef4444",
    danger_hover="#f87171",
    danger_active="#dc2626",
    info="#3b82f6",
    info_hover="#60a5fa",
    info_active="#2563eb",
    # Editor
    editor_bg="#1e1e1e",
    editor_fg="#d4d4d4",
    editor_selection="#264f78",
    editor_line_highlight="#2a2d2e",
    editor_gutter_bg="#1e1e1e",
    editor_gutter_fg="#858585",
)


LIGHT_COLORS = ColorPalette(
    # Backgrounds
    bg_primary="#ffffff",
    bg_secondary="#f5f5f5",
    bg_tertiary="#eeeeee",
    bg_elevated="#fafafa",
    bg_overlay="rgba(0, 0, 0, 0.5)",
    # Borders
    border_default="#e0e0e0",
    border_muted="#f0f0f0",
    border_strong="#bdbdbd",
    # Text
    text_primary="#333333",
    text_secondary="#666666",
    text_tertiary="#999999",
    text_disabled="#bdbdbd",
    text_inverse="#ffffff",
    # Interactive
    interactive_primary="#3369FF",
    interactive_primary_hover="#4d7fff",
    interactive_primary_active="#2952cc",
    interactive_secondary="#e0e0e0",
    interactive_secondary_hover="#d0d0d0",
    interactive_secondary_active="#c0c0c0",
    # Semantic
    success="#2e7d32",
    success_hover="#388e3c",
    success_active="#1b5e20",
    warning="#ed6c02",
    warning_hover="#ff9800",
    warning_active="#c77700",
    danger="#d32f2f",
    danger_hover="#e53935",
    danger_active="#b71c1c",
    info="#0288d1",
    info_hover="#03a9f4",
    info_active="#01579b",
    # Editor
    editor_bg="#ffffff",
    editor_fg="#000000",
    editor_selection="#add6ff",
    editor_line_highlight="#f0f0f0",
    editor_gutter_bg="#f5f5f5",
    editor_gutter_fg="#237893",
)


TYPOGRAPHY = Typography(
    font_family_primary="Inter, SF Pro Display, Roboto, -apple-system, BlinkMacSystemFont, sans-serif",
    font_family_mono="JetBrains Mono, Fira Code, Consolas, monospace",
    text_xs=11,
    text_sm=12,
    text_base=14,
    text_lg=16,
    text_xl=18,
    text_2xl=20,
    text_3xl=24,
    font_regular=400,
    font_medium=500,
    font_semibold=600,
    font_bold=700,
    leading_tight=1.2,
    leading_normal=1.5,
    leading_relaxed=1.75,
)


SPACING = Spacing(
    space_0=0,
    space_1=4,
    space_2=8,
    space_3=12,
    space_4=16,
    space_5=20,
    space_6=24,
    space_8=32,
    space_10=40,
    space_12=48,
    space_16=64,
)


RADIUS = Radius(
    radius_none=0,
    radius_sm=8,
    radius_md=12,
    radius_lg=16,
    radius_full=9999,
)


SHADOW = Shadow(
    shadow_none="none",
    shadow_sm="0 1px 3px rgba(0, 0, 0, 0.08), 0 1px 2px rgba(0, 0, 0, 0.06)",
    shadow_md="0 4px 6px rgba(0, 0, 0, 0.07), 0 2px 4px rgba(0, 0, 0, 0.05)",
    shadow_lg="0 10px 15px rgba(0, 0, 0, 0.08), 0 4px 6px rgba(0, 0, 0, 0.04)",
    shadow_xl="0 20px 25px rgba(0, 0, 0, 0.10), 0 8px 10px rgba(0, 0, 0, 0.05)",
)


# Tema ativo (pode ser trocado dinamicamente)
_current_theme = "dark"


def get_colors() -> ColorPalette:
    """Retorna paleta de cores do tema ativo"""
    return DARK_COLORS if _current_theme == "dark" else LIGHT_COLORS


def set_theme(theme: str):
    """Altera tema ativo"""
    global _current_theme
    if theme in ("dark", "light"):
        _current_theme = theme


def get_theme() -> str:
    """Retorna tema ativo"""
    return _current_theme

# =============================================================================
# ADDITIONAL TOKENS - State Colors, Chart Colors, etc.
# =============================================================================

@dataclass
class StateColors:
    """Colors for execution states and status indicators"""
    
    # Execution states
    running: str = "#f39c12"           # Amber/yellow for running
    running_text: str = "#000000"       # Black text on running
    running_bg: str = "#fff3cd"         # Light amber background
    
    # Connection states  
    connected: str = "#4ec9b0"          # Teal for connected
    disconnected: str = "#f48771"       # Salmon for disconnected
    connecting: str = "#f39c12"         # Amber for connecting
    
    # Validation states
    valid: str = "#2e7d32"
    invalid: str = "#d32f2f"
    pending: str = "#ed6c02"


@dataclass
class ChartColors:
    """Colors for matplotlib and chart rendering"""
    
    figure_bg: str = "#1e1e1e"
    axes_bg: str = "#2d2d30"
    axes_edge: str = "#555555"
    text: str = "#d4d4d4"
    grid: str = "#3e3e42"
    legend_bg: str = "#2d2d30"
    legend_edge: str = "#555555"


# Singleton instances
DARK_STATE_COLORS = StateColors()
DARK_CHART_COLORS = ChartColors()

LIGHT_STATE_COLORS = StateColors(
    running="#f39c12",
    running_text="#000000",
    running_bg="#fff3cd",
    connected="#2e7d32",
    disconnected="#d32f2f",
    connecting="#ed6c02",
    valid="#2e7d32",
    invalid="#d32f2f",
    pending="#ed6c02",
)

LIGHT_CHART_COLORS = ChartColors(
    figure_bg="#ffffff",
    axes_bg="#f5f5f5",
    axes_edge="#cccccc",
    text="#333333",
    grid="#e0e0e0",
    legend_bg="#f5f5f5",
    legend_edge="#cccccc",
)


def get_state_colors() -> StateColors:
    """Returns state colors for current theme"""
    return DARK_STATE_COLORS if _current_theme == "dark" else LIGHT_STATE_COLORS


def get_chart_colors() -> ChartColors:
    """Returns chart colors for current theme"""
    return DARK_CHART_COLORS if _current_theme == "dark" else LIGHT_CHART_COLORS


# =============================================================================
# STYLESHEET GENERATORS - Centralized CSS generation
# =============================================================================

def get_button_stylesheet(variant: str = "primary") -> str:
    """
    Returns stylesheet for buttons.
    
    Args:
        variant: primary, secondary, danger, success, ghost
    """
    colors = get_colors()
    
    variants = {
        "primary": {
            "bg": colors.interactive_primary,
            "bg_hover": colors.interactive_primary_hover,
            "bg_active": colors.interactive_primary_active,
            "fg": colors.text_inverse,
            "border": "none",
        },
        "secondary": {
            "bg": colors.interactive_secondary,
            "bg_hover": colors.interactive_secondary_hover,
            "bg_active": colors.interactive_secondary_active,
            "fg": colors.text_primary,
            "border": f"1px solid {colors.border_default}",
        },
        "danger": {
            "bg": colors.danger,
            "bg_hover": colors.danger_hover,
            "bg_active": colors.danger_active,
            "fg": colors.text_inverse,
            "border": "none",
        },
        "success": {
            "bg": colors.success,
            "bg_hover": colors.success_hover,
            "bg_active": colors.success_active,
            "fg": colors.text_inverse,
            "border": "none",
        },
        "ghost": {
            "bg": "transparent",
            "bg_hover": colors.interactive_secondary,
            "bg_active": colors.interactive_secondary_active,
            "fg": colors.text_primary,
            "border": "none",
        },
    }
    
    v = variants.get(variant, variants["primary"])
    
    return f"""
        QPushButton {{
            background-color: {v["bg"]};
            color: {v["fg"]};
            border: {v["border"]};
            padding: {SPACING.space_2}px {SPACING.space_4}px;
            border-radius: {RADIUS.radius_sm}px;
            font-weight: {TYPOGRAPHY.font_semibold};
            font-size: {TYPOGRAPHY.text_sm}px;
            min-height: 24px;
        }}
        QPushButton:hover {{
            background-color: {v["bg_hover"]};
        }}
        QPushButton:pressed {{
            background-color: {v["bg_active"]};
        }}
        QPushButton:disabled {{
            background-color: {colors.bg_tertiary};
            color: {colors.text_disabled};
        }}
    """


def get_input_stylesheet() -> str:
    """Returns stylesheet for input fields"""
    colors = get_colors()
    
    return f"""
        QLineEdit, QTextEdit, QPlainTextEdit {{
            background-color: {colors.bg_secondary};
            color: {colors.text_primary};
            border: 1px solid {colors.border_default};
            padding: {SPACING.space_2}px {SPACING.space_3}px;
            border-radius: {RADIUS.radius_sm}px;
            font-size: {TYPOGRAPHY.text_sm}px;
            min-height: 20px;
        }}
        QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus {{
            border-color: {colors.interactive_primary};
            border-width: 2px;
        }}
        QLineEdit:disabled, QTextEdit:disabled, QPlainTextEdit:disabled {{
            background-color: {colors.bg_tertiary};
            color: {colors.text_disabled};
        }}
    """


def get_combobox_stylesheet() -> str:
    """Returns stylesheet for comboboxes"""
    colors = get_colors()
    
    return f"""
        QComboBox {{
            background-color: {colors.bg_secondary};
            color: {colors.text_primary};
            border: 1px solid {colors.border_default};
            padding: {SPACING.space_2}px {SPACING.space_3}px;
            border-radius: {RADIUS.radius_sm}px;
            font-size: {TYPOGRAPHY.text_sm}px;
            min-height: 24px;
        }}
        QComboBox:hover {{
            border-color: {colors.interactive_primary};
        }}
        QComboBox:focus {{
            border-color: {colors.interactive_primary};
            border-width: 2px;
        }}
        QComboBox::drop-down {{
            border: none;
            border-radius: {RADIUS.radius_sm}px;
            width: 20px;
        }}
        QComboBox QAbstractItemView {{
            background-color: {colors.bg_primary};
            color: {colors.text_primary};
            selection-background-color: {colors.interactive_primary};
            selection-color: {colors.text_inverse};
            border: 1px solid {colors.border_default};
            border-radius: {RADIUS.radius_sm}px;
            padding: {SPACING.space_1}px;
        }}
        QComboBox QAbstractItemView::item {{
            padding: {SPACING.space_2}px;
            border-radius: {RADIUS.radius_sm}px;
        }}
        QComboBox QAbstractItemView::item:hover {{
            background-color: {colors.bg_tertiary};
        }}
    """


def get_panel_stylesheet() -> str:
    """Returns stylesheet for panels/cards"""
    colors = get_colors()
    
    return f"""
        QFrame[frameShape="StyledPanel"] {{
            background-color: {colors.bg_secondary};
            border: 1px solid {colors.border_muted};
            border-radius: {RADIUS.radius_md}px;
        }}
    """


def get_statusbar_connected_stylesheet(color: str = None) -> str:
    """Returns stylesheet for connected status bar"""
    colors = get_colors()
    bg = color or colors.interactive_primary
    
    return f"""
        QStatusBar {{
            background-color: {bg};
            color: {colors.text_inverse};
        }}
    """


def get_statusbar_disconnected_stylesheet() -> str:
    """Returns stylesheet for disconnected status bar"""
    colors = get_colors()
    
    return f"""
        QStatusBar {{
            background-color: {colors.bg_tertiary};
            color: {colors.text_inverse};
        }}
    """


def get_dock_stylesheet() -> str:
    """Returns stylesheet for dock widgets"""
    colors = get_colors()
    
    return f"""
        QDockWidget {{
            titlebar-close-icon: none;
            titlebar-normal-icon: none;
        }}
        QDockWidget::title {{
            background-color: {colors.bg_secondary};
            color: {colors.text_primary};
            padding: {SPACING.space_2}px;
            border-bottom: 1px solid {colors.border_muted};
        }}
        QDockWidget::close-button, QDockWidget::float-button {{
            background: transparent;
            border: none;
        }}
    """


def get_tab_stylesheet() -> str:
    """Returns stylesheet for tab widgets"""
    colors = get_colors()
    
    return f"""
        QTabWidget::pane {{
            border: 1px solid {colors.border_default};
            background-color: {colors.bg_primary};
            border-radius: {RADIUS.radius_sm}px;
        }}
        QTabBar::tab {{
            background-color: {colors.bg_secondary};
            color: {colors.text_secondary};
            padding: {SPACING.space_2}px {SPACING.space_4}px;
            border: none;
            border-bottom: 2px solid transparent;
            margin-right: 4px;
            border-top-left-radius: {RADIUS.radius_sm}px;
            border-top-right-radius: {RADIUS.radius_sm}px;
        }}
        QTabBar::tab:selected {{
            background-color: {colors.bg_primary};
            color: {colors.text_primary};
            border-bottom: 2px solid {colors.interactive_primary};
        }}
        QTabBar::tab:hover:!selected {{
            background-color: {colors.bg_tertiary};
            color: {colors.text_primary};
        }}
    """


def get_scrollbar_stylesheet() -> str:
    """Returns stylesheet for scrollbars"""
    colors = get_colors()
    
    return f"""
        QScrollBar:vertical {{
            background-color: transparent;
            width: 10px;
            margin: 2px;
        }}
        QScrollBar::handle:vertical {{
            background-color: {colors.border_strong};
            border-radius: 5px;
            min-height: 30px;
        }}
        QScrollBar::handle:vertical:hover {{
            background-color: {colors.text_tertiary};
        }}
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
            height: 0px;
        }}
        QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
            background: none;
        }}
        QScrollBar:horizontal {{
            background-color: transparent;
            height: 10px;
            margin: 2px;
        }}
        QScrollBar::handle:horizontal {{
            background-color: {colors.border_strong};
            border-radius: 5px;
            min-width: 20px;
        }}
        QScrollBar::handle:horizontal:hover {{
            background-color: {colors.text_tertiary};
        }}
        QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
            width: 0px;
        }}
    """


def get_table_stylesheet() -> str:
    """Returns stylesheet for tables"""
    colors = get_colors()
    
    return f"""
        QTableWidget, QTableView {{
            background-color: {colors.bg_primary};
            color: {colors.text_primary};
            border: 1px solid {colors.border_default};
            border-radius: {RADIUS.radius_sm}px;
            gridline-color: {colors.border_muted};
            selection-background-color: {colors.interactive_primary};
            selection-color: {colors.text_inverse};
        }}
        QTableWidget::item, QTableView::item {{
            padding: {SPACING.space_2}px;
            border-radius: 4px;
        }}
        QTableWidget::item:alternate, QTableView::item:alternate {{
            background-color: {colors.bg_secondary};
        }}
        QTableWidget::item:selected, QTableView::item:selected {{
            background-color: {colors.interactive_primary};
            color: {colors.text_inverse};
        }}
        QHeaderView::section {{
            background-color: {colors.bg_tertiary};
            color: {colors.text_primary};
            padding: {SPACING.space_2}px {SPACING.space_3}px;
            border: none;
            border-right: 1px solid {colors.border_muted};
            border-bottom: 1px solid {colors.border_muted};
            font-weight: {TYPOGRAPHY.font_semibold};
        }}
    """


def get_list_stylesheet() -> str:
    """Returns stylesheet for list widgets"""
    colors = get_colors()
    
    return f"""
        QListWidget {{
            background-color: {colors.bg_primary};
            color: {colors.text_primary};
            border: 1px solid {colors.border_default};
            border-radius: {RADIUS.radius_sm}px;
            padding: {SPACING.space_1}px;
        }}
        QListWidget::item {{
            padding: {SPACING.space_2}px {SPACING.space_3}px;
            border-radius: {RADIUS.radius_sm}px;
            margin: 1px 0;
        }}
        QListWidget::item:hover {{
            background-color: {colors.bg_secondary};
        }}
        QListWidget::item:selected {{
            background-color: {colors.interactive_primary};
            color: {colors.text_inverse};
        }}
    """


def get_tree_stylesheet() -> str:
    """Returns stylesheet for tree widgets"""
    colors = get_colors()
    
    return f"""
        QTreeWidget, QTreeView {{
            background-color: {colors.bg_primary};
            color: {colors.text_primary};
            border: 1px solid {colors.border_default};
            border-radius: {RADIUS.radius_sm}px;
        }}
        QTreeWidget::item, QTreeView::item {{
            padding: {SPACING.space_1}px {SPACING.space_2}px;
            border-radius: 4px;
        }}
        QTreeWidget::item:hover, QTreeView::item:hover {{
            background-color: {colors.bg_secondary};
        }}
        QTreeWidget::item:selected, QTreeView::item:selected {{
            background-color: {colors.interactive_primary};
            color: {colors.text_inverse};
        }}
        QTreeWidget::branch, QTreeView::branch {{
            background-color: {colors.bg_primary};
        }}
    """


def get_groupbox_stylesheet() -> str:
    """Returns stylesheet for group boxes"""
    colors = get_colors()
    
    return f"""
        QGroupBox {{
            color: {colors.text_secondary};
            font-weight: {TYPOGRAPHY.font_semibold};
            font-size: {TYPOGRAPHY.text_sm}px;
            border: 1px solid {colors.border_muted};
            border-radius: {RADIUS.radius_md}px;
            margin-top: {SPACING.space_3}px;
            padding-top: {SPACING.space_5}px;
            padding-left: {SPACING.space_3}px;
            padding-right: {SPACING.space_3}px;
        }}
        QGroupBox::title {{
            subcontrol-origin: margin;
            left: {SPACING.space_3}px;
            padding: 0 {SPACING.space_2}px;
        }}
    """


def get_checkbox_stylesheet() -> str:
    """Returns stylesheet for checkboxes"""
    colors = get_colors()
    
    return f"""
        QCheckBox {{
            color: {colors.text_primary};
            spacing: {SPACING.space_2}px;
        }}
        QCheckBox::indicator {{
            width: 18px;
            height: 18px;
            border-radius: 4px;
        }}
        QCheckBox::indicator:unchecked {{
            border: 2px solid {colors.border_default};
            background-color: {colors.bg_secondary};
            border-radius: 4px;
        }}
        QCheckBox::indicator:checked {{
            background-color: {colors.interactive_primary};
            border: 2px solid {colors.interactive_primary};
            border-radius: 4px;
        }}
        QCheckBox::indicator:unchecked:hover {{
            border-color: {colors.interactive_primary};
        }}
    """


def get_dialog_base_stylesheet() -> str:
    """Returns base stylesheet for dialogs"""
    colors = get_colors()
    
    return f"""
        QDialog {{
            background-color: {colors.bg_primary};
            color: {colors.text_primary};
        }}
        QLabel {{
            color: {colors.text_primary};
        }}
        {get_input_stylesheet()}
        {get_combobox_stylesheet()}
        {get_button_stylesheet("primary")}
        {get_checkbox_stylesheet()}
        {get_groupbox_stylesheet()}
        {get_table_stylesheet()}
        {get_list_stylesheet()}
        {get_tree_stylesheet()}
        {get_scrollbar_stylesheet()}
    """