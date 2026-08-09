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

import json
import os
import re
import tomllib
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import services.assistant_orchestrator.src.entrypoint as entrypoint
from shared.fleet.dispatch import (
    FLEET_AGENTIC_SETUP_DIR_ENV,
    FLEET_PROJECTS_DIR_ENV,
    FLEET_SCRIPTS_DIR_ENV,
    _AGENTIC_SETUP,
    _PROJECTS,
    FleetScriptsDirUnavailable,
    build_default_config,
    resolve_fleet_root,
    scripts_dir_provenance,
    resolve_fleet_scripts_dir,
)
from tools.dispatch_harness.config import load_harness_config

# The env-var names under test (assert we used the BLARAI_-prefix convention).
_ENV_AGENTIC = "BLARAI_FLEET_AGENTIC_SETUP_DIR"
_ENV_PROJECTS = "BLARAI_FLEET_PROJECTS_DIR"
# #1181a: the CODE pin (spelled out here rather than imported, so a rename of the
# constant cannot silently move the contract the battery bootstrap exports against).
_ENV_SCRIPTS = "BLARAI_FLEET_SCRIPTS_DIR"

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


# ---------------------------------------------------------------------------
# #1181a — the CODE/STATE split on scripts_dir.
#
# #1181 pinned the battery's DRIVER to a commit that exists on main. It did not
# pin the per-task dispatch SCRIPTS, which is where most of the coder's behaviour
# lives. Measured 2026-07-30 13:36: a night ran a pinned driver whose tree carried
# newly-merged coder_test_qa wiring, and the wiring never fired — the dispatch
# resolved scripts_dir to the PRIMARY checkout, parked by another session on
# fix/1171-declared-surface, which did not contain it. `grep -c CoderTestHard`
# returned 0 on the primary's copy and 1 on the pinned copy. No error was raised
# anywhere; the run simply validated nothing.
#
# The locks below are paired per security_by_design principle 12 — each proves the
# control BLOCKS when engaged and a toggle proves the probe FAILS when it is off.
# ---------------------------------------------------------------------------


def _no_scripts_env(monkeypatch) -> None:
    _no_fleet_env(monkeypatch)
    monkeypatch.delenv(_ENV_SCRIPTS, raising=False)


def test_scripts_pin_env_var_name_is_the_one_the_bootstrap_exports() -> None:
    """The battery's PowerShell exports a literal string; this module names a constant.
    They are only the same contract while this holds — a rename here without one there
    would silently un-pin every night (agentic-setup/scripts/run-battery-night.ps1)."""
    assert FLEET_SCRIPTS_DIR_ENV == _ENV_SCRIPTS


def test_unpinned_scripts_dir_is_byte_identical_to_today(monkeypatch) -> None:
    """CONTROL / toggle-test. With the pin unset, every path resolves exactly as it
    did before #1181a — a hand-run or dev invocation must be unaffected."""
    _no_scripts_env(monkeypatch)
    cfg = build_default_config("X:/fleet", "Y:/proj")
    assert cfg.scripts_dir == Path("X:/fleet") / "scripts"
    assert cfg.queue_path == Path("X:/fleet") / "state" / "fleet-queue.json"
    assert cfg.runs_dir == Path("X:/fleet") / "state" / "fleet-runs"

    # …and the resolver itself is a pure passthrough when unset.
    assert resolve_fleet_scripts_dir(Path("X:/fleet")) == Path("X:/fleet") / "scripts"


def test_pinned_scripts_dir_moves_code_but_never_state(tmp_path, monkeypatch) -> None:
    """The lock. The pin moves scripts_dir ONLY: the queue, the run directory and
    the projects root stay rooted in the primary checkout, because they are
    accumulated history and a pinned worktree is re-detached every night."""
    _no_scripts_env(monkeypatch)
    primary = tmp_path / "agentic-setup"
    pinned = tmp_path / "agentic-battery-measured" / "scripts"
    pinned.mkdir(parents=True)
    monkeypatch.setenv(_ENV_SCRIPTS, str(pinned))

    cfg = build_default_config(str(primary), "Y:/proj")
    assert cfg.scripts_dir == pinned                                   # CODE follows the pin
    assert cfg.queue_path == primary / "state" / "fleet-queue.json"    # STATE does not
    assert cfg.runs_dir == primary / "state" / "fleet-runs"            # STATE does not
    assert cfg.projects_dir == Path("Y:/proj")                         # untouched


def test_pinned_dir_that_is_missing_raises_and_never_falls_back(tmp_path, monkeypatch) -> None:
    """FAIL-CLOSED (principles 1 + 11). A named-but-absent pin is fatal. Falling back
    to <setup>/scripts is the silent defeat this whole change exists to remove, so the
    assertion is not merely 'it raised' — it is that the primary's path is NOT returned."""
    _no_scripts_env(monkeypatch)
    primary = tmp_path / "agentic-setup"
    (primary / "scripts").mkdir(parents=True)  # the fallback EXISTS and is still refused
    monkeypatch.setenv(_ENV_SCRIPTS, str(tmp_path / "not-created"))

    with pytest.raises(FleetScriptsDirUnavailable) as exc:
        build_default_config(str(primary), "Y:/proj")
    assert "not-created" in str(exc.value)
    assert str(primary / "scripts") not in str(exc.value)


