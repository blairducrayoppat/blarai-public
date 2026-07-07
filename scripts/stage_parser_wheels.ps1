# BlarAI — Stage guest-parser wheels on the HOST (UC-003 Stage C; #655)
# ======================================================================
# The Alpine guest is NIC-less, so it can never pip-install from PyPI.  This
# script runs on the HOST (which has internet in dev sessions) and produces a
# self-contained wheel directory that the controlled session ships into the
# guest over the Copy-VMFile deploy channel (scripts/ship_parser_files.ps1).
#
# What it does:
#   1. pip download the requirements/guest-parser.txt closure (--no-deps;
#      the file lists the full closure) targeting the guest platform:
#      CPython 3.12 / musllinux_1_2_x86_64, binaries only.  Pure-python
#      (py3-none-any) wheels satisfy any platform, so only genuinely
#      C-extension packages (regex; possibly charset-normalizer) resolve to
#      musllinux wheels.
#   2. Verify every downloaded wheel's SHA-256 against the hash-pinned
#      universe in requirements/ingest-cleaner.txt (the LA-approved Stage-B
#      supply-chain record).  Wheels whose hash is NOT in that universe are
#      allowed ONLY for the named platform-wheel packages (regex,
#      charset-normalizer) and are LOUDLY recorded — anything else aborts.
#   3. Write SHA256SUMS (sha256sum -c format, verified in-guest before
#      install) + staging_report.json, and copy guest-parser.txt alongside.
#
# Network note: this is a DEV-SESSION tool (PyPI reachable).  It is never run
# by, or shipped into, the BlarAI runtime.

param(
    [string]$Dest = "build/guest_parser_wheels",
    [string]$Requirements = "requirements/guest-parser.txt",
    [string]$HashAnchor = "requirements/ingest-cleaner.txt",
    [string]$Python = ".\.venv\Scripts\python.exe"
)

$ErrorActionPreference = "Stop"

# Packages allowed to resolve to platform wheels whose hashes are not in the
# Stage-B anchor file (their musllinux artefacts were never pinned for the
# host).  Their staged hashes are recorded in SHA256SUMS + the report, and the
# provisioning record instructs the operator to spot-check them against PyPI.
$PlatformWheelAllowlist = @("regex", "charset_normalizer", "charset-normalizer")

if (-not (Test-Path -LiteralPath $Python)) { $Python = "python" }
if (-not (Test-Path -LiteralPath $Requirements)) {
    Write-Error "Requirements file not found: $Requirements"
    exit 2
}
if (-not (Test-Path -LiteralPath $HashAnchor)) {
    Write-Error "Hash-anchor file not found: $HashAnchor"
    exit 2
}

New-Item -ItemType Directory -Force -Path $Dest | Out-Null

# -- 1. Download the closure for the guest platform ---------------------------
Write-Host "=== pip download (guest platform: cp312 / musllinux_1_2_x86_64) ==="
& $Python -m pip download `
    --dest $Dest `
    --no-deps `
    --only-binary=:all: `
    --requirement $Requirements `
    --implementation cp `
    --python-version 3.12 `
    --platform musllinux_1_2_x86_64 `
    --platform musllinux_1_1_x86_64 `
    --abi cp312 `
    --abi abi3 `
    --abi none
if ($LASTEXITCODE -ne 0) {
    Write-Error "pip download failed (exit $LASTEXITCODE) - nothing staged."
    exit 3
}

# -- 2. Verify against the Stage-B hash universe -------------------------------
$anchorHashes = @{}
foreach ($line in (Get-Content -LiteralPath $HashAnchor)) {
    if ($line -match '--hash=sha256:([0-9a-f]{64})') {
        $anchorHashes[$Matches[1]] = $true
    }
}
Write-Host ("Hash anchor: {0} pinned sha256 values loaded from {1}" -f $anchorHashes.Count, $HashAnchor)

$wheels = Get-ChildItem -LiteralPath $Dest -Filter *.whl | Sort-Object Name
if ($wheels.Count -eq 0) {
    Write-Error "No wheels staged in $Dest - aborting."
    exit 4
}

$verified = @()
$recordedNew = @()
$violations = @()
$sumLines = @()

foreach ($wheel in $wheels) {
    $hash = (Get-FileHash -LiteralPath $wheel.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
    $sumLines += ("{0}  {1}" -f $hash, $wheel.Name)
    $pkg = ($wheel.Name -split '-')[0].ToLowerInvariant()
    if ($anchorHashes.ContainsKey($hash)) {
        $verified += [ordered]@{ file = $wheel.Name; sha256 = $hash; status = "VERIFIED_AGAINST_STAGE_B_PINS" }
    } elseif ($PlatformWheelAllowlist -contains $pkg) {
        Write-Warning "RECORDED-NEW platform wheel (not in the Stage-B pin set): $($wheel.Name) sha256=$hash - spot-check against PyPI per the provisioning record."
        $recordedNew += [ordered]@{ file = $wheel.Name; sha256 = $hash; status = "RECORDED_NEW_PLATFORM_WHEEL" }
    } else {
        $violations += [ordered]@{ file = $wheel.Name; sha256 = $hash; status = "HASH_NOT_IN_ANCHOR" }
    }
}

if ($violations.Count -gt 0) {
    $violations | ForEach-Object { Write-Error ("SUPPLY-CHAIN REFUSAL: {0} (sha256 {1}) matches no Stage-B pin and is not an allowlisted platform-wheel package." -f $_.file, $_.sha256) }
    exit 5
}

# -- 3. Manifest + report + requirements alongside -----------------------------
Copy-Item -LiteralPath $Requirements -Destination (Join-Path $Dest "guest-parser.txt") -Force
$reqHash = (Get-FileHash -LiteralPath (Join-Path $Dest "guest-parser.txt") -Algorithm SHA256).Hash.ToLowerInvariant()
$sumLines += ("{0}  {1}" -f $reqHash, "guest-parser.txt")

# busybox `sha256sum -c` wants LF endings and "<hash>  <name>" lines.
$sumPath = Join-Path $Dest "SHA256SUMS"
[System.IO.File]::WriteAllText((Resolve-Path $Dest).Path + "\SHA256SUMS", (($sumLines -join "`n") + "`n"))

$report = [ordered]@{
    artifact      = "guest-parser wheel staging report (#655 Stage C)"
    timestamp_utc = (Get-Date).ToUniversalTime().ToString("o")
    requirements  = $Requirements
    hash_anchor   = $HashAnchor
    wheel_count   = $wheels.Count
    verified      = $verified
    recorded_new  = $recordedNew
}
$report | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath (Join-Path $Dest "staging_report.json") -Encoding utf8

Write-Host "STAGING OK"
Write-Host ("  wheels       : {0} ({1} verified against Stage-B pins, {2} recorded-new platform wheels)" -f $wheels.Count, $verified.Count, $recordedNew.Count)
Write-Host "  manifest     : $sumPath"
Write-Host "  report       : $(Join-Path $Dest 'staging_report.json')"
Write-Host "  next step    : scripts/ship_parser_files.ps1 -SourceDir $Dest -GuestDir /opt/blarai/parser/wheels"
exit 0
