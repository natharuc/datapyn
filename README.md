<p align="center">
  <img src="source/src/assets/datapyn_logo.svg" alt="DataPyn Logo" width="200">
</p>

<h1 align="center">DataPyn</h1>

<p align="center">
  <strong>IDE moderna para consultas SQL com Python integrado</strong>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.12+-blue.svg" alt="Python">
  <img src="https://img.shields.io/badge/PyQt6-6.6+-green.svg" alt="PyQt6">
  <img src="https://img.shields.io/badge/uv-package%20manager-blueviolet.svg" alt="uv">
  <img src="https://img.shields.io/badge/License-MIT-yellow.svg" alt="License">
</p>

---

## Features

- **Multi-database** -- SQL Server, MySQL, PostgreSQL, MariaDB, SQLite
- **Python integrado** -- Manipule resultados SQL com Pandas diretamente
- **Cross-syntax** -- Misture SQL e Python no mesmo bloco com `{{ SELECT ... }}`
- **Block Editor** -- Blocos de codigo independentes com linguagem por bloco
- **Conexao per-block** -- Cada bloco pode usar uma conexao de banco diferente
- **Importacao rapida** -- Arraste arquivos CSV/JSON/XLSX para importar automaticamente
- **Exportar script** -- Exporte sua analise como script Python standalone
- **Exportar para tabela** -- Exporte DataFrames diretamente para tabelas no banco
- **Gerenciador de pacotes** -- Instale/atualize pacotes Python sem sair da IDE
- **Visualizacao** -- Tabelas interativas com exportacao para Excel/CSV
- **Temas** -- Interface moderna com Material Design (dark/light)
- **Atalhos** -- Produtividade maxima com atalhos de teclado configuraveis
- **Workspaces** -- Salve e restaure suas sessoes de trabalho
- **Seguro** -- Credenciais armazenadas com criptografia

---

## Instalacao

O DataPyn usa [uv](https://docs.astral.sh/uv/) como gerenciador de pacotes e ambientes virtuais.

### Windows (automatico)

```bash
# 1. Clone o repositorio
git clone https://github.com/seu-usuario/datapyn.git
cd datapyn

# 2. Execute o instalador (instala uv se necessario)
scripts\install.bat

# 3. Inicie o DataPyn
scripts\run.bat
```

### Manual (Linux/Mac/Windows)

```bash
# 1. Instale o uv (caso nao tenha)
# Windows:
powershell -c "irm https://astral.sh/uv/install.ps1 | iex"
# Linux/Mac:
curl -LsSf https://astral.sh/uv/install.sh | sh

# 2. Clone e entre no projeto
git clone https://github.com/seu-usuario/datapyn.git
cd datapyn

# 3. Crie o ambiente e instale dependencias
uv sync

# 4. Execute
uv run python source/main.py
```

### Dependencias de desenvolvimento

```bash
# Instalar com dependencias de dev (testes, build)
uv sync --dev

# Executar testes
uv run pytest
```

---

## Atalhos de Teclado

| Atalho | Acao |
|--------|------|
| `F5` | Executar SQL |
| `Shift+F5` | Executar Python |
| `Ctrl+Enter` | Executar bloco atual |
| `Ctrl+N` | Nova aba |
| `Ctrl+W` | Fechar aba |
| `Ctrl+S` | Salvar workspace |
| `Ctrl+O` | Abrir workspace |
| `Ctrl+,` | Configuracoes |

---

## Estrutura do Projeto

```
datapyn/
├── source/                  # Codigo-fonte
│   ├── main.py              # Ponto de entrada
│   └── src/
│       ├── core/            # Logica central (executor, sessoes, results)
│       ├── database/        # Conectores e gerenciador de conexoes
│       ├── editors/         # Block editor, code editor, Monaco
│       ├── services/        # Servicos (import, export, packages, panels)
│       ├── ui/              # Interface grafica (main_window, dialogs, components)
│       └── assets/          # Icones e recursos
├── tests/                   # Testes automatizados (850+)
├── scripts/                 # Scripts de build/install
├── docs/                    # Documentacao
├── pyproject.toml           # Dependencias e config do projeto
└── uv.lock                  # Lock file de dependencias
```

---

## Testes

```bash
# Executar todos os testes
uv run pytest

# Com cobertura
uv run pytest --cov=source/src --cov-report=html

# Testes especificos
uv run pytest tests/test_mixed_executor.py -v

# Testes rapidos (sem testes visuais)
uv run pytest tests/ --ignore=tests/test_visual_manual.py --ignore=tests/test_gui.py -q
```

Os testes usam `pytest-qt` para testar a interface PyQt6 em modo headless (`QT_QPA_PLATFORM=offscreen`), com timeout de 30s por teste para evitar travamentos.

---

## Build (Executavel)

```bash
# Gerar executavel standalone
scripts\build.bat

# O executavel sera gerado em dist/DataPyn.exe
```

---

## Licenca

Este projeto esta sob a licenca MIT. Veja o arquivo [LICENSE](LICENSE) para mais detalhes.

---

<p align="center">
  Feito com amor, cafe e IA
  <br>
  <sub>Com carinho por um humano incrivel e seu copiloto</sub>
</p>
