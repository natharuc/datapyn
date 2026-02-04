"""
DataPyn - IDE moderna para consultas SQL com Python integrado
"""
import sys
import os
import logging
from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import QIcon
from qt_material import apply_stylesheet
from src.ui import MainWindow


# Configurar logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('datapyn.log'),
        logging.StreamHandler()
    ]
)


def get_icon_path():
    """Retorna caminho do ícone, funciona tanto em dev quanto no EXE"""
    if getattr(sys, 'frozen', False):
        # Executando como EXE (PyInstaller)
        base_path = sys._MEIPASS
    else:
        # Executando em desenvolvimento
        base_path = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base_path, 'src', 'assets', 'datapyn-logo.ico')


def main():
    """Função principal"""
    app = QApplication(sys.argv)
    app.setApplicationName("DataPyn")
    app.setOrganizationName("DataPyn")
    
    # ⚡ APLICAR MATERIAL DESIGN THEME
    extra = {
        # Cores customizadas
        'danger': '#dc3545',
        'warning': '#ffc107',
        'success': '#28a745',
        'primaryColor': '#0d6efd',
        'primaryLightColor': '#4dabf7',
    }
    apply_stylesheet(app, theme='dark_blue.xml', extra=extra)
    
    # Definir ícone da aplicação (afeta todas as janelas)
    icon_path = get_icon_path()
    if os.path.exists(icon_path):
        app_icon = QIcon(icon_path)
        app.setWindowIcon(app_icon)
    
    # Criar e mostrar janela principal
    window = MainWindow()
    window.show()
    
    # Iniciar loop de eventos
    sys.exit(app.exec())


if __name__ == '__main__':
    main()
