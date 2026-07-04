"""Tests for the owner-preserving file/dir DACL hardening helpers (#637).

DATA_MAP §7 items 1 & 2.  Covers :func:`ensure_owner_only_dacl` and
:func:`strip_foreign_sids_from_dir` from ``shared.security.file_dacl``.

Test groups
-----------
TestNonWindowsNoOp
    HERMETIC — always runs on every platform.  With ``_ON_WIN32`` forced False,
    both helpers are a logged no-op returning ``False`` and never raise.

TestFailSafe
    HERMETIC — always runs.  Bad input (``None``), a non-existent path, and a
    pywin32-import failure all return ``False`` without raising — the fail-safe
    invariant.  Uses monkeypatch to simulate the import failure so the path is
    exercised even on a box where pywin32 IS installed.

TestSidClassification
    HERMETIC — always runs.  Drives ``_sid_is_legitimate`` with a stub
    ``win32security`` to assert the keep/strip decision (current user kept,
    well-known kept, AppContainer kept, resolvable kept, orphaned foreign
    stripped) WITHOUT touching the real OS.

TestEnsureOwnerOnlyDaclWindows
    CONDITIONAL — skipped when pywin32 is unavailable or the platform is not
    win32.  Full round-trip against a TEMP file: asserts the resulting DACL is
    exactly (current user + SYSTEM) full control, the owner is retained
    (owner-preserving), inheritance is severed, and the op is idempotent.

TestStripForeignSidsWindows
    CONDITIONAL — skipped off-Windows / no pywin32.  Builds a clean protected
    DACL on a TEMP dir containing a synthetic orphaned foreign-SID ACE, then
    asserts ONLY the foreign ACE is removed, every legitimate principal is
    preserved (owner-preserving), and the strip is idempotent.

ALL tests:
- Operate ONLY on pytest ``tmp_path`` temp directories — never the live
  ``%LOCALAPPDATA%\\BlarAI\\`` files or the live ``certs\\`` dir.
- Make no network calls.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

import shared.security.file_dacl as file_dacl
from shared.security.file_dacl import (
    _sid_is_legitimate,
    ensure_owner_only_dacl,
    strip_foreign_sids_from_dir,
)

# ---------------------------------------------------------------------------
# Platform / availability guards (mirror test_dpapi_store.py)
# ---------------------------------------------------------------------------

_ON_WIN32: bool = sys.platform == "win32"

try:
    import ntsecuritycon  # type: ignore[import-untyped]  # noqa: F401
    import win32api  # type: ignore[import-untyped]  # noqa: F401
    import win32con  # type: ignore[import-untyped]  # noqa: F401
    import win32security  # type: ignore[import-untyped]  # noqa: F401

    _PYWIN32_AVAILABLE: bool = True
except ImportError:
    _PYWIN32_AVAILABLE = False

_SKIP_DACL = pytest.mark.skipif(
    not (_ON_WIN32 and _PYWIN32_AVAILABLE),
    reason="pywin32 not available or platform is not win32",
)

# The exact orphaned-foreign-SID domain observed in DATA_MAP §4c on certs\.
_ORPHAN_FOREIGN_SID: str = "S-1-5-21-76345465-2051216645-4251589009-2931813655"


# ===========================================================================
# TestNonWindowsNoOp — HERMETIC
# ===========================================================================


class TestNonWindowsNoOp:
    """On a non-win32 platform both helpers are a logged no-op returning False."""

    def test_ensure_owner_only_dacl_noop_off_windows(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setattr(file_dacl, "_ON_WIN32", False)
        target = tmp_path / "sessions.db"
        target.write_text("x", encoding="utf-8")
        assert ensure_owner_only_dacl(target) is False

    def test_strip_foreign_sids_noop_off_windows(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setattr(file_dacl, "_ON_WIN32", False)
        assert strip_foreign_sids_from_dir(tmp_path) is False


# ===========================================================================
# TestFailSafe — HERMETIC
# ===========================================================================


class TestFailSafe:
    """The fail-safe invariant: never raise, return False on any failure."""

    def test_ensure_bad_input_returns_false(self) -> None:
        # None is not a valid path — must not raise.
        assert ensure_owner_only_dacl(None) is False  # type: ignore[arg-type]

    def test_strip_bad_input_returns_false(self) -> None:
        assert strip_foreign_sids_from_dir(None) is False  # type: ignore[arg-type]

    def test_ensure_nonexistent_path_returns_false(self, tmp_path: Path) -> None:
        missing = tmp_path / "does-not-exist.db"
        assert ensure_owner_only_dacl(missing) is False

    def test_strip_nonexistent_path_returns_false(self, tmp_path: Path) -> None:
        missing = tmp_path / "no-such-dir"
        assert strip_foreign_sids_from_dir(missing) is False

    @pytest.mark.skipif(not _ON_WIN32, reason="exercises the win32 import branch")
    def test_ensure_pywin32_import_failure_returns_false(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """If pywin32 cannot be imported at call time, fail safe to False."""
        import builtins

        real_import = builtins.__import__

        def _boom(name: str, *args: object, **kwargs: object) -> object:
            if name.startswith("win32") or name == "ntsecuritycon":
                raise ImportError(f"simulated missing module: {name}")
            return real_import(name, *args, **kwargs)  # type: ignore[arg-type]

        target = tmp_path / "sessions.db"
        target.write_text("x", encoding="utf-8")
        monkeypatch.setattr(builtins, "__import__", _boom)
        assert ensure_owner_only_dacl(target) is False

    @pytest.mark.skipif(not _ON_WIN32, reason="exercises the win32 import branch")
    def test_strip_pywin32_import_failure_returns_false(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        import builtins

        real_import = builtins.__import__

        def _boom(name: str, *args: object, **kwargs: object) -> object:
            if name.startswith("win32"):
                raise ImportError(f"simulated missing module: {name}")
            return real_import(name, *args, **kwargs)  # type: ignore[arg-type]

        monkeypatch.setattr(builtins, "__import__", _boom)
        assert strip_foreign_sids_from_dir(tmp_path) is False


# ===========================================================================
# TestSidClassification — HERMETIC (stubbed win32security)
# ===========================================================================


class _StubSid:
    """A fake SID object identified purely by its string form."""

    def __init__(self, s: str) -> None:
        self._s = s


class _StubWin32Security:
    """Minimal win32security stand-in for _sid_is_legitimate.

    ``ConvertSidToStringSid`` returns the stub's string; ``LookupAccountSid``
    resolves SIDs in ``resolvable`` and raises for everything else (mirroring
    the real "No mapping" error for an orphaned SID).
    """

    def __init__(self, resolvable: set[str]) -> None:
        self._resolvable = resolvable

    def ConvertSidToStringSid(self, sid: object) -> str:  # noqa: N802 - win32 name
        return sid._s  # type: ignore[attr-defined]

    def LookupAccountSid(  # noqa: N802 - win32 name
        self, system: object, sid: object
    ) -> tuple[str, str, int]:
        s = sid._s  # type: ignore[attr-defined]
        if s in self._resolvable:
            return ("SomeName", "SOMEDOMAIN", 1)
        raise RuntimeError("No mapping between account names and security IDs")


def _classify(sid_str: str, *, current: str, resolvable: set[str]) -> bool:
    stub = _StubWin32Security(resolvable)
    return _sid_is_legitimate(stub, _StubSid(sid_str), _StubSid(current))


class TestSidClassification:
    """_sid_is_legitimate keeps legitimate principals and flags foreign ones."""

    _CURRENT = "S-1-5-21-4125655822-2918122917-2734753367-1001"

    def test_current_user_is_kept(self) -> None:
        assert _classify(self._CURRENT, current=self._CURRENT, resolvable=set()) is True

    @pytest.mark.parametrize(
        "wk",
        [
            "S-1-5-18",  # SYSTEM
            "S-1-5-19",  # LOCAL SERVICE
            "S-1-5-20",  # NETWORK SERVICE
            "S-1-5-32-544",  # Administrators
            "S-1-5-32-545",  # Users
            "S-1-1-0",  # Everyone
            "S-1-3-0",  # CREATOR OWNER
            "S-1-5-11",  # Authenticated Users
        ],
    )
    def test_well_known_sids_kept(self, wk: str) -> None:
        assert _classify(wk, current=self._CURRENT, resolvable=set()) is True

    def test_appcontainer_sid_kept(self) -> None:
        ac = "S-1-15-3-1024-1065365936-1281604716-3511738428-1654721687-432734479"
        assert _classify(ac, current=self._CURRENT, resolvable=set()) is True

    def test_resolvable_local_account_kept(self) -> None:
        other = "S-1-5-21-4125655822-2918122917-2734753367-1002"
        assert (
            _classify(other, current=self._CURRENT, resolvable={other}) is True
        )

    def test_orphaned_foreign_sid_is_stripped(self) -> None:
        # Not current, not well-known, not AppContainer, does not resolve.
        assert (
            _classify(_ORPHAN_FOREIGN_SID, current=self._CURRENT, resolvable=set())
            is False
        )


# ===========================================================================
# Windows round-trip helpers (used by the CONDITIONAL test classes)
# ===========================================================================


def _dacl_sid_strings(path: Path) -> list[str]:
    """Return the SID string of every ACE in *path*'s DACL."""
    sd = win32security.GetNamedSecurityInfo(
        str(path),
        win32security.SE_FILE_OBJECT,
        win32security.DACL_SECURITY_INFORMATION,
    )
    dacl = sd.GetSecurityDescriptorDacl()
    if dacl is None:
        return []
    return [
        win32security.ConvertSidToStringSid(dacl.GetAce(i)[2])
        for i in range(dacl.GetAceCount())
    ]


