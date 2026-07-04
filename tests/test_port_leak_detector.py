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

import pytest

from conftest import port_leak_verdict


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
