@echo off
setlocal
cd /d "%~dp0"
set "HOCHAN_CODEX="
for /d %%D in ("%LOCALAPPDATA%\OpenAI\Codex\bin\*") do if exist "%%~D\codex.exe" set "HOCHAN_CODEX=%%~D\codex.exe"
echo Enter /hooks and review the Ho-chan hook definitions.
if defined HOCHAN_CODEX (
  "%HOCHAN_CODEX%" --no-alt-screen
) else (
  call codex --no-alt-screen
)
