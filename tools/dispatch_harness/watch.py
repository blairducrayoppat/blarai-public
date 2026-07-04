"""Live dispatch watcher (#688) -- a READABLE, real-time view of the coder's every action.

The fleet already logs everything (each per-task ``state/reports/<repo>-<task>-*.agent.log`` is a
complete JSON event stream: every bash command with its FULL text + FULL output, every file write,
every reasoning step, tokens, timestamps). What was missing was *watching* it: the harness only
signalled at whole-run completion, so a per-task PARK could sit unnoticed for minutes. This renders
that dense stream into ``$ command`` + output lines, shows the current ``[phase]``, surfaces each
task's RESULT the moment it lands, and (``--stop-on-park``) trips the driver's cancel sentinel the
instant a task parks -- so a doomed run stops itself instead of churning the remaining tasks.

Usage::

    python -m tools.dispatch_harness.watch                     # snapshot of the latest run
    python -m tools.dispatch_harness.watch --tail 12           # last 12 coder actions
    python -m tools.dispatch_harness.watch --follow            # poll + print new actions live
    python -m tools.dispatch_harness.watch --follow --stop-on-park   # + fail-fast on the first park
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from tools.dispatch_harness.config import load_harness_config


def _state_dir() -> Path:
    cfg = load_harness_config(None)
    base = Path(cfg.agentic_setup_dir) if cfg.agentic_setup_dir else Path("C:/Users/mrbla/agentic-setup")
    return base / "state"


def _latest_run(state: Path) -> Path | None:
    runs = state / "fleet-runs"
    if not runs.is_dir():
        return None
    dirs = [d for d in runs.iterdir() if d.is_dir()]
    if not dirs:
        return None
    return max(dirs, key=lambda d: d.stat().st_mtime)


def _clip(s: str, n: int) -> str:
    s = " ".join(str(s).split())
    return s if len(s) <= n else s[: n - 1] + "…"


def _render_event(ev: dict) -> str | None:
    """One agent-log JSON event -> a readable line (or None to skip)."""
    t = ev.get("type")
    part = ev.get("part", {}) if isinstance(ev.get("part"), dict) else {}
    if t == "tool_use":
        st = part.get("state", {}) if isinstance(part.get("state"), dict) else {}
        inp = st.get("input", {}) if isinstance(st.get("input"), dict) else {}
        cmd = inp.get("command") or inp.get("filePath") or part.get("tool", "?")
        out = st.get("output") or (st.get("metadata", {}) or {}).get("output") or ""
        exit_code = (st.get("metadata", {}) or {}).get("exit")
        line = f"  $ {_clip(cmd, 150)}"
        if out:
            line += f"\n      -> {_clip(out, 200)}"
        if exit_code not in (None, 0):
            line += f"  [exit {exit_code}]"
        return line
    if t == "text":
        txt = (part.get("text") or "").strip()
        return f"  . {_clip(txt, 150)}" if txt else None
    if t == "file":
        return f"  [file] {_clip(part.get('path') or part.get('filename') or 'wrote a file', 120)}"
    return None


def _read_events(agent_log: Path) -> list[dict]:
    out: list[dict] = []
    try:
        for ln in agent_log.read_text(encoding="utf-8", errors="replace").splitlines():
            ln = ln.strip()
            if not ln:
                continue
            try:
                out.append(json.loads(ln))
            except ValueError:
                continue
    except OSError:
        pass
    return out


def _active_task(run: Path) -> tuple[str, str]:
    """(current_task, last_journal_line) from the run journal."""
    j = run / "journal.log"
    task, last = "", ""
    try:
        for ln in j.read_text(encoding="utf-8", errors="replace").splitlines():
            last = ln
            if "TASK-START" in ln:
                # ...| TASK-START | <task> repo=...
                seg = ln.split("TASK-START")[-1].strip(" |")
                task = seg.split(" ")[0] if seg else task
    except OSError:
        pass
    return task, last


def _task_log(run: Path, task: str) -> Path | None:
    cands = sorted(run.glob(f"run-fleet-{task}.log"), key=lambda p: p.stat().st_mtime, reverse=True)
    return cands[0] if cands else None


def _agent_log(state: Path, task: str) -> Path | None:
    reports = state / "reports"
    cands = sorted(reports.glob(f"*-{task}-*.agent.log"), key=lambda p: p.stat().st_mtime, reverse=True)
    return cands[0] if cands else None


def _gate(task_log: Path | None) -> dict:
    """Pull the gate signals + verdict + RESULT from a run-fleet task log (best-effort)."""
    d = {"phase": "", "tests": "", "verify": "", "verdict": "", "result": "", "parked": False, "merged": False}
    if not task_log or not task_log.is_file():
        return d
    txt = task_log.read_text(encoding="utf-8", errors="replace")
    import re
    for key, pat in (("tests", r"(?m)^TESTS:\s*(.+)$"), ("verify", r"(?m)^VERIFY:\s*(.+)$"),
                     ("verdict", r"REVIEW VERDICT:\s*(.+)"), ("result", r"RESULT:\s*(.+)")):
        m = re.search(pat, txt)
        if m:
            d[key] = m.group(1).strip()
    # latest [n/5] phase marker
    phases = re.findall(r"\[(\d)/5\][^\n]*", txt)
    if phases:
        d["phase"] = f"[{phases[-1]}/5]"
    d["parked"] = "NOT merged" in (d["result"] or "")
    d["merged"] = d["result"].startswith("MERGED") if d["result"] else False
    return d


def snapshot(state: Path, run: Path, tail: int) -> dict:
    task, _ = _active_task(run)
    alog = _agent_log(state, task) if task else None
    tlog = _task_log(run, task) if task else None
    gate = _gate(tlog)
    print(f"\n=== RUN {run.name}  |  TASK {task or '?'}  |  phase {gate['phase'] or '(building)'} ===")
    if alog:
        age = time.time() - alog.stat().st_mtime
        evs = _read_events(alog)
        lines = [r for ev in evs if (r := _render_event(ev))]
        print(f"--- coder actions (last {tail} of {len(lines)}; log {age:.0f}s idle) ---")
        for ln in lines[-tail:]:
            print(ln)
    else:
        print("  (no agent log yet -- coder starting)")
    if gate["tests"] or gate["verify"] or gate["verdict"] or gate["result"]:
        print(f"--- gate: TESTS={gate['tests'] or '-'}  VERIFY={gate['verify'] or '-'}  "
              f"REVIEW={gate['verdict'] or '(pending)'} ---")
    if gate["result"]:
        flag = "  *** PARK ***" if gate["parked"] else ("  *** MERGED ***" if gate["merged"] else "")
        print(f"  RESULT: {gate['result']}{flag}")
    return gate


def main(argv: list[str] | None = None) -> int:
    # The coder's output carries check-marks / em-dashes / box glyphs; the default Windows console
    # code page (cp1252) raises UnicodeEncodeError on those. Degrade un-encodable glyphs to '?'.
    for _s in (sys.stdout, sys.stderr):
        try:
            _s.reconfigure(errors="replace")  # type: ignore[union-attr]
        except (AttributeError, ValueError):
            pass
    p = argparse.ArgumentParser(prog="python -m tools.dispatch_harness.watch")
    p.add_argument("--run", help="explicit run dir (default: latest under state/fleet-runs)")
    p.add_argument("--tail", type=int, default=8, help="how many recent coder actions to show")
    p.add_argument("--follow", action="store_true", help="poll and reprint (Ctrl-C to stop)")
    p.add_argument("--interval", type=float, default=15.0, help="--follow poll seconds")
    p.add_argument("--stop-on-park", action="store_true",
                   help="trip the driver's cancel sentinel the instant a task parks (fail-fast)")
    args = p.parse_args(argv)

    state = _state_dir()
    run = Path(args.run) if args.run else _latest_run(state)
    if not run:
        print("no fleet run found under", state / "fleet-runs")
        return 1

    seen_park: set[str] = set()
    while True:
        gate = snapshot(state, run, args.tail)
        # Only auto-cancel an ACTIVELY-CODING run (swap phase CODE). A terminal/older run (RECOVERED,
        # etc.) that happens to be the latest must never have its park trip a cancel -- that would fire
        # on a previous run and could disturb the NEXT dispatch's swap. (#688)
        if args.stop_on_park and gate.get("parked"):
            try:
                _ph = json.loads((state / "fleet-swap" / "current.json").read_text(encoding="utf-8")).get("phase", "")
            except (OSError, ValueError):
                _ph = ""
            task, _ = _active_task(run)
            if _ph == "CODE" and task not in seen_park:
                seen_park.add(task)
                cancel = state / "fleet-swap" / "cancel"
                try:
                    cancel.write_text("", encoding="utf-8")
                    print(f"\n!!! PARK on '{task}' (phase CODE) -> cancel sentinel set (fail-fast); "
                          f"the run tears down after the current task. !!!")
                except OSError as e:
                    print(f"!!! PARK detected but could not set cancel: {e}")
        if not args.follow:
            return 0
        try:
            time.sleep(max(2.0, args.interval))
        except KeyboardInterrupt:
            return 0
        # re-resolve latest run in case the swap rolled to a new one
        if not args.run:
            run = _latest_run(state) or run


if __name__ == "__main__":
    raise SystemExit(main())
