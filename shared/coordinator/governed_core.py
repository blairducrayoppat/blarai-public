"""Identity-based governed-core severance (ADR-039 §2.2 control 1) + config immutability (control 4).

This is the load-bearing module of the self-governance boundary: the deterministic,
fail-closed check that decides whether a proposed action *target* lands inside the
governed core (deny) or the workspace (allow). It generalizes and STRENGTHENS the
existing anchor ``shared/fleet/dispatch.py:40`` (``_FORBIDDEN_REPO_ROOTS`` — today a
casefolded name-component check plus ``relative_to(projects_dir)`` containment),
which a renamed clone or a junction can evade (SG-review F5).

**Membership is decided by IDENTITY, never by path-component name** (ADR-039 rejected
alt #1). Independent, deterministic layers, ANY of which marks a target as governed
core:

  1. **Canonical realpath + inode identity** — ``Path.resolve()`` resolves symlinks and
     Windows directory junctions to their real target before the containment test, so a
     junction/symlink under the workspace that points *into* the governed core is caught
     by its resolved path, not fooled by its name. ``resolve()`` alone cannot see through
     a **hardlink** (a second directory entry for the SAME inode, whose own path is
     genuinely under the workspace); an inode-identity check therefore also marks any
     target that shares the device+inode of a known governed-core anchor file
     (:func:`_governed_core_anchor_files`) — the hardlink-overwrite vector (SG-review F1).
     Because the governed core is the WHOLE tree and not only those anchors, a further
     link-count layer (:func:`_is_multiply_linked_existing`) refuses ANY existing target
     whose ``st_nlink > 1`` — closing a hardlink aimed at a NON-anchor core file (e.g.
     ``pyproject.toml`` or ``shared/coordinator/config.py``), which the anchor comparison
     alone misses (SG-review F1, non-anchor vector).
  2. **Git-worktree resolution** — a linked git worktree's top dir is real files (not
     a symlink) but carries a ``.git`` *file* pointing at ``<main>/.git/worktrees/…``.
     We parse that pointer, resolve the main repo root, and test IT for containment —
     so a worktree of the governed core placed anywhere is caught.
  3. **Content-identity sentinel** — a renamed *clone* is a genuinely separate tree
     (realpath and worktree resolution both miss it). It is caught by CONTENT: a
     candidate tree (or any ancestor of the target) carrying the governed core's
     identity markers (:data:`~shared.coordinator.config.GOVERNED_CORE_IDENTITY_FILESETS`)
     IS governed core, whatever its path or name.

**Fail-closed everywhere.** Any unresolvable path, unreadable file, or unexpected
error resolves to "governed core" (deny) — a boundary check that errors must DENY,
never allow (ADR-039 §2, the project's standing fail-closed rule).

**TOCTOU (ADR-039 §2.2 control 1 / §2.12.4).** :func:`check_target` is a pure
function of the *current* filesystem state. The coordinator calls it at STAGING time
AND re-runs it at EXECUTION time; if the world changed between (a benign dir replaced
by a junction into the governed core), the execution-time call re-resolves and
refuses. The execution-time run is authoritative.

**The CaMeL property (ADR-039 §2.2 control 1).** The execution *target* is separately
re-derived by deterministic code from trusted, structured fields
(:func:`derive_workspace_target`) — never taken from model free text — so untrusted
content can shape a proposal's *content* but can never select its *target*.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from shared.coordinator.config import (
    GOVERNED_CORE_IDENTITY_FILESETS,
    PROTECTED_CONFIG_BASENAMES,
    PROTECTED_CONFIG_SECTIONS,
    GovernedCoreRoots,
)

logger = logging.getLogger(__name__)


class SelfGovernanceBoundaryError(RuntimeError):
    """Raised when the self-governance boundary refuses an action or a boot.

    The refuse-to-stage / refuse-to-start signal (ADR-039 §2.2 controls 1, 6). It is
    a hard stop, not an advisory: the caller must NOT proceed. Fail-closed callers
    catch it and abort (a staged proposal is dropped; a boot refuses to start)."""


class BoundaryDecision(Enum):
    """A deterministic boundary verdict — ALLOW (workspace) or DENY (governed core)."""

    ALLOW = "ALLOW"
    DENY = "DENY"


@dataclass(frozen=True)
class TargetVerdict:
    """The verdict of a governed-core target check (control 1)."""

    decision: BoundaryDecision
    reason: str
    resolved_target: str = ""
    phase: str = ""
    """"STAGING" | "EXECUTION" | "" — which chokepoint ran the check (audit/TOCTOU)."""

    @property
    def allowed(self) -> bool:
        return self.decision is BoundaryDecision.ALLOW

    @property
    def denied(self) -> bool:
        return self.decision is BoundaryDecision.DENY


@dataclass(frozen=True)
class ConfigWriteVerdict:
    """The verdict of a configuration-immutability check (control 4)."""

    decision: BoundaryDecision
    reason: str

    @property
    def allowed(self) -> bool:
        return self.decision is BoundaryDecision.ALLOW

    @property
    def denied(self) -> bool:
        return self.decision is BoundaryDecision.DENY


# ---------------------------------------------------------------------------
# Low-level, fail-closed path primitives
# ---------------------------------------------------------------------------


def _safe_resolve(path: str | Path) -> Path | None:
    """``Path(path).resolve()`` (canonical realpath — resolves symlinks/junctions),
    or ``None`` on any error. Fail-closed: the caller treats ``None`` as deny."""
    try:
        return Path(path).resolve()
    except (OSError, ValueError, RuntimeError):
        return None


def _is_contained(child_resolved: Path, root_resolved: Path) -> bool:
    """True iff ``child_resolved`` is ``root_resolved`` or lives under it.

    Both arguments MUST already be realpath-resolved. Uses ``relative_to`` (pure path
    arithmetic on resolved paths — no further FS access), so a symlink/junction was
    already collapsed by the caller's :func:`_safe_resolve`."""
    try:
        child_resolved.relative_to(root_resolved)
        return True
    except ValueError:
        return False


