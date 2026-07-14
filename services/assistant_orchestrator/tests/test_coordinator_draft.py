"""Locks for coordinator_draft() — the C3 heartbeat drafting adapter
(#845 limb 5, design §3.3 wall 4 / §3.4).

Seam-real by construction: every test drives the REAL
``AssistantOrchestratorService.coordinator_draft`` entry through a REAL
``OrchestratorGPUInference`` attached to a REAL ``SharedInferencePipeline``
with its REAL ``threading.Lock`` — only the raw OpenVINO pipeline object is a
mock (the established ``test_gpu_inference`` idiom). The busy path holds the
actual lock; the not-resident path performs the actual UC-010 eviction
(``unload()``); the residency/lock claims are proven against the objects that
carry them in production, not against stand-ins.

The keyed locks (#845):
  * busy-defers        — lock held ⇒ ``busy``, ZERO model calls.
  * not_resident-defers — evicted 14B ⇒ ``not_resident``, ZERO load/reload
    calls (the rebuild closure — THE load path — is never consulted).
  * drafted            — lock free + resident ⇒ EXACTLY ONE bounded,
    deterministic model call.
  * grammar fail-soft  — an unavailable json-schema constraint degrades to
    the one plain bounded generation (#743), named in ``reason``, no raise.
  * lock-always-released — every path, including exceptions, leaves the
    single-flight lock free.
  * dormancy           — no production code path calls the adapter.
"""

from __future__ import annotations

import threading
from pathlib import Path
from unittest.mock import MagicMock, patch

from services.assistant_orchestrator.src.entrypoint import (
    _COORDINATOR_DRAFT_MAX_NEW_TOKENS,
    _COORDINATOR_DRAFT_SYSTEM_PROMPT,
    AssistantOrchestratorService,
)
from services.assistant_orchestrator.src.gpu_inference import (
    OrchestratorGPUInference,
)
from shared.coordinator.drafting import DraftStatus
from shared.inference.shared_pipeline import SharedInferencePipeline

_REPO_ROOT = Path(__file__).resolve().parents[3]


def _make_service(
    *,
    raw_text: str = "The dispatch finished green and merged.",
    rebuild: "MagicMock | None" = None,
) -> tuple[AssistantOrchestratorService, MagicMock, SharedInferencePipeline]:
    """A real service + real engine + real wrapper; only the raw ov pipeline
    is fake. Returns (service, raw_pipeline_mock, wrapper)."""
    raw = MagicMock()
    raw.generate.return_value = raw_text
    wrapper = SharedInferencePipeline(raw, threading.Lock(), rebuild=rebuild)
    engine = OrchestratorGPUInference(model_dir="/mock", shared_pipeline=wrapper)
    engine._loaded = True
    engine._pipeline = wrapper  # what load_model() does on the shared path
    engine._tokenizer = None  # manual ChatML fallback; token count word-splits
    service = AssistantOrchestratorService("dummy.toml")
    service._inference = engine
    return service, raw, wrapper


def _lock_is_free(wrapper: SharedInferencePipeline) -> bool:
    got = wrapper._lock.acquire(blocking=False)
    if got:
        wrapper._lock.release()
    return got


class TestBusyDefers:
    def test_lock_held_returns_busy_with_zero_model_calls(self) -> None:
        """The busy-defers lock: anything holding the single-flight lock (a
        chat turn, a PA classification) ⇒ ``busy`` immediately — no wait, no
        queue, no model call."""
        service, raw, wrapper = _make_service()

        assert wrapper._lock.acquire(blocking=False)  # simulate an in-flight turn
        try:
            result = service.coordinator_draft("Summarize the finished run.")
        finally:
            wrapper._lock.release()

        assert result.status is DraftStatus.BUSY
        assert not result.has_text
        assert "lock held" in result.reason
        raw.generate.assert_not_called()  # zero model calls
        assert _lock_is_free(wrapper)  # the holder's lock survives; then freed


