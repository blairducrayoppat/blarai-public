r"""Binary (image) egress door — fetch_external_binary (UC-003 Workstream B).

WHAT THIS PROVES
================
``shared.security.guarded_fetch.fetch_external_binary`` is the BINARY sibling of the
text door: the same strictly-ordered, fail-closed pipeline (SSRF guard ->
Policy-Agent adjudication -> resolution recheck -> the shared ``_fetch_raw`` transport
core), but the text decode + injection scan are replaced by ``_validate_binary_content``
— a MIME-allowlist + magic-byte gate (PNG/JPEG/GIF/WEBP only; SVG refused; header/body
mismatch refused). These tests exercise that gate end to end with the PA verdict faked
via the registration seam and ``httpx`` driven by an in-memory ``MockTransport``.

NO REAL NETWORK / NO REAL DNS
=============================
ZERO real sockets or DNS are opened — identical isolation to ``test_guarded_fetch.py``:
the PA verdict is injected via :func:`guarded_fetch.register_url_adjudicator`; the HTTP
body comes from an ``httpx.MockTransport`` injected via the test-only transport seam;
``_door_resolve`` is stubbed to a public IP. A core assertion is that the egress
allowlist is ALWAYS empty after a fetch, so no widened window can leak across tests.

REGRESSION
==========
A test in :class:`TestTextDoorUnchanged` re-asserts that the TEXT door
(:func:`fetch_external`) still works after the ``_fetch_body`` -> ``_fetch_raw`` refactor
— proving the refactor is behavior-preserving for the frozen text contract.
"""

from __future__ import annotations

import socket
from typing import Iterator

import httpx
import pytest

from shared.security import egress_guard, escalation_consent, guarded_fetch
from shared.security.escalation_consent import ApprovalResult, EscalationContext
from shared.security.guarded_fetch import (
    BinaryFetchResult,
    FetchResult,
    Verdict,
    dimension_above_max,
    dimension_below_min,
    fetch_external,
    fetch_external_binary,
    image_dimensions,
    image_dimensions_ok,
)

# A genuinely-GLOBAL public IP the good host "resolves" to in the happy path — never
# connected to (the fetch is answered by an httpx.MockTransport). Matches the value the
# sibling text-door test uses (the historical example.com IP).
_PUBLIC_TEST_IP = "93.184.216.34"

_GOOD_URL = "https://images.example/cat.png"


def _fake_addrinfo(*ips: str, port: int = 443) -> list:
    """A getaddrinfo-shaped result (5-tuples) for ``ips`` — no real DNS performed."""
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, port)) for ip in ips]


# ===========================================================================
# Minimal, REAL magic-byte image bodies (header + padding) — never decoded.
# Each is just enough of a valid signature for _validate_binary_content's sniff.
# ===========================================================================
_PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
_JPEG_BYTES = b"\xff\xd8\xff\xe0" + b"\x00" * 64
_GIF87_BYTES = b"GIF87a" + b"\x00" * 64
_GIF89_BYTES = b"GIF89a" + b"\x00" * 64
# WEBP RIFF container: b"RIFF" + 4-byte size + b"WEBP" + payload.
_WEBP_BYTES = b"RIFF" + b"\x20\x00\x00\x00" + b"WEBP" + b"\x00" * 64
# A tiny but valid SVG document (refused regardless of its bytes by the MIME check).
_SVG_BYTES = b"<svg xmlns='http://www.w3.org/2000/svg'></svg>"


# ===========================================================================
# Fixtures + helpers — isolation, the adjudicator seam, the mock transport.
# Mirrors test_guarded_fetch.py exactly so the two suites share one isolation model.
# ===========================================================================


@pytest.fixture(autouse=True)
def _pristine() -> Iterator[None]:
    """Reset every registration seam + the egress guard before AND after each test.

    Clears the URL adjudicator, the escalation verifier, the test transport, and
    fully resets the egress guard (disarm/clear-allowlist/clear-pins/rearm) so no
    widened endpoint, pinned IP, registered adjudicator/verifier, or injected
    transport can bleed across tests or into the wider suite.
    """

    def _reset() -> None:
        guarded_fetch.clear_url_adjudicator()
        guarded_fetch._set_test_transport(None)
        from shared.security import escalation_consent

        escalation_consent.clear_verifier()
        egress_guard.disarm()
        egress_guard.clear_screeners()
        egress_guard.clear_arm_hooks()
        egress_guard.clear_external_allowlist()
        egress_guard.clear_resolution_pins()
        egress_guard.rearm()

    _reset()
    yield
    _reset()


@pytest.fixture(autouse=True)
def _no_real_dns(monkeypatch: pytest.MonkeyPatch) -> None:
    """Stub the pre-fetch resolution recheck so NO test ever hits real DNS.

    Resolves the good host to a public IP so the happy-path tests proceed without a
    real lookup; auto-reverted by monkeypatch. Patches the ``_door_resolve`` seam.
    """
    monkeypatch.setattr(
        guarded_fetch,
        "_door_resolve",
        lambda host, port: _fake_addrinfo(_PUBLIC_TEST_IP),
    )


