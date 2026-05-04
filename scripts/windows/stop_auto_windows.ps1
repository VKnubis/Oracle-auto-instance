$ErrorActionPreference = "SilentlyContinue"

$taskName = "LoopOracleAutoLaunch"
Unregister-ScheduledTask -TaskName $taskName -Confirm:$false

Write-Host "Stopped Windows auto mode."
