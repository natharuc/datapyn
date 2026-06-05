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
# DARK THEME (DataPyn blue — matches frameless installer chrome)
# =============================================================================

CHROME_BG = "#0c111b"
CHROME_CARD = "#161f30"
CHROME_ACCENT = "#3369ff"
CHROME_ACCENT_HOVER = "#4d7dff"
CHROME_ACCENT_ACTIVE = "#2857e6"
CHROME_TEXT = "#eef2f7"
CHROME_MUTED = "#8b9cb3"
CHROME_BORDER = "rgba(148, 163, 184, 0.18)"

DARK_COLORS = ColorPalette(
    # Backgrounds — deep navy (installer / frameless shell)
    bg_primary=CHROME_BG,
    bg_secondary="#121a2b",
    bg_tertiary=CHROME_CARD,
    bg_elevated="#1e2a42",
    bg_overlay="rgba(7, 11, 18, 0.72)",
    # Borders — cool slate / blue tint
    border_default=CHROME_BORDER,
    border_muted="rgba(148, 163, 184, 0.10)",
    border_strong="rgba(51, 105, 255, 0.35)",
    # Text
    text_primary=CHROME_TEXT,
    text_secondary="#b8c5d9",
    text_tertiary=CHROME_MUTED,
    text_disabled="#5c6d85",
    text_inverse="#ffffff",
    # Interactive — brand blue
    interactive_primary=CHROME_ACCENT,
    interactive_primary_hover=CHROME_ACCENT_HOVER,
    interactive_primary_active=CHROME_ACCENT_ACTIVE,
    interactive_secondary="#1a2438",
    interactive_secondary_hover="#243352",
    interactive_secondary_active="#141c2e",
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
    info=CHROME_ACCENT,
    info_hover=CHROME_ACCENT_HOVER,
    info_active=CHROME_ACCENT_ACTIVE,
    # Editor — same navy plane as session chrome (not VS Code gray)
    editor_bg="#121a2b",
    editor_fg="#eef2f7",
    editor_selection="rgba(51, 105, 255, 0.35)",
    editor_line_highlight="#161f30",
    editor_gutter_bg="#121a2b",
    editor_gutter_fg="#5c6d85",
)


TYPOGRAPHY = Typography(
    font_family_primary="Ubuntu, Roboto, Segoe UI, -apple-system, BlinkMacSystemFont, sans-serif",
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


# DataPyn ships dark-only. The theme indirection is kept so existing callers
# (get_colors / set_theme / get_theme) keep working, but it always resolves
# to the dark palette.
_current_theme = "dark"


def get_colors() -> ColorPalette:
    """Return the active color palette (dark-only)."""
    return DARK_COLORS


def set_theme(theme: str):
    """No-op kept for backward compatibility — DataPyn is dark-only."""
    return


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
    running_text: str = "#1e1e1e"       # Dark text on the amber badge
    running_bg: str = "#f39c12"         # Solid amber badge (dark-theme friendly)
    
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
    
    figure_bg: str = CHROME_BG
    axes_bg: str = CHROME_BG
    axes_edge: str = "#2a3a5c"
    text: str = CHROME_TEXT
    grid: str = "#2a3a5c"
    legend_bg: str = CHROME_BG
    legend_edge: str = "#2a3a5c"


# Singleton instances (dark-only)
DARK_STATE_COLORS = StateColors()
DARK_CHART_COLORS = ChartColors()


def get_state_colors() -> StateColors:
    """Returns state colors (dark-only)."""
    return DARK_STATE_COLORS


def get_chart_colors() -> ChartColors:
    """Returns chart colors (dark-only)."""
    return DARK_CHART_COLORS


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


def _combobox_popup_view_stylesheet(*, list_item_height: int | None = None) -> str:
    """List popup only — applied on the QListView (avoids square window behind rounded menu)."""
    colors = get_colors()
    if list_item_height:
        list_padding = f"{SPACING.space_2}px"
        item_padding = "12px 16px"
        item_margin = "margin: 2px 4px;"
        item_min_height = f"min-height: {list_item_height}px;"
    else:
        list_padding = f"{SPACING.space_1}px"
        item_padding = f"{SPACING.space_2}px {SPACING.space_3}px"
        item_margin = ""
        item_min_height = "min-height: 22px;"
    return f"""
        QListView {{
            background-color: {colors.bg_primary};
            color: {colors.text_primary};
            border: 1px solid {colors.border_default};
            border-radius: {RADIUS.radius_md}px;
            padding: {list_padding};
            outline: none;
        }}
        QListView::item {{
            padding: {item_padding};
            border-radius: {RADIUS.radius_sm}px;
            {item_margin}
            {item_min_height}
        }}
        QListView::item:selected {{
            background-color: {colors.interactive_primary};
            color: {colors.text_inverse};
        }}
        QListView::item:hover {{
            background-color: {colors.bg_tertiary};
        }}
    """


def _svg_data_uri(svg: str) -> str:
    import base64

    encoded = base64.b64encode(svg.encode("utf-8")).decode("ascii")
    return f'url("data:image/svg+xml;base64,{encoded}")'


def _chevron_down_uri(color: str) -> str:
    fill = color if color.startswith("#") else f"#{color}"
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10" viewBox="0 0 10 10">'
        f'<path fill="{fill}" d="M2 3.5L5 6.5L8 3.5z"/></svg>'
    )
    return _svg_data_uri(svg)


