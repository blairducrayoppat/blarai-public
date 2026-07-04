"""Runtime configuration resolution helpers.

Provides deterministic host/guest config selection and compatibility checks.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from enum import Enum
from pathlib import Path


RUNTIME_MODE_ENV: str = "BLARAI_RUNTIME_MODE"

# ---------------------------------------------------------------------------
# network_facing — the load-bearing security posture flag (Sprint 13 DEC-8).
#
# BlarAI is air-gapped today, so this is False unconditionally.  The flag
# exists now so the dev-mode interlock (shared/security/dev_mode_guard.py) is
# wired BEFORE internet egress lands; flipping it to True without also
# disabling dev_mode is refused at launch.
#
# Resolution precedence (same pattern as DeploymentMode):
#   1. BLARAI_NETWORK_FACING env var ("1" / "true" / "yes" / "on" → True)
#   2. Hardcoded default: False (air-gapped Tier-1 posture)
#
# Changing this default requires Tier-2 cert provisioning + LA ratification.
# ---------------------------------------------------------------------------

NETWORK_FACING_ENV: str = "BLARAI_NETWORK_FACING"

# ---------------------------------------------------------------------------
# dev_mode override — the explicit, loud escape hatch (Sprint 15 EA-4b).
#
# After the HOST default flipped to production (dev_mode=False), the only
# way to boot in dev mode is an explicit environment variable opt-in.
# Resolution:
#   1. BLARAI_DEV_MODE env var ("1" / "true" / "yes" → True)
#   2. Returns None (not False) when unset — None means "use the mode default",
#      which is now production.  Returning False here would be a NO-OP (same as
#      the default), but None explicitly communicates "no override" to
#      resolve_dev_mode so the caller's own default logic stays in control.
#
# The loud INSECURE banner fires whenever this resolves True — the opt-in
# is never silent.  The interlock still refuses dev_mode + network_facing=True.
# ---------------------------------------------------------------------------

DEV_MODE_OVERRIDE_ENV: str = "BLARAI_DEV_MODE"


def resolve_dev_override() -> bool | None:
    """Return the explicit dev-mode override from the environment, or None.

    Reads ``BLARAI_DEV_MODE``.  Truthy values ("1", "true", "yes",
    case-insensitive) return ``True``; anything else — including absent,
    empty, or unrecognised values — returns ``None``.

    ``None`` means "no override; use the mode-derived default", which is
    now production (``False``) for HOST after Sprint 15 EA-4b.  Returning
    ``None`` rather than ``False`` preserves the three-way precedence in
    :func:`~shared.security.dev_mode_guard.resolve_dev_mode`:

      1. override not None → use the override
      2. runtime_mode == HOST → production (False)
      3. runtime_mode == GUEST → production (False)

    To opt into dev mode on a machine without provisioned keys, set::

        BLARAI_DEV_MODE=1

    in the process environment before launch.  The loud INSECURE banner
    fires on every such boot.

    Returns:
        ``True`` when ``BLARAI_DEV_MODE`` is set to a truthy value;
        ``None`` otherwise (no override — use the mode-derived default).
    """
    raw = os.environ.get(DEV_MODE_OVERRIDE_ENV, "").strip().lower()
    if raw in ("1", "true", "yes"):
        return True
    return None


def resolve_network_facing(
    explicit: bool | None = None,
) -> bool:
    """Return the network_facing bool for this launch.

    Deny-by-default: unrecognised env-var values are treated as False (the safe
    air-gapped posture) rather than True, because the caller can always set the
    env var explicitly to opt in.

    Args:
        explicit: If not ``None``, overrides env-var lookup (for tests).

    Returns:
        True only when explicitly set to a truthy value; False otherwise.
    """
    if explicit is not None:
        return explicit
    raw = os.environ.get(NETWORK_FACING_ENV, "").strip().lower()
    return raw in ("1", "true", "yes", "on")


def resolve_service_root(module_file: str, service_package: str) -> Path:
    """Resolve the service root directory, handling PyInstaller bundles.

    In a normal Python environment, uses ``Path(module_file).resolve().parents[1]``.
    In a PyInstaller frozen bundle, uses ``sys._MEIPASS / <service_package_path>``
    because compiled modules inside the PYZ archive may not have real file paths.

    Args:
        module_file: The ``__file__`` attribute of the calling module.
        service_package: Dotted package path (e.g. ``'services.policy_agent'``).

    Returns:
        Absolute ``Path`` to the service root directory.
    """
    meipass = getattr(sys, '_MEIPASS', None)
    if meipass is not None:
        # PyInstaller frozen bundle — data files are under _MEIPASS
        return Path(meipass) / service_package.replace('.', os.sep)

    # Normal Python — use __file__ relative resolution
    return Path(module_file).resolve().parents[1]


class DeploymentMode(str, Enum):
    """Supported deployment/runtime modes."""

    HOST = "host"
    GUEST = "guest"


@dataclass(frozen=True)
class ConfigResolutionError(ValueError):
    """Deterministic config resolution/compatibility failure."""

    code: str
    message: str


def build_failure_fingerprint(
    *,
    stage: str,
    code: str,
    message: str,
) -> dict[str, str]:
    return {
        "stage": stage,
        "code": code,
        "message": message,
        "disposition": "FAIL",
        "fail_closed": "true",
    }


def parse_deployment_mode(raw_mode: str) -> DeploymentMode:
    normalized = raw_mode.strip().lower()
    if normalized == DeploymentMode.HOST.value:
        return DeploymentMode.HOST
    if normalized == DeploymentMode.GUEST.value:
        return DeploymentMode.GUEST
    raise ConfigResolutionError(
        code="CFG_MODE_INVALID",
        message=(
            f"Invalid deployment mode '{raw_mode}'. Expected 'host' or 'guest'."
        ),
    )


def resolve_deployment_mode(explicit_mode: str | DeploymentMode | None = None) -> DeploymentMode:
    """Resolve mode using deterministic precedence.

    Precedence:
      1) explicit_mode argument
      2) BLARAI_RUNTIME_MODE environment variable
      3) default: host
    """
    if isinstance(explicit_mode, DeploymentMode):
        return explicit_mode
    if isinstance(explicit_mode, str):
        return parse_deployment_mode(explicit_mode)

    env_mode = os.environ.get(RUNTIME_MODE_ENV, "").strip()
    if env_mode:
        return parse_deployment_mode(env_mode)

    return DeploymentMode.HOST


def _expected_config_filename(mode: DeploymentMode) -> str:
    return "default.toml" if mode == DeploymentMode.HOST else "guest_runtime.toml"


def resolve_service_config_path(
    service_root: Path,
    *,
    deployment_mode: DeploymentMode,
    explicit_config_path: str | Path | None = None,
) -> Path:
    """Resolve the authoritative config file path for a service."""
    config_dir = service_root / "config"

    if explicit_config_path is None:
        resolved = config_dir / _expected_config_filename(deployment_mode)
    else:
        resolved = Path(explicit_config_path)
        if not resolved.is_absolute():
            resolved = (service_root / resolved).resolve()

        expected_name = _expected_config_filename(deployment_mode)
        if resolved.name != expected_name:
            raise ConfigResolutionError(
                code="CFG_MODE_CONFIG_MISMATCH",
                message=(
                    f"Deployment mode '{deployment_mode.value}' requires "
                    f"config '{expected_name}', got '{resolved.name}'."
                ),
            )

    if resolved.is_symlink():
        raise ConfigResolutionError(
            code="CFG_SYMLINK_REJECTED",
            message=f"Config path is a symlink (rejected for security): {resolved}",
        )

    if not resolved.exists():
        raise ConfigResolutionError(
            code="CFG_PATH_MISSING",
            message=f"Config file not found: {resolved}",
        )

    return resolved
