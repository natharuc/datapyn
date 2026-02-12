@echo off
echo ========================================
echo   DataPyn - Migracao para UV
echo ========================================
echo.

REM Navegar para a raiz do projeto
cd /d "%~dp0.."

REM Verificar se UV está instalado
uv --version >nul 2>&1
if errorlevel 1 (
    echo [INFO] UV nao encontrado. Instalando UV...
    powershell -Command "& {Invoke-WebRequest -Uri https://astral.sh/uv/install.ps1 -OutFile install-uv.ps1; .\install-uv.ps1}"
    if errorlevel 1 (
        echo [ERRO] Falha ao instalar UV
        pause
        exit /b 1
    )
    echo [OK] UV instalado!
)
echo [OK] UV encontrado!
uv --version
echo.

REM Deletar ambiente virtual antigo
echo [1/2] Removendo ambiente virtual antigo...
if exist .venv (
    rmdir /s /q .venv
    echo [OK] Ambiente virtual antigo removido!
) else (
    echo Ambiente virtual nao encontrado. Pulando...
)
echo.

REM Instalar dependências com UV
echo [2/2] Instalando dependencias com UV...
uv sync --dev
if errorlevel 1 (
    echo [ERRO] Falha ao instalar dependencias
    pause
    exit /b 1
)
echo.

echo ========================================
echo   Migracao concluida com sucesso!
echo ========================================
echo.
echo Seu ambiente agora usa UV.
echo Para executar testes: uv run pytest
echo Para executar o app: uv run python source\main.py
echo.
pause