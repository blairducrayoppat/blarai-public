"""Boot-time boundary canary + refuse-to-start (ADR-039 §2.2 control 6, §2.14.6).

At every backend boot, a deterministic self-check probes that the coordinator surface
**cannot** reach a governed-core write path (the OpenParallax canary pattern). Any
probe finding a forbidden path *reachable* means misconfiguration, and the coordinator
**refuses to start** — the same fail-closed idiom the egress guard already uses
(``shared/security/egress_guard.py``). This composes the other controls into one boot
gate:

  * **Negative probes (control 1 + 4)** — seed the host's ACTUAL governed-core paths
    (the repo root, the fleet governance root, the coordinator store root, this
    module's own file, protected config sections + files) and assert the boundary
    REFUSES every one. A seeded governed-core target that is NOT refused is the
    misconfiguration this canary exists to catch → refuse-to-start.
  * **Positive probe (§2.14.6, the paired half)** — assert a legitimate workspace
    target IS allowed. Control 6 alone (prove the negative) could be satisfied by a
    check that denies EVERYTHING; the positive probe proves the allowed path still
    works, so the boundary is a *fence*, not a wall.
  * **Policy-integrity probe (control 7)** — the signed policy verifies (or the
    dormant unsigned path is permitted). A tampered policy file → refuse-to-start.

**Fail-closed.** Any exception anywhere in the canary resolves to ``ok=False``
(refuse-to-start) — a boundary check that errors must DENY, never allow.

**Dormant.** Nothing calls this at boot yet; C1 (`#843`) wires it into the backend
entry point alongside the egress guard's ``arm()``. Constructing and running it here
changes no live behavior.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from shared.coordinator.config import (
    CoordinatorConfig,
    GovernedCoreRoots,
)
from shared.coordinator.governed_core import (
    BoundaryDecision,
    SelfGovernanceBoundaryError,
    check_config_write,
    check_target,
)
from shared.coordinator.policy import verify_policy_integrity

logger = logging.getLogger(__name__)

#: The synthetic workspace target the positive probe uses (a name that will not exist
#: and is never written) — proves the boundary ALLOWS a legitimate workspace target.
_POSITIVE_PROBE_REPO: str = "_sg_boundary_positive_probe_"

#: Protected config sections the control-4 negative probes seed (must all be DENIED).
_CONFIG_SECTION_PROBES: tuple[str, ...] = ("coordinator", "security", "policy")


@dataclass(frozen=True)
class CanaryProbe:
    """One boot-canary probe outcome."""

    name: str
    kind: str  # "negative-target" | "negative-config" | "positive-target" | "policy"
    passed: bool
    detail: str


@dataclass(frozen=True)
class CanaryResult:
    """The aggregate boot-canary verdict."""

    ok: bool
    """True iff the coordinator may start — every probe passed AND policy verified."""

    probes: tuple[CanaryProbe, ...]
    error: str | None = None

    def failures(self) -> tuple[CanaryProbe, ...]:
        return tuple(p for p in self.probes if not p.passed)


def _negative_target_probes(
    roots: GovernedCoreRoots, projects_dir: str | Path
) -> list[CanaryProbe]:
    """Seed the host's real governed-core paths; each MUST be denied (control 1)."""
    seeds: list[tuple[str, Path]] = []
    seeds.append(("repo_root", roots.repo_root))
    if roots.fleet_governance_root is not None:
        seeds.append(("fleet_governance_root", roots.fleet_governance_root))
    if roots.coordinator_store_root is not None:
        seeds.append(("coordinator_store_root", roots.coordinator_store_root))
    for extra in roots.extra_roots:
        seeds.append(("policy_extra_root", extra))
    # This module's own file is unambiguously governed core (it lives in the repo).
    seeds.append(("self_module_file", Path(__file__)))

    probes: list[CanaryProbe] = []
    for name, seed in seeds:
        verdict = check_target(
            seed, roots=roots, projects_dir=projects_dir, phase="BOOT_CANARY"
        )
        denied = verdict.decision is BoundaryDecision.DENY
        probes.append(
            CanaryProbe(
                name=f"governed-core-denied:{name}",
                kind="negative-target",
                passed=denied,
                detail=(
                    f"seeded governed-core target {seed} correctly DENIED"
                    if denied
                    else f"MISCONFIGURATION: governed-core target {seed} was NOT "
                    f"denied ({verdict.reason})"
                ),
            )
        )
    return probes


