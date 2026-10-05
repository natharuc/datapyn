param(
    [string]$InstallerPath = $env:DATAPYN_NSIS_INSTALLER,
    [string]$PythonPath = $env:DATAPYN_RUNTIME_PYTHON
)

function Assert-DataPynHostedWindowsRunner {
    param([System.Collections.IDictionary]$Environment = @{
        GITHUB_ACTIONS = $env:GITHUB_ACTIONS; RUNNER_ENVIRONMENT = $env:RUNNER_ENVIRONMENT
        RUNNER_OS = $env:RUNNER_OS; RUNNER_ARCH = $env:RUNNER_ARCH; RUNNER_TEMP = $env:RUNNER_TEMP
    })
    if ($Environment['GITHUB_ACTIONS'] -ne 'true' -or
        $Environment['RUNNER_ENVIRONMENT'] -ne 'github-hosted' -or
        $Environment['RUNNER_OS'] -ne 'Windows' -or $Environment['RUNNER_ARCH'] -ne 'X64') {
        throw 'Installer acceptance is allowed only on a GitHub-hosted Windows x64 runner. Never run it on a user computer.'
    }
    $temporary = [string]$Environment['RUNNER_TEMP']
    if (-not $temporary -or -not [System.IO.Path]::IsPathRooted($temporary)) {
        throw 'RUNNER_TEMP must be an absolute hosted-runner temporary directory.'
    }
    $root = [System.IO.Path]::GetFullPath($temporary).TrimEnd('\')
    if (-not [System.IO.Directory]::Exists($root) -or $root -eq [System.IO.Path]::GetPathRoot($root).TrimEnd('\')) {
        throw 'RUNNER_TEMP is absent or resolves to a filesystem root.'
    }
    return $root
}

function Get-DataPynSilentInstallArguments {
    param([Parameter(Mandatory = $true)][string]$InstallDirectory)
    # NSIS parses /D as the entire remaining command line. It must be last and
    # unquoted, including when the path deliberately contains spaces.
    return @('/S', '/NS', ('/D=' + $InstallDirectory))
}

function Get-DataPynSilentUninstallArguments {
    param([Parameter(Mandatory = $true)][string]$InstallDirectory)
    # _?= prevents the uninstaller from relaunching a temp copy and makes the
    # waited process represent the actual uninstall. It is also last/unquoted.
    return @('/S', ('_?=' + $InstallDirectory))
}

function Read-DataPynUninstallRecord {
    param([string]$ProductName, [Microsoft.Win32.RegistryHive]$Hive = 'CurrentUser',
          [Microsoft.Win32.RegistryView]$View = 'Registry64')
    $base = [Microsoft.Win32.RegistryKey]::OpenBaseKey($Hive, $View)
    try {
        $key = $base.OpenSubKey("Software\Microsoft\Windows\CurrentVersion\Uninstall\$ProductName")
        if ($null -eq $key) { return $null }
        try {
            $values = [ordered]@{}
            foreach ($name in ($key.GetValueNames() | Sort-Object)) { $values[$name] = $key.GetValue($name) }
            return $values
        } finally { $key.Dispose() }
    } finally { $base.Dispose() }
}

function Get-DataPynOdbcFingerprint {
    $name = Get-DataPynOdbcDriver
    if (-not $name) { throw 'Microsoft ODBC 17/18 x64 is not available after preparation.' }
    $base = [Microsoft.Win32.RegistryKey]::OpenBaseKey('LocalMachine', 'Registry64')
    try {
        $key = $base.OpenSubKey("SOFTWARE\ODBC\ODBCINST.INI\$name")
        try { $path = [string]$key.GetValue('Driver') } finally { $key.Dispose() }
    } finally { $base.Dispose() }
    return [ordered]@{ name = $name; path = $path; sha256 = (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash }
}

function Invoke-DataPynCiProcess {
    param([string]$FilePath, [string[]]$Arguments, [string]$LogBase, [int[]]$SuccessCodes = @(0))
    $null = Assert-DataPynHostedWindowsRunner
    $process = Start-Process -FilePath $FilePath -ArgumentList $Arguments -WindowStyle Hidden -Wait -PassThru `
        -RedirectStandardOutput ($LogBase + '.out.log') -RedirectStandardError ($LogBase + '.err.log')
    if ($process.ExitCode -notin $SuccessCodes) {
        foreach ($log in @(($LogBase + '.out.log'), ($LogBase + '.err.log'))) {
            if (Test-Path -LiteralPath $log) { Get-Content -LiteralPath $log -Tail 30 | Write-Host }
        }
        throw "Process $([System.IO.Path]::GetFileName($FilePath)) failed with exit code $($process.ExitCode). Logs: $LogBase"
    }
    return [int]$process.ExitCode
}

function Invoke-DataPynWindowsInstallationSmoke {
    param([string]$InstallerPath, [string]$PythonPath)
    # Perform this check before registry writes, MSI execution, or setup execution.
    $runnerRoot = Assert-DataPynHostedWindowsRunner
    $ErrorActionPreference = 'Stop'
    foreach ($module in @('Microsoft.PowerShell.Management', 'Microsoft.PowerShell.Utility', 'Microsoft.PowerShell.Security')) {
        Import-Module (Join-Path $PSHOME ('Modules/' + $module)) -ErrorAction Stop
    }
    $repository = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../..'))
    $configuration = Get-Content -LiteralPath (Join-Path $repository 'desktop/src-tauri/tauri.conf.json') -Raw | ConvertFrom-Json
    $productName = [string]$configuration.productName
    if ($productName -ne 'DataPyn Tauri' -or $configuration.identifier -ne 'app.datapyn.tauri') {
        throw 'This smoke only accepts the isolated production DataPyn Tauri identity.'
    }
    if (-not $InstallerPath -or -not (Test-Path -LiteralPath $InstallerPath -PathType Leaf)) {
        throw 'Provide the generated signed NSIS setup with -InstallerPath or DATAPYN_NSIS_INSTALLER.'
    }
    $InstallerPath = (Resolve-Path -LiteralPath $InstallerPath).Path
    if (-not $InstallerPath.EndsWith('.exe', [System.StringComparison]::OrdinalIgnoreCase) -or
        -not (Test-Path -LiteralPath ($InstallerPath + '.sig') -PathType Leaf)) {
        throw 'NSIS updater installer and its detached Tauri signature are required; verify the signature before this smoke.'
    }
    if (-not $PythonPath) { $PythonPath = Join-Path $repository '.venv/Scripts/python.exe' }
    if (-not (Test-Path -LiteralPath $PythonPath -PathType Leaf)) { throw 'The CI Python interpreter is unavailable.' }
    $PythonPath = (Resolve-Path -LiteralPath $PythonPath).Path

    foreach ($view in @('Registry64', 'Registry32')) {
        if ((Read-DataPynUninstallRecord -ProductName $productName -View $view) -or
            (Read-DataPynUninstallRecord -ProductName $productName -Hive LocalMachine -View $view)) {
            throw 'The hosted runner already has DataPyn Tauri installed. Refusing to replace it.'
        }
    }
    $legacyBefore = @(
        foreach ($hive in @('CurrentUser', 'LocalMachine')) {
            foreach ($view in @('Registry64', 'Registry32')) {
                Read-DataPynUninstallRecord -ProductName 'DataPyn' -Hive $hive -View $view | ConvertTo-Json -Depth 6 -Compress
            }
        }
    ) | ConvertTo-Json -Compress

    $testRoot = Join-Path $runnerRoot ('datapyn-tauri-installer-' + [Guid]::NewGuid().ToString('N'))
    $installDirectory = [System.IO.Path]::GetFullPath((Join-Path $testRoot 'DataPyn Tauri with spaces'))
    $prefix = $runnerRoot.TrimEnd('\') + '\'
    if (-not $installDirectory.StartsWith($prefix, [System.StringComparison]::OrdinalIgnoreCase) -or
        (Test-Path -LiteralPath $testRoot)) { throw 'Installer test target must be a fresh child of RUNNER_TEMP.' }
    New-Item -ItemType Directory -Path $testRoot | Out-Null

    . (Join-Path $repository 'desktop/src-tauri/windows/install-odbc.ps1')
    if (-not (Get-DataPynOdbcDriver)) {
        $identity = [System.Security.Principal.WindowsPrincipal]::new([System.Security.Principal.WindowsIdentity]::GetCurrent())
        if (-not $identity.IsInRole([System.Security.Principal.WindowsBuiltInRole]::Administrator)) {
            throw 'Hosted CI needs its administrator token to provision the Microsoft ODBC build prerequisite without UAC.'
        }
        $prerequisite = Get-Content -LiteralPath (Join-Path $repository 'scripts/tauri/windows-prerequisites.json') -Raw | ConvertFrom-Json
        $msi = Join-Path $repository ('build/windows-prerequisites/' + $prerequisite.filename)
        Assert-DataPynOdbcInstaller -Path $msi -ExpectedSha256 $prerequisite.sha256
        $msiArguments = @('/i', ('"' + $msi + '"'), '/qn', '/norestart', 'IACCEPTMSODBCSQLLICENSETERMS=YES',
                          '/L*v', ('"' + (Join-Path $testRoot 'odbc-msi.log') + '"'))
        $null = Invoke-DataPynCiProcess -FilePath (Join-Path $env:WINDIR 'System32/msiexec.exe') `
            -Arguments $msiArguments -LogBase (Join-Path $testRoot 'odbc') -SuccessCodes @(0, 3010)
    }
    $odbcBefore = Get-DataPynOdbcFingerprint | ConvertTo-Json -Compress
    $main = Join-Path $installDirectory 'datapyn-desktop.exe'
    $sidecar = Join-Path $installDirectory 'datapyn-runtime.exe'
    $uninstaller = Join-Path $installDirectory 'uninstall.exe'
    $installationAttempted = $false
    $uninstalled = $false
    $stateEnvironment = @{
        DATAPYN_RUNTIME_STATE_PATH = (Join-Path $testRoot 'state')
        DATAPYN_WORKSPACE_PATH = (Join-Path $testRoot 'workspace')
        DATAPYN_RUNTIME_DATA_DIR = (Join-Path $testRoot 'packages')
        DATAPYN_SNAPSHOT_ROOT = (Join-Path $testRoot 'snapshots')
    }
    $previousEnvironment = @{}
    foreach ($key in $stateEnvironment.Keys) {
        $previousEnvironment[$key] = [System.Environment]::GetEnvironmentVariable($key)
        [System.Environment]::SetEnvironmentVariable($key, $stateEnvironment[$key])
    }
    try {
        $installationAttempted = $true
        $null = Invoke-DataPynCiProcess -FilePath $InstallerPath -Arguments (Get-DataPynSilentInstallArguments $installDirectory) `
            -LogBase (Join-Path $testRoot 'setup') -SuccessCodes @(0, 3010)
        foreach ($path in @($main, $sidecar, $uninstaller)) {
            if (-not (Test-Path -LiteralPath $path -PathType Leaf) -or (Get-Item -LiteralPath $path).Length -eq 0) {
                throw "Installed artifact is missing or empty: $path"
            }
        }
        $record = Read-DataPynUninstallRecord -ProductName $productName
        if (-not $record -or $record['DisplayName'] -ne $productName -or
            $record['DisplayVersion'] -ne $configuration.version -or $record['MainBinaryName'] -ne 'datapyn-desktop.exe' -or
            -not [string]::Equals(([string]$record['InstallLocation']).Trim('"'), $installDirectory, [System.StringComparison]::OrdinalIgnoreCase) -or
            -not [string]::Equals(([string]$record['UninstallString']).Trim('"'), $uninstaller, [System.StringComparison]::OrdinalIgnoreCase)) {
            throw 'The installed HKCU uninstall record does not match the isolated per-user app and its explicit install directory.'
        }
        foreach ($view in @('Registry64', 'Registry32')) {
            if (Read-DataPynUninstallRecord -ProductName $productName -Hive LocalMachine -View $view) {
                throw 'DataPyn was registered as a machine installation instead of currentUser.'
            }
        }
        # Run only the installed headless sidecar. Never open the desktop GUI.
        foreach ($smoke in @('smoke_runtime.py', 'smoke_parity.py', 'smoke_persistence.py', 'smoke_distribution.py')) {
            $script = Join-Path $repository ('scripts/tauri/' + $smoke)
            Write-Host "Installed sidecar acceptance: $smoke"
            $null = Invoke-DataPynCiProcess -FilePath $PythonPath -Arguments @(('"' + $script + '"'), '--executable', ('"' + $sidecar + '"')) `
                -LogBase (Join-Path $testRoot $smoke)
        }
        $null = Invoke-DataPynCiProcess -FilePath $uninstaller -Arguments (Get-DataPynSilentUninstallArguments $installDirectory) `
            -LogBase (Join-Path $testRoot 'uninstall')
        $uninstalled = $true
        foreach ($path in @($main, $sidecar)) {
            if (Test-Path -LiteralPath $path) { throw "Uninstall preserved an application executable: $path" }
        }
        foreach ($view in @('Registry64', 'Registry32')) {
            if (Read-DataPynUninstallRecord -ProductName $productName -View $view) {
                throw 'Tauri uninstall left its per-user app registration behind.'
            }
        }
        if ((Get-DataPynOdbcFingerprint | ConvertTo-Json -Compress) -ne $odbcBefore) {
            throw 'Tauri installation/uninstall modified or removed the shared Microsoft ODBC driver.'
        }
        $legacyAfter = @(
            foreach ($hive in @('CurrentUser', 'LocalMachine')) {
                foreach ($view in @('Registry64', 'Registry32')) {
                    Read-DataPynUninstallRecord -ProductName 'DataPyn' -Hive $hive -View $view | ConvertTo-Json -Depth 6 -Compress
                }
            }
        ) | ConvertTo-Json -Compress
        if ($legacyAfter -ne $legacyBefore) { throw 'The PyQt installer identity was changed by Tauri.' }
        [ordered]@{ status = 'passed'; product = $productName; version = $configuration.version;
                    installed_sidecar_smokes = 4; scope = 'currentUser'; odbc_preserved = $true;
                    pyqt_identity_preserved = $true; logs = $testRoot } | ConvertTo-Json -Compress | Write-Host
    } finally {
        if ($installationAttempted -and -not $uninstalled -and (Test-Path -LiteralPath $uninstaller -PathType Leaf)) {
            try {
                $null = Invoke-DataPynCiProcess -FilePath $uninstaller -Arguments (Get-DataPynSilentUninstallArguments $installDirectory) `
                    -LogBase (Join-Path $testRoot 'cleanup-uninstall')
            } catch { Write-Warning ('Hosted CI cleanup failed: ' + $_.Exception.Message) }
        }
        # RUNNER_TEMP is owned/cleaned by GitHub. Keep logs; never recursively
        # delete a computed installation path or uninstall a shared driver.
        foreach ($key in $previousEnvironment.Keys) {
            [System.Environment]::SetEnvironmentVariable($key, $previousEnvironment[$key])
        }
    }
}

if ($MyInvocation.InvocationName -ne '.') {
    Invoke-DataPynWindowsInstallationSmoke -InstallerPath $InstallerPath -PythonPath $PythonPath
}
