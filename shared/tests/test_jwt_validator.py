"""
P1.5 Tests — Agentic JWT Validator
====================================
Groups:
  A. TestNonceStore             — TTL-based nonce-seen set (7 tests)
  B. TestEpochTracker           — lazy revocation tracking (5 tests)
  C. TestJWTValidationResult    — frozen dataclass properties (3 tests)
  D. TestValidatorProperties    — construction, factory (4 tests)
  E. TestValidation5StageGate   — each stage can fail independently (9 tests)
  F. TestEndToEndMintValidate   — round-trip mint → validate (8 tests)
  G. TestEpochRevocation        — epoch-based revocation scenarios (4 tests)
  H. TestLegacyValidateFunction — backward compat pure function (3 tests)
  I. TestNonceTtlAlignment      — #638: nonce-seen TTL is sized >= token validity
  J. TestReplayWithinValidity   — #638: replay inside the live window is rejected
  K. TestRevokeEndToEnd         — #638: revoke() → prior-epoch token rejected
"""

from __future__ import annotations

import os
import tempfile
import time
from dataclasses import FrozenInstanceError
from pathlib import Path

import jwt as pyjwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

from shared.crypto.jwt_validator import (
    NONCE_TTL_SKEW_MARGIN_SECONDS,
    AgenticJWTValidator,
    EpochTracker,
    JWTValidationResult,
    NonceStore,
    aligned_nonce_ttl,
    validate_agentic_jwt,
)
from shared.tests._keygen import (
    AgenticJWTMinter,
    EpochManager,
    MintedJWT,
)
from shared.schemas.car import (
    AdjudicationDecision,
    CanonicalActionRepresentation,
    DecisionArtifact,
    Sensitivity,
)


# ── Helpers ─────────────────────────────────────────────────────────────────


def _make_decision(
    *,
    decision: AdjudicationDecision = AdjudicationDecision.ALLOW,
    confidence: float = 0.90,
    request_id: str = "req-val-001",
) -> DecisionArtifact:
    car = CanonicalActionRepresentation(
        source_agent="assistant_orchestrator",
        destination_service="substrate",
        verb="READ",
        resource="substrate.vector_store",
        sensitivity=Sensitivity.INTERNAL,
        request_id=request_id,
    )
    return DecisionArtifact(
        car_hash=car.canonical_hash(),
        decision=decision,
        request_id=car.request_id,
        deterministic_pass=True,
        probabilistic_pass=True,
        confidence=confidence,
    )


def _gen_key_pair() -> tuple[ec.EllipticCurvePrivateKey, ec.EllipticCurvePublicKey]:
    return AgenticJWTMinter.generate_key_pair()


def _make_minter_and_validator(
    *,
    validity_seconds: int = 60,
    nonce_store: NonceStore | None = None,
    epoch_tracker: EpochTracker | None = None,
    epoch_manager: EpochManager | None = None,
) -> tuple[AgenticJWTMinter, AgenticJWTValidator]:
    """Create a matched minter/validator pair sharing the same key pair."""
    priv, pub = _gen_key_pair()
    minter = AgenticJWTMinter(
        priv,
        validity_seconds=validity_seconds,
        epoch_manager=epoch_manager,
    )
    validator = AgenticJWTValidator(
        pub,
        nonce_store=nonce_store or NonceStore(ttl_seconds=60.0),
        epoch_tracker=epoch_tracker or EpochTracker(),
    )
    return minter, validator


# ═══════════════════════════════════════════════════════════════════════════
# Group A: TestNonceStore
# ═══════════════════════════════════════════════════════════════════════════


