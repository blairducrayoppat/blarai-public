"""Differential probe harness for the #1067 v4 prose guard review.

Loads BOTH prose_guard.py files standalone (they import only stdlib), so the
same string can be run through main's guard and v4's guard side by side.
"""
from __future__ import annotations

import importlib.util
import sys
from types import ModuleType

MAIN = r"C:/Users/mrbla/BlarAI/shared/coordinator/prose_guard.py"
V4 = r"C:/Users/mrbla/wt-1067-v4/shared/coordinator/prose_guard.py"


def _load(name: str, path: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


pg_main = _load("pg_main", MAIN)
pg_v4 = _load("pg_v4", V4)

GUARD_MAIN = pg_main.ProseGuard()
GUARD_V4 = pg_v4.ProseGuard()

# The live-miss run shape: oracle FAILED but merged -> INCOMPLETE verdict.
TRUTH_MAIN = pg_main.RunTruth("r-incomplete", False, True, False)
TRUTH_V4 = pg_v4.RunTruth("r-incomplete", False, True, False)


def run(text: str, *, prefix: str = "INCOMPLETE: ") -> tuple[bool, str, bool, str]:
    """Return (main_accepted, main_action, v4_accepted, v4_action)."""
    full = text if text.startswith(("INCOMPLETE:", "PARKED:", "SUCCEEDED:")) else prefix + text
    d_main = GUARD_MAIN.validate_run_summary(TRUTH_MAIN, full)
    d_v4 = GUARD_V4.validate_run_summary(TRUTH_V4, full)
    return d_main.accepted, d_main.action, d_v4.accepted, d_v4.action


def report(texts, *, title: str = "", only_deltas: bool = False,
           flag_v4_accept: bool = False) -> None:
    if title:
        print(f"\n=== {title} ===")
    for t in texts:
        ma, mact, va, vact = run(t)
        if only_deltas and ma == va:
            continue
        tag = ""
        if flag_v4_accept and va:
            tag = "  <<< V4 ACCEPTS"
        elif ma and not va:
            tag = "  <<< NEW REFUSAL (v4 stricter)"
        elif not ma and va:
            tag = "  (v4 buys back)"
        print(f"main={'ACC' if ma else 'REJ':3} v4={'ACC' if va else 'REJ':3}{tag}\n    {t!r}")
