# Exportar Análise como Script Python

## Descrição

Esta funcionalidade permite exportar toda a análise realizada no DataPyn como um script Python standalone executável.

## Como Usar

### Via Menu
1. Realize sua análise no DataPyn (crie blocos SQL, Python e/ou Cross-Syntax)
2. Vá em **Arquivo → Exportar como Script...**
3. Escolha o local e nome do arquivo
4. O script Python será gerado e salvo

### Via Atalho
- Pressione `Ctrl+Shift+E` para exportar rapidamente

## O Que é Exportado

O script gerado contém:

1. **Cabeçalho com metadados**
   - Data e hora de exportação
   - Conexão utilizada (se houver)

2. **Imports necessários**
   - `pandas` (sempre)
   - `sqlalchemy` e `pyodbc` (se houver blocos SQL ou Cross-Syntax)

3. **Configuração de conexão ao banco**
   - Variáveis de ambiente (DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASSWORD)
   - String de conexão apropriada para o tipo de banco (MySQL, PostgreSQL, SQL Server)
   - Engine SQLAlchemy configurado

4. **Blocos de código na ordem de execução**
   - Blocos SQL → convertidos para `pd.read_sql(...)`
   - Blocos Python → preservados como estão
   - Blocos Cross-Syntax → sintaxe `{{ SQL }}` convertida para `pd.read_sql(...)`

## Exemplo de Saída

### Entrada no DataPyn

**Bloco 1 (SQL):**
```sql
SELECT * FROM users WHERE active = 1
```

**Bloco 2 (Cross-Syntax):**
```python
orders = {{ SELECT * FROM orders WHERE user_id IN (SELECT id FROM users) }}
total = orders['amount'].sum()
print(f'Total: {total}')
```

### Script Exportado

```python
"""
Script Python Exportado do DataPyn

Gerado em: 2026-02-09 18:25:00
Conexão: Production DB
"""

import pandas as pd
from sqlalchemy import create_engine
import pyodbc

# Configuração da Conexão de Banco de Dados
# IMPORTANTE: Ajuste as credenciais abaixo conforme sua configuração
# Tipo de banco: mysql
DB_HOST = 'localhost'
DB_PORT = 3306
DB_NAME = 'production'
DB_USER = 'admin'
DB_PASSWORD = ''  # Preencha a senha aqui

# String de conexão MySQL
connection_string = f'mysql+pymysql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}'

# Criar engine de conexão
engine = create_engine(connection_string)

# ========================================
# Blocos de Código
# ========================================

# --- Bloco 1: SQL ---
# SQL Query executada via pandas
df_bloco_1 = pd.read_sql("""
SELECT * FROM users WHERE active = 1
""", engine)
print(f"Query executada: {len(df_bloco_1)} linhas retornadas")

# --- Bloco 2: CROSS ---
# Cross-syntax: SQL + Python
# Query SQL atribuída a variável orders
orders = pd.read_sql("""
SELECT * FROM orders WHERE user_id IN (SELECT id FROM users)
""", engine)

total = orders['amount'].sum()
print(f'Total: {total}')

# ========================================
# Fim do Script
# ========================================
```

## Detalhes Técnicos

### Conversão de Blocos SQL
```sql
SELECT * FROM users
```
↓
```python
df_bloco_1 = pd.read_sql("""
SELECT * FROM users
""", engine)
```

### Conversão de Cross-Syntax
```python
data = {{ SELECT * FROM table }}
```
↓
```python
data = pd.read_sql("""
SELECT * FROM table
""", engine)
```

### Blocos com Nome
Se um bloco tiver nome definido (campo "Nome do bloco"), esse nome será usado como variável:
```python
# Bloco com nome "usuarios_ativos"
usuarios_ativos = pd.read_sql("""...""", engine)
```

### Strings de Conexão por Banco

**MySQL:**
```python
connection_string = f'mysql+pymysql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}'
```

**PostgreSQL:**
```python
connection_string = f'postgresql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}'
```

**SQL Server:**
```python
connection_string = f'mssql+pyodbc://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}?driver=ODBC+Driver+17+for+SQL+Server'
```

## Requisitos para Executar o Script

O script exportado requer:
- Python 3.7+
- pandas
- sqlalchemy
- Driver apropriado do banco (pymysql, psycopg2, pyodbc)

Instalação:
```bash
pip install pandas sqlalchemy pymysql  # Para MySQL
pip install pandas sqlalchemy psycopg2-binary  # Para PostgreSQL
pip install pandas sqlalchemy pyodbc  # Para SQL Server
```

## Casos de Uso

1. **Compartilhar análises**: Envie o script para colegas executarem
2. **Versionamento**: Salve versões da análise em Git
3. **Automação**: Integre em pipelines de dados (Airflow, cron, etc.)
4. **Reprodutibilidade**: Garanta que a análise pode ser reexecutada
5. **Documentação**: Scripts auto-documentados com comentários

## Limitações

- Apenas blocos com código são exportados (blocos vazios são ignorados)
- Variáveis Python em memória não são serializadas
- Conexões customizadas por bloco SQL ainda não suportadas totalmente
- Senha do banco não é exportada (deve ser preenchida manualmente)

## Segurança

⚠️ **IMPORTANTE**: 
- O script exportado NÃO contém senhas
- Preencha `DB_PASSWORD = ''` manualmente antes de executar
- Nunca versione scripts com senhas em texto plano
- Use variáveis de ambiente ou gerenciadores de secrets em produção

## Suporte

Para dúvidas ou problemas, consulte a [documentação completa](../README.md) ou abra uma issue no GitHub.
