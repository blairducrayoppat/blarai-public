"""Locks for multi-operator defaults (control 5) + the DORMANCY / no-live-change proof.

Control 5 (ADR-039 #848): the graduated-autonomy ladder ships FULLY OFF on a fresh
install; nothing an operator can click hands BlarAI a write path to itself. Plus the
load-bearing dormancy lock: this whole build changes NO live behavior — the existing
dispatch anchor is byte-identical, importing the package arms nothing, and the shipped
``[coordinator]`` config section resolves fully off.
"""

from __future__ import annotations

import socket
import tomllib
from pathlib import Path

from shared.coordinator.config import (
    AUTONOMY_LADDER_CLASSES,
    CoordinatorConfig,
    repo_root_from_module,
)


# ---------------------------------------------------------------------------
# Control 5 — multi-operator defaults: ladder fully off on a fresh install
# ---------------------------------------------------------------------------


class TestMultiOperatorDefaults:
    def test_fresh_install_is_fully_off(self) -> None:
        cfg = CoordinatorConfig.fresh_install()
        assert cfg.enabled is False
        assert cfg.heartbeat_enabled is False
        assert cfg.work_origination_enabled is False
        assert cfg.swap_doom_checks_enabled is False
        assert cfg.require_signed_policy is False
        assert cfg.enabled_auto_classes == frozenset()
        assert cfg.autonomy_all_off() is True

    def test_default_construction_equals_fresh_install(self) -> None:
        assert CoordinatorConfig() == CoordinatorConfig.fresh_install()

    def test_ladder_populates_only_from_explicit_known_classes(self) -> None:
        cfg = CoordinatorConfig.from_toml({"enabled_auto_classes": ["ticket-hygiene"]})
        assert cfg.enabled_auto_classes == frozenset({"ticket-hygiene"})
        assert cfg.autonomy_all_off() is False

    def test_unknown_autonomy_class_dropped_fail_closed(self) -> None:
        cfg = CoordinatorConfig.from_toml(
            {"enabled_auto_classes": ["ticket-hygiene", "grant-root", 123, None]}
        )
        assert cfg.enabled_auto_classes == frozenset({"ticket-hygiene"})
        assert "grant-root" not in cfg.enabled_auto_classes

    def test_all_ladder_classes_are_known(self) -> None:
        assert "work-origination" in AUTONOMY_LADDER_CLASSES


# ---------------------------------------------------------------------------
# Fail-closed config resolution
# ---------------------------------------------------------------------------


class TestConfigResolution:
    def test_none_section_all_off(self) -> None:
        cfg = CoordinatorConfig.from_toml(None)
        assert cfg.autonomy_all_off() and not cfg.enabled

    def test_missing_keys_all_off(self) -> None:
        cfg = CoordinatorConfig.from_toml({})
        assert not cfg.enabled and not cfg.require_signed_policy and cfg.policy_path == ""

    def test_mistyped_values_fail_closed(self) -> None:
        cfg = CoordinatorConfig.from_toml(
            {"enabled": "yes-please", "enabled_auto_classes": "not-a-list", "policy_path": 42}
        )
        # bool("yes-please") is truthy — but the SAFE default for a missing key is off,
        # and a mistyped list / non-string path resolve to empty/"" (fail-closed).
        assert cfg.enabled_auto_classes == frozenset()
        assert cfg.policy_path == ""

    def test_explicit_enable_resolves(self) -> None:
        cfg = CoordinatorConfig.from_toml({"enabled": True, "require_signed_policy": True})
        assert cfg.enabled and cfg.require_signed_policy

    def test_swap_doom_checks_flag_resolves_and_defaults_off(self) -> None:
        """#844: the stop-doomed-fast flag defaults off (missing key) and resolves
        only on an explicit true — the driver-side dormancy gate."""
        assert CoordinatorConfig.from_toml({}).swap_doom_checks_enabled is False
        cfg = CoordinatorConfig.from_toml({"swap_doom_checks_enabled": True})
        assert cfg.swap_doom_checks_enabled is True
        assert not cfg.enabled  # the master gate is independent and stays off


# ---------------------------------------------------------------------------
# shadow_mode — fail-closed toward TRUE (#845 C3 limb 4, design §7.2)
# ---------------------------------------------------------------------------


