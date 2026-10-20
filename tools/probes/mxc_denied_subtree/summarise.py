"""Verdict for a finished (or stopped) MXC denied-subtree batch.

WHAT IT DECIDES, from the per-launch records in a batch directory (launch-*.json, written by run_probe.py)
and the S0 tier in header.json:

  FAIL             any change inside T/sub (a named write landing, or any other difference in names, sizes,
                   sha256, attributes, last-write time, directories or alternate data streams) while the
                   policy was in force, whether or not the container's report came back
  CONTAINER-PAYLOAD-BROKEN  the import-only smoke launch did not complete inside the container; no S2 run was made
                   (summary.json ``smoke[].cause`` separates a payload import failure from a launcher failure
                   or timeout and from a missing report)
  STOPPED-STATE-CHANGE  the smoke launch changed MXC state (summary.json ``smoke_state_changed`` holds the change),
                   whether or not it completed; no S2 run was made
  HOST-PREP-REQUIRED  (fx-c) the dry-run names a wxc-host-prep subcommand whose effect is not in place; nothing was
                   launched (summary.json ``host_prep_required`` names the subcommands; this harness never runs host prep)
  REFUSED          the launcher's own validation (--dry-run) rejected the policy and no fx-a launch completed
  LAUNCH-FAILED    validation passed but a launch produced no container report (the payload never ran, ran
                   and was killed by its watchdog before reporting, or the launcher failed or timed out), T/sub
                   unchanged and every read on the host clean; a launch with no report and a host read error
                   is INSTRUMENT-BLIND
  TIER-MISMATCH    the dry-run tier differs from the S0 tier or is not base-container; nothing was launched
                   (summary.json names both tiers and the reason)
  INSTRUMENT-BLIND S1 (writes outside T/sub) did not all land, S4 (unfenced control) was absent or did not
                   land all five attempts, the five attempts were not all executed, the container's report
                   disagrees with the tree, an entry or ACL could not be read or fully parsed, the before-snapshot
                   lacks the layout the builder wrote, a refusal carried a code other than 5 (ACCESS_DENIED),
                   a guarded privilege was enabled (a launch skipped for that reason included), the smoke launch is absent, the per-launch tier differs from S0 or is not the single tier
                   named, MXC state changed, a DENY ACE or any ACL change was left on T/sub, or the toolchain
                   ACL changed
  INCOMPLETE       fewer than three completed fx-a launches and nothing above applies
  HOLD             three completed fx-a launches on one tier equal to S0, T/sub identical before and after
                   every launch, every S2 attempt refused, S1 and S4 as expected, MXC state unchanged,
                   nothing left on T/sub or the toolchain

fx-c (leastPrivilege true, AppContainer DACL tier) uses the same rules with appcontainer-dacl as the single tier.
For fx-c, over EVERY launched record (completed or not, and the smoke launch), a DENY ACE or ACL change left on
T/sub or T, a changed MXC state directory, a changed ACL on the toolchain root or on the container interpreter, or a
difference between the recursive toolchain ACL saves taken at batch start and end (the batch record) is
STOPPED-STATE-CHANGE (``state_left``). No DENY ACE observed on T/sub during a completed launch is INSTRUMENT-BLIND,
and so is a missing or unusable batch record.

Precedence: FAIL, STOPPED-STATE-CHANGE, CONTAINER-PAYLOAD-BROKEN, REFUSED, HOST-PREP-REQUIRED, TIER-MISMATCH, LAUNCH-FAILED, INSTRUMENT-BLIND, INCOMPLETE, HOLD. A change in T/sub is positive
evidence and wins over a control that failed. S5 (fx-b) is reported on its own line; a change there is also FAIL.
The refusal-code rule (every refusal must be Win32 error 5) is stricter than the case's "refused 5 of 5": MXC does
not document which error a native deny returns, so another code reads INSTRUMENT-BLIND and is recoverable from
summary.json. A read or listing error on the host never produces FAIL by itself: the judge leaves out only what the error
touched (an unreadable entry's content; everything below an unlistable directory), an entry that appears or
vanishes in a successful listing still counts, and the run is INSTRUMENT-BLIND whether or not a report came back.
summary.json carries the tier set, the S3 outcomes and the Win32 error code of every attempt.

Usage: python -I summarise.py <batch-dir>      (writes <batch-dir>/summary.json, prints the verdict)
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import payload as P  # noqa: E402

N_RUNS = 3
TIER = "base-container"
TIER_3 = "appcontainer-dacl"


def _completed(r: dict[str, object]) -> bool:
    return bool(r.get("launched")) and bool(r.get("payload_present")) and r.get("judge") is not None


def _refused(r: dict[str, object]) -> bool:
    return r.get("dry_run_rc") != 0


def _launch_failed(r: dict[str, object]) -> bool:
    return r.get("dry_run_rc") == 0 and bool(r.get("launched")) and not _completed(r)


def _changed(r: dict[str, object]) -> bool:
    """T/sub differs after a launch, whether or not the container's report came back."""
    j = r.get("judge")
    return j is not None and (j["landed_count"] > 0 or bool(j["sub_changes"]))  # type: ignore[index]


