"""TPM 2.0-backed signing via the Windows CNG *Microsoft Platform Crypto Provider*.

Host-side trust-root primitive (ADR-018). Provides **non-exportable**
hardware-backed signing keys: the private key is generated *inside* the platform
TPM 2.0 and cannot be exported, even by the creating process. Used by:

  - FUT-04 — signing the model-weight integrity manifest (tamper-evident weights).
  - FUT-01 — the CA signing key (future; host-vs-VM wiring is a separate decision).

Hardware note (ISS-4 / `docs/TPM_CAPABILITY_FINDINGS.md`): on the reference unit
the active TPM 2.0 is an STMicroelectronics TPM (Microsoft Pluton is *also*
present but not serving as the TPM). This module is vendor-agnostic — it binds to
whatever TPM 2.0 the *Microsoft Platform Crypto Provider* exposes.

Design constraints:
  - **No external network. No new dependencies** (stdlib ``ctypes`` → ``ncrypt.dll``).
  - **Portable + Fail-Closed:** importable on any OS; every TPM operation raises
    ``TpmUnavailable`` on non-Windows / no-TPM. Callers that *require* a valid
    signature must treat unavailability as verification failure.
  - **Non-exportability is the proven CNG default** for persisted keys (we never
    set ``NCRYPT_ALLOW_EXPORT``); ``test_tpm_signer`` asserts export is refused
    rather than assuming it.

Verification uses the persisted key directly (``NCryptVerifySignature``), so
same-machine boot verification needs no separate public-key handling;
``export_public_key`` exists for backup / off-box verification.
"""

from __future__ import annotations

import hashlib
import logging
import sys
from typing import Final

logger = logging.getLogger(__name__)

PROVIDER_NAME: Final[str] = "Microsoft Platform Crypto Provider"
ALG_ECDSA_P256: Final[str] = "ECDSA_P256"
_BLOB_ECC_PUBLIC: Final[str] = "ECCPUBLICBLOB"

# SECURITY_STATUS / NTSTATUS codes (compared as unsigned 32-bit).
_ERROR_SUCCESS: Final[int] = 0x00000000
_NTE_BAD_SIGNATURE: Final[int] = 0x80090006
_NTE_BAD_KEYSET: Final[int] = 0x80090016  # key/keyset does not exist

# CNG flags.
_NCRYPT_SILENT_FLAG: Final[int] = 0x00000040
_NCRYPT_OVERWRITE_KEY_FLAG: Final[int] = 0x00000080


class TpmUnavailable(RuntimeError):
    """Raised when no usable TPM 2.0 / CNG provider is present (Fail-Closed)."""


class TpmSigningError(RuntimeError):
    """Raised on an unexpected CNG/NCrypt failure during a TPM operation."""


_API: object = None  # cached (ctypes_module, configured_ncrypt_dll)


def _api():
    """Lazily load + configure ``ncrypt.dll``. Raises ``TpmUnavailable`` off-Windows."""
    global _API
    if sys.platform != "win32":
        raise TpmUnavailable("TPM signing requires Windows (CNG ncrypt.dll)")
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
    d.NCryptFinalizeKey.restype = ss
    d.NCryptFinalizeKey.argtypes = [vp, ul]
    d.NCryptOpenKey.restype = ss
    d.NCryptOpenKey.argtypes = [vp, ctypes.POINTER(vp), lpcwstr, ul, ul]
    d.NCryptSignHash.restype = ss
    d.NCryptSignHash.argtypes = [vp, vp, vp, ul, vp, ul, pul, ul]
    d.NCryptVerifySignature.restype = ss
    d.NCryptVerifySignature.argtypes = [vp, vp, vp, ul, vp, ul, ul]
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


def is_available() -> bool:
    """True iff a usable TPM 2.0 is reachable via the CNG Platform Crypto Provider."""
    if sys.platform != "win32":
        return False
    try:
        ctypes, d = _api()
        h = _open_provider(ctypes, d)
        d.NCryptFreeObject(h)
        return True
    except (TpmUnavailable, TpmSigningError, OSError):
        return False


