"""Tests for swap_ops — boot-reconcile gating + the AO-side handoff + file helpers.

The subprocess ops (start-llm / run-fleet / Stop-Process / launcher relaunch) are
live and verified on-hardware; here we test the existence-gating, the spec/state
writes, and the report/queue/status file writes (real_stop_ovms + the toast
subprocess are patched so no real process is touched).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from shared.fleet import swap_ops as so
from shared.fleet import swap_state as ss
from shared.fleet.dispatch import DispatchResult, FleetDispatchConfig, TaskOutcome


def _cfg(tmp_path):
    state = tmp_path / "state"
    return FleetDispatchConfig(
        scripts_dir=tmp_path / "scripts",
        queue_path=state / "fleet-queue.json",
        runs_dir=state / "fleet-runs",
        projects_dir=tmp_path / "projects",
    )


def _git_repo(cfg, name="myapp"):
    (cfg.projects_dir / name / ".git").mkdir(parents=True)


# ---- reconcile_at_boot gating ---------------------------------------------


def test_reconcile_at_boot_clean_is_noop(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(so, "real_stop_ovms", lambda: calls.append(1))
    res = so.reconcile_at_boot(_cfg(tmp_path))
    assert res is None          # no swap-state, no sentinel -> no-op
    assert calls == []          # NO subprocess on a clean boot


def test_reconcile_at_boot_ignores_bare_fleet_sentinel(tmp_path, monkeypatch):
    # F2: BlarAI booting while the operator runs the 30B (fleet sentinel armed, NO
    # BlarAI swap-state) must be a TOTAL no-op — never disarm the fleet or kill its OVMS.
    calls = []
    monkeypatch.setattr(so, "real_stop_ovms", lambda: calls.append(1))
    cfg = _cfg(tmp_path)
    sent = so.sentinel_path(cfg)
    sent.parent.mkdir(parents=True, exist_ok=True)
    sent.write_text("coder-30b", encoding="utf-8")
    res = so.reconcile_at_boot(cfg)
    assert res is None          # no BlarAI swap-state -> no-op
    assert sent.exists()        # fleet sentinel UNTOUCHED
    assert calls == []          # fleet OVMS NOT stopped


def test_reconcile_at_boot_in_flight_when_swap_state_present(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(so, "real_stop_ovms", lambda: calls.append(1))
    cfg = _cfg(tmp_path)
    sent = so.sentinel_path(cfg)
    sent.parent.mkdir(parents=True, exist_ok=True)
    sent.write_text("coder-30b", encoding="utf-8")
    ss.write_swap_state(
        ss.SwapState(run_id="R9", session_id="s", phase=ss.PHASE_CODE,
                     tasks=[{"repo": "r", "task": "t", "prompt": "p"}]),
        path=so.swap_state_path(cfg),
    )
    res = so.reconcile_at_boot(cfg)
    assert res is not None and res.in_flight and res.run_id == "R9"
    assert not sent.exists()    # OUR swap -> disarm
    assert calls == [1]         # OUR swap -> stop


# ---- AO-side handoff ------------------------------------------------------


def test_prepare_and_launch_swap_writes_state_spec_and_spawns(tmp_path):
    cfg = _cfg(tmp_path)
    so.cancel_path(cfg).parent.mkdir(parents=True, exist_ok=True)
    so.cancel_path(cfg).write_text("x", encoding="utf-8")  # a stale cancel must clear
    spawned = {}
    so.prepare_and_launch_swap(
        cfg, run_id="R1", session_id="s1",
        tasks=[{"repo": "X", "task": "a", "prompt": "p"}],
        old_pid=4321, relaunch_argv=["py", "-m", "launcher"], relaunch_cwd="C:/x",
        gate_gb=21.0, spawn=lambda p: spawned.setdefault("path", p),
    )
    st = ss.read_swap_state(so.swap_state_path(cfg))
    assert st.phase == ss.PHASE_HANDOFF and st.run_id == "R1" and len(st.tasks) == 1
    spec = json.loads((so.swap_dir(cfg) / "spec.json").read_text(encoding="utf-8"))
    assert spec["old_pid"] == 4321 and spec["relaunch_argv"] == ["py", "-m", "launcher"]
    assert spec["gate_gb"] == 21.0 and spec["run_id"] == "R1"
    assert spawned["path"] == so.swap_dir(cfg) / "spec.json"
    assert not so.cancel_path(cfg).exists()       # stale cancel cleared


# ---- file helpers ---------------------------------------------------------


def test_write_single_task_queue(tmp_path):
    p = so.write_single_task_queue(_cfg(tmp_path), {"repo": "X", "task": "a", "prompt": "p"})
    assert json.loads(p.read_text(encoding="utf-8")) == [{"repo": "X", "task": "a", "prompt": "p"}]


def test_write_cumulative_report(tmp_path):
    from shared.fleet.dispatch import parse_summary  # the parser the harness + gateway both use

    cfg = _cfg(tmp_path)
    outs = [TaskOutcome(task="a", outcome="processed", result="MERGED",
                        detail="RESULT: MERGED into your project."),
            TaskOutcome(task="b", outcome="errored", result="BLOCKED",
                        detail="RESULT: BLOCKED: a potential secret was detected.")]
    so.write_cumulative_report(cfg, "R1", outs)
    txt = (cfg.runs_dir / "R1" / "SUMMARY.txt").read_text(encoding="utf-8")
    assert "2 task(s)" in txt
    # The cumulative file MUST be parseable by the SAME parse_summary the harness + gateway use:
    # a divergent shape made them classify the final outcome as NONE at swap-back (#686).
    parsed = parse_summary(txt)
    assert [(o.task, o.result) for o in parsed] == [("a", "MERGED"), ("b", "BLOCKED")]


def test_write_failure_status(tmp_path):
    cfg = _cfg(tmp_path)
    so.write_failure_status(cfg, "R1", "swap failed — restart BlarAI")
    assert "swap failed" in so.status_path(cfg, "R1").read_text(encoding="utf-8")


# ---- orchestrate_swap_dispatch (AO-side, steps 1-5) -----------------------


def test_orchestrate_happy_decompose_validate_handoff(tmp_path):
    import json as _j

    cfg = _cfg(tmp_path)
    _git_repo(cfg)
    spawned = {}
    # Two DISTINCT features (both survive right-sizing) so the multi-task validate + handoff
    # coverage holds. #670 P2: EXECUTE now VALIDATES each repo directly (no shared-queue write)
    # — the real validate_repo passes because _git_repo made projects/myapp a git repo.
    res = so.orchestrate_swap_dispatch(
        "add health and readiness endpoints", "myapp", "sess1", config=cfg,
        generate_fn=lambda _p: _j.dumps([{"task": "add-health-endpoint", "prompt": "add /health"},
                                         {"task": "add-readiness-endpoint", "prompt": "add /ready"}]),
        gate_gb=21.0, old_pid=99, relaunch_argv=["py", "-m", "launcher"], relaunch_cwd="C:/x",
        spawn=lambda p: spawned.setdefault("p", p),
        mint_run_id=lambda: "RID-DET",
    )
    assert res.ok and res.run_id == "RID-DET" and len(res.tasks) == 2
    assert "RID-DET" in res.message and "/dispatch status RID-DET" in res.message
    assert spawned["p"] == so.swap_dir(cfg) / "spec.json"  # driver spawned
    st = ss.read_swap_state(so.swap_state_path(cfg))
    assert st.phase == ss.PHASE_HANDOFF and len(st.tasks) == 2
    # #670 P2: the operator's SHARED fleet-queue.json must NEVER be written by EXECUTE.
    assert not cfg.queue_path.exists()


def test_orchestrate_bad_repo_rejects_before_handoff(tmp_path):
    cfg = _cfg(tmp_path)
    _git_repo(cfg)
    spawned = []
    res = so.orchestrate_swap_dispatch(
        "idea", "nonexistent", "s", config=cfg,
        generate_fn=lambda _p: "[]", gate_gb=21.0, old_pid=1,
        relaunch_argv=["py"], relaunch_cwd="C:/x",
        spawn=lambda p: spawned.append(p), mint_run_id=lambda: "R",
    )
    assert not res.ok and spawned == []     # bad repo -> no swap


def test_orchestrate_validate_failure_no_handoff(tmp_path):
    cfg = _cfg(tmp_path)
    _git_repo(cfg)
    spawned = []
    res = so.orchestrate_swap_dispatch(
        "make it fast", "myapp", "s", config=cfg,
        generate_fn=lambda _p: "garbage",   # -> decompose falls back to one task
        gate_gb=21.0, old_pid=1, relaunch_argv=["py"], relaunch_cwd="C:/x",
        validate=lambda repo, projects_dir: "refused",
        spawn=lambda p: spawned.append(p), mint_run_id=lambda: "R",
    )
    assert not res.ok and "refused" in res.message and spawned == []  # no driver spawned


# ---- reconcile_at_boot_for_roots (#670 — config-driven crash recovery) -----


@pytest.mark.real_reconcile  # exercises the reconcile seam itself (inner call faked; #758 guard opt-out)
def test_reconcile_at_boot_for_roots_uses_configured_root(monkeypatch):
    # #670: the boot reconciler must READ swap-state under the CONFIGURED fleet root, not
    # the compiled-in fallback — else on a custom-root box the EXECUTE writer and this
    # recoverer disagree and the restore-the-14B / never-end-at-zero recovery never fires.
    seen = {}
    sentinel = object()

    def _fake_reconcile(cfg):
        seen["cfg"] = cfg
        return sentinel

    monkeypatch.setattr(so, "reconcile_at_boot", _fake_reconcile)
    result = so.reconcile_at_boot_for_roots("X:/custom/agentic", "Y:/proj")
    assert result is sentinel                                   # pass-through
    cfg = seen["cfg"]
    assert cfg.runs_dir == Path("X:/custom/agentic/state/fleet-runs")
    assert cfg.queue_path == Path("X:/custom/agentic/state/fleet-queue.json")
    assert cfg.scripts_dir == Path("X:/custom/agentic/scripts")
    assert cfg.projects_dir == Path("Y:/proj")


@pytest.mark.real_reconcile  # exercises the reconcile seam itself (inner call faked; #758 guard opt-out)
def test_reconcile_at_boot_for_roots_falls_back_on_empty(monkeypatch):
    # Empty roots (the "config key absent" case) fall back to the compiled-in default.
    seen = {}
    monkeypatch.setattr(so, "reconcile_at_boot", lambda cfg: seen.setdefault("cfg", cfg))
    so.reconcile_at_boot_for_roots("", "")
    assert seen["cfg"].scripts_dir.parent.name == "agentic-setup"
    assert seen["cfg"].projects_dir.name == "projects"


# ---- execute_swap_dispatch (the EXECUTE pre-decomposed pass-through, #670) --


def test_execute_swap_dispatch_runs_approved_tasks_no_decompose(tmp_path):
    # EXECUTE hands off the APPROVED tasks verbatim (no generate_fn, no re-decompose). #670 P2:
    # it VALIDATES each repo (here injected OK) — and writes NOTHING to the shared fleet-queue.
    cfg = _cfg(tmp_path)
    validated, spawned = [], {}
    tasks = [{"repo": "X", "task": "a", "prompt": "p1"},
             {"repo": "X", "task": "b", "prompt": "p2"}]
    res = so.execute_swap_dispatch(
        "RID-X", "s1", tasks, config=cfg, gate_gb=21.0, old_pid=99,
        relaunch_argv=["py", "-m", "launcher"], relaunch_cwd="C:/x",
        validate=lambda repo, projects_dir: (validated.append(str(repo)), None)[1],
        spawn=lambda p: spawned.setdefault("p", p),
    )
    assert res.ok and res.run_id == "RID-X" and len(res.tasks) == 2
    assert "RID-X" in res.message and "/dispatch status RID-X" in res.message
    assert validated == ["X", "X"]                             # each repo validated, verbatim
    assert spawned["p"] == so.swap_dir(cfg) / "spec.json"       # driver handoff
    st = ss.read_swap_state(so.swap_state_path(cfg))
    assert st.phase == ss.PHASE_HANDOFF and len(st.tasks) == 2
    assert not cfg.queue_path.exists()                          # shared queue NEVER written


def test_execute_swap_dispatch_empty_tasks_no_handoff(tmp_path):
    cfg = _cfg(tmp_path)
    spawned = []
    res = so.execute_swap_dispatch(
        "R", "s", [], config=cfg, gate_gb=21.0, old_pid=1,
        relaunch_argv=["py"], relaunch_cwd="C:/x", spawn=lambda p: spawned.append(p),
    )
    assert not res.ok and spawned == []  # nothing approved -> no swap


def test_execute_swap_dispatch_validate_failure_no_handoff(tmp_path):
    cfg = _cfg(tmp_path)
    spawned = []
    res = so.execute_swap_dispatch(
        "R", "s", [{"repo": "X", "task": "a", "prompt": "p"}],
        config=cfg, gate_gb=21.0, old_pid=1, relaunch_argv=["py"], relaunch_cwd="C:/x",
        validate=lambda repo, projects_dir: "refused",
        spawn=lambda p: spawned.append(p),
    )
    assert not res.ok and "refused" in res.message and spawned == []  # 14B untouched


def test_execute_swap_dispatch_never_writes_operator_queue(tmp_path):
    # #670 P2 (no destructive data): even when the operator has manually queued overnight tasks
    # in the SHARED fleet-queue.json, EXECUTE must NOT touch it (the prior enqueue/reset would
    # have appended-to / wiped it). The swap runs from swap-state, never this file.
    cfg = _cfg(tmp_path)
    cfg.queue_path.parent.mkdir(parents=True, exist_ok=True)
    operator_tasks = '[{"repo":"C:/proj/other","task":"overnight","prompt":"do it"}]'
    cfg.queue_path.write_text(operator_tasks, encoding="utf-8")
    so.execute_swap_dispatch(
        "R", "s", [{"repo": "X", "task": "a", "prompt": "p"}],
        config=cfg, gate_gb=21.0, old_pid=1, relaunch_argv=["py"], relaunch_cwd="C:/x",
        validate=lambda repo, projects_dir: None, spawn=lambda p: None,
    )
    assert cfg.queue_path.read_text(encoding="utf-8") == operator_tasks  # byte-identical


def test_orchestrate_still_decomposes_then_delegates(tmp_path):
    # orchestrate (combined form) decomposes then runs execute_swap_dispatch.
    import json as _j
    cfg = _cfg(tmp_path)
    _git_repo(cfg)
    spawned = {}
    res = so.orchestrate_swap_dispatch(
        "add health + tests", "myapp", "s1", config=cfg,
        generate_fn=lambda _p: _j.dumps([{"task": "add-health", "prompt": "add /health"}]),
        gate_gb=21.0, old_pid=99, relaunch_argv=["py"], relaunch_cwd="C:/x",
        spawn=lambda p: spawned.setdefault("p", p), mint_run_id=lambda: "RID-DET",
    )
    assert res.ok and res.run_id == "RID-DET" and len(res.tasks) == 1


# ---- writer-root == reconciler-root (#670) --------------------------------


@pytest.mark.real_reconcile  # exercises the reconcile seam itself (inner call faked; #758 guard opt-out)
def test_swap_state_writer_root_matches_reconciler_root(monkeypatch):
    # The EXECUTE writer persists swap-state under build_default_config(root); the boot
    # reconciler reads under build_default_config(root) too -> SAME path. Pin them equal so
    # a custom-root box can never desync the writer and the crash-recoverer.
    root = "X:/custom/agentic"
    cfg = so.build_default_config(root, "Y:/proj")
    writer_path = so.swap_state_path(cfg)
    seen = {}
    monkeypatch.setattr(so, "reconcile_at_boot",
                        lambda c: seen.setdefault("path", so.swap_state_path(c)))
    so.reconcile_at_boot_for_roots(root, "Y:/proj")
    assert seen["path"] == writer_path
    assert str(writer_path).startswith(str(Path(root)))


# ---- compute_relaunch_argv (pure relaunch capture, #670) ------------------


def test_compute_relaunch_argv_winui():
    argv, cwd = so.compute_relaunch_argv(winui=True, python_exe="py.exe", repo_root="C:/repo")
    assert argv == ["py.exe", "-m", "launcher", "--winui"]
    assert Path(cwd) == Path("C:/repo")


def test_compute_relaunch_argv_tui_and_golive():
    argv, _cwd = so.compute_relaunch_argv(
        winui=False, go_live=True, python_exe="py.exe", repo_root="C:/repo"
    )
    assert argv == ["py.exe", "-m", "launcher", "--go-live"]  # no --winui in tui mode


def test_compute_relaunch_argv_default_root_is_repo_root():
    # The default repo_root resolves to this checkout's root (has shared/ + launcher/).
    argv, cwd = so.compute_relaunch_argv(winui=True, python_exe="py.exe")
    assert argv[-1] == "--winui"
    assert (Path(cwd) / "launcher").exists() and (Path(cwd) / "shared").exists()


def test_compute_relaunch_argv_resolves_venv_python(tmp_path):
    # No python_exe -> resolve <repo_root>/.venv/Scripts/python.exe (#670 run-1 bug 2: the
    # relaunch must NOT inherit a foreign sys.executable like system Python311).
    venv_py = tmp_path / ".venv" / "Scripts" / "python.exe"
    venv_py.parent.mkdir(parents=True)
    venv_py.write_text("")  # presence is all _venv_python checks
    argv, _cwd = so.compute_relaunch_argv(winui=True, repo_root=str(tmp_path))
    assert argv[0] == str(venv_py)
    assert argv[1:] == ["-m", "launcher", "--winui"]


def test_compute_relaunch_argv_falls_back_to_sys_executable_without_venv(tmp_path):
    # No .venv present -> last-resort sys.executable (never crash the relaunch).
    import sys

    argv, _cwd = so.compute_relaunch_argv(winui=False, repo_root=str(tmp_path))
    assert argv[0] == sys.executable
    assert argv[1:] == ["-m", "launcher"]


# ---- #761: pythonw spawn chain — no VISIBLE console, no HIDDEN console -----
#
# Root cause (#761 c.1424): ``.venv\Scripts\python.exe`` is the Windows venv LAUNCHER
# SHIM — it spawns the BASE console-subsystem interpreter as a CHILD, so a
# DETACHED_PROCESS spawn is defeated one hop down: the child, born to a console-less
# parent, is allocated a fresh VISIBLE console the operator can accidentally close
# (the night-2 window-close incident class). Fix: the detached launcher/driver chain
# spawns via pythonw.exe (GUI subsystem — no console EVER), and NEVER via
# CREATE_NO_WINDOW — a HIDDEN console is the exact shape that crashed Textual on
# 2026-07-06 ("Driver must be in application mode"). pwsh/git children of the now
# console-less driver are the inverse case: console-subsystem, non-interactive,
# output-redirected — they DO ride CREATE_NO_WINDOW (the C15 audit outcome).

_CREATE_NO_WINDOW = 0x08000000
_DETACHED_PROCESS = 0x00000008


def _fake_venv(tmp_path, *, pythonw=True):
    scripts = tmp_path / ".venv" / "Scripts"
    scripts.mkdir(parents=True)
    (scripts / "python.exe").write_text("")
    if pythonw:
        (scripts / "pythonw.exe").write_text("")
    return scripts


def test_venv_pythonw_resolves_when_present(tmp_path):
    scripts = _fake_venv(tmp_path)
    assert so._venv_pythonw(tmp_path) == str(scripts / "pythonw.exe")


def test_venv_pythonw_falls_back_to_venv_python_when_absent(tmp_path):
    # No pythonw in the venv -> _venv_python's result, unchanged (never a broken spawn).
    scripts = _fake_venv(tmp_path, pythonw=False)
    assert so._venv_pythonw(tmp_path) == str(scripts / "python.exe")


def test_pythonw_sibling_resolves_and_falls_back(tmp_path):
    py = tmp_path / "python.exe"
    py.write_text("")
    assert so.pythonw_sibling(str(py)) == str(py)        # no sibling -> unchanged
    pyw = tmp_path / "pythonw.exe"
    pyw.write_text("")
    assert so.pythonw_sibling(str(py)) == str(pyw)       # sibling present -> preferred
    other = tmp_path / "python3.exe"
    other.write_text("")
    assert so.pythonw_sibling(str(other)) == str(other)  # non-standard name -> unchanged


def test_compute_relaunch_argv_emits_pythonw_path(tmp_path):
    # #761: the relaunch argv (the spec the detached driver respawns at swap-back) is
    # THE source of the visible swap-back window — it must carry pythonw.exe.
    scripts = _fake_venv(tmp_path)
    argv, _cwd = so.compute_relaunch_argv(winui=True, repo_root=str(tmp_path))
    assert argv[0] == str(scripts / "pythonw.exe")
    assert argv[1:] == ["-m", "launcher", "--winui"]


def test_spawn_detached_driver_uses_pythonw_sibling(tmp_path, monkeypatch):
    import subprocess as sp
    import sys

    scripts = _fake_venv(tmp_path)
    captured = {}

    def fake_popen(cmd, **kw):
        captured["cmd"] = cmd
        captured["kw"] = kw

    monkeypatch.setattr(sys, "executable", str(scripts / "python.exe"))
    monkeypatch.setattr(sp, "Popen", fake_popen)
    so._spawn_detached_driver(tmp_path / "spec.json")
    assert captured["cmd"][0] == str(scripts / "pythonw.exe")
    assert captured["cmd"][1:3] == ["-m", "shared.fleet.swap_ops"]
    flags = captured["kw"]["creationflags"]
    assert flags & _DETACHED_PROCESS
    # 2026-07-06 incident pin: NEVER CREATE_NO_WINDOW on a python-launcher spawn — a
    # HIDDEN console crashed Textual ("Driver must be in application mode").
    assert flags & _CREATE_NO_WINDOW == 0


def test_spawn_detached_driver_falls_back_to_sys_executable(tmp_path, monkeypatch):
    import subprocess as sp
    import sys

    scripts = _fake_venv(tmp_path, pythonw=False)
    captured = {}
    monkeypatch.setattr(sys, "executable", str(scripts / "python.exe"))
    monkeypatch.setattr(sp, "Popen", lambda cmd, **kw: captured.update(cmd=cmd))
    so._spawn_detached_driver(tmp_path / "spec.json")
    assert captured["cmd"][0] == str(scripts / "python.exe")  # never a broken spawn


def test_restart_launcher_never_create_no_window(tmp_path, monkeypatch):
    # The relaunch spawn keeps DETACHED on BOTH branches (the argv carries pythonw via
    # the spec); pin that neither branch reaches for the crash-shape CREATE_NO_WINDOW
    # (the 2026-07-06 Textual application-mode incident).
    import subprocess as sp

    flags_seen = []

    class _P:
        def poll(self):
            return None

    def fake_popen(cmd, **kw):
        flags_seen.append(kw.get("creationflags", 0))
        if len(flags_seen) == 1:
            raise OSError("not in a job object")   # exercise the BREAKAWAY-less fallback too
        return _P()

    monkeypatch.setattr(sp, "Popen", fake_popen)
    ops = so.build_swap_ops(_cfg(tmp_path), run_id="R", old_pid=1,
                            relaunch_argv=["pyw.exe", "-m", "launcher"], relaunch_cwd="C:/x")
    ops.restart_launcher()
    assert len(flags_seen) == 2                    # primary + OSError-fallback branch
    for flags in flags_seen:
        assert flags & _DETACHED_PROCESS
        assert flags & _CREATE_NO_WINDOW == 0


def test_spawn_detached_driver_gives_the_child_real_std_handles(tmp_path, monkeypatch):
    """2026-07-08 live-verify catch: a pythonw child with no explicit std handles
    can inherit a broken-but-present stderr and die on its first non-ASCII print
    (the relaunched launcher crashed encoding its BANNER, cp1252, SWAP_FAILED).
    Every detached python spawn must wire DEVNULL in + a UTF-8 log out +
    PYTHONIOENCODING=utf-8, the proven boot_launcher_detached shape."""
    import subprocess as sp
    import sys

    scripts = _fake_venv(tmp_path)
    captured = {}

    def fake_popen(cmd, **kw):
        captured["cmd"] = cmd
        captured["kw"] = kw

    monkeypatch.setattr(sys, "executable", str(scripts / "python.exe"))
    monkeypatch.setattr(sp, "Popen", fake_popen)
    so._spawn_detached_driver(tmp_path / "spec.json")
    kw = captured["kw"]
    assert kw["stdin"] == sp.DEVNULL
    assert kw["stdout"] is not None and kw["stderr"] == sp.STDOUT
    assert kw["env"]["PYTHONIOENCODING"] == "utf-8"
    # the stdio log lands beside the spec (the fleet-swap dir)
    assert (tmp_path / "driver-stdio.log").exists()


def test_restart_launcher_gives_the_child_real_std_handles(tmp_path, monkeypatch):
    """The leg-3 crash itself: the relaunch Popen passed NO std handles — fine
    for the old visible-console python.exe child, fatal under the #761 pythonw
    chain. Both branches (BREAKAWAY + fallback) must wire the handles + env."""
    import subprocess as sp

    seen = []

    class _P:
        def poll(self):
            return None

    def fake_popen(cmd, **kw):
        seen.append(kw)
        if len(seen) == 1:
            raise OSError("not in a job object")
        return _P()

    monkeypatch.setattr(sp, "Popen", fake_popen)
    ops = so.build_swap_ops(_cfg(tmp_path), run_id="R", old_pid=1,
                            relaunch_argv=["pyw.exe", "-m", "launcher"], relaunch_cwd="C:/x")
    ops.restart_launcher()
    assert len(seen) == 2
    for kw in seen:
        assert kw["stdin"] == sp.DEVNULL
        assert kw["stdout"] is not None and kw["stderr"] == sp.STDOUT
        assert kw["env"]["PYTHONIOENCODING"] == "utf-8"
    assert (so.swap_dir(_cfg(tmp_path)) / "ao-relaunch.log").exists()


def test_run_to_logfile_children_get_no_window(tmp_path):
    # #761 C15 audit outcome: the start-llm pwsh child rides CREATE_NO_WINDOW —
    # console-subsystem, non-interactive, file-redirected; under the console-less
    # pythonw driver it would otherwise be allocated a fresh VISIBLE console.
    import os
    from types import SimpleNamespace

    captured = {}

    def fake_run(cmd, **kw):
        captured.update(kw)
        return SimpleNamespace(returncode=0)

    assert so._run_to_logfile(["pwsh"], log_path=tmp_path / "l.log", timeout_s=5.0,
                              run=fake_run) is True
    assert captured["creationflags"] == so._NO_WINDOW
    assert so._NO_WINDOW == (_CREATE_NO_WINDOW if os.name == "nt" else 0)


def test_run_to_logfile_tree_children_get_no_window(tmp_path):
    # Same audit outcome for the LONG-LIVED run-fleet pwsh subtree — an hours-long
    # visible console is the exact accidental-close hazard #761 closes.
    captured = {}

    def fake_popen(cmd, **kw):
        captured.update(kw)
        return _FakeProc(rc=0)

    ok, _timed_out = so._run_to_logfile_tree(
        ["pwsh"], log_path=tmp_path / "l.log", timeout_s=5.0,
        popen=fake_popen, terminate_tree=lambda p: None,
    )
    assert ok is True
    assert captured["creationflags"] == so._NO_WINDOW


def test_safe_run_children_get_no_window(monkeypatch):
    # _safe_run is the same mechanism one level down: pwsh/git/tasklist children of the
    # console-less driver (short flashes; a wave-gate pytest child holds one ~600s).
    import os
    import subprocess as sp
    from types import SimpleNamespace

    from shared.fleet import dispatch as fd

    captured = {}

    def fake_run(cmd, **kw):
        captured.update(kw)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(sp, "run", fake_run)
    ok, _out, _err = fd._safe_run(["git", "status"], 5.0)
    assert ok is True
    assert captured["creationflags"] == fd._NO_WINDOW
    assert fd._NO_WINDOW == (_CREATE_NO_WINDOW if os.name == "nt" else 0)


# ---- (1) start-llm launch: no inheritable capture pipe (#670 run-2) --------


def test_run_to_logfile_uses_no_capture_pipe(tmp_path):
    # The start-llm launch MUST redirect to a FILE with close_fds — never a captured
    # pipe (OVMS + the qwen-proxy grandchildren would hold it open and deadlock the wait).
    import subprocess
    from types import SimpleNamespace

    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        captured["kwargs"] = kwargs
        return SimpleNamespace(returncode=0)

    log = tmp_path / "runs" / "RID" / "start-llm.log"
    ok = so._run_to_logfile(
        ["pwsh", "-File", "start-llm.ps1"], log_path=log, timeout_s=5.0, run=fake_run
    )
    assert ok is True
    kw = captured["kwargs"]
    assert "capture_output" not in kw  # never the deadlock-prone capture pipe
    assert kw["stdout"] is not subprocess.PIPE
    assert hasattr(kw["stdout"], "write")  # a real file handle, not a pipe
    assert kw["stderr"] is subprocess.STDOUT  # merged into the same file
    assert kw["close_fds"] is True  # no foreign fd inheritance
    assert kw["stdin"] is subprocess.DEVNULL
    assert log.exists()  # output preserved for diagnosis


def test_run_to_logfile_false_on_nonzero(tmp_path):
    from types import SimpleNamespace

    ok = so._run_to_logfile(
        ["x"], log_path=tmp_path / "l.log", timeout_s=5.0,
        run=lambda *a, **k: SimpleNamespace(returncode=1),
    )
    assert ok is False


def test_run_to_logfile_fail_closed_on_timeout(tmp_path):
    import subprocess

    def boom(*_a, **_k):
        raise subprocess.TimeoutExpired(cmd="x", timeout=5)

    assert so._run_to_logfile(["x"], log_path=tmp_path / "l.log", timeout_s=5.0, run=boom) is False


def test_real_load_30b_wires_per_run_log_and_start_llm(tmp_path, monkeypatch):
    # real_load_30b targets the per-run start-llm.log + the -Force cmd, via _run_to_logfile.
    seen = {}

    def fake_logfile(cmd, *, log_path, timeout_s, **_kw):
        seen.update(cmd=cmd, log_path=log_path, timeout_s=timeout_s)
        return True

    monkeypatch.setattr(so, "_run_to_logfile", fake_logfile)
    cfg = so.build_default_config(str(tmp_path / "agentic"), str(tmp_path / "projects"))
    assert so.real_load_30b(cfg, "RID-7") is True
    assert seen["cmd"][-3:] == ["-Model", "coder-30b", "-Force"]
    assert seen["log_path"] == cfg.runs_dir / "RID-7" / "start-llm.log"
    assert seen["timeout_s"] == 480.0   # #747: cold compile-cache load headroom (~289s live)


def test_safe_run_still_captures_stdout_for_parsing_callers():
    # SCOPE LOCK (#670 run-2): build/test/verify (run-fleet) PARSE stdout, so the generic
    # _safe_run MUST keep capturing it — only the start-llm launch moved off the pipe.
    import sys

    from shared.fleet.dispatch import _safe_run

    ok, out, _err = _safe_run([sys.executable, "-c", "print('PARSEME')"], timeout_s=30)
    assert ok and "PARSEME" in out


# ---- swap progress log (restart-surviving, #670) --------------------------


def test_swap_progress_appends_and_survives(tmp_path):
    cfg = _cfg(tmp_path)
    so.write_swap_progress(cfg, "RID", "stepping aside")
    so.write_swap_progress(cfg, "RID", "30B loading")
    trail = so.read_swap_progress(cfg, "RID")
    assert "stepping aside" in trail and "30B loading" in trail
    assert trail.count("\n") == 2                     # appended, not overwritten
    assert so.read_swap_progress(cfg, "nope") == ""   # missing run -> ''


def test_build_swap_ops_progress_writes_to_run_id_path(tmp_path):
    # The detached driver (via build_swap_ops) writes to the SAME run-id-keyed path the AO
    # started + /dispatch status reads — one continuous trail across the process boundary.
    cfg = _cfg(tmp_path)
    ops = so.build_swap_ops(cfg, run_id="RID", old_pid=1, relaunch_argv=["py"], relaunch_cwd="C:/x")
    ops.write_progress("30B loading")
    assert "30B loading" in so.read_swap_progress(cfg, "RID")
    assert so.swap_progress_path(cfg, "RID").exists()


def test_build_swap_ops_critic_enabled_reflects_env(tmp_path, monkeypatch):
    # #687 task 2: the observable critic_enabled flag + the wired run_critic op must AGREE with the
    # env read IN THIS process (the false-dormant trap: set on the wrong process -> the driver is
    # blind and a working build looks "dormant"). Same predicate, so they can never drift.
    from shared.fleet.swap_driver import _noop_critic

    cfg = _cfg(tmp_path)
    args = dict(run_id="R", old_pid=1, relaunch_argv=["py"], relaunch_cwd="C:/x")

    monkeypatch.delenv("BLARAI_ENABLE_CRITIC", raising=False)
    off = so.build_swap_ops(cfg, **args)
    assert off.critic_enabled is False
    assert off.run_critic is _noop_critic            # dormant -> the no-op

    monkeypatch.setenv("BLARAI_ENABLE_CRITIC", "1")
    on = so.build_swap_ops(cfg, **args)
    assert on.critic_enabled is True
    assert on.run_critic is not _noop_critic         # active -> the real critic closure

    # Junk values are NOT enabled (only 1/true/yes/on count) -> fail-closed predicate.
    monkeypatch.setenv("BLARAI_ENABLE_CRITIC", "maybe")
    junk = so.build_swap_ops(cfg, **args)
    assert junk.critic_enabled is False
    assert junk.run_critic is _noop_critic


# ==========================================================================
# #670 Problem 2 — task-run de-deadlock, budget holder, worktree sweep, config
# ==========================================================================


class _FakeProc:
    """A minimal subprocess.Popen stand-in for the tree-killable runner + holder tests."""

    def __init__(self, *, pid=4321, rc=0, timeout_first=False):
        self.pid = pid
        self._rc = rc
        self._timeout_first = timeout_first
        self._waits = 0
        self.killed = False

    def wait(self, timeout=None):
        self._waits += 1
        if self._timeout_first and self._waits == 1:
            import subprocess

            raise subprocess.TimeoutExpired(cmd="x", timeout=timeout)
        return self._rc

    def poll(self):
        return None if not self.killed else self._rc

    def kill(self):
        self.killed = True


# ---- _run_to_logfile_tree: no capture pipe + register/deregister -----------


def test_run_to_logfile_tree_no_capture_and_on_spawn(tmp_path):
    import subprocess

    seen, captured = [], {}

    def fake_popen(cmd, **kw):
        captured["kw"] = kw
        return _FakeProc(rc=0)

    ok, timed_out = so._run_to_logfile_tree(
        ["pwsh", "-File", "run-fleet.ps1"], log_path=tmp_path / "runs" / "R" / "t.log",
        timeout_s=5.0, on_spawn=seen.append, popen=fake_popen, terminate_tree=lambda p: None,
    )
    assert ok is True and timed_out is False
    kw = captured["kw"]
    assert "capture_output" not in kw                  # never the deadlock-prone capture pipe
    assert kw["stderr"] is subprocess.STDOUT and kw["close_fds"] is True
    assert kw["stdin"] is subprocess.DEVNULL
    assert hasattr(kw["stdout"], "write")              # a real file handle, not a pipe
    assert len(seen) == 2 and seen[0] is not None and seen[1] is None   # registered then cleared


def test_real_run_task_uses_tree_runner_and_per_task_log(tmp_path, monkeypatch):
    # The wedge fix: real_run_task drives run-fleet through the tree-killable file-redirect
    # runner (NOT the capture-pipe _safe_run), at a per-task log path, and hands the child to
    # the watchdog via on_spawn.
    seen = {}

    def fake_tree(cmd, *, log_path, timeout_s, on_spawn=None):
        seen.update(cmd=cmd, log_path=log_path, timeout_s=timeout_s, on_spawn=on_spawn)
        return True, False

    monkeypatch.setattr(so, "_run_to_logfile_tree", fake_tree)
    cfg = so.build_default_config(str(tmp_path / "agentic"), str(tmp_path / "projects"))
    (cfg.runs_dir / "RID").mkdir(parents=True, exist_ok=True)
    (cfg.runs_dir / "RID" / "SUMMARY.txt").write_text(
        "- t: processed\n  RESULT: MERGED into your project\n", encoding="utf-8")
    sentinel = object()
    oc = so.real_run_task(cfg, "RID", {"repo": "X", "task": "t", "prompt": "p"}, on_spawn=sentinel)
    assert "run-fleet.ps1" in str(seen["cmd"]) and seen["cmd"][-2:] == ["-RunId", "RID"]
    assert seen["log_path"] == cfg.runs_dir / "RID" / "run-fleet-t.log"
    assert seen["timeout_s"] == so.TASK_TIMEOUT_S
    assert seen["on_spawn"] is sentinel                # the budget-watchdog seam is wired
    assert oc.task == "t" and oc.result == "MERGED"


def test_run_to_logfile_tree_treekills_whole_tree_on_timeout(tmp_path):
    killed, seen = [], []
    proc = _FakeProc(timeout_first=True)
    ok, timed_out = so._run_to_logfile_tree(
        ["x"], log_path=tmp_path / "l.log", timeout_s=0.01,
        on_spawn=seen.append, popen=lambda *a, **k: proc,
        terminate_tree=lambda p: killed.append(p),
    )
    assert ok is False
    assert timed_out is True                           # #757: the kill is REPORTED, not swallowed
    assert killed == [proc]                            # the WHOLE held tree, not proc.kill() alone
    assert seen[-1] is None                            # holder cleared BEFORE the kill


# ==========================================================================
# #757 — honest timeout labeling: a tree-killed task must never masquerade as
# a mystery "no SUMMARY line" (the night-2 diagnosability defect: B4+B6 burned
# a full diagnostic cycle because the budget kill wore the parser's clothes).
# ==========================================================================


def test_run_to_logfile_tree_nonzero_exit_is_not_timed_out(tmp_path):
    # A normal failure (rc != 0) must NOT be labeled a timeout — the honest-timeout
    # rewrite keys off this flag, so a false positive here would mislabel real failures.
    ok, timed_out = so._run_to_logfile_tree(
        ["x"], log_path=tmp_path / "l.log", timeout_s=5.0,
        popen=lambda *a, **k: _FakeProc(rc=1), terminate_tree=lambda p: None,
    )
    assert ok is False and timed_out is False


def test_real_run_task_timeout_yields_honest_timeout_outcome(tmp_path, monkeypatch):
    # The night-2 miss, reproduced: run-fleet is tree-killed before it writes a SUMMARY
    # line for the task. The outcome must SAY timeout — not "no SUMMARY line".
    monkeypatch.setattr(so, "_run_to_logfile_tree",
                        lambda *a, **k: (False, True))
    cfg = so.build_default_config(str(tmp_path / "agentic"), str(tmp_path / "projects"))
    (cfg.runs_dir / "RID").mkdir(parents=True, exist_ok=True)
    # SUMMARY.txt exists but carries only the PREVIOUS task (run-fleet overwrites per
    # task and died before writing this one) — exactly the B4/B6 shape.
    (cfg.runs_dir / "RID" / "SUMMARY.txt").write_text(
        "- earlier-task: processed\n  RESULT: MERGED into your project\n", encoding="utf-8")
    oc = so.real_run_task(cfg, "RID", {"repo": "X", "task": "acceptance-tests", "prompt": "p"})
    assert oc.task == "acceptance-tests"
    assert oc.result == "TIMEOUT" and oc.outcome == "timeout"
    assert "TIMED OUT" in oc.detail and "per-task ceiling" in oc.detail
    assert "no SUMMARY line" not in oc.detail


def test_real_run_task_parsed_summary_wins_over_timeout(tmp_path, monkeypatch):
    # If run-fleet DID write the task's SUMMARY line before the kill landed, the parsed
    # outcome is the truth — the timeout flag must not overwrite a real result.
    monkeypatch.setattr(so, "_run_to_logfile_tree",
                        lambda *a, **k: (False, True))
    cfg = so.build_default_config(str(tmp_path / "agentic"), str(tmp_path / "projects"))
    (cfg.runs_dir / "RID").mkdir(parents=True, exist_ok=True)
    (cfg.runs_dir / "RID" / "SUMMARY.txt").write_text(
        "- t: processed\n  RESULT: MERGED into your project\n", encoding="utf-8")
    oc = so.real_run_task(cfg, "RID", {"repo": "X", "task": "t", "prompt": "p"})
    assert oc.result == "MERGED"


def test_real_run_task_no_summary_without_timeout_keeps_unknown(tmp_path, monkeypatch):
    # The legacy fallback survives unchanged for the genuinely-unexplained miss (run-fleet
    # exited on its own without writing the line): still UNKNOWN / "no SUMMARY line".
    monkeypatch.setattr(so, "_run_to_logfile_tree",
                        lambda *a, **k: (False, False))
    cfg = so.build_default_config(str(tmp_path / "agentic"), str(tmp_path / "projects"))
    (cfg.runs_dir / "RID").mkdir(parents=True, exist_ok=True)
    oc = so.real_run_task(cfg, "RID", {"repo": "X", "task": "t", "prompt": "p"})
    assert oc.result == "UNKNOWN" and "no SUMMARY line" in oc.detail


def test_build_swap_ops_budget_kill_is_labeled_timeout(tmp_path, monkeypatch):
    # The B4/B6 killer: the overall-run budget watchdog tree-kills run-fleet mid-task.
    # real_run_task sees no SUMMARY line; the ops wrapper must rewrite the mystery into
    # an explicit budget timeout WHEN the stop event says the budget fired.
    import threading

    from shared.fleet.dispatch import TaskOutcome

    monkeypatch.setattr(so, "real_run_task",
                        lambda *a, **k: TaskOutcome(
                            task="acceptance-tests", outcome="unknown", result="UNKNOWN",
                            detail="no SUMMARY line for this task"))
    cfg = _cfg(tmp_path)
    stop = threading.Event()
    ops = so.build_swap_ops(cfg, run_id="R", old_pid=1, relaunch_argv=["py"],
                            relaunch_cwd="C:/x", stop_event=stop)
    # Budget NOT fired -> the unknown passes through untouched (no false timeouts).
    oc = ops.run_task({"repo": "X", "task": "acceptance-tests", "prompt": "p"})
    assert oc.result == "UNKNOWN"
    # Budget fired -> honest, explicit label naming the budget.
    stop.set()
    oc = ops.run_task({"repo": "X", "task": "acceptance-tests", "prompt": "p"})
    assert oc.result == "TIMEOUT" and oc.outcome == "timeout"
    assert "overall run budget" in oc.detail and "TIMED OUT" in oc.detail


def test_build_swap_ops_budget_fire_never_rewrites_a_real_outcome(tmp_path, monkeypatch):
    # A task that finished (SUMMARY parsed) just before the budget fired keeps its real
    # outcome — the rewrite only claims the no-SUMMARY mystery, never actual results.
    import threading

    from shared.fleet.dispatch import TaskOutcome

    monkeypatch.setattr(so, "real_run_task",
                        lambda *a, **k: TaskOutcome(
                            task="t", outcome="processed", result="MERGED",
                            detail="RESULT: MERGED into your project"))
    cfg = _cfg(tmp_path)
    stop = threading.Event()
    stop.set()
    ops = so.build_swap_ops(cfg, run_id="R", old_pid=1, relaunch_argv=["py"],
                            relaunch_cwd="C:/x", stop_event=stop)
    oc = ops.run_task({"repo": "X", "task": "t", "prompt": "p"})
    assert oc.result == "MERGED"


def test_timeout_outcome_roundtrips_through_cumulative_summary(tmp_path):
    # #686 lock, extended to the new vocab: the cumulative SUMMARY.txt written for a
    # TIMEOUT outcome must read back as TIMEOUT through the ONE shared parse_summary
    # (harness + gateway /dispatch status) — a detail shape that drops the RESULT: prefix
    # would silently classify it as NONE at swap-back (the #686 failure class).
    from shared.fleet.dispatch import TaskOutcome, parse_summary

    cfg = _cfg(tmp_path)
    outs = [
        TaskOutcome(task="built", outcome="processed", result="MERGED",
                    detail="RESULT: MERGED into your project"),
        TaskOutcome(task="acceptance-tests", outcome="timeout", result="TIMEOUT",
                    detail="RESULT: TIMED OUT - the overall run budget elapsed mid-task; "
                           "run-fleet was tree-killed before it wrote a SUMMARY line"),
    ]
    so.write_cumulative_report(cfg, "RID", outs)
    text = (cfg.runs_dir / "RID" / "SUMMARY.txt").read_text(encoding="utf-8")
    parsed = parse_summary(text)
    assert [(o.task, o.result) for o in parsed] == [
        ("built", "MERGED"), ("acceptance-tests", "TIMEOUT")]
    assert parsed[1].outcome == "timeout"


def test_per_task_ceiling_dominates_runfleet_worst_case():
    # #757 headroom lock: run-fleet's legitimate single-task worst case is up to 3
    # candidates x MaxRunMinutes=60 + reviews/merge overhead. The night-2 ceiling (3600s)
    # EQUALLED one candidate's budget — zero headroom; the ceiling must dominate the
    # worst case so it never clips honest work (the budget watchdog is the binding bound).
    assert so.TASK_TIMEOUT_S >= 3 * 3600 + 1800


# ---- #693: real_run_critic threads the pre-dispatch base SHA to the script ----


def test_real_run_critic_passes_base_ref_only_when_given(tmp_path, monkeypatch):
    # Non-empty base_sha -> "-BaseRef <sha>" on the critic-run.ps1 command line (the
    # multi-commit fast-forward fix); empty -> omitted so the script's Resolve-CriticRange
    # fallback chain applies unchanged (pre-#693 behavior preserved).
    seen = {}
    monkeypatch.setattr(so, "real_load_14b", lambda c, r: True)
    monkeypatch.setattr(so, "real_wait_ready", lambda: True)

    def fake_run(cmd, *, log_path, timeout_s, **kw):
        seen["cmd"] = list(cmd)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_text("VERDICT: MERGE", encoding="utf-8")
        return True, 0          # #1076: (ok, byte offset of THIS lap's output)

    monkeypatch.setattr(so, "_run_to_logfile_at", fake_run)
    cfg = _cfg(tmp_path)

    so.real_run_critic(cfg, "RID", "C:/app", "main", "sha-base")
    i = seen["cmd"].index("-BaseRef")
    assert seen["cmd"][i + 1] == "sha-base"

    so.real_run_critic(cfg, "RID", "C:/app", "main", "")
    assert "-BaseRef" not in seen["cmd"]

    so.real_run_critic(cfg, "RID", "C:/app", "main")     # back-compat default
    assert "-BaseRef" not in seen["cmd"]


# ---- _CurrentChild: reuse-safe abort + structurally-inert at teardown ------


def test_current_child_abort_kills_registered(monkeypatch):
    killed = []
    monkeypatch.setattr("shared.fleet.proc_tree.terminate_process_tree",
                        lambda proc, *, child_create_time=None: killed.append(proc))
    cc = so._CurrentChild()
    proc = _FakeProc()
    cc.register(proc)
    cc.abort()
    assert killed == [proc]


def test_current_child_abort_noop_when_none(monkeypatch):
    killed = []
    monkeypatch.setattr("shared.fleet.proc_tree.terminate_process_tree",
                        lambda *a, **k: killed.append(1))
    cc = so._CurrentChild()
    cc.abort()                      # nothing registered
    cc.register(None)
    cc.abort()
    assert killed == []             # no current child -> never kills (can't hit a wrong process)


def test_current_child_begin_teardown_makes_abort_inert(monkeypatch):
    killed = []
    monkeypatch.setattr("shared.fleet.proc_tree.terminate_process_tree",
                        lambda *a, **k: killed.append(1))
    cc = so._CurrentChild()
    cc.register(_FakeProc())
    cc.begin_teardown()             # teardown owns the box now
    cc.abort()                      # a LATE budget fire
    assert killed == []             # structurally inert -> cannot act during the restore (oblig. A)


def test_current_child_tearing_down_guard_beats_a_late_register(monkeypatch):
    # Isolates the _tearing_down GUARD (defense-in-depth): even if a child is registered AFTER
    # teardown began (a race the single-threaded loop normally prevents), abort stays inert —
    # the None-clear alone would NOT catch this; the _tearing_down flag does (obligation A).
    killed = []
    monkeypatch.setattr("shared.fleet.proc_tree.terminate_process_tree",
                        lambda *a, **k: killed.append(1))
    cc = so._CurrentChild()
    cc.begin_teardown()             # teardown owns the box
    cc.register(_FakeProc())        # a LATE register sets _proc again...
    cc.abort()                      # ...but abort bails on _tearing_down regardless
    assert killed == []


def test_current_child_abort_noop_when_exited(monkeypatch):
    killed = []
    monkeypatch.setattr("shared.fleet.proc_tree.terminate_process_tree",
                        lambda *a, **k: killed.append(1))
    cc = so._CurrentChild()
    proc = _FakeProc()
    proc.killed = True              # poll() returns rc (already exited)
    cc.register(proc)
    cc.abort()
    assert killed == []             # already exited -> nothing to kill


# ---- worktree sweep: provenance-aware, force-free, never deletes a branch ---


def test_git_sweep_removes_run_worktrees_never_branch(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    repo = (tmp_path / "projects" / "myapp")
    wt_a = (repo.parent / "myapp-a").resolve()
    wt_b = (repo.parent / "myapp-b").resolve()
    cmds = []

    def fake_safe_run(cmd, timeout_s):
        cmds.append(list(cmd))
        if "list" in cmd:
            out = (f"worktree {repo.resolve()}\nbranch refs/heads/main\n\n"
                   f"worktree {wt_a}\nbranch refs/heads/agent/a\n\n"
                   f"worktree {wt_b}\nbranch refs/heads/agent/b\n")
            return (True, out, "")
        return (True, "", "")

    monkeypatch.setattr(so, "_safe_run", fake_safe_run)
    so._git_sweep_worktrees(cfg, [{"repo": str(repo), "task": "a", "prompt": "p"},
                                  {"repo": str(repo), "task": "b", "prompt": "p"}])
    flat = [" ".join(map(str, c)) for c in cmds]
    assert any("worktree remove" in f and "myapp-a" in f for f in flat)
    assert any("worktree remove" in f and "myapp-b" in f for f in flat)
    assert all("--force" not in f for f in flat)                     # never force (no data loss)
    assert any("worktree prune" in f for f in flat)
    assert not any("branch -d" in f or "branch -D" in f for f in flat)   # BRANCH NEVER deleted


def test_git_sweep_skips_same_named_different_branch(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    repo = (tmp_path / "projects" / "myapp")
    wt_a = (repo.parent / "myapp-a").resolve()
    cmds = []

    def fake_safe_run(cmd, timeout_s):
        cmds.append(list(cmd))
        if "list" in cmd:
            # myapp-a is registered but on a DIFFERENT branch (operator's / a concurrent run).
            return (True, f"worktree {repo.resolve()}\nbranch refs/heads/main\n\n"
                          f"worktree {wt_a}\nbranch refs/heads/feature/other\n", "")
        return (True, "", "")

    monkeypatch.setattr(so, "_safe_run", fake_safe_run)
    so._git_sweep_worktrees(cfg, [{"repo": str(repo), "task": "a", "prompt": "p"}])
    flat = [" ".join(map(str, c)) for c in cmds]
    assert not any("worktree remove" in f for f in flat)   # provenance: different branch -> skip
    assert any("worktree prune" in f for f in flat)        # prune still runs (safe)


def test_git_sweep_skips_unregistered(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    repo = (tmp_path / "projects" / "myapp")
    cmds = []

    def fake_safe_run(cmd, timeout_s):
        cmds.append(list(cmd))
        if "list" in cmd:
            return (True, f"worktree {repo.resolve()}\nbranch refs/heads/main\n", "")  # only main
        return (True, "", "")

    monkeypatch.setattr(so, "_safe_run", fake_safe_run)
    so._git_sweep_worktrees(cfg, [{"repo": str(repo), "task": "a", "prompt": "p"}])
    flat = [" ".join(map(str, c)) for c in cmds]
    assert not any("worktree remove" in f for f in flat)   # not registered -> nothing removed


def test_build_swap_ops_wires_worktree_sweep_and_verify(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    seen = {}
    monkeypatch.setattr(so, "_git_sweep_worktrees", lambda c, t: seen.update(cfg=c, tasks=t))
    tasks = [{"repo": "X", "task": "a", "prompt": "p"}]
    ops = so.build_swap_ops(cfg, run_id="R", old_pid=1, relaunch_argv=["py"],
                            relaunch_cwd="C:/x", tasks=tasks)
    ops.sweep_worktrees()
    assert seen["tasks"] == tasks and seen["cfg"] is cfg
    assert ops.ovms_alive is so.real_ovms_alive          # verify-stop probe wired


# ---- config coercion + the ovms verify probe ------------------------------


def test_coerce_budget_clamps():
    assert so._coerce_budget(5400.0) == 5400.0
    assert so._coerce_budget("90") == 90.0
    assert so._coerce_budget(0) == 0.0
    assert so._coerce_budget(-5) == 0.0          # negative disables (never instant-timeout)
    assert so._coerce_budget("off") == 0.0       # non-numeric disables (never crash)
    assert so._coerce_budget(None) == 0.0


def test_real_ovms_alive_never_raises(monkeypatch):
    import psutil

    monkeypatch.setattr(psutil, "process_iter",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    monkeypatch.setattr(so.subprocess, "run",
                        lambda *a, **k: (_ for _ in ()).throw(OSError("nope")))
    assert so.real_ovms_alive() is False         # both probes fail -> False, never raises


def test_run_swap_builds_fresh_per_run_instances(tmp_path, monkeypatch):
    # Each run_swap builds a FRESH _CurrentChild + stop_event (never module globals / a
    # filesystem sentinel), so a prior run's budget-timeout can't poison the next (#670 P2).
    import shared.fleet.swap_driver as sd_mod

    created = []
    orig_cc = so._CurrentChild

    def track_cc():
        inst = orig_cc()
        created.append(inst)
        return inst

    monkeypatch.setattr(so, "_CurrentChild", track_cc)
    monkeypatch.setattr(sd_mod.SwapDriver, "run", lambda self: None)
    cfg = _cfg(tmp_path)
    ss.write_swap_state(
        ss.SwapState(run_id="R1", session_id="s", phase=ss.PHASE_HANDOFF, tasks=[]),
        path=so.swap_state_path(cfg),
    )
    spec = {"run_id": "R1", "session_id": "s", "old_pid": 1, "relaunch_argv": ["py"],
            "relaunch_cwd": "C:/x", "gate_gb": 21.0, "run_budget_s": 0.0,
            "scripts_dir": str(cfg.scripts_dir), "queue_path": str(cfg.queue_path),
            "runs_dir": str(cfg.runs_dir), "projects_dir": str(cfg.projects_dir)}
    spec_path = so.swap_dir(cfg) / "spec.json"
    spec_path.write_text(json.dumps(spec), encoding="utf-8")
    so.run_swap(spec_path)
    so.run_swap(spec_path)
    assert len(created) == 2 and created[0] is not created[1]   # fresh per run


def test_run_swap_stamps_driver_pid_into_state(tmp_path, monkeypatch):
    # #758: the driver records its OWN pid + create-time into the swap state at takeover,
    # so a concurrent AO boot's reconcile can tell a LIVE swap from a CRASHED one instead
    # of killing the healthy run (the 2026-07-07 incident).
    import os

    import shared.fleet.swap_driver as sd_mod

    monkeypatch.setattr(sd_mod.SwapDriver, "run", lambda self: None)
    cfg = _cfg(tmp_path)
    ss.write_swap_state(
        ss.SwapState(run_id="R1", session_id="s", phase=ss.PHASE_HANDOFF, tasks=[]),
        path=so.swap_state_path(cfg),
    )
    spec = {"run_id": "R1", "session_id": "s", "old_pid": 1, "relaunch_argv": ["py"],
            "relaunch_cwd": "C:/x", "gate_gb": 21.0, "run_budget_s": 0.0,
            "scripts_dir": str(cfg.scripts_dir), "queue_path": str(cfg.queue_path),
            "runs_dir": str(cfg.runs_dir), "projects_dir": str(cfg.projects_dir)}
    spec_path = so.swap_dir(cfg) / "spec.json"
    spec_path.write_text(json.dumps(spec), encoding="utf-8")
    so.run_swap(spec_path)
    state = ss.read_swap_state(so.swap_state_path(cfg))
    assert state.driver_pid == os.getpid()          # THIS process was the driver
    assert state.driver_pid_created > 0.0           # psutil create-time recorded
    assert state.driver_image != ""                 # #902: image stamp recorded too
    assert ss.driver_alive(state) is True           # and the real probe agrees it is live


def test_run_swap_wires_watchdog_when_budget_positive(tmp_path, monkeypatch):
    # The budget>0 seam (run_swap) is the load-bearing A/B production assembly: it builds a
    # BudgetWatchdog whose abort is THIS run's _CurrentChild.abort and whose request_stop is THIS
    # run's stop_event.set — the SAME stop_event handed to build_swap_ops (-> stop_requested). Every
    # other run_swap test passes budget=0 (the watchdog=None branch), so this locks the wiring.
    import shared.fleet.swap_driver as sd_mod

    captured, seen = {}, {}

    class _SpyWatchdog:
        def __init__(self, *, budget_s, abort, request_stop):
            captured.update(budget_s=budget_s, abort=abort, request_stop=request_stop)

    real_build = so.build_swap_ops

    def spy_build(*a, **k):
        seen["current_child"] = k.get("current_child")
        seen["stop_event"] = k.get("stop_event")
        return real_build(*a, **k)

    monkeypatch.setattr(sd_mod, "BudgetWatchdog", _SpyWatchdog)
    monkeypatch.setattr(sd_mod.SwapDriver, "run", lambda self: None)
    monkeypatch.setattr(so, "build_swap_ops", spy_build)

    cfg = _cfg(tmp_path)
    ss.write_swap_state(
        ss.SwapState(run_id="R1", session_id="s", phase=ss.PHASE_HANDOFF, tasks=[]),
        path=so.swap_state_path(cfg),
    )
    spec = {"run_id": "R1", "session_id": "s", "old_pid": 1, "relaunch_argv": ["py"],
            "relaunch_cwd": "C:/x", "gate_gb": 21.0, "run_budget_s": 5400.0,
            "scripts_dir": str(cfg.scripts_dir), "queue_path": str(cfg.queue_path),
            "runs_dir": str(cfg.runs_dir), "projects_dir": str(cfg.projects_dir)}
    spec_path = so.swap_dir(cfg) / "spec.json"
    spec_path.write_text(json.dumps(spec), encoding="utf-8")
    so.run_swap(spec_path)

    assert captured.get("budget_s") == 5400.0                       # (a) watchdog built (budget>0 arm)
    assert captured["abort"].__self__ is seen["current_child"]      # (b) abort -> the per-run holder
    assert captured["request_stop"].__self__ is seen["stop_event"]  # (b) request_stop -> per-run event


def test_run_swap_no_watchdog_when_budget_zero(tmp_path, monkeypatch):
    # The disable arm: budget<=0 -> SwapDriver gets budget_watchdog=None (no daemon ever spawned).
    import shared.fleet.swap_driver as sd_mod

    seen = {}
    real_init = sd_mod.SwapDriver.__init__

    def spy_init(self, *a, budget_watchdog=None, **k):
        seen["watchdog"] = budget_watchdog
        real_init(self, *a, budget_watchdog=budget_watchdog, **k)

    monkeypatch.setattr(sd_mod.SwapDriver, "__init__", spy_init)
    monkeypatch.setattr(sd_mod.SwapDriver, "run", lambda self: None)
    cfg = _cfg(tmp_path)
    ss.write_swap_state(
        ss.SwapState(run_id="R1", session_id="s", phase=ss.PHASE_HANDOFF, tasks=[]),
        path=so.swap_state_path(cfg),
    )
    spec = {"run_id": "R1", "session_id": "s", "old_pid": 1, "relaunch_argv": ["py"],
            "relaunch_cwd": "C:/x", "gate_gb": 21.0, "run_budget_s": 0.0,
            "scripts_dir": str(cfg.scripts_dir), "queue_path": str(cfg.queue_path),
            "runs_dir": str(cfg.runs_dir), "projects_dir": str(cfg.projects_dir)}
    spec_path = so.swap_dir(cfg) / "spec.json"
    spec_path.write_text(json.dumps(spec), encoding="utf-8")
    so.run_swap(spec_path)
    assert seen["watchdog"] is None                                 # no watchdog on the disable arm


# ==========================================================================
# #688 Phase 3 — real_run_design_loop (capture+critique via critique-loop.ps1) + wiring
# ==========================================================================


def test_real_run_design_loop_parses_and_maps_json(tmp_path, monkeypatch):
    # The pwsh output (a ConvertTo-Json hashtable) is read back from the LOGFILE (no capture pipe)
    # and mapped onto the driver's snake_case dict. A leading noise line is tolerated.
    cfg = so.build_default_config(str(tmp_path / "agentic"), str(tmp_path / "projects"))
    seen = {}

    def fake_logfile(cmd, *, log_path, timeout_s, **_kw):
        seen.update(cmd=cmd, log_path=log_path, timeout_s=timeout_s)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_text(
            "capture: web tier rendered\n"
            '{"ShouldIterate":true,"NeedsWork":true,"Feedback":"tighten the hero",'
            '"LayoutHard":false,"CaptureTier":"web","Ok":true,'
            '"RuntimeHard":true,"RuntimeCaptured":true}\n',
            encoding="utf-8")
        return True, 0          # #1076: (ok, byte offset of THIS lap's output)

    monkeypatch.setattr(so, "_run_to_logfile_at", fake_logfile)
    out = so.real_run_design_loop(cfg, "RID-9", "C:/proj/app", "a landing page", '["hero"]')
    # #823: the browser-runtime channel round-trips through the coercion (a captured hard hit).
    assert out == {"should_iterate": True, "needs_work": True, "feedback": "tighten the hero",
                   "layout_hard": False, "capture_tier": "web", "ok": True,
                   "runtime_hard": True, "runtime_captured": True}
    # logfile lands under the per-run dir; the bounded subprocess uses the ~180s design timeout.
    assert seen["log_path"] == cfg.runs_dir / "RID-9" / "design-critique.log"
    assert seen["timeout_s"] == 180.0
    joined = " ".join(seen["cmd"])
    assert "critique-loop.ps1" in joined                 # dot-sourced to bind the param block
    assert "Invoke-CritiquePass" in joined and "ConvertTo-Json" in joined
    assert "a landing page" in joined and '["hero"]' in joined   # the args ride into the command


def test_real_run_design_loop_single_quote_escaped(tmp_path, monkeypatch):
    # A free-text goal with a single quote is DOUBLED for PowerShell (correctness + the obvious
    # injection seam closed) — the raw, unescaped form never reaches the command.
    cfg = so.build_default_config(str(tmp_path / "agentic"), str(tmp_path / "projects"))
    seen = {}

    def fake_logfile(cmd, *, log_path, timeout_s, **_kw):
        seen["cmd"] = cmd
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_text("{}", encoding="utf-8")
        return True, 0          # #1076: (ok, byte offset of THIS lap's output)

    monkeypatch.setattr(so, "_run_to_logfile_at", fake_logfile)
    so.real_run_design_loop(cfg, "R", "C:/proj/app", "Tony's bakery", "[]")
    joined = " ".join(seen["cmd"])
    assert "-Goal 'Tony''s bakery'" in joined            # the quote is doubled inside the arg
    assert "Tony's bakery" not in joined                 # the raw single-quote form never leaks


def test_real_run_design_loop_fail_soft_on_nonzero_exit(tmp_path, monkeypatch):
    cfg = so.build_default_config(str(tmp_path / "agentic"), str(tmp_path / "projects"))
    monkeypatch.setattr(so, "_run_to_logfile_at",
                        lambda *a, **k: (False, 0))   # non-zero exit / timeout
    out = so.real_run_design_loop(cfg, "R", "C:/proj/app", "g", "[]")
    # ok=False (#740 c.1717): an unavailable critique must never read as a real,
    # satisfied review — the driver's clean-ending verdict reclass keys on ok.
    # #823: a fail-soft path is also runtime-blind — both runtime flags False (honest degraded).
    assert out == {"should_iterate": False, "needs_work": False,
                   "feedback": "design critique unavailable", "layout_hard": False,
                   "capture_tier": "", "ok": False,
                   "runtime_hard": False, "runtime_captured": False}


def test_real_run_design_loop_fail_soft_on_unparseable(tmp_path, monkeypatch):
    cfg = so.build_default_config(str(tmp_path / "agentic"), str(tmp_path / "projects"))

    def fake_logfile(cmd, *, log_path, timeout_s, **_kw):
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_text("no json on any line here\n", encoding="utf-8")
        return True, 0          # #1076: (ok, byte offset of THIS lap's output)

    monkeypatch.setattr(so, "_run_to_logfile_at", fake_logfile)
    out = so.real_run_design_loop(cfg, "R", "C:/proj/app", "g", "[]")
    assert out["feedback"] == "design critique unavailable"   # unparseable -> fail-soft default
    assert out["should_iterate"] is False


def test_coerce_design_loop_result_tolerates_snake_case_and_missing():
    # A missing Ok/ok key defaults to False (#740 c.1717 fail-conservative): a
    # producer that never claims a real review can never trigger the clean reclass.
    # #823: missing RuntimeHard/RuntimeCaptured also default False — a legacy producer
    # that never emits the runtime channel reads as console-blind (no runtime verdict).
    out = so._coerce_design_loop_result({"should_iterate": 1, "feedback": "x"})
    assert out == {"should_iterate": True, "needs_work": False, "feedback": "x",
                   "layout_hard": False, "capture_tier": "", "ok": False,
                   "runtime_hard": False, "runtime_captured": False}


def test_coerce_design_loop_result_maps_runtime_channel_pascalcase():
    # #823: the PowerShell PascalCase RuntimeHard/RuntimeCaptured map onto the driver's
    # snake_case runtime signal; both coerce via bool.
    out = so._coerce_design_loop_result(
        {"ShouldIterate": False, "Ok": True, "Feedback": "Uncaught exception: sum is not defined",
         "RuntimeHard": True, "RuntimeCaptured": True})
    assert out["runtime_hard"] is True and out["runtime_captured"] is True
    assert out["ok"] is True and out["should_iterate"] is False


def test_parse_design_loop_json_takes_last_object_with_key():
    # Reverse-scan: the compact ConvertTo-Json line is the LAST recognized object; junk braces
    # without a critique key are ignored.
    text = '{"unrelated": 1}\nnoise\n{"ShouldIterate": false, "Feedback": "done-ish"}\n'
    assert so._parse_design_loop_json(text) == {"ShouldIterate": False, "Feedback": "done-ish"}
    assert so._parse_design_loop_json("no objects here") is None


def test_build_swap_ops_wires_run_design_loop(tmp_path, monkeypatch):
    # build_swap_ops threads config + run_id into real_run_design_loop, exposing the driver's
    # 3-arg run_design_loop(app_dir, goal, visual_criteria_json) seam.
    cfg = _cfg(tmp_path)
    seen = {}

    def fake_real(config, run_id, app_dir, goal, vcj):
        seen.update(config=config, run_id=run_id, app_dir=app_dir, goal=goal, vcj=vcj)
        return {"should_iterate": False}

    monkeypatch.setattr(so, "real_run_design_loop", fake_real)
    ops = so.build_swap_ops(cfg, run_id="RID", old_pid=1, relaunch_argv=["py"], relaunch_cwd="C:/x")
    result = ops.run_design_loop("C:/proj/app", "a landing page", '["hero"]')
    assert seen == {"config": cfg, "run_id": "RID", "app_dir": "C:/proj/app",
                    "goal": "a landing page", "vcj": '["hero"]'}
    assert result == {"should_iterate": False}


def test_build_swap_ops_wires_job_oracle_contract_from_riding_oracle(tmp_path):
    """#790 rec-1: build_swap_ops must extract the oracle's first-party import contract
    from the SAME oracle code riding the approved task dicts — the exact module surface
    the wave-final oracle imports, so the driver can surface it to the coder."""
    from shared.fleet.acceptance import JOB_ORACLE_CODE_KEY, JOB_ORACLE_PATH_KEY

    cfg = _cfg(tmp_path)
    oracle_code = (
        "import pytest\n"
        "from cli import main\n"
        "def test_smoke():\n"
        "    assert main is not None\n"
    )
    tasks = [
        {"repo": "battery-x", "task": "a", "prompt": "pa", "depends_on": []},
        {"repo": "battery-x", "task": "acceptance-tests", "prompt": "grade",
         "depends_on": ["a"],
         JOB_ORACLE_CODE_KEY: oracle_code,
         JOB_ORACLE_PATH_KEY: "tests/test_job_acceptance.py"},
    ]
    ops = so.build_swap_ops(cfg, run_id="RID", old_pid=1, relaunch_argv=["py"],
                            relaunch_cwd="C:/x", tasks=tasks)
    contract = ops.job_oracle_contract()
    assert "from cli import main" in contract
    assert not any("pytest" in c for c in contract)   # the test framework is dropped


def test_build_swap_ops_job_oracle_contract_empty_without_oracle(tmp_path):
    """No oracle rides the tasks ⇒ an empty contract (byte-identical to before #790)."""
    cfg = _cfg(tmp_path)
    ops = so.build_swap_ops(cfg, run_id="RID", old_pid=1, relaunch_argv=["py"],
                            relaunch_cwd="C:/x",
                            tasks=[{"repo": "battery-x", "task": "a", "prompt": "p"}])
    assert ops.job_oracle_contract() == []


# ---------------------------------------------------------------------------
# #750 fix 1 — real_backend_ready readiness hardening (stability + launcher-alive)
# ---------------------------------------------------------------------------


def _scripted_connect(results):
    """A ``_try_connect`` stand-in yielding successive bools from *results* (last repeats)."""
    seq = list(results)
    state = {"i": 0}

    def _c(port, timeout_s=2.0):
        i = state["i"]
        state["i"] = i + 1
        return seq[i] if i < len(seq) else seq[-1]

    return _c


def test_backend_ready_verifies_a_stably_up_ao(monkeypatch):
    monkeypatch.setattr(so, "_try_connect", _scripted_connect([True]))   # always accepts
    seen = []
    ok = so.real_backend_ready(5001, sleep=lambda _s: None, stable_polls=3,
                               launcher_alive=lambda: True, observe=seen.append)
    assert ok is True
    assert any(e["event"] == "verified-ready" for e in seen)


def test_backend_ready_rejects_bind_then_die(monkeypatch):
    # The night-1 false-positive: one accept, then the listener is gone. A single connect
    # must NOT be trusted -- the stability re-poll catches it.
    monkeypatch.setattr(so, "_try_connect", _scripted_connect([True, False]))
    seen = []
    ok = so.real_backend_ready(5001, timeout_s=6.0, poll_s=3.0, sleep=lambda _s: None,
                               stable_polls=3, stable_gap_s=2.0,
                               launcher_alive=lambda: True, observe=seen.append)
    assert ok is False                                   # not fooled by a single accept
    assert any(e["event"] == "unstable" for e in seen)


def test_backend_ready_aborts_fast_when_launcher_died(monkeypatch):
    # A lingering socket may still accept, but if the spawned launcher PROCESS is gone the
    # readiness aborts immediately -> the driver spawns fresh instead of trusting it.
    monkeypatch.setattr(so, "_try_connect", _scripted_connect([True]))
    sleeps = {"n": 0}
    seen = []
    ok = so.real_backend_ready(
        5001, timeout_s=180.0,
        sleep=lambda _s: sleeps.__setitem__("n", sleeps["n"] + 1),
        launcher_alive=lambda: False, observe=seen.append)
    assert ok is False
    assert sleeps["n"] == 0                              # returned at once, no 180s poll
    assert any(e["event"] == "launcher-died" for e in seen)


def test_backend_ready_catches_launcher_dying_mid_stability(monkeypatch):
    monkeypatch.setattr(so, "_try_connect", _scripted_connect([True]))   # socket stays up
    alive = iter([True, False])   # alive at the first accept, dead during the stability re-poll
    ok = so.real_backend_ready(5001, timeout_s=6.0, sleep=lambda _s: None,
                               stable_polls=3, launcher_alive=lambda: next(alive, False))
    assert ok is False


def test_backend_ready_times_out_when_never_up(monkeypatch):
    monkeypatch.setattr(so, "_try_connect", _scripted_connect([False]))
    seen = []
    ok = so.real_backend_ready(5001, timeout_s=6.0, poll_s=3.0, sleep=lambda _s: None,
                               launcher_alive=lambda: True, observe=seen.append)
    assert ok is False
    assert any(e["event"] == "timeout" for e in seen)


def test_build_swap_ops_wires_backend_ready_with_launcher_alive_and_observer(tmp_path, monkeypatch):
    # Fix 1 is only real if the guard is WIRED: build_swap_ops must call real_backend_ready with
    # the launcher-alive probe (relaunch_in_flight) AND an observer -> the swap-progress trail.
    cfg = _cfg(tmp_path)
    captured = {}

    def fake_real(port, launcher_alive=None, observe=None, **kw):
        captured.update(port=port, launcher_alive=launcher_alive, observe=observe)
        if observe:
            observe({"event": "verified-ready", "stable_polls": 3})
        return True

    monkeypatch.setattr(so, "real_backend_ready", fake_real)
    ops = so.build_swap_ops(cfg, run_id="RID", old_pid=1, relaunch_argv=["py"],
                            relaunch_cwd="C:/x", ao_port=5001)
    assert ops.backend_ready() is True
    assert captured["port"] == 5001
    assert callable(captured["launcher_alive"])       # relaunch_in_flight is wired in
    assert callable(captured["observe"])              # the progress-log observer is wired in
    trail = so.read_swap_progress(cfg, "RID")
    assert "backend-ready probe: verified-ready" in trail


# ==========================================================================
# #744 guest-certified oracle — spec threading + live wiring (DORMANT)
# ==========================================================================


def test_prepare_and_launch_swap_spec_carries_guest_oracle_knob(tmp_path):
    # The knob rides config -> spec exactly like plan_graph; the shipped default is
    # False (the legacy _cfg carries no explicit value -> dataclass default).
    cfg = _cfg(tmp_path)
    so.prepare_and_launch_swap(
        cfg, run_id="R1", session_id="s1",
        tasks=[{"repo": "X", "task": "a", "prompt": "p"}],
        old_pid=1, relaunch_argv=["py"], relaunch_cwd="C:/x",
        gate_gb=21.0, spawn=lambda p: None,
    )
    spec = json.loads((so.swap_dir(cfg) / "spec.json").read_text(encoding="utf-8"))
    assert spec["guest_oracle_enabled"] is False

    state = tmp_path / "state"
    cfg_on = FleetDispatchConfig(
        scripts_dir=tmp_path / "scripts", queue_path=state / "fleet-queue.json",
        runs_dir=state / "fleet-runs", projects_dir=tmp_path / "projects",
        guest_oracle_enabled=True,
    )
    so.prepare_and_launch_swap(
        cfg_on, run_id="R2", session_id="s1",
        tasks=[{"repo": "X", "task": "a", "prompt": "p"}],
        old_pid=1, relaunch_argv=["py"], relaunch_cwd="C:/x",
        gate_gb=21.0, spawn=lambda p: None,
    )
    spec = json.loads((so.swap_dir(cfg_on) / "spec.json").read_text(encoding="utf-8"))
    assert spec["guest_oracle_enabled"] is True


def test_run_swap_threads_guest_oracle_knob_to_driver(tmp_path, monkeypatch):
    # spec -> SwapDriver(guest_oracle_enabled=...) — and a PRE-#744 spec (no key at
    # all) resolves False, so crash-recovery re-reads of old specs stay legacy.
    import shared.fleet.swap_driver as sd_mod

    seen = {}
    real_init = sd_mod.SwapDriver.__init__

    def spy_init(self, *a, guest_oracle_enabled=False, **k):
        seen.setdefault("values", []).append(guest_oracle_enabled)
        real_init(self, *a, guest_oracle_enabled=guest_oracle_enabled, **k)

    monkeypatch.setattr(sd_mod.SwapDriver, "__init__", spy_init)
    monkeypatch.setattr(sd_mod.SwapDriver, "run", lambda self: None)
    cfg = _cfg(tmp_path)
    ss.write_swap_state(
        ss.SwapState(run_id="R1", session_id="s", phase=ss.PHASE_HANDOFF, tasks=[]),
        path=so.swap_state_path(cfg),
    )
    base = {"run_id": "R1", "session_id": "s", "old_pid": 1, "relaunch_argv": ["py"],
            "relaunch_cwd": "C:/x", "gate_gb": 21.0, "run_budget_s": 0.0,
            "scripts_dir": str(cfg.scripts_dir), "queue_path": str(cfg.queue_path),
            "runs_dir": str(cfg.runs_dir), "projects_dir": str(cfg.projects_dir)}
    spec_path = so.swap_dir(cfg) / "spec.json"
    spec_path.parent.mkdir(parents=True, exist_ok=True)

    spec_path.write_text(json.dumps(base), encoding="utf-8")          # pre-#744 spec
    so.run_swap(spec_path)
    spec_path.write_text(json.dumps({**base, "guest_oracle_enabled": True}),
                         encoding="utf-8")
    so.run_swap(spec_path)
    assert seen["values"] == [False, True]


def test_real_write_guest_oracle_persists_block_fail_soft(tmp_path):
    cfg = _cfg(tmp_path)
    block = {"schema": "guest-oracle/v1", "status": "not-run",
             "reason": "guest-transport-unregistered", "advisory": True}
    so.real_write_guest_oracle(cfg, "R1", block)
    on_disk = json.loads(
        so.guest_oracle_evidence_path(cfg, "R1").read_text(encoding="utf-8"))
    assert on_disk == block
    # Fail-soft: an unserializable block must never raise into teardown.
    so.real_write_guest_oracle(cfg, "R1", {"bad": object()})


def test_real_run_guest_oracle_uses_the_registered_transport(tmp_path, monkeypatch):
    # CONSCIOUSLY AMENDED at the 2026-07-08 go-live ceremony (#744): the former
    # transport-dormancy lock becomes the live-wiring lock. The call site must
    # BUILD the factory and pass its callable to the pipeline — proven here
    # with an injected factory (a TEST MUST NEVER live-call the corridor: the
    # first post-flip gate run reached the REAL guest from inside pytest,
    # today's gate-vs-live-fleet class one more time — hence the seam).
    import shared.fleet.guest_oracle_transport as got

    calls = {}

    def fake_factory(*, vsock_port):
        calls["port"] = vsock_port

        def transport(snapshot_zip, oracle_rel_path):
            calls["shipped"] = (len(snapshot_zip), oracle_rel_path)
            return {"status": "passed", "reason": "", "evidence": "exit 0 (fake guest)"}

        return transport

    monkeypatch.setattr(got, "make_guest_oracle_transport", fake_factory)
    cfg = _cfg(tmp_path)
    repo = tmp_path / "proj"
    (repo / "tests").mkdir(parents=True)
    (repo / "calc.py").write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")
    # #744 c.1565: inject the ensure-start/stop VM seam so the test NEVER touches the
    # real Hyper-V guest — the guest is DOWN, ensure-start brings it up, and it is
    # STOPPED again after the probe (LESSON 224 side-effect scoping). The c.1689
    # readiness wait is injected too (immediate success — no real probe, no sleep).
    calls["stopped"] = 0
    res = so.real_run_guest_oracle(
        cfg, "R1", str(repo), "tests/test_job_acceptance.py",
        "from calc import add\n\ndef test_a():\n    assert add(1, 1) == 2\n",
        guest_vm_running=lambda: False,
        ensure_guest_running=lambda: True,
        stop_guest=lambda: calls.__setitem__("stopped", calls["stopped"] + 1) or True,
        wait_for_service=lambda was_running: True)
    assert calls["port"] == so.GUEST_ORACLE_VSOCK_PORT == 50002
    assert calls["shipped"][1] == "tests/test_job_acceptance.py"
    assert res["status"] == "passed"
    assert calls["stopped"] == 1  # a guest we started is stopped again after the probe
    assert "passed" in so.read_swap_progress(cfg, "R1")


def test_real_run_guest_oracle_degrades_honestly_when_factory_fails(tmp_path, monkeypatch):
    # The fail-soft half of the registration: a factory failure (missing 3.14
    # bridge) degrades to transport=None — an honest not-run with the trail
    # line, NEVER a raise into the swap teardown.
    import shared.fleet.guest_oracle_transport as got

    def broken_factory(*, vsock_port):
        raise got.BridgeUnavailableError("no 3.12+ interpreter")

    monkeypatch.setattr(got, "make_guest_oracle_transport", broken_factory)
    cfg = _cfg(tmp_path)
    repo = tmp_path / "proj"
    (repo / "tests").mkdir(parents=True)
    (repo / "calc.py").write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")
    stopped = []
    res = so.real_run_guest_oracle(
        cfg, "R1", str(repo), "tests/test_job_acceptance.py",
        "from calc import add\n\ndef test_a():\n    assert add(1, 1) == 2\n",
        guest_vm_running=lambda: False,
        ensure_guest_running=lambda: True,
        stop_guest=lambda: stopped.append(1) or True,
        wait_for_service=lambda was_running: True)
    assert res["status"] == "not-run"
    assert res["reason"] == "guest-transport-unregistered"
    assert stopped == [1]  # the guest is still stopped after a transport-fail probe
    assert "transport unavailable" in so.read_swap_progress(cfg, "R1")


# ---------------------------------------------------------------------------
# #744 c.1565 — sequential ensure-start: bring the guest VM UP for the probe in
# the teardown RAM-free window, then restore its prior footprint. Fail-soft is
# INVARIANT (guest-unreachable => honest not-run, never a blocked restore, never
# a verdict change) and NO test touches the real Hyper-V VM (the ensure/stop/state
# seam is injected or launcher.vm_manager is monkeypatched).
# ---------------------------------------------------------------------------


def _ok_transport_factory(status="passed"):
    """A make_guest_oracle_transport double whose transport ships and returns
    ``status`` — no real corridor, no real guest."""
    def factory(*, vsock_port):
        def transport(snapshot_zip, oracle_rel_path):
            return {"status": status, "reason": "", "evidence": f"{status} (fake guest)"}
        return transport
    return factory


def _oracle_repo(tmp_path):
    repo = tmp_path / "proj"
    (repo / "tests").mkdir(parents=True)
    (repo / "calc.py").write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")
    return repo


def test_real_run_guest_oracle_ensure_starts_then_waits_then_probes_then_stops_in_order(
        tmp_path, monkeypatch):
    # The load-bearing sequence (#744 c.1689): ensure-start, THEN the service-
    # readiness wait, THEN the probe ships, STOP after — the wait sits exactly
    # between hypervisor-Running and the first frame on the wire.
    import shared.fleet.guest_oracle_transport as got

    events = []
    monkeypatch.setattr(got, "make_guest_oracle_transport", _ok_transport_factory())
    cfg = _cfg(tmp_path)
    repo = _oracle_repo(tmp_path)

    def ship_seam(*, vsock_port):
        def transport(snapshot_zip, oracle_rel_path):
            events.append("probe")
            return {"status": "passed", "reason": "", "evidence": "ok"}
        return transport

    monkeypatch.setattr(got, "make_guest_oracle_transport", ship_seam)
    res = so.real_run_guest_oracle(
        cfg, "R1", str(repo), "tests/test_job_acceptance.py",
        "from calc import add\n\ndef test_a():\n    assert add(1, 1) == 2\n",
        guest_vm_running=lambda: False,
        ensure_guest_running=lambda: events.append("ensure") or True,
        stop_guest=lambda: events.append("stop") or True,
        wait_for_service=lambda was_running: events.append("wait") or True)
    assert res["status"] == "passed"
    # ensure-start, readiness wait, probe ship, stop — in that order.
    assert events == ["ensure", "wait", "probe", "stop"]


def test_real_run_guest_oracle_guest_unreachable_when_ensure_start_fails(
        tmp_path, monkeypatch):
    # ensure-start FAILS -> honest not-run(guest-unreachable); the readiness wait
    # and the transport factory are NEVER invoked, the guest-stop is still
    # attempted, verdict untouched.
    import shared.fleet.guest_oracle_transport as got

    factory_calls = []
    wait_calls = []

    def spy_factory(*, vsock_port):
        factory_calls.append(vsock_port)
        raise AssertionError("transport must not be built when the guest is unreachable")

    monkeypatch.setattr(got, "make_guest_oracle_transport", spy_factory)
    cfg = _cfg(tmp_path)
    repo = _oracle_repo(tmp_path)
    stopped = []
    res = so.real_run_guest_oracle(
        cfg, "R1", str(repo), "tests/test_job_acceptance.py",
        "from calc import add\n\ndef test_a():\n    assert add(1, 1) == 2\n",
        guest_vm_running=lambda: False,
        ensure_guest_running=lambda: False,
        stop_guest=lambda: stopped.append(1) or True,
        wait_for_service=lambda was_running: wait_calls.append(was_running) or True)
    assert res == {"status": "not-run", "reason": "guest-unreachable",
                   "evidence": "the guest VM could not be started for the oracle probe"}
    assert factory_calls == []          # no probe when the guest never came up
    assert wait_calls == []             # no readiness wait on a guest that never started
    assert stopped == [1]               # stop still attempted (may have half-started)
    assert "could not be started" in so.read_swap_progress(cfg, "R1")


def test_real_run_guest_oracle_ensure_start_raise_is_guest_unreachable(
        tmp_path, monkeypatch):
    # An ensure-start that RAISES is treated identically to False — honest not-run,
    # never a raise into the swap teardown.
    import shared.fleet.guest_oracle_transport as got

    monkeypatch.setattr(got, "make_guest_oracle_transport", _ok_transport_factory())
    cfg = _cfg(tmp_path)
    repo = _oracle_repo(tmp_path)
    stopped = []
    wait_calls = []

    def boom():
        raise OSError("hyper-v RPC down")

    res = so.real_run_guest_oracle(
        cfg, "R1", str(repo), "tests/test_job_acceptance.py",
        "from calc import add\n\ndef test_a():\n    assert add(1, 1) == 2\n",
        guest_vm_running=lambda: False,
        ensure_guest_running=boom,
        stop_guest=lambda: stopped.append(1) or True,
        wait_for_service=lambda was_running: wait_calls.append(was_running) or True)
    assert res["status"] == "not-run" and res["reason"] == "guest-unreachable"
    assert wait_calls == []             # no readiness wait after a raising ensure-start
    assert stopped == [1]


def test_real_run_guest_oracle_probe_not_run_after_ensure_start_still_stops(
        tmp_path, monkeypatch):
    # probe machinery reports not-run (e.g. deps-unavailable) AFTER a good ensure-start
    # -> the honest not-run is passed through and the guest is STILL stopped.
    import shared.fleet.guest_oracle as go
    import shared.fleet.guest_oracle_transport as got

    monkeypatch.setattr(got, "make_guest_oracle_transport", _ok_transport_factory())
    monkeypatch.setattr(
        go, "run_guest_oracle",
        lambda repo, rel, code, transport=None: {
            "status": "not-run", "reason": "deps-unavailable", "evidence": "offline"})
    cfg = _cfg(tmp_path)
    repo = _oracle_repo(tmp_path)
    stopped = []
    res = so.real_run_guest_oracle(
        cfg, "R1", str(repo), "tests/test_job_acceptance.py", "x = 1\n",
        guest_vm_running=lambda: False,
        ensure_guest_running=lambda: True,
        stop_guest=lambda: stopped.append(1) or True,
        wait_for_service=lambda was_running: True)
    assert res["status"] == "not-run" and res["reason"] == "deps-unavailable"
    assert stopped == [1]


def test_real_run_guest_oracle_guest_failure_preserved_and_stops(tmp_path, monkeypatch):
    # A LEGITIMATE guest test FAILURE (status=failed — the divergence signal) is
    # PRESERVED, never swallowed to not-run, and the guest is stopped afterwards.
    import shared.fleet.guest_oracle_transport as got

    monkeypatch.setattr(got, "make_guest_oracle_transport", _ok_transport_factory("failed"))
    cfg = _cfg(tmp_path)
    repo = _oracle_repo(tmp_path)
    stopped = []
    res = so.real_run_guest_oracle(
        cfg, "R1", str(repo), "tests/test_job_acceptance.py",
        "from calc import add\n\ndef test_a():\n    assert add(1, 1) == 3\n",
        guest_vm_running=lambda: False,
        ensure_guest_running=lambda: True,
        stop_guest=lambda: stopped.append(1) or True,
        wait_for_service=lambda was_running: True)
    assert res["status"] == "failed"    # preserved, NOT converted to not-run
    assert stopped == [1]


def test_real_run_guest_oracle_already_running_guest_is_left_running(
        tmp_path, monkeypatch):
    # LESSON 224 side-effect scoping: a guest that was ALREADY running is left
    # running — only a guest WE started is stopped again. The readiness wait is
    # TOLD the guest was already up (was_running=True) so it uses the short
    # grace, never the full cold-boot budget.
    import shared.fleet.guest_oracle_transport as got

    monkeypatch.setattr(got, "make_guest_oracle_transport", _ok_transport_factory())
    cfg = _cfg(tmp_path)
    repo = _oracle_repo(tmp_path)
    stopped = []
    wait_calls = []
    res = so.real_run_guest_oracle(
        cfg, "R1", str(repo), "tests/test_job_acceptance.py",
        "from calc import add\n\ndef test_a():\n    assert add(1, 1) == 2\n",
        guest_vm_running=lambda: True,          # already up (some other path owns it)
        ensure_guest_running=lambda: True,
        stop_guest=lambda: stopped.append(1) or True,
        wait_for_service=lambda was_running: wait_calls.append(was_running) or True)
    assert res["status"] == "passed"
    assert stopped == []                        # never stop a guest we did not start
    assert wait_calls == [True]                 # the wait KNOWS the guest was already up


def test_real_run_guest_oracle_stop_failure_never_raises(tmp_path, monkeypatch):
    # A stop failure in the finally must NEVER derail the swap or change the verdict.
    import shared.fleet.guest_oracle_transport as got

    monkeypatch.setattr(got, "make_guest_oracle_transport", _ok_transport_factory())
    cfg = _cfg(tmp_path)
    repo = _oracle_repo(tmp_path)

    def stop_boom():
        raise OSError("stop-vm RPC failed")

    res = so.real_run_guest_oracle(
        cfg, "R1", str(repo), "tests/test_job_acceptance.py",
        "from calc import add\n\ndef test_a():\n    assert add(1, 1) == 2\n",
        guest_vm_running=lambda: False,
        ensure_guest_running=lambda: True,
        stop_guest=stop_boom,
        wait_for_service=lambda was_running: True)
    assert res["status"] == "passed"            # probe result survives the stop failure


def test_real_run_guest_oracle_state_probe_failure_defaults_to_stop(
        tmp_path, monkeypatch):
    # If the prior-state probe itself raises, treat the guest as "not running" so the
    # guest we start is still stopped afterwards (fail-soft, footprint-safe).
    import shared.fleet.guest_oracle_transport as got

    monkeypatch.setattr(got, "make_guest_oracle_transport", _ok_transport_factory())
    cfg = _cfg(tmp_path)
    repo = _oracle_repo(tmp_path)
    stopped = []

    def state_boom():
        raise OSError("get-vm RPC failed")

    wait_calls = []
    res = so.real_run_guest_oracle(
        cfg, "R1", str(repo), "tests/test_job_acceptance.py", "x = 1\n",
        guest_vm_running=state_boom,
        ensure_guest_running=lambda: True,
        stop_guest=lambda: stopped.append(1) or True,
        wait_for_service=lambda was_running: wait_calls.append(was_running) or True)
    assert res["status"] == "passed"
    assert stopped == [1]
    # An unreadable prior state is treated as "not running" — the wait gets the
    # COLD budget (was_running=False), the safe direction for a maybe-booting guest.
    assert wait_calls == [False]


# ---------------------------------------------------------------------------
# #744 c.1689 — the SERVICE-READINESS wait: ensure-start reaches hypervisor-
# Running in seconds, but the blarai-oracle listener needs the Alpine guest to
# BOOT (~30-60s+); the first live night probed a still-booting guest, got
# connection-refused, and stopped the VM at ~40s — so a certificate could never
# mint on a cold guest. The bounded wait below sits between ensure-start and
# the probe. EVERY test injects the probe/clock/sleep (or the whole wait seam):
# no real VM, no real seconds slept.
# ---------------------------------------------------------------------------


class _FakeTime:
    """A fake monotonic clock whose sleep() advances it — zero real seconds."""

    def __init__(self):
        self.now = 0.0
        self.sleeps = []

    def clock(self):
        return self.now

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.now += seconds


def test_wait_for_guest_oracle_service_cold_polls_until_reachable():
    # COLD start: the listener accepts on the 4th attempt — True, three polls slept.
    ft = _FakeTime()
    attempts = []

    def probe():
        attempts.append(ft.now)
        return len(attempts) >= 4

    assert so.wait_for_guest_oracle_service(
        False, reachable=probe, budget_s=90.0, grace_s=15.0, poll_s=3.0,
        clock=ft.clock, sleep=ft.sleep) is True
    assert len(attempts) == 4
    assert ft.sleeps == [3.0, 3.0, 3.0]


def test_wait_for_guest_oracle_service_first_probe_success_costs_zero_sleeps():
    # An already-booted guest costs exactly ONE probe and ZERO sleeps — the wait
    # never adds teardown-window time when the service is up.
    ft = _FakeTime()
    assert so.wait_for_guest_oracle_service(
        False, reachable=lambda: True,
        clock=ft.clock, sleep=ft.sleep) is True
    assert ft.sleeps == []


def test_wait_for_guest_oracle_service_cold_budget_exhaustion_returns_false():
    # Never-reachable + cold budget: exhausts at the 90s deadline (fake time),
    # returns False — the caller's honest not-run path, never a raise.
    ft = _FakeTime()
    attempts = []

    def probe():
        attempts.append(ft.now)
        return False

    assert so.wait_for_guest_oracle_service(
        False, reachable=probe, budget_s=90.0, grace_s=15.0, poll_s=3.0,
        clock=ft.clock, sleep=ft.sleep) is False
    # Attempts at t=0,3,...,90 — the deadline check runs AFTER each probe, so
    # the last attempt fires AT the deadline, then the wait gives up.
    assert attempts[0] == 0.0 and attempts[-1] == 90.0
    assert ft.now == 90.0               # fake elapsed == the budget, not a second more


def test_wait_for_guest_oracle_service_already_running_uses_grace_not_budget():
    # was_running=True: the SHORT grace bounds the wait (a presumed-ready guest
    # must not spend the full cold budget inside the teardown window) — but the
    # fast first check + a few polls still cover a half-booted external start.
    ft = _FakeTime()
    attempts = []

    def probe():
        attempts.append(ft.now)
        return False

    assert so.wait_for_guest_oracle_service(
        True, reachable=probe, budget_s=90.0, grace_s=15.0, poll_s=3.0,
        clock=ft.clock, sleep=ft.sleep) is False
    assert ft.now == 15.0               # exhausted at the GRACE, not the 90s budget
    assert attempts[0] == 0.0           # the fast first check fired immediately


def test_wait_for_guest_oracle_service_already_running_fast_first_check_short_circuits():
    ft = _FakeTime()
    assert so.wait_for_guest_oracle_service(
        True, reachable=lambda: True,
        clock=ft.clock, sleep=ft.sleep) is True
    assert ft.sleeps == []              # one probe, zero waiting


def test_wait_for_guest_oracle_service_raising_probe_is_failed_attempt_never_raise():
    # A raising attempt (bridge hiccup) is an unreachable attempt: the loop keeps
    # polling to the deadline and NEVER raises; a later good attempt still wins.
    ft = _FakeTime()
    calls = []

    def flaky():
        calls.append(ft.now)
        if len(calls) < 3:
            raise OSError("bridge spawn hiccup")
        return True

    assert so.wait_for_guest_oracle_service(
        False, reachable=flaky, budget_s=90.0, grace_s=15.0, poll_s=3.0,
        clock=ft.clock, sleep=ft.sleep) is True
    assert len(calls) == 3

    ft2 = _FakeTime()

    def always_boom():
        raise OSError("down")

    assert so.wait_for_guest_oracle_service(
        False, reachable=always_boom, budget_s=9.0, grace_s=3.0, poll_s=3.0,
        clock=ft2.clock, sleep=ft2.sleep) is False


def test_wait_for_guest_oracle_service_defaults_are_the_registered_constants():
    # The seam's defaults ARE the registered budgets (the registry gate locks the
    # constants against the registry; this ties the SIGNATURE to the constants).
    import inspect as _inspect

    sig = _inspect.signature(so.wait_for_guest_oracle_service)
    assert sig.parameters["budget_s"].default == so.GUEST_ORACLE_READY_TIMEOUT_S == 90.0
    assert sig.parameters["grace_s"].default == so.GUEST_ORACLE_READY_GRACE_S == 15.0
    assert sig.parameters["poll_s"].default == so.GUEST_ORACLE_READY_POLL_S == 3.0


def test_real_run_guest_oracle_wait_exhaustion_is_honest_not_run_guest_unreachable(
        tmp_path, monkeypatch):
    # THE night-20260711 lock: the readiness wait exhausts -> the SAME honest
    # not-run(guest-unreachable) path — the transport is never built (we already
    # know the listener refuses), the guest WE started is still stopped, the
    # verdict is untouched, and the trail names the readiness wait.
    import shared.fleet.guest_oracle_transport as got

    factory_calls = []

    def spy_factory(*, vsock_port):
        factory_calls.append(vsock_port)
        raise AssertionError("transport must not be built after wait exhaustion")

    monkeypatch.setattr(got, "make_guest_oracle_transport", spy_factory)
    cfg = _cfg(tmp_path)
    repo = _oracle_repo(tmp_path)
    stopped = []
    res = so.real_run_guest_oracle(
        cfg, "R1", str(repo), "tests/test_job_acceptance.py",
        "from calc import add\n\ndef test_a():\n    assert add(1, 1) == 2\n",
        guest_vm_running=lambda: False,
        ensure_guest_running=lambda: True,
        stop_guest=lambda: stopped.append(1) or True,
        wait_for_service=lambda was_running: False)
    assert res["status"] == "not-run"
    assert res["reason"] == "guest-unreachable"
    assert "readiness wait" in res["evidence"]
    assert str(so.GUEST_ORACLE_VSOCK_PORT) in res["evidence"]
    assert factory_calls == []          # no snapshot ships at a refused listener
    assert stopped == [1]               # the guest we started is STILL stopped
    trail = so.read_swap_progress(cfg, "R1")
    assert "waiting for the oracle service" in trail
    assert "did not become reachable" in trail


def test_real_run_guest_oracle_wait_raise_degrades_to_probe_attempt(
        tmp_path, monkeypatch):
    # A wait that RAISES must never subtract the attempt: degrade to the
    # pre-wait behavior (probe anyway — the transport tells the truth either
    # way), never a raise into the teardown, never a manufactured not-run.
    import shared.fleet.guest_oracle_transport as got

    monkeypatch.setattr(got, "make_guest_oracle_transport", _ok_transport_factory())
    cfg = _cfg(tmp_path)
    repo = _oracle_repo(tmp_path)
    stopped = []

    def wait_boom(was_running):
        raise RuntimeError("wait bug")

    res = so.real_run_guest_oracle(
        cfg, "R1", str(repo), "tests/test_job_acceptance.py",
        "from calc import add\n\ndef test_a():\n    assert add(1, 1) == 2\n",
        guest_vm_running=lambda: False,
        ensure_guest_running=lambda: True,
        stop_guest=lambda: stopped.append(1) or True,
        wait_for_service=wait_boom)
    assert res["status"] == "passed"    # the probe still shipped and its result stands
    assert stopped == [1]


def test_default_wait_seam_builds_the_corridor_probe_once_at_port_50002(monkeypatch):
    # The production default REUSES the corridor's own reachability primitive
    # (make_oracle_reachable_probe — the same bridge `reachable` op the go-live
    # ceremony live-proved), built ONCE, at the guest service's port. The probe
    # double answers immediately, so the real wait loop runs zero sleeps.
    import shared.fleet.guest_oracle_transport as got

    built = []

    def fake_probe_factory(*, vsock_port):
        built.append(vsock_port)
        return lambda: True

    monkeypatch.setattr(got, "make_oracle_reachable_probe", fake_probe_factory)
    assert so._default_wait_for_oracle_service(False) is True
    assert built == [so.GUEST_ORACLE_VSOCK_PORT] == [50002]


def test_default_wait_seam_threads_was_running_into_the_wait(monkeypatch):
    import shared.fleet.guest_oracle_transport as got

    monkeypatch.setattr(
        got, "make_oracle_reachable_probe", lambda *, vsock_port: (lambda: True))
    seen = []
    monkeypatch.setattr(
        so, "wait_for_guest_oracle_service",
        lambda was_running, *, reachable: seen.append(was_running) or True)
    assert so._default_wait_for_oracle_service(True) is True
    assert so._default_wait_for_oracle_service(False) is True
    assert seen == [True, False]


def test_default_wait_seam_probe_build_failure_proceeds_without_waiting(monkeypatch):
    # A probe-BUILD failure (no 3.12+ bridge interpreter) is a HOST transport
    # gap, not guest unreachability: the default seam must proceed (True) so the
    # transport factory reports the precise guest-transport-unregistered
    # degrade — never a manufactured guest-unreachable, never a raise.
    import shared.fleet.guest_oracle_transport as got

    def broken_factory(*, vsock_port):
        raise got.BridgeUnavailableError("no 3.12+ interpreter")

    monkeypatch.setattr(got, "make_oracle_reachable_probe", broken_factory)
    assert so._default_wait_for_oracle_service(False) is True


def test_default_vm_controls_reuse_launcher_primitives(monkeypatch):
    # The production defaults REUSE the launcher's VM-lifecycle primitives (no Hyper-V
    # is reimplemented in swap_ops). Proven with launcher.vm_manager monkeypatched, so
    # the REAL VM is never touched.
    import launcher.vm_manager as vm

    monkeypatch.setattr(vm, "ensure_vm_running", lambda: True)
    monkeypatch.setattr(vm, "stop_vm", lambda: True)
    monkeypatch.setattr(vm, "get_vm_state", lambda: vm.VMState.RUNNING)
    assert so._default_ensure_guest_running() is True
    assert so._default_stop_guest() is True
    assert so._default_guest_vm_running() is True
    monkeypatch.setattr(vm, "get_vm_state", lambda: vm.VMState.OFF)
    assert so._default_guest_vm_running() is False


def test_build_swap_ops_wires_guest_oracle_seams(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    seen = {}
    monkeypatch.setattr(
        so, "real_run_guest_oracle",
        lambda c, rid, repo, rel, code: seen.update(
            run=(rid, repo, rel, code)) or {"status": "not-run", "reason": "x"})
    monkeypatch.setattr(
        so, "real_write_guest_oracle",
        lambda c, rid, block: seen.update(write=(rid, block)))
    ops = so.build_swap_ops(cfg, run_id="RID", old_pid=1, relaunch_argv=["py"],
                            relaunch_cwd="C:/x",
                            tasks=[{"repo": "X", "task": "a", "prompt": "p"}])
    ops.run_guest_oracle("X", "tests/test_job_acceptance.py")
    ops.write_guest_oracle({"status": "not-run"})
    assert seen["run"][0] == "RID" and seen["run"][2] == "tests/test_job_acceptance.py"
    assert seen["write"] == ("RID", {"status": "not-run"})


# ---------------------------------------------------------------------------
# #740 B3 re-grain: per-card run-budget override (consume-once, fresh, clamped)
# ---------------------------------------------------------------------------


def test_pending_run_budget_round_trip_and_consume_once(tmp_path):
    cfg = _cfg(tmp_path)
    assert so.read_pending_run_budget(cfg) is None          # absent -> default
    so.write_pending_run_budget(cfg, 21600.0)
    assert so.read_pending_run_budget(cfg) == 21600.0        # honored once
    assert so.read_pending_run_budget(cfg) is None           # CONSUMED (deleted)


def test_pending_run_budget_clears_on_nonpositive(tmp_path):
    cfg = _cfg(tmp_path)
    so.write_pending_run_budget(cfg, 21600.0)
    so.write_pending_run_budget(cfg, 0.0)                    # a default card clears it
    assert so.read_pending_run_budget(cfg) is None


def test_pending_run_budget_clamped_to_max(tmp_path):
    cfg = _cfg(tmp_path)
    so.write_pending_run_budget(cfg, 999999.0)
    assert so.read_pending_run_budget(cfg) == so.CARD_RUN_BUDGET_MAX_S


def test_pending_run_budget_stale_is_ignored(tmp_path):
    import json
    cfg = _cfg(tmp_path)
    p = so.pending_run_budget_path(cfg)
    p.parent.mkdir(parents=True, exist_ok=True)
    # A budget written 'long ago' (beyond the freshness window) is a stale file
    # from a dispatch that never fired — it must NOT apply to a later job.
    p.write_text(json.dumps({"run_budget_s": 21600.0,
                             "written_at": 0.0}), encoding="utf-8")
    assert so.read_pending_run_budget(cfg) is None
    assert not p.exists()  # still consumed (deleted) so it can't linger


def test_pending_run_budget_garbage_is_none(tmp_path):
    cfg = _cfg(tmp_path)
    p = so.pending_run_budget_path(cfg)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("{not json", encoding="utf-8")
    assert so.read_pending_run_budget(cfg) is None


# ---- #744 host/guest oracle runner parity (c.1526) -----------------------------
#
# The host job oracle and the guest-certified oracle must grade with IDENTICAL
# runner versions, or version skew manufactures fake DIVERGENCE rows in the
# #744 agreement matrix. The guest venv is pinned by the provisioning ceremony
# (pytest 9.1.1 / hypothesis 6.155.7 — docs/security/guest_oracle_provisioning
# _record.md); these locks pin the host to the same versions and the host-side
# dep-scan allowlist to exactly the provisioned roots. The day either lock
# fails IS a guest re-provisioning ceremony.

_GUEST_PINNED_RUNNERS = ("pytest==9.1.1", "hypothesis==6.155.7")


def test_host_oracle_uv_calls_pin_the_guest_runner_versions():
    import inspect

    src = inspect.getsource(so)
    for pin in _GUEST_PINNED_RUNNERS:
        # Both uv call sites (the verify-step test run and the job-oracle
        # grade run) must carry the pin — 2 occurrences each, minimum.
        assert src.count(f'"--with", "{pin}"') >= 2, (
            f"host oracle uv call lost its version pin {pin!r} — either "
            "restore it or run the matching guest re-provisioning ceremony "
            "and update _GUEST_PINNED_RUNNERS (#744 c.1526)"
        )
    # The un-pinned form must be gone everywhere.
    assert '"--with", "pytest",' not in src
    assert '"--with", "hypothesis",' not in src


def test_guest_dep_scan_allowlist_matches_provisioned_runners():
    from shared.fleet import guest_oracle as go

    assert go.GUEST_AVAILABLE_IMPORT_ROOTS == frozenset(
        {"pytest", "_pytest", "hypothesis"}
    ), (
        "GUEST_AVAILABLE_IMPORT_ROOTS drifted from the provisioned guest venv "
        "(pytest + hypothesis, #744 ceremony + c.1526). Extend it only "
        "alongside a guest provisioning ceremony."
    )
