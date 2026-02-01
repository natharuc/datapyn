@echo off
echo ========================================
echo   Iniciando DataPyn IDE...
echo ========================================
echo.

REM Verificar se venv existe
if not exist venv (
    echo [ERRO] Ambiente virtual nao encontrado!
    echo Execute install.bat primeiro.
    pause
    exit /b 1
)

REM Ativar ambiente virtual e executar
call venv\Scripts\activate.bat
python main.py

REM Se houver erro
if errorlevel 1 (
    echo.
    echo [ERRO] Ocorreu um erro ao executar o DataPyn
    echo Verifique o arquivo datapyn.log para mais detalhes.
    pause
)
