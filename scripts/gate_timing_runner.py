"""Run the standing gate for TIMING, only on an idle box on AC power (#1699).

A gate run read as a wall-clock figure is a measurement (TEST_GOVERNANCE §1 rule 1): input
from the operator, a battery transition or another heavy process changes it. This runner makes
that precondition mechanical. It is invoked repeatedly (an elevated, interactive Scheduled Task
every few minutes, see scripts/register_gate_timing_task.ps1) and each invocation is one TICK:

  1. take the single-instance lock (a live tick elsewhere => exit, logged);
  2. reap a run whose tick died (kill its orphaned gate, void and requeue it);
  3. pick the next pending run from the plan in state.json (arms alternate, A B A B ...);
  4. start it only if input has been idle >= IDLE_REQUIRED_S, the box is on AC power, CPU is
     quiet and no other test runner is alive; the idle and power readings that count are taken
     immediately before the process starts;
  5. run pytest hidden, unbuffered, with --durations=0, and sample idle seconds, power source
     and CPU about every SAMPLE_S into samples.csv (other test runners are scanned every
     INTRUDER_SCAN_S) for the whole run;
  6. VOID the run (kill the process tree, record the reason, requeue) if ANY input arrived since
     the start, the power source is not AC at any sample, another test runner appears, or the
     log stops growing for STALL_S; otherwise record it CLEAN with its summary.

State is the file, never memory. Every failure of the runner itself is written to ticks.log with
its traceback (it runs under pythonw, which has no stderr). Nothing here changes a power setting.

Usage: python gate_timing_runner.py init --state-dir D --python PY --arm NAME=TREE ... --rounds N
       python gate_timing_runner.py tick --state-dir D
       python gate_timing_runner.py status --state-dir D
"""
from __future__ import annotations

import argparse
import csv
import ctypes
import json
import os
import re
import subprocess
import sys
import time
import traceback
from ctypes import wintypes
from pathlib import Path

IDLE_REQUIRED_S = 15 * 60
CPU_QUIET_PCT = 15.0
SAMPLE_S = 10
STALL_S = 5 * 60
INTRUDER_SCAN_S = 60      # one process scan costs ~7 s of wall clock on this box, so it is not per-sample
NO_WINDOW = 0x08000000    # CREATE_NO_WINDOW: a console child of the pythonw task must not open a window
MAX_VOIDS = 8
INPUT_TOLERANCE_S = 2.0   # idle-clock granularity (~16 ms) plus scheduling jitter between two reads
GATE_ARGS = ["shared/", "services/", "launcher/", "tests/integration/", "tests/security/",
             "-m", "not hardware and not winui and not slow"]
SUMMARY_RE = re.compile(r"=+ (?P<body>.*?) in (?P<secs>[\d.]+)s(?: \([\d:]+\))? =+\s*$", re.M)


# --------------------------------------------------------------------------- pure decisions

def start_blocker(idle_s: float, on_ac: bool | None, cpu_pct: float, others: list[str]) -> str | None:
    """Why a run may not start now, or None. An unknown power source blocks: never assume AC."""
    if on_ac is not True:
        return "not on AC power" if on_ac is False else "power source unknown"
    if idle_s < IDLE_REQUIRED_S:
        return f"input idle {idle_s:.0f}s < {IDLE_REQUIRED_S}s"
    if cpu_pct >= CPU_QUIET_PCT:
        return f"cpu {cpu_pct:.0f}% >= {CPU_QUIET_PCT:.0f}%"
    if others:
        return "other test runner alive: " + ", ".join(others[:3])
    return None


def void_reason(idle_s: float, elapsed_s: float, idle0_s: float, on_ac: bool | None,
                log_silent_s: float, intruders: list[str] | None = None) -> str | None:
    """Why a RUNNING run is no longer a clean measurement, or None.

    `idle0_s` is the idle clock read immediately before the process started. With no input the
    idle clock advances exactly with wall time, so idle_s >= idle0_s + elapsed_s; any input
    since the start makes it smaller, however brief."""
    if on_ac is not True:
        return "power source is not AC" if on_ac is False else "power source became unknown"
    if idle_s < idle0_s + elapsed_s - INPUT_TOLERANCE_S:
        return f"input resumed (idle {idle_s:.0f}s, expected >= {idle0_s + elapsed_s:.0f}s)"
    if intruders:
        return "another test runner started during the run: " + ", ".join(intruders[:3])
    if log_silent_s >= STALL_S:
        return f"log silent {log_silent_s:.0f}s (stall)"
    return None


