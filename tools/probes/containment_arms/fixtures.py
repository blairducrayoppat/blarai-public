# NOTE (2026-10-11 review): these probes were built for one finished study on a dev box and are not hardened for reuse.
# The throwaway roots inherit write access from C:\ for other accounts and the fixture tree is owned by the operator;
# before reusing any of it, restrict the roots to administrators and SYSTEM and take ownership away from the operator.
"""Throwaway fixtures for the #1740 containment comparison.

Creates ``C:/blarai-spike-1740`` (and removes it with ``--teardown``). Nothing outside that
folder is written. Real folders are only READ, to copy their access lists onto stand-ins.

Layout:
  instrument/grant-<setup>   the setup's identity granted Modify by name (expect: write)
  instrument/deny-<setup>    the same plus an explicit deny-write ACE (expect: no write)
                             (B3 restricts with the same synthetic SID as B2, so the B2 pair is
                             B3's on/off test too)
  leak/<name>                stand-ins carrying a copy of a real folder's DACL (protected,
                             so the copy does not depend on where the stand-in sits)
  worktree/                  the arm's work folder: operator, coder, write-SID and package
                             identities granted Modify by name
"""

from __future__ import annotations

import argparse
import ctypes
import ctypes.wintypes as wt
import json
import os
import shutil
import stat
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import effective_access as ea
import winsec as w

ROOT = Path("C:/blarai-spike-1740")
DACL_SECURITY_INFORMATION = 0x4
PROTECTED_DACL_SECURITY_INFORMATION = 0x80000000
# FILE_GENERIC_READ|WRITE|EXECUTE|DELETE: "Modify".
MODIFY = "0x1301bf"
ADMIN_SYSTEM = "(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)"

# Copied from the real folder at creation time.
LEAK_SOURCES = {
    "models": "B:/models",
    "fleet": "C:/blarai-fleet",
    "projects": str(ea.OPERATOR_HOME / "projects"),
    "windows-temp-today": "C:/Windows/Temp",
}
# Classes of grant recorded on the tickets, reproduced literally. windows-temp-classic is
# the Windows default for C:\Windows\Temp before it was narrowed (Users may create files
# and folders and traverse; CREATOR OWNER full on what they create).
LEAK_LITERAL = {
    "authenticated-users-modify": f"D:P{ADMIN_SYSTEM}(A;OICI;{MODIFY};;;AU)",
    "windows-temp-classic": f"D:P{ADMIN_SYSTEM}(A;CI;0x100026;;;BU)(A;OICIIO;FA;;;CO)",
    "users-modify": f"D:P{ADMIN_SYSTEM}(A;OICI;{MODIFY};;;BU)",
}


def identities() -> dict[str, str]:
    op = w.sid_of_account(os.environ.get("USERNAME") or __import__("getpass").getuser())
    return {
        "A": w.sid_of_account("blarai-coder"),
        "D": op,
        "B1": op,
        "B2": ea.synthetic_sid("blarai-1740-write"),
        "C": w.derive_appcontainer_sid("blarai.1740.coder"),
        "operator": op,
    }


def set_dacl(path: Path, sddl: str) -> None:
    sd = ctypes.c_void_p()
    if not w.advapi32.ConvertStringSecurityDescriptorToSecurityDescriptorW(
            wt.LPCWSTR(sddl), 1, ctypes.byref(sd), None):
        raise OSError(ctypes.get_last_error(), f"bad SDDL for {path}: {sddl}")
    try:
        if not w.advapi32.SetFileSecurityW(
                wt.LPCWSTR(str(path)),
                DACL_SECURITY_INFORMATION | PROTECTED_DACL_SECURITY_INFORMATION, sd):
            raise OSError(ctypes.get_last_error(), f"SetFileSecurityW {path}")
    finally:
        w.kernel32.LocalFree(sd)


def dacl_part(sddl: str) -> str:
    """The D:... section of an SDDL string, made protected (D:P...)."""
    start = sddl.index("D:")
    end = sddl.find("S:", start)
    d = sddl[start:end if end != -1 else None]
    flags_end = d.index("(") if "(" in d else len(d)
    flags = d[2:flags_end].replace("P", "")
    return "D:P" + flags + d[flags_end:]


