"""
Script de teste para validar instalação do DataPyn
"""
import sys

def test_imports():
    """Testa se todos os módulos necessários estão instalados"""
    print("=" * 50)
    print("TESTE DE INSTALAÇÃO - DataPyn IDE")
    print("=" * 50)
    print()
    
    errors = []
    
    # Testar PyQt6
    print("Testando PyQt6...", end=" ")
    try:
        from PyQt6.QtWidgets import QApplication
        from PyQt6.QtCore import Qt
        from PyQt6.QtGui import QFont
        print("✅ OK")
    except ImportError as e:
        print("❌ ERRO")
        errors.append(("PyQt6", str(e)))
    
    # Testar QScintilla
    print("Testando QScintilla...", end=" ")
    try:
        from PyQt6.Qsci import QsciScintilla, QsciLexerSQL, QsciLexerPython
        print("✅ OK")
    except ImportError as e:
        print("❌ ERRO")
        errors.append(("PyQt6-QScintilla", str(e)))
    
    # Testar Pandas
    print("Testando Pandas...", end=" ")
    try:
        import pandas as pd
        import numpy as np
        print("✅ OK")
    except ImportError as e:
        print("❌ ERRO")
        errors.append(("Pandas/NumPy", str(e)))
    
    # Testar SQLAlchemy
    print("Testando SQLAlchemy...", end=" ")
    try:
        from sqlalchemy import create_engine, text
        print("✅ OK")
    except ImportError as e:
        print("❌ ERRO")
        errors.append(("SQLAlchemy", str(e)))
    
    # Testar drivers SQL
    print("\nTestando drivers de banco de dados:")
    
    print("  - PyMySQL (MySQL)...", end=" ")
    try:
        import pymysql
        print("✅ OK")
    except ImportError as e:
        print("⚠️ Não instalado (opcional)")
    
    print("  - psycopg2 (PostgreSQL)...", end=" ")
    try:
        import psycopg2
        print("✅ OK")
    except ImportError as e:
        print("⚠️ Não instalado (opcional)")
    
    print("  - pyodbc (SQL Server)...", end=" ")
    try:
        import pyodbc
        print("✅ OK")
    except ImportError as e:
        print("⚠️ Não instalado (opcional)")
    
    print("  - pymssql (SQL Server alt)...", end=" ")
    try:
        import pymssql
        print("✅ OK")
    except ImportError as e:
        print("⚠️ Não instalado (opcional)")
    
    print("  - mariadb...", end=" ")
    try:
        import mariadb
        print("✅ OK")
    except ImportError as e:
        print("⚠️ Não instalado (opcional)")
    
    # Testar módulos do projeto
    print("\nTestando módulos do projeto:")
    
    print("  - database...", end=" ")
    try:
        from src.database import DatabaseConnector, ConnectionManager
        print("✅ OK")
    except ImportError as e:
        print("❌ ERRO")
        errors.append(("src.database", str(e)))
    
    print("  - editors...", end=" ")
    try:
        from src.editors import SQLEditor, PythonEditor
        print("✅ OK")
    except ImportError as e:
        print("❌ ERRO")
        errors.append(("src.editors", str(e)))
    
    print("  - core...", end=" ")
    try:
        from src.core import ResultsManager, ShortcutManager
        print("✅ OK")
    except ImportError as e:
        print("❌ ERRO")
        errors.append(("src.core", str(e)))
    
    print("  - ui...", end=" ")
    try:
        from src.ui import MainWindow, ConnectionDialog, ResultsViewer
        print("✅ OK")
    except ImportError as e:
        print("❌ ERRO")
        errors.append(("src.ui", str(e)))
    
    # Resumo
    print("\n" + "=" * 50)
    if errors:
        print("❌ INSTALAÇÃO INCOMPLETA")
        print("=" * 50)
        print("\nErros encontrados:")
        for module, error in errors:
            print(f"\n  {module}:")
            print(f"    {error}")
        print("\nExecute:")
        print("  pip install -r requirements.txt")
        return False
    else:
        print("✅ INSTALAÇÃO OK!")
        print("=" * 50)
        print("\nTodos os módulos necessários estão instalados.")
        print("Você pode executar o DataPyn com:")
        print("  python main.py")
        return True


def test_qt_display():
    """Testa se a interface gráfica funciona"""
    print("\n" + "=" * 50)
    print("TESTE DE INTERFACE GRÁFICA")
    print("=" * 50)
    print("\nTentando criar uma janela de teste...")
    
    try:
        from PyQt6.QtWidgets import QApplication, QMessageBox
        
        app = QApplication(sys.argv)
        
        msg = QMessageBox()
        msg.setWindowTitle("Teste DataPyn")
        msg.setText("✅ Interface gráfica funcionando!\n\nSe você está vendo esta mensagem, o PyQt6 está configurado corretamente.")
        msg.setIcon(QMessageBox.Icon.Information)
        msg.exec()
        
        print("✅ Interface gráfica OK!")
        return True
        
    except Exception as e:
        print(f"❌ Erro na interface gráfica: {e}")
        return False


if __name__ == '__main__':
    print()
    print("Versão do Python:", sys.version)
    print()
    
    # Teste de imports
    imports_ok = test_imports()
    
    if imports_ok:
        # Teste de interface
        print("\nDeseja testar a interface gráfica? (s/n): ", end="")
        try:
            resposta = input().lower()
            if resposta == 's':
                test_qt_display()
        except:
            pass
    
    print("\nTeste concluído!")
    print()
