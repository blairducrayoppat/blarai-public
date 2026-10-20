#requires -Version 7
<#
.SYNOPSIS
  The reviewer's non-elevated launcher: runs ONE command line under the desktop shell's own token (medium integrity, Administrators deny-only), from any
  console, elevated or not, and prints what it wrote.

.DESCRIPTION
  -Command '<text>'  Writes a temporary .cmd in a fresh folder under %TEMP%, hands it to explorer.exe (the running shell opens it with ITS token: no credential,
                     no password, no trust-level switch, no account read or change), waits for a done marker (-TimeoutSec, default 300), prints the command's
                     stdout and stderr, deletes the temporaries and exits with the command's exit code.
  -SelfCheck         Runs `whoami /groups /fo csv` through the same path and asserts that the command ran with `Mandatory Label\Medium Mandatory Level` and with
                     `BUILTIN\Administrators` marked `Group used for deny only` (and without the High label). Exit 0 when that holds, 1 when it does not.

  Fail closed: before the command runs, the .cmd itself reads its own token (`whoami /groups /fo csv`, System32 copy) and refuses to run the command when the
  High label is present or the Medium label is absent (for example when no shell was running and explorer.exe started elevated). The refusal is exit 4.

  The command text is written into the .cmd as it is: it must be one line of printable ASCII, and cmd expands %VARIABLES% in it. The .cmd restarts itself
  minimised, so the console the shell opens closes at once.

  EXIT CODES  the command's own exit code; 2 bad arguments; 3 no done marker within -TimeoutSec (the temporary folder is kept and named); 4 the command did NOT
              run limited (refused by the .cmd before it ran); 1 -SelfCheck failed.
#>
[CmdletBinding()]
param(
    [string]$Command,
    [ValidateRange(5, 3600)][int]$TimeoutSec = 300,
    [switch]$SelfCheck
)
$ErrorActionPreference = 'Stop'

function Test-LimitedCommandText {
    # PURE. Problems with the command text (empty = it may be written into the .cmd).
    param([string]$Text)
    if (-not $Text -or -not $Text.Trim()) { return @('the command is empty') }
    $p = @()
    if ($Text -match "[`r`n]") { $p += 'the command must be a single line' }
    if ($Text -match '[^\x20-\x7E]') { $p += 'the command must be printable ASCII (the .cmd is written as ASCII)' }
    return @($p)
}

function New-LimitedCmdText {
    # PURE. The .cmd body: restart minimised; read the own token into the label file; refuse (gate file) unless Medium and not High; run the command through a
    # subroutine so every part of a piped line is captured; write the exit code to the done marker last (redirection first: `echo 0> x` would redirect handle 0).
    param([Parameter(Mandatory)][string]$Text, [Parameter(Mandatory)][string]$Dir)
    $il = Join-Path $Dir 'token.csv'; $gate = Join-Path $Dir 'gate.txt'; $out = Join-Path $Dir 'out.txt'; $done = Join-Path $Dir 'done.txt'
    return (@(
        '@echo off'
        'if not defined RL_MIN ( set RL_MIN=1& start "" /min "%ComSpec%" /d /c "%~f0"& exit /b )'
        ('"%SystemRoot%\System32\whoami.exe" /groups /fo csv > "{0}" 2>&1' -f $il)
        ('"%SystemRoot%\System32\findstr.exe" /c:"S-1-16-12288" "{0}" >nul && ( > "{1}" echo refused-high& goto :fin )' -f $il, $gate)
        ('"%SystemRoot%\System32\findstr.exe" /c:"S-1-16-8192" "{0}" >nul || ( > "{1}" echo refused-not-medium& goto :fin )' -f $il, $gate)
        ('> "{0}" echo ok' -f $gate)
        ('call :run > "{0}" 2>&1' -f $out)
        ('> "{0}.tmp" echo %ERRORLEVEL%' -f $done)
        ':fin'
        ('if not exist "{0}.tmp" > "{0}.tmp" echo 255' -f $done)
        ('move /y "{0}.tmp" "{0}" >nul' -f $done)
        'exit /b'
        ':run'
        $Text
        'exit /b %ERRORLEVEL%'
    ) -join "`r`n") + "`r`n"
}

