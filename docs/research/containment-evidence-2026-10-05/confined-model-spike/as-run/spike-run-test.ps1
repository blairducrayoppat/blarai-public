#requires -Version 5.1
<#
.SYNOPSIS
  #1689 spike: the code the scheduled task \BlarAI\BlarAI-Spike-Model runs AS the blarai-spike account
  (RunLevel Limited, batch logon, no interactive session). Self-contained (no dot-sourcing): provision copies it,
  spike_model.py and spike-config.json into C:\blarai-spike\bin, which the account can read but not write.

.DESCRIPTION
  Steps, each recorded with machine-clock timestamps in ONE strict JSON file results\result-<run_id>.json:
    identity         whoami /user, token SID, groups, integrity level, session id (must equal config.expected_sid)
    memory           free RAM must be >= config.min_free_gb before the model is touched
    gpu_feasibility  python (venv) imports openvino_genai, lists devices, loads the 4B on GPU, 2 x 64 tokens
    file_denial      reads of the operator secret paths (must be DENIED), writes outside work (must be DENIED),
                     positive controls (own work dir writable, model dir + bin readable)
    outbound_probe   TCP connect to 1.1.1.1:443, 5 s; pass = (blocked == request.expected_blocked)
    serve            (-Mode serve) loopback listener inside the python process that holds the model; port written
                     to results\serve-port-<run_id>.json
  Fail-closed: any step error is recorded and the run still ends with a result file whose overall is not 'pass'.
  The request (mode, hold, run id, expected_blocked) comes from the operator-written bin\request.json when
  -RequestFile is given; explicit -Mode/-HoldSeconds are used otherwise.

  -SelfTest runs the pure helpers only: no GPU, no process, no network, no file outside memory.
#>
[CmdletBinding()]
param(
    [ValidateSet('feasibility', 'serve')][string]$Mode = 'feasibility',
    [int]$HoldSeconds = 45,
    [string]$RequestFile,
    [string]$ConfigFile,
    [switch]$SelfTest
)
$ErrorActionPreference = 'Stop'
if (-not $ConfigFile) { $ConfigFile = Join-Path $PSScriptRoot 'spike-config.json' }

function Get-Now { (Get-Date).ToString("yyyy-MM-dd'T'HH:mm:ss.fffzzz") }

function ConvertTo-AccessOutcome {
    # PURE. Classify the exception type name of a .NET file attempt. $TypeName = $null means the call succeeded.
    param([string]$TypeName)
    if (-not $TypeName) { return 'allowed' }
    if ($TypeName -match 'UnauthorizedAccess|SecurityException') { return 'denied' }
    if ($TypeName -match 'FileNotFound|DirectoryNotFound|PathTooLong') { return 'absent' }
    return 'error'
}

function Get-StepOverall {
    param($Steps)
    $st = @($Steps | ForEach-Object { $_.status })
    if ($st -contains 'error') { return 'error' }
    if ($st -contains 'fail') { return 'fail' }
    return 'pass'
}

function New-Step {
    param([string]$Name, [string]$Status, [string]$Started, [string]$Detail, $Data)
    [ordered]@{ name = $Name; status = $Status; started = $Started; finished = (Get-Now); detail = $Detail; data = $Data }
}

function Test-FileAccess {
    # Never Test-Path (it hides a denied parent as "absent"); call the .NET API and classify the exception.
    param([string]$Path, [ValidateSet('read', 'list')][string]$Kind = 'read')
    $t = $null; $msg = ''
    try {
        if ($Kind -eq 'list') { [void][IO.Directory]::GetFileSystemEntries($Path) }
        else { $fs = [IO.File]::Open($Path, 'Open', 'Read', 'ReadWrite'); $fs.Dispose() }
    } catch { $ex = $_.Exception; while ($ex.InnerException) { $ex = $ex.InnerException }; $t = $ex.GetType().Name; $msg = $ex.Message }
    [ordered]@{ path = $Path; kind = $Kind; outcome = (ConvertTo-AccessOutcome $t); exception = $t; message = $msg }
}

