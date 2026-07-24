"""
Web-Search Skill — Explicit /search Dispatch Entrypoint (W3).

Provides WebSearchSkill, a thin wrapper around run_web_search() that:
  1. Accepts an explicit /search <question> command string.
  2. Strips the /search prefix.
  3. Runs the agentic loop.
  4. Returns the final_answer string.

Intent-routing (transparent dispatch from the AO turn pipeline) is a
deliberately deferred enhancement — NOT built here (ADR-024 §6
question 3).  The system reaches the network ONLY when the user explicitly
invokes /search.

RELAY-GROUNDING CONTRACT (ADR-023 Amendment 3, #913) — READ BEFORE WIRING
------------------------------------------------------------------------
The agentic loop (run_web_search) runs entirely on a standalone SearchState:
it fetches, injection-scans (#896), datamarks (#909), and synthesises a
final answer WITHOUT ever touching the operator's ContextManager session.
That answer is derived wholly from UNTRUSTED web content.  If it is relayed
back into the operator's session as plain assistant text, the session's
``has_untrusted_content`` flag never flips — so a prompt-injection that
survived both the datamark and the scan could fire a tool on the operator's
NEXT turn (the Layer-3 action-lock would not be armed).  The web_search TOOL
path avoids this because it grounds its results ``UNTRUSTED_WEB`` via
``add_grounded_context`` (entrypoint.py ~6170), which arms the lock.

Therefore the ONLY sanctioned operator-facing relay is the GROUNDED entry
point — ``handle_search_command_grounded`` / ``WebSearchSkill.handle_grounded``
— which grounds the answer ``UNTRUSTED_WEB`` into the operator session before
returning it, mirroring the tool path and fail-closed (a grounding failure
WITHHOLDS the answer rather than relay it ungrounded).  The raw ``handle`` /
``handle_search_command`` return an UNGROUNDED string and are loop drivers for
tests/scripts ONLY — never a direct operator-session relay.

AO COMMAND-ROUTER REGISTRATION SEAM
-------------------------------------
The live AO command-router wires explicit user commands to skill handlers
via a register() call on the AO's tool/skill registry.  The seam below
shows where W3's WebSearchSkill plugs in — this one-liner is intentionally
NOT wired to the live pipeline here; it is the job of the AO entrypoint
integrator (a separate PR / sprint task) to call it.  register() wires the
GROUNDED handler (it requires the operator ContextManager) so the relay
cannot be wired ungrounded by copying the seam.

    # In AO entrypoint or skill-loader (DO NOT add here — W3 only):
    # from services.assistant_orchestrator.src.websearch.dispatch import register
    # register(command_router, adapter=LiveKagiAdapter(...), llm=ao_inference,
    #          context=ao.context_manager)

Keep W3 to new files under websearch/.  Do NOT import from or modify
services/assistant_orchestrator/src/entrypoint.py here.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Protocol

from services.assistant_orchestrator.src.websearch.adapter import KagiAdapter
from services.assistant_orchestrator.src.websearch.loop import LLMText, run_web_search
from services.assistant_orchestrator.src.websearch.state import (
    SearchState,
    WebSearchConfig,
)

if TYPE_CHECKING:
    from services.assistant_orchestrator.src.context_manager import Provenance

_LOG = logging.getLogger(__name__)

_COMMAND_PREFIX: str = "/search"

#: Deterministic, content-free notices this module may return in place of a
#: synthesised answer.  These carry NO web content, so the grounded relay must
#: NOT ground them (grounding them would arm the Layer-3 lock spuriously on a
#: benign "nothing happened" message).  Exact-match membership — the same
#: fail-closed shape ``tools.is_retrieval_notice`` uses on the tool path:
#: anything NOT in this set that rode real web learnings is grounded.
EMPTY_QUESTION_NOTICE: str = "[web-search: empty question — nothing to search]"

#: Returned by the GROUNDED relay when a content-bearing answer could not be
#: grounded ``UNTRUSTED_WEB`` (add_grounded_context returned False or raised).
#: Fail-closed: the web-derived answer is WITHHELD, never relayed ungrounded —
#: an ungrounded relay would leave the session's action-lock disarmed.
GROUNDING_WITHHELD_NOTICE: str = (
    "[web-search: result withheld — it could not be safely grounded as "
    "untrusted web content, so it was not relayed]"
)


class GroundingContext(Protocol):
    """Narrow structural type for the operator session's ContextManager.

    Only the two methods the grounded relay needs are declared, so this
    module never imports the concrete ContextManager (matching loop.py's
    narrow-Protocol dependency-injection discipline).  The real
    ``services.assistant_orchestrator.src.context_manager.ContextManager``
    satisfies it; tests drive a real ContextManager through this seam.
    """

    def add_grounded_context(
        self,
        session_id: str,
        chunks: list[str],
        recent_document: str = ...,
        source: str = ...,
        provenance: "Provenance | None" = ...,
    ) -> bool:
        """Ground chunks with datamarking + provenance; True on success."""
        ...

    def has_untrusted_content(self, session_id: str) -> bool:
        """The Layer-3 gate signal — True once untrusted content is grounded."""
        ...


# ---------------------------------------------------------------------------
# WebSearchSkill
# ---------------------------------------------------------------------------


class WebSearchSkill:
    """Explicit /search <question> skill handler.

    Instantiate once at app startup with a KagiAdapter and an LLMText
    implementation (MockKagiAdapter + MockLLM in W3; LiveKagiAdapter +
    OrchestratorGPUInference in W4+).

    All network calls go through the adapter; zero network calls are made
    directly by this class.

    Args:
        adapter: KagiAdapter implementation.
        llm:     LLMText implementation (real or mock 14B).
        config:  Optional WebSearchConfig (uses defaults if None).
    """

    def __init__(
        self,
        adapter: KagiAdapter,
        llm: LLMText,
        config: WebSearchConfig | None = None,
    ) -> None:
        self._adapter = adapter
        self._llm = llm
        self._config = config or WebSearchConfig()

    async def handle(self, command: str) -> str:
        """Run a /search command and return the RAW, UNGROUNDED answer string.

        Strips the /search prefix (case-insensitive), runs run_web_search(),
        and returns the final_answer string.

        WARNING — NOT an operator-session relay (ADR-023 Am.3, #913): the
        returned string is UNGROUNDED web-derived content.  Relaying it into
        an operator's ContextManager session as-is leaves the Layer-3
        action-lock disarmed, so an injection surviving the datamark + scan
        could fire a tool on the next turn.  Operator relay MUST go through
        :meth:`handle_grounded`.  This method is a loop driver for
        tests/scripts only.

        Fail-closed: any exception returns an error message string; the
        caller's session is never interrupted.

        Args:
            command: The raw command string, e.g. "/search what is OpenVINO?"
                     May optionally omit the /search prefix if the caller
                     pre-stripped it.

        Returns:
            The synthesised answer string, or an error message.
        """
        question = _extract_question(command)
        if not question:
            return EMPTY_QUESTION_NOTICE

        _LOG.info("WebSearchSkill: running search for question=%r", question[:120])
        try:
            state: SearchState = await run_web_search(
                question=question,
                adapter=self._adapter,
                llm=self._llm,
                config=self._config,
            )
            return state.final_answer
        except Exception as exc:  # noqa: BLE001
            _LOG.exception("WebSearchSkill.handle: unhandled exception")
            return f"[web-search error: {type(exc).__name__}]"

    async def handle_grounded(
        self,
        command: str,
        context: GroundingContext,
        session_id: str,
    ) -> str:
        """Run a /search command and relay the answer GROUNDED ``UNTRUSTED_WEB``.

        The sanctioned operator-facing relay (ADR-023 Am.3, #913).  Delegates
        to :func:`handle_search_command_grounded` with this skill's adapter,
        llm, and config — see that function for the full grounding + fail-closed
        contract.

        Args:
            command:    The raw /search command string.
            context:    The operator session's ContextManager (grounding sink).
            session_id: The operator session id to arm the Layer-3 lock on.

        Returns:
            The grounded answer, a content-free notice, or the withheld notice
            (fail-closed) — never an ungrounded web-derived answer.
        """
        return await handle_search_command_grounded(
            command,
            adapter=self._adapter,
            llm=self._llm,
            context=context,
            session_id=session_id,
            config=self._config,
        )

    def handle_sync(self, command: str) -> str:
        """Synchronous wrapper around handle() for non-async callers.

        WARNING — UNGROUNDED RELAY (like its sibling ``handle``): wraps the raw
        ``handle`` and returns the synthesised answer WITHOUT grounding it
        UNTRUSTED_WEB into any operator session, so a caller that relays this
        into a live turn leaves the Layer-3 action-lock disarmed. Any live
        wiring MUST go through ``register`` (which requires a ContextManager and
        wires the grounded relay) or call ``handle_grounded`` — never this
        directly on a production path (#913). No production caller exists today.

        Args:
            command: The raw command string.

        Returns:
            The synthesised answer string, or an error message.
        """
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # Already in an async context — callers should use handle() directly.
                # As a best-effort fallback, create a nested task via asyncio.run_coroutine_threadsafe.
                import concurrent.futures
                future = asyncio.run_coroutine_threadsafe(self.handle(command), loop)
                return future.result(timeout=120)
            return loop.run_until_complete(self.handle(command))
        except Exception as exc:  # noqa: BLE001
            return f"[web-search error: {type(exc).__name__}]"


# ---------------------------------------------------------------------------
# Convenience top-level coroutine (functional API)
# ---------------------------------------------------------------------------


async def handle_search_command(
    command: str,
    adapter: KagiAdapter,
    llm: LLMText,
    config: WebSearchConfig | None = None,
) -> str:
    """Run the search loop for a /search command; return the RAW answer string.

    Equivalent to WebSearchSkill(adapter, llm, config).handle(command) but
    without instantiating the class — useful for one-off invocations in
    tests and scripts.

    WARNING — NOT an operator-session relay (ADR-023 Am.3, #913): the returned
    string is UNGROUNDED web-derived content.  For operator relay use
    :func:`handle_search_command_grounded`, which grounds the answer
    ``UNTRUSTED_WEB`` so the Layer-3 action-lock is armed.

    Fail-closed: returns an error string on any exception.

    Args:
        command: The raw command string (with or without /search prefix).
        adapter: KagiAdapter implementation.
        llm:     LLMText implementation.
        config:  Optional WebSearchConfig.

    Returns:
        The synthesised answer string, or an error message.
    """
    question = _extract_question(command)
    if not question:
        return EMPTY_QUESTION_NOTICE
    try:
        state = await run_web_search(
            question=question,
            adapter=adapter,
            llm=llm,
            config=config,
        )
        return state.final_answer
    except Exception as exc:  # noqa: BLE001
        _LOG.exception("handle_search_command: unhandled exception")
        return f"[web-search error: {type(exc).__name__}]"


async def handle_search_command_grounded(
    command: str,
    adapter: KagiAdapter,
    llm: LLMText,
    context: GroundingContext,
    session_id: str,
    config: WebSearchConfig | None = None,
) -> str:
    """Run a /search command and relay the answer GROUNDED ``UNTRUSTED_WEB``.

    The sanctioned operator-facing relay (ADR-023 Am.3, #913). It mirrors the
    web_search TOOL path: any answer synthesised from real fetched web content
    is grounded ``UNTRUSTED_WEB`` into the operator's session via
    ``add_grounded_context`` BEFORE it is returned, so it is datamarked +
    provenance-tracked and ``has_untrusted_content(session_id)`` flips True —
    arming the Layer-3 action-lock so an injection that survived the datamark
    (#909) + injection scan (#896) cannot fire a tool on the operator's NEXT
    turn.

    Grounding decision is STRUCTURAL, not string-sniffing: the answer is
    grounded iff the loop actually extracted web learnings
    (``state.all_learnings`` non-empty). The content-free paths — empty
    question, decomposition/synthesis producing nothing, a loop crash — carry
    no untrusted web content and are returned WITHOUT grounding (so a benign
    "nothing happened" notice never arms the lock spuriously), exactly as the
    tool path skips its deterministic ``is_retrieval_notice`` strings.

    Fail-closed (the security-critical branch): if a content-bearing answer
    CANNOT be grounded (``add_grounded_context`` returns False or raises), the
    answer is WITHHELD — :data:`GROUNDING_WITHHELD_NOTICE` is returned in its
    place, never the ungrounded web-derived text. An ungrounded relay would
    leave the action-lock disarmed, which is precisely the gap this closes.

    Args:
        command:    The raw /search command string.
        adapter:    KagiAdapter implementation.
        llm:        LLMText implementation.
        context:    The operator session's ContextManager (grounding sink).
        session_id: The operator session id whose Layer-3 lock this arms.
        config:     Optional WebSearchConfig.

    Returns:
        The grounded answer, a content-free notice, or the withheld notice —
        never an ungrounded web-derived answer.
    """
    # Provenance is imported lazily (loop.py's dependency-injection idiom) so
    # this module carries no module-load dependency on context_manager.
    from services.assistant_orchestrator.src.context_manager import Provenance

    question = _extract_question(command)
    if not question:
        return EMPTY_QUESTION_NOTICE

    _LOG.info(
        "handle_search_command_grounded: running search for question=%r "
        "(session=%s)", question[:120], session_id,
    )
    try:
        state = await run_web_search(
            question=question,
            adapter=adapter,
            llm=llm,
            config=config,
        )
    except Exception as exc:  # noqa: BLE001 — fail-closed: no content escaped
        _LOG.exception("handle_search_command_grounded: unhandled exception")
        return f"[web-search error: {type(exc).__name__}]"

    answer = state.final_answer
    if not _relay_grounds_answer(state):
        # Content-free path (no web learnings extracted): nothing untrusted to
        # ground, so return the answer/notice as-is — arming the lock here would
        # be a spurious lock on a benign message.
        return answer

    # Content-bearing answer: it was synthesised from untrusted web content, so
    # it MUST be grounded UNTRUSTED_WEB into the operator session before relay.
    try:
        grounded = context.add_grounded_context(
            session_id,
            [answer],
            provenance=Provenance.UNTRUSTED_WEB,
        )
    except Exception as exc:  # noqa: BLE001 — fail-closed below
        _LOG.error(
            "handle_search_command_grounded: grounding the web answer for "
            "session=%s raised (%s) — WITHHOLDING (fail-closed; ungrounded "
            "web-derived text is never relayed).", session_id, exc,
        )
        return GROUNDING_WITHHELD_NOTICE
    if not grounded:
        _LOG.error(
            "handle_search_command_grounded: grounding the web answer for "
            "session=%s returned False — WITHHOLDING (fail-closed).", session_id,
        )
        return GROUNDING_WITHHELD_NOTICE
    return answer


def _relay_grounds_answer(state: SearchState) -> bool:
    """Return True iff the /search answer must be grounded ``UNTRUSTED_WEB``.

    Structural signal (not string-sniffing): the loop extracted at least one
    web learning, so the synthesised answer was built from untrusted web
    content and must arm the operator-session action-lock on relay. Every
    content-free loop outcome (no queries, no output, a crash) leaves
    ``all_learnings`` empty and no untrusted content ever reached synthesis.
    """
    return bool(state.all_learnings)


# ---------------------------------------------------------------------------
# AO command-router registration seam (documentation only — W3)
# ---------------------------------------------------------------------------


def register(
    command_router: object,  # type: ignore[misc]  # AO CommandRouter type (not imported here)
    adapter: KagiAdapter,
    llm: LLMText,
    context: GroundingContext,
    config: WebSearchConfig | None = None,
) -> None:
    """SEAM: Register the web-search skill with the AO command router.

    This function is the one-line integration point between the W3 skill
    and the live AO pipeline.  It is intentionally NOT called from any
    production code in W3.  The AO entrypoint integrator calls it in a
    separate task/sprint after W4 security gating is complete.

    It wires the GROUNDED handler (ADR-023 Am.3, #913): the registered
    handler takes ``(command, session_id)`` and grounds the answer
    ``UNTRUSTED_WEB`` into ``context`` before returning it, so copying this
    seam cannot produce an ungrounded operator relay.  ``context`` is a
    REQUIRED argument for exactly that reason — there is no seam that relays
    without a grounding sink.

    Usage (from AO entrypoint — NOT here):
        from services.assistant_orchestrator.src.websearch.dispatch import register
        register(ao.command_router, adapter=LiveKagiAdapter(...),
                 llm=ao_inference, context=ao.context_manager)

    This keeps W3 entirely within the websearch/ package — zero changes to
    existing AO files.

    Args:
        command_router: The AO CommandRouter instance (type elided to avoid
                        importing the live AO module here).
        adapter:        KagiAdapter to use for live search calls.
        llm:            LLMText implementation (OrchestratorGPUInference in prod).
        context:        The operator session's ContextManager (grounding sink);
                        REQUIRED so the relay arms the Layer-3 lock.
        config:         Optional WebSearchConfig.

    Raises:
        AttributeError: If command_router does not have a ``register`` method.
    """
    skill = WebSearchSkill(adapter=adapter, llm=llm, config=config)

    async def _grounded_handler(command: str, session_id: str) -> str:
        # The blessed relay: grounds UNTRUSTED_WEB into the operator session
        # (fail-closed), never the raw ungrounded skill.handle.
        return await skill.handle_grounded(command, context, session_id)

    # The AO CommandRouter is expected to have a .register(prefix, handler) method.
    # Handler signature: async def handler(command: str, session_id: str) -> str
    command_router.register(_COMMAND_PREFIX, _grounded_handler)  # type: ignore[attr-defined]
    _LOG.info(
        "WebSearchSkill registered (grounded relay) for command prefix %r",
        _COMMAND_PREFIX,
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _extract_question(command: str) -> str:
    """Strip the /search prefix (case-insensitive) and return the question.

    Args:
        command: Raw command string from the user or dispatcher.

    Returns:
        The question string with leading/trailing whitespace stripped.
        Empty string if nothing remains after stripping the prefix.
    """
    stripped = command.strip()
    lower = stripped.lower()
    if lower.startswith(_COMMAND_PREFIX):
        question = stripped[len(_COMMAND_PREFIX):].strip()
    else:
        question = stripped
    return question
