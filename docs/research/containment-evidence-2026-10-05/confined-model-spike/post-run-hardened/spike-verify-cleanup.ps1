#requires -Version 5.1
<#
.SYNOPSIS
  #1689 spike: assert that every trace of the spike is GONE. Read-only. Exit 0 only if every check passes;
  1 if any trace remains; 2 if the SID needed for the ACL/right checks is unknown (cannot prove it: not a pass).

.DESCRIPTION
  Checks (each prints PASS/FAIL with the evidence):
    account absent | scheduled task absent | C:\blarai-spike absent | C:\Users\blarai-spike absent |
    profile registration absent | no process owned by the SID | SeBatchLogonRight does not hold the SID |
    no ACE for the SID (by SID or by name) on the venv, its base interpreter, the model dir | no WFP object from
    the spike's keys (read-only engine query; elevated only) | blarai-coder untouched (its account, if it existed
    before, is still there: reported, not asserted).
  The SID comes from spike-state.cleaned.json (written by spike-cleanup.ps1), else spike-state.json, else the live
  account. ACL scans use `icacls <path> /T /C` over the whole tree (thousands of files; a minute or two); -Quick
  scans the top level only.
  -SelfTest: pure scanning logic against fabricated icacls output; no system access.
#>
[CmdletBinding()]
param([switch]$SelfTest, [switch]$Quick, [string]$WfpScript = 'C:\Users\_OPERATOR_\blarai-research-data\wfp-spike\wfp-coder-egress-spike.ps1')
$ErrorActionPreference = 'Stop'
. "$PSScriptRoot\spike-lib.ps1"

function Test-IsElevated { ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator) }

if ($SelfTest) {
    $f = 0
    function Chk([string]$n, [bool]$c) { if ($c) { Write-Host "  [PASS] $n" -ForegroundColor Green } else { Write-Host "  [FAIL] $n" -ForegroundColor Red; $script:f++ } }
    $sid = 'S-1-5-21-1111111111-2222222222-3333333333-1001'
    $clean = @('B:\models\Qwen3.5-4B-int8-ov BUILTIN\Administrators:(I)(F)', '                             NT AUTHORITY\SYSTEM:(I)(F)', 'Successfully processed 1 files; Failed processing 0 files')
    $byName = $clean + 'B:\models\x\a.bin _MACHINE_\blarai-spike:(I)(RX)'
    $bySid  = $clean + "B:\models\x\b.bin $sid`:(I)(RX)"
    Chk 'a clean icacls listing yields no hit' ((Find-SidInIcaclsText $clean $sid 'blarai-spike').Count -eq 0)
    Chk 'an ACE shown by account name is found' ((Find-SidInIcaclsText $byName $sid 'blarai-spike').Count -eq 1)
    Chk 'an orphaned ACE shown as the raw SID is found' ((Find-SidInIcaclsText $bySid $sid 'blarai-spike').Count -eq 1)
    Chk 'a different account SID (the pre-existing orphan on the venv) is NOT a hit' ((Find-SidInIcaclsText @('x S-1-5-21-1000000004-1000000005-1000000006-2931813655:(I)(OI)(CI)(RX,W)') $sid 'blarai-spike').Count -eq 0)
    Chk 'blarai-coder is not a hit for blarai-spike' ((Find-SidInIcaclsText @('x _MACHINE_\blarai-coder:(F)') $sid 'blarai-spike').Count -eq 0)
    Write-Host ("verify selftest: {0}" -f $(if ($f -eq 0) { 'all passed' } else { "$f FAILED" })) -ForegroundColor $(if ($f -eq 0) { 'Green' } else { 'Red' })
    exit $(if ($f -eq 0) { 0 } else { 1 })
}

$results = New-Object System.Collections.ArrayList
function Add-Check([string]$Name, [bool]$Pass, [string]$Evidence) {
    [void]$results.Add([pscustomobject]@{ name = $Name; pass = $Pass; evidence = $Evidence })
    Write-Host ("  [{0}] {1}  {2}" -f $(if ($Pass) { 'PASS' } else { 'FAIL' }), $Name, $Evidence) -ForegroundColor $(if ($Pass) { 'Green' } else { 'Red' })
}

Write-Host ("== verify cleanup of {0} ({1}) ==" -f $script:SpikeUser, (Get-Date -Format 'yyyy-MM-dd HH:mm:ss K'))
$sid = $null; $src = ''
foreach ($pair in @(@($script:SpikeCleanedPath, 'spike-state.cleaned.json'), @($script:SpikeStatePath, 'spike-state.json'))) {
    if (-not $sid -and (Test-Path -LiteralPath $pair[0])) { $sid = [string]((Get-Content -LiteralPath $pair[0] -Raw | ConvertFrom-Json).spike_sid); $src = $pair[1] }
}
$user = Get-LocalUser -Name $script:SpikeUser -ErrorAction SilentlyContinue
if ($user) { if (-not $sid) { $sid = $user.SID.Value; $src = 'the live account' } }
Write-Host ("SID under test: {0} (from {1})" -f $(if ($sid) { $sid } else { '<unknown>' }), $(if ($src) { $src } else { 'nowhere' }))

Add-Check 'account absent' (-not $user) $(if ($user) { "local user '$($script:SpikeUser)' STILL EXISTS" } else { 'Get-LocalUser finds none' })
$t = Get-ScheduledTask -TaskPath $script:SpikeTaskPath -TaskName $script:SpikeTaskName -ErrorAction SilentlyContinue
Add-Check 'scheduled task absent' (-not $t) "$($script:SpikeTaskPath)$($script:SpikeTaskName)"
Add-Check 'C:\blarai-spike absent' (-not (Test-PathExistsNoFollow $script:SpikeRoot)) $script:SpikeRoot
Add-Check 'C:\Users\blarai-spike absent' (-not (Test-PathExistsNoFollow $script:SpikeProfileDir)) $script:SpikeProfileDir