def _register_verdict(verdict: Verdict) -> None:
    """Register a fake PA adjudicator that always returns ``verdict``."""

    def _adj(url: str, purpose: str) -> Verdict:
        return verdict

    guarded_fetch.register_url_adjudicator(_adj)


def _install_transport(handler) -> None:
    """Install an httpx.MockTransport built from ``handler`` (request -> Response)."""
    guarded_fetch._set_test_transport(httpx.MockTransport(handler))


def _image_handler(body: bytes, content_type: str, status: int = 200):
    """A MockTransport handler returning ``body`` with ``content_type``."""

    def _handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, content=body, headers={"content-type": content_type})

    return _handler


class _Verifier:
    """A mock ApprovalVerifier returning a fixed approve/deny answer (#5 ESCALATE)."""

    def __init__(self, approved: bool) -> None:
        self._approved = approved

    def verify(self, context: EscalationContext) -> ApprovalResult:
        if self._approved:
            return ApprovalResult.allow(verifier_identity="mock-hello")
        return ApprovalResult.deny("operator denied", verifier_identity="mock-hello")


# ===========================================================================
# Hand-built REAL image headers (no decode lib) for the dimension read (#7).
# ===========================================================================
def _png(w: int, h: int) -> bytes:
    return (
        b"\x89PNG\r\n\x1a\n"
        + (0).to_bytes(4, "big") + b"IHDR"
        + w.to_bytes(4, "big") + h.to_bytes(4, "big")
        + b"\x00" * 8
    )


def _gif(w: int, h: int) -> bytes:
    return b"GIF89a" + w.to_bytes(2, "little") + h.to_bytes(2, "little") + b"\x00" * 8


def _jpeg(w: int, h: int) -> bytes:
    # SOI + SOF0 (len=17): precision(1) + height(2 BE) + width(2 BE) + component pad.
    return (
        b"\xff\xd8"
        + b"\xff\xc0" + (17).to_bytes(2, "big")
        + b"\x08" + h.to_bytes(2, "big") + w.to_bytes(2, "big")
        + b"\x00" * 10
    )


def _webp_vp8(w: int, h: int) -> bytes:
    return (
        b"RIFF" + (0).to_bytes(4, "little") + b"WEBP"
        + b"VP8 " + (0).to_bytes(4, "little")
        + b"\x00\x00\x00" + b"\x9d\x01\x2a"
        + (w & 0x3FFF).to_bytes(2, "little") + (h & 0x3FFF).to_bytes(2, "little")
    )


def _webp_vp8l(w: int, h: int) -> bytes:
    bits = (w - 1) | ((h - 1) << 14)
    return (
        b"RIFF" + (0).to_bytes(4, "little") + b"WEBP"
        + b"VP8L" + (0).to_bytes(4, "little")
        + b"\x2f" + bits.to_bytes(4, "little")
    )


def _webp_vp8x(w: int, h: int) -> bytes:
    return (
        b"RIFF" + (0).to_bytes(4, "little") + b"WEBP"
        + b"VP8X" + (0).to_bytes(4, "little")
        + b"\x00" + b"\x00\x00\x00"
        + (w - 1).to_bytes(3, "little") + (h - 1).to_bytes(3, "little")
    )


# ===========================================================================
# Allowlist ACCEPT — each allowlisted format with matching magic bytes fetches.
# ===========================================================================
class TestAllowlistAccept:
    @pytest.mark.parametrize(
        "body, content_type, expected_mime",
        [
            (_PNG_BYTES, "image/png", "image/png"),
            (_JPEG_BYTES, "image/jpeg", "image/jpeg"),
            (_GIF87_BYTES, "image/gif", "image/gif"),
            (_GIF89_BYTES, "image/gif", "image/gif"),
            (_WEBP_BYTES, "image/webp", "image/webp"),
        ],
        ids=["png", "jpeg", "gif87", "gif89", "webp"],
    )
    def test_allowlisted_image_is_fetched_and_validated(
        self, body: bytes, content_type: str, expected_mime: str
    ) -> None:
        _register_verdict(Verdict.ALLOW)
        _install_transport(_image_handler(body, content_type))

        result = fetch_external_binary(_GOOD_URL, purpose="uc003-image-ingest")

        assert isinstance(result, BinaryFetchResult)
        assert result.ok and result.denied_reason is None
        assert result.status == 200
        assert result.content_bytes == body
        assert result.mime == expected_mime
        assert result.content_type == content_type
        assert result.truncated is False
        # Allowlist fully reverted after the fetch.
        assert egress_guard.external_allowlist() == frozenset()

    def test_content_type_with_params_and_casing_is_normalised(self) -> None:
        # An uppercased MIME with a trailing parameter must still match the allowlist.
        _register_verdict(Verdict.ALLOW)
        _install_transport(_image_handler(_PNG_BYTES, "Image/PNG; charset=binary"))
        result = fetch_external_binary(_GOOD_URL, purpose="probe")
        assert result.ok and result.mime == "image/png"


