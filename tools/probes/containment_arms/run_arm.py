"""Launch the #1740 probe payload inside one setup, n times, and bank the raw results.

Setups (all launched hidden, from an elevated console):
  D   the operator's limited token (``winsec.limited_equivalent``; its access results are
      checked against the real limited token by effective_access.py on every path)
  B1  the SAFER normal-user token (what ``runas /trustlevel:0x20000`` computes)
  B2  a write-restricted token with Codex's published restricting list (synthetic SID, Everyone,
      the logon SID); the synthetic SID is granted only on the worktree fixture
  B3  a fully restricted token (restricting SIDs apply to reads as well) with a broad list
      (synthetic SID, Everyone, Users, Authenticated Users, logon SID, RESTRICTED), no WRITE_RESTRICTED
  C   an AppContainer: a registered throwaway profile, launched with the limited-equivalent
      token and SECURITY_CAPABILITIES

B1, B2, B3 and C and every option below belong to phase 2 of #1740, which the Lead Architect
approved to run before the #775 flip (2026-10-11); they refuse to run without ``--phase2`` so a
stray invocation cannot reach them. Phase-2 options, each a lock that can be switched on or off per run:
  --fence user:<SID> | package:<SID>   a temporary WFP egress fence (wfp_fence.ps1, dynamic
                                       session, removed and verified after every run);
                                       ``user:write-sid`` and ``package:auto`` resolve the
                                       B2 restricting SID and C's package SID
  --fence discriminate:block-only | discriminate:block-permit
                                       the app-scoped separation test (needs --toolchain
                                       fixture; every filter names the fixture python.exe only)
  --capabilities internetClient,...    C only: capabilities granted to the AppContainer
  --loopback-exempt                    C only: CheckNetIsolation loopback exemption for the
                                       throwaway package, removed and verified after the arm
  --toolchain fixture                  use the toolchain copies ``fixtures.py
                                       --toolchain-copy`` made (real toolchain folders are
                                       never re-permissioned)
C creates and deletes a throwaway AppContainer profile; its removal is verified.
Arm A (the dedicated account) is never launched from here: the operator runs it with
``arm_a_operator.ps1``.

Usage (elevated):  python -I run_arm.py --arm D --runs 5 --out <raw-data dir>
"""

from __future__ import annotations

import argparse
import ctypes
import ctypes.wintypes as wt
import datetime as dt
import json
import shutil
import socket
import subprocess
import sys
import threading
import time
import os
from pathlib import Path
from typing import Self

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import effective_access as ea
import winsec as w

FIXTURE_ROOT = Path("C:/blarai-spike-1740")
PAYLOAD_DIR = FIXTURE_ROOT / "payload"
WORKTREE = FIXTURE_ROOT / "worktree"
TOOLS = {
    "node": "C:/Program Files/nodejs/node.exe",
    "git": "C:/Program Files/Git/cmd/git.exe",
    "bash": "C:/Program Files/Git/bin/bash.exe",
    "python": "C:/Python314/python.exe",
    "opencode": str(Path(os.environ.get("USERPROFILE") or Path.home()) / "AppData/Roaming/npm/opencode.cmd"),
}
FIXTURE_TOOLS = {
    "node": "C:/blarai-spike-1740/toolchain/nodejs/node.exe",
    "git": "C:/blarai-spike-1740/toolchain/Git/cmd/git.exe",
    "bash": "C:/blarai-spike-1740/toolchain/Git/bin/bash.exe",
    "python": "C:/blarai-spike-1740/toolchain/Python314/python.exe",
    "opencode": "C:/blarai-spike-1740/toolchain/npm/opencode.cmd",
}
FENCE_SCRIPT = HERE / "wfp_fence.ps1"
FENCE_DIR = FIXTURE_ROOT / "fence"
PWSH = "C:/Program Files/PowerShell/7/pwsh.exe"
CHECKNETISOLATION = "C:/Windows/System32/CheckNetIsolation.exe"
APPCONTAINER_NAME = "blarai.1740.coder"
PHASE2 = {"B1", "B2", "B3", "C"}

