<#
Hash-bound launcher for the MXC loopback-proxy egress probe.

What this measures: nothing itself. It starts run_probe.py only if run_probe.py, net_payload.py, proxy.py and
summarise.py each match a line `<sha256>  <filename>` in the approved-hash file; any missing file, missing
line or mismatch REFUSES to start (exit 1) and names the cause.
Token mode (-Token elevated|standard, default elevated; passed to run_probe.py as --token and recorded there):
  elevated   a live run is refused unless this process is elevated; `--dry-run-only` is allowed without it.
  standard   any run, dry or live, is refused unless this process is NOT elevated and its token is Medium integrity
             (S-1-16-8192, from `whoami /groups`); an elevated or non-Medium token is refused and the reason named.
  -SelfTestElevation (elevated|standard) and -SelfTestIntegrity (medium|high) override the detection only when the
  self-test's environment variable BLARAI_PROBE_SELFTEST=1 is present; otherwise they are ignored and the real
  detection applies.
How to run: double-click launch.cmd (elevated mode) or launch-standard.cmd (standard mode, from a normal
  non-administrator shell), or `pwsh -File launch.ps1 [-Token standard] [-ApprovedFile PATH] [-VerifyOnly] [probe args]`.
  Probe args pass through to run_probe.py (for example `--arms A` or `--dry-run-only`), with these exceptions:
  `--out DIR` (or `-out DIR`) is bound to -OutDir and passed on as `--out DIR`; `--token` is bound to -Token (the
  token mode is always the launcher's -Token; an invalid value is a binding error and nothing starts); and
  `--launch-sha256` is set by this launcher and is REFUSED if given.
Exit marker: every exit this script makes first prints `PROBE_EXIT=<n>`. A console file with no PROBE_EXIT line means
  this script never ran to an exit (for example a parameter-binding failure). The wrapper run_nonelevated.ps1 reports
  the exit code of its headless console host, not of this script, so its `exit=` line is not an outcome; the answer
  of a run is the batch-summary.json in the run folder (its path is printed by run_probe.py).
Approved-hash file default: %USERPROFILE%\blarai-research-data\mxc-proxy-egress\APPROVED_SHA256.txt
What it writes: nothing; it passes its own sha256 to run_probe.py, which records it in the batch header
  (record only: launch.ps1 cannot verify itself). run_probe.py writes its raw records under its own output folder.
  -VerifyOnly checks the hashes (and, with -Token standard, the token), prints the verdict and stops (no probe is started).

NOT MEASURED: any build other than the one(s) run; under a standard token, the WFP filter count (netsh wfp needs
elevation; recorded as unreadable); behaviour on a host whose --probe reports host-loopback
ingress unsupported (the earlier 26200.9457 condition); an identity-scoped proxy (allowedProxyPeer); the session-isolation backend; UDP, ICMP or DNS egress under the proxy policy;
host-to-container ingress (the doc's own open limitation); nono under MXC; anything about the fork or any
other sandbox.
#>
param(
    [string]$ApprovedFile = (Join-Path $env:USERPROFILE 'blarai-research-data\mxc-proxy-egress\APPROVED_SHA256.txt'),
    [switch]$VerifyOnly,
    [Alias('out')][string]$OutDir = '',
    [ValidateSet('elevated', 'standard')][string]$Token = 'elevated',
    [ValidateSet('', 'elevated', 'standard')][string]$SelfTestElevation = '',
    [ValidateSet('', 'medium', 'high')][string]$SelfTestIntegrity = '',
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$ProbeArgs
)
$ErrorActionPreference = 'Stop'
function Exit-Probe([int]$Code) { Write-Host "PROBE_EXIT=$Code"; exit $Code }
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$required = @('run_probe.py', 'net_payload.py', 'proxy.py', 'summarise.py')
$problems = New-Object System.Collections.Generic.List[string]

if (-not (Test-Path -LiteralPath $ApprovedFile -PathType Leaf)) {
    $problems.Add("approved-hash file missing: $ApprovedFile")
    $approved = @{}
} else {
    $approved = @{}
    foreach ($line in Get-Content -LiteralPath $ApprovedFile) {
        $t = $line.Trim()
        if ($t -eq '' -or $t.StartsWith('#')) { continue }
        if ($t -notmatch '^([0-9A-Fa-f]{64})\s+\*?(\S+)$') { $problems.Add("unparseable line in approved file: $t"); continue }
        $name = $Matches[2]; $hash = $Matches[1].ToLowerInvariant()
        if ($approved.ContainsKey($name) -and $approved[$name] -ne $hash) { $problems.Add("conflicting approved hashes for $name") }
        $approved[$name] = $hash
    }
}
foreach ($f in $required) {
    $path = Join-Path $here $f
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { $problems.Add("file missing: $f"); continue }
    if (-not $approved.ContainsKey($f)) { $problems.Add("no approved hash listed for $f"); continue }
    $actual = (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($actual -ne $approved[$f]) { $problems.Add("hash mismatch for ${f}: file $actual, approved $($approved[$f])") }
}
if ($problems.Count -gt 0) {
    Write-Host 'REFUSED: the probe files do not match the approved hashes.'
    foreach ($p in $problems) { Write-Host "  - $p" }
    Exit-Probe 1
}
Write-Host 'VERIFIED: all probe files match the approved hashes.'
foreach ($reserved in '--token', '--launch-sha256') {
    if ($ProbeArgs -contains $reserved) { Write-Host "REFUSED: $reserved is set by this launcher and cannot be passed through (use -Token for the token mode)."; Exit-Probe 1 }
}
if ($OutDir -ne '') { $ProbeArgs = @($ProbeArgs) + @('--out', $OutDir) }

$isDry = $ProbeArgs -contains '--dry-run-only'
if ($SelfTestElevation -ne '' -and $env:BLARAI_PROBE_SELFTEST -eq '1') { $elevated = ($SelfTestElevation -eq 'elevated') }
else { $elevated = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator) }
if ($SelfTestIntegrity -ne '' -and $env:BLARAI_PROBE_SELFTEST -eq '1') { $medium = ($SelfTestIntegrity -eq 'medium') }
else { $medium = [bool]((whoami /groups /fo csv /nh 2>$null) -match 'S-1-16-8192') }
if ($Token -eq 'standard') {
    if ($elevated) {
        Write-Host 'REFUSED: -Token standard needs a NON-elevated token, and this process is elevated. Start launch-standard.cmd from a normal (non-administrator) shell or by double-click from Explorer.'
        Exit-Probe 1
    }
    if (-not $medium) {
        Write-Host 'REFUSED: -Token standard needs a Medium-integrity token (S-1-16-8192), and this process is not Medium integrity.'
        Exit-Probe 1
    }
} elseif (-not $elevated -and -not $isDry -and -not $VerifyOnly) {
    Write-Host 'REFUSED: a live run must be launched elevated (live runs are launched elevated so that they are comparable with the earlier elevated record of this question).'
    Write-Host '  Right-click launch.cmd and choose Run as administrator. The --dry-run-only mode may run without elevation. For a run from a standard token use launch-standard.cmd.'
    Exit-Probe 1
}
if ($VerifyOnly) { Write-Host "VERIFY-ONLY: hashes match$(if ($Token -eq 'standard') { ' and the token is a non-elevated Medium token' }); no probe started."; Exit-Probe 0 }
$stale = @(Get-ChildItem -LiteralPath $here -Recurse -Force -ErrorAction SilentlyContinue | Where-Object { $_.Name -eq '__pycache__' -or $_.Extension -eq '.pyc' })
if ($stale.Count -gt 0) {
    Write-Host 'REFUSED: compiled Python files are present in the probe folder; they would run in place of the hashed sources.'
    foreach ($f in $stale) { Write-Host "  - $($f.FullName)" }
    Exit-Probe 1
}
$py = $env:BLARAI_PROBE_PYTHON
if (-not $py) { $cmd = Get-Command python -ErrorAction SilentlyContinue; if ($cmd) { $py = $cmd.Source } }
if (-not $py) { Write-Host 'REFUSED: no python found (set BLARAI_PROBE_PYTHON).'; Exit-Probe 1 }
$self = (Get-FileHash -LiteralPath $MyInvocation.MyCommand.Path -Algorithm SHA256).Hash.ToLowerInvariant()
$pycPrefix = Join-Path ([IO.Path]::GetTempPath()) ('mxc-probe-pyc-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $pycPrefix | Out-Null
try {
    & $py -I -B -X "pycache_prefix=$pycPrefix" (Join-Path $here 'run_probe.py') --launch-sha256 $self --token $Token @ProbeArgs
    $probeRc = $LASTEXITCODE
} catch {
    Write-Host "FAILED: could not run the probe: $_"
    $probeRc = 1
} finally {
    Remove-Item -LiteralPath $pycPrefix -Recurse -Force -ErrorAction SilentlyContinue
}
Exit-Probe $probeRc
