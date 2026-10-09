"""The audit signing keys this machine has used, oldest first (#1578).

A chain that has survived a key rotation cannot be verified from the current key
alone: its early records were signed by a key that has since been retired, and
the verifier has to start from the oldest one and walk forward. This file is how
a service learns where to start.

**IT IS A HINT, NOT A TRUST ROOT, AND THAT IS THE POINT.** It lives on the same
filesystem as the log, so anyone who can rewrite the log can rewrite this. What
stops that mattering is that the sequence of keys is established by SIGNATURES,
not by this file:

* the walk switches key only at a bridge record it has already verified under
  the key in force (``AUDIT_KEY_ROTATION_VERB``), and
* every key it switches to must actually resolve — on this machine that means
  the key exists on the TPM, which an attacker cannot arrange for a key they
  invented.

So a forged history naming an attacker's key produces a chain that fails to
verify, not one that verifies falsely. The worst a rewritten history can do is
deny service, which the refusal already reports loudly.

Retired keys are NEVER deleted. Records signed by a retired key verify under that
key and under nothing else, so deleting one destroys the verifiability of every
record it signed — which is the same outcome as losing the log.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Final

logger = logging.getLogger(__name__)

HISTORY_SUFFIX: Final[str] = "-keys.json"
"""Suffix for the history file, kept beside the audit log it describes.

PER CHAIN, not per directory. The Assistant Orchestrator keeps its ingest and
verdict chains in ONE directory, so a single shared ``audit-keys.json`` made a
per-chain rotation unrepresentable — rotating one would have declared a key the
other had not adopted.
"""

_SCHEMA: Final[str] = "blarai.audit-key-history/1"


class AuditKeyHistoryError(RuntimeError):
    """The history could not be read or written. Fail-closed, never a warning."""


def history_path(audit_log_path: Path | str) -> Path:
    """The history file for a given audit log, named after that log."""
    log = Path(audit_log_path)
    return log.parent / f"{log.stem}{HISTORY_SUFFIX}"


def read_history(audit_log_path: Path | str) -> list[str]:
    """Signer ids this log has used, OLDEST FIRST.

    Returns an empty list when no history exists, which is the correct reading
    for a log that has never rotated: its only key is the one the service
    already holds, and the caller starts from that.

    A malformed history raises rather than resolving to empty. Treating a
    corrupt file as "never rotated" would start the walk at the current key and
    report a rotated chain as a TAMPER — telling the operator their log was
    altered when their key merely changed, which is the misreport #1569 exists
    to prevent.
    """
    path = history_path(audit_log_path)
    if not path.exists():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise AuditKeyHistoryError(
            f"audit key history at {path} could not be read: {exc}. It records "
            "which signing keys this chain has used; without it a rotated chain "
            "cannot be verified. Restore it from backup rather than deleting it."
        ) from exc
    if not isinstance(payload, dict) or payload.get("schema") != _SCHEMA:
        raise AuditKeyHistoryError(
            f"audit key history at {path} is not a {_SCHEMA} document."
        )
    keys = payload.get("keys")
    if not isinstance(keys, list) or not all(isinstance(k, str) and k for k in keys):
        raise AuditKeyHistoryError(
            f"audit key history at {path} has a malformed 'keys' list."
        )
    return list(keys)


def append_key(audit_log_path: Path | str, signer_id: str) -> list[str]:
    """Record a newly adopted key as the newest entry. Returns the full order.

    Idempotent for a key already newest, so a re-run of a ceremony does not
    corrupt the order. A key that appears EARLIER in the history is refused:
    re-adopting a retired key would make the order ambiguous for any verifier
    walking forward, and the ambiguity is not resolvable from the file.
    """
    if not signer_id:
        raise AuditKeyHistoryError("refusing to record an empty signer id")
    existing = read_history(audit_log_path)
    if existing and existing[-1] == signer_id:
        return existing
    if signer_id in existing:
        raise AuditKeyHistoryError(
            f"signing key {signer_id!r} already appears earlier in the audit key "
            "history. Re-adopting a retired key makes the key order ambiguous "
            "for a verifier walking the chain forward. Provision a new key."
        )
    keys = [*existing, signer_id]
    path = history_path(audit_log_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(
        json.dumps({"schema": _SCHEMA, "keys": keys}, indent=2) + "\n",
        encoding="utf-8",
    )
    tmp.replace(path)
    logger.warning(
        "Audit key history updated: %s is now the current signing key (%d key(s) "
        "in total). Every earlier key must be RETAINED — records it signed verify "
        "under it and under nothing else.",
        signer_id, len(keys),
    )
    return keys
