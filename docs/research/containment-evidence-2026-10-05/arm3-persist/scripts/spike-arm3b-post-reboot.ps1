#requires -Version 5.1
<#
.SYNOPSIS
  Arm 3b, the step after the restart: runs ONCE as SYSTEM at startup (task blarai-arm3b-post-reboot, registered by the arming
  script). Ran once after the 2026-10-12 restart (claims row C10). It records whether the persistent filter set survived the restart, checks the account is blocked,
  REMOVES every persistent object by key, verifies the removal, writes post-reboot-result.json and deletes its own task.

.DESCRIPTION
  Modes (exactly one):
    -SelfTest  pure only: the verdict table, the network wait, the engine-open retry, and the whole post-reboot flow against fakes
               (the set survived; the set is gone; the set is partial; the engine cannot be read; no network; a removal that
               fails; the fail-closed gate refusing to start the account). No WFP call, no task change.
    -DryRun    prints the order of what -Live does, the files it writes and the tasks it deletes. Changes nothing.
    -Live      the real run (SYSTEM, elevated, 64-bit). Order:
                 record boot time, uptime, the arm state, the Windows/Bitdefender conditions -> read the fence state BY KEY (engine
                 retried for up to 5 minutes while BFE comes up): ABSENT / PRESENT / PARTIAL / UNKNOWN, with each object's flags ->
                 wait for the network (-NetworkTimeoutSeconds, default 600) -> operator control connects -> export the filters ->
                 the fail-closed gate: only if PRESENT the account's outbound probe runs (it must be blocked); if the fence is
                 absent the account's task is NOT started and the result says "fence absent" -> remove every object by key ->
                 verify ABSENT -> export again -> the gate must now refuse -> the account's probe, unguarded (egress must be open
                 again: the attribution control) -> write the result -> delete the tasks.
               A removal that cannot be verified keeps THIS task registered (it retries at the next startup) and says so.

  FOLDER RULE. Everything a SYSTEM or elevated task runs comes from the folder these scripts sit in. If a non-administrator process can write to that folder
  (or replace it), it can run code elevated. These scripts therefore refuse to register a SYSTEM task, and the elevated wrapper refuses to register or run,
  unless only SYSTEM, Administrators and TrustedInstaller can write to the folder and to every file in it (Test-AdminOnlyFolder). Keep them under an
  administrator-only folder such as C:\ProgramData\BlarAI; the rollback proof is written beside them for the same reason.
  The wrapped script is pinned (-WfpSha256, taken at arming); if it cannot be used the set is deleted through the self-contained snippet. A failed removal retries
  at the next startup for at most -MaxAttempts runs and -ExpiryHours after arming, then the task deletes itself and the result demands a manual rollback.
  Removal is verified by the engine reading ABSENT; the network is needed only for the probes, so a down network is reported as such (exit 4), never as
  "did not survive"; a repeat run, or an arm state with no recorded add, is exit 4 as well.

  The result is C:\...\arm3-persist\post-reboot-result.json (an earlier file is renamed, never overwritten). Its claim inputs:
  c10 = the set was PRESENT and persistent after a restart that is confirmed (boot time later than the arm time); c11 = the gate
  refused when the set was absent (after the removal, or at the start if the set had gone).

  EXIT CODES
    0 the set survived the restart (PRESENT, persistent), the account was blocked, removal verified, the gate refused afterwards
    1 the set was PRESENT but the account was NOT blocked
    4 inconclusive (no confirmed restart, no network, no valid probe, engine unreadable)
    6 the gate did NOT refuse when the set was absent
    7 removal NOT verified (this task stays registered and retries at the next startup)
    8 the set did NOT survive the restart (ABSENT at the start) - a result
    9 the set was PARTIAL after the restart - a result
#>
[CmdletBinding()]
param(
    [switch]$SelfTest,
    [switch]$DryRun,
    [switch]$Live,
    [int]$NetworkTimeoutSeconds = 600,
    [string]$WfpSha256,
    [string]$CodeSetId,
    [int]$MaxAttempts = 3,
    [int]$ExpiryHours = 24,
    [string]$TaskName = 'blarai-arm3b-post-reboot',
    [string]$VetoTaskName = 'blarai-arm3b-veto',
    [string]$WrapperTaskName = 'blarai-arm3b-arm-run',
    [string]$WfpScript,
    [string]$OutDir = 'C:\Users\_OPERATOR_\blarai-research-data\arm3-persist'
)
$ErrorActionPreference = 'Stop'
# The wrapped #1671 script defaults to the copy BESIDE these scripts (the admin-only folder), never to a user-writable path: its text becomes code in this process.
if (-not $WfpScript) { $WfpScript = Join-Path $PSScriptRoot 'wfp-coder-egress-spike.ps1' }
$script:LoadedLibHashes = @{}; $script:LoadedLibFolder = $PSScriptRoot
function Get-VerifiedLibBlock {
    # Reads a library ONCE, records the SHA-256 (CRLF read as LF) of exactly those bytes, and returns a scriptblock built from that same text for the caller to
    # dot-source at script scope: `. (Get-VerifiedLibBlock 'x.ps1')`. There is no second read, so what is hashed (for the rollback proof and the code-set id) is what runs.
    param([Parameter(Mandatory)][string]$Name)
    $bytes = [IO.File]::ReadAllBytes((Join-Path $PSScriptRoot $Name))
    $ms = New-Object IO.MemoryStream
    for ($i = 0; $i -lt $bytes.Length; $i++) { if ($bytes[$i] -eq 13 -and $i + 1 -lt $bytes.Length -and $bytes[$i + 1] -eq 10) { continue }; $ms.WriteByte($bytes[$i]) }
    $sha = [Security.Cryptography.SHA256]::Create()
    try { $script:LoadedLibHashes[$Name] = ([BitConverter]::ToString($sha.ComputeHash($ms.ToArray()))) -replace '-', '' } finally { $sha.Dispose(); $ms.Dispose() }
    return [scriptblock]::Create([Text.Encoding]::UTF8.GetString($bytes).TrimStart([char]0xFEFF))
}
. (Get-VerifiedLibBlock 'spike-lib.ps1')
. (Get-VerifiedLibBlock 'spike-persist-lib.ps1')
. (Get-VerifiedLibBlock 'spike-task-driver.ps1')
. (Get-VerifiedLibBlock 'spike-arm3b-common.ps1')

