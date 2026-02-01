"""
Executor de linguagem mista SQL + Python
Permite syntax tipo: clientes = {{SELECT * FROM clientes}}
"""
import re
from typing import Any, Dict
import pandas as pd


class MixedLanguageExecutor:
    """Executor que permite misturar SQL e Python"""
    
    def __init__(self, database_connector, results_manager):
        self.db_connector = database_connector
        self.results_manager = results_manager
    
    def parse_and_execute(self, code: str, namespace: dict) -> Dict[str, Any]:
        """
        Parseia e executa código com sintaxe {{ SQL }}
        
        Syntax suportada:
        - var = {{SELECT * FROM table}}
        - resultado = {{SELECT COUNT(*) FROM clientes}}
        
        Args:
            code: Código com sintaxe {{...}}
            namespace: Namespace Python existente
            
        Returns:
            Dict com output, queries executadas e resultado
        """
        import sys
        from io import StringIO
        
        # Captura output
        old_stdout = sys.stdout
        sys.stdout = captured = StringIO()
        
        result = None
        queries_executed = 0
        
        try:
            # Extrair e substituir padrões {{ SQL }}
            processed_code, extractions = self._process_double_brace_syntax(code)
            
            # Executar queries SQL e criar variáveis
            for var_name, sql in extractions:
                df = self._execute_query(sql)
                namespace[var_name] = df
                queries_executed += 1
                # Salva a variável no results_manager para persistência
                self.results_manager.set_variable(var_name, df)
            
            # Executar código Python processado
            if processed_code.strip():
                exec(processed_code, namespace)
                # Pegar último resultado se houver
                if '_' in namespace:
                    result = namespace['_']
            
            # Atualiza o namespace do results_manager com as novas variáveis
            self.results_manager.update_namespace(namespace)
            
        finally:
            sys.stdout = old_stdout
        
        return {
            'output': captured.getvalue(),
            'queries_executed': queries_executed,
            'result': result
        }
    
    def _process_double_brace_syntax(self, code: str) -> tuple:
        """
        Processa sintaxe {{ SQL }} convertendo para variáveis Python
        
        Returns:
            (código_processado, [(var_name, sql), ...])
        """
        extractions = []
        
        # Pattern: var_name = {{ SQL }}
        pattern = r'(\w+)\s*=\s*\{\{\s*(.+?)\s*\}\}'
        
        def replace_match(match):
            var_name = match.group(1)
            sql = match.group(2).strip()
            extractions.append((var_name, sql))
            # Substituir por comentário para manter as linhas
            return f'# {var_name} = {{{{ {sql[:30]}... }}}}'
        
        processed = re.sub(pattern, replace_match, code, flags=re.DOTALL)
        
        return processed, extractions
    
    def _execute_query(self, sql: str) -> pd.DataFrame:
        """
        Função query() disponível no código
        Executa SQL e retorna DataFrame
        """
        if not self.db_connector or not self.db_connector.is_connected():
            raise ConnectionError("Não há conexão ativa com o banco de dados")
        
        # Executar query
        df = self.db_connector.execute_query(sql)
        
        return df
    
    def _execute_statement(self, sql: str) -> int:
        """
        Função execute() disponível no código
        Executa statement SQL (INSERT, UPDATE, DELETE)
        Retorna número de linhas afetadas
        """
        if not self.db_connector or not self.db_connector.is_connected():
            raise ConnectionError("Não há conexão ativa com o banco de dados")
        
        # Executar statement
        rows = self.db_connector.execute_statement(sql)
        
        return rows
    
    def extract_queries(self, code: str) -> list:
        """
        Extrai todas as queries do código para preview
        
        Returns:
            Lista de tuplas (variável, sql)
        """
        queries = []
        
        # Pattern para capturar: var = {{ SQL }}
        pattern = r'(\w+)\s*=\s*\{\{\s*(.+?)\s*\}\}'
        
        for match in re.finditer(pattern, code, re.MULTILINE | re.DOTALL):
            var_name = match.group(1)
            sql = match.group(2).strip()
            queries.append((var_name, sql))
        
        return queries
    
    def validate_syntax(self, code: str) -> tuple:
        """
        Valida syntax do código misto
        
        Returns:
            (is_valid: bool, error_message: str)
        """
        # Verificar se tem queries com sintaxe {{ }}
        queries = self.extract_queries(code)
        
        if not queries:
            return (False, "Nenhuma query encontrada com sintaxe {{ SQL }}")
        
        # Processar código
        processed_code, _ = self._process_double_brace_syntax(code)
        
        # Tentar compilar código Python resultante
        try:
            compile(processed_code, '<string>', 'exec')
        except SyntaxError as e:
            return (False, f"Erro de sintaxe Python: {e}")
        
        return (True, "")


def create_query_helper_text() -> str:
    """Retorna texto de ajuda para a linguagem mista"""
    return """
╔══════════════════════════════════════════════════════════════╗
║  SINTAXE CROSS SQL + PYTHON - GUIA RÁPIDO                    ║
╚══════════════════════════════════════════════════════════════╝

SINTAXE: variável = {{ SQL }}
───────────────────────────────────────────────────────────────
  clientes = {{ SELECT * FROM clientes }}
  vendas = {{ SELECT * FROM vendas WHERE ano = 2025 }}
  total = {{ SELECT COUNT(*) as qtd FROM clientes }}
  
  # Usar DataFrames imediatamente
  print(f"Total de clientes: {len(clientes)}")
  print(f"Total vendas: {vendas['valor'].sum()}")

MÚLTIPLAS QUERIES:
───────────────────────────────────────────────────────────────
  # Buscar dados de múltiplas tabelas
  clientes = {{ SELECT * FROM clientes }}
  vendas = {{ SELECT * FROM vendas }}
  produtos = {{ SELECT * FROM produtos }}
  
  # Manipular com Python/Pandas
  total_clientes = len(clientes)
  total_vendas = vendas['valor'].sum()
  
  print(f"Clientes: {total_clientes}")
  print(f"Vendas: R$ {total_vendas:,.2f}")

EXEMPLO COMPLETO:
───────────────────────────────────────────────────────────────
  # Buscar dados
  vendas_2025 = {{ SELECT * FROM vendas WHERE YEAR(data) = 2025 }}
  
  # Processar
  vendas_agrupadas = vendas_2025.groupby('produto')['valor'].sum()
  top_5 = vendas_agrupadas.nlargest(5)
  
  # Exibir
  print("Top 5 produtos:")
  print(top_5)

ATALHO: Ctrl+Shift+F5
───────────────────────────────────────────────────────────────
"""
