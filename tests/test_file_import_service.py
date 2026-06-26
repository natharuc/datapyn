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
        assert FileImportService.classify_file("query.sql") == "code"

    def test_classify_python(self):
        assert FileImportService.classify_file("script.py") == "code"

    def test_classify_csv(self):
        assert FileImportService.classify_file("data.csv") == "data"

    def test_classify_json(self):
        assert FileImportService.classify_file("data.json") == "data"

    def test_classify_xlsx(self):
        assert FileImportService.classify_file("data.xlsx") == "data"

    def test_classify_xls(self):
        assert FileImportService.classify_file("data.xls") == "data"

    def test_classify_dpw(self):
        assert FileImportService.classify_file("workspace.dpw") == "workspace"

    def test_classify_unsupported(self):
        assert FileImportService.classify_file("readme.txt") is None
        assert FileImportService.classify_file("image.png") is None

    def test_classify_case_insensitive(self):
        assert FileImportService.classify_file("QUERY.SQL") == "code"
        assert FileImportService.classify_file("Data.CSV") == "data"
        assert FileImportService.classify_file("Work.DPW") == "workspace"

    def test_classify_with_path(self):
        assert FileImportService.classify_file("C:/path/to/file.sql") == "code"
        assert FileImportService.classify_file("/home/user/data.csv") == "data"


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
        assert FileImportService.detect_language("script.py") == "python"

    def test_detect_sql(self):
        assert FileImportService.detect_language("query.sql") == "sql"

    def test_detect_default_sql(self):
        assert FileImportService.detect_language("file.unknown") == "sql"


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
        with tempfile.NamedTemporaryFile(mode="w", suffix=".sql", delete=False, encoding="utf-8") as f:
            f.write("SELECT * FROM tabela")
            f.flush()

            content = FileImportService.read_file_content(f.name)
            assert content == "SELECT * FROM tabela"

        os.unlink(f.name)

    def test_read_file_not_found(self):
        with pytest.raises(FileNotFoundError):
            FileImportService.read_file_content("nonexistent.sql")


class TestNormalizeVarName:
    """Testes de normalizacao de nomes de variaveis"""

    def test_simple_name(self):
        name = FileImportService._normalize_var_name("sales.csv")
        assert name == "sales"

    def test_uppercase_to_lowercase(self):
        name = FileImportService._normalize_var_name("PRODUTOS.csv")
        assert name == "produtos"

    def test_spaces_to_underscores(self):
        name = FileImportService._normalize_var_name("lista de clientes do mes.csv")
        assert name == "lista_de_clientes_do_mes"

    def test_hyphens_to_underscores(self):
        name = FileImportService._normalize_var_name("my-data-file.xlsx")
        assert name == "my_data_file"

    def test_special_chars_replaced(self):
        name = FileImportService._normalize_var_name("data (2).csv")
        assert name == "data_2"

    def test_numeric_prefix_gets_df(self):
        name = FileImportService._normalize_var_name("123data.csv")
        assert name == "df_123data"

    def test_multiple_underscores_collapsed(self):
        name = FileImportService._normalize_var_name("a---b___c.csv")
        assert name == "a_b_c"

    def test_leading_trailing_underscores_stripped(self):
        name = FileImportService._normalize_var_name("__test__.csv")
        assert name == "test"

    def test_empty_name_fallback(self):
        name = FileImportService._normalize_var_name("---.csv")
        assert name == "df"

    def test_full_path_uses_basename(self):
        name = FileImportService._normalize_var_name("C:/Users/joao/Documents/Relatorio Final.xlsx")
        assert name == "relatorio_final"

    def test_mixed_case_and_spaces(self):
        name = FileImportService._normalize_var_name("Meu Relatorio Mensal.json")
        assert name == "meu_relatorio_mensal"


class TestGenerateImportCode:
    """Testes de geracao de codigo de importacao"""

    def test_generate_csv_import(self):
        code = FileImportService.generate_import_code("C:/data/sales.csv")
        assert "pd.read_csv" in code
        assert "sales" in code
        assert "import pandas" in code
        assert 'sep=";"' in code

    def test_generate_json_import(self):
        code = FileImportService.generate_import_code("C:/data/config.json")
        assert "pd.read_json" in code
        assert "config" in code

    def test_generate_xlsx_import(self):
        code = FileImportService.generate_import_code("C:/data/report.xlsx")
        assert "fastexcel" in code
        assert ".load_sheet(0)" in code
        assert "report" in code

    def test_generate_xls_import(self):
        code = FileImportService.generate_import_code("C:/data/legacy.xls")
        assert "fastexcel" in code
        assert ".load_sheet(0)" in code

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
        assert "my_data_2" in code

    def test_generate_csv_var_name_lowercase(self):
        code = FileImportService.generate_import_code("C:/data/PRODUTOS.csv")
        assert "produtos" in code
        assert 'sep=";"' in code

    def test_generate_csv_spaces_normalized(self):
        code = FileImportService.generate_import_code("lista de clientes do mes.csv")
        assert "lista_de_clientes_do_mes" in code

    def test_generate_json_var_name_normalized(self):
        code = FileImportService.generate_import_code("C:/data/Meu Relatorio.json")
        assert "meu_relatorio" in code
        assert "pd.read_json" in code

    def test_generate_xlsx_var_name_normalized(self):
        code = FileImportService.generate_import_code("C:/data/DADOS FINANCEIROS (2024).xlsx")
        assert "dados_financeiros_2024" in code
        assert "fastexcel" in code


class TestCollectStartupFilePaths:
    def test_collects_supported_extensions(self, tmp_path):
        from src.services.file_import_service import collect_startup_file_paths

        dpw = tmp_path / "workspace.dpw"
        dpw.write_text("{}", encoding="utf-8")
        sql = tmp_path / "query.sql"
        sql.write_text("select 1", encoding="utf-8")

        paths = collect_startup_file_paths(
            [str(dpw), str(sql), "--flag", "readme.txt", ""]
        )
        assert str(dpw.resolve()) in paths
        assert str(sql.resolve()) in paths
        assert len(paths) == 2

    def test_ignores_flags_and_unsupported(self):
        from src.services.file_import_service import collect_startup_file_paths

        assert collect_startup_file_paths(["--workspace", "/tmp/ws", "-h"]) == []
