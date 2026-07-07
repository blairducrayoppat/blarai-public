"""Tests for swap_ops — boot-reconcile gating + the AO-side handoff + file helpers.

The subprocess ops (start-llm / run-fleet / Stop-Process / launcher relaunch) are
live and verified on-hardware; here we test the existence-gating, the spec/state
writes, and the report/queue/status file writes (real_stop_ovms + the toast
subprocess are patched so no real process is touched).
"""

from __future__ import annotations

import json
from pathlib import Path

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
    assert seen["timeout_s"] == 300.0


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

    ok = so._run_to_logfile_tree(
        ["pwsh", "-File", "run-fleet.ps1"], log_path=tmp_path / "runs" / "R" / "t.log",
        timeout_s=5.0, on_spawn=seen.append, popen=fake_popen, terminate_tree=lambda p: None,
    )
    assert ok is True
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
        return True

    monkeypatch.setattr(so, "_run_to_logfile_tree", fake_tree)
    cfg = so.build_default_config(str(tmp_path / "agentic"), str(tmp_path / "projects"))
    (cfg.runs_dir / "RID").mkdir(parents=True, exist_ok=True)
    (cfg.runs_dir / "RID" / "SUMMARY.txt").write_text(
        "- t: processed\n  RESULT: MERGED into your project\n", encoding="utf-8")
    sentinel = object()
    oc = so.real_run_task(cfg, "RID", {"repo": "X", "task": "t", "prompt": "p"}, on_spawn=sentinel)
    assert "run-fleet.ps1" in str(seen["cmd"]) and seen["cmd"][-2:] == ["-RunId", "RID"]
    assert seen["log_path"] == cfg.runs_dir / "RID" / "run-fleet-t.log"
    assert seen["timeout_s"] == 3600.0
    assert seen["on_spawn"] is sentinel                # the budget-watchdog seam is wired
    assert oc.task == "t" and oc.result == "MERGED"


def test_run_to_logfile_tree_treekills_whole_tree_on_timeout(tmp_path):
    killed, seen = [], []
    proc = _FakeProc(timeout_first=True)
    ok = so._run_to_logfile_tree(
        ["x"], log_path=tmp_path / "l.log", timeout_s=0.01,
        on_spawn=seen.append, popen=lambda *a, **k: proc,
        terminate_tree=lambda p: killed.append(p),
    )
    assert ok is False
    assert killed == [proc]                            # the WHOLE held tree, not proc.kill() alone
    assert seen[-1] is None                            # holder cleared BEFORE the kill


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
            '"LayoutHard":false,"CaptureTier":"web"}\n',
            encoding="utf-8")
        return True

    monkeypatch.setattr(so, "_run_to_logfile", fake_logfile)
    out = so.real_run_design_loop(cfg, "RID-9", "C:/proj/app", "a landing page", '["hero"]')
    assert out == {"should_iterate": True, "needs_work": True, "feedback": "tighten the hero",
                   "layout_hard": False, "capture_tier": "web"}
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
        return True

    monkeypatch.setattr(so, "_run_to_logfile", fake_logfile)
    so.real_run_design_loop(cfg, "R", "C:/proj/app", "Tony's bakery", "[]")
    joined = " ".join(seen["cmd"])
    assert "-Goal 'Tony''s bakery'" in joined            # the quote is doubled inside the arg
    assert "Tony's bakery" not in joined                 # the raw single-quote form never leaks


def test_real_run_design_loop_fail_soft_on_nonzero_exit(tmp_path, monkeypatch):
    cfg = so.build_default_config(str(tmp_path / "agentic"), str(tmp_path / "projects"))
    monkeypatch.setattr(so, "_run_to_logfile", lambda *a, **k: False)   # non-zero exit / timeout
    out = so.real_run_design_loop(cfg, "R", "C:/proj/app", "g", "[]")
    assert out == {"should_iterate": False, "needs_work": False,
                   "feedback": "design critique unavailable", "layout_hard": False,
                   "capture_tier": ""}


def test_real_run_design_loop_fail_soft_on_unparseable(tmp_path, monkeypatch):
    cfg = so.build_default_config(str(tmp_path / "agentic"), str(tmp_path / "projects"))

    def fake_logfile(cmd, *, log_path, timeout_s, **_kw):
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_text("no json on any line here\n", encoding="utf-8")
        return True

    monkeypatch.setattr(so, "_run_to_logfile", fake_logfile)
    out = so.real_run_design_loop(cfg, "R", "C:/proj/app", "g", "[]")
    assert out["feedback"] == "design critique unavailable"   # unparseable -> fail-soft default
    assert out["should_iterate"] is False


def test_coerce_design_loop_result_tolerates_snake_case_and_missing():
    out = so._coerce_design_loop_result({"should_iterate": 1, "feedback": "x"})
    assert out == {"should_iterate": True, "needs_work": False, "feedback": "x",
                   "layout_hard": False, "capture_tier": ""}


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