def _negative_config_probes(roots: GovernedCoreRoots) -> list[CanaryProbe]:
    """Seed protected config writes; each MUST be denied (control 4)."""
    probes: list[CanaryProbe] = []
    for section in _CONFIG_SECTION_PROBES:
        verdict = check_config_write(section=section, roots=roots)
        denied = verdict.decision is BoundaryDecision.DENY
        probes.append(
            CanaryProbe(
                name=f"config-section-denied:{section}",
                kind="negative-config",
                passed=denied,
                detail=(
                    f"protected config section [{section}] correctly DENIED"
                    if denied
                    else f"MISCONFIGURATION: config section [{section}] was NOT denied"
                ),
            )
        )
    # A config FILE path inside the governed core must also be denied.
    config_file = roots.repo_root / "services" / "assistant_orchestrator" / "config" / "default.toml"
    verdict = check_config_write(target_path=config_file, roots=roots)
    denied = verdict.decision is BoundaryDecision.DENY
    probes.append(
        CanaryProbe(
            name="config-file-denied:default.toml",
            kind="negative-config",
            passed=denied,
            detail=(
                "protected config file default.toml correctly DENIED"
                if denied
                else "MISCONFIGURATION: config file default.toml was NOT denied"
            ),
        )
    )
    return probes


def _positive_target_probe(
    roots: GovernedCoreRoots, projects_dir: str | Path
) -> CanaryProbe:
    """A legitimate workspace target MUST be allowed (§2.14.6 — prove the fence works)."""
    target = Path(projects_dir) / _POSITIVE_PROBE_REPO
    verdict = check_target(
        target, roots=roots, projects_dir=projects_dir, phase="BOOT_CANARY"
    )
    allowed = verdict.decision is BoundaryDecision.ALLOW
    return CanaryProbe(
        name="workspace-target-allowed",
        kind="positive-target",
        passed=allowed,
        detail=(
            f"legitimate workspace target {target} correctly ALLOWED"
            if allowed
            else f"OVER-DENY: legitimate workspace target {target} was denied "
            f"({verdict.reason}) — boundary is a wall, not a fence"
        ),
    )


def _policy_probe(config: CoordinatorConfig) -> CanaryProbe:
    """The signed policy verifies, or the dormant unsigned path is permitted (control 7)."""
    result = verify_policy_integrity(
        config.policy_path or None, require_signed=config.require_signed_policy
    )
    return CanaryProbe(
        name="signed-policy-verified",
        kind="policy",
        passed=result.verified,
        detail=(
            f"policy integrity OK (signed={result.signed})"
            if result.verified
            else f"policy integrity FAILED: {result.error}"
        ),
    )


def run_boot_canary(
    *,
    config: CoordinatorConfig,
    roots: GovernedCoreRoots,
    projects_dir: str | Path,
) -> CanaryResult:
    """Run every boundary probe and return the aggregate verdict (control 6).

    Fail-closed: any exception → ``ok=False`` (refuse-to-start). ``ok`` is True only
    when EVERY negative probe correctly denied, the positive probe correctly allowed,
    and the policy-integrity probe verified."""
    try:
        probes: list[CanaryProbe] = []
        probes.extend(_negative_target_probes(roots, projects_dir))
        probes.extend(_negative_config_probes(roots))
        probes.append(_positive_target_probe(roots, projects_dir))
        probes.append(_policy_probe(config))
        ok = all(p.passed for p in probes)
        if not ok:
            for probe in probes:
                if not probe.passed:
                    logger.error("boot canary FAIL [%s]: %s", probe.name, probe.detail)
        return CanaryResult(ok=ok, probes=tuple(probes), error=None)
    except Exception as exc:  # noqa: BLE001 — a boundary check that errors must DENY
        logger.error("boot canary raised: %s (refuse-to-start, fail-closed)", exc)
        return CanaryResult(
            ok=False,
            probes=(),
            error=f"boot canary raised: {type(exc).__name__}",
        )


def assert_boot_boundary(
    *,
    config: CoordinatorConfig,
    roots: GovernedCoreRoots,
    projects_dir: str | Path,
) -> CanaryResult:
    """Run the boot canary and RAISE if the coordinator must not start (control 6).

    Returns the :class:`CanaryResult` on success; raises
    :class:`~shared.coordinator.governed_core.SelfGovernanceBoundaryError`
    (refuse-to-start) if any probe failed. This is the boot-path call site: the
    backend refuses to start a coordinator surface whose boundary does not hold,
    exactly as the egress guard trips rather than degrade."""
    result = run_boot_canary(config=config, roots=roots, projects_dir=projects_dir)
    if not result.ok:
        failed = result.failures()
        summary = "; ".join(f"[{p.name}] {p.detail}" for p in failed) or result.error
        raise SelfGovernanceBoundaryError(
            f"coordinator boot canary FAILED — refusing to start (ADR-039 §2.2 "
            f"control 6). Failures: {summary}"
        )
    return result
