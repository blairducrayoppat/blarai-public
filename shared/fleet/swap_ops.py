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
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

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
    read_acceptance_record,
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


def pending_run_budget_path(config: FleetDispatchConfig) -> Path:
    return swap_dir(config) / "pending-run-budget.json"


# Per-card run-budget override (#740 B3 re-grain, 2026-07-08). The battery runner
# and the AO are SEPARATE processes and the AO stays up across jobs, so a
# per-card budget reaches the AO's driver watchdog through this small
# CONSUME-ONCE file rather than a live-protocol change or a per-job reboot.
#: Freshness window: an override older than this is IGNORED (stale-file guard —
#: a runner that wrote a budget then never dispatched must not silently apply it
#: to a later job; era-rot class, lesson 195). The runner writes it moments
#: before each dispatch.
PENDING_RUN_BUDGET_FRESH_S: float = 300.0
#: Hard clamp on any per-card budget the AO will honor (a card cannot request an
#: unbounded run). 8 h covers the longest measured card (B3 ~6.5 h) with margin.
CARD_RUN_BUDGET_MAX_S: float = 28800.0


def write_pending_run_budget(config: FleetDispatchConfig, seconds: float) -> None:
    """Runner side: stage a per-card driver budget for the NEXT dispatch.

    Fail-soft: a write failure just means the AO uses its config default. A
    non-positive value CLEARS any prior override (so a default-budget card after
    a B3 can never inherit B3's window)."""
    import json
    import time

    path = pending_run_budget_path(config)
    try:
        if seconds and seconds > 0:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(path.suffix + ".tmp")
            tmp.write_text(
                json.dumps({"run_budget_s": float(seconds), "written_at": time.time()}),
                encoding="utf-8",
            )
            os.replace(tmp, path)
        else:
            path.unlink(missing_ok=True)
    except OSError:
        pass


def read_pending_run_budget(config: FleetDispatchConfig) -> float | None:
    """AO side: CONSUME (read + delete) a fresh per-card budget override, or None.

    Fail-closed to the config default: absent, unreadable, stale (> the freshness
    window), or non-positive all return None. Deletes on read so one override can
    never bleed into a second dispatch. Clamped to CARD_RUN_BUDGET_MAX_S."""
    import json
    import time

    try:
        path = pending_run_budget_path(config)
        raw = path.read_text(encoding="utf-8")
    except (OSError, AttributeError):
        return None
    # Consume-once: delete immediately, before honoring — a torn/hostile file
    # still cannot survive to a later dispatch.
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass
    try:
        data = json.loads(raw)
        seconds = float(data.get("run_budget_s", 0.0))
        written_at = float(data.get("written_at", 0.0))
    except (ValueError, TypeError, AttributeError):
        return None
    if seconds <= 0:
        return None
    if time.time() - written_at > PENDING_RUN_BUDGET_FRESH_S:
        return None  # stale: the dispatch it was written for never fired
    return min(seconds, CARD_RUN_BUDGET_MAX_S)


def status_path(config: FleetDispatchConfig, run_id: str) -> Path:
    return swap_dir(config) / f"SWAP_FAILED_{run_id}.txt"


# ---- real side-effecting ops (live) ---------------------------------------

#: CREATE_NO_WINDOW — for CONSOLE-SUBSYSTEM children (pwsh / tasklist) of the
#: console-less detached driver ONLY (#761). The driver is spawned via pythonw.exe
#: (GUI subsystem, no console), so every console-subsystem child would otherwise be
#: allocated a fresh VISIBLE console window — the accidental-close hazard of the
#: night-2 (2026-07-06 23:53) window-close incident class, multiplied per child.
#: These children are non-interactive by construction (``-NonInteractive`` pwsh,
#: stdin DEVNULL, output captured or file-redirected), so a hidden console is safe.
#: CONSTRAINT — NEVER apply this flag to a python/pythonw LAUNCHER spawn
#: (``restart_launcher`` / ``_spawn_detached_driver`` / battery
#: ``boot_launcher_detached``): a HIDDEN console is the exact shape that crashed
#: Textual on 2026-07-06 ("Driver must be in application mode"). The launcher chain
#: uses pythonw.exe (no console AT ALL -> Textual's proven headless-driver fallback)
#: instead — see :func:`pythonw_sibling`. Guarded to 0 off-Windows (creationflags
#: raises on POSIX; this module's live paths are Windows-only, its pure paths not).
_NO_WINDOW = 0x08000000 if os.name == "nt" else 0


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
            creationflags=_NO_WINDOW,  # console child of a console-less driver (#761)
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
            # #761: CREATE_NO_WINDOW — this pwsh child is a console-subsystem exe born
            # to the console-less (pythonw-spawned) driver; without the flag Windows
            # allocates it a fresh VISIBLE console. Safe: -NonInteractive, stdin
            # DEVNULL, output file-redirected (the 2026-07-06 Textual hidden-console
            # crash constraint applies only to python-launcher spawns, never pwsh).
            cp = run(
                cmd,
                stdin=subprocess.DEVNULL,
                stdout=fh,
                stderr=subprocess.STDOUT,
                close_fds=True,
                timeout=timeout_s,
                creationflags=_NO_WINDOW,
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
) -> "tuple[bool, bool]":
    """Run a LONG-LIVED subprocess (run-fleet) with stdout+stderr -> ``log_path`` (a real FILE,
    never a captured pipe — the #670 run-2 deadlock) + ``close_fds``, then wait. On TIMEOUT,
    TREE-KILL the whole subtree (``pwsh -> opencode -> playwright-msedge``) via the held ``Popen``
    handle (the PRIMARY wedge defense — reuse-proof for the direct child), NOT ``subprocess.run``'s
    direct-child-only kill that orphans grandchildren. ``on_spawn(proc)`` registers the live child
    with the budget-watchdog holder and ``on_spawn(None)`` deregisters on EVERY exit; when None the
    helper is a pure file-redirect tree-killable runner. Returns ``(ok, timed_out)`` —
    ``ok = (returncode == 0)``, fail-closed; ``timed_out`` is True ONLY for the tree-kill branch
    (#757: the kill must be REPORTED so the caller can label the outcome honestly, not swallowed
    into a generic False that reads like a normal failure). ``popen`` / ``terminate_tree``
    injected for tests."""
    if terminate_tree is None:
        from shared.fleet.proc_tree import terminate_process_tree
        terminate_tree = terminate_process_tree
    proc = None
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with open(log_path, "w", encoding="utf-8", errors="replace") as fh:
            # #761: CREATE_NO_WINDOW — same rationale as _run_to_logfile: run-fleet's
            # pwsh subtree is console-subsystem under a console-less driver, and a
            # LONG-LIVED visible console (hours) is the exact accidental-close hazard
            # this ticket closes. Non-interactive by construction; never a launcher.
            proc = popen(cmd, stdin=subprocess.DEVNULL, stdout=fh,
                         stderr=subprocess.STDOUT, close_fds=True,
                         creationflags=_NO_WINDOW)
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
                return False, True
        return rc == 0, False
    except OSError:
        return False, False
    except Exception:  # noqa: BLE001 — fail-closed: any error is a task failure
        return False, False
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


#: start-llm.ps1 load ceiling — BOTH model loads (the 30B and the 14B critic swap).
#: 480s (not 300): #747 — a COLD compile-cache load measured ~289s live (compile + writing
#: ~15 GB of .cl_cache); start-llm's own deadline was bumped to 480 to match. A WARM load is
#: ~12s, far under this; the ceiling only bites cold (first install / OVMS upgrade). The
#: never-zero teardown restores the 14B if a load ever genuinely hangs to the ceiling.
#: Registered: shared/timeout_registry.py (#767 item 2 — the literal named as a constant).
START_LLM_TIMEOUT_S = 480.0


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
    return _run_to_logfile(cmd, log_path=base / "start-llm.log",
                           timeout_s=START_LLM_TIMEOUT_S)


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
    return _run_to_logfile(cmd, log_path=base / "start-14b.log",
                           timeout_s=START_LLM_TIMEOUT_S)  # #747 cold-cache headroom (see the constant)


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


