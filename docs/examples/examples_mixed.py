# ============================================================
# Mixed Syntax Examples (SQL + Python)
# ============================================================
#
# Mixed syntax allows writing SQL queries directly
# in Python code using query() and execute() functions
#
# IMPORTANT: Run this code in the Python Editor (Shift+F5)
# ============================================================

# Example 1: Basic query with result in variable
# --------------------------------------------------
clientes = query("SELECT * FROM clientes WHERE ativo = 1")
print(f"Total active clients: {len(clientes)}")
print(clientes.head())


# Example 2: Multiple queries and manipulation
# -------------------------------------------
vendas = query("SELECT * FROM vendas WHERE data >= '2024-01-01'")
produtos = query("SELECT * FROM produtos")

# Now manipulate with Pandas normally
vendas_por_produto = vendas.groupby("produto_id")["valor"].sum()
print(vendas_por_produto)


# Example 3: Query with JOIN
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


# Example 4: Use result from one query in another
# ------------------------------------------------
top_clientes = query("SELECT id FROM clientes ORDER BY total_compras DESC LIMIT 10")

# Convert to list of IDs
ids = top_clientes["id"].tolist()
ids_str = ",".join(map(str, ids))

# Use in next query
pedidos = query(f"SELECT * FROM pedidos WHERE cliente_id IN ({ids_str})")
print(f"Total orders from top 10 clients: {len(pedidos)}")


# Example 5: Execute for INSERT/UPDATE/DELETE
# ---------------------------------------------
# execute() returns number of affected rows
linhas = execute("""
    UPDATE clientes 
    SET ultimo_acesso = NOW() 
    WHERE id = 123
""")
print(f"{linhas} row(s) updated")


# Example 6: Combine with Python analysis
# ---------------------------------------
vendas_mes = query("""
    SELECT 
        DATE_FORMAT(data, '%Y-%m') as mes,
        SUM(valor) as total
    FROM vendas
    GROUP BY mes
    ORDER BY mes
""")

# Calculate month-over-month growth
vendas_mes["crescimento"] = vendas_mes["total"].pct_change() * 100
print("\nMonthly growth:")
print(vendas_mes)


# Example 7: Filter with Python and save to database
# ------------------------------------------------
todos_produtos = query("SELECT * FROM produtos")

# Filter low stock products
estoque_baixo = todos_produtos[todos_produtos["estoque"] < 10]

# Create alert (could save to another table)
for _, produto in estoque_baixo.iterrows():
    print(f"⚠️ ALERT: {produto['nome']} with low stock: {produto['estoque']} units")

    # Could do:
    # execute(f"INSERT INTO alertas (produto_id, tipo) VALUES ({produto['id']}, 'estoque_baixo')")


# Example 8: Parameterized query (BE CAREFUL with SQL Injection!)
# ------------------------------------------------------------
status = "ativo"
limite = 100

clientes_filtrados = query(f"""
    SELECT * FROM clientes 
    WHERE status = '{status}'
    LIMIT {limite}
""")

print(f"Found {len(clientes_filtrados)} clients")


# Example 9: Complex analysis
# ----------------------------
# Fetch sales
vendas = query("SELECT * FROM vendas WHERE YEAR(data) = 2024")

# Statistics with Pandas
print("\n=== 2024 Sales Statistics ===")
print(f"Total sales: {len(vendas)}")
print(f"Total value: R$ {vendas['valor'].sum():,.2f}")
print(f"Average ticket: R$ {vendas['valor'].mean():,.2f}")
print(f"Highest sale: R$ {vendas['valor'].max():,.2f}")
print(f"Lowest sale: R$ {vendas['valor'].min():,.2f}")

# Sales by month
vendas["mes"] = vendas["data"].dt.month
vendas_por_mes = vendas.groupby("mes")["valor"].sum()
print("\nSales by month:")
print(vendas_por_mes)


# Example 10: Create DataFrame and export
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

# Add percentage
relatorio["percentual"] = (relatorio["receita"] / relatorio["receita"].sum() * 100).round(2)

print("\nReport by Category:")
print(relatorio)

# To export: right-click on "Results" tab > Export


# ============================================================
# TIPS
# ============================================================
#
# 1. Use query() for SELECT (returns DataFrame)
# 2. Use execute() for INSERT/UPDATE/DELETE (returns number of rows)
# 3. Results are stored in normal Python variables
# 4. Manipulate with Pandas after receiving
# 5. Be careful with SQL Injection in dynamic queries
# 6. Database connection must be active
# 7. SQL errors appear in Python Output
#
# ============================================================
