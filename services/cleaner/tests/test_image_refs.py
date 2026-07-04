"""
Cleaner — inline image-reference helpers (UC-003 Workstream B, display-only).

Locks the three operations the host coordinator and the pipeline perform over
the inline ``![alt](url)`` refs trafilatura emits with ``include_images=True``:

* :func:`escape_image_alt` — the ALWAYS-ON hardening pass.  The security
  asserts: no ``javascript:`` (or other active scheme) and no broken-out
  markdown image syntax survives, including the two breakout shapes the
  contract spec names (``![x](javascript:alert(1))`` and the dangling
  ``![a](b) ](javascript:...)`` tail).  And the wiring assert: it is applied by
  ``clean_html`` / ``clean_text`` / ``clean_from_guest_parse``.
* :func:`extract_image_refs` — document-order, absolute-``http(s)``-only.
* :func:`rewrite_image_refs` — mapped → ``blarai-img://`` local scheme;
  unmapped → ``[image: alt]`` placeholder (never a dangling remote URL).

Plus a NO-NETWORK fixture test that ``include_images=True`` keeps a content
image inline as ``![alt](url)`` (trafilatura over a local HTML string — no
fetch).  NOTHING here touches the network: these are pure string transforms and
one local-string extraction.
"""

from __future__ import annotations

import dataclasses

import pytest

from services.cleaner.src.image_refs import (
    BLARAI_IMG_SCHEME,
    ImageRef,
    escape_image_alt,
    extract_image_refs,
    rewrite_image_refs,
)
from services.cleaner.src.pipeline import (
    clean_from_guest_parse,
    clean_html,
    clean_text,
)
from shared.ipc.parse_channel import ParseResponse

# ---------------------------------------------------------------------------
# escape_image_alt — the always-on hardening pass (security)
# ---------------------------------------------------------------------------


class TestEscapeImageAltSecurity:
    def test_active_scheme_in_url_slot_neutralized(self) -> None:
        """The contract-named case ``![x](javascript:alert(1))`` — an
        active-scheme URL in the URL slot collapses to an inert placeholder."""
        out = escape_image_alt("![x](javascript:alert(1))")
        assert "javascript:" not in out
        assert "blarai-blocked" in out  # the inert placeholder

    def test_dangling_tail_breakout_neutralized(self) -> None:
        """The contract-named case ``![a](b) ](javascript:...)`` — the forged
        ``](javascript:...)`` tail (where the leading ``![`` was consumed) must
        not survive as a navigable active-scheme link."""
        out = escape_image_alt("![a](b) ](javascript:alert(2))")
        assert "javascript:" not in out

    def test_adjacent_forged_tail_neutralized(self) -> None:
        """Tail directly abutting a prior ref: ``![a](b)](javascript:...)``."""
        out = escape_image_alt("![a](b)](javascript:alert(3))")
        assert "javascript:" not in out

    def test_early_terminating_alt_then_active_tail_neutralized(self) -> None:
        """A hostile ``]`` terminates ``![...]`` early, then a forged
        active-scheme tail follows — the tail sweep must still kill it."""
        out = escape_image_alt("![safe](https://ok.org/x.png) z](javascript:s())")
        assert "javascript:" not in out

    @pytest.mark.parametrize(
        "scheme_url",
        [
            "javascript:alert(1)",
            "data:text/html,<script>alert(1)</script>",
            "data:image/png;base64,AAAA",
            "vbscript:msgbox(1)",
            "file:///etc/passwd",
        ],
    )
    def test_dangerous_scheme_url_in_ref_neutralized(self, scheme_url: str) -> None:
        out = escape_image_alt(f"![alt]({scheme_url})")
        # The dangerous/active scheme must not survive in the URL slot.
        assert scheme_url not in out
        assert "blarai-blocked" in out

    @pytest.mark.parametrize(
        "benign_url",
        [
            "/relative/path.png",   # root-relative — benign, no active scheme
            "../up/one.png",        # path-relative
            "#anchor",              # in-page anchor
            "mailto:ops@example.org",
        ],
    )
    def test_benign_non_http_url_in_ref_preserved(self, benign_url: str) -> None:
        # Neutralization is keyed to the DANGEROUS scheme, not the absence of
        # http(s): a relative / #anchor / mailto URL is benign content and is
        # kept verbatim (Guide review fix, 2026-06-14). The coordinator's
        # rewrite + the renderer placeholder a non-fetchable image downstream.
        ref = f"![alt]({benign_url})"
        out = escape_image_alt(ref)
        assert out == ref
        assert "blarai-blocked" not in out

    def test_alt_breakout_chars_escaped(self) -> None:
        """``]``/``(``/``)`` inside a recognized ref's alt are backslash-escaped
        so they cannot terminate the syntax or open a forged tail."""
        out = escape_image_alt("![a ) paren](https://ok.org/y.png)")
        assert "\\)" in out  # the breakout ) is escaped
        assert "https://ok.org/y.png" in out  # legit URL preserved

    def test_allowlisted_http_url_preserved(self) -> None:
        ref = "![a scenic photo](https://example.org/photo.png)"
        assert escape_image_alt(ref) == ref

    def test_local_blarai_img_scheme_preserved(self) -> None:
        ref = "![cached](blarai-img://deadbeefcafe)"
        assert escape_image_alt(ref) == ref

    def test_legit_markdown_link_tail_preserved(self) -> None:
        """A genuine ``](http…)`` LINK tail (not an active scheme) is left
        intact — only non-allowlisted URLs are neutralized."""
        text = "see [the source](https://example.org/article) for more"
        assert escape_image_alt(text) == text

    def test_no_image_refs_returns_unchanged(self) -> None:
        text = "A perfectly ordinary paragraph with no image references at all."
        assert escape_image_alt(text) == text

    def test_deterministic(self) -> None:
        text = "![x](javascript:alert(1)) and ![ok](https://e.org/a.png)"
        assert escape_image_alt(text) == escape_image_alt(text)


