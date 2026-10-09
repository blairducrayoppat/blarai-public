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
    param([bool]$SelfTest, [bool]$DryRun, [bool]$TestA, [bool]$TestB, [int]$BlockMax, [int]$ServeHold, [int]$ResultTimeout)
    $e = New-Object System.Collections.ArrayList
    $modes = @($SelfTest, $DryRun, $TestA, $TestB) | Where-Object { $_ }
    if (@($modes).Count -ne 1) { [void]$e.Add('choose exactly one of -SelfTest, -DryRun, -TestA, -TestB') }
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
    # runs: 0x41303). Returns @{ Started; Detail }.
    $pre = [datetime]'1999-11-30'
    try { $pr = (Get-ScheduledTaskInfo -TaskPath $script:SpikeTaskPath -TaskName $script:SpikeTaskName -ErrorAction Stop).LastRunTime; if ($pr) { $pre = $pr } } catch {}
    Start-ScheduledTask -TaskPath $script:SpikeTaskPath -TaskName $script:SpikeTaskName
    $last = $null; $state = ''
    foreach ($i in 1..30) {
        Start-Sleep -Milliseconds 750
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
        if (Test-Path -LiteralPath $path) { Start-Sleep -Milliseconds 300; return (Get-Content -LiteralPath $path -Raw | ConvertFrom-Json) }
        if ($Tick) { & $Tick }
        Start-Sleep -Milliseconds 1000
    }
    return $null
}

function Write-SpikeRequest {
    param([string]$RunId, [string]$Mode, [int]$Hold, [bool]$ExpectedBlocked)
    Write-JsonAtomic -Path (Join-Path $script:SpikeRoot 'bin\request.json') -Object ([ordered]@{ run_id = $RunId; mode = $Mode; hold_seconds = $Hold; expected_blocked = $ExpectedBlocked; written = (Get-Date).ToString("yyyy-MM-dd'T'HH:mm:ss.fffzzz") })
}

function Assert-SpikePreflight {
    # Returns an array of problems (empty = go).
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
    $os = Get-CimInstance Win32_OperatingSystem
    $free = [Math]::Round($os.FreePhysicalMemory / 1MB, 2)
    if ($free -lt 14) { [void]$e.Add("free RAM $free GB < 14 GB: close memory-heavy processes (the 4B load needs ~10 GB In-Use)") }
    return @($e)
}

function Save-OperatorReport {
    param([string]$Name, $Report)
    New-Item -ItemType Directory -Force $OutDir | Out-Null
    $p = Join-Path $OutDir ("{0}-{1}.json" -f $Name, (Get-Date -Format 'yyyyMMdd-HHmmss'))
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
            if (Test-Path -LiteralPath $portPath) { Start-Sleep -Milliseconds 300; $portInfo = Get-Content -LiteralPath $portPath -Raw | ConvertFrom-Json; break }
            Start-Sleep -Milliseconds 1500
        }
        $report.steps.serve_port = $portInfo
        $comp = $null; $health = $null
        if ($portInfo -and -not $script:opAbort) {
            $obs.ServeStarted = $true
            Write-Host "listener at $($portInfo.host):$($portInfo.port) (model_loaded=$($portInfo.model_loaded)); requesting a completion as the operator"
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
    Write-Host '== argument validation ==' -ForegroundColor Cyan
    Chk 'no mode -> error' ((Test-WfpArgs $false $false $false $false 420 60 900).Count -ge 1)
    Chk 'two modes -> error' ((Test-WfpArgs $false $true $true $false 420 60 900).Count -ge 1)
    Chk '-TestB with defaults valid' ((Test-WfpArgs $false $false $false $true 420 60 900).Count -eq 0)
    Chk 'serve hold >= block max rejected' ((Test-WfpArgs $false $false $false $true 100 100 900).Count -ge 1)
    Chk 'block max 0 / 901 rejected' (((Test-WfpArgs $false $false $false $true 0 60 900).Count -ge 1) -and ((Test-WfpArgs $false $false $false $true 901 60 900).Count -ge 1))
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
    Write-Host '== Test A verdict ==' -ForegroundColor Cyan
    $t = (Get-Date).ToString("yyyy-MM-dd'T'HH:mm:ss.fffzzz")
    $mk = { param($bad) [pscustomobject]@{ steps = @($script:StepNamesBase | ForEach-Object { [pscustomobject]@{ name = $_; status = $(if ($bad -contains $_) { 'fail' } else { 'pass' }) } }) } }
    Chk 'all pass -> 0' ((Get-TestAVerdict (& $mk @()) @()).Code -eq 0)
    Chk 'only the GPU step failed -> 8' ((Get-TestAVerdict (& $mk @('gpu_feasibility')) @()).Code -eq 8)
    Chk 'GPU + file denial failed -> 4' ((Get-TestAVerdict (& $mk @('gpu_feasibility', 'file_denial')) @()).Code -eq 4)
    Chk 'schema violations -> 4' ((Get-TestAVerdict (& $mk @()) @('x')).Code -eq 4)
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
    Write-Host ''; Write-Host $plan.Describe()
    Write-Host 'TEST A sequence : preflight -> request.json(mode=feasibility) -> Start-ScheduledTask (+start proof) -> wait for result (<= ResultTimeoutSeconds) -> strict-schema check -> report'
    Write-Host 'TEST B sequence : preflight (+ WFP objects absent) -> operator baseline 3x 1.1.1.1:443 -> add dynamic block (+dead-man) -> request.json(mode=serve) -> start task -> watchdog every 2 s while waiting for serve-port-<run>.json -> operator POST /completion on 127.0.0.1:<port> -> wait for result (block still live) -> close engine -> verify removal -> report'
    Write-Host ("parameters      : BlockMaxSeconds={0}  ServeHoldSeconds={1}  ResultTimeoutSeconds={2}" -f $BlockMaxSeconds, $ServeHoldSeconds, $ResultTimeoutSeconds)
    Write-Host "operator reports: $OutDir\testA-*.json / testB-*.json; the task's own result: C:\blarai-spike\results\result-<run>.json"
    $t = Get-ScheduledTask -TaskPath $script:SpikeTaskPath -TaskName $script:SpikeTaskName -ErrorAction SilentlyContinue
    Write-Host $(if ($t) { "task present, State=$($t.State)" } else { 'task NOT registered (provision first)' })
    Write-Host 'DRY RUN complete. Nothing was added.' -ForegroundColor Green
    if ($fab) { return 2 }
    return 0
}

# ---- entry --------------------------------------------------------------------------------------------------------
$argErrors = Test-WfpArgs $SelfTest.IsPresent $DryRun.IsPresent $TestA.IsPresent $TestB.IsPresent $BlockMaxSeconds $ServeHoldSeconds $ResultTimeoutSeconds
if ($argErrors.Count) { $argErrors | ForEach-Object { Write-Host "ARG ERROR: $_" -ForegroundColor Red }; exit 2 }
try {
    if ($SelfTest) { exit (Invoke-SelfTest) }
    if ($DryRun)   { exit (Invoke-DryRun) }
    $null = Import-WfpHelpers -Path $WfpScript
    if ($TestA)    { exit (Invoke-TestA) }
    if ($TestB)    { exit (Invoke-TestB) }
} catch {
    Write-Host "STOPPED: $($_.Exception.Message)" -ForegroundColor Red
    exit 2
}
