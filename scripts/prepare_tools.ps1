param(
    [Parameter(Mandatory)][string]$Workspace,
    [string]$ViewerArchive
)

# Run after installing Python x64, PowerShell 7.4+, and the .NET 8 Desktop Runtime.
# Does not install hooks, enable autostart, or launch GUI programs.
$ErrorActionPreference = 'Stop'
$workspacePath = [IO.Path]::GetFullPath($Workspace)
$appDirectory = Join-Path $workspacePath 'hochan-desktop-pet'
if (-not (Test-Path -LiteralPath (Join-Path $appDirectory 'requirements.txt'))) {
    throw 'Create the workspace with create_workspace.py first.'
}
$pwshCommand = Get-Command pwsh -ErrorAction SilentlyContinue
$pythonCommand = Get-Command py -ErrorAction SilentlyContinue
if (-not $pythonCommand) { $pythonCommand = Get-Command python -ErrorAction SilentlyContinue }
$dotnetCommand = Get-Command dotnet -ErrorAction SilentlyContinue
if (-not $pwshCommand -or -not $pythonCommand -or -not $dotnetCommand) {
    throw 'Install Python x64 (3.11+), PowerShell 7.4+, and .NET 8 Desktop Runtime x64, then reopen the terminal. See references/windows-tools.md.'
}
$pwshVersion = & $pwshCommand.Source -NoProfile -Command '$PSVersionTable.PSVersion.ToString()'
if ($LASTEXITCODE -ne 0 -or [version]$pwshVersion -lt [version]'7.4') { throw 'PowerShell 7.4 or newer is required to load the .NET 8 assemblies.' }
$pythonArguments = @()
if ($pythonCommand.Name -eq 'py.exe') { $pythonArguments = @('-3') }
& $pythonCommand.Source @pythonArguments -c 'import sys,struct; assert sys.version_info >= (3,11) and struct.calcsize("P")==8, "Python 3.11+ x64 required"'
if ($LASTEXITCODE -ne 0) { throw 'Python version or architecture is unsuitable.' }
$runtimes = @(& $dotnetCommand.Source --list-runtimes)
if ($LASTEXITCODE -ne 0 -or -not ($runtimes -match '^Microsoft.NETCore.App 8\.') -or
    -not ($runtimes -match '^Microsoft.WindowsDesktop.App 8\.')) {
    throw 'Install Microsoft .NET 8 Desktop Runtime x64. A different major version alone is insufficient.'
}
$toolsDirectory = Join-Path $workspacePath '.tools'
New-Item -ItemType Directory -Path $toolsDirectory -Force | Out-Null
$expectedHash = 'C97F9DF5AA653DD85E88D865930FA591B6367B8D7A265A1B5FD068230D418778'
$url = 'https://github.com/ww-rm/SpineViewer/releases/download/v0.16.34/SpineViewer-v0.16.34.zip'
if ($ViewerArchive) {
    $archivePath = [IO.Path]::GetFullPath($ViewerArchive)
} else {
    $archivePath = Join-Path $toolsDirectory 'SpineViewer-v0.16.34.zip'
    if (-not (Test-Path -LiteralPath $archivePath)) {
        Invoke-WebRequest -Uri $url -OutFile $archivePath
    }
}
if ((Get-FileHash -LiteralPath $archivePath -Algorithm SHA256).Hash -ne $expectedHash) {
    throw 'SpineViewer archive checksum mismatch. Obtain the exact v0.16.34 standard Windows zip; do not bypass the check.'
}
$viewerDirectory = Join-Path $toolsDirectory 'SpineViewer-v0.16.34'
if (Test-Path -LiteralPath $viewerDirectory) {
    foreach ($name in @('SpineViewerCLI.exe', 'Spine.dll', 'SpineViewerCLI.runtimeconfig.json')) {
        if (-not (Test-Path -LiteralPath (Join-Path $viewerDirectory $name))) {
            throw "Existing viewer directory is incomplete: $name. Move that directory aside before retrying."
        }
    }
} else {
    Expand-Archive -LiteralPath $archivePath -DestinationPath $viewerDirectory
}
$cli = Join-Path $viewerDirectory 'SpineViewerCLI.exe'
$helpText = @(& $cli export --help 2>&1) -join "`n"
if ($LASTEXITCODE -ne 0 -or $helpText -notmatch '--fixed-view' -or $helpText -notmatch '--drop-last-frame') {
    throw 'SpineViewerCLI cannot run or lacks the required fixed-view export flags.'
}
$venvPython = Join-Path $appDirectory '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $venvPython)) {
    & $pythonCommand.Source @pythonArguments -m venv (Join-Path $appDirectory '.venv')
    if ($LASTEXITCODE -ne 0) { throw 'Python environment creation failed.' }
}
& $venvPython -m pip install -r (Join-Path $appDirectory 'requirements.txt')
if ($LASTEXITCODE -ne 0) { throw 'Python package installation failed.' }
Write-Host "Tools ready. Python: $venvPython"
Write-Host 'Next: query the model, inspect its configuration, and run tools/build_skin.py.'