def test_pin_pointing_at_a_file_is_refused(tmp_path, monkeypatch) -> None:
    """A path that exists but is not a directory is equally unusable — is_dir(), not
    exists(), so a stray file cannot satisfy the pin."""
    _no_scripts_env(monkeypatch)
    decoy = tmp_path / "scripts"
    decoy.write_text("not a directory", encoding="utf-8")
    monkeypatch.setenv(_ENV_SCRIPTS, str(decoy))
    with pytest.raises(FleetScriptsDirUnavailable):
        build_default_config(str(tmp_path / "agentic-setup"), "Y:/proj")


def test_blank_pin_is_treated_as_unset_not_as_cwd(tmp_path, monkeypatch) -> None:
    """A whitespace-only value must mean 'unpinned', never Path('') (which is cwd) —
    an empty env var is how a shell exports 'nothing', and resolving it to the current
    directory would dispatch whatever happened to be there."""
    _no_scripts_env(monkeypatch)
    monkeypatch.setenv(_ENV_SCRIPTS, "   ")
    assert resolve_fleet_scripts_dir(tmp_path) == tmp_path / "scripts"


def test_reproduces_the_2026_07_30_stale_dispatch(tmp_path, monkeypatch) -> None:
    """The decisive test: the one that would have caught the live failure.

    Two real script copies on disk, differing exactly as the two trees differed that
    afternoon — the primary's new-agent-task.ps1 lacking the merged CoderTestHard
    wiring, the measured tree's carrying it. Resolve the config the way the battery
    does and READ THE FILE THAT WOULD ACTUALLY RUN.

    Without the pin this asserts the observed defect (the stale copy is selected);
    with it, the merged copy runs. Asserting both directions is what makes this a
    reproduction rather than a restatement."""
    _no_scripts_env(monkeypatch)
    primary = tmp_path / "agentic-setup"
    measured = tmp_path / "agentic-battery-measured"
    (primary / "scripts").mkdir(parents=True)
    (measured / "scripts").mkdir(parents=True)
    # The primary is parked on a branch predating the merge.
    (primary / "scripts" / "new-agent-task.ps1").write_text(
        "# fix/1171-declared-surface\n", encoding="utf-8"
    )
    # The measured tree is at main, which carries the wiring.
    (measured / "scripts" / "new-agent-task.ps1").write_text(
        "# main\nif ($CoderTestHard) { Write-Host 'CODER TEST QA' }\n", encoding="utf-8"
    )

    def dispatched_text() -> str:
        cfg = build_default_config(str(primary), str(tmp_path / "projects"))
        return (cfg.scripts_dir / "new-agent-task.ps1").read_text(encoding="utf-8")

    # UNPINNED — the observed defect, reproduced: the stale copy is what dispatches.
    assert "CoderTestHard" not in dispatched_text()

    # PINNED — the fix: the merged copy is what dispatches.
    monkeypatch.setenv(_ENV_SCRIPTS, str(measured / "scripts"))
    assert "CoderTestHard" in dispatched_text()


def test_spec_round_trip_preserves_the_pin(tmp_path, monkeypatch) -> None:
    """The detached swap driver rebuilds its config from spec.json rather than from the
    environment, so the pin has to survive serialisation or it is lost at exactly the moment
    the per-task scripts are invoked.

    Drives the REAL serializer (:func:`prepare_and_launch_swap`, which writes the spec) and
    the REAL deserializer (:func:`run_swap`, which rebuilds the config from it). An earlier
    version of this test hand-built the dict and hand-built the config, which reduced it to
    asserting ``Path(str(p)) == p``: deleting ``scripts_dir`` from the real serializer and
    re-deriving it in the real deserializer — the exact defect one layer down — left it
    green. ``spawn`` is intercepted so nothing detaches; the spec on disk is the artefact."""
    import shared.fleet.swap_ops as so

    _no_scripts_env(monkeypatch)
    primary = tmp_path / "agentic-setup"
    pinned = tmp_path / "measured" / "scripts"
    pinned.mkdir(parents=True)
    (primary / "state" / "fleet-swap").mkdir(parents=True)
    monkeypatch.setenv(_ENV_SCRIPTS, str(pinned))
    cfg = build_default_config(str(primary), str(tmp_path / "projects"))
    assert cfg.scripts_dir == pinned  # premise: the pin reached the dispatching process

    captured: dict[str, Path] = {}
    so.prepare_and_launch_swap(
        cfg, run_id="r1", session_id="s1", tasks=[{"task": "t", "repo": "x"}],
        old_pid=0, relaunch_argv=[], relaunch_cwd="", gate_gb=0.0,
        spawn=lambda spec_path: captured.setdefault("spec", spec_path),
    )
    spec_path = captured["spec"]
    assert json.loads(spec_path.read_text(encoding="utf-8"))["scripts_dir"] == str(pinned)

    # The REAL deserializer, halted the instant it has built the config the driver would use.
    # The assertion is on that CONFIG OBJECT, not on a re-read of the file: what matters is
    # what run_swap constructed, which is what real_run_task invokes the scripts from.
    seen: dict[str, object] = {}

    class _Stop(Exception):
        pass

    def _capture(config):
        seen["config"] = config
        raise _Stop

    monkeypatch.setattr(so, "scripts_pin_violation", _capture)
    with pytest.raises(_Stop):
        so.run_swap(spec_path)

    built = seen["config"]
    assert built.scripts_dir == pinned
    assert built.queue_path == primary / "state" / "fleet-queue.json"