def _combobox_down_arrow_stylesheet(
    *,
    arrow_color: str | None = None,
    hover_arrow_color: str | None = None,
) -> str:
    colors = get_colors()
    normal = arrow_color or colors.text_secondary
    block = f"""
        QComboBox::drop-down {{
            subcontrol-origin: padding;
            subcontrol-position: center right;
            width: 22px;
            border: none;
            background: transparent;
        }}
        QComboBox::down-arrow {{
            image: {_chevron_down_uri(normal)};
            width: 10px;
            height: 10px;
            margin-right: 6px;
        }}
    """
    if hover_arrow_color:
        block += f"""
        QComboBox:hover::down-arrow {{
            image: {_chevron_down_uri(hover_arrow_color)};
        }}
        """
    return block


def get_combobox_stylesheet() -> str:
    """Returns stylesheet for comboboxes (pair with configure_combobox_popup)."""
    colors = get_colors()

    return f"""
        QComboBox {{
            background-color: {colors.bg_secondary};
            color: {colors.text_primary};
            border: 1px solid {colors.border_default};
            padding: {SPACING.space_2}px {SPACING.space_3}px;
            padding-right: 24px;
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
        {_combobox_down_arrow_stylesheet()}
    """


def get_combobox_stylesheet_toolbar() -> str:
    """Compact combobox for the main toolbar (workspace selector)."""
    colors = get_colors()

    return f"""
        QComboBox {{
            background-color: {colors.bg_tertiary};
            color: {colors.text_primary};
            border: none;
            border-radius: 6px;
            padding: 4px 8px;
            padding-right: 22px;
            font-size: 11px;
            min-height: 22px;
        }}
        QComboBox:hover {{
            background-color: {colors.bg_elevated};
        }}
        {_combobox_down_arrow_stylesheet()}
    """


def get_combobox_stylesheet_inline_toolbar() -> str:
    """Bordered combobox aligned with toolbar action buttons (e.g. export destination)."""
    colors = get_colors()

    return f"""
        QComboBox {{
            background-color: transparent;
            color: {colors.text_primary};
            border: 1px solid {colors.border_default};
            border-radius: {RADIUS.radius_sm}px;
            padding: 4px 8px;
            padding-right: 26px;
            font-size: 12px;
            min-height: 28px;
        }}
        QComboBox:hover {{
            background-color: {colors.interactive_primary};
            color: {colors.text_inverse};
            border-color: {colors.interactive_primary};
        }}
        QComboBox:focus {{
            border-color: {colors.interactive_primary};
        }}
        {_combobox_down_arrow_stylesheet(
            arrow_color=colors.text_secondary,
            hover_arrow_color=colors.text_inverse,
        )}
    """


