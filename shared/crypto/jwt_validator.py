"""
Agentic JWT Validator — Shared Across All Services
====================================================
USE-CASE-001, P1.5: Policy Agent mints JWTs; all other services validate them.

Implements the 5-stage destination enforcement gate per Use Cases_FINAL.md §6:
  Stage 1: Signature verification (ES256 against PA public key).
  Stage 2: Expiry check (``exp`` claim vs. local clock).
  Stage 3: Epoch validation (``epoch`` claim vs. ``last_seen_epoch``).
  Stage 4: Nonce uniqueness (nonce-seen set with TTL GC — single-use enforcement).
  Stage 5: CAR hash match (JWT ``car_hash`` vs. presented request).

This module provides the VALIDATION side only.  JWT minting is exclusive
to the Policy Agent (services/policy_agent/src/jwt_minter.py).

Security:
  - Fail-Closed: missing, expired, invalid, or replayed JWTs reject.
  - No external network calls.
  - Single-use is enforced by the nonce-seen set; its TTL is aligned to the
    token validity (#638, ``aligned_nonce_ttl``) so the seen window always
    outlasts the token and no replay slips through a GC gap.
  - Memory: <1 MB at peak throughput per Use Cases_FINAL.md §7.
"""

from __future__ import annotations

import logging
import time
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import jwt
from cryptography.hazmat.primitives.serialization import load_pem_public_key
from cryptography.hazmat.primitives.asymmetric import ec

logger = logging.getLogger(__name__)


# ── Nonce Store ─────────────────────────────────────────────────────────────


class NonceStore:
    """Thread-safe nonce-seen set with TTL-based garbage collection.

    Per Use Cases_FINAL.md §2 (Nonce: Cryptographic, Non-Replayable):
    - Every destination maintains a nonce-seen set recording all nonces
      observed within the active TTL window.
    - Any JWT presenting a nonce that exists in the set is rejected.
    - The nonce-seen set is garbage-collected every TTL interval;
      expired entries are pruned deterministically.
    """

    def __init__(self, ttl_seconds: float = 5.0) -> None:
        self._ttl = ttl_seconds
        self._nonces: dict[str, float] = {}  # nonce → first-seen timestamp
        self._lock = threading.Lock()

    @property
    def ttl(self) -> float:
        """TTL window in seconds."""
        return self._ttl

    @property
    def size(self) -> int:
        """Number of nonces currently tracked (after GC)."""
        with self._lock:
            self._gc()
            return len(self._nonces)

    def check_and_add(self, nonce: str) -> bool:
        """Check if *nonce* is unseen and add it.

        Returns ``True`` if accepted (first occurrence).
        Returns ``False`` if replay detected (nonce already seen within TTL).
        """
        with self._lock:
            self._gc()
            if nonce in self._nonces:
                return False  # Replay detected
            self._nonces[nonce] = time.monotonic()
            return True

    def clear(self) -> None:
        """Remove all tracked nonces."""
        with self._lock:
            self._nonces.clear()

    # ── Internal ────────────────────────────────────────────────

    def _gc(self) -> None:
        """Remove expired nonces (older than TTL)."""
        cutoff = time.monotonic() - self._ttl
        expired = [n for n, ts in self._nonces.items() if ts < cutoff]
        for n in expired:
            del self._nonces[n]


# ── Nonce-TTL / validity alignment (#638) ────────────────────────────────────

# Clock-skew safety margin added to the token validity when sizing the
# nonce-seen set's TTL (#638). The single-use guarantee depends on the
# nonce-seen window covering the token's ENTIRE live span: if a nonce were
# GC'd while the token were still inside its ``exp``, a replay in that gap
# would forget the nonce yet pass the expiry check — the 5–30 s replay window
# this fix closes. We make ``nonce_ttl = validity + margin`` so the window can
# never be shorter than the token's life even across modest host clock skew
# between minter and validator. The margin is small and fixed; it only widens
# the seen-set retention (strictly safe), never shortens it.
NONCE_TTL_SKEW_MARGIN_SECONDS: float = 2.0


def aligned_nonce_ttl(validity_seconds: float) -> float:
    """Return the nonce-seen-set TTL that safely covers *validity_seconds* (#638).

    ``nonce_ttl >= validity`` is the invariant that keeps single-use
    enforcement airtight (see :data:`NONCE_TTL_SKEW_MARGIN_SECONDS`). Tying the
    two together here — rather than letting each be configured independently —
    is what stops them drifting apart again (the bug was a 5 s nonce TTL under a
    30 s validity).
    """
    return float(validity_seconds) + NONCE_TTL_SKEW_MARGIN_SECONDS


# ── Epoch Tracker ───────────────────────────────────────────────────────────


