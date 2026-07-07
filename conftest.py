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
) -> str | None:
    """Pure decision function for the leak-detector fixture.

    Returns a non-empty failure message when the session itself caused a new
    port hold (free→held), or ``None`` when no action is needed.

    The four cases:
    - free→free (normal standing gate): silent pass → ``None``
    - free→held (this session leaked): FAIL → message
    - held→held (pre-existing live instance): silent pass → ``None``
    - held→free (someone released it during the session): silent pass → ``None``

    This function is tested directly by test_port_leak_detector.py to lock the
    no-false-positive contract.
    """
    if not held_at_start and held_at_end:
        return (
            f"AO loopback port {_AO_LOOPBACK_PORT} was FREE at session start "
            f"but is HELD at session end — a test in this run leaked a process "
            f"that holds the port.  This will cause boot-cascade / production-boot "
            f"tests to silently skip on the next gate run."
        )
    return None


def _kill_leaked_pids(pids: list[int]) -> None:
    """Best-effort tree-kill of newly leaked PIDs so the next run self-heals.

    Skips all errors silently — visibility (the pytest.fail) is the primary
    mechanism; this is belt-and-suspenders cleanup only.
    """
    try:
        from tests.harness.process_tree import terminate_process_tree

        for pid in pids:
            terminate_process_tree(pid)
    except Exception:  # noqa: BLE001
        pass


@pytest.fixture(scope="session", autouse=True)
def _ao_port_leak_detector() -> Generator[None, None, None]:
    """Session-scoped autouse fixture that detects AO loopback port leaks.

    Captures the free/held state of port 5001 at session start, yields for
    the full session, then evaluates the free→held delta at teardown.

    - free→free (normal standing gate): silent pass — does NOT affect the
      2342/0 baseline.
    - free→held (this session leaked a process): pytest.fail with the PID(s)
      holding the port; optionally tree-kills them so the next run is clean.
    - held→held (a live BlarAI instance is already running — the operator
      legitimately uses the machine): silent pass; boot-cascade tests
      correctly skip, as they always have.
    - held→free: silent pass.
    """
    held_at_start = _port_held(_AO_LOOPBACK_PORT)
    yield
    held_at_end = _port_held(_AO_LOOPBACK_PORT)

    verdict = port_leak_verdict(held_at_start=held_at_start, held_at_end=held_at_end)
    if verdict is not None:
        leaked_pids = _pids_holding_port(_AO_LOOPBACK_PORT)
        pid_clause = f" PIDs: {leaked_pids}" if leaked_pids else ""
        _kill_leaked_pids(leaked_pids)
        pytest.fail(f"{verdict}{pid_clause}")
