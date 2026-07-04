# BlarAI — Register the guest-parser hv_sock service GUID on the HOST (#655)
# ===========================================================================
# CONTROLLED-SESSION TOOL — this writes one registry key on the HOST (not the
# guest).  Windows requires every Hyper-V socket service to be registered
# under GuestCommunicationServices before a host process can address it; the
# existing BlarAI service (port 50000 / 0000c350-...) was registered during
# the Phase-2 vsock validation.  The guest parser gets its OWN service so the
# parse channel never contends with the runtime channel:
#
#   port 50001 (0xC351)  ->  0000c351-facb-11e6-bd58-64006a7986d3
#
# (hv_sock template: <port_hex>-facb-11e6-bd58-64006a7986d3.  Must match
# launcher/config/default.toml [guest_parser]; the launcher's config loader
# fails closed on any port/GUID divergence.)
#
# Requires an elevated shell.  Idempotent: an already-registered GUID is a
# success, not an error.  No guest interaction at all.

param(
    [int]$VsockPort = 50001,
    [string]$ElementName = "BlarAI Guest Parser (UC-003 Stage C, #655)"
)

$ErrorActionPreference = "Stop"

$guid = ('{0:x8}-facb-11e6-bd58-64006a7986d3' -f $VsockPort)
$key = "HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Virtualization\GuestCommunicationServices\$guid"

if (Test-Path -LiteralPath $key) {
    $existing = (Get-ItemProperty -LiteralPath $key -ErrorAction SilentlyContinue).ElementName
    Write-Host "Already registered: $guid (ElementName: '$existing') - nothing to do."
    exit 0
}

New-Item -Path $key -Force | Out-Null
New-ItemProperty -Path $key -Name "ElementName" -Value $ElementName -PropertyType String -Force | Out-Null

Write-Host "REGISTERED hv_sock service for the guest parser:"
Write-Host "  port  : $VsockPort"
Write-Host "  guid  : $guid"
Write-Host "  key   : $key"
Write-Host "Reversible: Remove-Item -LiteralPath '$key'"
exit 0
