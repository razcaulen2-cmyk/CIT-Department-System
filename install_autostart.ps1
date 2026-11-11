param(
    [switch]$Uninstall
)

$ErrorActionPreference = 'Stop'
$taskName = 'Department Fines Tracker'
$startupShortcut = Join-Path ([Environment]::GetFolderPath('Startup')) 'Department Fines Tracker.lnk'

if ($Uninstall) {
    $task = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
    if ($task) {
        Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
        Write-Host 'Removed Department Fines Tracker from startup.'
    } else {
        Write-Host 'Department Fines Tracker is not configured as a startup task.'
    }

    if (Test-Path $startupShortcut) {
        Remove-Item -LiteralPath $startupShortcut
    }
    exit 0
}

$projectRoot = $PSScriptRoot
$appPath = Join-Path $projectRoot 'app.py'
$pythonPath = Join-Path $projectRoot 'venv\Scripts\python.exe'
$pythonwPath = Join-Path $projectRoot 'venv\Scripts\pythonw.exe'
$launcherPath = Join-Path $projectRoot 'run_autostart.py'

foreach ($requiredPath in @($appPath, $pythonPath, $pythonwPath, $launcherPath)) {
    if (-not (Test-Path $requiredPath)) {
        throw "Required startup file was not found: $requiredPath"
    }
}

$currentUser = [Security.Principal.WindowsIdentity]::GetCurrent().Name
$action = New-ScheduledTaskAction `
    -Execute $pythonwPath `
    -Argument "`"$launcherPath`"" `
    -WorkingDirectory $projectRoot
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $currentUser
$principal = New-ScheduledTaskPrincipal -UserId $currentUser -LogonType Interactive -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet `
    -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit ([TimeSpan]::Zero) `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable

Register-ScheduledTask `
    -TaskName $taskName `
    -Action $action `
    -Trigger $trigger `
    -Principal $principal `
    -Settings $settings `
    -Description 'Start the CIT Department System when this Windows user signs in.' `
    -Force | Out-Null

if (Test-Path $startupShortcut) {
    Remove-Item -LiteralPath $startupShortcut
}

Write-Host 'Startup task configured. The tracker will start when this Windows user signs in.'
Write-Host 'On this computer, open http://127.0.0.1:5000.'
$lanAddress = Get-NetIPConfiguration |
    Where-Object { $_.IPv4DefaultGateway -and $_.IPv4Address } |
    ForEach-Object {
        $_.IPv4Address |
            Where-Object { $_.IPAddress -notlike '169.254.*' } |
            Select-Object -ExpandProperty IPAddress
    } |
    Select-Object -First 1
if ($lanAddress) {
    Write-Host "On office computers, open http://${lanAddress}:5000."
}
