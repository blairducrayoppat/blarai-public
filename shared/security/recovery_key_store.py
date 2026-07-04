"""Offline recovery-key store — the operator's break-glass key material.

Sprint 17 Stream K — offline key-recovery path (SECURITY_ROADMAP §5.5, C6).

What this module is
-------------------
The at-rest Data-Encryption Key (DEK) is wrapped **twice** by
:mod:`shared.security.dek_envelope`: once under the TPM seal key (the daily
binding) and once under a high-entropy **offline recovery key** (the
break-glass path).  If the TPM/chip dies or the operator migrates to new
hardware, the recovery key is the *only* way to unwrap the DEK and decrypt
the decades-lifespan session/substrate data (Sprint-14 Decision-2,
``SECURITY_ROADMAP_air_gap_removal.md`` §6 item 2).

This module owns the **recovery key material itself** — its generation, its
human-transcribable encoding, and the fail-closed parsing of an
operator-entered key back into bytes.  It is deliberately small and has a
single, sharp purpose so it is auditable in isolation, mirroring the
separation between ``tpm_sealer.py`` (sealing) and ``tpm_signer.py``
(signing).

The contract that makes it safe
-------------------------------
- **The recovery key is NEVER written to disk in cleartext by this module.**
  The only thing persisted anywhere is the *wrapped* DEK (the recovery wrap
  record), which lives in the keystore that :mod:`dek_envelope` owns.  The
  raw recovery key is generated, shown to the operator ONCE, and stored
  *off the machine* (printed / USB / safe).  There is intentionally no
  ``save_to_disk`` function here — that would be a footgun.
- **The recovery key is never logged.**  Use :func:`redact` for any
  diagnostic that must mention it; :func:`redact` reveals only the length
  and a short non-reversible fingerprint, never the bytes.
- **Fail-Closed parsing.**  :func:`parse_hex` rejects a key of the wrong
  length, wrong character set, or wrong checksum (when a checksummed display
  string is supplied) by raising :class:`RecoveryKeyError` — it never
  returns a truncated, padded, or otherwise "best-effort" key.

Design constraints (ADR-025, non-negotiable)
--------------------------------------------
- **No external network.  No new dependencies** — stdlib only (``secrets``,
  ``hashlib``).  The 256-bit key size is imported from
  :mod:`dek_envelope` so there is exactly one definition of "recovery key
  size" across the codebase.
- **Strict type hints, PEP 8, deterministic.**
"""

from __future__ import annotations

import hashlib
import secrets
from typing import Final

from shared.security.dek_envelope import RECOVERY_KEY_BYTES

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: Number of lowercase hex characters in a bare-hex recovery key
#: (``RECOVERY_KEY_BYTES`` bytes × 2 nibbles).  64 for a 256-bit key.
RECOVERY_KEY_HEX_CHARS: Final[int] = RECOVERY_KEY_BYTES * 2

#: Hex characters per group in the grouped display form (see
#: :func:`to_display_groups`).  Eight 8-char groups for a 256-bit key gives a
#: layout a human can transcribe one block at a time without losing their place.
_GROUP_LEN: Final[int] = 8

#: Separator between groups in the grouped display form.
_GROUP_SEP: Final[str] = "-"

#: Length (hex chars) of the truncated checksum appended to a checksummed
#: display string.  Four hex chars = 16 bits — enough to catch a single
#: transcription slip with overwhelming probability, while staying short
#: enough not to burden the operator.  It is a transcription guard, NOT a
#: cryptographic integrity guarantee (AES-GCM on the recovery wrap provides
#: that — a wrong key fails authentication regardless).
_CHECKSUM_HEX_CHARS: Final[int] = 4

#: Characters stripped from operator input before validation: spaces, the
#: group separator, and common transcription noise (newlines/tabs).
_STRIP_CHARS: Final[str] = " \t\r\n" + _GROUP_SEP


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class RecoveryKeyError(ValueError):
    """Raised when recovery-key material is malformed (Fail-Closed).

    Subclasses :class:`ValueError` so existing callers that already catch
    ``ValueError`` around recovery-key parsing (e.g. the provisioning
    ceremony) keep working, while new callers can catch the precise type.

    The message NEVER contains the key bytes or any reversible fragment of
    them — only structural facts (observed length, where parsing failed).
    """


