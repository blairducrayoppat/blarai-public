"""
Test-isolation fixtures for the UI Gateway test suite.

ISOLATION MANDATE (Sprint 14, EA-8 — SWAGR MINOR-4):
No test in this suite may read from or write to the real user-data directory
(%LOCALAPPDATA%\\BlarAI\\).  The ui_gateway constants module evaluates
LOCALAPPDATA at import time (SESSION_DB_PATH is a module-level constant), so
a conftest-level autouse fixture provides belt-and-suspenders protection
against any future test that forgets to patch LOCALAPPDATA explicitly.

The session_store.py build_session_store() factory also reads BLARAI_DEK_KEYSTORE
from os.environ.  Clearing that variable here ensures no test silently resolves
to the operator's production keystore.

Current state: all existing tests in this suite use :memory: or tmp_path for
the DB path, so no test presently creates real-user-dir pollution.  This
fixture locks that invariant permanently.
"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _isolate_user_data_dir(
    monkeypatch: pytest.MonkeyPatch, tmp_path_factory: pytest.TempPathFactory
) -> None:
    """Redirect all user-data env vars to a per-test temp directory.

    Applies to EVERY test in this package (autouse=True, function scope).

    Variables redirected:
      LOCALAPPDATA  — Windows path used by session_store factories and
                      SESSION_DB_PATH constants.
      HOME          — POSIX fallback for non-Windows environments.
      XDG_DATA_HOME — Explicit XDG override used on Linux CI.

    Variables unset:
      BLARAI_DEK_KEYSTORE — cleared so no test silently resolves to the real
                             production keystore path.
    """
    test_dir = tmp_path_factory.mktemp("user_data", numbered=True)
    monkeypatch.setenv("LOCALAPPDATA", str(test_dir))
    monkeypatch.setenv("HOME", str(test_dir))
    monkeypatch.setenv("XDG_DATA_HOME", str(test_dir))
    monkeypatch.delenv("BLARAI_DEK_KEYSTORE", raising=False)
