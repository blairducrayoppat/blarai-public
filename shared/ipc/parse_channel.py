"""
Guest Parse Channel — chunked framing above the 64 KB vsock frame cap
=====================================================================
UC-003 Stage C (ADR-030 §3, Vikunja #655): hostile fetched HTML is parsed
in the Hyper-V guest, never on the host.  The raw page crosses the vsock
boundary host → guest as ``INGEST_PARSE_REQUEST``; the cleaned text +
extraction metadata cross back guest → host as ``INGEST_PARSE_RESPONSE``.
A fetched page may be up to ``staging_max_bytes`` (262,144 bytes — ADR-030
§9), which does not fit the transport's 64 KB frame cap
(``VsockConfig.max_message_bytes`` / ``DEFAULT_MAX_MESSAGE_BYTES``), so this
module defines the ONE chunked framing both sides speak.

WIRE CONTRACT (cross-session — changing ANY of this is a protocol bump)
=======================================================================
A parse message (either direction) is a sequence of ordinary JSON envelopes
(``MessageFramer`` encoding; each frame individually <= 64 KB) of a single
``MessageType`` (``INGEST_PARSE_REQUEST`` or ``INGEST_PARSE_RESPONSE``):

  - The envelope ``request_id`` is the parse correlation id.  It is REQUIRED
    (non-empty, <= PARSE_REQUEST_ID_MAX_CHARS — host-minted UUIDs in
    practice), IDENTICAL on every chunk of one message, and the response
    echoes the request's ``request_id``.
  - Chunk payload schema (total-size-first, per-chunk sequence)::

        {
          "seq":         <int>,   # 0-based chunk index
          "chunk_count": <int>,   # total chunks; MUST equal
                                  # ceil(total_bytes / PARSE_CHUNK_DATA_BYTES)
          "total_bytes": <int>,   # raw body size in bytes (pre-base64);
                                  # 1 <= total_bytes <= PARSE_BODY_MAX_BYTES
          "data":        <str>,   # base64 of this chunk's raw body slice
          "meta":        <dict>   # seq 0 ONLY; absent on every later chunk
        }

  - Deterministic chunk framing: chunk ``i`` for ``i < chunk_count - 1``
    carries EXACTLY ``PARSE_CHUNK_DATA_BYTES`` raw bytes; the final chunk
    carries the remainder.  Any deviation (wrong size, wrong count, bad
    base64) is rejected — there is exactly one valid framing for a given
    body, so the framing itself is verifiable.
  - Body semantics:
      * REQUEST body  = the raw fetched HTML bytes, verbatim.
        ``meta = {"source_url": <str>}`` — extractor-heuristic metadata
        ONLY (nothing here fetches; ADR-030 §4); printable ASCII,
        <= PARSE_SOURCE_URL_MAX_CHARS (guarded_fetch URLs are ASCII —
        IDNs arrive punycoded).
      * RESPONSE body = UTF-8 JSON document::

            {"status": "clean"|"quarantined"|"error", "text": <str>,
             "title": <str|null>, "byline": <str|null>,
             "published_date": <str|null>, "word_count": <int>,
             "confidence": <float 0..1>, "reasons": [<str>...],
             "error_code": <str>, "message": <str>}

        ``reasons`` are the stable ``REASON_*`` event codes from
        ``services/cleaner/src/extraction.py``.  The guest verdict covers
        EXTRACTION-QUALITY axes only — injection sanitization runs
        host-side after the response (ADR-030 §5), so
        ``INJECTION_PATTERN_DETECTED`` never appears here.  ``error_code``
        is set (and ``text`` empty) iff ``status == "error"``.

FAIL-CLOSED RULES (both sides; every violation raises ParseChannelError)
========================================================================
  - Hard cap BOTH directions: ``total_bytes`` is validated on the FIRST
    chunk, before any buffering — an oversize declaration is rejected with
    nothing buffered, and per-chunk exact-size validation means assembly
    can never exceed the declared (already capped) total.  Encoders enforce
    the same cap, so an oversize body is unsendable, not just unreceivable.
  - Truncation: the assembler is complete ONLY after the final chunk;
    ``body()`` on an incomplete assembly raises.  A transport that returns
    None mid-message leaves a detectably incomplete assembler.
  - Reorder / duplicate / missing chunk: ``seq`` must be exactly the next
    expected index — anything else raises.
  - Cross-talk: a ``request_id`` or header (``chunk_count``/``total_bytes``)
    that changes mid-message raises.  One assembler assembles ONE message
    (sequential, like the rest of the IPC layer); construct a fresh one per
    message.
  - Each frame still rides ``MessageFramer.encode`` → the 64 KB envelope cap
    is enforced per-frame on top of everything above, and the transport's
    own ``max_message_bytes`` check backstops it.

No new dependencies: stdlib (base64/json/math) + ``shared.ipc.protocol``.
"""

