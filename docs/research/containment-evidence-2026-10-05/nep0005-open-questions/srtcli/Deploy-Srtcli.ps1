#requires -Version 7.2
<#
.SYNOPSIS
  Copies the srt-win command-line run (#1763) into the admin-only live folder: the driver, the TypeScript runner, both srt-win builds and
  both built TypeScript trees (dist + runtime dependencies only). Elevated. Writes under C:\ProgramData\BlarAI\trackb-live\srtcli, plus npm's own cache and logs under the operator's profile.

.DESCRIPTION
  The destination must be writable by SYSTEM and Administrators only (it inherits trackb-live's DACL: Users may read and execute);
  an allow entry giving any other principal a write, delete, permission or ownership right fails the deploy. The SHA-256 of every file the driver pins is printed from the destination; the driver's preflight compares them with its constants.
  `npm ci --omit=dev --ignore-scripts` installs the four runtime dependencies from each tree's own lock file.
#>
[CmdletBinding()]
param(
    # The folder holding the stock\ and patched\ extractions of the pinned tarball, with their release and TypeScript builds.
    [Parameter(Mandatory)][string]$BuildRoot,
    [string]$Dest = 'C:\ProgramData\BlarAI\trackb-live\srtcli'
)
$ErrorActionPreference = 'Stop'
$here = $PSScriptRoot
$tree = 'anthropics-sandbox-runtime-24eb39e'

if (-not ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) { throw 'not elevated' }
if ($Dest -ne 'C:\ProgramData\BlarAI\trackb-live\srtcli') { throw "destination $Dest is not the live folder" }

New-Item -ItemType Directory -Force -Path $Dest | Out-Null
$allowed = @('S-1-5-18', 'S-1-5-32-544')
$R = [Security.AccessControl.FileSystemRights]
# Generic rights (GENERIC_ALL 0x10000000, GENERIC_WRITE 0x40000000) appear raw on inherit-only entries and grant write to what they reach.
$writeMask = [int]($R::WriteData -bor $R::AppendData -bor $R::WriteAttributes -bor $R::WriteExtendedAttributes -bor $R::DeleteSubdirectoriesAndFiles -bor $R::Delete -bor $R::ChangePermissions -bor $R::TakeOwnership) -bor 0x10000000 -bor 0x40000000
$checkDirs = @($Dest) + @(Get-ChildItem -LiteralPath $Dest -Recurse -Directory -Force -ErrorAction SilentlyContinue | Where-Object { $_.FullName -notmatch '\\node_modules(\\|$)' } | ForEach-Object FullName)
foreach ($cd in $checkDirs) {
    $bad = @((Get-Acl -LiteralPath $cd).Access | Where-Object { $_.AccessControlType -eq 'Allow' -and ([int64][int]$_.FileSystemRights -band [int64]$writeMask) -ne 0 } |
        ForEach-Object { $_.IdentityReference.Translate([Security.Principal.SecurityIdentifier]).Value } | Where-Object { $_ -notin $allowed })
    if ($bad.Count) { throw "$cd lets $($bad -join ', ') write: not admin-writable-only" }
}

Copy-Item -LiteralPath (Join-Path $here 'srtcli-halfset.ps1') -Destination $Dest -Force
Copy-Item -LiteralPath (Join-Path $here 'fix\run-verify.mjs') -Destination $Dest -Force
foreach ($b in 'stock', 'patched') {
    $d = Join-Path $Dest $b; New-Item -ItemType Directory -Force -Path $d | Out-Null
    Copy-Item -LiteralPath (Join-Path $BuildRoot "$b\$tree\vendor\srt-win-src\target\release\srt-win.exe") -Destination (Join-Path $d 'srt-win.exe') -Force
    $t = Join-Path $d $tree; New-Item -ItemType Directory -Force -Path $t | Out-Null
    if (Test-Path -LiteralPath (Join-Path $t 'dist')) { Remove-Item -LiteralPath (Join-Path $t 'dist') -Recurse -Force }
    Copy-Item -LiteralPath (Join-Path $BuildRoot "$b\$tree\dist") -Destination $t -Recurse -Force
    foreach ($f in 'package.json', 'package-lock.json') { Copy-Item -LiteralPath (Join-Path $BuildRoot "$b\$tree\$f") -Destination $t -Force }
    Push-Location $t
    try { & npm.cmd ci --omit=dev --ignore-scripts --no-audit --no-fund 2>&1 | Out-Host; if ($LASTEXITCODE -ne 0) { throw "npm ci in $t exited $LASTEXITCODE" } } finally { Pop-Location }
}
Get-ChildItem -LiteralPath $Dest -Recurse -File | Where-Object { $_.Name -in @('srtcli-halfset.ps1', 'run-verify.mjs', 'srt-win.exe', 'windows-sandbox-utils.js') -and $_.FullName -notmatch '\\node_modules\\' } |
    ForEach-Object { '{0}  {1}' -f (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash, $_.FullName.Substring($Dest.Length + 1) }
