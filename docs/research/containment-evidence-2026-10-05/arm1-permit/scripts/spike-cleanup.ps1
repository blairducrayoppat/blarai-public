#requires -Version 5.1
<#
.SYNOPSIS
  #1689 spike: remove everything spike-provision.ps1 created. Run spike-verify-cleanup.ps1 afterwards.

.DESCRIPTION
  Modes (exactly one): -SelfTest (pure, no change) | -DryRun (prints exactly what -Apply would remove; changes
  nothing) | -Apply (elevated; stops at the first error; safe to re-run, every step is idempotent).
  Order matters: the account's SID is needed to remove its ACEs, so the account is deleted LAST.
    1 task      stop any running instance, unregister \BlarAI\BlarAI-Spike-Model (and only that task)
    2 processes any process still owned by the spike SID is stopped
    3 ACEs      remove ONLY the ACEs for the spike SID (icacls /remove:g and /remove:d on that SID; never /reset,
                never a rewrite) from the venv, the venv's base interpreter and the model dir
    4 tree      delete C:\blarai-spike (exact path; refused if it is a reparse point; NEVER Remove-Item -Recurse: the tree is
                walked without following links, every junction/symlink is removed as a link only, a hard link with a name
                outside the tree stops the run)
    5 right     remove SeBatchLogonRight for the spike SID (secedit export/modify/import; other holders kept)
    6 profile   remove the account's profile registration and C:\Users\blarai-spike (exact path, same link-safe delete)
    7 account   delete the local user blarai-spike (refused unless its description is this spike's marker)
    8 state     spike-state.json is renamed to spike-state.cleaned.json (keeps the SID so verify can still search)
  A WFP block, if one is somehow still present, is dynamic and disappears with its process; verify checks for it.
#>
[CmdletBinding()]
param([switch]$SelfTest, [switch]$DryRun, [switch]$Apply)
$ErrorActionPreference = 'Stop'
. "$PSScriptRoot\spike-lib.ps1"

function Write-Step([string]$m) { Write-Host "[spike-cleanup] $m" -ForegroundColor Cyan }
function Write-Ok([string]$m)   { Write-Host "  [ok] $m" -ForegroundColor Green }
function Write-Skip([string]$m) { Write-Host "  [skip] $m" -ForegroundColor DarkGray }
function Test-IsElevated { ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator) }

function Read-SpikeState {
    # The live state file first; else the cleaned copy a previous -Apply left for verify (SID and paths, no secret), so a
    # re-run after the account is gone still knows which SID's traces to remove (the verify reads the same files).
    foreach ($p in @($script:SpikeStatePath, $script:SpikeCleanedPath)) {
        if (Test-Path -LiteralPath $p) { return (Get-Content -LiteralPath $p -Raw | ConvertFrom-Json) }
    }
    return $null
}

function Resolve-CleanupContext {
    $user = Get-LocalUser -Name $script:SpikeUser -ErrorAction SilentlyContinue
    $state = Read-SpikeState
    $sid = $null
    if ($user) { $sid = $user.SID.Value } elseif ($state) { $sid = [string]$state.spike_sid }
    $venv = if ($state) { [string]$state.venv } else { $script:SpikeVenv }
    $model = if ($state) { [string]$state.model_dir } else { $script:SpikeModelDir }
    $base = if ($state) { [string]$state.venv_base_home } else { $null }
    if (-not $base) { $cfg = Join-Path $venv 'pyvenv.cfg'; if (Test-Path -LiteralPath $cfg) { $base = Get-VenvBaseHome (Get-Content -LiteralPath $cfg) } }
    $opSid = if ($state) { [string]$state.operator_sid } else { ([Security.Principal.WindowsIdentity]::GetCurrent()).User.Value }
    $plan = $null; $paths = @()
    if ($sid) {
        $plan = Get-SpikeAcePlan -SpikeSid $sid -OperatorSid $opSid -Venv $venv -VenvBaseHome $base -ModelDir $model
        $paths = Get-AceRemovalPaths -Plan $plan
    }
    [pscustomobject]@{ User = $user; State = $state; Sid = $sid; Paths = $paths; Venv = $venv; Model = $model; Base = $base }
}