# ---------------------------------------------------------------------------
# escape_image_alt — wired into the pipeline (always-on, regardless of locks)
# ---------------------------------------------------------------------------

_HOSTILE_IMG_HTML = (
    "<html><head><title>Hostile Image Page About Things</title></head><body>"
    "<article><h1>Hostile Image Page About Things</h1>"
    "<p>This is a long enough article body that comfortably clears the word "
    "and ratio floors so the verdict is clean and we can inspect the cleaned "
    "text for the neutralized image reference embedded in the markup below.</p>"
    '<img src="javascript:alert(1)" alt="totally innocent caption" />'
    "<p>More prose after the image so the surrounding context is captured and "
    "the extracted text stays well above the quarantine floors for a real "
    "looking article worth storing in the knowledge bank for the long term.</p>"
    "</article></body></html>"
)


class TestPipelineWiring:
    def test_clean_html_applies_escape(self) -> None:
        result = clean_html(_HOSTILE_IMG_HTML)
        assert "javascript:" not in result.text

    def test_clean_text_applies_escape(self) -> None:
        paste = (
            "Here are my notes with an embedded image reference that a hostile "
            "source planted: ![caption](javascript:alert(1)) — and the rest of "
            "the paragraph continues with enough words to clear the tiny floor "
            "comfortably so the text path produces a clean reviewable verdict."
        )
        result = clean_text(paste)
        assert "javascript:" not in result.text
        assert "alert" not in result.text or "blarai-blocked" in result.text

    def test_clean_from_guest_parse_applies_escape(self) -> None:
        response = ParseResponse(
            request_id="r-1",
            status="clean",
            text=(
                "A guest-parsed article body, long enough to clear the floors "
                "with room to spare, that carries a hostile inline image "
                "reference ![caption](javascript:alert(1)) planted by the page "
                "and several more sentences of ordinary prose afterward so the "
                "extraction ratio and word count stay comfortably above floor."
            ),
            title="Guest Parsed Title",
            byline=None,
            published_date=None,
            word_count=0,
            confidence=0.0,
            reasons=(),
        )
        result = clean_from_guest_parse(response, raw_len=4000)
        assert "javascript:" not in result.text


# ---------------------------------------------------------------------------
# extract_image_refs — ordering + absolute-http(s)-only filtering
# ---------------------------------------------------------------------------


class TestExtractImageRefs:
    def test_returns_image_refs_in_document_order(self) -> None:
        text = (
            "intro ![first](https://e.org/1.png) middle "
            "![second](http://e.org/2.jpg) end"
        )
        refs = extract_image_refs(text)
        assert refs == (
            ImageRef(alt="first", url="https://e.org/1.png"),
            ImageRef(alt="second", url="http://e.org/2.jpg"),
        )

    def test_filters_non_absolute_and_non_http_urls(self) -> None:
        text = (
            "![rel](/local/x.png) "
            "![data](data:image/png;base64,AAAA) "
            "![js](javascript:alert(1)) "
            "![local](blarai-img://abc) "
            "![empty]() "
            "![keep](https://e.org/keep.png)"
        )
        refs = extract_image_refs(text)
        assert refs == (ImageRef(alt="keep", url="https://e.org/keep.png"),)

    def test_no_refs_returns_empty_tuple(self) -> None:
        assert extract_image_refs("no images here") == ()

    def test_imageref_is_frozen(self) -> None:
        ref = ImageRef(alt="a", url="https://e.org/a.png")
        with pytest.raises(dataclasses.FrozenInstanceError):
            ref.url = "https://e.org/b.png"  # type: ignore[misc]

    def test_returns_tuple(self) -> None:
        refs = extract_image_refs("![a](https://e.org/a.png)")
        assert isinstance(refs, tuple)


