#requires -Version 5.1
<#
.SYNOPSIS
  Runs ONE bundled arm script elevated, once, through a Scheduled Task that unregisters itself: the task is registered
  with RunLevel Highest (interactive logon of the current user, so the operator's session exists for the scripts that
  need it), started, runs the script with its output written to a log, optionally runs a follow-up script whatever the
  first one did, and as its LAST act deletes its own registration.

.DESCRIPTION
  Modes (exactly one):
    -SelfTest  pure helpers and the inner runner with fakes. Registers nothing, starts nothing, touches no WFP object.
    -DryRun    (alias -WhatIf) prints the exact task definition and command lines. Registers and starts nothing.
    (default)  register + start (needs an elevated session to register a Highest task) and return; the inner process
               does the work. Follow the log named by -LogPath.
    -Inner     the task's own entry point. Not for hand use.

  Only scripts that sit in this script's own folder AND are on the allowlist below can be run, and every argument must
  be made of plain characters (no quotes, no shell metacharacters), so the wrapper is not a generic elevated launcher.
  The task's execution time limit is -TimeLimitMinutes (default 240); the follow-up runs inside the same task.
  FOLDER RULE. The task runs with the highest privileges, as the operator, from this script's own folder. Anything that can change a file in that
  folder (or replace the folder) can therefore run code elevated. So this wrapper refuses to register, and its inner process refuses to run, unless
  only SYSTEM, Administrators and TrustedInstaller can write to the folder, to every file in it, and to nothing above it that lets the folder be replaced
  (Test-AdminOnlyFolder; deny rules are not credited). Put the scripts in an administrator-only folder (for example under C:\ProgramData\BlarAI) and run them there.
  The registration is deleted last; if the inner process is killed the task stays registered (look with
  Get-ScheduledTask -TaskPath '\BlarAI\' and remove it with Unregister-ScheduledTask).
#>
[CmdletBinding()]
param(
    [switch]$SelfTest,
    [Alias('WhatIf')][switch]$DryRun,
    [switch]$Inner,
    [string]$Name,
    [string]$Script,
    [string[]]$ScriptArgs = @(),
    [string]$ThenScript,
    [string[]]$ThenArgs = @(),
    [string]$ArgsB64,
    [string]$LogPath,
    [ValidateSet('powershell', 'pwsh')][string]$HostExe = 'powershell',
    [ValidateRange(10, 1440)][int]$TimeLimitMinutes = 240,
    [string]$TaskPath = '\BlarAI\'
)
$ErrorActionPreference = 'Stop'

$script:Allowlist = @('spike-wfp.ps1', 'spike-wfp-persist.ps1', 'spike-arm3b-arm.ps1')

# ---- admin-only folder check (SYSTEM and elevated tasks run scripts from a folder; nobody but administrators may be able to change it) ----
# Rights that let a principal change what a file or folder contains, who may use it, or who owns it (FileSystemRights bits).
$script:WriteRightsMask = 0x2 -bor 0x4 -bor 0x10 -bor 0x40 -bor 0x100 -bor 0x10000 -bor 0x40000 -bor 0x80000 -bor 0x40000000 -bor 0x10000000
# Rights on an ANCESTOR that let a principal delete or rename it away (and so replace the folder under it), delete children, or change inherited permissions or the owner.
# Create-files and append (add-subfolder) alone are fine on an ancestor: users have them on ProgramData and cannot replace a folder with them.
$script:AncestorRightsMask = 0x40 -bor 0x10000 -bor 0x40000 -bor 0x80000 -bor 0x10000000
$script:TrustedWriterSids = @('S-1-5-18', 'S-1-5-32-544', 'S-1-5-80-956008885-3418522649-1831038044-1853292631-2271478464')   # SYSTEM, Administrators, TrustedInstaller

function Get-NonAdminWriteGrants {
    # PURE. $Rules: objects with Path, Sid, Type (Allow|Deny), Rights (int), Ancestor (bool), InheritOnly (bool). Returns one line per ALLOW rule that gives a
    # principal other than SYSTEM, Administrators and TrustedInstaller a right that can change the content (or, for an ancestor, delete or rename it away), plus a
    # line when the OWNER is not one of those three (an owner can rewrite the permissions). Deny rules are not credited (they can be bypassed by group membership in
    # ways this check cannot see), so they never excuse a grant. Inherit-only rules are skipped: their effect shows in the children's own ACLs, which are read too.
    param($Rules, [string]$OwnerSid, [string]$Path)
    $out = New-Object System.Collections.ArrayList
    if ($OwnerSid -and $script:TrustedWriterSids -notcontains $OwnerSid) { [void]$out.Add("$Path is owned by $OwnerSid (an owner can change its permissions)") }
    foreach ($r in @($Rules)) {
        if ($r.Type -ne 'Allow') { continue }
        if ($r.PSObject.Properties['InheritOnly'] -and $r.InheritOnly) { continue }
        if ($script:TrustedWriterSids -contains [string]$r.Sid) { continue }
        $mask = $(if ($r.Ancestor) { $script:AncestorRightsMask } else { $script:WriteRightsMask })
        $hit = ([int64]$r.Rights -band [int64]$mask)
        if ($hit -ne 0) { [void]$out.Add(("{0}: {1} is allowed rights 0x{2:X} ({3})" -f $r.Path, $r.Sid, [int64]$r.Rights, $(if ($r.Ancestor) { 'on an ancestor' } else { 'on the folder or a file in it' }))) }
    }
    return @($out)
}

function ConvertTo-AclRuleRows {
    # Turns a .NET security object's access rules into the rows Get-NonAdminWriteGrants reads.
    param($Security, [string]$Path, [bool]$Ancestor)
    $rows = @()
    foreach ($ar in $Security.GetAccessRules($true, $true, [Security.Principal.SecurityIdentifier])) {
        $rows += [pscustomobject]@{ Path = $Path; Sid = $ar.IdentityReference.Value; Type = [string]$ar.AccessControlType; Rights = [int64]([int]$ar.FileSystemRights); Ancestor = $Ancestor; InheritOnly = [bool]([int]$ar.PropagationFlags -band 2) }
    }
    return $rows
}

function Get-PathSecurityObject {
    param([string]$Path)
    if (Test-Path -LiteralPath $Path -PathType Container) {
        $di = New-Object IO.DirectoryInfo $Path
        if ($di.PSObject.Methods['GetAccessControl']) { return $di.GetAccessControl() }
        return [IO.FileSystemAclExtensions]::GetAccessControl($di)
    }
    $fi = New-Object IO.FileInfo $Path
    if ($fi.PSObject.Methods['GetAccessControl']) { return $fi.GetAccessControl() }
    return [IO.FileSystemAclExtensions]::GetAccessControl($fi)
}

function Get-PathAttributes {
    # The path's OWN attributes (a link is not followed); $null when unreadable.
    param([string]$Path)
    try { return [IO.File]::GetAttributes($Path) } catch { return $null }
}

function Test-AdminOnlyFolder {
    # READ-ONLY. Ok only when the folder, every file in it and every ancestor give no non-administrator a write-class right (ancestors: delete, rename-away, delete-child,
    # change permissions, take ownership), none of them is owned by a non-administrator, and none of them is a reparse point (junction or symlink). A SYSTEM or elevated task
    # that runs a script from a folder this check fails is a privilege-escalation path for any non-elevated process of the operator. The two providers are injectable so
    # the self-tests can feed fabricated security descriptors and attributes.
    param([Parameter(Mandatory)][string]$Path, [scriptblock]$SecurityProvider = { param($p) Get-PathSecurityObject -Path $p }, [scriptblock]$AttributeProvider = { param($p) Get-PathAttributes -Path $p })
    $problems = New-Object System.Collections.ArrayList; $checked = 0
    $reparse = [int][IO.FileAttributes]::ReparsePoint
    try {
        $full = (Resolve-Path -LiteralPath $Path -ErrorAction Stop).Path
        $items = @($full) + @(Get-ChildItem -LiteralPath $full -Recurse -Force -ErrorAction Stop | ForEach-Object { $_.FullName })
        foreach ($i in $items) {
            $sec = & $SecurityProvider $i; $checked++
            $owner = $null; try { $owner = $sec.GetOwner([Security.Principal.SecurityIdentifier]).Value } catch {}
            foreach ($g in (Get-NonAdminWriteGrants -Rules (ConvertTo-AclRuleRows -Security $sec -Path $i -Ancestor $false) -OwnerSid $owner -Path $i)) { [void]$problems.Add($g) }
            $attr = & $AttributeProvider $i
            if ($null -ne $attr -and (([int]$attr) -band $reparse)) { [void]$problems.Add("$i is a reparse point (junction or symlink)") }
        }
        $parent = Split-Path $full -Parent
        while ($parent) {
            $sec = & $SecurityProvider $parent; $checked++
            $owner = $null; try { $owner = $sec.GetOwner([Security.Principal.SecurityIdentifier]).Value } catch {}
            foreach ($g in (Get-NonAdminWriteGrants -Rules (ConvertTo-AclRuleRows -Security $sec -Path $parent -Ancestor $true) -OwnerSid $owner -Path $parent)) { [void]$problems.Add($g) }
            $attr = & $AttributeProvider $parent
            if ($null -ne $attr -and (([int]$attr) -band $reparse)) { [void]$problems.Add("$parent is a reparse point (junction or symlink)") }
            $next = Split-Path $parent -Parent
            if ($next -eq $parent) { break }
            $parent = $next
        }
    } catch { [void]$problems.Add("the folder's permissions could not be read ($($_.Exception.Message)): treated as not admin-only") }
    return [ordered]@{ Ok = ($problems.Count -eq 0); Problems = @($problems); Checked = $checked; Path = $Path }
}

$script:RestartDecisionFile = 'arm3b-restart-decision.json'
function Test-RestartDecision {
    # READ-ONLY. Arm 3b closes every application WITHOUT forewarning when its restart timer ends (shutdown with a timeout above 0 implies /f). Running it needs the Lead Architect's
    # recorded decision: this file in the script folder (which must be admin-only) with decision = accept-forced-restart, who decided, when (not in the future, not older than
    # $MaxAgeDays) and a reference to where the decision is recorded (for example a comment on #1682). An administrator writes it; nothing in these scripts does.
    param([Parameter(Mandatory)][string]$Folder, [datetimeoffset]$Now = [datetimeoffset]::Now, [int]$MaxAgeDays = 14)
    $p = Join-Path $Folder $script:RestartDecisionFile
    if (-not (Test-Path -LiteralPath $p)) { return [ordered]@{ Ok = $false; Reason = "no recorded decision: $p does not exist (the 3b restart is forced; see DESIGN.md section 7)" } }
    $d = $null
    try { $d = ConvertFrom-Json ([IO.File]::ReadAllText($p)) } catch { return [ordered]@{ Ok = $false; Reason = "the decision file does not parse: $($_.Exception.Message)" } }
    if ([string]$d.decision -ne 'accept-forced-restart') { return [ordered]@{ Ok = $false; Reason = "the decision file does not say decision = accept-forced-restart (it says '$($d.decision)')" } }
    if (-not [string]$d.decided_by) { return [ordered]@{ Ok = $false; Reason = 'the decision file names nobody in decided_by' } }
    if (-not [string]$d.reference) { return [ordered]@{ Ok = $false; Reason = 'the decision file has no reference to where the decision is recorded' } }
    $at = $null
    try { $at = $(if ($d.decided_at -is [datetime]) { [datetimeoffset]$d.decided_at } else { [datetimeoffset]::Parse([string]$d.decided_at) }) } catch { return [ordered]@{ Ok = $false; Reason = 'decided_at is missing or not a date' } }
    $age = ($Now - $at).TotalDays
    if ($age -lt -0.01) { return [ordered]@{ Ok = $false; Reason = 'decided_at is in the future' } }
    if ($age -gt $MaxAgeDays) { return [ordered]@{ Ok = $false; Reason = ("the decision is {0:N1} days old (limit {1}): record it again" -f $age, $MaxAgeDays) } }
    return [ordered]@{ Ok = $true; Reason = "decision recorded by $($d.decided_by) at $($at.ToString('o')) ($($d.reference))" }
}

function Test-TaskNameValid { param([string]$Value) return ($Value -match '^blarai-[A-Za-z0-9-]{3,60}$') }

function Test-ArgPlain {
    # PURE. An argument may contain letters, digits, space, and . _ : \ / - ; nothing a shell would interpret.
    param([string]$Value)
    return ($null -ne $Value -and $Value -match '^[A-Za-z0-9_.:\\/ -]*$' -and $Value.Length -le 260)
}

function ConvertTo-ArgsB64 {
    # PURE. The two argument lists as one base64 token: a value that starts with '-' would be read as a parameter name if it
    # were passed on the task's command line as it is.
    param([string[]]$Target, [string[]]$Then)
    $json = ConvertTo-Json -InputObject ([ordered]@{ target = @($Target); then = @($Then) }) -Compress
    return [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($json))
}

function ConvertFrom-ArgsB64 {
    param([string]$Value)
    if (-not $Value) { return [pscustomobject]@{ Target = @(); Then = @() } }
    $o = ConvertFrom-Json ([Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($Value)))
    return [pscustomobject]@{ Target = @($o.target | Where-Object { $null -ne $_ }); Then = @($o.then | Where-Object { $null -ne $_ }) }
}

function Test-ElevatedTarget {
    # PURE on its arguments. Returns violations (empty = may run): the file is on the allowlist, sits in $Folder itself
    # (not below, not above) and every argument is plain.
    param([string]$ScriptPath, [string[]]$Args2, [string]$Folder)
    $v = New-Object System.Collections.ArrayList
    if (-not $ScriptPath) { [void]$v.Add('no script named'); return @($v) }
    $leaf = Split-Path $ScriptPath -Leaf
    if ($script:Allowlist -notcontains $leaf) { [void]$v.Add("'$leaf' is not one of: " + ($script:Allowlist -join ', ')) }
    $dir = (Split-Path $ScriptPath -Parent)
    if ($ScriptPath -match '\.\.' ) { [void]$v.Add('path contains ..') }
    if ($dir -and $Folder -and (($dir.TrimEnd('\', '/') -replace '/', '\').ToLowerInvariant() -ne ($Folder.TrimEnd('\', '/') -replace '/', '\').ToLowerInvariant())) { [void]$v.Add("'$leaf' is not in this wrapper's own folder") }
    foreach ($a in @($Args2)) { if (-not (Test-ArgPlain $a)) { [void]$v.Add("argument is not plain: '$a'") } }
    # Arm 3b restarts the machine with every application closed WITHOUT forewarning: its arming script is not runnable here without the recorded decision.
    if ($leaf -eq 'spike-arm3b-arm.ps1' -and $Folder) { $dec = Test-RestartDecision -Folder $Folder; if (-not $dec.Ok) { [void]$v.Add("spike-arm3b-arm.ps1 is not runnable: $($dec.Reason)") } }
    return @($v)
}

function ConvertTo-ArgLine {
    # PURE. Joins plain arguments into one command-line string; an argument with a space is double-quoted.
    param([string[]]$Items)
    return (@($Items | ForEach-Object { if ($_ -match '\s') { '"' + $_ + '"' } else { $_ } }) -join ' ')
}

function Get-TaskDefinition {
    # PURE. Everything the registration will contain, as data (printed by -DryRun, asserted by -SelfTest).
    param([string]$Name, [string]$SelfPath, [string]$ScriptPath, [string[]]$Args2, [string]$ThenPath, [string[]]$ThenArgs2, [string]$Log, [string]$HostName, [int]$Minutes, [string]$Path, [string]$User)
    $inner = @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', $SelfPath, '-Inner', '-Name', $Name, '-Script', $ScriptPath, '-LogPath', $Log, '-TaskPath', $Path)
    if ($ThenPath) { $inner += @('-ThenScript', $ThenPath) }
    if (@($Args2).Count -or @($ThenArgs2).Count) { $inner += @('-ArgsB64', (ConvertTo-ArgsB64 -Target $Args2 -Then $ThenArgs2)) }
    return [pscustomobject]@{
        TaskName = $Name; TaskPath = $Path; User = $User; LogonType = 'Interactive'; RunLevel = 'Highest'
        Execute = "$HostName.exe"; Arguments = (ConvertTo-ArgLine $inner); ExecutionTimeLimitMinutes = $Minutes
        MultipleInstances = 'IgnoreNew'; Trigger = 'none (started once by this script)'; UnregistersItself = 'yes, as the last act of the inner process'
        Log = $Log; TargetCommand = "$HostName.exe -NoProfile -ExecutionPolicy Bypass -File `"$ScriptPath`" $(ConvertTo-ArgLine $Args2)".TrimEnd()
        FollowUp = $(if ($ThenPath) { "$HostName.exe -NoProfile -ExecutionPolicy Bypass -File `"$ThenPath`" $(ConvertTo-ArgLine $ThenArgs2)".TrimEnd() } else { $null })
    }
}

function Assert-PlainLogPath {
    # The inner process runs elevated and appends to the log: refuse a log file, folder or ancestor that is a reparse point (junction or symlink), which would send the
    # elevated write somewhere else.
    param([string]$Path)
    $cur = $Path
    while ($cur) {
        $attr = $null; try { $attr = [IO.File]::GetAttributes($cur) } catch {}
        if ($null -ne $attr -and ($attr -band [IO.FileAttributes]::ReparsePoint)) { throw "refusing to write the log: '$cur' is a reparse point (junction or symlink)" }
        $up = Split-Path $cur -Parent
        if ($up -eq $cur) { break }
        $cur = $up
    }
}

function Write-LogLine {
    param([string]$Path, [string]$Text)
    Assert-PlainLogPath -Path $Path
    [IO.File]::AppendAllText($Path, ((Get-Date).ToString("yyyy-MM-dd'T'HH:mm:ss.fffzzz") + ' ' + $Text + "`r`n"), (New-Object Text.UTF8Encoding($false)))
}

function Invoke-InnerRun {
    # The inner process's whole job, with the process runner and the unregistration injected so -SelfTest can drive it
    # with fakes. Order: header, target, follow-up (always), footer, unregister LAST (also when something threw).
    param([string]$Log, [scriptblock]$RunTarget, [scriptblock]$RunThen, [scriptblock]$Unregister)
    $dir = Split-Path $Log -Parent
    if ($dir -and -not (Test-Path -LiteralPath $dir)) { New-Item -ItemType Directory -Force $dir | Out-Null }
    $rc = $null; $rcThen = $null
    try {
        Write-LogLine $Log 'inner run started'
        try { $rc = & $RunTarget } catch { Write-LogLine $Log "target threw: $($_.Exception.Message)"; $rc = -1 }
        Write-LogLine $Log "target exit code: $rc"
        if ($RunThen) {
            try { $rcThen = & $RunThen } catch { Write-LogLine $Log "follow-up threw: $($_.Exception.Message)"; $rcThen = -1 }
            Write-LogLine $Log "follow-up exit code: $rcThen"
        }
    } finally {
        Write-LogLine $Log 'unregistering this task (last act)'
        try { & $Unregister; Write-LogLine $Log 'task unregistered' } catch { Write-LogLine $Log "unregister FAILED: $($_.Exception.Message)" }
    }
    return [pscustomobject]@{ Target = $rc; Then = $rcThen }
}

function Start-LoggedProcess {
    param([string]$HostName, [string]$ScriptPath, [string[]]$Args2, [string]$Log)
    $argList = @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', $ScriptPath) + @($Args2)
    $out = & "$HostName.exe" @argList 2>&1 | ForEach-Object { "$_" }
    $code = $LASTEXITCODE
    foreach ($l in @($out)) { Write-LogLine $Log "| $l" }
    return $code
}

if ($SelfTest) {
    $f = 0
    function Chk([string]$n, [bool]$c) { if ($c) { Write-Host "  [PASS] $n" -ForegroundColor Green } else { Write-Host "  [FAIL] $n" -ForegroundColor Red; $script:f++ } }
    $here = $PSScriptRoot
    Chk 'task names must start with blarai- and be plain' ((Test-TaskNameValid 'blarai-arm2-hold') -and -not (Test-TaskNameValid 'arm2') -and -not (Test-TaskNameValid 'blarai-x;y') -and -not (Test-TaskNameValid 'blarai-'))
    Chk 'plain arguments pass; quotes, ;, &, |, $, backtick, % and newlines are refused' ((Test-ArgPlain '-LongHold') -and (Test-ArgPlain 'C:\a b\c.txt') -and -not (Test-ArgPlain 'a"b') -and -not (Test-ArgPlain 'a;b') -and -not (Test-ArgPlain 'a&b') -and -not (Test-ArgPlain 'a|b') -and -not (Test-ArgPlain 'a$b') -and -not (Test-ArgPlain 'a`b') -and -not (Test-ArgPlain 'a%b') -and -not (Test-ArgPlain "a`nb"))
    Chk 'an allowlisted script in the wrapper folder with plain arguments is accepted' ((Test-ElevatedTarget -ScriptPath (Join-Path $here 'spike-wfp.ps1') -Args2 @('-LongHold', '-HoldSeconds', '3600') -Folder $here).Count -eq 0)
    $dd = Join-Path ([IO.Path]::GetTempPath()) ('wdec-' + [guid]::NewGuid().ToString('N')); New-Item -ItemType Directory -Path $dd | Out-Null
    try {
        $armPath = Join-Path $dd 'spike-arm3b-arm.ps1'
        $noDec = Test-ElevatedTarget -ScriptPath $armPath -Args2 @('-Live') -Folder $dd
        [IO.File]::WriteAllText((Join-Path $dd 'arm3b-restart-decision.json'), (ConvertTo-Json -InputObject ([ordered]@{ decision = 'accept-forced-restart'; decided_by = 'Lead Architect'; decided_at = [datetimeoffset]::Now.AddHours(-1).ToString('o'); reference = '#1682 comment' })))
        $withDec = Test-ElevatedTarget -ScriptPath $armPath -Args2 @('-Live') -Folder $dd
        Chk 'the 3b arming script is NOT runnable through the wrapper without a recorded restart decision, and is with one' (($noDec.Count -ge 1) -and (@($noDec | Where-Object { $_ -match 'not runnable' }).Count -eq 1) -and ($withDec.Count -eq 0))
    } finally { Remove-Item -LiteralPath $dd -Recurse -Force -ErrorAction SilentlyContinue }
    Chk 'a script that is not on the allowlist is refused' ((Test-ElevatedTarget -ScriptPath (Join-Path $here 'Start-ElevatedOnce.ps1') -Args2 @() -Folder $here).Count -ge 1)
    Chk 'an allowlisted name in ANOTHER folder is refused' ((Test-ElevatedTarget -ScriptPath 'C:\elsewhere\spike-wfp.ps1' -Args2 @() -Folder $here).Count -ge 1)
    Chk 'a path with .. is refused; an argument with a shell metacharacter is refused' (((Test-ElevatedTarget -ScriptPath (Join-Path $here '..\spike-wfp.ps1') -Args2 @() -Folder $here).Count -ge 1) -and ((Test-ElevatedTarget -ScriptPath (Join-Path $here 'spike-wfp.ps1') -Args2 @('-LongHold; calc') -Folder $here).Count -ge 1))
    Chk 'no script named is refused' ((Test-ElevatedTarget -ScriptPath '' -Args2 @() -Folder $here).Count -ge 1)
    Chk 'arg line: a value with a space is quoted, plain ones are not' ((ConvertTo-ArgLine @('-WfpScript', 'C:\a b\w.ps1', '-LongHold')) -eq '-WfpScript "C:\a b\w.ps1" -LongHold')
    $def = Get-TaskDefinition -Name 'blarai-arm2-hold' -SelfPath 'C:\x\Start-ElevatedOnce.ps1' -ScriptPath 'C:\x\spike-wfp.ps1' -Args2 @('-LongHold') -ThenPath 'C:\x\spike-wfp.ps1' -ThenArgs2 @('-DryRun') -Log 'C:\l\run.log' -HostName 'powershell' -Minutes 240 -Path '\BlarAI\' -User 'DOM\u'
    $b64 = ConvertTo-ArgsB64 -Target @('-LongHold', '-HoldSeconds', '3600') -Then @('-Remove')
    $back = ConvertFrom-ArgsB64 $b64
    $lt = Join-Path ([IO.Path]::GetTempPath()) ('logpath-' + [guid]::NewGuid().ToString('N')); New-Item -ItemType Directory -Path $lt | Out-Null
    try {
        $okThrew = $false; try { Assert-PlainLogPath -Path (Join-Path $lt 'run.log') } catch { $okThrew = $true }
        $jn = Join-Path $lt 'junction'; $tgt = Join-Path $lt 'target'; New-Item -ItemType Directory -Path $tgt | Out-Null
        $made = $true; try { New-Item -ItemType Junction -Path $jn -Target $tgt | Out-Null } catch { $made = $false }
        $linkThrew = $false; if ($made) { try { Assert-PlainLogPath -Path (Join-Path $jn 'run.log') } catch { $linkThrew = $true } }
        Chk 'log path: an ordinary path passes; a path through a directory junction is refused (the elevated write would land elsewhere)' ((-not $okThrew) -and ((-not $made) -or $linkThrew))
        if ($made) { [IO.Directory]::Delete($jn, $false) }
    } finally { Remove-Item -LiteralPath $lt -Recurse -Force -ErrorAction SilentlyContinue }
    Chk 'arguments round-trip through the base64 token (leading dashes survive); it never starts with a dash' (((@($back.Target) -join '|') -eq '-LongHold|-HoldSeconds|3600') -and ((@($back.Then) -join '|') -eq '-Remove') -and ($b64 -notmatch '^-') -and ((ConvertFrom-ArgsB64 '').Target.Count -eq 0))
    Chk 'definition: RunLevel Highest, interactive logon, no trigger, one instance, unregisters itself' (($def.RunLevel -eq 'Highest') -and ($def.LogonType -eq 'Interactive') -and ($def.Trigger -match '^none') -and ($def.MultipleInstances -eq 'IgnoreNew') -and ($def.UnregistersItself -match '^yes'))
    Chk 'definition: the inner command line names this script with -Inner, the task name, the target and the log' (($def.Arguments -match '-Inner') -and ($def.Arguments -match '-Name blarai-arm2-hold') -and ($def.Arguments -match '-Script C:\\x\\spike-wfp.ps1') -and ($def.Arguments -match '-LogPath C:\\l\\run.log') -and ($def.Arguments -match '-ThenScript'))
    Chk 'definition: the printed target and follow-up commands are exactly what will run' (($def.TargetCommand -eq 'powershell.exe -NoProfile -ExecutionPolicy Bypass -File "C:\x\spike-wfp.ps1" -LongHold') -and ($def.FollowUp -match '-DryRun$'))
    $T = 'S-1-5-18'; $A = 'S-1-5-32-544'; $U = 'S-1-5-32-545'
    $row = { param($sid, $type, $rights, $anc = $false, $io = $false) [pscustomobject]@{ Path = 'C:\x'; Sid = $sid; Type = $type; Rights = [int64]$rights; Ancestor = $anc; InheritOnly = $io } }
    Chk 'admin-only: SYSTEM and Administrators full control with Users read-and-execute -> no problem; Users Modify, create-files or append on the folder -> a problem each' (((Get-NonAdminWriteGrants -Rules @((& $row $T 'Allow' 0x1F01FF), (& $row $A 'Allow' 0x1F01FF), (& $row $U 'Allow' 0x1200A9)) -OwnerSid $A -Path 'C:\x').Count -eq 0) -and ((Get-NonAdminWriteGrants -Rules @((& $row $U 'Allow' 0x1301BF)) -OwnerSid $A -Path 'C:\x').Count -eq 1) -and ((Get-NonAdminWriteGrants -Rules @((& $row $U 'Allow' 0x2)) -OwnerSid $A -Path 'C:\x').Count -eq 1) -and ((Get-NonAdminWriteGrants -Rules @((& $row $U 'Allow' 0x4)) -OwnerSid $A -Path 'C:\x').Count -eq 1))
    Chk 'admin-only: a Deny does not excuse an Allow; a non-admin owner is a problem; on an ancestor create-files is fine but delete-child is not; inherit-only is not credited' (((Get-NonAdminWriteGrants -Rules @((& $row $U 'Deny' 0x2), (& $row $U 'Allow' 0x2)) -OwnerSid $A -Path 'C:\x').Count -eq 1) -and ((Get-NonAdminWriteGrants -Rules @() -OwnerSid 'S-1-5-21-1-2-3-1001' -Path 'C:\x').Count -eq 1) -and ((Get-NonAdminWriteGrants -Rules @((& $row $U 'Allow' 0x6 $true)) -OwnerSid $null -Path 'C:\p').Count -eq 0) -and ((Get-NonAdminWriteGrants -Rules @((& $row $U 'Allow' 0x40 $true)) -OwnerSid $null -Path 'C:\p').Count -eq 1) -and ((Get-NonAdminWriteGrants -Rules @((& $row $U 'Allow' 0x1301BF $false $true)) -OwnerSid $A -Path 'C:\x').Count -eq 0))
    $tmpAcl = Join-Path ([IO.Path]::GetTempPath()) ('acl-' + [guid]::NewGuid().ToString('N')); New-Item -ItemType Directory -Path $tmpAcl | Out-Null
    try { Chk 'admin-only (real ACL read, no change): the user''s own temp folder is NOT admin-only, and a missing folder is refused' (((Test-AdminOnlyFolder -Path $tmpAcl).Ok -eq $false) -and ((Test-AdminOnlyFolder -Path (Join-Path $tmpAcl 'nope')).Ok -eq $false)) } finally { Remove-Item -LiteralPath $tmpAcl -Recurse -Force -ErrorAction SilentlyContinue }
    # the inner runner with fakes
    $tmp = Join-Path ([IO.Path]::GetTempPath()) ('elev-' + [guid]::NewGuid().ToString('N')); New-Item -ItemType Directory -Path $tmp | Out-Null
    try {
        $log = Join-Path $tmp 'sub\run.log'; $script:unreg = 0; $script:order = New-Object System.Collections.ArrayList
        $r = Invoke-InnerRun -Log $log -RunTarget { [void]$script:order.Add('target'); 0 } -RunThen { [void]$script:order.Add('then'); 0 } -Unregister { [void]$script:order.Add('unregister'); $script:unreg++ }
        $txt = [IO.File]::ReadAllText($log)
        Chk 'inner run: target, follow-up, then unregister LAST, exactly once; both exit codes in the log' ((($script:order -join ',') -eq 'target,then,unregister') -and ($script:unreg -eq 1) -and ($txt -match 'target exit code: 0') -and ($txt -match 'follow-up exit code: 0') -and ($txt -match 'task unregistered'))
        $script:unreg = 0; $script:order.Clear()
        $r2 = Invoke-InnerRun -Log $log -RunTarget { throw 'boom' } -RunThen { [void]$script:order.Add('then'); 7 } -Unregister { $script:unreg++ }
        $txt2 = [IO.File]::ReadAllText($log)
        Chk 'inner run: a target that throws is logged, the follow-up STILL runs, and the task is still unregistered' (($r2.Target -eq -1) -and ($r2.Then -eq 7) -and ($script:unreg -eq 1) -and ($txt2 -match 'target threw: boom'))
        $script:unreg = 0
        $r3 = Invoke-InnerRun -Log $log -RunTarget { 3 } -RunThen $null -Unregister { throw 'cannot delete' }
        Chk 'inner run: a failing unregistration is logged loudly, not swallowed silently' (([IO.File]::ReadAllText($log)) -match 'unregister FAILED: cannot delete')
        Chk 'inner run: timestamps carry an offset' ([IO.File]::ReadAllText($log) -match '\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}[+-]\d{2}:\d{2} inner run started')
    } finally { Remove-Item -LiteralPath $tmp -Recurse -Force -ErrorAction SilentlyContinue }
    Write-Host ("elevated-once selftest: {0}" -f $(if ($f -eq 0) { 'all passed' } else { "$f FAILED" }))
    exit $(if ($f -eq 0) { 0 } else { 1 })
}

if ($Inner) {
    # The task's own entry point (runs elevated). Args arrive comma-joined (validated plain by the registering run).
    if (-not (Test-TaskNameValid $Name)) { exit 2 }
    $decoded = ConvertFrom-ArgsB64 $ArgsB64
    $sa = @($decoded.Target); $ta = @($decoded.Then)
    $problems = @(Test-ElevatedTarget -ScriptPath $Script -Args2 $sa -Folder $PSScriptRoot)
    if ($ThenScript) { $problems += @(Test-ElevatedTarget -ScriptPath $ThenScript -Args2 $ta -Folder $PSScriptRoot) }
    $dir = Split-Path $LogPath -Parent
    if ($dir -and -not (Test-Path -LiteralPath $dir)) { New-Item -ItemType Directory -Force $dir | Out-Null }
    $aoInner = Test-AdminOnlyFolder -Path $PSScriptRoot
    if (-not $aoInner.Ok) { $problems += (@($aoInner.Problems | Select-Object -First 3) | ForEach-Object { "folder is not admin-only: $_" }) }
    if ($problems.Count) { Write-LogLine $LogPath ('REFUSED: ' + ($problems -join '; ')); try { Unregister-ScheduledTask -TaskName $Name -TaskPath $TaskPath -Confirm:$false } catch {}; exit 2 }
    $res = Invoke-InnerRun -Log $LogPath `
        -RunTarget { Start-LoggedProcess -HostName $HostExe -ScriptPath $Script -Args2 $sa -Log $LogPath } `
        -RunThen $(if ($ThenScript) { { Start-LoggedProcess -HostName $HostExe -ScriptPath $ThenScript -Args2 $ta -Log $LogPath } } else { $null }) `
        -Unregister { Unregister-ScheduledTask -TaskName $Name -TaskPath $TaskPath -Confirm:$false }
    exit ([int]$res.Target)
}

# ---- register + start (or dry-run) ----------------------------------------------------------------------------------
if (-not (Test-TaskNameValid $Name)) { Write-Host 'ARG ERROR: -Name must look like blarai-<plain-name>' -ForegroundColor Red; exit 2 }
if (-not $LogPath) { Write-Host 'ARG ERROR: -LogPath is required' -ForegroundColor Red; exit 2 }
$scriptFull = if ($Script) { Join-Path $PSScriptRoot (Split-Path $Script -Leaf) } else { $null }
$thenFull = if ($ThenScript) { Join-Path $PSScriptRoot (Split-Path $ThenScript -Leaf) } else { $null }
$problems = @(Test-ElevatedTarget -ScriptPath $scriptFull -Args2 $ScriptArgs -Folder $PSScriptRoot)
if ($ThenScript) { $problems += @(Test-ElevatedTarget -ScriptPath $thenFull -Args2 $ThenArgs -Folder $PSScriptRoot) }
if ($scriptFull -and -not (Test-Path -LiteralPath $scriptFull)) { $problems += "script not found: $scriptFull" }
if ($thenFull -and -not (Test-Path -LiteralPath $thenFull)) { $problems += "follow-up script not found: $thenFull" }
if ($problems.Count) { $problems | ForEach-Object { Write-Host "REFUSED: $_" -ForegroundColor Red }; exit 2 }
$user = "$env:USERDOMAIN\$env:USERNAME"
$def = Get-TaskDefinition -Name $Name -SelfPath $PSCommandPath -ScriptPath $scriptFull -Args2 $ScriptArgs -ThenPath $thenFull -ThenArgs2 $ThenArgs -Log $LogPath -HostName $HostExe -Minutes $TimeLimitMinutes -Path $TaskPath -User $user
Write-Host ($(if ($DryRun) { '== DRY RUN: nothing is registered or started ==' } else { '== registering and starting ==' })) -ForegroundColor Yellow
$def | Format-List | Out-String -Width 220 | Write-Host
$ao = Test-AdminOnlyFolder -Path $PSScriptRoot
if ($ao.Ok) { Write-Host "script folder: admin-only ($($ao.Checked) paths checked)" -ForegroundColor Green }
else { Write-Host 'script folder: NOT admin-only; registering would be REFUSED:' -ForegroundColor Yellow; $ao.Problems | Select-Object -First 5 | ForEach-Object { Write-Host "   $_" -ForegroundColor Yellow } }
if ($DryRun) { Write-Host 'DRY RUN complete.' -ForegroundColor Green; exit 0 }
if (-not $ao.Ok) { Write-Host 'REFUSED: the script folder is writable by non-administrators; an elevated task would run code they can edit. Move the scripts to an admin-only folder.' -ForegroundColor Red; exit 2 }
$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) { Write-Host 'REFUSED: registering a Highest task needs an elevated session (run this from an elevated prompt).' -ForegroundColor Red; exit 2 }
if (Get-ScheduledTask -TaskPath $TaskPath -TaskName $Name -ErrorAction SilentlyContinue) { Write-Host "REFUSED: a task named $TaskPath$Name is already registered (a run in progress, or one that died: inspect it, then Unregister-ScheduledTask)." -ForegroundColor Red; exit 2 }
$action = New-ScheduledTaskAction -Execute $def.Execute -Argument $def.Arguments
$principal = New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Highest
$settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Minutes $TimeLimitMinutes)
Register-ScheduledTask -TaskName $Name -TaskPath $TaskPath -Action $action -Principal $principal -Settings $settings -Description 'BlarAI Track B arm: one elevated run; unregisters itself.' | Out-Null
Start-ScheduledTask -TaskName $Name -TaskPath $TaskPath
Write-Host "started $TaskPath$Name; follow the log: $LogPath" -ForegroundColor Green
exit 0
