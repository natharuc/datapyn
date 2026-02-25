#!/bin/bash

echo "========================================"
echo "  DataPyn IDE - Script de Instalacao"
echo "========================================"
echo ""

# Cores para output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Navegar para a raiz do projeto
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR/../.." || exit 1

# Instalar dependencias do sistema (requer sudo)
echo -e "${YELLOW}[INFO]${NC} Verificando dependencias do sistema..."

if command -v apt-get &> /dev/null; then
    MISSING_PKGS=()
    REQUIRED_PKGS=(
        "build-essential"
        "python3-dev"
        "python3-venv"
        "libxcb-cursor0"
        "libxcb-xinerama0"
        "libxkbcommon0"
        "libgl1"
        "libegl1"
        "libpq-dev"
        "unixodbc-dev"
        "curl"
        "xclip"              # Clipboard support for X11
        "wl-clipboard"        # Clipboard support for Wayland
    )

    for pkg in "${REQUIRED_PKGS[@]}"; do
        if ! dpkg -s "$pkg" &> /dev/null; then
            MISSING_PKGS+=("$pkg")
        fi
    done

    if [ ${#MISSING_PKGS[@]} -gt 0 ]; then
        echo -e "${YELLOW}[INFO]${NC} Instalando pacotes do sistema: ${MISSING_PKGS[*]}"
        sudo apt-get update -qq
        sudo apt-get install -y "${MISSING_PKGS[@]}"
        if [ $? -ne 0 ]; then
            echo -e "${RED}[ERRO]${NC} Falha ao instalar pacotes do sistema."
            echo "Tente instalar manualmente: sudo apt install -y ${MISSING_PKGS[*]}"
            exit 1
        fi
        echo -e "${GREEN}[OK]${NC} Pacotes do sistema instalados!"
    else
        echo -e "${GREEN}[OK]${NC} Todas as dependencias do sistema ja estao instaladas!"
    fi
else
    echo -e "${YELLOW}[AVISO]${NC} apt-get nao encontrado. Certifique-se de ter instalado:"
    echo "  build-essential python3-dev python3-venv libxcb-cursor0"
    echo "  libxcb-xinerama0 libxkbcommon0 libgl1 libegl1 libpq-dev unixodbc-dev xclip"
fi
echo ""

# Instalar GitHub CLI (necessario para Copilot)
echo -e "${YELLOW}[INFO]${NC} Verificando GitHub CLI (necessario para Copilot)..."

if ! command -v gh &> /dev/null; then
    echo -e "${YELLOW}[INFO]${NC} GitHub CLI nao encontrado. Instalando..."
    if command -v apt-get &> /dev/null; then
        ARCH=$(dpkg --print-architecture)
        curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg | sudo dd of=/usr/share/keyrings/githubcli-archive-keyring.gpg
        sudo chmod go+r /usr/share/keyrings/githubcli-archive-keyring.gpg
        echo "deb [arch=${ARCH} signed-by=/usr/share/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" | sudo tee /etc/apt/sources.list.d/github-cli.list > /dev/null
        sudo apt-get update -qq
        sudo apt-get install -y gh
        if [ $? -ne 0 ]; then
            echo -e "${YELLOW}[AVISO]${NC} Falha ao instalar GitHub CLI. Copilot pode nao funcionar."
        else
            echo -e "${GREEN}[OK]${NC} GitHub CLI instalado!"
        fi
    else
        echo -e "${YELLOW}[AVISO]${NC} apt-get nao encontrado. Instale gh manualmente: https://cli.github.com"
    fi
else
    echo -e "${GREEN}[OK]${NC} GitHub CLI ja esta instalado!"
    gh --version
fi

# Verificar se gh copilot funciona (built-in no gh 2.87+ ou via extensao)
if command -v gh &> /dev/null; then
    if gh copilot --help &> /dev/null; then
        echo -e "${GREEN}[OK]${NC} GitHub Copilot disponivel (built-in ou extensao)!"
    else
        # Tentar instalar extensao (para versoes antigas do gh)
        echo -e "${YELLOW}[INFO]${NC} Tentando instalar extensao GitHub Copilot..."
        if gh extension install github/gh-copilot 2>&1 | grep -q "built-in"; then
            echo -e "${GREEN}[OK]${NC} GitHub Copilot disponivel como comando built-in!"
        elif [ $? -eq 0 ]; then
            echo -e "${GREEN}[OK]${NC} Extensao Copilot instalada!"
        else
            echo -e "${YELLOW}[AVISO]${NC} Nao foi possivel configurar Copilot. Verifique manualmente."
        fi
    fi
fi
echo ""

# Verificar versao do Python (requer 3.12+)
echo -e "${YELLOW}[INFO]${NC} Verificando versao do Python..."

if ! command -v python3 &> /dev/null; then
    echo -e "${RED}[ERRO]${NC} Python3 nao encontrado!"
    echo "Instale Python 3.12 ou superior:"
    echo "  Ubuntu/Debian: sudo apt install python3.12 python3.12-venv"
    echo "  macOS: brew install python@3.12"
    exit 1
fi

PYTHON_VERSION=$(python3 --version 2>&1 | awk '{print $2}')
PYTHON_MAJOR=$(echo "$PYTHON_VERSION" | cut -d. -f1)
PYTHON_MINOR=$(echo "$PYTHON_VERSION" | cut -d. -f2)

if [ "$PYTHON_MAJOR" -lt 3 ] || { [ "$PYTHON_MAJOR" -eq 3 ] && [ "$PYTHON_MINOR" -lt 12 ]; }; then
    echo -e "${RED}[ERRO]${NC} Python 3.12+ necessario. Versao atual: $PYTHON_VERSION"
    echo "Instale Python 3.12 ou superior:"
    echo "  Ubuntu/Debian: sudo apt install python3.12 python3.12-venv"
    echo "  macOS: brew install python@3.12"
    exit 1
fi

echo -e "${GREEN}[OK]${NC} Python $PYTHON_VERSION encontrado!"
echo ""

# Verificar se UV esta instalado
echo -e "${YELLOW}[INFO]${NC} Verificando UV..."

if ! command -v uv &> /dev/null; then
    echo -e "${YELLOW}[INFO]${NC} UV nao encontrado. Instalando UV..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
    
    # Recarregar PATH
    export PATH="$HOME/.cargo/bin:$PATH"
    
    if ! command -v uv &> /dev/null; then
        echo -e "${RED}[ERRO]${NC} Falha ao instalar UV"
        echo "Tente instalar manualmente: curl -LsSf https://astral.sh/uv/install.sh | sh"
        exit 1
    fi
    echo -e "${GREEN}[OK]${NC} UV instalado!"
fi

echo -e "${GREEN}[OK]${NC} UV encontrado!"
uv --version
echo ""

# Criar ambiente virtual
echo -e "${YELLOW}[1/3]${NC} Criando ambiente virtual com Python $PYTHON_VERSION..."

if [ -d ".venv" ]; then
    echo "Ambiente virtual ja existe. Pulando..."
else
    uv venv
    if [ $? -ne 0 ]; then
        echo -e "${RED}[ERRO]${NC} Falha ao criar ambiente virtual"
        exit 1
    fi
    echo -e "${GREEN}[OK]${NC} Ambiente virtual criado!"
fi
echo ""

# Ativar ambiente virtual
echo -e "${YELLOW}[2/3]${NC} Ativando ambiente virtual..."
source .venv/bin/activate
if [ $? -ne 0 ]; then
    echo -e "${RED}[ERRO]${NC} Falha ao ativar ambiente virtual"
    exit 1
fi
echo -e "${GREEN}[OK]${NC} Ambiente virtual ativado!"
echo ""

# Instalar dependencias
echo -e "${YELLOW}[3/3]${NC} Instalando dependencias (isso pode demorar alguns minutos)..."
uv sync
if [ $? -ne 0 ]; then
    echo -e "${RED}[ERRO]${NC} Falha ao instalar dependencias"
    exit 1
fi
echo ""

echo "========================================"
echo "  Instalacao concluida com sucesso!"
echo "========================================"
echo ""
echo "Para executar o DataPyn:"
echo "  1. Execute: ./scripts/linux/run.sh"
echo "  OU"
echo "  2. Ative o ambiente: source .venv/bin/activate"
echo "     Depois execute: python source/main.py"
echo ""
echo "Consulte o README.md para mais informacoes."
