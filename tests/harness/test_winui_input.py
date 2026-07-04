"""Live front-end UI-Automation tests — drive the REAL WinUI window (#569).

Marked ``slow`` + ``winui``: deselected by default. Run on the LA's machine with a
free display, the exe built, and BlarAI closed:

    pytest -m winui tests/harness

Stands up the scripted pipe backend (no models, no admin, no Hyper-V) and
launches the real `BlarAI.Desktop.exe`, then drives it with pywinauto. Locks the
dead-input bug END-TO-END: a stalled backend (`FakeGateway(hang=True)`) freezes
the text input (the WinUI disables it during a turn), and the merged backend
fail-safe's terminal frame re-enables it within a bound — the front-end half of
the #565 / dead-input fix, proven against the real window.
"""

from __future__ import annotations

import subprocess
import sys
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

import pytest

from tests.harness.process_tree import terminate_process_tree

pytestmark = [
    pytest.mark.slow,
    pytest.mark.winui,
    pytest.mark.skipif(sys.platform != "win32", reason="WinUI is Windows-only"),
]

_ROOT = Path(__file__).resolve().parents[2]
EXE = _ROOT / "services/ui_winui/bin/x64/Debug/net8.0-windows10.0.19041.0/BlarAI.Desktop.exe"


@contextmanager
def _winui_window(gateway: Any, failsafe_s: float | None = None) -> Iterator[Any]:
    """Launch the real window against the scripted backend; yield the pywinauto
    window; always close the exe + stop the backend on exit."""
    from pywinauto import Desktop

    from tests.harness.winui_backend import scripted_pipe_backend

    if not EXE.exists():
        pytest.skip(f"WinUI exe not built: {EXE}")

    with scripted_pipe_backend(gateway=gateway, failsafe_s=failsafe_s):
        proc = subprocess.Popen([str(EXE)])
        try:
            time.sleep(7)  # let .NET start, connect the pipe, render
            win = Desktop(backend="uia").window(title_re=".*BlarAI.*")
            win.wait("visible", timeout=25)
            try:
                win.set_focus()
            except Exception:  # noqa: BLE001 — focus is best-effort
                pass
            yield win
        finally:
            # Terminate the full process tree (see #630, Sprint 18 C6).
            terminate_process_tree(proc.pid)
            time.sleep(1)


def _wait_enabled(ctrl: Any, target: bool, timeout: float = 12.0) -> bool:
    """Poll ``ctrl.is_enabled()`` until it equals ``target`` or timeout."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            if ctrl.is_enabled() == target:
                return True
        except Exception:  # noqa: BLE001 — element may briefly be re-rendering
            pass
        time.sleep(0.25)
    return False


def _prompt_box(win: Any) -> Any:
    return win.child_window(auto_id="PromptBox", control_type="Edit")


def _send_button(win: Any) -> Any:
    return win.child_window(auto_id="SendButton", control_type="Button")


def test_input_reenables_after_a_normal_turn() -> None:
    """A normal turn streams to completion and the input comes back live."""
    from tests.harness.fakes import FakeGateway

    with _winui_window(FakeGateway(reply="Hello from the harness.")) as win:
        prompt = _prompt_box(win)
        assert prompt.is_enabled(), "input should be live when idle"
        prompt.set_edit_text("hello there")
        _send_button(win).click_input()
        assert _wait_enabled(prompt, True, timeout=15), "input never re-enabled after a normal turn"


def test_input_recovers_from_a_stalled_backend_via_failsafe() -> None:
    """THE dead-input bug, end-to-end: a stalled backend freezes the input
    (the WinUI disables it during the turn), and the merged fail-safe's terminal
    frame re-enables it within the bound instead of freezing forever."""
    from tests.harness.fakes import FakeGateway

    with _winui_window(FakeGateway(reply="one two", hang=True), failsafe_s=3.0) as win:
        prompt = _prompt_box(win)
        assert prompt.is_enabled()
        prompt.set_edit_text("describe this image")
        _send_button(win).click_input()
        # During the stall the input is busy/disabled (the freeze)...
        assert _wait_enabled(prompt, False, timeout=5), "input should freeze (busy) during the stall"
        # ...and the 3s fail-safe emits a terminal frame that re-enables it.
        assert _wait_enabled(prompt, True, timeout=15), "fail-safe did not re-enable the frozen input"