def _canonical_containment(target_resolved: Path, roots: GovernedCoreRoots) -> bool:
    """Layer 1 — canonical realpath containment (symlink/junction defense).

    True iff the target's realpath is contained under any governed-core root's
    realpath. Because ``target_resolved`` is already realpath-resolved, a junction or
    symlink under the workspace that points into the governed core is caught by its
    *resolved* location."""
    for root in roots.all_roots():
        if _is_contained(target_resolved, root):
            return True
    return False


def _governed_core_anchor_files(roots: GovernedCoreRoots) -> Iterator[Path]:
    """Yield the known governed-core ANCHOR files for inode-identity comparison.

    Every identity-fileset member path under every governed-core root — exactly the
    ``.blarai-governed-core`` sentinel plus the ``CLAUDE.md`` /
    ``docs/DECISION_REGISTER.md`` / ``shared/fleet/dispatch.py`` triad, under each root
    (:data:`~shared.coordinator.config.GOVERNED_CORE_IDENTITY_FILESETS`). These are the
    files a hardlink attack would alias to obtain a write path to the core, so they are
    the identities the inode check compares a candidate target against."""
    for root in roots.all_roots():
        for fileset in GOVERNED_CORE_IDENTITY_FILESETS:
            for rel in fileset:
                yield root / rel


def _shares_inode_with_governed_core(
    target_resolved: Path, roots: GovernedCoreRoots
) -> bool:
    """Layer 1 (inode identity) — hardlink defense (ADR-039 control 1; SG-review F1).

    ``Path.resolve()`` cannot see through a HARDLINK: a hardlink is a second directory
    entry for the SAME on-disk file (device + inode), and its own path is genuinely under
    the workspace, so canonical-realpath containment passes it — yet a write through it
    mutates the linked governed-core file. This marks the target governed core iff it is
    the SAME file (device + inode) as any known governed-core anchor file
    (:func:`_governed_core_anchor_files`).

    A not-yet-existing target returns ``False`` — a file with no inode cannot alias an
    existing core file (the normal new-workspace-file case). If an EXISTING target cannot
    be ``stat``-ed, the ``OSError`` propagates to the caller's fail-closed handler (which
    denies): an unreadable existing target is never treated as safe."""
    try:
        target_st = target_resolved.stat()
    except FileNotFoundError:
        return False
    # Any OTHER OSError on an existing path propagates → caller denies (fail-closed).
    for anchor in _governed_core_anchor_files(roots):
        try:
            anchor_st = anchor.stat()
        except OSError:
            # A missing/unreadable anchor simply cannot match; keep checking the rest.
            continue
        if (
            target_st.st_ino != 0
            and target_st.st_ino == anchor_st.st_ino
            and target_st.st_dev == anchor_st.st_dev
        ):
            return True
    return False


