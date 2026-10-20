"""MXC loopback-proxy egress probe: harness, policy fixtures and per-run driver.

What this measures: with `runtimeConfig.networkProxy` pointing at a loopback proxy the run controls, per launcher
(arm A signed v1.0.0; arm B main build; optional arm B0 older main build):
  A1/B1  the same policy (fx-a / fx-b): accepted or refused by `--dry-run`, with the exact error text and exit
         code; the tier and flags `--probe` reports. Policy: networkProxy http://127.0.0.1:<proxy_port>, no
         allowedProxyPeer, ingress.default allow, ingress.hostLoopback allow, egress.default deny, no egress rules.
  If accepted, in the same container run: B2 three HTTP requests through the forwarding proxy to a second
  loopback listener (instrument control); B3 a direct connect to that listener; B4 connect-only attempts to
  a real LAN peer (the default gateway, on a port an unfenced pre-check reached) (i) and to 1.1.1.1:443 (ii).
  Once per batch, B5: the same direct connects from this unconfined process (control); and immediately before
  and after every launch the unfenced 1.1.1.1:443 and gateway connects are repeated.
  Reach for B2 and B3 is judged from the HOST-SIDE listener logs (run tag required; any unexplained listener
  connection at or after the launch start blinds the run); B4(i) and B4(ii) from the container's error code, where
  only WinError 10013 counts as a refusal. No listener is ever bound on a non-loopback address.
  Verdicts (HOLD / FAIL / REFUSED / REFUSED-AT-LAUNCH / INSTRUMENT-BLIND) come from summarise.py.
  Arm B (and B0) is refused unless `--probe` reports baseContainerSupportsIdentitylessLoopbackProxy == true.
  On any FAIL the harness prints `STOP: FAIL condition met` and runs nothing further.

How to run (use launch.ps1, which verifies the approved hashes first):
  python -I run_probe.py [--out DIR] [--runs 3] [--arms A,B[,B0]] [--dry-run-only] [--token elevated|standard]
                         [--wfp-capture]
                         [--arm-b-commit SHA] [--arm-b0-commit SHA]
Before every run (not only at the start) the proxy and target ports are checked; a held port records
ABORTED-PORT-HELD with the holder's pid in aborted-<arm>-r<n>.json and stops the batch.
Token mode (`--token`, default elevated): `elevated` is the mode launch.ps1 enforces for a live run (this file does
not enforce it); `standard` makes this file REFUSE (exit 2, nothing written) unless the process token is not elevated
and is Medium integrity (S-1-16-8192). The mode, IsUserAnAdmin, the token's elevation flag and type, its integrity
level SID and a `whoami /groups` summary are recorded in the batch header and in every run, control and dry-run
record. A run record whose mode is standard but whose recorded token is elevated or not Medium is INSTRUMENT-BLIND.
Steps that read state a non-elevated token cannot read are listed under `unreadable` in each snapshot and under
`unreadable_under_this_token` in the header; they are not measured, and equal before and after proves nothing.
An --out folder that already holds a batch header is refused.
`--dry-run-only` builds each arm's policy, applies the arm-B precondition and runs `--dry-run` only: no
listeners, no container. Elevation is recorded, not required.

What it writes: raw records ONLY under --out (default <home>/blarai-research-data/mxc-proxy-egress/run-<date>-<n>);
a path inside a git working tree is refused. Everything the harness stages (policy files, payload copy, work and
state directories, MXC logs) lives under <out>/staging. Files: batch-header.json, control-b5.json,
arm-<arm>-refused.json, run-<arm>-<state>-r<i>-<time>.json, batch-summary.json.

--wfp-capture (variant 4; elevated token mode only, refused with --token standard or --dry-run-only): per launch,
`netsh wfp show filters` and `show state` before, DURING (the payload holds the container open at a sync point and the
harness checks the container pid and the launcher alive before and after the capture) and after; raw XML under
<out>/wfp/. A positive control (a temporary firewall rule keyed to a synthetic package SID, created and removed
inside try/finally with removal verified) must be found by the same analysis, else the batch reading is
INSTRUMENT-BLIND. Records per run: wfp_delta_count, wfp_filters_referencing_container_sid,
capture_during_container_alive; batch-summary.json carries variant4_wfp.verdict.

NOT MEASURED: any build other than the one(s) run; the WFP filter count under a standard token (netsh wfp needs
elevation; recorded as unreadable); behaviour
on a host whose --probe reports host-loopback ingress unsupported (the earlier 26200.9457 condition); an
identity-scoped proxy (allowedProxyPeer); the session-isolation backend; UDP, ICMP or DNS egress under the proxy
policy; the WFP filter list of the container's session (only an MXC-named filter count is taken);
host-to-container ingress (the doc's own open limitation); nono under MXC (no MXC backend ships); anything
about the fork or any other sandbox. Also not measured: IPv6, HTTPS or CONNECT through the proxy, destination
ports other than those named, and run-to-run variance beyond the counts recorded.
"""

from __future__ import annotations

import argparse
import csv
import ctypes
import getpass
import hashlib
import json
import os
import re
import socket
import subprocess
import sys
import threading
import time
import winreg
from ctypes import wintypes
from datetime import datetime
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import net_payload  # noqa: E402
import summarise  # noqa: E402
from proxy import ForwardingProxy, ProbeListener, exclusive_socket, now_iso  # noqa: E402

Rec = dict[str, Any]

MXC_ROOT = Path("C:/blarai-spike-1740-mxc")
LAUNCHERS: dict[str, Path] = {
    "A": MXC_ROOT / "dl/x64/wxc-exec.exe",
    "B": MXC_ROOT / "build-main-20261015/target/x86_64-pc-windows-msvc/release/wxc-exec.exe",
    "B0": MXC_ROOT / "build1406/target/x86_64-pc-windows-msvc/release/wxc-exec.exe",
}
ARM_FIXTURE = {"A": ("fx-a", "A1"), "B": ("fx-b", "B1"), "B0": ("fx-b", "B1")}
TOOLCHAIN = Path("C:/blarai-spike-1740/toolchain")
CONTAINER_PY = TOOLCHAIN / "Python314/python.exe"
PROXY_PORT, TARGET_PORT = 18110, 18111
GATEWAY_PORTS = (80, 443, 53)
KNOWN_BUILDS = {
    "e951922beec5ad5f0ba967e398763640c3b24c96cbf97f2d198174a949e5f8cc": "525d0f25763b2edaab56e29651fb7c12c4cbbd93",
    "3cf91a4598a9acb657f8ca959a7393dab5b79ece2d993dfe3c392f2615279311": "70fc7d52c4ff2852c7be16da1c0666c8d6811e63",
}
PROXY_FLAG = "baseContainerSupportsIdentitylessLoopbackProxy"
HARNESS_FILES = ("run_probe.py", "net_payload.py", "proxy.py", "summarise.py")
PWSH = "C:/Program Files/PowerShell/7/pwsh.exe"
CREATE_NO_WINDOW = 0x08000000
BELOW_NORMAL = 0x00004000
REG_MAPPINGS = (r"HKCU\Software\Classes\Local Settings\Software\Microsoft\Windows\CurrentVersion"
                r"\ProcessSandboxes\Mappings")
