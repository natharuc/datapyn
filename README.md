<p align="center">
  <img src="source/src/assets/datapyn_logo.svg" alt="DataPyn Logo" width="180">
</p>

<h1 align="center">DataPyn</h1>

<p align="center">
  <strong>IDE moderna para analise de dados com SQL e Python integrados</strong>
</p>

<p align="center">
  <a href="#instalacao"><img src="https://img.shields.io/badge/version-1.13.0-blue.svg" alt="Version"></a>
  <img src="https://img.shields.io/badge/Python-3.12+-3776AB.svg?logo=python&logoColor=white" alt="Python">
  <img src="https://img.shields.io/badge/PyQt6-6.6+-41CD52.svg?logo=qt&logoColor=white" alt="PyQt6">
  <img src="https://img.shields.io/badge/Monaco_Editor-VS_Code-007ACC.svg?logo=visualstudiocode&logoColor=white" alt="Monaco">
  <img src="https://img.shields.io/badge/uv-package_manager-DE5FE9.svg" alt="uv">
  <img src="https://img.shields.io/badge/License-MIT-yellow.svg" alt="License">
</p>

<p align="center">
  <a href="#features">Features</a> |
  <a href="#instalacao">Instalacao</a> |
  <a href="#tecnologias">Tecnologias</a> |
  <a href="#atalhos">Atalhos</a> |
  <a href="#testes">Testes</a>
</p>

---

## Screenshots

<p align="center">
  <em>Interface moderna com blocos de codigo, resultados interativos e Object Explorer</em>
</p>

---

## Features

### Editor de Blocos
- **Block Editor** - Blocos de codigo independentes com linguagem por bloco (SQL/Python)
- **Monaco Editor** - Mesmo editor do VS Code com syntax highlighting
- **GitHub Copilot** - Sugestoes de codigo inline integradas (requer autenticacao)
- **SQL Autocomplete** - Completions inteligentes estilo SSMS (colunas, tabelas, aliases)
- **Conexao per-block** - Cada bloco pode usar uma conexao de banco diferente

### Multi-Database
- **SQL Server** - via pyodbc/pymssql
- **MySQL / MariaDB** - via mysql-connector e mariadb
- **PostgreSQL** - via psycopg2
- **SQLite** - nativo
- **Databricks** - via databricks-sql-connector

### Python Integrado
- **Cross-syntax** - Misture SQL e Python: `df = {{ SELECT * FROM users }}`
- **Pandas/Polars** - Manipule resultados SQL como DataFrames
- **Namespace compartilhado** - Variaveis Python disponiveis entre blocos
- **Gerenciador de pacotes** - Instale/atualize pacotes sem sair da IDE

### Produtividade
- **Importacao rapida** - Arraste CSV/JSON/XLSX para importar automaticamente
- **Exportar script** - Exporte analise como script Python standalone
- **Exportar para tabela** - Envie DataFrames diretamente para o banco
- **Workspaces** - Salve e restaure sessoes completas
- **Auto-update** - Atualizacoes automaticas via GitHub Releases

### Interface
- **Temas** - Dark/Light com Material Design
- **Object Explorer** - Navegue tabelas, colunas e stored procedures
- **Resultados interativos** - Tabelas com filtro, ordenacao e exportacao
- **Atalhos configuraveis** - Produtividade maxima

---

## Instalacao

