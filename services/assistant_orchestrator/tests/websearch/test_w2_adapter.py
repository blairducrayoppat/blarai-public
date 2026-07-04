"""
W2 Kagi Adapter — unit tests.

Covers:
  - Type contract: SearchResult and SummaryResult frozen dataclass behaviour.
  - MockKagiAdapter contract: search returns fixture capped at limit; unknown
    query returns []; summarize_url returns fixture or empty SummaryResult for
    unknown URLs; neither method raises.
  - parse_kagi_search_response: well-formed input, t==1 related entries,
    malformed/empty/missing-keys input.
  - parse_kagi_summary_response: well-formed input, missing keys, malformed
    values.
  - All parsers and adapter methods are fail-closed (never raise).

asyncio_mode = "auto" in pyproject.toml — bare async def test_... works.
"""

from __future__ import annotations

import pytest

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


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_search_result(
    *,
    url: str = "https://example.com/page",
    title: str = "Example Page",
    snippet: str = "A snippet of text.",
    rank: int = 1,
    published: str | None = None,
    result_type: int = 0,
    query_source: str = "",
) -> SearchResult:
    return SearchResult(
        url=url,
        title=title,
        snippet=snippet,
        rank=rank,
        published=published,
        result_type=result_type,
        query_source=query_source,
    )


def _make_summary_result(
    *,
    url: str = "https://example.com/page",
    summary: str = "Summary text here.",
    tokens_used: int = 100,
) -> SummaryResult:
    return SummaryResult(url=url, summary=summary, tokens_used=tokens_used)


# ---------------------------------------------------------------------------
# Type tests: SearchResult
# ---------------------------------------------------------------------------


class TestSearchResultType:
    """SearchResult frozen dataclass contract."""

    def test_fields_stored_correctly(self) -> None:
        r = _make_search_result(
            url="https://nps.gov/grca",
            title="Grand Canyon",
            snippet="One of the great wonders.",
            rank=1,
            published="2026-01-15T00:00:00Z",
            result_type=0,
            query_source="grand canyon national park",
        )
        assert r.url == "https://nps.gov/grca"
        assert r.title == "Grand Canyon"
        assert r.snippet == "One of the great wonders."
        assert r.rank == 1
        assert r.published == "2026-01-15T00:00:00Z"
        assert r.result_type == 0
        assert r.query_source == "grand canyon national park"

    def test_defaults(self) -> None:
        r = SearchResult(
            url="https://a.com",
            title="T",
            snippet="S",
            rank=1,
        )
        assert r.published is None
        assert r.result_type == 0
        assert r.query_source == ""

    def test_frozen_immutability(self) -> None:
        r = _make_search_result()
        with pytest.raises(AttributeError):
            r.url = "https://mutated.com"  # type: ignore[misc]

    def test_frozen_rank_immutable(self) -> None:
        r = _make_search_result()
        with pytest.raises(AttributeError):
            r.rank = 999  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Type tests: SummaryResult
# ---------------------------------------------------------------------------


class TestSummaryResultType:
    """SummaryResult frozen dataclass contract."""

    def test_fields_stored_correctly(self) -> None:
        r = _make_summary_result(
            url="https://example.com/page",
            summary="This is the summary.",
            tokens_used=250,
        )
        assert r.url == "https://example.com/page"
        assert r.summary == "This is the summary."
        assert r.tokens_used == 250

    def test_frozen_immutability(self) -> None:
        r = _make_summary_result()
        with pytest.raises(AttributeError):
            r.summary = "mutated"  # type: ignore[misc]

    def test_frozen_tokens_immutable(self) -> None:
        r = _make_summary_result()
        with pytest.raises(AttributeError):
            r.tokens_used = 0  # type: ignore[misc]


# ---------------------------------------------------------------------------
# MockKagiAdapter — interface subclass check
# ---------------------------------------------------------------------------


class TestMockAdapterIsAbstractSubclass:
    """MockKagiAdapter must be a concrete subclass of KagiAdapter."""

    def test_isinstance_of_abstract(self) -> None:
        adapter = MockKagiAdapter()
        assert isinstance(adapter, KagiAdapter)

    def test_kagi_adapter_is_abstract(self) -> None:
        """KagiAdapter itself cannot be instantiated."""
        with pytest.raises(TypeError):
            KagiAdapter()  # type: ignore[abstract]


