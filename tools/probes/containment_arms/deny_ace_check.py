"""Does a deny ACE naming an AppContainer's package SID deny it? (#1740)

In-memory only: security descriptors are built from SDDL and evaluated with AccessCheck
against an in-memory lowbox token. No file, profile or ACL is created or changed.

Each case states which ACEs the descriptor holds; the operator's own user SID always holds
an allow so the first (normal) pass of the AppContainer check can pass. The user-SID deny
case is the control showing that a deny ACE is honoured in the first pass.

Usage (elevated):  python -I deny_ace_check.py [--out file.json]
"""

from __future__ import annotations

import argparse
import ctypes
import ctypes.wintypes as wt
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import winsec as w

MODIFY = "0x1301bf"
SYS = "(A;;FA;;;SY)(A;;FA;;;BA)"


def sd_from_sddl(sddl: str) -> w.Descriptor:
    sd = ctypes.c_void_p()
    w._check(w.advapi32.ConvertStringSecurityDescriptorToSecurityDescriptorW(
        wt.LPCWSTR("O:BAG:BA" + sddl), 1, ctypes.byref(sd), None), "ConvertStringSecurityDescriptor")
    return w.Descriptor("<memory>", sd, sddl)


def check(desc: w.Descriptor, tok: w.HANDLE, want: int) -> bool:
    ps = ctypes.create_string_buffer(256)
    pl = wt.DWORD(256)
    g = wt.DWORD()
    st = wt.BOOL()
    w._check(w.advapi32.AccessCheck(desc.sd, tok, want, ctypes.byref(w.FILE_MAPPING), ps,
                                    ctypes.byref(pl), ctypes.byref(g), ctypes.byref(st)),
             "AccessCheck")
    return bool(st.value)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", type=Path)
    args = ap.parse_args()
    elevated = w.process_token()
    le = w.limited_equivalent(elevated)
    op = w.describe_token(le)["user"]
    pkg = w.derive_appcontainer_sid("blarai.1740.coder")
    cap = w.derive_capability_sid("blarai1740Probe")
    lowbox = w.to_impersonation(w.lowbox_token(le, pkg, []))
    lowbox_cap = w.to_impersonation(w.lowbox_token(le, pkg, [cap]))
    limited = w.to_impersonation(le)
    base = f"(A;;{MODIFY};;;{op})"
    cases = {
        "grant package (control: allowed)": f"D:P{SYS}{base}(A;;{MODIFY};;;{pkg})",
        "no package ACE (control: denied)": f"D:P{SYS}{base}",
        "deny package 0x116 + grant package": f"D:P(D;;0x116;;;{pkg}){SYS}{base}(A;;{MODIFY};;;{pkg})",
        "deny package 0x2 + grant package": f"D:P(D;;0x2;;;{pkg}){SYS}{base}(A;;{MODIFY};;;{pkg})",
        "deny ALL APPLICATION PACKAGES 0x2 + grant package": f"D:P(D;;0x2;;;AC){SYS}{base}(A;;{MODIFY};;;{pkg})",
        "deny user 0x2 + grant package (first-pass control)": f"D:P(D;;0x2;;;{op}){SYS}{base}(A;;{MODIFY};;;{pkg})",
        "grant capability (cap token)": f"D:P{SYS}{base}(A;;{MODIFY};;;{cap})",
        "deny capability 0x2 + grant package (cap token)": f"D:P(D;;0x2;;;{cap}){SYS}{base}(A;;{MODIFY};;;{pkg})",
    }
    results = []
    for name, sddl in cases.items():
        tok = lowbox_cap if "cap token" in name else lowbox
        d = sd_from_sddl(sddl)
        results.append({
            "case": name,
            "appcontainer_write_data": check(d, tok, w.FILE_WRITE_DATA),
            "limited_token_write_data": check(d, limited, w.FILE_WRITE_DATA),
            "sddl": sddl.replace(op, "<operator>").replace(pkg, "<package>").replace(cap, "<capability>"),
        })
    for r in results:
        print(f"{r['case']:<55} appcontainer={r['appcontainer_write_data']!s:<5} "
              f"limited={r['limited_token_write_data']}")
    if args.out:
        args.out.write_text(json.dumps({"instrument": "AccessCheck, in-memory lowbox token",
                                        "results": results}, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