REG_AC_MAPPINGS = (r"HKCU\Software\Classes\Local Settings\Software\Microsoft\Windows\CurrentVersion"
                   r"\AppContainer\Mappings")


# AppContainer profile names (the `Moniker` of each HKCU mapping) created by OTHER tools that share this account
# while a batch runs. They are counted in `appcontainer_foreign_count` and never compared. Every other mapping is
# compared by identity (SID and name), so a profile this probe's launches leave behind, or any mapping that no known
# prefix explains, changes the snapshot and stops the batch.
FOREIGN_AC_PREFIXES = ("mxcfx-",)
RECORDED_ONLY = frozenset({"appcontainer_total", "appcontainer_foreign_count"})


def win(p: Path | str) -> str:
    return str(p).replace("/", "\\")


def hidden(argv: list[str], state_dir: Path | None = None, timeout: float = 600,
           extra_env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    env.update(extra_env or {})
    if state_dir is not None:
        env["MXC_DACL_STATE_DIR"] = str(state_dir)
    return subprocess.run(argv, capture_output=True, text=True, timeout=timeout, env=env,
                          creationflags=CREATE_NO_WINDOW | BELOW_NORMAL, check=False)


def default_out() -> Path:
    root = Path.home() / "blarai-research-data" / "mxc-proxy-egress"
    stamp = datetime.now().strftime("%Y%m%d")
    n = 1
    while (root / f"run-{stamp}-{n}").exists():
        n += 1
    return root / f"run-{stamp}-{n}"


# ---------------------------------------------------------------- policy fixtures

def policy_core(proxy_port: int) -> Rec:
    """The part of the policy that defines the measured state; identical for fx-a and fx-b."""
    return {
        "network": {"egress": {"default": "deny"}, "ingress": {"default": "allow", "hostLoopback": "allow"}},
        "runtimeConfig": {"networkProxy": f"http://127.0.0.1:{proxy_port}"},
    }


def fixture(name: str, command_line: str, work_dir: Path, payload_dir: Path, proxy_port: int = PROXY_PORT) -> Rec:
    """Policy for fixture `name` (fx-a: arm A, fx-b: arm B and B0). Only the fixture name differs in provenance."""
    if name not in ("fx-a", "fx-b"):
        raise ValueError(f"unknown fixture {name!r}")
    core = policy_core(proxy_port)
    return {
        "version": "1.0.0", "containment": "processcontainer", "lifecycle": {"destroyOnExit": True},
        "fallback": {"allowDaclMutation": False},
        "process": {"commandLine": command_line, "cwd": win(work_dir), "inheritDefaultEnv": True, "timeout": 150000},
        "filesystem": {"readwritePaths": [win(work_dir)], "readonlyPaths": [win(TOOLCHAIN), win(payload_dir)]},
        "network": core["network"], "runtimeConfig": core["runtimeConfig"],
        "ui": {"disable": False, "clipboard": "none", "injection": False},
    }


# ---------------------------------------------------------------- preconditions

def check_arm_b_precondition(probe_json: Rec) -> tuple[bool, str]:
    """Arm B/B0 run only if `--probe` reports the identity-less loopback proxy flag as exactly true."""
    flag = (probe_json.get("probes") or {}).get(PROXY_FLAG) if isinstance(probe_json, dict) else None
    if flag is True:
        return True, f"{PROXY_FLAG} == true"
    return False, f"{PROXY_FLAG} is {flag!r} in the launcher's --probe output (required: true)"


def resolve_arm_commit(sha256: str | None, given: str | None) -> tuple[str | None, str]:
    """Source commit for a built launcher: the one given on the command line, else the known-build table's entry for
    the launcher's sha256. A given commit that contradicts the table, or neither source, yields (None, reason)."""
    known = KNOWN_BUILDS.get(sha256 or "")
    if given and not re.fullmatch(r"[0-9a-f]{40}", given):
        return None, f"--*-commit {given!r} is not a full 40-character lowercase hex commit id"
    if given and known and given != known:
        return None, f"--*-commit {given!r} contradicts the known build for this launcher sha256 ({known})"
    if given:
        return given, "given on the command line" + (" (matches the known-build table)" if known else "")
    if known:
        return known, "from the known-build table (launcher sha256 matched)"
    return None, "no commit given and the launcher sha256 is not in the known-build table"


def sha256_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def launcher_info(exe: Path) -> Rec:
    """Hash, Authenticode status and full --probe output; {'present': False} when the file is absent."""
    if not exe.exists():
        return {"path": str(exe), "present": False}
    probe = hidden([str(exe), "--probe"])
    try:
        pj: Rec = json.loads(probe.stdout)
    except ValueError:
        pj = {"unparsed": probe.stdout[-500:], "stderr": probe.stderr[-300:]}
    sig = hidden([PWSH, "-NoProfile", "-Command",
                  f"$s=Get-AuthenticodeSignature '{exe}'; \"$($s.Status)|$($s.SignerCertificate.Subject)\""])
    return {"path": str(exe), "present": True, "sha256": sha256_of(exe), "size": exe.stat().st_size,
            "signature": sig.stdout.strip(), "probe_rc": probe.returncode, "probe": pj}


# ---------------------------------------------------------------- machine and state

def is_elevated() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except (AttributeError, OSError):
        return False


MEDIUM_IL_SID = "S-1-16-8192"
INTEGRITY_NAMES = {"S-1-16-4096": "Low", "S-1-16-8192": "Medium", "S-1-16-8448": "Medium Plus",
                   "S-1-16-12288": "High", "S-1-16-16384": "System"}


def _token_query(token: Any, info_class: int, size: int = 512) -> bytes | None:
    adv = ctypes.WinDLL("advapi32", use_last_error=True)
    adv.GetTokenInformation.argtypes = [ctypes.c_void_p, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD,
                                        ctypes.POINTER(wintypes.DWORD)]
    buf = ctypes.create_string_buffer(size)
    got = wintypes.DWORD(0)
    if not adv.GetTokenInformation(token, info_class, buf, size, ctypes.byref(got)):
        return None
    return buf.raw[:got.value]


def token_info() -> Rec:
    """This process's token: IsUserAnAdmin, TokenElevation, TokenElevationType and the integrity level SID.
    A field that cannot be read is None (never a default that looks like a pass)."""
    out: Rec = {"is_user_an_admin": is_elevated(), "elevated": None, "elevation_type": None,
                "integrity_sid": None, "integrity_name": None}
    try:
        adv = ctypes.WinDLL("advapi32", use_last_error=True)
        kern = ctypes.WinDLL("kernel32", use_last_error=True)
        kern.GetCurrentProcess.restype = ctypes.c_void_p
        adv.OpenProcessToken.argtypes = [ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(ctypes.c_void_p)]
        kern.CloseHandle.argtypes = [ctypes.c_void_p]
        adv.ConvertSidToStringSidW.argtypes = [ctypes.c_void_p, ctypes.POINTER(wintypes.LPWSTR)]
        kern.LocalFree.argtypes = [ctypes.c_void_p]
        token = ctypes.c_void_p()
        if not adv.OpenProcessToken(kern.GetCurrentProcess(), 0x0008, ctypes.byref(token)):
            return out
        try:
            el = _token_query(token, 20, 4)
            if el and len(el) >= 4:
                out["elevated"] = bool(int.from_bytes(el[:4], "little"))
            et = _token_query(token, 18, 4)
            if et and len(et) >= 4:
                out["elevation_type"] = {1: "default", 2: "full", 3: "limited"}.get(int.from_bytes(et[:4], "little"))
            lab = _token_query(token, 25)
            if lab and len(lab) >= 8:
                sid_ptr = ctypes.c_void_p(int.from_bytes(lab[:8], "little"))
                text = wintypes.LPWSTR()
                if adv.ConvertSidToStringSidW(sid_ptr, ctypes.byref(text)):
                    out["integrity_sid"] = text.value
                    out["integrity_name"] = INTEGRITY_NAMES.get(text.value or "", "unknown")
                    kern.LocalFree(ctypes.cast(text, ctypes.c_void_p))
        finally:
            kern.CloseHandle(token)
    except (AttributeError, OSError):
        pass
    return out


def groups_summary() -> Rec:
    """`whoami /groups` reduced to: the mandatory-label line, the Administrators group state, the group count."""
    cp = hidden(["whoami", "/groups", "/fo", "csv", "/nh"], timeout=60)
    rows = [r for r in csv.reader(cp.stdout.splitlines()) if len(r) >= 4]
    out: Rec = {"rc": cp.returncode, "group_count": len(rows), "integrity_label": None, "administrators": "absent"}
    for name, _type, sid, attrs in (r[:4] for r in rows):
        if sid.startswith("S-1-16-"):
            out["integrity_label"] = f"{name} ({sid})"
        elif sid == "S-1-5-32-544":
            out["administrators"] = "deny-only" if "deny" in attrs.lower() else "enabled"
    return out


def token_record(mode: str) -> Rec:
    return {"mode": mode, **token_info(), "groups": groups_summary()}


def token_mode_problem(mode: str, tok: Rec) -> str | None:
    """Why `tok` does not satisfy `mode`, or None. `standard` needs a non-elevated Medium-integrity token; unreadable
    fields fail it. `elevated` is enforced by launch.ps1, not here."""
    if mode != "standard":
        return None
    if tok.get("is_user_an_admin") or tok.get("elevated") is not False:
        return (f"token is elevated or its elevation could not be read "
                f"(IsUserAnAdmin={tok.get('is_user_an_admin')}, elevated={tok.get('elevated')})")
    if tok.get("integrity_sid") != MEDIUM_IL_SID:
        return f"token integrity is {tok.get('integrity_sid')!r}, not Medium ({MEDIUM_IL_SID})"
    return None


def unreadable_keys(snap: Rec) -> list[str]:
    """Entries a read could not take; they compare equal before and after, so they are listed apart."""
    return sorted(k for k, v in snap.items()
                  if (isinstance(v, str) and "unreadable" in v[:40].lower())
                  or (isinstance(v, list) and any(isinstance(x, str) and x.startswith("<unreadable") for x in v)))


class _PowerStatus(ctypes.Structure):
    _fields_ = [("ACLineStatus", ctypes.c_ubyte), ("BatteryFlag", ctypes.c_ubyte),
                ("BatteryLifePercent", ctypes.c_ubyte), ("SystemStatusFlag", ctypes.c_ubyte),
                ("BatteryLifeTime", wintypes.DWORD), ("BatteryFullLifeTime", wintypes.DWORD)]


def machine_conditions() -> Rec:
    tok = token_info()
    out: Rec = {"elevated": is_elevated(), "token_elevated": tok["elevated"], "integrity_sid": tok["integrity_sid"],
                "time": now_iso()}
    try:

        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows NT\CurrentVersion") as k:
            build = winreg.QueryValueEx(k, "CurrentBuildNumber")[0]
            ubr = winreg.QueryValueEx(k, "UBR")[0]
            out["windows_build"] = f"{build}.{ubr}"
            out["windows_product"] = winreg.QueryValueEx(k, "ProductName")[0]
    except OSError as exc:
        out["windows_build"] = f"unavailable: {exc!r}"
    try:
        ps = _PowerStatus()
        ctypes.windll.kernel32.GetSystemPowerStatus(ctypes.byref(ps))
        out["ac_power"] = {1: True, 0: False}.get(ps.ACLineStatus)
        out["battery_percent"] = ps.BatteryLifePercent
    except (AttributeError, OSError):
        out["ac_power"] = None
    cp = hidden(["tasklist", "/fo", "csv", "/nh"], timeout=60)
    names = [ln.split('","')[0].strip('"') for ln in cp.stdout.splitlines() if ln.strip()]
    matched = sorted(n for n in names if re.search(r"bd|bitdefender|vsserv|epsecurity|"
                                                   r"epintegration|updatesrv|seccenter|epprotected", n, re.I))
    out["bitdefender_processes"] = len(matched)
    out["bitdefender_process_names"] = matched
    return out


def sddl_of(path: Path) -> str:
    adv = ctypes.WinDLL("advapi32", use_last_error=True)
    kern = ctypes.WinDLL("kernel32", use_last_error=True)
    vp = ctypes.c_void_p
    adv.GetNamedSecurityInfoW.restype = wintypes.DWORD
    adv.GetNamedSecurityInfoW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, vp, vp, vp, vp,
                                          ctypes.POINTER(vp)]
    adv.ConvertSecurityDescriptorToStringSecurityDescriptorW.argtypes = [vp, wintypes.DWORD, wintypes.DWORD,
                                                                          ctypes.POINTER(wintypes.LPWSTR), vp]
    kern.LocalFree.argtypes = [vp]
    sd = vp()
    rc = adv.GetNamedSecurityInfoW(str(path), 1, 4, None, None, None, None, ctypes.byref(sd))
    if rc:
        return f"<unreadable: error {rc}>"
    text = wintypes.LPWSTR()
    ok = adv.ConvertSecurityDescriptorToStringSecurityDescriptorW(sd, 1, 4, ctypes.byref(text), None)
    value = text.value if ok else "<convert failed>"
    if ok:
        kern.LocalFree(ctypes.cast(text, vp))
    kern.LocalFree(sd)
    return value or ""


