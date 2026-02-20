"""
Script Python Exportado do DataPyn

Gerado em: 2026-02-09 18:35:00
Conexão: Production Database
"""

import pandas as pd
from sqlalchemy import create_engine

# Configuração da Conexão de Banco de Dados
# IMPORTANTE: Ajuste as credenciais abaixo conforme sua configuração
# Tipo de banco: mysql
DB_HOST = 'localhost'
DB_PORT = 3306
DB_NAME = 'ecommerce'
DB_USER = 'analyst'
DB_PASSWORD = ''  # Preencha a senha aqui

# String de conexão MySQL
connection_string = f'mysql+pymysql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}'

# Criar engine de conexão
engine = create_engine(connection_string)

# ========================================
# Blocos de Código
# ========================================

# --- Bloco 1: SQL (usuarios_ativos) ---
# SQL Query executada via pandas
usuarios_ativos = pd.read_sql("""
SELECT 
    id,
    nome,
    email,
    data_cadastro
FROM usuarios
WHERE ativo = 1
ORDER BY data_cadastro DESC
""", engine)
print(f"Query executada: {len(usuarios_ativos)} linhas retornadas")

# --- Bloco 2: PYTHON ---
# Código Python
print(f'Total de usuários ativos: {len(usuarios_ativos)}')
print(f'Primeiro cadastro: {usuarios_ativos["data_cadastro"].min()}')
print(f'Último cadastro: {usuarios_ativos["data_cadastro"].max()}')

# --- Bloco 3: CROSS ---
# Cross-syntax: SQL + Python
# Query SQL atribuída a variável pedidos
pedidos = pd.read_sql("""
SELECT 
    p.id,
    p.usuario_id,
    p.valor_total,
    p.data_pedido
FROM pedidos p
WHERE p.usuario_id IN (SELECT id FROM usuarios WHERE ativo = 1)
""", engine)

# Análise dos pedidos
total_vendas = pedidos['valor_total'].sum()
ticket_medio = pedidos['valor_total'].mean()

print(f'\n=== Análise de Vendas ===')
print(f'Total de pedidos: {len(pedidos)}')
print(f'Total de vendas: R$ {total_vendas:,.2f}')
print(f'Ticket médio: R$ {ticket_medio:,.2f}')

# --- Bloco 4: SQL (top_produtos) ---
# SQL Query executada via pandas
top_produtos = pd.read_sql("""
SELECT 
    pr.nome as produto,
    COUNT(DISTINCT p.id) as qtd_pedidos,
    SUM(pi.quantidade) as qtd_vendida,
    SUM(pi.valor_total) as valor_total
FROM pedidos_itens pi
JOIN pedidos p ON pi.pedido_id = p.id
JOIN produtos pr ON pi.produto_id = pr.id
WHERE p.data_pedido >= DATE_SUB(CURDATE(), INTERVAL 30 DAY)
GROUP BY pr.id, pr.nome
ORDER BY valor_total DESC
LIMIT 10
""", engine)
print(f"Query executada: {len(top_produtos)} linhas retornadas")

# --- Bloco 5: PYTHON ---
# Código Python
print('\n=== Top 10 Produtos (últimos 30 dias) ===')
for idx, row in top_produtos.iterrows():
    print(f"{idx+1}. {row['produto']}: R$ {row['valor_total']:,.2f} ({row['qtd_vendida']} unidades)")

# Criar visualização
import matplotlib.pyplot as plt

plt.figure(figsize=(12, 6))
plt.barh(top_produtos['produto'], top_produtos['valor_total'])
plt.xlabel('Valor Total (R$)')
plt.title('Top 10 Produtos por Faturamento - Últimos 30 Dias')
plt.tight_layout()
plt.savefig('top_produtos.png')
print('\nGráfico salvo: top_produtos.png')

# ========================================
# Fim do Script
# ========================================
