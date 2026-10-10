#requires -Version 5.1
<#
.SYNOPSIS
  #1689 spike: provision the THROWAWAY account `blarai-spike` and everything the confined-inference feasibility
  spike needs. Modelled on agentic-setup\scripts\provision-coder-account.ps1 + register-coder-leg-task.ps1.

.DESCRIPTION
  Modes (exactly one):
    -SelfTest  pure functions only (ACE planning + safety invariants, privilege-line logic, schema, password shape).
               Changes nothing, needs no elevation.
    -DryRun    resolves what it can (operator SID, venv base interpreter, existing state) READ-ONLY and prints
               exactly what -Apply would change: account, group membership, user right, directories, every ACE with
               its path, the files copied into bin, the scheduled-task definition. Changes nothing.
    -Apply     does it. Elevated. Idempotent. Stops at the first error and says so (re-running is safe).
  No mode -> usage + exit 2 (fail closed; nothing happens by default).

  WHAT -Apply CHANGES (rollback = spike-cleanup.ps1)
    1 account    local user blarai-spike, member of Users ONLY, 24-char random password held only in the scheduled
                 task's credential vault (LSA secrets). It is never printed, logged or written to a file.
    2 right      SeBatchLogonRight ('Log on as a batch job') granted to its SID via secedit (other holders kept).
    3 tree       C:\blarai-spike\{bin,work,results}; root DACL protected: operator + SYSTEM + Administrators full,
                 the spike account traverse-only on the root; NOT Authenticated Users.
    4 ACEs       READ+EXECUTE for the spike SID on the 2026.4 venv, its base interpreter and the 4B model dir;
                 Modify on work + results only. NO ACE on any operator secret path (spike-run-test proves denial).
    5 files      spike-run-test.ps1, spike_model.py, spike-config.json copied into C:\blarai-spike\bin (the account
                 can read them but not change them).
    6 task       \BlarAI\BlarAI-Spike-Model: as blarai-spike, password logon, RunLevel Limited, NO trigger.
    7 state      spike-state.json (SID, ACE rows, timestamps; no secret) beside these scripts, for cleanup/verify.
  No firewall or WFP object is created here; the WFP block is a dynamic session added by spike-wfp.ps1 -TestB.
#>
[CmdletBinding()]
param(
    [switch]$SelfTest,
    [switch]$DryRun,
    [switch]$Apply,
    [switch]$ForceNewPassword,
    [string]$Venv,
    [string]$ModelDir
)
$ErrorActionPreference = 'Stop'
. "$PSScriptRoot\spike-lib.ps1"
if (-not $Venv) { $Venv = $script:SpikeVenv }
if (-not $ModelDir) { $ModelDir = $script:SpikeModelDir }

function Write-Step([string]$m) { Write-Host "[spike-provision] $m" -ForegroundColor Cyan }
function Write-Ok([string]$m)   { Write-Host "  [ok] $m" -ForegroundColor Green }
function Write-Skip([string]$m) { Write-Host "  [skip] $m" -ForegroundColor DarkGray }

