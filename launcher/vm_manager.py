"""
Hyper-V VM Lifecycle Manager
=============================
Manages the BlarAI-Orchestrator Hyper-V VM: start, stop, status checks.
Requires Administrator privileges for Hyper-V PowerShell cmdlets.

Security:
  - No external network calls.
  - Fail-Closed: if VM operations fail, report but do not crash.
  - PowerShell subprocess calls use -NoProfile for deterministic execution.
"""

from __future__ import annotations

import ctypes
import logging
from pathlib import Path
import subprocess
import sys
import time
from enum import Enum

from shared.constants import ORCHESTRATOR_VM_NAME

logger = logging.getLogger(__name__)

# Timeout for VM to reach Running state after Start-VM (seconds).
VM_START_TIMEOUT_S: float = 60.0

# Poll interval while waiting for VM to start (seconds).
VM_POLL_INTERVAL_S: float = 2.0

# Timeout for VM to stop after Stop-VM (seconds).
VM_STOP_TIMEOUT_S: float = 30.0


class VMState(str, Enum):
    """Hyper-V VM states."""

    RUNNING = "Running"
    OFF = "Off"
    SAVED = "Saved"
    PAUSED = "Paused"
    STARTING = "Starting"
    UNKNOWN = "Unknown"


def is_admin() -> bool:
    """Check if the current process has Administrator privileges.

    Returns:
        True if running elevated.
    """
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())  # type: ignore[attr-defined]
    except (AttributeError, OSError):
        return False


def request_elevation() -> bool:
    """Re-launch the current process with Administrator privileges via UAC.

    This function does NOT return if elevation succeeds — the current
    process is replaced by the elevated one.

    Returns:
        False if the user declined UAC or elevation failed.
    """
    try:
        result = ctypes.windll.shell32.ShellExecuteW(  # type: ignore[attr-defined]
            None,
            "runas",
            sys.executable,
            " ".join(sys.argv),
            None,
            1,  # SW_SHOWNORMAL
        )
        # ShellExecuteW returns > 32 on success
        return int(result) > 32
    except (AttributeError, OSError) as exc:
        logger.error("Elevation request failed: %s", exc)
        return False


