r"""The one-door, Policy-Agent-gated external-fetch seam (ADR-027 + ADR-020).

THE ONE DOOR
============
This module is **the single sanctioned path for ALL external (off-box) HTTP
fetching** in the BlarAI runtime. The air-gap-removal decision (#598 GO) does not
tear down the wall — it installs one door, with a guard on it, and welds every
other opening shut. The UC-003 URL-ingest cleaner is the first consumer; any
future web tool (Kagi search, a URL-clean agent, etc.) fetches through here too.
Nothing else in the runtime opens an external socket: the import-scan control
(``tests/security/test_no_external_egress.py``) forbids importing ``httpx`` (or
any network client) ANYWHERE in the runtime except this exact module, and the
raw-socket :mod:`shared.security.egress_guard` denies + auto-trips any off-
allowlist connect. So this is not *a* way out; it is *the* way out.

THE POSTURE — "URL = authorization" (binding LA decision, 2026-06-10)
====================================================================
When the operator initiates a fetch, the Policy Agent verdict on that URL
governs, and that verdict alone:

  * **ALLOW**   → proceed and fetch. There is NO extra mandatory fingerprint on
                  an ALLOW — the operator's initiation of the fetch IS the
                  authorization (hence the name). Adding a second consent gate on
                  every ALLOW would train the operator to rubber-stamp, defeating
                  the point of the ESCALATE tier.
  * **DENY**    → refuse, no fetch, WARNING log, denied :class:`FetchResult`.
  * **ESCALATE** → pause for a human approve/deny via
                  :func:`shared.security.escalation_consent.request_escalation_consent`
                  (the #639 Windows-Hello-backed consent path). Approval proceeds;
                  denial / timeout / no-verifier → DENY (fail-closed).

THE PIPELINE (strictly ordered, fail-closed at every step)
==========================================================
1. **URL validation / SSRF guard** — https only; no ``userinfo@``; no raw-IP
   hosts; reject loopback / private / link-local / CGNAT destinations; a non-
   standard port is rejected unless the caller put it in the URL explicitly. A
   rejected URL returns a denied :class:`FetchResult` — it NEVER fetches and
   NEVER raises. **Named-host resolution recheck (SSRF defense-in-depth):**
   immediately before widening the allowlist, the host is resolved ONCE (via
   :func:`_door_resolve`, the egress guard's REAL pre-arm resolver — so this
   inspect-and-refuse lookup does not trip the ARMED guard, since the host is not
   yet allowlisted at this moment) and the fetch is DENIED — no widen, no fetch —
   if ANY resolved address is in a blocked range per :func:`_is_blocked_ip`
   (loopback / private / link-local / reserved / multicast / unspecified / CGNAT).
   The actual egress (httpx) still resolves + connects through the armed guard +
   per-fetch widen + resolution pin. A raw-IP *literal* is already refused above;
   this catches a NAMED host that DNS-resolves to an internal address (e.g. an
   attacker pointing ``evil.example`` at ``169.254.169.254`` or ``127.0.0.1``).
   Resolution failure is fail-closed (DENY).

   **Residual — DNS rebinding (TOCTOU), NOT fully closed here.** The pre-fetch
   resolve-and-recheck and httpx's OWN resolution at connect time are two separate
   lookups; a rebinding attacker can answer the check with a good public IP and
   answer httpx's connect with a bad internal IP. The egress guard's resolution-pin
   layer narrows this (httpx connects to a numeric IP that must be pinned by an
   allowlisted name, and an internal IP is never pinned — merge-gate fix 1), but the
   robust close is a **custom httpx transport that validates the actually-connected
   peer IP** against the blocked ranges before sending the request. That transport
   is a named follow-up, deliberately out of scope here.
2. **Policy-Agent per-URL adjudication** via an INJECTED adjudicator
   (registration seam — :func:`register_url_adjudicator`). No adjudicator wired,
   or the adjudicator errors / is unreachable → DENY (fail-closed). This module
   does NOT import the PA service (no circular import; ``shared/security`` stays
   leaf-level) — exactly as :mod:`shared.security.egress_guard` takes its screener
   and :mod:`shared.security.escalation_consent` takes its verifier by
   registration.
3. **Charset-correct fetch** — :func:`egress_guard.allow_external_endpoint`
   widens the allowlist by exactly the one ``(host, 443)`` for the duration of
   this one fetch; the body is fetched via ``httpx`` with explicit timeouts;
   :func:`egress_guard.revoke_external_endpoint` runs in a ``finally`` so the
   allowlist is ALWAYS narrowed back, even on exception/timeout. The body is
   decoded by the response's DECLARED charset (Content-Type header, then an HTML
   ``<meta charset>``) — never a blind UTF-8 assume. An ``EgressTripped`` /
   ``EgressDenied`` from the guard latch is logged at CRITICAL with the guard
   reason and returned as a denied result (the latch is never swallowed quietly).
4. **Injection scan** — the returned text is run through the ADR-013 Layer-2
   heuristic scanner (``scan_for_injection``) before return; a flagged body is
   annotated + logged at WARNING (never silently passed).

THE BINARY (IMAGE) SIBLING — :func:`fetch_external_binary` (UC-003 Workstream B)
===============================================================================
Display-only images ride the SAME door in a binary mode. :func:`fetch_external_binary`
runs the identical Steps 1-3 (SSRF guard -> PA adjudication -> resolution recheck ->
the shared :func:`_fetch_raw` transport core), then REPLACES the text decode + Step-4
injection scan with :func:`_validate_binary_content` — a MIME-allowlist + magic-byte
gate (PNG/JPEG/GIF/WEBP only; SVG refused; header/body mismatch refused). It returns a
:class:`BinaryFetchResult` (a frozen SIBLING of :class:`FetchResult`, NOT a reshape of
it). The image path is welded INDEPENDENTLY of the text door, so a text go-live never
opens it: the registered adjudicator hard-denies the ``uc003-image-ingest`` purpose
(BED-1, ``services/ui_gateway/src/url_adjudicator.py`` ``IMAGE_INGEST_DENY_PURPOSES``),
``[knowledge].images_enabled`` gates it separately, and the MIME-allowlist + magic-byte
gate binds whatever gets through. Lifting the purpose-deny is part of the image go-live
ceremony, never a side effect. The byte cap is per-image (:data:`MAX_IMAGE_BYTES`),
enforced by the same streaming-cap read that protects the text path.

THE REGISTRATION SEAM (for callers)
===================================
A consumer (the UC-003 cleaner; a future web tool) MUST, at its entry point, wire
the real Policy Agent adjudication by calling :func:`register_url_adjudicator`
with a ``Callable[[str, str], Verdict]`` (url, purpose). That callable builds a
:class:`shared.schemas.car.CanonicalActionRepresentation` for the URL fetch and
runs it through the in-process Policy Agent (``HybridAdjudicator``), mapping the
PA ``AdjudicationDecision`` (ALLOW / DENY / ESCALATE) onto the local
:class:`Verdict`. Until a caller wires that, NO adjudicator is registered and
every fetch DENIES — the dormant, fail-closed default. **This module deliberately
ships WITHOUT a built-in adjudicator: faking a verdict in runtime code would be a
silent open door.** See the TODO at :func:`register_url_adjudicator`.

Design constraints (match the rest of ``shared/security/``):
  - **No new dependencies beyond ``httpx``** (already in the venv, declared in
    ``pyproject.toml``). ``httpx`` is the ONE network client the runtime imports,
    and ONLY here (the import-scan control exempts exactly this module).
  - **Importing this module has no side effects** — it registers no adjudicator
    and opens no socket at import. A caller wires the adjudicator explicitly.
  - **Fail-Closed everywhere:** every ambiguous / error / missing path is a denied
    :class:`FetchResult`, never a raise out of :func:`fetch_external` and never a
    silent pass. The allowlist widen is ALWAYS reverted.
"""

from __future__ import annotations

import logging
import re
import socket
import threading
from dataclasses import dataclass, replace
from enum import Enum
from ipaddress import ip_address
from typing import Callable, Final, Optional
from urllib.parse import urlsplit

import httpx

from shared.security import egress_guard, ip_block
from shared.security.escalation_consent import (
    EscalationContext,
    request_escalation_consent,
)

# The ADR-013 Layer-2 prompt-injection heuristic scanner (the single in-tree
# implementation; reused, not reinvented). #896: now homed in shared.security —
# this module previously reached ACROSS the shared→services boundary into the
# gateway document loader for it; the detector moved to its architectural home.
from shared.security.injection_scan import scan_for_injection

logger = logging.getLogger(__name__)

# The only scheme an external fetch may use. Plaintext http, file, ftp, data, etc.
# are all refused — TLS is mandatory for anything leaving the box.
_ALLOWED_SCHEME: Final[str] = "https"

# The standard TLS port. A URL with no explicit port fetches here; an explicit
# non-standard port is refused (the SSRF guard only permits 443 unless the caller
# put a port in the URL — and even then only a sane web port set, below).
_STANDARD_HTTPS_PORT: Final[int] = 443

