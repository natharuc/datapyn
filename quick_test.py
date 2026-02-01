#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Quick test to verify DataPyn can start
"""

if __name__ == '__main__':
    print("Testando imports básicos...")
    
    try:
        from PyQt6.QtWidgets import QApplication
        from PyQt6.Qsci import QsciScintilla
        import pandas as pd
        from sqlalchemy import create_engine
        
        print("✅ Imports OK!")
        print("\nTestando criação da janela principal...")
        
        from src.ui import MainWindow
        import sys
        
        app = QApplication(sys.argv)
        window = MainWindow()
        
        print("✅ Janela criada com sucesso!")
        print("\nDataPyn está pronto para uso!")
        print("Execute: python main.py")
        
    except Exception as e:
        print(f"❌ Erro: {e}")
        print("\nExecute: pip install -r requirements.txt")
