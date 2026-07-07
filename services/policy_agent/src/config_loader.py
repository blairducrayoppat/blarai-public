"""
Rule Engine Configuration Loader — Policy Agent
=================================================
USE-CASE-001, P1.2: Load versioned TOML configs for the deterministic
rule engine at boot time.

Loaded configs:
  1. ACL matrix:        config/acl_matrix.toml  → agent → service permissions
  2. Resource deny list: config/deny_list.toml   → resource-specific deny rules
  3. Rate limits:       config/default.toml [rate] → per-agent sliding window

Security:
  - Fail-Closed: if any config file is missing or malformed, the loader
    returns None and the rule engine defaults to DENY.
  - All paths are relative to the service root — no user-supplied paths.
  - No external network calls.
"""

from __future__ import annotations

import logging
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Typed config structures
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ResourceDenyRule:
    """A single resource deny rule from deny_list.toml."""

    verb: str | None
    """Action verb constraint. None = applies to all verbs."""

    resource_pattern: str
    """fnmatch-style pattern matched against CAR.resource."""

    reason: str
    """Human-readable reason for the deny (audit trail)."""


@dataclass(frozen=True)
class RateLimitConfig:
    """Per-agent rate limiting parameters."""

    max_requests_per_window: int = 100
    """Maximum requests per agent within the sliding window."""

    window_seconds: float = 60.0
    """Sliding window duration in seconds."""


@dataclass(frozen=True)
class RuleEngineConfig:
    """Aggregated rule engine configuration loaded from TOML files."""

    acl_matrix: dict[str, list[str]] = field(default_factory=dict)
    """Agent → list of allowed destination services."""

    resource_deny_rules: list[ResourceDenyRule] = field(default_factory=list)
    """Ordered list of resource deny rules."""

    rate_limit: RateLimitConfig = field(default_factory=RateLimitConfig)
    """Rate limiting configuration."""

    version: str = "1.0.0"
    """Rule engine config version for audit trail."""


# ---------------------------------------------------------------------------
# TOML loaders
# ---------------------------------------------------------------------------

def load_acl_matrix(path: Path) -> dict[str, list[str]] | None:
    """Load ACL matrix from a TOML file.

    Expected format:
        [permissions]
        agent_name = ["service_1", "service_2"]

    Args:
        path: Absolute or relative path to acl_matrix.toml.

    Returns:
        Dict mapping agent → list of allowed services, or None on error.
    """
    try:
        with open(path, "rb") as f:
            data = tomllib.load(f)
        permissions = data.get("permissions", {})
        if not isinstance(permissions, dict):
            logger.error("ACL matrix: [permissions] is not a table.")
            return None
        # Validate all values are lists of strings
        result: dict[str, list[str]] = {}
        for agent, services in permissions.items():
            if not isinstance(services, list):
                logger.error("ACL matrix: %s value is not a list.", agent)
                return None
            if not all(isinstance(s, str) for s in services):
                logger.error("ACL matrix: %s contains non-string entries.", agent)
                return None
            result[agent] = services
        return result
    except FileNotFoundError:
        logger.error("ACL matrix not found: %s", path)
        return None
    except tomllib.TOMLDecodeError as e:
        logger.error("ACL matrix TOML parse error: %s", e)
        return None


def load_resource_deny_list(path: Path) -> list[ResourceDenyRule] | None:
    """Load resource deny rules from a TOML file.

    Expected format:
        [[deny_rules]]
        verb = ""           # empty or omitted = all verbs
        resource_pattern = "system.*"
        reason = "Explanation"

    Args:
        path: Absolute or relative path to deny_list.toml.

    Returns:
        List of ResourceDenyRule, or None on error.
    """
    try:
        with open(path, "rb") as f:
            data = tomllib.load(f)
        raw_rules = data.get("deny_rules", [])
        if not isinstance(raw_rules, list):
            logger.error("Deny list: deny_rules is not an array of tables.")
            return None

        rules: list[ResourceDenyRule] = []
        for i, entry in enumerate(raw_rules):
            if not isinstance(entry, dict):
                logger.error("Deny list: entry %d is not a table.", i)
                return None
            pattern = entry.get("resource_pattern", "")
            reason = entry.get("reason", "")
            verb_raw = entry.get("verb", "")
            if not pattern:
                logger.error("Deny list: entry %d missing resource_pattern.", i)
                return None
            # Normalize empty string verb to None (matches all verbs)
            verb: str | None = verb_raw.upper() if verb_raw else None
            rules.append(ResourceDenyRule(verb=verb, resource_pattern=pattern, reason=reason))
        return rules
    except FileNotFoundError:
        logger.error("Deny list not found: %s", path)
        return None
    except tomllib.TOMLDecodeError as e:
        logger.error("Deny list TOML parse error: %s", e)
        return None


def load_rate_limit_config(config_data: dict) -> RateLimitConfig:
    """Extract rate limit config from the parsed default.toml [rate] section.

    Args:
        config_data: Full parsed default.toml dict.

    Returns:
        RateLimitConfig (always returns — uses defaults on missing keys).
    """
    rate_section = config_data.get("rate", {})
    return RateLimitConfig(
        max_requests_per_window=int(rate_section.get("max_requests_per_window", 100)),
        window_seconds=float(rate_section.get("window_seconds", 60.0)),
    )


def load_rule_engine_config(config_dir: Path) -> RuleEngineConfig | None:
    """Load the complete rule engine configuration from a config directory.

    Expects:
        config_dir/default.toml       — main config with [rules] and [rate]
        config_dir/acl_matrix.toml    — ACL permissions
        config_dir/deny_list.toml     — resource deny rules

    Args:
        config_dir: Path to the service config directory.

    Returns:
        RuleEngineConfig, or None if any critical config is missing/malformed.
        ACL and deny list must both load successfully; rate limit defaults
        are used on missing [rate] section.
    """
    default_path = config_dir / "default.toml"
    acl_path = config_dir / "acl_matrix.toml"
    deny_path = config_dir / "deny_list.toml"

    # Load main config for version + rate limit
    try:
        with open(default_path, "rb") as f:
            main_config = tomllib.load(f)
    except (FileNotFoundError, tomllib.TOMLDecodeError) as e:
        logger.error("Failed to load default.toml: %s", e)
        return None

    version = main_config.get("rules", {}).get("version", "1.0.0")
    rate_config = load_rate_limit_config(main_config)

    # Load ACL and deny list — both required (Fail-Closed)
    acl_matrix = load_acl_matrix(acl_path)
    if acl_matrix is None:
        logger.error("Fail-Closed: ACL matrix failed to load.")
        return None

    deny_rules = load_resource_deny_list(deny_path)
    if deny_rules is None:
        logger.error("Fail-Closed: Resource deny list failed to load.")
        return None

    return RuleEngineConfig(
        acl_matrix=acl_matrix,
        resource_deny_rules=deny_rules,
        rate_limit=rate_config,
        version=version,
    )