class TestNonceStore:
    """TTL-based nonce-seen set."""

    def test_accept_new_nonce(self) -> None:
        ns = NonceStore(ttl_seconds=60.0)
        assert ns.check_and_add("nonce-1") is True

    def test_reject_replay(self) -> None:
        ns = NonceStore(ttl_seconds=60.0)
        ns.check_and_add("nonce-1")
        assert ns.check_and_add("nonce-1") is False

    def test_accept_different_nonces(self) -> None:
        ns = NonceStore(ttl_seconds=60.0)
        assert ns.check_and_add("a") is True
        assert ns.check_and_add("b") is True

    def test_size(self) -> None:
        ns = NonceStore(ttl_seconds=60.0)
        ns.check_and_add("x")
        ns.check_and_add("y")
        assert ns.size == 2

    def test_clear(self) -> None:
        ns = NonceStore(ttl_seconds=60.0)
        ns.check_and_add("x")
        ns.clear()
        assert ns.size == 0
        # After clear, same nonce should be accepted again
        assert ns.check_and_add("x") is True

    def test_ttl_property(self) -> None:
        ns = NonceStore(ttl_seconds=10.0)
        assert ns.ttl == 10.0

    def test_gc_removes_expired(self) -> None:
        """Nonces older than TTL are garbage-collected."""
        ns = NonceStore(ttl_seconds=0.1)  # 100ms TTL
        ns.check_and_add("ephemeral")
        time.sleep(0.15)
        # After TTL expiry, nonce should be GC'd and re-accepted
        assert ns.check_and_add("ephemeral") is True


# ═══════════════════════════════════════════════════════════════════════════
# Group B: TestEpochTracker
# ═══════════════════════════════════════════════════════════════════════════


class TestEpochTracker:
    """Lazy revocation tracking."""

    def test_initial_value(self) -> None:
        et = EpochTracker()
        assert et.last_seen_epoch == 0

    def test_valid_epoch_accepted(self) -> None:
        et = EpochTracker()
        assert et.validate_and_update(1) is True
        assert et.last_seen_epoch == 1

    def test_same_epoch_accepted(self) -> None:
        et = EpochTracker()
        et.validate_and_update(5)
        assert et.validate_and_update(5) is True

    def test_higher_epoch_updates(self) -> None:
        et = EpochTracker()
        et.validate_and_update(3)
        et.validate_and_update(7)
        assert et.last_seen_epoch == 7

    def test_stale_epoch_rejected(self) -> None:
        et = EpochTracker()
        et.validate_and_update(5)
        assert et.validate_and_update(3) is False


# ═══════════════════════════════════════════════════════════════════════════
# Group C: TestJWTValidationResult
# ═══════════════════════════════════════════════════════════════════════════


class TestJWTValidationResult:
    """Frozen dataclass properties."""

    def test_valid_result(self) -> None:
        r = JWTValidationResult(
            valid=True,
            car_hash="abc123",
            decision="ALLOW",
            request_id="req-1",
            claims={"iss": "pa"},
        )
        assert r.valid is True
        assert r.claims["iss"] == "pa"

    def test_invalid_result(self) -> None:
        r = JWTValidationResult(
            valid=False, car_hash="", decision="DENY", request_id="",
            error="BAD",
        )
        assert r.valid is False
        assert r.error == "BAD"

    def test_frozen_immutable(self) -> None:
        r = JWTValidationResult(
            valid=True, car_hash="", decision="ALLOW", request_id="",
        )
        with pytest.raises(FrozenInstanceError):
            r.valid = False  # type: ignore[misc]


# ═══════════════════════════════════════════════════════════════════════════
# Group D: TestValidatorProperties
# ═══════════════════════════════════════════════════════════════════════════


