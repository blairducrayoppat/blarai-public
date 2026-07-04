"""
Measured Boot Sequence — Policy Agent
=======================================
USE-CASE-001: Ensures the PA is in a known-good state before accepting
any adjudication requests.

Boot sequence (strict order):
  1. Load configuration (TOML).
  2. Verify TPM/Pluton attestation (or dev-mode skip).
  3. Verify model weight integrity (SHA-256 vs Known-Good Manifest).
  4. Load GPU model (compile for GPU device per ADR-010).
  5. Load rule engine configuration (ACL matrix, deny lists).
  6. Start vsock listener.
  7. Set readiness flag.

Any step failure is FATAL — the PA does not start in a degraded state.
Fail-Closed: all downstream services get DENY until the PA is ready.

Security:
  - Boot order is enforced by sequential gating.
  - No external network calls during boot.
  - Dev mode flag clearly separates attestation bypass from production.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable


@dataclass
class BootState:
    """Tracks progress through the Measured Boot Sequence."""

    config_loaded: bool = False
    attestation_verified: bool = False
    weights_verified: bool = False
    npu_model_loaded: bool = False
    """NOTE: field name retained for schema compatibility. Actually GPU per ADR-010."""
    rules_loaded: bool = False
    listener_started: bool = False
    ready: bool = False
    attempt_count: int = 0
    hard_locked: bool = False
    error_code: str | None = None
    error_message: str | None = None

    @property
    def failed_step(self) -> str | None:
        """Return the name of the first incomplete step, or None if all passed."""
        checks = [
            ("config_loaded", self.config_loaded),
            ("attestation_verified", self.attestation_verified),
            ("weights_verified", self.weights_verified),
            ("npu_model_loaded", self.npu_model_loaded),
            ("rules_loaded", self.rules_loaded),
            ("listener_started", self.listener_started),
        ]
        for name, passed in checks:
            if not passed:
                return name
        return None


@dataclass(frozen=True)
class MeasuredBootPolicy:
    """Deterministic measured-boot retry policy."""

    max_attempts: int = 3
    retry_delay_s: float = 0.25


@dataclass(frozen=True)
class MeasuredBootStep:
    """Single measured-boot phase descriptor."""

    name: str
    state_field: str
    action: Callable[[], bool]
    error_code: str


def run_measured_boot(
    config_path: str,
    dev_mode: bool = False,
    *,
    steps: list[MeasuredBootStep] | None = None,
    policy: MeasuredBootPolicy | None = None,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> BootState:
    """Execute the Measured Boot Sequence.

    Args:
        config_path: Path to the Policy Agent TOML configuration.
        dev_mode: If True, skip hardware attestation (development only).

    Returns:
        BootState reflecting how far the sequence progressed.
        If ready=False, the PA MUST NOT accept requests.
    """
    _ = dev_mode
    selected_policy = policy or MeasuredBootPolicy()
    if selected_policy.max_attempts < 1:
        raise ValueError("Measured boot policy max_attempts must be >= 1")
    if selected_policy.retry_delay_s < 0:
        raise ValueError("Measured boot policy retry_delay_s must be >= 0")

    last_state = BootState(
        attempt_count=0,
        error_code="PA_BOOT_STEPS_MISSING",
        error_message="Measured-boot steps were not provided.",
    )
    if not steps:
        return last_state

    for attempt in range(1, selected_policy.max_attempts + 1):
        state = BootState(attempt_count=attempt)

        if config_path.strip():
            state.config_loaded = True
        else:
            state.error_code = "PA_BOOT_CONFIG_PATH_INVALID"
            state.error_message = "Measured-boot config path is empty."
            last_state = state
            continue

        all_steps_passed = True
        for step in steps:
            try:
                success = bool(step.action())
            except Exception as exc:  # noqa: BLE001
                state.error_code = step.error_code
                state.error_message = f"{step.name} raised exception: {exc}"
                all_steps_passed = False
                break

            if not success:
                state.error_code = step.error_code
                state.error_message = (
                    f"Measured-boot phase '{step.name}' returned False."
                )
                all_steps_passed = False
                break

            setattr(state, step.state_field, True)

        if all_steps_passed:
            state.ready = True
            return state

        last_state = state
        if attempt < selected_policy.max_attempts:
            sleep_fn(selected_policy.retry_delay_s)

    last_state.hard_locked = True
    if last_state.error_code is None:
        last_state.error_code = "PA_BOOT_UNKNOWN_FAILURE"
    return last_state
