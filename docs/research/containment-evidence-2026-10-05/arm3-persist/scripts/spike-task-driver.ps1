#requires -Version 5.1
<#
.SYNOPSIS
  Arm 3: how the operator side starts the spike account's task in probe mode and reads its result. Dot-source it after
  spike-lib.ps1 and spike-persist-lib.ps1 (it needs both, plus Import-WfpHelpers having run for Test-TcpConnect and
  Get-EnvSnapshot). No side effects on load.

  These functions are the ones spike-wfp.ps1 (arms 1 and 2) defines inline, copied here so the arm 3 scripts can use them without
  running that script; -SelfTest of the scripts that use them covers the pure parts. The task itself (spike-run-test.ps1 in
  probe mode, run as the account) is the arm 2 copy: its SHA-256 must equal the copy provisioned into C:\blarai-spike\bin.
#>

function Get-SpikeSidOrNull { try { return (Get-LocalUser -Name $script:SpikeUser -ErrorAction Stop).SID.Value } catch { return $null } }

function Start-SpikeTaskProved {
    # Start + prove it actually started (a password task whose account lacks SeBatchLogonRight stays Ready and never runs:
    # 0x41303). $Tick, when given, is the operator watchdog and runs between polls; it sets $script:opAbort to stop the wait.
    param([scriptblock]$Tick)
    $pre = [datetime]'1999-11-30'
    try { $pr = (Get-ScheduledTaskInfo -TaskPath $script:SpikeTaskPath -TaskName $script:SpikeTaskName -ErrorAction Stop).LastRunTime; if ($pr) { $pre = $pr } } catch {}
    Start-ScheduledTask -TaskPath $script:SpikeTaskPath -TaskName $script:SpikeTaskName
    $last = $null; $state = ''
    foreach ($i in 1..30) {
        Start-Sleep -Milliseconds 750
        if ($Tick) { & $Tick; if ($script:opAbort) { return [pscustomobject]@{ Started = $false; Detail = 'operator watchdog abort while waiting for the task to start' } } }
        $info = Get-ScheduledTaskInfo -TaskPath $script:SpikeTaskPath -TaskName $script:SpikeTaskName -ErrorAction SilentlyContinue
        $state = [string](Get-ScheduledTask -TaskPath $script:SpikeTaskPath -TaskName $script:SpikeTaskName -ErrorAction SilentlyContinue).State
        if ($info) { $last = $info.LastTaskResult }
        if (($info -and $info.LastRunTime -gt $pre) -or $state -eq 'Running') { return [pscustomobject]@{ Started = $true; Detail = "state=$state" } }
    }
    $hex = if ($null -ne $last) { '0x{0:X}' -f ([uint32]$last) } else { 'unknown' }
    $hint = switch ($hex) { '0x41303' { ' (SCHED_S_TASK_HAS_NOT_RUN: the account lacks the batch-logon right)' } '0x8007052E' { ' (logon failure: wrong password)' } '0x80070569' { ' (logon type not granted)' } default { '' } }
    return [pscustomobject]@{ Started = $false; Detail = "task never started (State=$state, LastTaskResult=$hex)$hint" }
}

function Wait-SpikeResult {
    param([string]$RunId, [int]$TimeoutSec, [scriptblock]$Tick)
    $path = Join-Path (Join-Path $script:SpikeRoot 'results') "result-$RunId.json"
    $deadline = (Get-Date).AddSeconds($TimeoutSec)
    while ((Get-Date) -lt $deadline) {
        # The results folder is writable by the spike account: Read-UntrustedJson refuses links and hard links, caps the size and parses data only.
        if (Test-PathExistsNoFollow $path) { Start-Sleep -Milliseconds 300; return (Read-UntrustedJson -Path $path) }
        if ($Tick) { & $Tick; if ($script:opAbort) { return $null } }
        Start-Sleep -Milliseconds 1000
    }
    return $null
}

function Write-SpikeRequest {
    param([string]$RunId, [string]$Mode, [int]$Hold, [bool]$ExpectedBlocked, [int]$ServerPort = 0)
    $o = [ordered]@{ run_id = $RunId; mode = $Mode; hold_seconds = $Hold; expected_blocked = $ExpectedBlocked; written = (Get-Date).ToString("yyyy-MM-dd'T'HH:mm:ss.fffzzz") }
    if ($Mode -eq 'client') { $o.server_port = $ServerPort }
    Write-JsonAtomic -Path (Join-Path $script:SpikeRoot 'bin\request.json') -Object $o
}

