"""
Guest parser service tests (UC-003 Stage C, ADR-030 §3; Vikunja #655).

REAL extraction, FAKE transport: trafilatura runs for real over the tracked
fixture corpus (extraction-only posture, ADR-030 §4) while the vsock layer is
an in-memory transport double — the real-VM round-trip is explicitly a later
task.  What is locked here:

* the full service loop (chunked request in → extraction + normalization +
  extraction-axis verdict → chunked response out), including multi-chunk
  bodies in BOTH directions;
* parity with the host pipeline on clean documents (same knobs, same verdict
  math — one definition in ``extraction.py``);
* the division of labor: the guest NEVER claims injection verdicts and a
  forged delimiter SURVIVES the guest response (host sanitization strips it
  after the channel — ADR-030 §5);
* fail-closed connection handling: truncation drops without a response,
  violations get one addressable error response then a drop.
"""

from __future__ import annotations

from collections import deque
from pathlib import Path

import unicodedata

import pytest

from services.cleaner.guest.parser_service import (
    DEFAULT_PARSER_PORT,
    ERROR_CHANNEL_VIOLATION,
    ERROR_RESPONSE_TOO_LARGE,
    GuestParserService,
)
from services.cleaner.src.extraction import (
    MIN_WORDS_HTML,
    REASON_EXTRACTION_FAILED,
    REASON_INJECTION_PATTERN_DETECTED,
    REASON_LOW_TEXT_LENGTH,
)
from services.cleaner.src.pipeline import clean_html
from shared.constants import GUEST_PARSER_VSOCK_PORT
from shared.ipc.parse_channel import (
    PARSE_BODY_MAX_BYTES,
    PARSE_REQUEST_ID_MAX_CHARS,
    ChunkAssembler,
    ParseResponse,
    encode_parse_request,
    decode_parse_response,
)
from shared.ipc.protocol import MessageFramer, MessageType

_FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _load_bytes(name: str) -> bytes:
    return (_FIXTURES / name).read_bytes()


class FakeTransport:
    """In-memory stand-in for VsockTransport (receive/send surface only)."""

    def __init__(self, frames: list[bytes]) -> None:
        self._inbox: deque[bytes] = deque(frames)
        self.sent: list[bytes] = []

    def receive(self) -> bytes | None:
        return self._inbox.popleft() if self._inbox else None

    def send(self, data: bytes) -> bool:
        self.sent.append(bytes(data))
        return True


class BrokenSendTransport(FakeTransport):
    def send(self, data: bytes) -> bool:
        return False


def _decode_responses(sent: list[bytes]) -> list[ParseResponse]:
    responses: list[ParseResponse] = []
    assembler = ChunkAssembler(MessageType.INGEST_PARSE_RESPONSE)
    for frame in sent:
        if assembler.feed(frame):
            responses.append(decode_parse_response(assembler))
            assembler = ChunkAssembler(MessageType.INGEST_PARSE_RESPONSE)
    assert not assembler.request_id, "trailing partial response on the wire"
    return responses


def _serve_one(
    html: bytes,
    *,
    source_url: str = "https://example.org/article",
    request_id: str = "req-1",
) -> ParseResponse:
    frames = encode_parse_request(
        request_id=request_id, html=html, source_url=source_url
    )
    transport = FakeTransport(frames)
    served = GuestParserService().serve_connection(transport)
    assert served == 1
    responses = _decode_responses(transport.sent)
    assert len(responses) == 1
    return responses[0]


def _big_article_html(paragraphs: int = 800) -> bytes:
    """A synthetic article large enough to need multiple chunks BOTH ways.

    Paragraphs are varied (trafilatura deduplicates repeats) and the total
    stays under the 262,144-byte hard cap."""
    paras = "".join(
        f"<p>Paragraph {i}: the committee reviewed agenda item {i} and recorded "
        f"a decision about budget line {i}, noting that the projected cost of "
        f"{i * 137} units exceeded the prior estimate by a measurable margin "
        f"during the session.</p>"
        for i in range(paragraphs)
    )
    html = (
        "<html><head><title>Committee Minutes, In Full</title></head>"
        f"<body><article><h1>Committee Minutes, In Full</h1>{paras}</article>"
        "</body></html>"
    )
    raw = html.encode("utf-8")
    assert len(raw) <= PARSE_BODY_MAX_BYTES
    return raw


