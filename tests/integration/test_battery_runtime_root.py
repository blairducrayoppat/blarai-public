"""#1181: the AO's boot root is separable from the harness's own tree.

The battery is pinned to a dedicated worktree so a night measures a named commit on
``main`` rather than whatever two working trees were parked on. But ``models/`` is
gitignored and therefore exists in exactly ONE checkout, so the Assistant Orchestrator
must still boot from the primary tree. Three constants in this package spelled both
roots the same way (``Path(__file__).resolve().parents[2]``); pinning without splitting
them destroys a night in three separate places.

The isolated-resolver tests below are cheap. The ones that matter are the REACHABILITY
tests: they re-import the real modules in a subprocess with the override set and assert
the shipped constants moved. A resolver nothing calls is the built-but-wired-into-nothing
failure, and it would pass every unit test in this file.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from tools.dispatch_harness.runtime_root import (
    RUNTIME_ROOT_ENV,
    RuntimeRootError,
    resolve_runtime_root,
)

_REPO_ROOT = Path(__file__).resolve().parents[2]


def _checkout(tmp_path: Path, name: str) -> Path:
    """A directory shaped enough like a checkout to boot ``python -m launcher``."""
    root = tmp_path / name
    (root / "launcher").mkdir(parents=True)
    (root / "launcher" / "__main__.py").write_text("# stub\n", encoding="utf-8")
    return root


# ---------------------------------------------------------------------------
# The resolver contract
# ---------------------------------------------------------------------------


def test_unset_returns_the_harness_root_unchanged(monkeypatch, tmp_path):
    """The default IS today's behavior — an unpinned battery must not change at all."""
    monkeypatch.delenv(RUNTIME_ROOT_ENV, raising=False)
    harness = _checkout(tmp_path, "harness")
    assert resolve_runtime_root(harness) == harness


@pytest.mark.parametrize("blank", ["", "   ", "\t"])
def test_blank_override_is_treated_as_unset(monkeypatch, tmp_path, blank):
    """An empty variable is how PowerShell spells "not set"; it must not be a path."""
    monkeypatch.setenv(RUNTIME_ROOT_ENV, blank)
    harness = _checkout(tmp_path, "harness")
    assert resolve_runtime_root(harness) == harness


def test_valid_override_replaces_the_harness_root(monkeypatch, tmp_path):
    harness = _checkout(tmp_path, "harness")
    runtime = _checkout(tmp_path, "runtime")
    monkeypatch.setenv(RUNTIME_ROOT_ENV, str(runtime))
    assert resolve_runtime_root(harness) == runtime.resolve()


def test_missing_directory_raises_rather_than_falling_back(monkeypatch, tmp_path):
    """Fail-closed. A fallback here would boot a weightless AO and report a normal night."""
    harness = _checkout(tmp_path, "harness")
    monkeypatch.setenv(RUNTIME_ROOT_ENV, str(tmp_path / "nope"))
    with pytest.raises(RuntimeRootError) as exc:
        resolve_runtime_root(harness)
    assert "not a directory" in str(exc.value)


def test_a_file_is_not_a_root(monkeypatch, tmp_path):
    harness = _checkout(tmp_path, "harness")
    victim = tmp_path / "a-file"
    victim.write_text("", encoding="utf-8")
    monkeypatch.setenv(RUNTIME_ROOT_ENV, str(victim))
    with pytest.raises(RuntimeRootError):
        resolve_runtime_root(harness)


def test_directory_without_launcher_package_is_refused(monkeypatch, tmp_path):
    """The marker is the actual precondition for ``python -m launcher``, not a proxy."""
    harness = _checkout(tmp_path, "harness")
    bare = tmp_path / "bare"
    bare.mkdir()
    monkeypatch.setenv(RUNTIME_ROOT_ENV, str(bare))
    with pytest.raises(RuntimeRootError) as exc:
        resolve_runtime_root(harness)
    assert "launcher/__main__.py" in str(exc.value)


def test_the_error_names_the_variable_so_a_night_log_is_actionable(monkeypatch, tmp_path):
    harness = _checkout(tmp_path, "harness")
    monkeypatch.setenv(RUNTIME_ROOT_ENV, str(tmp_path / "nope"))
    with pytest.raises(RuntimeRootError) as exc:
        resolve_runtime_root(harness)
    assert RUNTIME_ROOT_ENV in str(exc.value)


# ---------------------------------------------------------------------------
# REACHABILITY — the shipped constants actually consult the resolver
# ---------------------------------------------------------------------------


