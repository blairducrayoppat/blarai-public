"""
Web-Search Skill — KagiAdapter interface, MockKagiAdapter, and pure parsers (W2).

This module is the clean seam between the agentic loop (W3) and the live
Kagi HTTP client (W4).  Everything here is network-free:

- KagiAdapter      -- abstract base class; two async methods.
- MockKagiAdapter  -- fixture-backed implementation for W1-W3 testing.
- parse_kagi_search_response   -- pure dict -> list[SearchResult] parser.
- parse_kagi_summary_response  -- pure dict -> SummaryResult parser.

The two parsers accept the raw dicts that kagiapi's Python client returns
after JSON-decoding the Kagi HTTP responses.  W4's LiveKagiAdapter will
call the real kagiapi client and pass its output through these parsers,
keeping the parser logic in one tested place and keeping W4 free of
duplicate mapping code.

Fail-closed contract (ADR-024 §2.3):
  - search()        returns [] on any error; never raises.
  - summarize_url() returns SummaryResult(url=url, summary="", tokens_used=0)
                    on any error; never raises.
  - Both parsers:   skip malformed entries / return safe empties; never raise.
"""

from __future__ import annotations

import abc
import logging
from typing import Any

from services.assistant_orchestrator.src.websearch.types import (
    SearchResult,
    SummaryResult,
)

_LOG = logging.getLogger(__name__)

# Kagi Search API 't' field values.
_KAGI_T_RESULT: int = 0       # standard web result
_KAGI_T_RELATED: int = 1      # related-search suggestion list (not a real result)


# ---------------------------------------------------------------------------
# Pure parsers — no network, no side-effects, always fail-closed
# ---------------------------------------------------------------------------


def parse_kagi_search_response(raw: dict[str, Any]) -> list[SearchResult]:
    """Map a Kagi Search API JSON response dict to SearchResult objects.

    Kagi Search API response schema (verified against kagiapi README and
    help.kagi.com docs, 2026-06-04):

        {
          "meta": {"id": str, "node": str, "ms": int},
          "data": [
            {
              "t": int,          # 0=result, 1=related-searches list
              "rank": int,       # present when t==0
              "url": str,        # present when t==0
              "title": str,      # present when t==0
              "snippet": str,    # present when t==0, may be absent
              "published": str,  # ISO-8601, optional
              "thumbnail": {...} # optional, ignored here
            },
            ...
          ]
        }

    Entries with t==1 carry a 'list' key of related query strings — they
    are NOT web results.  This parser maps t==1 entries to SearchResult
    objects with result_type=1 so the caller (triage step, ADR §2.2 Step 3)
    can filter them.

    Fail-closed: any entry with missing or malformed required keys is
    silently skipped with a WARNING log.  A completely malformed top-level
    dict returns an empty list without raising.

    Args:
        raw: The parsed JSON dict returned by the Kagi Search API.

    Returns:
        A list of SearchResult objects.  May be empty.  Never raises.
    """
    results: list[SearchResult] = []
    try:
        data = raw.get("data")
        if not isinstance(data, list):
            _LOG.warning(
                "parse_kagi_search_response: 'data' key missing or not a list"
                " (got %s); returning empty list",
                type(data).__name__,
            )
            return results

        for idx, item in enumerate(data):
            if not isinstance(item, dict):
                _LOG.warning(
                    "parse_kagi_search_response: item[%d] is not a dict (%s);"
                    " skipping",
                    idx,
                    type(item).__name__,
                )
                continue

            t_val = item.get("t")
            if t_val is None:
                _LOG.warning(
                    "parse_kagi_search_response: item[%d] missing 't' field;"
                    " skipping",
                    idx,
                )
                continue

            try:
                result_type = int(t_val)
            except (TypeError, ValueError):
                _LOG.warning(
                    "parse_kagi_search_response: item[%d] 't' value %r not"
                    " castable to int; skipping",
                    idx,
                    t_val,
                )
                continue

            if result_type == _KAGI_T_RESULT:
                # Standard web result — url, title, rank are required.
                url = item.get("url")
                title = item.get("title")
                rank_raw = item.get("rank")

                if not isinstance(url, str) or not url:
                    _LOG.warning(
                        "parse_kagi_search_response: item[%d] (t=0) missing"
                        " or empty 'url'; skipping",
                        idx,
                    )
                    continue
                if not isinstance(title, str):
                    _LOG.warning(
                        "parse_kagi_search_response: item[%d] (t=0) missing"
                        " 'title'; skipping",
                        idx,
                    )
                    continue
                try:
                    rank = int(rank_raw) if rank_raw is not None else idx + 1
                except (TypeError, ValueError):
                    rank = idx + 1

                snippet_raw = item.get("snippet", "")
                snippet = snippet_raw if isinstance(snippet_raw, str) else ""

                published_raw = item.get("published")
                published: str | None = (
                    published_raw
                    if isinstance(published_raw, str) and published_raw
                    else None
                )

                results.append(
                    SearchResult(
                        url=url,
                        title=title,
                        snippet=snippet,
                        rank=rank,
                        published=published,
                        result_type=_KAGI_T_RESULT,
                        query_source="",
                    )
                )

            elif result_type == _KAGI_T_RELATED:
                # Related-search suggestion list.  We map to a SearchResult
                # with result_type=1 so the triage step can identify and
                # filter it.  url/title/snippet are synthetic sentinels so
                # the frozen dataclass is satisfied.
                results.append(
                    SearchResult(
                        url="",
                        title="",
                        snippet="",
                        rank=0,
                        published=None,
                        result_type=_KAGI_T_RELATED,
                        query_source="",
                    )
                )

            else:
                # Unknown 't' value — future Kagi API extension.  Skip but
                # do not crash; the loop continues with fewer results.
                _LOG.debug(
                    "parse_kagi_search_response: item[%d] unknown t=%d; skipping",
                    idx,
                    result_type,
                )

    except Exception:  # noqa: BLE001 — fail-closed: parsers never raise
        _LOG.warning(
            "parse_kagi_search_response: unexpected error during parsing;"
            " returning partial results",
            exc_info=True,
        )

    return results


