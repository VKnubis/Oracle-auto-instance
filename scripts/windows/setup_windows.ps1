$ErrorActionPreference = "Stop"

if (-not (Test-Path ".venv")) {
    python -m venv .venv
}

.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\pip.exe install -r requirements.txt

if (-not (Test-Path ".env")) {
    Copy-Item "config\config.example.env" ".env"
}

Write-Host ""
Write-Host "Setup complete."
Write-Host "Next:"
Write-Host "1. Edit .env and fill your Oracle values."
Write-Host "2. Create OCI API config at C:\Users\$env:USERNAME\.oci\config."
Write-Host "3. Run run_once_windows.bat to test."
