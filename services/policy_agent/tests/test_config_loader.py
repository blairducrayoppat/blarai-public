"""
Config Loader Tests — Policy Agent
=====================================
P1.2: Tests for TOML configuration loading (ACL, deny list, rate limit).
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from services.policy_agent.src.config_loader import (
    RateLimitConfig,
    ResourceDenyRule,
    RuleEngineConfig,
    load_acl_matrix,
    load_rate_limit_config,
    load_resource_deny_list,
    load_rule_engine_config,
)


class TestLoadAclMatrix:
    """ACL matrix TOML loading."""

    def test_load_valid_acl(self, tmp_path: Path) -> None:
        """Valid acl_matrix.toml produces correct dict."""
        acl_file = tmp_path / "acl_matrix.toml"
        acl_file.write_text(textwrap.dedent("""\
            [permissions]
            orch = ["substrate", "router"]
            code = ["substrate"]
            router = []
        """))
        result = load_acl_matrix(acl_file)
        assert result is not None
        assert result == {
            "orch": ["substrate", "router"],
            "code": ["substrate"],
            "router": [],
        }

    def test_missing_file_returns_none(self, tmp_path: Path) -> None:
        """Missing TOML file → None (Fail-Closed)."""
        result = load_acl_matrix(tmp_path / "nonexistent.toml")
        assert result is None

    def test_malformed_toml_returns_none(self, tmp_path: Path) -> None:
        """Invalid TOML syntax → None."""
        acl_file = tmp_path / "bad.toml"
        acl_file.write_text("[permissions\nbroken = ")
        result = load_acl_matrix(acl_file)
        assert result is None

    def test_non_list_value_returns_none(self, tmp_path: Path) -> None:
        """Agent with non-list value → None (validation failure)."""
        acl_file = tmp_path / "acl.toml"
        acl_file.write_text(textwrap.dedent("""\
            [permissions]
            orch = "not_a_list"
        """))
        result = load_acl_matrix(acl_file)
        assert result is None

    def test_missing_permissions_section(self, tmp_path: Path) -> None:
        """TOML without [permissions] → empty dict (no agents)."""
        acl_file = tmp_path / "acl.toml"
        acl_file.write_text("[other]\nfoo = 1\n")
        result = load_acl_matrix(acl_file)
        assert result is not None
        assert result == {}


class TestLoadResourceDenyList:
    """Resource deny list TOML loading."""

    def test_load_valid_deny_list(self, tmp_path: Path) -> None:
        """Valid deny_list.toml produces correct ResourceDenyRule list."""
        deny_file = tmp_path / "deny_list.toml"
        deny_file.write_text(textwrap.dedent("""\
            [[deny_rules]]
            verb = ""
            resource_pattern = "system.shutdown"
            reason = "Prohibited"

            [[deny_rules]]
            verb = "DELETE"
            resource_pattern = "substrate.*"
            reason = "No delete"
        """))
        result = load_resource_deny_list(deny_file)
        assert result is not None
        assert len(result) == 2
        assert result[0] == ResourceDenyRule(verb=None, resource_pattern="system.shutdown", reason="Prohibited")
        assert result[1] == ResourceDenyRule(verb="DELETE", resource_pattern="substrate.*", reason="No delete")

    def test_empty_verb_becomes_none(self, tmp_path: Path) -> None:
        """Empty string verb in TOML → None (matches all verbs)."""
        deny_file = tmp_path / "deny.toml"
        deny_file.write_text(textwrap.dedent("""\
            [[deny_rules]]
            verb = ""
            resource_pattern = "anything"
            reason = "test"
        """))
        result = load_resource_deny_list(deny_file)
        assert result is not None
        assert result[0].verb is None

    def test_missing_file_returns_none(self, tmp_path: Path) -> None:
        """Missing file → None."""
        result = load_resource_deny_list(tmp_path / "nope.toml")
        assert result is None

    def test_missing_pattern_returns_none(self, tmp_path: Path) -> None:
        """Rule without resource_pattern → None."""
        deny_file = tmp_path / "deny.toml"
        deny_file.write_text(textwrap.dedent("""\
            [[deny_rules]]
            verb = "READ"
            reason = "no pattern"
        """))
        result = load_resource_deny_list(deny_file)
        assert result is None

    def test_no_deny_rules_returns_empty_list(self, tmp_path: Path) -> None:
        """TOML with no [[deny_rules]] → empty list."""
        deny_file = tmp_path / "deny.toml"
        deny_file.write_text("[metadata]\nversion = 1\n")
        result = load_resource_deny_list(deny_file)
        assert result is not None
        assert result == []

    def test_verb_uppercased(self, tmp_path: Path) -> None:
        """Verb string is uppercased for consistent matching."""
        deny_file = tmp_path / "deny.toml"
        deny_file.write_text(textwrap.dedent("""\
            [[deny_rules]]
            verb = "delete"
            resource_pattern = "foo"
            reason = "test"
        """))
        result = load_resource_deny_list(deny_file)
        assert result is not None
        assert result[0].verb == "DELETE"


class TestLoadRateLimitConfig:
    """Rate limit config extraction from main config."""

    def test_explicit_values(self) -> None:
        """[rate] section with explicit values."""
        data = {"rate": {"max_requests_per_window": 50, "window_seconds": 30.0}}
        cfg = load_rate_limit_config(data)
        assert cfg.max_requests_per_window == 50
        assert cfg.window_seconds == 30.0

    def test_defaults_on_missing_section(self) -> None:
        """Missing [rate] section → defaults."""
        cfg = load_rate_limit_config({})
        assert cfg.max_requests_per_window == 100
        assert cfg.window_seconds == 60.0


class TestLoadRuleEngineConfig:
    """Full config directory loading."""

    def _write_config_dir(self, tmp_path: Path) -> Path:
        """Write a minimal valid config directory."""
        (tmp_path / "default.toml").write_text(textwrap.dedent("""\
            [rules]
            version = "2.0.0"
            [rate]
            max_requests_per_window = 200
            window_seconds = 120.0
        """))
        (tmp_path / "acl_matrix.toml").write_text(textwrap.dedent("""\
            [permissions]
            orch = ["substrate"]
        """))
        (tmp_path / "deny_list.toml").write_text(textwrap.dedent("""\
            [[deny_rules]]
            verb = ""
            resource_pattern = "system.*"
            reason = "blocked"
        """))
        return tmp_path

    def test_full_load_success(self, tmp_path: Path) -> None:
        """Full config load with all files present."""
        config_dir = self._write_config_dir(tmp_path)
        cfg = load_rule_engine_config(config_dir)
        assert cfg is not None
        assert cfg.version == "2.0.0"
        assert cfg.acl_matrix == {"orch": ["substrate"]}
        assert len(cfg.resource_deny_rules) == 1
        assert cfg.rate_limit.max_requests_per_window == 200
        assert cfg.rate_limit.window_seconds == 120.0

    def test_missing_acl_returns_none(self, tmp_path: Path) -> None:
        """Missing acl_matrix.toml → None (Fail-Closed)."""
        (tmp_path / "default.toml").write_text("[rules]\nversion = '1.0.0'\n")
        (tmp_path / "deny_list.toml").write_text("")
        cfg = load_rule_engine_config(tmp_path)
        assert cfg is None

    def test_missing_deny_list_returns_none(self, tmp_path: Path) -> None:
        """Missing deny_list.toml → None (Fail-Closed)."""
        (tmp_path / "default.toml").write_text("[rules]\nversion = '1.0.0'\n")
        (tmp_path / "acl_matrix.toml").write_text("[permissions]\norch = []\n")
        cfg = load_rule_engine_config(tmp_path)
        assert cfg is None

    def test_missing_default_toml_returns_none(self, tmp_path: Path) -> None:
        """Missing default.toml → None."""
        (tmp_path / "acl_matrix.toml").write_text("[permissions]\norch = []\n")
        (tmp_path / "deny_list.toml").write_text("")
        cfg = load_rule_engine_config(tmp_path)
        assert cfg is None

    def test_load_real_config_dir(self) -> None:
        """Load the actual config directory shipped with the service."""
        import pathlib
        config_dir = pathlib.Path(__file__).resolve().parent.parent / "config"
        cfg = load_rule_engine_config(config_dir)
        assert cfg is not None
        assert cfg.version == "1.0.0"
        # Validate known agents from acl_matrix.toml
        assert "assistant_orchestrator" in cfg.acl_matrix
        assert "substrate" in cfg.acl_matrix["assistant_orchestrator"]
        # Validate deny rules loaded
        assert len(cfg.resource_deny_rules) >= 5
