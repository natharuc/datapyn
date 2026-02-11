<p align="center">
  <img src="source/src/assets/datapyn_logo.svg" alt="DataPyn Logo" width="200">
</p>

<h1 align="center">DataPyn</h1>

<p align="center">
  <strong>IDE moderna para consultas SQL com Python integrado</strong>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.8+-blue.svg" alt="Python">
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
# 1. Crie um ambiente virtual
python -m venv .venv

# 2. Ative o ambiente
# Windows:
.venv\Scripts\activate
# Linux/Mac:
source .venv/bin/activate

# 3. Instale as dependências
pip install -r requirements.txt

# 4. Execute
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

## Estrutura do Projeto

```
datapyn/
├── source/              # Código-fonte
│   ├── main.py          # Ponto de entrada
│   └── src/             # Módulos da aplicação
│       ├── core/        # Lógica central
│       ├── database/    # Conectores de banco
│       ├── editors/     # Editores de código
│       ├── services/    # Serviços
│       ├── ui/          # Interface gráfica
│       └── assets/      # Ícones e recursos
├── tests/               # Testes automatizados
├── scripts/             # Scripts de build/install
├── docs/                # Documentação
└── requirements.txt     # Dependências
```

---

## Testes

```bash
# Executar todos os testes (execucao paralela automatica)
pytest

# Executar testes sequencialmente (sem paralelizacao)
pytest -n 0

# Com cobertura
pytest --cov=source/src --cov-report=html

# Testes especificos
pytest tests/test_mixed_executor.py -v

# Executar apenas testes unitarios rapidos
pytest -m unit

# Executar testes de integracao
pytest -m integration

# Pular testes lentos
pytest -m "not slow"
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
