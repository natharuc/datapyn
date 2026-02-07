"""
Testes do ResultsManager
"""
import pytest
import pandas as pd


class TestResultsManager:
    """Testes do gerenciador de resultados"""
    
    def test_results_start_empty(self, results_manager):
        """Resultados devem começar vazios"""
        assert len(results_manager.results) == 0
    
    def test_add_result_auto_name(self, results_manager, sample_dataframe):
        """Deve adicionar resultado com nome automático"""
        var_name = results_manager.add_result(sample_dataframe, "SELECT * FROM test")
        
        assert var_name == "df1"
        assert var_name in results_manager.results
    
    def test_add_multiple_results(self, results_manager, sample_dataframe):
        """Deve criar nomes sequenciais df1, df2, etc"""
        name1 = results_manager.add_result(sample_dataframe)
        name2 = results_manager.add_result(sample_dataframe)
        name3 = results_manager.add_result(sample_dataframe)
        
        assert name1 == "df1"
        assert name2 == "df2"
        assert name3 == "df3"
    
    def test_get_result(self, results_manager, sample_dataframe):
        """Deve recuperar resultado por nome"""
        results_manager.add_result(sample_dataframe)
        
        df = results_manager.get_result("df1")
        
        assert df is not None
        assert len(df) == 3
    
    def test_get_nonexistent_result(self, results_manager):
        """Resultado inexistente deve retornar None"""
        result = results_manager.get_result('nonexistent')
        
        assert result is None
    
    def test_last_result_updated(self, results_manager, sample_dataframe):
        """last_result deve ser o último DataFrame"""
        results_manager.add_result(sample_dataframe, "query1")
        
        df2 = pd.DataFrame({'other': [1, 2]})
        results_manager.add_result(df2, "query2")
        
        assert len(results_manager.last_result) == 2
    
    def test_get_namespace_includes_pd_np(self, results_manager):
        """Namespace deve incluir pd e np"""
        namespace = results_manager.get_namespace()
        
        assert 'pd' in namespace
        assert 'np' in namespace
    
    def test_get_namespace_includes_results(self, results_manager, sample_dataframe):
        """Namespace deve incluir resultados"""
        results_manager.add_result(sample_dataframe)
        
        namespace = results_manager.get_namespace()
        
        assert 'df1' in namespace
        assert isinstance(namespace['df1'], pd.DataFrame)
    
    def test_clear_result(self, results_manager, sample_dataframe):
        """Deve limpar resultado específico"""
        results_manager.add_result(sample_dataframe)
        
        results_manager.clear_result('df1')
        
        assert results_manager.get_result('df1') is None
    
    def test_clear_all(self, results_manager, sample_dataframe):
        """Deve limpar todos os resultados"""
        results_manager.add_result(sample_dataframe)
        results_manager.add_result(sample_dataframe)
        
        results_manager.clear_all()
        
        assert len(results_manager.results) == 0
        assert results_manager.last_result is None


class TestResultsManagerMetadata:
    """Testes de metadata dos resultados"""
    
    def test_metadata_saved(self, results_manager, sample_dataframe):
        """Metadata deve ser salva"""
        results_manager.add_result(sample_dataframe, "SELECT * FROM test")
        
        assert 'df1' in results_manager.metadata
    
    def test_metadata_contains_query(self, results_manager, sample_dataframe):
        """Metadata deve conter query original"""
        results_manager.add_result(sample_dataframe, "SELECT * FROM test")
        
        assert results_manager.metadata['df1']['query'] == "SELECT * FROM test"
    
    def test_metadata_contains_rows_columns(self, results_manager, sample_dataframe):
        """Metadata deve conter linhas e colunas"""
        results_manager.add_result(sample_dataframe)
        
        meta = results_manager.metadata['df1']
        assert meta['rows'] == 3
        assert meta['columns'] == 2
    
    def test_history_tracking(self, results_manager, sample_dataframe):
        """Histórico deve ser rastreado"""
        results_manager.add_result(sample_dataframe, "query1")
        results_manager.add_result(sample_dataframe, "query2")
        
        assert len(results_manager.history) == 2
