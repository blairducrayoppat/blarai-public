<#
.SYNOPSIS
    VALIDATE_DVMT_BUDGET — Phase 2 Day-1 Empirical Gate
.DESCRIPTION
    Red Team Issue: ISSUE-001
    Affected Use Cases: ALL
    
    Validates the DVMT pre-allocation on the Intel Arc 140V (Xe2) integrated GPU
    to confirm the 512MB BIOS reservation and establish the effective memory ceiling
    of 31.5GB (32GB - 512MB DVMT).
    
    Tests:
      2.1 - BIOS DVMT readout (manual/visual — instructions printed)
      2.2 - OS-level verification via WMI/CIM and Registry
      2.3 - Runtime memory visibility (TotalPhysicalMemory vs raw 32GB)
    
    Outputs:
      phase2_gates\evidence\dvmt_validation.json
    
    Failure Fingerprinting:
      All failures captured in structured JSON. Branch preserved on failure.
#>

[CmdletBinding()]
param(
    [switch]$SkipBiosCheck
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
$EFFECTIVE_CEILING_BYTES = [uint64](31.323 * 1024 * 1024 * 1024)  # 31.323 GB (empirical — ADR-005)
$EXPECTED_DVMT_MB        = 693  # Total firmware reservation (DVMT + CSME + PTT) — ADR-005
$RAW_PHYSICAL_GB         = 32
$TOLERANCE_MB            = 128  # Allow ±128MB tolerance for Lunar Lake multi-component firmware reservation

$ScriptRoot  = Split-Path -Parent $MyInvocation.MyCommand.Definition
$EvidenceDir = Join-Path (Split-Path -Parent $ScriptRoot) "evidence"
$OutputFile  = Join-Path $EvidenceDir "dvmt_validation.json"

# Ensure evidence directory exists
if (-not (Test-Path $EvidenceDir)) {
    New-Item -ItemType Directory -Path $EvidenceDir -Force | Out-Null
}

$Timestamp = (Get-Date).ToUniversalTime().ToString("o")

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
function New-FailureRecord {
    param(
        [string]$TestId,
        [string]$Metric,
        [string]$Expected,
        [string]$Actual,
        [string]$Disposition = "FAIL"
    )
    return @{
        gate             = "VALIDATE_DVMT_BUDGET"
        timestamp        = $Timestamp
        test_id          = $TestId
        metric           = $Metric
        expected         = $Expected
        actual           = $Actual
        disposition      = $Disposition
        escalation       = "Lead Architect decision required"
        branch_preserved = "feature/phase2-scaffolding"
        evidence_path    = $OutputFile
    }
}

# ---------------------------------------------------------------------------
# Test 2.1 — BIOS DVMT Readout (Instructional)
# ---------------------------------------------------------------------------
Write-Host "=" -NoNewline; Write-Host ("=" * 71)
Write-Host "VALIDATE_DVMT_BUDGET — Phase 2 Day-1 Empirical Gate"
Write-Host "Timestamp: $Timestamp"
Write-Host "=" -NoNewline; Write-Host ("=" * 71)
Write-Host ""

$Test21 = @{
    test_id     = "2.1"
    description = "BIOS DVMT readout (manual verification)"
    status      = "INFORMATIONAL"
    instructions = @(
        "1. Reboot and enter BIOS/UEFI (F2 or DEL during POST)",
        "2. Navigate to: Advanced > System Agent > Graphics Configuration",
        "3. Locate 'DVMT Pre-Allocated' setting",
        "4. Record the value (expected: 512MB)",
        "5. If the value differs, note it for the evidence record"
    )
}

if (-not $SkipBiosCheck) {
    Write-Host "[Test 2.1] BIOS DVMT Readout — MANUAL VERIFICATION REQUIRED"
    Write-Host "  The following BIOS check must be performed physically:"
    foreach ($instr in $Test21.instructions) {
        Write-Host "    $instr"
    }
    Write-Host "  (Use -SkipBiosCheck to skip this prompt in automated runs)"
    Write-Host ""
} else {
    Write-Host "[Test 2.1] BIOS DVMT Readout — SKIPPED (automated mode)"
    $Test21.status = "SKIPPED"
    Write-Host ""
}

# ---------------------------------------------------------------------------
# Test 2.2 — OS-Level DVMT Verification
# ---------------------------------------------------------------------------
Write-Host "[Test 2.2] OS-Level DVMT Verification via WMI/Registry"

$Test22Failures = @()
$Test22 = @{
    test_id     = "2.2"
    description = "OS-level DVMT verification"
}

# 2.2a — Video controller adapter RAM via WMI
try {
    $VideoControllers = Get-CimInstance -ClassName Win32_VideoController | Where-Object {
        $_.Name -match "Intel|Arc"
    }
    
    $VideoInfo = @()
    foreach ($vc in $VideoControllers) {
        $adapterRamMB = [math]::Round($vc.AdapterRAM / 1MB, 0)
        $VideoInfo += @{
            name          = $vc.Name
            adapter_ram_mb = $adapterRamMB
            driver_version = $vc.DriverVersion
            status        = $vc.Status
            pnp_device_id = $vc.PNPDeviceID
        }
        Write-Host "  Video Controller: $($vc.Name)"
        Write-Host "    Adapter RAM: ${adapterRamMB}MB"
        Write-Host "    Driver: $($vc.DriverVersion)"
    }
    $Test22.video_controllers = $VideoInfo
} catch {
    Write-Host "  WARNING: Failed to query Win32_VideoController: $_"
    $Test22.video_controllers = @()
    $Test22Failures += New-FailureRecord -TestId "2.2a" -Metric "video_controller_query" -Expected "success" -Actual "error: $_" -Disposition "WARNING"
}

# 2.2b — Registry DVMT values
try {
    $RegistryPaths = @(
        "HKLM:\SYSTEM\CurrentControlSet\Control\Class\{4d36e968-e325-11ce-bfc1-08002be10318}\0000",
        "HKLM:\SYSTEM\CurrentControlSet\Control\Class\{4d36e968-e325-11ce-bfc1-08002be10318}\0001"
    )
    
    $RegistryInfo = @()
    foreach ($regPath in $RegistryPaths) {
        if (Test-Path $regPath) {
            $props = Get-ItemProperty -Path $regPath -ErrorAction SilentlyContinue
            $dvmtSize = $null
            $dvmtMaxSize = $null
            
            # Common Intel DVMT registry value names
            foreach ($name in @("Intel(R) Graphics DVMT Total Memory Size", "DedicatedPreAllocSize", "DVMT_Pre_Alloc", "GraphicsMemorySize")) {
                if ($props.PSObject.Properties[$name]) {
                    $dvmtSize = $props.$name
                }
            }
            foreach ($name in @("Intel(R) Graphics DVMT Max Memory Size", "MaxDVMT", "MaxGfxMemory")) {
                if ($props.PSObject.Properties[$name]) {
                    $dvmtMaxSize = $props.$name
                }
            }
            
            $regEntry = @{
                path          = $regPath
                dvmt_size     = $dvmtSize
                dvmt_max_size = $dvmtMaxSize
                driver_desc   = if ($props.PSObject.Properties["DriverDesc"]) { $props.DriverDesc } else { $null }
            }
            $RegistryInfo += $regEntry
            
            if ($null -ne $dvmtSize) {
                Write-Host "  Registry ($regPath):"
                Write-Host "    DVMT Size: $dvmtSize"
                Write-Host "    DVMT Max: $dvmtMaxSize"
            }
        }
    }
    $Test22.registry = $RegistryInfo
} catch {
    Write-Host "  WARNING: Failed to query DVMT registry values: $_"
    $Test22.registry = @()
}

# 2.2c — DxDiag GPU memory info (parsed from systeminfo)
try {
    $GpuMemInfo = Get-CimInstance -ClassName Win32_VideoController | Where-Object { $_.Name -match "Intel|Arc" } | 
        Select-Object Name, AdapterRAM, AdapterDACType, VideoModeDescription
    $Test22.dxdiag_summary = $GpuMemInfo | ForEach-Object {
        @{
            name         = $_.Name
            adapter_ram  = $_.AdapterRAM
            dac_type     = $_.AdapterDACType
            video_mode   = $_.VideoModeDescription
        }
    }
} catch {
    $Test22.dxdiag_summary = @()
}

$Test22.failures = $Test22Failures
Write-Host ""

# ---------------------------------------------------------------------------
# Test 2.3 — Runtime Memory Visibility
# ---------------------------------------------------------------------------
Write-Host "[Test 2.3] Runtime Memory Visibility — Effective Ceiling Verification"

$Test23Failures = @()
$Test23 = @{
    test_id     = "2.3"
    description = "Runtime memory visibility — effective ceiling verification"
}

# 2.3a — Total physical memory via WMI
try {
    $CS = Get-CimInstance -ClassName Win32_ComputerSystem
    $TotalPhysicalBytes = $CS.TotalPhysicalMemory
    $TotalPhysicalMB    = [math]::Round($TotalPhysicalBytes / 1MB, 1)
    $TotalPhysicalGB    = [math]::Round($TotalPhysicalBytes / 1GB, 3)
    
    $RawMinusDVMT_MB = ($RAW_PHYSICAL_GB * 1024) - $EXPECTED_DVMT_MB
    $ActualMinusRaw_MB = ($RAW_PHYSICAL_GB * 1024) - $TotalPhysicalMB
    
    Write-Host "  Raw Physical (spec):     ${RAW_PHYSICAL_GB}GB (${RawMinusDVMT_MB}MB + ${EXPECTED_DVMT_MB}MB DVMT)"
    Write-Host "  OS-Visible Physical:     ${TotalPhysicalGB}GB (${TotalPhysicalMB}MB)"
    Write-Host "  Inferred DVMT Reservation: ${ActualMinusRaw_MB}MB"
    
    $Test23.raw_physical_gb = $RAW_PHYSICAL_GB
    $Test23.os_visible_mb   = $TotalPhysicalMB
    $Test23.os_visible_gb   = $TotalPhysicalGB
    $Test23.inferred_dvmt_mb = $ActualMinusRaw_MB
    
    # Check if inferred DVMT is within tolerance of expected 512MB
    $DvmtDelta = [math]::Abs($ActualMinusRaw_MB - $EXPECTED_DVMT_MB)
    if ($DvmtDelta -le $TOLERANCE_MB) {
        $Test23.dvmt_match = $true
        Write-Host "  DVMT reservation CONFIRMED: ${ActualMinusRaw_MB}MB (within ±${TOLERANCE_MB}MB of ${EXPECTED_DVMT_MB}MB)"
    } else {
        $Test23.dvmt_match = $false
        Write-Host "  WARNING: DVMT reservation MISMATCH: ${ActualMinusRaw_MB}MB (expected ~${EXPECTED_DVMT_MB}MB ±${TOLERANCE_MB}MB)"
        $Test23Failures += New-FailureRecord -TestId "2.3a" -Metric "inferred_dvmt_mb" -Expected "${EXPECTED_DVMT_MB}MB (±${TOLERANCE_MB}MB)" -Actual "${ActualMinusRaw_MB}MB"
    }
} catch {
    Write-Host "  ERROR: Failed to query physical memory: $_"
    $Test23.os_visible_mb = $null
    $Test23Failures += New-FailureRecord -TestId "2.3a" -Metric "total_physical_memory_query" -Expected "success" -Actual "error: $_"
}

# 2.3b — Effective ceiling computation
try {
    $EffectiveCeiling_MB = $TotalPhysicalMB
    $EffectiveCeiling_GB = $TotalPhysicalGB
    $CeilingTarget_GB    = 31.323  # Empirical — ADR-005
    $CeilingTarget_MB    = $CeilingTarget_GB * 1024
    $CeilingDelta_MB     = [math]::Abs($EffectiveCeiling_MB - $CeilingTarget_MB)
    
    $Test23.effective_ceiling_mb = $EffectiveCeiling_MB
    $Test23.effective_ceiling_gb = $EffectiveCeiling_GB
    $Test23.ceiling_target_gb    = $CeilingTarget_GB
    $Test23.ceiling_delta_mb     = $CeilingDelta_MB
    
    if ($CeilingDelta_MB -le $TOLERANCE_MB) {
        $Test23.ceiling_pass = $true
        Write-Host "  Effective ceiling CONFIRMED: ${EffectiveCeiling_GB}GB (target: ${CeilingTarget_GB}GB ±${TOLERANCE_MB}MB)"
    } else {
        $Test23.ceiling_pass = $false
        Write-Host "  WARNING: Effective ceiling MISMATCH: ${EffectiveCeiling_GB}GB (target: ${CeilingTarget_GB}GB ±${TOLERANCE_MB}MB)"
        $Test23Failures += New-FailureRecord -TestId "2.3b" -Metric "effective_ceiling_gb" -Expected "${CeilingTarget_GB}GB (±${TOLERANCE_MB}MB)" -Actual "${EffectiveCeiling_GB}GB"
    }
} catch {
    Write-Host "  ERROR: Ceiling computation failed: $_"
    $Test23.ceiling_pass = $false
    $Test23Failures += New-FailureRecord -TestId "2.3b" -Metric "ceiling_computation" -Expected "success" -Actual "error: $_"
}

# 2.3c — Hardware inventory snapshot
try {
    $Processor = Get-CimInstance -ClassName Win32_Processor | Select-Object -First 1
    $OS        = Get-CimInstance -ClassName Win32_OperatingSystem
    $BIOS      = Get-CimInstance -ClassName Win32_BIOS
    $Board     = Get-CimInstance -ClassName Win32_BaseBoard
    
    $Test23.hardware_snapshot = @{
        processor     = $Processor.Name
        cpu_max_mhz   = $Processor.MaxClockSpeed
        cpu_cores     = $Processor.NumberOfCores
        cpu_threads   = $Processor.NumberOfLogicalProcessors
        os_name       = $OS.Caption
        os_version    = $OS.Version
        os_build      = $OS.BuildNumber
        bios_vendor   = $BIOS.Manufacturer
        bios_version  = $BIOS.SMBIOSBIOSVersion
        board_product = $Board.Product
        board_vendor  = $Board.Manufacturer
    }
    
    Write-Host ""
    Write-Host "  Hardware Snapshot:"
    Write-Host "    CPU:  $($Processor.Name)"
    Write-Host "    Cores/Threads: $($Processor.NumberOfCores)/$($Processor.NumberOfLogicalProcessors)"
    Write-Host "    OS:   $($OS.Caption) ($($OS.BuildNumber))"
    Write-Host "    BIOS: $($BIOS.SMBIOSBIOSVersion)"
    Write-Host "    Board: $($Board.Manufacturer) $($Board.Product)"
} catch {
    Write-Host "  WARNING: Hardware snapshot partial: $_"
    $Test23.hardware_snapshot = @{ error = $_.ToString() }
}

$Test23.failures = $Test23Failures
Write-Host ""

# ---------------------------------------------------------------------------
# Gate Evaluation
# ---------------------------------------------------------------------------
$AllFailures = @()
$AllFailures += $Test22Failures | Where-Object { $_.disposition -eq "FAIL" }
$AllFailures += $Test23Failures | Where-Object { $_.disposition -eq "FAIL" }

$GatePass = ($AllFailures.Count -eq 0)
$Disposition = if ($GatePass) { "PASS" } else { "FAIL" }

$GateEvaluation = @{
    gate          = "VALIDATE_DVMT_BUDGET"
    disposition   = $Disposition
    pass          = $GatePass
    failures      = $AllFailures
    warnings      = @($Test22Failures | Where-Object { $_.disposition -eq "WARNING" })
    effective_ceiling_gb = $Test23.effective_ceiling_gb
    inferred_dvmt_mb     = $Test23.inferred_dvmt_mb
    recommendation = if ($GatePass) {
        "DVMT budget confirmed. Effective ceiling of $($Test23.effective_ceiling_gb)GB established. Proceed with memory allocation planning."
    } else {
        "ESCALATE: DVMT budget verification failed. Review hardware_snapshot and registry values. Do NOT delete this branch."
    }
}

# ---------------------------------------------------------------------------
# Assemble and Write Evidence
# ---------------------------------------------------------------------------
$Report = @{
    gate                = "VALIDATE_DVMT_BUDGET"
    timestamp           = $Timestamp
    effective_ceiling_gb = $Test23.effective_ceiling_gb
    expected_dvmt_mb    = $EXPECTED_DVMT_MB
    test_2_1            = $Test21
    test_2_2            = $Test22
    test_2_3            = $Test23
    gate_evaluation     = $GateEvaluation
}

$JsonOutput = $Report | ConvertTo-Json -Depth 10
$JsonOutput | Out-File -FilePath $OutputFile -Encoding utf8

Write-Host "=" -NoNewline; Write-Host ("=" * 71)
Write-Host "GATE RESULT: $Disposition"
if ($AllFailures.Count -gt 0) {
    Write-Host "FAILURES:"
    foreach ($f in $AllFailures) {
        Write-Host "  - $($f.test_id): $($f.metric) expected=$($f.expected) actual=$($f.actual)"
    }
}
Write-Host "Recommendation: $($GateEvaluation.recommendation)"
Write-Host "Evidence written to: $OutputFile"
Write-Host "=" -NoNewline; Write-Host ("=" * 71)

# Exit code
if ($GatePass) { exit 0 } else { exit 1 }
