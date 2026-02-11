@echo off
echo ========================================
echo    DataPyn - Build
echo ========================================
echo.
echo Escolha o tipo de build:
echo 1. EXE (PyInstaller - rapido)
echo 2. MSI Installer (cx_Freeze - completo)
echo 3. Ambos (EXE + MSI)
echo.
choice /c 123 /n /m "Opcao (1-3): "

if errorlevel 3 goto BUILD_BOTH
if errorlevel 2 goto BUILD_MSI
if errorlevel 1 goto BUILD_EXE

:BUILD_EXE
echo.
echo ========================================
echo    Gerando EXE com PyInstaller...
echo ========================================
call scripts\build_exe.bat
goto END

:BUILD_MSI
echo.
echo ========================================
echo    Gerando MSI Installer...
echo ========================================
call scripts\build_msi.bat
goto END

:BUILD_BOTH
echo.
echo ========================================
echo    Gerando EXE e MSI Installer...
echo ========================================
call scripts\build_exe.bat
echo.
call scripts\build_msi.bat
goto END

:END
pause

