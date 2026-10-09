"""Run the standing gate as parallel groups of whole test files (#1707), dependency-free.

The standing selection is collected ONCE, the test files are divided into N groups balanced by banked per-file
seconds (longest-first), and each group runs as its own pytest process with its own log. Every test still runs:
the groups are disjoint sets of whole files, and the run FAILS LOUD (exit 3) if the number of tests the groups
ran differs from the number the single collection found. A file pytest skips while collecting (a module-level
importorskip) is read from the collection output, assigned to a group, and counted, so it is neither dropped
nor hidden. One combined result line is printed in the form of a single pytest run, and the exit code is
non-zero if any group failed.

Files that bind a FIXED port (SERIAL_TAIL) are not run beside other groups: they run alone, after the parallel
phase, because two processes cannot both hold the port and the repository's port-leak detector fails a session
that sees the port free at its start and held at its end. Per-process data isolation comes from the repository's
root conftest, not from this runner.

A wall-clock from this runner is labelled with its group count and is NOT comparable with a sequential figure
(docs/TEST_GOVERNANCE.md section 1). Weights come from scripts/gate_weights.json; refresh them from any
`--durations=0` log with --refresh-weights LOG [LOG ...] (gzip accepted). A group that has not finished after
GATE_TIMEOUT_S is killed and the run fails.

Usage: python scripts/run_standing_gate.py [--groups 6] [--logdir DIR] [--python PY] [--refresh-weights LOG ...]
"""
from __future__ import annotations

import argparse
import gzip
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WEIGHTS = ROOT / "scripts" / "gate_weights.json"
SELECTION_ROOTS = ["shared/", "services/", "launcher/", "tests/integration/", "tests/security/"]
SELECTION_MARKERS = "not hardware and not winui and not slow"
DEFAULT_GROUPS = 6
SECONDS_PER_UNWEIGHED_TEST = 0.02   # --durations omits tests under 5 ms, so a file with no banked weight is cheap
GATE_TIMEOUT_S = 2 * 60 * 60
NO_WINDOW = 0x08000000
# Tests that bind the real loopback ports (AO 5001 / PA 5000) and skip when another process holds them.
SERIAL_TAIL = (
    "tests/integration/test_boot_cascade_smoke.py",
    "tests/integration/test_production_boot_integration.py",
    "tests/integration/test_prompt_round_trip_host_mode.py",
)

COUNT_LINE_RE = re.compile(r"^(\S+\.py): (\d+)\s*$")
TOTAL_RE = re.compile(r"^(\d+)/(\d+) tests collected(?: \((\d+) deselected\))?", re.M)
COLLECT_SKIP_RE = re.compile(r"^SKIPPED \[(\d+)\] (\S+?\.py):\d+: ", re.M)
SUMMARY_RE = re.compile(r"^=+ (?P<body>.*?) in (?P<secs>[\d.]+)s[^\n]*=+[ \t]*$", re.M)
COUNT_RE = re.compile(r"(\d+) (passed|failed|skipped|deselected|errors?|xfailed|xpassed)")
DURATION_RE = re.compile(r"^([\d.]+)s (?:call|setup|teardown)\s+(\S+)", re.M)


# --------------------------------------------------------------------------- pure functions

def parse_collect(output: str) -> tuple[dict[str, int], int, int]:
    """(tests per file, total expected to be accounted for, deselected) from `--collect-only -qq -rs` output.

    Two output shapes exist: one node id per line (the repository's `-v` addopts) or `file.py: N` per file
    (pytest's default). The 'N/M tests collected' line must equal the listed tests. A file skipped at
    collection time lists no test: it is added with 0 tests and its skip count is added to the total, because a
    group that runs the file reports that skip."""
    per_file: dict[str, int] = {}
    for line in output.splitlines():
        if "::" in line and not line.startswith((" ", "<", "=")):
            f = line.split("::", 1)[0].replace("\\", "/")
            per_file[f] = per_file.get(f, 0) + 1
        else:
            m = COUNT_LINE_RE.match(line)
            if m:
                per_file[m.group(1).replace("\\", "/")] = int(m.group(2))
    listed = sum(per_file.values())
    m = None
    for m in TOTAL_RE.finditer(output):
        pass
    total, deselected = (int(m.group(1)), int(m.group(3) or 0)) if m else (listed, 0)
    if listed != total:
        raise ValueError(f"collection lists {listed} tests but reports {total}")
    skipped_at_collection = 0
    for n, path in COLLECT_SKIP_RE.findall(output):
        per_file.setdefault(path.replace("\\", "/"), 0)
        skipped_at_collection += int(n)
    if not per_file:
        raise ValueError("the collection output lists no tests")
    return per_file, total + skipped_at_collection, deselected


