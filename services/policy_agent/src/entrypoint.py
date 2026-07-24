"""
Policy Agent Service Entrypoint
================================
Priority-2 operational milestone: service startup wiring with fail-closed
initialization and graceful shutdown.

Scope for this milestone:
  - Load service config.
  - Load deterministic rule-engine config.
  - Load GPU inference model.
  - Start vsock listener (no accept loop yet; Priority 3).

Security:
  - Fail-Closed on any startup failure.
  - No external network calls.
  - Dev-mode can use ephemeral JWT keys for local startup.
"""

from __future__ import annotations

import hashlib
import logging
import re
import threading
import tomllib
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from shared.crypto.jwt_validator import AgenticJWTValidator
from shared.security import tpm_signer
from shared.security.audit_log import (
    AUDIT_TPM_KEY_NAME,
    DEFAULT_MAX_ACTIVE_BYTES,
    DEFAULT_MAX_ACTIVE_RECORDS,
    AuditLog,
    AuditProvisioningError,
    HmacSha256Signer,
    TpmRecordSigner,
)
from shared.inference.shared_pipeline import SharedInferencePipeline
from shared.ipc.protocol import AdjudicationResponse
from shared.ipc.vsock import VsockAddress, VsockConfig
from shared.models.weight_integrity import load_manifest, load_manifest_verified
from shared.schemas.car import CanonicalActionRepresentation
from shared.service_signals import install_graceful_shutdown
from services.policy_agent.src.adjudicator import HybridAdjudicator
from services.policy_agent.src.boot import (
    BootState,
    MeasuredBootPolicy,
    MeasuredBootStep,
    run_measured_boot,
)
from services.policy_agent.src.config_loader import RuleEngineConfig, load_rule_engine_config
from services.policy_agent.src.constants import (
    MEASURED_BOOT_MAX_ATTEMPTS,
    MEASURED_BOOT_RETRY_DELAY_S,
)
from services.policy_agent.src.gpu_inference import PolicyGPUInference
from services.policy_agent.src.ipc import PolicyAgentListener
from services.policy_agent.src.jwt_minter import AgenticJWTMinter
from services.policy_agent.src.rule_engine import RateLimiter
from shared.runtime_config import (
    ConfigResolutionError,
    DeploymentMode,
    build_failure_fingerprint,
    resolve_deployment_mode,
    resolve_service_config_path,
    resolve_service_root,
)
from shared import config_validation
from shared.constants import (
    DRAFT_MODEL_OV_PATH,
    SPECULATIVE_DECODING_ENABLED,
)

logger = logging.getLogger(__name__)


def self_or_cls_error_code(prefix: str, code: str) -> str:
    normalized_prefix = f"{prefix}_"
    if code.startswith(normalized_prefix):
        return code
    return f"{prefix}_{code}"


@dataclass(frozen=True)
class PolicyAgentEntrypointConfig:
    """Resolved startup config for the Policy Agent entrypoint."""

    config_dir: Path
    model_dir: Path
    manifest_path: Path | None
    model_bin_path: Path
    device: str
    draft_model_dir: Path | None
    speculative_decoding_enabled: bool
    dev_mode: bool
    jwt_tpm_key_name: str | None
    jwt_ca_cert_path: Path | None
    jwt_issuer: str
    jwt_validity_seconds: int
    vsock_config: VsockConfig
    deployment_mode: DeploymentMode
    require_signed_manifest: bool = False
    """When True, the manifest MUST carry a valid TPM signature (.sig file) or boot
    is FAIL-CLOSED.  Defaults to False (capability built; off until LA flips it).
    Set via [security].require_signed_manifest in the service config (FUT-04)."""

    require_signed_draft_manifest: bool = False
    """DRAFT-manifest signature posture for the STANDALONE path (FUT-05 / #917).
    When True, the speculative-decoding draft's manifest MUST carry a valid TPM
    .sig or the standalone PA build FAILS CLOSED; when False (dormant, the shipped
    default) the draft is verified DIGEST-ONLY (.sig not consulted, digest still
    enforced). Kept SEPARATE from require_signed_manifest because the draft is
    NON-AUTHORITATIVE (the signed 14B re-verifies every token). Set via
    [security].require_signed_draft_manifest. Only the standalone/fallback path
    reads it; the host-mode shared pipeline is gated by the AO config's copy."""

    audit_log_path: Path | None = None
    """Filesystem path for the tamper-evident adjudication audit stream
    (Sprint 13 / Domain 7).  When None, the entrypoint resolves a default under
    the service data dir.  Override via [security].audit_log_path.  The sink is
    ACTIVE in both dev and production — the audit trail is forensic value in both."""

    audit_hmac_key_id: str = "dev-stub"
    """Key identifier written into dev/CI audit records (stub path only).  Override
    via [security].audit_hmac_key_id.  Cosmetic/forensic label — the actual HMAC
    key is sourced separately (see _build_audit_log dev branch)."""

    audit_max_active_bytes: int = DEFAULT_MAX_ACTIVE_BYTES
    """Active audit-file byte cap; crossing it rotates the file into a sealed,
    gzip-compressed segment (ISS-607 / ADR-029).  Default 64 MiB.  Override via
    [security].audit_max_active_bytes.  ``<= 0`` disables the byte trip."""

    audit_max_active_records: int = DEFAULT_MAX_ACTIVE_RECORDS
    """Active audit-file record-count cap; crossing it rotates (ISS-607).  Default
    100_000.  Override via [security].audit_max_active_records.  Whichever of the
    byte/record caps trips first rotates.  ``<= 0`` disables the count trip."""

    audit_archive_max_bytes: int | None = None
    """Retention ceiling on TOTAL sealed-segment bytes (ISS-607 / ADR-029).
    ``None`` (default) = keep everything — the chosen keep-all policy.  If set,
    whole sealed segments are pruned oldest-first and each prune is itself
    audited (signed RETENTION_PRUNE record).  Override via
    [security].audit_archive_max_bytes."""

    audit_archive_max_age_days: int | None = None
    """Retention ceiling on sealed-segment age in days (ISS-607 / ADR-029).
    ``None`` (default) = keep everything.  If set, sealed segments older than this
    are pruned oldest-first, each prune audited.  Override via
    [security].audit_archive_max_age_days."""


