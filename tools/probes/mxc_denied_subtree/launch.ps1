<#
Hash-bound launcher for the MXC denied-subtree probe.

WHAT IT DOES. Computes the sha256 of every .py and .ps1 file in this directory (this file included) and
compares each with a line "<sha256>  <filename>" in APPROVED_SHA256.txt under
<home>\blarai-research-data\mxc-denied-subtree\. It refuses (exit 2) when the approval file is missing,
when any script has no line, or when any hash differs. Only then does it run run_probe.py with the
remaining arguments, using the explicit interpreter -Python (default C:/Python314/python.exe, refused if
missing); run_probe.py is started with -I -B and a fresh pycache prefix, and the launch is refused when this directory holds anything but .py and .ps1 files (bytecode cache, package directory, extension module);
run_probe.py records that interpreter's path and sha256 in the batch header.

HOW TO RUN.  pwsh -NoProfile -File launch.ps1 [-ApprovedFile <path>] [-Python <exe>] [-CheckOnly] [run_probe.py options]
  -CheckOnly   verify the hashes and exit 0 without launching anything.
Hashes are of the bytes on disk; a line-ending conversion changes them.

WHAT IT WRITES. Nothing itself; run_probe.py writes the raw records (see its header).
#>
[CmdletBinding()]
param(
    [string]$Python = 'C:/Python314/python.exe',
    [string]$ApprovedFile = (Join-Path $env:USERPROFILE 'blarai-research-data\mxc-denied-subtree\APPROVED_SHA256.txt'),
    [switch]$CheckOnly,
    [Parameter(ValueFromRemainingArguments = $true)][string[]]$ProbeArgs
)
$ErrorActionPreference = 'Stop'
$dir = $PSScriptRoot

function Fail([string]$msg) {
    Write-Host "REFUSED: $msg"
    exit 2
}

if (-not (Test-Path -LiteralPath $ApprovedFile -PathType Leaf)) { Fail "approval file missing: $ApprovedFile" }
$approved = @{}
foreach ($line in Get-Content -LiteralPath $ApprovedFile) {
    if ($line -match '^\s*([0-9a-fA-F]{64})\s+\*?(\S+)\s*$') { $approved[$Matches[2]] = $Matches[1].ToLowerInvariant() }
}
$stale = @(Get-ChildItem -LiteralPath $dir -Force | Where-Object { $_.PSIsContainer -or $_.Extension -notin '.py', '.ps1' })
if ($stale.Count -gt 0) { Fail "entries the hash binding does not cover (bytecode cache, package directory, extension module or other file): $($stale[0].FullName)" }
$scripts = Get-ChildItem -LiteralPath $dir -File | Where-Object { $_.Extension -in '.py', '.ps1' } | Sort-Object Name
if (-not $scripts) { Fail 'no scripts found to hash' }
foreach ($s in $scripts) {
    $h = (Get-FileHash -LiteralPath $s.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
    if (-not $approved.ContainsKey($s.Name)) { Fail "no approved hash for $($s.Name)" }
    if ($approved[$s.Name] -ne $h) { Fail "hash mismatch for $($s.Name): on disk $h, approved $($approved[$s.Name])" }
}
Write-Host "hash check passed for $($scripts.Count) scripts"
if ($CheckOnly) { exit 0 }

if (-not (Test-Path -LiteralPath $Python -PathType Leaf)) { Fail "interpreter missing: $Python" }
$py = $Python
Write-Host "interpreter $py sha256 $((Get-FileHash -LiteralPath $py -Algorithm SHA256).Hash.ToLowerInvariant())"
$pyc = Join-Path ([IO.Path]::GetTempPath()) ('mxcds-pyc-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $pyc | Out-Null
try {
    & $py -I -B -X "pycache_prefix=$pyc" (Join-Path $dir 'run_probe.py') @ProbeArgs
    $rc = $LASTEXITCODE
} finally {
    Remove-Item -LiteralPath $pyc -Recurse -Force -ErrorAction SilentlyContinue
}
exit $rc