def assign_groups(files: dict[str, int], weights: dict[str, float], n: int) -> list[list[str]]:
    """Longest-first greedy balance of whole files into n groups; a file with no banked weight is
    estimated from its test count. Deterministic: ties break on the file name. Within a group the files keep
    the order of `files` (the collection order): some tests leave module-level state that a later test in the
    SAME process expects to be clean, so the relative order of two files must not change."""
    cost = {f: weights.get(f, c * SECONDS_PER_UNWEIGHED_TEST) for f, c in files.items()}
    groups: list[list[str]] = [[] for _ in range(max(1, min(n, len(files) or 1)))]
    load = [0.0] * len(groups)
    for f in sorted(files, key=lambda x: (-cost[x], x)):
        i = min(range(len(groups)), key=lambda k: (load[k], k))
        groups[i].append(f)
        load[i] += cost[f]
    order = {f: i for i, f in enumerate(files)}
    return [sorted(g, key=order.__getitem__) for g in groups]


def split_serial(files: dict[str, int], serial: tuple[str, ...] = SERIAL_TAIL) -> tuple[dict[str, int], list[str]]:
    """(files for the parallel phase, serial-tail files present in the selection, in collection order)."""
    tail = [f for f in files if f in serial]
    return {f: c for f, c in files.items() if f not in serial}, tail


def parse_summary(text: str) -> dict | None:
    """Counts from pytest's LAST summary line (a line that starts with '=' and ends with '='; a test id that
    merely contains such text sits mid-line in verbose output and does not match)."""
    m = None
    for m in SUMMARY_RE.finditer(text):
        pass
    if m is None:
        return None
    counts = {"passed": 0, "failed": 0, "skipped": 0, "deselected": 0, "errors": 0, "xfailed": 0, "xpassed": 0}
    for n, k in COUNT_RE.findall(m.group("body")):
        counts["errors" if k.startswith("error") else k] += int(n)
    return {**counts, "secs": float(m.group("secs"))}


def combine(groups: list[dict | None], expected_total: int, deselected: int) -> tuple[dict, list[str]]:
    """Sum the group summaries; list every reason the run cannot be trusted.

    A teardown error is reported beside the passed test it belongs to, so `errors` can overlap the other
    counts: the run is accounted for when passed+failed+skipped+xfailed+xpassed <= expected <= that sum + errors."""
    problems = []
    tot = {"passed": 0, "failed": 0, "skipped": 0, "errors": 0, "xfailed": 0, "xpassed": 0}
    for i, g in enumerate(groups, 1):
        if g is None:
            problems.append(f"group {i} printed no pytest summary line")
            continue
        for k in tot:
            tot[k] += g[k]
    outcomes = tot["passed"] + tot["failed"] + tot["skipped"] + tot["xfailed"] + tot["xpassed"]
    if not outcomes <= expected_total <= outcomes + tot["errors"]:
        problems.append(f"the groups ran {outcomes} tests (+{tot['errors']} errors) but the single collection found {expected_total}")
    tot["deselected"] = deselected
    return tot, problems


def summary_line(tot: dict, secs: float, n_groups: int, serial_tail: bool = False) -> str:
    parts = [f"{tot[k]} {k}" for k in ("failed", "errors", "passed", "skipped", "xfailed", "xpassed") if tot[k]]
    parts += [f"{tot['deselected']} deselected"]
    return f"= {', '.join(parts)} in {secs:.2f}s (parallel x{n_groups}{' + serial tail' if serial_tail else ''}) ="


def exit_code(problems: list[str], bad_rc: list[int], tot: dict) -> int:
    """3: the run cannot be trusted (a count mismatch, a missing summary, a timeout). 1: tests failed or a group
    exited non-zero. 0: every selected test ran and every group exited cleanly."""
    if problems:
        return 3
    return 1 if bad_rc or tot["failed"] or tot["errors"] else 0


def group_rc_ok(rc: int, summary: dict | None) -> bool:
    """A group's exit code is acceptable at 0, or at 5 (pytest's 'no tests ran') when every file it was given was
    skipped at collection and its counts show no failure and no error."""
    if rc == 0:
        return True
    return rc == 5 and summary is not None and not summary["failed"] and not summary["errors"]


def weights_from_logs(logs: list[Path]) -> dict[str, float]:
    acc: dict[str, float] = {}
    for p in logs:
        opener = gzip.open if p.suffix == ".gz" else open
        text = opener(p, "rt", encoding="utf-8", errors="replace").read()
        for dur, node in DURATION_RE.findall(text):
            f = node.split("::")[0].replace("\\", "/")
            acc[f] = acc.get(f, 0.0) + float(dur) / len(logs)
    return {k: round(v, 2) for k, v in sorted(acc.items())}


def load_weights(path: Path) -> dict[str, float]:
    """Banked per-file seconds. A missing file means no balance information (still correct, only slower);
    a file that exists but cannot be read is an error, never a silent fallback."""
    if not path.is_file():
        return {}
    try:
        w = json.loads(path.read_text(encoding="utf-8"))["seconds_per_file"]
        return {str(k): float(v) for k, v in w.items()}
    except (ValueError, KeyError, TypeError, AttributeError) as exc:
        raise SystemExit(f"{path} is not a weights file ({type(exc).__name__}: {exc}); regenerate it with --refresh-weights")


# --------------------------------------------------------------------------- running

