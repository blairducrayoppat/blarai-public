"""#1569: a key rotation is not a tamper, and the operator must not be told it is.

#1543 wired verify-on-load so a chain that does not verify is refused. Correct — but it
reported every failure identically, so a TPM audit-key rotation would tell the operator
their audit log had been tampered with. That is the wrong alarm at the worst moment, and
it is not hypothetical: #1543's own baseline test tripped on exactly this confusion within
minutes of the control being written.

The classification is STRUCTURAL — every raise inside verify() names its own fault,
because the code raising it knows which check failed:
  * content altered, link broken, sealed segment corrupted or missing -> TAMPER
  * hashes intact, signatures fail -> KEY_MISMATCH (rotation OR full-chain forgery)

It is NOT derived from the message. The first version substring-matched the reason
string, which interpolates values read off disk — so an attacker could write
"signature verification failed" into a field they control and have a real tamper
filed as a benign key problem. Caught in review before it shipped.

Both still refuse. Only the message and the recovery path differ.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from shared.security.audit_log import AuditChainError, AuditLog, HmacSha256Signer

_KEY_A = b"A" * 32
_KEY_B = b"B" * 32


def _chain(tmp_path: Path, key: bytes = _KEY_A, records: int = 3) -> Path:
    path = tmp_path / "audit.jsonl"
    log = AuditLog.from_path(path, HmacSha256Signer(key=key))
    for i in range(records):
        log.append(
            adjudication_id=f"1e6b1f9a-0000-4000-8000-00000000000{i}",
            decision="ALLOW",
            car_hash=f"{i:064x}",
            source_agent="assistant_orchestrator",
            destination_service="substrate",
            verb="EXECUTE",
            resource=f"tool:probe_{i}",
            sensitivity="INTERNAL",
            rule_engine_passed=True,
            confidence=1.0,
        )
    log.verify()  # the seed must be genuinely valid or every case below is vacuous
    return path


def _tamper(path: Path) -> None:
    lines = path.read_text(encoding="utf-8").splitlines()
    record = json.loads(lines[-1])
    record["resource"] = "tool:something_the_operator_never_approved"
    lines[-1] = json.dumps(record)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


class TestTheTwoFaultsAreDistinguished:
    """The measurement this ticket rests on, turned into a lock."""

    def test_tampered_content_is_classified_TAMPER(self, tmp_path: Path) -> None:
        path = _chain(tmp_path)
        _tamper(path)

        with pytest.raises(AuditChainError) as caught:
            AuditLog.from_path(path, HmacSha256Signer(key=_KEY_A)).verify()

        assert caught.value.fault == AuditChainError.TAMPER
        assert caught.value.is_tamper is True
        assert "record_hash mismatch" in caught.value.reason

    def test_wrong_key_is_classified_KEY_MISMATCH(self, tmp_path: Path) -> None:
        """A rotation must NOT be reported as tampering."""
        path = _chain(tmp_path, key=_KEY_A)

        with pytest.raises(AuditChainError) as caught:
            AuditLog.from_path(path, HmacSha256Signer(key=_KEY_B)).verify()

        assert caught.value.fault == AuditChainError.KEY_MISMATCH
        assert caught.value.is_tamper is False
        assert "signature verification failed" in caught.value.reason

    def test_an_untampered_chain_with_the_right_key_raises_nothing(self, tmp_path: Path) -> None:
        """THE BASELINE. Without it, a classifier that called everything TAMPER would
        pass the first case, and one that called everything KEY_MISMATCH would pass the
        second — neither distinguishing anything."""
        path = _chain(tmp_path)

        AuditLog.from_path(path, HmacSha256Signer(key=_KEY_A)).verify()

    def test_the_two_faults_are_not_the_same_value(self) -> None:
        """Guards against a refactor collapsing the classes into one constant."""
        assert AuditChainError.TAMPER != AuditChainError.KEY_MISMATCH


class TestBothFaultsStillRefuse:
    """Classification changes the message, never the verdict."""

    @pytest.mark.parametrize("key, tamper", [(_KEY_A, True), (_KEY_B, False)])
    def test_every_fault_class_raises(self, tmp_path: Path, key: bytes, tamper: bool) -> None:
        path = _chain(tmp_path)
        if tamper:
            _tamper(path)

        with pytest.raises(AuditChainError):
            AuditLog.from_path(path, HmacSha256Signer(key=key)).verify()


class TestAFullChainForgeryIsINDISTINGUISHABLEFromARotation:
    """A full-chain rewrite with the attacker's own key produces the ROTATION signature.

    This is the honest limit of the classification, and it is asserted rather than left
    implicit: an attacker who re-signs every record with a key they control leaves the
    hashes internally consistent, so the fault reads KEY_MISMATCH. The design consequence
    is that KEY_MISMATCH must never mean "probably benign, proceed" — it still refuses,
    and its guidance says so.
    """

    def test_full_chain_forgery_reads_as_key_mismatch_and_still_refuses(
        self, tmp_path: Path
    ) -> None:
        # The "attacker" rebuilds the whole chain with their own key: internally
        # consistent, every hash recomputes, signed with a key we do not hold.
        forged = _chain(tmp_path, key=_KEY_B)

        with pytest.raises(AuditChainError) as caught:
            AuditLog.from_path(forged, HmacSha256Signer(key=_KEY_A)).verify()

        assert caught.value.fault == AuditChainError.KEY_MISMATCH
        assert "forgery" in caught.value.operator_guidance.lower(), (
            "KEY_MISMATCH guidance must name the forgery possibility; a message that "
            "only mentions rotation would invite an operator to wave through an attack"
        )


class TestUnrecognisedFailuresFailSafe:
    """Deny-by-default on the classifier itself."""

    def test_an_unknown_reason_is_classified_TAMPER(self) -> None:
        """A failure mode added later must be treated as the MORE serious class until
        someone classifies it, not quietly filed as a benign key problem."""
        err = AuditChainError(3, "some new failure nobody has classified yet")

        assert err.fault == AuditChainError.TAMPER
        assert err.is_tamper is True

    def test_an_explicit_fault_overrides_the_derivation(self) -> None:
        err = AuditChainError(0, "anything", fault=AuditChainError.KEY_MISMATCH)

        assert err.fault == AuditChainError.KEY_MISMATCH


class TestGuidanceNamesTheRemedy:
    """FAIL-LOUD: a refusal has to be diagnosable when it fires."""

    def test_tamper_guidance_says_preserve_not_regenerate(self) -> None:
        guidance = AuditChainError(2, "record_hash mismatch: computed 'abc'").operator_guidance

        assert "altered" in guidance.lower()
        assert "forensics" in guidance.lower()

    def test_key_mismatch_guidance_offers_the_rotation_path(self) -> None:
        # A caller outside verify() must NAME the fault; the fallback always returns
        # TAMPER by design, because deriving it from the message is the #1569 defect.
        guidance = AuditChainError(
            0, "signature verification failed", fault=AuditChainError.KEY_MISMATCH
        ).operator_guidance

        assert "rotated" in guidance.lower()
        # #1578: this asserted `verify(signer=)` — a remedy the operator could
        # not perform (no CLI, no script, no runbook) and which could not have
        # worked anyway, since one verifier cannot cover a chain spanning two
        # keys. The test was pinning the defect. It now asserts the ceremony
        # that exists and a pointer to the runbook that documents it.
        assert "rotate_audit_key" in guidance
        assert "audit_key_rotation.md" in guidance

    def test_the_two_guidances_differ(self) -> None:
        """The toggle: identical guidance would make classification pointless."""
        tamper = AuditChainError(2, "record_hash mismatch").operator_guidance
        key = AuditChainError(
            0, "signature verification failed", fault=AuditChainError.KEY_MISMATCH
        ).operator_guidance

        assert tamper != key


class TestClassificationIsNotAttackerControlled:
    """#1569 review finding 1: the first classifier read bytes the attacker writes.

    It substring-matched the reason string, which interpolates `prev_hash`,
    `record_hash`, `filename` and `file_sha256` — all read off disk with no format
    validation, by an attacker this module's threat model explicitly includes. Writing
    `signature verification failed` into any of them filed a REAL TAMPER as a benign key
    problem, and the operator was shown "Every record hash is intact" beside a
    record-hash mismatch, without the forensics instruction.

    Classification now happens at each raise site, where the code knows which check
    failed. These locks pin that it cannot be steered from disk.
    """

    def test_injected_signature_text_in_record_hash_is_still_TAMPER(
        self, tmp_path: Path
    ) -> None:
        path = _chain(tmp_path)
        lines = path.read_text(encoding="utf-8").splitlines()
        record = json.loads(lines[-1])
        record["resource"] = "tool:never_approved"
        record["record_hash"] = "signature verification failed"
        lines[-1] = json.dumps(record)
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")

        with pytest.raises(AuditChainError) as caught:
            AuditLog.from_path(path, HmacSha256Signer(key=_KEY_A)).verify()

        assert caught.value.fault == AuditChainError.TAMPER, (
            "an attacker steered the fault classification by writing the magic string "
            "into a field they control — the classification is reading disk bytes"
        )
        assert caught.value.is_tamper is True
        assert "forensics" in caught.value.operator_guidance.lower()

    def test_injected_signature_text_in_prev_hash_is_still_TAMPER(
        self, tmp_path: Path
    ) -> None:
        path = _chain(tmp_path)
        lines = path.read_text(encoding="utf-8").splitlines()
        record = json.loads(lines[-1])
        record["prev_hash"] = "signature verification failed"
        lines[-1] = json.dumps(record)
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")

        with pytest.raises(AuditChainError) as caught:
            AuditLog.from_path(path, HmacSha256Signer(key=_KEY_A)).verify()

        assert caught.value.fault == AuditChainError.TAMPER

    def test_the_fallback_classifier_ignores_the_message_entirely(self) -> None:
        """The fallback must not be steerable either, even by a well-formed message."""
        assert AuditChainError(0, "signature verification failed").fault == (
            AuditChainError.TAMPER
        ), "the fallback still reads the reason string — it must always fail safe"
        assert AuditChainError(0, "anything at all").fault == AuditChainError.TAMPER

    def test_a_genuine_rotation_is_still_KEY_MISMATCH(self, tmp_path: Path) -> None:
        """The toggle. If everything were now TAMPER the tests above would pass while
        the classification distinguished nothing — which is the state before #1569."""
        path = _chain(tmp_path, key=_KEY_A)

        with pytest.raises(AuditChainError) as caught:
            AuditLog.from_path(path, HmacSha256Signer(key=_KEY_B)).verify()

        assert caught.value.fault == AuditChainError.KEY_MISMATCH


