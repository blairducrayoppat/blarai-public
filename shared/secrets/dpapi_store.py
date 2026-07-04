"""DPAPI-backed secret store for operator-provisioned credentials (W2, #573).

This module provides encrypt-at-rest storage for the Kagi Search API key using
Windows Data Protection API (DPAPI) via ``pywin32.win32crypt``.  The encrypted
blob is written to a fixed path under ``%LOCALAPPDATA%\\BlarAI\\secrets\\`` —
the same per-user, per-machine data directory the Assistant Orchestrator already
uses for ``substrate.db``.

Key design properties
---------------------
- **Machine + user binding.** DPAPI derives its encryption key from the user's
  Windows login credential and the machine identity.  The blob cannot be
  decrypted by a different user or on a different machine.  An offline attacker
  who copies the blob file cannot recover the plaintext.
- **Fail-closed.** If pywin32 is not importable (non-Windows dev env), any call
  to ``store_kagi_api_key`` or ``load_kagi_api_key`` raises ``RuntimeError``
  immediately.  The MODULE still imports successfully so that tests exercising
  the override path work on machines without pywin32.
- **Plaintext never logged.** No exception message, log call, or repr ever
  carries the key string.  Exceptions carry opaque codes or OS error messages
  only.
- **Test override path (hermetic).** When ``BLARAI_KAGI_KEY_TEST_OVERRIDE`` is
  set in the environment AND the process is running under pytest (detected by
  ``_is_test_mode()``), ``load_kagi_api_key`` returns the override value
  without touching DPAPI or the blob file.  This mirrors the PA ``dev_mode``
  bypass pattern described in the key-handling design (§6).

Operator setup
--------------
    python -m shared.secrets.provision_kagi_key

Run once.  Overwrites on rotation.  See ``docs/runbooks/kagi_key_provisioning.md``.

Blob path
---------
    %LOCALAPPDATA%\\BlarAI\\secrets\\kagi_api_key.dpapi
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Final

# ---------------------------------------------------------------------------
# Blob path — same %LOCALAPPDATA%\BlarAI\ tree as substrate.db.
# ---------------------------------------------------------------------------

_LOCALAPPDATA: str = os.environ.get("LOCALAPPDATA", "")

# Allow tests to redirect the store to a temp directory via the module-level
# attribute.  Monkeypatching ``_SECRETS_DIR`` in tests is the blessed approach.
_SECRETS_DIR: Path = Path(_LOCALAPPDATA) / "BlarAI" / "secrets"

#: The blob file name is a stable constant; only the containing directory is
#: redirectable in tests.
_BLOB_NAME: Final[str] = "kagi_api_key.dpapi"

#: Environment variable that supplies a plaintext override key in test mode.
_TEST_OVERRIDE_ENV: Final[str] = "BLARAI_KAGI_KEY_TEST_OVERRIDE"


# ---------------------------------------------------------------------------
# Lazy pywin32 import — the module must import cleanly without pywin32.
# ---------------------------------------------------------------------------

def _get_win32crypt() -> object:
    """Return the ``win32crypt`` module or raise ``RuntimeError`` fail-closed."""
    try:
        import win32crypt  # type: ignore[import-untyped]
        return win32crypt
    except ImportError as exc:
        raise RuntimeError(
            "FAIL-CLOSED: pywin32 (win32crypt) is not available on this host. "
            "DPAPI secret storage requires Windows with pywin32 installed. "
            "Install pywin32 or use the test-override path for non-production use."
        ) from exc


# ---------------------------------------------------------------------------
# Custom exceptions
# ---------------------------------------------------------------------------

class KagiKeyNotProvisioned(RuntimeError):
    """Raised when the DPAPI blob file does not exist.

    The operator must run ``python -m shared.secrets.provision_kagi_key``
    before the web-search worker can start.  There is no silent fallback.
    """


class KagiKeyDecryptError(RuntimeError):
    """Raised when DPAPI decryption fails.

    Possible causes: running as a different user, running on a different
    machine, or a corrupted blob file.  The exception message contains the
    OS-level error but NEVER the plaintext key.
    """


# ---------------------------------------------------------------------------
# Test-mode detection
# ---------------------------------------------------------------------------

def _is_test_mode() -> bool:
    """Return True when running under pytest.

    Detection strategy: check whether ``pytest`` is present in ``sys.modules``
    (set at import time by pytest's bootstrap) or ``sys.flags.dev_mode`` is
    set.  Both signals indicate a test or development execution environment
    where the DPAPI bypass is permitted.
    """
    if "pytest" in sys.modules:
        return True
    if sys.flags.dev_mode:
        return True
    return False


def _current_blob_path() -> Path:
    """Return the absolute path to the DPAPI blob file.

    Using a function (rather than a module-level constant) means that tests
    which monkeypatch ``shared.secrets.dpapi_store._SECRETS_DIR`` see the
    updated value immediately, without having to patch the path constant.
    """
    return _SECRETS_DIR / _BLOB_NAME


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def store_kagi_api_key(key: str) -> None:
    """Encrypt *key* with DPAPI and write the opaque blob to the secrets store.

    The blob file is created (with its parent directories) if it does not exist
    and overwritten on rotation.  The plaintext key is never written to disk and
    is not retained in any module-level variable after this function returns.

    Parameters
    ----------
    key:
        The Kagi API key string to protect.  Must be non-empty.

    Raises
    ------
    RuntimeError
        If ``pywin32`` / DPAPI is unavailable (fail-closed).
    OSError
        If the blob file cannot be written (permissions, disk full, etc.).
    ValueError
        If *key* is empty.
    """
    if not key:
        raise ValueError("key must be a non-empty string")

    win32crypt = _get_win32crypt()

    blob_path = _current_blob_path()
    blob_path.parent.mkdir(parents=True, exist_ok=True)

    # CryptProtectData returns an opaque bytes object (the encrypted BLOB).
    # The description string is stored unencrypted inside the BLOB for operator
    # reference; it does NOT contain or help derive the plaintext.
    encrypted: bytes = win32crypt.CryptProtectData(  # type: ignore[attr-defined]
        key.encode("utf-8"),
        "BlarAI Kagi API key",  # description — non-secret metadata only
        None,  # optional entropy
        None,  # reserved
        None,  # prompt struct
        0,     # flags — user-scope (no CRYPTPROTECT_LOCAL_MACHINE)
    )

    blob_path.write_bytes(encrypted)


def load_kagi_api_key() -> str:
    """Decrypt and return the Kagi API key from the DPAPI blob store.

    Test-override path
    ------------------
    When ``BLARAI_KAGI_KEY_TEST_OVERRIDE`` is set in the environment AND
    ``_is_test_mode()`` returns True, the override value is returned directly
    without touching DPAPI or the blob file.  This allows the full test suite
    to run hermetically on any machine.

    Returns
    -------
    str
        The plaintext Kagi API key.  The caller is responsible for holding
        this value only for the duration needed (pass directly to the client;
        do not cache in a module-level variable).

    Raises
    ------
    KagiKeyNotProvisioned
        If the blob file does not exist and no test override is active.
    KagiKeyDecryptError
        If DPAPI decryption fails (wrong user, wrong machine, corrupt blob).
    RuntimeError
        If ``pywin32`` / DPAPI is unavailable and no test override is active.
    """
    # ---- Test-override path (hermetic; never reaches DPAPI) ----------------
    override = os.environ.get(_TEST_OVERRIDE_ENV)
    if override is not None and _is_test_mode():
        return override

    # ---- Production path ---------------------------------------------------
    win32crypt = _get_win32crypt()

    blob_path = _current_blob_path()
    if not blob_path.exists():
        raise KagiKeyNotProvisioned(
            f"Kagi API key blob not found at {blob_path}. "
            "Run: python -m shared.secrets.provision_kagi_key"
        )

    encrypted = blob_path.read_bytes()

    try:
        # CryptUnprotectData returns (description, plaintext_bytes).
        _description, plaintext_bytes = win32crypt.CryptUnprotectData(  # type: ignore[attr-defined]
            encrypted,
            None,  # optional entropy
            None,  # reserved
            None,  # prompt struct
            0,     # flags
        )
    except Exception as exc:
        # Deliberately DO NOT include exc details that might reveal key material.
        # The OS exception text describes the DPAPI error (e.g. "The parameter
        # is incorrect") which is safe to surface; the key itself is not present
        # in the encrypted blob's error path.
        raise KagiKeyDecryptError(
            "DPAPI decryption failed — the blob may belong to a different user "
            "or machine, or may be corrupted. "
            f"OS error: {exc}"
        ) from exc

    return plaintext_bytes.decode("utf-8")
