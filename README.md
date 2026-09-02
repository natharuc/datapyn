<p align="center">
  <img src="source/src/assets/datapyn_logo.svg" alt="DataPyn Logo" width="180">
</p>

<h1 align="center">DataPyn</h1>

<p align="center">
  <strong>IDE desktop para analise de dados com SQL e Python no mesmo fluxo de trabalho</strong>
</p>

<p align="center">
  <a href="https://github.com/natharuc/datapyn/releases/latest"><img src="https://img.shields.io/badge/version-1.36.1-blue.svg" alt="Version"></a>
  <img src="https://img.shields.io/badge/Python-3.12+-3776AB.svg?logo=python&logoColor=white" alt="Python">
  <img src="https://img.shields.io/badge/PyQt6-6.6+-41CD52.svg?logo=qt&logoColor=white" alt="PyQt6">
  <img src="https://img.shields.io/badge/Monaco-VS_Code-007ACC.svg?logo=visualstudiocode&logoColor=white" alt="Monaco">
  <img src="https://img.shields.io/badge/uv-package_manager-DE5FE9.svg" alt="uv">
  <img src="https://img.shields.io/badge/License-MIT-yellow.svg" alt="License">
</p>

<p align="center">
  <a href="#recursos">Recursos</a> |
  <a href="#pynia">Pynia</a> |
  <a href="#instalacao">Instalacao</a> |
  <a href="#atalhos">Atalhos</a> |
  <a href="#testes">Testes</a>
</p>

---

## O que e o DataPyn

O DataPyn e uma IDE focada em **consultas, pipelines e analise** contra bancos reais. Cada aba de sessao combina:

- **Blocos SQL e Python** independentes (estilo notebook, com editor Monaco)
- **Resultados** em grade, graficos e exportacao
- **Pynia**, assistente com contexto da sessao (schema, blocos, resultados e selecao)

Fluxo tipico: executar SQL, materializar o resultado como DataFrame nomeado e continuar em Python no bloco seguinte — sem sair do editor.

---

## Recursos

### Editor de blocos

- Blocos **SQL** e **Python** com barra de controle, execucao individual ou em fila
- **Monaco Editor** (mesmo nucleo do VS Code) com syntax highlighting
- **Autocomplete SQL** offline (tabelas, colunas, aliases) e suporte a schema por conexao
- **Conexao por bloco** — cada bloco SQL pode usar servidor/banco diferentes
- **Parametros SQL** (`@nome`) com painel lateral de definicao
- Formatacao com **Ruff** (Python) e **sqlparse** (SQL)

### Bancos suportados

| Banco | Driver |
|-------|--------|
| SQL Server | pyodbc / pymssql |
| PostgreSQL | psycopg2 |
| MySQL | mysql-connector-python |
| MariaDB | PyMySQL |
| SQLite | nativo |
| Databricks | databricks-sql-connector |

### Python e resultados

- Resultados SQL expostos no namespace Python (ex.: `df = result_sql` apos um bloco com saida nomeada)
- **Pandas**, **Polars** e visualizacoes (**matplotlib**) na aba de resultados
- **Gerenciador de pacotes** integrado (instalar dependencias sem sair da IDE)
- Importacao por arrastar **CSV / JSON / XLSX**; exportar analise como script `.py` standalone

### Produtividade

- **Workspaces** (`.dpw`) — sessoes, conexoes, blocos e estado da UI
- **Object Explorer** — tabelas, colunas e procedures da conexao ativa
- **Timer por aba** — reexecucao periodica dos blocos da sessao
- **Notificacoes por aba** — templates com referencias ao ultimo resultado (`{{result[0][0]}}`)
- **Auto-update** via GitHub Releases (instalador Windows)

### Interface

- Temas **claro / escuro** (design tokens centralizados)
- Resultados com filtro, formatacao de colunas e abas de grafico
- Atalhos configuraveis em **Configuracoes > Atalhos**

---

## Pynia

**Pynia** e o painel de assistente integrado ao DataPyn (nao e um chat generico). Ele enxerga a sessao ativa e pode, via ferramentas, inspecionar blocos, executar SQL/Python, editar codigo, consultar schema e gerar graficos.

### Conectores (Configuracoes > Pynia)

| Provedor | Uso |
|----------|-----|
| **GitHub Copilot** | Login por device code + CLI `gh` |
| **OpenAI** | API key + modelos da conta |
| **Anthropic** | API key + modelos Claude |
| **OpenRouter** | API key + catalogo agregado |

Tambem ha **completions inline** no editor (ghost text) quando o conector Copilot ou Pynia estiver configurado.

> Uso de LLM e cobrado pelo provedor escolhido (assinatura Copilot ou creditos de API).