class TestNotResidentDefers:
    def test_evicted_14b_defers_and_never_loads(self) -> None:
        """The not_resident-defers lock, driven through the REAL eviction
        bookkeeping: after ``unload()`` (the UC-010 image-gen path) the lock
        is FREE but the 14B is absent — the adapter must report
        ``not_resident`` and never touch the load path (the wrapper's rebuild
        closure) nor the engine's ``load_model``."""
        rebuild = MagicMock()
        service, raw, wrapper = _make_service(rebuild=rebuild)
        wrapper.unload()  # the real eviction: _pipeline -> None, lock released
        assert not wrapper.is_loaded

        with patch.object(
            service._inference, "load_model", wraps=service._inference.load_model
        ) as load_spy:
            result = service.coordinator_draft("Summarize the finished run.")

        assert result.status is DraftStatus.NOT_RESIDENT
        assert not result.has_text
        assert "not positively resident" in result.reason
        raw.generate.assert_not_called()  # zero model calls
        rebuild.assert_not_called()  # THE load path — never consulted
        load_spy.assert_not_called()
        assert not wrapper.is_loaded  # still evicted: no load was initiated
        assert _lock_is_free(wrapper)

    def test_no_shared_wrapper_is_a_not_resident_defer(self) -> None:
        """Standalone topology (no SharedInferencePipeline): there is no
        single-flight seam to try-acquire, so drafting defers rather than
        generating outside the sanctioned seam."""
        engine = OrchestratorGPUInference(model_dir="/mock")  # no wrapper
        engine._loaded = True
        engine._pipeline = MagicMock()
        service = AssistantOrchestratorService("dummy.toml")
        service._inference = engine

        result = service.coordinator_draft("p")

        assert result.status is DraftStatus.NOT_RESIDENT
        engine._pipeline.generate.assert_not_called()

    def test_inference_not_constructed_is_a_not_resident_defer(self) -> None:
        """A service whose start() never ran (``_inference is None``) defers —
        the adapter never constructs or loads anything."""
        service = AssistantOrchestratorService("dummy.toml")
        result = service.coordinator_draft("p")
        assert result.status is DraftStatus.NOT_RESIDENT
        assert not result.has_text


class TestDraftedPath:
    def test_exactly_one_bounded_deterministic_model_call(self) -> None:
        """The drafted lock: lock free + 14B resident ⇒ exactly ONE model
        call, greedy (``do_sample=False``), caller-bounded token cap, the
        no-tools /no_think drafting persona — and the drafted text back."""
        service, raw, wrapper = _make_service(raw_text="Run 42 merged clean.")

        result = service.coordinator_draft(
            "Summarize the finished run.", max_new_tokens=64
        )

        assert result.status is DraftStatus.DRAFTED
        assert result.text == "Run 42 merged clean."
        assert result.has_text
        assert raw.generate.call_count == 1  # exactly one bounded call
        prompt_arg, gen_config = raw.generate.call_args.args
        assert "Summarize the finished run." in prompt_arg
        assert _COORDINATOR_DRAFT_SYSTEM_PROMPT in prompt_arg  # the persona rode along
        assert "/no_think" in _COORDINATOR_DRAFT_SYSTEM_PROMPT
        assert gen_config.do_sample is False  # greedy / temp-0 equivalent
        assert gen_config.max_new_tokens == 64  # caller's bound flowed through
        assert _lock_is_free(wrapper)

    def test_default_cap_applies(self) -> None:
        service, raw, _wrapper = _make_service()
        service.coordinator_draft("p")
        _prompt, gen_config = raw.generate.call_args.args
        assert gen_config.max_new_tokens == _COORDINATOR_DRAFT_MAX_NEW_TOKENS

    def test_hidden_think_blocks_are_stripped(self) -> None:
        """Drafted text is post-strip (ADR-012 §2.4) — internal reasoning
        never reaches the digest."""
        service, _raw, _wrapper = _make_service(
            raw_text="<think>internal chain</think>The queue is quiet."
        )
        result = service.coordinator_draft("p")
        assert result.status is DraftStatus.DRAFTED
        assert result.text == "The queue is quiet."
        assert "<think>" not in result.text

    def test_empty_emission_is_in_band_structured_failure(self) -> None:
        """A think-only/empty emission is a DRAFTED result with no text and a
        legible reason — the caller renders its deterministic fallback."""
        service, _raw, wrapper = _make_service(raw_text="<think>only</think>")
        result = service.coordinator_draft("p")
        assert result.status is DraftStatus.DRAFTED
        assert not result.has_text
        assert "deterministic fallback" in result.reason
        assert _lock_is_free(wrapper)


