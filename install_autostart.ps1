param(
    [switch]$Uninstall
)

$ErrorActionPreference = 'Stop'
$shortcutPath = Join-Path ([Environment]::GetFolderPath('Startup')) 'Department Fines Tracker.lnk'

if ($Uninstall) {
    if (Test-Path $shortcutPath) {
        Remove-Item $shortcutPath
        Write-Host 'Removed Department Fines Tracker from startup.'
    } else {
        Write-Host 'Department Fines Tracker is not configured to start automatically.'
    }
    exit 0
}

$projectRoot = $PSScriptRoot
$appPath = Join-Path $projectRoot 'app.py'
$pythonwPath = Join-Path $projectRoot 'venv\Scripts\pythonw.exe'

if (-not (Test-Path $appPath)) {
    throw "app.py was not found in $projectRoot. Run this script from the project folder."
}

if (-not (Test-Path $pythonwPath)) {
    throw "The project virtual environment was not found at $pythonwPath. Set up the venv and install requirements first."
}

$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($shortcutPath)
$shortcut.TargetPath = $pythonwPath
$shortcut.Arguments = "`"$appPath`""
$shortcut.WorkingDirectory = $projectRoot
$shortcut.Description = 'Start the Department Fines Tracker when this user signs in.'
$shortcut.Save()

Write-Host 'Startup configured. The tracker will start when this Windows user signs in.'
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