def _is_multiply_linked_existing(target_resolved: Path) -> bool:
    """Layer 1 (link-count) — non-anchor hardlink defense (ADR-039 control 1; SG-review F1).

    The inode-anchor check (:func:`_shares_inode_with_governed_core`) compares a target
    against a SMALL anchor fileset, but the governed core is the WHOLE tree: a hardlink
    placed under an allowed workspace path and pointing at a NON-anchor core file
    (``pyproject.toml``, ``launcher/config/default.toml``, ``shared/coordinator/config.py``
    — the boundary's own policy data — or a PA policy module) aliases no anchor, so the
    anchor check misses it AND canonical-realpath containment passes its innocent workspace
    path — yet a write through it still mutates the linked core file. This closes that gap
    deterministically and fail-closed: a hardlink is the attack primitive, so ANY already
    multiply-linked EXISTING file (POSIX ``st_nlink > 1``) is refused, whatever it aliases.

    A not-yet-existing target returns ``False`` (``FileNotFoundError`` — the normal
    new-workspace-file case; a freshly created file has ``st_nlink == 1``). Any OTHER
    ``OSError`` on an existing path propagates to the caller's fail-closed handler (which
    denies): an unreadable existing target is never treated as safe.

    **Windows scope (honest).** This is a Windows host; on NTFS Python populates
    ``st_nlink`` from the file handle's ``nNumberOfLinks`` and it is reliable for real
    files (an NTFS hardlink reports ``>= 2``). If the value is ``0`` (unknown — some
    non-NTFS / handle-less cases) that is NOT ``> 1``, so this layer does not false-deny
    and the other identity layers still apply. This check therefore only ever ADDS
    denials for genuinely multiply-linked files; a link count it cannot determine (``0``)
    never opens a path, and it never claims to catch more than link count reveals.

    Cost: over-denial fires ONLY when overwriting an already-hardlinked existing file — a
    negligible, correct cost for a constitutional fail-closed boundary; a normal new
    workspace file (``st_nlink == 1``) is unaffected."""
    try:
        return target_resolved.stat().st_nlink > 1
    except FileNotFoundError:
        return False
    # Any OTHER OSError on an existing path propagates → caller denies (fail-closed).


def _worktree_main_root(target_resolved: Path) -> Path | None:
    """Layer 2 — resolve a linked git worktree to its MAIN repo root, or ``None``.

    A linked worktree's top dir carries a ``.git`` *file* (not a dir) whose content is
    ``gitdir: <main>/.git/worktrees/<name>``. We walk the target and its ancestors for
    such a marker, parse the pointer, resolve it, and derive the main repo root (the
    parent of the ``.git`` dir it points into). Fail-closed: any unreadable/unparseable
    marker yields ``None`` (the other layers still apply)."""
    for base in (target_resolved, *target_resolved.parents):
        gitfile = base / ".git"
        try:
            if not gitfile.is_file():
                continue
            text = gitfile.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        gitdir_line = next(
            (ln for ln in text.splitlines() if ln.strip().lower().startswith("gitdir:")),
            None,
        )
        if gitdir_line is None:
            continue
        gitdir_str = gitdir_line.split(":", 1)[1].strip()
        if not gitdir_str:
            continue
        gitdir = Path(gitdir_str)
        if not gitdir.is_absolute():
            gitdir = base / gitdir
        gitdir_resolved = _safe_resolve(gitdir)
        if gitdir_resolved is None:
            continue
        # gitdir is typically <main>/.git/worktrees/<name>. The main repo root is the
        # parent of the `.git` ancestor. Prefer an explicit `commondir` if present.
        commondir_file = gitdir_resolved / "commondir"
        try:
            if commondir_file.is_file():
                common_rel = commondir_file.read_text(encoding="utf-8").strip()
                common = _safe_resolve(gitdir_resolved / common_rel)
                if common is not None and common.name == ".git":
                    return _safe_resolve(common.parent)
        except OSError:
            pass
        for ancestor in (gitdir_resolved, *gitdir_resolved.parents):
            if ancestor.name == ".git":
                return _safe_resolve(ancestor.parent)
    return None


def _has_governed_core_identity(target_resolved: Path) -> bool:
    """Layer 3 — content-identity sentinel (renamed-clone defense).

    True iff the target OR any ancestor is a directory tree carrying the governed
    core's identity markers: for ANY identity fileset, EVERY listed relative path
    exists under that candidate root. Deterministic (exact-path existence, no fuzzy
    threshold). Catches a renamed clone/copy that realpath and worktree resolution
    both miss, because the identity is in the CONTENT, not the path."""
    for base in (target_resolved, *target_resolved.parents):
        for fileset in GOVERNED_CORE_IDENTITY_FILESETS:
            try:
                if all((base / rel).exists() for rel in fileset):
                    return True
            except OSError:
                # An unreadable candidate is treated as a match (fail-closed toward
                # governed core): we could not prove it is NOT the governed core.
                return True
    return False