class TestValidatorProperties:
    """Construction and factory."""

    def test_initial_counts_zero(self) -> None:
        _, v = _make_minter_and_validator()
        assert v.validation_count == 0
        assert v.rejection_count == 0

    def test_nonce_store_accessible(self) -> None:
        ns = NonceStore(ttl_seconds=30.0)
        _, v = _make_minter_and_validator(nonce_store=ns)
        assert v.nonce_store is ns

    def test_epoch_tracker_accessible(self) -> None:
        et = EpochTracker(initial_epoch=5)
        _, v = _make_minter_and_validator(epoch_tracker=et)
        assert v.epoch_tracker.last_seen_epoch == 5

    def test_from_public_key_file(self) -> None:
        priv, pub = _gen_key_pair()
        tmp = tempfile.NamedTemporaryFile(suffix=".pem", delete=False)
        try:
            tmp.write(
                pub.public_bytes(
                    serialization.Encoding.PEM,
                    serialization.PublicFormat.SubjectPublicKeyInfo,
                )
            )
            tmp.close()
            v = AgenticJWTValidator.from_public_key_file(tmp.name)
            assert v is not None
        finally:
            os.unlink(tmp.name)


# ═══════════════════════════════════════════════════════════════════════════
# Group E: TestValidation5StageGate — each stage can fail independently
# ═══════════════════════════════════════════════════════════════════════════


class TestValidation5StageGate:
    """5-stage destination enforcement gate."""

    def test_stage1_bad_signature_rejected(self) -> None:
        """Token signed with wrong key → signature failure."""
        priv_a, _ = _gen_key_pair()
        _, pub_b = _gen_key_pair()
        minter = AgenticJWTMinter(priv_a, validity_seconds=60)
        validator = AgenticJWTValidator(
            pub_b,
            nonce_store=NonceStore(ttl_seconds=60.0),
        )
        token = minter.mint(_make_decision()).token
        result = validator.validate(token)
        assert result.valid is False
        assert "SIGNATURE" in (result.error or "")

    def test_stage1_garbage_token_rejected(self) -> None:
        _, v = _make_minter_and_validator()
        result = v.validate("not.a.jwt")
        assert result.valid is False
        assert "DECODE" in (result.error or "")

    def test_stage1_empty_token_rejected(self) -> None:
        _, v = _make_minter_and_validator()
        result = v.validate("")
        assert result.valid is False

    def test_stage2_expired_token_rejected(self) -> None:
        """Token with 0-second validity → already expired."""
        priv, pub = _gen_key_pair()
        minter = AgenticJWTMinter(priv, validity_seconds=0)
        validator = AgenticJWTValidator(
            pub, nonce_store=NonceStore(ttl_seconds=60.0),
        )
        # Mint with 0s TTL — by the time we validate, it's expired.
        token = minter.mint(_make_decision()).token
        time.sleep(0.05)  # small sleep to ensure exp is in the past
        result = validator.validate(token)
        assert result.valid is False
        assert "EXPIRED" in (result.error or "")

    def test_stage3_stale_epoch_rejected(self) -> None:
        """Token with epoch < last_seen → revocation detected."""
        m, v = _make_minter_and_validator(
            epoch_tracker=EpochTracker(initial_epoch=10),
            epoch_manager=EpochManager(initial_epoch=5),
        )
        token = m.mint(_make_decision()).token
        result = v.validate(token)
        assert result.valid is False
        assert "EPOCH" in (result.error or "")

    def test_stage4_replay_nonce_rejected(self) -> None:
        """Same token presented twice → nonce replay."""
        m, v = _make_minter_and_validator()
        token = m.mint(_make_decision()).token
        first = v.validate(token)
        assert first.valid is True
        second = v.validate(token)
        assert second.valid is False
        assert "NONCE" in (second.error or "")

    def test_stage5_car_hash_mismatch_rejected(self) -> None:
        """Token's car_hash doesn't match expected → CAR mismatch."""
        m, v = _make_minter_and_validator()
        decision = _make_decision()
        token = m.mint(decision).token
        result = v.validate(token, expected_car_hash="wrong_hash_value")
        assert result.valid is False
        assert "CAR_HASH" in (result.error or "")

    def test_stage1_wrong_issuer_rejected(self) -> None:
        """Token signed by wrong issuer."""
        priv, pub = _gen_key_pair()
        minter = AgenticJWTMinter(priv, issuer="evil_agent", validity_seconds=60)
        validator = AgenticJWTValidator(
            pub,
            expected_issuer="policy_agent",
            nonce_store=NonceStore(ttl_seconds=60.0),
        )
        token = minter.mint(_make_decision()).token
        result = validator.validate(token)
        assert result.valid is False
        assert "ISSUER" in (result.error or "")

    def test_rejection_count_increments(self) -> None:
        _, v = _make_minter_and_validator()
        v.validate("bad1")
        v.validate("bad2")
        assert v.rejection_count == 2
        assert v.validation_count == 2


