"""
Testes do MixedLanguageExecutor
"""
import pytest
import pandas as pd


class TestMixedExecutorSyntaxParsing:
    """Testes de parsing da sintaxe cross-syntax"""
    
    def test_extract_double_brace_simple(self, mixed_executor):
        """Deve extrair sintaxe {{ SQL }} simples"""
        code = 'clientes = {{SELECT * FROM cliente}}'
        
        queries = mixed_executor.extract_queries(code)
        
        assert len(queries) == 1
        assert queries[0][0] == 'clientes'
        assert 'SELECT * FROM cliente' in queries[0][1]
    
    def test_extract_double_brace_with_spaces(self, mixed_executor):
        """Deve extrair com espaços"""
        code = 'df = {{ SELECT id, name FROM users }}'
        
        queries = mixed_executor.extract_queries(code)
        
        assert len(queries) == 1
        assert queries[0][0] == 'df'
        assert 'SELECT id, name FROM users' in queries[0][1]
    
    def test_extract_multiple_queries(self, mixed_executor):
        """Deve extrair múltiplas queries"""
        code = '''
clientes = {{SELECT * FROM cliente}}
produtos = {{SELECT * FROM produto}}
'''
        queries = mixed_executor.extract_queries(code)
        
        assert len(queries) == 2
        assert queries[0][0] == 'clientes'
        assert queries[1][0] == 'produtos'
    
    def test_extract_multiline_sql(self, mixed_executor):
        """Deve extrair SQL multiline"""
        code = '''df = {{
    SELECT 
        id,
        name,
        email
    FROM users
    WHERE status = 'active'
}}'''
        queries = mixed_executor.extract_queries(code)
        
        assert len(queries) == 1
        assert 'SELECT' in queries[0][1]
        assert 'WHERE' in queries[0][1]
    
    def test_no_queries_returns_empty(self, mixed_executor):
        """Código sem queries deve retornar lista vazia"""
        code = 'x = 1 + 1'
        
        queries = mixed_executor.extract_queries(code)
        
        assert queries == []
    
    def test_validate_syntax_valid(self, mixed_executor):
        """Sintaxe válida deve passar"""
        code = 'df = {{SELECT 1}}'
        
        result = mixed_executor.validate_syntax(code)
        
        assert result[0] is True  # (is_valid, error_message)
    
    def test_validate_syntax_no_query(self, mixed_executor):
        """Código sem query deve ser inválido"""
        code = 'x = 1 + 1'
        
        result = mixed_executor.validate_syntax(code)
        
        assert result[0] is False
        assert 'query' in result[1].lower()


class TestMixedExecutorExecution:
    """Testes de execução cross-syntax"""
    
    def test_execute_creates_dataframe_in_namespace(self, mixed_executor, mock_db_connector, sample_dataframe):
        """Execução deve criar DataFrame na variável no namespace"""
        mock_db_connector.execute_query.return_value = sample_dataframe
        mock_db_connector.is_connected.return_value = True
        
        namespace = {}
        code = 'clientes = {{SELECT * FROM cliente}}'
        result = mixed_executor.parse_and_execute(code, namespace)
        
        assert 'clientes' in namespace
        assert isinstance(namespace['clientes'], pd.DataFrame)
    
    def test_execute_returns_queries_executed_count(self, mixed_executor, mock_db_connector, sample_dataframe):
        """Deve retornar contagem de queries executadas"""
        mock_db_connector.execute_query.return_value = sample_dataframe
        mock_db_connector.is_connected.return_value = True
        
        namespace = {}
        code = '''
c1 = {{SELECT 1}}
c2 = {{SELECT 2}}
'''
        result = mixed_executor.parse_and_execute(code, namespace)
        
        assert result['queries_executed'] == 2
    
    def test_execute_with_python_code(self, mixed_executor, mock_db_connector, sample_dataframe):
        """Deve executar código Python junto com SQL"""
        mock_db_connector.execute_query.return_value = sample_dataframe
        mock_db_connector.is_connected.return_value = True
        
        namespace = {}
        code = '''
x = 10
clientes = {{SELECT * FROM cliente}}
y = x + 5
'''
        result = mixed_executor.parse_and_execute(code, namespace)
        
        assert namespace.get('x') == 10
        assert namespace.get('y') == 15