CREATE_NO_WINDOW = 0x08000000
CREATE_UNICODE_ENVIRONMENT = 0x00000400
EXTENDED_STARTUPINFO_PRESENT = 0x00080000
PROC_THREAD_ATTRIBUTE_SECURITY_CAPABILITIES = 0x00020009
WAIT_TIMEOUT = 0x102


def argv_tail(path: str) -> str:
    """``path`` made safe before a closing quote on a Windows command line: each trailing backslash doubled, so a profile that
    ends in one (``C:\\``) reaches the payload intact instead of escaping the quote."""
    stripped = path.rstrip("\\")
    return path + "\\" * (len(path) - len(stripped))


class STARTUPINFOW(ctypes.Structure):
    _fields_ = [("cb", wt.DWORD), ("lpReserved", wt.LPWSTR), ("lpDesktop", wt.LPWSTR),
                ("lpTitle", wt.LPWSTR), ("dwX", wt.DWORD), ("dwY", wt.DWORD),
                ("dwXSize", wt.DWORD), ("dwYSize", wt.DWORD), ("dwXCountChars", wt.DWORD),
                ("dwYCountChars", wt.DWORD), ("dwFillAttribute", wt.DWORD),
                ("dwFlags", wt.DWORD), ("wShowWindow", wt.WORD), ("cbReserved2", wt.WORD),
                ("lpReserved2", ctypes.c_void_p), ("hStdInput", wt.HANDLE),
                ("hStdOutput", wt.HANDLE), ("hStdError", wt.HANDLE)]


class STARTUPINFOEXW(ctypes.Structure):
    _fields_ = [("StartupInfo", STARTUPINFOW), ("lpAttributeList", ctypes.c_void_p)]


class PROCESS_INFORMATION(ctypes.Structure):
    _fields_ = [("hProcess", wt.HANDLE), ("hThread", wt.HANDLE),
                ("dwProcessId", wt.DWORD), ("dwThreadId", wt.DWORD)]


class SECURITY_CAPABILITIES(ctypes.Structure):
    _fields_ = [("AppContainerSid", ctypes.c_void_p), ("Capabilities", ctypes.c_void_p),
                ("CapabilityCount", wt.DWORD), ("Reserved", wt.DWORD)]


def stage_payload(tools: dict[str, str]) -> None:
    PAYLOAD_DIR.mkdir(exist_ok=True)
    for name in ("arm_payload.py", "winsec.py"):
        shutil.copy2(HERE / name, PAYLOAD_DIR / name)
    (PAYLOAD_DIR / "tools.json").write_text(json.dumps(tools), encoding="utf-8")


class Listener:
    """A throwaway loopback listener: the definitive "can this setup reach loopback" target."""

    def __init__(self) -> None:
        self.sock = socket.socket()
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(16)
        self.port = self.sock.getsockname()[1]
        self.accepted = 0
        self._t = threading.Thread(target=self._loop, daemon=True)
        self._t.start()

    def _loop(self) -> None:
        while True:
            try:
                conn, _ = self.sock.accept()
            except OSError:
                return
            self.accepted += 1
            conn.close()

    def close(self) -> None:
        self.sock.close()


def token_for(arm: str) -> w.HANDLE:
    elevated = w.process_token()
    if w.elevation_type(elevated) != 2:
        raise SystemExit("run elevated")
    le = w.limited_equivalent(elevated)
    if arm in ("D", "C"):
        return le
    if arm == "B1":
        return w.safer_normal_user_token(elevated)
    b2_list, b3_list = ea.restricting_lists(ea.synthetic_sid("blarai-1740-write"), w.logon_sid(elevated))
    if arm == "B2":
        return w.limited_restricted(elevated, flags=w.WRITE_RESTRICTED, restricting=b2_list)
    if arm == "B3":
        return w.limited_restricted(elevated, flags=0, restricting=b3_list)
    raise SystemExit(f"unknown arm {arm}")


