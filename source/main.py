"""
DataPyn - IDE moderna para consultas SQL com Python integrado
"""

import sys
import os
import logging
from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import QIcon, QPalette, QColor, QFont
from PyQt6.QtCore import Qt

# Required for QtWebEngineWidgets (Monaco Editor) - must be set before QApplication
QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)

def _configure_logging() -> None:
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
    """Native QPalette — DataPyn blue dark (matches design-system tokens)."""
    from src.design_system.tokens import (
        CHROME_ACCENT,
        CHROME_BG,
        CHROME_CARD,
        CHROME_MUTED,
        CHROME_TEXT,
    )

    palette = QPalette()

    palette.setColor(QPalette.ColorRole.Window, QColor(CHROME_BG))
    palette.setColor(QPalette.ColorRole.Base, QColor("#121a2b"))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor(CHROME_CARD))

    palette.setColor(QPalette.ColorRole.WindowText, QColor(CHROME_TEXT))
    palette.setColor(QPalette.ColorRole.Text, QColor(CHROME_TEXT))
    palette.setColor(QPalette.ColorRole.BrightText, QColor("#ffffff"))
    palette.setColor(QPalette.ColorRole.PlaceholderText, QColor(CHROME_MUTED))

    palette.setColor(QPalette.ColorRole.Button, QColor("#1a2438"))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor(CHROME_TEXT))

    palette.setColor(QPalette.ColorRole.Highlight, QColor(CHROME_ACCENT))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor("#ffffff"))

    palette.setColor(QPalette.ColorRole.ToolTipBase, QColor(CHROME_CARD))
    palette.setColor(QPalette.ColorRole.ToolTipText, QColor(CHROME_TEXT))
    palette.setColor(QPalette.ColorRole.Link, QColor(CHROME_ACCENT))

    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.WindowText, QColor("#5c6d85"))
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text, QColor("#5c6d85"))
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.ButtonText, QColor("#5c6d85"))

    app.setPalette(palette)


def main():
    """Funcao principal"""
    import argparse

    # Make CPython preempt CPU-bound worker threads more often (default 5ms).
    # Keeps the UI thread responsive while background threads build large
    # DataFrames or serialize Parquet (GIL-heavy work).
    sys.setswitchinterval(0.001)

    # Parse command line arguments
    parser = argparse.ArgumentParser(description="DataPyn - IDE moderna para consultas SQL com Python integrado")
    parser.add_argument("--workspace", type=str, help="Path to workspace folder to open")
    args, unknown = parser.parse_known_args()
    
    # Setar AppUserModelID para icone correto na barra de tarefas do Windows
    try:
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("datapyn.ide.datapyn.1")
    except Exception:
        pass

    app = QApplication(sys.argv)
    app.setApplicationName("DataPyn")
    app.setOrganizationName("DataPyn")
    app.setStyle("Fusion")

    # Splash o mais cedo possível (antes de fontes, tema e imports pesados)
    from src.ui.splash_screen import SplashScreen

    splash = SplashScreen()
    splash.show()
    app.processEvents()

    _configure_logging()

    splash.set_progress(8, "Carregando fontes…")
    from src.design_system.font_manager import initialize_fonts, get_application_font

    initialize_fonts()

    global_font = get_application_font(size=10)
    app.setFont(global_font)

    splash.set_progress(18, "Aplicando tema…")
    from src.design_system.stylesheet import get_application_stylesheet

    _apply_dark_palette(app)
    app.setStyleSheet(get_application_stylesheet())

    splash.set_progress(28, "Carregando idioma…")
    from PyQt6.QtCore import QSettings
    from src.language import init_language

    settings = QSettings("DataPyn", "DataPyn")
    language = settings.value("language", "en-US")
    init_language(language)

    splash.set_progress(38, "Preparando ambiente…")
    
    # Handle --workspace argument: switch to specified workspace before loading UI
    if args.workspace:
        from pathlib import Path
        from src.core.workspace_service import get_workspace_service
        ws_service = get_workspace_service()
        workspace_path = Path(args.workspace)
        if workspace_path.exists():
            logging.info(f"Switching to workspace from command line: {workspace_path}")
            ws_service.switch_workspace(workspace_path)
        else:
            logging.warning(f"Workspace path does not exist: {workspace_path}")

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

    splash.set_progress(48, "Inicializando serviços…")

    # Ensure venv site-packages is on sys.path early, so that packages
    # installed via Package Manager are importable by PythonWorker.
    # This must happen before MainWindow is created (which may trigger code execution).
    try:
        from src.services.package_manager_service import PackageManagerService
        _pkg_svc = PackageManagerService()
        del _pkg_svc
    except Exception:
        logging.warning("Failed to initialize PackageManagerService for venv path setup")

    splash.set_progress(55, "Abrindo interface…")
    from src.ui import MainWindow

    window = MainWindow(splash=splash)

    splash.finish_with_window(window)

    # Iniciar loop de eventos
    sys.exit(app.exec())


if __name__ == "__main__":
    from src.services.in_app_update import try_run_apply_update_from_argv

    try_run_apply_update_from_argv(sys.argv)
    main()