function Wait-SpikeTaskReady {
    param([int]$TimeoutSec = 30, [scriptblock]$Tick)
    $deadline = (Get-Date).AddSeconds($TimeoutSec)
    while ((Get-Date) -lt $deadline) {
        $st = [string](Get-ScheduledTask -TaskPath $script:SpikeTaskPath -TaskName $script:SpikeTaskName -ErrorAction SilentlyContinue).State
        if ($st -ne 'Running') { return $true }
        if ($Tick) { & $Tick; if ($script:opAbort) { return $false } }
        Start-Sleep -Milliseconds 500
    }
    return $false
}

function Invoke-ProbeTaskRun {
    # One run of the task in probe mode. Never throws on a failed run; callers read the fields.
    param([string]$RunId, [bool]$ExpectedBlocked, [int]$TimeoutSec, [scriptblock]$Tick)
    $o = [ordered]@{ run_id = $RunId; expected_blocked = $ExpectedBlocked; started = (Get-Date).ToString("yyyy-MM-dd'T'HH:mm:ss.fffzzz"); task_ready = $false; task_started = $false; task_start = $null
                     valid = $false; schema_violations = @(); token_sid = $null; outbound_probe = $null; finished = $null }
    $o.task_ready = Wait-SpikeTaskReady -Tick $Tick
    if ($o.task_ready) {
        $reqAt = [datetimeoffset]::Now
        Write-SpikeRequest -RunId $RunId -Mode 'probe' -Hold 5 -ExpectedBlocked $ExpectedBlocked
        $go = Start-SpikeTaskProved -Tick $Tick
        $o.task_start = $go; $o.task_started = [bool]$go.Started
        if ($go.Started) {
            $res = Wait-SpikeResult -RunId $RunId -TimeoutSec $TimeoutSec -Tick $Tick
            if (-not $res) { try { Stop-ScheduledTask -TaskPath $script:SpikeTaskPath -TaskName $script:SpikeTaskName } catch {} }
            else {
                $viol = @(Test-SpikeResultSchema $res)
                try { if ((ConvertTo-DateTimeOffset $res.started) -lt $reqAt.AddSeconds(-5)) { $viol += "result.started $($res.started) predates the request written at $($reqAt.ToString('o'))" } } catch { $viol += "result.started unreadable: $($_.Exception.Message)" }
                if ([string]$res.run_id -ne $RunId) { $viol += "result.run_id '$($res.run_id)' is not '$RunId'" }
                $o.schema_violations = @($viol); $o.valid = ($viol.Count -eq 0 -and $res.mode -eq 'probe')
                $id = $res.steps | Where-Object { $_.name -eq 'identity' } | Select-Object -First 1
                if ($id -and $id.data) { $o.token_sid = [string]$id.data.token_sid }
                $ob = $res.steps | Where-Object { $_.name -eq 'outbound_probe' } | Select-Object -First 1
                if ($ob) { $o.outbound_probe = $ob.data }
            }
        }
    }
    $o.finished = (Get-Date).ToString("yyyy-MM-dd'T'HH:mm:ss.fffzzz")
    return $o
}

function Get-ProbeOutcome {
    # PURE. blocked | open | no_result | wrong_sid from an Invoke-ProbeTaskRun observation.
    param($Run, [string]$Sid)
    if (-not $Run -or -not $Run.valid -or -not $Run.outbound_probe -or -not $Run.outbound_probe.probe) { return 'no_result' }
    if ([string]$Run.token_sid -ne $Sid) { return 'wrong_sid' }
    if ($Run.outbound_probe.probe.connected) { return 'open' }
    return 'blocked'
}

function Invoke-GuardedProbe {
    # The account's task is started ONLY if the fence is PRESENT. Otherwise nothing is started and the answer says why
    # ("fence absent"): this is the fail-closed-on-absence check in use. $Starter is injectable for -SelfTest.
    param([Parameter(Mandatory)]$Backend, [Parameter(Mandatory)][string]$RunId, [bool]$ExpectedBlocked = $true, [int]$TimeoutSec = 60, [scriptblock]$Tick, [scriptblock]$Starter)
    $g = Test-FenceAllowsAccount -Backend $Backend
    if (-not $g.Allowed) { return [ordered]@{ started = $false; guard = $g; outcome = 'fence_absent_not_started'; run = $null } }
    $run = if ($Starter) { & $Starter $RunId $ExpectedBlocked } else { Invoke-ProbeTaskRun -RunId $RunId -ExpectedBlocked $ExpectedBlocked -TimeoutSec $TimeoutSec -Tick $Tick }
    return [ordered]@{ started = $true; guard = $g; outcome = $null; run = $run }
}

