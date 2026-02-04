@echo off
cd /d "%~dp0.."

if not exist .venv (
    echo Criando ambiente virtual...
    python -m venv .venv
    call .venv\Scripts\activate.bat
    echo Instalando dependencias...
    pip install -r requirements.txt
) else (
    call .venv\Scripts\activate.bat
)

python source\main.py