# Explicit ports a caller MAY request (in the URL). Kept tight: 443 (standard) and
# 8443 (the common alt-https). Anything else is refused as an SSRF/scan vector.
_ALLOWED_EXPLICIT_PORTS: Final[frozenset[int]] = frozenset({443, 8443})

# Connect timeout is fixed (a hung TCP connect must not wait the full read budget);
# the read timeout is the caller's ``timeout_s``.
_CONNECT_TIMEOUT_S: Final[float] = 10.0

# Cap the decoded body so a hostile/huge response cannot exhaust memory. Mirrors
# the gateway document-loader's extracted-text discipline.
_MAX_BODY_BYTES: Final[int] = 8 * 1024 * 1024  # 8 MiB

# Sniff an HTML <meta charset=...> / <meta http-equiv content="...charset=..."> from
# the first chunk of a body when the Content-Type header carries no charset.
_META_CHARSET_RE: Final[re.Pattern[bytes]] = re.compile(
    rb"""<meta[^>]+?charset\s*=\s*["']?\s*([A-Za-z0-9_\-]+)""",
    re.IGNORECASE,
)


# ===========================================================================
# UC-003 Workstream B — display-only image fetch constants (PINNED by the
# contract spec, docs/handoffs/uc003-b-contract-spec.md §"Shared constants").
# ===========================================================================
# These govern the BINARY egress path (:func:`fetch_external_binary`) and the
# downstream image-staging / storage modules. They live HERE (the door) because
# the door is the leaf module every image consumer already imports, and the
# byte/MIME caps are a SECURITY contract that must be enforced at the fetch seam
# itself — not just advised downstream. These constants govern the IMAGE path
# only. That path is welded INDEPENDENTLY of the text door — the BED-1
# `uc003-image-ingest` purpose-deny, the separate `[knowledge].images_enabled`
# gate, and the MIME/magic-byte gate below — so a text-door go-live never opens
# it; only a separate LA-reviewed image ceremony does.

# The lowercase MIME types an image fetch may return. SVG is DELIBERATELY ABSENT
# (and explicitly refused below) — SVG is an XML document that can carry script /
# external references, so it is NOT a safe display-only raster format. Anything
# not in this set is refused, fail-closed.
IMAGE_CONTENT_TYPE_ALLOWLIST: Final[frozenset[str]] = frozenset(
    {"image/png", "image/jpeg", "image/gif", "image/webp"}
)

# Per-image byte cap (2 MiB). NON-NEGOTIABLE — the binary read is capped at this
# many bytes; an over-cap image is truncated-at-cap and treated as truncated (the
# caller decides whether a truncated image is usable). Mirrors the text door's
# `_MAX_BODY_BYTES` discipline but scoped to a single image.
MAX_IMAGE_BYTES: Final[int] = 2 * 1024 * 1024  # 2 MiB per image

# How many images one article may carry through ingest (truncate-with-notice on
# count). Open LA sanity-check per the spec; built against 20. Enforced by the
# downstream coordinator (NOT by this door — the door fetches one image at a time);
# pinned here so every module reads the same number.
MAX_IMAGES_PER_ARTICLE: Final[int] = 20

# Aggregate byte ceiling across ALL images in one article (8 MiB). Enforced by the
# downstream coordinator across the per-article image set; pinned here for a single
# source of truth.
MAX_TOTAL_IMAGE_BYTES: Final[int] = 8 * 1024 * 1024  # 8 MiB total per article

# Drop images whose smaller dimension is below this (decorative spacers / tracking
# pixels). A header-read (no full decode) is the intended path; the dimension drop
# lives in the downstream coordinator, NOT in this door. The byte caps above are
# the mandatory floor; the dimension drop is a refinement.
MIN_IMAGE_DIMENSION_PX: Final[int] = 32

# Decompression-bomb CEILING (UC-003 Workstream B, W1 / BED-3).  The byte caps
# (:data:`MAX_IMAGE_BYTES`) bound the COMPRESSED size on the wire, but a tiny
# 2 MiB PNG/WEBP can DECODE to billions of pixels (a "decompression bomb") and
# exhaust host memory at render time.  These cap the DECODED pixel extent, read
# header-only (no decode — decoding the image to measure it would BE the attack):
#   * max edge — the larger of width/height must not exceed this.
#   * max area — width*height must not exceed this.
# An image OVER either bound is dropped to a placeholder (coordinator) and refused
# at the at-rest store boundary (knowledge_bank.store_image, defense-in-depth).
# Tunable by the LA in this ONE place (Guide defaults — max edge 16384 px, the
# common GPU/codec texture limit; max area 40 MP, well above any real article
# photo).  Header-only: enforced via :func:`dimension_above_max` /
# :func:`image_dimensions_ok`, never a pixel decode.
MAX_IMAGE_DIMENSION_PX: Final[int] = 16384         # 16384 px max edge
MAX_IMAGE_PIXELS: Final[int] = 40_000_000          # 40 megapixels max area

# The generic, pinned browser User-Agent the egress door presents on EVERY
# external fetch — the SHARED transport core (:func:`_fetch_raw`) sets it, so it
# governs BOTH the text door (:func:`fetch_external`) and the image door
# (:func:`fetch_external_binary`).  PRIV-2 (UC-003 Workstream B, LA-locked
# 2026-06-15): a single generic modern-desktop-browser string so an outbound
# fetch blends into ordinary web traffic rather than self-identifying as BlarAI
# (anti-fingerprinting).  DELIBERATELY PINNED — a per-build or auto-bumped UA
# would itself become a fingerprint, so it is a fixed literal here and is
# refreshed DELIBERATELY (a conscious edit to a current-but-common string),
# accepting that a long-stale string is its own mild signal — the trade-off the
# LA chose over a self-identifying or churning UA.  No Cookie / Referer / other
# identifying header is ever sent (the client carries only this one header).
_USER_AGENT: Final[str] = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)

# Magic-byte signatures for the allowlisted formats (sniff the first 12 bytes;
# REFUSE on a header/body mismatch). A declared `image/png` whose bytes are not a
# PNG is refused — the header alone is attacker-controlled, so the body must agree.
#   * PNG  — the 8-byte PNG signature.
#   * JPEG — the SOI marker `FF D8 FF` (the 4th byte varies by JFIF/EXIF/etc.).
#   * GIF  — `GIF87a` or `GIF89a`.
#   * WEBP — a RIFF container: bytes[0:4] == b"RIFF" AND bytes[8:12] == b"WEBP"
#     (bytes[4:8] are the little-endian chunk size — NOT matched). WEBP is handled
#     specially below (a split signature, not a simple prefix), so it is NOT in this
#     prefix table.
_IMAGE_MAGIC_PREFIXES: Final[dict[str, tuple[bytes, ...]]] = {
    "image/png": (b"\x89PNG\r\n\x1a\n",),
    "image/jpeg": (b"\xff\xd8\xff",),
    "image/gif": (b"GIF87a", b"GIF89a"),
}

# WEBP RIFF container markers — bytes[0:4] and bytes[8:12] respectively.
_WEBP_RIFF_MARKER: Final[bytes] = b"RIFF"
_WEBP_FORMAT_MARKER: Final[bytes] = b"WEBP"


class Verdict(str, Enum):
    """The Policy-Agent verdict on a fetch URL (local to this module).

    Mirrors :class:`shared.schemas.car.AdjudicationDecision` (ALLOW/DENY/ESCALATE)
    but is defined here so ``shared/security`` does not import the PA schema/service
    — the registration seam decouples this door from the PA implementation. A
    registered adjudicator maps the real PA decision onto one of these.
    """

    ALLOW = "ALLOW"
    DENY = "DENY"
    ESCALATE = "ESCALATE"


# The injected per-URL adjudicator: given (url, purpose), return a Verdict. The
# registration pattern (no import of the PA service from here) keeps shared/security
# leaf-level and acyclic — identical to egress_guard.register_screener and
# escalation_consent.register_verifier.
UrlAdjudicator = Callable[[str, str], Verdict]


@dataclass(frozen=True)
class FetchResult:
    """The outcome of an external fetch (FROZEN contract — Vikunja #577 c.1029).

    Consumed by the UC-003 cleaner and any future web tool. ``denied_reason`` is
    the load-bearing discriminator: ``None`` means the fetch succeeded (``status`` /
    ``content_text`` / ``content_type`` are populated); a non-``None`` string means
    the fetch was refused at some pipeline step (the body fields are empty) and the
    string is a short, log-safe label of WHY — never a raw secret/PII.

    ``injection_flags`` surfaces the ADR-013 Layer-2 injection-scan result to the
    consumer (merge-gate fix 3): the heuristic labels matched in the fetched body,
    empty when the body is clean (or the fetch was denied / never fetched). The scan
    is annotate-not-block — the body is returned unchanged regardless — but the
    cleaner (UC-003) can now ACT on the flags (quarantine, extra review) instead of
    them living only in the log.
    """

    url: str
    status: int = 0
    content_text: str = ""
    content_type: str = ""
    denied_reason: Optional[str] = None
    injection_flags: tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        """True iff the fetch was permitted and completed (no denial)."""
        return self.denied_reason is None


