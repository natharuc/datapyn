# DataPyn IDE

**IDE moderna para consultas SQL com manipulação Python integrada**

DataPyn é uma IDE completa desenvolvida em Python para trabalhar com bancos de dados SQL. O diferencial é que após executar suas queries SQL, você pode manipular os resultados usando código Python, e os dados ficam em memória até você decidir limpar.

## 🌟 Características

### Suporte a Múltiplos Bancos de Dados
- ✅ **SQL Server** (via pyodbc/pymssql) - com suporte a Windows Authentication
- ✅ **MySQL** (via PyMySQL)
- ✅ **MariaDB** (via mariadb connector)
- ✅ **PostgreSQL** (via psycopg2)

### Interface Moderna
- 🎨 Tema escuro (estilo VS Code)
- 📝 Editor SQL com syntax highlighting estilo Monaco
- 🐍 Editor Python integrado com syntax highlighting
- 📊 Visualizador de resultados em tabela
- 💾 Painel de variáveis em memória
- 🔌 Gerenciador de conexões
- ⚙️ Ícones profissionais (Font Awesome)

### Funcionalidades Principais
- **Execução de SQL**: Escreva e execute queries SQL (F5)
- **Manipulação Python**: Use Python para processar resultados (Shift+F5)
- **Sintaxe Mista**: Use `clientes = query("SELECT * FROM clientes")` no editor Python!
- **Resultados Persistentes**: DataFrames ficam em memória (df1, df2, df3...)
- **Exportação**: Exporte resultados para CSV ou Excel
- **Atalhos Configuráveis**: Customize seus atalhos de teclado (Ctrl+,)
- **Windows Authentication**: Conecte ao SQL Server sem senha
- **Histórico**: Mantenha histórico de queries e resultados

## 🚀 Instalação

### Pré-requisitos
- Python 3.8 ou superior
- Windows (testado no Windows, mas pode funcionar em outros sistemas)

### Passo a Passo

1. **Clone ou baixe o projeto**
```bash
cd c:\nac\datapyn
```

2. **Crie um ambiente virtual (recomendado)**
```bash
python -m venv venv
venv\Scripts\activate
```

3. **Instale as dependências**
```bash
pip install -r requirements.txt
```

4. **Execute a aplicação**
```bash
python main.py
```

## 📖 Como Usar

### 1. Conectar ao Banco

1. Clique em **"🔌 Nova Conexão"** na toolbar ou menu
2. Preencha os dados da conexão:
   - Nome da Conexão
   - Tipo de Banco (SQL Server, MySQL, MariaDB, PostgreSQL)
   - Host
   - Porta
   - Database
   - Usuário e Senha
3. Clique em **"Testar Conexão"** para validar
4. Clique em **"Conectar"**

### 2. Executar SQL

1. Escreva sua query SQL no **Editor SQL** (painel esquerdo superior)
2. Pressione **F5** ou clique em **"▶️ Executar SQL"**
3. Os resultados aparecem na aba **"📊 Resultados"**
4. O DataFrame é automaticamente salvo em memória como `df1`, `df2`, etc.

```sql
SELECT * FROM Clientes WHERE Ativo = 1
```

### 3. Manipular com Python

1. Após executar SQL, use o **Editor Python** (painel direito superior)
2. Use as variáveis `df`, `df1`, `df2`... para acessar os resultados
3. Pressione **Shift+F5** para executar o código Python
4. O output aparece na aba **"🖥️ Output Python"**

```python
# df sempre aponta para o último resultado
print(f"Total de registros: {len(df)}")

# Filtrar dados
clientes_sp = df[df['Estado'] == 'SP']
print(f"Clientes de SP: {len(clientes_sp)}")

# Agrupar
por_estado = df.groupby('Estado').size()
print(por_estado)

# Criar novo DataFrame (fica em memória!)
novos_clientes = df[df['DataCadastro'] > '2025-01-01']
```

### 4. Usar Sintaxe Mista (Novo! 🎉)

**A grande novidade:** Você pode escrever SQL diretamente no editor Python!

```python
# Em vez de trocar entre editores, faça tudo no Python:
clientes = query("SELECT * FROM clientes WHERE ativo = 1")
print(f"Total: {len(clientes)}")

# Múltiplas queries
vendas = query("SELECT * FROM vendas WHERE data >= '2024-01-01'")
produtos = query("SELECT * FROM produtos")

# Manipule normalmente com Pandas
total_por_produto = vendas.groupby('produto_id')['valor'].sum()

# Execute INSERT/UPDATE/DELETE
linhas = execute("UPDATE clientes SET ultimo_acesso = NOW() WHERE id = 123")
print(f"{linhas} linhas atualizadas")
```

Veja mais exemplos em [examples_mixed.py](examples_mixed.py)

### 5. Visualizar Variáveis em Memória

- Acesse a aba **"Variáveis em Memória"**
- Veja todas as variáveis salvas, com informações de:
  - Nome da variável
  - Número de linhas e colunas
  - Uso de memória
  - Data/hora de criação

