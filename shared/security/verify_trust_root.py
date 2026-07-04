"""Read-only on-chip verification of the four BlarAI trust-root TPM keys.

Sibling to :mod:`shared.security.ceremony_preflight`.  Where the preflight proves
each trust-root key *exists* (``key_exists``), this module proves each key
additionally *works on the chip* (a functional sign/verify or seal/unseal
round-trip) and *cannot be exported* (a private-key export attempt is **refused**
by the provider).  Together that upgrades the trust-root claim from "inferred from
the provisioning scripts + boot preflight" to "verified-live on the chip" — the
load-bearing claim behind the #612 capstone §K ("Is It Real?") and
``SECURITY_ROADMAP_air_gap_removal.md`` §5.1.

**READ-ONLY (paramount).**  This module NEVER provisions, mutates, or deletes a
key.  It calls only read-only primitives:

  - ``tpm_signer``: ``is_available``, ``key_exists``, ``sign``, ``verify``,
    ``export_public_key``
  - ``tpm_sealer``: ``is_available``, ``key_exists``,
    ``TpmSealer(auto_provision=False)`` → ``seal`` / ``unseal``

The non-export check issues a single ``NCryptExportKey`` for the *private* blob
and asserts the provider REFUSES it — a refused export reads-and-fails and mutates
nothing.  It reuses the exact CNG call vetted in ``test_tpm_signer`` /
``test_tpm_sealer`` (the module-internal helpers ``_api`` / ``_open_provider`` /
``_open_key`` / ``_u32``), now pointed at the production keys.  There is **no**
``ensure_key``, ``delete_key``, ``NCryptCreatePersistedKey``, or ``provision_*``
call anywhere in this module — this is a *verification*, never a (re-)provisioning.
The functional seal round-trip uses a throwaway ``os.urandom(32)`` blob — **never**
the real Data-Encryption-Key (DEK), never the keystore file.

The four trust-root keys (canonical names mirror ``ceremony_preflight.py``):

  ===========================  ============  ===================================
  Key name                     Type          Role
  ===========================  ============  ===================================
  BlarAI-PA-JWT-Signing        ECDSA P-256   Policy Agent JWT minting
  BlarAI-Audit-Signing-Key-v1  ECDSA P-256   tamper-evident audit stream
  BlarAI-Manifest-Signing      ECDSA P-256   FUT-04 weight-integrity manifest
  BlarAI-DEKSeal               RSA-2048      at-rest DEK envelope (ADR-025)
  ===========================  ============  ===================================

Usage::

    python -m shared.security.verify_trust_root           # human checklist + JSON
    python -m shared.security.verify_trust_root --json     # JSON only (machine)

Records booleans / key names / verdicts ONLY — never key material, never a raw
signature, never the throwaway test blob.  A successful *private* export (should
never happen) is surfaced as the ``CRITICAL_EXPORTABLE`` verdict and a non-zero
exit code.
"""

from __future__ import annotations

import json
import os
import sys
from typing import Final

from shared.security import tpm_sealer, tpm_signer

# ---------------------------------------------------------------------------
# The four trust-root keys (names mirror ceremony_preflight.py:40-45)
# ---------------------------------------------------------------------------

SIGNER_KEYS: Final[tuple[str, ...]] = (
    "BlarAI-PA-JWT-Signing",
    "BlarAI-Audit-Signing-Key-v1",
    "BlarAI-Manifest-Signing",
)
SEALER_KEY: Final[str] = "BlarAI-DEKSeal"

# Private-key blob types whose export MUST be refused by the provider.  Vetted in
# test_tpm_signer.py:98 (ECCPRIVATEBLOB) and test_tpm_sealer.py:206
# (RSAFULLPRIVATEBLOB).  A *successful* export here means the private key is
# extractable — a CRITICAL trust-root failure.
_ECC_PRIVATE_BLOB: Final[str] = "ECCPRIVATEBLOB"
_RSA_PRIVATE_BLOB: Final[str] = "RSAFULLPRIVATEBLOB"

# A fixed, non-secret message for the signer functional round-trip.  Its bytes
# carry no secret and are never recorded.
_SIGNER_TEST_MESSAGE: Final[bytes] = b"BlarAI trust-root verification probe (read-only)"

# Verdict labels.
_VERIFIED_LIVE: Final[str] = "VERIFIED_LIVE"
_NOT_PROVISIONED: Final[str] = "NOT_PROVISIONED"
_DEGRADED: Final[str] = "DEGRADED"
_CRITICAL_EXPORTABLE: Final[str] = "CRITICAL_EXPORTABLE"


# ---------------------------------------------------------------------------
# Direct per-key non-export probes (reuse the vetted CNG internals, read-only)
# ---------------------------------------------------------------------------


