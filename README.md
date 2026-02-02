# DataPyn

**DataPyn** é uma IDE desktop para análise de dados que combina SQL e Python em um único ambiente integrado. Execute queries SQL, processe dados com Python/Pandas e visualize resultados em tempo real.

## Características Principais

- **Execução Híbrida**: Suporte para SQL puro, Python puro ou sintaxe mista (Python + SQL)
- **Multi-SGBD**: Conexão com SQL Server, MySQL, MariaDB e PostgreSQL
- **Interface Material Design**: Tema dark moderno com componentes profissionais
- **Editor de Código**: Syntax highlighting para Python e SQL com números de linha
- **Notebooks**: Sistema de blocos de código executáveis independentes
- **Resultados Interativos**: Visualização de dados em grid, exportação para CSV/Excel
- **Gestão de Conexões**: Salve e gerencie múltiplas conexões de banco de dados

## Requisitos do Sistema

- **Sistema Operacional**: Windows 10/11
- **Python**: 3.12 ou superior
- **Memória RAM**: 4 GB mínimo (8 GB recomendado)
- **Espaço em Disco**: 500 MB para instalação

## Instalação

### 1. Clone o repositório

```bash
git clone https://github.com/seu-usuario/datapyn.git
cd datapyn
```

### 2. Crie um ambiente virtual

```bash
python -m venv .venv
.venv\Scripts\activate
```

### 3. Instale as dependências

```bash
pip install -r requirements.txt
```

### 4. Configure os drivers de banco de dados

