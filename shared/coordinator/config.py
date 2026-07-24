"""Coordinator self-governance boundary — configuration surface + policy data (ADR-039 #848).

This module is the DORMANT ``[coordinator]`` config surface and the code-level
"policy data" the seven structural controls read: the governed-core root set, the
renamed-clone identity filesets, and the protected-config-section set. It imports
nothing else from :mod:`shared.coordinator` (leaf module — no cycles).

**Every default here is off.** :class:`CoordinatorConfig` default-constructs to
"fully off" — the coordinator is disabled, the whole graduated-autonomy ladder is
empty, and signed-policy verification is not required. This module only resolves
values; it never acts on them, so importing it changes no runtime behavior. What the
coordinator actually does is decided by the RESOLVED ``[coordinator]`` values — read
them from ``services/assistant_orchestrator/config/default.toml``, never from here.

Design tenets (ADR-039 §2.1, §2.2):
  * **Fail-closed resolution.** A missing/mistyped TOML key resolves to the *safe*
    value (off / empty / require-nothing-live), never to "on".
  * **Multi-operator default (control 5).** A fresh install has the autonomy ladder
    *fully off*; :meth:`CoordinatorConfig.autonomy_all_off` is the lock's predicate.
  * **The forbidden-target set is config-defined but NOT modifiable via any BlarAI
    surface** (ADR-039 §2.2 control 1). It lives here as code constants (and, once
    control 7 ships, is additionally signature-anchored in a signed policy file);
    control 4 refuses every inside-write to it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Final, Mapping

# ---------------------------------------------------------------------------
# C3 heartbeat cadence defaults (#845, design doc §9) — the SSOT constants.
# They live HERE (the leaf config module) so :mod:`shared.coordinator.cadence`
# can import them without breaking this module's no-coordinator-imports
# invariant; the timeout registry's rows point at these attributes.
# ---------------------------------------------------------------------------

#: AC-power wake-cycle interval (seconds). Registered in shared/timeout_registry.py.
DEFAULT_HEARTBEAT_INTERVAL_S: Final[float] = 900.0

#: Battery interval stretch: effective interval = interval × this (ADR-039
#: §2.12.12). Dimensionless — noted on the interval's registry row, not a row.
DEFAULT_BATTERY_MULTIPLIER: Final[float] = 4.0

#: First-cycle delay after boot + the quiet-queue tripwire's idle-grace floor.
#: Registered in shared/timeout_registry.py.
DEFAULT_BOOT_GRACE_S: Final[float] = 300.0

#: The default runtime-readable overnight quiet window (local wall-clock).
DEFAULT_OVERNIGHT_WINDOW: Final[str] = "23:00-09:00"

# ---------------------------------------------------------------------------
# The dedicated coordinator identity (structural provenance — ADR-039 §2.2 control 2)
# ---------------------------------------------------------------------------
# The account itself is created by the C1/#843 operator-run migration. These
# constants are the STRUCTURAL provenance the refusal logic keys on — never a text
# convention (a text marker is forgeable by any injection that can author a comment,
# ADR-039 rejected-alt #2).

#: The dedicated Vikunja username for all coordinator runtime-bridge writes. A
#: ticket/comment whose immutable ``created_by`` is this account is BlarAI-authored.
COORDINATOR_ACCOUNT_USERNAME: Final[str] = "blarai-coordinator"

#: The deterministic, code-set label marking a proposal as self-advisory (about
#: BlarAI itself). Set by deterministic code at authoring time, NOT parsed from the
#: model's free text. BlarAI's own dispatch path refuses a ticket carrying this
#: label categorically, even post-approval (control 2).
SELF_ADVISORY_LABEL: Final[str] = "Advisory:BlarAI"

#: The provenance tier every consumer stamps on coordinator-authored ticket/comment
#: content (control 3): untrusted proposal-grade input, never operator instruction —
#: even on a later read by BlarAI itself.
COORDINATOR_AUTHORED_TIER: Final[str] = "UNTRUSTED_COORDINATOR_AUTHORED"

#: The default human-readable marker the coordinator prepends to content it authors
#: (control 3). Transparency for a human reader — NOT the trust anchor (the anchor is
#: the immutable ``created_by`` account, which an injection cannot forge).
AUTHORED_CONTENT_MARKER_DEFAULT: Final[str] = (
    "_[Authored by the BlarAI coordinator — untrusted proposal-grade input; "
    "review before acting.]_"
)


# ---------------------------------------------------------------------------
# Governed-core identity data (control 1 — renamed-clone defense)
# ---------------------------------------------------------------------------
# A renamed *clone* of the governed core is a genuinely separate directory tree, so
# neither path-name matching nor canonical-realpath containment catches it (realpath
# only resolves symlinks/junctions; a git worktree needs git-file resolution). The
# deterministic renamed-clone defense is CONTENT IDENTITY: a candidate tree that
# carries the governed core's identity markers IS governed core, whatever its path.

#: A single dedicated sentinel file (repo-root relative). Present in every clone of
#: the governed core; absent from an innocent workspace project. Zero-false-positive.
GOVERNED_CORE_SENTINEL_FILE: Final[str] = ".blarai-governed-core"

#: Identity filesets (repo-root-relative paths). A candidate root is identified as a
#: governed-core clone if, for ANY fileset, EVERY listed path exists under it. Two
#: independent deterministic predicates (defense-in-depth): the dedicated sentinel,
#: OR a distinctive multi-file combination that an innocent project is vanishingly
#: unlikely to reproduce in full. Requiring the FULL set (not a fuzzy threshold)
#: keeps the check deterministic — no heuristic scoring in constitutional code.
GOVERNED_CORE_IDENTITY_FILESETS: Final[tuple[tuple[str, ...], ...]] = (
    (GOVERNED_CORE_SENTINEL_FILE,),
    ("CLAUDE.md", "docs/DECISION_REGISTER.md", "shared/fleet/dispatch.py"),
)


# ---------------------------------------------------------------------------
# Protected config sections (control 4 — configuration immutability from inside)
# ---------------------------------------------------------------------------

#: The security/governance-critical config sections the coordinator surface (tools,
#: proposals, ``propose_preference``) may NEVER read-write from inside (ADR-039 §2.2
#: control 4; SG-review F3 named ``propose_preference`` explicitly). This is the
#: NAMED core; control 4's deny is categorical for *any* runtime-config write (the
#: whole config file is governed core, ADR-039 §2.1 item 2) — this set only sharpens
#: the refusal message for the highest-risk sections.
PROTECTED_CONFIG_SECTIONS: Final[frozenset[str]] = frozenset(
    {
        "coordinator",
        "autonomy",
        "policy",
        "pgov",
        "security",
        "generation",
        "gpu",
        "fleet_dispatch",
        "embeddings",
        "knowledge",
        "image_generation",
        "web_search",
        "egress",
    }
)

#: Config file basenames a write target might name directly (belt-and-suspenders
#: alongside the governed-core path containment). Any inside-write naming one of
#: these is refused by control 4 even before path resolution.
PROTECTED_CONFIG_BASENAMES: Final[frozenset[str]] = frozenset(
    {"default.toml", "config.toml"}
)


# ---------------------------------------------------------------------------
# The graduated-autonomy ladder (control 5 — multi-operator defaults)
# ---------------------------------------------------------------------------

#: The known low-risk action classes that C5 (`#847`) may individually flip
#: propose→auto, each behind a per-class flag, each an LA ceremony (ADR-039 §2.10).
#: The ladder ships FULLY OFF: :class:`CoordinatorConfig.enabled_auto_classes` is
#: empty by default, so every class is propose-only on a fresh install.
AUTONOMY_LADDER_CLASSES: Final[frozenset[str]] = frozenset(
    {
        "ticket-hygiene",
        "stall-redispatch",
        "readiness-refinement",
        "reclassification",
        "work-origination",
    }
)


@dataclass(frozen=True)
class CoordinatorConfig:
    """Resolved ``[coordinator]`` configuration — DORMANT, default fully off.

    Every field defaults to the safe value so a fresh install (default construction)
    has the coordinator disabled and the autonomy ladder empty (control 5). Frozen +
    hashable: ``enabled_auto_classes`` is a ``frozenset`` so the whole config is a
    value object.
    """

    enabled: bool = False
    """Master gate for the coordinator role. ``False`` (dormant default) means no
    coordinator surface is constructed at all. Resolved from ``[coordinator].enabled``."""

    heartbeat_enabled: bool = False
    """C3 (`#845`) wake cycle. Dormant default off. Resolved from
    ``[coordinator].heartbeat_enabled``."""

    work_origination_enabled: bool = False
    """C4 (`#846`) work-origination proposals. Dormant default off. Resolved from
    ``[coordinator].work_origination_enabled``."""

    swap_doom_checks_enabled: bool = False
    """C2 (`#844`) driver-integrated stop-doomed-fast checks
    (:mod:`shared.fleet.doom_check`). Dormant default off: the dispatch spec does
    not carry the flag, so the detached swap driver runs NO doom watchdog — swap
    behavior is byte-identical to pre-#844. Going live (an LA ceremony) threads
    this into the dispatch spec at AO-side dispatch time. Resolved from
    ``[coordinator].swap_doom_checks_enabled``."""

    require_signed_policy: bool = False
    """Control 7 gate — mirrors ``[security].require_signed_manifest``. ``True`` →
    the signed policy file MUST verify at boot or the coordinator refuses to start;
    ``False`` (dormant default) permits an unsigned policy with a WARNING but a
    *present-and-invalid* signature is still fail-closed (no silent downgrade).
    Resolved from ``[coordinator].require_signed_policy``."""

    policy_path: str = ""
    """Path to the signed policy file (control 7). Empty (dormant default) → the
    compiled-in governed-core defaults in this module are authoritative. Resolved
    from ``[coordinator].policy_path``."""

    enabled_auto_classes: frozenset[str] = field(default_factory=frozenset)
    """The autonomy-ladder classes flipped propose→auto (C5). EMPTY on a fresh
    install (control 5) — every class is propose-only until an LA ceremony adds it.
    Resolved from ``[coordinator].enabled_auto_classes`` (a list of class names;
    unknown names are dropped fail-closed)."""

    heartbeat_interval_s: float = DEFAULT_HEARTBEAT_INTERVAL_S
    """C3 (#845) AC-power wake-cycle interval (design §9; SSOT constant
    ``shared.coordinator.cadence.DEFAULT_HEARTBEAT_INTERVAL_S``, registered in
    ``shared/timeout_registry.py``). Inert while ``heartbeat_enabled`` is False.
    Resolved from ``[coordinator].heartbeat_interval_s`` — non-numeric or
    non-positive values fail closed to the default."""

    heartbeat_battery_multiplier: float = DEFAULT_BATTERY_MULTIPLIER
    """C3 battery interval stretch (ADR-039 §2.12.12): on battery (or an
    undeterminable power state) the interval is ``heartbeat_interval_s × this``.
    Values below 1 fail closed to the default — a sub-1 multiplier would SPEED UP
    on battery, the wrong direction. Resolved from
    ``[coordinator].heartbeat_battery_multiplier``."""

    heartbeat_boot_grace_s: float = DEFAULT_BOOT_GRACE_S
    """C3 first-cycle delay after boot + the quiet-queue tripwire's idle-grace
    floor (design §9; registered in the registry). Non-numeric/negative fails
    closed to the default. Resolved from ``[coordinator].heartbeat_boot_grace_s``."""

    overnight_window: str = DEFAULT_OVERNIGHT_WINDOW
    """C3 runtime-readable overnight quiet window (design §8.3 — deterministic-only
    cycles + tripwire quiet inside it; the fleet owns the night GPU). Parsed
    fail-soft-with-surfaced-note by ``shared.coordinator.cadence.parse_overnight_window``;
    empty string = deliberately no window. Resolved from
    ``[coordinator].overnight_window``."""

    operator_absent: bool = False
    """C3 operator-absence mode switch (ADR-039 §2.12.9): only Expedite-class
    conditions surface, digests accumulate to one catch-up brief, proposal TTLs
    pause. Operator-set outside BlarAI like every ``[coordinator]`` key (control
    4); auto-detection via unanswered briefings is C4's. Resolved from
    ``[coordinator].operator_absent``."""

    shadow_mode: bool = True
    """C3 output-router mode (#845 design §7; ADR-039 §2.13.2). ``True`` (the
    default) diverts every operator-visible and board-visible heartbeat effect
    to the born-encrypted shadow journal (machinery-health alarms excepted —
    never shadow-gated, §7.2); flipped to ``False`` ONLY at the #855 graduation
    ceremony — with ``heartbeat_enabled`` these are the two independent locks
    on live output (§7.1). Resolution is fail-closed toward TRUE: a missing OR
    mistyped value resolves ``True``, because for this key alone SHADOW is the
    safe direction — the usual missing-key→False bool idiom is deliberately
    inverted, and only an explicit TOML boolean ``false`` goes live. Resolved
    from ``[coordinator].shadow_mode``."""

    def autonomy_all_off(self) -> bool:
        """True iff no autonomy-ladder class is auto-enabled (control 5 predicate).

        The multi-operator-defaults lock asserts this holds on a fresh install."""
        return len(self.enabled_auto_classes) == 0

    @classmethod
    def fresh_install(cls) -> "CoordinatorConfig":
        """The fresh-install config — everything off, ladder empty (control 5).

        Identical to default construction; named for the multi-operator lock's
        intent (``CoordinatorConfig.fresh_install().autonomy_all_off()`` is True)."""
        return cls()

    @classmethod
    def from_toml(cls, section: Mapping[str, object] | None) -> "CoordinatorConfig":
        """Resolve a ``[coordinator]`` TOML section fail-closed.

        A ``None``/empty section, or any missing/mistyped key, resolves to the safe
        default (off / empty / require-nothing-live — and for ``shadow_mode``
        the safe direction is TRUE: shadow, never live). An ``enabled_auto_classes``
        list is filtered to KNOWN ladder classes (:data:`AUTONOMY_LADDER_CLASSES`)
        — an unrecognised or non-string entry is dropped, never granted autonomy.
        """
        data: Mapping[str, object] = section if isinstance(section, Mapping) else {}

        def _bool(key: str) -> bool:
            return bool(data.get(key, False))

        def _str(key: str) -> str:
            value = data.get(key, "")
            return value.strip() if isinstance(value, str) else ""

        def _float(key: str, default: float, *, minimum: float) -> float:
            """Fail-closed numeric resolve: mistyped, unparseable, or
            below-*minimum* values keep the safe default (a heartbeat interval
            of 0 or a battery multiplier of 0.5 is a misconfiguration, never a
            faster cadence)."""
            value = data.get(key, default)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                return default
            resolved = float(value)
            return resolved if resolved >= minimum else default

        # shadow_mode inverts the usual missing/mistyped→False resolution
        # (design §7.2): SHADOW is the safe direction for this key, so anything
        # other than an explicit boolean resolves TRUE — a typo'd or absent key
        # can silence the router's live output, never open it.
        raw_shadow = data.get("shadow_mode", True)
        shadow_mode = raw_shadow if isinstance(raw_shadow, bool) else True

        raw_classes = data.get("enabled_auto_classes", [])
        classes: set[str] = set()
        if isinstance(raw_classes, (list, tuple, set, frozenset)):
            for item in raw_classes:
                if isinstance(item, str) and item in AUTONOMY_LADDER_CLASSES:
                    classes.add(item)

        overnight = data.get("overnight_window", DEFAULT_OVERNIGHT_WINDOW)

        return cls(
            enabled=_bool("enabled"),
            heartbeat_enabled=_bool("heartbeat_enabled"),
            work_origination_enabled=_bool("work_origination_enabled"),
            swap_doom_checks_enabled=_bool("swap_doom_checks_enabled"),
            require_signed_policy=_bool("require_signed_policy"),
            policy_path=_str("policy_path"),
            enabled_auto_classes=frozenset(classes),
            heartbeat_interval_s=_float(
                "heartbeat_interval_s", DEFAULT_HEARTBEAT_INTERVAL_S, minimum=60.0
            ),
            heartbeat_battery_multiplier=_float(
                "heartbeat_battery_multiplier", DEFAULT_BATTERY_MULTIPLIER, minimum=1.0
            ),
            heartbeat_boot_grace_s=_float(
                "heartbeat_boot_grace_s", DEFAULT_BOOT_GRACE_S, minimum=0.0
            ),
            overnight_window=(
                overnight.strip()
                if isinstance(overnight, str)
                else DEFAULT_OVERNIGHT_WINDOW
            ),
            operator_absent=_bool("operator_absent"),
            shadow_mode=shadow_mode,
        )


# ---------------------------------------------------------------------------
# Governed-core roots (control 1 — the identity-based severance target set)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class GovernedCoreRoots:
    """The realpath-resolved roots that define the governed core (ADR-039 §2.1).

    A target is governed core if its canonical realpath is contained under ANY of
    these roots (control 1 layer 1). The set is config-defined but NOT modifiable
    via any BlarAI surface (controls 4 + 7). Roots are dependency-injected so tests
    drive tmp trees and the live wiring passes the real host paths.

    Members (ADR-039 §2.1):
      * ``repo_root`` — the BlarAI runtime code/config/prompts/models/docs tree.
      * ``fleet_governance_root`` — the agentic-setup fleet's verify-gate / oracle /
        harness config, severed from BOTH sides (§2.1 item 9, the frozen-evaluator
        rule). ``None`` when unresolved (still fail-closed — a ``None`` root simply
        contributes nothing, and the other layers/roots still apply).
      * ``coordinator_store_root`` — the proposal-staging store, briefing ledger, and
        shadow journal (§2.1 item 10).
      * ``extra_roots`` — additional governed-core roots from the signed policy file.
    """

    repo_root: Path
    fleet_governance_root: Path | None = None
    coordinator_store_root: Path | None = None
    extra_roots: tuple[Path, ...] = ()

    def all_roots(self) -> tuple[Path, ...]:
        """Every non-``None`` governed-core root, realpath-resolved.

        Resolution is best-effort per root; an unresolvable root is DROPPED here but
        the caller's per-target check is independently fail-closed, so a dropped root
        never opens a path (it just relies on the remaining roots + identity/worktree
        layers). A root that resolves is compared by its canonical realpath."""
        roots: list[Path] = []
        for candidate in (
            self.repo_root,
            self.fleet_governance_root,
            self.coordinator_store_root,
            *self.extra_roots,
        ):
            if candidate is None:
                continue
            try:
                roots.append(Path(candidate).resolve())
            except OSError:
                # Unresolvable root: drop it (the target check stays fail-closed via
                # the remaining roots + the identity/worktree layers).
                continue
        return tuple(roots)


def repo_root_from_module() -> Path:
    """The BlarAI repo root inferred from this module's location.

    ``shared/coordinator/config.py`` → ``parents[2]`` is the repo root. Used as the
    default ``repo_root`` when the caller supplies none."""
    return Path(__file__).resolve().parents[2]


def default_governed_core_roots(
    *,
    repo_root: str | Path | None = None,
    fleet_governance_root: str | Path | None = None,
    coordinator_store_root: str | Path | None = None,
    extra_roots: tuple[str | Path, ...] = (),
) -> GovernedCoreRoots:
    """Build the default governed-core root set for this host (control 1).

    ``repo_root`` defaults to :func:`repo_root_from_module`. ``fleet_governance_root``
    defaults to the agentic-setup fleet root the dispatch module already targets
    (imported lazily so this leaf module has no import-time dependency on
    :mod:`shared.fleet.dispatch`). Any argument may be overridden (tests pass tmp
    trees; the live wiring passes resolved config paths)."""
    root = Path(repo_root) if repo_root is not None else repo_root_from_module()

    fleet_root: Path | None
    if fleet_governance_root is not None:
        fleet_root = Path(fleet_governance_root)
    else:
        try:
            from shared.fleet.dispatch import _AGENTIC_SETUP  # lazy, avoid cycle

            fleet_root = Path(_AGENTIC_SETUP)
        except Exception:  # noqa: BLE001 — fail-closed toward no fleet root (drops it)
            fleet_root = None

    store_root = (
        Path(coordinator_store_root) if coordinator_store_root is not None else None
    )

    return GovernedCoreRoots(
        repo_root=root,
        fleet_governance_root=fleet_root,
        coordinator_store_root=store_root,
        extra_roots=tuple(Path(p) for p in extra_roots),
    )