# ---------------------------------------------------------------------------
# MockKagiAdapter — search() contract
# ---------------------------------------------------------------------------


class TestMockAdapterSearch:
    """MockKagiAdapter.search() contract."""

    async def test_returns_fixture_for_known_query(self) -> None:
        result = _make_search_result(url="https://a.com", rank=1)
        adapter = MockKagiAdapter(search_fixture={"openVINO release notes": [result]})
        found = await adapter.search("openVINO release notes")
        assert len(found) == 1
        assert found[0].url == "https://a.com"

    async def test_returns_empty_list_for_unknown_query(self) -> None:
        adapter = MockKagiAdapter(search_fixture={})
        found = await adapter.search("query with no fixture")
        assert found == []

    async def test_limit_caps_results(self) -> None:
        results = [
            _make_search_result(url=f"https://example.com/{i}", rank=i + 1)
            for i in range(10)
        ]
        adapter = MockKagiAdapter(search_fixture={"test query": results})
        found = await adapter.search("test query", limit=3)
        assert len(found) == 3
        assert found[0].url == "https://example.com/0"

    async def test_limit_default_is_seven(self) -> None:
        results = [
            _make_search_result(url=f"https://example.com/{i}", rank=i + 1)
            for i in range(20)
        ]
        adapter = MockKagiAdapter(search_fixture={"test query": results})
        found = await adapter.search("test query")
        assert len(found) == 7

    async def test_limit_larger_than_fixture_returns_all(self) -> None:
        results = [
            _make_search_result(url=f"https://example.com/{i}", rank=i + 1)
            for i in range(3)
        ]
        adapter = MockKagiAdapter(search_fixture={"q": results})
        found = await adapter.search("q", limit=100)
        assert len(found) == 3

    async def test_search_never_raises_on_unknown_query(self) -> None:
        adapter = MockKagiAdapter()
        # Must not raise regardless of query content.
        result = await adapter.search("", limit=0)
        assert result == []

    async def test_empty_fixture_returns_empty_list(self) -> None:
        adapter = MockKagiAdapter(search_fixture={"q": []})
        found = await adapter.search("q")
        assert found == []

    async def test_multiple_distinct_queries(self) -> None:
        r1 = _make_search_result(url="https://one.com", rank=1)
        r2 = _make_search_result(url="https://two.com", rank=1)
        adapter = MockKagiAdapter(
            search_fixture={"first query": [r1], "second query": [r2]}
        )
        assert (await adapter.search("first query"))[0].url == "https://one.com"
        assert (await adapter.search("second query"))[0].url == "https://two.com"
        assert await adapter.search("third query") == []


# ---------------------------------------------------------------------------
# MockKagiAdapter — summarize_url() contract
# ---------------------------------------------------------------------------


class TestMockAdapterSummarize:
    """MockKagiAdapter.summarize_url() contract."""

    async def test_returns_fixture_for_known_url(self) -> None:
        url = "https://intel.com/openvino"
        sr = _make_summary_result(url=url, summary="OpenVINO is ...", tokens_used=80)
        adapter = MockKagiAdapter(summary_fixture={url: sr})
        result = await adapter.summarize_url(url)
        assert result.summary == "OpenVINO is ..."
        assert result.tokens_used == 80

    async def test_unknown_url_returns_empty_summary_result(self) -> None:
        adapter = MockKagiAdapter()
        url = "https://unknown.example.com/page"
        result = await adapter.summarize_url(url)
        assert result.url == url
        assert result.summary == ""
        assert result.tokens_used == 0

    async def test_summarize_url_never_raises(self) -> None:
        adapter = MockKagiAdapter()
        result = await adapter.summarize_url("")
        assert isinstance(result, SummaryResult)

    async def test_multiple_distinct_urls(self) -> None:
        url_a = "https://a.example.com"
        url_b = "https://b.example.com"
        sr_a = _make_summary_result(url=url_a, summary="Summary A", tokens_used=50)
        sr_b = _make_summary_result(url=url_b, summary="Summary B", tokens_used=75)
        adapter = MockKagiAdapter(summary_fixture={url_a: sr_a, url_b: sr_b})

        result_a = await adapter.summarize_url(url_a)
        result_b = await adapter.summarize_url(url_b)
        result_c = await adapter.summarize_url("https://c.example.com")

        assert result_a.summary == "Summary A"
        assert result_b.summary == "Summary B"
        assert result_c.summary == ""

    async def test_default_constructor_all_unknown(self) -> None:
        adapter = MockKagiAdapter()
        r1 = await adapter.summarize_url("https://any.url/1")
        r2 = await adapter.summarize_url("https://any.url/2")
        assert r1.summary == ""
        assert r2.summary == ""


