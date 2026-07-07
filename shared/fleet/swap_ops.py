"""Live wiring for the model swap: real SwapOps, boot reconcile, detached entry.

This is the host-level glue between the tested-pure core (``swap_state`` /
``swap_driver`` / ``decompose``) and the real machine: reading free RAM, launching
``start-llm`` / ``run-fleet``, stopping OVMS, relaunching the BlarAI launcher, and
the out-of-band failure signal. The pure core is unit-tested with these injected;
the subprocess ops here are thin, correct-by-construction wrappers whose live
behavior is verified at the operator's on-hardware swap (per the design).

Path layout (derived from the fleet ``state`` dir):
    state/server-should-run.txt        the watchdog sentinel (disarm target)
    state/fleet-swap/current.json       the write-ahead swap-state record
    state/fleet-swap/cancel             the per-task cancel sentinel
    state/fleet-swap/SWAP_FAILED_<R>.txt the out-of-band failure status file

DORMANT until ``[fleet_dispatch].enabled`` — nothing here runs until a real swap.
"""

from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from shared.fleet import swap_state as ss
from shared.fleet.decompose import DEFAULT_MAX_TASKS, decompose_request
from shared.fleet.dispatch import (
    FleetDispatchConfig,
    TaskOutcome,
    _pwsh,
    _safe_run,
    build_default_config,
    new_run_id,
    parse_summary,
    slugify_task,
    validate_repo,
)
from shared.fleet.swap_driver import SwapOps, _noop_critic

_CODER_MODEL_ID = "coder-30b"
_CRITIC_MODEL_ID = "qwen3-14b"   # 14B cross-model critic (#687 task 2)

# The BlarAI checkout root (``<repo>/shared/fleet/swap_ops.py`` -> parents[2]); passed to the
# fleet's ``critique-loop.ps1`` as ``-BlarAiRepo`` so it can run ``python -m shared.fleet.critique``
# against this checkout's venv. Derived (not hard-coded) the same way ``compute_relaunch_argv``
# resolves the repo root, so it is correct in the live main checkout and never a brittle path.
_BLARAI_REPO_ROOT = Path(__file__).resolve().parents[2]

#: Fail-soft sentinel for the design loop: ANY failure (pwsh missing, non-zero exit, non-JSON,
#: timeout) yields this so the driver's design phase no-ops rather than raising (#688 Phase 3).
_DESIGN_LOOP_FALLBACK: dict = {
    "should_iterate": False,
    "needs_work": False,
    "feedback": "design critique unavailable",
    "layout_hard": False,
    "capture_tier": "",
}

#: Fail-soft sentinel for the 14B critic: ANY failure yields this so the driver's critic phase
#: no-ops rather than raising (#687 task 2). ``should_iterate=False`` leaves teardown unblocked.
_CRITIC_FALLBACK: dict = {
    "should_iterate": False,
    "verdict": "UNCLEAR",
    "findings": "critic unavailable",
}


# ---- path layout ----------------------------------------------------------


def state_dir(config: FleetDispatchConfig) -> Path:
    return config.queue_path.parent


def sentinel_path(config: FleetDispatchConfig) -> Path:
    return state_dir(config) / "server-should-run.txt"


def swap_dir(config: FleetDispatchConfig) -> Path:
    return state_dir(config) / "fleet-swap"


def swap_state_path(config: FleetDispatchConfig) -> Path:
    return swap_dir(config) / "current.json"


def cancel_path(config: FleetDispatchConfig) -> Path:
    return swap_dir(config) / "cancel"


def status_path(config: FleetDispatchConfig, run_id: str) -> Path:
    return swap_dir(config) / f"SWAP_FAILED_{run_id}.txt"


# ---- real side-effecting ops (live) ---------------------------------------


def real_stop_ovms() -> None:
    """``Stop-Process -Force -Name ovms`` — idempotent (no-op if not running)."""
    _safe_run(
        [_pwsh(), "-NoProfile", "-NonInteractive", "-Command",
         "Get-Process ovms -ErrorAction SilentlyContinue | Stop-Process -Force"],
        timeout_s=30.0,
    )


def real_ovms_alive() -> bool:
    """True iff an OVMS process is resident — the teardown verify-the-stop probe (#670 P2).

    psutil first; ``tasklist`` fallback; fail-soft -> False on any error. An unreadable probe
    must NOT manufacture a phantom "still alive" that fires signal_failure; the cost of a false
    negative is only that the boot reconciler converges a genuinely-stuck 30B instead of the
    in-line retry, which is the named backstop anyway."""
    try:
        import psutil

        for p in psutil.process_iter(["name"]):
            if (p.info.get("name") or "").lower() in ("ovms", "ovms.exe"):
                return True
        return False
    except Exception:  # noqa: BLE001 — fall through to tasklist
        pass
    try:
        cp = subprocess.run(  # noqa: S603,S607 — short, parsed; no long-lived grandchildren
            ["tasklist", "/FI", "IMAGENAME eq ovms.exe", "/NH"],
            capture_output=True, text=True, timeout=10,
        )
        return "ovms" in (cp.stdout or "").lower()
    except Exception:  # noqa: BLE001 — unreadable -> False (boot reconciler is the backstop)
        return False


def real_available_gb() -> float:
    """Free system RAM in **GiB** (binary) — matches the design's GiB reasoning and the
    fleet's ``Available MBytes`` / 1024 framing, NOT decimal GB (F1: was /1e9, which made
    the 21/24 threshold ~1.07x too lax)."""
    import psutil  # local import: keep the module importable where psutil is absent

    return float(psutil.virtual_memory().available) / (1024 ** 3)


def real_gpu_free_gb() -> "float | None":
    """Best-effort GPU-free (GiB) for the run-2 GPU wait-verify + instrumentation (#670).

    The Arc 140V is an iGPU: its GPU memory is SHARED system RAM, and the Windows GPU perf
    counters under-report OpenVINO/Level-Zero allocations (observed ~0.47 GiB with a 15 GB
    model loaded), so there is no reliable discrete-GPU 'budget free' probe here. We read
    GPU-free as SYSTEM-RAM-free — the pool the iGPU actually allocates from — which tracks
    the 14B's release (its ~8.7 GB returns to system RAM on unload). A true GPU-context /
    budget probe is a live-validate follow-up if one is found. Returns None on any error so
    the gate degrades to the graceful 14B unload rather than a wrong number."""
    try:
        return real_available_gb()
    except Exception:  # noqa: BLE001 — unreadable -> None (rely on the graceful unload)
        return None


