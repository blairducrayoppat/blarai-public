"""TPM 2.0-backed key-sealing (RSA-OAEP wrap/unwrap) via the Windows CNG
*Microsoft Platform Crypto Provider*.

Sealing primitive for Sprint 14 at-rest encryption (ADR-018 §Tier-2 extension).
Provides a **non-exportable** hardware-backed RSA-2048 key used to wrap/unwrap a
symmetric data-encryption key (DEK). The private RSA key is generated inside the
platform TPM 2.0 and cannot be exported, even by the creating process.

Deliberately separate from ``tpm_signer.py`` (ECDSA sign/verify) — the two CNG
operations have different failure modes, different key types, and different roles in
the security design. Signing is not sealing; keeping the modules apart makes both
auditable in isolation.

Design constraints (mirrored from ``tpm_signer.py``):
  - **No external network. No new dependencies** — stdlib ``ctypes`` → ``ncrypt.dll``
    for the TPM path; ``cryptography`` (already present, 46.0.5) only for the
    software stub.
  - **Portable + Fail-Closed:** importable on any OS; every TPM operation raises
    ``TpmUnavailable`` on non-Windows / no-provider.
  - **Non-exportability is the proven CNG default** for persisted keys (we never set
    ``NCRYPT_ALLOW_EXPORT``).
  - **Input-length validation:** RSA-2048 OAEP-SHA-256 max plaintext =
    ``2048/8 - 2*32 - 2 = 190 bytes``. A 32-byte AES-256 DEK fits in one block
    (no chunking). Inputs exceeding that limit raise ``TpmSealingError`` before any
    CNG call.
"""

from __future__ import annotations

import logging
import os
import sys
from typing import Protocol, runtime_checkable

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants — provider, algorithm, CNG status codes, and flags
# ---------------------------------------------------------------------------

PROVIDER_NAME: str = "Microsoft Platform Crypto Provider"
ALG_RSA: str = "RSA"

# SECURITY_STATUS / NTSTATUS codes (compared as unsigned 32-bit).
_ERROR_SUCCESS: int = 0x00000000
_NTE_BAD_KEYSET: int = 0x80090016  # key / keyset does not exist

# CNG flags.
_NCRYPT_SILENT_FLAG: int = 0x00000040
_NCRYPT_OVERWRITE_KEY_FLAG: int = 0x00000080

# NCrypt property name for key length (RSA modulus size in bits).
_NCRYPT_LENGTH_PROPERTY: str = "Length"

# RSA-2048 OAEP-SHA-256 maximum plaintext size:
#   modulus_bytes - 2*hash_bytes - 2  =  256 - 64 - 2  =  190 bytes.
# A 32-byte AES-256 DEK is well inside this limit; the cap is validated
# before any CNG call so callers never silently truncate.
_RSA2048_OAEP_SHA256_MAX_PLAINTEXT: int = 190
_RSA_KEY_BITS: int = 2048


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class TpmUnavailable(RuntimeError):
    """Raised when no usable TPM 2.0 / CNG provider is present (Fail-Closed)."""


class TpmSealingError(RuntimeError):
    """Raised on an unexpected CNG/NCrypt failure during a TPM sealing operation."""


# ---------------------------------------------------------------------------
# Public interface — Sealer Protocol
# ---------------------------------------------------------------------------


@runtime_checkable
class Sealer(Protocol):
    """Minimal protocol for key-sealing implementations.

    Both ``TpmSealer`` and ``SoftwareSealer`` satisfy this protocol; callers
    receive a ``Sealer`` and are indifferent to the concrete implementation.
    """

    def seal(self, key_material: bytes) -> bytes:
        """Wrap ``key_material`` (a DEK) and return an opaque sealed blob."""
        ...

    def unseal(self, blob: bytes) -> bytes:
        """Unwrap a sealed blob and return the original ``key_material``."""
        ...


# ---------------------------------------------------------------------------
# Lazy CNG loader (mirrors _api() in tpm_signer.py)
# ---------------------------------------------------------------------------

_API: object = None  # cached (ctypes_module, configured_ncrypt_dll)