function Test-PostRebootArgs {
    param([bool]$SelfTest, [bool]$DryRun, [bool]$Live, [int]$NetTimeout, [int]$Attempts = 3, [int]$Expiry = 24)
    $e = New-Object System.Collections.ArrayList
    if ($Attempts -lt 1 -or $Attempts -gt 10) { [void]$e.Add("MaxAttempts must be 1..10 (got $Attempts)") }
    if ($Expiry -lt 1 -or $Expiry -gt 168) { [void]$e.Add("ExpiryHours must be 1..168 (got $Expiry)") }
    if (@(@($SelfTest, $DryRun, $Live) | Where-Object { $_ }).Count -ne 1) { [void]$e.Add('choose exactly one of -SelfTest, -DryRun, -Live') }
    if ($NetTimeout -lt 30 -or $NetTimeout -gt 1800) { [void]$e.Add("NetworkTimeoutSeconds must be 30..1800 (got $NetTimeout)") }
    return @($e)
}

function Get-PostRebootVerdict {
    # PURE. Safety first (removal), then whether the restart is confirmed, then what the set looked like, then the account.
    param([Parameter(Mandatory)]$Obs)
    if (-not $Obs.RemovalVerified) { return [pscustomobject]@{ Code = 7; Reason = 'removal NOT verified: this task stays registered and retries at the next startup; the README''s manual rollback is the fallback' } }
    if (-not $Obs.RebootConfirmed) { return [pscustomobject]@{ Code = 4; Reason = 'inconclusive: a restart since arming is not confirmed (boot time not later than the arm time, or the arm state was unreadable), so survival cannot be claimed' } }
    if (-not $Obs.AddRecorded) { return [pscustomobject]@{ Code = 4; Reason = 'inconclusive: the arm state records no add (arming did not complete), so there was nothing to survive; whatever was found has been removed' } }
    if ($Obs.RepeatAttempt) { return [pscustomobject]@{ Code = 4; Reason = 'inconclusive: this is a repeat run (an earlier attempt already acted on the set), so the state at startup does not show survival' } }
    switch ($Obs.FenceAtStart) {
        'ABSENT'  { return [pscustomobject]@{ Code = 8; Reason = 'the persistent set did NOT survive the restart (all four objects absent at startup, first run after a confirmed restart, with the add recorded; the network state does not bear on this); the gate refused to start the account' } }
        'PARTIAL' { return [pscustomobject]@{ Code = 9; Reason = 'the persistent set was PARTIAL after the restart; the gate refused to start the account' } }
        'UNKNOWN' { return [pscustomobject]@{ Code = 4; Reason = 'inconclusive: the engine could not be read at startup (fence state UNKNOWN)' } }
    }
    if (-not $Obs.AllPersistentAtStart) { return [pscustomobject]@{ Code = 4; Reason = 'inconclusive: the set was present after the restart but not every object reads back with the persistent flag' } }
    if (-not $Obs.NetworkUp) { return [pscustomobject]@{ Code = 4; Reason = 'inconclusive: the network never came up, so a blocked probe cannot be attributed to the filters' } }
    if (-not $Obs.ProbeValid) { return [pscustomobject]@{ Code = 4; Reason = 'inconclusive: the account''s probe did not start, gave no schema-valid result, or ran as the wrong SID' } }
    if (-not $Obs.ProbeBlocked) { return [pscustomobject]@{ Code = 1; Reason = 'the set survived the restart but the account was NOT blocked' } }
    if (-not $Obs.GuardRefusedAfterRemoval) { return [pscustomobject]@{ Code = 6; Reason = 'the gate did NOT refuse when the set was absent after the removal: the fail-closed check is broken' } }
    return [pscustomobject]@{ Code = 0; Reason = 'the persistent set survived the restart (all four objects, persistent), the account was blocked, removal by key verified, the gate refused once the set was gone' }
}

function Open-BackendWithRetry {
    # BFE may still be starting a minute after boot: retry the open. $Opener and $Sleep are injected for -SelfTest.
    param([scriptblock]$Opener, [scriptblock]$Sleep = { param($s) Start-Sleep -Seconds $s }, [int]$Attempts = 20, [int]$PollSeconds = 15)
    $last = ''
    for ($i = 1; $i -le $Attempts; $i++) {
        try { return [ordered]@{ Backend = (& $Opener); Attempts = $i; Error = $null } } catch { $last = $_.Exception.Message }
        if ($i -lt $Attempts) { & $Sleep $PollSeconds }
    }
    return [ordered]@{ Backend = $null; Attempts = $Attempts; Error = $last }
}