def _s5_class(r: dict[str, object]) -> str:
    if _refused(r):
        return "rejected-at-validation"
    if not _completed(r):
        return "run-failed"
    return "ran-with-change" if _changed(r) else "ran-denied"


def state_left(r: dict[str, object]) -> list[str]:
    """Host state a launched record left behind (fx-c); empty for a record that never launched.

    Applies to a completed launch, a launch with no report and the smoke launch alike. A field that was not
    recorded counts as not restored.
    """
    if not r.get("launched"):
        return []
    tag = r.get("tag")
    out = []
    if r.get("state_changed_by_run"):
        out.append(f"{tag}: MXC state changed")
    d = r.get("deny_ace_cleanup") or {}
    if d.get("deny_aces_after") != 0 or d.get("sddl_after_equals_before") is not True:
        out.append(f"{tag}: DENY ACE or ACL change left on T/sub after exit")
    for key, what in (("t_acl_unchanged", "T ACL changed or not recorded"),
                      ("toolchain_acl_unchanged", "toolchain ACL changed or not recorded"),
                      ("python_acl_unchanged", "container interpreter ACL changed or not recorded")):
        if r.get(key) is not True:
            out.append(f"{tag}: {what}")
    return out


def _hygiene(r: dict[str, object]) -> list[str]:
    out = []
    if r.get("state_changed_by_run"):
        out.append(f"{r['tag']}: MXC state changed")
    d = r.get("deny_ace_cleanup") or {}
    if d.get("deny_aces_after") != 0 or d.get("sddl_after_equals_before") is not True:
        out.append(f"{r['tag']}: DENY ACE or ACL change left on T/sub after exit")
    if r.get("acl_parse_ok") is not True:
        out.append(f"{r['tag']}: an ACL was not fully parsed (unknown ACE type)")
    if r.get("toolchain_acl_unchanged") is not True:
        out.append(f"{r['tag']}: toolchain ACL changed or not recorded")
    return out


