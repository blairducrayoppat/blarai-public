"""
Hybrid Adjudicator — Policy Agent
====================================
USE-CASE-001, P1.4: Combines deterministic rule engine + GPU probabilistic
classifier into a single adjudication decision.

Decision Matrix:
  | Rule Engine | GPU Classifier | Final Decision |
  |-------------|----------------|----------------|
  | DENY        | (any)          | DENY           |
  | ALLOW       | ALLOW (≥0.75)  | ALLOW          |
  | ALLOW       | ESCALATE       | ESCALATE       |
  | ALLOW       | DENY           | DENY           |
  | ALLOW       | < threshold    | ESCALATE       |

After adjudication, the decision is minted into an Agentic JWT.

``HybridAdjudicator`` is the top-level orchestrator that wires the full
pipeline: rule engine → event-triggered weight integrity re-verification →
GPU inference → decision matrix → ``AdjudicationContext``.

``adjudicate()`` remains a pure function implementing the inner decision
matrix (backward compatible with P1.1 integration tests).

Event-triggered runtime re-verification (Use Cases_FINAL.md, Layer 2):
  Before every GPU inference call, the HybridAdjudicator re-computes the
  SHA-256 hash of the model weight file and compares it against the
  Known-Good Manifest. If divergence is detected, the adjudicator halts
  inference and returns DENY (Fail-Closed). This ensures no Agentic JWT
  is ever minted against potentially corrupted weights.

Security:
  - Deterministic DENY is non-appealable (rule engine is authoritative).
  - Fail-Closed: any pipeline error results in DENY.
  - All decisions are logged with full CAR hash for audit.
  - Event-triggered integrity re-verification before every GPU inference.
  - Short-circuit: rule engine DENY skips integrity + GPU entirely.
"""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

