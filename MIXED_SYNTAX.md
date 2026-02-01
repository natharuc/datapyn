# Sintaxe Mista SQL + Python

## O que é?

A **Sintaxe Mista** é um recurso exclusivo do DataPyn que permite escrever queries SQL diretamente no código Python, sem precisar alternar entre os editores.

## Como funciona?

O DataPyn injeta duas funções especiais no namespace do Python:

- **`query(sql)`** - Executa SELECT e retorna um DataFrame
- **`execute(sql)`** - Executa INSERT/UPDATE/DELETE e retorna número de linhas afetadas

## Exemplos Básicos

### Executar Query e Guardar Resultado

```python
# Sintaxe tradicional (2 passos):
# 1. No editor SQL: SELECT * FROM clientes
# 2. No editor Python: usar df

# Sintaxe mista (1 passo):
clientes = query("SELECT * FROM clientes WHERE ativo = 1")
print(len(clientes))
```

### Múltiplas Queries

```python
vendas = query("SELECT * FROM vendas WHERE data >= '2024-01-01'")
produtos = query("SELECT * FROM produtos")
clientes = query("SELECT * FROM clientes")

# Agora você tem 3 DataFrames em memória
print(f"Vendas: {len(vendas)} registros")
print(f"Produtos: {len(produtos)} produtos")
print(f"Clientes: {len(clientes)} clientes")
```

### Executar UPDATE/INSERT/DELETE

```python
# execute() retorna o número de linhas afetadas
linhas = execute("UPDATE produtos SET preco = preco * 1.1 WHERE categoria = 'Eletrônicos'")
print(f"{linhas} produtos atualizados")

# Inserir dados
execute("INSERT INTO log_acesso (usuario, data) VALUES ('admin', NOW())")

# Deletar
linhas_deletadas = execute("DELETE FROM temp_data WHERE processado = 1")
```

## Casos de Uso Avançados

### 1. Análise Sequencial

```python
# Buscar dados brutos
vendas_raw = query("SELECT * FROM vendas WHERE YEAR(data) = 2024")

# Processar
vendas_raw['mes'] = vendas_raw['data'].dt.month
vendas_raw['trimestre'] = vendas_raw['data'].dt.quarter

# Análise
print("Vendas por trimestre:")
print(vendas_raw.groupby('trimestre')['valor'].sum())

# Detalhamento de um trimestre específico
q1 = vendas_raw[vendas_raw['trimestre'] == 1]
detalhes = query(f"""
    SELECT 
        p.nome,
        COUNT(*) as qtd_vendas,
        SUM(v.valor) as total
    FROM vendas v
    JOIN produtos p ON v.produto_id = p.id
    WHERE v.id IN ({','.join(map(str, q1['id'].tolist()))})
    GROUP BY p.id, p.nome
    ORDER BY total DESC
""")
print(detalhes)
```

### 2. Pipeline de ETL

```python
# Extrair
dados_origem = query("SELECT * FROM sistema_legado.vendas")

# Transformar
dados_origem['valor_corrigido'] = dados_origem['valor'] * 1.15
dados_origem['data_importacao'] = pd.Timestamp.now()

# Carregar (salvar em arquivo ou outro banco)
dados_origem.to_csv('vendas_processadas.csv', index=False)

# Registrar sucesso
execute(f"""
    INSERT INTO log_etl (tabela, registros, status, data)
    VALUES ('vendas', {len(dados_origem)}, 'sucesso', NOW())
""")
```

### 3. Combinar Queries Dinâmicas

```python
# Buscar lista de categorias
categorias = query("SELECT DISTINCT categoria FROM produtos ORDER BY categoria")

# Para cada categoria, fazer análise
for categoria in categorias['categoria']:
    vendas_cat = query(f"""
        SELECT 
            p.nome,
            COUNT(v.id) as qtd,
            SUM(v.valor) as total
        FROM vendas v
        JOIN produtos p ON v.produto_id = p.id
        WHERE p.categoria = '{categoria}'
        GROUP BY p.nome
        ORDER BY total DESC
        LIMIT 10
    """)
    
    print(f"\n=== Top 10 em {categoria} ===")
    print(vendas_cat)
```

### 4. Validação e Correção de Dados

```python
# Buscar registros problemáticos
problemas = query("""
    SELECT * FROM clientes 
    WHERE email NOT LIKE '%@%' 
    OR telefone IS NULL
""")

print(f"Encontrados {len(problemas)} registros com problemas")

# Processar e corrigir
for idx, row in problemas.iterrows():
    cliente_id = row['id']
    
    # Tentar corrigir email
    if '@' not in row['email']:
        novo_email = row['email'] + '@example.com'
        execute(f"UPDATE clientes SET email = '{novo_email}' WHERE id = {cliente_id}")
    
    # Marcar para revisão manual
    execute(f"UPDATE clientes SET precisa_revisao = 1 WHERE id = {cliente_id}")

print("Correções aplicadas!")
```

### 5. Relatórios Complexos