def test_model_profiles_pin_env_var_name_is_the_one_the_bootstrap_exports() -> None:
    """F8. The battery pins the tracked model-profiles manifest in the SAME block that pins
    the scripts, but that pin had no cross-repo name lock: renaming ENV_OVERRIDE would have
    silently un-pinned the manifest with the verifier's B4 still green, because B4 asserts the
    variable the PowerShell sets, not the one Python reads."""
    from shared.fleet.model_profiles import ENV_OVERRIDE

    assert ENV_OVERRIDE == "BLARAI_MODEL_PROFILES_PATH"


# ---------------------------------------------------------------------------
# #1181a F4 — the pin is exported, but the process that WRITES scripts_dir into
# the spec is the running Assistant Orchestrator (entrypoint.py is the only
# caller of execute_swap_dispatch). An AO the launcher did not boot never saw
# the variable. The declaration on disk is what holds it to the pin anyway.
# ---------------------------------------------------------------------------


def _pinned_world(tmp_path):
    primary = tmp_path / "agentic-setup"
    (primary / "state" / "fleet-swap").mkdir(parents=True)
    pinned = tmp_path / "measured" / "scripts"
    pinned.mkdir(parents=True)
    return primary, pinned


def _dead_pid() -> int:
    """A pid belonging to a process that HAS ACTUALLY EXITED — a real dead run, not an
    invented number. Even if the OS recycles it before the assertion runs, the declaration
    below carries a start time far in the past, so the identity check still reads DEAD."""
    import subprocess
    import sys

    proc = subprocess.Popen([sys.executable, "-c", "pass"])
    proc.wait(timeout=120)
    return proc.pid


def _declare(primary: Path, scripts_dir, *, alive: bool = True) -> Path:
    """Write the declaration the battery writes, keyed to a REAL process.

    Liveness is not simulated here: ``alive=True`` keys the declaration to THIS pytest process
    and its true psutil start time, so the reader is checking a process that genuinely is
    running; ``alive=False`` keys it to a process that genuinely has exited. A fabricated pid
    would let these tests pass over a state the system cannot actually be in.

    The SHAPE is asserted against the real PowerShell producer's output by the agentic-side
    suite (``verify-fleet-scripts-pinning.ps1``), which drives ``Publish-ScriptsPin`` itself —
    that seam is what stops this helper drifting into a fixture production cannot emit."""
    import psutil

    if alive:
        pid = os.getpid()
        started = datetime.fromtimestamp(psutil.Process(pid).create_time(), tz=timezone.utc)
    else:
        pid = _dead_pid()
        started = datetime(2000, 1, 1, tzinfo=timezone.utc)
    pins = primary / "state" / "fleet-swap" / "pins"
    pins.mkdir(parents=True, exist_ok=True)
    path = pins / f"20260730-230000-{pid}-fixture.json"
    path.write_text(
        json.dumps({
            "scripts_dir": str(scripts_dir),
            "launcher_pid": pid,
            "launcher_started_at": started.strftime("%Y-%m-%dT%H:%M:%S.%f0Z"),
            "declared_at": "2026-07-30T23:00:00Z",
        }),
        encoding="utf-8",
    )
    return path


def test_a_process_that_never_inherited_the_pin_still_uses_it(tmp_path, monkeypatch) -> None:
    """THE F4 DURABILITY LOCK. No environment variable anywhere — the state of an assistant
    the operator's app started, or that came back after a reboot, which is the NORMAL state of
    this machine. It must still resolve the pinned scripts, because an inheritance-only pin is
    silently inert exactly there and would need re-establishing after every reboot.

    An earlier version of this fix only VALIDATED the declaration, so this case stood down
    instead. Safe, but it meant the operator could never run on demand with his app up."""
    _no_scripts_env(monkeypatch)
    primary, pinned = _pinned_world(tmp_path)
    _declare(primary, pinned)
    cfg = build_default_config(str(primary), str(tmp_path / "projects"))
    assert cfg.scripts_dir == pinned                                   # CODE follows the pin
    assert cfg.queue_path == primary / "state" / "fleet-queue.json"    # STATE does not