function Test-IsElevated {
    ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Get-OperatorSid { ([Security.Principal.WindowsIdentity]::GetCurrent()).User.Value }

function Get-BaseHome([string]$VenvPath) {
    $cfg = Join-Path $VenvPath 'pyvenv.cfg'
    if (-not (Test-Path -LiteralPath $cfg)) { return $null }
    return (Get-VenvBaseHome -PyvenvCfgLines (Get-Content -LiteralPath $cfg))
}

function Get-FilesToCopy {
    # name -> source; spike-config.json is generated, not copied.
    @('spike-run-test.ps1', 'spike_model.py')
}

function Get-TaskDefinitionText {
    $ps = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
    $bin = Join-Path $script:SpikeRoot 'bin'
    [pscustomobject]@{
        Path = $script:SpikeTaskPath; Name = $script:SpikeTaskName; User = $script:SpikeUser; LogonType = 'Password (credential vaulted by Task Scheduler)'
        RunLevel = 'Limited'; Trigger = 'none (on demand only)'; Execute = $ps
        Arguments = "-NoProfile -NonInteractive -ExecutionPolicy Bypass -File `"$bin\spike-run-test.ps1`" -RequestFile `"$bin\request.json`""
        WorkingDirectory = (Join-Path $script:SpikeRoot 'work'); ExecutionTimeLimit = '30 minutes'; MultipleInstances = 'IgnoreNew'
    }
}

function Set-BatchLogonRight {
    # Same secedit export/modify/configure approach as provision-coder-account.ps1, other holders preserved.
    # Files go in a private (protected-DACL) directory, never loose in %TEMP% (see New-PrivateTempDir).
    param([Parameter(Mandatory)][string]$Sid, [ValidateSet('add','remove')][string]$Mode = 'add')
    $tmp = New-PrivateTempDir
    $exportInf = Join-Path $tmp 'exp.inf'; $importInf = Join-Path $tmp 'imp.inf'; $db = Join-Path $tmp 'ur.sdb'
    try {
        & secedit /export /cfg $exportInf /areas USER_RIGHTS *> $null
        $lines = if (Test-Path -LiteralPath $exportInf) { Get-Content -LiteralPath $exportInf } else { @() }
        $newLine = Resolve-PrivilegeLine -ExportLines $lines -Privilege 'SeBatchLogonRight' -Sid $Sid -Mode $Mode -Name $script:SpikeUser
        if ($null -eq $newLine) { Write-Ok "SeBatchLogonRight already $(if ($Mode -eq 'add') { 'granted' } else { 'absent' }) (idempotent)"; return }
        Set-Content -LiteralPath $importInf -Encoding Unicode -Value @('[Unicode]', 'Unicode=yes', '[Version]', 'signature="$CHICAGO$"', 'Revision=1', '[Privilege Rights]', $newLine)
        & secedit /configure /db $db /cfg $importInf /areas USER_RIGHTS *> $null
        if ($LASTEXITCODE -ne 0) { throw "secedit /configure failed (exit $LASTEXITCODE)" }
        Write-Ok "$(if ($Mode -eq 'add') { 'granted' } else { 'revoked' }) SeBatchLogonRight for the spike SID"
    } finally { Remove-PrivateTempDir $tmp }
}

function Invoke-Icacls([string[]]$IcaclsArgs) {
    Assert-AclTargetPlain $IcaclsArgs[0]   # no wildcard characters; never a junction/symlink (icacls would act on its target)
    & icacls.exe @IcaclsArgs | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "icacls $($IcaclsArgs -join ' ') failed (exit $LASTEXITCODE)" }
}

