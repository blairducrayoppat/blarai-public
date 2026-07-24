"""
Web-Search Skill — SearchState and related types (W3).

This module owns all mutable and configuration state for a single
run_web_search() invocation plus the Citation and SourceLearning
types that carry evidence through the loop.

ADR-024 §2.4 — SearchState, §2.2 Step 4 — SourceLearning.
"""

from __future__ import annotations

from dataclasses import dataclass, field


# ---------------------------------------------------------------------------
# Immutable evidence types
# ---------------------------------------------------------------------------


@dataclass
class SourceLearning:
    """Distilled evidence from one fetched source page (Step 4b).

    The 14B's learning-extraction call compresses the raw extracted_text
    into a short ``learning`` string focused on the user's question.
    Only ``learning`` (and the provenance fields) enter the synthesis
    context — the raw text is retained for audit / W5 scan but is not
    injected into Step 6.

    Attributes:
        url:            Source URL.
        title:          Page title from the search result.
        extracted_text: Raw text returned by summarize_url() (pre-distil).
        learning:       14B-distilled fact-summary focused on the question.
        published:      ISO-8601 publication date if available, else None.
    """

    url: str
    title: str
    extracted_text: str
    learning: str
    published: str | None = None


@dataclass(frozen=True)
class Citation:
    """A single cited source in the final answer.

    Populated by the synthesis step (Step 6) and attached to
    SearchState.citations.  The index is 1-based (inline marker [N]).

    Attributes:
        index:  1-based citation number used in the final answer body.
        url:    Source URL.
        title:  Page title (from SearchResult or SourceLearning).
    """

    index: int
    url: str
    title: str


# ---------------------------------------------------------------------------
# Loop configuration
# ---------------------------------------------------------------------------


@dataclass
class WebSearchConfig:
    """Runtime configuration for a web-search invocation.

    All fields have sensible defaults so callers can omit the config
    entirely (run_web_search accepts ``config=None``).

    Attributes:
        max_passes:           Hard ceiling on loop iterations (initial pass
                              plus at most one follow-up by default).
        prefer_recent:        Bias triage toward results with a non-empty
                              published date (useful for version / event
                              questions).
        max_sources_per_pass: Cap on sources triaged per pass.
        use_summarizer:       If True, use Kagi Universal Summarizer for
                              content extraction; if False, use the snippet
                              from the search result or local fetch+extract
                              (zero marginal cost, W3 default).
        search_concurrency:   Max concurrent Kagi search calls (Semaphore).
        search_results_limit: Max results requested per search query call.
    """

    max_passes: int = 2
    prefer_recent: bool = False
    max_sources_per_pass: int = 5
    use_summarizer: bool = False
    search_concurrency: int = 3
    search_results_limit: int = 7


# ---------------------------------------------------------------------------
# Per-invocation mutable state
# ---------------------------------------------------------------------------


@dataclass
class SearchState:
    """All mutable state for one run_web_search() invocation.

    Instantiated at the top of run_web_search() and threaded through
    every step.  After the call returns, ``final_answer`` and
    ``citations`` carry the deliverable; callers should treat the rest
    as internal loop state.

    Attributes:
        question:             The user's original question.
        pass_count:           Number of search passes completed so far.
        max_passes:           Hard ceiling (copied from WebSearchConfig).
        prefer_recent:        Recency bias for triage (from config).
        max_sources_per_pass: Triage cap per pass (from config).
        use_summarizer:       Content-extraction mode flag (from config).
        queries:              Current list of search queries (updated each
                              pass — Step 1 fills it, Step 5 replaces it
                              on follow-up).
        all_learnings:        Accumulated SourceLearning objects across all
                              passes (deduplicated by URL at accumulation
                              time via visited_urls).
        visited_urls:         URLs already fetched in any pass — prevents
                              re-fetching the same source on a follow-up.
        final_answer:         Synthesised answer string (empty until Step 6
                              completes; set to an error message on failure).
        citations:            Ordered list of Citation objects referenced in
                              final_answer; empty on failure.
        session_token:        Per-session 8-hex datamark token (#909), minted
                              at search start and prefixed onto every line of
                              untrusted web content in the LLM prompts so an
                              injected instruction cannot masquerade as trusted
                              text. None only on the degraded/test path.
    """

    question: str
    pass_count: int = 0
    max_passes: int = 2
    prefer_recent: bool = False
    max_sources_per_pass: int = 5
    use_summarizer: bool = False
    queries: list[str] = field(default_factory=list)
    all_learnings: list[SourceLearning] = field(default_factory=list)
    visited_urls: set[str] = field(default_factory=set)
    final_answer: str = ""
    citations: list[Citation] = field(default_factory=list)
    session_token: str | None = None
