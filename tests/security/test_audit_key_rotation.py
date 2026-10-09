"""#1578: a signing-key rotation must not brick the audit chain.

MEASURED BEFORE THE FIX, on a real chain: a chain spanning a rotation verified
under NEITHER key — the pre-rotation records need the retired key and the
post-rotation records need the current one, and ``verify()`` bound one verifier
for the whole walk. The Policy Agent refused to start, three times identically,
with no escape in any code path. The remedy its own message named,
``verify(signer=...)``, could not have worked for the same reason.

THE BRIDGE. A rotation writes a record signed by the OUTGOING key naming the
INCOMING key in ``resource`` — a field inside the canonical bytes, so the naming
is covered by the outgoing key's signature. A verifier walking forward meets a
record it can check, and that record tells it which key signs what follows.

WHY NOT ``signer_id``: it sits outside the canonical bytes, so an attacker who
rewrites the chain writes whatever ``signer_id`` they like. Selecting a verifier
from it would re-open the #1569 defect. The bridge is a signed statement.

WHY THE HISTORY FILE IS NOT A TRUST ROOT: it only says where to START. The key
sequence is established by signatures, and each key must actually resolve — on
this machine, exist on the TPM. A forged history produces a chain that fails to
verify, never one that verifies falsely.
"""

from __future__ import annotations

import gzip
import json
from pathlib import Path

import pytest

from shared.security.audit_key_history import (
    AuditKeyHistoryError,
    append_key,
    read_history,
)
from shared.security.audit_log import (
    AUDIT_KEY_ROTATION_VERB,
    AuditChainError,
    AuditLog,
    HmacSha256Signer,
    hmac_key_resolver,
)

_A = HmacSha256Signer(key=b"A" * 32, key_id="keyA")
_B = HmacSha256Signer(key=b"B" * 32, key_id="keyB")
_C = HmacSha256Signer(key=b"C" * 32, key_id="keyC")
_KEYS = {s.signer_id(): s for s in (_A, _B, _C)}
_RESOLVE = hmac_key_resolver(_KEYS)

_COMMON = dict(
    source_agent="ao",
    destination_service="tools",
    verb="EXECUTE",
    sensitivity="INTERNAL",
    rule_engine_passed=True,
    confidence=1.0,
)


def _chain(tmp_path: Path, rotations: int = 1) -> AuditLog:
    log = AuditLog.from_path(tmp_path / "audit.jsonl", _A)
    for i in range(3):
        log.append(
            adjudication_id=f"a{i}", decision="ALLOW", car_hash=f"h{i}",
            resource=f"t{i}", **_COMMON,
        )
    log.rotate_signing_key(_B)
    for i in range(3):
        log.append(
            adjudication_id=f"b{i}", decision="ALLOW", car_hash=f"j{i}",
            resource=f"u{i}", **_COMMON,
        )
    if rotations >= 2:
        log.rotate_signing_key(_C)
        for i in range(2):
            log.append(
                adjudication_id=f"c{i}", decision="ALLOW", car_hash=f"k{i}",
                resource=f"v{i}", **_COMMON,
            )
    return log


class TestAChainSpanningARotationVerifies:
    """The defect itself."""

    @pytest.mark.parametrize("rotations", [1, 2])
    @pytest.mark.parametrize("full", [False, True])
    def test_it_verifies(self, tmp_path: Path, rotations: int, full: bool) -> None:
        log = _chain(tmp_path, rotations)
        log.verify(signer=_A, key_resolver=_RESOLVE, full=full)

    @pytest.mark.parametrize("rotations", [1, 2])
    def test_it_verifies_after_a_reload_from_disk(
        self, tmp_path: Path, rotations: int
    ) -> None:
        """The in-process object holds state a reloaded one does not, so a
        rotation that only works before a restart works for nobody."""
        _chain(tmp_path, rotations)
        current = _C if rotations >= 2 else _B
        AuditLog.from_path(tmp_path / "audit.jsonl", current).verify(
            signer=_A, key_resolver=_RESOLVE, full=True
        )

    def test_the_bridge_names_the_incoming_key_inside_the_signed_bytes(
        self, tmp_path: Path
    ) -> None:
        """If the naming were outside the signature, an attacker could redirect
        the walk to a key of their choosing."""
        from shared.security.audit_log import _canonical_bytes

        log = _chain(tmp_path, 1)
        bridge = next(
            r for r in log.records if r.verb == AUDIT_KEY_ROTATION_VERB
        )
        assert bridge.resource == _B.signer_id()
        canon = _canonical_bytes(
            seq=bridge.seq, adjudication_id=bridge.adjudication_id,
            decision=bridge.decision, car_hash=bridge.car_hash,
            source_agent=bridge.source_agent,
            destination_service=bridge.destination_service, verb=bridge.verb,
            resource=bridge.resource, sensitivity=bridge.sensitivity,
            rule_engine_passed=bridge.rule_engine_passed,
            confidence=bridge.confidence, timestamp_utc=bridge.timestamp_utc,
            prev_hash=bridge.prev_hash, receipt=bridge.receipt,
            schema_version=bridge.schema_version,
        )
        assert _B.signer_id().encode() in canon, (
            "the incoming key is named OUTSIDE the signed bytes, so the bridge "
            "can be redirected by editing the file."
        )

    def test_rotating_to_the_same_key_is_refused(self, tmp_path: Path) -> None:
        log = AuditLog.from_path(tmp_path / "audit.jsonl", _A)
        with pytest.raises(ValueError, match="same key"):
            log.rotate_signing_key(HmacSha256Signer(key=b"Z" * 32, key_id="keyA"))