# ===========================================================================
# MIME-allowlist REFUSE — a non-image / non-allowlisted content type is refused.
# ===========================================================================
class TestAllowlistRefuse:
    @pytest.mark.parametrize(
        "body, content_type",
        [
            (_PNG_BYTES, "text/html"),
            (_PNG_BYTES, "application/octet-stream"),
            (b"%PDF-1.4\n", "application/pdf"),
            (_PNG_BYTES, "image/tiff"),
            (_PNG_BYTES, ""),  # missing content-type
        ],
        ids=["html", "octet-stream", "pdf", "tiff", "missing"],
    )
    def test_non_allowlisted_content_type_refused(self, body: bytes, content_type: str) -> None:
        _register_verdict(Verdict.ALLOW)
        _install_transport(_image_handler(body, content_type))

        result = fetch_external_binary(_GOOD_URL, purpose="probe")

        assert not result.ok and result.denied_reason is not None
        assert result.denied_reason.startswith("content:")
        assert result.content_bytes == b""
        assert result.mime == ""
        assert egress_guard.external_allowlist() == frozenset()


# ===========================================================================
# SVG REFUSE — explicitly refused even though it is image/* (script-bearing vector).
# ===========================================================================
class TestSvgRefused:
    def test_svg_content_type_is_refused(self) -> None:
        _register_verdict(Verdict.ALLOW)
        _install_transport(_image_handler(_SVG_BYTES, "image/svg+xml"))

        result = fetch_external_binary(_GOOD_URL, purpose="probe")

        assert not result.ok
        assert result.denied_reason is not None
        assert "SVG" in result.denied_reason
        assert egress_guard.external_allowlist() == frozenset()

    def test_svg_bytes_under_png_header_is_refused_by_magic_mismatch(self) -> None:
        # SVG bytes declared as PNG: the MIME passes the allowlist but the magic-byte
        # sniff refuses the header/body mismatch (defense-in-depth).
        _register_verdict(Verdict.ALLOW)
        _install_transport(_image_handler(_SVG_BYTES, "image/png"))

        result = fetch_external_binary(_GOOD_URL, purpose="probe")

        assert not result.ok
        assert result.denied_reason is not None
        assert "signature" in result.denied_reason


# ===========================================================================
# MAGIC-BYTE MISMATCH REFUSE — a spoofed header (allowlisted MIME, wrong bytes).
# ===========================================================================
class TestMagicByteMismatch:
    @pytest.mark.parametrize(
        "body, content_type",
        [
            (_JPEG_BYTES, "image/png"),   # JPEG bytes claim PNG
            (_PNG_BYTES, "image/jpeg"),   # PNG bytes claim JPEG
            (_PNG_BYTES, "image/gif"),    # PNG bytes claim GIF
            (_PNG_BYTES, "image/webp"),   # PNG bytes claim WEBP
            (b"<html>not an image</html>", "image/png"),  # HTML claims PNG
        ],
        ids=["jpeg-as-png", "png-as-jpeg", "png-as-gif", "png-as-webp", "html-as-png"],
    )
    def test_header_body_mismatch_refused(self, body: bytes, content_type: str) -> None:
        _register_verdict(Verdict.ALLOW)
        _install_transport(_image_handler(body, content_type))

        result = fetch_external_binary(_GOOD_URL, purpose="probe")

        assert not result.ok and result.denied_reason is not None
        assert "signature" in result.denied_reason
        assert result.content_bytes == b""
        assert egress_guard.external_allowlist() == frozenset()

    def test_webp_riff_without_webp_marker_refused(self) -> None:
        # A RIFF container that is NOT a WEBP (e.g. a WAV) must be refused — the split
        # signature requires bytes[8:12] == b"WEBP".
        riff_wav = b"RIFF" + b"\x20\x00\x00\x00" + b"WAVE" + b"\x00" * 64
        _register_verdict(Verdict.ALLOW)
        _install_transport(_image_handler(riff_wav, "image/webp"))

        result = fetch_external_binary(_GOOD_URL, purpose="probe")

        assert not result.ok and result.denied_reason is not None
        assert "WEBP" in result.denied_reason

    def test_empty_body_refused(self) -> None:
        _register_verdict(Verdict.ALLOW)
        _install_transport(_image_handler(b"", "image/png"))

        result = fetch_external_binary(_GOOD_URL, purpose="probe")

        assert not result.ok and result.denied_reason is not None
        assert "empty" in result.denied_reason


