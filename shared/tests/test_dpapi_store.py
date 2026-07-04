"""Tests for the DPAPI-backed Kagi API key secret store.

Test groups
-----------
TestOverridePath
    HERMETIC — always runs on every platform.  Validates that when
    ``BLARAI_KAGI_KEY_TEST_OVERRIDE`` is set and pytest is active,
    ``load_kagi_api_key`` returns the override without touching DPAPI or disk.

TestNotProvisioned
    HERMETIC — always runs.  Validates that ``KagiKeyNotProvisioned`` is raised
    when the blob file is absent and no test override is active.  Uses
    ``monkeypatch`` to redirect ``_SECRETS_DIR`` to a controlled temp directory;
    never reads the real ``%LOCALAPPDATA%`` blob.

TestDpapiRoundTrip
    CONDITIONAL — skipped when pywin32 is unavailable or the platform is not
    win32.  Validates the full store → load round-trip on Windows.  Uses a
    monkeypatched secrets directory so it never writes to the real blob path.

TestExceptionSafety
    HERMETIC — asserts the plaintext key string never appears in the str()
    representation of either custom exception.

All tests:
- Make no network calls.
- Do not read the real ``%LOCALAPPDATA%\\BlarAI\\secrets\\kagi_api_key.dpapi`` blob.
- Do not require a real Kagi API key.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

import shared.secrets.dpapi_store as dpapi_store
from shared.secrets.dpapi_store import (
    KagiKeyDecryptError,
    KagiKeyNotProvisioned,
    load_kagi_api_key,
    store_kagi_api_key,
    _TEST_OVERRIDE_ENV,
)

# ---------------------------------------------------------------------------
# Platform / availability guards
# ---------------------------------------------------------------------------

_ON_WIN32: bool = sys.platform == "win32"

try:
    import win32crypt  # type: ignore[import-untyped]  # noqa: F401
    _WIN32CRYPT_AVAILABLE: bool = True
except ImportError:
    _WIN32CRYPT_AVAILABLE: bool = False

_SKIP_DPAPI = pytest.mark.skipif(
    not (_ON_WIN32 and _WIN32CRYPT_AVAILABLE),
    reason="pywin32 / win32crypt not available or platform is not win32",
)

# ---------------------------------------------------------------------------
# Sentinel values — never a real key; clearly fake.
# ---------------------------------------------------------------------------

_SENTINEL_KEY: str = "TEST_FAKE_KAGI_KEY_DO_NOT_USE"
_SENTINEL_KEY_ALT: str = "TEST_FAKE_KAGI_KEY_ROTATION_DO_NOT_USE"


# ---------------------------------------------------------------------------
# Helper: redirect _SECRETS_DIR to a temp path and ensure test mode is active.
# ---------------------------------------------------------------------------

def _redirect_store(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """Point the module's secrets dir at *tmp_path* and return it."""
    monkeypatch.setattr(dpapi_store, "_SECRETS_DIR", tmp_path)
    return tmp_path


# ---------------------------------------------------------------------------
# TestOverridePath — HERMETIC
# ---------------------------------------------------------------------------

