"""
Guest Oracle Channel — chunked framing above the 64 KB vsock frame cap
======================================================================
Guest-certified oracle runs (#744, plan §10.3): after a dispatch job's tasks
merge and the host-side job oracle has graded the integrated tree, an
OPTIONAL second run of the SAME job-level oracle executes inside the NIC-less
Alpine guest (``BlarAI-Orchestrator``) as an ISOLATION CERTIFICATE layered on
the host gate.  The source snapshot crosses the vsock boundary host → guest
as ``ORACLE_EXEC_REQUEST``; the advisory outcome crosses back guest → host as
``ORACLE_EXEC_RESPONSE``.  A snapshot may be up to
``ORACLE_BODY_MAX_BYTES`` (2 MiB), which does not fit the transport's 64 KB
frame cap, so this module defines the ONE chunked framing both sides speak —
a per-corridor mirror of the proven UC-003 parse channel
(``shared/ipc/parse_channel.py``; the display-resolve corridor
``resolve_channel.py`` is the same house pattern at a different cap).

WIRE CONTRACT (cross-session — changing ANY of this is a protocol bump)
=======================================================================
An oracle message (either direction) is a sequence of ordinary JSON
envelopes (``MessageFramer`` encoding; each frame individually <= 64 KB) of a
single ``MessageType`` (``ORACLE_EXEC_REQUEST`` or ``ORACLE_EXEC_RESPONSE``):

  - The envelope ``request_id`` is the correlation id.  It is REQUIRED
    (non-empty, <= ORACLE_REQUEST_ID_MAX_CHARS — host-minted run ids in
    practice), IDENTICAL on every chunk of one message, and the response
    echoes the request's ``request_id``.
  - Chunk payload schema (total-size-first, per-chunk sequence)::

        {
          "seq":         <int>,   # 0-based chunk index
          "chunk_count": <int>,   # total chunks; MUST equal
                                  # ceil(total_bytes / ORACLE_CHUNK_DATA_BYTES)
          "total_bytes": <int>,   # raw body size in bytes (pre-base64);
                                  # 1 <= total_bytes <= ORACLE_BODY_MAX_BYTES
          "data":        <str>,   # base64 of this chunk's raw body slice
          "meta":        <dict>   # seq 0 ONLY; absent on every later chunk
        }

  - Deterministic chunk framing: chunk ``i`` for ``i < chunk_count - 1``
    carries EXACTLY ``ORACLE_CHUNK_DATA_BYTES`` raw bytes; the final chunk
    carries the remainder.  Any deviation (wrong size, wrong count, bad
    base64) is rejected — there is exactly one valid framing for a given
    body, so the framing itself is verifiable.
  - Body semantics:
      * REQUEST body  = the ZIP source snapshot, verbatim (built by
        ``shared/fleet/guest_oracle.py`` — pure-Python source + the
        plan-carried oracle bytes overlaid; the guest re-validates every
        member name and decompressed size before extraction).
        ``meta = {"oracle_path": <str>}`` — the pinned RELATIVE oracle path
        inside the snapshot; printable ASCII, forward slashes,
        <= ORACLE_PATH_MAX_CHARS.
      * RESPONSE body = UTF-8 JSON document::

            {"status": "passed"|"failed"|"not-run",
             "reason": <str>, "evidence": <str>}

        ``status`` is the closed guest-run vocabulary; ``reason`` is a
        stable machine label (set iff status == "not-run"); ``evidence`` is
        a bounded human diagnostic label (exit codes / counts — never file
        contents; the §10 S6 structural rule).

FAIL-CLOSED RULES (both sides; every violation raises OracleChannelError)
=========================================================================
  - Hard cap BOTH directions: ``total_bytes`` is validated on the FIRST
    chunk, before any buffering; per-chunk exact-size validation means
    assembly can never exceed the declared (already capped) total.  Encoders
    enforce the same cap, so an oversize body is unsendable.
  - Truncation: the assembler is complete ONLY after the final chunk;
    ``body()`` on an incomplete assembly raises.
  - Reorder / duplicate / missing chunk: ``seq`` must be exactly the next
    expected index — anything else raises.
  - Cross-talk: a ``request_id`` or header that changes mid-message raises.
    One assembler assembles ONE message; construct a fresh one per message.
  - Each frame still rides ``MessageFramer.encode`` → the 64 KB envelope cap
    is enforced per-frame on top of everything above.

No new dependencies: stdlib (base64/json) + ``shared.ipc.protocol``.
"""