@dataclass(frozen=True)
class BinaryFetchResult:
    """The outcome of a BINARY (image) external fetch — a FROZEN SIBLING to
    :class:`FetchResult` (UC-003 Workstream B, display-only images).

    A deliberate SIBLING, not a reshape of :class:`FetchResult`: the text result's
    contract is frozen (#577 c.1029) and consumed by the cleaner, so the binary
    path gets its own frozen type rather than perturbing the proven one. The two
    share the discriminator shape — ``denied_reason is None`` means success — but
    carry different payloads (``content_bytes`` + a validated ``mime`` here vs.
    ``content_text`` + ``injection_flags`` there). There is NO injection-scan field:
    the binary path skips the text injection scan (image bytes are not text), so
    there are no flags to surface.

    On success: ``denied_reason is None``, ``status`` / ``content_bytes`` /
    ``content_type`` (the raw declared header) / ``mime`` (the VALIDATED, allowlisted
    MIME) are populated, and ``truncated`` says whether the body hit the byte cap.
    On any refusal (SSRF / policy / resolution / fetch error / content-validation
    failure): ``denied_reason`` is a short, log-safe label of WHY and the body
    fields are empty — :func:`fetch_external_binary` NEVER raises.
    """

    url: str
    status: int = 0
    content_bytes: bytes = b""
    content_type: str = ""
    mime: str = ""
    truncated: bool = False
    denied_reason: Optional[str] = None

    @property
    def ok(self) -> bool:
        """True iff the binary fetch was permitted, completed, and validated."""
        return self.denied_reason is None


# ---------------------------------------------------------------------------
# The per-URL adjudicator registry (the integration seam) — dormant by default.
# ---------------------------------------------------------------------------
# Mirrors egress_guard's screener registry and escalation_consent's verifier
# registry: a consumer wires the real PA adjudicator at startup so this door can
# reach it WITHOUT importing the PA service (no circular import). The default is NO
# adjudicator, which means every fetch DENIES — fail-closed and dormant-safe.

_adjudicator: Optional[UrlAdjudicator] = None
_adjudicator_lock = threading.Lock()


def register_url_adjudicator(adjudicator: UrlAdjudicator) -> None:
    """Register the per-URL Policy-Agent adjudicator (the integration seam).

    INTERFACE ANCHOR. A consumer (the UC-003 URL-ingest cleaner; a future web tool)
    calls this once at its entry point with a ``Callable[[str, str], Verdict]``
    (url, purpose). With an adjudicator registered, :func:`fetch_external` consults
    it on every URL; with none registered (the default), every fetch is DENIED —
    the fail-closed posture. The slot is SINGULAR and first-wins, so which
    adjudicator is in force depends on which caller wired it first; the two egress
    layers agree only while the deterministic one holds it (#977 OPEN).

    TODO (caller wiring — NOT done in this module by design): the registered
    callable is expected to build a
    :class:`shared.schemas.car.CanonicalActionRepresentation` describing the URL
    fetch (action = EXECUTE / resource = the URL / agent = the calling tool) and
    run it through the in-process Policy Agent
    (``services.policy_agent.src.adjudicator.HybridAdjudicator.adjudicate``),
    mapping the resulting :class:`shared.schemas.car.AdjudicationDecision` onto the
    local :class:`Verdict`. This module ships WITHOUT that wiring on purpose:
    fabricating a verdict in this leaf module would be a silent open door, and the
    PA is a service-layer dependency that ``shared/security`` must not import. Until
    the caller registers it, the door stays fail-closed shut.

    Single-adjudicator: registering replaces any previously-registered one (the
    fetch door is singular). Registering does not by itself permit anything — it
    only makes a per-URL verdict *obtainable*; an absent/erroring adjudicator still
    denies.

    :param adjudicator: ``Callable[[str, str], Verdict]`` — (url, purpose) -> verdict.
        MUST be synchronous and MUST NOT itself perform egress.
    :raises TypeError: if ``adjudicator`` is not callable.
    """
    if not callable(adjudicator):
        raise TypeError("register_url_adjudicator requires a callable (url, purpose) -> Verdict")
    global _adjudicator
    with _adjudicator_lock:
        _adjudicator = adjudicator
    logger.info(
        "guarded_fetch: per-URL Policy-Agent adjudicator registered (%s) — external "
        "fetches now route to the PA for an ALLOW/DENY/ESCALATE verdict.",
        getattr(adjudicator, "__name__", type(adjudicator).__name__),
    )


def clear_url_adjudicator() -> None:
    """Unregister the adjudicator — return to the dormant deny-every-fetch default.

    Used at shutdown and by tests (so an injected fake does not leak across tests).
    After this, :func:`fetch_external` denies every fetch again (fail-closed).
    """
    global _adjudicator
    with _adjudicator_lock:
        _adjudicator = None


def active_url_adjudicator() -> Optional[UrlAdjudicator]:
    """Return the currently-registered per-URL adjudicator, or ``None``."""
    with _adjudicator_lock:
        return _adjudicator


# ---------------------------------------------------------------------------
# Step 1 — URL validation / SSRF guard.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _ValidatedTarget:
    """A URL that passed the SSRF guard: the host + the resolved-intent port."""

    host: str
    port: int


def _validate_url(url: str) -> tuple[Optional[_ValidatedTarget], Optional[str]]:
    """Validate ``url`` against the SSRF guard. Returns (target, denied_reason).

    Exactly one of the two is non-``None``. Fail-closed: anything unparseable,
    non-https, with userinfo, a raw-IP host, a non-allowed port, or a host that
    parses to a loopback / private / link-local / CGNAT address is refused. Never
    raises.
    """
    if not isinstance(url, str) or not url.strip():
        return None, "url is empty or not a string"
    try:
        parts = urlsplit(url.strip())
    except ValueError:
        return None, "url is not parseable"

    if parts.scheme.lower() != _ALLOWED_SCHEME:
        return None, f"scheme {parts.scheme!r} not permitted (https only)"

    # userinfo (user[:pass]@host) is a classic SSRF/credential-smuggle vector.
    if parts.username is not None or parts.password is not None or "@" in parts.netloc:
        return None, "url carries userinfo (user@host) — refused"

    host = parts.hostname
    if not host:
        return None, "url has no host"
    host = host.strip().rstrip(".").lower()
    if not host:
        return None, "url host is empty after normalisation"

    # A raw-IP host (no DNS name) is refused outright — external fetches go to named
    # hosts the PA can reason about; an IP literal sidesteps the resolution-pin
    # allowlist semantics and is a common SSRF shape (e.g. http to 169.254.169.254).
    parsed_ip = None
    try:
        parsed_ip = ip_address(host)
    except ValueError:
        parsed_ip = None
    if parsed_ip is not None:
        return None, "url host is a raw IP literal — refused (named hosts only)"

    # Defensive: if the host string nonetheless resolves to a numeric form that is
    # loopback/private/link-local/CGNAT (an IPv6 literal in brackets, an unusual
    # encoding), refuse it. (A bracketed IPv6 literal is caught here.)
    bracket_host = parts.hostname  # urlsplit strips the [] for IPv6
    if bracket_host:
        try:
            ip_in_host = ip_address(bracket_host)
        except ValueError:
            ip_in_host = None
        if ip_in_host is not None and _is_blocked_ip(ip_in_host):
            return None, "url host resolves to a blocked (loopback/private/link-local/CGNAT) range"

    # Port: an explicit port must be in the tight allowed set; no explicit port ->
    # standard 443.
    try:
        explicit_port = parts.port
    except ValueError:
        return None, "url port is invalid"
    if explicit_port is None:
        port = _STANDARD_HTTPS_PORT
    elif explicit_port in _ALLOWED_EXPLICIT_PORTS:
        port = explicit_port
    else:
        return None, f"port {explicit_port} not permitted (allowed: {sorted(_ALLOWED_EXPLICIT_PORTS)})"

    return _ValidatedTarget(host=host, port=port), None


def _is_blocked_ip(addr: object) -> bool:
    """True iff ``addr`` (an ip_address) is in a range an external fetch must never reach.

    Delegates to the ONE canonical blocked-range predicate
    (:func:`shared.security.ip_block.is_blocked_ip`) so this fetch-side check and
    ``egress_guard``'s pin-side check can never diverge — a range is added in one
    place and both doors move together (Vikunja #802 / AUDIT-3). This wrapper is
    kept (not inlined) so the ``_is_blocked_ip`` name this module's callers
    (:func:`_validate_url`, :func:`_resolution_blocked_reason`) use is unchanged.
    """
    return ip_block.is_blocked_ip(addr)  # type: ignore[arg-type]


