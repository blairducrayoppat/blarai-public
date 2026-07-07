# BlarAI — Step-0 VHDX backup (UC-003 Stage C controlled session; #655)
# ======================================================================
# Backs up the hand-built BlarAI-Orchestrator VHDX BEFORE anything touches the
# guest.  The VHDX has NO rebuild script and NO prior backup — this script is
# the mandatory first step of the controlled provisioning session, and it
# REFUSES to run unless the VM is verifiably Off (a running VM's VHDX is an
# inconsistent, possibly-locked copy source).
#
# Behaviour:
#   1. Query VM state.  Refuse fail-closed unless EXACTLY 'Off' (a failed
#      state query also refuses — never copy on uncertainty).
#   2. Copy the VHDX to <BackupDir>\Orchestrator_<UTCSTAMP>.vhdx (never
#      overwrites; a same-name collision refuses).
#   3. Verify size equality, then SHA-256 equality of source vs backup.
#   4. Write a JSON receipt next to the backup.
#
# This script is READ-ONLY toward the VM (one Get-VM) and toward the source
# VHDX (read for copy + hash).  It never starts, stops, or reconfigures
# anything.
#
# Testability: the refusal predicate (Get-BackupRefusalReason) is a pure
# function; pytest dot-sources this file with -AsLibrary (which skips the
# main body) and exercises the predicate directly —
# launcher/tests/test_backup_script_refusal.py.

param(
    [string]$VmName = "BlarAI-Orchestrator",
    [string]$VhdxPath = "C:\HyperV\BlarAI\Orchestrator.vhdx",
    [string]$BackupDir = "C:\HyperV\BlarAI\backups",
    [switch]$AsLibrary
)

$ErrorActionPreference = "Stop"

function Get-BackupRefusalReason {
    <#
    .SYNOPSIS
        Pure refusal predicate: returns a non-empty reason string when the
        backup MUST NOT proceed, or "" when the VM state permits it.
    .NOTES
        Fail-closed: only the exact state 'Off' permits the backup.  A failed
        state query, an empty state, and every non-Off state (Running, Saved,
        Paused, Starting, ...) refuse — Saved/Paused still hold dirty memory
        state referencing the disk, so they are NOT safe copy points.
    #>
    param(
        [string]$VmState,
        [bool]$StateQueryFailed = $false
    )
    if ($StateQueryFailed) {
        return "VM state query failed - refusing fail-closed (cannot prove the VM is Off)."
    }
    $state = "$VmState".Trim()
    if ([string]::IsNullOrWhiteSpace($state)) {
        return "VM state is empty/unknown - refusing fail-closed (cannot prove the VM is Off)."
    }
    if ($state -ne 'Off') {
        return "VM is '$state', not 'Off' - refusing. Shut the VM down cleanly first (the VHDX of a non-Off VM is not a consistent copy source)."
    }
    return ""
}

if ($AsLibrary) {
    # Dot-sourced for unit tests — expose the predicate, run nothing.
    return
}

Write-Host "=== BlarAI Step-0 VHDX backup (#655 Stage C) ==="

# -- 1. Refusal gate ---------------------------------------------------------
$stateQueryFailed = $false
$vmState = ""
try {
    $vmState = (Get-VM -Name $VmName -ErrorAction Stop).State.ToString()
} catch {
    $stateQueryFailed = $true
}
$refusal = Get-BackupRefusalReason -VmState $vmState -StateQueryFailed $stateQueryFailed
if ($refusal) {
    Write-Error "REFUSED: $refusal"
    exit 2
}
Write-Host "VM '$VmName' is Off - proceeding."

if (-not (Test-Path -LiteralPath $VhdxPath -PathType Leaf)) {
    Write-Error "REFUSED: source VHDX not found at '$VhdxPath'."
    exit 3
}

# -- 2. Copy (never overwrite) -----------------------------------------------
if (-not (Test-Path -LiteralPath $BackupDir)) {
    New-Item -ItemType Directory -Path $BackupDir -Force | Out-Null
}
$stamp = (Get-Date).ToUniversalTime().ToString("yyyyMMdd_HHmmss")
$backupName = "Orchestrator_$stamp.vhdx"
$backupPath = Join-Path $BackupDir $backupName
if (Test-Path -LiteralPath $backupPath) {
    Write-Error "REFUSED: backup target already exists: '$backupPath' (this script never overwrites)."
    exit 4
}

$src = Get-Item -LiteralPath $VhdxPath
Write-Host ("Copying {0:N0} bytes -> {1} ..." -f $src.Length, $backupPath)
Copy-Item -LiteralPath $VhdxPath -Destination $backupPath

# -- 3. Verify size + SHA-256 ------------------------------------------------
$dst = Get-Item -LiteralPath $backupPath
if ($dst.Length -ne $src.Length) {
    Write-Error ("VERIFY FAILED: size mismatch (source {0:N0}, backup {1:N0}). Backup kept for inspection at '{2}' but is NOT trustworthy." -f $src.Length, $dst.Length, $backupPath)
    exit 5
}
Write-Host "Size verified. Hashing (this takes a while on a multi-GB VHDX)..."
$srcHash = (Get-FileHash -LiteralPath $VhdxPath -Algorithm SHA256).Hash.ToLowerInvariant()
$dstHash = (Get-FileHash -LiteralPath $backupPath -Algorithm SHA256).Hash.ToLowerInvariant()
if ($srcHash -ne $dstHash) {
    Write-Error "VERIFY FAILED: SHA-256 mismatch (source $srcHash, backup $dstHash). Backup kept for inspection but is NOT trustworthy."
    exit 6
}

# -- 4. Receipt ----------------------------------------------------------------
$receipt = [ordered]@{
    artifact        = "BlarAI Orchestrator VHDX step-0 backup (#655 Stage C)"
    timestamp_utc   = (Get-Date).ToUniversalTime().ToString("o")
    vm_name         = $VmName
    vm_state        = "Off"
    source_path     = $VhdxPath
    backup_path     = $backupPath
    size_bytes      = $src.Length
    sha256          = $srcHash
    verified        = $true
}
$receiptPath = "$backupPath.receipt.json"
$receipt | ConvertTo-Json | Set-Content -LiteralPath $receiptPath -Encoding utf8

Write-Host "BACKUP OK"
Write-Host "  backup : $backupPath"
Write-Host "  sha256 : $srcHash"
Write-Host "  receipt: $receiptPath"
exit 0