def payload_command(python: str, arm: str, tag: str, out_file: Path, listener_port: int, skip_egress: bool) -> str:
    """The payload's command line (never run by this function); the operator's profile is the launcher's own USERPROFILE."""
    return (f'"{python}" -I "{PAYLOAD_DIR / "arm_payload.py"}" --arm {arm}'
            f' --tag {tag} --out "{out_file}" --tools "{PAYLOAD_DIR / "tools.json"}"'
            f' --operator-home "{argv_tail(os.environ["USERPROFILE"])}"'
            f' --listener-port {listener_port}'
            + (" --skip-egress" if skip_egress else ""))


def launch(token: w.HANDLE, cmdline: str, cwd: Path, package_sid: str | None,
           timeout_s: float, capabilities: list[str]) -> dict[str, object]:
    """CreateProcessAsUserW, hidden; with SECURITY_CAPABILITIES when a package SID is given."""
    si = STARTUPINFOEXW()
    si.StartupInfo.cb = ctypes.sizeof(STARTUPINFOEXW if package_sid else STARTUPINFOW)
    flags = CREATE_NO_WINDOW | CREATE_UNICODE_ENVIRONMENT
    keep: list[object] = []
    if package_sid:
        size = ctypes.c_size_t()
        w.kernel32.InitializeProcThreadAttributeList(None, 1, 0, ctypes.byref(size))
        buf = ctypes.create_string_buffer(size.value)
        w._check(w.kernel32.InitializeProcThreadAttributeList(buf, 1, 0, ctypes.byref(size)),
                 "InitializeProcThreadAttributeList")
        cap_arr = (w.SID_AND_ATTRIBUTES * max(len(capabilities), 1))()
        for i, c in enumerate(capabilities):
            cap_arr[i].Sid = w.sid_from_string(c)
            cap_arr[i].Attributes = w.SE_GROUP_ENABLED
        sc = SECURITY_CAPABILITIES(w.sid_from_string(package_sid),
                                   ctypes.addressof(cap_arr) if capabilities else None,
                                   len(capabilities), 0)
        keep += [buf, sc, cap_arr]
        w._check(w.kernel32.UpdateProcThreadAttribute(
            buf, 0, ctypes.c_size_t(PROC_THREAD_ATTRIBUTE_SECURITY_CAPABILITIES),
            ctypes.byref(sc), ctypes.c_size_t(ctypes.sizeof(sc)), None, None),
            "UpdateProcThreadAttribute")
        si.lpAttributeList = ctypes.addressof(buf)
        flags |= EXTENDED_STARTUPINFO_PRESENT
    pi = PROCESS_INFORMATION()
    cmd = ctypes.create_unicode_buffer(cmdline)
    t0 = time.perf_counter()
    w._check(w.advapi32.CreateProcessAsUserW(token, None, cmd, None, None, False, flags, None,
                                             wt.LPCWSTR(str(cwd)), ctypes.byref(si),
                                             ctypes.byref(pi)), "CreateProcessAsUserW")
    rc = w.kernel32.WaitForSingleObject(pi.hProcess, int(timeout_s * 1000))
    timed_out = rc == WAIT_TIMEOUT
    if timed_out:
        w.kernel32.TerminateProcess(pi.hProcess, 99)
    code = wt.DWORD()
    w.kernel32.GetExitCodeProcess(pi.hProcess, ctypes.byref(code))
    w.kernel32.CloseHandle(pi.hThread)
    w.kernel32.CloseHandle(pi.hProcess)
    return {"exit_code": code.value, "timed_out": timed_out,
            "wall_secs": round(time.perf_counter() - t0, 3)}