def _api():
    """Lazily load + configure ``ncrypt.dll``. Raises ``TpmUnavailable`` off-Windows."""
    global _API
    if sys.platform != "win32":
        raise TpmUnavailable("TPM sealing requires Windows (CNG ncrypt.dll)")
    if _API is not None:
        return _API
    import ctypes
    from ctypes import wintypes

    try:
        d = ctypes.WinDLL("ncrypt")
    except OSError as exc:  # pragma: no cover - platform specific
        raise TpmUnavailable(f"ncrypt.dll not loadable: {exc}") from exc

    ss = ctypes.c_long  # SECURITY_STATUS
    vp = ctypes.c_void_p
    ul = ctypes.c_ulong
    pul = ctypes.POINTER(ctypes.c_ulong)
    lpcwstr = wintypes.LPCWSTR

    d.NCryptOpenStorageProvider.restype = ss
    d.NCryptOpenStorageProvider.argtypes = [ctypes.POINTER(vp), lpcwstr, ul]
    d.NCryptCreatePersistedKey.restype = ss
    d.NCryptCreatePersistedKey.argtypes = [vp, ctypes.POINTER(vp), lpcwstr, lpcwstr, ul, ul]
    d.NCryptSetProperty.restype = ss
    d.NCryptSetProperty.argtypes = [vp, lpcwstr, vp, ul, ul]
    d.NCryptFinalizeKey.restype = ss
    d.NCryptFinalizeKey.argtypes = [vp, ul]
    d.NCryptOpenKey.restype = ss
    d.NCryptOpenKey.argtypes = [vp, ctypes.POINTER(vp), lpcwstr, ul, ul]
    d.NCryptEncrypt.restype = ss
    d.NCryptEncrypt.argtypes = [vp, vp, ul, vp, vp, ul, pul, ul]
    d.NCryptDecrypt.restype = ss
    d.NCryptDecrypt.argtypes = [vp, vp, ul, vp, vp, ul, pul, ul]
    d.NCryptExportKey.restype = ss
    d.NCryptExportKey.argtypes = [vp, vp, lpcwstr, vp, vp, ul, pul, ul]
    d.NCryptDeleteKey.restype = ss
    d.NCryptDeleteKey.argtypes = [vp, ul]
    d.NCryptFreeObject.restype = ss
    d.NCryptFreeObject.argtypes = [vp]

    _API = (ctypes, d)
    return _API


def _u32(status: int) -> int:
    """Normalize a SECURITY_STATUS to unsigned 32-bit for comparison."""
    return status & 0xFFFFFFFF


def _open_provider(ctypes, d):
    h = ctypes.c_void_p()
    s = _u32(d.NCryptOpenStorageProvider(ctypes.byref(h), PROVIDER_NAME, 0))
    if s != _ERROR_SUCCESS:
        raise TpmUnavailable(f"NCryptOpenStorageProvider failed: 0x{s:08X}")
    return h


def _open_key(ctypes, d, h, key_name: str):
    hk = ctypes.c_void_p()
    s = _u32(d.NCryptOpenKey(h, ctypes.byref(hk), key_name, 0, _NCRYPT_SILENT_FLAG))
    if s != _ERROR_SUCCESS:
        raise TpmSealingError(f"open TPM seal key '{key_name}' failed: 0x{s:08X}")
    return hk


# ---------------------------------------------------------------------------
# Low-level key existence helper
# ---------------------------------------------------------------------------


def key_exists(key_name: str) -> bool:
    """True iff a persisted TPM seal key named ``key_name`` exists."""
    ctypes, d = _api()
    h = _open_provider(ctypes, d)
    try:
        hk = ctypes.c_void_p()
        s = _u32(d.NCryptOpenKey(h, ctypes.byref(hk), key_name, 0, _NCRYPT_SILENT_FLAG))
        if s == _ERROR_SUCCESS:
            d.NCryptFreeObject(hk)
            return True
        if s == _NTE_BAD_KEYSET:
            return False
        raise TpmSealingError(f"NCryptOpenKey('{key_name}') probe failed: 0x{s:08X}")
    finally:
        d.NCryptFreeObject(h)


# ---------------------------------------------------------------------------
# Idempotent key provisioning
# ---------------------------------------------------------------------------