# ===========================================================================
# OVERSIZE -> truncated — an over-cap image body is truncated-at-cap (streamed,
# never fully read). The truncated bytes still validate iff the magic bytes match.
# ===========================================================================
class TestOversizeTruncation:
    def test_over_cap_image_is_truncated_at_cap(self) -> None:
        # A PNG header followed by FAR more than the per-image cap of 'A' bytes.
        cap = guarded_fetch.MAX_IMAGE_BYTES
        chunk = b"A" * (1024 * 1024)  # 1 MiB chunks
        produced = {"chunks": 0}

        def _gen():
            # First chunk carries the PNG signature so the magic-byte sniff passes;
            # the rest is padding far beyond the 2-MiB image cap.
            yield b"\x89PNG\r\n\x1a\n" + chunk[8:]
            produced["chunks"] += 1
            for _ in range(8):  # 8 MiB more -> far over the 2-MiB cap
                produced["chunks"] += 1
                yield chunk

        def _handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, content=_gen(), headers={"content-type": "image/png"})

        _register_verdict(Verdict.ALLOW)
        _install_transport(_handler)

        result = fetch_external_binary(_GOOD_URL, purpose="probe")

        assert result.ok, "a truncated-but-valid PNG still validates (magic bytes intact)"
        assert result.truncated is True
        assert len(result.content_bytes) == cap, (
            f"capped image body must be exactly {cap} bytes, got {len(result.content_bytes)}"
        )
        # The generator was NOT drained — the cap stopped the read near 2 MiB, not 8+.
        assert produced["chunks"] <= 4, (
            f"streaming must stop near the cap; pulled {produced['chunks']} chunks"
        )
        assert egress_guard.external_allowlist() == frozenset()

    def test_custom_max_bytes_honored(self) -> None:
        # A small explicit cap truncates a body larger than it.
        body = b"\x89PNG\r\n\x1a\n" + b"\x00" * 4096
        _register_verdict(Verdict.ALLOW)
        _install_transport(_image_handler(body, "image/png"))

        result = fetch_external_binary(_GOOD_URL, purpose="probe", max_bytes=256)

        assert result.ok and result.truncated is True
        assert len(result.content_bytes) == 256


# ===========================================================================
# Policy gating — the dormant fail-closed default and DENY both refuse.
# ===========================================================================
class TestPolicyGating:
    def test_no_adjudicator_registered_denies(self) -> None:
        # No register_url_adjudicator call -> fail-closed DENY (the dormant default).
        # This is the weld: an image fetch refuses until the PA adjudicator is wired.
        _install_transport(_image_handler(_PNG_BYTES, "image/png"))

        result = fetch_external_binary(_GOOD_URL, purpose="probe")

        assert not result.ok and result.denied_reason is not None
        assert "no Policy-Agent adjudicator" in result.denied_reason
        assert result.content_bytes == b""
        assert egress_guard.external_allowlist() == frozenset()

    def test_deny_verdict_does_not_fetch(self) -> None:
        fetched = {"called": False}

        def _handler(request: httpx.Request) -> httpx.Response:
            fetched["called"] = True
            return httpx.Response(200, content=_PNG_BYTES, headers={"content-type": "image/png"})

        _register_verdict(Verdict.DENY)
        _install_transport(_handler)

        result = fetch_external_binary(_GOOD_URL, purpose="probe")

        assert not result.ok and result.denied_reason is not None
        assert result.denied_reason.startswith("policy:")
        assert fetched["called"] is False, "a DENY verdict must never fetch image bytes"
        assert egress_guard.external_allowlist() == frozenset()

    def test_ssrf_rejected_image_url_never_fetches(self) -> None:
        fetched = {"called": False}

        def _handler(request: httpx.Request) -> httpx.Response:
            fetched["called"] = True
            return httpx.Response(200, content=_PNG_BYTES, headers={"content-type": "image/png"})

        _register_verdict(Verdict.ALLOW)  # even with ALLOW, the SSRF guard refuses first
        _install_transport(_handler)

        result = fetch_external_binary("http://images.example/x.png", purpose="probe")

        assert not result.ok and result.denied_reason is not None
        assert result.denied_reason.startswith("SSRF guard:")
        assert fetched["called"] is False
        assert egress_guard.external_allowlist() == frozenset()


# ===========================================================================
# Allowlist hygiene — the per-fetch widen is reverted even when the fetch raises.
# ===========================================================================
class TestAllowlistHygiene:
    def test_allowlist_empty_after_transport_raises(self) -> None:
        def _raising_handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("boom")

        _register_verdict(Verdict.ALLOW)
        _install_transport(_raising_handler)

        result = fetch_external_binary(_GOOD_URL, purpose="probe")

        # The fetch failed -> denied result, NO raise out of fetch_external_binary.
        assert not result.ok and result.denied_reason is not None
        # ...and the always-runs finally-revoke ran despite the raise.
        assert egress_guard.external_allowlist() == frozenset(), (
            "the per-fetch allowlist widen MUST be reverted even when the fetch raises"
        )

    def test_allowlist_empty_after_timeout(self) -> None:
        def _timeout_handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ReadTimeout("slow")

        _register_verdict(Verdict.ALLOW)
        _install_transport(_timeout_handler)

        result = fetch_external_binary(_GOOD_URL, purpose="probe", timeout_s=0.01)

        assert not result.ok and "timed out" in result.denied_reason
        assert egress_guard.external_allowlist() == frozenset()


# ===========================================================================
# Validator unit coverage — _validate_binary_content in isolation.
# ===========================================================================
class TestValidatorUnit:
    def test_accepts_each_allowlisted_signature(self) -> None:
        for body, ct, mime in [
            (_PNG_BYTES, "image/png", "image/png"),
            (_JPEG_BYTES, "image/jpeg", "image/jpeg"),
            (_GIF89_BYTES, "image/gif", "image/gif"),
            (_WEBP_BYTES, "image/webp", "image/webp"),
        ]:
            ok, got_mime, reason = guarded_fetch._validate_binary_content(ct, body)
            assert ok and got_mime == mime and reason is None

    def test_constants_match_spec(self) -> None:
        assert guarded_fetch.IMAGE_CONTENT_TYPE_ALLOWLIST == frozenset(
            {"image/png", "image/jpeg", "image/gif", "image/webp"}
        )
        assert guarded_fetch.MAX_IMAGE_BYTES == 2 * 1024 * 1024
        assert guarded_fetch.MAX_IMAGES_PER_ARTICLE == 20
        assert guarded_fetch.MAX_TOTAL_IMAGE_BYTES == 8 * 1024 * 1024
        assert guarded_fetch.MIN_IMAGE_DIMENSION_PX == 32