def real_backend_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        import psutil

        return psutil.pid_exists(pid)
    except Exception:  # noqa: BLE001
        return False


def real_wait_ready(host: str = "127.0.0.1", port: int = 8000,
                    timeout_s: float = 240.0, poll_s: float = 3.0, sleep=None) -> bool:
    """Confirm OVMS is up on :8000 after the load — a LOCAL socket check.

    ``start-llm.ps1 -Force`` is the AUTHORITATIVE model-readiness wait: it blocks
    until :8000/v3/models serves ``coder-30b`` and only then exits 0 (brief §4.2), so
    ``real_load_30b`` returning True already means the right model is ready. This is a
    belt-and-suspenders "port still listening" confirmation before we spend tasks on
    it, over a LOCAL socket — the air-gap import control (rightly) forbids a runtime
    HTTP client (``urllib.request``); the model-id check is start-llm's job, not ours.
    """
    import socket
    import time

    sleep = sleep or time.sleep
    waited = 0.0
    while waited < timeout_s:
        try:
            with socket.create_connection((host, port), timeout=2):
                return True
        except OSError:
            pass
        sleep(poll_s)
        waited += poll_s
    return False


def _run_to_logfile(
    cmd: list[str],
    *,
    log_path: Path,
    timeout_s: float,
    run=subprocess.run,
) -> bool:
    """Run a bounded subprocess with stdout+stderr → ``log_path`` (NOT a captured pipe)
    + ``close_fds``, then WAIT for it. Returns ``ok = (returncode == 0)``; fail-closed.

    #670 run-2: ``_safe_run``'s ``capture_output=True`` DEADLOCKS for the start-llm
    launch — start-llm spawns LONG-LIVED grandchildren (OVMS + the qwen-proxy) that
    inherit the captured stdout/stderr pipe on Windows, so the pipe never reaches EOF
    and the wait (even the timeout's own ``communicate()``) blocks forever, AFTER
    start-llm has already loaded the 30B and exited (run-2: the 30B reached AVAILABLE,
    the driver hung at "loading the 30B"). Writing to a real FILE means there is no pipe
    to keep open — a grandchild holding the file handle is harmless. ``run`` is injected
    for tests; the start-llm output is preserved in ``log_path`` for diagnosis."""
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with open(log_path, "w", encoding="utf-8", errors="replace") as fh:
            cp = run(
                cmd,
                stdin=subprocess.DEVNULL,
                stdout=fh,
                stderr=subprocess.STDOUT,
                close_fds=True,
                timeout=timeout_s,
            )
        return cp.returncode == 0
    except subprocess.TimeoutExpired:
        return False
    except OSError:
        return False
    except Exception:  # noqa: BLE001 — fail-closed: any error is a load failure
        return False


def _run_to_logfile_tree(
    cmd: list[str],
    *,
    log_path: Path,
    timeout_s: float,
    on_spawn=None,
    popen=subprocess.Popen,
    terminate_tree=None,
) -> bool:
    """Run a LONG-LIVED subprocess (run-fleet) with stdout+stderr -> ``log_path`` (a real FILE,
    never a captured pipe — the #670 run-2 deadlock) + ``close_fds``, then wait. On TIMEOUT,
    TREE-KILL the whole subtree (``pwsh -> opencode -> playwright-msedge``) via the held ``Popen``
    handle (the PRIMARY wedge defense — reuse-proof for the direct child), NOT ``subprocess.run``'s
    direct-child-only kill that orphans grandchildren. ``on_spawn(proc)`` registers the live child
    with the budget-watchdog holder and ``on_spawn(None)`` deregisters on EVERY exit; when None the
    helper is a pure file-redirect tree-killable runner. Returns ``ok = (returncode == 0)``;
    fail-closed. ``popen`` / ``terminate_tree`` injected for tests."""
    if terminate_tree is None:
        from shared.fleet.proc_tree import terminate_process_tree
        terminate_tree = terminate_process_tree
    proc = None
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with open(log_path, "w", encoding="utf-8", errors="replace") as fh:
            proc = popen(cmd, stdin=subprocess.DEVNULL, stdout=fh,
                         stderr=subprocess.STDOUT, close_fds=True)
            if on_spawn is not None:
                try:
                    on_spawn(proc)
                except Exception:  # noqa: BLE001
                    pass
            try:
                rc = proc.wait(timeout=timeout_s)
            except subprocess.TimeoutExpired:
                # Clear the holder FIRST so the budget watchdog won't ALSO try to kill this
                # same child (the holder lock serialises the holder READS -> at most one
                # EFFECTIVE kill, never a wrong process; a second poll()-guarded kill is a
                # harmless no-op), then tree-kill via the held handle.
                if on_spawn is not None:
                    try:
                        on_spawn(None)
                    except Exception:  # noqa: BLE001
                        pass
                try:
                    terminate_tree(proc)
                except Exception:  # noqa: BLE001
                    pass
                return False
        return rc == 0
    except OSError:
        return False
    except Exception:  # noqa: BLE001 — fail-closed: any error is a task failure
        return False
    finally:
        # Deregister on EVERY exit path. The timeout branch already cleared; a redundant
        # clear is harmless (register(None) is idempotent).
        if on_spawn is not None and proc is not None:
            try:
                on_spawn(None)
            except Exception:  # noqa: BLE001
                pass


class _CurrentChild:
    """Thread-safe holder of the live run-fleet child for the budget watchdog (PER run, #670 P2).

    Holds either None or a fully-populated ``(Popen, create_time)`` pair, mutated ONLY under
    ``self._lock`` (so a watchdog read can never see a torn proc/create_time across two tasks).
    ``register`` is called by ``_run_to_logfile_tree`` on spawn (proc) and on exit (None);
    ``abort`` (the watchdog thread) tree-kills the held child reuse-safely; ``begin_teardown``
    (the driver, at teardown ENTRY) makes any subsequent ``abort`` STRUCTURALLY INERT so a late
    budget fire can never act during the 14B restore (LA proof obligation A)."""

    def __init__(self) -> None:
        import threading

        self._lock = threading.Lock()
        self._proc = None            # subprocess.Popen | None
        self._create_time = None     # float | None (psutil create_time captured at register)
        self._tearing_down = False

    def register(self, proc) -> None:
        ct = None
        if proc is not None:
            try:
                import psutil

                ct = psutil.Process(proc.pid).create_time()
            except Exception:  # noqa: BLE001 — best-effort identity baseline
                ct = None
        with self._lock:
            self._proc = proc
            self._create_time = ct

    def begin_teardown(self) -> None:
        # Teardown owns the box now: no abort may act on the registered child after this.
        with self._lock:
            self._tearing_down = True
            self._proc = None
            self._create_time = None

    def abort(self) -> None:
        from shared.fleet.proc_tree import terminate_process_tree

        # Hold the lock across the read + poll() + kill issuance (and the bounded reap inside
        # terminate_process_tree) so a concurrent register(None)/register(next-task) can never
        # make us target the wrong child. The reap is bounded (~3s); no other lock is taken
        # inside terminate_process_tree, so there is no deadlock.
        with self._lock:
            if self._tearing_down:
                return
            proc = self._proc
            ct = self._create_time
            if proc is None:
                return
            try:
                if proc.poll() is not None:   # already exited — nothing to kill
                    return
            except Exception:  # noqa: BLE001
                return
            try:
                terminate_process_tree(proc, child_create_time=ct)
            except Exception:  # noqa: BLE001 — never raise from the watchdog thread
                pass