function Get-SidOwnedProcesses([string]$Sid) {
    if (-not $Sid) { return @() }
    $hits = @()
    foreach ($p in (Get-CimInstance Win32_Process)) {
        try { $o = Invoke-CimMethod -InputObject $p -MethodName GetOwnerSid -ErrorAction Stop; if ($o.Sid -eq $Sid) { $hits += $p } } catch { }
    }
    return @($hits)
}

function Stop-SidProcessesConfirmed {
    # Stop every process owned by the SID and CONFIRM zero remain (bounded wait). Refuses to proceed otherwise: the tree
    # walk must not race anything still running as the account. No SID known = nothing to confirm.
    param([string]$Sid, [int]$WaitSeconds = 20)
    if (-not $Sid) { Write-Skip 'no SID known: no process check possible'; return }
    $deadline = (Get-Date).AddSeconds($WaitSeconds); $stopped = 0
    do {
        $procs = @(Get-SidOwnedProcesses $Sid)
        foreach ($p in $procs) { try { Stop-Process -Id $p.ProcessId -Force -ErrorAction Stop; $stopped++; Write-Ok "stopped pid $($p.ProcessId) $($p.Name)" } catch { } }
        if ($procs.Count) { Start-Sleep -Milliseconds 500 }
    } while ($procs.Count -and (Get-Date) -lt $deadline)
    $left = @(Get-SidOwnedProcesses $Sid)
    if ($left.Count) { throw ("processes owned by the spike SID are still running after ${WaitSeconds}s ({0}): refusing to touch its trees" -f (($left | ForEach-Object { "$($_.ProcessId):$($_.Name)" }) -join ', ')) }
    Write-Ok "no process owned by the spike SID ($stopped stopped)"
}

function Set-BatchLogonRight {
    param([Parameter(Mandatory)][string]$Sid, [ValidateSet('add','remove')][string]$Mode = 'remove')
    # Files go in a private (protected-DACL) directory, never loose in %TEMP% (see New-PrivateTempDir).
    $tmp = New-PrivateTempDir
    $exportInf = Join-Path $tmp 'exp.inf'; $importInf = Join-Path $tmp 'imp.inf'; $db = Join-Path $tmp 'ur.sdb'
    try {
        & secedit /export /cfg $exportInf /areas USER_RIGHTS *> $null
        $lines = if (Test-Path -LiteralPath $exportInf) { Get-Content -LiteralPath $exportInf } else { @() }
        $newLine = Resolve-PrivilegeLine -ExportLines $lines -Privilege 'SeBatchLogonRight' -Sid $Sid -Mode $Mode -Name $script:SpikeUser
        if ($null -eq $newLine) { Write-Ok "SeBatchLogonRight already absent for the spike SID (idempotent)"; return }
        Set-Content -LiteralPath $importInf -Encoding Unicode -Value @('[Unicode]', 'Unicode=yes', '[Version]', 'signature="$CHICAGO$"', 'Revision=1', '[Privilege Rights]', $newLine)
        & secedit /configure /db $db /cfg $importInf /areas USER_RIGHTS *> $null
        if ($LASTEXITCODE -ne 0) { throw "secedit /configure failed (exit $LASTEXITCODE)" }
        Write-Ok 'revoked SeBatchLogonRight for the spike SID'
    } finally { Remove-PrivateTempDir $tmp }
}

