#requires -Version 5.1
<#
.SYNOPSIS
  Pure helpers for the #1689 confined-inference-service spike (account `blarai-spike`). Dot-source it; it has NO
  side effects on load and no function here changes the system. Everything the -SelfTest of the provision /
  cleanup / verify scripts exercises lives here so it can be tested without an account, an ACL or a GPU.

  Patterns reused from C:\Users\_OPERATOR_\agentic-setup\scripts\coder-provisioning-lib.ps1 (Resolve-PrivilegeLine,
  password generation) and provision-coder-account.ps1 (SID-form icacls, Users-only membership).
#>

$script:SpikeUser       = 'blarai-spike'
$script:SpikeDescMarker = 'BlarAI #1689 throwaway spike account (delete me)'
$script:SpikeTaskPath   = '\BlarAI\'
$script:SpikeTaskName   = 'BlarAI-Spike-Model'
$script:SpikeRoot       = 'C:\blarai-spike'
$script:SpikeProfileDir = 'C:\Users\blarai-spike'
$script:OperatorRoot    = 'C:\Users\_OPERATOR_'
$script:SpikeVenv       = 'C:\Users\_OPERATOR_\BlarAI\.venv-2026.4'
$script:SpikeModelDir   = 'B:\models\Qwen3.5-4B-int8-ov'
$script:SpikeOutDir     = 'C:\Users\_OPERATOR_\blarai-research-data\confined-model-spike'
$script:SpikeStatePath  = 'C:\Users\_OPERATOR_\blarai-research-data\confined-model-spike\spike-state.json'
$script:SpikeCleanedPath = 'C:\Users\_OPERATOR_\blarai-research-data\confined-model-spike\spike-state.cleaned.json'
$script:WellKnown = @{ System = 'S-1-5-18'; Admins = 'S-1-5-32-544'; Users = 'S-1-5-32-545'; Everyone = 'S-1-1-0'; AuthUsers = 'S-1-5-11' }

function Test-SpikeUserName {
    # PURE. Only the one fixed account name is accepted by default; a different name must still be a plain token.
    param([string]$Name)
    return ($Name -match '^[A-Za-z0-9][A-Za-z0-9._-]{0,19}$')
}

function Test-AccountDomainSid {
    param([string]$Sid)
    return ($Sid -match '^S-1-5-21-\d+-\d+-\d+-\d{3,}$')
}

function Resolve-PrivilegeLine {
    # PURE. Same contract as coder-provisioning-lib.ps1 Resolve-PrivilegeLine: the new "[Privilege Rights]" line for
    # $Privilege after adding/removing $Sid, preserving every other holder; $null when nothing changes (idempotent).
    # `secedit /export` writes a holder whose account still exists by NAME (e.g. "blarai-spike") and an orphaned
    # holder as "*<SID>", so a holder is matched in either form: pass -Name while the account exists.
    param(
        [Parameter(Mandatory)][AllowEmptyCollection()][string[]]$ExportLines,
        [Parameter(Mandatory)][string]$Privilege,
        [Parameter(Mandatory)][string]$Sid,
        [Parameter(Mandatory)][ValidateSet('add','remove')][string]$Mode,
        [string]$Name
    )
    $token = "*$Sid"
    $isHolder = { param($m) ($m -eq $token) -or ($Name -and ($m -ieq $Name)) }
    $line = $ExportLines | Where-Object { $_ -match "^\s*$([regex]::Escape($Privilege))\s*=" } | Select-Object -First 1
    $members = @()
    if ($line) {
        $rhs = ($line -split '=', 2)[1]
        $members = @($rhs -split ',' | ForEach-Object { $_.Trim() } | Where-Object { $_ })
    }
    $present = @($members | Where-Object { & $isHolder $_ }).Count -gt 0
    if ($Mode -eq 'add') {
        if ($present) { return $null }
        return "$Privilege = " + (@($members + $token) -join ',')
    } else {
        if (-not $present) { return $null }
        $kept = @($members | Where-Object { -not (& $isHolder $_) })
        if ($kept.Count -eq 0) { return "$Privilege =" }
        return "$Privilege = " + ($kept -join ',')
    }
}

function Get-PrivilegeHolders {
    # PURE. Members of $Privilege in a `secedit /export` INF (tokens as written, e.g. '*S-1-5-32-544').
    param([string[]]$ExportLines, [string]$Privilege)
    $line = $ExportLines | Where-Object { $_ -match "^\s*$([regex]::Escape($Privilege))\s*=" } | Select-Object -First 1
    if (-not $line) { return @() }
    return @((($line -split '=', 2)[1]) -split ',' | ForEach-Object { $_.Trim() } | Where-Object { $_ })
}