class TestTheRotatedChainStillDetectsTampering:
    """A bridge that made a chain verifiable must not make it unfalsifiable.

    Every case here MUST fail. Without them, code that skipped verification
    entirely would pass the class above.
    """

    def _tamper(self, tmp_path: Path, mutate) -> None:
        _chain(tmp_path, 1)
        active = tmp_path / "audit.jsonl"
        before = active.read_text(encoding="utf-8")
        after = "\n".join(mutate(before.splitlines())) + "\n"
        assert after != before, "the mutation did not apply; this test proves nothing"
        active.write_text(after, encoding="utf-8")
        with pytest.raises(AuditChainError):
            AuditLog.from_path(active, _B).verify(
                signer=_A, key_resolver=_RESOLVE, full=True
            )

    def test_a_record_after_the_rotation(self, tmp_path: Path) -> None:
        self._tamper(
            tmp_path,
            lambda ls: [l.replace('"resource":"u1"', '"resource":"HACKED"') for l in ls],
        )

    def test_the_bridge_redirected_to_another_key(self, tmp_path: Path) -> None:
        self._tamper(
            tmp_path,
            lambda ls: [
                l.replace(f'"resource":"{_B.signer_id()}"', f'"resource":"{_C.signer_id()}"')
                for l in ls
            ],
        )

    def test_the_bridge_deleted(self, tmp_path: Path) -> None:
        self._tamper(
            tmp_path, lambda ls: [l for l in ls if AUDIT_KEY_ROTATION_VERB not in l]
        )

    def test_a_record_inside_a_sealed_pre_rotation_segment(
        self, tmp_path: Path
    ) -> None:
        """The rotation seals before bridging, so pre-rotation records live in a
        gzip. A tamper there must still be caught."""
        _chain(tmp_path, 1)
        sealed = sorted(tmp_path.glob("*.jsonl.gz"))
        assert sealed, "the rotation did not seal the active segment"
        raw = gzip.decompress(sealed[0].read_bytes()).decode("utf-8")
        assert '"resource":"t1"' in raw
        sealed[0].write_bytes(
            gzip.compress(raw.replace('"resource":"t1"', '"resource":"HACKED"').encode())
        )
        with pytest.raises(AuditChainError):
            AuditLog.from_path(tmp_path / "audit.jsonl", _B).verify(
                signer=_A, key_resolver=_RESOLVE, full=True
            )

    def test_an_UNTOUCHED_rotated_chain_still_passes(self, tmp_path: Path) -> None:
        """TOGGLE for the five above. A verifier that refused everything would
        satisfy all of them while rotation was simply broken."""
        _chain(tmp_path, 1)
        AuditLog.from_path(tmp_path / "audit.jsonl", _B).verify(
            signer=_A, key_resolver=_RESOLVE, full=True
        )


class TestRotationFailsClosedWhenAKeyIsMissing:
    """A retired key that cannot be produced is a refusal, never a skip."""

    def test_no_resolver_at_all(self, tmp_path: Path) -> None:
        _chain(tmp_path, 1)
        with pytest.raises(AuditChainError) as caught:
            AuditLog.from_path(tmp_path / "audit.jsonl", _B).verify(signer=_A)
        assert caught.value.fault == AuditChainError.KEY_MISMATCH

    def test_a_resolver_that_withholds_the_incoming_key(self, tmp_path: Path) -> None:
        _chain(tmp_path, 1)
        with pytest.raises(AuditChainError) as caught:
            AuditLog.from_path(tmp_path / "audit.jsonl", _B).verify(
                signer=_A, key_resolver=lambda _sid: None
            )
        assert caught.value.fault == AuditChainError.KEY_MISMATCH
        assert "RETAINED" in str(caught.value)

    def test_starting_the_walk_from_the_wrong_key(self, tmp_path: Path) -> None:
        _chain(tmp_path, 1)
        with pytest.raises(AuditChainError):
            AuditLog.from_path(tmp_path / "audit.jsonl", _B).verify(
                signer=_B, key_resolver=_RESOLVE, full=True
            )


