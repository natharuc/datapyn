-- ===================================
-- EXEMPLOS DE QUERIES SQL
-- ===================================

-- ----------------------------------
-- 1. SELECT BÁSICO
-- ----------------------------------
SELECT * FROM clientes;

SELECT id, nome, email, cidade
FROM clientes
WHERE ativo = 1;

-- ----------------------------------
-- 2. FILTROS E CONDIÇÕES
-- ----------------------------------

-- Filtro simples
SELECT * FROM vendas WHERE valor > 1000;

-- Múltiplas condições
SELECT * FROM vendas 
WHERE valor > 1000 
  AND estado = 'SP'
  AND data >= '2025-01-01';

-- Operador IN
SELECT * FROM produtos 
WHERE categoria IN ('Eletrônicos', 'Informática', 'Games');

-- Operador LIKE
SELECT * FROM clientes 
WHERE nome LIKE '%Silva%';

-- Operador BETWEEN
SELECT * FROM vendas 
WHERE data BETWEEN '2025-01-01' AND '2025-01-31';

-- ----------------------------------
-- 3. JOINS
-- ----------------------------------

-- INNER JOIN
SELECT 
    v.id,
    v.data,
    v.valor,
    c.nome as cliente,
    p.descricao as produto
FROM vendas v
INNER JOIN clientes c ON v.cliente_id = c.id
INNER JOIN produtos p ON v.produto_id = p.id;

-- LEFT JOIN
SELECT 
    c.nome,
    COUNT(v.id) as total_vendas
FROM clientes c
LEFT JOIN vendas v ON c.id = v.cliente_id
GROUP BY c.id, c.nome;

-- ----------------------------------
-- 4. AGREGAÇÕES
-- ----------------------------------

-- COUNT, SUM, AVG, MIN, MAX
SELECT 
    COUNT(*) as total_vendas,
    SUM(valor) as valor_total,
    AVG(valor) as valor_medio,
    MIN(valor) as menor_venda,
    MAX(valor) as maior_venda
FROM vendas;

-- GROUP BY
SELECT 
    estado,
    COUNT(*) as qtd_vendas,
    SUM(valor) as total
FROM vendas
GROUP BY estado
ORDER BY total DESC;

-- GROUP BY com múltiplas colunas
SELECT 
    estado,
    categoria,
    COUNT(*) as qtd,
    SUM(valor) as total
FROM vendas
GROUP BY estado, categoria
ORDER BY estado, total DESC;

-- HAVING (filtro após agregação)
SELECT 
    cliente_id,
    COUNT(*) as qtd_compras,
    SUM(valor) as total_gasto
FROM vendas
GROUP BY cliente_id
HAVING SUM(valor) > 10000
ORDER BY total_gasto DESC;

-- ----------------------------------
-- 5. SUBQUERIES
-- ----------------------------------

-- Subquery no WHERE
SELECT * FROM vendas
WHERE valor > (SELECT AVG(valor) FROM vendas);

-- Subquery no FROM
SELECT 
    categoria,
    AVG(total_vendas) as media_vendas
FROM (
    SELECT 
        categoria,
        COUNT(*) as total_vendas
    FROM produtos
    GROUP BY categoria
) as subquery
GROUP BY categoria;

-- ----------------------------------
-- 6. CASE WHEN
-- ----------------------------------

SELECT 
    id,
    valor,
    CASE 
        WHEN valor > 5000 THEN 'Alta'
        WHEN valor > 1000 THEN 'Média'
        ELSE 'Baixa'
    END as classificacao
FROM vendas;

-- ----------------------------------
-- 7. FUNÇÕES DE DATA
-- ----------------------------------

-- Extrair partes da data
SELECT 
    data,
    YEAR(data) as ano,
    MONTH(data) as mes,
    DAY(data) as dia
FROM vendas;

-- Agrupar por mês
SELECT 
    YEAR(data) as ano,
    MONTH(data) as mes,
    COUNT(*) as qtd_vendas,
    SUM(valor) as total
