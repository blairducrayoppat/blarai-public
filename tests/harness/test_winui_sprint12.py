"""Layer C — Sprint-12 front-end behaviours against the REAL WinUI window (#592).

Marked ``slow`` + ``winui``: deselected by default. Run on the LA's machine with a
free display, the exe built, and BlarAI closed:

    pytest -m winui tests/harness/test_winui_sprint12.py

These exercise the Sprint-12 UI-client changes against the real window, using the
scripted fake backend (no models, no AO, no elevation) — so the assertions are
deterministic even though the window is real.

Coverage:
  - ``/external`` is NOT a host command: the WinUI must forward it to the backend
    AS A PROMPT (the EA-6a fall-through fix in `MainWindow.xaml.cs`), not reject it
    host-side as "Unknown command". Verified by what the backend actually received.
  - A genuine slash command (``/unload``) still routes host-side (NOT sent as a
    prompt) — proving the fall-through is `/external`-specific, not a regression
    that leaks every command to the model.

NOTE on window resolution: the shared `_winui_window` matches the window by a
``.*BlarAI.*`` title regex, which is ambiguous when an unrelated window (a terminal
in the repo, a File Explorer on `userdata/`) also carries "BlarAI" in its title.
These tests resolve the window by the LAUNCHED PROCESS id instead — unambiguous.
"""

from __future__ import annotations

import subprocess
import sys
import time
from contextlib import contextmanager
from typing import Any, Iterator

import pytest

from tests.harness.fakes import FakeGateway
from tests.harness.process_tree import terminate_process_tree
from tests.harness.test_winui_input import (
    EXE,
    _prompt_box,
    _send_button,
    _wait_enabled,
)

pytestmark = [
    pytest.mark.slow,
    pytest.mark.winui,
    pytest.mark.skipif(sys.platform != "win32", reason="WinUI is Windows-only"),
]


@contextmanager
def _sprint12_window(gateway: Any, failsafe_s: float | None = None) -> Iterator[Any]:
    """Launch the real window against the scripted backend and resolve it by the
    launched PID (robust against unrelated 'BlarAI'-titled windows); always close
    the exe + stop the backend on exit."""
    from pywinauto import Desktop

    from tests.harness.winui_backend import scripted_pipe_backend

    if not EXE.exists():
        pytest.skip(f"WinUI exe not built: {EXE}")

    with scripted_pipe_backend(gateway=gateway, failsafe_s=failsafe_s):
        proc = subprocess.Popen([str(EXE)])
        try:
            time.sleep(7)  # let .NET start, connect the pipe, render
            win = Desktop(backend="uia").window(process=proc.pid)
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


def test_external_command_is_forwarded_as_a_prompt() -> None:
    """EA-6a fall-through (ADR-023 §2.4): typing ``/external …`` in the real
    window must reach the backend as a PROMPT — the WinUI command switch lets it
    fall through to `SubmitPromptAsync` instead of rejecting it as an unknown
    command. Proven by the backend recording the prompt it received."""
    gw = FakeGateway(reply="Acknowledged the external content.")
    with _sprint12_window(gw) as win:
        prompt = _prompt_box(win)
        assert prompt.is_enabled(), "input should be live when idle"
        prompt.set_edit_text("/external this is pasted external text")
        _send_button(win).click_input()
        # The turn completes and the input comes back (it was SENT, not swallowed).
        assert _wait_enabled(prompt, True, timeout=15), "input never re-enabled — /external may have been swallowed host-side"
        # The decisive check: the backend received it AS A PROMPT.
        assert any("/external" in p for p in gw.prompts), (
            "/external must reach the backend as a prompt (the EA-6a fall-through "
            f"fix); backend received prompts={gw.prompts!r}"
        )


def test_genuine_slash_command_is_not_sent_to_the_backend() -> None:
    """The fall-through is `/external`-specific. A real host command (``/unload``)
    is handled locally and must NOT be forwarded to the backend as a prompt —
    otherwise the exception over-matched and every command would leak to the
    model."""
    gw = FakeGateway(reply="(unused)")
    with _sprint12_window(gw) as win:
        prompt = _prompt_box(win)
        prompt.set_edit_text("/unload")
        _send_button(win).click_input()
        time.sleep(3)  # let the host-side command path run
        assert not any(p.strip() == "/unload" for p in gw.prompts), (
            "/unload must be handled host-side, not forwarded as a prompt; "
            f"backend received prompts={gw.prompts!r}"
        )
