"""Adversarial regression locks for identity-based governed-core severance (ADR-039 #848).

Control 1 (governed-core target severance) + control 4 (config immutability). These are
the crown-jewel adversarial locks: a staged self-targeted proposal is refused INCLUDING
via symlink / junction / renamed-clone / worktree evasion, the refusal RE-FIRES at
execution against changed state (TOCTOU), and every boundary check fails CLOSED.

None of these rely on operator vigilance — they drive the deterministic checks directly
and assert the DENY/ALLOW verdict.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from shared.coordinator import config as sgconfig
from shared.coordinator.governed_core import (
    BoundaryDecision,
    SelfGovernanceBoundaryError,
    assert_workspace_target,
    check_config_write,
    check_target,
    derive_workspace_target,
    is_governed_core_target,
    is_protected_config_section,
)


# ---------------------------------------------------------------------------
# Helpers — build a governed-core tree + a disjoint workspace projects dir
# ---------------------------------------------------------------------------


def _make_governed_repo(root: Path) -> Path:
    """Create a directory tree carrying the governed-core identity markers."""
    root.mkdir(parents=True, exist_ok=True)
    (root / "CLAUDE.md").write_text("governed", encoding="utf-8")
    (root / "docs").mkdir(exist_ok=True)
    (root / "docs" / "DECISION_REGISTER.md").write_text("governed", encoding="utf-8")
    (root / "shared" / "fleet").mkdir(parents=True, exist_ok=True)
    (root / "shared" / "fleet" / "dispatch.py").write_text("governed", encoding="utf-8")
    return root


@pytest.fixture()
def topology(tmp_path: Path) -> tuple[Path, Path, sgconfig.GovernedCoreRoots]:
    """A disjoint (repo, projects, roots) topology — neither nested in the other."""
    repo = _make_governed_repo(tmp_path / "blarai")
    projects = tmp_path / "projects"
    projects.mkdir()
    roots = sgconfig.GovernedCoreRoots(repo_root=repo)
    return repo, projects, roots


def _make_junction(link: Path, target: Path) -> bool:
    """Create a Windows directory junction (no privilege needed). Returns success."""
    if sys.platform != "win32":
        return False
    try:
        result = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(link), str(target)],
            capture_output=True,
            text=True,
            timeout=10,
        )
        return result.returncode == 0 and link.exists()
    except (OSError, subprocess.SubprocessError):
        return False


# ---------------------------------------------------------------------------
# Baseline — a legitimate workspace target is allowed, the repo is denied
# ---------------------------------------------------------------------------


class TestBaseline:
    def test_workspace_target_allowed(self, topology) -> None:
        repo, projects, roots = topology
        (projects / "myapp").mkdir()
        v = check_target(projects / "myapp", roots=roots, projects_dir=projects, phase="STAGING")
        assert v.allowed and v.decision is BoundaryDecision.ALLOW

    def test_repo_root_denied_by_identity(self, topology) -> None:
        repo, projects, roots = topology
        assert is_governed_core_target(repo, roots) is True
        v = check_target(repo, roots=roots, projects_dir=projects)
        assert v.denied and "governed core" in v.reason

    def test_target_outside_projects_denied(self, topology) -> None:
        repo, projects, roots = topology
        outside = projects.parent / "somewhere-else"
        outside.mkdir()
        v = check_target(outside, roots=roots, projects_dir=projects)
        assert v.denied and "outside" in v.reason


# ---------------------------------------------------------------------------
# EVASION 1 — canonical realpath containment (symlink / junction)
# ---------------------------------------------------------------------------


class TestCanonicalRealpathContainment:
    def test_junction_into_governed_core_denied(self, topology) -> None:
        """A junction under the workspace pointing INTO the governed core is caught by
        its RESOLVED path, not its innocent name (the realpath-specific layer)."""
        repo, projects, roots = topology
        link = projects / "innocent-junction"
        # Point at repo/shared (a subdir with NO identity files at that level), so ONLY
        # canonical-realpath containment — not the identity layer — can catch it.
        if not _make_junction(link, repo / "shared"):
            pytest.skip("directory junctions unavailable on this platform")
        # The realpath collapses the junction to its target inside the governed core.
        assert link.resolve() == (repo / "shared").resolve()
        v = check_target(link, roots=roots, projects_dir=projects)
        assert v.denied and "governed core" in v.reason

    def test_symlink_into_governed_core_denied(self, topology) -> None:
        """A directory symlink into the governed core is likewise caught by realpath."""
        repo, projects, roots = topology
        link = projects / "innocent-symlink"
        try:
            os.symlink(repo / "shared", link, target_is_directory=True)
        except (OSError, NotImplementedError):
            pytest.skip("symlink creation unavailable (privilege) on this platform")
        v = check_target(link, roots=roots, projects_dir=projects)
        assert v.denied and "governed core" in v.reason

    def test_containment_logic_is_realpath_not_name(self, topology, monkeypatch) -> None:
        """The containment decision is OS-realpath-driven, not path-name matching:
        a target whose realpath resolves under a root is denied even when its literal
        path shares no component with the root."""
        repo, projects, roots = topology
        decoy = projects / "totally-unrelated-name"
        decoy.mkdir()
        # Simulate the OS resolving `decoy` to a path inside the governed core.
        real_resolve = Path.resolve

        def fake_resolve(self: Path, *a, **k):
            if self == decoy:
                return (repo / "shared").resolve()
            return real_resolve(self, *a, **k)

        monkeypatch.setattr(Path, "resolve", fake_resolve)
        v = check_target(decoy, roots=roots, projects_dir=projects)
        assert v.denied and "governed core" in v.reason


# ---------------------------------------------------------------------------
# EVASION 2 — git worktree resolution
# ---------------------------------------------------------------------------


class TestWorktreeResolution:
    def test_worktree_of_governed_core_denied(self, topology) -> None:
        """A linked git worktree of the governed core, placed under the workspace, is
        resolved to its main repo root and denied — even though its own files are real
        (not symlinks) and its path is innocent."""
        repo, projects, roots = topology
        # Fabricate the main repo's worktree admin dir.
        wt_admin = repo / ".git" / "worktrees" / "wt1"
        wt_admin.mkdir(parents=True)
        # The linked worktree under the workspace: real dir + a `.git` FILE pointer.
        wt = projects / "some-worktree"
        wt.mkdir()
        (wt / ".git").write_text(f"gitdir: {wt_admin}\n", encoding="utf-8")
        v = check_target(wt, roots=roots, projects_dir=projects)
        assert v.denied and "governed core" in v.reason

    def test_worktree_pointer_to_non_governed_repo_allowed(self, topology) -> None:
        """A worktree whose main repo is NOT governed core stays a workspace target."""
        repo, projects, roots = topology
        other_main = projects.parent / "other-repo"
        (other_main / ".git" / "worktrees" / "wtx").mkdir(parents=True)
        wt = projects / "legit-worktree"
        wt.mkdir()
        (wt / ".git").write_text(
            f"gitdir: {other_main / '.git' / 'worktrees' / 'wtx'}\n", encoding="utf-8"
        )
        v = check_target(wt, roots=roots, projects_dir=projects)
        assert v.allowed


# ---------------------------------------------------------------------------
# EVASION 3 — renamed-clone content identity
# ---------------------------------------------------------------------------


class TestRenamedCloneIdentity:
    def test_renamed_clone_under_projects_denied(self, topology) -> None:
        """A renamed CLONE (a genuinely separate tree carrying the identity markers)
        placed under the workspace is caught by CONTENT identity — realpath and worktree
        resolution both miss it (it is not a link and not a worktree)."""
        repo, projects, roots = topology
        clone = _make_governed_repo(projects / "totally-innocent")
        # Not a link, not a worktree — a real independent copy under projects.
        assert clone.resolve() == (projects / "totally-innocent").resolve()
        v = check_target(clone, roots=roots, projects_dir=projects)
        assert v.denied and "governed core" in v.reason

    def test_subdir_of_renamed_clone_denied(self, topology) -> None:
        """A dispatch target DEEP inside a renamed clone is caught via the ancestor walk."""
        repo, projects, roots = topology
        clone = _make_governed_repo(projects / "innocent")
        deep = clone / "services" / "widget"
        deep.mkdir(parents=True)
        v = check_target(deep, roots=roots, projects_dir=projects)
        assert v.denied and "governed core" in v.reason

    def test_sentinel_file_alone_denies(self, tmp_path: Path) -> None:
        """The dedicated single-file sentinel identifies a clone on its own."""
        repo = _make_governed_repo(tmp_path / "blarai")
        projects = tmp_path / "projects"
        projects.mkdir()
        roots = sgconfig.GovernedCoreRoots(repo_root=repo)
        marked = projects / "looks-fine"
        marked.mkdir()
        (marked / sgconfig.GOVERNED_CORE_SENTINEL_FILE).write_text("x", encoding="utf-8")
        v = check_target(marked, roots=roots, projects_dir=projects)
        assert v.denied and "governed core" in v.reason

    def test_innocent_project_allowed(self, topology) -> None:
        """A genuine workspace project (no identity markers) is NOT a false positive."""
        repo, projects, roots = topology
        proj = projects / "real-webapp"
        proj.mkdir()
        (proj / "README.md").write_text("my app", encoding="utf-8")
        (proj / "src").mkdir()
        v = check_target(proj, roots=roots, projects_dir=projects)
        assert v.allowed


# ---------------------------------------------------------------------------
# TOCTOU — the refusal re-fires at EXECUTION against changed state
# ---------------------------------------------------------------------------


class TestTOCTOU:
    def test_benign_at_staging_becomes_clone_at_execution(self, topology) -> None:
        """Stage a benign target (ALLOW); the world changes (identity markers appear);
        the SAME check at execution now REFUSES. Approval is not freshness."""
        repo, projects, roots = topology
        target = projects / "app"
        target.mkdir()
        (target / "README.md").write_text("benign", encoding="utf-8")

        staging = check_target(target, roots=roots, projects_dir=projects, phase="STAGING")
        assert staging.allowed  # passed the staging gate

        # World changes between staging and execution: the dir is now a clone in place.
        _make_governed_repo(target)

        execution = check_target(target, roots=roots, projects_dir=projects, phase="EXECUTION")
        assert execution.denied and execution.phase == "EXECUTION"

    def test_benign_at_staging_becomes_junction_at_execution(self, topology) -> None:
        """The classic TOCTOU swap: a benign dir is replaced by a junction into the
        governed core after staging; execution-time re-validation catches it."""
        repo, projects, roots = topology
        target = projects / "app2"
        target.mkdir()
        staging = check_target(target, roots=roots, projects_dir=projects, phase="STAGING")
        assert staging.allowed

        target.rmdir()
        if not _make_junction(target, repo / "shared"):
            pytest.skip("directory junctions unavailable on this platform")
        execution = check_target(target, roots=roots, projects_dir=projects, phase="EXECUTION")
        assert execution.denied

    def test_assert_workspace_target_raises_on_deny(self, topology) -> None:
        repo, projects, roots = topology
        with pytest.raises(SelfGovernanceBoundaryError):
            assert_workspace_target(repo, roots=roots, projects_dir=projects, phase="EXECUTION")


# ---------------------------------------------------------------------------
# CaMeL — the target is derived from trusted structured fields, never free text
# ---------------------------------------------------------------------------


class TestDeriveWorkspaceTarget:
    def test_plain_repo_id_derives(self, tmp_path: Path) -> None:
        got = derive_workspace_target("myapp", projects_dir=tmp_path)
        assert got == tmp_path / "myapp"

    @pytest.mark.parametrize(
        "hostile",
        [
            "../blarai",
            "..\\blarai",
            "a/b",
            "a\\b",
            "/etc/passwd",
            "C:\\Windows",
            "~/blarai",
            ".hidden",
            "..",
            ".",
            "",
            "   ",
        ],
    )
    def test_free_text_target_rejected(self, tmp_path: Path, hostile: str) -> None:
        """Untrusted free-text can never SELECT a target: anything but a single plain
        path component returns None (the CaMeL property)."""
        assert derive_workspace_target(hostile, projects_dir=tmp_path) is None

    def test_non_string_rejected(self, tmp_path: Path) -> None:
        assert derive_workspace_target(None, projects_dir=tmp_path) is None  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Fail-closed — a boundary check that errors must DENY, never allow
# ---------------------------------------------------------------------------


class TestFailClosed:
    def test_unresolvable_target_denied(self, topology) -> None:
        repo, projects, roots = topology
        # A NUL byte makes the path unresolvable on every platform.
        v = check_target("bad\x00path", roots=roots, projects_dir=projects)
        assert v.denied

    def test_is_governed_core_true_on_unresolvable(self, topology) -> None:
        repo, projects, roots = topology
        assert is_governed_core_target("bad\x00path", roots) is True

    def test_inner_exception_denies(self, topology, monkeypatch) -> None:
        """If a resolution layer raises unexpectedly, the check DENIES (fail-closed)."""
        repo, projects, roots = topology
        import shared.coordinator.governed_core as gc

        def boom(*a, **k):
            raise RuntimeError("simulated resolver failure")

        monkeypatch.setattr(gc, "_canonical_containment", boom)
        assert is_governed_core_target(projects / "x", roots) is True

    def test_empty_roots_still_denies_identity_target(self, tmp_path: Path) -> None:
        """Even with a mis-resolved (dropped) repo_root, an identity-bearing clone is
        still denied by the content layer — no single misconfig opens the door."""
        repo = _make_governed_repo(tmp_path / "blarai")
        projects = tmp_path / "projects"
        projects.mkdir()
        # A roots object whose only root fails to resolve (dropped by all_roots()).
        roots = sgconfig.GovernedCoreRoots(repo_root=Path("does-not-exist-\x00"))
        clone = _make_governed_repo(projects / "clone")
        assert is_governed_core_target(clone, roots) is True


# ---------------------------------------------------------------------------
# Control 4 — configuration immutability from inside
# ---------------------------------------------------------------------------


class TestConfigImmutability:
    @pytest.mark.parametrize("section", ["coordinator", "autonomy", "policy", "security", "pgov", "COORDINATOR"])
    def test_protected_sections_denied(self, section: str) -> None:
        assert is_protected_config_section(section) is True
        v = check_config_write(section=section)
        assert v.denied

    def test_unprotected_section_allowed(self) -> None:
        v = check_config_write(section="some_project_setting")
        assert v.allowed

    def test_config_file_basename_denied(self, tmp_path: Path) -> None:
        v = check_config_write(target_path=tmp_path / "sub" / "default.toml")
        assert v.denied and "config file" in v.reason

    def test_config_write_into_governed_core_denied(self, topology) -> None:
        repo, projects, roots = topology
        v = check_config_write(target_path=repo / "shared" / "x.py", roots=roots)
        assert v.denied

    def test_propose_preference_to_protected_section_denied(self) -> None:
        """SG-review F3: propose_preference is explicitly included — a preference write
        that names a protected config section is refused."""
        v = check_config_write(section="coordinator")
        assert v.denied and "control 4" in v.reason

    def test_malformed_config_write_denied(self) -> None:
        """A config-write request naming neither a section nor a path is refused."""
        v = check_config_write()
        assert v.denied


# ---------------------------------------------------------------------------
# SG-review F1 — inode identity: a HARDLINK to a governed-core file is denied
# ---------------------------------------------------------------------------


class TestHardlinkInodeIdentity:
    """A hardlink is a second directory entry for the SAME inode; its own path is
    genuinely under the workspace, so ``Path.resolve()`` cannot see through it. The
    inode-identity layer catches it — a write through an ALLOWED hardlink would have
    overwritten the real governed-core file (the reviewer's probe 1 overwrote dispatch.py)."""

    def test_hardlink_to_dispatch_denied(self, topology) -> None:
        repo, projects, roots = topology
        core_file = repo / "shared" / "fleet" / "dispatch.py"
        myapp = projects / "myapp"
        myapp.mkdir()
        hardlink = myapp / "harmless_looking.py"
        try:
            os.link(core_file, hardlink)
        except (OSError, NotImplementedError) as exc:  # pragma: no cover - platform gate
            pytest.skip(f"hardlinks unavailable on this platform: {exc}")
        # It IS the same on-disk file, yet resolve() keeps its innocent workspace path.
        assert os.path.samefile(hardlink, core_file)
        assert hardlink.resolve() == (myapp / "harmless_looking.py").resolve()
        # ...but identity catches it: governed core, denied at BOTH staging and execution.
        assert is_governed_core_target(hardlink, roots) is True
        for phase in ("STAGING", "EXECUTION"):
            v = check_target(hardlink, roots=roots, projects_dir=projects, phase=phase)
            assert v.denied and "governed core" in v.reason

    def test_hardlink_to_claude_md_denied(self, topology) -> None:
        repo, projects, roots = topology
        proj = projects / "notes-app"
        proj.mkdir()
        link = proj / "notes.md"
        try:
            os.link(repo / "CLAUDE.md", link)
        except (OSError, NotImplementedError) as exc:  # pragma: no cover - platform gate
            pytest.skip(f"hardlinks unavailable: {exc}")
        assert is_governed_core_target(link, roots) is True
        assert check_target(link, roots=roots, projects_dir=projects).denied

    def test_hardlink_to_decision_register_denied(self, topology) -> None:
        repo, projects, roots = topology
        proj = projects / "docs-app"
        proj.mkdir()
        link = proj / "reg.md"
        try:
            os.link(repo / "docs" / "DECISION_REGISTER.md", link)
        except (OSError, NotImplementedError) as exc:  # pragma: no cover - platform gate
            pytest.skip(f"hardlinks unavailable: {exc}")
        assert is_governed_core_target(link, roots) is True

    def test_new_workspace_file_not_flagged_by_inode(self, topology) -> None:
        """A genuinely new workspace file (its own fresh inode) is NOT a false positive
        from the inode layer — the fence still allows legitimate work."""
        repo, projects, roots = topology
        proj = projects / "webapp"
        proj.mkdir()
        newf = proj / "brand_new.py"
        newf.write_text("print('hi')", encoding="utf-8")
        assert is_governed_core_target(newf, roots) is False
        assert check_target(newf, roots=roots, projects_dir=projects).allowed

    def test_nonexistent_target_not_flagged_by_inode(self, topology) -> None:
        """A not-yet-created target (no inode) cannot alias a core file — allowed."""
        repo, projects, roots = topology
        proj = projects / "webapp2"
        proj.mkdir()
        assert is_governed_core_target(proj / "does_not_exist_yet.py", roots) is False

    def test_inode_layer_exception_denies(self, topology, monkeypatch) -> None:
        """Fail-closed: if the inode-identity layer raises on an existing target, the
        governed-core check DENIES (a boundary check that errors must deny)."""
        repo, projects, roots = topology
        import shared.coordinator.governed_core as gc

        def boom(*a, **k):
            raise OSError("simulated inode-layer failure")

        monkeypatch.setattr(gc, "_shares_inode_with_governed_core", boom)
        proj = projects / "webapp3"
        proj.mkdir()
        f = proj / "f.py"
        f.write_text("x", encoding="utf-8")
        assert is_governed_core_target(f, roots) is True


# ---------------------------------------------------------------------------
# SG-review F1 (non-anchor vector) — link-count: a HARDLINK to ANY core file is denied
# ---------------------------------------------------------------------------


class TestNonAnchorHardlinkLinkCount:
    """The inode-ANCHOR check compares a target only against a SMALL anchor fileset
    (sentinel + CLAUDE.md + DECISION_REGISTER.md + dispatch.py), but the governed core is
    the WHOLE tree. A hardlink placed under an allowed workspace path and aimed at a
    NON-anchor core file (``pyproject.toml``, ``launcher/config/default.toml``,
    ``shared/coordinator/config.py`` — the boundary's OWN policy data — or a PA policy
    module) aliases no anchor, and its own realpath is an innocent workspace path, so the
    anchor + canonical-containment layers BOTH miss it — yet a write through it mutates
    the linked core file. An independent re-verify proved these four returned ALLOW at
    EXECUTION before the fix. The link-count layer (``st_nlink > 1``) closes the gap,
    fail-closed: ANY already-multiply-linked existing target is refused, whatever it
    aliases (ADR-039 control 1, "zero write path to the governed core")."""

    # (relative-path-under-repo, innocent workspace basename) for each PROVEN evasion case.
    _NON_ANCHOR_CORE_FILES = [
        ("pyproject.toml", "totally_innocent.toml"),
        ("launcher/config/default.toml", "app_defaults.toml"),
        ("shared/coordinator/config.py", "helpers.py"),
        ("services/policy_agent/classifier.py", "sorter.py"),
    ]

    @staticmethod
    def _make_non_anchor_core_file(repo: Path, rel: str) -> Path:
        """Create a NON-anchor governed-core file at *rel* under the repo. The
        ``_make_governed_repo`` helper deliberately does NOT create these — F1 is
        precisely about the core files OUTSIDE the small anchor set."""
        core_file = repo / rel
        core_file.parent.mkdir(parents=True, exist_ok=True)
        core_file.write_text("core policy data", encoding="utf-8")
        return core_file

    @pytest.mark.parametrize("rel, workspace_name", _NON_ANCHOR_CORE_FILES)
    def test_hardlink_to_non_anchor_core_file_denied(
        self, topology, rel: str, workspace_name: str
    ) -> None:
        """Each of the four proven-evadable non-anchor core files, hardlinked into the
        workspace, is now DENIED — both directly and via ``check_target`` at EXECUTION."""
        import shared.coordinator.governed_core as gc

        repo, projects, roots = topology
        core_file = self._make_non_anchor_core_file(repo, rel)
        proj = projects / "myapp"
        proj.mkdir(exist_ok=True)
        hardlink = proj / workspace_name
        try:
            os.link(core_file, hardlink)
        except (OSError, NotImplementedError) as exc:  # pragma: no cover - platform gate
            pytest.skip(f"hardlinks unavailable on this platform: {exc}")

        resolved = hardlink.resolve()
        # It IS the same on-disk file, yet resolve() keeps its innocent workspace path.
        assert os.path.samefile(hardlink, core_file)
        assert resolved == (proj / workspace_name).resolve()
        # The link count IS observably > 1 on this host (NTFS reports >= 2 for a hardlink).
        assert os.stat(hardlink).st_nlink >= 2
        # PROVE the two prior layers MISS it (this is exactly the F1 evasion):
        assert gc._canonical_containment(resolved, roots) is False
        assert gc._shares_inode_with_governed_core(resolved, roots) is False
        # ...and the NEW link-count layer is what catches it:
        assert gc._is_multiply_linked_existing(resolved) is True

        # End-to-end: governed core, DENIED at BOTH staging and execution.
        assert is_governed_core_target(hardlink, roots) is True
        for phase in ("STAGING", "EXECUTION"):
            v = check_target(hardlink, roots=roots, projects_dir=projects, phase=phase)
            assert v.denied and "governed core" in v.reason, f"{rel} must DENY at {phase}"

    def test_link_count_helper_true_for_hardlink(self, topology) -> None:
        """The helper returns True for a genuinely multiply-linked file (unit-level)."""
        import shared.coordinator.governed_core as gc

        repo, projects, roots = topology
        core_file = self._make_non_anchor_core_file(repo, "pyproject.toml")
        proj = projects / "u1"
        proj.mkdir()
        link = proj / "x.toml"
        try:
            os.link(core_file, link)
        except (OSError, NotImplementedError) as exc:  # pragma: no cover - platform gate
            pytest.skip(f"hardlinks unavailable: {exc}")
        assert gc._is_multiply_linked_existing(link.resolve()) is True

    def test_link_count_helper_false_for_fresh_file(self, topology) -> None:
        """Over-denial guard: a NORMAL new workspace file has ``st_nlink == 1`` and is
        NOT flagged by the link-count layer — nor denied end-to-end."""
        import shared.coordinator.governed_core as gc

        repo, projects, roots = topology
        proj = projects / "u2"
        proj.mkdir()
        newf = proj / "brand_new.py"
        newf.write_text("print('hi')", encoding="utf-8")
        assert os.stat(newf).st_nlink == 1
        assert gc._is_multiply_linked_existing(newf.resolve()) is False
        # ...and the boundary still ALLOWS it (no over-denial regression).
        assert is_governed_core_target(newf, roots) is False
        assert check_target(newf, roots=roots, projects_dir=projects).allowed

    def test_link_count_helper_false_for_missing(self, topology) -> None:
        """A not-yet-existing target has no links (``FileNotFoundError`` → False) — the
        normal new-file case must never be pre-emptively denied by this layer."""
        import shared.coordinator.governed_core as gc

        repo, projects, roots = topology
        proj = projects / "u3"
        proj.mkdir()
        assert gc._is_multiply_linked_existing(proj / "does_not_exist_yet.py") is False

    def test_link_count_layer_exception_denies(self, topology, monkeypatch) -> None:
        """Fail-closed: if the link-count layer raises an unexpected error on an existing
        target, the governed-core check DENIES (a boundary check that errors must deny)."""
        import shared.coordinator.governed_core as gc

        repo, projects, roots = topology

        def boom(*a, **k):
            raise OSError("simulated link-count-layer failure")

        monkeypatch.setattr(gc, "_is_multiply_linked_existing", boom)
        proj = projects / "u4"
        proj.mkdir()
        f = proj / "f.py"
        f.write_text("x", encoding="utf-8")
        assert is_governed_core_target(f, roots) is True


# ---------------------------------------------------------------------------
# SG-review F3 — control 4: a path-bearing config check REQUIRES roots (else fail-closed)
# ---------------------------------------------------------------------------


class TestConfigImmutabilityRootsRequired:
    @pytest.mark.parametrize(
        "name", ["pyproject.toml", ".mcp.json", "manifest.json", "settings.json"]
    )
    def test_path_write_without_roots_denies(self, tmp_path: Path, name: str) -> None:
        """A config write that names a PATH but supplies no roots cannot verify
        governed-core containment, so it DENIES (fail-closed). These previously slipped
        through the 2-name basename list to ALLOW (the reviewer's probe 3)."""
        v = check_config_write(target_path=tmp_path / name)  # roots omitted
        assert v.denied, f"{name} must deny without roots (fail-closed)"

    def test_path_write_with_roots_into_governed_core_denies(self, topology) -> None:
        repo, projects, roots = topology
        v = check_config_write(target_path=repo / "pyproject.toml", roots=roots)
        assert v.denied

    def test_path_write_with_roots_to_workspace_allows(self, topology) -> None:
        """The fix denies only the UNVERIFIABLE (roots=None) case: a workspace-path config
        write WITH roots (target outside the governed core) is still allowed."""
        repo, projects, roots = topology
        proj = projects / "app"
        proj.mkdir()
        v = check_config_write(target_path=proj / "app_settings.toml", roots=roots)
        assert v.allowed

    def test_protected_basename_still_denies_without_roots(self, tmp_path: Path) -> None:
        """The belt-and-suspenders basename deny still fires first (specific message),
        even without roots — the F3 change did not weaken it."""
        v = check_config_write(target_path=tmp_path / "default.toml")
        assert v.denied and "config file" in v.reason