def appcontainer_profile_create() -> str:
    sid = ctypes.c_void_p()
    hr = w.userenv.CreateAppContainerProfile(wt.LPCWSTR(APPCONTAINER_NAME),
                                             wt.LPCWSTR(APPCONTAINER_NAME),
                                             wt.LPCWSTR("BlarAI #1740 throwaway probe"),
                                             None, 0, ctypes.byref(sid))
    if hr not in (0, -2147024713):  # S_OK, or HRESULT_FROM_WIN32(ERROR_ALREADY_EXISTS)
        raise w.WinSecError(hr, f"CreateAppContainerProfile hr=0x{hr & 0xFFFFFFFF:08x}")
    return w.derive_appcontainer_sid(APPCONTAINER_NAME)


def appcontainer_profile_delete() -> int:
    return w.userenv.DeleteAppContainerProfile(wt.LPCWSTR(APPCONTAINER_NAME))


def _hidden(argv: list[str], timeout: float = 60) -> subprocess.CompletedProcess[str]:
    return subprocess.run(argv, capture_output=True, text=True, timeout=timeout,
                          creationflags=CREATE_NO_WINDOW, check=False)


def loopback_exempt(package_sid: str, add: bool) -> dict[str, object]:
    """Add or remove the throwaway package's loopback exemption; report the list after."""
    cp = _hidden([CHECKNETISOLATION, "LoopbackExempt", "-a" if add else "-d",
                  f"-p={package_sid}"])
    listed = package_sid.lower() in _hidden([CHECKNETISOLATION, "LoopbackExempt",
                                             "-s"]).stdout.lower()
    return {"action": "add" if add else "remove", "rc": cp.returncode,
            "listed_after": listed, "ok": listed == add}


class Fence:
    """One wfp_fence.ps1 -Hold per run: armed before the payload starts, released after."""

    def __init__(self, spec: str, hold_s: int) -> None:
        self.kind, _, self.sid = spec.partition(":")
        self.hold_s = hold_s
        self.proc: subprocess.Popen[str] | None = None

    def __enter__(self) -> Self:
        FENCE_DIR.mkdir(exist_ok=True)
        for name in ("ARMED", "DONE", "fence.json"):
            (FENCE_DIR / name).unlink(missing_ok=True)
        argv = [PWSH, "-NoProfile", "-NonInteractive", "-File", str(FENCE_SCRIPT), "-Hold",
                "-Kind", self.kind, "-HoldSeconds", str(self.hold_s), "-MarkerDir", str(FENCE_DIR)]
        if self.kind == "discriminate":
            argv += ["-Variant", self.sid, "-SyntheticSid", ea.synthetic_sid("blarai-1740-write"),
                     "-AppPath", FIXTURE_TOOLS["python"], "-AllowOperatorSid"]
        else:
            argv += ["-TargetSid", self.sid]
        self.proc = subprocess.Popen(argv, creationflags=CREATE_NO_WINDOW, text=True)
        deadline = time.monotonic() + 60
        while not (FENCE_DIR / "ARMED").exists():
            if self.proc.poll() is not None or time.monotonic() > deadline:
                raise RuntimeError(f"fence did not arm: {self.report()}")
            time.sleep(0.25)
        return self

    def report(self) -> object:
        f = FENCE_DIR / "fence.json"
        return json.loads(f.read_text(encoding="utf-8-sig")) if f.exists() else None

    def __exit__(self, *exc: object) -> None:
        (FENCE_DIR / "DONE").write_text("done", encoding="ascii")
        if self.proc is not None:
            self.proc.wait(timeout=self.hold_s + 60)


