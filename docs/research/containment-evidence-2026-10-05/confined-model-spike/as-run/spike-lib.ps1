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
    param(
        [Parameter(Mandatory)][AllowEmptyCollection()][string[]]$ExportLines,
        [Parameter(Mandatory)][string]$Privilege,
        [Parameter(Mandatory)][string]$Sid,
        [Parameter(Mandatory)][ValidateSet('add','remove')][string]$Mode
    )
    $token = "*$Sid"
    $line = $ExportLines | Where-Object { $_ -match "^\s*$([regex]::Escape($Privilege))\s*=" } | Select-Object -First 1
    $members = @()
    if ($line) {
        $rhs = ($line -split '=', 2)[1]
        $members = @($rhs -split ',' | ForEach-Object { $_.Trim() } | Where-Object { $_ })
    }
    if ($Mode -eq 'add') {
        if ($members -contains $token) { return $null }
        return "$Privilege = " + (@($members + $token) -join ',')
    } else {
        if (-not ($members -contains $token)) { return $null }
        $kept = @($members | Where-Object { $_ -ne $token })
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
$script:StepStatuses   = @('pass', 'fail', 'error', 'info', 'skipped')
$script:OverallValues  = @('pass', 'fail', 'error')

function Test-IsoTimestamp {
    param($Value)
    if ($Value -isnot [string]) { return $false }
    $d = [datetimeoffset]::MinValue
    return ($Value -match '^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:\d{2})$' -and [datetimeoffset]::TryParse($Value, [ref]$d))
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
    if ($Result.mode -notin @('feasibility', 'serve')) { [void]$v.Add("mode '$($Result.mode)' not in feasibility|serve") }
    if ($Result.overall -notin $script:OverallValues) { [void]$v.Add("overall '$($Result.overall)' not in pass|fail|error") }
    if ($Result.run_id -isnot [string] -or $Result.run_id -notmatch '^[A-Za-z0-9-]{8,64}$') { [void]$v.Add('run_id malformed') }
    foreach ($k in 'started', 'finished') { if (-not (Test-IsoTimestamp $Result.$k)) { [void]$v.Add("top-level $k is not an ISO-8601 timestamp with offset") } }
    $steps = @($Result.steps)
    $req = if ($Result.mode -eq 'serve') { $script:StepNamesServe } else { $script:StepNamesBase }
    foreach ($n in $req) {
        $c = @($steps | Where-Object { $_.name -eq $n }).Count
        if ($c -ne 1) { [void]$v.Add("step '$n' must appear exactly once (found $c)") }
    }
    $prev = $null
    foreach ($s in $steps) {
        $sn = @($s.PSObject.Properties.Name)
        foreach ($k in 'name', 'status', 'started', 'finished', 'detail') { if ($sn -notcontains $k) { [void]$v.Add("step '$($s.name)' missing '$k'") } }
        if ($s.status -notin $script:StepStatuses) { [void]$v.Add("step '$($s.name)' status '$($s.status)' invalid") }
        if ($s.name -notin $script:StepNamesServe) { [void]$v.Add("unknown step name '$($s.name)'") }
        foreach ($k in 'started', 'finished') { if (-not (Test-IsoTimestamp $s.$k)) { [void]$v.Add("step '$($s.name)' $k not ISO-8601") } }
        if ((Test-IsoTimestamp $s.started) -and (Test-IsoTimestamp $s.finished)) {
            $a = [datetimeoffset]::Parse($s.started); $b = [datetimeoffset]::Parse($s.finished)
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