# ---------------------------------------------------------------------------
# rewrite_image_refs — mapped → blarai-img://, unmapped → placeholder
# ---------------------------------------------------------------------------


class TestRewriteImageRefs:
    def test_mapped_url_rewritten_to_local_scheme(self) -> None:
        text = "before ![cap](https://e.org/a.png) after"
        out = rewrite_image_refs(text, {"https://e.org/a.png": "deadbeef"})
        assert f"![cap]({BLARAI_IMG_SCHEME}deadbeef)" in out
        assert "https://e.org/a.png" not in out

    def test_unmapped_url_dropped_to_alt_placeholder(self) -> None:
        text = "before ![a caption](https://e.org/notfetched.png) after"
        out = rewrite_image_refs(text, {})
        assert "[image: a caption]" in out
        # No dangling remote URL survives.
        assert "https://e.org/notfetched.png" not in out
        assert "![" not in out  # the image ref is gone, replaced by placeholder

    def test_mixed_mapped_and_unmapped(self) -> None:
        text = "![A](https://e.org/1.png) and ![B](https://e.org/2.png)"
        out = rewrite_image_refs(text, {"https://e.org/1.png": "id1"})
        assert f"![A]({BLARAI_IMG_SCHEME}id1)" in out
        assert "[image: B]" in out
        assert "https://e.org/2.png" not in out

    def test_alt_escaped_in_rewrite(self) -> None:
        text = "![cap ) breakout](https://e.org/a.png)"
        out = rewrite_image_refs(text, {"https://e.org/a.png": "id1"})
        assert f"![cap \\) breakout]({BLARAI_IMG_SCHEME}id1)" in out

    def test_no_refs_returns_unchanged(self) -> None:
        text = "no images at all in this text"
        assert rewrite_image_refs(text, {}) == text

    def test_deterministic(self) -> None:
        text = "![A](https://e.org/1.png) ![B](https://e.org/2.png)"
        mapping = {"https://e.org/1.png": "id1"}
        assert rewrite_image_refs(text, mapping) == rewrite_image_refs(text, mapping)


# ---------------------------------------------------------------------------
# include_images=True — content refs survive extraction (NO NETWORK)
# ---------------------------------------------------------------------------

_IMAGE_ARTICLE_HTML = (
    "<html><head><title>An Article With An Inline Content Image</title></head>"
    "<body><article><h1>An Article With An Inline Content Image</h1>"
    "<p>This opening paragraph is deliberately long so the extraction word and "
    "ratio floors are comfortably cleared and the document earns a clean "
    "verdict, letting us assert that the content image reference survived the "
    "full pipeline intact and inline within the cleaned article text body.</p>"
    '<img src="https://example.org/scenic.png" alt="A scenic photo" />'
    "<p>This closing paragraph adds yet more ordinary prose after the image so "
    "the surrounding context is captured and the whole thing reads like a real "
    "article that a knowledge store would happily keep for the long term.</p>"
    "</article></body></html>"
)


class TestIncludeImagesExtraction:
    def test_content_image_kept_inline_as_markdown_ref(self) -> None:
        """include_images=True on the trafilatura leaf keeps a content image
        inline as ``![alt](url)`` (verified over a LOCAL HTML string — no
        network).  The allowlisted https URL passes the always-on alt escape
        unchanged, so the ref survives the full pipeline."""
        result = clean_html(_IMAGE_ARTICLE_HTML)
        assert result.status == "clean"
        assert "![A scenic photo](https://example.org/scenic.png)" in result.text

    def test_extracted_ref_is_an_extract_image_refs_candidate(self) -> None:
        """End-to-end: the inline ref the pipeline produced is exactly what the
        host coordinator would enumerate to fetch."""
        result = clean_html(_IMAGE_ARTICLE_HTML)
        refs = extract_image_refs(result.text)
        assert ImageRef(
            alt="A scenic photo", url="https://example.org/scenic.png"
        ) in refs
