"""Read-only effective-access inventory for the #1740 containment setups.

For each setup (A dedicated account, B1 SAFER normal-user token, B2 write-restricted
tokens, B3 fully restricted token, C AppContainer, D the operator's limited token) and each real path, report what
Windows' own access check grants. Nothing is written to any path, no account is logged on,
no AppContainer profile is registered.

Instruments, and how each is checked before its numbers are used:

* The kernel instrument is the reference. ``limited_equivalent`` (the base for C; B2 and B3 are built by ``limited_restricted``)
  is compared with the real limited token on every path.
* AuthZ from a bare SID is the only instrument available for A. It applies no UAC
  filtering, so the operator's AuthZ context is compared with the operator's ELEVATED
  token, path by path. Any disagreement is reported; A is not comparable on that path.
* C uses an in-memory lowbox token. A real AppContainer launch can differ (profile folders,
  object namespace); C's rows are labelled PREDICTION until phase 2 re-checks them.

Run elevated (the real limited token is only reachable as the elevated token's linked
token):  python -I effective_access.py --out <dir>
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import platform
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import winsec as w

OPERATOR_HOME = Path(os.environ.get("USERPROFILE") or Path.home())

REAL_PATHS: list[tuple[str, str]] = [
    ("secret", str(OPERATOR_HOME / ".ssh")),
    ("secret", str(OPERATOR_HOME / ".git-credentials")),
    ("secret", str(OPERATOR_HOME / "AppData/Local/BlarAI")),
    ("secret", str(OPERATOR_HOME / ".config/opencode")),
    ("secret", str(OPERATOR_HOME / ".aws")),
    ("secret", str(OPERATOR_HOME / ".codex/.sandbox-secrets")),
    ("operator", str(OPERATOR_HOME)),
    ("operator", str(OPERATOR_HOME / "Documents")),
    ("operator", str(OPERATOR_HOME / "BlarAI")),
    ("known-leak", "B:/models"),
    ("known-leak", "C:/Windows/Temp"),
    ("known-leak", "C:/blarai-fleet"),
    ("known-leak", str(OPERATOR_HOME / "projects")),
    ("shared", "C:/blarai-fleet/worktrees"),
    ("shared", "C:/blarai-fleet/coder-leg"),
    ("shared", "C:/ProgramData"),
    ("shared", "C:/Users/Public"),
    ("shared", "C:/"),
    ("coder", "C:/Users/blarai-coder"),
    ("toolchain", "C:/Python314"),
    ("toolchain", "C:/Program Files/nodejs"),
    ("toolchain", "C:/Program Files/Git"),
    ("toolchain", str(OPERATOR_HOME / "AppData/Roaming/npm")),
    ("toolchain", "C:/Windows/System32"),
]

EVERYONE = "S-1-1-0"
USERS = "S-1-5-32-545"
LOCAL = "S-1-2-0"
AUTH_USERS = "S-1-5-11"
THIS_ORG = "S-1-5-15"
BATCH = "S-1-5-3"
RESTRICTED = "S-1-5-12"
APP_PACKAGES = "S-1-15-2-1"


def synthetic_sid(label: str) -> str:
    """A stable, otherwise unused SID for a write-restricted sandbox to be granted by name.

    Capability SIDs (S-1-15-3-...) are refused as restricting SIDs by
    CreateRestrictedToken (measured: ERROR_INVALID_PARAMETER), so the S-1-5-80 form
    service SIDs use is taken, with sub-authorities from a hash of the label.
    """
    h = hashlib.sha1(label.upper().encode("utf-16-le")).digest()
    subs = [int.from_bytes(h[i:i + 4], "little") for i in range(0, 20, 4)]
    return "S-1-5-80-" + "-".join(str(s) for s in subs)


def restricting_lists(write_sid: str, logon: str) -> tuple[list[str], list[str]]:
    """The two restricting lists the restricted-token setups use.

    B2 is OpenAI Codex's published list (Everyone, the logon SID, a synthetic SID): without the logon SID a
    restricted process cannot initialise its desktop objects and dies at start (0xC0000142). B3 is a broad,
    Chromium-style list that keeps ordinary system reads working while still failing any resource granted
    only to the operator's own account.
    """
    return ([write_sid, EVERYONE, logon],
            [write_sid, EVERYONE, USERS, AUTH_USERS, logon, RESTRICTED])


def build_setups() -> tuple[dict[str, object], dict[str, object]]:
    """Return (kernel-token setups, authz setups) plus a description of each."""
    elevated = w.process_token()
    if w.elevation_type(elevated) != 2:
        raise SystemExit("run elevated: the operator's real limited token is reached as "
                         "the elevated token's linked token")
    limited_real = w.to_impersonation(w.linked_token(elevated))
    le = w.limited_equivalent(elevated)
    write_sid = synthetic_sid("blarai-1740-write")
    b2_list, b3_list = restricting_lists(write_sid, w.logon_sid(elevated))
    package = w.derive_appcontainer_sid("blarai.1740.coder")
    kernel = {
        "V_elevated_full": w.to_impersonation(elevated),
        "D_real_limited": limited_real,
        "D_limited_equivalent": w.to_impersonation(le),
        "B1_safer_normaluser": w.to_impersonation(w.safer_normal_user_token(elevated)),
        "B2_write_restricted": w.to_impersonation(w.limited_restricted(
            elevated, flags=w.WRITE_RESTRICTED, restricting=b2_list)),
        # B3: a broad restricting list, applied to reads as well (no WRITE_RESTRICTED).
        "B3_fully_restricted": w.to_impersonation(w.limited_restricted(
            elevated, flags=0, restricting=b3_list)),
        "C_appcontainer_PREDICTION": w.to_impersonation(w.lowbox_token(le, package, [])),
    }
    operator_sid = w.describe_token(limited_real)["user"]
    real_groups = w.describe_token(limited_real)["groups_enabled"]
    logon_ids = [g for g in real_groups if g.startswith("S-1-5-5-")]
    coder_sid = w.sid_of_account("blarai-coder")
    authz = {
        "D_authz_from_sid": (str(operator_sid), [g for g in real_groups if g not in logon_ids]),
        "A_dedicated_account": (coder_sid, [EVERYONE, LOCAL, AUTH_USERS, THIS_ORG, BATCH]),
    }
    meta = {
        "write_restricting_sid": write_sid,
        "appcontainer_package_sid": package,
        "operator_sid": operator_sid,
        "coder_sid": coder_sid,
        "tokens": {k: w.describe_token(v) for k, v in kernel.items()},
    }
    return {"kernel": kernel, "authz": authz}, meta


def run(out_dir: Path, paths: list[tuple[str, str]], tag: str) -> dict[str, object]:
    w.enable_privilege("SeBackupPrivilege")
    setups, meta = build_setups()
    contexts = {}
    for name, (sid, extra) in setups["authz"].items():
        ctx = w.AuthzContext(sid, extra)
        contexts[name] = ctx
        meta.setdefault("authz_groups", {})[name] = {
            "computed": ctx.computed_groups, "added": ctx.added_groups}
    rows = []
    for kind, path in paths:
        row: dict[str, object] = {"kind": kind, "path": path}
        if not os.path.lexists(path):
            row["status"] = "absent"
            rows.append(row)
            continue
        try:
            desc = w.read_descriptor(path)
        except OSError as exc:
            row["status"] = f"unreadable: {exc}"
            rows.append(row)
            continue
        is_dir = os.path.isdir(path)
        row.update(status="ok", is_dir=is_dir, sddl=desc.sddl, access={})
        for name, tok in setups["kernel"].items():
            mask = w.kernel_access(desc, tok)
            row["access"][name] = {"mask": f"0x{mask:08x}", **w.summarize(mask, is_dir)}
        for name, ctx in contexts.items():
            mask = ctx.access(desc)
            row["access"][name] = {"mask": f"0x{mask:08x}", **w.summarize(mask, is_dir)}
        acc = row["access"]
        row["instrument_agreement"] = {
            "limited_equivalent_vs_real": acc["D_limited_equivalent"]["mask"]
            == acc["D_real_limited"]["mask"],
            # AuthZ from a bare SID applies no UAC filtering, so the operator's AuthZ
            # context holds Administrators enabled: it is compared with the ELEVATED token.
            "authz_vs_elevated": acc["D_authz_from_sid"]["mask"]
            == acc["V_elevated_full"]["mask"],
        }
        rows.append(row)
    for ctx in contexts.values():
        ctx.close()
    result = {
        "instrument": "tools/probes/containment_arms/effective_access.py",
        "ticket": "#1740",
        "measured_at": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
        "host": platform.node(),
        "os": platform.platform(),
        "python": sys.version.split()[0],
        "meta": meta,
        "rows": rows,
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.now().astimezone().strftime("%Y%m%dT%H%M%S")
    (out_dir / f"effective-access-{tag}-{stamp}.json").write_text(json.dumps(result, indent=1),
                                                            encoding="utf-8")
    return result


def render(result: dict[str, object]) -> str:
    cols = ["D_real_limited", "A_dedicated_account", "B1_safer_normaluser",
            "B2_write_restricted", "B3_fully_restricted",
            "C_appcontainer_PREDICTION"]
    cols = [c for c in cols if all(c in r.get("access", {}) for r in result["rows"]
                                   if r.get("status") == "ok")]
    short = {"D_real_limited": "D", "A_dedicated_account": "A", "B1_safer_normaluser": "B1",
             "B2_write_restricted": "B2",
             "B3_fully_restricted": "B3",
             "C_appcontainer_PREDICTION": "C*"}
    lines = ["| path | " + " | ".join(short[c] for c in cols) + " | instr. agree |",
             "|---|" + "---|" * (len(cols) + 1)]
    for row in result["rows"]:
        if row["status"] != "ok":
            lines.append(f"| `{row['path']}` | {row['status']} |" + " |" * len(cols))
            continue
        cells = []
        for c in cols:
            a = row["access"][c]
            cells.append(("R" if a["read"] else "-") + ("W" if a["write"] else "-")
                         + ("D" if a["delete"] else "-") + ("P" if a["change_permissions"] else "-"))
        ag = row["instrument_agreement"]
        agree = ("ok" if ag["limited_equivalent_vs_real"] and ag["authz_vs_elevated"]
                 else f"LE:{ag['limited_equivalent_vs_real']} AZ:{ag['authz_vs_elevated']}")
        lines.append(f"| `{row['path']}` | " + " | ".join(cells) + f" | {agree} |")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--fixtures", action="store_true",
                    help="check the throwaway fixture folders instead of the real paths")
    args = ap.parse_args()
    if args.fixtures:
        rec = json.loads(Path("C:/blarai-spike-1740/fixtures.json").read_text(encoding="utf-8"))
        paths = [("fixture", f) for f in rec["folders"]]
        result = run(args.out, paths, "fixtures")
    else:
        result = run(args.out, REAL_PATHS, "real")
    print(render(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