# ------------------------------------------------------------------------------------------------------------------
function Invoke-SelfTest {
    $script:f = 0
    function Chk([string]$n, [bool]$c) { if ($c) { Write-Host "  [PASS] $n" -ForegroundColor Green } else { Write-Host "  [FAIL] $n" -ForegroundColor Red; $script:f++ } }
    $spike = 'S-1-5-21-1111111111-2222222222-3333333333-1001'
    $op    = 'S-1-5-21-1111111111-2222222222-3333333333-1000'
    $secrets = Get-SpikeSecretPaths
    Write-Host '== ACE plan ==' -ForegroundColor Cyan
    $plan = Get-SpikeAcePlan -SpikeSid $spike -OperatorSid $op -VenvBaseHome 'C:\Users\_OPERATOR_\AppData\Local\Programs\Python\Python311'
    $allowed = @($plan | Where-Object { $_.Principal -eq 'spike' } | ForEach-Object { $_.Path })
    Chk 'plan is non-empty and has spike rows' ($plan.Count -ge 8 -and $allowed.Count -ge 6)
    Chk 'the real plan satisfies every safety invariant' ((Test-AcePlanSafe -Plan $plan -SecretPaths $secrets -AllowedSpikePaths $allowed).Count -eq 0)
    Chk 'spike Modify only on work + results' ((@($plan | Where-Object { $_.Principal -eq 'spike' -and $_.Rights -eq 'M' } | ForEach-Object { $_.Path }) | Sort-Object) -join '|' -eq ((@('C:\blarai-spike\work', 'C:\blarai-spike\results') | Sort-Object) -join '|'))
    Chk 'venv, base interpreter and model dir are RX only' (@($plan | Where-Object { $_.Principal -eq 'spike' -and $_.Path -match 'venv|Python311|Qwen3.5' -and $_.Rights -ne 'RX' }).Count -eq 0)
    Chk 'no row names Everyone / Users / Authenticated Users' (@($plan | Where-Object { $_.Sid -in @('S-1-1-0', 'S-1-5-32-545', 'S-1-5-11') }).Count -eq 0)
    Chk 'spike SID is in no row except spike rows' (@($plan | Where-Object { $_.Sid -eq $spike -and $_.Principal -ne 'spike' }).Count -eq 0)
    Chk 'the spike root grant is NOT inherited (children do not inherit traverse)' (@($plan | Where-Object { $_.Principal -eq 'spike' -and $_.Path -eq 'C:\blarai-spike' -and $_.Inherit -eq 'tree' }).Count -eq 0)
    Chk 'root inheritance is disabled before grants' ($plan[0].Kind -eq 'disable-inheritance' -and $plan[0].Path -eq 'C:\blarai-spike')
    Chk 'icacls spec: tree RX' ((ConvertTo-IcaclsGrantSpec ($plan | Where-Object { $_.Path -eq 'C:\blarai-spike\bin' })) -eq "*$spike`:(OI)(CI)(RX)")
    Chk 'icacls spec: this-folder only has no inheritance flags' ((ConvertTo-IcaclsGrantSpec ($plan | Where-Object { $_.Principal -eq 'spike' -and $_.Path -eq 'C:\blarai-spike' })) -eq "*$spike`:(RX)")
    Write-Host '== ACE plan: negative controls (the checker must be able to fail) ==' -ForegroundColor Cyan
    $badModify = @($plan) + [pscustomobject]@{ Path = 'C:\Users\_OPERATOR_\BlarAI\.venv-2026.4'; Principal = 'spike'; Sid = $spike; Rights = 'M'; Inherit = 'tree'; Kind = 'grant'; Purpose = 'x'; Removable = $true }
    Chk 'checker flags Modify on the venv' ((Test-AcePlanSafe -Plan $badModify -SecretPaths $secrets -AllowedSpikePaths $allowed).Count -ge 1)
    $badAuth = @($plan) + [pscustomobject]@{ Path = 'C:\blarai-spike\work'; Principal = 'x'; Sid = 'S-1-5-11'; Rights = 'RX'; Inherit = 'tree'; Kind = 'grant'; Purpose = 'x'; Removable = $false }
    Chk 'checker flags Authenticated Users' ((Test-AcePlanSafe -Plan $badAuth -SecretPaths $secrets -AllowedSpikePaths $allowed).Count -ge 1)
    $badSecret = @($plan) + [pscustomobject]@{ Path = 'C:\Users\_OPERATOR_\.ssh'; Principal = 'spike'; Sid = $spike; Rights = 'RX'; Inherit = 'tree'; Kind = 'grant'; Purpose = 'x'; Removable = $true }
    Chk 'checker flags a grant on a secret path' ((Test-AcePlanSafe -Plan $badSecret -SecretPaths $secrets -AllowedSpikePaths $allowed).Count -ge 1)
    $badAnc = @($plan) + [pscustomobject]@{ Path = 'C:\Users\_OPERATOR_'; Principal = 'spike'; Sid = $spike; Rights = 'RX'; Inherit = 'tree'; Kind = 'grant'; Purpose = 'x'; Removable = $true }
    Chk 'checker flags a tree grant on an ANCESTOR of a secret (the profile root)' ((Test-AcePlanSafe -Plan $badAnc -SecretPaths $secrets -AllowedSpikePaths ($allowed + 'C:\Users\_OPERATOR_')).Count -ge 1)
    $badOut = @($plan) + [pscustomobject]@{ Path = 'C:\Windows'; Principal = 'spike'; Sid = $spike; Rights = 'RX'; Inherit = 'tree'; Kind = 'grant'; Purpose = 'x'; Removable = $true }
    Chk 'checker flags a path outside the allowlist' ((Test-AcePlanSafe -Plan $badOut -SecretPaths $secrets -AllowedSpikePaths $allowed).Count -ge 1)
    Write-Host '== privilege line, venv home, names ==' -ForegroundColor Cyan
    $inf = @('[Privilege Rights]', 'SeBatchLogonRight = *S-1-5-32-544,*S-1-5-32-551')
    Chk 'add keeps the other holders' ((Resolve-PrivilegeLine $inf 'SeBatchLogonRight' $spike 'add') -eq "SeBatchLogonRight = *S-1-5-32-544,*S-1-5-32-551,*$spike")
    Chk 'add is idempotent ($null when present)' ($null -eq (Resolve-PrivilegeLine @("SeBatchLogonRight = *$spike") 'SeBatchLogonRight' $spike 'add'))
    Chk 'remove removes only that SID' ((Resolve-PrivilegeLine @("SeBatchLogonRight = *S-1-5-32-544,*$spike") 'SeBatchLogonRight' $spike 'remove') -eq 'SeBatchLogonRight = *S-1-5-32-544')
    Chk 'remove of the last holder leaves an empty right' ((Resolve-PrivilegeLine @("SeBatchLogonRight = *$spike") 'SeBatchLogonRight' $spike 'remove') -eq 'SeBatchLogonRight =')
    Chk 'remove when absent is a no-op' ($null -eq (Resolve-PrivilegeLine $inf 'SeBatchLogonRight' $spike 'remove'))
    Chk 'add is idempotent when the holder is written by NAME' ($null -eq (Resolve-PrivilegeLine @("SeBatchLogonRight = blarai-spike") 'SeBatchLogonRight' $spike 'add' -Name 'blarai-spike'))
    Chk 'venv home parse' ((Get-VenvBaseHome @('home = C:\Python311', 'version = 3.11.9')) -eq 'C:\Python311' -and $null -eq (Get-VenvBaseHome @('x = 1')))
    Chk 'account-domain SID check' ((Test-AccountDomainSid $spike) -and -not (Test-AccountDomainSid 'S-1-5-32-544') -and -not (Test-AccountDomainSid 'S-1-1-0'))
    Chk 'user name check' ((Test-SpikeUserName 'blarai-spike') -and -not (Test-SpikeUserName 'a;b') -and -not (Test-SpikeUserName ''))
    $pw = New-StrongPassword
    $bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($pw)
    try { $plain = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr) } finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr) }
    Chk 'password: 24 chars, all four classes' ($plain.Length -eq 24 -and $plain -cmatch '[a-z]' -and $plain -cmatch '[A-Z]' -and $plain -match '\d' -and $plain -match '[^A-Za-z0-9]')
    $pw2 = New-StrongPassword; $b2 = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($pw2)
    try { $plain2 = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($b2) } finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($b2) }
    Chk 'password: two draws differ' ($plain -ne $plain2)
    $plain = $null; $plain2 = $null
    Write-Host '== result schema ==' -ForegroundColor Cyan
    $t = (Get-Date).ToString("yyyy-MM-dd'T'HH:mm:ss.fffzzz")
    function New-FakeResult([string]$mode, [string]$overall, [string]$serveStatus) {
        $names = if ($mode -eq 'serve') { $script:StepNamesServe } else { $script:StepNamesBase }
        $st = @($names | ForEach-Object { [pscustomobject]@{ name = $_; status = $(if ($_ -eq 'serve') { $serveStatus } else { 'pass' }); started = $t; finished = $t; detail = 'd'; data = $null } })
        [pscustomobject]@{ schema_version = 1; run_id = 'run-20261005-aaaa'; mode = $mode; started = $t; finished = $t; overall = $overall; steps = $st }
    }
    Chk 'valid feasibility result passes the schema' ((Test-SpikeResultSchema (New-FakeResult 'feasibility' 'pass' 'pass')).Count -eq 0)
    Chk 'valid serve result passes the schema' ((Test-SpikeResultSchema (New-FakeResult 'serve' 'pass' 'pass')).Count -eq 0)
    $r = New-FakeResult 'serve' 'pass' 'pass'; $r.steps = @($r.steps | Where-Object { $_.name -ne 'serve' })
    Chk 'schema rejects a serve result without the serve step' ((Test-SpikeResultSchema $r).Count -ge 1)
    $r = New-FakeResult 'feasibility' 'pass' 'pass'; $r.steps[2].status = 'maybe'
    Chk 'schema rejects an unknown status' ((Test-SpikeResultSchema $r).Count -ge 1)
    $r = New-FakeResult 'feasibility' 'pass' 'pass'; $r.steps[1].started = '2026-10-05 15:00:00'
    Chk 'schema rejects a timestamp without T/offset' ((Test-SpikeResultSchema $r).Count -ge 1)
    $r = New-FakeResult 'feasibility' 'pass' 'pass'; $r.steps[3].status = 'fail'
    Chk 'schema rejects overall=pass over a failed step' ((Test-SpikeResultSchema $r).Count -ge 1)
    $r = New-FakeResult 'feasibility' 'pass' 'pass'; $r.PSObject.Properties.Remove('run_id')
    Chk 'schema rejects a missing top-level key' ((Test-SpikeResultSchema $r).Count -ge 1)
    $r = New-FakeResult 'feasibility' 'pass' 'pass'; $r.steps[2].finished = (Get-Date).AddMinutes(-5).ToString("yyyy-MM-dd'T'HH:mm:ss.fffzzz")
    Chk 'schema rejects a step that finishes before it starts' ((Test-SpikeResultSchema $r).Count -ge 1)
    Chk 'icacls-text scan finds a SID and ignores other lines' ((Find-SidInIcaclsText @("x $spike`:(R)", 'y BUILTIN\Administrators:(F)') $spike 'blarai-spike').Count -eq 1)
    Write-Host '== config ==' -ForegroundColor Cyan
    $c = Get-SpikeRuntimeConfig -SpikeSid $spike -SecretPaths $secrets -OperatorSid $op
    Chk 'config round-trips as JSON with the expected SID' ((ConvertFrom-Json (ConvertTo-Json -InputObject $c -Depth 5)).expected_sid -eq $spike)
    Chk 'model memory floor is set (>= 12 GB)' ($c.min_free_gb -ge 12)
    Write-Host '== review follow-ups: password handling, link-safe ACL targets ==' -ForegroundColor Cyan
    $own = @(Get-ChildItem -LiteralPath $PSScriptRoot -Filter '*.ps1' -File | ForEach-Object { $_.FullName })
    # Code lines only: comments and this block's own pattern lines are excluded so the scan cannot match itself.
    $code = @($own | ForEach-Object { Get-Content -LiteralPath $_ } | Where-Object { $_ -notmatch '^\s*#' -and $_ -notmatch '\[regex\]|^\s*Chk |^\s*\$(code|pwHits|plainUse) ' })
    $pwHits = @($code | Where-Object { $_ -match 'schtasks(\.exe)?\b.*/RP\b' -or $_ -match '\bnet(\.exe)?\s+user\b' })
    Chk 'no script passes the account password on a command line (schtasks /RP, net user)' ($pwHits.Count -eq 0)
    $plainUse = @($code | Where-Object { $_ -match 'Register-ScheduledTask\b.*-Password' })
    Chk 'the only plaintext password use is Register-ScheduledTask -Password (a CIM call, not a process command line)' ($plainUse.Count -eq 1)
    $leaks = @($code | Where-Object { $_ -match '(Write-Host|Write-Output|Out-File|Set-Content|Add-Content|ConvertTo-Json|Write-JsonAtomic)' -and $_ -match '\$(plain|secure|pw)\b' })
    Chk 'the password is never written to the host or a file' ($leaks.Count -eq 0)
    $wc = $false; try { Assert-AclTargetPlain 'C:\blarai-spike\*' } catch { $wc = $true }
    Chk 'Invoke-Icacls refuses a wildcard target' $wc
    Write-Host ("provision selftest: {0}" -f $(if ($script:f -eq 0) { 'all passed' } else { "$($script:f) FAILED" })) -ForegroundColor $(if ($script:f -eq 0) { 'Green' } else { 'Red' })
    return $(if ($script:f -eq 0) { 0 } else { 1 })
}