def appcontainer_mappings() -> tuple[list[str], int, int | str]:
    """(non-foreign mappings as `<sid> <moniker>`, foreign count, total) from HKCU AppContainer\\Mappings.
    A mapping that vanishes while being read is skipped (it was churn, not a stable entry). An unreadable key gives
    (["<absent>"], 0, "unreadable")."""
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, REG_AC_MAPPINGS.split("\\", 1)[1])
    except OSError:
        return ["<absent>"], 0, "unreadable"
    own, foreign, total, i = [], 0, 0, 0
    with key:
        while True:
            try:
                sid = winreg.EnumKey(key, i)
            except OSError:
                break
            i += 1
            try:
                sub = winreg.OpenKey(key, sid)
            except FileNotFoundError:
                continue
            except OSError:
                sub = None
            moniker = "<unreadable>"
            if sub is not None:
                with sub:
                    try:
                        moniker = str(winreg.QueryValueEx(sub, "Moniker")[0])
                    except OSError:
                        pass
            total += 1
            if moniker.startswith(FOREIGN_AC_PREFIXES):
                foreign += 1
            else:
                own.append(f"{sid} {moniker}")
    return sorted(own), foreign, total


def state_changes(before: Rec, after: Rec) -> Rec:
    """Entries of the two snapshots that differ, leaving out the fields that are recorded only."""
    return {k: [before[k], after.get(k)] for k in before if k not in RECORDED_ONLY and before[k] != after.get(k)}