class EpochTracker:
    """Tracks ``last_seen_epoch`` for epoch-based lazy revocation.

    Per Use Cases_FINAL.md §5 (Epoch-Based Revocation):
    - Each destination maintains a ``last_seen_epoch`` value.
    - Upon receiving a JWT, the destination updates ``last_seen_epoch``
      to the JWT's epoch if it is greater than the stored value.
    - Any subsequent JWT presenting an epoch older than
      ``last_seen_epoch`` is rejected regardless of signature validity.
    """

    def __init__(self, initial_epoch: int = 0) -> None:
        self._last_seen: int = initial_epoch

    @property
    def last_seen_epoch(self) -> int:
        """Current ``last_seen_epoch`` value."""
        return self._last_seen

    def validate_and_update(self, jwt_epoch: int) -> bool:
        """Validate *jwt_epoch* and update tracker.

        Returns ``True`` if the epoch is valid (>= last seen).
        Returns ``False`` if the epoch is stale (< last seen — revocation).
        """
        if jwt_epoch < self._last_seen:
            return False  # Stale epoch — revocation has occurred
        if jwt_epoch > self._last_seen:
            self._last_seen = jwt_epoch
        return True


# ── Validation Result ───────────────────────────────────────────────────────


@dataclass(frozen=True)
class JWTValidationResult:
    """Result of validating an Agentic JWT."""

    valid: bool
    """Whether the JWT passed all 5 validation stages."""

    car_hash: str
    """CAR hash extracted from the JWT payload."""

    decision: str
    """Adjudication decision: ALLOW / DENY / ESCALATE."""

    request_id: str
    """Correlating request identifier."""

    claims: dict[str, Any] = field(default_factory=dict)
    """Full decoded claims payload (populated on success)."""

    error: str | None = None
    """Human-readable error if validation failed."""


# ── JWT Validator ───────────────────────────────────────────────────────────