O DataPyn usa [uv](https://docs.astral.sh/uv/) como gerenciador de pacotes (mais rapido que pip).

### Windows

```powershell
# 1. Clone o repositorio
git clone https://github.com/natharuc/datapyn.git
cd datapyn

# 2. Instale uv (se nao tiver)
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"

# 3. Crie o ambiente e instale dependencias
uv sync

# 4. Execute o DataPyn
uv run python source/main.py

# Ou use os scripts prontos:
scripts\install.bat   # Instala tudo
scripts\run.bat       # Executa
```

### Linux (Ubuntu/Debian)

```bash
# 1. Instale dependencias do sistema
sudo apt update
sudo apt install -y git python3.12 python3.12-venv libxcb-cursor0

# 2. Instale uv
curl -LsSf https://astral.sh/uv/install.sh | sh
source ~/.bashrc  # ou ~/.zshrc

# 3. Clone e entre no projeto
git clone https://github.com/natharuc/datapyn.git
cd datapyn

# 4. Crie o ambiente e instale dependencias
uv sync

# 5. Execute o DataPyn
uv run python source/main.py
```

### macOS

```bash
# 1. Instale Homebrew (se nao tiver)
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

# 2. Instale Python 3.12
brew install python@3.12

# 3. Instale uv
curl -LsSf https://astral.sh/uv/install.sh | sh
source ~/.zshrc

# 4. Clone e entre no projeto
git clone https://github.com/natharuc/datapyn.git
cd datapyn

# 5. Crie o ambiente e instale dependencias
uv sync

# 6. Execute o DataPyn
uv run python source/main.py
```

### Docker (Experimental)

```bash
# Build da imagem
docker build -t datapyn .

# Execute com display (Linux com X11)
docker run -it --rm \
  -e DISPLAY=$DISPLAY \
  -v /tmp/.X11-unix:/tmp/.X11-unix \
  -v $(pwd)/workspaces:/app/workspaces \
  datapyn
```

---

## Tecnologias

| Categoria | Tecnologia | Versao |
|-----------|------------|--------|
| **GUI** | PyQt6 + WebEngine | 6.6+ |
| **Editor** | Monaco (VS Code) | latest |
| **AI** | GitHub Copilot SDK | 0.1.20+ |
| **Database** | SQLAlchemy | 2.0+ |
| **Data** | Pandas, Polars, PyArrow | latest |
| **SQL Parsing** | sqlglot | 26.0+ |
| **Formatting** | Ruff, sqlparse | latest |
| **Package Manager** | uv (Astral) | latest |
| **Build** | PyInstaller | latest |

### Drivers de Banco Suportados

| Banco | Driver | Versao |
|-------|--------|--------|
| SQL Server | pyodbc / pymssql | 5.0+ / 2.2+ |
| MySQL | mysql-connector-python | 8.0+ |
| PostgreSQL | psycopg2-binary | 2.9+ |
| MariaDB | mariadb | 1.1+ |
| SQLite | nativo | - |
| Databricks | databricks-sql-connector | 3.0+ |

---

## Atalhos

| Atalho | Acao |
|--------|------|
| `Ctrl+Enter` | Executar bloco atual |
| `Shift+Enter` | Executar e avancar |
| `F5` | Executar SQL |
| `Shift+F5` | Executar Python |
| `Ctrl+N` | Nova aba |
| `Ctrl+W` | Fechar aba |
| `Ctrl+S` | Salvar workspace |
| `Ctrl+O` | Abrir workspace |
| `Ctrl+B` | Novo bloco |
| `Ctrl+,` | Configuracoes |
| `Ctrl+Shift+F` | Formatar codigo |
| `Escape` | Cancelar execucao |

> Atalhos sao configuraveis em **Configuracoes > Atalhos**

---

## Estrutura do Projeto

```
datapyn/
├── source/                  # Codigo-fonte principal
│   ├── main.py              # Entry point
│   └── src/
│       ├── core/            # Executor, sessoes, results
│       ├── database/        # Conectores SQL (SQLAlchemy)
│       ├── editors/         # Block editor, Monaco wrapper
│       ├── services/        # Import/export, packages, autocomplete
│       ├── ui/              # Main window, dialogs, components
│       ├── design_system/   # Tokens, temas, estilos
│       └── assets/          # Icones e recursos
├── tests/                   # 850+ testes automatizados
├── scripts/                 # Build, install, CI/CD
├── docs/                    # Documentacao tecnica
├── pyproject.toml           # Dependencias (uv/pip)
└── uv.lock                  # Lock file
```

---

## Testes

```bash
# Executar todos os testes
uv run pytest

# Modo rapido (sem testes visuais)
uv run pytest tests/ --ignore=tests/test_visual_manual.py --ignore=tests/test_gui.py -q

# Com cobertura
uv run pytest --cov=source/src --cov-report=html

# Teste especifico
uv run pytest tests/test_sql_autocomplete.py -v
```

> Testes usam `pytest-qt` com `QT_QPA_PLATFORM=offscreen` para rodar headless.

---

## Build (Executavel)

### Windows

```powershell
# Gerar .exe standalone
scripts\build.bat

# Saida: dist/DataPyn.exe
```

### Linux/macOS

```bash
# Gerar executavel
uv run pyinstaller scripts/datapyn.spec --clean

# Saida: dist/DataPyn
```

---

## Contribuindo

1. Fork o repositorio
2. Crie uma branch: `git checkout -b feat/minha-feature`
3. Commit suas mudancas: `git commit -m 'feat: minha feature'`
4. Push: `git push origin feat/minha-feature`
5. Abra um Pull Request

### Conventional Commits

Usamos [Conventional Commits](https://www.conventionalcommits.org/) para mensagens:

- `feat:` nova feature
- `fix:` correcao de bug
- `docs:` documentacao
- `refactor:` refatoracao
- `test:` testes
- `chore:` tarefas de manutencao

---

## Licenca

Este projeto esta sob a licenca **MIT**. Veja [LICENSE](LICENSE) para detalhes.

---

<p align="center">
  <sub>Feito com Python, cafe e IA</sub>
  <br>
  <sub>DataPyn - Analise de dados sem complicacao</sub>
</p>
