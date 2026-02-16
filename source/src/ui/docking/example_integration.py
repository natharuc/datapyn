"""
Example integration of docking system with existing panels

Este arquivo mostra como integrar o novo sistema de docking
with existing panels: Results, Output, Variables
"""

from PyQt6.QtWidgets import (
    QApplication,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QTextEdit,
    QListWidget,
    QTableWidget,
    QLabel,
    QPushButton,
    QSplitter,
)
from PyQt6.QtCore import Qt, pyqtSignal
import sys

from ..docking import DockingMainWindow, DockableWidget


class MockResultsViewer(QWidget):
    """Mock do Results Viewer para testar docking"""

    def __init__(self):
        super().__init__()
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)

        # Header
        header = QLabel("Results Viewer")
        header.setStyleSheet("font-weight: bold; padding: 5px;")
        layout.addWidget(header)

        # Tabela de resultados
        self.table = QTableWidget(5, 3)
        self.table.setHorizontalHeaderLabels(["Column A", "Column B", "Column C"])

        # Dados de exemplo
        from PyQt6.QtWidgets import QTableWidgetItem

        for row in range(5):
            for col in range(3):
                item = QTableWidgetItem(f"Data {row},{col}")
                self.table.setItem(row, col, item)

        layout.addWidget(self.table)


class MockOutputPanel(QWidget):
    """Mock do Output Panel para testar docking"""

    def __init__(self):
        super().__init__()
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)

        # Header
        header = QLabel("Output Console")
        header.setStyleSheet("font-weight: bold; padding: 5px;")
        layout.addWidget(header)

        # Console de output
        self.console = QTextEdit()
        self.console.setReadOnly(True)
        self.console.setStyleSheet("""
            QTextEdit {
                background-color: #1e1e1e;
                color: #ffffff;
                font-family: 'Consolas', monospace;
                font-size: 10pt;
            }
        """)

        # Texto de exemplo
        self.console.setPlainText(
            """
> Executing Python code...
import pandas as pd
df = pd.DataFrame({'A': [1, 2, 3], 'B': [4, 5, 6]})
print(df.head())

   A  B
0  1  4
1  2  5
2  3  6

> Execution completed successfully.
        """.strip()
        )

        layout.addWidget(self.console)


class MockVariablesPanel(QWidget):
    """Mock do Variables Panel para testar docking"""

    def __init__(self):
        super().__init__()
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)

        # Header
        header = QLabel("Variables Explorer")
        header.setStyleSheet("font-weight: bold; padding: 5px;")
        layout.addWidget(header)

        # Variables list
        self.variables_list = QListWidget()

        # Example variables
        variables = [
            "df - DataFrame (3x2)",
            "df2 - DataFrame (1x2)",
            "x - int (42)",
            "result - str ('hello world')",
            "data - list (5 items)",
        ]

        for var in variables:
            self.variables_list.addItem(var)

        layout.addWidget(self.variables_list)


class MockEditorArea(QWidget):
    """Mock editor area for testing docking"""

    def __init__(self):
        super().__init__()
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)

        # Header
        header = QLabel("Editor Area (Python/SQL)")
        header.setStyleSheet("""
            font-weight: bold; 
            padding: 10px;
            background-color: #2d2d30;
            color: white;
        """)
        layout.addWidget(header)

        # Editor simulado
        editor = QTextEdit()
        editor.setStyleSheet("""
            QTextEdit {
                background-color: #1e1e1e;
                color: #d4d4d4;
                font-family: 'Consolas', monospace;
                font-size: 11pt;
            }
        """)

        # Example code
        example_code = """
import pandas as pd
import numpy as np

# Carrega dados
df = pd.read_csv('data.csv')

# Exploratory analysis
print(df.info())
print(df.describe())

# Filtragem
df_filtered = df[df['CEP'] == '28400-000']
print(f"Registros filtrados: {len(df_filtered)}")

# Visualization
df_filtered.head(10)
        """

        editor.setPlainText(example_code.strip())
        layout.addWidget(editor)


class DockingExampleWindow(DockingMainWindow):
    """
    Exemplo completo de como usar o sistema de docking

    Esta classe mostra como:
    1. Herdar de DockingMainWindow
    2. Add dockable panels
    3. Configurar layout inicial
    4. Permitir reposicionamento
    """

    def __init__(self):
        super().__init__()
        self.setWindowTitle("DataPyn - Docking System Demo")
        self._setup_content()
        self._setup_dockable_panels()

    def _setup_content(self):
        """Configure central content (editors)"""
        editor_area = MockEditorArea()
        self.set_central_content(editor_area)

    def _setup_dockable_panels(self):
        """Configure dockable panels"""

        # Results Panel (bottom by default)
        results_widget = MockResultsViewer()
        self.add_dockable_panel(name="results", widget=results_widget, title="Results", position="bottom", visible=True)

        # Output Panel (bottom by default, same area as Results)
        output_widget = MockOutputPanel()
        results_panel = self.get_panel("results")
        if results_panel:
            results_panel.add_tab(output_widget, "Output")

        # Variables Panel (right by default)
        variables_widget = MockVariablesPanel()
        self.add_dockable_panel(
            name="variables", widget=variables_widget, title="Variables", position="right", visible=True
        )

        # Conecta sinais para feedback
        self.panel_visibility_changed.connect(self._on_panel_visibility_changed)
        self.layout_restored.connect(self._on_layout_restored)

    def _on_panel_visibility_changed(self, name: str, visible: bool):
        """Callback quando visibilidade de painel muda"""
        status = "shown" if visible else "hidden"
        print(f"Panel '{name}' {status}")

    def _on_layout_restored(self):
        """Callback when layout is restored"""
        print("Layout restored from saved configuration")


def main():
    """Main function to test docking system"""
    app = QApplication(sys.argv)

    # Configure basic dark style
    app.setStyle("Fusion")

    dark_palette = """
    QWidget {
        background-color: #353535;
        color: #ffffff;
    }
    QTabWidget::pane {
        border: 1px solid #555555;
        background-color: #353535;
    }
    QTabBar::tab {
        padding: 5px 10px;
        margin-right: 2px;
        background-color: #555555;
        border: 1px solid #777777;
    }
    QTabBar::tab:selected {
        background-color: #0078d4;
    }
    QSplitter::handle {
        background-color: #555555;
        width: 3px;
        height: 3px;
    }
    """

    app.setStyleSheet(dark_palette)

    # Cria janela principal com docking
    window = DockingExampleWindow()
    window.show()

    # User instructions
    print("\n" + "=" * 60)
    print("DOCKING SYSTEM DEMO")
    print("=" * 60)
    print("- Arraste as abas (Results, Output, Variables) para reposicionar")
    print("- Use View > Panels menu to show/hide panels")
    print("- Use View > Reset Layout to restore default layout")
    print("- Layout is saved automatically")
    print("=" * 60 + "\n")

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
