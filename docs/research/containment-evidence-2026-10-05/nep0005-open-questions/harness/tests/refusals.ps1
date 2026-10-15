#requires -Version 5.1
<#
.SYNOPSIS
  Offline refusal tests for the halfset harness. Every invocation here is `--version`, `selftest-refusals`, or an
  invocation a guard refuses before any engine call. Refusal rows assert that the engine-open trace file
  (HALFSET_ENGINE_OPEN_TRACE) is empty or absent; rows that run the shipped exe with a mutating subcommand point the
  trace variable at a directory instead, so the exe exits 13 before any engine open whatever the guard under test does,
  and a bypass shows as exit 13 against the expected code.

.DESCRIPTION
  Part A (shipped exe): --version provenance, selftest-refusals (fake environments, fake filter source, engine-open
  count 0), wrong-sublayer refusals for every subcommand (exit 3), SID refusals for `install` using the real caller user
  SID, every SID in the caller's token groups, well-known SIDs and garbage (exit 4), usage errors (exit 2), and a byte
  scan proving the shipped exe does not contain the toggle variable name.

  Part B (toggle exe, built with --cfg halfset_toggle, which can never open the engine): proves each test above would
  fail if its guard were removed. With the guard switched off by HALFSET_TOGGLE_OFF the same invocation is no longer
  refused with the expected code and reaches an engine entry point (the trace file is non-empty); the toggle exe's own
  selftest-refusals fails and names the check that caught it. Without the variable the toggle exe refuses like the
  shipped exe.

  Arming interlock rows: each of the four mutating subcommands is invoked with a valid sublayer (and, for install, the
  recorded blarai-spike SID) ONLY with the --live token absent or invalid (no argument, a missing path, a non-JSON file,
  a proof naming a different exe hash, a wrong schema). They must exit 12 with an empty engine-open trace. This script
  never writes a proof that names the real exe hash, so no row here can arm a mutating subcommand. The toggle exe rows
  prove those rows fail with the interlock switched off.

  Source binding: the sha256 of halfset.rs beside this script is computed here and both exes must report it in
  --version; each exe's own sha256 must equal the one build-harness.ps1 recorded for it.

  Exit 0 only when every check passes.
#>
[CmdletBinding()]
param(
    [string]$Exe       = 'C:/Users/_OPERATOR_/rust-bootstrap/halfset-build/target/debug/examples/halfset.exe',
    [string]$ToggleExe = 'C:/Users/_OPERATOR_/rust-bootstrap/halfset-build/target-toggle/debug/examples/halfset.exe',
    [string]$BuildDir = 'C:/Users/_OPERATOR_/rust-bootstrap/halfset-build'
)
$ErrorActionPreference = 'Stop'

foreach ($p in $Exe, $ToggleExe) {
    if (-not (Test-Path -LiteralPath $p)) { throw "missing exe $p (run harness/build-harness.ps1, and with -Toggle for the toggle exe)" }
}

$S1 = 'c971a69f-d6ab-4885-9b49-506d8aa51c86'
$SrtDefault = '2c5d0ad6-5f3b-4d4e-9b8f-1a3e7c9d0b21'
$OldArm3 = '7e1f6a10-5c0b-4d8e-9a31-2b6d4c8e3f02'
$RandomGuid = 'deadbeef-0000-4000-8000-000000000001'
$SpikeSid = 'S-1-5-21-1000000001-1000000002-1000000003-1271'
$KEY = '11111111-2222-3333-4444-555555555555'

$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$operatorSid = $identity.User.Value
$groupSids = @($identity.Groups | ForEach-Object { $_.Value })

