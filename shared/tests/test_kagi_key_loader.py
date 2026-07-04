"""Tests for the wrapped, never-logged Kagi key loader (#719 Part B).

WHAT THIS PROVES
================
``shared.secrets.kagi_key_loader`` is the boot-time secret slot the AO's
conditional web_search registration consumes:

- The wrapper (:class:`KagiApiKey`) redacts the key in EVERY string
  conversion (repr / str / format / f-string / %-formatting through the real
  logging path) — the plaintext leaves only via
  ``authorization_header_value()``.
- The loader fail-closes to ``None`` (dormant) on EVERY bad path: blob
  absent, DPAPI decrypt failure, pywin32 unavailable, non-string decode,
  empty / whitespace, over-long, non-ASCII, embedded whitespace / control
  characters. It NEVER raises.
- NEVER-LOGGED LOCK: the real logging path is driven with a sentinel value
  end-to-end (load -> log the wrapper object) and the sentinel must not
  appear in any produced record.

HERMETIC: no DPAPI, no real blob, no real %LOCALAPPDATA% — the dpapi_store
loader is monkeypatched (or its pytest override env used); sentinels are
obviously fake, never real-looking keys.
"""

from __future__ import annotations

import logging

import pytest

from shared.secrets.kagi_key_loader import (
    REDACTED_KEY_MARKER,
    KagiApiKey,
    load_wrapped_kagi_key,
)

# Obviously-fake sentinel — NEVER a real-looking key.
_SENTINEL = "FAKE-TEST-SENTINEL-KAGI-KEY-abc123"


def _patch_store_load(monkeypatch: pytest.MonkeyPatch, fn) -> None:
    """Point the loader's underlying dpapi_store read at ``fn``."""
    import shared.secrets.dpapi_store as dpapi_store

    monkeypatch.setattr(dpapi_store, "load_kagi_api_key", fn)


# ---------------------------------------------------------------------------
# The wrapper — redaction everywhere, plaintext only at the single exit.
# ---------------------------------------------------------------------------


class TestKagiApiKeyWrapper:
    def test_repr_str_format_all_redacted(self) -> None:
        key = KagiApiKey(_SENTINEL)
        assert repr(key) == REDACTED_KEY_MARKER
        assert str(key) == REDACTED_KEY_MARKER
        assert format(key) == REDACTED_KEY_MARKER
        assert f"{key}" == REDACTED_KEY_MARKER
        assert "{}".format(key) == REDACTED_KEY_MARKER
        assert ("%s" % key) == REDACTED_KEY_MARKER
        assert ("%r" % key) == REDACTED_KEY_MARKER
        for rendered in (repr(key), str(key), format(key)):
            assert _SENTINEL not in rendered

    def test_redaction_is_constant_not_length_derived(self) -> None:
        """Nothing about the key — not even its length — leaks through the
        marker: two very different keys render identically."""
        assert str(KagiApiKey("x")) == str(KagiApiKey("Y" * 200))

    def test_authorization_header_value_is_the_only_exit(self) -> None:
        key = KagiApiKey(_SENTINEL)
        assert key.authorization_header_value() == f"Bearer {_SENTINEL}"

    def test_no_dict_to_dump(self) -> None:
        """__slots__: no __dict__ for a debug dump / vars() to spill."""
        assert not hasattr(KagiApiKey(_SENTINEL), "__dict__")


# ---------------------------------------------------------------------------
# The loader — every bad path is None (dormant), never a raise.
# ---------------------------------------------------------------------------


