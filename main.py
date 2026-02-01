"""
DataPyn - IDE moderna para consultas SQL com Python integrado
"""
import sys
import logging
from PyQt6.QtWidgets import QApplication
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


def main():
    """Função principal"""
    app = QApplication(sys.argv)
    app.setApplicationName("DataPyn")
    app.setOrganizationName("DataPyn")
    
    # Criar e mostrar janela principal
    window = MainWindow()
    window.show()
    
    # Iniciar loop de eventos
    sys.exit(app.exec())


if __name__ == '__main__':
    main()
