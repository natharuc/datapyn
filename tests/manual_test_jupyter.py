#!/usr/bin/env python3
"""
Script de teste manual para funcionalidade de import de Jupyter Notebook
"""

import sys
import json
import tempfile
import os
from pathlib import Path

# Adicionar source ao path
sys.path.insert(0, str(Path(__file__).parent.parent / "source"))

from src.services.file_import_service import FileImportService


def test_basic_functionality():
    """Testa funcionalidades basicas do FileImportService"""
    print("=" * 60)
    print("Teste 1: Verificar se .ipynb esta nas extensoes de codigo")
    print("=" * 60)
    
    result = ".ipynb" in FileImportService.CODE_EXTENSIONS
    print(f"✓ .ipynb em CODE_EXTENSIONS: {result}")
    assert result, ".ipynb deveria estar em CODE_EXTENSIONS"
    print()


def test_classify_file():
    """Testa classificacao de arquivo"""
    print("=" * 60)
    print("Teste 2: Classificar arquivo .ipynb")
    print("=" * 60)
    
    result = FileImportService.classify_file("test.ipynb")
    print(f"✓ Classificacao de 'test.ipynb': {result}")
    assert result == "code", "Deveria classificar como 'code'"
    print()


def test_detect_language():
    """Testa deteccao de linguagem"""
    print("=" * 60)
    print("Teste 3: Detectar linguagem de arquivo .ipynb")
    print("=" * 60)
    
    result = FileImportService.detect_language("test.ipynb")
    print(f"✓ Linguagem de 'test.ipynb': {result}")
    assert result == "python", "Deveria detectar como 'python'"
    print()


def test_parse_notebook():
    """Testa parse de arquivo notebook"""
    print("=" * 60)
    print("Teste 4: Parse de arquivo notebook")
    print("=" * 60)
    
    # Criar notebook de teste
    notebook_data = {
        "cells": [
            {
                "cell_type": "code",
                "execution_count": 1,
                "metadata": {},
                "outputs": [],
                "source": ["import pandas as pd\n", "import numpy as np\n"],
            },
            {
                "cell_type": "code",
                "execution_count": 2,
                "metadata": {},
                "outputs": [],
                "source": ["df = pd.DataFrame({'a': [1, 2, 3]})\n", "print(df)"],
            },
            {
                "cell_type": "markdown",
                "metadata": {},
                "source": ["# Titulo\n", "Descricao"],
            },
            {
                "cell_type": "code",
                "execution_count": 3,
                "metadata": {},
                "outputs": [],
                "source": [],  # Celula vazia
            },
            {
                "cell_type": "code",
                "execution_count": 4,
                "metadata": {},
                "outputs": [],
                "source": ["result = df['a'].sum()\n", "result"],
            },
        ],
        "metadata": {},
        "nbformat": 4,
        "nbformat_minor": 2,
    }
    
    # Salvar em arquivo temporario
    with tempfile.NamedTemporaryFile(mode="w", suffix=".ipynb", delete=False, encoding="utf-8") as f:
        json.dump(notebook_data, f)
        temp_path = f.name
    
    try:
        cells = FileImportService.parse_ipynb_file(temp_path)
        
        print(f"✓ Numero de celulas parseadas: {len(cells)}")
        assert len(cells) == 4, f"Deveria ter 4 celulas (ignora vazias), tem {len(cells)}"
        
        print("\nDetalhes das celulas:")
        for i, cell in enumerate(cells, 1):
            print(f"  Celula {i}:")
            print(f"    - Tipo: {cell['cell_type']}")
            print(f"    - Linguagem: {cell['language']}")
            print(f"    - Codigo (primeiras 50 chars): {cell['code'][:50]}...")
        
        # Verificar primeira celula
        assert cells[0]["language"] == "python"
        assert cells[0]["cell_type"] == "code"
        assert "import pandas" in cells[0]["code"]
        print("\n✓ Primeira celula verificada corretamente")
        
        # Verificar segunda celula
        assert cells[1]["language"] == "python"
        assert "DataFrame" in cells[1]["code"]
        print("✓ Segunda celula verificada corretamente")
        
        # Verificar terceira celula (markdown)
        assert cells[2]["cell_type"] == "markdown"
        assert "Titulo" in cells[2]["code"]
        print("✓ Terceira celula (markdown) verificada corretamente")
        
        # Verificar quarta celula (a vazia foi pulada)
        assert cells[3]["cell_type"] == "code"
        assert "sum()" in cells[3]["code"]
        print("✓ Quarta celula verificada corretamente")
        
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)
    
    print()


def test_parse_invalid_notebook():
    """Testa erro ao parsear notebook invalido"""
    print("=" * 60)
    print("Teste 5: Tratamento de notebook invalido")
    print("=" * 60)
    
    # Criar arquivo invalido
    with tempfile.NamedTemporaryFile(mode="w", suffix=".ipynb", delete=False, encoding="utf-8") as f:
        f.write("This is not valid JSON")
        temp_path = f.name
    
    try:
        try:
            FileImportService.parse_ipynb_file(temp_path)
            assert False, "Deveria lancar ValueError"
        except ValueError as e:
            print(f"✓ ValueError lancado corretamente: {str(e)[:60]}...")
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)
    
    print()


def test_parse_empty_cells():
    """Testa que celulas vazias sao ignoradas"""
    print("=" * 60)
    print("Teste 6: Ignorar celulas vazias")
    print("=" * 60)
    
    notebook_data = {
        "cells": [
            {"cell_type": "code", "source": ["print('hello')"]},
            {"cell_type": "code", "source": []},  # Vazia
            {"cell_type": "code", "source": ["   "]},  # Apenas espacos
            {"cell_type": "code", "source": ["print('world')"]},
        ],
        "metadata": {},
        "nbformat": 4,
        "nbformat_minor": 2,
    }
    
    with tempfile.NamedTemporaryFile(mode="w", suffix=".ipynb", delete=False, encoding="utf-8") as f:
        json.dump(notebook_data, f)
        temp_path = f.name
    
    try:
        cells = FileImportService.parse_ipynb_file(temp_path)
        print(f"✓ Celulas nao-vazias encontradas: {len(cells)}")
        assert len(cells) == 2, f"Deveria ter 2 celulas, tem {len(cells)}"
        assert "hello" in cells[0]["code"]
        assert "world" in cells[1]["code"]
        print("✓ Celulas vazias foram ignoradas corretamente")
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)
    
    print()


def main():
    """Executa todos os testes"""
    print("\n" + "=" * 60)
    print("TESTES DE IMPORTACAO JUPYTER NOTEBOOK")
    print("=" * 60 + "\n")
    
    try:
        test_basic_functionality()
        test_classify_file()
        test_detect_language()
        test_parse_notebook()
        test_parse_invalid_notebook()
        test_parse_empty_cells()
        
        print("=" * 60)
        print("✓✓✓ TODOS OS TESTES PASSARAM! ✓✓✓")
        print("=" * 60)
        return 0
        
    except AssertionError as e:
        print("\n" + "=" * 60)
        print(f"✗✗✗ TESTE FALHOU: {e}")
        print("=" * 60)
        return 1
    except Exception as e:
        print("\n" + "=" * 60)
        print(f"✗✗✗ ERRO INESPERADO: {e}")
        import traceback
        traceback.print_exc()
        print("=" * 60)
        return 1


if __name__ == "__main__":
    sys.exit(main())