def _door_resolve(host, port):
    """Resolve a host for the door's OWN SSRF pre-check, via the egress guard's
    REAL (pre-arm) resolver so an armed guard does not trip on the door's
    inspect-and-refuse lookup. The actual egress (httpx) still resolves through
    the armed guard + the per-fetch widen + resolution pin."""
    return egress_guard.real_getaddrinfo(host, port, type=socket.SOCK_STREAM)


def _resolution_blocked_reason(target: _ValidatedTarget) -> Optional[str]:
    """Resolve ``target.host`` once and DENY if ANY resolved IP is in a blocked range.

    SSRF defense-in-depth (merge-gate fix 1). :func:`_validate_url` rejects a raw-IP
    *literal* host, but a NAMED host that DNS-resolves to an internal address
    (10.x / 172.16-31.x / 192.168.x / 169.254.x / 100.64.x / reserved / multicast /
    loopback) is not caught by string inspection. Before widening the allowlist and
    fetching, we resolve the host ONCE and refuse the whole fetch if any returned
    address is blocked per :func:`_is_blocked_ip`. This also catches a name resolving
    to LOOPBACK — which the egress guard permits globally for IPC, so the door must
    refuse it itself rather than rely on the guard.

    Resolution routes through :func:`_door_resolve` — the unguarded door-resolution
    seam (the egress guard's REAL, pre-arm resolver). WHY: in production the egress
    guard is ARMED before any fetch, and the host the door is about to widen is NOT
    yet on the allowlist at this moment — so resolving it through the *guarded*
    resolver would TRIP the kill-switch on the door's own inspect-and-refuse lookup
    (and the operator's first ``/ingest`` would deny + air-gap the box). Using the
    real resolver here keeps this pre-check armed-guard-compatible while preserving
    its "no widen, no fetch" property: this lookup only INSPECTS the resolved IPs to
    REFUSE internal targets; it never connects. The ACTUAL egress (httpx in
    :func:`_fetch_body`) still resolves + connects through the armed guard, the
    per-fetch widen, and the W4 resolution pin — unchanged. The test suite drives
    this with a monkeypatched ``_door_resolve`` (no real DNS).

    Returns a short, log-safe denied-reason string if the host must NOT be fetched,
    or ``None`` if every resolved address is a permitted public destination.
    Fail-closed: any resolution error (or an empty result) is a DENY.
    """
    try:
        infos = _door_resolve(target.host, target.port)
    except OSError as exc:
        logger.warning(
            "guarded_fetch: pre-fetch resolution of host failed (%s) — DENY (fail-closed)",
            type(exc).__name__,
        )
        return f"host resolution failed: {type(exc).__name__}"
    except Exception as exc:  # noqa: BLE001 — any resolver error fails closed
        logger.warning(
            "guarded_fetch: pre-fetch resolution raised (%s) — DENY (fail-closed)",
            type(exc).__name__,
        )
        return f"host resolution error: {type(exc).__name__}"

    resolved: list[str] = []
    for info in infos:
        try:
            sockaddr = info[4]
            ip_str = sockaddr[0]
        except (IndexError, TypeError):
            return "host resolution returned a malformed address"  # fail-closed
        if not isinstance(ip_str, str) or not ip_str:
            return "host resolution returned a malformed address"
        try:
            addr = ip_address(ip_str)
        except ValueError:
            return "host resolved to an unparseable address"  # fail-closed
        if _is_blocked_ip(addr):
            logger.warning(
                "guarded_fetch: host resolves to a blocked (internal/special) range "
                "— DENY, no widen, no fetch (SSRF defense-in-depth)"
            )
            return "host resolves to a blocked (loopback/private/link-local/CGNAT) address"
        resolved.append(ip_str)

    if not resolved:
        # No address at all -> nothing to fetch; fail-closed DENY.
        return "host resolution returned no address"
    return None


# ---------------------------------------------------------------------------
# Step 2 — Policy-Agent per-URL adjudication.
# ---------------------------------------------------------------------------


def _adjudicate(url: str, purpose: str) -> tuple[Verdict, Optional[str]]:
    """Get the PA verdict for ``url``. Returns (verdict, denied_reason_if_denied).

    Fail-closed: no adjudicator registered, an adjudicator that raises, or one that
    returns a non-:class:`Verdict` value all yield ``Verdict.DENY`` with a reason.
    On ESCALATE, the #639 consent path is consulted: approval -> ALLOW, anything
    else (deny/timeout/no-verifier) -> DENY.
    """
    adjudicator = active_url_adjudicator()
    if adjudicator is None:
        return Verdict.DENY, "no Policy-Agent adjudicator registered (fail-closed default)"

    try:
        raw = adjudicator(url, purpose)
    except Exception as exc:  # noqa: BLE001 — a failing adjudicator fails closed
        logger.error("guarded_fetch: PA adjudicator raised %r — DENY (fail-closed)", exc)
        return Verdict.DENY, f"adjudicator error: {type(exc).__name__}"

    if not isinstance(raw, Verdict):
        logger.error(
            "guarded_fetch: PA adjudicator returned a non-Verdict (%r) — DENY (fail-closed)",
            type(raw).__name__,
        )
        return Verdict.DENY, "adjudicator returned a malformed verdict"

    if raw is Verdict.ALLOW:
        return Verdict.ALLOW, None
    if raw is Verdict.DENY:
        logger.warning("guarded_fetch: Policy Agent DENIED fetch of a URL (purpose=%r)", purpose)
        return Verdict.DENY, "Policy Agent denied the URL"

    # ESCALATE -> route to the #639 human-consent path. "URL = authorization" means
    # ESCALATE is the ONLY verdict that prompts for a fingerprint; an ALLOW does not.
    context = EscalationContext.from_pa_verdict(
        "ESCALATE_EXTERNAL_FETCH",
        tool_name="guarded_fetch",
        action_summary=f"FETCH external url (purpose:{purpose})",
        source="guarded_fetch",
    )
    approval = request_escalation_consent(context)
    if approval.approved:
        logger.warning(
            "guarded_fetch: ESCALATE fetch APPROVED by operator via %s",
            approval.verifier_identity,
        )
        return Verdict.ALLOW, None
    return Verdict.DENY, f"ESCALATE not approved ({approval.reason})"


# ---------------------------------------------------------------------------
# Step 3 — charset-correct fetch (allowlist widen / revoke around httpx).
# ---------------------------------------------------------------------------


def _charset_from_content_type(content_type: str) -> Optional[str]:
    """Extract the declared charset from a Content-Type header value, or ``None``."""
    if not content_type:
        return None
    for part in content_type.split(";"):
        part = part.strip()
        if part.lower().startswith("charset="):
            charset = part.split("=", 1)[1].strip().strip('"').strip("'")
            return charset or None
    return None


def _charset_from_meta(body: bytes) -> Optional[str]:
    """Sniff an HTML ``<meta charset>`` from the (head of the) body, or ``None``."""
    match = _META_CHARSET_RE.search(body[:4096])
    if match:
        try:
            return match.group(1).decode("ascii").strip() or None
        except UnicodeDecodeError:
            return None
    return None


def _decode_body(body: bytes, content_type: str, http_encoding: Optional[str]) -> str:
    """Decode ``body`` by its DECLARED charset, never a blind UTF-8 assume.

    Resolution order: Content-Type header charset -> httpx's parsed ``encoding``
    (which also reflects the header) -> an HTML ``<meta charset>`` -> a final
    UTF-8-with-replacement fallback so decoding never raises. The point is to honor
    whatever the page actually sent (a page may declare e.g. ISO-8859-1 / Shift_JIS
    and send bytes that are NOT valid UTF-8); a blind UTF-8 decode would mangle it.
    """
    candidates: list[str] = []
    declared = _charset_from_content_type(content_type)
    if declared:
        candidates.append(declared)
    if http_encoding and http_encoding.lower() not in (c.lower() for c in candidates):
        candidates.append(http_encoding)
    meta = _charset_from_meta(body)
    if meta and meta.lower() not in (c.lower() for c in candidates):
        candidates.append(meta)
    for charset in candidates:
        try:
            return body.decode(charset)
        except (LookupError, UnicodeDecodeError):
            continue
    # Nothing declared decoded cleanly -> UTF-8 with replacement (never raises).
    return body.decode("utf-8", errors="replace")


