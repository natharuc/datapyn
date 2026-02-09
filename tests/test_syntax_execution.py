"""
Testes de Execução de Sintaxe - SQL, Python e Cross-Syntax
Usa SQLite em memória para testes reais de banco de dados
"""

import pytest
import pandas as pd
import sqlite3
from io import StringIO
import sys


# ==================== FIXTURES ====================


@pytest.fixture
def sqlite_connection():
    """Cria conexão SQLite em memória com dados de teste"""
    conn = sqlite3.connect(":memory:")
    cursor = conn.cursor()

    # Criar tabela cliente
    cursor.execute("""
        CREATE TABLE cliente (
            id INTEGER PRIMARY KEY,
            nome TEXT NOT NULL,
            email TEXT,
            cidade TEXT,
            valor REAL
        )
    """)

    # Inserir dados de teste
    clientes = [
        (1, "João Silva", "joao@email.com", "São Paulo", 1500.50),
        (2, "Maria Santos", "maria@email.com", "Rio de Janeiro", 2300.00),
        (3, "Pedro Costa", "pedro@email.com", "Belo Horizonte", 1800.75),
        (4, "Ana Oliveira", "ana@email.com", "São Paulo", 3200.00),
        (5, "Carlos Lima", "carlos@email.com", "Curitiba", 2750.25),
    ]
    cursor.executemany("INSERT INTO cliente VALUES (?, ?, ?, ?, ?)", clientes)

    # Criar tabela produto
    cursor.execute("""
        CREATE TABLE produto (
            id INTEGER PRIMARY KEY,
            nome TEXT NOT NULL,
            preco REAL,
            estoque INTEGER
        )
    """)

    produtos = [
        (1, "Notebook", 3500.00, 10),
        (2, "Mouse", 150.00, 50),
        (3, "Teclado", 250.00, 30),
    ]
    cursor.executemany("INSERT INTO produto VALUES (?, ?, ?, ?)", produtos)

    conn.commit()
    yield conn
    conn.close()


@pytest.fixture
def sql_executor(sqlite_connection):
    """Executor SQL que usa a conexão SQLite"""

    class SQLExecutor:
        def __init__(self, conn):
            self.conn = conn

        def execute_query(self, sql: str) -> pd.DataFrame:
            """Executa query e retorna DataFrame"""
            return pd.read_sql_query(sql, self.conn)

        def is_connected(self) -> bool:
            return self.conn is not None

    return SQLExecutor(sqlite_connection)


@pytest.fixture
def python_executor():
    """Executor Python com namespace isolado"""

    class PythonExecutor:
        def __init__(self):
            self.namespace = {
                "pd": pd,
                "__builtins__": __builtins__,
            }

        def execute(self, code: str) -> dict:
            """
            Executa código Python e retorna resultado

            Returns:
                dict com 'output' (stdout), 'result' (último valor), 'success', 'error'
            """
            old_stdout = sys.stdout
            sys.stdout = captured = StringIO()

            result = None
            error = None
            success = True

            try:
                # Tentar como expressão primeiro
                try:
                    result = eval(code, self.namespace)
                except SyntaxError:
                    # Se falhar, executar como statement
                    exec(code, self.namespace)

                    # Tentar pegar valor da última linha se for expressão
                    lines = code.strip().split("\n")
                    last_line = lines[-1].strip()
                    if last_line and not any(
                        last_line.startswith(kw)
                        for kw in [
                            "if ",
                            "for ",
                            "while ",
                            "def ",
                            "class ",
                            "import ",
                            "from ",
                            "try:",
                            "except",
                            "with ",
                            "return ",
                            "raise ",
                            "pass",
                            "#",
                        ]
                    ):
                        try:
                            # Verificar se não é atribuição
                            if "=" not in last_line or last_line.count("=") == last_line.count("=="):
                                result = eval(last_line, self.namespace)
                        except:
                            pass

            except Exception as e:
                success = False
                error = str(e)
            finally:
                sys.stdout = old_stdout

            return {
                "output": captured.getvalue(),
                "result": result,
                "success": success,
                "error": error,
                "namespace": self.namespace,
            }

        def get_variable(self, name: str):
            return self.namespace.get(name)

        def set_variable(self, name: str, value):
            self.namespace[name] = value

    return PythonExecutor()


