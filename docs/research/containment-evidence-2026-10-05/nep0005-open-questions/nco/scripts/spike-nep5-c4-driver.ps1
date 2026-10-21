#requires -Version 7
<#
.SYNOPSIS
  NEP-0005 open questions, case 4 (a delegated non-administrator): the admin driver. Puts the recorded test sublayer S2 and its provider in place (no filter),
  the public folder the probe runs from and writes into, and the probe's arming proof; collects and validates the probe's records; removes everything by key
  and proves the removal by direct reads; reads back that the account is gone after the Lead Architect's own part C. Read README.md beside this file first.

.DESCRIPTION
  Modes (exactly one):
    -SelfTest [-WriteProof]  pure: every mode below runs against the library's fake engine, fake harness and fake export and this file's fake file system and
               fake account reads (no engine, harness, export, ACL or account call is reachable: a parser check proves it). With -WriteProof (live folder only)
               it also runs the probe's own self-test and `ncoprobe.exe --version` (no engine), checks the matrix's harness proof is fresh, and, if EVERYTHING
               passed, writes case4-selftest-proof.json beside this file.
    -DryRun    prints what -Prepare, -Collect, -Finish and -PartD would do, the ACL plan, the probe proof that would be written, the four probe command lines,
               the manual rollback, and whether a valid driver proof exists. Opens no engine, writes nothing.
    -Check     read-only: the direct sweep (S1/S2/S3, our provider, export hits), the probe's filter key, the public folder and its drop files, the account
               (`net user`), its group membership (`net localgroup`) and its profile folder. Exit 20 everything absent, 21 something present, 22 unreadable.
    -Prepare   elevated; refuses unless the folders are admin-only, the driver proof is valid and the engine reads CLEAN; adds our provider and S2 (no filter)
               through the library's proof-gated adder, reads the engine's and S2's security descriptors, creates the public folder with explicit DACLs,
               copies the probe exe (hash-bound) and writes the probe proof, records everything, prints the run sheet lines.
    -Collect [-ElevationRefused '<what Windows showed>']   validates every record in drop\ (the principal AND the token state its condition names),
               copies every file into the out dir, reads S2 for a filter left behind, prints one table per condition. -ElevationRefused records the Lead
               Architect's note that Windows refused to elevate nco-probe at condition E; it is counted as the E result only when no E record reached the engine.
    -Finish [-ElevationRefused '<note>']   -Collect first, then removal by key (the probe's key, the library's keys, S2, the provider), a direct sweep that
               must read clean, the engine's security descriptor compared with -Prepare's, the public folder's drop ACEs removed and read back, then the folder
               deleted.
    -PartD     read-only after the Lead Architect's part C: the account, its membership, its ProfileList entry and every profile folder of that name must be gone.

  This file NEVER creates, enables, disables, deletes, logs on, resets the password of, or changes the group membership of any account. Its only account
  operations are reads (the NTAccount name translation, Get-LocalUser / Get-LocalGroup / Get-LocalGroupMember by SID, `net user <name>`, `net localgroup <group>`);
  a parser check in -SelfTest holds that. It compiles no C# of its own (the library's Initialize-Nep5Type is the only compile).

  EXIT CODES
    -SelfTest 0 passed / 1 failed.   -DryRun 0.   -Check 20 / 21 / 22.   -PartD 20 all gone / 21 something remains or could not be read.
    -Prepare 0 prepared (the prepare record on disk and read back); 2 refused or failed with nothing left behind (nothing added, an error before the add, or
             a failure after the add whose rollback read back clean, the prepare record included); 7 ONLY a failure after the add whose rollback did not verify;
             9 STOP (a foreign filter of ours or srt-win's, or the account is the operator, in his token or in Administrators).
    -Collect 0; 4 a record or file is invalid (wrong principal, wrong token state, misnamed, a sub-folder, or an -ElevationRefused note an E record
             contradicts); 21 a filter is left behind, or the engine could not be read, or an unexpected error (nothing claimed); 9 STOP (a foreign filter, or an
             F/E add that SUCCEEDED under a principal that is not the account).
    -Finish  0 removed and verified; 7 NOT verified, or an unexpected error (manual rollback printed); 9 STOP (a foreign filter: nothing removed; or the
             wrong-principal finding, after a verified removal).
    -Check   an unexpected error is 22.   -PartD an unexpected error is 21.
    Every live mode: 2 when it is refused before it reads or changes anything (not elevated, bad arguments).
#>
[CmdletBinding()]
param(
    [switch]$SelfTest,
    [switch]$WriteProof,
    [switch]$DryRun,
    [switch]$Check,
    [switch]$Prepare,
    [switch]$Collect,
    [switch]$Finish,
    [switch]$PartD,
    [string]$ElevationRefused,
    [string]$WfpSha256,
    [string]$HarnessSha256
)
$ErrorActionPreference = 'Stop'

# The bytes of this file, read ONCE before anything else runs (CRLF read as LF): what the driver proof binds is this hash.
$script:C4SelfName = 'spike-nep5-c4-driver.ps1'
$script:C4SelfSha = & {
    $b = [IO.File]::ReadAllBytes($PSCommandPath); $ms = New-Object IO.MemoryStream
    for ($i = 0; $i -lt $b.Length; $i++) { if ($b[$i] -eq 13 -and $i + 1 -lt $b.Length -and $b[$i + 1] -eq 10) { continue }; $ms.WriteByte($b[$i]) }
    $sha = [Security.Cryptography.SHA256]::Create()
    try { ([BitConverter]::ToString($sha.ComputeHash($ms.ToArray()))) -replace '-', '' } finally { $sha.Dispose(); $ms.Dispose() }
}

$script:LoadedLibHashes = @{}; $script:LoadedLibFolder = $PSScriptRoot; $script:C4LoadedLibPaths = [ordered]@{}
# Where an attended -SelfTest WITHOUT -WriteProof may find a file in the repository layout when it is not beside this script (the live folder is flat).
$script:C4RepoFallback = @{
    'spike-lib.ps1' = '..\..\..\arm3-persist\scripts'; 'spike-persist-lib.ps1' = '..\..\..\arm3-persist\scripts'; 'spike-task-driver.ps1' = '..\..\..\arm3-persist\scripts'
    'spike-nep5-lib.ps1' = '..\..\scripts'; 'wfp-coder-egress-spike.ps1' = '..\..\..\wfp-spike'
    'NcoProbe.cs' = '..\probe'; 'BuildInfo.cs' = '..\probe'; 'build-probe.ps1' = '..\probe'; 'run-probe-selftest.ps1' = '..\probe'; 'RUN_SHEET.md' = '..'
}
function Join-C4Path {
    # PURE. Path joining as text ([IO.Path]::Combine): unlike Join-Path it never asks a provider about the drive, so a stand-in path needs no real drive.
    param([Parameter(Mandatory)][string]$Path, [Parameter(Mandatory)][string]$ChildPath)
    return [IO.Path]::Combine($Path, $ChildPath)
}

function Resolve-LibPath {
    # A file sits beside this script (the admin-only live folder). Only an attended -SelfTest without -WriteProof may fall back to the repository layout.
    param([Parameter(Mandatory)][string]$Name)
    $p = Join-C4Path $PSScriptRoot $Name
    if (Test-Path -LiteralPath $p) { return $p }
    if ($SelfTest -and -not $WriteProof -and $script:C4RepoFallback.ContainsKey($Name)) {
        $q = Join-C4Path (Join-C4Path $PSScriptRoot $script:C4RepoFallback[$Name]) $Name
        if (Test-Path -LiteralPath $q) { return (Resolve-Path -LiteralPath $q).Path }
    }
    return $p
}
function Get-VerifiedLibBlock {
    # Reads a library ONCE, records the SHA-256 (CRLF read as LF) of exactly those bytes, and returns a scriptblock built from that same text for the caller to
    # dot-source at script scope: `. (Get-VerifiedLibBlock 'x.ps1')`. There is no second read, so what is hashed (for the driver proof) is what runs.
    param([Parameter(Mandatory)][string]$Name)
    $path = Resolve-LibPath -Name $Name
    $bytes = [IO.File]::ReadAllBytes($path)
    $ms = New-Object IO.MemoryStream
    for ($i = 0; $i -lt $bytes.Length; $i++) { if ($bytes[$i] -eq 13 -and $i + 1 -lt $bytes.Length -and $bytes[$i + 1] -eq 10) { continue }; $ms.WriteByte($bytes[$i]) }
    $sha = [Security.Cryptography.SHA256]::Create()
    try { $script:LoadedLibHashes[$Name] = ([BitConverter]::ToString($sha.ComputeHash($ms.ToArray()))) -replace '-', '' } finally { $sha.Dispose(); $ms.Dispose() }
    $script:C4LoadedLibPaths[$Name] = $path
    return [scriptblock]::Create([Text.Encoding]::UTF8.GetString($bytes).TrimStart([char]0xFEFF))
}
. (Get-VerifiedLibBlock 'spike-lib.ps1')
. (Get-VerifiedLibBlock 'spike-persist-lib.ps1')
. (Get-VerifiedLibBlock 'spike-task-driver.ps1')
. (Get-VerifiedLibBlock 'spike-nep5-lib.ps1')
$WfpScript = Resolve-LibPath -Name 'wfp-coder-egress-spike.ps1'

# ---- recorded constants (fixed here; S2, the provider, the layer, the stale SID and the marker are the library's) ------------------------------------------
$script:C4ProbeKey = 'c4a0e001-0000-4d8e-9a31-2b6d4c8e0041'   # the probe's ONE filter key (it adds and deletes only this key, in S2)
$script:C4Account = 'nco-probe'
$script:C4NcoGroupSid = 'S-1-5-32-556'; $script:C4AdminsSid = 'S-1-5-32-544'; $script:C4SystemSid = 'S-1-5-18'; $script:C4UsersSid = 'S-1-5-32-545'
$script:C4PubRoot = 'C:\ProgramData\BlarAI\case4-pub'
$script:C4ProbeProofSchema = 'nep5-case4-probe-proof-v1'; $script:C4RecordSchema = 'nep5-case4-record-v1'; $script:C4ProbeStopLine = 'STOP: tell the session before the next run'; $script:C4ProbeStopLineWrongPrincipal = 'STOP: wrong principal; tell the session before the next run'; $script:C4DriverProofSchema = 'nep5-case4-driver-proof-v1'
$script:C4DriverProofName = 'case4-selftest-proof.json'; $script:C4ProbeProofName = 'nco-probe-live.json'
$script:C4HarnessProofName = 'harness-live-proof-1763.json'; $script:C4MatrixProofName = 'rollback-selftest-proof-1763.json'
$script:C4ProbeExeName = 'ncoprobe.exe'; $script:C4WrappedName = 'wfp-coder-egress-spike.ps1'
$script:C4Conds = @('F', 'E', 'S', 'A')
$script:C4DisplayName = "$($script:N5Marker) case4 nco probe"
$script:C4CorpusName = 'case4-lock-corpus.json'
$script:C4TextFiles = @($script:C4SelfName, $script:C4CorpusName, 'run-limited.ps1', 'NcoProbe.cs', 'BuildInfo.cs', 'build-probe.ps1', 'run-probe-selftest.ps1')
$script:C4LibFiles = @('spike-lib.ps1', 'spike-persist-lib.ps1', 'spike-task-driver.ps1', 'spike-nep5-lib.ps1')
$script:C4RawFiles = @($script:C4ProbeExeName, 'halfset.exe', 'halfset.rs', $script:C4HarnessProofName)
$script:C4RequiredTags = @('acl-plan-pure', 'acl-refuses-admin-member', 'acl-refuses-group', 'acl-refuses-operator-sid', 'prepare-refused-without-proof', 'prepare-refused-over-stale-objects',
                           'prepare-stops-on-foreign', 'plan-provider-and-s2-only', 'plan-no-filters', 'probe-proof-fields', 'probe-proof-hash-binding', 'record-validation',
                           'record-wrong-account-stop', 'collect-left-behind', 'finish-removes-by-key', 'finish-sweep-must-be-clean', 'finish-removes-folder', 'finish-ace-removal-read-back',
                           'partd-reads', 'seams', 'no-account-lifecycle', 'proof-hash-binding', 'harness-live-proof-fresh', 'controls-tested-off', 'record-owner', 'copy-owner')
$script:C4MinChecks = 60; $script:C4ProofMaxAgeHours = 24; $script:C4ProofNonce = $null
$script:C4RecordNameRe = '^case4-([FESA])-(\d{8}-\d{6})-(\d+)\.json$'
$script:C4MaxRecordBytes = 1048576; $script:C4ClockSkewMinutes = 5
$script:C4ProbeProofFields = @('schema', 'probe_exe_sha256', 'probe_cs_sha256', 'sublayer', 'provider', 'filter_key', 'user_sid', 'display_name', 'expected_account', 'checks_failed', 'written_utc')
$script:C4ProofSeams = @('Invoke-C4RealProbeVersion', 'Invoke-C4RealProbeSelfTest')
$script:C4Out = New-Object System.Collections.ArrayList; $script:C4Quiet = $false
$script:C4HasDateKind = (Get-Command ConvertFrom-Json).Parameters.ContainsKey('DateKind')

# ---- small pure helpers ---------------------------------------------------------------------------------------------------------------------------------------
function Write-C4 {
    # Every line a mode prints is also kept in $script:C4Out (the self-test reads it); -SelfTest silences the modes it drives.
    param([string]$Text = '', [string]$Color = 'Gray')
    [void]$script:C4Out.Add($Text)
    if (-not $script:C4Quiet) { Write-Host $Text -ForegroundColor $Color }
}

function ConvertFrom-C4Json {
    # Dates stay text (PowerShell 7.5+), so a field's written form can be checked; older hosts give [datetime], which the readers here also accept.
    param([Parameter(Mandatory)][string]$Text)
    if ($script:C4HasDateKind) { return (ConvertFrom-Json -InputObject $Text -DateKind String -Depth 32) }
    return (ConvertFrom-Json -InputObject $Text -Depth 32)
}

function Get-C4BytesSha {
    param([byte[]]$Bytes)
    $sha = [Security.Cryptography.SHA256]::Create()
    try { return ([BitConverter]::ToString($sha.ComputeHash([byte[]]$Bytes))) -replace '-', '' } finally { $sha.Dispose() }
}

function Get-C4SelfSha { return $script:C4SelfSha }
function Get-C4WrappedSha { return $script:WrappedSha256Used }

function Test-C4HasField {
    # PURE. True when the dotted path exists in a parsed JSON object or a dictionary (a member that is present with the value null counts as present).
    param($Obj, [Parameter(Mandatory)][string]$Path)
    $cur = $Obj
    foreach ($p in $Path.Split('.')) {
        if ($null -eq $cur) { return $false }
        if ($cur -is [System.Collections.IDictionary]) { if (-not $cur.Contains($p)) { return $false }; $cur = $cur[$p] }
        elseif ($cur -is [System.Management.Automation.PSCustomObject]) { if (-not $cur.PSObject.Properties[$p]) { return $false }; $cur = $cur.$p }
        else { return $false }
    }
    return $true
}

function Get-C4Field {
    # PURE. The value at the dotted path, or $null when any part is missing.
    param($Obj, [Parameter(Mandatory)][string]$Path)
    $cur = $Obj
    foreach ($p in $Path.Split('.')) {
        if ($null -eq $cur) { return $null }
        if ($cur -is [System.Collections.IDictionary]) { if (-not $cur.Contains($p)) { return $null }; $cur = $cur[$p] }
        elseif ($cur -is [System.Management.Automation.PSCustomObject]) { if (-not $cur.PSObject.Properties[$p]) { return $null }; $cur = $cur.$p }
        else { return $null }
    }
    if ($cur -is [array]) { return , $cur }
    return $cur
}

function Get-C4FieldNames {
    param($Obj)
    if ($Obj -is [System.Collections.IDictionary]) { return @($Obj.Keys | ForEach-Object { [string]$_ }) }
    if ($Obj -is [System.Management.Automation.PSCustomObject]) { return @($Obj.PSObject.Properties.Name) }
    return @()
}

function Get-C4RcValue {
    # PURE. The status as written by the probe ("0x" and eight hex digits) as a number; $null for anything else.
    param($Text)
    if ($Text -isnot [string] -or $Text -notmatch '^0x[0-9A-Fa-f]{8}$') { return $null }
    return [uint32]::Parse($Text.Substring(2), [Globalization.NumberStyles]::HexNumber)
}

function Get-C4RcClass {
    # PURE. The classes of SPEC part 1 step 9: 0 succeeded; 0x5 or 0x80070005 denied; for a delete 0x80320003 (FWP_E_FILTER_NOT_FOUND) not_found; anything else
    # other, 0x80320028 (FWP_E_OUT_OF_BOUNDS, not an access denial) included.
    param([Parameter(Mandatory)][uint32]$Rc, [ValidateSet('add', 'delete')][string]$Kind = 'add')
    if ($Rc -eq [uint32]0) { return 'succeeded' }
    if ($Rc -eq [uint32]5 -or $Rc -eq [uint32]2147942405) { return 'denied' }
    if ($Kind -eq 'delete' -and $Rc -eq [uint32]2150760451) { return 'not_found' }
    return 'other'
}

function Get-C4RecordName {
    # PURE. The probe's record file name: case4-<cond>-<UTC yyyyMMdd-HHmmss>-<pid>.json.
    param([Parameter(Mandatory)][string]$Cond, [Parameter(Mandatory)][datetimeoffset]$Utc, [Parameter(Mandatory)][long]$ProcessId)
    return ('case4-{0}-{1}-{2}.json' -f $Cond, $Utc.UtcDateTime.ToString('yyyyMMdd-HHmmss'), $ProcessId)
}

function Test-C4Args {
    # PURE. Argument errors (empty = valid): exactly one mode; -WriteProof only with -SelfTest; -ElevationRefused only with -Collect or -Finish, and then one
    # line of printable ASCII of 1 to 300 characters, recorded verbatim, with no '@' and no 'MicrosoftAccount' (the session writes it; it never quotes an account).
    param([Parameter(Mandatory)][hashtable]$Modes, [bool]$WriteProof, [string]$ElevationRefused)
    $e = @()
    $on = @($Modes.Keys | Where-Object { $Modes[$_] })
    if ($on.Count -ne 1) { $e += 'choose exactly one of -SelfTest, -DryRun, -Check, -Prepare, -Collect, -Finish, -PartD' }
    if ($WriteProof -and -not $Modes['SelfTest']) { $e += '-WriteProof applies to -SelfTest only' }
    if ($PSBoundParameters.ContainsKey('ElevationRefused') -and $null -ne $ElevationRefused -and $ElevationRefused -ne '') {
        if (-not ($Modes['Collect'] -or $Modes['Finish'])) { $e += '-ElevationRefused applies to -Collect and -Finish only' }
        if ($ElevationRefused.Length -gt 300 -or $ElevationRefused -match '[^\x20-\x7E]' -or -not $ElevationRefused.Trim()) { $e += '-ElevationRefused must be one line of printable ASCII, 1 to 300 characters' }
        if (($ElevationRefused -match '@') -or ($ElevationRefused -match '(?i)MicrosoftAccount')) { $e += '-ElevationRefused must not carry an account: no ''@'' and no ''MicrosoftAccount''' }
    }
    return @($e)
}

function Test-C4SddlText {
    # PURE. True when `netsh wfp show security` printed a security descriptor with a DACL.
    param([string]$Text)
    return [bool]($Text -match 'D:[A-Z]{0,8}\(')
}

function Compare-C4SdText {
    # PURE. Two `netsh wfp show security` outputs, line by line (blank lines and surrounding space ignored).
    param([string]$Before, [string]$After)
    $n = { param($t) @(([string]$t -split "`r?`n") | ForEach-Object { $_.Trim() } | Where-Object { $_ }) }
    $b = & $n $Before; $a = & $n $After
    $removed = @($b | Where-Object { $a -cnotcontains $_ }); $added = @($a | Where-Object { $b -cnotcontains $_ })
    return [ordered]@{ same = ($removed.Count -eq 0 -and $added.Count -eq 0 -and $b.Count -eq $a.Count); removed = $removed; added = $added }
}

function Find-C4NetshSecurity {
    # Which form `netsh wfp show security` accepts for an object GUID (braces or not) is not documented: each form is tried in turn and EVERY attempt is recorded
    # (command, exit code, text); the first whose output carries a DACL is the answer. $RunNetsh { param([string[]]$Argv) } -> @{ exit; text } is the seam.
    param([Parameter(Mandatory)][string]$Type, [string]$Guid, [Parameter(Mandatory)][scriptblock]$RunNetsh)
    $forms = if ($Guid) { @("guid={$Guid}", "guid=$Guid") } else { @('') }
    $tries = @()
    foreach ($f in $forms) {
        $argv = @('wfp', 'show', 'security', "type=$Type"); if ($f) { $argv += $f }
        $cmd = 'netsh ' + ($argv -join ' ')
        $r = $null
        try { $r = & $RunNetsh $argv } catch { $r = [pscustomobject]@{ exit = -1; text = "error: $($_.Exception.Message)" } }
        $acc = ([int]$r.exit -eq 0) -and (Test-C4SddlText ([string]$r.text))
        $tries += , ([ordered]@{ command = $cmd; exit = [int]$r.exit; text = [string]$r.text; accepted = [bool]$acc })
        if ($acc) { return [ordered]@{ ok = $true; command = $cmd; text = [string]$r.text; tries = $tries } }
    }
    return [ordered]@{ ok = $false; command = $null; text = $null; tries = $tries }
}

function Get-C4SweepSummary {
    # PURE. The direct sweep as it goes into a record (the export text itself is not copied: its hash, size and hit counts are).
    param($Sw)
    if (-not $Sw) { return $null }
    $per = [ordered]@{}; foreach ($id in $Sw.SubLayers.Keys) { $s = $Sw.SubLayers[$id]; $per[$id] = [ordered]@{ filter_keys = @($s.filter_keys); present = $s.present } }
    return [ordered]@{ label = $Sw.Label; at = $Sw.At; clean = [bool]$Sw.Clean; stop = [bool]$Sw.Stop; unreadable = [bool]$Sw.Unreadable; not_clean = @($Sw.NotClean); problems = @($Sw.Problems)
                       sublayers = $per; provider_present = $Sw.ProviderPresent; foreign = @($Sw.Foreign | ForEach-Object { "$($_.Key)@$($_.SubLayer)" })
                       export = [ordered]@{ ok = $Sw.Export.ok; sha256 = $Sw.Export.sha256; bytes = $Sw.Export.bytes; hits = $Sw.Export.hits; error = $Sw.Export.error } }
}

function Get-C4KeyState {
    # $true present, $false absent, $null unreadable: the probe's filter key read by key on our own engine session.
    param($Backend, [string]$Key = $script:C4ProbeKey)
    if (-not $Backend) { return $null }
    try { return ([long]$Backend.Flags('filter', $Key) -ge 0) } catch { return $null }
}

# ---- what -Prepare adds ---------------------------------------------------------------------------------------------------------------------------------------
function Get-C4PrepPlan {
    # PURE. The library's plan descriptor for -Prepare: our provider and S2 (S2 names the provider), in ONE transaction, and no filter and no attempt. The probe's
    # filter is the probe's own to add and delete; the driver never adds a filter.
    return [pscustomobject]@{ Id = 'case4-prepare'; Provider = $true; SubLayer = $script:N5SubLayers.S2; SubLayerUsesProvider = $true; Filters = @(); Attempts = @() }
}

function Get-C4PlanProblems {
    # PURE. Problems with a -Prepare plan beyond the library's own plan gate (empty = it may be added): provider and S2 exactly, S2 naming the provider, no filter.
    param([Parameter(Mandatory)]$Plan)
    $p = @()
    if (-not $Plan.Provider) { $p += 'the plan does not add our provider' }
    if ((ConvertTo-N5Guid $Plan.SubLayer) -ne $script:N5SubLayers.S2) { $p += "the plan's sublayer '$($Plan.SubLayer)' is not S2 (S2 is the only sublayer case 4 adds)" }
    if (-not $Plan.SubLayerUsesProvider) { $p += 'S2 must name our provider' }
    $nf = @($Plan.Filters | Where-Object { $_ }).Count; $na = @($Plan.Attempts | Where-Object { $_ }).Count
    if ($nf) { $p += "the plan carries $nf filter(s): -Prepare adds none" }
    if ($na) { $p += "the plan carries $na attempt(s): -Prepare adds none" }
    return @($p)
}

# ---- the public folder's DACLs (pure) ------------------------------------------------------------------------------------------------------------------------
function Get-C4AclPlanProblems {
    # PURE. Why the account may not be granted anything. Refuse: it does not resolve, is not a user (SID_NAME_USE 1), is a well-known or built-in SID, is not a
    # local account of this machine, or the members of Administrators cannot be read. STOP: it is the operator, a group in his token, or a member of Administrators.
    param([string]$NcoSid, [int]$NcoUse, [string]$NcoDomain, [string]$ComputerName, [string]$OperatorSid, [string[]]$OperatorGroups = @(), [string[]]$AdminMembers = @(), [bool]$AdminsReadable = $true)
    $refuse = @(); $stop = @()
    if (-not $NcoSid) { return [ordered]@{ Refuse = @("the account '$($script:C4Account)' does not resolve"); Stop = @() } }
    $useName = @{ 1 = 'user'; 2 = 'group'; 3 = 'domain'; 4 = 'alias (local group)'; 5 = 'well-known group'; 6 = 'deleted account'; 7 = 'invalid SID'; 8 = 'unknown SID'; 9 = 'computer'; 10 = 'label' }
    if ($NcoUse -ne 1) { $refuse += ("'{0}' resolves to a {1} (SID_NAME_USE {2}), not a user" -f $script:C4Account, $(if ($useName.ContainsKey($NcoUse)) { $useName[$NcoUse] } else { 'other' }), $NcoUse) }
    if ($NcoSid -match '^S-1-5-32-' -or $NcoSid -in @('S-1-1-0', 'S-1-5-11', 'S-1-5-18', 'S-1-5-19', 'S-1-5-20', 'S-1-5-4', 'S-1-2-0')) { $refuse += "SID $NcoSid is a well-known or built-in SID" }
    if ($ComputerName -and $NcoDomain -and $NcoDomain -ine $ComputerName) { $refuse += "'$($script:C4Account)' is in '$NcoDomain', not a local account of this machine" }
    if ($OperatorSid -and $NcoSid -eq $OperatorSid) { $stop += "'$($script:C4Account)' is the operator's own SID" }
    if (@($OperatorGroups) -contains $NcoSid) { $stop += "'$($script:C4Account)' SID is a group in the operator's token" }
    if (-not $AdminsReadable) { $refuse += 'the members of Administrators could not be read' }
    elseif (@($AdminMembers) -contains $NcoSid) { $stop += "'$($script:C4Account)' is a member of Administrators" }
    foreach ($m in @(Test-CoderSidSafe $NcoSid $OperatorSid @($OperatorGroups))) { if ($m -notmatch 'OPERATOR SID|GROUP in the operator') { $refuse += $m } }
    return [ordered]@{ Refuse = @($refuse); Stop = @($stop) }
}

function ConvertTo-C4Sddl {
    # PURE (an in-memory security object; nothing is read from or written to a file). A PROTECTED DACL (nothing inherited) with exactly these rows, each
    # inherited by subfolders and files; with -OwnerSid the owner too (an owner may rewrite the DACL, so who owns a folder is part of who may write it).
    param([Parameter(Mandatory)]$Rows, [string]$OwnerSid)
    $sec = [Security.AccessControl.DirectorySecurity]::new()
    if ($OwnerSid) { $sec.SetOwner([Security.Principal.SecurityIdentifier]::new($OwnerSid)) }
    $sec.SetAccessRuleProtection($true, $false)
    foreach ($r in @($Rows)) {
        $rule = [Security.AccessControl.FileSystemAccessRule]::new([Security.Principal.SecurityIdentifier]::new([string]$r.sid), [Security.AccessControl.FileSystemRights]([string]$r.rights),
                [Security.AccessControl.InheritanceFlags]'ContainerInherit, ObjectInherit', [Security.AccessControl.PropagationFlags]::None, [Security.AccessControl.AccessControlType]::Allow)
        $sec.AddAccessRule($rule)
    }
    $sections = if ($OwnerSid) { [Security.AccessControl.AccessControlSections]'Owner, Access' } else { [Security.AccessControl.AccessControlSections]::Access }
    return $sec.GetSecurityDescriptorSddlForm($sections)
}

function Get-C4AclPlan {
    # PURE: the public folder's three DACLs as a function of the account's SID (and how it resolved), the operator's SID and groups, and the members of Administrators.
    #   root and bin\  SYSTEM full control, Administrators full control, Users read and execute
    #   drop\          SYSTEM full control, Administrators full control, the account Modify, the operator Modify (for the S control)
    # Every DACL is protected and every folder is OWNED by Administrators: a folder an elevated process creates is otherwise owned by the operator's user SID, and an owner
    # may rewrite the DACL from a non-elevated process (then replace the exe that condition A runs elevated). No plan (Ok false) when Get-C4AclPlanProblems refuses or
    # stops; $ProblemsFn is replaceable so a test can switch the refusal off.
    param([string]$NcoSid, [int]$NcoUse, [string]$NcoDomain, [string]$ComputerName, [string]$OperatorSid, [string[]]$OperatorGroups = @(), [string[]]$AdminMembers = @(), [bool]$AdminsReadable = $true,
          [scriptblock]$ProblemsFn = { param($i) Get-C4AclPlanProblems -NcoSid $i.NcoSid -NcoUse $i.NcoUse -NcoDomain $i.NcoDomain -ComputerName $i.ComputerName -OperatorSid $i.OperatorSid -OperatorGroups $i.OperatorGroups -AdminMembers $i.AdminMembers -AdminsReadable $i.AdminsReadable })
    $in = [ordered]@{ NcoSid = $NcoSid; NcoUse = $NcoUse; NcoDomain = $NcoDomain; ComputerName = $ComputerName; OperatorSid = $OperatorSid; OperatorGroups = @($OperatorGroups); AdminMembers = @($AdminMembers); AdminsReadable = $AdminsReadable }
    $pr = & $ProblemsFn $in
    $plan = [ordered]@{ Ok = $false; Refuse = @($pr.Refuse); Stop = @($pr.Stop); Rows = $null; Sddl = $null; NcoSid = $NcoSid; OperatorSid = $OperatorSid }
    if ($plan.Refuse.Count -or $plan.Stop.Count) { return $plan }
    $base = @([ordered]@{ sid = $script:C4SystemSid; rights = 'FullControl' }, [ordered]@{ sid = $script:C4AdminsSid; rights = 'FullControl' })
    $users = [ordered]@{ sid = $script:C4UsersSid; rights = 'ReadAndExecute' }
    $rows = [ordered]@{
        root = @($base + @($users))
        bin  = @($base + @($users))
        drop = @($base + @([ordered]@{ sid = $NcoSid; rights = 'Modify' }, [ordered]@{ sid = $OperatorSid; rights = 'Modify' }))
    }
    $plan.Rows = $rows
    $plan.Sddl = [ordered]@{ root = (ConvertTo-C4Sddl $rows.root -OwnerSid $script:C4AdminsSid); bin = (ConvertTo-C4Sddl $rows.bin -OwnerSid $script:C4AdminsSid); drop = (ConvertTo-C4Sddl $rows.drop -OwnerSid $script:C4AdminsSid) }
    $plan.Ok = $true
    return $plan
}

function Get-C4DropSddlAfterRemoval {
    # PURE. drop\'s DACL once the account's and the operator's ACEs are removed (-Finish, before the folder is deleted): SYSTEM and Administrators only.
    return (ConvertTo-C4Sddl @([ordered]@{ sid = $script:C4SystemSid; rights = 'FullControl' }, [ordered]@{ sid = $script:C4AdminsSid; rights = 'FullControl' }))
}

function Get-C4AclRules {
    # PURE. The owner and the DACL of an SDDL string: the owner SID ($null when the text has none), the rules as sorted lines
    # (sid|rights|type|inheritance|propagation|explicit-or-inherited), whether the DACL is protected, and its SIDs.
    param([Parameter(Mandatory)][string]$Sddl)
    $sec = [Security.AccessControl.DirectorySecurity]::new()
    $sec.SetSecurityDescriptorSddlForm($Sddl, [Security.AccessControl.AccessControlSections]'Owner, Access')
    $own = $sec.GetOwner([Security.Principal.SecurityIdentifier])
    $rs = @($sec.GetAccessRules($true, $true, [Security.Principal.SecurityIdentifier]))
    $lines = @($rs | ForEach-Object { '{0}|{1}|{2}|{3}|{4}|{5}' -f $_.IdentityReference.Value, [int]$_.FileSystemRights, $_.AccessControlType, [int]$_.InheritanceFlags, [int]$_.PropagationFlags, $(if ($_.IsInherited) { 'inherited' } else { 'explicit' }) } | Sort-Object)
    return [ordered]@{ Owner = $(if ($own) { $own.Value } else { $null }); Protected = [bool]$sec.AreAccessRulesProtected; Rules = $lines; Sids = @($rs | ForEach-Object { $_.IdentityReference.Value } | Select-Object -Unique) }
}

function Compare-C4Acl {
    # PURE. The DACL read back against the planned one: equal only when protected the same way, the rule sets are identical, and (when the plan names an owner) the
    # owner is the planned one.
    param([string]$Expected, [string]$Actual)
    try { $e = Get-C4AclRules -Sddl $Expected; $a = Get-C4AclRules -Sddl $Actual } catch { return [ordered]@{ Equal = $false; Missing = @(); Extra = @(); Reason = "unreadable SDDL: $($_.Exception.Message)" } }
    $missing = @($e.Rules | Where-Object { $a.Rules -cnotcontains $_ }); $extra = @($a.Rules | Where-Object { $e.Rules -cnotcontains $_ })
    $ownOk = (-not $e.Owner) -or ($a.Owner -eq $e.Owner)
    $eq = ($e.Protected -eq $a.Protected) -and $missing.Count -eq 0 -and $extra.Count -eq 0 -and $ownOk
    $why = if ($eq) { 'equal' } else { "owner: planned $($e.Owner), read $($a.Owner); protected: planned $($e.Protected), read $($a.Protected); missing: $($missing -join ', '); extra: $($extra -join ', ')" }
    return [ordered]@{ Equal = $eq; Missing = $missing; Extra = $extra; Reason = $why }
}

function Test-C4AceRemoval {
    # PURE. drop\'s DACL as read back after the removal: exactly SYSTEM and Administrators as planned, and none of $GoneSids anywhere in it.
    param([string]$Expected, [string]$Actual, [string[]]$GoneSids = @())
    $c = Compare-C4Acl -Expected $Expected -Actual $Actual
    if (-not $c.Equal) { return $false }
    $sids = @((Get-C4AclRules -Sddl $Actual).Sids)
    foreach ($s in @($GoneSids | Where-Object { $_ })) { if ($sids -contains $s) { return $false } }
    return $true
}

# ---- the probe proof (pure) ----------------------------------------------------------------------------------------------------------------------------------
function New-C4ProbeProof {
    # PURE. The arming file the probe reads (`--live`), schema nep5-case4-probe-proof-v1: exactly the eleven fields of SPEC part 1 step 2, GUIDs and hashes lower case.
    param([Parameter(Mandatory)][string]$ExeSha, [Parameter(Mandatory)][string]$CsSha, [datetimeoffset]$Now = [datetimeoffset]::Now)
    return [ordered]@{
        schema = $script:C4ProbeProofSchema; probe_exe_sha256 = $ExeSha.ToLowerInvariant(); probe_cs_sha256 = $CsSha.ToLowerInvariant()
        sublayer = $script:N5SubLayers.S2; provider = $script:N5ProviderKey; filter_key = $script:C4ProbeKey; user_sid = $script:N5StaleSid
        display_name = $script:C4DisplayName; expected_account = $script:C4Account; checks_failed = 0; written_utc = $Now.UtcDateTime.ToString("yyyy-MM-dd'T'HH:mm:ss'Z'")
    }
}

function Test-C4ProbeProof {
    # PURE. The probe's own arming rules, applied by the driver to the proof it writes and to the copy it reads back from bin\: each problem names its field.
    param([Parameter(Mandatory)]$Proof, [Parameter(Mandatory)][string]$ExeSha, [Parameter(Mandatory)][string]$CsSha, [datetimeoffset]$Now = [datetimeoffset]::Now)
    $p = @()
    foreach ($n in $script:C4ProbeProofFields) { if (-not (Test-C4HasField $Proof $n)) { $p += "${n}: missing" } }
    foreach ($n in @(Get-C4FieldNames $Proof)) { if ($script:C4ProbeProofFields -notcontains $n) { $p += "${n}: unexpected field" } }
    $v = { param($n) Get-C4Field $Proof $n }
    $eqText = { param($n, $want) $x = & $v $n; if (($x -isnot [string]) -or ($x -cne $want)) { "${n}: not '$want'" } }
    $p += @(& $eqText 'schema' $script:C4ProbeProofSchema)
    foreach ($h in @(@('probe_exe_sha256', $ExeSha), @('probe_cs_sha256', $CsSha))) {
        $x = & $v $h[0]
        if (($x -isnot [string]) -or ($x -cnotmatch '^[0-9a-f]{64}$')) { $p += "$($h[0]): not a lower-case SHA-256" }
        elseif ($x -ne ([string]$h[1]).ToLowerInvariant()) { $p += "$($h[0]): not the hash the driver proof verified" }
    }
    $p += @(& $eqText 'sublayer' $script:N5SubLayers.S2)
    $p += @(& $eqText 'provider' $script:N5ProviderKey)
    $p += @(& $eqText 'filter_key' $script:C4ProbeKey)
    $p += @(& $eqText 'user_sid' $script:N5StaleSid)
    $dn = & $v 'display_name'
    if (($dn -isnot [string]) -or -not $dn.Trim() -or $dn.Length -gt 120) { $p += 'display_name: not a non-empty string of at most 120 characters' }
    $p += @(& $eqText 'expected_account' $script:C4Account)
    $cf = & $v 'checks_failed'
    if (-not (($cf -is [int]) -or ($cf -is [long])) -or $cf -ne 0) { $p += 'checks_failed: not the integer 0' }
    $w = & $v 'written_utc'
    if (-not (Test-IsoTimestamp $w)) { $p += 'written_utc: not an ISO 8601 time with a zone' }
    else {
        $age = ($Now - (ConvertTo-DateTimeOffset $w)).TotalMinutes
        if ($age -gt 24 * 60) { $p += ('written_utc: {0:N0} min old (limit 24 h)' -f $age) }
        if ($age -lt -5) { $p += 'written_utc: more than 5 min in the future' }
    }
    return @($p | Where-Object { $_ })
}

# ---- the probe's records (pure) ------------------------------------------------------------------------------------------------------------------------------
function Test-C4Record {
    # PURE (except that it adds the pid+stamp of every named record to $Seen). Why one drop record is invalid, each reason naming its field (empty = valid). The record is
    # the probe's (schema nep5-case4-record-v1; probe/README.md). SPEC part 2 -Collect's checks, plus: it came from `run` of a NON-toggle build; its source hash and its
    # proof are the ones -Prepare placed; its own file name, stamp and clocks agree; the account it resolved is the one -Prepare resolved; S and A are the operator's own
    # token; and every class, overall, residue and exit agree with the codes. An engine-open failure (engine.open.opened false) carries no add or delete status.
    param($Record, [string]$FileName, [string]$ExeSha, [string]$CsSha, [string]$ProofSha, [string]$NcoSid, [string]$OperatorSid, [datetimeoffset]$WindowStart, [datetimeoffset]$WindowEnd, [hashtable]$Seen = @{})
    if (-not (($Record -is [System.Management.Automation.PSCustomObject]) -or ($Record -is [System.Collections.IDictionary]))) { return @('record: not a JSON object') }
    $r = New-Object System.Collections.ArrayList
    $add = { param($t) [void]$r.Add($t) }
    $g = { param($n) Get-C4Field $Record $n }
    $isInt = { param($v) ($v -is [int]) -or ($v -is [long]) }
    $schema = & $g 'schema'
    if (($schema -isnot [string]) -or ($schema -cne $script:C4RecordSchema)) { & $add "schema: not '$($script:C4RecordSchema)'" }
    if ((& $g 'subcommand') -cne 'run') { & $add "subcommand: not 'run'" }
    $tb = & $g 'toggle_build'
    if (($tb -isnot [bool]) -or $tb) { & $add 'toggle_build: not false (a toggle build''s record is never evidence)' }
    $cond = & $g 'cond'
    $condOk = ($cond -is [string]) -and ($script:C4Conds -ccontains $cond)
    if (-not $condOk) { & $add "cond: '$cond' is not one of F, E, S, A" }
    $exe = & $g 'probe_exe_sha256'
    if (($exe -isnot [string]) -or ($exe -notmatch '^[0-9a-fA-F]{64}$')) { & $add 'probe_exe_sha256: not a SHA-256' }
    elseif (-not $ExeSha -or ($exe -ine $ExeSha)) { & $add 'probe_exe_sha256: not the exe -Prepare placed in bin' }
    $cs = & $g 'probe_cs_sha256'
    if (($cs -isnot [string]) -or ($cs -notmatch '^[0-9a-fA-F]{64}$')) { & $add 'probe_cs_sha256: not a SHA-256' }
    elseif ($CsSha -and ($cs -ine $CsSha)) { & $add 'probe_cs_sha256: not the source the prepared exe embeds' }
    $ps = & $g 'proof.sha256'
    if ($ProofSha -and (($ps -isnot [string]) -or ($ps -ine $ProofSha))) { & $add 'proof.sha256: not the probe proof -Prepare wrote' }
    $procId = & $g 'pid'
    $pidOk = (& $isInt $procId) -and ($procId -gt 0)
    if (-not $pidOk) { & $add 'pid: not a positive integer' }
    $user = & $g 'user_sid'
    $userOk = ($user -is [string]) -and ($user -match '^S-1-\d+(-\d+)+$')
    if (-not $userOk) { & $add 'user_sid: not a SID' }
    $exp = & $g 'is_expected_account'
    if ($exp -isnot [bool]) { & $add 'is_expected_account: not true or false' }
    if ($condOk -and $userOk -and ($exp -is [bool])) {
        if ($cond -in @('F', 'E')) {
            if (-not $exp) { & $add "is_expected_account: false for $cond (the run was not made as $($script:C4Account))" }
            if (-not $NcoSid -or $user -ne $NcoSid) { & $add "user_sid: $cond must run as $($script:C4Account) ($NcoSid), not $user" }
        } else {
            if ($exp) { & $add "is_expected_account: true for $cond (S and A are the operator's own token)" }
            if (-not $OperatorSid -or $user -ne $OperatorSid) { & $add "user_sid: $cond must run as the operator ($OperatorSid), not $user" }
        }
    }
    foreach ($m in @(Get-C4TokenStateProblems -Record $Record)) { & $add $m }
    $eas = & $g 'expected_account.sid'
    if ($NcoSid -and ($null -ne $eas) -and ([string]$eas -ne $NcoSid)) { & $add "expected_account.sid: the probe resolved $($script:C4Account) to $eas, -Prepare to $NcoSid" }
    $t = @{}
    foreach ($k in @('clock_start.utc', 'clock_end.utc')) {
        $v = & $g $k
        if (-not (Test-IsoTimestamp $v)) { & $add "${k}: not an ISO 8601 time with a zone"; continue }
        $t[$k] = ConvertTo-DateTimeOffset $v
        if ($t[$k] -lt $WindowStart -or $t[$k] -gt $WindowEnd) { & $add ("{0}: {1} is outside the prepare-to-now window ({2} .. {3})" -f $k, $t[$k].ToString('o'), $WindowStart.ToString('o'), $WindowEnd.ToString('o')) }
    }
    if ($t['clock_start.utc'] -and $t['clock_end.utc'] -and $t['clock_end.utc'] -lt $t['clock_start.utc']) { & $add 'clock_end.utc: before clock_start.utc' }
    $stamp = & $g 'stamp_utc'; $stampOk = $false
    if (($stamp -isnot [string]) -or ($stamp -notmatch '^\d{8}-\d{6}$')) { & $add 'stamp_utc: not yyyyMMdd-HHmmss' }
    else {
        $st = [datetime]::MinValue
        if (-not [datetime]::TryParseExact($stamp, 'yyyyMMdd-HHmmss', [Globalization.CultureInfo]::InvariantCulture, [Globalization.DateTimeStyles]'AssumeUniversal, AdjustToUniversal', [ref]$st)) { & $add 'stamp_utc: not a time' }
        else {
            $stampOk = $true
            if ($t['clock_start.utc']) { $d = [Math]::Abs(([datetimeoffset]::new($st, [timespan]::Zero) - $t['clock_start.utc']).TotalSeconds); if ($d -gt 2) { & $add ('stamp_utc: {0:N0} s from clock_start.utc' -f $d) } }
        }
    }
    $rfn = & $g 'record_file_name'
    if (($rfn -isnot [string]) -or ($rfn -cne $FileName)) { & $add "record_file_name: '$rfn' is not the file's own name" }
    $m = [regex]::Match([string]$FileName, $script:C4RecordNameRe)
    if (-not $m.Success) { & $add 'file name: not case4-<cond>-<yyyyMMdd-HHmmss>-<pid>.json' }
    else {
        if ($condOk -and ($m.Groups[1].Value -cne $cond)) { & $add "file name: its cond '$($m.Groups[1].Value)' is not the record's" }
        if ($pidOk -and ([long]$m.Groups[3].Value -ne [long]$procId)) { & $add "file name: its pid $($m.Groups[3].Value) is not the record's" }
        if ($stampOk -and ($m.Groups[2].Value -cne $stamp)) { & $add "file name: its stamp $($m.Groups[2].Value) is not the record's stamp_utc" }
        $key = "$($m.Groups[3].Value)|$($m.Groups[2].Value)"
        if ($Seen.ContainsKey($key)) { & $add "pid+stamp: duplicate of $($Seen[$key])" } else { $Seen[$key] = $FileName }
    }
    $opened = & $g 'engine.open.opened'
    $ov = & $g 'overall'; $ex = & $g 'exit'; $res = & $g 'residue'
    # The probe refuses (exit 12, wrong_principal, before the engine) F or E not made as the account and S or A made as the account.
    $probeShouldRefuse = $condOk -and ($exp -is [bool]) -and ((($cond -in @('F', 'E')) -and -not $exp) -or (($cond -in @('S', 'A')) -and $exp))
    if ($ov -ceq 'wrong_principal') {
        & $add ("principal: the probe refused {0} as {1} before the engine (wrong_principal): never counted, never a write verdict" -f $cond, $user)
        if (-not $probeShouldRefuse) { & $add "overall: 'wrong_principal' although is_expected_account $exp fits cond $cond" }
        if (-not (& $isInt $ex) -or $ex -ne 12) { & $add "exit: $ex (expected 12 for wrong_principal)" }
        if ($opened -eq $true) { & $add 'engine.open.opened: true on a wrong_principal record' }
        foreach ($k in @('add', 'delete')) {
            if ((& $g "$k.attempted") -eq $true) { & $add "${k}.attempted: true on a wrong_principal record" }
            if (Test-C4HasField $Record "$k.rc") { & $add "${k}.rc: present on a wrong_principal record" }
        }
        if (($null -ne $res) -and ($res -cne 'none_added')) { & $add "residue: '$res' (expected 'none_added' for wrong_principal)" }
        if ($null -ne (& $g 'sequence_complete')) { & $add "sequence_complete: '$(& $g 'sequence_complete')' on a wrong_principal record (expected null: no engine call was made)" }
        if ((& $g 'operator_action') -cne $script:C4ProbeStopLineWrongPrincipal) { & $add "operator_action: '$(& $g 'operator_action')' on a wrong_principal record (expected the probe's wrong-principal STOP line)" }
        return @($r)
    }
    if ($probeShouldRefuse) { & $add "overall: '$ov' although the probe should have refused cond $cond for is_expected_account $exp (wrong_principal, exit 12)" }
    # The engine section follows the probe's own rules (NcoProbe.cs Outcome): an open that threw is incomplete (11); an open that returned a status other than 0
    # is open_failed (7); once open, a filter still present after the delete is filter_left_behind (8) even if a later call threw; any call that threw (rc
    # null, class other, its text in error), a read-back or a close that threw, makes the sequence incomplete (11); else ok (0). Before incomplete: an add
    # that returned 0 or threw, a delete that did not return 0 and a delete read-back that is not false is filter_possibly_left_behind (8, residue unknown).
    # The STOP line is carried on exit 8, and on exit 11 once the engine was opened; never otherwise.
    $sc = & $g 'sequence_complete'; $oa = & $g 'operator_action'
    $isText = { param($v) ($v -is [string]) -and $v.Trim() }
    $nullOrText = { param($v) ($null -eq $v) -or (& $isText $v) }
    if ($opened -isnot [bool]) { & $add 'engine.open.opened: not true or false' }
    elseif (-not $opened) {
        foreach ($k in @('add', 'delete')) {
            if ((& $g "$k.attempted") -ne $false) { & $add "${k}.attempted: not false when the engine was not opened" }
            if (Test-C4HasField $Record "$k.rc") { & $add "${k}.rc: present when the engine was not opened" }
        }
        if ($res -cne 'none_added') { & $add "residue: '$res' (expected 'none_added' when the engine was not opened)" }
        $oerr = & $g 'engine.open.error'; $orcText = & $g 'engine.open.rc'
        if (& $isText $oerr) {
            if ($null -ne $orcText) { & $add "engine.open.rc: '$orcText' although the open threw (expected null)" }
            if ($ov -cne 'incomplete') { & $add "overall: '$ov' (expected 'incomplete' for an open that threw)" }
            if (-not (& $isInt $ex) -or $ex -ne 11) { & $add "exit: $ex (expected 11 for an open that threw)" }
            if (($sc -isnot [bool]) -or $sc) { & $add "sequence_complete: '$sc' (expected false for an open that threw)" }
        } else {
            if ($null -ne $oerr) { & $add 'engine.open.error: not null or a description' }
            $orc = Get-C4RcValue $orcText
            if ($null -eq $orc) { & $add 'engine.open.rc: not 0x and eight hex digits' } elseif ($orc -eq [uint32]0) { & $add 'engine.open.rc: 0 on an open failure' }
            if ($ov -cne 'open_failed') { & $add "overall: '$ov' (expected 'open_failed' for an engine-open failure)" }
            if (-not (& $isInt $ex) -or $ex -ne 7) { & $add "exit: $ex (expected 7 for an engine-open failure)" }
            if (($sc -isnot [bool]) -or -not $sc) { & $add "sequence_complete: '$sc' (expected true for an open that returned a status)" }
        }
        if ($null -ne $oa) { & $add "operator_action: '$oa' (expected null: the engine was not opened, so nothing can have been added)" }
    } else {
        $allDone = $true
        foreach ($k in @('add', 'delete')) {
            if ((& $g "$k.attempted") -ne $true) { & $add "${k}.attempted: not true once the engine was open" }
            $rcText = & $g "$k.rc"; $rc = Get-C4RcValue $rcText; $err = & $g "$k.error"
            $cls = & $g "$k.class"
            $allowed = if ($k -eq 'add') { @('succeeded', 'denied', 'other') } else { @('succeeded', 'denied', 'not_found', 'other') }
            if (-not (& $nullOrText $err)) { & $add "${k}.error: not null or a description" } elseif ($null -ne $err) { $allDone = $false }
            if ($null -eq $rcText) {
                $allDone = $false
                if ($cls -cne 'other') { & $add "${k}.class: '$cls' (expected 'other': ${k}.rc is null, the call threw)" }
                if (-not (& $isText $err)) { & $add "${k}.error: no description although ${k}.rc is null (the call threw)" }
            } else {
                if ($null -eq $rc) { & $add "${k}.rc: not 0x and eight hex digits, or null" }
                if (($cls -isnot [string]) -or ($allowed -cnotcontains $cls)) { & $add "${k}.class: '$cls' is not one of $($allowed -join ', ')" }
                elseif (($null -ne $rc) -and ($cls -cne (Get-C4RcClass -Rc $rc -Kind $k))) { & $add "${k}.class: '$cls' does not match ${k}.rc $rcText" }
            }
            $grc = & $g "$k.get_rc"
            if ($null -eq $grc) { $allDone = $false } elseif ($null -eq (Get-C4RcValue $grc)) { & $add "${k}.get_rc: not 0x and eight hex digits, or null" }
            $pa = & $g "$k.present_after"
            if (-not (($pa -is [bool]) -or ($pa -ceq 'unreadable') -or ($pa -ceq 'not_read'))) { & $add "${k}.present_after: not true, false, 'unreadable' or 'not_read'" }
        }
        $crc = & $g 'engine.close_rc'; $cerr = & $g 'engine.close_error'
        if (-not (& $nullOrText $cerr)) { & $add 'engine.close_error: not null or a description' } elseif ($null -ne $cerr) { $allDone = $false }
        if ($null -eq $crc) { $allDone = $false; if (-not (& $isText $cerr)) { & $add 'engine.close_error: no description although engine.close_rc is null (the close threw)' } }
        elseif ($null -eq (Get-C4RcValue $crc)) { & $add 'engine.close_rc: not 0x and eight hex digits, or null' }
        if ($sc -isnot [bool]) { & $add 'sequence_complete: not true or false once the engine was open' }
        elseif ($sc -ne $allDone) { & $add "sequence_complete: $sc, but the statuses and errors say $allDone" }
        $dp = & $g 'delete.present_after'
        $left = ($dp -is [bool]) -and $dp
        $addRcT = & $g 'add.rc'; $addRcV = Get-C4RcValue $addRcT; $delRcV = Get-C4RcValue (& $g 'delete.rc')
        $addedMaybe = ($null -eq $addRcT) -or (($null -ne $addRcV) -and ($addRcV -eq [uint32]0))
        $deletedOk = ($null -ne $delRcV) -and ($delRcV -eq [uint32]0)
        $possibly = (-not $left) -and $addedMaybe -and (-not $deletedOk) -and -not (($dp -is [bool]) -and -not $dp)
        $wantOv = if ($left) { 'filter_left_behind' } elseif ($possibly) { 'filter_possibly_left_behind' } elseif (-not $allDone) { 'incomplete' } else { 'ok' }
        if ($ov -cne $wantOv) { & $add "overall: '$ov' (expected '$wantOv' for add.rc $addRcT, delete.rc $(& $g 'delete.rc'), delete.present_after $dp and a sequence that $(if ($allDone) { 'completed' } else { 'did not complete' }))" }
        $wantEx = if ($left -or $possibly) { 8 } elseif (-not $allDone) { 11 } else { 0 }
        if (-not (& $isInt $ex) -or $ex -ne $wantEx) { & $add "exit: $ex (expected $wantEx)" }
        $wantRes = if ($left) { 'present' } elseif ($dp -is [bool]) { 'absent' } else { 'unknown' }
        if ($res -cne $wantRes) { & $add "residue: '$res' (expected '$wantRes' for delete.present_after $dp)" }
        if ($wantEx -in @(8, 11)) { if (($oa -isnot [string]) -or ($oa -cne $script:C4ProbeStopLine)) { & $add "operator_action: '$oa' (expected the probe's STOP line on exit $wantEx)" } }
        elseif ($null -ne $oa) { & $add "operator_action: '$oa' (expected null on exit $wantEx)" }
    }
    return @($r)
}

$script:C4TokenState = [ordered]@{
    F = [ordered]@{ elevation = @(3, 1); group = 'nco'; text = 'filtered token (elevation type 3) or an unsplit one (type 1) holding S-1-5-32-556' }
    E = [ordered]@{ elevation = @(2, 1); group = 'nco-enabled'; text = 'full token (elevation type 2) or an unsplit one (type 1) holding S-1-5-32-556 ENABLED (not deny-only)' }
    S = [ordered]@{ elevation = 3; group = 'admins-deny-only'; text = 'filtered token (elevation type 3) with BUILTIN\Administrators present as deny-only' }
    A = [ordered]@{ elevation = 2; group = 'admins-enabled'; text = 'full token (elevation type 2) with BUILTIN\Administrators present and enabled' }
}

function Get-C4TokenStateProblems {
    # PURE. Whether the record's token is the token its condition is defined by ($script:C4TokenState): F filtered (type 3) or unsplit (type 1; "membership
    # gives no split token" is a finding, and the row records which) with S-1-5-32-556, E full (type 2) or unsplit (type 1: a batch logon, the Task
    # Scheduler route of RUN_SHEET.md step 4b, is never split) with S-1-5-32-556 ENABLED (the question E answers is the group's effect; a deny-only
    # group under either type is not E), S filtered with Administrators deny-only, A full with Administrators enabled. F and E also require BUILTIN\Administrators absent or deny-only: a
    # token with Administrators enabled answers "can an administrator add a filter", not the group question (review round 4, R4-2). Each problem starts "token:"; a record with one is invalid by token state,
    # listed and never counted (one line typed into the wrong console must not become a counted answer). Empty for an unknown cond (cond is checked elsewhere).
    param($Record)
    $cond = Get-C4Field $Record 'cond'
    if (($cond -isnot [string]) -or -not $script:C4TokenState.Contains($cond)) { return @() }
    $want = $script:C4TokenState[$cond]; $p = @()
    $ev = Get-C4Field $Record 'elevation_type.value'
    if (-not (($ev -is [int]) -or ($ev -is [long])) -or (@($want.elevation) -notcontains $ev)) { $p += ("token: {0} needs a {1}; elevation_type.value is {2}" -f $cond, $want.text, $(if ($null -eq $ev) { 'not readable' } else { $ev })) }
    $isTrue = { param($v) ($v -is [bool]) -and $v }
    switch ($want.group) {
        'nco' {
            $np = Get-C4Field $Record 'nco_group.present'
            if (-not (& $isTrue $np)) { $p += ("token: {0} needs a {1}; nco_group.present is {2}" -f $cond, $want.text, $np) }
            if (Test-C4AdminsEnabled -Record $Record) { $p += ("token: {0} needs a {1} and BUILTIN\Administrators absent or deny-only; administrators is present and enabled (an administrator's token answers a different question)" -f $cond, $want.text) }
        }
        'nco-enabled' {
            if (-not (Test-C4NcoEnabled -Record $Record)) { $p += ("token: {0} needs a {1}; nco_group.present is {2}, enabled {3}, use_for_deny_only {4}" -f $cond, $want.text, (Get-C4Field $Record 'nco_group.present'), (Get-C4Field $Record 'nco_group.enabled'), (Get-C4Field $Record 'nco_group.use_for_deny_only')) }
            if (Test-C4AdminsEnabled -Record $Record) { $p += ("token: {0} needs a {1} and BUILTIN\Administrators absent or deny-only; administrators is present and enabled (an administrator's token answers a different question)" -f $cond, $want.text) }
        }
        'admins-deny-only' {
            $ap = Get-C4Field $Record 'administrators.present'; $dn = Get-C4Field $Record 'administrators.use_for_deny_only'
            if (-not (& $isTrue $ap) -or -not (& $isTrue $dn)) { $p += ("token: {0} needs a {1}; administrators.present is {2}, use_for_deny_only {3}" -f $cond, $want.text, $ap, $dn) }
        }
        'admins-enabled' {
            $ap = Get-C4Field $Record 'administrators.present'; $en = Get-C4Field $Record 'administrators.enabled'; $dn = Get-C4Field $Record 'administrators.use_for_deny_only'
            if (-not (& $isTrue $ap) -or -not (& $isTrue $en) -or (& $isTrue $dn)) { $p += ("token: {0} needs a {1}; administrators.present is {2}, enabled {3}, use_for_deny_only {4}" -f $cond, $want.text, $ap, $en, $dn) }
        }
    }
    return @($p)
}

function Get-C4InvalidKind {
    # PURE. The class of an invalid record from its reasons: by-principal (the probe refused the principal, or the principal is wrong), by-token-state (the right
    # principal under the wrong token), invalid (anything else). A record whose principal is wrong is reported by principal first.
    param([string[]]$Reasons)
    if (@($Reasons | Where-Object { $_ -like 'principal:*' -or $_ -like 'user_sid:*' -or $_ -like 'is_expected_account:*' }).Count) { return 'by-principal' }
    if (@($Reasons | Where-Object { $_ -like 'token:*' }).Count) { return 'by-token-state' }
    return 'invalid'
}

function Test-C4AdminsEnabled {
    # PURE. True when the record's token holds S-1-5-32-544 present AND enabled (a token that could add a filter as an administrator, whatever S-1-5-32-556 says).
    param($Record)
    $t = { param($v) ($v -is [bool]) -and $v }
    return ((& $t (Get-C4Field $Record 'administrators.present')) -and (& $t (Get-C4Field $Record 'administrators.enabled')))
}

function Test-C4NcoEnabled {
    # PURE. True when the record's token holds S-1-5-32-556 present AND enabled AND not use-for-deny-only (all three read as booleans).
    param($Record)
    $t = { param($v) ($v -is [bool]) -and $v }
    $dn = Get-C4Field $Record 'nco_group.use_for_deny_only'
    return ((& $t (Get-C4Field $Record 'nco_group.present')) -and (& $t (Get-C4Field $Record 'nco_group.enabled')) -and ($dn -is [bool]) -and -not $dn)
}

function Test-C4ETokenShown {
    # PURE. Whether an E record shows the token condition E is about: the account's elevated token (elevation_type 2), or an unsplit token (type 1) with
    # S-1-5-32-556 enabled (the batch-logon route). Judged on the token alone, whatever happened after.
    param($Record)
    $ev = Get-C4Field $Record 'elevation_type.value'
    if (-not (($ev -is [int]) -or ($ev -is [long]))) { return $false }
    if ($ev -eq 2) { return $true }
    return (($ev -eq 1) -and (Test-C4NcoEnabled -Record $Record))
}

function Get-C4ElevationRefused {
    # PURE. The E result `elevation_refused`: Windows refused to elevate the account at condition E. It rests on the note given with -ElevationRefused and is
    # judged on the TOKEN: counted ONLY when no E file in drop\, valid or not, shows the token E is about (Test-C4ETokenShown: elevation_type 2, or type 1 with
    # S-1-5-32-556 enabled), whatever happened after (an engine open that failed or threw still proves the token). An E line run under the account's unelevated
    # token (type 3, invalid by token state) does not contradict it, and neither does another principal's record.
    param([string]$Note, [string[]]$EElevated = @())
    if (-not $Note) { return [ordered]@{ given = $false; counted = $false; note = $null; contradicted_by = @(); reason = 'no note given' } }
    $c = @($EElevated | Where-Object { $_ })
    return [ordered]@{ given = $true; counted = ($c.Count -eq 0); note = $Note; contradicted_by = $c
                       reason = $(if ($c.Count) { "not counted: $($c.Count) E record(s) show the token E is about (elevation type 2, or type 1 with the group enabled) ($($c -join ', '))" } else { "counted as the E result: no E record shows the token E is about (elevation type 2, or type 1 with the group enabled)" }) }
}

function Test-C4WrongAccountAdd {
    # PURE. The STOP finding of SPEC part 2: a record of F or E whose add SUCCEEDED under a principal that is not the account (a filter was added by the wrong principal).
    # Evaluated on every parseable record, valid or not. Without the account's SID (no prepare record) the record's own is_expected_account decides.
    param($Record, [string]$NcoSid)
    $cond = Get-C4Field $Record 'cond'
    if (($cond -isnot [string]) -or (@('F', 'E') -cnotcontains $cond)) { return $false }
    $rc = Get-C4RcValue (Get-C4Field $Record 'add.rc')
    $added = (($null -ne $rc) -and ($rc -eq [uint32]0)) -or ((Get-C4Field $Record 'add.class') -ceq 'succeeded') -or ((Get-C4Field $Record 'add.present_after') -eq $true)
    if (-not $added) { return $false }
    if ($NcoSid) { return ([string](Get-C4Field $Record 'user_sid') -ne $NcoSid) }
    return ((Get-C4Field $Record 'is_expected_account') -ne $true)
}

function Get-C4RecordRow {
    # PURE. One table row: the token facts the question turns on (elevation type, integrity, linked token, the two groups' attributes) and the two verdicts.
    param($Record, [string]$FileName)
    $g = { param($n) Get-C4Field $Record $n }
    $grp = {
        param($o)
        if ($null -eq $o) { return 'not recorded' }
        $p = Get-C4Field $o 'present'
        if ($p -is [string]) { return $p }
        if ($p -ne $true) { return 'absent' }
        $fl = @(); if ((Get-C4Field $o 'enabled') -eq $true) { $fl += 'enabled' }; if ((Get-C4Field $o 'use_for_deny_only') -eq $true) { $fl += 'deny-only' }
        return ("$([string](Get-C4Field $o 'attributes')) $($fl -join '+')").Trim()
    }
    $opened = & $g 'engine.open.opened'; $addRc = & $g 'add.rc'; $delRc = & $g 'delete.rc'
    $noVerdict = ($opened -ne $true) -or ($null -eq $addRc)
    $addText = if ($opened -ne $true) { if (& $g 'engine.open.error') { "engine open threw: $(& $g 'engine.open.error') (not a write verdict)" } else { "engine open failed $(& $g 'engine.open.rc') (not a write verdict)" } }
               elseif ($null -eq $addRc) { "threw: $(& $g 'add.error') (not a write verdict)" } else { "$addRc $(& $g 'add.class')" }
    $delText = if ($opened -ne $true) { '-' } elseif ($null -eq $delRc) { "threw (other): $(& $g 'delete.error')" } else { "$delRc $(& $g 'delete.class')" }
    return [ordered]@{
        cond = (& $g 'cond'); file = $FileName; user_sid = (& $g 'user_sid'); elevation_type = ("$(& $g 'elevation_type.value') $(& $g 'elevation_type.label')").Trim()
        integrity = (& $g 'integrity.label'); linked_token = (& $g 'linked_token.present')
        nco_group = (& $grp (& $g 'nco_group')); admins_group = (& $grp (& $g 'administrators'))
        add = $addText; delete = $delText; left_behind = (& $g 'delete.present_after')
        open_failed = ($opened -ne $true); no_verdict = $noVerdict; overall = (& $g 'overall'); operator_action = (& $g 'operator_action')
    }
}

function Format-C4Table {
    # PURE. One block per condition: n = the VALID records with a write verdict (the engine opened and the add returned a status); engine-open failures and adds
    # that threw are listed below it and never counted;
    # the E block also names the elevation_refused result when the Lead Architect's note is counted. Invalid records never reach this table.
    param($Rows, $ElevationRefused)
    $l = @()
    foreach ($c in $script:C4Conds) {
        $rs = @(@($Rows) | Where-Object { $_ -and $_.cond -ceq $c })
        $verdicts = @($rs | Where-Object { -not $_.no_verdict }); $opens = @($rs | Where-Object { $_.no_verdict })
        $line = '{0}: n = {1}' -f $c, $verdicts.Count
        if ($opens.Count) { $line += " (no write verdict: an engine-open failure or an add that threw; listed, not counted: $($opens.Count))" }
        if ($c -eq 'E' -and $ElevationRefused -and $ElevationRefused.given) { $line += $(if ($ElevationRefused.counted) { "; E result: elevation_refused (the Lead Architect's note: '$($ElevationRefused.note)')" } else { "; the elevation_refused note is NOT counted: $($ElevationRefused.reason)" }) }
        $l += $line
        foreach ($x in $verdicts + $opens) { $l += ('    elevation type {0} | integrity {1} | linked token {2} | S-1-5-32-556 {3} | S-1-5-32-544 {4} | add {5} | delete {6} | left behind {7}' -f $x.elevation_type, $x.integrity, $x.linked_token, $x.nco_group, $x.admins_group, $x.add, $x.delete, $x.left_behind) }
    }
    return @($l)
}

# ---- exit codes and parsers of the reads (pure) --------------------------------------------------------------------------------------------------------------
function Get-C4CheckExit {
    # PURE. -Check: a STOP or anything definitely present is 21 (even if another read failed); otherwise anything unreadable ($null) is 22; only an all-clear is 20.
    param($Sweep, $ProbeKeyPresent, $PubPresent, $AccountPresent, $MemberPresent, $ProfilePresent, [bool]$HarnessTrusted = $true)
    if ($Sweep.Stop) { return 21 }
    if (@($Sweep.NotClean).Count -gt 0) { return 21 }
    foreach ($x in @($ProbeKeyPresent, $PubPresent, $AccountPresent, $MemberPresent, $ProfilePresent)) { if ($x -eq $true) { return 21 } }
    if ($Sweep.Unreadable -or -not $HarnessTrusted) { return 22 }
    foreach ($x in @($ProbeKeyPresent, $PubPresent, $AccountPresent, $MemberPresent, $ProfilePresent)) { if ($null -eq $x) { return 22 } }
    if (-not $Sweep.Clean) { return 22 }
    return 20
}

function Get-C4PartDExit {
    # PURE. 20 only when every read says gone ($true): the account (net user), its name lookup, its membership, its ProfileList\<SID> entry, and every profile
    # folder of its name (the default path, a ProfileImagePath, any `nco-probe.<suffix>` folder). Anything else (present or unreadable) is 21.
    param($AccountGone, $LookupGone, $MemberGone, $ProfileGone, $ProfileListGone = $true, $ProfileFoldersGone = $true)
    foreach ($x in @($AccountGone, $LookupGone, $MemberGone, $ProfileGone, $ProfileListGone, $ProfileFoldersGone)) { if ($x -ne $true) { return 21 } }
    return 20
}

function Get-C4CollectExit {
    # PURE. STOP 9, then a filter left behind (or an engine that could not be read) 21, then an invalid record 4, else 0.
    param([bool]$Stop, [int]$LeftBehind, [bool]$ResidueUnreadable, [int]$Invalid)
    if ($Stop) { return 9 }
    if ($LeftBehind -gt 0 -or $ResidueUnreadable) { return 21 }
    if ($Invalid -gt 0) { return 4 }
    return 0
}

function Get-C4FinishExit {
    # PURE. A foreign filter is a STOP before anything is removed (9); an unverified removal is 7; a verified removal with the wrong-principal finding is 9; else 0.
    param([bool]$ForeignStop, [bool]$Verified, [bool]$WrongAccountFinding)
    if ($ForeignStop) { return 9 }
    if (-not $Verified) { return 7 }
    if ($WrongAccountFinding) { return 9 }
    return 0
}

function ConvertFrom-C4NetLocalGroup {
    # PURE. Member names from `net localgroup <group>`: the lines after the dashed rule, without the final completion line. $null when the text cannot be read so.
    param([string]$Text, [int]$ExitCode)
    if ($ExitCode -ne 0) { return $null }
    $lines = @([string]$Text -split "`r?`n")
    $i = -1; for ($k = 0; $k -lt $lines.Count; $k++) { if ($lines[$k] -match '^-{10,}\s*$') { $i = $k; break } }
    if ($i -lt 0) { return $null }
    $rest = @($lines | Select-Object -Skip ($i + 1) | ForEach-Object { $_.Trim() } | Where-Object { $_ })
    if ($rest.Count -lt 1) { return $null }
    return , @($rest | Select-Object -First ($rest.Count - 1))
}

function Test-C4MemberListed {
    # PURE. Whether the account is among the names (bare, or MACHINE\name).
    param([string[]]$Members, [string]$Account = $script:C4Account)
    foreach ($m in @($Members)) { if ($m -ieq $Account -or $m -like "*\$Account") { return $true } }
    return $false
}

function Get-C4NetUserState {
    # PURE. `net user <name>`: present (exit 0), absent (exit 2 with NET HELPMSG 2221, "the user name could not be found", in any language), unreadable.
    param([int]$ExitCode, [string]$Text)
    if ($ExitCode -eq 0) { return 'present' }
    if ($ExitCode -eq 2 -and $Text -match '\b2221\b') { return 'absent' }
    return 'unreadable'
}

function ConvertFrom-C4ProbeVersion {
    # PURE. `ncoprobe.exe --version`: one JSON object with probe_exe_sha256, probe_cs_sha256 (64 hex each) and toggle_build (true or false).
    param([string]$Stdout, [int]$ExitCode)
    $o = [ordered]@{ Ok = $false; ExeSha = $null; CsSha = $null; ToggleBuild = $null; Problem = '' }
    if ($ExitCode -ne 0) { $o.Problem = "--version exited $ExitCode"; return $o }
    $j = $null; try { $j = ConvertFrom-C4Json -Text ([string]$Stdout).Trim() } catch { $o.Problem = '--version did not print one JSON object'; return $o }
    $e = Get-C4Field $j 'probe_exe_sha256'; $c = Get-C4Field $j 'probe_cs_sha256'; $t = Get-C4Field $j 'toggle_build'
    if (($e -isnot [string]) -or ($e -notmatch '^[0-9a-fA-F]{64}$')) { $o.Problem = 'probe_exe_sha256 is not a SHA-256'; return $o }
    if (($c -isnot [string]) -or ($c -notmatch '^[0-9a-fA-F]{64}$')) { $o.Problem = 'probe_cs_sha256 is not a SHA-256'; return $o }
    if ($t -isnot [bool]) { $o.Problem = 'toggle_build is not true or false'; return $o }
    $o.ExeSha = $e.ToUpperInvariant(); $o.CsSha = $c.ToUpperInvariant(); $o.ToggleBuild = $t; $o.Ok = $true
    return $o
}

function ConvertFrom-C4ProbeSelfTest {
    # PURE. The probe's own self-test output: the LAST line that names checks_run and checks_failed (and checks_skipped when given), as `name: N` / `name N` / `name=N`,
    # as JSON, or as `checks_run / checks_failed / checks_skipped: N / M / K`. Passed only with exit 0, at least one check, none failed and no [FAIL] line. Skips are
    # counted and recorded, not failed (the probe skips its constants-against-SPEC check where SPEC.md is absent, as in the live folder).
    param([string]$Stdout, [int]$ExitCode)
    $run = $null; $failed = $null; $skipped = $null
    foreach ($l in @(@(([string]$Stdout -split "`r?`n")) | Select-Object -Last 400)) {
        $sl = [regex]::Match($l, 'checks_run\s*/\s*checks_failed(?:\s*/\s*checks_skipped)?\W{0,4}(\d+)\s*/\s*(\d+)(?:\s*/\s*(\d+))?')
        if ($sl.Success) { $run = [int]$sl.Groups[1].Value; $failed = [int]$sl.Groups[2].Value; $skipped = $(if ($sl.Groups[3].Success) { [int]$sl.Groups[3].Value } else { $null }); continue }
        $m = [regex]::Match($l, 'checks_run\W{0,4}(\d+)\D{1,24}checks_failed\W{0,4}(\d+)(?:\D{1,24}checks_skipped\W{0,4}(\d+))?')
        if ($m.Success) { $run = [int]$m.Groups[1].Value; $failed = [int]$m.Groups[2].Value; $skipped = $(if ($m.Groups[3].Success) { [int]$m.Groups[3].Value } else { $null }) }
    }
    $passed = ($ExitCode -eq 0) -and ($null -ne $run) -and ($run -ge 1) -and ($failed -eq 0) -and ([string]$Stdout -notmatch '\[FAIL\]')
    return [ordered]@{ Passed = [bool]$passed; ChecksRun = $run; ChecksFailed = $failed; ChecksSkipped = $skipped; Exit = $ExitCode }
}

function Get-C4RunSheetLines {
    # PURE. The part of each RUN_SHEET.md launch line that this driver may print, character for character as the sheet writes it, and how the sheet launches
    # it. F: the command its secondary-logon line runs (`cmd /k <probe> ... --wait`, step 3). E: the probe line that step 4's elevation request wraps as
    # `/k <line>` inside the account's own console (--wait). S and A: the whole line the operator types (no --wait, steps 5). The launcher text for F and E is
    # in RUN_SHEET.md only. Paths carry no quotes (the line goes inside the launcher's own quotes): a path with a space is refused.
    param([Parameter(Mandatory)][string]$BinDir, [Parameter(Mandatory)][string]$DropDir)
    if ($BinDir -match '\s' -or $DropDir -match '\s') { throw 'a public folder path contains a space: the launch lines would need quoting inside quotes' }
    $exe = Join-C4Path $BinDir $script:C4ProbeExeName; $proof = Join-C4Path $BinDir $script:C4ProbeProofName
    $line = { param($c, [bool]$wait) "$exe run --cond $c --live $proof --out $DropDir" + $(if ($wait) { ' --wait' } else { '' }) }
    return @(
        [ordered]@{ cond = 'F'; how = "as $($script:C4Account), filtered token: from a console moved to the public folder, Windows' secondary-logon line of RUN_SHEET.md step 3 runs this command, three times"; command = 'cmd /k ' + (& $line 'F' $true) }
        [ordered]@{ cond = 'E'; how = "as $($script:C4Account), elevated: a console as $($script:C4Account) (RUN_SHEET.md step 4), then INSIDE it the step-4 elevation request wraps this line as /k <line> (the prompt is for $($script:C4Account)); a refusal to elevate is recorded with -Collect -ElevationRefused; three times. Or the Task Scheduler route (RUN_SHEET.md step 4b): the task's action is this line without --wait, run as $($script:C4Account) with highest privileges (an unsplit token with the group enabled)"; command = (& $line 'E' $true) }
        [ordered]@{ cond = 'S'; how = "typed as is in the operator's normal non-elevated console (RUN_SHEET.md step 5), three times"; command = (& $line 'S' $false) }
        [ordered]@{ cond = 'A'; how = "typed as is in the operator's elevated console (RUN_SHEET.md step 5), three times"; command = (& $line 'A' $false) }
    )
}

# ---- parser checks: seams and the account lifecycle ----------------------------------------------------------------------------------------------------------
# Two parser locks hold this file. The seams lock: every machine-touching call (the engine, the harness, the export, ACL reads and writes, account and token
# reads, the system tools, process starts, registry types) sits inside a function whose name contains "-C4Real", and every file creation or deletion sits in
# a seam, the self-test or Invoke-C4WriteProof. The account-lifecycle lock: no account is created, changed or used to log on, anywhere in the driver or the
# probe's sources; the two reads are allowed. Both locks' patterns, and every planted form the self-test proves them with, live in the lock corpus beside this
# script (case4-lock-corpus.json): data only, read with ConvertFrom-Json and never executed. Every pattern is a template with one slot and a list of
# alternatives, and every alternative carries the one plant it alone catches; the self-test requires each alternative to catch its plant and to be needed for
# it. Only -SelfTest parses the corpus (Initialize-C4LockCorpus, from the entry); the live modes bind it by hash through the driver proof, like every other
# bound file, and never parse it.
$script:C4CorpusSchema = 'nep5-case4-lock-corpus-v2'
$script:C4CorpusPatternVars = [ordered]@{ machine_commands = 'C4MachineCommands'; machine_members = 'C4MachineMembers'; machine_types = 'C4MachineTypes'; fs_commands = 'C4FsCommands'
                                          fs_static_types = 'C4FsStaticTypes'; fs_members = 'C4FsMembers'; lifecycle_commands = 'C4LifecycleCommands'; lifecycle_types = 'C4LifecycleTypes'
                                          lifecycle_apis = 'C4LifecycleApis'; lifecycle_interpreters = 'C4LifecycleInterpreters'; lifecycle_arg_text = 'C4LifecycleArgText'; net_names = 'C4NetNames'
                                          com_switch = 'C4ComSwitch'; com_members = 'C4ComMembers'; lifecycle_new_object_types = 'C4LifecycleNewObjectTypes'
                                          lifecycle_assign_members = 'C4LifecycleAssignMembers'; cs_marker = 'C4CsMarker'; process_types = 'C4ProcessTypes' }
$script:C4CorpusPatternKeys = @($script:C4CorpusPatternVars.Keys)
# The fewest alternatives each pattern may have: a corpus that drops an alternative (with its plant) fails the self-test. Counts only, no forms.
$script:C4CorpusAlternativeFloors = [ordered]@{ machine_commands = 43; machine_members = 3; machine_types = 6; fs_commands = 46; fs_static_types = 3; fs_members = 14; lifecycle_commands = 43
                                                lifecycle_types = 11; lifecycle_apis = 23; lifecycle_interpreters = 8; lifecycle_arg_text = 29; net_names = 2; com_switch = 1; com_members = 2
                                                lifecycle_new_object_types = 6; lifecycle_assign_members = 5; cs_marker = 1; process_types = 2 }
$script:C4CorpusScopes = @('seams', 'lifecycle', 'lifecycle-cs')
$script:C4CorpusFixtureKeys = @('cs_sample', 'cs_comment_only', 'seam_named', 'seam_plants', 'fs_off', 'impure_plants', 'lifecycle_ps', 'lifecycle_cs', 'ps_carrying_cs', 'lifecycle_reads',
                                'lifecycle_off', 'switch_plant', 'library_helpers')
$script:C4Corpus = $null
$script:C4CorpusPatternVars.Values | ForEach-Object { Set-Variable -Scope Script -Name $_ -Value $null }
$script:C4LifecycleSwitchAllowed = @(); $script:C4CsSample = $null
$script:C4FsAllowedFunctions = @('Invoke-C4SelfTest', 'Invoke-C4WriteProof')

function Get-C4CorpusPattern {
    # PURE. A corpus pattern's regex: its template with its alternatives joined by | in the slot ({0}). -Without leaves one alternative out (the self-test's
    # per-alternative check). No alternative left gives a pattern that matches nothing.
    param([Parameter(Mandatory)]$Pattern, [string]$Without)
    $alts = @(@($Pattern['alternatives']) | ForEach-Object { [string]$_['alt'] } | Where-Object { $_ -and ($_ -cne $Without) })
    if ($alts.Count -eq 0) { return '(?!)' }
    return ([string]$Pattern['template']).Replace('{0}', ($alts -join '|'))
}

function Get-C4JsonDuplicateKeys {
    # PURE. Every key given more than once in one JSON object, ignoring case as ConvertFrom-Json -AsHashtable does (which keeps the LAST silently), as a path.
    param([Parameter(Mandatory)][string]$Text)
    $doc = [System.Text.Json.JsonDocument]::Parse($Text)
    try {
        $out = New-Object System.Collections.Generic.List[string]
        $walk = $null
        $walk = {
            param($el, $path)
            if ($el.ValueKind -eq [System.Text.Json.JsonValueKind]::Object) {
                $seen = New-Object 'System.Collections.Generic.HashSet[string]' ([StringComparer]::OrdinalIgnoreCase)
                foreach ($pr in $el.EnumerateObject()) { if (-not $seen.Add($pr.Name)) { $out.Add("$path.$($pr.Name)") }; & $walk $pr.Value "$path.$($pr.Name)" }
            } elseif ($el.ValueKind -eq [System.Text.Json.JsonValueKind]::Array) { $i = 0; foreach ($x in $el.EnumerateArray()) { & $walk $x "$path[$i]"; $i++ } }
        }
        & $walk $doc.RootElement '$'
        return @($out)
    } finally { $doc.Dispose() }
}

function Test-C4LockCorpus {
    # PURE. Why a parsed lock corpus is unusable (empty = usable): its schema; every pattern an object with a template holding exactly one slot, a known scope
    # and a non-empty list of alternatives, each with an alt and a finding that compile and a non-empty plant; the built pattern compiles; the switch allowlist
    # an array of strings; every fixture set present and non-empty. The coverage itself (each alternative catches its plant) is the self-test's.
    param($Corpus)
    if ($Corpus -isnot [System.Collections.IDictionary]) { return @('corpus: not a JSON object') }
    $p = @()
    if ($Corpus['schema'] -cne $script:C4CorpusSchema) { $p += "schema: not '$($script:C4CorpusSchema)'" }
    $pat = $Corpus['patterns']; $fx = $Corpus['fixtures']
    if ($pat -isnot [System.Collections.IDictionary]) { $p += 'patterns: missing'; $pat = @{} }
    if ($fx -isnot [System.Collections.IDictionary]) { $p += 'fixtures: missing'; $fx = @{} }
    foreach ($k in $script:C4CorpusPatternKeys) {
        $pd = $pat[$k]
        if ($pd -isnot [System.Collections.IDictionary]) { $p += "patterns.${k}: missing or not an object"; continue }
        $t = $pd['template']
        $tOk = ($t -is [string]) -and ([regex]::Matches($t, [regex]::Escape('{0}')).Count -eq 1)
        if (-not $tOk) { $p += "patterns.${k}.template: not a string with exactly one {0}" }
        if ($script:C4CorpusScopes -cnotcontains $pd['scope']) { $p += "patterns.${k}.scope: not one of $($script:C4CorpusScopes -join ', ')" }
        $alts = $pd['alternatives']
        if (($null -eq $alts) -or ($alts -is [string]) -or ($alts -is [System.Collections.IDictionary]) -or (@($alts).Count -eq 0)) { $p += "patterns.${k}.alternatives: missing or empty"; continue }
        $i = 0
        foreach ($a in @($alts)) {
            if ($a -isnot [System.Collections.IDictionary]) { $p += "patterns.${k}.alternatives[$i]: not an object"; $i++; continue }
            foreach ($f in @('alt', 'plant', 'finding')) { if (($a[$f] -isnot [string]) -or -not $a[$f]) { $p += "patterns.${k}.alternatives[$i].${f}: missing or empty" } }
            foreach ($f in @('alt', 'finding')) { if (($a[$f] -is [string]) -and $a[$f]) { try { [void][regex]::new($a[$f]) } catch { $p += "patterns.${k}.alternatives[$i].${f}: not a regex" } } }
            $i++
        }
        if ($tOk) { try { [void][regex]::new((Get-C4CorpusPattern -Pattern $pd)) } catch { $p += "patterns.${k}: the built pattern is not a regex ($($_.Exception.Message))" } }
    }
    $sa = $Corpus['switch_allowlist']
    if (($null -eq $sa) -or ($sa -is [string]) -or ($sa -is [System.Collections.IDictionary]) -or @($sa | Where-Object { $_ -isnot [string] }).Count) { $p += 'switch_allowlist: not an array of strings' }
    foreach ($k in $script:C4CorpusFixtureKeys) {
        $v = $fx[$k]
        if (($null -eq $v) -or (($v -is [string]) -and -not $v) -or (($v -isnot [string]) -and @($v).Count -eq 0)) { $p += "fixtures.${k}: missing or empty" }
    }
    return @($p)
}

function Read-C4LockCorpus {
    # The lock corpus, parsed and checked; throws with the reasons when it is missing, not JSON, gives a key twice, or is unusable.
    param([Parameter(Mandatory)][string]$Path)
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { throw "the lock corpus is missing ($Path)" }
    $text = [IO.File]::ReadAllText($Path)
    $dups = @()
    try { $dups = @(Get-C4JsonDuplicateKeys -Text $text) } catch { throw "the lock corpus is not JSON ($Path): $($_.Exception.Message)" }
    if ($dups.Count) { throw "the lock corpus gives a key twice ($Path): $($dups -join ', ')" }
    $c = $null
    try { $c = ConvertFrom-Json -InputObject $text -AsHashtable -Depth 20 } catch { throw "the lock corpus is not JSON ($Path): $($_.Exception.Message)" }
    $why = @(Test-C4LockCorpus -Corpus $c)
    if ($why.Count) { throw "the lock corpus is unusable ($Path): $($why -join '; ')" }
    return $c
}

function Initialize-C4LockCorpus {
    # Loads the lock corpus for -SelfTest and sets the two locks' pattern variables from it. Called once, from the entry, under if ($SelfTest); the live modes
    # never parse the corpus (the driver proof binds its hash).
    param([Parameter(Mandatory)][string]$Path)
    $script:C4Corpus = Read-C4LockCorpus -Path $Path
    foreach ($k in $script:C4CorpusPatternKeys) { Set-Variable -Scope Script -Name $script:C4CorpusPatternVars[$k] -Value (Get-C4CorpusPattern -Pattern $script:C4Corpus.patterns[$k]) }
    $script:C4LifecycleSwitchAllowed = @($script:C4Corpus['switch_allowlist'])
    $script:C4CsSample = $script:C4Corpus.fixtures.cs_sample
}

function Get-C4CommandName {
    # PURE. The command a CommandAst runs, without a path or .exe: its parsed name, or for `& <expression>` the last NAME.exe written in the first element's text.
    param($Cmd)
    $n = $Cmd.GetCommandName()
    if ($n) { return (($n -replace '(?i)\.exe$', '') -replace '^.*[\\/]', '') }
    $m = [regex]::Matches($Cmd.CommandElements[0].Extent.Text, '(?i)([\w-]+)\.exe')
    if ($m.Count) { return $m[$m.Count - 1].Groups[1].Value }
    return ''
}

function Get-C4SeamProblems {
    # PURE on the text. Problems (empty = every machine-touching call sits behind a seam): (1) every machine command (by parsed name or by the NAME.exe written in
    # the command), member call or type use is inside a *-C4Real* function; (2) every file creation or deletion (the commands, and the static mutators of
    # IO.File, IO.Directory and FileSystemAclExtensions) is inside a seam, the self-test or Invoke-C4WriteProof; (3) a *-C4Real* function is called only from
    # another one, from the entry's live branch (the else of `if ($SelfTest)`), or, for the two proof-time seams, inside `if ($WriteProof)` in Invoke-C4SelfTest;
    # (4) the real context is built exactly once. Honest limit: a command run through a variable holding its path is not seen.
    param([Parameter(Mandatory)][string]$Text, [string]$CommandRegex = $script:C4MachineCommands, [string]$MemberRegex = $script:C4MachineMembers, [string]$TypeRegex = $script:C4MachineTypes,
          [string]$FsCommandRegex = $script:C4FsCommands, [string]$FsTypeRegex = $script:C4FsStaticTypes, [string]$FsMemberRegex = $script:C4FsMembers, [string[]]$FsAllowed = $script:C4FsAllowedFunctions)
    if (-not $script:C4Corpus) { throw 'the lock corpus is not loaded: the parser locks run under -SelfTest only' }
    $tokens = $null; $errs = $null
    $ast = [Management.Automation.Language.Parser]::ParseInput($Text, [ref]$tokens, [ref]$errs)
    if ($errs -and $errs.Count) { return @("the text does not parse: $($errs[0].Message)") }
    $p = @()
    $fnOf = { param($n) $x = $n.Parent; while ($x) { if ($x -is [Management.Automation.Language.FunctionDefinitionAst]) { return $x }; $x = $x.Parent }; return $null }
    $inSeam = { param($n) $f = & $fnOf $n; return [bool]($f -and $f.Name -match '-C4Real') }
    $fsOk = { param($n) $f = & $fnOf $n; return [bool]($f -and ($f.Name -match '-C4Real' -or $FsAllowed -contains $f.Name)) }
    $where = { param($n) $f = & $fnOf $n; if ($f) { $f.Name } else { 'the entry' } }
    $within = { param($outer, $inner) $outer -and $inner.Extent.StartOffset -ge $outer.Extent.StartOffset -and $inner.Extent.EndOffset -le $outer.Extent.EndOffset }
    foreach ($c in @($ast.FindAll({ param($n) $n -is [Management.Automation.Language.CommandAst] }, $true))) {
        $name = Get-C4CommandName $c
        $hit = ($name -and $name -match $CommandRegex)
        if (-not $hit -and $c.GetCommandName() -eq 'New-Object') { $hit = [bool](@($c.CommandElements | Select-Object -Skip 1 | Where-Object { $_.Extent.Text -match $TypeRegex -or $_.Extent.Text -match $script:C4ComSwitch }).Count) }
        if ($hit -and -not (& $inSeam $c)) { $p += "line $($c.Extent.StartLineNumber): $name outside a seam (in $(& $where $c))" }
        if ($name -and $name -match $FsCommandRegex -and -not (& $fsOk $c)) { $p += "line $($c.Extent.StartLineNumber): $name writes or deletes files outside a seam (in $(& $where $c))" }
    }
    foreach ($mx in @($ast.FindAll({ param($n) $n -is [Management.Automation.Language.InvokeMemberExpressionAst] }, $true))) {
        $mn = [string]$mx.Member.Value
        if ($mn -and $mn -match $MemberRegex -and -not (& $inSeam $mx)) { $p += "line $($mx.Extent.StartLineNumber): .$mn() outside a seam" }
        if ($mx.Static -and $mx.Expression -is [Management.Automation.Language.TypeExpressionAst]) {
            $tn = [string]$mx.Expression.TypeName.FullName
            if ($tn -match $FsTypeRegex -and $mn -match $FsMemberRegex -and -not (& $fsOk $mx)) { $p += "line $($mx.Extent.StartLineNumber): [$tn]::$mn writes or deletes files outside a seam (in $(& $where $mx))" }
        }
    }
    foreach ($tx in @($ast.FindAll({ param($n) $n -is [Management.Automation.Language.TypeExpressionAst] -or $n -is [Management.Automation.Language.TypeConstraintAst] }, $true))) {
        $tn = [string]$tx.TypeName.FullName
        if ($tn -match $TypeRegex -and -not (& $inSeam $tx)) { $p += "line $($tx.Extent.StartLineNumber): [$tn] outside a seam" }
    }
    $ifSelf = @($ast.FindAll({ param($n) $n -is [Management.Automation.Language.IfStatementAst] -and $n.Clauses.Count -ge 1 -and $n.Clauses[0].Item1.Extent.Text -eq '$SelfTest' }, $true))
    $realCalls = @($ast.FindAll({ param($n) $n -is [Management.Automation.Language.CommandAst] -and $n.GetCommandName() -match '-C4Real' }, $true))
    foreach ($c in $realCalls) {
        $name = $c.GetCommandName(); $f = & $fnOf $c
        if ($f -and $f.Name -match '-C4Real') { continue }
        if (-not $f) {
            $ok = $false; foreach ($i in $ifSelf) { if ($i.ElseClause -and (& $within $i.ElseClause $c)) { $ok = $true } }
            if (-not $ok) { $p += "line $($c.Extent.StartLineNumber): $name called at the top level outside the live branch (the else of if (`$SelfTest))" }
            continue
        }
        if ($f.Name -eq 'Invoke-C4SelfTest' -and $script:C4ProofSeams -contains $name) {
            $ok = $false; $x = $c.Parent
            while ($x -and $x -ne $f) {
                if ($x -is [Management.Automation.Language.IfStatementAst]) { foreach ($cl in $x.Clauses) { if ($cl.Item1.Extent.Text -eq '$WriteProof' -and (& $within $cl.Item2 $c)) { $ok = $true } } }
                $x = $x.Parent
            }
            if (-not $ok) { $p += "line $($c.Extent.StartLineNumber): $name in the self-test outside if (`$WriteProof)" }
            continue
        }
        $p += "line $($c.Extent.StartLineNumber): $name called from $($f.Name) (only the seams, the live branch and -WriteProof may)"
    }
    $ctxCalls = @($realCalls | Where-Object { $_.GetCommandName() -eq 'New-C4RealCtx' })
    if ($ctxCalls.Count -ne 1) { $p += "the real context is built $($ctxCalls.Count) times (expected exactly once, in the live branch)" }
    return @($p)
}

function Get-C4LifecycleHits {
    # PURE on the text. Every account-lifecycle use (empty = none), by the lock corpus's patterns. PowerShell: a forbidden command by parsed name or by the
    # NAME.exe written in the command; net or net1 in any form but the two reads, whose name is a literal or a [string]-typed parameter (an array or a splat can
    # carry a switch); an interpreter or process start whose arguments match the argument pattern; a .NET process start ([Diagnostics.Process]::Start,
    # [Diagnostics.ProcessStartInfo]::new, or New-Object of either) whose arguments match it; any slash switch outside $SwitchAllowed (deny by default; the list
    # is empty); New-Object of a listed type or of any COM object; a COM class by its registry name; a listed type, by short or fully qualified name; an
    # assignment to a listed member; a listed API in any C# source string. C#: a listed API anywhere outside comments, and an entry point that is not one plain
    # literal. Honest limit: a command or type name built at run time, or run through a variable or a script block made from text, is not seen.
    param([Parameter(Mandatory)][string]$Text, [ValidateSet('ps', 'cs')][string]$Kind = 'ps', [string]$CommandRegex = $script:C4LifecycleCommands, [string]$TypeRegex = $script:C4LifecycleTypes, [string]$ApiRegex = $script:C4LifecycleApis,
          [string]$InterpreterRegex = $script:C4LifecycleInterpreters, [string]$ArgTextRegex = $script:C4LifecycleArgText, [string[]]$SwitchAllowed = $script:C4LifecycleSwitchAllowed,
          [string]$ProcessRegex = $script:C4ProcessTypes)
    if (-not $script:C4Corpus) { throw 'the lock corpus is not loaded: the parser locks run under -SelfTest only' }
    $hits = @()
    if ($Kind -eq 'cs') {
        $code = [regex]::Replace($Text, '(?s)/\*.*?\*/', ' '); $code = [regex]::Replace($code, '(?m)(?<!:)//.*$', '')
        foreach ($m in [regex]::Matches($code, $ApiRegex)) { $hits += "C#: $($m.Value)" }
        return @($hits)
    }
    $tokens = $null; $errs = $null
    $ast = [Management.Automation.Language.Parser]::ParseInput($Text, [ref]$tokens, [ref]$errs)
    if ($errs -and $errs.Count) { return @("the text does not parse: $($errs[0].Message)") }
    $fnOf = { param($n) $x = $n.Parent; while ($x) { if ($x -is [Management.Automation.Language.FunctionDefinitionAst]) { return $x }; $x = $x.Parent }; return $null }
    $stringParam = {
        param($cmd, $var)
        $f = & $fnOf $cmd; if (-not $f) { return $false }
        $params = @(); if ($f.Parameters) { $params += @($f.Parameters) }; if ($f.Body.ParamBlock) { $params += @($f.Body.ParamBlock.Parameters) }
        foreach ($pa in $params) {
            if ($pa.Name.VariablePath.UserPath -ieq $var.VariablePath.UserPath) {
                return [bool](@($pa.Attributes | Where-Object { $_ -is [Management.Automation.Language.TypeConstraintAst] -and $_.TypeName.FullName -ieq 'string' }).Count)
            }
        }
        return $false
    }
    foreach ($c in @($ast.FindAll({ param($n) $n -is [Management.Automation.Language.CommandAst] }, $true))) {
        $name = Get-C4CommandName $c; $ln = $c.Extent.StartLineNumber
        $el = @($c.CommandElements | Select-Object -Skip 1)
        $argText = (@($el | ForEach-Object { $_.Extent.Text }) -join ' ')
        $switches = @($el | Where-Object { $_.Extent.Text -match '^["'']?/[A-Za-z?]' } | ForEach-Object { ('{0} {1}' -f $name, ($_.Extent.Text.Trim('"', "'") -replace '[:=].*$', '')).Trim() })
        $denied = @($switches | Where-Object { $SwitchAllowed -notcontains $_ })
        if ($denied.Count) { $hits += "line ${ln}: a slash switch ($($denied -join ', ')); no switch is on the allowlist"; continue }
        if ($name -and $name -match $CommandRegex) { $hits += "line ${ln}: $name"; continue }
        if ($name -match $script:C4NetNames) {
            $verbOk = ($el.Count -ge 1) -and ($el[0] -is [Management.Automation.Language.StringConstantExpressionAst]) -and ($el[0].Value -in @('user', 'localgroup'))
            $argOk = $false
            if ($el.Count -eq 2) {
                $a = $el[1]
                if ($a -is [Management.Automation.Language.StringConstantExpressionAst]) { $argOk = ($a.Value -notmatch '^\s*/') }
                elseif ($a -is [Management.Automation.Language.VariableExpressionAst] -and -not $a.Splatted) { $argOk = (& $stringParam $c $a) }
            }
            if (-not ($verbOk -and $argOk)) { $hits += "line ${ln}: $name $argText (only the two reads are allowed: the user or localgroup verb with one literal or [string] parameter)" }
            continue
        }
        if ($name -and $name -match $InterpreterRegex -and $argText -match $ArgTextRegex) { $hits += "line ${ln}: $name carries '$($Matches[0])' in its arguments" ; continue }
        if ($c.GetCommandName() -eq 'New-Object') {
            if (@($el | Where-Object { $_.Extent.Text -match $script:C4LifecycleNewObjectTypes -or $_.Extent.Text -match $script:C4ComSwitch }).Count) { $hits += "line ${ln}: New-Object of a credential, directory or COM type" }
            if (@($el | Where-Object { $_.Extent.Text -match $ProcessRegex }).Count -and ($argText -match $ArgTextRegex)) { $hits += "line ${ln}: a .NET process start carrying '$($Matches[0])'" }
        }
    }
    foreach ($mx in @($ast.FindAll({ param($n) $n -is [Management.Automation.Language.InvokeMemberExpressionAst] }, $true))) {
        if ([string]$mx.Member.Value -match $script:C4ComMembers) { $hits += "line $($mx.Extent.StartLineNumber): a COM class by its registry name" }
        if ($mx.Static -and ($mx.Expression -is [Management.Automation.Language.TypeExpressionAst]) -and ([string]$mx.Expression.TypeName.FullName -match $ProcessRegex) -and ([string]$mx.Member.Value -match '(?i)^(Start|new)$')) {
            $pa = (@($mx.Arguments | ForEach-Object { $_.Extent.Text }) -join ' ')
            if ($pa -match $ArgTextRegex) { $hits += "line $($mx.Extent.StartLineNumber): a .NET process start carrying '$($Matches[0])'" }
        }
    }
    foreach ($tx in @($ast.FindAll({ param($n) $n -is [Management.Automation.Language.TypeExpressionAst] -or $n -is [Management.Automation.Language.TypeConstraintAst] }, $true))) {
        if ([string]$tx.TypeName.FullName -match $TypeRegex) { $hits += "line $($tx.Extent.StartLineNumber): [$($tx.TypeName.FullName)]" }
    }
    foreach ($as in @($ast.FindAll({ param($n) $n -is [Management.Automation.Language.AssignmentStatementAst] -and $n.Left -is [Management.Automation.Language.MemberExpressionAst] }, $true))) {
        $mn = [string]$as.Left.Member.Extent.Text
        if ($mn -match $script:C4LifecycleAssignMembers) { $hits += "line $($as.Extent.StartLineNumber): assignment to .$mn" }
    }
    foreach ($s in @($ast.FindAll({ param($n) $n -is [Management.Automation.Language.StringConstantExpressionAst] -or $n -is [Management.Automation.Language.ExpandableStringExpressionAst] }, $true))) {
        $v = [string]$s.Value
        if ($v -match $script:C4CsMarker) { foreach ($m in [regex]::Matches($v, $ApiRegex)) { $hits += "line $($s.Extent.StartLineNumber): C# in a string: $($m.Value)" } }
    }
    return @($hits)
}

function Get-C4LibLifecycleFunctions {
    # PURE on the texts. The functions of the given library texts that call a lifecycle command ($script:C4LifecycleCommands, by parsed name), directly or through
    # another such function (to a fixed point). The driver may call none of them; the self-test holds the static lifecycle list to this computed set.
    param([Parameter(Mandatory)][string[]]$Texts, [string]$CommandRegex = $script:C4LifecycleCommands)
    if (-not $script:C4Corpus) { throw 'the lock corpus is not loaded: the parser locks run under -SelfTest only' }
    $calls = @{}
    foreach ($t in $Texts) {
        $ast = [Management.Automation.Language.Parser]::ParseInput($t, [ref]$null, [ref]$null)
        foreach ($fn in @($ast.FindAll({ param($n) $n -is [Management.Automation.Language.FunctionDefinitionAst] }, $true))) {
            $calls[$fn.Name] = @($fn.Body.FindAll({ param($n) $n -is [Management.Automation.Language.CommandAst] }, $true) | ForEach-Object { Get-C4CommandName $_ } | Where-Object { $_ } | Select-Object -Unique)
        }
    }
    $set = New-Object System.Collections.Generic.HashSet[string] ([StringComparer]::OrdinalIgnoreCase)
    foreach ($k in $calls.Keys) { if (@($calls[$k] | Where-Object { $_ -match $CommandRegex }).Count) { [void]$set.Add($k) } }
    do {
        $grew = $false
        foreach ($k in $calls.Keys) { if (-not $set.Contains($k) -and @($calls[$k] | Where-Object { $set.Contains($_) }).Count) { [void]$set.Add($k); $grew = $true } }
    } while ($grew)
    return @($set | Sort-Object)
}

function Get-C4ImpureCalls {
    # PURE on the text. The calls inside the named functions that are not pure: a command outside $AllowedCommands, and a static method call on any type outside
    # Security.AccessControl and Security.Principal (in-memory security objects), and an instance-member call named like a file write ($FsMemberRegex, e.g.
    # .Create() on a DirectoryInfo). A call through a variable (`& $fn`) is the caller's own scriptblock, not counted.
    param([Parameter(Mandatory)][string]$Text, [Parameter(Mandatory)][string[]]$Functions, [string[]]$AllowedCommands = @(), [string]$FsMemberRegex = $script:C4FsMembers)
    if (-not $script:C4Corpus) { throw 'the lock corpus is not loaded: the parser locks run under -SelfTest only' }
    $ast = [Management.Automation.Language.Parser]::ParseInput($Text, [ref]$null, [ref]$null)
    $out = @()
    foreach ($name in $Functions) {
        $f = $ast.Find({ param($x) $x -is [Management.Automation.Language.FunctionDefinitionAst] -and $x.Name -eq $name }, $true)
        if (-not $f) { $out += "${name}: missing"; continue }
        foreach ($c in @($f.FindAll({ param($x) $x -is [Management.Automation.Language.CommandAst] }, $true))) {
            $cn = $c.GetCommandName(); if ($cn -and $AllowedCommands -notcontains $cn) { $out += "${name}: $cn" }
        }
        foreach ($mx in @($f.FindAll({ param($x) $x -is [Management.Automation.Language.InvokeMemberExpressionAst] -and $x.Static -and $x.Expression -is [Management.Automation.Language.TypeExpressionAst] }, $true))) {
            $tn = [string]$mx.Expression.TypeName.FullName
            if ($tn -notmatch '(?i)^(System\.)?Security\.(AccessControl|Principal)\.') { $out += "${name}: [$tn]::$($mx.Member.Value)" }
        }
        foreach ($mx in @($f.FindAll({ param($x) $x -is [Management.Automation.Language.InvokeMemberExpressionAst] -and -not $x.Static }, $true))) {
            if ([string]$mx.Member.Value -match $FsMemberRegex) { $out += "${name}: .$($mx.Member.Value)()" }
        }
    }
    return @($out)
}

# ---- the driver proof ---------------------------------------------------------------------------------------------------------------------------------------
function Get-C4BoundHashes {
    # What the driver proof binds, as hashes of what is there NOW: the text files (LF-normalised; this script by the bytes that are running), the four libraries (the
    # bytes this process ran when it loaded them from $Folder, else from disk), the wrapped script (the bytes Import-WfpHelpers evaluated), and the raw files (the probe
    # exe, the harness exe, halfset.rs and the matrix's harness proof). A missing file is reported by name, never skipped.
    param([Parameter(Mandatory)][string]$Folder, [string]$SelfSha, [hashtable]$LoadedLibHashes = @{}, [string]$LoadedLibFolder, [string]$WrappedSha)
    $sameFolder = ($LoadedLibFolder -and ($LoadedLibFolder.TrimEnd('\', '/') -ieq $Folder.TrimEnd('\', '/')))
    $text = [ordered]@{}; $libs = [ordered]@{}; $raw = [ordered]@{}; $missing = @()
    foreach ($n in $script:C4TextFiles) {
        if ($n -eq $script:C4SelfName) { if ($SelfSha) { $text[$n] = $SelfSha.ToUpperInvariant() } else { $missing += $n }; continue }
        $p = Join-C4Path $Folder $n
        if (Test-Path -LiteralPath $p -PathType Leaf) { $text[$n] = Get-NormalizedSha256 -Path $p } else { $missing += $n }
    }
    foreach ($n in $script:C4LibFiles) {
        $p = Join-C4Path $Folder $n
        if ($sameFolder -and $LoadedLibHashes.ContainsKey($n)) { $libs[$n] = $LoadedLibHashes[$n] }
        elseif (Test-Path -LiteralPath $p -PathType Leaf) { $libs[$n] = Get-NormalizedSha256 -Path $p } else { $missing += $n }
    }
    foreach ($n in $script:C4RawFiles) { $h = Get-N5RawSha256 -Path (Join-C4Path $Folder $n); if ($h) { $raw[$n] = $h } else { $missing += $n } }
    if (-not $WrappedSha) { $missing += $script:C4WrappedName }
    return [ordered]@{ Text = $text; Libs = $libs; Wrapped = $(if ($WrappedSha) { $WrappedSha.ToUpperInvariant() } else { $null }); Raw = $raw; Missing = @($missing) }
}

function Get-C4ChecksCeiling {
    # The most checks a real -SelfTest of this driver can run: its `Chk` call sites counted by the parser, plus 40 for the -WriteProof ones and any in a loop. 0 when absent.
    param([Parameter(Mandatory)][string]$Path)
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { return 0 }
    $tokens = $null; $errs = $null; $ast = [Management.Automation.Language.Parser]::ParseFile((Resolve-Path -LiteralPath $Path).Path, [ref]$tokens, [ref]$errs)
    $n = @($ast.FindAll({ param($x) $x -is [Management.Automation.Language.CommandAst] -and $x.GetCommandName() -eq 'Chk' }, $true)).Count
    if ($n -eq 0) { return 0 }
    return ($n + 40)
}

function New-C4DriverProofObject {
    # PURE on its arguments. The record -SelfTest -WriteProof saves (schema nep5-case4-driver-proof-v1).
    param($Bound, [string[]]$PassedTags, [string[]]$FailedChecks, [int]$ChecksRun, [int]$ChecksPassed, $ProbeVersion, $ProbeSelfTest, [string]$HostInfo, [string]$When)
    $all = @($script:C4RequiredTags | Where-Object { $PassedTags -contains $_ })
    return [ordered]@{
        schema = $script:C4DriverProofSchema; written = $When; host = $HostInfo
        checks_run = $ChecksRun; checks_passed = $ChecksPassed; failed_checks = @($FailedChecks)
        tags_passed = @($PassedTags | Select-Object -Unique); tags_required = @($script:C4RequiredTags)
        passed = (@($FailedChecks).Count -eq 0 -and $all.Count -eq $script:C4RequiredTags.Count -and $ChecksRun -eq $ChecksPassed)
        text_sha256_lf = $Bound.Text; libraries_sha256_lf = $Bound.Libs; wrapped_script_sha256_lf = $Bound.Wrapped; raw_sha256 = $Bound.Raw
        probe_version = [ordered]@{ probe_exe_sha256 = [string]$ProbeVersion.ExeSha; probe_cs_sha256 = [string]$ProbeVersion.CsSha; toggle_build = $ProbeVersion.ToggleBuild; engine_open_trace_empty = [bool]$ProbeVersion.TraceEmpty }
        probe_selftest = [ordered]@{ passed = [bool]$ProbeSelfTest.Passed; checks_run = $ProbeSelfTest.ChecksRun; checks_failed = $ProbeSelfTest.ChecksFailed; checks_skipped = $ProbeSelfTest.ChecksSkipped }
    }
}

function Test-C4DriverProof {
    # The token -Prepare demands: @{ Kind = 'Nep5Case4Proof'; Ok; Problems; Nonce; ProbeExeSha; ProbeCsSha; HarnessSha }. Ok only when the proof parses, says passed with
    # no failed check, records a real run (at least 60 checks, all passed, no more than the call sites allow), lists every required tag, is younger than 24 h, and EVERY
    # hash it holds equals the hash now (Get-C4BoundHashes); the matrix's harness proof must also be valid now, and the probe exe it names must be a non-toggle build.
    param([Parameter(Mandatory)][string]$ProofPath, [Parameter(Mandatory)][string]$Folder, [string]$SelfSha, [hashtable]$LoadedLibHashes = $script:LoadedLibHashes, [string]$LoadedLibFolder = $script:LoadedLibFolder,
          [string]$WrappedSha, [datetimeoffset]$Now = [datetimeoffset]::Now, [int]$MaxAgeHours = $script:C4ProofMaxAgeHours)
    $pr = New-Object System.Collections.ArrayList
    $tok = [pscustomobject]@{ Kind = 'Nep5Case4Proof'; Ok = $false; Problems = @(); ProofPath = $ProofPath; Written = $null; Nonce = $null; ProbeExeSha = $null; ProbeCsSha = $null; HarnessSha = $null; HarnessProofSha = $null }
    if (-not (Test-Path -LiteralPath $ProofPath -PathType Leaf)) { $tok.Problems = @("no driver proof at ${ProofPath}: run $($script:C4SelfName) -SelfTest -WriteProof first"); return $tok }
    if (([IO.FileInfo]$ProofPath).Length -gt 4194304) { $tok.Problems = @('the driver proof is over 4 MiB'); return $tok }
    $p = $null; try { $p = ConvertFrom-C4Json -Text ([IO.File]::ReadAllText($ProofPath)) } catch { $tok.Problems = @("the driver proof does not parse: $($_.Exception.Message)"); return $tok }
    if ([string]$p.schema -cne $script:C4DriverProofSchema) { [void]$pr.Add("the driver proof's schema is not $($script:C4DriverProofSchema)") }
    if ($p.passed -ne $true) { [void]$pr.Add('the recorded self-test did not pass') }
    if (@($p.failed_checks).Count) { [void]$pr.Add("the proof records failed checks: $((@($p.failed_checks) | Select-Object -First 3) -join '; ')") }
    if ([int]$p.checks_run -lt $script:C4MinChecks -or [int]$p.checks_passed -ne [int]$p.checks_run) { [void]$pr.Add("the proof does not record a self-test run (at least $($script:C4MinChecks) checks, all passed)") }
    $ceil = Get-C4ChecksCeiling -Path (Join-C4Path $Folder $script:C4SelfName)
    if ($ceil -le 0) { [void]$pr.Add('cannot judge whether the recorded number of checks is plausible: the driver is not in the folder') }
    elseif ([int]$p.checks_run -gt $ceil) { [void]$pr.Add("the proof claims $([int]$p.checks_run) checks but the driver has at most $ceil check sites: not a real run") }
    foreach ($t in $script:C4RequiredTags) { if (@($p.tags_passed) -notcontains $t) { [void]$pr.Add("required tag '$t' is not in the proof") } }
    try {
        $w = ConvertTo-DateTimeOffset $p.written; $tok.Written = $w; $age = ($Now - $w).TotalHours
        if ($age -gt $MaxAgeHours) { [void]$pr.Add(("the driver proof is {0:N1} h old (limit {1} h): re-run -SelfTest -WriteProof" -f $age, $MaxAgeHours)) }
        if ($age -lt -0.1) { [void]$pr.Add('the driver proof is dated in the future') }
    } catch { [void]$pr.Add('the driver proof has no readable written time') }
    $b = Get-C4BoundHashes -Folder $Folder -SelfSha $SelfSha -LoadedLibHashes $LoadedLibHashes -LoadedLibFolder $LoadedLibFolder -WrappedSha $WrappedSha
    foreach ($m in $b.Missing) { [void]$pr.Add("${m}: missing now (cannot be compared)") }
    foreach ($grp in @(@('text_sha256_lf', $b.Text), @('libraries_sha256_lf', $b.Libs), @('raw_sha256', $b.Raw))) {
        foreach ($n in $grp[1].Keys) {
            $grpObj = $p.($grp[0]); $was = if ($grpObj -and $grpObj.PSObject.Properties[$n]) { [string]$grpObj.$n } else { '' }
            if (-not $was) { [void]$pr.Add("${n}: the proof has no hash for it") }
            elseif ($was -ine $grp[1][$n]) { [void]$pr.Add(("{0}: changed since the self-test (proof {1}..., now {2}...): re-run -SelfTest -WriteProof" -f $n, $was.Substring(0, [Math]::Min(12, $was.Length)), $grp[1][$n].Substring(0, 12))) }
        }
    }
    if ($b.Wrapped -and ([string]$p.wrapped_script_sha256_lf -ine $b.Wrapped)) { [void]$pr.Add("$($script:C4WrappedName): the bytes evaluated now are not the ones the self-test evaluated") }
    $hp = Join-C4Path $Folder $script:C4HarnessProofName
    foreach ($m in @(Test-N5HarnessLiveProof -Path $hp -ExeSha $b.Raw['halfset.exe'] -RsSha $b.Raw['halfset.rs'] -Now $Now)) { [void]$pr.Add("the matrix's harness proof: $m") }
    $pv = $p.probe_version
    if (-not $pv -or [string]$pv.probe_exe_sha256 -ine [string]$b.Raw[$script:C4ProbeExeName]) { [void]$pr.Add('the proof''s probe --version hash is not the probe exe beside this script') }
    if (-not $pv -or $pv.toggle_build -ne $false) { [void]$pr.Add('the probe exe the proof names is a toggle build (or the proof does not say)') }
    if (-not $pv -or [string]$pv.probe_cs_sha256 -notmatch '^[0-9A-Fa-f]{64}$') { [void]$pr.Add('the proof records no embedded source hash of the probe') }
    if (-not $p.probe_selftest -or $p.probe_selftest.passed -ne $true) { [void]$pr.Add('the proof does not record the probe''s own self-test as passed') }
    $tok.Problems = @($pr); $tok.Ok = ($pr.Count -eq 0)
    if ($tok.Ok) {
        $script:C4ProofNonce = [guid]::NewGuid().ToString('N'); $tok.Nonce = $script:C4ProofNonce
        $tok.ProbeExeSha = $b.Raw[$script:C4ProbeExeName]; $tok.ProbeCsSha = ([string]$pv.probe_cs_sha256).ToUpperInvariant(); $tok.HarnessSha = $b.Raw['halfset.exe']; $tok.HarnessProofSha = $b.Raw[$script:C4HarnessProofName]
    }
    return $tok
}

function Test-C4ProofToken {
    # The check every add path runs on the token it was handed: the right kind, Ok, and the nonce only Test-C4DriverProof of THIS process hands out.
    param($Proof)
    return [bool]($null -ne $Proof -and $Proof.PSObject.Properties['Kind'] -and $Proof.Kind -eq 'Nep5Case4Proof' -and $Proof.PSObject.Properties['Ok'] -and $Proof.Ok -eq $true -and
                  $Proof.PSObject.Properties['Nonce'] -and $Proof.Nonce -and $script:C4ProofNonce -and ([string]$Proof.Nonce -eq $script:C4ProofNonce))
}

function Invoke-C4WriteProof {
    # Writes case4-selftest-proof.json into $Folder only when every input holds (no failed check, every tag, the libraries loaded from $Folder, every bound file present,
    # the matrix's harness proof valid NOW, the probe's --version naming this exe and its source and not a toggle build, the probe's own self-test passed); then
    # validates what it wrote and deletes it again when that fails. Both gates are parameters so a test can switch them off. @{ Written; Problems; Path; Token }.
    param([Parameter(Mandatory)][string]$Folder, [string]$SelfSha, [hashtable]$LoadedLibHashes = @{}, [string]$LoadedLibFolder, $LoadedLibPaths = @{}, [string]$WrappedSha,
          [int]$ChecksRun, [int]$ChecksPassed, [string[]]$PassedTags = @(), [string[]]$FailedChecks = @(), $ProbeVersion, $ProbeSelfTest, [string]$HostInfo = '', [datetimeoffset]$Now = [datetimeoffset]::Now,
          [scriptblock]$HarnessGate = { param($pr) @($pr).Count -eq 0 }, [scriptblock]$Validator = { param($a) Test-C4DriverProof @a })
    $pr = @()
    if (@($FailedChecks).Count) { $pr += "$(@($FailedChecks).Count) check(s) failed" }
    $miss = @($script:C4RequiredTags | Where-Object { $PassedTags -notcontains $_ }); if ($miss.Count) { $pr += "required tag(s) not passed: $($miss -join ', ')" }
    if ($ChecksRun -lt $script:C4MinChecks) { $pr += "only $ChecksRun checks ran (at least $($script:C4MinChecks))" }
    if ($ChecksPassed -ne $ChecksRun) { $pr += 'not every check passed' }
    foreach ($n in $LoadedLibPaths.Keys) { if ((Split-Path $LoadedLibPaths[$n] -Parent).TrimEnd('\') -ine $Folder.TrimEnd('\')) { $pr += "library $n was loaded from $(Split-Path $LoadedLibPaths[$n] -Parent), not from $Folder" } }
    $b = Get-C4BoundHashes -Folder $Folder -SelfSha $SelfSha -LoadedLibHashes $LoadedLibHashes -LoadedLibFolder $LoadedLibFolder -WrappedSha $WrappedSha
    foreach ($m in $b.Missing) { $pr += "${m}: missing" }
    $hp = @(Test-N5HarnessLiveProof -Path (Join-C4Path $Folder $script:C4HarnessProofName) -ExeSha $b.Raw['halfset.exe'] -RsSha $b.Raw['halfset.rs'] -Now $Now)
    if (-not (& $HarnessGate $hp)) { $pr += "the matrix's harness proof is not valid now (run spike-nep5-matrix.ps1 -SelfTest -WriteProof first): $($hp -join '; ')" }
    if (-not $ProbeVersion -or -not $ProbeVersion.Ok) { $pr += "ncoprobe.exe --version gave no usable answer: $($ProbeVersion.Problem)" }
    else {
        if ($ProbeVersion.ExeSha -ine [string]$b.Raw[$script:C4ProbeExeName]) { $pr += 'ncoprobe.exe --version names another exe hash than the file''s own bytes' }
        $csPath = Join-C4Path $Folder 'NcoProbe.cs'
        $csRaw = Get-N5RawSha256 -Path $csPath; $csLf = $(if (Test-Path -LiteralPath $csPath) { Get-NormalizedSha256 -Path $csPath })
        if ($ProbeVersion.CsSha -ine [string]$csRaw -and $ProbeVersion.CsSha -ine [string]$csLf) { $pr += 'the source hash the exe embeds is not NcoProbe.cs beside this script (raw or LF-normalised)' }
        if ($ProbeVersion.ToggleBuild -ne $false) { $pr += 'ncoprobe.exe beside this script is a TOGGLE build (it honours NCOPROBE_TOGGLE_OFF): never in the live folder' }
        if ($ProbeVersion.TraceEmpty -ne $true) { $pr += 'ncoprobe.exe --version wrote to the engine-open trace' }
    }
    if (-not $ProbeSelfTest -or $ProbeSelfTest.Passed -ne $true) { $pr += "the probe's own self-test did not pass" }
    if ($pr.Count) { return [ordered]@{ Written = $false; Problems = @($pr); Path = $null; Token = $null } }
    $obj = New-C4DriverProofObject -Bound $b -PassedTags $PassedTags -FailedChecks @() -ChecksRun $ChecksRun -ChecksPassed $ChecksPassed -ProbeVersion $ProbeVersion -ProbeSelfTest $ProbeSelfTest -HostInfo $HostInfo -When ($Now.ToString('o'))
    $path = Join-C4Path $Folder $script:C4DriverProofName
    Write-JsonGuarded -Path $path -Object $obj -Depth 10
    $v = & $Validator @{ ProofPath = $path; Folder = $Folder; SelfSha = $SelfSha; LoadedLibHashes = $LoadedLibHashes; LoadedLibFolder = $LoadedLibFolder; WrappedSha = $WrappedSha; Now = $Now }
    if (-not $v.Ok) { Remove-Item -LiteralPath $path -Force -ErrorAction SilentlyContinue; return [ordered]@{ Written = $false; Problems = @('the proof just written did not validate (removed):') + @($v.Problems); Path = $null; Token = $null } }
    return [ordered]@{ Written = $true; Problems = @(); Path = $path; Token = $v }
}

function Get-C4TrustedHarnessSha {
    # The harness exe's raw SHA-256 when it can be trusted for reads and removals (no VALID proof needed: a removal must work after an edit or after 24 h): it equals the
    # hash the driver proof or the matrix proof beside this script recorded, or the one passed with -HarnessSha256. $null otherwise.
    param([Parameter(Mandatory)][string]$ScriptDir, [string]$Override)
    $now = Get-N5RawSha256 -Path (Join-C4Path $ScriptDir 'halfset.exe')
    if (-not $now) { return $null }
    if ($Override -and $Override.ToUpperInvariant() -eq $now) { return $now }
    try { $d = ConvertFrom-C4Json -Text ([IO.File]::ReadAllText((Join-C4Path $ScriptDir $script:C4DriverProofName))); if ($d.raw_sha256 -and [string]$d.raw_sha256.'halfset.exe' -ieq $now) { return $now } } catch {}
    try { $m = ConvertFrom-C4Json -Text ([IO.File]::ReadAllText((Join-C4Path $ScriptDir $script:C4MatrixProofName))); if ([string]$m.harness.exe_sha256 -ieq $now) { return $now } } catch {}
    return $null
}

# ---- the gates every mode consults (each replaceable, so -SelfTest can switch one off and show the bad outcome is then reachable) ------------------------------
function Add-C4DefaultGates {
    param([Parameter(Mandatory)]$Ctx)
    $g = [ordered]@{
        ProofGate       = { param($t) Test-C4ProofToken $t }
        PlanGate        = { param($pl) @(Get-Nep5PlanProblems -Plan $pl) + @(Get-C4PlanProblems -Plan $pl) }
        StopGate        = { param($sw) [bool]$sw.Stop }
        CleanGate       = { param($sw, $x) [bool]$sw.Clean -and ($x.ProbeKeyPresent -eq $false) -and ($x.PubPresent -eq $false) }
        AclProblemsFn   = { param($i) Get-C4AclPlanProblems -NcoSid $i.NcoSid -NcoUse $i.NcoUse -NcoDomain $i.NcoDomain -ComputerName $i.ComputerName -OperatorSid $i.OperatorSid -OperatorGroups $i.OperatorGroups -AdminMembers $i.AdminMembers -AdminsReadable $i.AdminsReadable }
        AclReadBackGate = { param($want, $got) [bool](Compare-C4Acl -Expected $want -Actual $got).Equal }
        ExeBindGate     = { param($want, $got) [bool]($want -and $got -and ($got -ieq $want)) }
        BinAdminOnlyGate = { param($r) [bool]$r.Ok }
        RecordValidator = { param($a) @(Test-C4Record @a) }
        EvidenceGate    = { param($missing) @($missing).Count -eq 0 }
        AceRemovalGate  = { param($want, $got, $gone) Test-C4AceRemoval -Expected $want -Actual $got -GoneSids $gone }
        FinishSweepGate = { param($sw, $pk) [bool]$sw.Clean -and ($pk -eq $false) }
        Plan            = $null
    }
    foreach ($k in $g.Keys) { $Ctx | Add-Member -NotePropertyName $k -NotePropertyValue $g[$k] -Force }
}

# ---- shared mode helpers ------------------------------------------------------------------------------------------------------------------------------------
function Save-C4Record {
    # Writes a record into the admin-only out dir through the context's file seam and gives it to Administrators as owner; a failure is printed and
    # returned, never swallowed. The owner is set explicitly because a new file is otherwise owned by the writing token's default owner, which on some
    # sessions is the user's own SID (README, departure 1): a file so owned makes the out dir read non-admin-only, after which -Prepare refuses, -Collect
    # skips the engine enumeration (exit 21) and -Finish falls back to its own engine. The copies -Collect writes get the same owner (Invoke-C4Collect).
    param([Parameter(Mandatory)]$Ctx, [Parameter(Mandatory)][string]$Name, [Parameter(Mandatory)]$Object)
    $p = Join-C4Path $Ctx.OutDir $Name
    try { $Ctx.Fs.WriteJson($p, $Object) } catch { Write-C4 "COULD NOT WRITE the record ${p}: $($_.Exception.Message)" 'Red'; return $null }
    try { $Ctx.Fs.SetOwnerAdmins($p) } catch { Write-C4 "the record ${p} was written but its owner could not be set to Administrators: $($_.Exception.Message) (the out dir may no longer read admin-only)" 'Red'; return $null }
    Write-C4 "record written: $p" 'DarkGray'; return $p
}

function Write-C4ManualRollback {
    param([Parameter(Mandatory)]$Ctx)
    Write-C4 '--- manual rollback (an elevated PowerShell 7; needs no file from this folder): it enumerates every filter, deletes those under S1/S2/S3 by key (the probe''s key lies in S2), REPORTS any other filter of ours or srt-win''s, then deletes the three sublayers and the provider ---' 'Yellow'
    foreach ($l in ($script:N5ManualRollbackSnippet -split "`r?`n")) { Write-C4 "    $l" 'Yellow' }
    Write-C4 "  then: the public folder $($Ctx.PubRoot) by hand (copy drop\ first; the out dir keeps the records -Collect copied)." 'Yellow'
}

function Write-C4RunSheet {
    param([Parameter(Mandatory)]$Ctx)
    Write-C4 '--- the probe command lines (RUN_SHEET.md holds each launch line verbatim; every run writes one record into drop\) ---' 'Cyan'
    foreach ($l in (Get-C4RunSheetLines -BinDir $Ctx.BinDir -DropDir $Ctx.DropDir)) { Write-C4 ("  [{0}] {1}" -f $l.cond, $l.how) 'Cyan'; Write-C4 ("      {0}" -f $l.command) }
}

function Get-C4LatestPrepare {
    # The latest successful prepare record in the out dir (written by this driver, admin-only), chosen by the UTC instant it records (`at`), never by its file
    # name (a local-time stamp, which a timezone change reorders). @{ Ok; Record; Name; Problem }.
    param([Parameter(Mandatory)]$Ctx)
    $best = $null; $bestAt = $null; $bestName = $null
    foreach ($n in @(@($Ctx.Fs.ListFiles($Ctx.OutDir, 'case4-prepare-*.json')) | Where-Object { $_ -and -not $_.IsLink -and -not $_.IsDir })) {
        try {
            $r = ConvertFrom-C4Json -Text ($Ctx.Fs.ReadText($n.FullName))
            if ($r.kind -ne 'nep5-case4-prepare' -or $r.ok -ne $true) { continue }
            $at = ConvertTo-DateTimeOffset $r.at
            if ($null -eq $bestAt -or $at.UtcDateTime -gt $bestAt.UtcDateTime) { $best = $r; $bestAt = $at; $bestName = $n.Name }
        } catch {}
    }
    if ($best) { return [ordered]@{ Ok = $true; Record = $best; Name = $bestName; Problem = '' } }
    return [ordered]@{ Ok = $false; Record = $null; Name = $null; Problem = "no successful case4-prepare-*.json in $($Ctx.OutDir)" }
}

function Invoke-C4Rollback {
    # After a failed -Prepare: the public folder (when this run created it), the probe's key, everything in S1/S2/S3 and our provider by key, then the direct sweep.
    param([Parameter(Mandatory)]$Ctx, $Backend, $Runner, [bool]$RemoveFolder)
    $steps = @()
    if ($RemoveFolder -and $Ctx.Fs.Exists($Ctx.PubRoot)) { try { $Ctx.Fs.RemoveTree($Ctx.PubRoot); $steps += "public folder removed" } catch { $steps += "public folder NOT removed: $($_.Exception.Message)" } }
    $pk = 'error: no backend'; if ($Backend) { try { $pk = [string]$Backend.Delete('filter', $script:C4ProbeKey) } catch { $pk = "error: $($_.Exception.Message)" } }
    $steps += "probe key: $pk"
    $rm = $null; if ($Runner -and $Backend) { $rm = Remove-Nep5All -Runner $Runner -Backend $Backend }
    $sw = Invoke-Nep5DirectSweep -Runner $Runner -Backend $Backend -Exporter $Ctx.Exporter -Label 'rollback' -NoHarness:(-not $Runner)
    $pkNow = Get-C4KeyState -Backend $Backend
    $ok = [bool]$sw.Clean -and ($pkNow -eq $false) -and -not ($RemoveFolder -and $Ctx.Fs.Exists($Ctx.PubRoot))
    return [ordered]@{ Ok = $ok; Steps = $steps; Removal = $(if ($rm) { [ordered]@{ ok = $rm.Ok; steps = @($rm.Steps) } }); Sweep = (Get-C4SweepSummary $sw); ProbeKeyPresent = $pkNow }
}

# ---- -DryRun --------------------------------------------------------------------------------------------------------------------------------------------------
function Invoke-C4DryRun {
    param([Parameter(Mandatory)]$Ctx)
    Write-C4 '== DRY RUN: nothing is added; no WFP engine is opened; nothing is written ==' 'Yellow'
    Write-C4 ("S2 {0} (the only sublayer case 4 adds); our provider {1}; the probe's filter key {2} (layer ALE_AUTH_CONNECT_V4 {3}, BLOCK, user condition for the stale SID {4})" -f $script:N5SubLayers.S2, $script:N5ProviderKey, $script:C4ProbeKey, $script:N5LayerV4, $script:N5StaleSid)
    Write-C4 ("public folder {0}; bin {1}; drop {2}; out dir {3}" -f $Ctx.PubRoot, $Ctx.BinDir, $Ctx.DropDir, $Ctx.OutDir)
    $op = & $Ctx.OperatorToken
    $nco = $Ctx.Acct.Lookup($script:C4Account); $adm = $Ctx.Acct.MemberSids($script:C4AdminsSid)
    Write-C4 ("operator SID {0}; '{1}' resolves to {2} (domain {3}, SID_NAME_USE {4}, error {5}); Administrators readable {6}" -f $op.User, $script:C4Account, $nco.Sid, $nco.Domain, $nco.Use, $nco.Error, $adm.Ok)
    $acl = Get-C4AclPlan -NcoSid $nco.Sid -NcoUse ([int]$nco.Use) -NcoDomain $nco.Domain -ComputerName $Ctx.ComputerName -OperatorSid $op.User -OperatorGroups @($op.Groups) -AdminMembers @($adm.Sids) -AdminsReadable ([bool]$adm.Ok) -ProblemsFn $Ctx.AclProblemsFn
    Write-C4 '--- the ACL plan for the public folder (protected DACLs; -Prepare reads each back and compares) ---' 'Cyan'
    if ($acl.Ok) { foreach ($k in $acl.Sddl.Keys) { Write-C4 ("  {0,-5} {1}" -f $k, $acl.Sddl[$k]); foreach ($r in $acl.Rows[$k]) { Write-C4 ("          {0} {1}" -f $r.sid, $r.rights) } } }
    else { foreach ($m in @($acl.Stop)) { Write-C4 "  -Prepare would STOP (9): $m" 'Red' }; foreach ($m in @($acl.Refuse)) { Write-C4 "  -Prepare would REFUSE (2): $m" 'Yellow' } }
    Write-C4 '--- the driver proof -Prepare requires ---' 'Cyan'
    $tok = & $Ctx.ProofCheck $Ctx
    if ($tok.Ok) { Write-C4 "  VALID (written $($tok.Written)): every bound file, library, the wrapped script, the probe exe, the harness and its proof match." 'Green' }
    else { foreach ($m in @($tok.Problems)) { Write-C4 "  NO VALID PROOF: $m" 'Yellow' }; Write-C4 '  -Prepare would REFUSE until -SelfTest -WriteProof has passed on these exact files.' 'Yellow' }
    $exeSha = $Ctx.Fs.Sha256Raw($Ctx.ProbeExeSrc)
    $cs = if ($tok.Ok) { $tok.ProbeCsSha } else { try { [string](Get-C4Field (ConvertFrom-C4Json -Text ([IO.File]::ReadAllText($Ctx.DriverProofPath))) 'probe_version.probe_cs_sha256') } catch { '' } }
    Write-C4 "--- the probe proof -Prepare would write to $(Join-C4Path $Ctx.BinDir $script:C4ProbeProofName) (written_utc = the moment of -Prepare) ---" 'Cyan'
    if ($exeSha -and $cs) { Write-C4 (ConvertTo-Json -InputObject (New-C4ProbeProof -ExeSha $exeSha -CsSha $cs -Now (& $Ctx.Now)) -Depth 4) }
    else { Write-C4 ("  probe exe beside this script: {0}; embedded source hash from the driver proof: {1}" -f $(if ($exeSha) { $exeSha } else { 'MISSING' }), $(if ($cs) { $cs } else { 'none yet' })) 'Yellow' }
    Write-C4 '--- -Prepare, in this order (each refusal adds nothing) ---' 'Cyan'
    foreach ($l in @('elevated and 64-bit; the scripts folder and the out dir admin-only; the driver proof valid (a per-process token)',
                     "the stale SID must NOT resolve; '$($script:C4Account)' must resolve to a local user that is not the operator, not in his token and not in Administrators (else STOP 9)",
                     'the direct sweep reads CLEAN (S1/S2/S3 absent and empty, provider absent, export 0 hits), the probe key absent, the public folder absent (a foreign filter is STOP 9)',
                     'netsh wfp show security type=engine (recorded; unreadable = refusal), and the filter, sublayer and provider containers (recorded)',
                     "ONE transaction: provider $($script:N5ProviderKey) and S2 $($script:N5SubLayers.S2) naming it, persistent, NO filter (the library's proof-gated adder; read back)",
                     'netsh wfp show security type=sublayer guid=<S2> (braces first, then without; every attempt recorded) and the provider object',
                     'the public folder: root, bin\ and drop\ created WITH the planned owner (Administrators) and DACL, each read back and compared',
                     "the probe exe copied into bin\ and hash-checked against the driver proof; the probe proof written and read back; both owned by Administrators; bin\ must read admin-only for writes",
                     'case4-prepare-<stamp>.json into the out dir; the run sheet lines printed')) { Write-C4 "  * $l" }
    Write-C4 '--- -Collect: every file in drop\ copied into <out>\case4-runs\; each case4-*.json validated (schema, run of a non-toggle build, exe, source and proof hashes, cond, account, clock window, own name and stamp, no duplicate pid+stamp, classes, overall, residue, exit); S2 read for a filter left behind; a table per condition ---' 'Cyan'
    Write-C4 '--- -Finish: -Collect; the probe key, the library keys, S2 and the provider removed by key; the sweep must read clean (else 7 and the manual rollback); the engine SD compared; drop\ ACEs of the account and the operator removed and read back; the folder deleted ---' 'Cyan'
    Write-C4 "--- -PartD (after part C): net user $($script:C4Account) must say 'could not be found', net localgroup of S-1-5-32-556 must not list it, its profile folder must be gone ---" 'Cyan'
    Write-C4RunSheet -Ctx $Ctx
    Write-C4ManualRollback -Ctx $Ctx
    Write-C4 'DRY RUN complete. Nothing was added or written.' 'Green'
    return 0
}

# ---- -Check ---------------------------------------------------------------------------------------------------------------------------------------------------
function Invoke-C4Check {
    param([Parameter(Mandatory)]$Ctx)
    if (-not (& $Ctx.IsElevated)) { Write-C4 'UNREADABLE: not elevated, so the engine cannot be read.' 'Red'; return 22 }
    $ao = & $Ctx.AdminOnly $Ctx.ScriptDir
    $runner = if ($ao.Ok) { & $Ctx.NewRunner (& $Ctx.TrustedHarnessSha) } else { $null }
    $be = $null; $sw = $null; $pk = $null
    try { $be = & $Ctx.NewBackend } catch { Write-C4 "engine: could not be opened ($($_.Exception.Message))" 'Yellow' }
    try {
        if ($be) { $sw = Invoke-Nep5DirectSweep -Runner $runner -Backend $be -Exporter $Ctx.Exporter -Label 'check' -NoHarness:(-not $runner); $pk = Get-C4KeyState -Backend $be }
    } finally { if ($be) { try { $be.Close() } catch {} } }
    if (-not $sw) { $sw = [pscustomobject]@{ Stop = $false; Clean = $false; Unreadable = $true; NotClean = @(); Problems = @('the engine could not be read') } }
    if (-not $runner) { Write-C4 'harness: not trusted here (the folder is not admin-only, or the exe is not the one a proof recorded): enumeration skipped, so a foreign filter cannot be seen.' 'Yellow' }
    $pub = $null; $dropN = $null; try { $pub = [bool]$Ctx.Fs.Exists($Ctx.PubRoot); if ($pub) { $dropN = @($Ctx.Fs.ListFiles($Ctx.DropDir, '*')).Count } else { $dropN = 0 } } catch {}
    $nu = $Ctx.Acct.NetUser($script:C4Account); $us = Get-C4NetUserState -ExitCode $nu.Exit -Text $nu.Text
    $acct = switch ($us) { 'present' { $true } 'absent' { $false } default { $null } }
    $gname = $Ctx.Acct.GroupName($script:C4NcoGroupSid); $members = $null
    if ($gname) { $ng = $Ctx.Acct.NetLocalGroup(($gname -replace '^.*\\', '')); $members = ConvertFrom-C4NetLocalGroup -Text $ng.Text -ExitCode $ng.Exit }
    $mem = if ($null -eq $members) { $null } else { Test-C4MemberListed -Members $members }
    $prof = $Ctx.Acct.PathExists($Ctx.Acct.ProfileDir($script:C4Account))
    if ($sw.SubLayers) { foreach ($id in @($sw.SubLayers.Keys)) { $s = $sw.SubLayers[$id]; Write-C4 ("  {0}: {1} filter(s); present {2}" -f $id, @($s.filter_keys).Count, $s.present) } }
    Write-C4 ("  provider present {0}; probe key present {1}; export hits {2}" -f $sw.ProviderPresent, $pk, $(if ($sw.Export -and $sw.Export.hits) { $sw.Export.hits.total } else { 'n/a' }))
    foreach ($m in @($sw.NotClean) + @($sw.Problems)) { Write-C4 "  ! $m" 'Yellow' }
    Write-C4 ("  public folder present {0}; files in drop {1}; account '{2}' {3}; member of S-1-5-32-556 {4}; profile folder present {5}" -f $pub, $dropN, $script:C4Account, $us, $mem, $prof)
    $code = Get-C4CheckExit -Sweep $sw -ProbeKeyPresent $pk -PubPresent $pub -AccountPresent $acct -MemberPresent $mem -ProfilePresent $prof -HarnessTrusted ([bool]$runner)
    Write-C4 ("CHECK exit {0}: {1}" -f $code, $(switch ($code) { 20 { 'everything reads absent' } 21 { 'something is present (see above)' } default { 'something could not be read' } })) $(if ($code -eq 20) { 'Green' } else { 'Yellow' })
    return $code
}

# ---- -Prepare -------------------------------------------------------------------------------------------------------------------------------------------------
$script:C4MatrixFiles = @('spike-nep5-matrix.ps1', 'spike-nep5-lib.ps1', 'spike-nep5-run-lib.ps1', 'spike-nep5-connect-probe.ps1', 'halfset.exe')

function Invoke-C4Prepare {
    # The -Prepare entry. An error that escapes the steps is classified by whether the add had started: before it, nothing can be in the engine (exit 2, the
    # manual rollback printed for reference); after it, the state is not verified (exit 7). Exit 7 means only that.
    param([Parameter(Mandatory)]$Ctx)
    $script:C4PrepAddStarted = $false
    try { return (Invoke-C4PrepareSteps -Ctx $Ctx) }
    catch {
        Write-C4 "ERROR: $($_.Exception.Message)" 'Red'
        if ($script:C4PrepAddStarted) { Write-C4 'The error came after the add started and its rollback did not complete: NOT VERIFIED. Run the manual rollback, then -Check.' 'Red'; Write-C4ManualRollback -Ctx $Ctx; return 7 }
        Write-C4 'REFUSED: the error came before the add (nothing was added to the engine and no folder was made). The manual rollback below is for reference only.' 'Red'
        Write-C4ManualRollback -Ctx $Ctx
        return 2
    }
}

function Invoke-C4PrepareSteps {
    param([Parameter(Mandatory)]$Ctx)
    $now = & $Ctx.Now; $stamp = $now.ToString('yyyyMMdd-HHmmss')
    $rec = [ordered]@{ kind = 'nep5-case4-prepare'; schema = 1; ok = $false; at = $now.ToString('o'); stamp = $stamp; error = $null; proof = $null; nco_sid = $null; operator_sid = $null
                       nco = $null; acl_plan = $null; sweep = $null; probe_key_before = $null; security = [ordered]@{}; add = $null; public = [ordered]@{}; probe_exe_sha256 = $null; probe_cs_sha256 = $null
                       probe_proof = $null; rollback = $null; run_sheet = @(); matrix_sha256 = [ordered]@{} }
    if (-not (& $Ctx.IsElevated)) { Write-C4 'REFUSED: not elevated (nothing added).' 'Red'; return 2 }
    if (-not (& $Ctx.Is64Bit)) { Write-C4 'REFUSED: not a 64-bit process (WFP struct layout is asserted for x64).' 'Red'; return 2 }
    $ao = & $Ctx.AdminOnly $Ctx.ScriptDir
    if (-not $ao.Ok) { Write-C4 "REFUSED: $($Ctx.ScriptDir) is not admin-only: $(@($ao.Problems | Select-Object -First 2) -join '; ')" 'Red'; return 2 }
    try { $Ctx.Fs.EnsureDir($Ctx.OutDir) } catch { Write-C4 "REFUSED: the out dir $($Ctx.OutDir) could not be made: $($_.Exception.Message)" 'Red'; return 2 }
    $ao2 = & $Ctx.AdminOnly $Ctx.OutDir
    if (-not $ao2.Ok) { Write-C4 "REFUSED: the out dir $($Ctx.OutDir) is not admin-only: $(@($ao2.Problems | Select-Object -First 2) -join '; ')" 'Red'; return 2 }
    $tok = & $Ctx.ProofCheck $Ctx
    if (-not (& $Ctx.ProofGate $tok)) { foreach ($m in @($tok.Problems)) { Write-C4 "REFUSED: $m" 'Red' }; Write-C4 'REFUSED: no valid driver proof (nothing added).' 'Red'; return 2 }
    $rec.proof = [ordered]@{ written = [string]$tok.Written; probe_exe_sha256 = $tok.ProbeExeSha; probe_cs_sha256 = $tok.ProbeCsSha; harness_sha256 = $tok.HarnessSha; harness_proof_sha256 = $tok.HarnessProofSha }
    foreach ($n in $script:C4MatrixFiles) {
        $h = $Ctx.Fs.Sha256Raw((Join-C4Path $Ctx.ScriptDir $n)); $rec.matrix_sha256[$n] = $h
        if ($h) { Write-C4 ("live matrix file {0}  sha256 {1}" -f $n, $h.ToLowerInvariant()) } else { Write-C4 "WARNING: the live matrix file $n is not beside this script; its hash is recorded as missing." 'Yellow' }
    }
    $script:N5LiveProof = $Ctx.HarnessProofPath
    $op = & $Ctx.OperatorToken; $rec.operator_sid = $op.User
    $staleProblems = @(Get-Nep5SidProblems -Sid $script:N5StaleSid -OperatorSid $op.User -OperatorGroups @($op.Groups) -Resolve $Ctx.SidResolver)
    if ($staleProblems.Count) { foreach ($m in $staleProblems) { Write-C4 "REFUSED: $m" 'Red' }; return 2 }
    $nco = $Ctx.Acct.Lookup($script:C4Account); $adm = $Ctx.Acct.MemberSids($script:C4AdminsSid); $ncoMembers = $Ctx.Acct.MemberSids($script:C4NcoGroupSid)
    $rec.nco = [ordered]@{ lookup = $nco; administrators_readable = $adm.Ok; network_configuration_operators = $ncoMembers }
    $acl = Get-C4AclPlan -NcoSid $nco.Sid -NcoUse ([int]$nco.Use) -NcoDomain $nco.Domain -ComputerName $Ctx.ComputerName -OperatorSid $op.User -OperatorGroups @($op.Groups) -AdminMembers @($adm.Sids) -AdminsReadable ([bool]$adm.Ok) -ProblemsFn $Ctx.AclProblemsFn
    $rec.acl_plan = [ordered]@{ ok = $acl.Ok; refuse = @($acl.Refuse); stop = @($acl.Stop); sddl = $acl.Sddl }
    if (@($acl.Stop).Count) {
        foreach ($m in @($acl.Stop)) { Write-C4 "STOP: $m" 'Red' }
        Write-C4 'STOP: nothing was added. The account must not be the operator, in his token or in Administrators.' 'Red'
        [void](Save-C4Record -Ctx $Ctx -Name "case4-prepare-$stamp.json" -Object $rec); Write-C4ManualRollback -Ctx $Ctx; return 9
    }
    if (-not $acl.Ok) { foreach ($m in @($acl.Refuse)) { Write-C4 "REFUSED: $m" 'Red' }; [void](Save-C4Record -Ctx $Ctx -Name "case4-prepare-$stamp.json" -Object $rec); return 2 }
    $rec.nco_sid = $nco.Sid
    if ($ncoMembers.Ok -and @($ncoMembers.Sids) -notcontains $nco.Sid) { Write-C4 "WARNING: '$($script:C4Account)' is not a member of Network Configuration Operators now; the records will show the token as it is." 'Yellow' }
    $be = $null; $runner = $null; $created = $false; $added = $false; $addStarted = $false
    try {
        $be = & $Ctx.NewBackend
        $runner = & $Ctx.NewRunner $tok.HarnessSha
        $sw = Invoke-Nep5DirectSweep -Runner $runner -Backend $be -Exporter $Ctx.Exporter -Label 'prepare-before'
        $pk = Get-C4KeyState -Backend $be; $pub = [bool]$Ctx.Fs.Exists($Ctx.PubRoot)
        $rec.sweep = Get-C4SweepSummary $sw; $rec.probe_key_before = $pk; $rec.public.present_before = $pub
        if (& $Ctx.StopGate $sw) {
            foreach ($m in @($sw.Problems)) { Write-C4 "STOP: $m" 'Red' }
            Write-C4 'STOP: a filter of ours or srt-win''s sits outside S1/S2/S3. Nothing was added and nothing is removed by this mode.' 'Red'
            Write-C4ManualRollback -Ctx $Ctx; [void](Save-C4Record -Ctx $Ctx -Name "case4-prepare-$stamp.json" -Object $rec); return 9
        }
        if (-not (& $Ctx.CleanGate $sw ([pscustomobject]@{ ProbeKeyPresent = $pk; PubPresent = $pub }))) {
            foreach ($m in @($sw.NotClean) + @($sw.Problems)) { Write-C4 "REFUSED: $m" 'Red' }
            if ($pk -ne $false) { Write-C4 "REFUSED: the probe's filter key reads $(if ($null -eq $pk) { 'UNREADABLE' } else { 'PRESENT' })" 'Red' }
            if ($pub) { Write-C4 "REFUSED: the public folder $($Ctx.PubRoot) already exists" 'Red' }
            Write-C4 'REFUSED: the engine or the folder does not read clean (stale objects); run -Finish or the manual rollback first. Nothing was added.' 'Red'
            [void](Save-C4Record -Ctx $Ctx -Name "case4-prepare-$stamp.json" -Object $rec); return 2
        }
        $eng = & $Ctx.ReadWfpSecurity 'engine' $null
        $rec.security.engine = $eng
        if (-not $eng.ok) { Write-C4 'REFUSED: netsh wfp show security type=engine gave no security descriptor (it is the -Finish comparison''s baseline). Nothing was added.' 'Red'; [void](Save-C4Record -Ctx $Ctx -Name "case4-prepare-$stamp.json" -Object $rec); return 2 }
        $rec.security.containers = [ordered]@{ filter = (& $Ctx.ReadWfpSecurity 'filter' $null); sublayer = (& $Ctx.ReadWfpSecurity 'sublayer' $null); provider = (& $Ctx.ReadWfpSecurity 'provider' $null) }
        $plan = if ($Ctx.Plan) { $Ctx.Plan } else { Get-C4PrepPlan }
        $addStarted = $true; $script:C4PrepAddStarted = $true
        $add = Add-Nep5OurPlan -Runner $runner -Backend $be -Plan $plan -SidProblems $staleProblems -Proof $tok -ProofValidator $Ctx.ProofGate -PlanGate $Ctx.PlanGate
        $rec.add = [ordered]@{ ok = $add.Ok; refused = $add.Refused; reason = $add.Reason; rollback = $(if ($add.Rollback) { [ordered]@{ ok = $add.Rollback.Ok; steps = @($add.Rollback.Steps) } }) }
        if ($add.Refused) { Write-C4 "REFUSED: $($add.Reason)" 'Red'; [void](Save-C4Record -Ctx $Ctx -Name "case4-prepare-$stamp.json" -Object $rec); return 2 }
        if (-not $add.Ok) {
            $rbOk = [bool]($add.Rollback -and $add.Rollback.Ok)
            Write-C4 "FAILED: $($add.Reason); the rollback by key read back clean: $rbOk" $(if ($rbOk) { 'Yellow' } else { 'Red' })
            if (-not $rbOk) { Write-C4ManualRollback -Ctx $Ctx }
            [void](Save-C4Record -Ctx $Ctx -Name "case4-prepare-$stamp.json" -Object $rec); return $(if ($rbOk) { 2 } else { 7 })
        }
        $added = $true
        Write-C4 "added: provider $($script:N5ProviderKey) and S2 $($script:N5SubLayers.S2) (no filter); read back." 'Green'
        $rec.security.s2 = & $Ctx.ReadWfpSecurity 'sublayer' $script:N5SubLayers.S2
        $rec.security.provider_object = & $Ctx.ReadWfpSecurity 'provider' $script:N5ProviderKey
        if (-not $rec.security.s2.ok) { Write-C4 "WARNING: no form of netsh wfp show security type=sublayer gave S2's security descriptor; every attempt is in the record." 'Yellow' }
        else { Write-C4 "S2 security descriptor read with: $($rec.security.s2.command)" }
        foreach ($d in @(@('root', $Ctx.PubRoot), @('bin', $Ctx.BinDir), @('drop', $Ctx.DropDir))) {
            $Ctx.Fs.NewProtectedDir($d[1], $acl.Sddl[$d[0]]); $created = $true
            $got = $Ctx.Fs.GetSddl($d[1])
            $rec.public[$d[0]] = [ordered]@{ path = $d[1]; planned = $acl.Sddl[$d[0]]; read_back = $got }
            if (-not (& $Ctx.AclReadBackGate $acl.Sddl[$d[0]] $got)) { throw "the DACL read back from $($d[1]) is not the plan ($((Compare-C4Acl -Expected $acl.Sddl[$d[0]] -Actual $got).Reason))" }
        }
        $dst = Join-C4Path $Ctx.BinDir $script:C4ProbeExeName
        $Ctx.Fs.CopyFile($Ctx.ProbeExeSrc, $dst); $Ctx.Fs.SetOwnerAdmins($dst)
        $exeNow = $Ctx.Fs.Sha256Raw($dst); $rec.probe_exe_sha256 = $exeNow; $rec.probe_cs_sha256 = $tok.ProbeCsSha
        if (-not (& $Ctx.ExeBindGate $tok.ProbeExeSha $exeNow)) { throw "the probe exe copied into bin hashes $exeNow, not the $($tok.ProbeExeSha) the driver proof verified" }
        $pp = New-C4ProbeProof -ExeSha $tok.ProbeExeSha -CsSha $tok.ProbeCsSha -Now (& $Ctx.Now)
        $pp1 = @(Test-C4ProbeProof -Proof $pp -ExeSha $tok.ProbeExeSha -CsSha $tok.ProbeCsSha -Now (& $Ctx.Now))
        if ($pp1.Count) { throw "the probe proof this driver built does not pass the probe's own rules: $($pp1 -join '; ')" }
        $ppPath = Join-C4Path $Ctx.BinDir $script:C4ProbeProofName
        $Ctx.Fs.WriteJson($ppPath, $pp); $Ctx.Fs.SetOwnerAdmins($ppPath)
        $back = ConvertFrom-C4Json -Text ((New-Object Text.UTF8Encoding($false, $true)).GetString([byte[]]$Ctx.Fs.ReadBytes($ppPath, $script:C4MaxRecordBytes)).TrimStart([char]0xFEFF))
        $pp2 = @(Test-C4ProbeProof -Proof $back -ExeSha $tok.ProbeExeSha -CsSha $tok.ProbeCsSha -Now (& $Ctx.Now))
        if ($pp2.Count) { throw "the probe proof read back from bin\ does not pass: $($pp2 -join '; ')" }
        $rec.probe_proof = [ordered]@{ path = $ppPath; content = $pp; sha256 = $Ctx.Fs.Sha256Raw($ppPath) }
        $bao = & $Ctx.AdminOnly $Ctx.BinDir
        $rec.public.bin_admin_only = [ordered]@{ ok = [bool]$bao.Ok; problems = @($bao.Problems); checked = $bao.Checked }
        if (-not (& $Ctx.BinAdminOnlyGate $bao)) { throw "bin\ is not admin-only for writes (condition A runs its exe elevated): $(@($bao.Problems | Select-Object -First 3) -join '; ')" }
        $rec.run_sheet = @(Get-C4RunSheetLines -BinDir $Ctx.BinDir -DropDir $Ctx.DropDir)
        $rec.ok = $true
        # The prepare record is what -Collect validates every run against: no record on disk and read back, no PREPARED (the add is rolled back instead).
        $saved = Save-C4Record -Ctx $Ctx -Name "case4-prepare-$stamp.json" -Object $rec
        if (-not $saved) { throw "the prepare record case4-prepare-$stamp.json could not be written" }
        $reread = $null; try { $reread = ConvertFrom-C4Json -Text ($Ctx.Fs.ReadText($saved)) } catch { $reread = $null }
        if (-not $reread -or $reread.ok -ne $true -or [string]$reread.stamp -cne $stamp -or [string]$reread.nco_sid -cne [string]$nco.Sid -or [string]$reread.probe_proof.sha256 -ine [string]$rec.probe_proof.sha256) { throw "the prepare record $saved did not read back as written" }
        Write-C4 "PREPARED: provider and S2 in place (no filter), the public folder made with its planned DACLs, the probe exe and its proof in bin\, the prepare record on disk and read back ($saved)." 'Green'
        Write-C4 "The probe proof expires 24 h after $($pp.written_utc); every run must finish before then." 'Yellow'
        Write-C4RunSheet -Ctx $Ctx
        return 0
    } catch {
        $rec.ok = $false; $rec.error = $_.Exception.Message
        Write-C4 "FAILED: $($_.Exception.Message)" 'Red'
        $code = 2
        if ($addStarted -or $created) {
            $rb = Invoke-C4Rollback -Ctx $Ctx -Backend $be -Runner $runner -RemoveFolder $created
            $rec.rollback = $rb
            Write-C4 ("rolled back: public folder, the probe key, S1/S2/S3 and the provider by key; direct read-back clean: {0}" -f $rb.Ok) $(if ($rb.Ok) { 'Yellow' } else { 'Red' })
            if (-not $rb.Ok) { Write-C4ManualRollback -Ctx $Ctx; $code = 7 }
        } else {
            Write-C4 'Nothing was added (the error came before the add). The manual rollback below is for reference only.' 'Yellow'
            Write-C4ManualRollback -Ctx $Ctx
        }
        [void](Save-C4Record -Ctx $Ctx -Name "case4-prepare-$stamp.json" -Object $rec)
        return $code
    } finally { if ($be) { try { $be.Close() } catch {} } }
}

# ---- -Collect -------------------------------------------------------------------------------------------------------------------------------------------------
function Invoke-C4Collect {
    # Copies and validates every entry of drop\, reads the engine for what is left behind, prints the table. Returns the result object (Code is the exit code).
    # Every entry is accounted for: a sub-folder is refused (its contents are never read or copied, and -Finish keeps the public folder while it is there), a link
    # is listed and not followed, a file whose name is not a record name is listed AND still checked for the wrong-principal STOP when it parses as JSON.
    # Each file's sha256 is printed and recorded with its copy in case4-runs\ (the probe prints its record, not a hash: the record-tamper limit, README).
    param([Parameter(Mandatory)]$Ctx, $Backend, $Runner, [switch]$RunnerGiven, [string]$ElevationRefusedNote)
    $res = [ordered]@{ Code = 2; Prepare = $null; Valid = @(); Invalid = @(); WrongAccount = @(); ProbeStops = @(); ProbeLeft = @(); Copies = @(); Uncopied = @(); LeftBehind = @(); Foreign = @(); ResidueReadable = $false; Rows = @(); RecordPath = $null
                       EElevated = @(); ElevationRefused = $null }
    if (-not (& $Ctx.IsElevated)) { Write-C4 'REFUSED: not elevated (the out dir is admin-only and the engine is read).' 'Red'; return [pscustomobject]$res }
    $now = & $Ctx.Now; $stamp = $now.ToString('yyyyMMdd-HHmmss')
    $prep = Get-C4LatestPrepare -Ctx $Ctx; $res.Prepare = [ordered]@{ ok = $prep.Ok; name = $prep.Name; problem = $prep.Problem }
    if (-not $prep.Ok) { Write-C4 "WARNING: $($prep.Problem): every record is listed invalid (nothing to validate it against); the files are still copied." 'Yellow' }
    $pr = $prep.Record
    $start = $null; if ($prep.Ok) { try { $start = (ConvertTo-DateTimeOffset $pr.at).AddMinutes(-$script:C4ClockSkewMinutes) } catch { $start = $null } }
    $end = $now.AddMinutes($script:C4ClockSkewMinutes)
    $seen = @{}
    $invalid = { param($name, $kind, $why) $res.Invalid += , ([ordered]@{ file = $name; kind = $kind; reasons = @($why) }) }
    # The copies folder is a new folder in the admin-only out dir: created through the seam and given to Administrators as owner, as the records are
    # (README, departure 1); the record names the owner it got, and a failure is printed, never swallowed.
    $runsDir = Join-C4Path $Ctx.OutDir 'case4-runs'; $res.CopiesFolderOwner = 'not set'
    try { $Ctx.Fs.EnsureDir($runsDir); $Ctx.Fs.SetOwnerAdmins($runsDir); $res.CopiesFolderOwner = $script:C4AdminsSid }
    catch { $res.CopiesFolderOwner = "error: $($_.Exception.Message)"; Write-C4 "the copies folder ${runsDir} could not be given to Administrators as owner: $($_.Exception.Message) (the out dir may no longer read admin-only)" 'Red' }
    $files = @(@($Ctx.Fs.ListFiles($Ctx.DropDir, '*')) | Where-Object { $_ } | Sort-Object Name)
    foreach ($f in $files) {
        $reasons = @(); $sha = $null; $copy = $null; $obj = $null
        if ($f.IsLink) { & $invalid $f.Name 'link' 'a link in drop\ (not followed or read; -Finish removes it as a link, never its target)'; continue }
        if ($f.IsDir) { & $invalid $f.Name 'sub-folder' 'a sub-folder in drop\: refused (the probe writes only files; its contents are never read or copied, so -Finish keeps the public folder until it is removed by hand)'; $res.Uncopied += $f.Name; continue }
        [byte[]]$bytes = $null
        try { $bytes = $Ctx.Fs.ReadBytes($f.FullName, $script:C4MaxRecordBytes) } catch { & $invalid $f.Name 'unreadable' "unreadable: $($_.Exception.Message)"; $res.Uncopied += $f.Name; continue }
        $sha = Get-C4BytesSha $bytes
        $copyPath = Join-C4Path $runsDir $f.Name
        try { $copy = [string]$Ctx.Fs.WriteBytesOnce($copyPath, $bytes) } catch { $copy = "error: $($_.Exception.Message)" }
        if ($copy -in @('written', 'exists-same')) {
            # Each copy is a new file in the admin-only out dir: Administrators as owner, as for the records. A copy whose owner cannot be set is not counted as copied.
            try { $Ctx.Fs.SetOwnerAdmins($copyPath) } catch { $copy = "$copy, owner not set: $($_.Exception.Message)"; Write-C4 "the copy ${copyPath} was written but its owner could not be set to Administrators: $($_.Exception.Message) (the out dir may no longer read admin-only)" 'Red' }
        }
        $res.Copies += , ([ordered]@{ file = $f.Name; sha256 = $sha.ToLowerInvariant(); status = $copy })
        if ($copy -notin @('written', 'exists-same')) { $reasons += "copy into case4-runs: $copy"; $res.Uncopied += $f.Name }
        try { $obj = ConvertFrom-C4Json -Text ((New-Object Text.UTF8Encoding($false, $true)).GetString($bytes).TrimStart([char]0xFEFF)) } catch { $obj = $null }
        if ($null -ne $obj) {
            if (Test-C4WrongAccountAdd -Record $obj -NcoSid $(if ($prep.Ok) { [string]$pr.nco_sid } else { '' })) { $res.WrongAccount += $f.Name }
            $oaS = Get-C4Field $obj 'operator_action'
            if (($oaS -ceq $script:C4ProbeStopLine) -or ($oaS -ceq $script:C4ProbeStopLineWrongPrincipal)) { $res.ProbeStops += , ([ordered]@{ file = $f.Name; line = $oaS }) }
            if (@('filter_left_behind', 'filter_possibly_left_behind') -ccontains (Get-C4Field $obj 'overall')) { $res.ProbeLeft += , ([ordered]@{ file = $f.Name; overall = (Get-C4Field $obj 'overall') }) }
            $byAccount = $(if ($prep.Ok -and $pr.nco_sid) { [string](Get-C4Field $obj 'user_sid') -eq [string]$pr.nco_sid } else { (Get-C4Field $obj 'is_expected_account') -eq $true })
            if (((Get-C4Field $obj 'cond') -ceq 'E') -and $byAccount -and (Test-C4ETokenShown -Record $obj)) { $res.EElevated += $f.Name }
        }
        if ($f.Name -notmatch $script:C4RecordNameRe) { $reasons += 'file name: not a record (case4-<cond>-<yyyyMMdd-HHmmss>-<pid>.json); listed, never counted'; $res.Invalid += , ([ordered]@{ file = $f.Name; kind = 'misnamed'; reasons = $reasons }); continue }
        if ($null -eq $obj) { $reasons += 'record: not UTF-8 JSON'; $res.Invalid += , ([ordered]@{ file = $f.Name; kind = 'invalid'; reasons = $reasons }); continue }
        if (-not $prep.Ok -or -not $start) { $reasons += "no prepare record to validate against ($($prep.Problem))" }
        else {
            $va = @{ Record = $obj; FileName = $f.Name; ExeSha = [string]$pr.probe_exe_sha256; CsSha = [string]$pr.probe_cs_sha256; ProofSha = [string](Get-C4Field $pr 'probe_proof.sha256')
                     NcoSid = [string]$pr.nco_sid; OperatorSid = [string]$pr.operator_sid; WindowStart = $start; WindowEnd = $end; Seen = $seen }
            $reasons += @(& $Ctx.RecordValidator $va)
        }
        if ($reasons.Count) { $res.Invalid += , ([ordered]@{ file = $f.Name; kind = (Get-C4InvalidKind -Reasons $reasons); reasons = $reasons }) }
        else { $row = Get-C4RecordRow -Record $obj -FileName $f.Name; $res.Valid += , ([ordered]@{ file = $f.Name; sha256 = $sha.ToLowerInvariant(); elevation_type = (Get-C4Field $obj 'elevation_type.value') }); $res.Rows += , $row }
    }
    $res.ElevationRefused = Get-C4ElevationRefused -Note $ElevationRefusedNote -EElevated $res.EElevated
    $own = $false
    try {
        if (-not $Backend) { try { $Backend = & $Ctx.NewBackend; $own = $true } catch { Write-C4 "engine: could not be opened ($($_.Exception.Message))" 'Yellow' } }
        if (-not $RunnerGiven -and -not $Runner) { $ao = & $Ctx.AdminOnly $Ctx.ScriptDir; if ($ao.Ok) { $Runner = & $Ctx.NewRunner (& $Ctx.TrustedHarnessSha) } }
        if ($Backend) {
            $resid = Get-Nep5Residue -Runner $Runner -Backend $Backend -NoHarness:(-not $Runner)
            $pk = Get-C4KeyState -Backend $Backend
            $res.LeftBehind = @(@($resid.Rows | ForEach-Object { $_.Key }) + @($(if ($pk) { $script:C4ProbeKey })) | Where-Object { $_ } | Select-Object -Unique)
            $res.Foreign = @($resid.Foreign | ForEach-Object { "$($_.Key)@$($_.SubLayer)" })
            $res.ResidueReadable = ([bool]$resid.Readable -and ($null -ne $pk) -and [bool]$Runner)
            $res.Residue = [ordered]@{ readable = $resid.Readable; problems = @($resid.Problems); provider_present = $resid.ProviderPresent; s2_present = $resid.SubLayers['S2'].present; enum_skipped = (-not $Runner); probe_key_present = $pk }
        }
    } finally { if ($own -and $Backend) { try { $Backend.Close() } catch {} } }
    $kinds = [ordered]@{}; foreach ($i in $res.Invalid) { $kinds[$i.kind] = @($kinds[$i.kind]) + @($i.file) | Where-Object { $_ } }
    Write-C4 ("--- drop\: {0} entr(y/ies); {1} valid record(s); {2} invalid ({3}) ---" -f $files.Count, $res.Valid.Count, $res.Invalid.Count, $(if ($kinds.Count) { (@($kinds.Keys | ForEach-Object { "$_ $(@($kinds[$_]).Count)" }) -join ', ') } else { 'none' })) 'Cyan'
    foreach ($l in (Format-C4Table -Rows $res.Rows -ElevationRefused $res.ElevationRefused)) { Write-C4 $l }
    $label = @{ 'by-principal' = ' (by principal; never counted, not a STOP when nothing reached the engine)'; 'by-token-state' = ' (by token state: the right principal under the wrong token; never counted)'; 'misnamed' = ' (not a record name; never counted)'; 'sub-folder' = ' (a sub-folder; refused)'; 'link' = ' (a link; not followed)' }
    foreach ($i in $res.Invalid) { Write-C4 ("  INVALID{0} {1}: {2}" -f $(if ($label.ContainsKey($i.kind)) { $label[$i.kind] } else { '' }), $i.file, (@($i.reasons) -join '; ')) 'Yellow' }
    Write-C4 '--- sha256 of each file as read from drop\ (recorded with its copy in case4-runs\) ---' 'Cyan'
    foreach ($c in $res.Copies) { Write-C4 ("  {0}  {1}  [{2}]" -f $c.sha256, $c.file, $c.status) }
    foreach ($ps in $res.ProbeStops) { Write-C4 "  PROBE STOP LINE: $($ps.file) carries '$($ps.line)'." 'Red' }
    foreach ($pl in $res.ProbeLeft) { Write-C4 "  PROBE SAYS $($pl.overall.ToUpperInvariant()): $($pl.file). -Collect exits 21 until -Finish removes by key and verifies by enumeration." 'Red' }
    foreach ($w in $res.WrongAccount) { Write-C4 "  STOP: $w is an F/E record whose add SUCCEEDED under a principal that is not $($script:C4Account) (a filter was added by the wrong principal). -Finish removes it." 'Red' }
    foreach ($x in $res.Foreign) { Write-C4 "  STOP: a filter of ours or srt-win's outside S1/S2/S3: $x" 'Red' }
    if ($res.LeftBehind.Count) { Write-C4 "  LEFT BEHIND in S1/S2/S3 beside the provider and S2: $($res.LeftBehind -join ', ') (removed only by -Finish)" 'Red' }
    if (-not $res.ResidueReadable) { Write-C4 '  the engine could not be read completely: nothing is claimed about what is left (run -Finish).' 'Yellow' }
    if ($res.ElevationRefused.given -and -not $res.ElevationRefused.counted) { Write-C4 "  the -ElevationRefused note is NOT counted: $($res.ElevationRefused.reason)" 'Yellow' }
    $noteContradicted = [bool]($res.ElevationRefused.given -and -not $res.ElevationRefused.counted)
    $res.Code = Get-C4CollectExit -Stop ([bool]($res.WrongAccount.Count -or $res.Foreign.Count)) -LeftBehind ($res.LeftBehind.Count + $res.ProbeLeft.Count) -ResidueUnreadable (-not $res.ResidueReadable) -Invalid ($res.Invalid.Count + [int]$noteContradicted)
    $res.RecordPath = Save-C4Record -Ctx $Ctx -Name "case4-collect-$stamp.json" -Object ([ordered]@{ kind = 'nep5-case4-collect'; at = $now.ToString('o'); code = $res.Code; probe_stop_lines = $res.ProbeStops; probe_left_behind = $res.ProbeLeft; prepare = $res.Prepare; valid = $res.Valid; invalid = $res.Invalid
                                                                                                        invalid_by_kind = $kinds; wrong_account = $res.WrongAccount; e_elevated_as_account = $res.EElevated; elevation_refused = $res.ElevationRefused
                                                                                                        copies = $res.Copies; copies_folder_owner = $res.CopiesFolderOwner; left_behind = $res.LeftBehind; foreign = $res.Foreign; residue = $res.Residue; rows = $res.Rows })
    Write-C4 ("COLLECT exit {0}" -f $res.Code) $(if ($res.Code -eq 0) { 'Green' } else { 'Yellow' })
    return [pscustomobject]$res
}

# ---- -Finish --------------------------------------------------------------------------------------------------------------------------------------------------
function Get-C4UncopiedEvidence {
    # What in drop\ blocks deleting the public folder: every regular file without a byte-identical copy in <out>\case4-runs\, and every sub-folder (its contents are
    # never read or copied). A link is not evidence (it is removed as a link). The folder is never deleted over evidence that was not copied.
    param([Parameter(Mandatory)]$Ctx)
    $missing = @()
    foreach ($f in @(@($Ctx.Fs.ListFiles($Ctx.DropDir, '*')) | Where-Object { $_ -and -not $_.IsLink })) {
        if ($f.IsDir) { $missing += "$($f.Name) (a sub-folder)"; continue }
        $a = $Ctx.Fs.Sha256Raw($f.FullName); $b = $Ctx.Fs.Sha256Raw((Join-C4Path (Join-C4Path $Ctx.OutDir 'case4-runs') $f.Name))
        if (-not $a -or -not $b -or ($a -ne $b)) { $missing += $f.Name }
    }
    return @($missing)
}

function Invoke-C4Finish {
    param([Parameter(Mandatory)]$Ctx, [string]$ElevationRefusedNote)
    if (-not (& $Ctx.IsElevated)) { Write-C4 'REFUSED: not elevated; nothing removed. Use the manual rollback from an elevated PowerShell 7.' 'Red'; return 2 }
    $now = & $Ctx.Now; $stamp = $now.ToString('yyyyMMdd-HHmmss')
    $rec = [ordered]@{ kind = 'nep5-case4-final'; at = $now.ToString('o'); collect = $null; probe_key_delete = $null; removal = $null; manual = $null; sweep = $null; probe_key_after = $null
                       engine_sd = $null; folder = [ordered]@{}; verified = $false; code = $null; error = $null }
    $ao = & $Ctx.AdminOnly $Ctx.ScriptDir
    $runner = if ($ao.Ok) { & $Ctx.NewRunner (& $Ctx.TrustedHarnessSha) } else { $null }
    if (-not $runner) { Write-C4 'harness: not trusted here; removal falls back to our own engine and the manual rollback.' 'Yellow' }
    if ($Ctx.Fs.Exists($Ctx.HarnessProofPath)) { $script:N5LiveProof = $Ctx.HarnessProofPath }
    $be = $null; try { $be = & $Ctx.NewBackend } catch { Write-C4 "engine: could not be opened ($($_.Exception.Message))" 'Yellow' }
    $code = 7
    try {
        $col = Invoke-C4Collect -Ctx $Ctx -Backend $be -Runner $runner -RunnerGiven -ElevationRefusedNote $ElevationRefusedNote
        $rec.collect = [ordered]@{ code = $col.Code; valid = @($col.Valid).Count; invalid = $col.Invalid; wrong_account = $col.WrongAccount; left_behind = $col.LeftBehind; foreign = $col.Foreign; elevation_refused = $col.ElevationRefused; record = $col.RecordPath }
        if (@($col.Foreign).Count) {
            Write-C4 'STOP: a filter of ours or srt-win''s sits outside S1/S2/S3. NOTHING was removed by this mode.' 'Red'; Write-C4ManualRollback -Ctx $Ctx
            $rec.code = 9; [void](Save-C4Record -Ctx $Ctx -Name "case4-final-$stamp.json" -Object $rec); return 9
        }
        $pkSt = 'error: no backend'; if ($be) { try { $pkSt = [string]$be.Delete('filter', $script:C4ProbeKey) } catch { $pkSt = "error: $($_.Exception.Message)" } }
        $rec.probe_key_delete = $pkSt; Write-C4 ("  filter    {0}  {1}  [the probe's key, our engine]" -f $script:C4ProbeKey, $pkSt)
        $rm = $null; if ($runner -and $be) { $rm = Remove-Nep5All -Runner $runner -Backend $be; $rec.removal = [ordered]@{ ok = $rm.Ok; steps = @($rm.Steps); errors = @($rm.Errors) }; foreach ($s in $rm.Steps) { Write-C4 ("  {0,-9} {1}  {2}  [{3}]" -f $s.step, $s.key, $s.status, $s.via) } }
        if (-not ($rm -and $rm.Ok)) { Write-C4 'The by-key removal did not verify a clean engine (or could not run): the self-contained manual rollback runs now.' 'Yellow'; $rec.manual = & $Ctx.ManualRollback }
        $sw = Invoke-Nep5DirectSweep -Runner $runner -Backend $be -Exporter $Ctx.Exporter -Label 'finish' -NoHarness:(-not $runner)
        $pkNow = Get-C4KeyState -Backend $be
        $rec.sweep = Get-C4SweepSummary $sw; $rec.probe_key_after = $pkNow
        if ($sw.Stop) { Write-C4 'STOP: a filter of ours or srt-win''s sits outside S1/S2/S3 (reported, never deleted here).' 'Red'; Write-C4ManualRollback -Ctx $Ctx; $rec.code = 9; [void](Save-C4Record -Ctx $Ctx -Name "case4-final-$stamp.json" -Object $rec); return 9 }
        if (-not (& $Ctx.FinishSweepGate $sw $pkNow)) {
            foreach ($m in @($sw.NotClean) + @($sw.Problems)) { Write-C4 "  ! $m" 'Red' }
            Write-C4 "ENGINE REMOVAL NOT VERIFIED (probe key present: $pkNow). The public folder is kept. Run the manual rollback, then -Check." 'Red'; Write-C4ManualRollback -Ctx $Ctx
            $rec.code = 7; [void](Save-C4Record -Ctx $Ctx -Name "case4-final-$stamp.json" -Object $rec); return 7
        }
        Write-C4 'ENGINE REMOVAL VERIFIED: S1, S2, S3, our provider and the probe key read back absent; the export has no hits.' 'Green'
        $prep = Get-C4LatestPrepare -Ctx $Ctx
        $sdNow = & $Ctx.ReadWfpSecurity 'engine' $null
        $before = if ($prep.Ok) { [string](Get-C4Field $prep.Record 'security.engine.text') } else { '' }
        $rec.engine_sd = [ordered]@{ now = $sdNow; compared_with = $prep.Name; compare = $(if ($before -and $sdNow.ok) { Compare-C4SdText -Before $before -After $sdNow.text } else { 'not compared (no prepare record or unreadable now)' }) }
        if ($before -and $sdNow.ok) { $cmp = $rec.engine_sd.compare; Write-C4 ("engine security descriptor against -Prepare's: {0}" -f $(if ($cmp.same) { 'identical' } else { "DIFFERENT (removed: $($cmp.removed -join ' | '); added: $($cmp.added -join ' | '))" })) $(if ($cmp.same) { 'Gray' } else { 'Yellow' }) }
        if ($Ctx.Fs.Exists($Ctx.PubRoot)) {
            $missing = @(Get-C4UncopiedEvidence -Ctx $Ctx)
            $rec.folder.uncopied = $missing
            if (-not (& $Ctx.EvidenceGate $missing)) { Write-C4 "NOT VERIFIED: drop\ holds evidence that was not copied, or a sub-folder that is never read: $($missing -join ', '). The public folder is kept (inspect it by hand)." 'Red'; $rec.code = 7; [void](Save-C4Record -Ctx $Ctx -Name "case4-final-$stamp.json" -Object $rec); return 7 }
            if ($Ctx.Fs.Exists($Ctx.DropDir)) {
                $want = Get-C4DropSddlAfterRemoval
                $Ctx.Fs.SetDacl($Ctx.DropDir, $want)
                $got = $Ctx.Fs.GetSddl($Ctx.DropDir)
                $gone = @(@($(if ($prep.Ok) { [string]$prep.Record.nco_sid }), $(if ($prep.Ok) { [string]$prep.Record.operator_sid })) | Where-Object { $_ })
                $rec.folder.drop_acl = [ordered]@{ set = $want; read_back = $got; removed_sids = $gone }
                if (-not (& $Ctx.AceRemovalGate $want $got $gone)) { Write-C4 "NOT VERIFIED: drop\'s DACL read back still grants more than SYSTEM and Administrators ($got). The public folder is kept." 'Red'; $rec.code = 7; [void](Save-C4Record -Ctx $Ctx -Name "case4-final-$stamp.json" -Object $rec); return 7 }
                Write-C4 'drop\: the account''s and the operator''s ACEs removed and read back (SYSTEM and Administrators only).' 'Green'
            }
            $Ctx.Fs.RemoveTree($Ctx.PubRoot)
            $rec.folder.removed = -not $Ctx.Fs.Exists($Ctx.PubRoot)
            if (-not $rec.folder.removed) { Write-C4 "NOT VERIFIED: $($Ctx.PubRoot) still exists after the delete." 'Red'; $rec.code = 7; [void](Save-C4Record -Ctx $Ctx -Name "case4-final-$stamp.json" -Object $rec); return 7 }
            Write-C4 "public folder $($Ctx.PubRoot) deleted and read back absent." 'Green'
        } else { $rec.folder.removed = $true; Write-C4 "public folder $($Ctx.PubRoot): already absent." }
        $rec.verified = $true
        $code = Get-C4FinishExit -ForeignStop $false -Verified $true -WrongAccountFinding ([bool]@($col.WrongAccount).Count)
        if ($code -eq 9) { Write-C4 "REMOVAL VERIFIED, and a STOP finding stands: $($col.WrongAccount -join ', ') (an F/E add succeeded under another principal)." 'Red' }
        $rec.code = $code
        [void](Save-C4Record -Ctx $Ctx -Name "case4-final-$stamp.json" -Object $rec)
        Write-C4 ("FINISH exit {0}" -f $code) $(if ($code -eq 0) { 'Green' } else { 'Red' })
        return $code
    } catch {
        $rec.error = $_.Exception.Message; $rec.code = 7
        Write-C4 "ERROR: $($_.Exception.Message): NOT VERIFIED." 'Red'; Write-C4ManualRollback -Ctx $Ctx
        [void](Save-C4Record -Ctx $Ctx -Name "case4-final-$stamp.json" -Object $rec)
        return 7
    } finally { if ($be) { try { $be.Close() } catch {} } }
}

# ---- -PartD ---------------------------------------------------------------------------------------------------------------------------------------------------
function Invoke-C4PartD {
    param([Parameter(Mandatory)]$Ctx)
    if (-not (& $Ctx.IsElevated)) { Write-C4 'REFUSED: not elevated (the record goes into the admin-only out dir).' 'Red'; return 2 }
    $now = & $Ctx.Now
    $nu = $Ctx.Acct.NetUser($script:C4Account); $us = Get-C4NetUserState -ExitCode $nu.Exit -Text $nu.Text
    $lk = $Ctx.Acct.Lookup($script:C4Account)
    $lookupGone = if ($lk.Sid) { $false } elseif ([int]$lk.Error -eq 1332) { $true } else { $null }
    $gname = $Ctx.Acct.GroupName($script:C4NcoGroupSid); $ng = $null; $members = $null
    if ($gname) { $ng = $Ctx.Acct.NetLocalGroup(($gname -replace '^.*\\', '')); $members = ConvertFrom-C4NetLocalGroup -Text $ng.Text -ExitCode $ng.Exit }
    $memberGone = if ($null -eq $members) { $null } else { -not (Test-C4MemberListed -Members $members) }
    $profDir = $Ctx.Acct.ProfileDir($script:C4Account); $pe = $Ctx.Acct.PathExists($profDir)
    $profileGone = if ($pe -eq $false) { $true } elseif ($pe -eq $true) { $false } else { $null }
    $accountGone = switch ($us) { 'absent' { $true } 'present' { $false } default { $null } }
    # The account's SID from the prepare record (the account itself is gone by now): its ProfileList entry must be gone, and so must the folder that entry named.
    $prep = Get-C4LatestPrepare -Ctx $Ctx
    $sid = if ($prep.Ok -and $prep.Record.nco_sid) { [string]$prep.Record.nco_sid } elseif ($lk.Sid) { [string]$lk.Sid } else { $null }
    $pl = $null; $plGone = $null; $imageGone = $true
    if ($sid) {
        $pl = $Ctx.Acct.ProfileListEntry($sid)
        $plGone = if ($pl.Present -eq $false) { $true } elseif ($pl.Present -eq $true) { $false } else { $null }
        if ($pl.Present -eq $true -and $pl.ImagePath) { $ie = $Ctx.Acct.PathExists($pl.ImagePath); $imageGone = if ($ie -eq $false) { $true } elseif ($ie -eq $true) { $false } else { $null } }
    }
    $folders = $Ctx.Acct.ProfileFolders($script:C4Account)
    $foldersGone = if ($null -eq $folders) { $null } elseif (@($folders).Count) { $false } else { $true }
    $profileFoldersGone = if ($foldersGone -eq $true -and $imageGone -eq $true) { $true } elseif ($foldersGone -eq $false -or $imageGone -eq $false) { $false } else { $null }
    $code = Get-C4PartDExit -AccountGone $accountGone -LookupGone $lookupGone -MemberGone $memberGone -ProfileGone $profileGone -ProfileListGone $plGone -ProfileFoldersGone $profileFoldersGone
    Write-C4 ("net user {0}: {1}; LookupAccountName: {2}; member of {3}: {4}; profile folder {5}: {6}" -f $script:C4Account, $us, $(if ($lk.Sid) { $lk.Sid } else { "error $($lk.Error)" }), $gname, $(if ($null -eq $memberGone) { 'UNREADABLE' } elseif ($memberGone) { 'no' } else { 'YES' }), $profDir, $(if ($null -eq $pe) { 'UNREADABLE' } elseif ($pe) { 'PRESENT' } else { 'absent' }))
    Write-C4 ("ProfileList entry for {0}: {1}; profile folders named {2}: {3}" -f $(if ($sid) { $sid } else { '(no SID on record)' }), $(if ($null -eq $plGone) { 'UNREADABLE (or no SID to read it by)' } elseif ($plGone) { 'absent' } else { "PRESENT ($($pl.ImagePath))" }), $script:C4Account, $(if ($null -eq $folders) { 'UNREADABLE' } elseif (@($folders).Count) { 'PRESENT: ' + (@($folders) -join ', ') } else { 'none' }))
    try { $Ctx.Fs.EnsureDir($Ctx.OutDir) } catch { Write-C4 "the out dir could not be made: $($_.Exception.Message)" 'Red' }
    [void](Save-C4Record -Ctx $Ctx -Name ("case4-partd-{0}.json" -f $now.ToString('yyyyMMdd-HHmmss')) -Object ([ordered]@{ kind = 'nep5-case4-partd'; at = $now.ToString('o'); code = $code
                                         net_user = [ordered]@{ exit = $nu.Exit; state = $us; text = $nu.Text }; lookup = $lk; group = $gname; net_localgroup = $(if ($ng) { [ordered]@{ exit = $ng.Exit; text = $ng.Text } }); members = $members
                                         profile_dir = $profDir; profile_present = $pe; account_sid = $sid; profile_list_entry = $pl; profile_folders = $folders }))
    Write-C4 ("PART D exit {0}: {1}" -f $code, $(if ($code -eq 20) { 'the account, its membership, its ProfileList entry and every profile folder of its name are gone' } else { 'something remains or could not be read' })) $(if ($code -eq 20) { 'Green' } else { 'Yellow' })
    return $code
}

# ---- the real seams (the ONLY functions that touch the machine; -SelfTest never builds them) -------------------------------------------------------------------
function Invoke-C4RealLookup {
    # An account by name, read only and with no compiled type: its SID through .NET's NTAccount translation (the LSA lookup LookupAccountName also uses), its domain
    # from the reverse translation, and its kind: 1 a local user (Get-LocalUser by SID), 4 a local group (Get-LocalGroup by SID), 5 a well-known or built-in SID,
    # 8 anything else (for example a domain account). A name that does not map reads error 1332 (ERROR_NONE_MAPPED). @{ Ok; Sid; Domain; Use; Error; Detail }.
    param([Parameter(Mandatory)][string]$Name)
    $sid = $null
    try { $sid = ([Security.Principal.NTAccount]::new($Name)).Translate([Security.Principal.SecurityIdentifier]).Value }
    catch {
        $e = $_.Exception; while ($e.InnerException) { $e = $e.InnerException }
        $code = if ($e -is [Security.Principal.IdentityNotMappedException]) { 1332 } else { -1 }
        return [ordered]@{ Ok = $false; Sid = $null; Domain = $null; Use = 0; Error = $code; Detail = $e.Message }
    }
    $full = $null; try { $full = ([Security.Principal.SecurityIdentifier]::new($sid)).Translate([Security.Principal.NTAccount]).Value } catch { $full = $null }
    $domain = if ($full -and $full.Contains('\')) { $full.Substring(0, $full.IndexOf('\')) } else { $null }
    $use = 8
    if (@(Get-LocalUser -SID $sid -ErrorAction SilentlyContinue).Count) { $use = 1 }
    elseif (@(Get-LocalGroup -SID $sid -ErrorAction SilentlyContinue).Count) { $use = 4 }
    elseif ($sid -match '^S-1-5-32-' -or $sid -in @('S-1-1-0', 'S-1-2-0', 'S-1-5-4', 'S-1-5-11', 'S-1-5-18', 'S-1-5-19', 'S-1-5-20')) { $use = 5 }
    return [ordered]@{ Ok = $true; Sid = $sid; Domain = $domain; Use = $use; Error = 0; Detail = $full }
}

function Invoke-C4RealNet {
    # `net user <name>` or `net localgroup <group>`, System32's net.exe by full path: reads only (no switch, no second argument).
    param([Parameter(Mandatory)][ValidateSet('user', 'localgroup')][string]$Verb, [Parameter(Mandatory)][string]$Name)
    if ($Name -match '^\s*/' -or $Name -match '[\r\n"]') { throw "refusing net $Verb with '$Name'" }
    if ($Verb -eq 'user') { $out = & (Join-C4Path ([Environment]::GetFolderPath('System')) 'net.exe') user $Name 2>&1 | Out-String }
    else { $out = & (Join-C4Path ([Environment]::GetFolderPath('System')) 'net.exe') localgroup $Name 2>&1 | Out-String }
    return [ordered]@{ Exit = $LASTEXITCODE; Text = $out }
}

function Invoke-C4RealMemberSids {
    # The members of a local group as SIDs (a read): Get-LocalGroupMember; when it fails (an orphaned SID makes it throw), `net localgroup` names resolved one by one.
    # Any member that does not resolve makes the read unreadable (fail closed).
    param([Parameter(Mandatory)][string]$GroupSid)
    $e1 = $null
    try { return [ordered]@{ Ok = $true; Sids = @(Get-LocalGroupMember -SID $GroupSid -ErrorAction Stop | ForEach-Object { [string]$_.SID.Value }); Via = 'Get-LocalGroupMember'; Error = $null } } catch { $e1 = $_.Exception.Message }
    $gname = $null; try { $gname = ([Security.Principal.SecurityIdentifier]::new($GroupSid)).Translate([Security.Principal.NTAccount]).Value } catch { return [ordered]@{ Ok = $false; Sids = @(); Via = 'none'; Error = "group $GroupSid does not resolve" } }
    $r = Invoke-C4RealNet -Verb 'localgroup' -Name ($gname -replace '^.*\\', '')
    $names = ConvertFrom-C4NetLocalGroup -Text $r.Text -ExitCode $r.Exit
    if ($null -eq $names) { return [ordered]@{ Ok = $false; Sids = @(); Via = 'net localgroup'; Error = "Get-LocalGroupMember: $e1; net localgroup unreadable" } }
    $sids = @()
    foreach ($n in @($names)) { $l = Invoke-C4RealLookup -Name $n; if (-not $l.Sid) { return [ordered]@{ Ok = $false; Sids = @(); Via = 'net localgroup'; Error = "member '$n' does not resolve" } }; $sids += $l.Sid }
    return [ordered]@{ Ok = $true; Sids = $sids; Via = 'net localgroup'; Error = $e1 }
}

function Invoke-C4RealNetshSecurity {
    param([Parameter(Mandatory)][string]$Type, [string]$Guid)
    return (Find-C4NetshSecurity -Type $Type -Guid $Guid -RunNetsh { param([string[]]$Argv) $t = & (Join-C4Path ([Environment]::GetFolderPath('System')) 'netsh.exe') @Argv 2>&1 | Out-String; [pscustomobject]@{ exit = $LASTEXITCODE; text = $t } })
}

function Invoke-C4RealProbeVersion {
    # PROOF-TIME seam: `ncoprobe.exe --version` from $Folder (it opens no engine), with NCOPROBE_ENGINE_OPEN_TRACE pointed at a fresh file that must stay absent or
    # empty and NCOPROBE_TOGGLE_OFF cleared; both are put back afterwards. No timeout (--version returns at once; a hang is visible to the operator at the console).
    param([Parameter(Mandatory)][string]$Folder)
    $trace = Join-C4Path ([IO.Path]::GetTempPath()) ('c4-trace-' + [guid]::NewGuid().ToString('N') + '.txt')
    $saved = @{ trace = $env:NCOPROBE_ENGINE_OPEN_TRACE; toggle = $env:NCOPROBE_TOGGLE_OFF }
    $all = @(); $code = $null
    try {
        $env:NCOPROBE_ENGINE_OPEN_TRACE = $trace; $env:NCOPROBE_TOGGLE_OFF = $null
        $all = @(& (Join-C4Path $Folder 'ncoprobe.exe') --version 2>&1); $code = $LASTEXITCODE
    } finally { $env:NCOPROBE_ENGINE_OPEN_TRACE = $saved.trace; $env:NCOPROBE_TOGGLE_OFF = $saved.toggle }
    $empty = (-not (Test-Path -LiteralPath $trace)) -or (([IO.File]::ReadAllText($trace)).Trim().Length -eq 0)
    Remove-Item -LiteralPath $trace -Force -ErrorAction SilentlyContinue
    return [ordered]@{ Exit = $code; Stdout = (@($all | Where-Object { $_ -isnot [Management.Automation.ErrorRecord] }) -join "`n"); Stderr = (@($all | Where-Object { $_ -is [Management.Automation.ErrorRecord] }) -join "`n"); TraceEmpty = $empty }
}

function Invoke-C4RealProbeSelfTest {
    # PROOF-TIME seam: the probe's own runner `run-probe-selftest.ps1` from $Folder in a child PowerShell 7 (it builds fresh exes into a temp folder, runs the probe's
    # `selftest` and `selftest-process`, and opens no engine). NCOPROBE_TOGGLE_OFF is cleared for the child and put back afterwards. No timeout (it is attended).
    param([Parameter(Mandatory)][string]$Folder)
    $runner = Join-C4Path $Folder 'run-probe-selftest.ps1'
    if (-not (Test-Path -LiteralPath $runner -PathType Leaf)) { return [ordered]@{ Exit = -1; Stdout = ''; Stderr = "missing: $runner" } }
    $saved = $env:NCOPROBE_TOGGLE_OFF; $all = @(); $code = $null
    try { $env:NCOPROBE_TOGGLE_OFF = $null; $all = @(& (Join-C4Path $PSHOME 'pwsh.exe') -NoProfile -File $runner 2>&1); $code = $LASTEXITCODE } finally { $env:NCOPROBE_TOGGLE_OFF = $saved }
    return [ordered]@{ Exit = $code; Stdout = (@($all | Where-Object { $_ -isnot [Management.Automation.ErrorRecord] }) -join "`n"); Stderr = (@($all | Where-Object { $_ -is [Management.Automation.ErrorRecord] }) -join "`n") }
}

function New-C4RealFs {
    # The file seam. Every write is guarded against junctions, symlinks and hard links; reads of drop\ (which the account can write) refuse links and cap the size.
    $fs = [pscustomobject]@{ Kind = 'real' }
    $fs | Add-Member -MemberType ScriptMethod -Name Exists -Value { param($p) Test-PathExistsNoFollow $p }
    $fs | Add-Member -MemberType ScriptMethod -Name EnsureDir -Value {
        param($p)
        Assert-PlainOutputPath -Path (Join-C4Path $p 'probe.tmp')
        if (-not (Test-PathExistsNoFollow $p)) { New-Item -ItemType Directory -Force -Path $p | Out-Null }
        if (Test-IsReparsePoint $p) { throw "'$p' is a reparse point" }
    }
    $fs | Add-Member -MemberType ScriptMethod -Name NewProtectedDir -Value {
        param($p, $sddl)
        Assert-PlainOutputPath -Path $p
        if (Test-PathExistsNoFollow $p) { throw "'$p' already exists" }
        $sec = [Security.AccessControl.DirectorySecurity]::new(); $sec.SetSecurityDescriptorSddlForm($sddl)
        [void][IO.FileSystemAclExtensions]::Create([IO.DirectoryInfo]::new($p), $sec)
        if (-not (Test-PathExistsNoFollow $p) -or (Test-IsReparsePoint $p)) { throw "'$p' was not created as a plain folder" }
    }
    $fs | Add-Member -MemberType ScriptMethod -Name GetSddl -Value { param($p) (Get-PathSecurityObject -Path $p).GetSecurityDescriptorSddlForm([Security.AccessControl.AccessControlSections]'Owner, Access') }
    $fs | Add-Member -MemberType ScriptMethod -Name SetDacl -Value { param($p, $sddl) Assert-AclTargetPlain $p; $sec = Get-DirSecurity $p; $sec.SetSecurityDescriptorSddlForm($sddl, [Security.AccessControl.AccessControlSections]::Access); Set-DirSecurity $p $sec }
    $fs | Add-Member -MemberType ScriptMethod -Name CopyFile -Value { param($src, $dst) Assert-PlainOutputPath -Path $dst; if (Test-PathExistsNoFollow $dst) { throw "'$dst' already exists" }; [IO.File]::Copy($src, $dst, $false) }
    $fs | Add-Member -MemberType ScriptMethod -Name SetOwnerAdmins -Value {
        param($p)
        Assert-AclTargetPlain $p
        # A file or a folder (the copies folder case4-runs\): the info type of its kind, because the ACL extensions are typed per kind.
        $fi = $(if (Test-Path -LiteralPath $p -PathType Container) { [IO.DirectoryInfo]::new($p) } else { [IO.FileInfo]::new($p) })
        $sec = [IO.FileSystemAclExtensions]::GetAccessControl($fi)
        $sec.SetOwner([Security.Principal.SecurityIdentifier]::new('S-1-5-32-544')); [IO.FileSystemAclExtensions]::SetAccessControl($fi, $sec)
        $now = ([IO.FileSystemAclExtensions]::GetAccessControl($fi)).GetOwner([Security.Principal.SecurityIdentifier]).Value
        if ($now -ne 'S-1-5-32-544') { throw "the owner of '$p' reads $now after it was set to Administrators" }
    }
    $fs | Add-Member -MemberType ScriptMethod -Name WriteJson -Value { param($p, $o) Write-JsonGuarded -Path $p -Object $o -Depth 16 }
    $fs | Add-Member -MemberType ScriptMethod -Name WriteBytesOnce -Value {
        param($p, [byte[]]$b)
        $dir = Split-Path $p -Parent
        if (-not (Test-PathExistsNoFollow $dir)) { Assert-PlainOutputPath -Path $p; New-Item -ItemType Directory -Force -Path $dir | Out-Null }
        Assert-PlainOutputPath -Path $p
        if (Test-PathExistsNoFollow $p) { if ((Get-N5RawSha256 -Path $p) -eq (Get-C4BytesSha $b)) { return 'exists-same' }; return 'exists-different' }
        [IO.File]::WriteAllBytes($p, $b); return 'written'
    }
    $fs | Add-Member -MemberType ScriptMethod -Name ReadBytes -Value {
        param($p, [int]$max)
        $parent = Split-Path -Path $p -Parent
        if ($parent -and (Test-IsReparsePoint $parent)) { throw "refusing to read '$p': its folder is a reparse point" }
        if (Test-IsReparsePoint $p) { throw "refusing to read '$p': it is a reparse point" }
        if ((Get-FileLinkCount $p) -gt 1) { throw "refusing to read '$p': it has more than one hard link" }
        if (([IO.FileInfo]$p).Length -gt $max) { throw "refusing to read '$p': larger than $max bytes" }
        $bytes = [IO.File]::ReadAllBytes($p)
        if ($bytes.Length -gt $max) { throw "refusing to read '$p': larger than $max bytes" }
        return , $bytes
    }
    $fs | Add-Member -MemberType ScriptMethod -Name ListFiles -Value {
        param($dir, $filter)
        if (-not (Test-PathExistsNoFollow $dir)) { return , @() }
        return , @(([IO.DirectoryInfo]$dir).GetFileSystemInfos($filter) | ForEach-Object { [pscustomobject]@{ Name = $_.Name; FullName = $_.FullName; IsLink = [bool]($_.Attributes -band [IO.FileAttributes]::ReparsePoint); IsDir = [bool]($_.Attributes -band [IO.FileAttributes]::Directory) } })
    }
    $fs | Add-Member -MemberType ScriptMethod -Name RemoveTree -Value { param($p) Remove-TreeNoFollow -Root $p }
    $fs | Add-Member -MemberType ScriptMethod -Name Sha256Raw -Value { param($p) Get-N5RawSha256 -Path $p }
    $fs | Add-Member -MemberType ScriptMethod -Name ReadText -Value { param($p) [IO.File]::ReadAllText($p) }
    return $fs
}

function New-C4RealAcct {
    # The account seam: reads only. There is no method here that writes anything about an account.
    $a = [pscustomobject]@{ Kind = 'real' }
    $a | Add-Member -MemberType ScriptMethod -Name Lookup -Value { param($name) Invoke-C4RealLookup -Name $name }
    $a | Add-Member -MemberType ScriptMethod -Name MemberSids -Value { param($groupSid) Invoke-C4RealMemberSids -GroupSid $groupSid }
    $a | Add-Member -MemberType ScriptMethod -Name NetUser -Value { param($name) Invoke-C4RealNet -Verb 'user' -Name $name }
    $a | Add-Member -MemberType ScriptMethod -Name NetLocalGroup -Value { param($name) Invoke-C4RealNet -Verb 'localgroup' -Name $name }
    $a | Add-Member -MemberType ScriptMethod -Name GroupName -Value { param($sid) try { ([Security.Principal.SecurityIdentifier]::new($sid)).Translate([Security.Principal.NTAccount]).Value } catch { $null } }
    $a | Add-Member -MemberType ScriptMethod -Name ProfileDir -Value {
        param($name)
        $base = $null
        try { $base = [Environment]::ExpandEnvironmentVariables((Get-ItemProperty -LiteralPath 'HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion\ProfileList' -Name ProfilesDirectory -ErrorAction Stop).ProfilesDirectory) } catch {}
        if (-not $base) { $base = Split-Path $env:PUBLIC -Parent }
        return (Join-C4Path $base $name)
    }
    $a | Add-Member -MemberType ScriptMethod -Name PathExists -Value { param($p) try { [bool](Test-PathExistsNoFollow $p) } catch { $null } }
    $a | Add-Member -MemberType ScriptMethod -Name ProfileListEntry -Value {
        # The ProfileList\<SID> key (which part C deletes): @{ Present; ImagePath }, Present $null when the registry cannot be read.
        param($sid)
        if ([string]$sid -notmatch '^S-1-\d+(-\d+)+$') { return [ordered]@{ Present = $null; ImagePath = $null; Error = 'not a SID' } }
        $k = 'HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion\ProfileList\' + $sid
        try {
            if (-not (Test-Path -LiteralPath $k)) { return [ordered]@{ Present = $false; ImagePath = $null; Error = $null } }
            $ip = (Get-ItemProperty -LiteralPath $k -Name ProfileImagePath -ErrorAction SilentlyContinue).ProfileImagePath
            return [ordered]@{ Present = $true; ImagePath = $(if ($ip) { [Environment]::ExpandEnvironmentVariables([string]$ip) } else { $null }); Error = $null }
        } catch { return [ordered]@{ Present = $null; ImagePath = $null; Error = $_.Exception.Message } }
    }
    $a | Add-Member -MemberType ScriptMethod -Name ProfileFolders -Value {
        # Every folder under the profiles directory named <name> or <name>.<suffix> (Windows names a second profile `name.COMPUTER` when the first folder exists).
        # $null when the directory cannot be listed.
        param($name)
        try {
            $base = Split-Path ($this.ProfileDir($name)) -Parent
            return , @(Get-ChildItem -LiteralPath $base -Directory -Force -ErrorAction Stop | Where-Object { $_.Name -ieq $name -or $_.Name -like "$name.*" } | ForEach-Object { $_.FullName })
        } catch { return $null }
    }
    return $a
}

function New-C4RealCtx {
    # The ONLY place that builds the machine-touching context. Nothing is opened on construction: the engine opens when a mode calls NewBackend, the harness runs when a
    # mode builds a runner with a hash it verified, the export folder is made on first use.
    param([Parameter(Mandatory)][string]$ScriptDir)
    $exe = Join-C4Path $ScriptDir 'halfset.exe'; $ov = $HarnessSha256
    $tmp = [pscustomobject]@{ Dir = $null }; $opened = New-Object System.Collections.ArrayList
    $null = Import-WfpHelpers -Path $WfpScript -ExpectedSha256 $WfpSha256 -Unverified:($DryRun -and -not $WfpSha256 -and -not (Test-AdminOnlyFolder -Path (Split-Path (Resolve-Path -LiteralPath $WfpScript).Path -Parent)).Ok)
    Initialize-Nep5Type
    $ctx = [pscustomobject]@{
        Kind = 'real'; ScriptDir = $ScriptDir; OutDir = (Join-C4Path $ScriptDir 'nep5-out\case4'); PubRoot = $script:C4PubRoot
        BinDir = (Join-C4Path $script:C4PubRoot 'bin'); DropDir = (Join-C4Path $script:C4PubRoot 'drop')
        DriverProofPath = (Join-C4Path $ScriptDir $script:C4DriverProofName); HarnessProofPath = (Join-C4Path $ScriptDir $script:C4HarnessProofName)
        ProbeExeSrc = (Join-C4Path $ScriptDir $script:C4ProbeExeName); ComputerName = $env:COMPUTERNAME; Temp = $tmp; Opened = $opened
        NewBackend = { $b = New-Nep5RealBackend; [void]$opened.Add($b); $b }.GetNewClosure()
        NewRunner = { param($sha) if (-not $sha) { return $null }; New-HalfsetRunner -Exe $exe -ExpectedSha256 $sha }.GetNewClosure()
        TrustedHarnessSha = { Get-C4TrustedHarnessSha -ScriptDir $ScriptDir -Override $ov }.GetNewClosure()
        Exporter = { param($l) if (-not $tmp.Dir) { $tmp.Dir = New-PrivateTempDir }; Invoke-Nep5Export -Label $l -Path (Join-C4Path $tmp.Dir "c4-$l.xml") -DropClean }.GetNewClosure()
        ManualRollback = { Invoke-ManualN5Rollback }
        ReadWfpSecurity = { param($type, $guid) Invoke-C4RealNetshSecurity -Type $type -Guid $guid }
        Fs = (New-C4RealFs); Acct = (New-C4RealAcct)
        OperatorToken = { Get-OperatorTokenSids }; IsElevated = { Test-IsElevated }; Is64Bit = { [Environment]::Is64BitProcess }
        AdminOnly = { param($p) Test-AdminOnlyFolder -Path $p }; SidResolver = (New-Nep5SidResolver); Now = { [datetimeoffset]::Now }
        ProofCheck = { param($c) Test-C4DriverProof -ProofPath $c.DriverProofPath -Folder $c.ScriptDir -SelfSha (Get-C4SelfSha) -WrappedSha (Get-C4WrappedSha) }
        Close = { foreach ($b in @($opened)) { try { $b.Close() } catch {} }; if ($tmp.Dir) { Remove-PrivateTempDir $tmp.Dir; $tmp.Dir = $null } }.GetNewClosure()
    }
    Add-C4DefaultGates $ctx
    return $ctx
}

# ---- -SelfTest stand-ins ---------------------------------------------------------------------------------------------------------------------------------------
function New-C4FakeFs {
    # The file system stand-in: folders (with their SDDL) and files (bytes) in memory, keyed by the lower-cased path; nothing touches a disk. Switches:
    #   IgnoreSetDacl   SetDacl changes nothing (an ACE removal that did not take)    DropAceOnCreate  the folder named here is created with its last ACE missing
    #   CopyCorrupt     the copied file gets one extra byte                           FailWriteBytes   WriteBytesOnce throws
    #   Links           paths that are links (listed, never read)                     FailJsonMatch    WriteJson throws for a path matching this pattern
    $fs = [pscustomobject]@{ Kind = 'fake'; Files = @{}; Dirs = @{}; Links = @{}; Owners = @{}; Calls = (New-Object System.Collections.ArrayList); Writes = 0; IgnoreSetDacl = $false; DropAceOnCreate = ''; CopyCorrupt = $false; FailWriteBytes = $false; FailJsonMatch = '' }
    $fs | Add-Member -MemberType ScriptMethod -Name Key -Value { param($p) ([string]$p).TrimEnd('\').ToLowerInvariant() }
    $fs | Add-Member -MemberType ScriptMethod -Name Seed -Value { param($p, [byte[]]$b) $this.Files[$this.Key($p)] = [pscustomobject]@{ Path = [string]$p; Bytes = $b } }
    $fs | Add-Member -MemberType ScriptMethod -Name Exists -Value { param($p) $k = $this.Key($p); [bool]($this.Files.ContainsKey($k) -or $this.Dirs.ContainsKey($k) -or $this.Links.ContainsKey($k)) }
    $fs | Add-Member -MemberType ScriptMethod -Name EnsureDir -Value { param($p) [void]$this.Calls.Add("ensure $p"); $k = $this.Key($p); if (-not $this.Dirs.ContainsKey($k)) { $this.Dirs[$k] = [pscustomobject]@{ Path = [string]$p; Sddl = 'D:PAI(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)' }; $this.Writes++ } }
    $fs | Add-Member -MemberType ScriptMethod -Name NewProtectedDir -Value {
        param($p, $sddl)
        [void]$this.Calls.Add("newdir $p"); $k = $this.Key($p)
        if ($this.Exists($p)) { throw "'$p' already exists" }
        $s = [string]$sddl; if ($this.DropAceOnCreate -and $k -eq $this.Key($this.DropAceOnCreate)) { $s = $s -replace '\([^()]*\)$', '' }
        $this.Dirs[$k] = [pscustomobject]@{ Path = [string]$p; Sddl = $s }; $this.Writes++
    }
    $fs | Add-Member -MemberType ScriptMethod -Name GetSddl -Value { param($p) $k = $this.Key($p); if (-not $this.Dirs.ContainsKey($k)) { throw "no folder $p" }; $x = [string]$this.Dirs[$k].Sddl; if ($x -match '^O:') { $x } else { 'O:BA' + $x } }
    $fs | Add-Member -MemberType ScriptMethod -Name SetDacl -Value {
        param($p, $sddl)
        [void]$this.Calls.Add("setdacl $p"); $k = $this.Key($p); if (-not $this.Dirs.ContainsKey($k)) { throw "no folder $p" }
        if (-not $this.IgnoreSetDacl) { $own = if ($this.Dirs[$k].Sddl -match '^(O:.+?)(?=G:|D:)') { $Matches[1] } else { '' }; $this.Dirs[$k].Sddl = $own + ([string]$sddl -replace '^O:.+?(?=G:|D:)', '') }
        $this.Writes++
    }
    $fs | Add-Member -MemberType ScriptMethod -Name SetOwnerAdmins -Value { param($p) [void]$this.Calls.Add("setowner $p"); if (-not $this.Exists($p)) { throw "no file $p" }; $this.Owners[$this.Key($p)] = 'S-1-5-32-544'; $this.Writes++ }
    $fs | Add-Member -MemberType ScriptMethod -Name CopyFile -Value {
        param($src, $dst)
        [void]$this.Calls.Add("copy $src $dst"); $sk = $this.Key($src)
        if ($this.Exists($dst)) { throw "'$dst' already exists" }
        if (-not $this.Files.ContainsKey($sk)) { throw "no file $src" }
        [byte[]]$b = $this.Files[$sk].Bytes; if ($this.CopyCorrupt) { $b = [byte[]](@($b) + @([Text.Encoding]::ASCII.GetBytes('x'))) }
        $this.Files[$this.Key($dst)] = [pscustomobject]@{ Path = [string]$dst; Bytes = $b }; $this.Writes++
    }
    $fs | Add-Member -MemberType ScriptMethod -Name WriteJson -Value { param($p, $o) [void]$this.Calls.Add("writejson $p"); if ($this.FailJsonMatch -and ([string]$p -match $this.FailJsonMatch)) { throw 'stand-in: disk full' }; $this.Files[$this.Key($p)] = [pscustomobject]@{ Path = [string]$p; Bytes = [Text.Encoding]::UTF8.GetBytes((ConvertTo-Json -InputObject $o -Depth 16)) }; $this.Writes++ }
    $fs | Add-Member -MemberType ScriptMethod -Name WriteBytesOnce -Value {
        param($p, [byte[]]$b)
        [void]$this.Calls.Add("writebytes $p"); if ($this.FailWriteBytes) { throw 'fake write failure' }
        $k = $this.Key($p)
        if ($this.Files.ContainsKey($k)) { if ((Get-C4BytesSha $this.Files[$k].Bytes) -eq (Get-C4BytesSha $b)) { return 'exists-same' }; return 'exists-different' }
        $this.Files[$k] = [pscustomobject]@{ Path = [string]$p; Bytes = $b }; $this.Writes++; return 'written'
    }
    $fs | Add-Member -MemberType ScriptMethod -Name ReadBytes -Value { param($p, $max) $k = $this.Key($p); if ($this.Links.ContainsKey($k)) { throw "refusing to read '$p': it is a reparse point" }; if (-not $this.Files.ContainsKey($k)) { throw "no file $p" }; return , ([byte[]]$this.Files[$k].Bytes) }
    $fs | Add-Member -MemberType ScriptMethod -Name ListFiles -Value {
        param($dir, $filter)
        $d = $this.Key($dir); $out = @()
        foreach ($e in @($this.Files.Values) + @($this.Links.Values)) {
            if ([IO.Path]::GetDirectoryName($e.Path).ToLowerInvariant() -eq $d) { $n = [IO.Path]::GetFileName($e.Path); if ($n -like $filter) { $out += [pscustomobject]@{ Name = $n; FullName = $e.Path; IsLink = $this.Links.ContainsKey($this.Key($e.Path)); IsDir = $false } } }
        }
        foreach ($e in @($this.Dirs.Values)) {
            if ([IO.Path]::GetDirectoryName(([string]$e.Path).TrimEnd('\')).ToLowerInvariant() -eq $d) { $n = [IO.Path]::GetFileName(([string]$e.Path).TrimEnd('\')); if ($n -like $filter) { $out += [pscustomobject]@{ Name = $n; FullName = $e.Path; IsLink = $false; IsDir = $true } } }
        }
        return , @($out)
    }
    $fs | Add-Member -MemberType ScriptMethod -Name RemoveTree -Value {
        param($p)
        [void]$this.Calls.Add("removetree $p"); $d = $this.Key($p)
        foreach ($store in @($this.Files, $this.Dirs, $this.Links)) { foreach ($k in @($store.Keys)) { if ($k -eq $d -or $k.StartsWith("$d\")) { $store.Remove($k) } } }
        $this.Writes++
    }
    $fs | Add-Member -MemberType ScriptMethod -Name Sha256Raw -Value { param($p) $k = $this.Key($p); if ($this.Files.ContainsKey($k)) { Get-C4BytesSha $this.Files[$k].Bytes } else { $null } }
    $fs | Add-Member -MemberType ScriptMethod -Name ReadText -Value { param($p) $k = $this.Key($p); if (-not $this.Files.ContainsKey($k)) { throw "no file $p" }; [Text.Encoding]::UTF8.GetString($this.Files[$k].Bytes) }
    return $fs
}

function New-C4FakeAcct {
    # The account stand-in: the same read methods as the real seam, answering from switches; it records every call by name.
    param([string]$NcoSid, [string[]]$AdminMembers = @())
    $a = [pscustomobject]@{ Kind = 'fake'; Calls = (New-Object System.Collections.ArrayList); NcoSid = $NcoSid; NcoUse = 1; NcoDomain = 'TESTPC'; LookupError = 1332; AdminMembers = @($AdminMembers); AdminsReadable = $true
                            NcoMemberSids = @($NcoSid); NetUserExit = 0; NetUserText = "User name                    nco-probe`r`nThe command completed successfully.`r`n"; GroupMemberNames = @('nco-probe'); NetLocalGroupExit = 0; ProfileExists = $true
                            ProfileListPresent = $false; ProfileListImage = $null; ProfileFolderNames = @(); ProfileFoldersReadable = $true; LookupThrows = $false }
    $a | Add-Member -MemberType ScriptMethod -Name Lookup -Value { param($name) [void]$this.Calls.Add('Lookup'); if ($this.LookupThrows) { throw 'stand-in: Get-LocalUser is not recognized' }; if ($this.NcoSid) { [ordered]@{ Ok = $true; Sid = $this.NcoSid; Domain = $this.NcoDomain; Use = $this.NcoUse; Error = 0 } } else { [ordered]@{ Ok = $false; Sid = $null; Domain = $null; Use = 0; Error = $this.LookupError } } }
    $a | Add-Member -MemberType ScriptMethod -Name MemberSids -Value {
        param($g)
        [void]$this.Calls.Add('MemberSids')
        if ($g -eq 'S-1-5-32-544') { if (-not $this.AdminsReadable) { return [ordered]@{ Ok = $false; Sids = @(); Via = 'fake'; Error = 'fake unreadable' } }; return [ordered]@{ Ok = $true; Sids = @($this.AdminMembers); Via = 'fake'; Error = $null } }
        return [ordered]@{ Ok = $true; Sids = @($this.NcoMemberSids | Where-Object { $_ }); Via = 'fake'; Error = $null }
    }
    $a | Add-Member -MemberType ScriptMethod -Name NetUser -Value { param($name) [void]$this.Calls.Add('NetUser'); [ordered]@{ Exit = $this.NetUserExit; Text = $this.NetUserText } }
    $a | Add-Member -MemberType ScriptMethod -Name NetLocalGroup -Value {
        param($name)
        [void]$this.Calls.Add('NetLocalGroup')
        $t = "Alias name     $name`r`nComment        fake`r`n`r`nMembers`r`n`r`n-------------------------------------------------------------------------------`r`n" + ((@($this.GroupMemberNames) | ForEach-Object { "$_`r`n" }) -join '') + "The command completed successfully.`r`n"
        [ordered]@{ Exit = $this.NetLocalGroupExit; Text = $t }
    }
    $a | Add-Member -MemberType ScriptMethod -Name GroupName -Value { param($sid) [void]$this.Calls.Add('GroupName'); 'BUILTIN\Network Configuration Operators' }
    $a | Add-Member -MemberType ScriptMethod -Name ProfileDir -Value { param($name) [void]$this.Calls.Add('ProfileDir'); "Z:\Users\$name" }
    $a | Add-Member -MemberType ScriptMethod -Name PathExists -Value { param($p) [void]$this.Calls.Add('PathExists'); $this.ProfileExists }
    $a | Add-Member -MemberType ScriptMethod -Name ProfileListEntry -Value { param($sid) [void]$this.Calls.Add('ProfileListEntry'); [ordered]@{ Present = $this.ProfileListPresent; ImagePath = $this.ProfileListImage; Error = $null } }
    $a | Add-Member -MemberType ScriptMethod -Name ProfileFolders -Value { param($name) [void]$this.Calls.Add('ProfileFolders'); if (-not $this.ProfileFoldersReadable) { return $null }; return , @($this.ProfileFolderNames | ForEach-Object { "Z:\Users\$_" }) }
    return $a
}

function New-C4TestCtx {
    # A complete fake context over a fake world: the library's fake harness, fake backend and fake export, this file's fake file system and account reads, a fake proof
    # token (with this process's nonce) and every gate at its default.
    param([Parameter(Mandatory)][string]$NcoSid, [Parameter(Mandatory)][string]$OperatorSid, [string[]]$OperatorGroups = @(), [string[]]$AdminMembers = @())
    $w = New-Nep5World
    $runner = New-FakeHalfset -World $w -OperatorSid $OperatorSid -OperatorGroups $OperatorGroups
    $be = New-Nep5FakeBackend -World $w
    $fs = New-C4FakeFs
    $root = 'Z:\c4-selftest'
    $exeBytes = [Text.Encoding]::ASCII.GetBytes('stand-in for the probe exe (text, never run)')
    $fs.Seed("$root\scripts\$($script:C4ProbeExeName)", $exeBytes)
    $acct = New-C4FakeAcct -NcoSid $NcoSid -AdminMembers $AdminMembers
    $cnt = [pscustomobject]@{ BackendOpens = 0; ManualRollbacks = 0; SecurityReads = (New-Object System.Collections.ArrayList) }
    $script:C4ProofNonce = 'c4-selftest-nonce'
    $tok = [pscustomobject]@{ Kind = 'Nep5Case4Proof'; Ok = $true; Problems = @(); Nonce = 'c4-selftest-nonce'; Written = [datetimeoffset]::Now; ProbeExeSha = (Get-C4BytesSha $exeBytes); ProbeCsSha = ('AB' * 32); HarnessSha = 'FAKE'; HarnessProofSha = 'FAKE' }
    $opT = [pscustomobject]@{ User = $OperatorSid; Groups = @($OperatorGroups) }; $asked = New-Object System.Collections.ArrayList
    $ctx = [pscustomobject]@{
        Kind = 'fake'; ScriptDir = "$root\scripts"; OutDir = "$root\scripts\nep5-out\case4"; PubRoot = "$root\pub"; BinDir = "$root\pub\bin"; DropDir = "$root\pub\drop"
        DriverProofPath = "$root\scripts\$($script:C4DriverProofName)"; HarnessProofPath = "$root\scripts\harness-proof.json"; ProbeExeSrc = "$root\scripts\$($script:C4ProbeExeName)"; ComputerName = 'TESTPC'
        World = $w; Backend = $be; Runner = $runner; Counters = $cnt; Token = $tok; ExeBytes = $exeBytes
        NewBackend = { $cnt.BackendOpens++; $be }.GetNewClosure()
        NewRunner = { param($sha) $runner }.GetNewClosure()
        TrustedHarnessSha = { 'FAKE' }
        Exporter = (New-Nep5FakeExporter -World $w)
        ManualRollback = { $cnt.ManualRollbacks++; [ordered]@{ Ok = $false; Rows = @(); Foreign = @(); Reason = 'stand-in: the manual rollback is never run by the self-test' } }.GetNewClosure()
        ReadWfpSecurity = { param($type, $guid) [void]$cnt.SecurityReads.Add("$type $guid"); Find-C4NetshSecurity -Type $type -Guid $guid -RunNetsh { param([string[]]$Argv) if (($Argv -join ' ') -match 'guid=\{') { [pscustomobject]@{ exit = 1; text = 'The parameter is incorrect.' } } else { [pscustomobject]@{ exit = 0; text = "O:BAG:BAD:(A;;0xf00ff;;;BA)(A;;0x4;;;NO)`r`n" } } } }.GetNewClosure()
        Fs = $fs; Acct = $acct
        OperatorToken = { $opT }.GetNewClosure(); IsElevated = { $true }; Is64Bit = { $true }; AdminOnlyAsked = $asked; AdminOnly = { param($p) [void]$asked.Add([string]$p); [ordered]@{ Ok = $true; Problems = @(); Checked = 1 } }.GetNewClosure()
        SidResolver = { param($which) $null }; Now = { [datetimeoffset]::Now }
        ProofCheck = { param($c) $tok }.GetNewClosure()
        Close = { }
    }
    Add-C4DefaultGates $ctx
    $script:N5LiveProof = $ctx.HarnessProofPath
    return $ctx
}

function New-C4TestRecord {
    # A record in the probe's own shape (probe/NcoProbe.cs, RunCmd), for the stand-in drop folder. -OpenFailed gives the engine-open failure record. The token
    # state defaults to the one the condition is defined by (F 3 + NCO, E 2 + NCO, S 3 + Administrators deny-only, A 2 + Administrators enabled); -Elevation,
    # -NcoPresent (true, false or 'unreadable'), -NcoDenyOnly (present, attributes 0x10) and -Admins ('absent', 'deny-only', 'enabled') override it.
    param([Parameter(Mandatory)][string]$Cond, [Parameter(Mandatory)][string]$UserSid, [bool]$Expected, [Parameter(Mandatory)][string]$ExeSha, [datetimeoffset]$At = [datetimeoffset]::Now, [long]$ProcId = 4242,
          [string]$AddRc = '0x00000000', [string]$DelRc = '0x00000000', $DelPresent = $false, [int]$Elevation = 0, [string]$Integrity = '', [string]$CsSha = ('ab' * 32), [string]$ProofSha = ('ee' * 32),
          [string]$NcoSid = '', $NcoPresent = $null, [string]$Admins = '', [switch]$OpenFailed, [switch]$WrongPrincipal, [switch]$OpenThrew, [switch]$AddThrew, [switch]$DeleteThrew,
          [switch]$CloseThrew, [switch]$NcoDenyOnly)
    if ($Elevation -eq 0) { $Elevation = $(if ($Cond -in @('E', 'A')) { 2 } else { 3 }) }
    if (-not $Integrity) { $Integrity = $(if ($Elevation -eq 2) { 'high' } else { 'medium' }) }
    if ($null -eq $NcoPresent) { $NcoPresent = ($Cond -in @('F', 'E')) }
    if (-not $Admins) { $Admins = $(switch ($Cond) { 'S' { 'deny-only' } 'A' { 'enabled' } default { 'absent' } }) }
    $stamp = $At.UtcDateTime.ToString('yyyyMMdd-HHmmss'); $name = "case4-$Cond-$stamp-$ProcId.json"
    $clk = [ordered]@{ local = $At.ToString("yyyy-MM-dd'T'HH:mm:ss.fffzzz"); utc = $At.UtcDateTime.ToString("yyyy-MM-dd'T'HH:mm:ss.fff'Z'") }
    $elevLabel = @{ 1 = 'default'; 2 = 'full'; 3 = 'limited' }[$Elevation]
    $r = [ordered]@{
        schema = $script:C4RecordSchema; subcommand = 'run'; probe_version = 'stand-in'; toggle_build = $false; probe_exe_path = 'Z:\pub\bin\ncoprobe.exe'
        probe_exe_sha256 = $ExeSha.ToLowerInvariant(); probe_exe_sha256_error = $null; probe_cs_sha256 = $CsSha.ToLowerInvariant(); pid = $ProcId; command_line = "ncoprobe.exe run --cond $Cond"
        cond = $Cond; clock_start = $clk; proof = [ordered]@{ given = 'Z:\pub\bin\nco-probe-live.json'; sha256 = $ProofSha.ToLowerInvariant(); display_name = $script:C4DisplayName; extra_keys = @(); interlock_toggled_off = $false }
        stale_sid = [ordered]@{ sid = $script:N5StaleSid; mapped = $false; lookup_error = 1332; name = $null; accepted = $true }; out_dir = 'Z:\pub\drop'; clock = $clk
        user = [ordered]@{ sid = $UserSid; attributes = '0x00000000'; error = 0 }; user_sid = $UserSid
        groups = [ordered]@{ error = 0; count = 2; items = @() }
        nco_group = $(if ($NcoPresent -is [string]) { [ordered]@{ sid = 'S-1-5-32-556'; present = $NcoPresent } } elseif ($NcoDenyOnly) { [ordered]@{ sid = 'S-1-5-32-556'; present = $true; attributes = '0x00000010'; enabled = $false; enabled_by_default = $false; use_for_deny_only = $true } } elseif ($NcoPresent) { [ordered]@{ sid = 'S-1-5-32-556'; present = $true; attributes = '0x00000007'; enabled = $true; enabled_by_default = $true; use_for_deny_only = $false } } else { [ordered]@{ sid = 'S-1-5-32-556'; present = $false } })
        administrators = $(switch ($Admins) {
            'deny-only' { [ordered]@{ sid = 'S-1-5-32-544'; present = $true; attributes = '0x00000010'; enabled = $false; enabled_by_default = $false; use_for_deny_only = $true } }
            'enabled' { [ordered]@{ sid = 'S-1-5-32-544'; present = $true; attributes = '0x0000000F'; enabled = $true; enabled_by_default = $true; use_for_deny_only = $false } }
            default { [ordered]@{ sid = 'S-1-5-32-544'; present = $false } } })
        integrity = [ordered]@{ sid = $(if ($Integrity -eq 'high') { 'S-1-16-12288' } else { 'S-1-16-8192' }); label = $Integrity; attributes = '0x00000060'; error = 0 }
        elevation_type = [ordered]@{ value = $Elevation; label = $elevLabel; error = 0 }; elevation = [ordered]@{ elevated = ($Elevation -eq 2); error = 0 }
        linked_token = [ordered]@{ present = ($Elevation -ne 1); error = 0; closed = ($Elevation -ne 1) }; session_id = [ordered]@{ value = 1; error = 0 }
        expected_account = [ordered]@{ name = 'nco-probe'; sid = $(if ($NcoSid) { $NcoSid } else { $null }); domain = 'TESTPC'; sid_type = 'user'; error = 0 }
        is_expected_account = $Expected; stamp_utc = $stamp; record_file_name = $name; principal = [ordered]@{ accepted = (-not $WrongPrincipal); detail = $(if ($WrongPrincipal) { 'stand-in: wrong principal' } else { $null }) }
        filter = [ordered]@{ key = $script:C4ProbeKey; sublayer = $script:N5SubLayers.S2; provider = $script:N5ProviderKey }
    }
    if ($WrongPrincipal) {
        $r.engine = [ordered]@{ open = [ordered]@{ call = $null; rc = $null; opened = $false; error = $null }; closed = $false; close_rc = $null; close_error = $null }
        $r.add = [ordered]@{ attempted = $false; error = $null }; $r.delete = [ordered]@{ attempted = $false; error = $null }; $r.sequence_complete = $null
        $r.overall = 'wrong_principal'; $r.residue = 'none_added'; $r.exit = 12; $r.operator_action = $script:C4ProbeStopLineWrongPrincipal
    } elseif ($OpenFailed -or $OpenThrew) {
        $r.engine = [ordered]@{ open = [ordered]@{ call = 'FwpmEngineOpen0'; rc = $(if ($OpenThrew) { $null } else { '0x80070005' }); opened = $false; error = $(if ($OpenThrew) { 'stand-in: the open threw' } else { $null }) }; closed = $false; close_rc = $null; close_error = $null }
        $r.add = [ordered]@{ attempted = $false; error = $null }; $r.delete = [ordered]@{ attempted = $false; error = $null }; $r.sequence_complete = (-not $OpenThrew)
        $r.overall = $(if ($OpenThrew) { 'incomplete' } else { 'open_failed' }); $r.residue = 'none_added'; $r.exit = $(if ($OpenThrew) { 11 } else { 7 }); $r.operator_action = $null
    } else {
        $ac = Get-C4RcClass -Rc (Get-C4RcValue $AddRc) -Kind add; $dc = Get-C4RcClass -Rc (Get-C4RcValue $DelRc) -Kind delete
        $left = ($DelPresent -is [bool]) -and $DelPresent
        if ($AddThrew) { $ac = 'other' }; if ($DeleteThrew) { $dc = 'other' }
        $r.engine = [ordered]@{ open = [ordered]@{ call = 'FwpmEngineOpen0'; rc = '0x00000000'; opened = $true; error = $null }; closed = (-not $CloseThrew); close_rc = $(if ($CloseThrew) { $null } else { '0x00000000' }); close_error = $(if ($CloseThrew) { 'stand-in: the close threw' } else { $null }) }
        $r.add = [ordered]@{ attempted = $true; rc = $(if ($AddThrew) { $null } else { $AddRc }); class = $ac; filter_id = $(if ($ac -eq 'succeeded') { 70001 } else { $null }); present_after = ($ac -eq 'succeeded'); get_rc = $(if ($ac -eq 'succeeded') { '0x00000000' } else { '0x80320003' }); error = $(if ($AddThrew) { 'stand-in: the add threw' } else { $null }) }
        $r.delete = [ordered]@{ attempted = $true; rc = $(if ($DeleteThrew) { $null } else { $DelRc }); class = $dc; present_after = $DelPresent; get_rc = $(if ($left) { '0x00000000' } else { '0x80320003' }); error = $(if ($DeleteThrew) { 'stand-in: the delete threw' } else { $null }) }
        $threw = [bool]($AddThrew -or $DeleteThrew -or $CloseThrew); $r.sequence_complete = (-not $threw)
        $possibly = (-not $left) -and ($AddThrew -or ($ac -eq 'succeeded')) -and -not ((-not $DeleteThrew) -and ($dc -eq 'succeeded')) -and -not (($DelPresent -is [bool]) -and -not $DelPresent)
        $r.overall = $(if ($left) { 'filter_left_behind' } elseif ($possibly) { 'filter_possibly_left_behind' } elseif ($threw) { 'incomplete' } else { 'ok' }); $r.residue = $(if ($left) { 'present' } elseif ($DelPresent -is [bool]) { 'absent' } else { 'unknown' }); $r.exit = $(if ($left -or $possibly) { 8 } elseif ($threw) { 11 } else { 0 })
        $r.operator_action = $(if ($r.exit -in @(8, 11)) { $script:C4ProbeStopLine } else { $null })
    }
    $r.clock_end = $clk
    return $r
}

function Add-C4TestDrop {
    # Puts a record into the stand-in drop folder under its own name (or $Name).
    param([Parameter(Mandatory)]$Ctx, [Parameter(Mandatory)]$Record, [string]$Name)
    if (-not $Name) { $Name = [string]$Record.record_file_name }
    $Ctx.Fs.Seed((Join-C4Path $Ctx.DropDir $Name), [Text.Encoding]::UTF8.GetBytes((ConvertTo-Json -InputObject $Record -Depth 10)))
    return $Name
}

function Add-C4FakeFilter {
    param([Parameter(Mandatory)]$World, [Parameter(Mandatory)][string]$Key, [Parameter(Mandatory)][string]$SubLayer, [Parameter(Mandatory)][string]$Name)
    $World.Filters[$Key] = [pscustomobject]@{ Key = $Key; SubLayer = $SubLayer; Layer = 'v4'; Name = $Name; Kind = ''; Tool = ''; Sid = $script:N5StaleSid; HasUser = $true; Action = 'block'; HasRemote = $false; RemotePort = 0 }
}

# ---- -SelfTest ----------------------------------------------------------------------------------------------------------------------------------------------------
function Invoke-C4SelfTest {
    $script:c4Fail = 0; $script:c4Total = 0; $script:c4TagsPassed = New-Object System.Collections.ArrayList; $script:c4TagsFailed = New-Object System.Collections.ArrayList; $script:c4FailedNames = New-Object System.Collections.ArrayList
    function Chk([string]$n, [bool]$c, [string[]]$tags = @()) {
        $script:c4Total++
        if ($c) { Write-Host "  [PASS] $n" -ForegroundColor Green; foreach ($t in $tags) { if ($t) { [void]$script:c4TagsPassed.Add($t) } } }
        else { Write-Host "  [FAIL] $n" -ForegroundColor Red; $script:c4Fail++; [void]$script:c4FailedNames.Add($n); foreach ($t in $tags) { if ($t) { [void]$script:c4TagsFailed.Add($t) } } }
    }
    $s1 = $script:N5SubLayers.S1; $s2 = $script:N5SubLayers.S2; $s3 = $script:N5SubLayers.S3
    $dom = $script:N5StaleSid -replace '-\d+$', ''   # fake SIDs share the library's fabricated stale domain; no SID of this machine is written here
    $opSid = "$dom-1001"; $opGrp = "$dom-513"; $ncoSid = "$dom-5001"; $otherSid = "$dom-5002"
    $opGroups = @($opGrp, $script:C4UsersSid, 'S-1-1-0', $script:C4AdminsSid)
    $foreignSl = '11111111-2222-3333-4444-555555555555'
    $mk = { param([string[]]$Admins = @()) New-C4TestCtx -NcoSid $ncoSid -OperatorSid $opSid -OperatorGroups $opGroups -AdminMembers $Admins }

    Write-Host '== libraries, the wrapped script and the compile (no engine is opened) ==' -ForegroundColor Cyan
    $libOk = (@($script:C4LibFiles | Where-Object { [string]$script:LoadedLibHashes[$_] -match '^[0-9A-F]{64}$' }).Count -eq $script:C4LibFiles.Count)
    $libFrom = @($script:C4LoadedLibPaths.Values | ForEach-Object { Split-Path $_ -Parent } | Select-Object -Unique)
    Chk "the four libraries were read once through Get-VerifiedLibBlock and hashed (from: $($libFrom -join '; '))" $libOk
    $imp = Import-WfpHelpers -Path $WfpScript -ExpectedSha256 $WfpSha256 -Unverified:(-not $WriteProof)
    Chk 'the wrapped script''s helpers were extracted (the script is only read) and its SHA-256 recorded' (($imp.Functions.Count -eq $script:WrappedFunctions.Count) -and ($imp.Sha256 -match '^[0-9A-F]{64}$'))
    Initialize-Nep5Type
    Chk 'the WFP C# and the nep5 C# compile together in-process (nothing is opened)' ([bool]('BlarAI.Nep5.N5Engine' -as [type]))
    $libKeys = @($script:N5FilterKeys.Values) + @($script:N5SubLayers.Values) + @($script:N5ProviderKey, $script:N5MissingSubLayer)
    Chk 'constants: the probe''s filter key is a lower-case GUID distinct from every library key, sublayer and the provider; S2, the provider, the layer and the stale SID are the library''s' (((ConvertTo-N5Guid $script:C4ProbeKey) -ceq $script:C4ProbeKey) -and ($libKeys -notcontains $script:C4ProbeKey) -and ($s2 -eq '3e29ae7e-fd9f-413a-8b8d-da9bd3a96359') -and ($script:N5ProviderKey -eq '3e29ae7e-fd9f-413a-8b8d-da9bd3a96360') -and ($script:N5LayerV4 -eq 'c38d57d1-05a7-4c33-904f-7fbceee60e82'))
    Chk 'constants: the display name starts with the library marker, is at most 120 characters; the public paths carry no space; the stale SID does not resolve here is checked by -Prepare, not assumed' (($script:C4DisplayName.StartsWith($script:N5Marker)) -and ($script:C4DisplayName.Length -le 120) -and ($script:C4PubRoot -notmatch '\s') -and ($script:C4RequiredTags.Count -eq 26))

    Write-Host '== pure functions: status classes, names, arguments, plans ==' -ForegroundColor Cyan
    $cls = @([uint32]0, [uint32]5, [uint32]2147942405, [uint32]2150760488, [uint32]2150760451, [uint32]2150760455, [uint32]3735928559 | ForEach-Object { "$(Get-C4RcClass -Rc $_ -Kind add)/$(Get-C4RcClass -Rc $_ -Kind delete)" })
    Chk "status classes: 0, 0x5, 0x80070005, 0x80320028 (FWP_E_OUT_OF_BOUNDS), 0x80320003, 0x80320007, 0xDEADBEEF -> $($cls -join ', ')" (($cls -join ',') -ceq 'succeeded/succeeded,denied/denied,denied/denied,other/other,other/not_found,other/other,other/other')
    Chk 'status text: 0x and eight hex digits only (0x5, 5, 0xZZZZZZZZ and a number are refused)' (((Get-C4RcValue '0x80320003') -eq [uint32]2150760451) -and ($null -eq (Get-C4RcValue '0x5')) -and ($null -eq (Get-C4RcValue '5')) -and ($null -eq (Get-C4RcValue '0xZZZZZZZZ')) -and ($null -eq (Get-C4RcValue 5)))
    $t0 = [datetimeoffset]::new(2026, 10, 19, 21, 5, 9, [timespan]::FromHours(-4))
    $nm = Get-C4RecordName -Cond 'E' -Utc $t0 -ProcessId 1234
    Chk "record name: '$nm' (UTC stamp), matched by the record-name pattern; a lower-case cond, a missing pid and a .txt are not" (($nm -ceq 'case4-E-20261020-010509-1234.json') -and ($nm -match $script:C4RecordNameRe) -and ('case4-e-20261020-010509-1234.json' -cnotmatch $script:C4RecordNameRe) -and ('case4-E-20261020-010509-.json' -notmatch $script:C4RecordNameRe) -and ('case4-E-20261020-010509-1234.txt' -notmatch $script:C4RecordNameRe))
    Chk "self name: the driver proof binds this file as $($script:C4SelfName); this run's file is $(Split-Path -Leaf $PSCommandPath) (any other name fails this check)" (($script:C4SelfName -ceq 'spike-nep5-c4-driver.ps1') -and ((Split-Path -Leaf $PSCommandPath) -ceq $script:C4SelfName) -and ($script:C4TextFiles -ccontains $script:C4SelfName))
    $mode = { param($on) $h = @{ SelfTest = $false; DryRun = $false; Check = $false; Prepare = $false; Collect = $false; Finish = $false; PartD = $false }; foreach ($o in $on) { $h[$o] = $true }; $h }
    Chk 'arguments: no mode and two modes are errors; each single mode is valid; -WriteProof only with -SelfTest' (((Test-C4Args (& $mode @()) $false).Count -ge 1) -and ((Test-C4Args (& $mode @('Prepare', 'Finish')) $false).Count -ge 1) -and (@('SelfTest', 'DryRun', 'Check', 'Prepare', 'Collect', 'Finish', 'PartD' | Where-Object { (Test-C4Args (& $mode @($_)) $false).Count -ne 0 }).Count -eq 0) -and ((Test-C4Args (& $mode @('Prepare')) $true).Count -ge 1) -and ((Test-C4Args (& $mode @('SelfTest')) $true).Count -eq 0))
    Chk 'arguments: -ElevationRefused is accepted with -Collect and -Finish only, as one printable line of at most 300 characters' (((Test-C4Args (& $mode @('Collect')) $false 'Windows refused to elevate nco-probe').Count -eq 0) -and ((Test-C4Args (& $mode @('Finish')) $false 'x').Count -eq 0) -and ((Test-C4Args (& $mode @('Check')) $false 'x').Count -ge 1) -and ((Test-C4Args (& $mode @('Prepare')) $false 'x').Count -ge 1) -and ((Test-C4Args (& $mode @('Collect')) $false ('x' * 301)).Count -ge 1) -and ((Test-C4Args (& $mode @('Collect')) $false "a`nb").Count -ge 1))
    Chk 'arguments: an -ElevationRefused note carrying ''@'' or ''MicrosoftAccount'' (any case) is refused, so it never quotes an account; a plain note is accepted' (((Test-C4Args (& $mode @('Collect')) $false 'the prompt showed @ only').Count -ge 1) -and ((Test-C4Args (& $mode @('Finish')) $false 'shown as microsoftaccount only').Count -ge 1) -and ((Test-C4Args (& $mode @('Collect')) $false 'Windows refused to elevate nco-probe').Count -eq 0))
    $plan = Get-C4PrepPlan
    Chk 'plan: our provider and S2 naming it, in one set, and nothing else; the library''s own plan gate accepts it' ($plan.Provider -and ($plan.SubLayer -ceq $s2) -and $plan.SubLayerUsesProvider -and (@(Get-C4PlanProblems -Plan $plan).Count -eq 0) -and (@(Get-Nep5PlanProblems -Plan $plan).Count -eq 0)) 'plan-provider-and-s2-only'
    $pS1 = Get-C4PrepPlan; $pS1.SubLayer = $s1; $pS3 = Get-C4PrepPlan; $pS3.SubLayer = $s3; $pOther = Get-C4PrepPlan; $pOther.SubLayer = $foreignSl; $pNoProv = Get-C4PrepPlan; $pNoProv.Provider = $false; $pNoUse = Get-C4PrepPlan; $pNoUse.SubLayerUsesProvider = $false
    Chk 'plan: S1, S3 or any other sublayer, no provider, or S2 not naming the provider are each refused' ((@(Get-C4PlanProblems -Plan $pS1).Count -ge 1) -and (@(Get-C4PlanProblems -Plan $pS3).Count -ge 1) -and (@(Get-C4PlanProblems -Plan $pOther).Count -ge 1) -and (@(Get-C4PlanProblems -Plan $pNoProv).Count -ge 1) -and (@(Get-C4PlanProblems -Plan $pNoUse).Count -ge 1)) 'plan-provider-and-s2-only'
    $pF = Get-C4PrepPlan; $pF.Filters = @(New-N5FilterDescriptor -Id 's2-block-v4' -SubLayer $s2 -V6 $false -Permit $false -Sid $script:N5StaleSid -UseProvider $true)
    $pA = Get-C4PrepPlan; $pA.Attempts = @(New-N5FilterDescriptor -Id 's2-noprov-block-v4' -SubLayer $s2 -V6 $false -Permit $false -Sid $script:N5StaleSid -UseProvider $false)
    Chk 'plan: a plan carrying a filter, or an attempt, is refused (the probe''s filter is the probe''s own)' ((@(Get-C4PlanProblems -Plan $pF).Count -ge 1) -and (@(Get-C4PlanProblems -Plan $pA).Count -ge 1) -and ($plan.Filters.Count -eq 0) -and ($plan.Attempts.Count -eq 0)) 'plan-no-filters'

    Write-Host '== the public folder''s DACLs (pure, in-memory security objects) ==' -ForegroundColor Cyan
    $aclArgs = @{ NcoSid = $ncoSid; NcoUse = 1; NcoDomain = 'TESTPC'; ComputerName = 'TESTPC'; OperatorSid = $opSid; OperatorGroups = $opGroups; AdminMembers = @($opSid); AdminsReadable = $true }
    $ap = Get-C4AclPlan @aclArgs; $ap2 = Get-C4AclPlan @aclArgs
    $rr = { param($k) @($ap.Rows[$k] | ForEach-Object { "$($_.sid)=$($_.rights)" }) -join ',' }
    $wantRoot = "S-1-5-18=FullControl,S-1-5-32-544=FullControl,S-1-5-32-545=ReadAndExecute"; $wantDrop = "S-1-5-18=FullControl,S-1-5-32-544=FullControl,$ncoSid=Modify,$opSid=Modify"
    Chk 'ACL plan: root and bin are SYSTEM and Administrators full control plus Users read and execute; drop is SYSTEM and Administrators full control plus the account and the operator Modify' ($ap.Ok -and ((& $rr 'root') -ceq $wantRoot) -and ((& $rr 'bin') -ceq $wantRoot) -and ((& $rr 'drop') -ceq $wantDrop)) 'acl-plan-pure'
    $parsed = Get-C4AclRules -Sddl $ap.Sddl.drop
    Chk 'ACL plan: every DACL is protected, every ACE is explicit and inherited by folders and files; the same inputs give byte-identical SDDL' ((@('root', 'bin', 'drop' | Where-Object { -not (Get-C4AclRules -Sddl $ap.Sddl[$_]).Protected }).Count -eq 0) -and ($parsed.Rules.Count -eq 4) -and (@($parsed.Rules | Where-Object { $_ -notmatch '\|Allow\|3\|0\|explicit$' }).Count -eq 0) -and ($ap.Sddl.drop -ceq $ap2.Sddl.drop) -and ($ap.Sddl.root -ceq $ap2.Sddl.root)) 'acl-plan-pure'
    $selfTextP = [IO.File]::ReadAllText($PSCommandPath)
    $pureFns = @('Get-C4AclPlan', 'Get-C4AclPlanProblems', 'ConvertTo-C4Sddl', 'Get-C4DropSddlAfterRemoval', 'Get-C4AclRules', 'Compare-C4Acl', 'Test-C4AceRemoval')
    $pureAllowed = @('Get-C4AclPlanProblems', 'ConvertTo-C4Sddl', 'Get-C4AclRules', 'Compare-C4Acl', 'Test-CoderSidSafe', 'ForEach-Object', 'Where-Object', 'Select-Object', 'Sort-Object')
    $impure = @(Get-C4ImpureCalls -Text $selfTextP -Functions $pureFns -AllowedCommands $pureAllowed)
    $pAst = [Management.Automation.Language.Parser]::ParseInput($selfTextP, [ref]$null, [ref]$null)
    $plantPure = { param($code) $f = $pAst.Find({ param($x) $x -is [Management.Automation.Language.FunctionDefinitionAst] -and $x.Name -eq 'Get-C4AclPlan' }, $true); $o = $f.Body.Extent.StartOffset + 1; $selfTextP.Substring(0, $o) + "`n    " + $code + "`n" + $selfTextP.Substring($o) }
    $impMiss = @(foreach ($ip in @($script:C4Corpus.fixtures.impure_plants)) { $r = @(Get-C4ImpureCalls -Text (& $plantPure $ip.code) -Functions $pureFns -AllowedCommands $pureAllowed); if (@($r | Where-Object { $_ -match $ip.finding }).Count -ne 1) { $ip.code } })
    Chk "ACL plan: the seven ACL functions call nothing but each other, the arms' SID check, pipeline cmdlets and in-memory security objects; each of the lock corpus's $(@($script:C4Corpus.fixtures.impure_plants).Count) planted file or registry calls is found $(if ($impure.Count + $impMiss.Count) { '(found: ' + ($impure -join ', ') + '; missed: ' + ($impMiss -join ', ') + ')' })" (($impure.Count -eq 0) -and (@($script:C4Corpus.fixtures.impure_plants).Count -ge 3) -and ($impMiss.Count -eq 0)) 'acl-plan-pure'
    $adm = Get-C4AclPlan -NcoSid $ncoSid -NcoUse 1 -NcoDomain 'TESTPC' -ComputerName 'TESTPC' -OperatorSid $opSid -OperatorGroups $opGroups -AdminMembers @($opSid, $ncoSid)
    $admU = Get-C4AclPlan -NcoSid $ncoSid -NcoUse 1 -NcoDomain 'TESTPC' -ComputerName 'TESTPC' -OperatorSid $opSid -OperatorGroups $opGroups -AdminMembers @() -AdminsReadable $false
    Chk 'ACL plan: an account that is a member of Administrators is a STOP (no plan); unreadable Administrators members are a refusal (no plan)' ((-not $adm.Ok) -and (@($adm.Stop | Where-Object { $_ -match 'Administrators' }).Count -eq 1) -and (-not $admU.Ok) -and (@($admU.Refuse).Count -ge 1)) 'acl-refuses-admin-member'
    $grpA = Get-C4AclPlan -NcoSid $ncoSid -NcoUse 4 -NcoDomain 'TESTPC' -ComputerName 'TESTPC' -OperatorSid $opSid -OperatorGroups $opGroups; $grpG = Get-C4AclPlan -NcoSid $ncoSid -NcoUse 2 -NcoDomain 'TESTPC' -ComputerName 'TESTPC' -OperatorSid $opSid -OperatorGroups $opGroups
    $grpW = Get-C4AclPlan -NcoSid $script:C4UsersSid -NcoUse 4 -NcoDomain 'BUILTIN' -ComputerName 'TESTPC' -OperatorSid $opSid -OperatorGroups $opGroups; $grpE = Get-C4AclPlan -NcoSid 'S-1-1-0' -NcoUse 5 -NcoDomain '' -ComputerName 'TESTPC' -OperatorSid $opSid -OperatorGroups $opGroups
    Chk 'ACL plan: a name that resolves to a local group (alias), a group, BUILTIN\Users or Everyone is refused (no plan)' ((-not $grpA.Ok) -and (-not $grpG.Ok) -and (-not $grpW.Ok) -and (-not $grpE.Ok) -and (@($grpA.Refuse | Where-Object { $_ -match 'not a user' }).Count -eq 1)) 'acl-refuses-group'
    $opS = Get-C4AclPlan -NcoSid $opSid -NcoUse 1 -NcoDomain 'TESTPC' -ComputerName 'TESTPC' -OperatorSid $opSid -OperatorGroups $opGroups; $opG = Get-C4AclPlan -NcoSid $opGrp -NcoUse 1 -NcoDomain 'TESTPC' -ComputerName 'TESTPC' -OperatorSid $opSid -OperatorGroups $opGroups
    Chk 'ACL plan: the operator''s own SID and a group in his token are each a STOP (no plan)' ((-not $opS.Ok) -and (@($opS.Stop | Where-Object { $_ -match 'operator''s own' }).Count -eq 1) -and (-not $opG.Ok) -and (@($opG.Stop | Where-Object { $_ -match 'operator''s token' }).Count -eq 1)) 'acl-refuses-operator-sid'
    $unres = Get-C4AclPlan -NcoSid $null -NcoUse 0 -OperatorSid $opSid -OperatorGroups $opGroups; $dom2 = Get-C4AclPlan -NcoSid $ncoSid -NcoUse 1 -NcoDomain 'CORP' -ComputerName 'TESTPC' -OperatorSid $opSid -OperatorGroups $opGroups
    Chk 'ACL plan: a name that does not resolve, or resolves in another domain, is refused' ((-not $unres.Ok) -and (@($unres.Refuse).Count -eq 1) -and (-not $dom2.Ok) -and (@($dom2.Refuse | Where-Object { $_ -match 'not a local account' }).Count -eq 1))
    $cmpOk = Compare-C4Acl -Expected $ap.Sddl.drop -Actual $ap.Sddl.drop; $cmpOwn = Compare-C4Acl -Expected $ap.Sddl.drop -Actual ($ap.Sddl.drop -replace '^O:BA', "O:$opSid")
    $cmpMiss = Compare-C4Acl -Expected $ap.Sddl.drop -Actual ($ap.Sddl.drop -replace '\([^()]*\)$', ''); $cmpExtra = Compare-C4Acl -Expected $ap.Sddl.root -Actual $ap.Sddl.drop; $cmpUnprot = Compare-C4Acl -Expected $ap.Sddl.root -Actual ($ap.Sddl.root -replace 'D:P', 'D:')
    Chk 'ACL plan and read-back: every folder is planned OWNED by Administrators; the planned SDDL reads back equal; the operator as owner, a missing ACE, other ACEs and an unprotected DACL are each not equal' (((Get-C4AclRules -Sddl $ap.Sddl.root).Owner -eq $script:C4AdminsSid) -and ((Get-C4AclRules -Sddl $ap.Sddl.bin).Owner -eq $script:C4AdminsSid) -and ((Get-C4AclRules -Sddl $ap.Sddl.drop).Owner -eq $script:C4AdminsSid) -and $cmpOk.Equal -and (-not $cmpOwn.Equal) -and (-not $cmpMiss.Equal) -and (-not $cmpExtra.Equal) -and (-not $cmpUnprot.Equal)) 'acl-plan-pure'
    $after = Get-C4DropSddlAfterRemoval
    Chk 'ACE removal: the reduced drop DACL is SYSTEM and Administrators only and passes the read-back; a read-back still carrying the account''s or the operator''s ACE fails it' ((Test-C4AceRemoval -Expected $after -Actual ('O:BA' + $after) -GoneSids @($ncoSid, $opSid)) -and -not (Test-C4AceRemoval -Expected $after -Actual $ap.Sddl.drop -GoneSids @($ncoSid, $opSid)) -and ((Get-C4AclRules -Sddl $after).Sids.Count -eq 2)) 'finish-ace-removal-read-back'
    $offAcl = Get-C4AclPlan -NcoSid $ncoSid -NcoUse 1 -NcoDomain 'TESTPC' -ComputerName 'TESTPC' -OperatorSid $opSid -OperatorGroups $opGroups -AdminMembers @($ncoSid) -ProblemsFn { param($i) [ordered]@{ Refuse = @(); Stop = @() } }
    Chk 'OFF: with the refusal switched off, a plan IS produced that grants an Administrators member Modify on drop (so the STOP above is the lock)' ($offAcl.Ok -and ((Get-C4AclRules -Sddl $offAcl.Sddl.drop).Sids -contains $ncoSid)) 'controls-tested-off'

    Write-Host '== the probe proof (the probe''s own arming rules, applied by the driver) ==' -ForegroundColor Cyan
    $exeH = 'C4' * 32; $csH = 'AB' * 32; $nowT = [datetimeoffset]::Now
    $pp = New-C4ProbeProof -ExeSha $exeH -CsSha $csH -Now $nowT
    Chk 'probe proof: exactly the eleven SPEC fields, lower-case hashes and GUIDs, the stale SID, the account, checks_failed 0, a Z time; it passes the rules' (((@($pp.Keys) -join ',') -ceq ($script:C4ProbeProofFields -join ',')) -and ($pp.probe_exe_sha256 -ceq $exeH.ToLowerInvariant()) -and ($pp.user_sid -ceq $script:N5StaleSid) -and ($pp.written_utc -match 'Z$') -and (@(Test-C4ProbeProof -Proof $pp -ExeSha $exeH -CsSha $csH -Now $nowT).Count -eq 0)) 'probe-proof-fields'
    $plant = [ordered]@{ schema = 'nep5-case4-probe-proof-v0'; probe_exe_sha256 = ('cd' * 32); probe_cs_sha256 = ('ef' * 32); sublayer = $s1; provider = $s2; filter_key = $script:N5FilterKeys['s2-block-v4']
                         user_sid = $opSid; display_name = ('x' * 121); expected_account = 'blarai-spike'; checks_failed = '0'; written_utc = $nowT.AddHours(-25).UtcDateTime.ToString("yyyy-MM-dd'T'HH:mm:ss'Z'") }
    $missed = @(foreach ($f in $plant.Keys) { $bad = New-C4ProbeProof -ExeSha $exeH -CsSha $csH -Now $nowT; $bad[$f] = $plant[$f]; $pr = @(Test-C4ProbeProof -Proof $bad -ExeSha $exeH -CsSha $csH -Now $nowT); if (@($pr | Where-Object { $_.StartsWith("${f}:") }).Count -ne 1 -or $pr.Count -ne 1) { "$f -> $($pr -join ' / ')" } })
    Chk "probe proof: each of the eleven fields planted wrong, one at a time, is refused with exactly that field named $(if ($missed.Count) { '(MISSED: ' + ($missed -join '; ') + ')' })" ($missed.Count -eq 0) 'probe-proof-fields'
    $fut = New-C4ProbeProof -ExeSha $exeH -CsSha $csH -Now $nowT.AddMinutes(6); $noZone = New-C4ProbeProof -ExeSha $exeH -CsSha $csH -Now $nowT; $noZone.written_utc = $nowT.ToString('yyyy-MM-ddTHH:mm:ss')
    $extra = New-C4ProbeProof -ExeSha $exeH -CsSha $csH -Now $nowT; $extra['note'] = 'x'; $boolCf = New-C4ProbeProof -ExeSha $exeH -CsSha $csH -Now $nowT; $boolCf.checks_failed = $false; $miss = New-C4ProbeProof -ExeSha $exeH -CsSha $csH -Now $nowT; $miss.Remove('provider')
    Chk 'probe proof: a time 6 min in the future, a time without a zone, an unexpected field, checks_failed false and a missing field are each refused' ((@(Test-C4ProbeProof -Proof $fut -ExeSha $exeH -CsSha $csH -Now $nowT).Count -ge 1) -and (@(Test-C4ProbeProof -Proof $noZone -ExeSha $exeH -CsSha $csH -Now $nowT).Count -ge 1) -and (@(Test-C4ProbeProof -Proof $extra -ExeSha $exeH -CsSha $csH -Now $nowT).Count -ge 1) -and (@(Test-C4ProbeProof -Proof $boolCf -ExeSha $exeH -CsSha $csH -Now $nowT).Count -ge 1) -and (@(Test-C4ProbeProof -Proof $miss -ExeSha $exeH -CsSha $csH -Now $nowT).Count -ge 1)) 'probe-proof-fields'
    $rt = ConvertFrom-C4Json -Text (ConvertTo-Json -InputObject $pp -Depth 4)
    Chk 'probe proof: the JSON round trip (what -Prepare reads back from bin\) still passes; the same proof checked against ANOTHER exe hash is refused on probe_exe_sha256' ((@(Test-C4ProbeProof -Proof $rt -ExeSha $exeH -CsSha $csH -Now $nowT).Count -eq 0) -and (@(Test-C4ProbeProof -Proof $rt -ExeSha ('DD' * 32) -CsSha $csH -Now $nowT | Where-Object { $_ -like 'probe_exe_sha256:*' }).Count -eq 1)) 'probe-proof-hash-binding'

    Write-Host '== the probe''s records (in the probe''s own shape) ==' -ForegroundColor Cyan
    $win0 = [datetimeoffset]::Now.AddMinutes(-30); $win1 = [datetimeoffset]::Now.AddMinutes(5); $rx = 'C4' * 32; $rcs = 'AB' * 32; $rps = 'EE' * 32
    $va = { param($rec, $name, $seen = @{}) if (-not $name) { $name = [string]$rec.record_file_name }; @(Test-C4Record -Record (ConvertFrom-C4Json -Text (ConvertTo-Json -InputObject $rec -Depth 10)) -FileName $name -ExeSha $rx -CsSha $rcs -ProofSha $rps -NcoSid $ncoSid -OperatorSid $opSid -WindowStart $win0 -WindowEnd $win1 -Seen $seen) }
    $nr = { param($cond, $user, $exp, [int]$elev = 0) New-C4TestRecord -Cond $cond -UserSid $user -Expected $exp -ExeSha $rx -Elevation $elev -NcoSid $ncoSid }
    $good = @(@(@('F', $ncoSid, $true, 3), @('E', $ncoSid, $true, 2), @('E', $ncoSid, $true, 1), @('S', $opSid, $false, 3), @('A', $opSid, $false, 2)) | ForEach-Object { @(& $va (& $nr $_[0] $_[1] $_[2] $_[3])).Count })
    $openRec = New-C4TestRecord -Cond 'F' -UserSid $ncoSid -Expected $true -ExeSha $rx -NcoSid $ncoSid -OpenFailed
    $leftRec = New-C4TestRecord -Cond 'F' -UserSid $ncoSid -Expected $true -ExeSha $rx -NcoSid $ncoSid -DelRc '0x80070005' -DelPresent $true
    $unreadRec = New-C4TestRecord -Cond 'E' -UserSid $ncoSid -Expected $true -ExeSha $rx -NcoSid $ncoSid -DelPresent 'unreadable'
    Chk 'records: a good F, E (type 2 and type 1 with the group enabled), S and A record, an engine-open failure, a filter left behind (filter_left_behind, exit 8) and an unreadable delete read-back (residue unknown) are valid' ((($good | Measure-Object -Sum).Sum -eq 0) -and ($good.Count -eq 5) -and (@(& $va $openRec).Count -eq 0) -and (@(& $va $leftRec).Count -eq 0) -and (@(& $va $unreadRec).Count -eq 0))
    $muts = [ordered]@{
        'schema'               = { param($r) $r.schema = 'nep5-case4-record-v0' }
        'subcommand'           = { param($r) $r.subcommand = 'identity' }
        'toggle_build'         = { param($r) $r.toggle_build = $true }
        'cond'                 = { param($r) $r.cond = 'X' }
        'probe_exe_sha256'     = { param($r) $r.probe_exe_sha256 = ('dd' * 32) }
        'probe_cs_sha256'      = { param($r) $r.probe_cs_sha256 = ('ef' * 32) }
        'proof.sha256'         = { param($r) $r.proof.sha256 = ('00' * 32) }
        'pid'                  = { param($r) $r.pid = 0 }
        'user_sid'             = { param($r) $r.user_sid = $otherSid }
        'is_expected_account'  = { param($r) $r.is_expected_account = 'yes' }
        'expected_account.sid' = { param($r) $r.expected_account.sid = $otherSid }
        'clock_start.utc'      = { param($r) $r.clock_start = [ordered]@{ local = 'x'; utc = '2001-01-01T00:00:00Z' } }
        'clock_end.utc'        = { param($r) $r.clock_end = [ordered]@{ local = 'x'; utc = '2001-01-01T00:00:00Z' } }
        'stamp_utc'            = { param($r) $r.stamp_utc = '20010101-000000' }
        'record_file_name'     = { param($r) $r.record_file_name = 'case4-F-20010101-000000-1.json' }
        'engine.open.opened'   = { param($r) $r.engine.open.opened = 'yes' }
        'add.attempted'        = { param($r) $r.add.attempted = $false }
        'add.rc'               = { param($r) $r.add.rc = '5' }
        'add.class'            = { param($r) $r.add.class = 'denied' }
        'add.present_after'    = { param($r) $r.add.present_after = 'maybe' }
        'delete.rc'            = { param($r) $r.delete.rc = '0xZZ' }
        'delete.class'         = { param($r) $r.delete.class = 'gone' }
        'delete.present_after' = { param($r) $r.delete.present_after = 'maybe' }
        'overall'              = { param($r) $r.overall = 'filter_left_behind' }
        'residue'              = { param($r) $r.residue = 'present' }
        'exit'                 = { param($r) $r.exit = 3 }
    }
    $recMissed = @(foreach ($k in $muts.Keys) {
        $r = & $nr 'F' $ncoSid $true; $name = [string]$r.record_file_name
        & $muts[$k] $r
        $why = @(& $va $r $name)
        if (@($why | Where-Object { $_.StartsWith("${k}:") }).Count -lt 1) { "$k -> $($why -join ' / ')" }
    })
    Chk "records: each of $($muts.Count) fields planted wrong, one at a time ($(@($muts.Keys) -join ', ')), is invalid with that field named $(if ($recMissed.Count) { '(MISSED: ' + ($recMissed -join '; ') + ')' })" ($recMissed.Count -eq 0) 'record-validation'
    $rCo = & $nr 'F' $ncoSid $true; $t0c = [datetimeoffset]::Parse($rCo.clock_start.utc); $rCo.clock_end = [ordered]@{ local = 'x'; utc = $t0c.AddSeconds(-1).UtcDateTime.ToString("yyyy-MM-dd'T'HH:mm:ss.fff'Z'") }
    $coR = @(& $va $rCo)
    Chk "records: a clock_end.utc one second BEFORE clock_start.utc, both inside the window, is invalid by exactly that rule ($($coR -join ' / '))" (($coR.Count -eq 1) -and ($coR[0] -ceq 'clock_end.utc: before clock_start.utc')) 'record-validation'
    $tokCases = [ordered]@{
        'F with a full token (elevation type 2)'                      = { New-C4TestRecord -Cond 'F' -UserSid $ncoSid -Expected $true -ExeSha $rx -NcoSid $ncoSid -Elevation 2 }
        'F without S-1-5-32-556 (the account not in the group)'       = { New-C4TestRecord -Cond 'F' -UserSid $ncoSid -Expected $true -ExeSha $rx -NcoSid $ncoSid -NcoPresent $false }
        'E with a filtered token (the elevation wrapper skipped)'     = { New-C4TestRecord -Cond 'E' -UserSid $ncoSid -Expected $true -ExeSha $rx -NcoSid $ncoSid -Elevation 3 }
        'E without S-1-5-32-556'                                      = { New-C4TestRecord -Cond 'E' -UserSid $ncoSid -Expected $true -ExeSha $rx -NcoSid $ncoSid -NcoPresent $false }
        'E with the group read unreadable'                            = { New-C4TestRecord -Cond 'E' -UserSid $ncoSid -Expected $true -ExeSha $rx -NcoSid $ncoSid -NcoPresent 'unreadable' }
        'E with an unsplit token (type 1) and the group deny-only'    = { New-C4TestRecord -Cond 'E' -UserSid $ncoSid -Expected $true -ExeSha $rx -NcoSid $ncoSid -Elevation 1 -NcoDenyOnly }
        'E with a full token (type 2) and the group deny-only'        = { New-C4TestRecord -Cond 'E' -UserSid $ncoSid -Expected $true -ExeSha $rx -NcoSid $ncoSid -Elevation 2 -NcoDenyOnly }
        'E with the group enabled AND deny-only (a contradictory read)' = { $r = New-C4TestRecord -Cond 'E' -UserSid $ncoSid -Expected $true -ExeSha $rx -NcoSid $ncoSid -Elevation 1 -NcoDenyOnly; $r.nco_group.enabled = $true; $r }
        'E with the group enabled and Administrators enabled'         = { New-C4TestRecord -Cond 'E' -UserSid $ncoSid -Expected $true -ExeSha $rx -NcoSid $ncoSid -Elevation 1 -Admins 'enabled' }
        'E (type 2) with Administrators enabled'                      = { New-C4TestRecord -Cond 'E' -UserSid $ncoSid -Expected $true -ExeSha $rx -NcoSid $ncoSid -Elevation 2 -Admins 'enabled' }
        'F with Administrators enabled'                               = { New-C4TestRecord -Cond 'F' -UserSid $ncoSid -Expected $true -ExeSha $rx -NcoSid $ncoSid -Elevation 1 -Admins 'enabled' }
        'S with a full token (typed in the elevated console)'         = { New-C4TestRecord -Cond 'S' -UserSid $opSid -Expected $false -ExeSha $rx -NcoSid $ncoSid -Elevation 2 -Admins 'enabled' }
        'S with Administrators enabled, not deny-only'                = { New-C4TestRecord -Cond 'S' -UserSid $opSid -Expected $false -ExeSha $rx -NcoSid $ncoSid -Admins 'enabled' }
        'A with a filtered token (typed in the non-elevated console)'  = { New-C4TestRecord -Cond 'A' -UserSid $opSid -Expected $false -ExeSha $rx -NcoSid $ncoSid -Elevation 3 -Admins 'deny-only' }
        'A with Administrators deny-only'                             = { New-C4TestRecord -Cond 'A' -UserSid $opSid -Expected $false -ExeSha $rx -NcoSid $ncoSid -Admins 'deny-only' }
        'A without Administrators'                                    = { New-C4TestRecord -Cond 'A' -UserSid $opSid -Expected $false -ExeSha $rx -NcoSid $ncoSid -Admins 'absent' }
    }
    $tokMissed = @(foreach ($k in $tokCases.Keys) { $why = @(& $va (& $tokCases[$k])); if (@($why | Where-Object { $_ -like 'token:*' }).Count -lt 1 -or (Get-C4InvalidKind -Reasons $why) -ne 'by-token-state') { "$k -> $($why -join ' / ')" } })
    Chk "records: the right principal under the wrong token is invalid by token state, never counted, for each condition and way ($($tokCases.Count) rows: $(@($tokCases.Keys) -join '; ')) $(if ($tokMissed.Count) { '(MISSED: ' + ($tokMissed -join '; ') + ')' })" ($tokMissed.Count -eq 0) 'record-validation'
    $f1 = New-C4TestRecord -Cond 'F' -UserSid $ncoSid -Expected $true -ExeSha $rx -NcoSid $ncoSid -Elevation 1; $f3 = New-C4TestRecord -Cond 'F' -UserSid $ncoSid -Expected $true -ExeSha $rx -NcoSid $ncoSid -Elevation 3
    $f1R = @(& $va $f1); $f3R = @(& $va $f3); $f1Row = Get-C4RecordRow -Record $f1 -FileName 'x'; $f3Row = Get-C4RecordRow -Record $f3 -FileName 'x'
    Chk "records: F is valid under an unsplit token (elevation type 1) as under a filtered one (type 3), and its row records which ($($f1Row.elevation_type); $($f3Row.elevation_type)); only type 2 invalidates an F record $(if ($f1R.Count + $f3R.Count) { '(' + ((@($f1R) + @($f3R)) -join ' / ') + ')' })" (($f1R.Count -eq 0) -and ($f3R.Count -eq 0) -and ($f1Row.elevation_type -match '^1\b') -and ($f3Row.elevation_type -match '^3\b')) 'record-validation'
    $e1 = New-C4TestRecord -Cond 'E' -UserSid $ncoSid -Expected $true -ExeSha $rx -NcoSid $ncoSid -Elevation 1; $e2 = New-C4TestRecord -Cond 'E' -UserSid $ncoSid -Expected $true -ExeSha $rx -NcoSid $ncoSid -Elevation 2
    $e1R = @(& $va $e1); $e2R = @(& $va $e2); $e1Row = Get-C4RecordRow -Record $e1 -FileName 'x'; $e2Row = Get-C4RecordRow -Record $e2 -FileName 'x'
    $eShown = @((Test-C4ETokenShown -Record $e1), (Test-C4ETokenShown -Record $e2), (Test-C4ETokenShown -Record (New-C4TestRecord -Cond 'E' -UserSid $ncoSid -Expected $true -ExeSha $rx -NcoSid $ncoSid -Elevation 1 -NcoDenyOnly)), (Test-C4ETokenShown -Record (New-C4TestRecord -Cond 'E' -UserSid $ncoSid -Expected $true -ExeSha $rx -NcoSid $ncoSid -Elevation 3)), (Test-C4ETokenShown -Record (New-C4TestRecord -Cond 'E' -UserSid $ncoSid -Expected $true -ExeSha $rx -NcoSid $ncoSid -Elevation 1 -NcoPresent 'unreadable')))
    Chk "records: E is valid under an unsplit token (type 1) with the group enabled (the batch-logon route) as under a full one (type 2), and its row records which ($($e1Row.elevation_type) $($e1Row.nco_group); $($e2Row.elevation_type) $($e2Row.nco_group)); the token E is about is shown by type 1 enabled and type 2, not by type 1 deny-only, type 3, or an unreadable group ($($eShown -join ','))" (($e1R.Count -eq 0) -and ($e2R.Count -eq 0) -and ($e1Row.elevation_type -match '^1\b') -and ($e1Row.nco_group -ceq '0x00000007 enabled') -and (($eShown -join ',') -ceq 'True,True,False,False,False')) 'record-validation'
    $tokOff = @(Test-C4Record -Record (ConvertFrom-C4Json -Text (ConvertTo-Json -InputObject (& $tokCases['A with a filtered token (typed in the non-elevated console)']) -Depth 10)) -FileName ([string](& $tokCases['A with Administrators deny-only']).record_file_name) -ExeSha $rx -CsSha $rcs -ProofSha $rps -NcoSid $ncoSid -OperatorSid $opSid -WindowStart $win0 -WindowEnd $win1 | Where-Object { $_ -like 'token:*' })
    $kindOrder = @((Get-C4InvalidKind -Reasons @('token: x', 'user_sid: y')), (Get-C4InvalidKind -Reasons @('token: x')), (Get-C4InvalidKind -Reasons @('principal: x')), (Get-C4InvalidKind -Reasons @('schema: x')))
    Chk "records: an invalid record's class is by-principal before by-token-state before invalid ($($kindOrder -join ', ')), and the token rule fires on the very record the review typed into the wrong console" ((($kindOrder -join ',') -ceq 'by-principal,by-token-state,by-principal,invalid') -and ($tokOff.Count -ge 1)) 'record-validation'
    $oMuts = [ordered]@{ 'engine.open.rc' = { param($r) $r.engine.open.rc = '0x00000000' }; 'add.attempted' = { param($r) $r.add.attempted = $true }; 'overall' = { param($r) $r.overall = 'ok' }; 'exit' = { param($r) $r.exit = 0 }; 'residue' = { param($r) $r.residue = 'absent' }; 'add.rc' = { param($r) $r.add['rc'] = '0x00000000' } }
    $oMissed = @(foreach ($k in $oMuts.Keys) { $r = New-C4TestRecord -Cond 'F' -UserSid $ncoSid -Expected $true -ExeSha $rx -NcoSid $ncoSid -OpenFailed; & $oMuts[$k] $r; if (@(@(& $va $r) | Where-Object { $_.StartsWith("${k}:") }).Count -lt 1) { $k } })
    Chk "records: an engine-open failure record that claims an open rc of 0, an attempted add, overall ok, exit 0, residue absent or an add status is invalid with that field named $(if ($oMissed.Count) { '(MISSED: ' + ($oMissed -join ', ') + ')' })" ($oMissed.Count -eq 0) 'record-validation'
    $nt = { param([hashtable]$sw) New-C4TestRecord -Cond 'F' -UserSid $ncoSid -Expected $true -ExeSha $rx -NcoSid $ncoSid @sw }
    $thrown = [ordered]@{
        'an open that threw (incomplete, exit 11, no STOP line)'                  = @{ OpenThrew = $true }
        'an add that threw (incomplete, exit 11, the STOP line)'                  = @{ AddThrew = $true }
        'a delete that threw (incomplete, exit 11, the STOP line)'                = @{ DeleteThrew = $true }
        'a close that threw (incomplete, exit 11, the STOP line)'                 = @{ CloseThrew = $true }
        'a delete that threw with the filter still present (filter_left_behind wins, exit 8)' = @{ DeleteThrew = $true; DelPresent = $true }
    }
    $thrownBad = @(foreach ($k in $thrown.Keys) { $why = @(& $va (& $nt $thrown[$k])); if ($why.Count) { "$k -> $($why -join ' / ')" } })
    Chk "records: the probe's records of a call that threw are valid ($(@($thrown.Keys) -join '; ')) $(if ($thrownBad.Count) { '(REFUSED: ' + ($thrownBad -join '; ') + ')' })" ($thrownBad.Count -eq 0) 'record-validation'
    $tMuts = [ordered]@{
        'open threw, exit 7'                     = @(@{ OpenThrew = $true }, { param($r) $r.exit = 7 }, 'exit:')
        'open threw, overall open_failed'        = @(@{ OpenThrew = $true }, { param($r) $r.overall = 'open_failed' }, 'overall:')
        'open threw, an open rc'                 = @(@{ OpenThrew = $true }, { param($r) $r.engine.open.rc = '0x80070005' }, 'engine.open.rc:')
        'open threw, sequence_complete true'     = @(@{ OpenThrew = $true }, { param($r) $r.sequence_complete = $true }, 'sequence_complete:')
        'open threw, the STOP line'              = @(@{ OpenThrew = $true }, { param($r) $r.operator_action = $script:C4ProbeStopLine }, 'operator_action:')
        'open failed, sequence_complete false'   = @(@{ OpenFailed = $true }, { param($r) $r.sequence_complete = $false }, 'sequence_complete:')
        'add threw, class denied'                = @(@{ AddThrew = $true }, { param($r) $r.add.class = 'denied' }, 'add.class:')
        'add threw, no error text'               = @(@{ AddThrew = $true }, { param($r) $r.add.error = $null }, 'add.error:')
        'add threw, no STOP line'                = @(@{ AddThrew = $true }, { param($r) $r.operator_action = $null }, 'operator_action:')
        'add threw, sequence_complete true'      = @(@{ AddThrew = $true }, { param($r) $r.sequence_complete = $true }, 'sequence_complete:')
        'add threw, overall ok'                  = @(@{ AddThrew = $true }, { param($r) $r.overall = 'ok' }, 'overall:')
        'add threw, exit 0'                      = @(@{ AddThrew = $true }, { param($r) $r.exit = 0 }, 'exit:')
        'close threw, no close_error'            = @(@{ CloseThrew = $true }, { param($r) $r.engine.close_error = $null }, 'engine.close_error:')
        'ok, the STOP line'                      = @(@{}, { param($r) $r.operator_action = $script:C4ProbeStopLine }, 'operator_action:')
        'ok, sequence_complete false'            = @(@{}, { param($r) $r.sequence_complete = $false }, 'sequence_complete:')
        'ok, a read-back that threw (get_rc null) unreported' = @(@{}, { param($r) $r.delete.get_rc = $null }, 'sequence_complete:')
        'left behind, no STOP line'              = @(@{ DelPresent = $true; DelRc = '0x80070005' }, { param($r) $r.operator_action = $null }, 'operator_action:')
    }
    $tMissed = @(foreach ($k in $tMuts.Keys) { $sw = $tMuts[$k][0]; $r = & $nt $sw; & $tMuts[$k][1] $r; $why = @(& $va $r); if (@($why | Where-Object { $_.StartsWith($tMuts[$k][2]) }).Count -lt 1) { "$k -> $($why -join ' / ')" } })
    $wpSc = New-C4TestRecord -Cond 'F' -UserSid $opSid -Expected $false -ExeSha $rx -NcoSid $ncoSid -WrongPrincipal; $wpSc.sequence_complete = $false; $wpOa = New-C4TestRecord -Cond 'F' -UserSid $opSid -Expected $false -ExeSha $rx -NcoSid $ncoSid -WrongPrincipal; $wpOa.operator_action = $script:C4ProbeStopLine
    Chk "records: each of $($tMuts.Count) wrong claims about a call that threw, the sequence or the STOP line is invalid with that field named, and a wrong_principal record with a sequence_complete or a STOP line is too $(if ($tMissed.Count) { '(MISSED: ' + ($tMissed -join '; ') + ')' })" (($tMissed.Count -eq 0) -and (@(& $va $wpSc | Where-Object { $_ -like 'sequence_complete:*' }).Count -eq 1) -and (@(& $va $wpOa | Where-Object { $_ -like 'operator_action:*' }).Count -eq 1)) 'record-validation'
    $possOk = [ordered]@{
        'add 0, delete denied, read-back unreadable'   = @{ DelRc = '0x80070005'; DelPresent = 'unreadable' }
        'add threw, delete threw, read-back not read'  = @{ AddThrew = $true; DeleteThrew = $true; DelPresent = 'not_read' }
    }
    $possBad = @(foreach ($k in $possOk.Keys) { $pr2 = & $nt $possOk[$k]; $why = @(& $va $pr2); if ($why.Count -or $pr2.overall -cne 'filter_possibly_left_behind' -or $pr2.exit -ne 8 -or $pr2.residue -cne 'unknown' -or $pr2.operator_action -cne $script:C4ProbeStopLine) { "$k -> $($pr2.overall) $($pr2.exit) / $($why -join ' / ')" } })
    $notPoss = @((& $nt @{ DelRc = '0x80070005'; DelPresent = $false }), (& $nt @{ AddRc = '0x80070005'; DelRc = '0x80320003'; DelPresent = 'unreadable' }), (& $nt @{ DelPresent = 'unreadable' }))
    $notPossBad = @($notPoss | Where-Object { $_.overall -ceq 'filter_possibly_left_behind' -or @(& $va $_).Count })
    $pMut1 = & $nt @{ DelRc = '0x80070005'; DelPresent = 'unreadable' }; $pMut1.overall = 'ok'; $pMut1.exit = 0; $pMut1.operator_action = $null
    $pMut2 = & $nt @{ DelRc = '0x80070005'; DelPresent = 'unreadable' }; $pMut2.operator_action = $null
    $pMut3 = & $nt @{ DelRc = '0x80070005'; DelPresent = $false }; $pMut3.overall = 'filter_possibly_left_behind'; $pMut3.exit = 8; $pMut3.residue = 'unknown'; $pMut3.operator_action = $script:C4ProbeStopLine
    $wpNull = New-C4TestRecord -Cond 'F' -UserSid $opSid -Expected $false -ExeSha $rx -NcoSid $ncoSid -WrongPrincipal; $wpNull.operator_action = $null
    Chk "records: filter_possibly_left_behind (exit 8, residue unknown, the STOP line) is valid exactly when the add returned 0 or threw, the delete did not return 0 and the read-back is not false; claiming ok or dropping the STOP line on one, or claiming it with a read-back of false, is invalid; a wrong_principal record must carry the wrong-principal STOP line $(if ($possBad.Count + $notPossBad.Count) { '(' + ((@($possBad) + @($notPossBad | ForEach-Object { 'wrongly possibly: ' + $_.overall })) -join '; ') + ')' })" (($possBad.Count -eq 0) -and ($notPossBad.Count -eq 0) -and (@(& $va $pMut1 | Where-Object { $_ -like 'overall:*' }).Count -eq 1) -and (@(& $va $pMut1 | Where-Object { $_ -like 'exit:*' }).Count -eq 1) -and (@(& $va $pMut2 | Where-Object { $_ -like 'operator_action:*' }).Count -eq 1) -and (@(& $va $pMut3 | Where-Object { $_ -like 'overall:*' }).Count -eq 1) -and (@(& $va $wpNull | Where-Object { $_ -like 'operator_action:*' }).Count -eq 1)) 'record-validation'
    $waThrew = New-C4TestRecord -Cond 'F' -UserSid $otherSid -Expected $false -ExeSha $rx -AddThrew; $waThrew.add.present_after = $true
    Chk 'wrong principal: an F record whose add THREW but whose filter read present afterwards is the STOP finding too' (Test-C4WrongAccountAdd -Record $waThrew -NcoSid $ncoSid) 'record-wrong-account-stop'
    $rowsT = @((Get-C4RecordRow -Record (& $nr 'F' $ncoSid $true) -FileName 'a'), (Get-C4RecordRow -Record (& $nt @{ AddThrew = $true }) -FileName 'b'), (Get-C4RecordRow -Record (& $nt @{ CloseThrew = $true }) -FileName 'c'), (Get-C4RecordRow -Record (& $nt @{ OpenThrew = $true }) -FileName 'd'))
    $tblT = @(Format-C4Table -Rows $rowsT)
    Chk "table: an add that threw and an open that threw are listed and not counted; a close that threw still has its add verdict and is counted ($($tblT[0]))" ($tblT[0] -ceq 'F: n = 2 (no write verdict: an engine-open failure or an add that threw; listed, not counted: 2)') 'record-validation'
    $wpF = New-C4TestRecord -Cond 'F' -UserSid $opSid -Expected $false -ExeSha $rx -NcoSid $ncoSid -WrongPrincipal; $wpS = New-C4TestRecord -Cond 'S' -UserSid $ncoSid -Expected $true -ExeSha $rx -NcoSid $ncoSid -WrongPrincipal
    $wpFr = @(& $va $wpF); $wpSr = @(& $va $wpS)
    $shapeNames = { param($rs) @($rs | Where-Object { $_ -like 'exit:*' -or $_ -like 'add.*' -or $_ -like 'delete.*' -or $_ -like 'engine.*' -or $_ -like 'residue:*' -or $_ -like 'overall:*' }) }
    $wpBad = New-C4TestRecord -Cond 'F' -UserSid $opSid -Expected $false -ExeSha $rx -NcoSid $ncoSid -WrongPrincipal; $wpBad.exit = 0; $wpBad.add.attempted = $true; $wpBadR = @(& $va $wpBad)
    $wpLie = New-C4TestRecord -Cond 'F' -UserSid $ncoSid -Expected $true -ExeSha $rx -NcoSid $ncoSid -WrongPrincipal; $notRefused = & $nr 'F' $opSid $false
    Chk 'records: a wrong_principal record (F by the operator, S by the account) is invalid by principal with no shape complaint and is not the STOP finding; one claiming exit 0 and an attempted add, one claiming wrong_principal for the right account, and an F record by the operator that reached the engine each carry the further reason' ((@($wpFr | Where-Object { $_ -like 'principal:*' }).Count -eq 1) -and ((& $shapeNames $wpFr).Count -eq 0) -and (@($wpSr | Where-Object { $_ -like 'principal:*' }).Count -eq 1) -and ((& $shapeNames $wpSr).Count -eq 0) -and -not (Test-C4WrongAccountAdd -Record $wpF -NcoSid $ncoSid) -and (@($wpBadR | Where-Object { $_ -like 'exit:*' }).Count -eq 1) -and (@($wpBadR | Where-Object { $_ -like 'add.attempted:*' }).Count -eq 1) -and (@(& $va $wpLie | Where-Object { $_ -like 'overall:*' }).Count -eq 1) -and (@(& $va $notRefused | Where-Object { $_ -like 'overall:*' }).Count -eq 1)) 'record-validation'
    $rF = & $nr 'F' $ncoSid $true; $nF = [string]$rF.record_file_name
    $seen = @{}; $first = @(& $va $rF $nF $seen); $dup = @(& $va $rF $nF $seen)
    $wrongName = @(& $va $rF ($nF -replace '-4242\.json$', '-4243.json')); $wrongCond = @(& $va $rF ($nF -replace '^case4-F-', 'case4-E-')); $notName = @(& $va $rF 'record.json')
    $sOnAcct = New-C4TestRecord -Cond 'S' -UserSid $ncoSid -Expected $true -ExeSha $rx -NcoSid $ncoSid; $sBad = @(& $va $sOnAcct)
    Chk 'records: a duplicate pid+stamp, a file name with another pid or cond, a name that is not a record name, and an S record made as the account are each invalid' (($first.Count -eq 0) -and (@($dup | Where-Object { $_ -like 'pid+stamp:*' }).Count -eq 1) -and (@($wrongName | Where-Object { $_ -like 'file name:*' }).Count -ge 1) -and (@($wrongCond | Where-Object { $_ -like 'file name:*' }).Count -ge 1) -and (@($notName | Where-Object { $_ -like 'file name:*' }).Count -eq 1) -and ($sBad.Count -ge 1)) 'record-validation'
    $wa = New-C4TestRecord -Cond 'F' -UserSid $otherSid -Expected $false -ExeSha $rx; $waDen = New-C4TestRecord -Cond 'F' -UserSid $otherSid -Expected $false -ExeSha $rx -AddRc '0x80070005' -DelRc '0x80320003'; $waS = New-C4TestRecord -Cond 'S' -UserSid $opSid -Expected $false -ExeSha $rx; $waE = New-C4TestRecord -Cond 'E' -UserSid $ncoSid -Expected $true -ExeSha $rx
    Chk 'wrong principal: an F record whose add SUCCEEDED under another SID is the STOP finding; the same with the add denied, an S record of the operator and an E record of the account are not' ((Test-C4WrongAccountAdd -Record $wa -NcoSid $ncoSid) -and -not (Test-C4WrongAccountAdd -Record $waDen -NcoSid $ncoSid) -and -not (Test-C4WrongAccountAdd -Record $waS -NcoSid $ncoSid) -and -not (Test-C4WrongAccountAdd -Record $waE -NcoSid $ncoSid) -and (Test-C4WrongAccountAdd -Record $wa -NcoSid '')) 'record-wrong-account-stop'
    $rows = @((Get-C4RecordRow -Record $rF -FileName $nF), (Get-C4RecordRow -Record $openRec -FileName 'x'))
    $tbl = @(Format-C4Table -Rows $rows)
    Chk "table: n counts only the valid records that reached the engine; an engine-open failure is listed below it, says it is not a write verdict, and is not counted ($($tbl[0]))" (($tbl[0] -ceq 'F: n = 1 (no write verdict: an engine-open failure or an add that threw; listed, not counted: 1)') -and (@($tbl | Where-Object { $_ -ceq 'E: n = 0' }).Count -eq 1) -and ($tbl[1] -match 'elevation type 3 limited \| integrity medium \| linked token True \| S-1-5-32-556 0x00000007 enabled \| S-1-5-32-544 absent \| add 0x00000000 succeeded') -and ($tbl[2] -match 'not a write verdict'))
    $erC = Get-C4ElevationRefused -Note 'Windows offered only the operator''s account' -EElevated @(); $erX = Get-C4ElevationRefused -Note 'refused' -EElevated @('case4-E-1.json'); $erN = Get-C4ElevationRefused -Note '' -EElevated @()
    $tblE = @(Format-C4Table -Rows @() -ElevationRefused $erC); $tblX = @(Format-C4Table -Rows @() -ElevationRefused $erX)
    Chk 'elevation_refused: the note is counted as the E result when no E record shows the account''s elevated token, NOT counted when one does, and absent without a note; the E line says which' ($erC.counted -and -not $erX.counted -and -not $erN.given -and -not $erN.counted -and (@($tblE | Where-Object { $_ -match '^E: n = 0; E result: elevation_refused' }).Count -eq 1) -and (@($tblX | Where-Object { $_ -match '^E: n = 0; the elevation_refused note is NOT counted' }).Count -eq 1)) 'record-validation'

    Write-Host '== parsers of the account reads, netsh and the probe''s outputs; exit codes ==' -ForegroundColor Cyan
    $nlg = "Alias name     Network Configuration Operators`r`nComment        x`r`n`r`nMembers`r`n`r`n-------------------------------------------------------------------------------`r`nnco-probe`r`nTESTPC\other`r`nThe command completed successfully.`r`n"
    $nlg0 = "Alias name     x`r`n`r`n-------------------------------------------------------------------------------`r`nThe command completed successfully.`r`n"
    $m1 = ConvertFrom-C4NetLocalGroup -Text $nlg -ExitCode 0; $m0 = ConvertFrom-C4NetLocalGroup -Text $nlg0 -ExitCode 0
    Chk 'net localgroup: members parsed (the completion line dropped); an empty group is an empty list; no rule or a non-zero exit is unreadable ($null); MACHINE\name matches' ((@($m1) -join ',') -ceq 'nco-probe,TESTPC\other' -and ($null -ne $m0) -and (@($m0).Count -eq 0) -and ($null -eq (ConvertFrom-C4NetLocalGroup -Text 'garbage' -ExitCode 0)) -and ($null -eq (ConvertFrom-C4NetLocalGroup -Text $nlg -ExitCode 2)) -and (Test-C4MemberListed -Members @('TESTPC\nco-probe')) -and -not (Test-C4MemberListed -Members @('nco-probe2')))
    Chk 'net user: exit 0 is present; exit 2 with NET HELPMSG 2221 is absent; any other answer is unreadable' (((Get-C4NetUserState 0 'x') -eq 'present') -and ((Get-C4NetUserState 2 "The user name could not be found.`r`nMore help is available by typing NET HELPMSG 2221.") -eq 'absent') -and ((Get-C4NetUserState 2 'access denied') -eq 'unreadable') -and ((Get-C4NetUserState 5 '2221') -eq 'unreadable'))
    $fr = Find-C4NetshSecurity -Type 'sublayer' -Guid $s2 -RunNetsh { param([string[]]$Argv) if (($Argv -join ' ') -match 'guid=\{') { [pscustomobject]@{ exit = 1; text = 'The parameter is incorrect.' } } else { [pscustomobject]@{ exit = 0; text = 'O:BAG:BAD:(A;;0xf00ff;;;BA)' } } }
    $fn = Find-C4NetshSecurity -Type 'sublayer' -Guid $s2 -RunNetsh { param([string[]]$Argv) [pscustomobject]@{ exit = 1; text = 'The parameter is incorrect.' } }
    $fb = Find-C4NetshSecurity -Type 'sublayer' -Guid $s2 -RunNetsh { param([string[]]$Argv) [pscustomobject]@{ exit = 0; text = 'O:BAG:BAD:(A;;0xf00ff;;;BA)' } }
    Chk 'netsh security: the braced form is tried first, refused, and recorded; the plain form is then accepted and named; when no form works every attempt is recorded and none is claimed' ($fr.ok -and ($fr.command -ceq "netsh wfp show security type=sublayer guid=$s2") -and ($fr.tries.Count -eq 2) -and (-not $fr.tries[0].accepted) -and (-not $fn.ok) -and ($fn.tries.Count -eq 2) -and ($fb.command -ceq "netsh wfp show security type=sublayer guid={$s2}") -and ($fb.tries.Count -eq 1))
    $sdc = Compare-C4SdText -Before "O:BA`r`nD:(A;;1;;;BA)" -After "O:BA`r`nD:(A;;1;;;BA)(A;;4;;;NO)"
    Chk 'security descriptor compare: identical text is the same; a changed DACL line is reported removed and added' ((Compare-C4SdText -Before "x`r`n y " -After ('x' + "`n" + 'y')).same -and -not $sdc.same -and ($sdc.added.Count -eq 1) -and ($sdc.removed.Count -eq 1))
    $vGood = ConvertFrom-C4ProbeVersion -Stdout ('{"probe_exe_sha256":"' + ('ab' * 32) + '","probe_cs_sha256":"' + ('cd' * 32) + '","toggle_build":false}') -ExitCode 0
    $vTog = ConvertFrom-C4ProbeVersion -Stdout ('{"probe_exe_sha256":"' + ('ab' * 32) + '","probe_cs_sha256":"' + ('cd' * 32) + '","toggle_build":true}') -ExitCode 0
    $vBad = ConvertFrom-C4ProbeVersion -Stdout '{"probe_exe_sha256":"zz","probe_cs_sha256":"x","toggle_build":"no"}' -ExitCode 0
    Chk 'probe --version (stand-in output): hashes and toggle_build read; a toggle build is reported as one; bad hashes, a non-zero exit and non-JSON are not usable' ($vGood.Ok -and ($vGood.ToggleBuild -eq $false) -and ($vGood.ExeSha -ceq ('AB' * 32)) -and $vTog.Ok -and ($vTog.ToggleBuild -eq $true) -and (-not $vBad.Ok) -and (-not (ConvertFrom-C4ProbeVersion -Stdout 'x' -ExitCode 0).Ok) -and (-not (ConvertFrom-C4ProbeVersion -Stdout ('{"probe_exe_sha256":"' + ('ab' * 32) + '","probe_cs_sha256":"' + ('cd' * 32) + '","toggle_build":false}') -ExitCode 1).Ok))
    $stA = ConvertFrom-C4ProbeSelfTest -Stdout "  [PASS] a`r`nchecks_run: 41  checks_failed: 0`r`n" -ExitCode 0; $stJ = ConvertFrom-C4ProbeSelfTest -Stdout '{"checks_run":41,"checks_failed":0,"failures":[]}' -ExitCode 0
    $stF = ConvertFrom-C4ProbeSelfTest -Stdout "checks_run: 41  checks_failed: 1" -ExitCode 1; $stX = ConvertFrom-C4ProbeSelfTest -Stdout "  [FAIL] b`r`nchecks_run: 41  checks_failed: 0" -ExitCode 0; $stN = ConvertFrom-C4ProbeSelfTest -Stdout 'done' -ExitCode 0
    $stB = ConvertFrom-C4ProbeSelfTest -Stdout ("[PASS] version.shipped :: exit 0`r`n[PASS] selftest :: exit 0`r`nchecks_run 140 / checks_failed 0`r`n" + '{"checks_run":140,"checks_failed":0,"runner_steps":5}') -ExitCode 0
    $stBf = ConvertFrom-C4ProbeSelfTest -Stdout ("[FAIL] selftest :: exit 1`r`nchecks_run 140 / checks_failed 1`r`n" + '{"checks_run":140,"checks_failed":1}') -ExitCode 1
    Chk 'probe self-test (stand-in output): the text and the JSON summary both pass at 0 failed, as does the run-probe-selftest.ps1 form (a slash line, then a JSON line); a failure, a [FAIL] line, or no summary line do not' ($stA.Passed -and ($stA.ChecksRun -eq 41) -and $stJ.Passed -and $stB.Passed -and ($stB.ChecksRun -eq 140) -and (-not $stBf.Passed) -and (-not $stF.Passed) -and (-not $stX.Passed) -and (-not $stN.Passed))
    $sheet = @(Get-C4RunSheetLines -BinDir 'C:\ProgramData\BlarAI\case4-pub\bin' -DropDir 'C:\ProgramData\BlarAI\case4-pub\drop')
    $pfx = 'C:\ProgramData\BlarAI\case4-pub\bin\ncoprobe.exe run --cond {0} --live C:\ProgramData\BlarAI\case4-pub\bin\nco-probe-live.json --out C:\ProgramData\BlarAI\case4-pub\drop'
    $wantSheet = @(('cmd /k ' + ($pfx -f 'F') + ' --wait'), (($pfx -f 'E') + ' --wait'), ($pfx -f 'S'), ($pfx -f 'A'))
    $sheetOk = ((($sheet | ForEach-Object { $_.cond }) -join '') -ceq 'FESA') -and ((@($sheet | ForEach-Object { $_.command }) -join '|') -ceq ($wantSheet -join '|'))
    $spaceRefused = $false; try { [void](Get-C4RunSheetLines -BinDir 'C:\Program Data\bin' -DropDir 'C:\x') } catch { $spaceRefused = $true }
    Chk 'run sheet: F is cmd /k <probe line> --wait, E the bare probe line with --wait (step 4 wraps it), S and A the bare line WITHOUT --wait, all with the real bin\ proof and drop\ paths and no quotes; a path with a space is refused' ($sheetOk -and $spaceRefused)
    $rsPath = Resolve-LibPath -Name 'RUN_SHEET.md'
    if (Test-Path -LiteralPath $rsPath) {
        $rsText = [IO.File]::ReadAllText($rsPath)
        $notInSheet = @($sheet | Where-Object { -not $rsText.Contains($_.command) } | ForEach-Object { $_.cond })
        Chk "run sheet: every line the driver prints appears character for character in RUN_SHEET.md ($rsPath) $(if ($notInSheet.Count) { '(NOT in the sheet: ' + ($notInSheet -join ', ') + ')' })" ($notInSheet.Count -eq 0)
    } else { Write-Host "  NOTE: RUN_SHEET.md is not reachable from here ($rsPath; the live folder does not hold it): the driver's lines were not compared with the sheet in this run." -ForegroundColor Yellow }
    $swC = [pscustomobject]@{ Stop = $false; Clean = $true; Unreadable = $false; NotClean = @() }; $swU = [pscustomobject]@{ Stop = $false; Clean = $false; Unreadable = $true; NotClean = @() }; $swS = [pscustomobject]@{ Stop = $true; Clean = $false; Unreadable = $true; NotClean = @() }; $swP = [pscustomobject]@{ Stop = $false; Clean = $false; Unreadable = $true; NotClean = @('S2 sublayer is still present') }
    Chk '-Check exit: all absent 20; the account present 21; a STOP 21 even when unreadable; S2 present 21 even with another read failed; an unreadable engine, profile or untrusted harness 22' (((Get-C4CheckExit -Sweep $swC -ProbeKeyPresent $false -PubPresent $false -AccountPresent $false -MemberPresent $false -ProfilePresent $false) -eq 20) -and ((Get-C4CheckExit -Sweep $swC -ProbeKeyPresent $false -PubPresent $false -AccountPresent $true -MemberPresent $false -ProfilePresent $false) -eq 21) -and ((Get-C4CheckExit -Sweep $swS -ProbeKeyPresent $null -PubPresent $false -AccountPresent $false -MemberPresent $false -ProfilePresent $false) -eq 21) -and ((Get-C4CheckExit -Sweep $swP -ProbeKeyPresent $null -PubPresent $false -AccountPresent $false -MemberPresent $false -ProfilePresent $false) -eq 21) -and ((Get-C4CheckExit -Sweep $swU -ProbeKeyPresent $false -PubPresent $false -AccountPresent $false -MemberPresent $false -ProfilePresent $false) -eq 22) -and ((Get-C4CheckExit -Sweep $swC -ProbeKeyPresent $false -PubPresent $false -AccountPresent $false -MemberPresent $false -ProfilePresent $null) -eq 22) -and ((Get-C4CheckExit -Sweep $swC -ProbeKeyPresent $false -PubPresent $false -AccountPresent $false -MemberPresent $false -ProfilePresent $false -HarnessTrusted $false) -eq 22))
    Chk 'exit codes: -PartD 20 only when all four reads say gone; -Collect STOP 9 over left-behind 21 over invalid 4; -Finish foreign 9, unverified 7, verified with the wrong-principal finding 9, clean 0' (((Get-C4PartDExit $true $true $true $true) -eq 20) -and ((Get-C4PartDExit $true $true $null $true) -eq 21) -and ((Get-C4PartDExit $false $true $true $true) -eq 21) -and ((Get-C4CollectExit -Stop $true -LeftBehind 1 -ResidueUnreadable $false -Invalid 1) -eq 9) -and ((Get-C4CollectExit -Stop $false -LeftBehind 1 -ResidueUnreadable $false -Invalid 1) -eq 21) -and ((Get-C4CollectExit -Stop $false -LeftBehind 0 -ResidueUnreadable $true -Invalid 0) -eq 21) -and ((Get-C4CollectExit -Stop $false -LeftBehind 0 -ResidueUnreadable $false -Invalid 1) -eq 4) -and ((Get-C4CollectExit -Stop $false -LeftBehind 0 -ResidueUnreadable $false -Invalid 0) -eq 0) -and ((Get-C4FinishExit $true $true $false) -eq 9) -and ((Get-C4FinishExit $false $false $false) -eq 7) -and ((Get-C4FinishExit $false $true $true) -eq 9) -and ((Get-C4FinishExit $false $true $false) -eq 0))

    Write-Host '== the driver proof and the harness proof (temporary folder of stand-in files; nothing in the live folder) ==' -ForegroundColor Cyan
    $pd = Join-C4Path ([IO.Path]::GetTempPath()) ('c4-proof-' + [guid]::NewGuid().ToString('N')); New-Item -ItemType Directory -Path $pd | Out-Null
    try {
        [IO.File]::WriteAllBytes((Join-C4Path $pd $script:C4SelfName), [IO.File]::ReadAllBytes($PSCommandPath))
        foreach ($n in @($script:C4TextFiles | Where-Object { $_ -ne $script:C4SelfName }) + $script:C4LibFiles) { [IO.File]::WriteAllText((Join-C4Path $pd $n), "// stand-in $n`n") }
        [IO.File]::WriteAllText((Join-C4Path $pd $script:C4ProbeExeName), 'stand-in probe exe (text, never run)'); [IO.File]::WriteAllText((Join-C4Path $pd 'halfset.exe'), 'stand-in harness exe (text, never run)'); [IO.File]::WriteAllText((Join-C4Path $pd 'halfset.rs'), "// stand-in`n")
        $hpObj = New-N5HarnessLiveProof -ExeSha (Get-N5RawSha256 -Path (Join-C4Path $pd 'halfset.exe')) -RsSha (Get-N5RawSha256 -Path (Join-C4Path $pd 'halfset.rs'))
        $hpPath = Join-C4Path $pd $script:C4HarnessProofName; [IO.File]::WriteAllText($hpPath, (ConvertTo-Json -InputObject $hpObj -Depth 4))
        $selfSha = Get-NormalizedSha256 -Path (Join-C4Path $pd $script:C4SelfName); $wrapSha = 'AB' * 32
        $pvF = [ordered]@{ Ok = $true; ExeSha = (Get-N5RawSha256 -Path (Join-C4Path $pd $script:C4ProbeExeName)); CsSha = (Get-NormalizedSha256 -Path (Join-C4Path $pd 'NcoProbe.cs')); ToggleBuild = $false; TraceEmpty = $true; Problem = '' }
        $pstF = [ordered]@{ Passed = $true; ChecksRun = 41; ChecksFailed = 0 }
        $wpArgs = @{ Folder = $pd; SelfSha = $selfSha; LoadedLibHashes = @{}; LoadedLibFolder = 'Z:\elsewhere'; WrappedSha = $wrapSha; ChecksRun = 90; ChecksPassed = 90; PassedTags = $script:C4RequiredTags; ProbeVersion = $pvF; ProbeSelfTest = $pstF }
        $tv = { Test-C4DriverProof -ProofPath (Join-C4Path $pd $script:C4DriverProofName) -Folder $pd -SelfSha $selfSha -LoadedLibHashes @{} -LoadedLibFolder 'Z:\elsewhere' -WrappedSha $wrapSha }
        $w1 = Invoke-C4WriteProof @wpArgs
        $tk = & $tv
        Chk "driver proof: written for a folder whose files all match, and it validates (a token with this process's nonce) $(if (-not $w1.Written) { '(' + ($w1.Problems -join '; ') + ')' })" ($w1.Written -and $tk.Ok -and (Test-C4ProofToken $tk) -and ($tk.ProbeExeSha -eq $pvF.ExeSha)) 'proof-hash-binding'
        $bindMiss = @()
        foreach ($n in @($script:C4TextFiles | Where-Object { $_ -ne $script:C4SelfName }) + $script:C4LibFiles + @($script:C4ProbeExeName, 'halfset.exe', 'halfset.rs')) {
            $fp = Join-C4Path $pd $n; $orig = [IO.File]::ReadAllBytes($fp)
            [IO.File]::AppendAllText($fp, ' ')
            $t = & $tv; if ($t.Ok -or @($t.Problems | Where-Object { $_.StartsWith("${n}:") -or ($n -eq 'halfset.exe' -and $_ -match 'harness') -or ($n -eq 'halfset.rs' -and $_ -match 'harness') }).Count -lt 1) { $bindMiss += $n }
            [IO.File]::WriteAllBytes($fp, $orig)
        }
        $tWrap = Test-C4DriverProof -ProofPath (Join-C4Path $pd $script:C4DriverProofName) -Folder $pd -SelfSha $selfSha -LoadedLibHashes @{} -LoadedLibFolder 'Z:\elsewhere' -WrappedSha ('CD' * 32)
        $tSelf = Test-C4DriverProof -ProofPath (Join-C4Path $pd $script:C4DriverProofName) -Folder $pd -SelfSha ('EF' * 32) -LoadedLibHashes @{} -LoadedLibFolder 'Z:\elsewhere' -WrappedSha $wrapSha
        $tLoaded = Test-C4DriverProof -ProofPath (Join-C4Path $pd $script:C4DriverProofName) -Folder $pd -SelfSha $selfSha -LoadedLibHashes @{ 'spike-nep5-lib.ps1' = ('00' * 32) } -LoadedLibFolder $pd -WrappedSha $wrapSha
        Chk "driver proof: each bound file changed in turn (the text files, the four libraries, the probe exe, the harness exe and halfset.rs), the wrapped script's evaluated bytes, this driver's own bytes and a library's RUN bytes are each refused by name $(if ($bindMiss.Count) { '(NOT refused: ' + ($bindMiss -join ', ') + ')' })" (($bindMiss.Count -eq 0) -and (-not $tWrap.Ok) -and (-not $tSelf.Ok) -and (@($tSelf.Problems | Where-Object { $_ -like "$($script:C4SelfName):*" }).Count -eq 1) -and (-not $tLoaded.Ok)) 'proof-hash-binding'
        $handMade = [pscustomobject]@{ Kind = 'Nep5Case4Proof'; Ok = $true; Nonce = 'forged' }; $noNonce = [pscustomobject]@{ Kind = 'Nep5Case4Proof'; Ok = $true }
        Chk 'driver proof: a hand-made token, a token without a nonce and a token of another kind are refused; the validated token is accepted' ((-not (Test-C4ProofToken $handMade)) -and (-not (Test-C4ProofToken $noNonce)) -and (-not (Test-C4ProofToken ([pscustomobject]@{ Kind = 'Nep5Proof'; Ok = $true; Nonce = $script:C4ProofNonce }))) -and (Test-C4ProofToken $tk)) 'proof-hash-binding'
        $pj = Get-Content -LiteralPath (Join-C4Path $pd $script:C4DriverProofName) -Raw
        $variant = { param($edit) $o = ConvertFrom-Json $pj -AsHashtable; & $edit $o; [IO.File]::WriteAllText((Join-C4Path $pd $script:C4DriverProofName), (ConvertTo-Json -InputObject $o -Depth 10)); $r = & $tv; [IO.File]::WriteAllText((Join-C4Path $pd $script:C4DriverProofName), $pj); $r }
        $v59 = & $variant { param($o) $o.checks_run = 59; $o.checks_passed = 59 }; $vTag = & $variant { param($o) $o.tags_passed = @($o.tags_passed | Where-Object { $_ -ne 'seams' }) }
        $vOld = & $variant { param($o) $o.written = [datetimeoffset]::Now.AddHours(-25).ToString('o') }; $vFut = & $variant { param($o) $o.written = [datetimeoffset]::Now.AddHours(1).ToString('o') }
        $vCeil = & $variant { param($o) $o.checks_run = 100000; $o.checks_passed = 100000 }; $vTog2 = & $variant { param($o) $o.probe_version.toggle_build = $true }
        Chk 'driver proof: 59 checks, a missing tag, 25 h old, dated in the future, more checks than the driver has call sites, or a toggle-build probe are each refused' ((-not $v59.Ok) -and (-not $vTag.Ok) -and (-not $vOld.Ok) -and (-not $vFut.Ok) -and (-not $vCeil.Ok) -and (-not $vTog2.Ok))
        $hpFresh = @(Test-N5HarnessLiveProof -Path $hpPath -ExeSha $hpObj.halfset_exe_sha256 -RsSha $hpObj.halfset_rs_sha256)
        $stale = New-N5HarnessLiveProof -ExeSha $hpObj.halfset_exe_sha256 -RsSha $hpObj.halfset_rs_sha256 -Now ([datetime]::Now.AddHours(-25))
        [IO.File]::WriteAllText($hpPath, (ConvertTo-Json -InputObject $stale -Depth 4)); $hpStale = @(Test-N5HarnessLiveProof -Path $hpPath -ExeSha $hpObj.halfset_exe_sha256 -RsSha $hpObj.halfset_rs_sha256)
        $hpWrong = @(Test-N5HarnessLiveProof -Path $hpPath -ExeSha ('00' * 32) -RsSha $hpObj.halfset_rs_sha256)
        Chk "harness proof: a fresh one is valid; one 25 h old is refused; one naming another exe is refused" (($hpFresh.Count -eq 0) -and ($hpStale.Count -ge 1) -and (@($hpWrong | Where-Object { $_ -match 'exe hash' }).Count -ge 1)) 'harness-live-proof-fresh'
        Remove-Item -LiteralPath (Join-C4Path $pd $script:C4DriverProofName) -Force
        $w2 = Invoke-C4WriteProof @wpArgs
        Chk 'write proof: with the matrix''s harness proof 25 h old NO driver proof is written (the file stays absent) and the reason names the harness proof' ((-not $w2.Written) -and -not (Test-Path -LiteralPath (Join-C4Path $pd $script:C4DriverProofName)) -and (@($w2.Problems | Where-Object { $_ -match 'harness proof' }).Count -ge 1)) 'harness-live-proof-fresh'
        $w3 = Invoke-C4WriteProof @wpArgs -HarnessGate { param($pr) $true }
        $w4 = Invoke-C4WriteProof @wpArgs -HarnessGate { param($pr) $true } -Validator { param($a) [pscustomobject]@{ Ok = $true; Problems = @() } }
        $wroteOff = Test-Path -LiteralPath (Join-C4Path $pd $script:C4DriverProofName)
        Chk 'OFF: with only the write-time gate off the post-write validation still removes the proof; with BOTH off a proof IS written over a stale harness proof (each lock is real)' ((-not $w3.Written) -and $w4.Written -and $wroteOff) 'controls-tested-off'
        Remove-Item -LiteralPath (Join-C4Path $pd $script:C4DriverProofName) -Force -ErrorAction SilentlyContinue
        [IO.File]::WriteAllText($hpPath, (ConvertTo-Json -InputObject $hpObj -Depth 4))
        $pvTog = [ordered]@{}; foreach ($k in $pvF.Keys) { $pvTog[$k] = $pvF[$k] }; $pvTog.ToggleBuild = $true; $w5 = Invoke-C4WriteProof @wpArgs -ProbeVersion $pvTog
        $pvOther = [ordered]@{}; foreach ($k in $pvF.Keys) { $pvOther[$k] = $pvF[$k] }; $pvOther.CsSha = ('99' * 32); $w6 = Invoke-C4WriteProof @wpArgs -ProbeVersion $pvOther
        $w7 = Invoke-C4WriteProof @wpArgs -ProbeSelfTest ([ordered]@{ Passed = $false })
        $w8 = Invoke-C4WriteProof @wpArgs -LoadedLibPaths @{ 'spike-lib.ps1' = 'Z:\repo\spike-lib.ps1' }
        Chk 'write proof: a toggle-build probe, an embedded source hash that is not NcoProbe.cs, a failed probe self-test and a library loaded from another folder each write NO proof' ((-not $w5.Written) -and (-not $w6.Written) -and (-not $w7.Written) -and (-not $w8.Written) -and -not (Test-Path -LiteralPath (Join-C4Path $pd $script:C4DriverProofName)))
    } finally { Remove-Item -LiteralPath $pd -Recurse -Force -ErrorAction SilentlyContinue }

    Write-Host '== -Prepare against the stand-ins (fake engine, fake harness, fake export, fake files, fake account reads) ==' -ForegroundColor Cyan
    $script:C4Quiet = $true
    $c = & $mk
    $mxSeed = [ordered]@{}; foreach ($n in $script:C4MatrixFiles) { $mb = [Text.Encoding]::ASCII.GetBytes("stand-in $n"); $c.Fs.Seed((Join-C4Path $c.ScriptDir $n), $mb); $mxSeed[$n] = Get-C4BytesSha $mb }
    $script:C4Out.Clear(); $rc = Invoke-C4Prepare -Ctx $c
    $w = $c.World; $fsP = $c.Fs
    $prepRec = $null; try { $prepRec = ConvertFrom-C4Json -Text ($fsP.ReadText((@($fsP.ListFiles($c.OutDir, 'case4-prepare-*.json'))[0]).FullName)) } catch {}
    Chk "prepare: exit 0; the engine holds our provider and S2 naming it and ZERO filters (exit $rc)" (($rc -eq 0) -and $w.Providers.ContainsKey($script:N5ProviderKey) -and ($w.SubLayers[$s2] -eq $script:N5ProviderKey) -and ($w.Filters.Count -eq 0) -and ($w.SubLayers.Count -eq 1)) @('plan-no-filters', 'plan-provider-and-s2-only')
    $dirsOk = (@('root', 'bin', 'drop') | Where-Object { -not (Compare-C4Acl -Expected $prepRec.acl_plan.sddl.$_ -Actual $fsP.GetSddl(@{ root = $c.PubRoot; bin = $c.BinDir; drop = $c.DropDir }[$_])).Equal }).Count -eq 0
    Chk 'prepare: root, bin\ and drop\ exist with exactly the planned DACLs, and the record holds each DACL as read back' ($dirsOk -and $prepRec -and $prepRec.public.drop.read_back -and ($prepRec.nco_sid -eq $ncoSid) -and ($prepRec.operator_sid -eq $opSid))
    $ppBack = ConvertFrom-C4Json -Text ($fsP.ReadText((Join-C4Path $c.BinDir $script:C4ProbeProofName)))
    Chk 'prepare: the probe exe in bin\ hashes like the one the driver proof verified, and the probe proof in bin\ passes the probe''s rules for exactly that hash' (($fsP.Sha256Raw((Join-C4Path $c.BinDir $script:C4ProbeExeName)) -eq $c.Token.ProbeExeSha) -and (@(Test-C4ProbeProof -Proof $ppBack -ExeSha $c.Token.ProbeExeSha -CsSha $c.Token.ProbeCsSha).Count -eq 0)) 'probe-proof-hash-binding'
    Chk 'prepare: the exe and the proof in bin\ were given to Administrators as owner, and bin\ was then checked admin-only for writes (recorded)' (($fsP.Owners[$fsP.Key((Join-C4Path $c.BinDir $script:C4ProbeExeName))] -eq $script:C4AdminsSid) -and ($fsP.Owners[$fsP.Key((Join-C4Path $c.BinDir $script:C4ProbeProofName))] -eq $script:C4AdminsSid) -and (@($c.AdminOnlyAsked) -contains $c.BinDir) -and ($prepRec.public.bin_admin_only.ok -eq $true))
    Chk 'prepare: the engine''s security descriptor and the three containers were read before the add, S2''s and the provider''s after it; S2''s record names the form netsh accepted and keeps the refused braced attempt' ((($c.Counters.SecurityReads | Select-Object -First 4) -join ',') -ceq 'engine ,filter ,sublayer ,provider ' -and $prepRec.security.engine.ok -and $prepRec.security.s2.ok -and ($prepRec.security.s2.command -ceq "netsh wfp show security type=sublayer guid=$s2") -and ($prepRec.security.s2.tries.Count -eq 2) -and ($prepRec.security.s2.tries[0].accepted -eq $false))
    Chk 'prepare: the run sheet lines are printed (F, E, S, A) and recorded' ((@($script:C4Out | Where-Object { $_ -match '--cond [FESA] --live' }).Count -eq 4) -and (@($prepRec.run_sheet).Count -eq 4))
    Chk 'prepare: the sha256 of the five live matrix files beside the driver is in the prepare record; PREPARED is printed only with the record on disk and read back' ((@($script:C4MatrixFiles | Where-Object { [string]$prepRec.matrix_sha256.$_ -ne $mxSeed[$_] }).Count -eq 0) -and (@($script:C4Out | Where-Object { $_ -match '^PREPARED: .*read back' }).Count -eq 1))

    $c = & $mk; $c.ProofCheck = { param($x) Test-C4DriverProof -ProofPath 'Z:\nowhere\case4-selftest-proof.json' -Folder 'Z:\nowhere' -SelfSha ('AB' * 32) -WrappedSha ('AB' * 32) }
    $rc = Invoke-C4Prepare -Ctx $c
    Chk "prepare: without a driver proof it is refused (exit $rc): no engine opened, nothing added, no folder made" (($rc -eq 2) -and ($c.Counters.BackendOpens -eq 0) -and ($c.World.Providers.Count -eq 0) -and ($c.World.SubLayers.Count -eq 0) -and -not $c.Fs.Exists($c.PubRoot)) 'prepare-refused-without-proof'
    $c = & $mk; $c.ProofCheck = { param($x) [pscustomobject]@{ Kind = 'Nep5Case4Proof'; Ok = $true; Nonce = 'forged'; Problems = @() } }
    $rc = Invoke-C4Prepare -Ctx $c
    Chk "prepare: a hand-made token (another nonce) is refused the same way (exit $rc)" (($rc -eq 2) -and ($c.World.SubLayers.Count -eq 0)) 'prepare-refused-without-proof'
    $c = & $mk; $c.ProofCheck = { param($x) [pscustomobject]@{ Kind = 'Nep5Case4Proof'; Ok = $true; Nonce = 'forged'; Problems = @(); ProbeExeSha = $x.Token.ProbeExeSha; ProbeCsSha = $x.Token.ProbeCsSha; HarnessSha = 'FAKE' } }; $c.ProofGate = { param($t) $true }
    $rc = Invoke-C4Prepare -Ctx $c
    Chk "OFF: with the proof gate switched off the same forged token DOES add provider and S2 (exit $rc)" (($rc -eq 0) -and ($c.World.SubLayers.Count -eq 1)) 'controls-tested-off'
    $c = & $mk; $c.IsElevated = { $false }; $rc1 = Invoke-C4Prepare -Ctx $c
    $c2 = & $mk; $c2.AdminOnly = { param($p) [ordered]@{ Ok = $false; Problems = @('stand-in: writable by Users') } }; $rc2 = Invoke-C4Prepare -Ctx $c2
    Chk "prepare: not elevated, or the scripts folder not admin-only, is refused before anything is read or added (exits $rc1, $rc2)" (($rc1 -eq 2) -and ($rc2 -eq 2) -and ($c.Counters.BackendOpens -eq 0) -and ($c2.Counters.BackendOpens -eq 0))

    $staleCases = [ordered]@{
        'S2 present' = { param($x) $x.World.SubLayers[$s2] = '' }
        'the probe key present outside our sublayers' = { param($x) Add-C4FakeFilter -World $x.World -Key $script:C4ProbeKey -SubLayer $foreignSl -Name 'unlabelled' }
        'the public folder present' = { param($x) $x.Fs.EnsureDir($x.PubRoot) }
        'S3 present' = { param($x) $x.World.SubLayers[$s3] = '' }
        'our provider present' = { param($x) $x.World.Providers[$script:N5ProviderKey] = $true }
    }
    $staleBad = @(foreach ($k in $staleCases.Keys) { $c = & $mk; & $staleCases[$k] $c; $f0 = $c.World.Filters.Count; $rc = Invoke-C4Prepare -Ctx $c; if ($rc -ne 2 -or @($c.Backend.Calls | Where-Object { $_ -eq 'addset' }).Count -or $c.World.Filters.Count -ne $f0) { "$k -> $rc" } })
    Chk "prepare: over stale objects (S2, the probe key, the public folder, S3, our provider) it is refused with exit 2 and adds nothing $(if ($staleBad.Count) { '(' + ($staleBad -join '; ') + ')' })" ($staleBad.Count -eq 0) 'prepare-refused-over-stale-objects'
    $c = & $mk; $c.World.SubLayers[$s3] = ''; $c.CleanGate = { param($sw, $x) $true }
    $rc = Invoke-C4Prepare -Ctx $c
    Chk "OFF: with the clean gate switched off it DOES add over a stale S3 (the library's own pre-state read covers only the plan's objects) (exit $rc)" (($rc -eq 0) -and ($c.World.SubLayers.Count -eq 2)) 'controls-tested-off'
    $c = & $mk; Add-C4FakeFilter -World $c.World -Key 'aaaaaaaa-0000-4d8e-9a31-2b6d4c8e0099' -SubLayer $foreignSl -Name "$($script:N5Marker) foreign"
    $before = @($c.World.Filters.Keys) -join ','; $script:C4Out.Clear(); $rc = Invoke-C4Prepare -Ctx $c
    Chk "prepare: a filter of ours outside S1/S2/S3 is a STOP (exit $rc): nothing added, nothing removed, the manual rollback printed" (($rc -eq 9) -and ((@($c.World.Filters.Keys) -join ',') -ceq $before) -and ($c.World.SubLayers.Count -eq 0) -and (@($c.Backend.Calls | Where-Object { $_ -like 'delete*' -or $_ -eq 'addset' }).Count -eq 0) -and (@($script:C4Out | Where-Object { $_ -match 'ManualNep5Rollback' }).Count -ge 1)) 'prepare-stops-on-foreign'
    $c = & $mk; Add-C4FakeFilter -World $c.World -Key 'aaaaaaaa-0000-4d8e-9a31-2b6d4c8e0099' -SubLayer $foreignSl -Name "$($script:N5Marker) foreign"; $c.StopGate = { param($sw) $false }; $c.CleanGate = { param($sw, $x) $true }
    $rc = Invoke-C4Prepare -Ctx $c
    Chk "OFF: with the STOP and clean gates switched off it DOES add beside the foreign filter (exit $rc)" (($rc -eq 0) -and ($c.World.SubLayers.Count -eq 1)) 'controls-tested-off'
    $c = & $mk @($opSid, $ncoSid); $rc = Invoke-C4Prepare -Ctx $c
    Chk "prepare: the account in Administrators is a STOP (exit $rc) before the engine is opened" (($rc -eq 9) -and ($c.Counters.BackendOpens -eq 0) -and ($c.World.SubLayers.Count -eq 0)) 'acl-refuses-admin-member'
    $c = & $mk; $c.Acct.NcoUse = 4; $rcG = Invoke-C4Prepare -Ctx $c; $c2 = & $mk; $c2.Acct.NcoSid = $null; $rcU = Invoke-C4Prepare -Ctx $c2
    $c3 = & $mk; $c3.SidResolver = { param($which) if ($which -eq 'stale') { 'TESTPC\someone' } }; $rcS = Invoke-C4Prepare -Ctx $c3
    Chk "prepare: the account resolving to a group (exit $rcG), not resolving (exit $rcU), or the stale SID resolving (exit $rcS) is refused before the engine is opened" (($rcG -eq 2) -and ($rcU -eq 2) -and ($rcS -eq 2) -and ($c.Counters.BackendOpens + $c2.Counters.BackendOpens + $c3.Counters.BackendOpens -eq 0)) 'acl-refuses-group'
    $c = & $mk; $c.Plan = $pF; $rcPF = Invoke-C4Prepare -Ctx $c; $c2 = & $mk; $c2.Plan = $pF; $c2.PlanGate = { param($pl) @() }; $rcPF2 = Invoke-C4Prepare -Ctx $c2
    Chk "prepare: a plan carrying a filter is refused by the plan gate (exit $rcPF, nothing added); OFF: with the gate switched off the filter IS added (exit $rcPF2)" (($rcPF -eq 2) -and ($c.World.Filters.Count -eq 0) -and ($c.World.SubLayers.Count -eq 0) -and ($c2.World.Filters.Count -eq 1)) @('plan-no-filters', 'controls-tested-off')
    $c = & $mk; $c.Fs.CopyCorrupt = $true; $rc = Invoke-C4Prepare -Ctx $c
    Chk "prepare: a probe exe whose copy in bin\ does not hash like the verified one fails it (exit $rc): the public folder, S2 and the provider are rolled back and read back clean" (($rc -eq 2) -and -not $c.Fs.Exists($c.PubRoot) -and ($c.World.SubLayers.Count -eq 0) -and ($c.World.Providers.Count -eq 0)) 'probe-proof-hash-binding'
    $c = & $mk; $c.Fs.CopyCorrupt = $true; $c.ExeBindGate = { param($a, $b) $true }; $rc = Invoke-C4Prepare -Ctx $c
    Chk "OFF: with the exe binding switched off it DOES prepare with the wrong exe in bin\ (exit $rc)" (($rc -eq 0) -and ($c.Fs.Sha256Raw((Join-C4Path $c.BinDir $script:C4ProbeExeName)) -ne $c.Token.ProbeExeSha)) 'controls-tested-off'
    $c = & $mk; $c.Fs.DropAceOnCreate = $c.DropDir; $rc = Invoke-C4Prepare -Ctx $c
    $c2 = & $mk; $c2.Fs.DropAceOnCreate = $c2.DropDir; $c2.AclReadBackGate = { param($a, $b) $true }; $rc2 = Invoke-C4Prepare -Ctx $c2
    Chk "prepare: a DACL that reads back without an ACE fails it and everything is rolled back (exit $rc); OFF: with the read-back gate switched off it prepares anyway (exit $rc2)" (($rc -eq 2) -and -not $c.Fs.Exists($c.PubRoot) -and ($c.World.SubLayers.Count -eq 0) -and ($rc2 -eq 0)) 'controls-tested-off'
    $binNotAdmin = { param($x) $a = $x.AdminOnlyAsked; $bd = $x.BinDir; $x.AdminOnly = { param($p) [void]$a.Add([string]$p); if ($p -eq $bd) { [ordered]@{ Ok = $false; Problems = @('stand-in: the operator owns bin\ncoprobe.exe'); Checked = 3 } } else { [ordered]@{ Ok = $true; Problems = @(); Checked = 1 } } }.GetNewClosure() }
    $c = & $mk; & $binNotAdmin $c; $rc = Invoke-C4Prepare -Ctx $c
    $c2 = & $mk; & $binNotAdmin $c2; $c2.BinAdminOnlyGate = { param($r) $true }; $rc2 = Invoke-C4Prepare -Ctx $c2
    Chk "prepare: a bin\ that does not read admin-only for writes fails it and everything is rolled back (exit $rc); OFF: with that gate switched off it prepares anyway (exit $rc2)" (($rc -eq 2) -and -not $c.Fs.Exists($c.PubRoot) -and ($c.World.SubLayers.Count -eq 0) -and ($rc2 -eq 0)) 'controls-tested-off'
    $c = & $mk; $c.Backend.FailAddAfter = 1; $rc = Invoke-C4Prepare -Ctx $c
    Chk "prepare: an add that fails half-way is rolled back by key and reads back clean (exit $rc)" (($rc -eq 2) -and ($c.World.Providers.Count -eq 0) -and ($c.World.SubLayers.Count -eq 0) -and -not $c.Fs.Exists($c.PubRoot))
    $c = & $mk; $c.Fs.FailJsonMatch = 'case4-prepare-'; $script:C4Out.Clear(); $rc = Invoke-C4Prepare -Ctx $c
    Chk "prepare: when the prepare record cannot be written it exits $rc (not 0), never prints PREPARED, and rolls the add and the folder back (read back clean)" (($rc -eq 2) -and (@($script:C4Out | Where-Object { $_ -match '^PREPARED' }).Count -eq 0) -and ($c.World.SubLayers.Count -eq 0) -and ($c.World.Providers.Count -eq 0) -and -not $c.Fs.Exists($c.PubRoot))
    $c = & $mk; $c.OperatorToken = { throw 'stand-in: token read failed' }; $script:C4Out.Clear(); $rcT = Invoke-C4Prepare -Ctx $c; $outT = @($script:C4Out)
    $c2 = & $mk; $c2.Acct.LookupThrows = $true; $script:C4Out.Clear(); $rcL = Invoke-C4Prepare -Ctx $c2; $outL = @($script:C4Out)
    $c4 = & $mk; $c4.ReadWfpSecurity = { param($t, $g) if ($t -eq 'engine') { throw 'stand-in: netsh failed' } }; $rcN = Invoke-C4Prepare -Ctx $c4
    Chk "prepare: an error before the add (the token read, the account lookup, the engine security read) exits 2, not 7 (exits $rcT, $rcL, $rcN), adds nothing and prints the manual rollback for reference" (($rcT -eq 2) -and ($rcL -eq 2) -and ($rcN -eq 2) -and ($c.Counters.BackendOpens -eq 0) -and ($c2.Counters.BackendOpens -eq 0) -and ($c.World.SubLayers.Count + $c2.World.SubLayers.Count + $c4.World.SubLayers.Count -eq 0) -and (@($outT | Where-Object { $_ -match 'ManualNep5Rollback' }).Count -ge 1) -and (@($outL | Where-Object { $_ -match 'ManualNep5Rollback' }).Count -ge 1))
    $c3 = & $mk; $c3.Fs.CopyCorrupt = $true; $c3.Backend.FailDelete = @($script:N5ProviderKey); $script:C4Out.Clear(); $rc7 = Invoke-C4Prepare -Ctx $c3
    Chk "prepare: exit 7 is reserved for a failure after the add whose rollback did NOT read back clean (the provider could not be deleted: exit $rc7, the manual rollback printed)" (($rc7 -eq 7) -and $c3.World.Providers.ContainsKey($script:N5ProviderKey) -and (@($script:C4Out | Where-Object { $_ -match 'ManualNep5Rollback' }).Count -ge 1))

    Write-Host '== -Collect, -Finish, -PartD, -Check and -DryRun against the stand-ins ==' -ForegroundColor Cyan
    $psOf = { param($x) $x.Fs.Sha256Raw((Join-C4Path $x.BinDir $script:C4ProbeProofName)) }
    $recFor = { param($x, $cond, $user, $exp, $procId, $addRc = '0x00000000', $exeSha = $null) New-C4TestRecord -Cond $cond -UserSid $user -Expected $exp -ExeSha $(if ($exeSha) { $exeSha } else { $x.Token.ProbeExeSha }) -ProcId $procId -AddRc $addRc -DelRc $(if ($addRc -eq '0x00000000') { '0x00000000' } else { '0x80320003' }) -CsSha $x.Token.ProbeCsSha -ProofSha (& $psOf $x) -NcoSid $ncoSid }
    $prepared = {
        $x = & $mk; [void](Invoke-C4Prepare -Ctx $x)
        $at = [datetimeoffset]::Now; $n = 0
        foreach ($d in @(@('F', $ncoSid, $true, 3, '0x80070005'), @('E', $ncoSid, $true, 2, '0x00000000'), @('S', $opSid, $false, 3, '0x80070005'), @('A', $opSid, $false, 2, '0x00000000'))) {
            $n++
            $r = New-C4TestRecord -Cond $d[0] -UserSid $d[1] -Expected $d[2] -ExeSha $x.Token.ProbeExeSha -Elevation $d[3] -AddRc $d[4] -DelRc $(if ($d[4] -eq '0x00000000') { '0x00000000' } else { '0x80320003' }) -At $at.AddSeconds($n) -ProcId (5000 + $n) -CsSha $x.Token.ProbeCsSha -ProofSha (& $psOf $x) -NcoSid $ncoSid
            [void](Add-C4TestDrop -Ctx $x -Record $r)
        }
        $x
    }
    $c = & $prepared; $col = Invoke-C4Collect -Ctx $c
    Chk "collect: four valid records (F, E, S, A) give exit 0, a table row each, and a byte-identical copy of each in the out dir's case4-runs (exit $($col.Code))" (($col.Code -eq 0) -and (@($col.Valid).Count -eq 4) -and (@($col.Rows).Count -eq 4) -and (@($col.Copies | Where-Object { $_.status -eq 'written' }).Count -eq 4) -and (@(Get-C4UncopiedEvidence -Ctx $c).Count -eq 0))
    $runsK = Join-C4Path $c.OutDir 'case4-runs'; $copyOwners = @(@($c.Fs.ListFiles($runsK, 'case4-*.json')) | ForEach-Object { $c.Fs.Owners[$c.Fs.Key($_.FullName)] })
    Chk "collect: the copies folder and each of the four copies were given to Administrators as owner through the file seam, and the record names the folder's owner (owners: $(@(@($c.Fs.Owners[$c.Fs.Key($runsK)]) + $copyOwners) -join ', '))" (($c.Fs.Owners[$c.Fs.Key($runsK)] -eq $script:C4AdminsSid) -and ($copyOwners.Count -eq 4) -and (@($copyOwners | Where-Object { $_ -ne $script:C4AdminsSid }).Count -eq 0) -and ($col.CopiesFolderOwner -eq $script:C4AdminsSid)) 'copy-owner'
    $col2 = Invoke-C4Collect -Ctx $c
    Chk 'collect: run again, the copies read exists-same and nothing changes (exit 0)' (($col2.Code -eq 0) -and (@($col2.Copies | Where-Object { $_.status -eq 'exists-same' }).Count -eq 4))
    $cNo = & $prepared
    $cNo.Fs | Add-Member -MemberType ScriptMethod -Name SetOwnerAdmins -Value { param($p) [void]$this.Calls.Add("setowner $p"); if ([string]$p -match 'case4-runs') { throw 'stand-in: SetSecurityInfo refused' }; if (-not $this.Exists($p)) { throw "no file $p" }; $this.Owners[$this.Key($p)] = 'S-1-5-32-544'; $this.Writes++ } -Force
    $script:C4Out.Clear(); $colNo = Invoke-C4Collect -Ctx $cNo
    Chk "collect: when the copies' owner cannot be set the copies stay, each status says so, the four records are listed not copied and none is counted, the folder's owner reads as an error, the failures are printed in red and the exit is 4 (exit $($colNo.Code))" (($colNo.Code -eq 4) -and (@($colNo.Copies | Where-Object { $_.status -match '^written, owner not set' }).Count -eq 4) -and (@($colNo.Uncopied).Count -eq 4) -and (@($colNo.Valid).Count -eq 0) -and ([string]$colNo.CopiesFolderOwner -match '^error') -and (@($script:C4Out | Where-Object { $_ -match 'owner could not be set to Administrators' }).Count -eq 4) -and (@($cNo.Fs.ListFiles((Join-C4Path $cNo.OutDir 'case4-runs'), 'case4-*.json')).Count -eq 4)) 'copy-owner'
    $bad = & $recFor $c 'F' $ncoSid $true 6001 '0x00000000' ('DD' * 32); [void](Add-C4TestDrop -Ctx $c -Record $bad); $c.Fs.Seed((Join-C4Path $c.DropDir 'junk.txt'), [Text.Encoding]::ASCII.GetBytes('junk'))
    $col3 = Invoke-C4Collect -Ctx $c
    Chk "collect: a record naming another exe and a stray file are listed invalid with the reason and never counted (exit $($col3.Code))" (($col3.Code -eq 4) -and (@($col3.Valid).Count -eq 4) -and (@($col3.Invalid).Count -eq 2) -and (@($col3.Invalid | Where-Object { @($_.reasons) -match 'probe_exe_sha256' }).Count -eq 1)) 'record-validation'
    $c = & $prepared; $c.RecordValidator = { param($a) @() }; [void](Add-C4TestDrop -Ctx $c -Record (& $recFor $c 'F' $ncoSid $true 6002 '0x00000000' ('DD' * 32))); $colOff = Invoke-C4Collect -Ctx $c
    Chk "OFF: with the record validator switched off the record naming another exe IS counted (5 valid, exit $($colOff.Code))" (@($colOff.Valid).Count -eq 5) 'controls-tested-off'
    $c = & $prepared; Add-C4FakeFilter -World $c.World -Key $script:C4ProbeKey -SubLayer $s2 -Name $script:C4DisplayName; $colL = Invoke-C4Collect -Ctx $c
    Chk "collect: the probe's filter still in S2 is recorded as left behind (exit $($colL.Code))" (($colL.Code -eq 21) -and (@($colL.LeftBehind) -contains $script:C4ProbeKey)) 'collect-left-behind'
    $c = & $prepared; [void](Add-C4TestDrop -Ctx $c -Record (& $recFor $c 'F' $otherSid $false 6003)); $colW = Invoke-C4Collect -Ctx $c
    $c2 = & $prepared; [void](Add-C4TestDrop -Ctx $c2 -Record (& $recFor $c2 'F' $otherSid $false 6004 '0x80070005')); $colW2 = Invoke-C4Collect -Ctx $c2
    Chk "collect: an F record whose add SUCCEEDED under another principal is a STOP (exit $($colW.Code)); the same record with the add denied is only invalid (exit $($colW2.Code))" (($colW.Code -eq 9) -and (@($colW.WrongAccount).Count -eq 1) -and ($colW2.Code -eq 4) -and (@($colW2.WrongAccount).Count -eq 0)) 'record-wrong-account-stop'
    $c = & $prepared; [void](Add-C4TestDrop -Ctx $c -Record (New-C4TestRecord -Cond 'F' -UserSid $opSid -Expected $false -ExeSha $c.Token.ProbeExeSha -ProcId 6006 -CsSha $c.Token.ProbeCsSha -ProofSha (& $psOf $c) -NcoSid $ncoSid -WrongPrincipal)); $colP = Invoke-C4Collect -Ctx $c
    Chk "collect: a wrong_principal record (F by the operator, refused by the probe before the engine) is listed invalid by principal, never counted, and is no STOP (exit $($colP.Code))" (($colP.Code -eq 4) -and (@($colP.Valid).Count -eq 4) -and (@($colP.Invalid).Count -eq 1) -and (@($colP.Invalid | Where-Object { $_.kind -eq 'by-principal' }).Count -eq 1) -and (@($colP.WrongAccount).Count -eq 0)) 'record-validation'
    $c = & $prepared; $wr = & $recFor $c 'F' $otherSid $false 6007; $c.Fs.Seed((Join-C4Path $c.DropDir ([string]$wr.record_file_name + '.bak')), [Text.Encoding]::UTF8.GetBytes((ConvertTo-Json -InputObject $wr -Depth 10))); $colB = Invoke-C4Collect -Ctx $c
    Chk "collect: a wrong-principal F record whose add succeeded, saved under a name that is not a record name, is still the STOP (exit $($colB.Code)) and is listed as misnamed, never counted" (($colB.Code -eq 9) -and (@($colB.WrongAccount).Count -eq 1) -and (@($colB.Invalid | Where-Object { $_.kind -eq 'misnamed' }).Count -eq 1) -and (@($colB.Valid).Count -eq 4)) 'record-wrong-account-stop'
    $c = & $prepared; $c.Fs.EnsureDir((Join-C4Path $c.DropDir 'sub')); $c.Fs.Seed((Join-C4Path (Join-C4Path $c.DropDir 'sub') 'case4-E-20261019-120000-1.json'), [Text.Encoding]::ASCII.GetBytes('{}')); $colS = Invoke-C4Collect -Ctx $c; $rcS = Invoke-C4Finish -Ctx $c
    Chk "collect and finish: a sub-folder in drop\ is a listed, refused finding (exit $($colS.Code)), and -Finish keeps the public folder over it, its record never copied (exit $rcS)" (($colS.Code -eq 4) -and (@($colS.Invalid | Where-Object { $_.kind -eq 'sub-folder' }).Count -eq 1) -and ($rcS -eq 7) -and $c.Fs.Exists($c.PubRoot)) 'finish-removes-folder'
    $c = & $prepared; [void](Add-C4TestDrop -Ctx $c -Record (New-C4TestRecord -Cond 'A' -UserSid $opSid -Expected $false -ExeSha $c.Token.ProbeExeSha -ProcId 6008 -CsSha $c.Token.ProbeCsSha -ProofSha (& $psOf $c) -NcoSid $ncoSid -Elevation 3 -Admins 'deny-only')); $colT = Invoke-C4Collect -Ctx $c
    Chk "collect: an A line typed into the non-elevated console (filtered token, Administrators deny-only) is listed invalid by token state and not counted, A stays at its one valid record (exit $($colT.Code))" (($colT.Code -eq 4) -and (@($colT.Invalid | Where-Object { $_.kind -eq 'by-token-state' }).Count -eq 1) -and (@($colT.Rows | Where-Object { $_.cond -eq 'A' }).Count -eq 1)) 'record-validation'
    $c = & $prepared; $colEx = Invoke-C4Collect -Ctx $c -ElevationRefusedNote 'Windows refused to elevate nco-probe'
    $c2 = & $prepared; foreach ($e in @($c2.Fs.ListFiles($c2.DropDir, 'case4-E-*.json'))) { [void]$c2.Fs.Files.Remove($c2.Fs.Key($e.FullName)) }; $colE0 = Invoke-C4Collect -Ctx $c2 -ElevationRefusedNote 'Windows refused to elevate nco-probe'
    $c3 = & $prepared; foreach ($e in @($c3.Fs.ListFiles($c3.DropDir, 'case4-E-*.json'))) { [void]$c3.Fs.Files.Remove($c3.Fs.Key($e.FullName)) }; [void](Add-C4TestDrop -Ctx $c3 -Record (New-C4TestRecord -Cond 'E' -UserSid $opSid -Expected $false -ExeSha $c3.Token.ProbeExeSha -ProcId 6009 -CsSha $c3.Token.ProbeCsSha -ProofSha (& $psOf $c3) -NcoSid $ncoSid -WrongPrincipal)); $colEw = Invoke-C4Collect -Ctx $c3 -ElevationRefusedNote 'Windows refused to elevate nco-probe'
    Chk "collect: -ElevationRefused is counted as the E result when no E record shows the token E is about (exit $($colE0.Code); with a wrong_principal E refusal beside it, counted and the refusal listed, exit $($colEw.Code)), and NOT counted beside a valid E record under the account's elevated token (exit $($colEx.Code))" ($colE0.ElevationRefused.counted -and ($colE0.Code -eq 0) -and $colEw.ElevationRefused.counted -and ($colEw.Code -eq 4) -and ($colEx.ElevationRefused.counted -eq $false) -and ($colEx.Code -eq 4)) 'record-validation'
    $eDrop = { param($cc, [hashtable]$sw) foreach ($e in @($cc.Fs.ListFiles($cc.DropDir, 'case4-E-*.json'))) { [void]$cc.Fs.Files.Remove($cc.Fs.Key($e.FullName)) }; [void](Add-C4TestDrop -Ctx $cc -Record (New-C4TestRecord -Cond 'E' -UserSid $ncoSid -Expected $true -ExeSha $cc.Token.ProbeExeSha -ProcId 6012 -CsSha $cc.Token.ProbeCsSha -ProofSha (& $psOf $cc) -NcoSid $ncoSid @sw)) }
    $ca = & $prepared; & $eDrop $ca @{ OpenFailed = $true }; $colOf = Invoke-C4Collect -Ctx $ca -ElevationRefusedNote 'Windows refused to elevate nco-probe'
    $cb = & $prepared; & $eDrop $cb @{ OpenThrew = $true }; $colOt = Invoke-C4Collect -Ctx $cb -ElevationRefusedNote 'Windows refused to elevate nco-probe'
    $cu = & $prepared; & $eDrop $cu @{ Elevation = 3 }; $colUn = Invoke-C4Collect -Ctx $cu -ElevationRefusedNote 'Windows refused to elevate nco-probe'
    $c1 = & $prepared; & $eDrop $c1 @{ Elevation = 1 }; $colB1 = Invoke-C4Collect -Ctx $c1 -ElevationRefusedNote 'Windows refused to elevate nco-probe'
    $c1d = & $prepared; & $eDrop $c1d @{ Elevation = 1; NcoDenyOnly = $true }; $colB1d = Invoke-C4Collect -Ctx $c1d -ElevationRefusedNote 'Windows refused to elevate nco-probe'
    Chk "collect, elevation_refused judged on the token: an E run by the account under its elevated token whose engine open failed or threw contradicts the note (not counted; exits $($colOf.Code), $($colOt.Code)); an E line run in the account's unelevated console (type 3, invalid by token state) does not (counted; exit $($colUn.Code) for the invalid record)" ((-not $colOf.ElevationRefused.counted) -and ($colOf.Code -eq 4) -and (-not $colOt.ElevationRefused.counted) -and ($colOt.Code -eq 4) -and $colUn.ElevationRefused.counted -and ($colUn.Code -eq 4) -and (@($colUn.Invalid | Where-Object { $_.kind -eq 'by-token-state' }).Count -eq 1)) 'record-validation'
    Chk "collect, the batch-logon route: an E record by the account under an unsplit token (type 1) with the group enabled is valid, counted, and contradicts the note (not counted; exit $($colB1.Code)); the same token with the group deny-only is invalid by token state and does not contradict it (counted; exit $($colB1d.Code))" ((-not $colB1.ElevationRefused.counted) -and ($colB1.Code -eq 4) -and (@($colB1.Valid | Where-Object { $_.file -like 'case4-E-*' }).Count -eq 1) -and (@($colB1.Rows | Where-Object { $_.cond -ceq 'E' -and $_.elevation_type -match '^1\b' }).Count -eq 1) -and $colB1d.ElevationRefused.counted -and ($colB1d.Code -eq 4) -and (@($colB1d.Invalid | Where-Object { $_.kind -eq 'by-token-state' }).Count -eq 1)) 'record-validation'
    $c = & $prepared; [void](Add-C4TestDrop -Ctx $c -Record (New-C4TestRecord -Cond 'F' -UserSid $ncoSid -Expected $true -ExeSha $c.Token.ProbeExeSha -ProcId 6010 -CsSha $c.Token.ProbeCsSha -ProofSha (& $psOf $c) -NcoSid $ncoSid -CloseThrew)); $script:C4Out.Clear(); $colP = Invoke-C4Collect -Ctx $c
    Chk "collect: a valid record carrying the probe's STOP line (a close that threw) is counted, and its STOP line is printed and recorded (exit $($colP.Code))" ((@($colP.ProbeStops).Count -eq 1) -and (@($script:C4Out | Where-Object { $_ -match '^\s+PROBE STOP LINE: case4-F-' }).Count -eq 1) -and (@($colP.Valid).Count -eq 5)) 'record-validation'
    $c = & $prepared; [void](Add-C4TestDrop -Ctx $c -Record (New-C4TestRecord -Cond 'F' -UserSid $ncoSid -Expected $true -ExeSha $c.Token.ProbeExeSha -ProcId 6011 -CsSha $c.Token.ProbeCsSha -ProofSha (& $psOf $c) -NcoSid $ncoSid -DelRc '0x80070005' -DelPresent 'unreadable')); $script:C4Out.Clear(); $colQ = Invoke-C4Collect -Ctx $c
    Chk "collect: a valid filter_possibly_left_behind record keeps -Collect at 21 even when the engine reads clean (exit $($colQ.Code)), and its STOP line and the left-behind claim are printed and recorded" (($colQ.Code -eq 21) -and (@($colQ.ProbeLeft).Count -eq 1) -and (@($colQ.ProbeStops).Count -eq 1) -and (@($script:C4Out | Where-Object { $_ -match '^\s+PROBE SAYS FILTER_POSSIBLY_LEFT_BEHIND: case4-F-' }).Count -eq 1) -and (@($colQ.Valid).Count -eq 5)) 'record-validation'
    $c = & $prepared; $script:C4Out.Clear(); $colH = Invoke-C4Collect -Ctx $c
    Chk 'collect: each file''s sha256 is printed and recorded with its copy in case4-runs\' ((@($script:C4Out | Where-Object { $_ -match '^\s+[0-9a-f]{64}\s+case4-[FESA]-' }).Count -eq 4) -and (@($colH.Copies | Where-Object { $_.sha256 -match '^[0-9a-f]{64}$' }).Count -eq 4))
    $c = & $mk; $fsx = $c.Fs
    $mkPrep = { param($name, $at, $marker) $fsx.WriteJson((Join-C4Path $c.OutDir $name), [ordered]@{ kind = 'nep5-case4-prepare'; ok = $true; at = $at; stamp = 'x'; marker = $marker }) }
    & $mkPrep 'case4-prepare-20261019-100000.json' '2026-10-19T10:00:00.0000000-04:00' 'earlier'
    & $mkPrep 'case4-prepare-20261019-083000.json' '2026-10-19T08:30:00.0000000-07:00' 'later'
    $lp = Get-C4LatestPrepare -Ctx $c
    Chk "prepare record selection: by the UTC instant it records, not by its local-time file name (an attempt at 14:00Z named 100000 against one at 15:30Z named 083000: picked '$($lp.Record.marker)')" ($lp.Ok -and $lp.Record.marker -eq 'later')
    $c = & $prepared; Add-C4FakeFilter -World $c.World -Key 'aaaaaaaa-0000-4d8e-9a31-2b6d4c8e0099' -SubLayer $foreignSl -Name "$($script:N5Marker) foreign"; $colF = Invoke-C4Collect -Ctx $c
    Chk "collect: a foreign filter of ours is a STOP (exit $($colF.Code))" (($colF.Code -eq 9) -and (@($colF.Foreign).Count -eq 1))

    $c = & $prepared; Add-C4FakeFilter -World $c.World -Key $script:C4ProbeKey -SubLayer $s2 -Name $script:C4DisplayName
    $script:C4Out.Clear(); $rc = Invoke-C4Finish -Ctx $c
    $finRec = $null; try { $finRec = ConvertFrom-C4Json -Text ($c.Fs.ReadText((@($c.Fs.ListFiles($c.OutDir, 'case4-final-*.json'))[0]).FullName)) } catch {}
    Chk "finish: exit $rc; the probe's key was deleted by key on our engine, then S2 by the harness and the provider by key; the engine is empty" (($rc -eq 0) -and (@($c.Backend.Calls | Where-Object { $_ -eq "delete filter $($script:C4ProbeKey)" }).Count -eq 1) -and (@($c.Runner.State.Calls | Where-Object { $_ -match "^delete-sublayer --sublayer $s2 --live" }).Count -eq 1) -and (@($c.Backend.Calls | Where-Object { $_ -eq "delete provider $($script:N5ProviderKey)" }).Count -eq 1) -and ($c.World.Filters.Count -eq 0) -and ($c.World.SubLayers.Count -eq 0) -and ($c.World.Providers.Count -eq 0)) 'finish-removes-by-key'
    Chk 'finish: the library''s fixed keys were each deleted by key as well (the safety net), and the final record says verified with the engine SD compared' ((@($script:N5FilterKeys.Values | Where-Object { @($c.Backend.Calls) -notcontains "delete filter $_" }).Count -eq 0) -and $finRec -and ($finRec.verified -eq $true) -and ($finRec.engine_sd.compare.same -eq $true)) 'finish-removes-by-key'
    $dropCalls = @($c.Fs.Calls | Where-Object { $_ -like 'setdacl*' -or $_ -like 'removetree*' })
    Chk 'finish: drop\''s DACL was cut to SYSTEM and Administrators and read back BEFORE the tree was deleted; the record holds the read-back' (($dropCalls.Count -eq 2) -and ($dropCalls[0] -like 'setdacl*') -and ($dropCalls[1] -like 'removetree*') -and $finRec -and (Test-C4AceRemoval -Expected (Get-C4DropSddlAfterRemoval) -Actual $finRec.folder.drop_acl.read_back -GoneSids @($ncoSid, $opSid))) 'finish-ace-removal-read-back'
    Chk 'finish: the public folder is gone and read back absent; the four records remain as copies in the out dir' ((-not $c.Fs.Exists($c.PubRoot)) -and ($finRec.folder.removed -eq $true) -and (@($c.Fs.ListFiles((Join-C4Path $c.OutDir 'case4-runs'), 'case4-*.json')).Count -eq 4)) 'finish-removes-folder'
    $c = & $prepared; Add-C4FakeFilter -World $c.World -Key $script:C4ProbeKey -SubLayer $s2 -Name $script:C4DisplayName
    $c.Runner.State.FailDeleteFilter = @($script:C4ProbeKey); $c.Backend.FailDelete = @($script:C4ProbeKey, $s2)
    $script:C4Out.Clear(); $rc = Invoke-C4Finish -Ctx $c
    Chk "finish: a filter that cannot be deleted leaves the sweep unclean: exit $rc, the manual rollback runs and is printed, the public folder is KEPT" (($rc -eq 7) -and ($c.Counters.ManualRollbacks -eq 1) -and (@($script:C4Out | Where-Object { $_ -match 'ManualNep5Rollback' }).Count -ge 1) -and $c.Fs.Exists($c.PubRoot)) 'finish-sweep-must-be-clean'
    $c = & $prepared; Add-C4FakeFilter -World $c.World -Key $script:C4ProbeKey -SubLayer $s2 -Name $script:C4DisplayName
    $c.Runner.State.FailDeleteFilter = @($script:C4ProbeKey); $c.Backend.FailDelete = @($script:C4ProbeKey, $s2); $c.FinishSweepGate = { param($sw, $pk) $true }
    $rc = Invoke-C4Finish -Ctx $c
    Chk "OFF: with the sweep gate switched off it DOES go on to delete the folder and claim exit $rc over a filter still in S2" (($rc -eq 0) -and -not $c.Fs.Exists($c.PubRoot) -and $c.World.Filters.ContainsKey($script:C4ProbeKey)) @('finish-sweep-must-be-clean', 'controls-tested-off')
    $c = & $prepared; $c.Fs.IgnoreSetDacl = $true; $rc = Invoke-C4Finish -Ctx $c
    $c2 = & $prepared; $c2.Fs.IgnoreSetDacl = $true; $c2.AceRemovalGate = { param($a, $b, $g) $true }; $rc2 = Invoke-C4Finish -Ctx $c2
    Chk "finish: an ACE removal that does not read back keeps the folder (exit $rc); OFF: with the read-back gate switched off the tree IS deleted while the account's ACE remained (exit $rc2)" (($rc -eq 7) -and $c.Fs.Exists($c.PubRoot) -and ($rc2 -eq 0) -and -not $c2.Fs.Exists($c2.PubRoot)) @('finish-ace-removal-read-back', 'controls-tested-off')
    $c = & $prepared; $c.Fs.FailWriteBytes = $true; $rc = Invoke-C4Finish -Ctx $c
    $c2 = & $prepared; $c2.Fs.FailWriteBytes = $true; $c2.EvidenceGate = { param($m) $true }; $rc2 = Invoke-C4Finish -Ctx $c2
    Chk "finish: records that could not be copied keep the folder (exit $rc); OFF: with the evidence gate switched off the folder is deleted over uncopied records (exit $rc2)" (($rc -eq 7) -and $c.Fs.Exists($c.PubRoot) -and ($rc2 -eq 0) -and -not $c2.Fs.Exists($c2.PubRoot)) @('finish-removes-folder', 'controls-tested-off')
    $c = & $prepared; Add-C4FakeFilter -World $c.World -Key 'aaaaaaaa-0000-4d8e-9a31-2b6d4c8e0099' -SubLayer $foreignSl -Name "$($script:N5Marker) foreign"; $rc = Invoke-C4Finish -Ctx $c
    Chk "finish: a foreign filter is a STOP before anything is removed (exit $rc): provider, S2 and the folder still there" (($rc -eq 9) -and ($c.World.SubLayers.Count -eq 1) -and $c.Fs.Exists($c.PubRoot) -and (@($c.Backend.Calls | Where-Object { $_ -like 'delete*' }).Count -eq 0))
    $c = & $prepared; [void](Add-C4TestDrop -Ctx $c -Record (& $recFor $c 'F' $otherSid $false 6005)); $rc = Invoke-C4Finish -Ctx $c
    Chk "finish: the wrong-principal finding still lets the removal run and verify, and the exit is the STOP $rc" (($rc -eq 9) -and ($c.World.SubLayers.Count -eq 0) -and -not $c.Fs.Exists($c.PubRoot)) 'record-wrong-account-stop'

    $seedPrep = { param($x) $x.Fs.WriteJson((Join-C4Path $x.OutDir 'case4-prepare-20261019-120000.json'), [ordered]@{ kind = 'nep5-case4-prepare'; ok = $true; at = [datetimeoffset]::Now.AddHours(-1).ToString('o'); stamp = '20261019-120000'; nco_sid = $ncoSid; operator_sid = $opSid }) }
    $pdc = & $mk; & $seedPrep $pdc; $pdc.Acct.NcoSid = $null; $pdc.Acct.NetUserExit = 2; $pdc.Acct.NetUserText = 'The user name could not be found. NET HELPMSG 2221.'; $pdc.Acct.GroupMemberNames = @('TESTPC\other'); $pdc.Acct.ProfileExists = $false
    $rcD = Invoke-C4PartD -Ctx $pdc
    $pdRec = $null; try { $pdRec = ConvertFrom-C4Json -Text ($pdc.Fs.ReadText((@($pdc.Fs.ListFiles($pdc.OutDir, 'case4-partd-*.json'))[0]).FullName)) } catch {}
    $pdReads = @('NetUser', 'Lookup', 'GroupName', 'NetLocalGroup', 'ProfileDir', 'PathExists', 'ProfileListEntry', 'ProfileFolders')
    $readOnly = (@($pdc.Acct.Calls | Where-Object { $_ -notin $pdReads }).Count -eq 0)
    Chk "partd: all gone gives 20 (exit $rcD), the record is written with the account's SID from the prepare record, and the only account calls were the eight reads ($(@($pdc.Acct.Calls) -join ', '))" (($rcD -eq 20) -and $pdRec -and ($pdRec.code -eq 20) -and ($pdRec.account_sid -eq $ncoSid) -and $readOnly -and (@($pdc.Acct.Calls | Select-Object -Unique).Count -eq 8)) 'partd-reads'
    $pdOwned = @($pdc.Fs.ListFiles($pdc.OutDir, 'case4-partd-*.json') | ForEach-Object { $pdc.Fs.Owners[$pdc.Fs.Key($_.FullName)] })
    Chk "partd: the record it wrote was given to Administrators as owner through the file seam (owners: $($pdOwned -join ', '))" (($pdOwned.Count -eq 1) -and ($pdOwned[0] -eq $script:C4AdminsSid)) 'record-owner'
    $pdNoOwn = & $mk; & $seedPrep $pdNoOwn; $pdNoOwn.Acct.NcoSid = $null; $pdNoOwn.Acct.NetUserExit = 2; $pdNoOwn.Acct.NetUserText = 'NET HELPMSG 2221'; $pdNoOwn.Acct.GroupMemberNames = @(); $pdNoOwn.Acct.ProfileExists = $false
    $pdNoOwn.Fs | Add-Member -MemberType ScriptMethod -Name SetOwnerAdmins -Value { param($p) throw 'stand-in: SetSecurityInfo refused' } -Force
    $script:C4Out.Clear(); $rcNoOwn = Invoke-C4PartD -Ctx $pdNoOwn
    Chk "partd: when the owner cannot be set the record stays on disk, the failure is printed in red and the mode still returns its reading (exit $rcNoOwn)" ((@($pdNoOwn.Fs.ListFiles($pdNoOwn.OutDir, 'case4-partd-*.json')).Count -eq 1) -and (@($script:C4Out | Where-Object { $_ -match 'owner could not be set to Administrators' }).Count -eq 1) -and ($rcNoOwn -eq 20)) 'record-owner'
    $pdBad = @(foreach ($k in @('account', 'lookup', 'member', 'profile', 'unreadable', 'profilelist', 'suffix-folder', 'folders-unreadable', 'no-sid')) {
        $x = & $mk; if ($k -ne 'no-sid') { & $seedPrep $x }; $x.Acct.NcoSid = $null; $x.Acct.NetUserExit = 2; $x.Acct.NetUserText = 'NET HELPMSG 2221'; $x.Acct.GroupMemberNames = @(); $x.Acct.ProfileExists = $false
        switch ($k) { 'account' { $x.Acct.NetUserExit = 0 } 'lookup' { $x.Acct.NcoSid = $ncoSid } 'member' { $x.Acct.GroupMemberNames = @('nco-probe') } 'profile' { $x.Acct.ProfileExists = $true } 'unreadable' { $x.Acct.NetLocalGroupExit = 5 }
                      'profilelist' { $x.Acct.ProfileListPresent = $true; $x.Acct.ProfileListImage = 'Z:\Users\nco-probe.TESTPC' } 'suffix-folder' { $x.Acct.ProfileFolderNames = @('nco-probe.TESTPC') } 'folders-unreadable' { $x.Acct.ProfileFoldersReadable = $false } }
        $r = Invoke-C4PartD -Ctx $x; if ($r -ne 21) { "$k -> $r" } })
    Chk "partd: the account still there, still resolving, still a member, its default profile folder, an unreadable membership, its ProfileList entry, a nco-probe.<suffix> folder, an unlistable profiles folder, or no SID on record each give 21 $(if ($pdBad.Count) { '(' + ($pdBad -join '; ') + ')' })" ($pdBad.Count -eq 0) 'partd-reads'

    $ck = & $mk; $ck.Acct.NetUserExit = 2; $ck.Acct.NetUserText = 'NET HELPMSG 2221'; $ck.Acct.GroupMemberNames = @(); $ck.Acct.ProfileExists = $false; $rcK0 = Invoke-C4Check -Ctx $ck
    $ck1 = & $mk; $rcK1 = Invoke-C4Check -Ctx $ck1
    $ck2 = & $mk; $ck2.NewBackend = { throw 'stand-in: engine unavailable' }; $ck2.Acct.NetUserExit = 2; $ck2.Acct.NetUserText = 'NET HELPMSG 2221'; $ck2.Acct.GroupMemberNames = @(); $ck2.Acct.ProfileExists = $false; $rcK2 = Invoke-C4Check -Ctx $ck2
    $ck3 = & $prepared; $ck3.Acct.NetUserExit = 2; $ck3.Acct.NetUserText = 'NET HELPMSG 2221'; $ck3.Acct.GroupMemberNames = @(); $ck3.Acct.ProfileExists = $false; $rcK3 = Invoke-C4Check -Ctx $ck3
    Chk "check: nothing there 20 ($rcK0); the account, its membership and profile present 21 ($rcK1); the engine unopenable 22 ($rcK2); provider, S2 and the public folder after -Prepare 21 ($rcK3); nothing was written or removed" (($rcK0 -eq 20) -and ($rcK1 -eq 21) -and ($rcK2 -eq 22) -and ($rcK3 -eq 21) -and ($ck.Fs.Writes -eq 0) -and ($ck3.World.SubLayers.Count -eq 1) -and (@($ck3.Backend.Calls | Where-Object { $_ -like 'delete*' -or $_ -eq 'addset' }).Count -eq 1))

    $dr = & $mk; $script:C4Out.Clear(); $rcR = Invoke-C4DryRun -Ctx $dr
    $out = @($script:C4Out)
    Chk "dry run: exit $rcR; it prints the ACL plan, the probe proof with the exe hash, the four command lines and the manual rollback; it opened no engine, ran no harness verb and wrote nothing" (($rcR -eq 0) -and (@($out | Where-Object { $_ -match '^\s+drop\s+O:BAD:P' }).Count -eq 1) -and (@($out | Where-Object { $_ -match [regex]::Escape($dr.Token.ProbeExeSha.ToLowerInvariant()) }).Count -ge 1) -and (@($out | Where-Object { $_ -match '--cond [FESA] --live' }).Count -eq 4) -and (@($out | Where-Object { $_ -match 'ManualNep5Rollback' }).Count -ge 1) -and ($dr.Counters.BackendOpens -eq 0) -and (@($dr.Runner.State.Calls).Count -eq 0) -and ($dr.Fs.Writes -eq 0))
    $script:C4Quiet = $false

    Write-Host '== parser checks: seams and the account lifecycle ==' -ForegroundColor Cyan
    $selfText = [IO.File]::ReadAllText($PSCommandPath)
    $seamP = @(Get-C4SeamProblems -Text $selfText)
    Chk "seams: every engine, harness, export, ACL, account, netsh, net and process call of this file sits inside a *-C4Real* seam; the real context is built once, in the live branch only; the proof-time seams run only under if (`$WriteProof) $(if ($seamP.Count) { '(' + (($seamP | Select-Object -First 4) -join '; ') + ')' })" ($seamP.Count -eq 0) 'seams'
    $selfAstT = [Management.Automation.Language.Parser]::ParseInput($selfText, [ref]$null, [ref]$null)
    $plantAt = { param($fnName, $code) $f = $selfAstT.Find({ param($x) $x -is [Management.Automation.Language.FunctionDefinitionAst] -and $x.Name -eq $fnName }, $true); $o = $f.Body.Extent.StartOffset + 1; $selfText.Substring(0, $o) + "`n    " + $code + "`n" + $selfText.Substring($o) }
    $parses = { param($t) $e = $null; [void][Management.Automation.Language.Parser]::ParseInput($t, [ref]$null, [ref]$e); @($e).Count -eq 0 }
    $found = { param($t, $what) @(Get-C4SeamProblems -Text $t | Where-Object { $_ -match $what }).Count -ge 1 }
    $fx = $script:C4Corpus.fixtures
    $corpusPath = Join-C4Path $PSScriptRoot $script:C4CorpusName
    $corpusText = [IO.File]::ReadAllText($corpusPath)
    $corpusBad = [ordered]@{
        'a pattern missing'                    = { param($c) $c.patterns.Remove('lifecycle_commands') }
        'an alternative that is not a regex'   = { param($c) $c.patterns['lifecycle_apis']['alternatives'][0]['alt'] = '(unclosed' }
        'a pattern with no alternatives'       = { param($c) $c.patterns['machine_types']['alternatives'] = @() }
        'a template without its slot'          = { param($c) $c.patterns['net_names']['template'] = '(?i)^net$' }
        'an alternative without a plant'       = { param($c) $c.patterns['fs_members']['alternatives'][0]['plant'] = '' }
        'another schema'                       = { param($c) $c['schema'] = 'nep5-case4-lock-corpus-v1' }
        'an empty fixture set'                 = { param($c) $c.fixtures['lifecycle_ps'] = @() }
        'a switch allowlist that is a string'  = { param($c) $c['switch_allowlist'] = 'x' }
    }
    $corpusMissed = @(foreach ($k in $corpusBad.Keys) { $cc = ConvertFrom-Json -InputObject $corpusText -AsHashtable -Depth 20; & $corpusBad[$k] $cc; if (@(Test-C4LockCorpus -Corpus $cc).Count -eq 0) { $k } })
    $dupText = $corpusText -replace '^\{', '{ "schema": "nep5-case4-lock-corpus-v2",'
    $dupKeys = @(Get-C4JsonDuplicateKeys -Text $dupText)
    $dupTmp = Join-C4Path ([IO.Path]::GetTempPath()) ('c4-corpus-dup-' + [guid]::NewGuid().ToString('N') + '.json'); [IO.File]::WriteAllText($dupTmp, $dupText)
    $dupRefused = $false
    try { [void](Read-C4LockCorpus -Path $dupTmp) } catch { $dupRefused = ($_.Exception.Message -match 'gives a key twice') } finally { Remove-Item -LiteralPath $dupTmp -Force -ErrorAction SilentlyContinue }
    Chk "lock corpus: $($script:C4CorpusName) beside this script is usable ($($script:C4CorpusPatternKeys.Count) patterns, $($script:C4CorpusFixtureKeys.Count) fixture sets) and bound by the driver proof; a copy with $(@($corpusBad.Keys) -join ', ') is each refused, and the loader refuses a key given twice ($($dupKeys -join ', ')) $(if ($corpusMissed.Count) { '(NOT refused: ' + ($corpusMissed -join ', ') + ')' })" ((@(Test-C4LockCorpus -Corpus $script:C4Corpus).Count -eq 0) -and ($script:C4TextFiles -ccontains $script:C4CorpusName) -and ($corpusMissed.Count -eq 0) -and ($dupKeys.Count -ge 1) -and $dupRefused -and (@(Get-C4JsonDuplicateKeys -Text $corpusText).Count -eq 0)) @('seams', 'no-account-lifecycle', 'controls-tested-off')
    $runLock = {
        param($scope, $plant)
        switch ($scope) {
            'seams' { @(Get-C4SeamProblems -Text ("function Get-C4PlantHost {`n" + $plant + "`n}`n")) }
            'lifecycle' { @(Get-C4LifecycleHits -Text $plant -Kind ps) }
            'lifecycle-cs' { @(Get-C4LifecycleHits -Text $plant -Kind cs) }
            default { @("unknown scope $scope") }
        }
    }
    $altMiss = New-Object System.Collections.Generic.List[string]; $altRun = 0
    foreach ($k in $script:C4CorpusPatternKeys) {
        $pd = $script:C4Corpus.patterns[$k]; $var = $script:C4CorpusPatternVars[$k]; $orig = (Get-Variable -Scope Script -Name $var).Value
        foreach ($al in @($pd.alternatives)) {
            $altRun++
            $withIt = @(& $runLock $pd.scope $al.plant | Where-Object { $_ -match $al.finding })
            Set-Variable -Scope Script -Name $var -Value (Get-C4CorpusPattern -Pattern $pd -Without $al.alt)
            try { $without = @(& $runLock $pd.scope $al.plant | Where-Object { $_ -match $al.finding }) } finally { Set-Variable -Scope Script -Name $var -Value $orig }
            if ($withIt.Count -lt 1) { $altMiss.Add("$k '$($al.alt)': its plant is not found") } elseif ($without.Count -ne 0) { $altMiss.Add("$k '$($al.alt)': its plant is still found without it") }
        }
    }
    $floorMiss = @(foreach ($k in $script:C4CorpusPatternKeys) { $n = @($script:C4Corpus.patterns[$k].alternatives).Count; if ($n -lt $script:C4CorpusAlternativeFloors[$k]) { "$k has $n alternatives, fewer than the $($script:C4CorpusAlternativeFloors[$k]) this driver pins" } })
    Chk "lock corpus, table-driven: each of the $altRun alternatives of the $($script:C4CorpusPatternKeys.Count) patterns catches its own plant, and with that alternative removed the plant is not found; no pattern has fewer alternatives than this driver pins $(if ($altMiss.Count + $floorMiss.Count) { '(' + ((@($altMiss | Select-Object -First 8) + @($floorMiss)) -join '; ') + ')' })" (($altRun -ge 248) -and ($altMiss.Count -eq 0) -and ($floorMiss.Count -eq 0)) @('seams', 'no-account-lifecycle', 'controls-tested-off')
    $initCalls = @($selfAstT.FindAll({ param($x) $x -is [Management.Automation.Language.CommandAst] -and $x.GetCommandName() -eq 'Initialize-C4LockCorpus' }, $true))
    $initIfs = @($selfAstT.FindAll({ param($x) $x -is [Management.Automation.Language.IfStatementAst] -and $x.Clauses[0].Item1.Extent.Text -eq '$SelfTest' -and -not $x.ElseClause }, $false))
    $readCalls = @($selfAstT.FindAll({ param($x) $x -is [Management.Automation.Language.CommandAst] -and $x.GetCommandName() -eq 'Read-C4LockCorpus' }, $true) | ForEach-Object { $q = $_.Parent; while ($q -and $q -isnot [Management.Automation.Language.FunctionDefinitionAst]) { $q = $q.Parent }; if ($q) { $q.Name } else { 'the entry' } })
    $initOk = ($initCalls.Count -eq 1) -and (@($initIfs | Where-Object { ($_.Clauses[0].Item2.Extent.StartOffset -le $initCalls[0].Extent.StartOffset) -and ($_.Clauses[0].Item2.Extent.EndOffset -ge $initCalls[0].Extent.EndOffset) }).Count -eq 1) -and (@($readCalls | Where-Object { $_ -notin @('Initialize-C4LockCorpus', 'Invoke-C4SelfTest') }).Count -eq 0)
    Chk "lock corpus: parsed for -SelfTest only (one Initialize-C4LockCorpus call, inside the entry's if (`$SelfTest); the reader called only from it and the self-test: $(($readCalls | Select-Object -Unique) -join ', ')); a live mode binds it by hash and never parses it" $initOk @('seams')
    $inSelf = @(@($fx.lifecycle_ps) + @($fx.lifecycle_cs) | Where-Object { $selfText.Contains($_) })
    Chk "lock corpus: none of its $(@($fx.lifecycle_ps).Count + @($fx.lifecycle_cs).Count) planted lifecycle forms appears in this script's own text (they live only in the data file) $(if ($inSelf.Count) { '(in the script: ' + ($inSelf -join '; ') + ')' })" ($inSelf.Count -eq 0) 'no-account-lifecycle'
    $named = @(foreach ($pn in @($fx.seam_named)) { [ordered]@{ name = $pn.name; text = (& $plantAt $pn.function $pn.code); finding = $pn.finding } })
    $namedMiss = @($named | Where-Object { -not ((& $parses $_.text) -and (& $found $_.text $_.finding)) } | ForEach-Object { $_.name })
    $plantedSeam = @($named | Where-Object { $_.finding -match 'New-Nep5RealBackend' })[0].text
    Chk "seams: each of the lock corpus's $($named.Count) named plants ($(@($named | ForEach-Object { $_.name }) -join '; ')) parses and is found by name $(if ($namedMiss.Count) { '(MISSED: ' + ($namedMiss -join ', ') + ')' })" (($named.Count -ge 4) -and ($namedMiss.Count -eq 0)) 'seams'
    Chk 'OFF: with the machine-command list emptied the planted engine open is NOT found (so the finding above is the check, not an accident)' (@(Get-C4SeamProblems -Text $plantedSeam -CommandRegex '^$' | Where-Object { $_ -match 'New-Nep5RealBackend' }).Count -eq 0) @('seams', 'controls-tested-off')
    $seamPlants = @($fx.seam_plants)
    $seamMissed = @(foreach ($sp in $seamPlants) { $t = & $plantAt 'Get-C4PrepPlan' $sp.code; if (-not ((& $parses $t) -and (& $found $t $sp.finding))) { $sp.name } })
    Chk "seams: each of the lock corpus's $($seamPlants.Count) machine or file calls planted in a pure function parses and is found by name ($(@($seamPlants | ForEach-Object { $_.name }) -join ', ')) $(if ($seamMissed.Count) { '(MISSED: ' + ($seamMissed -join ', ') + ')' })" (($seamPlants.Count -ge 14) -and ($seamMissed.Count -eq 0)) 'seams'
    $fsOff = & $plantAt 'Get-C4PrepPlan' $fx.fs_off
    Chk 'OFF: with the file-type list emptied the planted CreateDirectory is NOT found (the finding above is the check)' (@(Get-C4SeamProblems -Text $fsOff -FsTypeRegex '^$' | Where-Object { $_ -match 'CreateDirectory' }).Count -eq 0) @('seams', 'controls-tested-off')
    $lcSelf = @(Get-C4LifecycleHits -Text $selfText -Kind ps)
    $rlPath = Resolve-LibPath -Name 'run-limited.ps1'; $lcRl = $(if (Test-Path -LiteralPath $rlPath) { @(Get-C4LifecycleHits -Text ([IO.File]::ReadAllText($rlPath)) -Kind ps) } else { @('run-limited.ps1 missing') })
    Chk "no account lifecycle: none of the lock's forms appears in this driver or run-limited.ps1 (its limit: a command or type name built at run time, or run through a variable, is not seen) $(if ($lcSelf.Count + $lcRl.Count) { '(' + ((@($lcSelf) + @($lcRl)) -join '; ') + ')' })" (($lcSelf.Count -eq 0) -and ($lcRl.Count -eq 0)) 'no-account-lifecycle'
    $probeCs = Resolve-LibPath -Name 'NcoProbe.cs'
    if (Test-Path -LiteralPath $probeCs) {
        $lcCs = @(Get-C4LifecycleHits -Text ([IO.File]::ReadAllText($probeCs)) -Kind cs)
        Chk "no account lifecycle: the probe source NcoProbe.cs carries none of the forbidden APIs $(if ($lcCs.Count) { '(' + ($lcCs -join '; ') + ')' })" ($lcCs.Count -eq 0) 'no-account-lifecycle'
    } elseif ($WriteProof) { Chk "no account lifecycle: the probe source NcoProbe.cs must be beside this script for -WriteProof (missing: $probeCs)" $false 'no-account-lifecycle' }
    else {
        Write-Host "  NOTE: the probe source is not present ($probeCs): the C# check ran on a stand-in source; -WriteProof checks the real one." -ForegroundColor Yellow
        Chk 'no account lifecycle: a stand-in probe source carries none of the forbidden APIs (a forbidden name inside a comment is not a finding)' (@(Get-C4LifecycleHits -Text $fx.cs_comment_only -Kind cs).Count -eq 0) 'no-account-lifecycle'
    }
    foreach ($sib in @('build-probe.ps1', 'run-probe-selftest.ps1')) { $sp = Resolve-LibPath -Name $sib; if (Test-Path -LiteralPath $sp) { $h = @(Get-C4LifecycleHits -Text ([IO.File]::ReadAllText($sp)) -Kind ps); Chk "no account lifecycle: $sib $(if ($h.Count) { '(' + ($h -join '; ') + ')' })" ($h.Count -eq 0) 'no-account-lifecycle' } }
    $plants = @($fx.lifecycle_ps)
    $notFound = @($plants | Where-Object { @(Get-C4LifecycleHits -Text $_ -Kind ps).Count -eq 0 })
    $csPlants = @($fx.lifecycle_cs)
    $csNotFound = @($csPlants | Where-Object { @(Get-C4LifecycleHits -Text $_ -Kind cs).Count -eq 0 })
    $psCs = $fx.ps_carrying_cs
    Chk "no account lifecycle: each of the lock corpus's $($plants.Count) PowerShell forms and $($csPlants.Count) C# forms, and its C# carried in a PowerShell string, is found $(if ($notFound.Count + $csNotFound.Count) { '(MISSED: ' + ((@($notFound) + @($csNotFound | ForEach-Object { 'C#' })) -join '; ') + ')' })" (($plants.Count -ge 38) -and ($csPlants.Count -ge 6) -and ($notFound.Count -eq 0) -and ($csNotFound.Count -eq 0) -and (@(Get-C4LifecycleHits -Text $psCs -Kind ps).Count -ge 1)) 'no-account-lifecycle'
    $libTexts = @($script:C4LoadedLibPaths.Values | Where-Object { $_ -match '(?i)spike-(lib|persist-lib|task-driver|nep5-lib)\.ps1$' } | ForEach-Object { [IO.File]::ReadAllText($_) })
    $libLc = @(Get-C4LibLifecycleFunctions -Texts $libTexts)
    $libNamed = @($fx.library_helpers)
    $libUnlisted = @($libLc | Where-Object { $_ -notmatch $script:C4LifecycleCommands })
    $selfCallsLib = @($selfAstT.FindAll({ param($x) $x -is [Management.Automation.Language.CommandAst] -and $libLc -contains $x.GetCommandName() }, $true) | ForEach-Object { "line $($_.Extent.StartLineNumber): $($_.GetCommandName())" })
    Chk "no account lifecycle: the dot-sourced libraries' functions that reach a lifecycle command (computed from the $($libTexts.Count) loaded texts: $($libLc -join ', ')) include the three named helpers, are each on the forbidden list, and this driver calls none $(if ($libUnlisted.Count + $selfCallsLib.Count) { '(' + ((@($libUnlisted | ForEach-Object { "unlisted $_" }) + $selfCallsLib) -join '; ') + ')' })" (($libTexts.Count -eq 4) -and (@($libNamed | Where-Object { $libLc -notcontains $_ }).Count -eq 0) -and ($libUnlisted.Count -eq 0) -and ($selfCallsLib.Count -eq 0)) 'no-account-lifecycle'
    $readsFound = @(@($fx.lifecycle_reads) | Where-Object { @(Get-C4LifecycleHits -Text $_ -Kind ps).Count -ne 0 })
    Chk "no account lifecycle: the lock corpus's $(@($fx.lifecycle_reads).Count) read forms (the two reads, by literal and by [string] parameter) are NOT findings $(if ($readsFound.Count) { '(FOUND: ' + ($readsFound -join '; ') + ')' })" ((@($fx.lifecycle_reads).Count -ge 4) -and ($readsFound.Count -eq 0))
    $addTypes = @($selfAstT.FindAll({ param($x) $x -is [Management.Automation.Language.CommandAst] -and $x.GetCommandName() -eq 'Add-Type' }, $true))
    Chk "this file compiles no C# of its own: no Add-Type call anywhere in it (the library's Initialize-Nep5Type is the only compile) $(if ($addTypes.Count) { '(found at line ' + (($addTypes | ForEach-Object { $_.Extent.StartLineNumber }) -join ', ') + ')' })" ($addTypes.Count -eq 0) 'seams'
    Chk "no account lifecycle: the slash-switch allowlist is empty ($(@($script:C4LifecycleSwitchAllowed).Count) entries); the lock corpus's planted switch '$($fx.switch_plant)' is found" ((@($script:C4LifecycleSwitchAllowed).Count -eq 0) -and (@(Get-C4LifecycleHits -Text $fx.switch_plant -Kind ps | Where-Object { $_ -match [regex]::Escape("slash switch ($($fx.switch_plant))") }).Count -eq 1)) 'no-account-lifecycle'
    Chk 'OFF: with the planted switch on the allowlist the same plant is NOT found (the empty allowlist is the check)' (@(Get-C4LifecycleHits -Text $fx.switch_plant -Kind ps -SwitchAllowed @($fx.switch_plant)).Count -eq 0) @('no-account-lifecycle', 'controls-tested-off')
    Chk 'OFF: with the lifecycle command list emptied the lock corpus''s planted account cmdlet is NOT found (the finding above is the check)' ((@(Get-C4LifecycleHits -Text $fx.lifecycle_off -Kind ps).Count -ge 1) -and (@(Get-C4LifecycleHits -Text $fx.lifecycle_off -Kind ps -CommandRegex '^$').Count -eq 0)) @('no-account-lifecycle', 'controls-tested-off')

    if ($WriteProof) {
        Write-Host '== -WriteProof: the probe''s own self-test, ncoprobe.exe --version (no engine), the matrix''s harness proof, then the proof ==' -ForegroundColor Cyan
        $pst = Invoke-C4RealProbeSelfTest -Folder $PSScriptRoot
        $pstP = ConvertFrom-C4ProbeSelfTest -Stdout $pst.Stdout -ExitCode $pst.Exit
        Chk "the probe's own self-test (run-probe-selftest.ps1) passed: exit $($pst.Exit), $($pstP.ChecksRun) checks, $($pstP.ChecksFailed) failed" $pstP.Passed
        $pv = Invoke-C4RealProbeVersion -Folder $PSScriptRoot
        $pvP = ConvertFrom-C4ProbeVersion -Stdout $pv.Stdout -ExitCode $pv.Exit
        $pvP['TraceEmpty'] = [bool]$pv.TraceEmpty
        $exeNow = Get-N5RawSha256 -Path (Join-C4Path $PSScriptRoot $script:C4ProbeExeName)
        Chk "ncoprobe.exe --version names its own bytes, is not a toggle build and opened no engine ($($pvP.Problem))" ($pvP.Ok -and ($pvP.ExeSha -ieq [string]$exeNow) -and ($pvP.ToggleBuild -eq $false) -and $pv.TraceEmpty)
        $hpReal = @(Test-N5HarnessLiveProof -Path (Join-C4Path $PSScriptRoot $script:C4HarnessProofName) -ExeSha (Get-N5RawSha256 -Path (Join-C4Path $PSScriptRoot 'halfset.exe')) -RsSha (Get-N5RawSha256 -Path (Join-C4Path $PSScriptRoot 'halfset.rs')))
        Chk "the matrix's harness proof beside this script is valid now $(if ($hpReal.Count) { '(' + ($hpReal -join '; ') + ')' })" ($hpReal.Count -eq 0) 'harness-live-proof-fresh'
    }
    $passedTags = @($script:c4TagsPassed | Select-Object -Unique | Where-Object { $script:c4TagsFailed -notcontains $_ })
    $missingTags = @($script:C4RequiredTags | Where-Object { $passedTags -notcontains $_ })
    Chk "every one of the $($script:C4RequiredTags.Count) required tags passed $(if ($missingTags.Count) { '(missing: ' + ($missingTags -join ', ') + ')' })" ($missingTags.Count -eq 0)
    if ($WriteProof) {
        $wp = Invoke-C4WriteProof -Folder $PSScriptRoot -SelfSha $script:C4SelfSha -LoadedLibHashes $script:LoadedLibHashes -LoadedLibFolder $script:LoadedLibFolder -LoadedLibPaths $script:C4LoadedLibPaths -WrappedSha $imp.Sha256 `
                                  -ChecksRun $script:c4Total -ChecksPassed ($script:c4Total - $script:c4Fail) -PassedTags $passedTags -FailedChecks @($script:c4FailedNames) -ProbeVersion $pvP -ProbeSelfTest $pstP `
                                  -HostInfo ("$($Host.Name) $($PSVersionTable.PSVersion) $($PSVersionTable.PSEdition) on $([Environment]::OSVersion.Version)")
        if ($wp.Written) { Write-Host "PROOF WRITTEN: $($wp.Path) ($($script:c4Total) checks, $($passedTags.Count) tags; validated after writing)" -ForegroundColor Green }
        else { Write-Host 'NO PROOF WRITTEN:' -ForegroundColor Red; $wp.Problems | ForEach-Object { Write-Host "   $_" -ForegroundColor Red }; $script:c4Fail++ }
    }
    $script:N5LiveProof = $null; $script:C4ProofNonce = $null
    Write-Host ("case 4 driver self-test: {0} ({1} checks run, {2} failed)" -f $(if ($script:c4Fail -eq 0) { 'all passed' } else { 'FAILED' }), $script:c4Total, $script:c4Fail) -ForegroundColor $(if ($script:c4Fail -eq 0) { 'Green' } else { 'Red' })
    return $(if ($script:c4Fail -eq 0) { 0 } else { 1 })
}

# ---- entry -----------------------------------------------------------------------------------------------------------------------------------------------------
$argErrors = @(Test-C4Args -Modes @{ SelfTest = $SelfTest.IsPresent; DryRun = $DryRun.IsPresent; Check = $Check.IsPresent; Prepare = $Prepare.IsPresent; Collect = $Collect.IsPresent; Finish = $Finish.IsPresent; PartD = $PartD.IsPresent } -WriteProof $WriteProof.IsPresent -ElevationRefused $ElevationRefused)
if ($argErrors.Count) { $argErrors | ForEach-Object { Write-Host "ARG ERROR: $_" -ForegroundColor Red }; exit 2 }
# The driver proof binds this file by its own name, so every mode but the attended -SelfTest runs only under that name.
if ((-not $SelfTest -or $WriteProof) -and ((Split-Path -Leaf $PSCommandPath) -cne $script:C4SelfName)) {
    Write-Host "REFUSED: this driver is running as $(Split-Path -Leaf $PSCommandPath); its proof binds it as $($script:C4SelfName). Nothing was read or changed." -ForegroundColor Red
    exit 2
}
# The lock corpus is parsed for -SelfTest only; the live modes bind it by hash through the driver proof and never parse it.
if ($SelfTest) {
    try { Initialize-C4LockCorpus -Path (Join-C4Path $PSScriptRoot $script:C4CorpusName) }
    catch { Write-Host "REFUSED: $($_.Exception.Message). -SelfTest needs the lock corpus; the libraries were loaded, nothing else was read or changed." -ForegroundColor Red; exit 2 }
}
$c4rc = 2; $ctx = $null
try {
    if ($SelfTest) { $c4rc = 1; try { $c4rc = Invoke-C4SelfTest } catch { Write-Host "SELFTEST ABORTED (counted as a failure): $($_.Exception.Message)" -ForegroundColor Red; Write-Host $_.ScriptStackTrace -ForegroundColor DarkGray; $c4rc = 1 } }
    else {
        $ctx = New-C4RealCtx -ScriptDir $PSScriptRoot
        if ($DryRun) { $c4rc = Invoke-C4DryRun -Ctx $ctx }
        elseif ($Check) { $c4rc = Invoke-C4Check -Ctx $ctx }
        elseif ($Prepare) { $c4rc = Invoke-C4Prepare -Ctx $ctx }
        elseif ($Collect) { $c4rc = (Invoke-C4Collect -Ctx $ctx -ElevationRefusedNote $ElevationRefused).Code }
        elseif ($Finish) { $c4rc = Invoke-C4Finish -Ctx $ctx -ElevationRefusedNote $ElevationRefused }
        elseif ($PartD) { $c4rc = Invoke-C4PartD -Ctx $ctx }
    }
} catch {
    Write-Host "STOPPED: $($_.Exception.Message)" -ForegroundColor Red
    Write-Host $_.ScriptStackTrace -ForegroundColor DarkGray
    # Only what can escape: -Prepare's own entry classifies every error by whether the add started, so an escape is from building the context (nothing
    # added: 2). -Finish: not verified (7). -Collect: nothing claimed (21). -Check: unreadable (22). -PartD: not proven gone (21). -DryRun: 2.
    $c4rc = $(if ($Check) { 22 } elseif ($PartD) { 21 } elseif ($Finish) { 7 } elseif ($Collect) { 21 } else { 2 })
} finally {
    if ($ctx -and $ctx.Close) { try { & $ctx.Close } catch {} }
    $script:N5LiveProof = $null
}
exit $c4rc
