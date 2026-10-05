<p align="center">
  <img src="source/src/assets/datapyn_logo.svg" alt="DataPyn Logo" width="180">
</p>

<h1 align="center">DataPyn</h1>

<p align="center">
  <strong>IDE desktop para analise de dados com SQL e Python no mesmo fluxo de trabalho</strong>
</p>

<p align="center">
  <a href="https://github.com/natharuc/datapyn/releases/tag/tauri-v1.0.1"><img src="https://img.shields.io/badge/Tauri-1.0.1-blue.svg" alt="Version"></a>
  <img src="https://img.shields.io/badge/Python-3.12+-3776AB.svg?logo=python&logoColor=white" alt="Python">
  <img src="https://img.shields.io/badge/Tauri-2-24C8D8.svg?logo=tauri&logoColor=white" alt="Tauri">
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

`main` contem o aplicativo **Tauri**, com frontend React/TypeScript, host Rust e kernels Python por sessao. A distribuicao PyQt6 permanece historica, com versao e canal de atualizacao independentes.

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
- **Auto-update** assinado via canal Tauri no Windows, Linux e macOS

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

Instaladores Tauri: [release 1.0.1](https://github.com/natharuc/datapyn/releases/tag/tauri-v1.0.1). Os arquivos seguem o nome `DataPyn-Tauri-<versao>-<plataforma>`. O link `releases/latest` permanece reservado ao PyQt6 historico.

| Sistema | Artefato | Notas |
|---------|----------|--------|
| Windows x64 | `*-windows-x86_64-setup.exe`, ZIP | Setup inclui WebView2 e prepara ODBC quando necessario |
| Linux amd64 | `*-linux-x86_64.deb`, AppImage, tar.gz | Base Ubuntu 22.04; atualizacao em copia gerenciada pelo usuario |
| macOS Apple Silicon | `*-darwin-aarch64.dmg` | Sem Developer ID, pode exigir liberacao em Privacidade e Seguranca |

O runtime Python e os drivers Python acompanham os pacotes. Requisitos de drivers nativos, armazenamento e atualizacao: [distribuicao Tauri](docs/TAURI_DISTRIBUTION.md).

### Distribuicao historica (PyQt6)

Os pacotes abaixo pertencem ao canal PyQt6 historico e usam os tags `vX.Y.Z`.
Seus nomes e requisitos AppImage sao independentes dos pacotes Tauri acima.

| Sistema | Rótulo do artefato | Nome e instalação |
|---------|---------------------|-------------------|
| Linux x86_64/amd64 — Debian/Ubuntu | `Ubuntu/Debian (.deb)` | Ubuntu/Debian 22.04+ — `datapyn_VERSION_amd64.deb` — `sudo apt install ./datapyn_VERSION_amd64.deb` |
| Linux x86_64 — Fedora/RHEL/openSUSE | `Fedora/RHEL/openSUSE (.rpm)` | `datapyn-VERSION-1.x86_64.rpm` — `sudo dnf install ./datapyn-VERSION-1.x86_64.rpm` ou `sudo zypper install ./datapyn-VERSION-1.x86_64.rpm` |
| Linux x86_64 — Arch/Manjaro | `Arch/Manjaro (.pkg.tar.zst)` | `datapyn-VERSION-1-x86_64.pkg.tar.zst` — `sudo pacman -U ./datapyn-VERSION-1-x86_64.pkg.tar.zst` |
| Linux x86_64 — portátil | `Universal Linux (AppImage, FUSE3)` | `DataPyn-VERSION-x86_64.AppImage` |
| Linux x86_64 — fallback | `Other Linux (.tar.gz)` | `DataPyn-VERSION-linux-x86_64.tar.gz` |

Nos nomes versionados, `VERSION` é substituído pela versão da release (por exemplo, `1.57.0`). A
primeira arquitetura Linux publicada é **x86_64** (chamada **amd64** no nome do pacote Debian);
“Universal Linux” descreve o formato AppImage, não suporte a outras arquiteturas ou a qualquer
host Linux.

Para o AppImage, o caminho normal usa **FUSE3** e `fusermount3`. Depois do download, torne o
arquivo executável e inicie-o:

```bash
chmod +x DataPyn-VERSION-x86_64.AppImage
./DataPyn-VERSION-x86_64.AppImage
```

Se a montagem normal não estiver disponível, use o modo extract-and-run ou escolha um pacote
nativo/tarball:

```bash
./DataPyn-VERSION-x86_64.AppImage --appimage-extract-and-run
```

O AppImage não requer um pacote de FUSE legado. O tarball é um fallback manual:

```bash
tar -xzf DataPyn-VERSION-linux-x86_64.tar.gz
./DataPyn/DataPyn
```

Em uma referencia historica PyQt6, `scripts/linux/install.sh` instala dependencias
de sistema (Qt, ODBC, libpq, etc.) quando necessario. Empacotar os artefatos Linux
apos PyInstaller: `bash scripts/linux/package.sh <version>` (requer `fpm`). O
comando gera `.deb`, `.rpm`, `.pkg.tar.zst`, AppImage e tar.gz para x86_64, alem do
manifesto `DataPyn-linux-artifacts.json` e `SHA256SUMS`. Dry-run no CI: Actions →
**Build Linux Installers (dry run)**, selecionando uma referencia historica explicita.

No macOS Apple Silicon, o pacote historico e `DataPyn-VERSION-macos-arm64.dmg`;
`VERSION` corresponde a release PyQt6. Esse arquivo permanece separado do DMG Tauri.

### Desenvolvimento

**Desenvolvedores** — fluxo Tauri em `main`:

Prerequisitos: Node.js **22**, Rust **1.90+**, Python **3.12+**, [uv](https://docs.astral.sh/uv/) e dependencias nativas da plataforma descritas em [AGENTS.md](AGENTS.md).

```bash
git clone https://github.com/natharuc/datapyn.git
cd datapyn
uv sync --dev --frozen
npm --prefix desktop ci
npm --prefix desktop run desktop:dev
```

O PyQt6 retido em `source/main.py`, `scripts/install.bat`, `scripts/run.bat` e `scripts/linux/` destina-se a manutencao historica em uma referencia explicita. Esses scripts nao sao o fluxo de desenvolvimento ou publicacao de `main`.

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
├── desktop/
│   ├── src/                 # React, Monaco, resultados e estado da UI
│   └── src-tauri/           # Host Rust, integracoes nativas e updater
├── source/
│   ├── datapyn_runtime/     # Supervisor e kernels Python sem Qt
│   ├── main.py             # Entry point PyQt historico
│   └── src/
│       ├── core/            # Sessoes, executor, resultados
│       ├── database/        # Conectores SQLAlchemy
│       ├── editors/           # Blocos, Monaco, autocomplete
│       ├── services/
│       │   ├── pynia/         # Agente, provedores, ferramentas
│       │   └── copilot/     # SDK / LSP Copilot
│       ├── ui/                # Janela principal e componentes
│       └── design_system/     # Tokens e temas
├── runtime_tests/           # Contratos do runtime Tauri
├── tests/                   # Suite historica PyQt (pytest-qt)
├── scripts/tauri/           # Desenvolvimento, build e distribuicao Tauri
├── docs/                    # Notas tecnicas internas
├── pyproject.toml
└── uv.lock
```

---

## Tecnologias

| Area | Stack |
|------|--------|
| GUI | Tauri 2, Rust, React, TypeScript |
| Editor | Monaco |
| Dados | Pandas, Polars, PyArrow, matplotlib |
| SQL | SQLAlchemy, sqlglot, sqlparse |
| IA | Pynia (multi-provedor), github-copilot-sdk |
| Build | Tauri, PyInstaller (sidecar Python), uv, npm, Cargo |

---

## Testes

```bash
npm --prefix desktop test
npm --prefix desktop run build
uv run pytest -c runtime_tests/pytest.ini runtime_tests -q
node scripts/tauri/release.mjs verify-version tauri-v1.0.1

# Contratos Rust (a partir de desktop/src-tauri)
cargo fmt --check
cargo test --locked
```

A suite historica `uv run pytest tests/` permanece separada; os testes Qt usam `QT_QPA_PLATFORM=offscreen` no CI.

---

## Build (executavel)

```bash
npm --prefix desktop run desktop:build -- --no-bundle
# Saida nativa: desktop/src-tauri/target/release/
```

Instaladores assinados e requisitos por plataforma: [distribuicao](docs/TAURI_DISTRIBUTION.md) e [release](docs/TAURI_RELEASE.md). Um push em `main` publica a versao dos manifests quando o tag `tauri-vX.Y.Z` ainda nao existe, apos validar as tres plataformas. A branch de migracao continua como dry run; tags Tauri e despacho manual tambem sao suportados. A versao Tauri e atualizada explicitamente, sem bump automatico por tipo de commit.

Os scripts `scripts/build.bat` e `scripts/datapyn.spec` permanecem para builds historicos PyQt6.

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