def is_pytest_cmdline(cmdline: list[str]) -> bool:
    """A test runner by what it EXECUTES, not by a word in its arguments: `-m pytest`,
    pytest.exe / py.test, or a script named pytest."""
    for i, tok in enumerate(cmdline):
        base = os.path.basename(tok.replace("\\", "/")).lower()
        if i <= 1 and base in ("pytest", "pytest.exe", "py.test", "py.test.exe", "pytest-script.py"):
            return True   # the executable, or the script handed to an interpreter; not any later argument
        if tok == "-mpytest" or (tok == "-m" and i + 1 < len(cmdline) and cmdline[i + 1] == "pytest"):
            return True
    return False


def next_pending(state: dict) -> dict | None:
    return next((r for r in state["runs"] if r["status"] == "pending"), None)


def plan_runs(arms: list[str], rounds: int) -> list[dict]:
    """Arms alternate within each round, so every arm sees the same box over time."""
    return [{"n": i * len(arms) + j + 1, "arm": a, "status": "pending"}
            for i in range(rounds) for j, a in enumerate(arms)]


def requeue(state: dict, run: dict) -> bool:
    """Repeat a voided run next, keeping the alternation, until MAX_VOIDS runs have voided.

    Returns whether a repeat was queued; False means the plan was abandoned."""
    if sum(r["status"] == "void" for r in state["runs"]) >= MAX_VOIDS:
        return False
    at = state["runs"].index(run) + 1
    state["runs"].insert(at, {"n": max(r["n"] for r in state["runs"]) + 1, "arm": run["arm"], "status": "pending"})
    return True


def parse_summary(log_text: str) -> dict | None:
    m = None
    for m in SUMMARY_RE.finditer(log_text):
        pass
    if m is None:
        return None
    counts = {k: int(n) for n, k in re.findall(r"(\d+) (passed|failed|skipped|deselected|error|errors)", m.group("body"))}
    return {"summary": m.group("body"), "pytest_s": float(m.group("secs")), **counts}


# --------------------------------------------------------------------------- Windows probes

class _LASTINPUTINFO(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.UINT), ("dwTime", wintypes.DWORD)]


class _POWER(ctypes.Structure):
    _fields_ = [("ACLineStatus", ctypes.c_ubyte), ("BatteryFlag", ctypes.c_ubyte),
                ("BatteryLifePercent", ctypes.c_ubyte), ("SystemStatusFlag", ctypes.c_ubyte),
                ("BatteryLifeTime", wintypes.DWORD), ("BatteryFullLifeTime", wintypes.DWORD)]


def idle_seconds() -> float:
    """Seconds since the last keyboard/mouse input of the interactive session this runs in."""
    info = _LASTINPUTINFO(ctypes.sizeof(_LASTINPUTINFO), 0)
    if not ctypes.windll.user32.GetLastInputInfo(ctypes.byref(info)):
        raise OSError("GetLastInputInfo failed")
    ctypes.windll.kernel32.GetTickCount64.restype = ctypes.c_uint64
    now = ctypes.windll.kernel32.GetTickCount64()
    return ((now & 0xFFFFFFFF) - info.dwTime) % (1 << 32) / 1000.0


def on_ac_power() -> bool | None:
    p = _POWER()
    if not ctypes.windll.kernel32.GetSystemPowerStatus(ctypes.byref(p)):
        return None
    return {0: False, 1: True}.get(p.ACLineStatus)


def other_test_runners(own_pid: int, family: int | None = None) -> list[str]:
    """Test runners alive that are neither this tick nor (when `family` is the gate process)
    that process or one of its descendants. Each entry carries the start of its command line."""
    import psutil
    skip = {own_pid}
    if family is not None:
        try:
            skip |= {family} | {c.pid for c in psutil.Process(family).children(recursive=True)}
        except psutil.Error:
            pass
    found = []
    for pr in psutil.process_iter(["pid", "name", "cmdline"]):
        try:
            cmd = pr.info["cmdline"] or []
        except psutil.Error:
            continue
        if pr.info["pid"] not in skip and is_pytest_cmdline(cmd):
            found.append(f"{pr.info['name']}:{pr.info['pid']} {' '.join(cmd)[:80]}")
    return found


def cpu_percent() -> float:
    import psutil
    return psutil.cpu_percent(interval=20)


def kill_tree(pid: int) -> None:
    subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True, check=False,
                   creationflags=NO_WINDOW)


