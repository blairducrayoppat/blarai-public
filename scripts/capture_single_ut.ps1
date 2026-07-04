<#
.SYNOPSIS
  Capture ONE single-model inference run in the FOREGROUND under Intel UT, then
  extract per-phase socwatch + level-zero (remapped) GPU telemetry for it.

.DESCRIPTION
  The single-model companion to capture_one.ps1 (which captures co-residency).
  Session-2 methodology EXPANSION: the comparable throughput numbers still come
  from the UT-FREE benchmark_gpu_inference.py run (apples-to-apples with the
  published 2026.1.0 baseline). THIS pass adds a separate, clearly-annotated
  foreground-UT capture of the same single-model workload so we accumulate
  richer per-run iGPU power / frequency / GPU-busy % / bandwidth / NPU=0W
  telemetry to compare OVER TIME across future runs.

  Wraps benchmark_gpu_inference.py (with --emit-phases, the opt-in boundary
  emitter) in ut.exe --enable socwatch,level-zero, then segments per phase
  (<config>_measured = steady-state decode; <config>_prefill) via the harness's
  Unix-epoch boundaries. Foreground-only because background UT tasks get reaped
  on this box (README_coresident_ut.md sec 4). Keep each call SHORT (1 config,
  low run/warmup count) so it completes within one invocation. Requires an
  ELEVATED shell (socwatch/level-zero drivers). LOCALAPPDATA is redirected.

.EXAMPLE
  .\scripts\capture_single_ut.ps1 -Tag 14b_specon -Configs spec_on -Runs 2 -Warmup 1 -OutDir <scratch>\single_ut
  .\scripts\capture_single_ut.ps1 -Tag 8b_specon -ModelDir models\qwen3-8b\openvino-int4-gpu -ModelName qwen3-8b -Configs spec_on -OutDir <scratch>\single_ut
#>
param(
  [Parameter(Mandatory)][string]$Tag,
  [string]$ModelDir = "",
  [string]$ModelName = "",
  [string]$DraftModelDir = "",
  [ValidateSet('both','spec_off','spec_on')][string]$Configs = 'spec_on',
  [string]$DraftDevice = "",            # e.g. CPU; empty = GPU (same as target)
  [int]$Runs = 2,
  [int]$Warmup = 1,
  [int]$RunCooldown = 0,
  [ValidateSet('on','off')][string]$Prefill = 'on',
  [Parameter(Mandatory)][string]$OutDir
)
$ErrorActionPreference = "Continue"

# --- elevation guard (UT drivers require Administrator) ---
$admin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $admin) { Write-Host "[FATAL] not elevated - UT socwatch/level-zero need Administrator."; exit 2 }

$ut = $env:INTEL_UT_HOME
if (-not $ut -or -not (Test-Path "$ut\bin\ut.exe")) { $ut = "C:\Users\mrbla\tools\intel-ut\ut-tool-ext-v0.2.0-beta1.1" }
. "$ut\ut-vars.ps1" | Out-Null
$b2p = "$ut\bin\bin2perfetto.exe"

$repo = Split-Path -Parent $PSScriptRoot
$py = "$repo\.venv\Scripts\python.exe"
$harness = "$repo\scripts\benchmark_gpu_inference.py"
$ex = "$repo\scripts\extract_ut_metrics.py"

New-Item -ItemType Directory -Force $OutDir | Out-Null
$root = Split-Path -Parent $OutDir
New-Item -ItemType Directory -Force "$root\localappdata" | Out-Null
$env:LOCALAPPDATA = "$root\localappdata"   # keep the harness off the real session store

$prefix = "$OutDir\ut_$Tag"
$phases = "$prefix.phases.json"
Remove-Item "$prefix*" -ErrorAction SilentlyContinue

# --- build the harness command string (single -a argument for ut.exe) ---
$cmd = "$py -u $harness --configs $Configs --runs $Runs --warmup $Warmup --run-cooldown $RunCooldown --prefill $Prefill --emit-phases `"$phases`""
if ($ModelDir)      { $cmd += " --model-dir `"$repo\$ModelDir`"" }
if ($ModelName)     { $cmd += " --model-name $ModelName" }
if ($DraftModelDir) { $cmd += " --draft-model-dir `"$repo\$DraftModelDir`"" }
if ($DraftDevice)   { $cmd += " --draft-device $DraftDevice" }

Write-Host "=== [$Tag] SINGLE-MODEL FOREGROUND UT capture START $(Get-Date -Format o) ==="
Write-Host "    cmd: $cmd"
& "$ut\bin\ut.exe" -o $prefix --config-level medium --enable socwatch,level-zero -a $cmd
Write-Host "=== [$Tag] ut exit $LASTEXITCODE ==="

# --- extract per-phase metrics using the emitted Unix-epoch boundaries ---
if (Test-Path $phases) {
  if (Test-Path "$prefix.socwatch.bin") {
    & $py $ex --bin "$prefix.socwatch.bin" --bin2perfetto $b2p --phases $phases --out "$prefix.socwatch.metrics.json"
  }
  if ((Test-Path "$prefix.l0_gpu.bin") -and (Test-Path "$prefix.socwatch.bin")) {
    & $py $ex --bin "$prefix.l0_gpu.bin" --bin2perfetto $b2p --remap-from "$prefix.socwatch.bin" --phases $phases --out "$prefix.l0.metrics.json"
  }
} else { Write-Host "  [WARN] no phases file emitted for $Tag - harness may have failed (check above)." }
Write-Host "=== [$Tag] DONE ==="