def reg_list(key: str) -> list[str]:
    cp = hidden(["reg", "query", key])
    return (sorted(ln.strip() for ln in cp.stdout.splitlines() if ln.strip().startswith("HKEY"))
            if cp.returncode == 0 else ["<absent>"])


FIREWALL_PS = r"""
$progs = @($env:BLARAI_PROGS -split ';' | Where-Object { $_ })
$rules = @()
foreach ($f in Get-NetFirewallApplicationFilter -ErrorAction SilentlyContinue) {
  if ($progs -contains $f.Program) {
    foreach ($r in ($f | Get-NetFirewallRule)) {
      $rules += "$($r.Name)|$($r.DisplayName)|$($r.Enabled)|$($r.Direction)|$($r.Action)|$($r.Profile)|$($f.Program)"
    }
  }
}
$prof = @(Get-NetFirewallProfile | ForEach-Object { "$($_.Name)|$($_.Enabled)|$($_.DefaultInboundAction)|$($_.DefaultOutboundAction)|$($_.NotifyOnListen)" })
$product = @(Get-CimInstance -Namespace root/SecurityCenter2 -ClassName FirewallProduct -ErrorAction SilentlyContinue | ForEach-Object { "$($_.displayName)|$($_.productState)" })
@{ rules = @($rules | Sort-Object); profiles = $prof; product = $product } | ConvertTo-Json -Compress -Depth 3
"""


def firewall_state(programs: list[Path]) -> Rec:
    """Firewall rules whose program is one of `programs`, the profiles, and the registered firewall product."""
    cp = hidden([PWSH, "-NoProfile", "-Command", FIREWALL_PS], timeout=180,
                extra_env={"BLARAI_PROGS": ";".join(win(p) for p in programs)})
    try:
        return json.loads(cp.stdout)
    except ValueError:
        return {"unreadable": (cp.stdout[-200:] + cp.stderr[-200:])}


def wfp_mxc_filter_count(scratch: Path) -> object:
    """Count of WFP filters whose name mentions mxc/wxc; 'unreadable' when the read needs elevation."""
    if not is_elevated():
        return "unreadable: not elevated"
    scratch.mkdir(parents=True, exist_ok=True)
    target = scratch / "wfp-filters.xml"
    try:
        cp = hidden(["netsh", "wfp", "show", "filters", f"file={target}"], timeout=180)
    except subprocess.TimeoutExpired:
        target.unlink(missing_ok=True)
        return "unreadable: netsh timed out"
    if cp.returncode != 0 or not target.exists():
        target.unlink(missing_ok=True)
        return f"unreadable: netsh rc={cp.returncode}"
    raw = target.read_bytes()
    text = raw.decode("utf-16" if raw[:2] in (b"\xff\xfe", b"\xfe\xff") else "utf-8", errors="replace")
    target.unlink()
    return len(re.findall(r"<name>[^<]*(?:mxc|wxc)[^<]*</name>", text, re.I))


# ---------------------------------------------------------------- variant 4: WFP capture

CONTROL_PACKAGE_SID = "S-1-15-2-1111111111-2222222222-3333333333-4444444444-5555555555-6666666666-7777777777"
HOLD_READY_WAIT_SECS = 90.0
HOLD_MAX_SECS = 100.0


def netsh_capture(kind: str, target: Path) -> tuple[bool, str]:
    """`netsh wfp show <kind> file=<target>`; (ok, detail). A capture that fails or leaves no file is not ok."""
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        cp = hidden(["netsh", "wfp", "show", kind, f"file={target}"], timeout=240)
    except subprocess.TimeoutExpired:
        return False, f"netsh wfp show {kind} timed out"
    if cp.returncode != 0 or not target.exists():
        return False, f"netsh wfp show {kind} rc={cp.returncode} {cp.stdout.strip()[-120:]}"
    return True, "ok"


def capture_pair(folder: Path, label: str) -> tuple[Rec, list[str]]:
    """Filters and state captures for one moment; returns ({'filters': path|None, 'state': path|None}, problems)."""
    paths: Rec = {}
    probs: list[str] = []
    for kind in ("filters", "state"):
        target = folder / f"{label}-{kind}.xml"
        ok, why = netsh_capture(kind, target)
        paths[kind] = str(target) if ok else None
        if not ok:
            probs.append(f"{label} {kind}: {why}")
    return paths, probs


def read_capture(path: str | None) -> str | None:
    return summarise.decode_wfp(Path(path).read_bytes()) if path and Path(path).exists() else None


def pid_alive(pid: int | None) -> bool:
    if not pid:
        return False
    cp = hidden(["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"], timeout=30)
    return f'"{pid}"' in cp.stdout


def launch_with_wfp(exe: Path, cfg_path: Path, state_dir: Path, logf: Path, tag: str, stg: dict[str, Path],
                    wfp_dir: Path) -> tuple[Rec, Rec]:
    """Launch with the payload's hold point and capture WFP before, during and after. Returns (launch record, wfp
    capture record: paths, timings, alive flags, payload pid/token, problems). The during capture counts as taken
    with the container alive only if the payload pid and the launcher process are both alive immediately before and
    immediately after it and the release file did not yet exist."""
    ready, release = stg["work"] / f"ready-{tag}.json", stg["work"] / f"release-{tag}"
    cap: Rec = {"problems": [], "files": {}}
    before, probs = capture_pair(wfp_dir, f"{tag}-before")
    cap["files"]["before"], cap["problems"] = before, probs
    env = dict(os.environ, MXC_DACL_STATE_DIR=str(state_dir))
    t0, started = time.perf_counter(), now_iso()
    proc = subprocess.Popen([str(exe), str(cfg_path), "--log-file", str(logf)], stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, text=True, env=env,
                            creationflags=CREATE_NO_WINDOW | BELOW_NORMAL)
    out: list[tuple[str, str]] = []
    th = threading.Thread(target=lambda: out.append(proc.communicate(timeout=300)), daemon=True)
    th.start()
    waited = time.perf_counter()
    while not ready.exists() and proc.poll() is None and time.perf_counter() - waited < HOLD_READY_WAIT_SECS:
        time.sleep(0.2)
    info: Rec = {}
    if ready.exists():
        try:
            info = json.loads(ready.read_text(encoding="utf-8"))
        except ValueError:
            cap["problems"].append("ready file unparseable")
    else:
        cap["problems"].append("container never reached the hold point (launcher exited or wait elapsed)")
    pid = info.get("pid") if isinstance(info.get("pid"), int) else None
    cap["payload"] = {"pid": pid, "token": info.get("token"), "ready_at": info.get("started")}
    alive = False
    if pid:
        a0 = pid_alive(pid) and proc.poll() is None and not release.exists()
        cap["during_started"] = now_iso()
        during, probs = capture_pair(wfp_dir, f"{tag}-during")
        cap["during_ended"] = now_iso()
        a1 = pid_alive(pid) and proc.poll() is None and not release.exists()
        cap["files"]["during"], cap["problems"] = during, cap["problems"] + probs
        alive = a0 and a1
        cap["alive_before_capture"], cap["alive_after_capture"] = a0, a1
    else:
        cap["files"]["during"] = {"filters": None, "state": None}
    release.write_text("release", encoding="utf-8")
    th.join(timeout=320)
    rec: Rec
    if out:
        so, se = out[0]
        rec = {"exit_code": proc.returncode, "wall_secs": round(time.perf_counter() - t0, 3), "started": started,
               "stdout_tail": so.strip()[-1500:], "stderr_tail": se.strip()[-1500:]}
    else:
        proc.kill()
        rec = {"timeout": True, "started": started}
    cap["container_alive_at_during_capture"] = alive
    after, probs = capture_pair(wfp_dir, f"{tag}-after")
    cap["files"]["after"], cap["problems"] = after, cap["problems"] + probs
    ready.unlink(missing_ok=True)
    release.unlink(missing_ok=True)
    return rec, cap


