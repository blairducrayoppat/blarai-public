#requires -Version 5.1
<#
.SYNOPSIS
  Turns a folder of bundled (sanitised) scripts into the live copies: the user-name placeholder becomes the real user name and the
  text files get CRLF line endings. The bundle stores `_OPERATOR_` in every default path; the live copies under the research-data
  folder carry the real ones. Nothing here touches the WFP engine, an account, a task or the network.

.DESCRIPTION
  Modes (exactly one):
    -SelfTest  runs against a temporary folder with a made-up user name.
    -DryRun    lists what would be written, replaced or left alone, and writes nothing.
    -Apply     writes the live copies into -Dest.
  A destination file that already exists and differs from what would be written is NOT overwritten unless -Force is given
  (a re-run of an unchanged folder is a no-op); the listing says which files differ. Binary files are skipped by suffix.
  The user name comes from -UserName or the USERNAME environment variable, never from this file.
#>
[CmdletBinding()]
param(
    [switch]$SelfTest,
    [switch]$DryRun,
    [switch]$Apply,
    [string]$Source,
    [string]$Dest,
    [string]$UserName = $env:USERNAME,
    [switch]$Force
)
$ErrorActionPreference = 'Stop'
$script:Placeholder = '_OPERATOR_'
$script:TextSuffixes = @('.ps1', '.py', '.cmd', '.md', '.txt', '.json')

function ConvertTo-LiveText {
    # PURE. The placeholder replaced by the user name (case-sensitive: the bundle writes it exactly), line endings CRLF.
    param([string]$Text, [string]$User)
    return (($Text -replace "`r`n", "`n").Replace($script:Placeholder, $User) -replace "`n", "`r`n")
}

function Test-UserNameSafe { param([string]$User) return ($User -match '^[A-Za-z0-9][A-Za-z0-9._ -]{0,63}$') }

