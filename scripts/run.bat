@echo off
echo ========================================
echo   Iniciando DataPyn IDE...
echo ========================================
echo.

REM Navegar para a raiz do projeto
cd /d "%~dp0.."

REM Verificar versao do Python (requer 3.12+)
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERRO] Python nao encontrado!
    echo Instale Python 3.12 ou superior: https://www.python.org/downloads/
    pause
    exit /b 1
)

for /f "tokens=2 delims= " %%v in ('python --version 2^>^&1') do set PYTHON_VERSION=%%v
for /f "tokens=1,2 delims=." %%a in ("%PYTHON_VERSION%") do (
    set PYTHON_MAJOR=%%a
    set PYTHON_MINOR=%%b
)

if %PYTHON_MAJOR% LSS 3 (
    echo [ERRO] Python 3.12+ necessario. Versao atual: %PYTHON_VERSION%
    pause
    exit /b 1
)
if %PYTHON_MAJOR% EQU 3 if %PYTHON_MINOR% LSS 12 (
    echo [ERRO] Python 3.12+ necessario. Versao atual: %PYTHON_VERSION%
    pause
    exit /b 1
)

REM Verificar se .venv existe
if not exist .venv (
    echo [ERRO] Ambiente virtual nao encontrado!
    echo Execute scripts\install.bat primeiro.
    pause
    exit /b 1
)

REM Ativar ambiente virtual e executar
call .venv\Scripts\activate.bat
python source\main.py

REM Se houver erro
if errorlevel 1 (
    echo.
    echo [ERRO] Ocorreu um erro ao executar o DataPyn
    echo Verifique o arquivo datapyn.log para mais detalhes.
    pause
)
