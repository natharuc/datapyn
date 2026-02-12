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
  <img src="https://img.shields.io/badge/License-MIT-yellow.svg" alt="License">
</p>

---

## Features

- **Multi-database** — SQL Server, MySQL, PostgreSQL, MariaDB, SQLite
- **Python integrado** — Manipule resultados SQL com Pandas diretamente
- **Importação rápida** — Arraste arquivos CSV/JSON/XLSX para importar automaticamente
- **Visualização** — Tabelas interativas com exportação para Excel/CSV
- **Temas** — Interface moderna com Material Design (dark/light)
- **Atalhos** — Produtividade máxima com atalhos de teclado
- **Workspaces** — Salve e restaure suas sessões de trabalho
- **Seguro** — Credenciais armazenadas com criptografia

---

## Instalação

### Windows

```bash
# 1. Clone o repositório
git clone https://github.com/seu-usuario/datapyn.git
cd datapyn

# 2. Execute o instalador
scripts\install.bat

# 3. Inicie o DataPyn
scripts\run.bat
```

### Manual (Linux/Mac/Windows)

```bash
# 1. Instale o Poetry (se ainda nao tiver)
pip install poetry

# 2. Instale as dependencias (cria o .venv automaticamente)
poetry install

# 3. Execute
poetry run python source/main.py

# Ou ative o shell do Poetry e execute diretamente
poetry shell
python source/main.py
```

---

## Atalhos de Teclado

| Atalho | Ação |
|--------|------|
| `F5` | Executar SQL |
| `Shift+F5` | Executar Python |
| `Ctrl+Enter` | Executar bloco atual |
| `Ctrl+N` | Nova aba |
| `Ctrl+W` | Fechar aba |
| `Ctrl+S` | Salvar workspace |
| `Ctrl+O` | Abrir workspace |
| `Ctrl+,` | Configurações |

---

## Documentacao

- [Guia de Geracao do Instalador MSI](docs/BUILD_MSI.md)
- [Guia de Otimizacao de Testes](docs/TEST_OPTIMIZATION.md)

---

## Estrutura do Projeto

```
datapyn/
├── source/                  # Codigo-fonte
│   ├── main.py              # Ponto de entrada
│   └── src/                 # Modulos da aplicacao
│       ├── core/            # Logica central
│       ├── database/        # Conectores de banco
│       ├── editors/         # Editores de codigo
│       ├── services/        # Servicos
│       ├── ui/              # Interface grafica
│       └── assets/          # Icones e recursos
├── tests/                   # Testes automatizados
├── scripts/                 # Scripts de build/install
├── docs/                    # Documentacao
├── pyproject.toml           # Configuracao do projeto e dependencias (Poetry)
└── poetry.lock              # Lock file de dependencias
```

---

## Testes

```bash
# Instalar dependencias de teste
poetry install --with test

# Executar todos os testes (execucao paralela automatica)
poetry run pytest

# Executar testes sequencialmente (sem paralelizacao)
poetry run pytest -n 0

# Com cobertura
poetry run pytest --cov=source/src --cov-report=html

# Testes especificos
poetry run pytest tests/test_mixed_executor.py -v

# Executar apenas testes unitarios rapidos
poetry run pytest -m unit

# Executar testes de integracao
poetry run pytest -m integration

# Pular testes lentos
poetry run pytest -m "not slow"
```

**Nota**: Os testes estao configurados para execucao paralela automatica usando `pytest-xdist`, o que reduz significativamente o tempo de execucao.


---

## Build (Executavel)

### Opcoes de Build

```bash
# Build interativo - escolha entre EXE, MSI ou ambos
scripts\build.bat

# Gerar apenas executavel (PyInstaller - rapido)
scripts\build_exe.bat

# Gerar apenas instalador MSI (cx_Freeze - completo)
scripts\build_msi.bat
```

### Resultado do Build

- **EXE**: Executavel standalone em `dist/DataPyn/DataPyn.exe`
- **MSI**: Instalador Windows em `dist/DataPyn-1.0.0-win64.msi`

---

## Licença

Este projeto está sob a licença MIT. Veja o arquivo [LICENSE](LICENSE) para mais detalhes.

---

<p align="center">
  Feito com amor, café e IA
  <br>
  <sub>Com carinho por um humano incrível e seu copiloto</sub>
</p>