function New-StrongPassword {
    # 24 chars from the crypto RNG, all four classes seeded. Returns a SecureString; never printed or logged.
    $lower = 'abcdefghijkmnpqrstuvwxyz'; $upper = 'ABCDEFGHJKLMNPQRSTUVWXYZ'
    $digit = '23456789'; $sym = '!@#$%^&*()-_=+[]{}'
    $all = ($lower + $upper + $digit + $sym).ToCharArray()
    $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    try {
        $bytes = New-Object 'byte[]' 64
        $rng.GetBytes($bytes)
        $sb = New-Object System.Text.StringBuilder
        foreach ($set in @($lower, $upper, $digit, $sym)) { [void]$sb.Append($set[ [int]($bytes[$sb.Length] % $set.Length) ]) }
        for ($i = 4; $i -lt 24; $i++) { [void]$sb.Append($all[ [int]($bytes[$i] % $all.Length) ]) }
        $plain = $sb.ToString()
        $secure = ConvertTo-SecureString $plain -AsPlainText -Force
        $plain = $null
        return $secure
    } finally { $rng.Dispose() }
}

function Get-VenvBaseHome {
    # PURE on its input. The `home =` directory of a venv's pyvenv.cfg text (the base interpreter the venv python
    # redirects to; it needs Read+Execute for the spike account too). $null if absent.
    param([string[]]$PyvenvCfgLines)
    foreach ($l in $PyvenvCfgLines) {
        if ($l -match '^\s*home\s*=\s*(.+?)\s*$') { return $Matches[1] }
    }
    return $null
}

function Get-SpikeSecretPaths {
    # The operator secret paths verify-coder-containment.ps1 uses, plus the profile root, the repo root and the
    # research-data dir. Resolved against the OPERATOR profile ($OperatorRoot), never the caller's, and filtered
    # to those that exist when $ExistsFilter is set (the provision-time resolution is frozen into the config).
    param([string]$OperatorRoot = $script:OperatorRoot, [string]$OperatorLocalAppData = (Join-Path $script:OperatorRoot 'AppData\Local'), [switch]$ExistsFilter)
    $p = @(
        (Join-Path $OperatorRoot '.ssh'),
        (Join-Path $OperatorRoot '.git-credentials'),
        (Join-Path $OperatorLocalAppData 'BlarAI'),
        (Join-Path $OperatorRoot '.aws'),
        (Join-Path $OperatorRoot '.azure'),
        $OperatorRoot,
        (Join-Path $OperatorRoot 'BlarAI'),
        (Join-Path $OperatorRoot 'blarai-research-data')
    )
    if ($ExistsFilter) { $p = @($p | Where-Object { Test-Path -LiteralPath $_ }) }
    return $p
}

function Get-SpikeAcePlan {
    # PURE. The complete, ordered list of ACL changes provision will make. One row per change:
    #   Path, Principal (spike|operator|system|admins), Sid, Rights ('RX' | 'M' | 'F'), Inherit ('this' | 'tree'),
    #   Kind (grant | disable-inheritance), Purpose, Removable (cleanup removes this SID's ACE on the path).
    # $SpikeSid may be a placeholder string for dry-run listing; all other SIDs are concrete.
    param(
        [Parameter(Mandatory)][string]$SpikeSid,
        [Parameter(Mandatory)][string]$OperatorSid,
        [string]$Root = $script:SpikeRoot,
        [string]$Venv = $script:SpikeVenv,
        [string]$VenvBaseHome,
        [string]$ModelDir = $script:SpikeModelDir
    )
    $rows = New-Object System.Collections.ArrayList
    function Add-Row($path, $who, $sid, $rights, $inherit, $kind, $purpose, $removable) {
        [void]$rows.Add([pscustomobject]@{ Path = $path; Principal = $who; Sid = $sid; Rights = $rights; Inherit = $inherit; Kind = $kind; Purpose = $purpose; Removable = $removable })
    }
    $sys = $script:WellKnown.System; $adm = $script:WellKnown.Admins
    # spike work tree: protected DACL, operator + SYSTEM + Administrators + the spike account, NOT Authenticated Users.
    Add-Row $Root 'operator' $OperatorSid '' '' 'disable-inheritance' 'spike root: stop inheriting the C:\ ACL (which carries Authenticated Users)' $false
    Add-Row $Root 'system'   $sys 'F' 'tree' 'grant' 'spike root' $false
    Add-Row $Root 'admins'   $adm 'F' 'tree' 'grant' 'spike root' $false
    Add-Row $Root 'operator' $OperatorSid 'F' 'tree' 'grant' 'spike root: operator reads the results' $false
    Add-Row $Root 'spike'    $SpikeSid 'RX' 'this' 'grant' 'traverse the root only (not inherited by children)' $true
    Add-Row (Join-Path $Root 'bin')     'spike' $SpikeSid 'RX' 'tree' 'grant' 'scripts + config the task runs (operator-written; the account cannot alter its own instructions)' $true
    Add-Row (Join-Path $Root 'work')    'spike' $SpikeSid 'M'  'tree' 'grant' 'scratch + TEMP for the task' $true
    Add-Row (Join-Path $Root 'results') 'spike' $SpikeSid 'M'  'tree' 'grant' 'result JSON, port file, process logs' $true
    Add-Row $Venv 'spike' $SpikeSid 'RX' 'tree' 'grant' 'the Python venv used for Qwen3.5 (read + execute only)' $true
    if ($VenvBaseHome) { Add-Row $VenvBaseHome 'spike' $SpikeSid 'RX' 'tree' 'grant' 'the base interpreter the venv redirects to (read + execute only)' $true }
    Add-Row $ModelDir 'spike' $SpikeSid 'RX' 'tree' 'grant' 'the 4B model directory (read + execute only)' $true
    return @($rows)
}

