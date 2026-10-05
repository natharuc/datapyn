param(
    [string]$MsiPath,
    [string]$ExpectedSha256,
    [switch]$CheckOnly
)

# npm/GitHub Actions can inherit PowerShell 7's module path into Windows
# PowerShell 5.1. Resolve its built-in modules from its own installation.
foreach ($module in @('Microsoft.PowerShell.Management', 'Microsoft.PowerShell.Utility', 'Microsoft.PowerShell.Security')) {
    Import-Module (Join-Path $PSHOME ('Modules/' + $module)) -ErrorAction Stop
}

function Get-DataPynOdbcDriver {
    # The NSIS process is x86; inspect the driver registry for the x64 runtime.
    $base = [Microsoft.Win32.RegistryKey]::OpenBaseKey(
        [Microsoft.Win32.RegistryHive]::LocalMachine, [Microsoft.Win32.RegistryView]::Registry64
    )
    try {
        foreach ($name in @('ODBC Driver 18 for SQL Server', 'ODBC Driver 17 for SQL Server')) {
            $key = $base.OpenSubKey("SOFTWARE\ODBC\ODBCINST.INI\$name")
            if ($null -ne $key) {
                try {
                    $driver = [string]$key.GetValue('Driver', '')
                    if ($driver -and (Test-Path -LiteralPath $driver -PathType Leaf)) { return $name }
                } finally { $key.Dispose() }
            }
        }
        return $null
    } finally { $base.Dispose() }
}

function Assert-DataPynOdbcInstaller {
    param([Parameter(Mandatory = $true)][string]$Path,
          [Parameter(Mandatory = $true)][ValidatePattern('^[A-Fa-f0-9]{64}$')][string]$ExpectedSha256)
    $hash = (Get-FileHash -LiteralPath $Path -Algorithm SHA256 -ErrorAction Stop).Hash
    if ($hash -ne $ExpectedSha256) { throw 'Microsoft ODBC installer SHA256 mismatch.' }
    $signature = Get-AuthenticodeSignature -LiteralPath $Path
    if ($signature.Status -ne 'Valid' -or $null -eq $signature.SignerCertificate -or
        $signature.SignerCertificate.Subject -notmatch '(^|,\s*)O=Microsoft Corporation(,|$)') {
        throw 'Microsoft ODBC installer has no valid Microsoft signature.'
    }
}

function Invoke-DataPynOdbcPrerequisite {
    param([string]$MsiPath, [string]$ExpectedSha256, [switch]$CheckOnly)
    $ErrorActionPreference = 'Stop'
    try {
        $driver = Get-DataPynOdbcDriver
        if ($driver) { Write-Output "SQL Server driver ready: $driver"; return 0 }
        if ($CheckOnly) { Write-Output 'Microsoft SQL Server ODBC 17/18 x64 is not installed.'; return 10 }
        Assert-DataPynOdbcInstaller -Path $MsiPath -ExpectedSha256 $ExpectedSha256
        $log = Join-Path $env:TEMP ('DataPynTauri-ODBC-' + [Guid]::NewGuid().ToString('N') + '.log')
        $arguments = @('/i', ('"' + $MsiPath + '"'), '/passive', '/norestart',
                       'IACCEPTMSODBCSQLLICENSETERMS=YES', '/L*v', ('"' + $log + '"'))
        # Only the Microsoft driver elevates. The DataPyn installation remains currentUser.
        $process = Start-Process -FilePath (Join-Path $env:WINDIR 'System32/msiexec.exe') `
            -ArgumentList $arguments -Verb RunAs -WindowStyle Hidden -Wait -PassThru
        if ($process.ExitCode -notin @(0, 3010, 1641)) {
            Write-Output "Microsoft ODBC installation failed ($($process.ExitCode)). Log: $log"
            return [int]$process.ExitCode
        }
        if (-not (Get-DataPynOdbcDriver)) {
            Write-Output "Microsoft ODBC driver was not registered. Log: $log"
            return 1603
        }
        Write-Output 'Microsoft SQL Server ODBC driver installed.'
        if ($process.ExitCode -in @(3010, 1641)) { return 3010 }
        return 0
    } catch {
        Write-Output ("Microsoft ODBC prerequisite failed: " + $_.Exception.Message)
        if ($_.Exception.NativeErrorCode -eq 1223) { return 1223 }
        return 1603
    }
}

if ($MyInvocation.InvocationName -ne '.') {
    $result = @(Invoke-DataPynOdbcPrerequisite -MsiPath $MsiPath -ExpectedSha256 $ExpectedSha256 -CheckOnly:$CheckOnly)
    $result | Select-Object -SkipLast 1 | Write-Output
    exit [int]$result[-1]
}
