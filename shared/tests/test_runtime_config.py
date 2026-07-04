"""Tests for shared.runtime_config — resolve_service_config_path()."""
from __future__ import annotations

import os
import sys
import pytest
from pathlib import Path

from shared.runtime_config import (
    RUNTIME_MODE_ENV,
    ConfigResolutionError,
    DeploymentMode,
    build_failure_fingerprint,
    parse_deployment_mode,
    resolve_deployment_mode,
    resolve_service_config_path,
    resolve_service_root,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _can_symlink(tmp_path: Path) -> bool:
    """Return True when the OS / privilege level supports symlink creation."""
    test_link = tmp_path / "_probe_link"
    test_target = tmp_path / "_probe_target"
    test_target.write_text("x")
    try:
        test_link.symlink_to(test_target)
        return True
    except (OSError, NotImplementedError):
        return False
    finally:
        test_link.unlink(missing_ok=True)
        test_target.unlink(missing_ok=True)


def _make_service_root(tmp_path: Path, mode: DeploymentMode) -> Path:
    """Create a minimal service root with a valid config file for *mode*."""
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    filename = "default.toml" if mode == DeploymentMode.HOST else "guest_runtime.toml"
    (config_dir / filename).write_text("[service]\n")
    return tmp_path


# ---------------------------------------------------------------------------
# Happy-path
# ---------------------------------------------------------------------------


class TestResolveServiceConfigPathHappyPath:
    """P2-2: resolve_service_config_path returns a real path for valid input."""

    def test_host_mode_default_config(self, tmp_path: Path) -> None:
        """HOST mode resolves to default.toml."""
        service_root = _make_service_root(tmp_path, DeploymentMode.HOST)
        result = resolve_service_config_path(service_root, deployment_mode=DeploymentMode.HOST)
        assert result == service_root / "config" / "default.toml"
        assert result.is_file()

    def test_guest_mode_default_config(self, tmp_path: Path) -> None:
        """GUEST mode resolves to guest_runtime.toml."""
        service_root = _make_service_root(tmp_path, DeploymentMode.GUEST)
        result = resolve_service_config_path(service_root, deployment_mode=DeploymentMode.GUEST)
        assert result == service_root / "config" / "guest_runtime.toml"
        assert result.is_file()


# ---------------------------------------------------------------------------
# Symlink guard (P2-2)
# ---------------------------------------------------------------------------


class TestSymlinkGuard:
    """P2-2: symlink paths are rejected with CFG_SYMLINK_REJECTED."""

    def test_symlink_rejected(self, tmp_path: Path) -> None:
        """A symlinked config file must raise ConfigResolutionError(CFG_SYMLINK_REJECTED)."""
        if not _can_symlink(tmp_path):
            pytest.skip("Symlink creation requires elevated privileges on this system.")

        config_dir = tmp_path / "config"
        config_dir.mkdir()

        # Create a real file outside the config dir and symlink to it
        real_file = tmp_path / "real_default.toml"
        real_file.write_text("[service]\n")

        link = config_dir / "default.toml"
        link.symlink_to(real_file)

        with pytest.raises(ConfigResolutionError) as exc_info:
            resolve_service_config_path(tmp_path, deployment_mode=DeploymentMode.HOST)

        assert exc_info.value.code == "CFG_SYMLINK_REJECTED"

    def test_symlink_guard_message_contains_path(self, tmp_path: Path) -> None:
        """CFG_SYMLINK_REJECTED error message must include the offending path."""
        if not _can_symlink(tmp_path):
            pytest.skip("Symlink creation requires elevated privileges on this system.")

        config_dir = tmp_path / "config"
        config_dir.mkdir()

        real_file = tmp_path / "real_default.toml"
        real_file.write_text("[service]\n")
        (config_dir / "default.toml").symlink_to(real_file)

        with pytest.raises(ConfigResolutionError) as exc_info:
            resolve_service_config_path(tmp_path, deployment_mode=DeploymentMode.HOST)

        assert "default.toml" in exc_info.value.message


# ---------------------------------------------------------------------------
# Missing file
# ---------------------------------------------------------------------------


class TestMissingConfigFile:
    """Missing config file raises CFG_PATH_MISSING."""

    def test_missing_file_raises(self, tmp_path: Path) -> None:
        """Empty config dir → CFG_PATH_MISSING."""
        (tmp_path / "config").mkdir()

        with pytest.raises(ConfigResolutionError) as exc_info:
            resolve_service_config_path(tmp_path, deployment_mode=DeploymentMode.HOST)

        assert exc_info.value.code == "CFG_PATH_MISSING"


# ---------------------------------------------------------------------------
# Mode mismatch
# ---------------------------------------------------------------------------


class TestModeMismatch:
    """Config file whose name does not match deployment mode raises CFG_MODE_CONFIG_MISMATCH."""

    def test_guest_file_with_host_mode(self, tmp_path: Path) -> None:
        """Explicit path pointing at guest file while mode=HOST → CFG_MODE_CONFIG_MISMATCH."""
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        guest_cfg = config_dir / "guest_runtime.toml"
        guest_cfg.write_text("[service]\n")

        with pytest.raises(ConfigResolutionError) as exc_info:
            resolve_service_config_path(
                tmp_path,
                deployment_mode=DeploymentMode.HOST,
                explicit_config_path=guest_cfg,
            )

        assert exc_info.value.code == "CFG_MODE_CONFIG_MISMATCH"


# ---------------------------------------------------------------------------
# EA-4: TestResolveServiceRoot — WI-1
# ---------------------------------------------------------------------------


class TestResolveServiceRoot:
    """Sprint 8 EA-4 WI-1: resolve_service_root normal Python + PyInstaller frozen."""

    def test_normal_python_returns_real_directory(self, tmp_path: Path) -> None:
        """Without sys._MEIPASS, returns parents[1] of the module file."""
        fake_module = tmp_path / "pkg" / "module.py"
        fake_module.parent.mkdir(parents=True)
        fake_module.write_text("")

        result = resolve_service_root(str(fake_module), "pkg")

        assert result == tmp_path
        assert result.is_dir()

    def test_pyinstaller_frozen_uses_meipass(self, monkeypatch, tmp_path: Path) -> None:
        """With sys._MEIPASS set, returns MEIPASS/<package_path>."""
        meipass = tmp_path / "meipass"
        (meipass / "services" / "policy_agent").mkdir(parents=True)
        monkeypatch.setattr(sys, "_MEIPASS", str(meipass), raising=False)

        result = resolve_service_root("/unused/module.py", "services.policy_agent")

        assert result == meipass / "services" / "policy_agent"


# ---------------------------------------------------------------------------
# EA-4: TestResolveDeploymentMode — WI-2
# ---------------------------------------------------------------------------


class TestResolveDeploymentMode:
    """Sprint 8 EA-4 WI-2: resolve_deployment_mode precedence."""

    def test_explicit_parameter_host(self, monkeypatch) -> None:
        """Explicit 'host' string returns DeploymentMode.HOST regardless of env."""
        monkeypatch.setenv(RUNTIME_MODE_ENV, "guest")
        assert resolve_deployment_mode("host") == DeploymentMode.HOST

    def test_environment_variable(self, monkeypatch) -> None:
        """Env var BLARAI_RUNTIME_MODE=guest → DeploymentMode.GUEST."""
        monkeypatch.setenv(RUNTIME_MODE_ENV, "guest")
        assert resolve_deployment_mode() == DeploymentMode.GUEST

    def test_default_is_host_when_env_absent(self, monkeypatch) -> None:
        """With explicit=None and env absent, default = HOST."""
        monkeypatch.delenv(RUNTIME_MODE_ENV, raising=False)
        assert resolve_deployment_mode() == DeploymentMode.HOST


# ---------------------------------------------------------------------------
# EA-4: TestParseDeploymentMode — WI-3
# ---------------------------------------------------------------------------


class TestParseDeploymentMode:
    """Sprint 8 EA-4 WI-3: parse_deployment_mode string parsing."""

    def test_parse_host(self) -> None:
        assert parse_deployment_mode("host") == DeploymentMode.HOST

    def test_parse_guest(self) -> None:
        assert parse_deployment_mode("guest") == DeploymentMode.GUEST

    def test_parse_invalid_raises_config_resolution_error(self) -> None:
        """Invalid mode raises ConfigResolutionError (subclass of ValueError) with CFG_MODE_INVALID."""
        with pytest.raises(ValueError) as exc_info:
            parse_deployment_mode("invalid_mode")
        assert isinstance(exc_info.value, ConfigResolutionError)
        assert exc_info.value.code == "CFG_MODE_INVALID"


# ---------------------------------------------------------------------------
# EA-4: TestBuildFailureFingerprint — WI-4
# ---------------------------------------------------------------------------


class TestBuildFailureFingerprint:
    """Sprint 8 EA-4 WI-4: build_failure_fingerprint structure + keys."""

    def test_structure_has_expected_values(self) -> None:
        """All expected fields present with correct FAIL disposition."""
        result = build_failure_fingerprint(
            stage="TEST_STAGE",
            code="TEST_CODE",
            message="test message",
        )
        assert isinstance(result, dict)
        assert result["stage"] == "TEST_STAGE"
        assert result["code"] == "TEST_CODE"
        assert result["message"] == "test message"
        assert result["disposition"] == "FAIL"
        assert result["fail_closed"] == "true"

    def test_required_keys_exact_set(self) -> None:
        """Key set is exactly {stage, code, message, disposition, fail_closed} — no extras."""
        result = build_failure_fingerprint(stage="S", code="C", message="M")
        assert set(result.keys()) == {"stage", "code", "message", "disposition", "fail_closed"}