function Get-LivePlan {
    # Returns one row per source file: Rel, Action (write | same | differs | skip) and the text that would be written.
    param([string]$Src, [string]$Dst, [string]$User)
    $rows = @()
    foreach ($f in (Get-ChildItem -LiteralPath $Src -File -Recurse | Sort-Object FullName)) {
        $rel = $f.FullName.Substring($Src.TrimEnd('\').Length).TrimStart('\')
        if ($script:TextSuffixes -notcontains $f.Extension.ToLowerInvariant()) { $rows += [pscustomobject]@{ Rel = $rel; Action = 'skip'; Text = $null; Target = $null }; continue }
        $bytes = [IO.File]::ReadAllBytes($f.FullName)
        $text = ConvertTo-LiveText -Text ((New-Object Text.UTF8Encoding($false, $true)).GetString($bytes)) -User $User
        $target = Join-Path $Dst $rel
        $action = 'write'
        if (Test-Path -LiteralPath $target) {
            $cur = [IO.File]::ReadAllBytes($target)
            $action = $(if ([Convert]::ToBase64String($cur) -eq [Convert]::ToBase64String((New-Object Text.UTF8Encoding($false)).GetBytes($text))) { 'same' } else { 'differs' })
        }
        $rows += [pscustomobject]@{ Rel = $rel; Action = $action; Text = $text; Target = $target }
    }
    return $rows
}

if ($SelfTest) {
    $f = 0
    function Chk([string]$n, [bool]$c) { if ($c) { Write-Host "  [PASS] $n" -ForegroundColor Green } else { Write-Host "  [FAIL] $n" -ForegroundColor Red; $script:f++ } }
    Chk 'the placeholder becomes the user name everywhere and line endings become CRLF' ((ConvertTo-LiveText -Text "a _OPERATOR_ b`nC:\Users\_OPERATOR_\x`n" -User 'tester') -eq "a tester b`r`nC:\Users\tester\x`r`n")
    Chk 'already-CRLF input is not doubled' ((ConvertTo-LiveText -Text "a`r`nb`r`n" -User 'u') -eq "a`r`nb`r`n")
    Chk 'a user name must be plain (no path or shell characters)' ((Test-UserNameSafe 'tester') -and -not (Test-UserNameSafe 'a;b') -and -not (Test-UserNameSafe '..\x') -and -not (Test-UserNameSafe ''))
    $tmp = Join-Path ([IO.Path]::GetTempPath()) ('live-' + [guid]::NewGuid().ToString('N')); $src = Join-Path $tmp 'src'; $dst = Join-Path $tmp 'dst'
    New-Item -ItemType Directory -Path $src, $dst | Out-Null
    try {
        [IO.File]::WriteAllText((Join-Path $src 'a.ps1'), "`$p = 'C:\Users\_OPERATOR_\x'`n"); [IO.File]::WriteAllBytes((Join-Path $src 'b.bin'), [byte[]](1, 2, 3))
        $p1 = Get-LivePlan -Src $src -Dst $dst -User 'tester'
        Chk 'plan: the text file is "write", the binary is "skip"' (((@($p1 | Where-Object { $_.Rel -eq 'a.ps1' })[0]).Action -eq 'write') -and ((@($p1 | Where-Object { $_.Rel -eq 'b.bin' })[0]).Action -eq 'skip'))
        Chk 'plan: nothing was written by planning' (-not (Test-Path (Join-Path $dst 'a.ps1')))
        [IO.File]::WriteAllText((Join-Path $dst 'a.ps1'), 'different')
        Chk 'plan: an existing file that differs is "differs" (would not be overwritten without -Force)' (((Get-LivePlan -Src $src -Dst $dst -User 'tester') | Where-Object { $_.Rel -eq 'a.ps1' }).Action -eq 'differs')
        [IO.File]::WriteAllBytes((Join-Path $dst 'a.ps1'), (New-Object Text.UTF8Encoding($false)).GetBytes("`$p = 'C:\Users\tester\x'`r`n"))
        Chk 'plan: an existing file equal to the result is "same" (idempotent)' (((Get-LivePlan -Src $src -Dst $dst -User 'tester') | Where-Object { $_.Rel -eq 'a.ps1' }).Action -eq 'same')
    } finally { Remove-Item -LiteralPath $tmp -Recurse -Force -ErrorAction SilentlyContinue }
    Write-Host ("convert-to-live selftest: {0}" -f $(if ($f -eq 0) { 'all passed' } else { "$f FAILED" }))
    exit $(if ($f -eq 0) { 0 } else { 1 })
}

if (@(@($DryRun, $Apply) | Where-Object { $_ }).Count -ne 1) { Write-Host 'choose exactly one of -SelfTest, -DryRun, -Apply' -ForegroundColor Red; exit 2 }
if (-not $Source -or -not $Dest) { Write-Host '-Source and -Dest are required' -ForegroundColor Red; exit 2 }
if (-not (Test-UserNameSafe $UserName)) { Write-Host "refusing the user name '$UserName'" -ForegroundColor Red; exit 2 }
if (-not (Test-Path -LiteralPath $Source -PathType Container)) { Write-Host "source folder not found: $Source" -ForegroundColor Red; exit 2 }
$src = (Resolve-Path -LiteralPath $Source).Path
if (-not (Test-Path -LiteralPath $Dest)) { if ($DryRun) { Write-Host "(destination $Dest does not exist; -Apply would create it)" } else { New-Item -ItemType Directory -Force $Dest | Out-Null } }
$dstPath = if (Test-Path -LiteralPath $Dest) { (Resolve-Path -LiteralPath $Dest).Path } else { $Dest }
$plan = Get-LivePlan -Src $src -Dst $dstPath -User $UserName
$blocked = 0
foreach ($r in $plan) {
    $will = switch ($r.Action) { 'write' { 'WRITE ' } 'same' { 'same  ' } 'skip' { 'skip  ' } 'differs' { $(if ($Force) { 'REPLACE' } else { 'DIFFERS (not replaced without -Force)' }) } }
    Write-Host ("  {0,-8} {1}" -f $will, $r.Rel)
    if ($r.Action -eq 'differs' -and -not $Force) { $blocked++ }
    if ($Apply -and ($r.Action -eq 'write' -or ($r.Action -eq 'differs' -and $Force))) {
        New-Item -ItemType Directory -Force (Split-Path $r.Target -Parent) | Out-Null
        [IO.File]::WriteAllBytes($r.Target, (New-Object Text.UTF8Encoding($false)).GetBytes($r.Text))
    }
}
Write-Host $(if ($DryRun) { 'DRY RUN: nothing written.' } elseif ($blocked) { "$blocked file(s) differ and were left alone: review, then re-run with -Force." } else { 'done.' })
exit $(if ($Apply -and $blocked) { 1 } else { 0 })
