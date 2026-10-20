"""Self-test for the MXC denied-subtree probe. Non-elevated, needs no MXC launcher and starts no container.

WHAT IT CHECKS
  * the launching token: guarded privileges (backup, restore, take-ownership, security) are disabled and read
    back, the old structure layout is shown to leave them enabled, and a failed disable is refused;
  * summarise.verdict returns HOLD, FAIL (each landing, and a change in T/sub no landing predicate names),
    REFUSED (validation text only), LAUNCH-FAILED, INSTRUMENT-BLIND (several causes, including tier mismatch,
    changed MXC state, a DENY ACE or ACL change left behind), INCOMPLETE, and the precedence rules;
  * T/sub is judged by whole-subtree equality: an extra file, a file moved in, changed bytes in an unnamed
    file, an alternate data stream, a nested directory and a vanished sub are each caught, and the old
    "no named predicate fired" rule is shown to miss the ones it cannot see;
  * landing attribution on a scratch tree, with a toggle showing the host comparison is load-bearing;
  * every one of the five S2 attempts, the S1 writes and the S3 read and listing record a real Win32 error
    code (non-None winerror) against a refusing tree, a missing target and an existing target;
  * the path guards, and run_probe refusing an output root inside a git tree before writing anything;
  * launch.ps1 on a scratch copy, driven with pwsh: missing file, missing line, mismatch, tampered script,
    unlisted script, missing interpreter;
  * end to end: the real run_probe.main driven against a fake launcher (a .cmd that answers --probe and
    --dry-run and runs the policy's command line) to FAIL (open tree), HOLD (tree made read-only to the payload
    by an ACL), LAUNCH-FAILED (no report), REFUSED (validation rejects), a dry-run tier mismatch stop and an
    S0 tier stop; the fake launcher never starts a container;
  * a landed entry the host cannot read (held without read sharing at the after-snapshot), a vanished one, a
    new directory that cannot be listed and a failed listing elsewhere, each judged from listings and kinds,
    with and without the container's report, and the earlier rule shown to miss them;
  * fx-c (leastPrivilege, AppContainer DACL tier): verdicts, the policy shape, the system-drive grant detector, and
    end to end against the fake launcher: refusal without --allow-dacl-tier, HOLD with a DENY ACE seen during and gone
    after, no DENY ACE during, ACE left behind, toolchain ACL not restored, host prep required, tier mismatch;
  * the directory carries no hash-and-digits reference, no numbered fixture name, no account name.

Usage: python -I self_test.py     (prints PASS/FAIL per check; exit 1 if any FAIL)
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import ctypes  # noqa: E402
import hashlib  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
import re  # noqa: E402
import shutil  # noqa: E402
import subprocess  # noqa: E402
import tempfile  # noqa: E402
import time  # noqa: E402

import fixtures as F  # noqa: E402
import landing as L  # noqa: E402
import payload as P  # noqa: E402
import summarise as S  # noqa: E402

PWSH = F.PWSH
SELF_ROOT = Path(f"C:/mxc-fx-selftest-{os.getpid()}")  # the end-to-end runs never share a tree root with a live run
USER = os.environ.get("USERNAME", "")
results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, bool(ok), detail))
    print(f"{'PASS' if ok else 'FAIL'}: {name}" + (f"  [{detail}]" if detail and not ok else ""))


def icacls(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["icacls", *args], capture_output=True, text=True)


def lock(path: Path) -> None:
    """Make path and everything under it read-and-execute only for this account (absence of a write allow)."""
    icacls(str(path), "/inheritance:r", "/grant:r", f"{USER}:(OI)(CI)(RX)", "/Q")


def unlock(path: Path) -> None:
    icacls(str(path), "/reset", "/T", "/Q")


# ------------------------------------------------------------------ synthetic records

def judge_d(landed: tuple[str, ...] = (), changes: tuple[str, ...] = (), executed: bool = True,
            disagree: tuple[str, ...] = (), read_errors: tuple[str, ...] = (), layout: bool = True) -> dict[str, object]:
    return {"read_errors": [{"path": e} for e in read_errors], "layout_ok": layout, "attempts_executed": executed, "landed": {n: n in landed for n in P.ATTEMPTS}, "landed_count": len(landed),
            "disagreements": list(disagree), "sub_changes": list(changes), "sub_unchanged": not changes,
            "unattributed_changes": [], "reported_success": {n: n in landed for n in P.ATTEMPTS}}


def run_rec(i: int, fixture: str = "fx-a", landed: tuple[str, ...] = (), changes: tuple[str, ...] = (), s1: bool = True,
            executed: bool = True, disagree: tuple[str, ...] = (), tier: str = "base-container", state: dict | None = None,
            ace_left: bool = False, tc_ok: bool = True, read_errors: tuple[str, ...] = (), layout: bool = True,
            codes: int = 5, acl_ok: bool = True, privs: tuple[str, ...] = (), t_ok: bool = True,
            py_ok: bool = True) -> dict[str, object]:
    return {"state": "S2", "fixture": fixture, "tag": f"{fixture}-r{i}", "dry_run_rc": 0, "launched": True,
            "payload_present": True, "dry_run_selected_tier": tier, "state_changed_by_run": state or {},
            "deny_ace_cleanup": {"deny_aces_after": 1 if ace_left else 0, "sddl_after_equals_before": not ace_left},
            "toolchain_acl_unchanged": tc_ok, "t_acl_unchanged": t_ok, "python_acl_unchanged": py_ok, "acl_parse_ok": acl_ok, "privileges_enabled": list(privs),
            "s1_host": {"create_file": s1, "append_marker": s1},
            "payload": {"s1": {"create_file": {"winerror": None}}, "s2": {n: {"ok": False, "winerror": codes} for n in P.ATTEMPTS},
                        "s3": {"read_marker": {"ok": True, "winerror": None}}},
            "judge": judge_d(landed, changes, executed, disagree, read_errors, layout)}


def s4_rec(ok: bool = True) -> dict[str, object]:
    return {"state": "S4", "tag": "s4-r1", "landed": {n: ok for n in P.ATTEMPTS}, "all_landed": ok}


def smoke_rec(ok: bool = True, ace_left: bool = False, tc_ok: bool = True, state: dict | None = None) -> dict[str, object]:
    return {"state": "SMOKE", "tag": "smoke-r1", "dry_run_rc": 0, "launched": True, "ok": ok, "report": {"ok": ok},
            "dry_run_selected_tier": "base-container", "privileges_enabled": [], "state_changed_by_run": state or {},
            "deny_ace_cleanup": {"deny_aces_after": 1 if ace_left else 0, "sddl_after_equals_before": not ace_left},
            "t_acl_unchanged": True, "toolchain_acl_unchanged": tc_ok, "python_acl_unchanged": True}


def batch_rec(unchanged: bool | None = True) -> dict[str, object]:
    return {"state": "BATCH", "tag": "batch", "toolchain_tree_unchanged": unchanged,
            "toolchain_tree_differences": [] if unchanged else ["x: DACL differs"]}


def V(records: list[dict[str, object]], tier: str | None = None, smoke: bool = True) -> dict[str, object]:
    return S.verdict(records + ([smoke_rec()] if smoke else []), tier)


def test_verdicts() -> None:
    good = [run_rec(i) for i in (1, 2, 3)] + [s4_rec()]
    v = V(good, "base-container")
    check("verdict HOLD", v["verdict"] == "HOLD")
    check("summary carries tier, S3 and per-attempt error codes",
          v["dry_run_tiers"] == ["base-container"] and v["s0_tier"] == "base-container"
          and v["s2_win32"]["fx-a-r1"]["create_file"] == 5 and "read_marker" in v["s3"]["fx-a-r1"])
    for n in P.ATTEMPTS:
        vv = V([run_rec(1), run_rec(2, landed=(n,)), run_rec(3), s4_rec()])
        check(f"verdict FAIL on landing {n}", vv["verdict"] == "FAIL" and vv["changes"][0][0] == "fx-a-r2")
    ch = V([run_rec(1), run_rec(2, changes=("sub/other.txt",)), run_rec(3), s4_rec()])
    check("verdict FAIL on a change in T/sub no named attempt explains", ch["verdict"] == "FAIL")
    rej = {"state": "S2", "fixture": "fx-a", "tag": "fx-a-r1", "dry_run_rc": 1, "launched": False,
           "payload_present": False, "judge": None}
    check("verdict REFUSED only on a rejected validation", V([rej, s4_rec()])["verdict"] == "REFUSED")
    nopay = dict(rej, dry_run_rc=0, launched=True)
    check("verdict LAUNCH-FAILED when validation passed and no report came back, never REFUSED",
          V([nopay, s4_rec()])["verdict"] == "LAUNCH-FAILED")
    base = [run_rec(2), run_rec(3), s4_rec()]
    for name, bad in (("S1 did not land", run_rec(1, s1=False)), ("attempts not executed", run_rec(1, executed=False)),
                      ("report and tree disagree", run_rec(1, disagree=("create_file",))),
                      ("MXC state changed", run_rec(1, state={"mxc_state_dir": [[], [1]]})),
                      ("DENY ACE left on T/sub", run_rec(1, ace_left=True)),
                      ("toolchain ACL changed", run_rec(1, tc_ok=False)),
                      ("per-launch tier is not base-container", run_rec(1, tier="appcontainer-dacl"))):
        check(f"verdict INSTRUMENT-BLIND ({name})", V([bad, *base], "base-container")["verdict"] == "INSTRUMENT-BLIND")
    for name, bad in (("unreadable entry", run_rec(1, read_errors=("sub/marker.txt",))),
                      ("before-snapshot layout missing", run_rec(1, layout=False)),
                      ("refusal code 32 instead of 5", run_rec(1, codes=32)),
                      ("ACL not fully parsed", run_rec(1, acl_ok=False)),
                      ("guarded privilege enabled", run_rec(1, privs=("SeRestorePrivilege",)))):
        vv = V([bad, *base], "base-container")
        check(f"verdict INSTRUMENT-BLIND ({name})", vv["verdict"] == "INSTRUMENT-BLIND", str(vv["blind_reasons"]))
    check("an unreadable entry is not a change by itself", V([run_rec(1, read_errors=("sub/marker.txt",)), *base])["changes"] == [])
    nr = run_rec(1, changes=("sub/s2_new.txt",), landed=("create_file",))
    nr["payload_present"], nr["payload"] = False, None
    vv = V([nr, s4_rec()])
    check("verdict FAIL (not LAUNCH-FAILED) when T/sub changed and no report came back",
          vv["verdict"] == "FAIL" and vv["changes"][0][3] == "no report", str(vv["verdict"]))
    tm = {"state": "S2", "fixture": "fx-a", "tag": "fx-a-r1", "dry_run_rc": 0, "launched": False, "payload_present": False,
          "judge": None, "dry_run_selected_tier": "appcontainer-dacl",
          "tier_mismatch": {"tag": "fx-a-r1", "dry_run_tier": "appcontainer-dacl", "s0_tier": "base-container", "reason": "x"}}
    vv = V([tm, s4_rec()], "base-container")
    check("verdict TIER-MISMATCH names the reason", vv["verdict"] == "TIER-MISMATCH" and vv["tier_mismatch"][0]["s0_tier"] == "base-container")
    check("verdict INSTRUMENT-BLIND (tier differs from S0)",
          V(good, "other-tier")["verdict"] == "INSTRUMENT-BLIND")
    check("verdict INSTRUMENT-BLIND (S4 landed 4 of 5)",
          V([run_rec(1), run_rec(2), run_rec(3), s4_rec(False)])["verdict"] == "INSTRUMENT-BLIND")
    check("verdict INSTRUMENT-BLIND (S4 absent)", V([run_rec(1), run_rec(2), run_rec(3)])["verdict"] == "INSTRUMENT-BLIND")
    check("verdict INSTRUMENT-BLIND (smoke launch absent)", V(good, smoke=False)["verdict"] == "INSTRUMENT-BLIND")
    vv = S.verdict([smoke_rec(False), s4_rec()])
    check("verdict CONTAINER-PAYLOAD-BROKEN when the smoke launch did not complete, before any S2 run",
          vv["verdict"] == "CONTAINER-PAYLOAD-BROKEN" and vv["fx_a_launches"] == 0, str(vv["verdict"]))
    sc = dict(smoke_rec(), cause="payload-import-failure", ok=False)
    check("the smoke record's cause reaches summary.json", S.verdict([sc, s4_rec()])["smoke"][0]["cause"] == "payload-import-failure")
    ss = dict(smoke_rec(), state_changed_by_run={"mxc_state_dir": [[], [1]]})
    vv = S.verdict([ss, s4_rec()], "base-container")
    check("a smoke launch that changed MXC state is STOPPED-STATE-CHANGE with the change named",
          vv["verdict"] == "STOPPED-STATE-CHANGE" and vv["smoke_state_changed"][0]["changes"] == {"mxc_state_dir": [[], [1]]}, str(vv["verdict"]))
    clean_nr = run_rec(1, landed=(), changes=())
    clean_nr["payload_present"], clean_nr["payload"] = False, None
    check("a launch with no report, clean host reads and nothing changed is LAUNCH-FAILED",
          V([clean_nr, s4_rec()], "base-container")["verdict"] == "LAUNCH-FAILED")
    blind_nr = run_rec(1, read_errors=("sub/marker.txt",))
    blind_nr["payload_present"], blind_nr["payload"] = False, None
    vv = V([blind_nr, s4_rec()], "base-container")
    check("a launch with no report and a host read error is INSTRUMENT-BLIND with the reason, never LAUNCH-FAILED",
          vv["verdict"] == "INSTRUMENT-BLIND" and any("no container report and unreadable" in r for r in vv["blind_reasons"]), str(vv))
    smt = dict(smoke_rec(False), launched=False, tier_mismatch={"tag": "smoke-r1", "dry_run_tier": "x", "s0_tier": "base-container", "reason": "r"})
    check("a smoke tier mismatch is TIER-MISMATCH", S.verdict([smt, s4_rec()])["verdict"] == "TIER-MISMATCH")
    skipped = {"state": "S2", "fixture": "fx-a", "tag": "fx-a-r1", "dry_run_rc": 0, "launched": False, "payload_present": False,
               "judge": None, "dry_run_selected_tier": "base-container", "privileges_enabled": ["SeRestorePrivilege"]}
    check("verdict INSTRUMENT-BLIND for a launch refused over an enabled privilege (record shape run_probe writes)",
          S.verdict([skipped, s4_rec(), smoke_rec()], "base-container")["verdict"] == "INSTRUMENT-BLIND")
    check("verdict INCOMPLETE (two launches)", V([run_rec(1), run_rec(2), s4_rec()])["verdict"] == "INCOMPLETE")
    check("verdict FAIL outranks a failed control",
          V([run_rec(1, landed=("mkdir",), s1=False), s4_rec(False)])["verdict"] == "FAIL")
    b = V(good + [run_rec(1, fixture="fx-b", changes=("sub/x",))])
    check("fx-b change is a FAIL and is reported as S5", b["verdict"] == "FAIL" and b["s5"][0]["outcome"] == "ran-with-change")
    rej_b = dict(rej, fixture="fx-b", tag="fx-b-r1")
    check("S5 rejection classified", V(good + [rej_b])["s5"][0]["outcome"] == "rejected-at-validation"
          and V(good + [rej_b])["verdict"] == "HOLD")


def fxc_rec(i: int, obs: bool = True, **kw: object) -> dict[str, object]:
    r = run_rec(i, fixture="fx-c", tier=F.TIER_3, **kw)  # type: ignore[arg-type]
    r["deny_ace_cleanup"]["deny_ace_observed_during"] = obs  # type: ignore[index]
    return r


def test_fxc_verdicts_and_policy() -> None:
    br = batch_rec()
    good = [fxc_rec(i) for i in (1, 2, 3)] + [s4_rec(), br]
    v = V(good, F.TIER_3)
    check("fx-c verdict HOLD on the AppContainer DACL tier", v["verdict"] == "HOLD" and v["variant"] == "fx-c"
          and v["dry_run_tiers"] == [F.TIER_3], str(v["blind_reasons"]))
    check("fx-c verdict FAIL on a landing", V([fxc_rec(1), fxc_rec(2, landed=("mkdir",)), fxc_rec(3), s4_rec(), br], F.TIER_3)["verdict"] == "FAIL")
    check("fx-c verdict INSTRUMENT-BLIND when no DENY ACE was observed during the run",
          V([fxc_rec(1, obs=False), fxc_rec(2), fxc_rec(3), s4_rec(), br], F.TIER_3)["verdict"] == "INSTRUMENT-BLIND")
    check("fx-c verdict INSTRUMENT-BLIND when the per-launch tier is base-container",
          V([dict(fxc_rec(i), dry_run_selected_tier=F.TIER_1) for i in (1, 2, 3)] + [s4_rec(), br], F.TIER_3)["verdict"] == "INSTRUMENT-BLIND")
    for name, bad in (("DENY ACE left on T/sub", fxc_rec(1, ace_left=True)), ("toolchain ACL not restored", fxc_rec(1, tc_ok=False)),
                      ("T ACL changed", fxc_rec(1, t_ok=False)), ("container interpreter ACL changed", fxc_rec(1, py_ok=False)),
                      ("MXC state changed", fxc_rec(1, state={"mxc_state_dir": [[], [1]]}))):
        vv = V([bad, fxc_rec(2), fxc_rec(3), s4_rec(), br], F.TIER_3)
        check(f"fx-c verdict STOPPED-STATE-CHANGE ({name})", vv["verdict"] == "STOPPED-STATE-CHANGE" and bool(vv["state_left"]), str(vv["verdict"]))

    def no_report(r: dict[str, object]) -> dict[str, object]:
        return dict(r, payload_present=False, payload=None)

    vv = V([no_report(fxc_rec(1, ace_left=True, tc_ok=False)), s4_rec(), br], F.TIER_3)
    check("fx-c failed launch (no report) that left an ACE and a changed toolchain is STOPPED-STATE-CHANGE with both named",
          vv["verdict"] == "STOPPED-STATE-CHANGE" and any("DENY ACE" in h for h in vv["state_left"])
          and any("toolchain ACL" in h for h in vv["state_left"]), str(vv["verdict"]) + str(vv["state_left"]))
    check("toggle: the same failed launch with nothing left behind is LAUNCH-FAILED",
          V([no_report(fxc_rec(1)), s4_rec(), br], F.TIER_3)["verdict"] == "LAUNCH-FAILED")
    check("fx-c failed launch that left only a changed T ACL is STOPPED-STATE-CHANGE",
          V([no_report(fxc_rec(1, t_ok=False)), s4_rec(), br], F.TIER_3)["verdict"] == "STOPPED-STATE-CHANGE")
    check("fx-c a landing outranks state left behind on a failed launch",
          V([dict(no_report(fxc_rec(1, ace_left=True)), judge=judge_d(landed=("mkdir",))), s4_rec(), br], F.TIER_3)["verdict"] == "FAIL")
    for name, sm in (("an ACE left on the smoke tree", smoke_rec(ace_left=True)), ("a toolchain ACL changed by the smoke launch", smoke_rec(tc_ok=False)),
                     ("a failed smoke launch that also left an ACE", smoke_rec(False, ace_left=True))):
        vv = S.verdict([fxc_rec(1), s4_rec(), br, dict(sm, dry_run_selected_tier=F.TIER_3)], F.TIER_3)
        check(f"fx-c smoke launch: {name} is STOPPED-STATE-CHANGE", vv["verdict"] == "STOPPED-STATE-CHANGE", str(vv["verdict"]))
    check("toggle: a clean smoke launch with the same records is not STOPPED-STATE-CHANGE",
          S.verdict([fxc_rec(1), s4_rec(), br, dict(smoke_rec(), dry_run_selected_tier=F.TIER_3)], F.TIER_3)["verdict"] == "INCOMPLETE")
    check("fx-c a failed smoke launch with nothing left behind stays CONTAINER-PAYLOAD-BROKEN",
          S.verdict([s4_rec(), br, dict(smoke_rec(False), dry_run_selected_tier=F.TIER_3)], F.TIER_3)["verdict"] == "CONTAINER-PAYLOAD-BROKEN")
    vv = V([fxc_rec(i) for i in (1, 2, 3)] + [s4_rec(), batch_rec(False)], F.TIER_3)
    check("fx-c batch-level toolchain tree difference is STOPPED-STATE-CHANGE",
          vv["verdict"] == "STOPPED-STATE-CHANGE" and any(h.startswith("batch:") for h in vv["state_left"]), str(vv["verdict"]))
    check("fx-c batch-level comparison absent or unusable is INSTRUMENT-BLIND",
          V([fxc_rec(i) for i in (1, 2, 3)] + [s4_rec()], F.TIER_3)["verdict"] == "INSTRUMENT-BLIND"
          and V([fxc_rec(i) for i in (1, 2, 3)] + [s4_rec(), batch_rec(None)], F.TIER_3)["verdict"] == "INSTRUMENT-BLIND")
    hp = dict(smoke_rec(False), launched=False, dry_run_selected_tier=F.TIER_3, host_prep_required=["prepare-null-device"])
    vv = S.verdict([hp, s4_rec()], F.TIER_3)
    check("host-prep-required smoke record is HOST-PREP-REQUIRED and names the subcommand",
          vv["verdict"] == "HOST-PREP-REQUIRED" and vv["host_prep_required"] == ["prepare-null-device"], str(vv["verdict"]))
    base_acl = "O:BAG:SYD:(A;OICI;FA;;;BA)(A;;FRFX;;;WD)"
    both = "(A;;0x120088;;;AC)(A;;0x120088;;;S-1-15-2-2)"
    h = F.sddl_has_host_prep
    check("host-prep detector: exactly the two prepared entries count, appended or prepended, either SID spelling",
          h(base_acl + both) and h("O:BAG:SYD:" + both + "(A;OICI;FA;;;BA)") and h(base_acl + "(A;;0x120088;;;S-1-15-2-1)(A;;0x120088;;;S-1-15-2-2)"))
    for name, acl in (("no AppContainer entry", base_acl), ("AC alone", base_acl + "(A;;0x120088;;;AC)"),
                      ("restricted SID alone", base_acl + "(A;;0x120088;;;S-1-15-2-2)"),
                      ("wrong mask", base_acl + "(A;;0x1;;;AC)(A;;0x1;;;S-1-15-2-2)"),
                      ("one wrong mask", base_acl + "(A;;0x120088;;;AC)(A;;0x1200a9;;;S-1-15-2-2)"),
                      ("inherited entries", base_acl + "(A;ID;0x120088;;;AC)(A;ID;0x120088;;;S-1-15-2-2)"),
                      ("inheriting entries", base_acl + "(A;OICI;0x120088;;;AC)(A;OICI;0x120088;;;S-1-15-2-2)"),
                      ("deny entries", base_acl + "(D;;0x120088;;;AC)(D;;0x120088;;;S-1-15-2-2)"),
                      ("object entries", base_acl + "(OA;;0x120088;;;AC)(OA;;0x120088;;;S-1-15-2-2)"),
                      ("a different SID", base_acl + "(A;;0x120088;;;WD)(A;;0x120088;;;BA)")):
        check(f"host-prep detector rejects {name}", not h(acl))
    hs = F.host_prep_status("warning: x\nRun `wxc-host-prep prepare-null-device` (elevated)\nselected isolation tier: appcontainer-dacl")
    check("an unverifiable host-prep subcommand counts as not in effect; none named means none required",
          hs == [{"subcommand": "prepare-null-device", "in_effect": False, "checked_by": "not verifiable without elevation"}]
          and F.host_prep_status("selected isolation tier: base-container") == [])
    cfg = F.policy("fx-c", "mxcfx-x", Path("C:/t"), Path("C:/p"), Path("C:/tc"), Path("C:/py.exe"), Path("C:/r.json"))
    base = F.policy("fx-a", "mxcfx-x", Path("C:/t"), Path("C:/p"), Path("C:/tc"), Path("C:/py.exe"), Path("C:/r.json"))
    same = {k: v for k, v in cfg.items() if k != "processContainer"} == {k: v for k, v in base.items() if k != "processContainer"}
    check("fx-c policy is fx-a with leastPrivilege true and no captureDenials; fx-a is unchanged",
          cfg["processContainer"] == {"leastPrivilege": True} and base["processContainer"] == {"captureDenials": {"mode": "block"}} and same)


# ------------------------------------------------------------------ subtree equality and attribution

def perform(sub: Path, which: str) -> None:
    def append() -> None:
        with (sub / P.MARKER).open("ab") as f:
            f.write(b"y")

    {"create_file": lambda: (sub / P.NEW_FILE).write_bytes(b"x"),
     "open_write_append": append,
     "rename": lambda: os.rename(sub / P.RENAME_SRC, sub / P.RENAME_DST),
     "delete": lambda: os.remove(sub / P.DELETE_ME),
     "mkdir": lambda: os.mkdir(sub / P.NEW_DIR)}[which]()


def _winapi_open_exclusive(path: Path) -> int:
    import _winapi  # noqa: PLC0415

    return _winapi.CreateFile(str(path), 0x80000000, 0, 0, 3, 0x80, 0)


def _winapi_close(h: int) -> None:
    import _winapi  # noqa: PLC0415

    _winapi.CloseHandle(h)


def _winapi_hold_new(path: Path) -> int:
    """Create path and keep it open for write with no sharing: the entry exists in a listing but cannot be read."""
    import _winapi  # noqa: PLC0415

    return _winapi.CreateFile(str(path), 0x40000000, 0, 0, 2, 0x80, 0)


def test_unreadable_landings(scratch: Path, refused5: dict[str, object]) -> None:
    """Existence in a successful listing is evidence whatever the entry's bytes; a failed listing hides only what is below it."""
    reported_ok = {"s2": {n: {"ok": True, "winerror": None} for n in P.ATTEMPTS}}
    new_rel = f"{P.SUB}/{P.NEW_FILE}"
    pc = F.make_tree(scratch / "held-create", "c")
    bc = L.snapshot_tree(pc["T"])
    h = _winapi_hold_new(pc["sub"] / P.NEW_FILE)
    try:
        ac = L.snapshot_tree(pc["T"])
    finally:
        _winapi_close(h)
    check("held new file: the entry is listed and unreadable in the after-snapshot",
          new_rel in ac["entries"] and any(e["path"] == new_rel for e in ac["errors"]))
    for label, rep in (("no report", None), ("report says refused", refused5), ("report says created", reported_ok)):
        j = L.judge(rep, bc, ac, tag="c")
        check(f"held new file, {label}: create_file landed and sub_changes names it",
              j["landed"]["create_file"] and new_rel in j["sub_changes"], str(j["sub_changes"]))
        rec = run_rec(1, landed=(), changes=())
        rec["judge"] = j
        if rep is None:
            rec["payload_present"], rec["payload"] = False, None
        v = V([rec, run_rec(2), run_rec(3), s4_rec()], "base-container")
        check(f"held new file, {label}: verdict FAIL, never LAUNCH-FAILED or INSTRUMENT-BLIND", v["verdict"] == "FAIL", str(v["verdict"]))
    # toggle: the earlier rule (an unreadable entry is dropped from the evidence) misses the same landing
    dropped = {"entries": {k: v for k, v in ac["entries"].items() if not v.get("unreadable")}, "errors": ac["errors"]}
    jd = L.judge(None, bc, dropped, tag="c")
    check("toggle: with the unreadable entry dropped from the after-snapshot the landing is missed",
          jd["landed_count"] == 0 and jd["sub_changes"] == [], str(jd["sub_changes"]))
    # rename to a held destination
    pr = F.make_tree(scratch / "held-rename", "r")
    br = L.snapshot_tree(pr["T"])
    os.rename(pr["sub"] / P.RENAME_SRC, pr["sub"] / P.RENAME_DST)
    h = _winapi_open_exclusive(pr["sub"] / P.RENAME_DST)
    try:
        ar = L.snapshot_tree(pr["T"])
    finally:
        _winapi_close(h)
    jr = L.judge(None, br, ar, tag="r")
    check("held rename destination: rename landed", jr["landed"]["rename"] and jr["read_errors"] != [], str(jr["landed"]))
    # delete of an entry the host could not read in the before-snapshot
    pd = F.make_tree(scratch / "held-delete", "d")
    h = _winapi_open_exclusive(pd["sub"] / P.DELETE_ME)
    try:
        bd = L.snapshot_tree(pd["T"])
    finally:
        _winapi_close(h)
    os.remove(pd["sub"] / P.DELETE_ME)
    ad = L.snapshot_tree(pd["T"])
    jdl = L.judge(None, bd, ad, tag="d")
    check("delete of an entry unreadable in the before-snapshot: delete landed and named in sub_changes",
          jdl["landed"]["delete"] and f"{P.SUB}/{P.DELETE_ME}" in jdl["sub_changes"], str(jdl["sub_changes"]))
    # a new directory the host cannot list
    pm = F.make_tree(scratch / "held-mkdir", "m")
    bm = L.snapshot_tree(pm["T"])
    os.mkdir(pm["sub"] / P.NEW_DIR)
    am = L.snapshot_tree(pm["T"])
    am["errors"].append({"path": f"{P.SUB}/{P.NEW_DIR}", "op": "list", "error": "denied"})
    jm = L.judge(None, bm, am, tag="m")
    check("new directory that cannot be listed: mkdir landed", jm["landed"]["mkdir"] and f"{P.SUB}/{P.NEW_DIR}" in jm["sub_changes"], str(jm))
    # a failed listing hides only what is below it; a landing elsewhere still decides FAIL
    pn = F.make_tree(scratch / "nolist-elsewhere", "n")
    os.mkdir(pn["sub"] / "d")
    (pn["sub"] / "d" / "f").write_bytes(b"f")
    bn = L.snapshot_tree(pn["T"])
    (pn["sub"] / "other.txt").write_bytes(b"o")
    an = L.snapshot_tree(pn["T"])
    an["errors"].append({"path": f"{P.SUB}/d", "op": "list", "error": "denied"})
    an["entries"].pop(f"{P.SUB}/d/f")
    jn = L.judge(refused5, bn, an, tag="n")
    check("failed listing of a nested directory: its children are not changes, the landing elsewhere is",
          jn["sub_changes"] == [f"{P.SUB}/other.txt"] and jn["read_errors"] != [], str(jn["sub_changes"]))
    recn = run_rec(1)
    recn["judge"] = jn
    check("failed listing plus a landing elsewhere: verdict FAIL",
          V([recn, run_rec(2), run_rec(3), s4_rec()], "base-container")["verdict"] == "FAIL")
    an2 = {"entries": {k: v for k, v in bn["entries"].items() if k != f"{P.SUB}/d/f"},
           "errors": bn["errors"] + [{"path": f"{P.SUB}/d", "op": "list", "error": "denied"}]}
    jn2 = L.judge(refused5, bn, an2, tag="n")
    check("failed listing alone: no change, no landing, read error present", jn2["sub_changes"] == [] and jn2["landed_count"] == 0
          and jn2["read_errors"] != [], str(jn2["sub_changes"]))


