"""Provisioning ceremony for the at-rest encryption DEK keystore (ADR-025).

Run ONCE on the deployment host, by the operator::

    python -m shared.security.provision_dek_keystore

This ceremony provisions ALL THREE keys that BlarAI's at-rest encryption
posture requires — in one command:

  1. The RSA-2048 TPM seal key  (``BlarAI-DEKSeal``)  used to wrap the DEK.
  2. A fresh AES-256 data-encryption key (DEK) dual-wrapped under the seal
     key and under an offline recovery key, then persisted as a keystore file.
  3. The ECDSA P-256 TPM audit signing key
     (``BlarAI-Audit-Signing-Key-v1``) used by the tamper-evident audit log.

The offline recovery key is printed **once** in a clearly-delimited block.
It must be stored off the machine (print it / copy to a USB drive / a safe).
It is NEVER written to disk by this ceremony.  It is the only way to recover
encrypted data if the TPM or chip is replaced.

--rotate
    Pass this flag to replace an existing keystore with a fresh DEK.  Without
    it the ceremony refuses to clobber an existing keystore — a safety guard
    against accidentally destroying the live DEK and orphaning all encrypted
    data.

--recover
    Recovery mode: re-seal an existing DEK onto a new machine after a chip
    replacement or hardware migration.  You will be prompted for the offline
    recovery key; it is read silently and never echoed.  The DEK is unsealed
    via the recovery wrap and re-sealed to this machine's new TPM, then the
    keystore is rewritten.  A non-developer can follow this path.

--keystore-path PATH
    Override the default keystore file location.  The default is
    ``%LOCALAPPDATA%\\BlarAI\\dek_keystore.json`` on Windows, or
    ``~/.local/share/BlarAI/dek_keystore.json`` on other platforms.
    THIS PATH must match the ``BLARAI_DEK_KEYSTORE`` environment variable
    the production services read (ADR-025 §2.1).

Fail-Closed: if no usable TPM 2.0 is present the ceremony refuses to run
rather than falling back to a software key.  The at-rest encryption posture
stays fail-closed until this ceremony has been run on the real deployment
hardware.

Design constraints (ADR-025, non-negotiable):
  - No external network.  No new dependencies — stdlib + ``cryptography``
    (present, 46.0.5).
  - The recovery key is NEVER written to disk or logged.  Only printed once,
    to the operator's terminal.
  - The DEK itself is NEVER written to disk or printed.
  - Both unseal paths (TPM and recovery) are verified before reporting success.
"""

from __future__ import annotations

