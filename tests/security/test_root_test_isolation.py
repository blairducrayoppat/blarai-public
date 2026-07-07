"""Root conftest isolation regression guard.

This test proves that the root ``conftest.py`` fired at process startup and
redirected every user-data env var away from the real
``%LOCALAPPDATA%\\BlarAI\\`` directory before any BlarAI module was imported.

WHY THIS TEST EXISTS
====================
The root conftest runs process-startup env mutations (not a fixture) so that
import-time module-level constants such as ``SESSION_DB_PATH`` resolve against
the throwaway temp directory rather than the operator's real user-data tree.
This test is the *teeth* of that mechanism: if someone deletes the root
conftest (or moves the mutations into a fixture), this test fails, alerting
the team before the real user-data dir is at risk again.

The data-corruption incident (Sprint 14) that motivated this guard:
dev-key-encrypted rows were written into the live ``sessions.db`` by tests
that called service startup paths.  The production key could not decrypt them
and the backend refused to start.

WHAT IS ASSERTED
================
1. ``SESSION_DB_PATH`` (an import-time module-level constant in
   ``services/ui_gateway/src/constants.py``) resolves under the
   ``blarai-pytest-userdata-`` sentinel prefix, not under any real BlarAI
   user directory.
2. ``os.environ["LOCALAPPDATA"]`` carries the ``blarai-pytest-userdata-``
   sentinel prefix.
3. ``BLARAI_DEK_KEYSTORE`` is absent from the environment.

Dependencies: stdlib + pytest only (no BlarAI runtime deps needed beyond
importing the constants module that is already part of the test suite).
"""

from __future__ import annotations

import os

from services.ui_gateway.src import constants as gw_constants

# The sentinel prefix written by the root conftest.
_SENTINEL = "blarai-pytest-userdata-"


def test_localappdata_redirected_to_test_temp_dir() -> None:
    """LOCALAPPDATA must contain the blarai-pytest-userdata- sentinel.

    If this fails, the root conftest has been deleted or the env mutation has
    been moved into a fixture (too late for import-time constants).
    """
    localappdata = os.environ.get("LOCALAPPDATA", "")
    assert _SENTINEL in localappdata, (
        f"LOCALAPPDATA does not contain the test-isolation sentinel '{_SENTINEL}'. "
        f"Got: {localappdata!r}. "
        "The root conftest.py is likely missing or its env mutations have been "
        "moved into a fixture.  Restoring conftest.py process-startup code fixes this."
    )


def test_session_db_path_resolves_under_test_temp_dir() -> None:
    """SESSION_DB_PATH must resolve under the blarai-pytest-userdata- sentinel dir.

    SESSION_DB_PATH is evaluated at import time in
    services/ui_gateway/src/constants.py.  If it points at the real BlarAI
    user dir, the root conftest's env mutations ran too late (in a fixture
    rather than at module-load).
    """
    db_path = gw_constants.SESSION_DB_PATH
    if not db_path:
        # If SESSION_DB_PATH is empty, LOCALAPPDATA was empty at import time —
        # that also means the real path was NOT used.  This is safe: check that
        # LOCALAPPDATA was already the sentinel dir (not just absent).
        localappdata = os.environ.get("LOCALAPPDATA", "")
        assert _SENTINEL in localappdata, (
            "SESSION_DB_PATH is empty AND LOCALAPPDATA does not carry the "
            f"sentinel '{_SENTINEL}' — isolation state is ambiguous.  "
            f"LOCALAPPDATA={localappdata!r}"
        )
        return

    assert _SENTINEL in db_path, (
        f"SESSION_DB_PATH does not resolve under the test-isolation sentinel "
        f"'{_SENTINEL}'. "
        f"Got: {db_path!r}. "
        "This means the constants module was imported BEFORE the root conftest "
        "could redirect LOCALAPPDATA — i.e. the root conftest.py is missing or "
        "the env mutations are inside a fixture rather than at module-load."
    )
    # Verify the path is under the test temp dir, not under the real Windows
    # user profile.  The real production path would contain the user's actual
    # LOCALAPPDATA directory (e.g. C:\Users\<user>\AppData\Local\BlarAI\).
    # The sentinel dir is a throwaway temp path; "BlarAI" as a *subfolder name*
    # is expected and correct — constants.py appends \BlarAI\sessions.db to
    # whatever LOCALAPPDATA is set to.  The safety check is that the prefix
    # (before the \BlarAI\ subfolder) is the sentinel temp dir, not the real
    # user AppData\Local directory.
    blarai_subdir_idx = db_path.find("\\BlarAI\\")
    if blarai_subdir_idx == -1:
        blarai_subdir_idx = db_path.find("/BlarAI/")
    path_prefix = db_path[:blarai_subdir_idx] if blarai_subdir_idx != -1 else db_path
    assert _SENTINEL in path_prefix, (
        f"SESSION_DB_PATH prefix (before \\BlarAI\\) does not contain the "
        f"sentinel '{_SENTINEL}'. "
        f"Prefix: {path_prefix!r}  Full path: {db_path!r}. "
        "The path appears to point into the real user AppData directory."
    )


def test_blarai_dek_keystore_not_in_environ() -> None:
    """BLARAI_DEK_KEYSTORE must be absent so no test reaches the real keystore.

    If this fails, the root conftest is not unsetting BLARAI_DEK_KEYSTORE,
    which means tests could resolve to the real production keystore path.
    """
    assert "BLARAI_DEK_KEYSTORE" not in os.environ, (
        f"BLARAI_DEK_KEYSTORE is present in the environment: "
        f"{os.environ['BLARAI_DEK_KEYSTORE']!r}. "
        "The root conftest.py should pop this variable at process startup."
    )
