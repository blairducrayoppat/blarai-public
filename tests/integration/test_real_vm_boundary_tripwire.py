"""
#817 — Contract locks for the root-conftest REAL Hyper-V VM boundary tripwire.

THE INCIDENT THIS LOCKS AGAINST
===============================
On 2026-07-10 the standing gate itself started the real ``BlarAI-Orchestrator``
VM three times in one day (Hyper-V Worker-Admin 18500 events at 10:26:00 /
14:41:06 / 23:10:51): #788's ``_ensure_vm_for_feature`` reads the
``launcher.__main__`` module globals ``get_vm_state`` / ``ensure_vm_running``
at its point of use, while the pre-existing guest-parser tests mocked only the
OLD ``launcher.guest_parser`` import site — so the enabled-path tests sailed
past their own mocks into the real primitives, ``Start-VM`` genuinely ran, and
the tests PASSED *because* Hyper-V complied.  The benign-stub fix in
``launcher/tests/conftest.py`` (fourth gate-integrity member) shields
``launcher/tests``; the root-conftest ``_real_vm_boundary_tripwire`` fixture is
the structural control for the WHOLE gate selection: any test anywhere that
reaches ``launcher.vm_manager._run_ps`` unmocked now FAILS LOUDLY naming
itself, instead of silently mutating Hyper-V.

WHAT EACH LOCK PROVES
=====================
1. The tripwire fires on an unmocked boundary reach, naming the offending
   test, the ticket (#817), and the blocked PowerShell command.
2. THE POSITIVE CONTROL: the exact pre-fix #788 hole — calling
   ``launcher.__main__._ensure_vm_for_feature`` with ``get_vm_state`` mocked
   at the OLD wrong site (``launcher.guest_parser``) — trips the wire.  This
   file deliberately lives OUTSIDE ``launcher/tests`` so the benign-stub
   autouse does NOT apply here; without the tripwire this call would reach the
   real primitives exactly as the incident did.
3. Opt-out (b): a per-test ``mock.patch`` of ``_run_ps`` — the
   ``launcher/tests/test_vm_manager.py`` pattern — layers OVER the autouse
   patch and wins.
4. Opt-out (b'): a per-test monkeypatch of the WRAPPER seams — the
   ``tests/integration/test_swap_ops.py`` pattern — composes (the wrappers
   never reach ``_run_ps``).
5. Opt-out (a): patching the ``launcher.__main__`` bindings — the
   ``launcher/tests/conftest.py`` benign-stub shape — shields
   ``_ensure_vm_for_feature`` without ever reaching vm_manager internals.
6. Opt-out (c): ``@pytest.mark.real_vm`` leaves the GENUINE ``_run_ps`` in
   place for legitimately-real supervised tiers.
7. The tripwire's exception derives from ``BaseException`` (via
   ``pytest.fail``), so a broad ``except Exception`` between the test and the
   boundary — the exact defensive shape of
   ``test_guest_boundary_hyperv._vm_running`` — cannot swallow the violation
   into a silent fallback.
8. The read-only wrappers all funnel through the one choke point (the
   mutating wrappers share the identical funnel by construction, but calling
   them here would risk a REAL Start-VM/Stop-VM if the tripwire under test
   were ever broken — the positive control exercises that family through
   ``_ensure_vm_for_feature`` behind a safety net instead).

SAFETY (worst case if the control under test is broken)
========================================================
Every direct boundary call in this file is a READ-ONLY query (``Get-VM`` /
``Get-VMNetworkAdapter`` / ``Get-VMIntegrationService``); the one test that
walks the mutating path (`test 2`) pins ``launcher.__main__.ensure_vm_running``
to a recording stub first — so even with the tripwire absent, no test here can
start, stop, or otherwise mutate the real VM.  A broken tripwire shows up as
these locks FAILING (no exception where one is required), never as a Hyper-V
mutation.
"""

from __future__ import annotations

from typing import Callable
from unittest import mock

import pytest

import launcher.vm_manager as vm_manager
from launcher.vm_manager import VMState

# Captured at import (collection) time — before any function-scoped fixture
# has patched the module — so this is the GENUINE subprocess-spawning door.
# The marker opt-out lock compares against it by identity.
_REAL_RUN_PS = vm_manager._run_ps