function Test-ProbeRead {
    # A secret path may be a file or a directory: try the directory API, and if that says "not a directory"/absent
    # try the file API; a DENIED from either is the answer.
    param([string]$Path)
    $r = Test-FileAccess $Path 'list'
    if ($r.outcome -eq 'allowed' -or $r.outcome -eq 'denied') { return $r }
    $f = Test-FileAccess $Path 'read'
    if ($f.outcome -eq 'allowed' -or $f.outcome -eq 'denied') { return $f }
    return $r
}

function Test-FileWrite {
    param([string]$Path)
    $t = $null; $msg = ''; $created = $false
    try { $fs = [IO.File]::Open($Path, 'CreateNew', 'Write', 'None'); $created = $true; $fs.Dispose() }
    catch { $ex = $_.Exception; while ($ex.InnerException) { $ex = $ex.InnerException }; $t = $ex.GetType().Name; $msg = $ex.Message }
    if ($created) { try { [IO.File]::Delete($Path) } catch { $msg = "created but could not delete: $($_.Exception.Message)" } }
    [ordered]@{ path = $Path; kind = 'write'; outcome = (ConvertTo-AccessOutcome $t); exception = $t; message = $msg }
}

function Test-TcpConnect {
    param([string]$HostName, [int]$Port, [int]$TimeoutMs)
    $sw = [Diagnostics.Stopwatch]::StartNew(); $c = New-Object Net.Sockets.TcpClient
    try {
        $iar = $c.BeginConnect($HostName, $Port, $null, $null)
        if ($iar.AsyncWaitHandle.WaitOne($TimeoutMs, $false)) {
            try { $c.EndConnect($iar); return [ordered]@{ target = "${HostName}:$Port"; connected = $true; ms = $sw.ElapsedMilliseconds; error = ''; t = (Get-Now) } }
            catch { return [ordered]@{ target = "${HostName}:$Port"; connected = $false; ms = $sw.ElapsedMilliseconds; error = $_.Exception.Message; t = (Get-Now) } }
        }
        return [ordered]@{ target = "${HostName}:$Port"; connected = $false; ms = $sw.ElapsedMilliseconds; error = "timeout ${TimeoutMs}ms"; t = (Get-Now) }
    } catch {
        return [ordered]@{ target = "${HostName}:$Port"; connected = $false; ms = $sw.ElapsedMilliseconds; error = $_.Exception.Message; t = (Get-Now) }
    } finally { $c.Close() }
}

function Write-Utf8NoBom([string]$Path, [string]$Text) {
    [IO.File]::WriteAllText($Path, $Text, (New-Object Text.UTF8Encoding($false)))
}

function Write-ResultAtomic([string]$Path, $Obj) {
    $tmp = "$Path.tmp"
    Write-Utf8NoBom $tmp (ConvertTo-Json -InputObject $Obj -Depth 14)
    Move-Item -LiteralPath $tmp -Destination $Path -Force
}

