"""Lock: every containment-arm launcher passes the OPERATOR's profile to the payload, and the payload refuses to run without it.

The payload runs as the coder account (arms A, E) or inside a container, whose own USERPROFILE is not the operator's; the
launcher runs as the operator and passes its own. A launcher that drops the argument turns a harness error into a containment
outcome (review of #1765, round 3, R3-1).
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
ARMS = REPO_ROOT / "tools" / "probes" / "containment_arms"
LAUNCHERS = ("run_arm.py", "run_arm_e.py", "arm_a_operator.ps1")


def _payload_command_lines(text: str) -> list[str]:
    """Every source line that builds the payload's command (names arm_payload.py or continues that f-string)."""
    lines = text.splitlines()
    out: list[str] = []
    for i, line in enumerate(lines):
        window = "".join(lines[i:i + 4])
        if "--arm" in line and "--tag" in window and ("arm_payload" in window or "$payload" in window):
            out.append(window)
    return out


def test_every_launcher_passes_the_operators_home() -> None:
    for name in LAUNCHERS:
        text = (ARMS / name).read_text(encoding="utf-8")
        cmds = _payload_command_lines(text)
        assert cmds, f"{name}: no payload command line found"
        for cmd in cmds:
            assert "--operator-home" in cmd, f"{name}: the payload command line does not pass --operator-home"
            assert re.search(r"USERPROFILE", cmd), f"{name}: --operator-home must come from the launcher's own USERPROFILE"
            tail_guard = "-replace" if name.endswith(".ps1") else "argv_tail("
            assert tail_guard in cmd, f"{name}: a profile ending in a backslash must be made safe before the closing quote (R4-8)"


def test_payload_refuses_to_run_without_the_operators_home(tmp_path: Path) -> None:
    out = subprocess.run([sys.executable, "-I", str(ARMS / "arm_payload.py"), "--arm", "E", "--tag", "t", "--out", str(tmp_path / "o.json")],
                         capture_output=True, text=True, cwd=str(tmp_path))
    assert out.returncode == 2 and "--operator-home" in out.stderr, (out.returncode, out.stderr[-300:])


# ---- round 4 (R4-8): a profile that ends in a backslash must arrive intact -------------------------------------------------------

import ctypes
import importlib
import os
import shutil

import pytest

PROFILES = (r"C:\Users\someone", r"C:\Users\some one", r"C:\Users\a$b%X%", "C:\\Users\\someone\\", "C:\\", "C:\\Users\\someone\\\\")


def _argv(cmdline: str) -> list[str]:
    """What CreateProcess's own parser (CommandLineToArgvW) hands the payload for this command line."""
    shell32 = ctypes.WinDLL("shell32", use_last_error=True)
    shell32.CommandLineToArgvW.restype = ctypes.POINTER(ctypes.c_wchar_p)
    shell32.CommandLineToArgvW.argtypes = [ctypes.c_wchar_p, ctypes.POINTER(ctypes.c_int)]
    n = ctypes.c_int(0)
    ptr = shell32.CommandLineToArgvW(cmdline, ctypes.byref(n))
    try:
        return [ptr[i] for i in range(n.value)]
    finally:
        ctypes.WinDLL("kernel32").LocalFree(ptr)


def _operator_home_from(cmdline: str) -> str:
    argv = _argv(cmdline)
    return argv[argv.index("--operator-home") + 1], argv


def _import_launchers(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.syspath_prepend(str(ARMS))
    for m in ("run_arm", "run_arm_e"):
        sys.modules.pop(m, None)
    return importlib.import_module("run_arm"), importlib.import_module("run_arm_e")


@pytest.mark.skipif(sys.platform != "win32", reason="Windows command-line parsing")
@pytest.mark.parametrize("profile", PROFILES)
def test_python_launchers_deliver_the_operators_home_intact(profile: str, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """The launchers' own quoting, parsed by CommandLineToArgvW: a trailing backslash must not swallow the quote or the next
    argument (arm E builds the whole command line; run_arm.py uses ``argv_tail`` in the same expression)."""
    run_arm, run_arm_e = _import_launchers(monkeypatch)
    monkeypatch.setenv("USERPROFILE", profile)
    cfg = run_arm_e.build_config("E0", "t", 5, tmp_path / "o.json")
    home, argv = _operator_home_from(cfg["process"]["commandLine"])
    assert home == profile.replace("/", "\\") and argv[-1] == home, (home, argv)
    cmd = run_arm.payload_command("x.exe", "A", "t", tmp_path / "o.json", 5, False)  # run_arm.main's own command, never run
    home, argv = _operator_home_from(cmd)
    assert home == profile and argv[-2:] == ["--listener-port", "5"], (home, argv)


@pytest.mark.skipif(sys.platform != "win32" or not (shutil.which("pwsh") or shutil.which("powershell")), reason="needs Windows PowerShell")
@pytest.mark.parametrize("profile", PROFILES)
def test_arm_a_script_delivers_the_operators_home_intact(profile: str) -> None:
    """The ``$arg`` line of arm_a_operator.ps1, evaluated by PowerShell with a stubbed USERPROFILE, then parsed."""
    text = (ARMS / "arm_a_operator.ps1").read_text(encoding="utf-8")
    line = next(l.strip() for l in text.splitlines() if l.strip().startswith("$arg ="))
    exe = shutil.which("pwsh") or shutil.which("powershell")
    script = f"$payload='p.py';$tag='t';$resultFile='r.json';$toolsFile='t.json';$port=5;{line};[Console]::Out.Write($arg)"
    out = subprocess.run([exe, "-NoProfile", "-NonInteractive", "-Command", script], capture_output=True, text=True,
                         env={**os.environ, "USERPROFILE": profile}, timeout=60)
    assert out.returncode == 0, out.stderr
    home, argv = _operator_home_from("x.exe " + out.stdout)
    assert home == profile and argv[-1] == profile, (home, argv)