# ═══════════════════════════════════════════════════════════════════════════
# Group F: TestEndToEndMintValidate — round-trip
# ═══════════════════════════════════════════════════════════════════════════


class TestEndToEndMintValidate:
    """Full mint → validate round-trip."""

    def test_valid_token_passes_all_stages(self) -> None:
        m, v = _make_minter_and_validator()
        decision = _make_decision()
        minted = m.mint(decision)
        result = v.validate(minted.token)
        assert result.valid is True
        assert result.car_hash == decision.car_hash
        assert result.decision == "ALLOW"
        assert result.request_id == "req-val-001"
        assert result.error is None

    def test_allow_decision_propagates(self) -> None:
        m, v = _make_minter_and_validator()
        r = v.validate(m.mint(_make_decision(decision=AdjudicationDecision.ALLOW)).token)
        assert r.decision == "ALLOW"

    def test_deny_decision_propagates(self) -> None:
        m, v = _make_minter_and_validator()
        r = v.validate(m.mint(_make_decision(decision=AdjudicationDecision.DENY)).token)
        assert r.decision == "DENY"

    def test_escalate_decision_propagates(self) -> None:
        m, v = _make_minter_and_validator()
        r = v.validate(m.mint(_make_decision(decision=AdjudicationDecision.ESCALATE)).token)
        assert r.decision == "ESCALATE"

    def test_car_hash_matches_with_expected(self) -> None:
        m, v = _make_minter_and_validator()
        decision = _make_decision()
        token = m.mint(decision).token
        result = v.validate(token, expected_car_hash=decision.car_hash)
        assert result.valid is True

    def test_claims_populated_on_success(self) -> None:
        m, v = _make_minter_and_validator()
        token = m.mint(_make_decision()).token
        result = v.validate(token)
        assert "nonce" in result.claims
        assert "epoch" in result.claims
        assert "jti" in result.claims
        assert result.claims["confidence"] == pytest.approx(0.90, abs=0.001)

    def test_multiple_mints_validate_independently(self) -> None:
        m, v = _make_minter_and_validator()
        tokens = [m.mint(_make_decision(request_id=f"req-{i}")).token for i in range(5)]
        results = [v.validate(t) for t in tokens]
        assert all(r.valid for r in results)
        # Check request_ids are different
        req_ids = {r.request_id for r in results}
        assert len(req_ids) == 5

    def test_nonce_unique_across_mints(self) -> None:
        m, v = _make_minter_and_validator()
        minted = [m.mint(_make_decision(request_id=f"req-{i}")) for i in range(10)]
        nonces = {mt.nonce for mt in minted}
        assert len(nonces) == 10


# ═══════════════════════════════════════════════════════════════════════════
# Group G: TestEpochRevocation — epoch-based revocation scenarios
# ═══════════════════════════════════════════════════════════════════════════