class TestMixedExecutorEdgeCases:
    """Testes de casos de borda"""
    
    def test_special_characters_in_sql(self, mixed_executor):
        """Caracteres especiais no SQL"""
        code = "df = {{SELECT * FROM users WHERE name = 'O''Brien'}}"
        
        queries = mixed_executor.extract_queries(code)
        
        assert len(queries) == 1
    
    def test_process_double_brace_returns_tuple(self, mixed_executor):
        """_process_double_brace_syntax deve retornar tupla"""
        code = 'df = {{SELECT 1}}'
        
        result = mixed_executor._process_double_brace_syntax(code)
        
        assert isinstance(result, tuple)
        assert len(result) == 2
    
    def test_process_extracts_variable_and_sql(self, mixed_executor):
        """Deve extrair variável e SQL corretamente"""
        code = 'minha_var = {{ SELECT COUNT(*) FROM tabela }}'
        
        processed, extractions = mixed_executor._process_double_brace_syntax(code)
        
        assert len(extractions) == 1
        assert extractions[0][0] == 'minha_var'
        assert 'SELECT COUNT(*)' in extractions[0][1]


class TestNamespacePersistence:
    """Testes de persistência do namespace entre execuções"""
    
    def test_variable_persists_after_cross_syntax(self, mixed_executor, mock_db_connector, results_manager):
        """Variável criada via cross-syntax deve persistir no namespace"""
        # Configura mock para retornar um DataFrame
        mock_df = pd.DataFrame({'id': [1, 2, 3], 'nome': ['A', 'B', 'C']})
        mock_db_connector.execute_query.return_value = mock_df
        
        # Executa cross-syntax
        code = 'cliente = {{SELECT * FROM cliente}}'
        namespace = results_manager.get_namespace()
        mixed_executor.parse_and_execute(code, namespace)
        
        # Verifica que a variável está no results_manager
        assert results_manager.get_variable('cliente') is not None
        assert isinstance(results_manager.get_variable('cliente'), pd.DataFrame)
    
    def test_variable_available_in_new_namespace(self, mixed_executor, mock_db_connector, results_manager):
        """Variável criada via cross-syntax deve estar disponível em novo namespace"""
        # Configura mock para retornar um DataFrame
        mock_df = pd.DataFrame({'id': [1, 2, 3], 'nome': ['A', 'B', 'C']})
        mock_db_connector.execute_query.return_value = mock_df
        
        # Executa cross-syntax
        code = 'cliente = {{SELECT * FROM cliente}}'
        namespace1 = results_manager.get_namespace()
        mixed_executor.parse_and_execute(code, namespace1)
        
        # Obtém um novo namespace (simula nova execução Python)
        namespace2 = results_manager.get_namespace()
        
        # Verifica que a variável está disponível no novo namespace
        assert 'cliente' in namespace2
        assert isinstance(namespace2['cliente'], pd.DataFrame)
    
    def test_set_variable_in_results_manager(self, results_manager):
        """set_variable deve adicionar variável ao namespace persistente"""
        df = pd.DataFrame({'x': [1, 2, 3]})
        
        results_manager.set_variable('meu_df', df)
        
        # Verifica via get_variable
        assert results_manager.get_variable('meu_df') is not None
        
        # Verifica que está no namespace
        namespace = results_manager.get_namespace()
        assert 'meu_df' in namespace
    
    def test_update_namespace_persists_variables(self, results_manager):
        """update_namespace deve persistir variáveis no namespace"""
        namespace = results_manager.get_namespace()
        namespace['nova_var'] = 'valor_teste'
        namespace['numero'] = 42
        
        results_manager.update_namespace(namespace)
        
        # Obtém novo namespace e verifica
        new_namespace = results_manager.get_namespace()
        assert new_namespace['nova_var'] == 'valor_teste'
        assert new_namespace['numero'] == 42
    
    def test_clear_user_namespace(self, results_manager):
        """clear_user_namespace deve limpar apenas variáveis do usuário"""
        # Adiciona variáveis
        results_manager.set_variable('var1', 'valor1')
        results_manager.set_variable('var2', 'valor2')
        
        # Limpa namespace do usuário
        results_manager.clear_user_namespace()
        
        # Verifica que foram limpas
        assert results_manager.get_variable('var1') is None
        assert results_manager.get_variable('var2') is None
        
        # Mas o namespace ainda deve ter pd e np após get_namespace
        namespace = results_manager.get_namespace()
        assert 'pd' in namespace
        assert 'np' in namespace
