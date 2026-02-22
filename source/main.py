"""
DataPyn - IDE moderna para consultas SQL com Python integrado
"""

import sys
import os
import logging
from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import QIcon, QPalette, QColor
from PyQt6.QtCore import Qt

# Required for QtWebEngineWidgets (Monaco Editor) - must be set before QApplication
QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)

# Configurar logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.FileHandler("datapyn.log"), logging.StreamHandler()],
)


def get_icon_path():
    """Retorna caminho do icone, funciona tanto em dev quanto no EXE"""
    if getattr(sys, "frozen", False):
        # Executando como EXE (PyInstaller)
        base_path = sys._MEIPASS
    else:
        # Executando em desenvolvimento
        base_path = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base_path, "src", "assets", "datapyn-logo.ico")


def _apply_dark_palette(app):
    """Aplica paleta dark nativa via QPalette para visual consistente"""
    palette = QPalette()

    # Backgrounds
    palette.setColor(QPalette.ColorRole.Window, QColor("#1e1e1e"))
    palette.setColor(QPalette.ColorRole.Base, QColor("#252526"))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor("#2d2d30"))

    # Text
    palette.setColor(QPalette.ColorRole.WindowText, QColor("#cccccc"))
    palette.setColor(QPalette.ColorRole.Text, QColor("#cccccc"))
    palette.setColor(QPalette.ColorRole.BrightText, QColor("#ffffff"))
    palette.setColor(QPalette.ColorRole.PlaceholderText, QColor("#6e6e6e"))

    # Buttons
    palette.setColor(QPalette.ColorRole.Button, QColor("#2d2d30"))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor("#cccccc"))

    # Highlights
    palette.setColor(QPalette.ColorRole.Highlight, QColor("#3369FF"))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor("#ffffff"))

    # Misc
    palette.setColor(QPalette.ColorRole.ToolTipBase, QColor("#252526"))
    palette.setColor(QPalette.ColorRole.ToolTipText, QColor("#cccccc"))
    palette.setColor(QPalette.ColorRole.Link, QColor("#3369FF"))

    # Disabled
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.WindowText, QColor("#5a5a5a"))
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text, QColor("#5a5a5a"))
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.ButtonText, QColor("#5a5a5a"))

    app.setPalette(palette)


def main():
    """Funcao principal"""
    # Setar AppUserModelID para icone correto na barra de tarefas do Windows
    try:
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("datapyn.ide.datapyn.1")
    except Exception:
        pass

    app = QApplication(sys.argv)
    app.setApplicationName("DataPyn")
    app.setOrganizationName("DataPyn")

    # Estilo Fusion para visual consistente cross-platform
    app.setStyle("Fusion")

    # Paleta dark nativa
    _apply_dark_palette(app)

    # Splash screen - exibe imediatamente enquanto carrega
    from src.ui.splash_screen import SplashScreen

    splash = SplashScreen()
    splash.show()
    app.processEvents()

    splash.set_progress(10, "Loading language settings...")

    # Initialize i18n before creating any UI widgets
    from PyQt6.QtCore import QSettings
    from src.language import init_language
    settings = QSettings("DataPyn", "DataPyn")
    language = settings.value("language", "en-US")
    init_language(language)

    splash.set_progress(25, "Loading design system...")

    # Initialize editor backend from saved settings
    from src.editors.editor_config import init_editor_backend
    init_editor_backend()

    # Obter cores do design system
    from src.design_system.tokens import get_colors
    colors = get_colors()

    # Definir icone da aplicacao (afeta todas as janelas)
    icon_path = get_icon_path()
    if os.path.exists(icon_path):
        app_icon = QIcon(icon_path)
        app.setWindowIcon(app_icon)

    splash.set_progress(40, "Initializing application...")

    # Criar janela principal (a parte mais pesada - import deferido)
    from src.ui import MainWindow
    window = MainWindow(splash=splash)

    splash.set_progress(100, "Ready!")

    # Fechar splash e mostrar janela
    splash.finish_with_window(window)

    # Iniciar loop de eventos
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