def wfp_reading(cap: Rec, payload: Rec | None) -> Rec:
    """Analysis of one launch's captures; the container SID and user SID come from the payload's own token record
    (the hold file's copy when the result file is absent)."""
    tok = (payload or {}).get("token") or (cap.get("payload") or {}).get("token") or {}
    hold = (payload or {}).get("hold") or {}
    probs = list(cap.get("problems") or [])
    if payload is not None and hold and hold.get("released") is not True:
        probs.append("payload was not released by the host before its hold timed out")
    f = cap["files"]
    rec = summarise.analyse_wfp(read_capture(f["before"]["filters"]), read_capture(f["during"]["filters"]),
                                read_capture(f["after"]["filters"]), tok.get("appcontainer_sid"), tok.get("user_sid"),
                                cap.get("container_alive_at_during_capture"), probs)
    state_hits = {k: summarise.decode_wfp(Path(f[k]["state"]).read_bytes()).lower().count(str(tok.get("appcontainer_sid")).lower())
                  if f[k]["state"] and tok.get("appcontainer_sid") else None for k in ("before", "during", "after")}
    rec["state_file_container_sid_mentions"] = state_hits
    rec["capture"] = {k: v for k, v in cap.items() if k != "files"}
    rec["files"] = f
    return rec


def positive_control(out: Path) -> Rec:
    """Instrument check for the WFP capture: create a firewall rule keyed to a synthetic package SID, capture, find the
    SID through the same analysis, remove the rule in finally and verify the removal, capture again and confirm the
    SID is gone. ok only if all of that holds."""
    name = f"BlarAI-wfp-poscontrol-{datetime.now().strftime('%H%M%S')}"
    wdir = out / "wfp"
    rec: Rec = {"rule": name, "sid": CONTROL_PACKAGE_SID, "created": False, "found_filters": [],
                "removed_verified": False, "absent_after_removal": None, "problems": [], "ok": False}

    def ps(cmd: str) -> subprocess.CompletedProcess[str]:
        return hidden([PWSH, "-NoProfile", "-NonInteractive", "-Command", cmd], timeout=120)

    def rule_count() -> int | None:
        cp = ps(f"@(Get-NetFirewallRule -Name '{name}' -ErrorAction SilentlyContinue).Count")
        return int(cp.stdout.strip()) if cp.returncode == 0 and cp.stdout.strip().isdigit() else None

    if rule_count() != 0:
        rec["problems"].append("rule name already present or not checkable before creation")
        return rec
    try:
        cp = ps(f"New-NetFirewallRule -Name '{name}' -DisplayName '{name}' -Direction Outbound -Action Block "
                f"-Package '{CONTROL_PACKAGE_SID}' -Enabled True -Profile Any | Out-Null")
        rec["created"] = cp.returncode == 0 and rule_count() == 1
        if not rec["created"]:
            rec["problems"].append(f"rule creation failed: {cp.stderr.strip()[-200:]}")
        else:
            paths, probs = capture_pair(wdir, "control-present")
            rec["problems"] += probs
            text = read_capture(paths["filters"])
            if text is not None:
                rec["found_filters"] = summarise.filters_referencing(summarise.wfp_filters(text), CONTROL_PACKAGE_SID)
    except (ValueError, OSError, subprocess.SubprocessError) as exc:
        rec["problems"].append(f"control failed: {exc!r}")
    finally:
        ps(f"Remove-NetFirewallRule -Name '{name}' -ErrorAction SilentlyContinue")
        rec["removed_verified"] = rule_count() == 0
        if not rec["removed_verified"]:
            rec["problems"].append("rule removal NOT verified; remove it by hand: " + name)
    try:
        paths, probs = capture_pair(wdir, "control-removed")
        rec["problems"] += probs
        text = read_capture(paths["filters"])
        if text is not None:
            rec["absent_after_removal"] = not summarise.filters_referencing(summarise.wfp_filters(text), CONTROL_PACKAGE_SID)
    except ValueError as exc:
        rec["problems"].append(f"post-removal capture unreadable: {exc}")
    rec["ok"] = bool(rec["created"] and rec["found_filters"] and rec["removed_verified"] and rec["absent_after_removal"])
    if not rec["found_filters"]:
        rec["problems"].append("analysis found no filter naming the control SID")
    (out / "wfp-control.json").write_text(json.dumps(rec, indent=1), encoding="utf-8")
    return rec


def snapshot(watched: list[Path], state_dir: Path, programs: list[Path] | None = None) -> Rec:
    """State that a run must leave unchanged. Any difference between before and after stops the batch.
    `unreadable` lists the entries this token could not read: they are not measured, and equal before and after
    proves nothing about them."""
    fw = firewall_state(programs or [])
    ac_own, ac_foreign, ac_total = appcontainer_mappings()
    snap: Rec = {"acl": {str(p): hashlib.sha256(sddl_of(p).encode()).hexdigest()[:16] for p in watched},
            "process_sandboxes": reg_list(REG_MAPPINGS), "appcontainer_mappings": ac_own,
            "appcontainer_foreign_count": ac_foreign, "appcontainer_total": ac_total,
            "state_dir": sorted(p.name for p in state_dir.glob("*")),
            "firewall_rules_for_interpreters": fw.get("rules", fw.get("unreadable")),
            "firewall_profiles": fw.get("profiles", fw.get("unreadable")),
            "loopback_exempt": hidden(["CheckNetIsolation", "LoopbackExempt", "-s"], timeout=60).stdout.strip(),
            "winhttp_proxy": hidden(["netsh", "winhttp", "show", "proxy"], timeout=60).stdout.strip(),
            "wfp_mxc_filters": wfp_mxc_filter_count(state_dir.parent / "scratch")}
    snap["unreadable"] = unreadable_keys(snap)
    return snap


