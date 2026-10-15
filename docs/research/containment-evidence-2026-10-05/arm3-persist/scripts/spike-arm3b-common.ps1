#requires -Version 5.1
<#
.SYNOPSIS
  Arm 3b shared pieces (the arming script, the post-reboot script and the veto script all dot-source this after spike-lib.ps1,
  spike-persist-lib.ps1 and spike-task-driver.ps1). Functions only; no side effects on load, no param block.

.DESCRIPTION
  * Get-Arm3bTaskDefinitions: the two SYSTEM tasks the arming script registers, as data (printed by -DryRun, asserted by
    -SelfTest). blarai-arm3b-post-reboot runs at startup; blarai-arm3b-veto fires once, VetoMinutes after arming.
  * Register-Arm3bTask: turns one definition into a registered task.
  * The armed-state file (arm3b-armed.json): what the arming script wrote, read by the veto and post-reboot scripts.
  * Wait-NetworkUp: polls an operator connect (no filter touches the operator or SYSTEM) until it works or times out.
#>

$script:Arm3bPostName = 'blarai-arm3b-post-reboot'
$script:Arm3bVetoName = 'blarai-arm3b-veto'
$script:Arm3bWrapperName = 'blarai-arm3b-arm-run'

function Get-Arm3bTaskDefinitions {
    # PURE. Both tasks run as SYSTEM, RunLevel Highest; paths are baked absolute because SYSTEM has no user profile.
    param([Parameter(Mandatory)][string]$Folder, [Parameter(Mandatory)][string]$OutDir, [Parameter(Mandatory)][string]$Wfp,
          [string]$PostName = $script:Arm3bPostName, [string]$VetoName = $script:Arm3bVetoName, [string]$WrapperName = $script:Arm3bWrapperName,
          [datetime]$Now = (Get-Date), [int]$VetoMinutes = 30, [string]$WfpSha256 = '', [string]$CodeSetId = '')
    $common = '-OutDir "{0}" -WfpScript "{1}" -TaskName {2} -VetoTaskName {3} -WrapperTaskName {4}' -f $OutDir, $Wfp, $PostName, $VetoName, $WrapperName
    # The SYSTEM tasks turn text from the wrapped script into code: they pin the hash taken at arming and refuse any other file.
    if ($WfpSha256) { $common += " -WfpSha256 $WfpSha256" }
    # ... and the id of the code set taken at arming: they verify it (the libraries they loaded plus the other scripts on disk) before doing anything else.
    if ($CodeSetId) { $common += " -CodeSetId $CodeSetId" }
    $post = [pscustomobject]@{
        TaskName = $PostName; TaskPath = '\BlarAI\'; User = 'NT AUTHORITY\SYSTEM'; LogonType = 'ServiceAccount'; RunLevel = 'Highest'
        Trigger = 'AtStartup'; TriggerDelay = 'PT1M'; TriggerAt = $null; Execute = 'powershell.exe'
        Arguments = ('-NoProfile -ExecutionPolicy Bypass -File "{0}" -Live {1}' -f (Join-Path $Folder 'spike-arm3b-post-reboot.ps1'), $common)
        ExecutionTimeLimitMinutes = 60
        Purpose = 'after the reboot: wait for the network, probe the account, check the fence, export, REMOVE the persistent set by key, verify, write post-reboot-result.json, delete this task'
    }
    $veto = [pscustomobject]@{
        TaskName = $VetoName; TaskPath = '\BlarAI\'; User = 'NT AUTHORITY\SYSTEM'; LogonType = 'ServiceAccount'; RunLevel = 'Highest'
        Trigger = 'Once'; TriggerDelay = $null; TriggerAt = $Now.AddMinutes($VetoMinutes); Execute = 'powershell.exe'
        Arguments = ('-NoProfile -ExecutionPolicy Bypass -File "{0}" -Live {1}' -f (Join-Path $Folder 'spike-arm3b-veto.ps1'), $common)
        ExecutionTimeLimitMinutes = 20
        Purpose = "veto watchdog: $VetoMinutes minutes after arming, if the machine has NOT rebooted: shutdown /a, remove the set by key, delete the startup task, record 'reboot vetoed'"
    }
    return [pscustomobject]@{ Post = $post; Veto = $veto }
}

function Register-Arm3bTask {
    param([Parameter(Mandatory)]$Def)
    $a = New-ScheduledTaskAction -Execute $Def.Execute -Argument $Def.Arguments
    if ($Def.Trigger -eq 'AtStartup') { $t = New-ScheduledTaskTrigger -AtStartup; $t.Delay = $Def.TriggerDelay } else { $t = New-ScheduledTaskTrigger -Once -At $Def.TriggerAt }
    $p = New-ScheduledTaskPrincipal -UserId $Def.User -LogonType ServiceAccount -RunLevel Highest
    $s = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Minutes $Def.ExecutionTimeLimitMinutes)
    Register-ScheduledTask -TaskName $Def.TaskName -TaskPath $Def.TaskPath -Action $a -Trigger $t -Principal $p -Settings $s -Description ('BlarAI arm 3b: ' + $Def.Purpose) -Force | Out-Null
}

function Get-TaskStateOrNull {
    param([string]$Name, [string]$Path = '\BlarAI\')
    try { $t = Get-ScheduledTask -TaskPath $Path -TaskName $Name -ErrorAction Stop; return [string]$t.State } catch { return $null }
}

function Write-ArmedState {
    param([Parameter(Mandatory)][string]$OutDir, [Parameter(Mandatory)]$Object)
    New-Item -ItemType Directory -Force $OutDir | Out-Null
    Write-JsonGuarded -Path (Join-Path $OutDir 'arm3b-armed.json') -Object $Object -Depth 8
}

function Read-ArmedState {
    # Returns the parsed armed-state object, or $null when there is none or it cannot be read (callers treat that as "unknown").
    param([Parameter(Mandatory)][string]$OutDir)
    $p = Join-Path $OutDir 'arm3b-armed.json'
    if (-not (Test-Path -LiteralPath $p)) { return $null }
    try { return (ConvertFrom-Json ([IO.File]::ReadAllText($p))) } catch { return $null }
}

function Wait-NetworkUp {
    # Polls an operator-side connect to 1.1.1.1:443 (no filter of this arm touches SYSTEM or the operator). Returns what happened.
    param([int]$TimeoutSeconds = 600, [int]$PollSeconds = 5, [scriptblock]$Connect = { Test-TcpConnect '1.1.1.1' 443 3000 }, [scriptblock]$Sleep = { param($s) Start-Sleep -Seconds $s }, [scriptblock]$Clock = { Get-Date })
    $t0 = & $Clock; $attempts = 0; $lastError = ''
    while ($true) {
        $attempts++
        $r = & $Connect
        if ($r.ok) { return [ordered]@{ up = $true; attempts = $attempts; seconds = [Math]::Round(((& $Clock) - $t0).TotalSeconds, 1); last_error = '' } }
        $lastError = [string]$r.error
        if (((& $Clock) - $t0).TotalSeconds -ge $TimeoutSeconds) { return [ordered]@{ up = $false; attempts = $attempts; seconds = [Math]::Round(((& $Clock) - $t0).TotalSeconds, 1); last_error = $lastError } }
        & $Sleep $PollSeconds
    }
}

function ConvertTo-ArmedIso { param($Value) if ($null -eq $Value) { return $null }; return (ConvertTo-DateTimeOffset $Value) }
