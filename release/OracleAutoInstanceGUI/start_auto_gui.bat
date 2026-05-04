@echo off
cd /d "%~dp0\..\.."
powershell -ExecutionPolicy Bypass -File scripts\windows\start_auto_windows.ps1
pause
