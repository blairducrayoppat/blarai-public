"""Cold adversarial harness for #1067 v5. Read-only.

Loads BOTH guards (v5 worktree + main) as separate modules so every probe can be
scored against each. Asserts the echo layer was actually passed on every probe:
a `rejected:echo-*` action measures the echo layer, not the claim screen.
"""
from __future__ import annotations

import importlib.util
import sys

V5 = r"C:/Users/mrbla/wt-1067-v5/shared/coordinator/prose_guard.py"
MAIN = r"C:/Users/mrbla/BlarAI/shared/coordinator/prose_guard.py"


def _load(name: str, path: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


v5 = _load("pg_v5", V5)
main = _load("pg_main", MAIN)

# INCOMPLETE run: oracle failed, tasks merged, not parked. Verdict == INCOMPLETE.
TRUTH_V5 = v5.RunTruth(run_id="20260721-111715-bd", oracle_passed=False, merged=True, parked=False)
TRUTH_MAIN = main.RunTruth(run_id="20260721-111715-bd", oracle_passed=False, merged=True, parked=False)
assert TRUTH_V5.verdict() == "INCOMPLETE", TRUTH_V5.verdict()
assert TRUTH_MAIN.verdict() == "INCOMPLETE"

PREFIX = "INCOMPLETE: "

_echo_failures: list[str] = []


def score(body: str) -> tuple[str, str]:
    """Return (v5_action, main_action) for `PREFIX + body`. Echo-asserted."""
    text = PREFIX + body
    g5 = v5.ProseGuard()
    gm = main.ProseGuard()
    d5 = g5.validate_run_summary(TRUTH_V5, text)
    dm = gm.validate_run_summary(TRUTH_MAIN, text)
    for d in (d5, dm):
        if d.action.startswith("rejected:echo"):
            _echo_failures.append(f"{d.action} :: {text!r}")
    return d5.action, dm.action


def annot(body: str) -> tuple[str, str]:
    return (
        v5.ProseGuard().validate_annotation(body).action,
        main.ProseGuard().validate_annotation(body).action,
    )


def report(title: str, probes: list[str]) -> list[str]:
    """Print a table; return the probes v5 ACCEPTS."""
    print(f"\n=== {title} ===")
    accepted = []
    for p in probes:
        a5, am = score(p)
        flag = "  <<< V5 ACCEPTS" if a5 == "accepted" else ""
        if a5 == "accepted":
            accepted.append(p)
        print(f"  v5={a5:<45} main={am:<45} {ascii(p)}{flag}")
    return accepted


def echo_check() -> None:
    print("\n--- echo-layer assertion ---")
    if _echo_failures:
        print("FATAL: probes never reached the claim screen:")
        for f in _echo_failures:
            print("   ", f)
        raise SystemExit(1)
    print("OK: every probe passed the verdict-echo layer (no rejected:echo-* seen).")