def _read_capped_body(response: httpx.Response, max_bytes: int = _MAX_BODY_BYTES) -> tuple[bytes, bool]:
    """Read a streaming response body up to ``max_bytes``; stop once capped.

    Memory-exhaustion DoS guard (merge-gate fix 2). ``client.get()`` reads the FULL
    body into memory before any slice, so a hostile host streaming gigabytes would
    exhaust host memory before the cap could apply. Here we consume the byte stream
    chunk-by-chunk, accumulating only up to the cap, and stop reading the moment the
    cap is reached — the unread remainder is never pulled into memory.

    ``max_bytes`` is parameterized so the SAME streaming-cap logic serves the text
    door (``_MAX_BODY_BYTES``, 8 MiB) and the binary/image door (``MAX_IMAGE_BYTES``,
    2 MiB) without duplicating the read loop. The default preserves the historical
    text-door behaviour exactly.

    Returns ``(body, truncated)`` where ``body`` is at most ``max_bytes`` and
    ``truncated`` is True iff the response carried more than the cap (the caller logs
    a WARNING; an over-cap body is treated as truncated-at-cap, NOT an error).
    """
    chunks: list[bytes] = []
    total = 0
    truncated = False
    # ONE iterator over the byte stream — httpx forbids re-iterating a consumed
    # stream, so the over-cap "is there more?" check peeks the SAME iterator.
    stream = response.iter_bytes()
    for chunk in stream:
        if not chunk:
            continue
        remaining = max_bytes - total
        if len(chunk) >= remaining:
            chunks.append(chunk[:remaining])
            total += remaining
            if len(chunk) > remaining:
                # This chunk alone overflowed the cap — definitely truncated; stop
                # reading (the unread remainder is never pulled into memory).
                truncated = True
            else:
                # Exactly filled the cap — peek ONE more chunk on the same iterator
                # (next(), not a re-iteration) to learn whether bytes remain. At most
                # one extra chunk is pulled; the rest is never read.
                truncated = next(stream, b"") != b""
            break
        chunks.append(chunk)
        total += len(chunk)
    return b"".join(chunks), truncated


class _RawFetchError(Exception):
    """Internal: a fetch failed at the raw (pre-decode) transport layer.

    Carries a short, log-safe ``denied_reason`` that the caller maps onto its own
    result type (text :class:`FetchResult` or :class:`BinaryFetchResult`). NEVER
    escapes the module — both wrappers catch it and return a denied result. Used so
    the shared :func:`_fetch_raw` core can report a refusal WITHOUT knowing which
    result type the caller wants.
    """

    def __init__(self, denied_reason: str) -> None:
        super().__init__(denied_reason)
        self.denied_reason = denied_reason


def _fetch_raw(
    target: _ValidatedTarget,
    url: str,
    timeout_s: float,
    *,
    max_bytes: int,
    authorization: Optional[str] = None,
    method: str = "GET",
    json_body: Optional[dict] = None,
) -> tuple[int, bytes, str, bool]:
    """Widen the allowlist for exactly this host, fetch RAW bytes, and ALWAYS revoke.

    The shared transport core for BOTH the text door (:func:`_fetch_body`) and the
    binary/image door (:func:`fetch_external_binary`). It does the egress-guard
    widen -> ``httpx.stream`` (``method``, default GET) -> :func:`_read_capped_body`
    (capped at ``max_bytes``) -> **ALWAYS-runs ``finally`` revoke** — and returns the
    RAW ``(status, body_bytes, content_type_header, truncated)`` with NO text decode
    and NO content validation. The caller decides what to do with the bytes (text
    decode + injection scan, or binary MIME/magic validation).

    The allowlist widen is reverted in a ``finally`` no matter what — exception,
    timeout, guard trip — preserving the door's core "the widen is ALWAYS narrowed
    back" guarantee. An egress-guard latch (``EgressTripped`` / ``EgressDenied``), a
    timeout, or any other ``httpx.HTTPError`` is converted to a :class:`_RawFetchError`
    with a short denied-reason (logged at the appropriate level here); this function
    never returns a partial/ambiguous success.

    ``authorization`` (#719 web_search go-live build, ADR-024 W4): an optional
    ``Authorization`` header VALUE (e.g. ``"Bearer <key>"``) for an API endpoint the
    PA has already adjudicated — the Kagi Search API is the first (and only)
    consumer. SECRET-HANDLING CONTRACT: the value is placed in the request
    headers and NOWHERE else — it is never logged, never echoed into a
    denied-reason, and never stored on a result object. ``None`` (the default,
    and every pre-existing caller) sends no Authorization header — the
    historical wire shape, byte-identical. The PRIV-2 no-Cookie/no-Referer
    posture is unchanged; the client carries at most User-Agent + this one
    caller-supplied credential header.

    ``method`` / ``json_body`` (#724 — Kagi v1 POST): the CURRENT Kagi Search API
    (``/api/v1/search``) is a POST with a JSON request body, not a GET. Both are
    keyword-only and DEFAULT to the historical GET-with-no-body shape, so every
    pre-existing caller (the UC-003 text door, the image door) is byte-identical
    on the wire — no method change, no request body, no extra header. When
    ``json_body`` is not ``None`` it is passed to ``httpx`` as ``json=...`` (httpx
    serialises it and sets ``Content-Type: application/json``); the whole pipeline
    (SSRF guard, PA adjudication, allowlist widen/revoke, streaming byte cap) is
    unchanged — POST only alters the single ``client.stream`` call, and the
    ``max_bytes`` cap still bounds the response body.

    :raises _RawFetchError: on any guard-latch / timeout / HTTP error (the caller
        maps ``.denied_reason`` onto its own denied result type).
    """
    host, port = target.host, target.port
    timeout = httpx.Timeout(timeout_s, connect=_CONNECT_TIMEOUT_S)
    # PRIV-2: one generic pinned User-Agent; no Cookie, no Referer. The ONLY
    # other header ever sent is the caller-supplied Authorization credential
    # (never logged — see the secret-handling contract in the docstring).
    headers: dict[str, str] = {"User-Agent": _USER_AGENT}
    if authorization is not None:
        headers["Authorization"] = authorization

    logger.warning(
        "guarded_fetch: WIDEN egress allowlist for one fetch — host=%r port=%d "
        "(PA-ALLOWED; auto-revoked after this fetch)",
        host, port,
    )
    egress_guard.allow_external_endpoint(host, port)
    try:
        with httpx.Client(
            timeout=timeout,
            follow_redirects=False,
            transport=_active_transport(),
            # PRIV-2: present ONE generic, pinned browser User-Agent — no
            # Cookie, no Referer — so the fetch blends into ordinary web
            # traffic instead of self-identifying as BlarAI. Governs BOTH
            # doors (this is the shared transport core). ``headers`` may also
            # carry the caller-supplied Authorization credential (see above).
            headers=headers,
        ) as client:
            # STREAM the body so a hostile (PA-allowed) host cannot exhaust host
            # memory: a plain client.get() reads the FULL body into memory BEFORE the
            # cap could slice it. We accumulate chunks up to the cap and stop — an
            # over-cap body is truncated-at-cap (logged WARNING, never raised).
            #
            # #724: ``method`` defaults to "GET" and ``stream_kwargs`` is empty
            # unless a caller supplied a ``json_body`` — so the historical GET path
            # is ``client.stream("GET", url)`` EXACTLY, byte-identical. A POST caller
            # (Kagi v1) rides ``json=<body>``; the streaming cap still bounds the
            # response, so a large POST reply cannot exhaust memory either.
            stream_kwargs: dict[str, object] = {}
            if json_body is not None:
                stream_kwargs["json"] = json_body
            with client.stream(method, url, **stream_kwargs) as response:
                body, truncated = _read_capped_body(response, max_bytes)
                content_type = response.headers.get("content-type", "")
                status = response.status_code
            if truncated:
                logger.warning(
                    "guarded_fetch: response body exceeded the %d-byte cap — "
                    "truncated at cap (over-large host response, not an error)",
                    max_bytes,
                )
            return status, body, content_type, truncated
    except (egress_guard.EgressTripped, egress_guard.EgressDenied) as exc:
        logger.critical(
            "guarded_fetch: egress guard refused the fetch (latch/allowlist) — %s",
            exc,
        )
        raise _RawFetchError(f"egress guard refused: {exc}") from exc
    except httpx.TimeoutException as exc:
        logger.warning("guarded_fetch: fetch timed out for a URL (purpose-bound) — denied")
        raise _RawFetchError("fetch timed out") from exc
    except httpx.HTTPError as exc:
        logger.warning("guarded_fetch: HTTP error during fetch (%s) — denied", type(exc).__name__)
        raise _RawFetchError(f"http error: {type(exc).__name__}") from exc
    finally:
        # ALWAYS narrow the allowlist back (and drop this host's resolution pins) —
        # the per-fetch window closes here, even on exception/timeout/trip.
        egress_guard.revoke_external_endpoint(host, port)
        logger.warning(
            "guarded_fetch: REVOKE egress allowlist for host=%r port=%d (fetch window closed)",
            host, port,
        )


