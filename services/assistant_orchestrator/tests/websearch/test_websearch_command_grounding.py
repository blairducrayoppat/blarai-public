"""#913 — the /search COMMAND-dispatch relay grounds ``UNTRUSTED_WEB``.

WHY THIS EXISTS (ADR-023 Amendment 3, #909 independent review):
  The web_search TOOL path grounds its results ``UNTRUSTED_WEB`` (entrypoint
  ~6170), arming the Layer-3 action-lock so an injection surviving the
  datamark (#909) + scan (#896) cannot fire a tool on the operator's next
  turn. The explicit ``/search`` COMMAND path runs a self-contained
  ``run_web_search`` loop over a standalone SearchState that NEVER touches the
  operator's ContextManager, and its raw handlers return a plain,
  **ungrounded** answer string. Relaying that string to the operator would
  leave ``has_untrusted_content`` False — the exact gap #913 closes with the
  grounded relay (``handle_search_command_grounded`` /
  ``WebSearchSkill.handle_grounded`` / the grounded ``register`` seam).

Everything here is offline: MockKagiAdapter fixtures + a scripted MockLLM,
driven through a REAL ContextManager (the seam, not a mock of it).
``has_untrusted_content`` is the literal Layer-3 gate signal the AO tool loop
reads at entrypoint.py ~5980, so asserting it IS asserting the lock.

asyncio_mode=auto (pyproject.toml) — bare async def tests work.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

from services.assistant_orchestrator.src.context_manager import (
    ContextManager,
    Provenance,
)
from services.assistant_orchestrator.src.websearch.adapter import MockKagiAdapter
from services.assistant_orchestrator.src.websearch.state import WebSearchConfig
from services.assistant_orchestrator.src.websearch.types import (
    SearchResult,
    SummaryResult,
)
from services.assistant_orchestrator.src.websearch.dispatch import (
    EMPTY_QUESTION_NOTICE,
    GROUNDING_WITHHELD_NOTICE,
    WebSearchSkill,
    handle_search_command,
    handle_search_command_grounded,
    register,
)


# ---------------------------------------------------------------------------
# Minimal offline test doubles (mirrors the proven scripting in test_w3_loop)
# ---------------------------------------------------------------------------


@dataclass
class _MockGenerationResult:
    text: str


class _MockLLM:
    """Scripted LLMText — first prompt-substring match wins; else default."""

    def __init__(
        self, responses: dict[str, str] | None = None, default_text: str = ""
    ) -> None:
        self._responses = responses or {}
        self._default_text = default_text

    def generate_text(self, prompt: str, max_new_tokens: int) -> _MockGenerationResult:  # noqa: ARG002
        lower = prompt.lower()
        for key, resp in self._responses.items():
            if key.lower() in lower:
                return _MockGenerationResult(text=resp)
        return _MockGenerationResult(text=self._default_text)


def _content_rig() -> tuple[MockKagiAdapter, _MockLLM, WebSearchConfig]:
    """A rig whose loop extracts a real web learning (all_learnings non-empty),
    so the answer is content-bearing and MUST be grounded on relay."""
    adapter = MockKagiAdapter(
        search_fixture={
            "topic": [
                SearchResult(url="https://src.com", title="Src", snippet="s", rank=1)
            ]
        },
        summary_fixture={
            "https://src.com": SummaryResult(
                url="https://src.com", summary="OpenVINO is fast.", tokens_used=10
            )
        },
    )
    llm = _MockLLM(
        responses={
            "decompos": '["topic"]',
            "fact-summary": "Key info about OpenVINO.",
            "gap": '{"gaps": null}',
            "synthes": "OpenVINO is fast [1].\n\nReferences\n[1] Src — https://src.com",
        }
    )
    return adapter, llm, WebSearchConfig(max_passes=1)


def _no_content_rig() -> tuple[MockKagiAdapter, _MockLLM, WebSearchConfig]:
    """A rig whose decomposition yields no queries — the loop extracts NO
    learnings, so the answer is a content-free notice (nothing to ground)."""
    adapter = MockKagiAdapter()
    llm = _MockLLM(default_text="not a json array")  # decomposition -> []
    return adapter, llm, WebSearchConfig(max_passes=1)


class _CountingSink:
    """A GroundingContext double that records add_grounded_context calls and
    returns a scripted success flag (or raises)."""

    def __init__(self, *, result: bool = True, raise_exc: Exception | None = None) -> None:
        self._result = result
        self._raise = raise_exc
        self.calls: list[tuple[str, list[str], Any]] = []

    def add_grounded_context(
        self,
        session_id: str,
        chunks: list[str],
        recent_document: str = "",
        source: str = "document",
        provenance: Any = None,
    ) -> bool:
        self.calls.append((session_id, chunks, provenance))
        if self._raise is not None:
            raise self._raise
        return self._result

    def has_untrusted_content(self, session_id: str) -> bool:  # noqa: ARG002
        return False


class _FakeRouter:
    """Captures what register() wires — the AO CommandRouter seam."""

    def __init__(self) -> None:
        self.registered: dict[str, Any] = {}

    def register(self, prefix: str, handler: Any) -> None:
        self.registered[prefix] = handler


# ---------------------------------------------------------------------------
# The lock BLOCKS when engaged (grounded relay arms the Layer-3 action-lock)
# ---------------------------------------------------------------------------


class TestGroundedRelayArmsActionLock:
    async def test_grounded_relay_grounds_untrusted_web(self) -> None:
        """MUST-NOT-WEAKEN (#913): a content-bearing /search answer relayed via
        the grounded entry point lands UNTRUSTED_WEB in the operator session,
        flipping has_untrusted_content True — so a subsequent non-SAFE tool is
        Layer-3 locked, exactly like the web_search TOOL path."""
        adapter, llm, config = _content_rig()
        cm = ContextManager()
        cm.create_session("op")

        answer = await handle_search_command_grounded(
            "/search tell me about this topic",
            adapter=adapter,
            llm=llm,
            context=cm,
            session_id="op",
            config=config,
        )

        # The real synthesised answer is relayed (not withheld, not a notice).
        assert "[web-search" not in answer
        assert answer != GROUNDING_WITHHELD_NOTICE
        # The action-lock is ARMED: this is the exact signal entrypoint reads.
        assert cm.has_untrusted_content("op") is True
        assert Provenance.UNTRUSTED_WEB in cm.get_grounded_provenance("op")
        # ADR-023 Am.3: web content is EXEMPT from the Stage-5 leakage feed.
        assert cm.get_untrusted_chunk_texts("op") == []

    async def test_skill_handle_grounded_method_arms_lock(self) -> None:
        """Method parity: WebSearchSkill.handle_grounded arms the lock too."""
        adapter, llm, config = _content_rig()
        cm = ContextManager()
        cm.create_session("op")
        skill = WebSearchSkill(adapter=adapter, llm=llm, config=config)

        answer = await skill.handle_grounded("/search topic", cm, "op")

        assert answer != GROUNDING_WITHHELD_NOTICE
        assert cm.has_untrusted_content("op") is True
        assert Provenance.UNTRUSTED_WEB in cm.get_grounded_provenance("op")


# ---------------------------------------------------------------------------
# The probe FAILS when the control is OFF (principle 12 toggle)
# ---------------------------------------------------------------------------


class TestUngroundedRelayLeavesLockDisarmed:
    async def test_raw_handler_does_not_arm_lock(self) -> None:
        """TOGGLE (control OFF): the SAME search relayed via the RAW ungrounded
        handler leaves has_untrusted_content False — proving the grounding in
        the grounded relay is the load-bearing control, and demonstrating the
        exact gap #913 closes (an ungrounded relay would not arm the lock)."""
        adapter, llm, config = _content_rig()
        cm = ContextManager()
        cm.create_session("op")

        answer = await handle_search_command(
            "/search topic", adapter=adapter, llm=llm, config=config
        )

        # A real answer came back, but nothing was grounded into the session.
        assert "[web-search" not in answer
        assert cm.has_untrusted_content("op") is False
        assert cm.get_grounded_provenance("op") == []


# ---------------------------------------------------------------------------
# Fail-closed: a content-bearing answer that cannot be grounded is WITHHELD
# ---------------------------------------------------------------------------


class TestGroundingFailureIsFailClosed:
    async def test_grounding_returns_false_withholds_answer(self) -> None:
        """add_grounded_context returning False -> the web-derived answer is
        WITHHELD (never relayed ungrounded); the raw answer text must not leak
        through in its place."""
        adapter, llm, config = _content_rig()
        sink = _CountingSink(result=False)

        answer = await handle_search_command_grounded(
            "/search topic",
            adapter=adapter,
            llm=llm,
            context=sink,
            session_id="op",
            config=config,
        )

        assert answer == GROUNDING_WITHHELD_NOTICE
        assert "OpenVINO" not in answer  # the ungrounded answer did not leak
        # It genuinely TRIED to ground UNTRUSTED_WEB before withholding.
        assert len(sink.calls) == 1
        assert sink.calls[0][2] == Provenance.UNTRUSTED_WEB

    async def test_grounding_raises_withholds_answer(self) -> None:
        """add_grounded_context raising -> same fail-closed withhold, no leak."""
        adapter, llm, config = _content_rig()
        sink = _CountingSink(raise_exc=RuntimeError("grounding backend down"))

        answer = await handle_search_command_grounded(
            "/search topic",
            adapter=adapter,
            llm=llm,
            context=sink,
            session_id="op",
            config=config,
        )

        assert answer == GROUNDING_WITHHELD_NOTICE
        assert "OpenVINO" not in answer


# ---------------------------------------------------------------------------
# Content-free paths never arm the lock spuriously
# ---------------------------------------------------------------------------


class TestContentFreePathsDoNotGround:
    async def test_no_web_learnings_does_not_arm_lock(self) -> None:
        """No web learnings extracted (decomposition produced no queries) ->
        the content-free notice is returned WITHOUT grounding, so the lock is
        not armed spuriously and add_grounded_context is never called."""
        adapter, llm, config = _no_content_rig()
        sink = _CountingSink(result=True)

        answer = await handle_search_command_grounded(
            "/search topic",
            adapter=adapter,
            llm=llm,
            context=sink,
            session_id="op",
            config=config,
        )

        assert "[web-search" in answer  # a loop notice, not real content
        assert sink.calls == []  # nothing untrusted -> no grounding attempt

    async def test_empty_question_returns_notice_ungrounded(self) -> None:
        """An empty /search returns the empty-question notice and never grounds."""
        sink = _CountingSink(result=True)
        answer = await handle_search_command_grounded(
            "/search   ",
            adapter=MockKagiAdapter(),
            llm=_MockLLM(),
            context=sink,
            session_id="op",
        )
        assert answer == EMPTY_QUESTION_NOTICE
        assert sink.calls == []


# ---------------------------------------------------------------------------
# The register() seam wires the GROUNDED relay (built-and-wired-correctly)
# ---------------------------------------------------------------------------


class TestRegisterWiresGroundedRelay:
    async def test_registered_handler_grounds_untrusted_web(self) -> None:
        """The blessed AO seam: register() wires a (command, session_id) handler
        that grounds UNTRUSTED_WEB — copying the seam cannot yield an ungrounded
        relay because a grounding context is REQUIRED and the wired handler is
        the grounded one, never skill.handle."""
        adapter, llm, config = _content_rig()
        cm = ContextManager()
        cm.create_session("op")
        router = _FakeRouter()

        register(router, adapter=adapter, llm=llm, context=cm, config=config)

        assert "/search" in router.registered
        handler = router.registered["/search"]
        answer = await handler("/search topic", "op")

        assert answer != GROUNDING_WITHHELD_NOTICE
        assert cm.has_untrusted_content("op") is True
        assert Provenance.UNTRUSTED_WEB in cm.get_grounded_provenance("op")

    def test_register_requires_a_grounding_context(self) -> None:
        """register() cannot be called without a grounding sink — there is no
        seam that relays /search without one (structural, not by convention)."""
        adapter, llm, _ = _content_rig()
        with pytest.raises(TypeError):
            register(_FakeRouter(), adapter=adapter, llm=llm)  # type: ignore[call-arg]