FROM vendas
GROUP BY YEAR(data), MONTH(data)
ORDER BY ano DESC, mes DESC;

-- ----------------------------------
-- 8. WINDOW FUNCTIONS
-- ----------------------------------

-- Ranking
SELECT 
    nome,
    valor,
    RANK() OVER (ORDER BY valor DESC) as ranking
FROM vendas;

-- Partition by
SELECT 
    categoria,
    nome,
    valor,
    RANK() OVER (PARTITION BY categoria ORDER BY valor DESC) as ranking_categoria
FROM produtos;

-- ----------------------------------
-- 9. CTE (Common Table Expression)
-- ----------------------------------

WITH vendas_2025 AS (
    SELECT * FROM vendas
    WHERE YEAR(data) = 2025
),
vendas_agrupadas AS (
    SELECT 
        estado,
        SUM(valor) as total
    FROM vendas_2025
    GROUP BY estado
)
SELECT * FROM vendas_agrupadas
ORDER BY total DESC;

-- ----------------------------------
-- 10. UNION
-- ----------------------------------

-- Combinar resultados de múltiplas queries
SELECT 'Janeiro' as mes, SUM(valor) as total
FROM vendas WHERE MONTH(data) = 1

UNION ALL

SELECT 'Fevereiro' as mes, SUM(valor) as total
FROM vendas WHERE MONTH(data) = 2

UNION ALL

SELECT 'Março' as mes, SUM(valor) as total
FROM vendas WHERE MONTH(data) = 3;

-- ----------------------------------
-- 11. TOP N
-- ----------------------------------

-- SQL Server
SELECT TOP 10 * FROM vendas ORDER BY valor DESC;

-- MySQL/PostgreSQL
SELECT * FROM vendas ORDER BY valor DESC LIMIT 10;

-- ----------------------------------
-- 12. DISTINCT
-- ----------------------------------

-- Valores únicos
SELECT DISTINCT estado FROM clientes;

-- Contar valores únicos
SELECT COUNT(DISTINCT cliente_id) as total_clientes
FROM vendas;

-- ----------------------------------
-- 13. NULL HANDLING
-- ----------------------------------

-- Filtrar nulos
SELECT * FROM clientes WHERE email IS NULL;
SELECT * FROM clientes WHERE email IS NOT NULL;

-- Substituir nulos
SELECT 
    nome,
    COALESCE(email, 'sem-email@example.com') as email
FROM clientes;

-- ----------------------------------
-- 14. STRING FUNCTIONS
-- ----------------------------------

SELECT 
    UPPER(nome) as nome_maiusculo,
    LOWER(nome) as nome_minusculo,
    LEN(nome) as tamanho_nome,
    SUBSTRING(nome, 1, 3) as primeiras_letras,
    CONCAT(nome, ' - ', cidade) as nome_completo
FROM clientes;

-- ----------------------------------
-- 15. ANÁLISES AVANÇADAS
-- ----------------------------------

-- Análise de cohort (clientes por mês de cadastro)
SELECT 
    YEAR(data_cadastro) as ano,
    MONTH(data_cadastro) as mes,
    COUNT(*) as novos_clientes,
    SUM(COUNT(*)) OVER (ORDER BY YEAR(data_cadastro), MONTH(data_cadastro)) as acumulado
FROM clientes
GROUP BY YEAR(data_cadastro), MONTH(data_cadastro)
ORDER BY ano, mes;

-- Análise de crescimento
SELECT 
    YEAR(data) as ano,
    MONTH(data) as mes,
    SUM(valor) as total,
    LAG(SUM(valor)) OVER (ORDER BY YEAR(data), MONTH(data)) as total_mes_anterior,
    (SUM(valor) - LAG(SUM(valor)) OVER (ORDER BY YEAR(data), MONTH(data))) / 
        LAG(SUM(valor)) OVER (ORDER BY YEAR(data), MONTH(data)) * 100 as crescimento_pct
FROM vendas
GROUP BY YEAR(data), MONTH(data)
ORDER BY ano, mes;