# ===========================================================================
# REGRESSION — the TEXT door (fetch_external) is unchanged by the _fetch_raw refactor.
# ===========================================================================
class TestTextDoorUnchanged:
    def test_text_fetch_still_decodes_body_and_reverts_allowlist(self) -> None:
        def _handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200, content=b"<html>ok</html>", headers={"content-type": "text/html; charset=utf-8"}
            )

        _register_verdict(Verdict.ALLOW)
        _install_transport(_handler)

        result = fetch_external("https://kagi.example/path?q=1", purpose="uc003-url-ingest")

        assert isinstance(result, FetchResult)
        assert result.ok and result.denied_reason is None
        assert result.status == 200
        assert result.content_text == "<html>ok</html>"
        assert "text/html" in result.content_type
        assert egress_guard.external_allowlist() == frozenset()

    def test_text_fetch_honors_declared_non_utf8_charset(self) -> None:
        # The refactor must preserve declared-charset decoding (a Latin-1 body).
        body = "café déjà".encode("latin-1")
        _register_verdict(Verdict.ALLOW)
        _install_transport(_image_handler(body, "text/html; charset=iso-8859-1"))

        result = fetch_external("https://kagi.example/path", purpose="probe")

        assert result.ok and result.content_text == "café déjà"

    def test_utf8_fallback_wins_over_conflicting_meta(self) -> None:
        # Regression (review 2026-06-14): a garbage/UNKNOWN header charset that
        # ALSO conflicts with the page's own <meta> must decode as UTF-8 — httpx's
        # Response.encoding is NEVER None (it defaults to 'utf-8' for an absent or
        # unknown header charset), so the pre-refactor path always had a utf-8
        # candidate BEFORE the <meta>. The _fetch_body wrapper restores that with
        # `_charset_from_content_type(ct) or "utf-8"`; without it the iso-8859-1
        # meta would win and mojibake a valid-UTF-8 body. Frozen text path parity.
        body = b'<meta charset="iso-8859-1">' + "café".encode("utf-8")
        _register_verdict(Verdict.ALLOW)
        _install_transport(
            _image_handler(body, "text/html; charset=x-unknown-garbage")
        )

        result = fetch_external("https://kagi.example/path", purpose="probe")

        assert result.ok
        # utf-8 won: the é decodes correctly (iso-8859-1 would give "cafÃ©").
        assert "café" in result.content_text
        assert "Ã" not in result.content_text


# ===========================================================================
# W4 / PRIV-2 — the generic pinned User-Agent reaches the wire (BOTH doors), and
# no Cookie / Referer leaks. Captures the outgoing httpx.Request via a recording
# handler (the _active_transport seam), not just an assertion on the constant.
# ===========================================================================
class TestPinnedUserAgent:
    def _capture_request_headers(self, fetch_call) -> httpx.Headers:
        captured: dict[str, httpx.Headers] = {}

        def _handler(request: httpx.Request) -> httpx.Response:
            captured["headers"] = request.headers
            return httpx.Response(
                200, content=_PNG_BYTES, headers={"content-type": "image/png"}
            )

        _register_verdict(Verdict.ALLOW)
        _install_transport(_handler)
        fetch_call()
        return captured["headers"]

    def test_binary_door_sends_pinned_ua_no_cookie_referer(self) -> None:
        headers = self._capture_request_headers(
            lambda: fetch_external_binary(_GOOD_URL, purpose="uc003-image-ingest")
        )
        assert headers["user-agent"] == guarded_fetch._USER_AGENT
        assert "cookie" not in headers
        assert "referer" not in headers

    def test_text_door_sends_pinned_ua_no_cookie_referer(self) -> None:
        # The SHARED transport core, so the TEXT door carries the same pinned UA.
        headers = self._capture_request_headers(
            lambda: fetch_external("https://images.example/page", purpose="probe")
        )
        assert headers["user-agent"] == guarded_fetch._USER_AGENT
        assert "cookie" not in headers
        assert "referer" not in headers

    def test_user_agent_is_a_generic_browser_string(self) -> None:
        # Pinned literal: a generic modern desktop-browser UA (blends into ordinary
        # traffic), NOT a BlarAI-identifying string.
        ua = guarded_fetch._USER_AGENT
        assert ua.startswith("Mozilla/5.0")
        assert "blarai" not in ua.lower()


