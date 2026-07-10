"""Conformance suite for ``shared.procspawn`` — the POSITIVE CONTROL (#774).

2026-07-09 lesson: a verdict-issuing instrument needs a positive control.  Every
blessed spawn shape here is exercised against a REAL child process and asserted on
its OBSERVABLE END PROPERTY (lesson 219 — verify the property the control exists
for, never the flag at the spawn site):

  R1  no console      -> the final child self-reports GetConsoleWindow() is NULL
                         (and runs under pythonw, proving the venv-shim resolve).
  R3  unicode         -> emoji + cp1252-hostile chars round-trip through both
                         stdout and stderr, uncorrupted, with an honest exit code.
  R4  capture / EOF   -> full output captured; a child that reads stdin does not
                         hang (DEVNULL == instant EOF).
  R5  tree-kill       -> a child-with-grandchild is ACTUALLY dead (both pids gone)
                         after a kill, both directly and via run_captured timeout.

All children are short cmd/python one-liners created by the test; total runtime is
kept well under 60s.  The console/window checks are Windows-only and skip cleanly
elsewhere; the capture/tree-kill checks run cross-platform.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest

from shared.procspawn import (
    detached_no_console,
    hidden_console,
    pythonw_sibling,
    run_captured,
    terminate_process_tree,
)

IS_WINDOWS = sys.platform == "win32"

# A string that a naive cp1252 stdout cannot encode: a fire emoji (non-BMP),
# euro/arrow/copyright/em-dash/section (cp1252-absent or trap code points).
UNICODE_PROBE = "PROBE \U0001f525 € → © — § END"


def _write_child(tmp_path: Path, name: str, body: str) -> str:
    """Write *body* as a child script and return its path (keeps -c quoting sane)."""
    p = tmp_path / name
    p.write_text(body, encoding="utf-8")
    return str(p)


def _alive(pid: int) -> bool:
    """True iff *pid* is a live, non-zombie process."""
    try:
        import psutil

        return psutil.pid_exists(pid) and psutil.Process(pid).status() != psutil.STATUS_ZOMBIE
    except Exception:  # noqa: BLE001 — psutil absent/lookup race -> treat as gone
        return False


def _wait_for_file(path: Path, timeout_s: float = 10.0) -> str:
    """Poll until *path* has content or the deadline passes; return its text ('' on miss)."""
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if path.exists():
            txt = path.read_text(encoding="utf-8", errors="replace").strip()
            if txt:
                return txt
        time.sleep(0.1)
    return ""


# ---------------------------------------------------------------------------
# R1 — detached, console-less: the venv-shim resolve + the no-console property
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not IS_WINDOWS, reason="pythonw shim + console semantics are Windows-only")
def test_r1_pythonw_sibling_resolves_venv_shim():
    """The blessed resolver turns the venv ``python.exe`` shim into ``pythonw.exe``."""
    resolved = pythonw_sibling(sys.executable)
    if Path(sys.executable).name.lower() == "python.exe" and \
            Path(sys.executable).with_name("pythonw.exe").exists():
        assert resolved.lower().endswith("pythonw.exe"), resolved
    else:  # non-standard layout -> unchanged, never a broken spawn
        assert resolved == sys.executable


@pytest.mark.skipif(not IS_WINDOWS, reason="GetConsoleWindow end-property is Windows-only")
def test_r1_detached_child_has_no_console(tmp_path):
    """END PROPERTY: the final child reports NO console window (GetConsoleWindow == NULL).

    This is the exact property #761/lesson 219 exists for — observed on the process
    at the END of the shim chain, not the flag at the spawn site.
    """
    log = tmp_path / "r1.log"
    child = _write_child(
        tmp_path,
        "r1_child.py",
        "import ctypes, sys\n"
        "ctypes.windll.kernel32.GetConsoleWindow.restype = ctypes.c_void_p\n"
        "hwnd = ctypes.windll.kernel32.GetConsoleWindow()\n"
        "print('CONSOLE_HWND=%s' % ('NULL' if hwnd in (None, 0) else 'PRESENT'))\n"
        "print('EXE=%s' % sys.executable)\n",
    )
    proc = detached_no_console([sys.executable, child], log_path=log)
    try:
        proc.wait(timeout=15)
    finally:
        terminate_process_tree(proc.pid)
    out = _wait_for_file(log)
    assert "CONSOLE_HWND=NULL" in out, f"child still had a console: {out!r}"
    # The venv-shim was resolved to pythonw (the mechanism behind the no-console property).
    if Path(sys.executable).with_name("pythonw.exe").exists():
        assert "pythonw.exe" in out.lower(), f"did not run under pythonw: {out!r}"


# ---------------------------------------------------------------------------
# R3 — unicode round-trip through stdout AND stderr (the cp1252 banner crash)
# ---------------------------------------------------------------------------


def test_r3_unicode_round_trip_stdout_and_stderr(tmp_path):
    """END PROPERTY: emoji + cp1252-hostile chars survive on both streams, exit honest.

    Without the R3 UTF-8 pins a redirected child stdout defaults to the locale
    (cp1252 on Windows) and the fire emoji crashes the write — the #761 banner class.
    """
    child = _write_child(
        tmp_path,
        "r3_child.py",
        "import sys\n"
        f"s = {UNICODE_PROBE!r}\n"
        "sys.stdout.write(s + '\\n'); sys.stdout.flush()\n"
        "sys.stderr.write(s + '\\n'); sys.stderr.flush()\n"
        "sys.exit(0)\n",
    )
    res = run_captured([sys.executable, child], timeout_s=30)
    assert res.returncode == 0, (res.returncode, res.stderr)
    assert not res.timed_out
    assert UNICODE_PROBE in res.stdout, repr(res.stdout)
    assert UNICODE_PROBE in res.stderr, repr(res.stderr)


# ---------------------------------------------------------------------------
# R4 — full capture, honest exit code, and DEVNULL stdin == no hang
# ---------------------------------------------------------------------------


def test_r4_captures_full_output_and_honest_exit(tmp_path):
    """END PROPERTY: every emitted line is captured and the real exit code is reported."""
    child = _write_child(
        tmp_path,
        "r4_child.py",
        "import sys\n"
        "for i in range(2000):\n"
        "    print('line-%04d' % i)\n"
        "sys.exit(3)\n",
    )
    res = run_captured([sys.executable, child], timeout_s=30)
    assert res.returncode == 3, res.returncode
    assert not res.timed_out
    assert res.stdout.count("line-") == 2000, res.stdout.count("line-")
    assert "line-0000" in res.stdout and "line-1999" in res.stdout


def test_r4_devnull_stdin_does_not_hang(tmp_path):
    """END PROPERTY: a child reading stdin hits EOF immediately (no init stall).

    The opencode-run init-stall class: an inherited non-TTY stdin that never EOFs
    hangs the run forever.  DEVNULL stdin makes the read return instantly.
    """
    child = _write_child(
        tmp_path,
        "r4_stdin_child.py",
        "import sys\n"
        "data = sys.stdin.read()\n"  # would block forever on a never-EOF stdin
        "print('READ_LEN=%d' % len(data))\n"
        "print('DONE')\n",
    )
    started = time.monotonic()
    res = run_captured([sys.executable, child], timeout_s=15)
    assert not res.timed_out, "child hung on stdin — DEVNULL EOF not honored"
    assert "DONE" in res.stdout
    assert "READ_LEN=0" in res.stdout
    assert time.monotonic() - started < 15


def test_r4_supplied_stdin_is_delivered(tmp_path):
    """When input_text is given it reaches the child (and still EOFs cleanly)."""
    child = _write_child(
        tmp_path,
        "r4_input_child.py",
        "import sys\nprint('GOT[%s]' % sys.stdin.read().strip())\n",
    )
    res = run_captured([sys.executable, child], timeout_s=15, input_text="hello-774")
    assert not res.timed_out
    assert "GOT[hello-774]" in res.stdout


# ---------------------------------------------------------------------------
# R5 — tree-kill: the child AND its grandchild are actually dead
# ---------------------------------------------------------------------------


def _parent_with_grandchild_body(pidfile: Path) -> str:
    """A child that spawns a long-sleeping grandchild and records its pid, then sleeps."""
    return (
        "import subprocess, sys, time\n"
        f"gc = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])\n"
        f"open({str(pidfile)!r}, 'w').write(str(gc.pid))\n"
        "time.sleep(60)\n"
    )


def test_r5_terminate_process_tree_kills_grandchild(tmp_path):
    """END PROPERTY: after a tree-kill, BOTH the child and its grandchild are gone."""
    import subprocess

    pidfile = tmp_path / "gc.pid"
    child = _write_child(tmp_path, "r5_parent.py", _parent_with_grandchild_body(pidfile))
    parent = subprocess.Popen([sys.executable, child])  # noqa: S603
    try:
        gc_txt = _wait_for_file(pidfile)
        assert gc_txt, "grandchild never registered its pid"
        gc_pid = int(gc_txt)
        assert _alive(parent.pid) and _alive(gc_pid), "setup: both should be alive"

        targeted = terminate_process_tree(parent.pid)
        assert gc_pid in targeted and parent.pid in targeted, targeted

        # Give the OS a moment to reap, then assert BOTH are actually dead.
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline and (_alive(parent.pid) or _alive(gc_pid)):
            time.sleep(0.1)
        assert not _alive(parent.pid), "parent survived tree-kill"
        assert not _alive(gc_pid), "grandchild survived tree-kill (orphan leak)"
    finally:
        terminate_process_tree(parent.pid)


def test_r5_run_captured_timeout_tree_kills(tmp_path):
    """run_captured's timeout path tree-kills: the grandchild dies with the parent."""
    pidfile = tmp_path / "gc2.pid"
    child = _write_child(tmp_path, "r5b_parent.py", _parent_with_grandchild_body(pidfile))

    # Launch the parent via run_captured with a short timeout in a background thread is
    # unnecessary — run_captured blocks until it times out (~2s) and tree-kills for us.
    res = run_captured([sys.executable, child], timeout_s=3)
    assert res.timed_out, "expected a timeout"
    assert res.returncode is None

    gc_txt = _wait_for_file(pidfile, timeout_s=2)
    if gc_txt:  # the grandchild had time to register before the kill
        gc_pid = int(gc_txt)
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline and _alive(gc_pid):
            time.sleep(0.1)
        assert not _alive(gc_pid), "grandchild survived run_captured timeout tree-kill"
    assert not _alive(res.pid), "parent survived run_captured timeout tree-kill"


# ---------------------------------------------------------------------------
# R2 — hidden_console runs non-interactive console children and captures them
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not IS_WINDOWS, reason="CREATE_NO_WINDOW is a Windows flag")
def test_r2_hidden_console_runs_and_captures():
    """A non-interactive console child (cmd) runs hidden and its output is captured."""
    res = hidden_console(["cmd", "/c", "echo", "hidden-774"], timeout_s=15)
    assert res.returncode == 0
    assert "hidden-774" in res.stdout
