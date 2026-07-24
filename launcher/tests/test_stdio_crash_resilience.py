"""Launcher stdio / crash-diagnostic hardening (#890).

Regression locks for the 2026-07-15 reboot-recovery finding: the launcher's own
startup banner crashed it before boot. ``_banner()`` / ``_step()`` print
box-drawing and arrow glyphs (U+2554.. ╔╗║╚╝, U+2192 →, U+2713 ✓) to
``sys.stderr``; under ``pythonw`` with no console and no stderr redirect,
``sys.stderr`` defaults to the cp1252 codec, and the FIRST such print raised
``UnicodeEncodeError`` — killing the launcher (crash.log 2026-07-15 10:05:34 and,
identically, 07:34:26). The "first launch fails, relaunch succeeds" pattern that
bit repeatedly was exactly this: a relaunch that happened to hand stderr a
UTF-8-capable stream survived.

The fix (``launcher.__main__._harden_stdio_encoding``) reconfigures stdout/stderr
to UTF-8 at the real ``__main__`` entry so the banner can never crash the launcher
again, regardless of how it was started. ``_install_crash_diagnostics`` +
``_thread_excepthook`` extend the existing main-thread crash.log capture to the
launcher's worker threads (AO daemon / heartbeat / watchdogs), whose exceptions
otherwise print to a discarded stderr and vanish.
"""

from __future__ import annotations

import io
import sys
from types import SimpleNamespace

import pytest

import launcher.__main__ as main_mod


# ---------------------------------------------------------------------------
# The hazard this locks against (self-contained; not coupled to banner text).
# ---------------------------------------------------------------------------

def test_raw_cp1252_strict_stream_rejects_the_banner_glyph_class() -> None:
    """cp1252 genuinely cannot encode the glyph class the banner emits — the bug is real."""
    stream = io.TextIOWrapper(io.BytesIO(), encoding="cp1252", errors="strict")
    with pytest.raises(UnicodeEncodeError):
        stream.write("╔══╗ → ✓")
        stream.flush()


# ---------------------------------------------------------------------------
# The fix: UTF-8 hardening of stdout/stderr.
# ---------------------------------------------------------------------------

def test_harden_reconfigures_cp1252_stderr_to_utf8(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "stderr", io.TextIOWrapper(io.BytesIO(), encoding="cp1252"))
    assert sys.stderr.encoding.lower() in ("cp1252", "windows-1252")
    main_mod._harden_stdio_encoding()
    assert sys.stderr.encoding.lower() == "utf-8"


def test_banner_and_step_survive_cp1252_stderr_after_harden(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The core regression lock: the exact 2026-07-15 crash must not recur."""
    raw = io.BytesIO()
    monkeypatch.setattr(
        sys, "stderr", io.TextIOWrapper(raw, encoding="cp1252", errors="strict")
    )
    main_mod._harden_stdio_encoding()
    # Would have raised UnicodeEncodeError before the fix (see the test above).
    main_mod._banner()
    main_mod._step("ready ✓")
    sys.stderr.flush()
    out = raw.getvalue().decode("utf-8")
    assert "BlarAI" in out
    assert "ready" in out


def test_harden_is_fail_soft_on_a_non_reconfigurable_stream(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A stream without reconfigure() (or None) must be left as-is, never raise."""
    monkeypatch.setattr(sys, "stderr", object())  # no reconfigure attr
    monkeypatch.setattr(sys, "stdout", None)
    main_mod._harden_stdio_encoding()  # must not raise


# ---------------------------------------------------------------------------
# Diagnosability: worker-thread crashes leave a durable reason in crash.log.
# ---------------------------------------------------------------------------

def test_thread_excepthook_writes_reason_to_crash_log(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    monkeypatch.setattr(main_mod, "_LOG_DIR", str(tmp_path))
    try:
        raise ValueError("worker boom")
    except ValueError as exc:
        args = SimpleNamespace(
            exc_type=ValueError,
            exc_value=exc,
            exc_traceback=exc.__traceback__,
            thread=SimpleNamespace(name="heartbeat-thread"),
        )
    main_mod._thread_excepthook(args)
    crash = (tmp_path / "crash.log").read_text(encoding="utf-8")
    assert "THREAD CRASH" in crash
    assert "heartbeat-thread" in crash
    assert "worker boom" in crash


def test_thread_excepthook_ignores_systemexit(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """A thread SystemExit is a normal stop, not a crash — nothing written."""
    monkeypatch.setattr(main_mod, "_LOG_DIR", str(tmp_path))
    args = SimpleNamespace(
        exc_type=SystemExit,
        exc_value=SystemExit(0),
        exc_traceback=None,
        thread=SimpleNamespace(name="t"),
    )
    main_mod._thread_excepthook(args)
    assert not (tmp_path / "crash.log").exists()


def test_install_crash_diagnostics_wires_thread_hook(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    import faulthandler
    import threading

    monkeypatch.setattr(main_mod, "_LOG_DIR", str(tmp_path))
    monkeypatch.setattr(main_mod, "_faulthandler_file", None)
    # Isolate global state: monkeypatch restores both after the test regardless of
    # what _install_crash_diagnostics assigns.
    monkeypatch.setattr(threading, "excepthook", threading.excepthook)
    captured: dict = {}
    monkeypatch.setattr(faulthandler, "enable", lambda **kw: captured.update(kw))

    main_mod._install_crash_diagnostics()

    assert threading.excepthook is main_mod._thread_excepthook
    assert captured.get("all_threads") is True
    assert "file" in captured
    # faulthandler.enable was mocked, but _install still opened a real handle; close it
    # so the test leaves no open fd (monkeypatch restores the global to None afterward).
    if main_mod._faulthandler_file is not None:
        main_mod._faulthandler_file.close()
