#requires -Version 5.1
<#
.SYNOPSIS
  NEP-0005 open questions (#1763): the half-set matrix. Puts one state at a time in place on the REAL Windows Filtering Platform engine (test account and the three test
  sublayers only), reads what srt-win's status and our own checks report, connects as the account and as the operator, removes by key and proves the removal by direct
  reads. Machine-wide state while a state exists: read README.md first.

.DESCRIPTION
  Modes (exactly one):
    -SelfTest [-WriteProof]  pure only: against a FAKE engine, a FAKE harness and fake account and task operations (no WFP call, no password change, no task, no real harness run). With -WriteProof (and only then) it also
               runs the siblings' self-tests and the harness's refusal self-test (no engine; an engine-open trace must stay empty) and, if EVERYTHING passed, writes the proof the
               add paths require: the SHA-256 of every script of the code set, of the wrapped #1671 script, of the harness exe, of halfset.rs and of the pinned Cargo.lock.
    -DryRun    prints exactly what each state would do, the manual rollback, and whether a valid proof exists. Opens no engine, runs no harness, starts no task.
    -Check     read-only: S1/S2/S3 and our provider by direct reads, the name/GUID export, the account task's arguments AND whole definition against the recorded baseline, and the account's bin folder.
               Also reads the session-open record (present = 21, never 20) and the task's last run result (a read, not a start). Exit 20 only when everything reads absent/original, 21 something is present, 22 something was unreadable.
    -Remove    removes by key everything in S1/S2/S3 and our provider (harness first, our own engine second, the self-contained snippet last), restores the account task and
               the bin folder, then verifies: the direct checks for the engine, and for the task its arguments, its whole definition against the baseline and a start of the restored task.
               Needs no proof. Reports 'engine removal verified' and 'task restore proven' separately.
    -Run -Phase taskcheck|halfset|ours|n1 [-Passes 1..3] [-Only R1+R2]   the live phases. Every state is the same cycle, in this fixed order, THREE passes unless -Passes says less:
               1 direct sweep (refuse to add on anything but clean); 2 control (account and operator connect before any filter); 3 add (proof-gated); 4 record; 5 the account's
               and the operator's connects through the gate; 6 remove by key, read back with the checks of step 1, refuse to continue if anything reads back present.
               N1 has no step 2 (it makes no connects). The first live action of every run is the pre-cleanup (README); a run that it refuses or stops removes NOTHING.
               taskcheck first: it sets a fresh session password on blarai-spike (memory only), runs the identity probe and one connect probe AS the account, then restores the original task
               credential with spike-provision.ps1 -Apply -ForceNewPassword and PROVES it (arguments, definition against the baseline, and the restored task started in its original form
               as the account); no other phase runs until it has passed for the current proof. The task itself is never edited.

  EXIT CODES
    0 ok    2 refusal / precondition (no proof, not elevated, not admin-only, sweep not clean, no passed taskcheck): the state that refused added nothing (earlier states of the same phase are in the record)    3 unsafe target (the operator's SID or a group of his)
    4 inconclusive (a row did not run, a probe gave no valid result)    5 a control failed before any filter    7 removal NOT verified (run -Remove, then the README's manual rollback)
    9 STOP: a filter of ours or srt-win's outside S1/S2/S3, the operator's traffic affected, a finding (the account's non-elevated token added or deleted a filter), or the account's task NOT RESTORED
    20/21/22 -Check: ABSENT / PRESENT / UNREADABLE     1 -SelfTest failed
#>
[CmdletBinding()]
param(
    [switch]$SelfTest,
    [switch]$WriteProof,
    [switch]$DryRun,
    [switch]$Check,
    [switch]$Remove,
    [switch]$Run,
    [ValidateSet('taskcheck', 'halfset', 'ours', 'n1')][string]$Phase,
    [ValidateRange(1, 3)][int]$Passes = 3,
    [string]$Only,
    [string]$WfpScript,
    [string]$WfpSha256,
    [string]$HarnessExe,
    [string]$HarnessSource,
    [string]$CargoLock,
    [string]$HarnessSha256,
    [string]$HarnessLiveProof,
    [string]$OutDir,
    [string]$ProofPath,
    [string]$BinDir = 'C:\blarai-spike\bin',
    [switch]$DropCleanExports
)
$ErrorActionPreference = 'Stop'
if ($PSVersionTable.PSEdition -eq 'Desktop') {
    # A Windows PowerShell 5.1 host started from a PowerShell 7 environment inherits PowerShell 7's PSModulePath, under which ConvertTo-SecureString (Microsoft.PowerShell.Security) cannot load. Reset it to the machine value for this process.
    $n5mpOrig = $env:PSModulePath
    $n5mp = [Environment]::GetEnvironmentVariable('PSModulePath', 'Machine'); if ($n5mp) { $env:PSModulePath = $n5mp }
}
$script:LoadedLibHashes = @{}; $script:LoadedLibFolder = $PSScriptRoot
function Resolve-LibPath {
    # The libraries sit beside this script (the admin-only live folder). Only an attended -SelfTest without -WriteProof may fall back to the repository's arm 3 folder.
    param([Parameter(Mandatory)][string]$Name)
    $p = Join-Path $PSScriptRoot $Name
    if (Test-Path -LiteralPath $p) { return $p }
    if ($SelfTest -and -not $WriteProof) { $q = Join-Path $PSScriptRoot "..\..\arm3-persist\scripts\$Name"; if (Test-Path -LiteralPath $q) { return (Resolve-Path -LiteralPath $q).Path } }
    return $p
}
function Get-VerifiedLibBlock {
    # Reads a library ONCE, records the SHA-256 (CRLF read as LF) of exactly those bytes, and returns a scriptblock built from that same text for the caller to
    # dot-source at script scope: `. (Get-VerifiedLibBlock 'x.ps1')`. There is no second read, so what is hashed (for the rollback proof and the code-set id) is what runs.
    param([Parameter(Mandatory)][string]$Name)
    $bytes = [IO.File]::ReadAllBytes((Resolve-LibPath -Name $Name))
    $ms = New-Object IO.MemoryStream
    for ($i = 0; $i -lt $bytes.Length; $i++) { if ($bytes[$i] -eq 13 -and $i + 1 -lt $bytes.Length -and $bytes[$i + 1] -eq 10) { continue }; $ms.WriteByte($bytes[$i]) }
    $sha = [Security.Cryptography.SHA256]::Create()
    try { $script:LoadedLibHashes[$Name] = ([BitConverter]::ToString($sha.ComputeHash($ms.ToArray()))) -replace '-', '' } finally { $sha.Dispose(); $ms.Dispose() }
    return [scriptblock]::Create([Text.Encoding]::UTF8.GetString($bytes).TrimStart([char]0xFEFF))
}
. (Get-VerifiedLibBlock 'spike-lib.ps1')
. (Get-VerifiedLibBlock 'spike-persist-lib.ps1')
. (Get-VerifiedLibBlock 'spike-task-driver.ps1')
. (Get-VerifiedLibBlock 'spike-nep5-lib.ps1')
. (Get-VerifiedLibBlock 'spike-nep5-run-lib.ps1')
if (-not $WfpScript) {
    $WfpScript = Join-Path $PSScriptRoot 'wfp-coder-egress-spike.ps1'
    if (-not (Test-Path -LiteralPath $WfpScript) -and $SelfTest -and -not $WriteProof) { $WfpScript = Join-Path $PSScriptRoot '..\..\wfp-spike\wfp-coder-egress-spike.ps1' }
}
if (-not $HarnessExe) { $HarnessExe = Join-Path $PSScriptRoot 'halfset.exe' }
if (-not $HarnessSource) { $HarnessSource = Join-Path $PSScriptRoot 'halfset.rs' }
if (-not $CargoLock) { $CargoLock = Join-Path $PSScriptRoot 'Cargo.lock' }
if (-not $HarnessLiveProof) { $HarnessLiveProof = Join-Path $PSScriptRoot 'harness-live-proof-1763.json' }
if (-not $OutDir) { $OutDir = Join-Path $PSScriptRoot 'nep5-out' }
if (-not $ProofPath) { $ProofPath = Join-Path $PSScriptRoot 'rollback-selftest-proof-1763.json' }
$FixedDir = $PSScriptRoot   # the task baseline and the taskcheck record live here, beside the scripts and the proof (never derived from a parameter)

# ---- pure helpers ---------------------------------------------------------------------------------------------------------------------------
function Test-Nep5ProofInFolder {
    # PURE. Problems (empty = ok): the proof must be read from the scripts' own folder and nowhere else.
    param([string]$ProofPath, [string]$Folder)
    $d = $null; try { $d = (Split-Path ([IO.Path]::GetFullPath($ProofPath)) -Parent).TrimEnd('\') } catch { return @("-ProofPath '$ProofPath' is not a usable path") }
    if ($d -ine [IO.Path]::GetFullPath($Folder).TrimEnd('\')) { return @("-ProofPath must be in the scripts' own folder ($Folder), not '$d'") }
    return @()
}

function Test-Nep5Args {
    param([bool]$SelfTest, [bool]$WriteProof, [bool]$DryRun, [bool]$Check, [bool]$Remove, [bool]$Run, [string]$Phase, [string]$Only)
    $e = New-Object System.Collections.ArrayList
    if (@(@($SelfTest, $DryRun, $Check, $Remove, $Run) | Where-Object { $_ }).Count -ne 1) { [void]$e.Add('choose exactly one of -SelfTest, -DryRun, -Check, -Remove, -Run') }
    if ($WriteProof -and -not $SelfTest) { [void]$e.Add('-WriteProof applies to -SelfTest only') }
    if ($Run -and -not $Phase) { [void]$e.Add("-Run needs -Phase ($($script:N5Phases -join ', '))") }
    if ($Phase -and -not $Run) { [void]$e.Add('-Phase applies to -Run only') }
    if ($Only) {
        if (-not $Run) { [void]$e.Add('-Only applies to -Run only') }
        foreach ($t in ($Only -split '[,+]')) { if (@($script:N5States | Where-Object { $_.Id -eq $t -and (-not $Phase -or $_.Phase -eq $Phase) }).Count -eq 0) { [void]$e.Add("-Only names '$t', which is not a state of phase '$Phase'") } }
    }
    return @($e)
}

function Get-Nep5CheckExit {
    # PURE. -Check's exit code: a STOP finding, or an open session record (a session set the account password and never proved its restore), is "something present" (21) even if a read failed; otherwise any
    # unreadable read is 22; a task whose last run failed to log on counts as present too; only an all-clear is 20.
    param($Sweep, [string]$TaskState, [string[]]$BinLeft = @(), $TaskDefMatch = $null, [bool]$SessionOpen = $false, [bool]$TaskCredentialFailure = $false, [bool]$TaskInfoUnreadable = $false)
    if ($Sweep.Stop -or $SessionOpen) { return 21 }
    if ($Sweep.Unreadable -or $TaskState -like 'unreadable:*' -or $TaskInfoUnreadable) { return 22 }
    if (-not $Sweep.Clean -or $TaskState -ne 'original' -or @($BinLeft).Count -or $TaskDefMatch -eq $false -or $TaskCredentialFailure) { return 21 }
    return 20
}

function Get-N5TrustedHarnessSha {
    # The harness exe's raw SHA-256 when it can be trusted for a read or a removal: it equals the one a proof file of this folder recorded, or the one the operator passed
    # (-HarnessSha256). $null otherwise. -Remove and -Check do not need a VALID proof (a removal must work after an edit), only a harness they can recognise.
    param([string]$ProofFile, [string]$Override, [string]$Exe)
    $now = Get-N5RawSha256 -Path $Exe
    if (-not $now) { return $null }
    if ($Override -and $Override.ToUpperInvariant() -eq $now) { return $now }
    try { $p = ConvertFrom-Json ([IO.File]::ReadAllText($ProofFile)); if ($p.harness -and [string]$p.harness.exe_sha256 -eq $now) { return $now } } catch {}
    return $null
}

function Get-N5HarnessSelfChecks {  # -RsSha256: the halfset.rs hash the exe must report
    # The harness's own refusal self-test and its provenance, run through $Runner with a trace file: `--version` must show the pinned srt-win SHA and the pinned Cargo.lock hash,
    # `selftest-refusals` must exit 0 with ok true and engine_opens 0, and the engine-open trace file must be absent or empty afterwards. @{ version_ok; refusals_exit_zero; engine_open_trace_empty; detail }.
    param([Parameter(Mandatory)][scriptblock]$Runner, [Parameter(Mandatory)][string]$TracePath, [Parameter(Mandatory)][string]$LockSha256, [string]$RsSha256)
    $v = Invoke-Halfset -Runner $Runner -Argv @('--version')
    $versionOk = ($v.ExitCode -eq 0 -and $v.Stdout -match [regex]::Escape($script:N5PinnedSrtSha) -and $v.Stdout -match [regex]::Escape($LockSha256.ToLowerInvariant()))
    if ($RsSha256) { $versionOk = ($versionOk -and $v.Json -and [string]$v.Json.halfset_rs_sha256 -eq $RsSha256.ToLowerInvariant()) }
    $r = Invoke-Halfset -Runner $Runner -Argv @('selftest-refusals')
    $refOk = ($r.ExitCode -eq 0 -and $r.Json -and $r.Json.ok -eq $true -and [int]$r.Json.engine_opens -eq 0)
    $traceEmpty = (-not (Test-Path -LiteralPath $TracePath)) -or (([IO.File]::ReadAllText($TracePath)).Trim().Length -eq 0)
    return [ordered]@{ version_ok = [bool]$versionOk; refusals_exit_zero = [bool]$refOk; engine_open_trace_empty = [bool]$traceEmpty; version_text = $v.Stdout.Trim(); detail = "version exit $($v.ExitCode); refusals exit $($r.ExitCode)" }
}

function Initialize-Nep5Session {
    # Reads the wrapped script (never runs it) and compiles the types. With -Unverified (self-test only) the repository copy of the wrapped script is read without a pin.
    param([switch]$Unverified)
    $null = Import-WfpHelpers -Path $WfpScript -ExpectedSha256 $WfpSha256 -Unverified:$Unverified
    Initialize-Nep5Type
}

function Get-Nep5RealRunner {
    # The harness Runner for a trusted exe, or $null.
    param([switch]$ForRun)
    $sha = Get-N5TrustedHarnessSha -ProofFile $ProofPath -Override $HarnessSha256 -Exe $HarnessExe
    if (-not $sha) { return $null }
    return (New-HalfsetRunner -Exe $HarnessExe -ExpectedSha256 $sha)
}

function Write-SweepLines {
    param($Sw)
    foreach ($id in $Sw.SubLayers.Keys) { $s = $Sw.SubLayers[$id]; Write-Host ("  {0}: {1} filter(s); sublayer present: {2}" -f $id, @($s.filter_keys).Count, $s.present) }
    Write-Host ("  provider present: {0}" -f $Sw.ProviderPresent)
    if ($Sw.Export.hits) { Write-Host ("  export hits: marker {0}, srt-win {1}, S1 {2}, S2 {3}, S3 {4}, provider {5}" -f $Sw.Export.hits.marker, $Sw.Export.hits.srt_win, $Sw.Export.hits.S1, $Sw.Export.hits.S2, $Sw.Export.hits.S3, $Sw.Export.hits.provider) }
    foreach ($p in @($Sw.NotClean) + @($Sw.Problems)) { Write-Host "  ! $p" -ForegroundColor Yellow }
}

# ---- -Check / -Remove -----------------------------------------------------------------------------------------------------------------------
function Invoke-Check {
    Initialize-Nep5Session
    if (-not (Test-IsElevated)) { Write-Host 'UNREADABLE: not elevated, so the engine cannot be read.' -ForegroundColor Red; return 22 }
    $ao = Test-AdminOnlyFolder -Path $PSScriptRoot
    $runner = $(if ($ao.Ok) { Get-Nep5RealRunner } else { $null })
    if (-not $runner) { Write-Host 'UNREADABLE: no harness that can be trusted (the folder is not admin-only, or the exe is not the one a proof recorded; pass -HarnessSha256).' -ForegroundColor Red; return 22 }
    $be = $null
    try { $be = New-Nep5RealBackend } catch { Write-Host "UNREADABLE: the engine could not be opened ($($_.Exception.Message))." -ForegroundColor Red; return 22 }
    $tmp = New-PrivateTempDir
    try {
        $exp = { param($l) Invoke-Nep5Export -Label $l -Path (Join-Path $tmp "check-$l.xml") -DropClean }.GetNewClosure()
        $sw = Invoke-Nep5DirectSweep -Runner $runner -Backend $be -Exporter $exp -Label 'check'
    } finally { $be.Close(); Remove-PrivateTempDir $tmp }
    Write-SweepLines $sw
    $ts = Get-Nep5TaskState -Ops (New-Nep5RealTaskOps); $left = @(Get-Nep5BinResidue -BinDir $BinDir)
    Write-Host ("  account task arguments: {0}; files left in {1}: {2}" -f $ts, $BinDir, $(if ($left.Count) { $left -join ', ' } else { 'none' }))
    $ops = New-Nep5RealTaskOps; $snapNow = $null; try { $snapNow = [string]$ops.Snapshot() } catch {}
    $baseNow = Get-Nep5TaskBaseline -Ctx ([pscustomobject]@{ OutDir = $OutDir; FixedDir = $FixedDir })
    $defMatch = $(if ($baseNow -and $snapNow) { [bool]($snapNow -ceq $baseNow) } else { $null })
    Write-Host ("  account task definition against the recorded baseline: {0}" -f $(if ($null -eq $defMatch) { 'not compared (no baseline recorded, or unreadable)' } elseif ($defMatch) { 'identical' } else { 'DIFFERENT' }))
    $sessionOpen = Get-Nep5CheckSessionOpen -FixedDir $FixedDir
    Write-Host ("  session-open record (a session set the account password and never proved its restore): {0}" -f $(if ($sessionOpen) { 'PRESENT: run -Remove (it re-provisions the task and proves the restore)' } else { 'none' })) -ForegroundColor $(if ($sessionOpen) { 'Red' } else { 'Gray' })
    $info = $null; try { $info = $ops.Info() } catch {}
    $iv = Get-Nep5TaskInfoVerdict -Info $info
    Write-Host ("  account task start-ability: {0}" -f $iv.Text)
    $code = Get-Nep5CheckExit -Sweep $sw -TaskState $ts -BinLeft $left -TaskDefMatch $defMatch -SessionOpen $sessionOpen -TaskCredentialFailure $iv.CredentialFailure -TaskInfoUnreadable $iv.Unreadable
    Write-Host ("CHECK exit {0}: {1}" -f $code, $(switch ($code) { 20 { 'everything reads absent / original' } 21 { 'something is present (see above)' } default { 'something could not be read' } })) -ForegroundColor $(if ($code -eq 20) { 'Green' } else { 'Yellow' })
    return $code
}

function Invoke-Remove {
    $initErr = $null
    try { Initialize-Nep5Session } catch { $initErr = $_.Exception.Message }
    if (-not (Test-IsElevatedSafe)) { Write-Host 'FAIL: not elevated; nothing removed. Use the README''s manual rollback from an elevated prompt.' -ForegroundColor Red; return 7 }
    $be = $null; $notes = @()
    if (-not $initErr) { try { $be = New-Nep5RealBackend } catch { $notes += "own engine unavailable: $($_.Exception.Message)" } }
    $ao = Test-AdminOnlyFolder -Path $PSScriptRoot
    $runner = $(if ($ao.Ok -and -not $initErr) { Get-Nep5RealRunner } else { $null })
    $stg = @(Remove-Nep5StagedHarnessProof -HarnessProof $HarnessLiveProof); if ($stg.Count) { Write-Host "deleted a surviving staged harness proof: $($stg -join ', ')" -ForegroundColor Yellow }
    $stale = Remove-Nep5StaleHarnessProof -HarnessProof $HarnessLiveProof -MatrixProof $ProofPath
    if ($stale.Removed) { Write-Host "deleted a stale harness proof ($($stale.Reason))" -ForegroundColor Yellow }
    if (Test-Path -LiteralPath $HarnessLiveProof) { $script:N5LiveProof = $HarnessLiveProof }   # the harness answers 12 without a valid one and the removal falls back to our own engine
    $rec = [ordered]@{ kind = 'remove-by-key'; at = (Get-N5Now); init_error = $initErr; harness_trusted = [bool]$runner; notes = $notes; removal = $null; manual = $null; sweep = $null; session = $null }
    $verified = $false; $stop = $false
    $tmp = New-PrivateTempDir
    try {
        $exp = { param($l) Invoke-Nep5Export -Label $l -Path (Join-Path $tmp "remove-$l.xml") -DropClean }.GetNewClosure()
        if ($runner -and $be) {
            $rm = Remove-Nep5All -Runner $runner -Backend $be
            $rec.removal = [ordered]@{ ok = $rm.Ok; steps = @($rm.Steps); errors = @($rm.Errors) }
            foreach ($s in $rm.Steps) { Write-Host ("  {0,-9} {1}  {2}  [{3}]" -f $s.step, $s.key, $s.status, $s.via) }
        }
        if (-not ($rec.removal -and $rec.removal.ok)) {
            Write-Host 'The harness path did not verify a clean engine (or is unavailable): the self-contained manual rollback runs now.' -ForegroundColor Yellow
            $mr = Invoke-ManualN5Rollback; $rec.manual = $mr
            foreach ($r in $mr.Rows) { Write-Host ("  {0,-9} {1}  {2}" -f $r.kind, $r.key, $r.status) }
            if (-not $mr.Ok) { Write-Host "manual rollback: $($mr.Reason)" -ForegroundColor Yellow }
        }
        $sweepBe = $be
        if (-not $sweepBe) { try { $sweepBe = New-Nep5RealBackend } catch { $sweepBe = $null } }
        if ($sweepBe) {
            $sw = Invoke-Nep5DirectSweep -Runner $runner -Backend $sweepBe -Exporter $exp -Label 'remove' -NoHarness:(-not $runner)
            $rec.sweep = Get-Nep5SweepSummary $sw; Write-SweepLines $sw
            $verified = [bool]$sw.Clean; $stop = [bool]$sw.Stop
            if ($sweepBe -ne $be) { $sweepBe.Close() }
        } else { Write-Host 'NOT VERIFIED: the engine could not be opened to read it back.' -ForegroundColor Red }
    } finally { if ($be) { try { $be.Close() } catch {} }; Remove-PrivateTempDir $tmp }
    # the account's task and bin folder: put back whatever this matrix changed, and say what is PROVEN (never a restore from the arguments alone)
    $ctx = [pscustomobject]@{ TaskOps = (New-Nep5RealTaskOps); BinDir = $BinDir; OutDir = $OutDir; FixedDir = $FixedDir; OriginalTaskRun = { param($rid) Invoke-ProbeTaskRun -RunId $rid -ExpectedBlocked $false -TimeoutSec 60 }
                            AccountOps = (New-Nep5AccountOps -BinDir $BinDir) }
    $provSha = $null; $libSha = $null; try { $pj = ConvertFrom-Json ([IO.File]::ReadAllText($ProofPath)); $provSha = [string]$pj.sha256_lf_normalised.'spike-provision.ps1'; $libSha = [string]$pj.sha256_lf_normalised.'spike-lib.ps1' } catch {}
    $seams = New-Nep5ProvisionSeams -Folder $PSScriptRoot -ProvisionSha $provSha -LibSha $libSha -BinDir $BinDir
    $ctx | Add-Member -NotePropertyName Reprovision -NotePropertyValue $seams.Reprovision
    $rt = Resolve-Nep5RemoveTask -Ctx $ctx
    $ex = $rt.Ex; $mm = @($rt.Mm); $mismatch = $rt.Mismatch; $hasBase = $rt.HasBase; $hasSession = $rt.HasSession
    $rec.session = $ex
    if ($mismatch) { Write-Host ("account task records: MISMATCH ({0})" -f ($mm -join '; ')) -ForegroundColor Red }
    elseif ($ex.Untouched) { Write-Host ("account task: TASK NEVER CHANGED BY THIS MATRIX (no baseline on record); arguments read original; residue files left in the bin folder: {0}" -f $(if ($ex.Files.Left.Count) { $ex.Files.Left -join ', ' } else { 'none' })) }
    else { Write-Host ("account task: arguments {0}; definition against the baseline: {1}; restored task started as the account: {2}; files left in the bin folder: {3}" -f $ex.TaskNow, $(if ($null -eq $ex.DefinitionMatches) { 'NOT COMPARED' } elseif ($ex.DefinitionMatches) { 'identical' } else { 'DIFFERENT' }), $(if ($ex.StartedInOriginalForm) { $ex.StartedInOriginalForm.Ok } else { 'not started' }), $(if ($ex.Files.Left.Count) { $ex.Files.Left -join ', ' } else { 'none' })) }
    try { New-Item -ItemType Directory -Force $OutDir | Out-Null; if ((Test-AdminOnlyFolder -Path $OutDir).Ok) { $rec.state_file = Join-Path $OutDir ("remove-{0}.json" -f (Get-Date -Format 'yyyyMMdd-HHmmss')); Write-JsonGuarded -Path $rec.state_file -Object $rec -Depth 14 } } catch { Write-Host "could not write the record: $($_.Exception.Message)" -ForegroundColor Yellow }
    if ($stop) { Write-Host 'STOP: a filter of ours or srt-win''s sits outside S1/S2/S3 (reported, never deleted by this script).' -ForegroundColor Red; return 9 }
    if ($verified) { Write-Host 'ENGINE REMOVAL VERIFIED: S1, S2, S3 and our provider read back absent; the export has no hits.' -ForegroundColor Green }
    else { Write-Host 'ENGINE REMOVAL NOT VERIFIED: run the manual rollback (spike-nep5-matrix.ps1 -DryRun prints it) and then -Check.' -ForegroundColor Red }
    if ($mismatch) { Write-Host ("TASK RECORDS MISMATCH: {0}. Resolve by hand (README); nothing about the task is claimed." -f ($mm -join '; ')) -ForegroundColor Red; return 9 }
    if (-not $ex.TaskRestored) {
        if ($hasBase -or $hasSession) { Write-Host ("TASK RESTORE NOT PROVEN ({0}). From an elevated prompt re-provision the account's task: spike-provision.ps1 -Apply -ForceNewPassword (full command above), then run -Run -Phase taskcheck." -f $ex.RestoreWhy) -ForegroundColor Red }
        else { Write-Host ("TASK RESTORE NOT PROVEN ({0}). There is no baseline on record, so this is not a re-key case: put the arguments back by hand (README, Manual rollback) and run -Check." -f $ex.RestoreWhy) -ForegroundColor Red }
        return 9
    }
    elseif ($ex.Untouched) { if ($ex.Ok) { Write-Host 'Bin-folder residue removed (or none); the task itself was never changed by this matrix.' -ForegroundColor Green } else { Write-Host "Residue file(s) could NOT be removed from the account's bin folder: $($ex.Files.Left -join ', ')" -ForegroundColor Yellow } }
    elseif (-not $ex.Ok) { Write-Host "TASK RESTORE PROVEN, but file(s) remain in the account's bin folder: $($ex.Files.Left -join ', ')" -ForegroundColor Yellow }
    else { Write-Host 'TASK RESTORE PROVEN (arguments, definition against the baseline, and a start as the account).' -ForegroundColor Green }
    if ($verified -and $ex.Ok) { return 0 }
    return 7
}

function Test-IsElevatedSafe {
    return ([Security.Principal.WindowsPrincipal]::new([Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator))
}

# ---- -DryRun ---------------------------------------------------------------------------------------------------------------------------------
function Invoke-DryRun {
    Write-Host '== DRY RUN: nothing is added; no WFP engine is opened; the harness is not run; no task is started ==' -ForegroundColor Yellow
    $imp = Import-WfpHelpers -Path $WfpScript -ExpectedSha256 $WfpSha256 -Unverified:(-not $WfpSha256 -and -not (Test-AdminOnlyFolder -Path (Split-Path (Resolve-Path -LiteralPath $WfpScript).Path -Parent)).Ok)
    Write-Host "wrapped script: $($imp.Path)`n  sha256 (LF-normalised) $($imp.Sha256)"
    Initialize-Nep5Type
    Write-Host ''; Write-Host '--- the three sublayers (the ONLY ones any script here may add to or delete from) and our provider ---'
    foreach ($id in $script:N5SubLayers.Keys) { Write-Host ("  {0}  {1}" -f $id, $script:N5SubLayers[$id]) }
    Write-Host ("  provider  {0}  ({1})" -f $script:N5ProviderKey, $script:N5ProviderName)
    Write-Host ("  refused everywhere: srt-win default {0}, old arm 3 sublayer {1}" -f $script:N5SrtDefaultSubLayer, $script:N5OldArm3SubLayer)
    Write-Host ("  test account {0} SID {1}; stale test SID {2} (must NOT resolve)" -f $script:SpikeUser, $script:N5SpikeSid, $script:N5StaleSid)
    $op = Get-OperatorTokenSids; $res = New-Nep5SidResolver
    $sp = @(Get-Nep5SidProblems -Sid $script:N5SpikeSid -OperatorSid $op.User -OperatorGroups $op.Groups -Resolve $res)
    $st = @(Get-Nep5SidProblems -Sid $script:N5StaleSid -OperatorSid $op.User -OperatorGroups $op.Groups -Resolve $res)
    Write-Host ("operator SID {0}; spike SID check: {1}; stale SID check: {2}" -f $op.User, $(if ($sp.Count) { 'REFUSED (exit 3): ' + ($sp -join '; ') } else { 'OK (resolves to the recorded SID, distinct from the operator and his groups)' }), $(if ($st.Count) { 'REFUSED: ' + ($st -join '; ') } else { 'OK (does not resolve)' }))
    Write-Host ''; Write-Host ('--- the first live action of every -Run: if S1 holds the srt-win set for the test account (and nothing else is there), halfset uninstall --sublayer {0} --live <harness proof> and a direct read-back that S1 is absent; anything else there is a STOP or a refusal ---' -f $script:N5SubLayers.S1)
    Write-Host ('    harness proof file: {0}' -f $HarnessLiveProof)
    Write-Host '--- states: exactly what each would do (harness arguments verbatim; every mutating call also carries --live <harness proof>; our plans as descriptors) ---'
    foreach ($s in $script:N5States) {
        Write-Host ("[{0}] phase {1}: {2}" -f $s.Id, $s.Phase, $s.Title) -ForegroundColor Cyan
        switch ($s.Kind) {
            'none' { Write-Host '    adds nothing' }
            'srt' {
                $sidv = Get-Nep5SidFor $s.Sid
                Write-Host ("    halfset install --sublayer {0} --sid {1}" -f $script:N5SubLayers.S1, $sidv)
                foreach ($r in @($s.Delete)) { Write-Host ("    halfset enum --sublayer {0}   then   halfset delete-filter --sublayer {0} --key <the one {1} filter>" -f $script:N5SubLayers.S1, $r) }
            }
            'ours' { $pl = Get-Nep5OurPlan -Id $s.Plan; Write-Host (Format-Nep5Plan $pl) }
            'n1' { Write-Host ("    plan o1 is added by us elevated first (provider, S2, one block); then the account's own standard token makes ONE direct FwpmFilterAdd0 (a block for its own SID in S2, key $($script:N5FilterKeys['s2-n1-probe-v4'])) and ONE direct FwpmFilterDeleteByKey0 (key $($script:N5FilterKeys['s2-block-v4'])); the engine's status codes are the verdicts (no harness, no explicit transaction)") }
        }
        Write-Host '    every pass: sweep (S1/S2/S3 enumerate zero + absent + export 0 hits) -> control -> add -> status/enum -> account+operator connects -> remove by key -> sweep'
    }
    $ports = "ports {0} (out of range), {1} (its neighbour), {2} (inside 60080-60089), each on 127.0.0.1 and [::1]; a listener that does not bind makes its rows NOT RUN" -f $script:N5PortOut, $script:N5PortNeighbour, $script:N5PortIn
    Write-Host ''; Write-Host "--- probes: $ports ---"
    Write-Host ("--- the account session (the task is NEVER edited): BEFORE any password change spike-provision.ps1 -DryRun (its own read-only precondition report) must pass; then a fresh random password is set on the local account '{0}' (looked up by its recorded SID {1}; name and SID both checked; written by that SID; kept in memory only), each probe runs as" -f $script:SpikeUser, $script:N5SpikeSid)
    Write-Host ("    that account: hidden, profile loaded, working folder {0}\bin, an INTERACTIVE-type logon (CreateProcessWithLogonW; not the batch logon the existing task uses), and an EXPLICIT environment block of only these variables, never the operator's: {2}`n    with the fixed command line:`n      powershell.exe {1}`n    the result comes back as a file in {0}\results (the account already has Modify there; no ACE is added). At the end of every session (every exit path)" -f $script:SpikeRoot, (Get-Nep5ProbeCommandLine), ($script:N5AccountEnvAllow -join ', '))
    Write-Host ("    spike-provision.ps1 -Apply -ForceNewPassword restores the original task credential (in a child Windows PowerShell 5.1 with the Windows PowerShell module path), and the restore is proven. The task's original arguments: {0}" -f $script:N5TaskOrigArgs)
    Write-Host ("    task now: {0}; files in {1}: {2}" -f (Get-Nep5TaskState -Ops (New-Nep5RealTaskOps)), $BinDir, $(if (@(Get-Nep5BinResidue -BinDir $BinDir).Count) { (@(Get-Nep5BinResidue -BinDir $BinDir)) -join ', ' } else { 'none' }))
    $ao = Test-AdminOnlyFolder -Path $PSScriptRoot
    if ($ao.Ok) { Write-Host "script folder: admin-only ($($ao.Checked) paths checked)." -ForegroundColor Green } else { Write-Host 'script folder: NOT admin-only; -Run would REFUSE from here:' -ForegroundColor Yellow; $ao.Problems | Select-Object -First 4 | ForEach-Object { Write-Host "   $_" -ForegroundColor Yellow } }
    Write-Host ''; Write-Host '--- rollback ---'
    Write-Host '  1. spike-nep5-matrix.ps1 -Remove   (elevated; by key; harness first, our engine second, then the snippet; exits 0 only when the direct checks read clean)'
    Write-Host '  2. if that cannot run, from an elevated PowerShell 7 (pwsh; Windows PowerShell 5.1 cannot load the compiled snippet on this machine) (no other file needed: it enumerates every filter, deletes those under S1/S2/S3 by key, reports any other filter of ours or srt-win''s, deletes the three sublayers and the provider):'
    $script:N5ManualRollbackSnippet -split "`r?`n" | ForEach-Object { Write-Host "       $_" }
    Write-Host '  3. then: netsh wfp show filters file=check.xml  and search it for "BlarAI #1763", "srt-win" and the three sublayer GUIDs (no hit = gone). -Check exit 20 alone is not the proof.'
    Write-Host '  4. if a run died: spike-nep5-matrix.ps1 -Remove re-provisions the account task and proves the restore; by hand that is spike-provision.ps1 -Apply -ForceNewPassword from an elevated prompt (the task is never edited), then delete the three files from the bin folder.'
    Write-Host ''; Write-Host '--- the rollback proof the add paths require ---'
    $proof = Test-N5Proof -ProofPath $ProofPath -Folder $PSScriptRoot -WrappedSha256 $script:WrappedSha256Used -HarnessExe $HarnessExe -HarnessSource $HarnessSource -CargoLock $CargoLock -HarnessLiveProof $HarnessLiveProof
    if ($proof.Ok) { Write-Host "  VALID (written $($proof.Written)): every script, the wrapped script, the harness exe, halfset.rs and Cargo.lock match." -ForegroundColor Green }
    else { $proof.Problems | ForEach-Object { Write-Host "  NO VALID PROOF: $_" -ForegroundColor Yellow }; Write-Host '  -Run would REFUSE until -SelfTest -WriteProof has been run on these exact files.' -ForegroundColor Yellow }
    Write-Host 'DRY RUN complete. Nothing was added.' -ForegroundColor Green
    if ($sp.Count) { return 3 }
    return 0
}

function Format-Nep5Plan {
    param($Plan)
    $l = @()
    if ($Plan.Provider) { $l += "    provider  $($script:N5ProviderKey)  persistent" }
    if ($Plan.SubLayer) { $l += "    sublayer  $($Plan.SubLayer)  persistent; provider: $(if ($Plan.SubLayerUsesProvider) { 'ours' } else { 'none' })" }
    foreach ($f in @($Plan.Filters)) { $l += "    filter    $($f.Key)  $($f.Name)  $(if ($f.V6) { 'V6' } else { 'V4' }) $(if ($f.Permit) { 'PERMIT' } else { 'BLOCK' })  user: $(if ($f.UserSid) { $f.UserSid } else { 'none' })$(if ($f.HasRemote) { "  remote 127.0.0.1:$($f.RemotePort)" })  provider: $(if ($f.UseProvider) { 'ours' } else { 'none' })" }
    foreach ($f in @($Plan.Attempts)) { $l += "    ATTEMPT   $($f.Key)  $($f.Name)  sublayer $($f.SubLayer)  provider: $(if ($f.UseProvider) { 'ours' } else { 'none' })  (the engine's answer is the recorded result)" }
    return ($l -join "`n")
}

# ---- -Run ------------------------------------------------------------------------------------------------------------------------------------
function Invoke-Run {
    Initialize-Nep5Session
    if (-not (Test-IsElevatedSafe)) { Write-Host 'REFUSED: not elevated.' -ForegroundColor Red; return 2 }
    if (-not [Environment]::Is64BitProcess) { Write-Host 'REFUSED: not a 64-bit process (WFP struct layout is asserted for x64).' -ForegroundColor Red; return 2 }
    $op = Get-OperatorTokenSids; $res = New-Nep5SidResolver
    $unsafe = @(Get-Nep5SidProblems -Sid $script:N5SpikeSid -OperatorSid $op.User -OperatorGroups $op.Groups -Resolve $res)
    if ($unsafe.Count) { Write-Host ('REFUSED (exit 3): ' + ($unsafe -join '; ')) -ForegroundColor Red; return 3 }
    $problems = @(Assert-SpikePreflight -ScriptFolder $PSScriptRoot)
    if ($problems.Count) { $problems | ForEach-Object { Write-Host "FAIL: $_" -ForegroundColor Red }; return 2 }
    foreach ($d in @($PSScriptRoot)) { $ao = Test-AdminOnlyFolder -Path $d; if (-not $ao.Ok) { Write-Host "REFUSED: $d is not admin-only: $(@($ao.Problems | Select-Object -First 2) -join '; ')" -ForegroundColor Red; return 2 } }
    New-Item -ItemType Directory -Force $OutDir | Out-Null
    $ao = Test-AdminOnlyFolder -Path $OutDir
    if (-not $ao.Ok) { Write-Host "REFUSED: the output folder $OutDir is not admin-only: $(@($ao.Problems | Select-Object -First 2) -join '; ')" -ForegroundColor Red; return 2 }
    $stg = @(Remove-Nep5StagedHarnessProof -HarnessProof $HarnessLiveProof); if ($stg.Count) { Write-Host "deleted a surviving staged harness proof: $($stg -join ', ')" -ForegroundColor Yellow }
    $stale = Remove-Nep5StaleHarnessProof -HarnessProof $HarnessLiveProof -MatrixProof $ProofPath
    if ($stale.Removed) { Write-Host "deleted a stale harness proof ($($stale.Reason))" -ForegroundColor Yellow }
    $proof = Test-N5Proof -ProofPath $ProofPath -Folder $PSScriptRoot -WrappedSha256 $script:WrappedSha256Used -HarnessExe $HarnessExe -HarnessSource $HarnessSource -CargoLock $CargoLock -HarnessLiveProof $HarnessLiveProof
    if (-not $proof.Ok) { $proof.Problems | ForEach-Object { Write-Host "REFUSED: $_" -ForegroundColor Red }; return 2 }
    $pl = @(Test-ProofLocation -ProofPath $ProofPath -ScriptFolder $PSScriptRoot)
    if ($pl.Count) { $pl | ForEach-Object { Write-Host "REFUSED: $_" -ForegroundColor Red }; return 2 }
    $stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
    $runner = New-HalfsetRunner -Exe $HarnessExe -ExpectedSha256 $proof.HarnessSha   # the hash the proof verified: a changed exe is refused before every run
    $script:N5LiveProof = $HarnessLiveProof   # the harness refuses every mutating verb (exit 12) without it
    $be = $null; $listeners = $null; $code = 4; $tmpFinal = $null
    try {
        $be = New-Nep5RealBackend
        $listeners = Start-Nep5Listeners -Ports @($script:N5PortOut, $script:N5PortNeighbour, $script:N5PortIn)
        foreach ($it in $listeners.Items) { Write-Host ("listener {0}:{1} bound: {2} {3}" -f $it.Family, $it.Port, $it.Bound, $it.Error) -ForegroundColor $(if ($it.Bound) { 'Green' } else { 'Yellow' }) }
        if (-not $listeners.Bound["v4:$($script:N5PortOut)"] -or -not $listeners.Bound["v4:$($script:N5PortIn)"]) { Write-Host 'REFUSED: the IPv4 listeners did not bind.' -ForegroundColor Red; return 2 }
        $expDir = Join-Path $OutDir "exports-$stamp"; New-Item -ItemType Directory -Force $expDir | Out-Null
        $drop = [bool]$DropCleanExports
        $exporter = { param($label) Invoke-Nep5Export -Label $label -Path (Join-Path $expDir "export-$label.xml") -DropClean:$drop }.GetNewClosure()
        $tmpFinal = New-PrivateTempDir
        $finalExp = { param($l) Invoke-Nep5Export -Label $l -Path (Join-Path $tmpFinal "final-$l.xml") -DropClean }.GetNewClosure()
        $sidFor = { param($sid) @(Get-Nep5SidProblems -Sid $sid -OperatorSid $op.User -OperatorGroups $op.Groups -Resolve $res) }.GetNewClosure()
        $aops = New-Nep5AccountOps -BinDir $BinDir
        $seams = New-Nep5ProvisionSeams -Folder $PSScriptRoot -ProvisionSha $proof.ProvisionSha -LibSha $proof.ProvisionLibSha -BinDir $BinDir
        $ctx = [pscustomobject]@{
            Runner = $runner; Backend = $be; Exporter = $exporter; Proof = $proof; SidProblemsFor = $sidFor
            AccountRun = (New-Nep5RealAccountRun -BinDir $BinDir -ExpectedSid $script:N5SpikeSid -AccountOps $aops)
            AccountOps = $aops
            Reprovision = $seams.Reprovision
            ProvisionDryRun = $seams.ProvisionDryRun
            OperatorConnect = { param($family, $port) $r = Test-Nep5Loopback -Family $family -Port $port; [pscustomobject]@{ ok = [bool]$r.ok; ms = $r.ms; error = $r.error } }
            OperatorProbe = { Test-TcpConnect '1.1.1.1' 443 2000 }
            OriginalTaskRun = { param($rid) Invoke-ProbeTaskRun -RunId $rid -ExpectedBlocked $false -TimeoutSec 60 }
            TaskOps = (New-Nep5RealTaskOps); BinDir = $BinDir; ScriptFolder = $PSScriptRoot; ProbeSha = $proof.ProbeSha; HarnessExe = $HarnessExe; HarnessSha = $proof.HarnessSha
            Bound = $listeners.Bound; Listeners = $listeners; OutDir = $OutDir; FixedDir = $FixedDir; RunStamp = $stamp; ProofStamp = $proof.Written.ToString('o'); Passes = $Passes; Only = $(if ($Only) { @($Only -split '[,+]') } else { $null }); TickGap = 2.0
        }
        Write-Host ("== phase {0}: {1} pass(es); a session password is set on the account for the run and the task is re-provisioned and proven at the end ==" -f $Phase, $Passes) -ForegroundColor Cyan
        $core = Invoke-Nep5RunCore -Ctx $ctx -Phase $Phase -FinalExporter $finalExp
        $code = $core.Code
    } catch {
        Write-Host "ERROR: $($_.Exception.Message)" -ForegroundColor Red; Write-Host $_.ScriptStackTrace -ForegroundColor DarkGray; $code = 4
    } finally {
        if ($be) { try { $be.Close() } catch {} }
        if ($listeners) { Stop-Nep5Listeners $listeners }
        if ($tmpFinal) { Remove-PrivateTempDir $tmpFinal }
    }
    Write-Host ("RESULT: exit {0}" -f $code) -ForegroundColor $(if ($code -eq 0) { 'Green' } else { 'Yellow' })
    return $code
}

# ---- -SelfTest -------------------------------------------------------------------------------------------------------------------------------
# ---- structure checks by the PowerShell parser (a command is found by its parsed name, never by raw text, so prose and strings never count) ------------
$script:N5ThreeScripts = @('spike-nep5-matrix.ps1', 'spike-nep5-lib.ps1', 'spike-nep5-run-lib.ps1')

function Find-Nep5Commands {
    # PURE on the files. Every parsed command call in $Files (under $Folder) whose command name matches $NameRegex (and, when given, whose text matches $TextRegex): @{ File; Line; Command; Function; Ast }.
    param([Parameter(Mandatory)][string]$Folder, [string[]]$Files = $script:N5ThreeScripts, [Parameter(Mandatory)][string]$NameRegex, [string]$TextRegex = '')
    $hits = @()
    foreach ($f in $Files) {
        $path = Join-Path $Folder $f; if (-not (Test-Path -LiteralPath $path)) { continue }
        $tokens = $null; $errs = $null; $ast = [Management.Automation.Language.Parser]::ParseFile($path, [ref]$tokens, [ref]$errs)
        foreach ($c in @($ast.FindAll({ param($n) $n -is [Management.Automation.Language.CommandAst] }, $true))) {
            $cn = $c.GetCommandName()
            if (-not $cn -or $cn -notmatch $NameRegex) { continue }
            if ($TextRegex -and $c.Extent.Text -notmatch $TextRegex) { continue }
            $fn = ''; $p = $c.Parent; while ($p) { if ($p -is [Management.Automation.Language.FunctionDefinitionAst]) { $fn = $p.Name; break }; $p = $p.Parent }
            $hits += [pscustomobject]@{ File = $f; Line = $c.Extent.StartLineNumber; Command = $cn; Function = $fn; Ast = $c }
        }
    }
    return @($hits)
}

function Get-Nep5TaskEditHits {
    # PURE. Calls in the three matrix scripts that would edit, create, re-register, disable or delete the account's task (the task is only ever put back by re-running spike-provision.ps1 in a child).
    param([Parameter(Mandatory)][string]$Folder)
    return @(@(Find-Nep5Commands -Folder $Folder -NameRegex '(?i)^(?:[\w.]+\\)?(?:(?:Set|Register|Unregister|Disable|Enable|New)-ScheduledTask|Set-Nep5TaskTarget)$') + @(Find-Nep5Commands -Folder $Folder -NameRegex '(?i)^schtasks(\.exe)?$' -TextRegex '(?i)/(change|create|delete)'))
}

function Get-Nep5PasswordWriteHits {
    # PURE. Calls in the matrix scripts and the probe that create, alter or set the password of a local account, or run `net user`. There must be exactly ONE, in New-Nep5AccountOps.
    param([Parameter(Mandatory)][string]$Folder)
    $files = @($script:N5ThreeScripts) + @('spike-nep5-connect-probe.ps1')
    return @(@(Find-Nep5Commands -Folder $Folder -Files $files -NameRegex '(?i)^(?:[\w.]+\\)?(?:(?:Set|New|Rename|Remove|Enable|Disable)-LocalUser|Set-LocalUserPassword|Set-ADAccountPassword)$') + @(Find-Nep5Commands -Folder $Folder -Files $files -NameRegex '(?i)^net(\.exe)?$' -TextRegex '(?i)\buser\b'))
}

function Test-Nep5SetPasswordWrite {
    # PURE. Problems with the one password write: it exists exactly once, inside New-Nep5AccountOps, and addresses the account by -SID (never -Name, never -InputObject, which would bind to whatever holds a name).
    param([Parameter(Mandatory)][string]$Folder)
    $h = @(Get-Nep5PasswordWriteHits -Folder $Folder); $p = @()
    if ($h.Count -ne 1) { return @("expected exactly one account password / account-write call in the scripts, found $($h.Count): $((@($h | ForEach-Object { "$($_.File):$($_.Line) $($_.Command)" })) -join '; ')") }
    if ($h[0].Function -ne 'New-Nep5AccountOps') { $p += "the one password write is in '$($h[0].Function)', not New-Nep5AccountOps" }
    if ($h[0].Command -ne 'Set-LocalUser') { $p += "the one account write is '$($h[0].Command)', not Set-LocalUser" }
    $pn = @($h[0].Ast.CommandElements | Where-Object { $_ -is [Management.Automation.Language.CommandParameterAst] } | ForEach-Object { $_.ParameterName })
    if ($pn -notcontains 'SID') { $p += 'the password write does not address the account by -SID' }
    if ($pn -contains 'Name' -or $pn -contains 'InputObject') { $p += 'the password write addresses the account by -Name or -InputObject' }
    return @($p)
}

function New-N5FakeProc {
    param([bool]$Hang)
    $p = [pscustomobject]@{ HasExited = (-not $Hang); ExitCode = 0; Killed = $false }
    $p | Add-Member -MemberType ScriptMethod -Name Kill -Value { $this.Killed = $true; $this.HasExited = $true; $this.ExitCode = -1 }
    return $p
}

function New-N5TestAccountOps {
    # The real New-Nep5AccountOps with every OS action replaced by a closure over the switch object $Sw (UserName, UserSid, FailSet, NoStart, Hang, OnStart, Secret, Sets, SetSids, Starts, EnvNames, MarkerPath, RecordAtSet).
    param($Sw, [string]$BinDir)
    $gu = { param($sid) [pscustomobject]@{ Name = $Sw.UserName; SID = [pscustomobject]@{ Value = $Sw.UserSid } } }.GetNewClosure()
    $np = { $Sw.Secret = 'Fp-' + [guid]::NewGuid().ToString('N') + '!aZ9'; ConvertTo-SecureString $Sw.Secret -AsPlainText -Force }.GetNewClosure()
    $sp = { param($u, $s) if ($Sw.FailSet) { throw 'fake account write failed' }; $Sw.RecordAtSet = $(if ($Sw.MarkerPath) { [bool](Test-Path -LiteralPath $Sw.MarkerPath) } else { $null }); [void]$Sw.Sets.Add([string]$u.Name); [void]$Sw.SetSids.Add([string]$u.SID.Value) }.GetNewClosure()
    $st = { param($cred, $exe, $argLine, $wd, $envBlock) [void]$Sw.Starts.Add("$exe $argLine"); $Sw.EnvNames = @($envBlock.Keys); if ($Sw.NoStart) { throw 'fake: the user name or password is incorrect' }; if ($Sw.OnStart) { & $Sw.OnStart }; New-N5FakeProc -Hang $Sw.Hang }.GetNewClosure()
    return (New-Nep5AccountOps -BinDir $BinDir -GetUser $gu -NewPassword $np -SetPasswordFn $sp -StartProcess $st -ComputerName 'TESTPC' -PollMs 20)
}

function Invoke-FakeReprovision {
    param($Ctx)
    $sw = $Ctx.RepSw; $sw.Count++
    if ($sw.Fail) { return [ordered]@{ Ok = $false; Detail = 'fake spike-provision failed'; Manual = 'fake manual command' } }
    $Ctx.TaskOps.Extra = $(if ($sw.Damage) { 'logon=lost' } else { 'logon=password' })
    return [ordered]@{ Ok = $true; Detail = 'fake ok'; Manual = 'fake manual command' }
}

function Invoke-FakeProvisionDryRun {
    param($Ctx)
    $sw = $Ctx.DrySw; $sw.Count++; $sw.SetsAtCall = $Ctx.AcctSw.Sets.Count
    if ($sw.Fail) { return [ordered]@{ Ok = $false; Detail = 'stand-in precondition fails' } }
    return [ordered]@{ Ok = $true; Detail = 'stand-in preconditions hold' }
}

function Get-N5DirText {
    param([string]$Dir)
    return ((@(Get-ChildItem -LiteralPath $Dir -Recurse -File -Force -ErrorAction SilentlyContinue | ForEach-Object { [IO.File]::ReadAllText($_.FullName) })) -join "`n")
}

function New-N5TestCtx {
    param([switch]$NoMarker)
    # A complete fake context: a fake world, backend, harness, exporter, account, tasks, with real temp folders for the account's bin folder and the script folder.
    $w = New-Nep5World
    $tmp = Join-Path ([IO.Path]::GetTempPath()) ('nep5-ctx-' + [guid]::NewGuid().ToString('N')); New-Item -ItemType Directory -Path $tmp | Out-Null
    $sf = Join-Path $tmp 'scripts'; $bin = Join-Path $tmp 'bin'; $out = Join-Path $tmp 'out'; $fx = Join-Path $tmp 'fixed'; New-Item -ItemType Directory -Path $sf, $bin, $out, $fx | Out-Null
    [IO.File]::WriteAllText((Join-Path $sf $script:N5ProbeScriptName), "# fake probe`n"); $exe = Join-Path $sf 'halfset.exe'; [IO.File]::WriteAllBytes($exe, [byte[]](1, 2, 3, 4))
    $script:N5ProofNonce = 'selftest-nonce'; $script:N5LiveProof = 'C:\fake\harness-live-proof-1763.json'
    $bound = @{}; foreach ($t in (Get-Nep5Targets -Bound @{})) { $bound[$t.Key] = $true }
    $resolve = { param($which) if ($which -eq 'spike') { $script:N5SpikeSid } else { $null } }
    $asw = [pscustomobject]@{ UserName = 'blarai-spike'; UserSid = $script:N5SpikeSid; FailSet = $false; NoStart = $false; Hang = $false; OnStart = $null; Secret = $null; Sets = (New-Object System.Collections.ArrayList); SetSids = (New-Object System.Collections.ArrayList); Starts = (New-Object System.Collections.ArrayList); EnvNames = @(); MarkerPath = (Join-Path $fx 'session-open-1763.json'); RecordAtSet = $null }
    $ctxObj = [pscustomobject]@{
        Tmp = $tmp; World = $w; Runner = (New-FakeHalfset -World $w); Backend = (New-Nep5FakeBackend -World $w); Exporter = (New-Nep5FakeExporter -World $w)
        Proof = [pscustomobject]@{ Kind = 'Nep5Proof'; Ok = $true; Nonce = 'selftest-nonce' }
        SidProblemsFor = { param($sid) @(Get-Nep5SidProblems -Sid $sid -OperatorSid 'S-1-5-21-1-2-3-1001' -OperatorGroups @('S-1-5-21-1-2-3-513') -Resolve $resolve) }.GetNewClosure()
        AccountRun = (New-Nep5FakeAccountRun -World $w)
        OperatorConnect = { param($family, $port) [pscustomobject]@{ ok = $true; ms = 1; error = '' } }
        OperatorProbe = { [pscustomobject]@{ ok = $true; ms = 1; error = ''; t = '' } }
        TaskOps = (New-Nep5FakeTaskOps); AccountOps = (New-N5TestAccountOps -Sw $asw -BinDir $bin); AcctSw = $asw; RepSw = [pscustomobject]@{ Count = 0; Fail = $false; Damage = $false }; Reprovision = { param($c) Invoke-FakeReprovision -Ctx $c }
        DrySw = [pscustomobject]@{ Count = 0; Fail = $false; SetsAtCall = $null }; ProvisionDryRun = { param($c) Invoke-FakeProvisionDryRun -Ctx $c }; BinDir = $bin; ScriptFolder = $sf; ProbeSha = (Get-NormalizedSha256 -Path (Join-Path $sf $script:N5ProbeScriptName)); HarnessExe = $exe; HarnessSha = (Get-N5RawSha256 -Path $exe)
        Bound = $bound; OutDir = $out; FixedDir = $fx; Passes = 1; Only = $null; TickGap = 0.0; RunStamp = 'testrun'; ProofStamp = '2026-10-13T10:26:44.1234567-04:00'; Listeners = $null
        OriginalTaskRun = { param($rid) [pscustomobject]@{ valid = $true; token_sid = $script:N5SpikeSid; task_start = $null } }
    }
    if (-not $NoMarker) { Write-Nep5TaskcheckMarker -Ctx $ctxObj -Ex ([pscustomobject]@{ DefinitionMatches = $true; StartedInOriginalForm = [pscustomobject]@{ Ok = $true } }) }
    return $ctxObj
}

function Get-N5Cell { param($Rec, [string]$Key) $Rec.steps.during.account.Summary[$Key] }

function Invoke-SelfTest {
    $script:f = 0; $script:tagsPassed = New-Object System.Collections.ArrayList; $script:tagsFailed = New-Object System.Collections.ArrayList; $script:failedNames = New-Object System.Collections.ArrayList; $script:chkTotal = 0
    function Chk([string]$n, [bool]$c, [string]$tag = '') {
        $script:chkTotal++
        if ($c) { Write-Host "  [PASS] $n" -ForegroundColor Green; if ($tag) { [void]$script:tagsPassed.Add($tag) } }
        else { Write-Host "  [FAIL] $n" -ForegroundColor Red; $script:f++; [void]$script:failedNames.Add($n); if ($tag) { [void]$script:tagsFailed.Add($tag) } }
    }
    $realWorkPath = Join-Path $script:SpikeRoot 'work'; $realWorkBefore = Get-Nep5TreeStamp -Path $realWorkPath   # read only: a self-test must leave the real account folder exactly as it found it
    $sidS = $script:N5SpikeSid; $sidO = 'S-1-5-21-1-2-3-1001'; $s1 = $script:N5SubLayers.S1; $s2 = $script:N5SubLayers.S2; $s3 = $script:N5SubLayers.S3
    Write-Host '== extraction from the wrapped script and compile (no engine is opened) ==' -ForegroundColor Cyan
    $imp = Import-WfpHelpers -Path $WfpScript -ExpectedSha256 $WfpSha256 -Unverified:(-not $WriteProof)
    Chk "all $($script:WrappedFunctions.Count) wrapped functions extracted; the wrapped script was only read (SHA-256 recorded)" (($imp.Functions.Count -eq $script:WrappedFunctions.Count) -and ($imp.Sha256 -match '^[0-9A-F]{64}$'))
    Initialize-Nep5Type
    Chk 'the WFP C# and the nep5 C# compile together in-process' ([bool]('BlarAI.Nep5.N5Engine' -as [type]) -and [bool]('BlarAI.Wfp.Plan' -as [type]))
    $K = [BlarAI.Nep5.N5Keys]
    Chk 'the C# constants equal the recorded PowerShell constants (S1, S2, S3, missing sublayer, provider, both SIDs, marker)' (($K::S1 -eq [guid]$s1) -and ($K::S2 -eq [guid]$s2) -and ($K::S3 -eq [guid]$s3) -and ($K::MissingSubLayer -eq [guid]$script:N5MissingSubLayer) -and ($K::Provider -eq [guid]$script:N5ProviderKey) -and ($K::SpikeSid -eq $sidS) -and ($K::StaleSid -eq $script:N5StaleSid) -and ($K::Marker -eq $script:N5Marker) -and ($K::ProviderName -eq $script:N5ProviderName))
    Chk 'the three sublayers differ from each other, from srt-win''s default and from the old arm 3 sublayer; our provider differs from the old arm 3 provider' ((@($script:N5SubLayers.Values + @($script:N5SrtDefaultSubLayer, $script:N5OldArm3SubLayer) | Select-Object -Unique).Count -eq 5) -and ($script:N5ProviderKey -ne $script:N5OldArm3Provider))
    Chk 'the SDK GUIDs of the remote address and remote port conditions are the ones read from fwpmu.h' (($K::CondRemoteAddress -eq [guid]'b235ae9a-1d64-49b8-a44c-5ff3d9095045') -and ($K::CondRemotePort -eq [guid]'c35a604d-d22b-4e1a-91b4-68f674ee674b'))
    Chk 'every one of our filter keys is a distinct GUID and none equals a sublayer or the provider' ((@($script:N5FilterKeys.Values | Select-Object -Unique).Count -eq $script:N5FilterKeys.Count) -and (@($script:N5FilterKeys.Values | Where-Object { -not (ConvertTo-N5Guid $_) -or $script:N5SubLayers.Values -contains $_ -or $_ -eq $script:N5ProviderKey }).Count -eq 0))
    Write-Host '== C# guards, offline (marshalling in memory only; every refusal is in front of any engine call) ==' -ForegroundColor Cyan
    $mkF = { param($id, $over) $d = New-N5FilterDescriptor -Id $id -SubLayer $s2 -V6 $false -Permit $false -Sid $sidS -UseProvider $true; foreach ($k in $over.Keys) { $d.$k = $over[$k] }; ConvertTo-N5Filter $d }
    $thrown = { param($f) $t = $false; try { [BlarAI.Nep5.N5Set]::ValidateFilter($f) } catch { $t = $true }; $t }
    Chk 'C# guard: a plain block for the test account in S2 is accepted' (-not (& $thrown (& $mkF 's2-block-v4' @{})))
    Chk 'C# guard: srt-win''s default sublayer, the old arm 3 sublayer and a random GUID are each refused' ((& $thrown (& $mkF 's2-block-v4' @{ SubLayer = $script:N5SrtDefaultSubLayer })) -and (& $thrown (& $mkF 's2-block-v4' @{ SubLayer = $script:N5OldArm3SubLayer })) -and (& $thrown (& $mkF 's2-block-v4' @{ SubLayer = '11111111-2222-3333-4444-555555555555' }))) 'sublayer-allowlist'
    Chk 'C# guard: the operator''s SID, a group SID, Everyone, SYSTEM and a garbage SID are each refused' ((& $thrown (& $mkF 's2-block-v4' @{ UserSid = $sidO })) -and (& $thrown (& $mkF 's2-block-v4' @{ UserSid = 'S-1-5-21-1-2-3-513' })) -and (& $thrown (& $mkF 's2-block-v4' @{ UserSid = 'S-1-1-0' })) -and (& $thrown (& $mkF 's2-block-v4' @{ UserSid = 'S-1-5-18' })) -and (& $thrown (& $mkF 's2-block-v4' @{ UserSid = 'garbage' }))) 'operator-sid-refused'
    Chk 'C# guard: the stale test SID is accepted (the one other allowed SID)' (-not (& $thrown (& $mkF 's2-block-v4' @{ UserSid = $script:N5StaleSid })))
    Chk 'C# guard: a BLOCK with no user condition, a filter with no condition at all, a name without the marker and a v4 address on a v6 filter are each refused' ((& $thrown (& $mkF 's2-block-v4' @{ UserSid = $null; HasRemote = $true; RemotePort = 1234; RemoteAddr = [uint32]2130706433 })) -and (& $thrown (& $mkF 's2-block-v4' @{ UserSid = $null; Permit = $true })) -and (& $thrown (& $mkF 's2-block-v4' @{ Name = 'nobody' })) -and (& $thrown (& $mkF 's2-block-v4' @{ Permit = $true; HasRemote = $true; V6 = $true; RemotePort = 1234 })))
    Chk 'C# guard: the recorded missing sublayer is accepted only for an ATTEMPT row without a provider; the same sublayer on an ordinary filter, or an attempt row carrying a provider, is refused' ((-not (& $thrown (& $mkF 's2-missing-sublayer-v4' @{ SubLayer = $script:N5MissingSubLayer; UseProvider = $false; Attempt = $true }))) -and (& $thrown (& $mkF 's2-missing-sublayer-v4' @{ SubLayer = $script:N5MissingSubLayer; UseProvider = $false; Attempt = $false })) -and (& $thrown (& $mkF 's2-missing-sublayer-v4' @{ SubLayer = $script:N5MissingSubLayer; UseProvider = $true; Attempt = $true })))
    $badSet = New-Object BlarAI.Nep5.N5Set; $badSet.AddSubLayer = $true; $badSet.SubLayer = [guid]$script:N5SrtDefaultSubLayer; $t1 = $false; try { $badSet.Validate() } catch { $t1 = $true }
    $setAtt = New-Object BlarAI.Nep5.N5Set; $setAtt.Filters.Add((& $mkF 's2-missing-sublayer-v4' @{ SubLayer = $script:N5MissingSubLayer; UseProvider = $false; Attempt = $true })); $t2 = $false; try { $setAtt.Validate() } catch { $t2 = $true }
    Chk 'C# guard: a SET that adds srt-win''s default sublayer is refused; an attempt filter cannot ride in an add set' ($t1 -and $t2) 'sublayer-allowlist'
    $m = [BlarAI.Nep5.N5Marshal]::Build((ConvertTo-N5Set (Get-Nep5OurPlan -Id 'o4')))
    try {
        Chk 'marshalling o4: provider, sublayer and EVERY filter carry the persistent flag; three filters; each filter references the S2 sublayer' (($m.Provider.flags -eq 1) -and ($m.SubLayer.flags -eq 1) -and ($m.Filters.Count -eq 3) -and (@($m.Filters | Where-Object { $_.flags -ne 1 -or $_.subLayerKey -ne [guid]$s2 }).Count -eq 0))
        Chk 'marshalling o4: a block carries ONE condition (the user SD); the exact-port permit carries TWO (remote address, remote port) and NO user condition' (($m.Conditions[0].Count -eq 1) -and ($m.Conditions[0][0].fieldKey -eq [BlarAI.Wfp.Plan]::CondAleUserId) -and ($m.Conditions[2].Count -eq 2) -and (@($m.Conditions[2] | Where-Object { $_.fieldKey -eq [BlarAI.Wfp.Plan]::CondAleUserId }).Count -eq 0) -and ($m.Conditions[2][0].fieldKey -eq $K::CondRemoteAddress) -and ($m.Conditions[2][1].fieldKey -eq $K::CondRemotePort))
        Chk 'marshalling o4: the exact-port permit is 127.0.0.1 (0x7F000001) port 61763 as FWP_UINT32 / FWP_UINT16, action PERMIT, weight above the blocks' (($m.Conditions[2][0].conditionValue.value.ToInt64() -eq 2130706433) -and ($m.Conditions[2][0].conditionValue.type -eq 3) -and ($m.Conditions[2][1].conditionValue.value.ToInt64() -eq $script:N5PortOut) -and ($m.Conditions[2][1].conditionValue.type -eq 2) -and ($m.Filters[2].action.type -eq [BlarAI.Wfp.Plan]::FWP_ACTION_PERMIT) -and ($m.Filters[0].action.type -eq [BlarAI.Wfp.Plan]::FWP_ACTION_BLOCK) -and ([Runtime.InteropServices.Marshal]::ReadInt64($m.Filters[2].weight.value) -gt [Runtime.InteropServices.Marshal]::ReadInt64($m.Filters[0].weight.value)))
        Chk 'marshalling o4: layers are ALE_AUTH_CONNECT V4 / V6 / V4 (fwpmu.h literals)' (($m.Filters[0].layerKey -eq [guid]'c38d57d1-05a7-4c33-904f-7fbceee60e82') -and ($m.Filters[1].layerKey -eq [guid]'4a72393b-319f-44bc-84c3-ba54dcb3b6b4') -and ($m.Filters[2].layerKey -eq [guid]'c38d57d1-05a7-4c33-904f-7fbceee60e82'))
        if ([Environment]::Is64BitProcess) { Chk 'x64 sizeof FWPM_FILTER0 == 200 and FWPM_FILTER_CONDITION0 == 40 (the wrapped layout the arms asserted)' (([Runtime.InteropServices.Marshal]::SizeOf([type][BlarAI.Wfp.FWPM_FILTER0]) -eq 200) -and ([Runtime.InteropServices.Marshal]::SizeOf([type][BlarAI.Wfp.FWPM_FILTER_CONDITION0]) -eq 40)) }
        else { Write-Host '  [SKIP] struct-size asserts need a 64-bit process' -ForegroundColor Yellow }
    } finally { $m.Free() }
    $m1 = [BlarAI.Nep5.N5Marshal]::BuildOne((ConvertTo-N5Filter (Get-Nep5OurPlan -Id 'o5').Attempts[0]))
    $m6 = [BlarAI.Nep5.N5Marshal]::BuildOne((ConvertTo-N5Filter (Get-Nep5OurPlan -Id 'o6').Attempts[0]))
    try { Chk 'marshalling the attempts: o5 has no provider reference and names S2; o6 has no provider reference and names the missing sublayer' (($m1.Filters[0].providerKey -eq [IntPtr]::Zero) -and ($m1.Filters[0].subLayerKey -eq [guid]$s2) -and ($m6.Filters[0].providerKey -eq [IntPtr]::Zero) -and ($m6.Filters[0].subLayerKey -eq [guid]$script:N5MissingSubLayer)) } finally { $m1.Free(); $m6.Free() }
    Write-Host '== the manual rollback snippet compiles (it is NOT run) and its output parser ==' -ForegroundColor Cyan
    $cs = [regex]::Match($script:N5ManualRollbackSnippet, '(?s)@"\r?\n(.*?)\r?\n"@').Groups[1].Value
    $compiled = $false; $compErr = ''; try { Add-Type -TypeDefinition $cs -Language CSharp; $compiled = [bool]('ManualNep5Rollback' -as [type]) } catch { $compiled = $false; $compErr = $_.Exception.Message }
    if (-not $compiled -and $PSVersionTable.PSEdition -eq 'Desktop' -and $compErr -match 'Access .* is denied') { Write-Host "  [SKIP] the snippet's C# was not compiled: Windows PowerShell 5.1 writes it to a DLL under %TEMP% and this machine's endpoint protection refused to load it ($compErr). Run this self-test, and the snippet, under PowerShell 7 (pwsh), which compiles in memory." -ForegroundColor Yellow }
    else { if ($compErr) { Write-Host "    compile error: $compErr" -ForegroundColor Red }; Chk 'the snippet''s C# compiles and exposes Run()' ($compiled -and $null -ne ('ManualNep5Rollback' -as [type]).GetMethod('Run')) }
    $ixs = @($s1, $s2, $s3, $script:N5ProviderKey | ForEach-Object { $script:N5ManualRollbackSnippet.IndexOf($_) })
    Chk 'the snippet names S1, S2, S3 and the provider, and deletes filters, then sublayers, then the provider' (($ixs -notcontains -1) -and ($script:N5ManualRollbackSnippet.IndexOf('FwpmFilterDeleteByKey0(h, ref k)') -lt $script:N5ManualRollbackSnippet.IndexOf('FwpmSubLayerDeleteByKey0(h, ref k)')) -and ($script:N5ManualRollbackSnippet.IndexOf('FwpmSubLayerDeleteByKey0(h, ref k)') -lt $script:N5ManualRollbackSnippet.IndexOf('FwpmProviderDeleteByKey0(h, ref pk)')))
    Chk 'the snippet reports (never deletes) a filter outside S1/S2/S3 and enumerates with a NULL template (every layer)' (($script:N5ManualRollbackSnippet -match 'foreign') -and ($script:N5ManualRollbackSnippet -match 'FwpmFilterCreateEnumHandle0\(h, IntPtr\.Zero, out en\)'))
    $good = ConvertFrom-ManualN5Output -Text ("filter f1763001-0000-4d8e-9a31-2b6d4c8e0001 0x00000000`nfilter b1763001-0000-4d8e-9a31-2b6d4c8e1111 0x00000000`nsublayer $s1 0x00000000`nsublayer $s2 0x80320007`nsublayer $s3 0x80320007`nprovider $($script:N5ProviderKey) 0x80320005`n")
    $none = ConvertFrom-ManualN5Output -Text ("sublayer $s1 0x80320007`nsublayer $s2 0x80320007`nsublayer $s3 0x80320007`nprovider $($script:N5ProviderKey) 0x80320005`n")
    $badSt = ConvertFrom-ManualN5Output -Text ("sublayer $s1 0x8032000A`nsublayer $s2 0x80320007`nsublayer $s3 0x80320007`nprovider $($script:N5ProviderKey) 0x80320005`n")
    $forn = ConvertFrom-ManualN5Output -Text ("foreign aaaaaaaa-0000-4d8e-9a31-2b6d4c8e0001 11111111-2222-3333-4444-555555555555 srt-win-v4-block-user`nsublayer $s1 0x80320007`nsublayer $s2 0x80320007`nsublayer $s3 0x80320007`nprovider $($script:N5ProviderKey) 0x80320005`n")
    Chk 'manual rollback output: deleted/already-gone rows -> Ok; no filter rows is fine; a delete error (FWP_E_IN_USE) -> not Ok; a foreign line -> not Ok; an engine-open failure -> not Ok; short output -> not Ok' (($good.Ok -eq $true) -and ($none.Ok -eq $true) -and ($badSt.Ok -eq $false) -and ($forn.Ok -eq $false) -and ((ConvertFrom-ManualN5Output -Text 'engine open failed 0x80320001').Ok -eq $false) -and ((ConvertFrom-ManualN5Output -Text "provider $($script:N5ProviderKey) 0x00000000").Ok -eq $false))

    Write-Host '== the harness contract: argument allowlist, outcome mapping, JSON reading ==' -ForegroundColor Cyan
    $va = { param($argv) Test-HalfsetArgv -Argv $argv }
    Chk 'argv: every shape the matrix uses is accepted (install, status, enum, enum --all-ours, delete-filter, delete-sublayer, uninstall, selftest-refusals, --version)' ((& $va @('install', '--sublayer', $s1, '--sid', $sidS)).Ok -and (& $va @('install', '--sublayer', $s1, '--sid', $script:N5StaleSid)).Ok -and (& $va @('status', '--sublayer', $s1)).Ok -and (& $va @('enum', '--sublayer', $s3)).Ok -and (& $va @('enum', '--all-ours')).Ok -and (& $va @('delete-filter', '--sublayer', $s2, '--key', $script:N5FilterKeys['s2-block-v4'])).Ok -and (& $va @('delete-sublayer', '--sublayer', $s2)).Ok -and (& $va @('uninstall', '--sublayer', $s1)).Ok -and (& $va @('selftest-refusals')).Ok -and (& $va @('--version')).Ok)
    $rd = & $va @('enum', '--sublayer', $script:N5SrtDefaultSubLayer); $ro = & $va @('install', '--sublayer', $script:N5OldArm3SubLayer, '--sid', $sidS); $rr = & $va @('delete-sublayer', '--sublayer', '7e1f6a10-5c0b-4d8e-9a31-2b6d4c8e3f99')
    Chk 'argv: srt-win''s default sublayer, the old arm 3 sublayer and an unlisted GUID are each refused as a STOP (class sublayer) for every verb' ((-not $rd.Ok) -and $rd.Class -eq 'sublayer' -and (-not $ro.Ok) -and $ro.Class -eq 'sublayer' -and (-not $rr.Ok) -and $rr.Class -eq 'sublayer' -and ((& $va @('status', '--sublayer', $script:N5SrtDefaultSubLayer)).Class -eq 'sublayer') -and ((& $va @('uninstall', '--sublayer', $script:N5SrtDefaultSubLayer)).Class -eq 'sublayer') -and ((& $va @('delete-filter', '--sublayer', $script:N5SrtDefaultSubLayer, '--key', $script:N5FilterKeys['s2-block-v4'])).Class -eq 'sublayer')) 'sublayer-allowlist'
    $so = & $va @('install', '--sublayer', $s1, '--sid', $sidO); $sg = & $va @('install', '--sublayer', $s1, '--sid', 'S-1-5-21-1-2-3-513'); $sw2 = & $va @('install', '--sublayer', $s1, '--sid', 'S-1-1-0')
    Chk 'argv: install with the operator''s SID, a group SID, Everyone or no SID is refused (class sid / syntax) before any run' (((-not $so.Ok) -and $so.Class -eq 'sid') -and ((-not $sg.Ok) -and $sg.Class -eq 'sid') -and ((-not $sw2.Ok) -and $sw2.Class -eq 'sid') -and (-not (& $va @('install', '--sublayer', $s1)).Ok)) 'operator-sid-refused'
    Chk 'argv: unknown verb, an uppercase GUID, an extra token, a repeated option, --all-ours with a sublayer, a bad delete key, a missing key and a range with letters are each refused' ((-not (& $va @('format-c')).Ok) -and (-not (& $va @('enum', '--sublayer', $s1.ToUpperInvariant())).Ok) -and (-not (& $va @('enum', '--sublayer', $s1, '--extra')).Ok) -and (-not (& $va @('enum', '--sublayer', $s1, '--sublayer', $s1)).Ok) -and (-not (& $va @('enum', '--all-ours', '--sublayer', $s1)).Ok) -and (-not (& $va @('delete-filter', '--sublayer', $s2, '--key', '..\evil')).Ok) -and (-not (& $va @('delete-filter', '--sublayer', $s2)).Ok) -and (-not (& $va @('install', '--sublayer', $s1, '--sid', $sidS, '--range', 'abc-def')).Ok) -and (-not (& $va @()).Ok))
    $calls = New-Object System.Collections.ArrayList; $spy = { param([string[]]$Argv) [void]$calls.Add($Argv -join ' '); [pscustomobject]@{ ExitCode = 0; Stdout = '{}'; Stderr = ''; TimedOut = $false } }.GetNewClosure()
    $ref = Invoke-Halfset -Runner $spy -Argv @('enum', '--sublayer', $script:N5SrtDefaultSubLayer)
    Chk 'Invoke-Halfset: a refused vector is NEVER handed to the Runner (lock on)' ($ref.Refused -and $calls.Count -eq 0 -and $ref.Outcome -eq 'refused_before_run')
    $off = Invoke-Halfset -Runner $spy -Argv @('enum', '--sublayer', $script:N5SrtDefaultSubLayer) -ArgvValidator { param($v) [ordered]@{ Ok = $true; Class = ''; Reason = '' } }
    Chk 'Invoke-Halfset: with the validator switched OFF the same vector reaches the Runner (so the refusal above is the lock, not an unreachable path)' ((-not $off.Refused) -and $calls.Count -eq 1)
    $tmap = @(0, 3, 4, 5, 6, 7, 8, 9, 10, 11 | ForEach-Object { $x = $_; $r = Invoke-Halfset -Runner ({ param([string[]]$Argv) [pscustomobject]@{ ExitCode = $x; Stdout = '{"ok":true}'; Stderr = ''; TimedOut = $false } }.GetNewClosure()) -Argv @('status', '--sublayer', $s1); $r.Outcome })
    Chk 'exit-code mapping: 0 ok, 3 sublayer_refused, 4 sid_refused, 5 sublayer_not_empty, 6 not_elevated_engine_unreadable, 7 engine_denied, 8 readback_mismatch, 9 stop_foreign_filter, 10 engine_error, 11 delete_target_not_under_sublayer' (($tmap -join ',') -eq 'ok,sublayer_refused,sid_refused,sublayer_not_empty,not_elevated_engine_unreadable,engine_denied,readback_mismatch,stop_foreign_filter,engine_error,delete_target_not_under_sublayer')
    $thr = Invoke-Halfset -Runner { param([string[]]$Argv) throw 'boom' } -Argv @('status', '--sublayer', $s1)
    $gj = Invoke-Halfset -Runner { param([string[]]$Argv) [pscustomobject]@{ ExitCode = 0; Stdout = 'not json'; Stderr = ''; TimedOut = $false } } -Argv @('status', '--sublayer', $s1)
    Chk 'Invoke-Halfset: a Runner that throws is exit -2 with the text, output that is not JSON leaves Json null and never throws' (($thr.ExitCode -eq -2 -and $thr.Stderr -match 'boom') -and ($null -eq $gj.Json) -and ($gj.ExitCode -eq 0))
    $okEnum = ConvertFrom-HarnessFilters -Json (ConvertFrom-Json '{"count":2,"filters":[{"key":"B1763001-0000-4D8E-9A31-C971A69F0001","sublayer":"C971A69F-D6AB-4885-9B49-506D8AA51C86","layer":"ale_auth_connect_v4","name":"srt-win-v4-block-user","kind":"block-user","user_sid":"S-1-5-21-1-2-3-4","has_user_condition":true},{"key":"b1763002-0000-4d8e-9a31-c971a69f0002","sublayer":"c971a69f-d6ab-4885-9b49-506d8aa51c86","layer":"ale_auth_connect_v6","name":"srt-win-v6-permit-loopback-user","kind":"permit-loopback-user","user_sid":"S-1-5-21-1-2-3-4","has_user_condition":true}]}')
    Chk 'enum reading: rows are normalised (lowercase GUIDs, v4/v6 from the layer text); roles are block-v4 and permit-v6 from the srt-win tag kinds' (($okEnum.Ok) -and $okEnum.Rows.Count -eq 2 -and $okEnum.Rows[0].SubLayer -eq $s1 -and $okEnum.Rows[0].Key -eq 'b1763001-0000-4d8e-9a31-c971a69f0001' -and ((Get-SrtRole $okEnum.Rows[0]) -eq 'block-v4') -and ((Get-SrtRole $okEnum.Rows[1]) -eq 'permit-v6') -and ((Get-SrtRole ([pscustomobject]@{ Layer = 'other'; Name = 'x'; Kind = 'block-user' })) -eq 'other'))
    Chk 'enum reading: no filters member, a row with no readable key, a count that disagrees with the rows, and no JSON at all are each NOT Ok (an unreadable answer is never "zero filters")' ((-not (ConvertFrom-HarnessFilters -Json (ConvertFrom-Json '{"ok":true}')).Ok) -and (-not (ConvertFrom-HarnessFilters -Json (ConvertFrom-Json '{"filters":[{"key":"nope","sublayer":"c971a69f-d6ab-4885-9b49-506d8aa51c86"}]}')).Ok) -and (-not (ConvertFrom-HarnessFilters -Json (ConvertFrom-Json '{"count":3,"filters":[]}')).Ok) -and (-not (ConvertFrom-HarnessFilters -Json $null).Ok) -and ((ConvertFrom-HarnessFilters -Json (ConvertFrom-Json '{"count":0,"filters":[]}')).Ok))
    Chk 'status reading: installed / absent / cannot-read come from srt_win_status.state; anything else is unparsed' (((Get-SrtStatusWord (ConvertFrom-Json '{"ok":true,"srt_win_status":{"state":"installed"}}')) -eq 'installed') -and ((Get-SrtStatusWord (ConvertFrom-Json '{"srt_win_status":{"state":"absent"}}')) -eq 'absent') -and ((Get-SrtStatusWord (ConvertFrom-Json '{"srt_win_status":{"state":"cannot-read"}}')) -eq 'cannot-read') -and ((Get-SrtStatusWord (ConvertFrom-Json '{"srt_win_status":{"state":"weird"}}')) -eq 'unparsed') -and ((Get-SrtStatusWord $null) -eq 'unparsed'))
    Chk 'failure classes: sublayer refusal and exit 9 are STOP, a SID refusal is unsafe, exit 7 denied, exit 6 unreadable' (((Get-HarnessFailureClass ([pscustomobject]@{ Refused = $true; Class = 'sublayer' })) -eq 'stop') -and ((Get-HarnessFailureClass ([pscustomobject]@{ Refused = $false; ExitCode = 9 })) -eq 'stop') -and ((Get-HarnessFailureClass ([pscustomobject]@{ Refused = $true; Class = 'sid' })) -eq 'unsafe') -and ((Get-HarnessFailureClass ([pscustomobject]@{ Refused = $false; ExitCode = 7 })) -eq 'denied') -and ((Get-HarnessFailureClass ([pscustomobject]@{ Refused = $false; ExitCode = 6 })) -eq 'unreadable'))
    Write-Host '== the real Runner against a harness STUB (a .cmd file, never the real exe): hash binding, hidden start, trace variable ==' -ForegroundColor Cyan
    $stubDir = Join-Path ([IO.Path]::GetTempPath()) ('nep5-stub-' + [guid]::NewGuid().ToString('N')); New-Item -ItemType Directory -Path $stubDir | Out-Null
    try {
        $stub = Join-Path $stubDir 'stub.cmd'; $ran = Join-Path $stubDir 'ran.txt'; $trace = Join-Path $stubDir 'trace.txt'
        [IO.File]::WriteAllText($stub, "@echo off`r`necho ran> `"%~dp0ran.txt`"`r`nif defined HALFSET_ENGINE_OPEN_TRACE echo traced>> `"%HALFSET_ENGINE_OPEN_TRACE%`"`r`necho {`"ok`":true,`"engine_opens`":0}`r`nexit /b 0`r`n")
        $stubSha = Get-N5RawSha256 -Path $stub
        $rn = New-HalfsetRunner -Exe $stub -ExpectedSha256 $stubSha -TracePath $trace
        $out = & $rn @('status', '--sublayer', $s1)
        Chk 'Runner: with the recorded hash the stub runs, its stdout comes back as the one JSON object, its exit code is read, and the trace variable reached it' (($out.ExitCode -eq 0) -and ($out.Stdout -match '"ok":true') -and (Test-Path $ran) -and (Test-Path $trace))
        Remove-Item $ran -Force
        $rnBad = New-HalfsetRunner -Exe $stub -ExpectedSha256 ('AB' * 32)
        $outBad = & $rnBad @('status', '--sublayer', $s1)
        Chk 'Runner: an exe whose hash is not the recorded one is NOT run (exit -1, no marker file)' (($outBad.ExitCode -eq -1) -and ($outBad.Stderr -match 'refusing to run') -and -not (Test-Path $ran)) 'harness-hash-binding'
        [IO.File]::AppendAllText($stub, "rem edited after the proof`r`n")
        $outEdit = & $rn @('status', '--sublayer', $s1)
        Chk 'Runner: the exe edited AFTER the runner was built (check-then-use) is refused at the next run' (($outEdit.ExitCode -eq -1) -and -not (Test-Path $ran)) 'harness-hash-binding'
        $chk1 = [ordered]@{}
        Remove-Item $trace -Force -ErrorAction SilentlyContinue
        $stub2 = Join-Path $stubDir 'stub2.cmd'
        [IO.File]::WriteAllText($stub2, "@echo off`r`nif `"%1`"==`"--version`" (echo {`"version`":`"stub`",`"pinned_srt_win_sha`":`"$($script:N5PinnedSrtSha)`",`"pinned_cargo_lock_sha256`":`"$($script:N5PinnedCargoLockSha256.ToLowerInvariant())`",`"halfset_rs_sha256`":`"$('ab' * 32)`"}) else (echo {`"ok`":true,`"engine_opens`":0,`"failed`":0})`r`nexit /b 0`r`n")
        $rn2 = New-HalfsetRunner -Exe $stub2 -ExpectedSha256 (Get-N5RawSha256 -Path $stub2) -TracePath $trace
        $hc = Get-N5HarnessSelfChecks -Runner $rn2 -TracePath $trace -LockSha256 $script:N5PinnedCargoLockSha256 -RsSha256 ('AB' * 32)
        Chk 'harness self-checks: version shows the pinned SHA and Cargo.lock hash, selftest-refusals exits 0 with engine_opens 0, and the engine-open trace is empty' ($hc.version_ok -and $hc.refusals_exit_zero -and $hc.engine_open_trace_empty)
        $rn3 = New-HalfsetRunner -Exe $stub -ExpectedSha256 (Get-N5RawSha256 -Path $stub) -TracePath $trace
        $hc3 = Get-N5HarnessSelfChecks -Runner $rn3 -TracePath $trace -LockSha256 $script:N5PinnedCargoLockSha256
        Chk 'harness self-checks (lock OFF): a harness that touches the engine during its refusal test (writes the trace) is caught: engine_open_trace_empty false, version not ok' ((-not $hc3.engine_open_trace_empty) -and (-not $hc3.version_ok))
        $hcBadLock = Get-N5HarnessSelfChecks -Runner $rn2 -TracePath (Join-Path $stubDir 'none.txt') -LockSha256 ('00' * 32)
        $hcBadRs = Get-N5HarnessSelfChecks -Runner $rn2 -TracePath (Join-Path $stubDir 'none.txt') -LockSha256 $script:N5PinnedCargoLockSha256 -RsSha256 ('CD' * 32)
        Chk 'harness self-checks: a Cargo.lock hash that is not the one the harness reports makes version_ok false; so does a halfset.rs hash the exe does not report' ((-not $hcBadLock.version_ok) -and (-not $hcBadRs.version_ok))
    } finally { Remove-Item -LiteralPath $stubDir -Recurse -Force -ErrorAction SilentlyContinue }

    Write-Host '== SID allowlist (the arms'' own safety function behind it) ==' -ForegroundColor Cyan
    $resOk = { param($w) if ($w -eq 'spike') { $script:N5SpikeSid } else { $null } }
    $sp = { param($sid, $res = $resOk, $g = @('S-1-5-21-1-2-3-513')) @(Get-Nep5SidProblems -Sid $sid -OperatorSid $sidO -OperatorGroups $g -Resolve $res) }
    Chk 'SID: the spike SID (resolving to itself) and the stale SID (not resolving) are accepted; the operator''s SID, a token group, Everyone, a random account SID are refused' (((& $sp $sidS).Count -eq 0) -and ((& $sp $script:N5StaleSid).Count -eq 0) -and ((& $sp $sidO).Count -ge 1) -and ((& $sp 'S-1-5-21-1-2-3-513').Count -ge 1) -and ((& $sp 'S-1-1-0').Count -ge 1) -and ((& $sp 'S-1-5-21-9-9-9-5000').Count -ge 1)) 'operator-sid-refused'
    Chk 'SID: the spike account resolving to a DIFFERENT SID is refused; the stale SID RESOLVING to an account is refused; the spike SID being a token group is refused by the arms'' own function' (((& $sp $sidS { param($w) 'S-1-5-21-9-9-9-9999' }).Count -ge 1) -and ((& $sp $script:N5StaleSid { param($w) 'MACHINE\someone' }).Count -ge 1) -and ((& $sp $sidS $resOk @($sidS)).Count -ge 1))
    Write-Host '== plans ==' -ForegroundColor Cyan
    $plans = @('o1', 'o2', 'o3', 'o4', 'o5', 'o6', 'r7' | ForEach-Object { Get-Nep5OurPlan -Id $_ })
    Chk 'all seven plans pass the plan gate (allowed sublayers, allowed SIDs, markers, blocks carry the user condition)' (@($plans | ForEach-Object { @(Get-Nep5PlanProblems -Plan $_) } | Where-Object { $_ }).Count -eq 0)
    $o4 = Get-Nep5OurPlan -Id 'o4'; $o6 = Get-Nep5OurPlan -Id 'o6'; $r7 = Get-Nep5OurPlan -Id 'r7'; $o1 = Get-Nep5OurPlan -Id 'o1'
    Chk 'plans: o4 has an exact-port permit (127.0.0.1, no user condition) beside two blocks; o6 names only the missing sublayer and adds nothing; r7 uses S3; the others use S2' ((@($o4.Filters | Where-Object { $_.Permit -and $_.HasRemote -and -not $_.UserSid -and $_.RemotePort -eq $script:N5PortOut }).Count -eq 1) -and (@($o4.Filters | Where-Object { -not $_.Permit }).Count -eq 2) -and (-not $o6.Provider) -and (-not $o6.SubLayer) -and ($o6.Attempts[0].SubLayer -eq $script:N5MissingSubLayer) -and ($r7.SubLayer -eq $s3) -and ($o1.SubLayer -eq $s2))
    $bad1 = Get-Nep5OurPlan -Id 'o1'; $bad1.Filters[0].SubLayer = $script:N5SrtDefaultSubLayer
    $bad2 = Get-Nep5OurPlan -Id 'o1'; $bad2.Filters[0].UserSid = $sidO
    $bad3 = Get-Nep5OurPlan -Id 'o1'; $bad3.Filters[0].UserSid = $null
    $bad4 = Get-Nep5OurPlan -Id 'o1'; $bad4.Filters[0].SubLayer = $script:N5MissingSubLayer
    $bad5 = Get-Nep5OurPlan -Id 'o1'; $bad5.Filters[0].Name = 'nobody'
    Chk 'plan gate: a foreign sublayer, the operator''s SID, a block with no user condition, the missing sublayer outside an attempt, and a name without the marker are each refused' (((Get-Nep5PlanProblems -Plan $bad1).Count -ge 1) -and ((Get-Nep5PlanProblems -Plan $bad2).Count -ge 1) -and ((Get-Nep5PlanProblems -Plan $bad3).Count -ge 1) -and ((Get-Nep5PlanProblems -Plan $bad4).Count -ge 1) -and ((Get-Nep5PlanProblems -Plan $bad5).Count -ge 1)) 'sublayer-allowlist'

    Write-Host '== the direct sweep and removal against the fake machine ==' -ForegroundColor Cyan
    $ctx = New-N5TestCtx
    try {
        $w = $ctx.World; $sweep = { param($c = $ctx, $label = 'x', $allowed = $null) Invoke-Nep5DirectSweep -Runner $c.Runner -Backend $c.Backend -Exporter $c.Exporter -Label $label -AllowedSubLayers $allowed }
        $sw0 = & $sweep
        Chk 'sweep: an empty machine reads CLEAN (every sublayer enumerates zero and is absent, provider absent, export 0 hits)' ($sw0.Clean -and -not $sw0.Stop -and -not $sw0.Unreadable -and $sw0.Export.hits.total -eq 0) 'absent-detected'
        $w.SubLayers[$s2] = ''
        Chk 'sweep: a sublayer that is present but empty is NOT clean (enumerating zero filters is not the proof)' ((-not (& $sweep).Clean) -and (@((& $sweep).NotClean) -match 'S2 sublayer is still present').Count -eq 1)
        $w.SubLayers.Clear(); $w.Providers[(ConvertTo-N5Guid $script:N5ProviderKey)] = $true
        Chk 'sweep: a provider left behind is NOT clean' ((-not (& $sweep).Clean) -and (@((& $sweep).NotClean) -match 'provider').Count -ge 1)
        $w.Providers.Clear()
        $ctx.Exporter = New-Nep5FakeExporter -World $w -Extra '<x>BlarAI #1763 leftover</x>'
        $swx = & $sweep
        Chk 'sweep: an export hit with nothing enumerated (the export is an independent read) is NOT clean' ((-not $swx.Clean) -and (@($swx.NotClean) -match 'export has 1 hit').Count -ge 1)
        $ctx.Exporter = New-Nep5FakeExporter -World $w -Extra '<x>srt-win-v4-block-user</x>'
        Chk 'sweep: a hit for srt-win''s filter names alone is NOT clean (our marker alone would read 0 for srt-win filters)' (-not (& $sweep).Clean)
        $ctx.Exporter = New-Nep5FakeExporter -World $w -Extra "<g>{$($s3.ToUpperInvariant())}</g>"
        Chk 'sweep: a hit for a sublayer GUID (upper case, braces) alone is NOT clean' (-not (& $sweep).Clean)
        $ctx.Exporter = New-Nep5FakeExporter -World $w
        $w.Filters['aaaaaaaa-0000-4d8e-9a31-2b6d4c8e0001'] = [pscustomobject]@{ Key = 'aaaaaaaa-0000-4d8e-9a31-2b6d4c8e0001'; SubLayer = '11111111-2222-3333-4444-555555555555'; Layer = 'v4'; Name = 'srt-win-v4-block-user'; Kind = 'block-user'; Tool = 'srt-win'; Sid = $sidS; HasUser = $true; Action = 'block' }
        $swf = & $sweep
        Chk 'sweep: an srt-win filter under an UNLISTED sublayer is a STOP (not a cleanup), named in the problems' ($swf.Stop -and -not $swf.Clean -and (@($swf.Problems) -match 'STOP').Count -eq 1) 'sweep-finds-foreign-sublayer'
        $swfOff = & $sweep $ctx 'x' @('11111111-2222-3333-4444-555555555555')
        Chk 'sweep (stop detector OFF: allowlist widened to the foreign sublayer): the same filter no longer stops the sweep, so the stop above is the detector' (-not $swfOff.Stop) 'sweep-finds-foreign-sublayer'
        $w.Filters.Clear()
        $w.Filters['bbbbbbbb-0000-4d8e-9a31-2b6d4c8e0001'] = [pscustomobject]@{ Key = 'bbbbbbbb-0000-4d8e-9a31-2b6d4c8e0001'; SubLayer = $script:N5OldArm3SubLayer; Layer = 'v4'; Name = 'BlarAI #1763 s2-block-v4'; Kind = ''; Tool = ''; Sid = $sidS; HasUser = $true; Action = 'block' }
        Chk 'sweep: a filter of ours under the OLD arm 3 sublayer is a STOP too' ((& $sweep).Stop) 'sweep-finds-foreign-sublayer'
        $w.Filters.Clear()
        $ctxU = New-N5TestCtx
        try {
            $unr = { param($c, $label) Invoke-Nep5DirectSweep -Runner $c.Runner -Backend $c.Backend -Exporter $c.Exporter -Label $label }
            $c1 = $ctxU; $c1.Runner = New-FakeHalfset -World $c1.World -Unreadable $true
            $c2 = New-N5TestCtx; $c2.Runner = New-FakeHalfset -World $c2.World -GarbageEnum $true
            $c3 = New-N5TestCtx; $c3.Backend = New-Nep5FakeBackend -World $c3.World -Unreadable $true
            $c4 = New-N5TestCtx; $c4.Exporter = New-Nep5FakeExporter -World $c4.World -Fail $true
            $r1 = & $unr $c1 'u1'; $r2 = & $unr $c2 'u2'; $r3 = & $unr $c3 'u3'; $r4 = & $unr $c4 'u4'
            Chk 'sweep: a harness that cannot read (exit 6), one that prints garbage, an engine that cannot be read and an export that fails are each UNREADABLE and never clean' ($r1.Unreadable -and -not $r1.Clean -and $r2.Unreadable -and -not $r2.Clean -and $r3.Unreadable -and -not $r3.Clean -and $r4.Unreadable -and -not $r4.Clean) 'unknown-detected'
            $c5 = New-N5TestCtx; $c5.World.SubLayers[$s2] = ''
            try {
                $rNo = Invoke-Nep5DirectSweep -Runner $null -Backend $c5.Backend -Exporter $c5.Exporter -Label 'n' -NoHarness
                Chk 'sweep (no harness): -NoHarness reads sublayers and the provider by key only, records that enumeration was skipped, and a present sublayer is NOT clean' (($rNo.SubLayers.S2.present -eq $true) -and ($rNo.SubLayers.S2.enum_skipped -eq $true) -and (-not $rNo.Clean) -and (-not $rNo.Unreadable))
            } finally { Remove-Item -LiteralPath $c5.Tmp -Recurse -Force -ErrorAction SilentlyContinue }
        } finally { foreach ($c in @($ctxU, $c2, $c3, $c4)) { if ($c -and $c.Tmp) { Remove-Item -LiteralPath $c.Tmp -Recurse -Force -ErrorAction SilentlyContinue } } }
    } finally { Remove-Item -LiteralPath $ctx.Tmp -Recurse -Force -ErrorAction SilentlyContinue }

    Write-Host '== removal by key against the fake machine ==' -ForegroundColor Cyan
    $c = New-N5TestCtx
    try {
        $w = $c.World
        $null = & $c.Runner @('install', '--sublayer', $s1, '--sid', $sidS, '--live', 'x'); [void]$c.Backend.AddSet((Get-Nep5OurPlan -Id 'o4')); $w.SubLayers[$s3] = ''
        $nBefore = $w.Filters.Count
        $rm = Remove-Nep5All -Runner $c.Runner -Backend $c.Backend
        $stp = @($rm.Steps); $lastF = ($stp | ForEach-Object { $_.step }).LastIndexOf('filter'); $firstS = ($stp | ForEach-Object { $_.step }).IndexOf('sublayer'); $provI = ($stp | ForEach-Object { $_.step }).IndexOf('provider')
        Chk 'remove (srt-win''s four S1 filters, our provider, S2 with three filters, S3): Ok, nothing left in the fake machine, no error, filters then sublayers then the provider' (($nBefore -eq 7) -and $rm.Ok -and $w.Filters.Count -eq 0 -and $w.SubLayers.Count -eq 0 -and $w.Providers.Count -eq 0 -and $rm.Errors.Count -eq 0 -and ($lastF -lt $firstS) -and ($firstS -lt $provI)) 'remove-full-set'
        $sw = Invoke-Nep5DirectSweep -Runner $c.Runner -Backend $c.Backend -Exporter $c.Exporter -Label 'after'
        Chk 'removal proof: after the removal the DIRECT checks read clean (each sublayer zero filters and absent, provider absent, export 0 hits)' ($sw.Clean) 'removal-direct-proof'
        $c.Exporter = New-Nep5FakeExporter -World $w -Extra '<leftover>{3E29AE7E-FD9F-413A-8B8D-DA9BD3A96360}</leftover>'
        $rm2 = Remove-Nep5All -Runner $c.Runner -Backend $c.Backend; $sw2 = Invoke-Nep5DirectSweep -Runner $c.Runner -Backend $c.Backend -Exporter $c.Exporter -Label 'after2'
        Chk 'removal proof: the remover reading Ok is NOT the proof: an export that still shows the provider GUID makes the direct checks fail even though the remover''s own re-read is empty' ($rm2.Ok -and -not $sw2.Clean) 'removal-direct-proof'
    } finally { Remove-Item -LiteralPath $c.Tmp -Recurse -Force -ErrorAction SilentlyContinue }
    $c = New-N5TestCtx
    try {
        $w = $c.World; $be = New-Nep5FakeBackend -World $w -FailAddAfter 3; try { [void]$be.AddSet((Get-Nep5OurPlan -Id 'o4')) } catch {}
        $nHalf = ($w.Providers.Count + $w.SubLayers.Count + $w.Filters.Count)
        $rm = Remove-Nep5All -Runner $c.Runner -Backend $c.Backend
        Chk 'remove (half-failed add: provider, sublayer, one filter): Ok, the filters that never existed are reported as not_found, not as errors' (($nHalf -eq 3) -and $rm.Ok -and $rm.Errors.Count -eq 0 -and (@($rm.Steps | Where-Object { $_.status -eq 'not_found' }).Count -ge 2)) 'remove-half-failed-add'
        $rm3 = Remove-Nep5All -Runner $c.Runner -Backend $c.Backend
        Chk 'remove (nothing there): Ok, every key not_found or deleted-by-harness-noop, no error (idempotent)' ($rm3.Ok -and $rm3.Errors.Count -eq 0 -and @($rm3.Steps | Where-Object { $_.step -eq 'filter' -and $_.via -eq 'engine-fixed-key' -and $_.status -eq 'not_found' }).Count -eq $script:N5FilterKeys.Count) 'remove-when-absent'
    } finally { Remove-Item -LiteralPath $c.Tmp -Recurse -Force -ErrorAction SilentlyContinue }
    $c = New-N5TestCtx
    try {
        $w = $c.World; $null = & $c.Runner @('install', '--sublayer', $s1, '--sid', $sidS, '--live', 'x'); [void]$c.Backend.AddSet((Get-Nep5OurPlan -Id 'o1'))
        $stuck = @($w.Filters.Keys | Where-Object { $w.Filters[$_].Tool -eq 'srt-win' })[0]
        $c.Runner = New-FakeHalfset -World $w -FailDeleteFilter @($stuck); $c.Backend = New-Nep5FakeBackend -World $w -FailDelete @($stuck)
        $rm = Remove-Nep5All -Runner $c.Runner -Backend $c.Backend
        Chk 'remove (one filter cannot be deleted by the harness NOR the engine): Ok is FALSE, the failing key is named, and the direct re-read still shows it' ((-not $rm.Ok) -and (@($rm.Errors | Where-Object { $_.key -eq $stuck }).Count -ge 1) -and $w.Filters.Count -eq 1 -and $w.Filters.ContainsKey($stuck)) 'remove-reports-delete-error'
        Chk 'remove (one delete fails): every OTHER key was still tried and deleted (our filter, the sublayers, the provider)' (@($c.Backend.Calls | Where-Object { $_ -like 'delete provider *' }).Count -eq 1 -and (-not $w.Filters.ContainsKey($script:N5FilterKeys['s2-block-v4'])) -and $w.Providers.Count -eq 0 -and @($c.Backend.Calls | Where-Object { $_ -like 'delete sublayer *' }).Count -ge 1) 'remove-continues-after-error'
    } finally { Remove-Item -LiteralPath $c.Tmp -Recurse -Force -ErrorAction SilentlyContinue }
    $c = New-N5TestCtx
    try {
        $w = $c.World; $null = & $c.Runner @('install', '--sublayer', $s1, '--sid', $sidS, '--live', 'x'); $stuck = @($w.Filters.Keys)[0]
        $c.Runner = New-FakeHalfset -World $w -FailDeleteFilter @($stuck)
        $rm = Remove-Nep5All -Runner $c.Runner -Backend $c.Backend
        Chk 'remove (the harness fails one delete but our own engine succeeds): Ok, and the step says which path did it' ($rm.Ok -and @($rm.Steps | Where-Object { $_.key -eq $stuck -and $_.via -like 'harness-failed*engine' -and $_.status -eq 'deleted' }).Count -eq 1)
    } finally { Remove-Item -LiteralPath $c.Tmp -Recurse -Force -ErrorAction SilentlyContinue }
    $c = New-N5TestCtx
    try {
        $w = $c.World; $null = & $c.Runner @('install', '--sublayer', $s1, '--sid', $sidS, '--live', 'x')
        $fk = 'cccccccc-0000-4d8e-9a31-2b6d4c8e0001'; $w.Filters[$fk] = [pscustomobject]@{ Key = $fk; SubLayer = '11111111-2222-3333-4444-555555555555'; Layer = 'v4'; Name = 'srt-win-v4-block-user'; Kind = 'block-user'; Tool = 'srt-win'; Sid = $sidS; HasUser = $true; Action = 'block' }
        $rm = Remove-Nep5All -Runner $c.Runner -Backend $c.Backend
        Chk 'remove: a filter outside S1/S2/S3 is NEVER deleted (the harness refuses with exit 9, our engine is never asked for its key), the rest is removed, and Ok is false' ((-not $rm.Ok) -and $w.Filters.ContainsKey($fk) -and $w.Filters.Count -eq 1 -and @($c.Backend.Calls | Where-Object { $_ -like "delete filter $fk" }).Count -eq 0 -and $rm.After.Foreign.Count -eq 1) 'sweep-finds-foreign-sublayer'
    } finally { Remove-Item -LiteralPath $c.Tmp -Recurse -Force -ErrorAction SilentlyContinue }
    $c = New-N5TestCtx
    try {
        $w = $c.World; [void]$c.Backend.AddSet((Get-Nep5OurPlan -Id 'o1'))
        $c.Runner = { param([string[]]$Argv) throw 'harness gone' }
        $rm = Remove-Nep5All -Runner $c.Runner -Backend $c.Backend
        Chk 'remove (the harness is gone entirely): our own engine still deletes our fixed filter keys, the sublayers and the provider; Ok is FALSE because the re-read is unreadable' ((-not $rm.Ok) -and $w.Filters.Count -eq 0 -and $w.SubLayers.Count -eq 0 -and $w.Providers.Count -eq 0) 'unknown-detected'
    } finally { Remove-Item -LiteralPath $c.Tmp -Recurse -Force -ErrorAction SilentlyContinue }

    Write-Host '== the add paths: proof gate, SID gate, sublayer gate, stale gate, rollback by key ==' -ForegroundColor Cyan
    $c = New-N5TestCtx
    try {
        $w = $c.World; $good = $c.Proof; $sp0 = @(& $c.SidProblemsFor $sidS)
        $forgeries = @($null, [pscustomobject]@{ Kind = 'Nep5Proof'; Ok = $false; Nonce = 'selftest-nonce' }, [pscustomobject]@{ Ok = $true }, 'yes', [pscustomobject]@{ Kind = 'Nep5Proof'; Ok = $true; Nonce = 'forged' }, [pscustomobject]@{ Kind = 'Nep5Proof'; Ok = $true }, [pscustomobject]@{ Kind = 'RollbackProof'; Ok = $true; Nonce = 'selftest-nonce' })
        $okRefused = $true; foreach ($fp in $forgeries) { $a = Add-Nep5OurPlan -Runner $c.Runner -Backend $c.Backend -Plan (Get-Nep5OurPlan -Id 'o1') -SidProblems $sp0 -Proof $fp; $b = Add-Nep5SrtWinSet -Runner $c.Runner -Backend $c.Backend -SubLayer $s1 -Sid $sidS -SidProblems $sp0 -Proof $fp; if (-not ($a.Refused -and $b.Refused)) { $okRefused = $false } }
        Chk 'add: with no proof, a failed proof, a token of the wrong kind, a bare string, a hand-made token with a wrong or no nonce, or another arm''s token, BOTH add paths refuse; AddSet is never called, install never reaches the harness, nothing is added' ($okRefused -and @($c.Backend.Calls | Where-Object { $_ -like 'addset*' -or $_ -like 'addone*' }).Count -eq 0 -and @($c.Runner.State.Calls | Where-Object { $_ -like 'install*' }).Count -eq 0 -and $w.Filters.Count -eq 0) 'add-refused-without-proof'
        Chk 'add: a hand-made object with Kind and Ok = true but without this process''s nonce is refused (a token cannot be forged by copying its fields)' ((-not (Test-N5ProofToken ([pscustomobject]@{ Kind = 'Nep5Proof'; Ok = $true; Nonce = 'guess' }))) -and (-not (Test-N5ProofToken ([pscustomobject]@{ Kind = 'Nep5Proof'; Ok = $true }))) -and (Test-N5ProofToken $good)) 'forged-proof-refused'
        $off = Add-Nep5OurPlan -Runner $c.Runner -Backend $c.Backend -Plan (Get-Nep5OurPlan -Id 'o1') -SidProblems $sp0 -Proof $null -ProofValidator { param($p) $true }
        Chk 'add (proof gate OFF: validator switched to accept anything): the same call with NO proof now adds, so the refusals above are the gate' ($off.Ok -and $w.Filters.Count -eq 1) 'add-refused-without-proof'
        $null = Remove-Nep5All -Runner $c.Runner -Backend $c.Backend
        $a1 = Add-Nep5OurPlan -Runner $c.Runner -Backend $c.Backend -Plan (Get-Nep5OurPlan -Id 'o4') -SidProblems $sp0 -Proof $good
        $a1n = $w.Filters.Count
        Chk 'add: with a valid token and an empty machine our four-object set (provider, sublayer, three filters) is added, read back persistent' ($a1.Ok -and $a1.Added -and $a1n -eq 3 -and $w.SubLayers.Count -eq 1 -and $w.Providers.Count -eq 1)
        $callsN = $c.Backend.Calls.Count
        $a2 = Add-Nep5OurPlan -Runner $c.Runner -Backend $c.Backend -Plan (Get-Nep5OurPlan -Id 'o4') -SidProblems $sp0 -Proof $good
        Chk 'add: refused over stale objects of the same plan (nothing added, nothing deleted)' ($a2.Refused -and $a2.Reason -match 'already exists' -and $w.Filters.Count -eq 3 -and @($c.Backend.Calls | Select-Object -Skip $callsN | Where-Object { $_ -like 'delete*' -or $_ -like 'addset*' }).Count -eq 0) 'add-refused-over-stale-objects'
        $null = Remove-Nep5All -Runner $c.Runner -Backend $c.Backend
        $w.Filters['dddddddd-0000-4d8e-9a31-2b6d4c8e0001'] = [pscustomobject]@{ Key = 'dddddddd-0000-4d8e-9a31-2b6d4c8e0001'; SubLayer = $s1; Layer = 'v4'; Name = 'srt-win-v4-block-user'; Kind = 'block-user'; Tool = 'srt-win'; Sid = $sidS; HasUser = $true; Action = 'block' }
        $a3 = Add-Nep5SrtWinSet -Runner $c.Runner -Backend $c.Backend -SubLayer $s1 -Sid $sidS -SidProblems $sp0 -Proof $good
        Chk 'add (srt-win): refused over a sublayer that already holds a filter (install_filters would delete every srt-win-tagged filter in it); install never reaches the harness' ($a3.Refused -and @($c.Runner.State.Calls | Where-Object { $_ -like 'install*' }).Count -eq 0) 'add-refused-over-stale-objects'
        $w.Filters.Clear()
        $cu = New-N5TestCtx; $cu.Backend = New-Nep5FakeBackend -World $cu.World -Unreadable $true
        try { $a4 = Add-Nep5OurPlan -Runner $cu.Runner -Backend $cu.Backend -Plan (Get-Nep5OurPlan -Id 'o1') -SidProblems $sp0 -Proof $cu.Proof; $a5 = Add-Nep5SrtWinSet -Runner $cu.Runner -Backend $cu.Backend -SubLayer $s1 -Sid $sidS -SidProblems $sp0 -Proof $cu.Proof
            Chk 'add: refused when the engine cannot be read (state UNKNOWN), both paths, nothing added' ($a4.Refused -and $a5.Refused -and $cu.World.Filters.Count -eq 0) 'unknown-detected' } finally { Remove-Item -LiteralPath $cu.Tmp -Recurse -Force -ErrorAction SilentlyContinue }
        # SID gate and plan gate: two independent locks
        $spOp = @(& $c.SidProblemsFor $sidO)
        $planOp = Get-Nep5OurPlan -Id 'o1' -Sid $sidO
        $r1 = Add-Nep5OurPlan -Runner $c.Runner -Backend $c.Backend -Plan (Get-Nep5OurPlan -Id 'o1') -SidProblems $spOp -Proof $good
        $r2 = Add-Nep5OurPlan -Runner $c.Runner -Backend $c.Backend -Plan $planOp -SidProblems @() -Proof $good
        Chk 'add: with the operator''s SID the SID gate alone refuses (plan built for the test account), and the plan gate alone refuses (SID verdict empty): two independent locks; nothing is added' ($r1.Refused -and $r1.Reason -match 'SID not safe' -and $r2.Refused -and $r2.Reason -match 'plan refused' -and $w.Filters.Count -eq 0) 'operator-sid-refused'
        $r3 = Add-Nep5OurPlan -Runner $c.Runner -Backend $c.Backend -Plan $planOp -SidProblems @() -Proof $good -PlanGate { param($p) @() }
        Chk 'add (SID gate AND plan gate OFF): the operator''s SID IS added to the fake machine, so the refusals above are those two locks' ($r3.Ok -and $w.Filters.Count -eq 1 -and $w.Filters.Values[0].Sid -eq $sidO) 'operator-sid-refused'
        $null = Remove-Nep5All -Runner $c.Runner -Backend $c.Backend
        $r4 = Add-Nep5SrtWinSet -Runner $c.Runner -Backend $c.Backend -SubLayer $s1 -Sid $sidO -SidProblems $spOp -Proof $good
        Chk 'add (srt-win): with the operator''s SID verdict the install is refused before the harness is asked' ($r4.Refused -and @($c.Runner.State.Calls | Where-Object { $_ -like 'install*' }).Count -eq 0) 'operator-sid-refused'
        $r5 = Add-Nep5SrtWinSet -Runner $c.Runner -Backend $c.Backend -SubLayer $script:N5SrtDefaultSubLayer -Sid $sidS -SidProblems $sp0 -Proof $good
        $callsBefore = @($c.Runner.State.Calls).Count
        $r6 = Add-Nep5SrtWinSet -Runner $c.Runner -Backend $c.Backend -SubLayer $script:N5SrtDefaultSubLayer -Sid $sidS -SidProblems $sp0 -Proof $good -SublayerGate { param($s) $true }
        Chk 'add (srt-win): srt-win''s default sublayer is refused by the sublayer gate; with that gate OFF the harness-argument allowlist still refuses it before the harness runs (a second lock); nothing is added' ($r5.Refused -and $r6.Ok -eq $false -and @($c.Runner.State.Calls | Where-Object { $_ -like 'install*' }).Count -eq 0 -and $w.Filters.Count -eq 0 -and $w.SubLayers.Count -eq 0) 'sublayer-allowlist'
        $ok = Add-Nep5SrtWinSet -Runner $c.Runner -Backend $c.Backend -SubLayer $s1 -Sid $sidS -SidProblems $sp0 -Proof $good
        $st = Invoke-Halfset -Runner $c.Runner -Argv @('status', '--sublayer', $s1)
        Chk 'add (srt-win): with a valid token and an empty machine the harness installs the full set in S1 and srt-win''s status reads installed' ($ok.Ok -and $w.Filters.Count -eq 4 -and (Get-SrtStatusWord $st.Json) -eq 'installed')
        $null = Remove-Nep5All -Runner $c.Runner -Backend $c.Backend
        # rollback by key
        $cf = New-N5TestCtx; $cf.Backend = New-Nep5FakeBackend -World $cf.World -FailAddAfter 2
        try { $f1 = Add-Nep5OurPlan -Runner $cf.Runner -Backend $cf.Backend -Plan (Get-Nep5OurPlan -Id 'o4') -SidProblems $sp0 -Proof $cf.Proof
            Chk 'add: a half-failed add (provider, sublayer, then an error) is rolled back by key to an empty machine and reported as not added' ((-not $f1.Ok) -and (-not $f1.Added) -and $f1.Rollback.Ok -and $cf.World.Filters.Count -eq 0 -and $cf.World.SubLayers.Count -eq 0 -and $cf.World.Providers.Count -eq 0 -and $f1.Reason -match 'rolled back') 'add-failure-rolls-back' } finally { Remove-Item -LiteralPath $cf.Tmp -Recurse -Force -ErrorAction SilentlyContinue }
        $cn = New-N5TestCtx; $cn.Backend = New-Nep5FakeBackend -World $cn.World -AddClearsFlags $true
        try { $f2 = Add-Nep5OurPlan -Runner $cn.Runner -Backend $cn.Backend -Plan (Get-Nep5OurPlan -Id 'o4') -SidProblems $sp0 -Proof $cn.Proof
            Chk 'add: an add that "succeeds" without the persistent flag is rolled back (a non-persistent filter would vanish with the engine session)' ((-not $f2.Ok) -and $f2.Rollback.Ok -and $cn.World.Filters.Count -eq 0) 'add-failure-rolls-back' } finally { Remove-Item -LiteralPath $cn.Tmp -Recurse -Force -ErrorAction SilentlyContinue }
        $cm = New-N5TestCtx; $cm.Backend = New-Nep5FakeBackend -World $cm.World -RefuseAttempt $false
        try { $f3 = Add-Nep5OurPlan -Runner $cm.Runner -Backend $cm.Backend -Plan (Get-Nep5OurPlan -Id 'o6') -SidProblems $sp0 -Proof $cm.Proof
            Chk 'add: an attempt naming the missing sublayer that the engine ACCEPTS is deleted at once, flagged STOP, and the machine is back to empty' ((-not $f3.Ok) -and $f3.Stop -and $f3.Attempts[0].deleted_at_once -and $cm.World.Filters.Count -eq 0) 'add-failure-rolls-back' } finally { Remove-Item -LiteralPath $cm.Tmp -Recurse -Force -ErrorAction SilentlyContinue }
        $co = New-N5TestCtx
        try {
            $f4 = Add-Nep5OurPlan -Runner $co.Runner -Backend $co.Backend -Plan (Get-Nep5OurPlan -Id 'o5') -SidProblems $sp0 -Proof $co.Proof
            $f5 = Add-Nep5OurPlan -Runner $co.Runner -Backend $co.Backend -Plan (Get-Nep5OurPlan -Id 'o6') -SidProblems $sp0 -Proof $co.Proof
            Chk 'add: a block with no provider in a sublayer that has one, and a filter naming a missing sublayer, are ATTEMPTED; the engine''s refusal text is the recorded result and the set around them stays whole' ($f4.Ok -and $f4.Attempts[0].status -like 'error*0x8032002F' -and $f5.Ok -and $f5.Attempts[0].status -like 'error*0x80320007' -and $co.World.Filters.Count -eq 0 -and $co.World.SubLayers.Count -eq 1)
        } finally { Remove-Item -LiteralPath $co.Tmp -Recurse -Force -ErrorAction SilentlyContinue }
        foreach ($sw in @(@{ n = 'install fails (exit 10)'; r = (New-FakeHalfset -World $w -FailInstall $true) }, @{ n = 'read-back mismatch after filters were added (exit 8)'; r = (New-FakeHalfset -World $w -NoReadback $true) }, @{ n = 'engine denied (exit 7)'; r = (New-FakeHalfset -World $w -Denied $true) })) {
            $fr = Add-Nep5SrtWinSet -Runner $sw.r -Backend $c.Backend -SubLayer $s1 -Sid $sidS -SidProblems $sp0 -Proof $good
            Chk "add (srt-win): $($sw.n): not added, rolled back by key, the machine is empty again" ((-not $fr.Ok) -and $w.Filters.Count -eq 0 -and $w.SubLayers.Count -eq 0) 'harness-add-failure-rolls-back'
        }
    } finally { Remove-Item -LiteralPath $c.Tmp -Recurse -Force -ErrorAction SilentlyContinue }

    Write-Host '== the harness arming interlock (--live) and the pre-existing set left in S1 ==' -ForegroundColor Cyan
    $c = New-N5TestCtx
    try {
        $w = $c.World; $live = $script:N5LiveProof
        $null = Invoke-Halfset -Runner $c.Runner -Argv @('status', '--sublayer', $s1); $null = Invoke-Halfset -Runner $c.Runner -Argv @('enum', '--sublayer', $s1); $null = Invoke-Halfset -Runner $c.Runner -Argv @('enum', '--all-ours')
        $null = Invoke-Halfset -Runner $c.Runner -Argv @('install', '--sublayer', $s1, '--sid', $sidS)
        $kk = @($w.Filters.Keys)[0]
        $null = Invoke-Halfset -Runner $c.Runner -Argv @('delete-filter', '--sublayer', $s1, '--key', $kk); $null = Invoke-Halfset -Runner $c.Runner -Argv @('uninstall', '--sublayer', $s1); $null = Invoke-Halfset -Runner $c.Runner -Argv @('delete-sublayer', '--sublayer', $s1)
        $cl = @($c.Runner.State.Calls)
        Chk 'arming: --live <the harness proof> is appended to install, delete-filter, uninstall and delete-sublayer, and to status and enum (every form) it is NOT' ((@($cl | Where-Object { $_ -match '^(status|enum)' -and $_ -match '--live' }).Count -eq 0) -and (@($cl | Where-Object { $_ -match '^(install|delete-filter|uninstall|delete-sublayer) ' -and $_.EndsWith("--live $live") }).Count -eq 4)) 'harness-arming'
        $script:N5LiveProof = $null
        $ia = Invoke-Halfset -Runner $c.Runner -Argv @('install', '--sublayer', $s1, '--sid', $sidS)
        $da = Invoke-Halfset -Runner $c.Runner -Argv @('uninstall', '--sublayer', $s1)
        Chk 'arming (lock on): with no harness proof configured every mutating verb exits 12 (not_armed) before anything changes, and the failure class says so' (($ia.ExitCode -eq 12) -and ($ia.Outcome -eq 'not_armed') -and ($da.ExitCode -eq 12) -and ((Get-HarnessFailureClass $ia) -eq 'not_armed') -and ((Get-HarnessFailureClass ([pscustomobject]@{ Refused = $false; ExitCode = 13 })) -eq 'trace_failed') -and $w.Filters.Count -eq 0) 'harness-arming'
        $script:N5LiveProof = $live
        $callerLive = @((Test-HalfsetArgv -Argv @('enum', '--sublayer', $s1, '--live', 'x')), (Test-HalfsetArgv -Argv @('install', '--sublayer', $s1, '--sid', $sidS, '--live', 'C:\somewhere\else.json')), (Test-HalfsetArgv -Argv @('status', '--sublayer', $s1, '--live', 'x')))
        $direct12 = & $c.Runner @('enum', '--sublayer', $s1, '--live', 'x'); $directSt = & $c.Runner @('status', '--sublayer', $s1, '--live', 'x')
        Chk 'arming: a caller cannot supply its own --live (the vector validator refuses it for every verb), and the harness rejects --live on enum and status (exit 2)' ((@($callerLive | Where-Object { $_.Ok }).Count -eq 0) -and $direct12.ExitCode -eq 2 -and $directSt.ExitCode -eq 2) 'harness-arming'
        $cNa = New-N5TestCtx; $cNa.Runner = New-FakeHalfset -World $cNa.World -NotArmed $true
        try { $na = Add-Nep5SrtWinSet -Runner $cNa.Runner -Backend $cNa.Backend -SubLayer $s1 -Sid $sidS -SidProblems @() -Proof $cNa.Proof
            Chk 'arming: a harness that answers 12 (proof stale or edited) makes the srt-win add fail and roll back: the machine stays empty' ((-not $na.Ok) -and $cNa.World.Filters.Count -eq 0 -and $na.Install.ExitCode -eq 12) 'harness-arming' } finally { Remove-Item -LiteralPath $cNa.Tmp -Recurse -Force -ErrorAction SilentlyContinue }
        $hl = New-N5HarnessLiveProof -ExeSha ('AB' * 32) -RsSha ('CD' * 32) -Now ([datetime]'2026-10-12T19:00:00-04:00')
        Chk 'harness proof object: schema nep5-1763-proof-v1, lower-case hashes, checks_failed the integer 0, written_utc in UTC with a Z' (($hl.schema -ceq 'nep5-1763-proof-v1') -and ($hl.halfset_exe_sha256 -ceq ('ab' * 32)) -and ($hl.halfset_rs_sha256 -ceq ('cd' * 32)) -and ($hl.checks_failed -is [int]) -and ($hl.checks_failed -eq 0) -and ($hl.written_utc -ceq '2026-10-12T23:00:00Z'))
    } finally { $script:N5LiveProof = 'C:\fake\harness-live-proof-1763.json'; Remove-Item -LiteralPath $c.Tmp -Recurse -Force -ErrorAction SilentlyContinue }
    $hpDir = Join-Path ([IO.Path]::GetTempPath()) ('nep5-hp-' + [guid]::NewGuid().ToString('N')); New-Item -ItemType Directory -Path $hpDir | Out-Null
    try {
        $hpp = Join-Path $hpDir 'p.json'; $eS = ('ab' * 32); $rS = ('cd' * 32)
        $wr = { param($o) [IO.File]::WriteAllText($hpp, (ConvertTo-Json -InputObject $o)) }
        & $wr (New-N5HarnessLiveProof -ExeSha $eS -RsSha $rS)
        $okP = @(Test-N5HarnessLiveProof -Path $hpp -ExeSha $eS -RsSha $rS)
        $bad = @{}
        & $wr (New-N5HarnessLiveProof -ExeSha ('ee' * 32) -RsSha $rS); $bad.exe = @(Test-N5HarnessLiveProof -Path $hpp -ExeSha $eS -RsSha $rS)
        & $wr (New-N5HarnessLiveProof -ExeSha $eS -RsSha ('ee' * 32)); $bad.rs = @(Test-N5HarnessLiveProof -Path $hpp -ExeSha $eS -RsSha $rS)
        & $wr (New-N5HarnessLiveProof -ExeSha $eS -RsSha $rS -ChecksFailed 1); $bad.failed = @(Test-N5HarnessLiveProof -Path $hpp -ExeSha $eS -RsSha $rS)
        & $wr (New-N5HarnessLiveProof -ExeSha $eS -RsSha $rS -Now (Get-Date).AddHours(-25)); $bad.old = @(Test-N5HarnessLiveProof -Path $hpp -ExeSha $eS -RsSha $rS)
        & $wr (New-N5HarnessLiveProof -ExeSha $eS -RsSha $rS -Now (Get-Date).AddHours(2)); $bad.future = @(Test-N5HarnessLiveProof -Path $hpp -ExeSha $eS -RsSha $rS)
        $o = New-N5HarnessLiveProof -ExeSha $eS -RsSha $rS; $o.schema = 'other'; & $wr $o; $bad.schema = @(Test-N5HarnessLiveProof -Path $hpp -ExeSha $eS -RsSha $rS)
        $o = New-N5HarnessLiveProof -ExeSha $eS -RsSha $rS; $o.checks_failed = '0'; & $wr $o; $bad.str0 = @(Test-N5HarnessLiveProof -Path $hpp -ExeSha $eS -RsSha $rS)
        [IO.File]::WriteAllText($hpp, '{not json'); $bad.json = @(Test-N5HarnessLiveProof -Path $hpp -ExeSha $eS -RsSha $rS)
        $bad.missing = @(Test-N5HarnessLiveProof -Path (Join-Path $hpDir 'nope.json') -ExeSha $eS -RsSha $rS)
        $slack = @($bad.Keys | Where-Object { $bad[$_].Count -eq 0 })
        Chk "harness proof file: a matching fresh proof is accepted; each of these is refused: wrong exe hash, wrong halfset.rs hash, checks_failed 1, 25 h old, dated in the future, wrong schema, checks_failed as a string, not JSON, missing $(if ($slack.Count) { '(NOT refused: ' + ($slack -join ', ') + ')' })" (($okP.Count -eq 0) -and ($slack.Count -eq 0)) 'harness-live-proof-binding'
    } finally { Remove-Item -LiteralPath $hpDir -Recurse -Force -ErrorAction SilentlyContinue }
    $mkS1Leftover = { param($c, $sid) $null = & $c.Runner @('install', '--sublayer', $s1, '--sid', $sid, '--live', 'x') }
    $c = New-N5TestCtx
    try {
        & $mkS1Leftover $c $sidS; $w = $c.World; $c.Only = @('R0')
        $swL = Invoke-Nep5DirectSweep -Runner $c.Runner -Backend $c.Backend -Exporter $c.Exporter -Label 'check'
        Chk 'pre-existing set (as a reviewer probe left it): the sweep that -Check runs reads it as NOT clean, the S1 sublayer present with four filters, and -Check''s exit code is 21' ((-not $swL.Clean) -and $swL.SubLayers.S1.filter_keys.Count -eq 4 -and $swL.SubLayers.S1.present -and ((Get-Nep5CheckExit -Sweep ([pscustomobject]$swL) -TaskState 'original') -eq 21))
        $r = Invoke-Nep5Phase -Ctx $c -Phase 'halfset'
        $uc = @($c.Runner.State.Calls | Where-Object { $_ -like 'uninstall*' })
        Chk 'pre-cleanup: the first live action removes that set with the harness uninstall (armed with --live) and reads S1 ABSENT by the direct checks; the phase then runs and finishes clean' (($r.ExitCode -eq 0) -and $uc.Count -eq 1 -and $uc[0] -like "uninstall --sublayer $s1 --live *" -and $r.Records[0].state -eq 'R0' -and $r.Records[0].class -eq 'ok' -and ($w.Filters.Count + $w.SubLayers.Count + $w.Providers.Count) -eq 0) 'pre-cleanup'
        Chk 'pre-cleanup: the record says what was removed and the sweep before and after' (($null -ne (Get-Content $r.ResultsPath -Raw | ConvertFrom-Json).pre_cleanup) -and ((Get-Content $r.ResultsPath -Raw | ConvertFrom-Json).pre_cleanup.Class -eq 'ok'))
    } finally { Remove-Item -LiteralPath $c.Tmp -Recurse -Force -ErrorAction SilentlyContinue }
    $c = New-N5TestCtx
    try {
        & $mkS1Leftover $c $script:N5StaleSid; $c.Only = @('R0'); $w = $c.World
        $r = Invoke-Nep5Phase -Ctx $c -Phase 'halfset'
        Chk 'pre-cleanup: a set for a DIFFERENT SID is not the incident pattern: nothing is removed, exit 2, the filters are untouched' (($r.ExitCode -eq 2) -and $r.Records[0].state -eq 'pre_cleanup' -and $w.Filters.Count -eq 4 -and @($c.Runner.State.Calls | Where-Object { $_ -like 'uninstall*' -or $_ -like 'delete*' }).Count -eq 0) 'pre-cleanup'
    } finally { Remove-Item -LiteralPath $c.Tmp -Recurse -Force -ErrorAction SilentlyContinue }
    $c = New-N5TestCtx
    try {
        & $mkS1Leftover $c $sidS; $c.Only = @('R0'); $w = $c.World; $w.SubLayers[$s2] = ''
        $r = Invoke-Nep5Phase -Ctx $c -Phase 'halfset'
        Chk 'pre-cleanup: the set plus a sublayer in S2 is not the incident pattern: nothing is removed, exit 2' (($r.ExitCode -eq 2) -and $w.Filters.Count -eq 4 -and @($c.Runner.State.Calls | Where-Object { $_ -like 'uninstall*' }).Count -eq 0) 'pre-cleanup'
    } finally { Remove-Item -LiteralPath $c.Tmp -Recurse -Force -ErrorAction SilentlyContinue }
    $c = New-N5TestCtx
    try {
        & $mkS1Leftover $c $sidS; $c.Only = @('R0'); $w = $c.World
        $fk = 'cccccccc-0000-4d8e-9a31-2b6d4c8e0002'; $w.Filters[$fk] = [pscustomobject]@{ Key = $fk; SubLayer = '11111111-2222-3333-4444-555555555555'; Layer = 'v4'; Name = 'srt-win-v4-block-user'; Kind = 'block-user'; Tool = 'srt-win'; Sid = $sidS; HasUser = $true; Action = 'block' }
        $r = Invoke-Nep5Phase -Ctx $c -Phase 'halfset'
        Chk 'pre-cleanup: with an srt-win filter outside S1/S2/S3 as well the first action is a STOP (exit 9): nothing is removed' (($r.ExitCode -eq 9) -and $w.Filters.Count -eq 5 -and @($c.Runner.State.Calls | Where-Object { $_ -like 'uninstall*' }).Count -eq 0) 'pre-cleanup'
    } finally { Remove-Item -LiteralPath $c.Tmp -Recurse -Force -ErrorAction SilentlyContinue }
    $c = New-N5TestCtx
    try {
        & $mkS1Leftover $c $sidS; $c.Only = @('R0'); $w = $c.World
        $c.Runner = New-FakeHalfset -World $w -NotArmed $true
        $r = Invoke-Nep5Phase -Ctx $c -Phase 'halfset'
        Chk 'pre-cleanup: if the harness answers 12 (stale harness proof) the set is still removed BY KEY through our own engine and read back clean; the phase goes on' (($r.ExitCode -eq 0) -and ($w.Filters.Count + $w.SubLayers.Count + $w.Providers.Count) -eq 0 -and (Get-Content $r.ResultsPath -Raw | ConvertFrom-Json).pre_cleanup.Steps.by_key.ok) 'pre-cleanup'
    } finally { Remove-Item -LiteralPath $c.Tmp -Recurse -Force -ErrorAction SilentlyContinue }
    $c = New-N5TestCtx
    try {
        & $mkS1Leftover $c $sidS; $w = $c.World
        $rm = Remove-Nep5All -Runner $c.Runner -Backend $c.Backend
        $swR = Invoke-Nep5DirectSweep -Runner $c.Runner -Backend $c.Backend -Exporter $c.Exporter -Label 'after-remove'
        Chk 'pre-existing set: -Remove''s remover deletes it filter by filter (armed), then the sublayer, and the direct checks read clean' ($rm.Ok -and $swR.Clean -and $w.Filters.Count -eq 0 -and @($c.Runner.State.Calls | Where-Object { $_ -like 'delete-filter*' -and $_ -like '*--live*' }).Count -eq 4)
    } finally { Remove-Item -LiteralPath $c.Tmp -Recurse -Force -ErrorAction SilentlyContinue }

    Write-Host '== the rollback proof and its hash binding (temp folder, fake files) ==' -ForegroundColor Cyan
    $tmp = Join-Path ([IO.Path]::GetTempPath()) ('nep5-proof-' + [guid]::NewGuid().ToString('N')); New-Item -ItemType Directory -Path $tmp | Out-Null
    $savedPin = $script:N5PinnedCargoLockSha256; $savedNonce = $script:N5ProofNonce
    try {
        foreach ($n in $script:N5CodeSetFiles) { [IO.File]::WriteAllText((Join-Path $tmp $n), "# fake $n`n") }
        [IO.File]::WriteAllText((Join-Path $tmp 'spike-nep5-matrix.ps1'), ((1..150 | ForEach-Object { "    Chk 'site$_' `$true" }) -join "`n") + "`n")
        $exeP = Join-Path $tmp 'halfset.exe'; $rsP = Join-Path $tmp 'halfset.rs'; $lockP = Join-Path $tmp 'Cargo.lock'
        [IO.File]::WriteAllBytes($exeP, [byte[]](1, 2, 3, 13, 10, 4)); [IO.File]::WriteAllText($rsP, "// fake halfset`r`n"); [IO.File]::WriteAllText($lockP, "# fake lock`n")
        $wrapped = Join-Path $tmp 'wrapped-1671.ps1'; [IO.File]::WriteAllText($wrapped, "# fake wrapped`n`$x = 1`n"); $wh = Get-NormalizedSha256 -Path $wrapped
        $script:N5PinnedCargoLockSha256 = Get-N5RawSha256 -Path $lockP
        $hashes = (Get-N5CodeSetHashes -Folder $tmp).Hashes; $hh = Get-N5HarnessHashes -Exe $exeP -Source $rsP -CargoLock $lockP
        $hlp = Join-Path $tmp 'harness-live-proof-1763.json'; [IO.File]::WriteAllText($hlp, (ConvertTo-Json -InputObject (New-N5HarnessLiveProof -ExeSha $hh.exe_sha256 -RsSha $hh.source_sha256))); $hh['live_proof_sha256'] = Get-N5RawSha256 -Path $hlp
        $pp = Join-Path $tmp 'proof.json'; $now = [datetimeoffset]::Now
        $sibOk = @(1..1 | ForEach-Object { [ordered]@{ name = "sibling$_"; passed = $true; checks = 20 } }); $hcOk = [ordered]@{ refusals_exit_zero = $true; engine_open_trace_empty = $true; version_ok = $true }
        $mk = { param($written, $tags, $failed, $run = 150, $passedN = 150, $sib = $sibOk, $whash = $wh, $hc = $hcOk) (ConvertTo-Json -InputObject (New-N5ProofObject -Hashes $hashes -Harness $hh -PassedTags $tags -FailedChecks $failed -HostInfo 'selftest' -When $written -WrappedHash $whash -ChecksRun $run -ChecksPassed $passedN -Siblings $sib -HarnessChecks $hc) -Depth 8) }
        $allTags = @($script:N5RequiredTags)
        $chkProof = { Test-N5Proof -ProofPath $pp -Folder $tmp -WrappedSha256 (Get-NormalizedSha256 -Path $wrapped) -HarnessExe $exeP -HarnessSource $rsP -CargoLock $lockP -HarnessLiveProof $hlp }
        [IO.File]::WriteAllText($pp, (& $mk $now.ToString('o') $allTags @()))
        $t1 = & $chkProof
        Chk 'proof: a complete, fresh proof whose hashes all match (scripts, wrapped script, harness exe, halfset.rs, Cargo.lock) is accepted and yields a token with a nonce' (($t1.Ok -eq $true) -and ($t1.Kind -eq 'Nep5Proof') -and $t1.Nonce -and (Test-N5ProofToken $t1))
        $t1b = & $chkProof
        Chk 'proof: the token carries the hashes it VERIFIED (the probe script, the harness exe and spike-provision.ps1), which is what the run binds its copy, its runner and its re-provisioning to' (($t1.ProbeSha -eq $hashes['spike-nep5-connect-probe.ps1']) -and ($t1.HarnessSha -eq $hh.exe_sha256) -and ($t1.ProvisionSha -eq $hashes['spike-provision.ps1']) -and ($t1.ProvisionSha -match '^[0-9A-F]{64}$')) 'proof-hash-binding'
        Chk 'proof: a second successful check issues a NEW nonce: the earlier token is refused (a token cannot outlive the check that made it)' ((Test-N5ProofToken $t1b) -and -not (Test-N5ProofToken $t1)) 'forged-proof-refused'
        $first = $script:N5CodeSetFiles[1]; $fp = Join-Path $tmp $first
        [IO.File]::WriteAllText($fp, "# edited after the self-test`n"); $t2 = & $chkProof
        Chk 'proof: editing ONE new script after the self-test invalidates it, naming the file; the token is not Ok and is refused by the adders' (($t2.Ok -eq $false) -and (@($t2.Problems | Where-Object { $_ -match [regex]::Escape($first) }).Count -eq 1) -and -not (Test-N5ProofToken $t2)) 'proof-hash-binding'
        [IO.File]::WriteAllText($fp, "# fake $first`n"); $t3 = & $chkProof
        Chk 'proof: restoring the exact bytes validates it again; a CRLF copy of the same script text validates too (scripts are hashed LF-normalised)' (($t3.Ok -eq $true) -and ((& { [IO.File]::WriteAllText($fp, "# fake $first`r`n"); (& $chkProof).Ok }) -eq $true)) 'proof-hash-binding'
        [IO.File]::WriteAllText($fp, "# fake $first`n")
        foreach ($case in @(@{ n = 'the harness exe'; p = $exeP; bytes = [byte[]](1, 2, 3, 13, 10, 5); orig = [byte[]](1, 2, 3, 13, 10, 4) }, @{ n = 'halfset.rs'; p = $rsP; bytes = [Text.Encoding]::ASCII.GetBytes("// edited`r`n"); orig = [Text.Encoding]::ASCII.GetBytes("// fake halfset`r`n") })) {
            [IO.File]::WriteAllBytes($case.p, $case.bytes); $tx = & $chkProof
            Chk "proof: a one-byte edit of $($case.n) invalidates it, naming it" (($tx.Ok -eq $false) -and (@($tx.Problems | Where-Object { $_ -match [regex]::Escape($case.n) }).Count -ge 1)) 'proof-hash-binding'
            [IO.File]::WriteAllBytes($case.p, $case.orig)
        }
        [IO.File]::WriteAllBytes($exeP, [byte[]](1, 2, 3, 10, 4)); $tcr = & $chkProof
        Chk 'proof: the exe is hashed RAW: the same bytes with CRLF turned into LF are a different exe and invalidate the proof (unlike scripts)' ($tcr.Ok -eq $false) 'harness-hash-binding'
        [IO.File]::WriteAllBytes($exeP, [byte[]](1, 2, 3, 13, 10, 4))
        $hlpGood = [IO.File]::ReadAllText($hlp)
        [IO.File]::WriteAllText($hlp, (ConvertTo-Json -InputObject (New-N5HarnessLiveProof -ExeSha $hh.exe_sha256 -RsSha $hh.source_sha256 -Now (Get-Date).AddMinutes(-1)))); $thp1 = & $chkProof
        Chk 'proof: a harness proof file REWRITTEN after the self-test (even a valid-looking one) is refused: it is not the file this proof was written with' (($thp1.Ok -eq $false) -and (@($thp1.Problems | Where-Object { $_ -match 'not the one this proof was written with' }).Count -eq 1)) 'harness-live-proof-binding'
        [IO.File]::WriteAllText($hlp, $hlpGood)
        Remove-Item -LiteralPath $hlp -Force; $thp2 = & $chkProof; [IO.File]::WriteAllText($hlp, $hlpGood)
        Chk 'proof: a missing harness proof file is refused; restoring the exact bytes validates again' (($thp2.Ok -eq $false) -and ((& $chkProof).Ok -eq $true)) 'harness-live-proof-binding'
        [IO.File]::WriteAllText($lockP, "# changed lock`n"); $tl = & $chkProof
        Chk 'proof: a Cargo.lock that changed (and is therefore no longer the pinned one) invalidates it' (($tl.Ok -eq $false) -and (@($tl.Problems | Where-Object { $_ -match 'Cargo\.lock' }).Count -ge 1)) 'proof-hash-binding'
        [IO.File]::WriteAllText($lockP, "# fake lock`n")
        $script:N5PinnedCargoLockSha256 = $savedPin; $tp = & $chkProof
        Chk 'proof: a Cargo.lock that is unchanged since the self-test but is NOT the recorded pin is refused (the pin is a constant of the scripts, not just what the proof recorded)' (($tp.Ok -eq $false) -and (@($tp.Problems | Where-Object { $_ -match 'not the pinned one' }).Count -eq 1)) 'proof-hash-binding'
        $script:N5PinnedCargoLockSha256 = Get-N5RawSha256 -Path $lockP
        [IO.File]::WriteAllText($wrapped, "# fake wrapped`n`$x = 2`n"); $tw = & $chkProof
        Chk 'proof: a ONE-TOKEN edit of the wrapped #1671 script invalidates it' (($tw.Ok -eq $false) -and (@($tw.Problems | Where-Object { $_ -match 'wrapped #1671 script changed' }).Count -eq 1)) 'proof-hash-binding'
        [IO.File]::WriteAllText($wrapped, "# fake wrapped`n`$x = 1`n")
        Remove-Item -LiteralPath (Join-Path $tmp $script:N5CodeSetFiles[2]) -Force; $tm = & $chkProof
        Chk 'proof: a code-set file missing from the folder invalidates it, naming the file' (($tm.Ok -eq $false) -and (@($tm.Problems | Where-Object { $_ -match [regex]::Escape($script:N5CodeSetFiles[2]) }).Count -ge 1))
        [IO.File]::WriteAllText((Join-Path $tmp $script:N5CodeSetFiles[2]), "# fake $($script:N5CodeSetFiles[2])`n")
        [IO.File]::WriteAllText($pp, (& $mk $now.AddHours(-25).ToString('o') $allTags @())); $told = & $chkProof
        [IO.File]::WriteAllText($pp, (& $mk $now.AddHours(2).ToString('o') $allTags @())); $tfut = & $chkProof
        Chk 'proof: older than 24 hours, and dated in the future, are each refused' (($told.Ok -eq $false) -and ($tfut.Ok -eq $false))
        $variants = @(
            @{ n = 'zero checks run'; j = (& $mk $now.ToString('o') $allTags @() 0 0) }, @{ n = 'more checks claimed than the self-test has check sites'; j = (& $mk $now.ToString('o') $allTags @() 999 999) },
            @{ n = 'fewer checks passed than run'; j = (& $mk $now.ToString('o') $allTags @() 150 149) }, @{ n = 'a recorded failed check'; j = (& $mk $now.ToString('o') $allTags @('a failed check')) },
            @{ n = 'a missing required tag'; j = (& $mk $now.ToString('o') @($allTags | Select-Object -First ($allTags.Count - 1)) @()) }, @{ n = 'no sibling self-test results'; j = (& $mk $now.ToString('o') $allTags @() 150 150 @()) },
            @{ n = 'a failed sibling'; j = (& $mk $now.ToString('o') $allTags @() 150 150 @(@{ name = 'a'; passed = $true; checks = 20 }, @{ name = 'b'; passed = $false; checks = 20 })) },
            @{ n = 'no harness self-check record'; j = (& $mk $now.ToString('o') $allTags @() 150 150 $sibOk $wh $null) }, @{ n = 'a harness whose refusal test opened the engine'; j = (& $mk $now.ToString('o') $allTags @() 150 150 $sibOk $wh ([ordered]@{ refusals_exit_zero = $true; engine_open_trace_empty = $false })) },
            @{ n = 'no wrapped-script hash'; j = (& $mk $now.ToString('o') $allTags @() 150 150 $sibOk '') }, @{ n = 'an old schema'; j = ((& $mk $now.ToString('o') $allTags @()) -replace '"schema":\s*1', '"schema": 0') }, @{ n = 'not JSON'; j = '{not json' })
        $allRefused = $true; $names = @(); foreach ($v in $variants) { [IO.File]::WriteAllText($pp, $v.j); if ((& $chkProof).Ok) { $allRefused = $false; $names += $v.n } }
        Chk "proof: each of these is refused: zero checks run, too many claimed, fewer passed than run, a failed check, a missing tag, no sibling results, a failed sibling, no harness record, a harness that opened the engine, no wrapped hash, an old schema, not JSON $(if ($names.Count) { '(NOT refused: ' + ($names -join ', ') + ')' })" $allRefused 'proof-hash-binding'
        Remove-Item -LiteralPath $pp -Force
        Chk 'proof: no file at all is refused' (-not (& $chkProof).Ok)
        Chk 'proof: the ceiling counts the Chk calls of the matrix scripts beside it, counted by the parser (150 here), plus 30' ((Get-N5ChecksCeiling -Folder $tmp) -eq 180)
        $csTmp = Get-N5CodeSetHashes -Folder $tmp
        Chk 'code set: every file of the new code set is hashed, a library this process loaded is represented by the hash of the bytes it ran, and the set names both libraries, the probe, the arms'' libraries and spike-provision.ps1' (($csTmp.Missing.Count -eq 0) -and ($script:N5CodeSetFiles.Count -eq 8) -and ($script:N5CodeSetFiles -contains 'spike-provision.ps1') -and ($script:N5CodeSetFiles -contains 'spike-nep5-lib.ps1') -and ($script:N5CodeSetFiles -contains 'spike-nep5-run-lib.ps1') -and ($script:N5CodeSetFiles -contains 'spike-nep5-connect-probe.ps1') -and ($script:N5CodeSetFiles -contains 'spike-persist-lib.ps1') -and ($script:LoadedLibHashes.ContainsKey('spike-nep5-lib.ps1')) -and ($script:LoadedLibHashes['spike-nep5-lib.ps1'] -eq (Get-NormalizedSha256 -Path (Join-Path $PSScriptRoot 'spike-nep5-lib.ps1'))))
    } finally { $script:N5PinnedCargoLockSha256 = $savedPin; $script:N5ProofNonce = $savedNonce; Remove-Item -LiteralPath $tmp -Recurse -Force -ErrorAction SilentlyContinue }

    Write-Host '== targets, listeners, the account''s task, the bin folder, results ==' -ForegroundColor Cyan
    $all = @{}; foreach ($t in (Get-Nep5Targets -Bound @{})) { $all[$t.Key] = $true }; $half = $all.Clone(); $half['v6:61763'] = $false
    $tg = Get-Nep5Targets -Bound $half
    Chk 'targets: three ports x two families; a target whose listener did not bind is NOT runnable (NOT RUN), never "blocked"' (($tg.Count -eq 6) -and (@($tg | Where-Object { -not $_.Runnable }).Count -eq 1) -and (@($tg | Where-Object { -not $_.Runnable })[0].Key -eq 'v6:61763') -and (@(Get-Nep5Targets -Bound @{} | Where-Object { $_.Runnable }).Count -eq 0))
    $free = { $l = New-Object Net.Sockets.TcpListener([Net.IPAddress]::Loopback, 0); $l.Start(); $p = ([Net.IPEndPoint]$l.LocalEndpoint).Port; $l.Stop(); $p }
    $p1 = & $free; $p2 = & $free
    $ls = Start-Nep5Listeners -Ports @($p1)
    $cn4 = Test-Nep5Loopback -Family v4 -Port $p1
    Chk 'listeners (real loopback): the v4 listener binds and a connect completes against it' ($ls.Bound["v4:$p1"] -and $cn4.ok)
    if ($ls.Bound["v6:$p1"]) { $cn6 = Test-Nep5Loopback -Family v6 -Port $p1; Chk 'listeners (real loopback): the [::1] listener binds and a connect completes against it' ($cn6.ok) } else { Write-Host '  [SKIP] [::1] did not bind here: its rows would be NOT RUN' -ForegroundColor Yellow }
    $ls2 = Start-Nep5Listeners -Ports @($p1)
    Chk 'listeners: a port that is already taken is reported as NOT bound (no throw), so its rows are NOT RUN' ((-not $ls2.Bound["v4:$p1"]) -and ($null -ne (@($ls2.Items | Where-Object { $_.Family -eq 'v4' })[0].Error)))
    Stop-Nep5Listeners $ls2; Stop-Nep5Listeners $ls
    $cnClosed = Test-Nep5Loopback -Family v4 -Port $p1 -TimeoutMs 1500
    Chk 'listeners: after Stop the port refuses connections' (-not $cnClosed.ok)
$to = New-Nep5FakeTaskOps
    Chk 'task: the state reads original only for the recorded original arguments; anything else is unknown, an unreadable task is unreadable (there is no "probe" state any more: the task is never edited)' (((Get-Nep5TaskState -Ops $to) -eq 'original') -and ((Get-Nep5TaskState -Ops (New-Nep5FakeTaskOps -Initial 'powershell -File evil.ps1')) -like 'unknown:*') -and ((Get-Nep5TaskState -Ops ([pscustomobject]@{} | Add-Member -MemberType ScriptMethod -Name GetArguments -Value { throw 'no task' } -PassThru)) -like 'unreadable:*'))
    $bt = Join-Path ([IO.Path]::GetTempPath()) ('nep5-bin-' + [guid]::NewGuid().ToString('N')); $sfT = Join-Path $bt 'scripts'; $bnT = Join-Path $bt 'bin'; New-Item -ItemType Directory -Path $sfT, $bnT | Out-Null
    try {
        [IO.File]::WriteAllText((Join-Path $sfT $script:N5ProbeScriptName), "# probe`r`n"); [IO.File]::WriteAllText((Join-Path $bnT 'spike-config.json'), '{}'); [IO.File]::WriteAllText((Join-Path $bnT 'request.json'), '{}')
        $shaP = Get-NormalizedSha256 -Path (Join-Path $sfT $script:N5ProbeScriptName)
        $iBad = Install-Nep5ProbeScript -ScriptFolder $sfT -BinDir $bnT -ExpectedSha ('AB' * 32); $iOk = Install-Nep5ProbeScript -ScriptFolder $sfT -BinDir $bnT -ExpectedSha $shaP
        Chk 'bin: the probe script is copied only if it hashes to the proof''s value (a different one writes nothing); the copy hashes like the source' ((-not $iBad.Ok) -and $iOk.Ok -and (Test-Path (Join-Path $bnT $script:N5ProbeScriptName)) -and ((Get-NormalizedSha256 -Path (Join-Path $bnT $script:N5ProbeScriptName)) -eq $shaP))
        [IO.File]::WriteAllText((Join-Path $bnT 'nep5-request.json'), '{}'); [IO.File]::WriteAllBytes((Join-Path $bnT 'halfset.exe'), [byte[]](1))
        $rb = Remove-Nep5BinFiles -BinDir $bnT
        Chk 'bin: removal deletes exactly the three names (probe copy, a stale harness copy, request) and nothing else (spike-config.json and request.json stay), then reads back' ($rb.Ok -and (Test-Path (Join-Path $bnT 'spike-config.json')) -and (Test-Path (Join-Path $bnT 'request.json')) -and @(Get-Nep5BinResidue -BinDir $bnT).Count -eq 0)
        
        
        
        $null = Remove-Nep5BinFiles -BinDir $bnT
    } finally { Remove-Item -LiteralPath $bt -Recurse -Force -ErrorAction SilentlyContinue }
    $req = [pscustomobject]@{ run_id = 'nep5-t-0001'; mode = 'connect'; targets = @([pscustomobject]@{ family = 'v4'; port = 61763 }, [pscustomobject]@{ family = 'v6'; port = 61763 }) }
    $resGood = [pscustomobject]@{ schema_version = 1; kind = 'nep5-probe'; run_id = 'nep5-t-0001'; mode = 'connect'; started = (Get-N5Now); token_sid = $sidS; overall = 'done'; error = $null
                                  targets = @([pscustomobject]@{ family = 'v4'; port = 61763; result = 'blocked'; win32 = 10013 }, [pscustomobject]@{ family = 'v6'; port = 61763; result = 'connected'; win32 = 0 }) }
    $judge = { param($mut) $r = ($resGood | ConvertTo-Json -Depth 6 | ConvertFrom-Json); & $mut $r; Resolve-Nep5AccountResult -Request $req -Result $r -ExpectedSid $sidS -RequestedAt ([datetimeoffset]::Now.AddMinutes(-1)) }
    Chk 'result: a well-formed result for exactly the requested rows is valid' ((& $judge { param($r) }).Valid)
    $bad = @(
        @{ n = 'wrong token SID'; m = { param($r) $r.token_sid = 'S-1-5-21-1-2-3-1001' } }, @{ n = 'wrong run id'; m = { param($r) $r.run_id = 'other-run-id' } }, @{ n = 'wrong mode'; m = { param($r) $r.mode = 'identity' } },
        @{ n = 'a missing row'; m = { param($r) $r.targets = @($r.targets[0]) } }, @{ n = 'rows in the wrong order'; m = { param($r) $r.targets = @($r.targets[1], $r.targets[0]) } }, @{ n = 'an unknown outcome'; m = { param($r) $r.targets[0].result = 'maybe' } },
        @{ n = 'no integer socket code'; m = { param($r) $r.targets[0].win32 = 'x' } }, @{ n = 'overall error'; m = { param($r) $r.overall = 'error' } }, @{ n = 'a result that predates the request'; m = { param($r) $r.started = '2001-01-01T00:00:00.000+00:00' } },
        @{ n = 'the wrong kind'; m = { param($r) $r.kind = 'spike' } })
    $bn = @(); foreach ($b in $bad) { if ((& $judge $b.m).Valid) { $bn += $b.n } }
    Chk "result: each of these is judged invalid, never read as a connect outcome: wrong token SID, wrong run id, wrong mode, missing row, rows out of order, unknown outcome, no socket code, overall error, predates the request, wrong kind $(if ($bn.Count) { '(NOT invalid: ' + ($bn -join ', ') + ')' })" ($bn.Count -eq 0)
    $dres = { param($v, $ph, $rc) [pscustomobject]@{ Valid = $true; Result = [pscustomobject]@{ direct = [pscustomobject]@{ op = 'add'; phase = $ph; rc_hex = $rc; verdict = $v } } } }
    $dreq = [pscustomobject]@{ run_id = 'nep5-t-0002'; mode = 'direct'; direct = [pscustomobject]@{ op = 'add' } }
    $dresult = { param($mut) $r = [pscustomobject]@{ schema_version = 1; kind = 'nep5-probe'; run_id = 'nep5-t-0002'; mode = 'direct'; started = (Get-N5Now); token_sid = $sidS; overall = 'done'; direct = [pscustomobject]@{ op = 'add'; phase = 'call'; rc_hex = '0x00000005'; verdict = 'denied' } }; & $mut $r; Resolve-Nep5AccountResult -Request $dreq -Result $r -ExpectedSid $sidS -RequestedAt ([datetimeoffset]::Now.AddMinutes(-1)) }
    Chk 'result (direct mode): a well-formed record is valid; no direct record, another op, an unknown phase, a call status that is not a hex status and an unknown verdict are each invalid' (((& $dresult { param($r) }).Valid) -and (-not (& $dresult { param($r) $r.direct = $null }).Valid) -and (-not (& $dresult { param($r) $r.direct.op = 'delete' }).Valid) -and (-not (& $dresult { param($r) $r.direct.phase = 'wherever' }).Valid) -and (-not (& $dresult { param($r) $r.direct.rc_hex = 'denied' }).Valid) -and (-not (& $dresult { param($r) $r.direct.verdict = 'fine' }).Valid))
    Chk 'N1 class: denied (the call''s status, code kept verbatim), succeeded, other (any other status at the call, or a failure at the open or compile: never "denied"), no_result' (((Get-Nep5N1Class -Run (& $dres 'denied' 'call' '0x00000005')).Class -eq 'denied') -and ((Get-Nep5N1Class -Run (& $dres 'denied' 'call' '0x00000005')).Code -eq '0x00000005') -and ((Get-Nep5N1Class -Run (& $dres 'succeeded' 'call' '0x00000000')).Class -eq 'succeeded') -and ((Get-Nep5N1Class -Run (& $dres 'open_failed' 'open' '0x00000005')).Class -eq 'other') -and ((Get-Nep5N1Class -Run (& $dres 'compile_failed' 'compile' '')).Class -eq 'other') -and ((Get-Nep5N1Class -Run (& $dres 'other' 'call' '0x80320007')).Class -eq 'other') -and ((Get-Nep5N1Class -Run ([pscustomobject]@{ Valid = $false })).Class -eq 'no_result'))
    $mkRec = { param($cls) [pscustomobject]@{ class = $cls } }
    Chk 'phase exit: stop / operator abort / finding -> 9 beats removal unverified 7 beats control failure 5 beats refusal 2 beats inconclusive 4 beats ok 0' (((Get-Nep5PhaseExit @((& $mkRec 'ok'), (& $mkRec 'finding_stop'), (& $mkRec 'removal_unverified'))) -eq 9) -and ((Get-Nep5PhaseExit @((& $mkRec 'operator_abort'))) -eq 9) -and ((Get-Nep5PhaseExit @((& $mkRec 'stop'))) -eq 9) -and ((Get-Nep5PhaseExit @((& $mkRec 'ok'), (& $mkRec 'removal_unverified'), (& $mkRec 'control_failed'))) -eq 7) -and ((Get-Nep5PhaseExit @((& $mkRec 'control_failed'), (& $mkRec 'inconclusive'))) -eq 5) -and ((Get-Nep5PhaseExit @((& $mkRec 'refused'), (& $mkRec 'inconclusive'))) -eq 2) -and ((Get-Nep5PhaseExit @((& $mkRec 'inconclusive'), (& $mkRec 'ok'))) -eq 4) -and ((Get-Nep5PhaseExit @((& $mkRec 'ok'), (& $mkRec 'ok'))) -eq 0))
    $script:opAbort = $false; $removed = New-Object System.Collections.ArrayList; $seq = New-Object System.Collections.ArrayList; $pat = @(0, 1, 0, 0)
    $probeSeq = { $n = $seq.Count; [void]$seq.Add($n); [pscustomobject]@{ ok = ($pat[$n] -ne 0); t = ''; error = 'x'; ms = 1 } }.GetNewClosure()
    $wd = New-Nep5Tick -Probe $probeSeq -OnAbort ({ [void]$removed.Add('removed'); 'removal-record' }.GetNewClosure()) -MinGapSeconds 0
    1..3 | ForEach-Object { & $wd.Tick }
    Chk 'watchdog: fail, ok, fail does not abort and removes nothing' ((-not $script:opAbort) -and $removed.Count -eq 0 -and $wd.State.Fail -eq 2)
    & $wd.Tick
    Chk 'watchdog: a second consecutive failure aborts: the removal runs ONCE, the abort flag is set and the removal record is kept' ($script:opAbort -and $removed.Count -eq 1 -and $wd.State.Aborted -and $wd.State['AbortRemoval'] -eq 'removal-record')
    & $wd.Tick; Chk 'watchdog: after an abort further ticks do not remove again' ($removed.Count -eq 1)
    $script:opAbort = $false
    $seq.Clear(); $wdGap = New-Nep5Tick -Probe $probeSeq -OnAbort { 'x' } -MinGapSeconds 5; & $wdGap.Tick; & $wdGap.Tick
    Chk 'watchdog: ticks closer together than the gap (2 s in a real run) do not connect again' ($seq.Count -eq 1)

    Write-Host '== whole cycles against the fake machine (reachability of every state through the real entry points) ==' -ForegroundColor Cyan
    $c = New-N5TestCtx
    try {
        $r = Invoke-Nep5Phase -Ctx $c -Phase 'halfset'
        $by = @{}; foreach ($rec in $r.Records) { $by[$rec.state] = $rec }
        Chk 'halfset phase: R0..R7 each ran one pass and every cycle is class ok; exit 0' (($r.ExitCode -eq 0) -and @($r.Records | Where-Object { $_.class -ne 'ok' }).Count -eq 0 -and $r.Records.Count -eq 8)
        $cell = { param($id, $k) Get-N5Cell $by[$id] $k }
        Chk 'R0: no filters: the account is open on all six targets' (@($by['R0'].steps.during.account.Summary.Values | Where-Object { $_ -ne 'open' }).Count -eq 0 -and $by['R0'].steps.readings.status_word -eq 'absent')
        Chk 'R1: full set: status installed; the account is blocked outside the range on v4 and v6 and open inside 60080-60089 (the permits)' (($by['R1'].steps.readings.status_word -eq 'installed') -and (& $cell 'R1' 'v4:61763') -eq 'blocked' -and (& $cell 'R1' 'v6:61764') -eq 'blocked' -and (& $cell 'R1' 'v4:60085') -eq 'open' -and (& $cell 'R1' 'v6:60085') -eq 'open')
        Chk 'R2: V4 block deleted: status STILL installed; v4 open on every port, v6 blocked outside the range' (($by['R2'].steps.readings.status_word -eq 'installed') -and (& $cell 'R2' 'v4:61763') -eq 'open' -and (& $cell 'R2' 'v6:61763') -eq 'blocked' -and $by['R2'].steps.add.Deleted[0].role -eq 'block-v4')
        Chk 'R3: V6 block deleted: status installed; v6 open, v4 blocked outside the range' (($by['R3'].steps.readings.status_word -eq 'installed') -and (& $cell 'R3' 'v6:61763') -eq 'open' -and (& $cell 'R3' 'v4:61763') -eq 'blocked')
        Chk 'R4: both blocks deleted, permits remain: status absent-or-installed as the harness says; the account is open everywhere' (@($by['R4'].steps.during.account.Summary.Values | Where-Object { $_ -ne 'open' }).Count -eq 0 -and @($by['R4'].steps.add.Deleted).Count -eq 2)
        Chk 'R5: permits deleted, blocks remain: the account is blocked everywhere including inside the range; status installed' (@($by['R5'].steps.during.account.Summary.Values | Where-Object { $_ -ne 'blocked' }).Count -eq 0 -and $by['R5'].steps.readings.status_word -eq 'installed')
        Chk 'R6: stale test SID: status installed while the account is open everywhere (the finding)' (($by['R6'].steps.readings.status_word -eq 'installed') -and @($by['R6'].steps.during.account.Summary.Values | Where-Object { $_ -ne 'open' }).Count -eq 0)
        Chk 'R7: our unlabelled blocks in S3: srt-win''s status on S1 reads ABSENT while the account is blocked everywhere (the reverse finding)' (($by['R7'].steps.readings.status_word -eq 'absent') -and @($by['R7'].steps.during.account.Summary.Values | Where-Object { $_ -ne 'blocked' }).Count -eq 0 -and $by['R7'].steps.readings.enum.S3.n -eq 2 -and $by['R7'].steps.readings.enum.S1.n -eq 0)
        $w = $c.World
        Chk 'halfset phase: afterwards the fake machine is empty, the account task reads original, the bin folder is empty, and every cycle''s sweep before and after read clean' (($w.Filters.Count + $w.SubLayers.Count + $w.Providers.Count) -eq 0 -and (Get-Nep5TaskState -Ops $c.TaskOps) -eq 'original' -and @(Get-Nep5BinResidue -BinDir $c.BinDir).Count -eq 0 -and @($r.Records | Where-Object { -not $_.steps.sweep_before.clean -or ($_.steps.sweep_after -and -not $_.steps.sweep_after.clean) }).Count -eq 0)
        Chk 'halfset phase: a session password was set once (on the recorded account), released, and the task was re-provisioned exactly once and proven; the results file was written' (($c.AcctSw.Sets.Count -eq 1) -and ($c.AcctSw.Sets[0] -eq 'blarai-spike') -and ($c.RepSw.Count -eq 1) -and (-not $c.AccountOps.Changed) -and ($null -eq $c.AccountOps.Cred) -and (Test-Path $r.ResultsPath) -and ((Get-Content $r.ResultsPath -Raw | ConvertFrom-Json).records.Count -eq 8)) 'restore-proof'
        Chk 'halfset phase: the exact harness commands of a cycle are recorded' (@($by['R2'].commands | Where-Object { ($_.argv -join ' ') -like "install --sublayer $s1 --sid $sidS --live *" }).Count -eq 1 -and @($by['R2'].commands | Where-Object { ($_.argv -join ' ') -like 'delete-filter*' }).Count -ge 1)
        $c.OutDir | Out-Null
        $r2 = Invoke-Nep5Phase -Ctx $c -Phase 'ours'
        $bo = @{}; foreach ($rec in $r2.Records) { $bo[$rec.state] = $rec }
        $cell2 = { param($id, $k) Get-N5Cell $bo[$id] $k }
        Chk 'ours phase: O1..O6 each ran and every cycle is class ok; exit 0' (($r2.ExitCode -eq 0) -and @($r2.Records | Where-Object { $_.class -ne 'ok' }).Count -eq 0 -and $r2.Records.Count -eq 6)
        Chk 'O1/O2: V4 block only blocks v4 and leaves v6 open; V6 block only the reverse; our four keys read PRESENT (provider, sublayer, filter)' (((& $cell2 'O1' 'v4:61763') -eq 'blocked') -and ((& $cell2 'O1' 'v6:61763') -eq 'open') -and ((& $cell2 'O2' 'v6:61763') -eq 'blocked') -and ((& $cell2 'O2' 'v4:61763') -eq 'open') -and $bo['O1'].steps.readings.our_keys.state -eq 'PRESENT')
        Chk 'O3: a permit without a block: the account is open everywhere' (@($bo['O3'].steps.during.account.Summary.Values | Where-Object { $_ -ne 'open' }).Count -eq 0)
        Chk 'O4: exact-port permit: v4 on the permitted port is open, the neighbour port and the in-range port are blocked, v6 is blocked everywhere' (((& $cell2 'O4' 'v4:61763') -eq 'open') -and ((& $cell2 'O4' 'v4:61764') -eq 'blocked') -and ((& $cell2 'O4' 'v4:60085') -eq 'blocked') -and ((& $cell2 'O4' 'v6:61763') -eq 'blocked') -and ((& $cell2 'O4' 'v6:61764') -eq 'blocked'))
        Chk 'O5/O6: the engine''s answer to the attempt is recorded verbatim (0x8032002F / 0x80320007), and the account stays open' (($bo['O5'].steps.add.Detail.Attempts[0].status -like '*0x8032002F') -and ($bo['O6'].steps.add.Detail.Attempts[0].status -like '*0x80320007') -and @($bo['O5'].steps.during.account.Summary.Values | Where-Object { $_ -ne 'open' }).Count -eq 0)
        Chk 'ours phase: the fake machine is empty again and the task is original' (($w.Filters.Count + $w.SubLayers.Count + $w.Providers.Count) -eq 0 -and (Get-Nep5TaskState -Ops $c.TaskOps) -eq 'original')
        $r3 = Invoke-Nep5Phase -Ctx $c -Phase 'n1'
        $n1 = $r3.Records[0]
        Chk 'N1: the account''s own direct add and direct delete (no harness) are both denied by the engine at the CALL, the code recorded verbatim; the test filter is still there when the delete is judged; the add left nothing behind; class ok' (($r3.ExitCode -eq 0) -and $n1.class -eq 'ok' -and $n1.steps.n1_add.class -eq 'denied' -and $n1.steps.n1_add.code -eq '0x00000005' -and $n1.steps.n1_add.filter_present_after -eq $false -and $n1.steps.n1_delete.class -eq 'denied' -and $n1.steps.n1_delete.filter_still_present -eq $true)
        Chk 'N1: afterwards the machine is empty, the task original and the bin folder (probe copy, request) empty' (($w.Filters.Count + $w.SubLayers.Count + $w.Providers.Count) -eq 0 -and (Get-Nep5TaskState -Ops $c.TaskOps) -eq 'original' -and @(Get-Nep5BinResidue -BinDir $c.BinDir).Count -eq 0)
        $r4 = Invoke-Nep5Phase -Ctx $c -Phase 'taskcheck'
        Chk 'taskcheck: the identity probe returns the account''s token SID; the task is restored; exit 0' (($r4.ExitCode -eq 0) -and $r4.Records[0].class -eq 'ok' -and (Get-Nep5TaskState -Ops $c.TaskOps) -eq 'original')
    } finally { Remove-Item -LiteralPath $c.Tmp -Recurse -Force -ErrorAction SilentlyContinue }

    Write-Host '== cycles that must stop, refuse or fail closed ==' -ForegroundColor Cyan
    $c = New-N5TestCtx
    try {
        $c.AccountRun = New-Nep5FakeAccountRun -World $c.World -Invalid $true
        $r = Invoke-Nep5Phase -Ctx $c -Phase 'halfset' -ErrorAction Stop
        Chk 'control: an account probe that runs as the WRONG SID (or gives no valid result) fails the control: class control_failed, exit 5, nothing added (no install, no AddSet), and the phase stops after the first state' (($r.ExitCode -eq 5) -and $r.Records[0].class -eq 'control_failed' -and @($c.Runner.State.Calls | Where-Object { $_ -like 'install*' }).Count -eq 0 -and @($c.Backend.Calls | Where-Object { $_ -like 'addset*' }).Count -eq 0 -and $r.Records.Count -eq 1)
    } finally { Remove-Item -LiteralPath $c.Tmp -Recurse -Force -ErrorAction SilentlyContinue }
    $c = New-N5TestCtx
    try {
        $c.AccountRun = New-Nep5FakeAccountRun -World $c.World -IgnoreBlocks $false
        $c.OperatorProbe = { [pscustomobject]@{ ok = $false; ms = 1; error = 'offline'; t = '' } }
        $r = Invoke-Nep5Phase -Ctx $c -Phase 'halfset'
        Chk 'control: the operator offline (three failed outside connects) fails the control before anything is added: exit 5' (($r.ExitCode -eq 5) -and $r.Records[0].class -eq 'control_failed' -and $c.World.Filters.Count -eq 0)
    } finally { Remove-Item -LiteralPath $c.Tmp -Recurse -Force -ErrorAction SilentlyContinue }
    $c = New-N5TestCtx
    try {
        $k = 0; $c.OperatorProbe = { $script:__opN++; [pscustomobject]@{ ok = ($script:__opN -le 3); ms = 1; error = 'dropped'; t = '' } }; $script:__opN = 0
        $r = Invoke-Nep5Phase -Ctx $c -Phase 'halfset' -ErrorAction Stop
        $first = $r.Records[0]
        Chk 'operator watchdog: the control passes (3 connects) then every later outside connect fails: two in a row during the state abort it: class operator_abort, exit 9, removed by key, the direct checks after read clean, the phase stops' (($r.ExitCode -eq 9) -and $first.class -eq 'operator_abort' -and $first.steps.sweep_after.clean -and ($c.World.Filters.Count + $c.World.SubLayers.Count + $c.World.Providers.Count) -eq 0 -and $r.Records.Count -eq 1)
    } finally { Remove-Item -LiteralPath $c.Tmp -Recurse -Force -ErrorAction SilentlyContinue }
    $c = New-N5TestCtx
    try {
        $fk = 'eeeeeeee-0000-4d8e-9a31-2b6d4c8e0001'; $c.World.Filters[$fk] = [pscustomobject]@{ Key = $fk; SubLayer = '11111111-2222-3333-4444-555555555555'; Layer = 'v4'; Name = 'srt-win-v4-block-user'; Kind = 'block-user'; Tool = 'srt-win'; Sid = $sidS; HasUser = $true; Action = 'block' }
        $r = Invoke-Nep5Phase -Ctx $c -Phase 'halfset'
        Chk 'stop: a filter of srt-win''s outside S1/S2/S3 stops the very first cycle: class stop, exit 9, nothing added and the foreign filter is left alone (never cleaned)' (($r.ExitCode -eq 9) -and $r.Records[0].class -eq 'stop' -and $c.World.Filters.Count -eq 1 -and $c.World.Filters.ContainsKey($fk) -and @($c.Runner.State.Calls | Where-Object { $_ -like 'install*' -or $_ -like 'delete*' }).Count -eq 0) 'sweep-finds-foreign-sublayer'
    } finally { Remove-Item -LiteralPath $c.Tmp -Recurse -Force -ErrorAction SilentlyContinue }
    $c = New-N5TestCtx
    try {
        $c.World.Filters['ffffffff-0000-4d8e-9a31-2b6d4c8e0001'] = [pscustomobject]@{ Key = 'ffffffff-0000-4d8e-9a31-2b6d4c8e0001'; SubLayer = $s2; Layer = 'v4'; Name = 'BlarAI #1763 leftover'; Kind = ''; Tool = ''; Sid = $sidS; HasUser = $true; Action = 'block' }
        $r = Invoke-Nep5Phase -Ctx $c -Phase 'ours'
        Chk 'refuse: leftovers in S2 make the sweep before the add not clean: class refused, nothing added over them, the leftover is untouched, exit 2' (($r.ExitCode -eq 2) -and $r.Records[0].class -eq 'refused' -and $c.World.Filters.Count -eq 1 -and @($c.Backend.Calls | Where-Object { $_ -like 'addset*' }).Count -eq 0 -and @($c.Backend.Calls | Where-Object { $_ -like 'delete*' }).Count -eq 0)
    } finally { Remove-Item -LiteralPath $c.Tmp -Recurse -Force -ErrorAction SilentlyContinue }
    $c = New-N5TestCtx
    try {
        $c.Exporter = New-Nep5FakeExporter -World $c.World -Extra '<x>BlarAI #1763</x>'
        $r = Invoke-Nep5Phase -Ctx $c -Phase 'ours'
        Chk 'refuse: an export hit alone (enumeration empty) refuses the add: the sweep is not clean' (($r.Records[0].class -eq 'refused') -and $c.World.Filters.Count -eq 0 -and @($c.Backend.Calls | Where-Object { $_ -like 'addset*' }).Count -eq 0)
    } finally { Remove-Item -LiteralPath $c.Tmp -Recurse -Force -ErrorAction SilentlyContinue }
    $c = New-N5TestCtx
    try {
        $c.Proof = [pscustomobject]@{ Kind = 'Nep5Proof'; Ok = $true; Nonce = 'wrong' }
        $r = Invoke-Nep5Phase -Ctx $c -Phase 'ours'
        Chk 'proof gate through the whole cycle: a token with the wrong nonce makes the state refuse to add (class refused), the control having run first; nothing is in the machine afterwards' (($r.Records[0].class -eq 'refused') -and $r.Records[0].steps.add.Reason -match 'no valid rollback' -and $c.World.Filters.Count -eq 0 -and $c.World.Providers.Count -eq 0)
    } finally { Remove-Item -LiteralPath $c.Tmp -Recurse -Force -ErrorAction SilentlyContinue }
    $c = New-N5TestCtx
    try {
        $c.Only = @('O1')
        $stuckKey = $script:N5FilterKeys['s2-block-v4']
        $c.Runner = New-FakeHalfset -World $c.World -FailDeleteFilter @($stuckKey); $c.Backend = New-Nep5FakeBackend -World $c.World -FailDelete @($stuckKey)
        $r = Invoke-Nep5Phase -Ctx $c -Phase 'ours'
        Chk 'removal unverified: a filter that cannot be deleted makes the cycle removal_unverified (the direct checks read it back), exit 7, and the phase does not go on to the next state' (($r.ExitCode -eq 7) -and $r.Records[0].class -eq 'removal_unverified' -and -not $r.Records[0].steps.sweep_after.clean -and $r.Records.Count -eq 1 -and $c.World.Filters.ContainsKey($stuckKey))
    } finally { Remove-Item -LiteralPath $c.Tmp -Recurse -Force -ErrorAction SilentlyContinue }
    $c = New-N5TestCtx
    try {
        $c.AccountRun = New-Nep5FakeAccountRun -World $c.World -AllowAdd $true
        $r = Invoke-Nep5Phase -Ctx $c -Phase 'n1'
        Chk 'N1 finding (engine-denial lock OFF: the account''s token is allowed to write): the account''s ADD succeeds -> class finding_stop, exit 9, everything removed by key, the direct checks read clean, task and bin folder restored' (($r.ExitCode -eq 9) -and $r.Records[0].class -eq 'finding_stop' -and $r.Records[0].reason -match 'ADDED' -and ($c.World.Filters.Count + $c.World.SubLayers.Count + $c.World.Providers.Count) -eq 0 -and (Get-Nep5TaskState -Ops $c.TaskOps) -eq 'original' -and @(Get-Nep5BinResidue -BinDir $c.BinDir).Count -eq 0)
    } finally { Remove-Item -LiteralPath $c.Tmp -Recurse -Force -ErrorAction SilentlyContinue }
    $c = New-N5TestCtx
    try {
        $hw = $c.World
        $c.AccountRun = New-Nep5FakeAccountRun -World $hw -AllowDelete $true
        $r = Invoke-Nep5Phase -Ctx $c -Phase 'n1'
        Chk 'N1 finding: the add is denied but the direct DELETE of our test filter succeeds -> finding_stop, exit 9, everything removed' (($r.ExitCode -eq 9) -and $r.Records[0].class -eq 'finding_stop' -and $r.Records[0].reason -match 'DELETED' -and ($hw.Filters.Count + $hw.SubLayers.Count + $hw.Providers.Count) -eq 0)
    } finally { Remove-Item -LiteralPath $c.Tmp -Recurse -Force -ErrorAction SilentlyContinue }
    $c = New-N5TestCtx
    try {
        $c.AccountRun = New-Nep5FakeAccountRun -World $c.World -DirectOverride ([pscustomobject]@{ phase = 'open'; rc_hex = '0x00000005'; verdict = 'open_failed' })
        $r = Invoke-Nep5Phase -Ctx $c -Phase 'n1'
        Chk 'N1: an engine OPEN that fails (a denial before any write) is NOT a write verdict: class inconclusive, exit 4, never read as "denied"' (($r.ExitCode -eq 4) -and $r.Records[0].class -eq 'inconclusive' -and $r.Records[0].steps.n1_add.class -eq 'other')
    } finally { Remove-Item -LiteralPath $c.Tmp -Recurse -Force -ErrorAction SilentlyContinue }
    $c = New-N5TestCtx
    try {
        $c.AccountRun = New-Nep5FakeAccountRun -World $c.World -DirectOverride ([pscustomobject]@{ phase = 'call'; rc_hex = '0x80320007'; verdict = 'other' })
        $r = Invoke-Nep5Phase -Ctx $c -Phase 'n1'
        Chk 'N1: any call status other than access denied (here sublayer-not-found) is recorded verbatim and is inconclusive, never "denied"' (($r.ExitCode -eq 4) -and $r.Records[0].steps.n1_add.code -match '0x80320007')
    } finally { Remove-Item -LiteralPath $c.Tmp -Recurse -Force -ErrorAction SilentlyContinue }
    $c = New-N5TestCtx
    try {
$c.AcctSw.FailSet = $true
        $r = Invoke-Nep5Phase -Ctx $c -Phase 'halfset'
        Chk 'session: when the password write fails the phase is refused before ANY filter exists (exit 2); the half-applied write counts as changed, so the task is re-provisioned and proven and the session record is gone' (($r.ExitCode -eq 2) -and $r.Records[0].state -eq 'session' -and $c.World.Filters.Count -eq 0 -and @($c.Backend.Calls | Where-Object { $_ -like 'addset*' }).Count -eq 0 -and $c.RepSw.Count -eq 1 -and -not (Test-Path (Get-Nep5SessionMarkerPath -Ctx $c)) -and -not $c.AccountOps.Changed) 'restore-proof'
        $c.TaskOps = New-Nep5FakeTaskOps -Initial 'powershell -File somebody-elses.ps1'; $c.AcctSw.FailSet = $false; $nset = $c.AcctSw.Sets.Count
        $r = Invoke-Nep5Phase -Ctx $c -Phase 'taskcheck'
        Chk 'session: a task whose arguments are not recognised is refused and left exactly as found: no password was set' (($r.ExitCode -eq 2) -and $c.TaskOps.Args -eq 'powershell -File somebody-elses.ps1' -and $c.AcctSw.Sets.Count -eq $nset)
    } finally { Remove-Item -LiteralPath $c.Tmp -Recurse -Force -ErrorAction SilentlyContinue }
    $c = New-N5TestCtx
    try {
$c.RepSw.Fail = $true
        $r = Invoke-Nep5Phase -Ctx $c -Phase 'taskcheck'
        Chk 'session: when spike-provision fails the task is NOT restored: class task_not_restored, exit 9, the record names the manual command, the session record stays (so -Remove re-provisions), no taskcheck record is written' (($r.ExitCode -eq 9) -and $r.Records[0].class -eq 'task_not_restored' -and $r.Records[0].reason -match 'fake manual command' -and $r.Records[0].reason -match 'ForceNewPassword' -and (Test-Path (Get-Nep5SessionMarkerPath -Ctx $c)) -and -not (Test-Path (Get-Nep5MarkerPath -Ctx $c))) 'restore-proof'
    } finally { Remove-Item -LiteralPath $c.Tmp -Recurse -Force -ErrorAction SilentlyContinue }
    $c = New-N5TestCtx
    try {
        $c.Only = @('R1', 'R2'); $c.Passes = 3
        $r = Invoke-Nep5Phase -Ctx $c -Phase 'halfset'
        Chk '-Only and -Passes: two states x three passes run in the fixed order R1 p1..p3, R2 p1..p3, each pass with its own sweep before and after' (($r.Records.Count -eq 6) -and ((@($r.Records | ForEach-Object { "$($_.state)p$($_.pass)" })) -join ',') -eq 'R1p1,R1p2,R1p3,R2p1,R2p2,R2p3' -and @($r.Records | Where-Object { $_.steps.sweep_before.clean -and $_.steps.sweep_after.clean }).Count -eq 6)
    } finally { Remove-Item -LiteralPath $c.Tmp -Recurse -Force -ErrorAction SilentlyContinue }
    $c = New-N5TestCtx
    try {
        $c.Bound = @{}; foreach ($t in (Get-Nep5Targets -Bound @{})) { $c.Bound[$t.Key] = ($t.Family -eq 'v4') }
        $c.Only = @('R1'); $r = Invoke-Nep5Phase -Ctx $c -Phase 'halfset'
        Chk 'IPv6 listener not bound: the v6 rows are NOT RUN (listed, never "blocked"), the v4 rows run, the cycle completes' (($r.ExitCode -eq 0) -and (@($r.Records[0].steps.during.account.NotRun).Count -eq 3) -and ($r.Records[0].steps.during.account.Summary.Keys.Count -eq 3) -and (@($r.Records[0].steps.during.account.NotRun | Where-Object { $_ -match 'v6' }).Count -eq 3) -and ($r.Records[0].summary -match 'NOT RUN: v6:61763, v6:61764, v6:60085'))
    } finally { Remove-Item -LiteralPath $c.Tmp -Recurse -Force -ErrorAction SilentlyContinue }

    Write-Host '== the task restore proof, the taskcheck gate, the run core (pre-cleanup lock on the entry point), the listener backlog ==' -ForegroundColor Cyan
$xmlA = "<Task xmlns=`"x`">`r`n  <RegistrationInfo><Date>2026-10-01T10:00:00</Date><Author>someone</Author><URI>\\BlarAI\\t</URI><Description>d</Description></RegistrationInfo>`r`n  <Principals><Principal id=`"Author`"><UserId>S-1-5-21-1-2-3-1271</UserId><LogonType>Password</LogonType><RunLevel>LeastPrivilege</RunLevel></Principal></Principals>`r`n  <Settings><MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy><ExecutionTimeLimit>PT30M</ExecutionTimeLimit><Enabled>true</Enabled></Settings>`r`n  <Actions><Exec><Command>powershell.exe</Command><Arguments>-File a.ps1</Arguments><WorkingDirectory>C:\w</WorkingDirectory></Exec></Actions>`r`n</Task>"
    $xmlB = $xmlA -replace '2026-10-01T10:00:00', '2026-10-12T20:00:00' -replace 'someone', 'else' -replace '<Description>d', '<Description>other'
    $nA = ConvertTo-Nep5NormalizedTaskXml $xmlA
    Chk 'task XML: the normaliser keeps principal, logon type, run level, action and settings, and EXCLUDES date, author, URI and description, so a re-registration with only those changed is equal' (($nA -ceq (ConvertTo-Nep5NormalizedTaskXml $xmlB)) -and ($nA -match 'LogonType=Password') -and ($nA -match 'Arguments=-File a.ps1') -and ($nA -match 'Triggers=0') -and ($nA -notmatch 'someone'))
    $differ = @(($xmlA -replace 'Password', 'InteractiveToken'), ($xmlA -replace '-File a.ps1', '-File b.ps1'), ($xmlA -replace 'LeastPrivilege', 'HighestAvailable'), ($xmlA -replace 'C:\\w', 'C:\\x'), ($xmlA -replace 'PT30M', 'PT1H'), ($xmlA -replace '-1271', '-1272')) | ForEach-Object { (ConvertTo-Nep5NormalizedTaskXml $_) -cne $nA }
    Chk 'task XML (negative controls): a changed LogonType, arguments, RunLevel, working folder, time limit or user is NOT equal; text that is not XML normalises to $null' ((@($differ | Where-Object { -not $_ }).Count -eq 0) -and ($null -eq (ConvertTo-Nep5NormalizedTaskXml 'not xml <<')))
    $c = New-N5TestCtx
    try {
        $r = Invoke-Nep5Phase -Ctx $c -Phase 'taskcheck'; $ex = $r.Records[0].steps.session_exit
        Chk 'taskcheck: the task is restored AND PROVEN: arguments original, the whole definition equals the baseline recorded before the first change, and the restored task started as the account in its original form; the baseline file and the passed-record are written' (($r.ExitCode -eq 0) -and $r.Records[0].class -eq 'ok' -and $ex.TaskRestored -and $ex.DefinitionMatches -eq $true -and $ex.StartedInOriginalForm.Ok -and (Test-Path (Get-Nep5TaskBaselinePath -Ctx $c)) -and (Test-Path (Get-Nep5MarkerPath -Ctx $c)) -and $r.Records[0].reason -match 'PROVEN')
    } finally { Remove-Item -LiteralPath $c.Tmp -Recurse -Force -ErrorAction SilentlyContinue }
    $c = New-N5TestCtx
    try {
        $c.RepSw.Damage = $true
        $r = Invoke-Nep5Phase -Ctx $c -Phase 'taskcheck'; $rec = $r.Records[0]
        Chk 'taskcheck: a restore that puts the arguments back but changes the task''s definition (as a dropped credential would) is class task_not_restored, exit 9, names the re-key command, and the passed-record is removed' (($r.ExitCode -eq 9) -and $rec.class -eq 'task_not_restored' -and (Get-Nep5TaskState -Ops $c.TaskOps) -eq 'original' -and $rec.steps.session_exit.DefinitionMatches -eq $false -and $rec.reason -match 'ForceNewPassword' -and -not (Test-Path (Get-Nep5MarkerPath -Ctx $c)))
        $hN = @($c.Runner.State.Calls).Count; $bN = @($c.Backend.Calls).Count
        $r2 = Invoke-Nep5Phase -Ctx $c -Phase 'halfset'
        Chk 'gate: after a task_not_restored no other phase runs (class refused, exit 2, nothing added, nothing removed, the harness and the engine not called again)' (($r2.ExitCode -eq 2) -and $r2.Records[0].state -eq 'taskcheck_required' -and $c.World.Filters.Count -eq 0 -and @($c.Runner.State.Calls).Count -eq $hN -and @($c.Backend.Calls).Count -eq $bN)
    } finally { Remove-Item -LiteralPath $c.Tmp -Recurse -Force -ErrorAction SilentlyContinue }
    $c = New-N5TestCtx
    try {
        $c.OriginalTaskRun = { param($rid) [pscustomobject]@{ valid = $false; token_sid = $null; task_start = [pscustomobject]@{ Detail = 'task never started (LastTaskResult=0x8007052E)' } } }
        $r = Invoke-Nep5Phase -Ctx $c -Phase 'taskcheck'; $rec = $r.Records[0]; $ex = $rec.steps.session_exit
        Chk 'taskcheck: arguments original AND definition identical but the restored task does NOT start as the account: still task_not_restored, exit 9 (a restore is never claimed from strings and XML alone)' (($r.ExitCode -eq 9) -and $rec.class -eq 'task_not_restored' -and $ex.TaskNow -eq 'original' -and $ex.DefinitionMatches -eq $true -and -not $ex.TaskRestored -and $rec.reason -match '0x8007052E' -and -not (Test-Path (Get-Nep5MarkerPath -Ctx $c)))
    } finally { Remove-Item -LiteralPath $c.Tmp -Recurse -Force -ErrorAction SilentlyContinue }
    $c = New-N5TestCtx
    try {
        $c.OriginalTaskRun = { param($rid) [pscustomobject]@{ valid = $true; token_sid = 'S-1-5-21-1-2-3-1001'; task_start = $null } }
        $r = Invoke-Nep5Phase -Ctx $c -Phase 'taskcheck'
        Chk 'taskcheck: a restored task that starts as the WRONG account is not a restore either (exit 9)' (($r.ExitCode -eq 9) -and $r.Records[0].class -eq 'task_not_restored')
    } finally { Remove-Item -LiteralPath $c.Tmp -Recurse -Force -ErrorAction SilentlyContinue }
    $c = New-N5TestCtx
    try {
        $c.TaskOps = New-Nep5FakeTaskOps -SnapFail $true
        $r = Invoke-Nep5Phase -Ctx $c -Phase 'taskcheck'
        Chk 'session: if the task definition cannot be read (Export-ScheduledTask fails) the session is refused BEFORE anything is set: exit 2, no password set, no re-provision, no files' (($r.ExitCode -eq 2) -and $c.AcctSw.Sets.Count -eq 0 -and $c.RepSw.Count -eq 0 -and @(Get-Nep5BinResidue -BinDir $c.BinDir).Count -eq 0)
    } finally { Remove-Item -LiteralPath $c.Tmp -Recurse -Force -ErrorAction SilentlyContinue }
    $c = New-N5TestCtx
    try {
        [IO.File]::WriteAllText((Get-Nep5TaskBaselinePath -Ctx $c), "<Task>`n<Principal>logon=somebody-elses</Principal>`n</Task>")
        $r = Invoke-Nep5Phase -Ctx $c -Phase 'taskcheck'
        Chk 'session: a task whose definition already differs from the recorded baseline is refused with nothing changed (exit 2, no password set)' (($r.ExitCode -eq 2) -and $r.Records[0].reason -match 'differs from the baseline' -and $c.AcctSw.Sets.Count -eq 0 -and $c.RepSw.Count -eq 0)
    } finally { Remove-Item -LiteralPath $c.Tmp -Recurse -Force -ErrorAction SilentlyContinue }
    $c = New-N5TestCtx
    try {
$null = Invoke-Nep5Phase -Ctx $c -Phase 'taskcheck'
        Write-JsonGuarded -Path (Get-Nep5SessionMarkerPath -Ctx $c) -Object ([ordered]@{ kind = 'nep5-session-open'; at = (Get-N5Now) }) -Depth 3
        $nset = $c.AcctSw.Sets.Count; $repN = $c.RepSw.Count
        $r = Invoke-Nep5Phase -Ctx $c -Phase 'halfset'
        Chk 'session: an open session record (a run died after setting the password) blocks every new session: refused, no password set, nothing added' (($r.ExitCode -eq 2) -and $c.AcctSw.Sets.Count -eq $nset -and $c.World.Filters.Count -eq 0 -and ($r.Records[0].reason -match 'previous session' -or $r.Records[0].steps.session.Reason -match 'previous session'))
        $c.AccountOps.Changed = $true
        $exF = Exit-Nep5AccountSession -Ctx $c
        Chk 'session: -Remove''s path (Changed forced, Exit) re-provisions, proves the restore (exit proof Ok) and removes the session record' ($exF.TaskRestored -and $exF.Ok -and $c.RepSw.Count -eq ($repN + 1) -and -not (Test-Path (Get-Nep5SessionMarkerPath -Ctx $c)) -and -not $c.AccountOps.Changed) 'restore-proof'
    } finally { Remove-Item -LiteralPath $c.Tmp -Recurse -Force -ErrorAction SilentlyContinue }
    $c = New-N5TestCtx
    try {
        $exNo = Exit-Nep5AccountSession -Ctx $c
        Chk 'exit proof: with no baseline anywhere the exit reads the arguments back but says the restore is NOT PROVEN (TaskRestored false); the start check is not even attempted' ((-not $exNo.TaskRestored) -and $exNo.RestoreWhy -match 'NOT PROVEN' -and $exNo.TaskNow -eq 'original' -and $null -eq $exNo.StartedInOriginalForm)
    } finally { Remove-Item -LiteralPath $c.Tmp -Recurse -Force -ErrorAction SilentlyContinue }
    $c = New-N5TestCtx -NoMarker
    try {
        $r = Invoke-Nep5Phase -Ctx $c -Phase 'halfset'
        Chk 'gate: with no taskcheck record no other phase runs: class refused, exit 2, the harness and the engine never touched' (($r.ExitCode -eq 2) -and $r.Records[0].state -eq 'taskcheck_required' -and @($c.Runner.State.Calls).Count -eq 0 -and @($c.Backend.Calls).Count -eq 0 -and $c.AcctSw.Sets.Count -eq 0 -and $c.RepSw.Count -eq 0)
        Write-JsonGuarded -Path (Get-Nep5MarkerPath -Ctx $c) -Object ([ordered]@{ kind = 'nep5-taskcheck-passed'; at = (Get-N5Now); proof_stamp = '2026-10-13T10:26:45.1234567-04:00'; definition_matches_baseline = $true; restored_task_started = $true })
        $mOther = @(Test-Nep5TaskcheckMarker -Ctx $c)
        Write-JsonGuarded -Path (Get-Nep5MarkerPath -Ctx $c) -Object ([ordered]@{ kind = 'nep5-taskcheck-passed'; at = (Get-Date).AddHours(-25).ToString("yyyy-MM-dd'T'HH:mm:ss.fffzzz"); proof_stamp = '2026-10-13T10:26:44.1234567-04:00'; definition_matches_baseline = $true; restored_task_started = $true })
        $mOld = @(Test-Nep5TaskcheckMarker -Ctx $c)
        Write-JsonGuarded -Path (Get-Nep5MarkerPath -Ctx $c) -Object ([ordered]@{ kind = 'nep5-taskcheck-passed'; at = (Get-N5Now); proof_stamp = '2026-10-13T10:26:44.1234567-04:00'; definition_matches_baseline = $true; restored_task_started = $false })
        $mNoStart = @(Test-Nep5TaskcheckMarker -Ctx $c)
        Write-JsonGuarded -Path (Get-Nep5MarkerPath -Ctx $c) -Object ([ordered]@{ kind = 'nep5-taskcheck-passed'; at = (Get-N5Now); proof_stamp = '2026-10-13T10:26:44.1234567-04:00'; definition_matches_baseline = $true; restored_task_started = $true })
        Chk 'gate: a taskcheck record from another matrix proof, one older than 24 h, and one that does not show a started restored task are each refused; a current one is accepted' (($mOther.Count -ge 1) -and ($mOld.Count -ge 1) -and ($mNoStart.Count -ge 1) -and (@(Test-Nep5TaskcheckMarker -Ctx $c).Count -eq 0))
    } finally { Remove-Item -LiteralPath $c.Tmp -Recurse -Force -ErrorAction SilentlyContinue }
    # the run core: the entry point's removal decision
    $fe = { param($c0) $e = $c0.Exporter; $e }
    $c = New-N5TestCtx
    try {
        $c.Only = @('R0'); $core = Invoke-Nep5RunCore -Ctx $c -Phase 'halfset' -FinalExporter $c.Exporter
        Chk 'run core: a run that got past the pre-cleanup removes by key in its finally and ends with a clean final sweep: exit 0, Removed true' (($core.Code -eq 0) -and $core.Removed -and $core.PastPreCleanup -and $core.Final.clean)
    } finally { Remove-Item -LiteralPath $c.Tmp -Recurse -Force -ErrorAction SilentlyContinue }
    $c = New-N5TestCtx
    try {
        $null = & $c.Runner @('install', '--sublayer', $s1, '--sid', $script:N5StaleSid, '--live', 'x'); $c.Only = @('R0'); $w = $c.World
        $callsH = @($c.Runner.State.Calls).Count; $callsB = @($c.Backend.Calls).Count
        $core = Invoke-Nep5RunCore -Ctx $c -Phase 'halfset' -FinalExporter $c.Exporter
        $newH = @($c.Runner.State.Calls | Select-Object -Skip $callsH); $newB = @($c.Backend.Calls | Select-Object -Skip $callsB)
        Chk 'run core (ENTRY POINT lock): when the pre-cleanup REFUSES (a set for another SID) the run removes NOTHING: exit 2, Removed false, the four filters still there, no uninstall and no delete reached the harness or the engine; the final sweep is read-only' (($core.Code -eq 2) -and (-not $core.Removed) -and (-not $core.PastPreCleanup) -and $w.Filters.Count -eq 4 -and @($newH | Where-Object { $_ -like 'uninstall*' -or $_ -like 'delete*' }).Count -eq 0 -and @($newB | Where-Object { $_ -like 'delete*' -or $_ -like 'addset*' }).Count -eq 0 -and $core.Final -and (-not $core.Final.clean)) 'pre-cleanup'
    } finally { Remove-Item -LiteralPath $c.Tmp -Recurse -Force -ErrorAction SilentlyContinue }
    $c = New-N5TestCtx
    try {
        $null = & $c.Runner @('install', '--sublayer', $s1, '--sid', $sidS, '--live', 'x'); $c.Only = @('R0'); $w = $c.World
        $fk = 'cccccccc-0000-4d8e-9a31-2b6d4c8e0003'; $w.Filters[$fk] = [pscustomobject]@{ Key = $fk; SubLayer = '11111111-2222-3333-4444-555555555555'; Layer = 'v4'; Name = 'srt-win-v4-block-user'; Kind = 'block-user'; Tool = 'srt-win'; Sid = $sidS; HasUser = $true; Action = 'block' }
        $callsB = @($c.Backend.Calls).Count
        $core = Invoke-Nep5RunCore -Ctx $c -Phase 'halfset' -FinalExporter $c.Exporter
        Chk 'run core: when the pre-cleanup STOPS (a foreign srt-win filter) the run removes nothing (exit 9, the set and the foreign filter both still there, no delete reached the engine)' (($core.Code -eq 9) -and (-not $core.Removed) -and $w.Filters.Count -eq 5 -and @($c.Backend.Calls | Select-Object -Skip $callsB | Where-Object { $_ -like 'delete*' }).Count -eq 0) 'pre-cleanup'
    } finally { Remove-Item -LiteralPath $c.Tmp -Recurse -Force -ErrorAction SilentlyContinue }
    $c = New-N5TestCtx -NoMarker
    try {
        $null = & $c.Runner @('install', '--sublayer', $s1, '--sid', $sidS, '--live', 'x'); $w = $c.World
        $core = Invoke-Nep5RunCore -Ctx $c -Phase 'halfset' -FinalExporter $c.Exporter
        Chk 'run core: a run refused by the taskcheck gate also removes nothing (exit 2; the leftover set is untouched)' (($core.Code -eq 2) -and (-not $core.Removed) -and $w.Filters.Count -eq 4)
    } finally { Remove-Item -LiteralPath $c.Tmp -Recurse -Force -ErrorAction SilentlyContinue }
    $c = New-N5TestCtx
    try {
        $c.Only = @('O1'); $stuckKey = $script:N5FilterKeys['s2-block-v4']
        $c.Runner = New-FakeHalfset -World $c.World -FailDeleteFilter @($stuckKey); $c.Backend = New-Nep5FakeBackend -World $c.World -FailDelete @($stuckKey)
        $core = Invoke-Nep5RunCore -Ctx $c -Phase 'ours' -FinalExporter $c.Exporter
        Chk 'run core: a leftover after a run that got past the pre-cleanup is exit 7 from the final direct checks' (($core.Code -eq 7) -and $core.Removed -and (-not $core.Final.clean))
    } finally { Remove-Item -LiteralPath $c.Tmp -Recurse -Force -ErrorAction SilentlyContinue }
    $c = New-N5TestCtx
    try {
        $c.RepSw.Damage = $true; $c.Only = @('R0')
        $r1 = Invoke-Nep5Phase -Ctx $c -Phase 'halfset'
        Chk 'task_not_restored in an ordinary phase: the cycles ran, the restore failed its proof: exit 9 and the record names the re-key command; the next phase is refused' (($r1.ExitCode -eq 9) -and @($r1.Records | Where-Object { $_.class -eq 'task_not_restored' -and $_.reason -match 'ForceNewPassword' }).Count -eq 1 -and ((Invoke-Nep5Phase -Ctx $c -Phase 'ours').ExitCode -eq 2))
    } finally { Remove-Item -LiteralPath $c.Tmp -Recurse -Force -ErrorAction SilentlyContinue }
    $c = New-N5TestCtx
    try {
        $c.Only = @('R0'); $a1 = Invoke-Nep5Phase -Ctx $c -Phase 'halfset'; $a2 = Invoke-Nep5Phase -Ctx $c -Phase 'halfset'
        Chk 'results: two runs of the same phase with the same stamp write two different results files; the first is not overwritten' (($a1.ResultsPath -ne $a2.ResultsPath) -and (Test-Path $a1.ResultsPath) -and (Test-Path $a2.ResultsPath) -and ((Split-Path $a1.ResultsPath -Leaf) -match '^nep5-results-halfset-testrun'))
    } finally { Remove-Item -LiteralPath $c.Tmp -Recurse -Force -ErrorAction SilentlyContinue }
    # listeners: drained before each batch of connects; a timeout is never read as blocked
    Chk 'a timeout is recorded as timeout and never as blocked (both in the probe''s outcome mapping and the row verdict)' (((Get-Nep5RowVerdict ([pscustomobject]@{ result = 'timeout' })) -eq 'timeout') -and ((Get-Nep5RowVerdict ([pscustomobject]@{ result = 'blocked' })) -eq 'blocked') -and ((Get-Nep5RowVerdict ([pscustomobject]@{ result = 'refused' })) -eq 'refused') -and ((Get-Nep5RowVerdict ([pscustomobject]@{ result = 'error' })) -eq 'error'))
    $pb = & $free; $lsb = Start-Nep5Listeners -Ports @($pb)
    try {
        $okAll = $true; $drained = 0
        foreach ($round in 1..3) { foreach ($i in 1..150) { if (-not (Test-Nep5Loopback -Family v4 -Port $pb -TimeoutMs 1000).ok) { $okAll = $false } }; $drained += (Clear-Nep5Backlog $lsb) }
        Chk 'listeners: 450 connects in three batches of 150 with the accept queue drained between them all complete, and the drain returned what was queued' ($okAll -and $drained -ge 400)
        $bad = 0; foreach ($i in 1..260) { if (-not (Test-Nep5Loopback -Family v4 -Port $pb -TimeoutMs 150).ok) { $bad++ } }
        Write-Host ("  [INFO] the same listener WITHOUT draining: {0} of 260 connects failed (a full accept queue); {1}" -f $bad, $(if ($bad -gt 0) { 'this is the limit the drain exists for' } else { 'this machine''s queue did not fill in 260 connects' }))
        [void](Clear-Nep5Backlog $lsb)
    } finally { Stop-Nep5Listeners $lsb }
    $pc = & $free; $lsc = Start-Nep5Listeners -Ports @($pc)
    try {
        $c = New-N5TestCtx; $c.Only = @('R0'); $c.Listeners = $lsc
        try {
            [void](Test-Nep5Loopback -Family v4 -Port $pc -TimeoutMs 1000); [void](Test-Nep5Loopback -Family v4 -Port $pc -TimeoutMs 1000)
            $pendBefore = $lsc.Items[0].Listener.Pending()
            $script:__lsc = $lsc; $script:__pendAtControl = $null
            $c.OperatorConnect = { param($family, $port) if ($null -eq $script:__pendAtControl) { $script:__pendAtControl = $script:__lsc.Items[0].Listener.Pending() }; [pscustomobject]@{ ok = $true; ms = 1; error = '' } }
            $r = Invoke-Nep5Phase -Ctx $c -Phase 'halfset'
            Chk 'listeners: every cycle drains the accept queues BEFORE its control connects (connects queued earlier are gone when the first control connect is made, and after the phase)' ($pendBefore -and ($script:__pendAtControl -eq $false) -and -not $lsc.Items[0].Listener.Pending() -and $r.ExitCode -eq 0)
        } finally { Remove-Item -LiteralPath $c.Tmp -Recurse -Force -ErrorAction SilentlyContinue }
    } finally { Stop-Nep5Listeners $lsc }
    # fake export shape and the sublayer read
    $c = New-N5TestCtx
    try {
        $c.World.SubLayers[$s2] = ''; $c.World.Providers[(ConvertTo-N5Guid $script:N5ProviderKey)] = $true
        $txt = Get-FakeExportText -World $c.World -Extra ''
        $swE = Invoke-Nep5DirectSweep -Runner $c.Runner -Backend $c.Backend -Exporter $c.Exporter -Label 'shape'
        Chk 'export shape: a bare sublayer and a bare provider do not appear in the (fake, real-shaped) export; their absence is read by key, and the sweep still reads NOT clean for them' (((Get-N5ExportHits -Text $txt).total -eq 0) -and (-not $swE.Clean) -and (@($swE.NotClean) -match 'S2 sublayer is still present').Count -eq 1 -and (@($swE.NotClean) -match 'provider').Count -ge 1)
    } finally { Remove-Item -LiteralPath $c.Tmp -Recurse -Force -ErrorAction SilentlyContinue }
    # stale / orphaned harness proof
    $sd = Join-Path ([IO.Path]::GetTempPath()) ('nep5-stale-' + [guid]::NewGuid().ToString('N')); New-Item -ItemType Directory -Path $sd | Out-Null
    try {
        $hp = Join-Path $sd 'h.json'; $mp = Join-Path $sd 'm.json'
        $mkPair = { param($hlpText, $matrixObj) [IO.File]::WriteAllText($mp, (ConvertTo-Json -InputObject $matrixObj)); (Get-Item $mp).LastWriteTimeUtc = [datetime]::UtcNow.AddMinutes(-5); [IO.File]::WriteAllText($hp, $hlpText); (Get-Item $hp).LastWriteTimeUtc = [datetime]::UtcNow }
        $r0 = Remove-Nep5StaleHarnessProof -HarnessProof $hp -MatrixProof $mp
        & $mkPair 'harness-proof-bytes' ([ordered]@{ harness = [ordered]@{ live_proof_sha256 = '' } }); $good = Get-N5RawSha256 -Path $hp
        & $mkPair 'harness-proof-bytes' ([ordered]@{ harness = [ordered]@{ live_proof_sha256 = $good } }); $rCur = Remove-Nep5StaleHarnessProof -HarnessProof $hp -MatrixProof $mp; $curStill = Test-Path $hp
        & $mkPair 'harness-proof-bytes' ([ordered]@{ harness = [ordered]@{ live_proof_sha256 = 'AB' * 32 } }); $rHash = Remove-Nep5StaleHarnessProof -HarnessProof $hp -MatrixProof $mp; $hashGone = -not (Test-Path $hp)
        & $mkPair 'harness-proof-bytes' ([ordered]@{ harness = [ordered]@{ live_proof_sha256 = $good } }); (Get-Item $hp).LastWriteTimeUtc = [datetime]::UtcNow.AddHours(-1); $rOld = Remove-Nep5StaleHarnessProof -HarnessProof $hp -MatrixProof $mp; $oldGone = -not (Test-Path $hp)
        & $mkPair 'harness-proof-bytes' ([ordered]@{ harness = [ordered]@{ live_proof_sha256 = $good } }); Remove-Item $mp -Force; $rOrph = Remove-Nep5StaleHarnessProof -HarnessProof $hp -MatrixProof $mp; $orphGone = -not (Test-Path $hp)
        & $mkPair 'x' ([ordered]@{ a = 1 }); [IO.File]::WriteAllText($mp, '{not json'); $rBad = Remove-Nep5StaleHarnessProof -HarnessProof $hp -MatrixProof $mp; $badGone = -not (Test-Path $hp)
        Chk 'stale harness proof: none -> nothing to do; a current one (newer than the matrix proof, hash recorded) is kept; one whose hash the matrix proof did not record, one OLDER than the matrix proof, one with no matrix proof (orphaned) and one beside an unparseable matrix proof are each deleted' ((-not $r0.Removed) -and (-not $rCur.Removed) -and $curStill -and $rHash.Removed -and $hashGone -and $rOld.Removed -and $oldGone -and $rOrph.Removed -and $orphGone -and $rBad.Removed -and $badGone) 'harness-live-proof-binding'
    } finally { Remove-Item -LiteralPath $sd -Recurse -Force -ErrorAction SilentlyContinue }
    Chk '-Check exit: a task definition that differs from the baseline is "present" (21) even with everything else clean; an unknown comparison does not change a clean 20' (((Get-Nep5CheckExit -Sweep ([pscustomobject]@{ Stop = $false; Unreadable = $false; Clean = $true }) -TaskState 'original' -TaskDefMatch $false) -eq 21) -and ((Get-Nep5CheckExit -Sweep ([pscustomobject]@{ Stop = $false; Unreadable = $false; Clean = $true }) -TaskState 'original' -TaskDefMatch $null) -eq 20) -and ((Get-Nep5CheckExit -Sweep ([pscustomobject]@{ Stop = $false; Unreadable = $false; Clean = $true }) -TaskState 'original' -TaskDefMatch $true) -eq 20))

    Write-Host '== round-2 fixes: fixed task-record location, staged harness proof, residue-only removal ==' -ForegroundColor Cyan
    $c = New-N5TestCtx
    try {
        $r = Invoke-Nep5Phase -Ctx $c -Phase 'taskcheck'
        Chk 'R2-1: the task baseline and the taskcheck record are written at the FIXED location (beside the proof), and nothing of either is written to the -OutDir folder' ((Test-Path (Join-Path $c.FixedDir 'task-baseline-1763-v2.xml')) -and (Test-Path (Join-Path $c.FixedDir 'taskcheck-passed-1763.json')) -and -not (Test-Path (Join-Path $c.OutDir 'task-baseline-1763-v2.xml')) -and -not (Test-Path (Join-Path $c.OutDir 'taskcheck-passed-1763.json')) -and $r.ExitCode -eq 0)
        $c2 = $c | Select-Object *; $c2.OutDir = Join-Path $c.Tmp 'other-out'; New-Item -ItemType Directory -Path $c2.OutDir | Out-Null
        Chk 'R2-1: a different -OutDir does not lose the baseline or the record (both are found at the fixed location; the marker test passes)' ((@(Test-Nep5TaskcheckMarker -Ctx $c2).Count -eq 0) -and ($null -ne (Get-Nep5TaskBaseline -Ctx ([pscustomobject]@{ OutDir = $c2.OutDir; FixedDir = $c.FixedDir }))))
        [IO.File]::WriteAllText((Join-Path $c.OutDir 'task-baseline-1763-v2.xml'), 'a different copy')
        $hN = @($c.Runner.State.Calls).Count; $bN = @($c.Backend.Calls).Count
        $rm = Invoke-Nep5Phase -Ctx $c -Phase 'halfset'
        Chk 'R2-1: a baseline in -OutDir that differs from the fixed one is exit 9 (class task_files_mismatch), and nothing runs: no harness call, no engine call, no password set' (($rm.ExitCode -eq 9) -and $rm.Records[0].class -eq 'task_files_mismatch' -and @($c.Runner.State.Calls).Count -eq $hN -and @($c.Backend.Calls).Count -eq $bN)
        Remove-Item (Join-Path $c.FixedDir 'task-baseline-1763-v2.xml') -Force
        $mmOnly = @(Test-Nep5TaskFileLocations -Ctx $c)
        Chk 'R2-1: a baseline in -OutDir with none at the fixed location is a mismatch too (the records were moved)' ($mmOnly.Count -ge 1 -and $mmOnly[0] -match 'not at the fixed location')
        Remove-Item (Join-Path $c.OutDir 'task-baseline-1763-v2.xml') -Force
        Chk 'R2-1: with no record in either place there is no mismatch' (@(Test-Nep5TaskFileLocations -Ctx $c).Count -eq 0)
    } finally { Remove-Item -LiteralPath $c.Tmp -Recurse -Force -ErrorAction SilentlyContinue }
    $remText = (& { $selfAst2 = [Management.Automation.Language.Parser]::ParseFile($PSCommandPath, [ref]$null, [ref]$null); ($selfAst2.FindAll({ param($n) $n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq 'Invoke-Remove' }, $true) | Select-Object -First 1).Extent.Text })
    $remText += "`n" + ([Management.Automation.Language.Parser]::ParseFile((Join-Path $PSScriptRoot 'spike-nep5-run-lib.ps1'), [ref]$null, [ref]$null).Find({ param($n) $n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq 'Resolve-Nep5RemoveTask' }, $true)).Extent.Text
    Chk 'R2-1: -Remove never prints PROVEN for the branch where the task was not touched; it prints TASK NEVER CHANGED BY THIS MATRIX (no baseline on record) and still looks at the arguments first' (($remText -match 'TASK NEVER CHANGED BY THIS MATRIX \(no baseline on record\)') -and ($remText -notmatch 'or the task was never changed') -and ($remText -match "\`$argsNow -ne 'original'") -and ($remText -match 'TASK RECORDS MISMATCH') -and ($remText -match 'return 9'))
    Chk 'R2-4: -Remove with no baseline never prints the re-key line (it is printed only when a baseline exists); with residue alone it removes the residue and prints that result' (($remText -match 'if \(\$hasBase -or \$hasSession\)') -and ($remText -match 'not a re-key case') -and ($remText -match 'Bin-folder residue removed'))
    $sg = Join-Path ([IO.Path]::GetTempPath()) ('nep5-stg-' + [guid]::NewGuid().ToString('N')); New-Item -ItemType Directory -Path $sg | Out-Null
    try {
        $hpS = Join-Path $sg 'harness-live-proof-1763.json'
        [IO.File]::WriteAllText("$hpS.staged", '{}'); [IO.File]::WriteAllText((Join-Path $sg 'other.staged'), '{}'); [IO.File]::WriteAllText((Join-Path $sg 'keep.json'), '{}'); [IO.File]::WriteAllText($hpS, '{}')
        $gone = @(Remove-Nep5StagedHarnessProof -HarnessProof $hpS)
        Chk 'R2-2: every *.staged file beside the harness proof is deleted; the proof itself and other files are not touched' (($gone.Count -eq 2) -and -not (Test-Path "$hpS.staged") -and -not (Test-Path (Join-Path $sg 'other.staged')) -and (Test-Path $hpS) -and (Test-Path (Join-Path $sg 'keep.json')) -and @(Remove-Nep5StagedHarnessProof -HarnessProof $hpS).Count -eq 0)
    } finally { Remove-Item -LiteralPath $sg -Recurse -Force -ErrorAction SilentlyContinue }
    $entryText = (Get-Content -LiteralPath $PSCommandPath -Raw)
    Chk 'R2-2: -Run, -Remove and -SelfTest -WriteProof each call the staged-proof cleaner before they stage or use a harness proof' ([regex]::Matches($entryText, 'Remove-Nep5StagedHarnessProof -HarnessProof \$HarnessLiveProof').Count -ge 3)

    Chk 'R3-1: the proof is accepted only from the scripts'' own folder (any case, trailing slash); another folder, a parent, a sub-folder and a sibling with the same name prefix are each refused' ((@(Test-Nep5ProofInFolder 'C:\x\live\p.json' 'C:\x\live').Count -eq 0) -and (@(Test-Nep5ProofInFolder 'c:\X\LIVE\p.json' 'C:\x\live\').Count -eq 0) -and (@(Test-Nep5ProofInFolder 'C:\x\other\p.json' 'C:\x\live').Count -eq 1) -and (@(Test-Nep5ProofInFolder 'C:\x\p.json' 'C:\x\live').Count -eq 1) -and (@(Test-Nep5ProofInFolder 'C:\x\live\sub\p.json' 'C:\x\live').Count -eq 1) -and (@(Test-Nep5ProofInFolder 'C:\x\live2\p.json' 'C:\x\live').Count -eq 1))
    $fxLine = @(Get-Content -LiteralPath $PSCommandPath | Where-Object { $_ -match '^\$FixedDir\s*=' })
    Chk 'R3-1: the fixed task-record folder is the scripts'' folder itself, set once, not derived from -ProofPath; the ProofPath default is set once' (($fxLine.Count -eq 1) -and ($fxLine[0] -match '^\$FixedDir = \$PSScriptRoot') -and (@(Get-Content -LiteralPath $PSCommandPath | Where-Object { $_ -match '^if \(-not \$ProofPath\)' }).Count -eq 1))
    Chk 'R3-1: the entry point refuses a -ProofPath outside the scripts'' folder as an argument error (exit 2) before any mode runs' ((@(Get-Content -LiteralPath $PSCommandPath | Where-Object { $_ -match '^\$argErrors = .*Test-Nep5ProofInFolder \$ProofPath \$PSScriptRoot' }).Count -eq 1) -and (@(Get-Content -LiteralPath $PSCommandPath | Where-Object { $_ -match '^if \(\$argErrors.Count\) .*exit 2' }).Count -eq 1))
    Write-Host '== the account session: password guard, no secret anywhere, probe run and kill, re-provisioning ==' -ForegroundColor Cyan
    $mkOps = { param($sw) New-N5TestAccountOps -Sw $sw -BinDir 'C:\fake\bin' }
    $mkSw = { [pscustomobject]@{ UserName = 'blarai-spike'; UserSid = $script:N5SpikeSid; FailSet = $false; NoStart = $false; Hang = $false; OnStart = $null; Secret = $null; Sets = (New-Object System.Collections.ArrayList); SetSids = (New-Object System.Collections.ArrayList); Starts = (New-Object System.Collections.ArrayList); EnvNames = @(); MarkerPath = $null; RecordAtSet = $null } }
    $swOk = & $mkSw; $opsOk = & $mkOps $swOk; $rOk = $opsOk.SetPassword()
    Chk 'account: with the right name and the recorded SID a fresh password is set on that account once, the credential is held in memory (user TESTPC\blarai-spike), and Changed is true' ($rOk.Ok -and $swOk.Sets.Count -eq 1 -and $swOk.Sets[0] -eq 'blarai-spike' -and $opsOk.Changed -and $opsOk.Cred.UserName -eq 'TESTPC\blarai-spike' -and $swOk.Secret.Length -ge 20) 'account-guard'
    $swW = & $mkSw; $swW.UserSid = 'S-1-5-21-1-2-3-1001'; $opsW = & $mkOps $swW; $rW = $opsW.SetPassword()
    $swN = & $mkSw; $swN.UserName = 'someone-else'; $opsN = & $mkOps $swN; $rN = $opsN.SetPassword()
    $swE = & $mkSw; $swE.UserSid = ''; $opsE = & $mkOps $swE; $rE = $opsE.SetPassword()
    Chk 'account guard: an account found by name with a DIFFERENT SID (here the operator''s), one with a different name, and one with no SID are each refused: no password generated or set, Changed false, no credential' ((-not $rW.Ok) -and (-not $rN.Ok) -and (-not $rE.Ok) -and $swW.Sets.Count -eq 0 -and $swN.Sets.Count -eq 0 -and $swE.Sets.Count -eq 0 -and $null -eq $swW.Secret -and -not $opsW.Changed -and -not $opsN.Changed -and $null -eq $opsW.Cred -and $rW.Reason -match 'REFUSED') 'account-guard'
    $opsX2 = New-Nep5AccountOps -BinDir 'C:\fake' -GetUser { param($n) throw 'no such user' } -NewPassword { throw 'must not be called' } -SetPasswordFn { throw 'must not be called' } -StartProcess { throw 'must not be called' }
    $rX2 = $opsX2.SetPassword()
    Chk 'account guard: an account that cannot be looked up is refused (nothing generated, nothing set)' ((-not $rX2.Ok) -and -not $opsX2.Changed) 'account-guard'
    $swF = & $mkSw; $swF.FailSet = $true; $opsF = & $mkOps $swF; $rF = $opsF.SetPassword()
    Chk 'account: a password write that throws is reported not Ok but Changed stays TRUE (a half-applied write is treated as changed, so the task gets re-provisioned)' ((-not $rF.Ok) -and $opsF.Changed -and $null -eq $opsF.Cred) 'account-guard'
    $opsOk.Drop()
    Chk 'account: Drop releases the credential' ($null -eq $opsOk.Cred)
    # no secret in any record, log, file or command line
    $c = New-N5TestCtx
    try {
        $c.Only = @('R1'); $rt = Invoke-Nep5Phase -Ctx $c -Phase 'taskcheck'; $rh = Invoke-Nep5Phase -Ctx $c -Phase 'halfset'
        $null = $c.AccountOps.SetPassword(); $secret = $c.AcctSw.Secret
        $rp = $c.AccountOps.RunProbe(5, $null); $c.AccountOps.Drop()
        $blob = (ConvertTo-Json -InputObject @($rt.Records, $rh.Records, $rp, @($c.AccountOps.Log)) -Depth 25) + "`n" + (Get-N5DirText -Dir $c.Tmp) + "`n" + (Get-Nep5ProbeCommandLine) + "`n" + (($c.AcctSw.Starts) -join "`n")
        Chk 'secret: the generated password appears in NO record, result file, session or baseline file, log line, process command line or request file of a taskcheck phase, a halfset phase and a probe start' (($secret.Length -ge 20) -and (-not $blob.Contains($secret)) -and ($c.AcctSw.Starts.Count -eq 1) -and ($c.AcctSw.Starts[0] -notmatch 'assword')) 'secret-not-recorded'
        Chk 'secret (positive control): the same scan DOES find the password when it is planted in a record' (((ConvertTo-Json -InputObject @($rt.Records, @{ leak = $secret }) -Depth 25)).Contains($secret)) 'secret-not-recorded'
        Chk 'probe command line: fixed text naming the hash-bound probe in the account''s bin folder and the request file there; no variable part' ((Get-Nep5ProbeCommandLine) -eq ('-NoProfile -NonInteractive -ExecutionPolicy Bypass -File "{0}\bin\spike-nep5-connect-probe.ps1" -RequestFile "{0}\bin\nep5-request.json"' -f $script:SpikeRoot))
    } finally { Remove-Item -LiteralPath $c.Tmp -Recurse -Force -ErrorAction SilentlyContinue }
    $swH = & $mkSw; $swH.Hang = $true; $opsH = & $mkOps $swH; $null = $opsH.SetPassword(); $tH = $opsH.RunProbe(1, $null)
    Chk 'child timeout: a probe that does not finish is KILLED at the limit and reported TimedOut and Killed (never left running)' ($tH.Started -and $tH.TimedOut -and $tH.Killed) 'child-timeout-kill'
    $swS = & $mkSw; $swS.NoStart = $true; $opsS = & $mkOps $swS; $null = $opsS.SetPassword(); $tS = $opsS.RunProbe(5, $null)
    $opsNo = & $mkOps (& $mkSw); $tNo = $opsNo.RunProbe(5, $null)
    Chk 'probe start: a logon refusal at start is reported not Started with the message; with no session password nothing is started at all' ((-not $tS.Started) -and $tS.Detail -match 'could not be started' -and (-not $tNo.Started) -and $tNo.Detail -match 'no session password')
    # the real run body with a fake child
    $rb = Join-Path ([IO.Path]::GetTempPath()) ('nep5-rb-' + [guid]::NewGuid().ToString('N')); $rbBin = Join-Path $rb 'bin'; $rbRes = Join-Path $rb 'results'; New-Item -ItemType Directory -Path $rbBin, $rbRes | Out-Null
    try {
        $reqB = { param($id) [ordered]@{ run_id = $id; mode = 'identity'; timeout_ms = 3000 } }
        $spk = $script:N5SpikeSid; $writeRes = { param($id, $sid, $rbRes) $o = [ordered]@{ schema_version = 1; kind = 'nep5-probe'; run_id = $id; mode = 'identity'; started = (Get-N5Now); finished = (Get-N5Now); token_sid = $sid; expected_sid = $spk; targets = @(); direct = $null; error = $null; overall = 'done' }; [IO.File]::WriteAllText((Join-Path $rbRes "result-$id.json"), (ConvertTo-Json -InputObject $o -Depth 6)) }
        $sw1 = & $mkSw; $sw1.OnStart = { & $writeRes 'nep5-rb-0001' $spk $rbRes }.GetNewClosure(); $o1 = & $mkOps $sw1; $null = $o1.SetPassword()
        $b1 = Invoke-Nep5RealAccountRunBody -BinDir $rbBin -ResultsDir $rbRes -ExpectedSid $script:N5SpikeSid -TimeoutSec 5 -AccountOps $o1 -RunId 'nep5-rb-0001' -Request (& $reqB 'nep5-rb-0001') -Tick $null
        Chk 'real run body: the request file is written, the child is started as the account, and its result file is read and judged: valid for the right SID' ($b1.Started -and $b1.Valid -and (Test-Path (Join-Path $rbBin 'nep5-request.json')))
        $sw2 = & $mkSw; $sw2.OnStart = { & $writeRes 'nep5-rb-0002' 'S-1-5-21-1-2-3-1001' $rbRes }.GetNewClosure(); $o2 = & $mkOps $sw2; $null = $o2.SetPassword()
        $b2 = Invoke-Nep5RealAccountRunBody -BinDir $rbBin -ResultsDir $rbRes -ExpectedSid $script:N5SpikeSid -TimeoutSec 5 -AccountOps $o2 -RunId 'nep5-rb-0002' -Request (& $reqB 'nep5-rb-0002') -Tick $null
        $sw3 = & $mkSw; $o3 = & $mkOps $sw3; $null = $o3.SetPassword()
        $b3 = Invoke-Nep5RealAccountRunBody -BinDir $rbBin -ResultsDir $rbRes -ExpectedSid $script:N5SpikeSid -TimeoutSec 5 -AccountOps $o3 -RunId 'nep5-rb-0003' -Request (& $reqB 'nep5-rb-0003') -Tick $null
        $sw4 = & $mkSw; $sw4.Hang = $true; $o4 = & $mkOps $sw4; $null = $o4.SetPassword()
        $b4 = Invoke-Nep5RealAccountRunBody -BinDir $rbBin -ResultsDir $rbRes -ExpectedSid $script:N5SpikeSid -TimeoutSec 1 -AccountOps $o4 -RunId 'nep5-rb-0004' -Request (& $reqB 'nep5-rb-0004') -Tick $null
        Chk 'real run body: a result from the WRONG token SID is invalid; a child that exits without a result file is a problem; a child that hangs is killed and reported (never read as a result)' ((-not $b2.Valid) -and ($b2.Problems -join ' ') -match 'ran as' -and (-not $b3.Valid) -and ($b3.Problems -join ' ') -match 'no result file' -and (-not $b4.Valid) -and ($b4.Problems -join ' ') -match 'killed: True') 'child-timeout-kill'
    } finally { Remove-Item -LiteralPath $rb -Recurse -Force -ErrorAction SilentlyContinue }
    # Invoke-Nep5Reprovision
    $pd = Join-Path ([IO.Path]::GetTempPath()) ('nep5-prov-' + [guid]::NewGuid().ToString('N')); New-Item -ItemType Directory -Path $pd | Out-Null
    try {
        [IO.File]::WriteAllText((Join-Path $pd 'spike-provision.ps1'), "# fake provision`n"); $psha = Get-NormalizedSha256 -Path (Join-Path $pd 'spike-provision.ps1')
        $started = New-Object System.Collections.ArrayList
        $mkP = { param($exit, $hang, $log) { param($exe, $argLine, $so, $se) [void]$log.Add($argLine); $p = [pscustomobject]@{ HasExited = (-not $hang); ExitCode = $exit; Killed = $false }; $p | Add-Member -MemberType ScriptMethod -Name Kill -Value { $this.Killed = $true; $this.HasExited = $true }; $p }.GetNewClosure() }
        $rp0 = Invoke-Nep5Reprovision -Folder $pd -ExpectedSha $psha -StartProcess (& $mkP 0 $false $started)
        Chk 'reprovision: with the bound hash it runs spike-provision.ps1 -Apply -ForceNewPassword (exactly that command line) and exit 0 is Ok' ($rp0.Ok -and $started.Count -eq 1 -and $started[0] -match '-Apply -ForceNewPassword$' -and $started[0] -match 'spike-provision.ps1') 'restore-proof'
        $started.Clear(); [IO.File]::WriteAllText((Join-Path $pd 'spike-provision.ps1'), "# fake provision EDITED`n")
        $rp1 = Invoke-Nep5Reprovision -Folder $pd -ExpectedSha $psha -StartProcess (& $mkP 0 $false $started)
        Chk 'reprovision: a spike-provision.ps1 whose hash is not the proof''s is REFUSED and never started; the record carries the manual command' ((-not $rp1.Ok) -and $started.Count -eq 0 -and $rp1.Detail -match 'REFUSED' -and $rp1.Manual -match '-Apply -ForceNewPassword') 'restore-proof'
        Chk 'reprovision (lock OFF): with the proof hash replaced by the edited file''s own hash the same call DOES start it, so the refusal above is the hash check' ((Invoke-Nep5Reprovision -Folder $pd -ExpectedSha (Get-NormalizedSha256 -Path (Join-Path $pd 'spike-provision.ps1')) -StartProcess (& $mkP 0 $false $started)).Ok -and $started.Count -eq 1) 'restore-proof'
        $rp2 = Invoke-Nep5Reprovision -Folder $pd -ExpectedSha (Get-NormalizedSha256 -Path (Join-Path $pd 'spike-provision.ps1')) -StartProcess (& $mkP 3 $false $started)
        $rp3 = Invoke-Nep5Reprovision -Folder $pd -ExpectedSha (Get-NormalizedSha256 -Path (Join-Path $pd 'spike-provision.ps1')) -StartProcess (& $mkP 0 $true $started) -TimeoutSec 1 -PollMs 50
        Chk 'reprovision: a non-zero exit is not Ok (exit code kept); a run that hangs is killed at the limit and not Ok' ((-not $rp2.Ok) -and $rp2.ExitCode -eq 3 -and (-not $rp3.Ok) -and $rp3.TimedOut) 'child-timeout-kill'
    } finally { Remove-Item -LiteralPath $pd -Recurse -Force -ErrorAction SilentlyContinue }
    # session lifecycle through the phase runner
    $c = New-N5TestCtx
    try {
        $c.Only = @('R0'); $r = Invoke-Nep5Phase -Ctx $c -Phase 'halfset'
        Chk 'lifecycle: password set once, released and re-provisioned once per phase; the session record exists only while the password is live (gone after a proven restore); the harness and engine ran in between' (($c.AcctSw.Sets.Count -eq 1) -and ($c.RepSw.Count -eq 1) -and -not (Test-Path (Get-Nep5SessionMarkerPath -Ctx $c)) -and $r.ExitCode -eq 0) 'restore-proof'
        $c.RepSw.Fail = $true; $r2 = Invoke-Nep5Phase -Ctx $c -Phase 'halfset'
        $gate = Invoke-Nep5Phase -Ctx $c -Phase 'ours'
        Chk 'lifecycle: a failed re-provision leaves the session record and exit 9; the next phase is refused (taskcheck record removed, session record present) without touching the account' (($r2.ExitCode -eq 9) -and (Test-Path (Get-Nep5SessionMarkerPath -Ctx $c)) -and ($gate.ExitCode -eq 2) -and $c.AcctSw.Sets.Count -eq 2) 'restore-proof'
    } finally { Remove-Item -LiteralPath $c.Tmp -Recurse -Force -ErrorAction SilentlyContinue }
    $c = New-N5TestCtx
    try {
        $c.AcctSw.UserSid = 'S-1-5-21-1-2-3-1001'; $r = Invoke-Nep5Phase -Ctx $c -Phase 'taskcheck'
        Chk 'lifecycle: with the wrong SID the taskcheck is refused (exit 2), no password is set, NO re-provision runs (nothing changed) and no session record remains' (($r.ExitCode -eq 2) -and $c.AcctSw.Sets.Count -eq 0 -and $c.RepSw.Count -eq 0 -and -not (Test-Path (Get-Nep5SessionMarkerPath -Ctx $c))) 'account-guard'
    } finally { Remove-Item -LiteralPath $c.Tmp -Recurse -Force -ErrorAction SilentlyContinue }
    $c = New-N5TestCtx
    try {
        $c.OriginalTaskRun = { param($rid) [pscustomobject]@{ valid = $false; token_sid = $null; task_start = [pscustomobject]@{ Detail = 'task never started (LastTaskResult=0x8007052E)' } } }
        $r = Invoke-Nep5Phase -Ctx $c -Phase 'taskcheck'
        Chk 'lifecycle: re-provision reports success but the restored task does not start as the account: still task_not_restored (exit 9) and the session record stays' (($r.ExitCode -eq 9) -and $r.Records[0].class -eq 'task_not_restored' -and (Test-Path (Get-Nep5SessionMarkerPath -Ctx $c))) 'restore-proof'
    } finally { Remove-Item -LiteralPath $c.Tmp -Recurse -Force -ErrorAction SilentlyContinue }

    Write-Host '== review round 1 (account logon): the launcher, the account environment, the session record, the restore preconditions ==' -ForegroundColor Cyan
    $ps51exe = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
    $hostTag = "$($PSVersionTable.PSEdition) $($PSVersionTable.PSVersion)"
    $lt = Join-Path ([IO.Path]::GetTempPath()) ('nep5-launch-' + [guid]::NewGuid().ToString('N')); New-Item -ItemType Directory -Path $lt | Out-Null
    $srRoot = Join-Path $lt 'sr'; New-Item -ItemType Directory -Path (Join-Path $srRoot 'work\tmp') -Force | Out-Null
    $env:NEP5_SELFTEST_FAKE_SECRET_TOKEN = 'planted-parent-secret-0451'
    try {
        # --- pure builders
        $wmp = Get-Nep5WinPsModulePath -SystemRoot 'C:\Windows' -ProgramFiles 'C:\Program Files'
        Chk 'launcher: the Windows PowerShell module path is the machine value (Program Files\WindowsPowerShell\Modules; System32\WindowsPowerShell\v1.0\Modules)' ($wmp -ceq 'C:\Program Files\WindowsPowerShell\Modules;C:\Windows\System32\WindowsPowerShell\v1.0\Modules')
        $parentFake = @{ PSModulePath = 'C:\Program Files\PowerShell\7\Modules;C:\x'; Foo = 'bar'; OTHER = 'baz' }
        $pe = Get-Nep5ProvisionEnvironment -Parent $parentFake -ModulePath $wmp
        Chk 'launcher: the operator-side child environment is the parent''s own variables with ONLY PSModulePath replaced by the Windows PowerShell value' (($pe['PSModulePath'] -ceq $wmp) -and $pe['Foo'] -eq 'bar' -and $pe['OTHER'] -eq 'baz' -and $pe.Count -eq 3)
        $pureRoot = 'Z:\nep5-selftest-account'; $aeP = Get-Nep5AccountEnvironment -SystemRoot 'C:\Windows' -ProgramFiles 'C:\Program Files' -SpikeRoot $pureRoot   # strings only: no folder is touched
        $ae = Get-Nep5AccountEnvironment -SystemRoot $env:SystemRoot -ProgramFiles $env:ProgramFiles -SpikeRoot $srRoot
        $forbid = @($env:USERPROFILE, $env:LOCALAPPDATA, $env:APPDATA, $env:TEMP) | Where-Object { $_ }
        $envProbs = @(Test-Nep5ChildEnvironment -Environment $aeP -Allow $script:N5AccountEnvAllow -SpikeRoot $pureRoot -Forbidden $forbid)
        Chk 'account environment: the block built for blarai-spike has exactly the allowlisted names, no secret-looking name, profile and temp inside the account folder it was built for (a fictitious root here), and no mention of the operator''s profile or temp folders' (($envProbs.Count -eq 0) -and ((@($aeP.Keys | Sort-Object) -join ',') -ceq (@($script:N5AccountEnvAllow | Sort-Object) -join ',')) -and $aeP['TEMP'] -ceq "$pureRoot\work\tmp") 'account-env'
        $negEnv = @(
            @{ n = 'a token variable'; m = { param($e) $e['GITHUB_PERSONAL_ACCESS_TOKEN'] = 'x' } }, @{ n = 'an unlisted variable'; m = { param($e) $e['Foo'] = 'x' } }, @{ n = 'a password variable'; m = { param($e) $e['VIKUNJA_PASS'] = 'x' } },
            @{ n = 'TEMP outside the account folder'; m = { param($e) $e['TEMP'] = 'C:\Windows\Temp' } }, @{ n = 'an empty value'; m = { param($e) $e['TMP'] = '' } },
            @{ n = 'the operator''s profile in a value'; m = { param($e) $e['PATH'] = $e['PATH'] + ';C:\Users\someone\bin' } })
        $negMiss = @(); foreach ($ne in $negEnv) { $e2 = [ordered]@{}; foreach ($k in $aeP.Keys) { $e2[$k] = $aeP[$k] }; & $ne.m $e2; if (@(Test-Nep5ChildEnvironment -Environment $e2 -Allow $script:N5AccountEnvAllow -SpikeRoot $pureRoot -Forbidden @('C:\Users\someone')).Count -eq 0) { $negMiss += $ne.n } }
        Chk "account environment (negative controls): the checker flags each of: a token variable, an unlisted variable, a password variable, TEMP outside the account folder, an empty value, the operator's profile in a value $(if ($negMiss.Count) { '(NOT flagged: ' + ($negMiss -join ', ') + ')' })" ($negMiss.Count -eq 0) 'account-env'
        Chk 'account environment: a secret variable planted in THIS process is absent from the built block (names and values)' (-not ($aeP.Keys -contains 'NEP5_SELFTEST_FAKE_SECRET_TOKEN') -and (@($aeP.Values | Where-Object { [string]$_ -like '*planted-parent-secret-0451*' }).Count -eq 0)) 'account-env'
        # --- the start info of the account child (built, never started)
        $fcred = New-Object Management.Automation.PSCredential('TESTPC\blarai-spike', (ConvertTo-SecureString 'Fp-not-a-real-password-1!' -AsPlainText -Force))
        $si = New-Nep5AccountStartInfo -Cred $fcred -FilePath $ps51exe -ArgumentLine (Get-Nep5ProbeCommandLine) -WorkingDirectory "$srRoot\bin" -Environment $ae
        $siNames = @($si.EnvironmentVariables.Keys | ForEach-Object { ([string]$_).ToLowerInvariant() } | Sort-Object)
        Chk 'account start info: runs as blarai-spike on the computer, profile loaded, no shell, no window, hidden, the bin folder as working folder, the fixed command line, nothing captured, and the environment block is the minimal one only (cleared first)' (($si.UserName -ceq 'blarai-spike') -and ($si.Domain -ceq 'TESTPC') -and $si.LoadUserProfile -and (-not $si.UseShellExecute) -and $si.CreateNoWindow -and ($si.WindowStyle -eq [Diagnostics.ProcessWindowStyle]::Hidden) -and ($si.WorkingDirectory -ceq "$srRoot\bin") -and ($si.Arguments -ceq (Get-Nep5ProbeCommandLine)) -and (-not $si.RedirectStandardOutput) -and ($siNames -join ',') -ceq ((@($script:N5AccountEnvAllow | ForEach-Object { $_.ToLowerInvariant() } | Sort-Object)) -join ',') -and ($si.Arguments -notmatch 'Fp-not') -and ($null -ne $si.Password)) 'account-env'
        # --- real child processes on benign scripts (no account, no machine state)
        $okScr = Join-Path $lt 'ss-ok.ps1'; Set-Content -LiteralPath $okScr -Value @('$ErrorActionPreference = ''Stop''', 'ConvertTo-SecureString ''x'' -AsPlainText -Force | Out-Null', 'Write-Output ''ss-ok''', 'exit 0')
        $dumpScr = Join-Path $lt 'dump-env.ps1'; Set-Content -LiteralPath $dumpScr -Value @('param([string]$Out)', 'Get-ChildItem Env: | ForEach-Object { $_.Name } | Sort-Object | Set-Content -LiteralPath $Out')
        $runChild = { param($scr, $envB, $extra) $psi = New-Nep5StartInfo -FilePath $ps51exe -ArgumentLine ('-NoProfile -NonInteractive -ExecutionPolicy Bypass -File "{0}" {1}' -f $scr, $extra) -WorkingDirectory $lt -Environment $envB -Capture
            $p = Start-Nep5Child -StartInfo $psi; $dl = (Get-Date).AddSeconds(90); while (-not $p.HasExited -and (Get-Date) -lt $dl) { Start-Sleep -Milliseconds 100 }; if (-not $p.HasExited) { try { $p.Kill() } catch {} }
            $o = $p.ReadOutput(); [pscustomobject]@{ Exit = $p.ExitCode; Out = $o.Out; Err = $o.Err } }
        $cleanEnv = Get-Nep5ProvisionEnvironment -Parent ([Environment]::GetEnvironmentVariables()) -ModulePath $wmp
        $rOk = & $runChild $okScr $cleanEnv ''
        Chk "launcher (REAL child, $hostTag host): Windows PowerShell 5.1 started by the real launcher with the clean module path runs ConvertTo-SecureString (exit 0, output back through the launcher)" (($rOk.Exit -eq 0) -and ($rOk.Out -match 'ss-ok')) 'launcher-real'
        $p7mods = $null
        if ($PSVersionTable.PSEdition -eq 'Core') { $p7mods = Join-Path $PSHOME 'Modules' } else { $cand = Join-Path $env:ProgramFiles 'PowerShell\7\Modules'; if (Test-Path -LiteralPath $cand) { $p7mods = $cand } }
        if ($p7mods) {
            $dirtyEnv = Get-Nep5ProvisionEnvironment -Parent ([Environment]::GetEnvironmentVariables()) -ModulePath ("$p7mods;" + $wmp)
            $rBad = & $runChild $okScr $dirtyEnv ''
            Chk 'launcher (lock OFF, REAL child): the same child with a PowerShell 7 module folder first on PSModulePath FAILS to run ConvertTo-SecureString, so the pass above is the clean path and not a script that cannot fail' (($rBad.Exit -ne 0) -and ($rBad.Out -notmatch 'ss-ok')) 'launcher-real'
        } else { Write-Host '  [SKIP] no PowerShell 7 module folder on this machine: the lock-off control of the module path cannot be built here' -ForegroundColor Yellow }
        $dumpOut = Join-Path $lt 'env-account.txt'
        $rEnv = & $runChild $dumpScr $ae ('-Out "{0}"' -f $dumpOut)
        $seen = @(); if (Test-Path -LiteralPath $dumpOut) { $seen = @(Get-Content -LiteralPath $dumpOut | Where-Object { $_ }) }
        $allowL = @($script:N5AccountEnvAllow | ForEach-Object { $_.ToLowerInvariant() }) + @('psexecutionpolicypreference')
        $extra = @($seen | Where-Object { $allowL -notcontains $_.ToLowerInvariant() })
        Chk "account environment (REAL child, $hostTag host): the child started with the account block sees ONLY those variables (plus the one PowerShell sets for -ExecutionPolicy), and the secret variable planted in this process is not among them; extra names seen: $(if ($extra.Count) { $extra -join ',' } else { 'none' })" (($rEnv.Exit -eq 0) -and $seen.Count -ge 8 -and $extra.Count -eq 0 -and ($seen -notcontains 'NEP5_SELFTEST_FAKE_SECRET_TOKEN')) 'account-env'
        $dumpOut2 = Join-Path $lt 'env-inherit.txt'
        $rEnv2 = & $runChild $dumpScr $cleanEnv ('-Out "{0}"' -f $dumpOut2)
        $seen2 = @(); if (Test-Path -LiteralPath $dumpOut2) { $seen2 = @(Get-Content -LiteralPath $dumpOut2 | Where-Object { $_ }) }
        Chk 'account environment (lock OFF, REAL child): a child started with the parent''s whole environment DOES see the planted secret variable, so the dump above can see a leak and the clean result is not a blind probe' (($rEnv2.Exit -eq 0) -and ($seen2 -contains 'NEP5_SELFTEST_FAKE_SECRET_TOKEN')) 'account-env'
        # --- Invoke-Nep5Reprovision through its REAL default launcher against a benign stand-in for spike-provision.ps1
        $pv = Join-Path $lt 'prov'; $pvBin = Join-Path $lt 'provbin'; New-Item -ItemType Directory -Path $pv, $pvBin | Out-Null
        Set-Content -LiteralPath (Join-Path $pv 'spike-provision.ps1') -Value @('param([switch]$Apply, [switch]$DryRun, [switch]$ForceNewPassword)', '$ErrorActionPreference = ''Stop''', 'ConvertTo-SecureString ''x'' -AsPlainText -Force | Out-Null',
            'if ($DryRun -and (Test-Path -LiteralPath (Join-Path $PSScriptRoot ''dryrun-fails.flag''))) { Write-Host ''PRECONDITION FAILS: stand-in''; exit 2 }', 'Write-Host ("PROVISION-RAN Apply=$Apply DryRun=$DryRun Force=$ForceNewPassword")', 'exit 0')
        foreach ($n in @('spike-lib.ps1', 'spike-run-test.ps1', 'spike_model.py')) { Set-Content -LiteralPath (Join-Path $pv $n) -Value "# stand-in $n"; Set-Content -LiteralPath (Join-Path $pvBin $n) -Value "# stand-in $n" }
        $pvSha = Get-NormalizedSha256 -Path (Join-Path $pv 'spike-provision.ps1'); $pvDep = @{ 'spike-lib.ps1' = (Get-NormalizedSha256 -Path (Join-Path $pv 'spike-lib.ps1')) }
        $rpA = Invoke-Nep5Reprovision -Folder $pv -ExpectedSha $pvSha -DependencySha $pvDep -BinDir $pvBin -TimeoutSec 90
        Chk "reprovision (REAL default launcher, $hostTag host): a stand-in spike-provision.ps1 that calls ConvertTo-SecureString runs under Windows PowerShell 5.1 with -Apply -ForceNewPassword and exit 0 is Ok; its output tail comes back" (($rpA.Ok) -and ($rpA.Detail -match 'PROVISION-RAN Apply=True DryRun=False Force=True')) 'launcher-real'
        $rpD = Invoke-Nep5Reprovision -Mode DryRun -Folder $pv -ExpectedSha $pvSha -DependencySha $pvDep -BinDir $pvBin -TimeoutSec 90
        Chk 'reprovision -Mode DryRun (REAL launcher): the stand-in is started with -DryRun only (never -Apply) and exit 0 is Ok' (($rpD.Ok) -and ($rpD.Detail -match 'DryRun=True') -and ($rpD.Detail -match 'Apply=False') -and ($rpD.Manual -match '-DryRun') -and ($rpD.Manual -notmatch '-Apply')) 'precondition-dryrun'
        Set-Content -LiteralPath (Join-Path $pv 'dryrun-fails.flag') -Value 'x'
        $rpF = Invoke-Nep5Reprovision -Mode DryRun -Folder $pv -ExpectedSha $pvSha -DependencySha $pvDep -BinDir $pvBin -TimeoutSec 90
        Chk 'reprovision -Mode DryRun (REAL launcher): a stand-in whose precondition fails exits 2: not Ok, exit code kept, the PRECONDITION line is in the detail' ((-not $rpF.Ok) -and $rpF.ExitCode -eq 2 -and ($rpF.Detail -match 'PRECONDITION FAILS: stand-in')) 'precondition-dryrun'
        Remove-Item -LiteralPath (Join-Path $pv 'dryrun-fails.flag') -Force
        $rpP = Invoke-Nep5Reprovision -Folder $pv -ExpectedSha $pvSha -DependencySha $pvDep -BinDir $pvBin -TimeoutSec 90 -ModulePath ("$(if ($p7mods) { $p7mods } else { 'C:\no-such' });" + $wmp)
        Chk 'reprovision (lock OFF, REAL launcher): with the PowerShell 7 module path handed to the child the same stand-in does NOT restore (not Ok): the clean module path is what makes the pass above' ($(if ($p7mods) { (-not $rpP.Ok) } else { $true })) 'launcher-real'
        # --- dependencies hashed before the start
        $startedD = New-Object System.Collections.ArrayList
        $mkPd = { param($log) { param($exe, $argLine, $envB) [void]$log.Add($argLine); $p = [pscustomobject]@{ HasExited = $true; ExitCode = 0 }; $p | Add-Member -MemberType ScriptMethod -Name Kill -Value { }; $p }.GetNewClosure() }
        Chk 'dependencies: with every file as the proof bound it, the stand-ins are accepted' (@(Test-Nep5ProvisionDependencies -Folder $pv -ExpectedSha $pvSha -DependencySha $pvDep -BinDir $pvBin).Count -eq 0)
        $depCases = @(
            @{ n = 'spike-lib.ps1 edited'; f = 'spike-lib.ps1'; t = '# edited' }, @{ n = 'spike-provision.ps1 edited'; f = 'spike-provision.ps1'; t = '# edited' },
            @{ n = 'spike-run-test.ps1 differs from the copy in bin'; f = 'spike-run-test.ps1'; t = '# edited' }, @{ n = 'spike_model.py differs from the copy in bin'; f = 'spike_model.py'; t = '# edited' })
        $depMiss = @(); $depStarted = @()
        foreach ($dc in $depCases) {
            $fp = Join-Path $pv $dc.f; $orig = [IO.File]::ReadAllText($fp); [IO.File]::WriteAllText($fp, $dc.t)
            $startedD.Clear(); $rr = Invoke-Nep5Reprovision -Folder $pv -ExpectedSha $pvSha -DependencySha $pvDep -BinDir $pvBin -StartProcess (& $mkPd $startedD)
            if ($rr.Ok -or $startedD.Count -ne 0 -or $rr.Detail -notmatch 'REFUSED') { $depMiss += $dc.n }
            [IO.File]::WriteAllText($fp, $orig)
        }
        Remove-Item -LiteralPath (Join-Path $pvBin 'spike_model.py') -Force
        $startedD.Clear(); $rr = Invoke-Nep5Reprovision -Folder $pv -ExpectedSha $pvSha -DependencySha $pvDep -BinDir $pvBin -StartProcess (& $mkPd $startedD)
        if ($rr.Ok -or $startedD.Count -ne 0) { $depMiss += 'a copy source with no copy in bin to compare against' }
        Set-Content -LiteralPath (Join-Path $pvBin 'spike_model.py') -Value '# stand-in spike_model.py'
        $startedD.Clear(); $rrOk = Invoke-Nep5Reprovision -Folder $pv -ExpectedSha $pvSha -DependencySha $pvDep -BinDir $pvBin -StartProcess (& $mkPd $startedD)
        Chk "dependencies: spike-provision.ps1 is NOT started (REFUSED, nothing launched) when spike-lib.ps1, spike-provision.ps1, a copy source or the copy to compare it with differs or is missing $(if ($depMiss.Count) { '(started anyway: ' + ($depMiss -join ', ') + ')' }); with all restored the same call starts it" (($depMiss.Count -eq 0) -and $rrOk.Ok -and $startedD.Count -eq 1) 'proof-hash-binding'
        # --- B7: the seams -Run and -Remove wire into their contexts (one builder, both entry points)
        $sCap = New-Object System.Collections.ArrayList
        $seams = New-Nep5ProvisionSeams -Folder $pv -ProvisionSha $pvSha -LibSha $pvDep['spike-lib.ps1'] -BinDir $pvBin -StartProcess (& $mkPd $sCap)
        $sA = & $seams.Reprovision $null; $sD = & $seams.ProvisionDryRun $null
        Chk 'seams (B7): the Reprovision seam starts spike-provision.ps1 with -Apply -ForceNewPassword and the ProvisionDryRun seam with -DryRun only, each exactly once' ($sA.Ok -and $sD.Ok -and $sCap.Count -eq 2 -and $sCap[0] -match '-Apply -ForceNewPassword$' -and $sCap[1] -match '-DryRun$' -and $sCap[1] -notmatch '-Apply') 'seams'
        $fpL = Join-Path $pv 'spike-lib.ps1'; $origL = [IO.File]::ReadAllText($fpL); [IO.File]::WriteAllText($fpL, '# edited')
        $sCap.Clear(); $tA = & $seams.Reprovision $null; $tD = & $seams.ProvisionDryRun $null
        [IO.File]::WriteAllText($fpL, $origL)
        $seamsNoBin = New-Nep5ProvisionSeams -Folder $pv -ProvisionSha $pvSha -LibSha $pvDep['spike-lib.ps1'] -BinDir (Join-Path $lt 'no-such-bin') -StartProcess (& $mkPd $sCap)
        $sbA = & $seamsNoBin.Reprovision $null; $sbD = & $seamsNoBin.ProvisionDryRun $null
        $seamsNoLib = New-Nep5ProvisionSeams -Folder $pv -ProvisionSha $pvSha -LibSha '' -BinDir $pvBin -StartProcess (& $mkPd $sCap)
        $lA = & $seamsNoLib.Reprovision $null; $lD = & $seamsNoLib.ProvisionDryRun $null
        Chk 'seams (B7): BOTH seams (the -Run and -Remove re-provision, and the DryRun) refuse and start nothing when spike-lib.ps1 was edited, when the bin copies cannot be compared, and when the proof had no spike-lib hash' ((-not $tA.Ok) -and (-not $tD.Ok) -and (-not $sbA.Ok) -and (-not $sbD.Ok) -and (-not $lA.Ok) -and (-not $lD.Ok) -and $sCap.Count -eq 0 -and $tA.Detail -match 'REFUSED' -and $tD.Detail -match 'REFUSED') 'seams'
        # --- B3: a timeout kills the whole process tree and returns on time
        $pvH = Join-Path $lt 'provhang'; New-Item -ItemType Directory -Path $pvH | Out-Null
        Set-Content -LiteralPath (Join-Path $pvH 'spike-provision.ps1') -Value @('param([switch]$Apply, [switch]$DryRun, [switch]$ForceNewPassword)', '$g = Start-Process -FilePath cmd.exe -ArgumentList ''/c ping -n 60 127.0.0.1 > nul'' -PassThru -WindowStyle Hidden', 'Set-Content -LiteralPath (Join-Path $PSScriptRoot ''grandchild.pid'') -Value $g.Id', 'Start-Sleep -Seconds 60')
        Set-Content -LiteralPath (Join-Path $pvH 'spike-lib.ps1') -Value '# stand-in'
        $hShaP = Get-NormalizedSha256 -Path (Join-Path $pvH 'spike-provision.ps1'); $hShaL = Get-NormalizedSha256 -Path (Join-Path $pvH 'spike-lib.ps1')
        $swH = [Diagnostics.Stopwatch]::StartNew()
        $rpH = Invoke-Nep5Reprovision -Folder $pvH -ExpectedSha $hShaP -DependencySha @{ 'spike-lib.ps1' = $hShaL } -TimeoutSec 6 -PollMs 100
        $swH.Stop(); $gpid = $null; $gpf = Join-Path $pvH 'grandchild.pid'; if (Test-Path -LiteralPath $gpf) { $gpid = [int](Get-Content -LiteralPath $gpf -Raw) }
        $goneAt = [Diagnostics.Stopwatch]::StartNew(); while ($gpid -and (Get-Process -Id $gpid -ErrorAction SilentlyContinue) -and $goneAt.Elapsed.TotalSeconds -lt 4) { Start-Sleep -Milliseconds 200 }
        $gAlive = [bool]($gpid -and (Get-Process -Id $gpid -ErrorAction SilentlyContinue))
        if ($gAlive) { Stop-Process -Id $gpid -Force -ErrorAction SilentlyContinue }
        Chk "timeout (B3): a stand-in that starts a long grandchild and then hangs is killed AS A TREE at the limit (grandchild gone), the call returns within the limit plus 7 s ($([int]$swH.Elapsed.TotalSeconds) s taken), TimedOut and not Ok" ($rpH.TimedOut -and (-not $rpH.Ok) -and $null -ne $gpid -and (-not $gAlive) -and $swH.Elapsed.TotalSeconds -lt 13) 'child-timeout-kill'
    } finally { Remove-Item Env:NEP5_SELFTEST_FAKE_SECRET_TOKEN -ErrorAction SilentlyContinue; Remove-Item -LiteralPath $lt -Recurse -Force -ErrorAction SilentlyContinue }

    # --- the account operations against shimmed cmdlets: the REAL default write and lookup, addressed by SID
    $pwTxt = @(Test-Nep5SetPasswordWrite -Folder $PSScriptRoot)
    $pwOk = ($pwTxt.Count -eq 0)
    Chk "structure: exactly ONE account password write exists in the matrix scripts and the probe, inside New-Nep5AccountOps, addressed by -SID; no net user, no Set-LocalUserPassword $(if ($pwTxt.Count) { '(' + ($pwTxt -join '; ') + ')' })" $pwOk 'account-guard'
    # the stand-in test below drives the REAL default write scriptblock: it runs only if the guarded-write check above passed, with a SID that does not exist here
    & {
        if (-not $pwOk) { Chk 'account (REAL default write): NOT RUN - the one-guarded-write check failed, so the stand-in test is skipped before any write path can be reached' $false 'account-guard'; return }
        $script:N5ShimCalls = New-Object System.Collections.ArrayList
        function Set-LocalUser { [CmdletBinding()] param([string]$Name, [Security.Principal.SecurityIdentifier]$SID, $InputObject, [securestring]$Password) [void]$script:N5ShimCalls.Add([pscustomobject]@{ Cmd = 'Set-LocalUser'; Keys = @($PSBoundParameters.Keys | Where-Object { $_ -ne 'ErrorAction' } | Sort-Object); Sid = [string]$SID; HasPassword = [bool]$Password }) }
        function Get-LocalUser { [CmdletBinding()] param([string[]]$Name, [Security.Principal.SecurityIdentifier[]]$SID) [void]$script:N5ShimCalls.Add([pscustomobject]@{ Cmd = 'Get-LocalUser'; Keys = @($PSBoundParameters.Keys | Where-Object { $_ -ne 'ErrorAction' } | Sort-Object); Sid = [string]($SID | Select-Object -First 1); HasPassword = $false }); [pscustomobject]@{ Name = 'nep5-selftest-no-such-user'; SID = [Security.Principal.SecurityIdentifier]$script:N5StaleSid } }
        $stResolves = $false; try { [void](([Security.Principal.SecurityIdentifier]$script:N5StaleSid).Translate([Security.Principal.NTAccount])); $stResolves = $true } catch {}
        $shimCmds = @((Get-Command Set-LocalUser -ErrorAction SilentlyContinue), (Get-Command Get-LocalUser -ErrorAction SilentlyContinue))
        $shimIsFn = (@($shimCmds | Where-Object { $_ -and $_.CommandType -eq 'Function' -and -not $_.Module }).Count -eq 2)
        if (-not $shimIsFn -or $stResolves) { Chk 'account (REAL default write): NOT RUN - the stand-in functions are not what Set-LocalUser / Get-LocalUser resolve to here (or the stale SID resolves on this machine), so the real write path was not exercised' $false 'account-guard'; return }
        $realOps = New-Nep5AccountOps -BinDir 'C:\fake\bin'
        $gotUser = & $realOps.GetUserFn $script:N5StaleSid
        & $realOps.SetPasswordFn $gotUser (ConvertTo-SecureString 'Fp-shim-pw-1!' -AsPlainText -Force)
        $shimSet = @($script:N5ShimCalls | Where-Object { $_.Cmd -eq 'Set-LocalUser' }); $shimGet = @($script:N5ShimCalls | Where-Object { $_.Cmd -eq 'Get-LocalUser' })
        Chk 'account: the REAL default lookup asks for the account by the recorded SID (not by name) and the REAL default write is one Set-LocalUser addressed by that SID with a password and nothing else (no -Name, no -InputObject); the SID written is the one looked up' (($shimGet.Count -eq 1) -and ($shimGet[0].Keys -join ',') -ceq 'SID' -and ($shimGet[0].Sid -ceq $script:N5StaleSid) -and ($shimSet.Count -eq 1) -and (($shimSet[0].Keys -join ',') -ceq 'Password,SID') -and ($shimSet[0].Sid -ceq $script:N5StaleSid) -and $shimSet[0].HasPassword) 'account-guard'
    }
    $spHits = @(Find-Nep5Commands -Folder $PSScriptRoot -Files @('spike-nep5-matrix.ps1', 'spike-nep5-run-lib.ps1') -NameRegex '(?i)^Start-Process$|^Invoke-WmiMethod$|^Invoke-CimMethod$')
    Chk 'structure: no Start-Process in the matrix or the run library: every account / provision child is started by Start-Nep5Child, which clears and sets the environment explicitly (the library''s netsh export is the operator''s own tool)' ($spHits.Count -eq 0) 'launcher-real'
    $acAst = [Management.Automation.Language.Parser]::ParseFile((Join-Path $PSScriptRoot 'spike-nep5-run-lib.ps1'), [ref]$null, [ref]$null)
    $acFn = $acAst.Find({ param($n) $n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq 'New-Nep5AccountOps' }, $true)
    $acCalls = @($acFn.FindAll({ param($n) $n -is [Management.Automation.Language.CommandAst] }, $true) | ForEach-Object { $_.GetCommandName() })
    Chk 'structure: the account''s default start is New-Nep5AccountStartInfo then Start-Nep5Child, the default lookup is Get-LocalUser, the default write is Set-LocalUser' (($acCalls -contains 'New-Nep5AccountStartInfo') -and ($acCalls -contains 'Start-Nep5Child') -and ($acCalls -contains 'Get-LocalUser') -and ($acCalls -contains 'Set-LocalUser')) 'launcher-real'
    $edHits = @(Get-Nep5TaskEditHits -Folder $PSScriptRoot)
    Chk "task: nothing in the three matrix scripts edits, re-registers, disables or deletes the task (found by the parser as a command: Set/Register/Unregister/Disable/Enable/New-ScheduledTask, schtasks /change /create /delete, Set-Nep5TaskTarget) $(if ($edHits.Count) { '(' + (($edHits | ForEach-Object { "$($_.File):$($_.Line) $($_.Command)" }) -join '; ') + ')' })" ($edHits.Count -eq 0) 'task-never-edited'
    $mt = Join-Path ([IO.Path]::GetTempPath()) ('nep5-mut-' + [guid]::NewGuid().ToString('N')); New-Item -ItemType Directory -Path $mt | Out-Null
    try {
        foreach ($f in ($script:N5ThreeScripts + @('spike-nep5-connect-probe.ps1'))) { Copy-Item -LiteralPath (Join-Path $PSScriptRoot $f) -Destination (Join-Path $mt $f) }
        Add-Content -LiteralPath (Join-Path $mt 'spike-nep5-run-lib.ps1') -Value "`nfunction Nep5Evil { Set-ScheduledTask -TaskPath '\BlarAI\' -TaskName 'x' -Action (New-ScheduledTaskAction -Execute 'cmd.exe') }"
        $edMut = @(Get-Nep5TaskEditHits -Folder $mt)
        Chk 'task (lock OFF): a real Set-ScheduledTask call added to a copy of the run library IS found by the same check, so the clean result above can fail' ($edMut.Count -ge 1 -and $edMut[0].Command -eq 'Set-ScheduledTask') 'task-never-edited'
        Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'spike-nep5-run-lib.ps1') -Destination (Join-Path $mt 'spike-nep5-run-lib.ps1') -Force
        Add-Content -LiteralPath (Join-Path $mt 'spike-nep5-matrix.ps1') -Value "`nfunction Nep5Evil2 { Set-LocalUser -Name 'someone' -Password `$x }"
        $pwMut = @(Test-Nep5SetPasswordWrite -Folder $mt)
        Chk 'account write (lock OFF): a second Set-LocalUser (by -Name) added to a copy of the matrix is reported by the structure check' ($pwMut.Count -ge 1) 'account-guard'
        Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'spike-nep5-matrix.ps1') -Destination (Join-Path $mt 'spike-nep5-matrix.ps1') -Force
        $rlt = [IO.File]::ReadAllText((Join-Path $mt 'spike-nep5-run-lib.ps1')); [IO.File]::WriteAllText((Join-Path $mt 'spike-nep5-run-lib.ps1'), $rlt.Replace('Set-LocalUser -SID $u.SID', 'Set-LocalUser -Name $u.Name'))
        $pwMut2 = @(Test-Nep5SetPasswordWrite -Folder $mt)
        Chk 'account write (lock OFF): the one write changed from -SID to -Name in a copy is reported by the structure check' ($pwMut2.Count -ge 1 -and ($pwMut2 -join ' ') -match 'SID') 'account-guard'
    } finally { Remove-Item -LiteralPath $mt -Recurse -Force -ErrorAction SilentlyContinue }

    # --- the session password's order, the record, the probe copy
    $c = New-N5TestCtx
    try {
        $en = Enter-Nep5AccountSession -Ctx $c
        Chk 'session order: the session-open record already exists at the moment the password is written (the write is the last step), and the record is owned by the session that wrote it' ($en.Ok -and $c.AcctSw.RecordAtSet -eq $true -and $en.OwnsRecord -eq $true -and $c.AcctSw.Sets.Count -eq 1 -and $c.AcctSw.SetSids[0] -ceq $script:N5SpikeSid) 'account-guard'
        $null = Exit-Nep5AccountSession -Ctx $c
    } finally { Remove-Item -LiteralPath $c.Tmp -Recurse -Force -ErrorAction SilentlyContinue }
    $enAst = [Management.Automation.Language.Parser]::ParseFile((Join-Path $PSScriptRoot 'spike-nep5-run-lib.ps1'), [ref]$null, [ref]$null)
    $enFn = $enAst.Find({ param($n) $n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq 'Enter-Nep5AccountSession' }, $true)
    $posRec = @($enFn.FindAll({ param($n) $n -is [Management.Automation.Language.CommandAst] -and $n.GetCommandName() -eq 'Write-JsonGuarded' }, $true))[0].Extent.StartOffset
    $posPw = @($enFn.FindAll({ param($n) $n -is [Management.Automation.Language.InvokeMemberExpressionAst] -and "$($n.Member)" -eq 'SetPassword' }, $true))[0].Extent.StartOffset
    $posDry = @($enFn.FindAll({ param($n) $n -is [Management.Automation.Language.CommandAst] -and $n.GetCommandName() -eq 'Test-Nep5ProvisionPreconditions' }, $true))[0].Extent.StartOffset
    Chk 'structure: in Enter-Nep5AccountSession the restore preconditions come before the session-open record, and the record before the password write' (($posDry -lt $posRec) -and ($posRec -lt $posPw)) 'account-guard'
    $c = New-N5TestCtx
    try {
        $tamper = { param($dest) [IO.File]::AppendAllText($dest, "`n# tampered after the copy") }
        $ins1 = Install-Nep5ProbeScript -ScriptFolder $c.ScriptFolder -BinDir $c.BinDir -ExpectedSha $c.ProbeSha -AfterCopy $tamper
        Chk 'probe copy: a copy that does not hash like the source after the move is refused AND removed from the bin folder' ((-not $ins1.Ok) -and $ins1.Reason -match 'does not hash' -and -not (Test-Path -LiteralPath (Join-Path $c.BinDir $script:N5ProbeScriptName))) 'proof-hash-binding'
        $ins2 = Install-Nep5ProbeScript -ScriptFolder $c.ScriptFolder -BinDir $c.BinDir -ExpectedSha $c.ProbeSha
        Chk 'probe copy (lock OFF): the same call without tampering installs the copy, so the refusal above is the re-hash' ($ins2.Ok -and (Test-Path -LiteralPath (Join-Path $c.BinDir $script:N5ProbeScriptName))) 'proof-hash-binding'
    } finally { Remove-Item -LiteralPath $c.Tmp -Recurse -Force -ErrorAction SilentlyContinue }

    # --- A2: a refused session never deletes the record of the session that wrote it
    foreach ($ph in @('halfset', 'taskcheck', 'n1')) {
        $c = New-N5TestCtx
        try {
            if ($ph -eq 'halfset') { $c.Only = @('R0') }
            $en = Enter-Nep5AccountSession -Ctx $c
            $c.AccountOps = New-N5TestAccountOps -Sw $c.AcctSw -BinDir $c.BinDir   # the process died: nothing is remembered in memory
            [void]$c.PSObject.Properties.Remove('__taskSnap')
            $mp = Get-Nep5SessionMarkerPath -Ctx $c; $before = [IO.File]::ReadAllText($mp); $nset = $c.AcctSw.Sets.Count; $repN = $c.RepSw.Count; $dryN = $c.DrySw.Count
            $r2 = Invoke-Nep5Phase -Ctx $c -Phase $ph; $keep2 = (Test-Path -LiteralPath $mp) -and (([IO.File]::ReadAllText($mp)) -ceq $before)
            $r3 = Invoke-Nep5Phase -Ctx $c -Phase $ph; $keep3 = (Test-Path -LiteralPath $mp) -and (([IO.File]::ReadAllText($mp)) -ceq $before)
            $noChange = ($c.AcctSw.Sets.Count -eq $nset) -and ($c.RepSw.Count -eq $repN) -and ($c.DrySw.Count -eq $dryN) -and ($c.World.Filters.Count -eq 0)
            Chk "A2 ($ph): after a run died holding the session password, the 2nd run is REFUSED (exit 2) and so is the 3rd; the session-open record survives both unchanged; no password set, no re-provision, nothing added" ($en.Ok -and $r2.ExitCode -eq 2 -and $keep2 -and $r3.ExitCode -eq 2 -and $keep3 -and $noChange) 'session-record'
            $rtR = Resolve-Nep5RemoveTask -Ctx $c; $exR = $rtR.Ex; $repAtRemove = $c.RepSw.Count
            $r4 = Invoke-Nep5Phase -Ctx $c -Phase $ph
            Chk "A2 ($ph): -Remove's real task branch (Resolve-Nep5RemoveTask: a session record FORCES the re-provision, then the proof) clears the record and the next run is allowed to start: exit 0" ($rtR.HasSession -and $exR.TaskRestored -and -not (Test-Path -LiteralPath $mp) -and $repAtRemove -eq ($repN + 1) -and $r4.ExitCode -eq 0) 'session-record'
        } finally { Remove-Item -LiteralPath $c.Tmp -Recurse -Force -ErrorAction SilentlyContinue }
    }
    $c = New-N5TestCtx
    try {
        $mpX = Get-Nep5SessionMarkerPath -Ctx $c; [IO.File]::WriteAllText($mpX, '{"kind":"nep5-session-open","at":"x"}')
        $en = Enter-Nep5AccountSession -Ctx $c; $cl = Close-Nep5FailedSession -Ctx $c -Enter $en
        Chk 'A2 (unit): Close after a refusal because a record exists leaves the record, reports Untouched with NO claim of a restore (TaskRestored $null), and the owner flag is false' ((-not $en.Ok) -and $en.OwnsRecord -eq $false -and (Test-Path -LiteralPath $mpX) -and $cl.Untouched -and $null -eq $cl.TaskRestored -and $cl.SessionRecordKept) 'session-record'
        Remove-Item -LiteralPath $mpX -Force
        $c.AcctSw.UserSid = 'S-1-5-21-1-2-3-1001'; $en2 = Enter-Nep5AccountSession -Ctx $c; $cl2 = Close-Nep5FailedSession -Ctx $c -Enter $en2
        Chk 'A2 (unit): a session that wrote its own record and was then refused (wrong SID, nothing changed) deletes that record' ((-not $en2.Ok) -and $en2.OwnsRecord -eq $true -and -not (Test-Path -LiteralPath $mpX) -and $cl2.Untouched) 'session-record'
    } finally { Remove-Item -LiteralPath $c.Tmp -Recurse -Force -ErrorAction SilentlyContinue }

    # --- A8: the restore's own preconditions are checked before any password change
    $c = New-N5TestCtx
    try {
        $c.DrySw.Fail = $true
        $r = Invoke-Nep5Phase -Ctx $c -Phase 'taskcheck'
        Chk 'preconditions: when spike-provision.ps1 -DryRun says its preconditions do NOT hold, no password is set, no probe is installed, no session record is written, nothing is re-provisioned: class refused, exit 2, the reason carries the DryRun text' (($r.ExitCode -eq 2) -and $r.Records[0].class -eq 'refused' -and $c.AcctSw.Sets.Count -eq 0 -and $c.RepSw.Count -eq 0 -and $c.DrySw.Count -eq 1 -and -not (Test-Path -LiteralPath (Get-Nep5SessionMarkerPath -Ctx $c)) -and @(Get-Nep5BinResidue -BinDir $c.BinDir).Count -eq 0 -and $r.Records[0].reason -match 'stand-in precondition') 'precondition-dryrun'
        $c.DrySw.Fail = $false; $r = Invoke-Nep5Phase -Ctx $c -Phase 'taskcheck'
        Chk 'preconditions (lock OFF): with the DryRun passing the same phase proceeds, sets the password once and the DryRun ran exactly once before it' (($r.ExitCode -eq 0) -and $c.AcctSw.Sets.Count -eq 1 -and $c.DrySw.Count -eq 2 -and $c.DrySw.SetsAtCall -eq 0) 'precondition-dryrun'
    } finally { Remove-Item -LiteralPath $c.Tmp -Recurse -Force -ErrorAction SilentlyContinue }
    $c = New-N5TestCtx
    try {
        $c.PSObject.Properties.Remove('ProvisionDryRun')
        $r = Invoke-Nep5Phase -Ctx $c -Phase 'halfset'
        Chk 'preconditions: a run with no DryRun wired is refused before any password change (fail-closed), exit 2' (($r.ExitCode -eq 2) -and $c.AcctSw.Sets.Count -eq 0 -and $r.Records[0].reason -match 'no precondition check') 'precondition-dryrun'
        $c | Add-Member -NotePropertyName ProvisionDryRun -NotePropertyValue ({ param($x) throw 'the check blew up' }) -Force
        $r = Invoke-Nep5Phase -Ctx $c -Phase 'halfset'
        Chk 'preconditions: a DryRun that throws is a refusal, not a pass' (($r.ExitCode -eq 2) -and $c.AcctSw.Sets.Count -eq 0) 'precondition-dryrun'
    } finally { Remove-Item -LiteralPath $c.Tmp -Recurse -Force -ErrorAction SilentlyContinue }

    # --- A4: an exception in the taskcheck body still reports the restore
    $c = New-N5TestCtx
    try {
        $c.AccountRun = { param($runId, $request, $tick) throw 'Access is denied' }
        $c.RepSw.Fail = $true
        $r = Invoke-Nep5Phase -Ctx $c -Phase 'taskcheck'
        $out = (& { try { Get-Content -LiteralPath $r.ResultsPath -Raw } catch { '' } })
        Chk 'A4: an exception in the taskcheck body AND a failed restore is class task_not_restored, exit 9, the TASK NOT RESTORED text and the manual command are in the record, a results file was written, the session record stays' (($r.ExitCode -eq 9) -and $r.Records[0].class -eq 'task_not_restored' -and $r.Records[0].reason -match 'TASK NOT RESTORED' -and $out -match 'task_not_restored' -and (Test-Path -LiteralPath (Get-Nep5SessionMarkerPath -Ctx $c))) 'restore-proof'
    } finally { Remove-Item -LiteralPath $c.Tmp -Recurse -Force -ErrorAction SilentlyContinue }
    $c = New-N5TestCtx -NoMarker
    try {
        $c.AccountRun = { param($runId, $request, $tick) throw 'Access is denied' }
        $r = Invoke-Nep5Phase -Ctx $c -Phase 'taskcheck'
        Chk 'A4 (control): the same exception with a good restore is class inconclusive, exit 4, the results file is written, the task is restored and proven, no passed-record is written' (($r.ExitCode -eq 4) -and $r.Records[0].class -eq 'inconclusive' -and $r.Records[0].reason -match 'Access is denied' -and (Test-Path -LiteralPath $r.ResultsPath) -and $r.Records[0].steps.session_exit.TaskRestored -and -not (Test-Path -LiteralPath (Get-Nep5MarkerPath -Ctx $c))) 'restore-proof'
    } finally { Remove-Item -LiteralPath $c.Tmp -Recurse -Force -ErrorAction SilentlyContinue }

    # --- A5: -Check reads the session record and the task's last run
    $clean = [pscustomobject]@{ Stop = $false; Unreadable = $false; Clean = $true }
    Chk '-Check exit (A5): an open session record is 21 even when everything else reads clean, original and identical (never 20); without it the same inputs are 20' (((Get-Nep5CheckExit -Sweep $clean -TaskState 'original' -TaskDefMatch $true -SessionOpen $true) -eq 21) -and ((Get-Nep5CheckExit -Sweep $clean -TaskState 'original' -TaskDefMatch $true -SessionOpen $false) -eq 20))
    Chk '-Check exit (A5): a task whose last run was a logon failure is 21; task info that cannot be read is 22' (((Get-Nep5CheckExit -Sweep $clean -TaskState 'original' -TaskCredentialFailure $true) -eq 21) -and ((Get-Nep5CheckExit -Sweep $clean -TaskState 'original' -TaskInfoUnreadable $true) -eq 22))
    $vOk = Get-Nep5TaskInfoVerdict -Info ([pscustomobject]@{ State = 'Ready'; LastTaskResult = 0 }); $vNever = Get-Nep5TaskInfoVerdict -Info ([pscustomobject]@{ State = 'Ready'; LastTaskResult = 267011 })
    $vLogon = Get-Nep5TaskInfoVerdict -Info ([pscustomobject]@{ State = 'Ready'; LastTaskResult = 2147943726 }); $vOff = Get-Nep5TaskInfoVerdict -Info ([pscustomobject]@{ State = 'Disabled'; LastTaskResult = 0 }); $vNone = Get-Nep5TaskInfoVerdict -Info $null
    Chk 'task info (A5): last result 0 and "has not run" read as startable; 0x8007052E (logon failure) and a disabled task read as unable to start (and say so in words); no info is unreadable' ((-not $vOk.CredentialFailure) -and (-not $vNever.CredentialFailure) -and $vLogon.CredentialFailure -and $vLogon.Text -match 'CANNOT start' -and $vLogon.Text -match '0x8007052E' -and $vOff.CredentialFailure -and $vNone.Unreadable)
    $ckAst = [Management.Automation.Language.Parser]::ParseFile($PSCommandPath, [ref]$null, [ref]$null)
    $ckFn = $ckAst.Find({ param($n) $n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq 'Invoke-Check' }, $true)
    $ckCalls = @($ckFn.FindAll({ param($n) $n -is [Management.Automation.Language.CommandAst] }, $true))
    $ckExit = @($ckCalls | Where-Object { $_.GetCommandName() -eq 'Get-Nep5CheckExit' })
    $ckParams = @(); if ($ckExit.Count) { $ckParams = @($ckExit[0].CommandElements | Where-Object { $_ -is [Management.Automation.Language.CommandParameterAst] } | ForEach-Object { $_.ParameterName }) }
    Chk 'structure (A5): the real -Check reads the session-open record and passes it to the exit function, and reads the task info' (@($ckCalls | Where-Object { $_.GetCommandName() -eq 'Get-Nep5CheckSessionOpen' }).Count -ge 1 -and ($ckParams -contains 'SessionOpen') -and ($ckParams -contains 'TaskCredentialFailure') -and ($ckFn.Extent.Text -match '\.Info\(\)')) 'check-session'

    $sdA = Join-Path ([IO.Path]::GetTempPath()) ('nep5-sess-' + [guid]::NewGuid().ToString('N')); New-Item -ItemType Directory -Path $sdA | Out-Null
    try {
        $none = Get-Nep5CheckSessionOpen -FixedDir $sdA; [IO.File]::WriteAllText((Join-Path $sdA 'session-open-1763.json'), '{}'); $pres = Get-Nep5CheckSessionOpen -FixedDir $sdA
        $unr = Get-Nep5CheckSessionOpen -FixedDir $null
        Chk '-Check wiring (B7): the session-record read says "open" when the record is present AND when it cannot be read at all (an unreadable record is never clean); it says closed only for a readable folder without it' ((-not $none) -and $pres -and $unr) 'check-session'
        $ckClean = Get-Nep5CheckExit -Sweep $clean -TaskState 'original' -TaskDefMatch $true -SessionOpen $unr
        Chk '-Check wiring (B7): an unreadable session record drives the exit to 21, never 20' ($ckClean -eq 21) 'check-session'
    } finally { Remove-Item -LiteralPath $sdA -Recurse -Force -ErrorAction SilentlyContinue }
    $entryAst = [Management.Automation.Language.Parser]::ParseFile($PSCommandPath, [ref]$null, [ref]$null)
    $fnOf = { param($n) $entryAst.Find({ param($x) $x -is [Management.Automation.Language.FunctionDefinitionAst] -and $x.Name -eq $n }, $true) }
    $parOf = { param($cmd) @($cmd.CommandElements | Where-Object { $_ -is [Management.Automation.Language.CommandParameterAst] } | ForEach-Object { $_.ParameterName }) }
    $rmFn = & $fnOf 'Invoke-Remove'; $runFn = & $fnOf 'Invoke-Run'
    $rmSeam = @($rmFn.FindAll({ param($x) $x -is [Management.Automation.Language.CommandAst] -and $x.GetCommandName() -eq 'New-Nep5ProvisionSeams' }, $true)); $runSeam = @($runFn.FindAll({ param($x) $x -is [Management.Automation.Language.CommandAst] -and $x.GetCommandName() -eq 'New-Nep5ProvisionSeams' }, $true))
    $rmP = @(); if ($rmSeam.Count) { $rmP = & $parOf $rmSeam[0] }; $runP = @(); if ($runSeam.Count) { $runP = & $parOf $runSeam[0] }
    $need = @('Folder', 'ProvisionSha', 'LibSha', 'BinDir')
    Chk 'entry wiring (B7): -Remove and -Run each build their re-provision through New-Nep5ProvisionSeams with the folder, both proof hashes and the bin folder (so both call sites hash-check the dependencies)' ($rmSeam.Count -eq 1 -and $runSeam.Count -eq 1 -and (@($need | Where-Object { $rmP -notcontains $_ }).Count -eq 0) -and (@($need | Where-Object { $runP -notcontains $_ }).Count -eq 0)) 'seams'
    Chk '-Run wiring (B7): the run context takes BOTH seams from the builder: Reprovision and ProvisionDryRun (the DryRun precondition is wired)' (($runFn.Extent.Text -match 'Reprovision = \$seams\.Reprovision') -and ($runFn.Extent.Text -match 'ProvisionDryRun = \$seams\.ProvisionDryRun')) 'seams'
    Chk '-Remove wiring (B7): -Remove sets its context''s Reprovision from the builder and resolves its task branch through Resolve-Nep5RemoveTask (the function that forces the re-provision for a session record, driven above)' (($rmFn.Extent.Text -match 'Add-Member -NotePropertyName Reprovision -NotePropertyValue \$seams\.Reprovision') -and ($rmFn.Extent.Text -match 'Resolve-Nep5RemoveTask -Ctx \$ctx')) 'seams'
    $entryTxt = [IO.File]::ReadAllText($PSCommandPath)
    Chk 'module path (B6): under Windows PowerShell the entry point restores the caller''s PSModulePath in a finally after the run, and the reset keeps the original first' (($entryTxt -match '\$n5mpOrig = \$env:PSModulePath') -and ($entryTxt -match '(?s)finally \{[^}]*\$env:PSModulePath = \$n5mpOrig')) 'seams'
    $tsD = Join-Path ([IO.Path]::GetTempPath()) ('nep5-stamp-' + [guid]::NewGuid().ToString('N'))
    $tsAbsent = Get-Nep5TreeStamp -Path $tsD; New-Item -ItemType Directory -Path (Join-Path $tsD 'a') -Force | Out-Null; $ts0 = Get-Nep5TreeStamp -Path $tsD
    try {
        [IO.File]::WriteAllText((Join-Path $tsD 'a\f.txt'), 'x'); $ts1 = Get-Nep5TreeStamp -Path $tsD; [IO.File]::WriteAllText((Join-Path $tsD 'a\f.txt'), 'xy'); $ts2 = Get-Nep5TreeStamp -Path $tsD
        Chk 'self-test isolation (B2, unit): the fingerprint used to prove the real work folder untouched reads "<absent>" for a missing folder and changes when a file is created or grown, and is stable when nothing changes' (($tsAbsent -ceq '<absent>') -and ($ts0 -cne $ts1) -and ($ts1 -cne $ts2) -and ($ts2 -ceq (Get-Nep5TreeStamp -Path $tsD))) 'seams'
    } finally { Remove-Item -LiteralPath $tsD -Recurse -Force -ErrorAction SilentlyContinue }
    # --- the taskcheck record's proof stamp is an instant, written and read back through the real writer and reader (ConvertFrom-Json under PowerShell 7 returns a [datetime])
    $c = New-N5TestCtx -NoMarker
    try {
        $okStamps = @('2026-10-13T10:26:44.1234567-04:00', (Get-Date).ToString('o'), [datetimeoffset]::UtcNow.ToString('o'), '2026-10-13T14:26:44.9999999+00:00'); $badRead = @(); $typeSeen = ''
        foreach ($st in $okStamps) {
            $c.ProofStamp = $st; Write-Nep5TaskcheckMarker -Ctx $c -Ex ([pscustomobject]@{ DefinitionMatches = $true; StartedInOriginalForm = [pscustomobject]@{ Ok = $true } })
            $typeSeen = (ConvertFrom-Json ([IO.File]::ReadAllText((Get-Nep5MarkerPath -Ctx $c)))).proof_stamp.GetType().Name
            $pr = @(Test-Nep5TaskcheckMarker -Ctx $c); if ($pr.Count) { $badRead += "$st => $($pr -join '; ')" }
        }
        Chk "taskcheck stamp (live defect): a real ISO stamp (7-digit fraction, offset) written by the real writer and read back by the real reader under $($PSVersionTable.PSEdition) (the stamp reads back as [$typeSeen]) gives NO problem, for four stamps $(if ($badRead.Count) { '(PROBLEMS: ' + ($badRead -join ' | ') + ')' })" ($badRead.Count -eq 0) 'taskcheck-stamp'
        $c.ProofStamp = '2026-10-13T10:26:44.1234567-04:00'; Write-Nep5TaskcheckMarker -Ctx $c -Ex ([pscustomobject]@{ DefinitionMatches = $true; StartedInOriginalForm = [pscustomobject]@{ Ok = $true } })
        $other = @{ 'one second later' = '2026-10-13T10:26:45.1234567-04:00'; 'one minute later' = '2026-10-13T10:27:44.1234567-04:00'; 'one hour earlier' = '2026-10-13T09:26:44.1234567-04:00'; 'the same instant in another zone (accepted)' = '2026-10-13T14:26:44.1234567+00:00' }
        $res = @{}; foreach ($k in $other.Keys) { $c.ProofStamp = $other[$k]; $res[$k] = @(Test-Nep5TaskcheckMarker -Ctx $c | Where-Object { $_ -match 'another matrix proof' }).Count }
        Chk 'taskcheck stamp (strict): a different proof one second later, one minute later or one hour earlier still gives the "another matrix proof" problem; the same instant written with another offset is the same proof' (($res['one second later'] -eq 1) -and ($res['one minute later'] -eq 1) -and ($res['one hour earlier'] -eq 1) -and ($res['the same instant in another zone (accepted)'] -eq 0)) 'taskcheck-stamp'
        $c.ProofStamp = 'not-a-date'; $u1 = @(Test-Nep5TaskcheckMarker -Ctx $c).Count; $c.ProofStamp = $null; $u2 = @(Test-Nep5TaskcheckMarker -Ctx $c).Count
        $c.ProofStamp = '2026-10-13T10:26:44.1234567-04:00'; Write-JsonGuarded -Path (Get-Nep5MarkerPath -Ctx $c) -Object ([ordered]@{ kind = 'nep5-taskcheck-passed'; at = (Get-N5Now); proof_stamp = 'garbage'; definition_matches_baseline = $true; restored_task_started = $true }) -Depth 3
        $u3 = @(Test-Nep5TaskcheckMarker -Ctx $c).Count
        Chk 'taskcheck stamp (fail closed): an unreadable stamp on the context, a missing one, or an unreadable one in the record is a problem, never a match' (($u1 -ge 1) -and ($u2 -ge 1) -and ($u3 -ge 1)) 'taskcheck-stamp'
        Chk 'taskcheck stamp (helper): the instant helper reads a string, a [datetime] and a [datetimeoffset] of the same instant to the same second, truncates the fraction, and returns $null for text that is not an instant' ((ConvertTo-Nep5InstantSeconds '2026-10-13T10:26:44.9999999-04:00') -eq (ConvertTo-Nep5InstantSeconds ([datetime]'2026-10-13T10:26:44.1-04:00')) -and (ConvertTo-Nep5InstantSeconds ([datetimeoffset]'2026-10-13T10:26:44-04:00')) -eq (ConvertTo-Nep5InstantSeconds '2026-10-13T14:26:44Z') -and $null -eq (ConvertTo-Nep5InstantSeconds 'selftest-stamp') -and $null -eq (ConvertTo-Nep5InstantSeconds '') -and $null -eq (ConvertTo-Nep5InstantSeconds $null)) 'taskcheck-stamp'
    } finally { Remove-Item -LiteralPath $c.Tmp -Recurse -Force -ErrorAction SilentlyContinue }
    # --- A3: what the matrix records about the launch; A10: the password in no failure path
    $swL = & $mkSw; $opsL = & $mkOps $swL; $null = $opsL.SetPassword(); $rpL = $opsL.RunProbe(5, $null)
    Chk 'launch record (A3): every probe run records the logon type (interactive-type logon, not the batch logon of the existing task) and the environment variable NAMES supplied (names only), and the start received exactly that block' (($rpL.Launch.logon_type -match 'interactive') -and ($rpL.Launch.logon_type -match 'NOT the batch') -and ((@($rpL.Launch.environment_variable_names_supplied) -join ',') -ceq (@($script:N5AccountEnvAllow | Sort-Object) -join ',')) -and ((@($swL.EnvNames | Sort-Object) -join ',') -ceq (@($script:N5AccountEnvAllow | Sort-Object) -join ','))) 'account-env'
    $c = New-N5TestCtx
    try { $rtc = Invoke-Nep5Phase -Ctx $c -Phase 'taskcheck'
        Chk 'launch record (A3, B5): the taskcheck record carries the launch (logon type and variable names) of its identity probe AND of its connect probe' ($null -ne $rtc.Records[0].steps.identity.launch -and $rtc.Records[0].steps.identity.launch.logon_type -and $null -ne $rtc.Records[0].steps.connect.launch -and $rtc.Records[0].steps.connect.launch.logon_type) 'account-env'
    } finally { Remove-Item -LiteralPath $c.Tmp -Recurse -Force -ErrorAction SilentlyContinue }
    $leakScenarios = @(
        @{ n = 'the password write fails'; m = { param($c) $c.AcctSw.FailSet = $true }; ph = 'taskcheck' },
        @{ n = 'the account logon is refused at the start'; m = { param($c) $c.AcctSw.NoStart = $true; $c.AccountRun = New-Nep5RealAccountRun -BinDir $c.BinDir -ExpectedSid $script:N5SpikeSid -AccountOps $c.AccountOps -ResultsDir $c.Tmp -TimeoutSec 5 }; ph = 'taskcheck' },
        @{ n = 'the probe hangs and is killed'; m = { param($c) $c.AcctSw.Hang = $true; $c.AccountRun = New-Nep5RealAccountRun -BinDir $c.BinDir -ExpectedSid $script:N5SpikeSid -AccountOps $c.AccountOps -ResultsDir $c.Tmp -TimeoutSec 1 }; ph = 'taskcheck' },
        @{ n = 'the re-provision fails'; m = { param($c) $c.RepSw.Fail = $true }; ph = 'taskcheck' },
        @{ n = 'the restore damages the task'; m = { param($c) $c.RepSw.Damage = $true }; ph = 'taskcheck' },
        @{ n = 'a halfset phase whose restore fails'; m = { param($c) $c.RepSw.Fail = $true; $c.Only = @('R0') }; ph = 'halfset' })
    $leakMiss = @(); $leakNoSecret = @()
    foreach ($ls in $leakScenarios) {
        $c = New-N5TestCtx
        try {
            & $ls.m $c
            $rl = Invoke-Nep5Phase -Ctx $c -Phase $ls.ph
            $sec = [string]$c.AcctSw.Secret
            $blob = (ConvertTo-Json -InputObject @($rl.Records, @($c.AccountOps.Log), @($c.AcctSw.Starts)) -Depth 25) + "`n" + (Get-N5DirText -Dir $c.Tmp)
            if ($sec.Length -lt 20) { $leakNoSecret += $ls.n } elseif ($blob.Contains($sec)) { $leakMiss += $ls.n }
        } finally { Remove-Item -LiteralPath $c.Tmp -Recurse -Force -ErrorAction SilentlyContinue }
    }
    Chk "secret (A10): the generated password appears in no record, result file, log line, command line or file of the FAILURE paths either: $(($leakScenarios | ForEach-Object { $_.n }) -join '; ') $(if ($leakMiss.Count) { '(FOUND in: ' + ($leakMiss -join ', ') + ')' })$(if ($leakNoSecret.Count) { '(no password was generated in: ' + ($leakNoSecret -join ', ') + ')' })" (($leakMiss.Count -eq 0) -and ($leakNoSecret.Count -eq 0)) 'secret-not-recorded'
    Chk 'secret (A10, positive control): the failure-path scan DOES find the password when it is planted in a failure record' (((ConvertTo-Json -InputObject @{ reason = "setting the account password failed: bad value $($swL.Secret)" } -Depth 5)).Contains($swL.Secret)) 'secret-not-recorded'

    # --- A12: no switches without a caller; the normaliser compares every Settings element
    $exCmd = Get-Command Exit-Nep5AccountSession
    Chk 'structure (A12): Exit-Nep5AccountSession has no switch that skips the start check or forces a re-provision (-Remove forces one by setting Changed)' (($exCmd.Parameters.Keys -notcontains 'NoStartCheck') -and ($exCmd.Parameters.Keys -notcontains 'ForceReprovision'))
    $xmlC = $xmlA -replace '<Enabled>true</Enabled>', '<Enabled>true</Enabled><Hidden>false</Hidden><Priority>7</Priority><AllowHardTerminate>true</AllowHardTerminate><RestartOnFailure><Interval>PT1M</Interval><Count>3</Count></RestartOnFailure><IdleSettings><Duration>PT10M</Duration></IdleSettings>'
    $nC = ConvertTo-Nep5NormalizedTaskXml $xmlC
    $diffC = @(@{ n = 'Hidden'; x = ($xmlC -replace '<Hidden>false', '<Hidden>true') }, @{ n = 'Priority'; x = ($xmlC -replace '<Priority>7', '<Priority>5') }, @{ n = 'AllowHardTerminate'; x = ($xmlC -replace '<AllowHardTerminate>true', '<AllowHardTerminate>false') },
        @{ n = 'RestartOnFailure count'; x = ($xmlC -replace '<Count>3', '<Count>4') }, @{ n = 'RestartOnFailure removed'; x = ($xmlC -replace '<RestartOnFailure>.*</RestartOnFailure>', '') }, @{ n = 'idle duration'; x = ($xmlC -replace 'PT10M', 'PT20M') }) | Where-Object { (ConvertTo-Nep5NormalizedTaskXml $_.x) -ceq $nC } | ForEach-Object { $_.n }
    Chk "task XML (A12): a change to Hidden, Priority, AllowHardTerminate, RestartOnFailure (count or removal) or the idle settings is NOT equal $(if (@($diffC).Count) { '(equal anyway: ' + (@($diffC) -join ', ') + ')' })" (@($diffC).Count -eq 0)
    $secVars = @(@{ n = 'a Principal GroupId'; x = ($xmlA -replace '</Principal>', '<GroupId>S-1-1-0</GroupId></Principal>') }, @{ n = 'RequiredPrivileges'; x = ($xmlA -replace '</Principal>', '<RequiredPrivileges><Privilege>SeDebugPrivilege</Privilege></RequiredPrivileges></Principal>') },
        @{ n = 'Actions Context'; x = ($xmlA -replace '<Actions>', '<Actions Context="Other">') }, @{ n = 'a security descriptor'; x = ($xmlA -replace '</RegistrationInfo>', '<SecurityDescriptor>D:(A;;FA;;;WD)</SecurityDescriptor></RegistrationInfo>') }) | Where-Object { (ConvertTo-Nep5NormalizedTaskXml $_.x) -ceq $nA } | ForEach-Object { $_.n }
    Chk "task XML (B4): a Principal GroupId, RequiredPrivileges, an Actions Context or a security descriptor added to the task is NOT equal $(if (@($secVars).Count) { '(equal anyway: ' + (@($secVars) -join ', ') + ')' })" (@($secVars).Count -eq 0)

    Write-Host '== arguments, exit codes, structure ==' -ForegroundColor Cyan
    Chk 'args: no mode and two modes are errors; each single mode is valid; -Run needs -Phase; -Phase and -Only only with -Run; -WriteProof only with -SelfTest' (((Test-Nep5Args $false $false $false $false $false $false '' '').Count -ge 1) -and ((Test-Nep5Args $true $false $true $false $false $false '' '').Count -ge 1) -and ((Test-Nep5Args $true $false $false $false $false $false '' '').Count -eq 0) -and ((Test-Nep5Args $false $false $true $false $false $false '' '').Count -eq 0) -and ((Test-Nep5Args $false $false $false $true $false $false '' '').Count -eq 0) -and ((Test-Nep5Args $false $false $false $false $true $false '' '').Count -eq 0) -and ((Test-Nep5Args $false $false $false $false $false $true '' '').Count -ge 1) -and ((Test-Nep5Args $false $false $false $false $false $true 'halfset' '').Count -eq 0) -and ((Test-Nep5Args $false $false $true $false $false $false 'halfset' '').Count -ge 1) -and ((Test-Nep5Args $false $true $false $true $false $false '' '').Count -ge 1) -and ((Test-Nep5Args $false $false $false $false $false $true 'halfset' 'R1+R2').Count -eq 0) -and ((Test-Nep5Args $false $false $false $false $false $true 'halfset' 'O1').Count -ge 1) -and ((Test-Nep5Args $false $false $false $false $false $true 'halfset' 'R99').Count -ge 1) -and ((Test-Nep5Args $false $false $true $false $false $false '' 'R1').Count -ge 1))
    Chk '-Check exit codes: all clear 20; anything present or a task not original or files left 21; a STOP is 21 even if a read failed; any unreadable read 22' (((Get-Nep5CheckExit -Sweep ([pscustomobject]@{ Stop = $false; Unreadable = $false; Clean = $true }) -TaskState 'original') -eq 20) -and ((Get-Nep5CheckExit -Sweep ([pscustomobject]@{ Stop = $false; Unreadable = $false; Clean = $false }) -TaskState 'original') -eq 21) -and ((Get-Nep5CheckExit -Sweep ([pscustomobject]@{ Stop = $false; Unreadable = $false; Clean = $true }) -TaskState 'probe') -eq 21) -and ((Get-Nep5CheckExit -Sweep ([pscustomobject]@{ Stop = $false; Unreadable = $false; Clean = $true }) -TaskState 'original' -BinLeft @('halfset.exe')) -eq 21) -and ((Get-Nep5CheckExit -Sweep ([pscustomobject]@{ Stop = $true; Unreadable = $true; Clean = $false }) -TaskState 'original') -eq 21) -and ((Get-Nep5CheckExit -Sweep ([pscustomobject]@{ Stop = $false; Unreadable = $true; Clean = $false }) -TaskState 'original') -eq 22) -and ((Get-Nep5CheckExit -Sweep ([pscustomobject]@{ Stop = $false; Unreadable = $false; Clean = $true }) -TaskState 'unreadable:x') -eq 22))
    $cmdInfo = Get-Command $PSCommandPath
    Chk 'structure: there is no -Add mode and no switch that skips the proof; every phase is a member of the phase list' (($cmdInfo.Parameters.Keys -notcontains 'Add') -and ($cmdInfo.Parameters.Keys -notcontains 'SkipProof') -and ($cmdInfo.Parameters.Keys -notcontains 'NoProof') -and (@($script:N5States | Where-Object { $script:N5Phases -notcontains $_.Phase }).Count -eq 0) -and ($script:N5Phases -contains 'taskcheck'))
    $matrixText = Get-Content -LiteralPath $PSCommandPath -Raw; $runText = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'spike-nep5-run-lib.ps1') -Raw; $libText = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'spike-nep5-lib.ps1') -Raw
    $selfAst0 = [Management.Automation.Language.Parser]::ParseFile($PSCommandPath, [ref]$null, [ref]$null)
    $matrixLive = (@($selfAst0.FindAll({ param($n) $n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -notin @('Invoke-SelfTest', 'New-N5TestCtx') }, $false) | ForEach-Object { $_.Extent.Text }) -join "`n")
    $runAst = [Management.Automation.Language.Parser]::ParseFile((Join-Path $PSScriptRoot 'spike-nep5-run-lib.ps1'), [ref]$null, [ref]$null)
    $runInstallFns = @($runAst.FindAll({ param($n) $n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Extent.Text -match "@\('install'" }, $false) | ForEach-Object { $_.Name })
    Chk 'structure: no code outside the two proof-gated adders calls the backend''s AddSet/AddOne or builds an install vector (the run library and the matrix''s live functions only call the adders)' (($matrixLive -notmatch '\.AddSet\(|\.AddOne\(') -and ($runText -notmatch '\.AddSet\(|\.AddOne\(') -and ($runInstallFns.Count -eq 0) -and ($matrixLive -notmatch "@\('install'") -and ([regex]::Matches($libText, "@\('install', '--sublayer'").Count -eq 1) -and ([regex]::Matches($libText, '\$Backend\.AddSet\(').Count -eq 1) -and ([regex]::Matches($libText, '\$Backend\.AddOne\(').Count -eq 1))
    $guidRe = '[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}'
    $ownGuids = @([regex]::Matches($runText, $guidRe) | ForEach-Object { $_.Value })
    Chk 'structure: the run library names no GUID of its own (every sublayer, provider and filter key comes from the recorded tables)' ($ownGuids.Count -eq 0)
    $selfAst = [Management.Automation.Language.Parser]::ParseFile($PSCommandPath, [ref]$null, [ref]$null)
    $fnText = { param($name) ($selfAst.FindAll({ param($n) $n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq $name }, $true) | Select-Object -First 1).Extent.Text }
    $callRe = '\$\w+\s*=\s*New-Nep5RealBackend'
    Chk 'structure: neither -DryRun nor -SelfTest creates the real backend (the engine is opened by -Check, -Remove and -Run only)' (((& $fnText 'Invoke-DryRun') -notmatch $callRe) -and ((& $fnText 'Invoke-SelfTest') -notmatch $callRe) -and ((& $fnText 'Invoke-Run') -match $callRe) -and ((& $fnText 'Invoke-Check') -match $callRe))

    $realWorkAfter = Get-Nep5TreeStamp -Path $realWorkPath
    Chk 'self-test isolation (B2): this run left the real account work folder exactly as it was (same listing, sizes and last-write times, or still absent)' ($realWorkAfter -ceq $realWorkBefore)
    $passedTags = @($script:tagsPassed | Select-Object -Unique | Where-Object { $script:tagsFailed -notcontains $_ })
    if ($WriteProof) {
        Write-Host '== -WriteProof: the siblings'' self-tests, the harness refusal self-test (no engine), then the proof ==' -ForegroundColor Cyan
        $hostExe = (Get-Process -Id $PID).Path
        $sibResults = @()
        foreach ($s in @('spike-nep5-connect-probe.ps1')) {
            $out = (& $hostExe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot $s) -SelfTest 2>&1 | Out-String); $rc = $LASTEXITCODE
            $sibPassed = (($rc -eq 0) -and ($out -notmatch '\[FAIL\]') -and ($out -match 'all passed'))
            $sibResults += [ordered]@{ name = $s; passed = $sibPassed; checks = [regex]::Matches($out, '\[PASS\]').Count }
            Chk "sibling self-test passes: $s" $sibPassed
        }
        $hh = Get-N5HarnessHashes -Exe $HarnessExe -Source $HarnessSource -CargoLock $CargoLock
        $haveHarness = ($hh.exe_sha256 -and $hh.source_sha256 -and $hh.cargo_lock_sha256)
        Chk 'harness files readable (exe, halfset.rs, Cargo.lock) and the Cargo.lock is the pinned one' ([bool]$haveHarness -and $hh.cargo_lock_sha256 -eq $script:N5PinnedCargoLockSha256)
        $hc = $null
        if ($haveHarness) {
            $trace = Join-Path ([IO.Path]::GetTempPath()) ('nep5-trace-' + [guid]::NewGuid().ToString('N') + '.txt')
            try { $hc = Get-N5HarnessSelfChecks -Runner (New-HalfsetRunner -Exe $HarnessExe -ExpectedSha256 $hh.exe_sha256 -TracePath $trace) -TracePath $trace -LockSha256 $hh.cargo_lock_sha256 -RsSha256 $hh.source_sha256 } finally { Remove-Item -LiteralPath $trace -Force -ErrorAction SilentlyContinue }
            Chk 'the real harness: --version shows the pinned srt-win SHA and this Cargo.lock hash; selftest-refusals exits 0 with engine_opens 0; the engine-open trace file stayed empty' ($hc.version_ok -and $hc.refusals_exit_zero -and $hc.engine_open_trace_empty)
        }
        if ($script:f -eq 0 -and @($script:N5RequiredTags | Where-Object { $passedTags -contains $_ }).Count -eq $script:N5RequiredTags.Count -and $hc) {
            $hashes = Get-N5CodeSetHashes -Folder $PSScriptRoot
            $impReal = Import-WfpHelpers -Path $WfpScript -ExpectedSha256 $WfpSha256
            if ($hashes.Missing.Count) { Write-Host "NO PROOF WRITTEN: code-set file(s) missing: $($hashes.Missing -join ', ')" -ForegroundColor Red; $script:f++ }
            elseif ($impReal.Sha256 -ne $imp.Sha256) { Write-Host 'NO PROOF WRITTEN: the wrapped script changed between the self-test reads' -ForegroundColor Red; $script:f++ }
            else {
                # ORDER: the matrix proof first (it records the hash of the harness proof bytes that WILL be written), validated with the harness proof still STAGED; only then is the
                # harness proof renamed into place (temp then rename). No failure branch above or below ever writes the harness proof.
                $hlpObj = New-N5HarnessLiveProof -ExeSha $hh.exe_sha256 -RsSha $hh.source_sha256 -ChecksFailed $script:f
                $hlpBytes = (New-Object Text.UTF8Encoding($false)).GetBytes((ConvertTo-Json -InputObject $hlpObj -Depth 4))
                $sha = [Security.Cryptography.SHA256]::Create(); try { $hh['live_proof_sha256'] = ([BitConverter]::ToString($sha.ComputeHash($hlpBytes))) -replace '-', '' } finally { $sha.Dispose() }
                $obj = New-N5ProofObject -Hashes $hashes.Hashes -Harness $hh -PassedTags $passedTags -FailedChecks @() -HostInfo ("$($Host.Name) $($PSVersionTable.PSVersion) $($PSVersionTable.PSEdition) on $([Environment]::OSVersion.Version)") -When ((Get-Date).ToString('o')) -WrappedHash $imp.Sha256 -ChecksRun $script:chkTotal -ChecksPassed ($script:chkTotal - $script:f) -Siblings $sibResults -HarnessChecks ([ordered]@{ version_ok = $hc.version_ok; refusals_exit_zero = $hc.refusals_exit_zero; engine_open_trace_empty = $hc.engine_open_trace_empty; version_text = $hc.version_text })
                New-Item -ItemType Directory -Force (Split-Path $ProofPath -Parent) | Out-Null
                $staged = "$HarnessLiveProof.staged"
                [void](Remove-Nep5StagedHarnessProof -HarnessProof $HarnessLiveProof)
                Assert-PlainOutputPath -Path $staged; Assert-PlainOutputPath -Path $HarnessLiveProof
                Write-JsonGuarded -Path $ProofPath -Object $obj -Depth 8
                [IO.File]::WriteAllBytes($staged, $hlpBytes)
                $v1 = Test-N5Proof -ProofPath $ProofPath -Folder $PSScriptRoot -WrappedSha256 $imp.Sha256 -HarnessExe $HarnessExe -HarnessSource $HarnessSource -CargoLock $CargoLock -HarnessLiveProof $staged
                if (-not $v1.Ok) {
                    Remove-Item -LiteralPath $staged -Force -ErrorAction SilentlyContinue; Remove-Item -LiteralPath $ProofPath -Force -ErrorAction SilentlyContinue
                    Write-Host 'NO PROOF WRITTEN: the proof just written did not validate (removed; no harness proof was written):' -ForegroundColor Red; $v1.Problems | ForEach-Object { Write-Host "   $_" -ForegroundColor Red }; $script:f++
                } else {
                    Move-Item -LiteralPath $staged -Destination $HarnessLiveProof -Force
                    $v2 = Test-N5Proof -ProofPath $ProofPath -Folder $PSScriptRoot -WrappedSha256 $imp.Sha256 -HarnessExe $HarnessExe -HarnessSource $HarnessSource -CargoLock $CargoLock -HarnessLiveProof $HarnessLiveProof
                    if (-not $v2.Ok) {
                        Remove-Item -LiteralPath $HarnessLiveProof -Force -ErrorAction SilentlyContinue; Remove-Item -LiteralPath $ProofPath -Force -ErrorAction SilentlyContinue
                        Write-Host 'NO PROOF WRITTEN: validation after the rename failed (both files removed):' -ForegroundColor Red; $v2.Problems | ForEach-Object { Write-Host "   $_" -ForegroundColor Red }; $script:f++
                    } else {
                        Write-Host "PROOF WRITTEN: $ProofPath ($($hashes.Hashes.Count) scripts hashed, the wrapped script, the harness exe, halfset.rs and Cargo.lock hashed, $script:chkTotal checks run, $($passedTags.Count) rollback tags)" -ForegroundColor Green
                        Write-Host "HARNESS PROOF WRITTEN (after the matrix proof was written and validated; renamed into place): $HarnessLiveProof" -ForegroundColor Green
                    }
                }
            }
        } else { Write-Host 'NO PROOF WRITTEN: the self-test did not fully pass.' -ForegroundColor Red }
    }
    $script:N5LiveProof = $null
    Write-Host ("nep5 selftest: {0} ({1} checks run)" -f $(if ($script:f -eq 0) { 'all passed' } else { "$($script:f) FAILED" }), $script:chkTotal) -ForegroundColor $(if ($script:f -eq 0) { 'Green' } else { 'Red' })
    return $(if ($script:f -eq 0) { 0 } else { 1 })
}

# ---- entry -----------------------------------------------------------------------------------------------------------------------------------
$argErrors = @(Test-Nep5Args $SelfTest.IsPresent $WriteProof.IsPresent $DryRun.IsPresent $Check.IsPresent $Remove.IsPresent $Run.IsPresent $Phase $Only) + @(Test-Nep5ProofInFolder $ProofPath $PSScriptRoot)
if ($argErrors.Count) { $argErrors | ForEach-Object { Write-Host "ARG ERROR: $_" -ForegroundColor Red }; if ($PSVersionTable.PSEdition -eq 'Desktop' -and $null -ne $n5mpOrig) { $env:PSModulePath = $n5mpOrig }; exit 2 }
$n5rc = 2
try {
    if ($SelfTest) { $stRc = 1; try { $stRc = Invoke-SelfTest } catch { Write-Host "SELFTEST ABORTED (counted as a failure): $($_.Exception.Message)" -ForegroundColor Red; Write-Host $_.ScriptStackTrace -ForegroundColor DarkGray; $stRc = 1 }; $n5rc = $stRc }
    elseif ($DryRun) { $n5rc = (Invoke-DryRun) }
    elseif ($Check) { $n5rc = (Invoke-Check) }
    elseif ($Remove) { $n5rc = (Invoke-Remove) }
    elseif ($Run) { $n5rc = (Invoke-Run) }
} catch {
    Write-Host "STOPPED: $($_.Exception.Message)" -ForegroundColor Red
    Write-Host $_.ScriptStackTrace -ForegroundColor DarkGray
    $n5rc = 2
} finally {
    # the module-path reset above is for this process only: put the caller's value back (a 5.1 console that dot-runs this script keeps its own session)
    if ($PSVersionTable.PSEdition -eq 'Desktop' -and $null -ne $n5mpOrig) { $env:PSModulePath = $n5mpOrig }
}
exit $n5rc