function Invoke-PostRebootCore {
    # $W: Backend, Cfg-independent scriptblocks (BootTime, Uptime, Env, ReadArmed, WaitNetwork, OperatorConnect, Export, Probe, UnregisterTask, Now)
    param([Parameter(Mandatory)]$W, [Parameter(Mandatory)]$Cfg)
    $r = [ordered]@{ spike = '#1682 arm 3b: persistence across a restart, absence detection, removal by key'; run_id = ('arm3b-' + (Get-Date -Format 'yyyyMMdd-HHmmss')); started = (& $W.Now) ; steps = [ordered]@{}; exports = @() }
    $obs = @{ AddRecorded = $false; RepeatAttempt = $false; RemovalVerified = $false; RebootConfirmed = $false; FenceAtStart = 'UNKNOWN'; AllPersistentAtStart = $false; NetworkUp = $false; ProbeValid = $false; ProbeBlocked = $false; GuardRefusedAfterRemoval = $false }
    $be = $W.Backend
    $r.steps.boot_time = (& $W.BootTime); $r.steps.uptime_seconds = (& $W.Uptime); $r.steps.env = (& $W.Env)
    $armed = & $W.ReadArmed
    $r.steps.arm_state = $armed
    if ($armed -and $armed.armed_at) {
        try { $obs.RebootConfirmed = ((ConvertTo-DateTimeOffset $r.steps.boot_time) -gt (ConvertTo-DateTimeOffset $armed.armed_at)) } catch { $obs.RebootConfirmed = $false }
    }
    $r.steps.reboot_confirmed = $obs.RebootConfirmed
    $obs.AddRecorded = [bool]($armed -and $armed.filters_added_at)
    $obs.RepeatAttempt = ([int]$Cfg.Attempt -gt 1)
    $r.attempt = [int]$Cfg.Attempt; $r.max_attempts = [int]$Cfg.MaxAttempts; $r.expired = [bool]$Cfg.Expired

    $fence0 = Get-FenceState -Backend $be
    $r.steps.fence_state_at_start = $fence0
    $obs.FenceAtStart = $fence0.State; $obs.AllPersistentAtStart = [bool]$fence0.AllPersistent
    $guard0 = Test-FenceAllowsAccount -Backend $be
    $r.steps.absence_check_at_start = [ordered]@{ allowed = $guard0.Allowed; state = $guard0.State; reason = $guard0.Reason }

    $net = & $W.WaitNetwork $Cfg.NetworkTimeoutSeconds
    $r.steps.network = $net; $obs.NetworkUp = [bool]$net.up
    $ctl = @(); if ($obs.NetworkUp) { foreach ($i in 1..3) { $ctl += (& $W.OperatorConnect) } }
    $r.steps.operator_control = $ctl

    $exports = New-Object System.Collections.ArrayList
    [void]$exports.Add((& $W.Export 'post-reboot-before-removal'))
    # The gate: the account's task is started only if the set is PRESENT.
    $gp = Invoke-GuardedProbe -Backend $be -RunId 'arm3b-block' -ExpectedBlocked $true -Starter { param($rid, $eb) & $W.Probe $rid $eb }
    $r.steps.account_probe_under_fence = [ordered]@{ started = $gp.started; outcome = $gp.outcome; guard_reason = $gp.guard.Reason; run = $gp.run }
    if ($gp.started -and $gp.run) {
        $sid = $Cfg.AccountSid
        $obs.ProbeValid = [bool]($gp.run.valid -and $gp.run.token_sid -eq $sid)
        $obs.ProbeBlocked = [bool]($obs.ProbeValid -and $gp.run.outbound_probe -and -not $gp.run.outbound_probe.probe.connected)
    }

    $addedAt = $null; if ($armed -and $armed.filters_added_at) { try { $addedAt = ConvertTo-DateTimeOffset $armed.filters_added_at } catch {} }
    $rm = Remove-FenceSet -Backend $be
    $removedAt = [datetimeoffset]::Now
    $r.steps.removal = $rm
    if ($addedAt) { $r.steps.objects_existed_seconds = [Math]::Round(($removedAt - $addedAt).TotalSeconds, 1) }
    [void]$exports.Add((& $W.Export 'post-reboot-after-removal'))
    $g1 = Test-FenceAllowsAccount -Backend $be
    $r.steps.absence_check_after_removal = [ordered]@{ allowed = $g1.Allowed; state = $g1.State; reason = $g1.Reason }
    $gp2 = Invoke-GuardedProbe -Backend $be -RunId 'arm3b-guard2' -ExpectedBlocked $false -Starter { param($rid, $eb) throw 'the gate must not start the account when the set is absent' }
    $r.steps.guarded_probe_after_removal = [ordered]@{ started = $gp2.started; outcome = $gp2.outcome }
    $obs.GuardRefusedAfterRemoval = (-not $g1.Allowed -and $g1.State -eq 'ABSENT' -and -not $gp2.started)

    # Removal is verified by the engine reading ABSENT. The operator connect and the account's egress check only add evidence when the network was
    # up at the start: with the network down they cannot be required (a down network must not keep a SYSTEM startup task alive).
    $opAfter = $null; $post = $null; $postValid = $false; $postOpen = $false
    if ($obs.NetworkUp) {
        $opAfter = & $W.OperatorConnect
        $post = & $W.Probe 'arm3b-after' $false
        $postValid = [bool]($post -and $post.valid -and $post.token_sid -eq $Cfg.AccountSid)
        $postOpen = [bool]($postValid -and $post.outbound_probe -and $post.outbound_probe.probe.connected)
    }
    $r.steps.operator_after_removal = $(if ($opAfter) { $opAfter } else { 'not checked: the network was down at the start' })
    $r.steps.account_probe_after_removal_unguarded = $(if ($post) { $post } else { 'not run: the network was down at the start' })
    $obs.RemovalVerified = ($rm.Ok -and ((-not $obs.NetworkUp) -or ($opAfter.ok -and ((-not $postValid) -or $postOpen))))
    $r.exports = @($exports)
    $r.claim_inputs = [ordered]@{
        c10_survived_reboot = [bool]($obs.RebootConfirmed -and $fence0.State -eq 'PRESENT' -and $fence0.AllPersistent)
        c10_note = 'true only when a restart since arming is confirmed (boot time later than the arm time) and all four objects read back with the persistent flag at startup'
        c11_gate_refused_when_absent = [bool]$obs.GuardRefusedAfterRemoval
        c11_gate_at_start = $guard0.State
    }
    $d = Get-PostRebootVerdict ([pscustomobject]$obs)
    $r.decision_inputs = $obs; $r.exit_code = $d.Code; $r.exit_reason = $d.Reason; $r.finished = (& $W.Now)
    return $r
}

function Complete-PostReboot {
    # Writes the result (renaming an earlier file), then deletes the tasks: the wrapper's and veto's always when the removal is
    # verified, this task's LAST and only when the removal is verified.
    param($W, $Cfg, $Result)
    $path = Join-Path $Cfg.OutDir 'post-reboot-result.json'
    & $W.WriteResult $path $Result
    $ok = ($Result.decision_inputs.RemovalVerified -eq $true)
    # A failed removal retries at the next startup, but only a bounded number of times and only until the arm state expires: after that this
    # task deletes itself and the result says a MANUAL rollback is required (the README has it). An endless SYSTEM startup task is not a safety net.
    $gaveUp = ((-not $ok) -and (([int]$Cfg.Attempt -ge [int]$Cfg.MaxAttempts) -or [bool]$Cfg.Expired))
    $tasks = [ordered]@{}
    $tasks.wrapper = & $W.UnregisterTask $Cfg.WrapperTaskName
    if ($ok) { $tasks.veto = & $W.UnregisterTask $Cfg.VetoTaskName; $tasks.self = & $W.UnregisterTask $Cfg.TaskName }
    elseif ($gaveUp) { $tasks.veto = & $W.UnregisterTask $Cfg.VetoTaskName; $tasks.self = (& $W.UnregisterTask $Cfg.TaskName) + ': GAVE UP after attempt ' + $Cfg.Attempt + ' of ' + $Cfg.MaxAttempts + $(if ($Cfg.Expired) { ' (arm state expired)' } else { '' }) + '; the set may still be present: run the manual rollback' }
    else { $tasks.veto = 'kept (removal not verified)'; $tasks.self = "kept (removal not verified): it retries at the next startup (attempt $($Cfg.Attempt) of $($Cfg.MaxAttempts))" }
    $tasks.gave_up = $gaveUp
    return $tasks
}