@pytest.fixture
def cross_executor(sql_executor, python_executor):
    """Executor Cross-Syntax que combina SQL e Python"""
    import re

    class CrossSyntaxExecutor:
        def __init__(self, sql_exec, py_exec):
            self.sql_executor = sql_exec
            self.python_executor = py_exec

        def execute(self, code: str) -> dict:
            """
            Executa código com sintaxe {{ SQL }}

            Syntax: variavel = {{SELECT * FROM tabela}}
            """
            # Pattern: var = {{ SQL }}
            pattern = r"(\w+)\s*=\s*\{\{\s*(.+?)\s*\}\}"

            processed_code = code
            queries_executed = 0
            dataframes_created = []

            # Encontrar e processar todas as queries
            for match in re.finditer(pattern, code, re.DOTALL):
                var_name = match.group(1)
                sql = match.group(2).strip()

                # Executar query SQL
                df = self.sql_executor.execute_query(sql)

                # Adicionar ao namespace Python
                self.python_executor.set_variable(var_name, df)

                queries_executed += 1
                dataframes_created.append(var_name)

                # Remover a linha com {{ }} do código
                processed_code = processed_code.replace(match.group(0), f"# {var_name} loaded from SQL")

            # Executar código Python restante
            py_result = self.python_executor.execute(processed_code)

            return {
                "success": py_result["success"],
                "output": py_result["output"],
                "result": py_result["result"],
                "error": py_result["error"],
                "queries_executed": queries_executed,
                "dataframes_created": dataframes_created,
                "namespace": py_result["namespace"],
            }

        def get_variable(self, name: str):
            return self.python_executor.get_variable(name)

    return CrossSyntaxExecutor(sql_executor, python_executor)


# ==================== TESTES DE SQL ====================


class TestSQLExecution:
    """Testes de execução SQL pura"""

    def test_select_all_from_cliente(self, sql_executor):
        """SELECT * FROM cliente deve retornar todas as linhas"""
        df = sql_executor.execute_query("SELECT * FROM cliente")

        assert isinstance(df, pd.DataFrame)
        assert len(df) == 5
        assert "id" in df.columns
        assert "nome" in df.columns
        assert "email" in df.columns

    def test_select_with_where(self, sql_executor):
        """SELECT com WHERE deve filtrar corretamente"""
        df = sql_executor.execute_query("SELECT * FROM cliente WHERE cidade = 'São Paulo'")

        assert len(df) == 2
        assert all(df["cidade"] == "São Paulo")

    def test_select_specific_columns(self, sql_executor):
        """SELECT de colunas específicas"""
        df = sql_executor.execute_query("SELECT nome, email FROM cliente")

        assert len(df.columns) == 2
        assert "nome" in df.columns
        assert "email" in df.columns
        assert "id" not in df.columns

    def test_select_with_order_by(self, sql_executor):
        """SELECT com ORDER BY"""
        df = sql_executor.execute_query("SELECT * FROM cliente ORDER BY valor DESC")

        assert df.iloc[0]["nome"] == "Ana Oliveira"  # Maior valor
        assert df.iloc[0]["valor"] == 3200.00

    def test_select_with_limit(self, sql_executor):
        """SELECT com LIMIT"""
        df = sql_executor.execute_query("SELECT * FROM cliente LIMIT 3")

        assert len(df) == 3

    def test_select_count(self, sql_executor):
        """SELECT COUNT(*)"""
        df = sql_executor.execute_query("SELECT COUNT(*) as total FROM cliente")

        assert df.iloc[0]["total"] == 5

    def test_select_sum(self, sql_executor):
        """SELECT SUM()"""
        df = sql_executor.execute_query("SELECT SUM(valor) as total FROM cliente")

        # 1500.50 + 2300.00 + 1800.75 + 3200.00 + 2750.25 = 11551.50
        assert df.iloc[0]["total"] == 11551.50

    def test_select_from_produto(self, sql_executor):
        """SELECT de outra tabela"""
        df = sql_executor.execute_query("SELECT * FROM produto")

        assert len(df) == 3
        assert "preco" in df.columns
        assert "estoque" in df.columns

    def test_select_join(self, sql_executor, sqlite_connection):
        """SELECT com JOIN"""
        # Criar tabela de pedidos para teste de JOIN
        cursor = sqlite_connection.cursor()
        cursor.execute("""
            CREATE TABLE pedido (
                id INTEGER PRIMARY KEY,
                cliente_id INTEGER,
                produto_id INTEGER,
                quantidade INTEGER
            )
        """)
        cursor.execute("INSERT INTO pedido VALUES (1, 1, 1, 2)")
        sqlite_connection.commit()

        df = sql_executor.execute_query("""
            SELECT c.nome, p.nome as produto, pe.quantidade
            FROM pedido pe
            JOIN cliente c ON c.id = pe.cliente_id
            JOIN produto p ON p.id = pe.produto_id
        """)

        assert len(df) == 1
        assert df.iloc[0]["nome"] == "João Silva"
        assert df.iloc[0]["produto"] == "Notebook"


