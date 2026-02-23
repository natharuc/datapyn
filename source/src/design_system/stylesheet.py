"""
Application Stylesheet Generator

Consolidates the main application styles into reusable functions.
This module provides the centralized stylesheet that was previously
scattered across main_window.py and other files.
"""

from src.design_system.tokens import (
    get_colors,
    SPACING,
    RADIUS,
    TYPOGRAPHY,
)


def get_main_window_stylesheet() -> str:
    """
    Generate the main window stylesheet.
    
    Replaces the ~150 line inline CSS in main_window.py _setup_ui_style()
    """
    colors = get_colors()
    
    return f"""
        * {{
            font-family: \"Inter\", \"SF Pro Display\", \"Roboto\", -apple-system, BlinkMacSystemFont, \"Helvetica Neue\", sans-serif;
        }}
        QMainWindow {{
            background-color: {colors.bg_primary};
        }}
        QMenuBar {{
            background-color: {colors.bg_secondary};
            color: {colors.text_primary};
            border: none;
            padding: 4px 0;
            font-size: 13px;
        }}
        QMenuBar::item {{
            padding: 8px 14px;
            border-radius: {RADIUS.radius_sm}px;
            margin: 2px 4px;
        }}
        QMenuBar::item:selected {{
            background-color: {colors.bg_elevated};
        }}
        QMenu {{
            background-color: {colors.bg_tertiary};
            color: {colors.text_primary};
            border: 1px solid {colors.border_muted};
            border-radius: {RADIUS.radius_md}px;
            padding: 8px;
        }}
        QMenu::item {{
            padding: 10px 36px 10px 36px;
            border-radius: {RADIUS.radius_sm}px;
            margin: 2px 4px;
        }}
        QMenu::item:selected {{
            background-color: {colors.interactive_primary};
        }}
        QMenu::separator {{
            height: 1px;
            background: {colors.border_muted};
            margin: 8px 16px;
        }}
        QMenu::icon {{
            padding-left: 14px;
            margin-right: 10px;
            width: 16px;
            height: 16px;
        }}
        QToolBar {{
            background-color: {colors.bg_secondary};
            border: none;
            spacing: 6px;
            padding: 6px;
        }}
        QStatusBar {{
            background-color: {colors.interactive_primary};
            color: {colors.text_inverse};
            border: none;
            font-size: 12px;
            padding: 4px 8px;
        }}
        QSplitter::handle {{
            background-color: {colors.border_muted};
            width: 1px;
            height: 1px;
        }}
        QPushButton {{
            background-color: {colors.interactive_primary};
            color: {colors.text_inverse};
            border: none;
            padding: 10px 20px;
            border-radius: {RADIUS.radius_sm}px;
            font-weight: 500;
            font-size: 13px;
            min-height: 18px;
        }}
        QPushButton:hover {{
            background-color: {colors.interactive_primary_hover};
        }}
        QPushButton:pressed {{
            background-color: {colors.interactive_primary_active};
        }}\n        QTextEdit {{
            background-color: {colors.bg_primary};
            color: {colors.editor_fg};
            border: 1px solid {colors.border_muted};
            border-radius: {RADIUS.radius_sm}px;
            selection-background-color: {colors.editor_selection};
        }}
        QLineEdit {{
            background-color: {colors.bg_tertiary};
            color: {colors.text_primary};
            border: 1px solid {colors.border_muted};
            border-radius: {RADIUS.radius_sm}px;
            padding: 8px 12px;
            font-size: 13px;
        }}
        QLineEdit:focus {{
            border: 2px solid {colors.interactive_primary};
        }}
        QScrollBar:vertical {{
            background: transparent;
            width: 10px;
            border-radius: 5px;
            margin: 2px;
        }}
        QScrollBar::handle:vertical {{
            background: rgba(150, 150, 150, 0.4);
            border-radius: 5px;
            min-height: 28px;
        }}
        QScrollBar::handle:vertical:hover {{
            background: rgba(150, 150, 150, 0.6);
        }}
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
            height: 0;
        }}
        QScrollBar:horizontal {{
            background: transparent;
            height: 10px;
            border-radius: 5px;
            margin: 2px;
        }}
        QScrollBar::handle:horizontal {{
            background: rgba(150, 150, 150, 0.4);
            border-radius: 5px;
            min-width: 28px;
        }}
        QScrollBar::handle:horizontal:hover {{
            background: rgba(150, 150, 150, 0.6);
        }}
        QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
            width: 0;
        }}
        QDockWidget {{
            font-size: 12px;
            font-weight: 500;
        }}
        QDockWidget::title {{
            background: {colors.bg_secondary};
            padding: 10px 12px;
            border-top-left-radius: 8px;
            border-top-right-radius: 8px;
        }}
        QTabWidget::pane {{
            border: none;
            border-top: 1px solid {colors.border_muted};
            background: {colors.bg_primary};
        }}
        QTabBar::tab {{
            background: transparent;
            color: {colors.text_secondary};
            padding: 10px 18px;
            border: none;
            border-bottom: 2px solid transparent;
            font-size: 13px;
        }}
        QTabBar::tab:selected {{
            color: {colors.text_primary};
            border-bottom: 2px solid {colors.interactive_primary};
        }}
        QTabBar::tab:hover:!selected {{
            background: {colors.bg_elevated};
            color: {colors.text_primary};
        }}
        QGroupBox {{
            font-weight: 500;
            border: 1px solid {colors.border_muted};
            border-radius: {RADIUS.radius_md}px;
            margin-top: 12px;
            padding-top: 12px;
        }}
        QGroupBox::title {{
            subcontrol-origin: margin;
            padding: 0 8px;
        }}
        QToolTip {{
            background: {colors.bg_tertiary};
            color: {colors.text_primary};
            border: 1px solid {colors.border_default};
            border-radius: 6px;
            padding: 8px 12px;
            font-size: 12px;
        }}
    """


