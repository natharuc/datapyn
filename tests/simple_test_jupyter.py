#!/usr/bin/env python3
"""
Script de teste simplificado - testa apenas a funcao parse_ipynb_file isoladamente
"""

import json
import tempfile
import os


def parse_ipynb_file(file_path: str) -> list:
    """
    Parse um arquivo Jupyter Notebook e retorna lista de celulas de codigo.
    
    (Copia da implementacao em file_import_service.py para teste isolado)
    """
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            notebook = json.load(f)
    except json.JSONDecodeError as e:
        raise ValueError(f"Arquivo .ipynb invalido: {e}")
    except Exception as e:
        raise ValueError(f"Erro ao ler arquivo .ipynb: {e}")

    # Validar estrutura basica do notebook
    if not isinstance(notebook, dict):
        raise ValueError("Notebook deve ser um objeto JSON")

    cells = notebook.get("cells", [])
    if not isinstance(cells, list):
        raise ValueError("Campo 'cells' deve ser uma lista")

    # Extrair celulas de codigo
    result = []
    for cell in cells:
        cell_type = cell.get("cell_type", "code")
        source = cell.get("source", [])

        # Converter source para string
        if isinstance(source, list):
            code = "".join(source)
        elif isinstance(source, str):
            code = source
        else:
            code = ""

        # So adicionar celulas nao vazias
        if code.strip():
            result.append(
                {
                    "language": "python",
                    "code": code,
                    "cell_type": cell_type,
                }
            )

    return result


def test_parse_notebook():
    """Testa parse de arquivo notebook"""
    print("=" * 60)
    print("Teste: Parse de arquivo notebook")
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
        cells = parse_ipynb_file(temp_path)
        
        print(f"✓ Numero de celulas parseadas: {len(cells)}")
        assert len(cells) == 4, f"Deveria ter 4 celulas (ignora vazias), tem {len(cells)}"
        
        print("\nDetalhes das celulas:")
        for i, cell in enumerate(cells, 1):
            code_preview = cell['code'][:60].replace('\n', '\\n')
            print(f"  Celula {i}: [{cell['cell_type']}] {code_preview}...")
        
        # Verificar primeira celula
        assert cells[0]["language"] == "python"
        assert cells[0]["cell_type"] == "code"
        assert "import pandas" in cells[0]["code"]
        print("\n✓ Primeira celula verificada (imports)")
        
        # Verificar segunda celula
        assert cells[1]["language"] == "python"
        assert "DataFrame" in cells[1]["code"]
        print("✓ Segunda celula verificada (DataFrame)")
        
        # Verificar terceira celula (markdown)
        assert cells[2]["cell_type"] == "markdown"
        assert "Titulo" in cells[2]["code"]
        print("✓ Terceira celula verificada (markdown)")
        
        # Verificar quarta celula (a vazia foi pulada)
        assert cells[3]["cell_type"] == "code"
        assert "sum()" in cells[3]["code"]
        print("✓ Quarta celula verificada (sum)")
        
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)
    
    print()


def test_parse_invalid():
    """Testa erro ao parsear notebook invalido"""
    print("=" * 60)
    print("Teste: Tratamento de notebook invalido")
    print("=" * 60)
    
    with tempfile.NamedTemporaryFile(mode="w", suffix=".ipynb", delete=False, encoding="utf-8") as f:
        f.write("This is not valid JSON")
        temp_path = f.name
    
    try:
        try:
            parse_ipynb_file(temp_path)
            assert False, "Deveria lancar ValueError"
        except ValueError as e:
            error_msg = str(e)[:80]
            print(f"✓ ValueError lancado: {error_msg}...")
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)
    
    print()


def test_empty_cells():
    """Testa que celulas vazias sao ignoradas"""
    print("=" * 60)
    print("Teste: Ignorar celulas vazias")
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
        cells = parse_ipynb_file(temp_path)
        print(f"✓ Celulas nao-vazias: {len(cells)} (esperado: 2)")
        assert len(cells) == 2, f"Deveria ter 2 celulas, tem {len(cells)}"
        assert "hello" in cells[0]["code"]
        assert "world" in cells[1]["code"]
        print("✓ Celulas vazias ignoradas corretamente")
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)
    
    print()


def test_source_as_string():
    """Testa quando source e string ao inves de lista"""
    print("=" * 60)
    print("Teste: Source como string")
    print("=" * 60)
    
    notebook_data = {
        "cells": [
            {"cell_type": "code", "source": "print('hello')\nprint('world')"},
        ],
        "metadata": {},
        "nbformat": 4,
        "nbformat_minor": 2,
    }
    
    with tempfile.NamedTemporaryFile(mode="w", suffix=".ipynb", delete=False, encoding="utf-8") as f:
        json.dump(notebook_data, f)
        temp_path = f.name
    
    try:
        cells = parse_ipynb_file(temp_path)
        assert len(cells) == 1
        assert "hello" in cells[0]["code"]
        assert "world" in cells[0]["code"]
        print("✓ Source string parseado corretamente")
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)
    
    print()


def main():
    print("\n" + "=" * 60)
    print("TESTES DE PARSE JUPYTER NOTEBOOK")
    print("=" * 60 + "\n")
    
    try:
        test_parse_notebook()
        test_parse_invalid()
        test_empty_cells()
        test_source_as_string()
        
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
        print(f"✗✗✗ ERRO: {e}")
        import traceback
        traceback.print_exc()
        print("=" * 60)
        return 1


if __name__ == "__main__":
    import sys
    sys.exit(main())