def _signer_private_export_refused(key_name: str) -> bool:
    """Attempt a PRIVATE-key export on an ECDSA signer key; True iff REFUSED.

    Reuses ``tpm_signer``'s vetted CNG internals — the same call
    ``test_tpm_signer.test_private_key_is_non_exportable`` makes, pointed at the
    production key.  READ-ONLY: a refused export mutates nothing.  Returning
    ``False`` means the provider EXPORTED the private key (CRITICAL).
    """
    import ctypes

    ctypes_mod, d = tpm_signer._api()
    h = tpm_signer._open_provider(ctypes_mod, d)
    try:
        hk = tpm_signer._open_key(ctypes_mod, d, h, key_name)
        try:
            cb = ctypes.c_ulong(0)
            status = tpm_signer._u32(
                d.NCryptExportKey(hk, None, _ECC_PRIVATE_BLOB, None, None, 0, ctypes.byref(cb), 0)
            )
            return status != tpm_signer._ERROR_SUCCESS
        finally:
            d.NCryptFreeObject(hk)
    finally:
        d.NCryptFreeObject(h)


def _sealer_private_export_refused(key_name: str) -> bool:
    """Attempt a PRIVATE-key export on the RSA seal key; True iff REFUSED.

    Reuses ``tpm_sealer``'s vetted CNG internals — the same call
    ``test_tpm_sealer.test_private_key_is_non_exportable`` makes, pointed at the
    production key.  READ-ONLY: a refused export mutates nothing.
    """
    import ctypes

    ctypes_mod, d = tpm_sealer._api()
    h = tpm_sealer._open_provider(ctypes_mod, d)
    try:
        hk = tpm_sealer._open_key(ctypes_mod, d, h, key_name)
        try:
            cb = ctypes.c_ulong(0)
            status = tpm_sealer._u32(
                d.NCryptExportKey(hk, None, _RSA_PRIVATE_BLOB, None, None, 0, ctypes.byref(cb), 0)
            )
            return status != tpm_sealer._ERROR_SUCCESS
        finally:
            d.NCryptFreeObject(hk)
    finally:
        d.NCryptFreeObject(h)


# ---------------------------------------------------------------------------
# Verdict
# ---------------------------------------------------------------------------


def _verdict(result: dict) -> str:
    """Derive a per-key verdict from the probed booleans."""
    if not result["resident"]:
        return _NOT_PROVISIONED
    # A successful private export is the worst possible outcome — surface loudly.
    if result.get("private_export_refused") is False:
        return _CRITICAL_EXPORTABLE
    public_ok = result.get("public_export_ok")
    if (
        result.get("functional_roundtrip") is True
        and result.get("private_export_refused") is True
        and public_ok is not False  # None (N/A for sealer) or True both acceptable
    ):
        return _VERIFIED_LIVE
    return _DEGRADED


# ---------------------------------------------------------------------------
# Per-key probes (READ-ONLY)
# ---------------------------------------------------------------------------


def probe_signer_key(key_name: str) -> dict:
    """Read-only probe of one ECDSA P-256 signer key.

    Returns a dict: ``key_name``, ``type``, ``resident``,
    ``functional_roundtrip``, ``public_export_ok``, ``private_export_refused``,
    ``verdict``.  If the key is not resident, the functional/export fields stay
    ``None`` and the verdict is ``NOT_PROVISIONED`` — **nothing is created**.
    """
    result: dict = {
        "key_name": key_name,
        "type": "ECDSA-P256",
        "resident": False,
        "functional_roundtrip": None,
        "public_export_ok": None,
        "private_export_refused": None,
        "verdict": _NOT_PROVISIONED,
    }
    if not tpm_signer.key_exists(key_name):
        return result
    result["resident"] = True

    # Functional: sign a fixed test message and verify it round-trips on-chip.
    signature = tpm_signer.sign(key_name, _SIGNER_TEST_MESSAGE)
    result["functional_roundtrip"] = bool(
        tpm_signer.verify(key_name, _SIGNER_TEST_MESSAGE, signature)
    )

    # The PUBLIC half must export (by design); the PRIVATE half must be refused.
    public_blob = tpm_signer.export_public_key(key_name)
    result["public_export_ok"] = isinstance(public_blob, bytes) and len(public_blob) > 0
    result["private_export_refused"] = _signer_private_export_refused(key_name)

    result["verdict"] = _verdict(result)
    return result


def probe_sealer_key(key_name: str) -> dict:
    """Read-only probe of the RSA-2048 seal key.

    The functional check seals + unseals a throwaway ``os.urandom(32)`` blob
    (never the real DEK, never the keystore file).  The sealer exposes no
    public-export API, so ``public_export_ok`` stays ``None`` (not applicable).
    """
    result: dict = {
        "key_name": key_name,
        "type": "RSA-2048",
        "resident": False,
        "functional_roundtrip": None,
        "public_export_ok": None,  # sealer has no public-export API — N/A
        "private_export_refused": None,
        "verdict": _NOT_PROVISIONED,
    }
    if not tpm_sealer.key_exists(key_name):
        return result
    result["resident"] = True

    # Functional: seal + unseal a THROWAWAY random blob.  auto_provision=False is
    # MANDATORY — the default True would call ensure_key() and CREATE the key.
    test_blob = os.urandom(32)
    sealer = tpm_sealer.TpmSealer(key_name, auto_provision=False)
    sealed = sealer.seal(test_blob)
    result["functional_roundtrip"] = sealer.unseal(sealed) == test_blob

    result["private_export_refused"] = _sealer_private_export_refused(key_name)

    result["verdict"] = _verdict(result)
    return result


