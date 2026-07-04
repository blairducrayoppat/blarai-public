"""
Agentic JWT Minter — Policy Agent Exclusive
=============================================
USE-CASE-001, P1.5: Only the Policy Agent may mint Agentic JWTs.

Implements the full JWT lifecycle from Use Cases_FINAL.md (ISSUE-006):
  - Instance-scoped, single-use tokens bound to one adjudicated CAR.
  - 128-bit cryptographic nonce for replay prevention.
  - 5-second hard TTL (configurable for testing).
  - ES256 (ECDSA P-256) signing — non-exportable TPM key in production
    (ADR-021), in-memory/file-based key in dev.
  - Epoch-based lazy revocation propagation.

The JWT encodes the DecisionArtifact and is signed with the PA's
non-exportable TPM signing key (ADR-018/021); the private key never leaves
the TPM. All downstream services validate JWTs against the exported public
key using shared/crypto/jwt_validator.py.

Security:
  - Private key never leaves the TPM (production; ADR-021).
  - Dev mode uses ephemeral / file-based keys (clearly flagged).
  - No external network calls.
  - Fail-Closed: minting failures produce no token (request is blocked).
"""

from __future__ import annotations

import base64
import json
import logging
import os
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

from shared.schemas.car import DecisionArtifact
from shared.security import tpm_signer
from services.policy_agent.src.constants import JWT_ISSUER, JWT_VALIDITY_SECONDS

logger = logging.getLogger(__name__)


# ── Data Types ──────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class MintedJWT:
    """Result of JWT minting."""

    token: str
    """Encoded JWT string (empty on failure)."""

    success: bool
    """True if the token was minted successfully."""

    nonce: str = ""
    """128-bit hex nonce embedded in the token (32 hex chars)."""

    epoch: int = 0
    """Epoch value embedded in the token."""

    error: str | None = None
    """Error message if minting failed."""


# ── Epoch Manager ───────────────────────────────────────────────────────────


class EpochManager:
    """Manages the monotonically increasing epoch counter.

    Per Use Cases_FINAL.md — Epoch-Based Revocation (§5):
    - Initialized to 1 at boot.
    - Incremented atomically on any agent mTLS certificate revocation.
    - Every minted JWT includes the current epoch value in a custom ``epoch`` claim.
    - Destinations maintain ``last_seen_epoch`` and reject stale-epoch JWTs.
    """

    def __init__(self, initial_epoch: int = 1) -> None:
        self._epoch: int = max(1, initial_epoch)

    @property
    def current(self) -> int:
        """Current epoch value (monotonically increasing, minimum 1)."""
        return self._epoch

    def increment(self) -> int:
        """Atomically increment the epoch counter.

        Called when the PA revokes an agent's mTLS certificate.
        Returns the new epoch value.
        """
        self._epoch += 1
        logger.info("Epoch incremented to %d", self._epoch)
        return self._epoch


# ── TPM signing helpers (ADR-021) ────────────────────────────────────────────


def _b64url(data: bytes) -> str:
    """Base64url-encode without padding (JOSE convention)."""
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _to_jose_p256(signature: bytes) -> bytes:
    """Normalise an ECDSA P-256 signature to JOSE raw r‖s (64 bytes).

    Windows CNG / the TPM returns raw r‖s already; if a provider ever returns a
    DER-encoded signature instead, convert it. Verified on-chip, not assumed.
    """
    if len(signature) == 64:
        return signature
    from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature

    r, s = decode_dss_signature(signature)
    return r.to_bytes(32, "big") + s.to_bytes(32, "big")


# ── JWT Minter ──────────────────────────────────────────────────────────────