# ---------------------------------------------------------------------------
# Generation
# ---------------------------------------------------------------------------


def generate() -> bytes:
    """Generate a fresh high-entropy 256-bit offline recovery key.

    The returned bytes are the operator's break-glass key.  They are shown
    ONCE (the ceremony prints them) and stored off the machine; this module
    never persists them.

    Returns:
        ``RECOVERY_KEY_BYTES`` cryptographically-random bytes from the OS
        CSPRNG.
    """
    return secrets.token_bytes(RECOVERY_KEY_BYTES)


# ---------------------------------------------------------------------------
# Encoding for display (operator transcription)
# ---------------------------------------------------------------------------


def to_hex(recovery_key: bytes) -> str:
    """Encode a recovery key as a bare lowercase-hex string (no separators).

    This is the canonical, copy-paste-friendly form.  It is exactly
    :data:`RECOVERY_KEY_HEX_CHARS` characters and round-trips through
    :func:`parse_hex`.

    Args:
        recovery_key: Exactly ``RECOVERY_KEY_BYTES`` bytes.

    Returns:
        The lowercase-hex encoding.

    Raises:
        RecoveryKeyError: if ``recovery_key`` is not the expected length.
    """
    _require_key_length(recovery_key)
    return recovery_key.hex()


def to_display_groups(recovery_key: bytes, *, checksum: bool = True) -> str:
    """Encode a recovery key as dash-separated groups for human transcription.

    The grouped form (e.g. ``a1b2c3d4-e5f6...``) is easier for a person to
    copy onto paper or read aloud than one unbroken 64-character run.  When
    ``checksum`` is True a short truncated-SHA-256 checksum group is appended
    so an accidental transcription slip is caught on re-entry by
    :func:`parse_hex` *before* the (slower, all-or-nothing) AES-GCM unwrap is
    even attempted.

    Both the grouped form and the checksummed grouped form parse cleanly back
    through :func:`parse_hex`.

    Args:
        recovery_key: Exactly ``RECOVERY_KEY_BYTES`` bytes.
        checksum:     Append a transcription-checksum group (default True).

    Returns:
        A dash-separated display string.

    Raises:
        RecoveryKeyError: if ``recovery_key`` is not the expected length.
    """
    _require_key_length(recovery_key)
    hexed = recovery_key.hex()
    groups = [hexed[i : i + _GROUP_LEN] for i in range(0, len(hexed), _GROUP_LEN)]
    if checksum:
        groups.append(_checksum_hex(recovery_key))
    return _GROUP_SEP.join(groups)


# ---------------------------------------------------------------------------
# Parsing operator input (Fail-Closed)
# ---------------------------------------------------------------------------


def parse_hex(text: str) -> bytes:
    """Parse an operator-entered recovery key back into bytes (Fail-Closed).

    Accepts every form this module emits:
      * bare hex from :func:`to_hex`;
      * dash-separated groups from :func:`to_display_groups` (no checksum);
      * checksummed groups from :func:`to_display_groups` — the trailing
        checksum group is validated against the recovered key and then
        stripped.

    Tolerant of incidental whitespace, dashes, and case (operators paste
    imperfectly), but **strict** on the result: a key of the wrong length,
    containing non-hex characters, or carrying a checksum that does not match
    is rejected with :class:`RecoveryKeyError`.  It never returns a truncated
    or padded key.

    Args:
        text: The string the operator entered or pasted.

    Returns:
        Exactly ``RECOVERY_KEY_BYTES`` bytes.

    Raises:
        RecoveryKeyError: on any malformed input (wrong length, bad hex, or
            checksum mismatch).  The error message contains only structural
            facts, never the key material.
    """
    if not isinstance(text, str):  # defensive: callers may pass bytes by mistake
        raise RecoveryKeyError(
            f"recovery key input must be a string, got {type(text).__name__}"
        )

    cleaned = _strip_noise(text).lower()
    if not cleaned:
        raise RecoveryKeyError("recovery key input is empty after stripping separators")

    # A checksummed grouped string is RECOVERY_KEY_HEX_CHARS + _CHECKSUM_HEX_CHARS
    # once the separators are gone.  If the length matches that, peel + verify
    # the trailing checksum; otherwise treat the whole thing as the key body.
    expected_with_checksum = RECOVERY_KEY_HEX_CHARS + _CHECKSUM_HEX_CHARS
    if len(cleaned) == expected_with_checksum:
        body_hex = cleaned[:RECOVERY_KEY_HEX_CHARS]
        supplied_checksum = cleaned[RECOVERY_KEY_HEX_CHARS:]
        key = _hex_to_key(body_hex)
        if not secrets.compare_digest(supplied_checksum, _checksum_hex(key)):
            raise RecoveryKeyError(
                "recovery key checksum mismatch — the key was likely "
                "mis-transcribed; re-enter it exactly as printed"
            )
        return key

    # No checksum present (or an unexpected length): require an exact bare-hex
    # key.  This is the Fail-Closed branch — no padding, no truncation.
    if len(cleaned) != RECOVERY_KEY_HEX_CHARS:
        raise RecoveryKeyError(
            f"recovery key has wrong length: {len(cleaned)} hex characters "
            f"(expected {RECOVERY_KEY_HEX_CHARS}, or "
            f"{expected_with_checksum} with a checksum group)"
        )
    return _hex_to_key(cleaned)