def test_the_pin_survives_a_completely_clean_environment(tmp_path) -> None:
    """The reboot scenario, PROVEN rather than reasoned.

    A real child process with the environment SCRUBBED of every BLARAI_* variable — which is
    what a freshly booted box and an app-started assistant actually give you — resolves the
    declared pin. monkeypatch cannot demonstrate this: it edits the current process, which has
    already inherited whatever this session has. Only a clean subprocess can."""
    import subprocess
    import sys

    primary, pinned = _pinned_world(tmp_path)
    _declare(primary, pinned)
    repo_root = Path(entrypoint.__file__).resolve().parents[3]
    src = (
        "import sys; sys.path.insert(0, %r)\n"
        "from shared.fleet.dispatch import build_default_config, scripts_dir_provenance\n"
        "from pathlib import Path\n"
        "cfg = build_default_config(%r, %r)\n"
        "print(cfg.scripts_dir)\n"
        "print(scripts_dir_provenance(Path(%r)))\n"
    ) % (str(repo_root), str(primary), str(tmp_path / "projects"), str(primary))

    clean = {
        k: v for k, v in os.environ.items()
        if not k.startswith("BLARAI_")
    }
    clean["SYSTEMROOT"] = os.environ.get("SYSTEMROOT", "")  # Windows needs this to start python
    assert not any(k.startswith("BLARAI_") for k in clean)

    out = subprocess.run(
        [sys.executable, "-c", src], capture_output=True, text=True, env=clean, timeout=120,
    )
    assert out.returncode == 0, out.stderr
    resolved, provenance = out.stdout.strip().splitlines()[-2:]
    assert Path(resolved) == pinned, f"a clean process resolved {resolved}, not the pin"
    assert provenance == "declaration"


def test_provenance_is_recorded_in_the_runs_durable_record(tmp_path, monkeypatch) -> None:
    """The spec is what outlives the run. It must say WHERE scripts_dir came from, so a later
    session can tell which scripts a past run used without an environment to inspect."""
    import shared.fleet.swap_ops as so

    _no_scripts_env(monkeypatch)
    primary, pinned = _pinned_world(tmp_path)
    _declare(primary, pinned)
    cfg = build_default_config(str(primary), str(tmp_path / "projects"))
    captured = {}
    so.prepare_and_launch_swap(
        cfg, run_id="r1", session_id="s1", tasks=[{"task": "t", "repo": "x"}],
        old_pid=0, relaunch_argv=[], relaunch_cwd="", gate_gb=0.0,
        spawn=lambda p: captured.setdefault("spec", p),
    )
    spec = json.loads(captured["spec"].read_text(encoding="utf-8"))
    assert spec["scripts_dir"] == str(pinned)
    assert spec["scripts_dir_source"] == "declaration"


def test_a_declaration_naming_a_missing_tree_is_fatal_not_a_fallback(tmp_path, monkeypatch) -> None:
    """FAIL-CLOSED on the durable channel too. A declaration pointing at a tree that is gone
    must stand the run down, never quietly resolve the primary — the same rule the env var
    already obeyed, applied to the source that now actually carries the pin."""
    _no_scripts_env(monkeypatch)
    primary, _pinned = _pinned_world(tmp_path)
    (primary / "scripts").mkdir()  # the fallback EXISTS and is still refused
    _declare(primary, tmp_path / "deleted-measured-tree" / "scripts")
    with pytest.raises(FleetScriptsDirUnavailable) as exc:
        build_default_config(str(primary), str(tmp_path / "projects"))
    assert "deleted-measured-tree" in str(exc.value)
    assert str(primary / "scripts") not in str(exc.value)


def test_an_explicit_env_override_still_outranks_the_declaration(tmp_path, monkeypatch) -> None:
    """Precedence. The declaration is the durable channel; an explicit variable is a
    deliberate per-process override and must still win, or a hand-run could not escape it."""
    _no_scripts_env(monkeypatch)
    primary, pinned = _pinned_world(tmp_path)
    other = tmp_path / "other" / "scripts"
    other.mkdir(parents=True)
    _declare(primary, pinned)
    monkeypatch.setenv(_ENV_SCRIPTS, str(other))
    cfg = build_default_config(str(primary), str(tmp_path / "projects"))
    assert cfg.scripts_dir == other


def test_a_dispatch_that_honours_the_pin_proceeds(tmp_path, monkeypatch) -> None:
    """CONTROL for the lock above. Same declaration, but this process DID inherit the pin —
    the dispatch must go through, or the check would simply block every pinned night."""
    import shared.fleet.swap_ops as so

    _no_scripts_env(monkeypatch)
    primary, pinned = _pinned_world(tmp_path)
    _declare(primary, pinned)
    monkeypatch.setenv(_ENV_SCRIPTS, str(pinned))
    cfg = build_default_config(str(primary), str(tmp_path / "projects"))
    assert cfg.scripts_dir == pinned

    launched = []
    result = so.execute_swap_dispatch(
        run_id="r1", session_id="s1", tasks=[{"task": "t", "repo": str(tmp_path / "p")}],
        config=cfg, gate_gb=0.0, old_pid=0, relaunch_argv=[], relaunch_cwd="",
        validate=lambda *_a, **_k: "", spawn=lambda p: launched.append(p),
    )
    assert result.ok is True
    assert len(launched) == 1


