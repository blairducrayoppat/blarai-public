"""
IPC Message Protocol — vsock AF_HYPERV
========================================
USE-CASE-001, P1.6: Defines the wire protocol for all inter-agent
communication over vsock (AF_HYPERV).

Provides:
  - MessageType: request/response type enumeration.
  - AdjudicationRequest: serialized CAR for Policy Agent evaluation.
  - AdjudicationResponse: adjudication result with optional Agentic JWT.
  - MessageFramer: JSON encoding/decoding of IPC envelopes.

The framing layer (4-byte length prefix) is handled by VsockTransport,
NOT by this module. MessageFramer encodes/decodes the JSON body only.

Envelope format (JSON):
  {
    "type": "ADJUDICATION_REQUEST",
    "request_id": "<uuid>",
    "payload": { ... }
  }

Security:
  - Maximum message size enforced at encode time.
  - Malformed payloads produce ValueError (caller converts to DENY).
  - No external network calls.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import Enum
from typing import Any


# Default max: 64 KB (matches VsockConfig.max_message_bytes).
DEFAULT_MAX_MESSAGE_BYTES: int = 65_536


class MessageType(str, Enum):
    """IPC message types for the vsock protocol."""

    ADJUDICATION_REQUEST = "ADJUDICATION_REQUEST"
    """Agent → PA: evaluate this CAR."""

    ADJUDICATION_RESPONSE = "ADJUDICATION_RESPONSE"
    """PA → Agent: adjudication result + optional JWT."""

    ERROR = "ERROR"
    """PA → Agent: processing error (Fail-Closed DENY)."""

    HEARTBEAT = "HEARTBEAT"
    """Bidirectional: liveness check."""

    # ── UI Gateway message types (P1.11) ──

    HANDSHAKE_REQUEST = "HANDSHAKE_REQUEST"
    """Gateway → Orchestrator: Boot-Phase-3 PA status check."""

    HANDSHAKE_RESPONSE = "HANDSHAKE_RESPONSE"
    """Orchestrator → Gateway: PA operational status."""

    PROMPT_REQUEST = "PROMPT_REQUEST"
    """Gateway → Orchestrator: user prompt for generation."""

    STREAM_TOKEN = "STREAM_TOKEN"
    """Orchestrator → Gateway: single generated token (streamed)."""

    PGOV_RESULT = "PGOV_RESULT"
    """Orchestrator → Gateway: PGOV validation outcome."""

    GENERATION_COMPLETE = "GENERATION_COMPLETE"
    """Orchestrator → Gateway: signals end of token stream."""

    # ── Knowledge-bank ingest message types (UC-002/UC-003, #655) ──

    INGEST_SUBMIT = "INGEST_SUBMIT"
    """Gateway → Orchestrator: a cleaned document awaits the pending-row write.

    The content itself NEVER rides this frame — it crosses processes via the
    encrypted staging file (``shared/security/ingest_staging.py``); the payload
    carries the doc_uuid + metadata labels only, keeping the envelope far under
    the 64 KB cap."""

    INGEST_DECISION = "INGEST_DECISION"
    """Gateway → Orchestrator: operator decision (approve|reject) for a pending doc."""

    INGEST_RESULT = "INGEST_RESULT"
    """Orchestrator → Gateway: outcome of an ingest submit/decision."""

    # ── Guest parse channel message types (UC-003 Stage C, #655) ──

    INGEST_PARSE_REQUEST = "INGEST_PARSE_REQUEST"
    """Host → guest parser: one CHUNK of a raw-HTML parse request.

    Unlike every other message type, a parse payload (fetched page up to
    ``staging_max_bytes`` = 262,144 bytes) does not fit one 64 KB frame, so
    the body is base64-chunked across several frames of this type.  The
    chunking contract (sequencing, caps, fail-closed assembly) lives in
    ``shared/ipc/parse_channel.py`` — encode/decode through that module,
    never by hand."""

    INGEST_PARSE_RESPONSE = "INGEST_PARSE_RESPONSE"
    """Guest parser → host: one CHUNK of the cleaned-text parse response.

    Same chunking contract as INGEST_PARSE_REQUEST (``parse_channel.py``).
    The assembled body is a JSON document carrying cleaned text + extraction
    metadata (title/byline/date/word_count/confidence/status/reasons)."""

    # ── Local generative imaging message types (UC-010, ADR-033 — DORMANT) ──

    IMAGE_GEN_REQUEST = "IMAGE_GEN_REQUEST"
    """Gateway → Orchestrator: generate an image (text→image or image+text).

    METADATA ONLY — the request carries the mode + prompt + caps + (for img2img)
    a reference to the encrypted ``image_staging`` blob that holds the LOCAL seed
    image's bytes. The seed bytes NEVER ride this frame (and are NEVER a URL — no
    egress); they cross via the per-image encrypted staging blob, exactly like an
    ingest image. The generated PNG cannot ride the 64 KB frame either, so the
    result is a ``blarai-img://<id>`` reference."""

    IMAGE_GEN_RESULT = "IMAGE_GEN_RESULT"
    """Orchestrator → Gateway: outcome of an image-generation request.

    On success carries the ``blarai-img://<image_id>`` ref + mime; on failure
    carries an ``error_code`` + ``message`` (labels only, never content). The
    dormant default (``[image_generation].enabled=false``) always returns
    ``ok=False`` with an ``IMAGE_GEN_UNAVAILABLE`` notice — no model is loaded."""

    # ── Image display-resolve channel (UC-010/UC-003 WS3, ADR-033 §D) ─────

    IMAGE_RESOLVE_REQUEST = "IMAGE_RESOLVE_REQUEST"
    """Gateway → Orchestrator: resolve a ``blarai-img://<id>`` ref to bytes.

    METADATA ONLY (one small frame): carries the ``image_id`` to decrypt for
    INLINE DISPLAY (WinUI render) or a TUI ``/save``.  No model is loaded on this
    path — it is a single-record decrypt-quarantine read, NOT a generation.

    What the by-id corridor resolves TODAY: ``generated_images`` by ``image_id``
    alone (UC-010).  The ``knowledge_images`` (UC-003 display) store is keyed
    PER-DOCUMENT (``bank.get_knowledge_image(doc_uuid, image_id)``); a by-id
    resolve of it is built-ahead-but-NOT-wired on this path — the renderer carries
    only the ``image_id`` (not the ``doc_uuid``), so a per-doc lookup cannot be
    issued from a bare id (a deferred render-path decision; see
    ``generated_image_resolver.resolve_generated_or_display_image``).

    The decrypted PNG (up to 2 MiB) cannot ride one 64 KB frame, so it returns
    chunked as ``IMAGE_RESOLVE_RESPONSE`` frames; the chunking contract
    (sequencing, the 2 MiB cap, fail-closed assembly) lives in
    ``shared/ipc/resolve_channel.py`` — encode/decode through that module."""

    IMAGE_RESOLVE_RESPONSE = "IMAGE_RESOLVE_RESPONSE"
    """Orchestrator → Gateway: one CHUNK of a resolved image's decrypted bytes.

    Same chunking contract as the parse channel (``resolve_channel.py``): the
    decrypted PNG body is base64-chunked across several frames, total-bytes-first
    + per-chunk exact size + fail-closed assembly under a HARD 2 MiB cap
    (== ``shared.security.image_staging.MAX_IMAGE_BYTES``).  A None result
    (unknown id / decrypt-quarantine / dormant) is a SINGLE small frame with
    ``found=false`` and NO data — never an error frame, never partial plaintext."""

    # ── Generated-image management (UC-010 Phase 1, #667) ─────────────────

    IMAGE_LIST_REQUEST = "IMAGE_LIST_REQUEST"
    """Gateway → Orchestrator: list generated-image METADATA (the /images view).

    METADATA ONLY — one small frame.  Carries an OPTIONAL ``session_id`` filter
    (empty = list across all sessions).  The store that holds generated images
    lives in the AO, so the listing crosses this gateway→AO leg.  No model is
    loaded; no image bytes / prompts cross the wire (the AO reads only the cheap
    non-content columns — see ``EncryptedKnowledgeBank.list_generated_images``)."""

    IMAGE_LIST_RESPONSE = "IMAGE_LIST_RESPONSE"
    """Orchestrator → Gateway: the generated-image metadata listing.

    METADATA ONLY: a list of per-image records, each carrying ``image_id`` /
    ``session_id`` / ``mime`` / ``byte_size`` / ``saved`` / ``created_at`` and
    NOTHING ELSE — never a decrypted prompt, never image bytes.  Capped at
    ``IMAGE_LIST_MAX_ITEMS`` newest-first so the listing always fits one 64 KB
    frame; ``truncated=true`` signals that older images exist beyond the cap.
    A ``total`` count is carried so the UI can say "showing N of M"."""

    IMAGE_MANAGE_REQUEST = "IMAGE_MANAGE_REQUEST"
    """Gateway → Orchestrator: a metadata-only management action on one image.

    Carries an ``action`` (``delete`` | ``mark_saved``) + the FULL 32-hex
    ``image_id``.  ``delete`` reaps the row via the store's secure_delete=ON
    wipe; ``mark_saved`` flips the forward-looking exported-once flag.  Both are
    metadata-only — no image bytes cross, no model is loaded."""

    IMAGE_MANAGE_RESULT = "IMAGE_MANAGE_RESULT"
    """Orchestrator → Gateway: outcome of an IMAGE_MANAGE_REQUEST.

    Carries ``ok`` + the echoed ``action`` + ``image_id`` + ``found`` (whether a
    row matched the id) and, on failure, ``error_code`` / ``message`` labels
    (never content).  A delete/mark of an unknown id is ``ok=True, found=false``
    (idempotent no-op — the store's own contract), NOT an error."""

    # ── Operator preferences (Learning Loops Loop 1, #770 M1) ──

    PREFERENCE_WRITE_REQUEST = "PREFERENCE_WRITE_REQUEST"
    """Gateway → Orchestrator: one explicit operator preference command.

    Carries ``op`` (``remember`` | ``edit`` | ``delete``) + the operator's
    verbatim ``body`` (remember/edit) and/or the full 32-hex ``pref_id``
    (edit/delete).  THE ONLY WRITE PATH to the auto-injected
    OPERATOR_PREFERENCE tier (P8): this frame originates exclusively from the
    gateway's slash-command parse of operator-typed text — no model-callable
    tool, no ingest path, and no AO-internal code emits it (structural
    absence, locked by test_preference_write_authority.py)."""

    PREFERENCE_WRITE_RESULT = "PREFERENCE_WRITE_RESULT"
    """Orchestrator → Gateway: outcome of a PREFERENCE_WRITE_REQUEST.

    Carries ``ok`` + the echoed ``op`` + ``status`` (``stored`` | ``updated``
    | ``deleted`` | ``requires_confirmation`` | ``refused``) + ``pref_id``,
    and on a P5 near-duplicate/contradiction the ``conflict`` record
    (``{pref_id, body}``) the confirmation must resolve.  ``error_code`` /
    ``message`` carry labels on refusal (P4 caps, unknown id, no store)."""

    PREFERENCE_LIST_REQUEST = "PREFERENCE_LIST_REQUEST"
    """Gateway → Orchestrator: list the ACTIVE operator-preference tier.

    No payload beyond the envelope.  The reply carries the operator's own
    decrypted preference bodies back to the operator's own UI over the local
    pipe/vsock — the same trust geometry as PROMPT_REQUEST prompt text."""

    PREFERENCE_LIST_RESPONSE = "PREFERENCE_LIST_RESPONSE"
    """Orchestrator → Gateway: the ACTIVE preference rows, deterministic order.

    ``preferences`` (each projected onto the pinned PREFERENCE_LIST_KEYS) +
    ``total``.  Capped at PREFERENCE_MAX_COUNT rows — the store's own count
    cap guarantees one 64 KB frame always suffices (no truncation limb)."""

    # ── Headless-coding dispatch (agentic-setup brief §9, #670 — DORMANT) ──

    PLAN_REQUEST = "PLAN_REQUEST"
    """Gateway → Orchestrator: run the 14B's acceptance-criteria generation for a
    ``/dispatch`` goal against a target repo (the Acceptance Layer PLAN step).

    METADATA ONLY — carries ``repo`` + plain-English ``goal``.  The AO runs a
    DIRECT, deterministic single-shot completion over the resident 14B (NOT the
    conversational PROMPT_REQUEST path) and the deterministic ruler; nothing is
    enqueued and no work fires (the operator approves the criteria first).  Gated
    by ``[fleet_dispatch].enabled`` at the gateway — the coordinator never sends
    this frame while dormant."""

    PLAN_RESULT = "PLAN_RESULT"
    """Orchestrator → Gateway: the decomposed tasks + the validated AcceptanceSpec.

    METADATA ONLY — ``ok`` + ``message`` + ``fell_back`` + ``tasks`` (the compiled
    ``{repo, task, prompt}`` list) + ``criteria`` (the AcceptanceSpec as a dict:
    ``{goal, criteria:[{id, text, tier, check}]}``).  Plain-English criteria + task
    prompts only — no model weights, no conversation.  On failure ``ok=False`` with
    a ``message`` label."""

    EXECUTE_REQUEST = "EXECUTE_REQUEST"
    """Gateway → Orchestrator: fire the operator-APPROVED dispatch (the EXECUTE step,
    reachable ONLY via ``/dispatch approve``).

    METADATA ONLY — ``session_id`` + ``run_id`` + ``tasks`` (the pre-decomposed,
    APPROVED ``{repo, task, prompt}`` list — the AO NEVER re-decomposes, so the run
    matches what was approved).  The AO enqueues the tasks, hands off to the detached
    swap driver, and steps the launcher aside (the model swap).  The acceptance record
    was already persisted gateway-side BEFORE this frame, so the post-swap report
    survives the restart."""

    EXECUTE_RESULT = "EXECUTE_RESULT"
    """Orchestrator → Gateway: the dispatch was accepted + handed off (or refused).

    METADATA ONLY — ``ok`` + ``run_id`` + ``message``.  Sent BEFORE the launcher steps
    aside (a brief configurable grace), so the operator sees the "stepping aside" notice
    before the WinUI window closes for the swap.  On failure ``ok=False`` (e.g. an
    enqueue refusal) and NO step-aside occurs (the 14B stays up)."""

    # ── Guest-certified oracle channel (#744, plan §10.3 — DORMANT) ──

    ORACLE_EXEC_REQUEST = "ORACLE_EXEC_REQUEST"
    """Host → Guest: run the job-level acceptance oracle inside the NIC-less
    Alpine guest as an ISOLATION CERTIFICATE on top of the host gate (#744).

    SOURCE ONLY — the body is a size-capped ZIP snapshot of the integrated
    target repo's pure-Python source (plus the plan-carried oracle bytes,
    overlaid so a merged edit to the oracle can never help); the chunk-0
    ``meta`` carries the pinned relative oracle path.  Chunked framing
    contract in ``shared/ipc/oracle_channel.py`` (mirrors ``parse_channel``).
    NO production code sends this frame until the LA's supervised go-live
    ceremony wires a transport — structural dormancy, like the guest parser."""

    ORACLE_EXEC_RESPONSE = "ORACLE_EXEC_RESPONSE"
    """Guest → Host: the guest oracle outcome — ADVISORY evidence only.

    METADATA ONLY — a small JSON body: closed-vocabulary ``status``
    (``passed`` | ``failed`` | ``not-run``), a stable machine ``reason`` and a
    bounded human ``evidence`` label (never file contents).  The host gate
    remains the fidelity verdict; this response never changes verdict or
    attribution semantics (#744 design constraint 3)."""


