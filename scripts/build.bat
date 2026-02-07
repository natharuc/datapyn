@echo off
echo ========================================
echo    DataPyn - Build EXE
echo ========================================
echo.

REM Navegar para a raiz do projeto
cd /d "%~dp0.."

REM Ativar ambiente virtual
call .venv\Scripts\activate

REM Verificar se PyInstaller está instalado
pip show pyinstaller >nul 2>&1
if errorlevel 1 (
    echo Instalando PyInstaller...
    pip install pyinstaller
)

echo.
echo Gerando executavel...
echo.

REM Executar PyInstaller com o spec file
pyinstaller scripts\datapyn.spec --clean

echo.
if exist "dist\DataPyn\DataPyn.exe" (
    echo ========================================
    echo    Build concluido com sucesso!
    echo    Pasta: dist\DataPyn\
    echo    Executavel: dist\DataPyn\DataPyn.exe
    echo ========================================
) else (
    echo ========================================
    echo    ERRO: Build falhou!
    echo ========================================
)

pause