def test_landing(scratch: Path) -> None:
    for n in P.ATTEMPTS:
        paths = F.make_tree(scratch / f"land-{n}", n)
        before = L.snapshot_tree(paths["T"])
        perform(paths["sub"], n)
        after = L.snapshot_tree(paths["T"])
        got = {k for k, v in L.landings(before, after).items() if v}
        check(f"attribution sees {n} and only {n}", got == {n}, str(got))
        check(f"sub_changes non-empty for {n}", bool(L.sub_changes(before, after)))
    paths = F.make_tree(scratch / "land-none", "none")
    before = L.snapshot_tree(paths["T"])
    after = L.snapshot_tree(paths["T"])
    check("untouched tree: nothing landed and sub_changes empty",
          not any(L.landings(before, after).values()) and not L.sub_changes(before, after))
    (paths["T"] / "outside.txt").write_bytes(b"z")
    check("a change outside T/sub is not a sub change", not L.sub_changes(before, L.snapshot_tree(paths["T"])))

    def case(name: str, mutate: object) -> None:
        pp = F.make_tree(scratch / f"eq-{name}", name)
        b0 = L.snapshot_tree(pp["T"])
        mutate(pp)  # type: ignore[operator]
        a0 = L.snapshot_tree(pp["T"])
        old_rule_misses = not any(L.landings(b0, a0).values())
        sc = L.sub_changes(b0, a0)
        check(f"whole-subtree equality catches {name}", bool(sc), str(sc))
        if name in ("extra file", "file moved in", "stream on marker", "nested directory", "read-only attribute set on the marker",
                    "last-write time changed on the marker"):
            check(f"toggle: the five-predicate rule alone misses {name}", old_rule_misses)

    case("extra file", lambda pp: (pp["sub"] / "other.txt").write_bytes(b"o"))

    def move_in(pp: dict[str, Path]) -> None:
        (pp["T"] / "moved.txt").write_bytes(b"m")
        os.rename(pp["T"] / "moved.txt", pp["sub"] / "moved.txt")

    case("file moved in", move_in)
    case("stream on marker", lambda pp: (pp["sub"] / (P.MARKER + ":extra")).write_bytes(b"ads"))
    pq = F.make_tree(scratch / "eq-unnamed", "u")
    (pq["sub"] / "u.txt").write_bytes(b"1")
    b1 = L.snapshot_tree(pq["T"])
    (pq["sub"] / "u.txt").write_bytes(b"2")
    check("same-size change in an unnamed file is caught by sha256", bool(L.sub_changes(b1, L.snapshot_tree(pq["T"]))))
    case("nested directory", lambda pp: (os.mkdir(pp["sub"] / "d"), (pp["sub"] / "d" / "f").write_bytes(b"f")))
    def chmod_ro(pp: dict[str, Path]) -> None:
        os.chmod(pp["sub"] / P.MARKER, 0o444)

    case("read-only attribute set on the marker", chmod_ro)
    case("last-write time changed on the marker", lambda pp: os.utime(pp["sub"] / P.MARKER, (1_000_000_000, 1_000_000_000)))
    case("sub renamed away", lambda pp: os.rename(pp["sub"], pp["T"] / "sub_gone"))
    case("stream on sub directory", lambda pp: (pp["T"] / "sub:dirstream").write_bytes(b"d"))
    # an exclusive handle makes an entry unreadable: recorded, never a change, layout/read errors block HOLD
    pu = F.make_tree(scratch / "unreadable", "u")
    h = _winapi_open_exclusive(pu["sub"] / P.MARKER)
    try:
        snap_u = L.snapshot_tree(pu["T"])
    finally:
        _winapi_close(h)
    snap_ok = L.snapshot_tree(pu["T"])
    check("exclusive handle: read error recorded on the entry", any(e["path"] == "sub/marker.txt" for e in snap_u["errors"]), str(snap_u["errors"]))
    check("exclusive handle: not counted as a change", L.sub_changes(snap_ok, snap_u) == [], str(L.sub_changes(snap_ok, snap_u)))
    check("exclusive handle: judge reports read errors and layout not ok",
          bool(L.judge(None, snap_u, snap_ok, tag="u")["read_errors"]) and L.judge(None, snap_u, snap_ok, tag="u")["layout_ok"] is False)
    refused5 = {"s2": {n: {"ok": False, "winerror": 5, "error": "denied"} for n in P.ATTEMPTS}}
    j_lock = L.judge(refused5, snap_ok, snap_u, tag="u")
    rec_lock = run_rec(1)
    rec_lock["judge"] = j_lock
    check("exclusive handle at the after-snapshot: judge reports no landing and no change, read error present",
          j_lock["landed_count"] == 0 and j_lock["sub_changes"] == [] and bool(j_lock["read_errors"]), str(j_lock))
    vv = V([rec_lock, run_rec(2), run_rec(3), s4_rec()], "base-container")
    check("exclusive handle at the after-snapshot: verdict is INSTRUMENT-BLIND, never FAIL",
          vv["verdict"] == "INSTRUMENT-BLIND" and vv["changes"] == [], str(vv["verdict"]))
    sub_ent = snap_ok["entries"]["sub"]
    after_nolist = {"entries": {"sub": sub_ent}, "errors": [{"path": "sub", "op": "list", "error": "denied"}]}
    j_nl = L.judge(refused5, snap_ok, after_nolist, tag="u")
    check("after-snapshot listing failure: no landing, no change, read error present",
          j_nl["landed_count"] == 0 and j_nl["sub_changes"] == [] and bool(j_nl["read_errors"]), str(j_nl))
    rec_nl = run_rec(1)
    rec_nl["judge"] = j_nl
    check("after-snapshot listing failure: verdict INSTRUMENT-BLIND, never FAIL",
          V([rec_nl, run_rec(2), run_rec(3), s4_rec()], "base-container")["verdict"] == "INSTRUMENT-BLIND")
    before_nolist = {"entries": {"sub": sub_ent}, "errors": [{"path": "sub", "op": "list", "error": "denied"}]}
    j_bl = L.judge(refused5, before_nolist, snap_ok, tag="u")
    check("before-snapshot listing failure: no landing, no change; layout not ok",
          j_bl["landed_count"] == 0 and j_bl["sub_changes"] == [] and j_bl["layout_ok"] is False, str(j_bl))
    pg = F.make_tree(scratch / "readable-landing", "r")
    b0 = L.snapshot_tree(pg["T"])
    (pg["sub"] / P.NEW_FILE).write_bytes(b"x")
    h2 = _winapi_open_exclusive(pg["sub"] / P.MARKER)
    try:
        a0 = L.snapshot_tree(pg["T"])
    finally:
        _winapi_close(h2)
    j_mix = L.judge(refused5, b0, a0, tag="r")
    check("a readable landing still counts while an unrelated entry is unreadable",
          j_mix["landed"]["create_file"] and j_mix["read_errors"] != [], str(j_mix["landed"]))
    test_unreadable_landings(scratch, refused5)
    check("layout_ok accepts the builder's tree", L.layout_ok(snap_ok, "u") is True)
    empty = {"entries": {"sub": {"kind": "dir"}}, "errors": []}
    check("layout_ok refuses a before-snapshot that cannot see the files (unlistable sub)", L.layout_ok(empty, "u") is False)
    # report denies, tree changed
    paths = F.make_tree(scratch / "land-lie", "lie")
    before = L.snapshot_tree(paths["T"])
    perform(paths["sub"], "create_file")
    after = L.snapshot_tree(paths["T"])
    refused = {"s2": {n: {"ok": False, "winerror": 5, "error": "denied"} for n in P.ATTEMPTS}}
    on, off = L.judge(refused, before, after, host_side=True), L.judge(refused, before, after, host_side=False)
    check("toggle: host-side judge catches a landing the report denies",
          on["landed_count"] == 1 and on["disagreements"] == ["create_file"] and not on["sub_unchanged"])
    check("toggle: report-only judge misses it (host comparison is load-bearing)",
          off["landed_count"] == 0 and off["sub_unchanged"])
    # the real payload, unconfined
    paths = F.make_tree(scratch / "land-payload", "payload")
    before = L.snapshot_tree(paths["T"])
    cp = subprocess.run([sys.executable, "-I", "-B", str(HERE / "payload.py"), "--t", str(paths["T"]), "--out",
                         str(paths["T"] / "_report.json"), "--mode", "control"], capture_output=True, text=True)
    after = L.snapshot_tree(paths["T"])
    j = L.judge(json.loads((paths["T"] / "_report.json").read_text(encoding="utf-8")), before, after)
    check("real payload unconfined: all five land, none disagree", cp.returncode == 0 and j["landed_count"] == 5
          and not j["disagreements"] and j["attempts_executed"], str(j) + cp.stderr[-1500:])
    check("real payload unconfined: S1 effects judged from host", all(L.s1_effects(before, after).values()))


