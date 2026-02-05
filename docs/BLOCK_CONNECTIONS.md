# Conexoes por Bloco - Guia de Uso

## Visao Geral

O DataPyn agora permite que cada bloco de codigo utilize uma conexao de banco de dados diferente. Isso possibilita trabalhar com multiplas fontes de dados na mesma aba de forma organizada.

## Recursos Principais

### 1. Selecao de Conexao por Bloco

Cada bloco possui um seletor de conexao na barra de controle, ao lado do seletor de linguagem:

- **Padrao da aba**: Usa a conexao ativa da aba (comportamento anterior)
- **Conexoes especificas**: Permite selecionar qualquer conexao salva no DataPyn

### 2. Novos Blocos Herdam Conexao da Aba

Quando voce cria um novo bloco:
- Por padrao, ele usa a conexao da aba (se houver uma conectada)
- Voce pode alterar a conexao a qualquer momento usando o seletor

### 3. Persistencia

A conexao selecionada em cada bloco e salva quando voce:
- Salva a sessao/workspace
- Fecha e reabre o DataPyn
- Duplica uma aba

## Usando Conexoes em Codigo Python

### Variavel `conn` ou `connection`

Quando um bloco Python e executado, o objeto de conexao selecionado fica disponivel automaticamente no namespace como `conn` ou `connection`:

```python
# Exemplo 1: Executar query usando pandas
import pandas as pd

# A variavel 'conn' esta automaticamente disponivel
df = pd.read_sql("SELECT * FROM users", conn)
print(df.head())
```

```python
# Exemplo 2: Executar query diretamente na conexao
# Para SQL Server, MySQL, PostgreSQL, etc.

cursor = conn.connection.cursor()
cursor.execute("SELECT COUNT(*) FROM orders")
count = cursor.fetchone()[0]
print(f"Total de pedidos: {count}")
```

```python
# Exemplo 3: Usar SQLAlchemy-style
from sqlalchemy import text

with conn.connection.cursor() as cursor:
    cursor.execute("INSERT INTO logs (message) VALUES (?)", ("Nova entrada",))
    conn.connection.commit()
```

### Multiplas Conexoes em Blocos Diferentes

Voce pode trabalhar com multiplas fontes de dados em uma mesma aba:

**Bloco 1** (Conexao: `DB_Producao` - Linguagem: SQL)
```sql
SELECT customer_id, total_amount 
FROM orders 
WHERE order_date >= '2024-01-01'
```

**Bloco 2** (Conexao: `DB_Analytics` - Linguagem: Python)
```python
# conn aqui aponta para DB_Analytics
import pandas as pd

# Buscar dados de clientes do analytics
customers_df = pd.read_sql("SELECT * FROM customer_segments", conn)

# Juntar com dados de orders do bloco anterior (variavel 'df')
result = df.merge(customers_df, on='customer_id')
print(result)
```

**Bloco 3** (Conexao: `DB_Logs` - Linguagem: SQL)
```sql
-- Registrar processamento no banco de logs
INSERT INTO processing_log (process_name, records_count, timestamp)
VALUES ('analise_vendas', 100, GETDATE())
```

## Fluxo de Trabalho Recomendado

### Cenario 1: Analise Cross-Database

1. **Bloco 1**: Conectar ao banco de producao
   - Selecione conexao: `DB_Producao`
   - Linguagem: SQL
   - Extrair dados de vendas

2. **Bloco 2**: Conectar ao data warehouse
   - Selecione conexao: `DB_DataWarehouse`
   - Linguagem: SQL
   - Extrair dados historicos

3. **Bloco 3**: Processar com Python
   - Selecione conexao: `(Padrao da aba)` ou qualquer outra
   - Linguagem: Python
   - Combinar e analisar dados usando pandas

### Cenario 2: ETL Simples

1. **Bloco 1**: Extrair da origem
   - Conexao: `DB_Source`
   - Executar SELECT e armazenar em `df`

2. **Bloco 2**: Transformar dados
   - Conexao: `(Padrao da aba)`
   - Linguagem: Python
   - Processar `df` com pandas/numpy