# ---------------------------------------------------------------------------
# Control 1 — the governed-core target check
# ---------------------------------------------------------------------------


def is_governed_core_target(path: str | Path, roots: GovernedCoreRoots) -> bool:
    """True iff *path* is a governed-core target (identity-based; ADR-039 control 1).

    Fail-closed: ANY resolution/IO error → ``True`` (deny). A target is governed core
    if ANY of these deterministic identity checks trips:
      1. its realpath is contained under a governed-core root (symlink/junction), OR it
         shares the device+inode of a known governed-core ANCHOR file (anchor hardlink),
         OR it is an existing file with a link count > 1 (ANY hardlink — closes the
         non-anchor-core hardlink vector, F1),
      2. it is (inside) a git worktree whose main repo is a governed-core root, or
      3. it (or an ancestor) carries the governed-core identity markers (renamed clone).
    """
    target_resolved = _safe_resolve(path)
    if target_resolved is None:
        logger.warning("governed-core check: unresolvable target %r → DENY (fail-closed)", path)
        return True
    try:
        if _canonical_containment(target_resolved, roots):
            return True
        if _shares_inode_with_governed_core(target_resolved, roots):
            return True
        if _is_multiply_linked_existing(target_resolved):
            return True
        worktree_root = _worktree_main_root(target_resolved)
        if worktree_root is not None and _canonical_containment(worktree_root, roots):
            return True
        if _has_governed_core_identity(target_resolved):
            return True
        return False
    except Exception:  # noqa: BLE001 — a boundary check that errors must DENY
        logger.warning(
            "governed-core check raised on %r → DENY (fail-closed)", path, exc_info=True
        )
        return True


def derive_workspace_target(
    repo_id: str, *, projects_dir: str | Path
) -> Path | None:
    """Re-derive an execution target from a TRUSTED, structured field (the CaMeL rule).

    ADR-039 §2.2 control 1: the target of any proposal is derived by deterministic
    code from a validated, structured field (a repo id/name) checked against
    ``projects_dir`` — NEVER taken from model free text. *repo_id* must be a single
    plain path component (no separators, no ``..``, no drive/root, no absolute path);
    anything else returns ``None`` (fail-closed). The returned path is
    ``projects_dir / repo_id`` — its governed-core standing is still decided
    separately by :func:`check_target` (this function only fixes WHERE the target may
    be named from, closing the free-text-target injection vector)."""
    if not isinstance(repo_id, str):
        return None
    candidate = repo_id.strip()
    if not candidate:
        return None
    # Reject anything that is not a single, plain, relative path component.
    if candidate in (".", ".."):
        return None
    if "/" in candidate or "\\" in candidate:
        return None
    if candidate.startswith((".", "~")) or ":" in candidate:
        # No dotfiles/home-expansion/drive letters — a workspace repo id is a plain name.
        return None
    try:
        pd = Path(projects_dir)
        # Path() of a single component keeps it a single component; guard anyway.
        derived = pd / candidate
        if derived.name != candidate or derived.parent != pd:
            return None
        return derived
    except (OSError, ValueError):
        return None


def check_target(
    target: str | Path,
    *,
    roots: GovernedCoreRoots,
    projects_dir: str | Path,
    phase: str = "",
) -> TargetVerdict:
    """The governed-core target check — run at STAGING and re-run at EXECUTION (TOCTOU).

    DENY (fail-closed) unless the target is BOTH (a) not governed core (control 1's
    three layers) AND (b) contained under the configured ``projects_dir`` (the
    workspace). Pure function of the CURRENT filesystem state, so re-running it at
    execution catches a world that changed after staging. *phase* is carried on the
    verdict for audit ("STAGING"/"EXECUTION")."""
    resolved = _safe_resolve(target)
    if resolved is None:
        return TargetVerdict(
            BoundaryDecision.DENY,
            "target path could not be resolved (fail-closed)",
            phase=phase,
        )
    if is_governed_core_target(resolved, roots):
        return TargetVerdict(
            BoundaryDecision.DENY,
            "target resolves into the governed core — BlarAI has zero write path to "
            "itself (ADR-039 §2.1); refused by identity, not by name",
            resolved_target=str(resolved),
            phase=phase,
        )
    projects_resolved = _safe_resolve(projects_dir)
    if projects_resolved is None:
        return TargetVerdict(
            BoundaryDecision.DENY,
            "projects_dir could not be resolved (fail-closed)",
            resolved_target=str(resolved),
            phase=phase,
        )
    if not _is_contained(resolved, projects_resolved):
        return TargetVerdict(
            BoundaryDecision.DENY,
            f"target is outside the configured projects dir ({projects_resolved})",
            resolved_target=str(resolved),
            phase=phase,
        )
    return TargetVerdict(
        BoundaryDecision.ALLOW,
        "workspace target (not governed core; under projects dir)",
        resolved_target=str(resolved),
        phase=phase,
    )


