"""
Shared LLMPipeline for the Policy Agent and the Assistant Orchestrator
======================================================================
ADR-012 §2.1 / §3.1 specify "single compilation, shared weights" across
the 14B's consumers. This module is the implementation: build one
``ov_genai.LLMPipeline`` (target + draft) at boot, wrap it with a
``threading.Lock`` so the two synchronous consumers serialise on a single
``.generate()`` call, and hand the wrapper to both ``PolicyGPUInference``
and ``OrchestratorGPUInference``.

Why a lock at all: one ``LLMPipeline`` cannot serve two concurrent
``.generate()`` calls (it owns one KV-cache scheduler and one set of
compiled inference contexts). For a single-user local assistant where PA
classification and AO conversation are sequential in practice, serialising
the rare overlap is acceptable. PA's latency budget (ADR-012 §2.5) is
tracked excluding and including lock-wait so the budget delta is visible.

Security frame (ADR-012 §1, Red Team ISSUE-003 mitigation): the wrapper
verifies weight integrity for BOTH target and draft before construction,
which raises PA's security floor. Pre-refactor PA verifies only its own
(full) draft; post-refactor both PA and AO use the same verified
pruned-6L draft.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from shared.models.weight_integrity import (
    IntegrityCheckResult,
    verify_weight_integrity,
)

logger = logging.getLogger(__name__)

try:
    import openvino_genai as ov_genai  # type: ignore[import-untyped]

    _OV_GENAI_AVAILABLE = True
except ImportError:
    ov_genai = None  # type: ignore[assignment]
    _OV_GENAI_AVAILABLE = False


@dataclass(frozen=True)
class SharedPipelineBuildResult:
    """Outcome of ``build_shared_pipeline``. Fail-Closed on any error."""

    pipeline: "SharedInferencePipeline | None"
    target_integrity: IntegrityCheckResult | None
    draft_integrity: IntegrityCheckResult | None
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.pipeline is not None and self.error is None


class SharedInferencePipeline:
    """Threading-lock-serialised wrapper around one ``ov_genai.LLMPipeline``.

    Both ``PolicyGPUInference`` and ``OrchestratorGPUInference`` receive
    the same instance from the launcher. Their existing ``.generate()``
    call sites continue to use ``self._pipeline.generate(...)``; the lock
    is transparent.
    """

    def __init__(
        self,
        pipeline: Any,
        lock: threading.Lock,
        rebuild: "Callable[[], Any] | None" = None,
    ) -> None:
        self._pipeline = pipeline
        self._lock = lock
        self._generate_calls: int = 0
        # Closure that reconstructs the raw LLMPipeline (verify + build) on
        # demand, used to lazily RELOAD the 14B after an explicit unload() —
        # UC-010 (#666) evicts it to free RAM for the diffusion hires pass. None
        # disables reload (e.g. a directly-constructed test wrapper); unload()
        # then refuses and generate() raises if the pipeline is gone. Set by
        # build_shared_pipeline.
        self._rebuild = rebuild

    def generate(self, *args: Any, **kwargs: Any) -> Any:
        """Serialised ``.generate()``. Both PA and AO funnel through here.

        If the pipeline was unloaded (UC-010 eviction), it is RELOADED on demand
        under the lock before the call — so the first PA classification or AO
        turn after an image generation transparently pays the one-time 14B
        reload, and neither consumer ever observes a missing pipeline.
        """
        with self._lock:
            if self._pipeline is None:
                self._reload_locked()
            self._generate_calls += 1
            return self._pipeline.generate(*args, **kwargs)

    def _reload_locked(self) -> None:
        """Reconstruct the 14B (caller MUST hold ``self._lock``). Fail-Closed:
        raises if no rebuild closure is set or the rebuild fails — a missing 14B
        is never silently tolerated."""
        if self._rebuild is None:
            raise RuntimeError(
                "SharedInferencePipeline: pipeline was unloaded and no rebuild "
                "closure is set — cannot reload the 14B (Fail-Closed). Restart "
                "the service."
            )
        logger.info("SharedInferencePipeline: reloading the 14B (was evicted)…")
        pipeline = self._rebuild()
        if pipeline is None:
            raise RuntimeError(
                "SharedInferencePipeline: 14B reload returned no pipeline "
                "(Fail-Closed)."
            )
        self._pipeline = pipeline
        logger.info("SharedInferencePipeline: 14B reload complete.")

    def unload(self) -> None:
        """Evict the underlying 14B to free GPU/system RAM.

        UC-010 (#666): a hires-fix diffusion pass at 1536² overflows the 31.3 GB
        ceiling co-resident with the resident 14B (measured: it thrashes the 14B
        to disk). For a hires image generate the AO calls this to evict the 14B
        for the duration; the next :meth:`generate` reloads it lazily via the
        rebuild closure. Idempotent and thread-safe. A no-op when no rebuild
        closure is set — without one a reload would be impossible, so eviction is
        refused rather than wedging the service (Fail-Closed)."""
        import gc

        with self._lock:
            if self._pipeline is None:
                return
            if self._rebuild is None:
                logger.warning(
                    "SharedInferencePipeline: unload() refused — no rebuild "
                    "closure, so the 14B could not be reloaded. Keeping it."
                )
                return
            self._pipeline = None
        gc.collect()
        logger.info(
            "SharedInferencePipeline: 14B evicted; reloads on next generate()."
        )

    def release_gpu_for_exit(self) -> bool:
        """Drop the underlying 14B to release its GPU/Level-Zero context — for the
        PROCESS-EXIT path ONLY (the model-swap step-aside, #670 run-2), where no reload
        follows, so the rebuild-closure guard :meth:`unload` honors does NOT apply.

        A forceful ``os._exit`` skips the OpenVINO destructors, so the 14B's GPU context
        would linger and the incoming 30B could OOM (run-2 fit by timing luck only).
        Calling this first releases the GPU gracefully before the hard exit. Idempotent +
        thread-safe; returns True if a pipeline was released. The ACTUAL GPU-context
        teardown is live-validated on the box (the instrumented GPU-free before/after)."""
        import gc

        with self._lock:
            if self._pipeline is None:
                return False
            self._pipeline = None
        gc.collect()
        logger.info(
            "SharedInferencePipeline: 14B GPU context released for process exit (#670)."
        )
        return True

    @property
    def is_loaded(self) -> bool:
        """True iff the underlying pipeline is currently resident."""
        return self._pipeline is not None

    @property
    def raw(self) -> Any:
        """Direct access to the underlying pipeline.

        Only for one-time setup (tokenizer fetch, ``finish_chat`` cleanup,
        property reads) that runs without contention. Do NOT use for
        ``.generate()`` — that must go through the lock.
        """
        return self._pipeline

    @property
    def generate_call_count(self) -> int:
        """Cumulative number of serialised ``.generate()`` calls."""
        return self._generate_calls


def build_shared_pipeline(
    *,
    model_dir: Path,
    draft_model_dir: Path,
    enable_prefix_caching: bool,
    device: str = "GPU",
    target_manifest_path: Path | None = None,
    draft_manifest_path: Path | None = None,
    model_priority: str = "HIGH",
    kv_cache_precision: str | None = None,
) -> SharedPipelineBuildResult:
    """Construct one ``LLMPipeline`` + lock and return them wrapped.

    Called once at boot from the launcher, BEFORE either the Policy Agent
    or the Assistant Orchestrator service is constructed. The returned
    wrapper is then passed into both ``PolicyGPUInference`` and
    ``OrchestratorGPUInference``.

    Security: if manifest paths are supplied, weight integrity is
    verified for both target and draft. Fail-Closed on mismatch.

    Args:
        model_dir: Path to the target model directory (Qwen3-14B INT4).
        draft_model_dir: Path to the draft model directory (Qwen3-0.6B
            pruned-6L INT8, per ADR-012 Amendment 3).
        enable_prefix_caching: Whether OV GenAI prefix caching is on.
            Locked empirically per ADR-012 Amendment 3 §Phase 0.
        device: OpenVINO device string (default ``"GPU"``).
        target_manifest_path: Optional Known-Good Manifest for the target.
        draft_manifest_path: Optional Known-Good Manifest for the draft.
        model_priority: ``"HIGH"`` for the security-gate posture inherited
            from the Policy Agent (ADR-012 Amendment 3).
        kv_cache_precision: Optional GPU ``KV_CACHE_PRECISION`` hint
            (OpenVINO 2026.2; e.g. ``'u8'``/``'u4'``/``'i4'``). None/empty =
            unset = the runtime default (FP16) — a Session-2 memory/quality A/B
            knob. On the Arc 140V (XMX) KV-cache quant is opt-in, so this must
            be set explicitly to engage.

    Returns:
        SharedPipelineBuildResult with ``.ok`` True on success, with
        ``.pipeline`` populated and integrity results recorded.
    """
    if not _OV_GENAI_AVAILABLE:
        return SharedPipelineBuildResult(
            pipeline=None,
            target_integrity=None,
            draft_integrity=None,
            error="OpenVINO GenAI not available",
        )

    # Resolve weight files.
    target_bin = model_dir / "openvino_model.bin"
    draft_bin = draft_model_dir / "openvino_model.bin"

    if not (model_dir / "openvino_model.xml").exists() or not target_bin.exists():
        return SharedPipelineBuildResult(
            pipeline=None,
            target_integrity=None,
            draft_integrity=None,
            error=f"Target model files missing under {model_dir}",
        )
    if not (draft_model_dir / "openvino_model.xml").exists() or not draft_bin.exists():
        return SharedPipelineBuildResult(
            pipeline=None,
            target_integrity=None,
            draft_integrity=None,
            error=f"Draft model files missing under {draft_model_dir}",
        )

    # Weight integrity — Fail-Closed on any failure.
    target_integrity: IntegrityCheckResult | None = None
    draft_integrity: IntegrityCheckResult | None = None
    if target_manifest_path is not None:
        target_integrity = verify_weight_integrity(
            model_path=str(target_bin),
            manifest_path=str(target_manifest_path),
        )
        if not target_integrity.verified:
            return SharedPipelineBuildResult(
                pipeline=None,
                target_integrity=target_integrity,
                draft_integrity=None,
                error=f"Target weight integrity FAILED: {target_integrity.error}",
            )
        logger.info("Shared pipeline: target weight integrity verified (%s)", target_bin)
    if draft_manifest_path is not None:
        draft_integrity = verify_weight_integrity(
            model_path=str(draft_bin),
            manifest_path=str(draft_manifest_path),
        )
        if not draft_integrity.verified:
            return SharedPipelineBuildResult(
                pipeline=None,
                target_integrity=target_integrity,
                draft_integrity=draft_integrity,
                error=f"Draft weight integrity FAILED: {draft_integrity.error}",
            )
        logger.info("Shared pipeline: draft weight integrity verified (%s)", draft_bin)

    # Construct one LLMPipeline. Speculative decoding is mandatory per
    # ADR-012 §3.1 — autoregressive solo runs at ~2-3 tps on the 14B,
    # too slow for interactive use. If draft construction fails, return
    # an error rather than silently falling back; the launcher decides
    # whether to abort or to fall back to per-service pipelines.
    scheduler = ov_genai.SchedulerConfig()
    scheduler.cache_size = 3
    scheduler.enable_prefix_caching = enable_prefix_caching

    try:
        draft_model = ov_genai.draft_model(
            str(draft_model_dir),
            device,
            PERFORMANCE_HINT="LATENCY",
            INFERENCE_PRECISION_HINT="f16",
            GPU_ENABLE_SDPA_OPTIMIZATION="ON",
            CACHE_DIR="",
        )
        target_config: dict[str, object] = {
            "PERFORMANCE_HINT": "LATENCY",
            "MODEL_PRIORITY": model_priority,
            "INFERENCE_PRECISION_HINT": "f16",
            "GPU_ENABLE_SDPA_OPTIMIZATION": "ON",
            "CACHE_DIR": "",
            "scheduler_config": scheduler,
            "draft_model": draft_model,
        }
        # OpenVINO 2026.2 GPU KV-cache quantization hint (A3). Added ONLY when
        # set, so the unset default leaves target_config byte-identical to the
        # pre-2026.2 behaviour (FP16 KV-cache). On the Arc 140V (XMX) KV-cache
        # quant is opt-in — it engages only with this property present.
        if kv_cache_precision:
            target_config["KV_CACHE_PRECISION"] = kv_cache_precision
        pipeline = ov_genai.LLMPipeline(
            str(model_dir),
            device,
            **target_config,
        )
    except TypeError as exc:
        # Older OV GenAI builds may not accept the full kwarg set. Retry
        # without compile hints / spec-decode kwargs — autoregressive
        # fallback. Logged so an operator can see the degradation.
        logger.warning(
            "Shared pipeline: LLMPipeline rejected kwargs (older OV GenAI build) — "
            "retrying without spec-decode hints. Reason: %s",
            exc,
        )
        try:
            pipeline = ov_genai.LLMPipeline(str(model_dir), device)
        except Exception as exc2:  # noqa: BLE001
            return SharedPipelineBuildResult(
                pipeline=None,
                target_integrity=target_integrity,
                draft_integrity=draft_integrity,
                error=f"LLMPipeline init failed even after fallback: {exc2}",
            )
    except Exception as exc:  # noqa: BLE001
        return SharedPipelineBuildResult(
            pipeline=None,
            target_integrity=target_integrity,
            draft_integrity=draft_integrity,
            error=f"LLMPipeline init failed: {exc}",
        )

    def _rebuild_raw() -> Any:
        # Reconstruct the raw 14B pipeline on demand (UC-010 eviction reload).
        # Re-runs the SAME verified build with the captured params and returns
        # the new raw pipeline; the throwaway wrapper it builds is discarded
        # (its own rebuild closure is never invoked, so there is no recursion).
        res = build_shared_pipeline(
            model_dir=model_dir,
            draft_model_dir=draft_model_dir,
            enable_prefix_caching=enable_prefix_caching,
            device=device,
            target_manifest_path=target_manifest_path,
            draft_manifest_path=draft_manifest_path,
            model_priority=model_priority,
            kv_cache_precision=kv_cache_precision,
        )
        if not res.ok or res.pipeline is None:
            raise RuntimeError(
                f"14B reload failed (Fail-Closed): {res.error or 'unknown error'}"
            )
        return res.pipeline.raw

    wrapper = SharedInferencePipeline(pipeline, threading.Lock(), rebuild=_rebuild_raw)
    logger.info(
        "Shared pipeline built: device=%s, model_priority=%s, "
        "enable_prefix_caching=%s, draft=%s",
        device,
        model_priority,
        enable_prefix_caching,
        draft_model_dir,
    )
    return SharedPipelineBuildResult(
        pipeline=wrapper,
        target_integrity=target_integrity,
        draft_integrity=draft_integrity,
    )