def configure_combobox_popup(combo, *, list_item_height: int | None = None) -> None:
    """Frameless translucent popup so rounded list does not show a square behind it."""
    from PyQt6.QtCore import Qt
    from PyQt6.QtWidgets import QFrame

    view = combo.view()
    if view is None:
        return
    view.setFrameShape(QFrame.Shape.NoFrame)
    view.setStyleSheet(_combobox_popup_view_stylesheet(list_item_height=list_item_height))
    view.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

    popup = view.window()
    if popup is not None and popup is not combo:
        popup.setWindowFlags(
            Qt.WindowType.Popup
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.NoDropShadowWindowHint
        )
        popup.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)


def apply_combobox_style(
    combo,
    *,
    variant: str = "default",
    icon_size: int | None = None,
    list_item_height: int | None = None,
) -> None:
    """Apply combobox QSS and fix popup rendering for one QComboBox instance."""
    from PyQt6.QtCore import QSize

    if variant == "toolbar":
        combo.setStyleSheet(get_combobox_stylesheet_toolbar())
    elif variant == "inline_toolbar":
        combo.setStyleSheet(get_combobox_stylesheet_inline_toolbar())
    else:
        combo.setStyleSheet(get_combobox_stylesheet())

    if icon_size is not None:
        combo.setIconSize(QSize(icon_size, icon_size))

    configure_combobox_popup(combo, list_item_height=list_item_height)


def polish_combobox_popups(root) -> None:
    """Fix popup chrome for all comboboxes under *root* (keeps existing QSS)."""
    from PyQt6.QtWidgets import QComboBox

    for combo in root.findChildren(QComboBox):
        configure_combobox_popup(combo)


def get_panel_stylesheet() -> str:
    """Returns stylesheet for panels/cards (borderless — tone only)."""
    colors = get_colors()

    return f"""
        QFrame[frameShape="StyledPanel"],
        QFrame#sectionPanel {{
            background-color: {colors.bg_secondary};
            border: none;
            border-radius: {RADIUS.radius_md}px;
        }}
    """


def get_section_panel_stylesheet() -> str:
    """Borderless section panels inside dialogs."""
    return get_panel_stylesheet()


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


# Constant for clean scrollbar style - can be concatenated to any stylesheet
SCROLLBAR_STYLE = """
    QScrollBar:vertical {
        background: transparent;
        width: 8px;
        margin: 0px;
    }
    QScrollBar::handle:vertical {
        background: rgba(51, 105, 255, 0.35);
        border-radius: 4px;
        min-height: 40px;
        margin: 2px;
    }
    QScrollBar::handle:vertical:hover {
        background: rgba(51, 105, 255, 0.55);
    }
    QScrollBar::handle:vertical:pressed {
        background: rgba(51, 105, 255, 0.75);
    }
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
        height: 0px;
    }
    QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
        background: none;
    }
    QScrollBar:horizontal {
        background: transparent;
        height: 8px;
        margin: 0px;
    }
    QScrollBar::handle:horizontal {
        background: rgba(51, 105, 255, 0.35);
        border-radius: 4px;
        min-width: 40px;
        margin: 2px;
    }
    QScrollBar::handle:horizontal:hover {
        background: rgba(51, 105, 255, 0.55);
    }
    QScrollBar::handle:horizontal:pressed {
        background: rgba(51, 105, 255, 0.75);
    }
    QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
        width: 0px;
    }
    QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {
        background: none;
    }
    QScrollBar::corner {
        background: transparent;
    }
"""


def get_scrollbar_stylesheet() -> str:
    """Returns stylesheet for scrollbars - minimal macOS-style"""
    return SCROLLBAR_STYLE


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
        {SCROLLBAR_STYLE}
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
        {SCROLLBAR_STYLE}
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
        {SCROLLBAR_STYLE}
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