def real_load_30b(config: FleetDispatchConfig, run_id: str = "") -> bool:
    """``start-llm.ps1 -Model coder-30b -Force`` (brief §4: -Force is MANDATORY).

    #670 run-2: does NOT use the capture-pipe ``_safe_run`` (see :func:`_run_to_logfile`)
    — start-llm's long-lived OVMS/proxy grandchildren inherit a captured pipe and deadlock
    the driver AFTER the 30B is already loaded. Redirect start-llm's output to a per-run
    LOG FILE (kept for diagnosis). The parsing callers (run-fleet build/test/verify) keep
    ``_safe_run`` — short subprocesses whose stdout we must read."""
    script = config.scripts_dir / "start-llm.ps1"
    cmd = [_pwsh(), "-NoProfile", "-NonInteractive", "-File", str(script),
           "-Model", _CODER_MODEL_ID, "-Force"]
    base = (config.runs_dir / run_id) if run_id else config.runs_dir
    return _run_to_logfile(cmd, log_path=base / "start-llm.log", timeout_s=300.0)


def real_load_14b(config: FleetDispatchConfig, run_id: str = "") -> bool:
    """``start-llm.ps1 -Model qwen3-14b -Force`` — the 14B critic model swap (#687 task 2).

    Mirrors ``real_load_30b``: uses :func:`_run_to_logfile` (NOT the capture-pipe ``_safe_run``
    — start-llm's long-lived OVMS grandchildren inherit a captured pipe and deadlock on Windows).
    The ``-Force`` flag replaces whatever model is currently in OVMS (typically the 30B).
    Output is redirected to a per-run LOG FILE (kept for diagnosis)."""
    script = config.scripts_dir / "start-llm.ps1"
    cmd = [_pwsh(), "-NoProfile", "-NonInteractive", "-File", str(script),
           "-Model", _CRITIC_MODEL_ID, "-Force"]
    base = (config.runs_dir / run_id) if run_id else config.runs_dir
    return _run_to_logfile(cmd, log_path=base / "start-14b.log", timeout_s=300.0)


def _ps_single_quote(value: str) -> str:
    """Escape ``value`` for embedding inside a PowerShell single-quoted string (``'...'``): a
    literal single quote is doubled. The operator's free-text goal / criteria ride into the
    ``Invoke-CritiquePass`` ``-Command`` as single-quoted args, so this both keeps a quote in the
    text from breaking the command AND closes the obvious injection seam (a ``'`` can't end the
    string and start a new statement). Mirrors PowerShell's own single-quote-escaping rule."""
    return str(value).replace("'", "''")


def _parse_design_loop_json(text: str) -> "dict | None":
    """Extract the critique pass's compact JSON object from the design-loop logfile, or ``None``.

    ``Invoke-CritiquePass | ConvertTo-Json -Compress`` writes a single-line ``{...}`` to stdout
    (redirected to the logfile), but the file may also carry capture/critique progress noise. Scan
    the lines in REVERSE and return the first that parses as a JSON object carrying a recognized
    critique key — robust to leading diagnostics. Never raises (fail-soft)."""
    for raw in reversed((text or "").splitlines()):
        line = raw.strip()
        if not (line.startswith("{") and line.endswith("}")):
            continue
        try:
            data = json.loads(line)
        except (ValueError, TypeError):
            continue
        if isinstance(data, dict) and (
            "ShouldIterate" in data or "should_iterate" in data
            or "Feedback" in data or "feedback" in data
        ):
            return data
    return None


def _parse_critic_result(text: str) -> "dict | None":
    """Extract the critic verdict from the ``critic-run.ps1`` logfile output.

    Scans for ``VERDICT: MERGE`` or ``VERDICT: FIX FIRST`` (last occurrence wins, in case
    the agent reasons aloud before concluding); collects numbered blocker lines that follow.
    Returns ``{should_iterate, verdict, findings}`` or ``None`` (no verdict found -> fallback).
    Never raises (fail-soft)."""
    import re

    lines = (text or "").splitlines()
    verdict: "str | None" = None
    verdict_idx = -1
    for i, raw in enumerate(lines):
        line = raw.strip()
        if re.search(r"VERDICT\s*:\s*MERGE\b", line, re.IGNORECASE):
            verdict = "MERGE"
            verdict_idx = i
        elif re.search(r"VERDICT\s*:\s*FIX\s*FIRST\b", line, re.IGNORECASE):
            verdict = "FIX FIRST"
            verdict_idx = i
    if verdict is None:
        return None
    findings_lines: list = []
    for raw in lines[verdict_idx + 1:]:
        line = raw.strip()
        if re.match(r"^\d+\.", line):
            findings_lines.append(line)
    return {
        "should_iterate": verdict == "FIX FIRST",
        "verdict": verdict,
        "findings": "\n".join(findings_lines),
    }


def _coerce_design_loop_result(data: dict) -> dict:
    """Map the PowerShell hashtable JSON (``ShouldIterate``/``NeedsWork``/``Feedback``/``LayoutHard``
    /``CaptureTier``) onto the driver's snake_case dict, tolerating either casing and a missing key
    (-> the fail-closed default for that field). Booleans coerce via ``bool``; strings via ``str``."""
    def _b(*keys: str) -> bool:
        for k in keys:
            if k in data and data[k] is not None:
                return bool(data[k])
        return False

    def _s(*keys: str) -> str:
        for k in keys:
            if k in data and data[k] is not None:
                return str(data[k])
        return ""

    return {
        "should_iterate": _b("ShouldIterate", "should_iterate"),
        "needs_work": _b("NeedsWork", "needs_work"),
        "feedback": _s("Feedback", "feedback"),
        "layout_hard": _b("LayoutHard", "layout_hard"),
        "capture_tier": _s("CaptureTier", "capture_tier"),
    }