function New-RealPostRebootWorld {
    param($Backend, $Sid)
    $script:PrSid = $Sid
    $W = @{ Backend = $Backend }
    $W.Now = { (Get-Date).ToString("yyyy-MM-dd'T'HH:mm:ss.fffzzz") }
    $W.BootTime = { (Get-BootTime).ToString('o') }
    $W.Uptime = { [Math]::Round(((Get-Date) - (Get-BootTime).LocalDateTime).TotalSeconds) }
    $W.Env = { Get-ArmEnvSnapshot }
    $W.ReadArmed = { Read-ArmedState -OutDir $OutDir }
    $W.WaitNetwork = { param($t) Wait-NetworkUp -TimeoutSeconds $t }
    $W.OperatorConnect = { Test-TcpConnect '1.1.1.1' 443 5000 }
    $W.Export = { param($label) Invoke-PersistFilterExport -Label $label -Path (Join-Path $OutDir ("arm3b-filters-$label.xml")) }
    $W.Probe = { param($rid, $eb) Invoke-ProbeTaskRun -RunId ("$rid-" + (Get-Date -Format 'HHmmss')) -ExpectedBlocked $eb -TimeoutSec 90 }
    $W.UnregisterTask = { param($n) Unregister-TaskIfPresent -Name $n }
    $W.BumpAttempt = {
        $p = Join-Path $OutDir 'arm3b-post-reboot-attempts.json'; $n = 0
        if (Test-Path -LiteralPath $p) { try { $n = [int](ConvertFrom-Json ([IO.File]::ReadAllText($p))).count } catch { $n = 0 } }
        $n++; New-Item -ItemType Directory -Force $OutDir | Out-Null; Write-JsonGuarded -Path $p -Object ([ordered]@{ count = $n; last = (Get-Date).ToString('o') }) -Depth 3; $n
    }
    $W.WriteResult = {
        param($path, $obj)
        New-Item -ItemType Directory -Force (Split-Path $path -Parent) | Out-Null
        if (Test-Path -LiteralPath $path) { Move-Item -LiteralPath $path -Destination ($path -replace '\.json$', ('.' + (Get-Date -Format 'yyyyMMdd-HHmmss') + '.json')) -Force }
        Write-JsonGuarded -Path $path -Object $obj -Depth 14
    }
    return $W
}

function Invoke-Live {
    $startedAt = Get-Date
    New-Item -ItemType Directory -Force $OutDir | Out-Null
    $W0 = New-RealPostRebootWorld -Backend $null -Sid $null
    $attempt = [int](& $W0.BumpAttempt)
    $armed0 = Read-ArmedState -OutDir $OutDir
    $cfg = [pscustomobject]@{ OutDir = $OutDir; TaskName = $TaskName; VetoTaskName = $VetoTaskName; WrapperTaskName = $WrapperTaskName; NetworkTimeoutSeconds = $NetworkTimeoutSeconds; AccountSid = $null
                              Attempt = $attempt; MaxAttempts = $MaxAttempts; Expired = (Test-ArmExpired -Armed $armed0 -Hours $ExpiryHours) }
    # The wrapped script's text becomes code in this SYSTEM process: it is pinned to the hash taken at arming. If it cannot be used for ANY reason
    # (missing, changed, unparseable) the removal still happens, through the self-contained snippet that depends on nothing else.
    $initErr = $null
    # First the code set (the libraries this process ran and the other scripts on disk) must be the one taken at arming, then the wrapped script must match its pin.
    if ($CodeSetId) { $csChk = Test-CodeSetId -Folder $PSScriptRoot -Expected $CodeSetId; if (-not $csChk.Ok) { $initErr = "code set check failed: $($csChk.Reason)" } }
    if (-not $initErr) { try { $null = Import-WfpHelpers -Path $WfpScript -ExpectedSha256 $WfpSha256; Initialize-PersistType } catch { $initErr = $_.Exception.Message } }
    if ($initErr) {
        $mr = Invoke-ManualRollback
        $res = [ordered]@{ spike = '#1682 arm 3b'; started = $startedAt.ToString("yyyy-MM-dd'T'HH:mm:ss.fffzzz"); error = "the wrapped script could not be used: $initErr"; manual_rollback = $mr
                           attempt = $attempt; expired = $cfg.Expired; decision_inputs = @{ RemovalVerified = [bool]$mr.Ok }
                           exit_code = $(if ($mr.Ok) { 4 } else { 7 }); exit_reason = $(if ($mr.Ok) { 'inconclusive: the wrapped script could not be used, so nothing was read from the engine; the set was deleted through the self-contained rollback (statuses recorded)' } else { 'removal NOT verified: the wrapped script could not be used and the self-contained rollback did not confirm' }) }
        $tasks = Complete-PostReboot -W $W0 -Cfg $cfg -Result $res
        Write-Host $res.exit_reason -ForegroundColor $(if ($mr.Ok) { 'Yellow' } else { 'Red' })
        return [int]$res.exit_code
    }
    $sid = Get-SpikeSidOrNull
    $cfg.AccountSid = $sid
    $open = Open-BackendWithRetry -Opener { New-RealBackend }
    if (-not $open.Backend) {
        $mr = Invoke-ManualRollback
        $res = [ordered]@{ spike = '#1682 arm 3b'; started = $startedAt.ToString("yyyy-MM-dd'T'HH:mm:ss.fffzzz"); error = "the WFP engine could not be opened after $($open.Attempts) attempts: $($open.Error)"; manual_rollback = $mr
                           attempt = $attempt; expired = $cfg.Expired; decision_inputs = @{ RemovalVerified = [bool]$mr.Ok }; exit_code = $(if ($mr.Ok) { 4 } else { 7 })
                           exit_reason = $(if ($mr.Ok) { 'inconclusive: the engine could not be read; the self-contained rollback reported the four keys deleted or already gone' } else { 'removal NOT verified: the engine could not be opened' }) }
        $null = Complete-PostReboot -W $W0 -Cfg $cfg -Result $res
        Write-Host $res.exit_reason -ForegroundColor Red
        return [int]$res.exit_code
    }
    $be = $open.Backend
    $res = $null
    try {
        if (-not $sid) { throw "account $($script:SpikeUser) not found" }
        $W = New-RealPostRebootWorld -Backend $be -Sid $sid
        $res = Invoke-PostRebootCore -W $W -Cfg $cfg
        $res.steps.engine_open_attempts = $open.Attempts
    } catch {
        # Whatever went wrong, the set is removed by key before anything else is said about it.
        $rm = Remove-FenceSet -Backend $be
        $res = [ordered]@{ spike = '#1682 arm 3b'; started = $startedAt.ToString("yyyy-MM-dd'T'HH:mm:ss.fffzzz"); error = $_.Exception.Message + ' @ ' + $_.InvocationInfo.PositionMessage; steps = [ordered]@{ removal_after_error = $rm }
                 attempt = $attempt; expired = $cfg.Expired
                 decision_inputs = @{ RemovalVerified = [bool]$rm.Ok }; exit_code = $(if ($rm.Ok) { 4 } else { 7 }); exit_reason = $(if ($rm.Ok) { 'error before a decision; the set was removed by key and read back ABSENT' } else { 'error before a decision, and the removal was NOT verified' }) }
        $W = New-RealPostRebootWorld -Backend $be -Sid $sid
    } finally { $be.Close() }
    $tasks = Complete-PostReboot -W $W -Cfg $cfg -Result $res
    Write-Host ("RESULT: exit {0}: {1}" -f $res.exit_code, $res.exit_reason)
    Write-Host ("tasks: wrapper {0}; veto {1}; self {2}" -f $tasks.wrapper, $tasks.veto, $tasks.self)
    return [int]$res.exit_code
}

