"""
Eval Harness — Continuous-Batching Engine Arms (#1663)
======================================================
Qwen3.5 ships a Multi-Token Prediction (MTP) head inside its export
(``openvino_mtp_model.xml``). OpenVINO GenAI turns it on only through
``ContinuousBatchingPipeline`` with a ``draft_model`` pointing at the SAME
directory; ``VLMPipeline`` (the existing ``multimodal-vlm`` arm) cannot use it.

This module is the arm that can. :class:`CBEnginePipeline` wraps one
``ContinuousBatchingPipeline`` in exactly the surface the production Policy
Agent and Assistant Orchestrator already attach to
(``generate(prompt, generation_config=..., streamer=...)``,
``try_run_exclusive``, ``raw``, ``is_loaded``), so every suite drives the REAL
production inference classes through their real entry points instead of a
re-implementation.

Three engines, differing in exactly the variable named:

``cb-mtp-off``
    Continuous batching, no draft, prefix caching OFF.
``cb-mtp-on``
    Same, plus the MTP head. Greedy only; static ``num_assistant_tokens``.
``cb-prefix-cache``
    Continuous batching, no draft, prefix caching ON — the multi-turn price
    that MTP charges (MTP requires prefix caching OFF).

Every generation records a statistics row (first streamed chunk, chunk count,
generated/accepted/rejected draft tokens, TTFT/TPOT) so a run can PROVE that the
head engaged, and that thinking was suppressed, instead of inferring either from
a score (lesson 369). ``assert_mtp_engaged`` refuses a speed claim when the
accepted-token count is zero.

Fail-closed: a missing ``openvino_genai``, a load failure or a generation error
raises ``RuntimeError``; nothing degrades to a silent empty answer.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger(__name__)

ENGINE_DEFAULT: str = "default"
ENGINE_MTP_OFF: str = "cb-mtp-off"
ENGINE_MTP_ON: str = "cb-mtp-on"
ENGINE_PREFIX_CACHE: str = "cb-prefix-cache"

#: argparse ``choices`` for ``--engine``. ``default`` is the byte-identical
#: pre-#1663 behaviour for the declared capability.
ENGINE_CHOICES: tuple[str, ...] = (
    ENGINE_DEFAULT,
    ENGINE_MTP_OFF,
    ENGINE_MTP_ON,
    ENGINE_PREFIX_CACHE,
)

ENV_ENGINE: str = "BLARAI_EVAL_ENGINE"
#: Optional JSONL path; every generation appends its statistics row here.
ENV_CB_STATS: str = "BLARAI_EVAL_CB_STATS"

#: Static draft length for the MTP arm. A constant, never adaptive: GenAI's
#: linear-verifier constraints for hybrid (linear-attention) models require a
#: static ``num_assistant_tokens`` (genai 2026.4.0.0, ``pipeline_impl.cpp``).
MTP_NUM_ASSISTANT_TOKENS: int = 3

#: Compile properties shared by every CB arm, so the arms differ only in the
#: variable under test. ``KV_CACHE_PRECISION=f16`` and
#: ``DYNAMIC_QUANTIZATION_GROUP_SIZE=0`` are the documented cure for
#: speculative-vs-plain greedy divergence (genai #4476); they are stamped on the
#: MTP-off arm too, and production leaves both at the plugin default.
_COMPILE_PROPERTIES: dict[str, object] = {
    "PERFORMANCE_HINT": "LATENCY",
    "INFERENCE_PRECISION_HINT": "f16",
    "GPU_ENABLE_SDPA_OPTIMIZATION": "ON",
    "CACHE_DIR": "",
    "KV_CACHE_PRECISION": "f16",
    "DYNAMIC_QUANTIZATION_GROUP_SIZE": 0,
}

#: KV budget in GB — the production scheduler value. ``max_num_seqs`` is 1 (one
#: request at a time, as BlarAI serves) because the linear-attention state is
#: reserved per sequence and the default of 256 exceeds any sane budget.
_CACHE_SIZE_GB: int = 3
_MAX_NUM_SEQS: int = 1


class CBEngineError(RuntimeError):
    """The CB engine arm failed to load, run, or prove it engaged."""


class CBText(str):
    """The generated text, carrying the statistics row of the call that made it."""

    stats: dict[str, Any]


@dataclass(frozen=True)
class EngineSpec:
    """What an engine arm turns on."""

    name: str
    mtp: bool
    prefix_caching: bool


_SPECS: dict[str, EngineSpec] = {
    ENGINE_MTP_OFF: EngineSpec(ENGINE_MTP_OFF, mtp=False, prefix_caching=False),
    ENGINE_MTP_ON: EngineSpec(ENGINE_MTP_ON, mtp=True, prefix_caching=False),
    ENGINE_PREFIX_CACHE: EngineSpec(ENGINE_PREFIX_CACHE, mtp=False, prefix_caching=True),
}


def engine_spec(name: str) -> EngineSpec:
    """Resolve an engine name, raising for ``default`` or an unknown name."""
    try:
        return _SPECS[name]
    except KeyError:
        raise CBEngineError(
            f"unknown CB engine {name!r} (must be one of: {', '.join(_SPECS)})"
        ) from None


class CBEnginePipeline:
    """One ``ContinuousBatchingPipeline`` presented as the shared-pipeline surface.

    Thread-safe: a single lock serialises generations, like the production
    ``SharedInferencePipeline`` this stands in for.
    """

    def __init__(self, model_dir: Path, engine: str, *, device: str = "GPU") -> None:
        self._spec = engine_spec(engine)
        self._model_dir = Path(model_dir)
        self._device = device
        self._lock = threading.Lock()
        self._calls = 0
        self.stats: list[dict[str, Any]] = []
        try:
            import openvino_genai as ov_genai  # type: ignore[import-untyped]
        except ImportError as exc:
            raise CBEngineError(
                "OpenVINO GenAI is not available — cannot load a "
                "ContinuousBatchingPipeline (fail-closed)."
            ) from exc
        self._ov = ov_genai

        if self._spec.mtp and not (self._model_dir / "openvino_mtp_model.xml").exists():
            raise CBEngineError(
                f"{self._model_dir} has no openvino_mtp_model.xml — the MTP head is "
                "absent, so the cb-mtp-on arm cannot engage (fail-closed)."
            )

        scheduler = ov_genai.SchedulerConfig()
        scheduler.cache_size = _CACHE_SIZE_GB
        scheduler.max_num_seqs = _MAX_NUM_SEQS
        scheduler.enable_prefix_caching = self._spec.prefix_caching
        props: dict[str, object] = dict(_COMPILE_PROPERTIES)
        if self._spec.mtp:
            props["draft_model"] = ov_genai.draft_model(str(self._model_dir), device)
        t0 = time.perf_counter()
        try:
            self._pipe: Any = ov_genai.ContinuousBatchingPipeline(
                str(self._model_dir), scheduler, device, props
            )
        except Exception as exc:  # noqa: BLE001 — surface the load failure fail-closed
            raise CBEngineError(
                f"ContinuousBatchingPipeline failed to load {self._model_dir} "
                f"({self._spec.name}): {exc}"
            ) from exc
        self.load_seconds = time.perf_counter() - t0
        self.header: dict[str, Any] = {
            "engine": self._spec.name,
            "mtp": self._spec.mtp,
            "prefix_caching": self._spec.prefix_caching,
            "model_dir": str(self._model_dir),
            "device": device,
            "genai_version": getattr(ov_genai, "__version__", "?"),
            "scheduler": {
                "cache_size_gb": _CACHE_SIZE_GB,
                "max_num_seqs": _MAX_NUM_SEQS,
            },
            "compile_properties": {k: v for k, v in props.items() if k != "draft_model"},
            "num_assistant_tokens": MTP_NUM_ASSISTANT_TOKENS if self._spec.mtp else None,
            "load_seconds": round(self.load_seconds, 2),
        }
        logger.info("CB engine loaded: %s", self.header)

    # -- the surface production attaches to --------------------------------

    @property
    def engine(self) -> str:
        return self._spec.name

    @property
    def is_loaded(self) -> bool:
        return self._pipe is not None

    @property
    def raw(self) -> "CBEnginePipeline":
        # Production hands ``raw`` into ``try_run_exclusive`` callbacks, which
        # then call ``.generate`` on it with the lock already held; this class's
        # own ``generate`` is the lock-free-by-reentry path via ``_generate``.
        return _Unlocked(self)

    @property
    def generate_call_count(self) -> int:
        return self._calls

    def get_tokenizer(self) -> Any:
        """The engine's own tokenizer, which production asks for the turn-end id."""
        return self._pipe.get_tokenizer()

    def unload(self) -> None:  # parity with SharedInferencePipeline; eviction is not modelled
        return None

    def try_run_exclusive(self, fn: Callable[[Any], Any]) -> tuple[str, Any | None]:
        from shared.inference.shared_pipeline import TRY_RUN_BUSY, TRY_RUN_RAN

        if not self._lock.acquire(blocking=False):
            return (TRY_RUN_BUSY, None)
        try:
            return (TRY_RUN_RAN, fn(_Unlocked(self)))
        finally:
            self._lock.release()

    def generate(
        self,
        prompt: str,
        generation_config: Any = None,
        streamer: Callable[[str], Any] | None = None,
        **_ignored: Any,
    ) -> CBText:
        with self._lock:
            return self._generate(prompt, generation_config, streamer)

    # -- internals ----------------------------------------------------------

    def _generate(
        self,
        prompt: str,
        generation_config: Any,
        streamer: Callable[[str], Any] | None,
    ) -> CBText:
        ov = self._ov
        cfg = generation_config if generation_config is not None else ov.GenerationConfig()
        if self._spec.mtp:
            cfg.num_assistant_tokens = MTP_NUM_ASSISTANT_TOKENS
            cfg.assistant_confidence_threshold = 0.0
        first: list[str] = []
        chunks = [0]

        def _tap(chunk: str) -> Any:
            if not first:
                first.append(chunk)
            chunks[0] += 1
            if streamer is not None:
                return streamer(chunk)
            return ov.StreamingStatus.RUNNING

        t0 = time.perf_counter()
        try:
            results = self._pipe.generate([prompt], [cfg], _tap)
        except Exception as exc:  # noqa: BLE001 — fail-closed
            raise CBEngineError(f"CB generation failed ({self._spec.name}): {exc}") from exc
        wall_ms = (time.perf_counter() - t0) * 1000.0
        self._calls += 1

        result = results[0]
        texts = result.m_generation_ids
        if not texts:
            raise CBEngineError(
                f"CB generation returned no sequence ({self._spec.name}) — refusing an "
                "empty answer rather than scoring it (fail-closed)."
            )
        text = texts[0]
        row: dict[str, Any] = {
            "engine": self._spec.name,
            "call": self._calls,
            "first_chunk": first[0] if first else "",
            "n_stream_chunks": chunks[0],
            "wall_ms": round(wall_ms, 2),
        }
        pm = getattr(result, "perf_metrics", None)
        if pm is not None:
            try:
                row["generated_tokens"] = int(pm.get_num_generated_tokens())
                row["input_tokens"] = int(pm.get_num_input_tokens())
                row["ttft_ms"] = round(float(pm.get_ttft().mean), 2)
                row["tpot_ms"] = round(float(pm.get_tpot().mean), 2)
            except Exception as exc:  # noqa: BLE001 — logged, row simply lacks the field
                logger.warning("perf metrics unreadable: %s", exc)
        em = getattr(result, "extended_perf_metrics", None)
        if em is not None:
            try:
                row["draft_tokens"] = int(em.get_num_draft_tokens())
                row["accepted_tokens"] = int(em.get_num_accepted_tokens())
                row["rejected_tokens"] = int(em.get_num_rejected_tokens())
                row["acceptance_rate"] = round(float(em.get_draft_acceptance_rate()), 4)
            except Exception as exc:  # noqa: BLE001
                logger.warning("speculative metrics unreadable: %s", exc)
        self.stats.append(row)
        sink = os.environ.get(ENV_CB_STATS)
        if sink:
            with open(sink, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(row, sort_keys=True) + "\n")

        out = CBText(text)
        out.stats = row
        return out

    def summary(self) -> dict[str, Any]:
        """Aggregate witness over every generation so far."""
        rows = self.stats
        gen = sum(int(r.get("generated_tokens", 0)) for r in rows)
        acc = sum(int(r.get("accepted_tokens", 0)) for r in rows)
        drafted = sum(int(r.get("draft_tokens", 0)) for r in rows)
        first_chunks = [str(r.get("first_chunk", "")) for r in rows]
        return {
            **self.header,
            "generations": len(rows),
            "generated_tokens": gen,
            "draft_tokens": drafted,
            "accepted_tokens": acc,
            "acceptance_rate": round(acc / drafted, 4) if drafted else None,
            "think_first_chunk_count": sum(1 for c in first_chunks if "<think>" in c),
        }


