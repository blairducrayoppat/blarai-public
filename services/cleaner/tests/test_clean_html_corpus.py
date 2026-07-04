"""
Cleaner v1 — clean_html corpus tests (UC-003, ADR-030; Vikunja #655 Stage B).

A fixture corpus of synthesized, realistic article pages exercises the full
pipeline (trafilatura extraction → normalization → sanitization → verdict)
with NO network and NO model — trafilatura is a real installed dependency
used for real (extraction-only posture, ADR-030 §4). Each fixture locks a
specific behavior with targeted substring asserts: body retained,
boilerplate gone, metadata extracted, quarantine verdicts with stable
reason codes, determinism, and immutability.
"""

from __future__ import annotations

import dataclasses
import unicodedata
from pathlib import Path

import pytest

from services.cleaner.src.pipeline import (
    CLEANER_VERSION,
    MIN_EXTRACTION_RATIO,
    MIN_WORDS_HTML,
    REASON_EXTRACTION_FAILED,
    REASON_INJECTION_PATTERN_DETECTED,
    REASON_LOW_EXTRACTION_RATIO,
    REASON_LOW_TEXT_LENGTH,
    CleanResult,
    clean_html,
)

_FIXTURES = Path(__file__).resolve().parent / "fixtures"

_ALL_FIXTURES = (
    "news_quantum.html",
    "blog_code.html",
    "unicode_culture.html",
    "paywall_teaser.html",
    "injection_attack.html",
    "comments_section.html",
    "listicle_recipes.html",
)


def _load(name: str) -> str:
    return (_FIXTURES / name).read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Extraction quality — body retained, boilerplate gone, metadata extracted
# ---------------------------------------------------------------------------


class TestNewsArticle:
    """Standard news page: nav + ad slot + related box + footer chrome."""

    def test_clean_verdict_and_metadata(self) -> None:
        result = clean_html(_load("news_quantum.html"),
                            source_url="https://example.org/quantum-leap")
        assert result.status == "clean"
        assert result.reasons == ()
        assert result.title == "Quantum Leap in Local AI"
        assert result.byline == "Jane Mercer"
        assert result.published_date == "2026-05-14"
        assert result.word_count >= MIN_WORDS_HTML
        assert result.cleaner_version == CLEANER_VERSION
        assert result.source_format == "html"

    def test_body_retained_boilerplate_gone(self) -> None:
        result = clean_html(_load("news_quantum.html"))
        # Body prose retained.
        assert "speculative decoding scheme" in result.text
        assert "fourteen-billion-parameter model" in result.text
        # Navigation chrome gone.
        assert "Newsletter signup" not in result.text
        # Ad slot gone.
        assert "SUBSCRIBE NOW" not in result.text
        # Related-links box and footer gone.
        assert "Five laptops we like" not in result.text
        assert "TechDaily Media Group" not in result.text


class TestBlogWithCodeBlocks:
    def test_code_and_prose_retained(self) -> None:
        result = clean_html(_load("blog_code.html"))
        assert result.status == "clean"
        assert result.title == "Streaming Tokens Over a Named Pipe — A Field Note"
        assert result.byline == "Priya Raghavan"
        assert result.published_date == "2026-04-02"
        # The <pre><code> block content survives extraction.
        assert "MAX_FRAME_BYTES" in result.text
        # Surrounding prose survives too.
        assert "cap-then-allocate ordering" in result.text
        # Nav chrome gone.
        assert "blog home" not in result.text


class TestCommentsSection:
    def test_reader_comments_dropped(self) -> None:
        """include_comments=False is a pipeline decision (ADR-030 §1: reader
        comments are chrome-grade noise for a knowledge store), locked here."""
        result = clean_html(_load("comments_section.html"))
        assert result.status == "clean"
        assert "seven to two" in result.text  # council vote — article body
        assert "contingency reserve" in result.text
        assert "first!!!" not in result.text  # comment content
        assert "TaxpayerTed" not in result.text  # commenter handle
        assert "keep comments civil" not in result.text  # mod notice


class TestListicle:
    def test_list_steps_retained(self) -> None:
        result = clean_html(_load("listicle_recipes.html"))
        assert result.status == "clean"
        assert "Pat four chicken thighs dry" in result.text  # <li> content
        assert "swirl a splash of stock" in result.text
        assert "weeknight newsletter" not in result.text  # promo aside


class TestUnicodeArticle:
    """The fixture carries NFD-decomposed accents and zero-width spaces in
    its raw bytes (generated from codepoints, not typed)."""

    def test_nfc_normalized_and_invisibles_stripped(self) -> None:
        zero_width_space = chr(0x200B)
        combining_acute = chr(0x0301)
        raw = _load("unicode_culture.html")
        assert zero_width_space in raw  # the fixture really carries ZWSPs
        assert combining_acute in raw  # ... and NFD combining accents
        result = clean_html(raw)
        assert result.status == "clean"
        assert zero_width_space not in result.text
        assert unicodedata.is_normalized("NFC", result.text)
        assert "café" in result.text  # composed, not e + combining accent
        assert "東京の小さな喫茶店" in result.text  # CJK retained
        assert result.title is not None and "Café" in result.title
        assert result.byline == "Elif Demir"