def test_no_declaration_means_no_expectation(tmp_path, monkeypatch) -> None:
    """TOGGLE. Every unpinned run — hand-runs, dev invocations, every dispatch before this
    change — has no declaration on disk and must be completely unaffected."""
    import shared.fleet.swap_ops as so

    _no_scripts_env(monkeypatch)
    primary, _pinned = _pinned_world(tmp_path)
    cfg = build_default_config(str(primary), str(tmp_path / "projects"))
    assert so.read_scripts_pin_expectation(cfg) is None
    assert so.scripts_pin_violation(cfg) == ""


def test_declaration_matching_case_insensitively_is_honoured(tmp_path, monkeypatch) -> None:
    """The two sides are written by DIFFERENT processes (PowerShell and Python) on Windows.
    A case or separator difference is not a mismatch, and treating it as one would stand down
    a correctly pinned night."""
    import shared.fleet.swap_ops as so

    _no_scripts_env(monkeypatch)
    primary, pinned = _pinned_world(tmp_path)
    _declare(primary, str(pinned).upper().replace("\\", "/"))
    monkeypatch.setenv(_ENV_SCRIPTS, str(pinned))
    cfg = build_default_config(str(primary), str(tmp_path / "projects"))
    assert so.scripts_pin_violation(cfg) == ""


def test_execute_swap_dispatch_REFUSES_when_the_pin_is_violated(tmp_path, monkeypatch) -> None:
    """THE PRIMARY LOCK, and until now nothing proved it BLOCKS.

    ``execute_swap_dispatch`` is the path ``entrypoint.py`` uses for every EXECUTE. Its
    refusal existed and every occurrence of ``scripts_pin_violation`` in this suite was
    either the empty case or a monkeypatch TARGET — so deleting the six lines that refuse
    left the suite green. A lock with no test that it blocks is a lock nobody has checked.

    Drives the REAL function with a REAL declaration keyed to a genuinely running process,
    and asserts the refusal reaches the caller as ``ok=False`` with a readable message.
    Found by independent review, #1301 BLOCKING 2.

    Toggle: delete the ``if pin_violation:`` return in ``execute_swap_dispatch`` and this
    goes red while every other test in this file stays green.
    """
    import shared.fleet.swap_ops as so

    _no_scripts_env(monkeypatch)
    primary, pinned = _pinned_world(tmp_path)
    # Build the config FIRST, unpinned -- this is the real sequence: the AO resolves a config,
    # and the declaration can change under it before the dispatch fires. Declaring a tree that
    # does not EXIST would trip the unreadable-directory refusal inside build_default_config
    # instead, which is a different lock; ``pinned`` exists, so this exercises the MISMATCH.
    projects = tmp_path / "projects"
    # A VALID target. Without this the repo validation refuses first and ok=False arrives for
    # a reason that has nothing to do with the pin -- which is how the first draft of this test
    # passed with the refusal DELETED. A lock that fires on the wrong cause is not a lock.
    (projects / "demo").mkdir(parents=True)
    cfg = build_default_config(str(primary), str(projects))
    _declare(primary, pinned)
    assert cfg.scripts_dir != pinned, "the config must not already resolve to the pinned tree"

    result = so.execute_swap_dispatch(
        "r1", "s1", [{"task": "t", "repo": str(projects / "demo")}],
        config=cfg, gate_gb=0.0, old_pid=0, relaunch_argv=[], relaunch_cwd="",
    )

    assert result.ok is False, (
        "execute_swap_dispatch proceeded despite a live declaration pinning a different "
        "scripts tree - the dispatch would run scripts nobody asked for")
    assert "pin" in (result.message or "").lower(), (
        f"refused, but not for the PIN: {result.message!r}")


def test_a_dispatch_that_HONOURS_the_pin_is_not_refused(tmp_path, monkeypatch) -> None:
    """CONTROL for the lock above: it must refuse a MISMATCH, not refuse everything.

    Without this, ``execute_swap_dispatch`` could return ok=False unconditionally and the
    lock test above would still pass -- proving only that something said no."""
    import shared.fleet.swap_ops as so

    _no_scripts_env(monkeypatch)
    primary, pinned = _pinned_world(tmp_path)
    cfg = build_default_config(str(primary), str(tmp_path / "projects"))
    # The declaration names EXACTLY what this config resolves to.
    _declare(primary, cfg.scripts_dir)

    violation = so.scripts_pin_violation(cfg)

    assert violation == "", (
        f"a dispatch that honours the live declaration was reported as a violation: "
        f"{violation!r}")


def test_the_driver_refuses_a_spec_that_violates_the_declaration(tmp_path, monkeypatch) -> None:
    """The SECOND lock, at spec-READ time. A spec written before the declaration existed and
    re-read after a crash recovery never passes through execute_swap_dispatch again, so the
    driver has to be able to refuse on its own."""
    import shared.fleet.swap_ops as so

    _no_scripts_env(monkeypatch)
    primary, pinned = _pinned_world(tmp_path)
    monkeypatch.setenv(_ENV_SCRIPTS, str(pinned))
    cfg = build_default_config(str(primary), str(tmp_path / "projects"))
    captured = {}
    so.prepare_and_launch_swap(
        cfg, run_id="r1", session_id="s1", tasks=[{"task": "t", "repo": "x"}],
        old_pid=0, relaunch_argv=[], relaunch_cwd="", gate_gb=0.0,
        spawn=lambda p: captured.setdefault("spec", p),
    )
    # The declaration lands (or changes) only AFTER the spec was written.
    _declare(primary, tmp_path / "some-other-tree" / "scripts")
    with pytest.raises(FleetScriptsDirUnavailable):
        so.run_swap(captured["spec"])