class TestTheSegmentSummaryVersionIsBackwardCompatible:
    """The migration. Index rows sealed before #1578 do not bind a key id, and
    their bytes are frozen: including the id unconditionally would have changed
    the signed bytes of every row already on disk."""

    def test_a_v1_row_produces_the_pre_rotation_bytes(self) -> None:
        from shared.security.audit_log import SegmentEntry, _segment_summary_bytes

        row = SegmentEntry(
            first_seq=0, last_seq=2, first_prev_hash="p", last_record_hash="l",
            file_sha256="sha", segment_signature="00", filename="f",
            signer_id="HMAC-SHA256:keyA",
        )
        assert row.summary_version == 1
        assert row.summary_bytes() == _segment_summary_bytes(0, 2, "p", "l", "sha")
        assert b"signer_key_id" not in row.summary_bytes()

    def test_a_v2_row_binds_its_key(self) -> None:
        from shared.security.audit_log import SegmentEntry

        row = SegmentEntry(
            first_seq=0, last_seq=2, first_prev_hash="p", last_record_hash="l",
            file_sha256="sha", segment_signature="00", filename="f",
            signer_id="HMAC-SHA256:keyA", summary_version=2,
        )
        assert b"signer_key_id" in row.summary_bytes()

    def test_downgrading_a_v2_row_changes_its_bytes(self) -> None:
        """So a v2 row cannot be stripped of its key binding on disk: the
        signature stops matching. A fallback-to-legacy design would have let an
        attacker remove the binding and verify under any key in force."""
        from shared.security.audit_log import SegmentEntry

        args = dict(
            first_seq=0, last_seq=2, first_prev_hash="p", last_record_hash="l",
            file_sha256="sha", segment_signature="00", filename="f",
            signer_id="HMAC-SHA256:keyA",
        )
        v1 = SegmentEntry(**args, summary_version=1)  # type: ignore[arg-type]
        v2 = SegmentEntry(**args, summary_version=2)  # type: ignore[arg-type]
        assert v1.summary_bytes() != v2.summary_bytes()

    def test_an_absent_version_reads_as_1_not_the_current_constant(self) -> None:
        from shared.security.audit_log import SegmentEntry

        row = SegmentEntry.from_dict(
            {
                "first_seq": 0, "last_seq": 2, "first_prev_hash": "p",
                "last_record_hash": "l", "file_sha256": "sha",
                "segment_signature": "00", "filename": "f",
                "signer_id": "HMAC-SHA256:keyA",
            }
        )
        assert row.summary_version == 1, (
            "an absent version resolved to the CURRENT constant, which silently "
            "changes the signed bytes of every row already on disk."
        )


class TestTheKeyHistory:
    """A hint, and it must behave like one."""

    def test_absent_history_reads_as_never_rotated(self, tmp_path: Path) -> None:
        assert read_history(tmp_path / "audit.jsonl") == []

    def test_a_malformed_history_RAISES_rather_than_reading_as_empty(
        self, tmp_path: Path
    ) -> None:
        """Resolving to empty would start the walk at the current key and report
        a rotated chain as a TAMPER — the #1569 misreport, reintroduced."""
        (tmp_path / "audit-keys.json").write_text("{not json", encoding="utf-8")
        with pytest.raises(AuditKeyHistoryError):
            read_history(tmp_path / "audit.jsonl")

    def test_keys_are_recorded_oldest_first(self, tmp_path: Path) -> None:
        log_path = tmp_path / "audit.jsonl"
        append_key(log_path, "HMAC-SHA256:keyA")
        append_key(log_path, "HMAC-SHA256:keyB")
        assert read_history(log_path) == ["HMAC-SHA256:keyA", "HMAC-SHA256:keyB"]

    def test_re_recording_the_newest_key_is_idempotent(self, tmp_path: Path) -> None:
        log_path = tmp_path / "audit.jsonl"
        append_key(log_path, "HMAC-SHA256:keyA")
        append_key(log_path, "HMAC-SHA256:keyA")
        assert read_history(log_path) == ["HMAC-SHA256:keyA"]

    def test_re_adopting_a_RETIRED_key_is_refused(self, tmp_path: Path) -> None:
        log_path = tmp_path / "audit.jsonl"
        append_key(log_path, "HMAC-SHA256:keyA")
        append_key(log_path, "HMAC-SHA256:keyB")
        with pytest.raises(AuditKeyHistoryError, match="already appears"):
            append_key(log_path, "HMAC-SHA256:keyA")

    def test_the_history_is_valid_json_with_a_schema(self, tmp_path: Path) -> None:
        log_path = tmp_path / "audit.jsonl"
        append_key(log_path, "HMAC-SHA256:keyA")
        payload = json.loads((tmp_path / "audit-keys.json").read_text(encoding="utf-8"))
        assert payload["schema"].startswith("blarai.audit-key-history/")


