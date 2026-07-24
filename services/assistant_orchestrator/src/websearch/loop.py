"""
Web-Search Skill — Agentic Loop (W3).

Implements the 6-step search loop (ADR-024 §2.2, §2.4):

    decompose → [search → triage → extract+learn → gap-detect?]×N → synthesise

Entry point: run_web_search(question, adapter, llm, config) -> SearchState

Design constraints honoured here:
- The real 14B (OrchestratorGPUInference) is NEVER imported or loaded by
  this module. All calls go through the LLMText Protocol, which MockLLM
  satisfies in tests and OrchestratorGPUInference satisfies in production.
- Fail-closed: the top-level try/except catches all unhandled exceptions and
  returns a SearchState with final_answer set to an error string.
- LLM inference is serialised via llm_sem (asyncio.Semaphore(1)) to honour
  the single-GPU constraint (ADR-011).
- Kagi search calls are concurrently bounded by semaphore (default 3).
- All LLM calls are dispatched via asyncio.to_thread() because
  generate_text() is synchronous (blocking; runs on the GPU thread).
- No external network calls — the KagiAdapter interface is the only outbound
  surface; in W3 it is always MockKagiAdapter.

Untrusted-web defenses (ADR-024 §2.5 / ADR-013 — both LIVE):
  - injection_scan() — #896: the ADR-013 Layer-2 heuristic scanner runs on
    every fetched page before the learning-extraction LLM call
    (flagged/unscannable pages truncated to 500 chars).
  - Datamarking — #909: a per-session 8-hex token is minted at search start
    and prefixed onto every web-content line in the extraction + synthesis
    prompts, with a header telling the model to never obey marked lines
    (prompts._build_web_data_header / _mark_web_lines).
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import secrets
from typing import Protocol, runtime_checkable

from services.assistant_orchestrator.src.websearch.adapter import KagiAdapter
from services.assistant_orchestrator.src.websearch.types import (
    SearchResult,
    SummaryResult,
)
from services.assistant_orchestrator.src.websearch.state import (
    Citation,
    SearchState,
    SourceLearning,
    WebSearchConfig,
)
from services.assistant_orchestrator.src.websearch.prompts import (
    DECOMPOSITION_PROMPT_TEMPLATE,
    build_gap_detection_prompt,
    build_learning_extraction_prompt,
    build_synthesis_prompt,
)

_LOG = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# LLM Protocol — narrow dependency-injection surface
# ---------------------------------------------------------------------------


@runtime_checkable
class LLMText(Protocol):
    """Narrow typing Protocol for text generation.

    Both the real OrchestratorGPUInference and MockLLM (tests) must satisfy
    this interface. The loop calls generate_text() via asyncio.to_thread()
    because the real implementation is synchronous (blocking GPU call).

    The return type is intentionally loose (object) because
    OrchestratorGPUInference returns a GenerationResult dataclass — the loop
    only reads the ``.text`` attribute (str) from the return value, which is
    present on both the real GenerationResult and the MockLLM's return.

    Protocol contract:
        def generate_text(self, prompt: str, max_new_tokens: int) -> object:
            ...
            # return value must have a .text: str attribute

    Callers extract result.text (str) immediately after the await.
    """

    def generate_text(self, prompt: str, max_new_tokens: int) -> object:
        """Synchronous text generation call.

        Args:
            prompt:         The full prompt string.
            max_new_tokens: Maximum tokens to generate.

        Returns:
            An object with a ``.text: str`` attribute carrying the decoded
            model output.  Empty string on failure (fail-closed contract).
        """
        ...


# ---------------------------------------------------------------------------
# Injection scan (ADR-024 §2.5 / ADR-013 Layer 2 — live as of #896)
# ---------------------------------------------------------------------------

#: On a scan hit (or an unscannable page — see fail-closed note below), the
#: flagged summary is truncated to this many characters before the LLM sees it:
#: enough to show the title/intro, not enough to carry an injection buried in
#: the body (ADR-024 §2.5).
INJECTION_SCAN_TRUNCATE_CHARS: int = 500


def injection_scan(source: SummaryResult) -> SummaryResult:
    """Heuristic prompt-injection scan on one fetched page (ADR-024 §2.5).

    Runs the ADR-013 Layer-2 phrase scanner (:mod:`shared.security.injection_scan`
    — the same detector the document-load, guarded-fetch, and cleaner paths use)
    over ``source.summary`` BEFORE the learning-extraction LLM call. On a hit:

      - Logs a WARNING naming ``source.url`` and the matched pattern classes.
      - Returns a new :class:`SummaryResult` with ``summary`` truncated to
        :data:`INJECTION_SCAN_TRUNCATE_CHARS` characters.

    On no hit: returns *source* unchanged. The user is not interrupted for
    heuristic-only hits — this is one layer of defense-in-depth alongside the
    live datamarking, the Layer-3 tool-action lock, and the Stage-5 leakage
    screen (see #896 / #576).

    FAIL-CLOSED (never fail-open): if the scanner itself errors, the page is
    UNVERIFIABLE — it is treated as flagged (truncated) and an ERROR is logged
    loudly, never passed through unscanned. A page too short to truncate is
    still logged when flagged.

    Args:
        source: SummaryResult from KagiAdapter.summarize_url().

    Returns:
        *source* unchanged when clean; a truncated replacement when flagged or
        unscannable.
    """
    from shared.security.injection_scan import scan_for_injection

    try:
        hits = scan_for_injection(source.summary)
    except Exception as exc:  # noqa: BLE001 — an unscannable page must not pass unscanned
        _LOG.error(
            "web-search injection scan ERRORED on %s (%s: %s) — failing CLOSED: "
            "treating the page as flagged and truncating to %d chars.",
            source.url, type(exc).__name__, exc, INJECTION_SCAN_TRUNCATE_CHARS,
        )
        return SummaryResult(
            url=source.url,
            summary=source.summary[:INJECTION_SCAN_TRUNCATE_CHARS],
            tokens_used=source.tokens_used,
        )
    if not hits:
        return source
    _LOG.warning(
        "web-search injection scan FLAGGED %s (%s) — truncating the page to "
        "%d chars before the LLM sees it (ADR-024 §2.5).",
        source.url, "; ".join(hits), INJECTION_SCAN_TRUNCATE_CHARS,
    )
    return SummaryResult(
        url=source.url,
        summary=source.summary[:INJECTION_SCAN_TRUNCATE_CHARS],
        tokens_used=source.tokens_used,
    )


# ---------------------------------------------------------------------------
# JSON parsing helpers — fail-closed
# ---------------------------------------------------------------------------


def _parse_json_list(text: str) -> list[str]:
    """Parse a JSON array from LLM output. Returns [] on any failure.

    The 14B may wrap the array in prose or markdown fences; this function
    extracts the first JSON array it finds in the text, making it robust
    to common output noise.

    Args:
        text: Raw text from the 14B decomposition or gap response.

    Returns:
        A list[str] of query strings, or [] on parse failure.
    """
    if not text:
        return []
    # Strip markdown code fences if present.
    cleaned = re.sub(r"```(?:json)?\s*", "", text).strip()
    # Find first [...] block.
    match = re.search(r"\[.*?\]", cleaned, re.DOTALL)
    if not match:
        _LOG.debug("_parse_json_list: no JSON array found in: %r", text[:200])
        return []
    try:
        raw = json.loads(match.group())
        if not isinstance(raw, list):
            return []
        return [str(item) for item in raw if isinstance(item, str) and item.strip()]
    except json.JSONDecodeError as exc:
        _LOG.debug("_parse_json_list: JSON decode error: %s", exc)
        return []


def _parse_gap_result(text: str) -> list[str] | None:
    """Parse the gap-detection JSON from the 14B response.

    Returns:
        None   — if the model says coverage is sufficient ({"gaps": null}).
        list   — follow-up query strings if gaps exist.
        None   — on any parse failure (fail-closed: treat as sufficient).
    """
    if not text:
        return None
    cleaned = re.sub(r"```(?:json)?\s*", "", text).strip()
    # Find first {...} block.
    match = re.search(r"\{.*?\}", cleaned, re.DOTALL)
    if not match:
        _LOG.debug("_parse_gap_result: no JSON object found in: %r", text[:200])
        return None
    try:
        raw = json.loads(match.group())
        gaps = raw.get("gaps")
        if gaps is None:
            return None
        if isinstance(gaps, list):
            result = [str(q) for q in gaps if isinstance(q, str) and q.strip()]
            return result if result else None
        return None
    except json.JSONDecodeError as exc:
        _LOG.debug("_parse_gap_result: JSON decode error: %s", exc)
        return None


def _parse_synthesis_result(
    text: str,
    learnings: list[SourceLearning],
) -> tuple[str, list[Citation]]:
    """Extract answer text and citations from the synthesis response.

    The 14B produces inline [N] markers and a References section.  This
    parser extracts the citations by matching the References lines.

    Args:
        text:      Raw synthesis output from the 14B.
        learnings: All SourceLearning objects (used as fallback URL lookup).

    Returns:
        A tuple of (answer_text: str, citations: list[Citation]).
        On failure: (text, []) — return the raw text and empty citations.
    """
    if not text:
        return "", []

    # Split on "References" header (case-insensitive) to find citation block.
    parts = re.split(r"\n\s*(?:References?|Sources?)\s*:?\s*\n", text, flags=re.IGNORECASE)
    answer_text = parts[0].strip()
    citations: list[Citation] = []

    if len(parts) > 1:
        ref_block = parts[1]
        # Match lines like: [1] Title — URL  or  [1] URL
        for line in ref_block.splitlines():
            m = re.match(
                r"\[(\d+)\]\s+(.+?)(?:\s+[—–-]+\s+(https?://\S+))?$",
                line.strip(),
            )
            if m:
                idx = int(m.group(1))
                title_or_url = m.group(2).strip()
                url_part = m.group(3)
                if url_part:
                    citations.append(Citation(index=idx, url=url_part.strip(), title=title_or_url))
                else:
                    # Title contains the URL.
                    url_match = re.search(r"(https?://\S+)", title_or_url)
                    if url_match:
                        url = url_match.group(1)
                        title = title_or_url.replace(url, "").strip(" —–-")
                        citations.append(Citation(index=idx, url=url, title=title))

    return answer_text, citations


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------


def _format_learnings(learnings: list[SourceLearning]) -> str:
    """Format learnings for the gap-detection prompt (Step 5).

    Args:
        learnings: SourceLearning objects from all passes so far.

    Returns:
        A multi-line string with one numbered entry per learning.
    """
    if not learnings:
        return "(no findings yet)"
    lines: list[str] = []
    for i, sl in enumerate(learnings, start=1):
        lines.append(f"[{i}] {sl.title} ({sl.url})")
        lines.append(f"    {sl.learning[:500]}")
    return "\n".join(lines)


def _format_learnings_for_synthesis(learnings: list[SourceLearning]) -> str:
    """Format learnings for the synthesis prompt (Step 6).

    Includes source index, title, URL, and the distilled learning text.

    Args:
        learnings: All accumulated SourceLearning objects (all passes).

    Returns:
        A multi-line numbered block for injection into the synthesis prompt.
    """
    if not learnings:
        return "(no search findings available)"
    lines: list[str] = []
    for i, sl in enumerate(learnings, start=1):
        lines.append(f"[{i}] {sl.title}")
        lines.append(f"    URL: {sl.url}")
        lines.append(f"    {sl.learning}")
    return "\n".join(lines)


def _deduplicate_by_url(results: list[SearchResult]) -> list[SearchResult]:
    """Return results deduplicated by URL (first occurrence wins).

    Args:
        results: Flat list of SearchResult objects from multiple queries.

    Returns:
        Deduplicated list preserving original rank order.
    """
    seen: set[str] = set()
    deduped: list[SearchResult] = []
    for r in results:
        if r.url not in seen:
            seen.add(r.url)
            deduped.append(r)
    return deduped


# ---------------------------------------------------------------------------
# Step 1 — Query Decomposition
# ---------------------------------------------------------------------------


async def decompose_question(
    state: SearchState,
    llm: LLMText,
    llm_sem: asyncio.Semaphore,
) -> list[str]:
    """Step 1: 14B generates 2-4 search queries from the user's question.

    Uses /no_think mode (latency-sensitive planning call; extended
    reasoning does not help query decomposition — ADR-012 §2.4).

    Args:
        state:   Current SearchState (reads state.question).
        llm:     LLMText implementation (real or mock).
        llm_sem: Semaphore serialising LLM calls (single GPU).

    Returns:
        A list[str] of query strings.  Empty list on parse failure
        (fail-closed: caller exits loop early on empty queries).
    """
    prompt = DECOMPOSITION_PROMPT_TEMPLATE.format(question=state.question)
    async with llm_sem:
        result = await asyncio.to_thread(llm.generate_text, prompt, 256)
    queries = _parse_json_list(result.text)  # type: ignore[attr-defined]
    _LOG.debug("decompose_question: produced %d queries: %s", len(queries), queries)
    return queries


# ---------------------------------------------------------------------------
# Step 2 — Kagi Search
# ---------------------------------------------------------------------------


async def search_queries(
    queries: list[str],
    adapter: KagiAdapter,
    semaphore: asyncio.Semaphore,
    limit: int = 7,
) -> list[SearchResult]:
    """Step 2: Run queries concurrently through the Kagi adapter.

    Queries are dispatched concurrently up to the semaphore concurrency
    limit, then the results are flattened and deduplicated by URL.

    Args:
        queries:   List of query strings from decompose_question or gap-detect.
        adapter:   KagiAdapter (MockKagiAdapter in W3, LiveKagiAdapter in W4).
        semaphore: Concurrency limiter for outbound search calls.
        limit:     Max results per query (passed to adapter.search).

    Returns:
        Flat, URL-deduplicated list of SearchResult objects.
    """
    async def _one(q: str) -> list[SearchResult]:
        async with semaphore:
            return await adapter.search(q, limit=limit)

    batches = await asyncio.gather(*[_one(q) for q in queries])
    flat = [r for batch in batches for r in batch]
    deduped = _deduplicate_by_url(flat)
    _LOG.debug("search_queries: %d queries → %d deduplicated results", len(queries), len(deduped))
    return deduped


# ---------------------------------------------------------------------------
# Step 3 — Source Triage
# ---------------------------------------------------------------------------


def triage_sources(
    results: list[SearchResult],
    state: SearchState,
) -> list[SearchResult]:
    """Step 3: Filter and cap search results for content extraction.

    Triage rules (applied in order):
      1. Filter out result_type==1 (Kagi related-search suggestions, not
         real web results — ADR §2.2 Step 3).
      2. If state.prefer_recent is True, sort results with a non-empty
         ``published`` date first (stable sort).
      3. Cap at state.max_sources_per_pass.

    Args:
        results: SearchResult objects from search_queries (already deduped
                 and filtered for visited URLs by the main loop).
        state:   SearchState (reads prefer_recent and max_sources_per_pass).

    Returns:
        A list of at most max_sources_per_pass SearchResult objects.
    """
    # Rule 1: remove related-search suggestion entries.
    real_results = [r for r in results if r.result_type != 1]

    # Rule 2: recency bias — stable sort (results already have rank order).
    if state.prefer_recent:
        real_results.sort(key=lambda r: (r.published is None, r.rank))

    # Rule 3: cap.
    selected = real_results[: state.max_sources_per_pass]
    _LOG.debug(
        "triage_sources: %d → %d after triage (prefer_recent=%s, cap=%d)",
        len(results),
        len(selected),
        state.prefer_recent,
        state.max_sources_per_pass,
    )
    return selected


# ---------------------------------------------------------------------------
# Step 4 — Content Extraction (injection scan #896 + datamark #909)
# Step 4b — Learning Extraction (serialised LLM calls)
# ---------------------------------------------------------------------------


async def extract_learning_serialised(
    summary: SummaryResult,
    llm: LLMText,
    llm_sem: asyncio.Semaphore,
    question: str,
    search_result: SearchResult | None = None,
    session_token: str | None = None,
) -> SourceLearning:
    """Step 4b: 14B distils one source into a SourceLearning.

    LLM calls are serialised (llm_sem=Semaphore(1)) because the GPU is a
    single-threaded singleton (ADR-011).  Despite asyncio.gather() at the
    call site, each call blocks on the semaphore, so they run sequentially
    on the GPU.

    Args:
        summary:       SummaryResult from (scanned) KagiAdapter.summarize_url().
        llm:           LLMText implementation.
        llm_sem:       Semaphore serialising LLM calls.
        question:      The user's original question (context for the 14B).
        search_result: Optional SearchResult that produced this URL
                       (used for title fallback when summary has no title).
        session_token: Per-session datamark token (#909); prefixes every web
                       content line in the prompt. None on the degraded path.

    Returns:
        A SourceLearning.  learning is "No relevant information found." if
        the model produces no output (fail-closed).
    """
    title = (search_result.title if search_result else "") or summary.url
    content = summary.summary[:4096]  # hard truncation before injection (ADR §2.2 Step 4b)
    prompt = build_learning_extraction_prompt(
        question=question,
        url=summary.url,
        title=title,
        content=content,
        session_token=session_token,  # #909: datamark the web content lines
    )
    async with llm_sem:
        result = await asyncio.to_thread(llm.generate_text, prompt, 512)
    learning_text = result.text.strip()  # type: ignore[attr-defined]
    if not learning_text:
        learning_text = "No relevant information found."

    return SourceLearning(
        url=summary.url,
        title=title,
        extracted_text=summary.summary,
        learning=learning_text,
        published=search_result.published if search_result else None,
    )


# ---------------------------------------------------------------------------
# Step 5 — Gap Detection
# ---------------------------------------------------------------------------


async def detect_gaps(
    state: SearchState,
    learnings: list[SourceLearning],
    llm: LLMText,
    llm_sem: asyncio.Semaphore,
) -> list[str] | None:
    """Step 5: 14B evaluates whether follow-up queries are needed.

    Returns None if the hard pass ceiling has already been reached —
    the ceiling check is the first guard so the LLM is never called
    after max_passes is exhausted.

    Args:
        state:     SearchState (checks pass_count vs max_passes).
        learnings: All SourceLearning objects accumulated so far.
        llm:       LLMText implementation.
        llm_sem:   Semaphore serialising LLM calls.

    Returns:
        None  — if coverage is sufficient or max_passes reached.
        list  — follow-up query strings for the next pass.
    """
    if state.pass_count >= state.max_passes:
        _LOG.debug("detect_gaps: pass_count=%d >= max_passes=%d — skipping", state.pass_count, state.max_passes)
        return None
    prompt = build_gap_detection_prompt(
        question=state.question,
        learnings=_format_learnings(learnings),
        session_token=state.session_token,  # #911: datamark the findings block
    )
    async with llm_sem:
        result = await asyncio.to_thread(llm.generate_text, prompt, 256)
    follow_up = _parse_gap_result(result.text)  # type: ignore[attr-defined]
    _LOG.debug("detect_gaps: follow_up=%s", follow_up)
    return follow_up


# ---------------------------------------------------------------------------
# Step 6 — Synthesis
# ---------------------------------------------------------------------------


async def synthesise(
    state: SearchState,
    llm: LLMText,
    llm_sem: asyncio.Semaphore,
) -> tuple[str, list[Citation]]:
    """Step 6: 14B synthesises the cited final answer.

    Constructs the synthesis prompt from all accumulated learnings across
    all passes, calls the 14B, and parses the answer + citations.

    Args:
        state:   SearchState with all_learnings populated.
        llm:     LLMText implementation.
        llm_sem: Semaphore serialising LLM calls.

    Returns:
        Tuple of (answer_text: str, citations: list[Citation]).
        On failure: ("[web-search: synthesis failed]", []).
    """
    learnings_block = _format_learnings_for_synthesis(state.all_learnings)
    prompt = build_synthesis_prompt(
        question=state.question,
        learnings_block=learnings_block,
        session_token=state.session_token,  # #909: datamark the findings lines
    )
    async with llm_sem:
        result = await asyncio.to_thread(llm.generate_text, prompt, 1024)
    raw_text = result.text.strip()  # type: ignore[attr-defined]
    if not raw_text:
        return "[web-search: synthesis produced no output]", []
    answer, citations = _parse_synthesis_result(raw_text, state.all_learnings)
    return answer or raw_text, citations


# ---------------------------------------------------------------------------
# Top-level orchestration
# ---------------------------------------------------------------------------


async def run_web_search(
    question: str,
    adapter: KagiAdapter,
    llm: LLMText,
    config: WebSearchConfig | None = None,
) -> SearchState:
    """Top-level entry point for the agentic web-search loop.

    Implements the 6-step loop (ADR-024 §2.2, §2.4).

    In W1-W3: adapter is always MockKagiAdapter; llm is always MockLLM.
    The function signature and loop logic are complete; the live adapter
    and real 14B slot in at W4/production without changing callers.

    Fail-closed: any unhandled exception returns a SearchState with
    final_answer set to an error message and an empty citations list.
    The caller's session is never interrupted by a loop crash.

    Args:
        question: The user's original question.
        adapter:  KagiAdapter implementation (mock in W3, live in W4).
        llm:      LLMText implementation (MockLLM in W3,
                  OrchestratorGPUInference in production).
        config:   WebSearchConfig controlling loop parameters.  Uses
                  defaults if None.

    Returns:
        A completed SearchState with final_answer and citations populated.
    """
    cfg = config or WebSearchConfig()
    state = SearchState(
        question=question,
        max_passes=cfg.max_passes,
        prefer_recent=cfg.prefer_recent,
        max_sources_per_pass=cfg.max_sources_per_pass,
        use_summarizer=cfg.use_summarizer,
        # #909: mint the per-session datamark token ONCE at search start —
        # every web-content line in the extraction + synthesis prompts is
        # prefixed with it, and it is unknown to any fetched page, so an
        # injected instruction cannot forge the marker to read as trusted.
        session_token=secrets.token_hex(4),  # 8 hex chars (ADR-024 §2.5)
    )
    semaphore = asyncio.Semaphore(cfg.search_concurrency)
    llm_sem = asyncio.Semaphore(1)  # single GPU — serialise all inference

    try:
        # --- Step 1: Query decomposition ---
        state.queries = await decompose_question(state, llm, llm_sem)
        if not state.queries:
            state.final_answer = "[web-search: query decomposition produced no queries]"
            return state

        # --- Main loop: Steps 2-5 ---
        while state.pass_count < state.max_passes:
            state.pass_count += 1
            _LOG.debug("run_web_search: starting pass %d / %d", state.pass_count, state.max_passes)

            # Step 2: Search
            results = await search_queries(
                state.queries,
                adapter,
                semaphore,
                limit=cfg.search_results_limit,
            )
            # Filter out already-visited URLs before triage.
            new_results = [r for r in results if r.url not in state.visited_urls]
            state.visited_urls.update(r.url for r in new_results)

            # Step 3: Triage
            selected = triage_sources(new_results, state)

            if not selected:
                _LOG.warning("run_web_search: pass %d produced no triaged sources", state.pass_count)
                # Continue to gap-detect / synthesise with what we have.
            else:
                # Step 4: Content extraction (the injection scan fires here).
                raw_summaries = await asyncio.gather(
                    *[adapter.summarize_url(r.url) for r in selected]
                )
                # Every fetched page is scanned BEFORE the learning-extraction
                # LLM call (ADR-024 §2.5; live as of #896 — flagged pages are
                # truncated, never passed whole to the model).
                scanned_summaries = [injection_scan(rs) for rs in raw_summaries]

                # Step 4b: Learning extraction (serialised via llm_sem).
                # Build a (SummaryResult, SearchResult) pairing for title fallback.
                sr_map: dict[str, SearchResult] = {r.url: r for r in selected}
                new_learnings = await asyncio.gather(
                    *[
                        extract_learning_serialised(
                            summary=ss,
                            llm=llm,
                            llm_sem=llm_sem,
                            question=state.question,
                            search_result=sr_map.get(ss.url),
                            session_token=state.session_token,
                        )
                        for ss in scanned_summaries
                    ]
                )
                state.all_learnings.extend(new_learnings)

            # Step 5: Gap detection (skip on the last allowed pass).
            if state.pass_count < state.max_passes:
                follow_up = await detect_gaps(state, state.all_learnings, llm, llm_sem)
                if follow_up is None:
                    _LOG.debug("run_web_search: gap-detect says coverage sufficient; exiting loop early")
                    break
                state.queries = follow_up
            else:
                _LOG.debug("run_web_search: max_passes reached; exiting loop")
                break

        # --- Step 6: Synthesis ---
        state.final_answer, state.citations = await synthesise(state, llm, llm_sem)

    except Exception as exc:  # noqa: BLE001 — fail-closed contract
        _LOG.exception("run_web_search: unhandled exception in loop")
        state.final_answer = f"[web-search error: {type(exc).__name__}]"
        state.citations = []

    return state
