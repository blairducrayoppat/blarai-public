"""
Web-Search Skill — core types (W2).

Frozen dataclasses for search and summarisation results.
These are the contract types that W3 (the agentic loop) and W4 (the live
adapter) both import.  They are intentionally narrow — no HTTP client
imports, no kagiapi dependency.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SearchResult:
    """One entry returned by the Kagi Search API.

    Fields map directly to the Kagi Search API 'data' array item schema
    (ADR-024 §2.3).

    Attributes:
        url:         Destination URL of the result.
        title:       Display title of the result.
        snippet:     Preview text (may contain HTML bold markers from Kagi).
        rank:        1-based position in the Kagi result set.
        published:   ISO-8601 timestamp string if present, else None.
        result_type: Kagi 't' field — 0=standard result, 1=related searches.
                     Only t==0 entries are genuine web results; the loop
                     filters t==1 at the triage step (ADR §2.2 Step 3).
        query_source: The sub-query string that produced this result.
                      Set by the loop (Step 2); empty when created by parsers.
    """

    url: str
    title: str
    snippet: str
    rank: int
    published: str | None = None
    result_type: int = 0
    query_source: str = ""


@dataclass(frozen=True)
class SummaryResult:
    """Response from the Kagi Universal Summarizer (or local fetch+extract).

    In W1-W3 the mock returns pre-configured fixture values.
    In W4 the live adapter populates this from either the Kagi Summarizer
    JSON or a local extraction function.

    Attributes:
        url:         The URL that was summarised.
        summary:     The extracted / summarised text.  Empty string on error
                     or when the source returned no usable content.
        tokens_used: Tokens billed by the Summarizer (input + output combined).
                     Zero when using local fetch+extract or on error.
    """

    url: str
    summary: str
    tokens_used: int
