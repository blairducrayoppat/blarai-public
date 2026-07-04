"""Tests for shared.security.audit_log — tamper-evident adjudication audit stream.

Sprint 13, Tier-1 security hardening (Vikunja #602 / Domain 7).

Layer-A tests with teeth — all six mandated coverage areas:
  A. Clean chain verifies end-to-end.
  B. Tampered field in a middle record is DETECTED.
  C. Removed record is DETECTED.
  D. Reordered records are DETECTED.
  E. ALLOW and DENY decisions BOTH persist (driven through HybridAdjudicator).
  F. Sink-write error is fail-closed / explicit.
  G. Signature verification fails on a forged record.
  H. In-memory mode: chain verification works without disk.
  I. File-backed mode: chain persists and reloads across AuditLog instances.
  J. Genesis constant and chain linkage details.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from shared.security.audit_log import (
    GENESIS_HASH,
    RETENTION_PRUNE_DECISION,
    SEGMENT_INDEX_NAME,
    AuditChainError,
    AuditLog,
    AuditRecord,
    AuditSinkError,
    HmacSha256Signer,
    RecordSigner,
    SegmentEntry,
    _canonical_bytes,
)
from shared.schemas.car import (
    ActionVerb,
    AdjudicationDecision,
    Sensitivity,
)
from services.policy_agent.src.adjudicator import HybridAdjudicator
from services.policy_agent.src.car import build_car
from services.policy_agent.src.gpu_inference import (
    GPUClassificationResult,
    PolicyGPUInference,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_KEY = b"test-audit-hmac-key-32bytes!!!!!"


def _signer(key: bytes = _KEY, key_id: str = "test") -> HmacSha256Signer:
    return HmacSha256Signer(key=key, key_id=key_id)


def _in_memory_log(key: bytes = _KEY) -> AuditLog:
    return AuditLog.in_memory(signer=_signer(key))


_FIXED_TS = "2026-06-05T12:00:00+00:00"

_BASE_RECORD_KWARGS: dict[str, Any] = dict(
    adjudication_id="test-uuid-001",
    decision="ALLOW",
    car_hash="a" * 64,
    source_agent="assistant_orchestrator",
    destination_service="substrate",
    verb="READ",
    resource="substrate.vector_store",
    sensitivity="INTERNAL",
    rule_engine_passed=True,
    confidence=0.90,
    timestamp_utc=_FIXED_TS,
)


def _append_record(log: AuditLog, *, override: dict[str, Any] | None = None) -> AuditRecord:
    kwargs = {**_BASE_RECORD_KWARGS, **(override or {})}
    return log.append(**kwargs)


def _make_car(
    source: str = "assistant_orchestrator",
    dest: str = "substrate",
    sensitivity: Sensitivity = Sensitivity.INTERNAL,
) -> Any:
    return build_car(
        source_agent=source,
        destination_service=dest,
        verb=ActionVerb.READ,
        resource="substrate.vector_store",
        sensitivity=sensitivity,
        session_id="sess-audit-test",
    )


def _make_gpu_stub(
    label: str = "ALLOW",
    confidence: float = 0.90,
    error: str | None = None,
    loaded: bool = True,
) -> PolicyGPUInference:
    npu = PolicyGPUInference("dummy_dir")
    if loaded:
        npu.classify_car = MagicMock(  # type: ignore[assignment]
            return_value=GPUClassificationResult(
                label=label,
                confidence=confidence,
                latency_ms=1.0,
                error=error,
            )
        )
        npu._loaded = True  # type: ignore[attr-defined]
    return npu


ACL = {
    "assistant_orchestrator": ["substrate", "semantic_router", "code_agent"],
    "code_agent": ["substrate"],
    "semantic_router": [],
}


def _make_adjudicator(
    audit_log: AuditLog | None = None,
    npu: PolicyGPUInference | None = None,
) -> HybridAdjudicator:
    return HybridAdjudicator(
        npu_inference=npu or _make_gpu_stub(),
        acl_matrix=ACL,
        audit_log=audit_log,
    )


# ---------------------------------------------------------------------------
# Group A: Clean chain verifies end-to-end
# ---------------------------------------------------------------------------


class TestCleanChainVerifies:
    def test_empty_log_verifies(self) -> None:
        log = _in_memory_log()
        log.verify()  # must not raise

    def test_single_record_verifies(self) -> None:
        log = _in_memory_log()
        _append_record(log)
        log.verify()

    def test_three_records_verify(self) -> None:
        log = _in_memory_log()
        _append_record(log, override={"adjudication_id": "id-1"})
        _append_record(log, override={"adjudication_id": "id-2", "decision": "DENY"})
        _append_record(log, override={"adjudication_id": "id-3", "decision": "ALLOW"})
        log.verify()
        assert log.record_count == 3

    def test_chain_links_correctly(self) -> None:
        log = _in_memory_log()
        r0 = _append_record(log, override={"adjudication_id": "id-0"})
        r1 = _append_record(log, override={"adjudication_id": "id-1"})
        r2 = _append_record(log, override={"adjudication_id": "id-2"})

        assert r0.prev_hash == GENESIS_HASH
        assert r1.prev_hash == r0.record_hash
        assert r2.prev_hash == r1.record_hash

    def test_seq_increments(self) -> None:
        log = _in_memory_log()
        r0 = _append_record(log)
        r1 = _append_record(log)
        r2 = _append_record(log)
        assert r0.seq == 0
        assert r1.seq == 1
        assert r2.seq == 2


# ---------------------------------------------------------------------------
# Group B: Tampered field in a middle record is DETECTED
# ---------------------------------------------------------------------------


class TestTamperedFieldDetected:
    def _log_with_three_records(self) -> AuditLog:
        log = _in_memory_log()
        _append_record(log, override={"adjudication_id": "id-0", "decision": "ALLOW"})
        _append_record(log, override={"adjudication_id": "id-1", "decision": "DENY"})
        _append_record(log, override={"adjudication_id": "id-2", "decision": "ALLOW"})
        return log

    def _tamper(self, log: AuditLog, index: int, field: str, value: Any) -> None:
        """Directly mutate an AuditRecord field to simulate tampering."""
        object.__setattr__(log._records[index], field, value)

    def test_tampered_decision_in_middle_detected(self) -> None:
        log = self._log_with_three_records()
        # Flip DENY→ALLOW in record 1 (the middle record).
        self._tamper(log, 1, "decision", "ALLOW")
        with pytest.raises(AuditChainError) as exc_info:
            log.verify()
        assert exc_info.value.index == 1
        assert "record_hash" in exc_info.value.reason

    def test_tampered_confidence_detected(self) -> None:
        log = self._log_with_three_records()
        self._tamper(log, 1, "confidence", 0.0)
        with pytest.raises(AuditChainError) as exc_info:
            log.verify()
        assert exc_info.value.index == 1

    def test_tampered_source_agent_detected(self) -> None:
        log = self._log_with_three_records()
        self._tamper(log, 0, "source_agent", "malicious_agent")
        with pytest.raises(AuditChainError) as exc_info:
            log.verify()
        assert exc_info.value.index == 0

    def test_tampered_first_record_breaks_chain_downstream(self) -> None:
        """Tamper record 0 → records 1 and 2 also fail (prev_hash mismatch)."""
        log = self._log_with_three_records()
        self._tamper(log, 0, "decision", "ALLOW_FORGED")
        # Should break at index 0 (first hash mismatch)
        with pytest.raises(AuditChainError) as exc_info:
            log.verify()
        # The first break is at record 0 (hash recompute fails)
        assert exc_info.value.index == 0


# ---------------------------------------------------------------------------
# Group C: Removed record is DETECTED
# ---------------------------------------------------------------------------


class TestRemovedRecordDetected:
    def test_remove_first_record_detected(self) -> None:
        log = _in_memory_log()
        _append_record(log, override={"adjudication_id": "id-0"})
        _append_record(log, override={"adjudication_id": "id-1"})
        _append_record(log, override={"adjudication_id": "id-2"})
        # Remove record 0 — record 1's prev_hash will not match GENESIS_HASH.
        log._records.pop(0)
        with pytest.raises(AuditChainError) as exc_info:
            log.verify()
        assert exc_info.value.index == 0
        assert "prev_hash" in exc_info.value.reason

    def test_remove_middle_record_detected(self) -> None:
        log = _in_memory_log()
        _append_record(log, override={"adjudication_id": "id-0"})
        _append_record(log, override={"adjudication_id": "id-1"})
        _append_record(log, override={"adjudication_id": "id-2"})
        # Remove record 1 — record 2's prev_hash won't match record 0's hash.
        log._records.pop(1)
        with pytest.raises(AuditChainError) as exc_info:
            log.verify()
        assert exc_info.value.index == 1

    def test_remove_last_record_does_not_affect_remaining_chain(self) -> None:
        """Removing the tail is undetectable by hash-chain alone (by design) —
        the chain only detects internal mutations.  Verify reports no break."""
        log = _in_memory_log()
        _append_record(log, override={"adjudication_id": "id-0"})
        _append_record(log, override={"adjudication_id": "id-1"})
        _append_record(log, override={"adjudication_id": "id-2"})
        log._records.pop(2)
        # The remaining 2-record chain is internally consistent.
        log.verify()


# ---------------------------------------------------------------------------
# Group D: Reordered records are DETECTED
# ---------------------------------------------------------------------------


class TestReorderedRecordsDetected:
    def test_swap_first_two_detected(self) -> None:
        log = _in_memory_log()
        _append_record(log, override={"adjudication_id": "id-0"})
        _append_record(log, override={"adjudication_id": "id-1"})
        _append_record(log, override={"adjudication_id": "id-2"})
        # Swap records 0 and 1.
        log._records[0], log._records[1] = log._records[1], log._records[0]
        with pytest.raises(AuditChainError) as exc_info:
            log.verify()
        # Record 0 (now the original record 1) has wrong prev_hash vs GENESIS.
        assert exc_info.value.index == 0
        assert "prev_hash" in exc_info.value.reason

    def test_swap_middle_records_detected(self) -> None:
        log = _in_memory_log()
        for i in range(4):
            _append_record(log, override={"adjudication_id": f"id-{i}"})
        log._records[1], log._records[2] = log._records[2], log._records[1]
        with pytest.raises(AuditChainError):
            log.verify()


# ---------------------------------------------------------------------------
# Group E: ALLOW and DENY decisions BOTH persist (via HybridAdjudicator)
# ---------------------------------------------------------------------------


class TestAllowAndDenyBothPersist:
    def test_allow_decision_persists(self) -> None:
        log = _in_memory_log()
        npu = _make_gpu_stub(label="ALLOW", confidence=0.92)
        adj = _make_adjudicator(audit_log=log, npu=npu)
        car = _make_car()

        ctx = adj.adjudicate_car(car)

        assert ctx.decision == AdjudicationDecision.ALLOW
        assert log.record_count == 1
        rec = log.records[0]
        assert rec.decision == "ALLOW"
        assert rec.adjudication_id == ctx.adjudication_id

    def test_deny_decision_persists(self) -> None:
        log = _in_memory_log()
        # Rule-engine DENY (UNCLASSIFIED sensitivity) — no NPU needed.
        adj = _make_adjudicator(audit_log=log)
        car = _make_car(sensitivity=Sensitivity.UNCLASSIFIED)

        ctx = adj.adjudicate_car(car)

        assert ctx.decision == AdjudicationDecision.DENY
        assert log.record_count == 1
        rec = log.records[0]
        assert rec.decision == "DENY"
        assert rec.adjudication_id == ctx.adjudication_id

    def test_allow_and_deny_both_persist_in_sequence(self) -> None:
        log = _in_memory_log()
        npu_allow = _make_gpu_stub(label="ALLOW", confidence=0.92)
        adj = _make_adjudicator(audit_log=log, npu=npu_allow)

        allow_car = _make_car()
        deny_car = _make_car(sensitivity=Sensitivity.UNCLASSIFIED)

        ctx_allow = adj.adjudicate_car(allow_car)
        ctx_deny = adj.adjudicate_car(deny_car)

        assert log.record_count == 2
        assert log.records[0].decision == "ALLOW"
        assert log.records[1].decision == "DENY"
        assert log.records[0].adjudication_id == ctx_allow.adjudication_id
        assert log.records[1].adjudication_id == ctx_deny.adjudication_id
        # Chain must still verify
        log.verify()

    def test_car_fields_captured_correctly(self) -> None:
        log = _in_memory_log()
        npu = _make_gpu_stub(label="ALLOW", confidence=0.90)
        adj = _make_adjudicator(audit_log=log, npu=npu)
        car = _make_car(
            source="assistant_orchestrator",
            dest="substrate",
            sensitivity=Sensitivity.INTERNAL,
        )

        adj.adjudicate_car(car)

        rec = log.records[0]
        assert rec.source_agent == "assistant_orchestrator"
        assert rec.destination_service == "substrate"
        assert rec.sensitivity == "INTERNAL"
        assert rec.verb == "READ"
        assert rec.rule_engine_passed is True

    def test_no_log_wired_does_not_error(self) -> None:
        """Adjudicator without audit_log still works (optional)."""
        adj = _make_adjudicator(audit_log=None)
        car = _make_car(sensitivity=Sensitivity.UNCLASSIFIED)
        ctx = adj.adjudicate_car(car)
        assert ctx.decision == AdjudicationDecision.DENY

    def test_has_audit_log_property(self) -> None:
        log = _in_memory_log()
        adj_with = _make_adjudicator(audit_log=log)
        adj_without = _make_adjudicator(audit_log=None)
        assert adj_with.has_audit_log is True
        assert adj_without.has_audit_log is False

    def test_integrity_short_circuit_deny_persists(self) -> None:
        """The integrity-failure DENY (second short-circuit path) also persists."""
        import os
        import json as _json

        # Create a mismatched manifest to trigger integrity failure.
        import tempfile as _tmp
        fd, bin_path = _tmp.mkstemp(suffix=".bin")
        with os.fdopen(fd, "wb") as f:
            f.write(b"model-weight-data")
        fd, manifest_path = _tmp.mkstemp(suffix=".json")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            _json.dump({"version": "1.0.0", "digests": {Path(bin_path).name: "0" * 64}}, f)
        try:
            log = _in_memory_log()
            npu = PolicyGPUInference("dummy_dir")
            npu._loaded = True  # type: ignore[attr-defined]
            adj = HybridAdjudicator(
                npu_inference=npu,
                acl_matrix=ACL,
                manifest_path=manifest_path,
                model_bin_path=bin_path,
                audit_log=log,
            )
            car = _make_car()
            ctx = adj.adjudicate_car(car)
            assert ctx.decision == AdjudicationDecision.DENY
            assert log.record_count == 1
            assert log.records[0].decision == "DENY"
        finally:
            os.unlink(bin_path)
            os.unlink(manifest_path)


# ---------------------------------------------------------------------------
# Group F: Sink-write error is fail-closed / explicit
# ---------------------------------------------------------------------------


class TestSinkWriteFailClosedExplicit:
    def test_unwritable_path_raises_audit_sink_error(self) -> None:
        """Writing to a path that fails raises AuditSinkError — never silent.

        We simulate an unwritable sink by monkey-patching open() in the
        audit_log module so the write path raises OSError, then assert that
        AuditSinkError (not a raw OSError) propagates to the caller.
        """
        import builtins
        import shared.security.audit_log as _al

        log = AuditLog.in_memory(signer=_signer())
        # Patch the log path to a non-None value so _write_record attempts I/O.
        log._path = Path("/fake/path/audit.jsonl")  # type: ignore[attr-defined]

        original_open = builtins.open

        def _fail_open(*args, **kwargs):
            if "fake" in str(args[0]):
                raise OSError("simulated disk full")
            return original_open(*args, **kwargs)

        with patch("builtins.open", side_effect=_fail_open):
            with pytest.raises(AuditSinkError, match="Audit-log write failed"):
                _append_record(log)

    def test_sink_error_propagates_from_adjudicator(self) -> None:
        """AuditSinkError from the log propagates through adjudicate_car."""
        log = _in_memory_log()
        # Monkey-patch append to raise AuditSinkError.
        log.append = MagicMock(side_effect=AuditSinkError("simulated disk full"))  # type: ignore[method-assign]

        adj = _make_adjudicator(audit_log=log)
        car = _make_car(sensitivity=Sensitivity.UNCLASSIFIED)

        with pytest.raises(AuditSinkError):
            adj.adjudicate_car(car)

    def test_sink_error_does_not_silently_allow(self) -> None:
        """A sink write failure must not silently produce an ALLOW result."""
        log = _in_memory_log()
        log.append = MagicMock(side_effect=AuditSinkError("disk error"))  # type: ignore[method-assign]

        npu = _make_gpu_stub(label="ALLOW", confidence=0.99)
        adj = _make_adjudicator(audit_log=log, npu=npu)
        car = _make_car()

        # The adjudicator must raise, not return an ALLOW context silently.
        with pytest.raises(AuditSinkError):
            adj.adjudicate_car(car)


# ---------------------------------------------------------------------------
# Group G: Signature verification fails on a forged record
# ---------------------------------------------------------------------------


class TestSignatureVerificationFails:
    def test_forged_signature_detected(self) -> None:
        log = _in_memory_log()
        _append_record(log)
        _append_record(log, override={"adjudication_id": "id-1"})
        # Forge signature on record 1 (replace hex signature with all-zeros).
        sig_len = len(log._records[1].signature)
        object.__setattr__(log._records[1], "signature", "0" * sig_len)
        with pytest.raises(AuditChainError) as exc_info:
            log.verify()
        assert exc_info.value.index == 1
        assert "signature" in exc_info.value.reason

    def test_wrong_key_fails_verification(self) -> None:
        """Verifying with a different key should detect all records as forged."""
        log = AuditLog.in_memory(signer=_signer(b"original-key-1234567890123456"))
        _append_record(log)
        _append_record(log, override={"adjudication_id": "id-1"})

        wrong_signer = _signer(b"different-key-9876543210987654")
        with pytest.raises(AuditChainError) as exc_info:
            log.verify(signer=wrong_signer)
        # First record should fail immediately.
        assert exc_info.value.index == 0
        assert "signature" in exc_info.value.reason

    def test_signer_id_stored_in_record(self) -> None:
        signer = HmacSha256Signer(key=b"mykey123", key_id="prod-key-2026")
        log = AuditLog.in_memory(signer=signer)
        rec = _append_record(log)
        assert "prod-key-2026" in rec.signer_id
        assert "HMAC-SHA256" in rec.signer_id


# ---------------------------------------------------------------------------
# Group H: In-memory mode
# ---------------------------------------------------------------------------


class TestInMemoryMode:
    def test_in_memory_no_disk_io(self) -> None:
        log = AuditLog.in_memory(signer=_signer())
        _append_record(log)
        _append_record(log, override={"adjudication_id": "id-1"})
        assert log.record_count == 2
        log.verify()

    def test_in_memory_record_count(self) -> None:
        log = AuditLog.in_memory(signer=_signer())
        assert log.record_count == 0
        _append_record(log)
        assert log.record_count == 1


# ---------------------------------------------------------------------------
# Group I: File-backed mode — persistence and reload
# ---------------------------------------------------------------------------


class TestFileBacked:
    def test_file_backed_write_and_reload(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "audit.jsonl"
            signer = _signer()

            # Write two records.
            log1 = AuditLog.from_path(path, signer)
            r0 = _append_record(log1, override={"adjudication_id": "id-0"})
            r1 = _append_record(log1, override={"adjudication_id": "id-1"})

            # Reload from disk.
            log2 = AuditLog.from_path(path, signer)
            assert log2.record_count == 2
            assert log2.records[0].adjudication_id == "id-0"
            assert log2.records[1].adjudication_id == "id-1"
            assert log2.records[0].record_hash == r0.record_hash
            assert log2.records[1].record_hash == r1.record_hash

            # Append a third record and verify.
            _append_record(log2, override={"adjudication_id": "id-2"})
            log2.verify()

    def test_file_backed_chain_continuity_across_reload(self) -> None:
        """The chain prev_hash links correctly even after a reload."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "audit.jsonl"
            signer = _signer()

            log1 = AuditLog.from_path(path, signer)
            r0 = _append_record(log1, override={"adjudication_id": "id-0"})

            log2 = AuditLog.from_path(path, signer)
            r1 = _append_record(log2, override={"adjudication_id": "id-1"})

            # r1.prev_hash must equal r0.record_hash (chain continuity)
            assert r1.prev_hash == r0.record_hash
            log2.verify()

    def test_file_backed_tamper_on_disk_detected(self) -> None:
        """Directly modifying the JSONL file on disk is detected on next load."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "audit.jsonl"
            signer = _signer()

            log1 = AuditLog.from_path(path, signer)
            _append_record(log1, override={"adjudication_id": "id-0"})
            _append_record(log1, override={"adjudication_id": "id-1"})

            # Read lines and tamper the first record's decision field.
            lines = path.read_text(encoding="utf-8").splitlines()
            first = json.loads(lines[0])
            first["decision"] = "ALLOW_FORGED"
            lines[0] = json.dumps(first)
            path.write_text("\n".join(lines) + "\n", encoding="utf-8")

            # Reloading and verifying must detect the tamper.
            log2 = AuditLog.from_path(path, signer)
            with pytest.raises(AuditChainError) as exc_info:
                log2.verify()
            assert exc_info.value.index == 0


# ---------------------------------------------------------------------------
# Group J: Genesis constant and hash-chain formula details
# ---------------------------------------------------------------------------


class TestHashChainDetails:
    def test_genesis_hash_is_deterministic(self) -> None:
        import hashlib
        expected = hashlib.sha256(b"BlarAI-audit-log-genesis-v1").hexdigest()
        assert GENESIS_HASH == expected

    def test_record_hash_covers_prev_hash(self) -> None:
        """Changing prev_hash changes record_hash (the chain property)."""
        import hashlib as _hl

        canon_a = _canonical_bytes(
            seq=0, adjudication_id="id", decision="ALLOW", car_hash="a" * 64,
            source_agent="src", destination_service="dst", verb="READ",
            resource="res", sensitivity="INTERNAL", rule_engine_passed=True,
            confidence=0.9, timestamp_utc=_FIXED_TS, prev_hash=GENESIS_HASH,
        )
        canon_b = _canonical_bytes(
            seq=0, adjudication_id="id", decision="ALLOW", car_hash="a" * 64,
            source_agent="src", destination_service="dst", verb="READ",
            resource="res", sensitivity="INTERNAL", rule_engine_passed=True,
            confidence=0.9, timestamp_utc=_FIXED_TS, prev_hash="0" * 64,
        )
        assert _hl.sha256(canon_a).hexdigest() != _hl.sha256(canon_b).hexdigest()

    def test_hmac_empty_key_raises(self) -> None:
        with pytest.raises(ValueError, match="non-empty"):
            HmacSha256Signer(key=b"")

    def test_record_signer_is_abstract(self) -> None:
        """RecordSigner cannot be instantiated directly."""
        with pytest.raises(TypeError):
            RecordSigner()  # type: ignore[abstract]

    def test_audit_chain_error_carries_index_and_reason(self) -> None:
        exc = AuditChainError(index=3, reason="hash mismatch")
        assert exc.index == 3
        assert exc.reason == "hash mismatch"
        assert "3" in str(exc)

    def test_deterministic_hash_with_injected_timestamp(self) -> None:
        """Two appends with identical injected timestamps produce identical record_hashes
        only if all other fields are also identical (seq differs → hashes differ)."""
        log = _in_memory_log()
        r0 = log.append(**{**_BASE_RECORD_KWARGS, "timestamp_utc": _FIXED_TS})
        r1 = log.append(**{**_BASE_RECORD_KWARGS, "timestamp_utc": _FIXED_TS})
        # seq differs (0 vs 1) so hashes must differ.
        assert r0.record_hash != r1.record_hash


# ===========================================================================
# Segmented retention + bounded RAM (ISS-607 / ADR-029)
# ===========================================================================
#
# Coverage:
#   K. Rotation triggers exactly at the record-count AND the byte threshold.
#   L. Chain continuity across a rotation seam (verify + verify(full=True)).
#   M. A tampered byte in a sealed .jsonl.gz is caught by verify(full=True)
#      (and independently by the fast verify's SHA anchor).
#   N. Bounded RAM: after a rotation, len(log.records) reflects only the
#      active segment, not the whole history; reload loads only the active.
#   O. RETENTION_PRUNE flow writes the signed meta-record and verify(full=True)
#      still passes with the documented gap.
#   P. Fail-safe: a simulated rotation error keeps appending and loses no record.

import gzip as _gzip  # noqa: E402 — grouped with the segmentation tests


def _file_log(
    path: Path,
    *,
    max_active_records: int = 0,
    max_active_bytes: int = 0,
    archive_max_bytes: int | None = None,
    archive_max_age_days: int | None = None,
    key: bytes = _KEY,
) -> AuditLog:
    return AuditLog.from_path(
        path,
        _signer(key),
        max_active_records=max_active_records,
        max_active_bytes=max_active_bytes,
        archive_max_bytes=archive_max_bytes,
        archive_max_age_days=archive_max_age_days,
    )


def _sealed_segments(path: Path) -> list[Path]:
    return sorted(path.parent.glob("audit-*.jsonl.gz"))


# ---------------------------------------------------------------------------
# Group K: Rotation trigger thresholds (count AND bytes)
# ---------------------------------------------------------------------------


class TestRotationTriggers:
    def test_rotation_triggers_exactly_at_record_threshold(self, tmp_path: Path) -> None:
        path = tmp_path / "audit.jsonl"
        # Cap at 3 records, byte trip disabled.
        log = _file_log(path, max_active_records=3, max_active_bytes=0)

        # Two records: no rotation yet.
        _append_record(log, override={"adjudication_id": "id-0"})
        _append_record(log, override={"adjudication_id": "id-1"})
        assert log.segment_count == 0
        assert log.record_count == 2
        assert _sealed_segments(path) == []

        # Third record hits the cap (len >= 3) → rotates; active resets to empty.
        _append_record(log, override={"adjudication_id": "id-2"})
        assert log.segment_count == 1
        assert log.record_count == 0
        assert len(_sealed_segments(path)) == 1

        # Fourth lands in the fresh active segment.
        _append_record(log, override={"adjudication_id": "id-3"})
        assert log.record_count == 1
        assert log.segment_count == 1

    def test_rotation_triggers_at_byte_threshold(self, tmp_path: Path) -> None:
        path = tmp_path / "audit.jsonl"
        # First measure one record's on-disk line size with no rotation.
        probe = _file_log(tmp_path / "probe.jsonl", max_active_records=0, max_active_bytes=0)
        _append_record(probe, override={"adjudication_id": "id-probe"})
        line_bytes = (tmp_path / "probe.jsonl").stat().st_size
        assert line_bytes > 0

        # Cap bytes so that the 3rd record crosses it (>= 2.5 lines), count off.
        cap = int(line_bytes * 2.5)
        log = _file_log(path, max_active_records=0, max_active_bytes=cap)

        _append_record(log, override={"adjudication_id": "b-0"})
        _append_record(log, override={"adjudication_id": "b-1"})
        # After 2 lines, active bytes (2 * line) < cap (2.5 * line) → no rotation.
        assert log.segment_count == 0

        _append_record(log, override={"adjudication_id": "b-2"})
        # 3 lines (3 * line) >= cap (2.5 * line) → rotation.
        assert log.segment_count == 1
        assert log.record_count == 0

    def test_caps_of_zero_never_rotate(self, tmp_path: Path) -> None:
        path = tmp_path / "audit.jsonl"
        log = _file_log(path, max_active_records=0, max_active_bytes=0)
        for i in range(50):
            _append_record(log, override={"adjudication_id": f"id-{i}"})
        assert log.segment_count == 0
        assert log.record_count == 50
        log.verify()
        log.verify(full=True)

    def test_empty_active_does_not_rotate(self, tmp_path: Path) -> None:
        """A cap of 1 must not rotate an empty active file into an empty segment."""
        path = tmp_path / "audit.jsonl"
        log = _file_log(path, max_active_records=1, max_active_bytes=0)
        # First append rotates immediately (len >= 1) → 1 sealed, 0 active.
        _append_record(log, override={"adjudication_id": "id-0"})
        assert log.segment_count == 1
        assert log.record_count == 0
        # No second empty segment is produced without another append.
        assert len(_sealed_segments(path)) == 1


# ---------------------------------------------------------------------------
# Group L: Chain continuity across a rotation seam
# ---------------------------------------------------------------------------


class TestChainContinuityAcrossSeam:
    def test_prev_hash_links_across_rotation_seam(self, tmp_path: Path) -> None:
        path = tmp_path / "audit.jsonl"
        log = _file_log(path, max_active_records=2, max_active_bytes=0)

        r0 = _append_record(log, override={"adjudication_id": "id-0"})
        r1 = _append_record(log, override={"adjudication_id": "id-1"})  # rotates here
        assert log.segment_count == 1
        # The next record's prev_hash MUST equal the sealed segment's last hash.
        r2 = _append_record(log, override={"adjudication_id": "id-2"})
        assert r1.prev_hash == r0.record_hash
        assert r2.prev_hash == r1.record_hash  # spans the file boundary

    def test_verify_and_full_verify_pass_across_seam(self, tmp_path: Path) -> None:
        path = tmp_path / "audit.jsonl"
        log = _file_log(path, max_active_records=3, max_active_bytes=0)
        for i in range(10):  # 3 sealed segments (3+3+3) + 1 active
            _append_record(log, override={"adjudication_id": f"id-{i}"})
        assert log.segment_count == 3
        assert log.record_count == 1
        log.verify()           # fast: anchor chain + active
        log.verify(full=True)  # exhaustive: every sealed record + active

    def test_segment_index_file_written(self, tmp_path: Path) -> None:
        path = tmp_path / "audit.jsonl"
        log = _file_log(path, max_active_records=2, max_active_bytes=0)
        for i in range(4):
            _append_record(log, override={"adjudication_id": f"id-{i}"})
        index = path.parent / SEGMENT_INDEX_NAME
        assert index.exists()
        rows = [
            SegmentEntry.from_dict(json.loads(ln))
            for ln in index.read_text(encoding="utf-8").splitlines()
            if ln.strip()
        ]
        assert len(rows) == log.segment_count
        # Consecutive segments link: each first_prev_hash == prior last_record_hash.
        for prev, cur in zip(rows, rows[1:]):
            assert cur.first_prev_hash == prev.last_record_hash

    def test_total_record_count_spans_segments(self, tmp_path: Path) -> None:
        path = tmp_path / "audit.jsonl"
        log = _file_log(path, max_active_records=2, max_active_bytes=0)
        for i in range(7):
            _append_record(log, override={"adjudication_id": f"id-{i}"})
        # record_count is active-only (bounded); total spans sealed + active.
        assert log.record_count < 7
        assert log.total_record_count == 7

    def test_iter_all_records_yields_full_history_in_order(self, tmp_path: Path) -> None:
        path = tmp_path / "audit.jsonl"
        log = _file_log(path, max_active_records=2, max_active_bytes=0)
        for i in range(7):
            _append_record(log, override={"adjudication_id": f"id-{i}"})
        seqs = [r.seq for r in log.iter_all_records()]
        assert seqs == list(range(7))


# ---------------------------------------------------------------------------
# Group M: Tamper inside a sealed .jsonl.gz is detected
# ---------------------------------------------------------------------------


class TestSealedSegmentTamperDetected:
    def _tamper_first_sealed_record(self, path: Path) -> None:
        """Decompress the oldest sealed segment, flip a field, recompress."""
        sealed = _sealed_segments(path)[0]
        lines = _gzip.open(sealed, "rt", encoding="utf-8").read().splitlines()
        rec = json.loads(lines[0])
        rec["decision"] = "DENY_FORGED"
        lines[0] = json.dumps(rec, separators=(",", ":"))
        with _gzip.open(sealed, "wt", encoding="utf-8") as fh:
            fh.write("\n".join(lines) + "\n")

    def test_full_verify_catches_sealed_tamper(self, tmp_path: Path) -> None:
        path = tmp_path / "audit.jsonl"
        log = _file_log(path, max_active_records=2, max_active_bytes=0)
        for i in range(5):
            _append_record(log, override={"adjudication_id": f"id-{i}"})
        self._tamper_first_sealed_record(path)
        with pytest.raises(AuditChainError):
            log.verify(full=True)

    def test_fast_verify_catches_sealed_tamper_via_sha_anchor(self, tmp_path: Path) -> None:
        """The fast verify pins each sealed file's SHA-256 in the signed index,
        so a sealed-file edit is caught WITHOUT gunzipping/re-walking records."""
        path = tmp_path / "audit.jsonl"
        log = _file_log(path, max_active_records=2, max_active_bytes=0)
        for i in range(5):
            _append_record(log, override={"adjudication_id": f"id-{i}"})
        self._tamper_first_sealed_record(path)
        # Reload so the in-RAM index SHA is re-read from the (now-tampered) disk.
        log2 = _file_log(path, max_active_records=2, max_active_bytes=0)
        with pytest.raises(AuditChainError) as exc:
            log2.verify()  # fast path
        assert "sha256" in exc.value.reason or "signature" in exc.value.reason

    def test_deleted_sealed_segment_file_detected(self, tmp_path: Path) -> None:
        """An index row whose .jsonl.gz file was deleted (NOT a documented prune)
        is an undocumented gap — verify must raise."""
        path = tmp_path / "audit.jsonl"
        log = _file_log(path, max_active_records=2, max_active_bytes=0)
        for i in range(5):
            _append_record(log, override={"adjudication_id": f"id-{i}"})
        _sealed_segments(path)[0].unlink()
        log2 = _file_log(path, max_active_records=2, max_active_bytes=0)
        with pytest.raises(AuditChainError) as exc:
            log2.verify()
        assert "missing" in exc.value.reason


# ---------------------------------------------------------------------------
# Group N: Bounded RAM
# ---------------------------------------------------------------------------


class TestBoundedRAM:
    def test_records_reflect_only_active_segment_after_rotation(self, tmp_path: Path) -> None:
        path = tmp_path / "audit.jsonl"
        log = _file_log(path, max_active_records=3, max_active_bytes=0)
        for i in range(7):  # 2 sealed (3+3) + 1 active
            _append_record(log, override={"adjudication_id": f"id-{i}"})
        # The bound: in-RAM records are ONLY the active segment, not all history.
        assert len(log.records) == 1
        assert log.record_count == 1
        assert log.segment_count == 2
        assert log.total_record_count == 7

    def test_reload_loads_only_active_segment(self, tmp_path: Path) -> None:
        path = tmp_path / "audit.jsonl"
        log = _file_log(path, max_active_records=3, max_active_bytes=0)
        for i in range(7):
            _append_record(log, override={"adjudication_id": f"id-{i}"})

        # A fresh instance (process restart) loads ONLY the active segment into
        # RAM but still restores the chain head from it.
        reloaded = _file_log(path, max_active_records=3, max_active_bytes=0)
        assert len(reloaded.records) == 1
        assert reloaded.segment_count == 2
        reloaded.verify()
        reloaded.verify(full=True)

    def test_reload_after_rotation_continues_chain(self, tmp_path: Path) -> None:
        path = tmp_path / "audit.jsonl"
        log = _file_log(path, max_active_records=2, max_active_bytes=0)
        for i in range(6):
            _append_record(log, override={"adjudication_id": f"id-{i}"})
        last_seq = max(r.seq for r in log.iter_all_records())

        reloaded = _file_log(path, max_active_records=2, max_active_bytes=0)
        nxt = _append_record(reloaded, override={"adjudication_id": "id-next"})
        assert nxt.seq == last_seq + 1
        reloaded.verify(full=True)

    def test_reload_with_empty_active_restores_head_from_index(self, tmp_path: Path) -> None:
        """If a restart finds the active file empty (just rotated), the chain head
        is restored from the segment index's last_record_hash / last_seq."""
        path = tmp_path / "audit.jsonl"
        log = _file_log(path, max_active_records=2, max_active_bytes=0)
        # 4 records → 2 sealed segments, active file freshly emptied (0 records).
        for i in range(4):
            _append_record(log, override={"adjudication_id": f"id-{i}"})
        assert log.record_count == 0
        assert log.segment_count == 2

        reloaded = _file_log(path, max_active_records=2, max_active_bytes=0)
        assert reloaded.record_count == 0
        # Appending continues from seq 4 (index last_seq 3 + 1), chain intact.
        nxt = _append_record(reloaded, override={"adjudication_id": "id-4"})
        assert nxt.seq == 4
        reloaded.verify(full=True)