# ---------------------------------------------------------------------------
# parse_kagi_search_response — well-formed input
# ---------------------------------------------------------------------------


class TestParseKagiSearchWellFormed:
    """parse_kagi_search_response with valid Kagi API response shapes."""

    def test_single_t0_result(self) -> None:
        raw = {
            "meta": {"id": "abc", "node": "us-east", "ms": 120},
            "data": [
                {
                    "t": 0,
                    "rank": 1,
                    "url": "https://nps.gov/grca/index.htm",
                    "title": "Grand Canyon National Park",
                    "snippet": "<b>Grand Canyon</b> is a steep-sided canyon.",
                    "published": "2024-03-10T00:00:00Z",
                }
            ],
        }
        results = parse_kagi_search_response(raw)
        assert len(results) == 1
        r = results[0]
        assert r.url == "https://nps.gov/grca/index.htm"
        assert r.title == "Grand Canyon National Park"
        assert r.snippet == "<b>Grand Canyon</b> is a steep-sided canyon."
        assert r.rank == 1
        assert r.published == "2024-03-10T00:00:00Z"
        assert r.result_type == 0

    def test_multiple_t0_results_rank_order(self) -> None:
        data_items = [
            {
                "t": 0,
                "rank": i,
                "url": f"https://example.com/{i}",
                "title": f"Result {i}",
                "snippet": f"Snippet {i}",
            }
            for i in range(1, 6)
        ]
        raw = {"data": data_items}
        results = parse_kagi_search_response(raw)
        assert len(results) == 5
        for idx, r in enumerate(results):
            assert r.rank == idx + 1
            assert r.result_type == 0

    def test_published_none_when_absent(self) -> None:
        raw = {
            "data": [
                {
                    "t": 0,
                    "rank": 1,
                    "url": "https://example.com",
                    "title": "Example",
                    "snippet": "Snippet",
                    # no 'published' key
                }
            ]
        }
        results = parse_kagi_search_response(raw)
        assert results[0].published is None

    def test_published_empty_string_treated_as_none(self) -> None:
        raw = {
            "data": [
                {
                    "t": 0,
                    "rank": 1,
                    "url": "https://example.com",
                    "title": "Example",
                    "snippet": "Snippet",
                    "published": "",
                }
            ]
        }
        results = parse_kagi_search_response(raw)
        assert results[0].published is None

    def test_snippet_absent_defaults_to_empty_string(self) -> None:
        raw = {
            "data": [
                {
                    "t": 0,
                    "rank": 1,
                    "url": "https://example.com",
                    "title": "Title",
                    # no snippet
                }
            ]
        }
        results = parse_kagi_search_response(raw)
        assert results[0].snippet == ""

    def test_rank_absent_falls_back_to_index(self) -> None:
        raw = {
            "data": [
                {
                    "t": 0,
                    "url": "https://a.com",
                    "title": "A",
                    "snippet": "s",
                    # no rank
                },
                {
                    "t": 0,
                    "url": "https://b.com",
                    "title": "B",
                    "snippet": "s",
                },
            ]
        }
        results = parse_kagi_search_response(raw)
        assert len(results) == 2
        assert results[0].rank == 1   # index 0 + 1
        assert results[1].rank == 2

    def test_query_source_empty_from_parser(self) -> None:
        """Parsers never set query_source — that is the loop's job (Step 2)."""
        raw = {
            "data": [
                {"t": 0, "rank": 1, "url": "https://x.com", "title": "X", "snippet": "s"}
            ]
        }
        results = parse_kagi_search_response(raw)
        assert results[0].query_source == ""

    def test_thumbnail_field_ignored(self) -> None:
        """Extra fields like 'thumbnail' are silently ignored."""
        raw = {
            "data": [
                {
                    "t": 0,
                    "rank": 1,
                    "url": "https://nps.gov/grca",
                    "title": "Grand Canyon",
                    "snippet": "Snippet",
                    "thumbnail": {"url": "https://cdn.example.com/img.jpg", "width": 320, "height": 240},
                }
            ]
        }
        results = parse_kagi_search_response(raw)
        assert len(results) == 1
        assert results[0].url == "https://nps.gov/grca"