class TestTripwireFiresOnUnmockedBoundaryReach:
    """The fail-loud contract: unmocked reach → Failed naming test + ticket."""

    def test_unmocked_get_vm_state_fails_loud_naming_test_and_ticket(
        self,
    ) -> None:
        """An unmocked ``get_vm_state()`` call must trip the wire.

        Locks the message contract: the offending test's nodeid, the ticket
        (#817), the blocked PowerShell command, and the fix pattern must all
        be present — the failure has to hand the next builder the repair
        instructions, not just a stack trace.
        """
        with pytest.raises(pytest.fail.Exception) as excinfo:
            vm_manager.get_vm_state()
        message = str(excinfo.value)
        assert "#817" in message
        assert (
            "test_unmocked_get_vm_state_fails_loud_naming_test_and_ticket"
            in message
        ), "the tripwire must NAME the offending test"
        assert "Get-VM" in message, "the blocked command must be visible"
        assert "launcher.__main__" in message and "real_vm" in message, (
            "the fix pattern (patch the __main__ bindings / vm_manager seams "
            "per-test; real_vm marker for supervised tiers) must be spelled out"
        )

    def test_original_788_hole_is_caught(self) -> None:
        """THE POSITIVE CONTROL — the exact pre-fix hole trips the wire.

        Reproduces the incident shape: ``launcher.guest_parser.get_vm_state``
        is mocked to the OFF shape (the OLD wrong-site pattern the guest-parser
        tests used), while the ``launcher.__main__`` bindings that
        ``_ensure_vm_for_feature`` ACTUALLY reads stay unpatched.  Pre-fix,
        this exact call ran the real ``Get-VM`` then the real ``Start-VM`` and
        stranded the VM Running; with the tripwire, the first boundary touch
        (``get_vm_state`` → ``_run_ps``) fails loud instead.

        Safety net: ``launcher.__main__.ensure_vm_running`` is pinned to a
        recording stub returning False, so even if the tripwire under test
        were broken this test could never issue a real ``Start-VM`` — the
        worst case is one read-only ``Get-VM`` query.  The recorder must
        never fire: the wire trips BEFORE the start path.

        ORDER-IMMUNITY: the pre-fix world is CONSTRUCTED, not inherited —
        ``main_mod.get_vm_state`` is pinned to the genuine
        ``launcher.vm_manager.get_vm_state`` for the replay, because a full
        suite run reaches this test with a leaked benign mock on that binding
        (observed after ``launcher/tests/test_launcher.py``, 2026-07-11: the
        fast path then returns RUNNING and the wire is never touched). A
        positive control must build the world it claims to replay (the
        lesson-222 discipline, applied to the control itself).
        """
        import launcher.__main__ as main_mod
        import launcher.vm_manager as vm_manager

        ensure_calls: list[bool] = []

        with mock.patch(
            "launcher.guest_parser.get_vm_state", return_value=VMState.OFF
        ) as wrong_site_mock, mock.patch.object(
            main_mod, "get_vm_state", vm_manager.get_vm_state
        ), mock.patch.object(
            main_mod,
            "ensure_vm_running",
            side_effect=lambda: ensure_calls.append(True) or False,
        ):
            with pytest.raises(pytest.fail.Exception) as excinfo:
                main_mod._ensure_vm_for_feature("#817 tripwire positive control")

        assert "#817" in str(excinfo.value)
        # The wrong-site mock did NOT protect the real path — it was never
        # consulted (that is the seam mismatch, demonstrated live).
        wrong_site_mock.assert_not_called()
        # The wire tripped at the FIRST boundary touch — the start path
        # (and with it any possible Start-VM) was never reached.
        assert ensure_calls == []