class TestACorruptedSignatureHexIsClassified:
    """#1578 item 2. ``bytes.fromhex`` raises a bare ``ValueError``, and
    ``AuditChainError`` IS a ``ValueError`` — so ``except AuditChainError`` never
    caught it and the operator saw "non-hexadecimal number found in fromhex()",
    which reads like a bug rather than an attack."""

    def test_it_raises_AuditChainError_not_a_bare_ValueError(
        self, tmp_path: Path
    ) -> None:
        log = AuditLog.from_path(tmp_path / "audit.jsonl", _A)
        for i in range(3):
            log.append(
                adjudication_id=f"a{i}", decision="ALLOW", car_hash=f"h{i}",
                resource=f"t{i}", **_COMMON,
            )
        active = tmp_path / "audit.jsonl"
        lines = active.read_text(encoding="utf-8").splitlines()
        row = json.loads(lines[1])
        row["signature"] = "zzzz-not-hex"
        lines[1] = json.dumps(row, separators=(",", ":"))
        active.write_text("\n".join(lines) + "\n", encoding="utf-8")

        with pytest.raises(AuditChainError) as caught:
            AuditLog.from_path(active, _A).verify()
        assert caught.value.fault == AuditChainError.TAMPER
        assert "not valid hex" in str(caught.value)

    def test_a_VALID_hex_signature_still_verifies(self, tmp_path: Path) -> None:
        """TOGGLE. A check that rejected every signature would satisfy the test
        above while breaking verification outright."""
        log = AuditLog.from_path(tmp_path / "audit.jsonl", _A)
        log.append(
            adjudication_id="a", decision="ALLOW", car_hash="h",
            resource="t", **_COMMON,
        )
        AuditLog.from_path(tmp_path / "audit.jsonl", _A).verify()


class TestTheRefusalTellsTheOperatorWhatToDo:
    """#1578 items 3 and 4."""

    def test_the_tamper_guidance_says_the_chain_was_refused(self) -> None:
        guidance = AuditChainError(
            0, "record_hash mismatch", fault=AuditChainError.TAMPER
        ).operator_guidance
        assert "REFUSED" in guidance, (
            "for the MORE serious class the operator is told LESS: only the "
            "key-mismatch guidance stated the chain was refused."
        )

    def test_the_key_mismatch_guidance_names_a_ceremony_that_EXISTS(self) -> None:
        guidance = AuditChainError(
            0, "signature verification failed", fault=AuditChainError.KEY_MISMATCH
        ).operator_guidance
        assert "rotate_audit_key" in guidance
        assert "verify(signer=" not in guidance, (
            "the guidance still names verify(signer=...), a remedy with no CLI, "
            "no script and no runbook — and one that cannot work anyway, since a "
            "single verifier cannot cover a chain spanning two keys."
        )

    def test_the_named_ceremony_is_importable(self) -> None:
        """The remedy must be reachable, not merely described. A runbook naming
        a module that does not exist is the same defect in a new place."""
        import importlib

        module = importlib.import_module("shared.security.rotate_audit_key")
        assert hasattr(module, "rotate") and hasattr(module, "main")

    def test_the_runbook_the_guidance_names_exists(self) -> None:
        runbook = (
            Path(__file__).resolve().parents[2]
            / "docs" / "runbooks" / "audit_key_rotation.md"
        )
        assert runbook.exists(), (
            "the refusal points the operator at a runbook that is not there."
        )