function Remove-SidAces([string]$Path, [string]$Sid) {
    if (-not (Test-PathExistsNoFollow $Path)) { Write-Skip "path absent: $Path"; return }
    Assert-AclTargetPlain $Path   # no wildcard characters, never a junction/symlink (icacls would act on its target)
    # Only this SID's ACEs: /remove:g (granted) and /remove:d (denied). No /reset, no /T needed (inherited copies are
    # removed by propagation; verify-cleanup scans the tree to prove it).
    $out = & icacls.exe $Path /remove:g "*$Sid" 2>&1
    if ($LASTEXITCODE -eq 1332) {
        # ERROR_NONE_MAPPED: the account is already deleted and icacls refuses a SID it cannot map, even in *SID form.
        # The .NET ACL API purges by SecurityIdentifier without resolving it: same effect (explicit allow + deny rules
        # for this SID only; inherited copies go with their parent), no /reset.
        $sec = Get-DirSecurity $Path
        $before = @($sec.GetAccessRules($true, $false, [Security.Principal.SecurityIdentifier]) | Where-Object { $_.IdentityReference.Value -eq $Sid }).Count
        if ($before -gt 0) { [void]$sec.PurgeAccessRules([Security.Principal.SecurityIdentifier]$Sid); Set-DirSecurity $Path $sec }
        Write-Ok ("removed the spike SID's ACEs from {0} via .NET ({1} explicit rule(s); icacls cannot map a deleted SID)" -f $Path, $before)
        return
    }
    if ($LASTEXITCODE -ne 0) { throw "icacls /remove:g failed on $Path (exit $LASTEXITCODE): $out" }
    & icacls.exe $Path /remove:d "*$Sid" | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "icacls /remove:d failed on $Path (exit $LASTEXITCODE)" }
    Write-Ok "removed the spike SID's ACEs from $Path"
}

function Remove-SafeTree([string]$Path) {
    if (-not (Test-PathExistsNoFollow $Path)) { Write-Skip "absent: $Path"; return }
    $reparse = Test-IsReparsePoint $Path
    if (-not (Test-SafeDeletePath -Path $Path -IsReparsePoint $reparse)) { throw "refusing to delete '$Path' (not one of the two exact spike directories, or a reparse point)" }
    # The spike account could write inside these trees: a planted junction/symlink/hard link must never be followed.
    $rep = Get-TreeLinkReport -Root $Path
    foreach ($l in $rep.Links) { Write-Host ("  [link] will remove the link itself, not its target: {0}" -f $l.Path) -ForegroundColor Yellow }
    Remove-TreeNoFollow -Root $Path
    Write-Ok "deleted $Path ($($rep.Links.Count) link(s) removed as links)"
}