class TestEpochRevocation:
    """Epoch-based lazy revocation per Use Cases_FINAL.md §5."""

    def test_epoch_propagates_to_validator(self) -> None:
        em = EpochManager(initial_epoch=3)
        m, v = _make_minter_and_validator(epoch_manager=em)
        token = m.mint(_make_decision()).token
        result = v.validate(token)
        assert result.valid is True
        assert v.epoch_tracker.last_seen_epoch == 3

    def test_pre_revocation_token_fails_after_epoch_advance(self) -> None:
        """After epoch advances, tokens with old epoch are rejected."""
        em = EpochManager(initial_epoch=1)
        m, v = _make_minter_and_validator(epoch_manager=em)

        # Mint at epoch 1
        token_epoch1 = m.mint(_make_decision(request_id="r1")).token
        # Validate it → tracker advances to 1
        r1 = v.validate(token_epoch1)
        assert r1.valid is True

        # Advance epoch (simulate revocation)
        em.increment()  # epoch → 2

        # Mint at epoch 2 and validate → tracker advances to 2
        token_epoch2 = m.mint(_make_decision(request_id="r2")).token
        r2 = v.validate(token_epoch2)
        assert r2.valid is True
        assert v.epoch_tracker.last_seen_epoch == 2

        # Now try a token minted at epoch 1 (pre-revocation)
        # We need a fresh token at epoch 1, but epoch is now 2.
        # Instead, test that tracker rejects epoch < last_seen directly.
        assert v.epoch_tracker.validate_and_update(1) is False

    def test_new_epoch_tokens_accepted(self) -> None:
        em = EpochManager(initial_epoch=1)
        m, v = _make_minter_and_validator(epoch_manager=em)
        em.increment()
        em.increment()  # epoch → 3
        token = m.mint(_make_decision()).token
        result = v.validate(token)
        assert result.valid is True
        assert v.epoch_tracker.last_seen_epoch == 3

    def test_lazy_propagation(self) -> None:
        """Destinations only learn about new epochs via JWT receipt."""
        em = EpochManager(initial_epoch=1)
        m, v = _make_minter_and_validator(epoch_manager=em)

        # Validator hasn't seen any epoch yet (initial 0)
        assert v.epoch_tracker.last_seen_epoch == 0

        # First JWT at epoch 1 → lazy propagation
        v.validate(m.mint(_make_decision(request_id="r1")).token)
        assert v.epoch_tracker.last_seen_epoch == 1

        # Advance epoch
        em.increment()  # → 2
        # Validator still at 1 until next JWT arrives
        assert v.epoch_tracker.last_seen_epoch == 1

        # Next JWT at epoch 2 → lazy propagation
        v.validate(m.mint(_make_decision(request_id="r2")).token)
        assert v.epoch_tracker.last_seen_epoch == 2


# ═══════════════════════════════════════════════════════════════════════════
# Group H: TestLegacyValidateFunction
# ═══════════════════════════════════════════════════════════════════════════


class TestLegacyValidateFunction:
    """Backward compat ``validate_agentic_jwt()`` pure function."""

    def test_with_valid_key_file(self) -> None:
        priv, pub = _gen_key_pair()
        minter = AgenticJWTMinter(priv, validity_seconds=60)
        token = minter.mint(_make_decision()).token

        tmp = tempfile.NamedTemporaryFile(suffix=".pem", delete=False)
        try:
            tmp.write(
                pub.public_bytes(
                    serialization.Encoding.PEM,
                    serialization.PublicFormat.SubjectPublicKeyInfo,
                )
            )
            tmp.close()
            result = validate_agentic_jwt(token, tmp.name)
            assert result.valid is True
        finally:
            os.unlink(tmp.name)

    def test_with_bad_path_fail_closed(self) -> None:
        result = validate_agentic_jwt("some.token", "/nonexistent.pem")
        assert result.valid is False
        assert result.error is not None

    def test_with_bad_key_content_fail_closed(self) -> None:
        tmp = tempfile.NamedTemporaryFile(suffix=".pem", delete=False)
        try:
            tmp.write(b"not a real PEM key")
            tmp.close()
            result = validate_agentic_jwt("some.token", tmp.name)
            assert result.valid is False
        finally:
            os.unlink(tmp.name)


# ═══════════════════════════════════════════════════════════════════════════
# Group I: TestNonceTtlAlignment — #638: nonce-seen TTL sized >= token validity
# ═══════════════════════════════════════════════════════════════════════════


