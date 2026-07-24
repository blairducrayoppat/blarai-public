"""Independent cold-review harness for #1067 v6. Read-only, scratchpad-only.

Loads the v6 guard from the worktree and main's guard from a `git show` export
(main is checked out elsewhere, so the primary checkout's working file is NOT
trustworthy as "main"). Every probe asserts it cleared the verdict-echo layer.
"""
from __future__ import annotations

import importlib.util
import sys

SCRATCH = r"C:/Users/mrbla/AppData/Local/Temp/claude/C--Users-mrbla-BlarAI/82d57925-c6b8-46fc-be83-77fd7033bee2/scratchpad"
V6 = r"C:/Users/mrbla/wt-1067-v5/shared/coordinator/prose_guard.py"
MAIN = SCRATCH + "/main_prose_guard.py"


def _load(name: str, path: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


v6 = _load("pg_v6", V6)
mn = _load("pg_main", MAIN)

# INCOMPLETE: oracle failed. (merged=True is the harsher setting - it makes
# "tasks merged" prose literally true, so any acceptance I find is about the
# success claim, not about merge vocabulary.)
T6 = v6.RunTruth(run_id="20260721-111715-bd", oracle_passed=False, merged=True, parked=False)
TM = mn.RunTruth(run_id="20260721-111715-bd", oracle_passed=False, merged=True, parked=False)
assert T6.verdict() == "INCOMPLETE"
assert TM.verdict() == "INCOMPLETE"

# A PARKED run too - second verdict, same screen.
P6 = v6.RunTruth(run_id="20260721-111715-bd", oracle_passed=False, merged=False, parked=True)
assert P6.verdict() == "PARKED"

PREFIX = "INCOMPLETE: "
ECHO_FAILURES: list[str] = []
PROBES_RUN = 0


def score(body: str, prefix: str = PREFIX):
    """(v6_action, main_action) for prefix+body. Echo layer asserted cleared."""
    global PROBES_RUN
    PROBES_RUN += 1
    text = prefix + body
    d6 = v6.ProseGuard().validate_run_summary(T6, text)
    dm = mn.ProseGuard().validate_run_summary(TM, text)
    for tag, d in (("v6", d6), ("main", dm)):
        if d.action.startswith("rejected:echo"):
            ECHO_FAILURES.append(f"{tag}:{d.action} :: {text!r}")
    return d6.action, dm.action


def report(title: str, probes):
    print(f"\n=== {title} ===")
    accepted = []
    for p in probes:
        a6, am = score(p)
        if a6 == "accepted":
            accepted.append(p)
            flag = "   <<<<< V6 ACCEPTS"
        else:
            flag = ""
        print(f"  v6={a6:<40} main={am:<40} {ascii(p)}{flag}")
    return accepted


def echo_check():
    print("\n--- echo-layer assertion ---")
    print(f"probes scored: {PROBES_RUN}")
    if ECHO_FAILURES:
        print("FATAL: probes never reached the claim screen:")
        for f in ECHO_FAILURES:
            print("   ", f)
        raise SystemExit(1)
    print("OK: zero rejected:echo-* actions. Every probe reached the claim screen.")
