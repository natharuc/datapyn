param([string]$ScriptPath)
$ErrorActionPreference = 'Stop'
$parseErrors = $null
$null = [System.Management.Automation.Language.Parser]::ParseFile($ScriptPath, [ref]$null, [ref]$parseErrors)
if ($parseErrors.Count) { throw 'Installer acceptance script has syntax errors.' }
. $ScriptPath

# Read-only acceptance assertions use this in-memory registry. No setup,
# uninstall, process execution, registry writes, or real registry reads occur.
$script:values = @{}
function Read-DataPynAssociationValues {
    param([string]$Path, [Microsoft.Win32.RegistryHive]$Hive = 'CurrentUser')
    return $script:values[$Path]
}
$main = 'C:\Runner Temp\DataPyn Tauri with spaces\datapyn-desktop.exe'
$command = '"' + $main + '" "%1"'
$capabilities = 'Software\DataPynTauri\Capabilities'
$script:values['Software\RegisteredApplications'] = [ordered]@{ 'DataPyn Tauri' = $capabilities }
$script:values[$capabilities] = [ordered]@{ ApplicationName = 'DataPyn Tauri' }
$script:values[$capabilities + '\FileAssociations'] = [ordered]@{ '.sql' = 'app.datapyn.tauri.sql'; '.dpw' = 'app.datapyn.tauri.dpw' }
$choices = @{}
foreach ($extension in @('sql', 'dpw')) {
    $progId = 'app.datapyn.tauri.' + $extension
    $script:values['Software\Classes\' + $progId] = [ordered]@{ '' = 'File' }
    $script:values['Software\Classes\' + $progId + '\shell\open\command'] = [ordered]@{ '' = $command }
    $script:values['Software\Classes\.' + $extension + '\OpenWithProgids'] = [ordered]@{ $progId = '' }
    $script:values['Software\Classes\.' + $extension] = [ordered]@{ '' = 'Other.Editor' }
    $choicePath = 'Software\Microsoft\Windows\CurrentVersion\Explorer\FileExts\.' + $extension + '\UserChoice'
    $script:values[$choicePath] = [ordered]@{ ProgId = 'Other.Editor'; Hash = 'protected-choice' }
    $choices[$extension] = $script:values[$choicePath] | ConvertTo-Json -Compress
}
$cases = @()
Assert-DataPynInstalledAssociations -MainPath $main -SqlDefault 'Other.Editor' -DpwDefault 'Other.Editor' -UserChoices $choices
$cases += @{ scenario = 'valid-registration'; accepted = $true }
foreach ($scenario in @('unquoted-executable', 'missing-capability', 'missing-open-with', 'changed-user-choice', 'claimed-existing-default')) {
    $path = switch ($scenario) {
        'unquoted-executable' { 'Software\Classes\app.datapyn.tauri.sql\shell\open\command' }
        'missing-capability' { $capabilities + '\FileAssociations' }
        'missing-open-with' { 'Software\Classes\.sql\OpenWithProgids' }
        'changed-user-choice' { 'Software\Microsoft\Windows\CurrentVersion\Explorer\FileExts\.sql\UserChoice' }
        'claimed-existing-default' { 'Software\Classes\.sql' }
    }
    $before = $script:values[$path]
    $script:values[$path] = switch ($scenario) {
        'unquoted-executable' { [ordered]@{ '' = ($main + ' "%1"') } }
        'missing-capability' { [ordered]@{ '.dpw' = 'app.datapyn.tauri.dpw' } }
        'missing-open-with' { [ordered]@{ 'Other.Editor' = '' } }
        'changed-user-choice' { [ordered]@{ ProgId = 'app.datapyn.tauri.sql'; Hash = 'changed' } }
        'claimed-existing-default' { [ordered]@{ '' = 'app.datapyn.tauri.sql' } }
    }
    $rejected = $false
    try { Assert-DataPynInstalledAssociations -MainPath $main -SqlDefault 'Other.Editor' -DpwDefault 'Other.Editor' -UserChoices $choices }
    catch { $rejected = $true }
    if (-not $rejected) { throw "Invalid acceptance case passed: $scenario" }
    $cases += @{ scenario = $scenario; rejected = $rejected }
    $script:values[$path] = $before
}
foreach ($extension in @('sql', 'dpw')) {
    $null = $script:values.Remove('Software\Classes\app.datapyn.tauri.' + $extension)
    $script:values['Software\Classes\.' + $extension + '\OpenWithProgids'] = [ordered]@{ 'Other.Editor' = '' }
}
$null = $script:values.Remove($capabilities)
Assert-DataPynRemovedAssociations -SqlDefault 'Other.Editor' -DpwDefault 'Other.Editor' -UserChoices $choices
$cases += @{ scenario = 'valid-uninstall-preserves-other-editor'; accepted = $true }
$script:values['Software\Classes\.dpw'] = $null
Assert-DataPynRemovedAssociations -SqlDefault 'Other.Editor' -DpwDefault '' -UserChoices $choices
$cases += @{ scenario = 'valid-uninstall-removes-unclaimed-extension'; accepted = $true }
$cases | ConvertTo-Json -Depth 5 -Compress