def real_run_design_loop(
    config: FleetDispatchConfig,
    run_id: str,
    app_dir: str,
    goal: str,
    visual_criteria_json: str,
) -> dict:
    """ONE capture+critique pass over the BUILT app, via the fleet's ``critique-loop.ps1`` (#688).

    Invokes ``Invoke-CritiquePass`` (which runs ``capture-app.ps1`` then ``python -m
    shared.fleet.critique`` over the in-process VLM) as a pwsh subprocess, redirected to a per-run
    LOGFILE — NOT a captured pipe. A headless-``msedge`` capture can leave long-lived grandchildren
    that inherit a captured stdout pipe and deadlock the wait (the #670 run-2 failure mode), so we
    reuse :func:`_run_to_logfile` and read the compact JSON back from the file. The dot-source with
    placeholder args binds ``critique-loop.ps1``'s param block before the call (mirroring
    ``new-agent-task.ps1``); the operator's free-text args are PowerShell single-quote-escaped.

    Returns ``{should_iterate, needs_work, feedback, layout_hard, capture_tier}``. FAIL-SOFT: ANY
    failure (pwsh missing, non-zero exit, non-JSON, timeout ~180s, unreadable log) returns a COPY of
    :data:`_DESIGN_LOOP_FALLBACK` and NEVER raises — the design phase is best-effort, never blocking."""
    try:
        script = config.scripts_dir / "critique-loop.ps1"
        command = (
            f". '{_ps_single_quote(str(script))}' -AppDir 'x' -Goal 'x' "
            "-VisualCriteriaJson '[]' -BlarAiRepo 'x' 2>$null; "
            f"$r = Invoke-CritiquePass -AppDir '{_ps_single_quote(app_dir)}' "
            f"-Goal '{_ps_single_quote(goal)}' "
            f"-VisualCriteriaJson '{_ps_single_quote(visual_criteria_json)}' "
            f"-BlarAiRepo '{_ps_single_quote(str(_BLARAI_REPO_ROOT))}'; "
            "$r | ConvertTo-Json -Compress"
        )
        cmd = [_pwsh(), "-NoProfile", "-NonInteractive", "-Command", command]
        base = (config.runs_dir / run_id) if run_id else config.runs_dir
        log_path = base / "design-critique.log"
        ok = _run_to_logfile(cmd, log_path=log_path, timeout_s=180.0)
        if not ok:
            return dict(_DESIGN_LOOP_FALLBACK)
        try:
            text = log_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return dict(_DESIGN_LOOP_FALLBACK)
        data = _parse_design_loop_json(text)
        if data is None:
            return dict(_DESIGN_LOOP_FALLBACK)
        return _coerce_design_loop_result(data)
    except Exception:  # noqa: BLE001 — fail-soft: the design pass must NEVER raise into the driver
        return dict(_DESIGN_LOOP_FALLBACK)


def real_run_critic(
    config: FleetDispatchConfig,
    run_id: str,
    app_dir: str,
    base_branch: str,
) -> dict:
    """Load the 14B and run ONE critic pass over the merged diff (#687 task 2).

    Sequence: ``start-llm.ps1 -Model qwen3-14b -Force`` (swaps from 30B to 14B) +
    ``real_wait_ready`` (belt-and-suspenders port check), then ``critic-run.ps1`` via
    :func:`_run_to_logfile` (NOT a captured pipe — avoids the #670 run-2 grandchild deadlock);
    parse the VERDICT from the logfile.

    Returns ``{should_iterate, verdict, findings}``. FAIL-SOFT: ANY failure (load failed,
    port not up, pwsh missing, non-zero exit, unparseable output, timeout ~10 min) returns a
    COPY of :data:`_CRITIC_FALLBACK` and NEVER raises — the critic phase is best-effort and
    can NEVER block the driver's teardown or the 14B restore (#687 task 2 NEVER-ZERO)."""
    try:
        if not real_load_14b(config, run_id):
            return dict(_CRITIC_FALLBACK)
        if not real_wait_ready():
            return dict(_CRITIC_FALLBACK)
        script = config.scripts_dir / "critic-run.ps1"
        cmd = [_pwsh(), "-NoProfile", "-NonInteractive", "-File", str(script),
               "-AppDir", app_dir, "-BaseBranch", base_branch,
               "-Model", _CRITIC_MODEL_ID]
        base = (config.runs_dir / run_id) if run_id else config.runs_dir
        log_path = base / "critic-run.log"
        ok = _run_to_logfile(cmd, log_path=log_path, timeout_s=600.0)
        if not ok:
            return dict(_CRITIC_FALLBACK)
        try:
            text = log_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return dict(_CRITIC_FALLBACK)
        data = _parse_critic_result(text)
        if data is None:
            return dict(_CRITIC_FALLBACK)
        return data
    except Exception:  # noqa: BLE001 — fail-soft: critic must NEVER raise into the driver
        return dict(_CRITIC_FALLBACK)


def write_single_task_queue(config: FleetDispatchConfig, task: dict) -> Path:
    """Write a one-task queue file for a per-task run-fleet invocation (cancel granularity)."""
    qpath = swap_dir(config) / "task-queue.json"
    qpath.parent.mkdir(parents=True, exist_ok=True)
    qpath.write_text(json.dumps([task], indent=2), encoding="utf-8")
    return qpath


