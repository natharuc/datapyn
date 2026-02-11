@echo off
REM Script separado para build do EXE com PyInstaller

REM Navegar para a raiz do projeto
cd /d "%~dp0.."

REM Ativar ambiente virtual
call .venv\Scripts\activate

REM Verificar se PyInstaller esta instalado
pip show pyinstaller >nul 2>&1
if errorlevel 1 (
    echo Instalando PyInstaller...
    pip install pyinstaller
)

echo.
echo Gerando executavel...
echo.

REM Limpar build anterior para detectar falha corretamente
if exist "dist\DataPyn\DataPyn.exe" del "dist\DataPyn\DataPyn.exe"

REM Executar PyInstaller com o spec file
pyinstaller scripts\datapyn.spec --clean -y

echo.
if exist "dist\DataPyn\DataPyn.exe" (
    echo ========================================
    echo    Build EXE concluido com sucesso!
    echo    Pasta: dist\DataPyn\
    echo    Executavel: dist\DataPyn\DataPyn.exe
    echo ========================================
) else (
    echo ========================================
    echo    ERRO: Build EXE falhou!
    echo ========================================
)
