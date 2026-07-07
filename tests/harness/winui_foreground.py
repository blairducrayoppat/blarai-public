"""Foreground-and-wait helpers for the WinUI UI-Automation harness (#621).

WHY THIS EXISTS
---------------
A backgrounded WinUI 3 window has an UNREALIZED UI-Automation tree: any element
that starts ``Visibility=Collapsed`` (``GreetingPanel``, ``SuggestBox``) or is
data-template-virtualized and not yet materialized (``PgovDenialCard``) is simply
ABSENT from the UIA tree until the window is the foreground, active window. A test
that asserts ``element.exists()`` on such a control while the window sits behind
the test runner sees a false negative — the control is *there in the app*, just
not yet projected into the automation tree. The WinUI rendering pass that
realizes those subtrees is gated on the window being foreground + active.

pywinauto's ``win.set_focus()`` alone is unreliable for WinUI 3 windows: the
modern XAML island host frequently refuses ``SetFocus`` from a background thread,
so a bare ``set_focus()`` (wrapped in a best-effort ``try/except`` in the older
harness) often left the window non-foreground and the tree unrealized. This
module adds a layered foregrounding path — ``set_focus`` first, then a Win32
``ShowWindow``/``SetForegroundWindow`` fallback driven through ``ctypes`` against
``user32.dll`` (no ``pywin32`` import required) — plus a poll that waits for the
target ``AutomationId`` to actually appear before the test asserts on it.

IMPORT-SAFE
-----------
Every ``pywinauto`` / win32 import is LAZY (inside a function body), so importing
this module on a headless box with no display, no exe, and no pywinauto is clean.
The ``winui``-marked tests are deselected by default and skip at runtime when the
exe is absent; this module must never break ``pytest --collect-only``.
"""

from __future__ import annotations

import time
from typing import Any, Callable

__all__ = [
    "bring_to_foreground",
    "wait_for_element",
    "foreground_and_wait",
]


def _force_foreground_win32(hwnd: int) -> None:
    """Best-effort Win32 foregrounding via ``ctypes`` (no ``pywin32`` needed).

    WinUI 3 windows are stubborn about ``SetForegroundWindow`` when the caller is
    a background thread that does not own the current foreground window. Windows'
    foreground-lock policy can silently no-op the call. We nudge it the way the
    documented work-arounds do: restore the window if minimized
    (``ShowWindow(SW_RESTORE)``), then attempt ``SetForegroundWindow`` /
    ``BringWindowToTop``. All calls are best-effort — a failure here is not fatal;
    the subsequent element poll is the real gate.

    Tries ``win32gui`` opportunistically (if ``pywin32`` happens to be present)
    and always falls back to raw ``ctypes`` ``user32`` calls.
    """
    if not hwnd:
        return

    SW_RESTORE = 9
    SW_SHOW = 5

    # Opportunistic pywin32 path (present on the LA dev machine alongside
    # pywinauto). Wrapped so its absence is a no-op, not an error.
    try:  # pragma: no cover - exercised only on the dev machine
        import win32con  # type: ignore
        import win32gui  # type: ignore

        try:
            if win32gui.IsIconic(hwnd):
                win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
            else:
                win32gui.ShowWindow(hwnd, win32con.SW_SHOW)
        except Exception:  # noqa: BLE001 — best-effort
            pass
        try:
            win32gui.BringWindowToTop(hwnd)
        except Exception:  # noqa: BLE001
            pass
        try:
            win32gui.SetForegroundWindow(hwnd)
        except Exception:  # noqa: BLE001 — foreground-lock can refuse; non-fatal
            pass
        return
    except Exception:  # noqa: BLE001 — win32gui not installed → ctypes fallback
        pass

    # ctypes fallback — always available on Windows, no third-party import.
    try:  # pragma: no cover - exercised only on the dev machine
        import ctypes

        user32 = ctypes.windll.user32  # type: ignore[attr-defined]
        try:
            if user32.IsIconic(hwnd):
                user32.ShowWindow(hwnd, SW_RESTORE)
            else:
                user32.ShowWindow(hwnd, SW_SHOW)
        except Exception:  # noqa: BLE001
            pass
        try:
            user32.BringWindowToTop(hwnd)
        except Exception:  # noqa: BLE001
            pass
        try:
            user32.SetForegroundWindow(hwnd)
        except Exception:  # noqa: BLE001 — foreground-lock can refuse; non-fatal
            pass
    except Exception:  # noqa: BLE001 — not on Windows / no user32
        pass