def key_exists(key_name: str) -> bool:
    """True iff a persisted TPM key named ``key_name`` exists."""
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
        raise TpmSigningError(f"NCryptOpenKey('{key_name}') error: 0x{s:08X}")
    finally:
        d.NCryptFreeObject(h)


def ensure_key(key_name: str) -> bool:
    """Create a persisted, non-exportable ECDSA P-256 TPM key if absent.

    Returns True if a new key was created, False if it already existed.
    Idempotent: safe to call every boot (provisioning is one-time).
    """
    ctypes, d = _api()
    h = _open_provider(ctypes, d)
    try:
        if key_exists(key_name):
            return False
        hk = ctypes.c_void_p()
        s = _u32(d.NCryptCreatePersistedKey(
            h, ctypes.byref(hk), ALG_ECDSA_P256, key_name, 0, _NCRYPT_OVERWRITE_KEY_FLAG
        ))
        if s != _ERROR_SUCCESS:
            raise TpmSigningError(f"NCryptCreatePersistedKey failed: 0x{s:08X}")
        try:
            # No NCRYPT_ALLOW_EXPORT set => private key is non-exportable (CNG
            # default for persisted keys; asserted by test_tpm_signer).
            s = _u32(d.NCryptFinalizeKey(hk, _NCRYPT_SILENT_FLAG))
            if s != _ERROR_SUCCESS:
                raise TpmSigningError(f"NCryptFinalizeKey failed: 0x{s:08X}")
        finally:
            d.NCryptFreeObject(hk)
        logger.info("Provisioned non-exportable TPM signing key '%s'", key_name)
        return True
    finally:
        d.NCryptFreeObject(h)


def _open_key(ctypes, d, h, key_name):
    hk = ctypes.c_void_p()
    s = _u32(d.NCryptOpenKey(h, ctypes.byref(hk), key_name, 0, _NCRYPT_SILENT_FLAG))
    if s != _ERROR_SUCCESS:
        raise TpmSigningError(f"open TPM key '{key_name}' failed: 0x{s:08X}")
    return hk


def sign(key_name: str, data: bytes) -> bytes:
    """Sign ``data`` (SHA-256 then ECDSA) with the persisted TPM key. Returns the raw signature."""
    digest = hashlib.sha256(data).digest()
    ctypes, d = _api()
    h = _open_provider(ctypes, d)
    try:
        hk = _open_key(ctypes, d, h, key_name)
        try:
            hbuf = (ctypes.c_ubyte * len(digest)).from_buffer_copy(digest)
            cb = ctypes.c_ulong(0)
            s = _u32(d.NCryptSignHash(hk, None, hbuf, len(digest), None, 0, ctypes.byref(cb), _NCRYPT_SILENT_FLAG))
            if s != _ERROR_SUCCESS:
                raise TpmSigningError(f"NCryptSignHash(size) failed: 0x{s:08X}")
            sig = (ctypes.c_ubyte * cb.value)()
            s = _u32(d.NCryptSignHash(hk, None, hbuf, len(digest), sig, cb.value, ctypes.byref(cb), _NCRYPT_SILENT_FLAG))
            if s != _ERROR_SUCCESS:
                raise TpmSigningError(f"NCryptSignHash failed: 0x{s:08X}")
            return bytes(sig[: cb.value])
        finally:
            d.NCryptFreeObject(hk)
    finally:
        d.NCryptFreeObject(h)