def _current_user_sid_str() -> str:
    token = win32security.OpenProcessToken(
        win32api.GetCurrentProcess(), win32con.TOKEN_QUERY
    )
    sid = win32security.GetTokenInformation(token, win32security.TokenUser)[0]
    return win32security.ConvertSidToStringSid(sid)


def _dacl_is_protected(path: Path) -> bool:
    """True iff *path*'s security descriptor has the PROTECTED-DACL control bit."""
    sd = win32security.GetNamedSecurityInfo(
        str(path),
        win32security.SE_FILE_OBJECT,
        win32security.DACL_SECURITY_INFORMATION,
    )
    control, _rev = sd.GetSecurityDescriptorControl()
    return bool(control & win32security.SE_DACL_PROTECTED)


# ===========================================================================
# TestEnsureOwnerOnlyDaclWindows — CONDITIONAL
# ===========================================================================


@_SKIP_DACL
class TestEnsureOwnerOnlyDaclWindows:
    """Full owner-only DACL round-trip against a TEMP file (never live data)."""

    def test_dacl_is_owner_and_system_only(self, tmp_path: Path) -> None:
        target = tmp_path / "sessions.db"
        target.write_text("payload", encoding="utf-8")

        assert ensure_owner_only_dacl(target) is True

        sids = set(_dacl_sid_strings(target))
        assert sids == {_current_user_sid_str(), "S-1-5-18"}, (
            f"expected exactly (current user + SYSTEM), got {sids}"
        )

    def test_owner_is_preserved(self, tmp_path: Path) -> None:
        """Owner-preserving invariant: current user always retains an ACE."""
        target = tmp_path / "substrate.db"
        target.write_text("payload", encoding="utf-8")

        assert ensure_owner_only_dacl(target) is True
        assert _current_user_sid_str() in _dacl_sid_strings(target)

    def test_inheritance_is_severed(self, tmp_path: Path) -> None:
        target = tmp_path / "dek_keystore.json"
        target.write_text("{}", encoding="utf-8")

        assert ensure_owner_only_dacl(target) is True
        assert _dacl_is_protected(target) is True

    def test_idempotent(self, tmp_path: Path) -> None:
        target = tmp_path / "audit.jsonl"
        target.write_text("line\n", encoding="utf-8")

        assert ensure_owner_only_dacl(target) is True
        first = _dacl_sid_strings(target)
        assert ensure_owner_only_dacl(target) is True
        second = _dacl_sid_strings(target)
        assert first == second == [_current_user_sid_str(), "S-1-5-18"]

    def test_works_on_a_directory(self, tmp_path: Path) -> None:
        """The helper also accepts a directory target (defense-in-depth)."""
        d = tmp_path / "data_dir"
        d.mkdir()

        assert ensure_owner_only_dacl(d) is True
        assert set(_dacl_sid_strings(d)) == {_current_user_sid_str(), "S-1-5-18"}


