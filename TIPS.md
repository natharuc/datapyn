# Dicas e Truques - DataPyn IDE

## 🎯 Workflow Eficiente

### 1. Explorando um Banco Novo

```sql
-- 1. Liste todas as tabelas
SELECT TABLE_NAME 
FROM INFORMATION_SCHEMA.TABLES 
WHERE TABLE_TYPE = 'BASE TABLE';
```

```python
# 2. Explore estrutura de uma tabela
import pandas as pd
print(df)
print("\nColunas:", list(df.columns))
```

```sql
-- 3. Veja amostra de dados
SELECT TOP 100 * FROM nome_da_tabela;
```

```python
# 4. Analise os dados
print(df.info())
print(df.describe())
```

### 2. Desenvolvimento Iterativo

**Passo 1**: Comece com amostra pequena
```sql
SELECT TOP 1000 * FROM vendas 
WHERE data >= '2025-01-01';
```

**Passo 2**: Teste sua lógica Python
```python
# Teste com df
resultado = df.groupby('categoria')['valor'].sum()
print(resultado)
```

**Passo 3**: Expanda para dados completos
```sql
SELECT * FROM vendas 
WHERE data >= '2025-01-01';
```

### 3. Usar Múltiplas Queries

```sql
-- Query 1: Vendas Janeiro
SELECT * FROM vendas WHERE MONTH(data) = 1;
```

```sql
-- Query 2: Vendas Fevereiro  
SELECT * FROM vendas WHERE MONTH(data) = 2;
```

```python
# Agora você tem df1 (Janeiro) e df2 (Fevereiro)
print("Jan:", df1['valor'].sum())
print("Fev:", df2['valor'].sum())

# Combine os dados
df_total = pd.concat([df1, df2])
print("Total:", df_total['valor'].sum())
```

## ⚡ Atalhos Produtivos

### Edição Rápida