class PolicyAgentService:
    """Policy Agent startup/shutdown wrapper for launcher integration."""

    def __init__(
        self,
        config_path: str | Path,
        *,
        dev_mode_override: bool | None = None,
        deployment_mode: str | DeploymentMode | None = None,
        shared_pipeline: "SharedInferencePipeline | None" = None,
    ) -> None:
        self._config_path = Path(config_path)
        self._dev_mode_override = dev_mode_override
        self._deployment_mode = resolve_deployment_mode(deployment_mode)
        self._running = False
        self._last_failure: dict[str, str] | None = None

        self._inference: PolicyGPUInference | None = None
        self._adjudicator: HybridAdjudicator | None = None
        self._listener: PolicyAgentListener | None = None
        self._jwt_minter: AgenticJWTMinter | None = None
        self._loop_thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._measured_boot_hard_locked = False
        self._last_boot_state: BootState | None = None
        self._shared_pipeline = shared_pipeline

    @classmethod
    def from_default_config(
        cls,
        *,
        dev_mode_override: bool | None = None,
    ) -> "PolicyAgentService":
        return cls.from_runtime_mode(
            deployment_mode=None,
            dev_mode_override=dev_mode_override,
        )

    @classmethod
    def from_runtime_mode(
        cls,
        deployment_mode: str | DeploymentMode | None,
        *,
        dev_mode_override: bool | None = None,
        shared_pipeline: "SharedInferencePipeline | None" = None,
    ) -> "PolicyAgentService":
        service_root = resolve_service_root(__file__, 'services.policy_agent')
        resolved_mode = resolve_deployment_mode(deployment_mode)
        config_path = resolve_service_config_path(
            service_root,
            deployment_mode=resolved_mode,
        )
        return cls(
            config_path,
            dev_mode_override=dev_mode_override,
            deployment_mode=resolved_mode,
            shared_pipeline=shared_pipeline,
        )

    @property
    def running(self) -> bool:
        """True when the entrypoint has started successfully."""
        return self._running

    @property
    def last_failure(self) -> dict[str, str] | None:
        """Latest deterministic fail-closed startup fingerprint, if any."""
        return self._last_failure

    @property
    def measured_boot_state(self) -> BootState | None:
        """Latest measured-boot outcome."""
        return self._last_boot_state

    @property
    def measured_boot_hard_locked(self) -> bool:
        """True when measured-boot retries are exhausted for this process."""
        return self._measured_boot_hard_locked

    @classmethod
    def validate_runtime_config(
        cls,
        *,
        deployment_mode: str | DeploymentMode | None,
        dev_mode_override: bool | None = None,
        config_path: str | Path | None = None,
    ) -> tuple[bool, dict[str, str] | None]:
        service_root = resolve_service_root(__file__, 'services.policy_agent')
        try:
            resolved_mode = resolve_deployment_mode(deployment_mode)
            resolved_path = resolve_service_config_path(
                service_root,
                deployment_mode=resolved_mode,
                explicit_config_path=config_path,
            )
        except ConfigResolutionError as exc:
            return (
                False,
                build_failure_fingerprint(
                    stage="config_resolution",
                    code=self_or_cls_error_code("PA", exc.code),
                    message=exc.message,
                ),
            )

        service = cls(
            resolved_path,
            dev_mode_override=dev_mode_override,
            deployment_mode=resolved_mode,
        )
        try:
            resolved = service._load_entrypoint_config()
            service._validate_security_material(
                model_bin_path=resolved.model_bin_path,
                manifest_path=resolved.manifest_path,
                jwt_tpm_key_name=resolved.jwt_tpm_key_name,
                jwt_ca_cert_path=resolved.jwt_ca_cert_path,
                dev_mode=resolved.dev_mode,
                require_signed_manifest=resolved.require_signed_manifest,
            )
        except ConfigResolutionError as exc:
            return (
                False,
                build_failure_fingerprint(
                    stage="config_validation",
                    code=self_or_cls_error_code("PA", exc.code),
                    message=exc.message,
                ),
            )
        return True, None

    def start(self) -> bool:
        """Start the Policy Agent entrypoint.

        Returns:
            True if all startup phases completed successfully.
            False on any failure (Fail-Closed).
        """
        if self._running:
            return True

        if self._measured_boot_hard_locked:
            self._last_failure = build_failure_fingerprint(
                stage="measured_boot",
                code="PA_BOOT_HARD_LOCKED",
                message=(
                    "Measured boot hard-lock active; restart process to re-arm "
                    "startup attempts."
                ),
            )
            logger.error("Policy Agent measured boot hard-locked: %s", self._last_failure)
            return False

        self._last_failure = None
        boot_context: dict[str, Any] = {}

        def _cleanup_boot_context() -> None:
            listener_obj = boot_context.get("listener")
            if listener_obj is not None and hasattr(listener_obj, "stop"):
                listener_obj.stop()
            inference_obj = boot_context.get("inference")
            if inference_obj is not None and hasattr(inference_obj, "unload"):
                inference_obj.unload()

        def _phase_attestation() -> bool:
            _cleanup_boot_context()
            boot_context.clear()
            try:
                resolved = self._load_entrypoint_config()
            except ConfigResolutionError as exc:
                boot_context["error_code"] = self_or_cls_error_code("PA", exc.code)
                boot_context["error_message"] = exc.message
                return False
            except Exception as exc:  # noqa: BLE001
                boot_context["error_code"] = "PA_CFG_UNEXPECTED_EXCEPTION"
                boot_context["error_message"] = str(exc)
                return False

            boot_context["resolved"] = resolved
            try:
                self._validate_security_material(
                    model_bin_path=resolved.model_bin_path,
                    manifest_path=resolved.manifest_path,
                    jwt_tpm_key_name=resolved.jwt_tpm_key_name,
                    jwt_ca_cert_path=resolved.jwt_ca_cert_path,
                    dev_mode=resolved.dev_mode,
                    require_signed_manifest=resolved.require_signed_manifest,
                )
            except ConfigResolutionError as exc:
                boot_context["error_code"] = self_or_cls_error_code("PA", exc.code)
                boot_context["error_message"] = exc.message
                return False
            return True

        def _phase_weight_integrity() -> bool:
            resolved = boot_context.get("resolved")
            if not isinstance(resolved, PolicyAgentEntrypointConfig):
                boot_context["error_code"] = "PA_BOOT_CONFIG_NOT_RESOLVED"
                boot_context["error_message"] = "Measured boot config was not resolved."
                return False

            if not self._verify_weight_integrity_gate(resolved):
                boot_context.setdefault("error_code", "PA_BOOT_WEIGHT_VERIFY_FAILED")
                boot_context.setdefault(
                    "error_message",
                    "Known-Good Manifest weight verification failed.",
                )
                return False
            return True

        def _phase_model_load() -> bool:
            resolved = boot_context.get("resolved")
            if not isinstance(resolved, PolicyAgentEntrypointConfig):
                boot_context["error_code"] = "PA_BOOT_CONFIG_NOT_RESOLVED"
                boot_context["error_message"] = "Measured boot config was not resolved."
                return False

            inference = PolicyGPUInference(
                model_dir=str(resolved.model_dir),
                device=resolved.device,
                manifest_path=(
                    str(resolved.manifest_path)
                    if resolved.manifest_path is not None
                    else None
                ),
                draft_model_dir=(
                    str(resolved.draft_model_dir)
                    if resolved.draft_model_dir is not None
                    else None
                ),
                speculative_decoding_enabled=resolved.speculative_decoding_enabled,
                shared_pipeline=self._shared_pipeline,
                require_signed_draft_manifest=resolved.require_signed_draft_manifest,
            )
            if not inference.load_model():
                boot_context["error_code"] = "PA_MODEL_LOAD_FAILED"
                boot_context["error_message"] = "Policy Agent model load returned False"
                return False

            boot_context["inference"] = inference
            return True

        def _phase_rules_load() -> bool:
            resolved = boot_context.get("resolved")
            inference = boot_context.get("inference")
            if not isinstance(resolved, PolicyAgentEntrypointConfig):
                boot_context["error_code"] = "PA_BOOT_CONFIG_NOT_RESOLVED"
                boot_context["error_message"] = "Measured boot config was not resolved."
                return False
            if inference is None or not hasattr(inference, "load_model"):
                boot_context["error_code"] = "PA_BOOT_MODEL_NOT_READY"
                boot_context["error_message"] = "Measured boot model phase did not complete."
                return False

            rule_config = load_rule_engine_config(resolved.config_dir)
            if rule_config is None:
                boot_context["error_code"] = "PA_RULE_CONFIG_LOAD_FAILED"
                boot_context["error_message"] = "Rule-engine config missing or malformed"
                return False

            jwt_minter = self._build_jwt_minter(resolved)
            if jwt_minter is None:
                boot_context["error_code"] = "PA_JWT_MINTER_INIT_FAILED"
                boot_context["error_message"] = "JWT minter initialization failed"
                return False

            boot_context["rule_config"] = rule_config
            boot_context["adjudicator"] = self._build_adjudicator(
                inference,
                rule_config,
                resolved,
            )
            boot_context["jwt_minter"] = jwt_minter
            return True

        def _phase_listener_start() -> bool:
            resolved = boot_context.get("resolved")
            if not isinstance(resolved, PolicyAgentEntrypointConfig):
                boot_context["error_code"] = "PA_BOOT_CONFIG_NOT_RESOLVED"
                boot_context["error_message"] = "Measured boot config was not resolved."
                return False

            def _handler(car_json: str, request_id: str) -> AdjudicationResponse:
                return self._handle_adjudication(car_json, request_id)

            listener = PolicyAgentListener(
                resolved.vsock_config,
                handler=_handler,
                dev_mode=resolved.dev_mode,
                # host_mode=True (default) → production loopback+mTLS.
                # host_mode=False → AF_HYPERV (deferred, #615).
                host_mode=(resolved.deployment_mode == DeploymentMode.HOST),
            )
            if not listener.start():
                boot_context["error_code"] = "PA_LISTENER_START_FAILED"
                boot_context["error_message"] = "Policy Agent listener failed to bind/listen"
                return False

            boot_context["listener"] = listener
            return True

        steps = [
            MeasuredBootStep(
                name="attestation_gate",
                state_field="attestation_verified",
                action=_phase_attestation,
                error_code="PA_BOOT_ATTESTATION_FAILED",
            ),
            MeasuredBootStep(
                name="weight_integrity_gate",
                state_field="weights_verified",
                action=_phase_weight_integrity,
                error_code="PA_BOOT_WEIGHT_VERIFY_FAILED",
            ),
            MeasuredBootStep(
                name="model_load",
                state_field="npu_model_loaded",
                action=_phase_model_load,
                error_code="PA_MODEL_LOAD_FAILED",
            ),
            MeasuredBootStep(
                name="rules_load",
                state_field="rules_loaded",
                action=_phase_rules_load,
                error_code="PA_RULE_CONFIG_LOAD_FAILED",
            ),
            MeasuredBootStep(
                name="listener_start",
                state_field="listener_started",
                action=_phase_listener_start,
                error_code="PA_LISTENER_START_FAILED",
            ),
        ]
        boot_state = run_measured_boot(
            str(self._config_path),
            steps=steps,
            policy=MeasuredBootPolicy(
                max_attempts=MEASURED_BOOT_MAX_ATTEMPTS,
                retry_delay_s=MEASURED_BOOT_RETRY_DELAY_S,
            ),
        )

        context_error_code = boot_context.get("error_code")
        context_error_message = boot_context.get("error_message")
        if isinstance(context_error_code, str) and context_error_code:
            boot_state.error_code = context_error_code
        if isinstance(context_error_message, str) and context_error_message:
            boot_state.error_message = context_error_message

        self._last_boot_state = boot_state
        if not boot_state.ready:
            _cleanup_boot_context()
            self._measured_boot_hard_locked = boot_state.hard_locked
            self._last_failure = build_failure_fingerprint(
                stage="measured_boot",
                code=boot_state.error_code or "PA_BOOT_FAILED",
                message=(
                    f"{boot_state.error_message or 'Measured boot failed.'} "
                    f"attempt={boot_state.attempt_count}/{MEASURED_BOOT_MAX_ATTEMPTS} "
                    f"hard_lock={str(boot_state.hard_locked).lower()}"
                ),
            )
            logger.error("Policy Agent measured boot failed: %s", self._last_failure)
            return False

        listener = boot_context.get("listener")
        inference = boot_context.get("inference")
        adjudicator = boot_context.get("adjudicator")
        jwt_minter = boot_context.get("jwt_minter")
        if listener is None or not hasattr(listener, "serve_forever"):
            self._last_failure = build_failure_fingerprint(
                stage="measured_boot",
                code="PA_BOOT_LISTENER_MISSING",
                message="Measured boot completed without listener instance.",
            )
            logger.error("Policy Agent measured boot invalid state: %s", self._last_failure)
            return False
        if inference is None or not hasattr(inference, "unload"):
            self._last_failure = build_failure_fingerprint(
                stage="measured_boot",
                code="PA_BOOT_INFERENCE_MISSING",
                message="Measured boot completed without inference instance.",
            )
            logger.error("Policy Agent measured boot invalid state: %s", self._last_failure)
            return False
        if adjudicator is None or not hasattr(adjudicator, "adjudicate_car"):
            self._last_failure = build_failure_fingerprint(
                stage="measured_boot",
                code="PA_BOOT_ADJUDICATOR_MISSING",
                message="Measured boot completed without adjudicator instance.",
            )
            logger.error("Policy Agent measured boot invalid state: %s", self._last_failure)
            return False
        if jwt_minter is None or not hasattr(jwt_minter, "mint"):
            self._last_failure = build_failure_fingerprint(
                stage="measured_boot",
                code="PA_BOOT_JWT_MINTER_MISSING",
                message="Measured boot completed without JWT minter instance.",
            )
            logger.error("Policy Agent measured boot invalid state: %s", self._last_failure)
            return False

        self._stop_event.clear()
        loop_thread = threading.Thread(
            target=listener.serve_forever,
            args=(self._stop_event,),
            name="policy-agent-ipc-loop",
            daemon=True,
        )
        loop_thread.start()

        self._inference = inference
        self._adjudicator = adjudicator
        self._listener = listener
        self._jwt_minter = jwt_minter
        self._loop_thread = loop_thread
        self._running = True
        self._measured_boot_hard_locked = False
        self._last_failure = None
        logger.info("Policy Agent entrypoint started with measured-boot ordering.")
        return True

    def stop(self) -> None:
        """Graceful shutdown for Policy Agent entrypoint."""
        self._stop_event.set()

        if self._listener is not None:
            self._listener.stop()

        if self._loop_thread is not None and self._loop_thread.is_alive():
            self._loop_thread.join(timeout=2.0)
            if self._loop_thread.is_alive():
                logger.warning(
                    "Policy Agent IPC loop did not exit before timeout."
                )

        if self._inference is not None:
            self._inference.unload()

        self._loop_thread = None
        self._listener = None
        self._adjudicator = None
        self._jwt_minter = None
        self._inference = None
        self._running = False
        logger.info("Policy Agent entrypoint stopped.")

    def install_signal_handlers(
        self, signals: Iterable[int] | None = None
    ) -> tuple[int, ...]:
        """Arm SIGTERM/SIGINT → graceful :meth:`stop` for this PA (AUDIT-13 / #812).

        Gives the Policy Agent its OWN disposability drain, independent of the
        launcher: on a termination signal the listener is stopped, the IPC loop
        joined, and the model unloaded via :meth:`stop`. Opt-in and fail-safe —
        see :func:`shared.service_signals.install_graceful_shutdown`. In the
        default host topology the launcher owns process signal disposition (and
        already drains the PA via ``stop()``); this method is for the
        process-leader topology where the PA runs as its own process (the VM
        guest). Returns the signals actually armed (``()`` if none — e.g. called
        off the main thread).
        """
        return install_graceful_shutdown(
            self.stop, service_name="PolicyAgent", signals=signals
        )

    def _load_entrypoint_config(self) -> PolicyAgentEntrypointConfig:
        config_path = self._resolve_config_path()

        with open(config_path, "rb") as file_obj:
            config_data = tomllib.load(file_obj)

        service_root = config_path.parents[1]
        repo_root = service_root.parents[1]

        self._validate_config_data(config_data, config_path)

        security = config_data.get("security", {})
        inference = config_data.get("inference", {})
        jwt = config_data.get("jwt", {})
        ipc = config_data.get("ipc", {})

        model_dir = self._resolve_path(repo_root, service_root, str(inference.get("model_dir", "")))
        manifest = str(inference.get("weight_manifest", "")).strip()
        manifest_path = self._resolve_path(repo_root, service_root, manifest) if manifest else None
        model_bin_path = model_dir / "openvino_model.bin"

        draft_model_raw = str(inference.get("draft_model_dir", "")).strip()
        draft_model_dir = (
            self._resolve_path(repo_root, service_root, draft_model_raw)
            if draft_model_raw
            else Path(DRAFT_MODEL_OV_PATH)
        )
        speculative_decoding_enabled = inference.get(
            "speculative_decoding_enabled", SPECULATIVE_DECODING_ENABLED
        )
        if not isinstance(speculative_decoding_enabled, bool):
            speculative_decoding_enabled = bool(SPECULATIVE_DECODING_ENABLED)

        dev_mode = bool(security.get("dev_mode", False))
        if self._dev_mode_override is not None:
            dev_mode = self._dev_mode_override

        # require_signed_manifest defaults False — capability built, off until LA flips.
        require_signed_manifest = bool(security.get("require_signed_manifest", False))
        # require_signed_draft_manifest (FUT-05 / #917) — the STANDALONE-path draft's
        # signature posture, defaults False (dormant = digest-only). Independent of
        # the 14B flag (the draft is non-authoritative).
        require_signed_draft_manifest = bool(
            security.get("require_signed_draft_manifest", False)
        )

        # Tamper-evident audit stream (Sprint 13 / Domain 7).  Default path lives
        # under the service data dir so the live PA always has a durable forensic
        # record; override via [security].audit_log_path.  ACTIVE in dev + prod.
        audit_log_raw = str(security.get("audit_log_path", "")).strip()
        if audit_log_raw:
            audit_log_path = self._resolve_path(repo_root, service_root, audit_log_raw)
        else:
            audit_log_path = service_root / "data" / "audit" / "adjudication_audit.jsonl"
        audit_hmac_key_id = str(security.get("audit_hmac_key_id", "dev-stub")).strip() or "dev-stub"

        # Segmented retention knobs (ISS-607 / ADR-029).  Defaults keep the
        # active file (and in-RAM working set) bounded while retaining the full
        # history on disk; the archive ceilings default OFF (keep everything).
        audit_max_active_bytes = int(
            security.get("audit_max_active_bytes", DEFAULT_MAX_ACTIVE_BYTES)
        )
        audit_max_active_records = int(
            security.get("audit_max_active_records", DEFAULT_MAX_ACTIVE_RECORDS)
        )
        audit_archive_max_bytes = self._optional_positive_int(
            security.get("audit_archive_max_bytes")
        )
        audit_archive_max_age_days = self._optional_positive_int(
            security.get("audit_archive_max_age_days")
        )

        cert_path = (
            self._resolve_path(repo_root, service_root, str(ipc.get("mtls_cert_path", "")))
            if not dev_mode
            else None
        )
        key_path = (
            self._resolve_path(repo_root, service_root, str(ipc.get("mtls_key_path", "")))
            if not dev_mode
            else None
        )
        ca_path = (
            self._resolve_path(repo_root, service_root, str(ipc.get("ca_cert_path", "")))
            if not dev_mode
            else None
        )

        vsock_config = VsockConfig(
            address=VsockAddress(
                cid=int(ipc.get("vsock_cid", 2)),
                port=int(ipc.get("vsock_port", 5000)),
            ),
            mtls_cert_path=(str(cert_path) if cert_path is not None else ""),
            mtls_key_path=(str(key_path) if key_path is not None else ""),
            ca_cert_path=(str(ca_path) if ca_path is not None else ""),
            timeout_ms=int(ipc.get("timeout_ms", 5000)),
            max_message_bytes=int(ipc.get("max_message_bytes", 65536)),
        )

        jwt_tpm_key_name_raw = str(jwt.get("tpm_key_name", "")).strip()
        jwt_tpm_key_name = jwt_tpm_key_name_raw or None
        jwt_ca_path_raw = str(jwt.get("ca_cert_path", "")).strip()
        jwt_ca_cert_path = (
            self._resolve_path(repo_root, service_root, jwt_ca_path_raw)
            if jwt_ca_path_raw
            else None
        )

        return PolicyAgentEntrypointConfig(
            config_dir=service_root / "config",
            model_dir=model_dir,
            manifest_path=manifest_path,
            model_bin_path=model_bin_path,
            device=str(inference.get("device", "GPU")),
            draft_model_dir=draft_model_dir,
            speculative_decoding_enabled=speculative_decoding_enabled,
            dev_mode=dev_mode,
            jwt_tpm_key_name=jwt_tpm_key_name,
            jwt_ca_cert_path=jwt_ca_cert_path,
            jwt_issuer=str(jwt.get("issuer", "policy_agent")),
            jwt_validity_seconds=int(jwt.get("validity_seconds", 5)),
            vsock_config=vsock_config,
            deployment_mode=self._deployment_mode,
            require_signed_manifest=require_signed_manifest,
            require_signed_draft_manifest=require_signed_draft_manifest,
            audit_log_path=audit_log_path,
            audit_hmac_key_id=audit_hmac_key_id,
            audit_max_active_bytes=audit_max_active_bytes,
            audit_max_active_records=audit_max_active_records,
            audit_archive_max_bytes=audit_archive_max_bytes,
            audit_archive_max_age_days=audit_archive_max_age_days,
        )

    def _resolve_config_path(self) -> Path:
        service_root = resolve_service_root(__file__, 'services.policy_agent')
        return resolve_service_config_path(
            service_root,
            deployment_mode=self._deployment_mode,
            explicit_config_path=self._config_path,
        )

    def _validate_config_data(self, config_data: dict[str, object], config_path: Path) -> None:
        runtime = config_validation.require_section_dict(config_data, "runtime", code="PA_CFG_RUNTIME_SECTION_MISSING")
        runtime_mode_raw = config_validation.require_non_empty_str(
            runtime,
            "deployment_mode",
            code="PA_CFG_RUNTIME_MODE_MISSING",
        )
        runtime_mode = resolve_deployment_mode(runtime_mode_raw)
        if runtime_mode != self._deployment_mode:
            raise ConfigResolutionError(
                code="CFG_RUNTIME_MODE_MISMATCH",
                message=(
                    f"Runtime mode mismatch for {config_path.name}: "
                    f"expected '{self._deployment_mode.value}', got '{runtime_mode.value}'."
                ),
            )

        inference = config_validation.require_section_dict(config_data, "inference", code="PA_CFG_INFERENCE_SECTION_MISSING")
        device = config_validation.require_non_empty_str(inference, "device", code="PA_CFG_INFERENCE_DEVICE_MISSING")
        if device.upper() != "GPU":
            raise ConfigResolutionError(
                code="PA_CFG_DEVICE_INVALID",
                message=f"Policy Agent device must be GPU per ADR-010, got '{device}'.",
            )
        config_validation.require_non_empty_str(inference, "model_dir", code="PA_CFG_MODEL_DIR_MISSING")

        spec_decode = inference.get("speculative_decoding_enabled")
        if spec_decode is not None and not isinstance(spec_decode, bool):
            raise ConfigResolutionError(
                code="PA_CFG_SPECULATIVE_DECODING_INVALID",
                message="'inference.speculative_decoding_enabled' must be a boolean.",
            )

        draft_dir = inference.get("draft_model_dir")
        if draft_dir is not None:
            if not isinstance(draft_dir, str) or not draft_dir.strip():
                raise ConfigResolutionError(
                    code="PA_CFG_DRAFT_MODEL_DIR_INVALID",
                    message="'inference.draft_model_dir' must be a non-empty string when specified.",
                )

        security = config_validation.require_section_dict(config_data, "security", code="PA_CFG_SECURITY_SECTION_MISSING")
        dev_mode = config_validation.require_bool(security, "dev_mode", code="PA_CFG_DEV_MODE_INVALID")

        if not dev_mode:
            weight_manifest = inference.get("weight_manifest")
            if not isinstance(weight_manifest, str) or not weight_manifest.strip():
                raise ConfigResolutionError(
                    code="PA_CFG_WEIGHT_MANIFEST_MISSING",
                    message="'inference.weight_manifest' is required when dev_mode=false.",
                )

        jwt = config_validation.require_section_dict(config_data, "jwt", code="PA_CFG_JWT_SECTION_MISSING")
        config_validation.require_non_empty_str(jwt, "issuer", code="PA_CFG_JWT_ISSUER_MISSING")
        config_validation.require_int_range(
            jwt,
            "validity_seconds",
            minimum=1,
            maximum=300,
            code="PA_CFG_JWT_VALIDITY_INVALID",
        )
        if not dev_mode:
            tpm_key_name = jwt.get("tpm_key_name")
            if not isinstance(tpm_key_name, str) or not tpm_key_name.strip():
                raise ConfigResolutionError(
                    code="PA_CFG_JWT_TPM_KEY_MISSING",
                    message="'jwt.tpm_key_name' is required when dev_mode=false.",
                )
            ca_cert_path = jwt.get("ca_cert_path")
            if not isinstance(ca_cert_path, str) or not ca_cert_path.strip():
                raise ConfigResolutionError(
                    code="PA_CFG_JWT_CA_PATH_MISSING",
                    message="'jwt.ca_cert_path' is required when dev_mode=false.",
                )

        ipc = config_validation.require_section_dict(config_data, "ipc", code="PA_CFG_IPC_SECTION_MISSING")
        config_validation.require_int_range(ipc, "vsock_cid", minimum=0, maximum=2**32 - 1, code="PA_CFG_VSOCK_CID_INVALID")
        config_validation.require_int_range(ipc, "vsock_port", minimum=1, maximum=65535, code="PA_CFG_VSOCK_PORT_INVALID")
        config_validation.require_int_range(ipc, "timeout_ms", minimum=1, maximum=120000, code="PA_CFG_TIMEOUT_INVALID")
        config_validation.require_int_range(
            ipc,
            "max_message_bytes",
            minimum=1024,
            maximum=1_048_576,
            code="PA_CFG_MAX_MESSAGE_BYTES_INVALID",
        )

    def _validate_security_material(
        self,
        *,
        model_bin_path: Path,
        manifest_path: Path | None,
        jwt_tpm_key_name: str | None,
        jwt_ca_cert_path: Path | None,
        dev_mode: bool,
        require_signed_manifest: bool = False,
    ) -> None:
        if dev_mode:
            return

        if manifest_path is None:
            raise ConfigResolutionError(
                code="PA_CFG_KGM_PATH_MISSING",
                message="Known-Good Manifest path is required when dev_mode=false.",
            )
        if not manifest_path.exists():
            raise ConfigResolutionError(
                code="PA_CFG_KGM_PATH_NOT_FOUND",
                message=f"Known-Good Manifest file not found: {manifest_path}",
            )

        digests = load_manifest_verified(manifest_path, require_signed=require_signed_manifest)
        if digests is None:
            raise ConfigResolutionError(
                code="PA_CFG_KGM_INVALID",
                message=f"Known-Good Manifest is malformed or signature invalid: {manifest_path}",
            )

        expected_digest = digests.get(model_bin_path.name)
        if expected_digest is None:
            raise ConfigResolutionError(
                code="PA_CFG_KGM_MODEL_DIGEST_MISSING",
                message=(
                    f"Known-Good Manifest missing digest for '{model_bin_path.name}'."
                ),
            )
        if re.fullmatch(r"[0-9a-f]{64}", expected_digest) is None:
            raise ConfigResolutionError(
                code="PA_CFG_KGM_DIGEST_INVALID",
                message=(
                    f"Known-Good Manifest digest for '{model_bin_path.name}' is invalid."
                ),
            )

        if not jwt_tpm_key_name:
            raise ConfigResolutionError(
                code="PA_CFG_JWT_TPM_KEY_MISSING",
                message="'jwt.tpm_key_name' is required when dev_mode=false.",
            )
        try:
            key_present = tpm_signer.key_exists(jwt_tpm_key_name)
        except (tpm_signer.TpmUnavailable, tpm_signer.TpmSigningError) as exc:
            raise ConfigResolutionError(
                code="PA_CFG_JWT_TPM_UNAVAILABLE",
                message=(
                    f"TPM unavailable for JWT signing key '{jwt_tpm_key_name}': {exc}. "
                    "Production JWT signing requires a provisioned TPM key."
                ),
            ) from exc
        if not key_present:
            raise ConfigResolutionError(
                code="PA_CFG_JWT_TPM_KEY_NOT_PROVISIONED",
                message=(
                    f"TPM signing key '{jwt_tpm_key_name}' is not provisioned. Run the "
                    "provisioning ceremony: python -m shared.security.provision_signing_key"
                ),
            )

        if jwt_ca_cert_path is None:
            raise ConfigResolutionError(
                code="PA_CFG_JWT_CA_PATH_MISSING",
                message="'jwt.ca_cert_path' is required when dev_mode=false.",
            )
        if not jwt_ca_cert_path.exists():
            raise ConfigResolutionError(
                code="PA_CFG_JWT_CA_PATH_NOT_FOUND",
                message=f"JWT CA/public key not found: {jwt_ca_cert_path}",
            )

        if AgenticJWTValidator.from_public_key_file(jwt_ca_cert_path) is None:
            raise ConfigResolutionError(
                code="PA_CFG_JWT_CA_INVALID",
                message=(
                    "JWT CA/public key is invalid or unreadable: "
                    f"{jwt_ca_cert_path}"
                ),
            )

    def _verify_weight_integrity_gate(self, resolved: PolicyAgentEntrypointConfig) -> bool:
        if resolved.dev_mode:
            return True
        if resolved.manifest_path is None or not resolved.manifest_path.exists():
            return False
        digests = load_manifest_verified(
            resolved.manifest_path,
            require_signed=resolved.require_signed_manifest,
        )
        if digests is None:
            return False
        expected_digest = digests.get(resolved.model_bin_path.name)
        if expected_digest is None:
            return False
        return re.fullmatch(r"[0-9a-f]{64}", expected_digest) is not None

    @staticmethod
    def _resolve_path(repo_root: Path, service_root: Path, raw_path: str) -> Path:
        path = Path(raw_path)
        if path.is_absolute():
            return path
        candidate_repo = repo_root / path
        if candidate_repo.exists():
            return candidate_repo
        return service_root / path

    @staticmethod
    def _optional_positive_int(value: Any) -> int | None:
        """Parse an optional positive-int config value (retention ceilings).

        Returns ``None`` for an unset / empty / non-positive / unparseable value
        — the keep-everything default (ISS-607 / ADR-029).  A retention ceiling
        only takes effect when the operator sets a positive integer; anything
        else (including ``0`` or a typo) fails safe to "keep all" rather than
        silently enabling an aggressive prune.
        """
        if value is None:
            return None
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            return None
        return parsed if parsed > 0 else None

    @staticmethod
    def _build_audit_log(
        resolved: PolicyAgentEntrypointConfig,
    ) -> AuditLog | None:
        """Construct the tamper-evident adjudication audit sink (Sprint 13–14 / Domain 7).

        ACTIVE in both dev and production — the forensic record is value in both.

        Audit-path presence requirement — DELIBERATE DIVERGENCE between dev and
        production (LA ruling, 2026-06-05 / ADR-025 §2.8(a)):

          - Production (``dev_mode=False``) with ``audit_log_path=None``: the
            method **raises ``AuditProvisioningError`` and the Policy Agent
            REFUSES TO START**.  A PA authorizing actions in production with no
            audit trail, for any reason, is a governance hole — the audit-log
            path is a required configuration in production.
          - Dev / CI (``dev_mode=True``) with ``audit_log_path=None``: returns
            ``None`` (unchanged).  Audit logging is optional in dev/CI; the
            TPM ceremony has not been run and tests may not exercise the full
            pipeline.

        Signer selection and failure posture — DELIBERATE DIVERGENCE from
        ``_build_jwt_minter`` (ADR-025 §2.8(a)):

          - Production (``dev_mode=False``): ``TpmRecordSigner`` wrapping
            ``tpm_signer.sign/verify`` with the dedicated audit key
            ``AUDIT_TPM_KEY_NAME`` (``"BlarAI-Audit-Signing-Key-v1"``).  The
            private key never leaves the chip; forging a signature requires
            extracting a non-exportable CNG key.  If the TPM is unavailable or
            the key has not been provisioned, **this method raises
            ``AuditProvisioningError`` and the Policy Agent REFUSES TO START**
            — unlike ``_build_jwt_minter``, which degrades to None.  Rationale
            (LA ruling, ADR-025 §2.8(a)): a PA authorizing actions with NO
            audit trail in production is a governance hole; "tamper-evident
            audit stream live" is a #598 criterion; and this makes the audit
            path symmetric with the at-rest encryption fail-closed posture.
            The divergence from the JWT path is deliberate — never fall back to
            the forgeable stub in production.
          - Dev / CI (``dev_mode=True``): ``HmacSha256Signer`` with a
            deterministic per-path key derived from a local label.  The hash
            chain is still tamper-evident; only the signature is recomputable
            by an adversary with filesystem access (acceptable for dev/CI,
            where the TPM ceremony has not been run).

        This is a DROP-IN swap at ``_build_adjudicator`` — no other code changes.
        The dedicated audit key is separation-of-duties from the PA JWT key.
        """
        if not resolved.dev_mode:
            # Production path: audit_log_path=None is a governance hole —
            # refuse to start (LA ruling 2026-06-05, ADR-025 §2.8(a)).
            if resolved.audit_log_path is None:
                logger.error(
                    "No audit-log path configured — refusing to start in production "
                    "mode. Set audit_log_path in the Policy Agent configuration. "
                    "Production requires a tamper-evident audit trail (ADR-025 §2.8(a))."
                )
                raise AuditProvisioningError(
                    "No audit-log path configured. Production requires a tamper-evident "
                    "audit trail; a Policy Agent authorizing actions with no audit log "
                    "is a governance hole (ADR-025 §2.8(a)). Set audit_log_path in the "
                    "Policy Agent configuration before starting in production mode."
                )

        if resolved.dev_mode and resolved.audit_log_path is None:
            return None

        if not resolved.dev_mode:
            # Production: sign with the non-exportable TPM audit key (Sprint 14
            # / #605).  REFUSE TO START if the audit key is unprovisioned or
            # the TPM is unavailable — ADR-025 §2.8(a).  This diverges
            # deliberately from _build_jwt_minter (which degrades to None):
            # a PA authorizing actions with no audit trail is a governance hole.
            try:
                if not tpm_signer.key_exists(AUDIT_TPM_KEY_NAME):
                    logger.error(
                        "TPM audit signing key '%s' not provisioned — refusing to "
                        "start. Run the provisioning ceremony before starting in "
                        "production mode (ADR-025 §2.8(a)).",
                        AUDIT_TPM_KEY_NAME,
                    )
                    raise AuditProvisioningError(
                        f"TPM audit signing key '{AUDIT_TPM_KEY_NAME}' is not "
                        "provisioned. Run the provisioning ceremony before starting "
                        "in production mode. The Policy Agent cannot authorize "
                        "actions without a tamper-evident audit trail (ADR-025 §2.8(a))."
                    )
            except (tpm_signer.TpmUnavailable, tpm_signer.TpmSigningError) as exc:
                logger.error(
                    "TPM unavailable for audit signing key '%s': %s — refusing to "
                    "start (ADR-025 §2.8(a)).",
                    AUDIT_TPM_KEY_NAME,
                    exc,
                )
                raise AuditProvisioningError(
                    f"TPM unavailable for audit signing key '{AUDIT_TPM_KEY_NAME}': "
                    f"{exc}. The Policy Agent cannot authorize actions without a "
                    "tamper-evident audit trail (ADR-025 §2.8(a))."
                ) from exc
            signer = TpmRecordSigner(key_name=AUDIT_TPM_KEY_NAME)
            return AuditLog.from_path(
                resolved.audit_log_path,
                signer,
                **PolicyAgentService._audit_retention_kwargs(resolved),
            )

        # Dev / CI: derive a stable stub HMAC key from a fixed label + the log
        # path so different installs get different keys without storing a secret
        # in source.  This is intentionally recomputable — the hash-chain is
        # the tamper-evidence in dev; the non-forgeability property requires the
        # TPM path above.
        key_material = hashlib.sha256(
            b"BlarAI-audit-hmac-stub-v1::" + str(resolved.audit_log_path).encode("utf-8")
        ).digest()
        signer = HmacSha256Signer(key=key_material, key_id=resolved.audit_hmac_key_id)
        return AuditLog.from_path(
            resolved.audit_log_path,
            signer,
            **PolicyAgentService._audit_retention_kwargs(resolved),
        )

    @staticmethod
    def _audit_retention_kwargs(
        resolved: PolicyAgentEntrypointConfig,
    ) -> dict[str, Any]:
        """Map the resolved config's audit retention knobs to ``from_path`` kwargs.

        Single source of truth for both the production (TPM) and dev (HMAC) audit
        sink construction paths (ISS-607 / ADR-029) so they cannot drift.
        """
        return {
            "max_active_bytes": resolved.audit_max_active_bytes,
            "max_active_records": resolved.audit_max_active_records,
            "archive_max_bytes": resolved.audit_archive_max_bytes,
            "archive_max_age_days": resolved.audit_archive_max_age_days,
        }

    @staticmethod
    def _build_adjudicator(
        inference: PolicyGPUInference,
        rule_config: RuleEngineConfig,
        resolved: PolicyAgentEntrypointConfig,
    ) -> HybridAdjudicator:
        rate_limiter = RateLimiter(
            max_requests=rule_config.rate_limit.max_requests_per_window,
            window_seconds=rule_config.rate_limit.window_seconds,
        )
        # Wire the tamper-evident audit sink so EVERY adjudication the live PA
        # makes is persisted (Sprint 13 / Domain 7).  Without this, the rich
        # AdjudicationContext is built and discarded — the "built but wired into
        # nothing" anti-pattern the 2026-06-03 audit was about.
        audit_log = PolicyAgentService._build_audit_log(resolved)
        return HybridAdjudicator.from_config(
            npu_inference=inference,
            acl_matrix=rule_config.acl_matrix,
            rate_limiter=rate_limiter,
            resource_deny_list=rule_config.resource_deny_rules,
            manifest_path=(str(resolved.manifest_path) if resolved.manifest_path else None),
            model_bin_path=str(resolved.model_bin_path),
            audit_log=audit_log,
            # #571: thread the signed-manifest posture into the per-request
            # Stage-2 re-verify so it matches the signature-checked boot gate.
            require_signed_manifest=resolved.require_signed_manifest,
        )

    @staticmethod
    def _build_jwt_minter(
        resolved: PolicyAgentEntrypointConfig,
    ) -> AgenticJWTMinter | None:
        if not resolved.dev_mode:
            # Production: sign with the non-exportable TPM key (ADR-021). The
            # private key never leaves the chip; signing is fail-closed until the
            # provisioning ceremony has run on this host.
            key_name = resolved.jwt_tpm_key_name
            if not key_name:
                logger.error("JWT TPM key name not configured and dev_mode is disabled.")
                return None
            try:
                if not tpm_signer.key_exists(key_name):
                    logger.error(
                        "TPM signing key '%s' not provisioned — run "
                        "`python -m shared.security.provision_signing_key`.",
                        key_name,
                    )
                    return None
            except (tpm_signer.TpmUnavailable, tpm_signer.TpmSigningError) as exc:
                logger.error("TPM unavailable for JWT signing key '%s': %s", key_name, exc)
                return None
            return AgenticJWTMinter.from_tpm(
                key_name,
                issuer=resolved.jwt_issuer,
                validity_seconds=resolved.jwt_validity_seconds,
            )

        # Dev mode: ephemeral in-memory key material (never the TPM).
        private_key, _public_key = AgenticJWTMinter.generate_key_pair()
        logger.warning("Using ephemeral dev JWT key material.")
        return AgenticJWTMinter(
            private_key,
            issuer=resolved.jwt_issuer,
            validity_seconds=resolved.jwt_validity_seconds,
        )

    def _handle_adjudication(
        self,
        car_json: str,
        request_id: str,
    ) -> AdjudicationResponse:
        if self._adjudicator is None or self._jwt_minter is None:
            return AdjudicationResponse(
                decision="DENY",
                request_id=request_id,
                error="POLICY_AGENT_NOT_READY",
            )

        try:
            car = CanonicalActionRepresentation.model_validate_json(car_json)
        except Exception as exc:  # noqa: BLE001
            return AdjudicationResponse(
                decision="DENY",
                request_id=request_id,
                error=f"MALFORMED_CAR: {exc}",
            )

        context = self._adjudicator.adjudicate_car(car)
        decision = context.decision_artifact.decision.value
        car_hash = context.decision_artifact.car_hash

        if decision == "ALLOW":
            minted = self._jwt_minter.mint(context.decision_artifact)
            if not minted.success:
                return AdjudicationResponse(
                    decision="DENY",
                    request_id=request_id,
                    car_hash=car_hash,
                    error=minted.error or "JWT_MINT_FAILED",
                )
            return AdjudicationResponse(
                decision="ALLOW",
                request_id=request_id,
                car_hash=car_hash,
                jwt_token=minted.token,
            )

        return AdjudicationResponse(
            decision=decision,
            request_id=request_id,
            car_hash=car_hash,
            error=context.npu_result.error or "",
        )