# ------------------------------------------------------------------------------------------------------------------
if ($SelfTest) {
    $f = 0
    function Chk([string]$n, [bool]$c) { if ($c) { Write-Host "  [PASS] $n" -ForegroundColor Green } else { Write-Host "  [FAIL] $n" -ForegroundColor Red; $script:f++ } }
    Chk 'no exception -> allowed' ((ConvertTo-AccessOutcome $null) -eq 'allowed')
    Chk 'UnauthorizedAccessException -> denied' ((ConvertTo-AccessOutcome 'UnauthorizedAccessException') -eq 'denied')
    Chk 'DirectoryNotFoundException -> absent (NOT denied)' ((ConvertTo-AccessOutcome 'DirectoryNotFoundException') -eq 'absent')
    Chk 'IOException -> error (not silently denied)' ((ConvertTo-AccessOutcome 'IOException') -eq 'error')
    Chk 'overall: error beats fail beats pass' (((Get-StepOverall @(@{status='pass'},@{status='fail'},@{status='error'})) -eq 'error') -and ((Get-StepOverall @(@{status='pass'},@{status='fail'})) -eq 'fail') -and ((Get-StepOverall @(@{status='pass'},@{status='info'},@{status='skipped'})) -eq 'pass'))
    $s = New-Step 'identity' 'pass' (Get-Now) 'x' $null
    Chk 'step has name/status/started/finished/detail/data' ((@('name','status','started','finished','detail','data') | Where-Object { $s.Keys -notcontains $_ }).Count -eq 0)
    Chk 'timestamps carry a UTC offset' (($s.started -match '[+-]\d{2}:\d{2}$') -and ($s.finished -match '[+-]\d{2}:\d{2}$'))
    Chk 'a missing path is classified absent, not allowed' ((Test-FileAccess 'Z:\no\such\dir-1689' 'list').outcome -in @('absent','error'))
    $j = ConvertTo-Json -InputObject ([ordered]@{ a = @(1); b = [ordered]@{ c = 'd' } }) -Depth 5
    Chk 'JSON round-trips' ((ConvertFrom-Json $j).b.c -eq 'd')
    Write-Host ("run-test selftest: {0}" -f $(if ($f -eq 0) { 'all passed' } else { "$f FAILED" }))
    exit $(if ($f -eq 0) { 0 } else { 1 })
}

# --- real run (as blarai-spike) -----------------------------------------------------------------------------------
$runStart = Get-Now
$cfg = Get-Content -LiteralPath $ConfigFile -Raw | ConvertFrom-Json
$req = [pscustomobject]@{ run_id = ('manual-' + (Get-Date -Format 'yyyyMMdd-HHmmss')); mode = $Mode; hold_seconds = $HoldSeconds; expected_blocked = $false }
if ($RequestFile) {
    $r = Get-Content -LiteralPath $RequestFile -Raw | ConvertFrom-Json
    foreach ($k in 'run_id', 'mode', 'hold_seconds', 'expected_blocked') { if ($null -ne $r.$k) { $req.$k = $r.$k } }
}
if ($req.mode -notin @('feasibility', 'serve')) { throw "bad mode '$($req.mode)'" }
if ($req.run_id -notmatch '^[A-Za-z0-9-]{8,64}$') { throw "bad run_id" }
$hold = [Math]::Max(5, [Math]::Min(600, [int]$req.hold_seconds))
$resultsDir = $cfg.results_dir
$resultPath = Join-Path $resultsDir ("result-{0}.json" -f $req.run_id)
$steps = New-Object System.Collections.ArrayList
$result = [ordered]@{
    schema_version = 1; run_id = $req.run_id; mode = $req.mode; started = $runStart; finished = $null; overall = 'error'
    hold_seconds = $hold; expected_blocked = [bool]$req.expected_blocked
    host = [ordered]@{ computer = $env:COMPUTERNAME; ps_version = $PSVersionTable.PSVersion.ToString(); machine_clock = (Get-Date -Format 'yyyy-MM-dd HH:mm:ss K') }
    steps = $null
}
$workTmp = Join-Path $cfg.work_dir 'tmp'
$pyOut = Join-Path $resultsDir ("python-{0}.json" -f $req.run_id)
$memOk = $false
$py = $null