def assert_workspace_target(
    target: str | Path,
    *,
    roots: GovernedCoreRoots,
    projects_dir: str | Path,
    phase: str = "",
) -> Path:
    """Return the resolved target if it is a workspace target, else RAISE (refuse).

    The raise-on-deny wrapper of :func:`check_target` for staging/execution call
    sites: it converts a DENY verdict into :class:`SelfGovernanceBoundaryError`
    (refuse-to-stage / refuse-to-execute)."""
    verdict = check_target(target, roots=roots, projects_dir=projects_dir, phase=phase)
    if verdict.denied:
        raise SelfGovernanceBoundaryError(
            f"self-governance boundary [{phase or 'check'}]: {verdict.reason} "
            f"(target={target!r})"
        )
    return Path(verdict.resolved_target)


# ---------------------------------------------------------------------------
# Control 4 — configuration immutability from inside
# ---------------------------------------------------------------------------


def is_protected_config_section(section: str | None) -> bool:
    """True iff *section* is a security/governance-critical config section (control 4).

    The coordinator surface (tools, proposals, ``propose_preference``) may never
    read-write these from inside (ADR-039 §2.2 control 4). Case-insensitive."""
    if not isinstance(section, str):
        return False
    return section.strip().lower() in PROTECTED_CONFIG_SECTIONS


def check_config_write(
    *,
    section: str | None = None,
    target_path: str | Path | None = None,
    roots: GovernedCoreRoots | None = None,
) -> ConfigWriteVerdict:
    """Control 4 — refuse any inside-write to runtime configuration.

    DENY (fail-closed) if the write names a protected config *section*, names a
    protected config *file* (by basename), or targets a path that resolves into the
    governed core. A path-bearing check REQUIRES ``roots``: a ``target_path`` given with
    ``roots=None`` cannot verify governed-core containment, so it DENIES (fail-closed —
    SG-review F3; it previously fell through to ALLOW, letting ``pyproject.toml`` /
    ``.mcp.json`` / a manifest path slip past the 2-name basename list). This is the
    enforcement point for "no tool/proposal/preference — ``propose_preference``
    explicitly included — may read-write ``[coordinator]``/autonomy/policy/security
    config" (SG-review F3).

    A call that names NEITHER a section nor a path is treated as malformed and DENIED
    (fail-closed — a config-write request we cannot characterise is refused)."""
    if section is None and target_path is None:
        return ConfigWriteVerdict(
            BoundaryDecision.DENY,
            "config-write request names neither a section nor a path (fail-closed)",
        )
    if is_protected_config_section(section):
        return ConfigWriteVerdict(
            BoundaryDecision.DENY,
            f"section [{str(section).strip().lower()}] is a protected config section — "
            "config is governed core and changes travel the human dev channel only "
            "(ADR-039 §2.2 control 4)",
        )
    if target_path is not None:
        try:
            basename = Path(target_path).name.strip().lower()
        except (OSError, ValueError):
            basename = ""
        if basename in PROTECTED_CONFIG_BASENAMES:
            return ConfigWriteVerdict(
                BoundaryDecision.DENY,
                f"target names a protected config file ({basename}) — refused "
                "(ADR-039 §2.2 control 4)",
            )
        if roots is None:
            return ConfigWriteVerdict(
                BoundaryDecision.DENY,
                "config-write names a path but no governed-core roots were supplied to "
                "verify containment — refused (fail-closed): a path-bearing check cannot "
                "prove the target is outside the governed core without roots (ADR-039 "
                "§2.2 control 4 + control 1; SG-review F3)",
            )
        if is_governed_core_target(target_path, roots):
            return ConfigWriteVerdict(
                BoundaryDecision.DENY,
                "config write targets a path inside the governed core (ADR-039 §2.2 "
                "control 4 + control 1)",
            )
    return ConfigWriteVerdict(
        BoundaryDecision.ALLOW,
        "not a protected config write",
    )
