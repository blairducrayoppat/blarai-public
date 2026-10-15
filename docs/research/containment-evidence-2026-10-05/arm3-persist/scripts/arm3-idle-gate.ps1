#requires -Version 5.1
<#
.SYNOPSIS
  Arm 3b precondition module: the operator must be away before anything is armed. Dot-source it; it defines functions only
  (it has no param block on purpose: dot-sourcing a script with parameters would overwrite the caller's same-named variables).
  Its checks are run by `spike-arm3b-arm.ps1 -SelfTest` (Invoke-IdleGateSelfTest) and nothing here changes system state.

.DESCRIPTION
  1. Idle gate: no keyboard or mouse input (GetLastInputInfo) for the required time (30 minutes). An idle time that cannot be
     read refuses.
  2. Countdown gate: a visible Windows toast (and, when countdown_gate.ps1 is available, its always-on-top window with a STOP
     button) for the countdown (10 minutes) during which ANY input aborts. If no visible warning could be raised the gate
     refuses: a warning nobody can see is not a warning. An unreadable input clock aborts.
  3. Wait-WithInputWatch: the same input watch, reused for the minutes between the shutdown command and the reboot.
  4. Get-ShutdownArgs: the shutdown command's arguments. They contain no /f, BUT `shutdown /r /t N` with N above 0 implies /f on
     Windows (shutdown /? says so): applications are closed WITHOUT forewarning when the timer ends. So `/t 600` is a forced restart
     with a ten-minute warning, and the idle gate plus the input watch are the only protection for unsaved work. Do not rely on the
     missing /f.

  One input baseline runs through the whole sequence: the last-input tick read at the idle gate is the baseline of the countdown and of
  the watch before the restart, so input between the gate and the countdown (or after it) is not absorbed by a fresh read.

  The idle clock is per session: it is only meaningful in the operator's own interactive session, so a non-interactive or session-0 process
  reads as unreadable (-1) and the gate refuses.

  Every provider (input clock, notifier, sleeper, wall clock, window) is injected, so the self-test runs the whole timeline with
  fakes in milliseconds. The real providers are Get-LastInputTick, Show-ToastNotification, Start-CountdownWindow.
#>

if (-not ('SpikeIdle' -as [type])) {
    Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
public static class SpikeIdle {
    [StructLayout(LayoutKind.Sequential)] struct LASTINPUTINFO { public uint cbSize; public uint dwTime; }
    [DllImport("user32.dll")] static extern bool GetLastInputInfo(ref LASTINPUTINFO p);
    // The tick (32-bit, same counter as Environment.TickCount) of the last keyboard or mouse input in THIS session; -1 if unreadable.
    public static long LastInputTick() {
        LASTINPUTINFO i = new LASTINPUTINFO(); i.cbSize = (uint)Marshal.SizeOf(typeof(LASTINPUTINFO));
        if (!GetLastInputInfo(ref i)) return -1;
        return (long)i.dwTime;
    }
    // Milliseconds since the last input; -1 if unreadable.
    public static long IdleMilliseconds() {
        long t = LastInputTick(); if (t < 0) return -1;
        return (long)unchecked((uint)(Environment.TickCount - (int)t));
    }
}
'@
}

function Get-LastInputTick { return [SpikeIdle]::LastInputTick() }
function Test-InteractiveSession {
    # PURE. The input clock belongs to the session's desktop: session 0 or a non-interactive process cannot see the operator's input.
    param([int]$SessionId, [bool]$UserInteractive)
    return ($SessionId -gt 0 -and $UserInteractive)
}

function Get-IdleSecondsNow {
    if (-not (Test-InteractiveSession -SessionId ([Diagnostics.Process]::GetCurrentProcess().SessionId) -UserInteractive ([Environment]::UserInteractive))) { return -1 }
    $ms = [SpikeIdle]::IdleMilliseconds(); if ($ms -lt 0) { return -1 } else { return [Math]::Floor($ms / 1000) }
}

function Test-IdleSufficient {
    # PURE. An unreadable idle time (negative) never passes.
    param([double]$IdleSeconds, [int]$RequiredSeconds)
    return ($IdleSeconds -ge 0 -and $IdleSeconds -ge $RequiredSeconds)
}

function Test-InputOccurred {
    # PURE. True when the last-input tick moved since the baseline, or when either reading is unreadable (fail closed).
    param([long]$BaselineTick, [long]$CurrentTick)
    if ($BaselineTick -lt 0 -or $CurrentTick -lt 0) { return $true }
    return ($CurrentTick -ne $BaselineTick)
}

function Get-ShutdownArgs {
    # PURE. Restart after $DelaySeconds with a comment. No /f is passed, but /t above 0 implies /f (see the module header): this restart is forced.
    param([ValidateRange(60, 3600)][int]$DelaySeconds = 600, [string]$Comment = 'arm 3b')
    return @('/r', '/t', "$DelaySeconds", '/c', $Comment)
}

function Invoke-IdleGate {
    param([int]$RequiredSeconds = 1800, [scriptblock]$IdleProvider = { Get-IdleSecondsNow }, [scriptblock]$TickProvider = { Get-LastInputTick })
    $tick = [long](& $TickProvider)      # the baseline for everything that follows
    $idle = [double](& $IdleProvider)
    if (Test-IdleSufficient -IdleSeconds $idle -RequiredSeconds $RequiredSeconds) { return [ordered]@{ Ok = $true; IdleSeconds = $idle; LastInputTick = $tick; Reason = "idle $idle s >= $RequiredSeconds s" } }
    $why = if ($idle -lt 0) { 'the idle time could not be read (not the operator''s interactive session?): refusing' } else { "only $idle s idle, $RequiredSeconds s required: refusing" }
    return [ordered]@{ Ok = $false; IdleSeconds = $idle; LastInputTick = $tick; Reason = $why }
}

function Wait-WithInputWatch {
    # Waits $Seconds, polling the input clock every $PollSeconds. Returns early with InputDetected = $true the moment the
    # last-input tick differs from $BaselineTick (or cannot be read). $OnPoll (optional) is called with the elapsed seconds and
    # may return $false to stop the wait early (Stopped = $true); it is how a countdown window reports a STOP press.
    param([int]$Seconds, [long]$BaselineTick, [scriptblock]$TickProvider, [scriptblock]$Sleep, [scriptblock]$Clock, [int]$PollSeconds = 2, [scriptblock]$OnPoll)
    $start = & $Clock; $polls = 0
    while ($true) {
        $elapsed = ((& $Clock) - $start).TotalSeconds
        if ($elapsed -ge $Seconds) { return [ordered]@{ Completed = $true; InputDetected = $false; Stopped = $false; ElapsedSeconds = [Math]::Round($elapsed, 1); Polls = $polls } }
        $cur = [long](& $TickProvider); $polls++
        if (Test-InputOccurred -BaselineTick $BaselineTick -CurrentTick $cur) { return [ordered]@{ Completed = $false; InputDetected = $true; Stopped = $false; ElapsedSeconds = [Math]::Round($elapsed, 1); Polls = $polls } }
        if ($OnPoll) { $go = & $OnPoll $elapsed; if ($go -eq $false) { return [ordered]@{ Completed = $false; InputDetected = $false; Stopped = $true; ElapsedSeconds = [Math]::Round($elapsed, 1); Polls = $polls } } }
        & $Sleep $PollSeconds
    }
}

function Invoke-CountdownGate {
    # Notify, then count down with the input watch. Proceed only when the countdown ran to zero with no input and at least one
    # visible warning was raised. $Notify is called as (stage, secondsLeft) and returns $true if something visible was shown.
    param([int]$Seconds = 600, [scriptblock]$TickProvider, [scriptblock]$Notify, [scriptblock]$Sleep, [scriptblock]$Clock, [scriptblock]$WindowCheck, [bool]$WindowStarted = $false, [int]$PollSeconds = 2, [long]$BaselineTick = -2)
    $baseline = $(if ($BaselineTick -ne -2) { $BaselineTick } else { [long](& $TickProvider) })   # -BaselineTick: the tick read at the idle gate
    if ($baseline -lt 0) { return [ordered]@{ Proceed = $false; Reason = 'the input clock could not be read: refusing'; ElapsedSeconds = 0 } }
    $shown = [bool](& $Notify 'start' $Seconds)
    if (-not $shown -and -not $WindowStarted) { return [ordered]@{ Proceed = $false; Reason = 'no visible warning could be raised (no toast, no window): refusing'; ElapsedSeconds = 0 } }
    $marks = New-Object System.Collections.ArrayList
    $onPoll = {
        param($elapsed)
        $left = $Seconds - $elapsed
        foreach ($m in @(300, 60)) { if ($left -le $m -and $Seconds -gt $m -and -not $marks.Contains($m)) { [void]$marks.Add($m); [void](& $Notify 'reminder' ([int]$left)) } }
        if ($WindowCheck) { $rc = & $WindowCheck; if ($null -ne $rc -and $rc -ne 0) { return $false } }
        return $true
    }.GetNewClosure()
    $w = Wait-WithInputWatch -Seconds $Seconds -BaselineTick $baseline -TickProvider $TickProvider -Sleep $Sleep -Clock $Clock -PollSeconds $PollSeconds -OnPoll $onPoll
    if ($w.Completed) { return [ordered]@{ Proceed = $true; Reason = "countdown of $Seconds s ran to zero with no input"; ElapsedSeconds = $w.ElapsedSeconds } }
    $why = if ($w.InputDetected) { "keyboard or mouse input after $($w.ElapsedSeconds) s: aborted" } elseif ($w.Stopped) { "STOP pressed or the window was closed after $($w.ElapsedSeconds) s: aborted" } else { 'aborted' }
    return [ordered]@{ Proceed = $false; Reason = $why; ElapsedSeconds = $w.ElapsedSeconds }
}

# ---- real providers (visible; not exercised by the self-test) ---------------------------------------------------------------
function Show-ToastNotification {
    # Raised from Windows PowerShell 5.1 (the only host with the Windows Runtime projection) under PowerShell's own identity.
    # Returns $true when the helper process exited 0. That does NOT prove a toast was seen (notifications off, Focus Assist): the gate counts it as
    # one visible channel, the window as the other, and refuses when neither exists; it cannot know that either was looked at.
    param([string]$Title, [string]$Body)
    $xmlText = '<toast scenario="reminder"><visual><binding template="ToastGeneric"><text>{0}</text><text>{1}</text></binding></visual></toast>' -f [Security.SecurityElement]::Escape($Title), [Security.SecurityElement]::Escape($Body)
    $cmd = @"
[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null
[Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime] | Out-Null
`$xml = New-Object Windows.Data.Xml.Dom.XmlDocument
`$xml.LoadXml('$($xmlText.Replace("'", "''"))')
`$toast = New-Object Windows.UI.Notifications.ToastNotification `$xml
[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\WindowsPowerShell\v1.0\powershell.exe').Show(`$toast)
"@
    try {
        $p = Start-Process -FilePath "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe" -ArgumentList '-NoProfile', '-NonInteractive', '-WindowStyle', 'Hidden', '-Command', $cmd -PassThru -WindowStyle Hidden -Wait
        return ($p.ExitCode -eq 0)
    } catch { return $false }
}

function Start-CountdownWindow {
    # The always-on-top countdown window with a STOP button: tools/probes/containment_arms/countdown_gate.ps1 (PowerShell 7).
    # Returns the process, or $null when pwsh or the script is not there (the toast alone then has to carry the warning).
    # NOTE: a started window is not proof it is visible; the gate treats the window's own exit code (1 STOP, 2 could not be shown) as an abort.
    param([string]$ScriptPath, [int]$Seconds, [string]$Title, [string]$Message)
    $pw = Get-Command pwsh.exe -ErrorAction SilentlyContinue
    if (-not $pw -or -not $ScriptPath -or -not (Test-Path -LiteralPath $ScriptPath)) { return $null }
    try { return (Start-Process -FilePath $pw.Source -ArgumentList @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', "`"$ScriptPath`"", '-Seconds', "$Seconds", '-NoToast', '-Title', "`"$Title`"", '-Message', "`"$Message`"") -PassThru) } catch { return $null }
}

# ---- self-test (fakes; changes nothing) --------------------------------------------------------------------------------------
function Invoke-IdleGateSelfTest {
    # Returns the number of failed checks; prints one line per check.
    $f = 0
    function Chk2([string]$n, [bool]$c) { if ($c) { Write-Host "  [PASS] $n" -ForegroundColor Green } else { Write-Host "  [FAIL] $n" -ForegroundColor Red; $script:IdleSelfFail++ } }
    $script:IdleSelfFail = 0
    Write-Host '== idle gate and countdown gate (fake providers) ==' -ForegroundColor Cyan
    Chk2 'idle: 1800 s needed; 1799 refuses, 1800 passes, 99999 passes' ((-not (Test-IdleSufficient 1799 1800)) -and (Test-IdleSufficient 1800 1800) -and (Test-IdleSufficient 99999 1800))
    Chk2 'idle: an unreadable idle time (-1) refuses even against a requirement of 0' (-not (Test-IdleSufficient -1 0))
    Chk2 'gate: 600 s idle refuses with the reason; 2400 s passes; -1 refuses saying it could not be read' ((-not (Invoke-IdleGate -RequiredSeconds 1800 -IdleProvider { 600 }).Ok) -and ((Invoke-IdleGate -RequiredSeconds 1800 -IdleProvider { 600 }).Reason -match 'only 600') -and (Invoke-IdleGate -RequiredSeconds 1800 -IdleProvider { 2400 }).Ok -and ((Invoke-IdleGate -RequiredSeconds 1800 -IdleProvider { -1 }).Reason -match 'could not be read'))
    Chk2 'session: only an interactive session above 0 can see the operator''s input (session 0 or non-interactive reads as unreadable)' ((Test-InteractiveSession 1 $true) -and -not (Test-InteractiveSession 0 $true) -and -not (Test-InteractiveSession 1 $false))
    $gi = Invoke-IdleGate -RequiredSeconds 1800 -IdleProvider { 2400 } -TickProvider { 4242 }
    Chk2 'idle gate returns the last-input tick it read: the baseline for the countdown and the pending-restart watch' (($gi.Ok -eq $true) -and ($gi.LastInputTick -eq 4242))
    Chk2 'input: the same tick is no input; a moved tick is; an unreadable tick on either side counts as input' ((-not (Test-InputOccurred 500 500)) -and (Test-InputOccurred 500 900) -and (Test-InputOccurred -1 500) -and (Test-InputOccurred 500 -1))
    $sd = Get-ShutdownArgs -DelaySeconds 600 -Comment 'arm 3b'
    Chk2 'shutdown arguments: /r /t 600 /c "arm 3b" exactly, no /f passed (the module header states that /t above 0 implies /f anyway)' ((($sd -join ' ') -eq '/r /t 600 /c arm 3b') -and ($sd -notcontains '/f') -and ((Get-ShutdownArgs).Count -eq 5))
    Chk2 'shutdown delay below 60 s or above 3600 s is rejected' (($(try { [void](Get-ShutdownArgs -DelaySeconds 30); $false } catch { $true })) -and ($(try { [void](Get-ShutdownArgs -DelaySeconds 3601); $false } catch { $true })))
    # a fake world: a clock that only Sleep advances, and an input tick that a script can move
    $mkWorld = {
        param([int[]]$InputAtPolls)
        $w = @{ t = [datetime]'2026-10-11T12:00:00'; poll = 0; tick = 1000; notes = (New-Object System.Collections.ArrayList); at = $InputAtPolls }
        $w.Clock = { $w.t }.GetNewClosure()
        $w.Sleep = { param($s) $w.t = $w.t.AddSeconds($s) }.GetNewClosure()
        $w.TickFn = { $w.poll++; if ($w.at -contains $w.poll) { $w.tick += 777 }; $w.tick }.GetNewClosure()
        $w.Notify = { param($stage, $left) [void]$w.notes.Add("$stage@$left"); $true }.GetNewClosure()
        $w
    }
    $w1 = & $mkWorld @()
    $r1 = Invoke-CountdownGate -Seconds 600 -TickProvider $w1.TickFn -Notify $w1.Notify -Sleep $w1.Sleep -Clock $w1.Clock
    Chk2 'countdown: 600 s with no input proceeds, after 600 s of fake time, with a start toast and reminders at 300 s and 60 s left' (($r1.Proceed -eq $true) -and ($r1.ElapsedSeconds -ge 600) -and ($w1.notes[0] -eq 'start@600') -and (@($w1.notes | Where-Object { $_ -like 'reminder@*' }).Count -eq 2))
    $w2 = & $mkWorld @(50)
    $r2 = Invoke-CountdownGate -Seconds 600 -TickProvider $w2.TickFn -Notify $w2.Notify -Sleep $w2.Sleep -Clock $w2.Clock
    Chk2 'countdown: input on the 50th poll (about 100 s in) aborts at once, with the reason' (($r2.Proceed -eq $false) -and ($r2.ElapsedSeconds -lt 120) -and ($r2.Reason -match 'input'))
    $w3 = & $mkWorld @(2)
    $r3 = Invoke-CountdownGate -Seconds 600 -TickProvider $w3.TickFn -Notify $w3.Notify -Sleep $w3.Sleep -Clock $w3.Clock
    Chk2 'countdown: input on the very first poll aborts' (($r3.Proceed -eq $false) -and ($r3.ElapsedSeconds -le 2))
    $wB = & $mkWorld @()
    $rB = Invoke-CountdownGate -Seconds 600 -TickProvider $wB.TickFn -BaselineTick 5 -Notify $wB.Notify -Sleep $wB.Sleep -Clock $wB.Clock
    Chk2 'countdown with the idle gate''s baseline: input that happened BEFORE the countdown started (tick differs from the baseline) aborts at once' (($rB.Proceed -eq $false) -and ($rB.ElapsedSeconds -le 2) -and ($rB.Reason -match 'input'))
    $w4 = & $mkWorld @()
    $r4 = Invoke-CountdownGate -Seconds 600 -TickProvider $w4.TickFn -Notify { param($a, $b) $false } -Sleep $w4.Sleep -Clock $w4.Clock
    Chk2 'countdown: if no toast and no window could be shown it refuses before counting' (($r4.Proceed -eq $false) -and ($r4.Reason -match 'no visible warning') -and ($r4.ElapsedSeconds -eq 0))
    $w5 = & $mkWorld @()
    $r5 = Invoke-CountdownGate -Seconds 600 -TickProvider $w5.TickFn -Notify { param($a, $b) $false } -Sleep $w5.Sleep -Clock $w5.Clock -WindowStarted $true
    Chk2 'countdown: a window alone (toast failed) is a visible warning and may proceed' ($r5.Proceed -eq $true)
    $w6 = & $mkWorld @()
    $r6 = Invoke-CountdownGate -Seconds 600 -TickProvider { -1 } -Notify $w6.Notify -Sleep $w6.Sleep -Clock $w6.Clock
    Chk2 'countdown: an unreadable input clock refuses' (($r6.Proceed -eq $false) -and ($r6.Reason -match 'could not be read'))
    $w7 = & $mkWorld @()
    $script:winCalls = 0
    $r7 = Invoke-CountdownGate -Seconds 600 -TickProvider $w7.TickFn -Notify $w7.Notify -Sleep $w7.Sleep -Clock $w7.Clock -WindowStarted $true -WindowCheck { $script:winCalls++; if ($script:winCalls -ge 20) { 1 } else { $null } }
    Chk2 'countdown: the window reporting STOP (exit 1) aborts' (($r7.Proceed -eq $false) -and ($r7.Reason -match 'STOP'))
    $w8 = & $mkWorld @(); $script:winCalls = 0
    $r8 = Invoke-CountdownGate -Seconds 600 -TickProvider $w8.TickFn -Notify $w8.Notify -Sleep $w8.Sleep -Clock $w8.Clock -WindowStarted $true -WindowCheck { 2 }
    Chk2 'countdown: the window reporting it could not be shown (exit 2) aborts' ($r8.Proceed -eq $false)
    $w9 = & $mkWorld @(40)
    $r9 = Wait-WithInputWatch -Seconds 600 -BaselineTick ([long](& $w9.TickFn)) -TickProvider $w9.TickFn -Sleep $w9.Sleep -Clock $w9.Clock
    Chk2 'input watch: a 600 s wait completes only if no input; input at poll 40 ends it early' (($r9.Completed -eq $false) -and ($r9.InputDetected -eq $true) -and ($r9.ElapsedSeconds -lt 600))
    $w10 = & $mkWorld @()
    $r10 = Wait-WithInputWatch -Seconds 120 -BaselineTick ([long](& $w10.TickFn)) -TickProvider $w10.TickFn -Sleep $w10.Sleep -Clock $w10.Clock
    Chk2 'input watch: a quiet 120 s wait completes' (($r10.Completed -eq $true) -and ($r10.Polls -gt 30))
    Chk2 'real input clock is readable on this host or reports -1 (never throws)' ((Get-LastInputTick) -isnot [string])
    return $script:IdleSelfFail
}
