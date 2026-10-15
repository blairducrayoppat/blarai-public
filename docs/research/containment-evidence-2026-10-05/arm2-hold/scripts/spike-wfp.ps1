#requires -Version 5.1
<#
.SYNOPSIS
  #1689 spike, operator side: Test A (GPU feasibility, no network block) and Test B (a raw WFP block keyed to
  blarai-spike while the task serves a completion over loopback). Wraps - never modifies - the validated #1671
  script C:\Users\_OPERATOR_\blarai-research-data\wfp-spike\wfp-coder-egress-spike.ps1: its embedded C# (the WFP
  structs, the per-SID security descriptor, the dynamic-session engine with dead-man) and a handful of its helper
  functions are extracted from that file with the PowerShell parser at run time and evaluated here, so the exact
  code that observed enforcement under Bitdefender is what runs. Extraction fails loudly if a name is missing.

.DESCRIPTION
  Modes (exactly one):
    -SelfTest  pure only: extraction, C# compile (in-process), SD/plan invariants for a fabricated SID, SID-safety
               refusals, verdict table, result-schema use. No system change.
    -DryRun    prints the plan and the exact sequence; resolves the spike SID read-only; adds nothing.
    -TestA     feasibility run of the task, NO block. Elevated. Result validated against the strict schema.
    -TestB     start the dynamic WFP block keyed to blarai-spike (+ dead-man), start the task in serve mode, connect
               from the operator account to the loopback port and request a completion, confirm the spike's own
               outbound probe was blocked, release the block, verify removal. Elevated. Operator-traffic watchdog
               (2 consecutive failed connects to 1.1.1.1:443 = remove everything, exit 3).
    -TestC     the account as CLIENT (arm 1): the OPERATOR starts spike_model.py in serve mode (the real local model
               server, bound to 127.0.0.1); the task runs in client mode THREE times in one invocation: before the
               filters (baseline: its POST must succeed and its egress must be open), under a fresh dynamic block,
               and after the engine is closed (egress must be open again). Each invocation is one engine session.
               -NoLoopbackPermit installs the TWO block filters only (V4 + V6), so the loopback permit's role is
               measured by comparing invocations with and without it; the result records which set was installed.
               Everything else (dynamic session, dead-man, watchdog, removal check) is as in -TestB.

    -LongHold  (arm 2) the long hold: ONE dynamic engine session holds the block for -HoldSeconds (60..7200, dead-man
               at HoldSeconds+30) while the OPERATOR starts the task in probe mode once per -SampleSeconds (default
               60) and writes one timestamped line per sample to <run>-samples.txt; the operator watchdog runs every
               2 s (two consecutive failures = remove everything, exit 3); `netsh wfp show filters` is exported at
               the start, at HoldSeconds/2, before close (and at once on the first sample that is not blocked) and
               searched for the 'BlarAI #1671' marker and every filter key; Bitdefender processes and install-folder
               timestamps are recorded at start and end; removal is verified and the account's egress must be open
               again. `wsl --shutdown` runs first and is recorded. -NoLoopbackPermit selects the two-filter set.

  EXIT CODES for -LongHold: 0 every valid sample blocked for the whole hold, filters in every export, removal verified;
    1 at least one sample was NOT blocked (the block did not hold: a result); 2 precondition; 3 operator traffic
    affected (aborted, removed) or the target SID is the operator's or one of his groups (refused, nothing added);
    4 inconclusive (engine closed early, too few valid samples, an export missing a filter); 5 no baseline; 7 removal
    NOT verified.

  EXIT CODES for -TestC: 0 valid run, client POST succeeded under the block; 9 valid run, client POST FAILED under
    the block (a result, not an error); 1 account NOT blocked; 8 the server's model did not load (not a counted run);
    2/3/4/5/7 as below (5 also when the account's baseline POST failed or its egress was already blocked).

  SAFETY (inherited from the wrapped script, re-asserted here)
    * Every WFP object lives in a DYNAMIC session: closing the engine handle OR this process dying removes the
      provider, sublayer and all four filters. A timer thread closes the handle at BlockMaxSeconds+30 regardless.
    * Every filter carries the ALE_USER_ID condition for the spike SID; the SID must be an account-domain user SID
      that is not the operator's and not a group of the operator token.
    * No filter is added before the operator baseline (3 x 1.1.1.1:443) succeeds.
    * No model is touched unless free RAM >= 14 GB (enforced inside the task and checked here first).

  EXIT CODES
    0 spike blocked, model served a completion to the operator, operator unaffected, removal verified
    8 spike blocked and listener reachable, but the model did NOT load on the GPU (the make-or-break finding)
    1 spike outbound NOT blocked with the filters live
    2 precondition / argument failure (nothing added)    3 operator traffic affected (aborted, removed)
    4 inconclusive (task not started, no valid result, wrong SID, listener not reached, operator completion failed)
    5 no baseline (operator offline, filters absent check failed, or spike already blocked)   7 removal NOT verified
  TestA exits 0 when the schema-valid result has overall pass, 8 when only gpu_feasibility failed, else 4.
#>
[CmdletBinding()]
param(
    [switch]$SelfTest,
    [switch]$DryRun,
    [switch]$TestA,
    [switch]$TestB,
    [switch]$TestC,
    [switch]$NoLoopbackPermit,
    [switch]$LongHold,
    [int]$HoldSeconds = 3600,
    [int]$SampleSeconds = 60,
    [string]$HoldOutDir = 'C:\Users\_OPERATOR_\blarai-research-data\arm2-hold',
    [int]$ServerLoadTimeoutSeconds = 240,
    [int]$BlockMaxSeconds = 420,
    [int]$ServeHoldSeconds = 60,
    [int]$ResultTimeoutSeconds = 900,
    [string]$WfpScript = 'C:\Users\_OPERATOR_\blarai-research-data\wfp-spike\wfp-coder-egress-spike.ps1',
    [string]$OutDir = 'C:\Users\_OPERATOR_\blarai-research-data\confined-model-spike\runs'
)
$ErrorActionPreference = 'Stop'
. "$PSScriptRoot\spike-lib.ps1"

# ---- reuse the wrapped script without modifying or executing it ---------------------------------------------------
$script:WrappedFunctions = @('Initialize-WfpType', 'Test-CoderSidSafe', 'Test-TcpConnect', 'Test-IsElevated', 'Get-OperatorTokenSids', 'Invoke-ReadOnlyEngineCheck', 'Get-EnvSnapshot')

function Import-WfpHelpers {
    param([Parameter(Mandatory)][string]$Path)
    if (-not (Test-Path -LiteralPath $Path)) { throw "wrapped script not found: $Path" }
    $tokens = $null; $errs = $null
    $ast = [Management.Automation.Language.Parser]::ParseFile($Path, [ref]$tokens, [ref]$errs)
    if ($errs -and $errs.Count) { throw "wrapped script does not parse: $($errs[0].Message)" }
    $assign = $ast.FindAll({ param($n) $n -is [Management.Automation.Language.AssignmentStatementAst] -and $n.Left.Extent.Text -eq '$csharp' }, $true) | Select-Object -First 1
    if (-not $assign) { throw 'wrapped script has no $csharp assignment' }
    $script:csharp = & ([scriptblock]::Create($assign.Right.Extent.Text))
    if (-not ($script:csharp -is [string]) -or $script:csharp -notmatch 'namespace BlarAI\.Wfp') { throw 'extracted $csharp is not the WFP type source' }
    $found = @()
    foreach ($name in $script:WrappedFunctions) {
        $fn = $ast.FindAll({ param($n) $n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq $name }, $true) | Select-Object -First 1
        if (-not $fn) { throw "wrapped script has no function $name" }
        Set-Item -Path ("Function:script:$name") -Value $fn.Body.GetScriptBlock()   # define it at SCRIPT scope (a dot-source here would be function-local)
        $found += $name
    }
    $sha = [Security.Cryptography.SHA256]::Create(); try { $hash = ([BitConverter]::ToString($sha.ComputeHash([IO.File]::ReadAllBytes($Path)))) -replace '-', '' } finally { $sha.Dispose() }
    return [pscustomobject]@{ Path = $Path; Sha256 = $hash; Functions = $found; CsharpChars = $script:csharp.Length }
}

# ---- pure helpers -------------------------------------------------------------------------------------------------
function Test-WfpArgs {
    param([bool]$SelfTest, [bool]$DryRun, [bool]$TestA, [bool]$TestB, [int]$BlockMax, [int]$ServeHold, [int]$ResultTimeout, [bool]$TestC = $false, [bool]$NoPermit = $false, [int]$ServerLoadTimeout = 240, [bool]$LongHold = $false, [int]$Hold = 3600, [int]$Sample = 60)
    $e = New-Object System.Collections.ArrayList
    $modes = @($SelfTest, $DryRun, $TestA, $TestB, $TestC, $LongHold) | Where-Object { $_ }
    if (@($modes).Count -ne 1) { [void]$e.Add('choose exactly one of -SelfTest, -DryRun, -TestA, -TestB, -TestC, -LongHold') }
    if ($LongHold) {
        if ($Hold -lt 60 -or $Hold -gt 7200) { [void]$e.Add("HoldSeconds must be 60..7200 (got $Hold)") }
        if ($Sample -lt 30 -or $Sample -gt 300) { [void]$e.Add("SampleSeconds must be 30..300 (got $Sample)") }
        if ($Sample -gt $Hold) { [void]$e.Add('SampleSeconds must not exceed HoldSeconds') }
    }
    if ($NoPermit -and ($TestA -or $TestB)) { [void]$e.Add('-NoLoopbackPermit applies to -TestC (and is printed by -DryRun); -TestA/-TestB always install the four-filter set') }
    if ($ServerLoadTimeout -lt 30 -or $ServerLoadTimeout -gt 900) { [void]$e.Add("ServerLoadTimeoutSeconds must be 30..900 (got $ServerLoadTimeout)") }
    if ($BlockMax -lt 60 -or $BlockMax -gt 900) { [void]$e.Add("BlockMaxSeconds must be 60..900 (got $BlockMax)") }
    if ($ServeHold -lt 10 -or $ServeHold -gt 300) { [void]$e.Add("ServeHoldSeconds must be 10..300 (got $ServeHold)") }
    if ($ServeHold -ge $BlockMax) { [void]$e.Add('ServeHoldSeconds must be < BlockMaxSeconds (the block must outlast the serve window)') }
    if ($ResultTimeout -lt 60 -or $ResultTimeout -gt 3600) { [void]$e.Add("ResultTimeoutSeconds must be 60..3600 (got $ResultTimeout)") }
    return @($e)
}

function Get-TestBVerdict {
    # PURE. Precedence is safety-first, as in the wrapped script: operator impact, unverified removal, no baseline,
    # inconclusive states, then the answers.
    param([Parameter(Mandatory)]$Obs)
    if ($Obs.OperatorAbort)        { return [pscustomobject]@{ Code = 3; Reason = 'operator traffic affected (watchdog abort)' } }
    if (-not $Obs.RemovalVerified) { return [pscustomobject]@{ Code = 7; Reason = 'removal NOT verified' } }
    if (-not $Obs.BaselineOk)      { return [pscustomobject]@{ Code = 5; Reason = 'no baseline (operator offline / stale WFP objects / spike already blocked)' } }
    if ([int]$Obs.OperatorFailures -gt 0) { return [pscustomobject]@{ Code = 4; Reason = 'inconclusive: isolated operator connect failure(s) during the block' } }
    if (-not $Obs.TaskStarted)     { return [pscustomobject]@{ Code = 4; Reason = 'inconclusive: the task never started' } }
    if (-not $Obs.ResultValid)     { return [pscustomobject]@{ Code = 4; Reason = 'inconclusive: no schema-valid result from the task' } }
    if (-not $Obs.SidIsSpike)      { return [pscustomobject]@{ Code = 4; Reason = 'inconclusive: the task did not run as the spike SID' } }
    if (-not $Obs.SpikeOutboundBlocked) { return [pscustomobject]@{ Code = 1; Reason = 'spike NOT blocked: the WFP block did not enforce for this account' } }
    if (-not $Obs.ServeStarted)    { return [pscustomobject]@{ Code = 4; Reason = 'inconclusive: the listener never started' } }
    if (-not $Obs.OperatorReachedListener) { return [pscustomobject]@{ Code = 4; Reason = 'inconclusive: the operator could not reach the loopback listener' } }
    if (-not $Obs.ModelLoaded)     { return [pscustomobject]@{ Code = 8; Reason = 'blocked and reachable, but the model did NOT load on the GPU for this account' } }
    if (-not $Obs.OperatorGotModelCompletion) { return [pscustomobject]@{ Code = 4; Reason = 'inconclusive: model loaded but the operator got no model completion' } }
    return [pscustomobject]@{ Code = 0; Reason = 'spike blocked, model completion served over loopback, operator unaffected, removal verified' }
}

function Get-ArmPlan {
    # The #1671 plan (4 filters) or, with -NoLoopbackPermit, the same plan with the two PERMIT filters removed from
    # the list in PowerShell: the wrapped C# is still read, never edited, and the block filters are byte-identical.
    param([Parameter(Mandatory)][string]$Sid, [bool]$PermitOn = $true)
    $plan = [BlarAI.Wfp.Plan]::Build($Sid)
    if (-not $PermitOn) {
        $keep = New-Object 'System.Collections.Generic.List[BlarAI.Wfp.FilterSpec]'
        foreach ($f in $plan.Filters) { if ($f.Action -eq [BlarAI.Wfp.Plan]::FWP_ACTION_BLOCK) { $keep.Add($f) } }
        $plan.Filters = $keep
    }
    return $plan
}

function Test-ArmPlanInvariants {
    # PURE. Problems with a plan for the named filter set (empty = fine). Every filter must carry the user condition
    # (the C# always adds it); the permit-off set must be exactly the two BLOCK filters and carry no loopback flag.
    param([Parameter(Mandatory)]$Plan, [bool]$PermitOn = $true)
    $e = New-Object System.Collections.ArrayList
    $blocks = @($Plan.Filters | Where-Object { $_.Action -eq [BlarAI.Wfp.Plan]::FWP_ACTION_BLOCK })
    $permits = @($Plan.Filters | Where-Object { $_.Action -eq [BlarAI.Wfp.Plan]::FWP_ACTION_PERMIT })
    if ($blocks.Count -ne 2) { [void]$e.Add("expected 2 block filters, got $($blocks.Count)") }
    if (@($blocks | Where-Object { $_.Loopback }).Count) { [void]$e.Add('a block filter carries the loopback condition') }
    if ($PermitOn) {
        if ($permits.Count -ne 2) { [void]$e.Add("permit on: expected 2 permit filters, got $($permits.Count)") }
        if (@($permits | Where-Object { -not $_.Loopback }).Count) { [void]$e.Add('a permit filter lacks the loopback condition') }
    } else {
        if ($permits.Count -ne 0) { [void]$e.Add("permit off: expected 0 permit filters, got $($permits.Count)") }
        if ($Plan.Filters.Count -ne 2) { [void]$e.Add("permit off: expected exactly 2 filters, got $($Plan.Filters.Count)") }
    }
    return @($e)
}

function Get-TestCVerdict {
    # PURE. Safety first as in Test B; then the two observations the arm exists for. Both client outcomes under the
    # block are RESULTS (0 and 9); only the account being unblocked (1) or the server lacking its model (8) are not.
    param([Parameter(Mandatory)]$Obs)
    if ($Obs.OperatorAbort)        { return [pscustomobject]@{ Code = 3; Reason = 'operator traffic affected (watchdog abort)' } }
    if (-not $Obs.RemovalVerified) { return [pscustomobject]@{ Code = 7; Reason = 'removal NOT verified (objects left, operator connect failed, or the account''s egress did not reopen)' } }
    if (-not $Obs.BaselineOk)      { return [pscustomobject]@{ Code = 5; Reason = 'no baseline (operator offline / stale WFP objects / account baseline POST failed or egress already blocked)' } }
    if (-not $Obs.ServerModelLoaded) { return [pscustomobject]@{ Code = 8; Reason = 'the operator-run server did not load its model: not a counted run' } }
    if ([int]$Obs.OperatorFailures -gt 0) { return [pscustomobject]@{ Code = 4; Reason = 'inconclusive: isolated operator connect failure(s) during the block' } }
    if (-not $Obs.BlockRunValid)   { return [pscustomobject]@{ Code = 4; Reason = 'inconclusive: the account run under the block did not start, gave no schema-valid result, or ran as the wrong SID' } }
    if (-not $Obs.AfterRunValid)   { return [pscustomobject]@{ Code = 4; Reason = 'inconclusive: the account run after removal gave no valid result, so its egress reopening was not observed' } }
    if (-not $Obs.SpikeOutboundBlocked) { return [pscustomobject]@{ Code = 1; Reason = 'account NOT blocked: its outbound connect succeeded with the filters live' } }
    if ($Obs.ClientOkUnderBlock)   { return [pscustomobject]@{ Code = 0; Reason = 'valid run: account blocked outbound, its loopback POST to the real server SUCCEEDED' } }
    if ($Obs.ClientSocketDenied)   { return [pscustomobject]@{ Code = 9; Reason = 'valid run: account blocked outbound, its loopback POST to the real server FAILED at the socket (a Windows socket error code was recorded)' } }
    return [pscustomobject]@{ Code = 4; Reason = 'inconclusive: the loopback POST failed WITHOUT a socket-level error (server-side failure or timeout), so the filters cannot be blamed' }
}

function Get-TestAVerdict {
    param([Parameter(Mandatory)]$Result, [string[]]$SchemaViolations)
    if ($SchemaViolations -and $SchemaViolations.Count) { return [pscustomobject]@{ Code = 4; Reason = 'result failed the strict schema: ' + ($SchemaViolations -join '; ') } }
    $bad = @($Result.steps | Where-Object { $_.status -in @('fail', 'error') } | ForEach-Object { $_.name })
    if ($bad.Count -eq 0) { return [pscustomobject]@{ Code = 0; Reason = 'all steps passed' } }
    if ($bad.Count -eq 1 -and $bad[0] -eq 'gpu_feasibility') { return [pscustomobject]@{ Code = 8; Reason = 'only gpu_feasibility failed: the GPU/model is not usable by this account (see the error text in the result)' } }
    return [pscustomobject]@{ Code = 4; Reason = 'failed steps: ' + ($bad -join ', ') }
}

function Invoke-LoopbackCompletion {
    param([int]$Port, [string]$Prompt = 'Reply with one short sentence confirming you are running in a confined account.', [int]$MaxNewTokens = 32, [int]$TimeoutMs = 120000)
    $sw = [Diagnostics.Stopwatch]::StartNew()
    try {
        $req = [Net.WebRequest]::Create("http://127.0.0.1:$Port/")
        $req.Method = 'POST'; $req.ContentType = 'application/json'; $req.Timeout = $TimeoutMs; $req.ReadWriteTimeout = $TimeoutMs
        $bytes = (New-Object Text.UTF8Encoding($false)).GetBytes((ConvertTo-Json -InputObject ([ordered]@{ prompt = $Prompt; max_new_tokens = $MaxNewTokens }) -Compress))
        $req.ContentLength = $bytes.Length
        $s = $req.GetRequestStream(); $s.Write($bytes, 0, $bytes.Length); $s.Close()
        $resp = $req.GetResponse(); $rd = New-Object IO.StreamReader($resp.GetResponseStream()); $body = $rd.ReadToEnd(); $rd.Close(); $resp.Close()
        $j = $null; try { $j = ConvertFrom-Json $body } catch {}
        return [ordered]@{ ok = $true; status = 200; ms = $sw.ElapsedMilliseconds; model_loaded = [bool]($j -and $j.model_loaded); completion = $(if ($j) { [string]$j.completion } else { '' }); body = $body; error = ''; t = (Get-Date).ToString("yyyy-MM-dd'T'HH:mm:ss.fffzzz") }
    } catch {
        return [ordered]@{ ok = $false; status = 0; ms = $sw.ElapsedMilliseconds; model_loaded = $false; completion = ''; body = ''; error = $_.Exception.Message; t = (Get-Date).ToString("yyyy-MM-dd'T'HH:mm:ss.fffzzz") }
    }
}

# ---- task driver --------------------------------------------------------------------------------------------------
function Get-SpikeSidOrNull { try { return (Get-LocalUser -Name $script:SpikeUser -ErrorAction Stop).SID.Value } catch { return $null } }

function Start-SpikeTaskProved {
    # Start + prove it actually started (a password task whose account lacks SeBatchLogonRight stays Ready and never
    # runs: 0x41303). Returns @{ Started; Detail }. $Tick is the operator watchdog, run between polls.
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
        if ($Tick) { & $Tick; if ($script:opAbort) { return $null } }   # the watchdog closed the engine: stop waiting
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

function Get-ArmEnvSnapshot {
    # The wrapped snapshot (clock, uptime, OS, Bitdefender processes, firewall profiles, BFE/mpssvc) plus what the
    # arm's conditions need: WSL state, the exact Windows build and the PowerShell host.
    $snap = Get-EnvSnapshot
    try { $cv = Get-ItemProperty 'HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion'; $snap.windows_build = "$($cv.CurrentBuild).$($cv.UBR) ($($cv.DisplayVersion))" } catch { $snap.windows_build = "error: $($_.Exception.Message)" }
    $snap.ps_host = "$($Host.Name) $($PSVersionTable.PSVersion) ($($PSVersionTable.PSEdition))"
    try {
        $raw = (& wsl.exe --list --verbose 2>&1 | Out-String) -replace "`0", ''
        $snap.wsl_state = @($raw -split "`r?`n" | ForEach-Object { ($_ -replace '\s+', ' ').Trim() } | Where-Object { $_ })
    } catch { $snap.wsl_state = "error: $($_.Exception.Message)" }
    return $snap
}

# ---- Test C helpers: the operator-run server and the account's client runs -----------------------------------------
function Start-OperatorServer {
    # spike_model.py in serve mode AS THE OPERATOR from the spike venv: the real local model server, bound to
    # 127.0.0.1 on an ephemeral port it reports in a port file (operator-owned folder; read through the strict reader
    # anyway). Returns the process and what the report needs, or throws (no server = no run).
    param([string]$RunId, [int]$HoldSeconds, [int]$LoadTimeoutSeconds)
    $dir = Join-Path $OutDir 'server'; New-Item -ItemType Directory -Force $dir | Out-Null
    $py = Join-Path $script:SpikeVenv 'Scripts\python.exe'
    $model = Join-Path $PSScriptRoot 'spike_model.py'
    foreach ($f in @($py, $model)) { if (-not (Test-Path -LiteralPath $f)) { throw "server prerequisite missing: $f" } }
    $outJson = Join-Path $dir "server-$RunId.json"; $portFile = Join-Path $dir "server-port-$RunId.json"; $stopFile = Join-Path $dir "server-stop-$RunId.flag"
    $argv = @($model, '--mode', 'serve', '--model-dir', $script:SpikeModelDir, '--out-json', $outJson, '--port-file', $portFile, '--stop-file', $stopFile,
              '--run-id', $RunId, '--hold', "$HoldSeconds", '--outbound', '1.1.1.1:443')
    $argLine = ($argv | ForEach-Object { if ($_ -match '[\s"]') { '"' + ($_ -replace '"', '\"') + '"' } else { $_ } }) -join ' '
    $t0 = (Get-Date).ToString("yyyy-MM-dd'T'HH:mm:ss.fffzzz")
    $p = Start-Process -FilePath $py -ArgumentList $argLine -WorkingDirectory $dir -PassThru -WindowStyle Hidden `
         -RedirectStandardOutput (Join-Path $dir "server-$RunId.stdout.txt") -RedirectStandardError (Join-Path $dir "server-$RunId.stderr.txt")
    $deadline = (Get-Date).AddSeconds($LoadTimeoutSeconds); $info = $null
    while ((Get-Date) -lt $deadline) {
        if ($p.HasExited) { break }
        if (Test-PathExistsNoFollow $portFile) { Start-Sleep -Milliseconds 300; $info = Read-UntrustedJson -Path $portFile -MaxBytes 65536; break }
        Start-Sleep -Milliseconds 1000
    }
    if (-not $info) {
        if (-not $p.HasExited) { try { & taskkill.exe /PID $p.Id /T /F 2>&1 | Out-Null } catch {} }
        $err = ''; try { $err = Get-Content -LiteralPath (Join-Path $dir "server-$RunId.stderr.txt") -Raw -ErrorAction SilentlyContinue } catch {}
        throw "the operator-run server wrote no port file within $LoadTimeoutSeconds s (exited=$($p.HasExited)); stderr tail: " + $(if ($err) { $err.Substring([Math]::Max(0, $err.Length - 600)) } else { '(none)' })
    }
    if (-not (Test-LoopbackPort $info.port)) { try { & taskkill.exe /PID $p.Id /T /F 2>&1 | Out-Null } catch {}; throw "refusing the server port file: port '$($info.port)' is not an integer in 1024..65535" }
    if ([string]$info.host -ne '127.0.0.1') { try { & taskkill.exe /PID $p.Id /T /F 2>&1 | Out-Null } catch {}; throw "refusing the server: bound to '$($info.host)', not 127.0.0.1" }
    $health = $null
    try { $wr = [Net.WebRequest]::Create("http://127.0.0.1:$($info.port)/"); $wr.Timeout = 10000; $r = $wr.GetResponse(); $rd = New-Object IO.StreamReader($r.GetResponseStream()); $health = ConvertFrom-Json $rd.ReadToEnd(); $rd.Close(); $r.Close() } catch { $health = [ordered]@{ ok = $false; error = $_.Exception.Message } }
    return [pscustomobject]@{ Process = $p; Pid = $p.Id; Port = [int]$info.port; Bind = "127.0.0.1:$($info.port)"; ModelLoaded = [bool]$info.model_loaded; Started = $t0; PortFileAt = [string]$info.t
                              OutJson = $outJson; PortFile = $portFile; StopFile = $stopFile; Health = $health; Type = 'spike_model.py --mode serve, run as the operator from the spike venv' }
}

function Stop-OperatorServer {
    # Ask the server to stop (stop file), wait for its result JSON (request log, pid, stop reason); kill only if it ignores the file.
    param([Parameter(Mandatory)]$Server, [int]$WaitSeconds = 45)
    $t0 = (Get-Date).ToString("yyyy-MM-dd'T'HH:mm:ss.fffzzz")
    try { [IO.File]::WriteAllText($Server.StopFile, "stop $t0") } catch {}
    $exited = $Server.Process.WaitForExit($WaitSeconds * 1000)
    if (-not $exited) { try { & taskkill.exe /PID $Server.Pid /T /F 2>&1 | Out-Null } catch {} }
    $rec = $null
    if (Test-PathExistsNoFollow $Server.OutJson) { try { $rec = Read-UntrustedJson -Path $Server.OutJson } catch { $rec = "unreadable: $($_.Exception.Message)" } }
    return [ordered]@{ stop_requested = $t0; exited_within_wait = [bool]$exited; killed = (-not $exited); exit_code = $(if ($Server.Process.HasExited) { $Server.Process.ExitCode } else { $null }); server_result = $rec }
}

function Wait-SpikeTaskReady {
    # The one scheduled task runs three times per Test C invocation; a Start while it is still Running is ignored by
    # the scheduler (default MultipleInstances), so wait for Ready first. $Tick is the operator watchdog.
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

function Invoke-ClientTaskRun {
    # One run of the task in client mode (baseline, under the block, or after removal). Returns the observation the
    # verdict needs plus the full task result; never throws on a failed run (the verdict reads the fields).
    param([string]$RunId, [int]$Port, [bool]$ExpectedBlocked, [int]$TimeoutSec, [scriptblock]$Tick)
    $o = [ordered]@{ run_id = $RunId; expected_blocked = $ExpectedBlocked; started = (Get-Date).ToString("yyyy-MM-dd'T'HH:mm:ss.fffzzz"); task_ready = $false; task_started = $false; task_start = $null
                     valid = $false; schema_violations = @(); token_sid = $null; client_connect = $null; outbound_probe = $null; result = $null; finished = $null }
    $o.task_ready = Wait-SpikeTaskReady -Tick $Tick
    if ($o.task_ready) {
        $reqAt = [datetimeoffset]::Now
        Write-SpikeRequest -RunId $RunId -Mode 'client' -Hold 5 -ExpectedBlocked $ExpectedBlocked -ServerPort $Port
        $go = Start-SpikeTaskProved -Tick $Tick
        $o.task_start = $go; $o.task_started = [bool]$go.Started
        if ($go.Started) {
            $res = Wait-SpikeResult -RunId $RunId -TimeoutSec $TimeoutSec -Tick $Tick
            if (-not $res) { try { Stop-ScheduledTask -TaskPath $script:SpikeTaskPath -TaskName $script:SpikeTaskName } catch {} }
            else {
                $viol = @(Test-SpikeResultSchema $res)
                # A result file is account-written: one that predates this request (planted, or stale) is refused.
                try { if ((ConvertTo-DateTimeOffset $res.started) -lt $reqAt.AddSeconds(-5)) { $viol += "result.started $($res.started) predates the request written at $($reqAt.ToString('o'))" } } catch { $viol += "result.started unreadable: $($_.Exception.Message)" }
                if ([string]$res.run_id -ne $RunId) { $viol += "result.run_id '$($res.run_id)' is not '$RunId'" }
                $o.schema_violations = @($viol); $o.valid = ($viol.Count -eq 0 -and $res.mode -eq 'client')
                $id = $res.steps | Where-Object { $_.name -eq 'identity' } | Select-Object -First 1
                if ($id -and $id.data) { $o.token_sid = [string]$id.data.token_sid }
                $cc = $res.steps | Where-Object { $_.name -eq 'client_connect' } | Select-Object -First 1
                if ($cc) { $o.client_connect = $cc.data }
                $ob = $res.steps | Where-Object { $_.name -eq 'outbound_probe' } | Select-Object -First 1
                if ($ob) { $o.outbound_probe = $ob.data }
                $o.result = $res
            }
        }
    }
    $o.finished = (Get-Date).ToString("yyyy-MM-dd'T'HH:mm:ss.fffzzz")
    return $o
}

function Invoke-TestC {
    $problems = Assert-SpikePreflight
    if ($problems.Count) { $problems | ForEach-Object { Write-Host "FAIL: $_" -ForegroundColor Red }; return 2 }
    Initialize-WfpType
    $sid = Get-SpikeSidOrNull
    $permitOn = -not $NoLoopbackPermit.IsPresent
    $filterSet = $(if ($permitOn) { 'permit_on' } else { 'permit_off' })
    $runId = 'testc-' + $(if ($permitOn) { 'on-' } else { 'off-' }) + (Get-Date -Format 'yyyyMMdd-HHmmss')
    $report = [ordered]@{ spike = '#1689 arm 1: the confined account as CLIENT of a real local model server over loopback while its outbound connects are blocked; with or without the loopback permit filter'
                          run_id = $runId; filter_set = $filterSet; started = (Get-Date).ToString("yyyy-MM-dd'T'HH:mm:ss.fffzzz"); block_max_seconds = $BlockMaxSeconds
                          env = (Get-ArmEnvSnapshot); server = $null; steps = [ordered]@{} }
    $obs = @{ OperatorAbort = $false; RemovalVerified = $false; BaselineOk = $false; ServerModelLoaded = $false; OperatorFailures = 0; BlockRunValid = $false; AfterRunValid = $false; SpikeOutboundBlocked = $false; ClientOkUnderBlock = $false; ClientSocketDenied = $false }
    $engine = $null; $server = $null; $code = 4; $reason = 'error before decision'
    $watch = New-Object System.Collections.ArrayList; $script:consec = 0; $script:opAbort = $false
    try {
        Write-Host "== 0 preflight ($filterSet) ==" -ForegroundColor Cyan
        $pre = Invoke-ReadOnlyEngineCheck
        if ($pre.sublayer_present -or $pre.provider_present -or $pre.filters_present.Count) { Write-Host 'FAIL: WFP objects with these keys already exist (stale state or a concurrent run). Nothing added.' -ForegroundColor Red; return 2 }
        $plan = Get-ArmPlan -Sid $sid -PermitOn $permitOn
        $inv = Test-ArmPlanInvariants -Plan $plan -PermitOn $permitOn
        if ($inv.Count) { throw ('plan invariants violated: ' + ($inv -join '; ')) }
        $report.steps.preflight = [ordered]@{ spike_sid = $sid; sd_sddl = $plan.Sddl; objects_absent_before = $true; filter_set = $filterSet; filters_planned = @($plan.Filters | ForEach-Object { "$($_.Name) $($_.Key)" }) }
        Write-Host "spike SID $sid; SD $($plan.Sddl); filters planned: $($plan.Filters.Count) ($filterSet)"
        Write-Host 'ROLLBACK FACT: dynamic WFP session. Closing the engine OR this process dying removes every object. Dead-man closes it at BlockMaxSeconds+30.' -ForegroundColor Yellow

        Write-Host '== 1 start the operator-run model server (127.0.0.1, ephemeral port) ==' -ForegroundColor Cyan
        $server = Start-OperatorServer -RunId $runId -HoldSeconds ($BlockMaxSeconds + 600) -LoadTimeoutSeconds $ServerLoadTimeoutSeconds
        $report.server = [ordered]@{ type = $server.Type; port = $server.Port; pid = $server.Pid; bound_address = $server.Bind; model_loaded = $server.ModelLoaded; started = $server.Started; port_file_at = $server.PortFileAt; health = $server.Health; result_file = $server.OutJson; stop = $null }
        $obs.ServerModelLoaded = [bool]$server.ModelLoaded
        Write-Host "server pid $($server.Pid) at $($server.Bind), model_loaded=$($server.ModelLoaded)"
        if (-not $server.ModelLoaded) { Write-Host 'the server did not load its model: this invocation will not count (exit 8); continuing so the removal path is still exercised' -ForegroundColor Yellow }

        Write-Host '== 2 operator baseline + account baseline (filters absent) ==' -ForegroundColor Cyan
        $ctl = @(); foreach ($i in 1..3) { $ctl += Test-TcpConnect '1.1.1.1' 443 5000 }
        $report.steps.operator_baseline = $ctl
        $opBaseOk = (@($ctl | Where-Object { -not $_.ok }).Count -eq 0)
        $base = Invoke-ClientTaskRun -RunId "$runId-base" -Port $server.Port -ExpectedBlocked $false -TimeoutSec $ResultTimeoutSeconds
        $report.steps.account_baseline = $base
        $baseEgressOpen = [bool]($base.valid -and $base.outbound_probe -and $base.outbound_probe.probe.connected)
        $baseClientOk = [bool]($base.valid -and $base.client_connect -and $base.client_connect.ok -and $base.client_connect.status -eq 200)
        $obs.BaselineOk = ($opBaseOk -and $base.valid -and $base.token_sid -eq $sid -and $baseEgressOpen -and $baseClientOk)
        Write-Host ("operator baseline {0}/3; account baseline: valid={1} sid_ok={2} egress_open={3} client_ok={4}" -f @($ctl | Where-Object { $_.ok }).Count, $base.valid, ($base.token_sid -eq $sid), $baseEgressOpen, $baseClientOk)
        if (-not $obs.BaselineOk) {
            $code = 5; $reason = 'no baseline: ' + $(if (-not $opBaseOk) { 'operator cannot reach 1.1.1.1:443' } elseif (-not $base.valid) { 'account baseline run gave no valid result' } elseif (-not $baseEgressOpen) { 'account egress ALREADY blocked before our filters' } else { 'account baseline POST to the server failed' })
            Write-Host $reason -ForegroundColor Red
            # Nothing was added (removal is vacuous); no return here: the report below must still be saved.
            $obs.RemovalVerified = $true
        }
        if ($obs.BaselineOk) {
        Write-Host "== 3 add the block ($filterSet, one transaction, fresh dynamic engine) ==" -ForegroundColor Cyan
        $engine = [BlarAI.Wfp.Engine]::Open($true, "BlarAI #1689 arm 1 ($filterSet, dynamic)")
        $engine.ArmDeadMan($BlockMaxSeconds + 30)
        $ids = $engine.AddAll($plan)
        $report.steps.filters_added = [ordered]@{ at = (Get-Date).ToString("yyyy-MM-dd'T'HH:mm:ss.fffzzz"); filter_set = $filterSet; filter_ids = @($ids); filters = @($plan.Filters | ForEach-Object { "$($_.Name) $($_.Key)" }) }
        Write-Host "added: $($ids.Count) filter(s), ids $($ids -join ', ')" -ForegroundColor Yellow

        Write-Host '== 4 account run under the block (watchdog every 2 s) ==' -ForegroundColor Cyan
        $loop = {
            $w = Test-TcpConnect '1.1.1.1' 443 2000; [void]$watch.Add($w)
            if ($w.ok) { $script:consec = 0 } else { $script:consec++; $obs.OperatorFailures++ }
            if ($script:consec -ge 2) { $engine.Close(); $obs.OperatorAbort = $true; $script:opAbort = $true; Write-Host 'OPERATOR TRAFFIC AFFECTED: two consecutive failures. Engine closed, everything removed.' -ForegroundColor Red }
        }.GetNewClosure()
        $remaining = [Math]::Max(30, [Math]::Min($ResultTimeoutSeconds, $BlockMaxSeconds - 10))
        $during = Invoke-ClientTaskRun -RunId "$runId-block" -Port $server.Port -ExpectedBlocked $true -TimeoutSec $remaining -Tick $loop
        $report.steps.account_during = $during
        $report.steps.watchdog = @($watch)
        $obs.BlockRunValid = [bool]($during.valid -and $during.token_sid -eq $sid)
        $obs.SpikeOutboundBlocked = [bool]($during.valid -and $during.outbound_probe -and $during.outbound_probe.blocked)
        $obs.ClientOkUnderBlock = [bool]($during.valid -and $during.client_connect -and $during.client_connect.ok -and $during.client_connect.status -eq 200 -and $during.client_connect.model_loaded)
        # A failed POST counts as "blocked by the filters" only with a socket-level error (the #1689 Test B signature was WSAEACCES 10013); an HTTP error or a read timeout is the server's, not the filters'.
        $obs.ClientSocketDenied = [bool]($during.valid -and $during.client_connect -and (-not $during.client_connect.ok) -and ([int]$during.client_connect.error_code) -ne 0)
        if (-not $script:opAbort) { $report.steps.operator_during = @((Test-TcpConnect '1.1.1.1' 443 3000), (Test-TcpConnect '8.8.8.8' 443 3000)); foreach ($d in $report.steps.operator_during) { if (-not $d.ok) { $obs.OperatorFailures++ } } }
        Write-Host ("under the block: valid={0} outbound_blocked={1} (code {2}) client_ok={3} (status {4}, {5} ms, tokens {6})" -f $obs.BlockRunValid, $obs.SpikeOutboundBlocked, $(if ($during.outbound_probe) { $during.outbound_probe.probe.error_code } else { '?' }), $obs.ClientOkUnderBlock, $(if ($during.client_connect) { $during.client_connect.status } else { '?' }), $(if ($during.client_connect) { $during.client_connect.ms } else { '?' }), $(if ($during.client_connect) { $during.client_connect.generated_tokens } else { '?' }))

        Write-Host '== 5 release the block + verify removal + account run after removal ==' -ForegroundColor Cyan
        $engine.Close()
        $report.steps.engine_closed_at = (Get-Date).ToString("yyyy-MM-dd'T'HH:mm:ss.fffzzz")
        $report.steps.engine_close_status = ('0x{0:X8}' -f $engine.LastCloseStatus)
        $post = Invoke-ReadOnlyEngineCheck
        $report.steps.removal_engine_check = $post
        $gone = (-not $post.sublayer_present) -and (-not $post.provider_present) -and ($post.filters_present.Count -eq 0)
        $after = Test-TcpConnect '1.1.1.1' 443 5000
        $report.steps.operator_after_removal = $after
        $acctAfter = $null; $acctEgressOpen = $false
        if (-not $script:opAbort) {
            $acctAfter = Invoke-ClientTaskRun -RunId "$runId-after" -Port $server.Port -ExpectedBlocked $false -TimeoutSec $ResultTimeoutSeconds
            $report.steps.account_after_removal = $acctAfter
            $obs.AfterRunValid = [bool]($acctAfter.valid -and $acctAfter.token_sid -eq $sid)
            $acctEgressOpen = [bool]($obs.AfterRunValid -and $acctAfter.outbound_probe -and $acctAfter.outbound_probe.probe.connected)
        } else { $obs.AfterRunValid = $true; $acctEgressOpen = $true }   # the abort path closed the engine already; the account run is skipped and the removal check below is what counts
        # Removal is "not verified" (7) only when an object is left, the operator cannot connect, or the account's run
        # after removal was valid AND still showed its egress blocked. An absent after-run is inconclusive (4), not 7.
        $obs.RemovalVerified = ($gone -and $after.ok -and ((-not $obs.AfterRunValid) -or $acctEgressOpen))
        Write-Host "removal: engine objects gone=$gone; operator connect after ok=$($after.ok); account after-run valid=$($obs.AfterRunValid); account egress open again=$acctEgressOpen"
        }
        $d = Get-TestCVerdict ([pscustomobject]$obs)
        $code = $d.Code; $reason = $d.Reason
    } catch {
        $report.error = $_.Exception.Message + ' @ ' + $_.InvocationInfo.PositionMessage
        Write-Host "ERROR: $($_.Exception.Message)" -ForegroundColor Red
        $code = 4; $reason = 'error: ' + $_.Exception.Message
    } finally {
        if ($engine) { $engine.Close() }
        if ($server) { try { $report.server.stop = Stop-OperatorServer -Server $server } catch { $report.server.stop = "error: $($_.Exception.Message)" } }
    }
    if ($report.Contains('error')) {
        try { $p2 = Invoke-ReadOnlyEngineCheck; $report.steps.final_removal_check = $p2; if ($p2.sublayer_present -or $p2.filters_present.Count) { $code = 7; $reason = 'removal NOT verified after error' } } catch { $code = 7; $reason = 'removal NOT verifiable after error' }
    }
    $report.finished = (Get-Date).ToString("yyyy-MM-dd'T'HH:mm:ss.fffzzz"); $report.decision_inputs = $obs; $report.exit_code = $code; $report.exit_reason = $reason
    Save-OperatorReport 'testC' $report -FileName "$runId.json" | Out-Null
    Write-Host ("RESULT ($filterSet): exit {0}: {1}" -f $code, $reason) -ForegroundColor $(if ($code -in @(0, 9)) { 'Green' } else { 'Yellow' })
    return $code
}

function Assert-SpikePreflight {
    # Returns an array of problems (empty = go). -NeedModel $false (arms 2 and 3: probe mode only) skips the free-RAM check.
    param([bool]$NeedModel = $true)
    $e = New-Object System.Collections.ArrayList
    if (-not (Test-IsElevated)) { [void]$e.Add('not elevated') }
    if (-not [Environment]::Is64BitProcess) { [void]$e.Add('not a 64-bit process (WFP struct layout is asserted for x64)') }
    $sid = Get-SpikeSidOrNull
    if (-not $sid) { [void]$e.Add("account $($script:SpikeUser) not found: run spike-provision.ps1 -Apply") }
    else {
        $op = Get-OperatorTokenSids
        foreach ($m in (Test-CoderSidSafe $sid $op.User $op.Groups)) { [void]$e.Add($m) }
    }
    if (-not (Get-ScheduledTask -TaskPath $script:SpikeTaskPath -TaskName $script:SpikeTaskName -ErrorAction SilentlyContinue)) { [void]$e.Add("task $($script:SpikeTaskPath)$($script:SpikeTaskName) not registered") }
    foreach ($f in @('bin\spike-run-test.ps1', 'bin\spike_model.py', 'bin\spike-config.json')) { if (-not (Test-Path (Join-Path $script:SpikeRoot $f))) { [void]$e.Add("missing $($script:SpikeRoot)\$f") } }
    # The task runs the copies provision made; a stale copy (older script, no client mode) would wait out the whole
    # result timeout and give no result. Compare bytes with this folder's versions.
    foreach ($f in @('spike-run-test.ps1', 'spike_model.py')) {
        $mine = Join-Path $PSScriptRoot $f; $theirs = Join-Path $script:SpikeRoot "bin\$f"
        if ((Test-Path $mine) -and (Test-Path $theirs)) {
            $sha = [Security.Cryptography.SHA256]::Create()
            try { $h1 = [BitConverter]::ToString($sha.ComputeHash([IO.File]::ReadAllBytes($mine))); $h2 = [BitConverter]::ToString($sha.ComputeHash([IO.File]::ReadAllBytes($theirs))) } finally { $sha.Dispose() }
            if ($h1 -ne $h2) { [void]$e.Add("$theirs differs from $mine (re-run spike-provision.ps1 -Apply so the task runs the current script)") }
        }
    }
    $os = Get-CimInstance Win32_OperatingSystem
    $free = [Math]::Round($os.FreePhysicalMemory / 1MB, 2)
    if ($NeedModel -and $free -lt 14) { [void]$e.Add("free RAM $free GB < 14 GB: close memory-heavy processes (the 4B load needs ~10 GB In-Use)") }
    return @($e)
}

function Save-OperatorReport {
    param([string]$Name, $Report, [string]$FileName)
    New-Item -ItemType Directory -Force $OutDir | Out-Null
    $p = Join-Path $OutDir $(if ($FileName) { $FileName } else { "{0}-{1}.json" -f $Name, (Get-Date -Format 'yyyyMMdd-HHmmss') })
    Write-JsonAtomic -Path $p -Object $Report -Depth 14
    Write-Host "report: $p" -ForegroundColor Cyan
    return $p
}

# ---- Test A -------------------------------------------------------------------------------------------------------
function Invoke-TestA {
    $problems = Assert-SpikePreflight
    if ($problems.Count) { $problems | ForEach-Object { Write-Host "FAIL: $_" -ForegroundColor Red }; return 2 }
    $runId = 'testa-' + (Get-Date -Format 'yyyyMMdd-HHmmss')
    Write-Host "== Test A (feasibility, NO network block) run $runId ==" -ForegroundColor Cyan
    Write-SpikeRequest -RunId $runId -Mode 'feasibility' -Hold 5 -ExpectedBlocked $false
    $t0 = (Get-Date).ToString("yyyy-MM-dd'T'HH:mm:ss.fffzzz")
    $go = Start-SpikeTaskProved
    if (-not $go.Started) { Write-Host "FAIL: $($go.Detail)" -ForegroundColor Red; return 4 }
    Write-Host "task started ($($go.Detail)); waiting up to $ResultTimeoutSeconds s for the result (the model load runs now)"
    $res = Wait-SpikeResult -RunId $runId -TimeoutSec $ResultTimeoutSeconds
    if (-not $res) { try { Stop-ScheduledTask -TaskPath $script:SpikeTaskPath -TaskName $script:SpikeTaskName } catch {}; Write-Host 'no result within the timeout; task stopped' -ForegroundColor Red; Save-OperatorReport 'testA' ([ordered]@{ run_id = $runId; started = $t0; error = 'no result' }) | Out-Null; return 4 }
    $viol = Test-SpikeResultSchema $res
    $v = Get-TestAVerdict $res $viol
    foreach ($s in $res.steps) { Write-Host ("  [{0}] {1}: {2}" -f $s.status.ToUpper(), $s.name, $s.detail) }
    Save-OperatorReport 'testA' ([ordered]@{ run_id = $runId; started = $t0; finished = (Get-Date).ToString("yyyy-MM-dd'T'HH:mm:ss.fffzzz"); schema_violations = @($viol); verdict = $v; task_result = $res; wrapped_env = (Get-EnvSnapshot) }) | Out-Null
    Write-Host ("RESULT: exit {0}: {1}" -f $v.Code, $v.Reason) -ForegroundColor $(if ($v.Code -eq 0) { 'Green' } else { 'Yellow' })
    return $v.Code
}

# ---- Test B -------------------------------------------------------------------------------------------------------
function Invoke-TestB {
    $problems = Assert-SpikePreflight
    if ($problems.Count) { $problems | ForEach-Object { Write-Host "FAIL: $_" -ForegroundColor Red }; return 2 }
    Initialize-WfpType
    $sid = Get-SpikeSidOrNull
    $runId = 'testb-' + (Get-Date -Format 'yyyyMMdd-HHmmss')
    $report = [ordered]@{ spike = '#1689 confined inference: WFP block keyed to blarai-spike while serving over loopback'; run_id = $runId; started = (Get-Date).ToString("yyyy-MM-dd'T'HH:mm:ss.fffzzz"); block_max_seconds = $BlockMaxSeconds; serve_hold_seconds = $ServeHoldSeconds; env = (Get-EnvSnapshot); steps = [ordered]@{} }
    $obs = @{ OperatorAbort = $false; RemovalVerified = $false; BaselineOk = $false; OperatorFailures = 0; TaskStarted = $false; ResultValid = $false; SidIsSpike = $false; SpikeOutboundBlocked = $false; ServeStarted = $false; OperatorReachedListener = $false; ModelLoaded = $false; OperatorGotModelCompletion = $false }
    $engine = $null; $code = 4; $reason = 'error before decision'
    try {
        Write-Host '== 0 preflight ==' -ForegroundColor Cyan
        $pre = Invoke-ReadOnlyEngineCheck
        if ($pre.sublayer_present -or $pre.provider_present -or $pre.filters_present.Count) { Write-Host 'FAIL: WFP objects with these keys already exist (stale state or a concurrent #1671 run). Nothing added.' -ForegroundColor Red; return 2 }
        $plan = [BlarAI.Wfp.Plan]::Build($sid)
        $report.steps.preflight = [ordered]@{ spike_sid = $sid; sd_sddl = $plan.Sddl; objects_absent_before = $true }
        Write-Host "spike SID $sid; SD $($plan.Sddl)"
        Write-Host 'ROLLBACK FACT: dynamic WFP session. Closing the engine OR this process dying removes every object. Dead-man closes it at BlockMaxSeconds+30.' -ForegroundColor Yellow

        Write-Host '== 1 operator baseline ==' -ForegroundColor Cyan
        $ctl = @(); foreach ($i in 1..3) { $ctl += Test-TcpConnect '1.1.1.1' 443 5000 }
        $report.steps.operator_baseline = $ctl
        if (@($ctl | Where-Object { -not $_.ok }).Count) { $code = 5; $reason = 'no baseline: the operator cannot reach 1.1.1.1:443'; Write-Host $reason -ForegroundColor Red; $report.exit_code = $code; $report.exit_reason = $reason; Save-OperatorReport 'testB' $report | Out-Null; return $code }
        $obs.BaselineOk = $true; Write-Host 'operator baseline: 3/3 OK'

        Write-Host '== 2 add the block (one transaction) ==' -ForegroundColor Cyan
        $engine = [BlarAI.Wfp.Engine]::Open($true, 'BlarAI #1689 spike (dynamic)')
        $engine.ArmDeadMan($BlockMaxSeconds + 30)
        $ids = $engine.AddAll($plan)
        $report.steps.filters_added = [ordered]@{ at = (Get-Date).ToString("yyyy-MM-dd'T'HH:mm:ss.fffzzz"); filter_ids = @($ids) }
        Write-Host "added: filter ids $($ids -join ', ')" -ForegroundColor Yellow

        Write-Host '== 3 start the task in serve mode; watch the operator; reach the listener ==' -ForegroundColor Cyan
        Write-SpikeRequest -RunId $runId -Mode 'serve' -Hold $ServeHoldSeconds -ExpectedBlocked $true
        $go = Start-SpikeTaskProved
        $report.steps.task_start = $go
        $obs.TaskStarted = [bool]$go.Started
        if (-not $go.Started) { Write-Host "task start FAILED: $($go.Detail)" -ForegroundColor Red }
        $watch = New-Object System.Collections.ArrayList; $script:consec = 0; $script:opAbort = $false
        $portPath = Join-Path $script:SpikeRoot "results\serve-port-$runId.json"
        $blockDeadline = (Get-Date).AddSeconds($BlockMaxSeconds)
        $loop = {
            $w = Test-TcpConnect '1.1.1.1' 443 2000; [void]$watch.Add($w)
            if ($w.ok) { $script:consec = 0 } else { $script:consec++; $obs.OperatorFailures++ }
            if ($script:consec -ge 2) { $engine.Close(); $obs.OperatorAbort = $true; $script:opAbort = $true; Write-Host 'OPERATOR TRAFFIC AFFECTED: two consecutive failures. Engine closed, everything removed.' -ForegroundColor Red }
        }.GetNewClosure()   # Wait-SpikeResult invokes this from its own scope: capture $watch/$obs/$engine by reference
        $portInfo = $null
        while ($obs.TaskStarted -and -not $script:opAbort -and (Get-Date) -lt $blockDeadline) {
            & $loop
            if ($script:opAbort) { break }
            if (Test-PathExistsNoFollow $portPath) {
                Start-Sleep -Milliseconds 300
                $portInfo = Read-UntrustedJson -Path $portPath -MaxBytes 65536
                # Only an integer port is used; the host is the fixed literal 127.0.0.1 in Invoke-LoopbackCompletion, never taken from the file.
                if (-not (Test-LoopbackPort $portInfo.port)) { throw "refusing the serve-port file: port '$($portInfo.port)' is not an integer in 1024..65535" }
                break
            }
            Start-Sleep -Milliseconds 1500
        }
        $report.steps.serve_port = $portInfo
        $comp = $null; $health = $null
        if ($portInfo -and -not $script:opAbort) {
            $obs.ServeStarted = $true
            Write-Host "listener at 127.0.0.1:$($portInfo.port) (model_loaded=$($portInfo.model_loaded)); requesting a completion as the operator"
            $comp = Invoke-LoopbackCompletion -Port ([int]$portInfo.port)
            $obs.OperatorReachedListener = [bool]$comp.ok
            $obs.OperatorGotModelCompletion = ([bool]$comp.ok -and [bool]$comp.model_loaded -and $comp.completion.Length -gt 0)
            Write-Host ("operator request: ok={0} model_loaded={1} {2} ms completion='{3}' {4}" -f $comp.ok, $comp.model_loaded, $comp.ms, ($comp.completion -replace '\s+', ' '), $comp.error)
        }
        $report.steps.operator_request = $comp
        Write-Host '== 4 wait for the task result (block stays live) ==' -ForegroundColor Cyan
        $res = $null
        if ($obs.TaskStarted -and -not $script:opAbort) {
            $remaining = [Math]::Max(10, [int]($blockDeadline - (Get-Date)).TotalSeconds)
            $res = Wait-SpikeResult -RunId $runId -TimeoutSec $remaining -Tick $loop
        }
        $report.steps.watchdog = @($watch)
        $viol = @(); if ($res) { $viol = Test-SpikeResultSchema $res }
        $obs.ResultValid = ([bool]$res -and $viol.Count -eq 0)
        if ($res) {
            $idStep = $res.steps | Where-Object { $_.name -eq 'identity' } | Select-Object -First 1
            $obs.SidIsSpike = [bool]($idStep -and $idStep.data -and $idStep.data.token_sid -eq $sid)
            $ob = $res.steps | Where-Object { $_.name -eq 'outbound_probe' } | Select-Object -First 1
            $obs.SpikeOutboundBlocked = [bool]($ob -and $ob.data -and $ob.data.blocked)
            $sv = $res.steps | Where-Object { $_.name -eq 'serve' } | Select-Object -First 1
            if ($sv -and $sv.data -and $sv.data.outbound_probe_mid_hold) { $report.steps.spike_outbound_mid_hold = $sv.data.outbound_probe_mid_hold; if ($sv.data.outbound_probe_mid_hold.connected) { $obs.SpikeOutboundBlocked = $false } }
            $obs.ModelLoaded = [bool]($portInfo -and $portInfo.model_loaded)
        }
        $report.steps.task_result = $res
        $report.steps.schema_violations = @($viol)
        if (-not $res -and $obs.TaskStarted -and -not $script:opAbort) { try { Stop-ScheduledTask -TaskPath $script:SpikeTaskPath -TaskName $script:SpikeTaskName } catch {} }

        Write-Host '== 5 release the block + verify removal ==' -ForegroundColor Cyan
        $engine.Close()
        $report.steps.engine_close_status = ('0x{0:X8}' -f $engine.LastCloseStatus)
        $post = Invoke-ReadOnlyEngineCheck
        $report.steps.removal_engine_check = $post
        $gone = (-not $post.sublayer_present) -and (-not $post.provider_present) -and ($post.filters_present.Count -eq 0)
        $after = Test-TcpConnect '1.1.1.1' 443 5000
        $report.steps.operator_after_removal = $after
        $obs.RemovalVerified = ($gone -and $after.ok)
        Write-Host "removal: engine objects gone=$gone; operator connect after removal ok=$($after.ok)"
        $d = Get-TestBVerdict ([pscustomobject]$obs)
        $code = $d.Code; $reason = $d.Reason
    } catch {
        $report.error = $_.Exception.Message + ' @ ' + $_.InvocationInfo.PositionMessage
        Write-Host "ERROR: $($_.Exception.Message)" -ForegroundColor Red
        $code = 4; $reason = 'error: ' + $_.Exception.Message
    } finally {
        if ($engine) { $engine.Close() }
    }
    if ($report.Contains('error')) {
        try { $p2 = Invoke-ReadOnlyEngineCheck; $report.steps.final_removal_check = $p2; if ($p2.sublayer_present -or $p2.filters_present.Count) { $code = 7; $reason = 'removal NOT verified after error' } } catch { $code = 7; $reason = 'removal NOT verifiable after error' }
    }
    $report.finished = (Get-Date).ToString("yyyy-MM-dd'T'HH:mm:ss.fffzzz"); $report.decision_inputs = $obs; $report.exit_code = $code; $report.exit_reason = $reason
    Save-OperatorReport 'testB' $report | Out-Null
    Write-Host ("RESULT: exit {0}: {1}" -f $code, $reason) -ForegroundColor $(if ($code -eq 0) { 'Green' } else { 'Yellow' })
    return $code
}

# ---- Arm 2: the long hold -----------------------------------------------------------------------------------------
# The block is held by ONE dynamic engine session for up to 7200 s. The OPERATOR starts the task in probe mode once per
# sample (many short task runs, so the task's 30-minute execution limit never bounds the hold). Everything the tick
# scriptblock touches lives in $script:Hold* variables and the scriptblock is NOT a closure: a closure's $script: is the
# closure's own module scope, so a flag it sets would be invisible to Wait-SpikeResult / Start-SpikeTaskProved.
$script:HoldMarker = 'BlarAI #1671'
$script:BdProcessPattern = 'bd|bitdefender|vsserv|epsecurity'      # the wrapped Get-EnvSnapshot pattern
$script:BdUpdatePattern = '(?i)update|updatesrv|bdupd'
$script:BdFolders = @('C:\Program Files\Bitdefender\Bitdefender Security', 'C:\Program Files\Bitdefender\Bitdefender Security App', 'C:\ProgramData\Bitdefender')
$script:WatchdogSeconds = 2

function Get-HoldSchedule {
    # PURE. Sample offsets (seconds from the hold start) on a fixed grid, how many samples are expected, the mid-hold
    # export offset and the dead-man offset.
    param([int]$Hold, [int]$Sample)
    $offs = New-Object System.Collections.ArrayList
    for ($t = 0; $t -lt $Hold; $t += $Sample) { [void]$offs.Add($t) }
    return [pscustomobject]@{ SampleOffsets = @($offs); Expected = $offs.Count; MidExportAt = [int][Math]::Floor($Hold / 2); DeadManAt = $Hold + 30 }
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

function Get-SampleOutcome {
    # PURE. blocked | open | no_result | wrong_sid, from the observation Invoke-ProbeTaskRun returns.
    param($Run, [string]$Sid)
    if (-not $Run -or -not $Run.valid -or -not $Run.outbound_probe -or -not $Run.outbound_probe.probe) { return 'no_result' }
    if ([string]$Run.token_sid -ne $Sid) { return 'wrong_sid' }
    if ($Run.outbound_probe.probe.connected) { return 'open' }
    return 'blocked'
}

function Format-SampleLine {
    # PURE. One compact JSON object per sample: the line written to <run>-samples.txt the moment the sample finishes.
    param([int]$N, [string]$When, [double]$OffsetSeconds, [string]$Outcome, $Probe, [string]$RunId, [string]$TaskDetail)
    $o = [ordered]@{ n = $N; t = $When; offset_s = [Math]::Round($OffsetSeconds, 1); outcome = $Outcome
                     error_code = $(if ($Probe) { $Probe.error_code } else { $null }); error = $(if ($Probe) { [string]$Probe.error } else { '' })
                     probe_ms = $(if ($Probe) { $Probe.ms } else { $null }); run_id = $RunId; task = $TaskDetail }
    return (ConvertTo-Json -InputObject $o -Compress)
}

function Get-SampleStats {
    # PURE. Counts by outcome, the error-code histogram of the blocked samples and the first sample that was not blocked.
    param($Samples)
    $s = @($Samples)
    $codes = [ordered]@{}
    foreach ($x in @($s | Where-Object { $_.outcome -eq 'blocked' })) { $k = "$($x.error_code)"; if ($codes.Contains($k)) { $codes[$k]++ } else { $codes[$k] = 1 } }
    $firstOpen = $s | Where-Object { $_.outcome -eq 'open' } | Select-Object -First 1
    return [ordered]@{
        total = $s.Count; blocked = @($s | Where-Object { $_.outcome -eq 'blocked' }).Count; open = @($s | Where-Object { $_.outcome -eq 'open' }).Count
        no_result = @($s | Where-Object { $_.outcome -eq 'no_result' }).Count; wrong_sid = @($s | Where-Object { $_.outcome -eq 'wrong_sid' }).Count
        blocked_error_codes = $codes; first_open = $(if ($firstOpen) { [ordered]@{ n = $firstOpen.n; t = $firstOpen.t; offset_s = $firstOpen.offset_s } } else { $null })
    }
}

function Read-ExportText {
    # PURE on bytes. netsh writes UTF-8 XML; a UTF-16 BOM is handled too so a different build does not read as empty.
    param([byte[]]$Bytes)
    if ($Bytes.Length -ge 2 -and $Bytes[0] -eq 0xFF -and $Bytes[1] -eq 0xFE) { return [Text.Encoding]::Unicode.GetString($Bytes) }
    return [Text.Encoding]::UTF8.GetString($Bytes)
}

function Get-FilterExportSummary {
    # PURE. What a `netsh wfp show filters` export says about OUR objects: the marker count and which filter keys appear
    # (case-insensitive, with or without braces). ok = every expected key present and the marker seen at least once.
    param([string]$Text, [string]$Marker, [string[]]$ExpectedKeys)
    $mc = if ($Text) { [regex]::Matches($Text, [regex]::Escape($Marker)).Count } else { 0 }
    $found = @(); $missing = @()
    foreach ($k in $ExpectedKeys) { if ($Text -and $Text.IndexOf($k, [StringComparison]::OrdinalIgnoreCase) -ge 0) { $found += $k } else { $missing += $k } }
    return [ordered]@{ marker = $Marker; marker_count = $mc; keys_expected = @($ExpectedKeys); keys_found = $found; keys_missing = $missing; ok = ($mc -ge 1 -and $missing.Count -eq 0) }
}

function Compare-BitdefenderSnapshots {
    # PURE. $A (start) and $B (end) are Get-BitdefenderSnapshot results. Process identity = name#id#start. A process whose
    # name matches the update pattern and that started after $HoldStart is an update signal; so is any folder whose
    # LastWriteTime moved. None observed is NOT proof that no update ran (both are weak signals; the log files of the
    # suite were not read).
    param([Parameter(Mandatory)]$A, [Parameter(Mandatory)]$B, [datetimeoffset]$HoldStart, $SeenDuring = @())
    $ka = @($A.processes | ForEach-Object { "$($_.name)#$($_.id)#$($_.start)" }); $kb = @($B.processes | ForEach-Object { "$($_.name)#$($_.id)#$($_.start)" })
    $added = @($kb | Where-Object { $ka -notcontains $_ }); $removed = @($ka | Where-Object { $kb -notcontains $_ })
    $upd = @(@($B.processes) + @($SeenDuring) | Where-Object { $_.name -match $script:BdUpdatePattern -and $_.start -and ([datetimeoffset]::Parse([string]$_.start) -ge $HoldStart) } | ForEach-Object { "$($_.name)#$($_.id)#$($_.start)" } | Select-Object -Unique)
    $dirsA = @{}; foreach ($d in @($A.folders)) { $dirsA[$d.path] = $d.last_write }
    $changed = @(@($B.folders) | Where-Object { $dirsA.ContainsKey($_.path) -and $dirsA[$_.path] -ne $_.last_write } | ForEach-Object { "$($_.path): $($dirsA[$_.path]) -> $($_.last_write)" })
    $signal = if ($upd.Count) { 'update_named_process_started_during_hold' } elseif ($changed.Count) { 'bitdefender_folder_timestamps_changed' } else { 'none_observed' }
    return [ordered]@{ processes_added = $added; processes_removed = $removed; update_named_processes_started = $upd; folders_changed = $changed; signal = $signal
                       caveat = 'a weak signal: process names and folder timestamps only; the suite''s own logs were not read; none_observed does not show that no update ran' }
}

function Get-LongHoldVerdict {
    # PURE. Safety first as in the wrapped script: operator impact, unverified removal, no baseline, then the hold itself.
    # An observed OPEN sample is a finding whatever the coverage; "held" needs coverage and every export showing the filters.
    param([Parameter(Mandatory)]$Obs)
    if ($Obs.OperatorAbort)        { return [pscustomobject]@{ Code = 3; Reason = 'operator traffic affected (watchdog abort): everything removed' } }
    if (-not $Obs.RemovalVerified) { return [pscustomobject]@{ Code = 7; Reason = 'removal NOT verified (objects left, operator connect failed, or the account''s egress did not reopen)' } }
    if (-not $Obs.BaselineOk)      { return [pscustomobject]@{ Code = 5; Reason = 'no baseline (operator offline / stale WFP objects / account baseline invalid or egress already blocked)' } }
    if ($Obs.EngineClosedEarly)    { return [pscustomobject]@{ Code = 4; Reason = 'inconclusive: the engine closed before the hold ended (dead-man or an unexpected close)' } }
    if ([int]$Obs.SamplesOpen -gt 0) { return [pscustomobject]@{ Code = 1; Reason = "the block did NOT hold: $($Obs.SamplesOpen) sample(s) connected with the filters live" } }
    $need = [Math]::Max(3, [int][Math]::Ceiling(0.9 * [int]$Obs.SamplesExpected))
    if ([int]$Obs.SamplesBlocked -lt $need) { return [pscustomobject]@{ Code = 4; Reason = "inconclusive: only $($Obs.SamplesBlocked) of $($Obs.SamplesExpected) samples gave a valid blocked result (need $need)" } }
    if (-not $Obs.ExportsOk)       { return [pscustomobject]@{ Code = 4; Reason = 'inconclusive: a filter export did not show every filter key' } }
    return [pscustomobject]@{ Code = 0; Reason = "block held for the whole hold: $($Obs.SamplesBlocked) of $($Obs.SamplesExpected) samples blocked, filters in every export, removal verified" }
}

# ---- impure helpers (read-only unless stated) ---------------------------------------------------------------------
function Get-BdProcessList {
    $out = @()
    foreach ($p in @(Get-Process -ErrorAction SilentlyContinue | Where-Object { $_.Name -match $script:BdProcessPattern })) {
        $st = $null; try { $st = ([datetimeoffset]$p.StartTime).ToString('o') } catch {}
        $out += [pscustomobject]@{ name = $p.Name; id = $p.Id; start = $st }
    }
    return $out
}

function Get-BitdefenderSnapshot {
    # READ-ONLY. Processes (name, id, start) and the LastWriteTime of the suite's install folders and their immediate
    # children where readable. An unreadable folder is recorded as such, never skipped silently.
    $folders = @()
    foreach ($root in $script:BdFolders) {
        try {
            $items = @($root) + @(Get-ChildItem -LiteralPath $root -Directory -ErrorAction Stop | ForEach-Object { $_.FullName })
            foreach ($i in $items) { try { $folders += [pscustomobject]@{ path = $i; last_write = ([datetimeoffset](Get-Item -LiteralPath $i -ErrorAction Stop).LastWriteTime).ToString('o') } } catch { $folders += [pscustomobject]@{ path = $i; last_write = "unreadable: $($_.Exception.Message)" } } }
        } catch { $folders += [pscustomobject]@{ path = $root; last_write = "unreadable: $($_.Exception.Message)" } }
    }
    $svc = @(); try { $svc = @(Get-Service -ErrorAction Stop | Where-Object { $_.Name -match 'vsserv|bdservicehost|updatesrv|EPSecurityService|EPUpdateService|EPProtectedService' } | ForEach-Object { "$($_.Name)=$($_.Status)" }) } catch { $svc = @("error: $($_.Exception.Message)") }
    return [pscustomobject]@{ taken = (Get-Date).ToString("yyyy-MM-dd'T'HH:mm:ss.fffzzz"); processes = @(Get-BdProcessList); folders = $folders; services = $svc }
}

function Invoke-WslShutdown {
    # `wsl --shutdown` before a live run (the brief's rule), recorded with the distribution list before and after.
    $rec = [ordered]@{ at = (Get-Date).ToString("yyyy-MM-dd'T'HH:mm:ss.fffzzz"); before = $null; exit_code = $null; after = $null; error = $null }
    $list = { ((& wsl.exe --list --verbose 2>&1 | Out-String) -replace "`0", '') -split "`r?`n" | ForEach-Object { ($_ -replace '\s+', ' ').Trim() } | Where-Object { $_ } }
    try { $rec.before = @(& $list); & wsl.exe --shutdown 2>&1 | Out-Null; $rec.exit_code = $LASTEXITCODE; Start-Sleep -Seconds 2; $rec.after = @(& $list) } catch { $rec.error = $_.Exception.Message }
    return $rec
}

function Invoke-FilterExport {
    # `netsh wfp show filters file=<path>` (needs elevation; reads the engine, changes nothing), then the summary of what it
    # holds for our objects. $Tick (the operator watchdog) runs while the export is written.
    param([Parameter(Mandatory)][string]$Label, [Parameter(Mandatory)][string]$Path, [string[]]$ExpectedKeys, [scriptblock]$Tick)
    $rec = [ordered]@{ label = $Label; at = (Get-Date).ToString("yyyy-MM-dd'T'HH:mm:ss.fffzzz"); path = $Path; ok = $false; bytes = 0; sha256 = $null; summary = $null; error = $null; seconds = 0 }
    $sw = [Diagnostics.Stopwatch]::StartNew()
    try {
        if (Test-Path -LiteralPath $Path) { Remove-Item -LiteralPath $Path -Force }
        $p = Start-Process -FilePath "$env:SystemRoot\System32\netsh.exe" -ArgumentList @('wfp', 'show', 'filters', "file=`"$Path`"") -PassThru -WindowStyle Hidden
        while (-not $p.WaitForExit(500)) {
            if ($Tick) { & $Tick; if ($script:opAbort) { break } }
            if ($sw.Elapsed.TotalSeconds -gt 120) { try { $p.Kill() } catch {}; throw 'netsh wfp show filters did not finish within 120 s' }
        }
        if (-not (Test-Path -LiteralPath $Path)) { throw "netsh wrote no file (exit $($p.ExitCode))" }
        $bytes = [IO.File]::ReadAllBytes($Path)
        $sha = [Security.Cryptography.SHA256]::Create(); try { $rec.sha256 = ([BitConverter]::ToString($sha.ComputeHash($bytes))) -replace '-', '' } finally { $sha.Dispose() }
        $rec.bytes = $bytes.Length
        $rec.summary = Get-FilterExportSummary -Text (Read-ExportText $bytes) -Marker $script:HoldMarker -ExpectedKeys $ExpectedKeys
        $rec.ok = [bool]$rec.summary.ok
    } catch { $rec.error = $_.Exception.Message }
    $rec.seconds = [Math]::Round($sw.Elapsed.TotalSeconds, 1)
    return $rec
}

if (-not ('SpikePower' -as [type])) {
    Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
public static class SpikePower {
    public const uint ES_CONTINUOUS = 0x80000000, ES_SYSTEM_REQUIRED = 0x00000001;
    [DllImport("kernel32.dll")] static extern uint SetThreadExecutionState(uint flags);
    public static uint KeepAwake() { return SetThreadExecutionState(ES_CONTINUOUS | ES_SYSTEM_REQUIRED); }
    public static uint Release() { return SetThreadExecutionState(ES_CONTINUOUS); }
}
'@
}

function Invoke-ProbeTaskRun {
    # One run of the task in probe mode (baseline, a sample, or after removal). Never throws on a failed run; the verdict
    # reads the fields. Same start-proof and result handling as Invoke-ClientTaskRun, without the loopback request.
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

function Add-SampleLine {
    param([string]$Path, [string]$Line)
    [IO.File]::AppendAllText($Path, $Line + "`n", (New-Object Text.UTF8Encoding($false)))
}

function Invoke-LongHold {
    # SID safety first: a target that is the operator or one of his groups is refused before anything else (exit 3).
    $sid = Get-SpikeSidOrNull
    if ($sid) {
        $opT = Get-OperatorTokenSids; $unsafe = @(Test-CoderSidSafe $sid $opT.User $opT.Groups)
        if ($unsafe.Count) { Write-Host ('REFUSED (exit 3): ' + ($unsafe -join '; ')) -ForegroundColor Red; return 3 }
    }
    $problems = Assert-SpikePreflight -NeedModel $false
    if ($problems.Count) { $problems | ForEach-Object { Write-Host "FAIL: $_" -ForegroundColor Red }; return 2 }
    Initialize-WfpType
    $permitOn = -not $NoLoopbackPermit.IsPresent
    $filterSet = $(if ($permitOn) { 'permit_on' } else { 'permit_off' })
    $runId = 'hold-' + $(if ($permitOn) { 'on-' } else { 'off-' }) + (Get-Date -Format 'yyyyMMdd-HHmmss')
    New-Item -ItemType Directory -Force $HoldOutDir | Out-Null
    $samplesPath = Join-Path $HoldOutDir "$runId-samples.txt"
    $sched = Get-HoldSchedule -Hold $HoldSeconds -Sample $SampleSeconds
    $report = [ordered]@{ spike = '#1689 arm 2: does the SID-keyed block stay enforced for a long hold while Bitdefender runs'; run_id = $runId; filter_set = $filterSet; started = (Get-Date).ToString("yyyy-MM-dd'T'HH:mm:ss.fffzzz")
                          hold_seconds = $HoldSeconds; sample_seconds = $SampleSeconds; samples_expected = $sched.Expected; dead_man_seconds = $sched.DeadManAt; watchdog_seconds = $script:WatchdogSeconds
                          samples_file = $samplesPath; env = $null; wsl_shutdown = $null; steps = [ordered]@{}; samples = @(); exports = @(); sample_stats = $null }
    $obs = @{ OperatorAbort = $false; RemovalVerified = $false; BaselineOk = $false; EngineClosedEarly = $false; SamplesExpected = $sched.Expected; SamplesBlocked = 0; SamplesOpen = 0; ExportsOk = $false }
    $engine = $null; $code = 4; $reason = 'error before decision'; $keysSeen = New-Object System.Collections.ArrayList
    $script:opAbort = $false; $script:HoldWd = New-WatchdogState; $script:HoldEngine = $null
    $awake = [SpikePower]::KeepAwake()
    try {
        Write-Host "== 0 preflight + wsl --shutdown ($filterSet, hold $HoldSeconds s, sample every $SampleSeconds s) ==" -ForegroundColor Cyan
        $report.wsl_shutdown = Invoke-WslShutdown
        $report.env = Get-ArmEnvSnapshot
        $report.keep_awake = ('SetThreadExecutionState(ES_CONTINUOUS|ES_SYSTEM_REQUIRED) previous state 0x{0:X}; released in finally' -f $awake)
        $pre = Invoke-ReadOnlyEngineCheck
        if ($pre.sublayer_present -or $pre.provider_present -or $pre.filters_present.Count) { Write-Host 'FAIL: WFP objects with these keys already exist (stale state or a concurrent run). Nothing added.' -ForegroundColor Red; return 2 }
        $plan = Get-ArmPlan -Sid $sid -PermitOn $permitOn
        $inv = Test-ArmPlanInvariants -Plan $plan -PermitOn $permitOn
        if ($inv.Count) { throw ('plan invariants violated: ' + ($inv -join '; ')) }
        $keys = @($plan.Filters | ForEach-Object { [string]$_.Key })
        $report.steps.preflight = [ordered]@{ spike_sid = $sid; sd_sddl = $plan.Sddl; objects_absent_before = $true; filter_set = $filterSet; filters_planned = @($plan.Filters | ForEach-Object { "$($_.Name) $($_.Key)" }) }
        Write-Host 'ROLLBACK FACT: dynamic WFP session. Closing the engine OR this process dying removes every object. Dead-man closes it at HoldSeconds+30.' -ForegroundColor Yellow

        Write-Host '== 1 operator baseline + account baseline (filters absent) ==' -ForegroundColor Cyan
        $ctl = @(); foreach ($i in 1..3) { $ctl += Test-TcpConnect '1.1.1.1' 443 5000 }
        $report.steps.operator_baseline = $ctl
        $opBaseOk = (@($ctl | Where-Object { -not $_.ok }).Count -eq 0)
        $base = Invoke-ProbeTaskRun -RunId "$runId-base" -ExpectedBlocked $false -TimeoutSec 60
        $report.steps.account_baseline = $base
        $baseOpen = [bool]($base.valid -and $base.outbound_probe -and $base.outbound_probe.probe.connected)
        $obs.BaselineOk = ($opBaseOk -and $base.valid -and $base.token_sid -eq $sid -and $baseOpen)
        Write-Host ("operator baseline {0}/3; account baseline: valid={1} sid_ok={2} egress_open={3}" -f @($ctl | Where-Object { $_.ok }).Count, $base.valid, ($base.token_sid -eq $sid), $baseOpen)
        if (-not $obs.BaselineOk) {
            $reason = 'no baseline: ' + $(if (-not $opBaseOk) { 'operator cannot reach 1.1.1.1:443' } elseif (-not $base.valid) { 'account baseline run gave no valid result' } else { 'account egress ALREADY blocked before our filters' })
            Write-Host $reason -ForegroundColor Red
            $obs.RemovalVerified = $true; $code = 5
        } else {
            $bd0 = Get-BitdefenderSnapshot; $report.steps.bitdefender_start = $bd0
            Write-Host "== 2 add the block ($filterSet, one transaction, fresh dynamic engine, dead-man $($sched.DeadManAt) s) ==" -ForegroundColor Cyan
            $engine = [BlarAI.Wfp.Engine]::Open($true, "BlarAI #1689 arm 2 ($filterSet, dynamic)")
            $script:HoldEngine = $engine
            $engine.ArmDeadMan($sched.DeadManAt)
            $ids = $engine.AddAll($plan)
            $t0 = Get-Date; $t0o = [datetimeoffset]::Now
            $report.steps.filters_added = [ordered]@{ at = $t0.ToString("yyyy-MM-dd'T'HH:mm:ss.fffzzz"); filter_set = $filterSet; filter_ids = @($ids); filters = @($plan.Filters | ForEach-Object { "$($_.Name) $($_.Key)" }) }
            Write-Host "added: $($ids.Count) filter(s), ids $($ids -join ', ')" -ForegroundColor Yellow

            $tick = {
                $wd = $script:HoldWd; $now = $wd.Clock.Elapsed.TotalSeconds
                if (($now - $wd.LastAt) -lt $script:WatchdogSeconds) { return }
                if ($wd.Count -gt 0 -and ($now - $wd.LastAt) -gt $wd.MaxGap) { $wd.MaxGap = $now - $wd.LastAt }
                $wd.LastAt = $now
                $w = Test-TcpConnect '1.1.1.1' 443 2000
                $abort = Update-WatchdogState -State $wd -Ok ([bool]$w.ok) -When ([string]$w.t) -Message ([string]$w.error) -Ms ([long]$w.ms)
                if ($abort -and -not $script:opAbort) { $script:HoldEngine.Close(); $script:opAbort = $true; $wd.Aborted = $true; Write-Host 'OPERATOR TRAFFIC AFFECTED: two consecutive failures. Engine closed, everything removed.' -ForegroundColor Red }
            }
            $exp = New-Object System.Collections.ArrayList
            [void]$exp.Add((Invoke-FilterExport -Label 'start' -Path (Join-Path $HoldOutDir "$runId-filters-start.xml") -ExpectedKeys $keys -Tick $tick))

            Write-Host "== 3 hold: watchdog every $($script:WatchdogSeconds) s, probe every $SampleSeconds s ==" -ForegroundColor Cyan
            $samples = New-Object System.Collections.ArrayList; $sampleN = 0; $midDone = $false; $openExported = $false; $nextSample = 0.0
            $holdEnd = $t0.AddSeconds($HoldSeconds)
            while ((Get-Date) -lt $holdEnd -and -not $script:opAbort) {
                if (-not $engine.IsOpen) { $obs.EngineClosedEarly = $true; Write-Host 'the engine closed before the hold ended' -ForegroundColor Red; break }
                & $tick
                if ($script:opAbort) { break }
                $elapsed = ((Get-Date) - $t0).TotalSeconds
                if (-not $midDone -and $elapsed -ge $sched.MidExportAt) { $midDone = $true; [void]$exp.Add((Invoke-FilterExport -Label 'mid' -Path (Join-Path $HoldOutDir "$runId-filters-mid.xml") -ExpectedKeys $keys -Tick $tick)); continue }
                if ($elapsed -ge $nextSample) {
                    $sampleN++; $nextSample = [double]($sampleN * $SampleSeconds)
                    $run = Invoke-ProbeTaskRun -RunId ('{0}-s{1:0000}' -f $runId, $sampleN) -ExpectedBlocked $true -TimeoutSec 40 -Tick $tick
                    $outcome = Get-SampleOutcome -Run $run -Sid $sid
                    $probe = $(if ($run.outbound_probe) { $run.outbound_probe.probe } else { $null })
                    $now = Get-Date
                    $line = Format-SampleLine -N $sampleN -When $now.ToString("yyyy-MM-dd'T'HH:mm:ss.fffzzz") -OffsetSeconds (($now - $t0).TotalSeconds) -Outcome $outcome -Probe $probe -RunId $run.run_id -TaskDetail $(if ($run.task_start) { [string]$run.task_start.Detail } else { 'task not ready' })
                    Add-SampleLine -Path $samplesPath -Line $line
                    [void]$samples.Add((ConvertFrom-Json $line))
                    $bdNow = @(Get-BdProcessList); foreach ($b in $bdNow) { if ($b.start -and ([datetimeoffset]::Parse($b.start) -ge $t0o) -and -not (@($keysSeen | Where-Object { $_.name -eq $b.name -and $_.id -eq $b.id }).Count)) { [void]$keysSeen.Add($b) } }
                    Write-Host ("sample {0}/{1} at {2:N0}s: {3}{4}" -f $sampleN, $sched.Expected, ($now - $t0).TotalSeconds, $outcome, $(if ($probe) { " (code $($probe.error_code), $($probe.ms) ms)" } else { '' }))
                    if ($outcome -eq 'open' -and -not $openExported) {
                        $openExported = $true
                        [void]$exp.Add((Invoke-FilterExport -Label 'on_first_open' -Path (Join-Path $HoldOutDir "$runId-filters-on-first-open.xml") -ExpectedKeys $keys -Tick $tick))
                    }
                    continue
                }
                Start-Sleep -Milliseconds 250
            }
            $report.samples = @($samples)
            $st = Get-SampleStats $samples
            $report.sample_stats = $st; $obs.SamplesBlocked = $st.blocked; $obs.SamplesOpen = $st.open
            if (-not $script:opAbort -and $engine.IsOpen) { [void]$exp.Add((Invoke-FilterExport -Label 'end' -Path (Join-Path $HoldOutDir "$runId-filters-end.xml") -ExpectedKeys $keys -Tick $tick)) }
            $report.exports = @($exp)
            $held = @($exp | Where-Object { $_.label -in @('start', 'mid', 'end') })
            $obs.ExportsOk = ($held.Count -eq 3 -and @($held | Where-Object { -not $_.ok }).Count -eq 0)
            $wd = $script:HoldWd
            $report.steps.watchdog = [ordered]@{ interval_seconds = $script:WatchdogSeconds; connects = $wd.Count; failures = $wd.Fail; max_consecutive_failures = $wd.MaxConsec; max_gap_between_ticks_seconds = [Math]::Round($wd.MaxGap, 1); aborted = $wd.Aborted; failure_events = @($wd.Events)
                                                  note = 'isolated failures (never two in a row) are recorded here and do not change the verdict; two in a row abort the run' }
            $obs.OperatorAbort = [bool]$wd.Aborted
            if (-not $script:opAbort) { $report.steps.operator_during = @((Test-TcpConnect '1.1.1.1' 443 3000), (Test-TcpConnect '8.8.8.8' 443 3000)) }
            $bd1 = Get-BitdefenderSnapshot; $report.steps.bitdefender_end = $bd1
            $report.steps.bitdefender_update = Compare-BitdefenderSnapshots -A $bd0 -B $bd1 -HoldStart $t0o -SeenDuring @($keysSeen)
            $report.steps.bitdefender_processes_first_seen_during_hold = @($keysSeen)

            Write-Host '== 4 release the block + verify removal + account run after removal ==' -ForegroundColor Cyan
            $engine.Close()
            $report.steps.engine_closed_at = (Get-Date).ToString("yyyy-MM-dd'T'HH:mm:ss.fffzzz")
            $report.steps.filters_stood_seconds = [Math]::Round(((Get-Date) - $t0).TotalSeconds, 1)
            $report.steps.engine_close_status = ('0x{0:X8}' -f $engine.LastCloseStatus)
            $post = Invoke-ReadOnlyEngineCheck
            $report.steps.removal_engine_check = $post
            $gone = (-not $post.sublayer_present) -and (-not $post.provider_present) -and ($post.filters_present.Count -eq 0)
            $after = Test-TcpConnect '1.1.1.1' 443 5000
            $report.steps.operator_after_removal = $after
            $afterRun = $null; $afterValid = $false; $acctOpen = $false
            if (-not $script:opAbort) {
                $afterRun = Invoke-ProbeTaskRun -RunId "$runId-after" -ExpectedBlocked $false -TimeoutSec 60
                $report.steps.account_after_removal = $afterRun
                $afterValid = [bool]($afterRun.valid -and $afterRun.token_sid -eq $sid)
                $acctOpen = [bool]($afterValid -and $afterRun.outbound_probe -and $afterRun.outbound_probe.probe.connected)
            } else { $afterValid = $true; $acctOpen = $true }
            $obs.RemovalVerified = ($gone -and $after.ok -and ((-not $afterValid) -or $acctOpen))
            Write-Host "removal: engine objects gone=$gone; operator connect after ok=$($after.ok); account after-run valid=$afterValid; account egress open again=$acctOpen"
            $d = Get-LongHoldVerdict ([pscustomobject]$obs)
            $code = $d.Code; $reason = $d.Reason
        }
    } catch {
        $report.error = $_.Exception.Message + ' @ ' + $_.InvocationInfo.PositionMessage
        Write-Host "ERROR: $($_.Exception.Message)" -ForegroundColor Red
        $code = 4; $reason = 'error: ' + $_.Exception.Message
    } finally {
        if ($engine) { $engine.Close() }
        [void][SpikePower]::Release()
    }
    if ($report.Contains('error')) {
        try { $p2 = Invoke-ReadOnlyEngineCheck; $report.steps.final_removal_check = $p2; if ($p2.sublayer_present -or $p2.filters_present.Count) { $code = 7; $reason = 'removal NOT verified after error' } } catch { $code = 7; $reason = 'removal NOT verifiable after error' }
        if ($samples -and -not $report.samples.Count) { $report.samples = @($samples) }
    }
    $report.finished = (Get-Date).ToString("yyyy-MM-dd'T'HH:mm:ss.fffzzz"); $report.decision_inputs = $obs; $report.exit_code = $code; $report.exit_reason = $reason
    Write-JsonAtomic -Path (Join-Path $HoldOutDir "$runId.json") -Object $report -Depth 14
    Write-Host ("report: {0}" -f (Join-Path $HoldOutDir "$runId.json")) -ForegroundColor Cyan
    Write-Host ("RESULT ($filterSet): exit {0}: {1}" -f $code, $reason) -ForegroundColor $(if ($code -in @(0, 1)) { 'Green' } else { 'Yellow' })
    return $code
}

# ---- self-test / dry-run ------------------------------------------------------------------------------------------
function Invoke-SelfTest {
    $script:f = 0
    function Chk([string]$n, [bool]$c) { if ($c) { Write-Host "  [PASS] $n" -ForegroundColor Green } else { Write-Host "  [FAIL] $n" -ForegroundColor Red; $script:f++ } }
    Write-Host '== extraction from the wrapped script ==' -ForegroundColor Cyan
    $imp = Import-WfpHelpers -Path $WfpScript
    Chk "all $($script:WrappedFunctions.Count) wrapped functions extracted" ($imp.Functions.Count -eq $script:WrappedFunctions.Count)
    Chk 'C# source extracted' ($imp.CsharpChars -gt 10000)
    Chk 'the wrapped script was only read (SHA-256 recorded)' ($imp.Sha256 -match '^[0-9A-F]{64}$')
    Initialize-WfpType
    Chk 'the WFP C# compiles in-process' ([bool]('BlarAI.Wfp.Plan' -as [type]))
    $sid = 'S-1-5-21-1111111111-2222222222-3333333333-1001'; $other = 'S-1-5-21-1111111111-2222222222-3333333333-1002'
    $plan = [BlarAI.Wfp.Plan]::Build($sid)
    Chk 'SDDL is exactly D:(A;;CC;;;<spike sid>)' ($plan.Sddl -eq "D:(A;;CC;;;$sid)")
    Chk 'four filters, permit weight > block weight' ($plan.Filters.Count -eq 4)
    $refused = 0; foreach ($b in @('S-1-1-0', 'S-1-5-32-545', 'S-1-5-18', 'S-1-5-11', 'S-1-5-32-544')) { $t = $false; try { [void][BlarAI.Wfp.Plan]::Build($b) } catch { $t = $true }; if ($t) { $refused++ } }
    Chk 'refuses non-account SIDs (Everyone, Users, SYSTEM, Authenticated Users, Administrators)' ($refused -eq 5)
    Chk 'SID safety: operator SID refused' ((Test-CoderSidSafe $sid $sid @()).Count -ge 1)
    Chk 'SID safety: group in the operator token refused' ((Test-CoderSidSafe $sid $other @($sid)).Count -ge 1)
    Chk 'SID safety: a distinct account SID accepted' ((Test-CoderSidSafe $sid $other @('S-1-5-32-545')).Count -eq 0)
    Write-Host '== arm 1 filter sets ==' -ForegroundColor Cyan
    $pOn = Get-ArmPlan -Sid $sid -PermitOn $true; $pOff = Get-ArmPlan -Sid $sid -PermitOn $false
    Chk 'permit on: four filters, invariants hold' (($pOn.Filters.Count -eq 4) -and ((Test-ArmPlanInvariants -Plan $pOn -PermitOn $true).Count -eq 0))
    Chk 'permit off: exactly the two BLOCK filters, no loopback condition, invariants hold' (($pOff.Filters.Count -eq 2) -and (@($pOff.Filters | Where-Object { $_.Action -ne [BlarAI.Wfp.Plan]::FWP_ACTION_BLOCK -or $_.Loopback }).Count -eq 0) -and ((Test-ArmPlanInvariants -Plan $pOff -PermitOn $false).Count -eq 0))
    Chk 'permit off: the block filters are the same keys as in the four-filter plan' ((@($pOff.Filters | ForEach-Object { $_.Key }) -join ',') -eq (@($pOn.Filters | Where-Object { $_.Action -eq [BlarAI.Wfp.Plan]::FWP_ACTION_BLOCK } | ForEach-Object { $_.Key }) -join ','))
    Chk 'invariants: the four-filter plan labelled permit off is refused' ((Test-ArmPlanInvariants -Plan $pOn -PermitOn $false).Count -ge 1)
    Chk 'invariants: the two-filter plan labelled permit on is refused' ((Test-ArmPlanInvariants -Plan $pOff -PermitOn $true).Count -ge 1)
    Chk 'the SD is identical in both sets' ($pOn.Sddl -eq $pOff.Sddl)
    Write-Host '== argument validation ==' -ForegroundColor Cyan
    Chk 'no mode -> error' ((Test-WfpArgs $false $false $false $false 420 60 900).Count -ge 1)
    Chk 'two modes -> error' ((Test-WfpArgs $false $true $true $false 420 60 900).Count -ge 1)
    Chk '-TestB with defaults valid' ((Test-WfpArgs $false $false $false $true 420 60 900).Count -eq 0)
    Chk 'serve hold >= block max rejected' ((Test-WfpArgs $false $false $false $true 100 100 900).Count -ge 1)
    Chk 'block max 0 / 901 rejected' (((Test-WfpArgs $false $false $false $true 0 60 900).Count -ge 1) -and ((Test-WfpArgs $false $false $false $true 901 60 900).Count -ge 1))
    Chk '-TestC alone valid, with -NoLoopbackPermit valid' (((Test-WfpArgs $false $false $false $false 420 60 900 $true $false).Count -eq 0) -and ((Test-WfpArgs $false $false $false $false 420 60 900 $true $true).Count -eq 0))
    Chk '-TestC with -TestB rejected; -NoLoopbackPermit with -TestB rejected' (((Test-WfpArgs $false $false $false $true 420 60 900 $true $false).Count -ge 1) -and ((Test-WfpArgs $false $false $false $true 420 60 900 $false $true).Count -ge 1))
    Chk 'server load timeout 10 / 901 rejected' (((Test-WfpArgs $false $false $false $false 420 60 900 $true $false 10).Count -ge 1) -and ((Test-WfpArgs $false $false $false $false 420 60 900 $true $false 901).Count -ge 1))
    Write-Host '== Test B verdict table (fabricated observations; each variant must be able to fail) ==' -ForegroundColor Cyan
    $good = @{ OperatorAbort = $false; RemovalVerified = $true; BaselineOk = $true; OperatorFailures = 0; TaskStarted = $true; ResultValid = $true; SidIsSpike = $true; SpikeOutboundBlocked = $true; ServeStarted = $true; OperatorReachedListener = $true; ModelLoaded = $true; OperatorGotModelCompletion = $true }
    function V($over) { $o = $good.Clone(); foreach ($k in $over.Keys) { $o[$k] = $over[$k] }; (Get-TestBVerdict ([pscustomobject]$o)).Code }
    Chk 'all good -> 0' ((V @{}) -eq 0)
    Chk 'operator abort -> 3 (beats everything)' ((V @{ OperatorAbort = $true; RemovalVerified = $false }) -eq 3)
    Chk 'removal unverified -> 7' ((V @{ RemovalVerified = $false; SpikeOutboundBlocked = $false }) -eq 7)
    Chk 'no baseline -> 5' ((V @{ BaselineOk = $false }) -eq 5)
    Chk 'isolated operator failure -> 4' ((V @{ OperatorFailures = 1 }) -eq 4)
    Chk 'task never started -> 4' ((V @{ TaskStarted = $false }) -eq 4)
    Chk 'invalid result -> 4' ((V @{ ResultValid = $false }) -eq 4)
    Chk 'wrong SID -> 4' ((V @{ SidIsSpike = $false }) -eq 4)
    Chk 'spike not blocked -> 1' ((V @{ SpikeOutboundBlocked = $false }) -eq 1)
    Chk 'listener never started -> 4' ((V @{ ServeStarted = $false }) -eq 4)
    Chk 'operator could not reach the listener -> 4' ((V @{ OperatorReachedListener = $false }) -eq 4)
    Chk 'model not loaded (fixed string only) -> 8, never 0' ((V @{ ModelLoaded = $false; OperatorGotModelCompletion = $false }) -eq 8)
    Chk 'model loaded but no completion -> 4' ((V @{ OperatorGotModelCompletion = $false }) -eq 4)
    Write-Host '== Test C verdict table (fabricated observations; each variant must be able to fail) ==' -ForegroundColor Cyan
    $goodC = @{ OperatorAbort = $false; RemovalVerified = $true; BaselineOk = $true; ServerModelLoaded = $true; OperatorFailures = 0; BlockRunValid = $true; AfterRunValid = $true; SpikeOutboundBlocked = $true; ClientOkUnderBlock = $true; ClientSocketDenied = $false }
    function VC($over) { $o = $goodC.Clone(); foreach ($k in $over.Keys) { $o[$k] = $over[$k] }; (Get-TestCVerdict ([pscustomobject]$o)).Code }
    Chk 'C: all good, client ok -> 0' ((VC @{}) -eq 0)
    Chk 'C: client failed WITH a socket error code -> 9 (a result)' ((VC @{ ClientOkUnderBlock = $false; ClientSocketDenied = $true }) -eq 9)
    Chk 'C: client failed WITHOUT a socket error code (HTTP 500 / timeout) -> 4, never 9' ((VC @{ ClientOkUnderBlock = $false; ClientSocketDenied = $false }) -eq 4)
    Chk 'C: after-run invalid -> 4, not 7' ((VC @{ AfterRunValid = $false }) -eq 4)
    Chk 'C: operator abort -> 3 (beats everything)' ((VC @{ OperatorAbort = $true; RemovalVerified = $false; BaselineOk = $false }) -eq 3)
    Chk 'C: removal unverified -> 7' ((VC @{ RemovalVerified = $false; SpikeOutboundBlocked = $false }) -eq 7)
    Chk 'C: no baseline -> 5' ((VC @{ BaselineOk = $false; ClientOkUnderBlock = $false }) -eq 5)
    Chk 'C: server model not loaded -> 8, never 0 or 9' ((VC @{ ServerModelLoaded = $false }) -eq 8)
    Chk 'C: isolated operator failure -> 4' ((VC @{ OperatorFailures = 1 }) -eq 4)
    Chk 'C: block run invalid -> 4' ((VC @{ BlockRunValid = $false }) -eq 4)
    Chk 'C: account not blocked -> 1' ((VC @{ SpikeOutboundBlocked = $false }) -eq 1)
    Write-Host '== client-mode result schema ==' -ForegroundColor Cyan
    $tc = (Get-Date).ToString("yyyy-MM-dd'T'HH:mm:ss.fffzzz")
    $mkC = { param($names) [pscustomobject]@{ schema_version = 1; run_id = 'testc-on-20261009-120000-block'; mode = 'client'; started = $tc; finished = $tc; overall = 'pass'; steps = @($names | ForEach-Object { [pscustomobject]@{ name = $_; status = 'pass'; started = $tc; finished = $tc; detail = 'x'; data = $null } }) } }
    Chk 'client result with identity, client_connect, outbound_probe is valid' ((Test-SpikeResultSchema (& $mkC @('identity', 'client_connect', 'outbound_probe'))).Count -eq 0)
    Chk 'client result missing client_connect is refused' ((Test-SpikeResultSchema (& $mkC @('identity', 'outbound_probe'))).Count -ge 1)
    $rt = ConvertFrom-Json (ConvertTo-Json -InputObject (& $mkC @('identity', 'client_connect', 'outbound_probe')) -Depth 8)
    Chk 'client result still valid after a JSON round-trip on THIS host (pwsh parses timestamps into [datetime])' ((Test-SpikeResultSchema $rt).Count -eq 0)
    Chk 'timestamp helper: string, [datetime] and [datetimeoffset] all convert' (((ConvertTo-DateTimeOffset $tc) -is [datetimeoffset]) -and ((ConvertTo-DateTimeOffset (Get-Date)) -is [datetimeoffset]) -and ((ConvertTo-DateTimeOffset ([datetimeoffset]::Now)) -is [datetimeoffset]))
    Chk 'timestamp check: a bare string without offset is still refused' (-not (Test-IsoTimestamp '2026-10-09T12:00:00'))
    Chk 'serve result is NOT satisfied by the client step list' ((Test-SpikeResultSchema ([pscustomobject]@{ schema_version = 1; run_id = 'testc-on-20261009-120000-block'; mode = 'serve'; started = $tc; finished = $tc; overall = 'pass'; steps = (& $mkC @('identity', 'client_connect', 'outbound_probe')).steps })).Count -ge 1)
    Write-Host '== arm 2: long hold (argument rules, schedule, watchdog, outcomes, exports, Bitdefender signals, verdicts) ==' -ForegroundColor Cyan
    Chk '-LongHold alone with defaults is valid' ((Test-WfpArgs $false $false $false $false 420 60 900 $false $false 240 $true 3600 60).Count -eq 0)
    Chk '-LongHold with -TestC rejected (exactly one mode)' ((Test-WfpArgs $false $false $false $false 420 60 900 $true $false 240 $true 3600 60).Count -ge 1)
    Chk 'hold 59 and 7201 rejected; 60 and 7200 accepted' (((Test-WfpArgs $false $false $false $false 420 60 900 $false $false 240 $true 59 30).Count -ge 1) -and ((Test-WfpArgs $false $false $false $false 420 60 900 $false $false 240 $true 7201 60).Count -ge 1) -and ((Test-WfpArgs $false $false $false $false 420 60 900 $false $false 240 $true 60 30).Count -eq 0) -and ((Test-WfpArgs $false $false $false $false 420 60 900 $false $false 240 $true 7200 60).Count -eq 0))
    Chk 'sample 29 and 301 rejected; a sample longer than the hold rejected' (((Test-WfpArgs $false $false $false $false 420 60 900 $false $false 240 $true 3600 29).Count -ge 1) -and ((Test-WfpArgs $false $false $false $false 420 60 900 $false $false 240 $true 3600 301).Count -ge 1) -and ((Test-WfpArgs $false $false $false $false 420 60 900 $false $false 240 $true 60 120).Count -ge 1))
    Chk '-LongHold with -NoLoopbackPermit is valid (the two-filter set)' ((Test-WfpArgs $false $false $false $false 420 60 900 $false $true 240 $true 3600 60).Count -eq 0)
    $sc = Get-HoldSchedule -Hold 3600 -Sample 60
    Chk 'schedule 3600/60: 60 samples at 0..3540, mid export at 1800, dead-man at 3630' (($sc.Expected -eq 60) -and ($sc.SampleOffsets[0] -eq 0) -and ($sc.SampleOffsets[59] -eq 3540) -and ($sc.MidExportAt -eq 1800) -and ($sc.DeadManAt -eq 3630))
    Chk 'schedule 7200/60: 120 samples, dead-man at 7230; 90/60: samples at 0 and 60' (((Get-HoldSchedule -Hold 7200 -Sample 60).Expected -eq 120) -and ((Get-HoldSchedule -Hold 7200 -Sample 60).DeadManAt -eq 7230) -and ((Get-HoldSchedule -Hold 90 -Sample 60).SampleOffsets -join ',') -eq '0,60')
    $w = New-WatchdogState
    Chk 'watchdog: one failure does not abort' (-not (Update-WatchdogState -State $w -Ok $false -When 't1' -Message 'e' -Ms 5))
    Chk 'watchdog: a success resets the run; fail, ok, fail never aborts (2 failures, max consecutive 1)' ((-not (Update-WatchdogState -State $w -Ok $true)) -and (-not (Update-WatchdogState -State $w -Ok $false -When 't3' -Message 'e' -Ms 5)) -and ($w.Fail -eq 2) -and ($w.MaxConsec -eq 1))
    Chk 'watchdog: two consecutive failures abort' (Update-WatchdogState -State $w -Ok $false -When 't4' -Message 'e' -Ms 5)
    $w2 = New-WatchdogState; 1..300 | ForEach-Object { [void](Update-WatchdogState -State $w2 -Ok $false) ; [void](Update-WatchdogState -State $w2 -Ok $true) }
    Chk 'watchdog: failure events are capped at 200 while the count keeps going' (($w2.Events.Count -eq 200) -and ($w2.Fail -eq 300))
    $script:opAbort = $false
    function Wait-Fake([scriptblock]$Tick) { & $Tick; return [bool]$script:opAbort }
    $seen = Wait-Fake { $script:opAbort = $true }; $script:opAbort = $false
    $seenClosure = Wait-Fake ({ $script:opAbort = $true }.GetNewClosure()); $script:opAbort = $false
    Chk 'an abort flag set inside a plain tick scriptblock IS seen by the waiting function (the form -LongHold uses)' $seen
    Chk 'toggle: the same flag set inside a .GetNewClosure() scriptblock is NOT seen (why -LongHold does not use a closure)' (-not $seenClosure)
    $mkRun = { param($valid, $sid, $connected) [pscustomobject]@{ valid = $valid; token_sid = $sid; outbound_probe = [pscustomobject]@{ probe = [pscustomobject]@{ connected = $connected; error_code = 10013; error = 'denied'; ms = 3 }; blocked = (-not $connected) } } }
    $S1 = 'S-1-5-21-1111111111-2222222222-3333333333-1001'
    Chk 'sample outcome: valid run as the right SID, connect failed -> blocked' ((Get-SampleOutcome -Run (& $mkRun $true $S1 $false) -Sid $S1) -eq 'blocked')
    Chk 'sample outcome: connect succeeded -> open' ((Get-SampleOutcome -Run (& $mkRun $true $S1 $true) -Sid $S1) -eq 'open')
    Chk 'sample outcome: invalid run, null run, or no probe -> no_result (never blocked)' (((Get-SampleOutcome -Run (& $mkRun $false $S1 $false) -Sid $S1) -eq 'no_result') -and ((Get-SampleOutcome -Run $null -Sid $S1) -eq 'no_result') -and ((Get-SampleOutcome -Run ([pscustomobject]@{ valid = $true; token_sid = $S1; outbound_probe = $null }) -Sid $S1) -eq 'no_result'))
    Chk 'sample outcome: a run as another SID -> wrong_sid (never blocked)' ((Get-SampleOutcome -Run (& $mkRun $true 'S-1-5-21-1111111111-2222222222-3333333333-1002' $false) -Sid $S1) -eq 'wrong_sid')
    $line = Format-SampleLine -N 7 -When '2026-10-11T10:00:00.000+01:00' -OffsetSeconds 360.04 -Outcome 'blocked' -Probe ([pscustomobject]@{ error_code = 10013; error = 'denied'; ms = 3 }) -RunId 'hold-on-20261011-100000-s0007' -TaskDetail 'state=Running'
    $lp = ConvertFrom-Json $line
    Chk 'sample line: ONE line of JSON with n, a timestamp with offset, the outcome and the socket error code' (($line -notmatch "[\r\n]") -and ($lp.n -eq 7) -and ($lp.outcome -eq 'blocked') -and ($lp.error_code -eq 10013) -and ($line -match '"t":"2026-10-11T10:00:00.000\+01:00"') -and ($lp.offset_s -eq 360))
    $samp = @(1..5 | ForEach-Object { ConvertFrom-Json (Format-SampleLine -N $_ -When '2026-10-11T10:00:00.000+01:00' -OffsetSeconds ($_ * 60) -Outcome 'blocked' -Probe ([pscustomobject]@{ error_code = 10013; error = 'd'; ms = 1 }) -RunId 'x' -TaskDetail 'x') }) + @(ConvertFrom-Json (Format-SampleLine -N 6 -When '2026-10-11T10:06:00.000+01:00' -OffsetSeconds 360 -Outcome 'open' -Probe ([pscustomobject]@{ error_code = 0; error = ''; ms = 40 }) -RunId 'x' -TaskDetail 'x')) + @(ConvertFrom-Json (Format-SampleLine -N 7 -When '2026-10-11T10:07:00.000+01:00' -OffsetSeconds 420 -Outcome 'no_result' -Probe $null -RunId 'x' -TaskDetail 'x'))
    $stt = Get-SampleStats $samp
    Chk 'sample stats: 5 blocked (all code 10013), 1 open, 1 no_result, first open is sample 6' (($stt.total -eq 7) -and ($stt.blocked -eq 5) -and ($stt.open -eq 1) -and ($stt.no_result -eq 1) -and ($stt.blocked_error_codes['10013'] -eq 5) -and ($stt.first_open.n -eq 6))
    $keys4 = @('f1100001-0000-4d8e-9a31-2b6d4c8e1f11', 'f1100002-0000-4d8e-9a31-2b6d4c8e1f12', 'f1100003-0000-4d8e-9a31-2b6d4c8e1f21', 'f1100004-0000-4d8e-9a31-2b6d4c8e1f22')
    $xmlOk = '<wfpdiag>' + (($keys4 | ForEach-Object { "<filter><filterKey>{$($_.ToUpper())}</filterKey><displayData><name>BlarAI #1671 spike: x</name></displayData></filter>" }) -join '') + '</wfpdiag>'
    Chk 'export summary: every key (upper case, braces) and the marker present -> ok' ((Get-FilterExportSummary -Text $xmlOk -Marker 'BlarAI #1671' -ExpectedKeys $keys4).ok)
    Chk 'export summary: one key missing -> not ok, and the missing key is named' ((-not (Get-FilterExportSummary -Text $xmlOk.Replace($keys4[2].ToUpper(), 'X') -Marker 'BlarAI #1671' -ExpectedKeys $keys4).ok) -and ((Get-FilterExportSummary -Text $xmlOk.Replace($keys4[2].ToUpper(), 'X') -Marker 'BlarAI #1671' -ExpectedKeys $keys4).keys_missing -contains $keys4[2]))
    Chk 'export summary: keys present but the marker absent, or an empty export -> not ok' ((-not (Get-FilterExportSummary -Text $xmlOk.Replace('BlarAI #1671', 'other') -Marker 'BlarAI #1671' -ExpectedKeys $keys4).ok) -and (-not (Get-FilterExportSummary -Text '' -Marker 'BlarAI #1671' -ExpectedKeys $keys4).ok))
    Chk 'export text: UTF-8 and UTF-16 (BOM) both decode' (((Read-ExportText ([Text.Encoding]::UTF8.GetBytes('abc BlarAI #1671'))) -eq 'abc BlarAI #1671') -and ((Read-ExportText (@(0xFF, 0xFE) + [Text.Encoding]::Unicode.GetBytes('x'))) -match 'x'))
    $hs = [datetimeoffset]::Parse('2026-10-11T10:00:00+01:00')
    $bdA = [pscustomobject]@{ processes = @([pscustomobject]@{ name = 'bdagent'; id = 1; start = '2026-10-11T08:00:00+01:00' }); folders = @([pscustomobject]@{ path = 'C:\bd'; last_write = '2026-10-11T08:00:00+01:00' }) }
    $bdSame = [pscustomobject]@{ processes = $bdA.processes; folders = $bdA.folders }
    $bdUpd = [pscustomobject]@{ processes = @($bdA.processes) + @([pscustomobject]@{ name = 'bdupdate'; id = 9; start = '2026-10-11T10:30:00+01:00' }); folders = $bdA.folders }
    $bdDir = [pscustomobject]@{ processes = $bdA.processes; folders = @([pscustomobject]@{ path = 'C:\bd'; last_write = '2026-10-11T10:40:00+01:00' }) }
    $bdOld = [pscustomobject]@{ processes = @($bdA.processes) + @([pscustomobject]@{ name = 'updatesrv'; id = 5; start = '2026-10-11T07:00:00+01:00' }); folders = $bdA.folders }
    Chk 'Bitdefender signal: nothing changed -> none_observed (with its caveat)' (((Compare-BitdefenderSnapshots -A $bdA -B $bdSame -HoldStart $hs).signal -eq 'none_observed') -and ((Compare-BitdefenderSnapshots -A $bdA -B $bdSame -HoldStart $hs).caveat -match 'does not show'))
    Chk 'Bitdefender signal: an update-named process started during the hold -> named' (((Compare-BitdefenderSnapshots -A $bdA -B $bdUpd -HoldStart $hs).signal -eq 'update_named_process_started_during_hold') -and ((Compare-BitdefenderSnapshots -A $bdA -B $bdUpd -HoldStart $hs).processes_added.Count -eq 1))
    Chk 'Bitdefender signal: a transient update process seen between samples counts' ((Compare-BitdefenderSnapshots -A $bdA -B $bdSame -HoldStart $hs -SeenDuring @([pscustomobject]@{ name = 'bdupdate'; id = 11; start = '2026-10-11T10:10:00+01:00' })).signal -eq 'update_named_process_started_during_hold')
    Chk 'Bitdefender signal: an update service running since BEFORE the hold is not a signal; a folder timestamp that moved is' (((Compare-BitdefenderSnapshots -A $bdOld -B $bdOld -HoldStart $hs).signal -eq 'none_observed') -and ((Compare-BitdefenderSnapshots -A $bdA -B $bdDir -HoldStart $hs).signal -eq 'bitdefender_folder_timestamps_changed'))
    $goodH = @{ OperatorAbort = $false; RemovalVerified = $true; BaselineOk = $true; EngineClosedEarly = $false; SamplesOpen = 0; SamplesBlocked = 60; SamplesExpected = 60; ExportsOk = $true }
    function VH($over) { $o = $goodH.Clone(); foreach ($k in $over.Keys) { $o[$k] = $over[$k] }; (Get-LongHoldVerdict ([pscustomobject]$o)).Code }
    Chk 'H: all good -> 0' ((VH @{}) -eq 0)
    Chk 'H: 54 of 60 blocked (90%) still 0; 53 of 60 -> 4' (((VH @{ SamplesBlocked = 54 }) -eq 0) -and ((VH @{ SamplesBlocked = 53 }) -eq 4))
    Chk 'H: one open sample -> 1 (the block did not hold), whatever the coverage' (((VH @{ SamplesOpen = 1; SamplesBlocked = 59 }) -eq 1) -and ((VH @{ SamplesOpen = 1; SamplesBlocked = 2 }) -eq 1))
    Chk 'H: operator abort -> 3 (beats everything)' ((VH @{ OperatorAbort = $true; RemovalVerified = $false; BaselineOk = $false; SamplesOpen = 5 }) -eq 3)
    Chk 'H: removal unverified -> 7 (beats an open sample)' ((VH @{ RemovalVerified = $false; SamplesOpen = 5 }) -eq 7)
    Chk 'H: no baseline -> 5' ((VH @{ BaselineOk = $false }) -eq 5)
    Chk 'H: engine closed early -> 4, even if samples then read open' ((VH @{ EngineClosedEarly = $true; SamplesOpen = 3 }) -eq 4)
    Chk 'H: an export missing a filter -> 4, never 0' ((VH @{ ExportsOk = $false }) -eq 4)
    Chk 'H: a 3-sample hold needs all 3 (floor of 3)' (((VH @{ SamplesExpected = 3; SamplesBlocked = 3 }) -eq 0) -and ((VH @{ SamplesExpected = 3; SamplesBlocked = 2 }) -eq 4))
    $mkP = { param($names) [pscustomobject]@{ schema_version = 1; run_id = 'hold-on-20261011-100000-s0001'; mode = 'probe'; started = $tc; finished = $tc; overall = 'pass'; steps = @($names | ForEach-Object { [pscustomobject]@{ name = $_; status = 'pass'; started = $tc; finished = $tc; detail = 'x'; data = $null } }) } }
    Chk 'probe result with identity and outbound_probe is valid' ((Test-SpikeResultSchema (& $mkP @('identity', 'outbound_probe'))).Count -eq 0)
    Chk 'probe result missing outbound_probe, or missing identity, is refused' (((Test-SpikeResultSchema (& $mkP @('identity'))).Count -ge 1) -and ((Test-SpikeResultSchema (& $mkP @('outbound_probe'))).Count -ge 1))
    Chk 'a feasibility-mode result is not satisfied by the probe step list' ((Test-SpikeResultSchema ([pscustomobject]@{ schema_version = 1; run_id = 'hold-on-20261011-100000-s0001'; mode = 'feasibility'; started = $tc; finished = $tc; overall = 'pass'; steps = (& $mkP @('identity', 'outbound_probe')).steps })).Count -ge 1)
    Chk 'the target account is the throwaway spike account, never blarai-coder (the real coder account''s containment state is not touched)' (($script:SpikeUser -eq 'blarai-spike') -and ($script:SpikeUser -ne 'blarai-coder'))
    Chk 'keep-awake constants (ES_CONTINUOUS 0x80000000, ES_SYSTEM_REQUIRED 0x1); nothing is called' (([SpikePower]::ES_CONTINUOUS -eq 2147483648) -and ([SpikePower]::ES_SYSTEM_REQUIRED -eq 1))
    Write-Host '== Test A verdict ==' -ForegroundColor Cyan
    $t = (Get-Date).ToString("yyyy-MM-dd'T'HH:mm:ss.fffzzz")
    $mk = { param($bad) [pscustomobject]@{ steps = @($script:StepNamesBase | ForEach-Object { [pscustomobject]@{ name = $_; status = $(if ($bad -contains $_) { 'fail' } else { 'pass' }) } }) } }
    Chk 'all pass -> 0' ((Get-TestAVerdict (& $mk @()) @()).Code -eq 0)
    Chk 'only the GPU step failed -> 8' ((Get-TestAVerdict (& $mk @('gpu_feasibility')) @()).Code -eq 8)
    Chk 'GPU + file denial failed -> 4' ((Get-TestAVerdict (& $mk @('gpu_feasibility', 'file_denial')) @()).Code -eq 4)
    Chk 'schema violations -> 4' ((Get-TestAVerdict (& $mk @()) @('x')).Code -eq 4)
    Write-Host '== untrusted result files (written by the restricted account) ==' -ForegroundColor Cyan
    $ub = Join-Path ([IO.Path]::GetTempPath()) ('spike-readtest-' + [guid]::NewGuid().ToString('N')); New-Item -ItemType Directory -Path $ub | Out-Null
    try {
        $good = Join-Path $ub 'good.json'; Set-Content -LiteralPath $good -Value '{"port": 50000}'
        Chk 'reader: parses an ordinary file' ((Read-UntrustedJson -Path $good).port -eq 50000)
        $secretFile = Join-Path $ub 'secret.json'; Set-Content -LiteralPath $secretFile -Value '{"secret": "operator-data"}'
        $jd = Join-Path $ub 'jdir'; New-Item -ItemType Junction -Path $jd -Target $ub | Out-Null
        $rj = $false; try { [void](Read-UntrustedJson -Path (Join-Path $jd 'good.json')) } catch { $rj = $true }
        Chk 'reader: refuses a file whose folder is a directory junction' $rj
        [IO.Directory]::Delete($jd, $false)
        $sl = $true; $lf = Join-Path $ub 'link.json'; try { New-Item -ItemType SymbolicLink -Path $lf -Target $secretFile | Out-Null } catch { $sl = $false }
        if ($sl) { $rs = $false; try { [void](Read-UntrustedJson -Path $lf) } catch { $rs = $true }; Chk 'reader: refuses a symlink in the place of the file' $rs } else { Write-Host '  [SKIP] symlinks cannot be created here' -ForegroundColor Yellow }
        $hl = $true; $hf = Join-Path $ub 'hard.json'; try { New-Item -ItemType HardLink -Path $hf -Target $secretFile | Out-Null } catch { $hl = $false }
        if ($hl) { $rh = $false; try { [void](Read-UntrustedJson -Path $hf) } catch { $rh = $true }; Chk 'reader: refuses a hard-linked file' $rh } else { Write-Host '  [SKIP] hard links cannot be created here' -ForegroundColor Yellow }
        $big = Join-Path $ub 'big.json'; [IO.File]::WriteAllBytes($big, (New-Object byte[] 70000))
        $rb = $false; try { [void](Read-UntrustedJson -Path $big -MaxBytes 65536) } catch { $rb = $true }
        Chk 'reader: refuses a file over the size cap' $rb
        $bad = Join-Path $ub 'bad.json'; Set-Content -LiteralPath $bad -Value '{not json'
        $rp = $false; try { [void](Read-UntrustedJson -Path $bad) } catch { $rp = $true }
        Chk 'reader: malformed JSON throws (fail closed)' $rp
        Chk 'port check: accepts 49580, refuses 80, 70000, a string, a float, null' ((Test-LoopbackPort 49580) -and -not (Test-LoopbackPort 80) -and -not (Test-LoopbackPort 70000) -and -not (Test-LoopbackPort '49580') -and -not (Test-LoopbackPort 49580.5) -and -not (Test-LoopbackPort $null))
    } finally { Remove-TreeNoFollow -Root $ub }
    Write-Host ("wfp selftest: {0}" -f $(if ($script:f -eq 0) { 'all passed' } else { "$($script:f) FAILED" })) -ForegroundColor $(if ($script:f -eq 0) { 'Green' } else { 'Red' })
    return $(if ($script:f -eq 0) { 0 } else { 1 })
}

function Invoke-DryRun {
    Write-Host '== DRY RUN: nothing is added; the WFP engine is NOT opened ==' -ForegroundColor Yellow
    $imp = Import-WfpHelpers -Path $WfpScript
    Write-Host "wrapped script: $($imp.Path)`n  sha256 $($imp.Sha256)`n  extracted: $($imp.Functions -join ', ') + the embedded C# ($($imp.CsharpChars) chars); the file itself is not modified or executed"
    Initialize-WfpType
    $sid = Get-SpikeSidOrNull; $fab = $false
    if (-not $sid) { $sid = 'S-1-5-21-1111111111-2222222222-3333333333-1001'; $fab = $true; Write-Host "account '$($script:SpikeUser)' not found: using a FABRICATED SID to build the plan ($sid). -TestA/-TestB would exit 2." -ForegroundColor Yellow }
    else { Write-Host "spike SID: $sid" }
    $op = Get-OperatorTokenSids
    $safety = Test-CoderSidSafe $sid $op.User $op.Groups
    Write-Host ("operator SID {0}; SID safety: {1}" -f $op.User, $(if ($safety.Count -eq 0) { 'OK' } else { 'REFUSED: ' + ($safety -join '; ') }))
    $plan = [BlarAI.Wfp.Plan]::Build($sid)
    Write-Host ''; Write-Host '--- filter set permit_on (TestA/TestB/TestC default): 4 filters ---'; Write-Host $plan.Describe()
    $off = Get-ArmPlan -Sid $sid -PermitOn $false
    Write-Host '--- filter set permit_off (TestC -NoLoopbackPermit): 2 filters ---'; Write-Host $off.Describe()
    Write-Host ("this invocation would install: {0}" -f $(if ($NoLoopbackPermit) { 'permit_off (2 filters)' } else { 'permit_on (4 filters)' }))
    Write-Host 'TEST A sequence : preflight -> request.json(mode=feasibility) -> Start-ScheduledTask (+start proof) -> wait for result (<= ResultTimeoutSeconds) -> strict-schema check -> report'
    Write-Host 'TEST B sequence : preflight (+ WFP objects absent) -> operator baseline 3x 1.1.1.1:443 -> add dynamic block (+dead-man) -> request.json(mode=serve) -> start task -> watchdog every 2 s while waiting for serve-port-<run>.json -> operator POST /completion on 127.0.0.1:<port> -> wait for result (block still live) -> close engine -> verify removal -> report'
    Write-Host 'TEST C sequence : preflight (+ WFP objects absent, venv + spike_model.py present, >= 14 GB free) -> start spike_model.py serve AS THE OPERATOR (127.0.0.1:<ephemeral>, port file, health GET) -> operator baseline 3x 1.1.1.1:443 -> ACCOUNT run 1 (client mode, filters absent: POST must succeed, egress must be open) -> fresh dynamic engine + dead-man, add the filter set -> ACCOUNT run 2 under the block (watchdog every 2 s; POST + 1.1.1.1:443 probe) -> close engine (timestamped) -> verify removal -> ACCOUNT run 3 (egress must be open again) -> stop the server (stop file; its request log is read) -> report'
    $holdErr = @(Test-WfpArgs $false $false $false $false 420 60 900 $false $false 240 $true $HoldSeconds $SampleSeconds)
    if ($holdErr.Count) { $holdErr | ForEach-Object { Write-Host "ARG ERROR (-LongHold would refuse): $_" -ForegroundColor Red }; return 2 }
    $hs = Get-HoldSchedule -Hold $HoldSeconds -Sample $SampleSeconds
    $holdSet = $(if ($NoLoopbackPermit) { 'permit_off (2 filters)' } else { 'permit_on (4 filters)' })
    Write-Host ("LONG HOLD (-LongHold, arm 2): hold {0} s, sample every {1} s => {2} samples (first at +0 s, last at +{3} s); dead-man at {4} s; operator watchdog every {5} s (two consecutive failures = engine closed, exit 3)" -f $HoldSeconds, $SampleSeconds, $hs.Expected, $hs.SampleOffsets[-1], $hs.DeadManAt, $script:WatchdogSeconds)
    Write-Host ("  filter set this invocation would install: {0}; run id hold-<on|off>-<stamp>; outputs in {1}" -f $holdSet, $HoldOutDir)
    Write-Host '  sequence : target SID safety (exit 3 if the operator or one of his groups) -> preflight (elevated, 64-bit, account, task, bin copies equal to this folder, no stale WFP objects; NO free-RAM check: probe mode loads no model) -> wsl --shutdown (before/after distribution list recorded) -> keep-awake (SetThreadExecutionState, released at the end) -> operator baseline 3x 1.1.1.1:443 -> ACCOUNT baseline probe (task, probe mode, filters absent: egress must be open) -> Bitdefender snapshot (processes + install-folder timestamps) -> fresh dynamic engine + dead-man -> add the filter set -> export start -> every 2 s operator watchdog; every sample: Start-ScheduledTask (probe mode) -> one JSON line appended to <run>-samples.txt -> at HoldSeconds/2 export mid; on the FIRST sample that is not blocked an extra export on-first-open -> export end -> Bitdefender snapshot + comparison -> close engine (timestamped) -> verify removal -> ACCOUNT probe after removal (egress must be open again) -> report <run>.json'
    Write-Host ('  exports  : netsh wfp show filters file="{0}\<run>-filters-<start|mid|end|on-first-open>.xml"; each is searched for the marker "{1}" and for every filter key of the set (a missing key makes the run inconclusive); raw exports stay in the research-data folder and are NOT bundled' -f $HoldOutDir, $script:HoldMarker)
    Write-Host '  exit     : 0 held all samples | 1 a sample was NOT blocked | 2 precondition | 3 operator affected or unsafe target | 4 inconclusive | 5 no baseline | 7 removal not verified'
    Write-Host ("parameters      : BlockMaxSeconds={0}  ServeHoldSeconds={1}  ResultTimeoutSeconds={2}  ServerLoadTimeoutSeconds={3}" -f $BlockMaxSeconds, $ServeHoldSeconds, $ResultTimeoutSeconds, $ServerLoadTimeoutSeconds)
    Write-Host "operator reports: $OutDir\testA-*.json / testB-*.json / testC-*.json; the server's files: $OutDir\server\; the task's own results: C:\blarai-spike\results\result-<run>.json"
    $t = Get-ScheduledTask -TaskPath $script:SpikeTaskPath -TaskName $script:SpikeTaskName -ErrorAction SilentlyContinue
    Write-Host $(if ($t) { "task present, State=$($t.State)" } else { 'task NOT registered (provision first)' })
    Write-Host 'DRY RUN complete. Nothing was added.' -ForegroundColor Green
    if ($fab) { return 2 }
    return 0
}

# ---- entry --------------------------------------------------------------------------------------------------------
$argErrors = Test-WfpArgs $SelfTest.IsPresent $DryRun.IsPresent $TestA.IsPresent $TestB.IsPresent $BlockMaxSeconds $ServeHoldSeconds $ResultTimeoutSeconds $TestC.IsPresent $NoLoopbackPermit.IsPresent $ServerLoadTimeoutSeconds $LongHold.IsPresent $HoldSeconds $SampleSeconds
if ($argErrors.Count) { $argErrors | ForEach-Object { Write-Host "ARG ERROR: $_" -ForegroundColor Red }; exit 2 }
try {
    if ($SelfTest) { exit (Invoke-SelfTest) }
    if ($DryRun)   { exit (Invoke-DryRun) }
    $null = Import-WfpHelpers -Path $WfpScript
    if ($TestA)    { exit (Invoke-TestA) }
    if ($TestB)    { exit (Invoke-TestB) }
    if ($TestC)    { exit (Invoke-TestC) }
    if ($LongHold) { exit (Invoke-LongHold) }
} catch {
    Write-Host "STOPPED: $($_.Exception.Message)" -ForegroundColor Red
    exit 2
}