def parse_kagi_summary_response(raw: dict[str, Any]) -> SummaryResult:
    """Map a Kagi Universal Summarizer JSON response dict to a SummaryResult.

    Kagi Universal Summarizer response schema (verified against
    help.kagi.com/kagi/api/summarizer.html, 2026-06-04):

        {
          "meta": {"id": str, "node": str, "ms": int},
          "data": {
            "output": str,    # the summary text
            "tokens": int     # total tokens billed (input + output)
          }
        }

    Fail-closed: missing or malformed keys return an empty-summary
    SummaryResult with tokens_used=0.  Never raises.

    Note: The caller must supply the source URL separately (Kagi's response
    does not echo the input URL back).

    Args:
        raw: The parsed JSON dict returned by the Kagi Summarizer API.
             A 'url' key at the top level is consumed if present (for the
             case where the caller embeds the URL for convenience).

    Returns:
        A SummaryResult.  summary is "" on any error.  Never raises.
    """
    # Allow the caller to embed the URL in the dict for convenience; the
    # Kagi API itself does not return the URL in its response body.
    url: str = ""
    try:
        candidate_url = raw.get("url", "")
        if isinstance(candidate_url, str):
            url = candidate_url
    except Exception:  # noqa: BLE001
        pass

    try:
        data = raw.get("data")
        if not isinstance(data, dict):
            _LOG.warning(
                "parse_kagi_summary_response: 'data' key missing or not a"
                " dict (got %s); returning empty summary",
                type(data).__name__,
            )
            return SummaryResult(url=url, summary="", tokens_used=0)

        output_raw = data.get("output", "")
        summary: str = output_raw if isinstance(output_raw, str) else ""

        tokens_raw = data.get("tokens", 0)
        try:
            tokens_used = int(tokens_raw)
        except (TypeError, ValueError):
            tokens_used = 0

        return SummaryResult(url=url, summary=summary, tokens_used=tokens_used)

    except Exception:  # noqa: BLE001 — fail-closed: parsers never raise
        _LOG.warning(
            "parse_kagi_summary_response: unexpected error during parsing;"
            " returning empty summary",
            exc_info=True,
        )
        return SummaryResult(url=url, summary="", tokens_used=0)


