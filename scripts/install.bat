@echo off
echo ========================================
echo   DataPyn IDE - Script de Instalacao
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

REM Criar ambiente virtual
echo [1/3] Criando ambiente virtual...
if exist .venv (
    echo Ambiente virtual ja existe. Pulando...
) else (
    uv venv
    if errorlevel 1 (
        echo [ERRO] Falha ao criar ambiente virtual
        pause
        exit /b 1
    )
    echo [OK] Ambiente virtual criado!
)
echo.

REM Ativar ambiente virtual
echo [2/3] Ativando ambiente virtual...
call .venv\Scripts\activate.bat
if errorlevel 1 (
    echo [ERRO] Falha ao ativar ambiente virtual
    pause
    exit /b 1
)
echo [OK] Ambiente virtual ativado!
echo.

REM Instalar dependências
echo [3/3] Instalando dependencias (isso pode demorar alguns minutos)...
uv sync
if errorlevel 1 (
    echo [ERRO] Falha ao instalar dependencias
    pause
    exit /b 1
)
echo.

echo ========================================
echo   Instalacao concluida com sucesso!
echo ========================================
echo.
echo Para executar o DataPyn:
echo   1. Execute: scripts\run.bat
echo   OU
echo   2. Ative o ambiente: .venv\Scripts\activate
echo      Depois execute: python source\main.py
echo.
echo Consulte o README.md para mais informacoes.
echo.
pause