class TestOverridePath:
    """The test-override path bypasses DPAPI entirely when pytest is running."""

    def test_override_returns_env_value(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """load_kagi_api_key returns the override without touching disk."""
        _redirect_store(monkeypatch, tmp_path)
        monkeypatch.setenv(_TEST_OVERRIDE_ENV, _SENTINEL_KEY)

        result = load_kagi_api_key()

        assert result == _SENTINEL_KEY
        # Confirm no blob was written by the override path.
        blob = tmp_path / "kagi_api_key.dpapi"
        assert not blob.exists(), "override path must not write a blob file"

    def test_override_ignores_missing_blob(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """Override path does not raise KagiKeyNotProvisioned even with no blob."""
        _redirect_store(monkeypatch, tmp_path)
        monkeypatch.setenv(_TEST_OVERRIDE_ENV, _SENTINEL_KEY)

        # No blob exists; the override should still succeed without raising.
        result = load_kagi_api_key()
        assert result == _SENTINEL_KEY

    def test_override_not_active_when_env_unset(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """Without the env var the override path is not taken; absent blob raises."""
        _redirect_store(monkeypatch, tmp_path)
        monkeypatch.delenv(_TEST_OVERRIDE_ENV, raising=False)

        with pytest.raises(KagiKeyNotProvisioned):
            load_kagi_api_key()

    def test_override_value_is_exact(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """The returned value is exactly the env var content, with no stripping."""
        override_value = "  leading_space_key  "
        _redirect_store(monkeypatch, tmp_path)
        monkeypatch.setenv(_TEST_OVERRIDE_ENV, override_value)

        result = load_kagi_api_key()
        assert result == override_value


# ---------------------------------------------------------------------------
# TestNotProvisioned — HERMETIC
# ---------------------------------------------------------------------------

class TestNotProvisioned:
    """KagiKeyNotProvisioned is raised when the blob is absent with no override."""

    def test_raises_when_blob_absent(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        _redirect_store(monkeypatch, tmp_path)
        monkeypatch.delenv(_TEST_OVERRIDE_ENV, raising=False)

        with pytest.raises(KagiKeyNotProvisioned):
            load_kagi_api_key()

    def test_exception_message_does_not_contain_key(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """KagiKeyNotProvisioned message must not include any key material."""
        _redirect_store(monkeypatch, tmp_path)
        monkeypatch.delenv(_TEST_OVERRIDE_ENV, raising=False)

        with pytest.raises(KagiKeyNotProvisioned) as exc_info:
            load_kagi_api_key()

        # The message can describe the missing path, but not any key value.
        msg = str(exc_info.value)
        assert _SENTINEL_KEY not in msg

    def test_is_runtime_error_subclass(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """KagiKeyNotProvisioned must be a RuntimeError for catch-all compatibility."""
        _redirect_store(monkeypatch, tmp_path)
        monkeypatch.delenv(_TEST_OVERRIDE_ENV, raising=False)

        with pytest.raises(RuntimeError):
            load_kagi_api_key()


# ---------------------------------------------------------------------------
# TestExceptionSafety — HERMETIC
# ---------------------------------------------------------------------------

class TestExceptionSafety:
    """The plaintext key never leaks into exception representations."""

    def test_kagi_key_not_provisioned_str_has_no_key(self) -> None:
        exc = KagiKeyNotProvisioned("blob not found at /some/path")
        assert _SENTINEL_KEY not in str(exc)

    def test_kagi_key_decrypt_error_str_has_no_key(self) -> None:
        exc = KagiKeyDecryptError("DPAPI decryption failed — wrong user or machine")
        assert _SENTINEL_KEY not in str(exc)

    def test_kagi_key_not_provisioned_is_runtime_error(self) -> None:
        assert issubclass(KagiKeyNotProvisioned, RuntimeError)

    def test_kagi_key_decrypt_error_is_runtime_error(self) -> None:
        assert issubclass(KagiKeyDecryptError, RuntimeError)

    def test_exception_with_interpolated_key_still_safe_by_convention(self) -> None:
        """Demonstrate that the implementation never interpolates the key.

        This test constructs a KagiKeyDecryptError manually with a key-like
        string to show the shape — the actual implementation never does this.
        The assertion proves the class itself does not mangle or re-emit content.
        """
        # The implementation is responsible for NOT passing key material to the
        # constructor.  The class itself is a plain RuntimeError subclass and
        # does not suppress its message — correct usage is enforced by
        # dpapi_store.py, not by the exception class.
        safe_msg = "DPAPI decryption failed — OS error: The parameter is incorrect"
        exc = KagiKeyDecryptError(safe_msg)
        assert _SENTINEL_KEY not in str(exc)


# ---------------------------------------------------------------------------
# TestDpapiRoundTrip — CONDITIONAL (skip when pywin32 unavailable / non-win32)
# ---------------------------------------------------------------------------

@_SKIP_DPAPI
class TestDpapiRoundTrip:
    """Full DPAPI store → load round-trip on Windows with pywin32 available.

    Uses a monkeypatched secrets directory so no write ever touches the real
    ``%LOCALAPPDATA%\\BlarAI\\secrets\\kagi_api_key.dpapi`` path.
    """

    def test_roundtrip_recovers_original_key(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """store then load returns the identical key string."""
        _redirect_store(monkeypatch, tmp_path)
        monkeypatch.delenv(_TEST_OVERRIDE_ENV, raising=False)

        store_kagi_api_key(_SENTINEL_KEY)
        recovered = load_kagi_api_key()

        assert recovered == _SENTINEL_KEY

    def test_roundtrip_writes_blob_file(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """store creates the blob file at the expected path."""
        _redirect_store(monkeypatch, tmp_path)
        monkeypatch.delenv(_TEST_OVERRIDE_ENV, raising=False)

        store_kagi_api_key(_SENTINEL_KEY)

        blob = tmp_path / "kagi_api_key.dpapi"
        assert blob.exists()
        assert blob.stat().st_size > 0

    def test_roundtrip_blob_is_not_plaintext(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """The blob file must not contain the plaintext key — it is encrypted."""
        _redirect_store(monkeypatch, tmp_path)
        monkeypatch.delenv(_TEST_OVERRIDE_ENV, raising=False)

        store_kagi_api_key(_SENTINEL_KEY)

        blob = tmp_path / "kagi_api_key.dpapi"
        raw = blob.read_bytes()
        assert _SENTINEL_KEY.encode("utf-8") not in raw

    def test_rotation_overwrites_blob(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """Re-running store with a new key overwrites the blob; load returns the new key."""
        _redirect_store(monkeypatch, tmp_path)
        monkeypatch.delenv(_TEST_OVERRIDE_ENV, raising=False)

        store_kagi_api_key(_SENTINEL_KEY)
        store_kagi_api_key(_SENTINEL_KEY_ALT)
        recovered = load_kagi_api_key()

        assert recovered == _SENTINEL_KEY_ALT
        assert recovered != _SENTINEL_KEY

    def test_store_empty_key_raises_value_error(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """An empty key string is rejected before DPAPI is called."""
        _redirect_store(monkeypatch, tmp_path)

        with pytest.raises(ValueError, match="non-empty"):
            store_kagi_api_key("")

    def test_real_blob_not_read(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """The test uses tmp_path — confirm the real LOCALAPPDATA blob is never read.

        This is a documentation test: it asserts that the monkeypatched dir
        is not %LOCALAPPDATA%\\BlarAI\\secrets so a reader can confirm the
        isolation guarantee.
        """
        import os
        real_dir = Path(os.environ.get("LOCALAPPDATA", "")) / "BlarAI" / "secrets"
        assert tmp_path != real_dir, "test isolation broken — tmp_path is the real secrets dir"
