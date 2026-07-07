"""Tamper-evident append-only audit log for adjudication decisions.

Sprint 13, Tier-1 security hardening (Vikunja #602 / Domain 7).
Sprint 14, Tier-2 — TPM-backed signer swap (Vikunja #605).
ISS-607 — segmented retention + bounded RAM (ADR-029).

Every AdjudicationContext produced by HybridAdjudicator.adjudicate_car() is
persisted here as a JSON-line record that is cryptographically chained to all
prior records: each record carries a SHA-256 hash of its own canonical fields
concatenated with the previous record's hash. Altering any field, deleting a
record, or reordering records breaks the chain downstream and is detected by
``AuditLog.verify()``.

Retention model — "segmented keep-everything with a bounded working set"
------------------------------------------------------------------------
ADR-029 (Vikunja #607).  The full forensic history is kept FOREVER, but in
sealed, individually-verifiable, gzip-compressed segments rotated at a
size/count cap.  Net effect: the in-RAM working set and the active file stay
bounded while complete history is retained on disk.  Never hard-delete by
default.

- **Rotation.** When the active file crosses ``max_active_bytes`` (default
  64 MiB) OR ``max_active_records`` (default 100_000) — whichever trips first
  — the active ``audit.jsonl`` is fsync'd, closed, renamed to a sealed segment
  ``audit-{first_seq:012d}-{last_seq:012d}-{YYYYMMDDTHHMMSSZ}.jsonl``,
  gzip-compressed to ``.jsonl.gz``, DACL-hardened (#637), and a fresh active
  file is started.  The chain is unbroken across the seam: the first record in
  the new active file carries ``prev_hash`` = the sealed segment's last
  ``record_hash``.
- **Segment index.** ``audit-segments.jsonl`` records, per sealed segment,
  ``{first_seq, last_seq, first_prev_hash, last_record_hash, file_sha256,
  segment_signature}``.  ``segment_signature`` is ``RecordSigner.sign()`` over
  the segment's canonical summary.  This index is the cross-segment verifiable
  anchor: a later ``verify()`` confirms the sealed segments form one unbroken,
  signed chain even though they live in separate files.
- **Bounded RAM (closes "unbounded memory growth").** At startup ONLY the
  active segment is loaded into ``self._records``; the chain head is restored
  from the active file's last record, or — if the active file is empty (just
  rotated) — from the segment index's ``last_record_hash`` / ``last_seq``.
  Sealed segments are NOT loaded into RAM.
- **verify(full=True).** The default ``verify()`` is fast (active segment +
  the segment-index anchor chain).  ``verify(full=True)`` walks every sealed
  segment (gunzip on the fly) + the active file end-to-end, and still raises
  ``AuditChainError`` at the first tamper anywhere — including inside a sealed
  ``.jsonl.gz``.
- **Retention ceiling — default OFF (keep all).** ``archive_max_bytes`` /
  ``archive_max_age_days`` default ``None`` (unlimited).  IF an operator ever
  sets one, WHOLE sealed segments are pruned oldest-first ONLY, and the prune
  itself is recorded as a normal chained+signed audit record with
  ``decision="RETENTION_PRUNE"`` / ``resource=<segment id>`` — so a later
  ``verify(full=True)`` sees a *documented, signed* gap (policy), distinguishable
  from a #606 tail-deletion attack.  Never prune mid-chain; never prune the
  active segment.

Design choices and trade-offs
------------------------------
- **Fail-closed on write error.** A write failure raises ``AuditSinkError``
  immediately. We do NOT silently drop records.  The coupling question (should
  a write failure block the authorization?) is NOT resolved here — the adjudicator
  surfaces the exception to its caller; the operator decides the policy at the
  integration point.  This keeps the audit primitive free of auth logic and
  maximises testability.
- **Fail-safe rotation.** Rotation must never lose a record or corrupt the
  chain.  If any rotation step fails it is logged and the log DEGRADES to the
  status-quo single unbounded active file (keep appending) rather than
  drop/corrupt a record.  The ``_write_record`` fail-closed contract is
  unchanged.
- **Deterministic hash inputs.** Timestamps and sequence numbers are injected
  as parameters (with defaults) so test harnesses can freeze them and get
  reproducible hashes.  Wall-clock is only used as a default for production.
- **Pluggable signer.** ``RecordSigner`` is the interface; ``HmacSha256Signer``
  is the stdlib-only software stub (dev/CI); ``TpmRecordSigner`` is the
  production implementation (Sprint 14 / #605), wrapping
  ``shared.security.tpm_signer.sign/verify`` with the dedicated audit key
  ``AUDIT_TPM_KEY_NAME`` — separation of duties from the PA JWT key.  Rotation
  is signer-agnostic; the production TPM path is unchanged.
- **Genesis constant.** ``GENESIS_HASH`` is the fixed predecessor hash for the
  first record — a well-known, documented constant, not random, so chain
  verification can be run without prior state.

Stdlib only (core path): gzip, hashlib, hmac, json, os, threading.  ``gzip`` is
stdlib — no new external dependency.  ``TpmRecordSigner`` lazily imports
``shared.security.tpm_signer`` (already in-tree).
"""

from __future__ import annotations

import gzip
import hashlib
import hmac
import json
import logging
import os
import threading
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterator, Sequence

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Genesis hash: predecessor for the very first record.  Fixed constant so the
# chain can be verified by any verifier without needing the "previous state."
# Value is SHA-256("BlarAI-audit-log-genesis-v1").
GENESIS_HASH: str = hashlib.sha256(b"BlarAI-audit-log-genesis-v1").hexdigest()

# Dedicated TPM key name for audit signing — MUST differ from the PA JWT key
# (separation of duties: Sprint 14 / ADR-018).  Provisioned once on-chip by
# the LA ceremony; the name is stable across reboots (persisted CNG key).
AUDIT_TPM_KEY_NAME: str = "BlarAI-Audit-Signing-Key-v1"

# --- Segmented retention (ISS-607 / ADR-029) -------------------------------

# Default rotation caps.  Whichever trips first rotates the active file into a
# sealed, compressed segment.  64 MiB keeps the active file (and the in-RAM
# working set) bounded; 100k records is the secondary trip for record-heavy /
# small-record runs.  Both are operator-overridable via config.
DEFAULT_MAX_ACTIVE_BYTES: int = 64 * 1024 * 1024  # 64 MiB
DEFAULT_MAX_ACTIVE_RECORDS: int = 100_000

# Filename of the segment index (the cross-segment verifiable anchor) and the
# sealed-segment / active filename conventions.  The active file keeps the
# historical name ``audit.jsonl``; sealed segments carry the seq-range + a UTC
# stamp so they sort chronologically and self-describe their coverage.
SEGMENT_INDEX_NAME: str = "audit-segments.jsonl"
SEALED_SEGMENT_PREFIX: str = "audit-"
SEALED_SEGMENT_SUFFIX: str = ".jsonl.gz"

# Decision string written for the self-auditing retention-prune meta-record.
# A later verify(full=True) sees the documented, signed gap this represents and
# distinguishes it from a #606 tail-deletion attack (which has NO such record).
RETENTION_PRUNE_DECISION: str = "RETENTION_PRUNE"


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class AuditSinkError(IOError):
    """Raised on any unrecoverable audit-log write failure (Fail-Closed)."""


