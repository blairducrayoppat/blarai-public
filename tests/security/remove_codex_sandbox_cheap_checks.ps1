#requires -Version 7.0
# Cheap behavioural checks of the Codex-removal script's safety logic, run by
# tests/security/test_remove_codex_sandbox_static.py (standing gate), and again against deliberately broken
# copies of the script to prove each check can fail. Pure helpers plus one tiny throwaway tree under
# C:\blarai-spike-1740-ops\zz1740-cheap-*; no accounts, rules or registry values; works without elevation.
param([Parameter(Mandatory)][string]$ScriptPath)
$ErrorActionPreference = 'Stop'
. $ScriptPath
$script:SelfTestActive = $true
$results = [System.Collections.Generic.List[object]]::new()
function Test-CheapCase([string]$Name, [scriptblock]$Body) {
    $err = ''
    try { $ok = [bool](& $Body) } catch { $ok = $false; $err = $_.Exception.Message }
    $results.Add([ordered]@{ name = $Name; pass = $ok; err = $err })
}
function Remove-CheapTree([string]$Path) {
    if (-not (Test-Path -LiteralPath $Path)) { return }
    Get-ChildItem -LiteralPath $Path -Recurse -Force -ErrorAction SilentlyContinue | Where-Object { $_.Attributes -band [IO.FileAttributes]::ReparsePoint } | ForEach-Object { [IO.Directory]::Delete($_.FullName) }
    Remove-Item -LiteralPath $Path -Recurse -Force -ErrorAction SilentlyContinue
}
$fake = 'S-1-5-21-1111111111-2222222222-3333333333-4001'
$other = 'S-1-5-21-1111111111-2222222222-3333333333-4003'

