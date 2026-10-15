#requires -Version 7.0
<#
.SYNOPSIS
  #1740 phase 2, arm A: run the same probe payload as the dedicated coder account.
  For the Lead Architect to run (double-click arm_a_operator.cmd), after the #775 flip.

.DESCRIPTION
  What it changes, and how each change is undone:
    * Registers ONE throwaway scheduled task, \BlarAI\BlarAI-1740-ArmA, that runs as
      blarai-coder with an S4U logon (no password stored). It is unregistered at the end,
      and its absence is checked and recorded.
    * Writes only inside C:\blarai-spike-1740 (the throwaway fixtures) and the -Out folder.
  It does not change the coder account, its groups, its profile or any real folder's
  permissions, and it does not touch the coder-leg task or the containment configuration.

  Each run: start a loopback listener, start the task, wait for the payload's result file,
  record it. Exit 0 when every run produced a result and the task is gone.
#>
[CmdletBinding()]
param(
    [int]$Runs = 3,
    [string]$Out = "$env:USERPROFILE\blarai-research-data\1740-arm-A",
    [string]$CoderUser = 'blarai-coder',
    [int]$RunTimeoutSec = 600
)
$ErrorActionPreference = 'Stop'
$root = 'C:\blarai-spike-1740'
$taskPath = '\BlarAI\'
$taskName = 'BlarAI-1740-ArmA'
$python = 'C:\Python314\python.exe'
$payload = Join-Path $root 'payload\arm_payload.py'
$worktree = Join-Path $root 'worktree'

$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) { Write-Host 'Run this elevated (arm_a_operator.cmd asks for it).' -ForegroundColor Red; exit 2 }
foreach ($p in (Join-Path $root 'fixtures.json'), $payload) {
    if (-not (Test-Path $p)) { Write-Host "Missing $p. The session that prepares phase 2 creates it first." -ForegroundColor Red; exit 2 }
}
if (Get-ScheduledTask -TaskPath $taskPath -TaskName $taskName -ErrorAction SilentlyContinue) {
    Write-Host "A task named $taskPath$taskName already exists; nothing was changed." -ForegroundColor Red; exit 2
}
New-Item -ItemType Directory -Force $Out | Out-Null

# Tools: the fixture copies when present (the coder cannot read the operator's npm folder).
$fx = Join-Path $root 'toolchain'
$tools = if (Test-Path $fx) {
    @{ node = "$fx\nodejs\node.exe"; git = "$fx\Git\cmd\git.exe"; bash = "$fx\Git\bin\bash.exe"; python = "$fx\Python314\python.exe"; opencode = "$fx\npm\opencode.cmd" }
} else {
    @{ node = 'C:\Program Files\nodejs\node.exe'; git = 'C:\Program Files\Git\cmd\git.exe'; bash = 'C:\Program Files\Git\bin\bash.exe'; python = $python; opencode = (Join-Path $env:USERPROFILE 'AppData\Roaming\npm\opencode.cmd') }
}
$toolsFile = Join-Path $root 'payload\tools-armA.json'
$tools | ConvertTo-Json | Set-Content $toolsFile -Encoding UTF8

$listener = [Net.Sockets.TcpListener]::new([Net.IPAddress]::Loopback, 0)
$listener.Start()
$port = ([Net.IPEndPoint]$listener.LocalEndpoint).Port
$summary = [ordered]@{ ticket = '#1740'; arm = 'A'; started = (Get-Date).ToString('o'); runs = @() }
$code = 0
try {
    for ($i = 1; $i -le $Runs; $i++) {
        $tag = 'A-{0}-r{1}' -f (Get-Date -Format 'yyyyMMddTHHmmss'), $i
        $resultFile = Join-Path $worktree "result-$tag.json"
        # --operator-home is THIS session's profile (the operator's): the task runs as the coder account, whose own
        # USERPROFILE would otherwise be probed instead of the operator's stores.
        $arg = "-I `"$payload`" --arm A --tag $tag --out `"$resultFile`" --tools `"$toolsFile`" --listener-port $port --operator-home `"$($env:USERPROFILE -replace '(\\+)$','$1$1')`""
        $action = New-ScheduledTaskAction -Execute $python -Argument $arg -WorkingDirectory $worktree
        $principal = New-ScheduledTaskPrincipal -UserId $CoderUser -LogonType S4U -RunLevel Limited
        $settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Seconds $RunTimeoutSec) -Hidden
        Register-ScheduledTask -TaskPath $taskPath -TaskName $taskName -Action $action -Principal $principal -Settings $settings | Out-Null
        $t0 = Get-Date
        Start-ScheduledTask -TaskPath $taskPath -TaskName $taskName
        while (-not (Test-Path $resultFile) -and ((Get-Date) - $t0).TotalSeconds -lt $RunTimeoutSec) {
            while ($listener.Pending()) { $listener.AcceptTcpClient().Close() }
            Start-Sleep -Milliseconds 500
        }
        Start-Sleep -Seconds 1
        $info = Get-ScheduledTaskInfo -TaskPath $taskPath -TaskName $taskName
        Unregister-ScheduledTask -TaskPath $taskPath -TaskName $taskName -Confirm:$false
        $rec = [ordered]@{ tag = $tag; wall_secs = [math]::Round(((Get-Date) - $t0).TotalSeconds, 2); last_task_result = ('0x{0:X}' -f [uint32]$info.LastTaskResult) }
        if (Test-Path $resultFile) {
            $rec.payload = Get-Content $resultFile -Raw | ConvertFrom-Json
            Remove-Item $resultFile
        } else { $rec.payload = $null; $code = 4 }
        ($rec | ConvertTo-Json -Depth 20) | Set-Content (Join-Path $Out "run-$tag.json") -Encoding UTF8
        $summary.runs += [ordered]@{ tag = $tag; result = [bool]$rec.payload; wall_secs = $rec.wall_secs }
        Write-Host ("run {0}: {1}" -f $i, $(if ($rec.payload) { 'result recorded' } else { 'NO RESULT' }))
    }
} finally {
    $listener.Stop()
    if (Get-ScheduledTask -TaskPath $taskPath -TaskName $taskName -ErrorAction SilentlyContinue) {
        Unregister-ScheduledTask -TaskPath $taskPath -TaskName $taskName -Confirm:$false
    }
    $summary.task_removed = -not [bool](Get-ScheduledTask -TaskPath $taskPath -TaskName $taskName -ErrorAction SilentlyContinue)
    if (-not $summary.task_removed) { $code = 7 }
    $summary.finished = (Get-Date).ToString('o'); $summary.exit_code = $code
    ($summary | ConvertTo-Json -Depth 6) | Set-Content (Join-Path $Out 'summary.json') -Encoding UTF8
}
Write-Host ''
Write-Host $(if ($code -eq 0) { "Done. Results are in $Out. The temporary task is removed." } else { "Finished with problems (code $code). Results so far are in $Out." }) -ForegroundColor $(if ($code -eq 0) { 'Green' } else { 'Yellow' })
exit $code