from __future__ import annotations

import base64
import binascii
import json
from dataclasses import dataclass
from typing import Any

from shared.ipc.protocol import MessageFramer, MessageType

#: Hard cap on an assembled parse body, both directions — mirrors the ingest
#: ``[knowledge].staging_max_bytes`` bound (262,144; ADR-030 §9).  Enforced at
#: encode AND on the first received chunk (before buffering).
PARSE_BODY_MAX_BYTES: int = 262_144

#: Raw bytes per chunk (pre-base64).  Sized so the worst-case frame —
#: base64 data (60,000 chars) + a maximal escaped source_url + envelope
#: overhead — stays comfortably under the 64 KB frame cap.
PARSE_CHUNK_DATA_BYTES: int = 45_000

#: Maximum chunks any valid message can have (= ceil(cap / chunk size)).
PARSE_MAX_CHUNKS: int = -(-PARSE_BODY_MAX_BYTES // PARSE_CHUNK_DATA_BYTES)

#: source_url metadata bound (printable ASCII enforced separately).
PARSE_SOURCE_URL_MAX_CHARS: int = 1_024

#: Hard cap on the ``request_id`` correlation field, both directions.
#: Correlation ids are host-minted UUIDs (~36 chars); 256 leaves generous
#: headroom while keeping any envelope that ECHOES the id (the guest's
#: error response) far inside the 64 KB frame cap.  Without this cap a
#: peer-supplied id of ~65,200 chars fits the incoming frame but makes the
#: echoed error-response envelope unencodable — the over-long id must die
#: on the FIRST frame at assembly time, not at error-response encode.
PARSE_REQUEST_ID_MAX_CHARS: int = 256

#: Closed status vocabulary for the response body.
PARSE_STATUSES: frozenset[str] = frozenset({"clean", "quarantined", "error"})

#: The two message types this channel speaks.
PARSE_MESSAGE_TYPES: frozenset[MessageType] = frozenset(
    {MessageType.INGEST_PARSE_REQUEST, MessageType.INGEST_PARSE_RESPONSE}
)


class ParseChannelError(ValueError):
    """A parse-channel wire-contract violation (fail-closed, both sides)."""


# ---------------------------------------------------------------------------
# Typed message views
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ParseRequest:
    """An assembled host → guest parse request."""

    request_id: str
    """Parse correlation id (echoed on the response)."""

    source_url: str
    """Extractor-heuristic metadata only — nothing in the guest fetches."""

    html: bytes
    """The raw fetched page, verbatim (1..PARSE_BODY_MAX_BYTES bytes)."""


@dataclass(frozen=True)
class ParseResponse:
    """An assembled guest → host parse response."""

    request_id: str
    status: str
    """``clean`` | ``quarantined`` | ``error`` (closed vocabulary)."""

    text: str
    """Cleaned, normalized article text (empty on error / failed extraction)."""

    title: str | None
    byline: str | None
    published_date: str | None
    word_count: int
    confidence: float
    reasons: tuple[str, ...]
    """Stable REASON_* event codes — extraction axes only (module docstring)."""

    error_code: str = ""
    """Set iff status == 'error' (label only, never content)."""

    message: str = ""
    """Diagnostic label for error responses (never content)."""


# ---------------------------------------------------------------------------
# Chunk math
# ---------------------------------------------------------------------------


def _chunk_count_for(total_bytes: int) -> int:
    """The ONE valid chunk count for a body of *total_bytes* bytes."""
    return -(-total_bytes // PARSE_CHUNK_DATA_BYTES)


def _expected_chunk_size(seq: int, chunk_count: int, total_bytes: int) -> int:
    """The ONE valid raw size of chunk *seq* (deterministic framing)."""
    if seq < chunk_count - 1:
        return PARSE_CHUNK_DATA_BYTES
    return total_bytes - (chunk_count - 1) * PARSE_CHUNK_DATA_BYTES


def _validate_body(body: bytes, *, direction: str) -> None:
    if not isinstance(body, (bytes, bytearray)):
        raise ParseChannelError(f"{direction} body must be bytes, got {type(body).__name__}")
    if len(body) == 0:
        raise ParseChannelError(
            f"{direction} body is empty — an empty parse payload is never valid "
            "(fail-closed at encode)"
        )
    if len(body) > PARSE_BODY_MAX_BYTES:
        raise ParseChannelError(
            f"{direction} body of {len(body)} bytes exceeds the hard cap "
            f"{PARSE_BODY_MAX_BYTES} (ADR-030 §9 staging_max_bytes)"
        )


def _validate_request_id(request_id: str) -> None:
    if not isinstance(request_id, str) or not request_id.strip():
        raise ParseChannelError(
            "request_id is required on every parse-channel message "
            "(correlation across chunks and across the request/response pair)"
        )
    if len(request_id) > PARSE_REQUEST_ID_MAX_CHARS:
        raise ParseChannelError(
            f"request_id of {len(request_id)} chars exceeds "
            f"{PARSE_REQUEST_ID_MAX_CHARS} — correlation ids are host-minted "
            "UUIDs; an over-long id would overflow the echoed error-response "
            "envelope (rejected on the first frame, fail-closed)"
        )


# ---------------------------------------------------------------------------
# Encoders (encode-side validation raises — nothing invalid crosses IPC)
# ---------------------------------------------------------------------------


def _encode_chunked(
    msg_type: MessageType,
    request_id: str,
    body: bytes,
    meta: dict[str, Any],
    framer: MessageFramer,
) -> list[bytes]:
    """Chunk *body* into framed envelopes per the wire contract."""
    total_bytes = len(body)
    chunk_count = _chunk_count_for(total_bytes)
    frames: list[bytes] = []
    for seq in range(chunk_count):
        start = seq * PARSE_CHUNK_DATA_BYTES
        chunk = body[start : start + PARSE_CHUNK_DATA_BYTES]
        payload: dict[str, Any] = {
            "seq": seq,
            "chunk_count": chunk_count,
            "total_bytes": total_bytes,
            "data": base64.b64encode(chunk).decode("ascii"),
        }
        if seq == 0:
            payload["meta"] = meta
        # MessageFramer.encode enforces the 64 KB envelope cap per frame —
        # the final fail-closed backstop under this layer.
        frames.append(framer.encode(msg_type, payload, request_id))
    return frames


def encode_parse_request(
    *,
    request_id: str,
    html: bytes,
    source_url: str = "",
    framer: MessageFramer | None = None,
) -> list[bytes]:
    """Encode a host → guest parse request into chunked frames.

    Raises:
        ParseChannelError: empty/oversize *html*, missing *request_id*, or a
            *source_url* that is non-ASCII / non-printable / over
            ``PARSE_SOURCE_URL_MAX_CHARS`` (fail-closed at encode).
    """
    _validate_request_id(request_id)
    _validate_body(html, direction="request")
    if not isinstance(source_url, str):
        raise ParseChannelError(
            f"source_url must be str, got {type(source_url).__name__}"
        )
    if len(source_url) > PARSE_SOURCE_URL_MAX_CHARS:
        raise ParseChannelError(
            f"source_url of {len(source_url)} chars exceeds "
            f"{PARSE_SOURCE_URL_MAX_CHARS} (chunk-0 frame budget)"
        )
    if any(not (0x20 <= ord(ch) < 0x7F) for ch in source_url):
        raise ParseChannelError(
            "source_url must be printable ASCII — guarded_fetch URLs are "
            "ASCII (IDNs arrive punycoded); anything else breaks the chunk-0 "
            "frame-size guarantee"
        )
    return _encode_chunked(
        MessageType.INGEST_PARSE_REQUEST,
        request_id,
        bytes(html),
        {"source_url": source_url},
        framer or MessageFramer(),
    )


def encode_parse_response(
    *,
    request_id: str,
    status: str,
    text: str,
    title: str | None = None,
    byline: str | None = None,
    published_date: str | None = None,
    word_count: int = 0,
    confidence: float = 0.0,
    reasons: tuple[str, ...] = (),
    error_code: str = "",
    message: str = "",
    framer: MessageFramer | None = None,
) -> list[bytes]:
    """Encode a guest → host parse response into chunked frames.

    Raises:
        ParseChannelError: unknown *status*, ``status == 'error'`` without an
            *error_code* (or an *error_code* on a non-error), out-of-range
            *confidence* / *word_count*, or a serialized body over the hard
            cap (fail-closed at encode — the service maps that to a small
            RESPONSE_TOO_LARGE error response instead).
    """
    _validate_request_id(request_id)
    if status not in PARSE_STATUSES:
        raise ParseChannelError(
            f"status {status!r} not in closed vocabulary {sorted(PARSE_STATUSES)}"
        )
    if status == "error" and not error_code.strip():
        raise ParseChannelError("status 'error' requires a non-empty error_code")
    if status != "error" and error_code:
        raise ParseChannelError(
            f"error_code {error_code!r} is only valid with status 'error'"
        )
    if not isinstance(word_count, int) or isinstance(word_count, bool) or word_count < 0:
        raise ParseChannelError(f"word_count must be an int >= 0, got {word_count!r}")
    if not 0.0 <= float(confidence) <= 1.0:
        raise ParseChannelError(f"confidence must be within [0, 1], got {confidence!r}")
    if not all(isinstance(reason, str) and reason for reason in reasons):
        raise ParseChannelError(f"reasons must be non-empty strings, got {reasons!r}")

    body = json.dumps(
        {
            "status": status,
            "text": text,
            "title": title,
            "byline": byline,
            "published_date": published_date,
            "word_count": word_count,
            "confidence": float(confidence),
            "reasons": list(reasons),
            "error_code": error_code,
            "message": message,
        },
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    _validate_body(body, direction="response")
    return _encode_chunked(
        MessageType.INGEST_PARSE_RESPONSE,
        request_id,
        body,
        {},
        framer or MessageFramer(),
    )


# ---------------------------------------------------------------------------
# Assembler (receive side — fail-closed on every contract violation)
# ---------------------------------------------------------------------------


class ChunkAssembler:
    """Assembles ONE chunked parse message from framed envelopes.

    Feed each received frame in arrival order; ``feed`` returns True when the
    message is complete.  Every wire-contract violation raises
    :class:`ParseChannelError` — the assembler is then poisoned and the
    caller drops the connection (no resync on a corrupted stream).

    ``request_id`` is recorded from the FIRST frame before size validation,
    so a service can still address an error response after rejecting an
    oversize declaration.
    """

    def __init__(
        self,
        expected_type: MessageType,
        *,
        framer: MessageFramer | None = None,
    ) -> None:
        if expected_type not in PARSE_MESSAGE_TYPES:
            raise ParseChannelError(
                f"{expected_type.value} is not a parse-channel message type"
            )
        self._expected_type = expected_type
        self._framer = framer or MessageFramer()
        self._request_id: str = ""
        self._meta: dict[str, Any] = {}
        self._chunk_count: int = 0
        self._total_bytes: int = 0
        self._next_seq: int = 0
        self._buffer = bytearray()
        self._complete = False

    @property
    def expected_type(self) -> MessageType:
        """The message type this assembler accepts."""
        return self._expected_type

    @property
    def complete(self) -> bool:
        """True once the final chunk has been assembled and verified."""
        return self._complete

    @property
    def request_id(self) -> str:
        """The correlation id ('' until the first frame carries one)."""
        return self._request_id

    @property
    def meta(self) -> dict[str, Any]:
        """The chunk-0 metadata object (empty until chunk 0 is accepted)."""
        return dict(self._meta)

    def body(self) -> bytes:
        """The assembled body.

        Raises:
            ParseChannelError: If the message is incomplete (truncation is a
                hard failure, never a partial result).
        """
        if not self._complete:
            raise ParseChannelError(
                f"parse message incomplete: have {self._next_seq} of "
                f"{self._chunk_count or '?'} chunks "
                f"({len(self._buffer)}/{self._total_bytes or '?'} bytes) — "
                "truncated stream is a hard failure"
            )
        return bytes(self._buffer)

    def feed(self, frame: bytes) -> bool:
        """Consume one framed envelope; True when the message is complete.

        Raises:
            ParseChannelError: On any wire-contract violation (wrong type,
                missing/over-long/mismatched request_id, oversize declaration,
                bad sequence, bad base64, wrong chunk size, header mutation,
                frames after completion).
            ValueError: From ``MessageFramer.decode`` on a malformed envelope.
        """
        if self._complete:
            raise ParseChannelError(
                "frame received after message completion — one assembler "
                "assembles one message"
            )
        msg_type, request_id, payload = self._framer.decode(frame)
        if msg_type is not self._expected_type:
            raise ParseChannelError(
                f"expected {self._expected_type.value}, got {msg_type.value}"
            )
        _validate_request_id(request_id)
        if self._next_seq == 0:
            # Record the correlation id BEFORE size validation so the caller
            # can address an error response on rejection (see class docstring).
            self._request_id = request_id
        elif request_id != self._request_id:
            raise ParseChannelError(
                f"request_id changed mid-message: {self._request_id!r} -> "
                f"{request_id!r} (cross-talk)"
            )

        seq = self._require_int(payload, "seq")
        chunk_count = self._require_int(payload, "chunk_count")
        total_bytes = self._require_int(payload, "total_bytes")

        if seq != self._next_seq:
            raise ParseChannelError(
                f"chunk out of order: expected seq {self._next_seq}, got {seq} "
                "(missing/duplicated/reordered chunk — fail-closed)"
            )

        if self._next_seq == 0:
            if not 1 <= total_bytes <= PARSE_BODY_MAX_BYTES:
                raise ParseChannelError(
                    f"declared total_bytes {total_bytes} outside "
                    f"[1, {PARSE_BODY_MAX_BYTES}] — rejected before buffering"
                )
            if chunk_count != _chunk_count_for(total_bytes):
                raise ParseChannelError(
                    f"chunk_count {chunk_count} does not match the one valid "
                    f"framing for {total_bytes} bytes "
                    f"({_chunk_count_for(total_bytes)} chunks)"
                )
            meta = payload.get("meta", {})
            if not isinstance(meta, dict):
                raise ParseChannelError("chunk-0 meta must be a JSON object")
            self._meta = meta
            self._chunk_count = chunk_count
            self._total_bytes = total_bytes
        else:
            if chunk_count != self._chunk_count or total_bytes != self._total_bytes:
                raise ParseChannelError(
                    "chunk header mutated mid-message "
                    f"(chunk_count {self._chunk_count}->{chunk_count}, "
                    f"total_bytes {self._total_bytes}->{total_bytes})"
                )
            if "meta" in payload:
                raise ParseChannelError(
                    f"meta is only valid on chunk 0, found on seq {seq}"
                )

        data_b64 = payload.get("data")
        if not isinstance(data_b64, str):
            raise ParseChannelError("chunk 'data' must be a base64 string")
        try:
            data = base64.b64decode(data_b64, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise ParseChannelError(f"chunk {seq} carries invalid base64: {exc}") from exc

        expected_size = _expected_chunk_size(seq, self._chunk_count, self._total_bytes)
        if len(data) != expected_size:
            raise ParseChannelError(
                f"chunk {seq} carries {len(data)} bytes; the deterministic "
                f"framing requires exactly {expected_size}"
            )

        self._buffer.extend(data)
        self._next_seq += 1
        if self._next_seq == self._chunk_count:
            # Guaranteed by per-chunk exact sizes; assert as a final backstop.
            if len(self._buffer) != self._total_bytes:
                raise ParseChannelError(
                    f"assembled {len(self._buffer)} bytes != declared "
                    f"{self._total_bytes}"
                )
            self._complete = True
        return self._complete

    @staticmethod
    def _require_int(payload: dict[str, Any], key: str) -> int:
        value = payload.get(key)
        if not isinstance(value, int) or isinstance(value, bool):
            raise ParseChannelError(f"chunk field {key!r} must be an int, got {value!r}")
        return value


# ---------------------------------------------------------------------------
# Decoders (assembled message → typed view)
# ---------------------------------------------------------------------------


def decode_parse_request(assembler: ChunkAssembler) -> ParseRequest:
    """Decode a complete request assembly into a :class:`ParseRequest`.

    Raises:
        ParseChannelError: Wrong assembler type, incomplete assembly, or a
            malformed/non-string ``source_url``.
    """
    if assembler.expected_type is not MessageType.INGEST_PARSE_REQUEST:
        raise ParseChannelError(
            f"decode_parse_request needs an INGEST_PARSE_REQUEST assembler, "
            f"got {assembler.expected_type.value}"
        )
    body = assembler.body()  # raises if incomplete
    source_url = assembler.meta.get("source_url", "")
    if not isinstance(source_url, str):
        raise ParseChannelError(
            f"source_url meta must be str, got {type(source_url).__name__}"
        )
    return ParseRequest(
        request_id=assembler.request_id,
        source_url=source_url,
        html=body,
    )


def decode_parse_response(assembler: ChunkAssembler) -> ParseResponse:
    """Decode a complete response assembly into a :class:`ParseResponse`.

    Raises:
        ParseChannelError: Wrong assembler type, incomplete assembly,
            non-JSON body, unknown status, or malformed fields (fail-closed —
            a response that does not match the contract is rejected, never
            coerced into a plausible-looking verdict).
    """
    if assembler.expected_type is not MessageType.INGEST_PARSE_RESPONSE:
        raise ParseChannelError(
            f"decode_parse_response needs an INGEST_PARSE_RESPONSE assembler, "
            f"got {assembler.expected_type.value}"
        )
    body = assembler.body()  # raises if incomplete
    try:
        doc = json.loads(body.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ParseChannelError(f"response body is not UTF-8 JSON: {exc}") from exc
    if not isinstance(doc, dict):
        raise ParseChannelError("response body must be a JSON object")

    status = doc.get("status")
    if status not in PARSE_STATUSES:
        raise ParseChannelError(
            f"response status {status!r} not in {sorted(PARSE_STATUSES)}"
        )
    text = doc.get("text")
    if not isinstance(text, str):
        raise ParseChannelError("response 'text' must be a string")
    word_count = doc.get("word_count")
    if not isinstance(word_count, int) or isinstance(word_count, bool) or word_count < 0:
        raise ParseChannelError(f"response 'word_count' must be an int >= 0, got {word_count!r}")
    confidence = doc.get("confidence")
    if not isinstance(confidence, (int, float)) or isinstance(confidence, bool) or not (
        0.0 <= float(confidence) <= 1.0
    ):
        raise ParseChannelError(
            f"response 'confidence' must be a number in [0, 1], got {confidence!r}"
        )
    reasons_raw = doc.get("reasons", [])
    if not isinstance(reasons_raw, list) or not all(
        isinstance(reason, str) and reason for reason in reasons_raw
    ):
        raise ParseChannelError(f"response 'reasons' must be a list of strings, got {reasons_raw!r}")

    def _optional_str(key: str) -> str | None:
        value = doc.get(key)
        if value is None or isinstance(value, str):
            return value
        raise ParseChannelError(f"response {key!r} must be a string or null, got {value!r}")

    error_code = doc.get("error_code", "")
    message = doc.get("message", "")
    if not isinstance(error_code, str) or not isinstance(message, str):
        raise ParseChannelError("response 'error_code'/'message' must be strings")
    if status == "error" and not error_code.strip():
        raise ParseChannelError("response status 'error' requires an error_code")

    return ParseResponse(
        request_id=assembler.request_id,
        status=status,
        text=text,
        title=_optional_str("title"),
        byline=_optional_str("byline"),
        published_date=_optional_str("published_date"),
        word_count=word_count,
        confidence=float(confidence),
        reasons=tuple(reasons_raw),
        error_code=error_code,
        message=message,
    )