function Assert-SpikePreflight {
    # Returns an array of problems (empty = go). Probe mode loads no model, so there is no free-RAM check.
    param([Parameter(Mandatory)][string]$ScriptFolder)
    $e = New-Object System.Collections.ArrayList
    if (-not (Test-IsElevated)) { [void]$e.Add('not elevated') }
    if (-not [Environment]::Is64BitProcess) { [void]$e.Add('not a 64-bit process (WFP struct layout is asserted for x64)') }
    $sid = Get-SpikeSidOrNull
    if (-not $sid) { [void]$e.Add("account $($script:SpikeUser) not found: run spike-provision.ps1 -Apply") }
    else { foreach ($m in (Get-SafeSidProblems -Sid $sid)) { [void]$e.Add($m) } }
    if (-not (Get-ScheduledTask -TaskPath $script:SpikeTaskPath -TaskName $script:SpikeTaskName -ErrorAction SilentlyContinue)) { [void]$e.Add("task $($script:SpikeTaskPath)$($script:SpikeTaskName) not registered") }
    foreach ($f in @('bin\spike-run-test.ps1', 'bin\spike_model.py', 'bin\spike-config.json')) { if (-not (Test-Path (Join-Path $script:SpikeRoot $f))) { [void]$e.Add("missing $($script:SpikeRoot)\$f") } }
    # The task runs the copies provision made. The copy must understand probe mode and must equal this folder's version.
    $binRun = Join-Path $script:SpikeRoot 'bin\spike-run-test.ps1'
    if (Test-Path $binRun) {
        if ((Get-Content -LiteralPath $binRun -Raw) -notmatch "'probe'") { [void]$e.Add("$binRun has no probe mode: copy the arm 2 spike-run-test.ps1 here and re-run spike-provision.ps1 -Apply") }
    }
    foreach ($f in @('spike-run-test.ps1', 'spike_model.py')) {
        $mine = Join-Path $ScriptFolder $f; $theirs = Join-Path $script:SpikeRoot "bin\$f"
        if (-not (Test-Path $mine)) { [void]$e.Add("$mine is missing: the live folder must hold the arm 2 spike-run-test.ps1 and spike_model.py beside these scripts"); continue }
        if (Test-Path $theirs) {
            if ((Get-NormalizedSha256 -Path $mine) -ne (Get-NormalizedSha256 -Path $theirs)) { [void]$e.Add("$theirs differs from $mine (re-run spike-provision.ps1 -Apply so the task runs the current script)") }
        }
    }
    return @($e)
}

function Invoke-WslShutdown {
    # `wsl --shutdown` before a live run, recorded with the distribution list before and after.
    $rec = [ordered]@{ at = (Get-Date).ToString("yyyy-MM-dd'T'HH:mm:ss.fffzzz"); before = $null; exit_code = $null; after = $null; error = $null }
    $list = { ((& wsl.exe --list --verbose 2>&1 | Out-String) -replace "`0", '') -split "`r?`n" | ForEach-Object { ($_ -replace '\s+', ' ').Trim() } | Where-Object { $_ } }
    try { $rec.before = @(& $list); & wsl.exe --shutdown 2>&1 | Out-Null; $rec.exit_code = $LASTEXITCODE; Start-Sleep -Seconds 2; $rec.after = @(& $list) } catch { $rec.error = $_.Exception.Message }
    return $rec
}

function Get-ArmEnvSnapshot {
    # The wrapped snapshot (clock, uptime, OS, Bitdefender processes, firewall profiles, BFE/mpssvc) plus the Windows build and PowerShell host.
    $snap = Get-EnvSnapshot
    try { $cv = Get-ItemProperty 'HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion'; $snap.windows_build = "$($cv.CurrentBuild).$($cv.UBR) ($($cv.DisplayVersion))" } catch { $snap.windows_build = "error: $($_.Exception.Message)" }
    $snap.ps_host = "$($Host.Name) $($PSVersionTable.PSVersion) ($($PSVersionTable.PSEdition))"
    return $snap
}

function New-WatchdogState {
    return @{ Count = 0; Fail = 0; Consec = 0; MaxConsec = 0; Aborted = $false; Events = (New-Object System.Collections.ArrayList); LastAt = -100.0; MaxGap = 0.0; Clock = [Diagnostics.Stopwatch]::StartNew() }
}

function Update-WatchdogState {
    # PURE on its arguments. One operator-connect result in; returns $true when the watchdog must abort (two consecutive
    # failures). Failure events are capped at 200 (the count keeps going).
    param([Parameter(Mandatory)]$State, [bool]$Ok, [string]$When = '', [string]$Message = '', [long]$Ms = 0)
    $State.Count++
    if ($Ok) { $State.Consec = 0; return $false }
    $State.Fail++; $State.Consec++
    if ($State.Consec -gt $State.MaxConsec) { $State.MaxConsec = $State.Consec }
    if ($State.Events.Count -lt 200) { [void]$State.Events.Add([ordered]@{ t = $When; error = $Message; ms = $Ms; consecutive = $State.Consec }) }
    return ($State.Consec -ge 2)
}