def verify(key_name: str, data: bytes, signature: bytes) -> bool:
    """Verify ``signature`` over ``data`` using the persisted TPM key.

    Returns True if valid, False if the signature is bad. Raises ``TpmSigningError``
    on an unexpected CNG failure and ``TpmUnavailable`` if no TPM is present —
    callers requiring a valid signature must treat both as failure (Fail-Closed).
    """
    digest = hashlib.sha256(data).digest()
    ctypes, d = _api()
    h = _open_provider(ctypes, d)
    try:
        hk = _open_key(ctypes, d, h, key_name)
        try:
            hbuf = (ctypes.c_ubyte * len(digest)).from_buffer_copy(digest)
            sbuf = (ctypes.c_ubyte * len(signature)).from_buffer_copy(signature)
            s = _u32(d.NCryptVerifySignature(hk, None, hbuf, len(digest), sbuf, len(signature), _NCRYPT_SILENT_FLAG))
            if s == _ERROR_SUCCESS:
                return True
            if s == _NTE_BAD_SIGNATURE:
                return False
            raise TpmSigningError(f"NCryptVerifySignature error: 0x{s:08X}")
        finally:
            d.NCryptFreeObject(hk)
    finally:
        d.NCryptFreeObject(h)


def export_public_key(key_name: str) -> bytes:
    """Export the PUBLIC key (BCRYPT_ECCPUBLIC_BLOB). The private key never exports."""
    ctypes, d = _api()
    h = _open_provider(ctypes, d)
    try:
        hk = _open_key(ctypes, d, h, key_name)
        try:
            cb = ctypes.c_ulong(0)
            s = _u32(d.NCryptExportKey(hk, None, _BLOB_ECC_PUBLIC, None, None, 0, ctypes.byref(cb), 0))
            if s != _ERROR_SUCCESS:
                raise TpmSigningError(f"NCryptExportKey(size) failed: 0x{s:08X}")
            out = (ctypes.c_ubyte * cb.value)()
            s = _u32(d.NCryptExportKey(hk, None, _BLOB_ECC_PUBLIC, None, out, cb.value, ctypes.byref(cb), 0))
            if s != _ERROR_SUCCESS:
                raise TpmSigningError(f"NCryptExportKey failed: 0x{s:08X}")
            return bytes(out[: cb.value])
        finally:
            d.NCryptFreeObject(hk)
    finally:
        d.NCryptFreeObject(h)


def export_public_key_pem(key_name: str) -> bytes:
    """Export the persisted key's PUBLIC half as a SubjectPublicKeyInfo PEM.

    Parses the CNG ``BCRYPT_ECCPUBLIC_BLOB`` from :func:`export_public_key` into a
    standard PEM that any verifier (PyJWT, ``cryptography``) can load. The private
    key never leaves the TPM. ``cryptography`` is imported lazily so the core
    sign/verify path stays stdlib-only (per this module's design constraints).
    """
    import struct

    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec

    blob = export_public_key(key_name)
    if len(blob) < 8:
        raise TpmSigningError(f"ECC public blob too short: {len(blob)} bytes")
    _magic, cb_key = struct.unpack("<II", blob[:8])
    if cb_key != 32 or len(blob) < 8 + 2 * cb_key:
        raise TpmSigningError(
            f"unexpected ECC public blob (cbKey={cb_key}, len={len(blob)}); "
            f"expected P-256 (cbKey=32)"
        )
    x = int.from_bytes(blob[8 : 8 + cb_key], "big")
    y = int.from_bytes(blob[8 + cb_key : 8 + 2 * cb_key], "big")
    public_key = ec.EllipticCurvePublicNumbers(x, y, ec.SECP256R1()).public_key()
    return public_key.public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )


def delete_key(key_name: str) -> None:
    """Delete a persisted TPM key (used by tests + re-provisioning ceremony)."""
    ctypes, d = _api()
    h = _open_provider(ctypes, d)
    try:
        hk = _open_key(ctypes, d, h, key_name)
        # NCryptDeleteKey frees the handle on success. NOTE: the TPM provider
        # rejects NCRYPT_SILENT_FLAG here with NTE_BAD_FLAGS (0x80090009) despite
        # the docs allowing it — dwFlags must be 0 (verified on hardware).
        s = _u32(d.NCryptDeleteKey(hk, 0))
        if s != _ERROR_SUCCESS:
            d.NCryptFreeObject(hk)
            raise TpmSigningError(f"NCryptDeleteKey('{key_name}') failed: 0x{s:08X}")
    finally:
        d.NCryptFreeObject(h)