function Test-AcePlanSafe {
    # PURE. Invariants of any ACE plan. Returns an array of violation strings (empty = safe).
    #  * no ACE for Everyone / Users / Authenticated Users, ever
    #  * the spike account never gets more than RX outside <root>\work and <root>\results
    #  * the spike account gets NO ACE on any operator secret path or on a parent of one inside the profile
    #  * every spike ACE path is in the allowlist (root, bin, work, results, venv, venv base home, model dir)
    param([Parameter(Mandatory)]$Plan, [string[]]$SecretPaths = @(), [string[]]$AllowedSpikePaths, [string]$Root = $script:SpikeRoot)
    $v = New-Object System.Collections.ArrayList
    $bad = @($script:WellKnown.Everyone, $script:WellKnown.Users, $script:WellKnown.AuthUsers)
    $norm = { param($p) ($p -replace '/', '\').TrimEnd('\').ToLowerInvariant() }
    $writable = @((& $norm (Join-Path $Root 'work')), (& $norm (Join-Path $Root 'results')))
    $allowed = @($AllowedSpikePaths | ForEach-Object { & $norm $_ })
    $secrets = @($SecretPaths | ForEach-Object { & $norm $_ })
    foreach ($r in $Plan) {
        if ($bad -contains $r.Sid) { [void]$v.Add("ACE for a broad principal ($($r.Sid)) on $($r.Path)") }
        if ($r.Principal -ne 'spike') { continue }
        $p = & $norm $r.Path
        if ($allowed.Count -gt 0 -and ($allowed -notcontains $p)) { [void]$v.Add("spike ACE on a path outside the allowlist: $($r.Path)") }
        if ($r.Rights -notin @('RX', 'M')) { [void]$v.Add("spike ACE with rights '$($r.Rights)' on $($r.Path)") }
        if ($r.Rights -eq 'M' -and ($writable -notcontains $p)) { [void]$v.Add("spike has Modify outside work/results: $($r.Path)") }
        foreach ($s in $secrets) {
            $reaches = ($p -eq $s) -or (($r.Inherit -eq 'tree') -and $s.StartsWith($p + '\'))
            if ($reaches) {
                # A tree grant on the path itself, or on an ancestor of a secret, would reach the secret.
                [void]$v.Add("spike grant on/above a secret path: $($r.Path) reaches $s")
            }
        }
    }
    return @($v)
}

function ConvertTo-IcaclsGrantSpec {
    # PURE. One plan row -> the icacls /grant argument ('*S-..:(OI)(CI)RX'). SID form, language-independent.
    param([Parameter(Mandatory)]$Row)
    $inh = if ($Row.Inherit -eq 'tree') { '(OI)(CI)' } else { '' }
    return "*$($Row.Sid):$inh($($Row.Rights))"
}

function Format-AceRow {
    param([Parameter(Mandatory)]$Row)
    if ($Row.Kind -eq 'disable-inheritance') { return ('{0,-44} DISABLE INHERITANCE (remove inherited ACEs)  [{1}]' -f $Row.Path, $Row.Purpose) }
    $scope = if ($Row.Inherit -eq 'tree') { 'this folder + all children' } else { 'this folder only' }
    return ('{0,-44} {1,-8} {2,-3} {3,-26} [{4}]' -f $Row.Path, $Row.Principal, $Row.Rights, $scope, $Row.Purpose)
}

function Find-SidInIcaclsText {
    # PURE. Lines of `icacls <path> /T` output that mention $Sid or $Name (a deleted account shows as its raw SID).
    param([string[]]$Lines, [Parameter(Mandatory)][string]$Sid, [string]$Name)
    $hits = New-Object System.Collections.ArrayList
    foreach ($l in $Lines) {
        if ($l -and ($l.Contains($Sid) -or ($Name -and $l -match [regex]::Escape($Name)))) { [void]$hits.Add($l.Trim()) }
    }
    return @($hits)
}

function ConvertTo-Utf8NoBom {
    param([Parameter(Mandatory)][string]$Path, [Parameter(Mandatory)][string]$Text)
    [IO.File]::WriteAllText($Path, $Text, (New-Object Text.UTF8Encoding($false)))
}

function Write-JsonAtomic {
    # temp + move; UTF-8 without BOM (Windows PowerShell 5.1 Set-Content -Encoding UTF8 writes a BOM, which Python's
    # json module rejects).
    param([Parameter(Mandatory)][string]$Path, [Parameter(Mandatory)]$Object, [int]$Depth = 12)
    $dir = Split-Path $Path -Parent
    if ($dir -and -not (Test-Path -LiteralPath $dir)) { New-Item -ItemType Directory -Force $dir | Out-Null }
    $tmp = "$Path.tmp"
    ConvertTo-Utf8NoBom -Path $tmp -Text (ConvertTo-Json -InputObject $Object -Depth $Depth)
    Move-Item -LiteralPath $tmp -Destination $Path -Force
}

# --- strict result schema ---------------------------------------------------------------------------------------
$script:StepNamesBase  = @('identity', 'memory', 'gpu_feasibility', 'file_denial', 'outbound_probe')
$script:StepNamesServe = @('identity', 'memory', 'gpu_feasibility', 'file_denial', 'outbound_probe', 'serve')
# client mode (arm 1): the account makes ONE loopback request to an operator-run server and one outbound probe; no model.
$script:StepNamesClient = @('identity', 'client_connect', 'outbound_probe')
# probe mode (arms 2 and 3): the account makes ONE outbound connect and nothing else; no model, no server, no file or memory steps.
$script:StepNamesProbe  = @('identity', 'outbound_probe')
$script:StepNamesAll    = @($script:StepNamesServe + @('client_connect')) | Select-Object -Unique
$script:ModeValues      = @('feasibility', 'serve', 'client', 'probe')
$script:StepStatuses   = @('pass', 'fail', 'error', 'info', 'skipped')
$script:OverallValues  = @('pass', 'fail', 'error')

function Test-IsoTimestamp {
    # PURE. An ISO-8601 timestamp WITH an offset. PowerShell 7's ConvertFrom-Json turns such strings into [datetime]
    # (Windows PowerShell 5.1 leaves them as strings), so a parsed value of either type is accepted; a bare string
    # must carry the offset.
    param($Value)
    if ($Value -is [datetime] -or $Value -is [datetimeoffset]) { return $true }
    if ($Value -isnot [string]) { return $false }
    $d = [datetimeoffset]::MinValue
    return ($Value -match '^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:\d{2})$' -and [datetimeoffset]::TryParse($Value, [ref]$d))
}

function ConvertTo-DateTimeOffset {
    # PURE. The value of a timestamp field however the host parsed it (string, [datetime] or [datetimeoffset]).
    param($Value)
    if ($Value -is [datetimeoffset]) { return $Value }
    if ($Value -is [datetime]) { return [datetimeoffset]$Value }
    return [datetimeoffset]::Parse([string]$Value)
}

function Test-SpikeResultSchema {
    # PURE. $Result is a parsed JSON object (pscustomobject). Returns an array of violations (empty = valid).
    # Strict: required top-level keys, ISO timestamps with offset, a closed set of statuses, every required step
    # present exactly once for the mode, steps in non-decreasing time order, finished >= started everywhere.
    param([Parameter(Mandatory)]$Result)
    $v = New-Object System.Collections.ArrayList
    $names = @($Result.PSObject.Properties.Name)
    foreach ($k in 'schema_version', 'run_id', 'mode', 'started', 'finished', 'overall', 'steps') {
        if ($names -notcontains $k) { [void]$v.Add("missing top-level key '$k'") }
    }
    if ($v.Count) { return @($v) }
    if ($Result.schema_version -ne 1) { [void]$v.Add("schema_version must be 1 (got $($Result.schema_version))") }
    if ($Result.mode -notin $script:ModeValues) { [void]$v.Add("mode '$($Result.mode)' not in " + ($script:ModeValues -join '|')) }
    if ($Result.overall -notin $script:OverallValues) { [void]$v.Add("overall '$($Result.overall)' not in pass|fail|error") }
    if ($Result.run_id -isnot [string] -or $Result.run_id -notmatch '^[A-Za-z0-9-]{8,64}$') { [void]$v.Add('run_id malformed') }
    foreach ($k in 'started', 'finished') { if (-not (Test-IsoTimestamp $Result.$k)) { [void]$v.Add("top-level $k is not an ISO-8601 timestamp with offset") } }
    $steps = @($Result.steps)
    $req = switch ($Result.mode) { 'serve' { $script:StepNamesServe } 'client' { $script:StepNamesClient } 'probe' { $script:StepNamesProbe } default { $script:StepNamesBase } }
    foreach ($n in $req) {
        $c = @($steps | Where-Object { $_.name -eq $n }).Count
        if ($c -ne 1) { [void]$v.Add("step '$n' must appear exactly once (found $c)") }
    }
    $prev = $null
    foreach ($s in $steps) {
        $sn = @($s.PSObject.Properties.Name)
        foreach ($k in 'name', 'status', 'started', 'finished', 'detail') { if ($sn -notcontains $k) { [void]$v.Add("step '$($s.name)' missing '$k'") } }
        if ($s.status -notin $script:StepStatuses) { [void]$v.Add("step '$($s.name)' status '$($s.status)' invalid") }
        if ($s.name -notin $script:StepNamesAll) { [void]$v.Add("unknown step name '$($s.name)'") }
        foreach ($k in 'started', 'finished') { if (-not (Test-IsoTimestamp $s.$k)) { [void]$v.Add("step '$($s.name)' $k not ISO-8601") } }
        if ((Test-IsoTimestamp $s.started) -and (Test-IsoTimestamp $s.finished)) {
            $a = ConvertTo-DateTimeOffset $s.started; $b = ConvertTo-DateTimeOffset $s.finished
            if ($b -lt $a) { [void]$v.Add("step '$($s.name)' finished before it started") }
            if ($prev -and $a -lt $prev) { [void]$v.Add("step '$($s.name)' starts before the previous step") }
            $prev = $a
        }
    }
    # overall must agree with the steps (a result may not claim pass over a failing step).
    $anyErr = @($steps | Where-Object { $_.status -eq 'error' }).Count
    $anyFail = @($steps | Where-Object { $_.status -eq 'fail' }).Count
    if ($Result.overall -eq 'pass' -and ($anyErr + $anyFail) -gt 0) { [void]$v.Add('overall is pass but a step failed or errored') }
    if ($Result.overall -eq 'fail' -and $anyFail -eq 0 -and $anyErr -eq 0) { [void]$v.Add('overall is fail but no step failed') }
    return @($v)
}

function Get-SpikeOverall {
    # PURE. error beats fail beats pass; info/skipped never count.
    param($Steps)
    $st = @($Steps | ForEach-Object { $_.status })
    if ($st -contains 'error') { return 'error' }
    if ($st -contains 'fail') { return 'fail' }
    return 'pass'
}

function Get-SpikeRuntimeConfig {
    # The operator-written, read-only-to-the-account config the task reads. Resolved at provision time.
    param([Parameter(Mandatory)][string]$SpikeSid, [string[]]$SecretPaths, [string]$OperatorSid)
    return [ordered]@{
        schema_version = 1
        spike_user     = $script:SpikeUser
        expected_sid   = $SpikeSid
        operator_sid   = $OperatorSid
        model_dir      = $script:SpikeModelDir
        venv_python    = (Join-Path $script:SpikeVenv 'Scripts\python.exe')
        root           = $script:SpikeRoot
        work_dir       = (Join-Path $script:SpikeRoot 'work')
        results_dir    = (Join-Path $script:SpikeRoot 'results')
        bin_dir        = (Join-Path $script:SpikeRoot 'bin')
        secret_paths   = @($SecretPaths)
        outbound_target = '1.1.1.1:443'
        outbound_timeout_s = 5
        min_free_gb    = 14
        load_timeout_s = 600
        info_write_targets = @('C:\Windows\Temp\spike-write-test.tmp', 'B:\models\spike-write-test.tmp')
    }
}

function Get-AceRemovalPaths {
    # PURE. The paths whose spike-SID ACEs cleanup removes explicitly: every removable row OUTSIDE the spike root
    # (the root is deleted wholesale). Unique, order preserved. Only ACEs for the spike SID are ever removed.
    param([Parameter(Mandatory)]$Plan, [string]$Root = $script:SpikeRoot)
    $r = ($Root -replace '/', '\').TrimEnd('\').ToLowerInvariant()
    $out = New-Object System.Collections.ArrayList
    foreach ($row in $Plan) {
        if (-not $row.Removable) { continue }
        $p = ($row.Path -replace '/', '\').TrimEnd('\').ToLowerInvariant()
        if ($p -eq $r -or $p.StartsWith($r + '\')) { continue }
        if ($out -notcontains $row.Path) { [void]$out.Add($row.Path) }
    }
    return @($out)
}

function Test-SafeDeletePath {
    # PURE. Cleanup deletes ONLY these two exact directories, and never through a reparse point.
    param([string]$Path, [bool]$IsReparsePoint = $false)
    if ($IsReparsePoint) { return $false }
    $n = ($Path -replace '/', '\').TrimEnd('\').ToLowerInvariant()
    return ($n -eq $script:SpikeRoot.ToLowerInvariant() -or $n -eq $script:SpikeProfileDir.ToLowerInvariant())
}

# ---- link-safe filesystem helpers (review follow-up: the spike account could write C:\blarai-spike\{work,results} and its
# ---- profile, so anything the OPERATOR (elevated) does to those trees must never follow a link planted there) ----------
# Windows PowerShell 5.1 follows junctions under Remove-Item -Recurse and Get-ChildItem -Recurse; nothing below relies on
# either. Directory entries are enumerated with .NET (attributes are the entry's own, never the link target's) and a
# reparse point is removed AS A LINK ([IO.Directory]::Delete(p,$false) / [IO.File]::Delete) without being entered.
if (-not ('SpikeLinkNative' -as [type])) {
    Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
using Microsoft.Win32.SafeHandles;
public static class SpikeLinkNative {
    [StructLayout(LayoutKind.Sequential)] public struct FT { public uint a; public uint b; }
    [StructLayout(LayoutKind.Sequential)] struct BHFI {
        public uint FileAttributes; public FT CreationTime; public FT LastAccessTime; public FT LastWriteTime;
        public uint VolumeSerialNumber; public uint FileSizeHigh; public uint FileSizeLow; public uint NumberOfLinks;
        public uint FileIndexHigh; public uint FileIndexLow;
    }
    [DllImport("kernel32.dll", SetLastError = true)] static extern bool GetFileInformationByHandle(SafeFileHandle h, out BHFI i);
    public static int LinkCount(string path) {
        using (var fs = new System.IO.FileStream(path, System.IO.FileMode.Open, System.IO.FileAccess.Read,
               System.IO.FileShare.ReadWrite | System.IO.FileShare.Delete)) {
            BHFI i;
            if (!GetFileInformationByHandle(fs.SafeFileHandle, out i)) throw new System.ComponentModel.Win32Exception();
            return (int)i.NumberOfLinks;
        }
    }
}
'@
}

function Get-FileLinkCount([Parameter(Mandatory)][string]$Path) { return [SpikeLinkNative]::LinkCount($Path) }

function Test-PathExistsNoFollow([string]$Path) {
    # True for a dangling link too (Test-Path says False for those).
    try { [void][IO.File]::GetAttributes($Path); return $true }
    catch [IO.FileNotFoundException] { return $false } catch [IO.DirectoryNotFoundException] { return $false }
}

function Test-IsReparsePoint([Parameter(Mandatory)][string]$Path) {
    # The path's OWN attributes (GetFileAttributes does not follow the link). Throws if unreadable: callers fail closed.
    return [bool]([IO.File]::GetAttributes($Path) -band [IO.FileAttributes]::ReparsePoint)
}

function Assert-AclTargetPlain([Parameter(Mandatory)][string]$Path) {
    # icacls expands wildcards and acts on a link's target: refuse both before any ACL call.
    if ($Path -match '[*?]') { throw "refusing an ACL change on '$Path': wildcard characters (icacls would expand them)" }
    if (-not (Test-PathExistsNoFollow $Path)) { throw "refusing an ACL change on '$Path': it does not exist" }
    if (Test-IsReparsePoint $Path) { throw "refusing an ACL change on '$Path': it is a reparse point (junction or symlink)" }
}

function Get-TreeLinkReport {
    # Walks $Root WITHOUT entering any reparse point. Returns Links (every junction/symlink, file or directory, by path)
    # and Refusals (a hard-linked file with a name outside $Root, or a link count that cannot be listed: fail closed).
    param([Parameter(Mandatory)][string]$Root)
    $links = New-Object Collections.ArrayList; $bad = New-Object Collections.ArrayList
    $rootNoDrive = $Root.Substring(2).TrimEnd('\').ToLowerInvariant()
    $stack = New-Object Collections.Stack; $stack.Push($Root)
    while ($stack.Count) {
        $dir = [string]$stack.Pop()
        foreach ($e in ([IO.DirectoryInfo]$dir).GetFileSystemInfos()) {
            $isDir = [bool]($e.Attributes -band [IO.FileAttributes]::Directory)
            if ($e.Attributes -band [IO.FileAttributes]::ReparsePoint) { [void]$links.Add([pscustomobject]@{ Path = $e.FullName; IsDirectory = $isDir }); continue }
            if ($isDir) { $stack.Push($e.FullName); continue }
            $n = 0
            try { $n = Get-FileLinkCount $e.FullName } catch { [void]$bad.Add("cannot read the link count of '$($e.FullName)': $($_.Exception.Message)"); continue }
            if ($n -gt 1) {
                $names = @(& fsutil.exe hardlink list $e.FullName 2>&1 | ForEach-Object { "$_".Trim() } | Where-Object { $_ })
                if ($LASTEXITCODE -ne 0 -or $names.Count -lt 2) { [void]$bad.Add("cannot list the hard links of '$($e.FullName)' (count $n)"); continue }
                foreach ($nm in $names) { if (-not $nm.ToLowerInvariant().StartsWith($rootNoDrive + '\')) { [void]$bad.Add("hard link '$($e.FullName)' also has the name '$nm' outside the tree") } }
            }
        }
    }
    return [pscustomobject]@{ Links = @($links); Refusals = @($bad) }
}

function Remove-LinkItself([string]$Path, [bool]$IsDirectory) {
    if ((Get-EntryKind $Path) -ne 'link') { throw "refusing to remove '$Path' as a link: it is no longer a link" }
    if ($IsDirectory) { [IO.Directory]::Delete($Path, $false) } else { [IO.File]::Delete($Path) }
    if (Test-PathExistsNoFollow $Path) { throw "could not remove the link '$Path'" }
}

$script:SpikeToctouHook = $null   # TEST HOOK ONLY: a scriptblock called with the entry path between enumerate and delete

function Get-EntryKind([string]$Path) {
    # The kind of ONE entry from its own attributes, read by literal path at this moment: link | dir | file | missing.
    try { $a = [IO.File]::GetAttributes($Path) } catch { return 'missing' }
    if ($a -band [IO.FileAttributes]::ReparsePoint) { return 'link' }
    if ($a -band [IO.FileAttributes]::Directory) { return 'dir' }
    return 'file'
}

function Remove-DirNoFollow([string]$Dir) {
    # Leaf first. For every entry: classify at enumeration, then RE-READ its attributes by literal path immediately before
    # acting; an entry that changed kind in between (for example a directory swapped for a junction) is a failure: stop,
    # delete nothing further. A residual window remains between that last re-read and the delete call itself (see README).
    if ((Get-EntryKind $Dir) -ne 'dir') { throw "refusing to enter '$Dir': it is no longer a plain directory" }
    $entries = @(([IO.DirectoryInfo]$Dir).GetFileSystemInfos() | ForEach-Object {
        $k = if ($_.Attributes -band [IO.FileAttributes]::ReparsePoint) { 'link' } elseif ($_.Attributes -band [IO.FileAttributes]::Directory) { 'dir' } else { 'file' }
        [pscustomobject]@{ Path = $_.FullName; Kind = $k }
    })
    foreach ($e in $entries) {
        if ($script:SpikeToctouHook) { & $script:SpikeToctouHook $e.Path }
        $now = Get-EntryKind $e.Path
        if ($now -ne $e.Kind) { throw "entry '$($e.Path)' changed from $($e.Kind) to $now between enumeration and delete: stopping, nothing further deleted" }
        switch ($e.Kind) {
            'link' { Remove-LinkItself $e.Path ([bool]([IO.File]::GetAttributes($e.Path) -band [IO.FileAttributes]::Directory)) }
            'dir'  { Remove-DirNoFollow $e.Path }
            default { if ([IO.File]::GetAttributes($e.Path) -band [IO.FileAttributes]::ReadOnly) { [IO.File]::SetAttributes($e.Path, [IO.FileAttributes]::Normal) }; [IO.File]::Delete($e.Path) }
        }
    }
    if ((Get-EntryKind $Dir) -ne 'dir') { throw "refusing to delete '$Dir': it is no longer a plain directory" }
    $da = [IO.File]::GetAttributes($Dir); if ($da -band [IO.FileAttributes]::ReadOnly) { [IO.File]::SetAttributes($Dir, [IO.FileAttributes]::Directory) }
    [IO.Directory]::Delete($Dir, $false)
}

function Remove-TreeNoFollow {
    # Delete a tree the spike account could write. Never Remove-Item -Recurse. Refuses (before deleting anything) a root
    # that is itself a link, and any hard-linked file whose other name lies outside the tree. Residual: a process still
    # running as the account could race the walk; cleanup stops every such process first and unregisters the task.
    param([Parameter(Mandatory)][string]$Root)
    if (-not (Test-PathExistsNoFollow $Root)) { return }
    if (Test-IsReparsePoint $Root) { throw "refusing to delete '$Root': it is a reparse point" }
    $rep = Get-TreeLinkReport -Root $Root
    if ($rep.Refusals.Count) { throw ("refusing to delete '$Root': " + ($rep.Refusals -join '; ')) }
    Remove-DirNoFollow $Root
    if (Test-PathExistsNoFollow $Root) { throw "could not fully delete $Root" }
}

function Get-DirSecurity([string]$Path) {
    # .NET Framework (Windows PowerShell 5.1) and .NET (PowerShell 7) expose this differently; the Security module can
    # also be unloadable when a 5.1 host inherits a PowerShell 7 PSModulePath, so no Get-Acl / Set-Acl here.
    $di = New-Object IO.DirectoryInfo $Path
    if ($di.PSObject.Methods['GetAccessControl']) { return $di.GetAccessControl() }
    return [IO.FileSystemAclExtensions]::GetAccessControl($di)
}

function Set-DirSecurity([string]$Path, $Security) {
    $di = New-Object IO.DirectoryInfo $Path
    if ($di.PSObject.Methods['SetAccessControl']) { $di.SetAccessControl($Security) } else { [IO.FileSystemAclExtensions]::SetAccessControl($di, $Security) }
}

function New-PrivateTempDir {
    # %TEMP% can carry a write ACE for a foreign or orphaned SID; a file there that an elevated step later feeds to
    # secedit could be swapped. A fresh random directory with a protected DACL (current user, SYSTEM, Administrators)
    # is where every such file goes.
    $p = Join-Path ([IO.Path]::GetTempPath()) ('spike-' + [guid]::NewGuid().ToString('N'))
    New-Item -ItemType Directory -Path $p | Out-Null
    $sec = New-Object Security.AccessControl.DirectorySecurity
    $sec.SetAccessRuleProtection($true, $false)
    $ids = @([Security.Principal.WindowsIdentity]::GetCurrent().User, (New-Object Security.Principal.SecurityIdentifier 'S-1-5-18'), (New-Object Security.Principal.SecurityIdentifier 'S-1-5-32-544'))
    foreach ($id in $ids) { $sec.AddAccessRule((New-Object Security.AccessControl.FileSystemAccessRule($id, 'FullControl', 'ContainerInherit,ObjectInherit', 'None', 'Allow'))) }
    Set-DirSecurity $p $sec
    return $p
}

function Remove-PrivateTempDir([string]$Path) { if ($Path -and (Test-PathExistsNoFollow $Path)) { try { Remove-TreeNoFollow -Root $Path } catch { } } }

function Read-UntrustedJson {
    # The operator parses JSON written by the restricted account. Refuses a link (junction or symlink) or a hard-linked
    # file in its place, caps the size, decodes as UTF-8 and parses as data only. The caller validates every field it
    # uses (strict schema / range checks) and never uses a path, command or host taken from the content. Only the file
    # and its immediate folder are checked for links (the folders above are operator-owned).
    param([Parameter(Mandatory)][string]$Path, [int]$MaxBytes = 4194304)
    $parent = Split-Path -Path $Path -Parent
    if ($parent -and (Test-IsReparsePoint $parent)) { throw "refusing to read '$Path': its folder is a reparse point" }
    if (Test-IsReparsePoint $Path) { throw "refusing to read '$Path': it is a reparse point" }
    if ((Get-FileLinkCount $Path) -gt 1) { throw "refusing to read '$Path': it has more than one hard link" }
    if (([IO.FileInfo]$Path).Length -gt $MaxBytes) { throw "refusing to read '$Path': larger than $MaxBytes bytes" }
    $bytes = [IO.File]::ReadAllBytes($Path)
    if ($bytes.Length -gt $MaxBytes) { throw "refusing to read '$Path': larger than $MaxBytes bytes" }
    if (Test-IsReparsePoint $Path) { throw "refusing '$Path': became a reparse point while being read" }
    $text = (New-Object Text.UTF8Encoding($false, $true)).GetString($bytes).TrimStart([char]0xFEFF)
    return (ConvertFrom-Json -InputObject $text)
}

function Test-LoopbackPort($Value) {
    # An unprivileged TCP port as an integer; anything else (string, float, out of range) is refused.
    return (($Value -is [int] -or $Value -is [long]) -and $Value -ge 1024 -and $Value -le 65535)
}
