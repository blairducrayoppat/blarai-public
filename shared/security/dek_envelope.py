"""DEK lifecycle — dual-wrap envelope, keystore persistence, and factory.

Sprint 14 EA-2 — app-layer crypto layer (ADR-025 §2.1, §2.5–§2.7).

Responsibilities
----------------
- **DekEnvelope** — owns ONE 256-bit master DEK that is **never persisted in
  cleartext** and **never used directly for encryption** (the raw DEK is only
  passed to :func:`~shared.security.field_cipher.derive_subkeys`).  The DEK
  is wrapped **twice**, producing two independent wrap records either of which
  can unwrap the same DEK:
  1. **TPM wrap** — ``sealer.seal(DEK)`` (RSA-2048 OAEP-SHA-256; the private
     key never leaves the chip).
  2. **Recovery wrap** — ``AES-256-GCM(DEK)`` under a high-entropy random
     256-bit recovery key stored **off-box** by the Lead Architect.  This is
     the break-glass path for a dead chip or hardware migration.
  Each wrap record is prefixed by a version byte (``WRAP_VERSION``).
- **Keystore** — ``save(path)`` persists the two wrap records to a JSON file
  at the caller-supplied path (never the DBs, never the DEK in clear).
  ``load(path)`` reads them back.
- **Fail-Closed factory** — :func:`build_envelope` is the **only** production
  construction path.  It refuses a :class:`~shared.security.tpm_sealer.SoftwareSealer`
  unless ``dev_mode=True`` is explicit — the enforcement EA-1 deliberately
  delegated here (tpm_sealer.py docstring §SoftwareSealer).  ``dev_mode=False``
  (default) + ``SoftwareSealer`` → :class:`DevModeSealerError` immediately.

Unseal order (ADR-025 §2.7)
----------------------------
1. Try the TPM sealer first.
2. If the TPM sealer raises (``TpmUnavailable`` or ``TpmSealingError``) AND a
   ``recovery_key`` is provided → use the recovery wrap.
3. If neither path succeeds → raise :class:`DekEnvelopeError` (refuse to open).
   **There is no plaintext fallback, ever.**

Design constraints (ADR-025, non-negotiable)
--------------------------------------------
- **Version byte** on every wrap record (``WRAP_VERSION``).  Rotation-ready per
  ADR-025 §2.6.  This module provides the wrap format only; the rotation
  *procedure* lives outside it.
- **Recovery key is a 256-bit random key** — not a passphrase.  It wraps the
  DEK under AES-256-GCM (a fresh random nonce per wrap, NOT the same key used
  for field encryption; the recovery key has a single, distinct purpose).
- **No external network.  No new dependencies** — ``cryptography`` + stdlib.
- **Fail-Closed throughout**: any unexpected condition raises, never falls
  back to plaintext or a weaker posture.
"""

from __future__ import annotations

