; Microsoft ODBC is embedded in the Tauri installer; never invoke the PyQt installer.
!include LogicLib.nsh
!include "${__FILEDIR__}\..\..\..\build\windows-prerequisites\odbc-artifact.nsh"
!define DATAPYN_ODBC_SCRIPT "${__FILEDIR__}\install-odbc.ps1"

LangString DataPynOdbcConsent 1033 "SQL Server requires Microsoft ODBC Driver 18. Install it now? Administrator approval will be requested only for this driver. Continuing accepts Microsoft's ODBC license terms: https://aka.ms/odbc18eula"
LangString DataPynOdbcConsent 1046 "O SQL Server requer o Microsoft ODBC Driver 18. Instalar agora? A permissao de administrador sera solicitada apenas para esse driver. Ao continuar, voce aceita os termos da Microsoft: https://aka.ms/odbc18eula"
LangString DataPynOdbcFailure 1033 "Microsoft ODBC could not be installed. DataPyn installation was interrupted. Check the installation details or install Microsoft ODBC Driver 18 and try again."
LangString DataPynOdbcFailure 1046 "Nao foi possivel instalar o Microsoft ODBC. A instalacao foi interrompida. Consulte os detalhes ou instale o Microsoft ODBC Driver 18 e tente novamente."

!macro NSIS_HOOK_PREINSTALL
  Push $0
  Push $1
  Push $2
  InitPluginsDir
  SetOutPath "$PLUGINSDIR"
  File "/oname=datapyn-install-odbc.ps1" "${DATAPYN_ODBC_SCRIPT}"
  StrCpy $2 "$SYSDIR\WindowsPowerShell\v1.0\powershell.exe"
  IfFileExists "$WINDIR\Sysnative\WindowsPowerShell\v1.0\powershell.exe" 0 +2
    StrCpy $2 "$WINDIR\Sysnative\WindowsPowerShell\v1.0\powershell.exe"
  nsExec::ExecToStack '"$2" -NoProfile -NonInteractive -ExecutionPolicy Bypass -File "$PLUGINSDIR\datapyn-install-odbc.ps1" -CheckOnly'
  Pop $0
  Pop $1
  ${If} $0 == 0
    DetailPrint "$1"
  ${Else}
    ; No consent dialogs or elevation during unattended/passive updates.
    ${If} $PassiveMode == 1
      DetailPrint "Microsoft ODBC 17/18 x64 missing. Install Microsoft ODBC Driver 18 before unattended installation."
      SetErrorLevel 1603
      Abort
    ${EndIf}
    IfSilent datapyn_odbc_abort
    MessageBox MB_YESNO|MB_ICONQUESTION|MB_DEFBUTTON2 "$(DataPynOdbcConsent)" IDYES datapyn_odbc_install
      SetErrorLevel 1223
      Abort
    datapyn_odbc_install:
    File "/oname=datapyn-msodbcsql.msi" "${DATAPYN_ODBC_MSI}"
    nsExec::ExecToStack '"$2" -NoProfile -NonInteractive -ExecutionPolicy Bypass -File "$PLUGINSDIR\datapyn-install-odbc.ps1" -MsiPath "$PLUGINSDIR\datapyn-msodbcsql.msi" -ExpectedSha256 "${DATAPYN_ODBC_SHA256}"'
    Pop $0
    Pop $1
    DetailPrint "$1"
    ${If} $0 == 3010
      SetRebootFlag true
    ${ElseIf} $0 != 0
      MessageBox MB_OK|MB_ICONSTOP "$(DataPynOdbcFailure)"
      datapyn_odbc_abort:
      SetErrorLevel 1603
      Abort
    ${EndIf}
  ${EndIf}
  SetOutPath "$INSTDIR"
  Pop $2
  Pop $1
  Pop $0
!macroend