def _fetch_body(
    target: _ValidatedTarget,
    url: str,
    timeout_s: float,
    *,
    authorization: Optional[str] = None,
    method: str = "GET",
    json_body: Optional[dict] = None,
) -> FetchResult:
    """Fetch a TEXT body through the shared :func:`_fetch_raw` core + charset decode.

    A thin wrapper over :func:`_fetch_raw` (which owns the widen/stream/cap/revoke
    transport): it fetches the raw bytes capped at ``_MAX_BODY_BYTES`` and decodes
    them by the DECLARED charset (:func:`_decode_body`), returning the UNCHANGED
    frozen :class:`FetchResult` contract. The always-runs ``finally`` revoke lives in
    :func:`_fetch_raw`, so the door's "the widen is ALWAYS narrowed back" guarantee is
    preserved exactly. Any raw-fetch failure (:class:`_RawFetchError`) is mapped to a
    denied :class:`FetchResult`; this never raises. ``method`` / ``json_body`` (#724)
    default to the historical GET-no-body shape and are forwarded to
    :func:`_fetch_raw` for the Kagi-v1 POST consumer.
    """
    try:
        status, body, content_type, _truncated = _fetch_raw(
            target,
            url,
            timeout_s,
            max_bytes=_MAX_BODY_BYTES,
            authorization=authorization,
            method=method,
            json_body=json_body,
        )
    except _RawFetchError as exc:
        return FetchResult(url=url, denied_reason=exc.denied_reason)

    # httpx parses the response's encoding off the header; the streamed body was read
    # outside the response context, so reproduce httpx's resolution exactly to keep the
    # frozen text path byte-identical to the pre-refactor behavior. ``Response.encoding``
    # is "the declared charset IF it is a KNOWN codec, ELSE 'utf-8'" (and NEVER None).
    # ``_decode_body`` already tries the header's declared charset as its FIRST candidate,
    # so the ONLY thing httpx's encoding still contributes is the utf-8 fallback for an
    # absent OR unknown declared charset — pass a literal "utf-8" for that.  (Passing
    # ``_charset_from_content_type(ct)`` here would be a no-op dup of candidate 1 and, for
    # a PRESENT-but-unknown charset like ``x-unknown-garbage``, would drop the utf-8
    # candidate entirely and let a conflicting page <meta> win — a real divergence.)
    text = _decode_body(body, content_type, "utf-8")
    return FetchResult(
        url=url,
        status=status,
        content_text=text,
        content_type=content_type,
        denied_reason=None,
    )


# ---------------------------------------------------------------------------
# Binary content validation (UC-003 Workstream B) — MIME allowlist + magic bytes.
# ---------------------------------------------------------------------------


def _mime_from_content_type(content_type_header: str) -> str:
    """Extract the bare lowercase MIME type from a Content-Type header value.

    Strips any ``; charset=...`` / ``; boundary=...`` parameters and whitespace and
    lowercases the result. ``"Image/PNG; charset=binary"`` -> ``"image/png"``;
    ``""`` -> ``""``. Never raises — a non-``str`` header (bytes/int/None) coerces
    to ``""`` (which the allowlist then refuses), upholding the fail-closed
    "never raises" contract of the validators that delegate here.
    """
    if not isinstance(content_type_header, str) or not content_type_header:
        return ""
    return content_type_header.split(";", 1)[0].strip().lower()


def _validate_binary_content(
    content_type_header: str, body: bytes
) -> tuple[bool, str, Optional[str]]:
    """Validate a fetched image body. Returns ``(ok, mime, denied_reason)``.

    Fail-closed image gate for :func:`fetch_external_binary` — the BINARY analogue of
    the text door's injection scan, but a HARD gate (refuse), not an annotate. Exactly
    one of the two outcomes holds:

      * ACCEPT -> ``(True, mime, None)`` where ``mime`` is the validated, allowlisted
        lowercase MIME (``image/png`` etc.).
      * REFUSE -> ``(False, "", reason)`` where ``reason`` is a short, log-safe label.

    The checks, in order (all fail-closed):
      1. **Empty body** -> refuse (nothing to display; a 0-byte image is a smell).
      2. **MIME allowlist** — the bare MIME parsed off the header must be in
         :data:`IMAGE_CONTENT_TYPE_ALLOWLIST`. SVG (``image/svg+xml``) and anything
         else is refused. SVG is called out explicitly: it is an XML/script-bearing
         vector format, NOT a safe display-only raster.
      3. **Magic-byte sniff** — the first bytes of the body must match the declared
         MIME's signature (:data:`_IMAGE_MAGIC_PREFIXES` / the WEBP RIFF markers). A
         header/body MISMATCH (a ``image/png`` header over JPEG/HTML/SVG bytes) is
         refused — the header is attacker-controlled, so the bytes must agree.

    NO full image decode happens here (no Pillow / no pixel parse) — only a header
    sniff. Dimension filtering (:data:`MIN_IMAGE_DIMENSION_PX`) is a downstream
    concern; this door enforces the byte cap (via :func:`_fetch_raw`) + the format
    gate only.
    """
    if not body:
        return False, "", "empty image body"

    mime = _mime_from_content_type(content_type_header)

    # Explicit SVG refusal — called out for clarity even though it is simply not in
    # the allowlist. SVG is XML and can carry <script> / external refs; it is never a
    # display-only raster.
    if mime == "image/svg+xml" or mime.startswith("image/svg"):
        return False, "", "SVG is refused (script-bearing vector format)"

    if mime not in IMAGE_CONTENT_TYPE_ALLOWLIST:
        return False, "", f"content-type {mime!r} not in the image allowlist"

    # Magic-byte sniff — the body's signature must match the DECLARED MIME. The header
    # alone is attacker-controlled, so a header claiming PNG over non-PNG bytes is a
    # spoof and is refused. Sniff at most the first 12 bytes.
    head = body[:12]

    if mime == "image/webp":
        # WEBP is a RIFF container with a split signature: bytes[0:4] == b"RIFF" AND
        # bytes[8:12] == b"WEBP" (bytes[4:8] are the chunk size, not matched).
        if len(head) >= 12 and head[0:4] == _WEBP_RIFF_MARKER and head[8:12] == _WEBP_FORMAT_MARKER:
            return True, mime, None
        return False, "", "image body does not match the declared WEBP signature"

    expected_prefixes = _IMAGE_MAGIC_PREFIXES.get(mime, ())
    for prefix in expected_prefixes:
        if head.startswith(prefix):
            return True, mime, None
    return False, "", f"image body does not match the declared {mime!r} signature"


def validate_image_content(
    content_type_header: str, body: bytes
) -> tuple[bool, str, Optional[str]]:
    """Public at-rest re-validation entry point (UC-003 Workstream B, #6).

    Defense-in-depth for consumers OUTSIDE the fetch path — specifically the AO
    knowledge bank, which re-sniffs an image's bytes against its claimed MIME at
    STORE time.  That is a DIFFERENT trust domain than the fetch-time gate: the
    door validated the bytes as they came off the wire, but the store boundary
    receives them off an on-disk staging blob plus a host-supplied frame label,
    so it must NOT trust the label — it re-runs the same gate.

    Delegates to the door's single validator (:func:`_validate_binary_content`)
    so the MIME allowlist + magic-byte table never forks into a second copy that
    can drift.  Returns ``(ok, mime, denied_reason)`` exactly as the internal
    validator does: ACCEPT -> ``(True, validated_mime, None)``; REFUSE ->
    ``(False, "", reason)``.
    """
    return _validate_binary_content(content_type_header, body)


# ---------------------------------------------------------------------------
# Header-only image dimensions (UC-003 Workstream B, #7) — NO full decode.
# The MIN_IMAGE_DIMENSION_PX floor finally gets a consumer: a pure byte-slicing
# read of the format header (no Pillow / no pixel decode) so the downstream
# coordinator can drop decorative spacers / tracking pixels.  Every parser is
# fail-closed-to-None on a short / malformed buffer and never raises.
# ---------------------------------------------------------------------------


def _png_dimensions(body: bytes) -> Optional[tuple[int, int]]:
    """PNG: 8-byte signature, then IHDR ``[len(4)][b"IHDR"][W(4 BE)][H(4 BE)]``."""
    if len(body) < 24 or body[12:16] != b"IHDR":
        return None
    width = int.from_bytes(body[16:20], "big")
    height = int.from_bytes(body[20:24], "big")
    return (width, height)


def _gif_dimensions(body: bytes) -> Optional[tuple[int, int]]:
    """GIF: ``GIF87a``/``GIF89a`` (6) then the Logical Screen Descriptor (W,H LE)."""
    if len(body) < 10 or body[0:6] not in (b"GIF87a", b"GIF89a"):
        return None
    width = int.from_bytes(body[6:8], "little")
    height = int.from_bytes(body[8:10], "little")
    return (width, height)


def _jpeg_dimensions(body: bytes) -> Optional[tuple[int, int]]:
    """JPEG: walk marker segments from SOI to the first Start-Of-Frame.

    The SOFn markers (0xC0..0xCF) carry ``[precision(1)][height(2 BE)][width(2
    BE)]`` — EXCLUDING DHT (0xC4) / JPG (0xC8) / DAC (0xCC), which are not frame
    headers.  The walk is hard-bounded and fail-closed (None) on any
    misalignment or truncation.
    """
    n = len(body)
    if n < 4 or body[0] != 0xFF or body[1] != 0xD8:
        return None
    i = 2
    for _ in range(512):  # hard iteration bound — a malformed stream can't loop
        if i >= n or body[i] != 0xFF:
            return None
        while i < n and body[i] == 0xFF:  # skip 0xFF fill bytes between markers
            i += 1
        if i >= n:
            return None
        marker = body[i]
        i += 1
        # Standalone markers carry NO length payload: TEM (0x01), RSTn
        # (0xD0-0xD7), SOI (0xD8), EOI (0xD9).
        if marker == 0x01 or 0xD0 <= marker <= 0xD9:
            continue
        if i + 2 > n:
            return None
        seg_len = int.from_bytes(body[i:i + 2], "big")
        if seg_len < 2 or i + seg_len > n:
            return None
        if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):
            if seg_len < 7:
                return None
            height = int.from_bytes(body[i + 3:i + 5], "big")
            width = int.from_bytes(body[i + 5:i + 7], "big")
            return (width, height)
        i += seg_len
    return None


