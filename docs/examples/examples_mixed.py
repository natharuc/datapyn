# ============================================================
# Exemplos de Sintaxe Mista (SQL + Python)
# ============================================================
#
# A sintaxe mista permite escrever queries SQL diretamente
# no código Python usando as funções query() e execute()
#
# IMPORTANTE: Execute este código no Editor Python (Shift+F5)
# ============================================================

# Exemplo 1: Query básica com resultado em variável
# --------------------------------------------------
clientes = query("SELECT * FROM clientes WHERE ativo = 1")
print(f"Total de clientes ativos: {len(clientes)}")
print(clientes.head())


# Exemplo 2: Múltiplas queries e manipulação
# -------------------------------------------
vendas = query("SELECT * FROM vendas WHERE data >= '2024-01-01'")
produtos = query("SELECT * FROM produtos")

# Agora manipule com Pandas normalmente
vendas_por_produto = vendas.groupby("produto_id")["valor"].sum()
print(vendas_por_produto)


# Exemplo 3: Query com JOIN
# --------------------------
resultado = query("""
    SELECT 
        c.nome,
        c.email,
        COUNT(v.id) as total_vendas,
        SUM(v.valor) as valor_total
    FROM clientes c
    LEFT JOIN vendas v ON v.cliente_id = c.id
    WHERE c.ativo = 1
    GROUP BY c.id, c.nome, c.email
    ORDER BY valor_total DESC
""")

print(resultado)


# Exemplo 4: Usar resultado de uma query em outra
# ------------------------------------------------
top_clientes = query("SELECT id FROM clientes ORDER BY total_compras DESC LIMIT 10")

# Converte para lista de IDs
ids = top_clientes["id"].tolist()
ids_str = ",".join(map(str, ids))

# Usa na próxima query
pedidos = query(f"SELECT * FROM pedidos WHERE cliente_id IN ({ids_str})")
print(f"Total de pedidos dos top 10 clientes: {len(pedidos)}")


# Exemplo 5: Execute para INSERT/UPDATE/DELETE
# ---------------------------------------------
# execute() retorna número de linhas afetadas
linhas = execute("""
    UPDATE clientes 
    SET ultimo_acesso = NOW() 
    WHERE id = 123
""")
print(f"{linhas} linha(s) atualizada(s)")


# Exemplo 6: Combinar com análise Python
# ---------------------------------------
vendas_mes = query("""
    SELECT 
        DATE_FORMAT(data, '%Y-%m') as mes,
        SUM(valor) as total
    FROM vendas
    GROUP BY mes
    ORDER BY mes
""")

# Calcular crescimento mês a mês
vendas_mes["crescimento"] = vendas_mes["total"].pct_change() * 100
print("\nCrescimento mensal:")
print(vendas_mes)


# Exemplo 7: Filtrar com Python e salvar no banco
# ------------------------------------------------
todos_produtos = query("SELECT * FROM produtos")

# Filtrar produtos com estoque baixo
estoque_baixo = todos_produtos[todos_produtos["estoque"] < 10]

# Criar alerta (poderia salvar em outra tabela)
for _, produto in estoque_baixo.iterrows():
    print(f"⚠️ ALERTA: {produto['nome']} com estoque baixo: {produto['estoque']} unidades")

    # Poderia fazer:
    # execute(f"INSERT INTO alertas (produto_id, tipo) VALUES ({produto['id']}, 'estoque_baixo')")


# Exemplo 8: Query parametrizada (CUIDADO com SQL Injection!)
# ------------------------------------------------------------
status = "ativo"
limite = 100

clientes_filtrados = query(f"""
    SELECT * FROM clientes 
    WHERE status = '{status}'
    LIMIT {limite}
""")

print(f"Encontrados {len(clientes_filtrados)} clientes")


# Exemplo 9: Análise complexa
# ----------------------------
# Buscar vendas
vendas = query("SELECT * FROM vendas WHERE YEAR(data) = 2024")

# Estatísticas com Pandas
print("\n=== Estatísticas de Vendas 2024 ===")
print(f"Total de vendas: {len(vendas)}")
print(f"Valor total: R$ {vendas['valor'].sum():,.2f}")
print(f"Ticket médio: R$ {vendas['valor'].mean():,.2f}")
print(f"Maior venda: R$ {vendas['valor'].max():,.2f}")
print(f"Menor venda: R$ {vendas['valor'].min():,.2f}")

# Vendas por mês
vendas["mes"] = vendas["data"].dt.month
vendas_por_mes = vendas.groupby("mes")["valor"].sum()
print("\nVendas por mês:")
print(vendas_por_mes)


# Exemplo 10: Criar DataFrame e exportar
# ---------------------------------------
relatorio = query("""
    SELECT 
        p.categoria,
        COUNT(v.id) as qtd_vendas,
        SUM(v.quantidade) as qtd_produtos,
        SUM(v.valor) as receita
    FROM vendas v
    JOIN produtos p ON v.produto_id = p.id
    GROUP BY p.categoria
    ORDER BY receita DESC
""")

# Adicionar percentual
relatorio["percentual"] = (relatorio["receita"] / relatorio["receita"].sum() * 100).round(2)

print("\nRelatório por Categoria:")
print(relatorio)

# Para exportar: clique com botão direito na aba "Resultados" > Exportar


# ============================================================
# DICAS
# ============================================================
#
# 1. Use query() para SELECT (retorna DataFrame)
# 2. Use execute() para INSERT/UPDATE/DELETE (retorna nº de linhas)
# 3. Resultados ficam em variáveis Python normais
# 4. Manipule com Pandas após receber
# 5. Cuidado com SQL Injection em queries dinâmicas
# 6. A conexão com o banco deve estar ativa
# 7. Erros SQL aparecem no Output Python
#
# ============================================================