class TestTheSigningKeyFollowsTheRotation:
    """Review finding 1, which was disqualifying: the remedy CAUSED the defect.

    Both services chose their signing key from the compiled-in constant. After
    the ceremony wrote a bridge declaring the new key, a service rebooted
    holding the RETIRED one and appended records signed by it AFTER that bridge.
    Boot #1 verified — nothing followed the bridge yet — and the runbook called
    that success. Boot #2 walked to the bridge, switched keys as designed, and
    refused. Permanently: the ceremony's own step 1 refuses on a chain that does
    not verify, and the history refuses to re-adopt a retired key, so both
    scripted escapes were closed.
    """

    def test_the_policy_agent_signs_with_the_newest_key(self, tmp_path: Path) -> None:
        from shared.security.audit_verification import (
            signing_key_name as _audit_signing_key_name,
        )

        log_path = tmp_path / "adjudication_audit.jsonl"
        assert _audit_signing_key_name(log_path) == "BlarAI-Audit-Signing-Key-v1", (
            "a chain with no history must use the compiled-in default, or every "
            "existing install changes behaviour."
        )
        append_key(log_path, "ECDSA-P256-TPM:BlarAI-Audit-Signing-Key-v1")
        append_key(log_path, "ECDSA-P256-TPM:BlarAI-Audit-Signing-Key-v2")
        assert _audit_signing_key_name(log_path) == "BlarAI-Audit-Signing-Key-v2", (
            "the service still signs with the RETIRED key after a rotation. Its "
            "records land after a bridge declaring the new key, and the NEXT "
            "boot refuses permanently."
        )

    def test_the_orchestrator_signs_with_the_newest_key(self, tmp_path: Path) -> None:
        from shared.security.audit_verification import signing_key_name as ao_key

        log_path = tmp_path / "ingest_audit.jsonl"
        assert ao_key(log_path) == "BlarAI-Audit-Signing-Key-v1"
        append_key(log_path, "ECDSA-P256-TPM:BlarAI-Audit-Signing-Key-v1")
        append_key(log_path, "ECDSA-P256-TPM:BlarAI-Audit-Signing-Key-v9")
        assert ao_key(log_path) == "BlarAI-Audit-Signing-Key-v9"

    def test_three_consecutive_boots_after_a_rotation_all_verify(
        self, tmp_path: Path
    ) -> None:
        """THE REGRESSION LOCK for the brick. Boot, append, reboot, three times.
        The original defect passed boot #1 and failed boot #2, so a single-boot
        test would have certified it."""
        log_path = tmp_path / "audit.jsonl"
        log = AuditLog.from_path(log_path, _A)
        for i in range(3):
            log.append(
                adjudication_id=f"pre{i}", decision="ALLOW", car_hash=f"h{i}",
                resource=f"t{i}", **_COMMON,
            )
        log.rotate_signing_key(_B)
        append_key(log_path, _A.signer_id())
        append_key(log_path, _B.signer_id())

        for boot in range(3):
            order = read_history(log_path)
            reopened = AuditLog.from_path(log_path, _KEYS[order[-1]])
            reopened.verify(
                signer=_KEYS[order[0]],
                key_resolver=hmac_key_resolver(_KEYS),
                key_order=order,
            )
            assert reopened._signer.signer_id() == _B.signer_id(), (
                f"boot {boot} signs with {reopened._signer.signer_id()}, not the "
                "key the bridge declared."
            )
            for i in range(2):
                reopened.append(
                    adjudication_id=f"boot{boot}-{i}", decision="ALLOW",
                    car_hash=f"x{i}", resource="t", **_COMMON,
                )

    def test_a_history_that_does_not_name_a_tpm_key_refuses(
        self, tmp_path: Path
    ) -> None:
        """Falling back to the default is exactly what produced the brick."""
        from shared.security.audit_verification import (
            signing_key_name as _audit_signing_key_name,
        )

        log_path = tmp_path / "audit.jsonl"
        append_key(log_path, "not-a-tpm-key")
        with pytest.raises(Exception, match="does not name a TPM key"):
            _audit_signing_key_name(log_path)


