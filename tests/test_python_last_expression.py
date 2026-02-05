"""
Testes para validar execução Python com captura da última expressão
"""

import pytest
import pandas as pd
from unittest.mock import MagicMock

from source.src.ui.main_window import PythonWorker
from source.src.workers import PythonExecutionWorker


class TestPythonLastExpressionCapture:
    """Testes para captura da última expressão em blocos Python"""

    def test_single_expression_captured(self):
        """Testa se expressão simples é capturada"""
        namespace = {}
        worker = PythonWorker("2 + 3", namespace, True)
        
        # Mock do signal
        result_captured = []
        worker.finished.connect(lambda result, output, error: result_captured.append((result, output, error)))
        
        # Executar
        worker.run()
        
        # Verificar resultado
        assert len(result_captured) == 1
        result, output, error = result_captured[0]
        assert result == 5
        assert error == ''

    def test_multiple_expressions_last_result_captured(self):
        """Testa que múltiplas expressões retornam o ÚLTIMO resultado válido"""
        code = """
df = pd.DataFrame({'CEP': ['2840-000', '3000-000', '4000-000']})
df[df['CEP']=='2840-000']
df[df['CEP']=='2840-']
        """.strip()
        
        namespace = {'pd': pd}
        worker = PythonWorker(code, namespace, False)
        
        # Mock do signal
        result_captured = []
        worker.finished.connect(lambda result, output, error: result_captured.append((result, output, error)))
        
        # Executar
        worker.run()
        
        # Verificar resultado
        assert len(result_captured) == 1
        result, output, error = result_captured[0]
        
        # O resultado deve ser o DataFrame vazio da última expressão
        assert isinstance(result, pd.DataFrame)
        assert len(result) == 0  # DataFrame vazio pois '2840-' não existe
        assert error == ''

    def test_user_debug_case(self):
        """Testa o caso específico do usuário para debugging"""
        # Caso que NÃO funciona
        code = """df
df2=df[df['CEP']=='2840-000']
df2"""
        
        namespace = {'df': pd.DataFrame({'CEP': ['2840-000', '3000-000', '4000-000']})}
        worker = PythonWorker(code, namespace, False)
        
        # Mock do signal
        result_captured = []
        worker.finished.connect(lambda result, output, error: result_captured.append((result, output, error)))
        
        # Executar
        worker.run()
        
        # Verificar resultado
        assert len(result_captured) == 1
        result, output, error = result_captured[0]
        
        print(f"Result: {result}")
        print(f"Output: '{output}'")
        print(f"Error: '{error}'")
        
        # O resultado deve ser o DataFrame filtrado da última linha
        assert isinstance(result, pd.DataFrame)
        assert len(result) == 1  # Só uma linha com CEP '2840-000'
        assert result.iloc[0]['CEP'] == '2840-000'
        assert error == ''

    def test_user_case_multiline_no_selection(self):
        """Testa o caso do usuário: múltiplas linhas sem seleção (execução completa)"""
        code = """df
df[df["CEP"] == "2840-000"]"""
        
        namespace = {'df': pd.DataFrame({'CEP': ['2840-000', '3000-000', '4000-000']})}
        # Simular execução completa (is_expression=False)
        worker = PythonWorker(code, namespace, False)
        
        # Mock do signal
        result_captured = []
        worker.finished.connect(lambda result, output, error: result_captured.append((result, output, error)))
        
        # Executar
        worker.run()
        
        # Verificar resultado
        assert len(result_captured) == 1
        result, output, error = result_captured[0]
        
        # O resultado deve ser o DataFrame filtrado da última linha
        assert isinstance(result, pd.DataFrame)
        assert len(result) == 1  # Só uma linha com CEP '2840-000'
        assert result.iloc[0]['CEP'] == '2840-000'
        assert error == ''

    def test_user_case_df_assignment_and_return(self):
        """Testa o caso específico do usuário: df, assignment, df2"""
        code = """
df = pd.DataFrame({'CEP': ['2840-000', '3000-000', '4000-000']})
df2 = df[df["CEP"] == '2840-000']  
df2
        """.strip()
        
        namespace = {'pd': pd}
        worker = PythonWorker(code, namespace, False)
        
        # Mock do signal
        result_captured = []
        worker.finished.connect(lambda result, output, error: result_captured.append((result, output, error)))
        
        # Executar
        worker.run()
        
        # Verificar resultado
        assert len(result_captured) == 1
        result, output, error = result_captured[0]  
        
        # O resultado deve ser o DataFrame filtrado
        assert isinstance(result, pd.DataFrame)
        assert len(result) == 1  # Só uma linha com CEP '2840-000'
        assert result.iloc[0]['CEP'] == '2840-000'
        assert error == ''

    def test_control_structures_with_final_expression(self):
        """Testa que estruturas de controle (if, for, while) funcionam com expressão final"""
        code = """
x = 5
if x > 3:
    y = x * 2
else:
    y = x / 2
y + 1
        """.strip()
        
        namespace = {}
        worker = PythonWorker(code, namespace, False)
        
        # Mock do signal
        result_captured = []
        worker.finished.connect(lambda result, output, error: result_captured.append((result, output, error)))
        
        # Executar
        worker.run()
        
        # Verificar resultado
        assert len(result_captured) == 1
        result, output, error = result_captured[0]
        
        # O resultado deve ser y + 1 = 10 + 1 = 11
        assert result == 11
        assert error == ''

    def test_mixed_statements_and_expressions(self):
        """Testa que statements (assignments, prints) não sobrescrevem o último resultado"""
        code = """
df = pd.DataFrame({'valores': [10, 20, 30]})
resultado = df.sum()
print("Processando...")
x = 42
resultado
        """.strip()
        
        namespace = {'pd': pd}
        worker = PythonWorker(code, namespace, False)
        
        # Mock do signal
        result_captured = []
        worker.finished.connect(lambda result, output, error: result_captured.append((result, output, error)))
        
        # Executar
        worker.run()
        
        # Verificar resultado
        assert len(result_captured) == 1
        result, output, error = result_captured[0]
        
        # O resultado deve ser o Series da soma
        assert isinstance(result, pd.Series)
        assert result['valores'] == 60  # 10+20+30
        assert error == ''

    def test_multiple_lines_with_last_expression(self):
        """Testa captura da última expressão em código multi-linha"""
        code = """
df = pd.DataFrame({'A': [1, 2, 3], 'B': [4, 5, 6]})
filtered_df = df[df['A'] > 1]
filtered_df
        """.strip()
        
        namespace = {'pd': pd}
        worker = PythonWorker(code, namespace, False)
        
        # Mock do signal
        result_captured = []
        worker.finished.connect(lambda result, output, error: result_captured.append((result, output, error)))
        
        # Executar
        worker.run()
        
        # Verificar resultado
        assert len(result_captured) == 1
        result, output, error = result_captured[0]
        
        # Deve ter retornado o DataFrame filtrado
        assert isinstance(result, pd.DataFrame)
        assert len(result) == 2  # Linhas onde A > 1
        assert list(result['A']) == [2, 3]
        assert error == ''

    def test_assignment_then_variable_name(self):
        """Testa o caso específico do usuário: atribuição + nome da variável"""
        code = """df1 = pd.DataFrame({'TCode5': ['3641', '1234', '3641'], 'Value': [10, 20, 30]})
df = df1.copy()
df1 = df[df["TCode5"] == '3641']
df1"""
        
        namespace = {'pd': pd}
        worker = PythonWorker(code, namespace, False)
        
        # Mock do signal
        result_captured = []
        worker.finished.connect(lambda result, output, error: result_captured.append((result, output, error)))
        
        # Executar
        worker.run()
        
        # Verificar resultado
        assert len(result_captured) == 1
        result, output, error = result_captured[0]
        
        # Deve ter retornado o DataFrame df1 filtrado
        assert isinstance(result, pd.DataFrame)
        assert len(result) == 2  # Duas linhas com TCode5 == '3641'
        assert all(result['TCode5'] == '3641')
        assert error == ''

    def test_last_line_is_statement_no_result(self):
        """Testa quando última linha é statement, não expressão"""
        code = """
x = 5
y = 10
print(x + y)
        """.strip()
        
        namespace = {}
        worker = PythonWorker(code, namespace, False) 
        
        # Mock do signal
        result_captured = []
        worker.finished.connect(lambda result, output, error: result_captured.append((result, output, error)))
        
        # Executar
        worker.run()
        
        # Verificar resultado
        assert len(result_captured) == 1
        result, output, error = result_captured[0]
        
        # Não deve ter resultado (print não retorna valor)
        assert result is None
        assert "15" in output  # Output do print
        assert error == ''

    def test_syntax_error_handling(self):
        """Testa tratamento de erro de sintaxe"""
        code = """
x = 5
y = 
invalid syntax here
        """.strip()
        
        namespace = {}
        worker = PythonWorker(code, namespace, False)
        
        # Mock do signal
        result_captured = []
        worker.finished.connect(lambda result, output, error: result_captured.append((result, output, error)))
        
        # Executar
        worker.run()
        
        # Verificar erro
        assert len(result_captured) == 1
        result, output, error = result_captured[0]
        
        assert result is None
        assert error != ''  # Deve ter capturado o erro

    def test_empty_lines_handling(self):
        """Testa handling de linhas vazias"""
        code = """

x = 42

x
        """
        
        namespace = {}
        worker = PythonWorker(code, namespace, False)
        
        # Mock do signal
        result_captured = []
        worker.finished.connect(lambda result, output, error: result_captured.append((result, output, error)))
        
        # Executar
        worker.run()
        
        # Verificar resultado
        assert len(result_captured) == 1
        result, output, error = result_captured[0]
        
        assert result == 42
        assert error == ''

    def test_python_execution_worker_same_behavior(self):
        """Testa que PythonExecutionWorker tem mesmo comportamento"""
        code = """
data = {'A': [1, 2, 3], 'B': [4, 5, 6]}
df = pd.DataFrame(data)
df
        """.strip()
        
        namespace = {'pd': pd}
        worker = PythonExecutionWorker(code, namespace, False)
        
        # Mock do signal
        result_captured = []
        worker.execution_complete.connect(lambda result, stdout, stderr: result_captured.append((result, stdout, stderr)))
        
        # Executar
        worker.run()
        
        # Verificar resultado
        assert len(result_captured) == 1
        result, stdout, stderr = result_captured[0]
        
        # Deve ter retornado o DataFrame
        assert isinstance(result, pd.DataFrame)
        assert len(result) == 3
        assert list(result.columns) == ['A', 'B']
        assert stderr == ''