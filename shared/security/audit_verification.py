"""Where a possibly-rotated audit chain's verification walk must START (#1578).

A chain that has survived a key rotation cannot be verified from its current key
alone: its early records were signed by a key since retired. The walk must begin
at the OLDEST key the chain's history names and let the in-chain bridge records
carry it forward.

ONE implementation, deliberately. There were THREE, and each disagreed with the
others on the case that matters. The Policy Agent's refused when the oldest key
was absent from the TPM. The rotation ceremony's, inlined in ``rotate()`` under
no name, called ``tpm_key_resolver`` with no allowlist and so raised TypeError
on every invocation -- nothing drove that function, so a green gate said nothing
about it. The Assistant Orchestrator's returned ``None`` for it, which made
:meth:`AuditLog.verify` fall back to the log's own CURRENT signer and report a
TAMPER for a chain whose only problem was a retired key. A duplicated key ladder
is the shape this codebase has already been bitten by (#1543).

The mechanism, stated exactly because the plausible version is wrong: it is not
a signature check failing. With the newest key in force from record 0, the
forward-only guard in ``_row_verifier`` fires FIRST, with an explicit
``fault=TAMPER`` -- the first record "claims signing key 'keyA', which PRECEDES
the key already in force". The operator is then told their audit record was
ALTERED on disk. Reproduced against a real rotated chain during #1581's review.

Note for anyone adding a caller: a ``None`` first signer is NOT a neutral
default here. ``verify()`` reads it as "use the log's own signer", so returning
``None`` for an unavailable key silently selects the wrong one.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - typing only
    from collections.abc import Sequence

    from shared.security.audit_log import KeyResolver, RecordSigner

__all__ = ["signing_key_name", "verification_start"]


def verification_start(
    audit_log_path: "Path | str | None",
) -> "tuple[RecordSigner | None, KeyResolver | None, Sequence[str] | None]":
    """``(first signer, resolver, key order)`` for a possibly-rotated chain.

    Returns ``(None, None, None)`` when the chain has never rotated, which makes
    ``verify()`` behave exactly as it did before rotation existed — the
    no-history case must not change behaviour for chains that already exist.

    Raises:
        AuditProvisioningError: when the history names a first key this chip
            cannot supply. This refuses rather than falling back to the current
            key, because that fallback verifies the pre-rotation records against
            the wrong key and reports a TAMPER — telling the operator their log
            was altered when a key was merely retired.
    """
    from shared.security.audit_key_history import read_history
    from shared.security.audit_log import AuditProvisioningError, tpm_key_resolver

    if audit_log_path is None:
        return None, None, None
    history = read_history(Path(audit_log_path))
    if len(history) < 2:
        # Never rotated: one key, the one the caller already holds.
        return None, None, None
    resolver = tpm_key_resolver(history)
    first = resolver(history[0])
    if first is None:
        raise AuditProvisioningError(
            f"the audit key history names {history[0]!r} as this chain's first "
            "signing key, and that key is not available on this TPM. Records it "
            "signed verify under it and under nothing else, so the chain cannot "
            "be checked. A retired audit key must never be deleted; restore it "
            "before starting."
        )
    return first, resolver, history


def signing_key_name(audit_log_path: "Path | str | None") -> str:
    """The TPM key this chain must SIGN with: the newest its history names.

    Falls back to the compiled-in default only when the chain has never rotated.
    Per chain, not per machine — the ingest and verdict chains share a directory
    and each keeps its own history, so rotating one does not declare a key the
    other has adopted.

    Reading this, rather than hardcoding the default, is the difference between
    a rotation that works and one that bricks the service on its SECOND boot: a
    rotated chain would get new records signed by the RETIRED key, appended
    after a bridge declaring the new one. The first boot verifies — nothing
    follows the bridge yet — and the runbook calls that success. The next boot
    walks to the bridge, switches keys as designed, and refuses permanently,
    with the ceremony itself refusing to run on the chain it had broken.

    Raises:
        AuditProvisioningError: when the history's newest entry does not name a
            TPM key. This refuses rather than falling back to the default,
            because falling back is what produced that state.
    """
    from shared.security.audit_key_history import read_history
    from shared.security.audit_log import (
        AUDIT_TPM_KEY_NAME,
        AuditProvisioningError,
        TpmRecordSigner,
    )

    if audit_log_path is None:
        return AUDIT_TPM_KEY_NAME
    history = read_history(Path(audit_log_path))
    if not history:
        return AUDIT_TPM_KEY_NAME
    newest = history[-1]
    prefix = f"{TpmRecordSigner._ALGORITHM}:"
    if not newest.startswith(prefix) or not newest[len(prefix):]:
        raise AuditProvisioningError(
            f"the audit key history's newest entry {newest!r} does not name a "
            f"TPM key ({prefix}<name>). The chain cannot tell which key to sign "
            "with. Repair the history rather than deleting it."
        )
    return newest[len(prefix):]
