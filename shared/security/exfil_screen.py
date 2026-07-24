r"""Outbound exfiltration screen — block-on-detection (ADR-027 §4).

This module is the *mechanism* that screens an outbound payload for secrets and
Personally Identifiable Information (PII) **before** it leaves the host — even to
an allowlisted endpoint (ADR-027 §4, Vikunja #628 / criterion C3, stream H-b).

Its reach is a function of the egress allowlist, not of a date: the egress guard
tags a socket for screening only when its destination is an allowlisted EXTERNAL
endpoint, so with an empty allowlist nothing is screened, and every endpoint the
allowlist names has its outbound payloads screened on every send. Read which
endpoints are live from the runtime wiring and the per-scope runbooks under
``docs/runbooks/`` — never from this docstring.

What it does (ADR-027 §4 — "screen every outbound payload, block on detection"):
  - :func:`screen` examines a payload and returns a :class:`Detection`. On any
    secret/PII hit, ``Detection.blocked`` is True (**fail-closed** — the caller
    MUST refuse the egress and fire the kill-switch auto-trip). A clean payload
    returns ``blocked=False``.
  - It REUSES the canonical PGOV PII detection
    (:func:`services.assistant_orchestrator.src.pgov.find_pii_spans` — the single
    source of truth for PII/secret pattern matching, OWASP LLM04 / Red-Team
    ISSUE-005) rather than reinventing recognizers. PGOV already covers SSN,
    credit-card (Luhn-gated), email, phone, IPv4, AWS keys, long hex secrets,
    passport, and bearer tokens. This screen ADDS a thin secret-credential layer
    for high-value formats the PGOV output-validator does not target (PEM private
    keys, JWT-shaped tokens, GitHub/Slack tokens, generic ``key=value`` secret
    assignments) — those are the credentials most likely to ride an outbound
    request body, and a leak of one is catastrophic.

Why block, not redact (ADR-027 §4, sharpening SECURITY_ROADMAP §6 Decision-5):
  redact-and-proceed trusts the redactor to catch everything; a single miss is a
  leak that cannot be recalled once it has left the host. The mandate is
  fail-closed, so the screen BLOCKS the whole call and the operator is alerted.
  A false positive blocks a legitimate call — accepted: fail-closed is the bar,
  and the operator can act (ADR-027 Consequences).

Wiring (stream H-a owns ``egress_guard``; this module only USES its public
interface): a caller registers :func:`screen` with
``shared.security.egress_guard.register_screener`` so the armed egress path
invokes it on every outbound payload, and calls
``shared.security.egress_guard.trip(reason)`` when a :class:`Detection` blocks —
the block-on-detect anomaly that cuts ALL egress (ADR-027 §3). The convenience
helper :func:`screen_and_enforce` performs exactly that handshake against the
documented contract; it imports ``egress_guard`` lazily so this module stays
importable (and unit-testable) before H-a's interface lands.

Design constraints (match the rest of ``shared/security/``):
  - **No external network. No new dependencies** (stdlib ``re`` + the in-tree
    PGOV recognizers).
  - **Importing this module has no side effects** — it does not register itself
    or arm anything. A process wires it explicitly at its entry point; tests call
    :func:`screen` directly.
  - **Fail-Closed everywhere:** an undecodable payload, or any error inside the
    screen, yields ``blocked=True`` — never a silent pass. "I can't tell" is not
    "it's safe."
  - The detection report carries **labels and offsets only, never raw secret
    values** — an alert/audit record must not itself leak the thing it caught
    (the same discipline PGOV applies to its redaction audit trail).
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Detection result
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DetectionSpan:
    """A single located secret/PII hit within a screened payload.

    Carries the pattern *label* and the *offsets* of the hit — never the raw
    matched value. An exfil alert/audit record must not itself become a leak of
    the secret it caught.
    """

    label: str
    """Pattern label (e.g. 'EMAIL', 'PRIVATE_KEY_PEM', 'AWS_KEY')."""

    start: int
    """Start offset of the hit in the screened text."""

    end: int
    """End offset (exclusive) of the hit in the screened text."""

    source: str
    """Which recognizer layer flagged it: 'pgov' (reused PII path) or 'secret'
    (this module's credential layer)."""


@dataclass(frozen=True)
class Detection:
    """Outcome of screening one outbound payload (ADR-027 §4).

    ``blocked`` is the load-bearing field: True means at least one secret/PII span
    was found and the egress MUST be refused (fail-closed). The caller fires the
    kill-switch auto-trip (``egress_guard.trip``) on a blocked detection.
    """

    blocked: bool
    """True iff one or more secret/PII spans were detected — the egress is
    refused (fail-closed). False iff the payload is clean."""

    labels: tuple[str, ...]
    """Sorted, de-duplicated pattern labels that matched (empty iff clean).
    Labels only — never raw values."""

    spans: tuple[DetectionSpan, ...] = field(default_factory=tuple)
    """All located hits (label + offsets), in document order. May be empty when
    a fail-closed error path blocks without locating a specific span."""

    reason: str = ""
    """Human-readable summary suitable for an operator alert / kill-switch
    ``trip`` reason. Contains labels + counts, never raw secret values."""

    @property
    def detected(self) -> bool:
        """Alias for ``blocked`` — True iff any secret/PII was found."""
        return self.blocked


# ---------------------------------------------------------------------------
# Secret-credential recognizers — the thin layer ADDED on top of the reused
# PGOV PII path. These target high-value credential FORMATS that the PGOV
# output-validator does not (it focuses on PII + a few secret shapes); a leak of
# one of these on an outbound request body is catastrophic, so they are screened
# explicitly here. Labels are distinct from PGOV's so the report attributes each
# hit to its recognizer layer.
# ---------------------------------------------------------------------------

_SECRET_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    # PEM private-key block header — RSA / EC / OPENSSH / generic PKCS#8.
    ("PRIVATE_KEY_PEM", re.compile(
        r"-----BEGIN (?:RSA |EC |DSA |OPENSSH |ENCRYPTED )?PRIVATE KEY-----"
    )),
    # JSON Web Token: three base64url segments separated by dots. The first
    # segment is a JOSE header beginning with "eyJ" ({"alg"... base64url-encoded).
    ("JWT", re.compile(
        r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b"
    )),
    # GitHub personal-access / OAuth / app tokens: ghp_, gho_, ghu_, ghs_, ghr_
    # followed by 36 base62 chars.
    ("GITHUB_TOKEN", re.compile(r"\bgh[poursa]_[A-Za-z0-9]{36}\b")),
    # Slack tokens: xox[bpoar]-... (bot/user/app/refresh).
    ("SLACK_TOKEN", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b")),
    # Google API key: AIza followed by 35 base64url-ish chars.
    ("GOOGLE_API_KEY", re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b")),
    # Generic secret assignment: a secret-announcing key followed by '=' or ':'
    # and a non-trivial value. Gated by the key word so a bare token is not
    # flagged (precision discipline, mirroring PGOV's context recognizers). The
    # value (group 1) is what gets located, not the announcing key.
    ("SECRET_ASSIGNMENT", re.compile(
        r"(?i)(?:api[_-]?key|secret[_-]?key|access[_-]?token|"
        r"client[_-]?secret|auth[_-]?token|password|passwd|"
        r"private[_-]?key|secret)"
        r"\s*[=:]\s*"
        r"['\"]?([A-Za-z0-9_\-./+]{12,})['\"]?"
    )),
]


def _find_secret_spans(text: str) -> list[DetectionSpan]:
    """Locate secret-credential spans via this module's credential layer.

    For ``SECRET_ASSIGNMENT`` (a capture-group pattern) the *value* (group 1) is
    located, not the announcing key — so the offsets point at the secret itself.
    Other patterns have no capture group; the whole match is the span.
    """
    spans: list[DetectionSpan] = []
    for label, pattern in _SECRET_PATTERNS:
        for match in pattern.finditer(text):
            group = 1 if pattern.groups >= 1 else 0
            start, end = match.span(group)
            if start < 0 or end <= start:
                continue
            spans.append(
                DetectionSpan(label=label, start=start, end=end, source="secret")
            )
    return spans


def _find_pii_spans(text: str) -> list[DetectionSpan]:
    """Locate PII/secret spans by REUSING the canonical PGOV recognizers.

    Lazy-imports :func:`services.assistant_orchestrator.src.pgov.find_pii_spans`
    so this module stays importable without pulling the AO dependency chain at
    module load (matching the lazy-import discipline used across the codebase),
    and so the PII path is the single source of truth — when PGOV's recognizers
    improve, this screen inherits the improvement for free.
    """
    from services.assistant_orchestrator.src.pgov import find_pii_spans

    return [
        DetectionSpan(label=m.label, start=m.start, end=m.end, source="pgov")
        for m in find_pii_spans(text)
    ]


def _coerce_to_text(payload: Any) -> str:
    """Reduce an outbound payload to the text that is screened. Fail-closed.

    Accepts ``str`` directly; decodes ``bytes``/``bytearray`` as UTF-8 (an
    undecodable body cannot be proven clean → the caller treats the
    :class:`UnicodeDecodeError` as a block, see :func:`screen`); serialises any
    other object via ``str`` so a structured body (dict/list) is still scanned
    for embedded secrets rather than silently skipped.
    """
    if isinstance(payload, str):
        return payload
    if isinstance(payload, (bytes, bytearray)):
        # errors="strict": an undecodable payload raises, and screen() converts
        # that to a fail-closed block. Silently replacing bad bytes could hide a
        # secret split across an invalid boundary.
        return bytes(payload).decode("utf-8")
    return str(payload)


def screen(payload: Any) -> Detection:
    """Screen one outbound payload for secrets + PII (ADR-027 §4).

    Runs two recognizer layers over the payload's text form:
      * the reused **PGOV PII path** (:func:`find_pii_spans`) — SSN, credit-card,
        email, phone, IPv4, AWS key, long hex secret, passport, bearer token; and
      * this module's **secret-credential layer** (:func:`_find_secret_spans`) —
        PEM private keys, JWTs, GitHub/Slack/Google tokens, generic secret
        assignments.

    Fail-Closed: any error during screening — an undecodable payload, or an
    unexpected exception in a recognizer — yields ``blocked=True``. A payload
    that cannot be proven clean is treated as a leak.

    Args:
        payload: The outbound payload. ``str``, ``bytes``/``bytearray``, or any
            object (serialised via ``str`` so structured bodies are still
            scanned).

    Returns:
        A :class:`Detection`. ``blocked=True`` (with the matched labels + spans)
        when any secret/PII is found OR on any fail-closed error; ``blocked=False``
        with empty labels when the payload is clean.
    """
    try:
        text = _coerce_to_text(payload)
    except Exception as exc:  # undecodable bytes, or a hostile __str__
        logger.warning(
            "exfil screen: payload not decodable for screening — BLOCKING "
            "(fail-closed): %s",
            exc,
        )
        return Detection(
            blocked=True,
            labels=("UNDECODABLE_PAYLOAD",),
            spans=(),
            reason=(
                "exfil screen blocked egress: payload could not be decoded for "
                "screening (fail-closed — an unscreenable payload is treated as a "
                "leak)"
            ),
        )

    try:
        spans = _find_pii_spans(text) + _find_secret_spans(text)
    except Exception as exc:  # a recognizer blew up — never silently pass.
        logger.error(
            "exfil screen: recognizer error — BLOCKING (fail-closed): %s", exc
        )
        return Detection(
            blocked=True,
            labels=("SCREEN_ERROR",),
            spans=(),
            reason=(
                "exfil screen blocked egress: screening raised an error "
                "(fail-closed — cannot prove the payload is clean)"
            ),
        )

    if not spans:
        return Detection(blocked=False, labels=(), spans=(), reason="")

    spans.sort(key=lambda s: (s.start, s.end, s.label))
    labels = tuple(sorted({s.label for s in spans}))
    reason = (
        f"exfil screen blocked egress: {len(spans)} secret/PII span(s) detected "
        f"in outbound payload (labels={list(labels)}) — fail-closed per ADR-027 §4"
    )
    logger.warning("%s", reason)
    return Detection(
        blocked=True,
        labels=labels,
        spans=tuple(spans),
        reason=reason,
    )


def screen_and_enforce(payload: Any) -> Detection:
    """Screen ``payload`` and, on a block, fire the egress kill-switch auto-trip.

    The block-on-detect enforcement path (ADR-027 §3/§4): screens the payload and,
    if the :class:`Detection` is blocked, calls
    ``shared.security.egress_guard.trip(reason)`` — the anomaly response that cuts
    ALL egress until the Lead Architect re-arms.

    ``egress_guard`` is imported lazily so this module is importable and
    unit-testable before stream H-a's ``register_screener``/``trip`` interface
    lands. If ``trip`` is absent (the interface has not merged yet), the block is
    still returned and logged — the screen never *fails open* just because the
    sink is not wired.

    This convenience helper is what a caller registers via
    ``egress_guard.register_screener(screen)`` indirectly enforces; it exists so
    the block→trip handshake is exercised by one tested call site rather than
    re-implemented per caller.

    Args:
        payload: The outbound payload to screen.

    Returns:
        The :class:`Detection` from :func:`screen`. On a blocked detection the
        kill-switch ``trip`` has been fired (when the interface is present).
    """
    detection = screen(payload)
    if detection.blocked:
        try:
            from shared.security import egress_guard

            trip = getattr(egress_guard, "trip", None)
            if callable(trip):
                trip(detection.reason)
            else:  # pragma: no cover - exercised only pre-H-a-merge
                logger.error(
                    "exfil screen: egress_guard.trip unavailable — block "
                    "returned but kill-switch NOT fired (H-a interface not "
                    "merged?): %s",
                    detection.reason,
                )
        except Exception as exc:  # never fail open on a wiring error
            logger.error(
                "exfil screen: egress_guard.trip raised — block stands: %s", exc
            )
    return detection


def wire_into_egress_guard() -> None:
    """Register :func:`screen` as the egress-guard outbound screener at arm time.

    This is the runtime wiring (Vikunja #634) that makes the built-and-tested
    exfil screen the live outbound-payload screener (ADR-027 rule 4). The
    launcher calls this once, around
    ``egress_guard.arm()``, at the real process entry.

    The wiring is via the documented **arm-hook seam**, NOT a direct
    ``register_screener`` call, so this module keeps its no-import-time-side-effect
    promise (the module docstring guarantees importing it arms/registers nothing):
    importing ``exfil_screen`` does nothing; *calling* this function appends a
    zero-arg arm-hook that calls
    ``egress_guard.register_screener(screen)`` exactly when the guard arms. If the
    guard is already armed when this is called, ``register_arm_hook`` runs the hook
    immediately, so the screener is registered either way.

    ``egress_guard`` is imported lazily (inside the function) so this module stays
    importable and unit-testable without pulling ``egress_guard`` at module load —
    matching :func:`screen_and_enforce`. Idempotent: ``register_arm_hook`` and
    ``register_screener`` both de-duplicate, so a second call (or a re-import) does
    not stack a second screener.

    SAFETY: registering the screener does NOT enable any external egress and does
    NOT screen internal traffic. The egress guard only invokes the screener for
    sockets connected to a vetted EXTERNAL-allowlisted endpoint, so registration is
    allowlist-scoped in both directions: with the external allowlist empty no
    socket is ever tagged and the registered screener is a behavior-free no-op;
    each widen brings exactly that endpoint's sends under the screen.
    """
    from shared.security import egress_guard

    egress_guard.register_arm_hook(
        lambda: egress_guard.register_screener(screen)
    )
    logger.info(
        "exfil screen: outbound screener wired into egress_guard via arm-hook "
        "(ADR-027 rule 4; registers at arm() time; dormant until an external "
        "endpoint is allowlisted)."
    )
