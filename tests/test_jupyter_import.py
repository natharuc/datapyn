"""
Testes para importacao de arquivos Jupyter Notebook (.ipynb)
"""

import pytest
import sys
import tempfile
import json
import os
from pathlib import Path
from PyQt6.QtWidgets import QApplication
from PyQt6.QtTest import QTest
from PyQt6.QtCore import Qt

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.services.file_import_service import FileImportService
from src.ui.main_window import MainWindow


@pytest.fixture
def sample_notebook():
    """Cria um arquivo notebook temporario para testes"""
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
                "source": ["df = pd.DataFrame({'a': [1, 2, 3], 'b': [4, 5, 6]})\n", "print(df)"],
            },
            {
                "cell_type": "markdown",
                "metadata": {},
                "source": ["# Titulo do Notebook\n", "Descricao do notebook"],
            },
            {
                "cell_type": "code",
                "execution_count": 3,
                "metadata": {},
                "outputs": [],
                "source": ["result = df['a'].sum()\n", "result"],
            },
        ],
        "metadata": {
            "kernelspec": {
                "display_name": "Python 3",
                "language": "python",
                "name": "python3",
            },
            "language_info": {"name": "python", "version": "3.12.0"},
        },
        "nbformat": 4,
        "nbformat_minor": 2,
    }

    with tempfile.NamedTemporaryFile(mode="w", suffix=".ipynb", delete=False, encoding="utf-8") as f:
        json.dump(notebook_data, f)
        temp_path = f.name

    yield temp_path

    # Cleanup
    if os.path.exists(temp_path):
        os.remove(temp_path)


@pytest.fixture
def empty_notebook():
    """Cria um notebook vazio"""
    notebook_data = {
        "cells": [],
        "metadata": {},
        "nbformat": 4,
        "nbformat_minor": 2,
    }

    with tempfile.NamedTemporaryFile(mode="w", suffix=".ipynb", delete=False, encoding="utf-8") as f:
        json.dump(notebook_data, f)
        temp_path = f.name

    yield temp_path

    if os.path.exists(temp_path):
        os.remove(temp_path)


@pytest.fixture
def invalid_notebook():
    """Cria um arquivo .ipynb invalido"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".ipynb", delete=False, encoding="utf-8") as f:
        f.write("This is not valid JSON")
        temp_path = f.name

    yield temp_path

    if os.path.exists(temp_path):
        os.remove(temp_path)


def test_ipynb_in_code_extensions():
    """Testa se .ipynb esta nas extensoes de codigo"""
    assert ".ipynb" in FileImportService.CODE_EXTENSIONS


def test_classify_ipynb_file(sample_notebook):
    """Testa classificacao de arquivo .ipynb"""
    result = FileImportService.classify_file(sample_notebook)
    assert result == "code"


def test_detect_language_ipynb(sample_notebook):
    """Testa deteccao de linguagem para .ipynb"""
    result = FileImportService.detect_language(sample_notebook)
    assert result == "python"


def test_parse_ipynb_file(sample_notebook):
    """Testa parse de arquivo notebook"""
    cells = FileImportService.parse_ipynb_file(sample_notebook)

    # Deve retornar 4 celulas (3 code + 1 markdown com conteudo)
    assert len(cells) == 4

    # Primeira celula deve ser codigo
    assert cells[0]["language"] == "python"
    assert cells[0]["cell_type"] == "code"
    assert "import pandas" in cells[0]["code"]

    # Segunda celula tambem codigo
    assert cells[1]["language"] == "python"
    assert cells[1]["cell_type"] == "code"
    assert "DataFrame" in cells[1]["code"]

    # Terceira celula e markdown
    assert cells[2]["language"] == "python"
    assert cells[2]["cell_type"] == "markdown"
    assert "Titulo" in cells[2]["code"]

    # Quarta celula e codigo
    assert cells[3]["language"] == "python"
    assert cells[3]["cell_type"] == "code"
    assert "sum()" in cells[3]["code"]


def test_parse_empty_notebook(empty_notebook):
    """Testa parse de notebook vazio"""
    cells = FileImportService.parse_ipynb_file(empty_notebook)
    assert cells == []


def test_parse_invalid_notebook(invalid_notebook):
    """Testa parse de arquivo .ipynb invalido"""
    with pytest.raises(ValueError, match="invalido"):
        FileImportService.parse_ipynb_file(invalid_notebook)


def test_parse_ipynb_with_empty_cells():
    """Testa que celulas vazias sao ignoradas"""
    notebook_data = {
        "cells": [
            {"cell_type": "code", "source": ["print('hello')"]},
            {"cell_type": "code", "source": []},  # Celula vazia
            {"cell_type": "code", "source": ["   "]},  # Celula com espacos
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
        # Apenas 2 celulas com conteudo devem ser retornadas
        assert len(cells) == 2
        assert "hello" in cells[0]["code"]
        assert "world" in cells[1]["code"]
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)


def test_parse_ipynb_source_as_string():
    """Testa parse quando source e string ao inves de lista"""
    notebook_data = {
        "cells": [
            {"cell_type": "code", "source": "print('hello')\nprint('world')"},  # String ao inves de lista
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
        assert len(cells) == 1
        assert "hello" in cells[0]["code"]
        assert "world" in cells[0]["code"]
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)


@pytest.fixture
def main_window(qapp):
    """Fixture da MainWindow"""
    window = MainWindow()
    window.show()
    QTest.qWaitForWindowExposed(window)

    # Aguardar restauracao completa
    max_wait_time = 10000
    wait_interval = 100
    max_iterations = max_wait_time // wait_interval

    for _ in range(max_iterations):
        QApplication.processEvents()
        QTest.qWait(50)
        if not hasattr(window, "_sessions_to_load") or not window._sessions_to_load:
            break
        QTest.qWait(wait_interval)

    QApplication.processEvents()
    QTest.qWait(100)
    return window


def test_open_notebook_file(main_window, sample_notebook):
    """Testa abertura de arquivo .ipynb pela UI"""
    # Abrir arquivo programaticamente
    main_window._open_code_file(sample_notebook)

    QApplication.processEvents()
    QTest.qWait(200)

    # Verificar se a aba foi criada
    assert main_window.session_tabs.count() > 0

    # Pegar widget da sessao
    widget = main_window.session_tabs.currentWidget()
    assert widget is not None

    # Verificar se o arquivo foi associado
    assert hasattr(widget, "file_path")
    assert widget.file_path == sample_notebook

    # Verificar se blocos foram criados (deve ter 4 blocos)
    blocks = widget.editor.get_blocks()
    assert len(blocks) == 4

    # Verificar conteudo do primeiro bloco
    assert blocks[0].get_language() == "python"
    assert "import pandas" in blocks[0].get_code()

    # Verificar segundo bloco
    assert blocks[1].get_language() == "python"
    assert "DataFrame" in blocks[1].get_code()

    # Verificar terceiro bloco (markdown)
    assert "Titulo" in blocks[2].get_code()

    # Verificar quarto bloco
    assert "sum()" in blocks[3].get_code()


def test_open_empty_notebook(main_window, empty_notebook):
    """Testa abertura de notebook vazio"""
    main_window._open_code_file(empty_notebook)

    QApplication.processEvents()
    QTest.qWait(200)

    widget = main_window.session_tabs.currentWidget()
    assert widget is not None

    # Notebook vazio deve criar apenas o bloco padrao vazio
    blocks = widget.editor.get_blocks()
    assert len(blocks) >= 1  # Pelo menos o bloco padrao