# ---------------------------------------------------------------- pure helpers
$sdB = "D:PAI(A;OICI;FA;;;SY)(A;OICIID;0x1201bf;;;$fake)(A;;FR;;;$other)"
Test-CheapCase 'sddl: removing a SID cuts exactly its entries and keeps the rest in order' { (Remove-SidsFromSddl $sdB @($fake)) -ceq "D:PAI(A;OICI;FA;;;SY)(A;;FR;;;$other)" }
Test-CheapCase 'sddl: removing no SID changes nothing' { (Remove-SidsFromSddl $sdB @()) -ceq $sdB }
Test-CheapCase 'sddl: a list left without entries is recognised as empty' { (-not (Test-SddlHasAces 'D:AI')) -and (Test-SddlHasAces $sdB) }
Test-CheapCase 'sddl: the write form adds the request flag once and only where the list is auto-inherited' { ((ConvertTo-WritableSddl 'D:PAI(A;;FA;;;SY)') -ceq 'D:PARAI(A;;FA;;;SY)') -and ((ConvertTo-WritableSddl 'D:PARAI(A;;FA;;;SY)') -ceq 'D:PARAI(A;;FA;;;SY)') -and ((ConvertTo-WritableSddl 'D:(A;;FA;;;SY)') -ceq 'D:(A;;FA;;;SY)') }
Test-CheapCase 'delta: only the dropped SID differs, so nothing is reported' { $null -eq (Get-AceDelta $sdB "D:PAI(A;OICI;FA;;;SY)(A;;FR;;;$other)" @($fake)) }
Test-CheapCase 'delta: a lost entry of another principal is reported' { (Get-AceDelta $sdB 'D:PAI(A;OICI;FA;;;SY)' @($fake)) -like "*lost=*$other*" }
Test-CheapCase 'delta: a GAINED entry is reported just like a loss' { (Get-AceDelta $sdB "D:PAI(A;OICI;FA;;;SY)(A;;FR;;;$other)(A;;FA;;;WD)" @($fake)) -like '*gained=*' }
Test-CheapCase 'delta: an unparseable list is reported, never read as no change' { $null -ne (Get-AceDelta $sdB 'not an access list' @($fake)) }
$sc = [ordered]@{ AclTargets = @([ordered]@{ Path = 'C:\a'; Sid = 'S1' }, [ordered]@{ Path = 'C:\a\.git'; Sid = 'S2' }, [ordered]@{ Path = 'C:\b'; Sid = 'S3' }) }
Test-CheapCase 'scope: an object gets the SIDs of the allowlisted folders at or above it, a look-alike name gets none' { (((Get-ScopeSids $sc 'C:\a\x') -join ',') -ceq 'S1') -and (((Get-ScopeSids $sc 'C:\a\.git\y') -join ',') -ceq 'S1,S2') -and ((Get-ScopeSids $sc 'C:\ab\x').Count -eq 0) -and (((Get-ScopeSids $sc 'C:\b') -join ',') -ceq 'S3') }
Test-CheapCase 'firewall scope: exactly the one SID passes; a longer SID that starts the same, a second SID or none do not' { $s7 = 'S-1-5-21-1-2-3-1007'; (Test-ScopeOnlySid "O:LSD:(A;;CC;;;$s7)" $s7) -and -not (Test-ScopeOnlySid "O:LSD:(A;;CC;;;$($s7)0)" $s7) -and -not (Test-ScopeOnlySid "O:LSD:(A;;CC;;;$s7)(A;;CC;;;S-1-5-21-1-2-3-1009)" $s7) -and -not (Test-ScopeOnlySid '' $s7) }
Test-CheapCase 'fw scope: a shorthand principal (WD, BU), a deny entry or a second entry of any form is not a match' { $s9 = 'S-1-5-21-1-2-3-1007'; (-not (Test-ScopeOnlySid "O:LSD:(A;;CC;;;WD)" $s9)) -and (-not (Test-ScopeOnlySid "O:LSD:(A;;CC;;;$s9)(A;;CC;;;BU)" $s9)) -and (-not (Test-ScopeOnlySid "O:LSD:(D;;CC;;;$s9)" $s9)) -and (-not (Test-ScopeOnlySid "O:LSD:(A;;CC;;;$s9)(D;;CC;;;WD)" $s9)) -and (Test-ScopeOnlySid "O:LSD:(A;;CC;;;$s9)" $s9) }
Test-CheapCase 'stage: any letter case is accepted, an unknown stage or part is refused' { $m1 = try { $null = Test-StageHas 'bogus' 'Acl'; '' } catch { $_.Exception.Message }; $m2 = try { $null = Test-StageHas 'all' 'Nope'; '' } catch { $_.Exception.Message }; (Test-StageHas 'ALL' 'Acl') -and (Test-StageHas 'accounts' 'Accounts') -and (-not (Test-StageHas 'accounts' 'Acl')) -and (Test-StageHas 'AclEntries' 'Acl') -and ($m1 -like '*unknown stage*') -and ($m2 -like '*unknown stage part*') -and ((Get-CanonicalStage 'aclENTRIES') -ceq 'AclEntries') }
Test-CheapCase 'digest: bound to the script itself, so the same plan under a different script hash differs' { $dga = Get-PlanDigest ([ordered]@{ Mode = 'test' }) @() 'Accounts'; $script:ScriptShaOverride = ('B' * 64); try { $dgb = Get-PlanDigest ([ordered]@{ Mode = 'test' }) @() 'Accounts' } finally { $script:ScriptShaOverride = $null }; ($dga -cne $dgb) -and ($dga -ceq (Get-PlanDigest ([ordered]@{ Mode = 'test' }) @() 'accounts')) }
Test-CheapCase 'read errors: an account that is not there reads as absent, any other failure is thrown' { $abs = Get-LocalUserOrNull 'zz1740-chp9-no-such-user'; function global:Get-LocalUser { throw [UnauthorizedAccessException]::new('denied') }; try { $m = try { $null = Get-LocalUserOrNull 'whoever'; '' } catch { $_.Exception.Message } } finally { Remove-Item Function:\Get-LocalUser -ErrorAction SilentlyContinue }; ($null -eq $abs) -and ($m -like '*denied*') }
Test-CheapCase 'read errors: a group that is not there reads as absent, any other failure is thrown' { $abs = Get-LocalGroupOrNull 'zz1740-chp9-no-such-group'; function global:Get-LocalGroup { throw [UnauthorizedAccessException]::new('denied') }; try { $m = try { $null = Get-LocalGroupOrNull 'whoever'; '' } catch { $_.Exception.Message } } finally { Remove-Item Function:\Get-LocalGroup -ErrorAction SilentlyContinue }; ($null -eq $abs) -and ($m -like '*denied*') }
Test-CheapCase 'read errors: no firewall rule found reads as empty, any other failure is thrown' { function global:Get-NetFirewallRule { [CmdletBinding()] param($DisplayName) Write-Error -Message 'No MSFT_NetFirewallRule objects found with property DisplayName' -Category ObjectNotFound }; try { $none = @(Get-FirewallRulesByDisplayName 'x') } finally { Remove-Item Function:\Get-NetFirewallRule -ErrorAction SilentlyContinue }; function global:Get-NetFirewallRule { throw [UnauthorizedAccessException]::new('denied') }; try { $m = try { $null = Get-FirewallRulesByDisplayName 'x'; '' } catch { $_.Exception.Message } } finally { Remove-Item Function:\Get-NetFirewallRule -ErrorAction SilentlyContinue }; ($none.Count -eq 0) -and ($m -like '*denied*') }
Test-CheapCase 'stages: Accounts covers the account steps only, AclEntries the access entries only' { (Test-StageHas 'Accounts' 'Accounts') -and -not (Test-StageHas 'Accounts' 'Acl') -and (Test-StageHas 'AclEntries' 'Acl') -and -not (Test-StageHas 'AclEntries' 'Accounts') -and (Test-StageHas 'All' 'Acl') -and (Test-StageHas 'All' 'Accounts') }
Test-CheapCase 'explicit codex: an explicit entry is seen, an inherited one is not' { ((Get-ExplicitPurgeSids "D:(A;OICI;FA;;;$fake)" @($fake)).Count -eq 1) -and ((Get-ExplicitPurgeSids "D:AI(A;OICIID;FA;;;$other)" @($other)).Count -eq 0) }
$good = [ordered]@{ root = 'x'; hits = 0; firstHits = @(); foldersLeftUnscanned = 0; unreadable = 0; scanned = 5 }
$withScan = { param($o) $c = [ordered]@{}; foreach ($k in $good.Keys) { $c[$k] = $good[$k] }; foreach ($k in $o.Keys) { $c[$k] = $o[$k] }; $c }
Test-CheapCase 'certification: a complete clean scan passes; a cut-short scan, unreadable objects and a hit do not' { ((Get-CertificationProblems @($good)).Count -eq 0) -and ((Get-CertificationProblems @(& $withScan @{ foldersLeftUnscanned = 3 })).Count -eq 1) -and ((Get-CertificationProblems @(& $withScan @{ unreadable = 2 })).Count -eq 1) -and ((Get-CertificationProblems @(& $withScan @{ hits = 1; firstHits = @('p') })).Count -eq 1) }
Test-CheapCase 'rights: a SID or a local account name in the export is found, other principals are not' { $rs = Get-RealSpec; ((Find-RightsHits $rs 'SeX = *S-1-5-32-544,CodexSandboxOffline,Guest').Count -ge 1) -and ((Find-RightsHits $rs 'SeX = *S-1-5-32-544,blarai-coder,Guest').Count -eq 0) }