def proc_ctime(pid: int) -> float | None:
    import psutil
    try:
        return psutil.Process(pid).create_time()
    except psutil.Error:
        return None


def same_process(pid: int, ctime: float | None) -> bool:
    """pid is alive AND is the process that was recorded (a reused pid has another start time)."""
    now = proc_ctime(pid)
    return now is not None and ctime is not None and abs(now - ctime) < 1.0


# --------------------------------------------------------------------------- state + tick

def load(state_dir: Path) -> dict:
    return json.loads((state_dir / "state.json").read_text(encoding="utf-8"))


def save(state_dir: Path, state: dict) -> None:
    tmp = state_dir / "state.json.tmp"
    tmp.write_text(json.dumps(state, indent=2), encoding="utf-8")
    os.replace(tmp, state_dir / "state.json")


def note(state_dir: Path, line: str) -> None:
    with (state_dir / "ticks.log").open("a", encoding="utf-8") as f:
        f.write(time.strftime("%Y-%m-%dT%H:%M:%S%z") + " " + line + "\n")


def take_lock(state_dir: Path) -> bool:
    """Exclusive lock holding (pid, start time): a stale file whose pid was reused by another
    process is taken over, and a live holder is reported rather than silently obeyed."""
    lock = state_dir / "tick.lock"
    mine = json.dumps({"pid": os.getpid(), "ctime": proc_ctime(os.getpid())})
    for _ in range(2):
        try:
            fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            try:
                if not lock.read_text(encoding="utf-8").strip() and time.time() - lock.stat().st_mtime < 5:
                    note(state_dir, "tick skipped: lock is being written by another tick")
                    return False
                held = json.loads(lock.read_text(encoding="utf-8"))
                if same_process(int(held["pid"]), held.get("ctime")):
                    note(state_dir, f"tick skipped: lock held by live pid {held['pid']}")
                    return False
            except (ValueError, KeyError, OSError):
                pass
            lock.unlink(missing_ok=True)   # stale: its owner is gone or the pid was reused
            continue
        with os.fdopen(fd, "w") as f:
            f.write(mine)
        return True
    note(state_dir, "tick skipped: could not take the lock")
    return False


def reap_dead_running(state_dir: Path, state: dict) -> None:
    """A RUNNING entry whose tick is gone: kill the gate it orphaned, void it, requeue it."""
    for r in state["runs"]:
        if r["status"] != "running" or same_process(r.get("tick_pid", -1), r.get("tick_ctime")):
            continue
        killed = ""
        if r.get("gate_pid") and same_process(r["gate_pid"], r.get("gate_ctime")):
            kill_tree(r["gate_pid"])
            killed = f"; orphaned gate pid {r['gate_pid']} killed"
        r.update(status="void", reason="runner died mid-run" + killed, ended=time.strftime("%F %T %z"))
        queued = requeue(state, r)
        note(state_dir, f"run {r['n']} voided: {r['reason']}" + ("" if queued else "; void cap reached, plan abandoned"))
        save(state_dir, state)