# ---------------------------------------------------------------------------
# SCOPING (#1203 review). The pinned tree is a DETACHED worktree frozen at one
# commit. An unscoped declaration would govern the operator's everyday
# dispatches too, so between battery runs he would merge a fix, dispatch, and
# silently get the old behaviour — #1203's defect with the polarity reversed,
# and it never fails loudly because nothing fails. It resolves to the wrong
# thing, successfully.
# ---------------------------------------------------------------------------


def test_a_previous_runs_declaration_does_not_govern_a_new_dispatch(tmp_path, monkeypatch) -> None:
    """THE SCOPING LOCK. A declaration from a run that has ended is left in place — nobody
    cleaned it up, because a killed or rebooted night never gets to. A dispatch that is not
    that run must ignore it and resolve CURRENT code.

    Scope is the writing run's LIVENESS, which replaced a wall-clock expiry. The expiry was
    measured binding work its run never did: written at 23:00 with a 16h window, it still
    resolved the frozen tree at 09:00, so the operator's morning silently ran 23:00-vintage
    scripts. Liveness has no window to tune — it is false the instant the launcher is gone."""
    _no_scripts_env(monkeypatch)
    primary, pinned = _pinned_world(tmp_path)
    _declare(primary, pinned, alive=False)  # its launcher process has exited

    cfg = build_default_config(str(primary), str(tmp_path / "projects"))
    assert cfg.scripts_dir == primary / "scripts", (
        "a spent declaration still governed a new dispatch — the operator would be running "
        "code frozen at whatever commit that run pinned"
    )


def test_that_scoping_is_byte_identical_to_the_unpinned_default(tmp_path, monkeypatch) -> None:
    """A dispatch that IGNORES a declaration must behave exactly as if none existed —
    same path, same provenance, no trace of the pin anywhere."""
    _no_scripts_env(monkeypatch)
    primary, pinned = _pinned_world(tmp_path)
    declared = _declare(primary, pinned, alive=False)
    ignored = build_default_config(str(primary), str(tmp_path / "projects"))
    assert scripts_dir_provenance(primary) == "default"

    declared.unlink()
    none_at_all = build_default_config(str(primary), str(tmp_path / "projects"))
    assert ignored == none_at_all


def test_the_scoping_lock_has_teeth(tmp_path, monkeypatch) -> None:
    """TOGGLE for the lock above. With the liveness check disabled — i.e. the unscoped design
    the review rejected — the SAME spent declaration does govern the dispatch. Without this,
    the lock could pass against a fixture where nothing was ever declared."""
    import shared.fleet.dispatch as fd

    _no_scripts_env(monkeypatch)
    primary, pinned = _pinned_world(tmp_path)
    _declare(primary, pinned, alive=False)

    monkeypatch.setattr(fd, "_launcher_is_live", lambda pid, started_at, source: True)
    assert build_default_config(str(primary), str(tmp_path / "projects")).scripts_dir == pinned


def test_a_live_runs_declaration_still_governs_its_own_dispatch(tmp_path, monkeypatch) -> None:
    """CONTROL. Scoping must not break the case the pin exists for: while the run that wrote
    the declaration is still alive, its dispatches resolve the pinned scripts."""
    _no_scripts_env(monkeypatch)
    primary, pinned = _pinned_world(tmp_path)
    _declare(primary, pinned, alive=True)
    assert build_default_config(str(primary), str(tmp_path / "projects")).scripts_dir == pinned


def test_a_recycled_pid_cannot_resurrect_a_dead_runs_declaration(tmp_path, monkeypatch) -> None:
    """PID REUSE. Identity is the PAIR (pid, start time). A declaration naming a pid that IS
    running, but whose recorded start time belongs to a different process, is a dead run whose
    number got handed to someone else — it must not pin anything.

    Keyed to this live pytest process with a deliberately wrong start time, so the pid half of
    the check passes and only the start-time half can reject it."""
    import psutil

    _no_scripts_env(monkeypatch)
    primary, pinned = _pinned_world(tmp_path)
    pins = primary / "state" / "fleet-swap" / "pins"
    pins.mkdir(parents=True, exist_ok=True)
    real = datetime.fromtimestamp(psutil.Process(os.getpid()).create_time(), tz=timezone.utc)
    (pins / "recycled.json").write_text(
        json.dumps({
            "scripts_dir": str(pinned),
            "launcher_pid": os.getpid(),                       # a LIVE pid
            "launcher_started_at": (real - timedelta(hours=3)) # ...but not this process
                .strftime("%Y-%m-%dT%H:%M:%S.%f0Z"),
            "declared_at": "2026-07-30T23:00:00Z",
        }),
        encoding="utf-8",
    )
    cfg = build_default_config(str(primary), str(tmp_path / "projects"))
    assert cfg.scripts_dir == primary / "scripts"