function Invoke-DryRun {
    Write-Host '== DRY RUN: nothing is read from the engine, removed or deleted ==' -ForegroundColor Yellow
    Write-Host 'order of -Live (as SYSTEM, at startup + 1 minute, via the task the arming script registers):'
    @('record boot time, uptime, Windows build, Bitdefender processes, firewall profiles; read the arm state file arm3b-armed.json',
      'open the WFP engine (retried every 15 s for up to 5 minutes while BFE starts)',
      'read the fence state BY KEY: ABSENT / PRESENT / PARTIAL / UNKNOWN, each object''s flags (persistent bit)',
      'absence check at start (the gate): allowed only if PRESENT',
      "wait for the network (an operator-side connect to 1.1.1.1:443; timeout $NetworkTimeoutSeconds s); 3 control connects",
      'export: netsh wfp show filters (before removal), searched for "BlarAI #1682" and both filter keys',
      'the account''s outbound probe THROUGH the gate: started only if PRESENT; if the set is absent the task is NOT started and the result says fence absent',
      'REMOVE every object by key (filters, sublayer, provider); every key tried; read back: must be ABSENT',
      'export again (after removal); the gate must now refuse and start nothing',
      'operator control connect; the account''s probe unguarded (egress must be open again: the attribution control)',
      "write $OutDir\post-reboot-result.json (an earlier one is renamed), then delete tasks: $WrapperTaskName, $VetoTaskName, and LAST $TaskName (these last two only if the removal was verified)") | ForEach-Object { Write-Host "  - $_" }
    $armed = Read-ArmedState -OutDir $OutDir
    Write-Host $(if ($armed) { "arm state present: armed at $($armed.armed_at), shutdown '$($armed.shutdown_command)'" } else { "no arm state at $OutDir\arm3b-armed.json (nothing is armed)" })
    foreach ($n in @($TaskName, $VetoTaskName, $WrapperTaskName)) { Write-Host ("task {0}: {1}" -f $n, $(if (Get-TaskStateOrNull -Name $n) { 'registered' } else { 'not registered' })) }
    Write-Host 'DRY RUN complete.' -ForegroundColor Green
    return 0
}

