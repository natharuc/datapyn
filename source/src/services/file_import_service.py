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


class FileImportService(QObject):
    """
    Servico centralizado para importacao de arquivos.
    
    Classifica arquivos por tipo e delega para o handler correto.
    Garante que sessoes e paineis sejam criados consistentemente.
    """
    
    # Extensoes suportadas
    CODE_EXTENSIONS = ('.sql', '.py')
    DATA_EXTENSIONS = ('.csv', '.json', '.xlsx', '.xls')
    WORKSPACE_EXTENSIONS = ('.dpw',)
    ALL_EXTENSIONS = CODE_EXTENSIONS + DATA_EXTENSIONS + WORKSPACE_EXTENSIONS
    
    # Sinais
    file_opened = pyqtSignal(str, str)     # (file_path, file_type)
    import_error = pyqtSignal(str, str)    # (file_path, error_message)
    
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
            return 'code'
        elif ext in FileImportService.DATA_EXTENSIONS:
            return 'data'
        elif ext in FileImportService.WORKSPACE_EXTENSIONS:
            return 'workspace'
        return None
    
    @staticmethod
    def detect_language(file_path: str) -> str:
        """Detecta a linguagem do arquivo."""
        if file_path.lower().endswith('.py'):
            return 'python'
        return 'sql'
    
    @staticmethod
    def is_supported(file_path: str) -> bool:
        """Verifica se o arquivo e suportado."""
        ext = os.path.splitext(file_path.lower())[1]
        return ext in FileImportService.ALL_EXTENSIONS
    
    @staticmethod
    def read_file_content(file_path: str) -> str:
        """Le o conteudo de um arquivo texto."""
        with open(file_path, 'r', encoding='utf-8') as f:
            return f.read()
    
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
            if kind == 'code':
                code_files.append(fp)
            elif kind == 'data':
                data_files.append(fp)
            elif kind == 'workspace':
                workspace_files.append(fp)
        
        return code_files, data_files, workspace_files
    
    @staticmethod
    def generate_import_code(file_path: str) -> Optional[str]:
        """Gera codigo Python para importar um arquivo de dados."""
        ext = os.path.splitext(file_path.lower())[1]
        # Usar raw string ou forward slashes para caminhos Windows
        safe_path = file_path.replace('\\', '/')
        var_name = os.path.splitext(os.path.basename(file_path))[0]
        # Limpar nome da variavel (remover caracteres invalidos)
        var_name = ''.join(c if c.isalnum() or c == '_' else '_' for c in var_name)
        if var_name[0].isdigit():
            var_name = f'df_{var_name}'
        
        if ext == '.csv':
            return f'import pandas as pd\n{var_name} = pd.read_csv("{safe_path}")\n{var_name}'
        elif ext == '.json':
            return f'import pandas as pd\n{var_name} = pd.read_json("{safe_path}")\n{var_name}'
        elif ext in ('.xlsx', '.xls'):
            return f'import pandas as pd\n{var_name} = pd.read_excel("{safe_path}")\n{var_name}'
        
        return None
