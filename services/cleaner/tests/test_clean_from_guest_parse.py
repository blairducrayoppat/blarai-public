"""
Host-side composition of a guest ParseResponse → CleanResult (UC-003 Stage C
host glue, ADR-030 §5; Vikunja #655 sub-task 6).

``clean_from_guest_parse`` closes the division of labor: the guest does
extraction + normalization + the extraction-quality verdict (injection axis =
0), and the host composes the injection axis on the returned text.  These
tests prove the composition reproduces :func:`clean_html` BYTE-IDENTICALLY on
the same bytes — so the URL-ingest verdict is single-sourced with the local
path — without re-running trafilatura host-side, plus the fail-closed edges
(empty/EXTRACTION_FAILED preserved; the upstream fetch-scan flag quarantines).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from services.cleaner.guest.parser_service import GuestParserService
from services.cleaner.src.extraction import (
    REASON_EXTRACTION_FAILED,
    REASON_INJECTION_PATTERN_DETECTED,
)
from services.cleaner.src.pipeline import clean_from_guest_parse, clean_html
from shared.ipc.parse_channel import ParseRequest, ParseResponse

_FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _load(name: str) -> bytes:
    return (_FIXTURES / name).read_bytes()


def _guest_response(raw: bytes, *, source_url: str = "") -> ParseResponse:
    """Run the REAL guest service parse (extraction-only) over *raw*."""
    return GuestParserService().parse(
        ParseRequest(request_id="r-1", source_url=source_url, html=raw)
    )


class TestParityWithHostPipeline:
    """compose(guest(raw), raw_len) == clean_html(raw) — one verdict definition."""

    @pytest.mark.parametrize(
        "fixture",
        ["news_quantum.html", "paywall_teaser.html", "unicode_culture.html"],
    )
    def test_clean_and_quarantine_docs_match_clean_html(self, fixture: str) -> None:
        raw = _load(fixture)
        html = raw.decode("utf-8")
        composed = clean_from_guest_parse(_guest_response(raw), raw_len=len(html))
        assert composed == clean_html(html)

    def test_injection_doc_matches_clean_html_after_host_compose(self) -> None:
        """The guest never claims the injection verdict; the host composition
        adds it — so the composed result matches clean_html, which DOES strip
        the delimiter and flag it (closes the ADR-030 §5 division of labor)."""
        raw = _load("injection_attack.html")
        html = raw.decode("utf-8")
        guest = _guest_response(raw)
        # Precondition: the delimiter survives the guest response by design.
        assert REASON_INJECTION_PATTERN_DETECTED not in guest.reasons
        assert "<|GROUNDED_CONTEXT_BEGIN|>" in guest.text

        composed = clean_from_guest_parse(guest, raw_len=len(html))
        host = clean_html(html)
        assert composed == host
        assert REASON_INJECTION_PATTERN_DETECTED in composed.reasons
        assert "<|GROUNDED_CONTEXT_BEGIN|>" not in composed.text


class TestFailClosedEdges:
    def test_extraction_failure_preserved_verbatim(self) -> None:
        raw = b"<html><body></body></html>"
        guest = _guest_response(raw)
        assert guest.text == "" and guest.reasons == (REASON_EXTRACTION_FAILED,)

        composed = clean_from_guest_parse(guest, raw_len=len(raw))
        assert composed.status == "quarantined"
        assert composed.text == ""
        assert composed.reasons == (REASON_EXTRACTION_FAILED,)
        assert composed.confidence == 0.0
        assert composed.source_format == "html"

    def test_empty_text_does_not_divide_by_zero(self) -> None:
        """A guest response with empty text and raw_len 0 must not raise."""
        empty = ParseResponse(
            request_id="r",
            status="quarantined",
            text="",
            title=None,
            byline=None,
            published_date=None,
            word_count=0,
            confidence=0.0,
            reasons=(REASON_EXTRACTION_FAILED,),
        )
        composed = clean_from_guest_parse(empty, raw_len=0)
        assert composed.text == ""
        assert composed.reasons == (REASON_EXTRACTION_FAILED,)

    def test_fetch_layer_injection_flag_quarantines_a_clean_doc(self) -> None:
        """A page the guest judged clean is quarantined when the host fetch
        layer (guarded_fetch) flagged injection in the raw body — defense in
        depth, fail-closed-strict."""
        raw = _load("news_quantum.html")
        html = raw.decode("utf-8")
        guest = _guest_response(raw)
        assert guest.status == "clean"

        composed = clean_from_guest_parse(
            guest, raw_len=len(html), extra_injection_findings=2
        )
        assert composed.status == "quarantined"
        assert REASON_INJECTION_PATTERN_DETECTED in composed.reasons
        # The injection confidence factor was applied (verdict degraded).
        assert composed.confidence < guest.confidence

    def test_extra_injection_findings_clamped_nonnegative(self) -> None:
        """A negative upstream count never strengthens the verdict."""
        raw = _load("news_quantum.html")
        html = raw.decode("utf-8")
        guest = _guest_response(raw)
        composed = clean_from_guest_parse(
            guest, raw_len=len(html), extra_injection_findings=-5
        )
        assert composed == clean_from_guest_parse(guest, raw_len=len(html))