class TestTheIndexCannotBeRedirectedToAnUnadoptedKey:
    """Review finding 2. Each index row chose its own verifier from its own
    claimed id, so a chain forged end to end under an unrelated key PASSED the
    fast path with no bridge at all. The parent commit refused that chain, so
    rotation support introduced it — and it opened exactly when the feature was
    used, because a resolver is only supplied once a rotation has happened."""

    _HISTORY = [_A.signer_id(), _B.signer_id()]

    @staticmethod
    def _allowlisted(order):
        return lambda sid: _KEYS.get(sid) if sid in set(order) else None

    def _forged(self, tmp_path: Path) -> Path:
        forger = HmacSha256Signer(key=b"X" * 32, key_id="attacker")
        log = AuditLog.from_path(tmp_path / "audit.jsonl", forger, max_active_records=3)
        for i in range(8):
            log.append(
                adjudication_id=f"forged{i}", decision="ALLOW", car_hash=f"h{i}",
                resource=f"t{i}", **_COMMON,
            )
        assert sorted(tmp_path.glob("*.jsonl.gz")), "the forgery sealed nothing"
        return tmp_path / "audit.jsonl"

    @pytest.mark.parametrize("full", [False, True])
    def test_a_chain_forged_under_an_unadopted_key_is_refused(
        self, tmp_path: Path, full: bool
    ) -> None:
        path = self._forged(tmp_path)
        with pytest.raises(AuditChainError):
            AuditLog.from_path(path, _B).verify(
                signer=_A,
                key_resolver=self._allowlisted(self._HISTORY),
                key_order=self._HISTORY,
                full=full,
            )

    @pytest.mark.parametrize("full", [False, True])
    def test_the_GENUINE_rotated_chain_still_verifies(
        self, tmp_path: Path, full: bool
    ) -> None:
        """TOGGLE. A check that refused every chain would satisfy the test above
        while rotation was simply broken."""
        _chain(tmp_path, 1)
        AuditLog.from_path(tmp_path / "audit.jsonl", _B).verify(
            signer=_A,
            key_resolver=self._allowlisted(self._HISTORY),
            key_order=self._HISTORY,
            full=full,
        )

    def test_the_resolver_is_an_allowlist_not_the_whole_keyring(self) -> None:
        """tpm_key_resolver took no allowlist and resolved ANY provisioned key.
        On this machine that is four, three of which — the model-manifest key,
        the Policy-Agent JWT key and the DEK-sealing key — have nothing to do
        with the audit chain."""
        from shared.security.audit_log import tpm_key_resolver

        resolver = tpm_key_resolver(["ECDSA-P256-TPM:BlarAI-Audit-Signing-Key-v1"])
        assert resolver("ECDSA-P256-TPM:BlarAI-Manifest-Signing") is None, (
            "an unrelated on-chip key resolves for the audit chain."
        )
        assert resolver("ECDSA-P256-TPM:BlarAI-PA-JWT-Signing") is None
        assert resolver("HMAC-SHA256:anything") is None

    def test_a_row_may_not_step_BACK_to_a_retired_key(self) -> None:
        from shared.security.audit_log import SegmentEntry

        row = SegmentEntry(
            first_seq=0, last_seq=2, first_prev_hash="p", last_record_hash="l",
            file_sha256="sha", segment_signature="00", filename="f",
            signer_id=_A.signer_id(), summary_version=2,
        )
        with pytest.raises(AuditChainError, match="PRECEDES"):
            AuditLog._row_verifier(
                row, _B, self._allowlisted(self._HISTORY), self._HISTORY
            )


class TestEachChainKeepsItsOwnKeyHistory:
    """Review finding 4. The ingest and verdict chains live in ONE directory, so
    a single shared history file made a per-chain rotation unrepresentable:
    rotating one would declare a key the other had not adopted."""

    def test_two_chains_in_one_directory_do_not_share_a_history(
        self, tmp_path: Path
    ) -> None:
        from shared.security.audit_key_history import history_path

        ingest = tmp_path / "ingest_audit.jsonl"
        verdict = tmp_path / "verdict_audit.jsonl"
        assert history_path(ingest) != history_path(verdict)

        append_key(ingest, "ECDSA-P256-TPM:Key-v2")
        assert read_history(ingest) == ["ECDSA-P256-TPM:Key-v2"]
        assert read_history(verdict) == [], (
            "rotating one chain declared a key the other never adopted."
        )