def port_holders(ports: list[int]) -> dict[int, list[int]]:
    """Process ids holding each port on 127.0.0.1 (from netstat); an empty list means a holder that could not be named."""
    cp = hidden(["netstat", "-ano", "-p", "tcp"], timeout=60)
    holders: dict[int, list[int]] = {}
    for line in cp.stdout.splitlines():
        cols = line.split()
        if len(cols) >= 5 and cols[0].upper() == "TCP" and cols[3].upper() == "LISTENING":
            local, pid = cols[1], cols[4]
            host, _, port = local.rpartition(":")
            if port.isdigit() and int(port) in ports and host in ("127.0.0.1", "0.0.0.0", "[::]", "[::1]") and pid.isdigit():
                holders.setdefault(int(port), []).append(int(pid))
    return holders


def check_ports_free(ports: list[int]) -> list[str]:
    """Plain-language problems for any of `ports` that cannot be bound exclusively on 127.0.0.1 right now (empty = free).

    A bind is attempted (and released) so that a listener we cannot see in netstat still counts; the holder's pid
    comes from netstat when it can be found."""
    busy: list[int] = []
    for port in ports:
        sock = exclusive_socket()
        try:
            sock.bind(("127.0.0.1", port))
        except OSError:
            busy.append(port)
        finally:
            sock.close()
    if not busy:
        return []
    holders = port_holders(busy)
    return [f"port {port} on 127.0.0.1 is already in use by "
            + (f"process id {', '.join(str(x) for x in sorted(set(holders[port])))}" if holders.get(port) else
               "a process that could not be identified (it may be a connection in its closing state; wait a minute and try again)")
            + ". Close that program and start the run again; nothing was started." for port in busy]


def gateway_ip() -> str | None:
    """Default gateway IPv4 from the routing table (the LAN peer for B4(i)); None when it cannot be read."""
    cp = hidden([PWSH, "-NoProfile", "-Command",
                 "(Get-NetRoute -DestinationPrefix 0.0.0.0/0 | Sort-Object RouteMetric | Select-Object -First 1).NextHop"])
    ip = cp.stdout.strip().splitlines()[0].strip() if cp.stdout.strip() else ""
    return ip if re.fullmatch(r"\d{1,3}(\.\d{1,3}){3}", ip) and ip != "0.0.0.0" else None


def pick_gateway_port(gw: str | None) -> int:
    """First port in GATEWAY_PORTS that an unfenced connect reaches; 0 when none (B4(i) is then NOT-MEASURABLE)."""
    if gw is None:
        return 0
    for port in GATEWAY_PORTS:
        if net_payload.tcp_probe(gw, port, None, 3).get("connected") is True:
            return port
    return 0


def unfenced(gw: str | None, gw_port: int) -> Rec:
    """The unfenced connects that attribute a refusal to the container: 1.1.1.1:443 and the gateway peer."""
    return {"c": net_payload.tcp_probe("1.1.1.1", 443, None, 4),
            "gw": (net_payload.tcp_probe(gw, gw_port, None, 4) if gw and gw_port
                   else {"connected": None, "skipped": "no gateway port"}),
            "ts": now_iso()}


# ---------------------------------------------------------------- instruments