class TestGrammarFailSoft:
    def test_unavailable_constraint_degrades_to_one_plain_call(self) -> None:
        """The grammar-failure fail-soft lock (#743): a json-schema constraint
        that cannot be built degrades to the ONE plain bounded generation —
        structured result, degradation named in reason, no raise, no retry,
        lock released."""
        service, raw, wrapper = _make_service(raw_text="A plain draft.")

        with patch(
            "services.assistant_orchestrator.src.gpu_inference."
            "_build_json_schema_structured_output",
            return_value=None,
        ):
            result = service.coordinator_draft(
                "Render the proposal.", json_schema={"type": "string"}
            )

        assert result.status is DraftStatus.DRAFTED
        assert result.text == "A plain draft."
        assert "#743" in result.reason  # the degradation is named, not silent
        assert raw.generate.call_count == 1  # one call — never a retry loop
        assert _lock_is_free(wrapper)

    def test_generation_layer_failure_is_structured_never_a_raise(self) -> None:
        """A generation-layer crash (the #725-style constraint crash shape)
        comes back as an in-band structured failure — DRAFTED with empty text
        and the cause in reason — with the lock released."""
        service, raw, wrapper = _make_service()
        raw.generate.side_effect = RuntimeError("xgrammar stop-token crash")

        result = service.coordinator_draft("p")  # must not raise

        assert result.status is DraftStatus.DRAFTED
        assert not result.has_text
        assert "deterministic fallback" in result.reason
        assert raw.generate.call_count == 1  # no retry while (or after) holding the lock
        assert _lock_is_free(wrapper)


class TestLockAlwaysReleased:
    def test_hard_exception_inside_the_seam_releases_the_lock(self) -> None:
        """Even an exception past the generation layer's own converter (here:
        the compose step itself blowing up inside the locked section) must
        release the try-acquired lock and surface as an in-band structured
        failure — never a raise out of the seam."""
        service, _raw, wrapper = _make_service()

        with patch.object(
            service._inference,
            "_generate_from_prompt",
            side_effect=RuntimeError("boom"),
        ):
            result = service.coordinator_draft("p")

        assert result.status is DraftStatus.DRAFTED
        assert not result.has_text
        assert "fail-soft" in result.reason
        assert _lock_is_free(wrapper)

    def test_every_status_path_leaves_the_lock_free(self) -> None:
        service, raw, wrapper = _make_service()
        # drafted
        assert service.coordinator_draft("p").status is DraftStatus.DRAFTED
        assert _lock_is_free(wrapper)
        # not_resident (real eviction needs a rebuild closure; force directly)
        wrapper._pipeline = None
        assert service.coordinator_draft("p").status is DraftStatus.NOT_RESIDENT
        assert _lock_is_free(wrapper)
        # busy
        assert wrapper._lock.acquire(blocking=False)
        try:
            assert service.coordinator_draft("p").status is DraftStatus.BUSY
        finally:
            wrapper._lock.release()
        assert _lock_is_free(wrapper)
        assert raw.generate.call_count == 1  # only the drafted path generated


class TestDormancy:
    def test_no_production_code_path_calls_the_adapter(self) -> None:
        """DORMANT by construction (#845 limb 5): the heartbeat cycle limb is
        the only intended caller and does not exist yet — no production
        source may invoke ``.coordinator_draft(``. Tests are exempt."""
        offenders: list[str] = []
        for top in ("services", "launcher", "shared", "tools"):
            root = _REPO_ROOT / top
            if not root.is_dir():
                continue
            for path in root.rglob("*.py"):
                parts = {p.lower() for p in path.parts}
                if "tests" in parts or path.name.startswith("test_"):
                    continue
                try:
                    text = path.read_text(encoding="utf-8")
                except (OSError, UnicodeDecodeError):
                    continue
                for line_no, line in enumerate(text.splitlines(), start=1):
                    if ".coordinator_draft(" in line:
                        offenders.append(f"{path}:{line_no}: {line.strip()}")
        assert offenders == [], (
            "coordinator_draft() must stay DORMANT until the heartbeat cycle "
            f"limb wires it — production callers found:\n" + "\n".join(offenders)
        )
