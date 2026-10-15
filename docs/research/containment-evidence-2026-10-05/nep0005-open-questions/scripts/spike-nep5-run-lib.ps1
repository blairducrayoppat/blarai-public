#requires -Version 5.1
<#
.SYNOPSIS
  NEP-0005 open-questions matrix, library 2 of 2: the state table, the loopback listeners, the child-process launcher (a clean module path; an explicit minimal environment for the account's child), the account's password for the length of a session and the proof that the account's task
  is whole again afterwards, the account and operator connects, the per-state cycle (sweep, control, add, record, probe, remove, sweep) and the phase runner. Dot-source it AFTER
  spike-nep5-lib.ps1 (and the libraries that one needs). No side effects on load; every action on the machine goes through a seam held in the context object so
  -SelfTest drives the whole cycle against fakes.

.DESCRIPTION
  Context object ($Ctx), built by the entry script (real) or by the self-test (fake):
    Runner, Backend, Exporter   as in spike-nep5-lib.ps1
    Proof                       the token Test-N5Proof returned (an add path refuses anything else)
    SidProblemsFor              { param($sid) } -> problems (the arms' SID-safety function on the operator's token)
    AccountRun                  { param($runId, $request, $tick) } -> @{ Started; Valid; Problems; Result; Launch } (the probe run as the account through a session password, or a fake)
    OperatorConnect             { param($family, $port) } -> @{ ok; ms; error }       OperatorProbe  { } -> @{ ok } (one connect to the outside, the watchdog's)
    AccountOps                  New-Nep5AccountOps: sets the account's password (in memory only) and runs the probe as the account; Reprovision { param($Ctx) } -> @{ Ok; Detail } runs spike-provision.ps1 -Apply -ForceNewPassword
    ProvisionDryRun             { param($Ctx) } -> @{ Ok; Detail }: spike-provision.ps1 -DryRun through the same verified launcher; a session sets no password unless it passed
    TaskOps (read only: GetArguments, Snapshot, Info), BinDir, ScriptFolder, ProbeSha, HarnessExe, HarnessSha, Bound (which listener bound), OutDir, Passes, Only, Phase
  Exit classes of a cycle: ok | inconclusive | control_failed | refused | stop | removal_unverified | operator_abort | finding_stop.
#>

# ---- the state table --------------------------------------------------------------------------------------------------------------------
$script:N5States = @(
    [pscustomobject]@{ Id = 'R0'; Phase = 'halfset'; Kind = 'none'; Sid = ''; Delete = @(); Plan = ''; Title = 'no filters (control)' }
    [pscustomobject]@{ Id = 'R1'; Phase = 'halfset'; Kind = 'srt'; Sid = 'spike'; Delete = @(); Plan = ''; Title = 'full set from install_filters' }
    [pscustomobject]@{ Id = 'R2'; Phase = 'halfset'; Kind = 'srt'; Sid = 'spike'; Delete = @('block-v4'); Plan = ''; Title = 'V4 block deleted (V6 block and both permits remain)' }
    [pscustomobject]@{ Id = 'R3'; Phase = 'halfset'; Kind = 'srt'; Sid = 'spike'; Delete = @('block-v6'); Plan = ''; Title = 'V6 block deleted (V4 block and both permits remain)' }
    [pscustomobject]@{ Id = 'R4'; Phase = 'halfset'; Kind = 'srt'; Sid = 'spike'; Delete = @('block-v4', 'block-v6'); Plan = ''; Title = 'both blocks deleted, permits remain' }
    [pscustomobject]@{ Id = 'R5'; Phase = 'halfset'; Kind = 'srt'; Sid = 'spike'; Delete = @('permit-v4', 'permit-v6'); Plan = ''; Title = 'permits deleted, blocks remain' }
    [pscustomobject]@{ Id = 'R6'; Phase = 'halfset'; Kind = 'srt'; Sid = 'stale'; Delete = @(); Plan = ''; Title = 'stale: full set for the stale test SID' }
    [pscustomobject]@{ Id = 'R7'; Phase = 'halfset'; Kind = 'ours'; Sid = 'spike'; Delete = @(); Plan = 'r7'; Title = 'S3: our unlabelled blocks for the account; srt-win status read on S1 (empty)' }
    [pscustomobject]@{ Id = 'O1'; Phase = 'ours'; Kind = 'ours'; Sid = 'spike'; Delete = @(); Plan = 'o1'; Title = 'S2 set: V4 block only' }
    [pscustomobject]@{ Id = 'O2'; Phase = 'ours'; Kind = 'ours'; Sid = 'spike'; Delete = @(); Plan = 'o2'; Title = 'S2 set: V6 block only' }
    [pscustomobject]@{ Id = 'O3'; Phase = 'ours'; Kind = 'ours'; Sid = 'spike'; Delete = @(); Plan = 'o3'; Title = 'S2 set: permit without a block' }
    [pscustomobject]@{ Id = 'O4'; Phase = 'ours'; Kind = 'ours'; Sid = 'spike'; Delete = @(); Plan = 'o4'; Title = 'S2 set: both blocks + an exact-port permit (127.0.0.1, no user condition)' }
    [pscustomobject]@{ Id = 'O5'; Phase = 'ours'; Kind = 'ours'; Sid = 'spike'; Delete = @(); Plan = 'o5'; Title = 'S2: a block with no provider, attempted (the engine''s answer is the result)' }
    [pscustomobject]@{ Id = 'O6'; Phase = 'ours'; Kind = 'ours'; Sid = 'spike'; Delete = @(); Plan = 'o6'; Title = 'a filter naming a missing sublayer, attempted (the engine''s answer is the result)' }
    [pscustomobject]@{ Id = 'N1'; Phase = 'n1'; Kind = 'n1'; Sid = 'spike'; Delete = @(); Plan = 'o1'; Title = 'non-elevated add and delete by the account''s own standard token against S2' }
)
$script:N5Phases = @('taskcheck', 'halfset', 'ours', 'n1')
$script:N5TaskDir = 'C:\blarai-spike\bin'
$script:N5TaskOrigArgs = '-NoProfile -NonInteractive -ExecutionPolicy Bypass -File "C:\blarai-spike\bin\spike-run-test.ps1" -RequestFile "C:\blarai-spike\bin\request.json"'
$script:N5ProbeScriptName = 'spike-nep5-connect-probe.ps1'

function Get-Nep5SidFor { param([string]$Which) if ($Which -eq 'stale') { return $script:N5StaleSid } return $script:N5SpikeSid }

function Get-Nep5Targets {
    # PURE. The connect targets of every state: the out-of-range port, its neighbour and one inside 60080-60089, each on 127.0.0.1 and [::1]. A target whose listener did
    # not bind is NOT RUN (Runnable = $false), never "blocked". $Bound: 'v4:61763' -> $true/$false.
    param($Bound)
    $t = @()
    foreach ($port in @($script:N5PortOut, $script:N5PortNeighbour, $script:N5PortIn)) {
        foreach ($fam in @('v4', 'v6')) { $k = "${fam}:$port"; $t += [pscustomobject]@{ Key = $k; Family = $fam; Port = $port; Runnable = [bool]($Bound -and $Bound[$k]) } }
    }
    return @($t)
}

function Get-Nep5RowVerdict {
    # PURE. open | blocked | refused | timeout | error, from one result row of the account's probe.
    param($Row)
    switch ([string]$Row.result) { 'connected' { return 'open' } 'blocked' { return 'blocked' } 'refused' { return 'refused' } 'timeout' { return 'timeout' } default { return 'error' } }
}

function Get-Nep5RowsSummary {
    # PURE. 'v4:61763' -> verdict, in target order.
    param($Rows)
    $o = [ordered]@{}
    foreach ($r in @($Rows)) { $o["$($r.family):$($r.port)"] = (Get-Nep5RowVerdict $r) }
    return $o
}

# ---- listeners ------------------------------------------------------------------------------------------------------------------------------
function Start-Nep5Listeners {
    # Binds a TCP listener on 127.0.0.1 and on [::1] for each port (a connect completes against the backlog; nothing is accepted). The result says which bound; a failed
    # bind is recorded and the targets on it are NOT RUN. Never throws.
    param([int[]]$Ports)
    $items = @(); $bound = @{}
    foreach ($port in $Ports) {
        foreach ($fam in @('v4', 'v6')) {
            $ip = if ($fam -eq 'v6') { [Net.IPAddress]::IPv6Loopback } else { [Net.IPAddress]::Loopback }
            $it = [pscustomobject]@{ Family = $fam; Port = $port; Listener = $null; Bound = $false; Error = $null }
            try { $l = New-Object Net.Sockets.TcpListener($ip, $port); $l.Start(); $it.Listener = $l; $it.Bound = $true } catch { $it.Error = $_.Exception.Message }
            $bound["${fam}:$port"] = $it.Bound; $items += $it
        }
    }
    return [pscustomobject]@{ Items = $items; Bound = $bound }
}

function Test-Nep5Loopback {
    # The operator's connect to a loopback listener. A real Socket of the right address family (Windows PowerShell 5.1's TcpClient is IPv4 only, so the wrapped Test-TcpConnect
    # cannot reach [::1] there). Never throws. @{ target; ok; ms; error; t }.
    param([Parameter(Mandatory)][ValidateSet('v4', 'v6')][string]$Family, [Parameter(Mandatory)][int]$Port, [int]$TimeoutMs = 2000)
    $addr = if ($Family -eq 'v6') { [Net.IPAddress]::IPv6Loopback } else { [Net.IPAddress]::Loopback }
    $af = if ($Family -eq 'v6') { [Net.Sockets.AddressFamily]::InterNetworkV6 } else { [Net.Sockets.AddressFamily]::InterNetwork }
    $sw = [Diagnostics.Stopwatch]::StartNew(); $s = New-Object Net.Sockets.Socket($af, [Net.Sockets.SocketType]::Stream, [Net.Sockets.ProtocolType]::Tcp)
    $ok = $false; $err = ''
    try {
        $iar = $s.BeginConnect((New-Object Net.IPEndPoint($addr, $Port)), $null, $null)
        if ($iar.AsyncWaitHandle.WaitOne($TimeoutMs, $false)) { try { $s.EndConnect($iar); $ok = $true } catch { $err = $_.Exception.Message } } else { $err = "timeout ${TimeoutMs}ms" }
    } catch { $err = $_.Exception.Message } finally { try { $s.Close() } catch {} }
    return [pscustomobject]@{ target = "${Family}:$Port"; ok = $ok; ms = $sw.ElapsedMilliseconds; error = $err; t = (Get-Date).ToString('o') }
}

function Clear-Nep5Backlog {
    # Accepts and closes every connection waiting on every listener. The listeners are never accepted from otherwise, and a queue holds only about 200 completed connects, after which a connect
    # TIMES OUT (never "blocked"). Called before each batch of connects so a phase cannot run into that limit. Returns how many were drained.
    param($Set)
    $n = 0
    foreach ($it in @($Set.Items)) { if ($it.Listener) { try { while ($it.Listener.Pending()) { $c = $it.Listener.AcceptTcpClient(); $c.Close(); $n++ } } catch {} } }
    return $n
}

function Stop-Nep5Listeners { param($Set) foreach ($it in @($Set.Items)) { if ($it.Listener) { try { $it.Listener.Stop() } catch {} } } }

# ---- the account's task: read only; it is put back by re-running spike-provision, never edited ----------------------------------------------
function New-Nep5RealTaskOps {
    # READ-ONLY view of the one existing task. Nothing in this matrix writes the task: it is restored by re-running spike-provision.ps1, not edited.
    return [pscustomobject]@{ Kind = 'real' } |
        Add-Member -MemberType ScriptMethod -Name Info -Value {
            $t = Get-ScheduledTask -TaskPath $script:SpikeTaskPath -TaskName $script:SpikeTaskName -ErrorAction Stop
            $i = Get-ScheduledTaskInfo -TaskPath $script:SpikeTaskPath -TaskName $script:SpikeTaskName -ErrorAction Stop
            return [pscustomobject]@{ State = [string]$t.State; LastTaskResult = [long]$i.LastTaskResult; LastRunTime = [string]$i.LastRunTime }
        } -PassThru |
        Add-Member -MemberType ScriptMethod -Name GetArguments -Value {
            $t = Get-ScheduledTask -TaskPath $script:SpikeTaskPath -TaskName $script:SpikeTaskName -ErrorAction Stop
            if (@($t.Actions).Count -ne 1) { throw "the task has $(@($t.Actions).Count) actions, expected one" }
            return [string]$t.Actions[0].Arguments
        } -PassThru |
        Add-Member -MemberType ScriptMethod -Name Snapshot -Value {
            $xml = [string](Export-ScheduledTask -TaskPath $script:SpikeTaskPath -TaskName $script:SpikeTaskName -ErrorAction Stop)
            $n = ConvertTo-Nep5NormalizedTaskXml -Xml $xml
            if ($null -eq $n) { throw 'the exported task XML did not parse' }
            return $n
        } -PassThru
}

function ConvertTo-Nep5NormalizedTaskXml {
    # PURE. The task XML reduced to the fields that decide what the task IS, one `name=value` line each: principal (UserId, LogonType, RunLevel), the action (Command, Arguments, WorkingDirectory),
    # EVERY child element of Settings (one `Settings.<name>=<text>` line each, sorted by name, so Hidden, Priority, AllowHardTerminate, RestartOnFailure and the idle settings are compared too; the six named
    # settings keep their own lines) and the number of triggers.
    # ALSO compared: every other child of Principal (GroupId, RequiredPrivileges, ...), the Context attribute of Actions, and RegistrationInfo/SecurityDescriptor when the export carries one.
    # EXCLUDED on purpose, because a re-registration legitimately changes them: RegistrationInfo's Date, Author, URI and Description, ids, and every element outside Principals, Actions, Settings and Triggers.
    # $null when the text is not XML.
    param([string]$Xml)
    $d = New-Object Xml.XmlDocument
    try { $d.LoadXml($Xml) } catch { return $null }
    $g = { param($n) (@($d.SelectNodes("//*[local-name()='$n']") | ForEach-Object { ([string]$_.InnerText).Trim() }) -join ',') }
    $named = @('UserId', 'LogonType', 'RunLevel', 'Command', 'Arguments', 'WorkingDirectory', 'MultipleInstancesPolicy', 'DisallowStartIfOnBatteries', 'StopIfGoingOnBatteries', 'ExecutionTimeLimit', 'StartWhenAvailable', 'Enabled')
    $lines = @(foreach ($n in $named) { "$n=$(& $g $n)" })
    $other = @($d.SelectNodes("//*[local-name()='Settings']/*") | Where-Object { $named -notcontains $_.LocalName } | Sort-Object LocalName | ForEach-Object { "Settings.$($_.LocalName)=$(([string]$_.InnerText).Trim() -replace '\s+', ' ')" })
    $prin = @($d.SelectNodes("//*[local-name()='Principals']/*[local-name()='Principal']/*") | Where-Object { $named -notcontains $_.LocalName } | Sort-Object LocalName | ForEach-Object { "Principal.$($_.LocalName)=$(([string]$_.InnerText).Trim() -replace '\s+', ' ')" })
    $ctxA = @($d.SelectNodes("//*[local-name()='Actions']") | ForEach-Object { "Actions.Context=$($_.GetAttribute('Context'))" })
    $sdn = @($d.SelectNodes("//*[local-name()='RegistrationInfo']/*[local-name()='SecurityDescriptor']") | ForEach-Object { "SecurityDescriptor=$(([string]$_.InnerText).Trim())" })
    $trig = @($d.SelectNodes("//*[local-name()='Triggers']/*")).Count
    return ((@($lines) + @($prin) + @($ctxA) + @($sdn) + @($other) + "Triggers=$trig") -join "`n")
}

function Get-Nep5TaskCredentialFailureCodes {
    # PURE. The Task Scheduler last-result codes that mean the stored credential or the account cannot log on (logon failure, account restriction, account disabled, password expired, logon type not granted, locked out).
    return @(0x8007052E, 0x8007052F, 0x80070530, 0x80070532, 0x80070533, 0x80070569, 0x80070775)
}

function Get-Nep5TaskInfoVerdict {
    # PURE. From a task info record (State, LastTaskResult) to @{ CredentialFailure; Text }. A READ of the task's last run, never a start: only taskcheck and -Remove start the task.
    param($Info)
    if (-not $Info) { return [ordered]@{ CredentialFailure = $false; Unreadable = $true; Text = 'task info unreadable' } }
    $code = [long]$Info.LastTaskResult; $hex = '0x{0:X8}' -f ($code -band 0xFFFFFFFFL)
    $bad = ((Get-Nep5TaskCredentialFailureCodes) | ForEach-Object { [long]$_ -band 0xFFFFFFFFL }) -contains ($code -band 0xFFFFFFFFL)
    $disabled = ([string]$Info.State -eq 'Disabled')
    $txt = "task state $($Info.State); last run result $hex"
    if ($bad) { $txt += ' = a logon / credential failure: the task CANNOT start (re-key with spike-provision.ps1 -Apply -ForceNewPassword, then taskcheck)' }
    elseif ($disabled) { $txt += ' = the task is disabled' }
    else { $txt += ' (a read of the last run, not a start: only taskcheck and -Remove start the task)' }
    return [ordered]@{ CredentialFailure = ($bad -or $disabled); Unreadable = $false; Text = $txt }
}

function New-Nep5FakeTaskOps {
    # In-memory task for the self-test: its arguments and one `Extra` field standing for the principal/credential; Snapshot is the normalised form. SnapFail: Snapshot throws.
    param([string]$Initial = $script:N5TaskOrigArgs, [bool]$SnapFail = $false)
    $o = [pscustomobject]@{ Args = $Initial; Extra = 'logon=password'; SnapFail = $SnapFail }
    $o | Add-Member -MemberType ScriptMethod -Name Snapshot -Value { if ($this.SnapFail) { throw 'fake Export-ScheduledTask failed' }; return "Arguments=$($this.Args)`nLogonType=$($this.Extra)" }
    $o | Add-Member -MemberType ScriptMethod -Name GetArguments -Value { return [string]$this.Args }
    return $o
}

function Get-Nep5TaskState {
    # original | unknown:<args> | unreadable:<why>. Only the recorded original argument string is "original".
    param([Parameter(Mandatory)]$Ops)
    try { $a = [string]$Ops.GetArguments(); if ($a -eq $script:N5TaskOrigArgs) { return 'original' }; return "unknown:$a" } catch { return "unreadable:$($_.Exception.Message)" }
}

# ---- child processes: a clean module path, and for the account an explicit minimal environment -------------------------------------------------
# The names the account's child may see. Nothing else is in its environment block: not the operator's tokens, passwords or key-store paths, not his profile, not his temp folder.
$script:N5AccountEnvAllow = @('SystemRoot', 'windir', 'SystemDrive', 'ComSpec', 'PATHEXT', 'PATH', 'PSModulePath', 'USERPROFILE', 'APPDATA', 'LOCALAPPDATA', 'TEMP', 'TMP')
$script:N5SecretNameRe = '(?i)token|secret|pass|pwd|key|cred|auth|dek|vikunja|github|api'
$script:N5AccountLogonType = 'interactive (CreateProcessWithLogonW, LOGON_WITH_PROFILE); NOT the batch logon the existing task uses'

function Get-Nep5WinPsModulePath {
    # PURE on its arguments. Windows PowerShell 5.1's machine module path: PowerShell 7 puts its own module folders first and a 5.1 child that inherits that cannot load
    # Microsoft.PowerShell.Security, so ConvertTo-SecureString fails inside it.
    param([string]$SystemRoot = $env:SystemRoot, [string]$ProgramFiles = $env:ProgramFiles)
    return ('{0}\WindowsPowerShell\Modules;{1}\System32\WindowsPowerShell\v1.0\Modules' -f $ProgramFiles.TrimEnd('\'), $SystemRoot.TrimEnd('\'))
}

function Get-Nep5ProvisionEnvironment {
    # PURE. The environment of a Windows PowerShell 5.1 child that runs as the OPERATOR (spike-provision.ps1): the parent's variables unchanged, except that PSModulePath is the given Windows
    # PowerShell value. The child needs the operator's profile variables, and it is the operator's own principal, so nothing crosses a boundary.
    param([Parameter(Mandatory)][System.Collections.IDictionary]$Parent, [Parameter(Mandatory)][string]$ModulePath)
    $o = [ordered]@{}
    foreach ($k in @($Parent.Keys)) { if ([string]$k -ine 'PSModulePath') { $o[[string]$k] = [string]$Parent[$k] } }
    $o['PSModulePath'] = $ModulePath
    return $o
}

function Get-Nep5AccountEnvironment {
    # PURE on its arguments (reads no environment variable). The WHOLE environment block of the child that runs as blarai-spike: system variables only, a system-only PATH, the Windows PowerShell module
    # path, and a profile / temp location inside the account's own folder (C:\blarai-spike\work, which the account can write). No variable is copied from the process that builds it.
    param([Parameter(Mandatory)][string]$SystemRoot, [Parameter(Mandatory)][string]$ProgramFiles, [Parameter(Mandatory)][string]$SpikeRoot)
    $sr = $SystemRoot.TrimEnd('\'); $root = $SpikeRoot.TrimEnd('\'); $tmp = "$root\work\tmp"
    return [ordered]@{
        SystemRoot = $sr; windir = $sr; SystemDrive = ([IO.Path]::GetPathRoot($sr)).TrimEnd('\'); ComSpec = "$sr\System32\cmd.exe"; PATHEXT = '.COM;.EXE;.BAT;.CMD'
        PATH = "$sr\System32;$sr;$sr\System32\Wbem;$sr\System32\WindowsPowerShell\v1.0"; PSModulePath = (Get-Nep5WinPsModulePath -SystemRoot $sr -ProgramFiles $ProgramFiles)
        USERPROFILE = "$root\work"; APPDATA = $tmp; LOCALAPPDATA = $tmp; TEMP = $tmp; TMP = $tmp
    }
}

function Test-Nep5ChildEnvironment {
    # PURE. Problems (empty = the block may be handed to the account's child): a name outside the allowlist, a secret-looking name, an empty value, a profile / temp location outside the account's own folder,
    # or a value that mentions any of the forbidden texts (the operator's profile folder).
    param([Parameter(Mandatory)][System.Collections.IDictionary]$Environment, [Parameter(Mandatory)][string[]]$Allow, [Parameter(Mandatory)][string]$SpikeRoot, [string[]]$Forbidden = @())
    $p = New-Object System.Collections.ArrayList
    foreach ($k in @($Environment.Keys)) {
        $n = [string]$k; $v = [string]$Environment[$k]
        if ($Allow -notcontains $n) { [void]$p.Add("variable '$n' is not on the allowlist") }
        if ($n -match $script:N5SecretNameRe) { [void]$p.Add("variable '$n' has a secret-looking name") }
        if (-not $v) { [void]$p.Add("variable '$n' is empty") }
        if ($n -in @('USERPROFILE', 'APPDATA', 'LOCALAPPDATA', 'TEMP', 'TMP') -and -not $v.StartsWith($SpikeRoot.TrimEnd('\') + '\', [StringComparison]::OrdinalIgnoreCase)) { [void]$p.Add("variable '$n' points outside $SpikeRoot") }
        foreach ($f in @($Forbidden | Where-Object { $_ })) { if ($v.IndexOf($f, [StringComparison]::OrdinalIgnoreCase) -ge 0) { [void]$p.Add("variable '$n' mentions '$f'") } }
    }
    return @($p)
}

function New-Nep5StartInfo {
    # Builds (never starts) the ProcessStartInfo every child of this matrix is started with: no shell, no window, hidden, the working folder, and an environment block that is CLEARED and then set to exactly the given
    # variables (a ProcessStartInfo that is not touched hands the child the parent's whole environment). With -UserName the child runs as that account (CreateProcessWithLogonW) with -Password, -Domain and,
    # with -LoadUserProfile, the account's profile. -Capture redirects stdout and stderr (read after the fact) and closes stdin.
    param([Parameter(Mandatory)][string]$FilePath, [string]$ArgumentLine = '', [string]$WorkingDirectory, [Parameter(Mandatory)][System.Collections.IDictionary]$Environment,
          [string]$UserName, [string]$Domain, [System.Security.SecureString]$Password, [switch]$LoadUserProfile, [switch]$Capture)
    $psi = New-Object Diagnostics.ProcessStartInfo
    $psi.FileName = $FilePath; $psi.Arguments = $ArgumentLine; $psi.UseShellExecute = $false; $psi.CreateNoWindow = $true; $psi.WindowStyle = [Diagnostics.ProcessWindowStyle]::Hidden
    if ($WorkingDirectory) { $psi.WorkingDirectory = $WorkingDirectory }
    $ev = $psi.EnvironmentVariables; $ev.Clear()
    foreach ($k in @($Environment.Keys)) { $ev[[string]$k] = [string]$Environment[$k] }
    if ($UserName) {
        $psi.UserName = $UserName; if ($Domain) { $psi.Domain = $Domain }
        if ($Password) { $psi.Password = $Password }
        $psi.LoadUserProfile = [bool]$LoadUserProfile
    }
    if ($Capture) { $psi.RedirectStandardInput = $true; $psi.RedirectStandardOutput = $true; $psi.RedirectStandardError = $true }
    return $psi
}

function New-Nep5AccountStartInfo {
    # The start info of the account's probe child: the credential split into account and computer, the minimal environment block, the profile loaded, nothing captured. Starts nothing.
    param([Parameter(Mandatory)][Management.Automation.PSCredential]$Cred, [Parameter(Mandatory)][string]$FilePath, [Parameter(Mandatory)][string]$ArgumentLine, [Parameter(Mandatory)][string]$WorkingDirectory, [Parameter(Mandatory)][System.Collections.IDictionary]$Environment)
    $parts = ([string]$Cred.UserName) -split '\\', 2
    $dom = $(if ($parts.Count -eq 2) { $parts[0] } else { '' }); $usr = $(if ($parts.Count -eq 2) { $parts[1] } else { $parts[0] })
    return (New-Nep5StartInfo -FilePath $FilePath -ArgumentLine $ArgumentLine -WorkingDirectory $WorkingDirectory -Environment $Environment -UserName $usr -Domain $dom -Password $Cred.Password -LoadUserProfile)
}

function Start-Nep5Child {
    # The ONE place a child process is started. Returns an object with HasExited, ExitCode, Kill() and ReadOutput() (the captured stdout / stderr, when the start info captured them). Throws when the start fails.
    param([Parameter(Mandatory)][Diagnostics.ProcessStartInfo]$StartInfo)
    $p = [Diagnostics.Process]::Start($StartInfo)
    if (-not $p) { throw 'the process did not start' }
    $w = [pscustomobject]@{ Proc = $p; OutTask = $null; ErrTask = $null }
    if ($StartInfo.RedirectStandardInput) { try { $p.StandardInput.Close() } catch {} }
    if ($StartInfo.RedirectStandardOutput) { $w.OutTask = $p.StandardOutput.ReadToEndAsync() }
    if ($StartInfo.RedirectStandardError) { $w.ErrTask = $p.StandardError.ReadToEndAsync() }
    $w | Add-Member -MemberType ScriptProperty -Name HasExited -Value { $this.Proc.HasExited }
    $w | Add-Member -MemberType ScriptProperty -Name ExitCode -Value { $this.Proc.ExitCode }
    $w | Add-Member -MemberType ScriptMethod -Name Kill -Value {
        # the WHOLE process tree (taskkill /T): a grandchild (secedit, icacls, csc) must not outlive a timeout, and it holds the output pipes open
        try { $tk = Join-Path $env:SystemRoot 'System32\taskkill.exe'; if (Test-Path -LiteralPath $tk) { & $tk /PID $this.Proc.Id /T /F *> $null } } catch {}
        try { $this.Proc.Kill() } catch {}
    }
    $w | Add-Member -MemberType ScriptMethod -Name ReadOutput -Value {
        param([int]$WaitMs = 5000)
        $o = ''; $e = ''
        try { if ($this.OutTask -and $this.OutTask.Wait($WaitMs)) { $o = [string]$this.OutTask.Result } } catch {}
        try { if ($this.ErrTask -and $this.ErrTask.Wait($WaitMs)) { $e = [string]$this.ErrTask.Result } } catch {}
        return [pscustomobject]@{ Out = $o; Err = $e }
    }
    return $w
}

# ---- the account: a session password held in memory, the probe run as the account, the task re-provisioned afterwards ------------------------------
function Get-Nep5ProbeCommandLine {
    # The ONE command line the account's probe is started with: fixed text, no password, no variable part. The request and the result go through files in the account's folders.
    return ('-NoProfile -NonInteractive -ExecutionPolicy Bypass -File "{0}\bin\{1}" -RequestFile "{0}\bin\nep5-request.json"' -f $script:SpikeRoot, $script:N5ProbeScriptName)
}

function New-Nep5AccountOps {
    # The account's session password and the child process that runs as the account. Every OS action is a scriptblock so -SelfTest passes fakes; the defaults are the real ones.
    #   SetPassword()  resolves the account BY THE RECORDED SID, requires its name and SID to be the recorded ones (anything else is refused with nothing changed), then sets a fresh random password
    #                  (New-StrongPassword) on that exact account object, addressed by its SID. `Changed` becomes true BEFORE the write, so a half-applied write is treated as changed. The password lives only in a
    #                  SecureString inside a PSCredential held here; it is never in a file, task, log, record, environment variable or command line, and Drop() releases it.
    #   RunProbe(sec)  starts powershell.exe with the fixed command line as that credential (profile loaded, hidden, working folder = the account's bin folder, an explicit minimal environment block),
    #                  waits up to sec seconds while calling the watchdog tick, and KILLS the child at the limit. The result carries Launch: the logon type and the environment variable NAMES supplied.
    param([Parameter(Mandatory)][string]$BinDir, [scriptblock]$GetUser, [scriptblock]$NewPassword, [scriptblock]$SetPasswordFn, [scriptblock]$StartProcess, [string]$ComputerName = $env:COMPUTERNAME, [int]$PollMs = 200,
          [string]$SystemRoot = $env:SystemRoot, [string]$ProgramFiles = $env:ProgramFiles)
    if (-not $GetUser) { $GetUser = { param($sid) Get-LocalUser -SID ([Security.Principal.SecurityIdentifier]$sid) -ErrorAction Stop } }
    if (-not $NewPassword) { $NewPassword = { New-StrongPassword } }
    if (-not $SetPasswordFn) { $SetPasswordFn = { param($u, $sec) Set-LocalUser -SID $u.SID -Password $sec -ErrorAction Stop } }
    if (-not $StartProcess) { $StartProcess = { param($cred, $exe, $argLine, $wd, $envBlock) Start-Nep5Child -StartInfo (New-Nep5AccountStartInfo -Cred $cred -FilePath $exe -ArgumentLine $argLine -WorkingDirectory $wd -Environment $envBlock) } }
    $o = [pscustomobject]@{ Kind = 'account-ops'; Changed = $false; BinDir = $BinDir; Cred = $null; Log = (New-Object System.Collections.ArrayList); GetUserFn = $GetUser; NewPasswordFn = $NewPassword; SetPasswordFn = $SetPasswordFn; StartFn = $StartProcess
                            Computer = $ComputerName; PollMs = $PollMs; Name = $script:SpikeUser; Sid = $script:N5SpikeSid; SystemRoot = $SystemRoot; ProgramFiles = $ProgramFiles; SpikeRoot = $script:SpikeRoot; LogonType = $script:N5AccountLogonType }
    $o | Add-Member -MemberType ScriptMethod -Name SetPassword -Value {
        $u = $null
        try { $u = & $this.GetUserFn $this.Sid } catch { return [ordered]@{ Ok = $false; Reason = "the account with the recorded SID could not be looked up: $($_.Exception.Message)" } }
        if (-not $u -or [string]$u.Name -ine $this.Name -or [string]$u.SID.Value -ne $this.Sid) { return [ordered]@{ Ok = $false; Reason = "REFUSED: the account with the recorded SID is '$($u.Name)' with SID '$($u.SID.Value)', not '$($this.Name)' with the recorded SID: no password was set" } }
        $this.Changed = $true
        try { $sec = & $this.NewPasswordFn; & $this.SetPasswordFn $u $sec } catch { return [ordered]@{ Ok = $false; Reason = "setting the account password failed: $($_.Exception.Message)" } }
        $this.Cred = New-Object Management.Automation.PSCredential(("{0}\{1}" -f $this.Computer, $u.Name), $sec)
        return [ordered]@{ Ok = $true; Reason = 'a fresh session password was set (held in memory only)' }
    }
    $o | Add-Member -MemberType ScriptMethod -Name RunProbe -Value {
        param([int]$TimeoutSec, [scriptblock]$Tick)
        if (-not $this.Cred) { return [ordered]@{ Started = $false; TimedOut = $false; Killed = $false; ExitCode = $null; Detail = 'no session password is set'; Launch = $null } }
        $exe = Join-Path $this.SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'; $cl = Get-Nep5ProbeCommandLine
        $envBlock = Get-Nep5AccountEnvironment -SystemRoot $this.SystemRoot -ProgramFiles $this.ProgramFiles -SpikeRoot $this.SpikeRoot
        $launch = [ordered]@{ logon_type = $this.LogonType; environment_variable_names_supplied = @($envBlock.Keys | Sort-Object); working_folder = $this.BinDir }
        [void]$this.Log.Add("start $exe $cl (as $($this.Cred.UserName), working folder $($this.BinDir), environment variable names: $((@($envBlock.Keys | Sort-Object)) -join ','))")
        $p = $null
        try { $p = & $this.StartFn $this.Cred $exe $cl $this.BinDir $envBlock } catch { return [ordered]@{ Started = $false; TimedOut = $false; Killed = $false; ExitCode = $null; Detail = "the probe could not be started as the account: $($_.Exception.Message)"; Launch = $launch } }
        $deadline = (Get-Date).AddSeconds($TimeoutSec); $timedOut = $false; $killed = $false
        while (-not $p.HasExited) {
            if ((Get-Date) -gt $deadline) { $timedOut = $true; break }
            if ($Tick) { & $Tick }
            Start-Sleep -Milliseconds $this.PollMs
        }
        if ($timedOut) {
            try { $p.Kill() } catch {}
            $k = (Get-Date).AddSeconds(5); while (-not $p.HasExited -and (Get-Date) -lt $k) { Start-Sleep -Milliseconds 100 }
            $killed = [bool]$p.HasExited
            [void]$this.Log.Add("timeout after $TimeoutSec s: child killed=$killed")
        }
        return [ordered]@{ Started = $true; TimedOut = $timedOut; Killed = $killed; ExitCode = $(if ($p.HasExited) { $p.ExitCode } else { $null }); Detail = $(if ($timedOut) { "the probe did not finish within $TimeoutSec s; killed: $killed" } else { "exit $($p.ExitCode)" }); Launch = $launch }
    }
    $o | Add-Member -MemberType ScriptMethod -Name Drop -Value { if ($this.Cred -and $this.Cred.Password) { try { $this.Cred.Password.Dispose() } catch {} }; $this.Cred = $null }
    return $o
}

function Test-Nep5ProvisionDependencies {
    # Problems (empty = spike-provision.ps1 may be started). Everything it loads or copies is hashed NOW, immediately before the start, and any difference refuses the start:
    # spike-provision.ps1 itself and the files in $DependencySha (name -> LF-normalised SHA-256 the proof bound; spike-lib.ps1, which it dot-sources), and the two files it copies into the account's bin folder
    # (spike-run-test.ps1, spike_model.py), which must hash like the copies already there. The generated spike-config.json has no source to hash.
    param([Parameter(Mandatory)][string]$Folder, [Parameter(Mandatory)][string]$ExpectedSha, [System.Collections.IDictionary]$DependencySha = @{}, [string]$BinDir)
    $p = New-Object System.Collections.ArrayList
    $h = $null; try { $h = Get-NormalizedSha256 -Path (Join-Path $Folder 'spike-provision.ps1') } catch {}
    if (-not $h -or $h -ne $ExpectedSha.ToUpperInvariant()) { [void]$p.Add('spike-provision.ps1 is missing or is not the file the proof bound') }
    foreach ($n in @($DependencySha.Keys)) {
        $x = $null; try { $x = Get-NormalizedSha256 -Path (Join-Path $Folder ([string]$n)) } catch {}
        if (-not $x -or $x -ne ([string]$DependencySha[$n]).ToUpperInvariant()) { [void]$p.Add("$n is missing or is not the file the proof bound") }
    }
    if ($BinDir) {
        foreach ($n in @('spike-run-test.ps1', 'spike_model.py')) {
            $mine = $null; $theirs = $null
            try { $mine = Get-NormalizedSha256 -Path (Join-Path $Folder $n) } catch {}
            try { $theirs = Get-NormalizedSha256 -Path (Join-Path $BinDir $n) } catch {}
            if (-not $mine) { [void]$p.Add("$n is missing from the script folder (spike-provision.ps1 would copy it into the account's bin folder)") }
            elseif (-not $theirs) { [void]$p.Add("$n is missing from $BinDir, so there is nothing to compare the copy source against") }
            elseif ($mine -ne $theirs) { [void]$p.Add("$n in the script folder does not hash like the copy in $BinDir (spike-provision.ps1 would put it there)") }
        }
    }
    return @($p)
}

function Invoke-Nep5Reprovision {
    # Runs the existing arm script `spike-provision.ps1` in a child Windows PowerShell 5.1 (it ends with `exit`, so never in this process): -Mode Apply (default) = `-Apply -ForceNewPassword`, which restores the
    # original task credential (it resets the account's password, which also invalidates the session password, and re-registers \BlarAI\BlarAI-Spike-Model with the new one);
    # -Mode DryRun = `-DryRun`, its read-only precondition report (exit 0 = they hold, 2 = they do not). Every file it loads or copies is hashed first (Test-Nep5ProvisionDependencies). The child gets the
    # Windows PowerShell module path (not PowerShell 7's, under which it cannot load ConvertTo-SecureString). Only a short tail of its output is kept. @{ Ok; ExitCode; TimedOut; Detail; Manual }.
    param([Parameter(Mandatory)][string]$Folder, [Parameter(Mandatory)][string]$ExpectedSha, [System.Collections.IDictionary]$DependencySha = @{}, [string]$BinDir, [ValidateSet('Apply', 'DryRun')][string]$Mode = 'Apply',
          [scriptblock]$StartProcess, [int]$TimeoutSec = 300, [int]$PollMs = 300, [System.Collections.IDictionary]$ParentEnvironment, [string]$ModulePath)
    $path = Join-Path $Folder 'spike-provision.ps1'
    $switches = $(if ($Mode -eq 'DryRun') { '-DryRun' } else { '-Apply -ForceNewPassword' })
    $manual = "powershell.exe -NoProfile -ExecutionPolicy Bypass -File `"$path`" $switches   (from an elevated prompt)"
    $out = [ordered]@{ Ok = $false; ExitCode = $null; TimedOut = $false; Detail = ''; Manual = $manual }
    $dp = @(Test-Nep5ProvisionDependencies -Folder $Folder -ExpectedSha $ExpectedSha -DependencySha $DependencySha -BinDir $BinDir)
    if ($dp.Count) { $out.Detail = "REFUSED: $($dp -join '; '); spike-provision.ps1 was not run"; return $out }
    if (-not $ParentEnvironment) { $ParentEnvironment = [Environment]::GetEnvironmentVariables() }
    if (-not $ModulePath) { $ModulePath = Get-Nep5WinPsModulePath }
    $envBlock = Get-Nep5ProvisionEnvironment -Parent $ParentEnvironment -ModulePath $ModulePath
    if (-not $StartProcess) { $wd = $Folder; $StartProcess = { param($exe, $argLine, $envB) Start-Nep5Child -StartInfo (New-Nep5StartInfo -FilePath $exe -ArgumentLine $argLine -WorkingDirectory $wd -Environment $envB -Capture) }.GetNewClosure() }
    try {
        $exe = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
        $p = & $StartProcess $exe ('-NoProfile -NonInteractive -ExecutionPolicy Bypass -File "{0}" {1}' -f $path, $switches) $envBlock
        $deadline = (Get-Date).AddSeconds($TimeoutSec)
        while (-not $p.HasExited) { if ((Get-Date) -gt $deadline) { $out.TimedOut = $true; break }; Start-Sleep -Milliseconds $PollMs }
        if ($out.TimedOut) { try { $p.Kill() } catch {}; $out.Detail = "spike-provision.ps1 $switches did not finish within $TimeoutSec s; killed" }
        else { $out.ExitCode = $p.ExitCode; $out.Ok = ($p.ExitCode -eq 0); $out.Detail = "spike-provision.ps1 $switches exit $($p.ExitCode)" }
        $txt = $null; if ($p.PSObject.Methods['ReadOutput']) { $txt = $p.ReadOutput($(if ($out.TimedOut) { 1500 } else { 5000 })) }
        if ($txt) {
            $lines = @((([string]$txt.Out + "`n" + [string]$txt.Err) -split "`r?`n") | ForEach-Object { $_.Trim() } | Where-Object { $_ })
            $keep = $(if ($Mode -eq 'DryRun' -and -not $out.Ok) { @($lines | Where-Object { $_ -match 'PRECONDITION|STOPPED|DRY RUN found' } | Select-Object -First 8) } else { @($lines | Select-Object -Last 8) })
            $tl = ($keep -join ' | '); if ($tl.Length -gt 1500) { $tl = $tl.Substring(0, 1500) }
            $out.Detail += "; tail: $tl"
        }
    } catch { $out.Detail = "spike-provision.ps1 could not be run: $($_.Exception.Message)" }
    return $out
}

function New-Nep5ProvisionSeams {
    # The two scriptblocks -Run and -Remove wire into the context, built in ONE place so both entry points get the same hashing: Reprovision ({ param($c) }: spike-provision.ps1 -Apply -ForceNewPassword) and
    # ProvisionDryRun (-DryRun). Each hashes spike-provision.ps1 and spike-lib.ps1 against the proof's values and the copy sources against the bin folder immediately before the start. A missing proof hash is a
    # refusal ("not run") with the manual command. -StartProcess is a test seam.
    param([Parameter(Mandatory)][string]$Folder, [string]$ProvisionSha, [string]$LibSha, [Parameter(Mandatory)][string]$BinDir, [scriptblock]$StartProcess)
    $pf = $Folder; $ps = $ProvisionSha; $ls = $LibSha; $bd = $BinDir; $sp = $StartProcess
    $mk = {
        param($mode)
        $m = $mode; $pf = $pf; $ps = $ps; $ls = $ls; $bd = $bd; $sp = $sp
        return {
            param($c)
            if (-not $ps -or -not $ls) { return [ordered]@{ Ok = $false; ExitCode = $null; TimedOut = $false; Detail = 'no recorded hash of spike-provision.ps1 or spike-lib.ps1 (no readable proof): not run'; Manual = "powershell.exe -NoProfile -ExecutionPolicy Bypass -File `"$pf\spike-provision.ps1`" $(if ($m -eq 'DryRun') { '-DryRun' } else { '-Apply -ForceNewPassword' })   (from an elevated prompt)" } }
            $a = @{ Folder = $pf; ExpectedSha = $ps; DependencySha = @{ 'spike-lib.ps1' = $ls }; BinDir = $bd; Mode = $m }
            if ($sp) { $a.StartProcess = $sp }
            return (Invoke-Nep5Reprovision @a)
        }.GetNewClosure()
    }
    return [pscustomobject]@{ Reprovision = (& $mk 'Apply'); ProvisionDryRun = (& $mk 'DryRun') }
}

function Get-Nep5CheckSessionOpen {
    # -Check's read of the session-open record: $true when it is present OR cannot be read (an unreadable record is never "clean").
    param($FixedDir)
    try { return [bool](Test-Path -LiteralPath (Get-Nep5SessionMarkerPath -Ctx ([pscustomobject]@{ FixedDir = $FixedDir }))) } catch { return $true }
}

function Resolve-Nep5RemoveTask {
    # -Remove's task branch, taking the same context the phase runner takes (TaskOps, BinDir, OutDir, FixedDir, AccountOps, Reprovision, OriginalTaskRun). A session-open record forces the re-provision (the account
    # password may be one nobody holds); a baseline, a passed-record or non-original arguments run the proof; with none of them the task was never touched and only residue files go.
    # @{ Ex; Mismatch; Mm; HasBase; HasSession }.
    param([Parameter(Mandatory)]$Ctx)
    $mm = @(Test-Nep5TaskFileLocations -Ctx $Ctx)
    $hasBase = Test-Path -LiteralPath (Get-Nep5TaskBaselinePath -Ctx $Ctx); $hasMark = Test-Path -LiteralPath (Get-Nep5MarkerPath -Ctx $Ctx)
    $hasSession = Test-Path -LiteralPath (Get-Nep5SessionMarkerPath -Ctx $Ctx)   # a session set the account password and never proved its restore
    $argsNow = Get-Nep5TaskState -Ops $Ctx.TaskOps
    $mismatch = ($mm.Count -gt 0)
    if ($mismatch) { $ex = [ordered]@{ Ok = $false; TaskRestored = $false; RestoreWhy = 'task records mismatch'; TaskNow = $argsNow; DefinitionMatches = $null; StartedInOriginalForm = $null; Files = [ordered]@{ Ok = $true; Left = @(Get-Nep5BinResidue -BinDir $Ctx.BinDir) } } }
    elseif ($hasSession -or $hasBase -or $hasMark -or $argsNow -ne 'original') { if ($hasSession) { $Ctx.AccountOps.Changed = $true }; $ex = Exit-Nep5AccountSession -Ctx $Ctx }
    else {
        # no baseline, no taskcheck record, arguments original: the task was never touched by this matrix. Only leftover files (if any) are removed; nothing is claimed about the definition.
        $rmR = Remove-Nep5BinFiles -BinDir $Ctx.BinDir
        $ex = [ordered]@{ Ok = $rmR.Ok; TaskRestored = $true; RestoreWhy = ''; TaskNow = 'original'; DefinitionMatches = $null; StartedInOriginalForm = $null; Files = $rmR; Untouched = $true }
    }
    return [pscustomobject]@{ Ex = $ex; Mismatch = $mismatch; Mm = $mm; HasBase = [bool]$hasBase; HasSession = [bool]$hasSession }
}

function Get-Nep5TreeStamp {
    # A read-only fingerprint of a folder tree (relative path, length, last write) or '<absent>': lets a self-test prove it left a real folder alone.
    param([Parameter(Mandatory)][string]$Path)
    if (-not (Test-Path -LiteralPath $Path)) { return '<absent>' }
    $root = (Resolve-Path -LiteralPath $Path).Path.TrimEnd('\')
    return ((@(Get-ChildItem -LiteralPath $Path -Recurse -Force -ErrorAction SilentlyContinue | ForEach-Object { '{0}|{1}|{2}' -f $_.FullName.Substring($root.Length), $(if ($_.PSIsContainer) { 'd' } else { $_.Length }), $_.LastWriteTimeUtc.Ticks } | Sort-Object)) -join "`n")
}

function Install-Nep5ProbeScript {
    # Copies the probe script into the account's bin folder from bytes read ONCE: their LF-normalised SHA-256 must equal the one the proof bound, the copy is written
    # temp + move behind the plain-path guard and re-hashed. @{ Ok; Reason }.
    param([Parameter(Mandatory)][string]$ScriptFolder, [Parameter(Mandatory)][string]$BinDir, [Parameter(Mandatory)][string]$ExpectedSha, [scriptblock]$AfterCopy)
    try {
        $bytes = [IO.File]::ReadAllBytes((Join-Path $ScriptFolder $script:N5ProbeScriptName))
        if ((Get-NormalizedSha256FromBytes -Bytes $bytes) -ne $ExpectedSha.ToUpperInvariant()) { return [ordered]@{ Ok = $false; Reason = 'the probe script differs from the one the proof bound' } }
        $dest = Join-Path $BinDir $script:N5ProbeScriptName
        Assert-PlainOutputPath -Path $dest; Assert-PlainOutputPath -Path "$dest.tmp"
        [IO.File]::WriteAllBytes("$dest.tmp", $bytes); Move-Item -LiteralPath "$dest.tmp" -Destination $dest -Force
        if ($AfterCopy) { & $AfterCopy $dest }   # test seam: lets -SelfTest damage the copy so the re-hash below can be seen to refuse
        if ((Get-NormalizedSha256 -Path $dest) -ne $ExpectedSha.ToUpperInvariant()) { Remove-Item -LiteralPath $dest -Force -ErrorAction SilentlyContinue; return [ordered]@{ Ok = $false; Reason = 'the copy does not hash like the source' } }
        return [ordered]@{ Ok = $true; Reason = "copied to $dest" }
    } catch { return [ordered]@{ Ok = $false; Reason = "could not install the probe script: $($_.Exception.Message)" } }
}

function Get-Nep5BinResidue {
    # The files this matrix puts in the account's bin folder that are still there (halfset.exe is listed too: no current code copies it, a stale one is removed).
    param([Parameter(Mandatory)][string]$BinDir)
    return @(@($script:N5ProbeScriptName, 'halfset.exe', 'nep5-request.json') | Where-Object { Test-Path -LiteralPath (Join-Path $BinDir $_) })
}

function Remove-Nep5BinFiles {
    # Deletes exactly those three names from the bin folder (never a wildcard) and reads them back. @{ Ok; Left }.
    param([Parameter(Mandatory)][string]$BinDir)
    foreach ($n in @($script:N5ProbeScriptName, 'halfset.exe', 'nep5-request.json')) {
        $p = Join-Path $BinDir $n
        if (Test-Path -LiteralPath $p) { try { [IO.File]::Delete($p) } catch {} }
    }
    $left = @(Get-Nep5BinResidue -BinDir $BinDir)
    return [ordered]@{ Ok = ($left.Count -eq 0); Left = $left }
}

# The task baseline and the taskcheck record live at a FIXED place beside the matrix proof ($Ctx.FixedDir), never in the per-run -OutDir.
function Get-Nep5TaskBaselinePath { param($Ctx) return (Join-Path $Ctx.FixedDir 'task-baseline-1763-v2.xml') }
function Get-Nep5SessionMarkerPath { param($Ctx) return (Join-Path $Ctx.FixedDir 'session-open-1763.json') }

function Test-Nep5TaskFileLocations {
    # Problems (empty = consistent): a task baseline or taskcheck record in the -OutDir folder that is missing from the fixed location, or that differs from the one there. Such a mismatch means
    # the records were moved or an earlier layout left copies; nothing is trusted until a human looks (exit 9).
    param($Ctx)
    $p = @()
    if (-not $Ctx.OutDir -or -not $Ctx.FixedDir -or ([IO.Path]::GetFullPath($Ctx.OutDir).TrimEnd('\') -ieq [IO.Path]::GetFullPath($Ctx.FixedDir).TrimEnd('\'))) { return @() }
    foreach ($n in @('task-baseline-1763-v2.xml', 'taskcheck-passed-1763.json', 'session-open-1763.json')) {
        $o = Join-Path $Ctx.OutDir $n; $x = Join-Path $Ctx.FixedDir $n
        if (-not (Test-Path -LiteralPath $o -PathType Leaf)) { continue }
        if (-not (Test-Path -LiteralPath $x -PathType Leaf)) { $p += "$n exists in the output folder ($($Ctx.OutDir)) but not at the fixed location ($($Ctx.FixedDir))" }
        elseif ((Get-N5RawSha256 -Path $o) -ne (Get-N5RawSha256 -Path $x)) { $p += "$n differs between the output folder and the fixed location" }
    }
    return @($p)
}

function Get-Nep5TaskBaseline {
    # The recorded definition of the account's task before this matrix ever changed it: from this session, else from the baseline file at the fixed location beside the proof, else $null.
    param($Ctx)
    if ($Ctx.PSObject.Properties['__taskSnap'] -and $Ctx.__taskSnap) { return [string]$Ctx.__taskSnap }
    try { $p = Get-Nep5TaskBaselinePath -Ctx $Ctx; if ($Ctx.FixedDir -and (Test-Path -LiteralPath $p -PathType Leaf)) { return [IO.File]::ReadAllText($p) } } catch {}
    return $null
}

function Test-Nep5RestoredTaskStarts {
    # The restore is only proven if the task, in its ORIGINAL form, starts as the account and returns a schema-valid result (a re-registration that dropped the stored password leaves
    # every string intact and the task unable to start). $Ctx.OriginalTaskRun { param($runId) } is the arms' own probe run (spike-run-test.ps1 through the original arguments).
    param([Parameter(Mandatory)]$Ctx)
    $rid = 'nep5-restored-' + (Get-Date -Format 'HHmmssfff'); $r = $null
    try { $r = & $Ctx.OriginalTaskRun $rid } catch { return [ordered]@{ Ok = $false; Detail = "the original task could not be started: $($_.Exception.Message)" } }
    $ok = [bool]($r -and $r.valid -and [string]$r.token_sid -eq $script:N5SpikeSid)
    return [ordered]@{ Ok = $ok; Detail = $(if ($ok) { 'the restored task started as the account and returned a valid result' } else { "the restored task did NOT start as the account with a valid result (valid=$($r.valid), sid=$($r.token_sid), $($r.task_start.Detail))" }) }
}

function Test-Nep5ProvisionPreconditions {
    # The restore's own preconditions, checked BEFORE the irreversible step: spike-provision.ps1 -DryRun (read only; exit 0 = they hold) through the same verified launcher that will later run -Apply.
    # Fail-closed: no wired check, a check that throws, or a check that does not say Ok is a refusal, and a refusal means no password change. @{ Ok; Detail }.
    param([Parameter(Mandatory)]$Ctx)
    if (-not $Ctx.PSObject.Properties['ProvisionDryRun'] -or -not $Ctx.ProvisionDryRun) { return [ordered]@{ Ok = $false; Detail = 'no precondition check (spike-provision.ps1 -DryRun) is wired into this run: refused' } }
    $r = $null; try { $r = & $Ctx.ProvisionDryRun $Ctx } catch { return [ordered]@{ Ok = $false; Detail = "the precondition check could not run: $($_.Exception.Message)" } }
    return [ordered]@{ Ok = [bool]($r -and $r.Ok); Detail = $(if ($r) { [string]$r.Detail } else { 'no answer' }) }
}

function Enter-Nep5AccountSession {
    # Before the first account probe of a phase: refuse if an earlier session never finished its restore; record (or check against the recorded baseline) the account task's definition; check the restore's
    # own preconditions (spike-provision.ps1 -DryRun); install the probe script; write the session-open record; set the session password. Refuses, with nothing changed, if the task is not in its original state,
    # cannot be read, differs from the baseline, the restore's preconditions do not hold, or the account is not the recorded one. @{ Ok; Steps; Reason; OwnsRecord }. OwnsRecord is true only when THIS call wrote
    # the session-open record: only the session that wrote it may delete it. A failure AFTER the password write is cleaned up by Close-Nep5FailedSession, which re-provisions.
    param([Parameter(Mandatory)]$Ctx)
    $steps = [ordered]@{}; $owns = $false; $fail = { param($why) return [ordered]@{ Ok = $false; Steps = $steps; Reason = $why; OwnsRecord = $owns } }
    if (Test-Path -LiteralPath (Get-Nep5SessionMarkerPath -Ctx $Ctx)) { return (& $fail 'a previous session did not finish its restore (session-open-1763.json exists beside the proof and is left in place): run -Remove first') }
    $st = Get-Nep5TaskState -Ops $Ctx.TaskOps; $steps.task_before = $st
    if ($st -ne 'original') { return (& $fail "the account's task is not in its original state ($st)") }
    $snap = $null; try { $snap = [string]$Ctx.TaskOps.Snapshot() } catch { $snap = $null }
    if (-not $snap) { return (& $fail 'the account task''s definition could not be read (Export-ScheduledTask), so a restore could not be proven: nothing changed') }
    $bf = Get-Nep5TaskBaselinePath -Ctx $Ctx; $saved = $null
    try { if (Test-Path -LiteralPath $bf -PathType Leaf) { $saved = [IO.File]::ReadAllText($bf) } } catch {}
    if ($saved -and $saved -cne $snap) { return (& $fail 'the account task''s definition differs from the baseline recorded before this matrix first changed anything (something changed it, or an earlier restore damaged it): nothing changed. After a deliberate re-key, and only once you have confirmed the task works, delete task-baseline-1763-v2.xml beside the proof and run -Run -Phase taskcheck to record a new one') }
    if (-not $saved) { try { Assert-PlainOutputPath -Path $bf; [IO.File]::WriteAllText($bf, $snap); $steps.baseline = "recorded in $bf" } catch { return (& $fail "the task baseline could not be recorded: $($_.Exception.Message)") } }
    $Ctx | Add-Member -NotePropertyName __taskSnap -NotePropertyValue $snap -Force
    $pre = Test-Nep5ProvisionPreconditions -Ctx $Ctx; $steps.provision_preconditions = $pre
    if (-not $pre.Ok) { return (& $fail "the restore's own preconditions do not hold, so no password is changed (spike-provision.ps1 -DryRun: $($pre.Detail))") }
    $ins = Install-Nep5ProbeScript -ScriptFolder $Ctx.ScriptFolder -BinDir $Ctx.BinDir -ExpectedSha $Ctx.ProbeSha; $steps.probe_script = $ins
    if (-not $ins.Ok) { return (& $fail $ins.Reason) }
    $owns = $true
    try { Write-JsonGuarded -Path (Get-Nep5SessionMarkerPath -Ctx $Ctx) -Object ([ordered]@{ kind = 'nep5-session-open'; at = (Get-N5Now); note = 'the account password was (or is about to be) changed; -Remove re-provisions the task' }) -Depth 3 } catch { return (& $fail "the session-open record could not be written: $($_.Exception.Message)") }
    $pw = $Ctx.AccountOps.SetPassword(); $steps.password = [ordered]@{ ok = [bool]$pw.Ok; reason = [string]$pw.Reason; changed = [bool]$Ctx.AccountOps.Changed }
    if (-not $pw.Ok) { return (& $fail $pw.Reason) }
    return [ordered]@{ Ok = $true; Steps = $steps; Reason = 'probe installed, session password set'; OwnsRecord = $true }
}

function Exit-Nep5AccountSession {
    # Always, every exit path: release the session password, remove the files from the bin folder, and - if the password was (or may have been) changed - restore the original task
    # credential with spike-provision.ps1 -Apply -ForceNewPassword. Then PROVE the restore: the arguments read original; the task's normalised definition equals the baseline recorded before the
    # first change; and the task started in its ORIGINAL form returns a valid result as the account. TaskRestored needs all of it (and a successful re-provision when one was needed); a missing
    # baseline is "not proven". The session-open record is removed only when the restore is proven.
    param([Parameter(Mandatory)]$Ctx)
    $ops = $Ctx.AccountOps
    if ($ops) { try { $ops.Drop() } catch {} }
    $rm = Remove-Nep5BinFiles -BinDir $Ctx.BinDir
    $needRep = [bool]($ops -and $ops.Changed); $rep = $null; $why = @()
    if ($needRep) {
        try { $rep = & $Ctx.Reprovision $Ctx } catch { $rep = [ordered]@{ Ok = $false; Detail = $_.Exception.Message; Manual = '' } }
        if ($rep.Ok) { if ($ops) { $ops.Changed = $false } } else { $why += "re-provisioning the task failed ($($rep.Detail)); run by hand: $($rep.Manual)" }
    }
    $now = Get-Nep5TaskState -Ops $Ctx.TaskOps
    $base = Get-Nep5TaskBaseline -Ctx $Ctx; $snapNow = $null; try { $snapNow = [string]$Ctx.TaskOps.Snapshot() } catch {}
    $defMatch = $(if ($null -eq $base -or -not $snapNow) { $null } else { [bool]($snapNow -ceq $base) })
    $start = $null
    if ($now -ne 'original') { $why += "the task's arguments read '$now'" }
    if ($null -eq $base) { $why += 'no recorded baseline of the task definition: the restore is NOT PROVEN' }
    elseif (-not $snapNow) { $why += 'the task definition could not be read back' }
    elseif (-not $defMatch) { $why += 'the task definition differs from its recorded baseline (principal, logon type, action or settings)' }
    $repOk = (-not $needRep) -or [bool]($rep -and $rep.Ok)
    if ($now -eq 'original' -and $defMatch -eq $true -and $repOk) { $start = Test-Nep5RestoredTaskStarts -Ctx $Ctx; if (-not $start.Ok) { $why += $start.Detail } }
    else { $why += 'the restored task was not started (an earlier check already failed)' }
    $restored = ($now -eq 'original' -and $defMatch -eq $true -and $repOk -and [bool]($start -and $start.Ok))
    if ($restored) { try { $mp = Get-Nep5SessionMarkerPath -Ctx $Ctx; if (Test-Path -LiteralPath $mp) { [IO.File]::Delete($mp) } } catch {} }
    return [ordered]@{ Ok = ($restored -and $rm.Ok); TaskRestored = $restored; RestoreWhy = ($why -join '; '); TaskNow = $now; DefinitionMatches = $defMatch; Reprovision = $rep; StartedInOriginalForm = $(if ($start) { $start } else { $null }); Files = $rm; At = (Get-N5Now) }
}

function Close-Nep5FailedSession {
    # After an Enter-Nep5AccountSession that did NOT succeed. If the password was changed (Changed true) the full Exit applies. Otherwise nothing was changed: the files this matrix put in the bin folder are removed,
    # and the session-open record is deleted ONLY when this session wrote it ($Enter.OwnsRecord): a refusal because a record already exists leaves that record exactly as it was, because it is the only backstop for
    # the session that wrote it. The result never claims a restore (TaskRestored $null): nothing was changed and nothing was proven.
    param([Parameter(Mandatory)]$Ctx, [Parameter(Mandatory)]$Enter)
    if ($Ctx.AccountOps -and $Ctx.AccountOps.Changed) { return (Exit-Nep5AccountSession -Ctx $Ctx) }
    $rm = Remove-Nep5BinFiles -BinDir $Ctx.BinDir
    $owns = [bool]($Enter.Contains('OwnsRecord') -and $Enter.OwnsRecord)
    if ($owns) { try { $mp = Get-Nep5SessionMarkerPath -Ctx $Ctx; if (Test-Path -LiteralPath $mp) { [IO.File]::Delete($mp) } } catch {} }
    return [ordered]@{ Ok = $rm.Ok; Untouched = $true; TaskRestored = $null; SessionRecordKept = (-not $owns); RestoreWhy = ''; TaskNow = [string]$Enter.Steps['task_before']; Files = $rm; At = (Get-N5Now) }
}

function Get-Nep5SessionExitRecord {
    # PURE. The phase record for a session exit that was not Ok, or $null: class task_not_restored (exit 9; names the re-key command) when the restore was not PROVEN, removal_unverified when only files remain.
    param($Ex)
    if (-not $Ex -or $Ex.Ok) { return $null }
    if ($Ex.Contains('Untouched') -and $Ex.Untouched) {
        return [ordered]@{ state = 'session_exit'; pass = 0; class = 'removal_unverified'; reason = "nothing was changed, but file(s) remain in the account's bin folder: $(@($Ex.Files.Left) -join ', ')"; steps = [ordered]@{ session_exit = $Ex } }
    }
    if (-not $Ex.TaskRestored) {
        return [ordered]@{ state = 'session_exit'; pass = 0; class = 'task_not_restored'; reason = "TASK NOT RESTORED ($($Ex.RestoreWhy)). The account's task may be unable to start. From an elevated prompt run: spike-provision.ps1 -Apply -ForceNewPassword (the full command is in the record), then run -Run -Phase taskcheck again. No later phase will run until taskcheck passes."; steps = [ordered]@{ session_exit = $Ex } }
    }
    return [ordered]@{ state = 'session_exit'; pass = 0; class = 'removal_unverified'; reason = "the task is restored but file(s) remain in the account's bin folder: $(@($Ex.Files.Left) -join ', ')"; steps = [ordered]@{ session_exit = $Ex } }
}

function Get-Nep5MarkerPath { param($Ctx) return (Join-Path $Ctx.FixedDir 'taskcheck-passed-1763.json') }
function Write-Nep5TaskcheckMarker {
    param($Ctx, $Ex)
    Write-JsonGuarded -Path (Get-Nep5MarkerPath -Ctx $Ctx) -Object ([ordered]@{ kind = 'nep5-taskcheck-passed'; at = (Get-N5Now); proof_stamp = [string]$Ctx.ProofStamp; definition_matches_baseline = $Ex.DefinitionMatches; restored_task_started = [bool]($Ex.StartedInOriginalForm -and $Ex.StartedInOriginalForm.Ok) }) -Depth 4
}
function Remove-Nep5TaskcheckMarker { param($Ctx) try { $p = Get-Nep5MarkerPath -Ctx $Ctx; if (Test-Path -LiteralPath $p) { [IO.File]::Delete($p) } } catch {} }
function ConvertTo-Nep5InstantSeconds {
    # PURE. A timestamp however a host handed it back (an ISO string, or the [datetime] that ConvertFrom-Json under PowerShell 7 makes of one) as UTC ticks truncated to the second, or $null when it is not a
    # readable instant (fail closed: the caller treats $null as a mismatch). Never compares text: [string] of a [datetime] is a culture format that has lost the fraction.
    param($Value)
    try {
        if ($null -eq $Value) { return $null }
        if ($Value -is [datetimeoffset]) { $d = $Value }
        elseif ($Value -is [datetime]) { $d = [datetimeoffset]$Value }
        else {
            $s = ([string]$Value).Trim(); $parsed = [datetimeoffset]::MinValue
            if (-not $s -or -not [datetimeoffset]::TryParse($s, [Globalization.CultureInfo]::InvariantCulture, [Globalization.DateTimeStyles]::None, [ref]$parsed)) { return $null }
            $d = $parsed
        }
        $t = [long]$d.UtcTicks
        return [long]($t - ($t % 10000000L))
    } catch { return $null }
}

function Test-Nep5TaskcheckMarker {
    # Problems (empty = a phase other than taskcheck may start): taskcheck passed, with the restored task started in its original form, under the SAME matrix proof, in the last 24 hours.
    param($Ctx, [datetimeoffset]$Now = [datetimeoffset]::Now)
    $p = Get-Nep5MarkerPath -Ctx $Ctx
    if (-not (Test-Path -LiteralPath $p -PathType Leaf)) { return @('taskcheck has not passed for this proof: run -Run -Phase taskcheck first (it proves the account''s task can be put back and still starts)') }
    $m = $null; try { $m = ConvertFrom-Json ([IO.File]::ReadAllText($p)) } catch { return @('the taskcheck record does not parse: run -Run -Phase taskcheck again') }
    $probs = @()
    if ([string]$m.kind -ne 'nep5-taskcheck-passed' -or $m.restored_task_started -ne $true -or $m.definition_matches_baseline -ne $true) { $probs += 'the taskcheck record does not show a proven restore' }
    # the stamp is an ISO instant: compared as instants (to the second, UTC), never as text, because ConvertFrom-Json under PowerShell 7 turns it into a [datetime]; an unreadable stamp on either side is a mismatch
    $stA = ConvertTo-Nep5InstantSeconds $m.proof_stamp; $stB = ConvertTo-Nep5InstantSeconds $Ctx.ProofStamp
    if ($null -eq $stA -or $null -eq $stB -or $stA -ne $stB) { $probs += 'the taskcheck record belongs to another matrix proof (or its stamp is unreadable): run -Run -Phase taskcheck again' }
    try { if (($Now - (ConvertTo-DateTimeOffset $m.at)).TotalHours -gt 24) { $probs += 'the taskcheck record is older than 24 hours' } } catch { $probs += 'the taskcheck record has no readable time' }
    return @($probs)
}

# ---- the account's probe: request, validated result, rows ---------------------------------------------------------------------------------------
function Resolve-Nep5AccountResult {
    # PURE. Judges the parsed result of the account's probe against the request: right kind and schema, the run id, the mode, a token SID equal to the expected one, overall
    # done, a clean error, the started time not earlier than the request, and for connect mode exactly the requested (family, port) rows in order with a known outcome
    # and an integer socket code. @{ Valid; Problems }. A result that fails any of this is "no result", never "blocked".
    param($Request, $Result, [string]$ExpectedSid, [datetimeoffset]$RequestedAt)
    $p = New-Object System.Collections.ArrayList
    if ($null -eq $Result) { return [ordered]@{ Valid = $false; Problems = @('no result') } }
    if ([string]$Result.kind -ne 'nep5-probe') { [void]$p.Add('result is not a nep5-probe') }
    if ($Result.schema_version -ne 1) { [void]$p.Add("schema_version $($Result.schema_version) is not 1") }
    if ([string]$Result.run_id -ne [string]$Request.run_id) { [void]$p.Add("run_id '$($Result.run_id)' is not '$($Request.run_id)'") }
    if ([string]$Result.mode -ne [string]$Request.mode) { [void]$p.Add("mode '$($Result.mode)' is not '$($Request.mode)'") }
    if ([string]$Result.token_sid -ne $ExpectedSid) { [void]$p.Add("the probe ran as '$($Result.token_sid)', not as the expected account SID") }
    if ([string]$Result.overall -ne 'done') { [void]$p.Add("overall is '$($Result.overall)' ($($Result.error))") }
    try { if ((ConvertTo-DateTimeOffset $Result.started) -lt $RequestedAt.AddSeconds(-5)) { [void]$p.Add("result.started $($Result.started) predates the request written at $($RequestedAt.ToString('o'))") } } catch { [void]$p.Add("result.started unreadable: $($_.Exception.Message)") }
    if ([string]$Request.mode -eq 'connect') {
        $rows = @($Result.targets); $want = @($Request.targets)
        if ($rows.Count -ne $want.Count) { [void]$p.Add("expected $($want.Count) rows, got $($rows.Count)") }
        else {
            for ($i = 0; $i -lt $want.Count; $i++) {
                if ([string]$rows[$i].family -ne [string]$want[$i].family -or [int]$rows[$i].port -ne [int]$want[$i].port) { [void]$p.Add("row $i is $($rows[$i].family):$($rows[$i].port), not the requested $($want[$i].family):$($want[$i].port)") }
                if ([string]$rows[$i].result -notin @('connected', 'blocked', 'refused', 'timeout', 'error')) { [void]$p.Add("row $i has an unknown outcome '$($rows[$i].result)'") }
                if (-not ($rows[$i].win32 -is [int] -or $rows[$i].win32 -is [long])) { [void]$p.Add("row $i has no integer socket code") }
            }
        }
    }
    if ([string]$Request.mode -eq 'direct') {
        $d = $Result.direct
        if (-not $d) { [void]$p.Add('direct mode returned no direct record') }
        else {
            if ([string]$d.op -cne [string]$Request.direct.op) { [void]$p.Add("direct.op '$($d.op)' is not the requested '$($Request.direct.op)'") }
            if ([string]$d.phase -notin @('open', 'call', 'refused', 'compile', 'error')) { [void]$p.Add("direct.phase '$($d.phase)' is unknown") }
            if ([string]$d.phase -in @('open', 'call') -and [string]$d.rc_hex -notmatch '^0x[0-9A-F]{8}$') { [void]$p.Add("direct.rc_hex '$($d.rc_hex)' is not a status") }
            if ([string]$d.verdict -notin @('succeeded', 'denied', 'open_failed', 'compile_failed', 'refused', 'other')) { [void]$p.Add("direct.verdict '$($d.verdict)' is unknown") }
        }
    }
    return [ordered]@{ Valid = ($p.Count -eq 0); Problems = @($p) }
}

function Invoke-Nep5RealAccountRunBody {
    # ONE probe run as the account: the operator writes the request file, AccountOps starts the child as the account (hard timeout, killed at the limit), the result file the child wrote in the
    # account's results folder is read as untrusted data and judged. Needs the session password (Enter-Nep5AccountSession).
    param([string]$BinDir, [string]$ResultsDir, [string]$ExpectedSid, [int]$TimeoutSec, $AccountOps, $RunId, $Request, $Tick)
    $o = [pscustomobject]@{ Started = $false; Valid = $false; Problems = @(); Result = $null; Detail = ''; Launch = $null }
    $reqAt = [datetimeoffset]::Now
    $Request['written'] = (Get-N5Now)
    try { Write-JsonAtomic -Path (Join-Path $BinDir 'nep5-request.json') -Object $Request } catch { $o.Problems = @("the request file could not be written: $($_.Exception.Message)"); return $o }
    $run = $AccountOps.RunProbe($TimeoutSec, $Tick)
    $o.Started = [bool]$run.Started; $o.Detail = [string]$run.Detail; $o.Launch = $run.Launch
    if (-not $run.Started) { $o.Problems = @("the probe did not start: $($run.Detail)"); return $o }
    if ($run.TimedOut) { $o.Problems = @("the probe did not finish within $TimeoutSec s (killed: $($run.Killed))"); return $o }
    $path = Join-Path $ResultsDir "result-$RunId.json"
    if (-not (Test-PathExistsNoFollow $path)) { $o.Problems = @("the probe exited ($($run.Detail)) but wrote no result file"); return $o }
    $res = $null; try { $res = Read-UntrustedJson -Path $path } catch { $o.Problems = @("the result file could not be read: $($_.Exception.Message)"); return $o }
    $o.Result = $res
    $j = Resolve-Nep5AccountResult -Request ([pscustomobject]$Request) -Result $res -ExpectedSid $ExpectedSid -RequestedAt $reqAt
    $o.Valid = $j.Valid; $o.Problems = @($j.Problems)
    return $o
}

function New-Nep5RealAccountRun {
    # The real AccountRun: Invoke-Nep5RealAccountRunBody with this session's AccountOps.
    param([Parameter(Mandatory)][string]$BinDir, [Parameter(Mandatory)][string]$ExpectedSid, [Parameter(Mandatory)]$AccountOps, [string]$ResultsDir, [int]$TimeoutSec = 90)
    $bin = $BinDir; $sid = $ExpectedSid; $to = $TimeoutSec; $ao = $AccountOps; $rd = $(if ($ResultsDir) { $ResultsDir } else { Join-Path $script:SpikeRoot 'results' })
    return { param($runId, $request, $tick) Invoke-Nep5RealAccountRunBody -BinDir $bin -ResultsDir $rd -ExpectedSid $sid -TimeoutSec $to -AccountOps $ao -RunId $runId -Request $request -Tick $tick }.GetNewClosure()
}

function Invoke-Nep5FakeAccountBody {
    param($World, $Switches, $RunId, $Request, $Tick)
    [void]$Switches.Calls.Add($Request)
    $o = [pscustomobject]@{ Started = (-not $Switches.NoStart); Valid = $false; Problems = @(); Result = $null; Detail = 'fake'; Launch = [ordered]@{ logon_type = 'fake'; environment_variable_names_supplied = @('fake'); working_folder = 'fake' } }
    if ($Switches.NoStart) { $o.Problems = @('the task did not start: fake'); return $o }
    if ($Tick) { & $Tick }
    $w = $World; $rows = @()
    if ($Request.mode -eq 'connect') {
        foreach ($t in @($Request.targets)) {
            $layer = $t.family
            $blocked = (-not $Switches.IgnoreBlocks) -and (@($w.Filters.Values | Where-Object { $_.Layer -eq $layer -and $_.Action -eq 'block' -and $_.Sid -eq $script:N5SpikeSid }).Count -gt 0)
            $permitted = (@($w.Filters.Values | Where-Object { $_.Layer -eq $layer -and $_.Action -eq 'permit' -and $_.HasRemote -and -not $_.HasUser -and $_.RemotePort -eq [int]$t.port }).Count -gt 0) -or
                         (@($w.Filters.Values | Where-Object { $_.Layer -eq $layer -and $_.Kind -eq 'permit-loopback-user' -and $_.Sid -eq $script:N5SpikeSid -and [int]$t.port -ge 60080 -and [int]$t.port -le 60089 }).Count -gt 0)
            if ($blocked -and -not $permitted) { $rows += [ordered]@{ family = $t.family; port = $t.port; result = 'blocked'; win32 = 10013; ms = 1; error = '' } }
            else { $rows += [ordered]@{ family = $t.family; port = $t.port; result = 'connected'; win32 = 0; ms = 1; error = '' } }
        }
    }
    $direct = $null
    if ($Request.mode -eq 'direct') {
        $addKey = $script:N5FilterKeys['s2-n1-probe-v4']; $delKey = $script:N5FilterKeys['s2-block-v4']
        if ($Request.direct.op -ceq 'add') {
            if ($Switches.AllowAdd) { $w.Filters[$addKey] = [pscustomobject]@{ Key = $addKey; SubLayer = $script:N5SubLayers.S2; Layer = 'v4'; Name = 'BlarAI #1763 n1-add-attempt'; Kind = ''; Tool = ''; Sid = $script:N5SpikeSid; HasUser = $true; Action = 'block' }; $rc = '0x00000000'; $v = 'succeeded' } else { $rc = $Switches.DenyRc; $v = 'denied' }
        } else {
            if ($Switches.AllowDelete) { $w.Filters.Remove($delKey); $rc = '0x00000000'; $v = 'succeeded' } else { $rc = $Switches.DenyRc; $v = 'denied' }
        }
        if ($Switches.DirectOverride) { $rc = $Switches.DirectOverride.rc_hex; $v = $Switches.DirectOverride.verdict; $direct = [ordered]@{ op = $Request.direct.op; phase = $Switches.DirectOverride.phase; rc_hex = $rc; verdict = $v; error = $null } }
        else { $direct = [ordered]@{ op = $Request.direct.op; phase = 'call'; rc_hex = $rc; verdict = $v; error = $null } }
    }
    $res = [pscustomobject]@{ schema_version = 1; kind = 'nep5-probe'; run_id = $Request.run_id; mode = $Request.mode; started = (Get-N5Now); finished = (Get-N5Now); token_sid = $(if ($Switches.Invalid) { 'S-1-5-21-1-2-3-1001' } else { $Switches.TokenSid }); token_name = 'fake'
                              expected_sid = $Switches.TokenSid; targets = $rows; direct = $direct; error = $null; overall = 'done' }
    $j = Resolve-Nep5AccountResult -Request ([pscustomobject]$Request) -Result $res -ExpectedSid $script:N5SpikeSid -RequestedAt ([datetimeoffset]::Now.AddMinutes(-1))
    $o.Result = $res; $o.Valid = $j.Valid; $o.Problems = @($j.Problems)
    return $o
}

function New-Nep5FakeAccountRun {
    # A fake AccountRun over the fake world. A connect request is answered from the world: a filter at the family's layer that blocks (user condition = the spike SID) blocks the
    # target unless a permit for the exact (127.0.0.1, port) with no user condition, or an srt-win loopback permit for the account on a port in 60080-60089, exists. A direct request
    # (N1) is DENIED (rc 0x00000005) unless AllowAdd / AllowDelete say the account's token may write, in which case it acts on the fake world; DirectOverride replaces the answer.
    # The result is built in the probe's own schema and still goes through Resolve-Nep5AccountResult. Switches: Invalid (wrong token SID), NoStart, IgnoreBlocks (never blocked).
    # The runner carries .Switches (Calls = every request it saw).
    param([Parameter(Mandatory)]$World, [bool]$Invalid = $false, [bool]$NoStart = $false, [string]$TokenSid = $script:N5SpikeSid, [bool]$IgnoreBlocks = $false, [bool]$AllowAdd = $false, [bool]$AllowDelete = $false, $DirectOverride = $null)
    $sw = [pscustomobject]@{ Invalid = $Invalid; NoStart = $NoStart; TokenSid = $TokenSid; IgnoreBlocks = $IgnoreBlocks; AllowAdd = $AllowAdd; AllowDelete = $AllowDelete; DirectOverride = $DirectOverride; DenyRc = '0x00000005'; Calls = (New-Object System.Collections.ArrayList) }
    $w = $World
    $run = { param($runId, $request, $tick) Invoke-Nep5FakeAccountBody -World $w -Switches $sw -RunId $runId -Request $request -Tick $tick }.GetNewClosure()
    $run | Add-Member -NotePropertyName Switches -NotePropertyValue $sw -Force
    return $run
}

function Invoke-Nep5AccountConnects {
    # One run of the account's probe over the RUNNABLE targets. @{ Valid; Problems; Rows; Summary; NotRun }.
    param([Parameter(Mandatory)]$Ctx, [Parameter(Mandatory)][string]$RunId, [Parameter(Mandatory)]$Targets, [scriptblock]$Tick)
    $run = @($Targets | Where-Object { $_.Runnable }); $notRun = @($Targets | Where-Object { -not $_.Runnable } | ForEach-Object { "$($_.Key): NOT RUN (the listener did not bind)" })
    if ($run.Count -eq 0) { return [ordered]@{ Valid = $false; Problems = @('no runnable target'); Rows = @(); Summary = [ordered]@{}; NotRun = $notRun } }
    $req = [ordered]@{ run_id = $RunId; mode = 'connect'; timeout_ms = 3000; targets = @($run | ForEach-Object { [ordered]@{ family = $_.Family; port = $_.Port } }) }
    $r = & $Ctx.AccountRun $RunId $req $Tick
    $rows = @(); if ($r.Result -and $r.Result.targets) { $rows = @($r.Result.targets) }
    return [ordered]@{ Valid = [bool]$r.Valid; Problems = @($r.Problems); Rows = $rows; Summary = $(if ($r.Valid) { Get-Nep5RowsSummary $rows } else { [ordered]@{} }); NotRun = $notRun; Detail = $r.Detail; Launch = $r.Launch }
}

function Invoke-Nep5OperatorConnects {
    # The operator's own connects to the same listeners (the control and the "during" reading). @{ ok = all; Rows }.
    param([Parameter(Mandatory)]$Ctx, [Parameter(Mandatory)]$Targets)
    $rows = @()
    foreach ($t in @($Targets | Where-Object { $_.Runnable })) { $r = & $Ctx.OperatorConnect $t.Family $t.Port; $rows += [ordered]@{ target = $t.Key; ok = [bool]$r.ok; ms = $r.ms; error = [string]$r.error } }
    return [ordered]@{ ok = (@($rows | Where-Object { -not $_.ok }).Count -eq 0 -and $rows.Count -gt 0); Rows = $rows }
}

# ---- the operator watchdog: two failed connects in a row remove everything by key and stop -------------------------------------------------------
function Invoke-Nep5TickStep {
    # One watchdog step (kept in a function: a scriptblock closure cannot see $script: variables). Every $Gap seconds one operator connect to the outside; two consecutive
    # failures run $OnAbort (remove by key), set the abort flag and record the removal.
    param($State, [scriptblock]$Probe, [scriptblock]$OnAbort, [double]$Gap)
    $now = $State.Clock.Elapsed.TotalSeconds
    if (($now - $State.LastAt) -lt $Gap) { return }
    $State.LastAt = $now
    $w = & $Probe
    $abort = Update-WatchdogState -State $State -Ok ([bool]$w.ok) -When ([string]$w.t) -Message ([string]$w.error) -Ms ([long]$w.ms)
    if ($abort -and -not $script:opAbort) { $script:opAbort = $true; $State.Aborted = $true; $State['AbortRemoval'] = (& $OnAbort) }
}

function New-Nep5Tick {
    # Returns the Tick scriptblock the task driver's wait loops call, and the watchdog state it feeds.
    param([Parameter(Mandatory)][scriptblock]$Probe, [Parameter(Mandatory)][scriptblock]$OnAbort, [double]$MinGapSeconds = 2.0)
    $state = New-WatchdogState; $pr = $Probe; $ab = $OnAbort; $gap = $MinGapSeconds
    $tick = { Invoke-Nep5TickStep -State $state -Probe $pr -OnAbort $ab -Gap $gap }.GetNewClosure()
    return [pscustomobject]@{ Tick = $tick; State = $state }
}

# ---- state setup ------------------------------------------------------------------------------------------------------------------------------
function Add-Nep5State {
    # Puts ONE state in place through the proof-gated adders. srt-win states: the harness install in S1, then the named filters deleted by key from an enumeration (each by
    # role; exactly one filter must match a role). @{ Ok; Reason; Detail }. Never leaves a half-built state unreported: the caller always removes by key afterwards.
    param([Parameter(Mandatory)]$Ctx, [Parameter(Mandatory)]$State)
    $sid = Get-Nep5SidFor $State.Sid
    $sp = @(& $Ctx.SidProblemsFor $sid)
    switch ($State.Kind) {
        'none' { return [ordered]@{ Ok = $true; Reason = 'nothing to add (control state)'; Detail = $null } }
        'ours' {
            $plan = Get-Nep5OurPlan -Id $State.Plan -Sid $sid
            $a = Add-Nep5OurPlan -Runner $Ctx.Runner -Backend $Ctx.Backend -Plan $plan -SidProblems $sp -Proof $Ctx.Proof
            return [ordered]@{ Ok = [bool]$a.Ok; Reason = $a.Reason; Detail = $a; Stop = [bool]$a.Stop; Plan = $plan }
        }
        'srt' {
            $a = Add-Nep5SrtWinSet -Runner $Ctx.Runner -Backend $Ctx.Backend -SubLayer $script:N5SubLayers.S1 -Sid $sid -SidProblems $sp -Proof $Ctx.Proof
            if (-not $a.Ok) { return [ordered]@{ Ok = $false; Reason = $a.Reason; Detail = $a } }
            $deleted = @()
            foreach ($role in @($State.Delete)) {
                $en = Invoke-Halfset -Runner $Ctx.Runner -Argv @('enum', '--sublayer', $script:N5SubLayers.S1)
                $pe = $(if ($en.ExitCode -eq 0) { ConvertFrom-HarnessFilters -Json $en.Json } else { [ordered]@{ Ok = $false; Rows = @(); Problem = "exit $($en.ExitCode)" } })
                if (-not $pe.Ok) { return [ordered]@{ Ok = $false; Reason = "could not enumerate S1 to pick the $role filter: $($pe.Problem)"; Detail = $a } }
                $hit = @($pe.Rows | Where-Object { (Get-SrtRole $_) -eq $role })
                if ($hit.Count -ne 1) { return [ordered]@{ Ok = $false; Reason = "expected exactly one $role filter in S1, found $($hit.Count)"; Detail = $a } }
                $d = Invoke-Halfset -Runner $Ctx.Runner -Argv @('delete-filter', '--sublayer', $script:N5SubLayers.S1, '--key', $hit[0].Key)
                $deleted += [ordered]@{ role = $role; key = $hit[0].Key; exit = $d.ExitCode; outcome = $d.Outcome }
                if ($d.ExitCode -ne 0) { return [ordered]@{ Ok = $false; Reason = "delete-filter of the $role filter exited $($d.ExitCode) ($($d.Outcome))"; Detail = $a; Deleted = $deleted } }
            }
            return [ordered]@{ Ok = $true; Reason = 'installed' + $(if ($deleted.Count) { ", then deleted: $((@($deleted | ForEach-Object { $_.role })) -join ', ')" } else { '' }); Detail = $a; Deleted = $deleted }
        }
        default { throw "Add-Nep5State: kind '$($State.Kind)' has no add" }
    }
}

function Get-Nep5Readings {
    # Step 4 of the cycle: srt-win's status on S1 (the harness), the enumeration of S1/S2/S3, and (for our rows) the plan's own objects by key (PRESENT / ABSENT / PARTIAL).
    param([Parameter(Mandatory)]$Ctx, $Plan)
    $out = [ordered]@{ status_word = 'unparsed'; status_raw = $null; enum = [ordered]@{}; our_keys = $null }
    $st = Invoke-Halfset -Runner $Ctx.Runner -Argv @('status', '--sublayer', $script:N5SubLayers.S1)
    $out.status_word = $(if ($st.ExitCode -eq 0) { Get-SrtStatusWord $st.Json } else { "harness_exit_$($st.ExitCode)" }); $out.status_raw = $st.Stdout
    foreach ($id in $script:N5SubLayers.Keys) {
        $en = Invoke-Halfset -Runner $Ctx.Runner -Argv @('enum', '--sublayer', $script:N5SubLayers[$id])
        $pe = $(if ($en.ExitCode -eq 0) { ConvertFrom-HarnessFilters -Json $en.Json } else { [ordered]@{ Ok = $false; Rows = @(); Problem = "exit $($en.ExitCode)" } })
        $out.enum[$id] = [ordered]@{ readable = [bool]$pe.Ok; n = @($pe.Rows).Count; filters = @($pe.Rows | ForEach-Object { [ordered]@{ key = $_.Key; layer = $_.Layer; name = $_.Name; kind = $_.Kind; sid = $_.Sid; role = (Get-SrtRole $_) } }) }
    }
    if ($Plan) {
        $objs = @(); $unknown = $false
        $items = @(); if ($Plan.Provider) { $items += , @('provider', $script:N5ProviderKey, 'provider') }; if ($Plan.SubLayer) { $items += , @('sublayer', $Plan.SubLayer, 'sublayer') }
        foreach ($f in @($Plan.Filters) + @($Plan.Attempts)) { if ($f) { $items += , @('filter', $f.Key, $f.Id) } }
        foreach ($i in $items) { try { $fl = [long]$Ctx.Backend.Flags($i[0], $i[1]); $objs += [ordered]@{ kind = $i[0]; id = $i[2]; key = $i[1]; present = ($fl -ge 0); flags = $(if ($fl -ge 0) { '0x{0:X}' -f $fl } else { $null }) } } catch { $unknown = $true; $objs += [ordered]@{ kind = $i[0]; id = $i[2]; key = $i[1]; present = $null; flags = $null } } }
        $pres = @($objs | Where-Object { $_.present -eq $true }).Count
        $out.our_keys = [ordered]@{ state = $(if ($unknown) { 'UNKNOWN' } elseif ($pres -eq 0) { 'ABSENT' } elseif ($pres -eq $objs.Count) { 'PRESENT' } else { 'PARTIAL' }); objects = $objs }
    }
    return $out
}

function Get-Nep5SweepSummary {
    # The sweep record without the export text (which can be megabytes); the export's path, hash and hit counts stay.
    param($Sw)
    return [ordered]@{ label = $Sw.Label; at = $Sw.At; clean = $Sw.Clean; stop = $Sw.Stop; unreadable = $Sw.Unreadable; not_clean = @($Sw.NotClean); problems = @($Sw.Problems); sublayers = $Sw.SubLayers; provider_present = $Sw.ProviderPresent; foreign = @($Sw.Foreign | ForEach-Object { "$($_.Key)@$($_.SubLayer)" }); export = $Sw.Export }
}

# ---- one cycle: sweep, control, add, record, probe, remove, sweep -----------------------------------------------------------------------------------
function Invoke-Nep5StateCycle {
    # The six steps, in the fixed order, for ONE state and ONE pass. Returns the record (with Class). The add is reachable only after step 1 read clean and step 2's
    # controls held. The removal and the direct sweep run on every exit path once anything may have been added.
    param([Parameter(Mandatory)]$Ctx, [Parameter(Mandatory)]$State, [Parameter(Mandatory)][int]$Pass)
    $label = "$($State.Id)-p$Pass"; $runId = ('nep5-{0}-p{1}-{2}' -f $State.Id.ToLowerInvariant(), $Pass, (Get-Date -Format 'HHmmss'))
    $rec = [ordered]@{ state = $State.Id; pass = $Pass; title = $State.Title; kind = $State.Kind; started = (Get-N5Now); clock = (Get-Date -Format 'yyyy-MM-dd HH:mm:ss K'); class = 'inconclusive'; reason = ''; steps = [ordered]@{}; commands = @(); summary = '' }
    $script:N5CommandLog = New-Object System.Collections.ArrayList
    $targets = Get-Nep5Targets -Bound $Ctx.Bound
    $script:opAbort = $false
    $mayHave = $false; $plan = $null
    $gap = if ($null -ne $Ctx.TickGap) { [double]$Ctx.TickGap } else { 2.0 }
    $wd = New-Nep5Tick -Probe $Ctx.OperatorProbe -OnAbort ({ Remove-Nep5All -Runner $Ctx.Runner -Backend $Ctx.Backend }.GetNewClosure()) -MinGapSeconds $gap
    try {
        # 1. direct sweep: refuse to add on anything else
        $sw1 = Invoke-Nep5DirectSweep -Runner $Ctx.Runner -Backend $Ctx.Backend -Exporter $Ctx.Exporter -Label "$label-before"
        $rec.steps.sweep_before = Get-Nep5SweepSummary $sw1
        if ($sw1.Stop) { $rec.class = 'stop'; $rec.reason = 'a filter of ours or srt-win''s sits outside S1/S2/S3: STOP, nothing added or cleaned'; return $rec }
        if (-not $sw1.Clean) { $rec.class = 'refused'; $rec.reason = "the sweep before the add is not clean ($((@($sw1.NotClean) + @($sw1.Problems)) -join '; ')): nothing added"; return $rec }
        if ($State.Kind -eq 'n1') { $mayHave = $true; return (Invoke-Nep5N1Body -Ctx $Ctx -State $State -Pass $Pass -Rec $rec -Targets $targets -Tick $wd.Tick -RunId $runId -Label $label) }
        # 2. control: the account and the operator connect BEFORE any filter
        if ($Ctx.PSObject.Properties['Listeners'] -and $Ctx.Listeners) { [void](Clear-Nep5Backlog $Ctx.Listeners) }
        $ctlOp = @(1..3 | ForEach-Object { & $Ctx.OperatorProbe })
        $opLoop = Invoke-Nep5OperatorConnects -Ctx $Ctx -Targets $targets
        $ctlAcc = Invoke-Nep5AccountConnects -Ctx $Ctx -RunId "$runId-ctl" -Targets $targets -Tick $wd.Tick
        $rec.steps.control = [ordered]@{ operator_outside = @($ctlOp | ForEach-Object { [bool]$_.ok }); operator_loopback = $opLoop; account = $ctlAcc }
        $accOpen = ($ctlAcc.Valid -and @($ctlAcc.Summary.Values | Where-Object { $_ -ne 'open' }).Count -eq 0)
        if (@($ctlOp | Where-Object { -not $_.ok }).Count -gt 0 -or -not $opLoop.ok -or -not $accOpen) { $rec.class = 'control_failed'; $rec.reason = 'the control did not hold before any filter (operator offline, a listener unreachable, or the account was not open on every target): nothing added'; return $rec }
        # 3. add the state
        $mayHave = $true
        $add = Add-Nep5State -Ctx $Ctx -State $State; if ($add.Plan) { $plan = $add.Plan }
        $rec.steps.add = $add
        if ($add.Stop) { $rec.class = 'finding_stop'; $rec.reason = $add.Reason; return $rec }
        if (-not $add.Ok) { $rec.class = $(if ($add.Detail -and $add.Detail.Refused) { 'refused' } else { 'inconclusive' }); $rec.reason = "the state could not be put in place: $($add.Reason)"; return $rec }
        # 4. record: srt-win status, enumeration, our keys
        $rec.steps.readings = Get-Nep5Readings -Ctx $Ctx -Plan $plan
        # 5. through the gate: the account's connects and the operator's, watchdog running
        if ($Ctx.PSObject.Properties['Listeners'] -and $Ctx.Listeners) { [void](Clear-Nep5Backlog $Ctx.Listeners) }
        $opDuring = Invoke-Nep5OperatorConnects -Ctx $Ctx -Targets $targets
        $acc = Invoke-Nep5AccountConnects -Ctx $Ctx -RunId "$runId-during" -Targets $targets -Tick $wd.Tick
        & $wd.Tick
        $rec.steps.during = [ordered]@{ operator_loopback = $opDuring; account = $acc }
        if ($script:opAbort) { $rec.class = 'operator_abort'; $rec.reason = 'two operator connects failed in a row: everything was removed by key'; return $rec }
        if (-not $acc.Valid) { $rec.class = 'inconclusive'; $rec.reason = "the account's probe gave no valid result under the state: $(@($acc.Problems) -join '; ')"; return $rec }
        $rec.class = 'ok'
        $rec.summary = "$($State.Id): status=$($rec.steps.readings.status_word); account " + ((@($acc.Summary.GetEnumerator() | ForEach-Object { "$($_.Key)=$($_.Value)" })) -join ' ') + $(if (@($acc.NotRun).Count) { "; NOT RUN: $(@($acc.NotRun | ForEach-Object { ($_ -split ':')[0..1] -join ':' }) -join ', ')" } else { '' })
    } catch {
        $rec.class = 'inconclusive'; $rec.reason = "error: $($_.Exception.Message)"; $rec.steps.error = $_.ScriptStackTrace; $mayHave = $true
    } finally {
        # 6. remove by key, then the direct checks of step 1
        if ($mayHave -or $script:opAbort) {
            $rm = Remove-Nep5All -Runner $Ctx.Runner -Backend $Ctx.Backend
            $sw2 = Invoke-Nep5DirectSweep -Runner $Ctx.Runner -Backend $Ctx.Backend -Exporter $Ctx.Exporter -Label "$label-after"
            $rec.steps.removal = [ordered]@{ ok = $rm.Ok; steps = @($rm.Steps); errors = @($rm.Errors) }
            $rec.steps.sweep_after = Get-Nep5SweepSummary $sw2
            if (-not $sw2.Clean) { $rec.class = $(if ($sw2.Stop) { 'stop' } else { 'removal_unverified' }); $rec.reason = "the direct checks after the removal do not read clean: $((@($sw2.NotClean) + @($sw2.Problems)) -join '; ')" }
        }
        $w = $wd.State; $rec.steps.watchdog = [ordered]@{ connects = $w.Count; failures = $w.Fail; max_consecutive_failures = $w.MaxConsec; aborted = [bool]$w.Aborted; failure_events = @($w.Events) }
        $rec.commands = @($script:N5CommandLog); $rec.finished = (Get-N5Now)
    }
    return $rec
}

function Invoke-Nep5N1Body {
    # N1: the account's OWN standard token makes ONE direct FwpmFilterAdd0 against S2 and ONE direct FwpmFilterDeleteByKey0 of our test filter (no harness: its install and delete cannot
    # record a write verdict for a token that cannot enumerate). S2, our provider and one test block exist first (added by us, elevated), so the engine's answer is about the write and
    # not about a missing sublayer. Expected: both denied. A success on either is a finding: everything is removed by key and the run stops (class finding_stop). The caller's finally
    # removes and sweeps.
    param($Ctx, $State, $Pass, $Rec, $Targets, $Tick, $RunId, $Label)
    $s2 = $script:N5SubLayers.S2
    $enter = Enter-Nep5AccountSession -Ctx $Ctx
    $Rec.steps.session = $enter
    if (-not $enter.Ok) {
        $cl = Close-Nep5FailedSession -Ctx $Ctx -Enter $enter; $Rec.steps.session_exit = $cl
        $Rec.class = 'refused'; $Rec.reason = "the account session could not be set up: $($enter.Reason)"
        $er = Get-Nep5SessionExitRecord -Ex $cl; if ($er) { $Ctx.__sessionRec = $er }
        return $Rec
    }
    try {
        $sid = Get-Nep5SidFor 'spike'
        $plan = Get-Nep5OurPlan -Id 'o1' -Sid $sid
        $add = Add-Nep5OurPlan -Runner $Ctx.Runner -Backend $Ctx.Backend -Plan $plan -SidProblems @(& $Ctx.SidProblemsFor $sid) -Proof $Ctx.Proof
        $Rec.steps.add = $add
        if (-not $add.Ok) { $Rec.class = $(if ($add.Refused) { 'refused' } else { 'inconclusive' }); $Rec.reason = "the test filter could not be added: $($add.Reason)"; return $Rec }
        $delKey = $plan.Filters[0].Key; $addKey = $script:N5FilterKeys['s2-n1-probe-v4']
        # a) the account's add
        $r1 = & $Ctx.AccountRun "$RunId-add" ([ordered]@{ run_id = "$RunId-add"; mode = 'direct'; timeout_ms = 5000; direct = [ordered]@{ op = 'add' } }) $Tick
        $c1 = Get-Nep5N1Class -Run $r1
        $addedNow = $null; try { $addedNow = ([long]$Ctx.Backend.Flags('filter', $addKey) -ge 0) } catch { $addedNow = $null }
        $Rec.steps.n1_add = [ordered]@{ class = $c1.Class; code = $c1.Code; valid = $r1.Valid; problems = @($r1.Problems); direct = $(if ($r1.Result) { $r1.Result.direct } else { $null }); launch = $r1.Launch; filter_present_after = $addedNow }
        if ($addedNow -eq $true -or $c1.Class -eq 'succeeded') { $Rec.class = 'finding_stop'; $Rec.reason = 'FINDING: the account''s non-elevated token ADDED a filter to a test sublayer (removed by key below)'; return $Rec }
        # b) the account's delete
        $r2 = & $Ctx.AccountRun "$RunId-del" ([ordered]@{ run_id = "$RunId-del"; mode = 'direct'; timeout_ms = 5000; direct = [ordered]@{ op = 'delete' } }) $Tick
        $c2 = Get-Nep5N1Class -Run $r2
        $stillThere = $null; try { $stillThere = ([long]$Ctx.Backend.Flags('filter', $delKey) -ge 0) } catch { $stillThere = $null }
        $Rec.steps.n1_delete = [ordered]@{ class = $c2.Class; code = $c2.Code; valid = $r2.Valid; problems = @($r2.Problems); direct = $(if ($r2.Result) { $r2.Result.direct } else { $null }); launch = $r2.Launch; filter_still_present = $stillThere }
        if ($stillThere -eq $false -or $c2.Class -eq 'succeeded') { $Rec.class = 'finding_stop'; $Rec.reason = 'FINDING: the account''s non-elevated token DELETED one of our test filters (everything removed by key below)'; return $Rec }
        if ($null -eq $addedNow -or $null -eq $stillThere) { $Rec.class = 'inconclusive'; $Rec.reason = 'a test filter could not be read after an attempt'; return $Rec }
        if ($c1.Class -eq 'denied' -and $c2.Class -eq 'denied') { $Rec.class = 'ok'; $Rec.reason = "both denied by the engine at the call (add: $($c1.Code); delete: $($c2.Code))" }
        else { $Rec.class = 'inconclusive'; $Rec.reason = "not both a plain engine denial at the call: add=$($c1.Class)/$($c1.Code), delete=$($c2.Class)/$($c2.Code)" }
        $Rec.summary = "N1: add=$($c1.Class) ($($c1.Code)); delete=$($c2.Class) ($($c2.Code))"
        return $Rec
    } finally {
        $ex = Exit-Nep5AccountSession -Ctx $Ctx; $Rec.steps.session_exit = $ex
        $er = Get-Nep5SessionExitRecord -Ex $ex; if ($er) { $Ctx.__sessionRec = $er }
    }
}

function Get-Nep5N1Class {
    # PURE on the direct record of the account's probe. succeeded | denied (the call's status was ACCESS_DENIED, code kept verbatim) | other (any other status at the call, or a
    # failure at the open / compile) | no_result. Only `denied` is the expected answer.
    param($Run)
    if (-not $Run -or -not $Run.Valid -or -not $Run.Result -or -not $Run.Result.direct) { return [ordered]@{ Class = 'no_result'; Code = '' } }
    $d = $Run.Result.direct
    switch ([string]$d.verdict) { 'succeeded' { return [ordered]@{ Class = 'succeeded'; Code = [string]$d.rc_hex } } 'denied' { return [ordered]@{ Class = 'denied'; Code = [string]$d.rc_hex } } default { return [ordered]@{ Class = 'other'; Code = ("$($d.verdict) $($d.phase) $($d.rc_hex)").Trim() } } }
}

# ---- phases -----------------------------------------------------------------------------------------------------------------------------------------
function Get-Nep5PhaseExit {
    # PURE. The exit code of a phase from its cycle records: 9 beats 7 beats 5 beats 4 beats 0 (2 is a refusal before anything ran).
    param($Records)
    $c = @($Records | ForEach-Object { $_.class })
    if (@($c | Where-Object { $_ -in @('stop', 'operator_abort', 'finding_stop', 'task_not_restored', 'task_files_mismatch') }).Count) { return 9 }
    if ($c -contains 'removal_unverified') { return 7 }
    if ($c -contains 'control_failed') { return 5 }
    if ($c -contains 'refused') { return 2 }
    if ($c -contains 'inconclusive') { return 4 }
    return 0
}

function Invoke-Nep5PreCleanup {
    # The first live action of every -Run: srt-win's set that an earlier probe left in S1 for the test account (and nothing else) is removed with the harness `uninstall` (then, if that
    # fails, by key) and S1 is read back ABSENT by the direct checks. Anything that is not exactly that pattern (a filter outside S1, anything in S2/S3, our provider, a filter that is
    # not srt-win-tagged or not for the test account's SID) is NOT removed here: it is a STOP or a refusal for the operator. @{ Ok; Class; Reason; Steps }.
    param([Parameter(Mandatory)]$Ctx)
    $s1 = $script:N5SubLayers.S1
    $sw = Invoke-Nep5DirectSweep -Runner $Ctx.Runner -Backend $Ctx.Backend -Exporter $Ctx.Exporter -Label 'pre-clean-before'
    $out = [ordered]@{ Ok = $false; Class = 'refused'; Reason = ''; Steps = [ordered]@{ sweep_before = (Get-Nep5SweepSummary $sw) } }
    if ($sw.Clean) { $out.Ok = $true; $out.Class = 'ok'; $out.Reason = 'nothing to remove: the machine reads clean'; return $out }
    if ($sw.Stop) { $out.Class = 'stop'; $out.Reason = 'a filter of ours or srt-win''s sits outside S1/S2/S3: STOP, nothing removed'; return $out }
    $res = Get-Nep5Residue -Runner $Ctx.Runner -Backend $Ctx.Backend
    if (-not $res.Readable) { $out.Reason = "the engine could not be read: $(@($res.Problems) -join '; ')"; return $out }
    $s1rows = @($res.Rows | Where-Object { $_.SubLayer -eq $s1 })
    $other = @($res.Rows | Where-Object { $_.SubLayer -ne $s1 })
    $notSet = @($s1rows | Where-Object { $_.Tool -ne 'srt-win' -or $_.Sid -ne $script:N5SpikeSid })
    $s2s3 = @($script:N5SubLayers.Keys | Where-Object { $_ -ne 'S1' } | Where-Object { $res.SubLayers[$_].present -eq $true })
    if ($s1rows.Count -lt 1) { $out.Reason = 'the machine is not clean but S1 holds no srt-win set for the test account: nothing is removed automatically (run -Check, then -Remove)'; return $out }
    if ($other.Count -or $notSet.Count -or $s2s3.Count -or $res.ProviderPresent) { $out.Reason = 'the leftovers are not exactly an srt-win set for the test account in S1 (other filters, S2/S3 or our provider present): nothing is removed automatically (run -Check, then -Remove)'; return $out }
    $un = Invoke-Halfset -Runner $Ctx.Runner -Argv @('uninstall', '--sublayer', $s1)
    $out.Steps.uninstall = [ordered]@{ exit = $un.ExitCode; outcome = $un.Outcome; stdout = $un.Stdout }
    if ($un.ExitCode -ne 0) { $rm = Remove-Nep5All -Runner $Ctx.Runner -Backend $Ctx.Backend; $out.Steps.by_key = [ordered]@{ ok = $rm.Ok; steps = @($rm.Steps); errors = @($rm.Errors) } }
    $sw2 = Invoke-Nep5DirectSweep -Runner $Ctx.Runner -Backend $Ctx.Backend -Exporter $Ctx.Exporter -Label 'pre-clean-after'
    $out.Steps.sweep_after = Get-Nep5SweepSummary $sw2
    if ($sw2.Clean) { $out.Ok = $true; $out.Class = 'ok'; $out.Reason = "removed a pre-existing srt-win set ($($s1rows.Count) filter(s)) from S1; S1 reads absent by the direct checks" }
    else { $out.Class = 'removal_unverified'; $out.Reason = "the pre-existing set was not removed or does not read clean: $((@($sw2.NotClean) + @($sw2.Problems)) -join '; ')" }
    return $out
}

function Get-Nep5ResultsPath {
    # A results file per run: nep5-results-<phase>-<run stamp>.json, never an earlier run's file (a counter is added if the name exists).
    param($Ctx, [string]$Phase)
    $stamp = if ($Ctx.PSObject.Properties['RunStamp'] -and $Ctx.RunStamp) { [string]$Ctx.RunStamp } else { Get-Date -Format 'yyyyMMdd-HHmmss' }
    $base = "nep5-results-$Phase-$stamp"; $p = Join-Path $Ctx.OutDir "$base.json"; $n = 1
    while (Test-Path -LiteralPath $p) { $n++; $p = Join-Path $Ctx.OutDir "$base-$n.json" }
    return $p
}

function Save-Nep5Results {
    param($Ctx, $Results)
    Write-JsonGuarded -Path $Results.path -Object $Results -Depth 16
}

function Invoke-Nep5TaskCheck {
    # Phase taskcheck: set the session password, run the identity probe AS THE ACCOUNT, run one connect probe against a bound loopback listener (no filter exists, so it must connect), then restore the
    # task with spike-provision.ps1 and PROVE it (arguments, definition against the baseline, the restored task started in its original form). Only a proven restore writes the record that lets any
    # later phase run.
    param([Parameter(Mandatory)]$Ctx)
    $rec = [ordered]@{ state = 'taskcheck'; pass = 1; started = (Get-N5Now); class = 'inconclusive'; reason = ''; steps = [ordered]@{} }
    $enter = Enter-Nep5AccountSession -Ctx $Ctx; $rec.steps.session = $enter
    if (-not $enter.Ok) {
        $rec.class = 'refused'; $rec.reason = $enter.Reason
        $cl = Close-Nep5FailedSession -Ctx $Ctx -Enter $enter; $rec.steps.session_exit = $cl
        $er = Get-Nep5SessionExitRecord -Ex $cl; if ($er) { $rec.class = $er.class; $rec.reason = $er.reason; Remove-Nep5TaskcheckMarker -Ctx $Ctx }
        $rec.finished = (Get-N5Now); return $rec
    }
    $ex = $null
    try {
        $rid = 'nep5-taskcheck-' + (Get-Date -Format 'HHmmss')
        $r = & $Ctx.AccountRun $rid ([ordered]@{ run_id = $rid; mode = 'identity'; timeout_ms = 3000 }) $null
        $rec.steps.identity = [ordered]@{ started = $r.Started; valid = $r.Valid; problems = @($r.Problems); token_sid = $(if ($r.Result) { $r.Result.token_sid } else { $null }); launch = $r.Launch }
        $tg = @(Get-Nep5Targets -Bound $Ctx.Bound | Where-Object { $_.Key -eq "v4:$($script:N5PortOut)" -and $_.Runnable })
        if (-not $r.Valid) { $rec.reason = "the probe gave no valid identity result as the account: $(@($r.Problems) -join '; ')" }
        elseif ($tg.Count -eq 0) { $rec.reason = 'the loopback listener did not bind, so the connect probe could not run' }
        else {
            $rid2 = 'nep5-taskcheck-c-' + (Get-Date -Format 'HHmmss')
            $r2 = & $Ctx.AccountRun $rid2 ([ordered]@{ run_id = $rid2; mode = 'connect'; timeout_ms = 3000; targets = @([ordered]@{ family = 'v4'; port = $script:N5PortOut }) }) $null
            $row = if ($r2.Result -and $r2.Result.targets) { @($r2.Result.targets)[0] } else { $null }
            $rec.steps.connect = [ordered]@{ valid = $r2.Valid; problems = @($r2.Problems); row = $row; launch = $r2.Launch }
            if ($r2.Valid -and $row -and [string]$row.result -eq 'connected') { $rec.class = 'ok'; $rec.reason = 'the probe started as the account, returned its token SID and connected to a bound loopback listener' }
            else { $rec.reason = "the connect probe as the account gave no valid 'connected' row: $(@($r2.Problems) -join '; ')" }
        }
    } catch {
        $rec.class = 'inconclusive'; $rec.reason = "error in the taskcheck body: $($_.Exception.Message)"; $rec.steps.error = $_.ScriptStackTrace
    } finally {
        $ex = Exit-Nep5AccountSession -Ctx $Ctx; $rec.steps.session_exit = $ex
        $er = Get-Nep5SessionExitRecord -Ex $ex
        if ($er) { $rec.class = $er.class; $rec.reason = $er.reason; Remove-Nep5TaskcheckMarker -Ctx $Ctx }
        elseif ($rec.class -eq 'ok') { Write-Nep5TaskcheckMarker -Ctx $Ctx -Ex $ex; $rec.reason += '; the task was restored and PROVEN: re-provisioned, arguments, definition against the baseline, and the restored task started as the account' }
        $rec.finished = (Get-N5Now)
    }
    return $rec
}

function Invoke-Nep5Phase {
    # Runs one phase: every state of it, for the requested number of passes, in order. Stops at once on stop / operator abort / finding / removal not verified / control failure;
    # other classes are recorded and the next state runs. The results file is rewritten after every cycle. The account session (session password, probe copy in the bin folder) is entered once and left
    # in a finally. @{ ExitCode; Records }.
    param([Parameter(Mandatory)]$Ctx, [Parameter(Mandatory)][ValidateSet('taskcheck', 'halfset', 'ours', 'n1')][string]$Phase)
    $results = [ordered]@{ kind = 'nep5-results'; phase = $Phase; path = (Get-Nep5ResultsPath -Ctx $Ctx -Phase $Phase); started = (Get-N5Now); passes = $Ctx.Passes; records = @(); finished = $null; exit_code = $null }
    $records = New-Object System.Collections.ArrayList
    $Ctx | Add-Member -NotePropertyName __mayHave -NotePropertyValue $false -Force
    $Ctx | Add-Member -NotePropertyName __sessionRec -NotePropertyValue $null -Force
    $Ctx | Add-Member -NotePropertyName PreCleanupOk -NotePropertyValue $false -Force
    $stopNow = { param($r) $r.class -in @('stop', 'operator_abort', 'finding_stop', 'removal_unverified', 'control_failed', 'task_not_restored', 'task_files_mismatch') }
    $done = { $results.records = @($records); $results.exit_code = Get-Nep5PhaseExit $records; $results.finished = (Get-N5Now); Save-Nep5Results -Ctx $Ctx -Results $results; [pscustomobject]@{ ExitCode = $results.exit_code; Records = @($records); ResultsPath = $results.path } }
    $mm = @(Test-Nep5TaskFileLocations -Ctx $Ctx)
    if ($mm.Count) { [void]$records.Add([ordered]@{ state = 'task_files'; pass = 0; class = 'task_files_mismatch'; reason = "the task records in the output folder do not match the fixed location: $($mm -join '; '). Nothing was run." }); return (& $done) }
    if ($Phase -ne 'taskcheck') {
        $mk = @(Test-Nep5TaskcheckMarker -Ctx $Ctx)
        if ($mk.Count) { [void]$records.Add([ordered]@{ state = 'taskcheck_required'; pass = 0; class = 'refused'; reason = ($mk -join '; ') }); return (& $done) }
    }
    $pre = Invoke-Nep5PreCleanup -Ctx $Ctx
    $results.pre_cleanup = $pre
    if (-not $pre.Ok) {
        [void]$records.Add([ordered]@{ state = 'pre_cleanup'; pass = 0; class = $pre.Class; reason = $pre.Reason; steps = [ordered]@{ pre_cleanup = $pre } })
        return (& $done)
    }
    $Ctx.PreCleanupOk = $true   # from here on a run may remove by key in its finally: it got past the pre-cleanup
    if ($pre.Class -eq 'ok' -and $pre.Steps.Contains('uninstall')) { Write-Host $pre.Reason -ForegroundColor Yellow }
    if ($Phase -eq 'taskcheck') {
        $r = Invoke-Nep5TaskCheck -Ctx $Ctx; [void]$records.Add($r)
        return (& $done)
    }
    $states = @($script:N5States | Where-Object { $_.Phase -eq $Phase -and (-not $Ctx.Only -or @($Ctx.Only) -contains $_.Id) })
    $needsSession = ($Phase -ne 'n1')
    $session = $null; $entered = $false
    try {
        if ($needsSession) {
            $session = Enter-Nep5AccountSession -Ctx $Ctx; $entered = [bool]$session.Ok
            if (-not $session.Ok) {
                $cl = Close-Nep5FailedSession -Ctx $Ctx -Enter $session
                $r = [ordered]@{ state = 'session'; pass = 0; class = 'refused'; reason = "the account session could not be set up: $($session.Reason)"; steps = [ordered]@{ session = $session; cleanup = $cl } }; [void]$records.Add($r)
                $er = Get-Nep5SessionExitRecord -Ex $cl; if ($er) { [void]$records.Add($er); Remove-Nep5TaskcheckMarker -Ctx $Ctx }
            }
        }
        if ($records.Count -eq 0) {
            :outer foreach ($s in $states) {
                foreach ($pass in 1..$Ctx.Passes) {
                    $r = Invoke-Nep5StateCycle -Ctx $Ctx -State $s -Pass $pass
                    [void]$records.Add($r)
                    $results.records = @($records); Save-Nep5Results -Ctx $Ctx -Results $results
                    if ($r.summary) { Write-Host $r.summary -ForegroundColor Cyan } else { Write-Host ("{0} pass {1}: {2}: {3}" -f $r.state, $r.pass, $r.class, $r.reason) -ForegroundColor Yellow }
                    if (& $stopNow $r) { break outer }
                    if ($r.class -in @('refused')) { break outer }
                }
            }
        }
    } finally {
        if ($needsSession -and $entered) {
            $ex = Exit-Nep5AccountSession -Ctx $Ctx
            $results.session_exit = $ex
            $er = Get-Nep5SessionExitRecord -Ex $ex; if ($er) { [void]$records.Add($er) }
        } elseif ($Ctx.__sessionRec) { [void]$records.Add($Ctx.__sessionRec) }
        if (@($records | Where-Object { $_.class -eq 'task_not_restored' }).Count) { Remove-Nep5TaskcheckMarker -Ctx $Ctx }
    }
    return (& $done)
}

function Invoke-Nep5RunCore {
    # The body of -Run behind the entry point's setup, so the self-test can drive it with a fake context. Runs the phase; then, ONLY if the run got past the pre-cleanup (it added or may have
    # added something of its own), removes by key again; always ends with a read-only direct sweep. A run that was refused or stopped by the pre-cleanup (or by the taskcheck gate) removes
    # NOTHING: what is there is left for a human, with the exit code of the refusal. Returns @{ Code; Removed; PastPreCleanup; Final; Phase }.
    param([Parameter(Mandatory)]$Ctx, [Parameter(Mandatory)][string]$Phase, [Parameter(Mandatory)][scriptblock]$FinalExporter)
    $code = 4; $r = $null; $removed = $false; $final = $null; $past = $false
    try { $r = Invoke-Nep5Phase -Ctx $Ctx -Phase $Phase; $code = $r.ExitCode }
    catch { Write-Host "ERROR: $($_.Exception.Message)" -ForegroundColor Red; Write-Host $_.ScriptStackTrace -ForegroundColor DarkGray; $code = 4 }
    finally {
        $past = [bool]($Ctx.PSObject.Properties['PreCleanupOk'] -and $Ctx.PreCleanupOk)
        try {
            if ($past) { $null = Remove-Nep5All -Runner $Ctx.Runner -Backend $Ctx.Backend; $removed = $true }
            else { Write-Host 'The run did not get past the pre-cleanup: NOTHING was removed. What is in S1/S2/S3 is left as found for you to read (-Check).' -ForegroundColor Yellow }
            $sw = Invoke-Nep5DirectSweep -Runner $Ctx.Runner -Backend $Ctx.Backend -Exporter $FinalExporter -Label 'final'
            $final = Get-Nep5SweepSummary $sw
            Write-Host '== final direct checks =='; Write-SweepLines $sw
            if ($past -and -not $sw.Clean) { $code = $(if ($sw.Stop) { 9 } else { 7 }); Write-Host 'LEFTOVERS: run -Remove, then the README''s manual rollback.' -ForegroundColor Red }
        } catch { if ($past) { $code = 7 }; Write-Host "the final check could not run: $($_.Exception.Message)" -ForegroundColor Red }
    }
    if ($r) { foreach ($rec in @($r.Records)) { if ($rec.class -eq 'task_not_restored') { Write-Host $rec.reason -ForegroundColor Red } } }
    return [pscustomobject]@{ Code = $code; Removed = $removed; PastPreCleanup = $past; Final = $final; Phase = $r }
}
