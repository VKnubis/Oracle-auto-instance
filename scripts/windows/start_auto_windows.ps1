$ErrorActionPreference = "Stop"

$taskName = "LoopOracleAutoLaunch"
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectDir = Split-Path -Parent (Split-Path -Parent $scriptDir)
$pythonPath = Join-Path $projectDir ".venv\Scripts\python.exe"
$scriptPath = Join-Path $projectDir "scripts\windows\run_with_random_delay.py"

if (-not (Test-Path $pythonPath)) {
    & powershell -ExecutionPolicy Bypass -File (Join-Path $projectDir "scripts\windows\setup_windows.ps1")
}

$action = New-ScheduledTaskAction -Execute $pythonPath -Argument "`"$scriptPath`"" -WorkingDirectory $projectDir
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) -RepetitionInterval (New-TimeSpan -Minutes 5)
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable

Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Settings $settings -Force | Out-Null

Write-Host "Started Windows auto mode."
Write-Host "Task name: $taskName"
Write-Host "It runs every 5 minutes plus a random delay up to 10 minutes while this PC is awake."
