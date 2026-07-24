"""LiveKagiAdapter — the ADR-024 W4 piece, built dormant (#719 Part B).

The live Kagi Search adapter and the deterministic ``web_search`` runner it
feeds. EVERYTHING here is fail-closed and network-free until the LA go-live
ceremony (``docs/runbooks/web_search_go_live.md``):

- The ONLY transport is the one egress door,
  :func:`shared.security.guarded_fetch.fetch_external` — this module never
  imports a network client (the repo-wide exactly-one-network-client
  invariant, ``tests/security/test_no_external_egress.py``, holds). The door
  itself runs the full pipeline (SSRF guard -> PA adjudication -> resolution
  recheck -> widen/fetch/revoke -> injection scan) on every call, and with
  the deterministic egress allowlist EMPTY it denies every URL (RULE 3).
- Instantiating this adapter requires the operator-provisioned, wrapped Kagi
  API key (:class:`shared.secrets.kagi_key_loader.KagiApiKey`) — the key
  value is redacted in every string conversion and leaves the wrapper only
  as the door's ``Authorization`` header value at the moment of the fetch.
- Every failure mode — door denial, timeout, non-200 status, malformed /
  non-JSON body, unexpected exception — collapses to an EMPTY result list.
  The runner then returns ``""``, which the ``web_search`` tool body maps to
  its deterministic failure notice. NOTHING here ever raises into the tool
  loop, and no raw response text ever reaches the context outside the
  grounding path (the AO loop grounds every non-notice web_search result as
  UNTRUSTED_WEB, ADR-023 Amendment 3 — action-locked + datamarked but
  Stage-5-leak-exempt; see ``tools.result_provenance``).

ENDPOINT VERSION NOTE (#724 — corrected LIVE at the 2026-07-02 go-live
ceremony): Kagi's CURRENT Search API is ``POST /api/v1/search`` with a JSON
request body ``{"query": "<text>"}`` and an ``Authorization: Bearer <key>``
header, returning ``{"data": {"search": [ {title, url, snippet, ...}, ... ],
"infobox": [...]}, "meta": {...}}`` — the RESULTS live under ``data.search``.
The deprecated ``/api/v0/search`` (a GET with an ``Authorization: Bot <key>``
header and a flat ``data``-array of ``t``/``rank``/``url``/``title``/
``snippet`` entries — the shape the W2 ``parse_kagi_search_response`` was
built for) now returns **HTTP 401**. This build was originally PINNED to v0
against the then-current ADR-024 / help.kagi.com docs; the first live fetch at
go-live 401'd, and probing the real key proved v1/POST/Bearer/JSON-body is the
live contract. The four axes moved together — v0->v1, GET->POST, Bot->Bearer,
query-param->JSON-body — plus a v1-shaped parser (``_parse_v1_search``, local
to this module, since ``data.search`` objects carry no ``t``/``rank`` fields).
The endpoint constant below, the ``gov-pf-007`` / ``gov-adj-008`` golden cases,
and this parser move together (a REVIEWED re-baseline), never silently.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Callable, Final

from services.assistant_orchestrator.src.websearch.adapter import KagiAdapter
from services.assistant_orchestrator.src.websearch.types import (
    SearchResult,
    SummaryResult,
)
from shared.secrets.kagi_key_loader import KagiApiKey

_LOG = logging.getLogger(__name__)

#: THE single named Kagi Search API endpoint constant. Everything that names
#: the endpoint — the search URL this adapter builds, the D4 dispatch-CAR
#: resource in ``entrypoint._adjudicate_tool_dispatch``, and (by a coupling
#: test) the ``gov-pf-007`` go-live-tripwire golden case — reads THIS value,
#: so the endpoint can never fork across governance surfaces. See the module
#: docstring's ENDPOINT VERSION NOTE before changing it.
KAGI_SEARCH_ENDPOINT: Final[str] = "https://kagi.com/api/v1/search"

#: The ``purpose`` label this adapter presents to the egress door / the PA
#: adjudicator on every fetch — a descriptor, never payload.
WEB_SEARCH_FETCH_PURPOSE: Final[str] = "web_search"

#: Read timeout for one search call (the door's connect timeout is fixed at
#: 10 s). A search API answers in single-digit seconds; a longer hang is a
#: failure, not a result worth waiting for.
DEFAULT_SEARCH_TIMEOUT_S: Final[float] = 20.0

#: How many results one search returns by default / at most. Deterministic
#: LOCAL caps — the v1 POST body sends ONLY the required ``query`` field (the
#: proven-live minimal request), and the parsed ``data.search`` list is
#: re-capped locally to ``bounded`` (the server's word / count is not trusted).
DEFAULT_SEARCH_LIMIT: Final[int] = 5
MAX_SEARCH_LIMIT: Final[int] = 8

#: Per-field caps applied when shaping results for the tool loop. The tool
#: body applies the overall RETRIEVAL_RESULT_MAX_CHARS (4000) deterministic
#: cap on top; these keep any single hostile field from eating that budget.
MAX_TITLE_CHARS: Final[int] = 200
MAX_URL_CHARS: Final[int] = 500
MAX_SNIPPET_CHARS: Final[int] = 400

#: FAIL-CLOSED response-PARSE guard bounds (#727) — applied to the raw Kagi HTTP
#: response BEFORE it is handed to stdlib ``json.loads``. ``json.loads`` has NO
#: size bound and NO recursion-depth limit of its own, so a pathological or
#: man-in-the-middle'd response (oversized, or pathologically deep) could
#: exhaust host memory / the C-stack DURING parsing — before any of the
#: fail-closed per-entry defenses in :func:`_parse_v1_search` ever run. These
#: are a SECOND, INDEPENDENT lock DOWNSTREAM of the egress door's on-the-wire
#: byte cap (:data:`shared.security.guarded_fetch._MAX_BODY_BYTES`, 8 MiB): the
#: door bounds what crosses the network; these bound what THIS adapter will
#: parse. They are deliberately TIGHTER than the door cap — a real Kagi v1
#: search reply is a few KB and nests only ~5 deep — so a hostile response that
#: slips through (or a future non-door caller) still fails closed to the empty
#: result list (VALIDATE-BEFORE-TRUST + FAIL-CLOSED + DENY-BY-DEFAULT). They are
#: the safe HARDCODED defaults so the guard is ALWAYS armed even if the
#: [web_search] config plumbing is absent; the config keys only tune them.
DEFAULT_MAX_RESPONSE_BYTES: Final[int] = 2 * 1024 * 1024  # 2 MiB (< the 8 MiB door cap)
DEFAULT_MAX_PARSE_DEPTH: Final[int] = 12  # Kagi v1 nests ~5; 12 = generous but bounded

# Collapse runs of whitespace (incl. newlines) when shaping snippet/title
# text so a hostile result cannot fake the runner's line structure.
_WS_RUN_RE: Final[re.Pattern[str]] = re.compile(r"\s+")

# Strip HTML tags (Kagi v1 wraps matched query terms in ``<strong>...</strong>``
# inside title/snippet). A deterministic, decode-free tag removal to plain text
# BEFORE the result is grounded as UNTRUSTED_WEB — never an HTML parser, and
# it also removes any other tag a hostile result might inject. Entities are left
# as-is (the grounded text is display/context, not re-rendered as HTML).
_HTML_TAG_RE: Final[re.Pattern[str]] = re.compile(r"<[^>]*>")


def _strip_tags(text: str) -> str:
    """Deterministically remove HTML tags from *text* (Kagi v1 ``<strong>``)."""
    return _HTML_TAG_RE.sub("", text)


def _clip(text: str, max_chars: int) -> str:
    """Collapse whitespace runs and hard-cap *text* at *max_chars*."""
    flattened = _WS_RUN_RE.sub(" ", text).strip()
    if len(flattened) <= max_chars:
        return flattened
    return flattened[: max_chars - 1] + "…"


def _within_parse_depth(text: str, max_depth: int) -> bool:
    """True iff JSON *text* nests no deeper than *max_depth* brace/bracket levels.

    A deterministic, NON-RECURSIVE pre-scan run BEFORE :func:`json.loads` (#727).
    The stdlib decoder has no depth bound of its own and descends (at the C
    level) through every nesting level DURING parsing, so a deeply-nested body
    can exhaust the stack / host memory before any Python code inspects it. An
    ``object_hook`` / ``object_pairs_hook`` cannot prevent this — a hook fires
    only as each container COMPLETES (after the recursion has already descended)
    and never observes ARRAY nesting at all, so an ``[[[[…`` array bomb sails
    straight past it. So we bound depth UP FRONT instead (validate-before-trust),
    counting BOTH ``{`` and ``[``.

    The scan is string- and escape-aware — a brace/bracket INSIDE a JSON string
    literal is data, not structure, and does not count — and early-exits
    ``False`` the instant nesting exceeds *max_depth*, so a depth-bomb is
    rejected in O(max_depth) work rather than being scanned (let alone parsed) in
    full. O(n) time, O(1) space, never raises.
    """
    depth = 0
    in_string = False
    escaped = False
    for ch in text:
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == "{" or ch == "[":
            depth += 1
            if depth > max_depth:
                return False
        elif ch == "}" or ch == "]":
            if depth > 0:
                depth -= 1
    return True


def _parse_v1_search(raw: dict[str, Any]) -> list[SearchResult]:
    """Map a Kagi Search API **v1** response to :class:`SearchResult` objects.

    The v1 shape (verified LIVE 2026-07-02) differs fundamentally from the v0
    flat ``data``-array the W2 ``parse_kagi_search_response`` was built for::

        {"data": {"search": [ {"title": str, "url": str, "snippet": str,
                               "time": str, "props": {...}}, ... ],
                  "infobox": [...]},
         "meta": {...}}

    The genuine web results are ``data.search`` — an ORDERED list (Kagi's own
    rank order, which we preserve as ``rank`` = 1-based position; v1 entries
    carry no ``t``/``rank`` field). ``infobox`` (and any other key) is ignored.
    Title/snippet are tag-stripped (v1 wraps query terms in ``<strong>``).

    Fail-closed, never raises: ``data`` not a dict, ``data.search`` absent or not
    a list (a no-results / error response), an entry that is not a dict, or one
    missing a usable ``url`` are all skipped — yielding ``[]`` in the worst case,
    which the caller maps to the deterministic "no results" value.
    """
    results: list[SearchResult] = []
    data = raw.get("data")
    if not isinstance(data, dict):
        _LOG.warning(
            "LiveKagiAdapter: v1 response has no 'data' object — no results"
        )
        return results
    search = data.get("search")
    if not isinstance(search, list):
        # Absent / non-list 'search' is the no-results / error shape — empty.
        _LOG.warning(
            "LiveKagiAdapter: v1 response 'data.search' absent or not a list "
            "— no results"
        )
        return results
    for rank, item in enumerate(search, start=1):
        if not isinstance(item, dict):
            continue
        url = item.get("url")
        if not isinstance(url, str) or not url:
            continue
        title_raw = item.get("title")
        title = _strip_tags(title_raw) if isinstance(title_raw, str) else ""
        snippet_raw = item.get("snippet")
        snippet = _strip_tags(snippet_raw) if isinstance(snippet_raw, str) else ""
        time_raw = item.get("time")
        published = time_raw if isinstance(time_raw, str) and time_raw else None
        results.append(
            SearchResult(
                url=url,
                title=title,
                snippet=snippet,
                rank=rank,
                published=published,
                result_type=0,
                query_source="",
            )
        )
    return results


class LiveKagiAdapter(KagiAdapter):
    """Kagi Search over the ONE egress door — fail-closed, never-raising.

    ADR-024 W4. Constructed only by the AO entrypoint's conditional
    web_search registration (``[web_search].enabled`` AND a loadable key);
    holds the key exclusively as the redacting :class:`KagiApiKey` wrapper.

    ``summarize_url`` is DELIBERATELY not live: the W5 untrusted-content
    pipeline it feeds is out of the #719 Part B scope, so it returns the
    fail-closed empty :class:`SummaryResult` unconditionally (never a fetch).
    """

    def __init__(
        self,
        api_key: KagiApiKey,
        *,
        timeout_s: float = DEFAULT_SEARCH_TIMEOUT_S,
        max_response_bytes: int = DEFAULT_MAX_RESPONSE_BYTES,
        max_parse_depth: int = DEFAULT_MAX_PARSE_DEPTH,
    ) -> None:
        if not isinstance(api_key, KagiApiKey):
            raise TypeError("LiveKagiAdapter requires a wrapped KagiApiKey")
        self._api_key = api_key
        self._timeout_s = float(timeout_s)
        # #727 — fail-closed PARSE-guard bounds (see DEFAULT_MAX_* above). A
        # non-positive / non-int value falls back to the vetted default rather
        # than DISARMING the guard: a 0 byte-cap would reject every response and
        # a <= 0 depth would too, so the guard must never be silently turned off
        # by a bad value — it clamps to the safe default. (``bool`` is excluded
        # explicitly: it is an ``int`` subclass, so ``True`` would slip through
        # as a 1-byte / depth-1 cap.) The AO config layer validates these at
        # boot as positive ints; this clamp is defense-in-depth for any direct
        # construction.
        self._max_response_bytes = (
            int(max_response_bytes)
            if isinstance(max_response_bytes, int)
            and not isinstance(max_response_bytes, bool)
            and max_response_bytes > 0
            else DEFAULT_MAX_RESPONSE_BYTES
        )
        self._max_parse_depth = (
            int(max_parse_depth)
            if isinstance(max_parse_depth, int)
            and not isinstance(max_parse_depth, bool)
            and max_parse_depth > 0
            else DEFAULT_MAX_PARSE_DEPTH
        )

    def search_sync(
        self, query: str, limit: int = DEFAULT_SEARCH_LIMIT
    ) -> list[SearchResult]:
        """One Kagi Search API v1 call through the egress door — synchronous.

        Fires a ``POST`` to :data:`KAGI_SEARCH_ENDPOINT` (``/api/v1/search``)
        with the minimal JSON body ``{"query": <text>}`` and the wrapped key's
        ``Bearer`` credential, through the ONE egress door. Returns at most
        ``min(limit, MAX_SEARCH_LIMIT)`` genuine web results from
        ``data.search``, preserving Kagi's own rank order, capped locally.

        EVERY failure mode returns ``[]``: empty query, door denial (which is
        every call while the egress allowlist is empty — the dormant posture),
        timeout, non-200 status, malformed / non-JSON / non-dict body, a
        response with no ``data.search`` array, or any unexpected exception.
        Never raises.
        """
        q = query.strip()
        if not q:
            return []
        try:
            bounded = max(1, min(int(limit), MAX_SEARCH_LIMIT))
        except (TypeError, ValueError):
            bounded = DEFAULT_SEARCH_LIMIT

        try:
            # Lazy import so importing THIS module (e.g. for the endpoint
            # constant in the D4 dispatch adjudication) never pulls in the
            # door module (and with it httpx).
            from shared.security.guarded_fetch import fetch_external

            result = fetch_external(
                KAGI_SEARCH_ENDPOINT,
                purpose=WEB_SEARCH_FETCH_PURPOSE,
                timeout_s=self._timeout_s,
                authorization=self._api_key.authorization_header_value(),
                method="POST",
                json_body={"query": q},
            )
        except Exception as exc:  # noqa: BLE001 — the adapter NEVER raises
            _LOG.error(
                "LiveKagiAdapter: egress-door call raised (%s) — no results "
                "(fail-closed)",
                type(exc).__name__,
            )
            return []

        if not result.ok:
            # The dormant posture lands here on every call (RULE 3 + the
            # empty allowlist deny at the door). Log-safe label only.
            _LOG.warning(
                "LiveKagiAdapter: search fetch refused/failed (%s) — no results",
                result.denied_reason,
            )
            return []
        if result.status != 200:
            _LOG.warning(
                "LiveKagiAdapter: search returned HTTP %d — no results",
                result.status,
            )
            return []

        # #727 — FAIL-CLOSED response-PARSE guard (validate-before-trust). Bound
        # BOTH the size and the nesting depth of the raw response BEFORE handing
        # it to ``json.loads`` (which has NO size or recursion-depth limit): a
        # pathological or MITM'd reply could otherwise exhaust host memory / the
        # C-stack DURING parsing, before the per-entry defenses in
        # ``_parse_v1_search`` run. On violation, fail closed to ``[]`` via the
        # SAME never-raise path as every other failure mode, logging WHY
        # (fail-LOUD, secret-free). This is a SECOND, INDEPENDENT lock downstream
        # of the door's 8 MiB on-the-wire cap, deliberately tighter — the door
        # bounds the fetch; this bounds the parse.
        body = result.content_text
        body_bytes = len(body.encode("utf-8", errors="ignore"))
        if body_bytes > self._max_response_bytes:
            _LOG.warning(
                "LiveKagiAdapter: search response is %d bytes, over the %d-byte "
                "parse cap — rejected unparsed (no results, fail-closed)",
                body_bytes,
                self._max_response_bytes,
            )
            return []
        if not _within_parse_depth(body, self._max_parse_depth):
            _LOG.warning(
                "LiveKagiAdapter: search response nests deeper than the max "
                "parse depth of %d — rejected unparsed (no results, fail-closed)",
                self._max_parse_depth,
            )
            return []

        try:
            raw = json.loads(body)
        except (json.JSONDecodeError, ValueError):
            _LOG.warning(
                "LiveKagiAdapter: search response is not valid JSON — no results"
            )
            return []
        except Exception as exc:  # noqa: BLE001 — the adapter NEVER raises
            # #727 defense-in-depth backstop for the module's "never raises"
            # contract. The pre-scan above rejects an over-deep body BEFORE
            # json.loads, so this is unreachable in practice — but stdlib
            # json.loads raises RecursionError on a deeply-nested body (and could
            # raise MemoryError on a huge one), neither of which is a
            # JSONDecodeError/ValueError. Catch them here so the never-raise
            # guarantee rests on TWO independent locks, not the pre-scan alone
            # (a hypothetical pre-scan miscount degrades to [] instead of
            # escaping search_sync). Mirrors the egress-door-call handler's
            # fail-closed `except Exception` idiom above. Fail-loud (secret-free
            # type name), fail-closed to [].
            _LOG.error(
                "LiveKagiAdapter: json.loads raised %s — no results "
                "(fail-closed, parse-guard backstop)",
                type(exc).__name__,
            )
            return []
        if not isinstance(raw, dict):
            _LOG.warning(
                "LiveKagiAdapter: search response JSON is not an object — "
                "no results"
            )
            return []

        # The v1 parser owns the defensive per-entry mapping (skip-on-malformed,
        # never raises) and preserves Kagi's rank order; we impose the local cap.
        web_results = _parse_v1_search(raw)
        return web_results[:bounded]

    async def search(
        self, query: str, limit: int = DEFAULT_SEARCH_LIMIT
    ) -> list[SearchResult]:
        """Async interface shim over :meth:`search_sync` (KagiAdapter ABC)."""
        return self.search_sync(query, limit)

    async def summarize_url(self, url: str) -> SummaryResult:
        """NOT live in #719 Part B — unconditionally the fail-closed empty.

        The W5 per-URL content-extraction pipeline is out of scope; until it
        is built AND reviewed, this performs NO fetch and returns the empty
        :class:`SummaryResult` (the ABC's documented error shape).
        """
        return SummaryResult(url=url, summary="", tokens_used=0)


def format_search_results(results: list[SearchResult]) -> str:
    """Deterministically shape results for the tool loop — title/url/snippet.

    One numbered block per result, fields whitespace-flattened and hard-capped
    (:data:`MAX_TITLE_CHARS` / :data:`MAX_URL_CHARS` /
    :data:`MAX_SNIPPET_CHARS`); NOTHING but title, url, and snippet is ever
    emitted. Returns ``""`` for an empty list — the runner contract's
    "no results" value, which the tool body maps to its deterministic failure
    notice. The tool body's RETRIEVAL_RESULT_MAX_CHARS cap applies on top.
    """
    blocks: list[str] = []
    for index, result in enumerate(results, start=1):
        title = _clip(result.title, MAX_TITLE_CHARS) or "(untitled)"
        url = _clip(result.url, MAX_URL_CHARS)
        snippet = _clip(result.snippet, MAX_SNIPPET_CHARS)
        block = f"{index}. {title}\n   {url}"
        if snippet:
            block += f"\n   {snippet}"
        blocks.append(block)
    return "\n".join(blocks)


def make_web_search_runner(adapter: LiveKagiAdapter) -> Callable[[str], str]:
    """Build the ``runner(query) -> str`` the web_search tool seam consumes.

    The runner delegates to :meth:`LiveKagiAdapter.search_sync` (never
    raises, fail-closed to ``[]``) and shapes the results via
    :func:`format_search_results` (``""`` on none -> the tool body's
    deterministic failure notice). The AO tool loop grounds any non-notice
    return as UNTRUSTED_WEB (ADR-023 Amendment 3) through the EXISTING
    provenance declaration (``tools.result_provenance("web_search")``) — this
    function adds no grounding path of its own.
    """

    def _runner(query: str) -> str:
        return format_search_results(adapter.search_sync(query))

    return _runner