def verdict(records: list[dict[str, object]], s0_tier: str | None = None) -> dict[str, object]:
    fx = "fx-c" if any((r.get("state") == "S2" and r.get("fixture") == "fx-c") or r.get("variant") == "fx-c" for r in records) else "fx-a"
    a = [r for r in records if r.get("state") == "S2" and r.get("fixture") == fx]
    b = [r for r in records if r.get("state") == "S2" and r.get("fixture") == "fx-b"]
    s4 = [r for r in records if r.get("state") == "S4"]
    done = [r for r in a if _completed(r)]
    smoke = [r for r in records if r.get("state") == "SMOKE"]
    batch_recs = [r for r in records if r.get("state") == "BATCH"]
    gate = a + smoke
    blind: list[str] = []
    left: list[str] = []
    for r in a + smoke:
        if r.get("privileges_enabled"):
            blind.append(f"{r['tag']}: guarded privileges enabled at launch {r['privileges_enabled']} (launch refused)")
    for r in a:
        if _launch_failed(r) and (r.get("judge") or {}).get("read_errors"):
            blind.append(f"{r['tag']}: no container report and unreadable entries "
                         f"{[e['path'] for e in r['judge']['read_errors']]}")  # type: ignore[index]
    for r in done:
        s1 = r.get("s1_host") or {}
        if not (s1 and all(s1.values())):  # type: ignore[union-attr]
            blind.append(f"{r['tag']}: S1 did not land {sorted(k for k, v in s1.items() if not v) or 'all'}")  # type: ignore[union-attr]
        j = r["judge"]
        if not j["attempts_executed"]:  # type: ignore[index]
            blind.append(f"{r['tag']}: S2 attempts not all executed")
        if j["disagreements"]:  # type: ignore[index]
            blind.append(f"{r['tag']}: container report and host disagree on {j['disagreements']}")  # type: ignore[index]
        if j.get("read_errors"):  # type: ignore[union-attr]
            blind.append(f"{r['tag']}: unreadable entries {[e['path'] for e in j['read_errors']]}")  # type: ignore[index]
        if j.get("layout_ok") is not True:  # type: ignore[union-attr]
            blind.append(f"{r['tag']}: the before-snapshot does not hold the layout the builder wrote")
        odd = {k: v.get("winerror") for k, v in (r.get("payload") or {}).get("s2", {}).items()  # type: ignore[union-attr]
               if not v.get("ok") and v.get("winerror") != 5}
        if odd:
            blind.append(f"{r['tag']}: refusal code other than 5 (ACCESS_DENIED): {odd}")
        if fx == "fx-c":
            if r.get("acl_parse_ok") is not True:
                blind.append(f"{r['tag']}: an ACL was not fully parsed (unknown ACE type)")
            if (r.get("deny_ace_cleanup") or {}).get("deny_ace_observed_during") is not True:
                blind.append(f"{r['tag']}: no DENY ACE observed on T/sub during the run")
        else:
            blind += _hygiene(r)
    if fx == "fx-c":
        for r in a + smoke:
            left += state_left(r)
        if any(r.get("launched") for r in a + smoke):
            if not batch_recs:
                blind.append("the batch-level toolchain ACL comparison is absent")
            elif batch_recs[0].get("toolchain_tree_unchanged") is False:
                left.append(f"batch: toolchain tree ACL differs between batch start and end "
                            f"{batch_recs[0].get('toolchain_tree_differences')}")
            elif batch_recs[0].get("toolchain_tree_unchanged") is not True:
                blind.append(f"the batch-level toolchain ACL comparison is unusable {batch_recs[0].get('toolchain_tree_differences')}")
    tiers = sorted({str(r.get("dry_run_selected_tier")) for r in a if r.get("dry_run_rc") == 0})
    want = (s0_tier or TIER_3) if fx == "fx-c" else TIER
    if done and (len(tiers) != 1 or tiers[0] != want or (s0_tier is not None and tiers[0] != s0_tier)):
        blind.append(f"per-launch tier {tiers} is not the single tier {s0_tier or TIER}")
    if not any(r.get("ok") for r in smoke) and done:
        blind.append("the import-only smoke launch is absent or did not complete")
    if not s4:
        blind.append("S4 absent")
    for r in s4:
        if not r.get("all_landed"):
            blind.append(f"S4 did not land all five attempts: {r.get('landed')}")
    changed = [(r["tag"], sorted(k for k, v in r["judge"]["landed"].items() if v), r["judge"]["sub_changes"],  # type: ignore[index]
                "report" if r.get("payload_present") else "no report")
               for r in a + b if _changed(r)]
    mismatch = [r["tier_mismatch"] for r in gate if r.get("tier_mismatch")]
    broken = [r for r in smoke if r.get("launched") and not r.get("ok")]
    smoke_state = [{"tag": r["tag"], "changes": r["state_changed_by_run"]} for r in smoke
                   if r.get("launched") and r.get("state_changed_by_run")]
    host_prep = sorted({str(x) for r in gate for x in (r.get("host_prep_required") or [])})
    out: dict[str, object] = {
        "variant": fx, "state_left": left, "host_prep_required": host_prep,
        "s0_tier": s0_tier, "dry_run_tiers": tiers, "fx_a_launches": len(a), "fx_a_completed": len(done),
        "s1_landed": [bool(r.get("s1_host")) and all(r["s1_host"].values()) for r in done],  # type: ignore[union-attr]
        "s1_win32": {r["tag"]: {k: v.get("winerror") for k, v in (r.get("payload") or {}).get("s1", {}).items()} for r in done},  # type: ignore[union-attr]
        "s2_landed_counts": [r["judge"]["landed_count"] for r in done],  # type: ignore[index]
        "s2_sub_unchanged": [r["judge"]["sub_unchanged"] for r in done],  # type: ignore[index]
        "s2_reported_refused": [sum(1 for v in r["judge"]["reported_success"].values() if not v) for r in done],  # type: ignore[index]
        "s2_win32": {r["tag"]: {k: v.get("winerror") for k, v in (r.get("payload") or {}).get("s2", {}).items()} for r in done},  # type: ignore[union-attr]
        "s3": {r["tag"]: {k: {"ok": v.get("ok"), "winerror": v.get("winerror")}
                          for k, v in (r.get("payload") or {}).get("s3", {}).items()} for r in done},  # type: ignore[union-attr]
        "s4": [{"tag": r.get("tag"), "landed_count": sum(r.get("landed", {}).values())} for r in s4],  # type: ignore[union-attr]
        "s5": [{"tag": r["tag"], "outcome": _s5_class(r)} for r in b],
        "smoke": [{"tag": r["tag"], "ok": r.get("ok"), "cause": r.get("cause"), "report": r.get("report")} for r in smoke],
        "smoke_state_changed": smoke_state,
        "ui_lockdown": False, "changes": changed, "tier_mismatch": mismatch, "blind_reasons": blind, "attempts": list(P.ATTEMPTS),
    }
    if changed:
        out["verdict"] = "FAIL"
    elif smoke_state or left:
        out["verdict"] = "STOPPED-STATE-CHANGE"
    elif broken:
        out["verdict"] = "CONTAINER-PAYLOAD-BROKEN"
    elif not done and any(_refused(r) for r in gate):
        out["verdict"] = "REFUSED"
    elif host_prep:
        out["verdict"] = "HOST-PREP-REQUIRED"
    elif mismatch:
        out["verdict"] = "TIER-MISMATCH"
    elif blind and any(r.get("privileges_enabled") for r in a + smoke) and not done:
        out["verdict"] = "INSTRUMENT-BLIND"
    elif any(_launch_failed(r) and not (r.get("judge") or {}).get("read_errors") for r in a):
        out["verdict"] = "LAUNCH-FAILED"
    elif blind:
        out["verdict"] = "INSTRUMENT-BLIND"
    elif len(done) < N_RUNS:
        out["verdict"] = "INCOMPLETE"
    else:
        out["verdict"] = "HOLD"
    return out


def load(batch: Path) -> list[dict[str, object]]:
    return [json.loads(p.read_text(encoding="utf-8")) for p in sorted([*batch.glob("launch-*.json"), *batch.glob("batch-record.json")])]


def s0_tier_of(batch: Path) -> str | None:
    """The tier the batch expects: the S0 tier, or appcontainer-dacl for an fx-c batch."""
    try:
        h = json.loads((batch / "header.json").read_text(encoding="utf-8"))
        return h.get("expected_tier") or h["s0"][h["launcher_used"]]["tier"]
    except (OSError, ValueError, KeyError):
        return None


def main() -> int:
    batch = Path(sys.argv[1])
    v = verdict(load(batch), s0_tier_of(batch))
    (batch / "summary.json").write_text(json.dumps(v, indent=1), encoding="utf-8")
    print(json.dumps(v, indent=1))
    print(f"VERDICT: {v['verdict']}")
    return 0 if v["verdict"] == "HOLD" else 1


if __name__ == "__main__":
    raise SystemExit(main())
