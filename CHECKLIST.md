# 📋 CHECKLIST DE INSTALAÇÃO E USO - DataPyn IDE

## ✅ Passo a Passo para Começar

### 1️⃣ Instalação

```bash
# Windows - Opção Fácil
install.bat

# OU Manual
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
```

### 2️⃣ Verificar Instalação

```bash
python test_install.py
```

### 3️⃣ Executar

```bash
# Windows - Opção Fácil
run.bat

# OU Manual
venv\Scripts\activate
python main.py
```

## 📝 Primeira Vez no DataPyn

### Passo 1: Criar Conexão
1. Clique em "🔌 Nova Conexão"
2. Preencha:
   - Nome: "MinhaConexao"
   - Tipo: SQL Server / MySQL / PostgreSQL / MariaDB
   - Host: localhost (ou IP do servidor)
   - Porta: (automática baseada no tipo)
   - Database: nome_do_banco
   - Usuário: seu_usuario
   - Senha: sua_senha
3. Clique "Testar Conexão"
4. Se OK, clique "Conectar"

### Passo 2: Executar SQL
1. No **Editor SQL** (esquerda), digite:
   ```sql
   SELECT * FROM sua_tabela LIMIT 10
   ```
2. Pressione **F5**
3. Veja resultados na aba "📊 Resultados"
4. O resultado foi salvo como `df1`

### Passo 3: Manipular com Python
1. No **Editor Python** (direita), digite:
   ```python
   print(f"Total de linhas: {len(df)}")
   print(df.head())
   ```
2. Pressione **Shift+F5**
3. Veja output na aba "🖥️ Output Python"

### Passo 4: Explorar
- Execute mais queries (df2, df3, ...)
- Manipule os DataFrames com Pandas
- Exporte resultados (CSV/Excel)
- Veja variáveis na aba "💾 Variáveis em Memória"

## 🎯 Comandos Essenciais

### SQL
```sql
-- Ver tabelas
SELECT * FROM INFORMATION_SCHEMA.TABLES

-- Amostra de dados
SELECT TOP 100 * FROM tabela

-- Com filtro
SELECT * FROM vendas WHERE data >= '2025-01-01'

-- Agregação
SELECT categoria, SUM(valor) as total
FROM vendas
GROUP BY categoria
ORDER BY total DESC
```

### Python
```python
# Análise básica
print(df.info())
print(df.describe())

# Filtrar
filtrado = df[df['valor'] > 1000]

# Agrupar
por_categoria = df.groupby('categoria')['valor'].sum()

# Exportar
df.to_csv('resultado.csv', index=False)
```

## ⌨️ Atalhos para Memorizar

| Atalho | Ação |
|--------|------|
| **F5** | Executar SQL |
| **Shift+F5** | Executar Python |
| **Ctrl+/** | Comentar linha |
| **Ctrl+S** | Salvar arquivo |
| **Ctrl+O** | Abrir arquivo |
| **Ctrl+Shift+C** | Limpar resultados |
| **Ctrl+Enter** | Executar SQL (alt) |
| **Ctrl+Shift+Enter** | Executar Python (alt) |

## 🔍 Dicas Rápidas

1. **Selecione parte do SQL** e pressione F5 para executar apenas a seleção
2. **Use comentários** para salvar queries importantes
3. **Variável `df`** sempre aponta para o último resultado
4. **Limpe memória** periodicamente (Ctrl+Shift+C)
5. **Exporte resultados** antes de limpar

## 🐛 Problemas Comuns

### Erro ao conectar
- ✅ Verifique se o banco está rodando
- ✅ Confira host, porta, usuário e senha
- ✅ Teste conexão antes de conectar

### Interface não aparece
- ✅ Reinstale PyQt6: `pip install --force-reinstall PyQt6`
- ✅ Atualize drivers de vídeo
- ✅ Execute `test_install.py`

### "df not defined"
- ✅ Execute uma query SQL primeiro (F5)
- ✅ Verifique aba "Variáveis em Memória"

### Caracteres estranhos
- ✅ Use encoding UTF-8 ao exportar
- ✅ No CSV: `df.to_csv('arquivo.csv', encoding='utf-8-sig')`

## 📚 Documentação

- **README.md** - Documentação completa
- **QUICKSTART.md** - Guia rápido
- **DRIVERS.md** - Instalar drivers de banco
- **TROUBLESHOOTING.md** - Resolver problemas
- **TIPS.md** - Dicas avançadas
- **examples.sql** - Exemplos de SQL
- **examples.py** - Exemplos de Python

## 🎓 Aprendendo

### Dia 1: Básico
1. Conectar ao banco
2. Executar SELECT simples
3. Ver resultados
4. Exportar CSV

### Dia 2: Intermediário
1. Múltiplas queries
2. Manipular com Python
3. Filtros e agrupamentos
4. Salvar queries úteis

### Dia 3: Avançado
1. Comparar resultados (df1 vs df2)
2. Visualizações com matplotlib
3. Análises complexas
4. Automatizar tarefas

## ✨ Recursos Especiais

### 1. Múltiplos Resultados em Memória
```sql
-- Query 1
SELECT * FROM vendas_2024
```
```sql
-- Query 2
SELECT * FROM vendas_2025
```
```python
# Agora você tem df1 e df2!
print("2024:", df1['total'].sum())
print("2025:", df2['total'].sum())
```

### 2. Variáveis Persistentes
- Resultados NÃO se perdem entre execuções
- Manipule df1, df2, df3 quantas vezes quiser
- Limpe só quando decidir

### 3. Pandas Completo
```python
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt

# Tudo do Pandas está disponível!
```

## 🎯 Casos de Uso

### Análise Exploratória
```sql
SELECT * FROM dados LIMIT 1000
```
```python
print(df.describe())
print(df.info())
print(df['coluna'].value_counts())
```

### ETL Rápido
```sql
SELECT * FROM fonte
```
```python
# Transformar
df['nova_coluna'] = df['coluna'].str.upper()
df_limpo = df.dropna()

# Exportar
df_limpo.to_csv('processado.csv')
```

### Comparações
```sql
-- Antes
SELECT * FROM tabela WHERE data < '2025-01-01'
```
```sql
-- Depois
SELECT * FROM tabela WHERE data >= '2025-01-01'
```
```python
# Comparar
print("Antes:", len(df1))
print("Depois:", len(df2))
print("Crescimento:", len(df2) - len(df1))
```

## 💡 Lembre-se

- ✅ **F5** = SQL
- ✅ **Shift+F5** = Python
- ✅ **df** = último resultado
- ✅ **df1, df2...** = resultados anteriores
- ✅ Exportar antes de limpar!

---

**Divirta-se com o DataPyn!** 🚀🐍
