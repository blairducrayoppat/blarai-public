"""
Image-Resolve Channel — chunked framing above the 64 KB vsock frame cap
=======================================================================
UC-010 / UC-003 Workstream 3 (ADR-033 §D): a ``blarai-img://<id>`` reference is
resolved to decrypted bytes for INLINE DISPLAY (WinUI render) or a TUI ``/save``.
The image bytes live encrypted in the AO-resident ``generated_images`` /
``knowledge_images`` stores; the gateway forwards an ``IMAGE_RESOLVE_REQUEST``
(one small frame, ``image_id`` only) and the AO replies with the decrypted PNG.

A decrypted image is up to ``image_staging.MAX_IMAGE_BYTES`` (2 MiB), which does
NOT fit the transport's 64 KB frame cap (``VsockConfig.max_message_bytes`` /
``DEFAULT_MAX_MESSAGE_BYTES``), so this module defines the ONE chunked framing
both sides speak — modelled directly on ``shared/ipc/parse_channel.py`` (the
proven Stage-C parse channel).

This is a DISPLAY-resolve path, NOT a generation path: no model is loaded, no
image is generated.  The decrypted bytes live ONLY in the outgoing frames + the
receive-side assembler — they are NEVER written to disk or a log on this leg.

WIRE CONTRACT (cross-session — changing ANY of this is a protocol bump)
=======================================================================
REQUEST (gateway → AO): a SINGLE ``IMAGE_RESOLVE_REQUEST`` envelope
(``MessageFramer`` encoding, < 64 KB) whose ``request_id`` is the correlation id
and whose payload is ``{"image_id": <str>}`` — a 32-char ``uuid4().hex`` (the
``blarai-img://`` id shape).  No bytes ride this frame.

RESPONSE (AO → gateway): a sequence of ``IMAGE_RESOLVE_RESPONSE`` envelopes of
ONE of two shapes:

  - PLACEHOLDER (the None result — unknown id / decrypt-quarantine / dormant /
    malformed id): EXACTLY ONE frame, payload ``{"found": false}`` (no ``data``,
    no ``mime``, no plaintext).  This is NOT an error frame — a missing image is
    a normal, expected outcome the caller renders as the inert alt placeholder.

  - FOUND: one or more chunk frames (total-size-first, per-chunk sequence)::

        {
          "found":       true,
          "mime":        <str>,   # first chunk ONLY; the decoder's mime
          "seq":         <int>,   # 0-based chunk index
          "chunk_count": <int>,   # total chunks; MUST equal
                                  # ceil(total_bytes / RESOLVE_CHUNK_DATA_BYTES)
          "total_bytes": <int>,   # decrypted image size in bytes (pre-base64);
                                  # 1 <= total_bytes <= RESOLVE_BODY_MAX_BYTES
          "data":        <str>    # base64 of this chunk's raw body slice
        }

    Deterministic chunk framing: chunk ``i`` for ``i < chunk_count - 1`` carries
    EXACTLY ``RESOLVE_CHUNK_DATA_BYTES`` raw bytes; the final chunk carries the
    remainder.  Any deviation (wrong size, wrong count, bad base64) is rejected —
    there is exactly one valid framing for a given body, so the framing is
    verifiable.

FAIL-CLOSED RULES (both sides; every violation raises ResolveChannelError)
==========================================================================
  - Hard cap: ``total_bytes`` is validated on the FIRST found chunk, BEFORE any
    buffering — an oversize declaration is rejected with nothing buffered, and
    per-chunk exact-size validation means assembly can never exceed the declared
    (already capped) total.  Encoders enforce the same cap, so an oversize image
    is unsendable, not just unreceivable.  The cap is
    ``RESOLVE_BODY_MAX_BYTES == shared.security.image_staging.MAX_IMAGE_BYTES``
    (a coupling-lock test asserts equality).
  - Truncation: the assembler is complete ONLY after the final chunk (or the
    single placeholder frame); ``body()`` on an incomplete found assembly raises.
    A transport that returns None mid-message leaves a detectably incomplete
    assembler — the gateway reader maps that to None (placeholder), never partial.
  - Reorder / duplicate / missing chunk: ``seq`` must be exactly the next
    expected index — anything else raises.
  - Cross-talk: a ``request_id`` or header (``found``/``chunk_count``/
    ``total_bytes``/``mime``) that changes mid-message raises.  One assembler
    assembles ONE message; construct a fresh one per message.
  - Each frame still rides ``MessageFramer.encode`` → the 64 KB envelope cap is
    enforced per-frame on top of everything above.

No new dependencies: stdlib (base64/binascii) + ``shared.ipc.protocol``.  The
cap constant is imported from ``shared.security.image_staging`` so the two cannot
drift.
"""

