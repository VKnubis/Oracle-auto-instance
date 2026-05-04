@echo off
cd /d "%~dp0"
".venv\Scripts\python.exe" scripts\windows\check_oci_config.py
pause