class TestNonceTtlAlignment:
    """The nonce-seen window must OUTLAST the token (#638).

    The single-use guarantee depends on the nonce-seen set still remembering a
    nonce for the token's whole live span. If the seen-set TTL were shorter than
    the validity (the historic 5 s nonce default under a 30 s token), a replay
    in the gap would forget the nonce yet still pass the expiry check — the
    replay window this fix closes. The fix ties the two together via
    ``aligned_nonce_ttl`` and threads the validity through the validator.
    """

    def test_aligned_nonce_ttl_exceeds_validity(self) -> None:
        for validity in (5.0, 30.0, 0.5, 300.0):
            assert aligned_nonce_ttl(validity) >= validity
            assert aligned_nonce_ttl(validity) == validity + NONCE_TTL_SKEW_MARGIN_SECONDS

    def test_validator_default_store_outlasts_validity(self) -> None:
        # When no nonce_store is injected, the validator derives the TTL from
        # the validity it is told — so nonce_ttl >= validity always holds.
        priv, pub = _gen_key_pair()
        v = AgenticJWTValidator(pub, validity_seconds=30.0)
        assert v.nonce_store.ttl >= v.validity_seconds
        assert v.nonce_store.ttl == aligned_nonce_ttl(30.0)

    def test_default_validity_is_5s_window(self) -> None:
        # The default validator (no validity passed) is sized for the 5 s spec
        # token, NOT the bare 5 s NonceStore default that ignored validity.
        priv, pub = _gen_key_pair()
        v = AgenticJWTValidator(pub)
        assert v.validity_seconds == 5.0
        assert v.nonce_store.ttl == aligned_nonce_ttl(5.0)

    def test_injected_store_is_respected(self) -> None:
        # An explicitly injected store is trusted as-is (tests/bespoke callers
        # own their sizing); alignment only governs the DEFAULT store.
        priv, pub = _gen_key_pair()
        custom = NonceStore(ttl_seconds=123.0)
        v = AgenticJWTValidator(pub, validity_seconds=30.0, nonce_store=custom)
        assert v.nonce_store is custom
        assert v.nonce_store.ttl == 123.0


# ═══════════════════════════════════════════════════════════════════════════
# Group J: TestReplayWithinValidity — #638: replay inside live window rejected
# ═══════════════════════════════════════════════════════════════════════════


class TestReplayWithinValidity:
    """A token replayed while still live is rejected by the nonce stage (#638).

    These exercise the single-use guarantee end-to-end and pin the exact
    regression: the seen window must cover the token's live span. The
    ``test_*_old_default_would_have_leaked`` case reproduces the historic bug
    deterministically with small TTLs — a bare 5 s-style nonce store GCs the
    nonce while the token is still valid, whereas the aligned store does not.
    """

    def test_replayed_token_rejected(self) -> None:
        # The same token, presented twice inside its validity, is rejected the
        # second time — single-use enforced by the nonce stage.
        m, v = _make_minter_and_validator()  # validity 60 s, aligned store
        token = m.mint(_make_decision()).token

        first = v.validate(token)
        assert first.valid is True, first.error

        second = v.validate(token)
        assert second.valid is False
        assert second.error is not None
        assert second.error.startswith("NONCE:")

    def test_replay_rejected_across_the_old_5s_boundary(self) -> None:
        # Regression for the 5–30 s window: mint a token that stays valid well
        # past 5 s, with the nonce store aligned to that validity. A replay
        # after a delay LONGER than the old 5 s nonce default must still be
        # rejected (the aligned window has not lapsed). Uses sub-second scaling
        # to stay fast: validity 1.0 s, store aligned to it; replay at 0.15 s,
        # which would have been GC'd by a hypothetical 0.1 s store.
        priv, pub = _gen_key_pair()
        minter = AgenticJWTMinter(priv, validity_seconds=60)  # token stays live
        # Aligned store keyed to a 1.0 s "validity" → TTL = 1.0 + margin.
        aligned = NonceStore(ttl_seconds=aligned_nonce_ttl(1.0))
        v = AgenticJWTValidator(pub, nonce_store=aligned)
        token = minter.mint(_make_decision()).token

        assert v.validate(token).valid is True
        time.sleep(0.15)  # past a 0.1 s window, well inside the aligned one
        replay = v.validate(token)
        assert replay.valid is False
        assert replay.error is not None
        assert replay.error.startswith("NONCE:")

    def test_old_default_would_have_leaked(self) -> None:
        # Demonstrates the BUG the fix removes: a too-short nonce store forgets
        # the nonce while the token is still live, so a replay slips through.
        # This is the failure mode the alignment prevents; asserting it here
        # documents WHY the alignment is load-bearing (and guards the helper —
        # if aligned_nonce_ttl ever returned < validity this contrast breaks).
        priv, pub = _gen_key_pair()
        minter = AgenticJWTMinter(priv, validity_seconds=60)  # token stays live
        too_short = NonceStore(ttl_seconds=0.1)               # the OLD bug shape
        v = AgenticJWTValidator(pub, nonce_store=too_short)
        token = minter.mint(_make_decision()).token

        assert v.validate(token).valid is True
        time.sleep(0.15)  # nonce GC'd, but token still valid (60 s)
        leaked = v.validate(token)
        assert leaked.valid is True  # REPLAY ACCEPTED — exactly the #638 gap

    def test_distinct_tokens_both_accepted(self) -> None:
        # Two different mints → two different nonces → both accepted.
        m, v = _make_minter_and_validator()
        r1 = v.validate(m.mint(_make_decision(request_id="r1")).token)
        r2 = v.validate(m.mint(_make_decision(request_id="r2")).token)
        assert r1.valid is True and r2.valid is True


