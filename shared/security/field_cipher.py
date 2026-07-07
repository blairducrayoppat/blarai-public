"""AES-256-GCM field cipher and HMAC keyed-index for BlarAI at-rest encryption.

Sprint 14 EA-2 — app-layer crypto layer (ADR-025 §2.2–§2.4).

Responsibilities
----------------
- **FieldCipher** — AES-256-GCM encryption/decryption of individual field values
  under a purpose-bound subkey ``k_enc`` (derived via HKDF-SHA256 from a DEK).
  Each encryption generates a fresh 96-bit CSPRNG nonce; the on-disk blob is
  self-describing: ``version(1) || nonce(12) || ciphertext || tag(16)``.
  Callers supply AAD on every call so a ciphertext is bound to the
  (table, column, row-identity) it was written into — relocating it to a
  different slot causes authentication failure (ADR-025 §2.4).
- **keyed_index** — deterministic HMAC-SHA256 under ``k_idx`` (a second subkey
  derived from the same DEK).  Used for uniqueness/dedup columns that must
  compare on ciphertext without revealing the plaintext (ADR-025 §2.4 / §3
  "keyed-hash index leaks equality — accepted residual").
- **SubkeySet** — named container produced by ``derive_subkeys(dek)``.  Holds
  the two 32-byte subkeys and exposes them to the envelope and to the store
  wiring layers (EA-3 / EA-4) without leaking the raw DEK past this layer.
- **make_aad_for** — convenience helper: ``table|column|row_id`` → bytes, the
  canonical AAD format specified in ADR-025 §2.4.  Callers may inline the
  concatenation instead; this is the blessed form.

Design constraints (ADR-025, non-negotiable)
--------------------------------------------
- **Fresh CSPRNG nonce per encryption** (``os.urandom(12)``).  NEVER stdlib
  ``random``, never a counter, never derived.  GCM nonce reuse under one key
  breaks confidentiality and authentication simultaneously.
- **Version byte** ``FIELD_CIPHER_VERSION`` is always the first byte of every
  encrypted blob — rotation-ready per ADR-025 §2.6.  ``decrypt`` validates it.
- **AAD mismatch → raise, never silently succeed.**  Authentication is the
  guarantee; returning corrupted data is the failure mode we MUST prevent.
- **No external network.  No new dependencies** — ``cryptography`` (present,
  46.0.5) + stdlib only.
- **Fail-Closed throughout**: any unexpected condition raises, never returns
  a partial or plaintext result.
"""

from __future__ import annotations

import hmac
import os
from dataclasses import dataclass
from typing import Final

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.hmac import HMAC
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

# ---------------------------------------------------------------------------
# Module-level constants
# ---------------------------------------------------------------------------

#: Version byte prepended to every encrypted field blob.  Bump to 0x02 when
#: the cipher or nonce format changes (rotation path per ADR-025 §2.6).
FIELD_CIPHER_VERSION: Final[int] = 0x01

#: HKDF info strings — lock these to the values pinned in ADR-025 §2.2.
_INFO_ENC: Final[bytes] = b"blarai-field-enc-v1"
_INFO_IDX: Final[bytes] = b"blarai-index-mac-v1"

#: AES-GCM nonce size in bytes (96-bit per NIST SP 800-38D recommendation).
_NONCE_BYTES: Final[int] = 12

#: AES-GCM authentication tag size in bytes (128-bit, the GCM default).
_TAG_BYTES: Final[int] = 16

#: Output key length for both HKDF-derived subkeys (256-bit AES / HMAC key).
_SUBKEY_BYTES: Final[int] = 32

#: Non-payload bytes added by :meth:`FieldCipher.encrypt` around every
#: plaintext: ``version(1) || nonce(12) || ciphertext || tag(16)``.  AES-GCM is
#: length-preserving on the payload (CTR-mode keystream), so an encrypted blob
#: is EXACTLY ``len(plaintext) + ENVELOPE_OVERHEAD_BYTES`` bytes.  Callers that
#: enforce a CIPHERTEXT byte cap (e.g. the ingest staging file) derive their
#: effective PLAINTEXT cap by subtracting this constant (#655 byte-cap seam).
ENVELOPE_OVERHEAD_BYTES: Final[int] = 1 + _NONCE_BYTES + _TAG_BYTES