Site e documentacao publica: [datapyn.page](https://datapyn.page)

---

## Instalacao

Instaladores oficiais: [datapyn.page/downloads.html](https://datapyn.page/downloads.html) ou [GitHub Releases](https://github.com/natharuc/datapyn/releases/latest).

| Sistema | Artefato | Notas |
|---------|----------|--------|
| Windows x64 | `DataPyn-Setup.exe` | Instala em `%LOCALAPPDATA%\DataPyn` |
| Linux amd64 | `datapyn_amd64.deb` | Ubuntu/Debian 22.04+. Outras distros: `DataPyn-linux-x86_64.tar.gz` |
| macOS Apple Silicon | `DataPyn-macos-arm64.dmg` | Unsigned — no Gatekeeper use **Open** no menu de contexto ou `xattr -cr /Applications/DataPyn.app` |

SQL Server no Linux: use o driver **pymssql** (FreeTDS no wheel). `pyodbc` exige `unixodbc` + driver Microsoft/FreeTDS no sistema.

**Desenvolvedores** (Python **3.12+**, [uv](https://docs.astral.sh/uv/)):

### Windows

```powershell
git clone https://github.com/natharuc/datapyn.git
cd datapyn
scripts\install.bat
scripts\run.bat
```

Build the Windows setup helper locally: `uv run pyinstaller installer/datapyn_setup.spec --clean`

### Linux (Ubuntu/Debian)

```bash
git clone https://github.com/natharuc/datapyn.git
cd datapyn
chmod +x scripts/linux/install.sh scripts/linux/run.sh
./scripts/linux/install.sh
./scripts/linux/run.sh
```

O `install.sh` instala dependencias de sistema (Qt, ODBC, libpq, etc.) quando necessario.

Empacotar `.deb` apos PyInstaller: `bash scripts/linux/package.sh <version>` (requer `fpm`). Dry-run no CI: Actions → **Build Linux Installers (dry run)**.

### macOS

```bash
brew install python@3.12
git clone https://github.com/natharuc/datapyn.git
cd datapyn
chmod +x scripts/linux/install.sh scripts/linux/run.sh
./scripts/linux/install.sh
./scripts/linux/run.sh
```

### Docker (experimental)

```bash
docker build -t datapyn .
docker run -it --rm \
  -e DISPLAY=$DISPLAY \
  -v /tmp/.X11-unix:/tmp/.X11-unix \
  -v $(pwd)/workspaces:/app/workspaces \
  datapyn
```

---

## Atalhos (padrao)

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

Atalhos editaveis em **Configuracoes > Atalhos**.

---

## Estrutura do projeto

```
datapyn/
├── source/
│   ├── main.py
│   └── src/
│       ├── core/            # Sessoes, executor, resultados
│       ├── database/        # Conectores SQLAlchemy
│       ├── editors/           # Blocos, Monaco, autocomplete
│       ├── services/
│       │   ├── pynia/         # Agente, provedores, ferramentas
│       │   └── copilot/     # SDK / LSP Copilot
│       ├── ui/                # Janela principal e componentes
│       └── design_system/     # Tokens e temas
├── tests/                   # Suite pytest (pytest-qt)
├── scripts/                 # install, build, CI
├── docs/                    # Notas tecnicas internas
├── pyproject.toml
└── uv.lock
```

---

## Tecnologias

| Area | Stack |
|------|--------|
| GUI | PyQt6, Qt WebEngine, QtAwesome |
| Editor | Monaco (WebView) |
| Dados | Pandas, Polars, PyArrow, matplotlib |
| SQL | SQLAlchemy, sqlglot, sqlparse |
| IA | Pynia (multi-provedor), github-copilot-sdk |
| Build | PyInstaller, uv |

---

## Testes

```bash
uv run pytest

# Rapido (sem testes GUI manuais)
uv run pytest tests/ \
  --ignore=tests/test_visual_manual.py \
  --ignore=tests/test_gui.py -q

# Cobertura
uv run pytest --cov=source/src --cov-report=html
```

Testes Qt usam `QT_QPA_PLATFORM=offscreen` no CI.

---

## Build (executavel)

### Windows

```powershell
scripts\build.bat
# Saida: dist/DataPyn.exe
```

### Linux / macOS

```bash
uv run pyinstaller scripts/datapyn.spec --clean
# Saida: dist/DataPyn
```

---

## Contribuindo

1. Fork o repositorio
2. Branch: `git checkout -b feat/minha-feature`
3. Commit no padrao [Conventional Commits](https://www.conventionalcommits.org/) (`feat:`, `fix:`, `docs:`, …)
4. Pull Request

---

## Licenca

Projeto sob licenca **MIT** — veja [LICENSE](LICENSE).

---

<p align="center">
  <sub>DataPyn — SQL, Python e Pynia no mesmo lugar.</sub>
</p>
