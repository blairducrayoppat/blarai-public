"""#829 (QUALITY-11) — the flake differential over the job-oracle grade.

When the job oracle FAILS on the integrated tree (the park-triggering path), it is
re-run ONCE in a fresh hermetic harness. A verdict FLIP (fail -> pass) means the GRADER
is nondeterministic, not the coder wrong: stamp ``oracle_flaky`` + both outputs and
reroute the park BUILD -> VERIFY. A deterministic failure re-runs identically -> no
flag. The GREEN / not-run paths are never re-run.

Every subprocess is injected (``run`` / ``hermetic_run`` seams), so the whole
differential runs model-free, GPU-free, and uv-free here — the B1n2 state-accumulation
shape is modelled as a state file so the flip is exercised deterministically. The one
place a real subprocess env is asserted (:func:`_default_hermetic_run`) monkeypatches
``subprocess.run`` and inspects the env it would launch, so no oracle is actually run.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from shared.fleet import grade_env
from shared.fleet import swap_ops as so
from shared.fleet.acceptance import JOB_ORACLE_PATH_PYTHON
from shared.fleet.dispatch import FleetDispatchConfig

_PY_ORACLE = (
    "from storage import save\n\n"
    "def test_save_roundtrip():\n"
    "    assert save(1) is not None\n"
)


def _config(tmp_path: Path) -> FleetDispatchConfig:
    return FleetDispatchConfig(
        scripts_dir=tmp_path / "scripts",
        queue_path=tmp_path / "state" / "q.json",
        runs_dir=tmp_path / "state" / "runs",
        projects_dir=tmp_path / "projects",
    )


def _repo(tmp_path: Path, name: str = "target") -> Path:
    repo = tmp_path / name
    (repo / ".git").mkdir(parents=True, exist_ok=True)
    return repo


def _fake_uv(monkeypatch):
    """The .py grade path needs `uv` on PATH (the injected runner replaces the real
    subprocess, so nothing runs) — patch shutil.which to hand back a fake uv/node."""
    monkeypatch.setattr(so.shutil, "which", lambda name: f"C:/fake/{name}.exe")


# ---------------------------------------------------------------------------
# The GREEN / not-run paths are NEVER re-run (the differential fires only on a park)
# ---------------------------------------------------------------------------


def test_passing_grade_is_not_rerun(tmp_path, monkeypatch):
    """A PASS is returned byte-untouched — the hermetic re-run never fires (the GREEN
    path must be identical to real_run_job_oracle: zero added latency, no flag)."""
    _fake_uv(monkeypatch)
    rerun_calls = {"n": 0}

    def hermetic_run(cmd, timeout_s, cwd=None, env=None):
        rerun_calls["n"] += 1
        return (True, "", "")

    res = so.real_run_job_oracle_flake_checked(
        _config(tmp_path), "G1", str(_repo(tmp_path)), JOB_ORACLE_PATH_PYTHON, _PY_ORACLE,
        run=lambda c, t, cwd=None, env=None: (True, "1 passed", ""), hermetic_run=hermetic_run)
    assert res["status"] == "passed"
    assert "oracle_flaky" not in res
    assert "flake_differential" not in res
    assert rerun_calls["n"] == 0  # the GREEN path never re-runs


def test_not_run_grade_is_not_rerun(tmp_path, monkeypatch):
    """An honest not-run (machinery miss / refusal) is not a park-triggering FAILURE —
    it is returned untouched and never re-run."""
    _fake_uv(monkeypatch)
    rerun_calls = {"n": 0}

    def hermetic_run(cmd, timeout_s, cwd=None, env=None):
        rerun_calls["n"] += 1
        return (True, "", "")

    # An unpinned path forces a not-run inside real_run_job_oracle without any subprocess.
    res = so.real_run_job_oracle_flake_checked(
        _config(tmp_path), "NR", str(_repo(tmp_path)), "../evil.py", _PY_ORACLE,
        run=lambda c, t, cwd=None, env=None: (True, "", ""), hermetic_run=hermetic_run)
    assert res["status"] == "not-run"
    assert "oracle_flaky" not in res
    assert rerun_calls["n"] == 0


# ---------------------------------------------------------------------------
# The differential: FLIP -> flaky ; deterministic failure -> no flag
# ---------------------------------------------------------------------------


def test_verdict_flip_flags_flaky_and_records_both_outputs(tmp_path, monkeypatch):
    """First grade FAILS, hermetic re-run PASSES -> the grader is nondeterministic:
    ``oracle_flaky`` is stamped, both outputs are recorded, the status STAYS 'failed'
    (never mints a pass), and <run>/oracle-flake.json is persisted."""
    _fake_uv(monkeypatch)
    res = so.real_run_job_oracle_flake_checked(
        _config(tmp_path), "FLIP", str(_repo(tmp_path)), JOB_ORACLE_PATH_PYTHON, _PY_ORACLE,
        run=lambda c, t, cwd=None, env=None: (False, "assert 689 == 1", ""),
        hermetic_run=lambda c, t, cwd=None, env=None: (True, "1 passed", ""))
    assert res["status"] == "failed"              # a flaky oracle can NEVER mint GREEN
    assert res["oracle_flaky"] is True
    diff = res["flake_differential"]
    assert diff["verdict"] == "flip"
    assert diff["first"]["status"] == "failed" and "689" in diff["first"]["evidence"]
    assert diff["hermetic_rerun"]["status"] == "passed"
    # Durable audit for #827/#832.
    out = _config(tmp_path).runs_dir / "FLIP" / "oracle-flake.json"
    assert out.is_file()
    assert json.loads(out.read_text(encoding="utf-8"))["verdict"] == "flip"


def test_deterministic_failure_reruns_identically_no_flag(tmp_path, monkeypatch):
    """The DUAL: a genuinely-broken build fails on BOTH the first grade and the fresh
    hermetic re-run -> NO oracle_flaky flag (the park stays a BUILD fault). The record
    names it 'confirmed' for the audit, but never flags."""
    _fake_uv(monkeypatch)
    res = so.real_run_job_oracle_flake_checked(
        _config(tmp_path), "DET", str(_repo(tmp_path)), JOB_ORACLE_PATH_PYTHON, _PY_ORACLE,
        run=lambda c, t, cwd=None, env=None: (False, "AssertionError: real bug", ""),
        hermetic_run=lambda c, t, cwd=None, env=None: (False, "AssertionError: real bug", ""))
    assert res["status"] == "failed"
    assert "oracle_flaky" not in res
    assert res["flake_differential"]["verdict"] == "confirmed"


def test_hermetic_machinery_miss_is_not_a_flake(tmp_path, monkeypatch):
    """Fail-conservative: if the hermetic re-run cannot RUN (honest not-run — no uv, a
    timeout), that is NOT a flip. No flag; the failure stands (BUILD)."""
    _fake_uv(monkeypatch)

    def hermetic_not_run(cmd, timeout_s, cwd=None, env=None):
        # Simulate the re-run's own machinery miss: real_run_job_oracle turns a runner
        # that can't produce output into a graded 'failed'; to model a not-run we drop
        # uv only for the re-run by raising, which the wrapper reads as non-pass.
        raise RuntimeError("uv vanished mid-run")

    res = so.real_run_job_oracle_flake_checked(
        _config(tmp_path), "MISS", str(_repo(tmp_path)), JOB_ORACLE_PATH_PYTHON, _PY_ORACLE,
        run=lambda c, t, cwd=None, env=None: (False, "assert 689 == 1", ""),
        hermetic_run=hermetic_not_run)
    assert res["status"] == "failed"
    assert "oracle_flaky" not in res  # an unrunnable re-run can't PROVE flakiness


# ---------------------------------------------------------------------------
# B1n2 STATE-ACCUMULATION FIXTURE LOCK — the shape the ticket names
# ---------------------------------------------------------------------------


def test_b1n2_state_accumulation_shape_flags_flaky(tmp_path, monkeypatch):
    """B1n2: state accumulated across a property test's examples, so the oracle's verdict
    depended on execution HISTORY (`assert 689 == 1` — the accumulator grew past 1). This
    models that exact shape: the AMBIENT grade reads a POLLUTED state file (residue from
    prior grades -> the count is 689 -> the property fails), while the HERMETIC re-run,
    with its fresh temp/DB, reads a FRESH state (count 1 -> passes). The flip -> flaky."""
    _fake_uv(monkeypatch)
    # Residue on disk from prior grades — the "accumulated state" execution history.
    polluted = tmp_path / "accumulated_state.txt"
    polluted.write_text("689", encoding="utf-8")

    def ambient_run(cmd, timeout_s, cwd=None, env=None):
        # The oracle reads the ACCUMULATED (polluted) state -> `assert 689 == 1` FAILS.
        n = int(polluted.read_text(encoding="utf-8"))
        return (n == 1, f"assert {n} == 1", "")

    def hermetic_run(cmd, timeout_s, cwd=None, env=None):
        # A FRESH hermetic harness: the accumulator starts at 1 (no history) -> PASSES.
        # (In production the fresh TMPDIR + HYPOTHESIS_STORAGE_DIRECTORY give exactly this
        # clean slate; here the fake stands in for that fresh state deterministically.)
        return (True, "assert 1 == 1", "")

    res = so.real_run_job_oracle_flake_checked(
        _config(tmp_path), "B1N2", str(_repo(tmp_path)), JOB_ORACLE_PATH_PYTHON, _PY_ORACLE,
        run=ambient_run, hermetic_run=hermetic_run)
    assert res["status"] == "failed"        # PARKED-HONEST holds — never GREEN
    assert res["oracle_flaky"] is True      # the grader, not the coder, is at fault
    assert res["flake_differential"]["verdict"] == "flip"


def test_b1n2_but_deterministic_failure_does_not_false_flag(tmp_path, monkeypatch):
    """The guard against the dual error: if the SAME state is present on both runs (a
    genuinely deterministic property failure — real accumulation with no fresh slate,
    or a real bug), the hermetic re-run fails identically -> NOT flagged flaky. This is
    what stops the differential from laundering every property failure into VERIFY."""
    _fake_uv(monkeypatch)
    state = tmp_path / "state.txt"
    state.write_text("689", encoding="utf-8")

    def both_read_same_state(cmd, timeout_s, cwd=None, env=None):
        n = int(state.read_text(encoding="utf-8"))
        return (n == 1, f"assert {n} == 1", "")

    res = so.real_run_job_oracle_flake_checked(
        _config(tmp_path), "DET2", str(_repo(tmp_path)), JOB_ORACLE_PATH_PYTHON, _PY_ORACLE,
        run=both_read_same_state, hermetic_run=both_read_same_state)
    assert res["status"] == "failed"
    assert "oracle_flaky" not in res
    assert res["flake_differential"]["verdict"] == "confirmed"


# ---------------------------------------------------------------------------
# The hermetic harness genuinely gives a FRESH temp + Hypothesis DB (the hermeticity)
# ---------------------------------------------------------------------------


def test_default_hermetic_run_isolates_temp_and_hypothesis_db(tmp_path, monkeypatch):
    """The production hermeticity: _default_hermetic_run launches the SAME argv/cwd but
    with a FRESH TMP + a FRESH, empty HYPOTHESIS_STORAGE_DIRECTORY (distinct from the
    ambient env), so an oracle whose verdict rides accumulated cross-run state grades
    from a clean slate. Asserted by capturing the env it would launch (no real run)."""
    captured = {}

    class _CP:
        returncode = 0
        stdout = "1 passed"
        stderr = ""

    def fake_subprocess_run(cmd, **kw):
        captured["cmd"] = cmd
        captured["cwd"] = kw.get("cwd")
        captured["env"] = kw.get("env")
        captured["timeout"] = kw.get("timeout")
        return _CP()

    monkeypatch.setattr(so.subprocess, "run", fake_subprocess_run)
    monkeypatch.setenv("HYPOTHESIS_STORAGE_DIRECTORY", "C:/ambient/should-be-overridden")
    monkeypatch.setenv("TEMP", "C:/ambient/temp")

    # real_run_job_oracle passes #822's clean-env overlay on the .py path — model it.
    clean_overlay = grade_env.clean_grade_env("C:/repo")
    ok, out, err = so._default_hermetic_run(
        ["uv", "run", "pytest"], 600.0, cwd="C:/repo", env=clean_overlay)
    assert ok is True and "passed" in out
    env = captured["env"]
    # Same command + cwd as the grade path (imports resolve from the repo root).
    assert captured["cmd"] == ["uv", "run", "pytest"] and captured["cwd"] == "C:/repo"
    # #822 clean-env recipe PRESERVED — the interleaving lock (grader-integrity intact).
    assert env["PYTHONPATH"] == clean_overlay["PYTHONPATH"] == "C:/repo"
    assert env["PYTHONSAFEPATH"] == "1"
    # FRESH Hypothesis DB + TEMP — NOT the ambient values (the #829 clean slate), layered
    # on top of #822's overlay (disjoint keys, so both survive).
    assert env["HYPOTHESIS_STORAGE_DIRECTORY"] != "C:/ambient/should-be-overridden"
    assert env["TEMP"] != "C:/ambient/temp"
    assert Path(env["HYPOTHESIS_STORAGE_DIRECTORY"]).name == "hypothesis"
    assert env["TMP"] == env["TEMP"] == env["TMPDIR"]
    assert env["PYTHONDONTWRITEBYTECODE"] == "1"
    # os.environ base preserved (PATH still present — not a bare overlay).
    assert "PATH" in env or "Path" in env
    # The re-run is capped at the registered bound (never longer than a grade).
    assert captured["timeout"] == so.JOB_ORACLE_FLAKE_RERUN_TIMEOUT_S


def test_default_hermetic_run_without_env_is_node_path_shape(tmp_path, monkeypatch):
    """The node grade path passes NO env (byte-identical to today): _default_hermetic_run
    then merges only os.environ + the hermetic channels (no clean-env overlay to keep)."""
    captured = {}

    class _CP:
        returncode = 0
        stdout = ""
        stderr = ""

    monkeypatch.setattr(so.subprocess, "run",
                        lambda cmd, **kw: (captured.update(env=kw.get("env")), _CP())[1])
    so._default_hermetic_run(["node", "--test", "x.mjs"], 600.0, cwd="C:/repo")
    env = captured["env"]
    assert env["HYPOTHESIS_STORAGE_DIRECTORY"] and env["PYTHONDONTWRITEBYTECODE"] == "1"
    # No env overlay passed → no PYTHONSAFEPATH from the clean-env recipe (node needs none).
    assert env.get("PYTHONSAFEPATH") != "1" or "PYTHONSAFEPATH" in os.environ
    assert "PATH" in env or "Path" in env  # os.environ base still present


def test_default_hermetic_run_caps_at_registered_bound(tmp_path, monkeypatch):
    """A caller-passed timeout ABOVE the registered cap is clamped down (the re-run can
    never legitimately run longer than a grade); a smaller one is honoured."""
    seen = {}

    class _CP:
        returncode = 1
        stdout = ""
        stderr = ""

    monkeypatch.setattr(so.subprocess, "run",
                        lambda cmd, **kw: (seen.update(timeout=kw.get("timeout")), _CP())[1])
    so._default_hermetic_run(["x"], 99999.0, cwd=None)
    assert seen["timeout"] == so.JOB_ORACLE_FLAKE_RERUN_TIMEOUT_S
    so._default_hermetic_run(["x"], 5.0, cwd=None)
    assert seen["timeout"] == 5.0
