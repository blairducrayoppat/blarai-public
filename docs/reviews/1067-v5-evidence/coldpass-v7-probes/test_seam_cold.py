"""SEAM proof: drive the REAL run_wake_cycle entry point and capture what the
prose guard is actually handed. The author's own seam test calls _guard_prose
directly and passes the names itself, so it cannot see a broken derivation in
run_wake_cycle. This one can."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, r"C:/Users/mrbla/wt-1067-v7")

import pytest

from shared.coordinator import heartbeat_cycle as hc
from shared.coordinator.prose_guard import GuardDecision
from shared.fleet import vikunja_bridge as vb
from shared.fleet.dispatch import TaskOutcome
from shared.tests.test_heartbeat_cycle import (  # reuse the repo's own fixtures
    NOW, LOCAL_DAY, _env, _snapshot, _tri, _DraftSpy, store,  # noqa: F401
)


class _Spy:
    def __init__(self):
        self.summary_names = None
        self.annot_names = None
        self.calls = []

    def validate_run_summary(self, truth, text, *, task_results=()):
        self.summary_names = tuple(task_results)
        self.calls.append(("summary", tuple(task_results), text))
        return GuardDecision(True, "accepted")

    def validate_annotation(self, text, *, task_results=()):
        self.annot_names = tuple(task_results)
        self.calls.append(("annotation", tuple(task_results), text))
        return GuardDecision(True, "accepted")


def test_real_entry_point_hands_the_guard_the_harvested_names(tmp_path, store):
    outcomes = (
        TaskOutcome("bill-splitter", "processed", "MERGED", "RESULT: MERGED"),
        TaskOutcome("acceptance-tests", "processed", "PARKED", "RESULT: PARKED"),
    )
    snap = _snapshot(
        latest_run=_tri(vb.ReadStatus.OK, ("20260721-111715-bd", outcomes)),
    )
    draft = _DraftSpy(hc.DraftOutcome(
        status="drafted",
        text="INCOMPLETE: The run did not complete successfully.",
    ))
    spy = _Spy()
    original = hc._PROSE_GUARD
    try:
        hc._PROSE_GUARD = spy
        env = _env(tmp_path, store, snap, draft=draft,
                   read_scorecard=lambda rid: {"oracle": {"status": "FAILED"}})
        hc.run_wake_cycle(env, now=NOW, local_now=LOCAL_DAY)
    finally:
        hc._PROSE_GUARD = original

    print("\nGUARD CALLS FROM run_wake_cycle:")
    for kind, names, text in spy.calls:
        print(f"  {kind:11s} task_names={names} text={text[:60]!r}")
    assert spy.calls, "the guard was never called from the real entry point"
    assert spy.summary_names == (("bill-splitter","MERGED"),("acceptance-tests","PARKED")), spy.summary_names