# ------------------------------------------------------------------ Win32 error codes

def run_payload(t: Path, out: Path) -> dict[str, object]:
    subprocess.run([sys.executable, "-I", "-B", str(HERE / "payload.py"), "--t", str(t), "--out", str(out), "--mode", "control"],
                   capture_output=True, text=True)
    return json.loads(out.read_text(encoding="utf-8"))


def test_win32(scratch: Path) -> None:
    pp = F.make_tree(scratch / "w32-sub", "w")
    lock(pp["sub"])
    rep = run_payload(pp["T"], scratch / "w32-sub-report.json")
    unlock(pp["sub"])
    codes = {n: rep["s2"][n]["winerror"] for n in P.ATTEMPTS}  # type: ignore[index]
    check("S2 refusals: all five attempts carry Win32 error 5", all(v == 5 for v in codes.values()), str(codes))
    check("S3 read and listing succeed on a read-only sub", rep["s3"]["read_marker"]["ok"] and rep["s3"]["list_sub"]["ok"])  # type: ignore[index]
    pt = F.make_tree(scratch / "w32-t", "w")
    lock(pt["T"])
    rep = run_payload(pt["T"], scratch / "w32-t-report.json")
    unlock(pt["T"])
    check("S1 refusals: create and append carry Win32 error 5",
          all(rep["s1"][k]["winerror"] == 5 for k in ("create_file", "append_marker")), str(rep["s1"]))  # type: ignore[index]
    pm = F.make_tree(scratch / "w32-missing", "w")
    os.rename(pm["sub"], pm["T"] / "sub_x")
    rep = run_payload(pm["T"], scratch / "w32-missing-report.json")
    check("S3 failures carry a Win32 error (path not found)",
          rep["s3"]["read_marker"]["winerror"] == 3 and rep["s3"]["list_sub"]["winerror"] == 3, str(rep["s3"]))  # type: ignore[index]
    check("S2 failures on missing targets carry real Win32 errors",
          all(rep["s2"][n]["winerror"] is not None for n in P.ATTEMPTS), str({n: rep["s2"][n]["winerror"] for n in P.ATTEMPTS}))  # type: ignore[index]
    pe = F.make_tree(scratch / "w32-exists", "w")
    (pe["sub"] / P.NEW_FILE).write_bytes(b"x")
    os.mkdir(pe["sub"] / P.NEW_DIR)
    os.rename(pe["sub"] / P.RENAME_SRC, pe["sub"] / P.RENAME_DST)
    rep = run_payload(pe["T"], scratch / "w32-exists-report.json")
    check("create and mkdir on existing targets carry Win32 errors 80 and 183, rename 2",
          (rep["s2"]["create_file"]["winerror"], rep["s2"]["mkdir"]["winerror"], rep["s2"]["rename"]["winerror"]) == (80, 183, 2),  # type: ignore[index]
          str({n: rep["s2"][n]["winerror"] for n in P.ATTEMPTS}))  # type: ignore[index]


