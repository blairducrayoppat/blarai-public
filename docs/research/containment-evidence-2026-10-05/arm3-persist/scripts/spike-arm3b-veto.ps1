#requires -Version 5.1
<#
.SYNOPSIS
  Arm 3b veto watchdog: a one-shot SYSTEM task (blarai-arm3b-veto) the arming script registers to fire VetoMinutes after arming.
  If the machine has NOT restarted by then it cancels any pending restart (`shutdown /a`), removes the persistent set by key,
  deletes the startup task and records "reboot vetoed". Registered by the 2026-10-12 run (inferred from the armed record); its own action (cancel and remove) was not exercised.

.DESCRIPTION
  Modes (exactly one):
    -SelfTest  the decision table and the whole veto flow against fakes (no restart happened; a restart happened and the
               post-reboot task already cleaned up; a restart happened and the post-reboot task is still running; a restart
               happened and a set is left with no task to remove it; the arm state unreadable; a removal that fails). No WFP call.
    -DryRun    prints what -Live would do. Changes nothing.
    -Live      (SYSTEM) read the arm state and the boot time and decide:
                 not restarted since arming      -> shutdown /a, remove the set by key, delete the startup and wrapper tasks,
                                                    record "reboot vetoed"
                 restarted, post-reboot running   -> touch nothing (it is doing the removal)
                 restarted, set already gone      -> nothing to do
                 restarted, set left, no post-reboot task running -> remove it by key (safety net)
                 arm state unreadable             -> treated as "not restarted": the set is removed (the safe direction)
               and then delete itself. The record is arm3b-veto-result.json.

  The wrapped script is pinned (-WfpSha256, taken at arming). If it cannot be used the decision still runs (it needs only the arm state, the boot time and the task
  state) and the removal goes through the self-contained snippet.
  FOLDER RULE. Everything a SYSTEM or elevated task runs comes from the folder these scripts sit in. If a non-administrator process can write to that folder
  (or replace it), it can run code elevated. These scripts therefore refuse to register a SYSTEM task, and the elevated wrapper refuses to register or run,
  unless only SYSTEM, Administrators and TrustedInstaller can write to the folder and to every file in it (Test-AdminOnlyFolder). Keep them under an
  administrator-only folder such as C:\ProgramData\BlarAI; the rollback proof is written beside them for the same reason.

  EXIT CODES   0 done (including "nothing to do")    7 the set could not be removed and verified: spike-wfp-persist.ps1 -Remove, then the README's manual rollback