# ---------------------------------------------------------------------------
# Redaction for logging / diagnostics
# ---------------------------------------------------------------------------


def redact(recovery_key: bytes) -> str:
    """Return a safe, non-reversible descriptor of a recovery key for logs.

    NEVER log the recovery key itself.  This descriptor reveals only the byte
    length and a short SHA-256 fingerprint (the same truncated digest used as
    the transcription checksum), which is sufficient to correlate log lines
    about "the same key" without disclosing any key material.

    Args:
        recovery_key: The key bytes (any length — this is a diagnostic, so it
            does not enforce the length contract).

    Returns:
        A string like ``"<recovery-key len=32 fp=1a2b3c4d>"``.
    """
    fingerprint = hashlib.sha256(recovery_key).hexdigest()[:_CHECKSUM_HEX_CHARS * 2]
    return f"<recovery-key len={len(recovery_key)} fp={fingerprint}>"


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _require_key_length(recovery_key: bytes) -> None:
    """Raise :class:`RecoveryKeyError` unless ``recovery_key`` is the right size."""
    if not isinstance(recovery_key, (bytes, bytearray)):
        raise RecoveryKeyError(
            f"recovery key must be bytes, got {type(recovery_key).__name__}"
        )
    if len(recovery_key) != RECOVERY_KEY_BYTES:
        raise RecoveryKeyError(
            f"recovery key must be {RECOVERY_KEY_BYTES} bytes, got {len(recovery_key)}"
        )


def _strip_noise(text: str) -> str:
    """Remove whitespace and group separators an operator may have included."""
    table = {ord(ch): None for ch in _STRIP_CHARS}
    return text.translate(table)


def _hex_to_key(body_hex: str) -> bytes:
    """Decode a bare-hex key body, raising :class:`RecoveryKeyError` on bad hex."""
    try:
        key = bytes.fromhex(body_hex)
    except ValueError as exc:
        # bytes.fromhex echoes the offending content; suppress it so no key
        # fragment reaches logs via the exception text.
        raise RecoveryKeyError(
            "recovery key contains non-hexadecimal characters"
        ) from None
    if len(key) != RECOVERY_KEY_BYTES:  # defensive — length checked upstream
        raise RecoveryKeyError(
            f"decoded recovery key has wrong length: {len(key)} bytes "
            f"(expected {RECOVERY_KEY_BYTES})"
        )
    return key


def _checksum_hex(recovery_key: bytes) -> str:
    """Truncated SHA-256 transcription checksum (hex) for ``recovery_key``.

    NOT a security control — AES-GCM authentication on the recovery wrap is
    the real integrity gate.  This only catches an operator mis-keying the
    recovery string before the expensive unwrap is attempted.
    """
    return hashlib.sha256(recovery_key).hexdigest()[:_CHECKSUM_HEX_CHARS]