#: DEK size in bytes (256-bit master key).
DEK_BYTES: Final[int] = 32


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class FieldCipherError(RuntimeError):
    """Raised when decryption or key-derivation fails (Fail-Closed)."""


# ---------------------------------------------------------------------------
# Subkey derivation
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SubkeySet:
    """Two purpose-bound 32-byte keys derived from the DEK via HKDF-SHA256.

    ``k_enc``: AES-256-GCM key — used exclusively for field encryption.
    ``k_idx``: HMAC key — used exclusively for deterministic keyed-index hashes.

    The separation means a weakness confined to one role cannot cross to the
    other, and the raw DEK stays clean (ADR-025 §2.2).
    """

    k_enc: bytes  # 32 bytes
    k_idx: bytes  # 32 bytes

    def __post_init__(self) -> None:
        if len(self.k_enc) != _SUBKEY_BYTES:
            raise ValueError(
                f"k_enc must be {_SUBKEY_BYTES} bytes, got {len(self.k_enc)}"
            )
        if len(self.k_idx) != _SUBKEY_BYTES:
            raise ValueError(
                f"k_idx must be {_SUBKEY_BYTES} bytes, got {len(self.k_idx)}"
            )


def derive_subkeys(dek: bytes) -> SubkeySet:
    """Derive ``k_enc`` and ``k_idx`` from ``dek`` via HKDF-SHA256.

    The DEK is **never** used directly for any cryptographic operation — all
    callers receive a ``SubkeySet`` and operate on the derived subkeys only
    (ADR-025 §2.2).

    Args:
        dek: 32-byte master Data-Encryption Key (from a CSPRNG).

    Returns:
        :class:`SubkeySet` with the two 32-byte purpose-bound subkeys.

    Raises:
        ValueError: if ``dek`` is not exactly 32 bytes.
    """
    if len(dek) != DEK_BYTES:
        raise ValueError(f"DEK must be {DEK_BYTES} bytes, got {len(dek)}")

    k_enc = HKDF(
        algorithm=hashes.SHA256(),
        length=_SUBKEY_BYTES,
        salt=None,
        info=_INFO_ENC,
    ).derive(dek)

    k_idx = HKDF(
        algorithm=hashes.SHA256(),
        length=_SUBKEY_BYTES,
        salt=None,
        info=_INFO_IDX,
    ).derive(dek)

    return SubkeySet(k_enc=k_enc, k_idx=k_idx)


# ---------------------------------------------------------------------------
# AAD helper
# ---------------------------------------------------------------------------


def make_aad_for(table: str, column: str, row_id: str | bytes) -> bytes:
    """Assemble canonical AAD for a field encryption (ADR-025 §2.4).

    Format: ``<table>|<column>|<row_id>`` as UTF-8.  The pipe separator is
    chosen because SQLite table/column names cannot contain ``|``, making
    component boundaries unambiguous.

    Args:
        table:  Table name (e.g. ``"substrate_chunks"``).
        column: Column name (e.g. ``"text"``).
        row_id: Natural row identity — a ``str`` or ``bytes``.  For sessions.db
                this is the UUID string; for substrate_chunks it is the
                ``kind|source_hash|session_id|chunk_index`` natural key.

    Returns:
        UTF-8-encoded AAD bytes.
    """
    if isinstance(row_id, bytes):
        row_id_str = row_id.decode("utf-8", errors="surrogateescape")
    else:
        row_id_str = row_id
    return f"{table}|{column}|{row_id_str}".encode("utf-8")


# ---------------------------------------------------------------------------
# Field cipher
# ---------------------------------------------------------------------------