$harnessDir = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$rsPath = Join-Path $harnessDir 'halfset.rs'
$rsSha = (Get-FileHash -Algorithm SHA256 -LiteralPath $rsPath).Hash.ToLowerInvariant()
$proofDir = Join-Path ([IO.Path]::GetTempPath()) ("halfset-proofs-{0}" -f [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Force -Path $proofDir | Out-Null

$script:results = New-Object System.Collections.Generic.List[object]
$trace = Join-Path ([IO.Path]::GetTempPath()) ("halfset-trace-{0}.txt" -f [guid]::NewGuid().ToString('N'))

function Invoke-Halfset {
    param([string]$Path, [string[]]$Arguments, [hashtable]$Env = @{}, [switch]$TraceIsDirectory)
    if (Test-Path -LiteralPath $trace) { Remove-Item -LiteralPath $trace -Force }
    # A directory as the trace path makes every engine entry exit 13 before the engine is touched, so a row that
    # should be refused cannot reach the engine even if the guard under test is wrong.
    $env:HALFSET_ENGINE_OPEN_TRACE = if ($TraceIsDirectory) { $proofDir } else { $trace }
    foreach ($k in $Env.Keys) { Set-Item -Path "Env:$k" -Value $Env[$k] }
    try {
        $out = & $Path @Arguments 2>&1 | Out-String
        $code = $LASTEXITCODE
    } finally {
        Remove-Item Env:HALFSET_ENGINE_OPEN_TRACE -ErrorAction SilentlyContinue
        foreach ($k in $Env.Keys) { Remove-Item -Path "Env:$k" -ErrorAction SilentlyContinue }
    }
    $traced = (Test-Path -LiteralPath $trace) -and ((Get-Item -LiteralPath $trace).Length -gt 0)
    $json = $null
    try { $json = $out | ConvertFrom-Json } catch { }
    [pscustomobject]@{ Code = $code; Out = $out.Trim(); Json = $json; Traced = $traced }
}

function Add-Result([string]$Name, [bool]$Ok, [string]$Detail) {
    $script:results.Add([pscustomobject]@{ check = $Name; ok = $Ok; detail = $Detail })
    $tag = if ($Ok) { 'PASS' } else { 'FAIL' }
    Write-Host ("[{0}] {1} :: {2}" -f $tag, $Name, $Detail)
}

# A refusal case: expected exit code, engine never touched.
function Test-Refused([string]$Name, [string]$Path, [string[]]$Arguments, [int]$WantExit) {
    # The shipped exe running a mutating subcommand always gets a directory trace path: a bypass of the guard under
    # test then shows as exit 13 and never touches the engine. Other rows assert an empty trace file.
    $directory = ($Path -eq $Exe) -and ($Arguments.Count -gt 0) -and (@('install', 'delete-filter', 'delete-sublayer', 'uninstall') -contains $Arguments[0])
    if ($directory) {
        $r = Invoke-Halfset -Path $Path -Arguments $Arguments -TraceIsDirectory
        $ok = ($r.Code -eq $WantExit)
        Add-Result $Name $ok ("exit {0} (want {1}; 13 would mean the engine entry was reached), trace path is a directory" -f $r.Code, $WantExit)
        return
    }
    $r = Invoke-Halfset -Path $Path -Arguments $Arguments
    $ok = ($r.Code -eq $WantExit) -and (-not $r.Traced)
    Add-Result $Name $ok ("exit {0} (want {1}), engine_open_trace={2}" -f $r.Code, $WantExit, $r.Traced)
}

# A toggle case: with the guard off the same invocation must not produce the refusal and must reach an engine entry.
function Test-GuardOffReachesEngine([string]$Name, [string[]]$Arguments, [string]$Guard, [int]$RefusalExit) {
    $r = Invoke-Halfset -Path $ToggleExe -Arguments $Arguments -Env @{ HALFSET_TOGGLE_OFF = $Guard }
    $ok = ($r.Code -ne $RefusalExit) -and $r.Traced
    Add-Result $Name $ok ("guard '{0}' off: exit {1} (refusal was {2}), engine entry reached={3}" -f $Guard, $r.Code, $RefusalExit, $r.Traced)
}

# ---------------- Source binding ----------------
$vt0 = Invoke-Halfset -Path $ToggleExe -Arguments @('--version')
$v0 = Invoke-Halfset -Path $Exe -Arguments @('--version')
Add-Result 'S.shipped_exe_reports_source_sha256' ($v0.Json.halfset_rs_sha256 -eq $rsSha) "exe $($v0.Json.halfset_rs_sha256) vs halfset.rs $rsSha"
Add-Result 'S.toggle_exe_reports_source_sha256' ($vt0.Json.halfset_rs_sha256 -eq $rsSha) "exe $($vt0.Json.halfset_rs_sha256) vs halfset.rs $rsSha"
foreach ($pair in @(@('shipped', $Exe), @('toggle', $ToggleExe))) {
    $recPath = Join-Path $BuildDir ("build-record-{0}.json" -f $pair[0])
    $haveRec = Test-Path -LiteralPath $recPath
    $recOk = $false
    $detail = "no build record at $recPath"
    if ($haveRec) {
        $rec = Get-Content -LiteralPath $recPath -Raw | ConvertFrom-Json
        $actual = (Get-FileHash -Algorithm SHA256 -LiteralPath $pair[1]).Hash.ToLowerInvariant()
        $recOk = ($rec.exe_sha256 -eq $actual) -and ($rec.halfset_rs_sha256 -eq $rsSha)
        $detail = "recorded exe $($rec.exe_sha256), actual $actual, recorded source $($rec.halfset_rs_sha256)"
    }
    Add-Result "S.$($pair[0])_exe_is_what_the_build_script_printed" $recOk $detail
}

# ---------------- Part A: shipped exe ----------------
$v = Invoke-Halfset -Path $Exe -Arguments @('--version')
Add-Result 'A.version_exit_0' ($v.Code -eq 0) "exit $($v.Code)"
Add-Result 'A.version_pinned_sha' ($v.Json.pinned_srt_win_sha -eq '24eb39e94a6de386e83d126c52317d8e0fa49522') "$($v.Json.pinned_srt_win_sha)"
Add-Result 'A.version_lock_sha256_embedded' ($v.Json.pinned_cargo_lock_sha256 -match '^[0-9a-f]{64}$') "$($v.Json.pinned_cargo_lock_sha256)"
Add-Result 'A.version_not_toggle_build' ($v.Json.toggle_build -eq $false) "toggle_build=$($v.Json.toggle_build)"

$st = Invoke-Halfset -Path $Exe -Arguments @('selftest-refusals')
Add-Result 'A.selftest_refusals_pass' (($st.Code -eq 0) -and $st.Json.ok -and ($st.Json.failed -eq 0) -and ($st.Json.engine_opens -eq 0) -and (-not $st.Traced)) `
    ("exit {0}, checks {1}, failed {2}, engine_opens {3}" -f $st.Code, $st.Json.total, $st.Json.failed, $st.Json.engine_opens)

foreach ($sub in 'status', 'enum', 'delete-filter', 'delete-sublayer', 'uninstall', 'install') {
    foreach ($bad in @(@('srt_default', $SrtDefault), @('old_arm3', $OldArm3), @('random', $RandomGuid))) {
        $a = @($sub, '--sublayer', $bad[1])
        if ($sub -eq 'delete-filter') { $a += @('--key', $KEY) }
        if ($sub -eq 'install') { $a += @('--sid', $SpikeSid) }
        Test-Refused "A.sublayer_refused.$sub.$($bad[0])" $Exe $a 3
    }
}
Test-Refused 'A.sublayer_refused_wins_over_sid.install' $Exe @('install', '--sublayer', $SrtDefault, '--sid', $operatorSid) 3

Test-Refused 'A.sid_refused.operator_user_sid' $Exe @('install', '--sublayer', $S1, '--sid', $operatorSid) 4
$i = 0
foreach ($g in $groupSids) {
    $i++
    Test-Refused "A.sid_refused.token_group_$i" $Exe @('install', '--sublayer', $S1, '--sid', $g) 4
}
Add-Result 'A.sid_token_groups_enumerated' ($groupSids.Count -gt 0) "$($groupSids.Count) group SIDs in the caller's token"
foreach ($w in 'S-1-1-0', 'S-1-5-18', 'S-1-5-32-544', 'S-1-5-32-545', 'S-1-5-11', 'S-1-5-21-9-9-9-9999', 'garbage') {
    Test-Refused "A.sid_refused.other_$w" $Exe @('install', '--sublayer', $S1, '--sid', $w) 4
}
Test-Refused 'A.sid_refused.lowercase_spike_sid' $Exe @('install', '--sublayer', $S1, '--sid', $SpikeSid.ToLowerInvariant()) 4

Test-Refused 'A.usage.no_args' $Exe @() 2
Test-Refused 'A.usage.unknown_subcommand' $Exe @('frobnicate') 2
Test-Refused 'A.usage.install_without_sid' $Exe @('install', '--sublayer', $S1) 2
Test-Refused 'A.usage.install_bad_guid' $Exe @('install', '--sublayer', 'not-a-guid', '--sid', $SpikeSid) 2
Test-Refused 'A.usage.unknown_flag' $Exe @('status', '--sublayer', $S1, '--bogus') 2
Test-Refused 'A.usage.sid_on_status' $Exe @('status', '--sublayer', $S1, '--sid', $SpikeSid) 2

# Arming interlock: the token is absent or invalid in every row. Valid S1 and the recorded spike SID appear only here.
$wrongExeProof = Join-Path $proofDir 'wrong-exe-hash.json'
$wrongSchemaProof = Join-Path $proofDir 'wrong-schema.json'
$garbageProof = Join-Path $proofDir 'garbage.json'
$now = (Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ')
$bogusExe = ('f' * 64)
Set-Content -LiteralPath $wrongExeProof -Value ('{"schema":"nep5-1763-proof-v1","halfset_exe_sha256":"' + $bogusExe + '","halfset_rs_sha256":"' + $rsSha + '","checks_failed":0,"written_utc":"' + $now + '"}')
Set-Content -LiteralPath $wrongSchemaProof -Value ('{"schema":"other","halfset_exe_sha256":"' + $bogusExe + '","halfset_rs_sha256":"' + $rsSha + '","checks_failed":0,"written_utc":"' + $now + '"}')
Set-Content -LiteralPath $garbageProof -Value 'not json'
$missingProof = Join-Path $proofDir 'does-not-exist.json'
$mutating = @(
    @('install', @('install', '--sublayer', $S1, '--sid', $SpikeSid)),
    @('delete-filter', @('delete-filter', '--sublayer', $S1, '--key', $KEY)),
    @('delete-sublayer', @('delete-sublayer', '--sublayer', $S1)),
    @('uninstall', @('uninstall', '--sublayer', $S1))
)
$tokens = @(
    @('no_token', @()),
    @('missing_path', @('--live', $missingProof)),
    @('garbage_file', @('--live', $garbageProof)),
    @('wrong_exe_hash', @('--live', $wrongExeProof)),
    @('wrong_schema', @('--live', $wrongSchemaProof))
)
foreach ($m in $mutating) {
    foreach ($t in $tokens) {
        Test-Refused "A.not_armed.$($m[0]).$($t[0])" $Exe ($m[1] + $t[1]) 12
    }
}
Test-Refused 'A.usage.live_on_status' $Exe @('status', '--sublayer', $S1, '--live', $missingProof) 2
Test-Refused 'A.usage.live_on_enum' $Exe @('enum', '--sublayer', $S1, '--live', $missingProof) 2
Test-Refused 'A.usage.all_ours_rejects_sublayer' $Exe @('enum', '--all-ours', '--sublayer', $S1) 2
Test-Refused 'A.usage.all_ours_rejects_bad_sublayer' $Exe @('enum', '--all-ours', '--sublayer', 'not-a-guid') 2

$bytes = [IO.File]::ReadAllBytes($Exe)
$latin = [Text.Encoding]::GetEncoding(28591).GetString($bytes)
Add-Result 'A.shipped_exe_has_no_toggle_variable' (-not $latin.Contains('HALFSET_TOGGLE_OFF')) 'byte scan of the shipped exe for the toggle variable name'
$bytesT = [IO.File]::ReadAllBytes($ToggleExe)
$latinT = [Text.Encoding]::GetEncoding(28591).GetString($bytesT)
Add-Result 'A.toggle_exe_has_toggle_variable' ($latinT.Contains('HALFSET_TOGGLE_OFF')) 'control: the scan can find the name where it exists'

# ---------------- Part B: toggle exe ----------------
$tv = Invoke-Halfset -Path $ToggleExe -Arguments @('--version')
Add-Result 'B.toggle_exe_reports_toggle_build' ($tv.Json.toggle_build -eq $true) "toggle_build=$($tv.Json.toggle_build)"

# Control: with no toggle set the toggle exe refuses exactly as the shipped exe does.
Test-Refused 'B.control.sublayer_refused' $ToggleExe @('install', '--sublayer', $SrtDefault, '--sid', $SpikeSid) 3
Test-Refused 'B.control.sid_refused' $ToggleExe @('install', '--sublayer', $S1, '--sid', $operatorSid) 4

# Guards removed: the process-level tests above would fail.
Test-GuardOffReachesEngine 'B.toggle.sublayer_guard_removed' @('status', '--sublayer', $SrtDefault) 'sublayer' 3
Test-GuardOffReachesEngine 'B.toggle.sid_guard_removed_operator' @('install', '--sublayer', $S1, '--sid', $operatorSid) 'sid,interlock' 4
if ($groupSids.Count -gt 0) {
    Test-GuardOffReachesEngine 'B.toggle.sid_guard_removed_token_group' @('install', '--sublayer', $S1, '--sid', $groupSids[0]) 'sid,interlock' 4
}
Test-GuardOffReachesEngine 'B.toggle.sid_guard_removed_wellknown' @('install', '--sublayer', $S1, '--sid', 'S-1-5-32-544') 'sid,interlock' 4

# Interlock removed: the not-armed rows fail (token absent in every row; the toggle exe cannot open the engine).
foreach ($m in $mutating) {
    Test-GuardOffReachesEngine "B.toggle.interlock_removed.$($m[0]).no_token" $m[1] 'interlock' 12
    Test-GuardOffReachesEngine "B.toggle.interlock_removed.$($m[0]).wrong_exe_hash" ($m[1] + @('--live', $wrongExeProof)) 'interlock' 12
}
Test-Refused 'B.control.interlock_refuses_untoggled.install' $ToggleExe @('install', '--sublayer', $S1, '--sid', $SpikeSid) 12
Test-Refused 'B.control.interlock_refuses_untoggled.uninstall' $ToggleExe @('uninstall', '--sublayer', $S1) 12

# Guards removed: the selftest (fake environments / fake filter source) fails and names the check.
foreach ($case in @(
        @('sublayer', 'sublayer_srt_default_refused'),
        @('sid', 'sid_operator_refused'),
        @('sid_lookup', 'sid_spike_lookup_mismatch_refused'),
        @('nonempty', 'nonempty_one_filter_refused'),
        @('stop_sweep', 'sweep_name_srt_win_elsewhere_stops'),
        @('interlock', 'arm_missing_token_refused'))) {
    $r = Invoke-Halfset -Path $ToggleExe -Arguments @('selftest-refusals') -Env @{ HALFSET_TOGGLE_OFF = $case[0] }
    $failedNames = @()
    if ($r.Json) { $failedNames = @($r.Json.checks | Where-Object { -not $_.ok } | ForEach-Object { $_.check }) }
    $ok = ($r.Code -eq 1) -and ($failedNames -contains $case[1])
    Add-Result "B.toggle.selftest_fails_without_guard_$($case[0])" $ok ("exit {0}, failed checks: {1}" -f $r.Code, ($failedNames -join ','))
}
$r = Invoke-Halfset -Path $ToggleExe -Arguments @('selftest-refusals')
Add-Result 'B.control.toggle_exe_selftest_passes_untoggled' (($r.Code -eq 0) -and ($r.Json.failed -eq 0)) "exit $($r.Code)"

if (Test-Path -LiteralPath $trace) { Remove-Item -LiteralPath $trace -Force }
Remove-Item -LiteralPath $proofDir -Recurse -Force
$failed = @($script:results | Where-Object { -not $_.ok })
Write-Host ("SUMMARY: {0} checks, {1} failed" -f $script:results.Count, $failed.Count)
[pscustomobject]@{ total = $script:results.Count; failed = $failed.Count; failed_checks = @($failed | ForEach-Object { $_.check }) } | ConvertTo-Json -Compress
if ($failed.Count -gt 0) { exit 1 }
exit 0