def create() -> dict[str, object]:
    if ROOT.exists():
        raise SystemExit(f"{ROOT} exists; run --teardown first")
    ids = identities()
    ROOT.mkdir()
    everyone_read = "(A;OICI;0x1200a9;;;WD)(A;OICI;0x1200a9;;;AC)"
    set_dacl(ROOT, f"D:P{ADMIN_SYSTEM}{everyone_read}")
    record: dict[str, object] = {"root": str(ROOT), "identities": ids, "folders": {}}
    inst = ROOT / "instrument"
    inst.mkdir()
    set_dacl(inst, f"D:P{ADMIN_SYSTEM}{everyone_read}")
    for setup in ("A", "D", "B2", "C"):
        sid = ids[setup]
        # B2 and C pass a second check only after the operator's own ACL check passes.
        first_pass = f"(A;OICI;{MODIFY};;;{ids['operator']})" if setup in ("B2", "C") else ""
        grant = f"D:P{ADMIN_SYSTEM}{first_pass}(A;OICI;{MODIFY};;;{sid})"
        deny = f"D:P(D;OICI;0x116;;;{sid}){ADMIN_SYSTEM}{first_pass}(A;OICI;{MODIFY};;;{sid})"
        for name, sddl in ((f"grant-{setup}", grant), (f"deny-{setup}", deny)):
            p = inst / name
            p.mkdir()
            set_dacl(p, sddl)
            record["folders"][str(p)] = sddl
    leak = ROOT / "leak"
    leak.mkdir()
    set_dacl(leak, f"D:P{ADMIN_SYSTEM}{everyone_read}")
    w.enable_privilege("SeBackupPrivilege")
    for name, src in LEAK_SOURCES.items():
        sddl = dacl_part(w.read_descriptor(src).sddl)
        p = leak / name
        p.mkdir()
        set_dacl(p, sddl)
        record["folders"][str(p)] = {"copied_from": src, "sddl": sddl}
    for name, sddl in LEAK_LITERAL.items():
        p = leak / name
        p.mkdir()
        set_dacl(p, sddl)
        record["folders"][str(p)] = {"literal": True, "sddl": sddl}
    wt_dir = ROOT / "worktree"
    wt_dir.mkdir()
    grants = "".join(f"(A;OICI;{MODIFY};;;{ids[k]})" for k in ("operator", "A", "B2", "C"))
    sddl = f"D:P{ADMIN_SYSTEM}{grants}"
    set_dacl(wt_dir, sddl)
    record["folders"][str(wt_dir)] = sddl
    (ROOT / "fixtures.json").write_text(json.dumps(record, indent=1), encoding="utf-8")
    return record


TOOLCHAIN_SOURCES = {
    "Python314": "C:/Python314",
    "nodejs": "C:/Program Files/nodejs",
    "Git": "C:/Program Files/Git",
    "npm/node_modules/opencode-ai": str(ea.OPERATOR_HOME / "AppData/Roaming/npm/node_modules/opencode-ai"),
}


def toolchain_copy() -> dict[str, object]:
    """Copy the coder toolchain under the fixture root (phase 2, for setups that cannot read
    the real install folders). Data and timestamps only: the copies inherit the fixture
    root's access list, so no real folder's permissions are touched."""
    if not (ROOT / "fixtures.json").exists():
        raise SystemExit("create the fixtures first")
    dest_root = ROOT / "toolchain"
    out: dict[str, object] = {}
    for rel, src in TOOLCHAIN_SOURCES.items():
        dest = dest_root / rel
        dest.mkdir(parents=True, exist_ok=True)
        cp = subprocess.run(["robocopy", src, str(dest), "/E", "/COPY:DAT", "/DCOPY:T", "/R:1",
                             "/W:1", "/NFL", "/NDL", "/NJH", "/NP"], capture_output=True,
                            text=True, creationflags=0x08000000, check=False)
        out[rel] = {"source": src, "robocopy_rc": cp.returncode, "ok": cp.returncode < 8}
    shim = dest_root / "npm/opencode.cmd"
    shim.write_text(Path(ea.OPERATOR_HOME / "AppData/Roaming/npm/opencode.cmd")
                    .read_text(encoding="ascii"), encoding="ascii")
    out["npm/opencode.cmd"] = {"ok": shim.exists()}
    return out


def teardown() -> None:
    if not ROOT.exists():
        return
    # Refuse a link or junction at the root: removing through it would reach whatever it
    # points at. Python's rmtree also refuses link roots; this check does not rely on that.
    if ROOT.is_symlink() or ROOT.is_junction():
        raise SystemExit(f"{ROOT} is a link or junction; refusing to remove it")
    if not (ROOT / "fixtures.json").exists():
        raise SystemExit(f"{ROOT} has no fixtures.json; refusing to remove a folder this tool did not create")

    def clear_readonly_and_retry(func: Callable[[str], object], path: str, _exc: BaseException) -> None:
        # The payload's task repos hold git object files, which git writes read-only.
        os.chmod(path, stat.S_IWRITE, follow_symlinks=False)  # never touch a link target outside ROOT
        func(path)

    shutil.rmtree(ROOT, onexc=clear_readonly_and_retry)


def main() -> int:
    ap = argparse.ArgumentParser(description="Create or remove the #1740 throwaway fixtures.")
    ap.add_argument("--teardown", action="store_true")
    ap.add_argument("--toolchain-copy", action="store_true",
                    help="phase 2: copy the toolchain under the fixture root")
    args = ap.parse_args()
    if args.toolchain_copy:
        print(json.dumps(toolchain_copy(), indent=1))
        return 0
    if args.teardown:
        teardown()
        print("removed" if not ROOT.exists() else "STILL PRESENT")
        return 0 if not ROOT.exists() else 1
    rec = create()
    print(json.dumps(rec["identities"], indent=1))
    print(f"{len(rec['folders'])} fixture folders under {ROOT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