# ---------------------------------------------------------------------------
# parse_kagi_search_response — t==1 related-search entries
# ---------------------------------------------------------------------------


class TestParseKagiSearchRelated:
    """t==1 related-search entries are mapped with result_type=1."""

    def test_t1_entry_mapped_with_result_type_1(self) -> None:
        raw = {
            "data": [
                {
                    "t": 0,
                    "rank": 1,
                    "url": "https://real.com",
                    "title": "Real Result",
                    "snippet": "A real snippet.",
                },
                {
                    "t": 1,
                    "list": ["related query A", "related query B"],
                },
            ]
        }
        results = parse_kagi_search_response(raw)
        assert len(results) == 2
        real = [r for r in results if r.result_type == 0]
        related = [r for r in results if r.result_type == 1]
        assert len(real) == 1
        assert real[0].url == "https://real.com"
        assert len(related) == 1
        assert related[0].url == ""

    def test_only_t1_entries_returns_only_related_type(self) -> None:
        raw = {
            "data": [
                {"t": 1, "list": ["query 1", "query 2"]},
            ]
        }
        results = parse_kagi_search_response(raw)
        assert len(results) == 1
        assert results[0].result_type == 1

    def test_mixed_t0_and_t1_ordering_preserved(self) -> None:
        """The order in the data array is preserved in the output list."""
        raw = {
            "data": [
                {"t": 0, "rank": 1, "url": "https://a.com", "title": "A", "snippet": ""},
                {"t": 1, "list": []},
                {"t": 0, "rank": 2, "url": "https://b.com", "title": "B", "snippet": ""},
            ]
        }
        results = parse_kagi_search_response(raw)
        assert len(results) == 3
        assert results[0].result_type == 0
        assert results[1].result_type == 1
        assert results[2].result_type == 0


# ---------------------------------------------------------------------------
# parse_kagi_search_response — malformed / missing-key inputs
# ---------------------------------------------------------------------------


