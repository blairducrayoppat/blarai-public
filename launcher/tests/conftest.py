"""
Shared launcher-test guards — instance-lock + token isolation (gate integrity).

``test_launcher.py`` drives the REAL launcher ``main()`` with its dependencies
mocked, but two early production steps were never among them:

1. **The single-instance lock (#670).** The lock is repo-path-keyed
   (``<repo_root>/certs/launcher.lock``), so a pytest run from a checkout
   whose lock a LIVE BlarAI holds walked into the real refusal path — whose
   deliberate ``os._exit(1)`` (correct in production: running cleanup there
   would stop the live instance's VM) killed the entire pytest process
   mid-run. The standing gate then TRUNCATES SILENTLY: no failure, no
   summary, and a piped consumer reads the run as green (observed 2026-07-04;
   the same gate-integrity class as the port-5001 silent-skip fixed at
   C6/#630).

2. **The privilege strip (#652).** ``strip_unused_privileges`` ran for REAL
   inside the pytest process, permanently removing 20 privileges from the
   test runner's own token (``SE_PRIVILEGE_REMOVED`` — irreversible for the
   process lifetime). Among them ``SeCreateSymbolicLinkPrivilege``, which the
   ``shared/tests`` symlink tests need — so launcher tests could flip
   later-collected tests from pass to env-skip within the same run.

3. **The per-boot cert mint (#751).** ``main()`` in production posture (the
   HOST default, ``dev_mode=False``) reaches Step 1.5 and calls the REAL
   ``provision_per_boot_certs(repo_root=<repo_root>)``, which mints nine fresh
   per-boot PEMs into the checkout's REAL ``<repo_root>/certs/`` dir,
   OVERWRITING whatever is there. Any launcher test that drives ``main()`` in
   production (``test_production_happy_path`` and its siblings) re-mints those
   certs as a side effect. The ``LOCALAPPDATA`` redirect the test-isolation
   discipline relies on does NOT cover ``certs/`` — it lives in the repo, not
   under ``LOCALAPPDATA``. When the standing gate runs from the operator's LIVE
   checkout this rotates the CA out from under a running AO whose in-memory CA
   no longer matches disk → ``CERTIFICATE_VERIFY_FAILED`` (lesson 55 recurrence,
   observed 2026-07-06; confirmed empirically — one run of
   ``test_production_happy_path`` writes nine PEMs into ``<repo_root>/certs/``).

4. **The real Hyper-V VM boundary (#817).** ``_ensure_vm_for_feature`` (#788,
   ``8bea7c54``) reads the ``launcher.__main__`` module globals
   ``get_vm_state``/``ensure_vm_running`` at its point of use, while the
   pre-existing ``test_guest_parser.py`` enabled-path tests mock only the
   ``launcher.guest_parser`` import site — so every standing-gate run with the
   guest VM Off genuinely STARTED ``BlarAI-Orchestrator`` via ``Start-VM``
   (the test passed *because* of the real mutation), ``_cleanup`` never runs
   under pytest, and the VM stranded Running (Hyper-V Worker-Admin 18500
   events 10:26:00 / 14:41:06 / 23:10:51 on 2026-07-10 — the #788 c.1580
   "VM-start anomaly", root-caused by controlled repro). The #783 class in
   reverse: tests must neither kill NOR start the real VM.

5. **The real shared-pipeline build (#902).** ``main()`` Step 2.5 calls the
   REAL ``build_shared_pipeline`` — a full OpenVINO 14B GPU compile+load —
   unless a test patches it. On a model-less checkout it fails fast (so those
   tests silently passed for the WRONG reason: a Step-2.5 build failure also
   returns 1), but on the operator's models-present primary the two failure-
   path tests that never patched it (``test_policy_entrypoint_failure_returns_1``
   / ``test_orchestrator_entrypoint_failure_returns_1``) genuinely compiled
   the 14B onto the live Arc GPU mid-gate — exactly where the 2026-07-15
   full-suite kills (#902) reproduced. A unit test asserting ``main()``'s
   return code must never load a model.

6. **The fleet boot-reconcile + its OVMS kill arm (#902).** The swap-recovery
   reconcile (``shared.fleet.swap_state.reconcile_swap_state`` and its
   ``swap_ops`` boot wrappers) converges a stranded swap by disarming the
   fleet watchdog sentinel and force-stopping OVMS — kill-capable by design.
   The 2026-07-07 incident (a gate run's boot-reconcile shot a live
   production dispatch) is the class; the root conftest's
   ``_guard_fleet_reconcile`` silently no-ops ONE entry name for all tests,
   which is a single lock. ``_boot_reconcile_kill_tripwire`` below is the
   independent second lock for THIS suite: any launcher test that reaches a
   live reconcile or the OVMS kill arm fails LOUD naming #902, instead of
   silently executing (or silently skipping) a kill-capable path.

The main autouse fixture patches steps 1-5 AS SEEN BY ``launcher.__main__`` so:

* a live BlarAI can never ``os._exit`` a test run (fail-loud gate integrity);
* tests never read or write the checkout's REAL ``certs/launcher.lock``
  (worktree runs used to create one as a side effect);
* the pytest process token is never mutated by a test;
* the per-boot cert mint is REDIRECTED to a throwaway tmp dir — the REAL
  ``provision_per_boot_certs`` still runs (the boot's cert flow keeps full
  coverage), but it never writes the checkout's ``<repo_root>/certs/`` (#751);
* the real Hyper-V boundary is stubbed benign (``get_vm_state`` → RUNNING,
  ``ensure_vm_running``/``stop_vm`` → True) — ``_ensure_vm_for_feature``
  fast-paths without touching Hyper-V, and a test that WANTS other VM
  behavior patches the same names per-test as before (a decorator/per-test
  patch layers on top of this fixture and wins) (#817);
* ``build_shared_pipeline`` is stubbed to a benign SUCCEEDING build result —
  no launcher test can compile the real 14B onto the GPU, and the failure-path
  tests now reach (and test) the step they actually claim to test on EVERY
  checkout; a test that wants a specific build result patches the same name
  per-test as before (#902).

``test_instance_lock.py`` and ``test_privilege_hardening.py`` are unaffected:
they exercise ``launcher.instance_lock`` / ``launcher.privilege_hardening``
directly, and only the ``launcher.__main__`` bindings are patched here. The
production refusal semantics (refuse + hard exit WITHOUT cleanup) stay
covered by ``test_launcher.py``'s ``TestInstanceLockRefusal``, which
re-patches the lock to a refusal per-test. ``launcher/tests/test_vm_manager.py``
is likewise unaffected: it exercises ``launcher.vm_manager`` functions directly
(over a mocked ``_run_ps``), and only the ``launcher.__main__`` bindings are
patched here.
"""