def _run_ps(command: str, timeout: float = 30.0) -> tuple[int, str, str]:
    """Execute a PowerShell command and return (exit_code, stdout, stderr).

    Args:
        command: PowerShell command string.
        timeout: Subprocess timeout in seconds.

    Returns:
        (exit_code, stdout, stderr)
    """
    try:
        result = subprocess.run(
            [
                "powershell.exe",
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                command,
            ],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return result.returncode, result.stdout.strip(), result.stderr.strip()
    except subprocess.TimeoutExpired:
        logger.error("PowerShell command timed out: %s", command)
        return -1, "", "timeout"
    except FileNotFoundError:
        logger.error("powershell.exe not found")
        return -1, "", "powershell not found"


def verify_vm_zero_nic(vm_name: str = ORCHESTRATOR_VM_NAME) -> bool:
    """Verify the guest VM has ZERO network adapters (Fail-Closed posture).

    The BlarAI guest must remain NIC-less under the one-door host-side-fetch
    composition (LA decision, #655 verdict 2026-06-10): the only network
    door is the host-side mediated fetch path — a guest network adapter
    would be a second, unmediated door.  This check enumerates the VM's
    adapters via ``Get-VMNetworkAdapter`` and returns True ONLY when the
    enumeration succeeds AND reports zero adapters.

    Fail-Closed in every other case: an attached adapter, an enumeration
    failure (PowerShell error, timeout, missing VM), or unparseable output
    all return False — the caller refuses to start the VM.

    Args:
        vm_name: Hyper-V VM name.

    Returns:
        True only when the VM verifiably has zero network adapters.
    """
    code, stdout, stderr = _run_ps(
        f'@(Get-VMNetworkAdapter -VMName "{vm_name}" -ErrorAction Stop).Count'
    )
    if code != 0:
        logger.error(
            "Zero-NIC posture check FAILED for VM '%s': adapter enumeration "
            "errored (%s) — refusing fail-closed (the guest must verifiably "
            "have no network adapters before it runs).",
            vm_name,
            stderr or "unknown error",
        )
        return False
    try:
        adapter_count = int(stdout.strip())
    except ValueError:
        logger.error(
            "Zero-NIC posture check FAILED for VM '%s': unparseable adapter "
            "count %r — refusing fail-closed.",
            vm_name,
            stdout,
        )
        return False
    if adapter_count != 0:
        logger.error(
            "Zero-NIC posture VIOLATED for VM '%s': %d network adapter(s) "
            "attached.  The BlarAI guest must have NO network adapters (the "
            "one-door host-side-fetch composition); remove them with "
            "Remove-VMNetworkAdapter before starting BlarAI.  VM start "
            "REFUSED (Fail-Closed).",
            vm_name,
            adapter_count,
        )
        return False
    logger.info("Zero-NIC posture verified for VM '%s' (0 adapters)", vm_name)
    return True


def get_vm_state(vm_name: str = ORCHESTRATOR_VM_NAME) -> VMState:
    """Query the current state of the Hyper-V VM.

    Args:
        vm_name: Hyper-V VM name.

    Returns:
        VMState enum value.
    """
    code, stdout, stderr = _run_ps(
        f'(Get-VM -Name "{vm_name}" -ErrorAction SilentlyContinue).State'
    )
    if code != 0 or not stdout:
        logger.warning("VM state query failed: %s", stderr or "unknown error")
        return VMState.UNKNOWN

    state_str = stdout.strip()
    try:
        return VMState(state_str)
    except ValueError:
        logger.warning("Unknown VM state: %s", state_str)
        return VMState.UNKNOWN


def start_vm(vm_name: str = ORCHESTRATOR_VM_NAME) -> bool:
    """Start the Hyper-V VM if it's not already running.

    Blocks until the VM reaches Running state or timeout expires.

    Zero-NIC precondition (#655 LA verdict 2026-06-10): before the VM is
    started — and before an already-running VM is accepted — the guest's
    network adapters are enumerated and the start is REFUSED fail-closed
    unless there are verifiably zero.  The check covers the already-running
    path deliberately: a running guest with an attached NIC is the posture
    violation, regardless of who started it.

    Args:
        vm_name: Hyper-V VM name.

    Returns:
        True if VM is running (or was already running), False on failure.
    """
    current = get_vm_state(vm_name)
    if current == VMState.UNKNOWN:
        logger.error("VM '%s' not found or Hyper-V not available", vm_name)
        return False

    # Zero-NIC posture gate — refuses BEFORE Start-VM and also refuses an
    # already-running guest that has an adapter attached (Fail-Closed).
    if not verify_vm_zero_nic(vm_name):
        return False

    if current == VMState.RUNNING:
        logger.info("VM '%s' already running", vm_name)
        return True

    logger.info("Starting VM '%s' (current state: %s)", vm_name, current.value)
    code, stdout, stderr = _run_ps(
        f'Start-VM -Name "{vm_name}" -ErrorAction Stop',
        timeout=VM_START_TIMEOUT_S,
    )

    if code != 0:
        logger.error("Start-VM failed: %s", stderr)
        return False

    # Wait for Running state
    start_time = time.monotonic()
    while time.monotonic() - start_time < VM_START_TIMEOUT_S:
        state = get_vm_state(vm_name)
        if state == VMState.RUNNING:
            logger.info("VM '%s' is Running", vm_name)
            return True
        logger.info("VM '%s' state: %s — waiting…", vm_name, state.value)
        time.sleep(VM_POLL_INTERVAL_S)

    logger.error("VM '%s' did not reach Running state within timeout", vm_name)
    return False


def stop_vm(
    vm_name: str = ORCHESTRATOR_VM_NAME,
    force: bool = True,
) -> bool:
    """Stop the Hyper-V VM.

    Args:
        vm_name: Hyper-V VM name.
        force: If True, use -Force (immediate shutdown). If False, graceful.

    Returns:
        True if VM is Off (or was already off), False on failure.
    """
    current = get_vm_state(vm_name)
    if current == VMState.OFF:
        logger.info("VM '%s' already off", vm_name)
        return True

    if current == VMState.UNKNOWN:
        logger.warning("VM '%s' not found — treating as stopped", vm_name)
        return True

    force_flag = " -Force" if force else ""
    logger.info(
        "Stopping VM '%s' (force=%s)", vm_name, force
    )
    code, stdout, stderr = _run_ps(
        f'Stop-VM -Name "{vm_name}"{force_flag} -ErrorAction Stop',
        timeout=VM_STOP_TIMEOUT_S,
    )

    if code != 0:
        logger.error("Stop-VM failed: %s", stderr)
        return False

    # Verify Off state
    start_time = time.monotonic()
    while time.monotonic() - start_time < VM_STOP_TIMEOUT_S:
        state = get_vm_state(vm_name)
        if state == VMState.OFF:
            logger.info("VM '%s' is Off", vm_name)
            return True
        time.sleep(VM_POLL_INTERVAL_S)

    logger.warning("VM '%s' may not have fully stopped", vm_name)
    return False


def ensure_vm_running(vm_name: str = ORCHESTRATOR_VM_NAME) -> bool:
    """Ensure the VM is running, starting it if necessary.

    This is the primary entry point for the launcher. It:
    1. Checks if already running → returns True immediately
    2. Attempts to start → waits for Running state
    3. Returns False on failure (Fail-Closed)

    Args:
        vm_name: Hyper-V VM name.

    Returns:
        True if VM is running, False otherwise.
    """
    return start_vm(vm_name)


def is_guest_service_interface_enabled(
    vm_name: str = ORCHESTRATOR_VM_NAME,
) -> bool:
    """Check whether Hyper-V Guest Service Interface is enabled.

    This integration service is required for ``Copy-VMFile`` host→guest
    artifact deployment.

    Args:
        vm_name: Hyper-V VM name.

    Returns:
        True when the Guest Service Interface is enabled, else False.
    """
    code, stdout, stderr = _run_ps(
        (
            f"(Get-VMIntegrationService -VMName \"{vm_name}\" "
            f"-Name \"Guest Service Interface\" "
            "-ErrorAction SilentlyContinue).Enabled"
        )
    )
    if code != 0:
        logger.error(
            "Guest Service Interface check failed for VM '%s': %s",
            vm_name,
            stderr or "unknown error",
        )
        return False
    return stdout.strip().lower() == "true"


def copy_file_to_vm(
    source_path: str | Path,
    destination_path: str,
    vm_name: str = ORCHESTRATOR_VM_NAME,
    *,
    create_full_path: bool = True,
    timeout: float = 120.0,
    retries: int = 3,
    retry_delay_s: float = 2.0,
) -> bool:
    """Copy a file from host to Hyper-V guest via Guest Service Interface.

    Args:
        source_path: File path on host.
        destination_path: Absolute file path in the guest VM.
        vm_name: Hyper-V VM name.
        create_full_path: Create destination directories in guest.
        timeout: PowerShell command timeout in seconds.
        retries: Number of copy attempts before giving up.
        retry_delay_s: Delay in seconds between retry attempts.

    Returns:
        True on successful copy; False on failure (Fail-Closed).
    """
    src = Path(source_path)
    if not src.exists() or not src.is_file():
        logger.error("Source file for VM copy does not exist: %s", src)
        return False

    create_flag = " -CreateFullPath" if create_full_path else ""
    command = (
        f'Copy-VMFile -Name "{vm_name}" '
        f'-SourcePath "{src.resolve()}" '
        f'-DestinationPath "{destination_path}" '
        "-FileSource Host"
        f"{create_flag} -Force -ErrorAction Stop"
    )
    attempts = max(1, retries)
    last_error = ""
    for attempt in range(1, attempts + 1):
        code, _stdout, stderr = _run_ps(command, timeout=timeout)
        if code == 0:
            logger.info(
                "Copied host file to VM '%s': %s -> %s",
                vm_name,
                src,
                destination_path,
            )
            return True

        last_error = stderr
        logger.warning(
            "Copy-VMFile attempt %d/%d failed (vm=%s, source=%s, destination=%s): %s",
            attempt,
            attempts,
            vm_name,
            src,
            destination_path,
            stderr,
        )
        if attempt < attempts:
            time.sleep(retry_delay_s)

    logger.error(
        "Copy-VMFile failed after %d attempts (vm=%s, source=%s, destination=%s): %s",
        attempts,
        vm_name,
        src,
        destination_path,
        last_error,
    )
    return False