#: One capture+critique design pass ceiling (#688 Phase 3; design value, never bitten) —
#: bounds the pwsh ``Invoke-CritiquePass`` subprocess (headless capture + in-process VLM
#: critique). The design phase is fail-soft/best-effort: expiry degrades to the no-op
#: fallback and can never block the driver's teardown.
#: Registered: shared/timeout_registry.py (#767 item 2 — the literal named as a constant).
DESIGN_LOOP_TIMEOUT_S = 180.0


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
        ok = _run_to_logfile(cmd, log_path=log_path, timeout_s=DESIGN_LOOP_TIMEOUT_S)
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


#: One 14B cross-model critic pass ceiling (#687 task 2; design value ~10 min, never
#: bitten) — bounds ``critic-run.ps1`` (a full-diff review on the just-swapped-in 14B).
#: Fail-soft: expiry returns the critic fallback, never raises, and can NEVER block the
#: driver's teardown or the 14B restore (#687 task 2 NEVER-ZERO).
#: Registered: shared/timeout_registry.py (#767 item 2 — the literal named as a constant).
CRITIC_RUN_TIMEOUT_S = 600.0


def real_run_critic(
    config: FleetDispatchConfig,
    run_id: str,
    app_dir: str,
    base_branch: str,
    base_sha: str = "",
) -> dict:
    """Load the 14B and run ONE critic pass over the merged diff (#687 task 2).

    Sequence: ``start-llm.ps1 -Model qwen3-14b -Force`` (swaps from 30B to 14B) +
    ``real_wait_ready`` (belt-and-suspenders port check), then ``critic-run.ps1`` via
    :func:`_run_to_logfile` (NOT a captured pipe — avoids the #670 run-2 grandchild deadlock);
    parse the VERDICT from the logfile.

    ``base_sha`` (#693): main's pre-dispatch HEAD, recorded by the driver before the repo's
    first task ran. Non-empty -> passed as ``-BaseRef`` so the script diffs ``<base>..HEAD``
    (ALL the merged work, robust to a multi-commit fast-forward); empty -> omitted and the
    script's ``Resolve-CriticRange`` fallback applies (the pre-#693 behavior).

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
        if base_sha:
            cmd += ["-BaseRef", base_sha]
        base = (config.runs_dir / run_id) if run_id else config.runs_dir
        log_path = base / "critic-run.log"
        ok = _run_to_logfile(cmd, log_path=log_path, timeout_s=CRITIC_RUN_TIMEOUT_S)
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


# ---- M2 plan-graph live ops (W3-W6, #740) ----------------------------------


_HEX_REF_RE = None  # lazily-compiled in real_dep_delta (keeps module import light)

#: File extensions the as-built signature extractor reads (context_pack dispatch set).
_DELTA_SOURCE_SUFFIXES = (".py", ".mjs", ".js")
#: Per-file read ceiling for signature extraction (a generated source file beyond this
#: is documentation-scale; its signatures are not worth the read).
_DELTA_MAX_FILE_BYTES = 262_144


def real_repo_head(repo: str) -> str:
    """``git rev-parse HEAD`` of *repo* ('' when unreadable) — brackets a task's merge
    for the W3 as-built delta. Bounded + fail-soft (a pack degrades to contract-only)."""
    ok, out, _err = _safe_run(["git", "-C", str(repo), "rev-parse", "HEAD"], 15.0)
    head = (out or "").strip()
    return head if ok and head else ""


def real_dep_delta(repo: str, base_ref: str, merge_ref: str) -> dict:
    """The W3 as-built delta: ``git diff --name-only base..merge`` + STRUCTURAL
    signature extraction (``context_pack.extract_signatures`` — Python ast / mjs
    export-line regex; never comments, docstrings, or bodies — §10 S2/N6).

    The refs come from our own ``real_repo_head`` reads, but are re-validated as hex
    anyway (defense-in-depth: nothing that is not a commit hash reaches the git argv).
    Fail-soft ``{}`` on any error — the pack then carries the contract alone."""
    import re as _re

    from shared.fleet import context_pack as _cp

    global _HEX_REF_RE
    if _HEX_REF_RE is None:
        _HEX_REF_RE = _re.compile(r"\A[0-9a-f]{4,40}\Z")
    try:
        base = str(base_ref or "").strip().lower()
        merge = str(merge_ref or "").strip().lower()
        if not _HEX_REF_RE.match(base) or not _HEX_REF_RE.match(merge) or base == merge:
            return {}
        ok, out, _err = _safe_run(
            ["git", "-C", str(repo), "diff", "--name-only", f"{base}..{merge}"], 30.0)
        if not ok:
            return {}
        files = [ln.strip() for ln in (out or "").splitlines() if ln.strip()][:24]
        signatures: list[str] = []
        for rel in files:
            if not rel.lower().endswith(_DELTA_SOURCE_SUFFIXES):
                continue
            path = Path(repo) / rel
            try:
                if not path.is_file() or path.stat().st_size > _DELTA_MAX_FILE_BYTES:
                    continue
                source = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            signatures.extend(_cp.extract_signatures(rel, source))
            if len(signatures) >= 48:
                break
        return {"files": files, "signatures": signatures[:48]}
    except Exception:  # noqa: BLE001 — fail-soft: a delta failure degrades the pack only
        return {}


def context_packs_log_path(config: FleetDispatchConfig, run_id: str) -> Path:
    return config.runs_dir / run_id / "context-packs.log"


def real_log_pack(config: FleetDispatchConfig, run_id: str, task_id: str, pack: str) -> None:
    """Append one task's context pack VERBATIM to the run's pack audit log (plan §4.4 —
    every pack logged for auditability; the §10 S2 review surface). Fail-soft."""
    try:
        path = context_packs_log_path(config, run_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(f"=== context pack: {task_id} ===\n{pack}\n\n")
    except OSError:
        pass


def _parse_verify_overall(text: str) -> str:
    """Pull ``overall`` from verify-project.ps1's ``-Json`` output (scan lines in
    reverse for a JSON object carrying it — robust to leading progress noise).
    ``'none'`` when unparseable (could-not-run, never a fail)."""
    for raw in reversed((text or "").splitlines()):
        line = raw.strip()
        if not (line.startswith("{") and line.endswith("}")):
            continue
        try:
            data = json.loads(line)
        except (ValueError, TypeError):
            continue
        if isinstance(data, dict) and "overall" in data:
            return str(data.get("overall", "none") or "none").strip().lower()
    # verify-project -Json may pretty-print; fall back to a whole-body parse.
    try:
        data = json.loads(text)
        if isinstance(data, dict) and "overall" in data:
            return str(data.get("overall", "none") or "none").strip().lower()
    except (ValueError, TypeError):
        pass
    return "none"


def _evidence_tail(text: str, cap: int = 400) -> str:
    """A structural, capped tail of gate/oracle output for evidence lines (§10 S3)."""
    flat = " ".join(str(text or "").split())
    return flat[-cap:] if len(flat) > cap else flat


def real_run_wave_gate(
    config: FleetDispatchConfig,
    run_id: str,
    repo: str,
    *,
    surface: str = "",
    language_hint: str = "",
    run=_safe_run,
) -> dict:
    """W4 wave gate: the deterministic verify gate + the full test suite on the
    INTEGRATED target-repo main (never a worktree) — the same two signals the per-task
    fleet gate reads, invoked the same way (``verify-project.ps1 -Path <repo> -Json``
    + ``pytest``/``npm test`` in the repo).

    Honesty contract: ``ok=False`` ONLY on an explicit failure (verify ``fail`` or a
    failing test run); ``ok=None`` when NEITHER signal could run (could-not-run — the
    caller records the wave UNVERIFIED, mirroring the fleet's non-blocking ``none``
    posture); ``ok=True`` when at least one signal ran and none failed. Repo paths ride
    argv / ``cwd`` only — never a shell string (§10 S1). Fail-soft on every error."""
    try:
        from shared.fleet.acceptance import detect_ecosystem

        verify = "none"
        verify_tail = ""
        script = config.scripts_dir / "verify-project.ps1"
        if script.is_file():
            cmd = [_pwsh(), "-NoProfile", "-NonInteractive", "-File", str(script),
                   "-Path", str(repo), "-Json", "-TimeoutSec", "600"]
            if surface:
                cmd += ["-Surface", str(surface)]
            if language_hint:
                cmd += ["-LanguageHint", str(language_hint)]
            _ok, out, err = run(cmd, 660.0)
            verify = _parse_verify_overall(out)
            if verify == "fail":
                verify_tail = _evidence_tail(out + "\n" + err)

        tests = "none"
        tests_tail = ""
        eco = detect_ecosystem(Path(repo))
        if eco == "python":
            uv = shutil.which("uv")
            if uv:
                ok_t, out_t, err_t = run(
                    [uv, "run", "--no-project", "--with", "pytest==9.1.1",
                     "--with", "hypothesis==6.155.7", "pytest", "-x", "-q"],
                    600.0, str(repo))
                tests = "pass" if ok_t else "fail"
                if not ok_t:
                    tests_tail = _evidence_tail(out_t + "\n" + err_t)
        elif eco == "node":
            # A constant literal command — no data ever enters the string; the repo
            # rides cwd. (npm is a .cmd shim on Windows; pwsh hosts it, argv-safe.)
            ok_t, out_t, err_t = run(
                [_pwsh(), "-NoProfile", "-NonInteractive", "-Command", "npm test"],
                600.0, str(repo))
            tests = "pass" if ok_t else "fail"
            if not ok_t:
                tests_tail = _evidence_tail(out_t + "\n" + err_t)

        if verify == "fail" or tests == "fail":
            ok_flag: "bool | None" = False
        elif verify == "none" and tests == "none":
            ok_flag = None
        else:
            ok_flag = True
        evidence = f"verify={verify}; tests={tests} ({eco})"
        fail_tail = verify_tail or tests_tail
        if fail_tail:
            evidence += f" | {fail_tail}"
        # Append to the run's wave-gate audit log (best-effort).
        try:
            log = config.runs_dir / run_id / "wave-gates.log"
            log.parent.mkdir(parents=True, exist_ok=True)
            with log.open("a", encoding="utf-8") as fh:
                fh.write(f"repo={repo} :: {evidence}\n")
        except OSError:
            pass
        return {"ok": ok_flag, "evidence": evidence}
    except Exception as exc:  # noqa: BLE001 — gate machinery failure is could-not-run
        return {"ok": None, "evidence": f"wave gate could not run: {type(exc).__name__}"}


#: Module-level skip guard prepended to the SEEDED copy of the job oracle (#748 run
#: 20260705-214803-bd). The seeded file exists so the coder CODES TOWARD the job
#: spec (plan §4.5 — the proven #690 per-task mechanic at job level), but it must
#: not execute in per-task/wave gates (early waves legitimately do not satisfy it
#: yet). Grade time is unaffected: ``real_run_job_oracle`` overwrites with the
#: UNWRAPPED plan bytes before grading (plan bytes ALWAYS win), then restores this
#: guarded copy — so the guard never needs an env sentinel or a gate exclusion.
_SEED_SKIP_GUARD = (
    "# Job-level acceptance oracle - graded on the FINAL integrated tree only.\n"
    "# This copy skips in per-task/wave gates; the grader runs the plan-carried\n"
    "# original. Do NOT edit this file - it is restored before grading.\n"
    "import pytest as _pytest_seed_guard\n"
    '_pytest_seed_guard.skip("job-level oracle - graded on the final integrated tree",'
    " allow_module_level=True)\n\n"
)

#: Node seed guard header (#740) — the ``.mjs`` equivalent of :data:`_SEED_SKIP_GUARD`,
#: with one structural difference forced by the language: static ESM imports are
#: HOISTED — module *linking* resolves every ``import`` before ANY body statement
#: runs, so a top-of-file ``process.exit(0)`` can never beat an import of a
#: not-yet-built module (proven live on node v24: ``ERR_MODULE_NOT_FOUND`` at link
#: time, the file fails, exit 1). The seeded node copy therefore contains NO
#: executable oracle statement at all: its only static import is the
#: always-resolvable ``node:test`` builtin, it registers ONE explicitly-SKIPPED test
#: (``node --test`` reports ``skipped 1`` / exit 0 in file-arg, discovery, and bare
#: ``node`` invocations — the ``pytest.skip`` mirror), and the oracle body follows
#: LINE-COMMENTED via :func:`_seed_guard_wrap_node` — still the readable job spec
#: the coder codes toward (its commented imports state the required module layout),
#: but inert by construction. ``// `` per line, never a ``/* */`` block: common
#: oracle content (``/a*/`` regexes, ``'src/**/*.mjs'`` globs) contains ``*/`` and
#: would terminate a block comment early. Grade time is unaffected:
#: ``real_run_job_oracle`` overwrites with the UNWRAPPED plan bytes before grading
#: (plan bytes ALWAYS win), then restores this guarded copy — so the guard never
#: needs an env sentinel or a gate exclusion (same contract as the python guard).
_SEED_SKIP_GUARD_NODE = (
    "// Job-level acceptance oracle - graded on the FINAL integrated tree only.\n"
    "// This SEEDED copy is inert in per-task/wave gates: the oracle body below is\n"
    "// line-commented (a hoisted static import of a not-yet-built module can never\n"
    "// execute) and the single registered test SKIPS. The grader replaces this\n"
    "// whole file with the plan-carried original before running it.\n"
    "// Do NOT edit this file - it is restored before grading.\n"
    "import { test as __blarai_seed_skip } from 'node:test';\n"
    "__blarai_seed_skip(\n"
    "  'job-level acceptance oracle (seeded copy - graded on the final integrated"
    " tree)',\n"
    "  { skip: 'seeded oracle: graded on the final integrated tree only' },\n"
    "  () => {},\n"
    ");\n"
    "// ---- seeded oracle spec below (READ it: the imports define the required\n"
    "// ---- module layout the FINAL integrated app must satisfy) ----\n"
)


def _seed_guard_wrap_node(oracle_code: str) -> str:
    """The guarded node seed: :data:`_SEED_SKIP_GUARD_NODE` + the oracle body with
    EVERY line ``// ``-prefixed. Deterministic (idempotence compares exact bytes);
    content-safe for arbitrary plan-generated JS (a line comment ends only at a
    newline, and the split guarantees none survives inside a line)."""
    body = "\n".join("// " + line for line in oracle_code.splitlines())
    return _SEED_SKIP_GUARD_NODE + body + "\n"


def real_seed_job_oracle(
    config: FleetDispatchConfig,
    run_id: str,
    repo: str,
    rel_path: str,
    oracle_code: str,
    *,
    run=_safe_run,
) -> dict:
    """Seed the job oracle INTO the target repo before wave 1 (#748): write the
    guard-wrapped oracle at the pinned path and COMMIT it, so every task worktree
    (branched from main) carries the job spec the coder must code toward. Without
    this the oracle grades a module layout nobody ever promised the coder — the
    run-4 live failure (`from commands.add import ...` vs the as-built root files).

    Containment mirrors ``real_run_job_oracle``: pinned paths only. The seed guard
    is per-ecosystem — ``.py`` gets the module-level ``pytest.skip`` prologue
    (:data:`_SEED_SKIP_GUARD`; python executes top-to-bottom, so the skip fires
    before any oracle import), ``.mjs`` gets the hoisting-proof ``node:test``
    skip wrapper (:func:`_seed_guard_wrap_node`; static ESM imports resolve
    before ANY body statement, so the seeded copy carries the oracle body
    line-commented instead — see :data:`_SEED_SKIP_GUARD_NODE`). A pinned path
    with no designed guard is refused fail-closed, never seeded unguarded.
    Fail-soft: any refusal/failure returns ``ok=False`` and the run proceeds
    exactly as before seeding existed (the oracle still grades at the end)."""
    from shared.fleet.acceptance import JOB_ORACLE_ALLOWED_PATHS

    if not oracle_code:
        return {"ok": False, "evidence": "no job oracle was generated at plan time"}
    if rel_path not in JOB_ORACLE_ALLOWED_PATHS:
        return {"ok": False,
                "evidence": f"refused oracle path {rel_path!r} (not a pinned oracle path)"}
    if rel_path.endswith(".py"):
        seeded = _SEED_SKIP_GUARD + oracle_code
    elif rel_path.endswith(".mjs"):
        seeded = _seed_guard_wrap_node(oracle_code)
    else:
        # Defense-in-depth: JOB_ORACLE_ALLOWED_PATHS carries only .py/.mjs today,
        # but a future pinned path with an undesigned guard must refuse — an
        # UNGUARDED seed would execute (and fail) in every per-task/wave gate.
        return {"ok": False,
                "evidence": f"no seed guard designed for {rel_path!r} — not seeded"}
    try:
        target = Path(repo) / rel_path
        if target.is_file() and target.read_text(encoding="utf-8") == seeded:
            return {"ok": True, "evidence": "already seeded"}
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(seeded, encoding="utf-8")
        git = shutil.which("git")
        if not git:
            return {"ok": False, "evidence": "git unavailable — oracle written but not committed"}
        ok_a, out_a, err_a = run([git, "add", "--", rel_path], 60.0, str(repo))
        if not ok_a:
            return {"ok": False,
                    "evidence": f"git add failed; {_evidence_tail(out_a + chr(10) + err_a)}"}
        ok_c, out_c, err_c = run(
            [git, "commit", "-m",
             "chore(m2): seed protected job-level acceptance oracle (#740)"],
            60.0, str(repo))
        if not ok_c:
            combined = out_c + "\n" + err_c
            if "nothing to commit" in combined.lower():
                return {"ok": True, "evidence": "already committed"}
            return {"ok": False,
                    "evidence": f"git commit failed; {_evidence_tail(combined)}"}
        return {"ok": True, "evidence": f"seeded + committed {rel_path}"}
    except Exception as exc:  # noqa: BLE001 — seeding failure must never block the run
        return {"ok": False, "evidence": f"seeding failed: {type(exc).__name__}"}


def real_run_job_oracle(
    config: FleetDispatchConfig,
    run_id: str,
    repo: str,
    rel_path: str,
    oracle_code: str,
    *,
    run=_safe_run,
) -> dict:
    """W4 job oracle on the FINAL INTEGRATED tree, restore-before-grade (#690 posture):

      1. containment: *rel_path* must be one of the PINNED oracle paths (a tampered
         plan/swap-state cannot aim the write — §10 S1) and *oracle_code* non-empty;
      2. restore-before-grade: the PLAN-CARRIED bytes are written over whatever is on
         disk at that path (a merged edit to the oracle can never help), with the
         prior disk state captured;
      3. grade: ``pytest <path>`` (via the fleet's proven ``uv`` invocation) or
         ``node --test <path>`` by extension, cwd=repo (argv-only);
      4. restore: the prior disk state is put back (or the file removed if absent
         before), so the operator's tree is left exactly as the merges made it — the
         run dir keeps the audit copy + the outcome.

    Returns ``{"status": "passed"|"failed"|"not-run", "evidence": str}``; every
    machinery failure is an honest ``not-run`` (never an implied pass)."""
    from shared.fleet.acceptance import JOB_ORACLE_ALLOWED_PATHS

    if not oracle_code:
        return {"status": "not-run", "evidence": "no job oracle was generated at plan time"}
    if rel_path not in JOB_ORACLE_ALLOWED_PATHS:
        return {"status": "not-run",
                "evidence": f"refused oracle path {rel_path!r} (not a pinned oracle path)"}
    target = Path(repo) / rel_path
    prior: "bytes | None" = None
    try:
        # Audit copy first (survives whatever happens to the working tree).
        try:
            audit = config.runs_dir / run_id / f"job-oracle-{Path(rel_path).name}"
            audit.parent.mkdir(parents=True, exist_ok=True)
            audit.write_text(oracle_code, encoding="utf-8")
        except OSError:
            pass
        try:
            if target.is_file():
                prior = target.read_bytes()
        except OSError:
            prior = None
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(oracle_code, encoding="utf-8")   # plan bytes ALWAYS win
        if rel_path.endswith(".py"):
            uv = shutil.which("uv")
            if not uv:
                return {"status": "not-run", "evidence": "uv unavailable — oracle not run"}
            # `python -m pytest`, NEVER the bare `pytest` CLI (#748 live-verify run
            # 20260705-214803-bd): the oracle lives in tests/ and imports the built
            # modules from the repo ROOT (`from main import main`). Bare pytest does
            # not put the CWD on sys.path, so collection died with
            # ModuleNotFoundError on a CORRECT build — an every-job VERIFY-harness
            # false-red. `-m pytest` inserts the CWD (the integrated repo root).
            # Versions pinned to the provisioned GUEST venv (pytest 9.1.1 /
            # hypothesis 6.155.7, pure wheels) so host and guest oracles grade
            # with identical runners — un-pinned, uv resolved fresh per run
            # (pytest 8-or-9 by interpreter, hypothesis drifting), a
            # non-deterministic grader and a fake-DIVERGENCE manufacturer for
            # the #744 agreement matrix.  Change only with a matching guest
            # re-provisioning ceremony (#744 c.1526).
            cmd = [uv, "run", "--no-project", "--with", "pytest==9.1.1",
                   "--with", "hypothesis==6.155.7",
                   "python", "-m", "pytest", "-q", rel_path]
        else:
            node = shutil.which("node")
            if not node:
                return {"status": "not-run", "evidence": "node unavailable — oracle not run"}
            cmd = [node, "--test", rel_path]
        ok, out, err = run(cmd, 600.0, str(repo))
        status = "passed" if ok else "failed"
        return {"status": status,
                "evidence": f"{'exit 0' if ok else 'nonzero exit'}; {_evidence_tail(out + chr(10) + err)}"}
    except Exception as exc:  # noqa: BLE001 — machinery failure is an honest not-run
        return {"status": "not-run", "evidence": f"job oracle could not run: {type(exc).__name__}"}
    finally:
        # Restore the tree exactly as the merges left it (best-effort, fail-soft).
        try:
            if prior is not None:
                target.write_bytes(prior)
            else:
                target.unlink(missing_ok=True)
        except OSError:
            pass


#: #744 go-live: the guest oracle service's vsock port. 50002 = 0xC352 (hv_sock
#: GUID 0000c352-facb-11e6-bd58-64006a7986d3, host-registered at the ceremony);
#: the guest PARSER owns 50001. A lock pins this equal to the guest service's
#: own DEFAULT_ORACLE_PORT so the two sides can never silently diverge.
GUEST_ORACLE_VSOCK_PORT: int = 50002


# --- #744 c.1565 sequential ensure-start VM controls (LESSON 224 side-effect scoping) ---
# The oracle probe needs the NIC-less orchestrator guest VM UP, but the nightly
# battery reboots the AO between jobs and each launcher-exit stops the guest
# (policy=always), so by this teardown RAM-free probe window the guest is DOWN and
# the probe reported ``not-run: guest-unreachable`` every night. These thin wrappers
# REUSE the launcher's existing VM-lifecycle primitives (``launcher.vm_manager`` —
# the SAME ``ensure_vm_running``/``stop_vm`` the launcher itself calls; no Hyper-V is
# reimplemented here), imported LAZILY so swap_ops stays importable in the guest/host
# contexts that never touch Hyper-V, and INJECTABLE into ``real_run_guest_oracle`` so
# no test ever starts or stops the real VM. The fail-soft try/except lives at the one
# call site, so an injected double that raises is handled identically to the real
# primitive returning False.

def _default_guest_vm_running() -> bool:
    """True iff the orchestrator guest VM is already in the Running state — the
    signal that lets the oracle path leave an already-up guest exactly as it found
    it (only a guest WE start is stopped again; LESSON 224 side-effect scoping)."""
    from launcher.vm_manager import VMState, get_vm_state
    return get_vm_state() == VMState.RUNNING


def _default_ensure_guest_running() -> bool:
    """Ensure-start the orchestrator guest VM for the oracle probe — reuses the
    launcher's fail-closed :func:`launcher.vm_manager.ensure_vm_running` (True iff
    the guest is Running)."""
    from launcher.vm_manager import ensure_vm_running
    return bool(ensure_vm_running())


def _default_stop_guest() -> bool:
    """Stop the orchestrator guest VM again after the probe — reuses the launcher's
    :func:`launcher.vm_manager.stop_vm` so the guest footprint returns to ZERO
    outside the probe window."""
    from launcher.vm_manager import stop_vm
    return bool(stop_vm())


def real_run_guest_oracle(
    config: FleetDispatchConfig,
    run_id: str,
    repo: str,
    rel_path: str,
    oracle_code: str,
    *,
    guest_vm_running: "Callable[[], bool]" = _default_guest_vm_running,
    ensure_guest_running: "Callable[[], bool]" = _default_ensure_guest_running,
    stop_guest: "Callable[[], bool]" = _default_stop_guest,
) -> dict:
    """#744: the live guest-oracle executor — the host pipeline over the SAME
    plan-carried oracle bytes the host gate grades (snapshot → overlay → offline
    dep scan → deterministic zip), shipped to the NIC-less guest over AF_HYPERV
    and re-run there with real pytest.

    GO-LIVE (LA-supervised ceremony, 2026-07-08 — the #744 c.1445 one-line
    registration, consciously amending the former structural-dormancy locks):
    the transport factory is REGISTERED here, targeting the ``blarai-oracle``
    guest service on vsock port **50002** (the parser owns 50001; provisioning
    record: docs/security/guest_oracle_provisioning_record.md). Live-proven at
    the ceremony BEFORE this line was written: reachable probe + a passed AND
    a failed round-trip through the real bridge, guest, and pytest.

    #744 c.1565 SEQUENTIAL ensure-start: this probe fires in the teardown RAM-free
    window (14B/30B unloaded) where the battery's between-jobs AO reboots have left
    the guest VM DOWN — so the probe used to report ``guest-unreachable`` every
    night. Bring the guest UP here, probe, then RESTORE its prior footprint so it
    never competes with the 30B during code phases (the parallelism optimisation —
    overlapping VM boot with the 30B unload — is a SEPARATE follow-up, #744 c.1566).
    Side-effect scoping (LESSON 224): a guest that was ALREADY running is left
    running; only one WE start is stopped again.

    Fail-soft at every layer AND INVARIANT: an ensure-start failure (or any
    guest-unreachable condition) degrades to an honest ``not-run`` — NEVER a
    blocked restore, NEVER a verdict change; the guest-stop is still attempted
    (fail-soft); a factory failure (missing 3.14 bridge, bad config) degrades to
    ``transport=None``; the returned callable itself never raises; the driver's
    ``_guard`` wraps the phase."""
    from shared.fleet.guest_oracle import run_guest_oracle
    from shared.fleet.guest_oracle_transport import (
        BridgeUnavailableError,
        GuestOracleTransportError,
        make_guest_oracle_transport,
    )

    # Record the prior footprint BEFORE touching the VM: only a guest we start is
    # stopped again (an unreadable state is treated as "not running" — fail-soft).
    try:
        was_running = bool(guest_vm_running())
    except Exception:  # noqa: BLE001 — an unreadable VM state is treated as "not running"
        was_running = False

    try:
        try:
            started = bool(ensure_guest_running())
        except Exception:  # noqa: BLE001 — ensure-start failure is an honest not-run
            started = False
        if not started:
            write_swap_progress(
                config, run_id,
                "Guest oracle: the guest VM could not be started for the probe — "
                "certificate not-run this job (advisory; verdict unchanged)",
            )
            return {
                "status": "not-run",
                "reason": "guest-unreachable",
                "evidence": "the guest VM could not be started for the oracle probe",
            }

        try:
            transport = make_guest_oracle_transport(vsock_port=GUEST_ORACLE_VSOCK_PORT)
        except (BridgeUnavailableError, GuestOracleTransportError, OSError) as exc:
            write_swap_progress(
                config, run_id,
                f"Guest oracle transport unavailable ({type(exc).__name__}) — "
                "certificate not-run this job",
            )
            transport = None
        result = run_guest_oracle(repo, rel_path, oracle_code, transport=transport)
        write_swap_progress(
            config, run_id,
            f"Guest oracle pipeline: {result.get('status', 'not-run')}"
            + (f" ({result.get('reason')})" if result.get("reason") else ""),
        )
        return result
    finally:
        # RESTORE the guest footprint to ZERO outside this probe window. ALWAYS
        # attempted (even after an ensure-start failure — ensure_vm_running may have
        # left the guest mid-Start), but ONLY for a guest we started; fail-soft — a
        # stop failure must NEVER derail the swap teardown or touch the verdict.
        if not was_running:
            try:
                stop_guest()
            except Exception:  # noqa: BLE001 — stop failure must never derail the swap
                pass


def guest_oracle_evidence_path(config: FleetDispatchConfig, run_id: str) -> Path:
    """The advisory guest-oracle certificate block for a run (#744) — beside
    scorecard.json; a SEPARATE artifact so the pinned, battery-adopted scorecard
    schema is untouched."""
    return config.runs_dir / run_id / "guest-oracle.json"


def real_write_guest_oracle(config: FleetDispatchConfig, run_id: str, block: dict) -> None:
    """Persist the advisory guest-oracle evidence block (#744). Fail-soft."""
    try:
        path = guest_oracle_evidence_path(config, run_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(block, indent=2), encoding="utf-8")
    except (OSError, TypeError, ValueError):
        pass


def scorecard_path(config: FleetDispatchConfig, run_id: str) -> Path:
    return config.runs_dir / run_id / "scorecard.json"


def real_write_scorecard(config: FleetDispatchConfig, run_id: str, scorecard: dict) -> None:
    """Persist the machine-readable job scorecard (W6, plan §4.3/§9.4), enriching the
    evidence POINTERS with this run's artifact paths (pointers, never raw logs — the
    §10 S6 structural rule). Fail-soft."""
    try:
        sc = dict(scorecard)
        ev = dict(sc.get("evidence") or {})
        ev.setdefault("summary", str(config.runs_dir / run_id / "SUMMARY.txt"))
        ev.setdefault("job_summary", str(job_summary_path(config, run_id)))
        ev.setdefault("progress", str(swap_progress_path(config, run_id)))
        ev.setdefault("packs", str(context_packs_log_path(config, run_id)))
        sc["evidence"] = ev
        path = scorecard_path(config, run_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(sc, indent=2), encoding="utf-8")
    except (OSError, TypeError, ValueError):
        pass


def job_summary_path(config: FleetDispatchConfig, run_id: str) -> Path:
    return config.runs_dir / run_id / "JOB_SUMMARY.txt"


def real_write_job_summary(config: FleetDispatchConfig, run_id: str, text: str) -> None:
    """Persist the human JOB_SUMMARY (W6) next to SUMMARY.txt. Fail-soft."""
    try:
        path = job_summary_path(config, run_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    except OSError:
        pass


def write_single_task_queue(config: FleetDispatchConfig, task: dict) -> Path:
    """Write a one-task queue file for a per-task run-fleet invocation (cancel granularity)."""
    qpath = swap_dir(config) / "task-queue.json"
    qpath.parent.mkdir(parents=True, exist_ok=True)
    qpath.write_text(json.dumps([task], indent=2), encoding="utf-8")
    return qpath


#: Per-task run-fleet ceiling (#757). Must DOMINATE run-fleet's legitimate single-task worst
#: case (up to 3 candidates x MaxRunMinutes=60 + reviews + merge/gate overhead ~= 3.5 h) so it
#: never clips honest work: the night-2 value (3600 s) EQUALLED one candidate's budget — zero
#: headroom — though the actual B4/B6 killer was the overall-run budget. This ceiling is the
#: wedge backstop for the budget-disabled path; whenever ``swap_run_budget_s`` is set, the
#: budget watchdog is the binding bound, and run-fleet's own idle-detection (#682) is the fast
#: kill for a stuck coder.
TASK_TIMEOUT_S = 14400.0


def real_run_task(config: FleetDispatchConfig, run_id: str, task: dict, *, on_spawn=None) -> TaskOutcome:
    """Run ONE task via run-fleet (shared -RunId accumulates done.txt), parse its outcome.

    #670 P2: run-fleet is a LONG-LIVED subtree (``pwsh -> opencode -> playwright-msedge``); it
    MUST NOT use the capture-pipe ``_safe_run`` (a grandchild inherits the pipe on Windows and
    deadlocks the wait past the per-task timeout — the CODE wedge that left the 30B resident).
    Redirect to a per-run-per-task LOG FILE via :func:`_run_to_logfile_tree` (no inheritable pipe;
    tree-kill on timeout). We parse SUMMARY.txt from disk, so dropping captured stdout costs
    nothing. ``on_spawn`` (ONLY the live run-task path passes a real one) hands the child to the
    budget watchdog; ``real_load_30b`` MUST pass None (start-llm is OVMS's parent — registering
    its child would let the budget abort tree-kill OVMS).

    #757: a tree-killed task yields an EXPLICIT timeout outcome. The old fall-through ("no
    SUMMARY line for this task") wore the parser's clothes and cost night-2 a full diagnostic
    cycle; a parsed SUMMARY line still wins (a result that raced the kill is real work)."""
    qpath = write_single_task_queue(config, task)
    script = config.scripts_dir / "run-fleet.ps1"
    name = str(task.get("task", ""))
    log_path = config.runs_dir / run_id / f"run-fleet-{slugify_task(name)}.log"
    _ok, timed_out = _run_to_logfile_tree(
        [_pwsh(), "-NoProfile", "-NonInteractive", "-File", str(script),
         "-Queue", str(qpath), "-RunId", run_id],
        log_path=log_path, timeout_s=TASK_TIMEOUT_S, on_spawn=on_spawn,
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
    if timed_out:
        return TaskOutcome(
            task=name, outcome="timeout", result="TIMEOUT",
            detail=(f"RESULT: TIMED OUT - per-task ceiling ({int(TASK_TIMEOUT_S)}s) elapsed; "
                    "run-fleet was tree-killed before it wrote a SUMMARY line"))
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


def _try_connect(port: int, timeout_s: float = 2.0) -> bool:
    """One loopback TCP connect attempt to *port* — True iff it is accepted. The
    air-gap import control forbids a runtime HTTP client, so liveness is socket-only."""
    import socket

    try:
        with socket.create_connection(("127.0.0.1", port), timeout=timeout_s):
            return True
    except OSError:
        return False


def real_backend_ready(port: int = 5001, timeout_s: float = 180.0,
                       poll_s: float = 3.0, sleep=None,
                       *, stable_polls: int = 3, stable_gap_s: float = 2.0,
                       launcher_alive=None, observe=None) -> bool:
    """Confirm the relaunched AO is SERVING and STAYS serving on :port — #750 fix 1.

    Readiness is "the new backend is actually up", not "the relaunch command returned"
    (design §2.3): the fresh launcher must cold-load the 14B before the AO listens, so
    we poll up to *timeout_s*. The night-1 false-positive (#750): a bare single
    ``socket.create_connection`` returned True for a launcher that bound :5001 in the
    single-instance-lock race (lesson 209), got connected-to, then EXITED — so the swap
    driver honestly-but-wrongly logged "14B is back" over a dead AO, and every later
    battery job STALLED. Two hardenings close it:

      * **STABILITY** — readiness requires ``stable_polls`` consecutive accepted
        connections ``stable_gap_s`` apart, not one. A bind-then-die listener passes the
        first connect and fails the follow-ups.
      * **LAUNCHER-ALIVE** — ``launcher_alive()`` (wired live to ``relaunch_in_flight``:
        is the spawned ``python -m launcher`` still running?) is checked before and through
        the wait. If the launcher PROCESS died, readiness aborts FAST and returns False, so
        the driver's retry spawns a fresh launcher instead of trusting a lingering socket.

    ``observe(dict)`` (optional) records what each probe saw — the residency evidence that
    5+ sequential swap-backs produce zero false-readies. Back-compat: the defaults
    (``launcher_alive`` -> always-alive, no observer) keep a patient poll plus the new
    stability requirement; the LIVE wiring passes the real ``relaunch_in_flight`` and a
    progress-log observer."""
    import time

    sleep = sleep or time.sleep
    alive = launcher_alive or (lambda: True)
    stable_polls = max(1, int(stable_polls))
    waited = 0.0
    while waited < timeout_s:
        if not alive():
            if observe:
                observe({"event": "launcher-died", "waited_s": round(waited, 1)})
            return False   # the spawned launcher exited -> retry spawns fresh, no lingering-socket trust
        if _try_connect(port):
            # First accept — now prove it STAYS up (and the launcher stays alive) across
            # stable_polls checks. A bind-then-die listener trips one of these follow-ups.
            stable = 1
            for _ in range(stable_polls - 1):
                sleep(stable_gap_s)
                waited += stable_gap_s
                if not alive() or not _try_connect(port):
                    stable = 0
                    break
                stable += 1
            if stable >= stable_polls:
                if observe:
                    observe({"event": "verified-ready", "stable_polls": stable_polls,
                             "waited_s": round(waited, 1)})
                return True
            if observe:
                observe({"event": "unstable", "waited_s": round(waited, 1)})
        sleep(poll_s)
        waited += poll_s
    if observe:
        observe({"event": "timeout", "timeout_s": timeout_s})
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

    # RESTART-AO hardening (M2 routed-in W7, risk R5): hold the LAST spawned relaunch so
    # the retry loop can tell "still starting" from "dead" — a second spawn while the
    # first is cold-loading the 14B would hit the launcher's single-instance lock and
    # exit immediately, silently burning the attempt (the 2026-07-03 failure shape).
    relaunch_holder: dict = {"proc": None}

    def restart_launcher() -> None:
        # #761 live-verify catch (2026-07-08): the relaunch child MUST get real,
        # valid standard handles. This Popen used to pass none — survivable only
        # because the pre-#761 python.exe child got a fresh VISIBLE console (the
        # exact window #761 removes). Under the pythonw chain the child's stderr
        # wrapper was a cp1252 dead end and the launcher crashed encoding its own
        # startup BANNER (UnicodeEncodeError at _banner, three retries, SWAP_FAILED)
        # — the AO never came back. Mirror the PROVEN boot_launcher_detached
        # wiring: DEVNULL stdin, UTF-8 append log for stdout+stderr, and
        # PYTHONIOENCODING=utf-8 so every wrapper Python builds on these handles
        # is banner-safe.
        log_path = swap_dir(config) / "ao-relaunch.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        env = dict(os.environ)
        env.setdefault("PYTHONIOENCODING", "utf-8")
        fh = open(  # noqa: SIM115 — handle is inherited by the child
            log_path, "a", encoding="utf-8", errors="replace")
        try:
            try:
                relaunch_holder["proc"] = subprocess.Popen(  # noqa: S603
                    relaunch_argv, cwd=relaunch_cwd or None,
                    stdin=subprocess.DEVNULL, stdout=fh, stderr=subprocess.STDOUT,
                    creationflags=_DETACHED | _NEW_GROUP | _BREAKAWAY,
                    close_fds=True, env=env)
            except OSError:
                relaunch_holder["proc"] = subprocess.Popen(  # noqa: S603
                    relaunch_argv, cwd=relaunch_cwd or None,
                    stdin=subprocess.DEVNULL, stdout=fh, stderr=subprocess.STDOUT,
                    creationflags=_DETACHED | _NEW_GROUP, close_fds=True, env=env)
        finally:
            fh.close()  # the child inherited the fd; our handle is free to close

    def relaunch_in_flight() -> bool:
        proc = relaunch_holder.get("proc")
        if proc is None:
            return False
        try:
            return proc.poll() is None   # alive == starting or up
        except Exception:  # noqa: BLE001 — unreadable -> unknown -> legacy respawn
            return False

    # M2 W4: the job oracle's code rides the approved task dicts (stamped by
    # generate_plan; path-validated by extract_job_oracle) — the closure threads it to
    # the live oracle run. The DRIVER passes the plan's pinned oracle path per call.
    from shared.fleet.acceptance import extract_job_oracle
    from shared.fleet.context_pack import extract_import_contract

    _, job_oracle_code, job_oracle_path = extract_job_oracle(tasks)

    def _run_task_honest_kill(task: dict) -> TaskOutcome:
        # ONLY the live run-task path registers a child with the budget-watchdog holder; the
        # LOAD path (real_load_30b) does NOT, so the budget abort can never tree-kill OVMS.
        oc = real_run_task(
            config, run_id, task,
            on_spawn=(current_child.register if current_child is not None else None))
        # #757 honest labeling: when the overall-run budget watchdog tree-killed run-fleet
        # mid-task, the no-SUMMARY miss is a BUDGET kill, not a mystery — night-2 (B4+B6)
        # burned a full diagnostic cycle because it read "no SUMMARY line for this task".
        # Rewrite ONLY that fallback; a real parsed outcome (even one that raced the kill)
        # always wins, and an unexplained miss without a budget fire stays UNKNOWN.
        if (stop_event is not None and stop_event.is_set()
                and getattr(oc, "result", "") == "UNKNOWN"
                and "no SUMMARY line" in (getattr(oc, "detail", "") or "")):
            return TaskOutcome(
                task=oc.task, outcome="timeout", result="TIMEOUT",
                detail=("RESULT: TIMED OUT - the overall run budget elapsed mid-task; "
                        "run-fleet was tree-killed before it wrote a SUMMARY line"))
        return oc

    return SwapOps(
        available_gb=real_available_gb,
        backend_alive=lambda: real_backend_alive(old_pid),
        load_30b=lambda: real_load_30b(config, run_id),
        wait_ready=real_wait_ready,
        run_task=_run_task_honest_kill,
        cancel_requested=lambda: cancel_path(config).exists(),
        disarm_watchdog=lambda: _rm(sentinel_path(config)),
        stop_ovms=real_stop_ovms,
        write_report=lambda rid, outs: write_cumulative_report(config, rid, outs),
        restart_launcher=restart_launcher,
        # #750 fix 1: readiness must PROVE the AO is serving and staying up — a stability
        # re-poll + the launcher-alive guard (relaunch_in_flight) reject the bind-then-die
        # false-positive that made night-1 log "14B is back" over a dead AO. The observer
        # writes each probe outcome to the swap-progress trail (the residency evidence that
        # sequential swap-backs produce zero false-readies).
        backend_ready=lambda: real_backend_ready(
            ao_port,
            launcher_alive=relaunch_in_flight,
            observe=lambda info: write_swap_progress(
                config, run_id,
                "backend-ready probe: " + str(info.get("event", "?"))
                + "".join(f" {k}={v}" for k, v in info.items() if k != "event"),
            ),
        ),
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
            (lambda app_dir, base, base_sha="": real_run_critic(
                config, run_id, app_dir, base, base_sha))
            if critic_on
            else _noop_critic
        ),
        # Observable enablement: the driver logs ACTIVE/DORMANT from this so a dormant run is never
        # mistaken for a working one (and vice-versa). Same predicate as run_critic — they can't drift.
        critic_enabled=critic_on,
        # ---- M2 plan-graph live seams (W3-W6, #740). Wired unconditionally — the driver
        # only CALLS them in plan mode (plan_graph=false never reaches them), and each is
        # individually fail-soft, so legacy runs are behavior-identical.
        repo_head=real_repo_head,
        dep_delta=real_dep_delta,
        log_pack=lambda task_id, pack: real_log_pack(config, run_id, task_id, pack),
        run_wave_gate=lambda repo: real_run_wave_gate(
            config, run_id, repo,
            surface=str((tasks[0] if tasks else {}).get("surface", "") or ""),
            language_hint=str((tasks[0] if tasks else {}).get("language_hint", "") or ""),
        ),
        run_job_oracle=lambda repo, rel: real_run_job_oracle(
            config, run_id, repo, rel, job_oracle_code),
        # #748: seed the job oracle into the repo before wave 1 so the coder codes
        # toward the job spec (plan §4.5) — guard-wrapped (skips in gates), grade
        # unaffected (plan bytes overwrite at grade time).
        seed_job_oracle=lambda repo, rel: real_seed_job_oracle(
            config, run_id, repo, rel, job_oracle_code),
        # #790 rec-1: the oracle's first-party import surface (module paths + names the
        # final tree must provide), extracted from the SAME plan-time oracle code the
        # seeder/grader use. Pure + deterministic; [] when no oracle rides the run. The
        # driver surfaces it into every plan-graph task's context so the coder builds
        # toward the imports the wave-final oracle grades (the B4/B6/B7 park class).
        job_oracle_contract=lambda: extract_import_contract(
            job_oracle_path, job_oracle_code),
        # The mid-swap re-decompose MODEL TRANSPORT is deliberately NOT live-wired yet:
        # the 14B planner is not resident during CODE and no fleet script exposes a
        # free-text generation seam the driver could argv-invoke. The deterministic
        # policy (budgets, strict-improvement replace, ruler re-validation, park-on-
        # refuse) is fully built + regression-locked against the seam; wiring a live
        # transport is a W8 residency-choreography step (noted in the Lane A2 report).
        # Default: no re-planner -> the failed task parks honestly (today's behavior).
        write_scorecard=lambda sc: real_write_scorecard(config, run_id, sc),
        write_job_summary=lambda text: real_write_job_summary(config, run_id, text),
        relaunch_in_flight=relaunch_in_flight,
        # #744 guest-certified oracle — wired unconditionally (the driver only CALLS
        # these when guest_oracle_enabled rides the spec as true), and the executor is
        # itself STRUCTURALLY TRANSPORT-DORMANT (transport=None -> honest not-run)
        # until the supervised go-live ceremony. Double lock, like the egress door.
        run_guest_oracle=lambda repo, rel: real_run_guest_oracle(
            config, run_id, repo, rel, job_oracle_code),
        write_guest_oracle=lambda block: real_write_guest_oracle(config, run_id, block),
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
        # M2 (#740): the [fleet_dispatch].plan_graph knob rides the spec to the detached
        # driver. False (the default) = today's flat queue, byte-identical behavior.
        "plan_graph": bool(getattr(config, "plan_graph", False)),
        # #744: the [fleet_dispatch].guest_oracle_enabled knob rides the spec the same
        # way. False (the default) = the driver never touches the guest-oracle seams.
        "guest_oracle_enabled": bool(getattr(config, "guest_oracle_enabled", False)),
    }
    spec_path = swap_dir(config) / "spec.json"
    spec_path.parent.mkdir(parents=True, exist_ok=True)
    spec_path.write_text(json.dumps(spec, indent=2), encoding="utf-8")
    (spawn or _spawn_detached_driver)(spec_path)


def _spawn_detached_driver(spec_path: Path) -> None:
    import sys

    # #761: spawn via the pythonw sibling when one exists — sys.executable through the
    # venv python.exe shim re-spawns a console-subsystem child that is allocated a fresh
    # VISIBLE console despite DETACHED_PROCESS (this driver's conhost was diagnosed live
    # 2026-07-07 morning). Fallback is sys.executable unchanged.
    # NO CREATE_NO_WINDOW on any python-launcher spawn — see the _NO_WINDOW constraint.
    #
    # Live-verify catch (2026-07-08): "under pythonw a stray print is a silent
    # no-op" — the claim this comment used to make — is FALSE when a child
    # inherits a broken-but-present handle: the relaunched LAUNCHER died encoding
    # its banner to a cp1252 stderr. Give the driver real handles the same way
    # boot_launcher_detached does (DEVNULL in, UTF-8 append log out,
    # PYTHONIOENCODING=utf-8), so a stray print/traceback lands in the log
    # instead of crashing or vanishing.
    log_path = spec_path.with_name("driver-stdio.log")
    env = dict(os.environ)
    env.setdefault("PYTHONIOENCODING", "utf-8")
    fh = open(  # noqa: SIM115 — handle is inherited by the child
        log_path, "a", encoding="utf-8", errors="replace")
    try:
        subprocess.Popen(  # noqa: S603
            [pythonw_sibling(sys.executable), "-m", "shared.fleet.swap_ops",
             "--spec", str(spec_path)],
            stdin=subprocess.DEVNULL, stdout=fh, stderr=subprocess.STDOUT,
            creationflags=_DETACHED | _NEW_GROUP | _BREAKAWAY, close_fds=True,
            env=env,
        )
    finally:
        fh.close()  # the child inherited the fd; our handle is free to close


def _coerce_budget(value) -> float:
    """Coerce a spec/config overall-run budget to a non-negative float; a non-numeric or
    non-positive value -> 0.0 (DISABLED — never an instant-timeout). Mirrors the AO config
    resolver's defensive coercion (#670 P2)."""
    try:
        b = float(value)
    except (TypeError, ValueError):
        return 0.0
    return b if b > 0 else 0.0


def plan_path(config: FleetDispatchConfig) -> Path:
    """The persisted JobPlan artifact for the CURRENT swap (plan-graph mode only)."""
    return swap_dir(config) / "plan.json"


def build_job_plan(
    config: FleetDispatchConfig, run_id: str, tasks: list[dict]
):
    """M2 (#740): build + validate + persist the JobPlan for a plan-graph dispatch.

    Returns ``(plan, plan_store, degraded, cleaned_tasks)``. The DEGRADE-TO-TODAY rule
    is absolute: any refusal (unrunnable plan input) returns ``(None, None, False,
    cleaned_tasks)`` and the caller runs the legacy flat queue — a dispatch never fails
    because planning got fancier (plan §4.1 principle 2). Steps:

      1. pop the riding job-oracle fields (``acceptance.extract_job_oracle`` — the
         pinned-path containment lives there);
      2. stamp the appended ``acceptance-tests`` task's ``depends_on`` (seam note (a));
      3. ``build_plan_raw`` (goal/criteria from the task dicts + the run's
         acceptance.json record) → ``validate_plan`` (the ruler, incl. repo
         containment) → ``PlanStore.write`` (the §10 S1 hashed artifact).
    """
    from shared.fleet.acceptance import extract_job_oracle
    from shared.fleet.plan_graph import (
        DEFAULT_ORACLE_PATH,
        PlanStore,
        build_plan_raw,
        stamp_acceptance_task_deps,
        validate_plan,
    )

    cleaned, _oracle_code, oracle_rel = extract_job_oracle(tasks)
    if not cleaned:
        return (None, None, False, cleaned)
    # DEGRADE-TO-TODAY (M2, under-decomposition safety net): a plan of fewer than 2 tasks has
    # NO job-level acceptance oracle (generate_job_acceptance_oracle refuses <2 tasks — the
    # #690 per-task oracle owns the single-task shape) and NO dependency graph to schedule.
    # Running it as a 1-task plan-graph job would produce an UNGRADEABLE job (no job oracle ->
    # the driver records job acceptance not-run and STALLS at [VERIFY] even though the lone
    # task merged clean — the live B2 failure, 2026-07-06). Degrade to the legacy flat queue so
    # the per-task path (build/test/verify + the #690 per-task oracle the task still carries)
    # grades the single task -> GREEN-able. Mirrors the absolute refusal rule above (plan §4.1
    # principle 2): a dispatch never gets a WORSE outcome because planning got fancier.
    if len(cleaned) < 2:
        write_swap_progress(
            config, run_id,
            "Plan-graph declined a <2-task plan (no job oracle, no graph to schedule) — "
            "degrading to the flat task queue so the per-task oracle grades the single task "
            "(today's serial behavior).",
        )
        return (None, None, False, cleaned)
    stamped = stamp_acceptance_task_deps(cleaned)
    record = read_acceptance_record(config, run_id) or {}
    spec_dict = record.get("spec") if isinstance(record.get("spec"), dict) else {}
    criteria = [
        str(c.get("text", "") or "")
        for c in (spec_dict.get("criteria") or [])
        if isinstance(c, dict) and str(c.get("text", "") or "").strip()
    ]
    goal = str(spec_dict.get("goal", "") or (stamped[0].get("goal", "") if stamped else ""))
    repo = str(stamped[0].get("repo", "") or "")
    raw = build_plan_raw(
        plan_id=run_id, goal=goal, repo=repo, tasks=stamped,
        criteria=criteria, oracle_path=oracle_rel or DEFAULT_ORACLE_PATH,
    )
    validation = validate_plan(raw, projects_dir=config.projects_dir)
    if not validation.ok or validation.plan is None:
        write_swap_progress(
            config, run_id,
            f"Plan-graph refused ({validation.reason}) — degrading to the flat task "
            "queue (today's serial behavior).",
        )
        return (None, None, False, stamped)
    store = PlanStore(plan_path(config), projects_dir=config.projects_dir)
    try:
        plan = store.write(validation.plan)
    except OSError:
        write_swap_progress(
            config, run_id,
            "Plan artifact could not be persisted — degrading to the flat task queue.",
        )
        return (None, None, False, stamped)
    if validation.degraded:
        write_swap_progress(
            config, run_id,
            "Plan-graph DEGRADED to the original-order linear chain (cycle) — logged, "
            "not hidden.",
        )
    return (plan, store, validation.degraded, stamped)


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
        plan_graph=bool(spec.get("plan_graph", False)),
        # #744: absent key -> False (fail-closed dormancy; pre-#744 spec files
        # re-read after a crash recovery resolve to the legacy behavior).
        guest_oracle_enabled=bool(spec.get("guest_oracle_enabled", False)),
    )
    state = ss.read_swap_state(swap_state_path(config))
    tasks = state.tasks if state else []
    # #758: stamp THIS (the detached driver) process into the swap state, so a concurrent
    # AO boot's reconcile can tell a LIVE swap from a CRASHED one (driver alive ->
    # hands-off; dead -> recover). Without this, any AO boot mid-dispatch "recovered" the
    # healthy swap — stopped the real OVMS mid-task and stamped RECOVERED over the live
    # run (2026-07-07). create-time guards pid reuse; psutil-less degrades to pid-only.
    if state is not None:
        from dataclasses import replace as _dc_replace

        created = 0.0
        try:
            import psutil

            created = float(psutil.Process(os.getpid()).create_time())
        except Exception:  # noqa: BLE001 — pid-only still guards (narrow reuse window)
            created = 0.0
        try:
            ss.write_swap_state(
                _dc_replace(state, driver_pid=os.getpid(), driver_pid_created=created),
                path=swap_state_path(config),
            )
        except OSError:
            pass  # fail-soft: an unstamped record degrades to pre-#758 recovery behavior
    # M2 (#740): plan-graph mode — build/validate/persist the JobPlan; ANY refusal
    # degrades to the legacy flat queue (plan=None), never a new failure mode. The
    # driver's task list is the CLEANED set (job-oracle blob popped; acceptance task
    # dep-stamped); build_swap_ops keeps the ORIGINAL dicts (it extracts the oracle
    # code itself, and the worktree sweep reads only repo/task keys).
    plan = None
    store = None
    degraded = False
    driver_tasks = tasks
    if config.plan_graph and tasks:
        plan, store, degraded, driver_tasks = build_job_plan(config, spec["run_id"], tasks)
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
        run_id=spec["run_id"], session_id=spec["session_id"], tasks=driver_tasks,
        swap_state_path=swap_state_path(config), ops=ops,
        gate_gb=float(spec.get("gate_gb", 20.0)), budget_watchdog=watchdog,
        plan=plan, plan_store=store, plan_degraded=degraded,
        guest_oracle_enabled=config.guest_oracle_enabled,
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


def pythonw_sibling(python_exe: str) -> str:
    """The GUI-subsystem ``pythonw.exe`` beside *python_exe*, else *python_exe* unchanged.

    #761 root cause: on Windows ``.venv\\Scripts\\python.exe`` is the venv LAUNCHER
    SHIM — it spawns the BASE console-subsystem interpreter as a CHILD, so a
    ``DETACHED_PROCESS`` spawn is defeated one hop down: the child, born to a
    console-less parent, is allocated a fresh VISIBLE console (the
    "Administrator: ...python.exe" window the operator can accidentally close — the
    night-2 window-close incident class). ``pythonw.exe`` is GUI-subsystem the whole
    way down (its shim child is ``pythonw`` too): no console is ever allocated, and
    the Textual launcher takes its PROVEN headless-driver fallback — the same one a
    DETACHED spawn already exercised. Deliberately NOT ``CREATE_NO_WINDOW``: a HIDDEN
    console is the exact shape that crashed Textual on 2026-07-06 ("Driver must be
    in application mode"). Fail-safe: no sibling (POSIX layout, non-standard exe
    name) -> the original interpreter unchanged, never a broken spawn."""
    path = Path(python_exe)
    if path.name.lower() == "python.exe":
        sibling = path.with_name("pythonw.exe")
        if sibling.exists():
            return str(sibling)
    return python_exe


def _venv_pythonw(repo_root: Path) -> str:
    """``_venv_python``'s GUI-subsystem sibling for the DETACHED relaunch argv (#761):
    resolve ``.venv/Scripts/pythonw.exe`` when present, else fall back to
    ``_venv_python``'s result (a POSIX venv, or a Scripts dir without pythonw) so the
    relaunch never breaks — it merely keeps the pre-#761 visible-console behavior."""
    candidate = repo_root.joinpath(".venv", "Scripts", "pythonw.exe")
    if candidate.exists():
        return str(candidate)
    return _venv_python(repo_root)


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
    the interpreter is the checkout's ``.venv`` **pythonw.exe** (NOT ``sys.executable`` —
    #670 run-1 bug 2 — and NOT the venv ``python.exe`` shim, whose console-subsystem child
    defeats DETACHED_PROCESS and presents the accidentally-closable visible console the
    swap-back was showing — #761; see :func:`pythonw_sibling`), and the default root is
    this checkout's repo root."""
    root = Path(repo_root) if repo_root else Path(__file__).resolve().parents[2]
    py = python_exe or _venv_pythonw(root)
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