# ---------------------------------------------------------------------------
# Group O: Retention prune is audited; verify still passes with the gap
# ---------------------------------------------------------------------------


class TestRetentionPruneAudited:
    def _segment_line_size(self, tmp_path: Path) -> int:
        """Compressed size of a single 1-record sealed segment (for thresholds)."""
        probe = _file_log(tmp_path / "probe.jsonl", max_active_records=1, max_active_bytes=0)
        _append_record(probe, override={"adjudication_id": "id-probe"})
        return _sealed_segments(tmp_path / "probe.jsonl")[0].stat().st_size

    def test_default_keeps_everything_no_prune(self, tmp_path: Path) -> None:
        """With archive ceilings unset (default), nothing is ever pruned."""
        path = tmp_path / "audit.jsonl"
        log = _file_log(path, max_active_records=2, max_active_bytes=0)
        for i in range(12):
            _append_record(log, override={"adjudication_id": f"id-{i}"})
        prunes = [r for r in log.iter_all_records() if r.decision == RETENTION_PRUNE_DECISION]
        assert prunes == []
        assert log.total_record_count == 12

    def test_byte_ceiling_prunes_oldest_and_audits_it(self, tmp_path: Path) -> None:
        seg_size = self._segment_line_size(tmp_path)
        path = tmp_path / "audit.jsonl"
        # Keep roughly the two newest 1-record segments worth of bytes.
        log = _file_log(
            path,
            max_active_records=1,
            max_active_bytes=0,
            archive_max_bytes=int(seg_size * 2.5),
        )
        for i in range(10):
            _append_record(log, override={"adjudication_id": f"id-{i}"})

        prunes = [r for r in log.iter_all_records() if r.decision == RETENTION_PRUNE_DECISION]
        # At least one prune happened, each documented by a signed meta-record.
        assert len(prunes) >= 1
        for pr in prunes:
            assert pr.source_agent == "audit_log"
            assert pr.verb == "PRUNE"
            assert pr.resource.endswith(".jsonl.gz")
        # The documented gap does NOT break verify (fast or full).
        log.verify()
        log.verify(full=True)
        # Some sealed segments remain (we did not prune everything).
        assert log.segment_count >= 1

    def test_age_ceiling_prunes_and_audits(self, tmp_path: Path) -> None:
        path = tmp_path / "audit.jsonl"
        # max_age_days=0 → every sealed segment is immediately over-age.
        log = _file_log(
            path, max_active_records=1, max_active_bytes=0, archive_max_age_days=0
        )
        for i in range(6):
            _append_record(log, override={"adjudication_id": f"id-{i}"})
        prunes = [r for r in log.iter_all_records() if r.decision == RETENTION_PRUNE_DECISION]
        assert len(prunes) >= 1
        log.verify()
        log.verify(full=True)

    def test_prune_record_distinguishable_from_tail_deletion(self, tmp_path: Path) -> None:
        """The signed RETENTION_PRUNE record is what makes a policy gap distinct
        from a #606 tail-deletion attack (which leaves NO such record)."""
        seg_size = self._segment_line_size(tmp_path)
        path = tmp_path / "audit.jsonl"
        log = _file_log(
            path,
            max_active_records=1,
            max_active_bytes=0,
            archive_max_bytes=int(seg_size * 2.5),
        )
        for i in range(8):
            _append_record(log, override={"adjudication_id": f"id-{i}"})
        # The prune is part of the signed chain — verify(full=True) confirms its
        # signature, so it cannot be forged after the fact.
        log.verify(full=True)
        prunes = [r for r in log.iter_all_records() if r.decision == RETENTION_PRUNE_DECISION]
        assert prunes, "expected an audited prune"

    def test_prune_then_reload_verifies(self, tmp_path: Path) -> None:
        seg_size = self._segment_line_size(tmp_path)
        path = tmp_path / "audit.jsonl"
        log = _file_log(
            path,
            max_active_records=1,
            max_active_bytes=0,
            archive_max_bytes=int(seg_size * 2.5),
        )
        for i in range(10):
            _append_record(log, override={"adjudication_id": f"id-{i}"})
        # Reload (without the ceiling) and verify the retained chain is intact.
        reloaded = _file_log(path, max_active_records=1, max_active_bytes=0)
        reloaded.verify()
        reloaded.verify(full=True)


