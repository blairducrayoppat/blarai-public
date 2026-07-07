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

AO COMMAND-ROUTER REGISTRATION SEAM
-------------------------------------
The live AO command-router wires explicit user commands to skill handlers
via a register() call on the AO's tool/skill registry.  The seam below
shows where W3's WebSearchSkill plugs in — this one-liner is intentionally
NOT wired to the live pipeline here; it is the job of the AO entrypoint
integrator (a separate PR / sprint task) to call it.

    # In AO entrypoint or skill-loader (DO NOT add here — W3 only):
    # from services.assistant_orchestrator.src.websearch.dispatch import register
    # register(command_router, adapter=LiveKagiAdapter(...), llm=ao_inference)

Keep W3 to new files under websearch/.  Do NOT import from or modify
services/assistant_orchestrator/src/entrypoint.py here.
"""

from __future__ import annotations

import asyncio
import logging

from services.assistant_orchestrator.src.websearch.adapter import KagiAdapter
from services.assistant_orchestrator.src.websearch.loop import LLMText, run_web_search
from services.assistant_orchestrator.src.websearch.state import (
    SearchState,
    WebSearchConfig,
)

_LOG = logging.getLogger(__name__)

_COMMAND_PREFIX: str = "/search"


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
        """Handle a /search command string and return the answer.

        Strips the /search prefix (case-insensitive), runs run_web_search(),
        and returns the final_answer string.

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
            return "[web-search: empty question — nothing to search]"

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

    def handle_sync(self, command: str) -> str:
        """Synchronous wrapper around handle() for non-async callers.

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
    """Functional entry point: run the search loop for a /search command.

    Equivalent to WebSearchSkill(adapter, llm, config).handle(command) but
    without instantiating the class — useful for one-off invocations in
    tests and scripts.

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
        return "[web-search: empty question — nothing to search]"
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


# ---------------------------------------------------------------------------
# AO command-router registration seam (documentation only — W3)
# ---------------------------------------------------------------------------


def register(
    command_router: object,  # type: ignore[misc]  # AO CommandRouter type (not imported here)
    adapter: KagiAdapter,
    llm: LLMText,
    config: WebSearchConfig | None = None,
) -> None:
    """SEAM: Register the web-search skill with the AO command router.

    This function is the one-line integration point between the W3 skill
    and the live AO pipeline.  It is intentionally NOT called from any
    production code in W3.  The AO entrypoint integrator calls it in a
    separate task/sprint after W4 security gating is complete.

    Usage (from AO entrypoint — NOT here):
        from services.assistant_orchestrator.src.websearch.dispatch import register
        register(ao.command_router, adapter=LiveKagiAdapter(...), llm=ao_inference)

    This keeps W3 entirely within the websearch/ package — zero changes to
    existing AO files.

    Args:
        command_router: The AO CommandRouter instance (type elided to avoid
                        importing the live AO module here).
        adapter:        KagiAdapter to use for live search calls.
        llm:            LLMText implementation (OrchestratorGPUInference in prod).
        config:         Optional WebSearchConfig.

    Raises:
        AttributeError: If command_router does not have a ``register`` method.
    """
    skill = WebSearchSkill(adapter=adapter, llm=llm, config=config)
    # The AO CommandRouter is expected to have a .register(prefix, handler) method.
    # Handler signature: async def handler(command: str) -> str
    command_router.register(_COMMAND_PREFIX, skill.handle)  # type: ignore[attr-defined]
    _LOG.info("WebSearchSkill registered for command prefix %r", _COMMAND_PREFIX)


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