# ------------------------------------------------------------------ launching token

PRIV_CHILD = r"""
import ctypes, ctypes.wintypes as wt, json, sys
sys.dont_write_bytecode = True
sys.path.insert(0, sys.argv[1])
import fixtures as F
held = {p["name"] for p in F.token_privileges()}
out = {"held": sorted(held & set(F.GUARDED_PRIVILEGES))}
for n in ("SeBackupPrivilege", "SeRestorePrivilege"):
    if n in held:
        F.enable_privilege(n)
out["enabled_before"] = F.enabled_guarded()


class OldLayout(ctypes.Structure):
    _fields_ = [("Count", wt.DWORD), ("Luid", ctypes.c_longlong), ("Attributes", wt.DWORD)]


def old_disable(name):
    luid = F._Luid()
    F._padv.LookupPrivilegeValueW(None, name, ctypes.byref(luid))
    tp = OldLayout(1, luid.LowPart | (luid.HighPart << 32), 0)
    tok = F._open_token()
    f = F._padv.AdjustTokenPrivileges
    f.argtypes = [wt.HANDLE, wt.BOOL, ctypes.c_void_p, wt.DWORD, ctypes.c_void_p, ctypes.c_void_p]
    ctypes.set_last_error(0)
    ok = f(tok, False, ctypes.byref(tp), 0, None, None)
    return bool(ok), ctypes.get_last_error()


out["old_layout_results"] = {n: old_disable(n) for n in out["enabled_before"]}
out["enabled_after_old_layout"] = F.enabled_guarded()
real = F.disable_privileges
F.disable_privileges = lambda *a, **k: {}
try:
    F.secure_token()
    out["refused_when_disable_does_nothing"] = False
except F.GuardError:
    out["refused_when_disable_does_nothing"] = True
F.disable_privileges = real
st = F.secure_token()
out["enabled_after_secure_token"] = F.enabled_guarded()
out["outcome"] = st["outcome"]
print(json.dumps(out))
"""