function Invoke-LimitedCommand {
    # Runs $Text through the shell. @{ ExitCode; Output; Gate; TimedOut; Dir; TokenCsv }.
    param([Parameter(Mandatory)][string]$Text, [int]$TimeoutSec = 300)
    $bad = @(Test-LimitedCommandText -Text $Text)
    if ($bad.Count) { throw ($bad -join '; ') }
    $dir = Join-Path ([IO.Path]::GetTempPath()) ('rl-' + [guid]::NewGuid().ToString('N'))
    New-Item -ItemType Directory -Path $dir | Out-Null
    $cmdFile = Join-Path $dir 'run.cmd'
    [IO.File]::WriteAllText($cmdFile, (New-LimitedCmdText -Text $Text -Dir $dir), [Text.Encoding]::ASCII)
    $done = Join-Path $dir 'done.txt'
    Start-Process -FilePath (Join-Path $env:SystemRoot 'explorer.exe') -ArgumentList ('"{0}"' -f $cmdFile) | Out-Null
    $sw = [Diagnostics.Stopwatch]::StartNew()
    while (-not (Test-Path -LiteralPath $done) -and $sw.Elapsed.TotalSeconds -lt $TimeoutSec) { [Threading.Thread]::Sleep(250) }
    $read = { param($n) $p = Join-Path $dir $n; if (Test-Path -LiteralPath $p) { [IO.File]::ReadAllText($p) } else { '' } }
    $res = [ordered]@{ ExitCode = $null; Output = (& $read 'out.txt'); Gate = (& $read 'gate.txt').Trim(); TimedOut = $false; Dir = $dir; TokenCsv = (& $read 'token.csv') }
    if (-not (Test-Path -LiteralPath $done)) { $res.TimedOut = $true; return [pscustomobject]$res }
    $code = 0; if (-not [int]::TryParse((& $read 'done.txt').Trim(), [ref]$code)) { $code = 255 }
    $res.ExitCode = $code
    for ($i = 0; $i -lt 8; $i++) { try { Remove-Item -LiteralPath $dir -Recurse -Force -ErrorAction Stop; break } catch { [Threading.Thread]::Sleep(250) } }
    return [pscustomobject]$res
}

function Get-LimitedTokenVerdict {
    # PURE. From `whoami /groups /fo csv` text: Medium label present, High label absent, BUILTIN\Administrators present and "Group used for deny only".
    param([string]$Csv)
    $rows = @()
    try { $rows = @(($Csv -split "`r?`n" | Where-Object { $_.Trim() }) | ConvertFrom-Csv) } catch { $rows = @() }
    $medium = @($rows | Where-Object { $_.SID -eq 'S-1-16-8192' -or $_.'Group Name' -eq 'Mandatory Label\Medium Mandatory Level' })
    $high = @($rows | Where-Object { $_.SID -eq 'S-1-16-12288' -or $_.'Group Name' -eq 'Mandatory Label\High Mandatory Level' })
    $admins = @($rows | Where-Object { ($_.SID -eq 'S-1-5-32-544' -or $_.'Group Name' -eq 'BUILTIN\Administrators') })
    $denyOnly = @($admins | Where-Object { $_.Attributes -match 'Group used for deny only' })
    return [pscustomobject]@{
        Rows = $rows.Count; Medium = ($medium.Count -ge 1); High = ($high.Count -ge 1); AdminsPresent = ($admins.Count -ge 1); AdminsDenyOnly = ($denyOnly.Count -ge 1 -and $denyOnly.Count -eq $admins.Count)
        Ok = ($medium.Count -ge 1 -and $high.Count -eq 0 -and $admins.Count -ge 1 -and $denyOnly.Count -eq $admins.Count)
    }
}

if ($SelfCheck -and $Command) { Write-Host 'ARG ERROR: choose -Command or -SelfCheck, not both.' -ForegroundColor Red; exit 2 }
if (-not $SelfCheck -and -not $Command) { Write-Host 'ARG ERROR: -Command ''<text>'' or -SelfCheck.' -ForegroundColor Red; exit 2 }
$text = $(if ($SelfCheck) { '"%SystemRoot%\System32\whoami.exe" /groups /fo csv' } else { $Command })
$bad = @(Test-LimitedCommandText -Text $text)
if ($bad.Count) { $bad | ForEach-Object { Write-Host "ARG ERROR: $_" -ForegroundColor Red }; exit 2 }

$r = Invoke-LimitedCommand -Text $text -TimeoutSec $TimeoutSec
if ($r.TimedOut) {
    Write-Output $r.Output
    Write-Host "TIMED OUT after $TimeoutSec s: no done marker. The temporary folder is kept: $($r.Dir)" -ForegroundColor Red
    exit 3
}
if ($r.Gate -ne 'ok') {
    $v = Get-LimitedTokenVerdict -Csv $r.TokenCsv
    Write-Host ("REFUSED by the .cmd before the command ran ({0}): the shell's token was not limited (Medium label {1}, High label {2}). The command did NOT run." -f $r.Gate, $v.Medium, $v.High) -ForegroundColor Red
    exit 4
}
Write-Output $r.Output
if ($SelfCheck) {
    $v = Get-LimitedTokenVerdict -Csv $r.Output
    Write-Host ("self-check: {0} group rows; Medium label {1}; High label {2}; BUILTIN\Administrators present {3}, deny-only {4}" -f $v.Rows, $v.Medium, $v.High, $v.AdminsPresent, $v.AdminsDenyOnly)
    if ($v.Ok -and $r.ExitCode -eq 0) { Write-Host 'SELF-CHECK PASSED: the command ran at Medium integrity with Administrators as deny-only.' -ForegroundColor Green; exit 0 }
    Write-Host 'SELF-CHECK FAILED.' -ForegroundColor Red
    exit 1
}
exit $r.ExitCode