# ==================== TESTES DE PYTHON ====================


class TestPythonExecution:
    """Testes de execução Python pura"""

    def test_simple_arithmetic(self, python_executor):
        """Aritmética simples deve retornar resultado"""
        result = python_executor.execute("1 + 1")

        assert result["success"] is True
        assert result["result"] == 2

    def test_variable_assignment_and_expression(self, python_executor):
        """Atribuição de variáveis e expressão final"""
        code = """
numero1 = 1
numero2 = 2
soma = numero1 + numero2
soma
"""
        result = python_executor.execute(code)

        assert result["success"] is True
        assert result["result"] == 3
        assert python_executor.get_variable("soma") == 3

    def test_print_output(self, python_executor):
        """print() deve aparecer no output"""
        result = python_executor.execute('print("Hello World")')

        assert result["success"] is True
        assert "Hello World" in result["output"]

    def test_multiple_variables(self, python_executor):
        """Múltiplas variáveis"""
        code = """
a = 10
b = 20
c = 30
total = a + b + c
total
"""
        result = python_executor.execute(code)

        assert result["result"] == 60

    def test_string_operations(self, python_executor):
        """Operações com strings"""
        code = """
nome = "João"
sobrenome = "Silva"
nome_completo = f"{nome} {sobrenome}"
nome_completo
"""
        result = python_executor.execute(code)

        assert result["result"] == "João Silva"

    def test_list_operations(self, python_executor):
        """Operações com listas"""
        code = """
numeros = [1, 2, 3, 4, 5]
soma = sum(numeros)
soma
"""
        result = python_executor.execute(code)

        assert result["result"] == 15

    def test_dictionary_operations(self, python_executor):
        """Operações com dicionários"""
        code = """
pessoa = {"nome": "Maria", "idade": 30}
pessoa["idade"]
"""
        result = python_executor.execute(code)

        assert result["result"] == 30

    def test_loop_and_accumulation(self, python_executor):
        """Loop com acumulação"""
        code = """
total = 0
for i in range(1, 6):
    total += i
total
"""
        result = python_executor.execute(code)

        assert result["result"] == 15

    def test_conditional_logic(self, python_executor):
        """Lógica condicional"""
        code = """
x = 10
if x > 5:
    resultado = "maior"
else:
    resultado = "menor"
resultado
"""
        result = python_executor.execute(code)

        assert result["result"] == "maior"

    def test_function_definition_and_call(self, python_executor):
        """Definição e chamada de função"""
        code = """
def dobro(n):
    return n * 2

dobro(5)
"""
        result = python_executor.execute(code)

        assert result["result"] == 10

    def test_pandas_operations(self, python_executor):
        """Operações com pandas"""
        code = """
df = pd.DataFrame({'a': [1, 2, 3], 'b': [4, 5, 6]})
df['a'].sum()
"""
        result = python_executor.execute(code)

        assert result["result"] == 6

    def test_syntax_error(self, python_executor):
        """Erro de sintaxe deve ser reportado"""
        result = python_executor.execute("x = ")

        assert result["success"] is False
        assert result["error"] is not None

    def test_runtime_error(self, python_executor):
        """Erro de runtime deve ser reportado"""
        result = python_executor.execute("1/0")

        assert result["success"] is False
        assert "division" in result["error"].lower()

    def test_undefined_variable_error(self, python_executor):
        """Variável não definida deve dar erro"""
        result = python_executor.execute("variavel_inexistente")

        assert result["success"] is False
        assert "not defined" in result["error"]

    def test_formatted_string(self, python_executor):
        """F-strings"""
        code = """
valor = 1500.50
mensagem = f"Total: R$ {valor:.2f}"
mensagem
"""
        result = python_executor.execute(code)

        assert result["result"] == "Total: R$ 1500.50"

    def test_list_comprehension(self, python_executor):
        """List comprehension"""
        code = """
quadrados = [x**2 for x in range(5)]
quadrados
"""
        result = python_executor.execute(code)

        assert result["result"] == [0, 1, 4, 9, 16]


# ==================== TESTES DE CROSS-SYNTAX ====================