def get_dock_widget_stylesheet() -> str:
    """Generate stylesheet for dock widgets"""
    colors = get_colors()
    
    return f"""
        QDockWidget {{
            background-color: {colors.bg_secondary};
            color: {colors.text_primary};
            titlebar-close-icon: none;
            titlebar-normal-icon: none;
            border: none;
        }}
        QDockWidget::title {{
            background-color: {colors.bg_tertiary};
            color: {colors.text_primary};
            padding: 8px 12px;
            border: none;
            font-weight: 500;
            text-align: left;
        }}
        QDockWidget::close-button, QDockWidget::float-button {{
            background: transparent;
            border: none;
            icon-size: 16px;
        }}
        QDockWidget::close-button:hover, QDockWidget::float-button:hover {{
            background-color: {colors.bg_elevated};
            border-radius: {RADIUS.radius_sm}px;
        }}
    """


def get_bottom_dock_stylesheet() -> str:
    """Generate stylesheet for bottom dock widgets (Results, Output, etc.)"""
    colors = get_colors()
    
    return f"""
        QDockWidget {{
            background-color: {colors.bg_secondary};
            color: {colors.text_primary};
            border: none;
        }}
        QDockWidget::title {{
            background-color: {colors.bg_tertiary};
            color: {colors.text_primary};
            padding: 6px 10px;
            border: none;
            font-weight: 500;
        }}
    """


def get_tab_widget_stylesheet() -> str:
    """Generate stylesheet for tab widgets"""
    colors = get_colors()
    
    return f"""
        QTabWidget::pane {{
            background-color: {colors.bg_primary};
            border: none;
        }}
        QTabBar {{
            background-color: {colors.bg_secondary};
        }}
        QTabBar::tab {{
            background-color: {colors.bg_tertiary};
            color: {colors.text_secondary};
            padding: 8px 16px;
            margin-right: 2px;
            border: none;
            border-top-left-radius: {RADIUS.radius_sm}px;
            border-top-right-radius: {RADIUS.radius_sm}px;
        }}
        QTabBar::tab:selected {{
            background-color: {colors.bg_primary};
            color: {colors.text_primary};
        }}
        QTabBar::tab:hover:!selected {{
            background-color: {colors.bg_elevated};
        }}
        QTabBar::close-button {{
            image: none;
            background: transparent;
            border: none;
        }}
    """


def get_execution_label_stylesheet(running: bool = False) -> str:
    """Generate stylesheet for execution timer label"""
    colors = get_colors()
    
    if running:
        return f"""
            QLabel {{
                color: {colors.success};
                font-size: {TYPOGRAPHY.text_sm}px;
                font-weight: {TYPOGRAPHY.font_medium};
                padding: 2px 8px;
                background-color: rgba(76, 175, 80, 0.1);
                border-radius: {RADIUS.radius_sm}px;
            }}
        """
    else:
        return f"""
            QLabel {{
                color: {colors.text_tertiary};
                font-size: {TYPOGRAPHY.text_sm}px;
                padding: 2px 8px;
            }}
        """


def get_connection_status_stylesheet(connected: bool = False) -> str:
    """Generate stylesheet for connection status bar"""
    colors = get_colors()
    
    if connected:
        return f"""
            QLabel {{
                background-color: {colors.success};
                color: {colors.text_inverse};
                padding: 4px 8px;
                border-radius: {RADIUS.radius_sm}px;
                font-weight: 500;
            }}
        """
    else:
        return f"""
            QLabel {{
                background-color: {colors.bg_tertiary};
                color: {colors.text_secondary};
                padding: 4px 8px;
                border-radius: {RADIUS.radius_sm}px;
            }}
        """


def get_empty_state_stylesheet() -> str:
    """Generate stylesheet for empty state widget"""
    colors = get_colors()
    
    return f"""
        QWidget {{
            background-color: {colors.bg_primary};
        }}
        QLabel#empty-icon {{
            font-size: 96px;
            background: transparent;
        }}
        QLabel#empty-title {{
            color: {colors.text_primary};
            font-size: {TYPOGRAPHY.text_2xl}px;
            font-weight: {TYPOGRAPHY.font_semibold};
        }}
        QLabel#empty-subtitle {{
            color: {colors.text_tertiary};
            font-size: {TYPOGRAPHY.text_base}px;
        }}
    """


def get_start_button_stylesheet() -> str:
    """Generate stylesheet for the start/new session button"""
    colors = get_colors()
    
    return f"""
        QPushButton {{
            background-color: {colors.interactive_primary};
            color: {colors.text_inverse};
            border: none;
            padding: 12px 24px;
            border-radius: {RADIUS.radius_md}px;
            font-size: {TYPOGRAPHY.text_base}px;
            font-weight: {TYPOGRAPHY.font_semibold};
        }}
        QPushButton:hover {{
            background-color: {colors.interactive_primary_hover};
        }}
        QPushButton:pressed {{
            background-color: {colors.interactive_primary_active};
        }}
    """