class Instruments:
    """Fresh proxy + second loopback listener, each with its own log, host-control tested. Loopback only."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.target_log: list[Rec] = []
        self.proxy_log: list[Rec] = []
        self.target = ProbeListener("target", "127.0.0.1", TARGET_PORT, self.target_log, self.lock)
        self.proxy = ForwardingProxy(PROXY_PORT, {TARGET_PORT}, self.proxy_log, self.lock)

    def host_control(self) -> Rec:
        t = net_payload.tcp_probe("127.0.0.1", TARGET_PORT, "host-control-target-1", 3)
        p = net_payload.http_via_proxy("127.0.0.1", PROXY_PORT, "127.0.0.1", TARGET_PORT, "host-control-proxy-1")
        return {"target": t.get("connected") is True, "proxy": p.get("status") == 200,
                "detail": {"target": t, "proxy": p}}

    def close(self) -> None:
        for x in (self.target, self.proxy):
            x.close()


# ---------------------------------------------------------------- driver

def run_unfenced_control(gw: str | None, gw_port: int, out: Path, token_mode: str = "elevated") -> Rec:
    """B5: the same direct connects from this unconfined process, 1 each."""
    ins = Instruments()
    tag = f"ctl-{datetime.now().strftime('%H%M%S')}"
    try:
        hc = ins.host_control()
        a = net_payload.tcp_probe("127.0.0.1", TARGET_PORT, f"{tag}-b5a-1")
        u = unfenced(gw, gw_port)
        time.sleep(0.5)
    finally:
        ins.close()
    with ins.lock:
        rec: Rec = {"tag": tag, "host_control": hc, "b5a": a, "b5b": u["gw"], "b5c": u["c"],
                    "gateway_port": gw_port, "target_log": list(ins.target_log), "proxy_log": list(ins.proxy_log),
                    "machine": machine_conditions(), "token": token_record(token_mode)}
    rec["judgement"] = summarise.judge_controls(rec)
    (out / "control-b5.json").write_text(json.dumps(rec, indent=1), encoding="utf-8")
    return rec


def payload_command(tag: str, result: Path, stg: dict[str, Path], gw: str | None, gw_port: int,
                    hold: bool = False) -> str:
    cmd = (f'"{win(CONTAINER_PY)}" -I "{win(stg["payload"] / "net_payload.py")}" --tag {tag} '
           f'--out "{win(result)}" --gateway-ip {gw or "0.0.0.0"} --gateway-port {gw_port} '
           f'--proxy-port {PROXY_PORT} --target-port {TARGET_PORT}')
    if hold:
        cmd += (f' --hold-ready "{win(stg["work"] / f"ready-{tag}.json")}"'
                f' --hold-release "{win(stg["work"] / f"release-{tag}")}" --hold-max-secs {HOLD_MAX_SECS}')
    return cmd


def run_one(arm: str, run_no: int, gw: str | None, gw_port: int, out: Path, stg: dict[str, Path],
            watched: list[Path], programs: list[Path], token_mode: str = "elevated", wfp: bool = False) -> Rec:
    fx_name, state = ARM_FIXTURE[arm]
    exe = LAUNCHERS[arm]
    tag = f"{arm}-{state}-r{run_no}-{datetime.now().strftime('%H%M%S')}"
    result_path = stg["work"] / f"result-{tag}.json"
    policy = fixture(fx_name, payload_command(tag, result_path, stg, gw, gw_port, hold=wfp), stg["work"], stg["payload"])
    cfg_path = stg["cfg"] / f"{tag}.json"
    cfg_path.write_text(json.dumps(policy, indent=1), encoding="utf-8")
    ins = Instruments()
    rec: Rec = {"arm": arm, "state": state, "fixture": fx_name, "run": run_no, "tag": tag, "launcher": str(exe),
                "policy_as_submitted": policy, "machine": machine_conditions(),
                "token": token_record(token_mode), "gateway": {"port": gw_port, "ip_recorded": gw},
                "snapshot_before": snapshot(watched, stg["state"], programs)}
    try:
        rec["host_control"] = ins.host_control()
        dry = hidden([str(exe), str(cfg_path), "--dry-run"], stg["state"])
        rec["dry_run"] = {"rc": dry.returncode, "stdout": dry.stdout.strip()[-4000:], "stderr": dry.stderr.strip()[-4000:]}
        if dry.returncode == 0:
            logf = stg["logs"] / f"{tag}.log"
            rec["unfenced_pre"] = unfenced(gw, gw_port)
            t0, started = time.perf_counter(), now_iso()
            if wfp:
                rec["launch"], wfp_cap = launch_with_wfp(exe, cfg_path, stg["state"], logf, tag, stg,
                                                         stg["work"].parent.parent / "wfp")
            else:
                try:
                    cp = hidden([str(exe), str(cfg_path), "--log-file", str(logf)], stg["state"], timeout=300)
                    rec["launch"] = {"exit_code": cp.returncode, "wall_secs": round(time.perf_counter() - t0, 3),
                                     "started": started, "stdout_tail": cp.stdout.strip()[-1500:],
                                     "stderr_tail": cp.stderr.strip()[-1500:]}
                except subprocess.TimeoutExpired:
                    rec["launch"] = {"timeout": True, "started": started}
            time.sleep(0.5)
            rec["launch"]["ended"] = now_iso()
            rec["unfenced_post"] = unfenced(gw, gw_port)
            log_text = logf.read_text(encoding="utf-8", errors="replace") if logf.exists() else ""
            rec["mxc_log_tail"] = log_text[-3000:]
            rec["mxc_log_full_text_has_process_start"] = summarise.mxc_process_started(log_text)
            rec["payload"] = json.loads(result_path.read_text(encoding="utf-8")) if result_path.exists() else None
            if result_path.exists():
                result_path.unlink()
            if wfp:
                rec["wfp"] = wfp_reading(wfp_cap, rec["payload"])
        else:
            rec["launch"] = {"skipped": "dry-run refused the policy"}
            rec["payload"] = None
            if wfp:
                rec["wfp"] = summarise.analyse_wfp(None, None, None, None, None, False,
                                                   ["no container launched: dry-run refused the policy"])
    finally:
        ins.close()
    with ins.lock:
        rec.update(target_log=list(ins.target_log), proxy_log=list(ins.proxy_log))
    rec["snapshot_after"] = snapshot(watched, stg["state"], programs)
    rec["state_changed_by_run"] = state_changes(rec["snapshot_before"], rec["snapshot_after"])
    rec["verdict"] = summarise.judge_run(rec)
    (out / f"run-{tag}.json").write_text(json.dumps(rec, indent=1), encoding="utf-8")
    return rec


def dry_run_only(arm: str, gw: str | None, gw_port: int, out: Path, stg: dict[str, Path],
                 token_mode: str = "elevated") -> Rec:
    fx_name, state = ARM_FIXTURE[arm]
    tag = f"{arm}-{state}-dry-{datetime.now().strftime('%H%M%S')}"
    policy = fixture(fx_name, payload_command(tag, stg["work"] / "unused.json", stg, gw, gw_port),
                     stg["work"], stg["payload"])
    cfg_path = stg["cfg"] / f"{tag}.json"
    cfg_path.write_text(json.dumps(policy, indent=1), encoding="utf-8")
    dry = hidden([str(LAUNCHERS[arm]), str(cfg_path), "--dry-run"], stg["state"])
    rec: Rec = {"arm": arm, "state": state, "fixture": fx_name, "mode": "dry-run-only", "policy_as_submitted": policy,
                "machine": machine_conditions(), "token": token_record(token_mode),
                "dry_run": {"rc": dry.returncode, "stdout": dry.stdout.strip()[-4000:], "stderr": dry.stderr.strip()[-4000:]}}
    (out / f"dryrun-{arm}-{state}.json").write_text(json.dumps(rec, indent=1), encoding="utf-8")
    return rec


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument("--runs", type=int, default=3)
    ap.add_argument("--arms", default="A,B")
    ap.add_argument("--dry-run-only", action="store_true")
    ap.add_argument("--arm-b-commit", default=None, help="40-hex source commit of arm B's launcher (required unless its sha256 is a known build)")
    ap.add_argument("--arm-b0-commit", default=None, help="40-hex source commit of arm B0's launcher (same rule)")
    ap.add_argument("--token", choices=("elevated", "standard"), default="elevated",
                    help="token mode recorded with the batch; standard is refused unless the token is non-elevated Medium integrity")
    ap.add_argument("--launch-sha256", default=None, help="launch.ps1's own sha256 as it computed it")
    ap.add_argument("--wfp-capture", action="store_true",
                    help="variant 4: WFP filter/state capture before, during and after each launch (elevated mode only)")
    args = ap.parse_args(argv)
    if args.wfp_capture and (args.token != "elevated" or args.dry_run_only or not is_elevated()):
        print("REFUSED: --wfp-capture needs --token elevated, an elevated process and a live run "
              "(netsh wfp is unreadable otherwise, which would blind the capture)")
        return 2
    arms = [a for a in args.arms.split(",") if a]
    if any(a not in LAUNCHERS for a in arms):
        print(f"REFUSED: unknown arm in {arms}; known: {sorted(LAUNCHERS)}")
        return 2
    tok_problem = token_mode_problem(args.token, token_info())
    if tok_problem:
        print(f"REFUSED: --token standard requires a non-elevated Medium-integrity token: {tok_problem}")
        return 2
    out = (args.out or default_out()).resolve()
    summarise.refuse_git_path(out)
    if (out / "batch-header.json").exists():
        print(f"REFUSED: {out} already holds a batch header; each batch needs a fresh output folder")
        return 2
    print(f"token mode: {args.token}; elevated: {is_elevated()}", flush=True)
    stg = {k: out / "staging" / k for k in ("cfg", "logs", "payload", "work", "state")}
    for d in (out, *stg.values()):
        d.mkdir(parents=True, exist_ok=True)
    if not CONTAINER_PY.exists():
        print(f"REFUSED: container Python absent at {CONTAINER_PY}")
        return 2
    (stg["payload"] / "net_payload.py").write_bytes((HERE / "net_payload.py").read_bytes())
    programs = [Path(sys.executable), CONTAINER_PY]
    watched = [stg["work"], stg["payload"], TOOLCHAIN, CONTAINER_PY]
    kernel32 = ctypes.windll.kernel32
    kernel32.SetPriorityClass(kernel32.GetCurrentProcess(), BELOW_NORMAL)
    gw = gateway_ip()
    gw_port = pick_gateway_port(gw)
    infos = {a: launcher_info(LAUNCHERS[a]) for a in arms}
    launch_ps1 = HERE / "launch.ps1"
    fw0 = firewall_state(programs)
    head: Rec = {"started": now_iso(), "account": getpass.getuser(), "elevated": is_elevated(),
                 "token_mode": args.token, "token": token_record(args.token),
                 "unreadable_under_this_token": unreadable_keys({
                     "wfp_mxc_filters": wfp_mxc_filter_count(out / "staging" / "scratch"),
                     "firewall": fw0.get("unreadable", ""),
                     "loopback_exempt": hidden(["CheckNetIsolation", "LoopbackExempt", "-s"], timeout=60).stdout.strip()
                     or "unreadable: empty output"}),
                 "host_python": sys.version, "harness_sha256": {f: sha256_of(HERE / f) for f in HARNESS_FILES},
                 "launch_ps1_sha256": sha256_of(launch_ps1) if launch_ps1.exists() else None,
                 "launch_ps1_sha256_as_passed_by_launcher": args.launch_sha256,
                 "interpreters": {"host": {"path": sys.executable, "sha256": sha256_of(Path(sys.executable))},
                                  "container": {"path": str(CONTAINER_PY), "sha256": sha256_of(CONTAINER_PY)}},
                 "arm_commits": {"A": {"release_tag": "v1.0.0", "basis": "the signed release launcher as designated by the operator; "
                                       "its sha256 and Authenticode status are in launchers.A (the launcher reports no version)"}},
                 "token_privileges": hidden(["whoami", "/priv"], timeout=60).stdout.strip(),
                 "host_prep": {"run_by_harness": False, "note": "wxc-host-prep is not invoked by this harness"},
                 "firewall_product": fw0.get("product"), "firewall_profiles": fw0.get("profiles"),
                 "gateway": {"ip": gw, "port_selected": gw_port, "candidate_ports": list(GATEWAY_PORTS)},
                 "ports": {"proxy": PROXY_PORT, "target": TARGET_PORT},
                 "launchers": infos, "machine_start": machine_conditions(), "runs_per_arm": args.runs,
                 "dry_run_only": args.dry_run_only, "priority": "BelowNormal", "scope_notes": {}}
    for a, info in infos.items():
        probes = (info.get("probe") or {}).get("probes") or {}
        info["probe_reports_psec_version"] = "psec" in json.dumps(info.get("probe") or {}).lower()
        head["scope_notes"][a] = (
            f"--probe reports baseContainerSupportsIngressHostLoopbackAllow="
            f"{probes.get('baseContainerSupportsIngressHostLoopbackAllow')!r}, {PROXY_FLAG}={probes.get(PROXY_FLAG)!r}; "
            f"this run measures this launcher on this host only")
    (out / "batch-header.json").write_text(json.dumps(head, indent=1), encoding="utf-8")
    runnable: list[str] = []
    for arm in arms:
        info = infos[arm]
        if not info.get("present"):
            reason = f"launcher absent at {info['path']}"
        elif arm in ("B", "B0"):
            ok, reason = check_arm_b_precondition(info.get("probe") or {})
            commit, why = resolve_arm_commit(info.get("sha256"), args.arm_b_commit if arm == "B" else args.arm_b0_commit)
            head["arm_commits"][arm] = {"commit": commit, "basis": why}
            if ok and commit is None:
                ok, reason = False, why
            if ok:
                runnable.append(arm)
                continue
        else:
            runnable.append(arm)
            continue
        (out / f"arm-{arm}-refused.json").write_text(
            json.dumps({"arm": arm, "refused": True, "reason": reason, "launcher": info}, indent=1), encoding="utf-8")
        print(f"arm {arm} REFUSED: {reason}", flush=True)
    (out / "batch-header.json").write_text(json.dumps(head, indent=1), encoding="utf-8")
    if args.dry_run_only:
        for arm in runnable:
            r = dry_run_only(arm, gw, gw_port, out, stg, args.token)
            print(json.dumps({"arm": arm, "dry_rc": r["dry_run"]["rc"], "stderr": r["dry_run"]["stderr"][:300]}), flush=True)
        return 0
    problems = check_ports_free([PROXY_PORT, TARGET_PORT])
    if problems:
        for text in problems:
            print(f"REFUSED: {text}", flush=True)
        return 3
    try:
        ctl = run_unfenced_control(gw, gw_port, out, args.token)
    except OSError as exc:
        print(f"REFUSED: cannot bind the probe listeners/proxy (ports {PROXY_PORT}-{TARGET_PORT}): {exc!r}")
        return 3
    print(json.dumps({"B5_control": ctl["judgement"]}), flush=True)
    wctl: Rec | None = None
    if args.wfp_capture:
        wctl = positive_control(out)
        print(json.dumps({"wfp_positive_control_ok": wctl["ok"], "problems": wctl["problems"][:3]}), flush=True)
    summary: Rec = {"groups": {}}
    for arm in runnable:
        for i in range(1, args.runs + 1):
            problems = check_ports_free([PROXY_PORT, TARGET_PORT])
            rec = None
            if not problems:
                try:
                    rec = run_one(arm, i, gw, gw_port, out, stg, watched, programs, args.token, args.wfp_capture)
                except OSError as exc:  # a bind lost to a process that took the port after the check
                    problems = [f"port {PROXY_PORT} or {TARGET_PORT} on 127.0.0.1 could not be bound ({exc!r}); "
                                + "; ".join(check_ports_free([PROXY_PORT, TARGET_PORT])) + " Nothing further was started."]
            if rec is None:
                aborted = {"verdict": "ABORTED-PORT-HELD", "arm": arm, "run": i, "at": now_iso(), "reasons": problems}
                (out / f"aborted-{arm}-r{i}.json").write_text(json.dumps(aborted, indent=1), encoding="utf-8")
                runs, ctl_rec = summarise.load_dir(out)
                summary = summarise.judge_batch(runs, ctl_rec, args.runs, wfp_control=wctl,
                                         unreadable=head["unreadable_under_this_token"])
                summary["aborted"] = aborted
                summary["arm_refusals"] = sorted(p.stem for p in out.glob("arm-*-refused.json"))
                (out / "batch-summary.json").write_text(json.dumps(summary, indent=1), encoding="utf-8")
                for text in problems:
                    print(f"STOP: ABORTED-PORT-HELD (arm {arm}, run {i}): {text}", flush=True)
                return 3
            print(json.dumps({"tag": rec["tag"], "verdict": rec["verdict"]["verdict"],
                              "reasons": rec["verdict"]["reasons"][:3], "dry_rc": rec["dry_run"]["rc"]}), flush=True)
            runs, ctl_rec = summarise.load_dir(out)
            summary = summarise.judge_batch(runs, ctl_rec, args.runs, wfp_control=wctl,
                                         unreadable=head["unreadable_under_this_token"])
            summary["arm_refusals"] = sorted(p.stem for p in out.glob("arm-*-refused.json"))
            (out / "batch-summary.json").write_text(json.dumps(summary, indent=1), encoding="utf-8")
            if rec["verdict"]["verdict"] == "FAIL":
                print("STOP: FAIL condition met")
                return 5
            if rec["state_changed_by_run"]:
                print("STOP: changed state; see the record")
                return 4
    head["finished"], head["machine_end"] = now_iso(), machine_conditions()
    (out / "batch-header.json").write_text(json.dumps(head, indent=1), encoding="utf-8")
    print(json.dumps({k: v["verdict"] for k, v in summary["groups"].items()} or {"arms": "none runnable"}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
