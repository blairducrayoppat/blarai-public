"""Unit tests for the AO loopback port leak-detector decision logic (#630, Sprint 18 C6).

These tests exercise ``port_leak_verdict`` (the pure decision function factored
out of the ``_ao_port_leak_detector`` conftest fixture) to lock the
no-false-positive contract: only the free→held transition should produce a
failure signal; all other state transitions must pass silently.

No markers: these tests are fast (pure logic, no IO) with no hardware or model
dependencies.  Placement note: this file lives at ``tests/`` root, which is
OUTSIDE the explicit-path standing gate
(``pytest shared/ services/ launcher/ tests/integration/ tests/security/``), so
the standing gate does NOT collect it — it runs in full-suite invocations
(``pytest`` / ``pytest tests/``).  The standing gate exercises the leak detector
through the autouse ``_ao_port_leak_detector`` fixture in ``conftest.py`` (which
keeps the 2342/0 baseline deterministic); this file locks the pure
``port_leak_verdict`` truth-table as belt-and-suspenders.
"""

from __future__ import annotations

import os
import subprocess
import sys

import pytest

from conftest import (
    _fleet_swap_fingerprint,
    _session_descendant_pids,
    port_leak_verdict,
)


class TestPortLeakVerdict:
    """Decision-table tests for the port-leak detector's pure verdict function."""

    def test_free_to_free_is_silent_pass(self) -> None:
        """Normal standing-gate run: port was free, stays free.

        This is the most important case — it must NEVER produce a failure, or
        the detector will break the 2342/0 baseline on every clean run.
        """
        result = port_leak_verdict(held_at_start=False, held_at_end=False)
        assert result is None, (
            "free→free must return None (silent pass); "
            "got a verdict that would break the clean standing gate"
        )

    def test_free_to_held_produces_failure_message(self) -> None:
        """This session leaked a process holding port 5001.

        The detector must fail LOUD so the skip-shift is visible rather than
        silently degrading coverage on the NEXT run.
        """
        result = port_leak_verdict(held_at_start=False, held_at_end=True)
        assert result is not None, "free→held must return a non-None failure message"
        assert "5001" in result, "failure message should name the port"
        assert "FREE" in result and "HELD" in result, (
            "failure message should describe the state transition"
        )

    def test_held_to_held_is_silent_pass(self) -> None:
        """A live BlarAI instance was already running before the session.

        The boot-cascade tests correctly skip in this case; the detector must
        NOT add a second failure on top — the operator is legitimately using
        the machine.
        """
        result = port_leak_verdict(held_at_start=True, held_at_end=True)
        assert result is None, (
            "held→held must return None (pre-existing live instance is not a leak)"
        )

    def test_held_to_free_is_silent_pass(self) -> None:
        """The port was held at the start but released during the session.

        An edge case (perhaps a live BlarAI instance shut down during the run).
        No leak occurred; the detector must not raise a false alarm.
        """
        result = port_leak_verdict(held_at_start=True, held_at_end=False)
        assert result is None, "held→free must return None (no new leak)"

    def test_free_to_held_message_mentions_next_run(self) -> None:
        """The failure message should explain the downstream consequence.

        The value of a fail-loud detector is explaining *why* it matters, not
        just that it fired.  The message should mention the impact on the next
        gate run.
        """
        result = port_leak_verdict(held_at_start=False, held_at_end=True)
        assert result is not None
        # The message should hint at the skip-shift consequence.
        assert "skip" in result.lower() or "gate" in result.lower(), (
            "failure message should explain the downstream coverage impact"
        )


class TestFleetSwapAwareness:
    """The 2026-07-08 false positive: a gate spanning a live battery job's
    teardown sees free→held because the DISPATCH CYCLE restored the AO —
    the fleet's transition, never a test leak.  free→held must pass silently
    when the real fleet's swap-state advanced during the session."""

    def test_free_to_held_with_fleet_swap_change_is_silent_pass(self) -> None:
        """The exact 2026-07-08 incident shape: gate started mid-dispatch
        (AO stopped, port free), a job teardown restored the AO mid-gate,
        teardown saw the port held.  The swap-state fingerprint differs →
        the AO restore is attributed to the fleet → None."""
        result = port_leak_verdict(
            held_at_start=False, held_at_end=True, fleet_swap_changed=True
        )
        assert result is None, (
            "free→held during a live fleet swap cycle must return None — "
            "the dispatch teardown's AO restore is not a test leak"
        )

    def test_free_to_held_without_fleet_activity_still_fails(self) -> None:
        """The detector's original teeth are unchanged when the fleet was
        quiet: free→held with an unchanged swap-state is still a leak."""
        result = port_leak_verdict(
            held_at_start=False, held_at_end=True, fleet_swap_changed=False
        )
        assert result is not None, (
            "free→held with no fleet activity must still fail loud"
        )

    def test_fleet_swap_change_does_not_mask_other_transitions(self) -> None:
        """fleet_swap_changed must only ever WIDEN the silent-pass set; the
        three already-silent transitions stay silent with it set."""
        for start, end in ((False, False), (True, True), (True, False)):
            assert (
                port_leak_verdict(
                    held_at_start=start, held_at_end=end, fleet_swap_changed=True
                )
                is None
            )

    def test_default_is_fleet_quiet(self) -> None:
        """Omitting the parameter preserves the pre-2026-07-08 behavior —
        existing callers and the truth-table above are byte-identical."""
        assert port_leak_verdict(held_at_start=False, held_at_end=True) is not None

    def test_fingerprint_is_read_only_and_fail_soft(self) -> None:
        """The fingerprint probe must never raise (absent file, unreadable
        state, import trouble all → a comparable value or None)."""
        fp = _fleet_swap_fingerprint()
        assert fp is None or isinstance(fp, tuple)


class TestKillAttribution:
    """The kill must only ever hit PIDs this session spawned: tree-killing an
    unattributed port holder is how a standing gate shoots the production AO
    (the 2026-07-08 near-miss — the battery's freshly restored AO was on the
    kill list)."""

    def test_own_child_is_attributed(self) -> None:
        """A process this session spawned descends from us and is killable."""
        child = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(30)"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        try:
            owned = _session_descendant_pids([child.pid], os.getpid())
            assert owned == [child.pid], (
                "a directly spawned child must be attributed to this session"
            )
        finally:
            child.kill()
            child.wait(timeout=10)

    def test_external_pid_is_never_attributed(self) -> None:
        """A system process (PID 4 on Windows / init's kin elsewhere) does not
        descend from the test session and must be excluded from any kill."""
        externals = _session_descendant_pids([4], os.getpid())
        assert externals == [], "an external PID must never be kill-attributed"

    def test_dead_pid_is_skipped_not_raised(self) -> None:
        """A PID that exited between the port probe and the kill filter must
        be skipped silently (the detector is teardown code — it cannot raise)."""
        child = subprocess.Popen([sys.executable, "-c", "pass"])
        child.wait(timeout=10)
        assert _session_descendant_pids([child.pid], os.getpid()) == []