class _Unlocked:
    """``raw`` handle: same generate, but the caller already holds the lock."""

    def __init__(self, owner: CBEnginePipeline) -> None:
        self._owner = owner

    def generate(self, prompt: str, generation_config: Any = None, streamer: Any = None, **kw: Any) -> CBText:
        return self._owner._generate(prompt, generation_config, streamer)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._owner, name)


def assert_mtp_engaged(pipeline: CBEnginePipeline) -> dict[str, Any]:
    """Refuse a speed claim from an MTP arm whose head never accepted a token.

    A silently inactive head produces "no speed-up", which reads exactly like the
    slow-verify kernel report (openvino#38153). Raises :class:`CBEngineError` when
    the engine is MTP-on and no generation recorded an accepted draft token.
    """
    summary = pipeline.summary()
    if pipeline.engine == ENGINE_MTP_ON and not summary["accepted_tokens"]:
        raise CBEngineError(
            "cb-mtp-on recorded zero accepted draft tokens over "
            f"{summary['generations']} generations — the MTP head did not engage; "
            "no speed result may be reported from this run."
        )
    return summary


# One pipeline per (directory, engine) per process: ``--suite all`` builds a
# generator per suite, and two resident copies of a model are a memory hazard.
_REGISTRY: dict[tuple[str, str], CBEnginePipeline] = {}
_REGISTRY_LOCK = threading.Lock()


