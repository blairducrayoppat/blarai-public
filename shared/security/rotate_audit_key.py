"""Rotate the audit signing key without breaking the chain (#1578).

Run this when the audit signing key must change. It is the operator-facing
remedy the refusal message used to name and not have: before this, a legitimate
rotation left the Policy Agent refusing to start permanently, and the guidance
pointed at a Python API call that could not have recovered the chain anyway.

WHAT IT DOES, in order, refusing at the first thing that is not right:

1. Verifies the chain AS IT STANDS. A chain that does not verify now must not be
   rotated: the rotation would sign a bridge into a chain whose integrity was
   already in question, and afterwards nobody could tell which break came first.
2. Provisions the incoming key on the TPM, if it is not there already.
3. Appends the BRIDGE record, signed by the OUTGOING key and naming the incoming
   one. That record is what lets a verifier walk across the boundary.
4. Records the incoming key in the key history, so a later boot knows where to
   start the walk.
5. Re-verifies the whole chain across the rotation, and says so.

WHAT IT NEVER DOES: delete the retired key. Records signed by it verify under it
and under nothing else, so deleting one destroys the verifiability of every
record it signed. The script prints this and does not offer an option to do it.

Usage::

    python -m shared.security.rotate_audit_key --new-key BlarAI-Audit-Signing-Key-v2
    python -m shared.security.rotate_audit_key --new-key ... --dry-run
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

logger = logging.getLogger("rotate_audit_key")


def discover_chains() -> list[Path]:
    """Audit chains found under the user-data audit directory.

    There is no single "the audit log": this machine keeps THREE chains with
    three different names — ``adjudication_audit.jsonl`` (Policy Agent, under
    the SERVICE root, not here), ``ingest_audit.jsonl`` and
    ``verdict_audit.jsonl`` (Assistant Orchestrator). An earlier version of this
    script defaulted to ``audit.jsonl``, a name nothing writes, so the runbook's
    first command could only ever print "no audit log at ...".
    """
    from shared.security.audit_log import SEGMENT_INDEX_NAME

    local = os.environ.get("LOCALAPPDATA", "")
    if not local:
        return []
    audit_dir = Path(local) / "BlarAI" / "audit"
    if not audit_dir.is_dir():
        return []
    # SEGMENT_INDEX_NAME is the system's own bookkeeping file, not a chain. It
    # is read from the module rather than spelled here so a rename cannot leave
    # this glob quietly wrong. The "-index.jsonl" suffix below does not match
    # it ("audit-segments.jsonl"), so before this the first segment rotation
    # made the index appear as a chain: the rotation script would then refuse
    # to guess between "two chains", and #1581's verify command reported it as
    # an "Unrecognised chain -- UNCHECKABLE" and exited non-zero for good.
    return sorted(
        path
        for path in audit_dir.glob("*.jsonl")
        if not path.name.endswith("-index.jsonl")
        and path.name != SEGMENT_INDEX_NAME
    )


def _resolve_log_path(explicit: Path | None) -> Path:
    """The chain to rotate: the one given, or the only one found.

    Refuses to guess. Rotating the wrong chain writes a bridge into a chain the
    operator did not mean to touch, and there is no undo.
    """
    if explicit is not None:
        return explicit
    found = discover_chains()
    if not found:
        raise SystemExit(
            "No audit chain found under %LOCALAPPDATA%/BlarAI/audit. The Policy "
            "Agent's chain lives under its SERVICE root, not here — pass it with "
            "--audit-log. See docs/runbooks/audit_key_rotation.md."
        )
    if len(found) > 1:
        listing = chr(10).join("  " + str(path) for path in found)
        raise SystemExit(
            "More than one audit chain is present, and rotating the wrong one "
            "cannot be undone. Choose with --audit-log:" + chr(10) + listing
        )
    return found[0]


def rotate(
    *, audit_log_path: Path, new_key_name: str, dry_run: bool = False
) -> int:
    """Perform the rotation. Returns a process exit code."""
    from shared.security import tpm_signer
    from shared.security.audit_key_history import (
        append_key,
        history_path,
        read_history,
    )
    from shared.security.audit_log import (
        AUDIT_TPM_KEY_NAME,
        AuditChainError,
        AuditLog,
        AuditProvisioningError,
        TpmRecordSigner,
    )
    from shared.security.audit_verification import verification_start

    if not audit_log_path.exists():
        print(f"REFUSED: no audit log at {audit_log_path}.")
        return 2

    if not tpm_signer.is_available():
        print("REFUSED: no TPM available, so the audit key cannot be rotated here.")
        return 2

    history = read_history(audit_log_path)
    current_name = AUDIT_TPM_KEY_NAME
    if history:
        newest = history[-1]
        prefix, _, name = newest.partition(":")
        if not _ or not name:
            print(
                f"REFUSED: the key history's newest entry {newest!r} does not "
                "name a key as '<algorithm>:<name>'. Repair the history rather "
                "than deleting it — it records which keys this chain has used."
            )
            return 2
        current_name = name
    if new_key_name == current_name:
        print(
            f"REFUSED: {new_key_name!r} is already the current signing key. A "
            "rotation that changes nothing would still write a bridge record "
            "and leave you believing the key had changed."
        )
        return 2

    outgoing = TpmRecordSigner(key_name=current_name)
    log = AuditLog.from_path(audit_log_path, outgoing)

    # ── 1. the chain must be sound BEFORE we add to it ──────────────────────
    # verification_start, not a local ladder. The version written here called
    # tpm_key_resolver() with no argument -- it takes a required allowlist --
    # so step 1 raised TypeError on every invocation, and nothing drove rotate()
    # in the suite to notice. It also dropped key_order, which disengages
    # #1578's forged-chain lock inside the ceremony that exists to protect the
    # chain, and passed key_resolver=None whenever the first key was missing,
    # which is the false-TAMPER the guard exists to prevent (#1581).
    try:
        first, resolver, order = verification_start(audit_log_path)
    except AuditProvisioningError as exc:
        print(f"REFUSED: {exc}")
        return 3
    try:
        log.verify(signer=first, key_resolver=resolver, key_order=order, full=True)
    except AuditChainError as exc:
        # NOT exc.operator_guidance. For a key mismatch that text says to run
        # THIS ceremony — so printing it here told the operator to run the
        # command that had just refused, and the Policy Agent's own refusal
        # pointed at the same place. A refusal that points at itself leaves
        # someone with nowhere to go.
        if exc.fault == AuditChainError.TAMPER:
            remedy = (
                "The chain's CONTENTS were altered on disk. Preserve the file "
                "for investigation; do not delete or regenerate it, and do not "
                "rotate. Rotating would sign a bridge into a chain whose "
                "integrity is already in question, and afterwards nobody could "
                "tell which break came first."
            )
        else:
            remedy = (
                "The chain does not verify under the key this machine holds. "
                "Either a key was already changed without recording it, or the "
                "key history names a key that is no longer on this TPM. Check "
                f"the history beside the log ({history_path(audit_log_path)}) "
                "against the keys actually provisioned. A retired audit key "
                "cannot be regenerated: if it is gone, the records it signed "
                "cannot be verified again, and that is a fact to record rather "
                "than a state to rotate out of."
            )
        print(f"REFUSED: the chain does not verify as it stands [{exc.fault}]: {exc}")
        print()
        print(remedy)
        return 3
    print(f"OK   chain verifies under its current key ({current_name}).")

    if dry_run:
        print(
            f"DRY RUN: would provision {new_key_name!r}, append a bridge record "
            f"signed by {current_name!r}, and record the new key in the history. "
            "Nothing was changed."
        )
        return 0

    # ── 2. provision the incoming key ───────────────────────────────────────
    created = tpm_signer.ensure_key(new_key_name)
    print(
        f"OK   incoming key {new_key_name!r} "
        f"{'provisioned' if created else 'already present'} on the TPM."
    )

    # ── 3. the bridge ───────────────────────────────────────────────────────
    incoming = TpmRecordSigner(key_name=new_key_name)
    record = log.rotate_signing_key(incoming)
    print(f"OK   bridge record written at seq={record.seq}, signed by the OLD key.")

    # ── 4. the history ──────────────────────────────────────────────────────
    if not history:
        append_key(audit_log_path, outgoing.signer_id())
    append_key(audit_log_path, incoming.signer_id())
    print("OK   key history updated.")

    # ── 5. prove it, across the boundary ────────────────────────────────────
    try:
        start, resolver, order = verification_start(audit_log_path)
    except AuditProvisioningError as exc:
        print(f"FAILED: {exc}")
        return 4
    try:
        AuditLog.from_path(audit_log_path, incoming).verify(
            signer=start, key_resolver=resolver, key_order=order, full=True
        )
    except AuditChainError as exc:
        print(f"FAILED: the rotated chain does not verify [{exc.fault}]: {exc}")
        return 4

    print(
        "\nOK   the chain verifies ACROSS the rotation.\n\n"
        f"KEEP THE RETIRED KEY {current_name!r}. Records it signed verify under "
        "it and under nothing else, so deleting it destroys the verifiability of "
        "everything written before today. This script never deletes a key."
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--new-key", required=True, help="TPM key name for the incoming key."
    )
    parser.add_argument(
        "--audit-log",
        type=Path,
        default=None,
        help=(
            "Path to the audit chain. Required when more than one is present, "
            "and for the Policy Agent's chain, which lives under its service "
            "root rather than the user-data audit directory."
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Verify and report what would happen; change nothing.",
    )
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.WARNING, format="%(message)s")
    return rotate(
        audit_log_path=_resolve_log_path(args.audit_log),
        new_key_name=args.new_key,
        dry_run=args.dry_run,
    )


if __name__ == "__main__":  # pragma: no cover — operator entry point
    sys.exit(main())