from __future__ import annotations

from collections.abc import Iterator
from unittest import mock

import pytest

from launcher.instance_lock import InstanceLockResult
from launcher.vm_manager import VMState

# Imported from the SOURCE module (not ``launcher.__main__``) so this reference
# stays the genuine, unpatched cert-minting function even while the fixture
# patches the ``launcher.__main__`` binding — the redirect wrapper delegates to
# it, preserving full real-cert-flow coverage.
from shared.security.cert_provisioning import (
    provision_per_boot_certs as _real_provision_per_boot_certs,
)

_NOOP_PRIVILEGE_REPORT: dict[str, list[str]] = {
    "removed": [],
    "kept": [],
    "errors": [],
}


@pytest.fixture(autouse=True)
def _isolate_launcher_process_side_effects(
    tmp_path_factory: pytest.TempPathFactory,
) -> Iterator[None]:
    """Patch ``launcher.__main__``'s lock + token-strip + cert-mint bindings.

    The lock + privilege-strip are neutralised (see the module docstring). The
    per-boot cert mint is REDIRECTED to a throwaway tmp dir so a launcher test
    that drives ``main()`` in production posture cannot re-mint the checkout's
    REAL ``<repo_root>/certs/`` (which would orphan a live AO's in-memory CA —
    #751). The REAL ``provision_per_boot_certs`` still runs, so the boot's cert
    flow keeps full coverage; only its write target changes.
    """
    import launcher.__main__ as main_mod

    lock_dir = tmp_path_factory.mktemp("instance-lock")
    certs_dir = tmp_path_factory.mktemp("per-boot-certs")
    acquired = InstanceLockResult(acquired=True)

    def _provision_into_tmp(*_args: object, **_kwargs: object):
        """Mint REAL per-boot certs, but into a tmp dir — never the repo certs/.

        ``main()`` calls ``provision_per_boot_certs(repo_root=<repo_root>)``; the
        production ``repo_root`` / ``certs_dir`` args are deliberately ignored and
        the mint is forced into the fixture's tmp ``certs_dir``. The real function
        runs end to end and returns a genuine ``PerBootCerts``, so ``main()``
        proceeds exactly as in production (only the write target moves to tmp).
        """
        return _real_provision_per_boot_certs(certs_dir=certs_dir)

    def _benign_shared_pipeline_build(*_args: object, **_kwargs: object):
        """A benign SUCCEEDING Step-2.5 build result — never the real 14B (#902).

        ``main()`` reads ``.ok`` / ``.pipeline`` / ``.error`` off the result; a
        MagicMock with ``ok=True`` lets the boot proceed to the step each test
        actually asserts, without an OpenVINO GPU compile ever running inside the
        gate. A test that wants a specific build outcome (happy-path pipeline
        identity, a build FAILURE) patches ``launcher.__main__.build_shared_
        pipeline`` per-test exactly as before — its patch layers over this one.
        """
        return mock.MagicMock(ok=True, pipeline=mock.MagicMock(), error=None)

    with (
        mock.patch.object(
            main_mod, "lock_path_for_repo", return_value=lock_dir / "launcher.lock"
        ),
        mock.patch.object(
            main_mod, "acquire_instance_lock", return_value=acquired
        ),
        mock.patch.object(main_mod, "release_instance_lock", return_value=True),
        mock.patch.object(
            main_mod,
            "strip_unused_privileges",
            return_value=dict(_NOOP_PRIVILEGE_REPORT),
        ),
        mock.patch.object(
            main_mod, "provision_per_boot_certs", _provision_into_tmp
        ),
        # #817: the real Hyper-V boundary. RUNNING makes _ensure_vm_for_feature
        # fast-path True without a start attempt; a test wanting Off/failure
        # semantics patches these same names per-test (its patch layers on top
        # of this fixture and wins).
        mock.patch.object(
            main_mod, "get_vm_state", return_value=VMState.RUNNING
        ),
        mock.patch.object(main_mod, "ensure_vm_running", return_value=True),
        mock.patch.object(main_mod, "stop_vm", return_value=True),
        # #902: no launcher test may compile the real 14B (Step 2.5) inside the gate.
        mock.patch.object(
            main_mod, "build_shared_pipeline", _benign_shared_pipeline_build
        ),
    ):
        yield


