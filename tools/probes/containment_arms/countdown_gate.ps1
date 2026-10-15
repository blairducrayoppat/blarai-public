#requires -Version 7.0
<#
.SYNOPSIS
  A visible countdown the operator can stop, shown before a test that could briefly affect his own network traffic.

.DESCRIPTION
  Shows (1) a Windows toast notification and (2) a small always-on-top window with a countdown and a large
  STOP button. The window stays up for -Seconds. Exit code 0 means the countdown reached zero (proceed);
  exit code 1 means the operator pressed STOP or closed the window (do not proceed); exit code 2 means the
  window could not be shown (do not proceed: a warning that cannot be seen is not a warning).
  -SelfTest checks the pure helpers and shows nothing.

  The toast is raised from Windows PowerShell 5.1 (the only host with the Windows Runtime projection) under
  PowerShell's own application identity; if the toast cannot be raised the window alone is still shown.
#>
[CmdletBinding()]
param(
    [int]$Seconds = 120,
    [string]$Title = 'BlarAI test starting',
    [string]$Message = 'A network test will start when the countdown ends. Press STOP to cancel it.',
    [switch]$SelfTest,
    [switch]$NoToast
)
$ErrorActionPreference = 'Stop'

function Format-Remaining {
    # PURE. Seconds -> m:ss.
    param([int]$Remaining)
    if ($Remaining -lt 0) { $Remaining = 0 }
    '{0}:{1:00}' -f [math]::Floor($Remaining / 60), ($Remaining % 60)
}

function Test-SecondsValid {
    # PURE. The countdown must be long enough to read and short enough not to stall a session.
    param([int]$Seconds)
    return ($Seconds -ge 5 -and $Seconds -le 900)
}

function Get-ExitCode {
    # PURE. Only a countdown that ran to zero without a stop proceeds.
    param([bool]$Stopped, [bool]$ReachedZero, [bool]$ShownOk)
    if (-not $ShownOk) { return 2 }
    if ($Stopped) { return 1 }
    if ($ReachedZero) { return 0 }
    return 1
}

if ($SelfTest) {
    $fail = 0
    function Check([string]$n, [bool]$c) { if ($c) { Write-Host "  [PASS] $n" } else { Write-Host "  [FAIL] $n"; $script:fail++ } }
    Check 'format 120 -> 2:00' ((Format-Remaining 120) -eq '2:00')
    Check 'format 65 -> 1:05' ((Format-Remaining 65) -eq '1:05')
    Check 'format negative clamps to 0:00' ((Format-Remaining -3) -eq '0:00')
    Check 'seconds 4 rejected, 5 and 900 accepted, 901 rejected' (-not (Test-SecondsValid 4) -and (Test-SecondsValid 5) -and (Test-SecondsValid 900) -and -not (Test-SecondsValid 901))
    Check 'zero without stop proceeds' ((Get-ExitCode $false $true $true) -eq 0)
    Check 'stop wins over zero' ((Get-ExitCode $true $true $true) -eq 1)
    Check 'window not shown never proceeds' ((Get-ExitCode $false $true $false) -eq 2)
    Check 'closed early without zero does not proceed' ((Get-ExitCode $false $false $true) -eq 1)
    Write-Host "SelfTest failures: $script:fail"
    exit $(if ($script:fail) { 1 } else { 0 })
}

if (-not (Test-SecondsValid $Seconds)) { Write-Host "Seconds must be 5..900 (got $Seconds)"; exit 2 }

function Show-Toast {
    param([string]$Title, [string]$Body)
    $xmlText = '<toast scenario="reminder"><visual><binding template="ToastGeneric"><text>{0}</text><text>{1}</text></binding></visual></toast>' -f [Security.SecurityElement]::Escape($Title), [Security.SecurityElement]::Escape($Body)
    $cmd = @"
[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null
[Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime] | Out-Null
`$xml = New-Object Windows.Data.Xml.Dom.XmlDocument
`$xml.LoadXml('$($xmlText.Replace("'", "''"))')
`$toast = New-Object Windows.UI.Notifications.ToastNotification `$xml
[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\WindowsPowerShell\v1.0\powershell.exe').Show(`$toast)
"@
    try {
        $p = Start-Process -FilePath "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe" -ArgumentList '-NoProfile', '-NonInteractive', '-WindowStyle', 'Hidden', '-Command', $cmd -PassThru -WindowStyle Hidden -Wait
        return ($p.ExitCode -eq 0)
    } catch { return $false }
}

Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing

$script:stopped = $false
$script:reachedZero = $false
$script:shownOk = $false
$deadline = [datetime]::UtcNow.AddSeconds($Seconds)

$form = New-Object System.Windows.Forms.Form
$form.Text = $Title
$form.TopMost = $true
$form.StartPosition = 'CenterScreen'
$form.Size = New-Object System.Drawing.Size(560, 330)
$form.FormBorderStyle = 'FixedDialog'
$form.MaximizeBox = $false
$form.MinimizeBox = $false
$form.ShowInTaskbar = $true

$msg = New-Object System.Windows.Forms.Label
$msg.Text = $Message
$msg.Font = New-Object System.Drawing.Font('Segoe UI', 12)
$msg.Location = New-Object System.Drawing.Point(20, 15)
$msg.Size = New-Object System.Drawing.Size(510, 90)
$form.Controls.Add($msg)

$clock = New-Object System.Windows.Forms.Label
$clock.Text = Format-Remaining $Seconds
$clock.Font = New-Object System.Drawing.Font('Segoe UI', 36, [System.Drawing.FontStyle]::Bold)
$clock.TextAlign = 'MiddleCenter'
$clock.Location = New-Object System.Drawing.Point(20, 105)
$clock.Size = New-Object System.Drawing.Size(510, 70)
$form.Controls.Add($clock)

$stop = New-Object System.Windows.Forms.Button
$stop.Text = 'STOP - do not run the test'
$stop.Font = New-Object System.Drawing.Font('Segoe UI', 14, [System.Drawing.FontStyle]::Bold)
$stop.BackColor = [System.Drawing.Color]::Firebrick
$stop.ForeColor = [System.Drawing.Color]::White
$stop.Location = New-Object System.Drawing.Point(60, 195)
$stop.Size = New-Object System.Drawing.Size(430, 70)
$stop.Add_Click({ $script:stopped = $true; $form.Close() })
$form.Controls.Add($stop)

$timer = New-Object System.Windows.Forms.Timer
$timer.Interval = 250
$timer.Add_Tick({
    $left = [int][math]::Ceiling(($deadline - [datetime]::UtcNow).TotalSeconds)
    $clock.Text = Format-Remaining $left
    if ($left -le 0) { $script:reachedZero = $true; $timer.Stop(); $form.Close() }
})
$form.Add_Shown({ $script:shownOk = $true; $form.Activate(); $timer.Start() })
$form.Add_FormClosing({ if (-not $script:reachedZero) { $script:stopped = $true } })

if (-not $NoToast) { [void](Show-Toast -Title $Title -Body ("{0} Starts in {1}." -f $Message, (Format-Remaining $Seconds))) }
try { [void]$form.ShowDialog() } catch { $script:shownOk = $false }
exit (Get-ExitCode -Stopped $script:stopped -ReachedZero $script:reachedZero -ShownOk $script:shownOk)