# ---------------------------------------------------------------------------
# Extraction through the channel — real trafilatura on the fixture corpus
# ---------------------------------------------------------------------------


class TestCleanArticle:
    def test_news_article_round_trip(self) -> None:
        response = _serve_one(
            _load_bytes("news_quantum.html"),
            source_url="https://example.org/quantum-leap",
            request_id="news-1",
        )
        assert response.request_id == "news-1"  # correlation id echoed
        assert response.status == "clean"
        assert response.reasons == ()
        assert response.title == "Quantum Leap in Local AI"
        assert response.byline == "Jane Mercer"
        assert response.published_date == "2026-05-14"
        assert response.word_count >= MIN_WORDS_HTML
        assert "speculative decoding scheme" in response.text
        assert "Newsletter signup" not in response.text  # chrome gone

    def test_parity_with_host_pipeline_on_clean_document(self) -> None:
        """Same knobs, same verdict math — ONE definition (extraction.py).
        On a document with no injection findings the guest response and the
        host pipeline agree on every shared field."""
        raw = _load_bytes("news_quantum.html")
        response = _serve_one(raw, source_url="https://example.org/a")
        host = clean_html(raw.decode("utf-8"), source_url="https://example.org/a")
        assert response.text == host.text
        assert response.title == host.title
        assert response.byline == host.byline
        assert response.published_date == host.published_date
        assert response.word_count == host.word_count
        assert response.confidence == pytest.approx(host.confidence)
        assert response.status == host.status
        assert response.reasons == host.reasons

    def test_unicode_normalized_across_the_channel(self) -> None:
        zero_width_space = chr(0x200B)
        raw = _load_bytes("unicode_culture.html")
        assert zero_width_space.encode("utf-8") in raw
        response = _serve_one(raw)
        assert zero_width_space not in response.text
        assert unicodedata.is_normalized("NFC", response.text)
        assert "café" in response.text  # composed, not e + combining accent
        assert "東京の小さな喫茶店" in response.text  # CJK intact across IPC


class TestQuarantineVerdicts:
    def test_paywall_teaser_quarantined_with_text_carried(self) -> None:
        response = _serve_one(_load_bytes("paywall_teaser.html"))
        assert response.status == "quarantined"
        assert REASON_LOW_TEXT_LENGTH in response.reasons
        assert response.word_count < MIN_WORDS_HTML
        # Quarantined results still carry the cleaned text for review.
        assert "internal memo circulated last week" in response.text

    @pytest.mark.parametrize(
        "raw",
        [b"<html><body></body></html>", b"   \n\t  ",
         b"just a few plain words with no markup at all"],
        ids=["empty-body", "whitespace", "not-html"],
    )
    def test_unextractable_input_fails_closed(self, raw: bytes) -> None:
        response = _serve_one(raw)
        assert response.status == "quarantined"
        assert response.reasons == (REASON_EXTRACTION_FAILED,)
        assert response.text == ""
        assert response.word_count == 0
        assert response.confidence == 0.0

    def test_non_utf8_bytes_replacement_decoded_not_crashed(self) -> None:
        """Charset is the host fetch layer's job; mojibake is judged by the
        quality floors, never a service crash (module contract)."""
        raw = _load_bytes("news_quantum.html").replace(
            b"speculative", b"specul\xff\xfetive"
        )
        response = _serve_one(raw)
        assert response.status in ("clean", "quarantined")


