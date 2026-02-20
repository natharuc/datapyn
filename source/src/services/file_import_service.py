"""
FileImportService - Servico centralizado para importacao de arquivos

Responsavel por:
- Abrir arquivos de codigo (.sql, .py)
- Abrir workspaces (.dpw)
- Importar arquivos de dados (.csv, .json, .xlsx)
- Tratar drag-and-drop de arquivos (tela vazia ou editor)

Principio: Toda importacao de arquivo DEVE passar por este servico.
"""

import os
from typing import List, Optional, Tuple
from PyQt6.QtCore import QObject, pyqtSignal


def _read_file_with_encoding_fallback(filepath: str) -> str:
    """
    Read file content with encoding fallback.
    
    Tries utf-8 first, then detects encoding with chardet,
    finally falls back to latin-1 (which never fails).
    """
    # Try utf-8 first (most common)
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            return f.read()
    except UnicodeDecodeError:
        pass
    
    # Try to detect encoding with chardet if available
    try:
        import chardet
        with open(filepath, "rb") as f:
            raw_data = f.read()
        detected = chardet.detect(raw_data)
        encoding = detected.get("encoding", "latin-1") or "latin-1"
        return raw_data.decode(encoding)
    except ImportError:
        pass
    except Exception:
        pass
    
    # Fallback to latin-1 (never fails, but may produce garbage for some encodings)
    with open(filepath, "r", encoding="latin-1") as f:
        return f.read()


class FileImportService(QObject):
    """
    Servico centralizado para importacao de arquivos.

    Classifica arquivos por tipo e delega para o handler correto.
    Garante que sessoes e paineis sejam criados consistentemente.
    """

    # Extensoes suportadas
    CODE_EXTENSIONS = (".sql", ".py", ".ipynb")
    DATA_EXTENSIONS = (".csv", ".json", ".xlsx", ".xls")
    WORKSPACE_EXTENSIONS = (".dpw",)
    ALL_EXTENSIONS = CODE_EXTENSIONS + DATA_EXTENSIONS + WORKSPACE_EXTENSIONS

    # Sinais
    file_opened = pyqtSignal(str, str)  # (file_path, file_type)
    import_error = pyqtSignal(str, str)  # (file_path, error_message)

    def __init__(self, parent=None):
        super().__init__(parent)

    @staticmethod
    def classify_file(file_path: str) -> Optional[str]:
        """
        Classifica um arquivo pelo tipo.

        Returns:
            'code', 'data', 'workspace' ou None se nao suportado
        """
        ext = os.path.splitext(file_path.lower())[1]
        if ext in FileImportService.CODE_EXTENSIONS:
            return "code"
        elif ext in FileImportService.DATA_EXTENSIONS:
            return "data"
        elif ext in FileImportService.WORKSPACE_EXTENSIONS:
            return "workspace"
        return None

    @staticmethod
    def detect_language(file_path: str) -> str:
        """Detecta a linguagem do arquivo."""
        lower_path = file_path.lower()
        if lower_path.endswith(".py") or lower_path.endswith(".ipynb"):
            return "python"
        return "sql"

    @staticmethod
    def is_supported(file_path: str) -> bool:
        """Verifica se o arquivo e suportado."""
        ext = os.path.splitext(file_path.lower())[1]
        return ext in FileImportService.ALL_EXTENSIONS

    @staticmethod
    def read_file_content(file_path: str) -> str:
        """Le o conteudo de um arquivo texto."""
        return _read_file_with_encoding_fallback(file_path)

    @staticmethod
    def classify_file_list(file_paths: List[str]) -> Tuple[List[str], List[str], List[str]]:
        """
        Classifica uma lista de arquivos em categorias.

        Returns:
            Tupla (code_files, data_files, workspace_files)
        """
        code_files = []
        data_files = []
        workspace_files = []

        for fp in file_paths:
            kind = FileImportService.classify_file(fp)
            if kind == "code":
                code_files.append(fp)
            elif kind == "data":
                data_files.append(fp)
            elif kind == "workspace":
                workspace_files.append(fp)

        return code_files, data_files, workspace_files

    @staticmethod
    def _normalize_var_name(file_path: str) -> str:
        """Normaliza o nome do arquivo para um nome de variavel Python valido.

        Regras:
        - Converte para minusculo
        - Substitui espacos e caracteres invalidos por _
        - Remove underscores duplicados e nas bordas
        - Prefixo df_ se comecar com digito
        """
        base_name = os.path.splitext(os.path.basename(file_path))[0]
        # Minusculo
        name = base_name.lower()
        # Substituir caracteres invalidos por _
        name = "".join(c if c.isalnum() or c == "_" else "_" for c in name)
        # Remover underscores duplicados
        while "__" in name:
            name = name.replace("__", "_")
        # Remover underscores nas bordas
        name = name.strip("_")
        # Se vazio, fallback
        if not name:
            name = "df"
        # Prefixo se comecar com digito
        if name[0].isdigit():
            name = f"df_{name}"
        return name

    @staticmethod
    def generate_import_code(file_path: str) -> Optional[str]:
        """Gera codigo Python para importar um arquivo de dados."""
        ext = os.path.splitext(file_path.lower())[1]
        # Usar raw string ou forward slashes para caminhos Windows
        safe_path = file_path.replace("\\", "/")
        var_name = FileImportService._normalize_var_name(file_path)

        if ext == ".csv":
            return f'import pandas as pd\n{var_name} = pd.read_csv("{safe_path}", sep=";")\n{var_name}'
        elif ext == ".json":
            return f'import pandas as pd\n{var_name} = pd.read_json("{safe_path}")\n{var_name}'
        elif ext in (".xlsx", ".xls"):
            return f'import fastexcel\n{var_name} = fastexcel.read_excel("{safe_path}").load_sheet(0).to_pandas()\n{var_name}'

        return None

    @staticmethod
    def parse_ipynb_file(file_path: str) -> list:
        """
        Parse um arquivo Jupyter Notebook e retorna lista de celulas de codigo.

        Returns:
            Lista de dicionarios com:
            - 'language': Linguagem da celula (sempre 'python' para Jupyter)
            - 'code': Codigo da celula
            - 'cell_type': Tipo da celula ('code', 'markdown', 'raw')

        Raises:
            ValueError: Se o arquivo nao for um notebook valido
        """
        import json

        try:
            content = _read_file_with_encoding_fallback(file_path)
            notebook = json.loads(content)
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