@pytest.fixture(autouse=True)
def _boot_reconcile_kill_tripwire(
    request: pytest.FixtureRequest,
) -> Iterator[None]:
    """No launcher test may run the live boot-reconcile or its OVMS kill arm (#902).

    The swap-recovery reconcile is kill-capable by design (sentinel disarm +
    ``Stop-Process -Force`` on OVMS); a launcher UNIT test asserting ``main()``'s
    return code must never execute it against real state. The root conftest's
    ``_guard_fleet_reconcile`` already no-ops ``swap_ops.reconcile_at_boot_for_roots``
    for every unmarked test — ONE lock, and a silent one. This tripwire is the
    independent second lock (defense-in-depth) for the launcher suite: it patches
    ALL the reconcile entry points AND the kill arm with fail-loud sentinels, so a
    future unmocked path (a real ``AssistantOrchestratorService.start()``, a moved
    import seam, a dropped root guard) fails naming this hazard instead of killing
    anything — the #817 tripwire pattern, applied to the #758/#902 door.

    ``pytest.fail`` raises a BaseException-derived error, so the AO entrypoint's
    ``except Exception`` around its reconcile call cannot swallow the violation.

    Toggle proof (control tested OFF, security_by_design principle 12): outside
    ``launcher/tests`` the same functions stay callable — the REAL reconcile is
    exercised over tmp roots by ``tests/integration/test_swap_state.py`` and
    ``tests/integration/test_swap_ops.py``. The ON side is locked by
    ``launcher/tests/test_reconcile_tripwire.py``.
    """
    import shared.fleet.swap_ops as swap_ops_mod
    import shared.fleet.swap_state as swap_state_mod

    nodeid = request.node.nodeid

    def _tripwire(name: str):
        def _fail(*_args: object, **_kwargs: object) -> None:
            pytest.fail(
                f"KILL-CAPABLE fleet-swap path reached by a launcher unit test "
                f"(#902): {nodeid} called {name}. The boot-reconcile converges "
                f"stranded swaps by disarming the fleet sentinel and force-"
                f"stopping OVMS — a launcher test must never run it live (the "
                f"2026-07-07 live-dispatch kill / 2026-07-15 gate-kill class). "
                f"Fix: patch the seam your code under test reads "
                f"(AssistantOrchestratorService, or the swap_ops/swap_state "
                f"function itself) per-test; a per-test mock.patch/monkeypatch "
                f"layers over this tripwire and wins."
            )

        return _fail

    with (
        mock.patch.object(
            swap_state_mod,
            "reconcile_swap_state",
            _tripwire("swap_state.reconcile_swap_state"),
        ),
        mock.patch.object(
            swap_ops_mod, "reconcile_at_boot", _tripwire("swap_ops.reconcile_at_boot")
        ),
        mock.patch.object(
            swap_ops_mod,
            "reconcile_at_boot_for_roots",
            _tripwire("swap_ops.reconcile_at_boot_for_roots"),
        ),
        mock.patch.object(
            swap_ops_mod, "real_stop_ovms", _tripwire("swap_ops.real_stop_ovms")
        ),
    ):
        yield