def main() -> int:
    ap = argparse.ArgumentParser(description="Run the #1740 payload inside one setup.")
    ap.add_argument("--arm", required=True, choices=["D", "B1", "B2", "B3", "C"])
    ap.add_argument("--runs", type=int, default=3)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--phase2", action="store_true",
                    help="required for B1, B2, B3, C and every phase-2 option")
    ap.add_argument("--skip-egress", action="store_true")
    ap.add_argument("--timeout", type=float, default=600)
    ap.add_argument("--fence", default="", help="user:<SID>|user:write-sid|package:auto")
    ap.add_argument("--capabilities", default="", help="C only: comma-separated names")
    ap.add_argument("--loopback-exempt", action="store_true", help="C only")
    ap.add_argument("--toolchain", choices=["real", "fixture"], default="real")
    ap.add_argument("--label", default="", help="variant label recorded with every run")
    args = ap.parse_args()
    phase2_options = bool(args.fence or args.capabilities or args.loopback_exempt)
    if (args.arm in PHASE2 or phase2_options) and not args.phase2:
        raise SystemExit(f"arm {args.arm} / these options are phase 2 of #1740: pass --phase2")
    if args.fence.startswith("discriminate:") and args.toolchain != "fixture":
        raise SystemExit("--fence discriminate:* needs --toolchain fixture (it is scoped to the fixture python.exe)")
    if (args.capabilities or args.loopback_exempt) and args.arm != "C":
        raise SystemExit("--capabilities and --loopback-exempt apply to arm C only")
    if args.fence == "package:auto":
        args.fence = "package:" + w.derive_appcontainer_sid(APPCONTAINER_NAME)
    elif args.fence == "user:write-sid":
        args.fence = "user:" + ea.synthetic_sid("blarai-1740-write")
    if not (FIXTURE_ROOT / "fixtures.json").exists():
        raise SystemExit("fixtures missing: run fixtures.py first")
    args.out.mkdir(parents=True, exist_ok=True)
    tools = FIXTURE_TOOLS if args.toolchain == "fixture" else TOOLS
    stage_payload(tools)
    listener = Listener()
    capabilities = [w.derive_capability_sid(c) for c in args.capabilities.split(",") if c]
    variant: dict[str, object] = {
        "label": args.label, "fence": args.fence, "toolchain": args.toolchain,
        "capabilities": [c for c in args.capabilities.split(",") if c],
        "loopback_exempt": args.loopback_exempt}
    package_sid: str | None = None
    try:
        if args.arm == "C":
            package_sid = appcontainer_profile_create()
            if args.loopback_exempt:
                variant["loopback_exempt_add"] = loopback_exempt(package_sid, True)
        for i in range(1, args.runs + 1):
            tag = f"{args.arm}-{dt.datetime.now().astimezone().strftime('%Y%m%dT%H%M%S')}-r{i}"
            out_file = WORKTREE / f"result-{tag}.json"
            cmd = payload_command(tools["python"], args.arm, tag, out_file, listener.port, args.skip_egress)
            before = listener.accepted
            fence_report: object = None
            if args.fence:
                with Fence(args.fence, int(args.timeout)) as fence:
                    launch_info = launch(token_for(args.arm), cmd, WORKTREE, package_sid,
                                         args.timeout, capabilities)
                fence_report = fence.report()
            else:
                launch_info = launch(token_for(args.arm), cmd, WORKTREE, package_sid,
                                     args.timeout, capabilities)
            launch_info["listener_accepts"] = listener.accepted - before
            record: dict[str, object] = {"launch": launch_info, "cmdline": cmd,
                                         "variant": variant, "fence_report": fence_report}
            if out_file.exists():
                record["payload"] = json.loads(out_file.read_text(encoding="utf-8"))
                out_file.unlink()
            else:
                record["payload"] = None
            (args.out / f"run-{tag}.json").write_text(json.dumps(record, indent=1),
                                                       encoding="utf-8")
            print(tag, json.dumps(launch_info))
    finally:
        listener.close()
        if args.arm == "C" and package_sid:
            cleanup: dict[str, object] = {}
            if args.loopback_exempt:
                cleanup["loopback_exempt_remove"] = loopback_exempt(package_sid, False)
            cleanup["delete_profile_hr"] = appcontainer_profile_delete()
            cleanup["profile_folder_gone"] = not (
                Path.home() / "AppData/Local/Packages" / APPCONTAINER_NAME).exists()
            (args.out / f"cleanup-{args.arm}-{dt.datetime.now().astimezone():%Y%m%dT%H%M%S}.json"
             ).write_text(json.dumps(cleanup, indent=1), encoding="utf-8")
            print("cleanup", json.dumps(cleanup))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