```python
# Dados base
vendas = query("""
    SELECT 
        v.*,
        c.nome as cliente_nome,
        c.estado,
        p.nome as produto_nome,
        p.categoria
    FROM vendas v
    JOIN clientes c ON v.cliente_id = c.id
    JOIN produtos p ON v.produto_id = p.id
    WHERE v.data BETWEEN '2024-01-01' AND '2024-12-31'
""")

# Análise 1: Por Estado
por_estado = vendas.groupby('estado').agg({
    'valor': ['sum', 'mean', 'count'],
    'cliente_id': 'nunique'
}).round(2)
por_estado.columns = ['Total', 'Ticket_Medio', 'Qtd_Vendas', 'Qtd_Clientes']
print("\n=== Vendas por Estado ===")
print(por_estado)

# Análise 2: Por Categoria
por_categoria = vendas.groupby('categoria')['valor'].sum().sort_values(ascending=False)
por_categoria_pct = (por_categoria / por_categoria.sum() * 100).round(2)
print("\n=== Participação por Categoria ===")
print(por_categoria_pct)

# Análise 3: Sazonalidade
vendas['mes'] = vendas['data'].dt.month
por_mes = vendas.groupby('mes')['valor'].sum()
print("\n=== Sazonalidade (vendas por mês) ===")
print(por_mes)

# Salvar insights no banco
total_vendas = vendas['valor'].sum()
ticket_medio = vendas['valor'].mean()
execute(f"""
    INSERT INTO relatorios_mensais (periodo, total_vendas, ticket_medio, gerado_em)
    VALUES ('2024', {total_vendas}, {ticket_medio}, NOW())
""")
```

### 6. Integração com Machine Learning

```python
import pandas as pd
from sklearn.model_selection import train_test_split
from sklearn.ensemble import RandomForestClassifier

# Buscar dados históricos
historico = query("""
    SELECT 
        c.idade,
        c.renda,
        c.tempo_cliente,
        COUNT(v.id) as total_compras,
        SUM(v.valor) as valor_total,
        CASE 
            WHEN SUM(v.valor) > 5000 THEN 1 
            ELSE 0 
        END as cliente_premium
    FROM clientes c
    LEFT JOIN vendas v ON v.cliente_id = c.id
    GROUP BY c.id
""")

# Preparar dados
X = historico[['idade', 'renda', 'tempo_cliente', 'total_compras', 'valor_total']]
y = historico['cliente_premium']

# Treinar modelo
X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2)
modelo = RandomForestClassifier()
modelo.fit(X_train, y_train)

# Aplicar em novos clientes
novos_clientes = query("SELECT * FROM clientes WHERE cadastro_recente = 1")
# ... fazer predições e salvar

print(f"Modelo treinado com acurácia: {modelo.score(X_test, y_test):.2%}")
```

## Diferenças: query() vs execute()

| Função | Uso | Retorno | Exemplo |
|--------|-----|---------|---------|
| `query()` | SELECT | DataFrame | `df = query("SELECT * FROM...")` |
| `execute()` | INSERT/UPDATE/DELETE | int (linhas afetadas) | `n = execute("UPDATE...")` |

## ⚠️ Cuidados Importantes

### 1. SQL Injection

```python
# ❌ PERIGOSO - Vulnerável a SQL Injection
usuario_input = "'; DROP TABLE clientes; --"
query(f"SELECT * FROM clientes WHERE nome = '{usuario_input}'")

# ✅ MELHOR - Use parâmetros quando possível
# Ou valide/escape a entrada
import re
if re.match(r'^[a-zA-Z0-9\s]+$', usuario_input):
    query(f"SELECT * FROM clientes WHERE nome = '{usuario_input}'")
```

### 2. Performance

```python
# ❌ LENTO - Múltiplas queries em loop
for id in range(1, 1000):
    query(f"SELECT * FROM clientes WHERE id = {id}")

# ✅ RÁPIDO - Uma query única
ids = ','.join(map(str, range(1, 1000)))
todos = query(f"SELECT * FROM clientes WHERE id IN ({ids})")
```

### 3. Memória

```python
# ⚠️ Cuidado com queries muito grandes
# Isso pode consumir muita RAM:
tudo = query("SELECT * FROM tabela_com_10_milhoes_linhas")

# Melhor: Use LIMIT ou filtre
amostra = query("SELECT * FROM tabela_com_10_milhoes_linhas LIMIT 10000")
```

## Quando Usar?

### Use Sintaxe Mista quando:
- ✅ Precisa combinar SQL e Python frequentemente
- ✅ Quer código mais limpo e linear
- ✅ Faz análises ad-hoc rápidas
- ✅ Precisa de múltiplas queries relacionadas
- ✅ Está fazendo ETL ou data wrangling

### Use Editores Separados quando:
- ✅ Está desenvolvendo queries SQL complexas
- ✅ Quer testar SQL isoladamente
- ✅ Precisa de formatação SQL específica
- ✅ Vai reusar a mesma query várias vezes

## Veja Mais

- [examples_mixed.py](examples_mixed.py) - Exemplos práticos completos
- [README.md](README.md) - Documentação geral
- [QUICKSTART.md](QUICKSTART.md) - Guia rápido de início

## Dicas Profissionais

1. **Combine com Pandas**: Use query() para buscar dados e depois aplique todo poder do Pandas
2. **Teste no SQL Editor primeiro**: Desenvolva a query no editor SQL, depois copie para query()
3. **Use variáveis descritivas**: `clientes_ativos` é melhor que `df1`
4. **Documente queries complexas**: Use comentários antes de queries grandes
5. **Valide antes de execute()**: Sempre teste UPDATE/DELETE antes de executar em produção

## Limitações

- Requer conexão ativa com banco de dados
- Não suporta prepared statements nativos (cuidado com SQL injection)
- Queries muito grandes podem consumir muita memória
- Não substitui ferramentas de BI para relatórios fixos

---

**Aproveite! Esta é uma das funcionalidades mais poderosas do DataPyn** 🚀
