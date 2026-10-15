#requires -Version 7.2
<#
.SYNOPSIS
  NEP-0005 open question 3 with srt-win's OWN command line (#1763): install, status, wfp verify (IPv4 and IPv6 loopback), re-install on a
  half-set, uninstall. Runs once per build (stock = pinned anthropics/sandbox-runtime 24eb39e9; patched = the same tree plus the two
  candidate fixes in fix/), three passes per build.

.DESCRIPTION
  Modes (exactly one):
    -SelfTest [-WriteProof]   Offline. Drives every step against an in-memory fake world (no engine, no account, no ACL, no network). With
                              -WriteProof and zero failed checks, writes srtcli-proof.json beside this script, bound to this script's SHA-256.
    -DryRun                   Read-only preflight on the real machine: elevation, file hashes, absence of every srt-win footprint item, sweep.
    -Run -Build stock|patched Live. Needs a proof under 24 hours old naming this script's hash, an elevated token and a clean preflight.

  What srt-win's `install` changes (read from the pinned source): the srt-sandbox account (BUILTIN\Users) and the sandbox-runtime-users group,
  four LSA deny-logon rights on that group, the Winlogon hide value, HKLM\SOFTWARE\sandbox-runtime, %ProgramData%\sandbox-runtime, write-deny
  ACEs for the srt-sandbox SID on the world-writable system directories in $AmbientTargets, and the WFP sublayer plus four filters. Every
  srt-win call here names sublayer S1; a vector without it would install into srt-win's default sublayer and is refused before it runs.

  Locks, each independent:
    1. Argument allowlist per executable (Test-SrtArgv, Test-HalfsetArgv, Test-NodeArgv). A refused vector never reaches the executor.
    2. Each executable's SHA-256 is compared with the constant in this file before every call.
    3. The harness (halfset.exe) keeps its own sublayer guard and `--live` proof; it deletes only filters under S1.
    4. A stop sweep (`halfset enum --all-ours`, exit 9 = a filter of ours or srt-win's outside S1/S2/S3) after every engine change.
    5. Operator controls in every state: loopback connects on both families, and one outside connect; two outside failures in a row stop.
    6. The TypeScript runner, the module it imports and each whole TypeScript tree are pinned; NODE_* variables never reach a child.
    7. A positive control per pass: while installed, the WFP state export must see S1 and the srt-win name, or the run stops (export_blind).
  A stop runs srt-win's own uninstall once (if anything was installed and srt-win still matches its pin), then the after-uninstall checks,
  records everything and exits non-zero. When the uninstall cannot run, the record carries left_installed and the footprint it saw.
  The after-uninstall checks never delete anything by hand: what they find is reported. Without both sandbox SIDs they never report clean.

  Results are recorded, never asserted: the live run stops only on the safety conditions above, never because srt-win behaved differently
  from what its source suggests.

  Exit codes: 0 done (or self-test passed), 1 self-test failed, 2 usage, 3 preflight failed, 4 proof missing/stale/wrong hash,
  5 not elevated, 9 stopped on a safety condition (see the record), 10 the after-uninstall checks found something left, could not certify
  clean, or srt-win could not be uninstalled (left_installed).
#>
[CmdletBinding()]
param(
    [switch]$SelfTest, [switch]$WriteProof, [switch]$DryRun, [switch]$Run,
    [ValidateSet('stock', 'patched')][string]$Build,
    [ValidateRange(1, 5)][int]$Passes = 3,
    [string]$OutRoot = 'C:\ProgramData\BlarAI\arm3b-out'
)
Set-StrictMode -Version 3.0
$ErrorActionPreference = 'Stop'

# ---- recorded constants (fixed here; never generated at run time) ----------------------------------------------------------------------
$script:S1 = 'c971a69f-d6ab-4885-9b49-506d8aa51c86'
$script:S2 = '3e29ae7e-fd9f-413a-8b8d-da9bd3a96359'
$script:S3 = '6cf901ba-a6cd-4846-81a5-2598c55bdef5'
$script:SrtDefaultSubLayer = '2c5d0ad6-5f3b-4d4e-9b8f-1a3e7c9d0b21'
$script:Range = '60080-60089'; $script:RangeLo = 60080; $script:RangeHi = 60089; $script:PortIn = 60085
$script:SandboxUser = 'srt-sandbox'; $script:SandboxGroup = 'sandbox-runtime-users'
$script:LiveDir = 'C:\ProgramData\BlarAI\trackb-live'
$script:Root = $PSScriptRoot
$script:Exe = @{
    stock   = @{ Path = (Join-Path $PSScriptRoot 'stock\srt-win.exe');   Sha = '620CCB9819896663466719E32BD61998A6E238C42C7607F61907C1F09B90E6DE' }
    patched = @{ Path = (Join-Path $PSScriptRoot 'patched\srt-win.exe'); Sha = 'A5724CE9E1AE6C4E2ABA9F1AAC91A167DEE4D8EE02E7B225C28A0A7D6E5F71B7' }
    halfset = @{ Path = 'C:\ProgramData\BlarAI\trackb-live\halfset.exe'; Sha = 'EBE029802387A86F986BAB161B1903F30D24D6C4583D8016D426152D6D07229F' }
    node    = @{ Path = 'C:\Program Files\nodejs\node.exe';             Sha = $null }   # hashed at preflight and pinned for the run
}
$script:HarnessProof = 'C:\ProgramData\BlarAI\trackb-live\harness-live-proof-1763.json'
$script:RunVerify = Join-Path $PSScriptRoot 'run-verify.mjs'
$script:TsUtil = @{   # the built module the runner imports, per tree
    stock   = (Join-Path $PSScriptRoot 'stock\anthropics-sandbox-runtime-24eb39e\dist\sandbox\windows-sandbox-utils.js')
    patched = (Join-Path $PSScriptRoot 'patched\anthropics-sandbox-runtime-24eb39e\dist\sandbox\windows-sandbox-utils.js')
}
$script:TsUtilSha = @{ stock = '1E389AB0717A8D886216D259D8D39E9A3F3C64458EFE5A1DED9690FF31FF47F3'; patched = 'CC9D544F0FB958FDE18BEE1B7B8F7468868B9D90048E006BBDD97BA3CF2BBFE3' }
$script:TsTree = @{
    stock   = (Join-Path $PSScriptRoot 'stock\anthropics-sandbox-runtime-24eb39e')
    patched = (Join-Path $PSScriptRoot 'patched\anthropics-sandbox-runtime-24eb39e')
}
$script:TsTreeSha = @{ stock = '3B5068E8F9254CC44BC101D0149EEB87AA5119A9EE09207894274724081EB6A9'; patched = 'CD032280C66744F3E504599D099C0C26BEBACCF4D74621C7ACD8E6D3E48674B8' }   # Get-TreeSha of each deployed tree
$script:RunVerifySha = '83F4BB72D86D3AB7615B49C7F5A8F7BE4900D208CFB2EDAF563A3464D180A4AA'
$script:AmbientTargets = @('C:\ProgramData', 'C:\Users\Public', 'C:\Windows\Temp', 'C:\Windows\Tasks', 'C:\Windows\tracing', 'C:\Windows\Registration\CRMLog',
    'C:\Windows\System32\FxsTmp', 'C:\Windows\System32\com\dmp', 'C:\Windows\System32\spool\PRINTERS', 'C:\Windows\System32\spool\drivers\color',
    'C:\Windows\SysWOW64\FxsTmp', 'C:\Windows\SysWOW64\com\dmp', 'C:\Windows\SysWOW64\Tasks')
$script:StoreDir = 'C:\ProgramData\sandbox-runtime'
$script:OutsideHost = '1.1.1.1'; $script:OutsidePort = 443
$script:Roles = @('block-v4', 'block-v6', 'permit-v4', 'permit-v6')
# The half-set states and the roles each deletes from a full set.
$script:HalfStates = [ordered]@{ H6 = @('block-v6'); H4 = @('block-v4'); HP = @('permit-v4', 'permit-v6') }

# ---- pure validators ----------------------------------------------------------------------------------------------------------------
function Test-ProbeTarget {
    # PURE. 127.0.0.1:N or [::1]:N, N in 1024-65535.
    param([string]$T)
    if ($T -cmatch '^127\.0\.0\.1:(\d{4,5})$' -or $T -cmatch '^\[::1\]:(\d{4,5})$') { $p = [int]$Matches[1]; return ($p -ge 1024 -and $p -le 65535) }
    return $false
}

function Test-SrtArgv {
    # PURE. The only srt-win vectors this script may run. Every engine-touching verb names S1 explicitly.
    param([string[]]$Argv)
    $a = @($Argv)
    $ok = @(
        , @('install', '--sublayer-guid', $script:S1, '--proxy-port-range', $script:Range)
        , @('install', '--sublayer-guid', $script:S1, '--proxy-port-range', $script:Range, '--force')
        , @('wfp', 'status', '--sublayer-guid', $script:S1)
        , @('status', '--sublayer-guid', $script:S1)
        , @('uninstall', '--sublayer-guid', $script:S1)
    )
    foreach ($v in $ok) {
        # Element by element: a re-split vector ('install --sublayer-guid' as one element) is not the same vector.
        if ($v.Count -ne $a.Count) { continue }
        $same = $true; for ($i = 0; $i -lt $v.Count; $i++) { if ($a[$i] -cne $v[$i]) { $same = $false; break } }
        if ($same) { return $true }
    }
    if ($a.Count -eq 4 -and $a[0] -ceq 'wfp' -and $a[1] -ceq 'verify' -and $a[2] -ceq '--target' -and (Test-ProbeTarget $a[3])) { return $true }
    return $false
}

function Test-HalfsetArgv {
    # PURE. enum of S1/S2/S3, the all-ours stop sweep, and delete-filter under S1 only (armed with the recorded harness proof).
    param([string[]]$Argv)
    $a = @($Argv)
    if ($a.Count -eq 2 -and $a[0] -ceq 'enum' -and $a[1] -ceq '--all-ours') { return $true }
    if ($a.Count -eq 3 -and $a[0] -ceq 'enum' -and $a[1] -ceq '--sublayer' -and $a[2] -cin @($script:S1, $script:S2, $script:S3)) { return $true }
    if ($a.Count -eq 7 -and $a[0] -ceq 'delete-filter' -and $a[1] -ceq '--sublayer' -and $a[2] -ceq $script:S1 -and $a[3] -ceq '--key' -and
        $a[4] -cmatch '^[0-9a-f]{8}(-[0-9a-f]{4}){3}-[0-9a-f]{12}$' -and $a[5] -ceq '--live' -and $a[6] -ceq $script:HarnessProof) { return $true }
    return $false
}

function Test-NodeArgv {
    # PURE. node <run-verify.mjs> --tree stock|patched --exe <one of the two pinned srt-win paths>. Never --prepend (self-test fakes only).
    param([string[]]$Argv)
    $a = @($Argv)
    return ($a.Count -eq 5 -and $a[0] -ceq $script:RunVerify -and $a[1] -ceq '--tree' -and $a[2] -cin @('stock', 'patched') -and $a[3] -ceq '--exe' -and
        $a[4] -cin @($script:Exe.stock.Path, $script:Exe.patched.Path))
}

function Get-SrtRole {
    # PURE. block-v4 | block-v6 | permit-v4 | permit-v6 | other, from a harness enum row (srt-win tag kind + layer).
    param($F)
    $fam = switch ([string]$F.layer) { 'ale_auth_connect_v4' { 'v4' } 'ale_auth_connect_v6' { 'v6' } default { '' } }
    if (-not $fam) { return 'other' }
    if ([string]$F.tool -ne 'srt-win') { return 'other' }
    if ([string]$F.kind -eq 'block-user') { return "block-$fam" }
    if ([string]$F.kind -eq 'permit-loopback-user') { return "permit-$fam" }
    return 'other'
}

function Get-RoleMap {
    # PURE. @{ Ok; Roles = role -> key; Other = count; Problem } from a parsed `halfset enum --sublayer S1` object. Duplicate roles are a problem.
    param($Json)
    if ($null -eq $Json -or -not $Json.PSObject.Properties['filters']) { return @{ Ok = $false; Roles = @{}; Other = 0; Problem = 'no filters member' } }
    $m = @{}; $other = 0
    foreach ($f in @($Json.filters)) {
        if ($null -eq $f) { continue }
        $r = Get-SrtRole $f
        if ($r -eq 'other') { $other++; continue }
        if ($m.ContainsKey($r)) { return @{ Ok = $false; Roles = $m; Other = $other; Problem = "role $r appears twice" } }
        $m[$r] = [string]$f.key
    }
    return @{ Ok = $true; Roles = $m; Other = $other; Problem = '' }
}

function Test-FullSet { param($Map) return ($Map.Ok -and $Map.Other -eq 0 -and $Map.Roles.Count -eq 4 -and @($script:Roles | Where-Object { -not $Map.Roles.ContainsKey($_) }).Count -eq 0) }

function ConvertTo-AceList {
    # PURE. The DACL's ACEs in order, each as 'type;flags;rights;object;inherit-object;sid' with its flag tokens sorted, or $null when the
    # SDDL is not a plain DACL this can read (the caller then treats the change as unclassifiable). One normalisation only: a CREATOR OWNER
    # ACE that applies to the object itself is dropped (S-1-3-0 is never in a token) and an inheritable one is written inherit-only, which
    # is the form Windows rewrites it to. Order and the inherited mark (ID) are kept: Windows evaluates ACEs in order.
    param([string]$Sddl)
    if ($Sddl -notmatch '^D:[A-Z]*(\(.*\))?$') { return $null }
    $out = New-Object Collections.Generic.List[string]
    foreach ($m in [regex]::Matches($Sddl, '\(([^)]*)\)')) {
        $f = $m.Groups[1].Value -split ';'
        if ($f.Count -ne 6 -or $f[0] -notin @('A', 'D')) { return $null }
        $flags = @([regex]::Matches($f[1], '..') | ForEach-Object Value)
        if (($flags -join '') -ne $f[1]) { return $null }
        if ($f[5] -eq 'CO') {
            if (-not ($flags -contains 'OI' -or $flags -contains 'CI')) { continue }
            if ($flags -notcontains 'IO') { $flags += 'IO' }
        }
        $out.Add(('{0};{1};{2};{3};{4};{5}' -f $f[0], ((@($flags | Sort-Object)) -join ''), $f[2], $f[3], $f[4], $f[5]))
    }
    return , $out.ToArray()
}

function Get-AclChangeClass {
    # PURE. equivalent, narrowed or other ('other' stops a run).
    #   No deny ACE before or after: allows only accumulate, so order and the inherited mark do not change access. equivalent when the
    #   allow sets (ID dropped) are equal; narrowed when every new allow was already there.
    #   Any deny ACE before or after: order and ID decide access. equivalent only when the ordered lists are identical; narrowed only when
    #   the new list is the old one with some ALLOW ACEs removed and nothing else changed (an ordered subsequence).
    #   Anything else, including any SDDL this cannot read, is other.
    param([string]$Old, [string]$New)
    $o = ConvertTo-AceList $Old; $n = ConvertTo-AceList $New
    if ($null -eq $o -or $null -eq $n) { return 'other' }
    $hasDeny = @(@($o) + @($n) | Where-Object { $_.StartsWith('D;') }).Count -gt 0
    if (-not $hasDeny) {
        $dropId = { param($a) $t = $a -split ';'; $t[1] = (@([regex]::Matches($t[1], '..') | ForEach-Object Value | Where-Object { $_ -ne 'ID' })) -join ''; $t -join ';' }
        $os = @($o | ForEach-Object { & $dropId $_ } | Sort-Object -Unique); $ns = @($n | ForEach-Object { & $dropId $_ } | Sort-Object -Unique)
        if (($os -join '|') -ceq ($ns -join '|')) { return 'equivalent' }
        if (@($ns | Where-Object { $os -cnotcontains $_ }).Count -eq 0) { return 'narrowed' }
        return 'other'
    }
    if ((@($o) -join '|') -ceq (@($n) -join '|')) { return 'equivalent' }
    $j = 0
    for ($i = 0; $i -lt @($o).Count; $i++) {
        if ($j -lt @($n).Count -and $o[$i] -ceq $n[$j]) { $j++; continue }
        if (-not $o[$i].StartsWith('A;')) { return 'other' }
    }
    if ($j -eq @($n).Count) { return 'narrowed' }
    return 'other'
}

function Compare-AclSnapshot {
    # PURE. Baseline A, churn set (paths that differed between two back-to-back baselines), and a later snapshot B (each: path -> SDDL).
    # Returns @{ SidHits; Changed; Missing; Added } where SidHits are entries of B whose SDDL names any of $Sids, and Changed lists paths in both
    # A and B, outside the churn set, whose SDDL differs. Missing/Added are counts outside the churn set.
    param([hashtable]$A, [hashtable]$B, [hashtable]$Churn, [string[]]$Sids)
    $hits = New-Object Collections.Generic.List[string]; $changed = New-Object Collections.Generic.List[string]; $added = 0; $missing = 0
    foreach ($k in $B.Keys) {
        $v = [string]$B[$k]
        foreach ($s in @($Sids | Where-Object { $_ })) { if ($v.Contains($s)) { $hits.Add($k); break } }
        if ($Churn.ContainsKey($k)) { continue }
        if ($A.ContainsKey($k)) { if ([string]$A[$k] -cne $v) { $changed.Add($k) } } else { $added++ }
    }
    foreach ($k in $A.Keys) { if (-not $Churn.ContainsKey($k) -and -not $B.ContainsKey($k)) { $missing++ } }
    $byClass = @{ equivalent = 0; narrowed = 0; other = 0 }; $detail = New-Object Collections.Generic.List[object]
    foreach ($k in $changed) {
        $c = Get-AclChangeClass ([string]$A[$k]) ([string]$B[$k]); $byClass[$c]++
        # [ordered]@{} cannot be passed straight to a .NET method ("Argument types do not match"): bind it first.
        if ($detail.Count -lt 5000) { $d = [ordered]@{ path = $k; class = $c; old = [string]$A[$k]; new = [string]$B[$k] }; $detail.Add($d) }
    }
    return @{ SidHits = @($hits); Changed = @($changed); Missing = $missing; Added = $added; ByClass = $byClass; Detail = $detail.ToArray() }
}

function Get-ChurnSet {
    # PURE. Paths whose presence or SDDL differs between two baselines.
    param([hashtable]$A, [hashtable]$B)
    $c = @{}
    foreach ($k in $A.Keys) { if (-not $B.ContainsKey($k) -or [string]$B[$k] -cne [string]$A[$k]) { $c[$k] = $true } }
    foreach ($k in $B.Keys) { if (-not $A.ContainsKey($k)) { $c[$k] = $true } }
    return $c
}

function Test-ProofFresh {
    # PURE. $true when the proof (as ConvertFrom-Json returns it) names $DriverSha, has zero failed checks and was written between 24 hours
    # ago and 5 minutes ahead of $NowUtc. ConvertFrom-Json turns an ISO stamp into a DateTime (Kind Utc); a string is parsed as an offset,
    # never through local time.
    param($Proof, [string]$DriverSha, [datetime]$NowUtc)
    try {
        $w = $Proof.written_utc
        $wu = if ($w -is [datetime]) { $w.ToUniversalTime() } else { [datetimeoffset]::Parse([string]$w, [Globalization.CultureInfo]::InvariantCulture).UtcDateTime }
        $age = $NowUtc.ToUniversalTime() - $wu
        return ([string]$Proof.driver_sha256 -eq $DriverSha -and [int]$Proof.checks_failed -eq 0 -and $age.TotalHours -le 24 -and $age.TotalMinutes -ge -5)
    } catch { return $false }
}

function Get-FootprintLeft {
    # PURE. The names of footprint items still present. store_dir is reported separately: `uninstall` does not remove
    # %ProgramData%\sandbox-runtime (no removal in the pinned source), so its presence is a recorded finding, not a stop.
    param($Fp)
    return @(foreach ($p in $Fp.PSObject.Properties) { if ($p.Value -eq $true -and $p.Name -ne 'store_dir') { $p.Name } })
}

function Remove-StoreEntries {
    # PURE. A copy of an ACL snapshot without %ProgramData%\sandbox-runtime and its subtree (recorded on its own).
    param([hashtable]$H, [string]$StoreDir)
    $c = @{}
    foreach ($k in $H.Keys) { if ($k -ne $StoreDir -and -not $k.StartsWith($StoreDir + '\', [StringComparison]::OrdinalIgnoreCase)) { $c[$k] = $H[$k] } }
    return $c
}

# ---- the real world (every machine touch goes through one of these) -------------------------------------------------------------------
function Get-Sha256 { param([string]$Path) try { return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash } catch { return $null } }

function Get-TreeSha {
    # SHA-256 over "relative-path<TAB>file-sha256" lines, sorted ordinally: one value for every file node can load from a tree. $null when unreadable.
    param([string]$Dir)
    try {
        $lines = foreach ($f in @(Get-ChildItem -LiteralPath $Dir -Recurse -File -Force)) { "{0}`t{1}" -f $f.FullName.Substring($Dir.Length + 1), (Get-FileHash -LiteralPath $f.FullName -Algorithm SHA256).Hash }
        $sorted = [string[]]@($lines); [Array]::Sort($sorted, [StringComparer]::Ordinal)
        $sha = [Security.Cryptography.SHA256]::Create()
        try { return [BitConverter]::ToString($sha.ComputeHash([Text.Encoding]::UTF8.GetBytes(($sorted -join "`n")))) -replace '-', '' } finally { $sha.Dispose() }
    } catch { return $null }
}

function New-RealWorld {
    $w = [ordered]@{}
    $w.Exec = {
        param([string]$Exe, [string[]]$Argv, [int]$TimeoutSec)
        $psi = [Diagnostics.ProcessStartInfo]::new($Exe)
        foreach ($x in $Argv) { [void]$psi.ArgumentList.Add($x) }
        $psi.UseShellExecute = $false; $psi.CreateNoWindow = $true; $psi.RedirectStandardOutput = $true; $psi.RedirectStandardError = $true
        # node reads NODE_OPTIONS / NODE_PATH and friends: none may reach a child from the operator's environment.
        foreach ($k in @($psi.Environment.Keys | Where-Object { $_ -like 'NODE_*' })) { [void]$psi.Environment.Remove($k) }
        $sw = [Diagnostics.Stopwatch]::StartNew()
        $p = [Diagnostics.Process]::Start($psi)
        $so = $p.StandardOutput.ReadToEndAsync(); $se = $p.StandardError.ReadToEndAsync()
        if (-not $p.WaitForExit($TimeoutSec * 1000)) {
            try { $p.Kill($true) } catch {}
            return [pscustomobject]@{ ExitCode = $null; Stdout = ''; Stderr = "killed at the $TimeoutSec s limit"; TimedOut = $true; Ms = $sw.ElapsedMilliseconds }
        }
        $p.WaitForExit()
        return [pscustomobject]@{ ExitCode = $p.ExitCode; Stdout = $so.Result; Stderr = $se.Result; TimedOut = $false; Ms = $sw.ElapsedMilliseconds }
    }
    $w.Footprint = {
        $ul = 'HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Winlogon\SpecialAccounts\UserList'
        $hide = $false
        if (Test-Path $ul) { $hide = $null -ne (Get-ItemProperty -Path $ul -Name $script:SandboxUser -ErrorAction SilentlyContinue) }
        $prof = @(Get-ChildItem 'HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion\ProfileList' -ErrorAction SilentlyContinue |
            Where-Object { ([string](Get-ItemProperty -Path $_.PSPath -Name ProfileImagePath -ErrorAction SilentlyContinue).ProfileImagePath) -match '\\srt-sandbox(\.|$)' })
        [pscustomobject]@{
            account        = [bool](Get-LocalUser -Name $script:SandboxUser -ErrorAction SilentlyContinue)
            group          = [bool](Get-LocalGroup -Name $script:SandboxGroup -ErrorAction SilentlyContinue)
            hklm_key       = (Test-Path 'HKLM:\SOFTWARE\sandbox-runtime')
            hide_value     = $hide
            store_dir      = (Test-Path -LiteralPath (Join-Path $env:ProgramData 'sandbox-runtime'))
            profile_dir    = (@(Get-ChildItem 'C:\Users' -Directory -Force -ErrorAction SilentlyContinue | Where-Object { $_.Name -match '^srt-sandbox(\.|$)' }).Count -gt 0)
            profile_list   = ($prof.Count -gt 0)
        }
    }
    $w.UserRights = {
        # secedit export of the user-rights area; returns the text (SIDs appear as *S-1-5-...).
        param([string]$Dir)
        $f = Join-Path $Dir ("user-rights-{0}.inf" -f [guid]::NewGuid().ToString('N'))
        $null = & secedit.exe /export /cfg $f /areas USER_RIGHTS /quiet 2>&1
        try { return (Get-Content -LiteralPath $f -Raw -Encoding Unicode) } finally { Remove-Item -LiteralPath $f -Force -ErrorAction SilentlyContinue }
    }
    $w.Export = {
        # netsh wfp show state (providers, sublayers AND filters), counted for the srt-win name and each test sublayer GUID, so a sublayer
        # left without filters still counts. The file is deleted after counting.
        param([string]$Dir)
        $f = Join-Path $Dir ("wfp-state-{0}.xml" -f [guid]::NewGuid().ToString('N'))
        $null = & netsh.exe wfp show state file=$f 2>&1
        if (-not (Test-Path -LiteralPath $f)) { return [pscustomobject]@{ ok = $false } }
        try {
            $t = Get-Content -LiteralPath $f -Raw
            $n = { param($s) ([regex]::Matches($t, [regex]::Escape($s), 'IgnoreCase')).Count }
            return [pscustomobject]@{ ok = $true; srt_win = (& $n 'srt-win'); s1 = (& $n $script:S1); s2 = (& $n $script:S2); s3 = (& $n $script:S3); default_sublayer = (& $n $script:SrtDefaultSubLayer) }
        } finally { Remove-Item -LiteralPath $f -Force -ErrorAction SilentlyContinue }
    }
    $w.AclSnapshot = {
        # path -> SDDL (access section) for every entry under the ambient targets, reparse points skipped (C:\ProgramData\Application Data loops).
        $opt = [IO.EnumerationOptions]::new(); $opt.RecurseSubdirectories = $true; $opt.IgnoreInaccessible = $true; $opt.AttributesToSkip = [IO.FileAttributes]::ReparsePoint
        $h = @{}; $acc = [Security.AccessControl.AccessControlSections]::Access
        foreach ($t in @($script:AmbientTargets | Where-Object { Test-Path -LiteralPath $_ -PathType Container })) {
            foreach ($p in @($t) + @([IO.Directory]::EnumerateFileSystemEntries($t, '*', $opt))) {
                try {
                    $sd = if ([IO.Directory]::Exists($p)) { [IO.FileSystemAclExtensions]::GetAccessControl([IO.DirectoryInfo]::new($p), $acc) } else { [IO.FileSystemAclExtensions]::GetAccessControl([IO.FileInfo]::new($p), $acc) }
                    $h[$p] = $sd.GetSecurityDescriptorSddlForm($acc)
                } catch {}
            }
        }
        return $h
    }
    $w.Listen = {
        # A loopback listener outside the permit range (or exactly on $Port when given). Returns @{ Listener; Target }.
        param([string]$Family, [int]$Port = 0)
        $ip = if ($Family -eq 'v6') { [Net.IPAddress]::IPv6Loopback } else { [Net.IPAddress]::Loopback }
        for ($i = 0; $i -lt 10; $i++) {
            $l = [Net.Sockets.TcpListener]::new($ip, $Port); $l.Start(16)
            $p = ([Net.IPEndPoint]$l.LocalEndpoint).Port
            if ($Port -ne 0 -or $p -lt $script:RangeLo -or $p -gt $script:RangeHi) {
                $t = if ($Family -eq 'v6') { "[::1]:$p" } else { "127.0.0.1:$p" }
                return @{ Listener = $l; Target = $t }
            }
            $l.Stop()
        }
        throw "no $Family loopback port outside $script:Range in 10 tries"
    }
    $w.Unlisten = { param($L) try { $L.Listener.Stop() } catch {} }
    $w.Connect = {
        # One TCP connect as the operator. @{ ok; ms; error }.
        param([string]$HostName, [int]$Port, [int]$Ms = 3000)
        $c = $null; $sw = [Diagnostics.Stopwatch]::StartNew()
        try {
            $ip = [Net.IPAddress]::Parse($HostName.Trim('[', ']'))
            $c = [Net.Sockets.TcpClient]::new($ip.AddressFamily)
            $ok = $c.ConnectAsync($ip, $Port).Wait($Ms)
            return [pscustomobject]@{ ok = [bool]($ok -and $c.Connected); ms = $sw.ElapsedMilliseconds; error = $(if ($ok) { '' } else { 'timeout' }) }
        } catch { return [pscustomobject]@{ ok = $false; ms = $sw.ElapsedMilliseconds; error = $_.Exception.GetBaseException().Message } } finally { if ($c) { $c.Dispose() } }
    }
    $w.AmbientRecorded = {
        $v = Get-ItemProperty 'HKLM:\SOFTWARE\sandbox-runtime' -Name AmbientDenies -ErrorAction SilentlyContinue
        if ($null -eq $v) { return @() }
        return @($v.AmbientDenies)
    }
    $w.StoreSddl = {
        $d = Join-Path $env:ProgramData 'sandbox-runtime'
        if (-not (Test-Path -LiteralPath $d)) { return $null }
        $acc = [Security.AccessControl.AccessControlSections]::Access
        return [IO.FileSystemAclExtensions]::GetAccessControl([IO.DirectoryInfo]::new($d), $acc).GetSecurityDescriptorSddlForm($acc)
    }
    $w.Elevated = { ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator) }
    $w.Hash = { param($Path) Get-Sha256 $Path }
    $w.FileExists = { param($Path) Test-Path -LiteralPath $Path -PathType Leaf }
    $w.TreeHash = { param($Dir) Get-TreeSha $Dir }
    $w.SaveSnapshot = {
        # path<TAB>SDDL, sorted, in the admin-only run directory: the before/after evidence for every ACL change the run reports.
        param([hashtable]$H, [string]$Path)
        $keys = [string[]]@($H.Keys); [Array]::Sort($keys, [StringComparer]::Ordinal)
        $wr = [IO.StreamWriter]::new($Path, $false, [Text.UTF8Encoding]::new($false))
        try { foreach ($k in $keys) { $wr.Write($k); $wr.Write("`t"); $wr.WriteLine([string]$H[$k]) } } finally { $wr.Close() }
    }
    return [pscustomobject]$w
}

# ---- the run --------------------------------------------------------------------------------------------------------------------------
class StopRun : Exception { [string]$Class; StopRun([string]$c, [string]$m) : base($m) { $this.Class = $c } }

function Invoke-Checked {
    # Validates the vector against its allowlist and the executable's hash, then runs it. Refusal or a hash mismatch is a StopRun, never a run.
    param($W, [ValidateSet('stock', 'patched', 'halfset', 'node')][string]$Which, [string[]]$Argv, [int]$TimeoutSec = 120, [string]$Label)
    $valid = switch ($Which) { 'halfset' { Test-HalfsetArgv $Argv } 'node' { Test-NodeArgv $Argv } default { Test-SrtArgv $Argv } }
    if (-not $valid) { throw [StopRun]::new('argv_refused', "$Which vector refused: $($Argv -join ' ')") }
    $e = $script:Exe[$Which]
    $h = & $W.Hash $e.Path
    if (-not $e.Sha -or $h -ne $e.Sha) { throw [StopRun]::new('hash_mismatch', "$Which at $($e.Path) hashes $h, not $($e.Sha)") }
    if ($Which -eq 'node') {
        # The runner and the built module it imports for the chosen tree are pinned too: node runs whatever they say.
        $rv = & $W.Hash $script:RunVerify; $tu = & $W.Hash $script:TsUtil[$Argv[2]]
        if ($rv -ne $script:RunVerifySha -or $tu -ne $script:TsUtilSha[$Argv[2]]) { throw [StopRun]::new('hash_mismatch', "run-verify.mjs $rv or the $($Argv[2]) module $tu is not the pinned build") }
        if (-not $script:TreeChecked.ContainsKey($Argv[2])) {
            # The whole tree (every dist module and node_modules file) once per build run; the admin-writable-only folder holds it after that.
            $th = & $W.TreeHash $script:TsTree[$Argv[2]]
            if ($th -ne $script:TsTreeSha[$Argv[2]]) { throw [StopRun]::new('hash_mismatch', "the $($Argv[2]) TypeScript tree hashes $th, not the pinned tree") }
            $script:TreeChecked[$Argv[2]] = $true
        }
    }
    $r = & $W.Exec $e.Path $Argv $TimeoutSec
    $json = $null
    $line = @(([string]$r.Stdout) -split "`r?`n" | Where-Object { $_.Trim().StartsWith('{') } | Select-Object -Last 1)
    if ($line.Count -eq 1) { try { $json = $line[0] | ConvertFrom-Json } catch { $json = $null } }
    $rec = [ordered]@{ label = $Label; exe = $Which; argv = @($Argv); exit = $r.ExitCode; timed_out = [bool]$r.TimedOut; ms = $r.Ms; stdout = [string]$r.Stdout; stderr = [string]$r.Stderr; json = $json; at = (Get-Date).ToString('o') }
    [void]$script:Log.Add($rec)
    return [pscustomobject]$rec
}

function Invoke-StopSweep {
    param($W)
    $r = Invoke-Checked $W 'halfset' @('enum', '--all-ours') 120 'stop-sweep'
    if ($r.exit -eq 9) { throw [StopRun]::new('foreign_filter', 'a filter of ours or srt-win''s sits outside S1/S2/S3') }
    if ($r.exit -ne 0) { throw [StopRun]::new('sweep_unreadable', "stop sweep exit $($r.exit)") }
}

function Get-S1Map { param($W, [string]$Label) $r = Invoke-Checked $W 'halfset' @('enum', '--sublayer', $script:S1) 120 $Label; if ($r.exit -ne 0) { throw [StopRun]::new('enum_failed', "enum S1 exit $($r.exit)") }; return (Get-RoleMap $r.json) }

function Test-Operator {
    # Operator controls: loopback v4 and v6 to the operator's own listeners, plus one outside connect. Two outside failures in a row stop.
    param($W, [string]$Label)
    $res = [ordered]@{ label = $Label }
    foreach ($fam in 'v4', 'v6') {
        $l = & $W.Listen $fam
        try { $hp = $l.Target -replace ':(\d+)$', ''; $port = [int]($l.Target -replace '^.*:', ''); $res["loopback_$fam"] = & $W.Connect $hp $port 3000 } finally { & $W.Unlisten $l }
        if (-not $res["loopback_$fam"].ok) { [void]$script:Operator.Add($res); throw [StopRun]::new('operator_loopback', "operator loopback $fam connect failed in $Label") }
    }
    $o = & $W.Connect $script:OutsideHost $script:OutsidePort 3000
    $res.outside = $o
    if ($o.ok) { $script:OutsideFails = 0 } else { $script:OutsideFails++ }
    [void]$script:Operator.Add($res)
    if ($script:OutsideFails -ge 2) { throw [StopRun]::new('operator_outside', "two outside connects in a row failed (last in $Label)") }
}

function Invoke-Verify {
    # srt-win's own `wfp verify` against a fresh listener of the given family (or the given in-range port). Records the runner's answer.
    param($W, [string]$Build, [string]$Family, [int]$Port = 0, [string]$Label)
    $l = & $W.Listen $Family $Port
    try { $r = Invoke-Checked $W $Build @('wfp', 'verify', '--target', $l.Target) 90 $Label } finally { & $W.Unlisten $l }
    $probe = if ($r.json -and $r.json.PSObject.Properties['egress_probe']) { [string]$r.json.egress_probe } else { 'unparsed' }
    return [ordered]@{ target_family = $Family; in_range = ($Port -ne 0); exit = $r.exit; probe = $probe }
}

function Invoke-Ts {
    # The host's own readiness check (verifyWindowsWfpEgress) from the stock or patched TypeScript build, pointed at this build's srt-win.
    param($W, [string]$Build, [string]$Tree, [string]$Label)
    $r = Invoke-Checked $W 'node' @($script:RunVerify, '--tree', $Tree, '--exe', $script:Exe[$Build].Path) 120 $Label
    $j = $r.json
    if ($null -eq $j) { return [ordered]@{ tree = $Tree; ok = $null; code = 'unparsed'; exit = $r.exit } }
    return [ordered]@{ tree = $Tree; ok = [bool]$j.ok; code = $(if ($j.PSObject.Properties['code']) { $j.code } else { $null }); targets = $(if ($j.ok) { $j.result } else { $null }) }
}

function Measure-State {
    param($W, [string]$Build, [int]$Pass, [string]$State, [switch]$InRangeControl)
    $tag = "p$Pass-$State"
    $st = Invoke-Checked $W $Build @('wfp', 'status', '--sublayer-guid', $script:S1) 60 "$tag-status"
    $map = Get-S1Map $W "$tag-enum"
    $m = [ordered]@{
        pass = $Pass; state = $State
        srt_status = $(if ($st.json) { [ordered]@{ state = [string]$st.json.state; filters = $st.json.filters; port_range = $(if ($st.json.PSObject.Properties['port_range']) { $st.json.port_range } else { $null }) } } else { [ordered]@{ state = 'unparsed'; exit = $st.exit } })
        roles_present = @($script:Roles | Where-Object { $map.Roles.ContainsKey($_) }); other_filters = $map.Other
        verify_v4_out = (Invoke-Verify $W $Build 'v4' 0 "$tag-verify-v4")
        verify_v6_out = (Invoke-Verify $W $Build 'v6' 0 "$tag-verify-v6")
        ts_stock = (Invoke-Ts $W $Build 'stock' "$tag-ts-stock")
        ts_patched = (Invoke-Ts $W $Build 'patched' "$tag-ts-patched")
    }
    if ($InRangeControl) {
        # Controls: the same probe through the permit range, so a 'connected' answer is shown reachable on both families in the same state.
        $m.verify_v4_in_range = (Invoke-Verify $W $Build 'v4' $script:PortIn "$tag-verify-v4-in")
        $m.verify_v6_in_range = (Invoke-Verify $W $Build 'v6' $script:PortIn "$tag-verify-v6-in")
    }
    Test-Operator $W $tag
    [void]$script:States.Add($m)
    return $m
}

function Invoke-Install {
    param($W, [string]$Build, [int]$Pass, [string]$Label, [switch]$Force)
    $argv = @('install', '--sublayer-guid', $script:S1, '--proxy-port-range', $script:Range); if ($Force) { $argv += '--force' }
    $r = Invoke-Checked $W $Build $argv 3600 "p$Pass-$Label"
    Invoke-StopSweep $W
    return $r
}

function Invoke-UninstallAndCheck {
    # srt-win's own uninstall, then the direct checks. Returns the after-uninstall record; nothing is removed by hand.
    param($W, [string]$Build, [int]$Pass, [string[]]$Sids)
    $after = [ordered]@{ pass = $Pass; sids_known = (@($Sids | Where-Object { $_ -match '^S-1-5-21-' }).Count -eq 2); clean = $false }
    [void]$script:After.Add($after)
    $u = Invoke-Checked $W $Build @('uninstall', '--sublayer-guid', $script:S1) 3600 "p$Pass-uninstall"
    # The uninstall ran: whatever the checks below do, no stop path runs it again.
    $script:Installed = $false
    $after.uninstall_exit = $u.exit; $after.uninstall_ms = $u.ms
    try {
    $fp = & $W.Footprint
    $after.footprint = $fp; $after.footprint_left = @(Get-FootprintLeft $fp)
    $enum = [ordered]@{}
    foreach ($s in @($script:S1, $script:S2, $script:S3)) { $e = Invoke-Checked $W 'halfset' @('enum', '--sublayer', $s) 120 "p$Pass-after-enum"; $enum[$s] = $(if ($e.exit -eq 0 -and $e.json) { [int]$e.json.count } else { -1 }) }
    $after.enum_counts = $enum
    $sw = Invoke-Checked $W 'halfset' @('enum', '--all-ours') 120 "p$Pass-after-sweep"
    $after.sweep_exit = $sw.exit; $after.sweep_count = $(if ($sw.json) { [int]$sw.json.count } else { -1 })
    $after.export = & $W.Export $script:RunDir
    $ur = [string](& $W.UserRights $script:RunDir)
    $after.user_rights_sid_hits = @($Sids | Where-Object { $_ -and $ur.Contains($_) }).Count
    $after.store_dir_sddl = & $W.StoreSddl
    $snap = Remove-StoreEntries (& $W.AclSnapshot) $script:StoreDir
    $cmp = Compare-AclSnapshot -A $script:Base1 -B $snap -Churn $script:Churn -Sids $Sids
    & $W.SaveSnapshot $snap (Join-Path $script:RunDir "acl-after-p$Pass.tsv")
    $after.acl = [ordered]@{ entries = $snap.Count; sid_hits = $cmp.SidHits.Count; sid_hit_sample = @($cmp.SidHits | Select-Object -First 10); changed = $cmp.Changed.Count
        equivalent = $cmp.ByClass.equivalent; narrowed = $cmp.ByClass.narrowed; other = $cmp.ByClass.other; changes = $cmp.Detail; missing = $cmp.Missing; added = $cmp.Added }
    # Without both SIDs the ACL and user-rights searches cannot see a leftover: never clean.
    $clean = $after.sids_known -and ($u.exit -eq 0) -and ($after.footprint_left.Count -eq 0) -and (@($enum.Values | Where-Object { $_ -ne 0 }).Count -eq 0) -and ($sw.exit -eq 0) -and
        ($after.sweep_count -eq 0) -and $after.export.ok -and ($after.export.srt_win -eq 0) -and ($after.export.s1 -eq 0) -and ($after.user_rights_sid_hits -eq 0) -and
        ($cmp.SidHits.Count -eq 0) -and ($cmp.ByClass.other -eq 0) -and ($after.export.s2 -eq 0) -and ($after.export.s3 -eq 0)
    $after.clean = $clean
    } catch { $after.check_error = $_.Exception.Message; $after.clean = $false }
    return $after
}

function Get-SandboxSids {
    # The sandbox user's and group's SIDs from srt-win's own `status`. @() when it does not name both.
    param($W, [string]$Build, [string]$Label)
    $us = Invoke-Checked $W $Build @('status', '--sublayer-guid', $script:S1) 60 $Label
    try { return @(@([string]$us.json.user.user.sid, [string]$us.json.user.user.group_sid) | Where-Object { $_ -match '^S-1-5-21-' }) } catch { return @() }
}

function Invoke-Pass {
    param($W, [string]$Build, [int]$Pass)
    $script:Sids = @()
    $script:Installed = $true
    $i = Invoke-Install $W $Build $Pass 'install'
    if ($i.exit -ne 0) { throw [StopRun]::new('install_failed', "first install of pass $Pass exited $($i.exit)") }
    $sids = @(Get-SandboxSids $W $Build "p$Pass-user-status")
    if ($sids.Count -ne 2) { throw [StopRun]::new('sids_unreadable', 'srt-win status did not name the sandbox user and group SIDs') }
    $script:Sids = $sids
    # Positive control for the after-uninstall export check: while installed, the export must see S1 and the srt-win name, or a later zero means nothing.
    $ex = & $W.Export $script:RunDir
    $script:ExportControls.Add([ordered]@{ pass = $Pass; export = $ex }) | Out-Null
    if (-not $ex.ok -or $ex.s1 -eq 0 -or $ex.srt_win -eq 0) { throw [StopRun]::new('export_blind', "the WFP state export does not see the installed set: $($ex | ConvertTo-Json -Compress)") }
    $script:PassInfo.Add([ordered]@{ pass = $Pass; install_ms = $i.ms; install_exit = $i.exit; ambient_recorded = @(& $W.AmbientRecorded) }) | Out-Null
    if ($Pass -eq 1) {
        # Size of the ambient stamp, once per build: how many entries under the targets name the sandbox SID while installed.
        $snap = Remove-StoreEntries (& $W.AclSnapshot) $script:StoreDir
        $script:StampSize = (Compare-AclSnapshot -A $script:Base1 -B $snap -Churn @{} -Sids $sids).SidHits.Count
    }
    $full = Get-S1Map $W "p$Pass-full-check"
    if (-not (Test-FullSet $full)) { throw [StopRun]::new('not_full_after_install', "after install S1 holds roles $($full.Roles.Keys -join ',') other $($full.Other)") }
    $null = Measure-State $W $Build $Pass 'F' -InRangeControl
    foreach ($h in $script:HalfStates.Keys) {
        $map = Get-S1Map $W "p$Pass-$h-pre"
        if (-not (Test-FullSet $map)) { throw [StopRun]::new('not_full_before_delete', "before $h S1 holds roles $($map.Roles.Keys -join ',')") }
        foreach ($role in $script:HalfStates[$h]) {
            $d = Invoke-Checked $W 'halfset' @('delete-filter', '--sublayer', $script:S1, '--key', $map.Roles[$role], '--live', $script:HarnessProof) 120 "p$Pass-$h-delete-$role"
            if ($d.exit -ne 0) { throw [StopRun]::new('delete_failed', "delete $role exit $($d.exit)") }
            Invoke-StopSweep $W
        }
        $null = Measure-State $W $Build $Pass $h -InRangeControl:($h -eq 'HP')
        $re = Invoke-Install $W $Build $Pass "$h-reinstall"
        $script:Reinstalls.Add([ordered]@{ pass = $Pass; state = $h; exit = $re.exit; ms = $re.ms; stderr = $re.stderr }) | Out-Null
        $null = Measure-State $W $Build $Pass "$h-after-reinstall" -InRangeControl:($h -eq 'HP')
        $f = Invoke-Install $W $Build $Pass "$h-restore" -Force
        $script:Restores.Add([ordered]@{ pass = $Pass; state = $h; exit = $f.exit; ms = $f.ms }) | Out-Null
        $after = Get-S1Map $W "p$Pass-$h-restored"
        if (-not (Test-FullSet $after)) { throw [StopRun]::new('restore_failed', "install --force after $h left roles $($after.Roles.Keys -join ',')") }
    }
    $a = Invoke-UninstallAndCheck $W $Build $Pass $script:Sids
    $script:Installed = $false
    if (-not $a.clean) { throw [StopRun]::new('not_clean_after_uninstall', "pass $Pass after-uninstall checks are not clean: $($a | ConvertTo-Json -Compress -Depth 4)") }
}

function Invoke-Preflight {
    # Read-only. @{ Ok; Problems; Record }.
    param($W, [switch]$Live)
    $p = New-Object Collections.Generic.List[string]
    if ($Live -and -not (& $W.Elevated)) { $p.Add('not elevated') }
    foreach ($k in 'stock', 'patched', 'halfset') { $h = & $W.Hash $script:Exe[$k].Path; if ($h -ne $script:Exe[$k].Sha) { $p.Add("$k exe hash $h") } }
    foreach ($k in 'stock', 'patched') { if ((& $W.Hash $script:TsUtil[$k]) -ne $script:TsUtilSha[$k]) { $p.Add("ts $k build missing or not the pinned build") } }
    foreach ($k in 'stock', 'patched') { if ((& $W.TreeHash $script:TsTree[$k]) -ne $script:TsTreeSha[$k]) { $p.Add("ts $k tree is not the pinned tree") } }
    if ((& $W.Hash $script:RunVerify) -ne $script:RunVerifySha) { $p.Add('run-verify.mjs missing or not the pinned file') }
    if (-not (& $W.FileExists $script:HarnessProof)) { $p.Add('harness proof missing') }
    $fp = & $W.Footprint
    $left = @(Get-FootprintLeft $fp); if ($left.Count) { $p.Add("srt-win footprint already present: $($left -join ',')") }
    $storeSddl = & $W.StoreSddl
    $sw = Invoke-Checked $W 'halfset' @('enum', '--all-ours') 120 'preflight-sweep'
    if ($sw.exit -ne 0 -or -not $sw.json -or [int]$sw.json.count -ne 0) { $p.Add("sweep exit $($sw.exit) count $(if ($sw.json) { $sw.json.count })") }
    $ex = & $W.Export $script:RunDir
    if (-not $ex.ok -or $ex.srt_win -ne 0 -or $ex.s1 -ne 0 -or $ex.s2 -ne 0 -or $ex.s3 -ne 0 -or $ex.default_sublayer -ne 0) { $p.Add("export not clean: $($ex | ConvertTo-Json -Compress)") }
    $o = & $W.Connect $script:OutsideHost $script:OutsidePort 3000; if (-not $o.ok) { $p.Add("outside control fails before anything ran: $($o.error)") }
    return @{ Ok = ($p.Count -eq 0); Problems = @($p); Footprint = $fp; Export = $ex; StoreSddl = $storeSddl }
}

function Invoke-Build {
    # One build, $Passes passes. Returns the exit code; writes record.json in the run directory whatever happens.
    param($W, [string]$Build, [int]$Passes)
    $script:Log = New-Object Collections.ArrayList; $script:States = New-Object Collections.ArrayList; $script:After = New-Object Collections.ArrayList
    $script:Operator = New-Object Collections.ArrayList; $script:Reinstalls = New-Object Collections.ArrayList; $script:Restores = New-Object Collections.ArrayList
    $script:PassInfo = New-Object Collections.ArrayList; $script:OutsideFails = 0; $script:Installed = $false; $script:Sids = @(); $script:StampSize = $null
    $script:TreeChecked = @{}; $script:ExportControls = New-Object Collections.ArrayList
    $rec = [ordered]@{ schema = 'nep5-1763-srtcli-v1'; build = $Build; passes_planned = $Passes; started = (Get-Date).ToString('o'); exe_sha256 = $script:Exe[$Build].Sha
        driver_sha256 = (Get-Sha256 $PSCommandPath); windows_build = [Environment]::OSVersion.Version.ToString() }
    $code = 0
    try {
        $pf = Invoke-Preflight $W -Live
        $rec.preflight = $pf
        if (-not $pf.Ok) { $code = 3 }
        else {
            $t = [Diagnostics.Stopwatch]::StartNew(); $script:Base1 = Remove-StoreEntries (& $W.AclSnapshot) $script:StoreDir; $rec.acl_snapshot_ms = $t.ElapsedMilliseconds
            & $W.SaveSnapshot $script:Base1 (Join-Path $script:RunDir 'acl-baseline.tsv')
            $script:Base2 = Remove-StoreEntries (& $W.AclSnapshot) $script:StoreDir; $script:Churn = Get-ChurnSet $script:Base1 $script:Base2
            $rec.acl_baseline = [ordered]@{ entries = $script:Base1.Count; churn = $script:Churn.Count }
            for ($p = 1; $p -le $Passes; $p++) { Invoke-Pass $W $Build $p; $rec.passes_done = $p }
        }
    } catch {
        $e = $_.Exception
        $cls = if ($e -is [StopRun]) { $e.Class } else { 'unexpected' }
        $rec.stop = [ordered]@{ class = $cls; message = $e.Message; at = (Get-Date).ToString('o') }
        $code = if ($cls -eq 'not_clean_after_uninstall') { 10 } else { 9 }
        if ($script:Installed) {
            # srt-win's own uninstall, once, whatever stopped the run. If it cannot run (its exe no longer matches the pin), the record says
            # what was left installed and the exit is 10.
            try {
                if (@($script:Sids).Count -ne 2) { $script:Sids = @(Get-SandboxSids $W $Build 'stop-user-status') }
                $a = Invoke-UninstallAndCheck $W $Build 0 $script:Sids
                if (-not $a.clean) { $code = 10 }
            } catch { $rec.stop_cleanup_error = $_.Exception.Message; $code = 10 }
            if ($script:Installed) { $rec.left_installed = $true; $rec.left_installed_footprint = & $W.Footprint; $code = 10 }
        }
    } finally {
        $rec.finished = (Get-Date).ToString('o'); $rec.exit = $code
        $rec.pass_info = $script:PassInfo; $rec.ambient_stamped_entries = $script:StampSize
        $rec.states = $script:States; $rec.reinstalls = $script:Reinstalls; $rec.restores = $script:Restores; $rec.after_uninstall = $script:After; $rec.export_controls = $script:ExportControls
        $rec.operator = $script:Operator; $rec.commands = $script:Log
        if ($script:RunDir) { $rec | ConvertTo-Json -Depth 30 | Set-Content -LiteralPath (Join-Path $script:RunDir 'record.json') -Encoding utf8NoBOM }
    }
    return $code
}

# ---- the fake world (self-test) ------------------------------------------------------------------------------------------------------
function New-FakeWorld {
    # In-memory srt-win + harness + node + machine. $Sem 'stock' or 'patched' models the two status rules and install's early-out as read in the
    # source; the self-test checks the DRIVER (sequence, locks, records), not srt-win.
    param([string]$Sem, [hashtable]$Opt = @{})
    $st = @{ User = $false; F = [ordered]@{}; Next = 1; Calls = (New-Object Collections.ArrayList); OutsideOk = $true; LeaveAccount = [bool]$Opt["LeaveAccount"]; Foreign = $false
        LeaveAcl = [bool]$Opt["LeaveAcl"]; LeaveRights = [bool]$Opt["LeaveRights"]; BadSids = [bool]$Opt["BadSids"]; UpperKeys = [bool]$Opt["UpperKeys"]
        FootprintThrowAfter = [int]$Opt["FootprintThrowAfter"]; FootprintCalls = 0; Ever = $false
        BlindExport = [bool]$Opt["BlindExport"]; LeaveSublayer = [bool]$Opt["LeaveSublayer"]; Installs = 0
        LeaveFrom = $(if ($Opt.ContainsKey('LeaveFromPass')) { [int]$Opt['LeaveFromPass'] } else { 1 })
        FailInstallNo = [int]$Opt['FailInstallNo']; AclAfter = [string]$Opt['AclAfter'] }
    # Closures made with GetNewClosure() run in their own module scope, where $script: does not reach this file: capture what they need.
    $S1 = $script:S1; $outside = $script:OutsideHost
    $w = [ordered]@{ State = $st }
    $statusOf = {
        $roles = @($st.F.Values)
        if ($Sem -eq 'patched') { if ($roles.Count -eq 4) { 'installed' } elseif ($roles.Count) { 'partial' } else { 'absent' } }
        else { if ($roles -contains 'block-v4' -or $roles -contains 'block-v6') { 'installed' } else { 'absent' } }
    }.GetNewClosure()
    $fill = { foreach ($r in 'permit-v4', 'block-v4', 'permit-v6', 'block-v6') { $k = '{0:x8}-0000-4000-8000-000000000000' -f $st.Next; if ($st.UpperKeys) { $k = $k.ToUpperInvariant() + 'A' }; $st.Next++; $st.F[$k] = $r } }.GetNewClosure()
    $w.Exec = {
        param([string]$Exe, [string[]]$Argv, [int]$TimeoutSec)
        [void]$st.Calls.Add(@($Exe) + @($Argv))
        $out = { param($o, $c, $e = '') [pscustomobject]@{ ExitCode = $c; Stdout = ($o | ConvertTo-Json -Compress -Depth 8); Stderr = $e; TimedOut = $false; Ms = 1 } }
        $a = @($Argv)
        if ($Exe -like '*halfset.exe') {
            if ($a[0] -eq 'enum' -and $a[1] -eq '--all-ours') { return (& $out @{ count = $st.F.Count; ok = (-not $st.Foreign) } $(if ($st.Foreign) { 9 } else { 0 })) }
            if ($a[0] -eq 'enum') {
                if ($a[2] -ne $S1) { return (& $out @{ count = 0; filters = @() } 0) }
                $fs = @(foreach ($k in $st.F.Keys) { $r = $st.F[$k]; @{ key = $k; layer = "ale_auth_connect_$($r.Split('-')[1])"; tool = 'srt-win'; kind = $(if ($r -like 'block*') { 'block-user' } else { 'permit-loopback-user' }) } })
                return (& $out @{ count = $fs.Count; filters = $fs } 0)
            }
            if ($a[0] -eq 'delete-filter') { $st.F.Remove($a[4]); return (& $out @{ ok = $true } 0) }
        }
        if ($Exe -like '*node.exe') {
            $tree = $a[2]
            $v4 = -not ($st.F.Values -contains 'block-v4'); $v6 = -not ($st.F.Values -contains 'block-v6')
            $open = $v4 -or ($tree -eq 'patched' -and $v6)
            if ($open) { return (& $out @{ tree = $tree; ok = $false; code = 'wfp_fence_inactive' } 0) }
            return (& $out @{ tree = $tree; ok = $true; result = @{ target = '127.0.0.1:1' } } 0)
        }
        switch -Regex ($a -join ' ') {
            '^install' {
                $force = $a -contains '--force'
                $s = & $statusOf
                if (-not $force -and $s -eq 'installed') {
                    if (-not ($st.F.Values -contains 'permit-v4' -or $st.F.Values -contains 'permit-v6')) { return (& $out @{} 13 'already installed with port_range=<unknown>') }
                    if ($st.User) { return (& $out @{} 0 'already installed; no changes') }
                }
                if (-not $st.User) { $st.Installs++ }
                $st.User = $true; $st.Ever = $true; $st.F.Clear()
                # An install that creates the account and then fails (as a real one can, exit 14/17/12).
                if ($st.FailInstallNo -gt 0 -and $st.Installs -eq $st.FailInstallNo) { return (& $out @{} 12 'fake: WFP install failed after the account step') }
                & $fill; return (& $out @{} 0 'installed')
            }
            '^wfp status' { $pr = if ($st.F.Values -contains 'permit-v4') { @(60080, 60089) } else { $null }; return (& $out @{ state = (& $statusOf); filters = $st.F.Count; port_range = $pr } 0) }
            '^status' {
                if ($st.BadSids) { return (& $out @{ user = @{ user = @{ exists = $st.User } }; wfp = @{ state = (& $statusOf) } } 0) }
                # A fresh account per install, as on the real machine: each pass has its own SIDs.
                $n = $st.Installs
                return (& $out @{ user = @{ user = @{ sid = "S-1-5-21-1-2-3-10$n"; group_sid = "S-1-5-21-1-2-3-20$n" } }; wfp = @{ state = (& $statusOf) } } 0)
            }
            '^wfp verify' {
                $t = $a[3]; $fam = if ($t.StartsWith('[')) { 'v6' } else { 'v4' }; $port = [int]($t -replace '^.*:', '')
                $inRange = $port -ge 60080 -and $port -le 60089
                $blocked = ($st.F.Values -contains "block-$fam") -and -not ($inRange -and ($st.F.Values -contains "permit-$fam"))
                if (-not $st.User) { return (& $out @{} 15 'not provisioned') }
                return (& $out @{ egress_probe = $(if ($blocked) { 'blocked' } else { 'connected' }); target = $t } $(if ($blocked) { 0 } else { 3 }))
            }
            '^uninstall' { $st.F.Clear(); if (-not $st.LeaveAccount) { $st.User = $false }; return (& $out @{} 0 'uninstalled') }
        }
        return (& $out @{} 99 'fake: unknown vector')
    }.GetNewClosure()
    $w.Footprint = {
        $st.FootprintCalls++
        if ($st.FootprintThrowAfter -gt 0 -and $st.FootprintCalls -gt $st.FootprintThrowAfter) { throw 'fake: footprint read failed' }
        [pscustomobject]@{ account = $st.User; group = $st.User; hklm_key = $st.User; hide_value = $st.User; store_dir = $false; profile_dir = $false; profile_list = $false }
    }.GetNewClosure()
    $w.UserRights = { param($Dir) if ($st.User -or ($st.LeaveRights -and $st.Ever -and $st.Installs -ge $st.LeaveFrom)) { "*S-1-5-21-1-2-3-20$($st.Installs)" } else { '' } }.GetNewClosure()
    $w.Export = { param($Dir)
        if ($st.BlindExport) { return [pscustomobject]@{ ok = $true; srt_win = 0; s1 = 0; s2 = 0; s3 = 0; default_sublayer = 0 } }
        $s1 = $st.F.Count; if ($st.LeaveSublayer -and $st.Ever) { $s1++ }
        [pscustomobject]@{ ok = $true; srt_win = $st.F.Count; s1 = $s1; s2 = 0; s3 = 0; default_sublayer = 0 } }.GetNewClosure()
    $w.AclSnapshot = {
        $h = @{ 'C:\ProgramData' = 'D:(A;;FA;;;SY)'; 'C:\Windows\Temp\t.tmp' = 'D:(A;ID;FA;;;SY)(A;ID;0x1200a9;;;BU)' }
        if ($st.Ever -and -not $st.User) {
            switch ($st.AclAfter) {
                'equivalent' { $h['C:\ProgramData'] = 'D:AI(A;;FA;;;SY)' }
                'narrowed' { $h['C:\Windows\Temp\t.tmp'] = 'D:AI(A;ID;FA;;;SY)' }
                'widened' { $h['C:\Windows\Temp\t.tmp'] = 'D:AI(A;ID;FA;;;SY)(A;ID;FA;;;BU)' }
            }
        } if ($st.User -or ($st.LeaveAcl -and $st.Ever -and $st.Installs -ge $st.LeaveFrom)) { $h['C:\ProgramData\x'] = "D:(D;OICI;WD;;;S-1-5-21-1-2-3-10$($st.Installs))" } else { $h['C:\ProgramData\x'] = 'D:(A;;FA;;;SY)' }; $h }.GetNewClosure()
    $w.Listen = { param([string]$Family, [int]$Port = 0) $p = if ($Port) { $Port } else { 61763 }; @{ Listener = $null; Target = $(if ($Family -eq 'v6') { "[::1]:$p" } else { "127.0.0.1:$p" }) } }
    $w.Unlisten = { param($L) }
    $w.Connect = { param($HostName, $Port, $Ms) if ($HostName -eq $outside) { [pscustomobject]@{ ok = $st.OutsideOk; ms = 1; error = '' } } else { [pscustomobject]@{ ok = $true; ms = 1; error = '' } } }.GetNewClosure()
    $w.AmbientRecorded = { @('C:\ProgramData') }
    $w.StoreSddl = { $null }
    $w.Elevated = { $true }
    $w.FileExists = { param($Path) $true }
    $w.SaveSnapshot = { param($H, $Path) }
    $w.TreeHash = { param($Dir) foreach ($k in 'stock', 'patched') { if ($script:TsTree[$k] -eq $Dir) { return $script:TsTreeSha[$k] } }; return $null }
    $w.Hash = { param($Path) foreach ($k in $script:Exe.Keys) { if ($script:Exe[$k].Path -eq $Path) { return $script:Exe[$k].Sha } }
        if ($Path -eq $script:RunVerify) { return $script:RunVerifySha }
        foreach ($k in 'stock', 'patched') { if ($script:TsUtil[$k] -eq $Path) { return $script:TsUtilSha[$k] } }
        return $null }
    return [pscustomobject]$w
}

function Invoke-SelfTest {
    $checks = New-Object Collections.ArrayList
    $chk = { param($name, $cond) [void]$checks.Add([ordered]@{ name = $name; ok = [bool]$cond }) }
    $script:Exe.node.Sha = 'FAKE'
    # validators: ON
    & $chk 'srt argv: install into S1 allowed' (Test-SrtArgv @('install', '--sublayer-guid', $script:S1, '--proxy-port-range', $script:Range))
    & $chk 'srt argv: install without a sublayer refused (would hit the default sublayer)' (-not (Test-SrtArgv @('install', '--proxy-port-range', $script:Range)))
    & $chk 'srt argv: install into the default sublayer refused' (-not (Test-SrtArgv @('install', '--sublayer-guid', $script:SrtDefaultSubLayer, '--proxy-port-range', $script:Range)))
    & $chk 'srt argv: install into S2 refused' (-not (Test-SrtArgv @('install', '--sublayer-guid', $script:S2, '--proxy-port-range', $script:Range)))
    & $chk 'srt argv: uppercase S1 refused' (-not (Test-SrtArgv @('install', '--sublayer-guid', $script:S1.ToUpper(), '--proxy-port-range', $script:Range)))
    & $chk 'srt argv: --sandbox-user refused' (-not (Test-SrtArgv @('install', '--sublayer-guid', $script:S1, '--proxy-port-range', $script:Range, '--sandbox-user', 'x')))
    & $chk 'srt argv: uninstall without a sublayer refused' (-not (Test-SrtArgv @('uninstall')))
    & $chk 'srt argv: uninstall --keep-user refused' (-not (Test-SrtArgv @('uninstall', '--sublayer-guid', $script:S1, '--keep-user')))
    & $chk 'srt argv: wfp uninstall refused' (-not (Test-SrtArgv @('wfp', 'uninstall', '--sublayer-guid', $script:S1)))
    & $chk 'srt argv: user read-cred refused' (-not (Test-SrtArgv @('user', 'read-cred')))
    & $chk 'srt argv: a re-split vector refused' (-not (Test-SrtArgv @('install --sublayer-guid', $script:S1, '--proxy-port-range', $script:Range)))
    & $chk 'srt argv: verify v6 loopback allowed' (Test-SrtArgv @('wfp', 'verify', '--target', '[::1]:61763'))
    & $chk 'srt argv: verify to a non-loopback host refused' (-not (Test-SrtArgv @('wfp', 'verify', '--target', '1.1.1.1:443')))
    & $chk 'srt argv: verify to a low port refused' (-not (Test-SrtArgv @('wfp', 'verify', '--target', '127.0.0.1:80')))
    & $chk 'halfset argv: delete under S1 with the proof allowed' (Test-HalfsetArgv @('delete-filter', '--sublayer', $script:S1, '--key', 'd3c3365d-ab4c-43ae-9d9f-66c6b1262541', '--live', $script:HarnessProof))
    & $chk 'halfset argv: delete under S2 refused' (-not (Test-HalfsetArgv @('delete-filter', '--sublayer', $script:S2, '--key', 'd3c3365d-ab4c-43ae-9d9f-66c6b1262541', '--live', $script:HarnessProof)))
    & $chk 'halfset argv: install refused' (-not (Test-HalfsetArgv @('install', '--sublayer', $script:S1, '--sid', 'x')))
    & $chk 'halfset argv: uninstall refused' (-not (Test-HalfsetArgv @('uninstall', '--sublayer', $script:S1)))
    & $chk 'node argv: --prepend refused' (-not (Test-NodeArgv @($script:RunVerify, '--tree', 'stock', '--exe', $script:Exe.stock.Path, '--prepend')))
    & $chk 'node argv: another exe refused' (-not (Test-NodeArgv @($script:RunVerify, '--tree', 'stock', '--exe', 'C:\x.exe')))
    # role map
    $mk = { param($r) @{ key = [guid]::NewGuid().ToString(); layer = "ale_auth_connect_$($r.Split('-')[1])"; tool = 'srt-win'; kind = $(if ($r -like 'block*') { 'block-user' } else { 'permit-loopback-user' }) } }
    $j = [pscustomobject]@{ filters = @('block-v4', 'block-v6', 'permit-v4', 'permit-v6' | ForEach-Object { [pscustomobject](& $mk $_) }) }
    & $chk 'role map: full set recognised' (Test-FullSet (Get-RoleMap $j))
    $j2 = [pscustomobject]@{ filters = @('block-v4', 'permit-v4', 'permit-v6' | ForEach-Object { [pscustomobject](& $mk $_) }) }
    & $chk 'role map: three of four is not full' (-not (Test-FullSet (Get-RoleMap $j2)))
    $j3 = [pscustomobject]@{ filters = @('block-v4', 'block-v4' | ForEach-Object { [pscustomobject](& $mk $_) }) }
    & $chk 'role map: a duplicate role is a problem' (-not (Get-RoleMap $j3).Ok)
    # ACL compare
    $A = @{ a = 'D:(A;;FA;;;SY)'; b = 'D:(A;;FA;;;BA)'; c = 'x' }; $B = @{ a = 'D:(A;;FA;;;SY)'; b = 'D:(A;;FA;;;BA)(D;;WD;;;S-1-5-21-9)'; c = 'y' }
    $cmp = Compare-AclSnapshot -A $A -B $B -Churn @{ c = $true } -Sids @('S-1-5-21-9')
    & $chk 'acl: a SID hit is found' ($cmp.SidHits.Count -eq 1)
    & $chk 'acl: a changed entry outside churn is found, churn ignored' ($cmp.Changed.Count -eq 1 -and $cmp.Changed[0] -eq 'b')
    $st0 = Remove-StoreEntries @{ 'C:\ProgramData\sandbox-runtime' = 1; 'C:\ProgramData\sandbox-runtime\ca' = 2; 'C:\ProgramData\sandbox-runtimeX' = 3 } 'C:\ProgramData\sandbox-runtime'
    & $chk 'acl: the store-dir exclusion drops the store and its subtree, not a sibling' ($st0.Count -eq 1 -and $st0.ContainsKey('C:\ProgramData\sandbox-runtimeX'))
    # The proof stamp as it comes back from disk (the round trip turned a string into a DateTime once already: 716fd87a).
    $now = [datetime]::new(2026, 10, 13, 20, 40, 0, [DateTimeKind]::Utc)
    $rt = '{"driver_sha256":"AB","checks_failed":0,"written_utc":"2026-10-13T20:36:26.0000000Z"}' | ConvertFrom-Json
    & $chk 'proof: a 4-minute-old stamp round-tripped through JSON is fresh' (Test-ProofFresh $rt 'AB' $now)
    & $chk 'proof: another driver hash is refused' (-not (Test-ProofFresh $rt 'CD' $now))
    $old = '{"driver_sha256":"AB","checks_failed":0,"written_utc":"2026-10-12T20:36:26Z"}' | ConvertFrom-Json
    & $chk 'proof: a 24h04m-old stamp is refused' (-not (Test-ProofFresh $old 'AB' $now))
    $fut = [pscustomobject]@{ driver_sha256 = 'AB'; checks_failed = 0; written_utc = '2026-10-13T20:50:00+00:00' }
    & $chk 'proof: a stamp 10 minutes ahead is refused (string form)' (-not (Test-ProofFresh $fut 'AB' $now))
    $bad = [pscustomobject]@{ driver_sha256 = 'AB'; checks_failed = 1; written_utc = '2026-10-13T20:36:26Z' }
    & $chk 'proof: a failed check is refused' (-not (Test-ProofFresh $bad 'AB' $now))
    & $chk 'acl class: only the AI flag added is equivalent' ((Get-AclChangeClass 'D:(A;OICIID;FA;;;SY)(A;OICIID;0x1200a9;;;BU)' 'D:AI(A;OICIID;FA;;;SY)(A;OICIID;0x1200a9;;;BU)') -eq 'equivalent')
    & $chk 'acl class: P to PAI with the same ACEs is equivalent' ((Get-AclChangeClass 'D:P(A;;FA;;;WD)' 'D:PAI(A;;FA;;;WD)') -eq 'equivalent')
    & $chk 'acl class: CREATOR OWNER made inherit-only is equivalent' ((Get-AclChangeClass 'D:P(A;OICI;FA;;;CO)(A;OICI;FA;;;SY)' 'D:PAI(A;OICIIO;FA;;;CO)(A;OICI;FA;;;SY)') -eq 'equivalent')
    & $chk 'acl class: an effective-only CREATOR OWNER ACE dropped is equivalent' ((Get-AclChangeClass 'D:P(A;;FA;;;CO)(A;;FA;;;SY)' 'D:PAI(A;;FA;;;SY)') -eq 'equivalent')
    & $chk 'acl class: inherited Users read removed is narrowed' ((Get-AclChangeClass 'D:AI(A;ID;FA;;;BA)(A;ID;0x1200a9;;;BU)' 'D:AI(A;ID;FA;;;BA)') -eq 'narrowed')
    & $chk 'acl class: Users write added is other' ((Get-AclChangeClass 'D:AI(A;ID;FA;;;BA)' 'D:AI(A;ID;FA;;;BA)(A;ID;FA;;;BU)') -eq 'other')
    & $chk 'acl class: a rights mask broadened is other' ((Get-AclChangeClass 'D:(A;;0x1200a9;;;BU)' 'D:(A;;FA;;;BU)') -eq 'other')
    & $chk 'acl class: a deny removed is other' ((Get-AclChangeClass 'D:(D;OICI;WD;;;BU)(A;;FA;;;SY)' 'D:(A;;FA;;;SY)') -eq 'other')
    & $chk 'acl class: a deny added is other (stops: a deny left behind is exactly what an uninstall must not do)' ((Get-AclChangeClass 'D:(A;;FA;;;SY)' 'D:(D;OICI;WD;;;BU)(A;;FA;;;SY)') -eq 'other')
    & $chk 'acl class: an allow moved ahead of a deny (ID swapped) is other' ((Get-AclChangeClass 'D:AI(D;;FA;;;BU)(A;ID;FA;;;BU)' 'D:AI(A;;FA;;;BU)(D;ID;FA;;;BU)') -eq 'other')
    & $chk 'acl class: a deny moved after an allow is other' ((Get-AclChangeClass 'D:(D;;FA;;;BU)(A;;FA;;;BU)' 'D:(A;;FA;;;BU)(D;;FA;;;BU)') -eq 'other')
    & $chk 'acl class: an inherited deny overtaken by an explicit allow is other' ((Get-AclChangeClass 'D:AI(D;ID;WD;;;BU)(A;ID;FA;;;BU)' 'D:AI(A;;FA;;;BU)(D;ID;WD;;;BU)') -eq 'other')
    & $chk 'acl class: a Users allow losing inherit-only is other' ((Get-AclChangeClass 'D:(A;OICIIO;FA;;;BU)(A;;FA;;;SY)' 'D:(A;OICI;FA;;;BU)(A;;FA;;;SY)') -eq 'other')
    & $chk 'acl class: an inheritable CREATOR OWNER full control added is other' ((Get-AclChangeClass 'D:(A;;FA;;;SY)' 'D:(A;;FA;;;SY)(A;OICIIO;FA;;;CO)') -eq 'other')
    & $chk 'acl class: with a deny present, the AI flag alone is equivalent' ((Get-AclChangeClass 'D:(D;OICI;WD;;;BU)(A;OICIID;FA;;;SY)' 'D:AI(D;OICI;WD;;;BU)(A;OICIID;FA;;;SY)') -eq 'equivalent')
    & $chk 'acl class: with a deny present, an allow removed in place is narrowed' ((Get-AclChangeClass 'D:(D;;WD;;;BU)(A;;FA;;;SY)(A;;FR;;;BU)' 'D:(D;;WD;;;BU)(A;;FA;;;SY)') -eq 'narrowed')
    & $chk 'acl class: with a deny present, allows reordered is other' ((Get-AclChangeClass 'D:(D;;WD;;;BU)(A;;FA;;;SY)(A;;FR;;;BU)' 'D:(D;;WD;;;BU)(A;;FR;;;BU)(A;;FA;;;SY)') -eq 'other')
    & $chk 'acl class: the real Windows\Temp case (allows only, reordered, two dropped) is narrowed' ((Get-AclChangeClass 'D:AI(A;ID;FA;;;BA)(A;ID;FA;;;SY)(A;ID;0x1200a9;;;WD)(A;ID;0x1200a9;;;BU)' 'D:AI(A;ID;FA;;;SY)(A;ID;FA;;;BA)') -eq 'narrowed')
    & $chk 'acl class: unparseable SDDL is other' ((Get-AclChangeClass 'D:(A;;FA;;;SY)' 'garbage') -eq 'other')
    & $chk 'acl: churn set from two baselines' ((Get-ChurnSet @{ a = 1; b = 2 } @{ a = 1; b = 3; d = 4 }).Count -eq 2)

    $outDir = Join-Path ([IO.Path]::GetTempPath()) ("srtcli-selftest-" + [guid]::NewGuid().ToString('N'))
    New-Item -ItemType Directory -Path $outDir | Out-Null
    try {
        foreach ($sem in 'stock', 'patched') {
            $script:RunDir = Join-Path $outDir $sem; New-Item -ItemType Directory -Path $script:RunDir | Out-Null
            $W = New-FakeWorld $sem
            $code = Invoke-Build $W $sem 3
            $rec = Get-Content (Join-Path $script:RunDir 'record.json') -Raw | ConvertFrom-Json
            if ($code -ne 0) { Write-Host "fake $sem stopped: $($rec | Select-Object stop, preflight | ConvertTo-Json -Compress -Depth 5)" }
            & $chk "$sem fake: exit 0, 3 passes" ($code -eq 0 -and $rec.passes_done -eq 3)
            & $chk "$sem fake: 7 states per pass recorded" (@($rec.states).Count -eq 21)
            & $chk "$sem fake: the export positive control ran once per pass and saw S1" (@($rec.export_controls | Where-Object { $_.export.s1 -gt 0 }).Count -eq 3)
            & $chk "$sem fake: every after-uninstall clean" (@($rec.after_uninstall | Where-Object { -not $_.clean }).Count -eq 0 -and @($rec.after_uninstall).Count -eq 3)
            & $chk "$sem fake: no srt-win vector without S1 reached the executor" (@($W.State.Calls | Where-Object { $_[0] -like '*srt-win.exe' -and ($_ -join ' ') -notmatch [regex]::Escape($script:S1) -and $_[1] -ne 'wfp' }).Count -eq 0)
            $calls = @($W.State.Calls)
            $badSweep = 0
            for ($ci = 0; $ci -lt $calls.Count; $ci++) { if ($calls[$ci][1] -eq 'delete-filter') { $nx = $calls[$ci + 1]; if (-not ($nx[0] -like '*halfset.exe' -and $nx[1] -eq 'enum' -and $nx[2] -eq '--all-ours')) { $badSweep++ } } }
            & $chk "$sem fake: every delete is followed at once by the stop sweep" ($badSweep -eq 0)
            & $chk "$sem fake: every TypeScript run points at this build's srt-win" (@($calls | Where-Object { $_[0] -like '*node.exe' -and $_[5] -ne $script:Exe[$sem].Path }).Count -eq 0 -and @($calls | Where-Object { $_[0] -like '*node.exe' }).Count -eq 42)
            & $chk "$sem fake: every halfset delete named S1 and the proof" (@($W.State.Calls | Where-Object { $_[0] -like '*halfset.exe' -and $_[1] -eq 'delete-filter' -and ($_[3] -ne $script:S1 -or $_[7] -ne $script:HarnessProof) }).Count -eq 0)
            $h6 = ($rec.states | Where-Object { $_.pass -eq 1 -and $_.state -eq 'H6' } | Select-Object -First 1)
            & $chk "$sem fake: H6 records v6 connected and v4 blocked" ($h6.verify_v6_out.probe -eq 'connected' -and $h6.verify_v4_out.probe -eq 'blocked')
            & $chk "$sem fake: H6 stock TS reads ok, patched TS does not" ($h6.ts_stock.ok -eq $true -and $h6.ts_patched.ok -eq $false)
            $fr = ($rec.states | Where-Object { $_.pass -eq 1 -and $_.state -eq 'F' } | Select-Object -First 1)
            & $chk "$sem fake: F in-range controls recorded connected on both families" ($fr.verify_v4_in_range.probe -eq 'connected' -and $fr.verify_v6_in_range.probe -eq 'connected')
            $hpR = ($rec.reinstalls | Where-Object { $_.pass -eq 1 -and $_.state -eq 'HP' } | Select-Object -First 1)
            $h6A = ($rec.states | Where-Object { $_.pass -eq 1 -and $_.state -eq 'H6-after-reinstall' } | Select-Object -First 1)
            if ($sem -eq 'stock') {
                & $chk 'stock fake: H6 status installed, reinstall leaves v6 open' ($h6.srt_status.state -eq 'installed' -and $h6A.verify_v6_out.probe -eq 'connected')
                & $chk 'stock fake: HP reinstall recorded exit 13 and the run continued' ($hpR.exit -eq 13)
            } else {
                & $chk 'patched fake: H6 status partial, reinstall closes v6' ($h6.srt_status.state -eq 'partial' -and $h6A.verify_v6_out.probe -eq 'blocked')
                & $chk 'patched fake: HP reinstall exit 0' ($hpR.exit -eq 0)
            }
        }
        foreach ($kind in 'equivalent', 'narrowed') {
            $script:RunDir = Join-Path $outDir "acl-$kind"; New-Item -ItemType Directory -Path $script:RunDir | Out-Null
            $W = New-FakeWorld 'stock' @{ AclAfter = $kind }
            $code = Invoke-Build $W 'stock' 3
            $rec = Get-Content (Join-Path $script:RunDir 'record.json') -Raw | ConvertFrom-Json
            $a1 = @($rec.after_uninstall)[0]
            & $chk "acl: an $kind change is recorded with before and after and does not stop the run" ($code -eq 0 -and $rec.passes_done -eq 3 -and $a1.acl.$kind -eq 1 -and $a1.acl.other -eq 0 -and @($a1.acl.changes)[0].old -and @($a1.acl.changes)[0].new)
        }
        # stops
        $script:RunDir = Join-Path $outDir 'stop-foreign'; New-Item -ItemType Directory -Path $script:RunDir | Out-Null
        $W = New-FakeWorld 'stock'; $W.State.Foreign = $false
        $origExec = $W.Exec; $n = 0
        $W.Exec = { param($Exe, $Argv, $T) $r = & $origExec $Exe $Argv $T; if (@($Argv)[0] -eq 'install') { $W.State.Foreign = $true }; $r }.GetNewClosure()
        $code = Invoke-Build $W 'stock' 3
        $rec = Get-Content (Join-Path $script:RunDir 'record.json') -Raw | ConvertFrom-Json
        & $chk 'stop: a foreign filter after install stops with exit 9 and srt-win uninstall runs once' ($code -ne 0 -and $rec.stop.class -eq 'foreign_filter' -and @($W.State.Calls | Where-Object { $_[1] -eq 'uninstall' }).Count -eq 1)
        $script:RunDir = Join-Path $outDir 'stop-account'; New-Item -ItemType Directory -Path $script:RunDir | Out-Null
        $W = New-FakeWorld 'stock' @{ LeaveAccount = $true }
        $code = Invoke-Build $W 'stock' 3
        $rec = Get-Content (Join-Path $script:RunDir 'record.json') -Raw | ConvertFrom-Json
        & $chk 'stop: an account left after uninstall stops after pass 1 with exit 10, nothing deleted by hand' ($code -eq 10 -and $rec.stop.class -eq 'not_clean_after_uninstall' -and -not $rec.PSObject.Properties['passes_done'] -and $W.State.User)
        $script:RunDir = Join-Path $outDir 'stop-outside'; New-Item -ItemType Directory -Path $script:RunDir | Out-Null
        $W = New-FakeWorld 'patched'; $orig = $W.Exec
        $W.Exec = { param($Exe, $Argv, $T) if (@($Argv)[0] -eq 'install') { $W.State.OutsideOk = $false }; & $orig $Exe $Argv $T }.GetNewClosure()
        $code = Invoke-Build $W 'patched' 3
        $rec = Get-Content (Join-Path $script:RunDir 'record.json') -Raw | ConvertFrom-Json
        & $chk 'stop: two outside failures stop the run and uninstall runs' ($code -ne 0 -and $rec.stop.class -eq 'operator_outside' -and @($W.State.Calls | Where-Object { $_[1] -eq 'uninstall' }).Count -eq 1)
        $cases = @(
            @{ Name = 'an ACE left after uninstall'; Opt = @{ LeaveAcl = $true }; Class = 'not_clean_after_uninstall'; Code = 10; Uninstalls = 1 }
            @{ Name = 'a user right left after uninstall'; Opt = @{ LeaveRights = $true }; Class = 'not_clean_after_uninstall'; Code = 10; Uninstalls = 1 }
            @{ Name = 'SIDs unreadable: uninstall runs, the after-check cannot certify clean'; Opt = @{ BadSids = $true }; Class = 'sids_unreadable'; Code = 10; Uninstalls = 1 }
            @{ Name = 'a refused vector while installed: srt-win uninstall still runs once'; Opt = @{ UpperKeys = $true }; Class = 'argv_refused'; Code = 9; Uninstalls = 1; Clean = $true }
            @{ Name = 'the after-check throws: uninstall runs once, the record keeps the error'; Opt = @{ FootprintThrowAfter = 1 }; Class = 'not_clean_after_uninstall'; Code = 10; Uninstalls = 1 }
            @{ Name = 'a blind export while installed stops the run'; Opt = @{ BlindExport = $true }; Class = 'export_blind'; Code = 9; Uninstalls = 1; Clean = $true }
            @{ Name = 'an access-widening ACL change after uninstall'; Opt = @{ AclAfter = 'widened' }; Class = 'not_clean_after_uninstall'; Code = 10; Uninstalls = 1 }
            @{ Name = 'a sublayer left after uninstall'; Opt = @{ LeaveSublayer = $true }; Class = 'not_clean_after_uninstall'; Code = 10; Uninstalls = 1 }
            @{ Name = 'pass 2 install fails before its SIDs are read and leaves a right: pass 2 SIDs are searched, not pass 1''s'; Opt = @{ LeaveRights = $true; LeaveFromPass = 2; FailInstallNo = 2 }; Class = 'install_failed'; Code = 10; Uninstalls = 2 }
            @{ Name = 'an ACE left by pass 2 (fresh SIDs per pass) is still found'; Opt = @{ LeaveAcl = $true; LeaveFromPass = 2 }; Class = 'not_clean_after_uninstall'; Code = 10; Uninstalls = 2 }
        )
        foreach ($cs in $cases) {
            $script:RunDir = Join-Path $outDir ([guid]::NewGuid().ToString('N')); New-Item -ItemType Directory -Path $script:RunDir | Out-Null
            $W = New-FakeWorld 'stock' $cs.Opt
            $code = Invoke-Build $W 'stock' 3
            $rec = Get-Content (Join-Path $script:RunDir 'record.json') -Raw | ConvertFrom-Json
            $un = @($W.State.Calls | Where-Object { $_[1] -eq 'uninstall' }).Count
            $wantClean = $cs.ContainsKey('Clean') -and $cs.Clean
            # The last after-uninstall record decides (earlier passes may have been clean).
            $okAfter = (@($rec.after_uninstall).Count -ge 1) -and ([bool](@($rec.after_uninstall)[-1].clean) -eq $wantClean)
            if ($cs.Opt.ContainsKey('FootprintThrowAfter')) { $okAfter = $okAfter -and [bool](@($rec.after_uninstall)[-1].PSObject.Properties['check_error']) }
            if (-not ($code -eq $cs.Code -and $rec.stop.class -eq $cs.Class -and $un -eq $cs.Uninstalls -and $okAfter)) { Write-Host "  debug $($cs.Name): code=$code class=$($rec.stop.class) uninstalls=$un okAfter=$okAfter after=$($rec.after_uninstall | ConvertTo-Json -Compress -Depth 3)" }
            & $chk "stop: $($cs.Name) (class $($cs.Class), exit $($cs.Code))" ($code -eq $cs.Code -and $rec.stop.class -eq $cs.Class -and $un -eq $cs.Uninstalls -and $okAfter)
        }
        # The TypeScript tree pin: wrong at preflight -> exit 3 with nothing run; right at preflight, changed before the first node call -> stop.
        $script:RunDir = Join-Path $outDir 'tree-pre'; New-Item -ItemType Directory -Path $script:RunDir | Out-Null
        $W = New-FakeWorld 'stock'; $W.TreeHash = { param($d) 'WRONG' }
        $code = Invoke-Build $W 'stock' 3
        & $chk 'lock: a TypeScript tree that is not the pinned tree fails preflight (exit 3, no srt-win call)' ($code -eq 3 -and @($W.State.Calls | Where-Object { $_[0] -like '*srt-win.exe' }).Count -eq 0)
        $script:RunDir = Join-Path $outDir 'tree-mid'; New-Item -ItemType Directory -Path $script:RunDir | Out-Null
        $W = New-FakeWorld 'stock'; $orig = $W.TreeHash; $stT = $W.State
        $W.TreeHash = { param($d) if ($stT.User) { 'CHANGED' } else { & $orig $d } }.GetNewClosure()
        $code = Invoke-Build $W 'stock' 3
        $rec = Get-Content (Join-Path $script:RunDir 'record.json') -Raw | ConvertFrom-Json
        & $chk 'lock: a TypeScript tree changed after preflight stops at the first node call, no node run' ($code -eq 9 -and $rec.stop.class -eq 'hash_mismatch' -and @($W.State.Calls | Where-Object { $_[0] -like '*node.exe' }).Count -eq 0)
        $script:RunDir = Join-Path $outDir 'hash-mid'; New-Item -ItemType Directory -Path $script:RunDir | Out-Null
        $W = New-FakeWorld 'stock'; $origHash = $W.Hash; $st2 = $W.State
        $W.Hash = { param($p) if ($st2.User -and $p -like '*srt-win.exe') { 'CHANGED' } else { & $origHash $p } }.GetNewClosure()
        $code = Invoke-Build $W 'stock' 3
        $rec = Get-Content (Join-Path $script:RunDir 'record.json') -Raw | ConvertFrom-Json
        & $chk 'stop: srt-win changes while installed: uninstall cannot run, the record says what is left, exit 10' ($code -eq 10 -and $rec.stop.class -eq 'hash_mismatch' -and $rec.left_installed -eq $true -and $rec.left_installed_footprint.account -eq $true)
        # lock tested OFF: with the srt allowlist switched off, a vector without the sublayer reaches the executor
        $script:RunDir = Join-Path $outDir 'toggle'; New-Item -ItemType Directory -Path $script:RunDir | Out-Null
        $W = New-FakeWorld 'stock'; $script:Log = New-Object Collections.ArrayList
        $refused = $false; try { $null = Invoke-Checked $W 'stock' @('install', '--proxy-port-range', $script:Range) 5 'toggle-on' } catch [StopRun] { $refused = $_.Exception.Class -eq 'argv_refused' }
        & $chk 'lock ON: an install without the sublayer is refused before the executor' ($refused -and $W.State.Calls.Count -eq 0)
        $saved = ${function:Test-SrtArgv}; ${function:Test-SrtArgv} = { param($Argv) $true }
        try { $null = Invoke-Checked $W 'stock' @('install', '--proxy-port-range', $script:Range) 5 'toggle-off' } finally { ${function:Test-SrtArgv} = $saved }
        & $chk 'lock OFF: the same vector reaches the executor (the check is what stops it)' ($W.State.Calls.Count -eq 1)
        $W2 = New-FakeWorld 'stock'; $W2.Hash = { param($p) 'BAD' }
        $hm = $false; try { $null = Invoke-Checked $W2 'stock' @('wfp', 'status', '--sublayer-guid', $script:S1) 5 'hash' } catch [StopRun] { $hm = $_.Exception.Class -eq 'hash_mismatch' }
        & $chk 'lock: a changed exe hash is refused before the executor' ($hm -and $W2.State.Calls.Count -eq 0)
    } finally { Remove-Item -LiteralPath $outDir -Recurse -Force -ErrorAction SilentlyContinue; $script:RunDir = $null }
    $failed = @($checks | Where-Object { -not $_.ok })
    foreach ($c in $checks) { Write-Host ('{0}  {1}' -f $(if ($c.ok) { 'PASS' } else { 'FAIL' }), $c.name) }
    Write-Host ("self-test: {0} checks, {1} failed" -f $checks.Count, $failed.Count)
    return @{ Total = $checks.Count; Failed = $failed.Count }
}

# ---- entry ----------------------------------------------------------------------------------------------------------------------------
$modes = @($SelfTest, $DryRun, $Run | Where-Object { $_ }).Count
if ($modes -ne 1) { [Console]::Error.WriteLine('exactly one of -SelfTest, -DryRun, -Run'); exit 2 }
$proofPath = Join-Path $PSScriptRoot 'srtcli-proof.json'

if ($SelfTest) {
    $r = Invoke-SelfTest
    if ($r.Failed -ne 0) { exit 1 }
    if ($WriteProof) {
        [ordered]@{ schema = 'nep5-1763-srtcli-proof-v1'; driver_sha256 = (Get-Sha256 $PSCommandPath); checks = $r.Total; checks_failed = 0; written_utc = (Get-Date).ToUniversalTime().ToString('o') } |
            ConvertTo-Json | Set-Content -LiteralPath $proofPath -Encoding utf8NoBOM
        Write-Output "proof written: $proofPath"
    }
    exit 0
}

$W = New-RealWorld
$script:Exe.node.Sha = Get-Sha256 $script:Exe.node.Path
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'

if ($DryRun) {
    $script:RunDir = Join-Path $OutRoot "nep5-srtcli-dryrun-$stamp"; New-Item -ItemType Directory -Path $script:RunDir | Out-Null
    $script:Log = New-Object Collections.ArrayList
    $pf = Invoke-Preflight $W -Live
    $pf | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath (Join-Path $script:RunDir 'preflight.json') -Encoding utf8NoBOM
    Write-Output ($pf | ConvertTo-Json -Depth 6)
    if ($pf.Ok) { exit 0 } else { exit 3 }
}

# -Run
if (-not $Build) { [Console]::Error.WriteLine('-Run needs -Build stock|patched'); exit 2 }
if (-not (& $W.Elevated)) { [Console]::Error.WriteLine('not elevated'); exit 5 }
try { $proof = Get-Content -LiteralPath $proofPath -Raw | ConvertFrom-Json } catch { [Console]::Error.WriteLine('no self-test proof'); exit 4 }
if (-not (Test-ProofFresh $proof (Get-Sha256 $PSCommandPath) (Get-Date).ToUniversalTime())) { [Console]::Error.WriteLine('self-test proof stale or for another script'); exit 4 }
$script:RunDir = Join-Path $OutRoot "nep5-srtcli-$Build-$stamp"; New-Item -ItemType Directory -Path $script:RunDir | Out-Null
$code = Invoke-Build $W $Build $Passes
Write-Output "record: $(Join-Path $script:RunDir 'record.json')  exit $code"
exit $code
