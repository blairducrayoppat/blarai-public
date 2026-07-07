<#
.SYNOPSIS
  Capture ONE co-residency run in the FOREGROUND under Intel UT, then extract
  per-phase socwatch + level-zero (remapped) metrics for that run.

.DESCRIPTION
  A foreground single-run companion to run_coresident_ut_sweep.ps1. Used when
  background UT tasks are being reaped by the environment: a foreground capture
  completes within one call and can't be killed at a turn boundary. Sources
  ut-vars, runs ut.exe over benchmark_coresident.py for one tag, then extracts
  socwatch (per-phase power/thermal) and l0_gpu (per-phase GPU freq/busy/bandwidth
  via the --remap-from clock fix). LOCALAPPDATA is redirected off the live store.

.EXAMPLE
  .\scripts\capture_one.ps1 -Tag vlm_r1 -Partner vlm -OutDir <scratch>\coresident\ut_hardened
#>
param(
  [Parameter(Mandatory)][string]$Tag,
  [Parameter(Mandatory)][string]$Partner,
  [Parameter(Mandatory)][string]$OutDir,
  [int]$CooldownS = 0
)
$ErrorActionPreference = "Continue"

$ut = $env:INTEL_UT_HOME
if (-not $ut -or -not (Test-Path "$ut\bin\ut.exe")) { $ut = "C:\Users\mrbla\tools\intel-ut\ut-tool-ext-v0.2.0-beta1.1" }
. "$ut\ut-vars.ps1" | Out-Null
$b2p = "$ut\bin\bin2perfetto.exe"

$repo = Split-Path -Parent $PSScriptRoot
$py = "$repo\.venv\Scripts\python.exe"
$harness = "$repo\scripts\benchmark_coresident.py"
$ex = "$repo\scripts\extract_ut_metrics.py"
$perf = "$repo\docs\performance"

New-Item -ItemType Directory -Force $OutDir | Out-Null
$root = Split-Path -Parent $OutDir
New-Item -ItemType Directory -Force "$root\localappdata" | Out-Null
$env:LOCALAPPDATA = "$root\localappdata"   # keep the harness off the real session store

$prefix = "$OutDir\ut_$Tag"
Remove-Item "$prefix*" -ErrorAction SilentlyContinue
Remove-Item "$perf\benchmark_coresident_${Tag}_*.json" -ErrorAction SilentlyContinue

Write-Host "=== [$Tag] FOREGROUND capture START $(Get-Date -Format o) ==="
& "$ut\bin\ut.exe" -o $prefix --config-level medium --enable socwatch,level-zero `
    -a "$py $harness --partners $Partner --out-tag $Tag"
Write-Host "=== [$Tag] ut exit $LASTEXITCODE ==="

$hj = Get-ChildItem "$perf\benchmark_coresident_${Tag}_*.json" -ErrorAction SilentlyContinue |
      Sort-Object LastWriteTime -Descending | Select-Object -First 1
if ($hj) {
  if (Test-Path "$prefix.socwatch.bin") {
    & $py $ex --bin "$prefix.socwatch.bin" --bin2perfetto $b2p --harness $hj.FullName --out "$prefix.socwatch.metrics.json"
  }
  if ((Test-Path "$prefix.l0_gpu.bin") -and (Test-Path "$prefix.socwatch.bin")) {
    & $py $ex --bin "$prefix.l0_gpu.bin" --bin2perfetto $b2p --remap-from "$prefix.socwatch.bin" `
        --harness $hj.FullName --out "$prefix.l0.metrics.json"
  }
} else { Write-Host "  [WARN] no harness JSON produced for $Tag" }
if ($CooldownS -gt 0) { Start-Sleep -Seconds $CooldownS }
Write-Host "=== [$Tag] DONE ==="
