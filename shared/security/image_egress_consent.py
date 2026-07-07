r"""Off-site image-egress consent — the coarse per-article privacy gate (UC-003 #663).

When UC-003 displays the images inside an ingested article, SAME-SITE images (an
``<img>`` whose host equals the article's host) ride the operator's existing
``/ingest`` consent — fetching the page's own images is implied by choosing to
ingest the page.  OFF-SITE images (a different host — a CDN, an ad/analytics
network, a third-party tracking beacon) are a SEPARATE privacy decision: fetching
one reaches out to a host the operator did not choose, leaking "this person is
reading this article" to that third party.

CD-1 (LA-locked, 2026-06-15) sets the grain: the box owns the *danger* (the
decode-time technical controls — SSRF, MIME allowlist, magic bytes, the
decompression-bomb ceiling, the byte caps), and the human owns *egress/privacy*
ONLY, at the COARSEST meaningful grain — **one per-article yes/no** for "fetch
this article's off-site images?".  NOT a per-host vetting list (a chore that
becomes a rubber-stamp — explicitly rejected, ADR-032 / #663 c.1088).

This module is the **consumer seam**, modelled exactly on
:mod:`shared.security.escalation_consent` (the ESCALATE human-review seam):

  * :class:`ImageEgressConsentContext` — the SAFE descriptor surfaced to the
    operator: the article's host + the DISTINCT off-site host list + an opaque
    document label.  Hosts ONLY — never an image URL with its path/query (a
    tracking token lives in the query), never payload.
  * :class:`ImageEgressConsentResult` — ``approved`` + verifier identity + reason.
    ``approved is True`` is the ONLY thing that permits an off-site fetch.
  * :class:`ImageEgressConsentVerifier` — the operator-surface Protocol
    (``verify(context) -> result``).  The WinUI yes/no prompt (Pass B) implements
    it; until one is wired NOTHING is registered → every off-site fetch is DENIED.
  * :func:`register_image_egress_verifier` / :func:`clear_image_egress_verifier` /
    :func:`active_image_egress_verifier` — the single-verifier registry.
  * :func:`request_image_egress_consent` — the one call the coordinator makes.
    **Fail-closed**: no verifier / exception / timeout / malformed result →
    DENIED (off-site images drop to placeholders, never fetched).

It also owns the SAME-SITE grain itself (:func:`same_site` / :func:`host_from_url`)
so "what counts as same-site" lives in ONE upgradable place.  This pass uses an
EXACT host match (case-insensitive, trailing-dot-normalised) — NO eTLD+1 /
registrable-domain / public-suffix-list logic (which would need a PSL dependency
and a "is ``cdn.example.com`` the same site as ``example.com``?" policy call).
The eTLD+1 question is teed up for the LA before Pass B; upgrading the grain is a
one-function change here.

This is a DEDICATED module rather than reusing the escalation-consent registry on
purpose: off-site-image egress and PA ESCALATE are two DIFFERENT operator
questions with two DIFFERENT prompts (the WinUI image-consent dialog vs. the
Windows-Hello escalation prompt), so they get independent single-verifier
registries — a verifier wired for one must never silently answer the other.

Design constraints (match the rest of ``shared/security/``):
  * **No external network. No new dependencies** (stdlib only).
  * **Importing this module has no side effects** — no verifier is registered.
    With none wired the behaviour is byte-for-byte the dormant default (every
    off-site image denied), so building this changes nothing at rest.
  * **Fail-Closed everywhere:** the safe state is DENY.  Absent verifier → DENY.
    Timeout → DENY.  Exception → DENY.  ``None`` / malformed result → DENY.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from typing import Optional, Protocol, runtime_checkable
from urllib.parse import urlsplit

logger = logging.getLogger(__name__)


# Bounded wait for the operator's answer (mirrors escalation_consent): a wedged or
# absent prompt surface must never hang the ingest turn — on expiry the off-site
# fetch is DENIED (fail-closed).  A console operator answers in seconds; this is
# the backstop for a hung surface, not the expected path.
DEFAULT_IMAGE_CONSENT_TIMEOUT_S: float = 120.0

# Identity used when no verifier is configured (the dormant default deny path).
_NO_VERIFIER_IDENTITY: str = "no-verifier"


# ---------------------------------------------------------------------------
# Same-site grain — the ONE upgradable place (exact host match for this pass).
# ---------------------------------------------------------------------------


def host_from_url(url: str) -> Optional[str]:
    """The normalised host of an absolute URL, or ``None`` if it has none.

    Normalisation: lowercase + strip a trailing dot (``Example.COM.`` ->
    ``example.com``).  Returns ``None`` for a relative URL, a ``data:`` URI, an
    unparseable string, or anything with no host component — the coordinator
    treats a ``None`` host as unclassifiable and (fail-closed) never fetches it.
    Never raises.
    """
    if not isinstance(url, str) or not url.strip():
        return None
    try:
        host = urlsplit(url.strip()).hostname
    except ValueError:
        return None
    if not host:
        return None
    host = host.strip().rstrip(".").lower()
    return host or None


def same_site(article_host: Optional[str], ref_host: Optional[str]) -> bool:
    """True iff *ref_host* is the SAME SITE as *article_host* — the consent grain.

    THE GRAIN (this pass): an EXACT host match, case-insensitive and
    trailing-dot-normalised.  ``images.example.com`` is NOT same-site as
    ``example.com`` here — deliberately strict, so a third-party-looking subdomain
    is treated as off-site (consent-gated) rather than waved through.  Upgrading
    to registrable-domain / eTLD+1 (so first-party subdomains ride the same
    consent) is a future LA decision; it changes ONLY this function.

    Fail-closed: a ``None`` on either side (an article with no determinable host,
    or a ref whose host could not be parsed) is NEVER same-site — the caller then
    routes it through off-site consent (or drops it).
    """
    if not article_host or not ref_host:
        return False
    return article_host.strip().rstrip(".").lower() == ref_host.strip().rstrip(".").lower()


# ---------------------------------------------------------------------------
# Safe descriptor + result shapes (host descriptors only — never a URL/payload)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ImageEgressConsentContext:
    """The SAFE descriptor of an off-site image-egress decision (hosts only).

    Carries **host descriptors only — never an image URL** (a path/query can hold
    a per-recipient tracking token) and never payload.  Sufficient for the
    operator to make the coarse per-article call: "this article wants to load
    images from these other hosts — fetch them?".

    ``offsite_hosts`` is the DISTINCT, ordered list of off-site hosts the article
    references — for disclosure in the prompt, NOT an actionable per-host vetting
    list (the answer is ONE boolean for the whole article; ADR-032 / #663 c.1088).
    """

    article_host: str
    """The host of the article being ingested (the site the operator already
    chose).  A host, not the full URL."""

    offsite_hosts: tuple[str, ...] = field(default_factory=tuple)
    """The DISTINCT off-site hosts this article's images reference (sorted, for a
    stable prompt).  Hosts only — for disclosure, not per-host actioning."""

    doc_label: str = ""
    """An opaque, content-independent document handle (e.g. the doc_uuid prefix)
    for the audit record — never a content digest / title / URL."""

    def describe(self) -> str:
        """A one-line operator/audit description (host descriptors only)."""
        hosts = ", ".join(self.offsite_hosts) or "(none)"
        label = f" [{self.doc_label}]" if self.doc_label else ""
        return f"off-site image egress for article {self.article_host}{label}: {hosts}"


@dataclass(frozen=True)
class ImageEgressConsentResult:
    """The outcome of an off-site image-egress consent request.

    ``approved`` is the load-bearing field: **True permits the article's off-site
    image fetches; anything else means DENY** (the off-site images drop to
    placeholders).  A denied/fail-closed result still carries the verifier
    identity + a reason for the audit record.
    """

    approved: bool
    verifier_identity: str = _NO_VERIFIER_IDENTITY
    reason: str = ""

    @classmethod
    def deny(cls, reason: str, *, verifier_identity: str = _NO_VERIFIER_IDENTITY) -> "ImageEgressConsentResult":
        """Construct a fail-closed DENY result with a reason."""
        return cls(approved=False, verifier_identity=verifier_identity, reason=reason)

    @classmethod
    def allow(cls, *, verifier_identity: str, reason: str = "operator approved") -> "ImageEgressConsentResult":
        """Construct an APPROVED result. Only an operator surface should call this."""
        return cls(approved=True, verifier_identity=verifier_identity, reason=reason)


@runtime_checkable
class ImageEgressConsentVerifier(Protocol):
    """The contract an operator off-site-image-consent surface implements.

    Given the SAFE :class:`ImageEgressConsentContext`, return an
    :class:`ImageEgressConsentResult` — synchronously.  It is the human-in-the-loop
    for the COARSE per-article off-site decision; it MUST NOT itself fetch
    anything, only decide whether the article's off-site images may be fetched.

    Fail-closed contract: a verifier that cannot obtain an answer SHOULD return a
    denied result rather than raise.  :func:`request_image_egress_consent`
    additionally treats any raised exception, a ``None`` return, a timeout, or a
    non-:class:`ImageEgressConsentResult` return as DENY.

    Implementation: the WinUI per-article yes/no dialog (UC-003 Pass B) — NOT in
    this pass.  Until it is wired via :func:`register_image_egress_verifier`,
    NOTHING is registered and every off-site fetch fails closed (denied).
    """

    def verify(self, context: ImageEgressConsentContext) -> ImageEgressConsentResult:
        """Surface ``context`` and return the operator's approve/deny answer.

        MUST be synchronous (the caller blocks on it). SHOULD fail closed.
        """
        ...


# ---------------------------------------------------------------------------
# Single-verifier registry (the integration seam) — dormant by default
# ---------------------------------------------------------------------------

_verifier: Optional[ImageEgressConsentVerifier] = None
_verifier_lock = threading.Lock()


def register_image_egress_verifier(verifier: ImageEgressConsentVerifier) -> None:
    """Register the operator off-site-image-consent verifier (the integration seam).

    INTERFACE ANCHOR.  The WinUI image-consent surface (Pass B) calls this once at
    startup.  With a verifier registered, :func:`request_image_egress_consent`
    consults it; with none registered (the default), every off-site fetch is
    DENIED — the dormant posture.  Single-verifier: registering replaces any prior
    one.  Registering does not by itself permit anything.

    :raises TypeError: if *verifier* has no callable ``verify`` method.
    """
    if not hasattr(verifier, "verify") or not callable(getattr(verifier, "verify")):
        raise TypeError(
            "register_image_egress_verifier requires an ImageEgressConsentVerifier "
            "(a verify(context) method)"
        )
    global _verifier
    with _verifier_lock:
        _verifier = verifier
    logger.info(
        "Image-egress consent: verifier registered (%s) — off-site article images "
        "now route to per-article operator consent.",
        type(verifier).__name__,
    )


def clear_image_egress_verifier() -> None:
    """Unregister the verifier — return to the dormant deny-every-off-site default.

    Used at shutdown and by tests (so an injected mock does not leak across tests).
    """
    global _verifier
    with _verifier_lock:
        _verifier = None


def active_image_egress_verifier() -> Optional[ImageEgressConsentVerifier]:
    """Return the currently-registered verifier, or ``None`` if none is wired."""
    with _verifier_lock:
        return _verifier


# ---------------------------------------------------------------------------
# The consumer entry point — the one call the ingest coordinator makes
# ---------------------------------------------------------------------------


def request_image_egress_consent(
    context: ImageEgressConsentContext,
    *,
    timeout_s: float = DEFAULT_IMAGE_CONSENT_TIMEOUT_S,
) -> ImageEgressConsentResult:
    """Ask the operator whether an article's OFF-SITE images may be fetched. Fail-closed.

    The single call the ingest coordinator makes when an article (URL mode) carries
    off-site image refs and images are enabled.  Synchronous-inline: it blocks until
    the registered verifier answers (or the bounded ``timeout_s`` fires).  The
    result's ``approved`` field is the ONLY thing that permits an off-site fetch.

    Fail-closed — every one of these yields a denied :class:`ImageEgressConsentResult`:
      * **No verifier configured** (the dormant default) → DENIED.
      * The verifier **raises** → DENIED.
      * The verifier **does not answer within ``timeout_s``** → DENIED.
      * The verifier returns **``None``** or a **non-:class:`ImageEgressConsentResult`** → DENIED.

    Off-site images are permitted **iff** the verifier returns ``approved is True``
    within the timeout.
    """
    verifier = active_image_egress_verifier()
    if verifier is None:
        logger.info(
            "Image-egress consent: no verifier configured — DENY (fail-closed "
            "default) for %s",
            context.describe(),
        )
        return ImageEgressConsentResult.deny(
            "no verifier configured", verifier_identity=_NO_VERIFIER_IDENTITY
        )

    verifier_name = type(verifier).__name__
    result_box: dict[str, ImageEgressConsentResult] = {}
    error_box: dict[str, BaseException] = {}

    def _run() -> None:
        try:
            result_box["result"] = verifier.verify(context)
        except BaseException as exc:  # noqa: BLE001 — fail-closed: any failure → DENY
            error_box["error"] = exc

    worker = threading.Thread(target=_run, name="image-egress-consent", daemon=True)
    worker.start()
    worker.join(timeout=timeout_s if timeout_s and timeout_s > 0 else None)

    if worker.is_alive():
        logger.warning(
            "Image-egress consent: verifier %s did not answer within %.1fs — DENY "
            "(fail-closed timeout) for %s",
            verifier_name, timeout_s, context.describe(),
        )
        return ImageEgressConsentResult.deny("timeout", verifier_identity=verifier_name)

    if "error" in error_box:
        logger.error(
            "Image-egress consent: verifier %s raised %r — DENY (fail-closed) for %s",
            verifier_name, error_box["error"], context.describe(),
        )
        return ImageEgressConsentResult.deny(
            f"verifier error: {type(error_box['error']).__name__}",
            verifier_identity=verifier_name,
        )

    result = result_box.get("result")
    if not isinstance(result, ImageEgressConsentResult):
        logger.error(
            "Image-egress consent: verifier %s returned a non-result (%r) — DENY "
            "(fail-closed) for %s",
            verifier_name, type(result).__name__, context.describe(),
        )
        return ImageEgressConsentResult.deny(
            "verifier returned malformed result", verifier_identity=verifier_name
        )

    if result.approved:
        logger.warning(
            "Image-egress consent: operator APPROVED %s via %s (%s).",
            context.describe(), result.verifier_identity or verifier_name, result.reason,
        )
        return result

    logger.info(
        "Image-egress consent: operator DENIED %s via %s (%s).",
        context.describe(), result.verifier_identity or verifier_name, result.reason,
    )
    return result