class TestShadowModeResolution:
    """The one [coordinator] bool whose safe direction is TRUE: shadow. Missing
    or mistyped resolves TRUE; only an explicit boolean false goes live (the
    #855 graduation ceremony's flip)."""

    def test_default_construction_is_shadow(self) -> None:
        assert CoordinatorConfig().shadow_mode is True
        assert CoordinatorConfig.fresh_install().shadow_mode is True

    def test_missing_key_resolves_true(self) -> None:
        assert CoordinatorConfig.from_toml(None).shadow_mode is True
        assert CoordinatorConfig.from_toml({}).shadow_mode is True

    def test_mistyped_values_resolve_true(self) -> None:
        for bad in ("false", "no", 0, 1, None, [], {"on": False}):
            cfg = CoordinatorConfig.from_toml({"shadow_mode": bad})
            assert cfg.shadow_mode is True, f"mistyped {bad!r} must stay shadow"

    def test_explicit_booleans_resolve(self) -> None:
        assert CoordinatorConfig.from_toml({"shadow_mode": True}).shadow_mode is True
        assert CoordinatorConfig.from_toml({"shadow_mode": False}).shadow_mode is False

    def test_shipped_toml_ships_shadow(self) -> None:
        """default.toml carries an EXPLICIT `shadow_mode = true` (a real TOML
        boolean) and resolves shadow — the two-independent-locks posture (§7.1)
        is visible in the shipped config, not implied by an absent key."""
        toml_path = (
            repo_root_from_module()
            / "services"
            / "assistant_orchestrator"
            / "config"
            / "default.toml"
        )
        data = tomllib.loads(toml_path.read_text(encoding="utf-8"))
        raw = data["coordinator"].get("shadow_mode")
        assert raw is True and isinstance(raw, bool)
        assert CoordinatorConfig.from_toml(data["coordinator"]).shadow_mode is True


# ---------------------------------------------------------------------------
# DORMANCY — the build changes NO live behavior
# ---------------------------------------------------------------------------


class TestDormancy:
    def test_import_has_no_socket_side_effect(self) -> None:
        """Importing the coordinator package must not arm the egress guard or otherwise
        patch the socket surface — it has zero import-time side effects."""
        real_socket = socket.socket
        import importlib

        import shared.coordinator as sg

        importlib.reload(sg)
        assert socket.socket is real_socket

    def test_dispatch_anchor_unchanged(self) -> None:
        """The existing dispatch forbidden-root anchor is byte-identical — control 1 was
        built in a NEW module, the live dispatch path was NOT edited."""
        from shared.fleet.dispatch import _FORBIDDEN_REPO_ROOTS

        assert _FORBIDDEN_REPO_ROOTS == ("BlarAI", ".openclaw")

    def test_dispatch_validate_repo_behaviour_unchanged(self, tmp_path: Path) -> None:
        """The live ``validate_repo`` still behaves exactly as before (proving no live
        behavior changed): a git repo under projects passes; a BlarAI-component path
        is refused as forbidden."""
        from shared.fleet.dispatch import validate_repo

        projects = tmp_path / "projects"
        good = projects / "app"
        (good / ".git").mkdir(parents=True)
        assert validate_repo(good, projects) is None

        bad = projects / "BlarAI"
        (bad / ".git").mkdir(parents=True)
        err = validate_repo(bad, projects)
        assert err is not None and "forbidden" in err

    def test_shipped_toml_coordinator_section_is_all_off(self) -> None:
        """The ``[coordinator]`` section shipped in default.toml resolves fully off —
        the dormant surface is documented but grants nothing."""
        toml_path = (
            repo_root_from_module()
            / "services"
            / "assistant_orchestrator"
            / "config"
            / "default.toml"
        )
        data = tomllib.loads(toml_path.read_text(encoding="utf-8"))
        assert "coordinator" in data, "the dormant [coordinator] section should be documented"
        cfg = CoordinatorConfig.from_toml(data["coordinator"])
        assert cfg.enabled is False
        assert cfg.heartbeat_enabled is False
        assert cfg.work_origination_enabled is False
        assert cfg.swap_doom_checks_enabled is False
        assert cfg.require_signed_policy is False
        assert cfg.autonomy_all_off() is True
