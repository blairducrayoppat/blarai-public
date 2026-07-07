"""Regression locks for the UC-003 Workstream B adversarial-review fixes
(2026-06-14): the alt-escape whitespace bypass (MAJOR) and the edit-path
mixed-ref collapse (MAJOR).  See #663.
"""

from __future__ import annotations

import pytest

from services.cleaner.src.image_refs import (
    BLARAI_IMG_SCHEME,
    escape_image_alt,
    extract_image_refs,
    rewrite_image_refs,
)


class TestWhitespaceActiveSchemeBypass:
    """The escaper URL class must match the SAME whitespace-tolerant span the
    WinUI renderer matches (`[^)]`), so an active-scheme URL with internal
    whitespace cannot slip past both passes while the renderer still honors it.
    """

    @pytest.mark.parametrize(
        "evil",
        [
            "[x](javascript: alert)",        # space after the scheme
            "[x](javascript:\talert)",       # tab after the scheme
            "[x](javascript: alert(1))",     # space + the classic payload shape
            "[link](data: text/html,xss)",   # data: with a space
            "![x](javascript: a)",           # the same in an IMAGE alt slot
            "![a](b) ](javascript: alert)",  # dangling forged tail with a space
        ],
    )
    def test_whitespace_active_scheme_is_neutralized(self, evil: str) -> None:
        out = escape_image_alt(evil)
        # No active scheme survives anywhere in the escaped text.
        lowered = out.lower()
        assert "javascript:" not in lowered
        assert "data:" not in lowered
        assert "about:blank#blarai-blocked" in out

    def test_legitimate_https_link_is_preserved(self) -> None:
        # A normal http(s) link/image (no whitespace in the URL) is untouched.
        assert escape_image_alt("[docs](https://example.org/a)") == (
            "[docs](https://example.org/a)"
        )
        assert escape_image_alt("![photo](https://example.org/p.png)") == (
            "![photo](https://example.org/p.png)"
        )

    def test_local_scheme_preserved(self) -> None:
        ref = f"![kept](blarai-img://abc123)"
        assert escape_image_alt(ref) == ref


class TestEditPathMixedRefSurvival:
    """rewrite_image_refs must pass a surviving blarai-img:// ref through
    verbatim even when a NEW http ref coexists in the same (edited) body — never
    collapse a kept local image to a placeholder.
    """

    def test_kept_local_ref_survives_alongside_new_http(self) -> None:
        body = (
            "![kept](blarai-img://abc123)\n\n"
            "![new](https://cdn.example/new.png)"
        )
        out = rewrite_image_refs(body, {"https://cdn.example/new.png": "newid999"})
        # The kept local image is NOT collapsed to a placeholder...
        assert f"![kept]({BLARAI_IMG_SCHEME}abc123)" in out
        assert "[image: kept]" not in out
        # ...and the new http ref is rewritten to the local scheme.
        assert f"![new]({BLARAI_IMG_SCHEME}newid999)" in out
        assert "https://cdn.example/new.png" not in out

    def test_kept_local_ref_survives_in_dormant_strip(self) -> None:
        # Dormant strip path: empty mapping. The kept local ref survives; the
        # un-fetched http ref drops to a placeholder (no remote URL stored).
        body = (
            "![kept](blarai-img://abc123)\n\n"
            "![dropped](https://cdn.example/x.png)"
        )
        out = rewrite_image_refs(body, {})
        assert f"![kept]({BLARAI_IMG_SCHEME}abc123)" in out
        assert "[image: dropped]" in out
        assert "https://cdn.example/x.png" not in out

    def test_extract_ignores_local_refs(self) -> None:
        # A blarai-img:// ref is never a fetch candidate (only absolute http(s)).
        body = "![kept](blarai-img://abc123)\n![new](https://cdn.example/n.png)"
        urls = [r.url for r in extract_image_refs(body)]
        assert urls == ["https://cdn.example/n.png"]