# ---------------------------------------------------------------- stage 1: every finding class and every identity check, on states built in memory
$rs = Get-RealSpec
$clean = [ordered]@{
    users = @($rs.Users | ForEach-Object { [ordered]@{ name = $_.Name; expectedSid = $_.Sid; exists = $true; sid = $_.Sid; enabled = $false; lastLogon = $null; profileListEntry = $false; profileFolders = @(); cimProfile = $false; groups = @('Users', $rs.Group.Name) } })
    group = [ordered]@{ name = $rs.Group.Name; expectedSid = $rs.Group.Sid; exists = $true; sid = $rs.Group.Sid; description = $rs.Group.Description; memberSids = @($rs.Users | ForEach-Object { $_.Sid }) }
    firewall = @($rs.Firewall | ForEach-Object { [ordered]@{ displayName = $_.DisplayName; expectedName = $_.Name; count = 1; name = $_.Name; enabled = 'True'; direction = 'Outbound'; action = 'Block'; localUser = "O:LSD:(A;;CC;;;$($_.UserSid))" } })
    firewallExtra = @()
    registry = [ordered]@{ targets = [ordered]@{ CodexSandboxOffline = 'DWord:0'; CodexSandboxOnline = 'DWord:0' } }
    acl = @()
    heavy = [ordered]@{ checked = $true; notRun = @(); services = @(); tasks = @(); wfpHits = @(); rightsHits = @() }
}
$cleanJson = $clean | ConvertTo-Json -Depth 8
$mutateState = { param($edit) $st = $cleanJson | ConvertFrom-Json -AsHashtable -Depth 8; & $edit $st; $st }
Test-CheapCase 'findings: the clean state raises none' { (Get-Findings $rs $clean).Count -eq 0 }
foreach ($case in @(
        @{ n = 'an account with a different SID'; e = { param($s) $s.users[0].sid = 'S-1-5-21-9-9-9-9' } },
        @{ n = 'a logon record'; e = { param($s) $s.users[0].lastLogon = '2026-01-01T00:00:00Z' } },
        @{ n = 'a ProfileList entry'; e = { param($s) $s.users[1].profileListEntry = $true } },
        @{ n = 'a Windows profile record'; e = { param($s) $s.users[0].cimProfile = $true } },
        @{ n = 'a profile folder'; e = { param($s) $s.users[0].profileFolders = @('C:\Users\CodexSandboxOffline') } },
        @{ n = 'an account in another group'; e = { param($s) $s.users[0].groups = @('Users', 'Administrators') } },
        @{ n = 'an account whose groups cannot be read'; e = { param($s) $s.users[0].groups = @('unreadable') } },
        @{ n = 'the group with a different SID'; e = { param($s) $s.group.sid = 'S-1-5-21-9-9-9-9' } },
        @{ n = 'the group with another description'; e = { param($s) $s.group.description = 'something else' } },
        @{ n = 'a member that is not on the allowlist'; e = { param($s) $s.group.memberSids += 'S-1-5-21-9-9-9-5' } },
        @{ n = 'a group whose members cannot be read'; e = { param($s) $s.group.memberSids = @('unreadable') } },
        @{ n = 'two rules of one name'; e = { param($s) $s.firewall[0].count = 2 } },
        @{ n = 'a rule with another id'; e = { param($s) $s.firewall[0].name = '{00000000-0000-0000-0000-000000000000}' } },
        @{ n = 'a rule that is inbound'; e = { param($s) $s.firewall[0].direction = 'Inbound' } },
        @{ n = 'a rule that allows'; e = { param($s) $s.firewall[1].action = 'Allow' } },
        @{ n = 'a rule scoped to a second SID'; e = { param($s) $s.firewall[0].localUser += '(A;;CC;;;S-1-5-21-9-9-9-5)' } },
        @{ n = 'a rule scoped to everyone'; e = { param($s) $s.firewall[0].localUser = 'O:LSD:(A;;CC;;;WD)' } },
        @{ n = 'another rule that matches the glob'; e = { param($s) $s.firewallExtra = @('codex_other [{x}]') } },
        @{ n = 'a registry value of another shape'; e = { param($s) $s.registry.targets['CodexSandboxOnline'] = 'String:1' } },
        @{ n = 'a service'; e = { param($s) $s.heavy.services = @('codexsvc') } },
        @{ n = 'a scheduled task'; e = { param($s) $s.heavy.tasks = @('\codex-task') } },
        @{ n = 'a Windows Filtering Platform filter'; e = { param($s) $s.heavy.wfpHits = @('codex') } },
        @{ n = 'a user-rights assignment'; e = { param($s) $s.heavy.rightsHits = @('CodexSandboxOffline') } },
        @{ n = 'a check that did not run'; e = { param($s) $s.heavy.checked = $false; $s.heavy.notRun = @('WFP') } })) {
    $cs = $case
    Test-CheapCase "findings: $($cs.n) is reported" { (Get-Findings $rs (& $mutateState $cs.e)).Count -ge 1 }
}
Test-CheapCase 'findings: with the unexpected-live lock off nothing is reported (the toggle shows the lock is what reports)' { $script:GatesOff = @('unexpected-live'); try { (Get-Findings $rs (& $mutateState { param($s) $s.users[0].cimProfile = $true })).Count -eq 0 } finally { $script:GatesOff = @() } }

# the identity checks the helpers run just before they act
$u1 = $rs.Users[0]
Test-CheapCase 'identity: an account whose SID is not the recorded one is refused, the recorded one passes' { $m = try { Assert-UserIdentity $u1 'S-1-5-21-9-9-9-9' $u1.Name; '' } catch { $_.Exception.Message }; $null = Assert-UserIdentity $u1 $u1.Sid $u1.Name; $m -like 'REFUSED`[sid-match`]*' }
Test-CheapCase 'identity: an account with any profile evidence is refused, a clean one passes' {
    $bad = 0
    foreach ($st in @(@{ profileListEntry = $true; cimProfile = $false; profileFolders = @() }, @{ profileListEntry = $false; cimProfile = $true; profileFolders = @() }, @{ profileListEntry = $false; cimProfile = $false; profileFolders = @('C:\x') })) {
        $m = try { Assert-NoProfile $st $u1.Name; '' } catch { $_.Exception.Message }; if ($m -notlike 'REFUSED`[no-profile`]*') { $bad++ }
    }
    $okM = try { Assert-NoProfile @{ profileListEntry = $false; cimProfile = $false; profileFolders = @() } $u1.Name; '' } catch { $_.Exception.Message }
    ($bad -eq 0) -and ($okM -eq '') }
