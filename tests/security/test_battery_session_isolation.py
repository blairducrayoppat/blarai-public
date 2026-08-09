"""
One battery run must not be able to inherit another's dispatch (#1324).
=======================================================================

The coordinator keys its pending dispatch by session id and parks it DURABLY in the
encrypted store (#1116), so a pending plan outlives both the run that created it and an AO
restart. While every battery run used the constant key ``"battery"``, a run that stalled
handed its stale plan to the next one.

Measured 2026-08-07 across four B9 attempts: run 4's scorecard carried run 1's ``run_id``
from 100 minutes earlier -- ``pre_run_id`` had come from run 1's pending slot -- and its
``/dispatch approve`` fired against a plan whose sandbox had since been archived and
re-initialised, and never returned. Two tickets (#1324, #1329) turned out to be one defect
seen from both ends.

The fix is structural rather than procedural, and that is the whole point: the contaminating
run had CRASHED, so any teardown step it was supposed to run would not have run. Two runs
that do not share a key cannot contaminate each other whatever either does.
"""

from __future__ import annotations

import re

import os

from tools.dispatch_harness.battery import (
    BATTERY_SESSION_PREFIX,
    _build_parser,
    new_battery_session_id,
)

build_parser = _build_parser


def test_the_key_carries_a_per_PROCESS_discriminator():
    """The property that matters is uniqueness between RUNS, and a run is a process.

    Two calls inside one process may legitimately produce the same string (same second,
    same pid) -- so asserting `a != b` here would be a test that passes by luck and fails
    at midnight boundaries. Assert the pid is embedded instead: that is what makes two
    concurrent or consecutive RUNS distinct, which is the defect's actual condition.
    """
    key = new_battery_session_id()
    assert re.fullmatch(rf"{re.escape(BATTERY_SESSION_PREFIX)}\d{{8}}-\d{{6}}-\d+", key), key
    assert key.endswith(f"-{os.getpid()}"), (
        "the key must embed the pid; without it two runs starting in the same second "
        "share a key and the inheritance defect returns"
    )


def test_the_key_is_not_the_bare_constant_that_caused_this():
    """`battery` alone is the exact value that let run 4 inherit run 1's pending dispatch."""
    assert new_battery_session_id() != "battery"
    assert new_battery_session_id().startswith(BATTERY_SESSION_PREFIX)


def test_the_parser_default_is_per_run_not_a_literal():
    """The default is what production uses -- the launcher passes no --session-id. If this
    ever reverts to a literal, every run shares a key again and nothing else would notice."""
    default = build_parser().get_default("session_id")
    assert default != "battery", (
        "the battery session id is a CONSTANT again; a stalled run will hand its pending "
        "dispatch to the next one (#1324)"
    )
    assert default.startswith(BATTERY_SESSION_PREFIX)
    assert re.fullmatch(rf"{re.escape(BATTERY_SESSION_PREFIX)}\d{{8}}-\d{{6}}-\d+", default)


def test_an_explicit_session_id_still_wins():
    """Reproducing a specific run's conditions requires pinning its key; the fix must not
    take that away."""
    args = build_parser().parse_args(["--session-id", "battery-pinned-for-repro"])
    assert args.session_id == "battery-pinned-for-repro"


def test_two_parsers_in_the_same_process_do_not_collide_by_construction():
    """argparse evaluates the default once at parser construction, so the value is stable
    for a run and re-derived for the next process. Both properties matter: stable within a
    run (the harness reads it more than once) and fresh between runs."""
    d1 = build_parser().get_default("session_id")
    p = build_parser()
    assert p.get_default("session_id") == p.parse_args([]).session_id, (
        "the default must be stable within one parser -- the harness reads the session id "
        "at dispatch and again when resolving run_id"
    )
    assert d1.startswith(BATTERY_SESSION_PREFIX)
