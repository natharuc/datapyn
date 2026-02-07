"""
Script de exemplo mostrando como usar o DataPyn
"""

# ===================================
# EXEMPLOS DE USO DO DATAPYN
# ===================================

# ----------------------------------
# 1. ANÁLISE BÁSICA
# ----------------------------------

# Após executar uma query SQL (F5):
# SELECT * FROM vendas

# Use o editor Python (Shift+F5):
print("=== ANÁLISE BÁSICA ===")
print(f"Total de registros: {len(df)}")
print(f"Colunas: {list(df.columns)}")
print("\nPrimeiras linhas:")
print(df.head())

# ----------------------------------
# 2. ESTATÍSTICAS DESCRITIVAS
# ----------------------------------

print("\n=== ESTATÍSTICAS ===")
print(df.describe())

# ----------------------------------
# 3. FILTRAGEM DE DADOS
# ----------------------------------

# Filtrar por valor
vendas_altas = df[df['valor'] > 1000]
print(f"\nVendas acima de R$ 1000: {len(vendas_altas)}")

# Filtrar por texto
vendas_sp = df[df['estado'] == 'SP']
print(f"Vendas em SP: {len(vendas_sp)}")

# Filtrar por data
import pandas as pd
df['data'] = pd.to_datetime(df['data'])
vendas_2025 = df[df['data'].dt.year == 2025]
print(f"Vendas em 2025: {len(vendas_2025)}")

# ----------------------------------
# 4. AGRUPAMENTO E AGREGAÇÃO
# ----------------------------------

print("\n=== AGRUPAMENTOS ===")

# Agrupar por categoria
por_categoria = df.groupby('categoria')['valor'].agg(['sum', 'mean', 'count'])
print("\nPor categoria:")
print(por_categoria)

# Agrupar por múltiplas colunas
por_estado_categoria = df.groupby(['estado', 'categoria'])['valor'].sum()
print("\nPor estado e categoria:")
print(por_estado_categoria)

# ----------------------------------
# 5. CRIAR NOVAS COLUNAS
# ----------------------------------

# Adicionar coluna calculada
df['valor_com_imposto'] = df['valor'] * 1.18
df['mes'] = df['data'].dt.month
df['ano'] = df['data'].dt.year

print("\nNovas colunas adicionadas!")
print(df[['valor', 'valor_com_imposto', 'mes', 'ano']].head())

# ----------------------------------
# 6. COMPARAR MÚLTIPLAS QUERIES
# ----------------------------------

# Execute duas queries diferentes e depois:
# Query 1 -> df1
# Query 2 -> df2

# Comparar totais
print("\n=== COMPARAÇÃO ===")
print(f"Total df1: R$ {df1['valor'].sum():,.2f}")
print(f"Total df2: R$ {df2['valor'].sum():,.2f}")

# Calcular crescimento
crescimento = ((df2['valor'].sum() / df1['valor'].sum()) - 1) * 100
print(f"Crescimento: {crescimento:.2f}%")

# ----------------------------------
# 7. VISUALIZAÇÃO (requer matplotlib)
# ----------------------------------

import matplotlib.pyplot as plt

# Gráfico de barras
df.groupby('categoria')['valor'].sum().plot(kind='bar', title='Vendas por Categoria')
plt.ylabel('Valor Total')
plt.xticks(rotation=45)
plt.tight_layout()
plt.show()

# Gráfico de pizza
df.groupby('estado')['valor'].sum().plot(kind='pie', title='Vendas por Estado', autopct='%1.1f%%')
plt.ylabel('')
plt.show()

# Gráfico de linha (temporal)
vendas_por_mes = df.groupby(df['data'].dt.to_period('M'))['valor'].sum()
vendas_por_mes.plot(kind='line', title='Evolução de Vendas')
plt.ylabel('Valor')
plt.xlabel('Mês')
plt.grid(True)
plt.show()

# ----------------------------------
# 8. EXPORTAR RESULTADOS
# ----------------------------------

# Exportar DataFrame filtrado para CSV
vendas_altas.to_csv('vendas_altas.csv', index=False, encoding='utf-8-sig')
print("\nArquivo CSV exportado!")

# Exportar para Excel
vendas_altas.to_excel('vendas_altas.xlsx', index=False)
print("Arquivo Excel exportado!")

# ----------------------------------
# 9. PIVOTING E TABELAS DINÂMICAS
# ----------------------------------

# Criar tabela dinâmica
pivot = df.pivot_table(
    values='valor',
    index='categoria',
    columns='estado',
    aggfunc='sum',
    fill_value=0
)
print("\n=== TABELA DINÂMICA ===")
print(pivot)

# ----------------------------------
# 10. ANÁLISE DE VALORES NULOS
# ----------------------------------

print("\n=== VALORES NULOS ===")
print(df.isnull().sum())

# Preencher nulos
df_limpo = df.fillna({
    'categoria': 'Sem Categoria',
    'valor': 0
})

# Remover linhas com nulos
df_sem_nulos = df.dropna()
print(f"Registros após remover nulos: {len(df_sem_nulos)}")

# ----------------------------------
# 11. TOP N REGISTROS
# ----------------------------------

# Top 10 maiores vendas
top_10 = df.nlargest(10, 'valor')
print("\n=== TOP 10 VENDAS ===")
print(top_10[['data', 'categoria', 'valor']])

# Bottom 10 menores vendas
bottom_10 = df.nsmallest(10, 'valor')
print("\n=== 10 MENORES VENDAS ===")
print(bottom_10[['data', 'categoria', 'valor']])

# ----------------------------------
# 12. OPERAÇÕES DE STRING
# ----------------------------------

# Converter para maiúsculas
df['categoria_upper'] = df['categoria'].str.upper()

# Extrair parte da string
df['codigo_produto'] = df['descricao'].str[:5]

# Verificar se contém texto
df['eh_especial'] = df['descricao'].str.contains('Premium', na=False)

print("\nOperações de string aplicadas!")

# ----------------------------------
# 13. MERGE/JOIN DE DATAFRAMES
# ----------------------------------

# Se você tem df1 (vendas) e df2 (produtos)
# Fazer join:
df_completo = pd.merge(
    df1, 
    df2, 
    on='produto_id', 
    how='left'
)
print(f"\nDataFrame merged: {len(df_completo)} registros")

# ----------------------------------
# 14. ANÁLISE DE PERFORMANCE
# ----------------------------------

print("\n=== PERFORMANCE ===")
print(f"Memória usada: {df.memory_usage(deep=True).sum() / 1024 / 1024:.2f} MB")
print(f"Tipos de dados:")
print(df.dtypes)

# ----------------------------------
# 15. CUSTOM FUNCTIONS
# ----------------------------------

def classificar_venda(valor):
    """Classifica venda por valor"""
    if valor > 5000:
        return 'Alta'
    elif valor > 1000:
        return 'Média'
    else:
        return 'Baixa'

# Aplicar função
df['classificacao'] = df['valor'].apply(classificar_venda)

print("\n=== CLASSIFICAÇÃO DE VENDAS ===")
print(df.groupby('classificacao').size())

print("\n✅ Exemplos executados com sucesso!")