class TestSealedSegmentFaultsAreClassified:
    """The five raise sites the original locks never reached (review finding 2)."""

    def _rotated(self, tmp_path: Path) -> Path:
        path = tmp_path / "audit.jsonl"
        log = AuditLog.from_path(path, HmacSha256Signer(key=_KEY_A), max_active_records=2)
        for i in range(5):
            log.append(
                adjudication_id=f"2e6b1f9a-0000-4000-8000-00000000000{i}",
                decision="ALLOW", car_hash=f"{i:064x}", source_agent="ao",
                destination_service="s", verb="EXECUTE", resource=f"tool:{i}",
                sensitivity="INTERNAL", rule_engine_passed=True, confidence=1.0,
            )
        log.verify()
        return path

    def test_corrupted_sealed_segment_is_TAMPER_not_a_key_problem(
        self, tmp_path: Path
    ) -> None:
        path = self._rotated(tmp_path)
        sealed = sorted(path.parent.glob("audit-*.jsonl.gz"))
        assert sealed, "no sealed segment produced — this lock would prove nothing"
        blob = bytearray(sealed[0].read_bytes())
        blob[-1] ^= 0xFF
        sealed[0].write_bytes(bytes(blob))

        with pytest.raises(AuditChainError) as caught:
            AuditLog.from_path(path, HmacSha256Signer(key=_KEY_A)).verify()

        assert caught.value.fault == AuditChainError.TAMPER, (
            "a corrupted sealed segment was classified as a key problem — the #606 "
            "tail-deletion class would be reported as a benign rotation"
        )

    def test_deleted_sealed_segment_is_TAMPER(self, tmp_path: Path) -> None:
        path = self._rotated(tmp_path)
        sealed = sorted(path.parent.glob("audit-*.jsonl.gz"))
        sealed[0].unlink()

        with pytest.raises(AuditChainError) as caught:
            AuditLog.from_path(path, HmacSha256Signer(key=_KEY_A)).verify()

        assert caught.value.fault == AuditChainError.TAMPER

    def test_a_rotated_chain_with_the_right_key_still_verifies(
        self, tmp_path: Path
    ) -> None:
        """Baseline for this class: rotation alone must not trip any fault."""
        path = self._rotated(tmp_path)

        AuditLog.from_path(path, HmacSha256Signer(key=_KEY_A)).verify()
