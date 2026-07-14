"""Unit tests for the launcher VM-binding residue tripwire (#836).

These tests exercise ``launcher_vm_binding_residue`` — the pure decision
function factored out of the ``_launcher_vm_binding_residue_tripwire`` session
fixture in ``conftest.py`` — to lock its contract: the three
``launcher.__main__`` VM bindings (``get_vm_state`` / ``ensure_vm_running`` /
``stop_vm``) must be the GENUINE ``launcher.vm_manager`` functions at session
end, and any that is a stranded mock must be reported by name.

Origin: 2026-07-11, #836.  ``launcher/tests/test_launcher.py``'s
``TestCleanupAtExit`` used ``monkeypatch.setattr`` on the fixture-owned
``get_vm_state`` / ``stop_vm`` names; because the shared function-scoped
``monkeypatch`` (created early for the root-conftest autouse fixtures) tears
down AFTER the ``launcher/tests`` autouse fixture restores the real functions,
the monkeypatch undo re-installed the benign RUNNING mock and stranded it on
``launcher.__main__.get_vm_state`` for the rest of the session — silently
defeating the #817 boundary tripwire's positive control (it fast-pathed on the
leaked mock and never tripped).  The leak is fixed at its source (the tests now
configure the fixture mocks); this tripwire makes any recurrence of the CLASS a
loud, self-naming failure.

The truth table below is driven with the REAL ``launcher.vm_manager`` functions
(high-fidelity — the exact objects the live fixture compares against), so a
refactor that renamed or re-homed a wrapper would also be caught.

No markers: pure logic, no IO.  Placement note: this file lives at ``tests/``
root, OUTSIDE the explicit-path standing gate
(``pytest shared/ services/ launcher/ tests/integration/ tests/security/``), so
the gate does NOT collect it — it runs in full-suite invocations (``pytest`` /
``pytest tests/``).  The standing gate exercises the tripwire through the
autouse ``_launcher_vm_binding_residue_tripwire`` session fixture in
``conftest.py``; this file locks the pure ``launcher_vm_binding_residue``
truth-table as belt-and-suspenders (mirrors ``test_port_leak_detector.py``).
"""

from __future__ import annotations

from unittest.mock import MagicMock

import launcher.vm_manager as vm_manager

from conftest import _LAUNCHER_VM_BINDINGS, launcher_vm_binding_residue

# The genuine references the live session fixture compares against.
_GENUINE: dict[str, object] = {
    name: getattr(vm_manager, name) for name in _LAUNCHER_VM_BINDINGS
}


class TestLauncherVmBindingResidue:
    """Decision-table tests for the residue tripwire's pure detector."""

    def test_all_genuine_is_no_residue(self) -> None:
        """The clean case — the most important: bindings equal to the genuine
        functions must report NOTHING, or the tripwire would fail every gate."""
        current = dict(_GENUINE)
        assert launcher_vm_binding_residue(current, _GENUINE) == {}, (
            "genuine bindings must produce an empty residue (silent pass); a "
            "false positive here would break the standing gate at session end"
        )

    def test_the_836_incident_shape_is_detected(self) -> None:
        """The exact #836 leak: get_vm_state + stop_vm stranded as benign mocks
        (ensure_vm_running untouched — no TestCleanupAtExit test monkeypatched
        it), so the residue names exactly those two and not the third."""
        leaked_get = MagicMock(name="get_vm_state")
        leaked_stop = MagicMock(name="stop_vm")
        current = dict(_GENUINE)
        current["get_vm_state"] = leaked_get
        current["stop_vm"] = leaked_stop

        residue = launcher_vm_binding_residue(current, _GENUINE)

        assert set(residue) == {"get_vm_state", "stop_vm"}
        assert residue["get_vm_state"] is leaked_get
        assert residue["stop_vm"] is leaked_stop
        assert "ensure_vm_running" not in residue

    def test_single_leaked_binding_is_named(self) -> None:
        """A single stranded mock on any one binding is caught and named."""
        leaked = MagicMock(name="ensure_vm_running")
        current = dict(_GENUINE)
        current["ensure_vm_running"] = leaked

        residue = launcher_vm_binding_residue(current, _GENUINE)

        assert residue == {"ensure_vm_running": leaked}

    def test_all_three_leaked_are_all_named(self) -> None:
        """Every stranded binding appears in the residue — the message lists all."""
        current = {name: MagicMock(name=name) for name in _LAUNCHER_VM_BINDINGS}

        residue = launcher_vm_binding_residue(current, _GENUINE)

        assert set(residue) == set(_LAUNCHER_VM_BINDINGS)

    def test_none_binding_counts_as_residue(self) -> None:
        """A missing (None) binding is not the genuine function → flagged, so a
        deleted attribute cannot masquerade as clean."""
        current = dict(_GENUINE)
        current["stop_vm"] = None

        residue = launcher_vm_binding_residue(current, _GENUINE)

        assert set(residue) == {"stop_vm"}
        assert residue["stop_vm"] is None

    def test_identity_not_equality(self) -> None:
        """The check is by identity: a distinct object that merely compares
        equal is still residue (a mock is never the genuine function object)."""
        equal_but_distinct = MagicMock(name="get_vm_state")
        equal_but_distinct.__eq__ = lambda self, other: True  # type: ignore[assignment]
        current = dict(_GENUINE)
        current["get_vm_state"] = equal_but_distinct

        residue = launcher_vm_binding_residue(current, _GENUINE)

        assert "get_vm_state" in residue
