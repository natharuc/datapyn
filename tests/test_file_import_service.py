"""
Testes para FileImportService

Cobre: classificacao de arquivos, deteccao de linguagem,
geracao de codigo de importacao.
"""
import pytest
import os
import tempfile
from src.services.file_import_service import FileImportService


class TestFileClassification:
    """Testes de classificacao de arquivos"""
    
    def test_classify_sql(self):
        assert FileImportService.classify_file("query.sql") == 'code'
    
    def test_classify_python(self):
        assert FileImportService.classify_file("script.py") == 'code'
    
    def test_classify_csv(self):
        assert FileImportService.classify_file("data.csv") == 'data'
    
    def test_classify_json(self):
        assert FileImportService.classify_file("data.json") == 'data'
    
    def test_classify_xlsx(self):
        assert FileImportService.classify_file("data.xlsx") == 'data'
    
    def test_classify_xls(self):
        assert FileImportService.classify_file("data.xls") == 'data'
    
    def test_classify_dpw(self):
        assert FileImportService.classify_file("workspace.dpw") == 'workspace'
    
    def test_classify_unsupported(self):
        assert FileImportService.classify_file("readme.txt") is None
        assert FileImportService.classify_file("image.png") is None
    
    def test_classify_case_insensitive(self):
        assert FileImportService.classify_file("QUERY.SQL") == 'code'
        assert FileImportService.classify_file("Data.CSV") == 'data'
        assert FileImportService.classify_file("Work.DPW") == 'workspace'
    
    def test_classify_with_path(self):
        assert FileImportService.classify_file("C:/path/to/file.sql") == 'code'
        assert FileImportService.classify_file("/home/user/data.csv") == 'data'


class TestFileListClassification:
    """Testes de classificacao de lista de arquivos"""
    
    def test_classify_mixed_list(self):
        files = [
            "query.sql",
            "data.csv",
            "script.py",
            "workspace.dpw",
            "report.xlsx",
        ]
        code, data, workspace = FileImportService.classify_file_list(files)
        
        assert len(code) == 2
        assert len(data) == 2
        assert len(workspace) == 1
    
    def test_classify_empty_list(self):
        code, data, workspace = FileImportService.classify_file_list([])
        assert code == []
        assert data == []
        assert workspace == []
    
    def test_classify_all_unsupported(self):
        files = ["readme.txt", "image.png", "doc.pdf"]
        code, data, workspace = FileImportService.classify_file_list(files)
        assert code == []
        assert data == []
        assert workspace == []


class TestLanguageDetection:
    """Testes de deteccao de linguagem"""
    
    def test_detect_python(self):
        assert FileImportService.detect_language("script.py") == 'python'
    
    def test_detect_sql(self):
        assert FileImportService.detect_language("query.sql") == 'sql'
    
    def test_detect_default_sql(self):
        assert FileImportService.detect_language("file.unknown") == 'sql'


class TestIsSupported:
    """Testes de verificacao de suporte"""
    
    def test_supported_extensions(self):
        assert FileImportService.is_supported("file.sql") is True
        assert FileImportService.is_supported("file.py") is True
        assert FileImportService.is_supported("file.csv") is True
        assert FileImportService.is_supported("file.json") is True
        assert FileImportService.is_supported("file.xlsx") is True
        assert FileImportService.is_supported("file.xls") is True
        assert FileImportService.is_supported("file.dpw") is True
    
    def test_unsupported_extensions(self):
        assert FileImportService.is_supported("file.txt") is False
        assert FileImportService.is_supported("file.png") is False


class TestReadFileContent:
    """Testes de leitura de arquivo"""
    
    def test_read_utf8_file(self):
        with tempfile.NamedTemporaryFile(mode='w', suffix='.sql', 
                                          delete=False, encoding='utf-8') as f:
            f.write("SELECT * FROM tabela")
            f.flush()
            
            content = FileImportService.read_file_content(f.name)
            assert content == "SELECT * FROM tabela"
        
        os.unlink(f.name)
    
    def test_read_file_not_found(self):
        with pytest.raises(FileNotFoundError):
            FileImportService.read_file_content("nonexistent.sql")


class TestGenerateImportCode:
    """Testes de geracao de codigo de importacao"""
    
    def test_generate_csv_import(self):
        code = FileImportService.generate_import_code("C:/data/sales.csv")
        assert "pd.read_csv" in code
        assert "sales" in code
        assert "import pandas" in code
    
    def test_generate_json_import(self):
        code = FileImportService.generate_import_code("C:/data/config.json")
        assert "pd.read_json" in code
        assert "config" in code
    
    def test_generate_xlsx_import(self):
        code = FileImportService.generate_import_code("C:/data/report.xlsx")
        assert "pd.read_excel" in code
        assert "report" in code
    
    def test_generate_xls_import(self):
        code = FileImportService.generate_import_code("C:/data/legacy.xls")
        assert "pd.read_excel" in code
    
    def test_generate_unsupported_returns_none(self):
        assert FileImportService.generate_import_code("file.txt") is None
    
    def test_generate_handles_windows_paths(self):
        code = FileImportService.generate_import_code("C:\\Users\\data\\file.csv")
        assert "\\\\" not in code or "/" in code  # Deve usar forward slashes
    
    def test_generate_handles_numeric_filename(self):
        code = FileImportService.generate_import_code("123data.csv")
        # Variavel nao pode comecar com numero
        assert code is not None
        # Deve ter prefixo df_
        assert "df_123data" in code
    
    def test_generate_handles_special_chars_in_name(self):
        code = FileImportService.generate_import_code("my-data (2).csv")
        assert code is not None
        # Caracteres especiais devem ser substituidos por _
        assert "my_data" in code
