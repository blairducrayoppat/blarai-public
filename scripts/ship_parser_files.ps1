# BlarAI — Ship a host directory into the Alpine guest via Copy-VMFile (#655)
# ============================================================================
# CONTROLLED-SESSION TOOL — this mutates the guest filesystem.  Do not run
# outside the Stage-C controlled session (whose step 0 is the VHDX backup,
# scripts/backup_orchestrator_vhdx.ps1).
#
# Copies every file in -SourceDir (non-recursive by default; -Recurse to walk
# subdirectories, preserving relative paths) into -GuestDir inside the VM
# using the Hyper-V Guest Service Interface.  Used twice in the controlled
# session:
#   * wheels:        -SourceDir build/guest_parser_wheels -GuestDir /opt/blarai/parser/wheels
#   * guest scripts: -SourceDir scripts/guest             -GuestDir /opt/blarai/parser/provision -Recurse
#
# PRECONDITIONS (the script verifies 1-2 and fails closed):
#   1. The VM is Running.
#   2. The 'Guest Service Interface' integration service is enabled.
#   3. hv_fcopy_daemon is RUNNING in the guest.  This is the piece the host
#      CANNOT verify remotely — the one recorded live Copy-VMFile attempt
#      (2026-02-25, P5_GUEST_CHANNEL_NOT_READY) failed precisely here.  The
#      controlled session's manual guest bootstrap (3 commands at the Hyper-V
#      console) enables it first; see
#      docs/security/guest_parser_provisioning_record.md.

param(
    [Parameter(Mandatory = $true)][string]$SourceDir,
    [Parameter(Mandatory = $true)][string]$GuestDir,
    [string]$VmName = "BlarAI-Orchestrator",
    [switch]$Recurse
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path -LiteralPath $SourceDir -PathType Container)) {
    Write-Error "Source directory not found: $SourceDir"
    exit 2
}

$vm = Get-VM -Name $VmName -ErrorAction Stop
if ($vm.State -ne 'Running') {
    Write-Error "REFUSED: VM '$VmName' is '$($vm.State)', not 'Running' - Copy-VMFile needs a running guest."
    exit 3
}
$gsi = Get-VMIntegrationService -VMName $VmName -Name "Guest Service Interface" -ErrorAction Stop
if (-not $gsi.Enabled) {
    Write-Error "REFUSED: 'Guest Service Interface' is disabled on '$VmName'. Enable it: Enable-VMIntegrationService -VMName '$VmName' -Name 'Guest Service Interface'"
    exit 4
}

$root = (Resolve-Path -LiteralPath $SourceDir).Path
$files = if ($Recurse) {
    Get-ChildItem -LiteralPath $root -File -Recurse
} else {
    Get-ChildItem -LiteralPath $root -File
}
if ($files.Count -eq 0) {
    Write-Error "No files to ship in $SourceDir"
    exit 5
}

$guestBase = $GuestDir.TrimEnd('/')
$shipped = 0
foreach ($file in $files) {
    $rel = $file.FullName.Substring($root.Length).TrimStart('\').Replace('\', '/')
    $dest = "$guestBase/$rel"
    Write-Host ("  {0}  ->  {1}" -f $rel, $dest)
    Copy-VMFile -Name $VmName -SourcePath $file.FullName -DestinationPath $dest `
        -FileSource Host -CreateFullPath -Force -ErrorAction Stop
    $shipped++
}

Write-Host "SHIP OK - $shipped file(s) -> ${VmName}:$guestBase"
Write-Host "If this FAILED with 'failed to initiate copying files to the guest', hv_fcopy_daemon is not running in the guest - run the manual guest bootstrap first (provisioning record, step 2)."
exit 0
