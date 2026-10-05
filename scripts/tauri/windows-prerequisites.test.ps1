param([string]$BootstrapPath, [string]$TestDirectory)
$ErrorActionPreference = 'Stop'
. $BootstrapPath

$script:startCalls = 0
$script:driverCalls = 0
$script:hasDriver = $false
$script:postInstallDriver = $false
$script:signatureStatus = 'Valid'
$script:publisher = 'O=Microsoft Corporation, C=US'
$script:msiCode = 0
$script:cancelElevation = $false
$script:lastStart = $null
function Get-DataPynOdbcDriver {
    $script:driverCalls++
    if ($script:hasDriver -or ($script:postInstallDriver -and $script:driverCalls -gt 1)) { return 'ODBC Driver 18 for SQL Server' }
    return $null
}
function Get-AuthenticodeSignature {
    param($LiteralPath)
    return [pscustomobject]@{ Status = $script:signatureStatus; SignerCertificate = [pscustomobject]@{ Subject = $script:publisher } }
}
function Start-Process {
    param($FilePath, $ArgumentList, $Verb, $WindowStyle, [switch]$Wait, [switch]$PassThru)
    $script:startCalls++
    $script:lastStart = [pscustomobject]@{ file = $FilePath; arguments = $ArgumentList; verb = $Verb; style = $WindowStyle; wait = [bool]$Wait; passThru = [bool]$PassThru }
    if ($script:cancelElevation) { throw [System.ComponentModel.Win32Exception]::new(1223) }
    return [pscustomobject]@{ ExitCode = $script:msiCode }
}
function Reset-TestState {
    $script:startCalls = 0; $script:driverCalls = 0; $script:hasDriver = $false
    $script:postInstallDriver = $false; $script:signatureStatus = 'Valid'; $script:publisher = 'O=Microsoft Corporation, C=US'
    $script:msiCode = 0; $script:cancelElevation = $false; $script:lastStart = $null
}
function Test-ResultCode {
    param($result)
    return [int]@($result)[-1]
}

$file = Join-Path $TestDirectory 'not-an-installer.dat'
[System.IO.File]::WriteAllText($file, 'Test payload, never run as an installer.')
$hash = (Get-FileHash -LiteralPath $file -Algorithm SHA256).Hash
$reports = @()

Reset-TestState
$script:hasDriver = $true
$code = Test-ResultCode (Invoke-DataPynOdbcPrerequisite -MsiPath $file -ExpectedSha256 $hash)
$reports += @{ scenario = 'existing-driver'; code = $code; starts = $script:startCalls }

Reset-TestState
$code = Test-ResultCode (Invoke-DataPynOdbcPrerequisite -CheckOnly)
$reports += @{ scenario = 'check-only-missing'; code = $code; starts = $script:startCalls }

Reset-TestState
$code = Test-ResultCode (Invoke-DataPynOdbcPrerequisite -MsiPath $file -ExpectedSha256 ('0' * 64))
$reports += @{ scenario = 'tampered-installer'; code = $code; starts = $script:startCalls }

Reset-TestState
$script:signatureStatus = 'NotSigned'
$code = Test-ResultCode (Invoke-DataPynOdbcPrerequisite -MsiPath $file -ExpectedSha256 $hash)
$reports += @{ scenario = 'unsigned-installer'; code = $code; starts = $script:startCalls }

Reset-TestState
$script:publisher = 'O=Example Other Publisher, C=US'
$code = Test-ResultCode (Invoke-DataPynOdbcPrerequisite -MsiPath $file -ExpectedSha256 $hash)
$reports += @{ scenario = 'wrong-publisher'; code = $code; starts = $script:startCalls }

Reset-TestState
$script:postInstallDriver = $true
$code = Test-ResultCode (Invoke-DataPynOdbcPrerequisite -MsiPath $file -ExpectedSha256 $hash)
$reports += @{ scenario = 'approved-install'; code = $code; starts = $script:startCalls; process = $script:lastStart }

Reset-TestState
$script:postInstallDriver = $true
$script:msiCode = 3010
$code = Test-ResultCode (Invoke-DataPynOdbcPrerequisite -MsiPath $file -ExpectedSha256 $hash)
$reports += @{ scenario = 'reboot-required'; code = $code; starts = $script:startCalls }

Reset-TestState
$code = Test-ResultCode (Invoke-DataPynOdbcPrerequisite -MsiPath $file -ExpectedSha256 $hash)
$reports += @{ scenario = 'driver-not-registered'; code = $code; starts = $script:startCalls }

Reset-TestState
$script:msiCode = 1603
$code = Test-ResultCode (Invoke-DataPynOdbcPrerequisite -MsiPath $file -ExpectedSha256 $hash)
$reports += @{ scenario = 'msi-failed'; code = $code; starts = $script:startCalls }

Reset-TestState
$script:cancelElevation = $true
$code = Test-ResultCode (Invoke-DataPynOdbcPrerequisite -MsiPath $file -ExpectedSha256 $hash)
$reports += @{ scenario = 'uac-cancelled'; code = $code; starts = $script:startCalls }

ConvertTo-Json -InputObject $reports -Depth 5 -Compress
