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
    4 tree      delete C:\blarai-spike (exact path, refused if it is a reparse point)
    5 right     remove SeBatchLogonRight for the spike SID (secedit export/modify/import; other holders kept)
    6 profile   remove the account's profile registration and C:\Users\blarai-spike (exact path)
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
    if (Test-Path -LiteralPath $script:SpikeStatePath) { return (Get-Content -LiteralPath $script:SpikeStatePath -Raw | ConvertFrom-Json) }
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

function Set-BatchLogonRight {
    param([Parameter(Mandatory)][string]$Sid, [ValidateSet('add','remove')][string]$Mode = 'remove')
    $stamp = [guid]::NewGuid().ToString('N')
    $exportInf = Join-Path $env:TEMP "spike-ur-exp-$stamp.inf"; $importInf = Join-Path $env:TEMP "spike-ur-imp-$stamp.inf"; $db = Join-Path $env:TEMP "spike-ur-$stamp.sdb"
    try {
        & secedit /export /cfg $exportInf /areas USER_RIGHTS *> $null
        $lines = if (Test-Path $exportInf) { Get-Content $exportInf } else { @() }
        $newLine = Resolve-PrivilegeLine -ExportLines $lines -Privilege 'SeBatchLogonRight' -Sid $Sid -Mode $Mode
        if ($null -eq $newLine) { Write-Ok "SeBatchLogonRight already absent for the spike SID (idempotent)"; return }
        Set-Content -Path $importInf -Encoding Unicode -Value @('[Unicode]', 'Unicode=yes', '[Version]', 'signature="$CHICAGO$"', 'Revision=1', '[Privilege Rights]', $newLine)
        & secedit /configure /db $db /cfg $importInf /areas USER_RIGHTS *> $null
        if ($LASTEXITCODE -ne 0) { throw "secedit /configure failed (exit $LASTEXITCODE)" }
        Write-Ok 'revoked SeBatchLogonRight for the spike SID'
    } finally { foreach ($f in @($exportInf, $importInf, $db)) { Remove-Item $f -ErrorAction SilentlyContinue } }
}

function Remove-SidAces([string]$Path, [string]$Sid) {
    if (-not (Test-Path -LiteralPath $Path)) { Write-Skip "path absent: $Path"; return }
    # Only this SID's ACEs: /remove:g (granted) and /remove:d (denied). No /reset, no /T needed (inherited copies are
    # removed by propagation; verify-cleanup scans the tree to prove it).
    & icacls.exe $Path /remove:g "*$Sid" | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "icacls /remove:g failed on $Path (exit $LASTEXITCODE)" }
    & icacls.exe $Path /remove:d "*$Sid" | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "icacls /remove:d failed on $Path (exit $LASTEXITCODE)" }
    Write-Ok "removed the spike SID's ACEs from $Path"
}

function Remove-SafeTree([string]$Path) {
    if (-not (Test-Path -LiteralPath $Path)) { Write-Skip "absent: $Path"; return }
    $item = Get-Item -LiteralPath $Path -Force
    $reparse = [bool]($item.Attributes -band [IO.FileAttributes]::ReparsePoint)
    if (-not (Test-SafeDeletePath -Path $Path -IsReparsePoint $reparse)) { throw "refusing to delete '$Path' (not one of the two exact spike directories, or a reparse point)" }
    Remove-Item -LiteralPath $Path -Recurse -Force
    if (Test-Path -LiteralPath $Path) { throw "could not fully delete $Path" }
    Write-Ok "deleted $Path"
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
    Chk 'description marker is the account guard' ($script:SpikeDescMarker -match '#1689')
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
    Write-Host '4. TREE'; Write-Host ("   DELETE {0}  (exists: {1})" -f $script:SpikeRoot, (Test-Path $script:SpikeRoot))
    Write-Host '5. RIGHT'
    $stamp = [guid]::NewGuid().ToString('N'); $inf = Join-Path $env:TEMP "spike-dry-$stamp.inf"
    try { & secedit /export /cfg $inf /areas USER_RIGHTS *> $null; $holders = Get-PrivilegeHolders (Get-Content $inf) 'SeBatchLogonRight'; $has = ($c.Sid -and ($holders -contains "*$($c.Sid)")); Write-Host ("   REMOVE SeBatchLogonRight for the spike SID  (currently held by it: {0}; other holders kept: {1})" -f [bool]$has, (@($holders | Where-Object { $_ -ne "*$($c.Sid)" }).Count)) } catch { Write-Host "   (could not read user rights: $($_.Exception.Message))" } finally { Remove-Item $inf -ErrorAction SilentlyContinue }
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
    Write-Step '1/8 task'
    $t = Get-ScheduledTask -TaskPath $script:SpikeTaskPath -TaskName $script:SpikeTaskName -ErrorAction SilentlyContinue
    if ($t) {
        if ($t.State -eq 'Running') { Stop-ScheduledTask -TaskPath $script:SpikeTaskPath -TaskName $script:SpikeTaskName; Start-Sleep -Seconds 2 }
        Unregister-ScheduledTask -TaskPath $script:SpikeTaskPath -TaskName $script:SpikeTaskName -Confirm:$false
        Write-Ok "unregistered $($script:SpikeTaskPath)$($script:SpikeTaskName)"
    } else { Write-Skip 'task not present' }
    Write-Step '2/8 processes'
    $procs = Get-SidOwnedProcesses $c.Sid
    if ($procs.Count) { foreach ($p in $procs) { Stop-Process -Id $p.ProcessId -Force; Write-Ok "stopped pid $($p.ProcessId) $($p.Name)" }; Start-Sleep -Seconds 1 } else { Write-Skip 'none' }
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
