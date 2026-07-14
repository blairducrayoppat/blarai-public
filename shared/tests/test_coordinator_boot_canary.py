"""Adversarial regression locks for the boot-time boundary canary (ADR-039 #848, control 6).

The canary proves — at every boot — that the coordinator surface CANNOT reach a
governed-core write path, and refuses to start otherwise. Proven here:

  * a correct topology passes (negative probes all deny, positive probe allows, policy ok);
  * the canary FAILS LOUD on a seeded misconfiguration (a governed-core target not denied,
    or a projects_dir nested inside the governed core), and ``assert_boot_boundary`` RAISES;
  * the positive probe rules out a blanket-deny "wall" masquerading as a boundary;
  * any exception in a probe fails closed → refuse-to-start.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from shared.coordinator import config as sgconfig
from shared.coordinator.boot_canary import (
    assert_boot_boundary,
    run_boot_canary,
)
from shared.coordinator.governed_core import (
    BoundaryDecision,
    SelfGovernanceBoundaryError,
    TargetVerdict,
)


def _make_governed_repo(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / "CLAUDE.md").write_text("x", encoding="utf-8")
    (root / "docs").mkdir(exist_ok=True)
    (root / "docs" / "DECISION_REGISTER.md").write_text("x", encoding="utf-8")
    (root / "shared" / "fleet").mkdir(parents=True, exist_ok=True)
    (root / "shared" / "fleet" / "dispatch.py").write_text("x", encoding="utf-8")
    return root


@pytest.fixture()
def topology(tmp_path: Path):
    repo = _make_governed_repo(tmp_path / "blarai")
    projects = tmp_path / "projects"
    projects.mkdir()
    roots = sgconfig.GovernedCoreRoots(repo_root=repo)
    cfg = sgconfig.CoordinatorConfig.fresh_install()
    return repo, projects, roots, cfg


class TestCanaryPasses:
    def test_correct_topology_passes(self, topology) -> None:
        repo, projects, roots, cfg = topology
        result = run_boot_canary(config=cfg, roots=roots, projects_dir=projects)
        assert result.ok is True
        assert result.failures() == ()
        # It probed BOTH directions: at least one negative and the positive.
        kinds = {p.kind for p in result.probes}
        assert "negative-target" in kinds and "positive-target" in kinds and "policy" in kinds

    def test_assert_boot_boundary_returns_on_pass(self, topology) -> None:
        repo, projects, roots, cfg = topology
        result = assert_boot_boundary(config=cfg, roots=roots, projects_dir=projects)
        assert result.ok


class TestCanaryFailsLoud:
    def test_negative_probe_failure_refuses_start(self, topology, monkeypatch) -> None:
        """Seed a BROKEN control 1 (a governed-core target NOT denied); the canary must
        catch it and refuse to start. This is the misconfiguration the canary exists for."""
        repo, projects, roots, cfg = topology
        import shared.coordinator.boot_canary as bc

        def broken_allow(target, **k):  # simulate a boundary that fails to deny
            return TargetVerdict(BoundaryDecision.ALLOW, "SIMULATED broken control", phase=k.get("phase", ""))

        monkeypatch.setattr(bc, "check_target", broken_allow)
        result = run_boot_canary(config=cfg, roots=roots, projects_dir=projects)
        assert result.ok is False
        assert any(p.kind == "negative-target" and not p.passed for p in result.probes)
        with pytest.raises(SelfGovernanceBoundaryError):
            assert_boot_boundary(config=cfg, roots=roots, projects_dir=projects)

    def test_projects_nested_in_governed_core_refuses_start(self, tmp_path: Path) -> None:
        """A genuine (non-mocked) misconfiguration: projects_dir configured INSIDE the
        governed core. The positive probe's workspace target resolves to governed core
        → over-deny → refuse-to-start."""
        repo = _make_governed_repo(tmp_path / "blarai")
        nested_projects = repo / "sub" / "projects"  # inside the governed core!
        nested_projects.mkdir(parents=True)
        roots = sgconfig.GovernedCoreRoots(repo_root=repo)
        cfg = sgconfig.CoordinatorConfig.fresh_install()
        result = run_boot_canary(config=cfg, roots=roots, projects_dir=nested_projects)
        assert result.ok is False
        assert any(p.kind == "positive-target" and not p.passed for p in result.probes)
        with pytest.raises(SelfGovernanceBoundaryError):
            assert_boot_boundary(config=cfg, roots=roots, projects_dir=nested_projects)

    def test_config_probe_failure_refuses_start(self, topology, monkeypatch) -> None:
        """A broken control 4 (config write not denied) also refuses start."""
        repo, projects, roots, cfg = topology
        import shared.coordinator.boot_canary as bc
        from shared.coordinator.governed_core import ConfigWriteVerdict

        monkeypatch.setattr(
            bc, "check_config_write",
            lambda **k: ConfigWriteVerdict(BoundaryDecision.ALLOW, "SIMULATED broken control 4"),
        )
        result = run_boot_canary(config=cfg, roots=roots, projects_dir=projects)
        assert result.ok is False
        assert any(p.kind == "negative-config" and not p.passed for p in result.probes)

    def test_tampered_policy_refuses_start(self, topology, tmp_path: Path) -> None:
        """require_signed_policy=true with no signature present → policy probe fails →
        refuse-to-start."""
        repo, projects, roots, _cfg = topology
        policy_file = tmp_path / "coordinator_policy.json"
        policy_file.write_text('{"version":"1.0.0"}', encoding="utf-8")  # NO .sig alongside
        cfg = sgconfig.CoordinatorConfig(
            enabled=True, require_signed_policy=True, policy_path=str(policy_file)
        )
        result = run_boot_canary(config=cfg, roots=roots, projects_dir=projects)
        assert result.ok is False
        assert any(p.kind == "policy" and not p.passed for p in result.probes)
        with pytest.raises(SelfGovernanceBoundaryError):
            assert_boot_boundary(config=cfg, roots=roots, projects_dir=projects)


class TestCanaryFailClosed:
    def test_probe_exception_refuses_start(self, topology, monkeypatch) -> None:
        """Any exception inside the canary → ok=False (a boundary check that errors DENIES)."""
        repo, projects, roots, cfg = topology
        import shared.coordinator.boot_canary as bc

        def boom(*a, **k):
            raise RuntimeError("simulated canary failure")

        monkeypatch.setattr(bc, "_negative_target_probes", boom)
        result = run_boot_canary(config=cfg, roots=roots, projects_dir=projects)
        assert result.ok is False and result.error is not None
        with pytest.raises(SelfGovernanceBoundaryError):
            assert_boot_boundary(config=cfg, roots=roots, projects_dir=projects)
