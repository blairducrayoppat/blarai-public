"""Fleet-dispatch root resolution + shipped-config hygiene (#811 / AUDIT-12).

AUDIT-12 (12-Factor III) flagged that the SHIPPED ``default.toml`` baked one dev's
home directory into ``[fleet_dispatch].agentic_setup_dir`` / ``projects_dir``. The
fix externalises the two roots: the shipped config carries an EMPTY value and each
root resolves through :func:`shared.fleet.dispatch.resolve_fleet_root` —

    env override  ->  the (empty) TOML value  ->  ""  ->  the compiled-in this-host
    fallback in build_default_config (_AGENTIC_SETUP / _PROJECTS)

On the build host (no env var, empty TOML) the resolved runtime paths are
byte-identical to the old baked config, so this is a hygiene refactor, not a
behaviour change.

These tests lock three things:
  1. the resolver precedence (env wins; empty falls through);
  2. the two live readers of ``[fleet_dispatch]`` (the AO entrypoint config loader
     AND the dispatch-harness config loader) BOTH route through the resolver, so an
     env override is honoured uniformly and neither reader re-bakes a path;
  3. a regression lock that FAILS if the shipped ``default.toml`` ever regrows an
     absolute user-home path (the durable guard against re-baking, #811).
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

import services.assistant_orchestrator.src.entrypoint as entrypoint
from shared.fleet.dispatch import (
    FLEET_AGENTIC_SETUP_DIR_ENV,
    FLEET_PROJECTS_DIR_ENV,
    _AGENTIC_SETUP,
    _PROJECTS,
    build_default_config,
    resolve_fleet_root,
)
from tools.dispatch_harness.config import load_harness_config

# The env-var names under test (assert we used the BLARAI_-prefix convention).
_ENV_AGENTIC = "BLARAI_FLEET_AGENTIC_SETUP_DIR"
_ENV_PROJECTS = "BLARAI_FLEET_PROJECTS_DIR"

# A single, cwd-independent handle on the SHIPPED config (mirrors the idiom in
# test_execute_handler.py: resolve from the entrypoint module file, not from cwd).
_SHIPPED_DEFAULT_TOML = (
    Path(entrypoint.__file__).resolve().parents[1] / "config" / "default.toml"
)

# An absolute Windows user-home path, e.g. C:\Users\alice or D:/Users/bob.
_HOME_PATH_RE = re.compile(r"[A-Za-z]:[\\/]+Users[\\/]+", re.IGNORECASE)


def _no_fleet_env(monkeypatch) -> None:
    monkeypatch.delenv(_ENV_AGENTIC, raising=False)
    monkeypatch.delenv(_ENV_PROJECTS, raising=False)


# ---------------------------------------------------------------------------
# The env-var names honour the repo convention.
# ---------------------------------------------------------------------------


def test_env_var_names_follow_blarai_convention() -> None:
    assert FLEET_AGENTIC_SETUP_DIR_ENV == _ENV_AGENTIC
    assert FLEET_PROJECTS_DIR_ENV == _ENV_PROJECTS
    assert FLEET_AGENTIC_SETUP_DIR_ENV.startswith("BLARAI_")
    assert FLEET_PROJECTS_DIR_ENV.startswith("BLARAI_")


# ---------------------------------------------------------------------------
# resolve_fleet_root() precedence.
# ---------------------------------------------------------------------------


def test_env_override_wins_over_toml_value(monkeypatch) -> None:
    monkeypatch.setenv(_ENV_AGENTIC, "X:/custom/agentic")
    assert resolve_fleet_root(_ENV_AGENTIC, "D:/from-toml") == "X:/custom/agentic"


def test_env_override_is_stripped(monkeypatch) -> None:
    monkeypatch.setenv(_ENV_AGENTIC, "  X:/custom/agentic \t")
    assert resolve_fleet_root(_ENV_AGENTIC, "D:/from-toml") == "X:/custom/agentic"


def test_toml_value_used_when_env_absent(monkeypatch) -> None:
    _no_fleet_env(monkeypatch)
    assert resolve_fleet_root(_ENV_AGENTIC, "D:/from-toml") == "D:/from-toml"


def test_blank_env_falls_through_to_toml(monkeypatch) -> None:
    # A whitespace-only env value is treated as "unset" — it must not shadow the TOML.
    monkeypatch.setenv(_ENV_AGENTIC, "   ")
    assert resolve_fleet_root(_ENV_AGENTIC, "D:/from-toml") == "D:/from-toml"


def test_all_empty_resolves_to_blank_string(monkeypatch) -> None:
    _no_fleet_env(monkeypatch)
    assert resolve_fleet_root(_ENV_AGENTIC, "") == ""
    assert resolve_fleet_root(_ENV_AGENTIC, None) == ""  # None -> "" (never "None")


# ---------------------------------------------------------------------------
# Composition with build_default_config — the "same paths on this box" lock.
# ---------------------------------------------------------------------------


def test_empty_resolution_yields_compiled_this_host_default(monkeypatch) -> None:
    """No env + empty TOML -> "" -> build_default_config's compiled-in fallback.

    This is the byte-identical-runtime guarantee: on the build host the two roots
    resolve to exactly the paths the old baked config pointed at."""
    _no_fleet_env(monkeypatch)
    setup = resolve_fleet_root(_ENV_AGENTIC, "")
    projects = resolve_fleet_root(_ENV_PROJECTS, "")
    assert (setup, projects) == ("", "")

    cfg = build_default_config(setup or None, projects or None)
    assert cfg.projects_dir == _PROJECTS
    assert cfg.scripts_dir == _AGENTIC_SETUP / "scripts"
    assert cfg.runs_dir == _AGENTIC_SETUP / "state" / "fleet-runs"


def test_env_override_flows_into_build_default_config(monkeypatch) -> None:
    monkeypatch.setenv(_ENV_AGENTIC, "X:/fleet")
    monkeypatch.setenv(_ENV_PROJECTS, "Y:/proj")
    setup = resolve_fleet_root(_ENV_AGENTIC, "")
    projects = resolve_fleet_root(_ENV_PROJECTS, "")

    cfg = build_default_config(setup or None, projects or None)
    assert cfg.projects_dir == Path("Y:/proj")
    assert cfg.scripts_dir == Path("X:/fleet") / "scripts"


# ---------------------------------------------------------------------------
# Reader #1 — the AO entrypoint config loader routes through the resolver.
# ---------------------------------------------------------------------------


# dev_mode_override=True only no-ops the orthogonal security-material file check
# (_validate_security_material, which needs the signed manifest absent in a hermetic
# worktree). Fleet-root resolution is downstream of it and independent of dev_mode,
# so this still exercises the REAL _load_entrypoint_config resolution path.
def _load_shipped_config():
    svc = entrypoint.AssistantOrchestratorService.from_runtime_mode(
        None, dev_mode_override=True
    )
    return svc._load_entrypoint_config()


def test_ao_entrypoint_resolves_shipped_roots_to_blank_without_env(monkeypatch) -> None:
    """End-to-end through the REAL shipped default.toml: with no env var the two
    resolved roots are "" (the shipped config no longer bakes a path). Locks that
    the loader at _load_entrypoint_config routes through resolve_fleet_root."""
    _no_fleet_env(monkeypatch)
    resolved = _load_shipped_config()
    assert resolved.fleet_dispatch_agentic_setup_dir == ""
    assert resolved.fleet_dispatch_projects_dir == ""


def test_ao_entrypoint_honours_env_override(monkeypatch) -> None:
    monkeypatch.setenv(_ENV_AGENTIC, "X:/fleet-override")
    monkeypatch.setenv(_ENV_PROJECTS, "Y:/proj-override")
    resolved = _load_shipped_config()
    assert resolved.fleet_dispatch_agentic_setup_dir == "X:/fleet-override"
    assert resolved.fleet_dispatch_projects_dir == "Y:/proj-override"


# ---------------------------------------------------------------------------
# Reader #2 — the dispatch-harness config loader routes through the resolver.
# (This is the residual-risk reader: it parses the same default.toml directly.)
# ---------------------------------------------------------------------------


def test_harness_config_resolves_shipped_roots_to_blank_without_env(monkeypatch) -> None:
    _no_fleet_env(monkeypatch)
    hc = load_harness_config()  # reads the real shipped default.toml
    assert hc.agentic_setup_dir == ""
    assert hc.projects_dir == ""


def test_harness_config_honours_env_override(monkeypatch) -> None:
    monkeypatch.setenv(_ENV_AGENTIC, "X:/fleet-override")
    monkeypatch.setenv(_ENV_PROJECTS, "Y:/proj-override")
    hc = load_harness_config()
    assert hc.agentic_setup_dir == "X:/fleet-override"
    assert hc.projects_dir == "Y:/proj-override"


def test_harness_missing_config_still_honours_env(monkeypatch, tmp_path) -> None:
    # No config file at all: the env override must still resolve.
    monkeypatch.setenv(_ENV_AGENTIC, "X:/fleet-override")
    monkeypatch.setenv(_ENV_PROJECTS, "Y:/proj-override")
    hc = load_harness_config(tmp_path / "does-not-exist.toml")
    assert hc.agentic_setup_dir == "X:/fleet-override"
    assert hc.projects_dir == "Y:/proj-override"


# ---------------------------------------------------------------------------
# Regression lock — the shipped default.toml carries NO absolute home path.
# ---------------------------------------------------------------------------


def test_shipped_default_toml_fleet_roots_are_empty() -> None:
    data = tomllib.loads(_SHIPPED_DEFAULT_TOML.read_text(encoding="utf-8"))
    fd = data["fleet_dispatch"]
    assert fd["agentic_setup_dir"] == ""
    assert fd["projects_dir"] == ""


def _walk_strings(value):
    """Yield every string leaf in a parsed-TOML value (dicts, lists, scalars)."""
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from _walk_strings(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from _walk_strings(item)


def test_shipped_default_toml_has_no_baked_home_path_in_any_value() -> None:
    """No CONFIG VALUE in the shipped default.toml may hold an absolute user-home
    path (C:\\Users\\..., D:/Users/..., etc.). The durable guard against anyone
    re-baking a machine-specific path into the shipped config (#811 / AUDIT-12)."""
    data = tomllib.loads(_SHIPPED_DEFAULT_TOML.read_text(encoding="utf-8"))
    offenders = [s for s in _walk_strings(data) if _HOME_PATH_RE.search(s)]
    assert offenders == [], (
        "shipped default.toml re-baked an absolute user-home path into a config "
        f"value: {offenders!r}. Externalise it via resolve_fleet_root / an env "
        "override instead (12-Factor III, #811)."
    )


def test_shipped_default_toml_text_has_no_dev_home_literal() -> None:
    """Literal-grep guard (the AUDIT-12 ask): the shipped default.toml text must not
    contain the original baked dev-home literal anywhere — value OR comment."""
    text = _SHIPPED_DEFAULT_TOML.read_text(encoding="utf-8").lower()
    assert "mrbla" not in text
    assert "c:/users" not in text
    assert "c:\\users" not in text