from __future__ import annotations

import base64
import binascii
from dataclasses import dataclass
from typing import Any

from shared.ipc.protocol import MessageFramer, MessageType
from shared.security.image_staging import MAX_IMAGE_BYTES

#: Hard cap on an assembled resolved-image body.  This corridor delivers BOTH
#: ingested ``knowledge_images`` (capped at ``image_staging.MAX_IMAGE_BYTES`` =
#: 2 MiB at fetch time) AND UC-010 ``generated_images`` — and a generated SDXL PNG
#: has NO fetch cap and routinely exceeds 2 MiB (a 1024² is ~2-4 MiB; the config
#: validator allows up to 2048²).  So the resolve cap is sized for the LARGEST
#: image it must deliver — a generated one — DECOUPLED from the 2 MiB fetch/staging
#: cap.  (The prior ``== MAX_IMAGE_BYTES`` coupling silently refused a generated
#: image 11 KB over 2 MiB; surfaced live at the UC-010 go-live, #666.)  16 MiB
#: covers the configurable max (2048²) with headroom and stays a bounded DoS guard
#: (reassembly can never exceed it).  Enforced at encode AND on the first received
#: found chunk (before buffering).
RESOLVE_BODY_MAX_BYTES: int = 16 * 1024 * 1024

#: Raw bytes per chunk (pre-base64).  Sized so the worst-case frame — base64 data
#: (60,000 chars) + the small header (found/mime/seq/chunk_count/total_bytes) +
#: envelope overhead — stays comfortably under the 64 KB frame cap.
RESOLVE_CHUNK_DATA_BYTES: int = 45_000