from shared.models.weight_integrity import (
    IntegrityCheckResult,
    verify_weight_integrity,
)
from shared.schemas.car import (
    AdjudicationDecision,
    CanonicalActionRepresentation,
    DecisionArtifact,
)
from shared.security.audit_log import AuditLog, AuditSinkError
from services.policy_agent.src.config_loader import ResourceDenyRule
from services.policy_agent.src.constants import (
    ESCALATION_CONFIDENCE_RANGE,
    PROBABILISTIC_CONFIDENCE_THRESHOLD,
)
from services.policy_agent.src.gpu_inference import (
    GPUClassificationResult,
    PolicyGPUInference,
)
from services.policy_agent.src.rule_engine import (
    RateLimiter,
    RuleEngineResult,
    run_rule_engine,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Adjudication Context — rich audit record
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AdjudicationLatency:
    """Per-adjudication timing breakdown in milliseconds."""

    rule_engine_ms: float = 0.0
    """Time spent in the deterministic rule engine."""

    integrity_ms: float = 0.0
    """Time spent in event-triggered weight integrity re-verification.
    0.0 if skipped (no manifest, rule engine DENY, or model not loaded)."""

    npu_inference_ms: float = 0.0
    """Time spent in GPU classify (includes model-level latency).
    0.0 if skipped (rule engine DENY or integrity failure).
    NOTE: field name retained as npu_inference_ms for schema compatibility."""

    total_ms: float = 0.0
    """Wall-clock time for the entire adjudication pipeline."""


@dataclass(frozen=True)
class AdjudicationContext:
    """Complete audit record of a single adjudication cycle.

    Produced by ``HybridAdjudicator.adjudicate_car()``.
    Contains everything needed for audit logging, JWT minting,
    and forensic analysis.
    """

    adjudication_id: str
    """Unique identifier for this adjudication (UUID4)."""

    decision_artifact: DecisionArtifact
    """The DecisionArtifact ready for JWT minting."""

    rule_engine_result: RuleEngineResult
    """Deterministic rule engine output (may be short-circuited)."""

    npu_result: GPUClassificationResult
    """GPU classification output (DENY/0.0 if pipeline short-circuited).
    NOTE: field name retained as npu_result for schema compatibility."""

    runtime_integrity: IntegrityCheckResult | None
    """Event-triggered weight integrity check result.
    None if not performed (no manifest, rule engine DENY, or model not loaded)."""

    latency: AdjudicationLatency
    """Per-stage latency breakdown."""

    timestamp: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    """UTC timestamp of adjudication completion."""

    @property
    def decision(self) -> AdjudicationDecision:
        """Convenience: the final adjudication decision."""
        return self.decision_artifact.decision

    @property
    def passed(self) -> bool:
        """True if the final decision is ALLOW."""
        return self.decision == AdjudicationDecision.ALLOW

    @property
    def integrity_verified(self) -> bool:
        """True if runtime integrity was checked and passed."""
        if self.runtime_integrity is None:
            return False
        return self.runtime_integrity.verified


# ---------------------------------------------------------------------------
# HybridAdjudicator — stateful pipeline orchestrator
# ---------------------------------------------------------------------------


class HybridAdjudicator:
    """Orchestrates the full hybrid adjudication pipeline.

    Pipeline: rule engine → integrity re-verify → GPU → decision matrix.

    Lifecycle:
      1. Construct with ``__init__`` or ``from_config()``.
      2. Call ``adjudicate_car(car)`` for each incoming request.
      3. Receive an ``AdjudicationContext`` with the complete audit trail.

    Short-circuit behavior:
      - Rule engine DENY → skip integrity + GPU entirely (saves latency).
      - Integrity failure → skip GPU, return DENY.
      - Model not loaded → Fail-Closed DENY (no integrity check either).
    """

    def __init__(
        self,
        npu_inference: PolicyGPUInference,
        acl_matrix: dict[str, list[str]] | None = None,
        *,
        rate_limiter: RateLimiter | None = None,
        resource_deny_list: list[ResourceDenyRule] | None = None,
        manifest_path: str | None = None,
        model_bin_path: str | None = None,
        audit_log: AuditLog | None = None,
    ) -> None:
        """Initialize the HybridAdjudicator.

        Args:
            npu_inference: Pre-configured PolicyGPUInference instance.
                NOTE: param name retained as npu_inference for API compatibility.
            acl_matrix: Source-agent → destination permission matrix.
            rate_limiter: Active RateLimiter (optional).
            resource_deny_list: Resource deny rules (optional).
            manifest_path: Path to KGM for event-triggered re-verification.
                If None, runtime integrity re-verification is skipped.
            model_bin_path: Path to the model .bin for re-verification.
                Required if manifest_path is provided.
            audit_log: Tamper-evident audit sink (optional).  When provided,
                every AdjudicationContext is persisted before being returned.
                AuditSinkError propagates to the caller — write failures are
                explicit (Fail-Closed: never silently dropped).
        """
        self._npu = npu_inference
        self._acl_matrix = acl_matrix
        self._rate_limiter = rate_limiter
        self._resource_deny_list = resource_deny_list
        self._manifest_path = manifest_path
        self._model_bin_path = model_bin_path
        self._audit_log = audit_log
        self._adjudication_count: int = 0

    @classmethod
    def from_config(
        cls,
        npu_inference: PolicyGPUInference,
        acl_matrix: dict[str, list[str]] | None = None,
        *,
        rate_limiter: RateLimiter | None = None,
        resource_deny_list: list[ResourceDenyRule] | None = None,
        manifest_path: str | None = None,
        model_bin_path: str | None = None,
        audit_log: AuditLog | None = None,
    ) -> "HybridAdjudicator":
        """Factory method: construct from individual config objects.

        Identical to ``__init__`` — provided for API clarity when composing
        at boot time.
        """
        return cls(
            npu_inference=npu_inference,
            acl_matrix=acl_matrix,
            rate_limiter=rate_limiter,
            resource_deny_list=resource_deny_list,
            manifest_path=manifest_path,
            model_bin_path=model_bin_path,
            audit_log=audit_log,
        )

    # -- Properties ---------------------------------------------------------

    @property
    def adjudication_count(self) -> int:
        """Total number of adjudications performed."""
        return self._adjudication_count

    @property
    def npu_loaded(self) -> bool:
        """True if the inference model is compiled and ready."""
        return self._npu.loaded

    @property
    def has_integrity_checking(self) -> bool:
        """True if runtime integrity re-verification is configured."""
        return (
            self._manifest_path is not None
            and self._model_bin_path is not None
        )

    @property
    def has_audit_log(self) -> bool:
        """True if a tamper-evident audit sink is wired in."""
        return self._audit_log is not None

    # -- Internal helpers ---------------------------------------------------

    def _persist_context_with_car(
        self,
        ctx: "AdjudicationContext",
        car: CanonicalActionRepresentation,
    ) -> None:
        """Persist ctx + the originating CAR to the audit sink.

        Separated from adjudicate_car to allow clean testing of the
        persistence path independent of the full pipeline.

        Raises:
            AuditSinkError: propagated directly (Fail-Closed).
        """
        if self._audit_log is None:
            return
        self._audit_log.append(
            adjudication_id=ctx.adjudication_id,
            decision=ctx.decision.value,
            car_hash=ctx.decision_artifact.car_hash,
            source_agent=car.source_agent,
            destination_service=car.destination_service,
            verb=car.verb.value,
            resource=car.resource,
            sensitivity=car.sensitivity.value,
            rule_engine_passed=ctx.rule_engine_result.passed,
            confidence=ctx.decision_artifact.confidence,
        )

    # -- Pipeline -----------------------------------------------------------

    def adjudicate_car(
        self,
        car: CanonicalActionRepresentation,
    ) -> AdjudicationContext:
        """Execute the full hybrid adjudication pipeline on a CAR.

        Pipeline stages (with short-circuit):
          1. Deterministic rule engine (STRUCTURAL → SENSITIVITY → ACL → RATE → RESOURCE).
          2. Event-triggered weight integrity re-verification (if configured + rules passed).
          3. GPU probabilistic classification.
          4. Decision matrix → DecisionArtifact.

        Args:
            car: The CAR to adjudicate.

        Returns:
            AdjudicationContext with complete audit trail.
        """
        t_start = time.perf_counter()
        adjudication_id = str(uuid.uuid4())

        # -- Stage 1: Deterministic rule engine --
        t_rules_start = time.perf_counter()
        rule_result = run_rule_engine(
            car,
            acl_matrix=self._acl_matrix,
            rate_limiter=self._rate_limiter,
            resource_deny_list=self._resource_deny_list,
        )
        t_rules_end = time.perf_counter()
        rule_engine_ms = (t_rules_end - t_rules_start) * 1000.0

        # Short-circuit: rule engine DENY → skip integrity + GPU.
        if not rule_result.passed:
            npu_result = GPUClassificationResult(
                label="DENY",
                confidence=0.0,
                latency_ms=0.0,
                error="Skipped — deterministic rule engine DENY.",
            )
            decision_artifact = adjudicate(car, rule_result, npu_result)
            t_end = time.perf_counter()
            total_ms = (t_end - t_start) * 1000.0

            self._adjudication_count += 1
            logger.info(
                "Adjudication %s: DENY (rule engine) in %.2fms [%s]",
                adjudication_id,
                total_ms,
                rule_result.blocking_rule,
            )
            ctx = AdjudicationContext(
                adjudication_id=adjudication_id,
                decision_artifact=decision_artifact,
                rule_engine_result=rule_result,
                npu_result=npu_result,
                runtime_integrity=None,
                latency=AdjudicationLatency(
                    rule_engine_ms=rule_engine_ms,
                    total_ms=total_ms,
                ),
            )
            self._persist_context_with_car(ctx, car)
            return ctx

        # -- Stage 2: Event-triggered weight integrity re-verification --
        integrity_result: IntegrityCheckResult | None = None
        integrity_ms = 0.0

        if self.has_integrity_checking:
            t_integrity_start = time.perf_counter()
            assert self._manifest_path is not None  # guarded by has_integrity_checking
            assert self._model_bin_path is not None
            integrity_result = verify_weight_integrity(
                model_path=self._model_bin_path,
                manifest_path=self._manifest_path,
            )
            t_integrity_end = time.perf_counter()
            integrity_ms = (t_integrity_end - t_integrity_start) * 1000.0

            if not integrity_result.verified:
                # Weight corruption detected — Fail-Closed DENY.
                logger.error(
                    "Adjudication %s: runtime integrity FAILURE — %s",
                    adjudication_id,
                    integrity_result.error,
                )
                npu_result = GPUClassificationResult(
                    label="DENY",
                    confidence=0.0,
                    latency_ms=0.0,
                    error=(
                        "Runtime weight integrity failure — Fail-Closed: "
                        f"{integrity_result.error}"
                    ),
                )
                decision_artifact = adjudicate(car, rule_result, npu_result)
                t_end = time.perf_counter()
                total_ms = (t_end - t_start) * 1000.0

                self._adjudication_count += 1
                ctx = AdjudicationContext(
                    adjudication_id=adjudication_id,
                    decision_artifact=decision_artifact,
                    rule_engine_result=rule_result,
                    npu_result=npu_result,
                    runtime_integrity=integrity_result,
                    latency=AdjudicationLatency(
                        rule_engine_ms=rule_engine_ms,
                        integrity_ms=integrity_ms,
                        total_ms=total_ms,
                    ),
                )
                self._persist_context_with_car(ctx, car)
                return ctx
            logger.debug(
                "Adjudication %s: runtime integrity verified (%.2fms)",
                adjudication_id,
                integrity_ms,
            )

        # -- Stage 3: GPU probabilistic classification --
        t_npu_start = time.perf_counter()
        npu_result = self._npu.classify_car(car)
        t_npu_end = time.perf_counter()
        npu_inference_ms = (t_npu_end - t_npu_start) * 1000.0

        # -- Stage 4: Decision matrix --
        decision_artifact = adjudicate(car, rule_result, npu_result)

        t_end = time.perf_counter()
        total_ms = (t_end - t_start) * 1000.0

        self._adjudication_count += 1
        logger.info(
            "Adjudication %s: %s (conf=%.3f) in %.2fms "
            "[rules=%.2fms, integrity=%.2fms, npu=%.2fms]",
            adjudication_id,
            decision_artifact.decision.value,
            npu_result.confidence,
            total_ms,
            rule_engine_ms,
            integrity_ms,
            npu_inference_ms,
        )
        ctx = AdjudicationContext(
            adjudication_id=adjudication_id,
            decision_artifact=decision_artifact,
            rule_engine_result=rule_result,
            npu_result=npu_result,
            runtime_integrity=integrity_result,
            latency=AdjudicationLatency(
                rule_engine_ms=rule_engine_ms,
                integrity_ms=integrity_ms,
                npu_inference_ms=npu_inference_ms,
                total_ms=total_ms,
            ),
        )
        self._persist_context_with_car(ctx, car)
        return ctx


# ---------------------------------------------------------------------------
# Pure decision matrix function (backward compatible)
# ---------------------------------------------------------------------------


def adjudicate(
    car: CanonicalActionRepresentation,
    rule_result: RuleEngineResult,
    npu_result: GPUClassificationResult,
) -> DecisionArtifact:
    """Combine deterministic and probabilistic results into a final decision.

    This is the inner decision matrix — a pure function with no side effects.
    Preserved from P1.1 for backward compatibility. The ``HybridAdjudicator``
    class calls this after orchestrating the full pipeline.

    Args:
        car: The CAR being adjudicated.
        rule_result: Output from the deterministic rule engine.
        npu_result: Output from the GPU probabilistic classifier.
            NOTE: param name retained as npu_result for API compatibility.

    Returns:
        DecisionArtifact ready for JWT minting.
    """
    car_hash = car.canonical_hash()

    # Rule engine DENY is authoritative — no appeal.
    if not rule_result.passed:
        return DecisionArtifact(
            car_hash=car_hash,
            decision=AdjudicationDecision.DENY,
            request_id=car.request_id,
            deterministic_pass=False,
            probabilistic_pass=False,
            confidence=npu_result.confidence,
        )

    # Rule engine passed — evaluate NPU result.
    if npu_result.error is not None:
        # Inference error — Fail-Closed DENY.
        return DecisionArtifact(
            car_hash=car_hash,
            decision=AdjudicationDecision.DENY,
            request_id=car.request_id,
            deterministic_pass=True,
            probabilistic_pass=False,
            confidence=0.0,
        )

    if npu_result.passed:
        return DecisionArtifact(
            car_hash=car_hash,
            decision=AdjudicationDecision.ALLOW,
            request_id=car.request_id,
            deterministic_pass=True,
            probabilistic_pass=True,
            confidence=npu_result.confidence,
        )

    # Check ESCALATE range
    low, high = ESCALATION_CONFIDENCE_RANGE
    if npu_result.label == "ESCALATE" or (low <= npu_result.confidence < high):
        return DecisionArtifact(
            car_hash=car_hash,
            decision=AdjudicationDecision.ESCALATE,
            request_id=car.request_id,
            deterministic_pass=True,
            probabilistic_pass=False,
            confidence=npu_result.confidence,
        )

    # Default: DENY
    return DecisionArtifact(
        car_hash=car_hash,
        decision=AdjudicationDecision.DENY,
        request_id=car.request_id,
        deterministic_pass=True,
        probabilistic_pass=False,
        confidence=npu_result.confidence,
    )