3. **Bloco 3**: Carregar no destino
   - Conexao: `DB_Destination`
   - Linguagem: Python
   ```python
   df.to_sql('tabela_destino', conn, if_exists='append', index=False)
   ```

## Objetos Disponiveis no Namespace Python

Quando voce executa um bloco Python, os seguintes objetos estao disponiveis:

| Variavel | Descricao |
|----------|-----------|
| `conn` | Objeto de conexao selecionado no bloco (DatabaseConnector) |
| `connection` | Alias para `conn` |
| `pd` | Pandas (import pandas as pd) |
| `df` | DataFrame resultante do ultimo bloco SQL executado |
| `df1`, `df2`, ... | DataFrames adicionais se o SQL retornou multiplos resultados |
| `_last_result` | Resultado do ultimo bloco executado |

## Notas Importantes

1. **Compatibilidade**: Blocos antigos sem conexao especificada usam automaticamente a conexao da aba (comportamento padrao)

2. **Execucao em Lote**: Quando voce executa todos os blocos (F5 ou Ctrl+Enter), cada bloco usa sua propria conexao

3. **Variaveis Compartilhadas**: Mesmo usando conexoes diferentes, todos os blocos na mesma aba compartilham o namespace Python (variaveis como `df` sao acessiveis entre blocos)

4. **Performance**: Manter multiplas conexoes abertas pode consumir recursos. Considere fechar conexoes que nao estao sendo usadas

## Exemplos Praticos

### Exemplo 1: Comparar dados entre ambientes

```python
# Bloco 1 - Producao (Conexao: DB_Prod)
SELECT COUNT(*) as prod_count FROM products WHERE active = 1
```

```python
# Bloco 2 - Homologacao (Conexao: DB_Homolog)
SELECT COUNT(*) as homolog_count FROM products WHERE active = 1
```

```python
# Bloco 3 - Comparacao (Conexao: qualquer)
prod_count = df.iloc[0]['prod_count']
homolog_count = df1.iloc[0]['homolog_count']

print(f"Producao: {prod_count} produtos")
print(f"Homologacao: {homolog_count} produtos")
print(f"Diferenca: {abs(prod_count - homolog_count)} produtos")
```

### Exemplo 2: Migrar dados entre bancos

```python
# Bloco 1 - Extrair (Conexao: DB_Source)
SELECT * FROM legacy_customers WHERE migrated = 0
```

```python
# Bloco 2 - Transformar e Carregar (Conexao: DB_Target)
import pandas as pd

# df contem dados do bloco anterior
# conn aponta para DB_Target

# Transformar dados
df['full_name'] = df['first_name'] + ' ' + df['last_name']
df['created_at'] = pd.to_datetime('now')

# Carregar no banco de destino
df.to_sql('customers', conn, if_exists='append', index=False)

print(f"Migrados {len(df)} clientes")
```

## Solucao de Problemas

### Erro: "Nenhuma conexao ativa para este bloco"

**Causa**: O bloco nao possui uma conexao selecionada e a aba tambem nao esta conectada.

**Solucao**: 
1. Selecione uma conexao no seletor do bloco, OU
2. Conecte a aba a um banco de dados

### Erro: "NameError: name 'conn' is not defined"

**Causa**: Voce esta tentando usar `conn` em um bloco sem conexao ativa.

**Solucao**: Verifique se o bloco possui uma conexao selecionada (nao pode estar em branco sem uma conexao na aba)

### Variavel `df` esta vazia ou None

**Causa**: Nenhum bloco SQL foi executado antes, ou o ultimo SQL nao retornou dados.

**Solucao**: Execute um bloco SQL antes de tentar usar `df` em Python

## Conclusao

A funcionalidade de conexoes por bloco torna o DataPyn ainda mais poderoso para:
- Trabalhar com multiplas fontes de dados
- Realizar analises cross-database
- Implementar pipelines ETL simples
- Comparar dados entre ambientes (dev, homolog, prod)

Experimente combinar blocos SQL e Python com diferentes conexoes para criar fluxos de trabalho eficientes!
