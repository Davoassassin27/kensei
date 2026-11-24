@echo off
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0kensei.ps1" %*
exit /b %errorlevel%
