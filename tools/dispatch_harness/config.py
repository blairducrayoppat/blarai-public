"""Resolve the harness's connection + fleet settings from the AO ``default.toml``.

The harness is a HEADLESS WinUI: it must construct the :class:`TransportGateway` with the SAME
``[fleet_dispatch]`` roots and ``[ipc]`` port the launcher reads off the started orchestrator, so
the coordinator's PLAN/EXECUTE transport calls reach the running AO and the monitor reads the
right ``state\\`` dirs. Rather than re-implement the launcher's resolution, we parse the same
``default.toml`` with the same stdlib ``tomllib`` the AO uses, and fall back to the documented
defaults for this box.

NOTE: this reads the config only to locate the AO + the fleet artifacts. It NEVER flips a flag or
writes config. ``fleet_dispatch_enabled`` here is informational (the AO is the source of truth at
runtime); the harness still sends ``/dispatch`` and lets the running AO's own gate decide.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path

# The committed AO config, relative to the repo root (this file lives at tools/dispatch_harness/).
_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_CONFIG = (
    _REPO_ROOT / "services" / "assistant_orchestrator" / "config" / "default.toml"
)
_DEFAULT_VSOCK_PORT = 5001
_DEFAULT_RUN_BUDGET_S = 5400.0


@dataclass(frozen=True)
class HarnessConfig:
    """Resolved settings for constructing the gateway + monitoring runs."""

    port: int
    fleet_dispatch_enabled: bool
    agentic_setup_dir: str
    projects_dir: str
    swap_run_budget_s: float
    config_path: Path

    @property
    def host(self) -> str:
        return "127.0.0.1"


def load_harness_config(config_path: str | Path | None = None) -> HarnessConfig:
    """Read the AO ``default.toml`` and resolve the harness's connection + fleet settings.

    A missing/unreadable config falls back to the documented defaults for this box (port 5001,
    empty roots → the fleet's compiled-in fallback). A malformed TOML raises ``ValueError`` —
    a corrupt config is an operator error worth surfacing, not silently defaulting past.
    """
    path = Path(config_path) if config_path else _DEFAULT_CONFIG
    if not path.is_file():
        return HarnessConfig(
            port=_DEFAULT_VSOCK_PORT,
            fleet_dispatch_enabled=False,
            agentic_setup_dir="",
            projects_dir="",
            swap_run_budget_s=_DEFAULT_RUN_BUDGET_S,
            config_path=path,
        )
    try:
        with path.open("rb") as fh:
            data = tomllib.load(fh)
    except tomllib.TOMLDecodeError as exc:
        raise ValueError(f"{path} is not valid TOML: {exc}") from exc
    except OSError as exc:
        raise ValueError(f"could not read {path}: {exc}") from exc

    ipc = data.get("ipc", {}) if isinstance(data.get("ipc"), dict) else {}
    fd = (
        data.get("fleet_dispatch", {})
        if isinstance(data.get("fleet_dispatch"), dict)
        else {}
    )
    return HarnessConfig(
        port=int(ipc.get("vsock_port", _DEFAULT_VSOCK_PORT)),
        fleet_dispatch_enabled=bool(fd.get("enabled", False)),
        agentic_setup_dir=str(fd.get("agentic_setup_dir", "") or ""),
        projects_dir=str(fd.get("projects_dir", "") or ""),
        swap_run_budget_s=float(fd.get("swap_run_budget_s", _DEFAULT_RUN_BUDGET_S)),
        config_path=path,
    )