def real_run_task(config: FleetDispatchConfig, run_id: str, task: dict, *, on_spawn=None) -> TaskOutcome:
    """Run ONE task via run-fleet (shared -RunId accumulates done.txt), parse its outcome.

    #670 P2: run-fleet is a LONG-LIVED subtree (``pwsh -> opencode -> playwright-msedge``); it
    MUST NOT use the capture-pipe ``_safe_run`` (a grandchild inherits the pipe on Windows and
    deadlocks the wait past the 3600s timeout — the CODE wedge that left the 30B resident).
    Redirect to a per-run-per-task LOG FILE via :func:`_run_to_logfile_tree` (no inheritable pipe;
    tree-kill on timeout). We parse SUMMARY.txt from disk, so dropping captured stdout costs
    nothing. ``on_spawn`` (ONLY the live run-task path passes a real one) hands the child to the
    budget watchdog; ``real_load_30b`` MUST pass None (start-llm is OVMS's parent — registering
    its child would let the budget abort tree-kill OVMS)."""
    qpath = write_single_task_queue(config, task)
    script = config.scripts_dir / "run-fleet.ps1"
    name = str(task.get("task", ""))
    log_path = config.runs_dir / run_id / f"run-fleet-{slugify_task(name)}.log"
    _run_to_logfile_tree(
        [_pwsh(), "-NoProfile", "-NonInteractive", "-File", str(script),
         "-Queue", str(qpath), "-RunId", run_id],
        log_path=log_path, timeout_s=3600.0, on_spawn=on_spawn,
    )
    # run-fleet overwrites SUMMARY.txt with THIS invocation's task; parse it.
    summary = config.runs_dir / run_id / "SUMMARY.txt"
    try:
        outcomes = parse_summary(summary.read_text(encoding="utf-8", errors="replace"))
    except OSError:
        outcomes = []
    for oc in outcomes:
        if oc.task == name:
            return oc
    return TaskOutcome(task=name, outcome="unknown", result="UNKNOWN",
                       detail="no SUMMARY line for this task")