def execute(state_dir: Path, state: dict, run: dict) -> bool:
    """Start and supervise one run. Returns False (run untouched) if the box is not quiet at the
    instant of the start; the readings that count are the ones taken here, not a tick earlier."""
    idle0, ac0 = idle_seconds(), on_ac_power()
    if ac0 is not True or idle0 < IDLE_REQUIRED_S:
        note(state_dir, f"run {run['n']} {run['arm']} not started: idle {idle0:.0f}s, power {ac0}")
        return False
    tree = Path(state["arms"][run["arm"]])
    stem = f"run{run['n']:02d}-{run['arm']}"
    log = state_dir / f"{stem}.log"
    env = {**os.environ, "PYTHONUNBUFFERED": "1", "LOCALAPPDATA": str(state_dir / f"la-{stem}")}
    Path(env["LOCALAPPDATA"]).mkdir(parents=True, exist_ok=True)
    run.update(status="running", tick_pid=os.getpid(), tick_ctime=proc_ctime(os.getpid()),
               started=time.strftime("%F %T %z"), power_at_start="AC", idle_at_start_s=round(idle0),
               log=str(log))
    save(state_dir, state)
    cmd = [state["python"], "-u", "-m", "pytest", *GATE_ARGS, "-p", "no:cacheprovider", "--durations=0", "-rfs"]
    try:
        with log.open("wb") as out:
            proc = subprocess.Popen(cmd, cwd=tree, env=env, stdout=out, stderr=subprocess.STDOUT,
                                    creationflags=NO_WINDOW)
    except OSError as exc:
        run.update(status="void", reason=f"gate failed to start: {exc}", ended=time.strftime("%F %T %z"))
        queued = requeue(state, run)
        note(state_dir, f"run {run['n']} {run['arm']} -> void {run['reason']}" + ("" if queued else "; void cap reached, plan abandoned"))
        save(state_dir, state)
        return True
    run.update(gate_pid=proc.pid, gate_ctime=proc_ctime(proc.pid))
    save(state_dir, state)
    t0 = time.monotonic()
    last_size, last_growth = -1, t0
    last_scan, intruders, why = t0, [], None
    with (state_dir / f"{stem}.samples.csv").open("w", newline="") as sf:
        w = csv.writer(sf)
        w.writerow(["t_s", "idle_s", "power", "cpu_pct"])
        import psutil
        while proc.poll() is None:
            time.sleep(SAMPLE_S)
            now = time.monotonic()
            size = log.stat().st_size
            if size != last_size:
                last_size, last_growth = size, now
            idle, ac = idle_seconds(), on_ac_power()
            w.writerow([f"{now - t0:.0f}", f"{idle:.0f}", {True: "AC", False: "BATTERY", None: "?"}[ac],
                        f"{psutil.cpu_percent(interval=None):.0f}"])
            sf.flush()
            if now - last_scan >= INTRUDER_SCAN_S:
                intruders, last_scan = other_test_runners(os.getpid(), proc.pid), time.monotonic()
            why = void_reason(idle, now - t0, idle0, ac, now - last_growth, intruders)
            if why:
                kill_tree(proc.pid)
                break
    run.update(ended=time.strftime("%F %T %z"), wall_s=round(time.monotonic() - t0, 1))
    if why:
        run.update(status="void", reason=why)
    else:
        parsed = parse_summary(log.read_text(encoding="utf-8", errors="replace"))
        run.update(status="clean" if parsed else "void", **(parsed or {"reason": "no pytest summary line"}))
    queued = True
    if run["status"] == "void":
        queued = requeue(state, run)
    note(state_dir, f"run {run['n']} {run['arm']} -> {run['status']} {run.get('reason', run.get('summary', ''))}"
         + ("" if queued else "; void cap reached, plan abandoned"))
    save(state_dir, state)
    return True


def tick(state_dir: Path) -> int:
    if not (state_dir / "state.json").is_file():
        state_dir.mkdir(parents=True, exist_ok=True)
        note(state_dir, f"TICK FAILED no state.json in {state_dir}; run init first")
        return 2
    if not take_lock(state_dir):
        return 0
    try:
        state = load(state_dir)
        reap_dead_running(state_dir, state)
        run = next_pending(state)
        if run is None:
            note(state_dir, "nothing pending")
            return 0
        blocker = start_blocker(idle_seconds(), on_ac_power(), cpu_percent(), other_test_runners(os.getpid()))
        if blocker:
            note(state_dir, f"run {run['n']} {run['arm']} waiting: {blocker}")
            return 0
        execute(state_dir, state, run)
        return 0
    except BaseException:  # noqa: BLE001 - the task runs without a console; this log is the only trace
        note(state_dir, "TICK FAILED " + traceback.format_exc().replace("\n", " | "))
        return 1
    finally:
        (state_dir / "tick.lock").unlink(missing_ok=True)


def init(args: argparse.Namespace) -> int:
    d = Path(args.state_dir)
    d.mkdir(parents=True, exist_ok=True)
    arms = dict(a.split("=", 1) for a in args.arm)
    save(d, {"python": args.python, "arms": arms, "runs": plan_runs(list(arms), args.rounds)})
    return 0


def status(state_dir: Path) -> int:
    for r in load(state_dir)["runs"]:
        print(r["n"], r["arm"], r["status"], r.get("wall_s", ""), r.get("summary", r.get("reason", "")))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["init", "tick", "status"])
    ap.add_argument("--state-dir", required=True)
    ap.add_argument("--python")
    ap.add_argument("--arm", action="append", default=[])
    ap.add_argument("--rounds", type=int, default=2)
    a = ap.parse_args()
    sd = Path(a.state_dir)
    return {"init": lambda: init(a), "tick": lambda: tick(sd), "status": lambda: status(sd)}[a.cmd]()


if __name__ == "__main__":
    sys.exit(main())