def test_token() -> None:
    cp = subprocess.run([sys.executable, "-I", "-B", "-c", PRIV_CHILD, str(HERE)], capture_output=True, text=True)
    try:
        o = json.loads(cp.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        check("launching-token child ran", False, cp.stdout + cp.stderr)
        return
    held_any = bool(o["held"])
    note = f"held {o['held']}, enabled before {o['enabled_before']}"
    check(f"secure_token leaves no guarded privilege enabled, read back from the token ({note})", o["enabled_after_secure_token"] == [], str(o))
    check("secure_token refuses when the disable did nothing", o["refused_when_disable_does_nothing"] is (True if held_any else o["refused_when_disable_does_nothing"]), str(o))
    if held_any:
        check("toggle: the old structure layout leaves the enabled privileges enabled",
              o["enabled_after_old_layout"] == o["enabled_before"] and o["enabled_before"] != [], str(o))
        check("outcome reports each held privilege as disabled", all(v == "disabled" for k, v in o["outcome"].items() if k in o["held"]), str(o["outcome"]))
    else:
        check("non-elevated token: the guarded privileges are absent and that is not an error", all(v == "absent" for v in o["outcome"].values()), str(o))
    # the launching process itself, after its own secure_token
    check("this process: no guarded privilege enabled", F.enabled_guarded() == [], str(F.enabled_guarded()))


# ------------------------------------------------------------------ guards

def test_guards(scratch: Path) -> None:
    repo = HERE.parents[2]
    check("git tree detected", F.in_git_tree(repo / "tools"))
    check("outside-git accepted", not F.in_git_tree(scratch))
    for what, fn in (("git tree", lambda: F.assert_outside_git(repo / "docs", "x")),
                     ("UNC path", lambda: F.assert_local_ntfs(Path("//server/share/mxc-fx"))),
                     ("user profile", lambda: F.assert_local_ntfs(Path(os.environ["USERPROFILE"]) / "mxc-fx")),
                     ("OneDrive component", lambda: F.assert_local_ntfs(Path("C:/OneDrive/mxc-fx")))):
        try:
            fn()
            check(f"guard refuses {what}", False, "accepted")
        except F.GuardError:
            check(f"guard refuses {what}", True)
    try:
        info = F.assert_local_ntfs(F.TREE_ROOT / "x")
        check("guard accepts a local fixed NTFS path", info["filesystem"] == "NTFS" and info["fixed"], str(info))
    except F.GuardError as exc:
        check("guard accepts a local fixed NTFS path", False, str(exc))
    real = F.volume_info
    try:
        for fs, kind, label in (("FAT32", 3, "non-NTFS"), ("NTFS", 2, "removable")):
            F.volume_info = lambda p, fs=fs, kind=kind: {"drive": "C:", "drive_type": kind, "fixed": kind == 3, "filesystem": fs}  # type: ignore[assignment]
            try:
                F.assert_local_ntfs(F.TREE_ROOT / "x")
                check(f"guard refuses a {label} volume", False, "accepted")
            except F.GuardError:
                check(f"guard refuses a {label} volume", True)
    finally:
        F.volume_info = real  # type: ignore[assignment]
    inside = repo / "docs" / "zz_probe_out"
    cp = subprocess.run([sys.executable, "-I", "-B", str(HERE / "run_probe.py"), "--dry-only", "--out-root", str(inside),
                         "--v100-launcher", sys.executable, "--main-launcher", sys.executable,
                         "--container-python", sys.executable, "--toolchain", str(scratch)], capture_output=True, text=True)
    check("run_probe refuses an output root inside a git tree and writes nothing",
          cp.returncode == 2 and "REFUSED" in cp.stdout and not inside.exists(), cp.stdout + cp.stderr)
    sddl = "O:BAG:SYD:PAI(A;OICI;FA;;;SY)(D;OICI;DCLCWP;;;S-1-15-2-1-2-3-4-5-6-7)(A;OICI;0x1200a9;;;S-1-15-2-1-2-3-4-5-6-7)S:AI"
    check("same_acl ignores the auto-inherited flag and sees an added ACE",
          F.same_acl("O:BAG:SYD:(A;;FA;;;SY)", "O:BAG:SYD:AI(A;;FA;;;SY)") and not F.same_acl("O:BAG:SYD:(A;;FA;;;SY)", "O:BAG:SYD:(A;;FA;;;SY)(D;;FA;;;BU)"))
    check("ace_types counts allow and deny", F.ace_types(sddl) == {"A": 2, "D": 1}, str(F.ace_types(sddl)))
    cond = "O:BAG:SYD:AI(A;OICIID;FA;;;BA)(XA;;FA;;;SY;(Member_of{SID(BA)}))(D;;FA;;;BU)"
    check("a conditional ACE is not understood: parse not ok and same_acl refuses",
          not F.parse_dacl(cond)["ok"] and not F.same_acl(cond, cond))
    check("a plain DACL parses fully", F.parse_dacl("O:BAG:SYD:AI(A;OICIID;FA;;;BA)(D;;FA;;;BU)")["ok"] is True)
    import run_probe as RP  # noqa: PLC0415

    before = {"process_sandboxes": [], "mxc_state_dir": [], "appcontainer_keys": ["HKCU\\k\\A", "HKCU\\k\\B"]}
    other = dict(before, appcontainer_keys=["HKCU\\k\\A", "HKCU\\k\\B", "HKCU\\k\\unrelated-app"])
    mine = dict(before, appcontainer_keys=["HKCU\\k\\A", "HKCU\\k\\B", "HKCU\\k\\mxcfx-abc123"])
    check("registry scoping: an unrelated AppContainer key change is not MXC state", RP.state_changes(before, other, "mxcfx-abc123") == {})
    check("registry scoping: a key naming this container is MXC state",
          "appcontainer_keys_for_this_container" in RP.state_changes(before, mine, "mxcfx-abc123"))
    copy_dir = scratch / "pyc-copy"
    copy_dir.mkdir()
    for f in HERE.iterdir():
        if f.suffix in (".py", ".ps1"):
            shutil.copyfile(f, copy_dir / f.name)
    (copy_dir / "__pycache__").mkdir()
    (copy_dir / "__pycache__" / "landing.cpython-314.pyc").write_bytes(b"\x00")
    cp2 = subprocess.run([sys.executable, "-I", "-B", str(copy_dir / "run_probe.py"), "--dry-only", "--out-root", str(scratch / "pyc-out"),
                          "--v100-launcher", sys.executable, "--main-launcher", sys.executable,
                          "--container-python", sys.executable, "--toolchain", str(scratch)], capture_output=True, text=True)
    check("run_probe refuses when a bytecode cache exists in its directory",
          cp2.returncode == 2 and "bytecode cache" in cp2.stdout and not (scratch / "pyc-out").exists(), cp2.stdout)
    approved = scratch / "pyc-approved.txt"
    approved.write_text("".join(f"{hashlib.sha256((copy_dir / n).read_bytes()).hexdigest()}  {n}\n"
                                for n in sorted(x.name for x in copy_dir.iterdir() if x.suffix in (".py", ".ps1"))), encoding="utf-8")
    r2 = subprocess.run([PWSH, "-NoProfile", "-File", str(copy_dir / "launch.ps1"), "-ApprovedFile", str(approved), "-CheckOnly"],
                        capture_output=True, text=True, timeout=120)
    check("launch.ps1 refuses when a bytecode cache exists", r2.returncode == 2 and "bytecode cache" in r2.stdout, r2.stdout)
    sd = F.read_sddl(scratch)
    ui = F.policy("fx-a", "c", Path("C:/mxc-fx/t/T"), Path("C:/mxc-fx/t/payload"), Path("C:/tc"), Path("C:/py.exe"), Path("C:/r.json"))["ui"]
    check("policy runs with UI lockdown off: ui exactly disable false, clipboard none, injection false",
          ui == {"disable": False, "clipboard": "none", "injection": False}, str(ui))
    pm = F.make_tree(scratch / "smoke-ok", "s")
    cps = subprocess.run([sys.executable, "-I", "-B", str(HERE / "smoke_payload.py"), "--t", str(pm["T"]), "--out", str(pm["T"] / "_smoke.json")],
                         capture_output=True, text=True)
    rs = json.loads((pm["T"] / "_smoke.json").read_text(encoding="utf-8"))
    check("smoke payload completes and reports ok when every import works", cps.returncode == 0 and rs["ok"] is True, str(rs))
    broken = scratch / "smoke-broken"
    broken.mkdir()
    shutil.copyfile(HERE / "smoke_payload.py", broken / "smoke_payload.py")
    (broken / "payload.py").write_text("raise ImportError('DLL load failed while importing _ctypes')\n", encoding="utf-8")
    pb = F.make_tree(scratch / "smoke-bad", "s")
    subprocess.run([sys.executable, "-I", "-B", str(broken / "smoke_payload.py"), "--t", str(pb["T"]), "--out", str(pb["T"] / "_smoke.json")],
                   capture_output=True, text=True)
    rb = json.loads((pb["T"] / "_smoke.json").read_text(encoding="utf-8"))
    check("smoke payload reports not ok when an import fails", rb["ok"] is False and "DLL load failed" in rb["steps"]["payload"], str(rb))
    for what, make in (("a package directory shadowing a module", lambda d: (d / "landing").mkdir()),
                       ("an extension module", lambda d: (d / "landing.pyd").write_bytes(b"MZ"))):
        d3 = scratch / ("shadow-" + what.split()[1])
        d3.mkdir()
        for f in HERE.iterdir():
            if f.suffix in (".py", ".ps1"):
                shutil.copyfile(f, d3 / f.name)
        make(d3)
        cp3 = subprocess.run([sys.executable, "-I", "-B", str(d3 / "run_probe.py"), "--dry-only", "--out-root", str(scratch / "shadow-out"),
                              "--v100-launcher", sys.executable, "--main-launcher", sys.executable,
                              "--container-python", sys.executable, "--toolchain", str(scratch)], capture_output=True, text=True)
        check(f"run_probe refuses {what}", cp3.returncode == 2 and "REFUSED" in cp3.stdout and not (scratch / "shadow-out").exists(), cp3.stdout)
        ap3 = scratch / (d3.name + ".txt")
        ap3.write_text("".join(f"{hashlib.sha256((d3 / n).read_bytes()).hexdigest()}  {n}\n"
                               for n in sorted(x.name for x in d3.iterdir() if x.suffix in (".py", ".ps1"))), encoding="utf-8")
        r3 = subprocess.run([PWSH, "-NoProfile", "-File", str(d3 / "launch.ps1"), "-ApprovedFile", str(ap3), "-CheckOnly"],
                            capture_output=True, text=True, timeout=120)
        check(f"launch.ps1 refuses {what}", r3.returncode == 2 and "REFUSED" in r3.stdout, r3.stdout)
    check("vendored SDDL reader reads a directory", sd.startswith("O:") and "D:" in sd, sd[:60])


# ------------------------------------------------------------------ hash-bound launch

def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def pwsh_launch(d: Path, approved: Path, *extra: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([PWSH, "-NoProfile", "-File", str(d / "launch.ps1"), "-ApprovedFile", str(approved), *extra],
                          capture_output=True, text=True, timeout=120)


def test_launch(scratch: Path) -> None:
    d = scratch / "launchcopy"
    d.mkdir()
    for p in HERE.iterdir():
        if p.suffix in (".py", ".ps1"):
            shutil.copyfile(p, d / p.name)
    names = sorted(p.name for p in d.iterdir())
    ok_text = "".join(f"{sha(d / n)}  {n}\n" for n in names)
    approved = scratch / "APPROVED_SHA256.txt"
    r = pwsh_launch(d, scratch / "missing.txt", "-CheckOnly")
    check("launch refuses a missing approval file", r.returncode == 2 and "REFUSED" in r.stdout, r.stdout + r.stderr)
    approved.write_text(ok_text, encoding="utf-8")
    r = pwsh_launch(d, approved, "-CheckOnly")
    check("launch passes when every hash matches", r.returncode == 0 and "hash check passed" in r.stdout, r.stdout + r.stderr)
    check("every module the harness imports is in the hashed set",
          {"fixtures.py", "landing.py", "payload.py", "run_probe.py", "summarise.py", "smoke_payload.py"} <= set(names))
    approved.write_text("".join(ln for ln in ok_text.splitlines(True) if "payload.py" not in ln), encoding="utf-8")
    r = pwsh_launch(d, approved, "-CheckOnly")
    check("launch refuses a script with no approved line", r.returncode == 2 and "no approved hash for payload.py" in r.stdout, r.stdout)
    approved.write_text(ok_text.replace(sha(d / "landing.py"), "0" * 64), encoding="utf-8")
    r = pwsh_launch(d, approved, "-CheckOnly")
    check("launch refuses a mismatched hash", r.returncode == 2 and "hash mismatch for landing.py" in r.stdout, r.stdout)
    approved.write_text(ok_text, encoding="utf-8")
    with (d / "payload.py").open("ab") as f:
        f.write(b"\n# tampered\n")
    r = pwsh_launch(d, approved, "-CheckOnly")
    check("launch refuses a script changed after approval", r.returncode == 2 and "hash mismatch for payload.py" in r.stdout, r.stdout)
    out_root = scratch / "launch-out"
    r = pwsh_launch(d, approved, "--dry-only", "--out-root", str(out_root))
    check("a refused launch starts nothing", r.returncode == 2 and not out_root.exists(), r.stdout + r.stderr)
    (d / "payload.py").write_bytes((HERE / "payload.py").read_bytes())
    (d / "extra.py").write_text("pass\n", encoding="utf-8")
    r = pwsh_launch(d, approved, "-CheckOnly")
    check("launch refuses an unlisted extra script", r.returncode == 2 and "no approved hash for extra.py" in r.stdout, r.stdout)
    (d / "extra.py").unlink()
    r = pwsh_launch(d, approved, "-Python", str(scratch / "no_such_python.exe"))
    check("launch refuses a missing interpreter", r.returncode == 2 and "interpreter missing" in r.stdout, r.stdout)


# ------------------------------------------------------------------ end to end with a fake launcher

FAKE = r'''
import json, os, subprocess, sys, time
args = sys.argv[1:]
mode = os.environ.get("FAKE_MODE", "open")
tier = "appcontainer-dacl" if (mode == "probe_tier" or mode.startswith("t3")) else "base-container"


def hold(path, new):
    """A detached third party that keeps path open without read sharing; returns once it holds it."""
    flag = os.path.join(os.environ["LOCALAPPDATA"], "hold-%d.flag" % time.time_ns())
    access = "0x40000000,0,0,2,0x80,0" if new else "0x80000000,0,0,3,0x80,0"
    code = "import _winapi,time,sys; h=_winapi.CreateFile(sys.argv[1]," + access + "); open(sys.argv[2],'w').close(); time.sleep(6)"
    subprocess.Popen([sys.executable, "-I", "-c", code, path, flag], creationflags=0x08000008)
    for _ in range(200):
        if os.path.exists(flag):
            return
        time.sleep(0.05)
if "--probe" in args:
    print(json.dumps({"tier": tier, "needsDaclAugmentation": False, "warnings": [],
                      "probes": {"baseContainerSupportsDenyPaths": True}}))
    sys.exit(0)
cfg = json.load(open(args[0], encoding="utf-8"))
is_smoke = "smoke_payload" in cfg["process"]["commandLine"]
if "--dry-run" in args:
    if mode == "dryfail":
        print("error: policy rejected by validation", file=sys.stderr)
        sys.exit(1)
    if mode == "t3hostprep":
        print("warning: AppContainer + DACL tier selected: run `wxc-host-prep prepare-null-device` (elevated) first")
    print("selected isolation tier: " + ("appcontainer-dacl" if (mode == "tiermismatch" or (mode == "tiermeasured" and not is_smoke)) else tier) + "\nDry run completed. Result: validation passed")
    sys.exit(0)
if "--log-file" in args:
    open(args[args.index("--log-file") + 1], "w").write("fake log\n")
if mode == "nopayload" or (mode == "nomeasured" and not is_smoke):
    sys.exit(1)
if mode == "landnoreport":
    rc = subprocess.run(cfg["process"]["commandLine"], cwd=cfg["process"]["cwd"], shell=True).returncode
    try:
        os.remove(cfg["filesystem"]["readwritePaths"][0] + "\\_report.json")
    except OSError:
        pass
    sys.exit(rc)
sub = cfg["filesystem"]["deniedPaths"][0]
user = os.environ["USERNAME"]
IC = "C:/Windows/System32/icacls.exe"


def lock_sub():
    subprocess.run([IC, sub, "/inheritance:r", "/grant:r", user + ":(OI)(CI)(RX)", "/Q"], capture_output=True)


def unlock_sub():
    subprocess.run([IC, sub, "/reset", "/T", "/Q"], capture_output=True)


if is_smoke and mode == "t3smokeace":
    subprocess.run([IC, sub, "/deny", user + ":(OI)(CI)(W,D,DC)", "/Q"], capture_output=True)
if not is_smoke and mode == "t3failleft":
    subprocess.run([IC, sub, "/deny", user + ":(OI)(CI)(W,D,DC)", "/Q"], capture_output=True)
    subprocess.run([IC, cfg["filesystem"]["readonlyPaths"][0], "/grant", "*S-1-1-0:(R)", "/Q"], capture_output=True)
    sys.exit(1)
if is_smoke and mode == "smokestate":
    d = os.path.join(os.environ["LOCALAPPDATA"], "Microsoft", "MXC", "dacl-restore")
    os.makedirs(d, exist_ok=True)
    open(os.path.join(d, "changed.json"), "w").write("{}")
if not is_smoke and mode == "hiddenland":
    hold(os.path.join(sub, "s2_new.txt"), True)
    sys.exit(1)
if not is_smoke and mode == "lockafternoreport":
    hold(os.path.join(sub, "marker.txt"), False)
    sys.exit(1)
if not is_smoke and mode in ("lockafter", "hiddenland_report"):
    lock_sub()
    rc = subprocess.run(cfg["process"]["commandLine"], cwd=cfg["process"]["cwd"], shell=True).returncode
    unlock_sub()
    hold(os.path.join(sub, "marker.txt" if mode == "lockafter" else "s2_new.txt"), mode == "hiddenland_report")
    sys.exit(rc)
if not is_smoke and mode in ("t3ok", "t3left", "t3tc", "t3nodeny", "t3tcchild"):
    if mode == "t3nodeny":
        lock_sub()
    else:
        subprocess.run([IC, sub, "/deny", user + ":(OI)(CI)(W,D,DC)", "/Q"], capture_output=True)
    rc = subprocess.run(cfg["process"]["commandLine"], cwd=cfg["process"]["cwd"], shell=True).returncode
    if mode != "t3left":
        unlock_sub()
    if mode == "t3tc":
        subprocess.run([IC, cfg["filesystem"]["readonlyPaths"][0], "/grant", "*S-1-1-0:(R)", "/Q"], capture_output=True)
    if mode == "t3tcchild":
        subprocess.run([IC, os.path.join(cfg["filesystem"]["readonlyPaths"][0], "child.txt"), "/grant", "*S-1-1-0:(R)", "/Q"], capture_output=True)
    sys.exit(rc)
if mode == "held":
    subprocess.run(["icacls", sub, "/inheritance:r", "/grant:r", user + ":(OI)(CI)(RX)", "/Q"], capture_output=True)
try:
    rc = subprocess.run(cfg["process"]["commandLine"], cwd=cfg["process"]["cwd"], shell=True).returncode
finally:
    if mode == "held":
        subprocess.run(["icacls", sub, "/reset", "/T", "/Q"], capture_output=True)
sys.exit(rc)
'''


def make_fake(scratch: Path) -> Path:
    py = scratch / "fake_wxc.py"
    py.write_text(FAKE, encoding="utf-8")
    cmd = scratch / "fake_wxc.cmd"
    cmd.write_text(f'@"{sys.executable}" -I "{py}" %*\r\n', encoding="utf-8")
    return cmd


def run_e2e(scratch: Path, mode: str, *extra: str) -> tuple[subprocess.CompletedProcess[str], dict[str, object] | None, Path]:
    tag = f"{mode}-{len(list(scratch.glob('e2e-*')))}"
    out = scratch / f"e2e-{tag}"
    local = scratch / f"e2e-local-{tag}"
    local.mkdir(exist_ok=True)
    tc = scratch / "e2e-toolchain"
    tc.mkdir(exist_ok=True)
    (tc / "child.txt").write_text("child\n", encoding="utf-8")
    env = dict(os.environ, FAKE_MODE=mode, LOCALAPPDATA=str(local))
    env.pop("MXC_DACL_STATE_DIR", None)
    fake = make_fake(scratch) if not (scratch / "fake_wxc.cmd").exists() else scratch / "fake_wxc.cmd"
    cp = subprocess.run([sys.executable, "-I", "-B", str(HERE / "run_probe.py"), "--out-root", str(out), "--v100-launcher", str(fake),
                         "--main-launcher", str(fake), "--container-python", sys.executable, "--toolchain", str(tc),
                         "--runs", "3", "--tree-root", str(SELF_ROOT), *extra], capture_output=True, text=True, env=env, timeout=600)
    summ = next(iter(sorted(out.glob("run-*/summary.json"))), None) if out.exists() else None
    batch = next(iter(sorted(out.glob("run-*"))), out) if out.exists() else out
    return cp, (json.loads(summ.read_text(encoding="utf-8")) if summ else None), batch


def clear_trees() -> None:
    """Remove the end-to-end trees; waits for the fake's third-party holders to let go of what they hold."""
    deadline = time.time() + 40
    while True:
        for d in SELF_ROOT.glob("run-*") if SELF_ROOT.exists() else []:
            icacls(str(d), "/reset", "/T", "/Q")
            shutil.rmtree(d, ignore_errors=True)
        try:
            SELF_ROOT.rmdir()
        except OSError:
            pass
        if not SELF_ROOT.exists() or time.time() > deadline:
            return
        time.sleep(1)


def test_e2e(scratch: Path) -> None:
    if SELF_ROOT.exists() and any(SELF_ROOT.iterdir()):
        check("end to end skipped: the self-test tree root is in use", False, str(list(SELF_ROOT.iterdir())))
        return
    cp, summ, batch = run_e2e(scratch, "open")
    kept = any(json.loads(p.read_text(encoding="utf-8")).get("cleanup", {}).get("tree_kept") for p in batch.glob("launch-fx-a-*.json"))
    check("e2e open tree: FAIL, STOP printed, tree kept for evidence",
          summ is not None and summ["verdict"] == "FAIL" and "STOP: FAIL condition met" in cp.stdout and kept, cp.stdout[-600:] + cp.stderr[-300:])
    check("e2e open tree: stopped after the first launch", len(list(batch.glob("launch-fx-a-*.json"))) == 1)
    check("e2e open tree: handshake captured the ACL while the process ran",
          json.loads((batch / "launch-fx-a-r1.json").read_text(encoding="utf-8"))["acl_during"].get("process_running_at_capture") is True)
    clear_trees()
    cp, summ, batch = run_e2e(scratch, "held")
    check("e2e held tree: HOLD with three completed launches",
          summ is not None and summ["verdict"] == "HOLD" and summ["fx_a_completed"] == 3, cp.stdout[-800:] + cp.stderr[-300:] + json.dumps(summ)[:600])
    if summ:
        check("e2e held tree: Win32 error 5 recorded for every attempt, S3 recorded, tier named",
              all(v == 5 for r in summ["s2_win32"].values() for v in r.values()) and summ["s3"] and summ["dry_run_tiers"] == ["base-container"])
    check("e2e held tree: tree root removed at the end", not SELF_ROOT.exists())
    clear_trees()
    cp, summ, batch = run_e2e(scratch, "nopayload")
    check("e2e payload cannot run in the container: CONTAINER-PAYLOAD-BROKEN before any S2 launch",
          summ is not None and summ["verdict"] == "CONTAINER-PAYLOAD-BROKEN" and "CONTAINER-PAYLOAD-BROKEN" in cp.stdout
          and not list(batch.glob("launch-fx-a-*.json")), cp.stdout[-500:])
    clear_trees()
    cp, summ, batch = run_e2e(scratch, "nomeasured")
    check("e2e smoke ok but the measured launch has no report: LAUNCH-FAILED and a stop",
          summ is not None and summ["verdict"] == "LAUNCH-FAILED" and "STOP: no container report" in cp.stdout, cp.stdout[-500:])
    clear_trees()
    cp, summ, batch = run_e2e(scratch, "landnoreport")
    check("e2e writes landed and the report is missing: FAIL, never LAUNCH-FAILED, tree kept",
          summ is not None and summ["verdict"] == "FAIL" and "report absent" in cp.stdout and "no container report" not in cp.stdout
          and summ["changes"] and summ["changes"][0][3] == "no report", cp.stdout[-600:])
    clear_trees()
    cp, summ, batch = run_e2e(scratch, "dryfail")
    check("e2e validation rejected: REFUSED", summ is not None and summ["verdict"] == "REFUSED", cp.stdout[-500:])
    clear_trees()
    cp, summ, batch = run_e2e(scratch, "tiermismatch")
    launched = [json.loads(p.read_text(encoding="utf-8"))["launched"] for p in batch.glob("launch-*.json") if "s4" not in p.name]
    check("e2e dry-run tier differs from S0: stop before any launch, TIER-MISMATCH with the reason",
          "dry-run tier" in cp.stdout and launched == [False] and summ is not None and summ["verdict"] == "TIER-MISMATCH"
          and summ["tier_mismatch"][0]["dry_run_tier"] == "appcontainer-dacl", cp.stdout[-500:])
    clear_trees()
    cp, summ, batch = run_e2e(scratch, "tiermeasured")
    recs = {p.name: json.loads(p.read_text(encoding="utf-8")) for p in batch.glob("launch-*.json")}
    check("e2e smoke tier matches S0 but the measured dry-run differs: the measured launch is not made, TIER-MISMATCH names it",
          recs.get("launch-smoke-r1.json", {}).get("ok") is True and recs.get("launch-fx-a-r1.json", {}).get("launched") is False
          and summ is not None and summ["verdict"] == "TIER-MISMATCH" and summ["tier_mismatch"][0]["tag"] == "fx-a-r1"
          and "dry-run tier" in cp.stdout, cp.stdout[-500:])
    clear_trees()
    cp, summ, batch = run_e2e(scratch, "smokestate")
    check("e2e smoke launch changes MXC state: STOPPED-STATE-CHANGE with the reason, no measured launch",
          summ is not None and summ["verdict"] == "STOPPED-STATE-CHANGE" and "STOPPED-STATE-CHANGE" in cp.stdout
          and summ["smoke_state_changed"] and not list(batch.glob("launch-fx-a-*.json")), cp.stdout[-500:])
    clear_trees()
    cp, summ, batch = run_e2e(scratch, "nopayload")
    sm_rec = json.loads((batch / "launch-smoke-r1.json").read_text(encoding="utf-8"))
    check("e2e smoke with no report: the cause is no-report and the stop text says the launcher or payload died, not an import failure",
          sm_rec["cause"] == "no-report" and "no report came back" in cp.stdout and "step failed" not in cp.stdout, cp.stdout[-500:])
    clear_trees()
    cp, summ, batch = run_e2e(scratch, "hiddenland")
    check("e2e a new file lands, is held without read sharing and no report comes back: FAIL, never LAUNCH-FAILED",
          summ is not None and summ["verdict"] == "FAIL" and "STOP: FAIL condition met" in cp.stdout and "T/sub unchanged" not in cp.stdout
          and summ["changes"][0][3] == "no report" and "create_file" in summ["changes"][0][1], cp.stdout[-600:] + json.dumps(summ)[:500])
    clear_trees()
    cp, summ, batch = run_e2e(scratch, "hiddenland_report")
    check("e2e a new file lands and is held, the report came back: FAIL",
          summ is not None and summ["verdict"] == "FAIL" and summ["changes"][0][3] == "report", cp.stdout[-600:] + json.dumps(summ)[:500])
    clear_trees()
    cp, summ, batch = run_e2e(scratch, "lockafter")
    check("e2e marker held at the after-snapshot and nothing appeared: INSTRUMENT-BLIND, no change",
          summ is not None and summ["verdict"] == "INSTRUMENT-BLIND" and summ["changes"] == [], cp.stdout[-600:] + json.dumps(summ)[:500])
    clear_trees()
    cp, summ, batch = run_e2e(scratch, "lockafternoreport")
    check("e2e marker held, nothing appeared, no report: INSTRUMENT-BLIND and a stop line that names the read error",
          summ is not None and summ["verdict"] == "INSTRUMENT-BLIND" and "could not read" in cp.stdout and "T/sub unchanged" not in cp.stdout,
          cp.stdout[-600:] + json.dumps(summ)[:500])
    clear_trees()
    cp, summ, batch = run_e2e(scratch, "probe_tier")
    check("e2e S0 tier not base-container: stop before S4 and any launch",
          "STOP: S0 tier" in cp.stdout and not list(batch.glob("launch-*.json")), cp.stdout[-500:])
    clear_trees()
    test_e2e_fxc(scratch)
    cp, summ, batch = run_e2e(scratch, "held", "--s5")
    hdr = json.loads((batch / "header.json").read_text(encoding="utf-8"))
    sm_rec = json.loads((batch / "launch-smoke-r1.json").read_text(encoding="utf-8"))
    check("e2e header and records state that UI lockdown is off and the policy submitted it so",
          hdr["ui_lockdown"] is False and "ctypes" in hdr["ui_lockdown_note"] and sm_rec["config"]["ui"] == F.UI_POLICY
          and sm_rec["ok"] is True)
    check("e2e --s5 on Tier 1: recorded as not applicable and no fx-b launch",
          hdr["s5"]["note"] == "S5 not applicable on Tier 1" and not list(batch.glob("launch-fx-b-*.json")))
    check("e2e header records interpreters with sha256 and host prep not run",
          len(hdr["host_interpreter"]["sha256"]) == 64 and len(hdr["container_interpreter"]["sha256"]) == 64
          and hdr["host_prep_ran"] in ("observed in effect", "not observed")
          and hdr["host_prep_evidence"]["start"]["sddl"] and hdr["host_prep_evidence"]["end"]["sddl"] and hdr["token_privileges"]["after"] is not None
          and all(not p["enabled"] for p in hdr["token_privileges"]["after"] if p["name"] in F.GUARDED_PRIVILEGES)
          and isinstance(hdr["security_suite"], list))
    state_dir_ok = all(r.get("state_changed_by_run") == {} for r in map(lambda p: json.loads(p.read_text(encoding="utf-8")), batch.glob("launch-fx-a-*.json")))
    check("e2e: MXC state directory was never redirected or deleted by the harness", state_dir_ok)
    clear_trees()


def test_e2e_fxc(scratch: Path) -> None:
    fxc = ("--variant", "fx-c", "--allow-dacl-tier")
    cp, summ, batch = run_e2e(scratch, "t3ok", "--variant", "fx-c")
    check("e2e fx-c without --allow-dacl-tier is refused before anything is written",
          cp.returncode == 2 and "requires --allow-dacl-tier" in cp.stdout and summ is None, cp.stdout[-300:])
    clear_trees()
    cp, summ, batch = run_e2e(scratch, "t3ok", *fxc)
    rec = json.loads((batch / "launch-fx-c-r1.json").read_text(encoding="utf-8")) if (batch / "launch-fx-c-r1.json").exists() else {}
    dc = rec.get("deny_ace_cleanup", {})
    check("e2e fx-c tier 3: HOLD, tier asserted, DENY ACE seen during and gone after, ACL and toolchain restored",
          summ is not None and summ["verdict"] == "HOLD" and summ["variant"] == "fx-c" and summ["dry_run_tiers"] == [F.TIER_3]
          and (dc.get("deny_aces_before"), dc.get("deny_aces_after")) == (0, 0) and (dc.get("deny_aces_during") or 0) >= 1
          and dc.get("deny_ace_observed_during") is True and dc.get("sddl_after_equals_before") is True
          and rec.get("toolchain_acl_unchanged") is True and "dacl_restore_dir" in rec and rec.get("toolchain_acl_during"),
          cp.stdout[-800:] + json.dumps(dc))
    hdr = json.loads((batch / "header.json").read_text(encoding="utf-8"))
    br = json.loads((batch / "batch-record.json").read_text(encoding="utf-8")) if (batch / "batch-record.json").exists() else {}
    sm = json.loads((batch / "launch-smoke-r1.json").read_text(encoding="utf-8")) if (batch / "launch-smoke-r1.json").exists() else {}
    check("e2e fx-c records: smoke ACLs, interpreter ACL per launch, recursive toolchain saves at start and end, host-prep evidence",
          sm.get("toolchain_acl_unchanged") is True and sm.get("t_acl_unchanged") is True and sm.get("deny_ace_cleanup", {}).get("deny_aces_after") == 0
          and rec.get("python_acl_unchanged") is True and rec.get("t_acl_unchanged") is True
          and br.get("toolchain_tree_unchanged") is True and br["toolchain_tree_compare"]["objects_start"] >= 2
          and (batch / "toolchain-acl-start.txt").exists() and (batch / "toolchain-acl-end.txt").exists()
          and hdr["toolchain_tree_acl_start"]["saved"] and hdr["toolchain_tree_acl_end"]["saved"]
          and hdr["host_prep_evidence"]["start"]["sddl"] and hdr["host_prep_evidence"]["end"]["sddl"]
          and hdr["host_prep_ran"] in ("observed in effect", "not observed"), json.dumps(br)[:500])
    check("e2e fx-c policy submitted leastPrivilege true without captureDenials",
          rec.get("config", {}).get("processContainer") == {"leastPrivilege": True})
    clear_trees()
    cp, summ, batch = run_e2e(scratch, "t3nodeny", *fxc)
    check("e2e fx-c no DENY ACE during the run: INSTRUMENT-BLIND and a stop that says so",
          summ is not None and summ["verdict"] == "INSTRUMENT-BLIND" and "no DENY ACE was observed" in cp.stdout, cp.stdout[-600:])
    clear_trees()
    cp, summ, batch = run_e2e(scratch, "t3left", *fxc)
    check("e2e fx-c DENY ACE left on T/sub after exit: STOPPED-STATE-CHANGE, tree kept, one launch",
          summ is not None and summ["verdict"] == "STOPPED-STATE-CHANGE" and "STOPPED-STATE-CHANGE" in cp.stdout and "DENY ACE or ACL change left on T/sub" in cp.stdout
          and len(list(batch.glob("launch-fx-c-*.json"))) == 1, cp.stdout[-600:])
    clear_trees()
    cp, summ, batch = run_e2e(scratch, "t3tc", *fxc)
    icacls(str(scratch / "e2e-toolchain"), "/reset", "/T", "/Q")
    check("e2e fx-c toolchain ACL not restored: STOPPED-STATE-CHANGE",
          summ is not None and summ["verdict"] == "STOPPED-STATE-CHANGE" and "STOPPED-STATE-CHANGE" in cp.stdout and "toolchain ACL changed" in cp.stdout, cp.stdout[-600:])
    clear_trees()
    cp, summ, batch = run_e2e(scratch, "t3failleft", *fxc)
    icacls(str(scratch / "e2e-toolchain"), "/reset", "/T", "/Q")
    check("e2e fx-c failed launch (no report) that left an ACE and a changed toolchain: STOPPED-STATE-CHANGE in summary.json AND on the console",
          summ is not None and summ["verdict"] == "STOPPED-STATE-CHANGE" and "VERDICT: STOPPED-STATE-CHANGE" in cp.stdout
          and "STOP: STOPPED-STATE-CHANGE" in cp.stdout and any("DENY ACE" in h for h in summ["state_left"])
          and any("toolchain ACL" in h for h in summ["state_left"]) and len(list(batch.glob("launch-fx-c-*.json"))) == 1,
          cp.stdout[-700:] + json.dumps(summ)[:400] if summ else cp.stdout[-700:])
    clear_trees()
    cp, summ, batch = run_e2e(scratch, "t3smokeace", *fxc)
    check("e2e fx-c smoke launch leaves an ACE: STOPPED-STATE-CHANGE, no measured launch (toggle: t3ok above is HOLD)",
          summ is not None and summ["verdict"] == "STOPPED-STATE-CHANGE" and "STOP: STOPPED-STATE-CHANGE: the smoke launch" in cp.stdout
          and not list(batch.glob("launch-fx-c-*.json")) and any(h.startswith("smoke-r1") for h in summ["state_left"]),
          cp.stdout[-700:])
    clear_trees()
    cp, summ, batch = run_e2e(scratch, "t3tcchild", *fxc)
    icacls(str(scratch / "e2e-toolchain"), "/reset", "/T", "/Q")
    check("e2e fx-c a toolchain descendant ACL changed (root unchanged, three launches complete): batch-level STOPPED-STATE-CHANGE",
          summ is not None and summ["verdict"] == "STOPPED-STATE-CHANGE" and summ["fx_a_completed"] == 3
          and any(h.startswith("batch:") for h in summ["state_left"]), cp.stdout[-700:] + (json.dumps(summ)[:400] if summ else ""))
    clear_trees()
    cp, summ, batch = run_e2e(scratch, "t3hostprep", *fxc)
    check("e2e fx-c host prep required: HOST-PREP-REQUIRED names the subcommand, nothing launched, host prep not run",
          summ is not None and summ["verdict"] == "HOST-PREP-REQUIRED" and "prepare-null-device" in cp.stdout
          and not list(batch.glob("launch-fx-c-*.json")) and summ["host_prep_required"] == ["prepare-null-device"], cp.stdout[-600:])
    clear_trees()
    cp, summ, batch = run_e2e(scratch, "held", *fxc)
    check("e2e fx-c but the dry-run selects base-container: TIER-MISMATCH, nothing launched",
          summ is not None and summ["verdict"] == "TIER-MISMATCH" and not list(batch.glob("launch-fx-c-*.json")), cp.stdout[-600:])
    clear_trees()


# ------------------------------------------------------------------ directory lint

def test_lint() -> None:
    hash_digits = re.compile("#" + r"\d")
    name_digit = re.compile(r"fx[-_]?\d|fixture[-_ ]?\d", re.I)
    bad = []
    for p in sorted(HERE.iterdir()):
        if p.suffix in (".py", ".ps1"):
            text = p.read_text(encoding="utf-8")
            if hash_digits.search(text) or name_digit.search(text) or (USER and USER.lower() in text.lower()):
                bad.append(p.name)
    check("no hash-and-digits reference, numbered fixture name or account name in the directory", not bad, str(bad))
    check("no MXC state redirection or state-directory deletion in the harness",
          "MXC_DACL_STATE_DIR" in (HERE / "run_probe.py").read_text(encoding="utf-8")
          and "pop(\"MXC_DACL_STATE_DIR\"" in (HERE / "run_probe.py").read_text(encoding="utf-8")
          and "rmtree(state_dir" not in (HERE / "run_probe.py").read_text(encoding="utf-8"))


def main() -> int:
    scratch = Path(tempfile.mkdtemp(prefix="mxcds-selftest-"))
    was_enabled = F.enabled_guarded()
    F.secure_token()
    print(f"launching token: guarded privileges enabled before secure_token {was_enabled}; after {F.enabled_guarded()}")
    probe = scratch / "lockprobe"
    (probe / "sub").mkdir(parents=True)
    lock(probe / "sub")
    enforced = P._rec(lambda: P.mkdir(probe / "sub" / "d"))["ok"] is False
    unlock(probe / "sub")
    check("preflight: a read-only ACL is enforced against this process (guarded privileges disabled)", enforced)
    try:
        test_verdicts()
        test_fxc_verdicts_and_policy()
        test_landing(scratch)
        test_token()
        test_win32(scratch)
        test_guards(scratch)
        test_launch(scratch)
        test_e2e(scratch)
        test_lint()
    finally:
        icacls(str(scratch), "/reset", "/T", "/Q")
        shutil.rmtree(scratch, ignore_errors=True)
    failed = [n for n, ok, _ in results if not ok]
    print(f"{len(results) - len(failed)} passed, {len(failed)} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