def test_two_live_runs_pinning_different_trees_is_REFUSED(tmp_path, monkeypatch) -> None:
    """AMBIGUITY IS FAIL-CLOSED. Per-run declaration files mean two runs can be live at once.
    If they name different trees there is no correct answer, so the dispatch must refuse:
    picking either would report on code the other run was not executing — #1203's own shape."""
    _no_scripts_env(monkeypatch)
    primary, pinned = _pinned_world(tmp_path)
    other = tmp_path / "measured-two" / "scripts"
    other.mkdir(parents=True)
    _declare(primary, pinned, alive=True)
    # A second LIVE declaration, from a different run, naming a different tree.
    (primary / "state" / "fleet-swap" / "pins" / "second.json").write_text(
        (primary / "state" / "fleet-swap" / "pins" / f"20260730-230000-{os.getpid()}-fixture.json")
        .read_text(encoding="utf-8").replace(str(pinned).replace("\\", "\\\\"),
                                             str(other).replace("\\", "\\\\")),
        encoding="utf-8",
    )
    with pytest.raises(FleetScriptsDirUnavailable) as exc:
        build_default_config(str(primary), str(tmp_path / "projects"))
    assert "two coder runs" in str(exc.value)


def test_two_live_runs_pinning_the_SAME_tree_agree(tmp_path, monkeypatch) -> None:
    """CONTROL for the refusal above. Two live declarations that name the same tree are not an
    ambiguity, and must not be turned into one — otherwise an ordinary re-publish would stand
    a night down."""
    _no_scripts_env(monkeypatch)
    primary, pinned = _pinned_world(tmp_path)
    first = _declare(primary, pinned, alive=True)
    (primary / "state" / "fleet-swap" / "pins" / "second.json").write_text(
        first.read_text(encoding="utf-8"), encoding="utf-8",
    )
    assert build_default_config(str(primary), str(tmp_path / "projects")).scripts_dir == pinned


