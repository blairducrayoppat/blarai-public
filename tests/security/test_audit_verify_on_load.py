"""#1543 / Gap D: a chain that does not verify is REFUSED, not extended.

Claim-register row 29: ``AuditLog.verify()`` walked the chain and checked every signature,
and its only callers were test files.  ``_load_existing`` restored the chain head from the
last record on disk without recomputing a hash or checking a signature, and neither
production constructor verified.  The chain was tamper-EVIDENT — a later ``verify()`` would
have caught the edit — but not tamper-REFUSING: a tampered active segment would have been
appended to.

Every lock here drives the REAL production constructors, dev AND production arms both -- the
first version of this file covered only dev, which is how review finding 1 shipped green.  A mock of the constructor would
prove only that ``verify()`` works, which was never in doubt; what was in doubt is whether
anything on the live path CALLS it.

Each control ships with its toggle-test (security_by_design principle 12): a probe that
passes only because the control is reachable is indistinguishable from a probe that cannot
reach the control at all, so the off-case is asserted explicitly.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from services.policy_agent.src.entrypoint import PolicyAgentService
from shared.security.audit_log import (
    AuditChainError,
    AuditLog,
    AuditProvisioningError,
    HmacSha256Signer,
)

_CONFIG = """
[runtime]
deployment_mode = "host"

[inference]
device = "GPU"
model_dir = "models/qwen3-14b/openvino-int4-gpu"
weight_manifest = "models/qwen3-14b/openvino-int4-gpu/manifest.json"
draft_model_dir = "models/qwen3-0.6b/openvino-int4-gpu"
speculative_decoding_enabled = true

[security]
dev_mode = true

[jwt]
issuer = "policy_agent"
validity_seconds = 5

