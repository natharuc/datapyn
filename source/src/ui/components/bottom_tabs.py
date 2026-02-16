"""Bottom Tabs - Bottom tabs container

Contains tabs for Results, Output, and Variables.
"""

from PyQt6.QtWidgets import QTabWidget, QWidget
from PyQt6.QtCore import pyqtSignal
import qtawesome as qta
from typing import Optional
import pandas as pd

from .results_viewer import ResultsViewer
from .output_panel import OutputPanel
from .variables_panel import VariablesPanel


class BottomTabs(QTabWidget):
    """Container with tabs for results, output, and variables"""

    # Signals
    tab_changed = pyqtSignal(int)  # index

    def __init__(self, theme_manager=None, parent=None):
        super().__init__(parent)

        self.theme_manager = theme_manager
        self._setup_ui()
        self._setup_style()
        self._connect_signals()

    def _setup_ui(self):
        """Configure UI"""
        # Tab: Results
        self.results_viewer = ResultsViewer(theme_manager=self.theme_manager)
        self.addTab(self.results_viewer, "Results")
        self.setTabIcon(0, qta.icon("mdi.table-eye", color="#64b5f6"))

        # Tab: Output/Logs
        self.output_panel = OutputPanel(theme_manager=self.theme_manager)
        self.addTab(self.output_panel, "Output")
        self.setTabIcon(1, qta.icon("mdi.console", color="#64b5f6"))

        # Tab: Variables
        self.variables_panel = VariablesPanel(theme_manager=self.theme_manager)
        self.addTab(self.variables_panel, "Variables")
        self.setTabIcon(2, qta.icon("mdi.variable", color="#64b5f6"))

    def _setup_style(self):
        """Configure style"""
        self._apply_theme()

    def _apply_theme(self):
        """Apply current theme"""
        if self.theme_manager:
            colors = self.theme_manager.get_app_colors()
            bg = colors.get("background", "#1e1e1e")
            fg = colors.get("foreground", "#d4d4d4")
            border = colors.get("border", "#3e3e42")
            secondary = colors.get("secondary", "#2d2d30")
        else:
            bg = "#1e1e1e"
            fg = "#d4d4d4"
            border = "#3e3e42"
            secondary = "#2d2d30"

        self.setStyleSheet(f"""
            QTabWidget::pane {{
                border: 1px solid {border};
                background-color: {bg};
                border-top: none;
            }}
            QTabBar::tab {{
                background-color: {secondary};
                color: #808080;
                padding: 8px 16px;
                border: 1px solid {border};
                border-bottom: none;
                margin-right: 2px;
            }}
            QTabBar::tab:selected {{
                background-color: {bg};
                color: {fg};
            }}
            QTabBar::tab:hover:!selected {{
                background-color: {border};
                color: #cccccc;
            }}
        """)

    def _connect_signals(self):
        """Connect signals"""
        self.currentChanged.connect(self.tab_changed.emit)

    def set_theme_manager(self, theme_manager):
        """Set theme manager for all components"""
        self.theme_manager = theme_manager
        self._apply_theme()
        self.results_viewer.set_theme_manager(theme_manager)
        self.output_panel.set_theme_manager(theme_manager)
        self.variables_panel.set_theme_manager(theme_manager)

    # === Convenience methods for Results ===

    def set_results(self, df: Optional[pd.DataFrame], var_name: str = "df"):
        """Set results data"""
        self.results_viewer.display_dataframe(df, var_name)
        self.show_results()

    def clear_results(self):
        """Clear results"""
        self.results_viewer.clear()

    def show_results(self):
        """Show results tab"""
        self.setCurrentWidget(self.results_viewer)

    # === Convenience methods for Output ===

    def log(self, text: str):
        """Add log"""
        self.output_panel.log(text)

    def log_success(self, text: str):
        """Add success log"""
        self.output_panel.success(text)

    def log_warning(self, text: str):
        """Add warning log"""
        self.output_panel.warning(text)

    def log_error(self, text: str):
        """Add error log"""
        self.output_panel.error(text)
        self.show_output()

    def append_output(self, text: str, error: bool = False):
        """Compatibility with old code"""
        self.output_panel.append_output(text, error)

    def clear_output(self):
        """Clear output"""
        self.output_panel.clear()

    def show_output(self):
        """Show output tab"""
        self.setCurrentWidget(self.output_panel)

    # === Convenience methods for Variables ===

    def set_variables(self, namespace: dict):
        """Set variables"""
        self.variables_panel.set_variables(namespace)

    def clear_variables(self):
        """Clear variables"""
        self.variables_panel.clear()

    def show_variables(self):
        """Show variables tab"""
        self.setCurrentWidget(self.variables_panel)

    # === General methods ===

    def clear_all(self):
        """Clear all panels"""
        self.clear_results()
        self.clear_output()
        self.clear_variables()

    # === Compatibility with old code ===

    @property
    def output_text(self):
        """Compatibility: return output text_edit"""
        return self.output_panel.text_edit

    @property
    def variables_viewer(self):
        """Compatibility: return variables_panel"""
        return self.variables_panel