@dataclass(frozen=True)
class AdjudicationRequest:
    """Serialized CAR request for Policy Agent evaluation.

    Sent by any agent to the Policy Agent over vsock.
    """

    car_json: str
    """JSON-encoded CanonicalActionRepresentation."""

    request_id: str
    """Unique request identifier for audit correlation."""

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a dict suitable for JSON encoding."""
        return {"car_json": self.car_json, "request_id": self.request_id}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AdjudicationRequest:
        """Deserialize from a dict."""
        return cls(
            car_json=str(data.get("car_json", "")),
            request_id=str(data.get("request_id", "")),
        )


@dataclass(frozen=True)
class AdjudicationResponse:
    """Adjudication result returned over IPC.

    Contains the decision, optional Agentic JWT, and correlation metadata.
    """

    decision: str
    """ALLOW, DENY, or ESCALATE."""

    jwt_token: str = ""
    """Minted Agentic JWT (empty on DENY/error)."""

    car_hash: str = ""
    """SHA-256 of the adjudicated CAR."""

    request_id: str = ""
    """Correlates to the originating request."""

    error: str = ""
    """Error description (empty on success)."""

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a dict suitable for JSON encoding."""
        return {
            "decision": self.decision,
            "jwt_token": self.jwt_token,
            "car_hash": self.car_hash,
            "request_id": self.request_id,
            "error": self.error,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AdjudicationResponse:
        """Deserialize from a dict."""
        return cls(
            decision=str(data.get("decision", "DENY")),
            jwt_token=str(data.get("jwt_token", "")),
            car_hash=str(data.get("car_hash", "")),
            request_id=str(data.get("request_id", "")),
            error=str(data.get("error", "")),
        )


class MessageFramer:
    """JSON message encoding/decoding for the IPC protocol.

    Handles ONLY the JSON envelope — length-prefixed framing is the
    responsibility of VsockTransport.

    Encode: typed data → JSON bytes.
    Decode: JSON bytes → typed data.
    """

    def __init__(self, max_message_bytes: int = DEFAULT_MAX_MESSAGE_BYTES) -> None:
        self._max_bytes = max_message_bytes

    @property
    def max_message_bytes(self) -> int:
        """Maximum allowed message size in bytes."""
        return self._max_bytes

    # ------------------------------------------------------------------
    # Generic encode / decode
    # ------------------------------------------------------------------

    def encode(
        self,
        msg_type: MessageType,
        payload: dict[str, Any],
        request_id: str = "",
    ) -> bytes:
        """Encode a message into JSON bytes.

        Args:
            msg_type: Message type tag.
            payload: JSON-serializable payload dict.
            request_id: Correlation ID.

        Returns:
            JSON-encoded bytes (no framing header).

        Raises:
            ValueError: If the encoded message exceeds max_message_bytes.
        """
        envelope = json.dumps(
            {
                "type": msg_type.value,
                "request_id": request_id,
                "payload": payload,
            },
            separators=(",", ":"),
        ).encode("utf-8")

        if len(envelope) > self._max_bytes:
            raise ValueError(
                f"Message size {len(envelope)} exceeds limit {self._max_bytes}"
            )
        return envelope

    def decode(
        self, data: bytes
    ) -> tuple[MessageType, str, dict[str, Any]]:
        """Decode JSON bytes into structured components.

        Args:
            data: JSON-encoded message bytes.

        Returns:
            (msg_type, request_id, payload_dict)

        Raises:
            ValueError: If JSON is malformed or type is unknown.
        """
        try:
            envelope = json.loads(data.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise ValueError(f"Malformed JSON: {exc}") from exc

        if not isinstance(envelope, dict):
            raise ValueError("Envelope must be a JSON object")

        try:
            msg_type = MessageType(envelope.get("type", ""))
        except ValueError:
            raise ValueError(f"Unknown message type: {envelope.get('type')}")

        request_id = str(envelope.get("request_id", ""))
        payload = envelope.get("payload", {})
        if not isinstance(payload, dict):
            raise ValueError("Payload must be a dict")

        return msg_type, request_id, payload

    # ------------------------------------------------------------------
    # Typed convenience methods
    # ------------------------------------------------------------------

    def encode_request(self, request: AdjudicationRequest) -> bytes:
        """Encode an AdjudicationRequest into JSON bytes."""
        return self.encode(
            MessageType.ADJUDICATION_REQUEST,
            request.to_dict(),
            request.request_id,
        )

    def decode_request(self, data: bytes) -> AdjudicationRequest:
        """Decode JSON bytes into an AdjudicationRequest.

        Raises:
            ValueError: If the message is not an ADJUDICATION_REQUEST.
        """
        msg_type, _rid, payload = self.decode(data)
        if msg_type != MessageType.ADJUDICATION_REQUEST:
            raise ValueError(f"Expected ADJUDICATION_REQUEST, got {msg_type.value}")
        return AdjudicationRequest.from_dict(payload)

    def encode_response(self, response: AdjudicationResponse) -> bytes:
        """Encode an AdjudicationResponse into JSON bytes."""
        return self.encode(
            MessageType.ADJUDICATION_RESPONSE,
            response.to_dict(),
            response.request_id,
        )

    def decode_response(self, data: bytes) -> AdjudicationResponse:
        """Decode JSON bytes into an AdjudicationResponse.

        Raises:
            ValueError: If the message is not an ADJUDICATION_RESPONSE.
        """
        msg_type, _rid, payload = self.decode(data)
        if msg_type != MessageType.ADJUDICATION_RESPONSE:
            raise ValueError(
                f"Expected ADJUDICATION_RESPONSE, got {msg_type.value}"
            )
        return AdjudicationResponse.from_dict(payload)

    def encode_error(self, error: str, request_id: str = "") -> bytes:
        """Encode an error message into JSON bytes."""
        return self.encode(
            MessageType.ERROR,
            {"error": error},
            request_id,
        )

    def encode_heartbeat(self, request_id: str = "") -> bytes:
        """Encode a heartbeat message into JSON bytes."""
        return self.encode(
            MessageType.HEARTBEAT,
            {"status": "alive"},
            request_id,
        )

    # ------------------------------------------------------------------
    # UI Gateway convenience methods (P1.11)
    # ------------------------------------------------------------------

    def encode_handshake_request(self, request_id: str = "") -> bytes:
        """Encode a Boot-Phase-3 handshake request."""
        return self.encode(
            MessageType.HANDSHAKE_REQUEST,
            {"type": "pa_status_check"},
            request_id,
        )

    def encode_handshake_response(
        self, status: str, request_id: str = ""
    ) -> bytes:
        """Encode a handshake response with PA operational status."""
        return self.encode(
            MessageType.HANDSHAKE_RESPONSE,
            {"status": status},
            request_id,
        )

    def encode_prompt_request(
        self,
        session_id: str,
        prompt: str,
        request_id: str = "",
        history: list[dict[str, str]] | None = None,
        documents: list[dict[str, object]] | None = None,
        clear_documents: bool = False,
        documents_trusted_for_tools: bool = False,
        external_documents: list[dict[str, object]] | None = None,
    ) -> bytes:
        """Encode a user prompt for generation.

        Args:
            session_id: Session identifier.
            prompt: User prompt text.
            request_id: Correlation ID.
            history: Optional prior conversation turns for cold-session seeding.
                Each entry is ``{"role": "user"|"assistant", "content": <str>}``.
                Defaults to None (encoded as empty list). Callers that do not
                pass history are unaffected — backward compatible.
            documents: Optional list of loaded documents to deliver to the AO.
                A text/PDF entry is ``{"filename": <str>, "content": <str>}``.
                A lazily-staged image (#561) instead carries ``{"filename",
                "media_type": "image", "image_path": <str>, "pending_vision":
                True}`` with empty ``content`` — the AO tasks the VLM on demand.
                Defaults to None (encoded as empty list). Backward compatible:
                older receivers use ``payload.get("documents", [])``.
            clear_documents: When True, instructs the AO to clear all prior
                grounded-context documents before this request (the /unload
                command). Defaults to False. Backward compatible: older
                receivers use ``payload.get("clear_documents", False)``.
        """
        return self.encode(
            MessageType.PROMPT_REQUEST,
            {
                "session_id": session_id,
                "prompt": prompt,
                "history": history or [],
                "documents": documents or [],
                "clear_documents": clear_documents,
                "documents_trusted_for_tools": documents_trusted_for_tools,
                "external_documents": external_documents or [],
            },
            request_id,
        )

    def encode_stream_token(
        self,
        token: str,
        token_index: int,
        is_final: bool,
        is_tool_call: bool,
        session_id: str,
        request_id: str = "",
        is_thinking: bool = False,
    ) -> bytes:
        """Encode a single streaming token."""
        return self.encode(
            MessageType.STREAM_TOKEN,
            {
                "token": token,
                "token_index": token_index,
                "is_final": is_final,
                "is_tool_call": is_tool_call,
                "session_id": session_id,
                "is_thinking": is_thinking,
            },
            request_id,
        )

    def encode_pgov_result(
        self,
        approved: bool,
        sanitized_text: str,
        reason_codes: list[str],
        request_id: str = "",
    ) -> bytes:
        """Encode a PGOV validation result."""
        return self.encode(
            MessageType.PGOV_RESULT,
            {
                "approved": approved,
                "sanitized_text": sanitized_text,
                "reason_codes": reason_codes,
            },
            request_id,
        )

    def encode_generation_complete(self, request_id: str = "") -> bytes:
        """Encode a generation-complete signal."""
        return self.encode(
            MessageType.GENERATION_COMPLETE,
            {"status": "complete"},
            request_id,
        )

    # ------------------------------------------------------------------
    # Knowledge-bank ingest convenience methods (UC-002/UC-003, #655)
    # ------------------------------------------------------------------

    #: Decisions accepted on the INGEST_DECISION frame (Fail-Closed at encode).
    INGEST_DECISIONS: frozenset[str] = frozenset({"approve", "reject"})

    #: Ordered metadata keys carried per image on an INGEST_SUBMIT frame
    #: (UC-003 Workstream B, display-only images).  METADATA ONLY — the image
    #: BYTES never ride the frame; they cross via the per-image encrypted
    #: ``image_staging`` blob, exactly mirroring how cleaned text crosses via
    #: ``ingest_staging``.  Each record is normalised to these keys at encode so
    #: a stray caller key can never inflate the envelope past the 64 KB cap.
    INGEST_IMAGE_KEYS: tuple[str, ...] = (
        "image_id",
        "staging_path",
        "alt",
        "source_url",
        "mime",
    )

    def encode_ingest_submit(
        self,
        *,
        doc_uuid: str,
        source_type: str,
        source_ref: str,
        staging_path: str,
        content_sha256: str,
        title: str = "",
        byline: str = "",
        published_date: str = "",
        word_count: int = 0,
        cleaner_version: str = "",
        prior_content_sha256: str = "",
        images: tuple[dict[str, str], ...] = (),
        request_id: str = "",
    ) -> bytes:
        """Encode an ingest-submit request (gateway → AO).

        Size discipline: the cleaned content NEVER rides this frame — it is
        staged via the encrypted ``ingest_staging`` file and only the path +
        metadata labels cross the 64 KB IPC envelope.  The generic
        :meth:`encode` cap still applies (oversized metadata raises).

        ``prior_content_sha256`` is the OPTIONAL operator-edit provenance signal
        (UC-003 editable preview, #663): when the gateway re-submits an
        operator-EDITED body (dedup-replacing the pending row), it carries the
        plaintext SHA-256 of the CLEANER'S ORIGINAL output here.  The AO keys it
        and records ``edited=1`` + the keyed cleaner-digest on the signed ingest
        audit chain (ADR-029 §curation provenance) so the chain honestly attests
        that a human curated the stored body.  Empty (the default) = an
        un-edited submit — the AO records nothing extra.  Like ``content_sha256``
        this plaintext digest is transient at the AO (keyed before it touches the
        signed-plaintext audit file — never persisted as a membership oracle).

        ``images`` is the OPTIONAL, ADDITIVE display-only-image manifest (UC-003
        Workstream B): a tuple of per-image METADATA records, each carrying
        ``image_id`` / ``staging_path`` / ``alt`` / ``source_url`` / ``mime`` —
        and NOTHING ELSE.  The image BYTES never ride this frame; like the
        cleaned text they cross the boundary via a per-image encrypted
        ``image_staging`` blob, and the AO reads each blob → stores the image →
        deletes the blob.  Default empty tuple → an INGEST_SUBMIT with no images
        is byte-IDENTICAL to a pre-Workstream-B submit minus the absent key
        (additive, exactly like ``prior_content_sha256`` was added).  Each record
        is NORMALISED to the five pinned keys (``INGEST_IMAGE_KEYS``) and string
        values so a malformed/oversized record never silently rides the frame and
        the 64 KB envelope discipline is preserved.

        Raises:
            ValueError: If *content_sha256* is absent/empty (Fail-Closed at
                encode — the AO's staged-content integrity cross-check is
                mandatory, so a frame without the hash never crosses IPC).
        """
        if not content_sha256.strip():
            raise ValueError(
                "encode_ingest_submit: content_sha256 is required — the AO's "
                "staged-content integrity cross-check is mandatory (Fail-Closed)."
            )
        payload: dict[str, Any] = {
            "doc_uuid": doc_uuid,
            "source_type": source_type,
            "source_ref": source_ref,
            "staging_path": staging_path,
            "content_sha256": content_sha256,
            "title": title,
            "byline": byline,
            "published_date": published_date,
            "word_count": word_count,
            "cleaner_version": cleaner_version,
            "prior_content_sha256": prior_content_sha256,
        }
        # Additive: only attach the key when images are present, so a no-image
        # submit stays byte-compatible with frames produced before this field
        # existed (mirrors how ``prior_content_sha256`` was added — except that
        # one always rides; the image manifest is keyed only when non-empty).
        if images:
            payload["images"] = [
                # METADATA ONLY: project each record onto the pinned key set and
                # coerce values to str.  A record key outside INGEST_IMAGE_KEYS
                # (e.g. an accidental bytes blob) is DROPPED, never forwarded —
                # the frame cannot carry image bytes by construction.
                {key: str(record.get(key, "")) for key in self.INGEST_IMAGE_KEYS}
                for record in images
            ]
        return self.encode(MessageType.INGEST_SUBMIT, payload, request_id)

    def encode_ingest_decision(
        self,
        *,
        doc_uuid: str,
        decision: str,
        request_id: str = "",
    ) -> bytes:
        """Encode an operator ingest decision (gateway → AO).

        Raises:
            ValueError: If *decision* is not ``approve`` or ``reject``
                (Fail-Closed at encode — a malformed decision never crosses IPC).
        """
        if decision not in self.INGEST_DECISIONS:
            raise ValueError(
                f"Invalid ingest decision {decision!r}; "
                f"expected one of {sorted(self.INGEST_DECISIONS)}"
            )
        return self.encode(
            MessageType.INGEST_DECISION,
            {"doc_uuid": doc_uuid, "decision": decision},
            request_id,
        )

    def encode_ingest_result(
        self,
        *,
        ok: bool,
        doc_uuid: str,
        state: str,
        chunk_count: int = 0,
        error_code: str = "",
        message: str = "",
        request_id: str = "",
    ) -> bytes:
        """Encode an ingest outcome (AO → gateway).

        ``state`` is one of ``pending | already_ingested | approved | rejected``
        on success, or ``error`` on failure (with ``error_code``/``message``
        labels — never content).
        """
        return self.encode(
            MessageType.INGEST_RESULT,
            {
                "ok": ok,
                "doc_uuid": doc_uuid,
                "state": state,
                "chunk_count": chunk_count,
                "error_code": error_code,
                "message": message,
            },
            request_id,
        )

    def decode_ingest_result(self, data: bytes) -> dict[str, Any]:
        """Decode JSON bytes into an INGEST_RESULT payload dict.

        Raises:
            ValueError: If the message is not an INGEST_RESULT.
        """
        msg_type, _rid, payload = self.decode(data)
        if msg_type != MessageType.INGEST_RESULT:
            raise ValueError(f"Expected INGEST_RESULT, got {msg_type.value}")
        return {
            "ok": bool(payload.get("ok", False)),
            "doc_uuid": str(payload.get("doc_uuid", "")),
            "state": str(payload.get("state", "error")),
            "chunk_count": int(payload.get("chunk_count", 0)),
            "error_code": str(payload.get("error_code", "")),
            "message": str(payload.get("message", "")),
        }

    # ------------------------------------------------------------------
    # Headless-coding dispatch — PLAN convenience methods (#670)
    # ------------------------------------------------------------------

    def encode_plan_request(
        self, *, repo: str, goal: str, request_id: str = ""
    ) -> bytes:
        """Encode a PLAN request (gateway → AO).  Metadata only (repo + goal)."""
        return self.encode(
            MessageType.PLAN_REQUEST, {"repo": repo, "goal": goal}, request_id
        )

    def decode_plan_request(self, data: bytes) -> dict[str, Any]:
        """Decode JSON bytes into a PLAN_REQUEST payload dict.

        Raises:
            ValueError: If the message is not a PLAN_REQUEST.
        """
        msg_type, _rid, payload = self.decode(data)
        if msg_type != MessageType.PLAN_REQUEST:
            raise ValueError(f"Expected PLAN_REQUEST, got {msg_type.value}")
        return {
            "repo": str(payload.get("repo", "")),
            "goal": str(payload.get("goal", "")),
        }

    def encode_plan_result(
        self,
        *,
        ok: bool,
        message: str = "",
        fell_back: bool = False,
        tasks: "list[dict] | None" = None,
        criteria: "dict[str, Any] | None" = None,
        request_id: str = "",
    ) -> bytes:
        """Encode a PLAN result (AO → gateway): tasks + the validated AcceptanceSpec.

        Metadata only — the compiled ``{repo, task, prompt}`` tasks + the spec dict
        (``{goal, criteria:[...]}``).  The 64 KB frame cap holds easily (a handful of
        short task prompts + plain-English criteria); an over-cap payload raises at
        ``encode`` (Fail-Closed), never a silent truncation.
        """
        return self.encode(
            MessageType.PLAN_RESULT,
            {
                "ok": ok,
                "message": message,
                "fell_back": fell_back,
                "tasks": list(tasks or []),
                "criteria": dict(criteria or {}),
            },
            request_id,
        )

    def decode_plan_result(self, data: bytes) -> dict[str, Any]:
        """Decode JSON bytes into a PLAN_RESULT payload dict.

        Raises:
            ValueError: If the message is not a PLAN_RESULT.
        """
        msg_type, _rid, payload = self.decode(data)
        if msg_type != MessageType.PLAN_RESULT:
            raise ValueError(f"Expected PLAN_RESULT, got {msg_type.value}")
        return {
            "ok": bool(payload.get("ok", False)),
            "message": str(payload.get("message", "")),
            "fell_back": bool(payload.get("fell_back", False)),
            "tasks": list(payload.get("tasks", [])),
            "criteria": dict(payload.get("criteria", {})),
        }

    def encode_execute_request(
        self,
        *,
        session_id: str,
        run_id: str,
        tasks: "list[dict] | None" = None,
        request_id: str = "",
    ) -> bytes:
        """Encode an EXECUTE request (gateway → AO): the APPROVED, pre-decomposed tasks."""
        return self.encode(
            MessageType.EXECUTE_REQUEST,
            {"session_id": session_id, "run_id": run_id, "tasks": list(tasks or [])},
            request_id,
        )

    def decode_execute_request(self, data: bytes) -> dict[str, Any]:
        """Decode JSON bytes into an EXECUTE_REQUEST payload dict.

        Raises:
            ValueError: If the message is not an EXECUTE_REQUEST.
        """
        msg_type, _rid, payload = self.decode(data)
        if msg_type != MessageType.EXECUTE_REQUEST:
            raise ValueError(f"Expected EXECUTE_REQUEST, got {msg_type.value}")
        return {
            "session_id": str(payload.get("session_id", "")),
            "run_id": str(payload.get("run_id", "")),
            "tasks": list(payload.get("tasks", [])),
        }

    def encode_execute_result(
        self, *, ok: bool, run_id: str = "", message: str = "", request_id: str = ""
    ) -> bytes:
        """Encode an EXECUTE result (AO → gateway): accepted + handed off, or refused."""
        return self.encode(
            MessageType.EXECUTE_RESULT,
            {"ok": ok, "run_id": run_id, "message": message},
            request_id,
        )

    def decode_execute_result(self, data: bytes) -> dict[str, Any]:
        """Decode JSON bytes into an EXECUTE_RESULT payload dict.

        Raises:
            ValueError: If the message is not an EXECUTE_RESULT.
        """
        msg_type, _rid, payload = self.decode(data)
        if msg_type != MessageType.EXECUTE_RESULT:
            raise ValueError(f"Expected EXECUTE_RESULT, got {msg_type.value}")
        return {
            "ok": bool(payload.get("ok", False)),
            "run_id": str(payload.get("run_id", "")),
            "message": str(payload.get("message", "")),
        }

    # ------------------------------------------------------------------
    # Local generative imaging convenience methods (UC-010, ADR-033)
    # ------------------------------------------------------------------

    #: Image-gen modes accepted on the IMAGE_GEN_REQUEST frame.
    IMAGE_GEN_MODES: frozenset[str] = frozenset({"text2image", "image2image"})

    #: Image-gen STYLES (#703) — the command-level selector that rides the
    #: IMAGE_GEN_REQUEST frame. The gateway sets it from the chat command
    #: (/imagine→photoreal, /illustrate→illustration, /cartoon→cartoon); the AO
    #: maps each to a model + (cartoon only) a RUNTIME LoRA adapter.
    IMAGE_GEN_STYLE_PHOTOREAL = "photoreal"
    IMAGE_GEN_STYLE_ILLUSTRATION = "illustration"
    IMAGE_GEN_STYLE_CARTOON = "cartoon"
    IMAGE_GEN_STYLES: frozenset[str] = frozenset(
        {
            IMAGE_GEN_STYLE_PHOTOREAL,
            IMAGE_GEN_STYLE_ILLUSTRATION,
            IMAGE_GEN_STYLE_CARTOON,
        }
    )

    def encode_image_gen_request(
        self,
        *,
        session_id: str,
        mode: str,
        prompt: str,
        style: str = "photoreal",
        width: int = 1024,
        height: int = 1024,
        steps: int = 0,
        seed: int = 0,
        staging_ref: str = "",
        staging_image_id: str = "",
        request_id: str = "",
    ) -> bytes:
        """Encode an image-generation request (gateway → AO).

        METADATA ONLY: the prompt + caps + (for img2img) the encrypted-staging
        reference cross this frame; the seed image BYTES ride the encrypted
        ``image_staging`` blob (NEVER this frame, NEVER a URL). ``steps``/``seed``
        of 0 mean "use the configured default" / "no seed".

        ``style`` (#703) selects the visual style/model the AO loads:
        ``photoreal`` (RealVisXL, /imagine), ``illustration`` (base SDXL flat
        vector, /illustrate), or ``cartoon`` (base SDXL + a RUNTIME LoRA,
        /cartoon). Default ``photoreal`` keeps an un-styled request byte-compatible
        with the pre-#703 frame (an absent ``style`` reads as photoreal AO-side).

        Raises:
            ValueError: If *mode* is not a known image-gen mode, or *style* is not
                a known style (Fail-Closed at encode — a malformed value never
                crosses IPC).
        """
        if mode not in self.IMAGE_GEN_MODES:
            raise ValueError(
                f"Invalid image-gen mode {mode!r}; "
                f"expected one of {sorted(self.IMAGE_GEN_MODES)}"
            )
        if style not in self.IMAGE_GEN_STYLES:
            raise ValueError(
                f"Invalid image-gen style {style!r}; "
                f"expected one of {sorted(self.IMAGE_GEN_STYLES)}"
            )
        return self.encode(
            MessageType.IMAGE_GEN_REQUEST,
            {
                "session_id": session_id,
                "mode": mode,
                "prompt": prompt,
                "style": style,
                "width": int(width),
                "height": int(height),
                "steps": int(steps),
                "seed": int(seed),
                "staging_ref": staging_ref,
                "staging_image_id": staging_image_id,
            },
            request_id,
        )

    def encode_image_gen_result(
        self,
        *,
        ok: bool,
        image_ref: str = "",
        mime: str = "",
        error_code: str = "",
        message: str = "",
        request_id: str = "",
    ) -> bytes:
        """Encode an image-generation outcome (AO → gateway).

        On success ``image_ref`` is a ``blarai-img://<image_id>`` reference and
        ``mime`` is the stored mime; on failure ``error_code``/``message`` carry
        labels only (never content)."""
        return self.encode(
            MessageType.IMAGE_GEN_RESULT,
            {
                "ok": ok,
                "image_ref": image_ref,
                "mime": mime,
                "error_code": error_code,
                "message": message,
            },
            request_id,
        )

    def decode_image_gen_result(self, data: bytes) -> dict[str, Any]:
        """Decode JSON bytes into an IMAGE_GEN_RESULT payload dict.

        Raises:
            ValueError: If the message is not an IMAGE_GEN_RESULT.
        """
        msg_type, _rid, payload = self.decode(data)
        if msg_type != MessageType.IMAGE_GEN_RESULT:
            raise ValueError(f"Expected IMAGE_GEN_RESULT, got {msg_type.value}")
        return {
            "ok": bool(payload.get("ok", False)),
            "image_ref": str(payload.get("image_ref", "")),
            "mime": str(payload.get("mime", "")),
            "error_code": str(payload.get("error_code", "")),
            "message": str(payload.get("message", "")),
        }

    # ------------------------------------------------------------------
    # Generated-image management convenience methods (UC-010 Phase 1, #667)
    # ------------------------------------------------------------------

    #: Hard cap on metadata records carried in ONE IMAGE_LIST_RESPONSE frame.
    #: Each record is ~6 small fields (~130 bytes encoded), so 200 records sit
    #: well under the 64 KB envelope with ample headroom; older images beyond
    #: the cap are reported via ``truncated=true`` + a ``total`` count.  The AO
    #: returns the NEWEST images first, so the cap never hides recent work.
    IMAGE_LIST_MAX_ITEMS: int = 200

    #: Ordered metadata keys carried per image on an IMAGE_LIST_RESPONSE frame —
    #: METADATA ONLY (no decrypted prompt, no image bytes).  Each record is
    #: normalised to these keys at encode so a stray caller key can never inflate
    #: the envelope or smuggle content onto the wire.
    IMAGE_LIST_KEYS: tuple[str, ...] = (
        "image_id",
        "session_id",
        "mime",
        "byte_size",
        "saved",
        "created_at",
    )

    #: Management actions accepted on an IMAGE_MANAGE_REQUEST (Fail-Closed at encode).
    IMAGE_MANAGE_ACTIONS: frozenset[str] = frozenset({"delete", "mark_saved"})

    def encode_image_list_request(
        self, *, session_id: str = "", request_id: str = ""
    ) -> bytes:
        """Encode a generated-image-list request (gateway → AO).

        ``session_id`` is an OPTIONAL filter; empty lists across all sessions.
        """
        return self.encode(
            MessageType.IMAGE_LIST_REQUEST,
            {"session_id": session_id},
            request_id,
        )

    def encode_image_list_response(
        self,
        *,
        images: "list[dict[str, Any]]",
        total: int,
        truncated: bool = False,
        request_id: str = "",
    ) -> bytes:
        """Encode a generated-image metadata listing (AO → gateway).

        METADATA ONLY: each record is projected onto the pinned
        :attr:`IMAGE_LIST_KEYS` and coerced (``byte_size`` int, ``saved`` bool,
        the rest str) so a malformed/oversized record — or an accidental
        bytes/prompt field — can NEVER ride the frame.  ``total`` is the full
        stored count; ``truncated`` signals images exist beyond the per-frame cap.
        """
        norm: list[dict[str, Any]] = []
        for record in images:
            norm.append(
                {
                    "image_id": str(record.get("image_id", "")),
                    "session_id": str(record.get("session_id", "")),
                    "mime": str(record.get("mime", "")),
                    "byte_size": int(record.get("byte_size", 0) or 0),
                    "saved": bool(record.get("saved", False)),
                    "created_at": str(record.get("created_at", "")),
                }
            )
        return self.encode(
            MessageType.IMAGE_LIST_RESPONSE,
            {"images": norm, "total": int(total), "truncated": bool(truncated)},
            request_id,
        )

    def decode_image_list_response(self, data: bytes) -> dict[str, Any]:
        """Decode JSON bytes into an IMAGE_LIST_RESPONSE payload dict.

        Returns ``{"images": [<normalised record>...], "total": int,
        "truncated": bool}``.  Each record is re-normalised to the pinned key
        set on decode too (defence in depth — a hostile AO cannot inject extra
        keys into the gateway-side structure).

        Raises:
            ValueError: If the message is not an IMAGE_LIST_RESPONSE.
        """
        msg_type, _rid, payload = self.decode(data)
        if msg_type != MessageType.IMAGE_LIST_RESPONSE:
            raise ValueError(f"Expected IMAGE_LIST_RESPONSE, got {msg_type.value}")
        raw_images = payload.get("images", [])
        images: list[dict[str, Any]] = []
        if isinstance(raw_images, list):
            for record in raw_images:
                if not isinstance(record, dict):
                    continue
                images.append(
                    {
                        "image_id": str(record.get("image_id", "")),
                        "session_id": str(record.get("session_id", "")),
                        "mime": str(record.get("mime", "")),
                        "byte_size": int(record.get("byte_size", 0) or 0),
                        "saved": bool(record.get("saved", False)),
                        "created_at": str(record.get("created_at", "")),
                    }
                )
        return {
            "images": images,
            "total": int(payload.get("total", len(images))),
            "truncated": bool(payload.get("truncated", False)),
        }

    def encode_image_manage_request(
        self, *, action: str, image_id: str, request_id: str = ""
    ) -> bytes:
        """Encode a generated-image management action (gateway → AO).

        Raises:
            ValueError: If *action* is not ``delete`` or ``mark_saved``
                (Fail-Closed at encode — a malformed action never crosses IPC).
        """
        if action not in self.IMAGE_MANAGE_ACTIONS:
            raise ValueError(
                f"Invalid image-manage action {action!r}; "
                f"expected one of {sorted(self.IMAGE_MANAGE_ACTIONS)}"
            )
        return self.encode(
            MessageType.IMAGE_MANAGE_REQUEST,
            {"action": action, "image_id": image_id},
            request_id,
        )

    def encode_image_manage_result(
        self,
        *,
        ok: bool,
        action: str,
        image_id: str,
        found: bool,
        error_code: str = "",
        message: str = "",
        request_id: str = "",
    ) -> bytes:
        """Encode the outcome of an IMAGE_MANAGE_REQUEST (AO → gateway).

        ``found`` reports whether a row matched the id (a delete/mark of an
        unknown id is ``ok=True, found=false`` — an idempotent no-op, not an
        error).  ``error_code``/``message`` carry labels only on failure.
        """
        return self.encode(
            MessageType.IMAGE_MANAGE_RESULT,
            {
                "ok": ok,
                "action": action,
                "image_id": image_id,
                "found": found,
                "error_code": error_code,
                "message": message,
            },
            request_id,
        )

    def decode_image_manage_result(self, data: bytes) -> dict[str, Any]:
        """Decode JSON bytes into an IMAGE_MANAGE_RESULT payload dict.

        Raises:
            ValueError: If the message is not an IMAGE_MANAGE_RESULT.
        """
        msg_type, _rid, payload = self.decode(data)
        if msg_type != MessageType.IMAGE_MANAGE_RESULT:
            raise ValueError(f"Expected IMAGE_MANAGE_RESULT, got {msg_type.value}")
        return {
            "ok": bool(payload.get("ok", False)),
            "action": str(payload.get("action", "")),
            "image_id": str(payload.get("image_id", "")),
            "found": bool(payload.get("found", False)),
            "error_code": str(payload.get("error_code", "")),
            "message": str(payload.get("message", "")),
        }

    # ── Operator preferences (Learning Loops Loop 1, #770 M1) ───────────

    #: Operations accepted on a PREFERENCE_WRITE_REQUEST (Fail-Closed at encode).
    #: ``confirm``/``dismiss`` (#770 M2 W1) resolve a staged model PROPOSAL by
    #: opaque ``token`` — the operator-typed/clicked confirm hop; the AO reads the
    #: STAGED verbatim bytes and commits (P2 across the proposal hop, P8 write
    #: authority preserved — the model never re-supplies the body at confirm).
    PREFERENCE_WRITE_OPS: frozenset[str] = frozenset(
        {"remember", "edit", "delete", "confirm", "dismiss"}
    )

    #: Write-result statuses (Fail-Closed at encode).  ``dismissed`` (#770 M2 W1)
    #: is a confirmed-nothing outcome; a confirmed proposal reuses
    #: ``stored``/``updated``/``deleted`` per the staged action.
    PREFERENCE_WRITE_STATUSES: frozenset[str] = frozenset(
        {
            "stored", "updated", "deleted", "requires_confirmation", "refused",
            "dismissed",
        }
    )

    #: Ordered keys carried per preference on a PREFERENCE_LIST_RESPONSE frame.
    #: Each record is projected onto exactly these keys at encode AND decode so
    #: a stray caller key can never inflate the envelope.
    PREFERENCE_LIST_KEYS: tuple[str, ...] = (
        "pref_id",
        "type_tag",
        "subject",
        "body",
        "created",
        "updated",
        "expires",  # #770 M2 W2 — operator-stated ISO expiry ('' = none)
    )

    @classmethod
    def _normalize_preference_record(cls, record: dict[str, Any]) -> dict[str, str]:
        """Project one preference record onto the pinned key set (all str)."""
        return {key: str(record.get(key, "")) for key in cls.PREFERENCE_LIST_KEYS}

    def encode_preference_write_request(
        self,
        *,
        op: str,
        body: str = "",
        pref_id: str = "",
        token: str = "",
        expires: str = "",
        request_id: str = "",
    ) -> bytes:
        """Encode an operator preference-write command (gateway → AO).

        ``token`` (#770 M2 W1) carries the staged-proposal handle for the
        ``confirm``/``dismiss`` ops; it is empty for ``remember``/``edit``/
        ``delete``.  The confirm frame deliberately carries NO body — the AO
        commits the STAGED verbatim bytes, so a model restatement cannot change
        what is written (confirm-hop integrity).

        Raises:
            ValueError: If *op* is not in :attr:`PREFERENCE_WRITE_OPS`
                (Fail-Closed at encode — a malformed op never crosses IPC).
        """
        if op not in self.PREFERENCE_WRITE_OPS:
            raise ValueError(
                f"Invalid preference-write op {op!r}; "
                f"expected one of {sorted(self.PREFERENCE_WRITE_OPS)}"
            )
        return self.encode(
            MessageType.PREFERENCE_WRITE_REQUEST,
            {
                "op": op, "body": body, "pref_id": pref_id, "token": token,
                "expires": expires,
            },
            request_id,
        )

    def encode_preference_write_result(
        self,
        *,
        ok: bool,
        op: str,
        status: str,
        pref_id: str = "",
        conflict: dict[str, Any] | None = None,
        token: str = "",
        error_code: str = "",
        message: str = "",
        request_id: str = "",
    ) -> bytes:
        """Encode the outcome of a PREFERENCE_WRITE_REQUEST (AO → gateway).

        ``conflict`` (P5) carries the near-duplicate row a REQUIRES_CONFIRMATION
        must resolve — projected onto ``{pref_id, body}`` only.  ``token`` (#770
        M2 W2) carries the staged-proposal handle a one-step contradiction
        confirm resolves — the operator confirms it with /remember-confirm.

        Raises:
            ValueError: If *status* is not in :attr:`PREFERENCE_WRITE_STATUSES`.
        """
        if status not in self.PREFERENCE_WRITE_STATUSES:
            raise ValueError(
                f"Invalid preference-write status {status!r}; "
                f"expected one of {sorted(self.PREFERENCE_WRITE_STATUSES)}"
            )
        norm_conflict = (
            {
                "pref_id": str(conflict.get("pref_id", "")),
                "body": str(conflict.get("body", "")),
            }
            if conflict
            else None
        )
        return self.encode(
            MessageType.PREFERENCE_WRITE_RESULT,
            {
                "ok": ok,
                "op": op,
                "status": status,
                "pref_id": pref_id,
                "conflict": norm_conflict,
                "token": token,
                "error_code": error_code,
                "message": message,
            },
            request_id,
        )

    def decode_preference_write_result(self, data: bytes) -> dict[str, Any]:
        """Decode JSON bytes into a PREFERENCE_WRITE_RESULT payload dict.

        Raises:
            ValueError: If the message is not a PREFERENCE_WRITE_RESULT.
        """
        msg_type, _rid, payload = self.decode(data)
        if msg_type != MessageType.PREFERENCE_WRITE_RESULT:
            raise ValueError(
                f"Expected PREFERENCE_WRITE_RESULT, got {msg_type.value}"
            )
        raw_conflict = payload.get("conflict")
        conflict = (
            {
                "pref_id": str(raw_conflict.get("pref_id", "")),
                "body": str(raw_conflict.get("body", "")),
            }
            if isinstance(raw_conflict, dict)
            else None
        )
        return {
            "ok": bool(payload.get("ok", False)),
            "op": str(payload.get("op", "")),
            "status": str(payload.get("status", "")),
            "pref_id": str(payload.get("pref_id", "")),
            "conflict": conflict,
            "token": str(payload.get("token", "")),
            "error_code": str(payload.get("error_code", "")),
            "message": str(payload.get("message", "")),
        }

    def encode_preference_list_request(self, *, request_id: str = "") -> bytes:
        """Encode a preference-list request (gateway → AO)."""
        return self.encode(
            MessageType.PREFERENCE_LIST_REQUEST, {}, request_id,
        )

    def encode_preference_list_response(
        self,
        *,
        preferences: "list[dict[str, Any]]",
        request_id: str = "",
    ) -> bytes:
        """Encode the ACTIVE preference listing (AO → gateway).

        Each record is projected onto the pinned :attr:`PREFERENCE_LIST_KEYS`
        so a stray field can never ride the frame.  The store's
        PREFERENCE_MAX_COUNT cap bounds the frame size (no truncation limb).
        """
        norm = [self._normalize_preference_record(r) for r in preferences]
        return self.encode(
            MessageType.PREFERENCE_LIST_RESPONSE,
            {"preferences": norm, "total": len(norm)},
            request_id,
        )

    def decode_preference_list_response(self, data: bytes) -> dict[str, Any]:
        """Decode JSON bytes into a PREFERENCE_LIST_RESPONSE payload dict.

        Records are re-normalised onto the pinned key set on decode too
        (defence in depth — a hostile AO cannot inject extra keys).

        Raises:
            ValueError: If the message is not a PREFERENCE_LIST_RESPONSE.
        """
        msg_type, _rid, payload = self.decode(data)
        if msg_type != MessageType.PREFERENCE_LIST_RESPONSE:
            raise ValueError(
                f"Expected PREFERENCE_LIST_RESPONSE, got {msg_type.value}"
            )
        raw = payload.get("preferences", [])
        preferences: list[dict[str, str]] = []
        if isinstance(raw, list):
            for record in raw:
                if isinstance(record, dict):
                    preferences.append(self._normalize_preference_record(record))
        return {
            "preferences": preferences,
            "total": int(payload.get("total", len(preferences))),
        }
