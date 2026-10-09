; Tauri includes FileAssociation.nsh before installerHooks. Replace only its two
; entry points: upstream claims every default and restores backups unconditionally.
; Keep Windows UserChoice untouched; Windows 10/11 owns that protected preference.
!include LogicLib.nsh
!ifmacrodef APP_ASSOCIATE
  !macroundef APP_ASSOCIATE
!endif
!ifmacrodef APP_UNASSOCIATE
  !macroundef APP_UNASSOCIATE
!endif
!define DATAPYN_CAPABILITIES "Software\DataPynTauri\Capabilities"

!macro APP_ASSOCIATE EXT FILECLASS DESCRIPTION ICON COMMANDTEXT COMMAND
  Push $R0
  Push $R1
  ; Register a stable application-specific ProgID, an Open With candidate, and
  ; Default Apps capabilities. Quote BOTH executable and argument (spaces/Unicode).
  WriteRegStr SHCTX "Software\Classes\${FILECLASS}" "" `${DESCRIPTION}`
  WriteRegStr SHCTX "Software\Classes\${FILECLASS}\DefaultIcon" "" '$\"$INSTDIR\${MAINBINARYNAME}.exe$\",0'
  WriteRegStr SHCTX "Software\Classes\${FILECLASS}\shell" "" "open"
  WriteRegStr SHCTX "Software\Classes\${FILECLASS}\shell\open" "" `${COMMANDTEXT}`
  WriteRegStr SHCTX "Software\Classes\${FILECLASS}\shell\open\command" "" '$\"$INSTDIR\${MAINBINARYNAME}.exe$\" $\"%1$\"'
  WriteRegStr SHCTX "Software\Classes\.${EXT}\OpenWithProgids" "${FILECLASS}" ""
  WriteRegStr SHCTX "${DATAPYN_CAPABILITIES}" "ApplicationName" "DataPyn Tauri"
  WriteRegStr SHCTX "${DATAPYN_CAPABILITIES}" "ApplicationDescription" "SQL and Python workspace"
  WriteRegStr SHCTX "${DATAPYN_CAPABILITIES}" "ApplicationIcon" '$\"$INSTDIR\${MAINBINARYNAME}.exe$\",0'
  WriteRegStr SHCTX "${DATAPYN_CAPABILITIES}\FileAssociations" ".${EXT}" "${FILECLASS}"
  WriteRegStr SHCTX "Software\RegisteredApplications" "DataPyn Tauri" "${DATAPYN_CAPABILITIES}"
  ; HKCR merges HKCU/HKLM. A machine default or explicit per-user choice must
  ; survive installation AND automatic updates, even if it is another editor.
  ReadRegStr $R0 HKCR ".${EXT}" ""
  ReadRegStr $R1 HKCU "Software\Microsoft\Windows\CurrentVersion\Explorer\FileExts\.${EXT}\UserChoice" "ProgId"
  ${If} $R0 == ""
  ${AndIf} $R1 == ""
    WriteRegStr SHCTX "Software\Classes\.${EXT}" "" "${FILECLASS}"
  ${EndIf}
  Pop $R1
  Pop $R0
!macroend

!macro APP_UNASSOCIATE EXT FILECLASS
  Push $R0
  ; Delete only a registration still pointing at this exact installation.
  ReadRegStr $R0 SHCTX "Software\Classes\${FILECLASS}\shell\open\command" ""
  ${If} $R0 == '$\"$INSTDIR\${MAINBINARYNAME}.exe$\" $\"%1$\"'
    ReadRegStr $R0 SHCTX "Software\Classes\.${EXT}" ""
    ${If} $R0 == "${FILECLASS}"
      DeleteRegValue SHCTX "Software\Classes\.${EXT}" ""
    ${EndIf}
    DeleteRegValue SHCTX "Software\Classes\.${EXT}\OpenWithProgids" "${FILECLASS}"
    DeleteRegKey /ifempty SHCTX "Software\Classes\.${EXT}\OpenWithProgids"
    DeleteRegKey /ifempty SHCTX "Software\Classes\.${EXT}"
    DeleteRegKey SHCTX "Software\Classes\${FILECLASS}"
  ${EndIf}
  Pop $R0
!macroend

!macro NSIS_HOOK_POSTINSTALL
  Push $R0
  ; 1.0.0-1.0.3 used this friendly name as their DPW ProgID. Preserve an existing
  ; UserChoice referring to it and repair its unquoted command during upgrades.
  ReadRegStr $R0 SHCTX "Software\Classes\DataPyn workspace\shell\open\command" ""
  ${If} $R0 == '$INSTDIR\${MAINBINARYNAME}.exe $\"%1$\"'
    WriteRegStr SHCTX "Software\Classes\DataPyn workspace\shell\open\command" "" '$\"$INSTDIR\${MAINBINARYNAME}.exe$\" $\"%1$\"'
    WriteRegStr SHCTX "Software\Classes\DataPyn workspace\DefaultIcon" "" '$\"$INSTDIR\${MAINBINARYNAME}.exe$\",0'
  ${EndIf}
  Pop $R0
  !insertmacro UPDATEFILEASSOC
!macroend

!macro NSIS_HOOK_POSTUNINSTALL
  Push $R0
  Push $R1
  ; Clean the old Tauri DPW registration only if this installation owns it.
  ; The old installer saved a previous class; restore it only while still the
  ; default, never after the user has selected another editor.
  ReadRegStr $R0 SHCTX "Software\Classes\DataPyn workspace\shell\open\command" ""
  ${If} $R0 == '$\"$INSTDIR\${MAINBINARYNAME}.exe$\" $\"%1$\"'
    ReadRegStr $R0 SHCTX "Software\Classes\.dpw" ""
    ${If} $R0 == "DataPyn workspace"
      ReadRegStr $R1 SHCTX "Software\Classes\.dpw" "DataPyn workspace_backup"
      ${If} $R1 != ""
      ${AndIf} $R1 != "DataPyn workspace"
        WriteRegStr SHCTX "Software\Classes\.dpw" "" "$R1"
      ${Else}
        DeleteRegValue SHCTX "Software\Classes\.dpw" ""
      ${EndIf}
    ${EndIf}
    DeleteRegValue SHCTX "Software\Classes\.dpw" "DataPyn workspace_backup"
    DeleteRegKey SHCTX "Software\Classes\DataPyn workspace"
    DeleteRegKey /ifempty SHCTX "Software\Classes\.dpw"
  ${EndIf}
  ReadRegStr $R0 SHCTX "${DATAPYN_CAPABILITIES}" "ApplicationIcon"
  ${If} $R0 == '$\"$INSTDIR\${MAINBINARYNAME}.exe$\",0'
    ReadRegStr $R1 SHCTX "Software\RegisteredApplications" "DataPyn Tauri"
    ${If} $R1 == "${DATAPYN_CAPABILITIES}"
      DeleteRegValue SHCTX "Software\RegisteredApplications" "DataPyn Tauri"
    ${EndIf}
    DeleteRegKey SHCTX "${DATAPYN_CAPABILITIES}"
    DeleteRegKey /ifempty SHCTX "Software\DataPynTauri"
  ${EndIf}
  Pop $R1
  Pop $R0
  !insertmacro UPDATEFILEASSOC
!macroend