def ensure_key(key_name: str) -> bool:
    """Create a persisted, non-exportable RSA-2048 TPM seal key if absent.

    Returns True if a new key was created, False if it already existed.
    Idempotent: safe to call every boot (provisioning is one-time).
    The key is finalized WITHOUT ``NCRYPT_ALLOW_EXPORT`` — the private key
    never leaves the TPM.
    """
    ctypes, d = _api()
    h = _open_provider(ctypes, d)
    try:
        if key_exists(key_name):
            return False
        hk = ctypes.c_void_p()
        s = _u32(d.NCryptCreatePersistedKey(
            h, ctypes.byref(hk), ALG_RSA, key_name, 0, _NCRYPT_OVERWRITE_KEY_FLAG
        ))
        if s != _ERROR_SUCCESS:
            raise TpmSealingError(f"NCryptCreatePersistedKey failed: 0x{s:08X}")
        try:
            # Set the RSA key length to 2048 bits.
            key_bits = ctypes.c_ulong(_RSA_KEY_BITS)
            s = _u32(d.NCryptSetProperty(
                hk,
                _NCRYPT_LENGTH_PROPERTY,
                ctypes.byref(key_bits),
                ctypes.sizeof(key_bits),
                0,
            ))
            if s != _ERROR_SUCCESS:
                raise TpmSealingError(f"NCryptSetProperty(Length) failed: 0x{s:08X}")
            # Finalize without NCRYPT_ALLOW_EXPORT => private key non-exportable.
            s = _u32(d.NCryptFinalizeKey(hk, _NCRYPT_SILENT_FLAG))
            if s != _ERROR_SUCCESS:
                raise TpmSealingError(f"NCryptFinalizeKey failed: 0x{s:08X}")
        finally:
            d.NCryptFreeObject(hk)
        logger.info("Provisioned non-exportable TPM RSA-2048 seal key '%s'", key_name)
        return True
    finally:
        d.NCryptFreeObject(h)


# ---------------------------------------------------------------------------
# BCRYPT_OAEP_PADDING_INFO helper
# ---------------------------------------------------------------------------


def _make_oaep_info(ctypes):
    """Build a ``BCRYPT_OAEP_PADDING_INFO`` struct for SHA-256 / MGF1-SHA-256.

    The struct layout (from bcrypt.h):
        LPCWSTR pszAlgId;   // offset 0, pointer-size
        PUCHAR  pbLabel;    // offset ptr_size
        ULONG   cbLabel;    // offset 2*ptr_size
    We use a zero-length label (pbLabel=NULL, cbLabel=0) per RFC 8017 §7.1.1.
    """
    ptr_size = ctypes.sizeof(ctypes.c_void_p)

    class _BCRYPT_OAEP_PADDING_INFO(ctypes.Structure):
        _fields_ = [
            ("pszAlgId", ctypes.c_wchar_p),
            ("pbLabel", ctypes.c_void_p),
            ("cbLabel", ctypes.c_ulong),
        ]

    info = _BCRYPT_OAEP_PADDING_INFO()
    info.pszAlgId = "SHA256"
    info.pbLabel = None
    info.cbLabel = 0
    return info


# BCRYPT_PAD_OAEP flag value (from bcrypt.h).
_BCRYPT_PAD_OAEP: int = 0x00000004


# ---------------------------------------------------------------------------
# TpmSealer — real TPM-backed implementation
# ---------------------------------------------------------------------------