import argparse
import getpass
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from shared.security import tpm_sealer, tpm_signer
from shared.security.audit_log import AUDIT_TPM_KEY_NAME
from shared.security.dek_envelope import (
    DekEnvelope,
    DekEnvelopeError,
    DevModeSealerError,
    build_envelope,
    generate_recovery_key,
    reseal_dek,
)
from shared.security.tpm_sealer import TpmSealer

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: The TPM seal key name used by BOTH production stores (session_store.py and
#: substrate/entrypoint.py).  Changing this breaks production loading.
DEK_SEAL_KEY_NAME: str = "BlarAI-DEKSeal"

#: The recovery key is 32 bytes (256 bits) = 64 hex nibbles.
_RECOVERY_KEY_HEX_CHARS: int = 64


# ---------------------------------------------------------------------------
# Default keystore path resolution
# ---------------------------------------------------------------------------


def _default_keystore_path() -> Path:
    """Resolve the default keystore path.

    Mirrors the ``LOCALAPPDATA/BlarAI/`` layout used by the production stores
    for the databases.  On non-Windows the XDG-standard location is used.

    This is the path the operator MUST set in ``BLARAI_DEK_KEYSTORE`` for the
    production services to pick it up.
    """
    local = os.environ.get("LOCALAPPDATA", "")
    if local:
        return Path(local) / "BlarAI" / "dek_keystore.json"
    # Fallback for non-Windows or when LOCALAPPDATA is absent.
    return Path.home() / ".local" / "share" / "BlarAI" / "dek_keystore.json"


# ---------------------------------------------------------------------------
# Banner helpers
# ---------------------------------------------------------------------------


def _banner(title: str) -> None:
    width = 72
    print()
    print("=" * width)
    print(f"  {title}")
    print("=" * width)


def _section(label: str) -> None:
    print(f"\n--- {label} ---")


# ---------------------------------------------------------------------------
# provision() — the forward-provision path
# ---------------------------------------------------------------------------


def provision(
    keystore_path: Path,
    *,
    rotate: bool = False,
) -> int:
    """Create the TPM seal key (idempotent), generate a new DEK, seal and
    persist the keystore, then provision the audit signing key.

    Returns a process exit code: 0 on success, 1 on any failure (Fail-Closed).
    """
    _banner("BlarAI At-Rest Encryption — Provisioning Ceremony (ADR-025)")

    # ── TPM availability check ───────────────────────────────────────────
    if not tpm_sealer.is_available():
        print(
            "\nFAIL-CLOSED: no usable TPM 2.0 (Microsoft Platform Crypto Provider)"
            " detected on this host.\n"
            "This ceremony MUST run on the deployment hardware with a real TPM.\n"
            "No key was created and no keystore was written.",
            file=sys.stderr,
        )
        return 1

    # ── Clobber guard ────────────────────────────────────────────────────
    if keystore_path.exists() and not rotate:
        print(
            f"\nFAIL-CLOSED: keystore already exists at:\n  {keystore_path}\n\n"
            "Re-provisioning would DESTROY the current DEK and orphan all\n"
            "encrypted data.  If you genuinely want a fresh DEK, re-run with\n"
            "  --rotate\n"
            "Only do this if you have NOT yet written encrypted data, or if you\n"
            "have securely migrated / re-encrypted everything.",
            file=sys.stderr,
        )
        return 1

    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    # ── Step 1: RSA seal key ─────────────────────────────────────────────
    _section("Step 1 of 3 — RSA seal key (BlarAI-DEKSeal)")
    try:
        seal_key_created = tpm_sealer.ensure_key(DEK_SEAL_KEY_NAME)
    except (tpm_sealer.TpmUnavailable, tpm_sealer.TpmSealingError) as exc:
        print(f"\nFAIL-CLOSED: RSA seal key provisioning failed: {exc}", file=sys.stderr)
        return 1

    seal_status = "created (new)" if seal_key_created else "already existed (idempotent no-op)"
    print(f"  TPM seal key  : {DEK_SEAL_KEY_NAME}")
    print(f"  Key status    : {seal_status}")

    # ── Step 2: DEK keystore ─────────────────────────────────────────────
    _section("Step 2 of 3 — DEK envelope + keystore")
    recovery_key = generate_recovery_key()
    sealer = TpmSealer(DEK_SEAL_KEY_NAME, auto_provision=False)

    keystore_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        envelope = build_envelope(
            sealer=sealer,
            recovery_key=recovery_key,
            keystore_path=keystore_path,
            dev_mode=False,
        )
    except (DevModeSealerError, ValueError, OSError) as exc:
        print(f"\nFAIL-CLOSED: keystore creation failed: {exc}", file=sys.stderr)
        return 1

    print(f"  DEK keystore  : {keystore_path}")
    print(f"  Wrap schemes  : TPM (RSA-2048 OAEP-SHA-256) + Recovery (AES-256-GCM)")

    # ── Recovery key — printed ONCE, never stored ────────────────────────
    recovery_hex = recovery_key.hex()
    print()
    print("!" * 72)
    print("!  RECOVERY KEY — SHOWN ONCE — STORE THIS OFF THE MACHINE")
    print("!  (print it / copy to a USB drive / a secure offline vault)")
    print("!  This is the ONLY way to recover your data if the TPM or chip")
    print("!  is replaced.  It is NEVER written to disk by this ceremony.")
    print("!" * 72)
    print()
    print(f"  Recovery key (hex):  {recovery_hex}")
    print()
    print("!" * 72)
    print()

    # ── Step 2b: round-trip verification ────────────────────────────────
    _section("Step 2b — DEK round-trip verification (both unseal paths)")
    try:
        dek_via_tpm = envelope.unseal_dek()
    except DekEnvelopeError as exc:
        print(
            f"\nFAIL-CLOSED: TPM-path unseal FAILED immediately after provisioning.\n"
            f"Error: {exc}\n"
            "The ceremony is INCOMPLETE.  The keystore may be corrupt.\n"
            "Do NOT use this keystore for production.",
            file=sys.stderr,
        )
        return 1

    try:
        dek_via_recovery = envelope.unseal_dek(recovery_key=recovery_key)
    except DekEnvelopeError as exc:
        print(
            f"\nFAIL-CLOSED: recovery-path unseal FAILED immediately after provisioning.\n"
            f"Error: {exc}\n"
            "The recovery wrap is unusable.  The ceremony is INCOMPLETE.",
            file=sys.stderr,
        )
        return 1

    if dek_via_tpm != dek_via_recovery:
        print(
            "\nFAIL-CLOSED: TPM-unsealed DEK != recovery-unsealed DEK.\n"
            "This is a cryptographic inconsistency — the keystore is corrupt.\n"
            "The ceremony is INCOMPLETE.  Do NOT use this keystore.",
            file=sys.stderr,
        )
        return 1

    print("  TPM-path unseal      : PASS")
    print("  Recovery-path unseal : PASS")
    print("  DEK identity check   : PASS  (both paths produce the same DEK)")

    # ── Step 3: ECDSA audit signing key ──────────────────────────────────
    _section("Step 3 of 3 — ECDSA audit signing key")
    try:
        audit_key_created = tpm_signer.ensure_key(AUDIT_TPM_KEY_NAME)
    except (tpm_signer.TpmUnavailable, tpm_signer.TpmSigningError) as exc:
        print(
            f"\nFAIL-CLOSED: audit signing key provisioning failed: {exc}",
            file=sys.stderr,
        )
        return 1

    audit_status = "created (new)" if audit_key_created else "already existed (idempotent no-op)"
    print(f"  Audit key     : {AUDIT_TPM_KEY_NAME}")
    print(f"  Key status    : {audit_status}")

    # ── Summary ──────────────────────────────────────────────────────────
    _banner("Ceremony Complete")
    print(f"  date (UTC)    : {stamp}")
    print(f"  RSA seal key  : {DEK_SEAL_KEY_NAME}  [{seal_status}]")
    print(f"  DEK keystore  : {keystore_path}")
    print(f"  Audit key     : {AUDIT_TPM_KEY_NAME}  [{audit_status}]")
    print()
    print("NEXT STEPS:")
    print(f"  1. Set the environment variable for the production services:")
    print(f"       BLARAI_DEK_KEYSTORE={keystore_path}")
    print("  2. Store the recovery key off this machine NOW (if not done yet).")
    print("  3. The production services are ready to run with at-rest encryption.")
    print()
    print("NOTE: The DEK itself was never written to disk or printed.")
    print("NOTE: The recovery key was shown once above — it is NOT in this log.")
    return 0


# ---------------------------------------------------------------------------
# recover() — the chip-replacement / hardware-migration recovery path
# ---------------------------------------------------------------------------


def recover(
    keystore_path: Path,
) -> int:
    """Re-seal an existing DEK onto a new machine after a chip replacement.

    You will be prompted for the offline recovery key (hidden input; never
    echoed to the terminal or logged).  The DEK is unsealed via the RECOVERY
    wrap ONLY — :meth:`DekEnvelope.unseal_via_recovery`, which never attempts
    the (dead) TPM path — then re-sealed to this machine's new TPM via the
    public :func:`~shared.security.dek_envelope.reseal_dek` (no new DEK is
    generated; the same DEK is re-wrapped), and the keystore is rewritten with
    a fresh recovery key.

    The new keystore is verified to round-trip via the TPM path before this
    function returns.

    Returns 0 on success, 1 on failure (Fail-Closed).
    """
    _banner("BlarAI At-Rest Encryption — Recovery Ceremony (ADR-025)")
    print()
    print("You are re-sealing an existing DEK onto this machine's new TPM.")
    print("You need the offline recovery key that was printed during the")
    print("original provisioning ceremony.")
    print()

    # ── TPM availability ─────────────────────────────────────────────────
    if not tpm_sealer.is_available():
        print(
            "FAIL-CLOSED: no usable TPM 2.0 on this host.\n"
            "The recovery ceremony must run on a machine with a real TPM.",
            file=sys.stderr,
        )
        return 1

    # ── Read the offline recovery key (hidden input) ──────────────────────
    _section("Step 1 of 4 — Enter the offline recovery key")
    print("  Enter the recovery key EXACTLY as it was printed (64 hex characters,")
    print("  no spaces).  Input is hidden and will not appear on screen.")
    print()
    try:
        recovery_hex_raw = getpass.getpass("  Recovery key (hex): ").strip()
    except (EOFError, KeyboardInterrupt):
        print("\nFAIL-CLOSED: recovery key input cancelled.", file=sys.stderr)
        return 1

    # Remove any whitespace the operator may have accidentally included.
    recovery_hex = recovery_hex_raw.replace(" ", "").replace("-", "").lower()
    if len(recovery_hex) != _RECOVERY_KEY_HEX_CHARS:
        print(
            f"\nFAIL-CLOSED: recovery key has wrong length: "
            f"{len(recovery_hex)} hex chars (expected {_RECOVERY_KEY_HEX_CHARS}).\n"
            "Re-run and enter the full key exactly as printed.",
            file=sys.stderr,
        )
        return 1

    try:
        recovery_key = bytes.fromhex(recovery_hex)
    except ValueError as exc:
        print(
            f"\nFAIL-CLOSED: recovery key contains invalid hex characters: {exc}",
            file=sys.stderr,
        )
        return 1
    finally:
        # Best-effort: drop our reference to the recovery-key hex now that we
        # have the bytes. HONEST LIMITATION: Python str/bytes are IMMUTABLE, so
        # rebinding the name does NOT overwrite the secret's backing store in
        # place — the original object merely becomes GC-eligible. True in-RAM
        # zeroization is not achievable in pure Python (the `cryptography` lib
        # also copies key material into OpenSSL beyond our reach); this reduces
        # the residency window, it does not erase the copy. The real residency
        # mitigation is tracked as a deferred item in #611.
        recovery_hex = "0" * _RECOVERY_KEY_HEX_CHARS  # rebinds name (best-effort drop)
        recovery_hex_raw = ""  # noqa: F841

    # ── Step 2: Unseal the existing DEK via the RECOVERY wrap ONLY ────────
    # We deliberately do NOT attempt the TPM path here: the whole premise of a
    # recovery is that the old chip is gone.  unseal_via_recovery() unwraps the
    # recovery wrap directly and never touches a sealer, so the recovery path is
    # selected by-design — not by relying on a placeholder sealer's exception to
    # trigger a TPM-then-recovery fallback (the round-1 merge-gate finding).
    _section("Step 2 of 4 — Unseal existing DEK via recovery key")
    if not keystore_path.exists():
        print(
            f"\nFAIL-CLOSED: keystore not found at:\n  {keystore_path}\n"
            "Verify the path and re-run.",
            file=sys.stderr,
        )
        # Best-effort drop the recovery key before returning (rebinds the name;
        # not true zeroization — see the immutability note in Step 1 / #611).
        recovery_key = bytes(len(recovery_key))
        return 1

    # Provision the NEW chip's seal key first, so the envelope we load carries a
    # legitimate (new) sealer — there is no SoftwareSealer anywhere in recover().
    try:
        seal_key_created = tpm_sealer.ensure_key(DEK_SEAL_KEY_NAME)
    except (tpm_sealer.TpmUnavailable, tpm_sealer.TpmSealingError) as exc:
        print(
            f"\nFAIL-CLOSED: new RSA seal key provisioning failed: {exc}",
            file=sys.stderr,
        )
        recovery_key = bytes(len(recovery_key))
        return 1

    new_sealer = TpmSealer(DEK_SEAL_KEY_NAME, auto_provision=False)

    try:
        old_envelope = DekEnvelope.load(
            sealer=new_sealer,
            keystore_path=keystore_path,
        )
    except DekEnvelopeError as exc:
        print(
            f"\nFAIL-CLOSED: cannot load keystore: {exc}",
            file=sys.stderr,
        )
        recovery_key = bytes(len(recovery_key))
        return 1

    try:
        # Recovery-ONLY unwrap: never attempts the (dead) TPM path.
        dek = old_envelope.unseal_via_recovery(recovery_key)
    except DekEnvelopeError as exc:
        print(
            f"\nFAIL-CLOSED: recovery-key unseal failed: {exc}\n"
            "Check that you entered the recovery key correctly.",
            file=sys.stderr,
        )
        recovery_key = bytes(len(recovery_key))
        return 1

    print("  Recovery-key unseal  : PASS  (recovery wrap only — TPM path not attempted)")

    # ── Step 3: Re-seal the SAME DEK under the new chip + fresh recovery ──
    _section("Step 3 of 4 — Re-seal DEK under new TPM seal key")
    seal_status = "created (new)" if seal_key_created else "already existed (idempotent no-op)"
    print(f"  TPM seal key  : {DEK_SEAL_KEY_NAME}  [{seal_status}]")

    # A fresh recovery key for the new keystore so the operator has an updated
    # recovery artefact bound to the new chip's keystore.  The old key retires.
    new_recovery_key = generate_recovery_key()

    # reseal_dek wraps the EXISTING DEK (no new DEK) and shares the single
    # dual-wrap implementation with build_envelope/create — no format drift.
    new_envelope = reseal_dek(
        dek,
        sealer=new_sealer,
        recovery_key=new_recovery_key,
        dev_mode=False,
    )

    # Best-effort drop the recovered DEK + old recovery key — no longer needed
    # in clear. Rebinds the names (GC-eligible); Python cannot overwrite the
    # immutable bytes in place, so this is residency-window reduction, not true
    # zeroization (see the Step 1 note / #611).
    dek = bytes(len(dek))
    recovery_key = bytes(len(recovery_key))

    # Write the new keystore (overwrites the old one).
    try:
        new_envelope.save(keystore_path)
    except OSError as exc:
        print(
            f"\nFAIL-CLOSED: cannot write new keystore: {exc}",
            file=sys.stderr,
        )
        new_recovery_key = bytes(len(new_recovery_key))
        return 1

    print(f"  New keystore  : {keystore_path}  (overwritten)")

    # ── Print the NEW recovery key — shown once ───────────────────────────
    new_recovery_hex = new_recovery_key.hex()
    print()
    print("!" * 72)
    print("!  NEW RECOVERY KEY — SHOWN ONCE — STORE THIS OFF THE MACHINE")
    print("!  This replaces the previous recovery key.  The old key is now")
    print("!  INVALID.  Copy this to a USB drive / secure offline vault.")
    print("!" * 72)
    print()
    print(f"  Recovery key (hex):  {new_recovery_hex}")
    print()
    print("!" * 72)
    print()

    # Best-effort drop the new recovery key after printing (rebinds the names;
    # not true in-RAM zeroization — Python immutability, see Step 1 note / #611).
    new_recovery_hex = "0" * _RECOVERY_KEY_HEX_CHARS
    new_recovery_key = bytes(len(new_recovery_key))

    # ── Step 4: Verify the re-sealed keystore round-trips ─────────────────
    _section("Step 4 of 4 — Verify re-sealed keystore (TPM path)")
    try:
        reload_envelope = DekEnvelope.load(
            sealer=TpmSealer(DEK_SEAL_KEY_NAME, auto_provision=False),
            keystore_path=keystore_path,
        )
        verified_dek = reload_envelope.unseal_dek()
        # Best-effort drop immediately (rebinds the name; not true zeroization —
        # Python immutability, see Step 1 note / #611).
        verified_dek = bytes(len(verified_dek))
    except DekEnvelopeError as exc:
        print(
            f"\nFAIL-CLOSED: re-sealed keystore verification FAILED: {exc}\n"
            "The recovery is INCOMPLETE.  The old keystore has been overwritten.\n"
            "You must run the recovery again with the new recovery key printed above.",
            file=sys.stderr,
        )
        return 1

    print("  TPM-path unseal      : PASS")

    # ── Provision audit key (idempotent — no-op if already present) ───────
    _section("Audit key (idempotent)")
    try:
        audit_key_created = tpm_signer.ensure_key(AUDIT_TPM_KEY_NAME)
        audit_status = "created (new)" if audit_key_created else "already existed (idempotent no-op)"
        print(f"  Audit key     : {AUDIT_TPM_KEY_NAME}  [{audit_status}]")
    except (tpm_signer.TpmUnavailable, tpm_signer.TpmSigningError) as exc:
        # Audit key failure is noted but does not abort the recovery — the DEK
        # re-seal succeeded and the operator can run provision_signing_key separately.
        print(f"  WARNING: audit key provisioning failed: {exc}", file=sys.stderr)
        print("  The DEK re-seal succeeded.  Run the signing-key ceremony separately.")

    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    _banner("Recovery Complete")
    print(f"  date (UTC)    : {stamp}")
    print(f"  Keystore      : {keystore_path}  (re-sealed to new TPM)")
    print()
    print("CRITICAL: The new recovery key was shown above — store it off this")
    print("machine NOW.  The old recovery key is no longer valid.")
    print()
    print("NEXT: Set BLARAI_DEK_KEYSTORE and restart the production services.")
    return 0


# ---------------------------------------------------------------------------
# main() — argparse CLI
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    """CLI entrypoint. See module docstring for the ceremony contract."""
    default_path = _default_keystore_path()

    parser = argparse.ArgumentParser(
        prog="python -m shared.security.provision_dek_keystore",
        description=(
            "Provision the BlarAI at-rest encryption DEK keystore (ADR-025).\n\n"
            "Default mode: creates the TPM seal key + DEK keystore + audit signing key.\n"
            "Use --rotate to replace an existing keystore.\n"
            "Use --recover to re-seal after a chip replacement."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--keystore-path",
        type=Path,
        default=default_path,
        help=(
            f"Path to write the DEK keystore "
            f"(default: {default_path}).  "
            "MUST match the BLARAI_DEK_KEYSTORE env var the production "
            "services read."
        ),
    )
    parser.add_argument(
        "--rotate",
        action="store_true",
        default=False,
        help=(
            "Replace an existing keystore with a fresh DEK.  "
            "CAUTION: destroys the current DEK — all encrypted data becomes "
            "unreadable unless previously migrated."
        ),
    )
    parser.add_argument(
        "--recover",
        action="store_true",
        default=False,
        help=(
            "Re-seal an existing DEK onto a replacement chip.  "
            "You will be prompted for the offline recovery key."
        ),
    )

    args = parser.parse_args(argv)

    if args.rotate and args.recover:
        print(
            "FAIL-CLOSED: --rotate and --recover are mutually exclusive.",
            file=sys.stderr,
        )
        return 1

    try:
        if args.recover:
            return recover(args.keystore_path)
        else:
            return provision(args.keystore_path, rotate=args.rotate)

    except tpm_sealer.TpmUnavailable as exc:
        print(f"FAIL-CLOSED: TPM unavailable: {exc}", file=sys.stderr)
        return 1
    except tpm_sealer.TpmSealingError as exc:
        print(f"FAIL-CLOSED: TPM sealing operation failed: {exc}", file=sys.stderr)
        return 1
    except tpm_signer.TpmUnavailable as exc:
        print(f"FAIL-CLOSED: TPM unavailable (signer): {exc}", file=sys.stderr)
        return 1
    except tpm_signer.TpmSigningError as exc:
        print(f"FAIL-CLOSED: TPM signing operation failed: {exc}", file=sys.stderr)
        return 1
    except DekEnvelopeError as exc:
        print(f"FAIL-CLOSED: DEK envelope error: {exc}", file=sys.stderr)
        return 1
    except OSError as exc:
        print(f"FAIL-CLOSED: file I/O error during ceremony: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
