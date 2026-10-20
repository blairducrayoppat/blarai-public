#requires -Version 7.0
<#
.SYNOPSIS
  Runs the probe's offline tests. Builds the shipped and the guard-toggle exe with build-probe.ps1 into a new folder under
  the temp path (outside any git tree), runs `--version` on both and `selftest` and `selftest-process` on the shipped exe,
  prints the counts and exits 1 on any failure. The process-level rows live in the probe (`selftest-process`, README.md).
#>
[CmdletBinding()]
param([string]$WorkDir)
$ErrorActionPreference = 'Stop'

$parent = if ($WorkDir) { $WorkDir } else { [IO.Path]::GetTempPath() }
$work = Join-Path ([IO.Path]::GetFullPath($parent)) ('ncoprobe-selftest-' + [guid]::NewGuid().ToString('N'))
for ($p = $work; $p; $p = Split-Path -Parent $p) {
    if (Test-Path -LiteralPath (Join-Path $p '.git')) { throw "the work folder $work is inside a git tree ($p)" }
}
$build = Join-Path $PSScriptRoot 'build-probe.ps1'
$script:steps = 0
$script:stepFailures = 0
function Step([string]$Name, [bool]$Ok, [string]$Detail) {
    $script:steps++
    if (-not $Ok) { $script:stepFailures++ }
    Write-Host ("[{0}] {1} :: {2}" -f $(if ($Ok) { 'PASS' } else { 'FAIL' }), $Name, $Detail)
}
function Invoke-Probe([string]$Exe, [string[]]$Arguments) {
    $text = (& $Exe @Arguments) -join "`n"
    $code = $LASTEXITCODE
    $json = $null
    try { $json = $text | ConvertFrom-Json } catch { }
    return [pscustomobject]@{ Code = $code; Json = $json }
}

$trace = Join-Path $work 'no-such-folder\engine-open.trace'
$inner = [ordered]@{ selftest_run = 0; selftest_failed = 0; process_run = 0; process_failed = 0 }
$shipped = $null; $toggle = $null
try {
    $shipped = & $build -BuildDir $work | ConvertFrom-Json
    $toggle = & $build -BuildDir $work -Toggle | ConvertFrom-Json
    $env:NCOPROBE_ENGINE_OPEN_TRACE = $trace
    foreach ($b in $shipped, $toggle) {
        $v = Invoke-Probe $b.exe @('--version')
        Step "version.$(if ($b.toggle_build) { 'toggle' } else { 'shipped' })" ($v.Code -eq 0 -and $v.Json.probe_exe_sha256 -eq $b.exe_sha256 -and $v.Json.probe_cs_sha256 -eq $b.cs_sha256 -and $v.Json.toggle_build -eq $b.toggle_build) "exit $($v.Code), exe $($v.Json.probe_exe_sha256)"
    }
    $st = Invoke-Probe $shipped.exe @('selftest')
    Step 'selftest' ($st.Code -eq 0 -and $st.Json.checks_failed -eq 0) "exit $($st.Code), checks_run $($st.Json.checks_run), checks_failed $($st.Json.checks_failed)"
    $sp = Invoke-Probe $shipped.exe @('selftest-process', '--exe-dir', $work)
    Step 'selftest-process' ($sp.Code -eq 0 -and $sp.Json.checks_failed -eq 0) "exit $($sp.Code), checks_run $($sp.Json.checks_run), checks_failed $($sp.Json.checks_failed)"
    foreach ($f in @($st.Json.failures) + @($sp.Json.failures)) { if ($f) { Write-Host "  failed: $($f.check) :: $($f.detail)" } }
    $inner.selftest_run = [int]$st.Json.checks_run; $inner.selftest_failed = [int]$st.Json.checks_failed
    $inner.process_run = [int]$sp.Json.checks_run; $inner.process_failed = [int]$sp.Json.checks_failed
    Step 'engine_open_trace_absent' (-not (Test-Path -LiteralPath $trace)) $trace
} catch {
    Step 'runner' $false $_.Exception.Message
} finally {
    Remove-Item Env:NCOPROBE_ENGINE_OPEN_TRACE -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $work -Recurse -Force -ErrorAction SilentlyContinue
}
$run = $script:steps + $inner.selftest_run + $inner.process_run
$failed = $script:stepFailures + $inner.selftest_failed + $inner.process_failed
Write-Host "checks_run $run / checks_failed $failed"
[ordered]@{ checks_run = $run; checks_failed = $failed; runner_steps = $script:steps; selftest_checks = $inner.selftest_run; selftest_process_checks = $inner.process_run
    shipped_exe_sha256 = $shipped.exe_sha256; toggle_exe_sha256 = $toggle.exe_sha256; cs_sha256 = $shipped.cs_sha256 } | ConvertTo-Json -Compress
exit $(if ($failed -eq 0) { 0 } else { 1 })