try {
    New-Item -ItemType Directory -Force $workTmp | Out-Null

    # (a) identity -------------------------------------------------------------------------------------------------
    $t0 = Get-Now
    try {
        $id = [Security.Principal.WindowsIdentity]::GetCurrent()
        $who = (& whoami.exe /user /fo csv /nh 2>&1 | Out-String).Trim()
        $lbl = (& whoami.exe /groups /fo csv /nh 2>&1 | Out-String) -split "`n" | Where-Object { $_ -match 'Mandatory Label' } | ForEach-Object { $_.Trim() }
        $isAdmin = ([Security.Principal.WindowsPrincipal]$id).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
        $sidOk = ($id.User.Value -eq $cfg.expected_sid)
        $d = [ordered]@{
            whoami_user = $who; token_user = $id.Name; token_sid = $id.User.Value; expected_sid = $cfg.expected_sid
            groups = @($id.Groups | ForEach-Object { $_.Value }); mandatory_label = @($lbl)
            is_admin_role = $isAdmin; session_id = [Diagnostics.Process]::GetCurrentProcess().SessionId
            user_interactive = [Environment]::UserInteractive; auth_type = $id.AuthenticationType
        }
        $st = if ($sidOk -and -not $isAdmin) { 'pass' } else { 'fail' }
        [void]$steps.Add((New-Step 'identity' $st $t0 $(if ($st -eq 'pass') { "ran as the spike SID, not elevated, session $($d.session_id)" } else { "token SID mismatch or admin role (sidOk=$sidOk admin=$isAdmin)" }) $d))
    } catch { [void]$steps.Add((New-Step 'identity' 'error' $t0 $_.Exception.Message $null)) }

    # memory -------------------------------------------------------------------------------------------------------
    $t0 = Get-Now
    try {
        $os = Get-CimInstance Win32_OperatingSystem
        $free = [Math]::Round($os.FreePhysicalMemory / 1MB, 2); $total = [Math]::Round($os.TotalVisibleMemorySize / 1MB, 2)
        $memOk = ($free -ge [double]$cfg.min_free_gb)
        $d = [ordered]@{ free_gb = $free; total_gb = $total; in_use_gb = [Math]::Round($total - $free, 2); required_free_gb = $cfg.min_free_gb }
        $st = if ($memOk) { 'pass' } else { 'fail' }
        [void]$steps.Add((New-Step 'memory' $st $t0 $(if ($memOk) { "free $free GB >= $($cfg.min_free_gb) GB" } else { "free $free GB < $($cfg.min_free_gb) GB: the model is NOT loaded (fail-closed)" }) $d))
    } catch { [void]$steps.Add((New-Step 'memory' 'error' $t0 $_.Exception.Message $null)) }

    # (b) gpu feasibility (+ (e) serve, which lives in the same python process as the model) -------------------------
    $t0 = Get-Now
    $serveStart = $null
    $pyArgs = New-Object System.Collections.ArrayList
    [void]$pyArgs.AddRange(@((Join-Path $cfg.bin_dir 'spike_model.py'), '--mode', $req.mode, '--model-dir', $cfg.model_dir, '--out-json', $pyOut,
        '--run-id', $req.run_id, '--hold', "$hold", '--outbound', $cfg.outbound_target, '--outbound-timeout', "$($cfg.outbound_timeout_s)"))
    if ($req.mode -eq 'serve') { [void]$pyArgs.AddRange(@('--port-file', (Join-Path $resultsDir ("serve-port-{0}.json" -f $req.run_id)))) }
    if (-not $memOk) { [void]$pyArgs.Add('--no-model') }
    # Quote each arg for the Windows command line.
    $argLine = ($pyArgs | ForEach-Object { if ($_ -match '[\s"]') { '"' + ($_ -replace '"', '\"') + '"' } else { $_ } }) -join ' '
    $env:TEMP = $workTmp; $env:TMP = $workTmp; $env:PYTHONUTF8 = '1'; $env:PYTHONDONTWRITEBYTECODE = '1'
    $stdout = Join-Path $resultsDir ("python-{0}.stdout.txt" -f $req.run_id)
    $stderr = Join-Path $resultsDir ("python-{0}.stderr.txt" -f $req.run_id)
    $limitMs = ([int]$cfg.load_timeout_s + $(if ($req.mode -eq 'serve') { $hold } else { 120 }) + 120) * 1000
    $gpuDetail = ''; $gpuStatus = 'error'; $gpuData = $null
    try {
        $py = Start-Process -FilePath $cfg.venv_python -ArgumentList $argLine -WorkingDirectory $cfg.work_dir -PassThru -WindowStyle Hidden `
              -RedirectStandardOutput $stdout -RedirectStandardError $stderr
        $serveStart = Get-Now
        if (-not $py.WaitForExit($limitMs)) {
            try { & taskkill.exe /PID $py.Id /T /F 2>&1 | Out-Null } catch {}
            $gpuDetail = "python exceeded ${limitMs} ms and was killed"
        } else {
            $gpuDetail = "python exit code $($py.ExitCode)"
        }
        $pyJson = $null
        if (Test-Path -LiteralPath $pyOut) { $pyJson = Get-Content -LiteralPath $pyOut -Raw | ConvertFrom-Json }
        $errTail = ''
        if (Test-Path -LiteralPath $stderr) { $errTail = (Get-Content -LiteralPath $stderr -Raw -ErrorAction SilentlyContinue) }
        $gpuData = [ordered]@{ python_exit_code = $(if ($py.HasExited) { $py.ExitCode } else { $null }); python_result_file = $pyOut; python = $pyJson; stderr = $errTail }
        if (-not $memOk) { $gpuStatus = 'skipped'; $gpuDetail = 'skipped: not enough free memory' }
        elseif (-not $pyJson) { $gpuStatus = 'error'; $gpuDetail += '; python wrote no result JSON' }
        elseif (-not $pyJson.runtime_imported) { $gpuStatus = 'fail'; $gpuDetail = 'openvino_genai import failed: ' + $pyJson.import_error.message }
        elseif (-not $pyJson.load.ok) { $gpuStatus = 'fail'; $gpuDetail = 'model load on GPU failed: ' + $pyJson.load.error.message }
        elseif (@($pyJson.runs | Where-Object { $_.ok }).Count -ne 2) { $gpuStatus = 'fail'; $gpuDetail = 'load ok, generation failed' }
        else {
            $gpuStatus = 'pass'
            $r1 = $pyJson.runs[0]; $r2 = $pyJson.runs[1]
            $gpuDetail = "GPU load $($pyJson.load.seconds) s; run1 ttft $($r1.ttft_ms) ms $($r1.tok_per_s_tpot) tok/s; run2 ttft $($r2.ttft_ms) ms $($r2.tok_per_s_tpot) tok/s"
        }
    } catch {
        $gpuStatus = 'error'; $gpuDetail = "could not run python: $($_.Exception.Message)"
    }
    # Order: the schema wants steps in time order, so record the three analysis steps in their schema order with the
    # python window as the gpu_feasibility step's span; file_denial and outbound_probe follow.
    [void]$steps.Add((New-Step 'gpu_feasibility' $gpuStatus $t0 $gpuDetail $gpuData))

    # (c) file denial ----------------------------------------------------------------------------------------------
    $t0 = Get-Now
    try {
        $reads = @(); foreach ($p in @($cfg.secret_paths)) { $reads += , (Test-ProbeRead $p) }
        $workFile = Join-Path $cfg.work_dir ("write-control-{0}.tmp" -f $req.run_id)
        $writeCtl = Test-FileWrite $workFile
        $outside = @(
            'C:\Windows\System32\spike-write-test.tmp',
            ('C:\Users\_OPERATOR_\spike-write-test.tmp'),
            (Join-Path $cfg.bin_dir 'spike-write-test.tmp'),
            'C:\spike-write-test.tmp'
        )
        $writes = @(); foreach ($p in $outside) { $writes += , (Test-FileWrite $p) }
        $info = @(); foreach ($p in @($cfg.info_write_targets)) { $info += , (Test-FileWrite $p) }
        $ctlRead = @((Test-FileAccess (Join-Path $cfg.bin_dir 'spike-config.json') 'read'), (Test-FileAccess (Join-Path $cfg.model_dir 'config.json') 'read'))
        $badReads = @($reads | Where-Object { $_.outcome -ne 'denied' })
        $badWrites = @($writes | Where-Object { $_.outcome -ne 'denied' })
        $badCtl = @(@($writeCtl) + @($ctlRead) | Where-Object { $_.outcome -ne 'allowed' })
        $d = [ordered]@{ secret_reads = $reads; outside_writes = $writes; informational_writes = $info; positive_controls = (@($writeCtl) + @($ctlRead)) }
        if ($badCtl.Count -gt 0) { $st = 'fail'; $det = "positive control failed ($($badCtl.Count)): the denials above prove nothing" }
        elseif ($badReads.Count -gt 0 -or $badWrites.Count -gt 0) { $st = 'fail'; $det = "NOT denied: reads $($badReads.Count), writes $($badWrites.Count)" }
        else { $st = 'pass'; $det = "all $($reads.Count) secret reads and $($writes.Count) outside writes denied; positive controls allowed" }
        [void]$steps.Add((New-Step 'file_denial' $st $t0 $det $d))
    } catch { [void]$steps.Add((New-Step 'file_denial' 'error' $t0 $_.Exception.Message $null)) }

    # (d) outbound probe -------------------------------------------------------------------------------------------
    $t0 = Get-Now
    try {
        $tp = $cfg.outbound_target -split ':'
        $pr = Test-TcpConnect $tp[0] ([int]$tp[1]) ([int]$cfg.outbound_timeout_s * 1000)
        $blocked = (-not $pr.connected)
        $st = if ($blocked -eq [bool]$req.expected_blocked) { 'pass' } else { 'fail' }
        $det = "outbound $($cfg.outbound_target): " + $(if ($pr.connected) { 'CONNECTED' } else { "BLOCKED ($($pr.error))" }) + "; expected_blocked=$([bool]$req.expected_blocked)"
        [void]$steps.Add((New-Step 'outbound_probe' $st $t0 $det ([ordered]@{ probe = $pr; blocked = $blocked; expected_blocked = [bool]$req.expected_blocked })))
    } catch { [void]$steps.Add((New-Step 'outbound_probe' 'error' $t0 $_.Exception.Message $null)) }

    # serve (summarised from the python result; the listener ran inside the model process) ------------------------------
    if ($req.mode -eq 'serve') {
        $t0 = Get-Now
        try {
            $pj = $steps | Where-Object { $_.name -eq 'gpu_feasibility' } | Select-Object -First 1
            $sv = $null
            if ($pj -and $pj.data -and $pj.data.python) { $sv = $pj.data.python.serve }
            if (-not $sv) { [void]$steps.Add((New-Step 'serve' 'fail' $t0 'the listener never started (no serve record from python)' $null)) }
            else {
                $mid = $sv.outbound_probe_mid_hold
                $st = if ($sv.bind -like '127.0.0.1:*' -and $sv.finished) { 'pass' } else { 'fail' }
                [void]$steps.Add((New-Step 'serve' $st $t0 "listener $($sv.bind) ran $($sv.hold_seconds) s, model_loaded=$($sv.model_loaded), requests served $($sv.requests_served)" ([ordered]@{ bind = $sv.bind; requests_served = $sv.requests_served; model_loaded = $sv.model_loaded; outbound_probe_mid_hold = $mid; requests = $sv.requests })))
            }
        } catch { [void]$steps.Add((New-Step 'serve' 'error' $t0 $_.Exception.Message $null)) }
    }
} catch {
    [void]$steps.Add((New-Step 'run' 'error' (Get-Now) ("fatal: " + $_.Exception.Message) $null))
} finally {
    if ($py -and -not $py.HasExited) { try { & taskkill.exe /PID $py.Id /T /F 2>&1 | Out-Null } catch {} }
    $result.finished = Get-Now
    $result.steps = @($steps)
    $result.overall = Get-StepOverall $steps
    try { Write-ResultAtomic $resultPath $result } catch { Write-Error "could not write $resultPath : $($_.Exception.Message)" }
}
exit $(if ($result.overall -eq 'error') { 1 } else { 0 })
