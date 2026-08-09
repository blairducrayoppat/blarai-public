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

import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path

# #811 / AUDIT-12: the SSOT fleet-root resolver + env-var names, so the harness honors
# the SAME env override -> TOML -> compiled-in fallback order the AO entrypoint uses
# (this loader is the second reader of [fleet_dispatch]; it must not bypass the resolver).
from shared.fleet.dispatch import (
    FLEET_AGENTIC_SETUP_DIR_ENV,
    FLEET_PROJECTS_DIR_ENV,
    resolve_fleet_root,
)
from tools.dispatch_harness.runtime_root import resolve_runtime_root

# The committed AO config, relative to the repo root (this file lives at tools/dispatch_harness/).
_REPO_ROOT = Path(__file__).resolve().parents[2]
_CONFIG_REL = Path("services") / "assistant_orchestrator" / "config" / "default.toml"
_DEFAULT_VSOCK_PORT = 5001
_DEFAULT_RUN_BUDGET_S = 10800.0  # #757: matches [fleet_dispatch].swap_run_budget_s (3 h)


@dataclass(frozen=True)
class HarnessConfig:
    """Resolved settings for constructing the gateway + monitoring runs.

    The four ceremony-gated gateway flags resolve VALIDATED-NOT-COERCED
    (#1042 rule: only an explicit TOML boolean ``true`` counts) because they
    feed :meth:`DispatchHarness.for_live`'s gateway construction — a driver
    reading them mirrors the SHIPPED posture instead of hardcoding one.
    ``fleet_dispatch_enabled`` stays informational (coerced) as documented
    above; the running AO adjudicates regardless."""

    port: int
    fleet_dispatch_enabled: bool
    agentic_setup_dir: str
    projects_dir: str
    swap_run_budget_s: float
    config_path: Path
    advanced_intake_enabled: bool = False
    advanced_intake_interview_enabled: bool = False
    advanced_intake_assets_pipeline_enabled: bool = False
    advanced_intake_interview_playback_enabled: bool = False
    advanced_intake_interview_voice_enabled: bool = False
    project_memory_enabled: bool = False
    #: #1281 — may the placeholder-prose scan's findings move a GREEN's band and take the
    #: operator card's one caveat slot? Resolved VALIDATED-NOT-COERCED for the same reason the
    #: four gateway flags above are: this one decides what the operator READS about a delivery,
    #: and a quoted "false" must not read as a grant. The scan's MEASUREMENT is not gated by it.
    green_quality_prose_band_enabled: bool = False

    @property
    def host(self) -> str:
        return "127.0.0.1"


def default_config_path() -> Path:
    """The AO config to read when the caller names none.

    ``default.toml`` describes the INSTALLATION — the ipc port, the fleet roots, the flags
    the shipped orchestrator is actually running under — so it belongs with the runtime
    root, beside ``models/`` and ``certs/``, not with whatever tree the measuring code was
    loaded from. While the two roots are the same directory this resolves to exactly the
    historical path. When they are split (see
    :data:`~tools.dispatch_harness.runtime_root.RUNTIME_ROOT_ENV`) it follows the
    installation and says so on stderr: an unnamed config read out of the measuring tree
    would configure a whole run against a file nobody chose, and would do it quietly.

    Raises:
        RuntimeRootError: the runtime-root override is set but unusable. Fail-closed —
            never a quiet fall back to the harness tree.
    """
    runtime = resolve_runtime_root(_REPO_ROOT)
    if runtime != _REPO_ROOT:
        print(
            f"harness config: no explicit config was named, so the INSTALLATION's copy is "
            f"being read ({runtime / _CONFIG_REL}); this code was loaded from {_REPO_ROOT}. "
            f"Name one explicitly (--config) to read a different tree's.",
            file=sys.stderr,
        )
    return runtime / _CONFIG_REL


def load_harness_config(config_path: str | Path | None = None) -> HarnessConfig:
    """Read the AO ``default.toml`` and resolve the harness's connection + fleet settings.

    *config_path* unset means :func:`default_config_path` — the installation's copy, which
    is the same file as this tree's whenever the two roots are not split.

    A missing/unreadable config falls back to the documented defaults for this box (port 5001,
    empty roots → the fleet's compiled-in fallback). A malformed TOML raises ``ValueError`` —
    a corrupt config is an operator error worth surfacing, not silently defaulting past.
    """
    path = Path(config_path) if config_path else default_config_path()
    if not path.is_file():
        # Missing config: the env override still resolves (else "" -> compiled-in fallback).
        return HarnessConfig(
            port=_DEFAULT_VSOCK_PORT,
            fleet_dispatch_enabled=False,
            agentic_setup_dir=resolve_fleet_root(FLEET_AGENTIC_SETUP_DIR_ENV, ""),
            projects_dir=resolve_fleet_root(FLEET_PROJECTS_DIR_ENV, ""),
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
        agentic_setup_dir=resolve_fleet_root(
            FLEET_AGENTIC_SETUP_DIR_ENV, fd.get("agentic_setup_dir", "")
        ),
        projects_dir=resolve_fleet_root(
            FLEET_PROJECTS_DIR_ENV, fd.get("projects_dir", "")
        ),
        swap_run_budget_s=float(fd.get("swap_run_budget_s", _DEFAULT_RUN_BUDGET_S)),
        config_path=path,
        advanced_intake_enabled=fd.get("advanced_intake") is True,
        advanced_intake_interview_enabled=fd.get("advanced_intake_interview") is True,
        advanced_intake_assets_pipeline_enabled=(
            fd.get("advanced_intake_assets_pipeline") is True
        ),
        advanced_intake_interview_playback_enabled=(
            fd.get("advanced_intake_interview_playback") is True
        ),
        advanced_intake_interview_voice_enabled=(
            fd.get("advanced_intake_interview_voice") is True
        ),
        project_memory_enabled=fd.get("project_memory") is True,
        green_quality_prose_band_enabled=fd.get("green_quality_prose_band") is True,
    )
