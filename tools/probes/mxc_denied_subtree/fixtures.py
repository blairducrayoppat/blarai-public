"""Tree, policy fixtures, path guards and machine records for the MXC denied-subtree probe.

Fixtures
  fx-a  readwritePaths [T], deniedPaths [T\\sub], distinct containerId per run, fallback.allowDaclMutation left
        at its default, captureDenials block (the default mode, stated), egress deny, no proxy, UI disabled.
  fx-b  fx-a with fallback.allowDaclMutation false.
  fx-c  fx-a with processContainer.leastPrivilege true and without captureDenials (the PSEC contract cannot
        represent leastPrivilege, so the request is serviced by an AppContainer tier; captureDenials there needs
        the guarded WPR fallback and is left out).

Guards (each raises GuardError; nothing is created before they pass)
  * the output directory and the tree must lie outside every git working tree;
  * the tree must be on a local fixed NTFS volume, not under OneDrive or the user profile, not UNC, and no
    existing ancestor may be a reparse point.
"""

from __future__ import annotations

import codecs
import ctypes
import ctypes.wintypes as wt
import getpass
import hashlib
import json
import os
import re
import subprocess
import sys
import winreg
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import payload as P  # noqa: E402

CREATE_NO_WINDOW = 0x08000000
BELOW_NORMAL = 0x00004000
DRIVE_FIXED = 3
REPARSE = 0x400
PWSH = "C:/Program Files/PowerShell/7/pwsh.exe"
TREE_ROOT = Path("C:/mxc-fx")
TIER_1 = "base-container"
TIER_3 = "appcontainer-dacl"
ALL_APP_PACKAGES = "S-1-15-2-1"
ALL_RESTRICTED_APP_PACKAGES = "S-1-15-2-2"
HOST_PREP_MASK = 0x00120088  # FILE_READ_ATTRIBUTES | FILE_READ_EA | READ_CONTROL | SYNCHRONIZE: the entries prepare-system-drive writes
# UI/win32k lockdown is off: with "disable": true the payload's _ctypes fails to initialise inside the container
# (a ConvertToGui denial), and this case measures the filesystem only.
UI_POLICY = {"disable": False, "clipboard": "none", "injection": False}
UI_LOCKDOWN_NOTE = ("UI lockdown is off (ui.disable false, clipboard none, injection false): with it on, importing _ctypes "
                    "fails inside the container; this probe measures the filesystem only")
SYS32 = "C:/Windows/System32/"
REG_MAPPINGS = (r"HKCU\Software\Classes\Local Settings\Software\Microsoft\Windows\CurrentVersion"
                r"\ProcessSandboxes\Mappings")
REG_AC_MAPPINGS = (r"HKCU\Software\Classes\Local Settings\Software\Microsoft\Windows\CurrentVersion"
                   r"\AppContainer\Mappings")


class GuardError(RuntimeError):
    pass


def win(p: Path | str) -> str:
    return str(p).replace("/", "\\")


