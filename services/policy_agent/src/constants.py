"""
Policy Agent Constants
=======================
Service-specific constants derived from shared hardware constants + Use Case specs.
"""

from __future__ import annotations

from shared.constants import (
    FAIL_CLOSED,
    JWT_VALIDITY_SECONDS as _SHARED_JWT_VALIDITY_SECONDS,
    PA_DEVICE,
    PA_MODEL_QUANT,
    PA_MODEL_SIZE_PARAMS,
    PA_MODEL_WEIGHT_MB,
    PA_PREEMPTION_P95_BUDGET_MS,
    PA_PREEMPTION_P99_BUDGET_MS,
)

# Re-export hardware constants for in-service use
INFERENCE_DEVICE: str = PA_DEVICE
"""PA inference device (ADR-010: GPU)."""
NPU_PRIORITY: int = 0
"""DEPRECATED (ADR-010): Retained for backward compatibility. Use INFERENCE_DEVICE."""
MODEL_PARAMS: str = PA_MODEL_SIZE_PARAMS
MODEL_QUANT: str = PA_MODEL_QUANT
MODEL_WEIGHT_MB: int = PA_MODEL_WEIGHT_MB
PREEMPTION_P95_MS: float = PA_PREEMPTION_P95_BUDGET_MS
PREEMPTION_P99_MS: float = PA_PREEMPTION_P99_BUDGET_MS
SECURITY_POSTURE_FAIL_CLOSED: bool = FAIL_CLOSED

# Service-specific constants
SERVICE_NAME: str = "policy_agent"
MEASURED_BOOT_REQUIRED: bool = True
"""Measured Boot Sequence must complete before the PA accepts requests."""

MEASURED_BOOT_MAX_ATTEMPTS: int = 3
"""Deterministic bounded retries for measured-boot startup phases."""

MEASURED_BOOT_RETRY_DELAY_S: float = 0.25
"""Fixed retry backoff in seconds between measured-boot attempts."""

JWT_VALIDITY_SECONDS: int = _SHARED_JWT_VALIDITY_SECONDS
"""Hard TTL in seconds (Use Cases_FINAL.md §3: 5-second hard expiry).

Re-exported from ``shared.constants`` — the single source of truth shared with
the destination validators' nonce-TTL alignment (#638). Per-service TOML
``[jwt] validity_seconds`` overrides the minter at runtime within 1..300 s."""

JWT_ISSUER: str = "policy_agent"
"""JWT issuer identity embedded in every minted token."""

PA_JWT_TPM_KEY_NAME: str = "BlarAI-PA-JWT-Signing"
"""Persisted TPM key name for the production JWT signing key (ADR-021).

The non-exportable ECDSA P-256 key lives in the platform TPM. The provisioning
ceremony (``python -m shared.security.provision_signing_key``) creates it once
on the host and exports its PUBLIC half to ``certs/pa_public.pem``. Production
config (``[jwt] tpm_key_name``) MUST match this name; production signing is
fail-closed until the ceremony is run. Dev mode uses ephemeral in-memory keys
and never touches the TPM."""

RULE_ENGINE_VERSION: str = "1.0.0"
"""Deterministic rule engine version for audit trail."""

PROBABILISTIC_CONFIDENCE_THRESHOLD: float = 0.75
"""Minimum GPU classifier confidence to pass probabilistic gate."""

ESCALATION_CONFIDENCE_RANGE: tuple[float, float] = (0.50, 0.75)
"""Confidence range that triggers ESCALATE instead of DENY."""

# Rate limiting defaults (P1.2)
RATE_LIMIT_MAX_REQUESTS: int = 100
"""Maximum requests per agent within the sliding window."""

RATE_LIMIT_WINDOW_SECONDS: float = 60.0
"""Sliding window duration in seconds."""
