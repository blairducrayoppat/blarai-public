#requires -Version 5.1
<#
.SYNOPSIS
  Builds the halfset harness as a cargo example inside a copy of the pinned srt-win tree.

.DESCRIPTION
  Copies the pinned source tree (src, tests, ci, Cargo.toml, Cargo.lock, rustfmt.toml) to a build directory that is NOT
  inside the git worktree, drops harness/halfset.rs in as examples/halfset.rs, verifies Cargo.toml and Cargo.lock are
  byte-identical to the pinned copies, runs `cargo build --locked --example halfset`, and prints the sha256 of the exe,
  of halfset.rs and of the pinned Cargo.lock. The build directory's target folder is kept between runs; sources are
  refreshed each run.

  -Toggle builds a second exe with RUSTFLAGS="--cfg halfset_toggle" into its own target directory. That exe exists only
  for tests/refusals.ps1: it can switch a guard off by environment variable and refuses every real engine call. The
  shipped exe never contains that code.

  The sha256 of harness/halfset.rs is embedded in the exe (HALFSET_RS_SHA256, read by option_env!) and reported by
  `--version`; the arming proof must carry it. A build record (build-record-shipped.json / build-record-toggle.json in the
  build dir) holds the exe sha256 this script produced.

  Output: one JSON object on stdout; progress and cargo output go to the host stream.
#>
[CmdletBinding()]
param(
    [string]$PinnedTree = 'C:/Users/_OPERATOR_/rust-bootstrap/srt-src-24eb39e9',
    [string]$BuildDir   = 'C:/Users/_OPERATOR_/rust-bootstrap/halfset-build',
    [switch]$Toggle
)
$ErrorActionPreference = 'Stop'

$ExpectedLockSha256 = 'c41cf41050c2b1e2986ed7ca690a703415cabadfed9219788a451df0da0967ec'
$ExpectedTomlSha256 = '281fb1762ecf788466eb61c184078c51184da197c56f426252cf65a3ecf60e38'

function Get-Sha256([string]$Path) { (Get-FileHash -Algorithm SHA256 -LiteralPath $Path).Hash.ToLowerInvariant() }

$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$src = Join-Path $here 'halfset.rs'
if (-not (Test-Path -LiteralPath $src)) { throw "halfset.rs not found beside the build script: $src" }

# The build directory must not be inside a git worktree.
$bd = [IO.Path]::GetFullPath($BuildDir)
$probe = $bd
while ($probe) {
    if (Test-Path -LiteralPath (Join-Path $probe '.git')) { throw "build dir $bd is inside a git tree ($probe)" }
    $parent = Split-Path -Parent $probe
    if ($parent -eq $probe) { break }
    $probe = $parent
}

# The pinned tree must be the recorded one.
$pinnedLock = Get-Sha256 (Join-Path $PinnedTree 'Cargo.lock')
$pinnedToml = Get-Sha256 (Join-Path $PinnedTree 'Cargo.toml')
if ($pinnedLock -ne $ExpectedLockSha256) { throw "pinned Cargo.lock sha256 $pinnedLock is not the recorded $ExpectedLockSha256" }
if ($pinnedToml -ne $ExpectedTomlSha256) { throw "pinned Cargo.toml sha256 $pinnedToml is not the recorded $ExpectedTomlSha256" }

New-Item -ItemType Directory -Force -Path $bd | Out-Null
foreach ($d in 'src', 'tests', 'ci') {
    $null = & robocopy (Join-Path $PinnedTree $d) (Join-Path $bd $d) /MIR /NFL /NDL /NJH /NJS /NP
    if ($LASTEXITCODE -ge 8) { throw "robocopy of $d failed with $LASTEXITCODE" }
}
foreach ($f in 'Cargo.toml', 'Cargo.lock', 'rustfmt.toml') { Copy-Item -LiteralPath (Join-Path $PinnedTree $f) -Destination (Join-Path $bd $f) -Force }
New-Item -ItemType Directory -Force -Path (Join-Path $bd 'examples') | Out-Null
Copy-Item -LiteralPath $src -Destination (Join-Path $bd 'examples/halfset.rs') -Force

# Cargo.toml and Cargo.lock must be untouched.
if ((Get-Sha256 (Join-Path $bd 'Cargo.lock')) -ne $pinnedLock) { throw 'build-dir Cargo.lock differs from the pinned copy' }
if ((Get-Sha256 (Join-Path $bd 'Cargo.toml')) -ne $pinnedToml) { throw 'build-dir Cargo.toml differs from the pinned copy' }

$env:PATH = (Join-Path $HOME '.cargo/bin') + [IO.Path]::PathSeparator + $env:PATH
$srcSha = Get-Sha256 $src
$env:HALFSET_PINNED_LOCK_SHA256 = $pinnedLock
$env:HALFSET_RS_SHA256 = $srcSha
$targetDir = if ($Toggle) { Join-Path $bd 'target-toggle' } else { Join-Path $bd 'target' }
$env:CARGO_TARGET_DIR = $targetDir
if ($Toggle) { $env:RUSTFLAGS = '--cfg halfset_toggle' } else { Remove-Item Env:RUSTFLAGS -ErrorAction SilentlyContinue }

Push-Location $bd
try {
    & cargo build --locked --example halfset 2>&1 | ForEach-Object { Write-Host $_ }
    if ($LASTEXITCODE -ne 0) { throw "cargo build failed with exit code $LASTEXITCODE" }
} finally { Pop-Location }

# Cargo.lock must still be byte-identical after the build (--locked refuses to rewrite it; this proves it).
if ((Get-Sha256 (Join-Path $bd 'Cargo.lock')) -ne $pinnedLock) { throw 'Cargo.lock changed during the build' }

$exe = Join-Path $targetDir 'debug/examples/halfset.exe'
if (-not (Test-Path -LiteralPath $exe)) { throw "built exe not found: $exe" }
# halfset.rs must not have changed while the build ran.
if ((Get-Sha256 $src) -ne $srcSha) { throw 'halfset.rs changed during the build' }
$record = [pscustomobject]@{
    exe                      = $exe
    exe_sha256               = Get-Sha256 $exe
    halfset_rs_sha256        = $srcSha
    pinned_cargo_lock_sha256 = $pinnedLock
    pinned_cargo_toml_sha256 = $pinnedToml
    toggle_build             = [bool]$Toggle
}
# The build record lets tests/refusals.ps1 check that the exe under test is the one this script produced.
$recordPath = Join-Path $bd ($(if ($Toggle) { 'build-record-toggle.json' } else { 'build-record-shipped.json' }))
$record | ConvertTo-Json -Compress | Set-Content -LiteralPath $recordPath -Encoding utf8
$record | ConvertTo-Json -Compress
