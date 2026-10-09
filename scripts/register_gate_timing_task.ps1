<#
Registers the Scheduled Task that drives scripts/gate_timing_runner.py (#1699).

Elevated (RunLevel Highest) and INTERACTIVE for the current user: the runner reads the idle
clock of the user's session, which a non-interactive task cannot see. A tick every 5 minutes;
the runner decides whether the box is idle, on AC and quiet. IgnoreNew keeps a running gate
from being overlapped. No power setting is touched and the machine is not woken.
Remove with:  Unregister-ScheduledTask -TaskName BlarAI-Gate-Timing -Confirm:$false
Usage: pwsh -File scripts/register_gate_timing_task.ps1 -Python <venv pythonw> -Runner <runner copy> -StateDir <dir>
#>
param(
    [Parameter(Mandatory)][string]$Python,
    [Parameter(Mandatory)][string]$Runner,
    [Parameter(Mandatory)][string]$StateDir
)
$ErrorActionPreference = 'Stop'
if (-not (Test-Path (Join-Path $StateDir 'state.json'))) { throw "no state.json in $StateDir; run gate_timing_runner.py init first" }
if (-not (Test-Path $Runner)) { throw "runner not found: $Runner" }
$action = New-ScheduledTaskAction -Execute $Python -Argument "`"$Runner`" tick --state-dir `"$StateDir`""
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) -RepetitionInterval (New-TimeSpan -Minutes 5) -RepetitionDuration (New-TimeSpan -Days 3)
$principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive -RunLevel Highest
$settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Hours 3)
Register-ScheduledTask -TaskName 'BlarAI-Gate-Timing' -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Force | Out-Null
Get-ScheduledTask -TaskName 'BlarAI-Gate-Timing' | Select-Object TaskName, State