Test-CheapCase 'identity: a group with another SID is refused' { $m = try { Assert-GroupIdentity $rs.Group 'S-1-5-21-9-9-9-9' $rs.Group.Name; '' } catch { $_.Exception.Message }; $null = Assert-GroupIdentity $rs.Group $rs.Group.Sid $rs.Group.Name; $m -like 'REFUSED`[sid-match`]*' }
Test-CheapCase 'identity: a group with a member that is not on the allowlist or that cannot be read is refused' { $al = @($rs.Users | ForEach-Object { $_.Sid }); $m1 = try { Assert-GroupMembers @($al[0], 'S-1-5-21-9-9-9-5') $al $rs.Group.Name; '' } catch { $_.Exception.Message }; $m2 = try { Assert-GroupMembers @('unreadable') $al $rs.Group.Name; '' } catch { $_.Exception.Message }; $null = Assert-GroupMembers $al $al $rs.Group.Name; $null = Assert-GroupMembers @() $al $rs.Group.Name; ($m1 -like 'REFUSED`[group-members`]*') -and ($m2 -like 'REFUSED`[group-members`]*') }
$fe = $rs.Firewall[0]
$liveRule = [pscustomobject]@{ Name = $fe.Name }
Test-CheapCase 'identity: a rule that is not exactly one, has another id or another scope is refused; the pinned one passes' {
    $m1 = try { Assert-FirewallIdentity $fe @($liveRule, $liveRule) "O:LSD:(A;;CC;;;$($fe.UserSid))" $fe.DisplayName; '' } catch { $_.Exception.Message }
    $m2 = try { Assert-FirewallIdentity $fe @([pscustomobject]@{ Name = '{other}' }) "O:LSD:(A;;CC;;;$($fe.UserSid))" $fe.DisplayName; '' } catch { $_.Exception.Message }
    $m3 = try { Assert-FirewallIdentity $fe @($liveRule) "O:LSD:(A;;CC;;;$($fe.UserSid))(A;;CC;;;WD)" $fe.DisplayName; '' } catch { $_.Exception.Message }
    $m4 = try { Assert-FirewallIdentity $fe @() '' $fe.DisplayName; '' } catch { $_.Exception.Message }
    $null = Assert-FirewallIdentity $fe @($liveRule) "O:LSD:(A;;CC;;;$($fe.UserSid))" $fe.DisplayName
    (@($m1, $m2, $m3, $m4) | Where-Object { $_ -like 'REFUSED`[fw-identity`]*' }).Count -eq 4 }
Test-CheapCase 'identity: a registry value that is not the recorded DWORD 0 is refused' { $m1 = try { Assert-RegistryShape 'String' '1' 'CodexSandboxOffline'; '' } catch { $_.Exception.Message }; $m2 = try { Assert-RegistryShape 'DWord' 1 'CodexSandboxOffline'; '' } catch { $_.Exception.Message }; $null = Assert-RegistryShape 'DWord' 0 'CodexSandboxOffline'; ($m1 -like 'REFUSED`[reg-value-shape`]*') -and ($m2 -like 'REFUSED`[reg-value-shape`]*') }
Test-CheapCase 'identity: a wildcard in a name is refused' { $m = try { Assert-NoWildcard 'Codex*' 'account name'; '' } catch { $_.Exception.Message }; $m -like 'REFUSED`[spec-wildcard`]*' }

# the plan, the step check, the verdict and the verify report
$planClean = @(Get-Plan $rs $clean 'Accounts')
Test-CheapCase 'plan: every pinned object is a step - 2 disables, 2 rules, 2 values, 2 accounts, 1 group - and disabling comes first' { ($planClean.Count -eq 9) -and ((($planClean | ForEach-Object { $_.kind }) -join ',') -ceq 'disable,disable,firewall,firewall,registry,registry,user,user,group') -and (@($planClean | Where-Object { $_.kind -ceq 'user' -or $_.kind -ceq 'group' }).Count -eq 3) }
Test-CheapCase 'plan: a step is present only while its object is (an account already disabled needs no disabling)' {
    $gone = & $mutateState { param($s) $s.users[0].exists = $false; $s.users[1].enabled = $true; $s.group.exists = $false; $s.firewall[0].count = 0; $s.registry.targets['CodexSandboxOffline'] = $null }
    $p = @(Get-Plan $rs $gone 'Accounts')
    (-not ($p | Where-Object { $_.id -ceq 'D1' }).present) -and ($p | Where-Object { $_.id -ceq 'D2' }).present -and (-not ($p | Where-Object { $_.kind -ceq 'user' -and $_.target -ceq $rs.Users[0].Name }).present) -and (($p | Where-Object { $_.kind -ceq 'user' -and $_.target -ceq $rs.Users[1].Name }).present) -and (-not ($p | Where-Object { $_.kind -ceq 'group' }).present) -and (-not ($p | Where-Object { $_.id -ceq 'A5' }).present) -and (($p | Where-Object { $_.id -ceq 'A6' }).present) -and (-not (@($p | Where-Object { $_.kind -ceq 'registry' })[0]).present) -and ((@($p | Where-Object { $_.kind -ceq 'registry' })[1]).present) }
Test-CheapCase 'plan digest: changes when any step state changes, when a step is added, and when the stage changes' { $d0 = Get-PlanDigest $rs $planClean 'Accounts'; $st2 = & $mutateState { param($s) $s.firewall[0].enabled = 'False' }; ($d0 -cne (Get-PlanDigest $rs @(Get-Plan $rs $st2 'Accounts') 'Accounts')) -and ($d0 -cne (Get-PlanDigest $rs $planClean 'All')) -and ($d0 -cne (Get-PlanDigest $rs ($planClean | Select-Object -First 8) 'Accounts')) -and ($d0 -ceq (Get-PlanDigest $rs $planClean 'accounts')) }
Test-CheapCase 'step check: each kind reads absent only when its object is absent, and an unknown kind is never absent' {
    $sa = & $mutateState { param($s) $s.users[0].exists = $false; $s.users[1].enabled = $false; $s.group.exists = $false; $s.firewall[0].count = 0; $s.registry.targets['CodexSandboxOffline'] = $null }
    $stp = @(Get-Plan $rs $sa 'Accounts')
    $abs = { param($id, $kind) Get-StepAbsent $rs $sa ($stp | Where-Object { $_.id -ceq $id -and ($null -eq $kind -or $_.kind -ceq $kind) } | Select-Object -First 1) }
    $pre = @(Get-Plan $rs $clean 'Accounts')
    (& $abs 'D1' 'disable') -and (& $abs 'D2' 'disable') -and (& $abs 'A5' 'firewall') -and (-not (& $abs 'A6' 'firewall')) -and (& $abs 'A3' 'group') -and (-not (Get-StepAbsent $rs $clean ($pre | Where-Object { $_.id -ceq 'A3' }))) -and (-not (Get-StepAbsent $rs $clean ($pre | Where-Object { $_.kind -ceq 'user' } | Select-Object -First 1))) -and (-not (Get-StepAbsent $rs $clean ($pre | Where-Object { $_.kind -ceq 'registry' } | Select-Object -First 1))) -and (-not (Get-StepAbsent $rs $clean @{ kind = 'mystery'; id = 'X'; target = 'x' })) }