class TestCrossSyntaxExecution:
    """Testes de execução Cross-Syntax (nossa linguagem)"""

    def test_simple_query_creates_dataframe(self, cross_executor):
        """Query simples deve criar DataFrame"""
        code = "cliente = {{SELECT * FROM cliente}}"

        result = cross_executor.execute(code)

        assert result["success"] is True
        assert result["queries_executed"] == 1
        assert "cliente" in result["dataframes_created"]

        # Verificar DataFrame criado
        df = cross_executor.get_variable("cliente")
        assert isinstance(df, pd.DataFrame)
        assert len(df) == 5

    def test_query_and_use_dataframe(self, cross_executor):
        """Deve poder usar DataFrame após criação"""
        code = """
cliente = {{SELECT * FROM cliente}}
cliente
"""
        result = cross_executor.execute(code)

        assert result["success"] is True
        df = result["result"]
        assert isinstance(df, pd.DataFrame)
        assert len(df) == 5

    def test_query_and_manipulate_dataframe(self, cross_executor):
        """Deve poder manipular DataFrame com pandas"""
        code = """
cliente = {{SELECT * FROM cliente}}
total_clientes = len(cliente)
total_clientes
"""
        result = cross_executor.execute(code)

        assert result["success"] is True
        assert result["result"] == 5

    def test_query_and_filter_dataframe(self, cross_executor):
        """Deve poder filtrar DataFrame"""
        code = """
cliente = {{SELECT * FROM cliente}}
sp = cliente[cliente['cidade'] == 'São Paulo']
len(sp)
"""
        result = cross_executor.execute(code)

        assert result["success"] is True
        assert result["result"] == 2

    def test_query_and_aggregate(self, cross_executor):
        """Deve poder agregar dados do DataFrame"""
        code = """
cliente = {{SELECT * FROM cliente}}
soma_valores = cliente['valor'].sum()
soma_valores
"""
        result = cross_executor.execute(code)

        assert result["success"] is True
        assert result["result"] == 11551.50

    def test_multiple_queries(self, cross_executor):
        """Múltiplas queries em um código"""
        code = """
clientes = {{SELECT * FROM cliente}}
produtos = {{SELECT * FROM produto}}
total = len(clientes) + len(produtos)
total
"""
        result = cross_executor.execute(code)

        assert result["success"] is True
        assert result["queries_executed"] == 2
        assert "clientes" in result["dataframes_created"]
        assert "produtos" in result["dataframes_created"]
        assert result["result"] == 8  # 5 clientes + 3 produtos

    def test_query_with_where_clause(self, cross_executor):
        """Query com WHERE"""
        code = """
sp_clientes = {{SELECT * FROM cliente WHERE cidade = 'São Paulo'}}
sp_clientes
"""
        result = cross_executor.execute(code)

        assert result["success"] is True
        df = cross_executor.get_variable("sp_clientes")
        assert len(df) == 2

    def test_query_with_aggregation(self, cross_executor):
        """Query com agregação SQL"""
        code = """
resumo = {{SELECT cidade, COUNT(*) as qtd, SUM(valor) as total FROM cliente GROUP BY cidade}}
resumo
"""
        result = cross_executor.execute(code)

        assert result["success"] is True
        df = result["result"]
        assert "cidade" in df.columns
        assert "qtd" in df.columns
        assert "total" in df.columns

    def test_merge_dataframes(self, cross_executor):
        """Deve poder fazer merge de DataFrames"""
        # Primeiro precisamos adicionar pedidos
        cross_executor.sql_executor.conn.execute("""
            CREATE TABLE IF NOT EXISTS pedido (
                id INTEGER PRIMARY KEY,
                cliente_id INTEGER,
                valor REAL
            )
        """)
        cross_executor.sql_executor.conn.execute("INSERT OR REPLACE INTO pedido VALUES (1, 1, 500)")
        cross_executor.sql_executor.conn.execute("INSERT OR REPLACE INTO pedido VALUES (2, 1, 300)")
        cross_executor.sql_executor.conn.commit()

        code = """
clientes = {{SELECT * FROM cliente}}
pedidos = {{SELECT * FROM pedido}}
merged = pd.merge(pedidos, clientes, left_on='cliente_id', right_on='id', suffixes=('_pedido', '_cliente'))
len(merged)
"""
        result = cross_executor.execute(code)

        assert result["success"] is True
        assert result["result"] == 2

    def test_print_dataframe_info(self, cross_executor):
        """Deve poder printar informações do DataFrame"""
        code = """
cliente = {{SELECT * FROM cliente}}
print(f"Total de clientes: {len(cliente)}")
print(f"Colunas: {list(cliente.columns)}")
"""
        result = cross_executor.execute(code)

        assert result["success"] is True
        assert "Total de clientes: 5" in result["output"]
        assert "Colunas:" in result["output"]

    def test_dataframe_statistics(self, cross_executor):
        """Deve poder calcular estatísticas"""
        code = """
cliente = {{SELECT * FROM cliente}}
stats = {
    'media': cliente['valor'].mean(),
    'max': cliente['valor'].max(),
    'min': cliente['valor'].min()
}
stats
"""
        result = cross_executor.execute(code)

        assert result["success"] is True
        stats = result["result"]
        assert stats["max"] == 3200.00
        assert stats["min"] == 1500.50

    def test_multiline_sql(self, cross_executor):
        """SQL multiline dentro de {{ }}"""
        code = """
resultado = {{
    SELECT 
        cidade,
        COUNT(*) as quantidade,
        AVG(valor) as media
    FROM cliente
    GROUP BY cidade
    ORDER BY quantidade DESC
}}
resultado
"""
        result = cross_executor.execute(code)

        assert result["success"] is True
        df = result["result"]
        assert "cidade" in df.columns
        assert "quantidade" in df.columns
        assert "media" in df.columns


