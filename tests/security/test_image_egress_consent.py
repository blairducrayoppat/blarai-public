"""Unit tests for the off-site image-egress consent seam (UC-003 #663, CD-1).

Covers the same-site GRAIN (host_from_url / same_site — exact host match), the
single-verifier registry, and the fail-closed :func:`request_image_egress_consent`
consumer (no verifier / deny / approve / timeout / exception / malformed → the
only allow path is an explicit approved=True in time).  stdlib-only; no network.
"""

from __future__ import annotations

import time

import pytest

from shared.security.image_egress_consent import (
    ImageEgressConsentContext,
    ImageEgressConsentResult,
    active_image_egress_verifier,
    clear_image_egress_verifier,
    host_from_url,
    register_image_egress_verifier,
    request_image_egress_consent,
    same_site,
)


@pytest.fixture(autouse=True)
def _clear_registry():
    clear_image_egress_verifier()
    yield
    clear_image_egress_verifier()


# ---------------------------------------------------------------------------
# host_from_url + same_site (the consent grain)
# ---------------------------------------------------------------------------


class TestHostFromUrl:
    @pytest.mark.parametrize(
        "url, expected",
        [
            ("https://cdn.example/turbo.png", "cdn.example"),
            ("https://CDN.Example/Turbo.PNG", "cdn.example"),     # lowercased
            ("https://cdn.example./x.png", "cdn.example"),        # trailing dot stripped
            ("http://images.example:8443/a.png", "images.example"),  # port ignored
            ("https://sub.cdn.example/x", "sub.cdn.example"),
        ],
    )
    def test_extracts_normalised_host(self, url, expected) -> None:
        assert host_from_url(url) == expected

    @pytest.mark.parametrize(
        "url",
        [
            "/relative/path.png",          # relative — no host
            "data:image/png;base64,AAAA",  # data URI — no host
            "",                            # empty
            "   ",                         # whitespace
            "not a url at all",            # garbage
            "mailto:someone@example.com",  # no //host authority
        ],
    )
    def test_no_host_returns_none(self, url) -> None:
        assert host_from_url(url) is None

    def test_non_str_returns_none(self) -> None:
        assert host_from_url(None) is None  # type: ignore[arg-type]
        assert host_from_url(123) is None  # type: ignore[arg-type]


class TestSameSite:
    def test_exact_host_match_is_same_site(self) -> None:
        assert same_site("cdn.example", "cdn.example") is True
        assert same_site("CDN.Example", "cdn.example.") is True  # normalised

    def test_different_host_is_offsite(self) -> None:
        assert same_site("news.example", "cdn.example") is False

    def test_subdomain_is_offsite_this_pass(self) -> None:
        # THE GRAIN (this pass): exact host, NOT eTLD+1.  A subdomain is off-site.
        assert same_site("example.com", "images.example.com") is False
        assert same_site("images.example.com", "example.com") is False

    def test_none_is_never_same_site(self) -> None:
        assert same_site(None, "cdn.example") is False
        assert same_site("cdn.example", None) is False
        assert same_site(None, None) is False


# ---------------------------------------------------------------------------
# Context — safe descriptors only
# ---------------------------------------------------------------------------


class TestContext:
    def test_describe_carries_hosts_not_urls(self) -> None:
        ctx = ImageEgressConsentContext(
            article_host="news.example",
            offsite_hosts=("ads.other", "cdn.example"),
            doc_label="deadbeef",
        )
        text = ctx.describe()
        assert "news.example" in text
        assert "ads.other" in text and "cdn.example" in text
        assert "deadbeef" in text

    def test_defaults_are_empty(self) -> None:
        ctx = ImageEgressConsentContext(article_host="x.example")
        assert ctx.offsite_hosts == ()
        assert ctx.doc_label == ""


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


class _YesVerifier:
    def verify(self, context: ImageEgressConsentContext) -> ImageEgressConsentResult:
        return ImageEgressConsentResult.allow(verifier_identity="test-yes")


class TestRegistry:
    def test_register_active_clear(self) -> None:
        assert active_image_egress_verifier() is None
        v = _YesVerifier()
        register_image_egress_verifier(v)
        assert active_image_egress_verifier() is v
        clear_image_egress_verifier()
        assert active_image_egress_verifier() is None

    def test_register_replaces_single_verifier(self) -> None:
        a, b = _YesVerifier(), _YesVerifier()
        register_image_egress_verifier(a)
        register_image_egress_verifier(b)
        assert active_image_egress_verifier() is b

    def test_register_rejects_non_verifier(self) -> None:
        with pytest.raises(TypeError):
            register_image_egress_verifier(object())  # no verify method


# ---------------------------------------------------------------------------
# request_image_egress_consent — fail-closed consumer
# ---------------------------------------------------------------------------


_CTX = ImageEgressConsentContext(
    article_host="news.example",
    offsite_hosts=("cdn.example",),
    doc_label="abc12345",
)


class TestRequestConsent:
    def test_no_verifier_is_denied(self) -> None:
        result = request_image_egress_consent(_CTX)
        assert result.approved is False
        assert result.verifier_identity == "no-verifier"
        assert "no verifier" in result.reason

    def test_approve_allows(self) -> None:
        register_image_egress_verifier(_YesVerifier())
        result = request_image_egress_consent(_CTX)
        assert result.approved is True
        assert result.verifier_identity == "test-yes"

    def test_explicit_deny_denies(self) -> None:
        class _No:
            def verify(self, context):
                return ImageEgressConsentResult.deny(
                    "operator declined", verifier_identity="test-no"
                )

        register_image_egress_verifier(_No())
        result = request_image_egress_consent(_CTX)
        assert result.approved is False
        assert result.reason == "operator declined"

    def test_raising_verifier_fails_closed(self) -> None:
        class _Boom:
            def verify(self, context):
                raise RuntimeError("surface crashed")

        register_image_egress_verifier(_Boom())
        result = request_image_egress_consent(_CTX)
        assert result.approved is False
        assert "verifier error" in result.reason

    def test_none_result_fails_closed(self) -> None:
        class _ReturnsNone:
            def verify(self, context):
                return None

        register_image_egress_verifier(_ReturnsNone())
        result = request_image_egress_consent(_CTX)
        assert result.approved is False
        assert "malformed" in result.reason

    def test_malformed_result_fails_closed(self) -> None:
        class _ReturnsGarbage:
            def verify(self, context):
                return "yes please"

        register_image_egress_verifier(_ReturnsGarbage())
        result = request_image_egress_consent(_CTX)
        assert result.approved is False
        assert "malformed" in result.reason

    def test_timeout_fails_closed(self) -> None:
        class _Wedged:
            def verify(self, context):
                time.sleep(5.0)
                return ImageEgressConsentResult.allow(verifier_identity="late")

        register_image_egress_verifier(_Wedged())
        result = request_image_egress_consent(_CTX, timeout_s=0.1)
        assert result.approved is False
        assert result.reason == "timeout"
