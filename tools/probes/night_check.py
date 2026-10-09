"""Mid-run health check for the overnight battery. Reports; never kills.

Why this exists
---------------
The two scheduled watchdogs fire at **23:30** (did it start?) and **09:00** (did it
finish?). Between them nothing outside the run observes it, so a run that wedges at
01:00 is discovered at 09:00 with eight hours of granted budget already gone. The
operator asked for a check "around 3:00am" instead of waiting for morning (#1424).

WHY IT DOES NOT KILL ANYTHING
-----------------------------
The in-run idle watchdog was once set to 120 s and **false-killed ~84% of 30B
candidates**, because "no session update" cannot distinguish a slow generation from a
wedged one. Raising it to 600 s cut false kills to ~0.7% without making the signal any
less blind. A 15-minute poller that kills on a blind signal recreates that failure at a
shorter interval. So this REPORTS, and whether anything may ever kill a run
autonomously stays an operator decision.

THE SIGNALS, AND WHY THESE ONES
-------------------------------
Three obvious candidates are useless, each verified wrong on 2026-08-15:

* ``night-<stamp>/battery-runner.log`` — **0 bytes for the entire run**.
* the launcher pid — **exits by design** minutes in ("the launcher is exiting now").
* the run directory — written only **between** candidates, so legitimately quiet for
  30+ minutes mid-task.

What actually moves while a candidate is generating:

1. ``ovms.exe`` CPU time (measured climbing 293 → 941 → 1167 → 2541 s across two tasks).
2. files under ``state/worktrees/<repo>-<task-slug>/`` — the coder builds there.

A stall is reported only when **both** are flat AND the run has not already ended.
One flat signal is the normal state of a working run.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

STATE = Path(os.environ.get("BLARAI_FLEET_STATE_ROOT", r"C:/Users/mrbla/agentic-setup/state"))
#: How long the two movement signals must BOTH be flat before a stall is reported.
#: Generous on purpose: a single candidate may legitimately run to 60 minutes.
FLAT_MINUTES = 20
#: Seconds between the two CPU samples. The whole check must stay far below its own
#: scheduling interval, so this is short.
CPU_SAMPLE_GAP_S = 45


def _newest(pattern_dir: Path, prefix: str = "") -> Path | None:
    if not pattern_dir.is_dir():
        return None
    cands = [d for d in pattern_dir.iterdir() if d.is_dir() and d.name.startswith(prefix)]
    return max(cands, key=lambda d: d.name, default=None)


def _ovms_cpu_seconds() -> float | None:
    """Total CPU seconds of the model server, or None if it is not running."""
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "$p=Get-Process ovms -ErrorAction SilentlyContinue; if($p){$p.CPU}else{''}"],
            capture_output=True, text=True, timeout=30,
        ).stdout.strip()
    except (subprocess.SubprocessError, OSError):
        return None
    if not out:
        return None
    try:
        return float(out.splitlines()[0])
    except ValueError:
        return None


def _newest_write(root: Path, within: timedelta) -> bool:
    """Did anything under ``root`` change recently? Cheap and shallow-ish on purpose."""
    if not root.is_dir():
        return False
    cutoff = time.time() - within.total_seconds()
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in {".git", "node_modules", "__pycache__"}]
        for name in filenames:
            try:
                if os.path.getmtime(os.path.join(dirpath, name)) > cutoff:
                    return True
            except OSError:
                continue
    return False


def check() -> dict:
    now = datetime.now().astimezone()
    night = _newest(STATE / "battery", "night-")
    run = _newest(STATE / "fleet-runs")
    out: dict = {
        "checked_at": now.isoformat(),
        "night_dir": night.name if night else None,
        "run_dir": run.name if run else None,
        "verdict": "UNKNOWN",
        "detail": "",
        "signals": {},
    }

    if night is None:
        out["verdict"] = "NO-NIGHT-DIRECTORY"
        out["detail"] = "Nothing under state/battery matches night-*. The battery has never run here, or its state moved."
        return out

    # Has it already finished? `scorecard.json` is the ONLY honest marker.
    #
    # CORRECTED 2026-08-16 03:25, after this check's first autonomous 03:00 firing
    # reported "run ended: True" on a run three tasks from finishing. Both markers the
    # first version used are written PER TASK, not per run:
    #   * RUN-END appears once per task DISPATCH -- 4 times in this run's journal by
    #     03:20, so it went true the moment the FIRST task ended.
    #   * SUMMARY.txt is rewritten after every task; it existed at 435 bytes mid-run.
    #
    # The consequence inverted the check's purpose: with the model server gone, a
    # mid-run death would have reported FINISHED ("nothing to do") instead of
    # STOPPED-WITHOUT-FINISHING -- the exact case this exists to catch.
    #
    # scorecard.json is written once, at the end. Verified across the corpus: present
    # on 20260815-161349-bd / 20260814-230237-bd / 20260810-012417-bd (completed),
    # ABSENT on 20260810-230238-bd (reaped mid-run) and absent on a run in flight.
    finished = run is not None and (run / "scorecard.json").is_file()
    out["signals"]["run_ended"] = finished

    cpu1 = _ovms_cpu_seconds()
    out["signals"]["model_server_running"] = cpu1 is not None

    if finished and cpu1 is None:
        out["verdict"] = "FINISHED"
        out["detail"] = "The run reached its end and the model server has exited. Nothing to do."
        return out

    if cpu1 is None and not finished:
        out["verdict"] = "STOPPED-WITHOUT-FINISHING"
        out["detail"] = (
            "The model server is gone but the run never wrote an end marker. That is the shape "
            "an unclean shutdown leaves. Its work may still be on disk under state/worktrees."
        )
        return out

    # Model server is up. Two independent movement signals.
    worktrees = STATE / "worktrees"
    wt_moving = _newest_write(worktrees, timedelta(minutes=FLAT_MINUTES))
    rd_moving = _newest_write(run, timedelta(minutes=FLAT_MINUTES)) if run else False
    time.sleep(CPU_SAMPLE_GAP_S)
    cpu2 = _ovms_cpu_seconds()
    cpu_moving = (cpu2 is not None and cpu1 is not None and cpu2 > cpu1)

    out["signals"].update({
        "model_cpu_before": cpu1,
        "model_cpu_after": cpu2,
        "model_cpu_climbing": cpu_moving,
        f"worktree_writes_in_{FLAT_MINUTES}min": wt_moving,
        f"run_dir_writes_in_{FLAT_MINUTES}min": rd_moving,
    })

    # OUTPUT is the primary signal, not CPU. `ovms` serves whatever is loaded, so a busy
    # model server does not prove the CODER is progressing -- and the #1365 wedge is exactly
    # "the model is up and producing nothing". Treating CPU as sufficient would call that
    # healthy, which is the failure this check exists to catch.
    output_moving = wt_moving or rd_moving
    if output_moving:
        moving = [k for k, v in (("worktree writes", wt_moving),
                                 ("run-dir writes", rd_moving)) if v]
        out["verdict"] = "HEALTHY"
        out["detail"] = "The run is producing work. Moving: " + ", ".join(moving) + "."
        return out

    if cpu_moving:
        out["verdict"] = "BUSY-BUT-PRODUCING-NOTHING"
        out["detail"] = (
            f"The model server is burning CPU but NOTHING has been written to the task "
            f"worktrees or the run directory in {FLAT_MINUTES} minutes. That is the shape of a "
            "wedged generation rather than a healthy one, and it is the case a CPU-only check "
            "would call healthy. Worth a look; nothing has been killed."
        )
        return out

    out["verdict"] = "STALLED"
    out["detail"] = (
        f"All three signals are flat: the model server burned no CPU across a "
        f"{CPU_SAMPLE_GAP_S}s sample, and nothing was written to the task worktrees or the run "
        f"directory in {FLAT_MINUTES} minutes. The run is up but is not doing anything. "
        "Nothing has been killed - that is deliberate."
    )
    return out


def render(r: dict, label: str = "run health check") -> str:
    head = {
        "HEALTHY": "The overnight run is working.",
        "FINISHED": "The overnight run finished.",
        "STALLED": "THE OVERNIGHT RUN LOOKS STUCK.",
        "STOPPED-WITHOUT-FINISHING": "THE OVERNIGHT RUN STOPPED WITHOUT FINISHING.",
        "NO-NIGHT-DIRECTORY": "NO OVERNIGHT RUN FOUND AT ALL.",
    }.get(r["verdict"], r["verdict"])
    lines = [
        f"# {label} - {head}",
        "",
        f"- **Checked:** {r['checked_at'][:19].replace('T', ' ')}",
        f"- **Run:** {r['run_dir'] or 'none'}",
        "",
        r["detail"],
        "",
        "## What was measured",
        "",
    ]
    for k, v in r["signals"].items():
        lines.append(f"- {k.replace('_', ' ')}: {v}")
    lines += [
        "",
        "*Nothing is ever killed by this check. A watchdog that acted on a blind signal once "
        "false-killed 84% of candidates, so this one reports and leaves the decision to a person.*",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--out", type=Path, help="also write a plain-language report here")
    # The heading used to be hardcoded "3am check". This probe is now scheduled at 23:05 as
    # well (the early-death check), and a report headed "3am check" written at 23:05 is a
    # sentence claiming a fact about itself that is false -- small, but it is the same class
    # of staleness this file exists to catch elsewhere.
    ap.add_argument("--label", default="run health check",
                    help="heading for the report, so a 23:05 run does not call itself the 3am check")
    args = ap.parse_args(argv)

    r = check()
    text = json.dumps(r, indent=2, default=str) if args.json else render(r, args.label)
    print(text)
    if args.out:
        try:
            args.out.parent.mkdir(parents=True, exist_ok=True)
            args.out.write_text(render(r, args.label), encoding="utf-8")
        except OSError as exc:
            print(f"could not write report: {exc}", file=sys.stderr)
    # Exit code carries the verdict for the scheduler: 0 fine, 1 needs a human.
    return 0 if r["verdict"] in ("HEALTHY", "FINISHED") else 1


if __name__ == "__main__":
    raise SystemExit(main())
