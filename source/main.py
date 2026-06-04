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
    """Aplica paleta dark nativa via QPalette para visual consistente"""
    palette = QPalette()

    # Backgrounds - with subtle blue undertone
    palette.setColor(QPalette.ColorRole.Window, QColor("#181a1f"))
    palette.setColor(QPalette.ColorRole.Base, QColor("#1f2228"))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor("#282c34"))

    # Text
    palette.setColor(QPalette.ColorRole.WindowText, QColor("#dcdee4"))
    palette.setColor(QPalette.ColorRole.Text, QColor("#dcdee4"))
    palette.setColor(QPalette.ColorRole.BrightText, QColor("#ffffff"))
    palette.setColor(QPalette.ColorRole.PlaceholderText, QColor("#70758a"))

    # Buttons
    palette.setColor(QPalette.ColorRole.Button, QColor("#282c34"))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor("#dcdee4"))

    # Highlights - modern blue
    palette.setColor(QPalette.ColorRole.Highlight, QColor("#3b82f6"))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor("#ffffff"))

    # Misc
    palette.setColor(QPalette.ColorRole.ToolTipBase, QColor("#282c34"))
    palette.setColor(QPalette.ColorRole.ToolTipText, QColor("#dcdee4"))
    palette.setColor(QPalette.ColorRole.Link, QColor("#3b82f6"))

    # Disabled
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.WindowText, QColor("#50556b"))
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text, QColor("#50556b"))
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.ButtonText, QColor("#50556b"))

    app.setPalette(palette)


def main():
    """Funcao principal"""
    import argparse
    
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
    from src.design_system.font_manager import FONT_FAMILY_PRIMARY

    app.setStyleSheet(f"""
        * {{
            font-family: {FONT_FAMILY_PRIMARY};
        }}
        QToolTip {{
            font-size: 11px;
            padding: 6px 10px;
            border-radius: 6px;
        }}
        QScrollBar:vertical {{
            background: transparent;
            width: 8px;
            margin: 0px;
        }}
        QScrollBar::handle:vertical {{
            background: rgba(128, 128, 128, 0.3);
            border-radius: 4px;
            min-height: 40px;
            margin: 2px;
        }}
        QScrollBar::handle:vertical:hover {{
            background: rgba(128, 128, 128, 0.5);
        }}
        QScrollBar::handle:vertical:pressed {{
            background: rgba(128, 128, 128, 0.7);
        }}
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
            height: 0px;
        }}
        QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
            background: none;
        }}
        QScrollBar:horizontal {{
            background: transparent;
            height: 8px;
            margin: 0px;
        }}
        QScrollBar::handle:horizontal {{
            background: rgba(128, 128, 128, 0.3);
            border-radius: 4px;
            min-width: 40px;
            margin: 2px;
        }}
        QScrollBar::handle:horizontal:hover {{
            background: rgba(128, 128, 128, 0.5);
        }}
        QScrollBar::handle:horizontal:pressed {{
            background: rgba(128, 128, 128, 0.7);
        }}
        QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
            width: 0px;
        }}
        QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{
            background: none;
        }}
        QScrollBar::corner {{
            background: transparent;
        }}
    """)

    _apply_dark_palette(app)

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
    main()
