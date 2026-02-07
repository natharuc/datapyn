"""
Design Tokens - Sistema de design centralizado

Inspirado em shadcn/ui, define todos os tokens visuais da aplicação:
- Cores
- Tipografia
- Espaçamentos
- Sombras
- Bordas
- Animações
"""

from dataclasses import dataclass
from typing import Dict


@dataclass
class ColorPalette:
    """Paleta de cores semântica"""

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
    """Sistema tipográfico"""

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
    """Sistema de espaçamento consistente"""

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
    # Backgrounds
    bg_primary="#1e1e1e",
    bg_secondary="#252526",
    bg_tertiary="#2d2d30",
    bg_elevated="#323232",
    bg_overlay="rgba(0, 0, 0, 0.7)",
    # Borders
    border_default="#3e3e42",
    border_muted="#2d2d30",
    border_strong="#555555",
    # Text
    text_primary="#cccccc",
    text_secondary="#999999",
    text_tertiary="#6e6e6e",
    text_disabled="#5a5a5a",
    text_inverse="#ffffff",
    # Interactive
    interactive_primary="#3369FF",
    interactive_primary_hover="#4d7fff",
    interactive_primary_active="#2952cc",
    interactive_secondary="#3c3c3c",
    interactive_secondary_hover="#4a4a4a",
    interactive_secondary_active="#333333",
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
    editor_bg="#1e1e1e",
    editor_fg="#d4d4d4",
    editor_selection="#264f78",
    editor_line_highlight="#2a2a2a",
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
    font_family_primary="Segoe UI, -apple-system, BlinkMacSystemFont, sans-serif",
    font_family_mono="Consolas, 'Courier New', monospace",
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
    radius_sm=3,
    radius_md=6,
    radius_lg=8,
    radius_full=9999,
)


SHADOW = Shadow(
    shadow_none="none",
    shadow_sm="0 1px 2px rgba(0, 0, 0, 0.1)",
    shadow_md="0 4px 6px rgba(0, 0, 0, 0.15)",
    shadow_lg="0 10px 20px rgba(0, 0, 0, 0.2)",
    shadow_xl="0 20px 40px rgba(0, 0, 0, 0.25)",
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