class AuditProvisioningError(RuntimeError):
    """Raised at startup when the production audit log cannot be provisioned.

    Thrown by ``_build_audit_log`` in production (``dev_mode=False``) when the
    TPM audit key is unprovisioned or the TPM is unavailable.  The Policy Agent
    must refuse to start rather than run with no audit trail (ADR-025 §2.8(a)).
    Run the provisioning ceremony before starting in production mode.
    """


class AuditChainError(ValueError):
    """Raised by verify() when chain integrity is broken at a specific index."""

    def __init__(self, index: int, reason: str) -> None:
        self.index = index
        self.reason = reason
        super().__init__(f"Chain break at record {index}: {reason}")


# ---------------------------------------------------------------------------
# Signer interface
# ---------------------------------------------------------------------------


class RecordSigner(ABC):
    """Pluggable signing authority for audit records.

    Interface mirrors shared.security.tpm_signer (sign/verify) so the
    TPM-backed implementation swaps in as a drop-in at the integration site.

    sign(data) -> bytes       — produce a signature over canonical bytes.
    verify(data, sig) -> bool — True iff signature is authentic.
    signer_id() -> str        — stable identifier for the key/algorithm
                                 (written into every record so verifiers
                                 know which key to use).
    """

    @abstractmethod
    def sign(self, data: bytes) -> bytes:
        """Produce a signature over ``data``.  Returns raw signature bytes."""

    @abstractmethod
    def verify(self, data: bytes, signature: bytes) -> bool:
        """Return True iff ``signature`` is authentic for ``data``."""

    @abstractmethod
    def signer_id(self) -> str:
        """Stable identifier for this signer (key name / algorithm label)."""


class HmacSha256Signer(RecordSigner):
    """Software-stub signer: HMAC-SHA256 with a local dev key.

    Suitable for development, CI, and pre-TPM operation.  The ``key``
    parameter accepts any bytes; in production it should come from the
    DPAPI-protected store or a secrets file outside the repo.

    TPM swap path: replace this signer at the ``HybridAdjudicator.from_config``
    site with a class that wraps ``shared.security.tpm_signer.sign`` /
    ``tpm_signer.verify``.  The interface is identical so no other code changes.
    """

    _ALGORITHM: str = "HMAC-SHA256"

    def __init__(self, key: bytes, key_id: str = "dev-stub") -> None:
        if not key:
            raise ValueError("HmacSha256Signer: key must be non-empty bytes.")
        self._key = key
        self._key_id = key_id

    def sign(self, data: bytes) -> bytes:
        return hmac.new(self._key, data, hashlib.sha256).digest()

    def verify(self, data: bytes, signature: bytes) -> bool:
        expected = hmac.new(self._key, data, hashlib.sha256).digest()
        return hmac.compare_digest(expected, signature)

    def signer_id(self) -> str:
        return f"{self._ALGORITHM}:{self._key_id}"


class TpmRecordSigner(RecordSigner):
    """Production-grade signer: ECDSA P-256 via the Windows CNG TPM 2.0 provider.

    Wraps ``shared.security.tpm_signer.sign`` / ``tpm_signer.verify`` with a
    **dedicated audit key** (``AUDIT_TPM_KEY_NAME``) — never the PA JWT key.
    Separation of duties: the private key is non-exportable and chip-bound;
    even an attacker with full filesystem access cannot forge a new signature
    because they cannot extract the private key.

    Sprint 14 / Vikunja #605: drop-in replacement for ``HmacSha256Signer``
    at the ``_build_audit_log`` factory site.  The interface is identical so
    no other code changes when this class is wired in.

    Fail-closed contract
    --------------------
    - If the TPM is unavailable (non-Windows, no chip, or provisioning not
      run), ``sign`` raises ``TpmRecordSignerError`` — never silently falling
      back to a weaker key.
    - ``verify`` returns ``False`` on a bad signature and raises
      ``TpmRecordSignerError`` on unexpected CNG failures.

    Key provisioning
    ----------------
    ``ensure_key()`` is called lazily on first ``sign`` call so the object is
    constructible without a TPM (safe for test fixtures that never call sign).
    In production the key is pre-provisioned by the LA ceremony; the lazy call
    is idempotent and harmless.
    """

    _ALGORITHM: str = "ECDSA-P256-TPM"

    def __init__(self, key_name: str = AUDIT_TPM_KEY_NAME) -> None:
        self._key_name = key_name

    def sign(self, data: bytes) -> bytes:
        """Sign ``data`` via the TPM-held audit key.  Fail-closed on unavailability."""
        from shared.security import tpm_signer as _tpm

        try:
            _tpm.ensure_key(self._key_name)
            return _tpm.sign(self._key_name, data)
        except (_tpm.TpmUnavailable, _tpm.TpmSigningError) as exc:
            raise TpmRecordSignerError(
                f"TPM audit signing failed for key '{self._key_name}': {exc}"
            ) from exc

    def verify(self, data: bytes, signature: bytes) -> bool:
        """Verify ``signature`` via the TPM-held audit key.  Returns False on bad sig."""
        from shared.security import tpm_signer as _tpm

        try:
            return _tpm.verify(self._key_name, data, signature)
        except (_tpm.TpmUnavailable, _tpm.TpmSigningError) as exc:
            raise TpmRecordSignerError(
                f"TPM audit verification failed for key '{self._key_name}': {exc}"
            ) from exc

    def signer_id(self) -> str:
        return f"{self._ALGORITHM}:{self._key_name}"


class TpmRecordSignerError(RuntimeError):
    """Raised when the TPM audit signer cannot sign or verify (Fail-Closed)."""


# ---------------------------------------------------------------------------
# Record schema
# ---------------------------------------------------------------------------