def hidden(argv: list[str], timeout: float = 300, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(argv, capture_output=True, text=True, timeout=timeout, env=env, check=False,
                          creationflags=CREATE_NO_WINDOW | BELOW_NORMAL)


# ------------------------------------------------------------------ guards

def in_git_tree(path: Path) -> bool:
    """True when path or any ancestor holds a .git entry (directory, or file for a linked worktree)."""
    p = Path(os.path.abspath(path))
    return any((q / ".git").exists() for q in [p, *p.parents])


def assert_outside_git(path: Path, what: str) -> None:
    if in_git_tree(path):
        raise GuardError(f"{what} {path} is inside a git working tree")


def volume_info(path: Path) -> dict[str, object]:
    drive, _ = os.path.splitdrive(os.path.abspath(path))
    if not (len(drive) == 2 and drive[1] == ":"):
        raise GuardError(f"{path} has no drive letter (UNC or device path)")
    root = drive + "\\"
    k32 = ctypes.windll.kernel32
    dtype = k32.GetDriveTypeW(root)
    fs = ctypes.create_unicode_buffer(64)
    ok = k32.GetVolumeInformationW(root, None, 0, None, None, None, fs, 64)
    return {"drive": drive.upper(), "drive_type": dtype, "fixed": dtype == DRIVE_FIXED,
            "filesystem": fs.value if ok else None}


def _reparse_ancestors(path: Path) -> list[str]:
    k32 = ctypes.windll.kernel32
    k32.GetFileAttributesW.restype = ctypes.c_uint32
    found = []
    p = Path(os.path.abspath(path))
    for q in [p, *p.parents]:
        if q.exists():
            attr = k32.GetFileAttributesW(str(q))
            if attr != 0xFFFFFFFF and attr & REPARSE:
                found.append(str(q))
    return found


def _norm(p: str | Path) -> str:
    return os.path.normcase(os.path.abspath(str(p)))


def assert_local_ntfs(path: Path) -> dict[str, object]:
    """Refuse anything but a local fixed NTFS path outside OneDrive and the user profile; return the volume record."""
    info = volume_info(path)
    if not info["fixed"]:
        raise GuardError(f"{info['drive']} is not a local fixed drive (type {info['drive_type']})")
    if info["filesystem"] != "NTFS":
        raise GuardError(f"{info['drive']} is {info['filesystem']}, not NTFS")
    n = _norm(path)
    sync_roots = [os.environ.get(k) for k in ("OneDrive", "OneDriveConsumer", "OneDriveCommercial", "USERPROFILE")]
    for root in filter(None, sync_roots):
        r = _norm(root)
        if n == r or n.startswith(r + os.sep):
            raise GuardError(f"{path} is under {'OneDrive' if 'onedrive' in r.lower() else 'the user profile'}")
    if any(part.lower().startswith("onedrive") for part in Path(n).parts):
        raise GuardError(f"{path} has a OneDrive path component")
    rp = _reparse_ancestors(path)
    if rp:
        raise GuardError(f"reparse point on the path: {rp}")
    return info


# ------------------------------------------------------------------ tree

def make_tree(base: Path, tag: str) -> dict[str, Path]:
    """Create base/T and base/T/sub with their files; base must not exist yet. Returns the named paths."""
    t, sub = base / "T", base / "T" / P.SUB
    sub.mkdir(parents=True)
    (t / P.MARKER).write_bytes(f"T-MARKER {tag}\n".encode())
    for name, data in P.sub_contents(tag).items():
        (sub / name).write_bytes(data)
    return {"base": base, "T": t, "sub": sub}


# ------------------------------------------------------------------ policy

def policy(variant: str, container_id: str, t: Path, payload_dir: Path, toolchain: Path, python: Path,
           report: Path, script: str = "payload.py") -> dict[str, object]:
    cmd = f'"{win(python)}" -I -B "{win(payload_dir / script)}" --t "{win(t)}" --out "{win(report)}" --mode container'
    cfg: dict[str, object] = {
        "version": "1.0.0", "containerId": container_id, "containment": "processcontainer",
        "lifecycle": {"destroyOnExit": True},
        "process": {"commandLine": cmd, "cwd": win(t), "inheritDefaultEnv": True, "timeout": 120000},
        "filesystem": {"readwritePaths": [win(t)], "deniedPaths": [win(t / P.SUB)],
                       "readonlyPaths": [win(toolchain), win(payload_dir)]},
        "network": {"egress": {"default": "deny"}, "ingress": {"default": "deny", "hostLoopback": "deny"}},
        "ui": UI_POLICY,
        "processContainer": {"captureDenials": {"mode": "block"}},
    }
    if variant == "fx-b":
        cfg["fallback"] = {"allowDaclMutation": False}
    elif variant == "fx-c":
        # captureDenials is omitted: on an AppContainer tier it needs the guarded WPR fallback (an elevated guardian
        # that refuses an install directory owned by a non-privileged account), and the case measures deniedPaths only.
        cfg["processContainer"] = {"leastPrivilege": True}
    elif variant != "fx-a":
        raise ValueError(variant)
    return cfg


# ------------------------------------------------------------------ icacls / SDDL

def icacls(path: Path) -> dict[str, object]:
    cp = hidden([SYS32 + "icacls.exe", str(path)], timeout=60)
    return {"rc": cp.returncode, "text": cp.stdout.strip()}


KNOWN_ACE_TYPES = ("A", "D", "OA", "OD")


def parse_dacl(sddl: str) -> dict[str, object]:
    """Owner, ordered ACE strings and whether every ACE was understood.

    ``ok`` is False when the parentheses do not balance or an ACE type is not one of A, D, OA, OD
    (conditional and callback ACEs are not understood and are never skipped).
    """
    owner = re.match(r"O:(.*?)(?:G:|D:|S:|$)", sddl)
    m = re.search(r"D:([A-Z]*)", sddl)
    aces: list[str] = []
    ok = True
    if m:
        i, depth, start = m.end(), 0, -1
        while i < len(sddl):
            c = sddl[i]
            if c == "(":
                if depth == 0:
                    start = i
                depth += 1
            elif c == ")":
                depth -= 1
                if depth < 0:
                    ok = False
                    break
                if depth == 0:
                    aces.append(sddl[start + 1:i])
            elif depth == 0:
                break  # the next section (S:) begins
            i += 1
        if depth != 0:
            ok = False
    ok = ok and all(a.split(";", 1)[0] in KNOWN_ACE_TYPES for a in aces)
    return {"owner": owner.group(1) if owner else "", "aces": aces, "ok": ok}


def ace_types(sddl: str) -> dict[str, int]:
    """Count ACE types (A allow, D deny, OA/OD object, ...) in the DACL of an SDDL string."""
    counts: dict[str, int] = {}
    for ace in parse_dacl(sddl)["aces"]:  # type: ignore[union-attr]
        t = ace.split(";", 1)[0]
        counts[t] = counts.get(t, 0) + 1
    return counts


_adv = ctypes.WinDLL("advapi32", use_last_error=True)
_k32 = ctypes.WinDLL("kernel32", use_last_error=True)
_adv.GetNamedSecurityInfoW.argtypes = [wt.LPCWSTR, ctypes.c_int, wt.DWORD, ctypes.c_void_p, ctypes.c_void_p,
                                       ctypes.c_void_p, ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)]