Test-CheapCase 'verdict: an apply passes only with exit 0, nothing left and nothing uncertified' { (Get-ApplyVerdict 0 @() @()) -and -not (Get-ApplyVerdict 0 @('[A1] user') @()) -and -not (Get-ApplyVerdict 0 @() @('cut short')) -and -not (Get-ApplyVerdict 1 @() @()) -and -not (Get-ApplyVerdict 3 @() @()) }
Test-CheapCase 'verify: present steps, findings, scan problems and an empty plan are each a problem; an all-absent plan with nothing else is none' {
    $absentPlan = @($planClean | ForEach-Object { $c = [ordered]@{}; foreach ($k in $_.Keys) { $c[$k] = $_[$k] }; $c.present = $false; $c })
    $okScan = [ordered]@{ root = 'x'; hits = 0; firstHits = @(); foldersLeftUnscanned = 0; unreadable = 0; scanned = 5 }
    $hitScan = [ordered]@{ root = 'x'; hits = 1; firstHits = @('p'); foldersLeftUnscanned = 0; unreadable = 0; scanned = 5 }
    (@(Get-VerifyProblems $absentPlan @() @($okScan) 'All').Count -eq 0) -and (@(Get-VerifyProblems $planClean @() @() 'Accounts').Count -eq 7) -and (@(Get-VerifyProblems $absentPlan @('a finding') @() 'Accounts').Count -eq 1) -and (@(Get-VerifyProblems $absentPlan @() @($hitScan) 'All').Count -eq 1) -and (@(Get-VerifyProblems @() @() @() 'AclEntries').Count -eq 1) }
Test-CheapCase 'verify: a plan that is null (a stage with no steps returns nothing) is also an empty plan, not a PASS' { @(Get-VerifyProblems $null @() @() 'AclEntries').Count -eq 1 }
Test-CheapCase 'extra rules: only rules that match the glob and are not the pinned ones are listed' { $rules = @([pscustomobject]@{ Name = $rs.Firewall[0].Name; DisplayName = $rs.Firewall[0].DisplayName }, [pscustomobject]@{ Name = '{stray}'; DisplayName = 'codex_stray' }); $x = @(Get-ExtraRuleNames $rs $rules); ($x.Count -eq 1) -and ($x[0] -like 'codex_stray*') }
Test-CheapCase 'extra rules: no rules at all (nothing found, null or empty) lists nothing' { (@(Get-ExtraRuleNames $rs $null).Count -eq 0) -and (@(Get-ExtraRuleNames $rs @()).Count -eq 0) }
Test-CheapCase 'exports: only a recognisable file is usable' { (Test-WfpExportUsable '<?xml?><wfpdiag><filters>') -and -not (Test-WfpExportUsable $null) -and -not (Test-WfpExportUsable 'not a dump') -and (Test-RightsExportUsable "[Unicode]`n[Privilege Rights]`nSeX = *S-1-1-0") -and -not (Test-RightsExportUsable $null) -and -not (Test-RightsExportUsable 'nothing') }

# the readers: a failed read is never "gone", and the checks that cannot run are said so
Test-CheapCase 'heavy (no administrator): not checked, and a service or task list that cannot be read is named' {
    function global:Get-Service { throw [UnauthorizedAccessException]::new('denied svc') }
    function global:Get-ScheduledTask { throw [UnauthorizedAccessException]::new('denied task') }
    try { $h = Get-HeavyState $rs $false } finally { Remove-Item Function:\Get-Service, Function:\Get-ScheduledTask -ErrorAction SilentlyContinue }
    (-not $h.checked) -and (@($h.notRun | Where-Object { $_ -like 'services (*denied svc*' }).Count -eq 1) -and (@($h.notRun | Where-Object { $_ -like 'scheduled tasks (*denied task*' }).Count -eq 1) -and (@($h.notRun | Where-Object { $_ -like '*needs administrator*' }).Count -eq 1) }
