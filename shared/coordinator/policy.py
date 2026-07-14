"""Signed policy verification — the out-of-process anchor (ADR-039 §2.2 control 7).

The forbidden-target set and the ``[coordinator]``/autonomy/policy config are the data
the whole boundary rests on. Control 7 makes a corrupted- or patched-on-disk policy
file *detected*, not trusted, by signature-verifying it at boot — **extending the
existing signed-manifest machinery (ADR-018 / weight-integrity) beyond model weights**.
This is the enforcement layer that does not depend on human code review, and the
control that (once its TPM-signed positive path is exercised) makes the boundary hold
for a non-technical operator, for whom the dev-channel write barrier does not
meaningfully exist (SG-review F1).

Reuse, not reinvention: this module calls
:func:`shared.models.manifest_signer.verify_manifest_signature` — which is already
model-agnostic ("signs ANY manifest path") — over the coordinator policy file's bytes,
under a DEDICATED signing key name. The signature machinery (TPM ECDSA P-256, detached
``.sig``, fail-closed on missing/invalid) is unchanged; only the file it protects is new.

**Dormant posture (mirrors ``require_signed_manifest``).** ``require_signed=False`` (the
default) permits an unsigned/absent policy file with a WARNING and falls back to the
compiled-in governed-core defaults — exactly as the weight manifest boots unsigned
today. A *present-but-invalid* signature is ALWAYS fail-closed (no silent downgrade).
``require_signed=True`` makes a missing/invalid signature a refuse-to-start. The
TPM-signed POSITIVE path (a real signature over the policy file) is an operator
provisioning ceremony, identical in status to the weight manifest's own signing today.

**The policy is signed, not encrypted** (ADR-039 §2.13.2): its content must be readable
to verify — only untamperable.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from shared.coordinator.config import (
    GovernedCoreRoots,
    PROTECTED_CONFIG_SECTIONS,
    default_governed_core_roots,
)

logger = logging.getLogger(__name__)

#: Dedicated TPM key name for the coordinator policy signature — distinct from the
#: weight-manifest key. Extends the ADR-018 machinery to a second protected artifact.
COORDINATOR_POLICY_SIGNING_KEY_NAME: Final[str] = "BlarAI-Coordinator-Policy-Signing"

#: The canonical policy filename (the operator stages + signs this via the C1 ceremony).
COORDINATOR_POLICY_FILENAME: Final[str] = "coordinator_policy.json"


@dataclass(frozen=True)
class PolicyVerificationResult:
    """The outcome of the boot-time policy-integrity check (control 7)."""

    verified: bool
    """True iff the policy is usable: either signature-verified, or (dormant path)
    unsigned-and-not-required. False is ALWAYS fail-closed → refuse-to-start."""

    policy: dict[str, Any] | None
    """The parsed, validated policy dict, or ``None`` when there is no policy file
    (dormant path — the compiled-in defaults are authoritative)."""

    signed: bool
    """True iff a signature was present AND verified. False on the unsigned-permitted
    dormant path (``verified`` may still be True) or on any failure."""

    error: str | None = None
    """A short, log-safe failure summary, or ``None`` on success."""


def _validate_policy_shape(data: Any) -> dict[str, Any] | None:
    """Validate the loaded policy JSON shape, or ``None`` if malformed (fail-closed).

    Accepted shape (all keys optional; unknown keys ignored)::

        {
          "version": "1.0.0",
          "governed_core_extra_roots": ["<abs path>", ...],
          "protected_config_sections": ["coordinator", ...]
        }

    A non-dict top level, or a listed-roots/sections value that is not a list of
    strings, is rejected (``None``)."""
    if not isinstance(data, dict):
        logger.error("coordinator policy: top level is not a JSON object (fail-closed)")
        return None
    for list_key in ("governed_core_extra_roots", "protected_config_sections"):
        if list_key in data:
            value = data[list_key]
            if not isinstance(value, list) or not all(
                isinstance(item, str) for item in value
            ):
                logger.error(
                    "coordinator policy: '%s' must be a list of strings (fail-closed)",
                    list_key,
                )
                return None
    return data


def load_policy_verified(
    policy_path: str | Path,
    *,
    require_signed: bool,
    key_name: str = COORDINATOR_POLICY_SIGNING_KEY_NAME,
) -> dict[str, Any] | None:
    """Load the coordinator policy file, TPM-signature-checked first (control 7).

    The signature-aware loader — the policy sibling of
    :func:`shared.models.weight_integrity.load_manifest_verified`. **Single-read
    (SG-review F5):** the policy bytes are read from disk EXACTLY ONCE; the signature
    is verified over those bytes and the SAME bytes are parsed. A write-capable local
    actor therefore cannot swap the file between a verify-read and a content-read to
    load a malicious policy under a signature that was valid over a benign one — nor
    craft a consistent (policy, sig) pair without the non-exportable TPM key.

    Returns the validated policy dict, or ``None`` on ANY failure (Fail-Closed):
    signature invalid; signature missing when ``require_signed=True``; unreadable/
    malformed JSON. When ``require_signed=False`` and no ``.sig`` exists, an unsigned
    policy is permitted (a WARNING is emitted — never silent)."""
    path = Path(policy_path)

    # Step 1: read the bytes ONCE. Verification AND parsing both operate on THESE bytes
    # (single-read TOCTOU defense — no second read the attacker could swap under us).
    try:
        raw_bytes = path.read_bytes()
    except OSError as exc:
        logger.error("coordinator policy: cannot read %s: %s (fail-closed)", path, exc)
        return None

    # Step 2: verify the detached signature over the EXACT bytes just read (reuses the
    # ADR-018 machinery, model-agnostic; the path only LOCATES the adjacent ``.sig``).
    from shared.models.manifest_signer import verify_manifest_signature

    if not verify_manifest_signature(
        path, require_signed=require_signed, key_name=key_name, manifest_bytes=raw_bytes
    ):
        logger.error(
            "coordinator policy signature verification failed; refusing policy: %s", path
        )
        return None

    # Step 3: parse + validate THOSE SAME bytes (fail-closed on any decode/parse/shape error).
    try:
        data = json.loads(raw_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        logger.error("coordinator policy: cannot parse %s: %s (fail-closed)", path, exc)
        return None
    return _validate_policy_shape(data)


def verify_policy_integrity(
    policy_path: str | Path | None,
    *,
    require_signed: bool,
    key_name: str = COORDINATOR_POLICY_SIGNING_KEY_NAME,
) -> PolicyVerificationResult:
    """Boot-time policy-integrity check (control 7). Fail-closed → refuse-to-start.

    Cases:
      * ``policy_path`` is ``None``/empty AND ``require_signed=False`` → the DORMANT
        path: no policy file, compiled-in defaults authoritative → ``verified=True,
        policy=None, signed=False`` (WARNING logged).
      * ``policy_path`` is ``None``/empty AND ``require_signed=True`` → refuse:
        signed policy required but none configured.
      * a path is given → load through :func:`load_policy_verified`; any failure →
        ``verified=False`` (refuse-to-start).

    Any unexpected exception is caught and returned as ``verified=False`` — a boundary
    check that errors must DENY."""
    try:
        if policy_path is None or (isinstance(policy_path, str) and not policy_path.strip()):
            if require_signed:
                return PolicyVerificationResult(
                    verified=False,
                    policy=None,
                    signed=False,
                    error="require_signed_policy=true but no policy_path configured",
                )
            logger.warning(
                "coordinator policy: no policy file configured and require_signed_policy="
                "false — proceeding on compiled-in governed-core defaults (unsigned)."
            )
            return PolicyVerificationResult(
                verified=True, policy=None, signed=False, error=None
            )

        path = Path(policy_path)
        sig_present = (path.parent / (path.name + ".sig")).exists()
        policy = load_policy_verified(
            path, require_signed=require_signed, key_name=key_name
        )
        if policy is None:
            return PolicyVerificationResult(
                verified=False,
                policy=None,
                signed=False,
                error=f"policy verification/load failed for {path}",
            )
        return PolicyVerificationResult(
            verified=True,
            policy=policy,
            signed=sig_present,
            error=None,
        )
    except Exception as exc:  # noqa: BLE001 — a boundary check that errors must DENY
        logger.error("coordinator policy integrity check raised: %s (fail-closed)", exc)
        return PolicyVerificationResult(
            verified=False,
            policy=None,
            signed=False,
            error=f"policy integrity check raised: {type(exc).__name__}",
        )


def resolve_governed_core_roots_from_policy(
    policy: dict[str, Any] | None,
    *,
    repo_root: str | Path | None = None,
    fleet_governance_root: str | Path | None = None,
    coordinator_store_root: str | Path | None = None,
) -> GovernedCoreRoots:
    """Build the governed-core roots, folding in any signed-policy ``extra_roots``.

    The compiled-in defaults (:func:`default_governed_core_roots`) are ALWAYS present;
    a verified policy may only ADD roots (``governed_core_extra_roots``), never remove
    one — the forbidden-target set can be widened by signed policy but the built-in
    core is never subtractable from inside (ADR-039 §2.2 control 1: config-defined but
    not modifiable via any BlarAI surface). A ``None`` policy (dormant path) yields the
    compiled-in defaults unchanged."""
    extra: tuple[str, ...] = ()
    if isinstance(policy, dict):
        raw = policy.get("governed_core_extra_roots", [])
        if isinstance(raw, list):
            extra = tuple(item for item in raw if isinstance(item, str) and item.strip())
    return default_governed_core_roots(
        repo_root=repo_root,
        fleet_governance_root=fleet_governance_root,
        coordinator_store_root=coordinator_store_root,
        extra_roots=extra,
    )


def resolve_protected_config_sections_from_policy(
    policy: dict[str, Any] | None,
) -> frozenset[str]:
    """Build the effective protected-config-section set, folding in a verified policy's
    ``protected_config_sections`` (control 4 + 7).

    Mirrors :func:`resolve_governed_core_roots_from_policy`: the compiled-in
    :data:`~shared.coordinator.config.PROTECTED_CONFIG_SECTIONS` are ALWAYS present; a
    verified policy may only ADD sections (case-normalised to lower), never remove a
    compiled-in one — the protected set is widenable by signed policy but never
    subtractable from inside (ADR-039 §2.2 control 4: config-defined but not modifiable
    via any BlarAI surface). A ``None`` policy (dormant path) yields the compiled-in
    defaults unchanged. This is the seam that CONSUMES the policy's
    ``protected_config_sections`` field — previously validated in
    :func:`_validate_policy_shape` but not yet honored (SG-review F5)."""
    sections: set[str] = set(PROTECTED_CONFIG_SECTIONS)
    if isinstance(policy, dict):
        raw = policy.get("protected_config_sections", [])
        if isinstance(raw, list):
            for item in raw:
                if isinstance(item, str) and item.strip():
                    sections.add(item.strip().lower())
    return frozenset(sections)
