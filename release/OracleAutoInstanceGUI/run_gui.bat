@echo off
cd /d "%~dp0\..\.."
if not exist ".venv\Scripts\python.exe" (
  powershell -ExecutionPolicy Bypass -File scripts\windows\setup_windows.ps1
)
".venv\Scripts\python.exe" release\OracleAutoInstanceGUI\oracle_auto_instance_gui.py
pause
