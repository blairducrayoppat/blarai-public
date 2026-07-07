param(
    [string]$VmName = "BlarAI-Orchestrator",
    [string]$GuestRoot = "/opt/blarai",
    [string]$EvidenceFile = "phase2_gates/evidence/priority5_guest_deploy.json",
    [switch]$ExcludeModels
)

$ErrorActionPreference = "Stop"

if (Test-Path ".\.venv\Scripts\python.exe") {
    $Python = ".\.venv\Scripts\python.exe"
} else {
    $Python = "python"
}

if ($ExcludeModels) {
    & $Python -m launcher.guest_deploy --vm-name $VmName --guest-root $GuestRoot --evidence-file $EvidenceFile --exclude-models
    exit $LASTEXITCODE
}

& $Python -m launcher.guest_deploy --vm-name $VmName --guest-root $GuestRoot --evidence-file $EvidenceFile
exit $LASTEXITCODE