class TpmSealer:
    """RSA-2048 TPM key seal/unseal via ``NCryptEncrypt``/``NCryptDecrypt`` (OAEP SHA-256).

    The persisted key is non-exportable; the private half never leaves the TPM.
    Use ``ensure_key(key_name)`` to provision the key before constructing a
    ``TpmSealer`` instance (or let the constructor call it lazily via ``_ensure``).

    ``seal()`` and ``unseal()`` operate on short byte strings (a 32-byte AES-256 DEK
    fits comfortably in one RSA-2048 OAEP block). Inputs longer than
    ``_RSA2048_OAEP_SHA256_MAX_PLAINTEXT`` (190 bytes) raise ``TpmSealingError``
    immediately — this primitive is for DEK wrapping, not bulk encryption.
    """

    def __init__(self, key_name: str, *, auto_provision: bool = True) -> None:
        """
        Args:
            key_name: Name of the persisted TPM key (e.g. ``"BlarAI-DEKSeal"``).
            auto_provision: If True (default), call ``ensure_key(key_name)`` on
                construction so the key is ready without a separate ceremony step.
                Set False in the ceremony runner that provisions keys explicitly.
        """
        # Trigger the lazy loader here so that TpmUnavailable fires at construction
        # time rather than at the first seal/unseal call (Fail-Closed discipline).
        _api()
        self._key_name = key_name
        if auto_provision:
            ensure_key(key_name)

    @property
    def key_name(self) -> str:
        return self._key_name

    def seal(self, key_material: bytes) -> bytes:
        """Wrap ``key_material`` with the TPM RSA-2048 key (RSA-OAEP SHA-256).

        Returns the ciphertext blob (256 bytes for an RSA-2048 key).
        Raises ``TpmSealingError`` if ``key_material`` exceeds the OAEP limit or
        if CNG reports a failure. Raises ``TpmUnavailable`` if no TPM is present.
        """
        if len(key_material) > _RSA2048_OAEP_SHA256_MAX_PLAINTEXT:
            raise TpmSealingError(
                f"seal() input too large: {len(key_material)} bytes "
                f"(RSA-2048 OAEP-SHA-256 max = {_RSA2048_OAEP_SHA256_MAX_PLAINTEXT})"
            )
        ctypes, d = _api()
        h = _open_provider(ctypes, d)
        try:
            hk = _open_key(ctypes, d, h, self._key_name)
            try:
                oaep = _make_oaep_info(ctypes)
                inbuf = (ctypes.c_ubyte * len(key_material)).from_buffer_copy(key_material)
                cb = ctypes.c_ulong(0)
                # Size probe.
                s = _u32(d.NCryptEncrypt(
                    hk, inbuf, len(key_material),
                    ctypes.byref(oaep),
                    None, 0, ctypes.byref(cb),
                    _BCRYPT_PAD_OAEP,
                ))
                if s != _ERROR_SUCCESS:
                    raise TpmSealingError(f"NCryptEncrypt(size probe) failed: 0x{s:08X}")
                outbuf = (ctypes.c_ubyte * cb.value)()
                s = _u32(d.NCryptEncrypt(
                    hk, inbuf, len(key_material),
                    ctypes.byref(oaep),
                    outbuf, cb.value, ctypes.byref(cb),
                    _BCRYPT_PAD_OAEP,
                ))
                if s != _ERROR_SUCCESS:
                    raise TpmSealingError(f"NCryptEncrypt failed: 0x{s:08X}")
                return bytes(outbuf[: cb.value])
            finally:
                d.NCryptFreeObject(hk)
        finally:
            d.NCryptFreeObject(h)

    def unseal(self, blob: bytes) -> bytes:
        """Unwrap a sealed blob with the TPM RSA-2048 key (RSA-OAEP SHA-256).

        Returns the original ``key_material``.
        Raises ``TpmSealingError`` on CNG failure (wrong key, corrupted blob, etc.).
        Raises ``TpmUnavailable`` if no TPM is present.
        """
        ctypes, d = _api()
        h = _open_provider(ctypes, d)
        try:
            hk = _open_key(ctypes, d, h, self._key_name)
            try:
                oaep = _make_oaep_info(ctypes)
                inbuf = (ctypes.c_ubyte * len(blob)).from_buffer_copy(blob)
                cb = ctypes.c_ulong(0)
                # Size probe.
                s = _u32(d.NCryptDecrypt(
                    hk, inbuf, len(blob),
                    ctypes.byref(oaep),
                    None, 0, ctypes.byref(cb),
                    _BCRYPT_PAD_OAEP,
                ))
                if s != _ERROR_SUCCESS:
                    raise TpmSealingError(f"NCryptDecrypt(size probe) failed: 0x{s:08X}")
                outbuf = (ctypes.c_ubyte * cb.value)()
                s = _u32(d.NCryptDecrypt(
                    hk, inbuf, len(blob),
                    ctypes.byref(oaep),
                    outbuf, cb.value, ctypes.byref(cb),
                    _BCRYPT_PAD_OAEP,
                ))
                if s != _ERROR_SUCCESS:
                    raise TpmSealingError(f"NCryptDecrypt failed: 0x{s:08X}")
                return bytes(outbuf[: cb.value])
            finally:
                d.NCryptFreeObject(hk)
        finally:
            d.NCryptFreeObject(h)


# ---------------------------------------------------------------------------
# SoftwareSealer — test / off-TPM stub
# ---------------------------------------------------------------------------


