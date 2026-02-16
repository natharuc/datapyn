"""
StatusBar da aplicacao
"""

from PyQt6.QtWidgets import QStatusBar, QLabel
from PyQt6.QtCore import QTimer, QElapsedTimer
import qtawesome as qta


class MainStatusBar(QStatusBar):
    """Main status bar"""

    def __init__(self, theme_manager=None, parent=None):
        super().__init__(parent)

        self.theme_manager = theme_manager
        self._setup_style()
        self._setup_widgets()
        self._setup_timer()

    def _setup_style(self):
        """Configure statusbar style"""
        self.setStyleSheet("""
            QStatusBar {
                background-color: #252526;
                border-top: 1px solid #3e3e42;
                color: #999999;
                font-size: 12px;
            }
            QStatusBar QLabel {
                color: #999999;
                padding: 0px 6px;
            }
        """)

    def _update_connection_icon(self, connected: bool, text: str = ""):
        """Update connection icon"""
        if connected:
            icon = qta.icon("mdi.database-check", color="#4caf50")
            label = f" {text}" if text else " Connected"
        else:
            icon = qta.icon("mdi.database-off", color="#757575")
            label = " Disconnected"

        self.connection_label.setPixmap(icon.pixmap(16, 16))
        self.connection_label.setText(label)

    def _setup_widgets(self):
        # Action
        self.action_label = QLabel("Ready")
        self.addWidget(self.action_label, 1)

        # Active file (displays open file path)
        self.file_label = QLabel("")
        self.addPermanentWidget(self.file_label)

        # Connection with icon
        self.connection_label = QLabel()
        self._update_connection_icon(False)
        self.addPermanentWidget(self.connection_label)

        # Timer
        self.timer_label = QLabel("")
        self.addPermanentWidget(self.timer_label)

        # Cursor
        self.cursor_label = QLabel("Ln 1, Col 1")
        self.addPermanentWidget(self.cursor_label)

        # Timer to restore style after feedback
        self._feedback_timer = QTimer()
        self._feedback_timer.setSingleShot(True)
        self._feedback_timer.timeout.connect(self._restore_action_style)

    def _setup_timer(self):
        self.elapsed_timer = QElapsedTimer()
        self.update_timer = QTimer()
        self.update_timer.timeout.connect(self._update_timer_display)
        self.update_timer.setInterval(100)

    def _update_connection_icon(self, connected: bool, text: str = ""):
        """Update connection icon"""
        if connected:
            icon = qta.icon("mdi.database-check", color="#4caf50")
            label = f" {text}" if text else " Connected"
        else:
            icon = qta.icon("mdi.database-off", color="#757575")
            label = " Disconnected"

        self.connection_label.setPixmap(icon.pixmap(16, 16))
        self.connection_label.setText(label)

    def set_action(self, text: str):
        self.action_label.setText(text)

    def set_file_info(self, file_path: str = ""):
        """Display active file path in statusbar"""
        if file_path:
            self.file_label.setText(f"  {file_path}")
            self.file_label.setToolTip(file_path)
        else:
            self.file_label.setText("")
            self.file_label.setToolTip("")

    def show_save_feedback(self, message: str):
        """Exibe feedback visual de salvamento com destaque temporario"""
        self.action_label.setText(message)
        self.action_label.setStyleSheet("""
            QLabel {
                color: #4caf50;
                font-weight: bold;
                padding: 0px 6px;
            }
        """)
        self._feedback_timer.start(3000)

    def _restore_action_style(self):
        """Restaura estilo padrao da action_label apos feedback"""
        self.action_label.setStyleSheet("""
            QLabel {
                color: #999999;
                padding: 0px 6px;
            }
        """)

    def set_connection(self, connection_name: str = None, db_type: str = None):
        """Set connection"""
        if connection_name:
            text = f"{connection_name}"
            if db_type:
                text += f" ({db_type})"
            self._update_connection_icon(True, text)
        else:
            self._update_connection_icon(False)

    def set_cursor_position(self, line: int, column: int):
        self.cursor_label.setText(f"Ln {line}, Col {column}")

    def start_timer(self):
        self.elapsed_timer.start()
        self.update_timer.start()
        self.timer_label.setText("0.0s")

    def stop_timer(self):
        self.update_timer.stop()
        elapsed = self.elapsed_timer.elapsed() / 1000.0
        self.timer_label.setText(f"{elapsed:.2f}s")
        return elapsed

    def _update_timer_display(self):
        elapsed = self.elapsed_timer.elapsed() / 1000.0
        self.timer_label.setText(f"{elapsed:.1f}s")

    def clear_timer(self):
        self.update_timer.stop()
        self.timer_label.setText("")