class AuditRecord:
    """One immutable audit record in the chain.

    Canonical fields (covered by record_hash and signature):
      seq, adjudication_id, decision, car_hash, source_agent,
      destination_service, verb, resource, sensitivity,
      rule_engine_passed, confidence, timestamp_utc, prev_hash.

    Non-canonical (set after hashing; not part of the hash input):
      record_hash, signature.
    """

    __slots__ = (
        "seq",
        "adjudication_id",
        "decision",
        "car_hash",
        "source_agent",
        "destination_service",
        "verb",
        "resource",
        "sensitivity",
        "rule_engine_passed",
        "confidence",
        "timestamp_utc",
        "prev_hash",
        "record_hash",
        "signature",
        "signer_id",
    )

    def __init__(
        self,
        *,
        seq: int,
        adjudication_id: str,
        decision: str,
        car_hash: str,
        source_agent: str,
        destination_service: str,
        verb: str,
        resource: str,
        sensitivity: str,
        rule_engine_passed: bool,
        confidence: float,
        timestamp_utc: str,
        prev_hash: str,
        record_hash: str,
        signature: str,
        signer_id: str,
    ) -> None:
        self.seq = seq
        self.adjudication_id = adjudication_id
        self.decision = decision
        self.car_hash = car_hash
        self.source_agent = source_agent
        self.destination_service = destination_service
        self.verb = verb
        self.resource = resource
        self.sensitivity = sensitivity
        self.rule_engine_passed = rule_engine_passed
        self.confidence = confidence
        self.timestamp_utc = timestamp_utc
        self.prev_hash = prev_hash
        self.record_hash = record_hash
        self.signature = signature
        self.signer_id = signer_id

    def to_dict(self) -> dict[str, Any]:
        return {
            "seq": self.seq,
            "adjudication_id": self.adjudication_id,
            "decision": self.decision,
            "car_hash": self.car_hash,
            "source_agent": self.source_agent,
            "destination_service": self.destination_service,
            "verb": self.verb,
            "resource": self.resource,
            "sensitivity": self.sensitivity,
            "rule_engine_passed": self.rule_engine_passed,
            "confidence": self.confidence,
            "timestamp_utc": self.timestamp_utc,
            "prev_hash": self.prev_hash,
            "record_hash": self.record_hash,
            "signature": self.signature,
            "signer_id": self.signer_id,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "AuditRecord":
        return cls(
            seq=int(d["seq"]),
            adjudication_id=str(d["adjudication_id"]),
            decision=str(d["decision"]),
            car_hash=str(d["car_hash"]),
            source_agent=str(d["source_agent"]),
            destination_service=str(d["destination_service"]),
            verb=str(d["verb"]),
            resource=str(d["resource"]),
            sensitivity=str(d["sensitivity"]),
            rule_engine_passed=bool(d["rule_engine_passed"]),
            confidence=float(d["confidence"]),
            timestamp_utc=str(d["timestamp_utc"]),
            prev_hash=str(d["prev_hash"]),
            record_hash=str(d["record_hash"]),
            signature=str(d["signature"]),
            signer_id=str(d["signer_id"]),
        )


def _canonical_bytes(
    seq: int,
    adjudication_id: str,
    decision: str,
    car_hash: str,
    source_agent: str,
    destination_service: str,
    verb: str,
    resource: str,
    sensitivity: str,
    rule_engine_passed: bool,
    confidence: float,
    timestamp_utc: str,
    prev_hash: str,
) -> bytes:
    """Produce the canonical byte string that is hashed + signed.

    Uses sort_keys + separators to guarantee determinism across Python versions.
    ``confidence`` is rounded to 9 decimal places to avoid float repr drift.
    """
    d = {
        "seq": seq,
        "adjudication_id": adjudication_id,
        "decision": decision,
        "car_hash": car_hash,
        "source_agent": source_agent,
        "destination_service": destination_service,
        "verb": verb,
        "resource": resource,
        "sensitivity": sensitivity,
        "rule_engine_passed": rule_engine_passed,
        "confidence": round(confidence, 9),
        "timestamp_utc": timestamp_utc,
        "prev_hash": prev_hash,
    }
    return json.dumps(d, sort_keys=True, separators=(",", ":")).encode("utf-8")


# ---------------------------------------------------------------------------
# Segment index entry (ISS-607 / ADR-029)
# ---------------------------------------------------------------------------


def _segment_summary_bytes(
    first_seq: int,
    last_seq: int,
    first_prev_hash: str,
    last_record_hash: str,
    file_sha256: str,
) -> bytes:
    """Canonical byte string for a sealed segment's summary (hashed + signed).

    The ``segment_signature`` in the index is ``RecordSigner.sign()`` over this.
    Binding ``file_sha256`` into the signed summary means a verifier can detect
    *both* a swapped/edited segment file (the SHA changes) *and* a forged index
    row (the signature fails) — the two together are the cross-segment anchor.
    Deterministic via sort_keys + tight separators, same as ``_canonical_bytes``.
    """
    d = {
        "first_seq": first_seq,
        "last_seq": last_seq,
        "first_prev_hash": first_prev_hash,
        "last_record_hash": last_record_hash,
        "file_sha256": file_sha256,
    }
    return json.dumps(d, sort_keys=True, separators=(",", ":")).encode("utf-8")


class SegmentEntry:
    """One sealed-segment row in ``audit-segments.jsonl`` (the anchor index).

    Records the seq range a sealed segment covers, the chain-linkage hashes at
    its boundaries (``first_prev_hash`` / ``last_record_hash``), the SHA-256 of
    the *compressed* ``.jsonl.gz`` file on disk, and a signature over the
    canonical summary (``_segment_summary_bytes``).  ``filename`` is recorded
    too so the index is self-locating, but it is NOT part of the signed summary
    (a rename is benign as long as the content SHA still matches a row).
    """

    __slots__ = (
        "first_seq",
        "last_seq",
        "first_prev_hash",
        "last_record_hash",
        "file_sha256",
        "segment_signature",
        "filename",
        "signer_id",
    )

    def __init__(
        self,
        *,
        first_seq: int,
        last_seq: int,
        first_prev_hash: str,
        last_record_hash: str,
        file_sha256: str,
        segment_signature: str,
        filename: str,
        signer_id: str,
    ) -> None:
        self.first_seq = first_seq
        self.last_seq = last_seq
        self.first_prev_hash = first_prev_hash
        self.last_record_hash = last_record_hash
        self.file_sha256 = file_sha256
        self.segment_signature = segment_signature
        self.filename = filename
        self.signer_id = signer_id

    def to_dict(self) -> dict[str, Any]:
        return {
            "first_seq": self.first_seq,
            "last_seq": self.last_seq,
            "first_prev_hash": self.first_prev_hash,
            "last_record_hash": self.last_record_hash,
            "file_sha256": self.file_sha256,
            "segment_signature": self.segment_signature,
            "filename": self.filename,
            "signer_id": self.signer_id,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "SegmentEntry":
        return cls(
            first_seq=int(d["first_seq"]),
            last_seq=int(d["last_seq"]),
            first_prev_hash=str(d["first_prev_hash"]),
            last_record_hash=str(d["last_record_hash"]),
            file_sha256=str(d["file_sha256"]),
            segment_signature=str(d["segment_signature"]),
            filename=str(d["filename"]),
            signer_id=str(d.get("signer_id", "")),
        )

    def summary_bytes(self) -> bytes:
        return _segment_summary_bytes(
            self.first_seq,
            self.last_seq,
            self.first_prev_hash,
            self.last_record_hash,
            self.file_sha256,
        )


# ---------------------------------------------------------------------------
# AuditLog — main class
# ---------------------------------------------------------------------------


class AuditLog:
    """Append-only, cryptographically-chained adjudication audit log.

    Usage (production)
    ------------------
    ::

        signer = HmacSha256Signer(key=os.environ["AUDIT_HMAC_KEY"].encode())
        log = AuditLog(path=Path("/var/blarai/audit.jsonl"), signer=signer)
        adjudicator = HybridAdjudicator.from_config(..., audit_log=log)

    Usage (tests)
    -------------
    ::

        log = AuditLog(path=None, signer=HmacSha256Signer(b"test-key"))
        # Records accumulate in-memory; no disk I/O.

    Thread safety
    -------------
    All write operations are protected by a reentrant lock — the adjudicator
    may be called from multiple threads in future configurations.

    Segmented retention (ISS-607 / ADR-029)
    ---------------------------------------
    When file-backed, the active file ``audit.jsonl`` is rotated into sealed,
    gzip-compressed segments once ``max_active_bytes`` OR ``max_active_records``
    is crossed (see the module docstring).  ``self._records`` then holds only
    the **active** segment — bounded RAM — while the full history is retained on
    disk as ``audit-*.jsonl.gz`` segments anchored by ``audit-segments.jsonl``.

    ``on_rotate`` (legacy hook)
    ---------------------------
    Pass ``on_rotate`` to ALSO receive a callback after each append (called with
    the current active ``Path``).  This predates the built-in segmentation and
    is retained for back-compat; the built-in size/count rotation runs
    independently and does not require it.
    """

    def __init__(
        self,
        *,
        path: Path | None,
        signer: RecordSigner,
        on_rotate: Callable[[Path], None] | None = None,
        max_active_bytes: int = DEFAULT_MAX_ACTIVE_BYTES,
        max_active_records: int = DEFAULT_MAX_ACTIVE_RECORDS,
        archive_max_bytes: int | None = None,
        archive_max_age_days: int | None = None,
    ) -> None:
        """
        Args:
            path: Filesystem path for the active JSONL audit log.  ``None`` means
                in-memory only (useful for tests and unit isolation).
            signer: Implementation of ``RecordSigner`` to sign each record.
            on_rotate: Optional back-compat callback invoked after each append.
            max_active_bytes: Active-file byte cap; crossing it rotates the file
                into a sealed segment.  Default 64 MiB.  ``<= 0`` disables the
                byte trip.
            max_active_records: Active-file record-count cap; crossing it
                rotates.  Default 100_000.  ``<= 0`` disables the count trip.
            archive_max_bytes: Retention ceiling on TOTAL sealed-segment bytes.
                ``None`` (default) = keep everything (the ADR-029 policy).  If
                set, whole sealed segments are pruned oldest-first until the
                total fits, and each prune is itself audited.
            archive_max_age_days: Retention ceiling on sealed-segment age (by the
                UTC stamp in the segment filename).  ``None`` (default) = keep
                everything.  If set, sealed segments older than this are pruned
                oldest-first, each prune audited.
        """
        self._path = path
        self._signer = signer
        self._on_rotate = on_rotate
        self._max_active_bytes = max_active_bytes
        self._max_active_records = max_active_records
        self._archive_max_bytes = archive_max_bytes
        self._archive_max_age_days = archive_max_age_days
        self._lock = threading.RLock()
        self._records: list[AuditRecord] = []
        self._prev_hash: str = GENESIS_HASH
        self._seq: int = 0
        # Byte size of the active file (tracked incrementally; the rotation
        # byte-trip checks this rather than stat()-ing on every append).
        self._active_bytes: int = 0
        # The sealed-segment index rows (the cross-segment anchor), in seq order.
        self._segments: list[SegmentEntry] = []
        # Re-entrancy guard: True while a retention prune is in progress, so the
        # prune meta-record's own append→rotate cannot recurse into retention.
        self._enforcing_retention: bool = False
        # #637 (DATA_MAP §7 item 1): the audit log is a CRITICAL forensic store.
        # We apply the owner-only DACL once, on the first write that creates the
        # file on disk (the file may not exist at construction time).  This flag
        # gates that one-time call so appends don't repeat it.
        self._dacl_hardened: bool = False

        if path is not None:
            path.parent.mkdir(parents=True, exist_ok=True)
            self._segment_index_path: Path | None = path.parent / SEGMENT_INDEX_NAME
            self._load_segment_index()
            self._load_existing()
            # If the file already exists (restart with prior records), harden it
            # now so an existing audit log is locked down at startup too.
            if path.exists():
                self._harden_file_dacl()
        else:
            self._segment_index_path = None

    def _load_segment_index(self) -> None:
        """Load the sealed-segment index (``audit-segments.jsonl``) into RAM.

        Only the lightweight per-segment anchor rows are loaded — NOT the sealed
        records themselves (that is the whole point: bounded RAM).  A missing
        index file is normal (no rotation has happened yet).
        """
        if self._segment_index_path is None or not self._segment_index_path.exists():
            return
        try:
            with open(self._segment_index_path, "r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    self._segments.append(SegmentEntry.from_dict(json.loads(line)))
        except Exception as exc:
            raise AuditSinkError(
                f"Failed to load audit segment index at "
                f"{self._segment_index_path}: {exc}"
            ) from exc

    def _load_existing(self) -> None:
        """Load the ACTIVE segment into RAM and restore chain head.

        Bounded-RAM startup (ISS-607): only the active ``audit.jsonl`` is read
        into ``self._records``; sealed segments stay on disk.  The chain head
        (``_prev_hash`` / ``_seq``) is restored from the active file's last
        record, or — when the active file is empty/absent (just rotated, or a
        restart immediately after rotation) — from the segment index's last
        ``last_record_hash`` / ``last_seq + 1``.
        """
        assert self._path is not None
        if self._path.exists():
            try:
                with open(self._path, "r", encoding="utf-8") as fh:
                    for line in fh:
                        line = line.strip()
                        if not line:
                            continue
                        rec = AuditRecord.from_dict(json.loads(line))
                        self._records.append(rec)
                self._active_bytes = self._path.stat().st_size
            except Exception as exc:
                raise AuditSinkError(
                    f"Failed to load existing audit log at {self._path}: {exc}"
                ) from exc

        if self._records:
            last = self._records[-1]
            self._prev_hash = last.record_hash
            self._seq = last.seq + 1
        elif self._segments:
            # Active file empty but sealed history exists: continue the chain
            # from the last sealed segment so a post-rotation restart links up.
            tail = self._segments[-1]
            self._prev_hash = tail.last_record_hash
            self._seq = tail.last_seq + 1

    @property
    def record_count(self) -> int:
        """Number of records in the ACTIVE segment (bounded; not total history).

        Sealed segments are not counted here — use :meth:`total_record_count`
        for the full-history figure.  Kept active-only so the in-RAM ``records``
        view and this count stay in sync after a rotation.
        """
        with self._lock:
            return len(self._records)

    @property
    def total_record_count(self) -> int:
        """Total records across all sealed segments + the active segment.

        Derived from the segment index seq ranges + the active records, so it
        does not require loading any sealed segment into RAM.  Sealed segments
        that were pruned (RETENTION_PRUNE) are excluded — this counts what is
        currently retained on disk, not the high-water seq.
        """
        with self._lock:
            sealed = sum(
                (seg.last_seq - seg.first_seq + 1) for seg in self._segments
            )
            return sealed + len(self._records)

    @property
    def records(self) -> Sequence[AuditRecord]:
        """Read-only view of the ACTIVE segment's records (in append order).

        After a rotation this reflects only the active segment — the bound that
        closes the unbounded-RAM gap.  Sealed history is on disk; walk it with
        ``verify(full=True)`` or :meth:`iter_all_records`.
        """
        with self._lock:
            return list(self._records)

    @property
    def segment_count(self) -> int:
        """Number of sealed segments currently retained on disk."""
        with self._lock:
            return len(self._segments)

    def append(
        self,
        *,
        adjudication_id: str,
        decision: str,
        car_hash: str,
        source_agent: str,
        destination_service: str,
        verb: str,
        resource: str,
        sensitivity: str,
        rule_engine_passed: bool,
        confidence: float,
        timestamp_utc: str | None = None,
    ) -> AuditRecord:
        """Append a new record to the audit chain.

        Args:
            timestamp_utc: ISO-8601 UTC timestamp string.  Defaults to
                ``datetime.now(timezone.utc).isoformat()`` when None.
                Inject a fixed value in tests for reproducible hashes.

        Returns:
            The ``AuditRecord`` that was persisted.

        Raises:
            AuditSinkError: If the write fails (Fail-Closed — never silent).
        """
        if timestamp_utc is None:
            timestamp_utc = datetime.now(timezone.utc).isoformat()

        with self._lock:
            seq = self._seq
            prev_hash = self._prev_hash

            canon = _canonical_bytes(
                seq=seq,
                adjudication_id=adjudication_id,
                decision=decision,
                car_hash=car_hash,
                source_agent=source_agent,
                destination_service=destination_service,
                verb=verb,
                resource=resource,
                sensitivity=sensitivity,
                rule_engine_passed=rule_engine_passed,
                confidence=confidence,
                timestamp_utc=timestamp_utc,
                prev_hash=prev_hash,
            )

            # record_hash = sha256(canonical_fields || prev_hash) — the prev_hash
            # is already included inside `canon`, so a plain sha256(canon) achieves
            # the chaining property.
            record_hash = hashlib.sha256(canon).hexdigest()
            sig_bytes = self._signer.sign(canon)
            signature = sig_bytes.hex()

            record = AuditRecord(
                seq=seq,
                adjudication_id=adjudication_id,
                decision=decision,
                car_hash=car_hash,
                source_agent=source_agent,
                destination_service=destination_service,
                verb=verb,
                resource=resource,
                sensitivity=sensitivity,
                rule_engine_passed=rule_engine_passed,
                confidence=confidence,
                timestamp_utc=timestamp_utc,
                prev_hash=prev_hash,
                record_hash=record_hash,
                signature=signature,
                signer_id=self._signer.signer_id(),
            )

            line_bytes = self._write_record(record)

            self._records.append(record)
            self._prev_hash = record_hash
            self._seq += 1
            self._active_bytes += line_bytes

            if self._on_rotate is not None and self._path is not None:
                self._on_rotate(self._path)

            # Built-in segmentation (ISS-607).  Fail-safe: a rotation failure is
            # logged and the log keeps appending to the (now over-cap) active
            # file — never drops or corrupts a record.
            if self._path is not None and self._should_rotate():
                self._rotate_active_segment()

            return record

    def _harden_file_dacl(self) -> None:
        """Apply the #637 owner-only DACL to the audit-log file (once).

        DATA_MAP §7 item 1: the adjudication audit log is a CRITICAL forensic
        record — lock it to (current user + SYSTEM) full control on top of the
        per-record signature chain.  Owner-preserving + fail-safe
        (``shared.security.file_dacl`` never raises and never blocks writes), so
        this can never break the audit path.  Idempotent + gated on
        ``_dacl_hardened`` so it runs at most once per log instance.  No-op in
        in-memory mode and on non-Windows hosts.
        """
        if self._dacl_hardened or self._path is None:
            return
        self._dacl_hardened = True  # set first: a failing helper must not retry forever
        try:
            from shared.security.file_dacl import ensure_owner_only_dacl

            ensure_owner_only_dacl(self._path)
        except Exception:  # noqa: BLE001 — fail-safe: never block the audit write
            # The helper itself is already fail-safe; this is belt-and-suspenders
            # so even an import error here can never propagate into the write path.
            logger.warning(
                "Audit-log DACL hardening raised unexpectedly; proceeding with "
                "existing ACLs on %s",
                self._path,
            )

    def _write_record(self, record: AuditRecord) -> int:
        """Persist a single record as a JSON line.  Raises AuditSinkError on failure.

        Returns the number of bytes written for the line (0 in in-memory mode),
        so the caller can track the active-file size incrementally for the
        rotation byte-trip without re-``stat``-ing on every append.
        """
        if self._path is None:
            return 0  # in-memory mode
        encoded = (json.dumps(record.to_dict(), separators=(",", ":")) + "\n").encode(
            "utf-8"
        )
        try:
            with open(self._path, "ab") as fh:
                fh.write(encoded)
                fh.flush()
                os.fsync(fh.fileno())
        except OSError as exc:
            raise AuditSinkError(
                f"Audit-log write failed at {self._path}: {exc}"
            ) from exc
        # Lock down the file once it exists on disk (first successful write).
        self._harden_file_dacl()
        return len(encoded)

    # -- Segment rotation (ISS-607 / ADR-029) -------------------------------

    def _rotation_has_occurred(self) -> bool:
        """True iff this on-disk log has ever rotated (segment index file exists).

        The index file is created on the first rotation and PERSISTS thereafter
        — even after a retention prune removes every sealed row (it is rewritten
        empty, never deleted).  So its presence is the durable signal that the
        active segment may legitimately start mid-chain (a documented gap),
        distinguishing a rotated/pruned log from an unrotated single-file log
        whose first record must chain from ``GENESIS_HASH``.
        """
        if self._segment_index_path is None:
            return False
        if self._segments:
            return True
        return self._segment_index_path.exists()

    def _should_rotate(self) -> bool:
        """True iff the active file has crossed a (positive) size/count cap.

        Whichever cap trips first rotates.  A cap of ``<= 0`` disables that trip.
        We never rotate an empty active file (nothing to seal).
        """
        if not self._records:
            return False
        if self._max_active_records > 0 and len(self._records) >= self._max_active_records:
            return True
        if self._max_active_bytes > 0 and self._active_bytes >= self._max_active_bytes:
            return True
        return False

    def _sealed_segment_filename(self, first_seq: int, last_seq: int) -> str:
        """``audit-{first:012d}-{last:012d}-{YYYYMMDDTHHMMSSZ}.jsonl.gz``.

        The UTC stamp makes the name sort chronologically and self-describe the
        seal time; the seq range makes it self-describe its coverage.
        """
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        return (
            f"{SEALED_SEGMENT_PREFIX}{first_seq:012d}-{last_seq:012d}-"
            f"{stamp}{SEALED_SEGMENT_SUFFIX}"
        )

    def _rotate_active_segment(self) -> None:
        """Seal the active file into a compressed segment + start a fresh active.

        Steps (all under the write lock):
          1. fsync the active file, gzip-compress it to the sealed ``.jsonl.gz``
             name, fsync the sealed file, then remove the plaintext active file.
          2. Compute the sealed file's SHA-256 + the signed segment summary and
             append a row to the segment index (itself fsync'd + DACL-hardened).
          3. DACL-harden the sealed segment.
          4. Reset the in-RAM active segment to empty (bounded RAM); the chain
             head (``_prev_hash`` / ``_seq``) is unchanged so the next record
             links straight across the seam.
          5. Enforce the retention ceiling (default off).

        FAIL-SAFE: any exception is logged and the method returns WITHOUT
        mutating chain state — the over-cap active file is kept and appends
        continue (degrade to status-quo unbounded), never dropping a record.
        Partial artifacts (a half-written sealed file) are cleaned up.
        """
        assert self._path is not None
        if not self._records:
            return
        first_seq = self._records[0].seq
        last_seq = self._records[-1].seq
        first_prev_hash = self._records[0].prev_hash
        last_record_hash = self._records[-1].record_hash

        sealed_name = self._sealed_segment_filename(first_seq, last_seq)
        sealed_path = self._path.parent / sealed_name

        try:
            # 1. Compress the active file into the sealed segment.  Read the raw
            #    bytes so the gzip member is an exact copy of the active file.
            raw = self._path.read_bytes()
            with open(sealed_path, "wb") as raw_fh:
                with gzip.GzipFile(fileobj=raw_fh, mode="wb", mtime=0) as gz:
                    gz.write(raw)
                raw_fh.flush()
                os.fsync(raw_fh.fileno())

            # 2. SHA-256 over the COMPRESSED file (what the index pins) + sign.
            file_sha256 = hashlib.sha256(sealed_path.read_bytes()).hexdigest()
            summary = _segment_summary_bytes(
                first_seq, last_seq, first_prev_hash, last_record_hash, file_sha256
            )
            segment_signature = self._signer.sign(summary).hex()
            entry = SegmentEntry(
                first_seq=first_seq,
                last_seq=last_seq,
                first_prev_hash=first_prev_hash,
                last_record_hash=last_record_hash,
                file_sha256=file_sha256,
                segment_signature=segment_signature,
                filename=sealed_name,
                signer_id=self._signer.signer_id(),
            )
            self._append_segment_index_entry(entry)

            # 3. DACL-harden the sealed segment (fail-safe; never raises).
            self._harden_path_dacl(sealed_path)

            # 4. Atomically replace the active file with a fresh empty one only
            #    AFTER the sealed copy + index row are durable.  Truncate by
            #    re-creating; chain head is unchanged.
            with open(self._path, "wb") as fh:
                fh.flush()
                os.fsync(fh.fileno())
            self._records = []
            self._active_bytes = 0
            self._segments.append(entry)
            logger.info(
                "Audit-log rotated: sealed seq %d..%d into %s (%d bytes compressed)",
                first_seq,
                last_seq,
                sealed_name,
                len(sealed_path.read_bytes()) if sealed_path.exists() else -1,
            )
        except Exception as exc:  # noqa: BLE001 — fail-safe: never drop a record
            logger.error(
                "Audit-log rotation FAILED (%s); keeping the active file and "
                "continuing to append (degraded to unbounded). No record lost.",
                exc,
            )
            # Clean up any partial sealed artifact so a retry/full-verify is not
            # tripped by a truncated .gz.  Best-effort; failure here is ignored.
            try:
                if sealed_path.exists():
                    sealed_path.unlink()
            except OSError:
                pass
            return

        # 5. Retention ceiling (default off — keep everything).  Runs only when
        #    a ceiling is configured; itself fail-safe.  The re-entrancy guard
        #    prevents the prune meta-record's own append→rotate from recursing
        #    back into retention enforcement (it is already running in the loop).
        if (
            (self._archive_max_bytes is not None or self._archive_max_age_days is not None)
            and not self._enforcing_retention
        ):
            self._enforce_retention()

    def _append_segment_index_entry(self, entry: SegmentEntry) -> None:
        """Append one row to ``audit-segments.jsonl`` (fsync'd + DACL-hardened).

        Raises ``AuditSinkError`` on write failure so the caller's fail-safe
        wrapper treats a failed index write as a failed rotation (degrade, do
        not lose the active file).
        """
        assert self._segment_index_path is not None
        line = (json.dumps(entry.to_dict(), separators=(",", ":")) + "\n").encode("utf-8")
        try:
            with open(self._segment_index_path, "ab") as fh:
                fh.write(line)
                fh.flush()
                os.fsync(fh.fileno())
        except OSError as exc:
            raise AuditSinkError(
                f"Audit segment-index write failed at "
                f"{self._segment_index_path}: {exc}"
            ) from exc
        self._harden_path_dacl(self._segment_index_path)

    def _harden_path_dacl(self, path: Path) -> None:
        """Apply the #637 owner-only DACL to an arbitrary sealed artifact.

        Fail-safe: ``ensure_owner_only_dacl`` never raises and never blocks; this
        wrapper additionally swallows an import error so DACL hardening can never
        propagate into the rotation path.  No-op on non-Windows hosts.
        """
        try:
            from shared.security.file_dacl import ensure_owner_only_dacl

            ensure_owner_only_dacl(path)
        except Exception:  # noqa: BLE001 — fail-safe: never block the audit path
            logger.warning(
                "Audit-log DACL hardening raised unexpectedly for %s; proceeding "
                "with existing ACLs",
                path,
            )

    # -- Retention ceiling (ISS-607 / ADR-029; default OFF) -----------------

    def _segment_age_days(self, entry: SegmentEntry) -> float | None:
        """Age in days of a sealed segment, from the UTC stamp in its filename.

        Returns ``None`` if the stamp cannot be parsed (then age is treated as
        unknown and the age-prune skips it — fail-safe toward keeping data).
        """
        # Filename: audit-{first:012d}-{last:012d}-{YYYYMMDDTHHMMSSZ}.jsonl.gz
        stem = entry.filename
        if stem.endswith(SEALED_SEGMENT_SUFFIX):
            stem = stem[: -len(SEALED_SEGMENT_SUFFIX)]
        parts = stem.split("-")
        if len(parts) < 4:
            return None
        try:
            sealed_at = datetime.strptime(parts[-1], "%Y%m%dT%H%M%SZ").replace(
                tzinfo=timezone.utc
            )
        except ValueError:
            return None
        return (datetime.now(timezone.utc) - sealed_at).total_seconds() / 86400.0

    def _retention_overage(self) -> list[SegmentEntry]:
        """Sealed segments to prune (oldest-first) to satisfy the ceiling.

        Returns the prefix of ``self._segments`` (oldest first) that must be
        removed so the remaining sealed bytes fit ``archive_max_bytes`` and no
        remaining segment exceeds ``archive_max_age_days``.  The active segment
        is never included (it is not in ``self._segments``).  Never returns a
        non-prefix selection — pruning is always a contiguous oldest-first cut
        so the surviving sealed chain stays unbroken.
        """
        if not self._segments:
            return []
        to_prune: list[SegmentEntry] = []
        remaining = list(self._segments)

        # Age trip: drop oldest while the oldest is older than the age ceiling.
        if self._archive_max_age_days is not None:
            while remaining:
                age = self._segment_age_days(remaining[0])
                if age is not None and age > self._archive_max_age_days:
                    to_prune.append(remaining.pop(0))
                else:
                    break

        # Bytes trip: drop oldest while total sealed bytes exceed the ceiling.
        if self._archive_max_bytes is not None:

            def _seg_bytes(seg: SegmentEntry) -> int:
                p = self._path.parent / seg.filename if self._path else None
                try:
                    return p.stat().st_size if p and p.exists() else 0
                except OSError:
                    return 0

            total = sum(_seg_bytes(s) for s in remaining)
            while remaining and total > self._archive_max_bytes:
                victim = remaining.pop(0)
                total -= _seg_bytes(victim)
                to_prune.append(victim)

        return to_prune

    def _enforce_retention(self) -> None:
        """Prune whole sealed segments oldest-first to satisfy the ceiling.

        Each prune is recorded as a normal chained+signed audit record with
        ``decision=RETENTION_PRUNE`` and ``resource=<segment id>`` BEFORE the
        sealed file is removed, so a later ``verify(full=True)`` sees a
        documented, signed gap (policy) rather than an unexplained one (attack).

        The work is a bounded loop, NOT recursion: under ``_enforcing_retention``
        the prune meta-record's own append may rotate (adding a fresh sealed
        segment) but cannot re-enter retention, so it cannot recurse.  Overage is
        re-evaluated each iteration and the loop converges because every
        iteration removes the oldest segment.  An iteration cap (segment count +
        a small slack) is a belt-and-suspenders against pathological input.

        FAIL-SAFE: if writing the meta-record or unlinking a file fails, the
        method logs and stops — it never removes a sealed file whose prune it
        could not first audit, and never removes the active segment.
        """
        if self._enforcing_retention:
            return
        self._enforcing_retention = True
        try:
            max_iterations = len(self._segments) + 8
            for _ in range(max_iterations):
                overage = self._retention_overage()
                if not overage:
                    return
                victim = overage[0]
                segment_id = victim.filename
                try:
                    # Audit the prune FIRST (chained + signed).  This advances
                    # the chain head, so the documented gap is provably
                    # post-prune.  (May rotate; the guard blocks recursion.)
                    self.append(
                        adjudication_id=(
                            f"retention-prune-{victim.first_seq}-{victim.last_seq}"
                        ),
                        decision=RETENTION_PRUNE_DECISION,
                        car_hash="0" * 64,
                        source_agent="audit_log",
                        destination_service="audit_log",
                        verb="PRUNE",
                        resource=segment_id,
                        sensitivity="INTERNAL",
                        rule_engine_passed=True,
                        confidence=1.0,
                    )
                except AuditSinkError as exc:
                    logger.error(
                        "Retention prune ABORTED for %s — could not write the "
                        "audited prune meta-record (%s). Segment NOT removed.",
                        segment_id,
                        exc,
                    )
                    return
                # Now remove the sealed file + its index row.
                try:
                    seg_path = (
                        self._path.parent / segment_id if self._path else None
                    )
                    if seg_path is not None and seg_path.exists():
                        seg_path.unlink()
                    self._segments = [
                        s for s in self._segments if s.filename != segment_id
                    ]
                    self._rewrite_segment_index()
                    logger.info(
                        "Retention prune: removed sealed segment %s (seq %d..%d); "
                        "documented by a signed RETENTION_PRUNE record.",
                        segment_id,
                        victim.first_seq,
                        victim.last_seq,
                    )
                except OSError as exc:
                    logger.error(
                        "Retention prune: failed to remove %s (%s); the prune is "
                        "already audited, leaving the file in place.",
                        segment_id,
                        exc,
                    )
                    return
        finally:
            self._enforcing_retention = False

    def _rewrite_segment_index(self) -> None:
        """Rewrite ``audit-segments.jsonl`` from ``self._segments`` (post-prune).

        Used only after a retention prune removes a row.  Written to a temp file
        and atomically replaced so a crash mid-rewrite cannot truncate the index.
        Fail-safe: on failure the in-RAM list is authoritative for this process
        and the stale on-disk index is left (a superset — verify tolerates a
        pruned-but-still-listed row only if the file exists, else it is skipped).
        """
        if self._segment_index_path is None:
            return
        tmp = self._segment_index_path.with_suffix(".jsonl.tmp")
        try:
            with open(tmp, "wb") as fh:
                for seg in self._segments:
                    fh.write(
                        (json.dumps(seg.to_dict(), separators=(",", ":")) + "\n").encode(
                            "utf-8"
                        )
                    )
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp, self._segment_index_path)
            self._harden_path_dacl(self._segment_index_path)
        except OSError as exc:
            logger.error(
                "Failed to rewrite audit segment index %s (%s); in-memory state "
                "is authoritative for this process.",
                self._segment_index_path,
                exc,
            )
            try:
                if tmp.exists():
                    tmp.unlink()
            except OSError:
                pass

    # -- Sealed-segment reading (full verify / iteration) -------------------

    def _read_sealed_segment(self, entry: SegmentEntry) -> list[AuditRecord]:
        """Gunzip + parse one sealed segment's records (not retained in RAM)."""
        assert self._path is not None
        seg_path = self._path.parent / entry.filename
        records: list[AuditRecord] = []
        with gzip.open(seg_path, "rt", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                records.append(AuditRecord.from_dict(json.loads(line)))
        return records

    def iter_all_records(self) -> Iterator[AuditRecord]:
        """Yield every retained record in chain order (sealed segments + active).

        Streams sealed segments one at a time (gunzip on the fly) so total
        history can be walked without loading it all into RAM at once.  In
        in-memory mode this is just the active records.
        """
        with self._lock:
            segments = list(self._segments)
            active = list(self._records)
        if self._path is not None:
            for entry in segments:
                for rec in self._read_sealed_segment(entry):
                    yield rec
        for rec in active:
            yield rec

    @staticmethod
    def _verify_one_record(
        index: int,
        rec: AuditRecord,
        expected_prev: str,
        verifier: RecordSigner,
    ) -> str:
        """Verify one record's linkage + hash + signature; return its record_hash.

        Raises ``AuditChainError(index, reason)`` at the first break.  ``index``
        is the caller's chosen position label (global seq-ordinal for the
        cross-segment walk, so a tamper anywhere reports a sensible position).
        """
        if rec.prev_hash != expected_prev:
            raise AuditChainError(
                index,
                f"prev_hash mismatch: expected {expected_prev!r} got {rec.prev_hash!r}",
            )
        canon = _canonical_bytes(
            seq=rec.seq,
            adjudication_id=rec.adjudication_id,
            decision=rec.decision,
            car_hash=rec.car_hash,
            source_agent=rec.source_agent,
            destination_service=rec.destination_service,
            verb=rec.verb,
            resource=rec.resource,
            sensitivity=rec.sensitivity,
            rule_engine_passed=rec.rule_engine_passed,
            confidence=rec.confidence,
            timestamp_utc=rec.timestamp_utc,
            prev_hash=rec.prev_hash,
        )
        computed_hash = hashlib.sha256(canon).hexdigest()
        if computed_hash != rec.record_hash:
            raise AuditChainError(
                index,
                f"record_hash mismatch: computed {computed_hash!r} "
                f"stored {rec.record_hash!r}",
            )
        sig_bytes = bytes.fromhex(rec.signature)
        if not verifier.verify(canon, sig_bytes):
            raise AuditChainError(index, "signature verification failed")
        return rec.record_hash

    def _verify_segment_index(self, verifier: RecordSigner) -> str:
        """Verify the sealed-segment anchor chain; return the head to continue from.

        For each retained sealed segment (in order):
          * its ``segment_signature`` is authentic over the canonical summary
            (so a forged index row is caught), and
          * its ``file_sha256`` matches the on-disk ``.jsonl.gz`` (so a swapped
            or byte-edited sealed file is caught even without gunzipping), and
          * consecutive segments link: ``segment[k].first_prev_hash`` ==
            ``segment[k-1].last_record_hash``.

        The FIRST retained segment's ``first_prev_hash`` is NOT required to equal
        ``GENESIS_HASH`` — after a retention prune the oldest retained segment
        legitimately points at a pruned (deleted) record.  That documented gap
        is attested by the signed ``RETENTION_PRUNE`` record elsewhere in the
        chain; an *undocumented* break is still caught because the surviving
        anchors must still link to each other and to the active segment.

        Returns the ``last_record_hash`` of the final retained sealed segment
        (the value the active segment's first record must chain from), or
        ``GENESIS_HASH`` if there are no sealed segments.
        """
        assert self._path is not None
        expected_prev: str | None = None
        head = GENESIS_HASH
        for k, seg in enumerate(self._segments):
            seg_path = self._path.parent / seg.filename
            if not seg_path.exists():
                # Index lists a segment whose file is gone and which was NOT a
                # contiguous oldest cut — an undocumented deletion.  (A pruned
                # segment's row is removed from the index, so a present row with
                # no file is anomalous.)
                raise AuditChainError(
                    seg.first_seq,
                    f"sealed segment file missing: {seg.filename}",
                )
            # File digest must match the signed summary's pin.
            actual_sha = hashlib.sha256(seg_path.read_bytes()).hexdigest()
            if actual_sha != seg.file_sha256:
                raise AuditChainError(
                    seg.first_seq,
                    f"sealed segment {seg.filename} sha256 mismatch: "
                    f"computed {actual_sha!r} indexed {seg.file_sha256!r}",
                )
            # Signature over the canonical summary (binds the four hashes + sha).
            if not verifier.verify(seg.summary_bytes(), bytes.fromhex(seg.segment_signature)):
                raise AuditChainError(
                    seg.first_seq,
                    f"sealed segment {seg.filename} signature verification failed",
                )
            # Consecutive linkage (skip the check for the first retained segment).
            if expected_prev is not None and seg.first_prev_hash != expected_prev:
                raise AuditChainError(
                    seg.first_seq,
                    f"segment linkage broken at {seg.filename}: expected "
                    f"first_prev_hash {expected_prev!r} got {seg.first_prev_hash!r}",
                )
            expected_prev = seg.last_record_hash
            head = seg.last_record_hash
            _ = k
        return head

    def verify(
        self,
        *,
        signer: RecordSigner | None = None,
        full: bool = False,
    ) -> None:
        """Walk the chain and raise ``AuditChainError`` at the first break.

        Per record (active segment, and every sealed record when ``full``):
          1. Canonical bytes recompute to the stored ``record_hash``.
          2. The stored ``prev_hash`` matches the preceding record's
             ``record_hash`` (or ``GENESIS_HASH`` for the chain's first record).
          3. The ``signature`` is authentic for the canonical bytes.

        Default (``full=False``) — FAST:
            Verify the sealed-segment **anchor chain** (per-segment signature +
            on-disk ``.jsonl.gz`` SHA-256 + consecutive linkage) via the segment
            index, then verify the **active** segment's records end-to-end,
            continuing the chain from the last sealed segment's
            ``last_record_hash``.  Sealed records are NOT gunzipped/re-walked
            here — the signed index anchor stands in for them.

        Full (``full=True``) — EXHAUSTIVE:
            Additionally gunzip every sealed segment and walk EVERY record
            end-to-end across all segments + the active file.  A tampered byte
            inside a sealed ``.jsonl.gz`` is caught here (by the record-hash
            recompute) — and is independently caught by the anchor SHA check.

        A documented retention prune (signed ``RETENTION_PRUNE`` record + removed
        index row) leaves the surviving chain internally consistent, so both
        modes still pass with the documented gap.

        Args:
            signer: Signer for signature verification.  Defaults to the log's own
                signer.  Pass a different signer to verify against a rotation key.
            full: When True, walk every sealed segment record-by-record too.

        Raises:
            AuditChainError: First integrity break found (index + reason).
        """
        verifier = signer if signer is not None else self._signer
        with self._lock:
            active = list(self._records)
            has_segments = bool(self._segments)
        rotated = self._rotation_has_occurred()

        # In-memory mode, or an on-disk log that has NEVER rotated: a single
        # chain that MUST start at GENESIS (strict tamper-detection for the
        # unrotated case — a missing/swapped first record breaks at index 0).
        if self._path is None or (not has_segments and not rotated):
            expected_prev = GENESIS_HASH
            for i, rec in enumerate(active):
                expected_prev = self._verify_one_record(i, rec, expected_prev, verifier)
            return

        if not full:
            # Fast path: anchor chain (sealed) + active records end-to-end.
            # When all sealed segments were pruned (index file present, no rows),
            # the active tail legitimately starts mid-chain — seed from its own
            # first prev_hash (the documented-gap case); the record hash + sig
            # still fully bind it.  Otherwise continue from the last sealed head.
            if has_segments:
                expected_prev = self._verify_segment_index(verifier)
            else:
                # Rotated-then-fully-pruned: nothing sealed remains.
                expected_prev = active[0].prev_hash if active else GENESIS_HASH
            for i, rec in enumerate(active):
                expected_prev = self._verify_one_record(i, rec, expected_prev, verifier)
            return

        # Full path: still validate the anchor chain (catches a swapped/edited
        # sealed file via the SHA pin and a forged index row via the signature),
        # AND walk every sealed record + the active file end-to-end.
        self._verify_segment_index(verifier)
        with self._lock:
            segments = list(self._segments)

        # GENESIS is the strict expected start UNLESS this log has rotated (sealed
        # history may have been pruned, so the first retained record can point at
        # a deleted predecessor — the documented gap).  When rotated, we seed from
        # the first retained record's own prev_hash; the record hash + signature
        # still bind it, so a tamper to prev_hash is still caught by the recompute.
        ordinal = 0
        first = True
        seed_from_record = rotated
        expected_prev = GENESIS_HASH

        def _walk(rec: AuditRecord) -> None:
            nonlocal ordinal, first, expected_prev
            if first and seed_from_record:
                expected_prev = rec.prev_hash
            first = False
            expected_prev = self._verify_one_record(ordinal, rec, expected_prev, verifier)
            ordinal += 1

        for seg in segments:
            for rec in self._read_sealed_segment(seg):
                _walk(rec)
        for rec in active:
            _walk(rec)

    @classmethod
    def in_memory(cls, signer: RecordSigner) -> "AuditLog":
        """Convenience factory: create an in-memory log with no disk I/O."""
        return cls(path=None, signer=signer)

    @classmethod
    def from_path(
        cls,
        path: Path | str,
        signer: RecordSigner,
        *,
        on_rotate: Callable[[Path], None] | None = None,
        max_active_bytes: int = DEFAULT_MAX_ACTIVE_BYTES,
        max_active_records: int = DEFAULT_MAX_ACTIVE_RECORDS,
        archive_max_bytes: int | None = None,
        archive_max_age_days: int | None = None,
    ) -> "AuditLog":
        """Convenience factory: create or reopen a file-backed log.

        Rotation/retention knobs default to the ADR-029 policy (64 MiB / 100k
        active cap; keep-everything archive ceiling).  Pass overrides to tune the
        active-file bound or to enable a (default-off) retention ceiling.
        """
        return cls(
            path=Path(path),
            signer=signer,
            on_rotate=on_rotate,
            max_active_bytes=max_active_bytes,
            max_active_records=max_active_records,
            archive_max_bytes=archive_max_bytes,
            archive_max_age_days=archive_max_age_days,
        )