class TestLoadWrappedKagiKey:
    def test_absent_blob_returns_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from shared.secrets.dpapi_store import KagiKeyNotProvisioned

        def _absent() -> str:
            raise KagiKeyNotProvisioned("blob not found")

        _patch_store_load(monkeypatch, _absent)
        assert load_wrapped_kagi_key() is None

    def test_decrypt_error_returns_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from shared.secrets.dpapi_store import KagiKeyDecryptError

        def _bad() -> str:
            raise KagiKeyDecryptError("DPAPI decryption failed")

        _patch_store_load(monkeypatch, _bad)
        assert load_wrapped_kagi_key() is None

    def test_dpapi_unavailable_returns_none(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def _no_pywin32() -> str:
            raise RuntimeError("FAIL-CLOSED: pywin32 (win32crypt) unavailable")

        _patch_store_load(monkeypatch, _no_pywin32)
        assert load_wrapped_kagi_key() is None

    def test_unexpected_error_returns_none_never_raises(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def _weird() -> str:
            raise OSError("disk went away")

        _patch_store_load(monkeypatch, _weird)
        assert load_wrapped_kagi_key() is None

    @pytest.mark.parametrize(
        "bad_value",
        [
            "",  # empty
            "   ",  # whitespace-only
            "\n\t",  # control whitespace only
            "two words",  # embedded space would corrupt the header
            "line\nbreak",  # embedded newline (header-splitting shape)
            "tab\tkey",  # embedded tab
            "ctrl\x00char",  # control character
            "k" * 257,  # over the length ceiling
            "clé-non-ascii",  # non-ASCII
        ],
        ids=[
            "empty",
            "spaces",
            "control-ws",
            "embedded-space",
            "newline",
            "tab",
            "nul",
            "overlong",
            "non-ascii",
        ],
    )
    def test_malformed_values_return_none(
        self, monkeypatch: pytest.MonkeyPatch, bad_value: str
    ) -> None:
        _patch_store_load(monkeypatch, lambda: bad_value)
        assert load_wrapped_kagi_key() is None

    def test_non_string_decode_returns_none(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _patch_store_load(monkeypatch, lambda: b"bytes-not-str")  # type: ignore[return-value]
        assert load_wrapped_kagi_key() is None

    def test_good_key_loads_wrapped_and_stripped(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _patch_store_load(monkeypatch, lambda: f"  {_SENTINEL}  ")
        key = load_wrapped_kagi_key()
        assert isinstance(key, KagiApiKey)
        # Surrounding whitespace is stripped; the value itself is intact.
        assert key.authorization_header_value() == f"Bearer {_SENTINEL}"

    def test_pytest_override_env_path_still_wraps(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The dpapi_store hermetic override env (pytest-only) flows through
        the loader and still comes out WRAPPED — no path hands back a bare
        string."""
        monkeypatch.setenv("BLARAI_KAGI_KEY_TEST_OVERRIDE", _SENTINEL)
        key = load_wrapped_kagi_key()
        assert isinstance(key, KagiApiKey)
        assert str(key) == REDACTED_KEY_MARKER


# ---------------------------------------------------------------------------
# NEVER-LOGGED LOCK — the real logging path, driven with the sentinel.
# ---------------------------------------------------------------------------


class TestKeyNeverLogged:
    def test_sentinel_never_reaches_any_log_record(
        self,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Load a sentinel-valued key through the REAL loader logging path,
        then log the wrapper through the REAL logging machinery in every
        common accidental shape (%s / %r / f-string) — the sentinel value
        must appear in NO record."""
        _patch_store_load(monkeypatch, lambda: _SENTINEL)

        probe_logger = logging.getLogger("test.kagi_key_leak_probe")
        with caplog.at_level(logging.DEBUG):
            key = load_wrapped_kagi_key()
            assert key is not None
            # The accidental-logging shapes a future bug would take:
            probe_logger.info("loaded key: %s", key)
            probe_logger.info("loaded key: %r", key)
            probe_logger.info(f"loaded key: {key}")
            probe_logger.debug("key in a collection: %s", [key])
            probe_logger.debug("key in a dict: %s", {"key": key})

        assert len(caplog.records) >= 5
        assert _SENTINEL not in caplog.text, (
            "the Kagi key value leaked into a log record"
        )
        # Every deliberate probe rendered the redaction marker instead.
        probe_lines = [
            r.getMessage() for r in caplog.records if "loaded key" in r.getMessage()
        ]
        assert probe_lines and all(
            REDACTED_KEY_MARKER in line for line in probe_lines
        )

    def test_failure_paths_never_log_the_value(
        self,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """The malformed-value refusal logs a fixed reason — never the value
        it refused (which could be a mistyped real credential)."""
        near_key = f"{_SENTINEL} with a space"  # malformed BUT secret-shaped
        _patch_store_load(monkeypatch, lambda: near_key)
        with caplog.at_level(logging.DEBUG):
            assert load_wrapped_kagi_key() is None
        assert _SENTINEL not in caplog.text
        assert near_key not in caplog.text

    def test_loader_exception_messages_never_carry_the_value(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        """An underlying store exception whose MESSAGE carries key-shaped
        text is reduced to its TYPE name in the loader's log line — the
        message text never reaches a record."""

        def _leaky_raise() -> str:
            raise RuntimeError(f"boom with {_SENTINEL} inside")

        _patch_store_load(monkeypatch, _leaky_raise)
        with caplog.at_level(logging.DEBUG):
            assert load_wrapped_kagi_key() is None
        assert _SENTINEL not in caplog.text
        assert "RuntimeError" in caplog.text