from __future__ import annotations

import base64
import binascii
import json
from dataclasses import dataclass
from typing import Any

from shared.ipc.protocol import MessageFramer, MessageType

#: Hard cap on an assembled oracle body, both directions.  2 MiB is generous
#: for a fleet-built project's pure-Python source ZIP (live jobs measure in
#: the tens of KB) while keeping a hostile/oversize snapshot unsendable AND
#: unreceivable.  The snapshot builder enforces its own raw-source cap below
#: this at collection time (``guest_oracle.SNAPSHOT_MAX_TOTAL_BYTES``).
ORACLE_BODY_MAX_BYTES: int = 2 * 1024 * 1024

#: Raw bytes per chunk (pre-base64) — same sizing as the sibling corridors:
#: base64 data (60,000 chars) + meta + envelope overhead stays comfortably
#: under the 64 KB frame cap.
ORACLE_CHUNK_DATA_BYTES: int = 45_000

#: Maximum chunks any valid message can have (= ceil(cap / chunk size)).
ORACLE_MAX_CHUNKS: int = -(-ORACLE_BODY_MAX_BYTES // ORACLE_CHUNK_DATA_BYTES)

#: oracle_path metadata bound (printable ASCII enforced separately).
ORACLE_PATH_MAX_CHARS: int = 256

#: Hard cap on the ``request_id`` correlation field, both directions
#: (mirrors PARSE_REQUEST_ID_MAX_CHARS: an over-long id must die on the
#: FIRST frame, not at error-response encode).
ORACLE_REQUEST_ID_MAX_CHARS: int = 256

#: Closed status vocabulary for the response body — the guest run's outcome.
#: Deliberately identical to the host job-oracle vocabulary
#: (``SwapOps.run_job_oracle``): the guest result is advisory evidence beside
#: the host result, so the two must be directly comparable.
ORACLE_RUN_STATUSES: frozenset[str] = frozenset({"passed", "failed", "not-run"})

#: The two message types this channel speaks.
ORACLE_MESSAGE_TYPES: frozenset[MessageType] = frozenset(
    {MessageType.ORACLE_EXEC_REQUEST, MessageType.ORACLE_EXEC_RESPONSE}
)


class OracleChannelError(ValueError):
    """An oracle-channel wire-contract violation (fail-closed, both sides)."""


# ---------------------------------------------------------------------------
# Typed message views
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class OracleExecRequest:
    """An assembled host → guest oracle-exec request."""

    request_id: str
    """Correlation id (echoed on the response)."""

    oracle_path: str
    """Pinned RELATIVE path of the oracle test inside the snapshot."""

    snapshot_zip: bytes
    """The ZIP source snapshot, verbatim (1..ORACLE_BODY_MAX_BYTES bytes)."""


@dataclass(frozen=True)
class OracleExecResponse:
    """An assembled guest → host oracle-exec response (advisory evidence)."""

    request_id: str
    status: str
    """``passed`` | ``failed`` | ``not-run`` (closed vocabulary)."""

    reason: str = ""
    """Stable machine label; set iff status == 'not-run'."""

    evidence: str = ""
    """Bounded human diagnostic label (never file contents)."""


# ---------------------------------------------------------------------------
# Chunk math
# ---------------------------------------------------------------------------


def _chunk_count_for(total_bytes: int) -> int:
    """The ONE valid chunk count for a body of *total_bytes* bytes."""
    return -(-total_bytes // ORACLE_CHUNK_DATA_BYTES)


def _expected_chunk_size(seq: int, chunk_count: int, total_bytes: int) -> int:
    """The ONE valid raw size of chunk *seq* (deterministic framing)."""
    if seq < chunk_count - 1:
        return ORACLE_CHUNK_DATA_BYTES
    return total_bytes - (chunk_count - 1) * ORACLE_CHUNK_DATA_BYTES


def _validate_body(body: bytes, *, direction: str) -> None:
    if not isinstance(body, (bytes, bytearray)):
        raise OracleChannelError(
            f"{direction} body must be bytes, got {type(body).__name__}"
        )
    if len(body) == 0:
        raise OracleChannelError(
            f"{direction} body is empty — an empty oracle payload is never "
            "valid (fail-closed at encode)"
        )
    if len(body) > ORACLE_BODY_MAX_BYTES:
        raise OracleChannelError(
            f"{direction} body of {len(body)} bytes exceeds the hard cap "
            f"{ORACLE_BODY_MAX_BYTES} (the guest-oracle corridor max)"
        )


def _validate_request_id(request_id: str) -> None:
    if not isinstance(request_id, str) or not request_id.strip():
        raise OracleChannelError(
            "request_id is required on every oracle-channel message "
            "(correlation across chunks and across the request/response pair)"
        )
    if len(request_id) > ORACLE_REQUEST_ID_MAX_CHARS:
        raise OracleChannelError(
            f"request_id of {len(request_id)} chars exceeds "
            f"{ORACLE_REQUEST_ID_MAX_CHARS} — an over-long id would overflow "
            "the echoed error-response envelope (rejected on the first "
            "frame, fail-closed)"
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
        start = seq * ORACLE_CHUNK_DATA_BYTES
        chunk = body[start : start + ORACLE_CHUNK_DATA_BYTES]
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


def encode_oracle_request(
    *,
    request_id: str,
    snapshot_zip: bytes,
    oracle_path: str,
    framer: MessageFramer | None = None,
) -> list[bytes]:
    """Encode a host → guest oracle-exec request into chunked frames.

    Raises:
        OracleChannelError: empty/oversize *snapshot_zip*, missing
            *request_id*, or an *oracle_path* that is empty / non-ASCII /
            non-printable / backslashed / traversing / over
            ``ORACLE_PATH_MAX_CHARS`` (fail-closed at encode).
    """
    _validate_request_id(request_id)
    _validate_body(snapshot_zip, direction="request")
    if not isinstance(oracle_path, str) or not oracle_path.strip():
        raise OracleChannelError("oracle_path is required (the pinned relative oracle path)")
    if len(oracle_path) > ORACLE_PATH_MAX_CHARS:
        raise OracleChannelError(
            f"oracle_path of {len(oracle_path)} chars exceeds "
            f"{ORACLE_PATH_MAX_CHARS} (chunk-0 frame budget)"
        )
    if any(not (0x20 <= ord(ch) < 0x7F) for ch in oracle_path):
        raise OracleChannelError(
            "oracle_path must be printable ASCII — pinned oracle paths are "
            "ASCII by construction; anything else breaks the chunk-0 "
            "frame-size guarantee"
        )
    # Path-shape containment at the wire (defense-in-depth under the pinned
    # allowlist the executor enforces): relative, forward slashes, no
    # traversal — a hostile path must be unsendable, not just refusable.
    if "\\" in oracle_path or oracle_path.startswith("/") or ":" in oracle_path:
        raise OracleChannelError(
            f"oracle_path {oracle_path!r} must be a relative forward-slash "
            "path (no drive, no leading slash, no backslash)"
        )
    if any(part in ("", "..") for part in oracle_path.split("/")):
        raise OracleChannelError(
            f"oracle_path {oracle_path!r} must not contain empty or '..' "
            "segments (traversal-shaped paths are unsendable)"
        )
    return _encode_chunked(
        MessageType.ORACLE_EXEC_REQUEST,
        request_id,
        bytes(snapshot_zip),
        {"oracle_path": oracle_path},
        framer or MessageFramer(),
    )


def encode_oracle_response(
    *,
    request_id: str,
    status: str,
    reason: str = "",
    evidence: str = "",
    framer: MessageFramer | None = None,
) -> list[bytes]:
    """Encode a guest → host oracle-exec response into chunked frames.

    Raises:
        OracleChannelError: unknown *status*, ``status == 'not-run'`` without
            a *reason* (or a *reason* on a run outcome), or non-string fields
            (fail-closed at encode).
    """
    _validate_request_id(request_id)
    if status not in ORACLE_RUN_STATUSES:
        raise OracleChannelError(
            f"status {status!r} not in closed vocabulary {sorted(ORACLE_RUN_STATUSES)}"
        )
    if not isinstance(reason, str) or not isinstance(evidence, str):
        raise OracleChannelError("response 'reason'/'evidence' must be strings")
    if status == "not-run" and not reason.strip():
        raise OracleChannelError("status 'not-run' requires a non-empty reason")
    if status != "not-run" and reason:
        raise OracleChannelError(
            f"reason {reason!r} is only valid with status 'not-run' — a run "
            "outcome carries evidence, never a not-run reason"
        )
    body = json.dumps(
        {"status": status, "reason": reason, "evidence": evidence},
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    _validate_body(body, direction="response")
    return _encode_chunked(
        MessageType.ORACLE_EXEC_RESPONSE,
        request_id,
        body,
        {},
        framer or MessageFramer(),
    )


# ---------------------------------------------------------------------------
# Assembler (receive side — fail-closed on every contract violation)
# ---------------------------------------------------------------------------


class OracleChunkAssembler:
    """Assembles ONE chunked oracle message from framed envelopes.

    Feed each received frame in arrival order; ``feed`` returns True when the
    message is complete.  Every wire-contract violation raises
    :class:`OracleChannelError` — the assembler is then poisoned and the
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
        if expected_type not in ORACLE_MESSAGE_TYPES:
            raise OracleChannelError(
                f"{expected_type.value} is not an oracle-channel message type"
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
            OracleChannelError: If the message is incomplete (truncation is a
                hard failure, never a partial result).
        """
        if not self._complete:
            raise OracleChannelError(
                f"oracle message incomplete: have {self._next_seq} of "
                f"{self._chunk_count or '?'} chunks "
                f"({len(self._buffer)}/{self._total_bytes or '?'} bytes) — "
                "truncated stream is a hard failure"
            )
        return bytes(self._buffer)

    def feed(self, frame: bytes) -> bool:
        """Consume one framed envelope; True when the message is complete.

        Raises:
            OracleChannelError: On any wire-contract violation (wrong type,
                missing/over-long/mismatched request_id, oversize
                declaration, bad sequence, bad base64, wrong chunk size,
                header mutation, frames after completion).
            ValueError: From ``MessageFramer.decode`` on a malformed envelope.
        """
        if self._complete:
            raise OracleChannelError(
                "frame received after message completion — one assembler "
                "assembles one message"
            )
        msg_type, request_id, payload = self._framer.decode(frame)
        if msg_type is not self._expected_type:
            raise OracleChannelError(
                f"expected {self._expected_type.value}, got {msg_type.value}"
            )
        _validate_request_id(request_id)
        if self._next_seq == 0:
            # Record the correlation id BEFORE size validation so the caller
            # can address an error response on rejection (class docstring).
            self._request_id = request_id
        elif request_id != self._request_id:
            raise OracleChannelError(
                f"request_id changed mid-message: {self._request_id!r} -> "
                f"{request_id!r} (cross-talk)"
            )

        seq = self._require_int(payload, "seq")
        chunk_count = self._require_int(payload, "chunk_count")
        total_bytes = self._require_int(payload, "total_bytes")

        if seq != self._next_seq:
            raise OracleChannelError(
                f"chunk out of order: expected seq {self._next_seq}, got {seq} "
                "(missing/duplicated/reordered chunk — fail-closed)"
            )

        if self._next_seq == 0:
            if not 1 <= total_bytes <= ORACLE_BODY_MAX_BYTES:
                raise OracleChannelError(
                    f"declared total_bytes {total_bytes} outside "
                    f"[1, {ORACLE_BODY_MAX_BYTES}] — rejected before buffering"
                )
            if chunk_count != _chunk_count_for(total_bytes):
                raise OracleChannelError(
                    f"chunk_count {chunk_count} does not match the one valid "
                    f"framing for {total_bytes} bytes "
                    f"({_chunk_count_for(total_bytes)} chunks)"
                )
            meta = payload.get("meta", {})
            if not isinstance(meta, dict):
                raise OracleChannelError("chunk-0 meta must be a JSON object")
            self._meta = meta
            self._chunk_count = chunk_count
            self._total_bytes = total_bytes
        else:
            if chunk_count != self._chunk_count or total_bytes != self._total_bytes:
                raise OracleChannelError(
                    "chunk header mutated mid-message "
                    f"(chunk_count {self._chunk_count}->{chunk_count}, "
                    f"total_bytes {self._total_bytes}->{total_bytes})"
                )
            if "meta" in payload:
                raise OracleChannelError(
                    f"meta is only valid on chunk 0, found on seq {seq}"
                )

        data_b64 = payload.get("data")
        if not isinstance(data_b64, str):
            raise OracleChannelError("chunk 'data' must be a base64 string")
        try:
            data = base64.b64decode(data_b64, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise OracleChannelError(f"chunk {seq} carries invalid base64: {exc}") from exc

        expected_size = _expected_chunk_size(seq, self._chunk_count, self._total_bytes)
        if len(data) != expected_size:
            raise OracleChannelError(
                f"chunk {seq} carries {len(data)} bytes; the deterministic "
                f"framing requires exactly {expected_size}"
            )

        self._buffer.extend(data)
        self._next_seq += 1
        if self._next_seq == self._chunk_count:
            # Guaranteed by per-chunk exact sizes; assert as a final backstop.
            if len(self._buffer) != self._total_bytes:
                raise OracleChannelError(
                    f"assembled {len(self._buffer)} bytes != declared "
                    f"{self._total_bytes}"
                )
            self._complete = True
        return self._complete

    @staticmethod
    def _require_int(payload: dict[str, Any], key: str) -> int:
        value = payload.get(key)
        if not isinstance(value, int) or isinstance(value, bool):
            raise OracleChannelError(f"chunk field {key!r} must be an int, got {value!r}")
        return value


# ---------------------------------------------------------------------------
# Decoders (assembled message → typed view)
# ---------------------------------------------------------------------------


def decode_oracle_request(assembler: OracleChunkAssembler) -> OracleExecRequest:
    """Decode a complete request assembly into an :class:`OracleExecRequest`.

    Raises:
        OracleChannelError: Wrong assembler type, incomplete assembly, or a
            missing/malformed ``oracle_path``.
    """
    if assembler.expected_type is not MessageType.ORACLE_EXEC_REQUEST:
        raise OracleChannelError(
            f"decode_oracle_request needs an ORACLE_EXEC_REQUEST assembler, "
            f"got {assembler.expected_type.value}"
        )
    body = assembler.body()  # raises if incomplete
    oracle_path = assembler.meta.get("oracle_path", "")
    if not isinstance(oracle_path, str) or not oracle_path.strip():
        raise OracleChannelError(
            "oracle_path meta is required and must be a non-empty string"
        )
    return OracleExecRequest(
        request_id=assembler.request_id,
        oracle_path=oracle_path,
        snapshot_zip=body,
    )


def decode_oracle_response(assembler: OracleChunkAssembler) -> OracleExecResponse:
    """Decode a complete response assembly into an :class:`OracleExecResponse`.

    Raises:
        OracleChannelError: Wrong assembler type, incomplete assembly,
            non-JSON body, unknown status, or malformed fields (fail-closed —
            a response that does not match the contract is rejected, never
            coerced into a plausible-looking verdict).
    """
    if assembler.expected_type is not MessageType.ORACLE_EXEC_RESPONSE:
        raise OracleChannelError(
            f"decode_oracle_response needs an ORACLE_EXEC_RESPONSE assembler, "
            f"got {assembler.expected_type.value}"
        )
    body = assembler.body()  # raises if incomplete
    try:
        doc = json.loads(body.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise OracleChannelError(f"response body is not UTF-8 JSON: {exc}") from exc
    if not isinstance(doc, dict):
        raise OracleChannelError("response body must be a JSON object")

    status = doc.get("status")
    if status not in ORACLE_RUN_STATUSES:
        raise OracleChannelError(
            f"response status {status!r} not in {sorted(ORACLE_RUN_STATUSES)}"
        )
    reason = doc.get("reason", "")
    evidence = doc.get("evidence", "")
    if not isinstance(reason, str) or not isinstance(evidence, str):
        raise OracleChannelError("response 'reason'/'evidence' must be strings")
    if status == "not-run" and not reason.strip():
        raise OracleChannelError("response status 'not-run' requires a reason")

    return OracleExecResponse(
        request_id=assembler.request_id,
        status=status,
        reason=reason,
        evidence=evidence,
    )