# ---------------------------------------------------------------------------
# Quarantine verdicts — conservative fail-closed (ADR-030 §6)
# ---------------------------------------------------------------------------


class TestPaywallTeaser:
    def test_quarantined_low_with_text_still_carried(self) -> None:
        result = clean_html(_load("paywall_teaser.html"))
        assert result.status == "quarantined"
        assert REASON_LOW_TEXT_LENGTH in result.reasons
        assert all(reason.startswith("LOW_") for reason in result.reasons)
        assert result.word_count < MIN_WORDS_HTML
        # Quarantined results still carry the cleaned text — the operator
        # reviews it in chat; approval is the override (interface contract).
        assert "internal memo circulated last week" in result.text


class TestInjectionArticle:
    def test_quarantined_with_injection_reason(self) -> None:
        result = clean_html(_load("injection_attack.html"))
        assert result.status == "quarantined"
        assert result.reasons == (REASON_INJECTION_PATTERN_DETECTED,)
        assert result.confidence < 0.5  # injection slashes confidence

    def test_forged_delimiter_stripped_but_text_carried(self) -> None:
        raw = _load("injection_attack.html")
        assert "<|GROUNDED_CONTEXT_BEGIN|>" in raw
        result = clean_html(raw)
        # Layer-1 deterministic strip: the forged spotlighting delimiter
        # never survives into cleaned text.
        assert "<|GROUNDED_CONTEXT_BEGIN|>" not in result.text
        # The rest of the document is still reviewable (quarantine carries
        # text), including the legitimate article body.
        assert "router placement" in result.text


class TestLowExtractionRatio:
    def test_huge_page_tiny_article_quarantined(self) -> None:
        """A page whose extracted text is an anomalously small fraction of
        the raw bytes (paywall/parser-failure shape) quarantines on the
        ratio floor even when the word floor passes."""
        body = (
            "The committee published its long awaited findings on Tuesday, and "
            "the report describes in plain language how the agency repeatedly "
            "deferred maintenance on the aging flood barriers despite three "
            "internal warnings. Residents of the lower district, who petitioned "
            "for an independent review two years ago, said the conclusions "
            "matched their own experience during the autumn storms. The mayor "
            "promised a funded response within ninety days and asked the "
            "council to treat the report as the baseline for the next budget "
            "cycle. Opposition members welcomed the report but questioned "
            "whether the proposed timeline survives contact with procurement "
            "rules already in force."
        )
        junk = "".join(
            f'<script>var pad{i} = "{"x" * 200}";</script>' for i in range(2000)
        )
        page = (
            "<html><head><title>Report</title></head><body>"
            f"<article><p>{body}</p></article>{junk}</body></html>"
        )
        result = clean_html(page)
        assert result.status == "quarantined"
        assert REASON_LOW_EXTRACTION_RATIO in result.reasons
        assert result.word_count >= MIN_WORDS_HTML  # the word floor passed
        assert len(result.text) / len(page) < MIN_EXTRACTION_RATIO
        assert "flood barriers" in result.text  # text still carried


class TestExtractionFailed:
    @pytest.mark.parametrize(
        "raw",
        ["", "   \n\t  ", "<html><body></body></html>",
         "just a few plain words with no markup at all"],
        ids=["empty", "whitespace", "empty-body", "not-html"],
    )
    def test_unextractable_input_quarantined_fail_closed(self, raw: str) -> None:
        result = clean_html(raw)
        assert result.status == "quarantined"
        assert result.reasons == (REASON_EXTRACTION_FAILED,)
        assert result.text == ""
        assert result.word_count == 0
        assert result.confidence == 0.0


# ---------------------------------------------------------------------------
# Contract properties — determinism, immutability, bounds
# ---------------------------------------------------------------------------


class TestContractProperties:
    @pytest.mark.parametrize("fixture", _ALL_FIXTURES)
    def test_deterministic_two_runs_identical(self, fixture: str) -> None:
        raw = _load(fixture)
        first = clean_html(raw, source_url="https://example.org/a")
        second = clean_html(raw, source_url="https://example.org/a")
        assert first == second  # frozen dataclass equality — every field

    @pytest.mark.parametrize("fixture", _ALL_FIXTURES)
    def test_confidence_bounded_and_fields_typed(self, fixture: str) -> None:
        result = clean_html(_load(fixture))
        assert 0.0 <= result.confidence <= 1.0
        assert result.status in ("clean", "quarantined")
        assert (result.status == "clean") == (result.reasons == ())
        assert result.source_format == "html"
        assert isinstance(result.reasons, tuple)

    def test_result_is_immutable(self) -> None:
        result = clean_html(_load("news_quantum.html"))
        with pytest.raises(dataclasses.FrozenInstanceError):
            result.status = "clean"  # type: ignore[misc]
        with pytest.raises(dataclasses.FrozenInstanceError):
            result.text = "tampered"  # type: ignore[misc]