def _probe_constants(env_value: str | None) -> dict:
    """Import the real modules in a clean interpreter and report their roots.

    A subprocess because these are module-level constants: re-importing in-process
    would either hit the module cache or contaminate every later test in the session.
    """
    src = (
        "import json\n"
        "from tools.dispatch_harness import battery, probe\n"
        "print(json.dumps({\n"
        "    'battery_harness': str(battery._REPO_ROOT),\n"
        "    'battery_runtime': str(battery._BLARAI_REPO_ROOT),\n"
        "    'battery_specs': str(battery.DEFAULT_SPEC_DIR),\n"
        "    'probe_runtime': str(probe._BLARAI_REPO_ROOT),\n"
        "}))\n"
    )
    env = {
        k: v
        for k, v in __import__("os").environ.items()
        if k != RUNTIME_ROOT_ENV
    }
    if env_value is not None:
        env[RUNTIME_ROOT_ENV] = env_value
    cp = subprocess.run(  # noqa: S603 — constant argv, no shell
        [sys.executable, "-c", src],
        capture_output=True, text=True, timeout=120, cwd=str(_REPO_ROOT), env=env,
    )
    assert cp.returncode == 0, f"import failed: {cp.stderr}"
    return json.loads(cp.stdout.strip().splitlines()[-1])


def test_battery_and_probe_default_to_their_own_tree(tmp_path):
    """Unset: every root collapses to the harness tree — the pre-#1181 shape exactly."""
    got = _probe_constants(None)
    assert got["battery_runtime"] == got["battery_harness"]
    assert got["probe_runtime"] == got["battery_harness"]


def test_the_override_moves_the_ao_boot_root_in_both_modules(tmp_path):
    """The reachability lock: set the variable, and the SHIPPED constants move."""
    runtime = _checkout(tmp_path, "runtime")
    got = _probe_constants(str(runtime))
    assert Path(got["battery_runtime"]) == runtime.resolve()
    assert Path(got["probe_runtime"]) == runtime.resolve()


def test_the_override_does_NOT_move_the_harness_root_or_the_exam_cards(tmp_path):
    """The other half of the split. If the cards followed the runtime root, pinning
    would measure the primary checkout's exam — which is the bug, not the fix."""
    runtime = _checkout(tmp_path, "runtime")
    got = _probe_constants(str(runtime))
    assert Path(got["battery_harness"]) == _REPO_ROOT
    assert Path(got["battery_specs"]) == _REPO_ROOT / "evals" / "battery"


def test_a_bad_override_refuses_at_import_rather_than_booting_wrong(tmp_path):
    """Toggle-off proof that the fail-closed path is real: a malformed override must
    take the process down, not degrade to the harness tree."""
    src = "from tools.dispatch_harness import battery\nprint(battery._BLARAI_REPO_ROOT)\n"
    env = {
        k: v for k, v in __import__("os").environ.items() if k != RUNTIME_ROOT_ENV
    }
    env[RUNTIME_ROOT_ENV] = str(tmp_path / "does-not-exist")
    cp = subprocess.run(  # noqa: S603 — constant argv, no shell
        [sys.executable, "-c", src],
        capture_output=True, text=True, timeout=120, cwd=str(_REPO_ROOT), env=env,
    )
    assert cp.returncode != 0, "a bad runtime root must NOT import cleanly"
    assert "RuntimeRootError" in cp.stderr or RUNTIME_ROOT_ENV in cp.stderr


def test_the_unnamed_config_follows_the_installation_not_the_measuring_tree(
    monkeypatch, tmp_path
):
    """``default.toml`` describes the installation, so a split must not read this tree's.

    The nightly names its config explicitly, so this is the HAND-RUN path: a session
    running the harness out of the pinned worktree would otherwise silently configure the
    run from ``main``'s copy rather than the one the running orchestrator booted on.
    """
    from tools.dispatch_harness.config import _REPO_ROOT as cfg_root
    from tools.dispatch_harness.config import default_config_path

    monkeypatch.delenv(RUNTIME_ROOT_ENV, raising=False)
    assert default_config_path() == cfg_root / "services" / (
        "assistant_orchestrator"
    ) / "config" / "default.toml"

    runtime = _checkout(tmp_path, "runtime")
    monkeypatch.setenv(RUNTIME_ROOT_ENV, str(runtime))
    assert default_config_path().parents[3] == runtime.resolve()