_adv.GetNamedSecurityInfoW.restype = wt.DWORD
_adv.ConvertSecurityDescriptorToStringSecurityDescriptorW.argtypes = [
    ctypes.c_void_p, wt.DWORD, wt.DWORD, ctypes.POINTER(wt.LPWSTR), ctypes.c_void_p]
_k32.LocalFree.argtypes = [ctypes.c_void_p]
SE_FILE_OBJECT, OWNER_GROUP_DACL = 1, 0x1 | 0x2 | 0x4


def read_sddl(path: Path) -> str:
    """Owner, group and DACL of path as SDDL (read-only; GetNamedSecurityInfoW)."""
    sd = ctypes.c_void_p()
    rc = _adv.GetNamedSecurityInfoW(str(path), SE_FILE_OBJECT, OWNER_GROUP_DACL, None, None, None, None, ctypes.byref(sd))
    if rc != 0:
        raise OSError(rc, f"GetNamedSecurityInfoW {path}: error {rc}")
    text = wt.LPWSTR()
    try:
        if not _adv.ConvertSecurityDescriptorToStringSecurityDescriptorW(sd, 1, OWNER_GROUP_DACL, ctypes.byref(text), None):
            raise ctypes.WinError(ctypes.get_last_error())
        return text.value or ""
    finally:
        if sd:
            _k32.LocalFree(sd)


def same_acl(a: str, b: str) -> bool:
    """Equal owner and equal ordered ACE list; False when either DACL is not fully understood.

    The DACL control flags (such as auto-inherited) are not compared.
    """
    pa, pb = parse_dacl(a), parse_dacl(b)
    return bool(pa["ok"]) and bool(pb["ok"]) and pa["owner"] == pb["owner"] and pa["aces"] == pb["aces"]


def acl_capture(path: Path) -> dict[str, object]:
    """icacls text plus raw SDDL plus ACE type counts. SIDs stay raw here."""
    try:
        sddl = read_sddl(path)
        types = ace_types(sddl)
    except OSError as exc:
        sddl, types = f"<unreadable: {exc}>", {}
    return {"icacls": icacls(path), "sddl": sddl, "ace_types": types, "parse_ok": bool(parse_dacl(sddl)["ok"]),
            "deny_aces": types.get("D", 0) + types.get("OD", 0)}


def icacls_save(path: Path, dest: Path) -> dict[str, object]:
    """icacls /save of the whole tree under path into dest (recursive, quiet); the record names the file and its hash."""
    cp = hidden([SYS32 + "icacls.exe", str(path), "/save", str(dest), "/T", "/Q"], timeout=1800)
    ok = dest.exists()
    return {"rc": cp.returncode, "dest": str(dest), "saved": ok, "size": dest.stat().st_size if ok else None,
            "sha256": file_sha256(dest) if ok else None, "output": (cp.stdout + cp.stderr).strip()[-300:]}


