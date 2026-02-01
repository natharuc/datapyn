@echo off
echo ========================================
echo   DataPyn IDE - Script de Instalacao
echo ========================================
echo.

REM Verificar se Python está instalado
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERRO] Python nao encontrado!
    echo Por favor, instale Python 3.8 ou superior em: https://www.python.org/
    pause
    exit /b 1
)

echo [OK] Python encontrado!
python --version
echo.

REM Criar ambiente virtual
echo [1/4] Criando ambiente virtual...
if exist .venv (
    echo Ambiente virtual ja existe. Pulando...
) else (
    python -m venv .venv
    if errorlevel 1 (
        echo [ERRO] Falha ao criar ambiente virtual
        pause
        exit /b 1
    )
    echo [OK] Ambiente virtual criado!
)
echo.

REM Ativar ambiente virtual
echo [2/4] Ativando ambiente virtual...
call .venv\Scripts\activate.bat
if errorlevel 1 (
    echo [ERRO] Falha ao ativar ambiente virtual
    pause
    exit /b 1
)
echo [OK] Ambiente virtual ativado!
echo.

REM Atualizar pip
echo [3/4] Atualizando pip...
python -m pip install --upgrade pip
echo.

REM Instalar dependências
echo [4/4] Instalando dependencias (isso pode demorar alguns minutos)...
pip install -r requirements.txt
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
echo   1. Execute: run.bat
echo   OU
echo   2. Ative o ambiente: .venv\Scripts\activate
echo      Depois execute: python main.py
echo.
echo Consulte o README.md para mais informacoes.
echo.
pause
