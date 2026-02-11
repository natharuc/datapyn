@echo off
echo ========================================
echo    DataPyn - Build MSI Installer
echo ========================================
echo.

REM Navegar para a raiz do projeto
cd /d "%~dp0.."

REM Ativar ambiente virtual
call .venv\Scripts\activate

REM Verificar se cx_Freeze esta instalado
pip show cx_Freeze >nul 2>&1
if errorlevel 1 (
    echo Instalando cx_Freeze...
    pip install cx_Freeze
)

echo.
echo Gerando instalador MSI...
echo.

REM Limpar build anterior
if exist "build" rmdir /s /q "build"
if exist "dist" rmdir /s /q "dist"

REM Executar cx_Freeze para gerar MSI
python scripts\setup_msi.py bdist_msi

echo.
if exist "dist\*.msi" (
    echo ========================================
    echo    Instalador MSI gerado com sucesso!
    echo    Localizacao: dist\
    echo ========================================
    dir /b dist\*.msi
) else (
    echo ========================================
    echo    ERRO: Falha ao gerar instalador MSI!
    echo ========================================
)

pause