# ===========================================================================
# TestStripForeignSidsWindows — CONDITIONAL
# ===========================================================================


@_SKIP_DACL
class TestStripForeignSidsWindows:
    """Strip a synthetic orphaned foreign-SID ACE from a TEMP dir (never live)."""

    @staticmethod
    def _apply_clean_dacl_with_foreign(d: Path) -> list[str]:
        """Put a clean protected DACL on *d*: me + SYSTEM + Admins + foreign SID.

        Returns the list of SID strings present after applying it.  Using a
        protected (built-from-scratch) DACL removes inherited per-machine temp
        noise so the test is deterministic across machines.
        """
        token = win32security.OpenProcessToken(
            win32api.GetCurrentProcess(), win32con.TOKEN_QUERY
        )
        me = win32security.GetTokenInformation(token, win32security.TokenUser)[0]
        system = win32security.CreateWellKnownSid(win32security.WinLocalSystemSid)
        admins = win32security.CreateWellKnownSid(
            win32security.WinBuiltinAdministratorsSid
        )
        foreign = win32security.ConvertStringSidToSid(_ORPHAN_FOREIGN_SID)

        dacl = win32security.ACL()
        for sid in (me, system, admins, foreign):
            dacl.AddAccessAllowedAce(
                win32security.ACL_REVISION, ntsecuritycon.FILE_ALL_ACCESS, sid
            )
        sec_info = (
            win32security.DACL_SECURITY_INFORMATION
            | win32security.PROTECTED_DACL_SECURITY_INFORMATION
        )
        win32security.SetNamedSecurityInfo(
            str(d), win32security.SE_FILE_OBJECT, sec_info, None, None, dacl, None
        )
        return _dacl_sid_strings(d)

    def test_foreign_sid_is_removed(self, tmp_path: Path) -> None:
        d = tmp_path / "certs"
        d.mkdir()
        pre = self._apply_clean_dacl_with_foreign(d)
        assert _ORPHAN_FOREIGN_SID in pre  # precondition

        assert strip_foreign_sids_from_dir(d) is True

        post = _dacl_sid_strings(d)
        assert _ORPHAN_FOREIGN_SID not in post

    def test_legitimate_principals_preserved(self, tmp_path: Path) -> None:
        """Owner-preserving: current user + SYSTEM + Administrators all kept."""
        d = tmp_path / "certs"
        d.mkdir()
        self._apply_clean_dacl_with_foreign(d)

        assert strip_foreign_sids_from_dir(d) is True

        post = set(_dacl_sid_strings(d))
        assert _current_user_sid_str() in post
        assert "S-1-5-18" in post  # SYSTEM
        assert "S-1-5-32-544" in post  # Administrators

    def test_only_the_foreign_ace_is_removed(self, tmp_path: Path) -> None:
        d = tmp_path / "certs"
        d.mkdir()
        self._apply_clean_dacl_with_foreign(d)

        assert strip_foreign_sids_from_dir(d) is True

        post = set(_dacl_sid_strings(d))
        expected = {_current_user_sid_str(), "S-1-5-18", "S-1-5-32-544"}
        assert post == expected, f"strip was not surgical: {post}"

    def test_idempotent_when_already_clean(self, tmp_path: Path) -> None:
        d = tmp_path / "certs"
        d.mkdir()
        self._apply_clean_dacl_with_foreign(d)

        assert strip_foreign_sids_from_dir(d) is True
        first = _dacl_sid_strings(d)
        # Second run: no foreign SID left → success, DACL unchanged.
        assert strip_foreign_sids_from_dir(d) is True
        assert _dacl_sid_strings(d) == first

    def test_clean_dir_is_left_untouched(self, tmp_path: Path) -> None:
        """A dir with only legitimate principals is unchanged (returns True)."""
        d = tmp_path / "clean"
        d.mkdir()
        before = _dacl_sid_strings(d)
        assert strip_foreign_sids_from_dir(d) is True
        # No foreign SID was present, so the DACL is preserved as-is.
        assert _dacl_sid_strings(d) == before