# ===========================================================================
# Header-only dimension read (#7) — image_dimensions / dimension_below_min.
# Pure byte parse; NO network, NO MockTransport. Hand-built real headers.
# ===========================================================================
class TestImageDimensions:
    @pytest.mark.parametrize(
        "mime, body, expected",
        [
            ("image/png", _png(64, 48), (64, 48)),
            ("image/gif", _gif(64, 48), (64, 48)),
            ("image/jpeg", _jpeg(64, 48), (64, 48)),
            ("image/webp", _webp_vp8(64, 48), (64, 48)),
            ("image/webp", _webp_vp8l(64, 48), (64, 48)),
            ("image/webp", _webp_vp8x(64, 48), (64, 48)),
        ],
        ids=["png", "gif", "jpeg", "webp-vp8", "webp-vp8l", "webp-vp8x"],
    )
    def test_reads_header_dimensions(self, mime, body, expected) -> None:
        assert image_dimensions(mime, body) == expected

    @pytest.mark.parametrize(
        "mime, body",
        [
            ("image/png", _png(16, 16)),
            ("image/png", _png(64, 16)),   # only the height is under floor
            ("image/png", _png(16, 64)),   # only the width is under floor
            ("image/gif", _gif(1, 1)),
            ("image/jpeg", _jpeg(8, 8)),
            ("image/webp", _webp_vp8(31, 31)),
            ("image/webp", _webp_vp8l(31, 200)),
            ("image/webp", _webp_vp8x(200, 31)),
        ],
        ids=["png16", "png64x16", "png16x64", "gif1", "jpeg8", "vp8-31", "vp8l-31w", "vp8x-31h"],
    )
    def test_sub_min_is_dropped(self, mime, body) -> None:
        assert dimension_below_min(mime, body) is True

    @pytest.mark.parametrize(
        "mime, body",
        [
            ("image/png", _png(32, 32)),     # exactly the floor — kept
            ("image/png", _png(64, 64)),
            ("image/jpeg", _jpeg(33, 33)),
            ("image/webp", _webp_vp8(64, 64)),
        ],
        ids=["png-floor", "png64", "jpeg33", "vp8-64"],
    )
    def test_at_or_above_min_is_kept(self, mime, body) -> None:
        assert dimension_below_min(mime, body) is False

    @pytest.mark.parametrize(
        "mime, body",
        [
            ("image/png", b"\x89PNG"),                            # truncated PNG
            ("image/webp", b"RIFF\x00\x00\x00\x00WEB"),            # truncated WEBP
            ("image/jpeg", b"\xff\xd8\xff\xe0\x00\x04\x00\x00"),   # JPEG, no SOF
            ("image/gif", b"GIF89"),                              # truncated GIF
            ("image/tiff", b"II*\x00"),                           # unknown MIME
            ("image/png", b""),                                   # empty
        ],
        ids=["png-trunc", "webp-trunc", "jpeg-no-sof", "gif-trunc", "unknown-mime", "empty"],
    )
    def test_unreadable_header_is_dropped(self, mime, body) -> None:
        # TD-4 (LA-locked 2026-06-15): an UNREADABLE header now DROPS — this
        # INVERTS the prior keep-not-drop posture.  The primitive still returns
        # None ("unknown"), and dimension_below_min still returns False on None (it
        # cannot prove "below min") — BUT the coordinator gate image_dimensions_ok
        # fails CLOSED on None: a header we cannot measure cannot be proven under
        # the decompression-bomb ceiling, so we refuse to keep it.
        assert image_dimensions(mime, body) is None
        assert dimension_below_min(mime, body) is False  # primitive unchanged
        assert image_dimensions_ok(mime, body) is False  # the gate DROPS it

    # -- W1 / BED-3 decompression-bomb ceiling + the single image_dimensions_ok gate --

    @pytest.mark.parametrize(
        "mime, body",
        [
            ("image/png", _png(16385, 100)),     # larger edge just over the 16384 max
            ("image/png", _png(100, 20000)),     # the height edge over the max
            ("image/png", _png(8000, 5001)),     # area 40.008 MP — just over 40 MP
            ("image/png", _png(40000, 40000)),   # both edges far over
        ],
        ids=["edge-16385", "edge-h-20000", "area-over-40mp", "huge"],
    )
    def test_above_max_is_flagged_and_dropped(self, mime, body) -> None:
        # A header over the max EDGE or the max AREA is a decompression-bomb
        # candidate: dimension_above_max flags it and the gate drops it.
        assert dimension_above_max(mime, body) is True
        assert image_dimensions_ok(mime, body) is False

    @pytest.mark.parametrize(
        "mime, body",
        [
            ("image/png", _png(16384, 2048)),    # edge EXACTLY at the max (area ok)
            ("image/png", _png(8000, 5000)),     # area EXACTLY 40 MP
            ("image/png", _png(1920, 1080)),     # an ordinary article photo
        ],
        ids=["edge-at-16384", "area-at-40mp", "ordinary"],
    )
    def test_at_or_under_max_is_kept(self, mime, body) -> None:
        # Both bounds are INCLUSIVE — exactly at the ceiling is permitted, one
        # pixel over is refused.
        assert dimension_above_max(mime, body) is False
        assert image_dimensions_ok(mime, body) is True

    def test_dimension_above_max_unreadable_is_false_but_gate_drops(self) -> None:
        # dimension_above_max is the AFFIRMATIVE "provably too big?" predicate (the
        # at-rest store mirror's contract), so an unreadable header is NOT "above
        # max" (False).  The COORDINATOR gate still drops it (fail-closed on None).
        unreadable = b"\x89PNG"  # truncated, no IHDR
        assert dimension_above_max("image/png", unreadable) is False
        assert image_dimensions_ok("image/png", unreadable) is False

    def test_image_dimensions_ok_enforces_min_floor(self) -> None:
        # The single gate also enforces the min floor (spacer / tracking pixel).
        assert image_dimensions_ok("image/png", _png(16, 16)) is False
        assert image_dimensions_ok("image/png", _png(32, 32)) is True

    def test_ceiling_constants_are_the_pinned_values(self) -> None:
        assert guarded_fetch.MAX_IMAGE_DIMENSION_PX == 16384
        assert guarded_fetch.MAX_IMAGE_PIXELS == 40_000_000

    def test_default_min_is_the_constant(self) -> None:
        # 32x32 (the floor) kept; 31x31 dropped — proves the default min_px is
        # MIN_IMAGE_DIMENSION_PX (32).
        assert dimension_below_min("image/png", _png(31, 31)) is True
        assert dimension_below_min("image/png", _png(32, 32)) is False
        assert guarded_fetch.MIN_IMAGE_DIMENSION_PX == 32

    def test_malformed_header_never_raises(self) -> None:
        # Adversarial garbage of every claimed MIME must return None, never raise.
        for mime in ("image/png", "image/jpeg", "image/gif", "image/webp"):
            for body in (b"", b"\x00", b"\xff" * 3, bytes(range(40))):
                assert image_dimensions(mime, body) is None

    def test_jpeg_marker_walk_skips_preceding_segments(self) -> None:
        # Real JPEGs carry APP0/DHT BEFORE the SOF — exercise the marker-walk
        # skip branch (i += seg_len), not just an SOF-immediately-after-SOI fixture.
        app0 = b"\xff\xe0" + (16).to_bytes(2, "big") + b"JFIF\x00" + b"\x00" * 9
        dht = b"\xff\xc4" + (6).to_bytes(2, "big") + b"\x00" * 4
        sof0 = (
            b"\xff\xc0" + (17).to_bytes(2, "big")
            + b"\x08" + (37).to_bytes(2, "big") + (100).to_bytes(2, "big")
            + b"\x00" * 10
        )
        jpeg = b"\xff\xd8" + app0 + dht + sof0
        assert image_dimensions("image/jpeg", jpeg) == (100, 37)

    @pytest.mark.parametrize(
        "jpeg",
        [
            b"\xff\xd8" + b"\xff\xc0" + (1).to_bytes(2, "big"),        # seg_len < 2
            b"\xff\xd8" + b"\xff\xe0" + (250).to_bytes(2, "big") + b"\x00" * 4,  # past EOF
            b"\xff\xd8" + b"\xff\xc0" + (5).to_bytes(2, "big") + b"\x00" * 3,    # SOF seg<7
            b"\xff\xd8" + b"\x00\x00",                                 # not a marker
            b"\xff\xd8" + b"\xff\xd9",                                 # EOI, no SOF
        ],
        ids=["seg-lt-2", "seg-past-eof", "sof-too-short", "misaligned", "no-sof"],
    )
    def test_malformed_jpeg_returns_none(self, jpeg: bytes) -> None:
        assert image_dimensions("image/jpeg", jpeg) is None

    @pytest.mark.parametrize("bad_mime", [123, b"image/png", None, [], {"x": 1}])
    def test_non_str_mime_never_raises(self, bad_mime) -> None:
        # The "never raises" contract holds for a non-str mime too: it coerces to
        # unknown -> None (dimensions) / refuse (validate), never an exception
        # (adversarial review, 2026-06-15).
        body = _png(64, 64)
        assert image_dimensions(bad_mime, body) is None
        ok, mime, _reason = guarded_fetch.validate_image_content(bad_mime, body)
        assert ok is False and mime == ""


