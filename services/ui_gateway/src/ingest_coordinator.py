"""
Ingest Coordinator — gateway-side UC-003 command surface (Vikunja #655 Stage B)
===============================================================================
Orchestrates the operator-facing half of the knowledge-bank ingest flow
(ADR-030 / ADR-031): parse the explicit chat commands, acquire + clean the
content, stage it ENCRYPTED for the AO, drive the INGEST_* IPC verbs, and
render the preview / decision messages that echo into the chat transcript as
deterministic *informational* turns (never model output, never PGOV-validated).

Commands (explicit by doctrine — ADR-030 §7; network actions are never
inferred from conversational text):

  ``/ingest <arg>``  — submit content for review.  Deterministic argument
    classification (documented order):

      1. ``http://`` / ``https://`` prefix → **URL mode** (UC-003 Stage C host
         glue, #655 sub-task 6).  The fetch crosses the SINGLE Policy-Agent-
         gated egress door (``shared.security.guarded_fetch``); the hostile
         HTML is parsed INSIDE the NIC-less guest (only clean text returns over
         vsock — ADR-030 §3) and the host composes the injection axis before
         the preview.  Gated on the guest parser being READY: with it
         unavailable (the shipped default — ``guest_parser.enabled=false`` and
         the egress door deny-by-default), URL mode refuses loudly and points
         to the interim paste path.  No host-side parse of hostile HTML, ever.
      2. An absolute path the operator gave → **FILE mode**.  Absolute mode
         deliberately bypasses the userdata/ containment for LOCAL paths only
         (operator convenience: the operator explicitly named the file).
         UNC/network paths (``\\\\host\\share\\…``, the ``\\\\?\\UNC\\…``
         long-path form — anything whose raw or resolved form starts with
         ``\\\\``) are refused loudly: an air-gapped runtime never reads
         off-host/SMB content (the refusal also covers ``\\\\?\\C:\\…``
         extended-length LOCAL paths — a named fail-closed trade-off; give
         the plain drive-letter path instead).  The path must exist; every
         guard failure (missing file, extension, size, encoding) is a loud
         refusal — an absolute path NEVER falls through to paste.
      3. A single whitespace-free token ending in an accepted extension
         (``.txt .md .markdown .html .htm``) → **FILE mode under userdata/**
         with the document_loader containment discipline (resolved path must
         stay inside userdata/).  Missing file / escape → loud refusal, never
         paste (a filename-shaped token pasted as an "article" would be an
         operator-error trap).
      4. Anything else → **PASTE mode** — the remainder of the message IS the
         article text.

    FILE mode applies the document_loader-pattern guards (extension allowlist,
    containment for bare filenames, loud refusals) but NOT its 16 KB grounding
    cap: ingest stores documents for retrieval, not per-turn grounding, so the
    bound is the ``[knowledge].staging_max_bytes`` ingest cap (262,144 bytes —
    ADR-030 §9), which caps the on-disk CIPHERTEXT; the gateway enforces the
    effective PLAINTEXT cap (``staging_max_bytes`` minus the
    ``CIPHER_ENVELOPE_OVERHEAD_BYTES`` AES-GCM envelope) so a passed check
    never bounces at the AO.  ``.pdf`` is deliberately NOT accepted in v1:
    the Cleaner contract (clean_html/clean_text) has no PDF path yet — named
    deferral, not an oversight.

  ``/approve`` / ``/reject`` — decide the session's pending document.  No
    argument accepted (one pending slot, nothing to disambiguate).

Pending-slot model (v1): ONE outstanding pending ingest per session, held
in-memory keyed by session_id.  A second ``/ingest`` before a decision is
refused naming the pending document.  Rejected alternative: a queue — plural
pending docs need list/select UX (``/approve <n>``), ordering rules, and a
reconciliation story, all for a flow whose whole point is "read the preview
you just asked for, then decide".  The slot clears on a successful decision
AND on a deterministic AO refusal (``INGEST_DECISION_REFUSED`` — the slot no
longer matches AO reality); it is kept on transient failures (transport
error, bank disabled) so the operator can retry.

Restart consequence (documented, deliberate): the slot is in-memory, so a
gateway restart forgets it — but the pending ROW survives in the AO's
knowledge bank.  Re-running ``/ingest`` with the same source re-submits and
REPLACES the prior pending row per the dedup contract (same keyed source-hash
→ delete + insert), so the same source never accumulates orphans.  Pending
rows from *other* forgotten sources remain AO-side (``list_pending``) — a
``/pending`` listing command is a named follow-up, not Stage-B scope.

Cleaner integration: the pipeline is **constructor-injected** (tests mock it);
the real wiring lazily imports ``services.cleaner.src.pipeline`` (a sibling
Stage-B deliverable) and fails LOUDLY with a "cleaner unavailable" message
when absent — never a silent passthrough of uncleaned content.  Both
``clean`` and ``quarantined`` verdicts proceed to the encrypted staging file
and the AO pending row: the L0 pending state IS the ingest quarantine
(ADR-030 §6) and the operator's ``/approve`` is the override.

Security posture (Fail-Closed):
  * Content crosses to the AO ONLY via the encrypted staging file
    (``shared/security/ingest_staging``) under the shared DEK — never the
    64 KB IPC frame.
  * ``content_sha256`` is computed over the cleaned text and is REQUIRED on
    the INGEST_SUBMIT frame (the encoder refuses without it).
  * No cipher → loud refusal (no plaintext staging fallback, ever).
  * Oversize content is refused BEFORE staging.
  * A failed submit deletes the orphaned staging file (fail-safe cleanup).
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import re
import uuid as _uuid_mod
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable, Protocol

from shared.ipc import MessageFramer
from shared.ipc.parse_channel import PARSE_BODY_MAX_BYTES
from shared.security.image_egress_consent import (
    ImageEgressConsentContext,
    host_from_url,
    request_image_egress_consent,
    same_site,
)
from shared.security.image_staging import (
    delete_staged_image,
    write_staged_image,
)
from shared.security.ingest_staging import (
    CIPHER_ENVELOPE_OVERHEAD_BYTES,
    DEFAULT_STAGING_MAX_BYTES,
    StagingError,
    default_staging_dir,
    delete_staged,
    write_staged,
)
from shared.ttl_dict import TtlDict

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: Ingest FILE-mode extension allowlist, split by cleaner entry point.
#: ``.pdf`` deliberately absent (no Cleaner PDF path in v1 — named deferral).
INGEST_HTML_EXTENSIONS: frozenset[str] = frozenset({".html", ".htm"})
INGEST_TEXT_EXTENSIONS: frozenset[str] = frozenset({".txt", ".md", ".markdown"})
INGEST_FILE_EXTENSIONS: frozenset[str] = INGEST_HTML_EXTENSIONS | INGEST_TEXT_EXTENSIONS

#: Byte cap for ingest content — mirrors ``[knowledge].staging_max_bytes``
#: (the AO re-enforces its configured value at staging-read time; ADR-030 §9).
#: This caps the on-disk CIPHERTEXT; the gateway's plaintext checks subtract
#: ``CIPHER_ENVELOPE_OVERHEAD_BYTES`` (the AES-256-GCM version + nonce + tag
#: envelope) so a plaintext that passes here always produces a staged file
#: within the AO's read cap — without the subtraction, plaintext in the last
#: 29 bytes below the cap passed the gateway and bounced at the AO with a
#: confusing same-number cap error (#655 byte-cap seam fix).
DEFAULT_INGEST_MAX_BYTES: int = DEFAULT_STAGING_MAX_BYTES

#: A message that is SOLELY one URL (+/- surrounding whitespace).  ``\S+``
#: forbids interior whitespace, so a URL inside a longer sentence never
#: matches — exact-shape check only (#655 LA requirement, 2026-06-10).
_BARE_URL_RE = re.compile(r"https?://\S+\Z", re.IGNORECASE)

#: The activation gate named in every dormant-fetch message (ADR-030 §8).
EGRESS_ACTIVATION_GATE: str = "#598 sign-off + ADR-027 Amendment 1"

_USAGE_MESSAGE: str = (
    "Usage: `/ingest <pasted article text>`, `/ingest <filename in userdata/>`, "
    "`/ingest <absolute file path>`, or `/ingest <url>`. (`/ingest <url>` fetches "
    "the page through the guarded egress door and parses it in the VM when the "
    "guest parser is running; until then — the shipped default — it refuses and "
    f"points you to pasting the text. Activation gate: {EGRESS_ACTIVATION_GATE}.)"
)


# ---------------------------------------------------------------------------
# Cleaner pipeline contract (services/cleaner/src/pipeline.py — sibling agent)
# ---------------------------------------------------------------------------


class CleanResultLike(Protocol):
    """Structural view of ``services.cleaner.src.pipeline.CleanResult``.

    This module codes against the cross-agent interface contract only — it
    never constructs a CleanResult and never imports the cleaner eagerly.
    """

    status: str                    # 'clean' | 'quarantined'
    text: str
    title: str | None
    byline: str | None
    published_date: str | None
    word_count: int
    confidence: float
    reasons: tuple[str, ...]
    cleaner_version: str
    source_format: str             # 'html' | 'text' | 'markdown'


#: ``clean_text(raw_text) -> CleanResult``
CleanTextFn = Callable[[str], CleanResultLike]
#: ``clean_html(raw_html, *, source_url=None) -> CleanResult``
CleanHtmlFn = Callable[..., CleanResultLike]
#: Loader returning ``(clean_text, clean_html)`` — overridable in tests.
PipelineLoader = Callable[[], tuple[CleanTextFn, CleanHtmlFn]]
#: Sends one encoded ingest frame over a fresh AO connection and returns the
#: decoded INGEST_RESULT payload dict (transport failures come back as an
#: ``ok=False`` dict, never an exception — Fail-Closed shape).
TransportCall = Callable[[bytes], Awaitable[dict[str, Any]]]
#: Returns the shared-DEK FieldCipher, or None when unavailable.
CipherProvider = Callable[[], Any | None]


class CleanerUnavailableError(RuntimeError):
    """Raised when the cleaner pipeline cannot be imported (loud, fail-closed)."""


def _load_real_pipeline() -> tuple[CleanTextFn, CleanHtmlFn]:
    """Lazily import the real cleaner pipeline (sibling Stage-B module)."""
    try:
        from services.cleaner.src import pipeline as _pipeline
    except ImportError as exc:
        raise CleanerUnavailableError(
            "The cleaner pipeline (services.cleaner.src.pipeline) is not "
            "available — ingest cannot run without it (Fail-Closed)."
        ) from exc
    return _pipeline.clean_text, _pipeline.clean_html


# ---------------------------------------------------------------------------
# URL-ingest collaborators (UC-003 Stage C host glue — #655 sub-task 6)
# ---------------------------------------------------------------------------
# URL mode composes three host-side capabilities, each INJECTED so the
# coordinator is fully unit-testable with the transport mocked (the egress door
# is NEVER opened in a test): the one PA-gated fetch door, the guest-parser
# availability signal, and the guest parse round-trip.  The real defaults lazily
# import the launcher + the egress door so this gateway module neither imports
# ``httpx`` (the egress import-scan forbids it everywhere but guarded_fetch) nor
# hard-depends on the launcher at import time.

#: ``purpose`` label handed to the PA adjudicator + the ESCALATE consent context.
_URL_FETCH_PURPOSE: str = "uc003-url-ingest"


class FetchResultLike(Protocol):
    """Structural view of ``shared.security.guarded_fetch.FetchResult``."""

    url: str
    content_text: str
    denied_reason: str | None
    injection_flags: tuple[str, ...]

    @property
    def ok(self) -> bool: ...


class ParseResponseLike(Protocol):
    """Structural view of ``shared.ipc.parse_channel.ParseResponse``."""

    status: str            # 'clean' | 'quarantined' | 'error'
    text: str
    title: str | None
    byline: str | None
    published_date: str | None
    word_count: int
    confidence: float
    reasons: tuple[str, ...]
    error_code: str


#: ``fetch(url, purpose) -> FetchResult`` — the one PA-gated egress door.
UrlFetchFn = Callable[[str, str], FetchResultLike]
#: ``available() -> bool`` — True only when the guest parser is proven READY.
GuestAvailableFn = Callable[[], bool]
#: ``parse(html, source_url) -> ParseResponse | None`` — guest parse round-trip.
GuestParseFn = Callable[[str, str], "ParseResponseLike | None"]


def _default_url_fetch(url: str, purpose: str) -> FetchResultLike:
    """Real wiring: the single Policy-Agent-gated egress door (lazy import).

    Imports ``guarded_fetch`` (the ONE door), never ``httpx`` directly — the
    egress import-scan allows importing the door from anywhere; it forbids
    importing the network client outside the door.
    """
    from shared.security.guarded_fetch import fetch_external

    return fetch_external(url, purpose=purpose)


def _default_guest_parse_available() -> bool:
    """Real wiring: the launcher-parked guest-parser READY signal (lazy)."""
    from launcher.guest_parser import guest_parser_available

    return guest_parser_available()


def _default_guest_parse(html: str, source_url: str) -> "ParseResponseLike | None":
    """Real wiring: parse fetched HTML inside the guest (lazy import)."""
    from launcher.guest_parser import get_guest_parser_manager

    manager = get_guest_parser_manager()
    if manager is None:
        return None
    return manager.parse_html(html, source_url)


# ---------------------------------------------------------------------------
# Display-only image collaborator (UC-003 Workstream B — DORMANT)
# ---------------------------------------------------------------------------
# A content image rides the cleaned text as an inline ``![alt](url)`` ref.  When
# images are enabled (a SEPARATE go-live ceremony — the 4th weld lock
# ``[knowledge].images_enabled`` AND the egress door must both open), the
# coordinator snapshots each ref's bytes ONCE through a BINARY sibling of the one
# PA-gated door (``fetch_external_binary``) and rewrites the ref to the local,
# non-navigable ``blarai-img://`` scheme.  The binary fetch is INJECTED so the
# corridor is unit-testable with a fake (the door is NEVER opened in a test);
# the real default lazily imports the door, never ``httpx``.

#: ``purpose`` label handed to the PA adjudicator for an image fetch.
_IMAGE_FETCH_PURPOSE: str = "uc003-image-ingest"


class BinaryFetchResultLike(Protocol):
    """Structural view of ``shared.security.guarded_fetch.BinaryFetchResult``."""

    url: str
    content_bytes: bytes
    content_type: str
    mime: str
    denied_reason: str | None

    @property
    def ok(self) -> bool: ...


#: ``fetch_binary(url, purpose) -> BinaryFetchResult`` — the one PA-gated door,
#: binary mode (content-type allowlist + magic-byte sniff + SVG-refuse + caps).
ImageFetchFn = Callable[[str, str], BinaryFetchResultLike]


def _default_image_fetch(url: str, purpose: str) -> BinaryFetchResultLike:
    """Real wiring: the single PA-gated egress door in BINARY mode (lazy import).

    Imports ``guarded_fetch`` (the ONE door), never ``httpx`` directly — same
    posture as :func:`_default_url_fetch`.  Returns a denied result for every
    URL while the door is welded (no adjudicator + empty allowlist), so this is
    dormant until the go-live ceremony regardless of ``images_enabled``.
    """
    from shared.security.guarded_fetch import fetch_external_binary

    return fetch_external_binary(url, purpose=purpose)


#: ``consent(context) -> bool`` — the COARSE per-article OFF-SITE image-egress
#: consent gate (CD-1).  Injected for tests; the real default delegates to the
#: global single-verifier registry in ``shared.security.image_egress_consent``.
ImageEgressConsentFn = Callable[[ImageEgressConsentContext], bool]


def _default_image_egress_consent(context: ImageEgressConsentContext) -> bool:
    """Real wiring: the global off-site image-egress consent registry (fail-closed).

    Delegates to ``shared.security.image_egress_consent`` — the WinUI per-article
    yes/no dialog registers a verifier in Pass B; until then NOTHING is registered,
    so this returns False for every article and off-site images are never fetched
    (the dormant, fail-closed default).  Mirrors :func:`_default_image_fetch`'s
    "constructor-injected, default delegates to the global seam" shape.
    """
    return request_image_egress_consent(context).approved


# ---------------------------------------------------------------------------
# Command parsing
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class IngestCommand:
    """A parsed ingest-surface command."""

    verb: str
    """``'ingest'`` | ``'approve'`` | ``'reject'``."""

    arg: str
    """Remainder of the message after the verb (stripped; '' when absent)."""


def parse_ingest_command(text: str) -> IngestCommand | None:
    """Parse ``/ingest`` / ``/approve`` / ``/reject`` from a chat message.

    Case-insensitive on the verb; the verb must be followed by end-of-string
    or whitespace (``/ingestfoo`` is NOT a command and flows to the model
    untouched).  Whitespace (including a newline immediately after the verb —
    the multi-line-paste shape) separates verb from argument.

    Returns None for anything that is not one of the three commands.
    """
    stripped = text.strip()
    lower = stripped.lower()
    for verb in ("ingest", "approve", "reject"):
        cmd = "/" + verb
        if lower == cmd:
            return IngestCommand(verb=verb, arg="")
        if lower.startswith(cmd) and stripped[len(cmd)].isspace():
            return IngestCommand(verb=verb, arg=stripped[len(cmd):].strip())
    return None


def is_bare_url(text: str) -> bool:
    """True when *text* is SOLELY one URL (+/- whitespace) — exact shape only.

    A URL inside a longer sentence does not match (it flows to the model
    untouched); a slash command can never match (it does not start with a
    scheme).  Case-insensitive on the scheme.
    """
    stripped = text.strip()
    if not stripped:
        return False
    return _BARE_URL_RE.fullmatch(stripped) is not None


def _is_unc_path_str(path_str: str) -> bool:
    r"""True when *path_str* is a UNC/network-namespace path (#655 air-gap).

    Every Windows network path begins with two backslashes — the plain
    ``\\host\share`` form AND the extended-length ``\\?\UNC\host\share``
    form (which starts ``\\?\``) — while no plain drive-letter LOCAL path
    does.  The check therefore refuses the entire ``\\`` namespace,
    including ``\\?\C:\…`` extended-length local paths and ``\\.\`` device
    paths: a named fail-closed trade-off — operators give plain local
    paths, and a simple prefix check cannot be confused by namespace
    aliasing tricks.
    """
    return path_str.startswith("\\\\")


def _unc_refusal(path: Path) -> str:
    """The loud air-gap refusal for a UNC/network ingest path."""
    return (
        f"Ingest refused: '{path}' is a UNC/network path. BlarAI's runtime "
        "is air-gapped — it never reads off-host/SMB content (Fail-Closed). "
        "Copy the file to a local path (or userdata/) and re-run /ingest."
    )


def bare_url_nudge(url: str) -> str:
    """The deterministic gateway response to a bare-URL message (#655).

    No model call, no fetch — offer the explicit-command path into the
    knowledge bank, or instruct to phrase a request for anything else.
    """
    return (
        "That message is a bare link — BlarAI never fetches a URL on its own, "
        "and no model call was made.\n\n"
        f"To capture this page into the knowledge bank, reply:\n\n"
        f"`/ingest {url}`\n\n"
        "(That fetches it through the guarded egress door and parses it in the "
        "VM, then shows you a preview to approve before anything is stored — "
        "when the guest parser is running; otherwise it refuses and points to "
        "pasting the text.) For anything else, phrase a request around the link."
    )


# ---------------------------------------------------------------------------
# Pending-slot state
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PendingIngest:
    """The session's single outstanding pending ingest (v1 one-slot model)."""

    doc_uuid: str
    source_type: str
    source_ref: str
    title: str
    word_count: int
    submitted_at: str
    """ISO-8601 UTC timestamp of the submit."""

    # Editable-preview state (#663 Workstream A).  The cleaned ARTICLE BODY
    # (``clean.text``) and the cleaner-output digest are retained so the
    # operator can edit-before-approve: the body seeds the WinUI edit box, and
    # ``content_sha256`` is the prior-content provenance signal an edited
    # re-submit feeds the AO audit chain.  byline/published_date/cleaner_version
    # are preserved so an edit (re-cleaned via the metadata-light paste path)
    # does not lose the original article metadata.  Defaulted so existing
    # 6-field constructions (older tests) keep working.
    cleaned_text: str = ""
    content_sha256: str = ""
    byline: str = ""
    published_date: str = ""
    cleaner_version: str = ""

    @property
    def label(self) -> str:
        """Human label for refusal/decision messages: title when present.

        For an untitled PASTE the source_ref is ``paste:<content-sha256>`` —
        a content-derived digest that must never reach the messages this
        label is rendered into, because decision/refusal replies persist into
        sessions.db and a content digest there would re-seed the
        content-fingerprint membership oracle (#655 LA verdict 2026-06-10).
        The doc_uuid prefix is the opaque, content-independent handle instead.
        """
        if self.title:
            return self.title
        if self.source_type == "paste":
            return f"pasted article (doc {self.doc_uuid[:8]})"
        return self.source_ref


# ---------------------------------------------------------------------------
# Coordinator
# ---------------------------------------------------------------------------


class IngestCoordinator:
    """Drives the /ingest → preview → /approve | /reject flow for the gateway.

    All collaborators are injected so the coordinator is fully unit-testable
    with no cleaner package, no AO, and no real DEK:

    Args:
        transport_call: Async callable sending one encoded ingest frame over a
            fresh AO connection, returning the decoded INGEST_RESULT payload.
        cipher_provider: Returns the shared-DEK ``FieldCipher`` (the session
            store's — ADR-025 §2.1 one-DEK rule) or None when unavailable.
        pipeline_loader: Returns ``(clean_text, clean_html)``.  Defaults to
            the lazy real import; tests inject fakes or a raising loader.
        staging_dir_provider: Returns the staging directory.  Defaults to the
            canonical ``%LOCALAPPDATA%\\BlarAI\\ingest_staging``.
        max_ingest_bytes: Ingest byte cap (``[knowledge].staging_max_bytes``
            default — NOT the 16 KB grounding cap).
        userdata_dir: FILE-mode root for bare filenames.  Defaults to the
            document_loader's ``USERDATA_DIR``.
    """

    def __init__(
        self,
        *,
        transport_call: TransportCall,
        cipher_provider: CipherProvider,
        pipeline_loader: PipelineLoader | None = None,
        staging_dir_provider: Callable[[], Path] | None = None,
        max_ingest_bytes: int = DEFAULT_INGEST_MAX_BYTES,
        userdata_dir: Path | None = None,
        url_fetch_fn: UrlFetchFn | None = None,
        guest_parse_available_fn: GuestAvailableFn | None = None,
        guest_parse_fn: GuestParseFn | None = None,
        images_enabled: bool = False,
        image_fetch_fn: ImageFetchFn | None = None,
        image_consent_fn: ImageEgressConsentFn | None = None,
    ) -> None:
        self._transport_call = transport_call
        self._cipher_provider = cipher_provider
        self._pipeline_loader: PipelineLoader = pipeline_loader or _load_real_pipeline
        self._staging_dir_provider = staging_dir_provider or default_staging_dir
        self._max_ingest_bytes = max_ingest_bytes
        # Effective PLAINTEXT cap (#655 byte-cap seam): ``max_ingest_bytes``
        # caps the staged CIPHERTEXT (the AO re-enforces it at read time, and
        # the Stage-A read cap does not move); AES-256-GCM staging adds
        # exactly CIPHER_ENVELOPE_OVERHEAD_BYTES (version + nonce + tag), so
        # plaintext is checked against the cap minus the envelope — otherwise
        # plaintext in the last envelope-sized band passes here and bounces
        # at the AO with a confusing same-number cap error.
        self._max_plaintext_bytes = max_ingest_bytes - CIPHER_ENVELOPE_OVERHEAD_BYTES
        self._userdata_dir = userdata_dir
        # URL-mode collaborators (UC-003 Stage C host glue): the one PA-gated
        # fetch door, the guest-parser READY signal, and the guest parse
        # round-trip — injected for tests; real defaults lazily wire the
        # launcher + the egress door (see the module's URL-collaborator section).
        self._url_fetch_fn: UrlFetchFn = url_fetch_fn or _default_url_fetch
        self._guest_parse_available_fn: GuestAvailableFn = (
            guest_parse_available_fn or _default_guest_parse_available
        )
        self._guest_parse_fn: GuestParseFn = guest_parse_fn or _default_guest_parse
        # Display-only images (UC-003 Workstream B) — the 4th weld lock.  DORMANT
        # by default: with images_enabled=False the corridor strips every remote
        # ref to a placeholder and never fetches; flipping it true is HALF the
        # go-live ceremony (the egress door weld is the other half).  The binary
        # door is injected so tests drive the corridor without opening egress.
        self._images_enabled = bool(images_enabled)
        self._image_fetch_fn: ImageFetchFn = image_fetch_fn or _default_image_fetch
        # Coarse per-article OFF-SITE image-egress consent (CD-1).  Injected for
        # tests; the real default delegates to the global consent registry, which
        # fails closed (denies every off-site fetch) until the Pass-B WinUI dialog
        # wires a verifier — so building this gate changes nothing at rest.
        self._image_consent_fn: ImageEgressConsentFn = (
            image_consent_fn or _default_image_egress_consent
        )
        self._framer = MessageFramer()
        # ONE outstanding pending ingest per session (v1) — see module docstring.
        # TtlDict (#801): a preview the operator never decides would otherwise
        # hold the cleaned text until restart; reap_expired (called from the
        # gateway's turn-start sweep) REJECTS + drops entries past the TTL.
        self._pending: TtlDict[PendingIngest] = TtlDict()

    # ── Public state inspection (tests / future /pending command) ────────

    def pending_for(self, session_id: str) -> PendingIngest | None:
        """The session's pending ingest, or None."""
        return self._pending.get(session_id)

    def preview_meta_for(self, session_id: str) -> dict[str, str] | None:
        """The pending preview's editable body + handle, for the WinUI edit
        surface (#663 Workstream A).

        Returns ``{doc_uuid, source_type, editable_body}`` when an ingest is
        pending — ``editable_body`` is the cleaned ARTICLE BODY (``clean.text``),
        the exact source the operator edits — else None.  The gateway hands this
        to the WinUI on the preview turn so the Edit box is seeded with the real
        source rather than a fragile parse of the ``---``-fenced preview blob.
        """
        pending = self._pending.get(session_id)
        if pending is None:
            return None
        return {
            "doc_uuid": pending.doc_uuid,
            "source_type": pending.source_type,
            "editable_body": pending.cleaned_text,
        }

    # ── Idle backstop (#801) ──────────────────────────────────────────────

    async def reap_expired(self, ttl_s: float) -> list[str]:
        """Drop pending ingests idle past *ttl_s* (the #801 idle backstop).

        Each expired slot is REJECTED through the SAME AO decision path the
        operator's ``/reject`` uses, so the AO's pending row and the encrypted
        staging blob clean up too (the AO deletes the blob at decision time).
        Best-effort and fail-soft: a transport failure (AO down) still drops
        the RAM entry — the memory bound is this backstop's contract; the AO
        row is DB-backed, visible via ``list_pending``, and a later /ingest
        of the same source is unaffected (fresh doc_uuid). ``ttl_s <= 0``
        disables the sweep.

        Returns:
            The session ids whose pending slots were reaped.
        """
        reaped: list[str] = []
        for session_id in self._pending.expired_keys(ttl_s):
            pending = self._pending.get(session_id)
            if pending is None:  # pragma: no cover — raced by a decision
                continue
            try:
                await self._dispatch_decision(pending, "reject")
            except Exception as exc:  # noqa: BLE001 — reap must not raise
                logger.error(
                    "Ingest reaper: best-effort reject failed for doc %s "
                    "(RAM entry dropped anyway): %s",
                    pending.doc_uuid,
                    exc,
                )
            self._pending.pop(session_id, None)
            reaped.append(session_id)
            # Eviction events are LOGGED (LA condition, #801 c.1666) —
            # labels/ids only, never the cleaned content.
            logger.info(
                "Ingest reaper: expired pending ingest %s (doc %s) for "
                "session %s rejected + dropped (ttl=%.0fs).",
                pending.label,
                pending.doc_uuid,
                session_id,
                ttl_s,
            )
        return reaped

    # ── Entry point ───────────────────────────────────────────────────────

    async def handle_command(self, session_id: str, command: IngestCommand) -> str:
        """Execute one parsed command and return the informational reply text.

        Never raises for operator-shaped failures — every refusal and every
        AO error comes back as a clear message for the transcript
        (Fail-Closed: anything unexpected is also caught and surfaced as an
        error message rather than crashing the turn).
        """
        try:
            if command.verb == "ingest":
                return await self._handle_ingest(session_id, command.arg)
            if command.arg:
                # One pending slot per session — there is nothing for an
                # argument to disambiguate, so an argument is an operator
                # error, refused deterministically rather than ignored.
                return (
                    f"/{command.verb} takes no argument — only one ingest can "
                    f"be pending per chat. Reply /{command.verb} on its own."
                )
            return await self._handle_decision(session_id, command.verb)
        except CleanerUnavailableError as exc:
            return f"Ingest failed — cleaner unavailable. {exc}"
        except StagingError as exc:
            return f"Ingest failed — encrypted staging error (Fail-Closed). {exc}"
        except Exception as exc:  # noqa: BLE001 — surface, never crash the turn
            logger.error(
                "Ingest command %r failed for session=%s: %s",
                command.verb, session_id, exc, exc_info=True,
            )
            return f"Ingest command failed (Fail-Closed): {exc}"

    # ── /ingest ───────────────────────────────────────────────────────────

    async def _handle_ingest(self, session_id: str, arg: str) -> str:
        if not arg:
            return _USAGE_MESSAGE

        pending = self._pending.get(session_id)
        if pending is not None:
            return (
                "An ingest is already pending in this chat: "
                f"“{pending.label}” (doc {pending.doc_uuid[:8]}…). "
                "Reply /approve or /reject before starting another — only one "
                "ingest can be pending at a time."
            )

        # ── URL mode: fetch (one PA-gated door) → guest parse → compose ────
        if arg.lower().startswith(("http://", "https://")):
            return await self._handle_url_ingest(session_id, arg)

        # ── Acquire raw content (FILE or PASTE) ───────────────────────────
        acquired = await self._acquire_content(arg)
        if isinstance(acquired, str):
            return acquired  # a loud refusal message
        raw_text, source_type, source_ref, suffix = acquired

        # ── Clean (injected pipeline; both verdicts proceed) ──────────────
        clean_text_fn, clean_html_fn = self._pipeline_loader()
        try:
            if suffix in INGEST_HTML_EXTENSIONS:
                clean = await asyncio.to_thread(clean_html_fn, raw_text)
            else:
                clean = await asyncio.to_thread(clean_text_fn, raw_text)
        except CleanerUnavailableError:
            raise
        except Exception as exc:  # noqa: BLE001 — pipeline bug → loud refusal
            logger.error("Cleaner pipeline failed: %s", exc, exc_info=True)
            return f"Ingest failed — the cleaner pipeline raised an error: {exc}"

        return await self._finalize_clean(
            session_id, clean, source_type=source_type, source_ref=source_ref
        )

    # ── /ingest <url> ─────────────────────────────────────────────────────

    async def _handle_url_ingest(self, session_id: str, url: str) -> str:
        """Fetch a URL through the one egress door, parse it in the guest, and
        stage the cleaned text for approval (UC-003 Stage C host glue, #655).

        The fetch crosses the SINGLE Policy-Agent-gated door
        (``shared.security.guarded_fetch``); the hostile HTML is parsed INSIDE
        the NIC-less guest (only clean text returns over vsock — ADR-030 §3),
        and the host composes the injection axis before the preview.  Every
        failure is a loud refusal — nothing is parsed host-side, ever, and
        nothing is stored until the operator approves the preview.
        """
        # 1. Capability gate — the guest parser must be proven READY.  With no
        #    guest parser, refuse (NEVER host-side parsing of hostile HTML).
        if not self._guest_parse_available_fn():
            return (
                "URL ingest is unavailable: the guest parser that isolates "
                "hostile page parsing inside the VM is not running, so BlarAI "
                "will not fetch or parse this link (Fail-Closed — there is no "
                "host-side parse fallback).\n\n"
                "Interim path: open the article yourself, copy the text, and "
                "run `/ingest <pasted text>`."
            )

        # 2. Fetch through the ONE PA-gated egress door (URL = authorization).
        try:
            fetch = await asyncio.to_thread(
                self._url_fetch_fn, url, _URL_FETCH_PURPOSE
            )
        except Exception as exc:  # noqa: BLE001 — door must never crash the turn
            logger.error("URL ingest fetch raised: %s", exc, exc_info=True)
            return (
                "URL ingest failed: the egress door raised an error "
                "(Fail-Closed). Nothing was fetched."
            )
        if not getattr(fetch, "ok", False):
            reason = getattr(fetch, "denied_reason", None) or "the fetch was refused"
            return (
                f"URL ingest refused: {reason}. Nothing was fetched into the "
                "knowledge bank."
            )

        raw_html = getattr(fetch, "content_text", "") or ""
        if not raw_html.strip():
            return (
                "URL ingest refused: the fetched page was empty (nothing to "
                "parse). Nothing was stored."
            )

        # 3. Hard size guard for the guest parse channel (raw-body cap).
        raw_bytes = len(raw_html.encode("utf-8"))
        if raw_bytes > PARSE_BODY_MAX_BYTES:
            return (
                f"URL ingest refused: the fetched page is {raw_bytes:,} bytes, "
                f"over the {PARSE_BODY_MAX_BYTES:,}-byte guest parse-channel "
                "cap. Save the article text and use `/ingest <pasted text>` "
                "instead (a v1 limit — large-page chunked parsing is a named "
                "follow-up)."
            )

        # 4. Parse INSIDE the guest — only clean text returns over vsock.
        try:
            parsed = await asyncio.to_thread(self._guest_parse_fn, raw_html, url)
        except Exception as exc:  # noqa: BLE001 — fail-closed
            logger.error("URL ingest guest parse raised: %s", exc, exc_info=True)
            return (
                "URL ingest failed: the guest parser raised an error "
                "(Fail-Closed). Nothing was stored."
            )
        if parsed is None:
            return (
                "URL ingest refused: the guest parser returned no result "
                "(unreachable, or the page was rejected by the parse channel). "
                "Nothing was stored (Fail-Closed)."
            )
        if getattr(parsed, "status", "") == "error":
            code = getattr(parsed, "error_code", "") or "PARSE_ERROR"
            return (
                "URL ingest refused: the guest parser reported an error "
                f"[{code}]. Nothing was stored (Fail-Closed)."
            )

        # 5. Compose the host-side verdict (ADR-030 §5 injection axis), folding
        #    the fetch door's injection scan into the count (defense in depth).
        clean = self._compose_url_clean(parsed, raw_len=len(raw_html), fetch=fetch)

        # 6. Stage + submit + preview — the shared tail (source_type='url').
        return await self._finalize_clean(
            session_id, clean, source_type="url", source_ref=url
        )

    def _compose_url_clean(
        self,
        parsed: "ParseResponseLike",
        *,
        raw_len: int,
        fetch: "FetchResultLike",
    ) -> CleanResultLike:
        """Compose a CleanResult from a guest ParseResponse (lazy cleaner import).

        The injection axis is the host's share of the work (ADR-030 §5); the
        upstream ``guarded_fetch`` Layer-2 scan over the raw body is folded in
        as extra injection findings (defense in depth, fail-closed-strict).
        """
        from services.cleaner.src.pipeline import clean_from_guest_parse

        extra = len(getattr(fetch, "injection_flags", ()) or ())
        return clean_from_guest_parse(
            parsed, raw_len=raw_len, extra_injection_findings=extra
        )

    # ── shared stage + submit + preview tail ──────────────────────────────

    async def _finalize_clean(
        self,
        session_id: str,
        clean: CleanResultLike,
        *,
        source_type: str,
        source_ref: str,
    ) -> str:
        """Stage (encrypted) + INGEST_SUBMIT + preview a cleaned document.

        The shared tail of every ingest mode (PASTE, FILE, URL): the verdict is
        already computed (``clean``); here it is checked for emptiness + size,
        hashed, staged under the shared DEK, submitted to the AO, and rendered
        as the single pending preview.  Both clean and quarantined verdicts
        proceed — the L0 pending state IS the quarantine and ``/approve`` is the
        override (ADR-030 §6).
        """
        title = clean.title or ""
        outcome = await self._stage_and_submit(
            cleaned_text=clean.text,
            source_type=source_type,
            source_ref=source_ref,
            title=title,
            byline=clean.byline or "",
            published_date=clean.published_date or "",
            word_count=int(clean.word_count),
            cleaner_version=clean.cleaner_version,
            recompute_paste_source_ref=True,
        )
        if isinstance(outcome, str):
            return outcome  # a loud refusal (empty / oversize / no-cipher / submit-fail)
        result, doc_uuid, content_sha256, source_ref, stored_text = outcome

        state = str(result.get("state", "error"))
        if state == "already_ingested":
            prior_uuid = str(result.get("doc_uuid", ""))
            return (
                "This source is already in the knowledge bank (approved "
                f"earlier as doc {prior_uuid[:8]}…). Nothing was submitted."
            )

        # state == 'pending' — record the slot (with the editable body + the
        # metadata an edit-then-approve needs) and render the preview.  The
        # editable body is the STORED text (image refs already rewritten to
        # blarai-img:// / placeholders) so the operator edits exactly what is
        # stored, and a deleted blarai-img:// line drops that image on approve.
        self._pending[session_id] = PendingIngest(
            doc_uuid=doc_uuid,
            source_type=source_type,
            source_ref=source_ref,
            title=title,
            word_count=int(clean.word_count),
            submitted_at=datetime.now(timezone.utc).isoformat(),
            cleaned_text=stored_text,
            content_sha256=content_sha256,
            byline=clean.byline or "",
            published_date=clean.published_date or "",
            cleaner_version=clean.cleaner_version,
        )
        return self._build_preview(
            clean, source_type=source_type, source_ref=source_ref, body=stored_text
        )

    async def _stage_and_submit(
        self,
        *,
        cleaned_text: str,
        source_type: str,
        source_ref: str,
        title: str,
        byline: str,
        published_date: str,
        word_count: int,
        cleaner_version: str,
        prior_content_sha256: str = "",
        recompute_paste_source_ref: bool = False,
    ) -> tuple[dict[str, Any], str, str, str, str] | str:
        """Empty/size check → image corridor → hash → encrypted-stage → INGEST_SUBMIT.

        The shared submit tail for the initial ``/ingest`` AND the
        edit-then-approve re-submit (#663).  Returns
        ``(result, doc_uuid, content_sha256, source_ref, stored_text)`` for a
        submitted document (``result`` is the AO INGEST_RESULT dict — its
        ``state`` is ``pending`` or ``already_ingested``), or a loud refusal
        string (empty / oversize / no-cipher / submit-failure; the orphaned
        text AND image staging files are cleaned up on a submit failure).

        ``stored_text`` is the body actually staged + submitted: for the
        display-only image corridor (UC-003 Workstream B) the inline
        ``![alt](url)`` refs are rewritten to local ``blarai-img://`` refs (or
        dropped to placeholders), so the hash, the preview, and the editable
        body all reflect what is stored — never the pre-rewrite text.

        ``recompute_paste_source_ref`` finalises a PASTE ``source_ref`` from the
        cleaned-content hash (the initial-ingest dedup identity).  The edit path
        leaves it False and passes the ORIGINAL pending ``source_ref`` through
        unchanged, so an edited paste dedup-REPLACES its pending row instead of
        minting a second (orphaned) one — the paste correctness trap (#663).
        ``prior_content_sha256`` is the operator-edit provenance signal forwarded
        to the AO audit chain (empty for an un-edited submit).
        """
        if not cleaned_text.strip():
            return (
                "Ingest refused: the cleaner produced no text (nothing left "
                "after cleaning) — there is nothing to store (Fail-Closed)."
            )

        # ── Encrypted staging cipher (shared DEK; no plaintext fallback) ──
        # Resolved BEFORE the image corridor — image bytes are staged under the
        # same cipher, so a missing cipher must refuse before any fetch/stage.
        cipher = self._cipher_provider()
        if cipher is None:
            return (
                "Ingest refused: the encrypted staging cipher is unavailable "
                "(no shared-DEK session store in this process) — content is "
                "never staged in plaintext (Fail-Closed)."
            )
        doc_uuid = str(_uuid_mod.uuid4())
        staging_dir = self._staging_dir_provider()

        # ── Display-only image corridor (UC-003 Workstream B — DORMANT) ───
        # Snapshot inline content-image bytes ONCE and rewrite the refs to the
        # local blarai-img:// scheme BEFORE hashing/staging, so the hash, the
        # preview, and the editable body all reflect the stored text.  Gated by
        # images_enabled + the egress door weld — a no-op (refs stripped to
        # placeholders, no fetch) in the shipped dormant posture.
        stored_text, images_meta = await self._process_images(
            cleaned_text,
            doc_uuid=doc_uuid,
            cipher=cipher,
            staging_dir=staging_dir,
            source_type=source_type,
            source_ref=source_ref,
        )

        stored_bytes = len(stored_text.encode("utf-8"))
        if stored_bytes > self._max_plaintext_bytes:
            # Drop any image staging written above — the doc is refused.
            self._cleanup_image_staging(images_meta, doc_uuid, staging_dir)
            return (
                f"Ingest refused: cleaned content is {stored_bytes:,} bytes, "
                f"exceeding the {self._max_plaintext_bytes:,}-byte effective "
                f"plaintext cap (the {self._max_ingest_bytes:,}-byte staging "
                f"cap minus the {CIPHER_ENVELOPE_OVERHEAD_BYTES}-byte "
                "encryption envelope; Fail-Closed refuse)."
            )

        content_sha256 = hashlib.sha256(stored_text.encode("utf-8")).hexdigest()
        if recompute_paste_source_ref and source_type == "paste":
            # Deterministic dedup identity for pastes: the STORED-content hash
            # (post image rewrite).  Identical paste → re-submit replaces the
            # prior row per the dedup contract; a different paste is a different
            # document.
            source_ref = f"paste:{content_sha256}"

        staging_path = await asyncio.to_thread(
            write_staged, stored_text, doc_uuid, cipher, staging_dir
        )

        # ── INGEST_SUBMIT over the existing gateway transport ─────────────
        # ``images`` carries METADATA ONLY (ids + staging paths + alt/mime) —
        # the bytes ride per-image encrypted staging blobs, never the 64 KB
        # frame.  Empty in the dormant posture (no image was fetched).
        message = self._framer.encode_ingest_submit(
            doc_uuid=doc_uuid,
            source_type=source_type,
            source_ref=source_ref,
            staging_path=str(staging_path),
            content_sha256=content_sha256,
            title=title,
            byline=byline,
            published_date=published_date,
            word_count=int(word_count),
            cleaner_version=cleaner_version,
            prior_content_sha256=prior_content_sha256,
            request_id=str(_uuid_mod.uuid4()),
            images=tuple(images_meta),
        )
        result = await self._transport_call(message)

        if not result.get("ok", False):
            # The pending row never landed — remove the orphaned text AND image
            # staging files (fail-safe; on success the AO deletes them after the
            # row persists).
            delete_staged(doc_uuid, staging_dir)
            self._cleanup_image_staging(images_meta, doc_uuid, staging_dir)
            return self._format_ao_error("Ingest submit failed", result)

        return result, doc_uuid, content_sha256, source_ref, stored_text

    async def _process_images(
        self,
        cleaned_text: str,
        *,
        doc_uuid: str,
        cipher: Any,
        staging_dir: Path,
        source_type: str,
        source_ref: str,
    ) -> tuple[str, list[dict[str, str]]]:
        """Snapshot inline content-image bytes ONCE; rewrite refs to blarai-img://.

        Walks the absolute-``http(s)`` ``![alt](url)`` refs in *cleaned_text*
        (display-only images, UC-003 Workstream B) and returns
        ``(stored_text, image_metadata)``.  ``source_type`` / ``source_ref``
        carry the ingest mode + the article's source URL — needed for the CD-1
        consent grain below.

        The gates, in order (every drop goes to an alt-only ``[image: alt]``
        placeholder so NO remote URL is ever stored):

        * No ``http(s)`` refs (an edited body already carrying ``blarai-img://``
          refs, or text with no images) → text returned UNCHANGED.  Load-bearing:
          ``rewrite_image_refs`` would otherwise collapse surviving
          ``blarai-img://`` refs to placeholders.
        * ``images_enabled`` FALSE (the shipped 4th-lock default) → strip every
          remote ref, fetch NOTHING.  This check is FIRST after the refs gate and
          short-circuits ALL fetch/consent logic — the dormancy invariant: even
          with a consent verifier registered and off-site refs present, the weld
          lock wins upstream of consent (no path around the weld).
        * CD-1 (LA-locked 2026-06-15) — only a **URL-ingested** article fetches
          remote images; PASTE/FILE content must never silently become a network
          egress.  A non-URL ingest, or a URL whose own host can't be parsed
          (fail-closed detection), fetches NOTHING.
        * CD-1 consent grain — SAME-SITE refs (host == the article host) ride the
          existing ``/ingest`` consent.  OFF-SITE refs (a third-party host) need
          ONE coarse per-article yes/no (:meth:`_image_consent_fn`); fail-closed:
          no verifier / deny / timeout / error → off-site images drop, never
          fetched (never a per-host vetting chore — ADR-032 / #663 c.1088).
        * Per image: the binary door (count- + byte-capped) → truncated drop
          (W2/BED-4) → header-only dimension gate (W1 ceiling + W3 unreadable-drop
          + min floor, :func:`image_dimensions_ok`) → per-image encrypted staging
          → ``blarai-img://<image_id>`` rewrite.

        Fail-safe: an individual image error drops that image, never the doc.
        Metadata records are the pinned ``{image_id, staging_path, alt,
        source_url, mime}`` shape the AO reads on INGEST_SUBMIT.
        """
        from services.cleaner.src.image_refs import (
            extract_image_refs,
            rewrite_image_refs,
        )

        refs = extract_image_refs(cleaned_text)
        if not refs:
            # No http(s) image refs — leave the text exactly as-is so any
            # already-local blarai-img:// refs (the edit path) survive verbatim.
            return cleaned_text, []

        if not self._images_enabled:
            # 4th weld lock closed (shipped default): never fetch; strip every
            # remote ref to a placeholder so no remote URL is ever stored.  FIRST
            # after the refs gate, ahead of any host classification or consent —
            # the dormancy invariant (a registered verifier cannot route around
            # the weld).
            return rewrite_image_refs(cleaned_text, {}), []

        # CD-1: only URL-ingested articles fetch remote images.  A paste/file
        # ingest (no source host), or a URL whose host can't be determined
        # (fail-closed detection), strips every ref and fetches nothing — offline
        # content must never silently become a network egress.
        article_host = host_from_url(source_ref) if source_type == "url" else None
        if article_host is None:
            return rewrite_image_refs(cleaned_text, {}), []

        # Classify refs into same-site (ride the existing /ingest consent) and
        # off-site (need the coarse per-article consent).  ``extract_image_refs``
        # only yields ABSOLUTE http(s) refs — a relative / protocol-relative /
        # ``data:`` ref is filtered out upstream and never reaches here (the
        # documented relative-URL limit, c.1088), so every ref host below is a
        # real off-box host.
        offsite_hosts = sorted(
            {
                host
                for ref in refs
                if (host := host_from_url(ref.url)) is not None
                and not same_site(article_host, host)
            }
        )
        # ONE coarse per-article off-site consent (never a per-host chore).
        # Skipped when the article has no off-site refs.  Fail-closed: any
        # non-approval → off-site images drop to placeholders.
        offsite_allowed = False
        if offsite_hosts:
            context = ImageEgressConsentContext(
                article_host=article_host,
                offsite_hosts=tuple(offsite_hosts),
                doc_label=doc_uuid[:8],
            )
            try:
                offsite_allowed = bool(self._image_consent_fn(context))
            except Exception as exc:  # noqa: BLE001 — a consent error fails closed
                logger.warning(
                    "Off-site image consent raised (off-site images dropped): %s",
                    exc,
                )
                offsite_allowed = False
            if not offsite_allowed:
                logger.info(
                    "Off-site image egress not consented — %d off-site host(s) "
                    "dropped to placeholders for doc %s",
                    len(offsite_hosts), doc_uuid[:8],
                )

        from shared.security.guarded_fetch import (
            MAX_IMAGES_PER_ARTICLE,
            MAX_TOTAL_IMAGE_BYTES,
            image_dimensions_ok,
        )

        mapping: dict[str, str] = {}
        metadata: list[dict[str, str]] = []
        total_bytes = 0
        for ref in refs[:MAX_IMAGES_PER_ARTICLE]:
            if ref.url in mapping:
                continue  # same URL twice → one fetch, reuse the id
            ref_host = host_from_url(ref.url)
            if ref_host is None:
                continue  # unclassifiable host → drop (fail-closed; never fetched)
            if not same_site(article_host, ref_host) and not offsite_allowed:
                # Off-site host without per-article consent — NEVER fetched; the
                # ref drops to a placeholder (no third-party host is reached).
                continue
            try:
                fetch = await asyncio.to_thread(
                    self._image_fetch_fn, ref.url, _IMAGE_FETCH_PURPOSE
                )
            except Exception as exc:  # noqa: BLE001 — a door error drops the image
                logger.warning("Image fetch raised (image dropped): %s", exc)
                continue
            if not getattr(fetch, "ok", False):
                continue  # denied / wrong content-type / SSRF — drop to placeholder
            if getattr(fetch, "truncated", False):
                # W2 / BED-4: the body hit the per-image byte cap — these are
                # INCOMPLETE bytes.  A half-image is a smell and a renderer
                # hazard; drop it rather than store a truncated image.
                logger.warning(
                    "Image exceeded the per-image byte cap (truncated) — dropped "
                    "to placeholder"
                )
                continue
            image_bytes = getattr(fetch, "content_bytes", b"") or b""
            if not image_bytes:
                continue
            # Header-only dimension gate (no decode): drops an UNREADABLE header
            # (W3/TD-4 — cannot prove under the bomb ceiling), a spacer/tracking
            # pixel below the min floor, OR a decompression bomb above the max
            # edge/area ceiling (W1/BED-3).  Drops to the alt placeholder (the url
            # never enters `mapping`).
            if not image_dimensions_ok(getattr(fetch, "mime", "") or "", image_bytes):
                logger.info(
                    "Image dimensions outside the accepted band (unreadable / "
                    "below floor / above bomb ceiling) — dropped to placeholder"
                )
                continue
            if total_bytes + len(image_bytes) > MAX_TOTAL_IMAGE_BYTES:
                logger.warning(
                    "Image total-byte cap (%d) reached — remaining images dropped",
                    MAX_TOTAL_IMAGE_BYTES,
                )
                break
            image_id = _uuid_mod.uuid4().hex
            try:
                await asyncio.to_thread(
                    write_staged_image,
                    image_bytes, image_id, doc_uuid, cipher, staging_dir,
                )
            except Exception as exc:  # noqa: BLE001 — staging failure drops the image
                logger.warning("Image staging failed (image dropped): %s", exc)
                continue
            total_bytes += len(image_bytes)
            mapping[ref.url] = image_id
            metadata.append(
                {
                    "image_id": image_id,
                    "staging_path": str(
                        staging_dir / f"{doc_uuid}__{image_id}.bin"
                    ),
                    "alt": ref.alt,
                    "source_url": ref.url,
                    "mime": getattr(fetch, "mime", "") or "",
                }
            )
        return rewrite_image_refs(cleaned_text, mapping), metadata

    @staticmethod
    def _cleanup_image_staging(
        images_meta: list[dict[str, str]], doc_uuid: str, staging_dir: Path
    ) -> None:
        """Best-effort removal of per-image staging blobs (fail-safe, never raises)."""
        for meta in images_meta:
            delete_staged_image(meta.get("image_id", ""), doc_uuid, staging_dir)

    async def _acquire_content(
        self, arg: str
    ) -> tuple[str, str, str, str] | str:
        """Resolve the /ingest argument to raw content (FILE or PASTE mode).

        Returns ``(raw_text, source_type, source_ref, suffix)`` on success or
        a loud refusal message string.  See the module docstring for the
        deterministic classification order.
        """
        # 2. Absolute path the operator gave → FILE mode, guards loud.
        try:
            arg_path = Path(arg)
            is_absolute = arg_path.is_absolute()
        except (OSError, ValueError):
            is_absolute = False
        if is_absolute:
            return await self._read_ingest_file(arg_path, containment_root=None)

        # 3. Single filename-shaped token → FILE mode under userdata/.
        if not any(ch.isspace() for ch in arg):
            suffix = Path(arg).suffix.lower()
            if suffix in INGEST_FILE_EXTENSIONS:
                userdata = self._resolve_userdata_dir()
                return await self._read_ingest_file(
                    userdata / arg, containment_root=userdata
                )

        # 4. PASTE mode — the remainder of the message IS the article text.
        # (source_ref is finalised by the caller from the cleaned-content hash.)
        return arg, "paste", "paste:", ""

    def _resolve_userdata_dir(self) -> Path:
        if self._userdata_dir is not None:
            return self._userdata_dir
        from services.ui_gateway.src.document_loader import USERDATA_DIR

        return USERDATA_DIR

    async def _read_ingest_file(
        self, candidate: Path, *, containment_root: Path | None
    ) -> tuple[str, str, str, str] | str:
        """FILE-mode read with document_loader-pattern guards, ingest-sized.

        Guard order: UNC/network rejection (raw form, BEFORE any filesystem
        touch) → extension → resolve → UNC/network rejection (resolved form —
        a local symlink/junction must not smuggle in a share) → containment →
        existence → size → strict UTF-8 read.  The size cap is the effective
        plaintext ingest cap, not the 16 KB grounding cap.  Every failure is
        a loud refusal string — FILE mode never falls through to paste.
        """
        # ── Air-gap guard (#655): refuse UNC/network paths outright ───────
        # Checked on the RAW string BEFORE resolve()/stat() so an off-host
        # SMB path never triggers network I/O from this process.
        if _is_unc_path_str(str(candidate)):
            return _unc_refusal(candidate)

        suffix = candidate.suffix.lower()
        if suffix not in INGEST_FILE_EXTENSIONS:
            allowed = ", ".join(sorted(INGEST_FILE_EXTENSIONS))
            return (
                f"Ingest refused: unsupported file type '{suffix or '(none)'}' "
                f"for '{candidate.name}'. /ingest accepts {allowed} files in v1 "
                "(.pdf is a named deferral — the cleaner has no PDF path yet)."
            )

        try:
            resolved = candidate.resolve()
        except (OSError, ValueError) as exc:
            return f"Ingest refused: cannot resolve path '{candidate}': {exc}"

        # Re-check the RESOLVED form: a local symlink/junction pointing at a
        # network share must not bypass the air-gap guard.
        if _is_unc_path_str(str(resolved)):
            return _unc_refusal(resolved)

        if containment_root is not None:
            try:
                resolved.relative_to(containment_root.resolve())
            except ValueError:
                return (
                    f"Ingest refused: '{candidate.name}' resolves outside "
                    "userdata/ (path containment, Fail-Closed)."
                )

        if not resolved.exists() or not resolved.is_file():
            return (
                f"Ingest refused: file not found: '{resolved}'. Place the file "
                "in userdata/ (or give an absolute path) and try again."
            )

        size = resolved.stat().st_size
        if size > self._max_plaintext_bytes:
            return (
                f"Ingest refused: '{resolved.name}' is {size:,} bytes, "
                f"exceeding the {self._max_plaintext_bytes:,}-byte effective "
                f"plaintext cap (the {self._max_ingest_bytes:,}-byte staging "
                f"cap minus the {CIPHER_ENVELOPE_OVERHEAD_BYTES}-byte "
                "encryption envelope; Fail-Closed refuse)."
            )

        try:
            raw_text = await asyncio.to_thread(
                resolved.read_text, encoding="utf-8", errors="strict"
            )
        except UnicodeDecodeError as exc:
            return f"Ingest refused: cannot read '{resolved.name}' as UTF-8 text: {exc}"
        except OSError as exc:
            return f"Ingest refused: cannot read '{resolved.name}': {exc}"

        return raw_text, "file", str(resolved), suffix

    # ── /approve, /reject ─────────────────────────────────────────────────

    async def _handle_decision(self, session_id: str, verb: str) -> str:
        pending = self._pending.get(session_id)
        if pending is None:
            return (
                f"Nothing to {verb}: no ingest is pending in this chat. "
                "Use /ingest first."
            )
        _ok, message, clear_slot = await self._dispatch_decision(pending, verb)
        if clear_slot:
            self._pending.pop(session_id, None)
        return message

    async def _dispatch_decision(
        self, pending: PendingIngest, verb: str
    ) -> tuple[bool, str, bool]:
        """Send one INGEST_DECISION for *pending* and interpret the AO result.

        Returns ``(ok, message, clear_slot)``: ``ok`` is True only on a stored
        verdict; ``clear_slot`` is True on success OR a deterministic AO refusal
        (``INGEST_DECISION_REFUSED`` — the slot no longer matches AO reality), and
        False on a transient failure (the slot is kept so the operator can retry
        or /reject).  Slot membership itself is managed by the caller — this
        method neither reads nor mutates ``self._pending`` (so the edit path can
        decide a freshly-staged document, #663).
        """
        message = self._framer.encode_ingest_decision(
            doc_uuid=pending.doc_uuid,
            decision=verb,
            request_id=str(_uuid_mod.uuid4()),
        )
        result = await self._transport_call(message)

        if not result.get("ok", False):
            error_code = str(result.get("error_code", ""))
            if error_code == "INGEST_DECISION_REFUSED":
                # Deterministic state refusal (unknown doc, already decided —
                # the AO's check_decision refusals are never transient): the
                # slot no longer matches AO reality, so keeping it would trap
                # the operator with a slot nothing can clear.  Drop it.
                return False, self._format_ao_error(
                    f"Ingest {verb} refused by the Orchestrator — the pending "
                    "slot was cleared; re-run /ingest if needed", result
                ), True
            # Transient failure (transport error, bank disabled): the decision
            # never reached a verdict — keep the slot so the operator can
            # retry or /reject.
            return False, self._format_ao_error(
                f"Ingest {verb} failed (the document is still pending)", result
            ), False

        if verb == "approve":
            chunk_count = int(result.get("chunk_count", 0))
            return True, (
                f"Approved — “{pending.label}” is now in the knowledge "
                f"bank ({chunk_count} chunk{'s' if chunk_count != 1 else ''} "
                "indexed). It is retrievable in future turns (always as "
                "untrusted, datamarked context — approval is not trust)."
            ), True
        return True, (
            f"Rejected — “{pending.label}” was not added to the "
            "knowledge bank (the rejection is retained as a tombstone for the "
            "audit record)."
        ), True

    # ── edit-then-approve (UC-003 editable preview, #663 Workstream A) ─────

    async def approve_with_edit(self, session_id: str, edited_body: str) -> str:
        """Approve the session's pending document, optionally with an EDITED body.

        The WinUI Approve button routes here carrying the editable-preview box
        contents.  When the body is unchanged from the cleaner's output this is
        exactly ``/approve`` (no re-submit).  When the operator trimmed/edited
        it, the edited text is re-validated through the paste-path Cleaner scan
        (``clean_text`` — injection scan + delimiter-neutralise + fresh verdict +
        recomputed word_count; NO trafilatura re-extraction, so deliberately-kept
        content is never stripped), then dedup-REPLACES the pending row and is
        approved — so the stored/indexed body is exactly the curated text the
        operator approved.

        Quarantine LABELS but never blocks (the operator approval is the
        override, matching the ``/ingest`` posture — ADR-030 §6): a re-scan that
        re-flags the edited text is surfaced in the reply, not refused.
        """
        pending = self._pending.get(session_id)
        if pending is None:
            return (
                "Nothing to approve: no ingest is pending in this chat. "
                "Use /ingest first."
            )

        # Unchanged body (EOL-tolerant) → plain approve, no re-clean/re-submit.
        if self._is_unchanged(edited_body, pending.cleaned_text):
            return await self._handle_decision(session_id, "approve")

        # Re-validate the EDITED body via the paste-path scan (no re-extraction).
        clean_text_fn, _clean_html_fn = self._pipeline_loader()
        try:
            reclean = await asyncio.to_thread(clean_text_fn, edited_body)
        except CleanerUnavailableError:
            raise
        except Exception as exc:  # noqa: BLE001 — pipeline bug → loud refusal
            logger.error("Edited-body re-clean failed: %s", exc, exc_info=True)
            return (
                "Approve failed — re-validating your edited text raised a "
                f"cleaner error: {exc}. The document is still pending."
            )

        if not reclean.text.strip():
            return (
                "Approve refused: your edit left no text after cleaning — there "
                "is nothing to store (Fail-Closed). Re-open the preview and "
                "restore some text, or /reject to discard."
            )

        # Re-submit the edited body: carry the ORIGINAL source_ref forward (so it
        # dedup-REPLACES the pending row — a recomputed paste:<hash> would orphan
        # it + trip the AO collision guard) and preserve the original article
        # metadata (the paste-path re-clean only derives a markdown-H1 title and
        # drops byline/date).  prior_content_sha256 = the cleaner's original
        # digest → the AO records edited=1 + the keyed cleaner digest (#663).
        outcome = await self._stage_and_submit(
            cleaned_text=reclean.text,
            source_type=pending.source_type,
            source_ref=pending.source_ref,
            title=pending.title,
            byline=pending.byline,
            published_date=pending.published_date,
            word_count=int(reclean.word_count),
            cleaner_version=reclean.cleaner_version,
            prior_content_sha256=pending.content_sha256,
            recompute_paste_source_ref=False,
        )
        if isinstance(outcome, str):
            return outcome  # loud refusal; slot kept so the operator can retry
        result, new_doc_uuid, content_sha256, _source_ref, stored_text = outcome

        state = str(result.get("state", "error"))
        if state != "pending":
            if state == "already_ingested":
                # The original source was approved out-of-band between preview
                # and edit — the edit cannot supersede an approved row.
                self._pending.pop(session_id, None)
                return (
                    "This source is already approved in the knowledge bank — "
                    "your edited version was not stored. Start a fresh /ingest "
                    "to add a separate copy."
                )
            return self._format_ao_error("Approve (edited) failed", result)

        # Point the slot at the freshly-staged edited row, then approve it.
        # cleaned_text is the STORED text (any surviving blarai-img:// refs in
        # the edited body pass through unchanged — _process_images is a no-op on
        # text with no http(s) refs).
        edited_pending = replace(
            pending,
            doc_uuid=new_doc_uuid,
            cleaned_text=stored_text,
            content_sha256=content_sha256,
            word_count=int(reclean.word_count),
            cleaner_version=reclean.cleaner_version,
        )
        self._pending[session_id] = edited_pending
        ok, message, clear_slot = await self._dispatch_decision(
            edited_pending, "approve"
        )
        if clear_slot:
            self._pending.pop(session_id, None)
        if ok:
            message += " (Your curated edit was stored — not the cleaner's original.)"
            if reclean.status == "quarantined":
                reasons = ", ".join(reclean.reasons) or "(no reason codes)"
                message += (
                    " Note: the cleaner's scan re-flagged your edited text "
                    f"[{reasons}] — stored anyway per your approval."
                )
        return message

    @staticmethod
    def _is_unchanged(edited_body: str, original_cleaned_text: str) -> bool:
        """True when *edited_body* equals the cleaner's text (EOL-tolerant)."""
        return (
            edited_body.replace("\r\n", "\n").strip()
            == original_cleaned_text.replace("\r\n", "\n").strip()
        )

    # ── Message rendering ─────────────────────────────────────────────────

    @staticmethod
    def _format_ao_error(prefix: str, result: dict[str, Any]) -> str:
        code = str(result.get("error_code", "")) or "UNKNOWN_ERROR"
        message = str(result.get("message", "")) or "no detail provided"
        return f"{prefix}: [{code}] {message}"

    def _build_preview(
        self,
        clean: CleanResultLike,
        *,
        source_type: str,
        source_ref: str,
        body: str | None = None,
    ) -> str:
        """Render the single informational preview message for the transcript.

        Metadata header + the full cleaned text + the decision instruction —
        ONE message, deterministic tool output (never model output).  *body*
        overrides ``clean.text`` with the STORED text (image refs rewritten to
        ``blarai-img://`` / placeholders) so the preview shows exactly what is
        stored; it defaults to ``clean.text`` for callers with no image rewrite.
        """
        quarantined = clean.status == "quarantined"
        lines: list[str] = ["**Ingest preview — pending your approval**", ""]
        lines.append(f"- Title: {clean.title or '(none)'}")
        lines.append(f"- Source: {source_ref} ({source_type})")
        if clean.byline:
            lines.append(f"- Byline: {clean.byline}")
        if clean.published_date:
            lines.append(f"- Date: {clean.published_date}")
        lines.append(f"- Words: {clean.word_count}")
        lines.append(
            f"- Cleaner: v{clean.cleaner_version} — verdict: "
            + ("**QUARANTINED**" if quarantined else "clean")
            + f" (confidence {clean.confidence:.2f})"
        )
        if quarantined:
            reasons = ", ".join(clean.reasons) or "(no reason codes)"
            lines.append(f"- Quarantine reasons: {reasons}")
            lines.append(
                "- The cleaner flagged this content — review it carefully "
                "below before approving (approval is the override)."
            )
        lines.append("")
        lines.append("---")
        lines.append("")
        lines.append(clean.text if body is None else body)
        lines.append("")
        lines.append("---")
        lines.append(
            "Reply **/approve** to store this document in the knowledge bank, "
            "or **/reject** to discard it."
        )
        return "\n".join(lines)
