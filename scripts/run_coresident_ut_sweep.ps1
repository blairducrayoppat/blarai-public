<#
.SYNOPSIS
  Hardened co-residency multi-sweep under Intel Unified Telemetry (UT).
  See docs/performance/README_coresident_ut.md for the full method + caveats.

.DESCRIPTION
  For each (partner x repeat): wraps benchmark_coresident.py in `ut.exe --enable
  socwatch,level-zero`, then extracts PER-PHASE metrics (socwatch power per phase;
  l0 GPU freq/bandwidth/busy whole-run). Cools down between runs. Drops `emon`
  (its stop-phase processing on large captures hangs UT finalization).

  Requires an ELEVATED shell + Intel UT (set $env:INTEL_UT_HOME, else the default
  permanent path below). Then aggregate with merge_coresident_hardened.py.

.EXAMPLE
  .\scripts\run_coresident_ut_sweep.ps1 -Repeats 3 -OutRoot D:\bench\coresident
#>
param(
  [string[]]$Partners = @("photoreal", "illustration", "cartoon", "vlm"),
  [int]$Repeats = 3,
  [int]$CooldownS = 45,
  [string]$OutRoot = "$env:TEMP\blarai_coresident_ut"
)
$ErrorActionPreference = "Continue"

# Intel UT home — permanent location; override via the INTEL_UT_HOME env var.
$ut = $env:INTEL_UT_HOME
if (-not $ut -or -not (Test-Path "$ut\bin\ut.exe")) {
  $ut = "C:\Users\mrbla\tools\intel-ut\ut-tool-ext-v0.2.0-beta1.1"
}
if (-not (Test-Path "$ut\bin\ut.exe")) {
  Write-Error "Intel UT not found at '$ut'. Set INTEL_UT_HOME to the ut-tool-ext dir."
  exit 1
}
. "$ut\ut-vars.ps1" | Out-Null
$b2p = "$ut\bin\bin2perfetto.exe"

$repo = Split-Path -Parent $PSScriptRoot
$py = "$repo\.venv\Scripts\python.exe"
$harness = "$repo\scripts\benchmark_coresident.py"
$ex = "$repo\scripts\extract_ut_metrics.py"
$perf = "$repo\docs\performance"

$outDir = "$OutRoot\ut_hardened"
New-Item -ItemType Directory -Force $outDir, "$OutRoot\localappdata" | Out-Null
$env:LOCALAPPDATA = "$OutRoot\localappdata"   # keep the harness off the real session store
Remove-Item "$outDir\done.marker" -ErrorAction SilentlyContinue

Write-Host "UT home   : $ut"
Write-Host "Out dir   : $outDir"
Write-Host "Partners  : $($Partners -join ', ') x $Repeats repeats; cooldown ${CooldownS}s`n"

foreach ($p in $Partners) {
  for ($r = 1; $r -le $Repeats; $r++) {
    $tag = "${p}_r${r}"
    $prefix = "$outDir\ut_$tag"
    Remove-Item "$prefix*" -ErrorAction SilentlyContinue
    Remove-Item "$perf\benchmark_coresident_${tag}_*.json" -ErrorAction SilentlyContinue
    Write-Host "=== [$tag] capture START $(Get-Date -Format o) ==="
    & "$ut\bin\ut.exe" -o $prefix --config-level medium --enable socwatch,level-zero `
        -a "$py $harness --partners $p --out-tag $tag"
    Write-Host "=== [$tag] ut exit $LASTEXITCODE ==="
    $hj = Get-ChildItem "$perf\benchmark_coresident_${tag}_*.json" -ErrorAction SilentlyContinue |
          Sort-Object LastWriteTime -Descending | Select-Object -First 1
    if ($hj) {
      if (Test-Path "$prefix.socwatch.bin") {
        & $py $ex --bin "$prefix.socwatch.bin" --bin2perfetto $b2p --harness $hj.FullName --out "$prefix.socwatch.metrics.json"
      }
      if ((Test-Path "$prefix.l0_gpu.bin") -and (Test-Path "$prefix.socwatch.bin")) {
        # --remap-from anchors the l0 clock onto socwatch's Unix window (the timestamp-units fix)
        # so GPU freq/busy/bandwidth segment per-phase, not just whole-run.
        & $py $ex --bin "$prefix.l0_gpu.bin" --bin2perfetto $b2p --remap-from "$prefix.socwatch.bin" --harness $hj.FullName --out "$prefix.l0.metrics.json"
      }
    } else { Write-Host "  [WARN] no harness JSON for $tag" }
    if (-not (($p -eq $Partners[-1]) -and ($r -eq $Repeats))) {
      Write-Host "=== [$tag] cooldown ${CooldownS}s (thermal) ==="
      Start-Sleep -Seconds $CooldownS
    }
  }
}
"DONE $(Get-Date -Format o)" | Out-File "$outDir\done.marker" -Encoding utf8
Write-Host "`n=== SWEEP DONE -> $outDir ==="