function Invoke-SelfTest {
    $script:f = 0
    function Chk([string]$n, [bool]$c) { if ($c) { Write-Host "  [PASS] $n" -ForegroundColor Green } else { Write-Host "  [FAIL] $n" -ForegroundColor Red; $script:f++ } }
    $spike = 'S-1-5-21-1111111111-2222222222-3333333333-1001'; $op = 'S-1-5-21-1111111111-2222222222-3333333333-1000'
    $plan = Get-SpikeAcePlan -SpikeSid $spike -OperatorSid $op -VenvBaseHome 'C:\Users\_OPERATOR_\AppData\Local\Programs\Python\Python311'
    $paths = Get-AceRemovalPaths -Plan $plan
    Chk 'removal covers the venv, the base interpreter and the model dir, exactly' (($paths | Sort-Object) -join '|' -eq ((@($script:SpikeVenv, 'C:\Users\_OPERATOR_\AppData\Local\Programs\Python\Python311', $script:SpikeModelDir) | Sort-Object) -join '|'))
    Chk 'removal never lists the spike root (deleted wholesale) or an operator secret path' ((@($paths | Where-Object { $_ -like 'C:\blarai-spike*' }).Count -eq 0) -and (@($paths | Where-Object { $_ -in (Get-SpikeSecretPaths) }).Count -eq 0))
    Chk 'every removal path corresponds to a spike ACE the provision plan adds' (@($paths | Where-Object { $p = $_; -not (@($plan | Where-Object { $_.Principal -eq 'spike' -and $_.Path -eq $p }).Count) }).Count -eq 0)
    Chk 'safe-delete: the spike root is allowed' (Test-SafeDeletePath 'C:\blarai-spike')
    Chk 'safe-delete: the spike profile dir is allowed (any case, trailing slash)' (Test-SafeDeletePath 'c:\users\BLARAI-SPIKE\')
    Chk 'safe-delete refuses the operator profile, C:\, a child, a lookalike' (-not ((Test-SafeDeletePath 'C:\Users\_OPERATOR_') -or (Test-SafeDeletePath 'C:\') -or (Test-SafeDeletePath 'C:\blarai-spike\work') -or (Test-SafeDeletePath 'C:\blarai-spike2') -or (Test-SafeDeletePath 'C:\Users\blarai-coder')))
    Chk 'safe-delete refuses a reparse point even at the exact path' (-not (Test-SafeDeletePath 'C:\blarai-spike' $true))
    Chk 'privilege removal keeps other holders' ((Resolve-PrivilegeLine @("SeBatchLogonRight = *S-1-5-32-544,*$spike") 'SeBatchLogonRight' $spike 'remove') -eq 'SeBatchLogonRight = *S-1-5-32-544')
    Chk 'privilege removal matches the holder written by NAME (the account still exists at step 5)' ((Resolve-PrivilegeLine @("SeBatchLogonRight = blarai-coder,*S-1-5-32-544,blarai-spike") 'SeBatchLogonRight' $spike 'remove' -Name 'blarai-spike') -eq 'SeBatchLogonRight = blarai-coder,*S-1-5-32-544')
    Chk 'privilege removal by name is case-insensitive and never touches another name' ((Resolve-PrivilegeLine @("SeBatchLogonRight = BLARAI-SPIKE,blarai-coder") 'SeBatchLogonRight' $spike 'remove' -Name 'blarai-spike') -eq 'SeBatchLogonRight = blarai-coder')
    Chk 'without -Name a holder written by name is NOT matched (the pre-fix behaviour, kept explicit)' ($null -eq (Resolve-PrivilegeLine @("SeBatchLogonRight = blarai-spike") 'SeBatchLogonRight' $spike 'remove'))
    Chk 'description marker is the account guard' ($script:SpikeDescMarker -match '#1689')
    # --- link-safe delete, driven against REAL junctions / hard links / symlinks in a temp "spike root" ---------------
    $base = Join-Path ([IO.Path]::GetTempPath()) ('spike-linktest-' + [guid]::NewGuid().ToString('N'))
    try {
        $victim = Join-Path $base 'victim'; New-Item -ItemType Directory -Path $victim -Force | Out-Null
        Set-Content -LiteralPath (Join-Path $victim 'sentinel.txt') -Value 'KEEP ME'
        Set-Content -LiteralPath (Join-Path $base 'outside.txt') -Value 'OUTSIDE'
        $sentinel = Join-Path $victim 'sentinel.txt'
        # 1 junction inside the tree pointing at the victim directory
        $root = Join-Path $base 'root1'; New-Item -ItemType Directory -Path (Join-Path $root 'work\tmp') -Force | Out-Null
        Set-Content -LiteralPath (Join-Path $root 'work\a.txt') -Value 'a'
        New-Item -ItemType Junction -Path (Join-Path $root 'work\j') -Target $victim | Out-Null
        Chk 'link test setup: the junction really reaches the sentinel' (Test-Path -LiteralPath (Join-Path $root 'work\j\sentinel.txt'))
        $rep = Get-TreeLinkReport -Root $root
        Chk 'link report: finds the junction, does not enter it' (($rep.Links.Count -eq 1) -and ($rep.Links[0].IsDirectory) -and ($rep.Refusals.Count -eq 0))
        Remove-TreeNoFollow -Root $root
        Chk 'junction: the tree is gone' (-not (Test-PathExistsNoFollow $root))
        Chk 'junction: the sentinel behind the link SURVIVED' ((Test-Path -LiteralPath $sentinel) -and ((Get-Content -LiteralPath $sentinel -Raw).Trim() -eq 'KEEP ME'))
        # 2 hard link whose other name is outside the tree: refuse, delete nothing
        $root = Join-Path $base 'root2'; New-Item -ItemType Directory -Path $root -Force | Out-Null
        Set-Content -LiteralPath (Join-Path $root 'plain.txt') -Value 'p'
        $hl = $true; try { New-Item -ItemType HardLink -Path (Join-Path $root 'h.txt') -Target (Join-Path $base 'outside.txt') | Out-Null } catch { $hl = $false }
        if ($hl) {
            $refused = $false; try { Remove-TreeNoFollow -Root $root } catch { $refused = $true }
            Chk 'hard link to a file outside the tree: delete is REFUSED' $refused
            Chk 'hard link: nothing was deleted and the outside file is intact' ((Test-Path -LiteralPath (Join-Path $root 'plain.txt')) -and ((Get-Content -LiteralPath (Join-Path $base 'outside.txt') -Raw).Trim() -eq 'OUTSIDE'))
            # a hard link whose every name is inside the tree is deleted normally
            Remove-Item -LiteralPath (Join-Path $root 'h.txt') -Force
            New-Item -ItemType HardLink -Path (Join-Path $root 'h2.txt') -Target (Join-Path $root 'plain.txt') | Out-Null
            $ok = $true; try { Remove-TreeNoFollow -Root $root } catch { $ok = $false }
            Chk 'hard link wholly inside the tree: deleted, outside file intact' ($ok -and -not (Test-PathExistsNoFollow $root) -and (Test-Path -LiteralPath (Join-Path $base 'outside.txt')))
        } else { Write-Host '  [SKIP] hard links cannot be created here' -ForegroundColor Yellow }
        # 3 directory and file symlinks (need the symlink privilege or developer mode)
        $root = Join-Path $base 'root3'; New-Item -ItemType Directory -Path $root -Force | Out-Null
        $sl = $true; try { New-Item -ItemType SymbolicLink -Path (Join-Path $root 'sd') -Target $victim | Out-Null; New-Item -ItemType SymbolicLink -Path (Join-Path $root 'sf.txt') -Target $sentinel | Out-Null } catch { $sl = $false }
        if ($sl) {
            Remove-TreeNoFollow -Root $root
            Chk 'directory + file symlinks: tree gone, sentinel SURVIVED' ((-not (Test-PathExistsNoFollow $root)) -and (Test-Path -LiteralPath $sentinel))
        } else { Write-Host '  [SKIP] symlinks cannot be created here (no privilege / developer mode); junction and hard-link cases above still ran' -ForegroundColor Yellow }
        # 3b TOCTOU: a directory swapped for a junction AFTER enumeration, BEFORE the delete (test hook between the two steps)
        $root = Join-Path $base 'root4'; New-Item -ItemType Directory -Path (Join-Path $root 'work\inner') -Force | Out-Null
        Set-Content -LiteralPath (Join-Path $root 'work\inner\x.txt') -Value 'x'
        $swapTarget = Join-Path $root 'work\inner'
        $script:SpikeToctouHook = { param($p) if ($p -eq $swapTarget -and (Get-EntryKind $p) -eq 'dir') { Remove-Item -LiteralPath $p -Recurse -Force; New-Item -ItemType Junction -Path $p -Target $victim | Out-Null } }.GetNewClosure()
        $failed = $false; try { Remove-TreeNoFollow -Root $root } catch { $failed = $true }
        $script:SpikeToctouHook = $null
        Chk 'TOCTOU: a directory swapped for a junction between enumerate and delete is a FAILURE, not followed' $failed
        Chk 'TOCTOU: the sentinel behind the swapped-in junction SURVIVED' ((Test-Path -LiteralPath $sentinel) -and ((Get-Content -LiteralPath $sentinel -Raw).Trim() -eq 'KEEP ME'))
        if (Test-PathExistsNoFollow (Join-Path $root 'work\inner')) { [IO.Directory]::Delete((Join-Path $root 'work\inner'), $false) }
        # 4 a root that is itself a junction is refused outright
        $jr = Join-Path $base 'rootjunction'; New-Item -ItemType Junction -Path $jr -Target $victim | Out-Null
        $refused = $false; try { Remove-TreeNoFollow -Root $jr } catch { $refused = $true }
        Chk 'a root that is itself a junction is refused; its target is untouched' ($refused -and (Test-Path -LiteralPath $sentinel))
        [IO.Directory]::Delete($jr, $false)
        # 5 ACL-target guard and the private temp dir
        $w = $false; try { Assert-AclTargetPlain 'C:\Users\*' } catch { $w = $true }
        Chk 'icacls target guard refuses wildcard characters' $w
        $j2 = Join-Path $base 'aclj'; New-Item -ItemType Junction -Path $j2 -Target $victim | Out-Null
        $rj = $false; try { Assert-AclTargetPlain $j2 } catch { $rj = $true }
        Chk 'icacls target guard refuses a junction' $rj
        [IO.Directory]::Delete($j2, $false)
        $pt = New-PrivateTempDir
        Chk 'private temp dir exists and its DACL is protected' ((Test-Path -LiteralPath $pt) -and (Get-DirSecurity $pt).AreAccessRulesProtected)
        Remove-PrivateTempDir $pt
        Chk 'private temp dir is removed' (-not (Test-PathExistsNoFollow $pt))
    } finally {
        if (Test-PathExistsNoFollow $base) { try { Remove-TreeNoFollow -Root $base } catch { Write-Host "  (temp cleanup of $base failed: $($_.Exception.Message))" -ForegroundColor Yellow } }
    }
    Write-Host ("cleanup selftest: {0}" -f $(if ($script:f -eq 0) { 'all passed' } else { "$($script:f) FAILED" })) -ForegroundColor $(if ($script:f -eq 0) { 'Green' } else { 'Red' })
    return $(if ($script:f -eq 0) { 0 } else { 1 })
}

function Invoke-DryRun {
    Write-Host '== DRY RUN: nothing below has been done; nothing will be changed by this command ==' -ForegroundColor Yellow
    Write-Host ("machine clock: {0}" -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss K'))
    $c = Resolve-CleanupContext
    Write-Host ("spike SID: {0}  (account present: {1}; state file present: {2})" -f $(if ($c.Sid) { $c.Sid } else { '<none known>' }), [bool]$c.User, [bool]$c.State)
    $t = Get-ScheduledTask -TaskPath $script:SpikeTaskPath -TaskName $script:SpikeTaskName -ErrorAction SilentlyContinue
    Write-Host '1. TASK'; Write-Host ("   {0} {1}{2}" -f $(if ($t) { 'UNREGISTER' } else { 'absent:' }), $script:SpikeTaskPath, $script:SpikeTaskName)
    Write-Host '2. PROCESSES'
    $procs = Get-SidOwnedProcesses $c.Sid
    if ($procs.Count) { $procs | ForEach-Object { Write-Host "   STOP pid $($_.ProcessId) $($_.Name)" } } else { Write-Host '   none owned by the spike SID' }
    Write-Host '3. ACEs (only the spike SID is removed: icacls /remove:g and /remove:d; never /reset)'
    if (-not $c.Sid) { Write-Host '   no SID known: cannot remove ACEs (verify will report this)' -ForegroundColor Yellow }
    foreach ($p in $c.Paths) {
        $has = 'unknown'
        if ($c.Sid -and (Test-Path -LiteralPath $p)) { $out = & icacls.exe $p 2>$null; $has = if (@(Find-SidInIcaclsText $out $c.Sid $script:SpikeUser).Count) { 'ACE present' } else { 'no ACE at the top level' } }
        Write-Host ("   REMOVE spike-SID ACEs from {0}  [{1}]" -f $p, $has)
    }
    Write-Host '4. TREE (link-safe: walked without following links; links removed as links; a hard link to a name outside stops the run)'
    Write-Host ("   DELETE {0}  (exists: {1})" -f $script:SpikeRoot, (Test-PathExistsNoFollow $script:SpikeRoot))
    foreach ($tr in @($script:SpikeRoot, $script:SpikeProfileDir)) {
        if ((Test-PathExistsNoFollow $tr) -and -not (Test-IsReparsePoint $tr)) {
            $lr = Get-TreeLinkReport -Root $tr
            foreach ($l in $lr.Links) { Write-Host ("   LINK inside {0}: {1} (would be removed as a link only)" -f $tr, $l.Path) -ForegroundColor Yellow }
            foreach ($rf in $lr.Refusals) { Write-Host ("   WOULD REFUSE: {0}" -f $rf) -ForegroundColor Red }
        }
    }
    Write-Host '5. RIGHT'
    $dryTmp = New-PrivateTempDir; $inf = Join-Path $dryTmp 'dry.inf'
    try { & secedit /export /cfg $inf /areas USER_RIGHTS *> $null; $holders = Get-PrivilegeHolders (Get-Content -LiteralPath $inf) 'SeBatchLogonRight'; $has = ($c.Sid -and ($holders -contains "*$($c.Sid)")); Write-Host ("   REMOVE SeBatchLogonRight for the spike SID  (currently held by it: {0}; other holders kept: {1})" -f [bool]$has, (@($holders | Where-Object { $_ -ne "*$($c.Sid)" }).Count)) } catch { Write-Host "   (could not read user rights: $($_.Exception.Message))" } finally { Remove-PrivateTempDir $dryTmp }
    Write-Host '6. PROFILE'
    $prof = if ($c.Sid) { Get-CimInstance Win32_UserProfile -Filter "SID='$($c.Sid)'" -ErrorAction SilentlyContinue } else { $null }
    Write-Host ("   REMOVE profile registration (present: {0}) and DELETE {1} (exists: {2})" -f [bool]$prof, $script:SpikeProfileDir, (Test-Path $script:SpikeProfileDir))
    Write-Host '7. ACCOUNT'
    if ($c.User) { Write-Host ("   DELETE local user '{0}'  {1}" -f $script:SpikeUser, $(if ($c.User.Description -eq $script:SpikeDescMarker) { '(description marker matches: this spike''s account)' } else { '** description does NOT match: -Apply would REFUSE **' })) } else { Write-Host '   absent' }
    Write-Host '8. STATE'; Write-Host ("   RENAME {0} -> {1}" -f $script:SpikeStatePath, $script:SpikeCleanedPath)
    Write-Host ''
    Write-Host 'NOT touched: the \BlarAI\ task folder, blarai-coder and its ACEs/task/right, the operator account, any other firewall/WFP object.' -ForegroundColor Green
    Write-Host 'DRY RUN complete. Nothing was changed.' -ForegroundColor Green
    return 0
}

function Invoke-Apply {
    if (-not (Test-IsElevated)) { throw 'spike-cleanup.ps1 -Apply must run ELEVATED.' }
    $c = Resolve-CleanupContext
    if ($c.User -and $c.User.Description -ne $script:SpikeDescMarker) { throw "local user '$($script:SpikeUser)' exists but its description is not this spike's marker: refusing to touch it" }
    if ($c.Sid -and -not (Test-AccountDomainSid $c.Sid)) { throw "unexpected SID shape: $($c.Sid)" }
    Write-Step '0/8 quiesce the account (nothing running as it may race the walk)'
    if ($c.User) {
        if ($c.User.Enabled) { Disable-LocalUser -Name $script:SpikeUser; Write-Ok "disabled local user '$($script:SpikeUser)' (no new logon)" } else { Write-Skip 'account already disabled' }
    } else { Write-Skip 'account not present' }
    $t0 = Get-ScheduledTask -TaskPath $script:SpikeTaskPath -TaskName $script:SpikeTaskName -ErrorAction SilentlyContinue
    if ($t0) {
        if ($t0.State -eq 'Running') { Stop-ScheduledTask -TaskPath $script:SpikeTaskPath -TaskName $script:SpikeTaskName }
        if ($t0.State -ne 'Disabled') { Disable-ScheduledTask -TaskPath $script:SpikeTaskPath -TaskName $script:SpikeTaskName | Out-Null; Write-Ok 'disabled the scheduled task' }
    } else { Write-Skip 'task not present' }
    Stop-SidProcessesConfirmed -Sid $c.Sid
    Write-Step '1/8 task'
    $t = Get-ScheduledTask -TaskPath $script:SpikeTaskPath -TaskName $script:SpikeTaskName -ErrorAction SilentlyContinue
    if ($t) {
        if ($t.State -eq 'Running') { Stop-ScheduledTask -TaskPath $script:SpikeTaskPath -TaskName $script:SpikeTaskName; Start-Sleep -Seconds 2 }
        Unregister-ScheduledTask -TaskPath $script:SpikeTaskPath -TaskName $script:SpikeTaskName -Confirm:$false
        Write-Ok "unregistered $($script:SpikeTaskPath)$($script:SpikeTaskName)"
    } else { Write-Skip 'task not present' }
    Write-Step '2/8 processes'
    Stop-SidProcessesConfirmed -Sid $c.Sid   # again, in case the task started something while it was being unregistered
    Write-Step '3/8 ACEs (spike SID only)'
    if ($c.Sid) { foreach ($p in $c.Paths) { Remove-SidAces $p $c.Sid } } else { Write-Skip 'no SID known (account and state both absent): nothing to remove; verify will say so' }
    Write-Step '4/8 tree'
    Remove-SafeTree $script:SpikeRoot
    Write-Step '5/8 batch-logon right'
    if ($c.Sid) { Set-BatchLogonRight -Sid $c.Sid -Mode remove } else { Write-Skip 'no SID known' }
    Write-Step '6/8 profile'
    if ($c.Sid) {
        $prof = Get-CimInstance Win32_UserProfile -Filter "SID='$($c.Sid)'" -ErrorAction SilentlyContinue
        if ($prof) { if ($prof.Loaded) { throw 'the spike profile is still loaded (a process is running as the account); stop it and re-run' }; $prof | Remove-CimInstance; Write-Ok 'removed the profile registration' } else { Write-Skip 'no profile registration' }
    }
    Remove-SafeTree $script:SpikeProfileDir
    Write-Step '7/8 account'
    if ($c.User) { Remove-LocalUser -Name $script:SpikeUser; Write-Ok "deleted local user '$($script:SpikeUser)'" } else { Write-Skip 'account not present' }
    Write-Step '8/8 state'
    if (Test-Path -LiteralPath $script:SpikeStatePath) { Move-Item -LiteralPath $script:SpikeStatePath -Destination $script:SpikeCleanedPath -Force; Write-Ok "state kept as $($script:SpikeCleanedPath) (SID only, for verify)" } else { Write-Skip 'no state file' }
    Write-Host 'CLEANUP complete. Next: spike-verify-cleanup.ps1' -ForegroundColor Green
    return 0
}

$modes = @($SelfTest.IsPresent, $DryRun.IsPresent, $Apply.IsPresent) | Where-Object { $_ }
if (@($modes).Count -ne 1) { Write-Host 'usage: spike-cleanup.ps1 -SelfTest | -DryRun | -Apply   (exactly one mode; nothing happens without one)' -ForegroundColor Yellow; exit 2 }
try {
    if ($SelfTest) { exit (Invoke-SelfTest) }
    if ($DryRun)   { exit (Invoke-DryRun) }
    if ($Apply)    { exit (Invoke-Apply) }
} catch {
    Write-Host "STOPPED: $($_.Exception.Message)" -ForegroundColor Red
    Write-Host 'Nothing further was done. Re-running -Apply is safe.' -ForegroundColor Red
    exit 1
}