import json
import logging
import os
import secrets
from base64 import b64decode, b64encode
from pathlib import Path
from typing import Final

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from shared.security.field_cipher import DEK_BYTES
from shared.security.tpm_sealer import (
    Sealer,
    SoftwareSealer,
    TpmSealingError,
    TpmUnavailable,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: Version byte prefixed to every wrap record.  Bump when the wrapping scheme
#: changes (rotation path per ADR-025 §2.6).
WRAP_VERSION: Final[int] = 0x01

#: Recovery key size in bytes (256-bit, from a CSPRNG at ceremony time).
RECOVERY_KEY_BYTES: Final[int] = 32

#: AES-GCM nonce size for the recovery wrap (96-bit per NIST SP 800-38D).
_RECOVERY_NONCE_BYTES: Final[int] = 12

#: AES-GCM authentication tag size (128-bit, GCM default).
_RECOVERY_TAG_BYTES: Final[int] = 16

#: JSON keystore field names — stable across versions.
_KEY_TPM_WRAP: Final[str] = "tpm_wrap_v"
_KEY_RECOVERY_WRAP: Final[str] = "recovery_wrap_v"

#: Minimum wrap record size: version(1) + nonce(12) + DEK(32) + tag(16).
_MIN_RECOVERY_WRAP_BYTES: Final[int] = 1 + _RECOVERY_NONCE_BYTES + DEK_BYTES + _RECOVERY_TAG_BYTES


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class DekEnvelopeError(RuntimeError):
    """Raised when the DEK cannot be unsealed and no fallback is available.

    This is the Fail-Closed signal: the store MUST refuse to open when this
    is raised.  There is no plaintext fallback.
    """


class DevModeSealerError(RuntimeError):
    """Raised by :func:`build_envelope` when a SoftwareSealer is supplied
    outside an explicit ``dev_mode=True`` context.

    The SoftwareSealer is not a security boundary (its key is a hard-coded
    public constant).  Using it in production would silently break the entire
    at-rest encryption posture.  This exception is loud and typed so that the
    failure is unmissable in logs and tests.
    """


# ---------------------------------------------------------------------------
# Recovery-key wrap / unwrap helpers
# ---------------------------------------------------------------------------


def _recovery_wrap(dek: bytes, recovery_key: bytes) -> bytes:
    """Wrap ``dek`` under AES-256-GCM(``recovery_key``) with a fresh nonce.

    The resulting record is::

        version(1) || nonce(12) || AES-GCM(dek, nonce, aad=b"") || tag(16)

    Args:
        dek:          32-byte DEK to wrap.
        recovery_key: 32-byte high-entropy random key (off-box; not a passphrase).

    Returns:
        Version-prefixed wrap record bytes.

    Raises:
        ValueError: if ``dek`` or ``recovery_key`` are not 32 bytes.
    """
    if len(dek) != DEK_BYTES:
        raise ValueError(f"dek must be {DEK_BYTES} bytes, got {len(dek)}")
    if len(recovery_key) != RECOVERY_KEY_BYTES:
        raise ValueError(
            f"recovery_key must be {RECOVERY_KEY_BYTES} bytes, got {len(recovery_key)}"
        )
    nonce: bytes = os.urandom(_RECOVERY_NONCE_BYTES)
    aesgcm = AESGCM(recovery_key)
    ct_and_tag = aesgcm.encrypt(nonce, dek, None)
    return bytes([WRAP_VERSION]) + nonce + ct_and_tag


def _recovery_unwrap(wrap_record: bytes, recovery_key: bytes) -> bytes:
    """Unwrap a record produced by :func:`_recovery_wrap`.

    Args:
        wrap_record:  Version-prefixed wrap record bytes (from the keystore).
        recovery_key: 32-byte recovery key.

    Returns:
        The original DEK bytes (32 bytes).

    Raises:
        DekEnvelopeError: on version mismatch, truncated record, wrong key,
            or authentication failure.
    """
    if len(wrap_record) < _MIN_RECOVERY_WRAP_BYTES:
        raise DekEnvelopeError(
            f"recovery wrap record too short: {len(wrap_record)} bytes "
            f"(minimum {_MIN_RECOVERY_WRAP_BYTES})"
        )
    version = wrap_record[0]
    if version != WRAP_VERSION:
        raise DekEnvelopeError(
            f"unsupported recovery wrap version 0x{version:02X} "
            f"(expected 0x{WRAP_VERSION:02X})"
        )
    if len(recovery_key) != RECOVERY_KEY_BYTES:
        raise DekEnvelopeError(
            f"recovery_key must be {RECOVERY_KEY_BYTES} bytes, got {len(recovery_key)}"
        )
    nonce = wrap_record[1 : 1 + _RECOVERY_NONCE_BYTES]
    ct_and_tag = wrap_record[1 + _RECOVERY_NONCE_BYTES :]
    aesgcm = AESGCM(recovery_key)
    try:
        dek = aesgcm.decrypt(nonce, ct_and_tag, None)
    except InvalidTag as exc:
        raise DekEnvelopeError(
            "recovery wrap authentication failed — wrong recovery key or tampered record"
        ) from exc
    if len(dek) != DEK_BYTES:
        raise DekEnvelopeError(
            f"unwrapped DEK has unexpected length: {len(dek)} bytes (expected {DEK_BYTES})"
        )
    return dek


# ---------------------------------------------------------------------------
# Shared dual-wrap implementation — used by BOTH create() and reseal_dek()
# ---------------------------------------------------------------------------


def _wrap_dek_dual(
    *,
    dek: bytes,
    sealer: "Sealer",
    recovery_key: bytes,
) -> "DekEnvelope":
    """Produce a :class:`DekEnvelope` by wrapping ``dek`` under BOTH schemes.

    This is the single source of truth for the on-disk wrap-record format.  Both
    :meth:`DekEnvelope.create` (fresh CSPRNG DEK) and :func:`reseal_dek`
    (existing DEK, new chip) call this, so the TPM-wrap and recovery-wrap layout
    can never diverge between the two construction paths.

    Args:
        dek:          32-byte DEK to wrap (new or recovered).
        sealer:       Sealer for the TPM wrap (``sealer.seal(dek)``).
        recovery_key: 32-byte recovery key for the recovery wrap.

    Returns:
        A populated :class:`DekEnvelope` (not yet persisted — caller saves).

    Raises:
        ValueError: if ``dek`` is not exactly ``DEK_BYTES`` long, or if
            ``recovery_key`` is not ``RECOVERY_KEY_BYTES`` (the latter via
            :func:`_recovery_wrap`).
    """
    if len(dek) != DEK_BYTES:
        raise ValueError(f"dek must be {DEK_BYTES} bytes, got {len(dek)}")
    tpm_wrap_blob: bytes = sealer.seal(dek)
    # Prefix the TPM wrap blob with the version byte so the keystore format is
    # self-describing and rotation-ready, even though the inner blob is already
    # opaque (the Sealer is free to prepend its own versioning).
    tpm_record = bytes([WRAP_VERSION]) + tpm_wrap_blob
    recovery_record = _recovery_wrap(dek, recovery_key)
    return DekEnvelope(
        sealer=sealer,
        tpm_wrap=tpm_record,
        recovery_wrap=recovery_record,
    )


# ---------------------------------------------------------------------------
# DekEnvelope — the lifecycle object
# ---------------------------------------------------------------------------


class DekEnvelope:
    """Holds the dual-wrapped DEK and manages its lifecycle.

    Construction paths:
    - :meth:`create` — generate a new CSPRNG DEK and wrap it twice immediately.
    - :meth:`load` — read wrap records from a keystore file and unseal lazily on
      first :meth:`unseal_dek` call.

    The raw DEK is available via :meth:`unseal_dek` and MUST be passed to
    :func:`~shared.security.field_cipher.derive_subkeys` rather than used
    directly for any cryptographic operation.  The envelope does not keep the
    DEK in memory after the initial creation / unseal — callers receive it and
    are responsible for any lifecycle management above this layer.

    Note: ``DekEnvelope`` is not a context manager for secrets zeroization —
    Python's garbage collector does not guarantee prompt destruction of bytes
    objects, and that is a threat model (in-memory) explicitly deferred in
    ADR-025 §3 ("Plaintext in RAM during operation — DEFERRED, not denied").
    """

    def __init__(
        self,
        *,
        sealer: Sealer,
        tpm_wrap: bytes,
        recovery_wrap: bytes,
    ) -> None:
        """Low-level constructor — prefer :meth:`create` or :meth:`load`."""
        self._sealer = sealer
        self._tpm_wrap = tpm_wrap
        self._recovery_wrap = recovery_wrap

    # ------------------------------------------------------------------
    # Factory class methods
    # ------------------------------------------------------------------

    @classmethod
    def create(
        cls,
        *,
        sealer: Sealer,
        recovery_key: bytes,
    ) -> "DekEnvelope":
        """Generate a fresh CSPRNG DEK and produce both wrap records.

        The DEK is generated, wrapped, and then discarded from this scope.
        The wrap records are stored in the returned :class:`DekEnvelope`; the
        DEK itself is only available by calling :meth:`unseal_dek`.

        Args:
            sealer:       A :class:`~shared.security.tpm_sealer.Sealer` (TPM
                          or software stub in dev/test).
            recovery_key: 32-byte high-entropy random key.

        Returns:
            A populated :class:`DekEnvelope` with both wrap records.
        """
        dek: bytes = secrets.token_bytes(DEK_BYTES)
        # ``create`` (new DEK) and ``reseal_dek`` (existing DEK) share ONE wrap
        # implementation via :func:`_wrap_dek_dual` so the on-disk format can
        # never diverge between the two construction paths.
        return _wrap_dek_dual(dek=dek, sealer=sealer, recovery_key=recovery_key)

    @classmethod
    def load(
        cls,
        *,
        sealer: Sealer,
        keystore_path: Path | str,
    ) -> "DekEnvelope":
        """Read wrap records from ``keystore_path`` and return a populated envelope.

        The DEK is NOT unsealed at load time; call :meth:`unseal_dek` when you
        actually need it (lazy unseal avoids blocking the constructor on TPM I/O).

        Args:
            sealer:        Sealer to use for the TPM-path unseal.
            keystore_path: Path to the JSON keystore written by :meth:`save`.

        Returns:
            A populated :class:`DekEnvelope` with both wrap records loaded.

        Raises:
            DekEnvelopeError: if the keystore file is missing, malformed, or
                lacks the expected version fields.
        """
        path = Path(keystore_path)
        try:
            raw = path.read_text(encoding="utf-8")
        except OSError as exc:
            raise DekEnvelopeError(f"cannot read keystore at '{path}': {exc}") from exc
        try:
            doc = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise DekEnvelopeError(f"keystore at '{path}' is not valid JSON: {exc}") from exc

        tpm_key = f"{_KEY_TPM_WRAP}{WRAP_VERSION}"
        rec_key = f"{_KEY_RECOVERY_WRAP}{WRAP_VERSION}"

        if tpm_key not in doc:
            raise DekEnvelopeError(
                f"keystore missing expected field '{tpm_key}'; "
                f"available keys: {sorted(doc)}"
            )
        if rec_key not in doc:
            raise DekEnvelopeError(
                f"keystore missing expected field '{rec_key}'; "
                f"available keys: {sorted(doc)}"
            )
        try:
            tpm_record = b64decode(doc[tpm_key])
            recovery_record = b64decode(doc[rec_key])
        except Exception as exc:
            raise DekEnvelopeError(f"keystore base64 decode failed: {exc}") from exc
        return cls(
            sealer=sealer,
            tpm_wrap=tpm_record,
            recovery_wrap=recovery_record,
        )

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def save(self, keystore_path: Path | str) -> None:
        """Persist the wrap records to ``keystore_path`` as a JSON file.

        The file contains ONLY the two opaque wrap records (base64-encoded).
        The DEK is never written to disk.  The keystore MUST be stored on a
        path that is NOT the same partition / volume as the encrypted DBs for
        full threat-model coverage, but that placement policy is the caller's
        responsibility.

        Args:
            keystore_path: Destination path (parent directory must exist).

        Raises:
            OSError: if the file cannot be written.
        """
        path = Path(keystore_path)
        doc: dict[str, str] = {
            f"{_KEY_TPM_WRAP}{WRAP_VERSION}": b64encode(self._tpm_wrap).decode("ascii"),
            f"{_KEY_RECOVERY_WRAP}{WRAP_VERSION}": b64encode(self._recovery_wrap).decode("ascii"),
        }
        path.write_text(json.dumps(doc, indent=2), encoding="utf-8")
        # #637 (DATA_MAP §7 item 1): lock the production DEK keystore to
        # (current user + SYSTEM) full control.  Even though the keystore holds
        # only TPM/recovery-wrapped material (file access != key access), it is
        # the root-of-trust file and warrants the same owner-only DACL as the
        # encrypted DBs.  Owner-preserving + fail-safe; never blocks the write.
        try:
            from shared.security.file_dacl import ensure_owner_only_dacl

            ensure_owner_only_dacl(path)
        except Exception:  # noqa: BLE001 — the keystore write already succeeded
            logger.warning(
                "DEK keystore DACL hardening raised unexpectedly; the keystore "
                "was written with existing ACLs at %s",
                path,
            )

    # ------------------------------------------------------------------
    # DEK access
    # ------------------------------------------------------------------

    def unseal_dek(self, *, recovery_key: bytes | None = None) -> bytes:
        """Unseal and return the raw DEK.

        Unseal order (ADR-025 §2.7):
        1. Try the TPM sealer.
        2. If the TPM fails AND ``recovery_key`` is provided → use the recovery
           wrap.
        3. If neither succeeds → raise :class:`DekEnvelopeError`.

        **There is no plaintext fallback, ever.**

        Args:
            recovery_key: Optional 32-byte recovery key (break-glass path).
                          Supply only when the TPM is unavailable (dead chip /
                          hardware migration).

        Returns:
            32-byte DEK.  Callers MUST pass this to
            :func:`~shared.security.field_cipher.derive_subkeys` and MUST NOT
            use it directly for any cryptographic operation.

        Raises:
            DekEnvelopeError: if neither path can produce the DEK.
        """
        # Strip the version byte we prepended in create() before passing to sealer.
        tpm_inner = self._tpm_wrap[1:]  # version byte is ours, not the sealer's

        # --- TPM path ---
        tpm_error: Exception | None = None
        try:
            dek = self._sealer.unseal(tpm_inner)
            if len(dek) != DEK_BYTES:
                raise DekEnvelopeError(
                    f"TPM-unsealed DEK has unexpected length: {len(dek)} bytes "
                    f"(expected {DEK_BYTES})"
                )
            return dek
        except (TpmUnavailable, TpmSealingError, DekEnvelopeError) as exc:
            tpm_error = exc

        # --- Recovery path ---
        if recovery_key is not None:
            try:
                return self.unseal_via_recovery(recovery_key)
            except DekEnvelopeError as rec_exc:
                raise DekEnvelopeError(
                    f"both unseal paths failed — "
                    f"TPM error: {tpm_error}; recovery error: {rec_exc}"
                ) from rec_exc

        # --- Neither path available → refuse to open ---
        raise DekEnvelopeError(
            f"TPM unseal failed and no recovery key was supplied — "
            f"refusing to open (fail-closed). TPM error: {tpm_error}"
        )

    def unseal_via_recovery(self, recovery_key: bytes) -> bytes:
        """Unwrap the DEK from the **recovery wrap ONLY** — never the TPM path.

        This is the explicit break-glass entry point for a dead / replaced chip
        (ADR-025 §2.7).  Unlike :meth:`unseal_dek`, it does **not** attempt the
        TPM sealer at all: the caller has already decided the TPM is gone, so the
        recovery wrap is the only authority.  This removes any reliance on the
        TPM-then-recovery fallback ORDER (or on a particular sealer raising a
        particular exception type) to reach the recovery key — the recovery path
        is selected by-design, not by-accident.

        Args:
            recovery_key: 32-byte offline recovery key (the one the operator
                          stored off-box at ceremony time).

        Returns:
            32-byte DEK.  Callers MUST pass this to
            :func:`~shared.security.field_cipher.derive_subkeys`.

        Raises:
            DekEnvelopeError: on wrong key, version mismatch, truncated record,
                or authentication failure (fail-closed).
        """
        return _recovery_unwrap(self._recovery_wrap, recovery_key)

    def unseal_via_recovery_hex(self, recovery_key_text: str) -> bytes:
        """Break-glass unwrap driven straight from an operator-entered string.

        The real recovery UX hands the operator a *string* (the hex / grouped
        recovery key printed at ceremony time), not raw bytes.  This method
        routes that string through the single validated parser
        :func:`shared.security.recovery_key_store.parse_hex` — which is
        Fail-Closed on a wrong length, non-hex characters, or a checksum
        mismatch — and then performs the recovery-wrap-ONLY unwrap (never the
        TPM path), exactly like :meth:`unseal_via_recovery`.

        Centralizing the string→bytes step here means the envelope, the
        provisioning ceremony, and any future recovery tool all parse the
        operator's input the same way, instead of each re-implementing the
        64-hex-character validation.

        Args:
            recovery_key_text: The recovery key as the operator typed/pasted
                it (bare hex, dash-grouped, or checksummed-grouped — all the
                forms ``recovery_key_store`` emits).

        Returns:
            32-byte DEK.  Callers MUST pass this to
            :func:`~shared.security.field_cipher.derive_subkeys`.

        Raises:
            DekEnvelopeError: on a malformed recovery string (wrong length,
                bad hex, checksum mismatch) or on unwrap/authentication
                failure (fail-closed).  The recovery-key-store's
                ``RecoveryKeyError`` is re-raised as ``DekEnvelopeError`` so a
                single break-glass call site catches one exception type and so
                no key fragment leaks via a differently-typed error.
        """
        # Imported here (not at module scope) because recovery_key_store imports
        # RECOVERY_KEY_BYTES from this module — a top-level import would cycle.
        from shared.security.recovery_key_store import (
            RecoveryKeyError,
            parse_hex,
        )

        try:
            recovery_key = parse_hex(recovery_key_text)
        except RecoveryKeyError as exc:
            raise DekEnvelopeError(f"invalid recovery key string: {exc}") from exc
        return _recovery_unwrap(self._recovery_wrap, recovery_key)

    # ------------------------------------------------------------------
    # Read-only accessors for the merge gate / test introspection
    # ------------------------------------------------------------------

    @property
    def tpm_wrap_record(self) -> bytes:
        """The raw TPM wrap record bytes (version-prefixed, opaque)."""
        return self._tpm_wrap

    @property
    def recovery_wrap_record(self) -> bytes:
        """The raw recovery wrap record bytes (version-prefixed)."""
        return self._recovery_wrap


# ---------------------------------------------------------------------------
# generate_recovery_key — ceremony helper
# ---------------------------------------------------------------------------


def generate_recovery_key() -> bytes:
    """Generate a fresh high-entropy 256-bit recovery key.

    This is called **once** during the ceremony; the returned bytes are the
    key the Lead Architect prints and/or stores on a USB drive off-box.  It
    must NOT be stored on the running disk in cleartext.

    Returns:
        32 cryptographically-random bytes.
    """
    return secrets.token_bytes(RECOVERY_KEY_BYTES)


# ---------------------------------------------------------------------------
# Fail-Closed factory — the ONLY production construction path
# ---------------------------------------------------------------------------


def build_envelope(
    *,
    sealer: Sealer,
    recovery_key: bytes,
    keystore_path: Path | str,
    dev_mode: bool = False,
) -> DekEnvelope:
    """Build and persist a fresh :class:`DekEnvelope` — the production factory.

    This is the **only** sanctioned way to provision a new DEK.  It refuses a
    :class:`~shared.security.tpm_sealer.SoftwareSealer` outside explicit
    ``dev_mode=True``, enforcing the constraint EA-1 deliberately delegated to
    this consumer (ADR-025 §2.7 / tpm_sealer.py§SoftwareSealer docstring).

    Args:
        sealer:        A :class:`~shared.security.tpm_sealer.Sealer`.  MUST be
                       a :class:`~shared.security.tpm_sealer.TpmSealer` in
                       production (``dev_mode=False``).
        recovery_key:  32-byte high-entropy random recovery key (from a CSPRNG;
                       not a passphrase).  Produced by :func:`generate_recovery_key`
                       at ceremony time and stored off-box by the Lead Architect.
        keystore_path: Path where the wrap records are persisted.  The DEK is
                       **never** written here or anywhere else in cleartext.
        dev_mode:      When ``True``, permits a ``SoftwareSealer`` (dev / test
                       use only — no security guarantee).  Defaults to ``False``.

    Returns:
        A populated and persisted :class:`DekEnvelope` (wrap records on disk).

    Raises:
        DevModeSealerError: if ``not dev_mode`` and ``sealer`` is a
            :class:`~shared.security.tpm_sealer.SoftwareSealer`.  This is the
            load-bearing production guard.
        ValueError: if ``recovery_key`` is not exactly 32 bytes.
        OSError: if the keystore file cannot be written.
    """
    if not dev_mode and isinstance(sealer, SoftwareSealer):
        raise DevModeSealerError(
            "SECURITY ENFORCEMENT: SoftwareSealer is NOT permitted in production "
            "(dev_mode=False).  The SoftwareSealer uses a hard-coded public key "
            "and provides NO security guarantee.  Pass dev_mode=True to use it "
            "in a development or test context, or supply a TpmSealer for production."
        )
    if len(recovery_key) != RECOVERY_KEY_BYTES:
        raise ValueError(
            f"recovery_key must be {RECOVERY_KEY_BYTES} bytes, "
            f"got {len(recovery_key)} bytes"
        )
    envelope = DekEnvelope.create(sealer=sealer, recovery_key=recovery_key)
    envelope.save(keystore_path)
    return envelope


# ---------------------------------------------------------------------------
# reseal_dek — re-wrap an EXISTING DEK onto a new chip (break-glass recovery)
# ---------------------------------------------------------------------------


def reseal_dek(
    dek: bytes,
    *,
    sealer: Sealer,
    recovery_key: bytes,
    dev_mode: bool = False,
) -> DekEnvelope:
    """Re-wrap an **existing** DEK under a new TPM seal + a fresh recovery wrap.

    The break-glass counterpart to :func:`build_envelope`.  Where
    ``build_envelope`` generates a brand-new DEK, ``reseal_dek`` takes a DEK that
    was recovered via :meth:`DekEnvelope.unseal_via_recovery` (dead-chip path)
    and re-seals that **same DEK** so the encrypted data on disk stays readable
    after a hardware migration.  **No new DEK is generated.**

    Shares the single dual-wrap implementation (:func:`_wrap_dek_dual`) with
    :meth:`DekEnvelope.create`, so the two paths produce byte-identical record
    formats.  The returned envelope is NOT persisted — the caller saves it (the
    ceremony writes it to the keystore and then verifies the round-trip).

    Args:
        dek:          The recovered 32-byte DEK to re-wrap.
        sealer:       The NEW machine's :class:`~shared.security.tpm_sealer.Sealer`.
                      MUST be a :class:`~shared.security.tpm_sealer.TpmSealer` in
                      production (``dev_mode=False``).
        recovery_key: A FRESH 32-byte recovery key for the new keystore (the old
                      recovery key is retired once the new keystore is written).
        dev_mode:     When ``True``, permits a ``SoftwareSealer`` (dev / test
                      only).  Defaults to ``False`` (production guard, mirroring
                      :func:`build_envelope`).

    Returns:
        A populated (un-persisted) :class:`DekEnvelope` wrapping the same DEK.

    Raises:
        DevModeSealerError: if ``not dev_mode`` and ``sealer`` is a
            :class:`~shared.security.tpm_sealer.SoftwareSealer`.
        ValueError: if ``dek`` is not ``DEK_BYTES`` or ``recovery_key`` is not
            ``RECOVERY_KEY_BYTES``.
    """
    if not dev_mode and isinstance(sealer, SoftwareSealer):
        raise DevModeSealerError(
            "SECURITY ENFORCEMENT: SoftwareSealer is NOT permitted in production "
            "(dev_mode=False).  The SoftwareSealer uses a hard-coded public key "
            "and provides NO security guarantee.  Pass dev_mode=True to use it "
            "in a development or test context, or supply a TpmSealer for production."
        )
    if len(recovery_key) != RECOVERY_KEY_BYTES:
        raise ValueError(
            f"recovery_key must be {RECOVERY_KEY_BYTES} bytes, "
            f"got {len(recovery_key)} bytes"
        )
    return _wrap_dek_dual(dek=dek, sealer=sealer, recovery_key=recovery_key)