if ($sid) {
    $prof = Get-CimInstance Win32_UserProfile -Filter "SID='$sid'" -ErrorAction SilentlyContinue
    Add-Check 'profile registration absent' (-not $prof) "Win32_UserProfile SID=$sid"
    $owned = @()
    foreach ($p in (Get-CimInstance Win32_Process)) { try { $o = Invoke-CimMethod -InputObject $p -MethodName GetOwnerSid -ErrorAction Stop; if ($o.Sid -eq $sid) { $owned += "$($p.ProcessId):$($p.Name)" } } catch { } }
    Add-Check 'no process owned by the SID' ($owned.Count -eq 0) $(if ($owned.Count) { $owned -join ', ' } else { 'none' })
    $vfyTmp = New-PrivateTempDir; $inf = Join-Path $vfyTmp 'vfy.inf'
    try {
        & secedit /export /cfg $inf /areas USER_RIGHTS *> $null
        $holders = Get-PrivilegeHolders (Get-Content -LiteralPath $inf) 'SeBatchLogonRight'
        Add-Check 'SeBatchLogonRight does not hold the SID' ($holders -notcontains "*$sid") ("holders now: " + ($holders -join ','))
    } catch { Add-Check 'SeBatchLogonRight readable' $false $_.Exception.Message } finally { Remove-PrivateTempDir $vfyTmp }

    # ACEs: scan the three trees the provision step granted on.
    $state = $null; foreach ($p in @($script:SpikeCleanedPath, $script:SpikeStatePath)) { if (-not $state -and (Test-Path -LiteralPath $p)) { $state = Get-Content -LiteralPath $p -Raw | ConvertFrom-Json } }
    $venv = if ($state) { [string]$state.venv } else { $script:SpikeVenv }
    $model = if ($state) { [string]$state.model_dir } else { $script:SpikeModelDir }
    $base = if ($state) { [string]$state.venv_base_home } else { $null }
    $scanPaths = @($venv, $base, $model) | Where-Object { $_ }
    foreach ($p in $scanPaths) {
        if (-not (Test-Path -LiteralPath $p)) { Add-Check "ACL scan $p" $false 'path does not exist, cannot scan (was it moved?)'; continue }
        $sw = [Diagnostics.Stopwatch]::StartNew()
        $out = if ($Quick) { & icacls.exe $p 2>&1 } else { & icacls.exe $p /T /C 2>&1 }
        $hits = Find-SidInIcaclsText ($out | ForEach-Object { "$_" }) $sid $script:SpikeUser
        Add-Check ("no ACE for the spike SID/name under {0}{1}" -f $p, $(if ($Quick) { ' (top level only)' } else { ' (whole tree)' })) ($hits.Count -eq 0) $(if ($hits.Count) { "$($hits.Count) hit(s), first: $($hits[0])" } else { "scanned in $([int]$sw.Elapsed.TotalSeconds) s, none found" })
    }
} else {
    Write-Host '  [UNVERIFIABLE] no SID is known (no state file, no account): profile, process, user-right and ACL checks cannot be run.' -ForegroundColor Yellow
}

# WFP: dynamic objects should be gone with their process; look by the wrapped script's keys (read-only).
if ((Test-IsElevated) -and (Test-Path -LiteralPath $WfpScript)) {
    try {
        $tokens = $null; $errs = $null
        $ast = [Management.Automation.Language.Parser]::ParseFile($WfpScript, [ref]$tokens, [ref]$errs)
        $assign = $ast.FindAll({ param($n) $n -is [Management.Automation.Language.AssignmentStatementAst] -and $n.Left.Extent.Text -eq '$csharp' }, $true) | Select-Object -First 1
        $csharp = & ([scriptblock]::Create($assign.Right.Extent.Text))
        if (-not ('BlarAI.Wfp.Plan' -as [type])) { Add-Type -TypeDefinition $csharp -Language CSharp }
        $e = [BlarAI.Wfp.Engine]::Open($false, 'BlarAI #1689 verify (read-only)')
        try {
            $plan = [BlarAI.Wfp.Plan]::Build('S-1-5-21-1-2-3-1001')
            $present = @($plan.Filters | Where-Object { $e.FilterExists($_.Key) })
            Add-Check 'no WFP provider/sublayer/filter from the spike keys' (-not $e.SubLayerExists() -and -not $e.ProviderExists() -and $present.Count -eq 0) 'read-only BFE lookup by key'
        } finally { $e.Close() }
    } catch { Add-Check 'WFP read-only lookup' $false $_.Exception.Message }
} else { Write-Host '  [skip] WFP lookup needs an elevated shell (dynamic objects vanish with their process anyway)' -ForegroundColor DarkGray }

$coder = Get-LocalUser -Name 'blarai-coder' -ErrorAction SilentlyContinue
Write-Host ("  [info] blarai-coder account present: {0} (this spike never touches it)" -f [bool]$coder)

$failed = @($results | Where-Object { -not $_.pass })
Write-Host ''
if (-not $sid) { Write-Host 'RESULT: INCOMPLETE - the account-level checks above are valid, but ACL/right/profile/process checks could not be run (no SID known).' -ForegroundColor Yellow; exit 2 }
if ($failed.Count -eq 0) { Write-Host ("RESULT: CLEAN - all {0} checks passed." -f $results.Count) -ForegroundColor Green; exit 0 }
Write-Host ("RESULT: TRACES REMAIN - {0} of {1} checks failed: {2}" -f $failed.Count, $results.Count, (($failed | ForEach-Object { $_.name }) -join '; ')) -ForegroundColor Red
exit 1
