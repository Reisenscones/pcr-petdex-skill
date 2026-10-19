@echo off
call "%~dp0start-hochan.cmd" --preview idle --no-codex-observer --status-file "%~dp0state\preview\codex-status.json" %*
