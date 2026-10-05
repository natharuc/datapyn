param([string]$ScriptPath, [string]$TestDirectory)
$ErrorActionPreference = 'Stop'
foreach ($module in @('Microsoft.PowerShell.Management', 'Microsoft.PowerShell.Utility')) {
    Import-Module (Join-Path $PSHOME ('Modules/' + $module)) -ErrorAction Stop
}
$parseErrors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile($ScriptPath, [ref]$null, [ref]$parseErrors)
if ($parseErrors.Count) { throw 'Installer acceptance script has syntax errors.' }
. $ScriptPath
$testEnvironment = @{ GITHUB_ACTIONS = 'true'; RUNNER_ENVIRONMENT = 'github-hosted'; RUNNER_OS = 'Windows'; RUNNER_ARCH = 'X64'; RUNNER_TEMP = $TestDirectory }
$eligible = Assert-DataPynHostedWindowsRunner -Environment $testEnvironment
$rejected = @()
foreach ($pair in @(@('GITHUB_ACTIONS', ''), @('RUNNER_ENVIRONMENT', 'self-hosted'), @('RUNNER_OS', 'Linux'), @('RUNNER_ARCH', 'ARM64'), @('RUNNER_TEMP', 'relative-dir'))) {
    $variant = $testEnvironment.Clone()
    $variant[$pair[0]] = $pair[1]
    try { $null = Assert-DataPynHostedWindowsRunner -Environment $variant }
    catch { $rejected += $pair[0] }
}
$rootVariant = $testEnvironment.Clone()
$rootVariant['RUNNER_TEMP'] = [System.IO.Path]::GetPathRoot($TestDirectory)
try { $null = Assert-DataPynHostedWindowsRunner -Environment $rootVariant }
catch { $rejected += 'filesystem-root' }
# All tested functions are pure validation/argument construction. Neither the
# installation function nor any process/registry/machine-changing function runs.
$installDirectory = Join-Path $TestDirectory 'DataPyn Tauri with spaces'
@{ parsed = $true; eligible = $eligible; rejected = $rejected;
   install = @(Get-DataPynSilentInstallArguments $installDirectory);
   uninstall = @(Get-DataPynSilentUninstallArguments $installDirectory) } | ConvertTo-Json -Depth 4 -Compress
