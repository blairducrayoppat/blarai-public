"""
Test-isolation fixtures for the Assistant Orchestrator test suite.

ISOLATION MANDATE (Sprint 14, EA-8 — SWAGR MINOR-4):
No test in this suite may read from or write to the real user-data directory
(%LOCALAPPDATA%\\BlarAI\\).  The confirmed defect: tests that call
service.start() with dev_mode=True reach _build_substrate(), which resolves
the real %LOCALAPPDATA% from os.environ and creates substrate.keystore.json
alongside substrate.db in the operator's real data directory.

Root cause: _build_substrate() calls os.environ.get("LOCALAPPDATA", ""), and
because the tests never patched that variable, the real path was used every
time load_model() succeeded (the bge-small embedder IS available on this
machine, so the code reaches the keystore-creation branch rather than the
early-return path).

Fix shape: a function-scope autouse fixture (below) runs for EVERY test in
this package.  It redirects LOCALAPPDATA, HOME, and XDG_DATA_HOME to a
per-test temp directory and unsets BLARAI_DEK_KEYSTORE so no test can
inadvertently reach the real user-data directory or the production keystore
regardless of which test forgot to patch.  This is the belt; the per-test
explicit patching already present in tests that call _build_substrate() or
build_session_store() is the suspender.
"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _guard_fleet_reconcile_scoped(monkeypatch: pytest.MonkeyPatch) -> None:
    """Scoped-run belt for the root-conftest reconcile guard (#758).

    service.start() runs reconcile_at_boot_for_roots; with the minimal test
    config's EMPTY [fleet_dispatch] roots it falls back to this box's REAL
    fleet root and can kill a live dispatch (stop the real OVMS + stamp
    RECOVERED — the 2026-07-07 incident).  The root conftest carries the
    primary guard, but a SCOPED run rooted at the AO package (#720 precedent
    above) does not load it — this duplicate covers that path.  No test in
    this package exercises the reconcile itself.
    """
    import shared.fleet.swap_ops as _so

    monkeypatch.setattr(_so, "reconcile_at_boot_for_roots", lambda *a, **k: None)


@pytest.fixture(autouse=True)
def _isolate_user_data_dir(
    monkeypatch: pytest.MonkeyPatch, tmp_path_factory: pytest.TempPathFactory
) -> None:
    """Redirect all user-data env vars to a per-test temp directory.

    Applies to EVERY test in this package (autouse=True, function scope).

    Variables redirected:
      LOCALAPPDATA  — Windows path used by _build_substrate() and the
                      ui_gateway SESSION_DB_PATH constants.
      HOME          — POSIX fallback: Path.home() / ".local" / "share" etc.
      XDG_DATA_HOME — Explicit XDG override that some code respects instead
                      of HOME on Linux CI.

    Variables unset:
      BLARAI_DEK_KEYSTORE — cleared so no test silently resolves to the real
                             production keystore path.

    The fixture uses tmp_path_factory (session-shared temp root) rather than
    the per-test tmp_path so the fixture signature avoids a request for
    tmp_path (which would shadow the tmp_path fixture in test bodies).  Each
    test gets its own sub-directory under the session temp root.
    """
    test_dir = tmp_path_factory.mktemp("user_data", numbered=True)
    monkeypatch.setenv("LOCALAPPDATA", str(test_dir))
    monkeypatch.setenv("HOME", str(test_dir))
    monkeypatch.setenv("XDG_DATA_HOME", str(test_dir))
    monkeypatch.delenv("BLARAI_DEK_KEYSTORE", raising=False)


def pytest_configure(config: pytest.Config) -> None:
    """Register the repo-root markers for SCOPED AO runs (#720).

    The repo-root ``pyproject.toml`` registers ``hardware``/``slow`` and
    deselects them by default, so the standing gate is unaffected.  But a
    scoped run rooted at the AO package (``pytest services/assistant_orchestrator/...``)
    resolves the AO ``pyproject.toml``, which enables ``--strict-markers``
    WITHOUT registering any markers — collection of a ``@pytest.mark.hardware``
    test (test_embedding_device_offload.py) would fail.  Registering here is
    idempotent with the root registration (the websearch_benchmark conftest
    precedent).
    """
    config.addinivalue_line(
        "markers",
        "hardware: requires real OpenVINO models on the GPU/NPU; deselected by default.",
    )
    config.addinivalue_line(
        "markers",
        "slow: real-hardware or long-running tests; deselected by default at the repo root.",
    )