#>
[CmdletBinding()]
param(
    [switch]$SelfTest,
    [switch]$DryRun,
    [switch]$Live,
    [string]$TaskName = 'blarai-arm3b-post-reboot',
    [string]$VetoTaskName = 'blarai-arm3b-veto',
    [string]$WrapperTaskName = 'blarai-arm3b-arm-run',
    [string]$WfpSha256,
    [string]$CodeSetId,
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

function Test-VetoArgs {
    param([bool]$SelfTest, [bool]$DryRun, [bool]$Live)
    if (@(@($SelfTest, $DryRun, $Live) | Where-Object { $_ }).Count -ne 1) { return @('choose exactly one of -SelfTest, -DryRun, -Live') }
    return @()
}

function Get-VetoDecision {
    # PURE. Returns the action: veto | leave_running | nothing_to_do | safety_net_remove.
    param($Armed, [datetimeoffset]$BootTime, [string]$PostTaskState, [string]$FenceState)
    $rebooted = $false
    if ($Armed -and $Armed.armed_at) { try { $rebooted = ($BootTime -gt (ConvertTo-DateTimeOffset $Armed.armed_at)) } catch { $rebooted = $false } }
    if (-not $rebooted) { return [pscustomobject]@{ Action = 'veto'; Rebooted = $false; Reason = $(if ($Armed) { 'the machine has not restarted since arming' } else { 'the arm state is unreadable: treated as not restarted (removing is the safe direction)' }) } }
    if ($PostTaskState -eq 'Running') { return [pscustomobject]@{ Action = 'leave_running'; Rebooted = $true; Reason = 'restarted, and the post-reboot task is running: it is doing the removal' } }
    if ($FenceState -eq 'ABSENT') { return [pscustomobject]@{ Action = 'nothing_to_do'; Rebooted = $true; Reason = 'restarted, and the set is already gone' } }
    return [pscustomobject]@{ Action = 'safety_net_remove'; Rebooted = $true; Reason = "restarted, but the set is $FenceState and no post-reboot task is running: removing it by key" }
}

function Invoke-VetoCore {
    # $W: Backend, ReadArmed(), BootTime(), TaskState(name), AbortShutdown(), UnregisterTask(name), Now(), WriteResult(obj)
    param([Parameter(Mandatory)]$W, [Parameter(Mandatory)]$Cfg)
    $r = [ordered]@{ kind = 'arm3b-veto'; started = (& $W.Now); steps = [ordered]@{} }
    $armed = & $W.ReadArmed
    $boot = [datetimeoffset]::Parse([string](& $W.BootTime))
    $post = & $W.TaskState $Cfg.TaskName
    $fence = Get-FenceState -Backend $W.Backend
    $d = Get-VetoDecision -Armed $armed -BootTime $boot -PostTaskState $post -FenceState $fence.State
    $r.steps.inputs = [ordered]@{ armed = $armed; boot_time = $boot.ToString('o'); post_reboot_task_state = $post; fence_state = $fence }
    $r.steps.decision = $d
    $ok = $true
    switch ($d.Action) {
        'veto' {
            $r.steps.shutdown_abort = [int](& $W.AbortShutdown)
            $rm = Remove-FenceSet -Backend $W.Backend; $r.steps.removal = $rm; $ok = [bool]$rm.Ok
            if ($ok) { $r.steps.post_task = & $W.UnregisterTask $Cfg.TaskName; $r.steps.wrapper_task = & $W.UnregisterTask $Cfg.WrapperTaskName }
            else { $r.steps.post_task = 'kept (removal not verified): it still removes the set if a restart happens' }
            $r.outcome = $(if ($ok) { 'reboot vetoed' } else { 'reboot vetoed, but the removal was NOT verified' })
        }
        'safety_net_remove' {
            $rm = Remove-FenceSet -Backend $W.Backend; $r.steps.removal = $rm; $ok = [bool]$rm.Ok
            if ($ok) { $r.steps.post_task = & $W.UnregisterTask $Cfg.TaskName; $r.steps.wrapper_task = & $W.UnregisterTask $Cfg.WrapperTaskName }
            $r.outcome = $(if ($ok) { 'set removed by the safety net' } else { 'safety net: the removal was NOT verified' })
        }
        'leave_running' { $r.outcome = 'left alone: the post-reboot task is running' }
        default { $r.outcome = 'nothing to do' }
    }
    $r.exit_code = $(if ($ok) { 0 } else { 7 }); $r.finished = (& $W.Now)
    & $W.WriteResult $r
    $r.steps.self = & $W.UnregisterTask $Cfg.VetoTaskName      # last act; the record above is already on disk
    return $r
}

function Invoke-ManualVeto {
    # Used when the wrapped script cannot be used (missing, changed, unparseable): the decision needs only the arm state, the boot time and the
    # task state; the removal goes through the self-contained snippet, whose statuses are the evidence (it cannot read the state back).
    param([string]$Why)
    $armed = Read-ArmedState -OutDir $OutDir
    $boot = Get-BootTime
    $d = Get-VetoDecision -Armed $armed -BootTime $boot -PostTaskState (Get-TaskStateOrNull -Name $TaskName) -FenceState 'UNKNOWN'
    $rec = [ordered]@{ kind = 'arm3b-veto'; started = (Get-Date).ToString("yyyy-MM-dd'T'HH:mm:ss.fffzzz"); fallback = $true; reason_for_fallback = $Why; decision = $d; exit_code = 0; outcome = $null }
    if ($d.Action -in @('veto', 'safety_net_remove')) {
        if ($d.Action -eq 'veto') { & "$env:SystemRoot\System32\shutdown.exe" /a 2>&1 | Out-Null; $rec.shutdown_abort = $LASTEXITCODE }
        $mr = Invoke-ManualRollback; $rec.manual_rollback = $mr
        if ($mr.Ok) { $rec.post_task = Unregister-TaskIfPresent -Name $TaskName; $rec.wrapper_task = Unregister-TaskIfPresent -Name $WrapperTaskName; $rec.outcome = 'removed by the self-contained rollback (wrapped script unusable)' }
        else { $rec.exit_code = 7; $rec.outcome = "removal NOT verified: $($mr.Reason)" }
    } else { $rec.outcome = "left alone: $($d.Reason)" }
    try { New-Item -ItemType Directory -Force $OutDir | Out-Null; Write-JsonGuarded -Path (Join-Path $OutDir 'arm3b-veto-result.json') -Object $rec -Depth 8 } catch {}
    $rec.self = Unregister-TaskIfPresent -Name $VetoTaskName
    Write-Host "veto (fallback): $($rec.outcome)" -ForegroundColor $(if ($rec.exit_code -eq 0) { 'Yellow' } else { 'Red' })
    return [int]$rec.exit_code
}

function Invoke-Live {
    $initErr = $null
    if ($CodeSetId) { $csChk = Test-CodeSetId -Folder $PSScriptRoot -Expected $CodeSetId; if (-not $csChk.Ok) { $initErr = "code set check failed: $($csChk.Reason)" } }
    if (-not $initErr) { try { $null = Import-WfpHelpers -Path $WfpScript -ExpectedSha256 $WfpSha256; Initialize-PersistType } catch { $initErr = $_.Exception.Message } }
    if ($initErr) { return (Invoke-ManualVeto -Why $initErr) }
    $be = $null
    try { $be = New-RealBackend } catch {
        $rec = [ordered]@{ kind = 'arm3b-veto'; started = (Get-Date).ToString("yyyy-MM-dd'T'HH:mm:ss.fffzzz"); error = "the WFP engine could not be opened: $($_.Exception.Message)"; outcome = 'veto NOT done: the set was not removed'; exit_code = 7 }
        try { New-Item -ItemType Directory -Force $OutDir | Out-Null; Write-JsonGuarded -Path (Join-Path $OutDir 'arm3b-veto-result.json') -Object $rec -Depth 6 } catch {}
        Write-Host $rec.error -ForegroundColor Red
        return 7
    }
    try {
        $W = @{ Backend = $be }
        $W.Now = { (Get-Date).ToString("yyyy-MM-dd'T'HH:mm:ss.fffzzz") }
        $W.ReadArmed = { Read-ArmedState -OutDir $OutDir }
        $W.BootTime = { (Get-BootTime).ToString('o') }
        $W.TaskState = { param($n) Get-TaskStateOrNull -Name $n }
        $W.AbortShutdown = { & "$env:SystemRoot\System32\shutdown.exe" /a 2>&1 | Out-Null; $LASTEXITCODE }
        $W.UnregisterTask = { param($n) Unregister-TaskIfPresent -Name $n }
        $W.WriteResult = { param($o) New-Item -ItemType Directory -Force $OutDir | Out-Null; Write-JsonGuarded -Path (Join-Path $OutDir 'arm3b-veto-result.json') -Object $o -Depth 12 }
        $cfg = [pscustomobject]@{ TaskName = $TaskName; VetoTaskName = $VetoTaskName; WrapperTaskName = $WrapperTaskName }
        $r = Invoke-VetoCore -W $W -Cfg $cfg
    } finally { $be.Close() }
    Write-Host ("veto: {0} (exit {1})" -f $r.outcome, $r.exit_code)
    return [int]$r.exit_code
}

function Invoke-DryRun {
    Write-Host '== DRY RUN: nothing is read from the engine, removed or deleted ==' -ForegroundColor Yellow
    @('read arm3b-armed.json and the boot time', 'not restarted since arming  -> shutdown /a; remove the set BY KEY; delete the startup task and the wrapper task; write arm3b-veto-result.json ("reboot vetoed")',
      'restarted, post-reboot task running -> leave everything alone', 'restarted, set already gone -> nothing to do', 'restarted, set left and no post-reboot task running -> remove it by key (safety net)', 'arm state unreadable -> treated as not restarted (the set is removed)',
      "then delete this task ($VetoTaskName)") | ForEach-Object { Write-Host "  - $_" }
    $armed = Read-ArmedState -OutDir $OutDir
    Write-Host $(if ($armed) { "arm state present: armed at $($armed.armed_at); veto fires at $($armed.veto_fires_at)" } else { "no arm state at $OutDir\arm3b-armed.json" })
    Write-Host 'DRY RUN complete.' -ForegroundColor Green
    return 0
}

function Invoke-SelfTest {
    $script:f = 0
    function Chk([string]$n, [bool]$c) { if ($c) { Write-Host "  [PASS] $n" -ForegroundColor Green } else { Write-Host "  [FAIL] $n" -ForegroundColor Red; $script:f++ } }
    $null = Import-WfpHelpers -Path $WfpScript -Unverified; Initialize-PersistType
    $sid = 'S-1-5-21-1111111111-2222222222-3333333333-1001'; $plan = [BlarAI.WfpPersist.PersistPlan]::Build($sid)
    $armedAt = [datetimeoffset]::Now.AddMinutes(-31)
    $armed = [pscustomobject]@{ armed_at = $armedAt.ToString('o') }
    Chk 'args: exactly one mode' (((Test-VetoArgs $false $false $false).Count -ge 1) -and ((Test-VetoArgs $true $true $false).Count -ge 1) -and ((Test-VetoArgs $false $false $true).Count -eq 0))
    Write-Host '== decision table ==' -ForegroundColor Cyan
    Chk 'no restart since arming -> veto' ((Get-VetoDecision -Armed $armed -BootTime $armedAt.AddDays(-3) -PostTaskState 'Ready' -FenceState 'PRESENT').Action -eq 'veto')
    Chk 'the arm state unreadable -> veto (the safe direction)' ((Get-VetoDecision -Armed $null -BootTime ([datetimeoffset]::Now) -PostTaskState $null -FenceState 'PRESENT').Action -eq 'veto')
    Chk 'restarted, post-reboot Running -> leave it alone' ((Get-VetoDecision -Armed $armed -BootTime $armedAt.AddMinutes(10) -PostTaskState 'Running' -FenceState 'PRESENT').Action -eq 'leave_running')
    Chk 'restarted, set ABSENT -> nothing to do' ((Get-VetoDecision -Armed $armed -BootTime $armedAt.AddMinutes(10) -PostTaskState $null -FenceState 'ABSENT').Action -eq 'nothing_to_do')
    Chk 'restarted, set PRESENT or PARTIAL or UNKNOWN, nothing running -> safety net removal' (((Get-VetoDecision -Armed $armed -BootTime $armedAt.AddMinutes(10) -PostTaskState 'Ready' -FenceState 'PRESENT').Action -eq 'safety_net_remove') -and ((Get-VetoDecision -Armed $armed -BootTime $armedAt.AddMinutes(10) -PostTaskState $null -FenceState 'PARTIAL').Action -eq 'safety_net_remove') -and ((Get-VetoDecision -Armed $armed -BootTime $armedAt.AddMinutes(10) -PostTaskState $null -FenceState 'UNKNOWN').Action -eq 'safety_net_remove'))
    Write-Host '== the veto flow against fakes ==' -ForegroundColor Cyan
    $cfg = [pscustomobject]@{ TaskName = 'blarai-arm3b-post-reboot'; VetoTaskName = 'blarai-arm3b-veto'; WrapperTaskName = 'blarai-arm3b-arm-run' }
    function New-VW($be, $boot, $postState, $armedObj) {
        $log = New-Object System.Collections.ArrayList
        $w = @{ Backend = $be; Log = $log }
        $w.Now = { (Get-Date).ToString("yyyy-MM-dd'T'HH:mm:ss.fffzzz") }
        $w.ReadArmed = { $armedObj }.GetNewClosure()
        $w.BootTime = { $boot.ToString('o') }.GetNewClosure()
        $w.TaskState = { param($n) $postState }.GetNewClosure()
        $w.AbortShutdown = { [void]$log.Add('shutdown /a'); 0 }.GetNewClosure()
        $w.UnregisterTask = { param($n) [void]$log.Add("unregister $n"); 'unregistered' }.GetNewClosure()
        $w.WriteResult = { param($o) [void]$log.Add('write result') }.GetNewClosure()
        $w
    }
    $b1 = New-FakeBackend; [void]$b1.AddAll($plan)
    $w1 = New-VW $b1 $armedAt.AddDays(-3) 'Ready' $armed
    $r1 = Invoke-VetoCore -W $w1 -Cfg $cfg
    Chk 'no restart: shutdown /a, the set removed by key (ABSENT), the post-reboot and wrapper tasks deleted, "reboot vetoed" recorded, exit 0' (($r1.exit_code -eq 0) -and ($r1.outcome -eq 'reboot vetoed') -and ($b1.Store.Count -eq 0) -and ($w1.Log -contains 'shutdown /a') -and ($w1.Log -contains 'unregister blarai-arm3b-post-reboot') -and ($w1.Log -contains 'unregister blarai-arm3b-arm-run'))
    Chk 'no restart: the shutdown is cancelled BEFORE the removal and the record is written BEFORE the veto task deletes itself (last)' (($w1.Log.IndexOf('shutdown /a') -eq 0) -and ($w1.Log.IndexOf('write result') -lt $w1.Log.IndexOf('unregister blarai-arm3b-veto')) -and ($w1.Log[$w1.Log.Count - 1] -eq 'unregister blarai-arm3b-veto'))
    $b2 = New-FakeBackend; [void]$b2.AddAll($plan)
    $w2 = New-VW $b2 $armedAt.AddMinutes(10) 'Running' $armed
    $r2 = Invoke-VetoCore -W $w2 -Cfg $cfg
    Chk 'restarted and post-reboot running: the set is NOT touched, no shutdown /a, only the veto task deletes itself' (($b2.Store.Count -eq 4) -and ($w2.Log -notcontains 'shutdown /a') -and ($r2.outcome -match 'left alone') -and ($r2.exit_code -eq 0))
    $b3 = New-FakeBackend
    $w3 = New-VW $b3 $armedAt.AddMinutes(10) $null $armed
    $r3 = Invoke-VetoCore -W $w3 -Cfg $cfg
    Chk 'restarted and the set already gone: nothing to do, exit 0' (($r3.outcome -eq 'nothing to do') -and ($r3.exit_code -eq 0))
    $b4 = New-FakeBackend; [void]$b4.AddAll($plan)
    $w4 = New-VW $b4 $armedAt.AddMinutes(10) $null $armed
    $r4 = Invoke-VetoCore -W $w4 -Cfg $cfg
    Chk 'restarted, a set left and nothing running: removed by the safety net' (($r4.outcome -eq 'set removed by the safety net') -and ($b4.Store.Count -eq 0) -and ($w4.Log -notcontains 'shutdown /a'))
    $b5 = New-FakeBackend; [void]$b5.AddAll($plan); $b5.FailDelete = @($script:PersistSubLayerKey)
    $w5 = New-VW $b5 $armedAt.AddDays(-3) 'Ready' $armed
    $r5 = Invoke-VetoCore -W $w5 -Cfg $cfg
    Chk 'a removal that fails: exit 7, recorded, and the post-reboot task is KEPT (it still removes the set if a restart happens)' (($r5.exit_code -eq 7) -and ($r5.outcome -match 'NOT verified') -and ($w5.Log -notcontains 'unregister blarai-arm3b-post-reboot') -and ($r5.steps.post_task -match 'kept'))
    $b6 = New-FakeBackend; [void]$b6.AddAll($plan)
    $w6 = New-VW $b6 ([datetimeoffset]::Now) 'Ready' $null
    $r6 = Invoke-VetoCore -W $w6 -Cfg $cfg
    Chk 'arm state unreadable: treated as not restarted - the set is removed' (($r6.outcome -eq 'reboot vetoed') -and ($b6.Store.Count -eq 0))
    Write-Host ("arm3b-veto selftest: {0}" -f $(if ($script:f -eq 0) { 'all passed' } else { "$($script:f) FAILED" })) -ForegroundColor $(if ($script:f -eq 0) { 'Green' } else { 'Red' })
    return $(if ($script:f -eq 0) { 0 } else { 1 })
}

$argErrors = Test-VetoArgs $SelfTest.IsPresent $DryRun.IsPresent $Live.IsPresent
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