def get_engine_pipeline(model_dir: Path, engine: str, *, device: str = "GPU") -> CBEnginePipeline:
    """Return the process-wide pipeline for ``(model_dir, engine)``, building it once.

    Building a different engine for the same directory first drops the previous
    one, so at most one copy of the model is ever resident.
    """
    key = (str(Path(model_dir).resolve()), engine)
    with _REGISTRY_LOCK:
        existing = _REGISTRY.get(key)
        if existing is not None:
            return existing
        for stale in list(_REGISTRY):
            _REGISTRY.pop(stale)
        import gc

        gc.collect()
        pipeline = CBEnginePipeline(Path(model_dir), engine, device=device)
        _REGISTRY[key] = pipeline
        return pipeline


def registered_pipelines() -> list[CBEnginePipeline]:
    """Every live engine pipeline (for end-of-run witness reporting)."""
    with _REGISTRY_LOCK:
        return list(_REGISTRY.values())


# ---------------------------------------------------------------------------
# Production inference classes, attached to an engine arm
# ---------------------------------------------------------------------------


def build_ao_inference(model_dir: Path, engine: str) -> Any:
    """The REAL ``OrchestratorGPUInference`` attached to a CB engine pipeline.

    The Assistant Orchestrator is constructed the way the launcher constructs it
    for a shared brain: ``shared_pipeline=`` supplied, no draft, no manifest
    sweep. Loading goes through ``load_model()`` so the tokenizer, turn-end token
    and chat-template posture are resolved by production code, not by the eval.
    """
    from services.assistant_orchestrator.src.gpu_inference import OrchestratorGPUInference

    pipeline = get_engine_pipeline(model_dir, engine)
    inference = OrchestratorGPUInference(
        model_dir=str(model_dir),
        speculative_decoding_enabled=False,
        shared_pipeline=pipeline,  # type: ignore[arg-type] — duck-typed shared surface
    )
    if not inference.load_model():
        raise CBEngineError(f"AO failed to attach to the {engine} pipeline for {model_dir}")
    return inference


def build_pa_inference(model_dir: Path, engine: str) -> Any:
    """The REAL ``PolicyGPUInference`` attached to a CB engine pipeline."""
    from services.policy_agent.src.gpu_inference import PolicyGPUInference

    pipeline = get_engine_pipeline(model_dir, engine)
    inference = PolicyGPUInference(
        str(model_dir),
        speculative_decoding_enabled=False,
        shared_pipeline=pipeline,  # type: ignore[arg-type] — duck-typed shared surface
    )
    if not inference.load_model():
        raise CBEngineError(f"PA failed to attach to the {engine} pipeline for {model_dir}")
    return inference
