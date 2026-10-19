@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\pythonw.exe" (
  echo Run setup.ps1 first to create the Python environment.
  pause
  exit /b 1
)
start "" ".venv\Scripts\pythonw.exe" "hochan_pet.py" %*
