"""#902 locks — launcher unit tests can NEVER run the live boot-reconcile / OVMS kill.

The autouse tripwire (``launcher/tests/conftest.py::_boot_reconcile_kill_tripwire``)
replaces every reconcile entry point and the OVMS kill arm with ``pytest.fail``
sentinels for the whole launcher suite. These locks prove the wire actually TRIPS
(control tested ON): a launcher test that reaches any of the four kill-capable
names fails loud naming #902 instead of executing (or silently skipping) a live
sentinel-disarm / ``Stop-Process -Force``.

Control tested OFF (security_by_design principle 12): outside ``launcher/tests``
the same functions stay fully callable — the REAL ``reconcile_swap_state`` /
``reconcile_at_boot`` are exercised over tmp roots by
``tests/integration/test_swap_state.py`` and ``tests/integration/test_swap_ops.py``
(including the #902 PID-reuse refusal locks), so "tripwire installed" is
distinguishable from "reconcile unreachable everywhere".

No test here touches real fleet state: every path handed to a (tripwired) function
is a pytest tmp_path, and the tripwire fires BEFORE any argument is used.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from shared.fleet import swap_ops as so
from shared.fleet import swap_state as ss


def test_reconcile_swap_state_trips(tmp_path: Path) -> None:
    """The single kill-capable convergence door fails loud in this suite."""
    with pytest.raises(pytest.fail.Exception, match="#902"):
        ss.reconcile_swap_state(
            swap_state_path=tmp_path / "swap.json",
            sentinel_path=tmp_path / "server-should-run.txt",
            runs_dir=tmp_path / "runs",
            stop_ovms=lambda: None,
        )


def test_reconcile_at_boot_trips(tmp_path: Path) -> None:
    """The config-driven boot wrapper trips too (a moved seam cannot evade)."""
    from shared.fleet.dispatch import FleetDispatchConfig

    cfg = FleetDispatchConfig(
        scripts_dir=tmp_path / "scripts",
        queue_path=tmp_path / "state" / "fleet-queue.json",
        runs_dir=tmp_path / "state" / "fleet-runs",
        projects_dir=tmp_path / "projects",
    )
    with pytest.raises(pytest.fail.Exception, match="#902"):
        so.reconcile_at_boot(cfg)


def test_reconcile_at_boot_for_roots_trips() -> None:
    """The AO-boot entry name trips — LOUD, unlike the root conftest's silent no-op.

    The root conftest's ``_guard_fleet_reconcile`` (the first lock) replaces this
    name with a silent ``None`` for every unmarked test; inside ``launcher/tests``
    the tripwire layers OVER that no-op, so a launcher test that reaches the AO's
    boot-reconcile is a named failure, never a silently-skipped control.
    """
    with pytest.raises(pytest.fail.Exception, match="#902"):
        so.reconcile_at_boot_for_roots("", "")


def test_real_stop_ovms_trips() -> None:
    """The kill arm itself (``Stop-Process -Force`` on OVMS) fails loud."""
    with pytest.raises(pytest.fail.Exception, match="#902"):
        so.real_stop_ovms()


def test_per_test_patch_layers_over_tripwire(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Composition contract: a per-test patch layers over the tripwire and wins.

    This is the documented escape hatch (same contract as the #817 VM-boundary
    tripwire): a launcher test that legitimately needs a reconcile SEAM patches the
    name itself; it never opts the whole suite out.
    """
    monkeypatch.setattr(so, "reconcile_at_boot_for_roots", lambda *a, **k: None)
    assert so.reconcile_at_boot_for_roots("", "") is None