def test_a_corrupt_declaration_is_REFUSED_not_treated_as_absent(tmp_path, monkeypatch) -> None:
    """N2. ABSENT means unpinned. PRESENT-BUT-UNREADABLE is a different thing, and conflating
    them restored the original defect inside the control meant to prevent it: an empty file, a
    whitespace-only file and a directory all read as "no expectation", so the run proceeded
    against the PRIMARY's scripts, silently, on a pinned night.

    THE CASES ARE DERIVED FROM A REAL DECLARATION, not invented. The previous version of this
    test hand-listed seven shapes, and the enumeration was the bug: it asserted an empty file
    was "not hypothetical" when the writer of the day could no longer produce one, while
    omitting the shape that writer DID produce transiently — absence — which was the only one
    that failed open. Mutating a produced declaration means every case here is a real payload
    with one thing wrong with it, and the shapes track the producer when it changes.

    This REVERSES a position taken earlier in this ticket (malformed -> inert). Inert is right
    for a SPENT declaration, whose run is genuinely over; it is wrong for a corrupt one, where
    nothing is known and proceeding is a guess."""
    _no_scripts_env(monkeypatch)
    primary, pinned = _pinned_world(tmp_path)
    (primary / "scripts").mkdir()  # the fallback EXISTS, so a fail-open would succeed
    decl = _declare(primary, pinned, alive=True)
    good = decl.read_text(encoding="utf-8")
    payload = json.loads(good)

    def _without(key: str) -> str:
        return json.dumps({k: v for k, v in payload.items() if k != key})

    def _with(key: str, value) -> str:
        return json.dumps({**payload, key: value})

    cases = [
        ("truncated mid-write", good[: len(good) // 2]),
        ("empty file", ""),
        ("whitespace only", " " * 3 + chr(10) + "  "),
        ("not json", "{not json at all"),
        ("bare path, the pre-scoping format", str(pinned)),
        ("no scripts_dir", _without("scripts_dir")),
        ("blank scripts_dir", _with("scripts_dir", "   ")),
        ("no launcher_pid", _without("launcher_pid")),
        ("no launcher_started_at", _without("launcher_started_at")),
        ("non-numeric launcher_pid", _with("launcher_pid", "not-a-pid")),
        ("unparseable launcher_started_at", _with("launcher_started_at", "just now")),
    ]
    for label, content in cases:
        decl.write_text(content, encoding="utf-8")
        with pytest.raises(FleetScriptsDirUnavailable) as exc:
            build_default_config(str(primary), str(tmp_path / "projects"))
        assert "unpinned" in str(exc.value), f"{label}: the refusal must name the remedy"


def test_the_producer_cannot_emit_any_of_the_transient_shapes(tmp_path, monkeypatch) -> None:
    """THE OMISSION THAT MATTERED. Absence read as "unpinned" and resolved to the primary, so
    the one shape the old writer produced transiently was the one shape that failed open.

    The fix is not to refuse absence — an absent pin is how every unpinned dispatch on this box
    looks, and refusing it would stand them all down. It is that the producer no longer has a
    transient state at all: it publishes by renaming onto a name that never existed, so no
    reader ever sees a half-written or momentarily-deleted declaration. What this asserts is
    that a file the reader can SEE is never a file mid-write: the temp name carries no ``.json``
    and so cannot appear in the listing the resolver walks."""
    _no_scripts_env(monkeypatch)
    primary, pinned = _pinned_world(tmp_path)
    (primary / "scripts").mkdir()
    pins = primary / "state" / "fleet-swap" / "pins"
    pins.mkdir(parents=True, exist_ok=True)

    # A publish in progress, exactly as Publish-ScriptsPin stages it.
    (pins / ".20260730-230000-4242-abcd1234.tmp").write_text("{partial", encoding="utf-8")
    cfg = build_default_config(str(primary), str(tmp_path / "projects"))
    assert cfg.scripts_dir == primary / "scripts", "a staging file was visible to the resolver"
    assert scripts_dir_provenance(primary) == "default"

    # ...and once it lands under its final name, it governs.
    _declare(primary, pinned, alive=True)
    assert build_default_config(str(primary), str(tmp_path / "projects")).scripts_dir == pinned


def test_a_declaration_that_is_a_DIRECTORY_is_refused(tmp_path, monkeypatch) -> None:
    """H. A directory where a declaration belongs raises IsADirectoryError/PermissionError,
    which the old bare `except OSError` swallowed into "unpinned"."""
    _no_scripts_env(monkeypatch)
    primary, _pinned = _pinned_world(tmp_path)
    (primary / "scripts").mkdir()
    (primary / "state" / "fleet-swap" / "pins" / "wedged.json").mkdir(parents=True)
    with pytest.raises(FleetScriptsDirUnavailable):
        build_default_config(str(primary), str(tmp_path / "projects"))


def test_a_FILE_where_the_pins_directory_belongs_is_refused(tmp_path, monkeypatch) -> None:
    """The container itself, not just its contents. A file at the pins path means no
    declaration can ever be read there, which must refuse rather than resolve the primary."""
    _no_scripts_env(monkeypatch)
    primary, _pinned = _pinned_world(tmp_path)
    (primary / "scripts").mkdir()
    (primary / "state" / "fleet-swap" / "pins").write_text("not a directory", encoding="utf-8")
    with pytest.raises(FleetScriptsDirUnavailable):
        build_default_config(str(primary), str(tmp_path / "projects"))


def test_the_corrupt_declaration_lock_has_teeth(tmp_path, monkeypatch) -> None:
    """TOGGLE. With the old conflating read restored - anything unreadable to "" - the same
    corrupt declaration resolves the PRIMARY's scripts and the run proceeds. The defect,
    demonstrated, so the locks above cannot be passing vacuously."""
    import shared.fleet.dispatch as fd

    _no_scripts_env(monkeypatch)
    primary, _pinned = _pinned_world(tmp_path)
    (primary / "scripts").mkdir()
    pins = primary / "state" / "fleet-swap" / "pins"
    pins.mkdir(parents=True, exist_ok=True)
    (pins / "corrupt.json").write_text("", encoding="utf-8")

    def _conflating(setup_root: Path) -> str:
        try:
            return (setup_root / "state" / "fleet-swap" / "pins" / "corrupt.json").read_text(
                encoding="utf-8"
            ).strip()
        except OSError:
            return ""

    monkeypatch.setattr(fd, "read_live_declaration", _conflating)
    assert build_default_config(str(primary), str(tmp_path / "projects")).scripts_dir == primary / "scripts"


def test_an_absent_declaration_is_still_simply_unpinned(tmp_path, monkeypatch) -> None:
    """CONTROL. Refusing corruption must not have turned the ordinary no-declaration case into
    a refusal - that is every legacy dispatch on this box. Both the never-pinned shape (no pins
    directory at all) and the pinned-then-pruned shape (an empty one) are ordinary."""
    _no_scripts_env(monkeypatch)
    primary, _pinned = _pinned_world(tmp_path)
    cfg = build_default_config(str(primary), str(tmp_path / "projects"))
    assert cfg.scripts_dir == primary / "scripts"
    assert scripts_dir_provenance(primary) == "default"

    (primary / "state" / "fleet-swap" / "pins").mkdir(parents=True)
    assert build_default_config(str(primary), str(tmp_path / "projects")).scripts_dir == primary / "scripts"
    assert scripts_dir_provenance(primary) == "default"


def test_a_declaration_with_a_utf8_BOM_is_still_read(tmp_path, monkeypatch) -> None:
    """Windows PowerShell 5.1's `Set-Content -Encoding utf8` prepends EF BB BF. The launcher
    runs under pwsh 7, where it does not — but a sibling task in the same task folder uses
    powershell.exe, so 5.1 is a live habit in this repo and a BOM would otherwise turn a
    correctly-pinned night into a refusal. Tolerated on the READ side, which holds no matter
    who writes the file."""
    _no_scripts_env(monkeypatch)
    primary, pinned = _pinned_world(tmp_path)
    decl = _declare(primary, pinned, alive=True)
    decl.write_bytes(b"\xef\xbb\xbf" + decl.read_bytes())
    assert build_default_config(str(primary), str(tmp_path / "projects")).scripts_dir == pinned