# ---------------------------------------------------------------------------
# Top-level verification
# ---------------------------------------------------------------------------


def verify_trust_root() -> dict:
    """Probe all four trust-root keys read-only and return a structured result.

    Pure with respect to environment metadata (timestamp / platform are added by
    :func:`main` when emitting), so the per-key booleans are deterministic and
    testable.  Returns ``{signer_available, sealer_available, keys[], verdict,
    all_verified_live}``.  If the TPM is unreachable from this shell the verdict
    is ``TPM_UNAVAILABLE`` — that is an environment/elevation condition, **not** a
    key failure.
    """
    signer_available = tpm_signer.is_available()
    sealer_available = tpm_sealer.is_available()
    result: dict = {
        "signer_available": signer_available,
        "sealer_available": sealer_available,
        "keys": [],
        "all_verified_live": False,
        "verdict": "TPM_UNAVAILABLE",
    }
    if not (signer_available and sealer_available):
        return result

    for key_name in SIGNER_KEYS:
        result["keys"].append(probe_signer_key(key_name))
    result["keys"].append(probe_sealer_key(SEALER_KEY))

    result["all_verified_live"] = all(
        k["verdict"] == _VERIFIED_LIVE for k in result["keys"]
    )
    result["verdict"] = "ALL_VERIFIED_LIVE" if result["all_verified_live"] else "SEE_KEYS"
    return result


# ---------------------------------------------------------------------------
# Human-readable rendering (mirrors ceremony_preflight.py's checklist style)
# ---------------------------------------------------------------------------

_PASS: Final[str] = "[  OK  ]"
_FAIL: Final[str] = "[ FAIL ]"
_WARN: Final[str] = "[ WARN ]"
_CRIT: Final[str] = "[ CRIT ]"


def _line(symbol: str, label: str, detail: str = "") -> str:
    base = f"  {symbol}  {label}"
    if detail:
        base += f"\n           {detail}"
    return base


def _header(title: str) -> str:
    bar = "=" * 70
    return f"\n{bar}\n  {title}\n{bar}\n"


def _symbol_for(verdict: str) -> str:
    return {
        _VERIFIED_LIVE: _PASS,
        _NOT_PROVISIONED: _WARN,
        _DEGRADED: _FAIL,
        _CRITICAL_EXPORTABLE: _CRIT,
    }.get(verdict, _FAIL)


def _print_human(result: dict) -> None:
    print(_header("BlarAI Trust-Root On-Chip Verification"))
    print("  Proves each trust-root TPM key is RESIDENT, FUNCTIONAL, and")
    print("  NON-EXPORTABLE on the real chip.")
    print("  READ-ONLY — nothing is created, changed, or deleted.\n")

    if not (result.get("signer_available") and result.get("sealer_available")):
        print(
            _line(
                _WARN,
                "TPM not reachable from this shell",
                "is_available() is False — the keys cannot be probed here.  Run in "
                "the same context the boot path uses.  This is an environment "
                "condition, NOT a key failure.",
            )
        )
        return

    print("  Trust-Root Key Verification")
    print("  " + "-" * 64)
    for key in result["keys"]:
        detail = (
            f"resident={key['resident']}  "
            f"functional={key['functional_roundtrip']}  "
            f"private_export_refused={key['private_export_refused']}  ->  {key['verdict']}"
        )
        print(_line(_symbol_for(key["verdict"]), f"{key['key_name']} ({key['type']})", detail))

    print()
    print("  " + "-" * 64)
    if result["all_verified_live"]:
        print(
            "  RESULT:  ALL FOUR TRUST-ROOT KEYS VERIFIED LIVE ON THE CHIP\n"
            "           resident + functional + non-exportable, each proven directly.\n"
        )
    else:
        print(
            "  RESULT:  NOT all keys verified live — see the per-key lines above.\n"
        )


def _environment() -> dict:
    """Cheap, reliable, no-elevation environment facts captured live."""
    import platform

    return {
        "platform": platform.platform(),
        "python": sys.version.split()[0],
        "cng_provider": tpm_signer.PROVIDER_NAME,
    }


def main(argv: list[str] | None = None) -> int:
    """CLI entrypoint.  Returns non-zero only on a CRITICAL or DEGRADED key."""
    argv = sys.argv[1:] if argv is None else argv
    json_only = "--json" in argv

    result = verify_trust_root()

    if not json_only:
        _print_human(result)

    # The emitted JSON wraps the deterministic core with live environment facts
    # and a UTC timestamp (added here, not in verify_trust_root(), to keep the
    # core function deterministic for tests).
    from datetime import datetime, timezone

    emitted = {
        **result,
        "environment": _environment(),
        "verified_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    if not json_only:
        print("  Machine-readable result:")
    print(json.dumps(emitted, indent=2))

    verdicts = {k.get("verdict") for k in result.get("keys", [])}
    if _CRITICAL_EXPORTABLE in verdicts or _DEGRADED in verdicts:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
