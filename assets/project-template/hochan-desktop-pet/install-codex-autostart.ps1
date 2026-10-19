param(
    [switch]$Remove,
    [switch]$NoStart
)

$ErrorActionPreference = 'Stop'
$stateDirectory = Join-Path $PSScriptRoot 'state'
$settingsPath = Join-Path $stateDirectory 'codex-autostart.json'
$watcherPath = Join-Path $PSScriptRoot 'codex_autostart.py'
$pythonwPath = Join-Path $PSScriptRoot '.venv\Scripts\pythonw.exe'
$startupDirectory = [Environment]::GetFolderPath('Startup')
$shortcutPath = Join-Path $startupDirectory 'Ho-chan Codex Autostart.lnk'
if (-not $Remove -and -not (Test-Path -LiteralPath $pythonwPath)) { throw 'Run setup.ps1 first.' }
if (-not (Test-Path -LiteralPath $watcherPath)) { throw "Missing watcher: $watcherPath" }

$shell = New-Object -ComObject WScript.Shell
if (Test-Path -LiteralPath $shortcutPath) {
    $existing = $shell.CreateShortcut($shortcutPath)
    if ($existing.TargetPath -ne $pythonwPath -or $existing.Arguments -ne ('"{0}"' -f $watcherPath)) {
        throw 'An autostart shortcut for another installation already exists. Disable that installation first.'
    }
}
New-Item -ItemType Directory -Force -Path $stateDirectory | Out-Null
$settings = [ordered]@{ enabled = (-not [bool]$Remove); project = $PSScriptRoot }
$temporary = $settingsPath + '.' + [Guid]::NewGuid().ToString('N') + '.tmp'
try {
    [IO.File]::WriteAllText($temporary, (($settings | ConvertTo-Json) + [Environment]::NewLine), (New-Object Text.UTF8Encoding($false)))
    if (Test-Path -LiteralPath $settingsPath) { [IO.File]::Replace($temporary, $settingsPath, [NullString]::Value) }
    else { [IO.File]::Move($temporary, $settingsPath) }
} finally { if (Test-Path -LiteralPath $temporary) { Remove-Item -LiteralPath $temporary -Force } }
if ($Remove) {
    if (Test-Path -LiteralPath $shortcutPath) { Remove-Item -LiteralPath $shortcutPath -Force }
    Write-Host 'Codex autostart disabled. The watcher exits within 3 seconds; the running pet is kept open.'
    return
}
New-Item -ItemType Directory -Force -Path $startupDirectory | Out-Null
$shortcut = $shell.CreateShortcut($shortcutPath)
$shortcut.TargetPath = $pythonwPath
$shortcut.Arguments = '"{0}"' -f $watcherPath
$shortcut.WorkingDirectory = $PSScriptRoot
$shortcut.Description = 'Start Ho-chan when the Codex desktop app opens.'
$shortcut.WindowStyle = 7
$shortcut.Save()
if (-not $NoStart) {
    # Start-Process inherits the caller's Windows job. Codex closes that job
    # when it exits, which used to kill both the watcher and the pet. Local
    # WMI creates the process outside the caller's job, in this user's session.
    $startup = ([wmiclass]'Win32_ProcessStartup').CreateInstance()
    $startup.ShowWindow = 0
    # Also leave WMI's own provider job, so its idle shutdown cannot stop us.
    $startup.CreateFlags = 0x01000000
    $created = ([wmiclass]'Win32_Process').Create(('"{0}" "{1}"' -f $pythonwPath, $watcherPath), $PSScriptRoot, $startup)
    if ($created.ReturnValue -ne 0) { throw ('Windows could not start the independent watcher. WMI return code: ' + $created.ReturnValue) }
    Write-Host ('Independent watcher launcher PID: ' + $created.ProcessId)
}
Write-Host 'Codex autostart enabled. The background watcher starts at Windows sign-in.'
Write-Host 'Opening Codex starts Ho-chan within 3 seconds. An already running pet is reused.'
Write-Host ('Startup shortcut: ' + $shortcutPath)
