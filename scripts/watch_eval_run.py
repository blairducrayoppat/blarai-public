"""Content-based watcher for a detached eval/measurement run (#1663, D8).

Emits ONE line on stdout per event, and nothing while the run is healthy:

* ``PROGRESS`` every ``--progress-every`` status lines (cheap heartbeat)
* ``ERROR``    an error signature appears in any watched log
* ``STALL``    no new status line and no log growth for ``--stall-seconds``
* ``DEAD``     the PID is gone without a completion line
* ``ALERT``    a status line contains an ``--alert`` substring (e.g. job_failed)
* ``DONE``     the status file carries ``"<done-key>": true`` (exit code included)

Process presence alone is not evidence of progress (a watcher can outlive a dead
run), so every decision here reads file CONTENT and size.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from pathlib import Path

ERROR_RE = re.compile(r"Traceback|Error\b|OOM|USM Host|Killed|out of memory|RuntimeError", re.I)


def pid_alive(pid: int) -> bool:
    out = subprocess.run(
        ["tasklist", "/FI", f"PID eq {pid}", "/NH"], capture_output=True, text=True
    ).stdout
    return str(pid) in out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pid", type=int, required=True)
    ap.add_argument("--status", type=Path, required=True)
    ap.add_argument("--log", type=Path, action="append", default=[])
    ap.add_argument("--stall-seconds", type=int, default=600)
    ap.add_argument("--progress-every", type=int, default=25)
    ap.add_argument("--poll", type=int, default=10)
    ap.add_argument("--tag", default="run")
    ap.add_argument("--done-key", default="done")
    ap.add_argument("--liveness-dir", type=Path, default=None, help="any file growth under this dir counts as progress")
    ap.add_argument("--alert", action="append", default=[], help="substring in a status line that is itself an event")
    a = ap.parse_args()

    last_change = time.time()
    seen_lines = 0
    sizes = {p: 0 for p in a.log}
    offsets = {p: 0 for p in a.log}
    stalled_reported = False
    live_total = -1
    err_reported: set[str] = set()
    while True:
        done = None
        if a.status.exists():
            lines = a.status.read_text(encoding="utf-8", errors="replace").splitlines()
            for ln in lines[seen_lines:]:
                if any(sub in ln for sub in a.alert):
                    print(f"ALERT {a.tag} {ln[:200]}", flush=True)
            if len(lines) != seen_lines:
                if len(lines) // a.progress_every > seen_lines // a.progress_every:
                    last = lines[-1][:160]
                    print(f"PROGRESS {a.tag} lines={len(lines)} last={last}", flush=True)
                seen_lines = len(lines)
                last_change = time.time()
                stalled_reported = False
            for ln in lines[-3:]:
                if f'"{a.done_key}": true' in ln:
                    done = ln
        for p in a.log:
            if not p.exists():
                continue
            size = p.stat().st_size
            if size != sizes[p]:
                sizes[p] = size
                last_change = time.time()
                stalled_reported = False
                with open(p, "r", encoding="utf-8", errors="replace") as fh:
                    fh.seek(offsets[p])
                    chunk = fh.read()
                    offsets[p] = fh.tell()
                for ln in chunk.splitlines():
                    if ERROR_RE.search(ln) and ln not in err_reported:
                        err_reported.add(ln)
                        print(f"ERROR {a.tag} {p.name}: {ln[:240]}", flush=True)
        if a.liveness_dir is not None and a.liveness_dir.exists():
            total = sum(f.stat().st_size for f in a.liveness_dir.rglob("*") if f.is_file())
            if total != live_total:
                live_total = total
                last_change = time.time()
                stalled_reported = False
        if done:
            print(f"DONE {a.tag} {done[:200]}", flush=True)
            return 0
        if not pid_alive(a.pid):
            print(f"DEAD {a.tag} pid={a.pid} exited without a completion line", flush=True)
            return 1
        if not stalled_reported and time.time() - last_change > a.stall_seconds:
            stalled_reported = True
            print(
                f"STALL {a.tag} no status line or log growth for {a.stall_seconds}s "
                f"(lines={seen_lines})",
                flush=True,
            )
        time.sleep(a.poll)


if __name__ == "__main__":
    sys.exit(main())
