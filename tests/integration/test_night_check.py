"""Locks on `tools/probes/night_check.py`, the mid-run battery health check.

The property under lock is the one the check got WRONG in its first draft, caught by
running it against a live run rather than by reading it:

    **A busy model server is not evidence that the coder is working.**

`ovms` serves whatever model is loaded. A wedged generation burning CPU and producing
nothing is precisely the failure this check exists to catch (#1365: *"the 30B stops
producing and nothing but a ten-minute timer notices"*), so treating CPU as sufficient
would make the check report HEALTHY in exactly the case it was written for.

Output — writes into the task worktrees or the run directory — is the primary signal.
CPU is corroboration only.

The second locked property is that it **never kills anything**. The in-run idle
watchdog once false-killed ~84% of 30B candidates on a blind signal; a check that acts
on the same class of signal at a shorter interval recreates that. This one reports.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_TOOL = Path(__file__).resolve().parents[2] / "tools" / "probes" / "night_check.py"


def _load():
    spec = importlib.util.spec_from_file_location("night_check", _TOOL)
    assert spec is not None and spec.loader is not None, f"cannot load {_TOOL}"
    mod = importlib.util.module_from_spec(spec)
    sys.modules["night_check"] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def nc():
    assert _TOOL.is_file(), (
        f"{_TOOL} is missing. It is wired to the BlarAI-Battery-3amCheck scheduled task; "
        "if it moved, move the task and this lock with it."
    )
    return _load()


def _mk_state(tmp_path: Path, *, run_ended: bool = False) -> Path:
    """A state root shaped like the real one: state/battery/night-*, state/fleet-runs/*.

    NOTE the journal ALWAYS carries RUN-END and SUMMARY.txt is ALWAYS present, because in
    a real run BOTH appear per TASK, from the first task onward. The original fixture
    wrote RUN-END only when ``run_ended`` was true — encoding the author's assumption
    instead of the artifact — so the whole suite passed over a classifier that called
    every run "finished" after its first task. ``run_ended`` is now driven by
    ``scorecard.json``, which is written once, at the end.
    """
    (tmp_path / "battery" / "night-20260101-230000").mkdir(parents=True)
    run = tmp_path / "fleet-runs" / "20260101-230100-bd"
    run.mkdir(parents=True)
    (run / "journal.log").write_text(
        "RUN-START x\nTASK-START y\nRUN-END | processed=1\n", encoding="utf-8"
    )
    (run / "SUMMARY.txt").write_text("per-task summary, rewritten each task\n", encoding="utf-8")
    if run_ended:
        (run / "scorecard.json").write_text('{"verdict": "PARKED-HONEST"}', encoding="utf-8")
    (tmp_path / "worktrees").mkdir(parents=True)
    return tmp_path


def test_busy_cpu_with_no_output_is_not_healthy(nc, tmp_path, monkeypatch):
    """THE lock. The first draft called this HEALTHY. It is the wedge signature.

    Model server burning CPU, nothing written anywhere. If a future change restores
    `cpu_moving or wt_moving or rd_moving`, this fails.
    """
    state = _mk_state(tmp_path)
    monkeypatch.setattr(nc, "STATE", state)
    monkeypatch.setattr(nc, "CPU_SAMPLE_GAP_S", 0)
    cpu = iter([100.0, 250.0])  # climbing hard
    monkeypatch.setattr(nc, "_ovms_cpu_seconds", lambda: next(cpu))
    monkeypatch.setattr(nc, "_newest_write", lambda root, within: False)  # nothing produced

    r = nc.check()
    assert r["verdict"] != "HEALTHY", (
        "a model server burning CPU while producing NOTHING was reported healthy. That is the "
        f"wedge this check exists to catch; verdict was {r['verdict']!r}"
    )
    assert r["verdict"] == "BUSY-BUT-PRODUCING-NOTHING"


def test_output_moving_is_healthy_even_if_cpu_sample_misses(nc, tmp_path, monkeypatch):
    """The converse. Real work must not be reported as a stall.

    CPU sampling is a 45-second window and can legitimately catch a gap between tokens.
    Files appearing in the worktree is unambiguous evidence of progress.
    """
    state = _mk_state(tmp_path)
    monkeypatch.setattr(nc, "STATE", state)
    monkeypatch.setattr(nc, "CPU_SAMPLE_GAP_S", 0)
    monkeypatch.setattr(nc, "_ovms_cpu_seconds", lambda: 100.0)  # flat across the sample
    monkeypatch.setattr(nc, "_newest_write", lambda root, within: True)

    r = nc.check()
    assert r["verdict"] == "HEALTHY", (
        f"work was being written and the check said {r['verdict']!r}. A false stall alarm is how "
        "a watchdog trains people to ignore it."
    )


def test_everything_flat_is_a_stall(nc, tmp_path, monkeypatch):
    state = _mk_state(tmp_path)
    monkeypatch.setattr(nc, "STATE", state)
    monkeypatch.setattr(nc, "CPU_SAMPLE_GAP_S", 0)
    monkeypatch.setattr(nc, "_ovms_cpu_seconds", lambda: 100.0)
    monkeypatch.setattr(nc, "_newest_write", lambda root, within: False)

    r = nc.check()
    assert r["verdict"] == "STALLED"
    assert "killed" in r["detail"], "the report must say plainly that nothing was killed"


def test_a_dead_model_server_mid_run_is_not_silently_fine(nc, tmp_path, monkeypatch):
    """The unclean-shutdown shape: server gone, no end marker written."""
    state = _mk_state(tmp_path, run_ended=False)
    monkeypatch.setattr(nc, "STATE", state)
    monkeypatch.setattr(nc, "_ovms_cpu_seconds", lambda: None)

    r = nc.check()
    assert r["verdict"] == "STOPPED-WITHOUT-FINISHING"


def test_a_finished_run_is_reported_finished_not_stalled(nc, tmp_path, monkeypatch):
    state = _mk_state(tmp_path, run_ended=True)
    monkeypatch.setattr(nc, "STATE", state)
    monkeypatch.setattr(nc, "_ovms_cpu_seconds", lambda: None)

    r = nc.check()
    assert r["verdict"] == "FINISHED"


def test_it_never_kills_anything(nc):
    """A reporting watchdog must contain no kill path at all.

    Not a style preference: the in-run watchdog false-killed ~84% of candidates on a
    blind signal, and whether anything may kill a run autonomously is an operator
    decision. If someone adds one here, this fails and sends them to ask.
    """
    source = _TOOL.read_text(encoding="utf-8")
    for forbidden in ("Stop-Process", "taskkill", "os.kill", "terminate()", "SIGKILL"):
        assert forbidden not in source, (
            f"{forbidden!r} appears in a REPORTING watchdog. Killing a run autonomously is an "
            "operator decision, and a blind-signal killer already cost ~84% of candidates once."
        )