class AgenticJWTValidator:
    """Stateful ES256 JWT validator — used by all destination services.

    Implements the 5-stage destination enforcement gate from
    Use Cases_FINAL.md §6.  Every check is executed in strict order;
    the gate short-circuits on the first failure.

    Fail-Closed: any validation failure returns
    ``JWTValidationResult(valid=False)``.
    """

    def __init__(
        self,
        public_key: ec.EllipticCurvePublicKey,
        *,
        expected_issuer: str = "policy_agent",
        validity_seconds: float = 5.0,
        nonce_store: NonceStore | None = None,
        epoch_tracker: EpochTracker | None = None,
    ) -> None:
        self._public_key = public_key
        self._expected_issuer = expected_issuer
        self._validity_seconds = float(validity_seconds)
        # Nonce-seen set sized to OUTLAST the token (#638). When the caller does
        # not inject a store, derive its TTL from the token validity via
        # ``aligned_nonce_ttl`` so ``nonce_ttl >= validity`` always holds — the
        # invariant that keeps single-use enforcement airtight. (The historic
        # bug: the validator took the bare ``NonceStore()`` 5 s default while
        # tokens were valid for 30 s, GC-forgetting a nonce 25 s before the
        # token expired and opening a replay window. An explicitly injected
        # store is trusted as-is — tests and bespoke callers own their sizing.)
        self._nonce_store = nonce_store or NonceStore(
            ttl_seconds=aligned_nonce_ttl(self._validity_seconds)
        )
        self._epoch_tracker = epoch_tracker or EpochTracker()
        self._validation_count: int = 0
        self._rejection_count: int = 0

    # ── Factory ─────────────────────────────────────────────────

    @classmethod
    def from_public_key_file(
        cls,
        key_path: str | Path,
        **kwargs: Any,
    ) -> AgenticJWTValidator | None:
        """Load a validator from a PEM-encoded EC public key file.

        Pass ``validity_seconds`` (kwarg) so the nonce-seen set is sized to
        outlast the token; defaults to 5 s (Use Cases_FINAL.md §3) when omitted.

        Returns ``None`` if the key cannot be loaded (Fail-Closed).
        """
        try:
            key_data = Path(key_path).read_bytes()
            public_key = load_pem_public_key(key_data)
            if not isinstance(public_key, ec.EllipticCurvePublicKey):
                logger.error("Key at %s is not an EC public key", key_path)
                return None
            return cls(public_key, **kwargs)
        except Exception as exc:
            logger.error("Failed to load public key from %s: %s", key_path, exc)
            return None

    # ── Properties ──────────────────────────────────────────────

    @property
    def validation_count(self) -> int:
        """Total number of validate() calls (pass or fail)."""
        return self._validation_count

    @property
    def rejection_count(self) -> int:
        """Number of failed validations."""
        return self._rejection_count

    @property
    def nonce_store(self) -> NonceStore:
        """Access the :class:`NonceStore` for inspection/testing."""
        return self._nonce_store

    @property
    def validity_seconds(self) -> float:
        """Token validity this validator's nonce-seen set is sized to outlast (#638)."""
        return self._validity_seconds

    @property
    def epoch_tracker(self) -> EpochTracker:
        """Access the :class:`EpochTracker` for inspection/testing."""
        return self._epoch_tracker

    # ── Core Validation ─────────────────────────────────────────

    def _fail(self, error: str) -> JWTValidationResult:
        """Return a Fail-Closed rejection result."""
        self._rejection_count += 1
        logger.warning("JWT validation failed: %s", error)
        return JWTValidationResult(
            valid=False,
            car_hash="",
            decision="DENY",
            request_id="",
            error=error,
        )

    def validate(
        self,
        token: str,
        expected_car_hash: str | None = None,
    ) -> JWTValidationResult:
        """Validate an Agentic JWT through the 5-stage gate.

        Stages (strict order — short-circuit on first failure):
          1. **Signature verification** — ES256 decode against PA public key.
          2. **Expiry check** — ``exp`` claim vs. local clock.
          3. **Epoch validation** — ``epoch`` claim vs. ``last_seen_epoch``.
          4. **Nonce uniqueness** — nonce-seen set check (single-use; #638
             aligns the seen-set TTL to the token validity).
          5. **CAR hash match** — JWT ``car_hash`` vs. *expected_car_hash*.

        Returns :class:`JWTValidationResult`.  Never raises.
        """
        self._validation_count += 1

        # ── Stage 1 + 2: Signature verification + Expiry ───────
        # PyJWT handles both: sig check and exp validation in decode().
        try:
            claims: dict[str, Any] = jwt.decode(
                token,
                self._public_key,
                algorithms=["ES256"],
                issuer=self._expected_issuer,
                options={
                    "require": [
                        "exp", "iat", "iss", "jti",
                        "nonce", "epoch", "car_hash",
                    ],
                },
            )
        except jwt.ExpiredSignatureError:
            return self._fail("EXPIRED: Token has expired.")
        except jwt.InvalidIssuerError:
            return self._fail("ISSUER: Invalid issuer claim.")
        except jwt.MissingRequiredClaimError as exc:
            return self._fail(f"MISSING_CLAIM: {exc}")
        except jwt.InvalidSignatureError:
            return self._fail("SIGNATURE: Invalid token signature.")
        except jwt.DecodeError as exc:
            return self._fail(f"DECODE: {exc}")
        except Exception as exc:
            return self._fail(f"UNEXPECTED: {exc}")

        # ── Stage 3: Epoch validation ──────────────────────────
        jwt_epoch = claims.get("epoch")
        if jwt_epoch is None or not isinstance(jwt_epoch, int):
            return self._fail("EPOCH: Missing or invalid epoch claim.")
        if not self._epoch_tracker.validate_and_update(jwt_epoch):
            return self._fail(
                f"EPOCH: Stale epoch {jwt_epoch} "
                f"< last_seen {self._epoch_tracker.last_seen_epoch}."
            )

        # ── Stage 4: Nonce uniqueness (single-use enforcement) ─
        # The token's single-use property is enforced here: every token carries
        # a unique 128-bit nonce, so a replay = a nonce already in the seen set
        # = rejected. The seen-set TTL is sized to outlast the token (#638,
        # ``aligned_nonce_ttl``) so the nonce cannot be GC-forgotten while the
        # token is still inside its ``exp`` — that gap was the replay window.
        nonce = claims.get("nonce")
        if not nonce or not isinstance(nonce, str):
            return self._fail("NONCE: Missing or invalid nonce claim.")
        if not self._nonce_store.check_and_add(nonce):
            return self._fail("NONCE: Replay detected — nonce already seen.")

        # ── Stage 5: CAR hash match ────────────────────────────
        car_hash: str = claims.get("car_hash", "")
        if expected_car_hash is not None and car_hash != expected_car_hash:
            return self._fail(
                f"CAR_HASH: Mismatch — expected {expected_car_hash[:12]}…, "
                f"got {car_hash[:12]}…"
            )

        # ── All 5 stages passed ────────────────────────────────
        decision = claims.get("decision", "DENY")
        request_id = claims.get("request_id", "")

        logger.info(
            "JWT validated: jti=%s car_hash=%s decision=%s epoch=%d",
            claims.get("jti", "?"),
            car_hash[:12],
            decision,
            jwt_epoch,
        )

        return JWTValidationResult(
            valid=True,
            car_hash=car_hash,
            decision=decision,
            request_id=request_id,
            claims=claims,
        )


# ── Legacy Pure Function (backward compat with P1.0 stub) ──────────────────


def validate_agentic_jwt(
    token: str,
    ca_cert_path: str,
    expected_car_hash: str | None = None,
) -> JWTValidationResult:
    """Validate an Agentic JWT issued by the Policy Agent.

    Thin wrapper around :class:`AgenticJWTValidator` for backward
    compatibility.  Loads the public key from *ca_cert_path*, validates
    a single JWT, returns the result.

    Args:
        token: The raw JWT string.
        ca_cert_path: Path to the Policy Agent CA public key (PEM).
        expected_car_hash: If provided, the JWT's ``car_hash`` must match.

    Returns:
        :class:`JWTValidationResult`.  Never raises — returns
        ``valid=False`` on any failure (Fail-Closed).
    """
    validator = AgenticJWTValidator.from_public_key_file(ca_cert_path)
    if validator is None:
        return JWTValidationResult(
            valid=False,
            car_hash="",
            decision="DENY",
            request_id="",
            error="VALIDATION_FAILED: Could not load public key.",
        )
    return validator.validate(token, expected_car_hash)