### 6. Exportar Resultados

- Na aba de Resultados, use os botões:
  - **Exportar CSV**: Salva como arquivo CSV
  - **Exportar Excel**: Salva como arquivo XLSX
  - **Copiar**: Copia para área de transferência

### 7. Windows Authentication (SQL Server)

- Ao conectar ao SQL Server, marque **"Usar Windows Authentication"**
- Os campos de usuário e senha serão desabilitados
- A conexão usará suas credenciais do Windows

### 8. Configurar Atalhos

- Menu **Ferramentas > Configurações de Atalhos** (Ctrl+,)
- Personalize todos os atalhos de teclado
- Sistema detecta conflitos automaticamente

## ⌨️ Atalhos de Teclado

### Execução
- `F5` - Executar SQL
- `Shift+F5` - Executar Python
- `Ctrl+Shift+C` - Limpar resultados

### Edição
- `Ctrl+/` - Comentar/Descomentar linha
- `Ctrl+S` - Salvar arquivo
- `Ctrl+O` - Abrir arquivo
- `Ctrl+N` - Novo arquivo

### Conexão
- `Ctrl+Shift+N` - Nova conexão

### Configurações
- `Ctrl+,` - Abrir configurações de atalhos

**Nota:** Todos os atalhos são configuráveis!

## 🔧 Configuração

### Conexões Salvas
As conexões são salvas em: `%USERPROFILE%\.datapyn\connections.json`

### Atalhos Personalizados
Os atalhos podem ser customizados em: `%USERPROFILE%\.datapyn\shortcuts.json`

## 📁 Estrutura do Projeto

```
datapyn/
├── main.py                 # Arquivo principal
├── requirements.txt        # Dependências
├── README.md              # Este arquivo
├── src/
│   ├── database/          # Módulos de conexão
│   │   ├── database_connector.py
│   │   └── connection_manager.py
│   ├── editors/           # Editores de código
│   │   ├── sql_editor.py
│   │   └── python_editor.py
│   ├── ui/                # Interface gráfica
│   │   ├── main_window.py
│   │   ├── connection_dialog.py
│   │   └── results_viewer.py
│   └── core/              # Funcionalidades core
│       ├── results_manager.py
│       └── shortcut_manager.py
├── config/                # Configurações
└── resources/             # Recursos (ícones, etc)
```

## 🎯 Casos de Uso

### 1. Análise Exploratória de Dados
```sql
-- Buscar dados
SELECT * FROM vendas WHERE ano = 2025
```
```python
# Análise rápida
print(df.describe())
print(df['categoria'].value_counts())
```

### 2. Transformação de Dados
```sql
SELECT * FROM pedidos
```
```python
# Transformar e filtrar
df['total'] = df['quantidade'] * df['preco']
df_grandes = df[df['total'] > 1000]
print(f"Pedidos grandes: {len(df_grandes)}")
```

### 3. Comparação entre Queries
```sql
-- Query 1: Vendas 2024
SELECT * FROM vendas WHERE ano = 2024
```
```sql
-- Query 2: Vendas 2025
SELECT * FROM vendas WHERE ano = 2025
```
```python
# Comparar resultados (df1 = 2024, df2 = 2025)
print("Vendas 2024:", df1['valor'].sum())
print("Vendas 2025:", df2['valor'].sum())
print("Crescimento:", ((df2['valor'].sum() / df1['valor'].sum()) - 1) * 100, "%")
```

### 4. Visualização de Dados
```python
import matplotlib.pyplot as plt

# Gráfico de barras
df.groupby('categoria')['valor'].sum().plot(kind='bar')
plt.title('Vendas por Categoria')
plt.show()
```

## 🛠️ Dependências Principais

- **PyQt6**: Framework de interface gráfica
- **QScintilla**: Editor de código com syntax highlighting
- **Pandas**: Manipulação de dados
- **SQLAlchemy**: Abstração de banco de dados
- **Drivers SQL**: pyodbc, pymysql, psycopg2, mariadb

## 🐛 Solução de Problemas

### Erro ao conectar SQL Server
- Certifique-se de ter o **ODBC Driver 17 for SQL Server** instalado
- Baixe em: https://learn.microsoft.com/en-us/sql/connect/odbc/download-odbc-driver-for-sql-server

### Erro ao importar matplotlib
- Instale: `pip install matplotlib`

### Interface não aparece corretamente
- Verifique se todas as dependências foram instaladas
- Tente reinstalar PyQt6: `pip install --force-reinstall PyQt6`

## 📝 Licença

Este projeto é de código aberto. Use como quiser!

## 🤝 Contribuindo

Contribuições são bem-vindas! Sinta-se livre para:
- Reportar bugs
- Sugerir novas funcionalidades
- Melhorar a documentação
- Enviar pull requests

## 📧 Contato

Para dúvidas ou sugestões, abra uma issue no repositório.

---

**DataPyn** - Desenvolvido com ❤️ em Python