# ------------------------------------------------------------------------------------------------------------------
function Get-ProvisionContext {
    $opSid = Get-OperatorSid
    $existing = Get-LocalUser -Name $script:SpikeUser -ErrorAction SilentlyContinue
    $spikeSid = if ($existing) { $existing.SID.Value } else { '<SID of blarai-spike, assigned when the account is created>' }
    $baseHome = Get-BaseHome $Venv
    [pscustomobject]@{
        OperatorSid = $opSid; Existing = $existing; SpikeSid = $spikeSid; BaseHome = $baseHome
        Plan = (Get-SpikeAcePlan -SpikeSid $spikeSid -OperatorSid $opSid -Venv $Venv -VenvBaseHome $baseHome -ModelDir $ModelDir)
        Secrets = (Get-SpikeSecretPaths -ExistsFilter)
    }
}

function Assert-Preconditions($ctx) {
    $e = New-Object System.Collections.ArrayList
    if (-not (Test-Path -LiteralPath (Join-Path $Venv 'Scripts\python.exe'))) { [void]$e.Add("venv python not found: $Venv\Scripts\python.exe") }
    if ((Test-PathExistsNoFollow $script:SpikeRoot) -and (Test-IsReparsePoint $script:SpikeRoot)) { [void]$e.Add("$($script:SpikeRoot) exists and is a reparse point (junction or symlink): refusing to provision through it") }
    if (-not $ctx.BaseHome -or -not (Test-Path -LiteralPath $ctx.BaseHome)) { [void]$e.Add("venv base interpreter home not found (pyvenv.cfg home = '$($ctx.BaseHome)')") }
    if (-not (Test-Path -LiteralPath (Join-Path $ModelDir 'openvino_language_model.xml'))) { [void]$e.Add("model dir has no openvino_language_model.xml: $ModelDir") }
    foreach ($f in (Get-FilesToCopy)) { if (-not (Test-Path -LiteralPath (Join-Path $PSScriptRoot $f))) { [void]$e.Add("missing source file $f") } }
    if ($ctx.Existing -and $ctx.Existing.Description -ne $script:SpikeDescMarker) { [void]$e.Add("a local user '$($script:SpikeUser)' exists but is not this spike's account (description mismatch): refusing to adopt it") }
    $unsafe = Test-AcePlanSafe -Plan $ctx.Plan -SecretPaths $ctx.Secrets -AllowedSpikePaths @($ctx.Plan | Where-Object { $_.Principal -eq 'spike' } | ForEach-Object { $_.Path })
    foreach ($u in $unsafe) { [void]$e.Add("ACE plan violates an invariant: $u") }
    if (-not (Test-AccountDomainSid $ctx.OperatorSid)) { [void]$e.Add("operator SID is not an account-domain SID: $($ctx.OperatorSid)") }
    if ($ctx.Existing -and $ctx.Existing.SID.Value -eq $ctx.OperatorSid) { [void]$e.Add('spike SID equals the operator SID') }
    return @($e)
}