# ===========================================================================
# #5 — binary-door SSRF post-resolution recheck.  A NAMED host that resolves to
# an internal/special address is DENIED before any widen or image fetch.  Mirrors
# test_guarded_fetch.py::TestNamedHostResolutionSsrf, driving fetch_external_binary.
# ===========================================================================
class TestBinaryNamedHostResolutionSsrf:
    _BLOCKED = {
        "loopback": "127.0.0.1",
        "rfc1918_10": "10.0.0.5",
        "rfc1918_192": "192.168.1.1",
        "link_local_metadata": "169.254.169.254",
        "cgnat_100_64": "100.64.0.1",
    }

    @pytest.mark.parametrize("ip", list(_BLOCKED.values()), ids=list(_BLOCKED))
    def test_name_resolving_to_internal_denied_no_widen_no_fetch(
        self, ip: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fetched = {"called": False}

        def _handler(request: httpx.Request) -> httpx.Response:
            fetched["called"] = True
            return httpx.Response(
                200, content=_PNG_BYTES, headers={"content-type": "image/png"}
            )

        # Even with the PA verdict ALLOW, the resolution recheck refuses first.
        _register_verdict(Verdict.ALLOW)
        _install_transport(_handler)
        monkeypatch.setattr(
            guarded_fetch, "_door_resolve", lambda host, port: _fake_addrinfo(ip)
        )

        result = fetch_external_binary(_GOOD_URL, purpose="probe")

        assert not result.ok and result.denied_reason is not None
        assert result.denied_reason.startswith("SSRF guard:"), result.denied_reason
        assert fetched["called"] is False, "an internal-resolving name must never fetch"
        assert result.content_bytes == b""
        assert egress_guard.external_allowlist() == frozenset()

    def test_mixed_resolution_one_internal_denied(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fetched = {"called": False}

        def _handler(request: httpx.Request) -> httpx.Response:
            fetched["called"] = True
            return httpx.Response(
                200, content=_PNG_BYTES, headers={"content-type": "image/png"}
            )

        _register_verdict(Verdict.ALLOW)
        _install_transport(_handler)
        monkeypatch.setattr(
            guarded_fetch,
            "_door_resolve",
            lambda host, port: _fake_addrinfo(_PUBLIC_TEST_IP, "10.0.0.5"),
        )

        result = fetch_external_binary(_GOOD_URL, purpose="probe")

        assert not result.ok and result.denied_reason.startswith("SSRF guard:")
        assert fetched["called"] is False
        assert egress_guard.external_allowlist() == frozenset()

    def test_resolution_failure_is_fail_closed_deny(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fetched = {"called": False}

        def _handler(request: httpx.Request) -> httpx.Response:
            fetched["called"] = True
            return httpx.Response(
                200, content=_PNG_BYTES, headers={"content-type": "image/png"}
            )

        def _boom(host, port):
            raise socket.gaierror("name resolution failed")

        _register_verdict(Verdict.ALLOW)
        _install_transport(_handler)
        monkeypatch.setattr(guarded_fetch, "_door_resolve", _boom)

        result = fetch_external_binary(_GOOD_URL, purpose="probe")

        assert not result.ok and result.denied_reason.startswith("SSRF guard:")
        assert fetched["called"] is False
        assert egress_guard.external_allowlist() == frozenset()

    def test_public_resolution_still_fetches_image(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _register_verdict(Verdict.ALLOW)
        _install_transport(_image_handler(_PNG_BYTES, "image/png"))
        monkeypatch.setattr(
            guarded_fetch, "_door_resolve", lambda host, port: _fake_addrinfo(_PUBLIC_TEST_IP)
        )
        result = fetch_external_binary(_GOOD_URL, purpose="probe")
        assert result.ok and result.mime == "image/png"
        assert result.content_bytes == _PNG_BYTES


# ===========================================================================
# #5 — binary-door ESCALATE/consent routing (#639 path).  approve -> fetch the
# image; deny / no-verifier -> DENY.  Mirrors the text door's ESCALATE cases.
# ===========================================================================
class TestBinaryEscalateConsent:
    def test_escalate_approved_fetches_image(self) -> None:
        _register_verdict(Verdict.ESCALATE)
        escalation_consent.register_verifier(_Verifier(approved=True))
        _install_transport(_image_handler(_PNG_BYTES, "image/png"))

        result = fetch_external_binary(_GOOD_URL, purpose="probe")

        assert result.ok and result.denied_reason is None
        assert result.mime == "image/png" and result.content_bytes == _PNG_BYTES
        assert egress_guard.external_allowlist() == frozenset()

    def test_escalate_denied_does_not_fetch(self) -> None:
        fetched = {"called": False}

        def _handler(request: httpx.Request) -> httpx.Response:
            fetched["called"] = True
            return httpx.Response(
                200, content=_PNG_BYTES, headers={"content-type": "image/png"}
            )

        _register_verdict(Verdict.ESCALATE)
        escalation_consent.register_verifier(_Verifier(approved=False))
        _install_transport(_handler)

        result = fetch_external_binary(_GOOD_URL, purpose="probe")

        assert not result.ok and result.denied_reason is not None
        assert "ESCALATE not approved" in result.denied_reason
        assert fetched["called"] is False
        assert egress_guard.external_allowlist() == frozenset()

    def test_escalate_no_verifier_denies(self) -> None:
        # ESCALATE with NO verifier wired -> #639 fail-closed default DENY.
        _register_verdict(Verdict.ESCALATE)
        _install_transport(_image_handler(_PNG_BYTES, "image/png"))
        result = fetch_external_binary(_GOOD_URL, purpose="probe")
        assert not result.ok and result.denied_reason is not None
        assert "ESCALATE not approved" in result.denied_reason

    def test_allow_does_not_invoke_consent(self) -> None:
        # 'URL = authorization': an ALLOW must NOT consult the consent path.
        consulted = {"called": False}

        class _ExplodingVerifier:
            def verify(self, context: EscalationContext) -> ApprovalResult:
                consulted["called"] = True
                raise AssertionError("consent must NOT be consulted on an ALLOW verdict")

        escalation_consent.register_verifier(_ExplodingVerifier())
        _register_verdict(Verdict.ALLOW)
        _install_transport(_image_handler(_PNG_BYTES, "image/png"))

        result = fetch_external_binary(_GOOD_URL, purpose="probe")

        assert result.ok and result.mime == "image/png"
        assert consulted["called"] is False