Test-CheapCase 'heavy: a service that runs as a pinned account, and a task run by their SID or by the pinned group, are found' {
    function global:Get-Service { @() }
    function global:Get-CimInstance { [CmdletBinding()] param($ClassName) [pscustomobject]@{ Name = 'strangesvc'; StartName = '.\CodexSandboxOnline' }; [pscustomobject]@{ Name = 'fine'; StartName = 'LocalSystem' } }
    function global:Get-ScheduledTask { [pscustomobject]@{ TaskName = 'a'; TaskPath = '\'; Principal = [pscustomobject]@{ UserId = $rs.Users[0].Sid; GroupId = '' } }; [pscustomobject]@{ TaskName = 'b'; TaskPath = '\'; Principal = [pscustomobject]@{ UserId = ''; GroupId = 'CodexSandboxUsers' } }; [pscustomobject]@{ TaskName = 'c'; TaskPath = '\'; Principal = [pscustomobject]@{ UserId = 'SYSTEM'; GroupId = '' } } }
    try { $h = Get-HeavyState $rs $false } finally { Remove-Item Function:\Get-Service, Function:\Get-CimInstance, Function:\Get-ScheduledTask -ErrorAction SilentlyContinue }
    (@($h.services | Where-Object { $_ -like 'strangesvc*CodexSandboxOnline*' }).Count -eq 1) -and ($h.services.Count -eq 1) -and ($h.tasks.Count -eq 2) -and (@($h.tasks | Where-Object { $_ -like '*c' }).Count -eq 0) }
Test-CheapCase 'readers: a group that cannot be found reads as unreadable members, never as none' { (Get-GroupMemberSids 'zz1740-chp9-no-such-group') -ccontains 'unreadable' }
$profRoot = "C:\blarai-spike-1740-ops\zz1740-chp9-prof-$([guid]::NewGuid().ToString('N').Substring(0, 6))"
try {
    New-Item -ItemType Directory "$profRoot\profiles\zz1740-chp9-acct-1" -Force | Out-Null
    $plKey = 'HKCU:\Software\zz1740-chp9-pl'; New-Item -Path "$plKey\S-1-5-21-5-5-5-5" -Force | Out-Null
    $specP = [ordered]@{ ProfileListRoot = $plKey; ProfileFolderRoot = "$profRoot\profiles" }
    Test-CheapCase 'readers: an account state sees a profile folder of that name, a ProfileList key of its SID and a profile record of its SID' {
        $s1 = Get-UserState $specP ([ordered]@{ Name = 'zz1740-chp9-acct-1'; Sid = 'S-1-5-21-5-5-5-5' }) @([pscustomobject]@{ SID = 'S-1-5-21-5-5-5-5' })
        $s2 = Get-UserState $specP ([ordered]@{ Name = 'zz1740-chp9-acct-2'; Sid = 'S-1-5-21-6-6-6-6' }) @()
        ($s1.profileFolders.Count -eq 1) -and $s1.profileListEntry -and $s1.cimProfile -and -not $s1.exists -and ($s2.profileFolders.Count -eq 0) -and -not $s2.profileListEntry -and -not $s2.cimProfile }
} finally { Remove-CheapTree $profRoot; Remove-Item -LiteralPath 'HKCU:\Software\zz1740-chp9-pl' -Recurse -Force -ErrorAction SilentlyContinue }
Test-CheapCase 'hash: the same text with Windows or Unix line endings gives one value, other text another' {
    $tmpH = Join-Path ([IO.Path]::GetTempPath()) "zz1740-chp9-hash-$([guid]::NewGuid().ToString('N').Substring(0, 6))"
    New-Item -ItemType Directory $tmpH | Out-Null
    try {
        [IO.File]::WriteAllBytes("$tmpH\a.txt", [Text.Encoding]::ASCII.GetBytes("one`r`ntwo`r`n")); [IO.File]::WriteAllBytes("$tmpH\b.txt", [Text.Encoding]::ASCII.GetBytes("one`ntwo`n")); [IO.File]::WriteAllBytes("$tmpH\c.txt", [Text.Encoding]::ASCII.GetBytes("one`ntwo!`n"))
        $ha = Get-NormalisedSha256 "$tmpH\a.txt"; ($ha -ceq (Get-NormalisedSha256 "$tmpH\b.txt")) -and ($ha -cne (Get-NormalisedSha256 "$tmpH\c.txt")) -and ($ha.Length -eq 64)
    } finally { Remove-Item -LiteralPath $tmpH -Recurse -Force }
}
Test-CheapCase 'restore: refused on the real spec (until the access-entry stage is reviewed), before anything is read' { $m = try { $null = Invoke-RestoreAcl $rs 'C:\nowhere' '' $true; '' } catch { $_.Exception.Message }; $m -like 'REFUSED`[restore-real-blocked`]*' }

# ---------------------------------------------------------------- earlier unfinished runs
$bkRoot = "C:\blarai-spike-1740-ops\zz1740-chp9-bk-$([guid]::NewGuid().ToString('N').Substring(0, 6))"
$spec0 = [ordered]@{ Mode = 'test'; Marker = 'cheap' }
$dig = Get-SpecDigest $spec0
try {
    New-Item -ItemType Directory $bkRoot -Force | Out-Null
    $mk = { param($name, $report, $meta, $resolved, $digest) $d = Join-Path $bkRoot $name; New-Item -ItemType Directory $d | Out-Null
        ([ordered]@{ specDigest = $digest; stage = 'All' } | ConvertTo-Json) | Set-Content "$d\backup.json"
        if ($meta) { '{}' | Set-Content "$d\tree-snapshot.tsv.meta.json" }
        if ($report) { ([ordered]@{ verdict = $report } | ConvertTo-Json) | Set-Content "$d\report.json" }
        if ($resolved) { 'x' | Set-Content "$d\resolved.txt" } }
    & $mk 'remove-codex-1-unfinished' $null $true $false $dig
    & $mk 'remove-codex-2-failed' 'FAIL' $true $false $dig
    & $mk 'remove-codex-3-passed' 'PASS' $true $false $dig
    & $mk 'remove-codex-4-resolved' 'FAIL' $true $true $dig
    & $mk 'remove-codex-5-no-snapshot' $null $false $false $dig
    & $mk 'remove-codex-6-other-spec' $null $true $false 'deadbeef'
    $inc = @(Get-IncompleteRuns $spec0 $bkRoot | ForEach-Object { Split-Path -Leaf $_ })
    Test-CheapCase 'resume: an earlier run without a clean PASS report that got as far as a snapshot is unfinished; passed, resolved, snapshot-less and other-spec runs are not' { ($inc -join ',') -ceq 'remove-codex-1-unfinished,remove-codex-2-failed' }
    Test-CheapCase 'resume: without -ResumeFrom an unfinished run refuses the next apply' { $m = try { $null = Resolve-ResumeBaseline $spec0 $bkRoot ''; '' } catch { $_.Exception.Message }; $m -like 'REFUSED`[resume-required`]*' }
    Test-CheapCase 'resume: a folder that is not one of the unfinished runs is refused as the target' { $m = try { $null = Resolve-ResumeBaseline $spec0 $bkRoot "$bkRoot\remove-codex-3-passed"; '' } catch { $_.Exception.Message }; $m -like 'REFUSED`[resume-target`]*' }
} finally { Remove-CheapTree $bkRoot }

# ---------------------------------------------------------------- a tiny tree: the object's own list is edited, nothing else
$root = "C:\blarai-spike-1740-ops\zz1740-chp9-$([guid]::NewGuid().ToString('N').Substring(0, 6))"
$script:Own = 'zz1740-chp9-'
try {
    New-Item -ItemType Directory "$root\t\sub", "$root\victim", "$root\profiles", "$root\dotcodex" -Force | Out-Null
    'a' | Set-Content "$root\t\a.txt"; 'b' | Set-Content "$root\t\sub\b.txt"; 'v' | Set-Content "$root\victim\f2.txt"
    $addAce = { param($p, $sid, $inh) $a = Get-Acl -LiteralPath $p; $a.AddAccessRule([Security.AccessControl.FileSystemAccessRule]::new([Security.Principal.SecurityIdentifier]$sid, [Security.AccessControl.FileSystemRights]0x1201bf, $inh, 'None', 'Allow')); Set-Acl -LiteralPath $p -AclObject $a }
    & $addAce "$root\t" $fake 'ContainerInherit,ObjectInherit'
    & $addAce "$root\t" $other 'ContainerInherit,ObjectInherit'
    & $addAce "$root\victim\f2.txt" $fake 'None'
    $spec = [ordered]@{
        Mode = 'test'; Users = @(); Group = [ordered]@{ Name = 'zz1740-chp9-g'; Sid = 'S-1-5-21-9-9-9-9'; Description = 'x' }; Firewall = @()
        FirewallGlob = 'zz1740-chp9'; ServiceGlob = 'zz1740-chp9'; Registry = [ordered]@{ Path = 'HKCU:\Software\zz1740-chp9\UserList'; Names = @() }
        ProfileListRoot = 'HKCU:\Software\zz1740-chp9\PL'; ProfileFolderRoot = "$root\profiles"; WfpNeedles = @(); ExtraScanSids = @()
        AclTargets = @([ordered]@{ Id = 'A7'; Path = "$root\t"; Sid = $fake; Scan = $true }); ReportOnly = "$root\dotcodex"
    }
    $readNow = { param($p) $ext = '\\?\' + $p; $acl = if ([IO.Directory]::Exists($ext)) { [IO.FileSystemAclExtensions]::GetAccessControl([IO.DirectoryInfo]::new($ext), [Security.AccessControl.AccessControlSections]::Access) } else { [IO.FileSystemAclExtensions]::GetAccessControl([IO.FileInfo]::new($ext), [Security.AccessControl.AccessControlSections]::Access) }; $acl.GetSecurityDescriptorSddlForm('Access') }
    $paths = @("$root\t", "$root\t\a.txt", "$root\t\sub", "$root\t\sub\b.txt")
    $before = @{}; foreach ($p in $paths) { $before[$p] = & $readNow $p }
    Test-CheapCase 'tree: before the change every object of the tree carries the Codex entry' { @($paths | Where-Object { $before[$_].Contains($fake) }).Count -eq 4 }
    $coll = [System.Collections.Generic.Dictionary[string, string]]::new([StringComparer]::OrdinalIgnoreCase)
    $scan0 = Find-SidAcesDeep "$root\t" @($fake) 60 $null $null @() ([ordered]@{ Purge = @($fake); Exempt = @{ "$root\t|$fake" = $true } }) $coll
    Test-CheapCase 'tree: the pre-change scan sees all objects, keeps them in memory, and finds nothing to refuse' { ($scan0.scanned -eq 4) -and ($coll.Count -eq 4) -and ($scan0.explicitCodex.Count -eq 0) -and ($scan0.emptyAfter.Count -eq 0) -and ($scan0.unreadable -eq 0) }
    $res = Remove-SidAcesTree $spec "$root\t" 60
    Test-CheapCase 'tree: the walk changed every object and reports it' { ($res.changed -eq 4) -and ($res.problems.Count -eq 0) }
    Test-CheapCase 'tree: every object now holds exactly its before-change list minus the Codex entry (order, flags and protection kept)' { $bad = 0; foreach ($p in $paths) { if ((& $readNow $p) -cne (Remove-SidsFromSddl $before[$p] @($fake))) { $bad++ } }; $bad -eq 0 }
    Test-CheapCase 'tree: the other principal keeps its entry on every object (nothing was re-derived)' { @($paths | Where-Object { (& $readNow $_).Contains($other) }).Count -eq 4 }
    $scan1 = Find-SidAcesDeep "$root\t" @($fake) 60 $null $coll @($fake)
    Test-CheapCase 'read-back: after a clean removal nothing differs and the cheap comparison covers everything' { ($scan1.hits -eq 0) -and ($scan1.collateral.Count -eq 0) -and ($scan1.fastCompared -eq 4) -and ($scan1.slowCompared -eq 0) -and ($scan1.missingNow -eq 0) }
    & $addAce "$root\t\sub\b.txt" 'S-1-5-21-1111111111-2222222222-3333333333-4009' 'None'
    $scan2 = Find-SidAcesDeep "$root\t" @($fake) 60 $null $coll @($fake)
    Test-CheapCase 'read-back: an entry gained by another principal afterwards is reported as a difference' { ($scan2.collateral.Count -eq 1) -and ($scan2.collateral[0] -like '*b.txt*gained=*4009*') }
    # a folder swapped for a link after the snapshot: the write must not reach the object outside the tree
    New-Item -ItemType Directory "$root\t\par" | Out-Null; 'x' | Set-Content "$root\t\par\f2.txt"
    $script:WalkHook = { param($path) if ($path -like '*\t\par\f2.txt') { Rename-Item "$root\t\par" 'par_real'; New-Item -ItemType Junction -Path "$root\t\par" -Target "$root\victim" | Out-Null } }
    & $addAce "$root\t" $fake 'ContainerInherit,ObjectInherit'
    $m = try { $null = Remove-SidAcesTree $spec "$root\t" 60; '' } catch { $_.Exception.Message }
    $script:WalkHook = $null
    Test-CheapCase 'handle: a folder swapped for a link after the snapshot is refused and the object outside the tree is untouched' { ($m -like '*resolves to*') -and ((& $readNow "$root\victim\f2.txt").Contains($fake)) }
    [IO.Directory]::Delete("$root\t\par")
    # a file with a second name shares one list with the other name
    & $addAce "$root\t" $fake 'ContainerInherit,ObjectInherit'
    'x' | Set-Content "$root\t\orig.txt"; New-Item -ItemType HardLink -Path "$root\victim\hl.txt" -Target "$root\t\orig.txt" | Out-Null
    $m2 = try { $null = Remove-SidAcesTree $spec "$root\t" 60; '' } catch { $_.Exception.Message }
    Test-CheapCase 'handle: a file with a second name is refused and its shared list is untouched' { ($m2 -like '*hard link*') -and ((& $readNow "$root\victim\hl.txt").Contains($fake)) }
    Remove-Item -LiteralPath "$root\victim\hl.txt", "$root\t\orig.txt" -Force
    # two names that are both inside the allowlisted folder are one object inside it: allowed
    & $addAce "$root\t" $fake 'ContainerInherit,ObjectInherit'
    'x' | Set-Content "$root\t\in1.txt"; New-Item -ItemType HardLink -Path "$root\t\sub\in2.txt" -Target "$root\t\in1.txt" | Out-Null
    $m2b = try { $null = Remove-SidAcesTree $spec "$root\t" 60; '' } catch { $_.Exception.Message }
    Test-CheapCase 'handle: a file whose every name is inside the allowlisted folder is changed once and both names agree' { ($m2b -eq '') -and -not (& $readNow "$root\t\in1.txt").Contains($fake) -and ((& $readNow "$root\t\in1.txt") -ceq (& $readNow "$root\t\sub\in2.txt")) }
    Remove-Item -LiteralPath "$root\t\sub\in2.txt", "$root\t\in1.txt" -Force
    # LA decision 2026-10-11: other names of a hard-linked file may live under a pinned link folder (its subtree only)
    & $addAce "$root\t" $fake 'ContainerInherit,ObjectInherit'
    'x' | Set-Content "$root\t\lr1.txt"; 'y' | Set-Content "$root\t\lr2.txt"; 'z' | Set-Content "$root\t\lr3.txt"
    New-Item -ItemType Directory "$root\linkroot\sub", "$root\linkroot-x" | Out-Null
    New-Item -ItemType HardLink -Path "$root\linkroot\sub\h1.txt" -Target "$root\t\lr1.txt" | Out-Null
    New-Item -ItemType HardLink -Path "$root\linkroot-x\h2.txt" -Target "$root\t\lr2.txt" | Out-Null
    New-Item -ItemType HardLink -Path "$root\linkroot\sub\h3.txt" -Target "$root\t\lr3.txt" | Out-Null
    $specL = [ordered]@{}; foreach ($k in $spec.Keys) { $specL[$k] = $spec[$k] }; $specL.LinkRoots = @("$root\linkroot")
    $lr1 = Remove-ObjectSids "$root\t\lr1.txt" @($fake) (Get-LinkNameRoots $specL)
    Test-CheapCase 'link roots: a name inside the approved link folder is allowed, the shared list is edited once and both names agree' { ($lr1 -ceq 'changed') -and ((& $readNow "$root\t\lr1.txt") -ceq (& $readNow "$root\linkroot\sub\h1.txt")) -and -not (& $readNow "$root\linkroot\sub\h1.txt").Contains($fake) }
    $lr2 = Remove-ObjectSids "$root\t\lr2.txt" @($fake) (Get-LinkNameRoots $specL)
    Test-CheapCase 'link roots: a look-alike sibling folder is outside the approved one, refused, list untouched' { ($lr2 -like 'refused*outside*') -and (& $readNow "$root\linkroot-x\h2.txt").Contains($fake) }
    $lr3a = Remove-ObjectSids "$root\t\lr3.txt" @($fake) (Get-LinkNameRoots $spec)
    Test-CheapCase 'link roots: without an approved folder the same name is refused' { ($lr3a -like 'refused*outside*') -and (& $readNow "$root\linkroot\sub\h3.txt").Contains($fake) }
    Test-CheapCase 'link roots: toggle off, the approved folder is not honoured' { $script:GatesOff = @('link-roots'); try { $lr3b = Remove-ObjectSids "$root\t\lr3.txt" @($fake) (Get-LinkNameRoots $specL); $cnt = @(Get-LinkNameRoots $specL).Count } finally { $script:GatesOff = @() }; ($lr3b -like 'refused*outside*') -and ($cnt -eq 1) }
    Test-CheapCase 'link roots: the real spec pins exactly one folder, in the allowed list only with the lock on' { $rs2 = Get-RealSpec; ($rs2.LinkRoots.Count -eq 1) -and (@(Get-LinkNameRoots $rs2) -contains $rs2.LinkRoots[0]) -and (@(Get-LinkNameRoots $rs2).Count -eq 5) }
    Remove-Item -LiteralPath "$root\linkroot", "$root\linkroot-x" -Recurse -Force; Remove-Item -LiteralPath "$root\t\lr1.txt", "$root\t\lr2.txt", "$root\t\lr3.txt" -Force
    # a list that holds only the Codex entry would be left empty
    'x' | Set-Content "$root\t\only.txt"; Initialize-OpNative
    $h = [OpAcl]::Open("$root\t\only.txt"); try { [OpAcl]::SetSddl($h, (ConvertTo-WritableSddl "D:AI(A;ID;FA;;;$fake)")) } finally { $h.Dispose() }
    $m3 = try { $null = Remove-SidAcesTree $spec "$root\t" 60; '' } catch { $_.Exception.Message }
    Test-CheapCase 'empty-after: an object whose list would be left empty is refused and keeps its list' { ($m3 -like '*empty access list*') -and ((& $readNow "$root\t\only.txt").Contains($fake)) }
    $sc3 = Find-SidAcesDeep "$root\t" @($fake) 60 $null $null @() ([ordered]@{ Purge = @($fake); Exempt = @{ "$root\t|$fake" = $true } })
    Test-CheapCase 'empty-after: the pre-change scan names that object' { ($sc3.emptyAfter.Count -eq 1) -and ($sc3.emptyAfter[0] -like '*only.txt') }
    $h = [OpAcl]::Open("$root\t\only.txt"); try { [OpAcl]::SetSddl($h, (ConvertTo-WritableSddl 'D:AI(A;;FA;;;BA)')) } finally { $h.Dispose() }
    # the folder being purged may carry the Codex entry itself, nothing below it may
    & $addAce "$root\t\sub" $fake 'None'
    $sc4 = Find-SidAcesDeep "$root\t" @($fake) 60 $null $null @() ([ordered]@{ Purge = @($fake); Exempt = @{ "$root\t|$fake" = $true } })
    Test-CheapCase 'codex-below-root: an explicit Codex entry on an object below the purged folder is found' { ($sc4.explicitCodex.Count -ge 1) -and ($sc4.explicitCodex[0] -like '*\sub*') }
    # a write that silently did not take effect must be caught by the read-back
    & $addAce "$root\t" $fake 'ContainerInherit,ObjectInherit'
    'x' | Set-Content "$root\t\wf.txt"
    $script:WriteFault = $true
    $mw = try { $null = Remove-SidAcesTree $spec "$root\t" 60; '' } catch { $_.Exception.Message }
    $script:WriteFault = $null
    Test-CheapCase 'write: a write that did not take effect is caught by the read-back' { $mw -like '*read back*' }
    # protected folders for backups
    $open = "$root\openbackup"; New-Item -ItemType Directory $open | Out-Null
    Test-CheapCase 'backup folder: an ordinary inheriting folder is refused' { $m5 = try { Assert-AdminOnlyDirectory $open; '' } catch { $_.Exception.Message }; $m5 -like 'REFUSED`[backup-dir-secure`]*' }
} finally { Remove-CheapTree $root }
$results | ConvertTo-Json -Compress -AsArray
