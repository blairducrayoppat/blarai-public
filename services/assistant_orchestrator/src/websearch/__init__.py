"""
Web-Search Skill — public surface (W2 + W3).

W2 surface:
    KagiAdapter       -- abstract base class (two async methods)
    MockKagiAdapter   -- fixture-backed, zero network, for W1-W3 testing
    SearchResult      -- frozen dataclass, one Kagi search-result entry
    SummaryResult     -- frozen dataclass, one Kagi Summarizer response
    parse_kagi_search_response   -- pure parser: raw dict -> list[SearchResult]
    parse_kagi_summary_response  -- pure parser: raw dict -> SummaryResult

W3 surface:
    SearchState       -- mutable invocation state
    SourceLearning    -- distilled evidence from one source
    Citation          -- one cited reference in the final answer
    WebSearchConfig   -- loop configuration (max_passes, concurrency, etc.)
    LLMText           -- narrow Protocol for LLM dependency injection
    run_web_search    -- top-level async entry point for the agentic loop
    injection_scan    -- ADR-013 Layer-2 scan on fetched pages (live, #896)
    WebSearchSkill    -- explicit /search <question> skill handler
    handle_search_command -- functional async entry point (RAW, ungrounded)
    handle_search_command_grounded -- functional relay grounding UNTRUSTED_WEB
                                      (the sanctioned operator relay, #913)
"""

from __future__ import annotations

from services.assistant_orchestrator.src.websearch.types import (
    SearchResult,
    SummaryResult,
)
from services.assistant_orchestrator.src.websearch.adapter import (
    KagiAdapter,
    MockKagiAdapter,
    parse_kagi_search_response,
    parse_kagi_summary_response,
)
from services.assistant_orchestrator.src.websearch.state import (
    Citation,
    SearchState,
    SourceLearning,
    WebSearchConfig,
)
from services.assistant_orchestrator.src.websearch.loop import (
    LLMText,
    injection_scan,
    run_web_search,
)
from services.assistant_orchestrator.src.websearch.dispatch import (
    WebSearchSkill,
    handle_search_command,
    handle_search_command_grounded,
)

__all__ = [
    # W2
    "KagiAdapter",
    "MockKagiAdapter",
    "SearchResult",
    "SummaryResult",
    "parse_kagi_search_response",
    "parse_kagi_summary_response",
    # W3 state
    "Citation",
    "SearchState",
    "SourceLearning",
    "WebSearchConfig",
    # W3 loop
    "LLMText",
    "injection_scan",
    "run_web_search",
    # W3 dispatch
    "WebSearchSkill",
    "handle_search_command",
    "handle_search_command_grounded",
]
