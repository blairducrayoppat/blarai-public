"""Boot-time Kagi API key loader — the wrapped, never-logged secret slot.

#719 Part B (web_search go-live build). The DPAPI-sealed blob store
(:mod:`shared.secrets.dpapi_store`, W2/#573 — machine- and user-bound,
``%LOCALAPPDATA%\\BlarAI\\secrets\\kagi_api_key.dpapi``) already owns
at-rest protection and the operator provisioning ceremony
(``python -m shared.secrets.provision_kagi_key``). This module owns the
BOOT-TIME consumption posture on top of it:

- **Wrapped, never bare.** :func:`load_wrapped_kagi_key` returns the key
  inside :class:`KagiApiKey`, whose ``repr``/``str``/``format`` are all a
  fixed redaction marker — an accidental ``logger.info("... %s", key)`` or an
  exception message carrying the object can never echo the key material. The
  plaintext is obtainable ONLY via :meth:`KagiApiKey.authorization_header_value`
  at the single point of use (the egress door's ``Authorization`` header).
- **Fail-closed to dormant.** An absent blob, an empty/whitespace value, a
  malformed value (non-string, over-long, non-ASCII, embedded whitespace or
  control characters), a DPAPI decrypt failure, or ANY other error returns
  ``None`` — the caller (the AO entrypoint's conditional web_search
  registration) treats ``None`` as "stay structurally dormant". This function
  NEVER raises.
- **Never logged.** No code path in this module places the key value (or any
  substring of it) into a log record, an exception message, or a repr. A
  regression test drives the real logging path with a sentinel value and
  asserts the sentinel never reaches any record.
"""

from __future__ import annotations

import logging
from typing import Final, Optional

logger = logging.getLogger(__name__)

#: The fixed redaction marker every string conversion of :class:`KagiApiKey`
#: yields. A constant (not derived from the key) so nothing about the key —
#: not even its length — leaks through repr/str/format.
REDACTED_KEY_MARKER: Final[str] = "KagiApiKey(<redacted>)"

#: The Kagi Search API authentication scheme (``Authorization: Bearer <key>``
#: — verified LIVE against the CURRENT ``/api/v1/search`` endpoint at the
#: 2026-07-02 go-live ceremony: v1 authenticates with ``Bearer``, NOT the
#: ``Bot`` scheme the deprecated ``/api/v0/search`` endpoint used. Building
#: the v0-era ``Bot`` header against v1 was the cause of the go-live 401;
#: the scheme now matches the live endpoint. The wrapper still owns header
#: construction so the bare key never leaves this module).
_AUTH_SCHEME: Final[str] = "Bearer"

#: Sanity ceiling on the key length. Real Kagi API tokens are far shorter; a
#: multi-kilobyte "key" is a corrupted/malformed blob, not a credential, and
#: is refused (fail-closed to dormant) rather than shipped in a header.
_MAX_KEY_CHARS: Final[int] = 256


class KagiApiKey:
    """An opaque wrapper around the Kagi API key — redacted everywhere.

    ``repr(key)``, ``str(key)``, and ``format(key)`` all return the fixed
    :data:`REDACTED_KEY_MARKER`, so the key value cannot reach a log record,
    a traceback, or a debug dump through any ordinary string conversion. The
    plaintext is reachable ONLY through
    :meth:`authorization_header_value`, whose single sanctioned consumer is
    the ``Authorization`` header of the one egress door
    (:func:`shared.security.guarded_fetch.fetch_external`).
    """

    __slots__ = ("_value",)

    def __init__(self, value: str) -> None:
        self._value = value

    def authorization_header_value(self) -> str:
        """The exact ``Authorization`` header value (``Bearer <key>``).

        The ONLY way the plaintext leaves this wrapper. Callers must pass it
        directly to the egress door's ``authorization`` parameter and never
        log, cache, or re-wrap it.
        """
        return f"{_AUTH_SCHEME} {self._value}"

    def __repr__(self) -> str:
        return REDACTED_KEY_MARKER

    def __str__(self) -> str:
        return REDACTED_KEY_MARKER

    def __format__(self, format_spec: str) -> str:
        return REDACTED_KEY_MARKER


def _is_well_formed(candidate: str) -> bool:
    """True iff *candidate* has the shape of a credential token.

    Fail-closed shape gate: non-empty, bounded length, ASCII, and free of
    whitespace / control characters (either would corrupt the HTTP header it
    is destined for — and is a corrupted-blob smell, not a real key).
    """
    if not candidate or len(candidate) > _MAX_KEY_CHARS:
        return False
    if not candidate.isascii():
        return False
    return all((not ch.isspace()) and ch.isprintable() for ch in candidate)


def load_wrapped_kagi_key() -> Optional[KagiApiKey]:
    """Load the operator-provisioned Kagi API key, wrapped — or ``None``.

    Reads the DPAPI blob via :func:`shared.secrets.dpapi_store.load_kagi_api_key`
    (which also honors the hermetic pytest override env). Every failure path —
    blob absent (not provisioned), DPAPI decrypt failure, pywin32 unavailable,
    empty/whitespace value, malformed value — returns ``None`` so the caller
    stays structurally dormant. NEVER raises, and NEVER logs the key value
    (log lines carry only the exception TYPE name / a fixed reason label).
    """
    try:
        from shared.secrets.dpapi_store import load_kagi_api_key

        raw = load_kagi_api_key()
    except Exception as exc:  # noqa: BLE001 — every load failure is dormancy, never a crash
        # Type name only — dpapi_store's exceptions never carry key material,
        # but we do not forward their messages into this log line regardless.
        logger.info(
            "Kagi API key unavailable (%s) — web_search stays dormant "
            "(fail-closed).",
            type(exc).__name__,
        )
        return None

    if not isinstance(raw, str):
        logger.warning(
            "Kagi API key blob decoded to a non-string — malformed; "
            "web_search stays dormant (fail-closed)."
        )
        return None

    candidate = raw.strip()
    if not _is_well_formed(candidate):
        # Deliberately reason-free beyond "empty or malformed": naming WHICH
        # shape check failed would leak information about the stored value.
        logger.warning(
            "Kagi API key is empty or malformed — web_search stays dormant "
            "(fail-closed)."
        )
        return None

    return KagiApiKey(candidate)
