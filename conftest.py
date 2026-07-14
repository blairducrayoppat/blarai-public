"""
Root pytest conftest — BlarAI test-process isolation.

WHY THIS MUST RUN AT MODULE-LOAD, NOT IN A FIXTURE
===================================================
Several BlarAI modules evaluate ``os.environ["LOCALAPPDATA"]`` at *import time*
to compute module-level constants.  The critical example is
``services/ui_gateway/src/constants.py``, which computes ``SESSION_DB_PATH`` as
a module-level string at the moment the module is first imported.  pytest
collection imports test modules before any fixture runs — even session-scoped
fixtures — so any fixture-level redirect would arrive too late: the constant
would already have resolved against the real ``%LOCALAPPDATA%\\BlarAI\\``
directory.

The only correct fix is to mutate ``os.environ`` at the *top level of this
module* (i.e. at pytest process startup, before any import of a BlarAI
package).  The rootdir conftest (same directory as ``pyproject.toml``) is the
earliest code that pytest executes, making it the right home for this guard.

WHAT THIS DOES
==============
1. Creates a single throwaway temp directory for the entire pytest process
   (``tempfile.mkdtemp(prefix="blarai-pytest-userdata-")``).
2. Points every user-data env var to that temp dir.
3. Unsets ``BLARAI_DEK_KEYSTORE`` so no test silently resolves to the real
   production keystore path.

This is a *process-lifetime* redirect, not per-test.  Per-test redirects
(the EA-8 package conftests in ``services/assistant_orchestrator/tests/`` and
``services/ui_gateway/tests/``) remain in place as a defence-in-depth second
layer; this root conftest is the *process-startup first layer* that guards
import-time constant resolution.

REAL DIR IS SACRED
==================
The real ``%LOCALAPPDATA%\\BlarAI\\`` directory holds the operator's
TPM-sealed keystore (``dek_keystore.json``), the live session database
(``sessions.db``), and the substrate database.  Writing to it during tests
caused actual data corruption in Sprint 14: dev-key-encrypted rows were
written into ``sessions.db`` that the production key could not decrypt,
preventing the backend from starting.  This conftest ensures the real dir
is never touched regardless of which test package is running.

ENV VARS REDIRECTED
===================
- ``LOCALAPPDATA``   — Windows user-data root; used at import time by
                        ``services/ui_gateway/src/constants.py`` (SESSION_DB_PATH),
                        ``shared/secrets/dpapi_store.py`` (_LOCALAPPDATA),
                        ``launcher/__main__.py`` (_LOCALAPPDATA), and
                        ``services/assistant_orchestrator/src/entrypoint.py``
                        (_build_substrate).
- ``HOME``           — POSIX fallback; Path.home() / ".local" / "share" etc.
- ``XDG_DATA_HOME``  — Explicit XDG override respected on Linux CI.

``USERPROFILE`` and ``APPDATA`` are NOT redirected: a grep of all non-test
source in services/, shared/, and launcher/ confirmed that no data-path
resolution reads either of those variables — only ``LOCALAPPDATA`` and the
two POSIX variables above.
"""

from __future__ import annotations

import os
import socket
import tempfile
from typing import Generator

import pytest

# ---------------------------------------------------------------------------
# PROCESS-STARTUP ISOLATION — must run before any BlarAI import
# ---------------------------------------------------------------------------
# This block executes at module load time (top-level code in the rootdir
# conftest), which is before pytest begins importing test modules during
# collection.  DO NOT move this into a fixture — see module docstring.
# ---------------------------------------------------------------------------

_BLARAI_TEST_USERDATA_DIR: str = tempfile.mkdtemp(prefix="blarai-pytest-userdata-")

os.environ["LOCALAPPDATA"] = _BLARAI_TEST_USERDATA_DIR
os.environ["HOME"] = _BLARAI_TEST_USERDATA_DIR
os.environ["XDG_DATA_HOME"] = _BLARAI_TEST_USERDATA_DIR
os.environ.pop("BLARAI_DEK_KEYSTORE", None)