class SoftwareSealer:
    """AES-256-GCM stub sealer for tests and off-TPM environments.

    **THIS IS NOT A SECURITY BOUNDARY.** The sealing key is derived from a
    hard-coded constant; any party with access to this source can unseal blobs.
    ``SoftwareSealer`` exists solely so that layers above it (the DEK envelope,
    the substrate store, the session store) can be fully tested on any machine
    without a TPM 2.0. It satisfies the ``Sealer`` protocol identically to
    ``TpmSealer``.

    In production, ``TpmSealer`` is the only acceptable implementation.  The
    existence of ``SoftwareSealer`` in the codebase is not a fallback — it is a
    test fixture.  The production factory MUST refuse to construct a
    ``SoftwareSealer`` in any mode that is not explicitly flagged as development
    or test (this enforcement is the responsibility of the factory, not this
    class).
    """

    # A fixed, public, intentionally-weak key.  Named to make any accidental
    # production use conspicuous in logs / heap dumps.
    _NOT_SECRET_KEY: bytes = b"SOFTWARE-SEALER-NOT-A-SECRET-KEY"  # 32 bytes

    def __init__(self) -> None:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM

        self._aesgcm = AESGCM(self._NOT_SECRET_KEY)

    def seal(self, key_material: bytes) -> bytes:
        """Wrap ``key_material`` with a fixed AES-256-GCM key (NOT production-safe).

        The sealed blob is ``nonce || ciphertext || tag`` (12 + len + 16 bytes).
        The nonce is freshly randomized per call, so two calls on the same input
        produce different blobs.
        """
        if len(key_material) > _RSA2048_OAEP_SHA256_MAX_PLAINTEXT:
            raise TpmSealingError(
                f"seal() input too large: {len(key_material)} bytes "
                f"(limit = {_RSA2048_OAEP_SHA256_MAX_PLAINTEXT})"
            )
        nonce = os.urandom(12)
        ct = self._aesgcm.encrypt(nonce, key_material, None)
        return nonce + ct

    def unseal(self, blob: bytes) -> bytes:
        """Unwrap a blob produced by ``seal()``.

        Raises ``TpmSealingError`` if the blob is too short, the tag is wrong
        (tampered / wrong key), or any other authentication failure.
        """
        from cryptography.exceptions import InvalidTag

        if len(blob) < 12 + 16:  # nonce + minimum GCM tag
            raise TpmSealingError(
                f"unseal() blob too short: {len(blob)} bytes (minimum 28)"
            )
        nonce, ct = blob[:12], blob[12:]
        try:
            return self._aesgcm.decrypt(nonce, ct, None)
        except InvalidTag as exc:
            raise TpmSealingError("SoftwareSealer: authentication failed (tampered or wrong key)") from exc


# ---------------------------------------------------------------------------
# is_available helper (mirrors tpm_signer.is_available)
# ---------------------------------------------------------------------------


def is_available() -> bool:
    """True iff a usable TPM 2.0 is reachable via the CNG Platform Crypto Provider."""
    if sys.platform != "win32":
        return False
    try:
        ctypes, d = _api()
        h = _open_provider(ctypes, d)
        d.NCryptFreeObject(h)
        return True
    except (TpmUnavailable, TpmSealingError, OSError):
        return False


# ---------------------------------------------------------------------------
# delete_key — used by tests and re-provisioning ceremony
# ---------------------------------------------------------------------------


def delete_key(key_name: str) -> None:
    """Delete a persisted TPM seal key (used by tests + re-provisioning ceremony)."""
    ctypes, d = _api()
    h = _open_provider(ctypes, d)
    try:
        hk = _open_key(ctypes, d, h, key_name)
        # NCryptDeleteKey frees the handle on success.  The TPM provider rejects
        # NCRYPT_SILENT_FLAG here (NTE_BAD_FLAGS 0x80090009); dwFlags must be 0.
        # (Same quirk documented in tpm_signer.py::delete_key.)
        s = _u32(d.NCryptDeleteKey(hk, 0))
        if s != _ERROR_SUCCESS:
            d.NCryptFreeObject(hk)
            raise TpmSealingError(f"NCryptDeleteKey('{key_name}') failed: 0x{s:08X}")
    finally:
        d.NCryptFreeObject(h)