def test_an_explicitly_named_config_still_wins_over_the_installation(monkeypatch, tmp_path):
    """The override is a DEFAULT, not a redirect: --config still names what it names."""
    from tools.dispatch_harness.config import load_harness_config

    runtime = _checkout(tmp_path, "runtime")
    monkeypatch.setenv(RUNTIME_ROOT_ENV, str(runtime))
    named = tmp_path / "side.toml"
    named.write_text("[ipc]\nvsock_port = 5099\n", encoding="utf-8")
    cfg = load_harness_config(named)
    assert cfg.config_path == named
    assert cfg.port == 5099


# ---------------------------------------------------------------------------
# The scorecard's condition stamp — containment, not the branch name
# ---------------------------------------------------------------------------


def _git(repo: Path, *args: str) -> None:
    subprocess.run(  # noqa: S603 — vector argv, no shell
        ["git", "-c", "user.email=t@x", "-c", "user.name=t", *args],
        cwd=str(repo), capture_output=True, text=True, timeout=30, check=True,
    )


def _repo_with_main(tmp_path: Path, name: str) -> Path:
    repo = tmp_path / name
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    (repo / "f.txt").write_text("one\n", encoding="utf-8")
    _git(repo, "add", "f.txt")
    _git(repo, "commit", "-q", "-m", "on main")
    return repo


def test_a_detached_head_at_a_merged_commit_reports_contained(monkeypatch, tmp_path):
    """The shape a correctly pinned measurement tree is in EVERY night.

    Git refuses to check out ``main`` in a second worktree, so the pin is detached by
    construction. Reading the branch name here yields ``"detached"`` forever — which is
    why the name cannot be the correctness test.
    """
    from tools.dispatch_harness import battery

    repo = _repo_with_main(tmp_path, "pinned")
    _git(repo, "checkout", "-q", "--detach", "main")
    monkeypatch.setattr(battery, "_REPO_ROOT", repo)

    assert battery._git_on_main() == "yes"
    assert battery._git_tree_state()[0] == "detached"


def test_an_unmerged_commit_reports_not_contained(monkeypatch, tmp_path):
    """The toggle: the property must FAIL on the tree the whole ticket is about."""
    from tools.dispatch_harness import battery

    repo = _repo_with_main(tmp_path, "parked")
    _git(repo, "checkout", "-q", "-b", "feat/parked")
    (repo / "f.txt").write_text("two\n", encoding="utf-8")
    _git(repo, "commit", "-q", "-am", "unmerged work")
    monkeypatch.setattr(battery, "_REPO_ROOT", repo)

    assert battery._git_on_main() == "no"
    assert battery._git_tree_state()[0] == "feat/parked"


def test_an_unanswerable_containment_question_reports_unknown(monkeypatch, tmp_path):
    """No repository, no ``main``, no git: an unknown must never render as a pass."""
    from tools.dispatch_harness import battery

    bare = tmp_path / "not-a-repo"
    bare.mkdir()
    monkeypatch.setattr(battery, "_REPO_ROOT", bare)
    assert battery._git_on_main() == "unknown"


def test_the_stamp_carries_containment_alongside_the_branch(monkeypatch, tmp_path):
    """Reachability: the SHIPPED stamp, not the helper. Both fields must be present —
    the branch as provenance a human reads, containment as the property a check reads."""
    from tools.dispatch_harness import battery

    repo = _repo_with_main(tmp_path, "stamped")
    _git(repo, "checkout", "-q", "--detach", "main")
    monkeypatch.setattr(battery, "_REPO_ROOT", repo)

    versions = battery.runner_versions()
    assert versions["blarai_on_main"] == "yes"
    assert versions["blarai_branch"] == "detached"
    assert versions["blarai_tree"] == "clean"


def test_the_harness_certs_lookup_follows_the_runtime_root(monkeypatch, tmp_path):
    """The failure that bites FIRST under a naive pin, and the one nobody predicted:
    the harness's own mTLS client resolves ``certs/`` from its module tree. Driven
    through the real ``DispatchHarness.for_live`` so the assertion is about shipped
    behavior, not about the resolver in isolation."""
    from tools.dispatch_harness.harness import DispatchHarness

    runtime = _checkout(tmp_path, "runtime")
    monkeypatch.setenv(RUNTIME_ROOT_ENV, str(runtime))
    with pytest.raises(FileNotFoundError) as exc:
        DispatchHarness.for_live(
            port=5001,
            agentic_setup_dir=str(tmp_path / "agentic"),
            projects_dir=str(tmp_path / "projects"),
            session_id="t",
        )
    # The certs it went looking for are under the RUNTIME root, not this checkout.
    assert str(runtime.resolve()) in str(exc.value)
    assert str(_REPO_ROOT / "certs") not in str(exc.value)