class TestDivisionOfLabor:
    def test_guest_never_claims_injection_verdicts(self) -> None:
        """The injection scan is composed HOST-side (ADR-030 §5): the forged
        delimiter SURVIVES the guest response by design — host sanitization
        strips it after the channel — and the guest verdict never carries
        INJECTION_PATTERN_DETECTED."""
        raw = _load_bytes("injection_attack.html")
        assert b"<|GROUNDED_CONTEXT_BEGIN|>" in raw
        response = _serve_one(raw)
        assert REASON_INJECTION_PATTERN_DETECTED not in response.reasons
        assert "<|GROUNDED_CONTEXT_BEGIN|>" in response.text
        # The host pipeline composes the final verdict on the same bytes.
        host = clean_html(raw.decode("utf-8"))
        assert REASON_INJECTION_PATTERN_DETECTED in host.reasons
        assert "<|GROUNDED_CONTEXT_BEGIN|>" not in host.text


# ---------------------------------------------------------------------------
# Channel behavior through the service loop
# ---------------------------------------------------------------------------


class TestServiceLoop:
    def test_large_article_multi_chunk_both_directions(self) -> None:
        raw = _big_article_html()
        frames = encode_parse_request(
            request_id="big-1", html=raw, source_url="https://example.org/minutes"
        )
        assert len(frames) >= 4  # the request really exercises chunking
        transport = FakeTransport(frames)
        served = GuestParserService().serve_connection(transport)
        assert served == 1
        assert len(transport.sent) >= 4  # ... and so does the response
        (response,) = _decode_responses(transport.sent)
        assert response.status == "clean"
        assert response.title == "Committee Minutes, In Full"
        assert "agenda item 0" in response.text
        assert "agenda item 799" in response.text  # tail survived chunking

    def test_two_requests_served_on_one_connection(self) -> None:
        frames = encode_parse_request(
            request_id="seq-1", html=_load_bytes("news_quantum.html")
        ) + encode_parse_request(
            request_id="seq-2", html=_load_bytes("paywall_teaser.html")
        )
        transport = FakeTransport(frames)
        served = GuestParserService().serve_connection(transport)
        assert served == 2
        first, second = _decode_responses(transport.sent)
        assert first.request_id == "seq-1"
        assert first.status == "clean"
        assert second.request_id == "seq-2"
        assert second.status == "quarantined"

    def test_truncated_request_drops_connection_without_response(self) -> None:
        frames = encode_parse_request(request_id="trunc-1", html=_big_article_html())
        transport = FakeTransport(frames[:-1])  # final chunk never arrives
        served = GuestParserService().serve_connection(transport)
        assert served == 0
        assert transport.sent == []  # no partial/garbage response

    def test_malformed_first_frame_drops_without_response(self) -> None:
        transport = FakeTransport([b"not a frame at all"])
        served = GuestParserService().serve_connection(transport)
        assert served == 0
        assert transport.sent == []  # no request_id to address

    def test_oversize_declaration_gets_error_response_then_drop(self) -> None:
        import base64

        framer = MessageFramer()
        payload = {
            "seq": 0,
            "chunk_count": 7,
            "total_bytes": PARSE_BODY_MAX_BYTES + 1,
            "data": base64.b64encode(b"x").decode("ascii"),
            "meta": {},
        }
        frame = framer.encode(MessageType.INGEST_PARSE_REQUEST, payload, "over-1")
        transport = FakeTransport([frame])
        served = GuestParserService().serve_connection(transport)
        assert served == 0  # the request was never served...
        (response,) = _decode_responses(transport.sent)  # ...but it was answered
        assert response.request_id == "over-1"
        assert response.status == "error"
        assert response.error_code == ERROR_CHANNEL_VIOLATION
        assert response.text == ""

    def test_out_of_order_chunks_get_error_response_then_drop(self) -> None:
        frames = encode_parse_request(request_id="ooo-1", html=_big_article_html())
        transport = FakeTransport([frames[0], frames[2]])  # chunk 1 skipped
        served = GuestParserService().serve_connection(transport)
        assert served == 0
        (response,) = _decode_responses(transport.sent)
        assert response.status == "error"
        assert response.error_code == ERROR_CHANNEL_VIOLATION

    def test_send_failure_drops_connection(self) -> None:
        frames = encode_parse_request(
            request_id="bs-1", html=_load_bytes("news_quantum.html")
        )
        transport = BrokenSendTransport(frames)
        served = GuestParserService().serve_connection(transport)
        assert served == 0

    def test_idle_connection_close_is_clean(self) -> None:
        transport = FakeTransport([])
        assert GuestParserService().serve_connection(transport) == 0
        assert transport.sent == []