def parse_icacls_save(p: Path) -> dict[str, object] | None:
    """Object name -> (DACL flags, sorted ACE strings) from an icacls /save file; None when unreadable or empty."""
    try:
        raw = p.read_bytes()
        if raw[:2] in (codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE):
            text = raw.decode("utf-16")
        elif len(raw) > 1 and raw[1] == 0:  # icacls writes UTF-16LE without a byte-order mark
            text = raw.decode("utf-16-le")
        else:
            text = raw.decode("utf-8")
    except (OSError, UnicodeError):
        return None
    out: dict[str, object] = {}
    name = None
    for line in (ln.strip() for ln in text.splitlines()):
        if not line:
            continue
        if line.startswith(("D:", "S:", "O:", "G:")) and name is not None:
            parsed = parse_dacl(line)
            m = re.search(r"D:([A-Z]*)", line)
            out[name] = (m.group(1) if m else "", tuple(sorted(parsed["aces"]))) if parsed["ok"] else ("raw", line)  # type: ignore[arg-type]
            name = None
        else:
            name = line
    return out or None


def compare_icacls_saves(a: Path, b: Path) -> dict[str, object]:
    """Order-insensitive per-object comparison of two icacls /save files; unchanged is None when either is unusable."""
    pa, pb = parse_icacls_save(a), parse_icacls_save(b)
    if pa is None or pb is None:
        return {"unchanged": None, "objects_start": None if pa is None else len(pa), "objects_end": None if pb is None else len(pb),
                "differences": ["a save file is missing, unreadable or holds no object"]}
    diffs = [f"{n}: only at start" for n in sorted(pa.keys() - pb.keys())] + [f"{n}: only at end" for n in sorted(pb.keys() - pa.keys())]
    diffs += [f"{n}: DACL differs" for n in sorted(pa.keys() & pb.keys()) if pa[n] != pb[n]]
    return {"unchanged": not diffs, "objects_start": len(pa), "objects_end": len(pb), "differences": diffs[:40],
            "difference_count": len(diffs)}


# ------------------------------------------------------------------ machine and launcher