# ---------------------------------------------------------------------------
# AO LOOPBACK PORT LEAK DETECTOR (#630, Sprint 18 C6)
# ---------------------------------------------------------------------------
# Port 5001 is the AO (Assistant Orchestrator) loopback port.  The WinUI
# harness launches BlarAI.Desktop.exe which spawns a Python backend child
# that binds this port.  If harness teardown only kills the .NET parent (the
# prior bug), the Python child holds port 5001 after the session, making ~7
# boot-cascade / production-boot integration tests defensively skip on the
# NEXT gate run without any visible failure.
#
# This fixture converts a "silent skip-shift" into an explicit pytest failure
# by detecting the free→held delta at session boundaries.
#
# The port constant (ORCHESTRATOR_HOST_LOOPBACK_PORT = 5001) lives in
# launcher/__main__.py, but importing that module at conftest time drags in
# heavy runtime imports (BlarAIApp, VoiceEngine, etc.).  We hardcode 5001
# with an explicit comment referencing the canonical source, mirroring the
# pattern used in tests/integration/test_prompt_round_trip_host_mode.py.
_AO_LOOPBACK_PORT: int = 5001  # = launcher.__main__.ORCHESTRATOR_HOST_LOOPBACK_PORT


def _port_held(port: int) -> bool:
    """Return True iff *port* on 127.0.0.1 is currently in use.

    Uses a non-blocking bind probe — bind succeeds only when no listener
    holds the port.  Mirrors the ``_port_is_free`` helper used in the boot-
    cascade integration tests (test_boot_cascade_smoke.py, test_prompt_round_
    trip_host_mode.py).
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 0)
        sock.bind(("127.0.0.1", port))
        return False  # bind succeeded → port free
    except OSError:
        return True   # bind failed → port held
    finally:
        sock.close()


def _pids_holding_port(port: int) -> list[int]:
    """Return a list of PIDs currently bound to *port* on 127.0.0.1.

    Uses psutil when available; falls back to an empty list so the caller can
    still fail with the port number even when PSutil is absent.
    """
    pids: list[int] = []
    try:
        import psutil  # type: ignore[import]

        for conn in psutil.net_connections(kind="inet"):
            laddr = getattr(conn, "laddr", None)
            if laddr and laddr.port == port and conn.pid:
                pids.append(conn.pid)
    except Exception:  # noqa: BLE001 — best-effort
        pass
    return pids


def port_leak_verdict(
    *,
    held_at_start: bool,
    held_at_end: bool,
    fleet_swap_changed: bool = False,
) -> str | None:
    """Pure decision function for the leak-detector fixture.

    Returns a non-empty failure message when the session itself caused a new
    port hold (free→held), or ``None`` when no action is needed.

    The four transitions:
    - free→free (normal standing gate): silent pass → ``None``
    - free→held (this session leaked): FAIL → message
    - held→held (pre-existing live instance): silent pass → ``None``
    - held→free (someone released it during the session): silent pass → ``None``

    ``fleet_swap_changed`` (2026-07-08, the false positive that almost shot the
    production AO): when the REAL fleet's swap-state advanced during the
    session, a fleet dispatch cycle ran concurrently with the gate — and a
    dispatch cycle's teardown legitimately RESTARTS the AO on port 5001.  A
    gate that started mid-dispatch (port free, AO stopped by the swap) and
    ended after the job's teardown (port held, AO restored by the swap) sees
    free→held without any test having leaked anything.  That transition is the
    fleet's, not ours: silent pass.  The battery-vs-gate interference class is
    #758's; this is the same class through the detector's own door.

    This function is tested directly by test_port_leak_detector.py to lock the
    no-false-positive contract.
    """
    if not held_at_start and held_at_end:
        if fleet_swap_changed:
            return None
        return (
            f"AO loopback port {_AO_LOOPBACK_PORT} was FREE at session start "
            f"but is HELD at session end — a test in this run leaked a process "
            f"that holds the port.  This will cause boot-cascade / production-boot "
            f"tests to silently skip on the next gate run."
        )
    return None


def _fleet_swap_fingerprint() -> tuple | None:
    """Read-only fingerprint of the REAL fleet root's swap-state record.

    Returns a comparable tuple (mtime_ns, size, run_id, phase) for
    ``<agentic-setup>/state/fleet-swap/current.json``, or ``None`` when the
    file is absent or anything fails (fail-soft: an unreadable fingerprint
    compares equal across the session and preserves the pre-2026-07-08
    detector behavior).  READ-ONLY — the real fleet state is sacred during
    tests (#758); this helper must never write, create, or lock it.
    """
    try:
        from shared.fleet.dispatch import build_default_config
        from shared.fleet.swap_ops import swap_state_path

        path = swap_state_path(build_default_config())
        stat = path.stat()
        run_id = ""
        phase = ""
        try:
            import json as _json

            data = _json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                run_id = str(data.get("run_id", ""))
                phase = str(data.get("phase", ""))
        except Exception:  # noqa: BLE001 — torn read mid-swap: stat still fingerprints
            pass
        return (stat.st_mtime_ns, stat.st_size, run_id, phase)
    except Exception:  # noqa: BLE001 — absent file / import failure: no fingerprint
        return None


def _session_descendant_pids(pids: list[int], session_pid: int) -> list[int]:
    """Filter *pids* to those whose live ancestor chain contains *session_pid*.

    A leak "this session caused" is a process this session (transitively)
    spawned.  A PID whose ancestry does NOT reach the running pytest process —
    the fleet's restored AO, an operator-launched app — must never be
    tree-killed by a test run: killing an unattributed port holder is how a
    standing gate shoots the production AO (2026-07-08).  Broken parent
    chains (orphaned leaks) therefore go UNKILLED but still fail loud via the
    verdict — visibility is the primary mechanism, the kill is opportunistic.
    """
    owned: list[int] = []
    try:
        import psutil  # type: ignore[import]

        for pid in pids:
            try:
                if any(
                    p.pid == session_pid
                    for p in psutil.Process(pid).parents()
                ):
                    owned.append(pid)
            except psutil.Error:
                continue
    except Exception:  # noqa: BLE001 — no psutil: kill nothing (fail-safe)
        return []
    return owned


def _kill_leaked_pids(pids: list[int]) -> None:
    """Best-effort tree-kill of newly leaked PIDs so the next run self-heals.

    Skips all errors silently — visibility (the pytest.fail) is the primary
    mechanism; this is belt-and-suspenders cleanup only.  Callers must pass
    only PIDs attributed to THIS session (see ``_session_descendant_pids``).
    """
    try:
        from tests.harness.process_tree import terminate_process_tree

        for pid in pids:
            terminate_process_tree(pid)
    except Exception:  # noqa: BLE001
        pass


# ---------------------------------------------------------------------------
# FLEET-SWAP RECONCILE GUARD (#758 — the 2026-07-07 live-dispatch kill)
# ---------------------------------------------------------------------------
# AssistantOrchestratorService.start() runs the swap-recovery reconcile
# (reconcile_at_boot_for_roots) BEFORE the model loads.  A test config that
# leaves the [fleet_dispatch] roots empty makes that call FALL BACK to this
# box's REAL fleet root (build_default_config's compiled-in default) — the
# LOCALAPPDATA redirect above does NOT cover it.  Live consequence (2026-07-07):
# a standing-gate run during an in-flight battery dispatch "recovered" the
# healthy swap — stopped the real OVMS mid-request, disarmed the sentinel, and
# stamped RECOVERED over the live run, killing the job.  Same class as the
# sessions.db corruption this conftest exists for: the real fleet state is
# SACRED during tests.
#
# Tests that exercise the reconcile itself (over tmp roots / fakes) opt out
# with @pytest.mark.real_reconcile.


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers",
        "real_reconcile: this test exercises the swap-recovery reconcile itself "
        "(over tmp roots/fakes) and opts out of the root-conftest reconcile guard.",
    )


@pytest.fixture(autouse=True)
def _guard_fleet_reconcile(
    request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No test may reconcile (and thereby kill) the box's REAL fleet swap (#758)."""
    if request.node.get_closest_marker("real_reconcile"):
        return
    import shared.fleet.swap_ops as _so

    monkeypatch.setattr(_so, "reconcile_at_boot_for_roots", lambda *a, **k: None)


# ---------------------------------------------------------------------------
# REAL HYPER-V VM BOUNDARY TRIPWIRE (#817 — the fail-loud structural control)
# ---------------------------------------------------------------------------
# 2026-07-10: the standing gate itself STARTED the real BlarAI-Orchestrator VM
# three times in one day (Hyper-V Worker-Admin 18500 events at 10:26:00 /
# 14:41:06 / 23:10:51) — #788's ``_ensure_vm_for_feature`` reads the
# ``launcher.__main__`` module globals at its point of use, while the
# pre-existing guest-parser tests mocked only the ``launcher.guest_parser``
# import site, so the enabled-path tests sailed past their own mocks into the
# real primitives and PASSED *because* Hyper-V actually complied.  The
# same-day surgical fix (the benign-stub fourth member of
# ``launcher/tests/conftest.py``) protects ``launcher.__main__`` callers in
# ``launcher/tests`` only; THIS fixture is the structural control for the
# whole gate selection.
#
# Enforcement point: patching named wrappers at their import sites is exactly
# the pattern that failed — twice in two days (#783: tests force-STOPPED the
# live VM via an import-armed teardown; #817: tests STARTED it via a moved
# point-of-use seam).  So the sentinel sits at the ONE choke point every real
# Hyper-V operation funnels through: ``launcher.vm_manager._run_ps``, the
# module's single PowerShell door.  Every wrapper (``get_vm_state`` /
# ``start_vm`` / ``stop_vm`` / ``ensure_vm_running`` / ``verify_vm_zero_nic``
# / ``copy_file_to_vm`` / ``is_guest_service_interface_enabled``) resolves
# ``_run_ps`` through the vm_manager module namespace AT CALL TIME, so
# from-import bindings of the wrappers elsewhere (``launcher.__main__``,
# ``launcher.guest_parser``, ``launcher.guest_deploy``, and
# ``shared/fleet/swap_ops``'s lazy point-of-use imports) cannot evade it —
# a moved import seam trips the wire instead of mutating Hyper-V.
#
# The sentinel raises via ``pytest.fail`` — BaseException-derived, so a broad
# ``except Exception`` anywhere between the test and the boundary (e.g. the
# defensive wrapper in test_guest_boundary_hyperv._vm_running) cannot swallow
# the violation into a silent fallback path.
#
# Opt-out composition (all locked by
# tests/integration/test_real_vm_boundary_tripwire.py):
# - Per-test patches of ``vm_manager._run_ps`` or the wrapper seams layer
#   OVER this autouse patch and win (mock.patch / monkeypatch inside the test
#   activate after fixture setup and unwind before fixture teardown) —
#   ``launcher/tests/test_vm_manager.py`` and
#   ``tests/integration/test_swap_ops.py`` keep working unchanged.
# - ``launcher/tests``' benign-stub autouse patches the ``launcher.__main__``
#   bindings, so those tests never reach vm_manager internals at all; the two
#   fixtures patch DIFFERENT objects and compose in either order.
# - Legitimately-real tiers (the @hardware guest-boundary round-trip; future
#   supervised go-live slots) opt out explicitly with
#   ``@pytest.mark.real_vm`` (registered in pyproject.toml).
#
# NOT covered (named residuals): a test that spawns the launcher as a
# SUBPROCESS bypasses any in-process patch (those tiers are @hardware /
# supervised); ``vm_manager.request_elevation`` (UAC relaunch via
# ShellExecuteW, not a Hyper-V mutation — test_vm_manager exercises it
# directly over mocked ctypes and a function-level sentinel would false-fire).


@pytest.fixture(autouse=True)
def _real_vm_boundary_tripwire(
    request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No test may reach the REAL Hyper-V VM boundary unmocked (#817)."""
    if request.node.get_closest_marker("real_vm"):
        return
    import launcher.vm_manager as _vm

    nodeid = request.node.nodeid

    def _trip(*args: object, **kwargs: object) -> tuple[int, str, str]:
        command = args[0] if args else kwargs.get("command", "<unknown>")
        pytest.fail(
            f"REAL Hyper-V VM boundary reached by an unmocked test (#817): "
            f"{nodeid} would have executed PowerShell {command!r} against the "
            f"real BlarAI-Orchestrator VM. launcher.vm_manager._run_ps is the "
            f"choke point every real VM operation (Get-VM / Start-VM / "
            f"Stop-VM / Copy-VMFile ...) funnels through; on 2026-07-10 "
            f"exactly this path let the standing gate genuinely START the VM "
            f"(the #788 seam mismatch). Fix: patch the seam your code under "
            f"test actually reads, per-test — the launcher.__main__ bindings "
            f"(get_vm_state / ensure_vm_running / stop_vm) or the "
            f"launcher.vm_manager functions / _run_ps itself; a per-test "
            f"mock.patch / monkeypatch layers over this tripwire and wins. "
            f"Legitimately-real supervised tiers opt out with "
            f"@pytest.mark.real_vm."
        )

    monkeypatch.setattr(_vm, "_run_ps", _trip)


# ---------------------------------------------------------------------------
# LAUNCHER VM-BINDING RESIDUE TRIPWIRE (#836 — the leaked-benign-mock haunting)
# ---------------------------------------------------------------------------
# ``_ensure_vm_for_feature`` (#788) reads the ``launcher.__main__`` module
# globals ``get_vm_state`` / ``ensure_vm_running`` / ``stop_vm`` at its point of
# use.  The ``launcher/tests`` autouse fixture replaces those three names with
# benign mocks per-test and restores the genuine ``vm_manager`` functions at its
# teardown.  But a launcher test that ``monkeypatch.setattr``-s one of those
# fixture-owned names re-installs the benign mock AFTER that restore: the shared
# function-scoped ``monkeypatch`` is created early (the two autouse fixtures
# above request it), so it tears down LAST — after the launcher fixture's
# ``mock.patch.object.__exit__`` already put the real function back.  The mock
# then rides ``launcher.__main__.get_vm_state`` for the rest of the SESSION and
# silently defeats the #817 positive control downstream (its ``_ensure_vm_for_
# feature`` fast-paths on the leaked RUNNING mock and never trips the wire — the
# 2026-07-11 "DID NOT RAISE" incident, worked around by constructed-world
# pinning in ``test_real_vm_boundary_tripwire.py``, root-caused here as #836).
#
# This session-end tripwire turns that whole leak class from a silent haunting
# into a caught, self-naming defect: at teardown it asserts the three
# ``launcher.__main__`` VM bindings are still the GENUINE ``vm_manager``
# functions, and fails loud naming the residue + the fix if any is a mock.

_LAUNCHER_VM_BINDINGS: tuple[str, ...] = ("get_vm_state", "ensure_vm_running", "stop_vm")


def launcher_vm_binding_residue(
    current: dict[str, object], genuine: dict[str, object]
) -> dict[str, object]:
    """Pure decision function for the launcher VM-binding residue tripwire.

    Returns ``{name: leaked_value}`` for every binding in *current* whose value
    is NOT (by identity) the genuine ``vm_manager`` function of the same name in
    *genuine*; an empty dict means the bindings are clean.  Factored out of the
    ``_launcher_vm_binding_residue_tripwire`` fixture and locked directly by
    ``tests/test_launcher_vm_binding_residue_tripwire.py`` (mirrors the
    ``port_leak_verdict`` + ``test_port_leak_detector.py`` pattern).
    """
    return {
        name: value
        for name, value in current.items()
        if value is not genuine.get(name)
    }


@pytest.fixture(scope="session", autouse=True)
def _launcher_vm_binding_residue_tripwire() -> Generator[None, None, None]:
    """No pytest session may end with a mock stranded on a launcher VM binding (#836)."""
    yield
    import sys as _sys

    main_mod = _sys.modules.get("launcher.__main__")
    if main_mod is None:
        return  # launcher.__main__ never imported this session — nothing to check

    import launcher.vm_manager as _vm

    genuine = {name: getattr(_vm, name) for name in _LAUNCHER_VM_BINDINGS}
    current = {name: getattr(main_mod, name, None) for name in _LAUNCHER_VM_BINDINGS}
    leaked = launcher_vm_binding_residue(current, genuine)
    if leaked:
        details = ", ".join(f"{name} -> {value!r}" for name, value in leaked.items())
        pytest.fail(
            f"launcher.__main__ VM binding(s) left non-genuine at session end "
            f"(#836): {details}. A test replaced a launcher-conftest-owned name "
            f"(get_vm_state / ensure_vm_running / stop_vm) via "
            f"monkeypatch.setattr — the shared monkeypatch tears down AFTER the "
            f"launcher/tests autouse fixture restores the real function, so its "
            f"undo re-installs the benign mock and strands it for the rest of "
            f"the session, silently defeating the #817 boundary tripwire's "
            f"positive control. Fix: in the offending test, CONFIGURE the "
            f"fixture's already-installed mock (set .return_value / assert on "
            f"launcher.__main__.<name>) instead of monkeypatching the name — see "
            f"launcher/tests/test_launcher.py::TestCleanupAtExit."
        )


@pytest.fixture(scope="session", autouse=True)
def _disarm_launcher_atexit_cleanup() -> Generator[None, None, None]:
    """No pytest process may leave the launcher's production teardown armed (#783).

    Any test that drives ``launcher.__main__.main()`` arms ``_cleanup`` via
    ``atexit`` (correct in production).  At interpreter exit the test's mocks
    are long torn down, so the handler fires with REAL bindings — and the
    ``policy=always`` VM ratchet then force-stops the REAL BlarAI-Orchestrator
    VM from a test run (three gate runs did exactly that on 2026-07-09, the
    first night the VM was deliberately kept Running for the guest oracle).

    This is the test-side belt to the production-side fix (registration moved
    from module scope into ``main()``): at session teardown — while pytest
    still controls the process — unregister the handler so interpreter exit
    has nothing to fire.  ``atexit.unregister`` is a no-op if never registered.
    """
    yield
    import atexit as _atexit
    import sys as _sys

    _m = _sys.modules.get("launcher.__main__")
    if _m is not None and hasattr(_m, "_cleanup"):
        _atexit.unregister(_m._cleanup)


@pytest.fixture(scope="session", autouse=True)
def _ao_port_leak_detector() -> Generator[None, None, None]:
    """Session-scoped autouse fixture that detects AO loopback port leaks.

    Captures the free/held state of port 5001 at session start, yields for
    the full session, then evaluates the free→held delta at teardown.

    - free→free (normal standing gate): silent pass — does NOT affect the
      2342/0 baseline.
    - free→held (this session leaked a process): pytest.fail with the PID(s)
      holding the port; tree-kills the SESSION-DESCENDANT subset so the next
      run is clean (never an unattributed PID — 2026-07-08).
    - free→held while the REAL fleet's swap-state advanced during the session:
      silent pass — a concurrent dispatch cycle's teardown restored the AO
      (the fleet's transition, not a test leak; #758's class).
    - held→held (a live BlarAI instance is already running — the operator
      legitimately uses the machine): silent pass; boot-cascade tests
      correctly skip, as they always have.
    - held→free: silent pass.
    """
    held_at_start = _port_held(_AO_LOOPBACK_PORT)
    swap_fp_at_start = _fleet_swap_fingerprint()
    yield
    held_at_end = _port_held(_AO_LOOPBACK_PORT)
    swap_fp_at_end = _fleet_swap_fingerprint()

    verdict = port_leak_verdict(
        held_at_start=held_at_start,
        held_at_end=held_at_end,
        fleet_swap_changed=(swap_fp_at_start != swap_fp_at_end),
    )
    if verdict is not None:
        leaked_pids = _pids_holding_port(_AO_LOOPBACK_PORT)
        session_owned = _session_descendant_pids(leaked_pids, os.getpid())
        _kill_leaked_pids(session_owned)
        pid_clause = f" PIDs: {leaked_pids}" if leaked_pids else ""
        if leaked_pids and not session_owned:
            pid_clause += (
                " (kill withheld: none of these PIDs descend from this test "
                "session — an external process holds the port; if a live "
                "BlarAI was started during the run this is a false positive)"
            )
        pytest.fail(f"{verdict}{pid_clause}")