#: Maximum chunks any valid message can have (= ceil(cap / chunk size)).
RESOLVE_MAX_CHUNKS: int = -(-RESOLVE_BODY_MAX_BYTES // RESOLVE_CHUNK_DATA_BYTES)

#: Hard cap on the ``request_id`` correlation field (host-minted UUIDs ~36 chars;
#: 256 leaves headroom while keeping any echoing envelope inside the frame cap).
RESOLVE_REQUEST_ID_MAX_CHARS: int = 256

#: Hard cap on the ``image_id`` request field (a 32-char uuid4 hex in practice;
#: a generous bound rejects a pathological peer-supplied id before it is used).
RESOLVE_IMAGE_ID_MAX_CHARS: int = 256

#: Hard cap on the ``mime`` label (a structural decoder hint, e.g. ``image/png``).
RESOLVE_MIME_MAX_CHARS: int = 128

#: The two message types this channel speaks.
RESOLVE_MESSAGE_TYPES: frozenset[MessageType] = frozenset(
    {MessageType.IMAGE_RESOLVE_REQUEST, MessageType.IMAGE_RESOLVE_RESPONSE}
)


class ResolveChannelError(ValueError):
    """An image-resolve-channel wire-contract violation (fail-closed, both sides)."""


# ---------------------------------------------------------------------------
# Typed message views
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ResolveRequest:
    """An assembled gateway → AO image-resolve request."""

    request_id: str
    """Resolve correlation id (echoed on the response)."""

    image_id: str
    """The ``blarai-img://`` id (32-char uuid4 hex in practice) to resolve."""


@dataclass(frozen=True)
class ResolveResponse:
    """An assembled AO → gateway image-resolve response.

    ``found`` False is the placeholder (None) result — ``mime`` is empty and
    ``data`` is empty.  ``found`` True carries the decrypted image bytes + mime.
    """

    request_id: str
    found: bool
    mime: str
    data: bytes


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------


def _chunk_count_for(total_bytes: int) -> int:
    """The ONE valid chunk count for a body of *total_bytes* bytes."""
    return -(-total_bytes // RESOLVE_CHUNK_DATA_BYTES)


def _expected_chunk_size(seq: int, chunk_count: int, total_bytes: int) -> int:
    """The ONE valid raw size of chunk *seq* (deterministic framing)."""
    if seq < chunk_count - 1:
        return RESOLVE_CHUNK_DATA_BYTES
    return total_bytes - (chunk_count - 1) * RESOLVE_CHUNK_DATA_BYTES


def _validate_request_id(request_id: str) -> None:
    if not isinstance(request_id, str) or not request_id.strip():
        raise ResolveChannelError(
            "request_id is required on every resolve-channel message "
            "(correlation across chunks and across the request/response pair)"
        )
    if len(request_id) > RESOLVE_REQUEST_ID_MAX_CHARS:
        raise ResolveChannelError(
            f"request_id of {len(request_id)} chars exceeds "
            f"{RESOLVE_REQUEST_ID_MAX_CHARS} — correlation ids are host-minted "
            "UUIDs (fail-closed on the first frame)"
        )


def _validate_image_id(image_id: str) -> None:
    if not isinstance(image_id, str) or not image_id.strip():
        raise ResolveChannelError(
            "image_id is required on an IMAGE_RESOLVE_REQUEST (fail-closed)"
        )
    if len(image_id) > RESOLVE_IMAGE_ID_MAX_CHARS:
        raise ResolveChannelError(
            f"image_id of {len(image_id)} chars exceeds "
            f"{RESOLVE_IMAGE_ID_MAX_CHARS} (fail-closed)"
        )


def _validate_body(body: bytes) -> None:
    if not isinstance(body, (bytes, bytearray)):
        raise ResolveChannelError(
            f"resolve body must be bytes, got {type(body).__name__}"
        )
    if len(body) == 0:
        raise ResolveChannelError(
            "resolve body is empty — a found image with zero bytes is never "
            "valid (use found=false for the placeholder; fail-closed at encode)"
        )
    if len(body) > RESOLVE_BODY_MAX_BYTES:
        raise ResolveChannelError(
            f"resolve body of {len(body)} bytes exceeds the hard cap "
            f"{RESOLVE_BODY_MAX_BYTES} (the resolve-corridor max, sized for "
            f"generated images — decoupled from the {MAX_IMAGE_BYTES}-byte fetch cap)"
        )


# ---------------------------------------------------------------------------
# Encoders (encode-side validation raises — nothing invalid crosses IPC)
# ---------------------------------------------------------------------------


def encode_resolve_request(
    *,
    request_id: str,
    image_id: str,
    framer: MessageFramer | None = None,
) -> bytes:
    """Encode a gateway → AO image-resolve request (one frame).

    Raises:
        ResolveChannelError: missing/over-long *request_id* or *image_id*.
    """
    _validate_request_id(request_id)
    _validate_image_id(image_id)
    framer = framer or MessageFramer()
    return framer.encode(
        MessageType.IMAGE_RESOLVE_REQUEST,
        {"image_id": image_id},
        request_id,
    )


def encode_resolve_placeholder(
    *,
    request_id: str,
    framer: MessageFramer | None = None,
) -> list[bytes]:
    """Encode the None/placeholder response (a single ``found=false`` frame).

    A list of one frame so the placeholder and found shapes share a return type
    (the AO streams ``encode_resolve_response(...)`` either way).

    Raises:
        ResolveChannelError: missing/over-long *request_id*.
    """
    _validate_request_id(request_id)
    framer = framer or MessageFramer()
    return [
        framer.encode(
            MessageType.IMAGE_RESOLVE_RESPONSE,
            {"found": False},
            request_id,
        )
    ]


def encode_resolve_response(
    *,
    request_id: str,
    mime: str,
    data: bytes,
    framer: MessageFramer | None = None,
) -> list[bytes]:
    """Encode a FOUND image into chunked ``IMAGE_RESOLVE_RESPONSE`` frames.

    Raises:
        ResolveChannelError: empty/oversize *data*, missing *request_id*, or a
            non-string / over-long *mime* (fail-closed at encode).
    """
    _validate_request_id(request_id)
    _validate_body(data)
    if not isinstance(mime, str) or not mime.strip():
        raise ResolveChannelError("a found resolve response requires a non-empty mime")
    if len(mime) > RESOLVE_MIME_MAX_CHARS:
        raise ResolveChannelError(
            f"mime of {len(mime)} chars exceeds {RESOLVE_MIME_MAX_CHARS} (fail-closed)"
        )
    framer = framer or MessageFramer()
    body = bytes(data)
    total_bytes = len(body)
    chunk_count = _chunk_count_for(total_bytes)
    frames: list[bytes] = []
    for seq in range(chunk_count):
        start = seq * RESOLVE_CHUNK_DATA_BYTES
        chunk = body[start : start + RESOLVE_CHUNK_DATA_BYTES]
        payload: dict[str, Any] = {
            "found": True,
            "seq": seq,
            "chunk_count": chunk_count,
            "total_bytes": total_bytes,
            "data": base64.b64encode(chunk).decode("ascii"),
        }
        if seq == 0:
            payload["mime"] = mime
        # MessageFramer.encode enforces the 64 KB envelope cap per frame.
        frames.append(framer.encode(MessageType.IMAGE_RESOLVE_RESPONSE, payload, request_id))
    return frames


# ---------------------------------------------------------------------------
# Assembler (receive side — fail-closed on every contract violation)
# ---------------------------------------------------------------------------


class ResolveAssembler:
    """Assembles ONE chunked ``IMAGE_RESOLVE_RESPONSE`` from framed envelopes.

    Feed each received frame in arrival order; ``feed`` returns True when the
    message is complete (the single placeholder frame, or the final found chunk).
    Every wire-contract violation raises :class:`ResolveChannelError` — the
    assembler is then poisoned and the caller drops the connection.
    """

    def __init__(self, *, framer: MessageFramer | None = None) -> None:
        self._framer = framer or MessageFramer()
        self._request_id: str = ""
        self._found: bool | None = None
        self._mime: str = ""
        self._chunk_count: int = 0
        self._total_bytes: int = 0
        self._next_seq: int = 0
        self._buffer = bytearray()
        self._complete = False

    @property
    def complete(self) -> bool:
        """True once the placeholder frame or the final found chunk is verified."""
        return self._complete

    @property
    def found(self) -> bool:
        """Whether the resolved image exists (False once a placeholder is seen).

        Raises:
            ResolveChannelError: If no frame has been accepted yet.
        """
        if self._found is None:
            raise ResolveChannelError("no resolve frame accepted yet — found is undefined")
        return self._found

    @property
    def request_id(self) -> str:
        """The correlation id ('' until the first frame carries one)."""
        return self._request_id

    @property
    def mime(self) -> str:
        """The found image's mime ('' for a placeholder / before chunk 0)."""
        return self._mime

    def body(self) -> bytes:
        """The assembled image bytes (empty for a placeholder).

        Raises:
            ResolveChannelError: If a FOUND message is incomplete (truncation is
                a hard failure, never a partial result).
        """
        if not self._complete:
            raise ResolveChannelError(
                f"resolve message incomplete: have {self._next_seq} of "
                f"{self._chunk_count or '?'} chunks "
                f"({len(self._buffer)}/{self._total_bytes or '?'} bytes) — "
                "truncated stream is a hard failure"
            )
        return bytes(self._buffer)

    def response(self) -> ResolveResponse:
        """The completed response as a typed view (raises if incomplete)."""
        body = self.body()  # raises if incomplete
        return ResolveResponse(
            request_id=self._request_id,
            found=bool(self._found),
            mime=self._mime,
            data=body,
        )

    def feed(self, frame: bytes) -> bool:
        """Consume one framed envelope; True when the message is complete.

        Raises:
            ResolveChannelError: On any wire-contract violation.
            ValueError: From ``MessageFramer.decode`` on a malformed envelope.
        """
        if self._complete:
            raise ResolveChannelError(
                "frame received after message completion — one assembler "
                "assembles one message"
            )
        msg_type, request_id, payload = self._framer.decode(frame)
        if msg_type is not MessageType.IMAGE_RESOLVE_RESPONSE:
            raise ResolveChannelError(
                f"expected IMAGE_RESOLVE_RESPONSE, got {msg_type.value}"
            )
        _validate_request_id(request_id)
        if self._found is None:
            self._request_id = request_id
        elif request_id != self._request_id:
            raise ResolveChannelError(
                f"request_id changed mid-message: {self._request_id!r} -> "
                f"{request_id!r} (cross-talk)"
            )

        found = payload.get("found")
        if not isinstance(found, bool):
            raise ResolveChannelError("resolve frame 'found' must be a bool")

        # ── Placeholder (None result): a single found=false frame, no data. ──
        if found is False:
            if self._next_seq != 0:
                raise ResolveChannelError(
                    "a found=false placeholder may only be the FIRST and ONLY "
                    "frame (it followed found-chunk data — cross-talk)"
                )
            if "data" in payload:
                raise ResolveChannelError(
                    "a found=false placeholder must carry no data (fail-closed)"
                )
            self._found = False
            self._complete = True
            return True

        # ── Found: chunked image bytes (mirrors the parse-channel framing). ──
        if self._found is False:
            raise ResolveChannelError(
                "found=true frame after a found=false placeholder (cross-talk)"
            )
        self._found = True

        seq = self._require_int(payload, "seq")
        chunk_count = self._require_int(payload, "chunk_count")
        total_bytes = self._require_int(payload, "total_bytes")

        if seq != self._next_seq:
            raise ResolveChannelError(
                f"chunk out of order: expected seq {self._next_seq}, got {seq} "
                "(missing/duplicated/reordered chunk — fail-closed)"
            )

        if self._next_seq == 0:
            if not 1 <= total_bytes <= RESOLVE_BODY_MAX_BYTES:
                raise ResolveChannelError(
                    f"declared total_bytes {total_bytes} outside "
                    f"[1, {RESOLVE_BODY_MAX_BYTES}] — rejected before buffering"
                )
            if chunk_count != _chunk_count_for(total_bytes):
                raise ResolveChannelError(
                    f"chunk_count {chunk_count} does not match the one valid "
                    f"framing for {total_bytes} bytes "
                    f"({_chunk_count_for(total_bytes)} chunks)"
                )
            mime = payload.get("mime")
            if not isinstance(mime, str) or not mime.strip():
                raise ResolveChannelError(
                    "found chunk 0 must carry a non-empty 'mime'"
                )
            if len(mime) > RESOLVE_MIME_MAX_CHARS:
                raise ResolveChannelError(
                    f"mime of {len(mime)} chars exceeds {RESOLVE_MIME_MAX_CHARS}"
                )
            self._mime = mime
            self._chunk_count = chunk_count
            self._total_bytes = total_bytes
        else:
            if chunk_count != self._chunk_count or total_bytes != self._total_bytes:
                raise ResolveChannelError(
                    "chunk header mutated mid-message "
                    f"(chunk_count {self._chunk_count}->{chunk_count}, "
                    f"total_bytes {self._total_bytes}->{total_bytes})"
                )
            if "mime" in payload:
                raise ResolveChannelError(
                    f"mime is only valid on chunk 0, found on seq {seq}"
                )

        data_b64 = payload.get("data")
        if not isinstance(data_b64, str):
            raise ResolveChannelError("chunk 'data' must be a base64 string")
        try:
            data = base64.b64decode(data_b64, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise ResolveChannelError(f"chunk {seq} carries invalid base64: {exc}") from exc

        expected_size = _expected_chunk_size(seq, self._chunk_count, self._total_bytes)
        if len(data) != expected_size:
            raise ResolveChannelError(
                f"chunk {seq} carries {len(data)} bytes; the deterministic "
                f"framing requires exactly {expected_size}"
            )

        self._buffer.extend(data)
        self._next_seq += 1
        if self._next_seq == self._chunk_count:
            if len(self._buffer) != self._total_bytes:
                raise ResolveChannelError(
                    f"assembled {len(self._buffer)} bytes != declared "
                    f"{self._total_bytes}"
                )
            self._complete = True
        return self._complete

    @staticmethod
    def _require_int(payload: dict[str, Any], key: str) -> int:
        value = payload.get(key)
        if not isinstance(value, int) or isinstance(value, bool):
            raise ResolveChannelError(f"chunk field {key!r} must be an int, got {value!r}")
        return value


# ---------------------------------------------------------------------------
# Decoders (request side — one-frame typed view)
# ---------------------------------------------------------------------------


def decode_resolve_request(
    frame: bytes, *, framer: MessageFramer | None = None
) -> ResolveRequest:
    """Decode a single ``IMAGE_RESOLVE_REQUEST`` frame into a typed view.

    Raises:
        ResolveChannelError: Wrong type or a missing/over-long image_id.
        ValueError: From ``MessageFramer.decode`` on a malformed envelope.
    """
    framer = framer or MessageFramer()
    msg_type, request_id, payload = framer.decode(frame)
    if msg_type is not MessageType.IMAGE_RESOLVE_REQUEST:
        raise ResolveChannelError(
            f"decode_resolve_request needs an IMAGE_RESOLVE_REQUEST, "
            f"got {msg_type.value}"
        )
    _validate_request_id(request_id)
    image_id = payload.get("image_id")
    if not isinstance(image_id, str):
        raise ResolveChannelError("IMAGE_RESOLVE_REQUEST 'image_id' must be a string")
    _validate_image_id(image_id)
    return ResolveRequest(request_id=request_id, image_id=image_id)