def file_sha256(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def interpreter_info(exe: Path) -> dict[str, object]:
    return {"path": str(exe), "sha256": file_sha256(exe), "size": exe.stat().st_size}


def mxc_state_dir() -> Path:
    """MXC's own default restore-journal directory (never redirected by this probe)."""
    base = os.environ.get("LOCALAPPDATA") or str(Path(os.environ["USERPROFILE"]) / "AppData" / "Local")
    return Path(base) / "Microsoft" / "MXC" / "dacl-restore"


def dir_listing(d: Path) -> list[dict[str, object]]:
    """Names, sizes and sha256 of everything under d (empty list when d is absent)."""
    if not d.exists():
        return []
    return [{"name": p.relative_to(d).as_posix(), "size": p.stat().st_size, "sha256": None if p.is_dir() else file_sha256(p)}
            for p in sorted(d.rglob("*"))]


def launcher_info(exe: Path) -> dict[str, object]:
    probe = hidden([str(exe), "--probe"], timeout=60)
    try:
        pj = json.loads(probe.stdout)
    except ValueError:
        pj = {"unparsed": probe.stdout[-400:]}
    sig = hidden([PWSH, "-NoProfile", "-Command",
                  f"$s=Get-AuthenticodeSignature '{exe}'; \"$($s.Status)|$($s.SignerCertificate.Subject)\""]).stdout.strip()
    return {"path": str(exe), "sha256": hashlib.sha256(exe.read_bytes()).hexdigest(), "size": exe.stat().st_size,
            "signature": sig, "probe_rc": probe.returncode,
            "probe": pj}


def s0_record(info: dict[str, object]) -> dict[str, object]:
    """The S0 fields read out of a launcher_info record: tier, whether native deny is advertised, DACL augmentation."""
    pr = info.get("probe") or {}
    probes = pr.get("probes") or {}  # type: ignore[union-attr]
    tier = pr.get("tier")  # type: ignore[union-attr]
    return {"tier": tier, "needs_dacl_augmentation": pr.get("needsDaclAugmentation"),  # type: ignore[union-attr]
            "fs_deny_advertised": probes.get("baseContainerSupportsDenyPaths"),
            "warnings": pr.get("warnings"),  # type: ignore[union-attr]
            "dacl_tier": tier not in (None, "base-container")}


def sddl_has_host_prep(sddl: str) -> bool:
    """True when the DACL holds exactly the entries prepare-system-drive writes.

    Each of ALL APPLICATION PACKAGES (alias AC or S-1-15-2-1) and ALL RESTRICTED APPLICATION PACKAGES (S-1-15-2-2)
    must have a plain allow ACE with mask 0x00120088, not inherited and not inheriting (no ID, OI, CI or IO flag),
    with no object type. A deny, another mask, an inherited or inheriting entry, or one SID alone does not count.
    """
    found: set[str] = set()
    for ace in parse_dacl(sddl)["aces"]:  # type: ignore[union-attr]
        f = ace.split(";")
        if len(f) != 6 or f[0] != "A" or f[3] or f[4]:
            continue
        flags = {f[1][i:i + 2] for i in range(0, len(f[1]), 2)}
        if flags & {"ID", "OI", "CI", "IO"}:
            continue
        try:
            mask = int(f[2], 0)
        except ValueError:
            continue
        sid = ALL_APP_PACKAGES if f[5] in ("AC", ALL_APP_PACKAGES) else f[5]
        if mask == HOST_PREP_MASK and sid in (ALL_APP_PACKAGES, ALL_RESTRICTED_APP_PACKAGES):
            found.add(sid)
    return found == {ALL_APP_PACKAGES, ALL_RESTRICTED_APP_PACKAGES}


def host_prep_evidence(root: Path | None = None) -> dict[str, object]:
    """The system-drive root DACL as SDDL and whether the prepare-system-drive entries are present (read-only)."""
    root = root or Path(os.environ.get("SystemDrive", "C:") + "\\")
    try:
        sddl = read_sddl(root)
        return {"path": str(root), "sddl": sddl, "prep_entries_present": sddl_has_host_prep(sddl)}
    except OSError as exc:
        return {"path": str(root), "sddl": f"<unreadable: {exc}>", "prep_entries_present": None}


def host_prep_observed(start: dict[str, object], end: dict[str, object] | None = None) -> str:
    """A statement of what the batch's own reads show about the system-drive prep; never a constant."""
    s = start.get("prep_entries_present") is True
    if end is None:
        return "observed in effect at batch start" if s else "not observed at batch start"
    e = end.get("prep_entries_present") is True
    if s and e:
        return "observed in effect"
    if s:
        return "observed in effect at batch start, not at batch end"
    if e:
        return "not observed at batch start, observed at batch end"
    return "not observed"


def host_prep_status(dry_stdout: str) -> list[dict[str, object]]:
    """Each wxc-host-prep subcommand the launcher's dry-run output names, with whether its effect is verifiable and present.

    prepare-system-drive is in effect when the system-drive root holds the entries it writes (read-only check). Any other subcommand cannot be verified without elevation and counts as not in effect (fail closed).
    """
    out = []
    for name in sorted(set(re.findall(r"wxc-host-prep (prepare-[a-z-]+)", dry_stdout))):
        if name == "prepare-system-drive":
            try:
                on = host_prep_evidence()["prep_entries_present"] is True
            except OSError:
                on = False
            out.append({"subcommand": name, "in_effect": on, "checked_by": "system-drive root DACL"})
        else:
            out.append({"subcommand": name, "in_effect": False, "checked_by": "not verifiable without elevation"})
    return out


def windows_build() -> dict[str, object]:
    k = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows NT\CurrentVersion")
    out: dict[str, object] = {}
    for n in ("ProductName", "DisplayVersion", "CurrentBuild", "UBR"):
        try:
            out[n] = winreg.QueryValueEx(k, n)[0]
        except OSError:
            out[n] = None
    out["build"] = f"{out['CurrentBuild']}.{out['UBR']}"
    return out


class _PowerStatus(ctypes.Structure):
    _fields_ = [("ACLineStatus", ctypes.c_ubyte), ("BatteryFlag", ctypes.c_ubyte), ("BatteryLifePercent", ctypes.c_ubyte),
                ("SystemStatusFlag", ctypes.c_ubyte), ("BatteryLifeTime", ctypes.c_uint32),
                ("BatteryFullLifeTime", ctypes.c_uint32)]


def machine_conditions() -> dict[str, object]:
    ps = _PowerStatus()
    ctypes.windll.kernel32.GetSystemPowerStatus(ctypes.byref(ps))
    tl = hidden([SYS32 + "tasklist.exe", "/fo", "csv", "/nh"], timeout=60).stdout
    names = [ln.split('","')[0].strip('"') for ln in tl.splitlines() if ln.strip()]
    bd = [n for n in names if re.search(r"^(bd|bitdefender|vsserv|epsecurity|epintegration|updatesrv|seccenter|epprotected)", n, re.I)]
    return {"elevated": bool(ctypes.windll.shell32.IsUserAnAdmin()), "ac_power": ps.ACLineStatus == 1,
            "battery_percent": ps.BatteryLifePercent, "bitdefender_process_count": len(bd),
            "bitdefender_process_names": sorted(set(bd)), "process_count": len(names),
            "account": getpass.getuser(), "windows": windows_build()}


def reg_list(key: str) -> list[str]:
    cp = hidden([SYS32 + "reg.exe", "query", key], timeout=60)
    if cp.returncode != 0:
        return ["<absent>"]
    return sorted(ln.strip() for ln in cp.stdout.splitlines() if ln.strip().startswith("HKEY"))


# ------------------------------------------------------------------ token privileges

class _Luid(ctypes.Structure):
    _fields_ = [("LowPart", wt.DWORD), ("HighPart", wt.LONG)]


class _TokenPrivileges(ctypes.Structure):
    """TOKEN_PRIVILEGES with one LUID_AND_ATTRIBUTES: Count at 0, LUID at 4, Attributes at 12, size 16."""

    _fields_ = [("Count", wt.DWORD), ("Luid", _Luid), ("Attributes", wt.DWORD)]


SE_PRIVILEGE_ENABLED = 0x2
GUARDED_PRIVILEGES = ("SeBackupPrivilege", "SeRestorePrivilege", "SeTakeOwnershipPrivilege", "SeSecurityPrivilege")
ERROR_NOT_ALL_ASSIGNED = 1300
_pk32 = ctypes.WinDLL("kernel32", use_last_error=True)
_padv = ctypes.WinDLL("advapi32", use_last_error=True)
_pk32.GetCurrentProcess.restype = wt.HANDLE
_pk32.CloseHandle.argtypes = [wt.HANDLE]
_padv.OpenProcessToken.argtypes = [wt.HANDLE, wt.DWORD, ctypes.POINTER(wt.HANDLE)]
_padv.LookupPrivilegeValueW.argtypes = [wt.LPCWSTR, wt.LPCWSTR, ctypes.POINTER(_Luid)]
_padv.LookupPrivilegeNameW.argtypes = [wt.LPCWSTR, ctypes.POINTER(_Luid), wt.LPWSTR, ctypes.POINTER(wt.DWORD)]
_padv.AdjustTokenPrivileges.argtypes = [wt.HANDLE, wt.BOOL, ctypes.POINTER(_TokenPrivileges), wt.DWORD, ctypes.c_void_p, ctypes.c_void_p]
_padv.GetTokenInformation.argtypes = [wt.HANDLE, ctypes.c_int, ctypes.c_void_p, wt.DWORD, ctypes.POINTER(wt.DWORD)]


def _open_token() -> wt.HANDLE:
    tok = wt.HANDLE()
    if not _padv.OpenProcessToken(_pk32.GetCurrentProcess(), 0x20 | 0x8, ctypes.byref(tok)):  # ADJUST_PRIVILEGES | QUERY
        raise ctypes.WinError(ctypes.get_last_error())
    return tok


def token_privileges() -> list[dict[str, object]]:
    """Every privilege in this process token as {name, enabled}, read back with GetTokenInformation."""
    tok = _open_token()
    try:
        need = wt.DWORD()
        _padv.GetTokenInformation(tok, 3, None, 0, ctypes.byref(need))  # TokenPrivileges
        buf = ctypes.create_string_buffer(need.value)
        if not _padv.GetTokenInformation(tok, 3, buf, need.value, ctypes.byref(need)):
            raise ctypes.WinError(ctypes.get_last_error())
        count = int.from_bytes(buf.raw[:4], "little")
        out = []
        for i in range(count):
            off = 4 + 12 * i
            luid = _Luid.from_buffer_copy(buf.raw[off:off + 8])
            attrs = int.from_bytes(buf.raw[off + 8:off + 12], "little")
            name = ctypes.create_unicode_buffer(128)
            size = wt.DWORD(128)
            _padv.LookupPrivilegeNameW(None, ctypes.byref(luid), name, ctypes.byref(size))
            out.append({"name": name.value, "enabled": bool(attrs & SE_PRIVILEGE_ENABLED)})
        return out
    finally:
        _pk32.CloseHandle(tok)


def disable_privileges(names: tuple[str, ...] = GUARDED_PRIVILEGES, layout: type[ctypes.Structure] = _TokenPrivileges) -> dict[str, str]:
    """Disable each named privilege this token holds; return {name: outcome}. Outcome is "disabled", "absent" or an error.

    A call counts as a success only when AdjustTokenPrivileges returned true AND GetLastError is 0
    (ERROR_NOT_ALL_ASSIGNED, 1300, is a failure). The caller must still verify with token_privileges().
    """
    held = {p["name"] for p in token_privileges()}
    tok = _open_token()
    out: dict[str, str] = {}
    try:
        for n in names:
            if n not in held:
                out[n] = "absent"
                continue
            luid = _Luid()
            if not _padv.LookupPrivilegeValueW(None, n, ctypes.byref(luid)):
                out[n] = f"lookup failed {ctypes.get_last_error()}"
                continue
            tp = layout(1, luid, 0)
            ctypes.set_last_error(0)
            ok = _padv.AdjustTokenPrivileges(tok, False, ctypes.byref(tp), 0, None, None)
            err = ctypes.get_last_error()
            out[n] = "disabled" if (ok and err == 0) else f"failed (returned {bool(ok)}, error {err})"
    finally:
        _pk32.CloseHandle(tok)
    return out


def enable_privilege(name: str) -> bool:
    """Enable a privilege this token holds (used only by the self-test to build the hostile starting state)."""
    tok = _open_token()
    try:
        luid = _Luid()
        if not _padv.LookupPrivilegeValueW(None, name, ctypes.byref(luid)):
            return False
        tp = _TokenPrivileges(1, luid, SE_PRIVILEGE_ENABLED)
        ctypes.set_last_error(0)
        return bool(_padv.AdjustTokenPrivileges(tok, False, ctypes.byref(tp), 0, None, None)) and ctypes.get_last_error() == 0
    finally:
        _pk32.CloseHandle(tok)


def enabled_guarded() -> list[str]:
    return sorted(p["name"] for p in token_privileges() if p["enabled"] and p["name"] in GUARDED_PRIVILEGES)  # type: ignore[misc]


def secure_token() -> dict[str, object]:
    """Disable the guarded privileges, read the token back, and refuse (GuardError) if any is still enabled."""
    before = token_privileges()
    outcome = disable_privileges()
    after = token_privileges()
    left = [p["name"] for p in after if p["enabled"] and p["name"] in GUARDED_PRIVILEGES]
    if left:
        raise GuardError(f"privileges still enabled after disabling: {left} ({outcome})")
    return {"before": before, "outcome": outcome, "after": after}


# ------------------------------------------------------------------ security suite and registry scoping

def security_suite() -> list[dict[str, object]]:
    """Antivirus products registered with the Security Center: name, product state, executable and its version."""
    ps = ("Get-CimInstance -Namespace root/SecurityCenter2 -ClassName AntiVirusProduct | ForEach-Object {"
          " $v=''; try { $v=(Get-Item -LiteralPath $_.pathToSignedProductExe.TrimStart([char]92,[char]63)).VersionInfo.ProductVersion } catch {};"
          " [pscustomobject]@{name=$_.displayName; state=$_.productState; exe=$_.pathToSignedProductExe; version=$v} } |"
          " ConvertTo-Json -Compress")
    cp = hidden([PWSH, "-NoProfile", "-Command", ps], timeout=120)
    try:
        j = json.loads(cp.stdout)
    except ValueError:
        return [{"error": (cp.stdout + cp.stderr)[-300:]}]
    return j if isinstance(j, list) else [j]


def registry_diff(before: list[str], after: list[str], container_id: str) -> dict[str, list[str]]:
    """Registry keys that appeared or vanished, split into those whose contents name container_id and the rest."""
    changed = sorted(set(before) ^ set(after))
    related, unrelated = [], []
    for k in changed:
        text = hidden([SYS32 + "reg.exe", "query", k, "/s"], timeout=60).stdout if k != "<absent>" else ""
        (related if container_id.lower() in text.lower() or container_id.lower() in k.lower() else unrelated).append(k)
    return {"related": related, "unrelated": unrelated}
