"""CAP-3 (#719) live smoke — the REAL 14B reaches for search_knowledge unprompted.

WHY THIS FILE EXISTS
====================
#719 registered ``search_knowledge`` as a GUARDED model-callable tool. The +55
deterministic tests lock the mechanics (registration, clamps, provenance
grounding, Layer-3 locking, notices); the eval golden cases lock parse and
allowlist behavior. What none of them can prove is the MODEL side: shown the
tools block, does the real Qwen3-14B actually CHOOSE the retrieval tool for a
knowledge question, call it with a sensible query, and use the grounded result?
That behavioral link is what makes the tool-surface expansion "agentic" rather
than plumbing — this file is that link, live.

The runner is SEEDED (registered via the real ``register_search_knowledge_
runner`` seam with a fixture snippet) rather than backed by a real encrypted
bank: the encrypted-store retrieval path is already covered deterministically
(the runner the entrypoint registers delegates to the same ``_knowledge_
retrieve`` the auto-recall uses), and seeding keeps this smoke focused on the
one unproven thing — model behavior through the real loop.

MARKERS / WHERE THIS RUNS
=========================
``slow`` + ``hardware``: deselected from the standing gate; run serially on the
GPU box. Skips cleanly when weights are absent. Emits ``KNOWSMOKE_PERF``
parseable timing lines.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import pytest

pytestmark = [pytest.mark.slow, pytest.mark.hardware]

_REPO_ROOT = Path(__file__).resolve().parents[2]

_TIMING_PREFIX = "KNOWSMOKE_PERF"

# A distinctive, un-guessable fact: the model cannot answer without retrieval.
_SEEDED_SNIPPET = (
    "[knowledge: home_network.md] The operator's NAS hostname is VAULT-7 and "
    "it is reachable at 10.0.0.42."
)


class _FakeTransport:
    """Single-shot transport: hands the service one inbound frame, records sent."""

    def __init__(self, inbound: bytes | None) -> None:
        self._inbound = inbound
        self.sent: list[bytes] = []

    def receive(self) -> bytes | None:
        return self._inbound

    def send(self, data: bytes) -> bool:
        self.sent.append(data)
        return True


def _real_engine_or_skip() -> Any:
    """Load the real Qwen3-14B (with the spec-decode draft), or skip if absent."""
    from services.assistant_orchestrator.src.gpu_inference import (
        OrchestratorGPUInference,
    )
    from shared.constants import DRAFT_MODEL_OV_PATH, TARGET_MODEL_OV_PATH

    model_dir = _REPO_ROOT / TARGET_MODEL_OV_PATH
    if not model_dir.exists():
        pytest.skip(f"14B weights absent: {model_dir}")
    draft_dir = _REPO_ROOT / DRAFT_MODEL_OV_PATH
    engine = OrchestratorGPUInference(
        model_dir=str(model_dir),
        device="GPU",
        draft_model_dir=str(draft_dir) if draft_dir.exists() else None,
        manifest_path=None,
    )
    load_start = time.perf_counter()
    if not engine.load_model():
        raise RuntimeError("14B load_model() returned False despite weights on disk")
    print(
        f"{_TIMING_PREFIX} model_load_seconds="
        f"{time.perf_counter() - load_start:.3f}"
    )
    return engine


def _make_service_with(engine: Any) -> Any:
    """Real AssistantOrchestratorService wired to the real engine (dev harness
    posture: leakage OFF so no embedder is needed; grammar knob rides its
    shipped default ON)."""
    from shared.ipc.vsock import VsockAddress, VsockConfig
    from services.assistant_orchestrator.src.context_manager import ContextManager
    from services.assistant_orchestrator.src.entrypoint import (
        AssistantOrchestratorEntrypointConfig,
        AssistantOrchestratorService,
    )

    config = AssistantOrchestratorEntrypointConfig(
        model_dir=Path("models"),
        manifest_path=None,
        device="GPU",
        priority=1,
        draft_model_dir=None,
        speculative_decoding_enabled=False,
        max_new_tokens=256,
        generation_temperature=0.0,
        generation_top_k=50,
        generation_top_p=0.9,
        generation_repetition_penalty=1.1,
        generation_do_sample=False,
        response_depth_mode="standard",
        dev_mode=True,
        jwt_ca_cert_path=None,
        vsock_config=VsockConfig(address=VsockAddress(cid=0, port=0)),
        pgov_cosine_threshold=0.85,
        deployment_mode="host",  # type: ignore[arg-type]
        block_tools_on_untrusted_content=True,
        pgov_leakage_detection_enabled=False,
    )
    service = AssistantOrchestratorService("dummy.toml")
    service._resolved_config = config
    service._context_manager = ContextManager()
    service._inference = engine
    return service


def _drive(service: Any, **kwargs: Any) -> _FakeTransport:
    """Encode a PROMPT_REQUEST, run one connection, return the transport."""
    from shared.ipc.protocol import MessageFramer

    framer = MessageFramer()
    request = framer.encode_prompt_request(**kwargs)
    transport = _FakeTransport(request)
    service._handle_connection(transport)
    return transport


@pytest.fixture(scope="module")
def engine() -> Any:
    """Load the real 14B ONCE for the module; unload at module teardown."""
    eng = _real_engine_or_skip()
    yield eng
    if hasattr(eng, "unload"):
        eng.unload()


def test_model_reaches_for_search_knowledge_and_grounds_the_result(
    engine: Any, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """The real model CHOOSES search_knowledge for a knowledge question.

    Strict mechanical assertions:
      (a) the model emitted a parsed ``search_knowledge`` call (native form —
          no legacy fallback, no fail-closed drops anywhere in the turn);
      (b) the registered runner was invoked with a non-empty query and a
          clamped max_results in [1, 8];
      (c) the retrieval result was GROUNDED with UNTRUSTED_KNOWLEDGE provenance
          — ``has_untrusted_content`` flips for the session (the Layer-3
          feedstock) while the leakage feed stays exempt per ADR-023 Am.2;
      (d) the turn completed with response frames.
    Lenient (wording) assertion:
      (e) the distinctive seeded fact (the NAS hostname) appears in the raw
          final generation — the model actually USED the retrieval.
    """
    import services.assistant_orchestrator.src.tools as tools_mod

    service = _make_service_with(engine)

    runner_calls: list[tuple[str, int]] = []

    def _seeded_runner(query: str, max_results: int) -> str:
        runner_calls.append((query, max_results))
        return _SEEDED_SNIPPET

    tools_mod.register_search_knowledge_runner(_seeded_runner)

    parsed_calls: list[tuple[str, str]] = []
    raw_generations: list[str] = []
    real_parse = tools_mod.parse_tool_call

    def _spy_parse(text: str) -> tuple[str, str] | None:
        raw_generations.append(text)
        result = real_parse(text)
        if result is not None:
            parsed_calls.append(result)
        return result

    monkeypatch.setattr(tools_mod, "parse_tool_call", _spy_parse)

    try:
        turn_start = time.perf_counter()
        with caplog.at_level("WARNING"):
            transport = _drive(
                service,
                session_id="harness-know-smoke",
                prompt=(
                    "Check my knowledge bank: what is the hostname of my NAS?"
                ),
                request_id="r-know-smoke",
            )
        turn_ms = (time.perf_counter() - turn_start) * 1000.0

        # (d) The turn completed and streamed frames back.
        assert transport.sent, "the knowledge-smoke turn produced no response frames"

        # (a) The model chose search_knowledge, natively, with nothing dropped.
        assert parsed_calls, (
            "the real model emitted NO parseable tool call for a direct "
            f"knowledge question — raw generations: {raw_generations!r}"
        )
        assert parsed_calls[0][0] == "search_knowledge", (
            f"expected search_knowledge, got {parsed_calls[0][0]!r}"
        )
        joined_warnings = " ".join(rec.getMessage() for rec in caplog.records)
        assert "LEGACY tool-call form used" not in joined_warnings, joined_warnings
        assert "dropped (fail-closed)" not in joined_warnings, joined_warnings

        # (b) The runner really ran, with a sane query and a clamped k.
        assert runner_calls, "search_knowledge parsed but the runner never ran"
        query, k = runner_calls[0]
        assert query.strip(), "runner received an empty query"
        assert 1 <= k <= 8, f"max_results outside the documented clamp: {k}"

        # (c) The provenance chain fired: the session now holds untrusted
        # content (UNTRUSTED_KNOWLEDGE grounding), and the Stage-5 leakage
        # feed remains EXEMPT (ADR-023 Am.2).
        assert service._context_manager.has_untrusted_content(
            "harness-know-smoke"
        ), "retrieval result was not grounded with untrusted provenance"
        assert not service._context_manager.get_untrusted_chunk_texts(
            "harness-know-smoke"
        ), "UNTRUSTED_KNOWLEDGE must stay exempt from the Stage-5 leakage feed"

        # (e) Lenient wording check: the model used the seeded fact.
        final_generation = raw_generations[-1] if raw_generations else ""
        assert "VAULT-7" in final_generation, (
            "the distinctive seeded fact never appeared in the final "
            f"generation: {final_generation!r}"
        )

        print(f"{_TIMING_PREFIX} turn_total_ms={turn_ms:.1f}")
        print(f"{_TIMING_PREFIX} generations_in_loop={len(raw_generations)}")
        print(f"{_TIMING_PREFIX} query={query!r} k={k}")
    finally:
        tools_mod.clear_search_knowledge_runner()
