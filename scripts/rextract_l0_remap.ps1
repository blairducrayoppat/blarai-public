<#
.SYNOPSIS
  Step 2 of the hardened co-residency plan: RE-EXTRACT every l0_gpu bin PER-PHASE
  using the matching socwatch bin's Unix-epoch clock as a linear remap anchor.

.DESCRIPTION
  level-zero sample timestamps are on a different clock than socwatch's Unix-epoch
  ns (the UT "timestamp-units" driver caveat), so a plain extract leaves l0 metrics
  with only a 'whole' bucket — no idle/contention split. extract_ut_metrics.py's
  --remap-from linearly maps the l0 clock onto the socwatch Unix window captured in
  the SAME ut.exe session, restoring per-phase segmentation for GPU frequency /
  busy / bandwidth. This re-runs that for all already-captured bins; the runner is
  separately patched to pass --remap-from for future sweeps.

  Run AFTER the sweep's done.marker exists (bin2perfetto is heavy; never run it
  while ut.exe is actively capturing — it contaminates the power telemetry).

.EXAMPLE
  .\scripts\rextract_l0_remap.ps1 -OutDir <scratch>\coresident\ut_hardened
#>
param(
  [string]$OutDir = "$env:TEMP\blarai_coresident_ut\ut_hardened",
  [string[]]$Partners = @("photoreal", "illustration", "cartoon", "vlm"),
  [int]$Repeats = 3
)
$ErrorActionPreference = "Continue"

$ut = $env:INTEL_UT_HOME
if (-not $ut -or -not (Test-Path "$ut\bin\bin2perfetto.exe")) {
  $ut = "C:\Users\mrbla\tools\intel-ut\ut-tool-ext-v0.2.0-beta1.1"
}
$b2p = "$ut\bin\bin2perfetto.exe"
if (-not (Test-Path $b2p)) { Write-Error "bin2perfetto not found at '$b2p'"; exit 1 }

$repo = Split-Path -Parent $PSScriptRoot
$py = "$repo\.venv\Scripts\python.exe"
$ex = "$repo\scripts\extract_ut_metrics.py"
$perf = "$repo\docs\performance"

foreach ($p in $Partners) {
  for ($r = 1; $r -le $Repeats; $r++) {
    $tag = "${p}_r${r}"
    $l0 = "$OutDir\ut_$tag.l0_gpu.bin"
    $sw = "$OutDir\ut_$tag.socwatch.bin"
    $hj = Get-ChildItem "$perf\benchmark_coresident_${tag}_*.json" -ErrorAction SilentlyContinue |
          Sort-Object LastWriteTime -Descending | Select-Object -First 1
    if ((Test-Path $l0) -and (Test-Path $sw) -and $hj) {
      Write-Host "=== remap-extract $tag ==="
      & $py $ex --bin $l0 --bin2perfetto $b2p --remap-from $sw `
          --harness $hj.FullName --out "$OutDir\ut_$tag.l0.metrics.json"
    } else {
      Write-Host "  [SKIP] $tag — missing l0/socwatch bin or harness JSON"
    }
  }
}
Write-Host "`n=== l0 remap re-extraction DONE -> $OutDir ==="