class TestCrossSyntaxEdgeCases:
    """Testes de casos de borda da Cross-Syntax"""

    def test_empty_result_query(self, cross_executor):
        """Query que retorna 0 linhas"""
        code = """
vazio = {{SELECT * FROM cliente WHERE id = 9999}}
len(vazio)
"""
        result = cross_executor.execute(code)

        assert result["success"] is True
        assert result["result"] == 0

    def test_special_characters_in_sql(self, cross_executor):
        """Caracteres especiais no SQL"""
        code = """
teste = {{SELECT * FROM cliente WHERE nome LIKE '%Silva%'}}
len(teste)
"""
        result = cross_executor.execute(code)

        assert result["success"] is True
        assert result["result"] == 1

    def test_variable_reuse(self, cross_executor):
        """Reutilizar variável com nova query"""
        # Executar em duas etapas para garantir isolamento
        code1 = "dados = {{SELECT * FROM cliente}}"
        cross_executor.execute(code1)
        qtd1 = len(cross_executor.get_variable("dados"))

        code2 = "dados = {{SELECT * FROM produto}}"
        cross_executor.execute(code2)
        qtd2 = len(cross_executor.get_variable("dados"))

        assert qtd1 == 5
        assert qtd2 == 3

    def test_complex_workflow(self, cross_executor):
        """Workflow complexo com múltiplas operações"""
        code = """
# Carregar dados
clientes = {{SELECT * FROM cliente}}
produtos = {{SELECT * FROM produto}}

# Análise
cliente_sp = clientes[clientes['cidade'] == 'São Paulo']
valor_medio_sp = cliente_sp['valor'].mean()

# Relatório
relatorio = {
    'total_clientes': len(clientes),
    'clientes_sp': len(cliente_sp),
    'valor_medio_sp': round(valor_medio_sp, 2),
    'total_produtos': len(produtos)
}
relatorio
"""
        result = cross_executor.execute(code)

        assert result["success"] is True
        r = result["result"]
        assert r["total_clientes"] == 5
        assert r["clientes_sp"] == 2
        assert r["total_produtos"] == 3


# ==================== TESTES DE ISOLAMENTO ====================


class TestExecutionIsolation:
    """Testes para garantir isolamento entre execuções"""

    def test_sql_does_not_affect_python_namespace(self, sql_executor, python_executor):
        """Execução SQL não deve afetar namespace Python"""
        sql_executor.execute_query("SELECT * FROM cliente")

        # Python não deve ter variável 'cliente'
        assert python_executor.get_variable("cliente") is None

    def test_python_namespace_persists(self, python_executor):
        """Namespace Python deve persistir entre execuções"""
        python_executor.execute("x = 42")
        result = python_executor.execute("x + 8")

        assert result["result"] == 50

    def test_cross_syntax_creates_in_namespace(self, cross_executor):
        """Cross-syntax deve criar variáveis no namespace"""
        cross_executor.execute("df = {{SELECT * FROM cliente}}")

        # Variável deve existir
        df = cross_executor.get_variable("df")
        assert df is not None
        assert isinstance(df, pd.DataFrame)