class TestParseKagiSearchMalformed:
    """parse_kagi_search_response must never raise and must return safe empties."""

    def test_empty_dict_returns_empty_list(self) -> None:
        assert parse_kagi_search_response({}) == []

    def test_data_missing_returns_empty_list(self) -> None:
        assert parse_kagi_search_response({"meta": {}}) == []

    def test_data_is_none_returns_empty_list(self) -> None:
        assert parse_kagi_search_response({"data": None}) == []

    def test_data_is_string_returns_empty_list(self) -> None:
        assert parse_kagi_search_response({"data": "not a list"}) == []

    def test_data_is_empty_list(self) -> None:
        assert parse_kagi_search_response({"data": []}) == []

    def test_item_missing_t_field_skipped(self) -> None:
        raw = {
            "data": [
                {"rank": 1, "url": "https://a.com", "title": "A", "snippet": "s"},
            ]
        }
        assert parse_kagi_search_response(raw) == []

    def test_item_t_is_none_skipped(self) -> None:
        raw = {"data": [{"t": None, "rank": 1, "url": "https://a.com", "title": "A", "snippet": "s"}]}
        assert parse_kagi_search_response(raw) == []

    def test_item_t_non_integer_string_skipped(self) -> None:
        raw = {"data": [{"t": "not_an_int", "url": "https://a.com", "title": "A", "snippet": "s"}]}
        assert parse_kagi_search_response(raw) == []

    def test_item_t0_missing_url_skipped(self) -> None:
        raw = {"data": [{"t": 0, "rank": 1, "title": "No URL", "snippet": "s"}]}
        assert parse_kagi_search_response(raw) == []

    def test_item_t0_empty_url_skipped(self) -> None:
        raw = {"data": [{"t": 0, "rank": 1, "url": "", "title": "T", "snippet": "s"}]}
        assert parse_kagi_search_response(raw) == []

    def test_item_t0_url_not_string_skipped(self) -> None:
        raw = {"data": [{"t": 0, "rank": 1, "url": 12345, "title": "T", "snippet": "s"}]}
        assert parse_kagi_search_response(raw) == []

    def test_item_t0_missing_title_skipped(self) -> None:
        raw = {"data": [{"t": 0, "rank": 1, "url": "https://a.com", "snippet": "s"}]}
        assert parse_kagi_search_response(raw) == []

    def test_item_not_a_dict_skipped(self) -> None:
        raw = {"data": ["not_a_dict", 42, None]}
        assert parse_kagi_search_response(raw) == []

    def test_valid_entry_after_invalid_entry_is_kept(self) -> None:
        """A bad entry must not abort processing of subsequent entries."""
        raw = {
            "data": [
                {"t": 0},  # missing url and title — skipped
                {"t": 0, "rank": 1, "url": "https://good.com", "title": "Good", "snippet": ""},
            ]
        }
        results = parse_kagi_search_response(raw)
        assert len(results) == 1
        assert results[0].url == "https://good.com"

    def test_unknown_t_value_silently_skipped(self) -> None:
        """A future t==99 must not crash the parser."""
        raw = {
            "data": [
                {"t": 99, "url": "https://x.com"},
                {"t": 0, "rank": 1, "url": "https://good.com", "title": "G", "snippet": ""},
            ]
        }
        results = parse_kagi_search_response(raw)
        assert len(results) == 1
        assert results[0].url == "https://good.com"

    def test_rank_non_numeric_falls_back(self) -> None:
        raw = {
            "data": [
                {"t": 0, "rank": "not_a_number", "url": "https://a.com", "title": "A", "snippet": ""},
            ]
        }
        results = parse_kagi_search_response(raw)
        assert len(results) == 1
        # Falls back to idx+1 = 1 for index 0
        assert results[0].rank == 1

    def test_completely_wrong_type_does_not_raise(self) -> None:
        """Even passing a non-dict must not raise (belt-and-suspenders)."""
        # Type checker would flag this, but defensive runtime code must handle it.
        try:
            result = parse_kagi_search_response([])  # type: ignore[arg-type]
        except Exception as exc:
            pytest.fail(f"parse_kagi_search_response raised on non-dict input: {exc}")


# ---------------------------------------------------------------------------
# parse_kagi_summary_response — well-formed input
# ---------------------------------------------------------------------------


class TestParseKagiSummaryWellFormed:
    """parse_kagi_summary_response with valid Kagi Summarizer response shapes."""

    def test_well_formed_response(self) -> None:
        raw = {
            "meta": {"id": "xyz", "node": "eu-west", "ms": 3200},
            "data": {
                "output": "OpenVINO is a toolkit for optimising and deploying deep learning models.",
                "tokens": 284,
            },
            "url": "https://docs.openvino.ai",
        }
        result = parse_kagi_summary_response(raw)
        assert result.url == "https://docs.openvino.ai"
        assert result.summary == "OpenVINO is a toolkit for optimising and deploying deep learning models."
        assert result.tokens_used == 284

    def test_url_not_in_raw_defaults_to_empty_string(self) -> None:
        raw = {
            "data": {"output": "Summary here.", "tokens": 100},
        }
        result = parse_kagi_summary_response(raw)
        assert result.url == ""
        assert result.summary == "Summary here."

    def test_output_empty_string(self) -> None:
        raw = {"data": {"output": "", "tokens": 0}}
        result = parse_kagi_summary_response(raw)
        assert result.summary == ""
        assert result.tokens_used == 0

    def test_large_token_count(self) -> None:
        raw = {"data": {"output": "Long document summary.", "tokens": 10000}}
        result = parse_kagi_summary_response(raw)
        assert result.tokens_used == 10000


# ---------------------------------------------------------------------------
# parse_kagi_summary_response — malformed / missing-key inputs
# ---------------------------------------------------------------------------


