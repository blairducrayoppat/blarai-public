#requires -Version 5.1
<#
.SYNOPSIS
  Arm 3a: a PERSISTENT raw WFP block keyed to the throwaway spike account's SID, added and removed under a rollback that is
  proved BEFORE the add path can be reached. Machine-wide state: read arm3-persist/DESIGN.md first.

.DESCRIPTION
  Modes (exactly one):
    -SelfTest  [-WriteProof]  pure only: extraction, C# compile (in-process, no engine), struct and condition invariants, the
               rollback and the fail-closed gate against an in-memory fake (a half-failed add, a failing delete, an unreadable
               engine, a stale object, a forged proof), the proof's hash binding, verdicts, argument rules. No WFP call, no system
               change. With -WriteProof (and only then) it also runs the self-test of every sibling script, and if EVERYTHING
               passes it writes the rollback proof the add paths require: the SHA-256 (LF-normalised) of each script of the code
               set plus the rollback checks that passed. Any later edit to any of those scripts invalidates it.
    -DryRun    prints exactly what would be added (keys, flags, the SD, the condition on every filter), what the run would do in
               order, the dead-man task, the manual rollback, and whether a valid proof exists now. Adds nothing; opens no engine.
    -Check     read-only: reports ABSENT / PRESENT / PARTIAL / UNKNOWN for the four objects and exits 0 only for PRESENT.
               Exit 20 ABSENT, 21 PARTIAL, 22 UNKNOWN (including an engine that cannot be opened): the account is allowed to
               run only on 0.
    -Remove    removes all four objects BY KEY (filters, then sublayer, then provider), whatever state they are in, including
               half-added; "already gone" is success; every key is tried even if one fails; the result is verified by reading
               the state back. With -RemoveTaskName it then unregisters that scheduled task (the dead-man's own name).
    -Arm3a     one attended-or-unattended run, no reboot: preflight (proof, SID safety) -> baseline -> optional dead-man task (-DeadManTask, default OFF) -> add (persistent)
               -> the account's probe through the fail-closed gate (must be blocked) -> operator watchdog during a short dwell -> exports
               -> remove by key -> verify ABSENT -> the gate must now REFUSE to start the account -> the account's probe, unguarded
               (egress must be open again) -> report. A `finally` removes by key again whatever happened.

  -DeadManTask is opt-in because registering a SYSTEM task is a separate grant and an escalation surface (see the FOLDER RULE); without it the rollback in force is the
  run's own removal, its finally block and the wrapper's follow-up -Remove. -WfpSha256 pins the wrapped script (the SYSTEM dead-man passes it): a different file is
  refused before its text becomes code, and -Remove then falls back to the self-contained snippet.

  FOLDER RULE. Everything a SYSTEM or elevated task runs comes from the folder these scripts sit in. If a non-administrator process can write to that folder
  (or replace it), it can run code elevated. These scripts therefore refuse to register a SYSTEM task, and the elevated wrapper refuses to register or run,
  unless only SYSTEM, Administrators and TrustedInstaller can write to the folder and to every file in it (Test-AdminOnlyFolder). Keep them under an
  administrator-only folder such as C:\ProgramData\BlarAI; the rollback proof is written beside them for the same reason.

  EXIT CODES
    0 ok (-Arm3a: fence enforced, gate behaved, removal verified; -Remove: verified ABSENT; -SelfTest: all passed)
    1 -Arm3a: the account was NOT blocked with the fence present (a result)
    2 precondition / refusal (no proof, stale objects, not elevated, preflight): nothing was added
    3 unsafe target (the SID is the operator's or one of his groups) or operator traffic affected (aborted, removed)
    4 inconclusive   5 no baseline   6 the absence check did not refuse when it must   7 removal NOT verified (run -Remove; then the README's manual rollback)
    20/21/22 -Check: ABSENT / PARTIAL / UNKNOWN
#>
[CmdletBinding()]
param(
    [switch]$SelfTest,
    [switch]$WriteProof,
    [switch]$DryRun,
    [switch]$Check,
    [switch]$Remove,
    [switch]$Arm3a,
    [string]$RemoveTaskName,
    [int]$DwellSeconds = 20,
    [int]$DeadManMinutes = 15,
    [switch]$DeadManTask,
    [string]$WfpSha256,
    [string]$CodeSetId,
    [string]$WfpScript,
    [string]$StateDir = 'C:\Users\_OPERATOR_\blarai-research-data\arm3-persist',
    [string]$ProofPath
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
# The proof lives beside the scripts it vouches for, in the admin-only folder: a proof anyone can write is not a proof.
if (-not $ProofPath) { $ProofPath = Join-Path $PSScriptRoot 'rollback-selftest-proof.json' }
$script:DeadManName = 'blarai-arm3a-deadman'

# ---- pure helpers -------------------------------------------------------------------------------------------------
function Test-PersistArgs {
    param([bool]$SelfTest, [bool]$WriteProof, [bool]$DryRun, [bool]$Check, [bool]$Remove, [bool]$Arm3a, [string]$TaskName, [int]$Dwell, [int]$DeadMan)
    $e = New-Object System.Collections.ArrayList
    $modes = @($SelfTest, $DryRun, $Check, $Remove, $Arm3a) | Where-Object { $_ }
    if (@($modes).Count -ne 1) { [void]$e.Add('choose exactly one of -SelfTest, -DryRun, -Check, -Remove, -Arm3a') }
    if ($WriteProof -and -not $SelfTest) { [void]$e.Add('-WriteProof applies to -SelfTest only') }
    if ($TaskName -and -not $Remove) { [void]$e.Add('-RemoveTaskName applies to -Remove only') }
    if ($TaskName -and $TaskName -notmatch '^blarai-[A-Za-z0-9-]{3,60}$') { [void]$e.Add("-RemoveTaskName must look like blarai-<plain-name> (got '$TaskName')") }
    if ($Dwell -lt 5 -or $Dwell -gt 120) { [void]$e.Add("DwellSeconds must be 5..120 (got $Dwell)") }
    if ($DeadMan -lt 5 -or $DeadMan -gt 120) { [void]$e.Add("DeadManMinutes must be 5..120 (got $DeadMan)") }
    return @($e)
}

function Get-CheckExitCode {
    # PURE. -Check's exit code: only PRESENT is 0.
    param([string]$State)
    switch ($State) { 'PRESENT' { 0 } 'ABSENT' { 20 } 'PARTIAL' { 21 } default { 22 } }
}

function Get-DeadManDefinition {
    # PURE. The SYSTEM one-shot task that removes the persistent set by key if this run never gets to: persistent objects have no
    # dynamic-session backstop, so this is the stand-in for the dead-man timer of arms 1 and 2.
    param([string]$Name, [string]$ScriptPath, [string]$State, [string]$Wfp, [int]$Minutes, [datetime]$Now, [string]$WfpHash = '', [string]$CodeSetId = '')
    $pin = $(if ($WfpHash) { " -WfpSha256 $WfpHash" } else { '' }) + $(if ($CodeSetId) { " -CodeSetId $CodeSetId" } else { '' })
    return [pscustomobject]@{
        TaskName = $Name; TaskPath = '\BlarAI\'; User = 'NT AUTHORITY\SYSTEM'; LogonType = 'ServiceAccount'; RunLevel = 'Highest'
        Execute = 'powershell.exe'
        Arguments = ('-NoProfile -ExecutionPolicy Bypass -File "{0}" -Remove -StateDir "{1}" -WfpScript "{2}" -RemoveTaskName {3}{4}' -f $ScriptPath, $State, $Wfp, $Name, $pin)
        TriggerAt = $Now.AddMinutes($Minutes); ExecutionTimeLimitMinutes = 10
        Purpose = 'removes the persistent WFP objects by key if the run did not; unregisters itself after a verified removal'
    }
}

function Get-Arm3aVerdict {
    # PURE. Safety first: operator impact, unverified removal, no baseline; then the add, the block, and the absence check.
    param([Parameter(Mandatory)]$Obs)
    if ($Obs.OperatorAbort)        { return [pscustomobject]@{ Code = 3; Reason = 'operator traffic affected (watchdog abort): everything removed by key' } }
    if (-not $Obs.RemovalVerified) { return [pscustomobject]@{ Code = 7; Reason = 'removal NOT verified (objects left, operator connect failed, or the account''s egress did not reopen): run -Remove, then the README''s manual rollback' } }
    if (-not $Obs.BaselineOk)      { return [pscustomobject]@{ Code = 5; Reason = 'no baseline (operator offline / the account''s baseline run invalid or its egress already blocked)' } }
    if (-not $Obs.AddOk)           { return [pscustomobject]@{ Code = 4; Reason = 'inconclusive: the add failed or was refused (rolled back by key)' } }
    if (-not $Obs.PresentAfterAdd -or -not $Obs.AllPersistent) { return [pscustomobject]@{ Code = 4; Reason = 'inconclusive: the set read back after the add was not PRESENT with the persistent flag on every object' } }
    if (-not $Obs.BlockRunValid)   { return [pscustomobject]@{ Code = 4; Reason = 'inconclusive: the account run under the fence did not start, gave no schema-valid result, ran as the wrong SID, or the gate refused it' } }
    if (-not $Obs.ProbeBlocked)    { return [pscustomobject]@{ Code = 1; Reason = 'account NOT blocked: its outbound connect succeeded with the persistent fence present' } }
    if (-not $Obs.GuardRefusedBeforeAdd -or -not $Obs.GuardRefusedAfterRemoval) { return [pscustomobject]@{ Code = 6; Reason = 'the absence check did NOT refuse when the fence was absent (before the add or after the removal): the fail-closed gate is broken' } }
    return [pscustomobject]@{ Code = 0; Reason = 'persistent fence enforced (account blocked), the absence check refused when the fence was absent, removal by key verified' }
}

function Register-DeadManTask {
    param([Parameter(Mandatory)]$Def)
    $a = New-ScheduledTaskAction -Execute $Def.Execute -Argument $Def.Arguments
    $t = New-ScheduledTaskTrigger -Once -At $Def.TriggerAt
    $p = New-ScheduledTaskPrincipal -UserId $Def.User -LogonType ServiceAccount -RunLevel Highest
    $s = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Minutes $Def.ExecutionTimeLimitMinutes)
    Register-ScheduledTask -TaskName $Def.TaskName -TaskPath $Def.TaskPath -Action $a -Trigger $t -Principal $p -Settings $s -Description 'BlarAI arm 3a dead-man: removes the persistent WFP objects by key. Unregisters itself.' -Force | Out-Null
}

function Initialize-PersistSession {
    # Reads the wrapped script (never runs it), compiles the persist types, requires elevation and a 64-bit process.
    if ($CodeSetId) { $cs = Test-CodeSetId -Folder $PSScriptRoot -Expected $CodeSetId; if (-not $cs.Ok) { throw "code set check failed: $($cs.Reason)" } }
    $null = Import-WfpHelpers -Path $WfpScript -ExpectedSha256 $WfpSha256
    Initialize-PersistType
}

function Write-StateFile {
    param([string]$Name, $Object)
    New-Item -ItemType Directory -Force $StateDir | Out-Null
    $p = Join-Path $StateDir $Name
    Write-JsonGuarded -Path $p -Object $Object -Depth 14
    return $p
}

# ---- -Check / -Remove -----------------------------------------------------------------------------------------------------
function Invoke-Check {
    Initialize-PersistSession
    if (-not (Test-IsElevated)) { Write-Host 'UNKNOWN: not elevated, so the engine cannot be read. The account is NOT allowed to run.' -ForegroundColor Red; return 22 }
    $be = $null
    try { $be = New-RealBackend } catch { Write-Host "UNKNOWN: the engine could not be opened ($($_.Exception.Message)). The account is NOT allowed to run." -ForegroundColor Red; return 22 }
    try { $g = Test-FenceAllowsAccount -Backend $be } finally { $be.Close() }
    Write-Host ("fence {0}: {1}" -f $g.State, $g.Reason) -ForegroundColor $(if ($g.Allowed) { 'Green' } else { 'Yellow' })
    Write-Host ("  present: {0}" -f ($g.Detail.Present -join ', ')); Write-Host ("  missing: {0}" -f ($g.Detail.Missing -join ', '))
    Write-Host ("  flags  : {0}; all persistent: {1}" -f (($g.Detail.Flags.GetEnumerator() | ForEach-Object { "$($_.Key)=$($_.Value)" }) -join ' '), $g.Detail.AllPersistent)
    return (Get-CheckExitCode $g.State)
}

function Invoke-Remove {
    $initErr = $null
    try { Initialize-PersistSession } catch { $initErr = $_.Exception.Message }
    if ($initErr) {
        # The wrapped script is missing, unparseable or not the pinned one: the removal must not depend on it. The self-contained snippet
        # deletes the same four keys; it cannot read the state back, so the statuses it prints are the evidence.
        Write-Host "The wrapped script could not be used ($initErr). Falling back to the self-contained manual rollback." -ForegroundColor Yellow
        if (-not [Security.Principal.WindowsPrincipal]::new([Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) { Write-Host 'FAIL: not elevated; nothing removed.' -ForegroundColor Red; return 7 }
        $mr = Invoke-ManualRollback
        foreach ($r in $mr.Rows) { Write-Host ("  {0,-9} {1}  {2}" -f $r.kind, $r.key, $r.status) }
        $rec0 = [ordered]@{ kind = 'remove-by-key-manual-fallback'; at = (Get-Date).ToString("yyyy-MM-dd'T'HH:mm:ss.fffzzz"); reason_for_fallback = $initErr; result = $mr; unregistered_task = $null }
        if ($mr.Ok -and $RemoveTaskName) { $rec0.unregistered_task = Unregister-TaskIfPresent -Name $RemoveTaskName }
        try { $null = Write-StateFile -Name ("remove-{0}.json" -f (Get-Date -Format 'yyyyMMdd-HHmmss')) -Object $rec0 } catch {}
        Write-Host $(if ($mr.Ok) { 'REMOVED by the manual fallback (statuses above); run -Check once the wrapped script is usable to read it back.' } else { "NOT VERIFIED: $($mr.Reason)" }) -ForegroundColor $(if ($mr.Ok) { 'Yellow' } else { 'Red' })
        return $(if ($mr.Ok) { 0 } else { 7 })
    }
    if (-not (Test-IsElevated)) { Write-Host 'FAIL: not elevated; nothing removed. Use the README''s manual rollback from an elevated prompt.' -ForegroundColor Red; return 7 }
    $be = $null
    try { $be = New-RealBackend } catch { Write-Host "FAIL: the engine could not be opened ($($_.Exception.Message)); nothing removed." -ForegroundColor Red; return 7 }
    try {
        $before = Get-FenceState -Backend $be
        $rm = Remove-FenceSet -Backend $be
    } finally { $be.Close() }
    $rec = [ordered]@{ kind = 'remove-by-key'; at = (Get-Date).ToString("yyyy-MM-dd'T'HH:mm:ss.fffzzz"); state_before = $before; removal = $rm; unregistered_task = $null }
    foreach ($r in $rm.Rows) { Write-Host ("  {0,-9} {1}  {2}" -f $r.kind, $r.key, $r.status) }
    if ($rm.Ok) {
        Write-Host 'REMOVED: all four objects absent (read back).' -ForegroundColor Green
        if ($RemoveTaskName) { $rec.unregistered_task = Unregister-TaskIfPresent -Name $RemoveTaskName; Write-Host "task $RemoveTaskName`: $($rec.unregistered_task)" }
    } else { Write-Host ("NOT VERIFIED: state after is {0}. Errors: {1}" -f $rm.StateAfter.State, (($rm.Errors | ForEach-Object { "$($_.kind) $($_.status)" }) -join '; ')) -ForegroundColor Red }
    try { $rec.state_file = Write-StateFile -Name ("remove-{0}.json" -f (Get-Date -Format 'yyyyMMdd-HHmmss')) -Object $rec } catch { Write-Host "could not write the record: $($_.Exception.Message)" -ForegroundColor Yellow }
    return $(if ($rm.Ok) { 0 } else { 7 })
}

# ---- -Arm3a ---------------------------------------------------------------------------------------------------------------
function Invoke-Arm3a {
    Initialize-PersistSession   # reads the wrapped script (the SID-safety and elevation helpers come from it) and compiles the types; opens no engine
    $sid = Get-SpikeSidOrNull
    if ($sid) { $unsafe = @(Get-SafeSidProblems -Sid $sid); if ($unsafe.Count) { Write-Host ('REFUSED (exit 3): ' + ($unsafe -join '; ')) -ForegroundColor Red; return 3 } }
    $problems = @(Assert-SpikePreflight -ScriptFolder $PSScriptRoot)
    if ($problems.Count) { $problems | ForEach-Object { Write-Host "FAIL: $_" -ForegroundColor Red }; return 2 }
    $proof = Test-RollbackProof -ProofPath $ProofPath -Folder $PSScriptRoot -WrappedSha256 $script:WrappedSha256Used
    if (-not $proof.Ok) { $proof.Problems | ForEach-Object { Write-Host "REFUSED: $_" -ForegroundColor Red }; return 2 }
    $pl = @(Test-ProofLocation -ProofPath $ProofPath -ScriptFolder $PSScriptRoot)
    if ($pl.Count) { $pl | ForEach-Object { Write-Host "REFUSED: $_" -ForegroundColor Red }; return 2 }
    if ($DeadManTask) {
        # A SYSTEM task would run this script AND write its records: refuse unless only administrators can change the script folder and the state folder.
        New-Item -ItemType Directory -Force $StateDir | Out-Null
        $ao = Test-AdminOnlyFolder -Path $PSScriptRoot
        $ao2 = Test-AdminOnlyFolder -Path $StateDir
        if (-not $ao2.Ok) { $ao = [ordered]@{ Ok = $false; Problems = @($ao.Problems) + @($ao2.Problems | ForEach-Object { "state folder: $_" }) } }
        if (-not $ao.Ok) { $ao.Problems | ForEach-Object { Write-Host "REFUSED (a SYSTEM dead-man task from a writable folder): $_" -ForegroundColor Red }; return 2 }
    }
    $plan = [BlarAI.WfpPersist.PersistPlan]::Build($sid)
    $runId = 'arm3a-' + (Get-Date -Format 'yyyyMMdd-HHmmss')
    $report = [ordered]@{ spike = '#1682 arm 3a: a persistent SID-keyed block, absence detection, removal by key (no reboot)'; run_id = $runId; started = (Get-Date).ToString("yyyy-MM-dd'T'HH:mm:ss.fffzzz"); dwell_seconds = $DwellSeconds
                          proof = [ordered]@{ path = $ProofPath; written = [string]$proof.Written }; env = $null; wsl_shutdown = $null; steps = [ordered]@{}; exports = @() }
    $obs = @{ OperatorAbort = $false; RemovalVerified = $false; BaselineOk = $false; AddOk = $false; PresentAfterAdd = $false; AllPersistent = $false; BlockRunValid = $false; ProbeBlocked = $false; GuardRefusedBeforeAdd = $false; GuardRefusedAfterRemoval = $false }
    $code = 4; $reason = 'error before decision'; $be = $null; $addedAt = $null; $deadMan = $null
    $script:opAbort = $false; $script:ArmWd = New-WatchdogState; $script:ArmBe = $null; $script:ArmAbortRemoval = $null
    $exports = New-Object System.Collections.ArrayList
    try {
        Write-Host '== 0 preflight (proof valid, SID safe, fence ABSENT) + wsl --shutdown ==' -ForegroundColor Cyan
        if (-not (Test-IsElevated)) { Write-Host 'FAIL: not elevated.' -ForegroundColor Red; return 2 }
        $be = New-RealBackend; $script:ArmBe = $be
        $pre = Get-FenceState -Backend $be
        $report.steps.fence_before = $pre
        if ($pre.State -ne 'ABSENT') { Write-Host "FAIL: the fence state is $($pre.State) before the run (stale objects or an unreadable engine). Run -Remove. Nothing added." -ForegroundColor Red; return 2 }
        $report.wsl_shutdown = Invoke-WslShutdown; $report.env = Get-ArmEnvSnapshot
        $report.steps.preflight = [ordered]@{ account_sid = $sid; sd_sddl = $plan.Sddl; filters_planned = @($plan.Filters | ForEach-Object { "$($_.Name) $($_.Key)" }) }
        Write-Host ('ROLLBACK FACT: these objects are PERSISTENT. Closing the engine or exiting does NOT remove them. Removal is by key (-Remove); ' + $(if ($DeadManTask) { 'the dead-man task, the finally block below and the wrapper''s follow-up -Remove all run it.' } else { 'NO dead-man task is registered (-DeadManTask is off): the finally block below and the wrapper''s follow-up -Remove are the rollback.' })) -ForegroundColor Yellow

        Write-Host '== 1 baselines and the absence check on an empty fence ==' -ForegroundColor Cyan
        $g0 = Test-FenceAllowsAccount -Backend $be
        $obs.GuardRefusedBeforeAdd = (-not $g0.Allowed -and $g0.State -eq 'ABSENT')
        $report.steps.guard_before_add = $g0
        Write-Host "gate on an empty fence: allowed=$($g0.Allowed) ($($g0.State))"
        $ctl = @(); foreach ($i in 1..3) { $ctl += Test-TcpConnect '1.1.1.1' 443 5000 }
        $report.steps.operator_baseline = $ctl
        $opBaseOk = (@($ctl | Where-Object { -not $_.ok }).Count -eq 0)
        $base = Invoke-ProbeTaskRun -RunId "$runId-base" -ExpectedBlocked $false -TimeoutSec 60
        $report.steps.account_baseline = $base
        $baseOpen = [bool]($base.valid -and $base.outbound_probe -and $base.outbound_probe.probe.connected)
        $obs.BaselineOk = ($opBaseOk -and $base.valid -and $base.token_sid -eq $sid -and $baseOpen)
        Write-Host ("operator baseline {0}/3; account baseline: valid={1} sid_ok={2} egress_open={3}" -f @($ctl | Where-Object { $_.ok }).Count, $base.valid, ($base.token_sid -eq $sid), $baseOpen)
        if (-not $obs.BaselineOk) { $obs.RemovalVerified = $true; $code = 5; $reason = 'no baseline'; Write-Host $reason -ForegroundColor Red }
        else {
            if ($DeadManTask) {
                $def = Get-DeadManDefinition -Name $script:DeadManName -ScriptPath $PSCommandPath -State $StateDir -Wfp $WfpScript -Minutes $DeadManMinutes -Now (Get-Date) -WfpHash $script:WrappedSha256Used -CodeSetId (Get-CodeSetId -Hashes (Get-CodeSetHashes -Folder $PSScriptRoot).Hashes)
                Register-DeadManTask -Def $def; $deadMan = $def
                $report.steps.dead_man_task = [ordered]@{ name = $def.TaskName; fires_at = $def.TriggerAt.ToString('o'); arguments = $def.Arguments }
                Write-Host "dead-man task registered: $($def.TaskName), fires at $($def.TriggerAt.ToString('HH:mm:ss')) and removes by key" -ForegroundColor Yellow
            }
            Write-Host '== 2 add the persistent set (one transaction, NON-dynamic session) ==' -ForegroundColor Cyan
            $add = Add-FenceSet -Backend $be -Plan $plan -Proof $proof
            $report.steps.add = $add
            $obs.AddOk = [bool]$add.Ok
            if ($add.Ok) { $addedAt = Get-Date; $obs.PresentAfterAdd = ($add.StateAfterAdd.State -eq 'PRESENT'); $obs.AllPersistent = [bool]$add.StateAfterAdd.AllPersistent; Write-Host "added; flags: $(($add.StateAfterAdd.Flags.GetEnumerator() | ForEach-Object { "$($_.Key)=$($_.Value)" }) -join ' ')" -ForegroundColor Yellow }
            else { Write-Host "ADD NOT DONE: $($add.Reason)" -ForegroundColor Red }
            if ($add.Ok) {
                $tick = {
                    $wd = $script:ArmWd; $now = $wd.Clock.Elapsed.TotalSeconds
                    if (($now - $wd.LastAt) -lt 2.0) { return }
                    $wd.LastAt = $now
                    $w = Test-TcpConnect '1.1.1.1' 443 2000
                    $abort = Update-WatchdogState -State $wd -Ok ([bool]$w.ok) -When ([string]$w.t) -Message ([string]$w.error) -Ms ([long]$w.ms)
                    if ($abort -and -not $script:opAbort) { $script:opAbort = $true; $wd.Aborted = $true; $script:ArmAbortRemoval = Remove-FenceSet -Backend $script:ArmBe; Write-Host 'OPERATOR TRAFFIC AFFECTED: two consecutive failures. Removed by key.' -ForegroundColor Red }
                }
                [void]$exports.Add((Invoke-PersistFilterExport -Label 'present' -Path (Join-Path $StateDir "$runId-filters-present.xml")))
                Write-Host '== 3 the account through the gate (watchdog every 2 s) ==' -ForegroundColor Cyan
                $gp = Invoke-GuardedProbe -Backend $be -RunId "$runId-block" -ExpectedBlocked $true -TimeoutSec 60 -Tick $tick
                $report.steps.account_under_fence = $gp
                $during = $gp.run
                $obs.BlockRunValid = [bool]($gp.started -and $during -and $during.valid -and $during.token_sid -eq $sid)
                $obs.ProbeBlocked = [bool]($obs.BlockRunValid -and $during.outbound_probe -and -not $during.outbound_probe.probe.connected)
                Write-Host ("under the fence: gate started the task={0}; valid={1}; outbound blocked={2} (code {3})" -f $gp.started, $obs.BlockRunValid, $obs.ProbeBlocked, $(if ($during -and $during.outbound_probe) { $during.outbound_probe.probe.error_code } else { '?' }))
                $dwellEnd = $addedAt.AddSeconds($DwellSeconds)
                while ((Get-Date) -lt $dwellEnd -and -not $script:opAbort) { & $tick; Start-Sleep -Milliseconds 500 }
                $chk = Get-FenceState -Backend $be
                $report.steps.fence_during = $chk
                if ($chk.State -ne 'PRESENT') { $obs.PresentAfterAdd = $false }
                [void]$exports.Add((Invoke-PersistFilterExport -Label 'before-removal' -Path (Join-Path $StateDir "$runId-filters-before-removal.xml")))
                $wd = $script:ArmWd
                $report.steps.watchdog = [ordered]@{ interval_seconds = 2; connects = $wd.Count; failures = $wd.Fail; max_consecutive_failures = $wd.MaxConsec; aborted = $wd.Aborted; failure_events = @($wd.Events) }
                $obs.OperatorAbort = [bool]$wd.Aborted
            }
            Write-Host '== 4 remove by key, verify, and the gate must now refuse ==' -ForegroundColor Cyan
            $rm = if ($script:ArmAbortRemoval) { $script:ArmAbortRemoval } else { Remove-FenceSet -Backend $be }
            $removedAt = Get-Date
            $report.steps.removal = $rm
            if ($addedAt) { $report.steps.objects_existed_seconds = [Math]::Round(($removedAt - $addedAt).TotalSeconds, 1) }
            if ($add.Ok) { [void]$exports.Add((Invoke-PersistFilterExport -Label 'after-removal' -Path (Join-Path $StateDir "$runId-filters-after-removal.xml"))) }
            $g1 = Test-FenceAllowsAccount -Backend $be
            $report.steps.guard_after_removal = $g1
            $obs.GuardRefusedAfterRemoval = (-not $g1.Allowed -and $g1.State -eq 'ABSENT')
            $gp2 = Invoke-GuardedProbe -Backend $be -RunId "$runId-guard2" -ExpectedBlocked $false -Starter { param($rid, $eb) throw 'the gate must not start the account when the fence is absent' }
            $report.steps.guarded_probe_after_removal = [ordered]@{ started = $gp2.started; outcome = $gp2.outcome }
            if ($gp2.started) { $obs.GuardRefusedAfterRemoval = $false }
            $after = Test-TcpConnect '1.1.1.1' 443 5000
            $report.steps.operator_after_removal = $after
            $afterRun = $null; $afterValid = $false; $acctOpen = $false
            if (-not $script:opAbort) {
                $afterRun = Invoke-ProbeTaskRun -RunId "$runId-after" -ExpectedBlocked $false -TimeoutSec 60
                $report.steps.account_after_removal_unguarded = $afterRun
                $afterValid = [bool]($afterRun.valid -and $afterRun.token_sid -eq $sid)
                $acctOpen = [bool]($afterValid -and $afterRun.outbound_probe -and $afterRun.outbound_probe.probe.connected)
            } else { $afterValid = $true; $acctOpen = $true }
            $obs.RemovalVerified = ($rm.Ok -and $after.ok -and ((-not $afterValid) -or $acctOpen))
            Write-Host "removal: objects gone=$($rm.Ok); operator connect after ok=$($after.ok); account after-run valid=$afterValid; egress open again=$acctOpen"
            $d = Get-Arm3aVerdict ([pscustomobject]$obs)
            $code = $d.Code; $reason = $d.Reason
        }
    } catch {
        $report.error = $_.Exception.Message + ' @ ' + $_.InvocationInfo.PositionMessage
        Write-Host "ERROR: $($_.Exception.Message)" -ForegroundColor Red
        $code = 4; $reason = 'error: ' + $_.Exception.Message
    } finally {
        # Persistent objects outlive this process: remove by key again whatever happened above.
        if ($be) {
            try {
                $last = Get-FenceState -Backend $be
                if ($last.State -ne 'ABSENT') { $fin = Remove-FenceSet -Backend $be; $report.steps.final_removal = $fin; if (-not $fin.Ok) { $code = 7; $reason = 'removal NOT verified in the final cleanup: run -Remove, then the README''s manual rollback' } }
                else { $report.steps.final_state = $last }
            } catch { $code = 7; $reason = "removal NOT verifiable in the final cleanup: $($_.Exception.Message)" }
            try { $be.Close() } catch {}
        }
        if ($deadMan -and $code -ne 7) { $report.steps.dead_man_unregistered = Unregister-TaskIfPresent -Name $script:DeadManName }
    }
    $report.exports = @($exports)
    $report.finished = (Get-Date).ToString("yyyy-MM-dd'T'HH:mm:ss.fffzzz"); $report.decision_inputs = $obs; $report.exit_code = $code; $report.exit_reason = $reason
    try { $p = Write-StateFile -Name "$runId.json" -Object $report; Write-Host "report: $p" -ForegroundColor Cyan } catch { Write-Host "could not write the report: $($_.Exception.Message)" -ForegroundColor Red }
    Write-Host ("RESULT: exit {0}: {1}" -f $code, $reason) -ForegroundColor $(if ($code -in @(0, 1)) { 'Green' } else { 'Yellow' })
    return $code
}

# ---- -DryRun --------------------------------------------------------------------------------------------------------------
function Invoke-DryRun {
    Write-Host '== DRY RUN: nothing is added; no WFP engine is opened ==' -ForegroundColor Yellow
    $imp = Import-WfpHelpers -Path $WfpScript -ExpectedSha256 $WfpSha256
    Write-Host "wrapped script: $($imp.Path)`n  sha256 (LF-normalised) $($imp.Sha256)`n  extracted: $($imp.Functions -join ', ') + the embedded C# ($($imp.CsharpChars) chars); the file itself is not modified or executed"
    Initialize-PersistType
    $sid = Get-SpikeSidOrNull; $fab = $false
    if (-not $sid) { $sid = 'S-1-5-21-1111111111-2222222222-3333333333-1001'; $fab = $true; Write-Host "account '$($script:SpikeUser)' not found: using a FABRICATED SID to build the plan ($sid). -Arm3a would exit 2." -ForegroundColor Yellow }
    else { Write-Host "account SID: $sid" }
    $op = Get-OperatorTokenSids
    $safety = @(Get-SafeSidProblems -Sid $sid)
    Write-Host ("operator SID {0}; SID safety: {1}" -f $op.User, $(if ($safety.Count -eq 0) { 'OK (distinct, not in the operator token groups)' } else { 'REFUSED (exit 3): ' + ($safety -join '; ') }))
    $plan = [BlarAI.WfpPersist.PersistPlan]::Build($sid)
    Write-Host ''; Write-Host '--- EXACTLY what -Arm3a (and the arm 3b arming script) would add ---'; Write-Host $plan.Describe()
    $m = [BlarAI.WfpPersist.PersistMarshal]::Build($plan)
    try {
        Write-Host ("marshalled in memory (this process is {0}-bit): provider flags 0x{1:X}, sublayer flags 0x{2:X}, filter flags {3}; sizeof FWPM_FILTER0 = {4} bytes" -f $(if ([Environment]::Is64BitProcess) { 64 } else { 32 }), $m.Provider.flags, $m.SubLayer.flags, (($m.Filters | ForEach-Object { '0x{0:X}' -f $_.flags }) -join '/'), $m.FilterImages[0].Length)
    } finally { $m.Free() }
    Write-Host ''; Write-Host '--- sequence of -Arm3a ---'
    Write-Host '  preflight (elevated, 64-bit, SID safe: exit 3 if the operator or one of his groups; proof valid; account, task, bin copies; fence ABSENT; no free-RAM check) -> wsl --shutdown (recorded) -> gate on the empty fence must REFUSE -> operator baseline 3x -> account baseline probe (egress open) -> dead-man task (SYSTEM, fires after DeadManMinutes, runs -Remove) -> ADD persistent set -> read back PRESENT + persistent -> export -> account probe THROUGH the gate (must be blocked; watchdog every 2 s) -> dwell -> export -> REMOVE BY KEY -> read back ABSENT -> export -> gate must REFUSE again and start nothing -> account probe unguarded (egress must be open) -> report -> finally: remove by key again, unregister the dead-man'
    $dm = Get-DeadManDefinition -Name $script:DeadManName -ScriptPath (Join-Path $PSScriptRoot 'spike-wfp-persist.ps1') -State $StateDir -Wfp $WfpScript -Minutes $DeadManMinutes -Now (Get-Date) -WfpHash $script:WrappedSha256Used -CodeSetId (Get-CodeSetId -Hashes (Get-CodeSetHashes -Folder $PSScriptRoot).Hashes)
    Write-Host ''; Write-Host ('--- dead-man task: registered by -Arm3a ONLY with -DeadManTask (default off; this invocation: {0}) ---' -f $(if ($DeadManTask) { 'ON' } else { 'OFF' })); $dm | Format-List | Out-String -Width 200 | Write-Host
    $ao = Test-AdminOnlyFolder -Path $PSScriptRoot
    if ($ao.Ok) { Write-Host "script folder: admin-only ($($ao.Checked) paths checked): a SYSTEM or elevated task may run from here." -ForegroundColor Green }
    else { Write-Host 'script folder: NOT admin-only. A SYSTEM dead-man task and the elevated wrapper would REFUSE to run from here:' -ForegroundColor Yellow; $ao.Problems | Select-Object -First 5 | ForEach-Object { Write-Host "   $_" -ForegroundColor Yellow } }
    Write-Host '--- exports (read-only) ---'; Write-Host ('  netsh wfp show filters file="{0}\<run>-filters-<present|before-removal|after-removal>.xml"  (searched for "{1}" and both filter keys)' -f $StateDir, $script:PersistMarker)
    Write-Host ''; Write-Host '--- rollback ---'
    Write-Host '  1. spike-wfp-persist.ps1 -Remove   (elevated; by key; idempotent; exits 0 only when ABSENT is read back)'
    Write-Host '  2. if that cannot run, from an elevated PowerShell (no other file needed; it deletes filters, then the sublayer, then the provider):'
    $script:ManualRollbackSnippet -split "`r?`n" | ForEach-Object { Write-Host "       $_" }
    Write-Host '  3. check: netsh wfp show filters file=check.xml, then search check.xml for "BlarAI #1682" (no hit = gone)'
    Write-Host ''; Write-Host '--- the rollback proof the add paths require ---'
    $proof = Test-RollbackProof -ProofPath $ProofPath -Folder $PSScriptRoot -WrappedSha256 $script:WrappedSha256Used
    if ($proof.Ok) { Write-Host "  VALID (written $($proof.Written)): every script of the code set matches the hashes the self-test ran against." -ForegroundColor Green }
    else { $proof.Problems | ForEach-Object { Write-Host "  NO VALID PROOF: $_" -ForegroundColor Yellow }; Write-Host '  -Arm3a and spike-arm3b-arm.ps1 would REFUSE to run until -SelfTest -WriteProof has been run on these exact files.' -ForegroundColor Yellow }
    $t = Get-ScheduledTask -TaskPath $script:SpikeTaskPath -TaskName $script:SpikeTaskName -ErrorAction SilentlyContinue
    Write-Host $(if ($t) { "spike task present, State=$($t.State)" } else { 'spike task NOT registered (provision first)' })
    Write-Host 'DRY RUN complete. Nothing was added.' -ForegroundColor Green
    if ($fab) { return 2 }
    if ($safety.Count) { return 3 }
    return 0
}

# ---- -SelfTest -----------------------------------------------------------------------------------------------------------
function Invoke-SelfTest {
    $script:f = 0; $script:tagsPassed = New-Object System.Collections.ArrayList; $script:tagsFailed = New-Object System.Collections.ArrayList; $script:failedNames = New-Object System.Collections.ArrayList
    $script:chkTotal = 0
    function Chk([string]$n, [bool]$c, [string]$tag = '') {
        $script:chkTotal++
        if ($c) { Write-Host "  [PASS] $n" -ForegroundColor Green; if ($tag) { [void]$script:tagsPassed.Add($tag) } }
        else { Write-Host "  [FAIL] $n" -ForegroundColor Red; $script:f++; [void]$script:failedNames.Add($n); if ($tag) { [void]$script:tagsFailed.Add($tag) } }
    }
    Write-Host '== extraction from the wrapped script and compile (no engine is opened) ==' -ForegroundColor Cyan
    # -SelfTest evaluates the repository copy of the validated script by design; -WriteProof does not: the proof pins that script's hash, so it must be pinned or in an admin-only folder.
    $imp = Import-WfpHelpers -Path $WfpScript -Unverified:(-not $WriteProof)
    Chk "all $($script:WrappedFunctions.Count) wrapped functions extracted" ($imp.Functions.Count -eq $script:WrappedFunctions.Count)
    Chk 'the wrapped script was only read (SHA-256 recorded)' ($imp.Sha256 -match '^[0-9A-F]{64}$')
    Initialize-PersistType
    Chk 'the WFP C# and the persist C# compile together in-process' ([bool]('BlarAI.WfpPersist.PersistEngine' -as [type]) -and [bool]('BlarAI.Wfp.Plan' -as [type]))
    $sid = 'S-1-5-21-1111111111-2222222222-3333333333-1001'; $other = 'S-1-5-21-1111111111-2222222222-3333333333-1002'
    $plan = [BlarAI.WfpPersist.PersistPlan]::Build($sid)
    Chk 'SDDL is exactly D:(A;;CC;;;<account sid>)' ($plan.Sddl -eq "D:(A;;CC;;;$sid)")
    Chk 'two filters, both BLOCK, none carrying the loopback condition' (($plan.Filters.Count -eq 2) -and (@($plan.Filters | Where-Object { $_.Action -ne [BlarAI.Wfp.Plan]::FWP_ACTION_BLOCK -or $_.Loopback }).Count -eq 0))
    $refused = 0; foreach ($b in @('S-1-1-0', 'S-1-5-32-545', 'S-1-5-18', 'S-1-5-11', 'S-1-5-32-544', '', 'garbage')) { $t = $false; try { [void][BlarAI.WfpPersist.PersistPlan]::Build($b) } catch { $t = $true }; if ($t) { $refused++ } }
    Chk 'the plan refuses non-account SIDs (Everyone, Users, SYSTEM, Authenticated Users, Administrators, empty, garbage)' ($refused -eq 7)
    Chk 'the target account is the throwaway spike account, never blarai-coder (the real coder account''s containment state is not touched)' (($script:SpikeUser -eq 'blarai-spike') -and ($script:SpikeUser -ne 'blarai-coder'))
    Chk 'SID safety: the operator SID is refused (exit 3 path)' ((Test-CoderSidSafe $sid $sid @()).Count -ge 1)
    Chk 'SID safety: a group in the operator token is refused' ((Test-CoderSidSafe $sid $other @($sid)).Count -ge 1)
    Chk 'SID safety: a distinct account SID is accepted' ((Test-CoderSidSafe $sid $other @('S-1-5-32-545')).Count -eq 0)
    Write-Host '== fixed keys and persistence flags ==' -ForegroundColor Cyan
    $PK = [BlarAI.WfpPersist.PersistKeys]
    Chk 'the library''s key strings equal the C# key constants (provider, sublayer, both filters)' ((([guid]$script:PersistProviderKey) -eq [BlarAI.WfpPersist.PersistKeys]::Provider) -and (([guid]$script:PersistSubLayerKey) -eq [BlarAI.WfpPersist.PersistKeys]::SubLayer) -and (([guid]$script:PersistFilterKeys[0]) -eq [BlarAI.WfpPersist.PersistKeys]::FilterV4) -and (([guid]$script:PersistFilterKeys[1]) -eq [BlarAI.WfpPersist.PersistKeys]::FilterV6))
    Chk 'the persistent keys differ from the dynamic spike''s (arms 1 and 2 cannot be confused with this set)' (([BlarAI.WfpPersist.PersistKeys]::Provider -ne [BlarAI.Wfp.Plan]::ProviderKey) -and ([BlarAI.WfpPersist.PersistKeys]::SubLayer -ne [BlarAI.Wfp.Plan]::SubLayerKey) -and (@($plan.Filters | Where-Object { $_.Key -in @(([BlarAI.Wfp.Plan]::Build($sid)).Filters | ForEach-Object { $_.Key }) }).Count -eq 0))
    Chk 'the plan''s filter keys are the fixed keys, in V4, V6 order' (($plan.Filters[0].Key -eq [BlarAI.WfpPersist.PersistKeys]::FilterV4) -and ($plan.Filters[1].Key -eq [BlarAI.WfpPersist.PersistKeys]::FilterV6))
    Chk 'every object name carries the marker "BlarAI #1682"' (@($plan.Filters | Where-Object { $_.Name -notlike 'BlarAI #1682*' }).Count -eq 0 -and [BlarAI.WfpPersist.PersistKeys]::Marker -eq $script:PersistMarker)
    Chk 'persistent flag constant is 0x1 (provider, sublayer and filter flags in fwpmtypes.h)' ([BlarAI.WfpPersist.PersistKeys]::Persistent -eq 1)
    $m = [BlarAI.WfpPersist.PersistMarshal]::Build($plan)
    try {
        Chk 'the marshalled provider, sublayer and EVERY filter carry the persistent flag' (($m.Provider.flags -eq 1) -and ($m.SubLayer.flags -eq 1) -and (@($m.Filters | Where-Object { $_.flags -ne 1 }).Count -eq 0) -and ($m.Filters.Count -eq 2))
        Chk 'every filter references the persistent provider and sublayer' ((@($m.Filters | Where-Object { $_.subLayerKey -ne [BlarAI.WfpPersist.PersistKeys]::SubLayer }).Count -eq 0) -and (@($m.Filters | Where-Object { [Runtime.InteropServices.Marshal]::PtrToStructure($_.providerKey, [type][guid]) -ne [BlarAI.WfpPersist.PersistKeys]::Provider }).Count -eq 0) -and ([Runtime.InteropServices.Marshal]::PtrToStructure($m.SubLayer.providerKey, [type][guid]) -eq [BlarAI.WfpPersist.PersistKeys]::Provider))
        $allUser = $true; $condSize = [Runtime.InteropServices.Marshal]::SizeOf([type][BlarAI.Wfp.FWPM_FILTER_CONDITION0])
        foreach ($fl in $m.Filters) {
            $has = $false
            for ($j = 0; $j -lt [int]$fl.numFilterConditions; $j++) {
                $c = [Runtime.InteropServices.Marshal]::PtrToStructure([IntPtr]($fl.filterCondition.ToInt64() + $j * $condSize), [type][BlarAI.Wfp.FWPM_FILTER_CONDITION0])
                if ($c.fieldKey -eq [BlarAI.Wfp.Plan]::CondAleUserId -and $c.conditionValue.type -eq 14 -and $c.matchType -eq 0) { $has = $true }
            }
            if (-not $has) { $allUser = $false }
        }
        Chk 'EVERY marshalled filter carries ALE_USER_ID / SECURITY_DESCRIPTOR / MATCH_EQUAL' $allUser
        Chk 'layers are ALE_AUTH_CONNECT V4 and V6 (fwpmu.h literals)' (($m.Filters[0].layerKey -eq [guid]'c38d57d1-05a7-4c33-904f-7fbceee60e82') -and ($m.Filters[1].layerKey -eq [guid]'4a72393b-319f-44bc-84c3-ba54dcb3b6b4'))
        if ([Environment]::Is64BitProcess) { Chk 'x64 sizeof FWPM_FILTER0 == 200 and FWPM_FILTER_CONDITION0 == 40 (hand-derived from fwpmtypes.h)' (([Runtime.InteropServices.Marshal]::SizeOf([type][BlarAI.Wfp.FWPM_FILTER0]) -eq 200) -and ($condSize -eq 40)) }
        else { Write-Host '  [SKIP] struct-size asserts need a 64-bit process' -ForegroundColor Yellow }
    } finally { $m.Free() }
    Write-Host '== the manual rollback snippet compiles (it is NOT run) ==' -ForegroundColor Cyan
    $cs = [regex]::Match($script:ManualRollbackSnippet, '(?s)@"\r?\n(.*?)\r?\n"@').Groups[1].Value
    $compiled = $false; try { Add-Type -TypeDefinition $cs -Language CSharp; $compiled = [bool]('ManualWfpRollback' -as [type]) } catch { $compiled = $false }
    Chk 'the snippet''s C# compiles and exposes Run()' ($compiled -and ('ManualWfpRollback' -as [type]).GetMethod('Run') -ne $null)
    $ix = @($script:PersistFilterKeys[0], $script:PersistFilterKeys[1], $script:PersistSubLayerKey, $script:PersistProviderKey | ForEach-Object { $script:ManualRollbackSnippet.IndexOf($_) })
    Chk 'the snippet names all four keys, deleting filters, then the sublayer, then the provider' (($ix -notcontains -1) -and ($ix[0] -lt $ix[2]) -and ($ix[1] -lt $ix[2]) -and ($ix[2] -lt $ix[3]))
    Write-Host '== rollback and fail-closed logic against the in-memory fake ==' -ForegroundColor Cyan
    $proofOk = [pscustomobject]@{ Kind = 'RollbackProof'; Ok = $true }
    $full = New-FakeBackend; [void]$full.AddAll($plan)
    Chk 'state: a full fake set reads PRESENT, all persistent' ((Get-FenceState -Backend $full).State -eq 'PRESENT' -and (Get-FenceState -Backend $full).AllPersistent)
    $r = Remove-FenceSet -Backend $full
    $dels = @($full.Calls | Where-Object { $_ -like 'delete *' } | ForEach-Object { ($_ -split ' ')[1] })
    Chk 'remove (full set): Ok, state ABSENT, deletes in the order filter, filter, sublayer, provider' (($r.Ok -eq $true) -and ($r.StateAfter.State -eq 'ABSENT') -and (($dels -join ',') -eq 'filter,filter,sublayer,provider') -and (@($r.Rows | Where-Object { $_.status -eq 'deleted' }).Count -eq 4)) 'remove-full-set'
    $half = New-FakeBackend -FailAddAfter 3
    $threw = $false; try { [void]$half.AddAll($plan) } catch { $threw = $true }
    $hs = Get-FenceState -Backend $half
    Chk 'a half-failed add (provider, sublayer, one filter, then an error) reads PARTIAL' ($threw -and $hs.State -eq 'PARTIAL' -and $hs.Present.Count -eq 3 -and $hs.Missing.Count -eq 1) 'partial-detected'
    $r2 = Remove-FenceSet -Backend $half
    Chk 'remove (half-failed add): Ok, ABSENT, the missing filter reported as not_found rather than an error' (($r2.Ok -eq $true) -and ($r2.StateAfter.State -eq 'ABSENT') -and (@($r2.Rows | Where-Object { $_.status -eq 'not_found' }).Count -eq 1) -and ($r2.Errors.Count -eq 0)) 'remove-half-failed-add'
    $none = New-FakeBackend
    $r3 = Remove-FenceSet -Backend $none
    Chk 'remove (nothing there): Ok, every key not_found, no error (idempotent)' (($r3.Ok -eq $true) -and (@($r3.Rows | Where-Object { $_.status -eq 'not_found' }).Count -eq 4) -and ($r3.Errors.Count -eq 0)) 'remove-when-absent'
    $bad = New-FakeBackend; [void]$bad.AddAll($plan); $bad.FailDelete = @($script:PersistSubLayerKey)
    $r4 = Remove-FenceSet -Backend $bad
    Chk 'remove (one delete fails): Ok is FALSE, the failing key is named, the state read back is PARTIAL' (($r4.Ok -eq $false) -and ($r4.Errors.Count -eq 1) -and ($r4.Errors[0].kind -eq 'sublayer') -and ($r4.StateAfter.State -eq 'PARTIAL')) 'remove-reports-delete-error'
    Chk 'remove (one delete fails): every OTHER key was still tried and deleted (the provider after the failure too)' (($bad.Store.Count -eq 1) -and ($bad.Store.ContainsKey("sublayer|$($script:PersistSubLayerKey)")) -and (@($bad.Calls | Where-Object { $_ -like 'delete provider *' }).Count -eq 1)) 'remove-continues-after-error'
    $unk = New-FakeBackend -Unreadable $true
    $us = Get-FenceState -Backend $unk
    Chk 'state: an engine that cannot be read is UNKNOWN with the error text (never ABSENT)' (($us.State -eq 'UNKNOWN') -and ($us.Error -match 'unreadable')) 'unknown-detected'
    Chk 'state: an empty fake is ABSENT' ((Get-FenceState -Backend $none).State -eq 'ABSENT') 'absent-detected'
    $halfB = New-FakeBackend -FailAddAfter 3; try { [void]$halfB.AddAll($plan) } catch {}
    $gAbsent = Test-FenceAllowsAccount -Backend $none; $gPartial = Test-FenceAllowsAccount -Backend $halfB; $gUnk = Test-FenceAllowsAccount -Backend $unk; $gFull = New-FakeBackend; [void]$gFull.AddAll($plan)
    Chk 'gate: ABSENT, PARTIAL and UNKNOWN all refuse; only PRESENT allows' ((-not $gAbsent.Allowed) -and (-not $gPartial.Allowed) -and (-not $gUnk.Allowed) -and (Test-FenceAllowsAccount -Backend $gFull).Allowed -and ($gAbsent.Reason -match 'ABSENT') -and ($gPartial.Reason -match 'PARTIAL') -and ($gUnk.Reason -match 'UNKNOWN')) 'guard-refuses-unless-present'
    $started = New-Object System.Collections.ArrayList
    $starter = { param($rid, $eb) [void]$started.Add($rid); [pscustomobject]@{ valid = $true } }.GetNewClosure()
    $gp1 = Invoke-GuardedProbe -Backend $none -RunId 'x' -Starter $starter
    $gp2 = Invoke-GuardedProbe -Backend $halfB -RunId 'x' -Starter $starter
    $gp3 = Invoke-GuardedProbe -Backend $unk -RunId 'x' -Starter $starter
    Chk 'guarded probe: with the fence ABSENT, PARTIAL or UNKNOWN the account''s task is NOT started (outcome fence_absent_not_started)' (($started.Count -eq 0) -and (-not $gp1.started) -and ($gp1.outcome -eq 'fence_absent_not_started') -and (-not $gp2.started) -and (-not $gp3.started)) 'guard-refuses-unless-present'
    $gp4 = Invoke-GuardedProbe -Backend $gFull -RunId 'y' -Starter $starter
    Chk 'guarded probe: with the fence PRESENT the task is started exactly once' (($started.Count -eq 1) -and $gp4.started)
    $np = New-FakeBackend
    $a1 = Add-FenceSet -Backend $np -Plan $plan -Proof $null
    $a2 = Add-FenceSet -Backend $np -Plan $plan -Proof ([pscustomobject]@{ Kind = 'RollbackProof'; Ok = $false })
    $a3 = Add-FenceSet -Backend $np -Plan $plan -Proof ([pscustomobject]@{ Ok = $true })
    $a4 = Add-FenceSet -Backend $np -Plan $plan -Proof 'yes'
    Chk 'add path: refused with no proof, a failed proof, a token of the wrong kind, or a bare string; the backend''s AddAll is never called' (($a1.Refused -and $a2.Refused -and $a3.Refused -and $a4.Refused) -and (@($np.Calls | Where-Object { $_ -eq 'addall' }).Count -eq 0) -and ($np.Store.Count -eq 0)) 'add-refused-without-proof'
    $stale = New-FakeBackend; $stale.Store["filter|$($script:PersistFilterKeys[0])"] = 1
    $a5 = Add-FenceSet -Backend $stale -Plan $plan -Proof $proofOk
    Chk 'add path: refused over a stale object (state PARTIAL), nothing added, nothing deleted' (($a5.Refused -eq $true) -and ($a5.Reason -match 'PARTIAL') -and (@($stale.Calls | Where-Object { $_ -eq 'addall' }).Count -eq 0) -and ($stale.Store.Count -eq 1)) 'add-refused-over-stale-objects'
    $unr = New-FakeBackend -Unreadable $true
    $a6 = Add-FenceSet -Backend $unr -Plan $plan -Proof $proofOk
    Chk 'add path: refused when the engine cannot be read (UNKNOWN), AddAll never called' (($a6.Refused -eq $true) -and (@($unr.Calls | Where-Object { $_ -eq 'addall' }).Count -eq 0)) 'add-refused-over-stale-objects'
    $ok = New-FakeBackend
    $a7 = Add-FenceSet -Backend $ok -Plan $plan -Proof $proofOk
    Chk 'add path: with a valid token on an empty fence it adds all four objects and reads back PRESENT, persistent' (($a7.Ok -eq $true) -and ($a7.StateAfterAdd.State -eq 'PRESENT') -and $a7.StateAfterAdd.AllPersistent -and ($ok.Store.Count -eq 4))
    $fa = New-FakeBackend -FailAddAfter 2
    $a8 = Add-FenceSet -Backend $fa -Plan $plan -Proof $proofOk
    Chk 'add path: a half-failed add is rolled back by key to ABSENT and reported as not added' (($a8.Ok -eq $false) -and ($a8.Rollback.Ok -eq $true) -and ((Get-FenceState -Backend $fa).State -eq 'ABSENT') -and ($fa.Store.Count -eq 0) -and ($a8.Reason -match 'rolled back')) 'add-failure-rolls-back'
    $nf = New-FakeBackend -AddClearsFlags $true
    $a9 = Add-FenceSet -Backend $nf -Plan $plan -Proof $proofOk
    Chk 'add path: an add that "succeeds" without the persistent flag is rolled back (it would not survive a reboot)' (($a9.Ok -eq $false) -and ($a9.Rollback.Ok -eq $true) -and ($nf.Store.Count -eq 0)) 'add-failure-rolls-back'
    Write-Host '== the rollback proof and its hash binding ==' -ForegroundColor Cyan
    $tmp = Join-Path ([IO.Path]::GetTempPath()) ('persist-proof-' + [guid]::NewGuid().ToString('N')); New-Item -ItemType Directory -Path $tmp | Out-Null
    try {
        foreach ($n in $script:CodeSetFiles) { [IO.File]::WriteAllText((Join-Path $tmp $n), "# fake $n`n") }
        # the fake persist script carries 100 check call sites, so the proof's claimed number of checks can be judged against it
        [IO.File]::WriteAllText((Join-Path $tmp 'spike-wfp-persist.ps1'), ((1..100 | ForEach-Object { "    Chk 'site$_' `$true" }) -join "`n") + "`n")
        $wrapped = Join-Path $tmp 'wrapped-1671.ps1'; [IO.File]::WriteAllText($wrapped, "# fake wrapped script`n`$x = 1`n")
        $hashes = (Get-CodeSetHashes -Folder $tmp).Hashes
        $wh = Get-NormalizedSha256 -Path $wrapped
        $pp = Join-Path $tmp 'proof.json'
        $now = [datetimeoffset]::Now
        $sibOk = @(1..4 | ForEach-Object { [ordered]@{ name = "sibling$_"; passed = $true; checks = 20 } })
        $mk = { param($written, $tags, $failed, $run = 80, $passedN = 80, $sib = $sibOk, $whash = $wh) (ConvertTo-Json -InputObject (New-RollbackProofObject -Hashes $hashes -PassedTags $tags -FailedChecks $failed -HostInfo 'selftest' -When $written -WrappedHash $whash -ChecksRun $run -ChecksPassed $passedN -Siblings $sib) -Depth 8) }
        $allTags = @($script:RequiredRollbackTags)
        $chkProof = { Test-RollbackProof -ProofPath $pp -Folder $tmp -WrappedSha256 (Get-NormalizedSha256 -Path $wrapped) }
        [IO.File]::WriteAllText($pp, (& $mk $now.ToString('o') $allTags @()))
        $t1 = & $chkProof
        Chk 'proof: a complete, fresh proof whose hashes match (scripts AND the wrapped #1671 script) is accepted and yields the token' (($t1.Ok -eq $true) -and ($t1.Kind -eq 'RollbackProof') -and ($t1.Problems.Count -eq 0))
        $first = $script:CodeSetFiles[4]; $firstPath = Join-Path $tmp $first
        [IO.File]::WriteAllText($firstPath, "# edited after the self-test`n")
        $t2 = & $chkProof
        Chk 'proof: editing ONE script after the self-test invalidates it, naming the file' (($t2.Ok -eq $false) -and (@($t2.Problems | Where-Object { $_ -match [regex]::Escape($first) }).Count -eq 1)) 'proof-hash-binding'
        [IO.File]::WriteAllText($firstPath, "# fake $first`n")
        Chk 'proof: restoring the exact bytes validates it again' ((& $chkProof).Ok -eq $true) 'proof-hash-binding'
        Chk 'proof: a CRLF copy of the same text validates (hashes are over LF-normalised bytes)' ((& { [IO.File]::WriteAllText($firstPath, "# fake $first`r`n"); (& $chkProof).Ok }) -eq $true) 'proof-hash-binding'
        [IO.File]::WriteAllText($firstPath, "# fake $first`n")
        [IO.File]::WriteAllText($wrapped, "# fake wrapped script`n`$x = 2`n")
        $t3 = & $chkProof
        Chk 'proof: a ONE-TOKEN edit of the wrapped #1671 script (the code that builds the security descriptor) invalidates it' (($t3.Ok -eq $false) -and (@($t3.Problems | Where-Object { $_ -match 'wrapped #1671 script changed' }).Count -eq 1)) 'proof-hash-binding'
        [IO.File]::WriteAllText($wrapped, "# fake wrapped script`n`$x = 1`n")
        Chk 'proof: restoring the wrapped script validates it again; no wrapped-script hash supplied is refused' (((& $chkProof).Ok -eq $true) -and (-not (Test-RollbackProof -ProofPath $pp -Folder $tmp -WrappedSha256 '').Ok)) 'proof-hash-binding'
        [IO.File]::WriteAllText($pp, (& $mk $now.ToString('o') $allTags @() 80 80 $sibOk ''))
        Chk 'proof: a proof with no hash of the wrapped script is refused' ((& $chkProof).Ok -eq $false) 'proof-hash-binding'
        [IO.File]::WriteAllText($pp, (& $mk $now.ToString('o') $allTags @() 0 0 $sibOk))
        Chk 'proof: a proof written without running a self-test (0 checks run) is refused' ((& $chkProof).Ok -eq $false) 'proof-hash-binding'
        [IO.File]::WriteAllText($pp, (& $mk $now.ToString('o') $allTags @() 999 999 $sibOk))
        Chk 'proof: a claimed 999 checks run, more than the self-test has check sites (110 here), is refused as not a real run' (((& $chkProof).Ok -eq $false) -and (@((& $chkProof).Problems | Where-Object { $_ -match 'not a real run' }).Count -eq 1)) 'proof-hash-binding'
        $fc = ConvertFrom-Json (& $mk $now.ToString('o') $allTags @()); $fc.failed_checks = @('a check failed'); $fc.passed = $true; $fc.rollback_checks_passed = $true
        [IO.File]::WriteAllText($pp, (ConvertTo-Json -InputObject $fc -Depth 8))
        Chk 'proof: failed_checks non-empty is refused even when the passed flags were edited to true' (((& $chkProof).Ok -eq $false) -and (@((& $chkProof).Problems | Where-Object { $_ -match 'records failed checks' }).Count -eq 1)) 'proof-hash-binding'
        [IO.File]::WriteAllText($pp, (& $mk $now.ToString('o') $allTags @() 80 79 $sibOk))
        Chk 'proof: a proof recording fewer checks passed than run is refused' ((& $chkProof).Ok -eq $false)
        [IO.File]::WriteAllText($pp, (& $mk $now.ToString('o') $allTags @() 80 80 @()))
        $noSib = (& $chkProof).Ok
        [IO.File]::WriteAllText($pp, (& $mk $now.ToString('o') $allTags @() 80 80 @(@{ name = 'a'; passed = $true; checks = 20 }, @{ name = 'b'; passed = $true; checks = 20 }, @{ name = 'c'; passed = $true; checks = 20 }, @{ name = 'd'; passed = $false; checks = 20 })))
        $failSib = (& $chkProof).Ok
        Chk 'proof: a proof with no sibling self-test results, or with one that failed, is refused' (($noSib -eq $false) -and ($failSib -eq $false))
        [IO.File]::WriteAllText($pp, (& $mk $now.ToString('o') $allTags @()))
        Remove-Item -LiteralPath (Join-Path $tmp $script:CodeSetFiles[5]) -Force
        Chk 'proof: a code-set file that is missing from the folder invalidates it, naming the file' ((-not (& $chkProof).Ok) -and (@((& $chkProof).Problems | Where-Object { $_ -match [regex]::Escape($script:CodeSetFiles[5]) }).Count -ge 1))
        [IO.File]::WriteAllText((Join-Path $tmp $script:CodeSetFiles[5]), "# fake $($script:CodeSetFiles[5])`n")
        [IO.File]::WriteAllText($pp, (& $mk $now.AddHours(-25).ToString('o') $allTags @()))
        Chk 'proof: older than 24 hours is refused' ((Test-RollbackProof -ProofPath $pp -Folder $tmp -WrappedSha256 (Get-NormalizedSha256 -Path $wrapped) -Now $now).Ok -eq $false)
        [IO.File]::WriteAllText($pp, (& $mk $now.ToString('o') @($allTags | Select-Object -First ($allTags.Count - 1)) @()))
        Chk 'proof: a missing rollback check tag is refused, naming it' ((-not (& $chkProof).Ok) -and (@((& $chkProof).Problems | Where-Object { $_ -match [regex]::Escape($allTags[-1]) }).Count -ge 1))
        [IO.File]::WriteAllText($pp, (& $mk $now.ToString('o') $allTags @('a failed check')))
        Chk 'proof: a recorded failure is refused' ((& $chkProof).Ok -eq $false)
        Chk 'proof: no file, and a file that is not JSON, are refused' ((-not (Test-RollbackProof -ProofPath (Join-Path $tmp 'nope.json') -Folder $tmp -WrappedSha256 (Get-NormalizedSha256 -Path $wrapped)).Ok) -and (& { [IO.File]::WriteAllText($pp, '{not json'); -not (& $chkProof).Ok }))
        [IO.File]::WriteAllText($pp, (& $mk ($now.AddHours(2)).ToString('o') $allTags @()))
        Chk 'proof: dated in the future is refused' ((Test-RollbackProof -ProofPath $pp -Folder $tmp -WrappedSha256 (Get-NormalizedSha256 -Path $wrapped) -Now $now).Ok -eq $false)
        $old = (& $mk $now.ToString('o') $allTags @()) -replace '"schema":\s*2', '"schema": 1'
        [IO.File]::WriteAllText($pp, $old)
        Chk 'proof: an old-schema proof (before the wrapped-script binding) is refused' ((& $chkProof).Ok -eq $false)
    } finally { Remove-Item -LiteralPath $tmp -Recurse -Force -ErrorAction SilentlyContinue }
    Write-Host '== the wrapped script is pinned before its text becomes code; the independent rollback; the admin-only folder rule ==' -ForegroundColor Cyan
    $pt = Join-Path ([IO.Path]::GetTempPath()) ('pin-' + [guid]::NewGuid().ToString('N') + '.ps1'); [IO.File]::WriteAllText($pt, "`$csharp = @'`nnamespace BlarAI.Wfp { }`n'@`n")
    try {
        $pinErr = ''; try { $null = Import-WfpHelpers -Path $pt -ExpectedSha256 ('A' * 64) } catch { $pinErr = $_.Exception.Message }
        $okErr = ''; try { $null = Import-WfpHelpers -Path $pt -ExpectedSha256 (Get-NormalizedSha256 -Path $pt) } catch { $okErr = $_.Exception.Message }
        Chk 'pin: a wrapped script whose hash is not the pinned one is refused BEFORE it is parsed' (($pinErr -match 'is not the pinned') -and ($pinErr -notmatch 'does not parse'))
        Chk 'pin: with the right hash the import proceeds past the pin (and fails later only because this file is not the real script)' (($okErr -ne '') -and ($okErr -notmatch 'is not the pinned'))
    } finally { Remove-Item -LiteralPath $pt -Force -ErrorAction SilentlyContinue }
    $gt = Join-Path ([IO.Path]::GetTempPath()) ('gate-' + [guid]::NewGuid().ToString('N')); New-Item -ItemType Directory -Path $gt | Out-Null
    try {
        $gf = Join-Path $gt 'w.ps1'; [IO.File]::WriteAllText($gf, "Set-Content -LiteralPath '$gt\pwned.txt' -Value evaluated`n`$csharp = 'x'`n")
        $gateErr = ''; try { $null = Import-WfpHelpers -Path $gf } catch { $gateErr = $_.Exception.Message }
        Chk 'wrapped-script gate: neither pinned nor in an admin-only folder -> refused BEFORE any of its text is evaluated (nothing ran)' (($gateErr -match 'neither pinned') -and -not (Test-Path (Join-Path $gt 'pwned.txt')))
        $wrongErr = ''; try { $null = Import-WfpHelpers -Path $gf -ExpectedSha256 ('B' * 64) } catch { $wrongErr = $_.Exception.Message }
        Chk 'wrapped-script gate: a wrong pin is refused before evaluation too' (($wrongErr -match 'is not the pinned') -and -not (Test-Path (Join-Path $gt 'pwned.txt')))
    } finally { Remove-Item -LiteralPath $gt -Recurse -Force -ErrorAction SilentlyContinue }
    $impReal = Import-WfpHelpers -Path $WfpScript -Unverified:(-not $WriteProof)
    Chk 'single read: Import-WfpHelpers returns, and records for the proof, the hash of the bytes it evaluated' (($impReal.Sha256 -eq $script:WrappedSha256Used) -and ($impReal.Sha256 -eq (Get-NormalizedSha256 -Path $WfpScript)))
    Chk 'single read: a library loaded through Get-VerifiedLibBlock is represented by the hash of the bytes that ran, and equals a fresh hash of the unchanged file' (($script:LoadedLibHashes['spike-persist-lib.ps1'] -eq (Get-NormalizedSha256 -Path (Join-Path $PSScriptRoot 'spike-persist-lib.ps1'))) -and ($script:LoadedLibHashes.Count -ge 3))
    $csTmp = Join-Path ([IO.Path]::GetTempPath()) ('csid-' + [guid]::NewGuid().ToString('N')); New-Item -ItemType Directory -Path $csTmp | Out-Null
    try {
        foreach ($n in $script:CodeSetFiles) { [IO.File]::WriteAllText((Join-Path $csTmp $n), "# fake $n`n") }
        $idA = Get-CodeSetId -Hashes (Get-CodeSetHashes -Folder $csTmp).Hashes
        Chk 'code-set id: stable for unchanged files, 64 hex characters; Test-CodeSetId accepts it' (($idA -match '^[0-9A-F]{64}$') -and ($idA -eq (Get-CodeSetId -Hashes (Get-CodeSetHashes -Folder $csTmp).Hashes)) -and (Test-CodeSetId -Folder $csTmp -Expected $idA).Ok)
        [IO.File]::WriteAllText((Join-Path $csTmp $script:CodeSetFiles[6]), "# changed after arming`n")
        Chk 'code-set id: changing ONE script after arming makes Test-CodeSetId refuse (the SYSTEM task falls back to the self-contained rollback)' ((-not (Test-CodeSetId -Folder $csTmp -Expected $idA).Ok) -and ((Test-CodeSetId -Folder $csTmp -Expected $idA).Reason -match 'a script changed'))
        Remove-Item -LiteralPath (Join-Path $csTmp $script:CodeSetFiles[2]) -Force
        Chk 'code-set id: a missing code-set file is refused, naming it' ((Test-CodeSetId -Folder $csTmp -Expected $idA).Reason -match [regex]::Escape($script:CodeSetFiles[2]))
    } finally { Remove-Item -LiteralPath $csTmp -Recurse -Force -ErrorAction SilentlyContinue }
    $good = ConvertFrom-ManualRollbackOutput -Text ("filter f1300003-0000-4d8e-9a31-2b6d4c8e3f21 0x00000000`nfilter f1300004-0000-4d8e-9a31-2b6d4c8e3f22 0x80320003`nsublayer 0x80320007`nprovider 0x00000000`n")
    $badSt = ConvertFrom-ManualRollbackOutput -Text ("filter f1300003-0000-4d8e-9a31-2b6d4c8e3f21 0x00000000`nfilter f1300004-0000-4d8e-9a31-2b6d4c8e3f22 0x00000000`nsublayer 0x8032000A`nprovider 0x00000000`n")
    $short = ConvertFrom-ManualRollbackOutput -Text ("filter f1300003-0000-4d8e-9a31-2b6d4c8e3f21 0x00000000`nprovider 0x00000000`n")
    Chk 'manual rollback output: four rows, each deleted or already gone -> Ok' (($good.Ok -eq $true) -and ($good.Rows.Count -eq 4))
    Chk 'manual rollback output: one error status (FWP_E_IN_USE) -> not Ok; fewer than four rows -> not Ok; an engine-open failure line -> not Ok' (($badSt.Ok -eq $false) -and ($short.Ok -eq $false) -and ((ConvertFrom-ManualRollbackOutput -Text 'engine open failed 0x80320001').Ok -eq $false))
    $T = 'S-1-5-18'; $A = 'S-1-5-32-544'; $U = 'S-1-5-32-545'
    $row = { param($sid, $type, $rights, $anc = $false, $io = $false) [pscustomobject]@{ Path = 'C:\x'; Sid = $sid; Type = $type; Rights = [int64]$rights; Ancestor = $anc; InheritOnly = $io } }
    Chk 'admin-only: SYSTEM and Administrators with full control, Users read-and-execute -> no problem' ((Get-NonAdminWriteGrants -Rules @((& $row $T 'Allow' 0x1F01FF), (& $row $A 'Allow' 0x1F01FF), (& $row $U 'Allow' 0x1200A9)) -OwnerSid $A -Path 'C:\x').Count -eq 0)
    Chk 'admin-only: Users with Modify (0x1301BF), or only create-files (0x2), or append (0x4) on the folder -> a problem each' (((Get-NonAdminWriteGrants -Rules @((& $row $U 'Allow' 0x1301BF)) -OwnerSid $A -Path 'C:\x').Count -eq 1) -and ((Get-NonAdminWriteGrants -Rules @((& $row $U 'Allow' 0x2)) -OwnerSid $A -Path 'C:\x').Count -eq 1) -and ((Get-NonAdminWriteGrants -Rules @((& $row $U 'Allow' 0x4)) -OwnerSid $A -Path 'C:\x').Count -eq 1))
    Chk 'admin-only: a Deny rule does not excuse an Allow; GenericWrite and GenericAll count' (((Get-NonAdminWriteGrants -Rules @((& $row $U 'Deny' 0x2), (& $row $U 'Allow' 0x2)) -OwnerSid $A -Path 'C:\x').Count -eq 1) -and ((Get-NonAdminWriteGrants -Rules @((& $row $U 'Allow' 0x40000000)) -OwnerSid $A -Path 'C:\x').Count -eq 1) -and ((Get-NonAdminWriteGrants -Rules @((& $row $U 'Allow' 0x10000000)) -OwnerSid $A -Path 'C:\x').Count -eq 1))
    Chk 'admin-only: an owner that is not SYSTEM, Administrators or TrustedInstaller is a problem' ((Get-NonAdminWriteGrants -Rules @() -OwnerSid 'S-1-5-21-1-2-3-1001' -Path 'C:\x').Count -eq 1)
    Chk 'admin-only: on an ANCESTOR, create-files and append are fine (Users have them on ProgramData) but delete-child and change-permissions are not' (((Get-NonAdminWriteGrants -Rules @((& $row $U 'Allow' 0x6 $true)) -OwnerSid $null -Path 'C:\p').Count -eq 0) -and ((Get-NonAdminWriteGrants -Rules @((& $row $U 'Allow' 0x40 $true)) -OwnerSid $null -Path 'C:\p').Count -eq 1) -and ((Get-NonAdminWriteGrants -Rules @((& $row $U 'Allow' 0x40000 $true)) -OwnerSid $null -Path 'C:\p').Count -eq 1))
    Chk 'admin-only: an inherit-only rule (children only) is not credited on the folder itself' ((Get-NonAdminWriteGrants -Rules @((& $row $U 'Allow' 0x1301BF $false $true)) -OwnerSid $A -Path 'C:\x').Count -eq 0)
    $tmpAcl = Join-Path ([IO.Path]::GetTempPath()) ('acl-' + [guid]::NewGuid().ToString('N')); New-Item -ItemType Directory -Path $tmpAcl | Out-Null
    try {
        $realAcl = Test-AdminOnlyFolder -Path $tmpAcl
        Chk 'admin-only (real ACL read, no change): the user''s own temp folder is NOT admin-only, and a missing folder is refused too' (($realAcl.Ok -eq $false) -and ($realAcl.Problems.Count -ge 1) -and ((Test-AdminOnlyFolder -Path (Join-Path $tmpAcl 'nope')).Ok -eq $false))
    } finally { Remove-Item -LiteralPath $tmpAcl -Recurse -Force -ErrorAction SilentlyContinue }
    Write-Host '== admin-only folder check against fabricated security descriptors and attributes ==' -ForegroundColor Cyan
    $aclRoot = Join-Path ([IO.Path]::GetTempPath()) ('aclfake-' + [guid]::NewGuid().ToString('N')); $aclTarget = Join-Path $aclRoot 'scripts'
    New-Item -ItemType Directory -Path $aclTarget | Out-Null; [IO.File]::WriteAllText((Join-Path $aclTarget 'a.ps1'), '# a')
    try {
        $opSid = 'S-1-5-21-1-2-3-1001'
        $adminSddl = 'O:BAG:SYD:P(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)(A;OICI;0x1200a9;;;BU)'
        $mkSd = { param($sddl, $isDir) $s = $(if ($isDir) { New-Object Security.AccessControl.DirectorySecurity } else { New-Object Security.AccessControl.FileSecurity }); $s.SetSecurityDescriptorSddlForm($sddl); $s }
        $runAcl = {
            param([hashtable]$map, [hashtable]$attrs = @{})
            $adminL = $adminSddl; $mkL = $mkSd   # GetNewClosure captures this scriptblock's own variables, not its caller's
            $provider = { param($p) $k = $p.TrimEnd('\'); $sd = $(if ($map.ContainsKey($k)) { $map[$k] } else { $adminL }); & $mkL $sd (Test-Path -LiteralPath $p -PathType Container) }.GetNewClosure()
            $attrP = { param($p) $k = $p.TrimEnd('\'); if ($attrs.ContainsKey($k)) { $attrs[$k] } else { [IO.FileAttributes]::Directory } }.GetNewClosure()
            Test-AdminOnlyFolder -Path $aclTarget -SecurityProvider $provider -AttributeProvider $attrP
        }
        Chk 'fake ACL: everything admin-only (Users read-and-execute) -> Ok' ((& $runAcl @{}).Ok -eq $true)
        Chk 'fake ACL: the folder grants Users modify -> refused' ((& $runAcl @{ $aclTarget = 'O:BAG:SYD:P(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)(A;OICI;0x1301bf;;;BU)' }).Ok -eq $false)
        Chk 'fake ACL: the folder is OWNED by a non-administrator (owner has WRITE_DAC) -> refused' ((& $runAcl @{ $aclTarget = "O:${opSid}G:SYD:P(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)(A;OICI;0x1200a9;;;BU)" }).Ok -eq $false)
        Chk 'fake ACL: a PARENT owned by a non-administrator, otherwise admin-only -> refused' ((& $runAcl @{ $aclRoot = "O:${opSid}G:SYD:P(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)(A;OICI;0x1200a9;;;BU)" }).Ok -eq $false)
        Chk 'fake ACL: a PARENT granting Users DELETE (rename-away of the parent), or DELETE plus add-subfolder -> refused' (((& $runAcl @{ $aclRoot = 'O:BAG:SYD:P(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)(A;;0x1301a9;;;BU)' }).Ok -eq $false) -and ((& $runAcl @{ $aclRoot = 'O:BAG:SYD:P(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)(A;;0x1301ad;;;BU)' }).Ok -eq $false))
        Chk 'fake ACL: a PARENT granting Users only create-files and add-subfolder (as ProgramData does) -> still Ok' ((& $runAcl @{ $aclRoot = 'O:BAG:SYD:P(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)(A;;0x100006;;;BU)' }).Ok -eq $true)
        Chk 'fake ACL: Authenticated Users WRITE_EA only on the folder, or Everyone DELETE only -> refused' (((& $runAcl @{ $aclTarget = 'O:BAG:SYD:P(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)(A;;0x120089;;;AU)(A;OICI;0x10;;;AU)' }).Ok -eq $false) -and ((& $runAcl @{ $aclTarget = 'O:BAG:SYD:P(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)(A;;0x10000;;;WD)' }).Ok -eq $false))
        Chk 'fake ACL: a file in the folder owned by a non-administrator, or OWNER RIGHTS with write on the folder -> refused' (((& $runAcl @{ (Join-Path $aclTarget 'a.ps1') = "O:${opSid}G:SYD:P(A;;FA;;;SY)(A;;FA;;;BA)" }).Ok -eq $false) -and ((& $runAcl @{ $aclTarget = 'O:BAG:SYD:P(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)(A;OICI;0x1301bf;;;S-1-3-4)' }).Ok -eq $false))
        Chk 'fake ACL: a creator-owner inherit-only rule is ignored, but Users add-file on the folder itself is refused' (((& $runAcl @{ $aclTarget = 'O:BAG:SYD:P(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)(A;OICIIO;FA;;;CO)' }).Ok -eq $true) -and ((& $runAcl @{ $aclTarget = 'O:BAG:SYD:P(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)(A;OICIIO;FA;;;CO)(A;;0x100002;;;BU)' }).Ok -eq $false))
        $rp = [int][IO.FileAttributes]::ReparsePoint -bor [int][IO.FileAttributes]::Directory
        Chk 'reparse points: the target folder, a parent, or a file inside being a link -> refused' (((& $runAcl @{} @{ $aclTarget = [IO.FileAttributes]$rp }).Ok -eq $false) -and ((& $runAcl @{} @{ $aclRoot = [IO.FileAttributes]$rp }).Ok -eq $false) -and ((& $runAcl @{} @{ (Join-Path $aclTarget 'a.ps1') = [IO.FileAttributes]$rp }).Ok -eq $false))
    } finally { Remove-Item -LiteralPath $aclRoot -Recurse -Force -ErrorAction SilentlyContinue }
    Write-Host '== elevated writes: no junction, symlink or hard-link redirect; the proof is trusted only from an admin-only place ==' -ForegroundColor Cyan
    $wt = Join-Path ([IO.Path]::GetTempPath()) ('plainout-' + [guid]::NewGuid().ToString('N')); New-Item -ItemType Directory -Path $wt | Out-Null
    try {
        $plainOk = $true; try { Assert-PlainOutputPath -Path (Join-Path $wt 'r.json') } catch { $plainOk = $false }
        $jd = Join-Path $wt 'jdir'; $tg = Join-Path $wt 'target'; New-Item -ItemType Directory -Path $tg | Out-Null
        $madeJ = $true; try { New-Item -ItemType Junction -Path $jd -Target $tg | Out-Null } catch { $madeJ = $false }
        $viaJunction = $false; if ($madeJ) { try { Assert-PlainOutputPath -Path (Join-Path $jd 'r.json') } catch { $viaJunction = $true } }
        $victim = Join-Path $wt 'victim.txt'; [IO.File]::WriteAllText($victim, 'keep'); $hl = Join-Path $wt 'hard.json'
        $madeH = $true; try { New-Item -ItemType HardLink -Path $hl -Target $victim | Out-Null } catch { $madeH = $false }
        $viaHard = $false; if ($madeH) { try { Assert-PlainOutputPath -Path $hl } catch { $viaHard = $true } }
        Chk 'output path guard: an ordinary path passes; a path through a directory junction is refused; an existing hard-linked file is refused' ($plainOk -and ((-not $madeJ) -or $viaJunction) -and ((-not $madeH) -or $viaHard))
        if ($madeJ) {
            $guardedThrew = $false; try { Write-JsonGuarded -Path (Join-Path $jd 'rec.json') -Object ([ordered]@{ a = 1 }) } catch { $guardedThrew = $true }
            Chk 'Write-JsonGuarded refuses to write through the junction and nothing lands in the target' ($guardedThrew -and -not (Test-Path (Join-Path $tg 'rec.json')))
            [IO.Directory]::Delete($jd, $false)
        }
        Write-JsonGuarded -Path (Join-Path $wt 'ok.json') -Object ([ordered]@{ a = 1 })
        Chk 'Write-JsonGuarded writes an ordinary path' ((Get-Content -LiteralPath (Join-Path $wt 'ok.json') -Raw) -match '"a":\s*1')
        $okChecker = { param($p) [ordered]@{ Ok = $true; Problems = @() } }; $badChecker = { param($p) [ordered]@{ Ok = $false; Problems = @('S-1-5-32-545 is allowed rights 0x2') } }
        Chk 'proof location: a proof in an admin-only folder is accepted; a proof in a non-admin folder is refused EVEN when it sits beside the scripts (attended runs included)' ((@(Test-ProofLocation -ProofPath (Join-Path $PSScriptRoot 'p.json') -ScriptFolder $PSScriptRoot -Checker $okChecker)).Count -eq 0 -and (@(Test-ProofLocation -ProofPath (Join-Path $PSScriptRoot 'p.json') -ScriptFolder $PSScriptRoot -Checker $badChecker)).Count -ge 1 -and (@(Test-ProofLocation -ProofPath (Join-Path $wt 'p.json') -ScriptFolder $PSScriptRoot -Checker $badChecker)).Count -ge 1)
    } finally { Remove-Item -LiteralPath $wt -Recurse -Force -ErrorAction SilentlyContinue }
    Write-Host '== arguments, verdicts, definitions ==' -ForegroundColor Cyan
    Chk 'args: no mode and two modes are errors; each single mode is valid' (((Test-PersistArgs $false $false $false $false $false $false '' 20 15).Count -ge 1) -and ((Test-PersistArgs $false $false $true $true $false $false '' 20 15).Count -ge 1) -and ((Test-PersistArgs $true $false $false $false $false $false '' 20 15).Count -eq 0) -and ((Test-PersistArgs $false $false $true $false $false $false '' 20 15).Count -eq 0) -and ((Test-PersistArgs $false $false $false $true $false $false '' 20 15).Count -eq 0) -and ((Test-PersistArgs $false $false $false $false $true $false '' 20 15).Count -eq 0) -and ((Test-PersistArgs $false $false $false $false $false $true '' 20 15).Count -eq 0))
    Chk 'args: there is no standalone -Add mode (the add paths are -Arm3a and the 3b arming script only)' ((Get-Command $PSCommandPath).Parameters.Keys -notcontains 'Add')
    Chk 'args: -WriteProof only with -SelfTest; -RemoveTaskName only with -Remove and only a plain blarai- name' (((Test-PersistArgs $false $true $true $false $false $false '' 20 15).Count -ge 1) -and ((Test-PersistArgs $false $false $false $false $false $true 'blarai-x1' 20 15).Count -ge 1) -and ((Test-PersistArgs $false $false $false $false $true $false 'blarai-arm3a-deadman' 20 15).Count -eq 0) -and ((Test-PersistArgs $false $false $false $false $true $false 'x;calc' 20 15).Count -ge 1))
    Chk 'args: dwell 4 / 121 and dead-man 4 / 121 minutes are rejected' (((Test-PersistArgs $false $false $false $false $false $true '' 4 15).Count -ge 1) -and ((Test-PersistArgs $false $false $false $false $false $true '' 121 15).Count -ge 1) -and ((Test-PersistArgs $false $false $false $false $false $true '' 20 4).Count -ge 1) -and ((Test-PersistArgs $false $false $false $false $false $true '' 20 121).Count -ge 1))
    Chk '-Check exit codes: PRESENT 0, ABSENT 20, PARTIAL 21, UNKNOWN 22, anything else 22' (((Get-CheckExitCode 'PRESENT') -eq 0) -and ((Get-CheckExitCode 'ABSENT') -eq 20) -and ((Get-CheckExitCode 'PARTIAL') -eq 21) -and ((Get-CheckExitCode 'UNKNOWN') -eq 22) -and ((Get-CheckExitCode 'weird') -eq 22))
    $goodA = @{ OperatorAbort = $false; RemovalVerified = $true; BaselineOk = $true; AddOk = $true; PresentAfterAdd = $true; AllPersistent = $true; BlockRunValid = $true; ProbeBlocked = $true; GuardRefusedBeforeAdd = $true; GuardRefusedAfterRemoval = $true }
    function VA($over) { $o = $goodA.Clone(); foreach ($k in $over.Keys) { $o[$k] = $over[$k] }; (Get-Arm3aVerdict ([pscustomobject]$o)).Code }
    Chk 'A: all good -> 0' ((VA @{}) -eq 0)
    Chk 'A: operator abort -> 3 (beats everything)' ((VA @{ OperatorAbort = $true; RemovalVerified = $false; BaselineOk = $false }) -eq 3)
    Chk 'A: removal unverified -> 7 (beats "not blocked")' ((VA @{ RemovalVerified = $false; ProbeBlocked = $false }) -eq 7)
    Chk 'A: no baseline -> 5' ((VA @{ BaselineOk = $false }) -eq 5)
    Chk 'A: add failed -> 4; not PRESENT or not persistent after the add -> 4' (((VA @{ AddOk = $false }) -eq 4) -and ((VA @{ PresentAfterAdd = $false }) -eq 4) -and ((VA @{ AllPersistent = $false }) -eq 4))
    Chk 'A: block run invalid or refused by the gate -> 4' ((VA @{ BlockRunValid = $false; ProbeBlocked = $false }) -eq 4)
    Chk 'A: account not blocked with the fence present -> 1' ((VA @{ ProbeBlocked = $false }) -eq 1)
    Chk 'A: the gate did not refuse before the add, or after the removal -> 6, never 0' (((VA @{ GuardRefusedBeforeAdd = $false }) -eq 6) -and ((VA @{ GuardRefusedAfterRemoval = $false }) -eq 6))
    $dm = Get-DeadManDefinition -Name 'blarai-arm3a-deadman' -ScriptPath 'C:\x\spike-wfp-persist.ps1' -State 'C:\s' -Wfp 'C:\w\w.ps1' -Minutes 15 -Now ([datetime]'2026-10-11T12:00:00')
    Chk 'dead-man: SYSTEM, Highest, fires 15 minutes later, runs -Remove with the baked paths and unregisters its own name' (($dm.User -eq 'NT AUTHORITY\SYSTEM') -and ($dm.RunLevel -eq 'Highest') -and ($dm.TriggerAt -eq [datetime]'2026-10-11T12:15:00') -and ($dm.Arguments -match ' -Remove ') -and ($dm.Arguments -match '-StateDir "C:\\s"') -and ($dm.Arguments -match '-RemoveTaskName blarai-arm3a-deadman$'))
    Chk 'dead-man: its arguments never contain -Arm3a (it can only remove)' ($dm.Arguments -notmatch '\s-Arm3a(\s|$)')
    $dmp = Get-DeadManDefinition -Name 'blarai-arm3a-deadman' -ScriptPath 'C:\x\spike-wfp-persist.ps1' -State 'C:\s' -Wfp 'C:\w\w.ps1' -Minutes 15 -Now ([datetime]'2026-10-11T12:00:00') -WfpHash ('AB' * 32)
    Chk 'dead-man: carries the hash of the wrapped script it must find unchanged (-WfpSha256), so a swapped file is refused before it becomes code' ($dmp.Arguments -match ('-WfpSha256 ' + ('AB' * 32) + '$'))
    Chk 'dead-man: carries the code-set id taken when it was registered (-CodeSetId)' ((Get-DeadManDefinition -Name 'blarai-arm3a-deadman' -ScriptPath 'C:\x\spike-wfp-persist.ps1' -State 'C:\s' -Wfp 'C:\w\w.ps1' -Minutes 15 -Now ([datetime]'2026-10-11T12:00:00') -WfpHash ('AB' * 32) -CodeSetId ('EF' * 32)).Arguments -match ('-CodeSetId ' + ('EF' * 32) + '$'))
    $cmdInfo = Get-Command $PSCommandPath
    Chk 'dead-man is OPT-IN: the switch is -DeadManTask (default off) and there is no -NoDeadManTask' (($cmdInfo.Parameters.Keys -contains 'DeadManTask') -and ($cmdInfo.Parameters.Keys -notcontains 'NoDeadManTask') -and ($cmdInfo.Parameters['DeadManTask'].SwitchParameter))
    Chk 'probe outcome (driver): blocked / open / no_result / wrong_sid' (((Get-ProbeOutcome -Run ([pscustomobject]@{ valid = $true; token_sid = $sid; outbound_probe = [pscustomobject]@{ probe = [pscustomobject]@{ connected = $false } } }) -Sid $sid) -eq 'blocked') -and ((Get-ProbeOutcome -Run ([pscustomobject]@{ valid = $true; token_sid = $sid; outbound_probe = [pscustomobject]@{ probe = [pscustomobject]@{ connected = $true } } }) -Sid $sid) -eq 'open') -and ((Get-ProbeOutcome -Run $null -Sid $sid) -eq 'no_result') -and ((Get-ProbeOutcome -Run ([pscustomobject]@{ valid = $true; token_sid = $other; outbound_probe = [pscustomobject]@{ probe = [pscustomobject]@{ connected = $false } } }) -Sid $sid) -eq 'wrong_sid'))
    $w = New-WatchdogState
    Chk 'watchdog: fail, ok, fail never aborts; two consecutive failures abort' ((-not (Update-WatchdogState -State $w -Ok $false)) -and (-not (Update-WatchdogState -State $w -Ok $true)) -and (-not (Update-WatchdogState -State $w -Ok $false)) -and (Update-WatchdogState -State $w -Ok $false))
    Chk 'export summary: both filter keys and the marker -> ok; one key missing -> not ok; marker missing -> not ok' (((Get-FilterExportSummary -Text '<f>{F1300003-0000-4D8E-9A31-2B6D4C8E3F21} {F1300004-0000-4D8E-9A31-2B6D4C8E3F22} BlarAI #1682 persist</f>' -Marker 'BlarAI #1682' -ExpectedKeys $script:PersistFilterKeys).ok) -and (-not (Get-FilterExportSummary -Text '<f>{F1300003-0000-4D8E-9A31-2B6D4C8E3F21} BlarAI #1682</f>' -Marker 'BlarAI #1682' -ExpectedKeys $script:PersistFilterKeys).ok) -and (-not (Get-FilterExportSummary -Text '<f>{F1300003-0000-4D8E-9A31-2B6D4C8E3F21} {F1300004-0000-4D8E-9A31-2B6D4C8E3F22}</f>' -Marker 'BlarAI #1682' -ExpectedKeys $script:PersistFilterKeys).ok))

    $passedTags = @($script:tagsPassed | Select-Object -Unique | Where-Object { $script:tagsFailed -notcontains $_ })
    if ($WriteProof) {
        Write-Host '== -WriteProof: the self-test of every sibling script, then the proof ==' -ForegroundColor Cyan
        $hostExe = (Get-Process -Id $PID).Path
        $siblings = @(@{ n = 'spike-arm3b-arm.ps1'; wfp = $true }, @{ n = 'spike-arm3b-post-reboot.ps1'; wfp = $true }, @{ n = 'spike-arm3b-veto.ps1'; wfp = $true }, @{ n = 'Start-ElevatedOnce.ps1'; wfp = $false })
        $sibResults = @()
        foreach ($s in $siblings) {
            $argv = @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', (Join-Path $PSScriptRoot $s.n), '-SelfTest'); if ($s.wfp) { $argv += @('-WfpScript', $WfpScript) }
            $out = (& $hostExe @argv 2>&1 | Out-String); $rc = $LASTEXITCODE
            $passN = [regex]::Matches($out, '\[PASS\]').Count
            $sibPassed = (($rc -eq 0) -and ($out -notmatch '\[FAIL\]') -and ($out -match 'all passed'))
            $sibResults += [ordered]@{ name = $s.n; passed = $sibPassed; checks = $passN }
            Chk "sibling self-test passes: $($s.n)" $sibPassed
        }
        if ($script:f -eq 0 -and @($script:RequiredRollbackTags | Where-Object { $passedTags -contains $_ }).Count -eq $script:RequiredRollbackTags.Count) {
            $hashes = Get-CodeSetHashes -Folder $PSScriptRoot
            if ($hashes.Missing.Count) { Write-Host "NO PROOF WRITTEN: code-set file(s) missing: $($hashes.Missing -join ', ')" -ForegroundColor Red; $script:f++ }
            elseif ($impReal.Sha256 -ne $imp.Sha256) { Write-Host 'NO PROOF WRITTEN: the wrapped script changed between the self-test reads' -ForegroundColor Red; $script:f++ }
            else {
                $obj = New-RollbackProofObject -Hashes $hashes.Hashes -PassedTags $passedTags -FailedChecks @() -HostInfo ("$($Host.Name) $($PSVersionTable.PSVersion) $($PSVersionTable.PSEdition) on $([Environment]::OSVersion.Version)") -When ((Get-Date).ToString('o')) -WrappedHash $imp.Sha256 -ChecksRun $script:chkTotal -ChecksPassed ($script:chkTotal - $script:f) -Siblings $sibResults
                New-Item -ItemType Directory -Force (Split-Path $ProofPath -Parent) | Out-Null
                Write-JsonGuarded -Path $ProofPath -Object $obj -Depth 8
                Write-Host "PROOF WRITTEN: $ProofPath ($($hashes.Hashes.Count) files hashed, the wrapped script hashed, $script:chkTotal checks run, $($passedTags.Count) rollback tags)" -ForegroundColor Green
            }
        } else { Write-Host 'NO PROOF WRITTEN: the self-test did not fully pass.' -ForegroundColor Red }
    }
    Write-Host ("persist selftest: {0}" -f $(if ($script:f -eq 0) { 'all passed' } else { "$($script:f) FAILED" })) -ForegroundColor $(if ($script:f -eq 0) { 'Green' } else { 'Red' })
    return $(if ($script:f -eq 0) { 0 } else { 1 })
}

# ---- entry ----------------------------------------------------------------------------------------------------------------
$argErrors = Test-PersistArgs $SelfTest.IsPresent $WriteProof.IsPresent $DryRun.IsPresent $Check.IsPresent $Remove.IsPresent $Arm3a.IsPresent $RemoveTaskName $DwellSeconds $DeadManMinutes
if ($argErrors.Count) { $argErrors | ForEach-Object { Write-Host "ARG ERROR: $_" -ForegroundColor Red }; exit 2 }
try {
    if ($SelfTest) { exit (Invoke-SelfTest) }
    if ($DryRun)   { exit (Invoke-DryRun) }
    if ($Check)    { exit (Invoke-Check) }
    if ($Remove)   { exit (Invoke-Remove) }
    if ($Arm3a)    { exit (Invoke-Arm3a) }
} catch {
    Write-Host "STOPPED: $($_.Exception.Message)" -ForegroundColor Red
    Write-Host $_.ScriptStackTrace -ForegroundColor DarkGray
    exit 2
}