function Invoke-SelfTest {
    $script:f = 0
    function Chk([string]$n, [bool]$c) { if ($c) { Write-Host "  [PASS] $n" -ForegroundColor Green } else { Write-Host "  [FAIL] $n" -ForegroundColor Red; $script:f++ } }
    Write-Host '== arguments and verdict ==' -ForegroundColor Cyan
    Chk 'args: MaxAttempts 0 / 11 and ExpiryHours 0 / 169 rejected' (((Test-PostRebootArgs $false $false $true 600 0 24).Count -ge 1) -and ((Test-PostRebootArgs $false $false $true 600 11 24).Count -ge 1) -and ((Test-PostRebootArgs $false $false $true 600 3 0).Count -ge 1) -and ((Test-PostRebootArgs $false $false $true 600 3 169).Count -ge 1) -and ((Test-PostRebootArgs $false $false $true 600 3 24).Count -eq 0))
    Chk 'args: exactly one mode; network timeout 29 and 1801 rejected' (((Test-PostRebootArgs $false $false $false 600).Count -ge 1) -and ((Test-PostRebootArgs $true $false $true 600).Count -ge 1) -and ((Test-PostRebootArgs $false $false $true 600).Count -eq 0) -and ((Test-PostRebootArgs $false $false $true 29).Count -ge 1) -and ((Test-PostRebootArgs $false $false $true 1801).Count -ge 1))
    $goodP = @{ AddRecorded = $true; RepeatAttempt = $false; RemovalVerified = $true; RebootConfirmed = $true; FenceAtStart = 'PRESENT'; AllPersistentAtStart = $true; NetworkUp = $true; ProbeValid = $true; ProbeBlocked = $true; GuardRefusedAfterRemoval = $true }
    function VP($over) { $o = $goodP.Clone(); foreach ($k in $over.Keys) { $o[$k] = $over[$k] }; (Get-PostRebootVerdict ([pscustomobject]$o)).Code }
    Chk 'P: all good -> 0' ((VP @{}) -eq 0)
    Chk 'P: removal unverified -> 7 (beats everything)' ((VP @{ RemovalVerified = $false; FenceAtStart = 'ABSENT'; ProbeBlocked = $false }) -eq 7)
    Chk 'P: no confirmed restart -> 4, never a survival claim' (((VP @{ RebootConfirmed = $false }) -eq 4) -and ((VP @{ RebootConfirmed = $false; FenceAtStart = 'ABSENT' }) -eq 4))
    Chk 'P: no add recorded in the arm state (arming never completed) -> 4, never "did not survive"' (((VP @{ AddRecorded = $false; FenceAtStart = 'ABSENT' }) -eq 4) -and ((VP @{ AddRecorded = $false }) -eq 4))
    Chk 'P: a repeat run (attempt 2 or more) -> 4, even when the set reads ABSENT: it was already acted on' (((VP @{ RepeatAttempt = $true; FenceAtStart = 'ABSENT' }) -eq 4) -and ((VP @{ RepeatAttempt = $true }) -eq 4))
    Chk 'P: ABSENT at start -> 8 (did not survive); PARTIAL -> 9; UNKNOWN -> 4' (((VP @{ FenceAtStart = 'ABSENT' }) -eq 8) -and ((VP @{ FenceAtStart = 'PARTIAL' }) -eq 9) -and ((VP @{ FenceAtStart = 'UNKNOWN' }) -eq 4))
    Chk 'P: present but not every object persistent -> 4' ((VP @{ AllPersistentAtStart = $false }) -eq 4)
    Chk 'P: network never up -> 4; probe invalid -> 4' (((VP @{ NetworkUp = $false }) -eq 4) -and ((VP @{ ProbeValid = $false; ProbeBlocked = $false }) -eq 4))
    Chk 'P: present but the account not blocked -> 1' ((VP @{ ProbeBlocked = $false }) -eq 1)
    Chk 'P: the gate did not refuse after removal -> 6, never 0' ((VP @{ GuardRefusedAfterRemoval = $false }) -eq 6)
    Write-Host '== network wait and engine-open retry (fake clocks) ==' -ForegroundColor Cyan
    $clk = @{ t = [datetime]'2026-10-11T12:00:00' }; $n = @{ c = 0 }
    $up = Wait-NetworkUp -TimeoutSeconds 600 -PollSeconds 5 -Connect { $n.c++; [pscustomobject]@{ ok = ($n.c -ge 4); error = 'no route' } } -Sleep { param($s) $clk.t = $clk.t.AddSeconds($s) } -Clock { $clk.t }
    Chk 'network: comes up on the 4th try after 15 s' (($up.up -eq $true) -and ($up.attempts -eq 4) -and ($up.seconds -eq 15))
    $clk2 = @{ t = [datetime]'2026-10-11T12:00:00' }
    $down = Wait-NetworkUp -TimeoutSeconds 60 -PollSeconds 5 -Connect { [pscustomobject]@{ ok = $false; error = 'no route' } } -Sleep { param($s) $clk2.t = $clk2.t.AddSeconds($s) } -Clock { $clk2.t }
    Chk 'network: never up -> up=false after the timeout, with the last error' (($down.up -eq $false) -and ($down.seconds -ge 60) -and ($down.last_error -eq 'no route'))
    $oc = @{ c = 0 }
    $o1 = Open-BackendWithRetry -Opener { $oc.c++; if ($oc.c -lt 3) { throw 'BFE not ready' } else { 'backend' } } -Sleep { param($s) } -Attempts 5
    Chk 'engine open: succeeds on the 3rd attempt' (($o1.Backend -eq 'backend') -and ($o1.Attempts -eq 3))
    $o2 = Open-BackendWithRetry -Opener { throw 'BFE not ready' } -Sleep { param($s) } -Attempts 4
    Chk 'engine open: gives up after the attempts with the last error' (($null -eq $o2.Backend) -and ($o2.Attempts -eq 4) -and ($o2.Error -eq 'BFE not ready'))
    Write-Host '== the post-reboot flow against fakes ==' -ForegroundColor Cyan
    $null = Import-WfpHelpers -Path $WfpScript -Unverified; Initialize-PersistType
    $sid = 'S-1-5-21-1111111111-2222222222-3333333333-1001'
    $plan = [BlarAI.WfpPersist.PersistPlan]::Build($sid)
    $cfg = [pscustomobject]@{ OutDir = 'C:\o'; TaskName = 'blarai-arm3b-post-reboot'; VetoTaskName = 'blarai-arm3b-veto'; WrapperTaskName = 'blarai-arm3b-arm-run'; NetworkTimeoutSeconds = 600; AccountSid = $sid; Attempt = 1; MaxAttempts = 3; Expired = $false }
    $armedAt = [datetimeoffset]::Now.AddMinutes(-20)
    function New-PW($be, $over) {
        $probeCalls = New-Object System.Collections.ArrayList; $tasks = New-Object System.Collections.ArrayList; $written = New-Object System.Collections.ArrayList
        $armedAtL = $armedAt; $sidL = $sid   # GetNewClosure captures this function's own variables, not the caller's
        $w = @{ Backend = $be; ProbeCalls = $probeCalls; Unreg = $tasks; Written = $written }
        $w.Now = { (Get-Date).ToString("yyyy-MM-dd'T'HH:mm:ss.fffzzz") }
        $w.BootTime = { [datetimeoffset]::Now.AddMinutes(-10).ToString('o') }
        $w.Uptime = { 600 }
        $w.Env = { [ordered]@{ fake = $true } }
        $w.ReadArmed = { [pscustomobject]@{ armed_at = $armedAtL.ToString('o'); filters_added_at = $armedAtL.AddSeconds(-3).ToString('o'); shutdown_command = 'shutdown.exe /r /t 600 /c arm 3b' } }.GetNewClosure()
        $w.WaitNetwork = { param($t) [ordered]@{ up = $true; attempts = 1; seconds = 0 } }
        $w.OperatorConnect = { [pscustomobject]@{ ok = $true; error = '' } }
        $w.Export = { param($l) [ordered]@{ label = $l; ok = $true } }
        $w.Probe = { param($rid, $eb) [void]$probeCalls.Add("$rid expected_blocked=$eb"); [pscustomobject]@{ valid = $true; token_sid = $sidL; outbound_probe = [pscustomobject]@{ probe = [pscustomobject]@{ connected = (-not $eb); error_code = $(if ($eb) { 10013 } else { 0 }) } } } }.GetNewClosure()
        $w.UnregisterTask = { param($n) [void]$tasks.Add($n); 'unregistered' }.GetNewClosure()
        $w.WriteResult = { param($p, $o) [void]$written.Add($p) }.GetNewClosure()
        foreach ($k in @($over.Keys)) { $w[$k] = $over[$k] }
        $w
    }
    $beS = New-FakeBackend; [void]$beS.AddAll($plan)
    $wS = New-PW $beS @{}
    $rS = Invoke-PostRebootCore -W $wS -Cfg $cfg
    $tS = Complete-PostReboot -W $wS -Cfg $cfg -Result $rS
    Chk 'survived: exit 0; the set read PRESENT and persistent at start; the account probed once under the fence (blocked) and once after removal (open)' (($rS.exit_code -eq 0) -and ($rS.steps.fence_state_at_start.State -eq 'PRESENT') -and $rS.steps.fence_state_at_start.AllPersistent -and ($wS.ProbeCalls.Count -eq 2) -and ($wS.ProbeCalls[0] -match 'expected_blocked=True') -and ($wS.ProbeCalls[1] -match 'expected_blocked=False'))
    Chk 'survived: removed by key and read back ABSENT; the gate refused afterwards without starting the task; claim inputs c10 and c11 true' (($beS.Store.Count -eq 0) -and ($rS.steps.absence_check_after_removal.state -eq 'ABSENT') -and (-not $rS.steps.guarded_probe_after_removal.started) -and $rS.claim_inputs.c10_survived_reboot -and $rS.claim_inputs.c11_gate_refused_when_absent)
    Chk 'survived: the result is written to post-reboot-result.json, then the wrapper, veto and this task are deleted, this task LAST' (($wS.Written.Count -eq 1) -and ($wS.Written[0] -eq 'C:\o\post-reboot-result.json') -and (($wS.Unreg -join ',') -eq 'blarai-arm3b-arm-run,blarai-arm3b-veto,blarai-arm3b-post-reboot'))
    $beA = New-FakeBackend
    $wA = New-PW $beA @{}
    $rA = Invoke-PostRebootCore -W $wA -Cfg $cfg
    Chk 'gone: exit 8 (did not survive); the account''s task was NOT started under the fence (only the unguarded post-removal control ran); c10 false' (($rA.exit_code -eq 8) -and ($wA.ProbeCalls.Count -eq 1) -and ($wA.ProbeCalls[0] -match 'expected_blocked=False') -and (-not $rA.claim_inputs.c10_survived_reboot) -and ($rA.steps.account_probe_under_fence.outcome -eq 'fence_absent_not_started') -and ($rA.steps.absence_check_at_start.allowed -eq $false))
    $beP = New-FakeBackend -FailAddAfter 3; try { [void]$beP.AddAll($plan) } catch {}
    $wP = New-PW $beP @{}
    $rP = Invoke-PostRebootCore -W $wP -Cfg $cfg
    Chk 'partial: exit 9; the account''s task not started under the fence; the remnants are removed by key' (($rP.exit_code -eq 9) -and ($beP.Store.Count -eq 0) -and ($rP.steps.account_probe_under_fence.started -eq $false))
    $beU = New-FakeBackend -Unreadable $true
    $wU = New-PW $beU @{}
    $rU = Invoke-PostRebootCore -W $wU -Cfg $cfg
    Chk 'unreadable engine: fence UNKNOWN, the account''s task NOT started, removal NOT verified -> exit 7' (($rU.steps.fence_state_at_start.State -eq 'UNKNOWN') -and ($rU.exit_code -eq 7) -and ($rU.steps.account_probe_under_fence.started -eq $false))
    $tU = Complete-PostReboot -W $wU -Cfg $cfg -Result $rU
    Chk 'removal not verified: this task and the veto task are KEPT (retry at the next startup); only the wrapper is deleted' (($wU.Unreg -join ',') -eq 'blarai-arm3b-arm-run' -and $tU.self -match 'kept')
    $beF = New-FakeBackend; [void]$beF.AddAll($plan); $beF.FailDelete = @($script:PersistProviderKey)
    $wF = New-PW $beF @{}
    $rF = Invoke-PostRebootCore -W $wF -Cfg $cfg
    Chk 'a removal that fails: exit 7, the failing key named in the record' (($rF.exit_code -eq 7) -and ($rF.steps.removal.Errors.Count -eq 1) -and ($rF.steps.removal.Errors[0].kind -eq 'provider'))
    $beN = New-FakeBackend; [void]$beN.AddAll($plan)
    $wN = New-PW $beN @{ WaitNetwork = { param($t) [ordered]@{ up = $false; attempts = 120; seconds = 600 } } }
    $rN = Invoke-PostRebootCore -W $wN -Cfg $cfg
    Chk 'no network: exit 4 (inconclusive) but the set is STILL removed and verified' (($rN.exit_code -eq 4) -and ($beN.Store.Count -eq 0) -and $rN.decision_inputs.RemovalVerified)
    $beR = New-FakeBackend; [void]$beR.AddAll($plan)
    $wR = New-PW $beR @{ BootTime = { [datetimeoffset]::Now.AddMinutes(-60).ToString('o') } }
    $rR = Invoke-PostRebootCore -W $wR -Cfg $cfg
    Chk 'no confirmed restart (boot time earlier than the arm time): exit 4, c10 false, the set still removed' (($rR.exit_code -eq 4) -and (-not $rR.claim_inputs.c10_survived_reboot) -and ($beR.Store.Count -eq 0))
    $beO = New-FakeBackend; [void]$beO.AddAll($plan)
    $wO = New-PW $beO @{ ReadArmed = { $null } }
    $rO = Invoke-PostRebootCore -W $wO -Cfg $cfg
    Chk 'arm state unreadable: no restart can be confirmed -> exit 4, the set still removed' (($rO.exit_code -eq 4) -and ($beO.Store.Count -eq 0))
    $beE = New-FakeBackend; [void]$beE.AddAll($plan)
    $wE = New-PW $beE @{ OperatorConnect = { [pscustomobject]@{ ok = $false; error = 'x' } } }
    $rE = Invoke-PostRebootCore -W $wE -Cfg $cfg
    Chk 'operator connect failing after removal WITH the network up -> removal not verified, exit 7' ($rE.exit_code -eq 7)
    $beK = New-FakeBackend; [void]$beK.AddAll($plan)
    $wK = New-PW $beK @{ Probe = { param($rid, $eb) [pscustomobject]@{ valid = $true; token_sid = $sid; outbound_probe = [pscustomobject]@{ probe = [pscustomobject]@{ connected = $true; error_code = 0 } } } } }
    $rK = Invoke-PostRebootCore -W $wK -Cfg $cfg
    Chk 'present but the account CONNECTED under the fence -> exit 1; and egress "open" after removal is consistent, so removal still verifies' (($rK.exit_code -eq 1) -and $rK.decision_inputs.RemovalVerified)
    $beS2 = New-FakeBackend; [void]$beS2.AddAll($plan)
    $wS2 = New-PW $beS2 @{ Probe = { param($rid, $eb) [pscustomobject]@{ valid = $true; token_sid = $sid; outbound_probe = [pscustomobject]@{ probe = [pscustomobject]@{ connected = $false; error_code = 10013 } } } } }
    $rS2 = Invoke-PostRebootCore -W $wS2 -Cfg $cfg
    Chk 'egress still blocked AFTER the removal -> removal not verified (exit 7): the block is not attributable to a filter that is gone' ($rS2.exit_code -eq 7)
    Write-Host '== bounded retries, expiry, and a down network told apart from a set that did not survive ==' -ForegroundColor Cyan
    $beD = New-FakeBackend; [void]$beD.AddAll($plan)
    $wD = New-PW $beD @{ WaitNetwork = { param($t) [ordered]@{ up = $false; attempts = 120; seconds = 600 } } }
    $rD = Invoke-PostRebootCore -W $wD -Cfg $cfg
    Chk 'network down, set present: verified by the engine alone (no operator connect or account probe required), reason names the network, NOT "did not survive"' (($rD.decision_inputs.RemovalVerified -eq $true) -and ($beD.Store.Count -eq 0) -and ($rD.exit_code -eq 4) -and ($rD.exit_reason -match 'network') -and ($rD.steps.operator_after_removal -match 'not checked') -and ($wD.ProbeCalls.Count -eq 1))
    $beE2 = New-FakeBackend; $wE2 = New-PW $beE2 @{ WaitNetwork = { param($t) [ordered]@{ up = $false; attempts = 120; seconds = 600 } } }
    $rE2 = Invoke-PostRebootCore -W $wE2 -Cfg $cfg
    Chk 'network down, set absent at the FIRST run after a confirmed restart: still reported as not surviving (the engine reading does not depend on the network), and the reason says so' (($rE2.exit_code -eq 8) -and ($rE2.exit_reason -match 'network state does not bear'))
    $cfg2 = $cfg.PSObject.Copy(); $cfg2.Attempt = 2
    $beR2 = New-FakeBackend; $rR2 = Invoke-PostRebootCore -W (New-PW $beR2 @{}) -Cfg $cfg2
    Chk 'a repeat attempt that finds the set ABSENT is exit 4 (an earlier attempt acted on it), never a false "did not survive"' (($rR2.exit_code -eq 4) -and ($rR2.exit_reason -match 'repeat run'))
    $beN2 = New-FakeBackend; [void]$beN2.AddAll($plan)
    $rN2 = Invoke-PostRebootCore -W (New-PW $beN2 @{ ReadArmed = { [pscustomobject]@{ armed_at = $armedAt.ToString('o'); filters_added_at = $null } }.GetNewClosure() }) -Cfg $cfg
    Chk 'an arm state with no recorded add (arming interrupted before the add): exit 4, "arming did not complete", the set (if any) still removed' (($rN2.exit_code -eq 4) -and ($rN2.exit_reason -match 'arming did not complete') -and ($beN2.Store.Count -eq 0))
    $cfgA = $cfg.PSObject.Copy(); $cfgA.Attempt = 3
    $beU2 = New-FakeBackend -Unreadable $true; $wU2 = New-PW $beU2 @{}
    $rU2 = Invoke-PostRebootCore -W $wU2 -Cfg $cfgA
    $tU2 = Complete-PostReboot -W $wU2 -Cfg $cfgA -Result $rU2
    Chk 'removal still unverified at attempt 3 of 3: the veto and this task are DELETED (bounded), the record says GAVE UP and demands the manual rollback' (($tU2.gave_up -eq $true) -and ($tU2.self -match 'GAVE UP') -and ($tU2.self -match 'manual rollback') -and ($wU2.Unreg -contains 'blarai-arm3b-post-reboot') -and ($wU2.Unreg -contains 'blarai-arm3b-veto'))
    $cfgX = $cfg.PSObject.Copy(); $cfgX.Expired = $true
    $beX = New-FakeBackend -Unreadable $true; $wX = New-PW $beX @{}
    $rX = Invoke-PostRebootCore -W $wX -Cfg $cfgX
    $tX = Complete-PostReboot -W $wX -Cfg $cfgX -Result $rX
    Chk 'an expired arm state (older than the limit) with an unverified removal at attempt 1: also gives up and deletes the task; the result records expired=true' (($tX.gave_up -eq $true) -and ($tX.self -match 'expired') -and ($rX.expired -eq $true))
    Chk 'unverified at attempt 1 of 3 and not expired: the task is kept for the next startup (existing behaviour, now bounded)' ((-not (Complete-PostReboot -W (New-PW (New-FakeBackend -Unreadable $true) @{}) -Cfg $cfg -Result $rU).gave_up))
    $nowT = [datetimeoffset]::Parse('2026-10-11T12:00:00+00:00')
    Chk 'expiry rule (pure): 25 h old is expired at 24 h, 23 h is not, no arm state is not' ((Test-ArmExpired -Armed ([pscustomobject]@{ armed_at = '2026-10-10T11:00:00+00:00' }) -Hours 24 -Now $nowT) -and -not (Test-ArmExpired -Armed ([pscustomobject]@{ armed_at = '2026-10-10T13:00:00+00:00' }) -Hours 24 -Now $nowT) -and -not (Test-ArmExpired -Armed $null -Hours 24 -Now $nowT))
    Write-Host ("arm3b-post-reboot selftest: {0}" -f $(if ($script:f -eq 0) { 'all passed' } else { "$($script:f) FAILED" })) -ForegroundColor $(if ($script:f -eq 0) { 'Green' } else { 'Red' })
    return $(if ($script:f -eq 0) { 0 } else { 1 })
}

$argErrors = Test-PostRebootArgs $SelfTest.IsPresent $DryRun.IsPresent $Live.IsPresent $NetworkTimeoutSeconds $MaxAttempts $ExpiryHours
if ($argErrors.Count) { $argErrors | ForEach-Object { Write-Host "ARG ERROR: $_" -ForegroundColor Red }; exit 2 }
try {
    if ($SelfTest) { exit (Invoke-SelfTest) }
    if ($DryRun)   { exit (Invoke-DryRun) }
    if ($Live)     { exit (Invoke-Live) }
} catch {
    Write-Host "STOPPED: $($_.Exception.Message)" -ForegroundColor Red
    Write-Host $_.ScriptStackTrace -ForegroundColor DarkGray
    exit 2
}