class TestPerTestPatchesLayerOverAndWin:
    """Opt-out (b): established per-test mock patterns keep working unchanged."""

    def test_mock_patch_of_run_ps_layers_over_and_wins(self) -> None:
        """The ``launcher/tests/test_vm_manager.py`` pattern composes.

        A per-test ``mock.patch.object(vm_manager, "_run_ps", ...)`` activates
        AFTER the autouse fixture installed the tripwire, so inside the test
        body the fake — not the sentinel — answers, and its unwind restores
        the sentinel (which the fixture teardown then restores to the real
        function).  This is the composition the whole design leans on;
        losing it would break every existing vm_manager test.
        """
        with mock.patch.object(
            vm_manager, "_run_ps", return_value=(0, "Off", "")
        ) as mock_ps:
            state = vm_manager.get_vm_state()
        assert state == VMState.OFF
        mock_ps.assert_called_once()

    def test_wrapper_seam_monkeypatch_composes(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The ``tests/integration/test_swap_ops.py`` pattern composes.

        Patching the WRAPPER (``get_vm_state``) means ``_run_ps`` is never
        consulted at all — the tripwire stays armed underneath without
        firing.  This is the pattern the #744 oracle tests use.
        """
        monkeypatch.setattr(
            vm_manager, "get_vm_state", lambda *a, **k: VMState.RUNNING
        )
        assert vm_manager.get_vm_state() == VMState.RUNNING

    def test_main_bindings_patch_shields_like_launcher_conftest(self) -> None:
        """Opt-out (a): the benign-stub shape shields ``_ensure_vm_for_feature``.

        ``launcher/tests/conftest.py`` patches the ``launcher.__main__``
        BINDINGS (not vm_manager) — reproduced here per-test to prove the two
        autouse layers compose: with the bindings patched, the launcher's VM
        gate fast-paths on RUNNING and never reaches vm_manager internals, so
        the tripwire underneath never fires.  (The full launcher suite running
        green with the tripwire armed is the package-level proof; this is the
        seam-level demonstration.)
        """
        import launcher.__main__ as main_mod

        with mock.patch.object(
            main_mod, "get_vm_state", return_value=VMState.RUNNING
        ):
            assert main_mod._ensure_vm_for_feature("#817 benign-stub shape") is True


class TestRealVmMarkerOptOut:
    """Opt-out (c): the documented escape hatch for legitimately-real tiers."""

    @pytest.mark.real_vm
    def test_real_vm_marker_leaves_genuine_boundary_in_place(self) -> None:
        """Under ``@pytest.mark.real_vm`` the genuine ``_run_ps`` is live.

        Identity-compared against the reference captured at import time —
        and deliberately NEVER CALLED: this lock verifies the opt-out without
        touching PowerShell.  (The marker is for supervised/@hardware tiers
        like ``test_guest_boundary_hyperv``, which the standing gate
        deselects.)
        """
        assert vm_manager._run_ps is _REAL_RUN_PS

    def test_unmarked_test_has_tripwire_installed(self) -> None:
        """Without the marker, ``_run_ps`` is the sentinel — not the real door."""
        assert vm_manager._run_ps is not _REAL_RUN_PS


class TestTripwireCannotBeSwallowed:
    """The violation must survive defensive ``except Exception`` wrappers."""

    def test_tripwire_escapes_broad_except_exception(self) -> None:
        """A ``try/except Exception`` between test and boundary cannot eat it.

        ``tests/integration/test_guest_boundary_hyperv.py::_vm_running`` wraps
        its real ``get_vm_state`` call in ``except Exception`` (any
        vm_manager/PowerShell error → "not running").  If the tripwire raised
        a plain ``Exception``, that wrapper would convert the violation into a
        silent False and the test would keep running on a lie.  ``pytest.fail``
        raises a ``BaseException``-derived outcome precisely so it cannot be
        absorbed; this lock replicates the defensive shape and proves escape.
        """

        def _vm_running_like_defensive_wrapper() -> bool:
            try:
                return vm_manager.get_vm_state() == VMState.RUNNING
            except Exception:  # noqa: BLE001 — the shape under test
                return False

        with pytest.raises(pytest.fail.Exception):
            _vm_running_like_defensive_wrapper()

    def test_sentinel_exception_is_baseexception_not_exception(self) -> None:
        """Type-level lock for the same property (belt to the behavioral proof)."""
        assert issubclass(pytest.fail.Exception, BaseException)
        assert not issubclass(pytest.fail.Exception, Exception)


class TestChokePointCoverage:
    """Every read-only wrapper funnels through the one guarded door."""

    @pytest.mark.parametrize(
        "wrapper",
        [
            vm_manager.get_vm_state,
            vm_manager.verify_vm_zero_nic,
            vm_manager.is_guest_service_interface_enabled,
        ],
        ids=[
            "get_vm_state",
            "verify_vm_zero_nic",
            "is_guest_service_interface_enabled",
        ],
    )
    def test_read_only_wrappers_trip_the_same_wire(
        self, wrapper: Callable[[], object]
    ) -> None:
        """Each read-only vm_manager wrapper reaches ``_run_ps`` and trips.

        The mutating wrappers (``start_vm`` / ``stop_vm`` /
        ``ensure_vm_running`` / ``copy_file_to_vm``) share the identical
        funnel — every PowerShell invocation in ``vm_manager`` goes through
        ``_run_ps`` — but are deliberately NOT direct-called here: if the
        tripwire under test were broken, a direct call could genuinely
        start/stop the real VM (the very incident class this file locks
        against).  Their family is covered through the safety-netted
        positive control instead.
        """
        with pytest.raises(pytest.fail.Exception) as excinfo:
            wrapper()
        assert "#817" in str(excinfo.value)