def _webp_dimensions(body: bytes) -> Optional[tuple[int, int]]:
    """WEBP: RIFF container (``RIFF``....``WEBP``) with a per-codec dim layout."""
    if (
        len(body) < 16
        or body[0:4] != _WEBP_RIFF_MARKER
        or body[8:12] != _WEBP_FORMAT_MARKER
    ):
        return None
    fourcc = body[12:16]
    if fourcc == b"VP8 ":  # lossy: 14-bit dims after the 0x9D 0x01 0x2A start code
        if len(body) < 30:
            return None
        width = int.from_bytes(body[26:28], "little") & 0x3FFF
        height = int.from_bytes(body[28:30], "little") & 0x3FFF
        return (width, height)
    if fourcc == b"VP8L":  # lossless: 14+14 bits packed after the 0x2F sig byte
        if len(body) < 25:
            return None
        bits = int.from_bytes(body[21:25], "little")
        width = (bits & 0x3FFF) + 1
        height = ((bits >> 14) & 0x3FFF) + 1
        return (width, height)
    if fourcc == b"VP8X":  # extended: 24-bit canvas (W-1, H-1) little-endian
        if len(body) < 30:
            return None
        width = int.from_bytes(body[24:27], "little") + 1
        height = int.from_bytes(body[27:30], "little") + 1
        return (width, height)
    return None


def image_dimensions(mime: str, body: bytes) -> Optional[tuple[int, int]]:
    """Header-only ``(width, height)`` for an allowlisted raster — no full decode.

    Pure byte inspection (no Pillow / no image lib): reads width/height out of the
    format header for PNG / JPEG / GIF / WEBP.  Returns ``None`` for an unknown
    MIME or any truncated / malformed header (fail-closed to "unknown", NOT to a
    dropped image — see :func:`dimension_below_min`).  Never raises.
    """
    try:
        m = _mime_from_content_type(mime)
        if m == "image/png":
            return _png_dimensions(body)
        if m == "image/jpeg":
            return _jpeg_dimensions(body)
        if m == "image/gif":
            return _gif_dimensions(body)
        if m == "image/webp":
            return _webp_dimensions(body)
    except (IndexError, ValueError, TypeError, AttributeError):  # any mishap -> unknown
        return None
    return None


def dimension_below_min(
    mime: str, body: bytes, min_px: int = MIN_IMAGE_DIMENSION_PX
) -> bool:
    """True iff a READABLE header reports EITHER dimension below *min_px*.

    Drops decorative spacers / tracking pixels (the
    :data:`MIN_IMAGE_DIMENSION_PX` floor).  An UNREADABLE header returns
    ``False`` (do NOT drop): the MIME-allowlist + magic-byte gate already proved
    the format, and silently dropping a validated image on a header-parse miss
    would quietly lower what the live feature can display — a capability change
    that is the LA's call, not this helper's.  Header-only; never raises.
    """
    dims = image_dimensions(mime, body)
    if dims is None:
        return False
    width, height = dims
    return width < min_px or height < min_px


def dimension_above_max(
    mime: str,
    body: bytes,
    *,
    max_px: int = MAX_IMAGE_DIMENSION_PX,
    max_pixels: int = MAX_IMAGE_PIXELS,
) -> bool:
    """True iff a READABLE header reports dimensions over the decompression-bomb
    ceiling (W1 / BED-3).

    Returns True when the larger edge exceeds *max_px* OR the pixel AREA
    (width*height) exceeds *max_pixels* — the two ways a small compressed image
    can decode to an enormous bitmap.  Both bounds are INCLUSIVE (exactly at the
    ceiling is permitted; one pixel over is refused).  Header-only via
    :func:`image_dimensions` — NO decode (decoding to measure would BE the
    attack).

    An UNREADABLE header returns ``False`` here: this is the AFFIRMATIVE
    "is it provably too big?" predicate, used by the at-rest store boundary
    (:meth:`knowledge_bank.store_image`) where the magic-byte gate already
    proved the format.  The COORDINATOR's drop gate
    (:func:`image_dimensions_ok`) is the one that fails an unreadable header
    CLOSED (drop) — there, a header we cannot measure cannot be proven under the
    ceiling, so it is refused.  Never raises.
    """
    dims = image_dimensions(mime, body)
    if dims is None:
        return False
    width, height = dims
    return max(width, height) > max_px or width * height > max_pixels


def image_dimensions_ok(mime: str, body: bytes) -> bool:
    """The single coordinator-side dimension gate — fail-closed (W1 + W3 + min).

    Returns True iff the image's header is READABLE **and** its dimensions sit
    within the accepted band:

      * READABLE — :func:`image_dimensions` returns a ``(w, h)`` (not ``None``).
        An UNREADABLE / malformed header → ``False`` (DROP): we cannot prove the
        image is under the decompression-bomb ceiling, so we refuse to keep it
        (TD-4, LA-locked 2026-06-15 — this DROPS what the prior keep-not-drop
        posture kept; the magic-byte gate proves the FORMAT, not the SIZE).
      * NOT below the :data:`MIN_IMAGE_DIMENSION_PX` floor (decorative spacers /
        tracking pixels drop).
      * NOT above the :data:`MAX_IMAGE_DIMENSION_PX` / :data:`MAX_IMAGE_PIXELS`
        ceiling (decompression bombs drop).

    Equivalent to ``image_dimensions(...) is not None and not
    dimension_below_min(...) and not dimension_above_max(...)`` but reads the
    header ONCE.  Header-only; never raises.  ``True`` → keep + display;
    ``False`` → drop to the alt placeholder.
    """
    dims = image_dimensions(mime, body)
    if dims is None:
        return False  # W3 / TD-4 — unreadable header fails CLOSED (drop)
    width, height = dims
    if width < MIN_IMAGE_DIMENSION_PX or height < MIN_IMAGE_DIMENSION_PX:
        return False  # below the min floor (spacer / tracking pixel)
    if max(width, height) > MAX_IMAGE_DIMENSION_PX or width * height > MAX_IMAGE_PIXELS:
        return False  # over the decompression-bomb ceiling
    return True


# A test seam: an injected httpx transport (httpx.MockTransport) so the test suite
# can exercise the full pipeline with ZERO real sockets/DNS. None in production ->
# httpx's default transport. Set only via the test-only context manager below.
_test_transport: Optional[httpx.BaseTransport] = None
_test_transport_lock = threading.Lock()


def _active_transport() -> Optional[httpx.BaseTransport]:
    with _test_transport_lock:
        return _test_transport


def _set_test_transport(transport: Optional[httpx.BaseTransport]) -> None:
    """TEST-ONLY: inject an ``httpx`` transport (a ``MockTransport``) for the fetch.

    Lets the test suite drive the full pipeline without any real socket or DNS.
    Production never calls this; the default transport (``None``) is httpx's real
    one — which, under the armed egress guard, is itself constrained to the one
    widened host. Resetting to ``None`` restores production behaviour.
    """
    global _test_transport
    with _test_transport_lock:
        _test_transport = transport


# ---------------------------------------------------------------------------
# Step 4 — injection scan (annotate, never silently pass).
# ---------------------------------------------------------------------------


def _scan_and_annotate(result: FetchResult) -> FetchResult:
    """Run the ADR-013 Layer-2 injection scanner on a fetched body.

    A flagged body is logged at WARNING and the flags are recorded on the returned
    :class:`FetchResult` (``injection_flags`` — merge-gate fix 3); the body is NOT
    blocked (the scan is a defense-in-depth WARNING signal, matching the gateway
    document-loader's contract — heuristics false-positive, and the deterministic
    egress-side control is the exfil screen, not this inbound scan). The body text is
    returned unchanged so the caller (UC-003 cleaner) can apply its own handling now
    that it can SEE the flags, not only read them in the log.
    """
    if result.denied_reason is not None or not result.content_text:
        return result
    try:
        flags = scan_for_injection(result.content_text)
    except Exception as exc:  # noqa: BLE001 — a scanner failure must not silently pass
        logger.warning("guarded_fetch: injection scan errored (%s) — body returned, flagged", type(exc).__name__)
        return result
    if flags:
        logger.warning(
            "guarded_fetch: fetched body matched %d prompt-injection heuristic(s): %s",
            len(flags), "; ".join(flags),
        )
        return replace(result, injection_flags=tuple(flags))
    return result


