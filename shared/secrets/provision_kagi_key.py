"""Provisioning ceremony for the Kagi Search API key (W2, Vikunja #573).

Run ONCE on the deployment host, by the operator, before starting the
Agentic Web-Search Skill worker::

    python -m shared.secrets.provision_kagi_key

This is the human-in-the-loop step that seals the Kagi API key into a
DPAPI-encrypted blob at::

    %LOCALAPPDATA%\\BlarAI\\secrets\\kagi_api_key.dpapi

The blob is machine-bound and user-bound: only the same Windows user account
on the same machine can decrypt it.  An offline attacker who copies the file
cannot recover the key without the user's Windows login credential.

Re-running this script on the same machine overwrites the existing blob,
which is how key rotation is performed.  See the runbook for the full
rotation procedure: ``docs/runbooks/kagi_key_provisioning.md``.

Fail-Closed: if pywin32 / DPAPI is unavailable on this host (e.g. non-Windows
environment), the ceremony refuses to run.  The web-search worker cannot start
without the provisioned blob on its host machine.

Design note: this script mirrors the deliberate-ceremony tone of
``shared/security/provision_signing_key.py`` (ADR-021).  Provisioning is an
observable, human-witnessed event — not an automatic side-effect of startup.
"""

from __future__ import annotations

import getpass
import sys
from datetime import datetime, timezone
from pathlib import Path

from shared.secrets.dpapi_store import (
    KagiKeyDecryptError,
    KagiKeyNotProvisioned,
    _current_blob_path,
    store_kagi_api_key,
    load_kagi_api_key,
)


def provision() -> int:
    """Run the interactive key provisioning ceremony.

    Prompts the operator for the Kagi API key (stdin, echo disabled), encrypts
    it with DPAPI, writes the blob, then immediately decrypts and verifies the
    round-trip.  Prints confirmation WITHOUT echoing the key.

    Returns 0 on success, 1 on any failure.
    """
    blob_path: Path = _current_blob_path()
    stamp: str = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    print("BlarAI Kagi API key provisioning ceremony")
    print(f"  blob destination   : {blob_path}")
    print(f"  ceremony started   : {stamp}")
    print()
    print("This step seals the Kagi API key into a DPAPI-encrypted blob that is")
    print("bound to this user account on this machine.  A second machine needs")
    print("its own provisioning step.  Re-running this script rotates the key.")
    print()

    # ---- Prompt (echo disabled) -------------------------------------------
    try:
        key = getpass.getpass("Enter Kagi API key (input hidden): ")
    except (KeyboardInterrupt, EOFError):
        print("\nProvisioning cancelled.", file=sys.stderr)
        return 1

    if not key:
        print("FAIL-CLOSED: empty key supplied — provisioning aborted.", file=sys.stderr)
        return 1

    # ---- Encrypt and write blob -------------------------------------------
    try:
        store_kagi_api_key(key)
    except RuntimeError as exc:
        # pywin32 / DPAPI unavailable
        print(f"FAIL-CLOSED: {exc}", file=sys.stderr)
        return 1
    except OSError as exc:
        print(f"FAIL-CLOSED: could not write blob file: {exc}", file=sys.stderr)
        return 1

    # ---- Immediate round-trip verification (decrypt and confirm) ----------
    try:
        recovered = load_kagi_api_key()
    except (KagiKeyNotProvisioned, KagiKeyDecryptError, RuntimeError) as exc:
        print(
            f"FAIL-CLOSED: blob was written but round-trip verification failed: {exc}",
            file=sys.stderr,
        )
        return 1

    if recovered != key:
        # Should never happen with DPAPI on the same user/machine, but guard it.
        print(
            "FAIL-CLOSED: round-trip verification mismatch — the stored blob "
            "does not decrypt to the supplied key.  Re-run the ceremony.",
            file=sys.stderr,
        )
        return 1

    # Immediately discard the plaintext from locals.  At this point `key` and
    # `recovered` go out of scope at return; we do not cache them anywhere.
    del key
    del recovered

    # ---- Success banner ---------------------------------------------------
    complete_stamp: str = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    print()
    print("Kagi API key provisioning ceremony complete.")
    print(f"  blob written       : {blob_path}")
    print(f"  round-trip         : PASS")
    print(f"  ceremony ended     : {complete_stamp}")
    print()
    print("NOTE: the blob is machine- and user-bound (DPAPI).  A second machine")
    print("requires its own provisioning step.  To rotate the key, re-run this")
    print("script — the blob is overwritten.  See docs/runbooks/kagi_key_provisioning.md")
    return 0


def main() -> int:
    """CLI entrypoint.  See module docstring for the ceremony contract."""
    try:
        return provision()
    except Exception as exc:  # noqa: BLE001 — catch-all; print, don't crash the terminal
        print(f"Provisioning ceremony failed unexpectedly: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