class AgenticJWTMinter:
    """Stateful ES256 JWT minter — Policy Agent exclusive.

    Orchestrates the full JWT minting pipeline per Use Cases_FINAL.md §1–§5:
      1. Generate 128-bit cryptographic nonce (``os.urandom``).
      2. Build claims payload from DecisionArtifact.
      3. Sign with ES256 (ECDSA P-256).
      4. Return :class:`MintedJWT` with all metadata.

    Fail-Closed: any exception during minting returns ``MintedJWT(success=False)``.
    """

    def __init__(
        self,
        private_key: ec.EllipticCurvePrivateKey | None = None,
        *,
        tpm_key_name: str | None = None,
        issuer: str = JWT_ISSUER,
        validity_seconds: int = JWT_VALIDITY_SECONDS,
        epoch_manager: EpochManager | None = None,
    ) -> None:
        # Exactly one signing backend: an in-memory key (dev/test) XOR a
        # non-exportable TPM key (production, ADR-021).
        if (private_key is None) == (tpm_key_name is None):
            raise ValueError(
                "AgenticJWTMinter requires exactly one of "
                "private_key (dev) or tpm_key_name (production TPM)"
            )
        self._private_key = private_key
        self._tpm_key_name = tpm_key_name
        self._issuer = issuer
        self._validity_seconds = validity_seconds
        self._epoch = epoch_manager or EpochManager()
        self._mint_count: int = 0

    # ── Factories ───────────────────────────────────────────────

    @classmethod
    def from_key_file(
        cls,
        key_path: str | Path,
        *,
        password: bytes | None = None,
        issuer: str = JWT_ISSUER,
        validity_seconds: int = JWT_VALIDITY_SECONDS,
        epoch_manager: EpochManager | None = None,
    ) -> AgenticJWTMinter | None:
        """Load a minter from a PEM-encoded ES256 private key file.

        Returns ``None`` if the key cannot be loaded (Fail-Closed).
        """
        try:
            key_data = Path(key_path).read_bytes()
            private_key = serialization.load_pem_private_key(key_data, password=None)
            if not isinstance(private_key, ec.EllipticCurvePrivateKey):
                logger.error("Key at %s is not an EC private key", key_path)
                return None
            return cls(
                private_key,
                issuer=issuer,
                validity_seconds=validity_seconds,
                epoch_manager=epoch_manager,
            )
        except Exception as exc:
            logger.error("Failed to load private key from %s: %s", key_path, exc)
            return None

    @classmethod
    def from_tpm(
        cls,
        tpm_key_name: str,
        *,
        issuer: str = JWT_ISSUER,
        validity_seconds: int = JWT_VALIDITY_SECONDS,
        epoch_manager: EpochManager | None = None,
    ) -> AgenticJWTMinter:
        """Build a minter that signs via the non-exportable TPM key ``tpm_key_name``.

        Production path (ADR-021). The private key never leaves the TPM; minting
        builds the JWT and signs the signing-input via
        ``shared.security.tpm_signer``. The key must already be provisioned (the
        provisioning ceremony); minting Fail-Closes if the key is absent.
        """
        return cls(
            tpm_key_name=tpm_key_name,
            issuer=issuer,
            validity_seconds=validity_seconds,
            epoch_manager=epoch_manager,
        )

    @staticmethod
    def generate_key_pair() -> tuple[ec.EllipticCurvePrivateKey, ec.EllipticCurvePublicKey]:
        """Generate a fresh ES256 (P-256) key pair for dev/testing.

        NOT for production — production keys are derived from Pluton.
        """
        private_key = ec.generate_private_key(ec.SECP256R1())
        return private_key, private_key.public_key()

    @staticmethod
    def save_key_pair(
        private_key: ec.EllipticCurvePrivateKey,
        private_path: str | Path,
        public_path: str | Path,
    ) -> None:
        """Save an ES256 key pair to PEM files.  Dev utility only."""
        Path(private_path).write_bytes(
            private_key.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.PKCS8,
                serialization.NoEncryption(),
            )
        )
        Path(public_path).write_bytes(
            private_key.public_key().public_bytes(
                serialization.Encoding.PEM,
                serialization.PublicFormat.SubjectPublicKeyInfo,
            )
        )

    # ── Properties ──────────────────────────────────────────────

    @property
    def mint_count(self) -> int:
        """Total number of JWTs minted by this instance."""
        return self._mint_count

    @property
    def epoch(self) -> int:
        """Current epoch value."""
        return self._epoch.current

    @property
    def epoch_manager(self) -> EpochManager:
        """Access the :class:`EpochManager` for revocation operations."""
        return self._epoch

    @property
    def issuer(self) -> str:
        """JWT issuer identity."""
        return self._issuer

    @property
    def validity_seconds(self) -> int:
        """JWT validity window in seconds."""
        return self._validity_seconds

    # ── Revocation (epoch bump) ─────────────────────────────────

    def revoke(self) -> int:
        """Revoke ALL outstanding tokens by advancing the epoch (#638).

        This is the runtime entry point for epoch-based revocation
        (Use Cases_FINAL.md §5). Every token already minted carries the *old*
        epoch in its ``epoch`` claim; once this bumps the counter, every
        subsequent mint stamps the new epoch, and any destination validator that
        has seen a new-epoch token rejects every prior-epoch token thereafter
        (``AgenticJWTValidator`` Stage 3 — stale epoch). Combined with the 5 s
        TTL, the worst-case window in which a pre-revocation token is still
        honoured is bounded by that lifetime.

        Intended callers: the operator's revoke-all control and the kill path
        (e.g. an agent-mTLS-certificate revocation, or an emergency
        de-authorization). Before #638 the only mechanism was
        ``EpochManager.increment`` with no runtime caller — the capability was
        built but wired into nothing; ``revoke()`` is that wiring.

        Returns the new (post-increment) epoch value.
        """
        new_epoch = self._epoch.increment()
        logger.warning(
            "Token revocation: epoch advanced to %d — all prior-epoch tokens "
            "are now invalid at destination validators.",
            new_epoch,
        )
        return new_epoch

    # ── Core Minting ────────────────────────────────────────────

    def mint(self, decision: DecisionArtifact) -> MintedJWT:
        """Mint an Agentic JWT from a :class:`DecisionArtifact`.

        Implements the full Use Cases_FINAL.md JWT lifecycle:

        1. Generate 128-bit cryptographic nonce (``os.urandom``).
        2. Build claims:  *iss, iat, exp, jti, nonce, epoch, car_hash,
           decision, request_id, deterministic_pass, probabilistic_pass,
           confidence*.
        3. Sign with ES256.
        4. Return :class:`MintedJWT` with metadata.

        Returns ``MintedJWT(success=False)`` on any error (Fail-Closed).
        """
        try:
            now = time.time()
            nonce = os.urandom(16).hex()  # 128-bit → 32 hex chars
            jti = str(uuid.uuid4())

            payload: dict[str, Any] = {
                # Standard JWT claims
                "iss": self._issuer,
                "iat": now,
                "exp": now + self._validity_seconds,
                "jti": jti,
                # Agentic JWT claims (Use Cases_FINAL.md §1–§5)
                "nonce": nonce,
                "epoch": self._epoch.current,
                "car_hash": decision.car_hash,
                "decision": decision.decision.value,
                "request_id": decision.request_id,
                "deterministic_pass": decision.deterministic_pass,
                "probabilistic_pass": decision.probabilistic_pass,
                "confidence": decision.confidence,
            }

            if self._tpm_key_name is not None:
                token = self._mint_tpm(payload)
            else:
                token = jwt.encode(
                    payload, self._private_key, algorithm="ES256"
                )
            self._mint_count += 1

            logger.info(
                "JWT minted: jti=%s car_hash=%s decision=%s epoch=%d",
                jti,
                decision.car_hash[:12],
                decision.decision.value,
                self._epoch.current,
            )

            return MintedJWT(
                token=token,
                success=True,
                nonce=nonce,
                epoch=self._epoch.current,
            )
        except Exception as exc:
            logger.error("JWT minting failed: %s", exc)
            return MintedJWT(
                token="",
                success=False,
                error=f"MINT_FAILED: {exc}",
            )

    def _mint_tpm(self, payload: dict[str, Any]) -> str:
        """Build and TPM-sign an ES256 JWT (production path, ADR-021).

        Constructs the JWS compact serialization by hand and signs the
        signing-input with the non-exportable TPM key. CNG's ECDSA-P256
        signature is the raw r‖s that JOSE ES256 expects (normalised defensively).
        """
        header = {"alg": "ES256", "typ": "JWT"}
        signing_input = (
            _b64url(json.dumps(header, separators=(",", ":")).encode("utf-8"))
            + "."
            + _b64url(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
        )
        raw_sig = tpm_signer.sign(self._tpm_key_name, signing_input.encode("ascii"))
        return signing_input + "." + _b64url(_to_jose_p256(raw_sig))


# ── Legacy Pure Function (backward compat with P1.0 stub) ──────────────────


def mint_agentic_jwt(
    decision: DecisionArtifact,
    private_key_path: str,
    issuer: str = JWT_ISSUER,
    validity_seconds: int = JWT_VALIDITY_SECONDS,
) -> MintedJWT:
    """Mint an Agentic JWT from a DecisionArtifact.

    Thin wrapper around :class:`AgenticJWTMinter` for backward compatibility.
    Loads the key from *private_key_path*, mints a single JWT, returns result.

    Args:
        decision: The adjudication decision to encode.
        private_key_path: Path to the PA's ES256 private key (PEM).
        issuer: JWT issuer claim.
        validity_seconds: Token validity window.

    Returns:
        :class:`MintedJWT`.  On any error, ``success`` is ``False`` (Fail-Closed).
    """
    minter = AgenticJWTMinter.from_key_file(
        private_key_path,
        issuer=issuer,
        validity_seconds=validity_seconds,
    )
    if minter is None:
        return MintedJWT(
            token="",
            success=False,
            error="MINT_FAILED: Could not load private key.",
        )
    return minter.mint(decision)
