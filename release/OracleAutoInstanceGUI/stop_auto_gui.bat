@echo off
cd /d "%~dp0\..\.."
powershell -ExecutionPolicy Bypass -File scripts\windows\stop_auto_windows.ps1
pause
