"""CAP-2 (#718) live verify — native JSON tool call through the REAL 14B loop.

WHY THIS FILE EXISTS
====================
#718 migrated tool calling to the Qwen3-native JSON format and enabled the
xgrammar structural-tags constraint (``[generation].tool_call_grammar = true``,
default ON). The builder proved the grammar COMPOSES with speculative decoding +
streaming offline (qwen3-0.6b on CPU, 6-leg probe) — but no test drives the REAL
Qwen3-14B on the Arc 140V through the real AO tool loop with the new system
prompt + grammar live. This file is that link:

    real 14B (spec-decode) -> new <tools> system prompt -> model EMITS a
    native-format tool call -> strict-JSON parse -> #570 PA adjudication ->
    dispatch -> tool result feeds the loop -> final streamed answer.

The mocked suites prove the deterministic mechanics; the VALUE here is the model
side — that the real model, shown the Hermes-style tools block, actually emits
the trained JSON form (not the retired homemade form), that the grammar config
does not break real GPU generation, and that the loop completes a turn.

MARKERS / WHERE THIS RUNS
=========================
``slow`` + ``hardware``: deselected from the standing gate; the Orchestrator
runs it serially on the GPU box. Skips cleanly when the weights are absent
(builder worktrees, CI). Emits parseable ``TOOLRT_PERF`` timing lines for
community-grade perf capture (PERFORMANCE_LOG.md / docs/performance/).

Harness pattern mirrors ``tests/harness/test_sprint12_real_model.py`` (module-
scoped engine so the 14B loads once; ``_FakeTransport`` single-shot connection
drive; lenient wording assertions to survive real-model nondeterminism — the
STRICT assertions are on the mechanics: a native-form call parsed, no legacy
fallback fired, no fail-closed drop fired, the tool dispatched, frames streamed).
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import pytest

pytestmark = [pytest.mark.slow, pytest.mark.hardware]

_REPO_ROOT = Path(__file__).resolve().parents[2]

# The three zero-argument clock tools the model may reasonably pick for a
# "what time is it" ask. get_current_time is the trained-obvious choice, but a
# real model choosing its date/day siblings is not a mechanics failure.
_CLOCK_TOOLS = {"get_current_time", "get_current_date", "get_day_of_week"}

_TIMING_PREFIX = "TOOLRT_PERF"


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
    """Load the real Qwen3-14B (WITH the spec-decode draft), or skip if absent.

    The draft model is deliberately wired when present: #718's compose claim is
    grammar + speculative decoding + streaming, so the live verify must run the
    spec-decode pipeline, not the plain one.
    """
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
        f"{time.perf_counter() - load_start:.3f} "
        f"draft_wired={draft_dir.exists()}"
    )
    return engine


def _make_service_with(engine: Any) -> Any:
    """Real AssistantOrchestratorService wired to the real engine.

    Grammar knob rides the dataclass default (``generation_tool_call_grammar=
    True`` — the shipped production default this test exists to verify live).
    Leakage detection OFF so no embedder is required; the tool loop + PGOV
    structural stages still run.
    """
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
        # Enough headroom for an optional think block + the tool call, and for
        # the post-tool final answer generation.
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


def test_native_tool_call_round_trip_with_grammar_live(
    engine: Any, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """The real 14B emits a NATIVE-format tool call and the loop completes.

    Strict mechanical assertions (model wording stays lenient):
      (a) at least one tool call PARSED during the turn;
      (b) the first parsed call is native JSON — the raw generation contains a
          ``<tool_call>{`` payload AND no LEGACY-fallback warning fired;
      (c) no fail-closed malformed-payload drop fired (with grammar ON a
          malformed emission should be impossible — a drop here is a red flag);
      (d) the parsed tool is a clock tool, it DISPATCHED through the real
          registry, and its result is a non-empty string;
      (e) the turn produced response frames (the loop reached a final answer).
    """
    import services.assistant_orchestrator.src.tools as tools_mod

    service = _make_service_with(engine)

    parsed_calls: list[tuple[str, str]] = []
    raw_generations: list[str] = []
    real_parse = tools_mod.parse_tool_call

    def _spy_parse(text: str) -> tuple[str, str] | None:
        raw_generations.append(text)
        result = real_parse(text)
        if result is not None:
            parsed_calls.append(result)
        return result

    executed: list[tuple[str, str, str]] = []
    real_execute = tools_mod.execute

    def _spy_execute(tool_name: str, args: str = "") -> str:
        result = real_execute(tool_name, args)
        executed.append((tool_name, args, result))
        return result

    monkeypatch.setattr(tools_mod, "parse_tool_call", _spy_parse)
    monkeypatch.setattr(tools_mod, "execute", _spy_execute)

    turn_start = time.perf_counter()
    with caplog.at_level("WARNING"):
        transport = _drive(
            service,
            session_id="harness-tool-rt",
            prompt="What time is it right now?",
            request_id="r-tool-rt",
        )
    turn_ms = (time.perf_counter() - turn_start) * 1000.0

    # (e) The turn completed and streamed frames back.
    assert transport.sent, "the tool round-trip turn produced no response frames"

    # (a) A tool call parsed during the turn.
    assert parsed_calls, (
        "the real model emitted NO parseable tool call for a direct time "
        f"question — raw generations: {raw_generations!r}"
    )

    # (b) Native-format emission: the generation that carried the first parsed
    # call used the JSON payload form, and the legacy transition fallback never
    # fired anywhere in the turn.
    joined_warnings = " ".join(rec.getMessage() for rec in caplog.records)
    assert "LEGACY tool-call form used" not in joined_warnings, (
        "the model fell back to the retired homemade NAME(args) form — the "
        f"native-format migration did not take: {joined_warnings}"
    )
    native_seen = any("<tool_call>{" in text.replace(" ", "") for text in raw_generations)
    assert native_seen, (
        "no native JSON <tool_call> payload observed in the raw generations: "
        f"{raw_generations!r}"
    )

    # (c) No fail-closed drop — with grammar ON, malformed emissions should be
    # structurally impossible.
    assert "dropped (fail-closed)" not in joined_warnings, (
        f"a tool-call payload was dropped fail-closed with grammar ON: "
        f"{joined_warnings}"
    )

    # (d) The parsed tool is a clock tool and it really dispatched.
    first_name, _first_args = parsed_calls[0]
    assert first_name in _CLOCK_TOOLS, (
        f"expected a clock tool for a time question, got {first_name!r}"
    )
    assert executed, "the parsed tool call never reached the registry dispatch"
    assert executed[0][0] == first_name
    assert executed[0][2].strip(), "the dispatched tool returned an empty result"

    print(f"{_TIMING_PREFIX} turn_total_ms={turn_ms:.1f}")
    print(f"{_TIMING_PREFIX} generations_in_loop={len(raw_generations)}")
    print(f"{_TIMING_PREFIX} tool={first_name} result={executed[0][2]!r}")
