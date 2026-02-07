"""
StatusBar da aplicacao
"""

import qtawesome as qta
from PyQt6.QtCore import QElapsedTimer, QTimer
from PyQt6.QtWidgets import QLabel, QStatusBar


class MainStatusBar(QStatusBar):
    """StatusBar principal"""

    def __init__(self, theme_manager=None, parent=None):
        super().__init__(parent)

        self.theme_manager = theme_manager
        self._setup_style()
        self._setup_widgets()
        self._setup_timer()

    def _setup_style(self):
        """Configura estilo da statusbar"""
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
        """Atualiza ícone de conexão"""
        if connected:
            icon = qta.icon("mdi.database-check", color="#4caf50")
            label = f" {text}" if text else " Conectado"
        else:
            icon = qta.icon("mdi.database-off", color="#757575")
            label = " Desconectado"

        self.connection_label.setPixmap(icon.pixmap(16, 16))
        self.connection_label.setText(label)

    def _setup_widgets(self):
        # Ação
        self.action_label = QLabel("Pronto")
        self.addWidget(self.action_label, 1)

        # Conexão com ícone
        self.connection_label = QLabel()
        self._update_connection_icon(False)
        self.addPermanentWidget(self.connection_label)

        # Timer
        self.timer_label = QLabel("")
        self.addPermanentWidget(self.timer_label)

        # Cursor
        self.cursor_label = QLabel("Ln 1, Col 1")
        self.addPermanentWidget(self.cursor_label)

    def _setup_timer(self):
        self.elapsed_timer = QElapsedTimer()
        self.update_timer = QTimer()
        self.update_timer.timeout.connect(self._update_timer_display)
        self.update_timer.setInterval(100)

    def _update_connection_icon(self, connected: bool, text: str = ""):
        """Atualiza ícone de conexão"""
        if connected:
            icon = qta.icon("mdi.database-check", color="#4caf50")
            label = f" {text}" if text else " Conectado"
        else:
            icon = qta.icon("mdi.database-off", color="#757575")
            label = " Desconectado"

        self.connection_label.setPixmap(icon.pixmap(16, 16))
        self.connection_label.setText(label)

    def set_action(self, text: str):
        self.action_label.setText(text)

    def set_connection(self, connection_name: str = None, db_type: str = None):
        """Define conexão"""
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