**SQL Server**: Instale o [ODBC Driver 17 for SQL Server](https://docs.microsoft.com/en-us/sql/connect/odbc/download-odbc-driver-for-sql-server)

**MySQL/MariaDB**: Incluído via pymysql e mariadb connector

**PostgreSQL**: Incluído via psycopg2

### 5. Execute o DataPyn

```bash
python main.py
```

Ou use o script de conveniência:

```bash
run.bat
```

## Uso Rápido

### Conectando a um Banco de Dados

1. Clique no botão **Nova Conexão** na barra de ferramentas
2. Preencha os dados de conexão:
   - Tipo de banco: SQL Server, MySQL, MariaDB ou PostgreSQL
   - Host e porta do servidor
   - Nome do banco de dados
   - Credenciais de autenticação
3. Clique em **Testar Conexão** para validar
4. Clique em **Conectar**

### Executando SQL

```sql
-- Selecione o modo SQL no dropdown do bloco
SELECT 
    produto,
    SUM(valor) AS total_vendas
FROM vendas
WHERE data_venda >= '2026-01-01'
GROUP BY produto
ORDER BY total_vendas DESC
```

Pressione **F5** ou **Ctrl+Enter** para executar.

### Executando Python

```python
# Selecione o modo Python no dropdown do bloco
import pandas as pd

# Acesse os resultados da última query SQL
df = resultados  # DataFrame com os dados

# Análise com pandas
media_vendas = df['total_vendas'].mean()
print(f"Média de vendas: R$ {media_vendas:,.2f}")

# Estatísticas descritivas
df.describe()
```

### Sintaxe Mista (Cross-Syntax)

```python
# Selecione o modo Cross-Syntax no dropdown do bloco

# SQL embutido em Python
query = """
    SELECT categoria, COUNT(*) as total
    FROM produtos
    WHERE ativo = 1
    GROUP BY categoria
"""

# Executa SQL e processa em Python
df = sql(query)
df['percentual'] = (df['total'] / df['total'].sum() * 100).round(2)
print(df)
```

## Exemplos de Uso

### Análise de Vendas

```sql
-- Query SQL para obter vendas do mês
USE vendas_db;

SELECT 
    v.data_venda,
    p.nome AS produto,
    v.quantidade,
    v.valor_unitario,
    (v.quantidade * v.valor_unitario) AS total
FROM vendas v
INNER JOIN produtos p ON v.produto_id = p.id
WHERE MONTH(v.data_venda) = MONTH(GETDATE())
ORDER BY v.data_venda DESC;
```

Em seguida, processe os dados em Python:

```python
# Análise com pandas
total_mes = df['total'].sum()
produto_mais_vendido = df.groupby('produto')['quantidade'].sum().idxmax()

print(f"Total do mês: R$ {total_mes:,.2f}")
print(f"Produto mais vendido: {produto_mais_vendido}")

# Visualização
import matplotlib.pyplot as plt
df.groupby('produto')['total'].sum().plot(kind='bar')
plt.title('Vendas por Produto')
plt.show()
```

### ETL com Múltiplas Queries

```sql
-- Criar tabela temporária
DROP TABLE IF EXISTS #analise_clientes;

SELECT 
    c.id,
    c.nome,
    COUNT(p.id) AS total_pedidos,
    SUM(p.valor) AS valor_total
INTO #analise_clientes
FROM clientes c
LEFT JOIN pedidos p ON c.id = p.cliente_id
WHERE p.data_pedido >= '2025-01-01'
GROUP BY c.id, c.nome;

-- Resultado final
SELECT 
    *,
    CASE 
        WHEN valor_total > 10000 THEN 'VIP'
        WHEN valor_total > 5000 THEN 'Premium'
        ELSE 'Regular'
    END AS categoria
FROM #analise_clientes
ORDER BY valor_total DESC;
```

## Atalhos de Teclado

| Atalho | Ação |
|--------|------|
| **F5** | Executar bloco atual |
| **Ctrl+Enter** | Executar bloco atual |
| **Shift+Enter** | Executar bloco atual |
| **Ctrl+N** | Novo bloco de código |
| **Ctrl+/** | Comentar/descomentar linha |
| **Ctrl+S** | Salvar workspace |
| **Ctrl+O** | Abrir workspace |

## Exportação de Dados

Os resultados podem ser exportados em múltiplos formatos:

- **CSV**: Arquivo de valores separados por vírgula
- **Excel**: Planilha XLSX com formatação
- **Clipboard**: Copiar para área de transferência (compatível com Excel)

Clique no botão de exportação na aba **Resultados** e selecione o formato desejado.

## Estrutura do Projeto

```
datapyn/
├── src/
│   ├── core/           # Lógica de execução e gerenciamento
│   ├── database/       # Conectores de banco de dados
│   ├── editors/        # Componentes de edição de código
│   └── ui/             # Interface gráfica (PyQt6)
├── config/             # Arquivos de configuração
├── tests/              # Testes automatizados
├── main.py             # Ponto de entrada da aplicação
├── requirements.txt    # Dependências Python
└── README.md           # Este arquivo
```

## Tecnologias Utilizadas

- **PyQt6**: Framework de interface gráfica
- **QScintilla**: Editor de código com syntax highlighting
- **SQLAlchemy**: ORM e engine de conexão SQL
- **Pandas**: Manipulação e análise de dados
- **qt-material**: Tema Material Design
- **qtawesome**: Ícones Material Design

## Desenvolvimento

### Executar Testes

```bash
pytest tests/ -v
```

### Executar com Debug

```bash
python main.py --debug
```

### Build Standalone (Executável)

```bash
build.bat
```

O executável será gerado em `dist/datapyn.exe`.

## Troubleshooting

### Erro de Conexão SQL Server

**Problema**: "ODBC Driver not found"

**Solução**: Instale o [ODBC Driver 17 for SQL Server](https://docs.microsoft.com/en-us/sql/connect/odbc/download-odbc-driver-for-sql-server)

### Erro ao Importar Pandas

**Problema**: "No module named 'pandas'"

**Solução**: Reinstale as dependências:
```bash
pip install --force-reinstall -r requirements.txt
```

### Interface não Aparece

**Problema**: Aplicação inicia mas janela não abre

**Solução**: Verifique a versão do Python (deve ser 3.12+) e reinstale PyQt6:
```bash
pip install --upgrade PyQt6 PyQt6-QScintilla
```

## Contribuindo

Contribuições são bem-vindas! Para contribuir:

1. Faça um fork do projeto
2. Crie uma branch para sua feature (`git checkout -b feature/nova-funcionalidade`)
3. Commit suas mudanças (`git commit -m 'Adiciona nova funcionalidade'`)
4. Push para a branch (`git push origin feature/nova-funcionalidade`)
5. Abra um Pull Request

## Licença

Este projeto está sob a licença MIT. Veja o arquivo `LICENSE` para mais detalhes.

## Suporte

Para reportar bugs ou sugerir melhorias, abra uma [issue](https://github.com/seu-usuario/datapyn/issues) no GitHub.

## Autores

Desenvolvido por [Seu Nome]

## Changelog

### Versão 1.0.0 (2026-02-01)
- Lançamento inicial
- Suporte para SQL Server, MySQL, MariaDB e PostgreSQL
- Editor de código com syntax highlighting
- Sistema de notebooks com blocos executáveis
- Tema Material Design dark
- Exportação de dados para CSV/Excel
- Gerenciamento de conexões