class TestTheCeremonyNamesAChainThatExists:
    """Review finding 3. The script defaulted to a filename NO service writes —
    the real ones are adjudication_audit.jsonl (Policy Agent, under its service
    root), ingest_audit.jsonl and verdict_audit.jsonl. The runbook's very first
    command could only ever print "no audit log at ...", which is also why
    finding 1 had never fired: the two defects masked each other."""

    def test_discovery_finds_real_chain_names_and_skips_the_index(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from shared.security.rotate_audit_key import discover_chains

        audit_dir = tmp_path / "BlarAI" / "audit"
        audit_dir.mkdir(parents=True)
        for name in (
            "ingest_audit.jsonl",
            "verdict_audit.jsonl",
            "ingest_audit-index.jsonl",
        ):
            (audit_dir / name).write_text("", encoding="utf-8")
        monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))

        found = [path.name for path in discover_chains()]
        assert found == ["ingest_audit.jsonl", "verdict_audit.jsonl"], found

    def test_it_refuses_to_guess_between_several_chains(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Rotating the wrong chain writes a bridge into a chain the operator did
        not mean to touch, and there is no undo."""
        from shared.security.rotate_audit_key import _resolve_log_path

        audit_dir = tmp_path / "BlarAI" / "audit"
        audit_dir.mkdir(parents=True)
        (audit_dir / "ingest_audit.jsonl").write_text("", encoding="utf-8")
        (audit_dir / "verdict_audit.jsonl").write_text("", encoding="utf-8")
        monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))

        with pytest.raises(SystemExit, match="More than one audit chain"):
            _resolve_log_path(None)

    def test_a_single_chain_is_used_without_a_flag(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """TOGGLE. A resolver that refused everything would satisfy the test
        above while the ceremony could never run."""
        from shared.security.rotate_audit_key import _resolve_log_path

        audit_dir = tmp_path / "BlarAI" / "audit"
        audit_dir.mkdir(parents=True)
        (audit_dir / "ingest_audit.jsonl").write_text("", encoding="utf-8")
        monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))

        assert _resolve_log_path(None).name == "ingest_audit.jsonl"

    def test_no_chain_present_says_where_the_policy_agents_one_lives(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from shared.security.rotate_audit_key import _resolve_log_path

        monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
        with pytest.raises(SystemExit, match="SERVICE root"):
            _resolve_log_path(None)


class TestTheRefusalDoesNotPointAtItself:
    """Review finding 6. The key-mismatch guidance says to run the ceremony; the
    ceremony printed that same guidance when its own verification refused. The
    Policy Agent said "run the ceremony", the ceremony said "run the ceremony"."""

    def test_the_ceremony_does_not_echo_the_guidance_that_names_it(self) -> None:
        """AST, not a text search.

        The first version of this test searched the source for the string
        "exc.operator_guidance" and matched the COMMENT explaining why the call
        had been removed — the same defect class this session has now shipped
        three times. An attribute access is a node; a comment is not.
        """
        import ast

        source = (
            Path(__file__).resolve().parents[2]
            / "shared" / "security" / "rotate_audit_key.py"
        ).read_text(encoding="utf-8")
        accesses = [
            node
            for node in ast.walk(ast.parse(source))
            if isinstance(node, ast.Attribute)
            and node.attr == "operator_guidance"
        ]
        assert not accesses, (
            "the ceremony reads operator_guidance at line(s) "
            f"{[n.lineno for n in accesses]}. For a key mismatch that text tells "
            "the operator to run this ceremony, so printing it here leaves them "
            "in a loop with nowhere to go."
        )


class TestTheCeremonyItselfRuns:
    """#1581 review finding 2: nothing in this suite ever drove ``rotate()``.

    Its step 1 called ``tpm_key_resolver()`` with no argument — the function
    takes a required allowlist — so the ceremony raised TypeError on every
    invocation, for as long as it had existed. Only its helpers
    (``discover_chains``, ``_resolve_log_path``) were tested, and a green gate
    said nothing about the procedure the runbook tells the operator to run.

    It also passed ``key_resolver=None`` whenever the first key was missing (the
    false-TAMPER of #1578, a third copy of it) and never passed ``key_order``,
    which disengages the forged-chain lock inside the ceremony meant to protect
    the chain.

    These drive the real ``rotate()`` end to end with the chip faked at the
    ``tpm_signer`` boundary, so the ceremony runs on any machine.
    """

    @staticmethod
    def _fake_tpm(monkeypatch):
        """Back every named TPM key with its own HMAC key. Not a stub of the
        signer — the real ``TpmRecordSigner`` runs, calling these."""
        import hashlib
        import hmac as _hmac

        from shared.security import tpm_signer

        provisioned: set[str] = set()

        def _key(name: str) -> bytes:
            return hashlib.sha256(name.encode("utf-8")).digest()

        monkeypatch.setattr(tpm_signer, "is_available", lambda: True)
        monkeypatch.setattr(
            tpm_signer, "key_exists", lambda name: name in provisioned
        )
        monkeypatch.setattr(
            tpm_signer,
            "ensure_key",
            lambda name: (provisioned.add(name), True)[1],
        )
        monkeypatch.setattr(
            tpm_signer,
            "sign",
            lambda name, data: _hmac.new(_key(name), data, hashlib.sha256).digest(),
        )
        monkeypatch.setattr(
            tpm_signer,
            "verify",
            lambda name, data, sig: _hmac.compare_digest(
                _hmac.new(_key(name), data, hashlib.sha256).digest(), sig
            ),
        )
        return provisioned

    def test_the_ceremony_completes_on_a_real_chain(
        self, tmp_path: Path, monkeypatch, capsys
    ) -> None:
        """THE LOCK. It would have failed with TypeError before this change."""
        from shared.security.audit_log import AUDIT_TPM_KEY_NAME, TpmRecordSigner
        from shared.security.rotate_audit_key import rotate

        provisioned = self._fake_tpm(monkeypatch)
        provisioned.add(AUDIT_TPM_KEY_NAME)

        log_path = tmp_path / "adjudication_audit.jsonl"
        log = AuditLog.from_path(log_path, TpmRecordSigner())
        for i in range(3):
            log.append(
                adjudication_id=f"a{i}", decision="ALLOW", car_hash=f"h{i}",
                resource=f"r{i}", **_COMMON,
            )

        code = rotate(
            audit_log_path=log_path, new_key_name="BlarAI-Audit-Signing-Key-v2"
        )
        out = capsys.readouterr().out
        assert code == 0, f"the ceremony failed (exit {code}):\n{out}"
        assert "verifies ACROSS the rotation" in out, out
        assert read_history(log_path) == [
            "ECDSA-P256-TPM:BlarAI-Audit-Signing-Key-v1",
            "ECDSA-P256-TPM:BlarAI-Audit-Signing-Key-v2",
        ]

    def test_the_ceremony_refuses_a_chain_that_does_not_verify(
        self, tmp_path: Path, monkeypatch, capsys
    ) -> None:
        """The toggle: a ceremony that returned 0 unconditionally would satisfy
        the test above. Step 1 must refuse a tampered chain and NOT rotate it."""
        from shared.security.audit_log import AUDIT_TPM_KEY_NAME, TpmRecordSigner
        from shared.security.rotate_audit_key import rotate

        provisioned = self._fake_tpm(monkeypatch)
        provisioned.add(AUDIT_TPM_KEY_NAME)

        log_path = tmp_path / "adjudication_audit.jsonl"
        log = AuditLog.from_path(log_path, TpmRecordSigner())
        for i in range(3):
            log.append(
                adjudication_id=f"a{i}", decision="ALLOW", car_hash=f"h{i}",
                resource=f"r{i}", **_COMMON,
            )
        lines = log_path.read_text(encoding="utf-8").splitlines()
        record = json.loads(lines[1])
        record["resource"] = "altered"
        lines[1] = json.dumps(record)
        log_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

        code = rotate(
            audit_log_path=log_path, new_key_name="BlarAI-Audit-Signing-Key-v2"
        )
        out = capsys.readouterr().out
        assert code == 3, f"a tampered chain was not refused (exit {code}):\n{out}"
        assert "does not verify as it stands" in out
        assert read_history(log_path) == [], (
            "the ceremony wrote a key history for a chain it refused to rotate"
        )

    def test_the_ceremony_verifies_with_the_key_order_pinned(self) -> None:
        """``key_order`` was never passed, which disengages #1578's lock on the
        sealed-segment index rows inside the ceremony's own verification.

        By syntax tree, never by matching source text: the first version of this
        test scanned for the string ``tpm_key_resolver(`` and flagged the
        explanatory COMMENT in ``rotate()`` that names the removed call. A text
        scan on a claim about code reads prose as code.
        """
        import ast
        import inspect

        from shared.security import rotate_audit_key

        tree = ast.parse(inspect.getsource(rotate_audit_key.rotate))

        verifies = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "verify"
        ]
        assert len(verifies) == 2, (
            f"the ceremony should verify the chain twice, before and after the "
            f"rotation; found {len(verifies)} verify calls"
        )
        for call in verifies:
            kwargs = {kw.arg for kw in call.keywords}
            assert "key_order" in kwargs, (
                "a verify call in the ceremony does not pin the key order, so "
                "#1578's forged-index lock is disengaged inside the procedure "
                f"that exists to protect the chain. kwargs={sorted(kwargs)}"
            )
            assert "full" in kwargs, f"verify without full=True: {sorted(kwargs)}"

        built_own_ladder = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "tpm_key_resolver"
        ]
        assert not built_own_ladder, (
            "the ceremony builds its own key ladder again; there is one "
            "implementation, in shared/security/audit_verification.py"
        )