- **Ctrl+/** - Comentar/descomentar múltiplas linhas
- **Ctrl+D** - Duplicar linha
- **Ctrl+X** - Recortar linha inteira (sem seleção)
- **Ctrl+Shift+K** - Deletar linha

### Navegação

- **Ctrl+F** - Buscar
- **Ctrl+H** - Substituir
- **Ctrl+G** - Ir para linha
- **Home/End** - Início/fim da linha

### Seleção

- **Ctrl+A** - Selecionar tudo
- **Shift+Setas** - Selecionar caracteres
- **Ctrl+Shift+Setas** - Selecionar palavras

### Execução Seletiva

- Selecione parte do SQL
- Pressione F5
- Apenas a seleção será executada!

Exemplo:
```sql
SELECT * FROM clientes;  -- Não será executado

SELECT * FROM produtos   -- Apenas isso será executado
WHERE ativo = 1;         -- se estiver selecionado

SELECT * FROM vendas;    -- Não será executado
```

## 🎨 Formatação de Código

### SQL

```sql
-- Mal formatado
select a.id,a.nome,b.valor from tabela_a a inner join tabela_b b on a.id=b.id where a.ativo=1

-- Bem formatado
SELECT 
    a.id,
    a.nome,
    b.valor
FROM tabela_a a
INNER JOIN tabela_b b ON a.id = b.id
WHERE a.ativo = 1;
```

### Python

```python
# Mal formatado
x=df[df['valor']>1000].groupby('cat')['val'].sum()

# Bem formatado
filtrado = df[df['valor'] > 1000]
resultado = filtrado.groupby('categoria')['valor'].sum()
print(resultado)
```

## 🔥 Truques Avançados

### 1. Template Queries

Salve queries comuns como comentários:

```sql
-- TEMPLATE: Vendas por período
-- SELECT * FROM vendas 
-- WHERE data BETWEEN 'DATA_INICIO' AND 'DATA_FIM';

-- Use assim:
SELECT * FROM vendas 
WHERE data BETWEEN '2025-01-01' AND '2025-01-31';
```

### 2. Funções Python Reutilizáveis

```python
# Salve funções úteis no início do editor Python

def resumo(dataframe):
    """Mostra resumo rápido do DataFrame"""
    print(f"Linhas: {len(dataframe):,}")
    print(f"Colunas: {len(dataframe.columns)}")
    print(f"Memória: {dataframe.memory_usage(deep=True).sum() / 1024 / 1024:.2f} MB")
    print("\nPrimeiras linhas:")
    print(dataframe.head())
    
def top_n(dataframe, coluna, n=10):
    """Retorna top N valores"""
    return dataframe.nlargest(n, coluna)

# Use em qualquer resultado:
resumo(df)
print(top_n(df, 'valor', 5))
```

### 3. Análise de Performance

```python
import time

# Marcar início
inicio = time.time()

# Seu código aqui
resultado = df.groupby('categoria').agg({
    'valor': ['sum', 'mean', 'count'],
    'quantidade': 'sum'
})

# Marcar fim
tempo = time.time() - inicio
print(f"\nTempo de execução: {tempo:.2f}s")
print(resultado)
```

### 4. Exports Customizados

```python
# Export com formatação
writer = pd.ExcelWriter('relatorio.xlsx', engine='openpyxl')

# Múltiplas abas
df.to_excel(writer, sheet_name='Dados Completos', index=False)

resumo = df.groupby('categoria')['valor'].sum()
resumo.to_excel(writer, sheet_name='Resumo')

writer.close()
print("Excel criado com múltiplas abas!")
```

### 5. Validação de Dados

```python
def validar_dados(df):
    """Valida qualidade dos dados"""
    print("=== VALIDAÇÃO DE DADOS ===\n")
    
    # Valores nulos
    nulos = df.isnull().sum()
    if nulos.any():
        print("⚠️ Colunas com valores nulos:")
        print(nulos[nulos > 0])
    else:
        print("✅ Sem valores nulos")
    
    # Duplicatas
    dupl = df.duplicated().sum()
    if dupl > 0:
        print(f"\n⚠️ {dupl} linhas duplicadas")
    else:
        print("\n✅ Sem duplicatas")
    
    # Tipos de dados
    print("\n📊 Tipos de dados:")
    print(df.dtypes)
    
validar_dados(df)
```

### 6. Comparações Rápidas

```python
# Compare dois DataFrames
def comparar(df1, df2, nome1="df1", nome2="df2"):
    print(f"\n=== {nome1} vs {nome2} ===")
    print(f"{nome1}: {len(df1):,} linhas")
    print(f"{nome2}: {len(df2):,} linhas")
    print(f"Diferença: {len(df2) - len(df1):,} linhas")
    
    if 'valor' in df1.columns and 'valor' in df2.columns:
        total1 = df1['valor'].sum()
        total2 = df2['valor'].sum()
        print(f"\n{nome1} total: R$ {total1:,.2f}")
        print(f"{nome2} total: R$ {total2:,.2f}")
        print(f"Diferença: R$ {total2 - total1:,.2f}")
        if total1 > 0:
            perc = ((total2 / total1) - 1) * 100
            print(f"Variação: {perc:+.2f}%")

comparar(df1, df2, "Janeiro", "Fevereiro")
```

## 💾 Gerenciamento de Memória

### Liberar Memória

```python
# Ver uso de memória
import sys
print(f"Tamanho de df: {sys.getsizeof(df) / 1024 / 1024:.2f} MB")

# Limpar variáveis específicas
del df1
del df2

# Python coleta lixo automaticamente, mas pode forçar:
import gc
gc.collect()
```

### Otimizar DataFrames

```python
# Converter tipos de dados para economizar memória
def otimizar_tipos(df):
    for col in df.columns:
        col_type = df[col].dtype
        
        if col_type == 'object':
            # Tentar converter para categoria
            num_unique = df[col].nunique()
            num_total = len(df[col])
            
            if num_unique / num_total < 0.5:
                df[col] = df[col].astype('category')
        
        elif col_type == 'float64':
            df[col] = df[col].astype('float32')
        
        elif col_type == 'int64':
            df[col] = df[col].astype('int32')
    
    return df

# Antes
print("Antes:", df.memory_usage(deep=True).sum() / 1024 / 1024, "MB")

# Otimizar
df = otimizar_tipos(df)

# Depois
print("Depois:", df.memory_usage(deep=True).sum() / 1024 / 1024, "MB")
```

## 🎓 Casos de Uso Reais

### Análise de Churn

```sql
SELECT 
    cliente_id,
    MAX(data_compra) as ultima_compra,
    COUNT(*) as total_compras,
    SUM(valor) as total_gasto
FROM vendas
GROUP BY cliente_id;
```

```python
import datetime as dt

# Calcular dias desde última compra
df['ultima_compra'] = pd.to_datetime(df['ultima_compra'])
hoje = pd.Timestamp.now()
df['dias_sem_comprar'] = (hoje - df['ultima_compra']).dt.days

# Classificar risco de churn
def classificar_churn(dias):
    if dias > 180:
        return 'Alto Risco'
    elif dias > 90:
        return 'Médio Risco'
    else:
        return 'Ativo'

df['risco_churn'] = df['dias_sem_comprar'].apply(classificar_churn)

print(df.groupby('risco_churn').size())
```

### Análise RFM (Recency, Frequency, Monetary)

```python
# Já tendo os dados de vendas

# Recency: Dias desde última compra
df['recency'] = df['dias_sem_comprar']

# Frequency: Total de compras
df['frequency'] = df['total_compras']

# Monetary: Valor total gasto
df['monetary'] = df['total_gasto']

# Criar quartis
df['R_score'] = pd.qcut(df['recency'], 4, labels=[4,3,2,1])
df['F_score'] = pd.qcut(df['frequency'], 4, labels=[1,2,3,4])
df['M_score'] = pd.qcut(df['monetary'], 4, labels=[1,2,3,4])

# Score RFM
df['RFM_score'] = df['R_score'].astype(str) + df['F_score'].astype(str) + df['M_score'].astype(str)

# Melhores clientes
melhores = df[df['RFM_score'] == '444']
print(f"Melhores clientes: {len(melhores)}")
print(melhores[['cliente_id', 'recency', 'frequency', 'monetary']])
```

## 🚀 Produtividade Máxima

1. **Mantenha queries base salvas** em arquivos .sql
2. **Crie biblioteca de funções Python** reutilizáveis
3. **Use comentários** para documentar lógica complexa
4. **Salve análises importantes** como scripts
5. **Use versionamento** (Git) para queries críticas
6. **Organize resultados** - limpe o que não precisa mais
7. **Nomeie variáveis claramente** em vez de df1, df2...

```python
# Em vez de:
df1 = resultado_query_1
df2 = resultado_query_2

# Faça:
vendas_2024 = df1.copy()
vendas_2025 = df2.copy()
```

Aproveite o DataPyn! 🎉
