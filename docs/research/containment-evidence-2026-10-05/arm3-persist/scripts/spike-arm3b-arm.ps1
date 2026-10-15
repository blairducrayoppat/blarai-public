#requires -Version 5.1
<#
.SYNOPSIS
  Arm 3b arming script: adds the PERSISTENT filter set, registers the one-shot SYSTEM startup task and the veto watchdog, and
  schedules one restart, but ONLY after the machine has been idle and a visible countdown has run out untouched. It REFUSES
  (adds nothing) unless every precondition holds. Ran live once on 2026-10-12 (claims row C10): it is the attended-or-away step of arm 3b.

.DESCRIPTION
  Modes (exactly one):
    -SelfTest  pure only: the argument rules, the task definitions, the idle and countdown gates with fake clocks, and the whole
               arming flow driven against fakes (not idle, input during the countdown, a failed registration, a failed shutdown
               command, input while the restart is pending, a missing proof, a stale object, the happy path). No WFP call, no task,
               no shutdown, nothing changes.
    -DryRun    prints exactly what -Live would add and do, in order, with the real times computed from now; reads the idle time and
               the proof read-only; adds nothing, registers nothing, schedules nothing.
    -Live      the arming run. Must be elevated, in the operator's own session (an interactive task: it reads that session's input
               clock and shows the toast). Order:
                 proof (rollback self-test, same script hashes) and SID safety (exit 3) and preflight -> nothing already armed ->
                 IDLE GATE (no keyboard or mouse input for -IdleMinutes, default and minimum 30) -> account baseline and operator
                 control -> COUNTDOWN (toast + window for -CountdownMinutes, default 10; ANY input aborts) -> wsl --shutdown ->
                 register blarai-arm3b-post-reboot (SYSTEM, at startup) and blarai-arm3b-veto (SYSTEM, once, -VetoMinutes later) FIRST, so a
                 cleanup exists before anything persistent does -> arm state file -> ADD the persistent set -> export -> `shutdown /r /t 600 /c "arm 3b"`
                 (FORCED: /t above 0 implies /f on Windows, so applications are closed without forewarning when the timer ends) -> watch the
                 input clock until the restart; input before it = `shutdown /a`, remove by key, delete both tasks, exit 11.
               The veto watchdog is a separate task so it survives this process: if the machine has not restarted -VetoMinutes after
               arming it runs `shutdown /a`, removes the set by key, deletes the startup task and records "reboot vetoed".

  FOLDER RULE. Everything a SYSTEM or elevated task runs comes from the folder these scripts sit in. If a non-administrator process can write to that folder
  (or replace it), it can run code elevated. These scripts therefore refuse to register a SYSTEM task, and the elevated wrapper refuses to register or run,
  unless only SYSTEM, Administrators and TrustedInstaller can write to the folder and to every file in it (Test-AdminOnlyFolder). Keep them under an
  administrator-only folder such as C:\ProgramData\BlarAI; the rollback proof is written beside them for the same reason.

  THE RESTART IS FORCED. The arguments carry no /f, but shutdown /? says a timeout above 0 implies /f. The idle gate and the input watch are the only
  protection for unsaved work; running this needs the Lead Architect's explicit acceptance of a forced restart.

  EXIT CODES
    0 never returned by -Live (the restart ends this process); -SelfTest: all passed; -DryRun: ok
    2 precondition / refusal (no proof, not elevated, preflight, something already armed, stale objects): nothing was added
    3 unsafe target (the SID is the operator's or one of his groups): nothing was added
    4 failed after the add and rolled back (registration, shutdown command or add failure; removal verified) - or inconclusive
    5 no baseline (operator offline, or the account's baseline run invalid / egress already blocked): nothing was added
    7 rollback NOT verified: run spike-wfp-persist.ps1 -Remove, then the README's manual rollback
    10 refused by the idle gate or because no visible warning could be raised: nothing was added
    11 aborted by keyboard or mouse input (countdown, or while the restart was pending); rolled back; nothing left
    12 armed, but the restart has not started when the watch ended: the veto watchdog will roll back at its time
#>
[CmdletBinding()]
param(
    [switch]$SelfTest,
    [switch]$DryRun,
    [switch]$Live,
    [int]$IdleMinutes = 30,
    [int]$CountdownMinutes = 10,
    [int]$ShutdownDelaySeconds = 600,
    [int]$VetoMinutes = 30,
    [switch]$NoWindow,
    [string]$WfpScript,
    [string]$OutDir = 'C:\Users\_OPERATOR_\blarai-research-data\arm3-persist',
    [string]$CountdownScript = 'C:\Users\_OPERATOR_\BlarAI\tools\probes\containment_arms\countdown_gate.ps1',
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
. (Get-VerifiedLibBlock 'spike-arm3b-common.ps1')
. (Get-VerifiedLibBlock 'arm3-idle-gate.ps1')
# The proof lives beside the scripts it vouches for, in the admin-only folder: a proof anyone can write is not a proof.
if (-not $ProofPath) { $ProofPath = Join-Path $PSScriptRoot 'rollback-selftest-proof.json' }

function Test-ArmArgs {
    # PURE. The 30-minute idle rule and the 10-minute countdown are floors, not defaults to lower for convenience.
    param([bool]$SelfTest, [bool]$DryRun, [bool]$Live, [int]$Idle, [int]$Countdown, [int]$Delay, [int]$Veto)
    $e = New-Object System.Collections.ArrayList
    if (@(@($SelfTest, $DryRun, $Live) | Where-Object { $_ }).Count -ne 1) { [void]$e.Add('choose exactly one of -SelfTest, -DryRun, -Live') }
    if ($Idle -lt 30 -or $Idle -gt 720) { [void]$e.Add("IdleMinutes must be 30..720 (got $Idle)") }
    if ($Countdown -lt 10 -or $Countdown -gt 15) { [void]$e.Add("CountdownMinutes must be 10..15 (got $Countdown; the countdown window script allows at most 900 s)") }
    if ($Delay -lt 600 -or $Delay -gt 1800) { [void]$e.Add("ShutdownDelaySeconds must be 600..1800 (got $Delay)") }
    if ($Veto -lt 30 -or $Veto -gt 240) { [void]$e.Add("VetoMinutes must be 30..240 (got $Veto)") }
    # the veto must fire clearly AFTER the restart was due, so a slow restart is not cut short
    if ($Veto * 60 -lt $Delay + 600) { [void]$e.Add("VetoMinutes ($Veto) must leave at least 10 minutes after the restart is due (delay $Delay s)") }
    return @($e)
}

function Invoke-ArmRollback {
    # Undo, in this order: cancel a pending restart, remove the set by key, delete both tasks. Every step is tried.
    param($W, $Cfg, [bool]$ShutdownIssued)
    $r = [ordered]@{ shutdown_abort = $null; removal = $null; post_task = $null; veto_task = $null }
    if ($ShutdownIssued) { try { $r.shutdown_abort = [int](& $W.AbortShutdown) } catch { $r.shutdown_abort = "error: $($_.Exception.Message)" } }
    try { $r.removal = Remove-FenceSet -Backend $W.Backend } catch { $r.removal = [ordered]@{ Ok = $false; Error = $_.Exception.Message } }
    $r.post_task = & $W.UnregisterTask $Cfg.PostName
    $r.veto_task = & $W.UnregisterTask $Cfg.VetoName
    $r.Ok = [bool]($r.removal -and $r.removal.Ok)
    return $r
}

function Invoke-ArmCore {
    # The arming flow with every outside effect injected through $W (scriptblocks and a backend), so -SelfTest drives it with fakes.
    #   $W.Proof() $W.Idle() $W.Baseline() $W.Countdown() $W.Wsl() $W.Export(label) $W.Record(name, obj) $W.TaskExists(name)
    #   $W.RegisterTask(def) $W.UnregisterTask(name) $W.Shutdown(args) $W.AbortShutdown() $W.Monitor(seconds)   $W.Backend   $W.Plan
    param([Parameter(Mandatory)]$W, [Parameter(Mandatory)]$Cfg)
    $steps = [ordered]@{}
    $fin = { param($code, $reason) [pscustomobject]@{ Code = $code; Reason = $reason; Steps = $steps } }

    $dec = & $W.Decision
    $steps.restart_decision = $dec
    if (-not $dec.Ok) { return (& $fin 2 ('refused: ' + $dec.Reason + '. Nothing added')) }

    $proof = & $W.Proof
    $steps.proof = [ordered]@{ ok = [bool]$proof.Ok; problems = @($proof.Problems) }
    if (-not $proof.Ok) { return (& $fin 2 ('refused: ' + (@($proof.Problems) -join '; '))) }
    $pre = Get-FenceState -Backend $W.Backend
    $steps.fence_before = $pre
    if ($pre.State -ne 'ABSENT') { return (& $fin 2 "refused: the fence state is $($pre.State) before arming (stale objects or an unreadable engine); run spike-wfp-persist.ps1 -Remove. Nothing added") }
    foreach ($n in @($Cfg.PostName, $Cfg.VetoName)) { if (& $W.TaskExists $n) { return (& $fin 2 "refused: a task named $n is already registered (something is armed, or an earlier run died): inspect it. Nothing added") } }

    $ao = & $W.AdminOnly
    $steps.admin_only_folder = $ao
    if (-not $ao.Ok) { return (& $fin 2 ('refused: the script folder is writable by non-administrators, so the SYSTEM tasks would run attacker-editable code: ' + (@($ao.Problems | Select-Object -First 3) -join '; ') + '. Nothing added')) }

    $idle = & $W.Idle
    $steps.idle_gate = $idle
    if (-not $idle.Ok) { return (& $fin 10 ('refused by the idle gate: ' + $idle.Reason + '. Nothing added')) }

    $base = & $W.Baseline
    $steps.baseline = $base
    if (-not $base.Ok) { return (& $fin 5 ('no baseline: ' + $base.Detail + '. Nothing added')) }

    $cd = & $W.Countdown $idle.LastInputTick
    $steps.countdown = $cd
    if (-not $cd.Proceed) { return (& $fin $(if ($cd.Reason -match 'refusing') { 10 } else { 11 }) ('countdown: ' + $cd.Reason + '. Nothing added')) }

    $steps.wsl_shutdown = & $W.Wsl
    $armedAt = Get-Date
    $defs = Get-Arm3bTaskDefinitions -Folder $Cfg.Folder -OutDir $Cfg.OutDir -Wfp $Cfg.Wfp -PostName $Cfg.PostName -VetoName $Cfg.VetoName -WrapperName $Cfg.WrapperName -Now $armedAt -VetoMinutes $Cfg.VetoMinutes -WfpSha256 $Cfg.WfpSha256 -CodeSetId $Cfg.CodeSetId
    $sdArgs = Get-ShutdownArgs -DelaySeconds $Cfg.ShutdownDelaySeconds -Comment 'arm 3b'
    $armed = [ordered]@{ armed_at = $armedAt.ToString("yyyy-MM-dd'T'HH:mm:ss.fffzzz"); boot_time_at_arm = $(try { (Get-BootTime).ToString('o') } catch { $null }); filters_added_at = $null
                         post_task = $Cfg.PostName; veto_task = $Cfg.VetoName; wrapper_task = $Cfg.WrapperName; veto_fires_at = $defs.Veto.TriggerAt.ToString('o')
                         shutdown_command = 'shutdown.exe ' + ($sdArgs -join ' '); shutdown_delay_seconds = $Cfg.ShutdownDelaySeconds; out_dir = $Cfg.OutDir; account_sid = $Cfg.AccountSid; flags = $null }
    $issued = $false; $stage = 'registering the cleanup tasks'; $steps.armed = $armed
    try {
        # ORDER: the cleanup tasks come FIRST. From the moment the set exists, something that removes it by key is already registered, so an
        # exception, a killed process or a power loss between the add and the restart can never leave a persistent set with nothing to remove it.
        & $W.RegisterTask $defs.Post
        & $W.RegisterTask $defs.Veto
        $steps.tasks_registered = @($Cfg.PostName, $Cfg.VetoName)
        & $W.Record 'arm3b-armed' $armed      # filters_added_at is null here: a post-reboot run that finds this knows no add is recorded
        $stage = 'the add'
        $add = Add-FenceSet -Backend $W.Backend -Plan $W.Plan -Proof $proof
        $steps.add = $add
        if (-not $add.Ok) {
            $rb = Invoke-ArmRollback -W $W -Cfg $Cfg -ShutdownIssued $false
            $steps.rollback = $rb
            return (& $fin $(if (-not $rb.Ok) { 7 } elseif ($add.Refused) { 2 } else { 4 }) ("add not done: $($add.Reason). The cleanup tasks had been registered before the add; " + $(if ($rb.Ok) { 'they were deleted again and the set reads ABSENT' } else { 'the rollback was NOT verified: run spike-wfp-persist.ps1 -Remove' })))
        }
        $armed.filters_added_at = [string]$add.At; $armed.flags = $add.StateAfterAdd.Flags
        $stage = 'recording the add'
        & $W.Record 'arm3b-armed' $armed
        $stage = 'the pre-restart export'
        $steps.export_pre_reboot = & $W.Export 'pre-reboot'
        $stage = 'the shutdown command'
        $rc = [int](& $W.Shutdown $sdArgs)
        $steps.shutdown_issued = [ordered]@{ at = (Get-Date).ToString("yyyy-MM-dd'T'HH:mm:ss.fffzzz"); args = $sdArgs; exit_code = $rc }
        if ($rc -ne 0) { throw "shutdown.exe returned $rc" }
        $issued = $true
        $stage = 'watching for input before the restart'
        $mon = & $W.Monitor ($Cfg.ShutdownDelaySeconds + 120) $idle.LastInputTick
        $steps.pending_restart_watch = $mon
        if ($mon.InputDetected) {
            $rb = Invoke-ArmRollback -W $W -Cfg $Cfg -ShutdownIssued $true
            $steps.rollback = $rb
            return (& $fin $(if ($rb.Ok) { 11 } else { 7 }) $(if ($rb.Ok) { 'input while the restart was pending: shutdown /a, set removed by key, both tasks deleted' } else { 'input while the restart was pending, and the rollback was NOT verified' }))
        }
        return (& $fin 12 "armed; the restart had not started $($Cfg.ShutdownDelaySeconds + 120) s after the command (a blocked shutdown?); the veto watchdog fires at $($defs.Veto.TriggerAt.ToString('HH:mm:ss')) and rolls back")
    } catch {
        $steps.error = "$stage`: $($_.Exception.Message)"
        $rb = Invoke-ArmRollback -W $W -Cfg $Cfg -ShutdownIssued $issued
        $steps.rollback = $rb
        return (& $fin $(if ($rb.Ok) { 4 } else { 7 }) ("failed at $stage ($($_.Exception.Message)); " + $(if ($rb.Ok) { 'rolled back and verified (set removed by key, both tasks deleted)' } else { 'the rollback was NOT verified' })))
    }
}

function New-RealArmWorld {
    # Plain scriptblocks (not closures): they run in this script's own session state, so the script's functions resolve normally;
    # what they need lives in $script:Arm* variables.
    param($Backend, $Plan, $Sid)
    $script:ArmSid = $Sid; $script:ArmFolder = $PSScriptRoot; $script:ArmWindow = $null
    $W = @{ Backend = $Backend; Plan = $Plan }
    $W.Proof = {
        $pr = Test-RollbackProof -ProofPath $ProofPath -Folder $script:ArmFolder -WrappedSha256 $script:WrappedSha256Used
        $pl = @(Test-ProofLocation -ProofPath $ProofPath -ScriptFolder $script:ArmFolder)
        if ($pr.Ok -and $pl.Count) { $pr.Ok = $false; $pr.Problems = $pl }
        $pr
    }
    # The SYSTEM tasks run these scripts AND write their records into the output folder: both must be admin-only.
    $W.Decision = { Test-RestartDecision -Folder $script:ArmFolder }
    $W.AdminOnly = {
        $a = Test-AdminOnlyFolder -Path $script:ArmFolder
        New-Item -ItemType Directory -Force $OutDir | Out-Null
        $b = Test-AdminOnlyFolder -Path $OutDir
        [ordered]@{ Ok = ($a.Ok -and $b.Ok); Problems = @($a.Problems) + @($b.Problems | ForEach-Object { "output folder: $_" }); Checked = ($a.Checked + $b.Checked) }
    }
    $W.Idle = { Invoke-IdleGate -RequiredSeconds ($IdleMinutes * 60) }
    $W.Baseline = {
        $ctl = @(); foreach ($i in 1..3) { $ctl += Test-TcpConnect '1.1.1.1' 443 5000 }
        $opOk = (@($ctl | Where-Object { -not $_.ok }).Count -eq 0)
        $run = Invoke-ProbeTaskRun -RunId ('arm3b-base-' + (Get-Date -Format 'yyyyMMdd-HHmmss')) -ExpectedBlocked $false -TimeoutSec 60
        $open = [bool]($run.valid -and $run.outbound_probe -and $run.outbound_probe.probe.connected -and $run.token_sid -eq $script:ArmSid)
        $detail = if (-not $opOk) { 'the operator cannot reach 1.1.1.1:443' } elseif (-not $run.valid) { 'the account baseline run gave no valid result' } elseif (-not $open) { 'the account''s egress is ALREADY blocked or it ran as the wrong SID' } else { 'operator 3/3 and account egress open' }
        [pscustomobject]@{ Ok = ($opOk -and $open); Detail = $detail; operator = $ctl; account = $run }
    }
    $W.Countdown = {
        param($baselineTick)
        $script:ArmWindow = $null
        if (-not $NoWindow) { $script:ArmWindow = Start-CountdownWindow -ScriptPath $CountdownScript -Seconds ($CountdownMinutes * 60) -Title 'BlarAI arm 3b: restart planned' -Message 'A network test will add a Windows Filtering Platform filter and restart this computer when the countdown ends. Move the mouse or press any key (or press STOP) to cancel it.' }
        $notify = { param($stage, $left) Show-ToastNotification -Title 'BlarAI arm 3b: restart planned' -Body ("This computer will restart for a network test in {0} min unless you touch the keyboard or mouse." -f [Math]::Ceiling($left / 60)) }
        $wc = $null
        if ($script:ArmWindow) { $wc = { if ($script:ArmWindow.HasExited) { $script:ArmWindow.ExitCode } else { $null } } }
        try { Invoke-CountdownGate -Seconds ($CountdownMinutes * 60) -TickProvider { Get-LastInputTick } -Notify $notify -Sleep { param($s) Start-Sleep -Seconds $s } -Clock { Get-Date } -WindowCheck $wc -WindowStarted ([bool]$script:ArmWindow) -BaselineTick ([long]$baselineTick) }
        finally { if ($script:ArmWindow -and -not $script:ArmWindow.HasExited) { try { $script:ArmWindow.Kill() } catch {} } }
    }
    $W.Wsl = { Invoke-WslShutdown }
    $W.Export = { param($label) Invoke-PersistFilterExport -Label $label -Path (Join-Path $OutDir ("arm3b-filters-$label.xml")) }
    $W.Record = { param($name, $obj) New-Item -ItemType Directory -Force $OutDir | Out-Null; Write-JsonGuarded -Path (Join-Path $OutDir "$name.json") -Object $obj -Depth 10 }
    $W.TaskExists = { param($n) $null -ne (Get-TaskStateOrNull -Name $n) }
    $W.RegisterTask = { param($d) Register-Arm3bTask -Def $d }
    $W.UnregisterTask = { param($n) Unregister-TaskIfPresent -Name $n }
    $W.Shutdown = { param($a) & "$env:SystemRoot\System32\shutdown.exe" @a 2>&1 | Out-Null; $LASTEXITCODE }
    $W.AbortShutdown = { & "$env:SystemRoot\System32\shutdown.exe" /a 2>&1 | Out-Null; $LASTEXITCODE }
    $W.Monitor = { param($sec, $baselineTick) Wait-WithInputWatch -Seconds $sec -BaselineTick ([long]$baselineTick) -TickProvider { Get-LastInputTick } -Sleep { param($s) Start-Sleep -Seconds $s } -Clock { Get-Date } }
    return $W
}

function Invoke-Live {
    Initialize-PersistSession2   # the wrapped script's helpers (SID safety, elevation) and the types; opens no engine
    $sid = Get-SpikeSidOrNull
    if ($sid) { $unsafe = @(Get-SafeSidProblems -Sid $sid); if ($unsafe.Count) { Write-Host ('REFUSED (exit 3): ' + ($unsafe -join '; ')) -ForegroundColor Red; return 3 } }
    if (-not (Test-IsElevated)) { Write-Host 'FAIL: not elevated.' -ForegroundColor Red; return 2 }
    $problems = @(Assert-SpikePreflight -ScriptFolder $PSScriptRoot)
    if ($problems.Count) { $problems | ForEach-Object { Write-Host "FAIL: $_" -ForegroundColor Red }; return 2 }
    $a = Test-ArmArgs $false $false $true $IdleMinutes $CountdownMinutes $ShutdownDelaySeconds $VetoMinutes
    if ($a.Count) { $a | ForEach-Object { Write-Host "ARG ERROR: $_" -ForegroundColor Red }; return 2 }
    $plan = [BlarAI.WfpPersist.PersistPlan]::Build($sid)
    $be = $null
    try { $be = New-RealBackend } catch { Write-Host "FAIL: the engine could not be opened: $($_.Exception.Message)" -ForegroundColor Red; return 2 }
    try {
        $W = New-RealArmWorld -Backend $be -Plan $plan -Sid $sid
        $cfg = [pscustomobject]@{ PostName = $script:Arm3bPostName; VetoName = $script:Arm3bVetoName; WrapperName = $script:Arm3bWrapperName; Folder = $PSScriptRoot; OutDir = $OutDir; Wfp = $WfpScript; WfpSha256 = $script:WrappedSha256Used; CodeSetId = (Get-CodeSetId -Hashes (Get-CodeSetHashes -Folder $PSScriptRoot).Hashes); VetoMinutes = $VetoMinutes; ShutdownDelaySeconds = $ShutdownDelaySeconds; AccountSid = $sid }
        Write-Host 'ROLLBACK FACT: the set is PERSISTENT. Rollbacks: this script (input aborts it), the veto watchdog task, spike-wfp-persist.ps1 -Remove, then the README manual rollback.' -ForegroundColor Yellow
        $res = Invoke-ArmCore -W $W -Cfg $cfg
    } finally { $be.Close() }
    try { Write-JsonGuarded -Path (Join-Path $OutDir ("arm3b-arm-result-{0}.json" -f (Get-Date -Format 'yyyyMMdd-HHmmss'))) -Object ([ordered]@{ exit_code = $res.Code; exit_reason = $res.Reason; steps = $res.Steps; finished = (Get-Date).ToString("yyyy-MM-dd'T'HH:mm:ss.fffzzz") }) -Depth 12 } catch { Write-Host "could not write the arming record: $($_.Exception.Message)" -ForegroundColor Yellow }
    Write-Host ("RESULT: exit {0}: {1}" -f $res.Code, $res.Reason) -ForegroundColor $(if ($res.Code -in @(11, 12)) { 'Yellow' } else { 'Red' })
    return $res.Code
}

function Initialize-PersistSession2 {
    $null = Import-WfpHelpers -Path $WfpScript
    Initialize-PersistType
}

function Invoke-DryRun {
    Write-Host '== DRY RUN: nothing is added, registered or scheduled; no WFP engine is opened ==' -ForegroundColor Yellow
    Initialize-PersistSession2
    $sid = Get-SpikeSidOrNull; $fab = $false
    if (-not $sid) { $sid = 'S-1-5-21-1111111111-2222222222-3333333333-1001'; $fab = $true; Write-Host "account '$($script:SpikeUser)' not found: using a FABRICATED SID to build the plan ($sid). -Live would exit 2." -ForegroundColor Yellow }
    $safety = @(Get-SafeSidProblems -Sid $sid)
    Write-Host ("account SID {0}; SID safety: {1}" -f $sid, $(if ($safety.Count -eq 0) { 'OK' } else { 'REFUSED (exit 3): ' + ($safety -join '; ') }))
    $a = Test-ArmArgs $false $true $false $IdleMinutes $CountdownMinutes $ShutdownDelaySeconds $VetoMinutes
    if ($a.Count) { $a | ForEach-Object { Write-Host "ARG ERROR: $_" -ForegroundColor Red }; return 2 }
    $plan = [BlarAI.WfpPersist.PersistPlan]::Build($sid)
    $now = Get-Date
    $idle = Get-IdleSecondsNow
    Write-Host ''; Write-Host '--- timeline (from now, if every gate passed) ---'
    Write-Host ("  now                      {0}" -f $now.ToString('HH:mm:ss'))
    Write-Host ("  idle gate                needs {0} min with no keyboard or mouse input (now: {1})" -f $IdleMinutes, $(if ($idle -lt 0) { 'unreadable, which refuses' } else { "$idle s idle, which would $(if ($idle -ge $IdleMinutes * 60) { 'pass' } else { 'REFUSE' })" }))
    Write-Host ("  account baseline         one task run in probe mode + operator 3x 1.1.1.1:443")
    Write-Host ("  countdown                {0} min of toast + window; ANY input or STOP aborts, nothing added (exit 11)" -f $CountdownMinutes)
    Write-Host ("  wsl --shutdown, ADD      at about {0}" -f $now.AddMinutes($CountdownMinutes).ToString('HH:mm:ss'))
    Write-Host ("  shutdown.exe {0}      restart due at about {1}; input before it = shutdown /a + rollback (exit 11)" -f ((Get-ShutdownArgs -DelaySeconds $ShutdownDelaySeconds -Comment 'arm 3b') -join ' '), $now.AddMinutes($CountdownMinutes).AddSeconds($ShutdownDelaySeconds).ToString('HH:mm:ss'))
    Write-Host ("  veto watchdog fires      {0}  (VetoMinutes {1} after arming)" -f $now.AddMinutes($CountdownMinutes).AddMinutes($VetoMinutes).ToString('HH:mm:ss'), $VetoMinutes)
    Write-Host ''; Write-Host '--- EXACTLY what would be added (persistent; every filter keyed to the account SID) ---'; Write-Host $plan.Describe()
    $defs = Get-Arm3bTaskDefinitions -Folder $PSScriptRoot -OutDir $OutDir -Wfp $WfpScript -Now $now.AddMinutes($CountdownMinutes) -VetoMinutes $VetoMinutes -WfpSha256 $script:WrappedSha256Used -CodeSetId (Get-CodeSetId -Hashes (Get-CodeSetHashes -Folder $PSScriptRoot).Hashes)
    Write-Host '--- task 1: post-reboot (deletes itself when it has finished) ---'; $defs.Post | Format-List | Out-String -Width 200 | Write-Host
    Write-Host '--- task 2: veto watchdog ---'; $defs.Veto | Format-List | Out-String -Width 200 | Write-Host
    Write-Host '--- refusals (nothing is added unless ALL hold) ---'
    @('rollback self-test proof valid for these exact scripts', 'target SID is not the operator and not one of his groups', 'elevated, 64-bit, in the operator''s own session', 'spike account, task and bin copies as expected', 'fence state ABSENT (no stale object)', 'neither task already registered', 'idle gate', 'account baseline and operator control', 'countdown untouched, a visible warning raised') | ForEach-Object { Write-Host "  - $_" }
    $ao = Test-AdminOnlyFolder -Path $PSScriptRoot
    if ($ao.Ok) { Write-Host "script folder: admin-only ($($ao.Checked) paths checked): the SYSTEM tasks and the elevated wrapper may run from here." -ForegroundColor Green } else { Write-Host '-Live would REFUSE: the script folder is writable by non-administrators, so the SYSTEM tasks would be a privilege-escalation path:' -ForegroundColor Yellow; $ao.Problems | Select-Object -First 5 | ForEach-Object { Write-Host "   $_" -ForegroundColor Yellow } }
    $proof = Test-RollbackProof -ProofPath $ProofPath -Folder $PSScriptRoot -WrappedSha256 $script:WrappedSha256Used
    if ($proof.Ok) { Write-Host "proof: VALID (written $($proof.Written))" -ForegroundColor Green } else { $proof.Problems | ForEach-Object { Write-Host "proof: NO VALID PROOF: $_" -ForegroundColor Yellow }; Write-Host '  -Live would REFUSE until spike-wfp-persist.ps1 -SelfTest -WriteProof has run on these exact files.' -ForegroundColor Yellow }
    $cd = if (Test-Path -LiteralPath $CountdownScript) { 'present' } else { 'NOT FOUND (the toast alone would carry the warning)' }
    Write-Host "countdown window script: $CountdownScript ($cd)"
    Write-Host '--- rollback ---'; Write-Host '  spike-wfp-persist.ps1 -Remove; then the manual snippet printed by spike-wfp-persist.ps1 -DryRun and kept in the README.'
    Write-Host 'DRY RUN complete. Nothing was added.' -ForegroundColor Green
    if ($fab) { return 2 }; if ($safety.Count) { return 3 }
    return 0
}

function Invoke-SelfTest {
    $script:f = 0
    function Chk([string]$n, [bool]$c) { if ($c) { Write-Host "  [PASS] $n" -ForegroundColor Green } else { Write-Host "  [FAIL] $n" -ForegroundColor Red; $script:f++ } }
    Write-Host '== argument rules (floors, not defaults) ==' -ForegroundColor Cyan
    Chk 'defaults are valid (30 min idle, 10 min countdown, 600 s delay, 30 min veto)' ((Test-ArmArgs $false $false $true 30 10 600 30).Count -eq 0)
    Chk 'exactly one mode' (((Test-ArmArgs $false $false $false 30 10 600 30).Count -ge 1) -and ((Test-ArmArgs $true $false $true 30 10 600 30).Count -ge 1))
    Chk 'idle below 30 minutes is refused (cannot be lowered for convenience)' (((Test-ArmArgs $false $false $true 29 10 600 30).Count -ge 1) -and ((Test-ArmArgs $false $false $true 721 10 600 30).Count -ge 1))
    Chk 'countdown below 10 minutes, or above the window script''s 15-minute maximum, is refused' (((Test-ArmArgs $false $false $true 30 9 600 30).Count -ge 1) -and ((Test-ArmArgs $false $false $true 30 16 600 30).Count -ge 1))
    Chk 'restart delay below 600 s or above 1800 s is refused' (((Test-ArmArgs $false $false $true 30 10 599 30).Count -ge 1) -and ((Test-ArmArgs $false $false $true 30 10 1801 60).Count -ge 1))
    Chk 'veto below 30 minutes, or less than 10 minutes after the restart is due, is refused' (((Test-ArmArgs $false $false $true 30 10 600 29).Count -ge 1) -and ((Test-ArmArgs $false $false $true 30 10 1800 35).Count -ge 1) -and ((Test-ArmArgs $false $false $true 30 10 1800 40).Count -eq 0))
    Write-Host '== task definitions ==' -ForegroundColor Cyan
    $d = Get-Arm3bTaskDefinitions -Folder 'C:\f' -OutDir 'C:\o' -Wfp 'C:\w\w.ps1' -Now ([datetime]'2026-10-11T12:00:00') -VetoMinutes 30
    Chk 'post-reboot task: SYSTEM, Highest, at startup with a one-minute delay, -Live, baked absolute paths and all three task names' (($d.Post.User -eq 'NT AUTHORITY\SYSTEM') -and ($d.Post.RunLevel -eq 'Highest') -and ($d.Post.Trigger -eq 'AtStartup') -and ($d.Post.TriggerDelay -eq 'PT1M') -and ($d.Post.Arguments -match ' -Live ') -and ($d.Post.Arguments -match 'spike-arm3b-post-reboot.ps1') -and ($d.Post.Arguments -match '-OutDir "C:\\o"') -and ($d.Post.Arguments -match '-TaskName blarai-arm3b-post-reboot') -and ($d.Post.Arguments -match '-VetoTaskName blarai-arm3b-veto') -and ($d.Post.Arguments -match '-WrapperTaskName blarai-arm3b-arm-run'))
    Chk 'veto task: SYSTEM, Highest, once, exactly 30 minutes after arming, running the veto script' (($d.Veto.User -eq 'NT AUTHORITY\SYSTEM') -and ($d.Veto.Trigger -eq 'Once') -and ($d.Veto.TriggerAt -eq [datetime]'2026-10-11T12:30:00') -and ($d.Veto.Arguments -match 'spike-arm3b-veto.ps1'))
    $dpin = Get-Arm3bTaskDefinitions -Folder 'C:\f' -OutDir 'C:\o' -Wfp 'C:\w\w.ps1' -Now ([datetime]'2026-10-11T12:00:00') -VetoMinutes 30 -WfpSha256 ('CD' * 32) -CodeSetId ('EF' * 32)
    Chk 'both SYSTEM tasks carry the pinned hash of the wrapped script and the code-set id when given' (($dpin.Post.Arguments -match ('-WfpSha256 ' + ('CD' * 32) + ' -CodeSetId ' + ('EF' * 32) + '$')) -and ($dpin.Veto.Arguments -match ('-CodeSetId ' + ('EF' * 32) + '$')) -and ($d.Post.Arguments -notmatch 'WfpSha256') -and ($d.Post.Arguments -notmatch 'CodeSetId'))
    Chk 'neither registered task can add: no argument names the arming script or -Arm3a' (($d.Post.Arguments + ' ' + $d.Veto.Arguments) -notmatch 'spike-arm3b-arm|Arm3a')
    Write-Host '== idle gate and countdown gate ==' -ForegroundColor Cyan
    $script:IdleSelfFail = 0
    $idleFails = Invoke-IdleGateSelfTest
    if ($idleFails -gt 0) { $script:f += $idleFails }
    Write-Host '== the arming flow against fakes ==' -ForegroundColor Cyan
    $null = Import-WfpHelpers -Path $WfpScript -Unverified; Initialize-PersistType
    $sid = 'S-1-5-21-1111111111-2222222222-3333333333-1001'
    $plan = [BlarAI.WfpPersist.PersistPlan]::Build($sid)
    $cfg = [pscustomobject]@{ PostName = 'blarai-arm3b-post-reboot'; VetoName = 'blarai-arm3b-veto'; WrapperName = 'blarai-arm3b-arm-run'; Folder = 'C:\f'; OutDir = 'C:\o'; Wfp = 'C:\w\w.ps1'; VetoMinutes = 30; ShutdownDelaySeconds = 600; AccountSid = $sid }
    function New-World($over) {
        $be = New-FakeBackend
        $calls = New-Object System.Collections.ArrayList; $tasks = New-Object System.Collections.ArrayList
        $w = @{ Backend = $be; Plan = $plan; Calls = $calls; Tasks = $tasks }
        $w.Proof = { [pscustomobject]@{ Kind = 'RollbackProof'; Ok = $true; Problems = @() } }
        $w.AdminOnly = { [ordered]@{ Ok = $true; Problems = @(); Checked = 3 } }
        $w.Decision = { [ordered]@{ Ok = $true; Reason = 'decision recorded' } }
        $w.Idle = { [ordered]@{ Ok = $true; IdleSeconds = 3600; Reason = 'ok' } }
        $w.Baseline = { [pscustomobject]@{ Ok = $true; Detail = 'ok' } }
        $w.Countdown = { [ordered]@{ Proceed = $true; Reason = 'ran to zero'; ElapsedSeconds = 600 } }
        $w.Wsl = { 'wsl-done' }
        $w.Export = { param($l) [ordered]@{ label = $l; ok = $true } }
        $w.Record = { param($n, $o) [void]$calls.Add("record $n") }.GetNewClosure()
        $w.TaskExists = { param($n) $tasks -contains $n }.GetNewClosure()
        $w.RegisterTask = { param($d) [void]$calls.Add("register $($d.TaskName)"); [void]$calls.Add("store-at-register $($be.Store.Count)"); [void]$tasks.Add($d.TaskName) }.GetNewClosure()
        $w.UnregisterTask = { param($n) [void]$calls.Add("unregister $n"); [void]$tasks.Remove($n); 'unregistered' }.GetNewClosure()
        $w.Shutdown = { param($a) [void]$calls.Add('shutdown ' + ($a -join ' ')); 0 }.GetNewClosure()
        $w.AbortShutdown = { [void]$calls.Add('shutdown /a'); 0 }.GetNewClosure()
        $w.Monitor = { param($s) [ordered]@{ Completed = $true; InputDetected = $false; ElapsedSeconds = $s } }
        foreach ($k in @($over.Keys)) { $w[$k] = $over[$k] }
        $w
    }
    $nothingAdded = { param($w) ($w.Backend.Store.Count -eq 0) -and (@($w.Calls | Where-Object { $_ -like 'register *' -or $_ -like 'shutdown *' }).Count -eq 0) -and (@($w.Backend.Calls | Where-Object { $_ -eq 'addall' }).Count -eq 0) }
    $w1 = New-World @{ Idle = { [ordered]@{ Ok = $false; IdleSeconds = 600; Reason = 'only 600 s idle' } } }
    $r1 = Invoke-ArmCore -W $w1 -Cfg $cfg
    Chk 'not idle: exit 10, nothing added, no task, no shutdown' (($r1.Code -eq 10) -and (& $nothingAdded $w1))
    $w2 = New-World @{ Countdown = { [ordered]@{ Proceed = $false; Reason = 'keyboard or mouse input after 100 s: aborted'; ElapsedSeconds = 100 } } }
    $r2 = Invoke-ArmCore -W $w2 -Cfg $cfg
    Chk 'input during the countdown: exit 11, nothing added, no task, no shutdown' (($r2.Code -eq 11) -and (& $nothingAdded $w2))
    $w3 = New-World @{ Countdown = { [ordered]@{ Proceed = $false; Reason = 'no visible warning could be raised (no toast, no window): refusing'; ElapsedSeconds = 0 } } }
    $r3 = Invoke-ArmCore -W $w3 -Cfg $cfg
    Chk 'no visible warning could be raised: exit 10, nothing added' (($r3.Code -eq 10) -and (& $nothingAdded $w3))
    $w4 = New-World @{ Proof = { [pscustomobject]@{ Kind = 'RollbackProof'; Ok = $false; Problems = @('no proof') } } }
    $r4 = Invoke-ArmCore -W $w4 -Cfg $cfg
    Chk 'no valid proof: exit 2, nothing added (the add path is unreachable)' (($r4.Code -eq 2) -and (& $nothingAdded $w4))
    $w5 = New-World @{}; $w5.Backend.Store["filter|$($script:PersistFilterKeys[0])"] = 1
    $r5 = Invoke-ArmCore -W $w5 -Cfg $cfg
    Chk 'a stale object: exit 2, nothing registered, no shutdown, the stale object is left for -Remove' (($r5.Code -eq 2) -and ($w5.Backend.Store.Count -eq 1) -and (@($w5.Calls | Where-Object { $_ -like 'register *' -or $_ -like 'shutdown *' }).Count -eq 0))
    $w6 = New-World @{}; [void]$w6.Tasks.Add('blarai-arm3b-veto')
    $r6 = Invoke-ArmCore -W $w6 -Cfg $cfg
    Chk 'a task already registered (something armed): exit 2, nothing added' (($r6.Code -eq 2) -and ($w6.Backend.Store.Count -eq 0) -and (@($w6.Backend.Calls | Where-Object { $_ -eq 'addall' }).Count -eq 0))
    $w7 = New-World @{ Baseline = { [pscustomobject]@{ Ok = $false; Detail = 'the operator cannot reach 1.1.1.1:443' } } }
    $r7 = Invoke-ArmCore -W $w7 -Cfg $cfg
    Chk 'no baseline: exit 5, nothing added' (($r7.Code -eq 5) -and (& $nothingAdded $w7))
    $w8 = New-World @{}
    $r8 = Invoke-ArmCore -W $w8 -Cfg $cfg
    $sdCalls = @($w8.Calls | Where-Object { $_ -like 'shutdown *' })
    Chk 'happy path: all four objects added and persistent, both tasks registered, then exactly "shutdown /r /t 600 /c arm 3b", exit 12 (restart pending when the watch ended)' (($r8.Code -eq 12) -and ($w8.Backend.Store.Count -eq 4) -and ((Get-FenceState -Backend $w8.Backend).AllPersistent) -and ($w8.Tasks.Count -eq 2) -and ($sdCalls.Count -eq 1) -and ($sdCalls[0] -eq 'shutdown /r /t 600 /c arm 3b'))
    $iReg = $w8.Calls.IndexOf('register blarai-arm3b-post-reboot'); $iVeto = $w8.Calls.IndexOf('register blarai-arm3b-veto'); $iSd = $w8.Calls.IndexOf($sdCalls[0]); $iRec = $w8.Calls.IndexOf('record arm3b-armed')
    Chk 'ORDER: both cleanup tasks are registered while the store is still EMPTY (before the add), the armed record follows, the shutdown command comes last' (($iReg -ge 0) -and ($w8.Calls[$iReg + 1] -eq 'store-at-register 0') -and ($iVeto -gt $iReg) -and ($w8.Calls[$iVeto + 1] -eq 'store-at-register 0') -and ($iRec -gt $iVeto) -and ($iSd -gt $iRec))
    Chk 'the armed record is written twice: first without filters_added_at (an interrupted arming is recognisable), then with it and the flags' (@($w8.Calls | Where-Object { $_ -eq 'record arm3b-armed' }).Count -eq 2 -and ($r8.Steps.armed.filters_added_at) -and ($r8.Steps.armed.flags.Count -eq 4))
    $w9 = New-World @{ Monitor = { param($s) [ordered]@{ Completed = $false; InputDetected = $true; ElapsedSeconds = 90 } } }
    $r9 = Invoke-ArmCore -W $w9 -Cfg $cfg
    Chk 'input while the restart is pending: shutdown /a, set removed by key (ABSENT), both tasks deleted, exit 11' (($r9.Code -eq 11) -and ($w9.Calls -contains 'shutdown /a') -and ($w9.Backend.Store.Count -eq 0) -and ($w9.Tasks.Count -eq 0))
    $iAbort = $w9.Calls.IndexOf('shutdown /a')
    Chk 'rollback order: the pending restart is cancelled BEFORE the tasks are deleted' ($iAbort -ge 0 -and $iAbort -lt $w9.Calls.IndexOf('unregister blarai-arm3b-post-reboot'))
    $w10 = New-World @{ RegisterTask = { param($d) throw 'access denied' } }
    $r10 = Invoke-ArmCore -W $w10 -Cfg $cfg
    Chk 'a failed task registration: NOTHING was added (the add comes after the tasks), no shutdown command, rolled back, exit 4' (($r10.Code -eq 4) -and ($w10.Backend.Store.Count -eq 0) -and (@($w10.Backend.Calls | Where-Object { $_ -eq 'addall' }).Count -eq 0) -and (@($w10.Calls | Where-Object { $_ -like 'shutdown *' }).Count -eq 0) -and ($r10.Reason -match 'rolled back') -and ($r10.Reason -match 'registering the cleanup tasks'))
    $w11 = New-World @{ Shutdown = { param($a) 1190 } }
    $r11 = Invoke-ArmCore -W $w11 -Cfg $cfg
    Chk 'a failing shutdown command: rolled back, both tasks deleted, set removed, exit 4, the stage named' (($r11.Code -eq 4) -and ($w11.Backend.Store.Count -eq 0) -and ($w11.Tasks.Count -eq 0) -and ($r11.Reason -match 'the shutdown command'))
    $w12 = New-World @{ Shutdown = { param($a) 1190 } }; $w12.Backend.FailDelete = @($script:PersistProviderKey)
    $r12 = Invoke-ArmCore -W $w12 -Cfg $cfg
    Chk 'a rollback whose removal fails: exit 7 (NOT verified), never 4' ($r12.Code -eq 7)
    $w13 = New-World @{}; $w13.Backend.AddClearsFlags = $true
    $r13 = Invoke-ArmCore -W $w13 -Cfg $cfg
    Chk 'an add that is not persistent: the cleanup tasks (registered before it) are deleted again, set absent, no shutdown, exit 4 and the reason says so' (($r13.Code -eq 4) -and ($w13.Backend.Store.Count -eq 0) -and ($w13.Tasks.Count -eq 0) -and (@($w13.Calls | Where-Object { $_ -like 'shutdown *' }).Count -eq 0) -and ($r13.Reason -match 'deleted again'))
    $w14 = New-World @{ Record = { param($n, $o) if ($o.filters_added_at) { throw 'disk full while recording the add' } } }
    $r14 = Invoke-ArmCore -W $w14 -Cfg $cfg
    Chk 'an exception AFTER the add (the old unprotected window): the set is removed by key and both tasks deleted, exit 4, never "nothing was added"' (($r14.Code -eq 4) -and ($w14.Backend.Store.Count -eq 0) -and ($w14.Tasks.Count -eq 0) -and ($r14.Reason -notmatch 'Nothing added') -and ($r14.Reason -match 'recording the add'))
    $w16 = New-World @{ Decision = { [ordered]@{ Ok = $false; Reason = 'no recorded decision: the 3b restart is forced' } } }
    $r16 = Invoke-ArmCore -W $w16 -Cfg $cfg
    Chk 'no recorded Lead Architect decision on the forced restart: exit 2 before anything else, nothing added, no task, no shutdown' (($r16.Code -eq 2) -and (& $nothingAdded $w16) -and ($r16.Reason -match 'forced'))
    $dt = Join-Path ([IO.Path]::GetTempPath()) ('dec-' + [guid]::NewGuid().ToString('N')); New-Item -ItemType Directory -Path $dt | Out-Null
    try {
        $nowD = [datetimeoffset]::Now
        $mkd = { param($o) [IO.File]::WriteAllText((Join-Path $dt 'arm3b-restart-decision.json'), (ConvertTo-Json -InputObject $o)) }
        Chk 'decision file: absent -> refused' (-not (Test-RestartDecision -Folder $dt).Ok)
        & $mkd ([ordered]@{ decision = 'accept-forced-restart'; decided_by = 'Lead Architect'; decided_at = $nowD.AddHours(-1).ToString('o'); reference = '#1682 comment' })
        $okD = Test-RestartDecision -Folder $dt
        & $mkd ([ordered]@{ decision = 'maybe'; decided_by = 'x'; decided_at = $nowD.ToString('o'); reference = 'r' }); $bad1 = (Test-RestartDecision -Folder $dt).Ok
        & $mkd ([ordered]@{ decision = 'accept-forced-restart'; decided_by = ''; decided_at = $nowD.ToString('o'); reference = 'r' }); $bad2 = (Test-RestartDecision -Folder $dt).Ok
        & $mkd ([ordered]@{ decision = 'accept-forced-restart'; decided_by = 'x'; decided_at = $nowD.ToString('o'); reference = '' }); $bad3 = (Test-RestartDecision -Folder $dt).Ok
        & $mkd ([ordered]@{ decision = 'accept-forced-restart'; decided_by = 'x'; decided_at = $nowD.AddDays(-30).ToString('o'); reference = 'r' }); $bad4 = (Test-RestartDecision -Folder $dt).Ok
        & $mkd ([ordered]@{ decision = 'accept-forced-restart'; decided_by = 'x'; decided_at = $nowD.AddDays(2).ToString('o'); reference = 'r' }); $bad5 = (Test-RestartDecision -Folder $dt).Ok
        [IO.File]::WriteAllText((Join-Path $dt 'arm3b-restart-decision.json'), '{not json'); $bad6 = (Test-RestartDecision -Folder $dt).Ok
        Chk 'decision file: a complete recent decision is accepted; a wrong decision, no name, no reference, 30 days old, dated in the future, or unparseable are each refused' (($okD.Ok -eq $true) -and -not $bad1 -and -not $bad2 -and -not $bad3 -and -not $bad4 -and -not $bad5 -and -not $bad6)
    } finally { Remove-Item -LiteralPath $dt -Recurse -Force -ErrorAction SilentlyContinue }
    $w15 = New-World @{ AdminOnly = { [ordered]@{ Ok = $false; Problems = @('C:\f: S-1-5-32-545 is allowed rights 0x1301BF'); Checked = 2 } } }
    $r15 = Invoke-ArmCore -W $w15 -Cfg $cfg
    Chk 'a script folder writable by non-administrators: exit 2, nothing added, no task registered (SYSTEM tasks would run editable code)' (($r15.Code -eq 2) -and (& $nothingAdded $w15) -and ($r15.Reason -match 'writable by non-administrators'))
    Chk 'the steps record carries the idle gate, countdown, add flags and the shutdown command for the evidence' (($r8.Steps.idle_gate.Ok) -and ($r8.Steps.countdown.Proceed) -and ($r8.Steps.add.StateAfterAdd.Flags.Count -eq 4) -and ($r8.Steps.shutdown_issued.args -join ' ') -eq '/r /t 600 /c arm 3b')
    Write-Host ("arm3b-arm selftest: {0}" -f $(if ($script:f -eq 0) { 'all passed' } else { "$($script:f) FAILED" })) -ForegroundColor $(if ($script:f -eq 0) { 'Green' } else { 'Red' })
    return $(if ($script:f -eq 0) { 0 } else { 1 })
}

$argErrors = Test-ArmArgs $SelfTest.IsPresent $DryRun.IsPresent $Live.IsPresent $IdleMinutes $CountdownMinutes $ShutdownDelaySeconds $VetoMinutes
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