# ---------------------------------------------------------------------------
# The public entry point — the one door.
# ---------------------------------------------------------------------------


def fetch_external(
    url: str,
    *,
    purpose: str,
    timeout_s: float = 30.0,
    authorization: Optional[str] = None,
    method: str = "GET",
    json_body: Optional[dict] = None,
) -> FetchResult:
    """Fetch an external URL through the one Policy-Agent-gated door. Fail-closed.

    FROZEN CONTRACT (Vikunja #577 c.1029; the keyword-only ``authorization``
    parameter is a PURELY ADDITIVE #719 extension, and ``method`` / ``json_body``
    are the same-shape PURELY ADDITIVE #724 extension — every pre-existing call
    shape and its wire behaviour are byte-identical, defaulting to GET-no-body).
    The single sanctioned path for external HTTP fetching in the BlarAI runtime.
    Runs the strictly-ordered pipeline (SSRF guard -> PA adjudication -> resolution
    recheck -> charset-correct fetch -> injection scan); every failure/ambiguous
    path returns a denied :class:`FetchResult` (``denied_reason`` set) rather than
    raising or fetching. The method/body choice does NOT change the pipeline — it
    only changes the single httpx call after the pipeline permits the fetch.

    Args:
        url: the absolute https URL to fetch. Validated by the SSRF guard first.
        purpose: a short, caller-supplied label of WHY the fetch is happening
            (e.g. ``"uc003-url-ingest"``). Passed to the PA adjudicator and the
            ESCALATE consent context — a descriptor, never raw payload.
        timeout_s: the read timeout (connect timeout is fixed at 10s). Defaults 30s.
        authorization: OPTIONAL ``Authorization`` header VALUE for an
            authenticated API endpoint (#719 / ADR-024 W4 — the Kagi Search
            API's ``"Bearer <key>"`` is the first consumer). Applied ONLY after
            the full pipeline (SSRF guard + PA adjudication + resolution
            recheck) permits the fetch. SECRET: the value is placed in the
            request headers and nowhere else — never logged, never echoed
            into a result. ``None`` (default) sends no such header.
        method: the HTTP method (#724). Defaults ``"GET"`` — byte-identical to
            every pre-existing caller. ``"POST"`` for the Kagi v1 JSON API.
        json_body: OPTIONAL JSON request body (#724 — the Kagi v1 ``{"query": ...}``
            POST body). ``None`` (default) sends NO request body, the historical
            wire shape. When set, httpx serialises it and adds the
            ``Content-Type: application/json`` request header; the response is
            still bounded by the streaming byte cap.

    Returns:
        A :class:`FetchResult`. ``denied_reason is None`` iff the fetch was permitted
        and completed; otherwise the body fields are empty and ``denied_reason`` is a
        short, log-safe label of why it was refused.
    """
    safe_purpose = str(purpose or "").strip() or "unspecified"

    # Step 1 — SSRF guard.
    target, reason = _validate_url(url)
    if target is None:
        logger.warning("guarded_fetch: URL refused by SSRF guard (%s)", reason)
        return FetchResult(url=str(url), denied_reason=f"SSRF guard: {reason}")

    # Step 2 — Policy-Agent adjudication (+ ESCALATE consent).
    verdict, deny_reason = _adjudicate(url, safe_purpose)
    if verdict is not Verdict.ALLOW:
        return FetchResult(url=url, denied_reason=f"policy: {deny_reason}")

    # Step 2.5 — named-host resolution recheck (SSRF defense-in-depth). Resolve the
    # host ONCE before any widen/fetch; refuse the whole fetch if it resolves to an
    # internal/special address (a NAMED host pointed at 169.254.169.254 / 127.0.0.1 /
    # an RFC-1918 IP). No widen, no fetch — the allowlist is never touched.
    resolution_reason = _resolution_blocked_reason(target)
    if resolution_reason is not None:
        return FetchResult(url=url, denied_reason=f"SSRF guard: {resolution_reason}")

    # Step 3 — charset-correct fetch (allowlist widen/revoke around httpx).
    result = _fetch_body(
        target,
        url,
        timeout_s,
        authorization=authorization,
        method=method,
        json_body=json_body,
    )

    # Step 4 — injection scan on the returned text.
    return _scan_and_annotate(result)


def fetch_external_binary(
    url: str,
    *,
    purpose: str,
    timeout_s: float = 30.0,
    max_bytes: int = MAX_IMAGE_BYTES,
) -> BinaryFetchResult:
    """Fetch an external IMAGE through the same one PA-gated door, in BINARY mode.

    UC-003 Workstream B (display-only images). The BINARY sibling of
    :func:`fetch_external`: it runs the IDENTICAL strictly-ordered, fail-closed
    pipeline — SSRF guard -> PA adjudication (+ ESCALATE consent) -> named-host
    resolution recheck -> the shared :func:`_fetch_raw` transport core (widen / stream
    / cap / always-revoke) — then, INSTEAD of a text decode + injection scan, runs
    :func:`_validate_binary_content` (MIME allowlist + magic-byte sniff, SVG refused).
    The text injection scan is SKIPPED on purpose: image bytes are not text, so the
    ADR-013 heuristic scanner has nothing to scan.

    WELDED (UC-003 Workstream B), independently of the text door: every call DENIES
    at Step 2 whenever no adjudicator is registered (the fail-closed default) OR the
    registered adjudicator refuses the purpose — and the production adjudicator
    hard-denies ``uc003-image-ingest`` by BED-1 purpose-deny, so a text-door go-live
    does NOT open this path. ``[knowledge].images_enabled`` gates it separately.
    Opening it takes an LA-reviewed ceremony that lifts the purpose-deny AND flips
    that flag. This function does NOT flip any lock.

    Every failure/ambiguous path returns a denied :class:`BinaryFetchResult`
    (``denied_reason`` set, body fields empty) rather than raising or fetching —
    identical fail-closed posture to :func:`fetch_external`.

    Args:
        url: the absolute https URL of the image. Validated by the SSRF guard first.
        purpose: a short, caller-supplied label of WHY the fetch is happening
            (e.g. ``"uc003-image-ingest"``). Passed to the PA adjudicator and the
            ESCALATE consent context — a descriptor, never raw payload.
        timeout_s: the read timeout (connect timeout is fixed at 10s). Defaults 30s.
        max_bytes: the per-image byte cap. Defaults :data:`MAX_IMAGE_BYTES` (2 MiB);
            an over-cap image is truncated-at-cap (``truncated=True``), not an error.

    Returns:
        A :class:`BinaryFetchResult`. ``denied_reason is None`` iff the fetch was
        permitted, completed, AND the bytes validated as an allowlisted image format;
        otherwise the body fields are empty and ``denied_reason`` is a short, log-safe
        label of why it was refused.
    """
    safe_purpose = str(purpose or "").strip() or "unspecified"

    # Step 1 — SSRF guard.
    target, reason = _validate_url(url)
    if target is None:
        logger.warning("guarded_fetch: image URL refused by SSRF guard (%s)", reason)
        return BinaryFetchResult(url=str(url), denied_reason=f"SSRF guard: {reason}")

    # Step 2 — Policy-Agent adjudication (+ ESCALATE consent). DENIES when no
    # adjudicator is registered (the fail-closed default) AND when the registered
    # one refuses the purpose — the production adjudicator purpose-denies image
    # ingest (BED-1), so this holds even after the text door goes live.
    verdict, deny_reason = _adjudicate(url, safe_purpose)
    if verdict is not Verdict.ALLOW:
        return BinaryFetchResult(url=url, denied_reason=f"policy: {deny_reason}")

    # Step 2.5 — named-host resolution recheck (SSRF defense-in-depth), identical to
    # the text door: refuse if the host resolves to an internal/special address.
    resolution_reason = _resolution_blocked_reason(target)
    if resolution_reason is not None:
        return BinaryFetchResult(url=url, denied_reason=f"SSRF guard: {resolution_reason}")

    # Step 3 — RAW fetch through the shared transport core (widen/stream/cap/revoke),
    # capped at the per-image byte budget. NO text decode.
    try:
        status, body, content_type, truncated = _fetch_raw(
            target, url, timeout_s, max_bytes=max_bytes
        )
    except _RawFetchError as exc:
        return BinaryFetchResult(url=url, denied_reason=exc.denied_reason)

    # Step 4 — binary content validation (MIME allowlist + magic-byte sniff; SVG
    # refused). A refusal here is a HARD deny (unlike the text path's annotate-only
    # injection scan) — a body that is not a recognised, allowlisted image format must
    # not reach storage/display.
    ok, mime, denied_reason = _validate_binary_content(content_type, body)
    if not ok:
        logger.warning(
            "guarded_fetch: image content rejected by the binary validator (%s)",
            denied_reason,
        )
        return BinaryFetchResult(url=url, denied_reason=f"content: {denied_reason}")

    return BinaryFetchResult(
        url=url,
        status=status,
        content_bytes=body,
        content_type=content_type,
        mime=mime,
        truncated=truncated,
        denied_reason=None,
    )
