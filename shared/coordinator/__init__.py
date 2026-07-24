"""BlarAI Coordinator — self-governance boundary (ADR-039 #848).

The constitutional security foundation of the Coordinator program (`#841`): the
structural severance of BlarAI's self-modification paths. BlarAI has **zero write
path** to the governed core (its own code/config/prompts/policy, models/keys,
governing docs, ruler/flag/trigger defs, the proposal-staging store, and the
agentic-setup fleet's verify-gate/oracle/harness config); it may observe and advise
on its own backlog, but never execute against itself (ADR-039 §2.1).

This package implements the seven structural controls, each gated behind
``[coordinator]`` config flags (dormant default: off), each fail-closed (a boundary
check that errors DENIES, never allows). Importing this package arms nothing and
changes no behavior — construction is what a flag gates, not import. Which flags are
set is read from ``services/assistant_orchestrator/config/default.toml``, never from
this docstring; the severance above binds identically at every flag setting.

Controls (ADR-039 §2.2):
  1. Identity-based governed-core severance — :mod:`shared.coordinator.governed_core`
     (``check_target`` / ``is_governed_core_target``): canonical-realpath containment
     + git-worktree resolution + content-identity sentinel; staging-time + re-run at
     execution (TOCTOU); target re-derived from trusted structured fields (CaMeL).
  2. Advisory-only self-work — :mod:`shared.coordinator.provenance`
     (``refuse_self_advisory_dispatch``): structural provenance, categorical refusal.
  3. Instruction-channel integrity — :mod:`shared.coordinator.provenance`
     (``treat_as_untrusted`` / ``provenance_tier_for_author``).
  4. Config immutability from inside — :mod:`shared.coordinator.governed_core`
     (``check_config_write``).
  5. Multi-operator defaults — :mod:`shared.coordinator.config`
     (``CoordinatorConfig.fresh_install`` / ``autonomy_all_off``): ladder fully off.
  6. Boot-time boundary canary + refuse-to-start — :mod:`shared.coordinator.boot_canary`
     (``run_boot_canary`` / ``assert_boot_boundary``): negative + positive probes.
  7. Signed policy verification — :mod:`shared.coordinator.policy`
     (``verify_policy_integrity``): extends the ADR-018 signed-manifest machinery.
"""

from __future__ import annotations

from shared.coordinator.boot_canary import (
    CanaryProbe,
    CanaryResult,
    assert_boot_boundary,
    run_boot_canary,
)
from shared.coordinator.config import (
    AUTONOMY_LADDER_CLASSES,
    COORDINATOR_ACCOUNT_USERNAME,
    COORDINATOR_AUTHORED_TIER,
    GOVERNED_CORE_IDENTITY_FILESETS,
    GOVERNED_CORE_SENTINEL_FILE,
    PROTECTED_CONFIG_SECTIONS,
    SELF_ADVISORY_LABEL,
    CoordinatorConfig,
    GovernedCoreRoots,
    default_governed_core_roots,
    repo_root_from_module,
)
from shared.coordinator.governed_core import (
    BoundaryDecision,
    ConfigWriteVerdict,
    SelfGovernanceBoundaryError,
    TargetVerdict,
    assert_workspace_target,
    check_config_write,
    check_target,
    derive_workspace_target,
    is_governed_core_target,
    is_protected_config_section,
)
from shared.coordinator.policy import (
    COORDINATOR_POLICY_FILENAME,
    COORDINATOR_POLICY_SIGNING_KEY_NAME,
    PolicyVerificationResult,
    load_policy_verified,
    resolve_governed_core_roots_from_policy,
    verify_policy_integrity,
)
from shared.coordinator.provenance import (
    DispatchProvenanceDecision,
    DispatchProvenanceVerdict,
    TicketProvenance,
    extract_provenance,
    is_coordinator_authored,
    is_self_advisory,
    mark_authored,
    provenance_tier_for_author,
    refuse_self_advisory_dispatch,
    treat_as_untrusted,
)

__all__ = [
    # config / control 5
    "CoordinatorConfig",
    "GovernedCoreRoots",
    "default_governed_core_roots",
    "repo_root_from_module",
    "AUTONOMY_LADDER_CLASSES",
    "COORDINATOR_ACCOUNT_USERNAME",
    "COORDINATOR_AUTHORED_TIER",
    "SELF_ADVISORY_LABEL",
    "GOVERNED_CORE_IDENTITY_FILESETS",
    "GOVERNED_CORE_SENTINEL_FILE",
    "PROTECTED_CONFIG_SECTIONS",
    # governed core / controls 1 + 4
    "BoundaryDecision",
    "TargetVerdict",
    "ConfigWriteVerdict",
    "SelfGovernanceBoundaryError",
    "check_target",
    "assert_workspace_target",
    "is_governed_core_target",
    "derive_workspace_target",
    "check_config_write",
    "is_protected_config_section",
    # provenance / controls 2 + 3
    "TicketProvenance",
    "DispatchProvenanceDecision",
    "DispatchProvenanceVerdict",
    "extract_provenance",
    "is_coordinator_authored",
    "is_self_advisory",
    "refuse_self_advisory_dispatch",
    "mark_authored",
    "provenance_tier_for_author",
    "treat_as_untrusted",
    # policy / control 7
    "PolicyVerificationResult",
    "verify_policy_integrity",
    "load_policy_verified",
    "resolve_governed_core_roots_from_policy",
    "COORDINATOR_POLICY_FILENAME",
    "COORDINATOR_POLICY_SIGNING_KEY_NAME",
    # boot canary / control 6
    "CanaryProbe",
    "CanaryResult",
    "run_boot_canary",
    "assert_boot_boundary",
]
