"""#758 guard lock: no AO test may reconcile the box's REAL fleet swap root.

service.start() runs the swap-recovery reconcile; the minimal test config's empty
[fleet_dispatch] roots make it FALL BACK to this box's real fleet root, and on
2026-07-07 a standing-gate run during a live battery dispatch "recovered" the
healthy swap — stopped the real OVMS mid-request and stamped RECOVERED over the
run.  The conftest autouse guards (root conftest + this package's scoped-run
belt) replace ``reconcile_at_boot_for_roots`` with a None-returning stub for
every test.  This test fails loudly if either guard is removed or renamed.

Deliberately an IDENTITY check only — actually calling the seam here would be
the very hazard the guard exists to prevent if the guard were broken.
"""

from __future__ import annotations

import shared.fleet.swap_ops as so


def test_reconcile_seam_is_stubbed_for_this_suite() -> None:
    assert so.reconcile_at_boot_for_roots.__name__ == "<lambda>", (
        "the #758 reconcile guard is NOT active — a service.start() test can now "
        "reconcile (and kill) a live fleet dispatch; restore the autouse fixture "
        "in conftest.py (root and services/assistant_orchestrator/tests)."
    )