# ═══════════════════════════════════════════════════════════════════════════
# Group K: TestRevokeEndToEnd — #638: revoke() → prior-epoch token rejected
# ═══════════════════════════════════════════════════════════════════════════


class TestRevokeEndToEnd:
    """``revoke()`` invalidates all prior-epoch tokens at the validator (#638).

    End-to-end exercise of the real revoke-all entry point: a token minted
    before ``revoke()`` is rejected once the validator has seen a post-revoke
    (higher-epoch) token. The held token is otherwise fully valid (fresh nonce,
    unexpired) so the rejection isolates the epoch stage.
    """

    def test_prior_epoch_token_rejected_after_revoke(self) -> None:
        em = EpochManager(initial_epoch=1)
        m, v = _make_minter_and_validator(epoch_manager=em)

        # Mint a token at epoch 1 and HOLD it (do not validate yet).
        held_token = m.mint(_make_decision(request_id="held")).token

        # Operator/kill-path revokes: epoch advances 1 → 2.
        new_epoch = m.revoke()
        assert new_epoch == 2

        # A fresh post-revoke token validates and advances the tracker to 2.
        fresh = v.validate(m.mint(_make_decision(request_id="fresh")).token)
        assert fresh.valid is True
        assert v.epoch_tracker.last_seen_epoch == 2

        # The held epoch-1 token is now stale → rejected on the epoch stage,
        # even though its signature/expiry/nonce are all still valid.
        result = v.validate(held_token)
        assert result.valid is False
        assert result.error is not None
        assert result.error.startswith("EPOCH:")

    def test_pre_revoke_token_still_valid_before_validator_sees_new_epoch(self) -> None:
        # Lazy propagation: revoke() bumps the minter epoch, but a validator
        # that has NOT yet seen a higher-epoch token still accepts the old one
        # (Use Cases_FINAL.md §5 — destinations learn epochs lazily via receipt).
        em = EpochManager(initial_epoch=1)
        m, v = _make_minter_and_validator(epoch_manager=em)
        held_token = m.mint(_make_decision(request_id="held")).token
        m.revoke()  # epoch → 2, but validator has seen nothing yet
        result = v.validate(held_token)
        assert result.valid is True  # accepted: tracker was at 0, epoch 1 >= 0