# ---------------------------------------------------------------------------
# Abstract adapter interface
# ---------------------------------------------------------------------------


class KagiAdapter(abc.ABC):
    """Abstract interface for the Kagi search + content-extraction surface.

    W2 provides two implementations:
    - MockKagiAdapter: fixture-backed, zero network calls, used in W1-W3.
    - LiveKagiAdapter: real HTTP via the W4 egress-proxied requests session.

    The interface is intentionally narrow: the loop only needs these two
    operations.  FastGPT, Enrichment, and future Kagi APIs are separate
    concerns and do not belong in this interface (ADR-024 §4).
    """

    @abc.abstractmethod
    async def search(
        self,
        query: str,
        limit: int = 7,
    ) -> list[SearchResult]:
        """Execute one Kagi Search API call for *query*.

        Returns at most *limit* results.  Returns an empty list on any
        error (fail-soft: the loop proceeds with fewer sources).
        Never raises — errors are logged and swallowed.

        Args:
            query: The search query string.
            limit: Maximum number of SearchResult objects to return.

        Returns:
            A list of SearchResult objects, length <= limit.
        """
        ...

    @abc.abstractmethod
    async def summarize_url(
        self,
        url: str,
    ) -> SummaryResult:
        """Extract and return the textual content of *url*.

        In MockKagiAdapter: returns a pre-configured fixture SummaryResult.
        In LiveKagiAdapter: calls the Kagi Universal Summarizer OR a local
        fetch+extract function, controlled by config flag
        `web_search.use_kagi_summarizer` in default.toml.

        Returns a SummaryResult with an empty summary string on error
        (fail-soft).  Never raises.

        Args:
            url: The URL whose content should be extracted.

        Returns:
            A SummaryResult.  summary is "" on error.
        """
        ...


# ---------------------------------------------------------------------------
# Mock adapter — fixture-backed, zero network, for W1-W3
# ---------------------------------------------------------------------------


class MockKagiAdapter(KagiAdapter):
    """Fixture-backed KagiAdapter for W1-W3 testing.

    Instantiate with pre-built fixture dicts, then inject into the loop or
    tests.  No network calls are made; the adapter is deterministic.

    Example::

        adapter = MockKagiAdapter(
            search_fixture={
                "OpenVINO GenAI version": [
                    SearchResult(
                        url="https://github.com/openvinotoolkit/openvino.genai",
                        title="OpenVINO GenAI",
                        snippet="Latest release...",
                        rank=1,
                    ),
                ],
            },
            summary_fixture={
                "https://github.com/openvinotoolkit/openvino.genai": SummaryResult(
                    url="https://github.com/openvinotoolkit/openvino.genai",
                    summary="OpenVINO GenAI is a library...",
                    tokens_used=120,
                ),
            },
        )

    Args:
        search_fixture:  Maps query strings to lists of SearchResult objects.
                         Queries not present in the dict return [].
        summary_fixture: Maps URL strings to SummaryResult objects.
                         URLs not present return an empty-summary SummaryResult.
    """

    def __init__(
        self,
        search_fixture: dict[str, list[SearchResult]] | None = None,
        summary_fixture: dict[str, SummaryResult] | None = None,
    ) -> None:
        self._search_fixture: dict[str, list[SearchResult]] = (
            search_fixture if search_fixture is not None else {}
        )
        self._summary_fixture: dict[str, SummaryResult] = (
            summary_fixture if summary_fixture is not None else {}
        )

    async def search(self, query: str, limit: int = 7) -> list[SearchResult]:
        """Return fixture results for *query*, capped at *limit*.

        Returns [] for unknown queries (fail-soft).  Never raises.
        """
        return self._search_fixture.get(query, [])[:limit]

    async def summarize_url(self, url: str) -> SummaryResult:
        """Return fixture SummaryResult for *url*.

        Returns an empty-summary SummaryResult for unknown URLs.  Never raises.
        """
        return self._summary_fixture.get(
            url,
            SummaryResult(url=url, summary="", tokens_used=0),
        )