def pytest_args(python: str, targets: list[str], extra: list[str]) -> list[str]:
    return [python, "-u", "-m", "pytest", *targets, "-m", SELECTION_MARKERS, "-p", "no:cacheprovider", *extra]


def collect(python: str, cwd: Path, targets: list[str]) -> tuple[dict[str, int], int, int]:
    r = subprocess.run(pytest_args(python, targets, ["--collect-only", "-qq", "-rs"]), cwd=cwd, capture_output=True,
                       text=True, encoding="utf-8", errors="replace", creationflags=NO_WINDOW)
    if r.returncode != 0:
        raise SystemExit(f"collection failed (exit {r.returncode}); no group was started:\n{r.stdout[-1500:]}{r.stderr[-500:]}")
    return parse_collect(r.stdout)


def run_phase(python: str, cwd: Path, groups: list[list[str]], logdir: Path, tag: str,
              timeout_s: float = GATE_TIMEOUT_S) -> list[tuple[int, str]]:
    """Run each group as its own process, wait for all, and make sure none outlives this call."""
    logdir.mkdir(parents=True, exist_ok=True)
    procs: list[tuple[subprocess.Popen, object, Path]] = []
    results: list[tuple[int, str]] = []
    try:
        for i, files in enumerate(groups, 1):
            env = {**os.environ, "PYTHONUNBUFFERED": "1"}
            log = logdir / f"{tag}{i}.log"
            out = log.open("wb")
            procs.append((subprocess.Popen(pytest_args(python, files, ["--durations=0", "-rfEs"]), cwd=cwd, env=env,
                                           stdout=out, stderr=subprocess.STDOUT, creationflags=NO_WINDOW), out, log))
        deadline = time.monotonic() + timeout_s
        for p, out, log in procs:
            try:
                rc = p.wait(timeout=max(0.0, deadline - time.monotonic()))
            except subprocess.TimeoutExpired:
                rc = -9
                with log.open("ab") as f:
                    f.write(f"\nGATE TIMEOUT: this group had not finished after {timeout_s:.0f}s and was killed\n".encode())
            out.close()
            results.append((rc, log.read_text(encoding="utf-8", errors="replace")))
    finally:
        for p, out, _log in procs:
            if p.poll() is None:
                subprocess.run(["taskkill", "/PID", str(p.pid), "/T", "/F"], capture_output=True, creationflags=NO_WINDOW)
            if not out.closed:
                out.close()
    return results


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--groups", type=int, default=DEFAULT_GROUPS)
    ap.add_argument("--logdir", default=None)
    ap.add_argument("--python", default=sys.executable)
    ap.add_argument("--cwd", default=str(ROOT))
    ap.add_argument("--roots", nargs="*", default=SELECTION_ROOTS)
    ap.add_argument("--weights", default=str(WEIGHTS))
    ap.add_argument("--timeout-s", type=float, default=GATE_TIMEOUT_S)
    ap.add_argument("--refresh-weights", nargs="+", metavar="LOG")
    a = ap.parse_args(argv)
    if a.refresh_weights:
        w = weights_from_logs([Path(x) for x in a.refresh_weights])
        Path(a.weights).write_text(json.dumps({"seconds_per_file": w}, indent=1) + "\n", encoding="utf-8")
        print(f"{len(w)} files, {sum(w.values()):.0f} s -> {a.weights}")
        return 0
    cwd = Path(a.cwd)
    weights = load_weights(Path(a.weights))
    logdir = Path(a.logdir) if a.logdir else Path(os.environ.get("TEMP", ".")) / f"standing-gate-{time.strftime('%Y%m%d-%H%M%S')}"
    t0 = time.monotonic()
    files, expected, deselected = collect(a.python, cwd, a.roots)
    parallel_files, tail = split_serial(files, SERIAL_TAIL)
    groups = assign_groups(parallel_files, weights, a.groups)
    print(f"collected {expected} tests in {len(files)} files ({deselected} deselected); {len(groups)} groups"
          f"{' + a serial tail of ' + str(len(tail)) + ' files' if tail else ''}; logs in {logdir}", flush=True)
    results = run_phase(a.python, cwd, groups, logdir, "group", a.timeout_s)
    if tail:
        results += run_phase(a.python, cwd, [tail], logdir, "tail", a.timeout_s)
    summaries = [parse_summary(text) for _rc, text in results]
    tot, problems = combine(summaries, expected, deselected)
    for ln in (ln for _rc, text in results for ln in text.splitlines() if ln.startswith(("FAILED ", "ERROR "))):
        print(ln)
    problems += [f"group {i} timed out" for i, (rc, _t) in enumerate(results, 1) if rc == -9]
    print(summary_line(tot, time.monotonic() - t0, len(groups), bool(tail)))
    for pr in problems:
        print("GATE PROBLEM: " + pr)
    bad = [i for i, (rc, _t) in enumerate(results, 1) if not group_rc_ok(rc, summaries[i - 1])]
    for i in bad:
        print(f"GATE: group {i} exited with code {results[i - 1][0]} although its counts show no failure")
    return exit_code(problems, bad, tot)


if __name__ == "__main__":
    raise SystemExit(main())