class FieldCipher:
    """AES-256-GCM field-level encrypt / decrypt under ``k_enc``.

    Each call to :meth:`encrypt` generates a fresh 96-bit CSPRNG nonce from
    ``os.urandom(12)`` and produces a self-describing blob::

        version(1) || nonce(12) || ciphertext(variable) || tag(16)

    The **version byte** (``FIELD_CIPHER_VERSION``) is the first byte, enabling
    format-compatible DEK rotation or algorithm changes later (ADR-025 §2.6).

    Callers MUST supply the same ``aad`` bytes on both :meth:`encrypt` and
    :meth:`decrypt`.  If the AAD, the ciphertext, or the tag do not match,
    :meth:`decrypt` raises :class:`FieldCipherError` — it never returns
    unauthenticated data.

    Args:
        subkeys: :class:`SubkeySet` produced by :func:`derive_subkeys`.
    """

    def __init__(self, subkeys: SubkeySet) -> None:
        self._aesgcm = AESGCM(subkeys.k_enc)
        self._k_idx = subkeys.k_idx

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def encrypt(self, plaintext: bytes, *, aad: bytes) -> bytes:
        """Encrypt ``plaintext`` under AES-256-GCM with a fresh random nonce.

        The returned blob is::

            version(1) || nonce(12) || ciphertext || tag(16)

        The same ``aad`` MUST be supplied to :meth:`decrypt`.  Passing an empty
        ``aad`` is technically valid GCM but violates ADR-025 §2.4 — callers
        from EA-3/EA-4 MUST use :func:`make_aad_for` or an equivalent binding.

        Args:
            plaintext: Field value to protect (arbitrary bytes; may be empty).
            aad:       Authenticated-additional-data binding this ciphertext to
                       its (table, column, row) identity.

        Returns:
            Self-describing encrypted blob: ``version || nonce || ciphertext || tag``.
        """
        nonce: bytes = os.urandom(_NONCE_BYTES)
        # AESGCM.encrypt returns ciphertext || tag (tag is the trailing 16 bytes).
        ct_and_tag: bytes = self._aesgcm.encrypt(nonce, plaintext, aad)
        return bytes([FIELD_CIPHER_VERSION]) + nonce + ct_and_tag

    def decrypt(self, blob: bytes, *, aad: bytes) -> bytes:
        """Decrypt a blob produced by :meth:`encrypt`.

        Validates the version byte, extracts the nonce, then asks AESGCM to
        authenticate the ciphertext against the tag and the supplied ``aad``.
        Any mismatch (wrong AAD, tampered ciphertext/tag, wrong key, wrong
        version) raises :class:`FieldCipherError`.

        Args:
            blob: Encrypted blob (from :meth:`encrypt`).
            aad:  Authenticated-additional-data — MUST match the value used
                  during :meth:`encrypt`.

        Returns:
            The original plaintext bytes.

        Raises:
            :class:`FieldCipherError`: on version mismatch, truncated blob,
                authentication failure, tamper, or any other decryption error.
        """
        _MIN_BLOB = ENVELOPE_OVERHEAD_BYTES  # version + nonce + tag
        if len(blob) < _MIN_BLOB:
            raise FieldCipherError(
                f"decrypt: blob too short ({len(blob)} bytes, minimum {_MIN_BLOB})"
            )
        version = blob[0]
        if version != FIELD_CIPHER_VERSION:
            raise FieldCipherError(
                f"decrypt: unsupported cipher version 0x{version:02X} "
                f"(expected 0x{FIELD_CIPHER_VERSION:02X})"
            )
        nonce = blob[1 : 1 + _NONCE_BYTES]
        ct_and_tag = blob[1 + _NONCE_BYTES :]
        try:
            return self._aesgcm.decrypt(nonce, ct_and_tag, aad)
        except InvalidTag as exc:
            raise FieldCipherError(
                "decrypt: authentication failed — ciphertext tampered, "
                "wrong AAD, or wrong key"
            ) from exc

    def keyed_index(self, source: bytes) -> bytes:
        """Return HMAC-SHA256(``k_idx``, ``source``) — the deterministic keyed index.

        Used for dedup/uniqueness columns (e.g. ``source_hash`` in substrate_chunks)
        that must work on ciphertext.  The output is 32 bytes, deterministic for
        identical input, and computationally unpredictable without ``k_idx``.

        The equality-leakage documented residual (ADR-025 §3): two identical
        ``source`` values produce the same output, revealing "these two entries
        share a source."  This is the accepted price of keeping dedup functional
        on ciphertext.

        Args:
            source: Raw bytes to hash (e.g. the UTF-8 filename, pre-normalisation).

        Returns:
            32-byte HMAC-SHA256 digest.
        """
        h = HMAC(self._k_idx, hashes.SHA256())
        h.update(source)
        return h.finalize()
