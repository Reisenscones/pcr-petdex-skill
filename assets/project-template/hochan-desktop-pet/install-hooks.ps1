param(
    [switch]$Remove,
    [string]$CodexHome,
    [switch]$NoEnableHookFeature
)

$ErrorActionPreference = 'Stop'
if (-not $CodexHome) {
    $CodexHome = if ($env:CODEX_HOME) { $env:CODEX_HOME } else { Join-Path $HOME '.codex' }
}
$CodexHome = [IO.Path]::GetFullPath($CodexHome)
$hooksPath = Join-Path $CodexHome 'hooks.json'
$hookPath = Join-Path $PSScriptRoot 'hooks\codex-hochan-hook.ps1'
$stateDirectory = Join-Path $PSScriptRoot 'state'
$powerShellPath = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
$normalizedHook = $hookPath.Replace('\', '/')
$command = '& "{0}" -NoProfile -ExecutionPolicy Bypass -File "{1}" -StateDirectory "{2}"' -f $powerShellPath.Replace('\', '/'), $normalizedHook, $stateDirectory.Replace('\', '/')
$eventTimeouts = [ordered]@{
    SessionStart = 10; UserPromptSubmit = 10; PreToolUse = 10; PostToolUse = 10
    Stop = 10; Interrupt = 3; PreCompact = 10; PostCompact = 10
    SubagentStart = 10; SubagentStop = 10; SessionEnd = 3; PermissionRequest = 600
}

function Get-ConfigHash {
    if (Test-Path -LiteralPath $hooksPath) {
        $hash = [Security.Cryptography.SHA256]::Create()
        try { return [BitConverter]::ToString($hash.ComputeHash([IO.File]::ReadAllBytes($hooksPath))).Replace('-', '') }
        finally { $hash.Dispose() }
    }
    return ''
}

function Get-CodexExecutable {
    $bundled = @(Get-ChildItem -Path (Join-Path $env:LOCALAPPDATA 'OpenAI\Codex\bin\*\codex.exe') -ErrorAction SilentlyContinue | Sort-Object LastWriteTime -Descending)
    if ($bundled.Count) { return $bundled[0].FullName }
    $cli = Get-Command codex -ErrorAction SilentlyContinue
    if ($cli) { return $cli.Source }
    return ''
}

if (-not (Test-Path -LiteralPath $hookPath)) { throw "Missing hook script: $hookPath" }
$sha = [Security.Cryptography.SHA256]::Create()
try { $lockKey = [BitConverter]::ToString($sha.ComputeHash([Text.Encoding]::UTF8.GetBytes($hooksPath.ToLowerInvariant()))).Replace('-', '') }
finally { $sha.Dispose() }
$installMutex = New-Object Threading.Mutex($false, ('Local\HoChanHooks-' + $lockKey))
$locked = $false
try {
    try { $locked = $installMutex.WaitOne(10000) } catch [Threading.AbandonedMutexException] { $locked = $true }
    if (-not $locked) { throw 'Another Ho-chan hook installer is running.' }
    $originalHash = Get-ConfigHash
    if ($originalHash) {
        $config = Get-Content -LiteralPath $hooksPath -Raw -Encoding UTF8 | ConvertFrom-Json
        if ($null -eq $config -or $config -isnot [pscustomobject]) { throw 'hooks.json must contain a JSON object.' }
    } else { $config = [pscustomobject]@{ hooks = [pscustomobject]@{} } }
    if ($config.PSObject.Properties.Name -notcontains 'hooks') {
        $config | Add-Member -NotePropertyName hooks -NotePropertyValue ([pscustomobject]@{})
    }
    if ($config.hooks -isnot [pscustomobject]) { throw 'The hooks field must be a JSON object; existing configuration was left untouched.' }
    $removedCount = 0
    foreach ($eventProperty in @($config.hooks.PSObject.Properties)) {
        $keptGroups = @()
        foreach ($group in @($eventProperty.Value)) {
            $remaining = @()
            $matched = $false
            foreach ($handler in @($group.hooks)) {
                $handlerCommand = ([string]$handler.command).Replace('\', '/')
                if ($handlerCommand.IndexOf($normalizedHook, [StringComparison]::OrdinalIgnoreCase) -ge 0) {
                    $matched = $true
                    $removedCount++
                } else { $remaining += $handler }
            }
            if (-not $matched) { $keptGroups += $group }
            elseif ($remaining.Count) {
                $copy = [ordered]@{}
                foreach ($property in $group.PSObject.Properties) {
                    if ($property.Name -ne 'hooks') { $copy[$property.Name] = $property.Value }
                }
                $copy.hooks = @($remaining)
                $keptGroups += [pscustomobject]$copy
            }
        }
        $config.hooks.($eventProperty.Name) = @($keptGroups)
    }
    if (-not $Remove) {
        foreach ($eventName in $eventTimeouts.Keys) {
            $newGroup = [pscustomobject]@{ hooks = @([pscustomobject]@{
                type = 'command'; command = $command; timeout = $eventTimeouts[$eventName]
            }) }
            $groups = @($newGroup) + @($config.hooks.$eventName | Where-Object { $null -ne $_ })
            if ($config.hooks.PSObject.Properties.Name -contains $eventName) { $config.hooks.$eventName = $groups }
            else { $config.hooks | Add-Member -NotePropertyName $eventName -NotePropertyValue $groups }
        }
    }
    $json = ($config | ConvertTo-Json -Depth 100) + [Environment]::NewLine
    $oldJson = if ($originalHash) { [IO.File]::ReadAllText($hooksPath) } else { '' }
    if (($Remove -and $removedCount -eq 0) -or $json -ceq $oldJson) {
        Write-Host 'Hook configuration is already up to date.'
    } else {
        New-Item -ItemType Directory -Path $CodexHome -Force | Out-Null
        $temporary = $hooksPath + '.' + [Guid]::NewGuid().ToString('N') + '.tmp'
        try {
            [IO.File]::WriteAllText($temporary, $json, (New-Object Text.UTF8Encoding($false)))
            if ((Get-ConfigHash) -ne $originalHash) { throw 'hooks.json changed during installation. Run this installer again.' }
            if ($originalHash) {
                $backup = $hooksPath + '.bak-hochan-' + [DateTime]::Now.ToString('yyyyMMdd-HHmmss') + '-' + [Guid]::NewGuid().ToString('N')
                [IO.File]::Replace($temporary, $hooksPath, $backup)
                Write-Host ('Backup: ' + $backup)
            } else { [IO.File]::Move($temporary, $hooksPath) }
        } finally { if (Test-Path -LiteralPath $temporary) { Remove-Item -LiteralPath $temporary -Force } }
        Write-Host ('Updated: ' + $hooksPath)
    }
} finally {
    if ($locked) { $installMutex.ReleaseMutex() }
    $installMutex.Dispose()
}

if ($Remove) { Write-Host 'Ho-chan hooks removed. Restart Codex to reload hook definitions.'; return }
if (-not $NoEnableHookFeature) {
    $codexCli = Get-CodexExecutable
    if ($codexCli) {
        $previousHome = $env:CODEX_HOME
        try {
            $env:CODEX_HOME = $CodexHome
            $features = & $codexCli features list 2>$null
            if ($LASTEXITCODE -ne 0) { throw 'Could not read Codex features.' }
            if ($features -match '^hooks\s+\S+\s+false\s*$') {
                $configPath = Join-Path $CodexHome 'config.toml'
                if (Test-Path -LiteralPath $configPath) { Copy-Item -LiteralPath $configPath -Destination ($configPath + '.bak-hochan-' + [Guid]::NewGuid().ToString('N')) }
                & $codexCli features enable hooks
                if ($LASTEXITCODE -ne 0) { throw 'Could not enable Codex hooks.' }
            }
        } finally { $env:CODEX_HOME = $previousHome }
    } else { Write-Warning 'Codex CLI was not found. Verify that hooks are enabled in your Codex client.' }
}
Write-Host ('Registered 12 Ho-chan hooks. State directory: ' + $stateDirectory)
Write-Host 'Run review-hooks.cmd, enter /hooks, and review/trust the Ho-chan definitions.'
Write-Host 'Then start a new task or fully restart Codex Desktop. Start the pet with start-hochan.cmd.'