[ipc]
vsock_cid = 2
vsock_port = 5000
timeout_ms = 5000
max_message_bytes = 65536
""".strip()


def _resolved(tmp_path: Path):
    """Resolve a real PA config, exactly as the boot path does."""
    config_path = tmp_path / "services" / "policy_agent" / "config" / "default.toml"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(_CONFIG, encoding="utf-8")
    service = PolicyAgentService(config_path)
    return service._load_entrypoint_config()


def _dev_signer(audit_path: Path) -> HmacSha256Signer:
    """The signer the real dev-mode constructor builds, derived the same way.

    ``_build_audit_log`` derives its dev key from the audit path, so a chain seeded
    with any other key fails verification on a KEY MISMATCH rather than on tampering.
    That is not a distinction a passing test would surface: the refusal cases below
    would still pass, for the wrong reason, and the toggle-test would assert the
    pre-#1543 path rejects a chain it should have accepted.  The baseline case is
    what catches it, which is the reason the baseline case exists.
    """
    import hashlib

    key = hashlib.sha256(
        b"BlarAI-audit-hmac-stub-v1::" + str(audit_path).encode("utf-8")
    ).digest()
    return HmacSha256Signer(key=key)


def _seed_chain(audit_path: Path, records: int = 3) -> None:
    """Write a genuine, well-formed chain through the real AuditLog append path."""
    log = AuditLog.from_path(audit_path, _dev_signer(audit_path))
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
    # The seeded chain must be genuinely valid, or every lock below passes for
    # the wrong reason.
    log.verify()


def _tamper_active_segment(audit_path: Path) -> None:
    """Flip one field of one record in the ACTIVE segment, leaving valid JSON.

    This is the motivating case from the ticket: the sealed-segment case is caught
    independently by the signed anchor pin, but the ACTIVE segment had nothing
    checking it at all.
    """
    lines = audit_path.read_text(encoding="utf-8").splitlines()
    record = json.loads(lines[-1])
    record["resource"] = "tool:something_the_operator_never_approved"
    lines[-1] = json.dumps(record)
    audit_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


class TestTamperedChainIsRefused:
    """The chain is refused rather than extended."""

    def test_untampered_chain_constructs(self, tmp_path: Path) -> None:
        """Baseline: a genuine chain opens through the real constructor.

        Without this, a refusal test proves nothing — a constructor that refused
        everything would pass the tamper cases too.
        """
        resolved = _resolved(tmp_path)
        assert resolved.audit_log_path is not None
        _seed_chain(resolved.audit_log_path)

        log = PolicyAgentService._build_audit_log(resolved)

        assert log is not None
        assert isinstance(log, AuditLog)

    def test_tampered_ACTIVE_segment_is_refused(self, tmp_path: Path) -> None:
        """THE LOCK. One edited byte in the active segment and the PA refuses to start."""
        resolved = _resolved(tmp_path)
        assert resolved.audit_log_path is not None
        _seed_chain(resolved.audit_log_path)
        _tamper_active_segment(resolved.audit_log_path)

        with pytest.raises(AuditProvisioningError) as caught:
            PolicyAgentService._build_audit_log(resolved)

        assert "failed verification" in str(caught.value).lower()
        assert isinstance(caught.value.__cause__, AuditChainError)

    def test_tampered_chain_opens_when_the_check_is_REMOVED(self, tmp_path: Path) -> None:
        """TOGGLE-TEST: with verification bypassed, the same tampered chain opens.

        This is what makes the lock above meaningful.  It reproduces the pre-#1543
        behaviour exactly — construct through ``AuditLog.from_path`` with no
        ``verify()`` call, which is what both production constructors used to do —
        and asserts the tampered chain is accepted and its head restored.

        If this test ever starts failing, the tamper case above has stopped being
        evidence: it would mean the chain is being rejected somewhere other than
        the control this ticket added.
        """
        resolved = _resolved(tmp_path)
        assert resolved.audit_log_path is not None
        _seed_chain(resolved.audit_log_path)
        _tamper_active_segment(resolved.audit_log_path)

        # The pre-#1543 construction path: load, restore the head, verify nothing.
        log = AuditLog.from_path(
            resolved.audit_log_path, _dev_signer(resolved.audit_log_path)
        )

        assert log is not None, "the tampered chain must open when nothing verifies it"
        with pytest.raises(AuditChainError):
            log.verify()

    def test_refusal_names_the_path(self, tmp_path: Path) -> None:
        """FAIL-LOUD: the refusal says which chain failed, not just that one did."""
        resolved = _resolved(tmp_path)
        assert resolved.audit_log_path is not None
        _seed_chain(resolved.audit_log_path)
        _tamper_active_segment(resolved.audit_log_path)

        with pytest.raises(AuditProvisioningError) as caught:
            PolicyAgentService._build_audit_log(resolved)

        assert str(resolved.audit_log_path) in str(caught.value)


class TestProductionBranchIsAlsoLocked:
    """The PRODUCTION branch refuses too — the arm whose absence hid review finding 1.

    Every other lock in this file resolves through `_CONFIG`, which sets
    `dev_mode = true`. The first version of this change left the production branch as
    its own early `return AuditLog.from_path(...)` with the verify below it, so the
    control ran in dev and nowhere in production — and every test here passed, because
    not one of them entered that branch. The file's docstring claimed it drove "the REAL
    production constructors"; it drove the real constructor *function* on the dev path.

    These locks enter the production branch. The TPM is stubbed — an HMAC signer with
    the same key material seeds and verifies — because what is under test is
    REACHABILITY of the check, not the chip. Signature correctness on real hardware is
    `shared/tests/test_tpm_record_signer.py`'s job.
    """

    @staticmethod
    def _production_resolved(tmp_path: Path):
        import dataclasses

        return dataclasses.replace(_resolved(tmp_path), dev_mode=False)

    @staticmethod
    def _stub_tpm(monkeypatch: pytest.MonkeyPatch, audit_path: Path) -> None:
        """Make the production branch constructible without a chip."""
        from services.policy_agent.src import entrypoint as pa_entrypoint

        signer = _dev_signer(audit_path)
        monkeypatch.setattr(pa_entrypoint.tpm_signer, "key_exists", lambda _name: True)
        monkeypatch.setattr(pa_entrypoint, "TpmRecordSigner", lambda **_kw: signer)

    def test_production_untampered_chain_constructs(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Baseline for the production arm — without it the refusal below proves nothing."""
        resolved = self._production_resolved(tmp_path)
        assert resolved.audit_log_path is not None
        _seed_chain(resolved.audit_log_path)
        self._stub_tpm(monkeypatch, resolved.audit_log_path)

        assert PolicyAgentService._build_audit_log(resolved) is not None

    def test_production_tampered_chain_is_REFUSED(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """THE LOCK THAT WAS MISSING. Production refuses a tampered chain.

        This test FAILED against the first version of this change — the production
        branch returned before the verify was reached, so a tampered chain constructed
        cleanly. That is the regression this locks.
        """
        resolved = self._production_resolved(tmp_path)
        assert resolved.audit_log_path is not None
        _seed_chain(resolved.audit_log_path)
        _tamper_active_segment(resolved.audit_log_path)
        self._stub_tpm(monkeypatch, resolved.audit_log_path)

        with pytest.raises(AuditProvisioningError) as caught:
            PolicyAgentService._build_audit_log(resolved)

        assert isinstance(caught.value.__cause__, AuditChainError)

    def test_production_constructed_log_carries_the_clamped_ceiling(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The clamp reaches the CONSTRUCTED LOG, not merely the kwargs dict.

        The previous ceiling tests asserted on `_audit_retention_kwargs`' return value,
        which proves the dict is right and says nothing about what the log received.
        """
        from shared.security.audit_log import PRODUCTION_MAX_ACTIVE_RECORDS

        resolved = self._production_resolved(tmp_path)
        assert resolved.audit_log_path is not None
        _seed_chain(resolved.audit_log_path)
        self._stub_tpm(monkeypatch, resolved.audit_log_path)

        log = PolicyAgentService._build_audit_log(resolved)

        assert log is not None
        assert log._max_active_records == PRODUCTION_MAX_ACTIVE_RECORDS


class TestIngestConstructorIsLocked:
    """The Assistant Orchestrator's ingest chain refuses too.

    Review finding 3: the AO half of this change had ZERO coverage. Neutering its
    `verify()` produced no test failure anywhere in the suite. It is the half that
    worked, and it was the half nothing locked — so a later refactor could have removed
    it silently.
    """

    @staticmethod
    def _ingest_path(local_root: Path) -> Path:
        return local_root / "BlarAI" / "audit" / "ingest_audit.jsonl"

    @staticmethod
    def _ingest_signer(audit_path: Path) -> HmacSha256Signer:
        """The key `_build_ingest_audit_log` derives for its dev branch."""
        import hashlib

        return HmacSha256Signer(
            key=hashlib.sha256(
                b"BlarAI-ingest-audit-hmac-stub-v1::" + str(audit_path).encode("utf-8")
            ).digest()
        )

    def _seed(self, local_root: Path) -> Path:
        audit_path = self._ingest_path(local_root)
        audit_path.parent.mkdir(parents=True, exist_ok=True)
        log = AuditLog.from_path(audit_path, self._ingest_signer(audit_path))
        log.append(
            adjudication_id="3e6b1f9a-0000-4000-8000-000000000001",
            decision="ALLOW",
            car_hash="0" * 64,
            source_agent="ui_gateway",
            destination_service="assistant_orchestrator",
            verb="INGEST_SUBMIT",
            resource="doc|abcd",
            sensitivity="INTERNAL",
            rule_engine_passed=True,
            confidence=1.0,
        )
        log.verify()
        return audit_path

    def _build(self, local_root: Path):
        from services.assistant_orchestrator.src.entrypoint import AssistantOrchestratorService

        return AssistantOrchestratorService._build_ingest_audit_log(
            dev_mode=True, local_root=str(local_root)
        )

    def test_untampered_ingest_chain_constructs(self, tmp_path: Path) -> None:
        """Baseline — the refusal test below is meaningless without it."""
        self._seed(tmp_path)
        assert self._build(tmp_path) is not None

    def test_tampered_ingest_chain_is_REFUSED(self, tmp_path: Path) -> None:
        """THE LOCK. A tampered ingest chain is refused, not extended."""
        audit_path = self._seed(tmp_path)
        _tamper_active_segment(audit_path)

        with pytest.raises(AuditProvisioningError) as caught:
            self._build(tmp_path)

        assert "failed verification" in str(caught.value).lower()
        assert isinstance(caught.value.__cause__, AuditChainError)

    def test_in_memory_branch_still_constructs(self, tmp_path: Path) -> None:
        """An empty local_root yields an in-memory chain with nothing to verify.

        Asserted so that a future change which starts verifying there — or which stops
        returning a usable log — is caught rather than discovered in a test context.
        """
        from services.assistant_orchestrator.src.entrypoint import AssistantOrchestratorService

        log = AssistantOrchestratorService._build_ingest_audit_log(
            dev_mode=True, local_root=""
        )
        assert log is not None


class TestTamperedSealedSegmentIsRefused:
    """A rotated, sealed segment is covered too — by the signed anchor, not by a re-walk."""

    def _seed_rotated_chain(self, audit_path: Path) -> Path:
        """Force a rotation so a sealed segment exists, and return its path."""
        signer = _dev_signer(audit_path)
        log = AuditLog.from_path(audit_path, signer, max_active_records=2)
        for i in range(5):
            log.append(
                adjudication_id=f"2e6b1f9a-0000-4000-8000-00000000000{i}",
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
        log.verify()

        sealed = sorted(audit_path.parent.glob("audit-*.jsonl.gz"))
        assert sealed, (
            "no sealed segment was produced — the rotation this lock depends on did "
            "not happen, so a pass here would prove nothing"
        )
        return sealed[0]

    def test_tampered_sealed_segment_is_refused(self, tmp_path: Path) -> None:
        """Corrupt a sealed segment's bytes; the anchor SHA-256 catches it on load."""
        resolved = _resolved(tmp_path)
        assert resolved.audit_log_path is not None
        sealed = self._seed_rotated_chain(resolved.audit_log_path)

        blob = bytearray(sealed.read_bytes())
        blob[-1] ^= 0xFF  # one flipped byte, still a file, no longer the signed one
        sealed.write_bytes(bytes(blob))

        with pytest.raises(AuditProvisioningError) as caught:
            PolicyAgentService._build_audit_log(resolved)

        assert isinstance(caught.value.__cause__, AuditChainError)

    def test_rotated_untampered_chain_still_constructs(self, tmp_path: Path) -> None:
        """Baseline for the sealed case: rotation alone must not trip the refusal."""
        resolved = _resolved(tmp_path)
        assert resolved.audit_log_path is not None
        self._seed_rotated_chain(resolved.audit_log_path)

        assert PolicyAgentService._build_audit_log(resolved) is not None


class TestProductionCeilingIsApplied:
    """The production record ceiling reaches the constructed log."""

    def test_dev_mode_keeps_the_adr_029_default(self, tmp_path: Path) -> None:
        """Dev/CI is not clamped — the reduction exists to bound TPM cost."""
        from shared.security.audit_log import DEFAULT_MAX_ACTIVE_RECORDS

        resolved = _resolved(tmp_path)
        kwargs = PolicyAgentService._audit_retention_kwargs(resolved)

        assert kwargs["max_active_records"] == DEFAULT_MAX_ACTIVE_RECORDS

    def test_production_clamps_the_ceiling(self, tmp_path: Path) -> None:
        """Production clamps to the verifiable ceiling even when config asks for more."""
        import dataclasses

        from shared.security.audit_log import (
            DEFAULT_MAX_ACTIVE_RECORDS,
            PRODUCTION_MAX_ACTIVE_RECORDS,
        )

        resolved = dataclasses.replace(
            _resolved(tmp_path),
            dev_mode=False,
            audit_max_active_records=DEFAULT_MAX_ACTIVE_RECORDS,
        )
        kwargs = PolicyAgentService._audit_retention_kwargs(resolved)

        assert kwargs["max_active_records"] == PRODUCTION_MAX_ACTIVE_RECORDS

    def test_production_does_not_RAISE_a_lower_operator_ceiling(self, tmp_path: Path) -> None:
        """The clamp is a ceiling, not an assignment.

        An operator who asks for a SMALLER active segment gets it; clamping upward
        would be the control overriding a stricter choice than its own.
        """
        import dataclasses

        resolved = dataclasses.replace(
            _resolved(tmp_path), dev_mode=False, audit_max_active_records=50
        )
        kwargs = PolicyAgentService._audit_retention_kwargs(resolved)

        assert kwargs["max_active_records"] == 50


class TestTheFaultClassReachesTheOperator:
    """#1569 review finding 3: the classification was wired and locked by NOTHING.

    Deleting the fault class and guidance from both entrypoints left the whole suite
    green. That is the third occurrence of one shape in one sprint — #1543's review
    found the AO half uncovered, and the note recording it lives in this very file.

    These drive the REAL constructors, because a test asserting on a hand-built string
    would certify the formatting and not the wiring.
    """

    def test_pa_refusal_names_the_fault_class_and_the_remedy(self, tmp_path: Path) -> None:
        resolved = _resolved(tmp_path)
        assert resolved.audit_log_path is not None
        _seed_chain(resolved.audit_log_path)
        _tamper_active_segment(resolved.audit_log_path)

        with pytest.raises(AuditProvisioningError) as caught:
            PolicyAgentService._build_audit_log(resolved)

        message = str(caught.value)
        assert "tamper" in message, (
            "the PA refusal does not name the fault class — an operator cannot tell a "
            "tampered chain from a rotated key, which is the whole of #1569"
        )
        assert "forensics" in message.lower(), (
            "the TAMPER remedy is missing from the refusal the operator actually sees"
        )

    def test_ao_refusal_names_the_fault_class_and_the_remedy(self, tmp_path: Path) -> None:
        import hashlib

        audit_path = tmp_path / "BlarAI" / "audit" / "ingest_audit.jsonl"
        audit_path.parent.mkdir(parents=True, exist_ok=True)
        signer = HmacSha256Signer(
            key=hashlib.sha256(
                b"BlarAI-ingest-audit-hmac-stub-v1::" + str(audit_path).encode("utf-8")
            ).digest()
        )
        log = AuditLog.from_path(audit_path, signer)
        log.append(
            adjudication_id="4e6b1f9a-0000-4000-8000-000000000001",
            decision="ALLOW", car_hash="0" * 64, source_agent="ui_gateway",
            destination_service="assistant_orchestrator", verb="INGEST_SUBMIT",
            resource="doc|abcd", sensitivity="INTERNAL",
            rule_engine_passed=True, confidence=1.0,
        )
        log.verify()
        _tamper_active_segment(audit_path)

        from services.assistant_orchestrator.src.entrypoint import (
            AssistantOrchestratorService,
        )

        with pytest.raises(AuditProvisioningError) as caught:
            AssistantOrchestratorService._build_ingest_audit_log(
                dev_mode=True, local_root=str(tmp_path)
            )

        message = str(caught.value)
        assert "tamper" in message
        assert "forensics" in message.lower()
