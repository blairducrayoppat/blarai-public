"""Tests for the W4 LiveKagiAdapter + the deterministic web_search runner
(#719 Part B).

ALL OFFLINE: the egress door is mocked AT THE SEAM
(``shared.security.guarded_fetch.fetch_external`` — the adapter's ONLY
transport, imported lazily inside ``search_sync``), so no socket, no DNS, and
no adjudicator/transport state is ever touched. Mirrors the W2 adapter-test
conventions (fixture-shaped Kagi dicts, fail-closed empties).

Covers:
  - the endpoint constant: pinned to the gov-pf-007 go-live-tripwire golden
    case's resource (a coupling lock — the D4 dispatch CAR, the adapter URL,
    and the eval tripwire can never fork);
  - search_sync success shaping: door called with the encoded query URL, the
    web_search purpose, and the wrapped key's Authorization header; t==1
    related-entries filtered; deterministic (rank, url) ordering; local cap;
  - EVERY failure mode -> [] and never a raise: empty query (door never
    consulted), door denial (the dormant posture), non-200, non-JSON body,
    non-dict JSON, a door call that raises;
  - the runner: deterministic title/url/snippet blocks, field caps,
    whitespace flattening, "" on no results (-> the tool body's failure
    notice); the sentinel key never reaches a log record;
  - summarize_url: unconditionally the fail-closed empty (W5 not in scope).
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import pytest

import shared.security.guarded_fetch as guarded_fetch_mod
from services.assistant_orchestrator.src.websearch import (
    live_adapter as live_adapter_mod,
)
from services.assistant_orchestrator.src.websearch.live_adapter import (
    DEFAULT_MAX_PARSE_DEPTH,
    DEFAULT_MAX_RESPONSE_BYTES,
    KAGI_SEARCH_ENDPOINT,
    MAX_SEARCH_LIMIT,
    MAX_SNIPPET_CHARS,
    MAX_TITLE_CHARS,
    WEB_SEARCH_FETCH_PURPOSE,
    LiveKagiAdapter,
    _within_parse_depth,
    format_search_results,
    make_web_search_runner,
)
from services.assistant_orchestrator.src.websearch.types import SearchResult
from shared.secrets.kagi_key_loader import KagiApiKey
from shared.security.guarded_fetch import FetchResult

# Obviously-fake sentinel — NEVER a real-looking key.
_SENTINEL = "FAKE-TEST-SENTINEL-KAGI-KEY-w4"


def _kagi_body(*entries: dict[str, Any], infobox: Any = None) -> str:
    """A Kagi Search API **v1** response body (verified LIVE 2026-07-02).

    Results live under ``data.search`` (an ordered list); ``infobox`` may be
    absent, empty, or populated — all three are tolerated by the parser.
    """
    data: dict[str, Any] = {"search": list(entries)}
    if infobox is not None:
        data["infobox"] = infobox
    return json.dumps({"meta": {"id": "x", "node": "y", "ms": 3}, "data": data})


def _entry(url: str, title: str, snippet: str = "", time: str = "") -> dict[str, Any]:
    """One v1 ``data.search`` entry (no ``t``/``rank`` — order IS the rank)."""
    entry: dict[str, Any] = {"title": title, "url": url, "snippet": snippet}
    if time:
        entry["time"] = time
    return entry


def _ok_result(body: str, status: int = 200) -> FetchResult:
    return FetchResult(
        url=KAGI_SEARCH_ENDPOINT,
        status=status,
        content_text=body,
        content_type="application/json",
        denied_reason=None,
    )


def _denied_result(reason: str) -> FetchResult:
    return FetchResult(url=KAGI_SEARCH_ENDPOINT, denied_reason=reason)


def _patch_door(monkeypatch: pytest.MonkeyPatch, fn) -> list[dict[str, Any]]:
    """Mock the door at the seam; returns the recorded call list."""
    calls: list[dict[str, Any]] = []

    def _fake_fetch_external(
        url: str,
        *,
        purpose: str,
        timeout_s: float = 30.0,
        authorization=None,
        method: str = "GET",
        json_body=None,
    ) -> FetchResult:
        calls.append(
            {
                "url": url,
                "purpose": purpose,
                "timeout_s": timeout_s,
                "authorization": authorization,
                "method": method,
                "json_body": json_body,
            }
        )
        return fn(url)

    monkeypatch.setattr(guarded_fetch_mod, "fetch_external", _fake_fetch_external)
    return calls


def _adapter() -> LiveKagiAdapter:
    return LiveKagiAdapter(KagiApiKey(_SENTINEL))


# ---------------------------------------------------------------------------
# The endpoint constant — one name, three governance surfaces.
# ---------------------------------------------------------------------------


class TestEndpointConstant:
    def test_pinned_to_the_gov_pf_007_tripwire_resource(self) -> None:
        """COUPLING LOCK: the adapter's endpoint constant IS the resource the
        gov-pf-007 go-live-tripwire eval pins (and the D4 dispatch CAR
        carries). If either side moves alone — e.g. a v0 -> v1 migration —
        this fails, forcing the reviewed together-move."""
        golden = (
            Path(__file__).resolve().parents[4]
            / "evals"
            / "golden"
            / "governance.jsonl"
        )
        tripwire = None
        for line in golden.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            case = json.loads(line)
            if case.get("id") == "gov-pf-007":
                tripwire = case
                break
        assert tripwire is not None, "gov-pf-007 golden case missing"
        assert tripwire["car"]["resource"] == KAGI_SEARCH_ENDPOINT

    def test_https_kagi_host(self) -> None:
        assert KAGI_SEARCH_ENDPOINT.startswith("https://kagi.com/")


# ---------------------------------------------------------------------------
# search_sync — success shaping.
# ---------------------------------------------------------------------------


class TestSearchSyncSuccess:
    def test_calls_the_door_with_post_json_purpose_and_bearer_auth(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls = _patch_door(
            monkeypatch,
            lambda url: _ok_result(
                _kagi_body(_entry("https://a.example/x", "A"))
            ),
        )
        results = _adapter().search_sync("openvino news & views", limit=3)
        assert len(results) == 1
        assert len(calls) == 1
        call = calls[0]
        # v1 is a POST to the bare endpoint (no query string); the query rides
        # in the JSON body, the credential in a Bearer header.
        assert call["url"] == KAGI_SEARCH_ENDPOINT
        assert call["method"] == "POST"
        assert call["json_body"] == {"query": "openvino news & views"}
        assert call["purpose"] == WEB_SEARCH_FETCH_PURPOSE
        assert call["authorization"] == f"Bearer {_SENTINEL}"

    def test_preserves_kagi_rank_order_strips_tags_and_caps(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _patch_door(
            monkeypatch,
            lambda url: _ok_result(
                _kagi_body(
                    _entry("https://a.example/", "<strong>A</strong>lpha", "s1"),
                    _entry("https://b.example/", "Beta", "the <strong>B</strong>"),
                    _entry("https://c.example/", "Gamma"),
                    _entry("https://d.example/", "Delta"),
                )
            ),
        )
        results = _adapter().search_sync("q", limit=3)
        # v1 has no rank field — Kagi's array order IS the rank; capped at limit.
        assert [r.title for r in results] == ["Alpha", "Beta", "Gamma"]
        # HTML tags stripped from both title and snippet before grounding.
        assert results[0].title == "Alpha"
        assert results[1].snippet == "the B"
        assert all(r.result_type == 0 for r in results)

    def test_tolerates_populated_and_absent_infobox(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # infobox present + populated: ignored, only data.search returned.
        _patch_door(
            monkeypatch,
            lambda url: _ok_result(
                _kagi_body(
                    _entry("https://a.example/", "A"),
                    infobox=[{"title": "box", "url": "https://x", "snippet": "y"}],
                )
            ),
        )
        assert [r.title for r in _adapter().search_sync("q")] == ["A"]

    def test_limit_clamped_to_max_via_local_cap(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # The body sends ONLY {"query": ...}; the local cap enforces the bound.
        calls = _patch_door(
            monkeypatch,
            lambda url: _ok_result(
                _kagi_body(
                    *[_entry(f"https://a{i}.example/", f"T{i}") for i in range(12)]
                )
            ),
        )
        results = _adapter().search_sync("q", limit=999)
        assert calls[0]["json_body"] == {"query": "q"}
        assert len(results) == MAX_SEARCH_LIMIT


# ---------------------------------------------------------------------------
# search_sync — every failure mode is [] and never a raise.
# ---------------------------------------------------------------------------


class TestSearchSyncFailureModes:
    def test_empty_query_never_consults_the_door(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls = _patch_door(monkeypatch, lambda url: _ok_result(_kagi_body()))
        assert _adapter().search_sync("   ") == []
        assert calls == []

    def test_door_denial_is_the_dormant_posture(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The shipped posture: RULE 3 + the empty allowlist deny at the door
        -> the adapter yields NO results and NO exception."""
        _patch_door(
            monkeypatch,
            lambda url: _denied_result("policy: Policy Agent denied the URL"),
        )
        assert _adapter().search_sync("anything") == []

    def test_timeout_shaped_denial(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch_door(monkeypatch, lambda url: _denied_result("fetch timed out"))
        assert _adapter().search_sync("q") == []

    def test_non_200_status(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch_door(
            monkeypatch, lambda url: _ok_result('{"error":"quota"}', status=429)
        )
        assert _adapter().search_sync("q") == []

    def test_malformed_json_body(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch_door(monkeypatch, lambda url: _ok_result("<html>not json</html>"))
        assert _adapter().search_sync("q") == []

    def test_non_dict_json_body(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch_door(monkeypatch, lambda url: _ok_result('["a", "list"]'))
        assert _adapter().search_sync("q") == []

    def test_data_search_absent_is_no_results(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A v1 response whose 'data' has no 'search' array (a no-results /
        error shape) fail-closes to [] — never a raise."""
        _patch_door(
            monkeypatch,
            lambda url: _ok_result('{"meta": {"ms": 1}, "data": {"infobox": []}}'),
        )
        assert _adapter().search_sync("q") == []

    def test_data_not_an_object_is_no_results(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # v0-shaped body (data is a flat LIST) is now the WRONG shape -> [].
        _patch_door(
            monkeypatch,
            lambda url: _ok_result('{"data": [{"t": 0, "url": "https://x/"}]}'),
        )
        assert _adapter().search_sync("q") == []

    def test_malformed_entries_skipped_not_fatal(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _patch_door(
            monkeypatch,
            lambda url: _ok_result(
                _kagi_body(
                    {"title": "no url"},  # missing url -> skipped
                    "not-a-dict",  # type: ignore[arg-type]
                    _entry("https://ok.example/", "OK"),
                )
            ),
        )
        results = _adapter().search_sync("q")
        assert [r.title for r in results] == ["OK"]

    def test_door_raising_never_escapes(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def _boom(
            url: str,
            *,
            purpose: str,
            timeout_s: float = 30.0,
            authorization=None,
            method: str = "GET",
            json_body=None,
        ) -> FetchResult:
            raise ConnectionError("no network — as designed")

        monkeypatch.setattr(guarded_fetch_mod, "fetch_external", _boom)
        assert _adapter().search_sync("q") == []

    def test_requires_a_wrapped_key(self) -> None:
        with pytest.raises(TypeError):
            LiveKagiAdapter("bare-string-key")  # type: ignore[arg-type]

    def test_key_never_logged_during_search(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Drive a denied search (the dormant posture, which logs) with the
        sentinel-keyed adapter — the sentinel must reach NO record."""
        _patch_door(monkeypatch, lambda url: _denied_result("policy: denied"))
        with caplog.at_level(logging.DEBUG):
            assert _adapter().search_sync("q") == []
        assert _SENTINEL not in caplog.text


# ---------------------------------------------------------------------------
# The async ABC surface.
# ---------------------------------------------------------------------------


class TestAsyncSurface:
    def test_async_search_delegates(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import asyncio

        _patch_door(
            monkeypatch,
            lambda url: _ok_result(_kagi_body(_entry("https://a.example/", "A"))),
        )
        results = asyncio.run(_adapter().search("q"))
        assert [r.title for r in results] == ["A"]

    def test_summarize_url_is_fail_closed_empty_and_never_fetches(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls = _patch_door(monkeypatch, lambda url: _ok_result(_kagi_body()))
        import asyncio

        summary = asyncio.run(_adapter().summarize_url("https://a.example/"))
        assert summary.summary == "" and summary.tokens_used == 0
        assert calls == [], "summarize_url must perform NO fetch (W5 not built)"


# ---------------------------------------------------------------------------
# Result shaping + the runner.
# ---------------------------------------------------------------------------


class TestFormatAndRunner:
    def test_format_emits_only_title_url_snippet(self) -> None:
        text = format_search_results(
            [
                SearchResult(
                    url="https://a.example/x",
                    title="Title A",
                    snippet="Snippet text",
                    rank=1,
                    published="2026-01-01T00:00:00Z",
                ),
                SearchResult(
                    url="https://b.example/y",
                    title="Title B",
                    snippet="",
                    rank=2,
                ),
            ]
        )
        assert "1. Title A\n   https://a.example/x\n   Snippet text" in text
        assert "2. Title B\n   https://b.example/y" in text
        # published (and any other field) is stripped from the shaped output.
        assert "2026-01-01" not in text

    def test_fields_capped_and_whitespace_flattened(self) -> None:
        text = format_search_results(
            [
                SearchResult(
                    url="https://a.example/",
                    title="T" * 1000,
                    snippet="line one\nline two\t\tspread",
                    rank=1,
                )
            ]
        )
        first_line = text.splitlines()[0]
        assert len(first_line) <= MAX_TITLE_CHARS + len("1. ")
        assert "line one line two spread" in text
        assert "\t" not in text
        assert all(len(line) <= MAX_SNIPPET_CHARS + 3 for line in text.splitlines())

    def test_empty_results_format_to_empty_string(self) -> None:
        assert format_search_results([]) == ""

    def test_runner_returns_empty_on_no_results(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """"" is the runner contract's no-results value — the tool body maps
        it to the deterministic failure notice (never raw text)."""
        _patch_door(monkeypatch, lambda url: _denied_result("policy: denied"))
        runner = make_web_search_runner(_adapter())
        assert runner("anything") == ""

    def test_runner_shapes_results(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch_door(
            monkeypatch,
            lambda url: _ok_result(
                _kagi_body(_entry("https://a.example/", "A", "snip"))
            ),
        )
        runner = make_web_search_runner(_adapter())
        out = runner("q")
        assert out.startswith("1. A\n   https://a.example/")
        assert "snip" in out

    def test_tool_body_maps_runner_empty_to_failure_notice(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """End-to-end through tools.execute: the dormant-door adapter behind
        the REAL runner yields the deterministic failure notice as the TOOL
        RESULT — never an exception, never raw text."""
        from services.assistant_orchestrator.src import tools

        _patch_door(monkeypatch, lambda url: _denied_result("policy: denied"))
        tools.register_web_search_runner(make_web_search_runner(_adapter()))
        try:
            result = tools.execute("web_search", '{"query":"anything"}')
        finally:
            tools.clear_web_search_runner()
        assert result == tools.WEB_SEARCH_ERROR_NOTICE
        assert tools.is_retrieval_notice(result)


# ---------------------------------------------------------------------------
# #727 — the fail-closed response-PARSE guard (validate-before-trust). stdlib
# json.loads has NO size or recursion-depth bound, so an oversized or
# pathologically-deep response (compromised / MITM'd Kagi endpoint) could
# resource-exhaust the host DURING parsing. The guard bounds BOTH dimensions
# BEFORE json.loads and fails closed to [] (never a raise) on violation. Every
# lock is tested ON (it BLOCKS when engaged) AND with the lock relaxed on the
# SAME body (it PARSES) — so a green result proves the CAP was the cause, not an
# unrelated skip (security-by-design principle 12).
# ---------------------------------------------------------------------------


def _deep_nested_body(levels: int) -> str:
    """A VALID Kagi v1 envelope whose ``data.search[0].props`` is a nested array
    ``levels`` deep. Under a generous depth cap it parses and yields ONE result
    ('A', since the entry carries url+title; ``props`` is ignored by the parser);
    under a tight cap the whole body is rejected unparsed."""
    nested = "[" * levels + "]" * levels
    return (
        '{"meta": {"ms": 1}, "data": {"search": [{"url": "https://a.example/", '
        '"title": "A", "props": ' + nested + "}]}}"
    )


class TestParseDepthScanner:
    """The non-recursive, string-aware depth pre-scan (``_within_parse_depth``)."""

    def test_shallow_within_limit_is_true(self) -> None:
        assert _within_parse_depth('{"a": [1, 2, 3]}', 2) is True

    def test_over_limit_is_false(self) -> None:
        assert _within_parse_depth("[[[]]]", 2) is False  # nests 3 deep

    def test_counts_both_objects_and_arrays(self) -> None:
        # An ARRAY bomb (what an object_hook would MISS) is caught.
        assert _within_parse_depth("[" * 50 + "]" * 50, 12) is False

    def test_braces_inside_strings_do_not_count(self) -> None:
        # Brackets that are STRING DATA are not structure — no false trip.
        body = '{"snippet": "' + "[" * 100 + '"}'
        assert _within_parse_depth(body, 3) is True

    def test_escaped_quote_keeps_string_open(self) -> None:
        # A backslash-escaped quote does NOT close the string, so the brackets
        # after it stay ignored (string-awareness is escape-aware).
        body = '{"s": "he said \\"' + "[" * 40 + '\\" done"}'
        assert _within_parse_depth(body, 3) is True


class TestResponseSizeGuard:
    def test_oversized_response_rejected_before_parse(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        """LOCK ON: a decoded response over the byte cap is rejected unparsed —
        [] and a fail-loud, secret-free WARNING naming the cap."""
        _patch_door(
            monkeypatch,
            lambda url: _ok_result(_kagi_body(_entry("https://a.example/", "A"))),
        )
        adapter = LiveKagiAdapter(KagiApiKey(_SENTINEL), max_response_bytes=64)
        with caplog.at_level(logging.WARNING):
            assert adapter.search_sync("q") == []
        assert "parse cap" in caplog.text
        assert _SENTINEL not in caplog.text

    def test_same_body_parses_under_a_generous_cap(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """LOCK RELAXED (toggle): the IDENTICAL body parses when the cap is wide,
        proving the block above was CAUSED by the cap, not an unrelated reason."""
        _patch_door(
            monkeypatch,
            lambda url: _ok_result(_kagi_body(_entry("https://a.example/", "A"))),
        )
        adapter = LiveKagiAdapter(KagiApiKey(_SENTINEL), max_response_bytes=10_000_000)
        assert [r.title for r in adapter.search_sync("q")] == ["A"]

    def test_normal_response_unaffected_by_the_default_cap(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Transparency: a normal Kagi reply is well under the 2 MiB default cap
        and parses unchanged through the shipped adapter."""
        _patch_door(
            monkeypatch,
            lambda url: _ok_result(
                _kagi_body(
                    _entry("https://a.example/", "A", "s1"),
                    _entry("https://b.example/", "B", "s2"),
                )
            ),
        )
        assert [r.title for r in _adapter().search_sync("q")] == ["A", "B"]

    def test_default_parse_cap_is_below_the_door_wire_cap(self) -> None:
        """COMPOSITION LOCK: the parse-side cap is a SECOND, tighter lock DOWN-
        STREAM of the egress door's on-the-wire byte cap — never a duplicate or a
        looser one. If someone widens the parse cap past the door cap, this fails
        and forces a reviewed reconciliation."""
        assert DEFAULT_MAX_RESPONSE_BYTES < guarded_fetch_mod._MAX_BODY_BYTES


class TestResponseDepthGuard:
    def test_overdeep_response_rejected_by_the_default_depth(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        """LOCK ON (shipped default depth = 12): a pathologically-deep but VALID
        JSON reply is rejected unparsed — [] + a fail-loud WARNING naming depth."""
        _patch_door(monkeypatch, lambda url: _ok_result(_deep_nested_body(40)))
        with caplog.at_level(logging.WARNING):
            assert _adapter().search_sync("q") == []
        assert "parse depth" in caplog.text
        assert _SENTINEL not in caplog.text

    def test_same_deep_body_parses_under_a_generous_depth(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """LOCK RELAXED (toggle): the IDENTICAL deep body parses when the depth
        cap is wide — proving depth was the cause. The entry has url+title, so
        it yields one result and the deep ``props`` is ignored by the parser."""
        _patch_door(monkeypatch, lambda url: _ok_result(_deep_nested_body(40)))
        adapter = LiveKagiAdapter(KagiApiKey(_SENTINEL), max_parse_depth=200)
        assert [r.title for r in adapter.search_sync("q")] == ["A"]

    def test_normal_response_within_the_default_depth(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Transparency: a real Kagi v1 reply (nests ~5) is under the 12 default
        and parses unchanged."""
        _patch_door(
            monkeypatch,
            lambda url: _ok_result(
                _kagi_body(
                    _entry("https://a.example/", "A"),
                    infobox=[{"title": "box", "url": "https://x", "snippet": "y"}],
                )
            ),
        )
        assert [r.title for r in _adapter().search_sync("q")] == ["A"]

    def test_recursion_error_at_json_loads_still_returns_empty(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        """DEFENSE-IN-DEPTH backstop (#727 NIT 2a): the never-raise contract must
        not rest on the depth pre-scan ALONE. Simulate a too-lenient / miscounting
        pre-scan (monkeypatched to accept everything) and feed a deep body that
        makes stdlib json.loads raise RecursionError — which is NOT a
        JSONDecodeError/ValueError. search_sync must still return [] and NEVER
        raise (fail-closed via the broadened `except`)."""
        # Force the pre-scan to MISS (as if it under-counted) so json.loads is
        # actually reached with the deep body.
        monkeypatch.setattr(
            live_adapter_mod, "_within_parse_depth", lambda _text, _d: True
        )
        deep = "[" * 20_000 + "]" * 20_000  # real json.loads -> RecursionError
        _patch_door(monkeypatch, lambda url: _ok_result(deep))
        with caplog.at_level(logging.ERROR):
            # Must NOT raise (RecursionError, or anything) — degrades to [].
            assert _adapter().search_sync("q") == []
        # Fail-loud: the backstop names the raised type; the key never leaks.
        assert "RecursionError" in caplog.text
        assert "backstop" in caplog.text
        assert _SENTINEL not in caplog.text


class TestParseGuardMisconfigFailClosed:
    """A bad guard bound must NEVER disarm the guard — it clamps to the safe
    default (fail-closed toward the tighter posture)."""

    def test_zero_byte_cap_clamps_to_default_not_reject_everything(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _patch_door(
            monkeypatch,
            lambda url: _ok_result(_kagi_body(_entry("https://a.example/", "A"))),
        )
        # 0 / negative would DISABLE the guard (reject-all) if honoured — the
        # adapter clamps it to DEFAULT_MAX_RESPONSE_BYTES instead.
        adapter = LiveKagiAdapter(KagiApiKey(_SENTINEL), max_response_bytes=0)
        assert adapter._max_response_bytes == DEFAULT_MAX_RESPONSE_BYTES
        assert [r.title for r in adapter.search_sync("q")] == ["A"]

    def test_bad_depth_clamps_to_default(self) -> None:
        assert (
            LiveKagiAdapter(KagiApiKey(_SENTINEL), max_parse_depth=-3)._max_parse_depth
            == DEFAULT_MAX_PARSE_DEPTH
        )
        # bool is an int subclass — must NOT slip through as depth-1.
        assert (
            LiveKagiAdapter(
                KagiApiKey(_SENTINEL), max_parse_depth=True  # type: ignore[arg-type]
            )._max_parse_depth
            == DEFAULT_MAX_PARSE_DEPTH
        )