# ---------------------------------------------------------------------------
# Group P: Fail-safe rotation (no record lost, chain intact)
# ---------------------------------------------------------------------------


class TestFailSafeRotation:
    def test_rotation_failure_keeps_appending_loses_no_record(self, tmp_path: Path) -> None:
        path = tmp_path / "audit.jsonl"
        log = _file_log(path, max_active_records=2, max_active_bytes=0)
        _append_record(log, override={"adjudication_id": "id-0"})

        # Make the NEXT rotation's compression step raise.
        import shared.security.audit_log as _al

        class _BoomGzip:
            def __init__(self, *args: Any, **kwargs: Any) -> None:
                raise OSError("simulated seal failure")

        with patch.object(_al.gzip, "GzipFile", _BoomGzip):
            _append_record(log, override={"adjudication_id": "id-1"})  # crosses cap
            _append_record(log, override={"adjudication_id": "id-2"})  # keep appending

        # Degraded to unbounded: all 3 records retained in the active file, no
        # sealed segment, and the chain still verifies.
        assert log.record_count == 3
        assert log.segment_count == 0
        log.verify()
        # No partial sealed artifact left behind.
        assert _sealed_segments(path) == []

    def test_rotation_resumes_after_transient_failure(self, tmp_path: Path) -> None:
        """Once the transient failure clears, the next over-cap append rotates."""
        path = tmp_path / "audit.jsonl"
        log = _file_log(path, max_active_records=2, max_active_bytes=0)
        _append_record(log, override={"adjudication_id": "id-0"})

        import shared.security.audit_log as _al

        class _BoomGzip:
            def __init__(self, *args: Any, **kwargs: Any) -> None:
                raise OSError("simulated seal failure")

        with patch.object(_al.gzip, "GzipFile", _BoomGzip):
            _append_record(log, override={"adjudication_id": "id-1"})
        assert log.segment_count == 0
        assert log.record_count == 3 - 1  # 2 records, still over cap, unsealed

        # Failure cleared: a further append re-attempts rotation and succeeds.
        _append_record(log, override={"adjudication_id": "id-2"})
        assert log.segment_count == 1
        log.verify(full=True)

    def test_write_failure_still_fail_closed(self, tmp_path: Path) -> None:
        """The pre-existing _write_record fail-closed contract is unchanged by
        segmentation: a write OSError surfaces as AuditSinkError (never silent)."""
        path = tmp_path / "audit.jsonl"
        log = _file_log(path, max_active_records=0, max_active_bytes=0)

        import builtins

        original_open = builtins.open

        def _fail_open(*args: Any, **kwargs: Any):
            # Fail only the active-file append (mode contains 'a'); allow the rest.
            if str(args[0]).endswith("audit.jsonl") and "a" in str(args[1] if len(args) > 1 else kwargs.get("mode", "")):
                raise OSError("simulated disk full")
            return original_open(*args, **kwargs)

        with patch("builtins.open", side_effect=_fail_open):
            with pytest.raises(AuditSinkError, match="Audit-log write failed"):
                _append_record(log)