def bring_to_foreground(win: Any, settle_s: float = 0.6) -> None:
    """Bring a pywinauto window wrapper to the foreground as robustly as we can.

    Layered:
      1. ``win.set_focus()`` (pywinauto's own activation).
      2. A Win32 ``ShowWindow``/``SetForegroundWindow`` nudge on the window's HWND
         (``win.handle``) for the WinUI-stubborn case where ``set_focus`` no-ops.

    Both layers are best-effort: WinUI 3 can refuse activation from a background
    thread, and Windows' foreground-lock can refuse the Win32 call. The caller is
    expected to follow this with :func:`wait_for_element` (or
    :func:`foreground_and_wait`), which is the real gate — foregrounding only
    *raises the odds* the lazily-rendered subtree realizes; the poll confirms it.

    ``settle_s`` gives the WinUI render pass a moment to realize the now-foreground
    tree before the caller starts polling.
    """
    try:
        win.set_focus()
    except Exception:  # noqa: BLE001 — set_focus is unreliable for WinUI islands
        pass

    hwnd = 0
    try:
        hwnd = int(win.handle)
    except Exception:  # noqa: BLE001 — wrapper may not expose a handle yet
        hwnd = 0
    _force_foreground_win32(hwnd)

    if settle_s > 0:
        time.sleep(settle_s)


def wait_for_element(
    finder: Callable[[], Any],
    timeout: float = 8.0,
    poll_s: float = 0.25,
) -> Any | None:
    """Poll ``finder()`` until it returns an element that ``.exists()``, or timeout.

    ``finder`` is a zero-arg callable that resolves a pywinauto child window (e.g.
    ``lambda: win.child_window(auto_id="GreetingPanel")``). Returns the resolved
    element once it exists in the UIA tree, or ``None`` if it never appears within
    ``timeout``. Used for lazily-rendered controls that are absent from the tree
    until the window is foreground + the WinUI render pass has realized them.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            elem = finder()
            if elem.exists():
                return elem
        except Exception:  # noqa: BLE001 — element may still be materializing
            pass
        time.sleep(poll_s)
    # One last resolve so the caller gets a handle to assert/error against even on
    # the timeout path (its ``.exists()`` will be False, yielding a clear failure).
    try:
        return finder()
    except Exception:  # noqa: BLE001
        return None


def foreground_and_wait(
    win: Any,
    finder: Callable[[], Any],
    timeout: float = 8.0,
    poll_s: float = 0.25,
) -> Any | None:
    """Foreground ``win`` then wait for the element ``finder`` resolves to appear.

    Re-foregrounds the window on each poll attempt (a transient focus steal by
    another window can re-collapse the WinUI tree mid-wait), so the element has
    the best chance to realize. Returns the element once it exists, or ``None`` on
    timeout (the caller then asserts on a clearly-absent handle).

    This is the single call a test should make before asserting on any lazily-
    rendered control (``GreetingPanel``, ``SuggestBox``, ``PgovDenialCard``).
    """
    deadline = time.monotonic() + timeout
    bring_to_foreground(win)
    while time.monotonic() < deadline:
        try:
            elem = finder()
            if elem.exists():
                return elem
        except Exception:  # noqa: BLE001 — still materializing
            pass
        # Re-assert foreground in case focus was stolen, then re-poll.
        bring_to_foreground(win, settle_s=0.0)
        time.sleep(poll_s)
    try:
        return finder()
    except Exception:  # noqa: BLE001
        return None
