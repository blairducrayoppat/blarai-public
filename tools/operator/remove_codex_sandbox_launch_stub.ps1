$ErrorActionPreference = 'Stop'
# Source of truth for the text embedded (as -EncodedCommand) in remove_codex_sandbox.cmd; this file is never run from disk.
# It runs elevated: copies the script into a SYSTEM/Administrators-only folder, checks the copy against the hash the
# launcher read before approval, and runs the copy. The hash check catches a file changed after the launcher read it.
$src = $env:RCS_PS1; $want = $env:RCS_SHA
function Get-LfSha([string]$p) { $b = [IO.File]::ReadAllBytes($p); $o = [Collections.Generic.List[byte]]::new(); for ($i = 0; $i -lt $b.Length; $i++) { if ($b[$i] -eq 13 -and ($i + 1) -lt $b.Length -and $b[$i + 1] -eq 10) { continue }; $o.Add($b[$i]) }; ([BitConverter]::ToString([Security.Cryptography.SHA256]::HashData($o.ToArray())) -replace '-', '') }
function New-ProtectedFolder([string]$p) { $sec = [Security.AccessControl.DirectorySecurity]::new(); $sec.SetOwner([Security.Principal.SecurityIdentifier]'S-1-5-32-544'); $sec.SetAccessRuleProtection($true, $false); foreach ($i in 'S-1-5-18', 'S-1-5-32-544') { $sec.AddAccessRule([Security.AccessControl.FileSystemAccessRule]::new([Security.Principal.SecurityIdentifier]$i, [Security.AccessControl.FileSystemRights]::FullControl, 'ContainerInherit,ObjectInherit', 'None', 'Allow')) }; [void][IO.FileSystemAclExtensions]::Create([IO.DirectoryInfo]::new($p), $sec) }
try {
    if (-not $src -or -not $want -or -not (Test-Path -LiteralPath $src)) { throw 'the launcher did not pass the script path and hash' }
    $root = Join-Path $env:ProgramData 'blarai-operator'
    if (-not (Test-Path -LiteralPath $root)) { New-ProtectedFolder $root }
    elseif (((Get-Item -LiteralPath $root -Force).Attributes -band [IO.FileAttributes]::ReparsePoint) -or -not [IO.FileSystemAclExtensions]::GetAccessControl([IO.DirectoryInfo]::new($root), [Security.AccessControl.AccessControlSections]::Access).AreAccessRulesProtected) { throw "$root is a link or not protected" }
    $run = Join-Path $root 'run-1743'
    if (Test-Path -LiteralPath $run) { Remove-Item -LiteralPath $run -Recurse -Force }
    New-ProtectedFolder $run
    $dst = Join-Path $run 'remove_codex_sandbox.ps1'
    Copy-Item -LiteralPath $src -Destination $dst
    $got = Get-LfSha $dst
    Write-Host "Script hash read before approval : $want"
    Write-Host "Hash of the protected copy       : $got"
    if ($got -ne $want) { Write-Host 'REFUSED: the script changed after the launcher read it. Nothing was changed.' -ForegroundColor Red; Read-Host 'Press Enter to close'; exit 2 }
    & (Join-Path $env:ProgramFiles 'PowerShell\7\pwsh.exe') -NoProfile -ExecutionPolicy Bypass -File $dst -Guided -Stage Accounts -HoldOpen -ExpectScriptSha256 $got
    exit $LASTEXITCODE
} catch { Write-Host "Could not prepare the protected copy: $($_.Exception.Message). Nothing was changed." -ForegroundColor Red; Read-Host 'Press Enter to close'; exit 1 }
