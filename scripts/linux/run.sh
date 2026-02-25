#!/bin/bash

echo "========================================"
echo "  Iniciando DataPyn IDE..."
echo "========================================"
echo ""

# Cores para output
RED='\033[0;31m'
GREEN='\033[0;32m'
NC='\033[0m' # No Color

# Navegar para a raiz do projeto
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR/../.." || exit 1

# Verificar versao do Python (requer 3.12+)
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
    exit 1
fi

# Verificar se .venv existe
if [ ! -d ".venv" ]; then
    echo -e "${RED}[ERRO]${NC} Ambiente virtual nao encontrado!"
    echo "Execute ./scripts/linux/install.sh primeiro."
    exit 1
fi

# Ativar ambiente virtual e executar
source .venv/bin/activate
python source/main.py

# Se houver erro
if [ $? -ne 0 ]; then
    echo ""
    echo -e "${RED}[ERRO]${NC} Ocorreu um erro ao executar o DataPyn"
    echo "Verifique o arquivo datapyn.log para mais detalhes."
fi