class TestParseKagiSummaryMalformed:
    """parse_kagi_summary_response must never raise and return safe empties."""

    def test_empty_dict_returns_empty_summary(self) -> None:
        result = parse_kagi_summary_response({})
        assert result.summary == ""
        assert result.tokens_used == 0

    def test_data_missing_returns_empty_summary(self) -> None:
        result = parse_kagi_summary_response({"meta": {}})
        assert result.summary == ""
        assert result.tokens_used == 0

    def test_data_is_none_returns_empty_summary(self) -> None:
        result = parse_kagi_summary_response({"data": None})
        assert result.summary == ""
        assert result.tokens_used == 0

    def test_data_is_a_list_returns_empty_summary(self) -> None:
        result = parse_kagi_summary_response({"data": ["not", "a", "dict"]})
        assert result.summary == ""

    def test_output_missing_defaults_to_empty_string(self) -> None:
        result = parse_kagi_summary_response({"data": {"tokens": 50}})
        assert result.summary == ""
        assert result.tokens_used == 50

    def test_tokens_missing_defaults_to_zero(self) -> None:
        result = parse_kagi_summary_response({"data": {"output": "Some text."}})
        assert result.summary == "Some text."
        assert result.tokens_used == 0

    def test_tokens_non_numeric_defaults_to_zero(self) -> None:
        result = parse_kagi_summary_response({"data": {"output": "Text.", "tokens": "not_a_number"}})
        assert result.tokens_used == 0

    def test_tokens_float_is_truncated(self) -> None:
        result = parse_kagi_summary_response({"data": {"output": "T.", "tokens": 99.9}})
        assert result.tokens_used == 99

    def test_output_not_string_returns_empty(self) -> None:
        result = parse_kagi_summary_response({"data": {"output": 12345, "tokens": 10}})
        assert result.summary == ""

    def test_url_not_string_ignored(self) -> None:
        result = parse_kagi_summary_response({"url": 9999, "data": {"output": "Text.", "tokens": 5}})
        assert result.url == ""
        assert result.summary == "Text."

    def test_completely_wrong_type_does_not_raise(self) -> None:
        try:
            result = parse_kagi_summary_response([])  # type: ignore[arg-type]
        except Exception as exc:
            pytest.fail(f"parse_kagi_summary_response raised on non-dict input: {exc}")

    def test_none_input_does_not_raise(self) -> None:
        try:
            result = parse_kagi_summary_response(None)  # type: ignore[arg-type]
        except Exception as exc:
            pytest.fail(f"parse_kagi_summary_response raised on None input: {exc}")


# ---------------------------------------------------------------------------
# Fail-closed composite: none of the public callables ever raise
# ---------------------------------------------------------------------------


class TestFailClosedContract:
    """Belt-and-suspenders: every public callable is non-raising."""

    async def test_mock_search_non_raising_various_inputs(self) -> None:
        adapter = MockKagiAdapter()
        for query in ["", "normal query", "a" * 10_000]:
            result = await adapter.search(query, limit=0)
            assert isinstance(result, list)

    async def test_mock_summarize_non_raising_various_inputs(self) -> None:
        adapter = MockKagiAdapter()
        for url in ["", "https://normal.com", "not_a_url", "a" * 10_000]:
            result = await adapter.summarize_url(url)
            assert isinstance(result, SummaryResult)

    def test_parse_search_non_raising_on_garbage(self) -> None:
        garbage_inputs = [
            {},
            {"data": None},
            {"data": 42},
            {"data": [None, "", {}, {"t": "x"}]},
            {"data": [{"t": 0}]},
        ]
        for inp in garbage_inputs:
            result = parse_kagi_search_response(inp)
            assert isinstance(result, list)

    def test_parse_summary_non_raising_on_garbage(self) -> None:
        garbage_inputs = [
            {},
            {"data": None},
            {"data": []},
            {"data": {"output": None, "tokens": None}},
            {"data": {"tokens": "xyz"}},
        ]
        for inp in garbage_inputs:
            result = parse_kagi_summary_response(inp)
            assert isinstance(result, SummaryResult)
            assert result.summary == "" or isinstance(result.summary, str)