class TestErrorPathHardening:
    """#655 adversarial-review regression locks: the error path itself can
    never crash the listener (error-or-drop, never an escaped exception),
    and request-side violations carry the request-side error code."""

    @staticmethod
    def _violation_frame(request_id: str) -> bytes:
        """One frame carrying a NORMAL violation (oversize declaration)
        under an arbitrary *request_id*."""
        import base64

        payload = {
            "seq": 0,
            "chunk_count": 7,
            "total_bytes": PARSE_BODY_MAX_BYTES + 1,
            "data": base64.b64encode(b"x").decode("ascii"),
            "meta": {},
        }
        return MessageFramer().encode(
            MessageType.INGEST_PARSE_REQUEST, payload, request_id
        )

    def test_reproducer_huge_request_id_on_violation_drops_not_crashes(self) -> None:
        """THE reproducer: a violation frame whose request_id (~65,200 chars
        — the longest that still fits the incoming 64 KB frame) once made
        the ECHOED error response unencodable; MessageFramer.encode raised a
        PLAIN ValueError that escaped _send_error (which caught only the
        ParseChannelError subclass) and killed the whole listener.  Now the
        channel-side cap rejects the id on the FIRST frame — never recorded,
        nothing addressable — and the connection drops with no response and
        no exception."""
        frame = self._violation_frame("r" * 65_200)
        transport = FakeTransport([frame])
        served = GuestParserService().serve_connection(transport)  # must not raise
        assert served == 0
        assert transport.sent == []  # drop without a response — contract kept

    def test_at_cap_request_id_still_gets_addressable_error_response(self) -> None:
        """At exactly the cap the id is accepted and the echoed error
        response still encodes comfortably inside the 64 KB envelope."""
        rid = "r" * PARSE_REQUEST_ID_MAX_CHARS
        transport = FakeTransport([self._violation_frame(rid)])
        served = GuestParserService().serve_connection(transport)
        assert served == 0
        (response,) = _decode_responses(transport.sent)
        assert response.request_id == rid
        assert response.status == "error"
        assert response.error_code == ERROR_CHANNEL_VIOLATION

    def test_plain_valueerror_in_error_encode_drops_not_crashes(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Defense in depth for _send_error itself, independent of the id
        cap: if the error-response encode raises the PLAIN ValueError base
        class (ParseChannelError subclasses it; MessageFramer.encode raises
        the base), the connection drops — the exception never escapes
        serve_connection."""
        from services.cleaner.guest import parser_service as ps

        def raising_encode(**_kwargs: object) -> list[bytes]:
            raise ValueError("injected: envelope exceeds limit")

        monkeypatch.setattr(ps, "encode_parse_response", raising_encode)
        transport = FakeTransport([self._violation_frame("ok-id")])
        served = GuestParserService().serve_connection(transport)  # must not raise
        assert served == 0
        assert transport.sent == []

    def test_request_side_decode_violation_gets_channel_violation_code(self) -> None:
        """A request that ASSEMBLES but violates the request schema (here a
        non-string source_url meta) is a request-side channel violation —
        before the fix the shared error path mislabeled it with the
        response-side RESPONSE_TOO_LARGE code."""
        import base64

        body = b"<html><body><p>hello there</p></body></html>"
        payload = {
            "seq": 0,
            "chunk_count": 1,
            "total_bytes": len(body),
            "data": base64.b64encode(body).decode("ascii"),
            "meta": {"source_url": 123},  # assembles fine; fails request decode
        }
        frame = MessageFramer().encode(
            MessageType.INGEST_PARSE_REQUEST, payload, "decode-1"
        )
        transport = FakeTransport([frame])
        served = GuestParserService().serve_connection(transport)
        assert served == 1  # answered on a still-usable connection
        (response,) = _decode_responses(transport.sent)
        assert response.request_id == "decode-1"
        assert response.status == "error"
        assert response.error_code == ERROR_CHANNEL_VIOLATION
        assert response.error_code != ERROR_RESPONSE_TOO_LARGE

    def test_oversize_response_still_reports_response_too_large(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The response-side code stays on the response-size path — the
        request-side relabel must not absorb the encode-cap branch."""
        huge = ParseResponse(
            request_id="big-resp-1",
            status="clean",
            text="x" * (PARSE_BODY_MAX_BYTES + 1),
            title=None,
            byline=None,
            published_date=None,
            word_count=10,
            confidence=1.0,
            reasons=(),
        )
        monkeypatch.setattr(
            GuestParserService, "parse", lambda self, request: huge
        )
        frames = encode_parse_request(request_id="big-resp-1", html=b"<p>x</p>")
        transport = FakeTransport(frames)
        served = GuestParserService().serve_connection(transport)
        assert served == 1
        (response,) = _decode_responses(transport.sent)
        assert response.status == "error"
        assert response.error_code == ERROR_RESPONSE_TOO_LARGE


class TestAcceptLoopResilience:
    """#655 adversarial-review NOTE: a malformed connection must never cost
    more than that connection — main()'s accept loop survives ANY unexpected
    per-connection exception (structural log, class name only) and keeps
    serving."""

    def test_unexpected_serve_exception_does_not_kill_listener(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        import logging
        import socket as socket_module
        import threading

        from services.cleaner.guest import parser_service as ps

        caplog.set_level(logging.ERROR, logger="services.cleaner.guest.parser_service")

        listener_ready = threading.Event()
        captured: dict[str, int] = {}
        real_create = ps._create_listener_socket

        def capturing_create(transport: str, port: int) -> socket_module.socket:
            sock = real_create(transport, port)
            captured["port"] = sock.getsockname()[1]
            listener_ready.set()
            return sock

        monkeypatch.setattr(ps, "_create_listener_socket", capturing_create)

        serve_calls: list[int] = []

        def fake_serve(self: ps.GuestParserService, transport: object) -> int:
            serve_calls.append(len(serve_calls))
            if len(serve_calls) == 1:
                # The injected unexpected failure: before the catch-all this
                # killed the listener (consuming the supervisor crash budget).
                raise RuntimeError("injected: unexpected per-connection failure")
            # Second connection: terminate main() cleanly so the test can
            # observe its return code (KeyboardInterrupt is BaseException —
            # deliberately NOT swallowed by the per-connection catch-all).
            raise KeyboardInterrupt

        monkeypatch.setattr(ps.GuestParserService, "serve_connection", fake_serve)

        result: dict[str, int | None] = {"exit": None}

        def run_main() -> None:
            result["exit"] = ps.main(
                ["--transport", "tcp", "--port", "0",
                 "--timeout-s", "5", "--allow-plaintext"]
            )

        thread = threading.Thread(target=run_main, daemon=True)
        thread.start()
        try:
            assert listener_ready.wait(timeout=10), "listener never bound"
            for _ in range(2):  # connection 1 raises; connection 2 must still serve
                with socket_module.create_connection(
                    ("127.0.0.1", captured["port"]), timeout=10
                ) as client:
                    client.settimeout(10)
                    try:
                        leftover = client.recv(1)  # server closes its side
                    except OSError:
                        leftover = b""
                    assert leftover == b""
        finally:
            thread.join(timeout=15)
        assert not thread.is_alive(), "main() did not return"
        assert len(serve_calls) == 2  # the loop SURVIVED the injected failure
        assert result["exit"] == 0  # clean KeyboardInterrupt shutdown path
        # Structural log only: the exception CLASS name, never content.
        assert "listener continues" in caplog.text
        assert "RuntimeError" in caplog.text
        assert "injected: unexpected per-connection failure" not in caplog.text


class TestDeploymentContract:
    def test_default_port_locked_to_shared_constants(self) -> None:
        """parser_service redeclares the port so the guest deployment does
        not need shared/constants.py; this host-side lock keeps the two
        values from drifting (the hv_sock GUID maps 0xC351 = 50001)."""
        assert DEFAULT_PARSER_PORT == GUEST_PARSER_VSOCK_PORT == 50001