function Invoke-DryRun {
    Write-Host '== DRY RUN: nothing below has been done; nothing will be changed by this command ==' -ForegroundColor Yellow
    Write-Host ("machine clock: {0}" -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss K'))
    $ctx = Get-ProvisionContext
    Write-Host ''
    Write-Host '1. ACCOUNT' -ForegroundColor Cyan
    if ($ctx.Existing) { Write-Host "   already exists (SID $($ctx.SpikeSid)); would be left as-is (password untouched unless -ForceNewPassword)" }
    else { Write-Host "   CREATE local user '$($script:SpikeUser)'  description '$($script:SpikeDescMarker)'" }
    Write-Host "   member of: Users ONLY (never Administrators / Power Users)"
    Write-Host "   password: 24 random characters generated at provision time, held ONLY in the scheduled task's credential vault; never printed, logged or saved"
    Write-Host '2. USER RIGHT' -ForegroundColor Cyan
    Write-Host "   GRANT SeBatchLogonRight ('Log on as a batch job') to the spike SID via secedit; every other holder preserved"
    Write-Host '3. DIRECTORIES' -ForegroundColor Cyan
    foreach ($d in @('', 'bin', 'work', 'work\tmp', 'results')) { Write-Host ("   CREATE {0}" -f (Join-Path $script:SpikeRoot $d).TrimEnd('\')) }
    Write-Host '4. ACCESS-CONTROL ENTRIES (SID-form icacls; the only ACEs this spike adds)' -ForegroundColor Cyan
    foreach ($r in $ctx.Plan) { Write-Host ('   ' + (Format-AceRow $r)) }
    Write-Host '   NO ACE is added on any of these operator secret paths (spike-run-test proves each is denied):' -ForegroundColor Yellow
    foreach ($s in $ctx.Secrets) { Write-Host "      $s" }
    Write-Host '5. FILES COPIED INTO C:\blarai-spike\bin (operator-written; the account can read, not write)' -ForegroundColor Cyan
    foreach ($f in (Get-FilesToCopy)) { Write-Host "   $PSScriptRoot\$f -> $($script:SpikeRoot)\bin\$f" }
    Write-Host "   GENERATED spike-config.json (expected SID, model dir, venv python, the secret-path list above, outbound target, 14 GB free-memory floor)"
    Write-Host '6. SCHEDULED TASK' -ForegroundColor Cyan
    (Get-TaskDefinitionText).PSObject.Properties | ForEach-Object { Write-Host ("   {0,-18}: {1}" -f $_.Name, $_.Value) }
    Write-Host '7. STATE FILE' -ForegroundColor Cyan
    Write-Host "   $($script:SpikeStatePath)  (SID + ACE rows + timestamps; no password)"
    Write-Host ''
    Write-Host 'NOT created by this script: any firewall rule, any WFP filter, any process on the GPU.' -ForegroundColor Green
    Write-Host 'Rollback: spike-cleanup.ps1 (-DryRun first). Check: spike-verify-cleanup.ps1.' -ForegroundColor Green
    Write-Host ''
    $pre = Assert-Preconditions $ctx
    Write-Host '-- preconditions (read-only) --' -ForegroundColor Cyan
    Write-Host ("   venv python           : {0}" -f (Join-Path $Venv 'Scripts\python.exe'))
    Write-Host ("   venv base interpreter : {0}" -f $ctx.BaseHome)
    Write-Host ("   model dir             : {0}" -f $ModelDir)
    Write-Host ("   elevated now          : {0} (-Apply needs it; -DryRun does not)" -f (Test-IsElevated))
    $os = Get-CimInstance Win32_OperatingSystem
    Write-Host ("   free RAM now          : {0:N1} GB of {1:N1} GB (the 4B load needs ~10 GB In-Use; the spike refuses below 14 GB free)" -f ($os.FreePhysicalMemory / 1MB), ($os.TotalVisibleMemorySize / 1MB))
    $tp = Get-ScheduledTask -TaskPath $script:SpikeTaskPath -TaskName $script:SpikeTaskName -ErrorAction SilentlyContinue
    Write-Host ("   task already present  : {0}" -f [bool]$tp)
    Write-Host ("   C:\blarai-spike exists: {0}" -f (Test-Path $script:SpikeRoot))
    if ($pre.Count) { $pre | ForEach-Object { Write-Host "   PRECONDITION FAILS: $_" -ForegroundColor Red }; Write-Host 'DRY RUN found problems; -Apply would refuse.' -ForegroundColor Red; return 2 }
    Write-Host 'DRY RUN complete; preconditions hold. Nothing was changed.' -ForegroundColor Green
    return 0
}

function Invoke-Apply {
    if (-not (Test-IsElevated)) { throw 'spike-provision.ps1 -Apply must run ELEVATED (it creates a local account and changes ACLs and a user right).' }
    $ctx = Get-ProvisionContext
    $pre = Assert-Preconditions $ctx
    if ($pre.Count) { $pre | ForEach-Object { Write-Host "PRECONDITION FAILS: $_" -ForegroundColor Red }; throw 'preconditions failed; nothing was changed' }
    $secure = $null
    Write-Step '1/7 account'
    if (-not $ctx.Existing) {
        $secure = New-StrongPassword
        New-LocalUser -Name $script:SpikeUser -Password $secure -PasswordNeverExpires -AccountNeverExpires -Description $script:SpikeDescMarker | Out-Null
        Write-Ok "created local user '$($script:SpikeUser)'"
    } elseif ($ForceNewPassword) {
        $secure = New-StrongPassword
        Set-LocalUser -Name $script:SpikeUser -Password $secure
        Write-Ok 'password re-keyed (-ForceNewPassword)'
    } else { Write-Skip 'account exists; password and task credential left as-is' }
    if (-not (Get-LocalGroupMember -Group 'Users' -Member $script:SpikeUser -ErrorAction SilentlyContinue)) { Add-LocalGroupMember -Group 'Users' -Member $script:SpikeUser }
    foreach ($g in @('Administrators', 'Power Users')) {
        try { if (Get-LocalGroupMember -Group $g -Member $script:SpikeUser -ErrorAction SilentlyContinue) { Remove-LocalGroupMember -Group $g -Member $script:SpikeUser -Confirm:$false; Write-Ok "removed from $g" } } catch { }
    }
    $sid = (Get-LocalUser -Name $script:SpikeUser).SID.Value
    if (-not (Test-AccountDomainSid $sid)) { throw "unexpected spike SID shape: $sid" }
    Write-Ok "spike SID $sid"
    # Re-plan with the real SID and re-check the invariants before touching any ACL.
    $plan = Get-SpikeAcePlan -SpikeSid $sid -OperatorSid $ctx.OperatorSid -Venv $Venv -VenvBaseHome $ctx.BaseHome -ModelDir $ModelDir
    $unsafe = Test-AcePlanSafe -Plan $plan -SecretPaths $ctx.Secrets -AllowedSpikePaths @($plan | Where-Object { $_.Principal -eq 'spike' } | ForEach-Object { $_.Path })
    if ($unsafe.Count) { throw ('ACE plan unsafe: ' + ($unsafe -join '; ')) }
    # State first (so a failure half-way is still cleanable): SID + rows, no secret.
    Write-JsonAtomic -Path $script:SpikeStatePath -Object ([ordered]@{
        schema_version = 1; provisioned = (Get-Date).ToString("yyyy-MM-dd'T'HH:mm:ss.fffzzz"); spike_user = $script:SpikeUser; spike_sid = $sid
        operator_sid = $ctx.OperatorSid; venv = $Venv; venv_base_home = $ctx.BaseHome; model_dir = $ModelDir
        root = $script:SpikeRoot; profile_dir = $script:SpikeProfileDir; task = "$($script:SpikeTaskPath)$($script:SpikeTaskName)"
        removable_ace_paths = @($plan | Where-Object { $_.Removable } | ForEach-Object { $_.Path } | Select-Object -Unique)
    })
    Write-Ok "state written: $($script:SpikeStatePath)"

    Write-Step '2/7 user right'
    Set-BatchLogonRight -Sid $sid -Mode add

    Write-Step '3/7 directories + root DACL'
    foreach ($d in @('', 'bin', 'work', 'work\tmp', 'results')) { New-Item -ItemType Directory -Force (Join-Path $script:SpikeRoot $d).TrimEnd('\') | Out-Null }
    Write-Step '4/7 ACEs'
    foreach ($r in $plan) {
        if ($r.Kind -eq 'disable-inheritance') { Invoke-Icacls @($r.Path, '/inheritance:r'); Write-Ok "inheritance disabled on $($r.Path)"; continue }
        Invoke-Icacls @($r.Path, '/grant', (ConvertTo-IcaclsGrantSpec $r)); Write-Ok ("{0} {1} -> {2}" -f $r.Principal, $r.Rights, $r.Path)
    }

    Write-Step '5/7 files into bin'
    $bin = Join-Path $script:SpikeRoot 'bin'
    foreach ($f in (Get-FilesToCopy)) { Copy-Item -LiteralPath (Join-Path $PSScriptRoot $f) -Destination (Join-Path $bin $f) -Force; Write-Ok "copied $f" }
    Write-JsonAtomic -Path (Join-Path $bin 'spike-config.json') -Object (Get-SpikeRuntimeConfig -SpikeSid $sid -SecretPaths $ctx.Secrets -OperatorSid $ctx.OperatorSid)
    Write-Ok 'generated spike-config.json'

    Write-Step '6/7 scheduled task (no trigger; credential vaulted)'
    $td = Get-TaskDefinitionText
    if ($null -eq $secure) {
        if (Get-ScheduledTask -TaskPath $td.Path -TaskName $td.Name -ErrorAction SilentlyContinue) { Write-Skip 'task exists and no fresh password: left as-is' }
        else { throw 'the account exists but the task does not, and no fresh password is available: re-run with -ForceNewPassword' }
    } else {
        $action = New-ScheduledTaskAction -Execute $td.Execute -Argument $td.Arguments -WorkingDirectory $td.WorkingDirectory
        $principal = New-ScheduledTaskPrincipal -UserId $script:SpikeUser -LogonType Password -RunLevel Limited
        $settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 30) -StartWhenAvailable:$false
        $task = New-ScheduledTask -Action $action -Principal $principal -Settings $settings -Description 'BlarAI #1689 spike: confined-inference feasibility run as blarai-spike (RunLevel Limited). On demand only; deleted by spike-cleanup.ps1.'
        $bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
        try {
            $plain = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr)
            Register-ScheduledTask -TaskName $td.Name -TaskPath $td.Path -InputObject $task -User $script:SpikeUser -Password $plain -Force | Out-Null
        } finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr); $plain = $null }
        Write-Ok "registered $($td.Path)$($td.Name) as $($script:SpikeUser) (RunLevel Limited, no trigger)"
    }
    if ($secure -is [IDisposable]) { try { $secure.Dispose() } catch {} }
    $secure = $null

    Write-Step '7/7 done'
    Write-Host 'PROVISION complete. Next: spike-wfp.ps1 -DryRun, then -TestA, then -TestB (see README.md). Rollback: spike-cleanup.ps1.' -ForegroundColor Green
    return 0
}

# ------------------------------------------------------------------------------------------------------------------
$modes = @($SelfTest.IsPresent, $DryRun.IsPresent, $Apply.IsPresent) | Where-Object { $_ }
if (@($modes).Count -ne 1) {
    Write-Host 'usage: spike-provision.ps1 -SelfTest | -DryRun | -Apply [-ForceNewPassword]   (exactly one mode; nothing happens without one)' -ForegroundColor Yellow
    exit 2
}
try {
    if ($SelfTest) { exit (Invoke-SelfTest) }
    if ($DryRun)   { exit (Invoke-DryRun) }
    if ($Apply)    { exit (Invoke-Apply) }
} catch {
    Write-Host "STOPPED: $($_.Exception.Message)" -ForegroundColor Red
    Write-Host 'Nothing further was done. Re-running -Apply is safe; spike-cleanup.ps1 removes whatever was created.' -ForegroundColor Red
    exit 1
}