class TestLegitLinkSurvival:
    """The escape pass must neutralize DANGEROUS schemes WITHOUT eating legitimate
    relative / #anchor / mailto links — it runs live on every paste + #663-A
    editable-preview re-clean, so over-neutralization is silent body corruption
    (Guide review, 2026-06-14).
    """

    @pytest.mark.parametrize(
        "ref",
        [
            "[see the page](/docs/page)",          # root-relative
            "[next](../other/page.html)",          # path-relative
            "[jump](#section-3)",                   # in-page anchor
            "[email me](mailto:ops@example.org)",   # mailto
            "[home](https://example.org/)",         # absolute https
            "![photo](https://example.org/p.png)",  # absolute image
            "![local](blarai-img://abc123)",        # local image scheme
        ],
    )
    def test_legitimate_links_survive_verbatim(self, ref: str) -> None:
        assert escape_image_alt(ref) == ref

    @pytest.mark.parametrize(
        "ref",
        [
            "[x](javascript:alert(1))",
            "[x](javascript: alert)",     # whitespace variant
            "[x](data:text/html,xss)",
            "[x](vbscript:msgbox)",
            "[x](file:///etc/passwd)",
            "[x](chrome://settings)",     # unknown active scheme
        ],
    )
    def test_dangerous_schemes_still_neutralized(self, ref: str) -> None:
        out = escape_image_alt(ref)
        low = out.lower()
        assert "about:blank#blarai-blocked" in out
        for bad in ("javascript:", "data:", "vbscript:", "file:", "chrome:"):
            assert bad not in low

    def test_clean_text_preserves_legit_links_neutralizes_dangerous(self) -> None:
        # The LIVE paste path: clean_text runs escape_image_alt. Legit links must
        # survive; an active-scheme link must be neutralized.
        from services.cleaner.src.pipeline import clean_text

        body = (
            "Read [the guide](/docs/guide) and [jump to top](#top), or "
            "[email the team](mailto:team@example.org) about turbochargers. "
            "Never click [this](javascript:steal()) or [that](data:text/html,x). "
            "Turbochargers compress intake air to raise engine power output."
        )
        out = clean_text(body).text
        assert "[the guide](/docs/guide)" in out
        assert "[jump to top](#top)" in out
        assert "[email the team](mailto:team@example.org)" in out
        assert "javascript:" not in out.lower()
        assert "data:text/html" not in out.lower()
        assert "about:blank#blarai-blocked" in out


class TestControlCharSchemeObfuscation:
    """A control-obfuscated active scheme (java\\tscript:, leading-\\x00
    javascript:) must NOT pass as "benign scheme-less" — a WHATWG-normalizing
    renderer strips the control chars and reconstitutes the active scheme.
    Detection runs on a control-stripped probe (Guide review, 2026-06-14).
    """

    @pytest.mark.parametrize(
        "evil",
        [
            "[x](java\tscript:alert(1))",   # tab in the scheme
            "[x](java\nscript:x)",           # newline in the scheme
            "[x](java\rscript:x)",           # CR in the scheme
            "[x](\x00javascript:alert)",     # leading NUL before the scheme
            "[x](jav\x01ascript:x)",         # other C0 control inside the scheme
            "![x](java\tscript:a)",          # the same in an IMAGE slot
        ],
    )
    def test_control_obfuscated_active_scheme_neutralized(self, evil: str) -> None:
        import re as _re

        out = escape_image_alt(evil)
        # Neutralized to the inert placeholder...
        assert "about:blank#blarai-blocked" in out
        # ...and must NOT reconstitute by stripping the control chars a renderer
        # drops (the whole point — the raw string hid the active scheme).
        reconstituted = _re.sub(r"[\x00-\x1f\x7f]", "", out).lower()
        assert "javascript:" not in reconstituted
        assert "script:" not in reconstituted

    def test_legit_links_with_no_controls_unaffected(self) -> None:
        # The control-strip probe must not disturb a clean legit URL.
        for ok in (
            "[a](https://example.org/p)",
            "[b](/rel/path)",
            "[c](#anchor)",
            "[d](mailto:a@b.co)",
            "[e](//cdn.example/x)",  # protocol-relative — benign, kept
        ):
            assert escape_image_alt(ok) == ok