def write_cumulative_report(config: FleetDispatchConfig, run_id: str,
                            outcomes: list) -> None:
    """Write the cumulative SUMMARY.txt aggregating every task (run-fleet overwrote it per task).

    Uses the SAME shape run-fleet writes — ``- <task>: <outcome>`` then an indented ``RESULT: …``
    line — so :func:`shared.fleet.dispatch.parse_summary` (the one parser the harness + the gateway
    ``/dispatch status`` share) reads it byte-compatibly. A divergent shape here (a 2-space indent +
    an inline ``RESULT``) made them classify the final outcome as NONE once they began reading the
    cumulative file at swap-back (#686)."""
    path = config.runs_dir / run_id / "SUMMARY.txt"
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [f"Fleet run {run_id} — {len(outcomes)} task(s):"]
    for oc in outcomes:
        task = getattr(oc, "task", "") or "task"
        outcome = getattr(oc, "outcome", "") or "processed"
        detail = getattr(oc, "detail", "") or f"RESULT: {getattr(oc, 'result', 'UNKNOWN')}"
        lines.append(f"- {task}: {outcome}")
        lines.append(f"    {detail}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_failure_status(config: FleetDispatchConfig, run_id: str, message: str) -> None:
    """Out-of-band failure signal: write a conspicuous status file the operator (or a
    future WinUI poll) can see when the assistant did not restart.

    No toast: a real Windows toast needs the full ToastNotification XML / BurntToast,
    and the prior inline pwsh did NOT actually raise a notification — so it is dropped
    rather than shipped as theater. The status file IS the signal; a real toast is a
    #670 follow-up (paired with the WinUI-reconnect work)."""
    path = status_path(config, run_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(message + "\n", encoding="utf-8")


def swap_progress_path(config: FleetDispatchConfig, run_id: str) -> Path:
    return config.runs_dir / run_id / "swap-progress.log"


def write_swap_progress(config: FleetDispatchConfig, run_id: str, message: str) -> None:
    """Append one human-readable swap-progress line, persisted (restart-surviving, like
    acceptance.json) under the run id (#670). The WinUI window CLOSES the moment the
    launcher steps aside, so the operator is blind during the swap; this trail is what they
    read after the box comes back (stepping aside -> driver spawned -> 30B loading -> gate
    pass/abort -> fleet running -> swapping back -> 14B restored). Best-effort + fail-soft:
    a progress-write failure must never derail the swap."""
    try:
        path = swap_progress_path(config, run_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(message.rstrip() + "\n")
    except OSError:
        pass


def read_swap_progress(config: FleetDispatchConfig, run_id: str) -> str:
    """The persisted swap-progress trail for a run, or '' if none — surfaced by
    ``/dispatch status`` so the operator can read what happened during the swap."""
    try:
        return swap_progress_path(config, run_id).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


# ---- boot reconcile (testable gating + real stop) -------------------------


def reconcile_at_boot(config: FleetDispatchConfig) -> ss.ReconcileResult | None:
    """Run the crash-recovery reconciler at backend boot — ONLY if a BlarAI swap-state
    file is in a non-terminal phase. Returns the ReconcileResult (for the AO to
    surface), or None when there is nothing to do (the clean, common case — no
    subprocess spawned, the fleet's sentinel/OVMS untouched).

    F2: the gate is the BlarAI swap-state ALONE — NOT the fleet's
    ``server-should-run.txt`` sentinel (which is armed whenever the operator runs the
    30B via OpenCode). Keying off the sentinel would make a BlarAI boot kill the
    operator's running 30B and disarm the fleet watchdog, breaking dormancy.
    """
    sp = swap_state_path(config)
    if not ss.is_in_flight(ss.read_swap_state(sp)):
        return None  # no in-flight BlarAI swap -> total no-op
    return ss.reconcile_swap_state(
        swap_state_path=sp,
        sentinel_path=sentinel_path(config),
        runs_dir=config.runs_dir,
        stop_ovms=real_stop_ovms,
    )


def reconcile_at_boot_for_roots(
    agentic_setup_dir: str, projects_dir: str
) -> ss.ReconcileResult | None:
    """Boot reconcile over the CONFIGURED fleet root (#670), not the compiled-in fallback.

    Builds the fleet config from the AO-resolved ``[fleet_dispatch]`` roots (an empty value
    falls back to ``build_default_config``'s compiled-in default for this box) and runs
    :func:`reconcile_at_boot` over it. Load-bearing for crash recovery on a NON-default
    ``agentic_setup_dir``: the live EXECUTE path writes the swap-state under the configured
    root, so the boot reconciler must READ under that SAME root — otherwise writer and
    recoverer disagree and the restore-the-14B / never-end-at-zero recovery silently never
    fires. The AO boot-hook calls this with the local resolved config (``self._resolved_config``
    is not yet assigned at that point in ``start()``).
    """
    config = build_default_config(agentic_setup_dir or None, projects_dir or None)
    return reconcile_at_boot(config)


# ---- the detached driver entry (live) -------------------------------------

# Windows process-creation flags so the driver OUTLIVES the launcher it relaunches
# (mirrors the increment-1 run_fleet detached launch).
_DETACHED = 0x00000008          # DETACHED_PROCESS
_NEW_GROUP = 0x00000200         # CREATE_NEW_PROCESS_GROUP
_BREAKAWAY = 0x01000000         # CREATE_BREAKAWAY_FROM_JOB


def real_backend_ready(port: int = 5001, timeout_s: float = 180.0,
                       poll_s: float = 3.0, sleep=None) -> bool:
    """Poll the relaunched AO listener (loopback) until it accepts a connection.

    Waits up to *timeout_s* because the fresh launcher must cold-load the 14B
    before the AO listens — readiness is "the new backend is actually up", not
    "the relaunch command returned" (design §2.3)."""
    import socket
    import time

    sleep = sleep or time.sleep
    waited = 0.0
    while waited < timeout_s:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=2):
                return True
        except OSError:
            pass
        sleep(poll_s)
        waited += poll_s
    return False


def build_swap_ops(
    config: FleetDispatchConfig,
    *,
    run_id: str,
    old_pid: int,
    relaunch_argv: list[str],
    relaunch_cwd: str,
    ao_port: int = 5001,
    tasks: "list | None" = None,
    current_child: "_CurrentChild | None" = None,
    stop_event=None,
) -> SwapOps:
    """Wire the real side-effecting ops into a ``SwapOps`` for the driver (live).

    ``tasks`` (this run's approved task set) feeds the worktree sweep; ``current_child`` /
    ``stop_event`` are the PER-RUN budget-watchdog instances (constructed in :func:`run_swap`).
    All three default to inert so the legacy callers/tests stay byte-stable (#670 P2)."""
    tasks = list(tasks or [])
    # #687 task 2: read the critic-enable env ONCE in THIS (the swap_driver) process, so the wired op
    # and the observable ``critic_enabled`` flag always agree. Surfacing the flag in the progress
    # trail makes the false-dormant trap (env exported on the wrong process) visible, not silent.
    critic_on = (
        str(os.environ.get("BLARAI_ENABLE_CRITIC", "")).strip().lower()
        in ("1", "true", "yes", "on")
    )

    def restart_launcher() -> None:
        try:
            subprocess.Popen(relaunch_argv, cwd=relaunch_cwd or None,  # noqa: S603
                             creationflags=_DETACHED | _NEW_GROUP | _BREAKAWAY,
                             close_fds=True)
        except OSError:
            subprocess.Popen(relaunch_argv, cwd=relaunch_cwd or None,  # noqa: S603
                             creationflags=_DETACHED | _NEW_GROUP, close_fds=True)

    return SwapOps(
        available_gb=real_available_gb,
        backend_alive=lambda: real_backend_alive(old_pid),
        load_30b=lambda: real_load_30b(config, run_id),
        wait_ready=real_wait_ready,
        # ONLY the live run-task path registers a child with the budget-watchdog holder; the
        # LOAD path (real_load_30b) does NOT, so the budget abort can never tree-kill OVMS.
        run_task=lambda task: real_run_task(
            config, run_id, task,
            on_spawn=(current_child.register if current_child is not None else None)),
        cancel_requested=lambda: cancel_path(config).exists(),
        disarm_watchdog=lambda: _rm(sentinel_path(config)),
        stop_ovms=real_stop_ovms,
        write_report=lambda rid, outs: write_cumulative_report(config, rid, outs),
        restart_launcher=restart_launcher,
        backend_ready=lambda: real_backend_ready(ao_port),
        signal_failure=lambda msg: write_failure_status(config, run_id, msg),
        # Same run-id-keyed progress log the AO started — the detached driver continues the
        # trail (30B loading -> gate -> fleet -> swapping back -> 14B restored) under the SAME
        # config root, so the operator reads one continuous story after the box returns (#670).
        write_progress=lambda msg: write_swap_progress(config, run_id, msg),
        # GPU-free probe for the run-2 GPU wait-verify + instrumentation (system-RAM-free as
        # the iGPU's GPU-memory pool proxy; best-effort -> None on error).
        gpu_free_gb=real_gpu_free_gb,
        # #670 P2 teardown robustness.
        ovms_alive=real_ovms_alive,
        stop_requested=(stop_event.is_set if stop_event is not None else (lambda: False)),
        begin_teardown=(current_child.begin_teardown if current_child is not None
                        else (lambda: None)),
        sweep_worktrees=lambda: _git_sweep_worktrees(config, tasks),
        # #688 Phase 3: the end-of-run VLM design loop runs ONE capture+critique pass per call
        # over the built app, with the 30B already unloaded so the GPU is free (the driver
        # choreographs the unload/reload). Threads config + run_id like the other real_* closures.
        run_design_loop=lambda app_dir, goal, vcj: real_run_design_loop(
            config, run_id, app_dir, goal, vcj),
        # #687 task 2: the cross-model 14B critic — loads the 14B via start-llm -Force (swaps
        # from 30B), runs critic-run.ps1, and parses VERDICT. Fail-soft; NEVER raises into driver.
        # DORMANT by default: the coder-30b<->qwen3-14b OVMS swap is NOT yet hardware-verified (a
        # follow-on, like the design loop was), so we do NOT auto-run an untested swap on the
        # operator's live dispatches. Set BLARAI_ENABLE_CRITIC=1/true to activate (the live-verify
        # ceremony); unset -> the no-op default (byte-identical to before this feature shipped).
        run_critic=(
            (lambda app_dir, base: real_run_critic(config, run_id, app_dir, base))
            if critic_on
            else _noop_critic
        ),
        # Observable enablement: the driver logs ACTIVE/DORMANT from this so a dormant run is never
        # mistaken for a working one (and vice-versa). Same predicate as run_critic — they can't drift.
        critic_enabled=critic_on,
    )


def _rm(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        pass
    except OSError:
        pass


def _parse_worktree_porcelain(out: str) -> dict:
    """Parse ``git worktree list --porcelain`` into ``{resolved_path: branch_short_name}``.
    A ``worktree <path>`` line opens a record; a following ``branch refs/heads/<name>`` sets its
    branch (``None`` for a detached/bare worktree)."""
    result: dict = {}
    cur = None
    for line in (out or "").splitlines():
        if line.startswith("worktree "):
            raw = line[len("worktree "):].strip()
            try:
                cur = Path(raw).resolve()
            except Exception:  # noqa: BLE001
                cur = None
            if cur is not None:
                result[cur] = None
        elif line.startswith("branch ") and cur is not None:
            ref = line[len("branch "):].strip()
            result[cur] = ref[len("refs/heads/"):] if ref.startswith("refs/heads/") else ref
    return result


def _git_sweep_worktrees(config: FleetDispatchConfig, tasks: list) -> None:
    """Remove THIS run's leftover task worktree DIRECTORIES; NEVER delete a branch (#670 P2).

    Reconstructs each worktree path the SAME way ``new-agent-task.ps1`` does
    (``<repo.parent>/<repo.name>-<sanitised task>``), intersects with the repo's REGISTERED
    worktrees whose branch is EXACTLY ``agent/<slug>`` (provenance: only a worktree THIS run's
    task owns — never a same-named operator/concurrent-run worktree on a different branch), and
    removes those with a force-FREE ``git worktree remove`` (which REFUSES on uncommitted /
    secret-park work -> we skip it; committed-but-unmerged work survives on its ``agent/<slug>``
    branch). Branches are NEVER deleted (the parked branch is the operator's recovery handle).
    Runs AFTER the 14B restore; every git op is timeout-bounded + fail-soft, so a slow/hung git
    can never sit on the critical path ahead of the restore."""
    import re

    by_repo: dict = {}
    for t in tasks:
        repo_raw = str(t.get("repo", "")).strip()
        slug = re.sub(r"[^A-Za-z0-9_-]", "-", str(t.get("task", "")))
        if repo_raw and slug:
            by_repo.setdefault(repo_raw, []).append(slug)
    for repo_raw, slugs in by_repo.items():
        try:
            repo = Path(repo_raw).resolve()
        except Exception:  # noqa: BLE001
            continue
        ok, out, _err = _safe_run(
            ["git", "-C", str(repo), "worktree", "list", "--porcelain"], 30.0)
        if not ok:
            continue
        registered = _parse_worktree_porcelain(out)
        for slug in slugs:
            try:
                wt = (repo.parent / f"{repo.name}-{slug}").resolve()
            except Exception:  # noqa: BLE001
                continue
            if wt == repo:
                continue  # never the main worktree
            if registered.get(wt) != f"agent/{slug}":
                continue  # not registered, or a same-named worktree on a DIFFERENT branch
            _safe_run(["git", "-C", str(repo), "worktree", "remove", str(wt)], 60.0)  # NO --force
        _safe_run(["git", "-C", str(repo), "worktree", "prune"], 30.0)


def prepare_and_launch_swap(
    config: FleetDispatchConfig,
    *,
    run_id: str,
    session_id: str,
    tasks: list[dict],
    old_pid: int,
    relaunch_argv: list[str],
    relaunch_cwd: str,
    gate_gb: float,
    run_budget_s: float = 0.0,
    spawn: "callable | None" = None,
) -> None:
    """AO-side handoff (design §2 steps 3-5): clear any stale cancel, persist the
    write-ahead swap-state (phase HANDOFF) + the driver spec, then spawn the
    DETACHED driver (breakaway, so it outlives the launcher's imminent exit).

    The caller (the coordinator) signals the launcher to exit AFTER this returns.
    ``spawn`` is injectable for testing; the default spawns the real detached entry.
    ``run_budget_s`` is the out-of-band overall-run budget (0 disables; #670 P2)."""
    _rm(cancel_path(config))  # a prior run's cancel must not abort this one
    ss.write_swap_state(
        ss.SwapState(run_id=run_id, session_id=session_id, phase=ss.PHASE_HANDOFF,
                     tasks=tasks),
        path=swap_state_path(config),
    )
    spec = {
        "run_id": run_id,
        "session_id": session_id,
        "old_pid": old_pid,
        "relaunch_argv": relaunch_argv,
        "relaunch_cwd": relaunch_cwd,
        "gate_gb": gate_gb,
        "run_budget_s": run_budget_s,
        "scripts_dir": str(config.scripts_dir),
        "queue_path": str(config.queue_path),
        "runs_dir": str(config.runs_dir),
        "projects_dir": str(config.projects_dir),
    }
    spec_path = swap_dir(config) / "spec.json"
    spec_path.parent.mkdir(parents=True, exist_ok=True)
    spec_path.write_text(json.dumps(spec, indent=2), encoding="utf-8")
    (spawn or _spawn_detached_driver)(spec_path)


def _spawn_detached_driver(spec_path: Path) -> None:
    import sys

    subprocess.Popen(  # noqa: S603
        [sys.executable, "-m", "shared.fleet.swap_ops", "--spec", str(spec_path)],
        creationflags=_DETACHED | _NEW_GROUP | _BREAKAWAY, close_fds=True,
    )


def _coerce_budget(value) -> float:
    """Coerce a spec/config overall-run budget to a non-negative float; a non-numeric or
    non-positive value -> 0.0 (DISABLED — never an instant-timeout). Mirrors the AO config
    resolver's defensive coercion (#670 P2)."""
    try:
        b = float(value)
    except (TypeError, ValueError):
        return 0.0
    return b if b > 0 else 0.0


def run_swap(spec_path: Path):
    """Build the config + real ops from a spec file and run the swap (live entry)."""
    import threading

    from shared.fleet.swap_driver import BudgetWatchdog, SwapDriver

    spec = json.loads(Path(spec_path).read_text(encoding="utf-8"))
    config = FleetDispatchConfig(
        scripts_dir=Path(spec["scripts_dir"]),
        queue_path=Path(spec["queue_path"]),
        runs_dir=Path(spec["runs_dir"]),
        projects_dir=Path(spec["projects_dir"]),
    )
    tasks = ss.read_swap_state(swap_state_path(config))
    tasks = tasks.tasks if tasks else []
    # PER-RUN budget-watchdog instances (never module globals / filesystem sentinels) — a fresh
    # _CurrentChild + stop_event so a prior run's budget-timeout can never poison this one.
    current_child = _CurrentChild()
    stop_event = threading.Event()
    ops = build_swap_ops(
        config, run_id=spec["run_id"], old_pid=int(spec["old_pid"]),
        relaunch_argv=list(spec["relaunch_argv"]), relaunch_cwd=spec["relaunch_cwd"],
        tasks=tasks, current_child=current_child, stop_event=stop_event,
    )
    budget_s = _coerce_budget(spec.get("run_budget_s", 0.0))
    watchdog = (BudgetWatchdog(budget_s=budget_s, abort=current_child.abort,
                               request_stop=stop_event.set)
                if budget_s > 0 else None)
    return SwapDriver(
        run_id=spec["run_id"], session_id=spec["session_id"], tasks=tasks,
        swap_state_path=swap_state_path(config), ops=ops,
        gate_gb=float(spec.get("gate_gb", 21.0)), budget_watchdog=watchdog,
    ).run()


# ---- AO-side orchestration (design §2 steps 1-5) --------------------------


@dataclass(frozen=True)
class SwapDispatchResult:
    """Outcome of the AO-side dispatch (before step-aside). ``ok`` gates the exit."""

    ok: bool
    run_id: str = ""
    tasks: list = field(default_factory=list)
    message: str = ""


def _venv_python(repo_root: Path) -> str:
    """The project venv interpreter for a swap relaunch (#670 run-1 bug 2).

    The relaunch must NOT inherit a foreign ``sys.executable`` — run-1 came up under
    system ``Python311`` because ``compute_relaunch_argv`` trusted ``sys.executable``,
    whatever started the *firing* launcher. Resolve the checkout's own ``.venv``
    deterministically (Windows ``Scripts`` layout, then POSIX ``bin``); fall back to
    ``sys.executable`` only if neither exists.
    """
    import sys

    for rel in (("Scripts", "python.exe"), ("bin", "python")):
        candidate = repo_root.joinpath(".venv", *rel)
        if candidate.exists():
            return str(candidate)
    return sys.executable


def compute_relaunch_argv(
    *,
    winui: bool,
    go_live: bool = False,
    python_exe: "str | None" = None,
    repo_root: "str | Path | None" = None,
) -> "tuple[list[str], str]":
    """The canonical ``(relaunch_argv, relaunch_cwd)`` for bringing the launcher back up
    after a swap (#670 process model: ``python -m launcher [--winui] [--go-live]`` from the
    repo root). The launcher captures its OWN mode at startup + hands these to the driver via
    the spec; the driver respawns them. Pure + unit-testable — the actual exit/relaunch is
    live-only (Phase B). ``python_exe`` / ``repo_root`` are injectable; the live default for
    the interpreter is the checkout's ``.venv`` (NOT ``sys.executable`` — #670 run-1 bug 2),
    and the default root is this checkout's repo root."""
    root = Path(repo_root) if repo_root else Path(__file__).resolve().parents[2]
    py = python_exe or _venv_python(root)
    argv = [str(py), "-m", "launcher"]
    if winui:
        argv.append("--winui")
    if go_live:
        argv.append("--go-live")
    return argv, str(root)


def execute_swap_dispatch(
    run_id: str,
    session_id: str,
    tasks: list,
    *,
    config: FleetDispatchConfig,
    gate_gb: float,
    old_pid: int,
    relaunch_argv: list[str],
    relaunch_cwd: str,
    run_budget_s: float = 0.0,
    validate=validate_repo,
    spawn=None,
) -> SwapDispatchResult:
    """EXECUTE the operator-APPROVED dispatch (design §2 steps 3-5): VALIDATE each approved
    repo (fail-fast) then HAND OFF to the detached driver. The CALLER signals the launcher to
    step aside ONLY after this returns ``ok`` (a validation failure leaves the 14B untouched,
    nothing swapped).

    **#670 P2 (no destructive data):** the prior version APPENDED every task to the operator's
    SHARED ``fleet-queue.json`` (``config.queue_path``) — a file the swap path never even reads
    (the detached driver runs from the swap-state; ``real_run_task`` runs run-fleet against a
    PER-TASK ``task-queue.json``). That append was vestigial pollution that a later MANUAL
    run-fleet would re-run, and a "fresh queue" reset would have DESTROYED the operator's
    overnight tasks on that same shared file. So we now VALIDATE the repo DIRECTLY (the same
    ``validate_repo`` fail-fast the old enqueue performed) and write NOTHING to the shared queue.

    **Writer-root (#670):** the swap-state WRITE path derives from ``config`` (the AO-resolved
    fleet root) — the SAME root the boot reconciler reads, so a crashed swap is recovered under
    the root it was written to. ``validate`` injectable for tests; nothing is irreversible until
    ``spawn`` launches the driver."""
    if not tasks:
        return SwapDispatchResult(
            ok=False, run_id=run_id,
            message="No approved tasks to dispatch — nothing was run.",
        )
    for task in tasks:
        err = validate(Path(str(task.get("repo", ""))), config.projects_dir)
        if err:
            return SwapDispatchResult(
                ok=False, run_id=run_id,
                message=f"Could not dispatch task '{task.get('task', '')}' — {err}.",
            )
    prepare_and_launch_swap(
        config, run_id=run_id, session_id=session_id, tasks=tasks,
        old_pid=old_pid, relaunch_argv=relaunch_argv, relaunch_cwd=relaunch_cwd,
        gate_gb=gate_gb, run_budget_s=run_budget_s, spawn=spawn,
    )
    return SwapDispatchResult(
        ok=True, run_id=run_id, tasks=list(tasks),
        message=(f"Dispatching {run_id} — {len(tasks)} task(s) to the coder fleet. I'll "
                 f"step aside for the 30B and be back when it's done; then check "
                 f"`/dispatch status {run_id}`."),
    )


def orchestrate_swap_dispatch(
    idea: str,
    repo: str,
    session_id: str,
    *,
    config: FleetDispatchConfig,
    generate_fn,
    gate_gb: float,
    old_pid: int,
    relaunch_argv: list[str],
    relaunch_cwd: str,
    run_budget_s: float = 0.0,
    validate=validate_repo,
    spawn=None,
    mint_run_id=new_run_id,
    max_tasks: int = DEFAULT_MAX_TASKS,
) -> SwapDispatchResult:
    """The combined DECOMPOSE-then-EXECUTE path (the increment-2 single-call form, kept
    for back-compat + tests). The live go-live flow SPLITS this: the gateway PLAN step
    decomposes (over the resident 14B) and the operator APPROVES the criteria; then EXECUTE
    runs the approved tasks via :func:`execute_swap_dispatch` — never re-decomposing, so the
    run matches what was approved. The CALLER steps the launcher aside ONLY after ``ok``.
    """
    decomposed = decompose_request(
        idea, repo, generate_fn=generate_fn,
        projects_dir=config.projects_dir, max_tasks=max_tasks,
    )
    if not decomposed.ok:
        return SwapDispatchResult(ok=False, message=decomposed.message)

    return execute_swap_dispatch(
        mint_run_id(), session_id, decomposed.tasks,
        config=config, gate_gb=gate_gb, old_pid=old_pid,
        relaunch_argv=relaunch_argv, relaunch_cwd=relaunch_cwd,
        run_budget_s=run_budget_s, validate=validate, spawn=spawn,
    )


def main(argv: "list[str] | None" = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="BlarAI model-swap driver (detached).")
    parser.add_argument("--spec", required=True)
    args = parser.parse_args(argv)
    run_swap(Path(args.spec))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
