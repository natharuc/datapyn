param(
    [Parameter(Mandatory = $true)][string]$Path,
    [Parameter(Mandatory = $true)][ValidatePattern('^[A-Fa-f0-9]{64}$')][string]$ExpectedSha256
)
$ErrorActionPreference = 'Stop'
$artifactPath = $Path
$artifactExpectedSha256 = $ExpectedSha256
. (Join-Path $PSScriptRoot '../../desktop/src-tauri/windows/install-odbc.ps1')
Assert-DataPynOdbcInstaller -Path $artifactPath -ExpectedSha256 $artifactExpectedSha256
