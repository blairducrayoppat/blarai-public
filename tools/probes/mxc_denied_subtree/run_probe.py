r"""MXC denied-subtree probe: does a deniedPaths entry inside a read-write tree hold against writes?

WHAT IT MEASURES
  One policy shape (fx-a): readwritePaths [T], deniedPaths [T/sub]. From inside the container it makes
  write attempts outside T/sub (S1, control) and five write attempts into T/sub (S2: create a file, open
  marker.txt with an append-only handle, rename rename_me.txt, delete delete_me.txt, create a subdirectory), plus a
  read and a listing of T/sub (S3). Every attempt is a Win32 call and is recorded with its Win32 error code.
  The HOST judges the outcome from the tree afterwards: T/sub must be identical to its pre-run snapshot
  (names, sizes, sha256 of every file, directories, alternate data streams); any difference is a FAIL.
  The five attempts' own landing predicates attribute a difference; they do not decide HOLD.
  S0 records both launchers' --probe output (tier, whether native deny is advertised) before any write; every
  launch's --dry-run tier must equal the S0 tier and be base-container, else the batch stops before launch.
  The ACL of T/sub is captured before, during (a host thread, while the container waits at a handshake file)
  and after, with the ACL of the toolchain folder before and after. S4 runs the same five attempts unconfined
  on the same account against a fresh tree, once per batch, before any container run. S5 (fx-b,
  allowDaclMutation false) applies only on a Tier 2/3 run (--allow-dacl-tier); on Tier 1 it records
  "S5 not applicable on Tier 1" and runs nothing.

VARIANT fx-c (--variant fx-c, requires --allow-dacl-tier). fx-a with processContainer.leastPrivilege true and without
  captureDenials. The PSEC contract cannot represent leastPrivilege, so the launcher selects an AppContainer tier;
  with the tier-2 broker compiled out that is appcontainer-dacl, where deniedPaths is a host DENY ACE on T/sub. The
  batch asserts the dry-run tier is appcontainer-dacl (else TIER-MISMATCH, nothing launched), records the ACL of T/sub
  and of T before, DURING (a DENY ACE must appear) and after (it must be gone), MXC's dacl-restore directory before,
  during and after, and the toolchain root ACL before, during and after; the container interpreter's own ACL is
  captured before and after every launch, the smoke launch included. At batch start and end the whole toolchain tree
  is saved with icacls /save /T into the run folder and the two files are compared per object, ignoring ACE order.
  Over EVERY launched record (completed or not, and the smoke launch), a DENY ACE or ACL change left on T/sub or T, a
  changed MXC state directory, a changed ACL on the toolchain root or the interpreter, or a difference between the
  batch-level saves is STOPPED-STATE-CHANGE (a landing in T/sub is still FAIL); no DENY ACE during a completed run is
  INSTRUMENT-BLIND. The header records the system-drive root DACL at batch start and end with the detector's result
  (the exact entries prepare-system-drive writes); host_prep_ran is derived from that evidence. If the dry-run names a wxc-host-prep subcommand whose effect is not in place, the batch stops with
  HOST-PREP-REQUIRED before any launch and names the subcommand; this harness never runs host prep.

HOW TO RUN (hash-bound: launch.ps1 refuses unless every script's sha256 is in APPROVED_SHA256.txt)
  pwsh -File launch.ps1 --v100-launcher <exe> --main-launcher <exe> --container-python <exe> --toolchain <dir>
       [--runs 3] [--s5] [--launcher v100|main] [--variant fx-a|fx-c] [--keep-tree] [--dry-only] [--allow-dacl-tier]
  Direct form (development only): python -I run_probe.py [same options]
  --dry-only creates each tree, validates each policy with --dry-run, removes the trees, and launches nothing.

WHAT IT WRITES
  Raw records only to <home>/blarai-research-data/mxc-denied-subtree/run-<YYYYMMDD>-<n>/ (refused if that is
  inside a git working tree): header.json (launcher sha256 + signature, both --probe outputs, host and
  container interpreter path + sha256, machine conditions, MXC state directory listing), launch-*.json (config,
  dry-run text, launch result, container report, host snapshots, ACL captures, state diff, cleanup proof),
  summary.json. Trees are created under C:/mxc-fx/<run>/ and removed after each launch unless --keep-tree; a
  tree is kept after any stop that follows a launch. MXC's own state directory is never redirected or deleted;
  it is listed (names, sizes, sha256) before and after each launch. SIDs are kept raw in the records.

WHAT IT DOES NOT MEASURE
  Tier 1 behaviour if the build selects Tier 2/3, and the reverse; a denied path that is a reparse point,
  junction or symlink into or out of the tree; a denied path on another volume; the enumeratePaths field;
  captureDenials mode allow; concurrent runs sharing a containerId; the session-isolation and WSLc backends;
  nono under MXC; anything about any fork; UI lockdown on (ui.disable true breaks the payload's ctypes inside the
  container, so the policy runs with ui.disable false, clipboard none, injection false: the case is
  filesystem only); per-entry ACL changes inside T/sub; change time and the archive bit; a directory's own
  last-write time (a file created and removed again, or renamed and renamed back, inside T/sub is not seen);
  a FILE_WRITE_DATA open of the marker (only the append-only open is attempted); moving a file into T/sub from elsewhere; renaming T/sub itself;
  writes to alternate data streams (streams are only compared before and after); other spellings of the
  denied path (8.3 short names, case variants, trailing dots, long-path prefixes). For fx-c additionally: no denial
  capture, so a refusal is seen only as a Win32 error code; fx-c differs from fx-a in three things at once (the
  tier, leastPrivilege, and no captureDenials), so neither a HOLD nor a FAIL is attributable to one of them; the
  \Device\Null host-prep state is not measured (an unverifiable subcommand counts as not in effect). It makes no network
  connection, binds no listener, touches no firewall rule, and runs no host-prep step.

SMOKE LAUNCH. Before the first measured launch one import-only payload (smoke_payload.py) runs under the same
policy shape on a throwaway tree. If it does not complete, the batch stops with CONTAINER-PAYLOAD-BROKEN and no
S2 attempt is made. UI lockdown is off in every policy (see above).

STOP RULES. The batch stops at once on: a failed smoke launch, any change in T/sub (prints "STOP: FAIL condition met"), a control
that did not land (S4, S1), a container report that disagrees with the tree, a dry-run rejection, a dry-run tier
that differs from S0 (fx-c: from appcontainer-dacl) or is not base-container (fx-c: or a host-prep step is required), a launch with no report, changed MXC state, a DENY ACE or ACL
change left on T/sub, or a changed toolchain ACL.
"""

from __future__ import annotations

import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
# Checked before any sibling module is imported: a package directory or an extension module in this directory
# would be imported in place of the hashed source, and a bytecode cache would be loaded instead of it.
_STALE = [str(x) for x in _HERE.iterdir() if x.is_dir() or x.suffix not in (".py", ".ps1")]
if _STALE:
    print(f"REFUSED: entries in the probe directory that the hash binding does not cover (bytecode cache, package "
          f"directory, extension module or other file): {_STALE}")
    sys.exit(2)
sys.path.insert(0, str(_HERE))

import argparse  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
import re  # noqa: E402
import shutil  # noqa: E402
import subprocess  # noqa: E402
import threading  # noqa: E402
import time  # noqa: E402
import uuid  # noqa: E402
from datetime import datetime  # noqa: E402

import fixtures as F  # noqa: E402
import landing as L  # noqa: E402
import payload as P  # noqa: E402
import summarise as S  # noqa: E402

DATA_ROOT_NAME = ("blarai-research-data", "mxc-denied-subtree")


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="milliseconds")


def data_root() -> Path:
    return Path.home().joinpath(*DATA_ROOT_NAME)


def next_batch_dir(root: Path) -> Path:
    day = datetime.now().strftime("%Y%m%d")
    n = 1
    while (root / f"run-{day}-{n}").exists():
        n += 1
    return root / f"run-{day}-{n}"


def mxc_state() -> dict[str, object]:
    return {"process_sandboxes": F.reg_list(F.REG_MAPPINGS), "appcontainer_keys": F.reg_list(F.REG_AC_MAPPINGS),
            "mxc_state_dir": F.dir_listing(F.mxc_state_dir())}


def state_changes(before: dict[str, object], after: dict[str, object], container_id: str) -> dict[str, object]:
    """MXC state that changed during a launch. AppContainer registry keys count only when they name this container."""
    ch: dict[str, object] = {}
    for k in ("process_sandboxes", "mxc_state_dir"):
        if before[k] != after[k]:
            ch[k] = [before[k], after[k]]
    reg = F.registry_diff(before["appcontainer_keys"], after["appcontainer_keys"], container_id)  # type: ignore[arg-type]
    if reg["related"]:
        ch["appcontainer_keys_for_this_container"] = reg["related"]
    return ch | ({"_unrelated_registry_changes_ignored": reg["unrelated"]} if reg["unrelated"] and ch else {})


def launch_env() -> dict[str, str]:
    env = dict(os.environ)
    env.pop("MXC_DACL_STATE_DIR", None)
    return env


def remove_tree(base: Path) -> dict[str, object]:
    errors: list[str] = []

    def onerr(func: object, path: str, exc: BaseException) -> None:
        errors.append(f"{path}: {exc!r}"[:200])
        try:
            os.chmod(path, 0o700)
            func(path)  # type: ignore[operator]
        except OSError:
            pass

    if sys.version_info >= (3, 12):
        shutil.rmtree(base, onexc=onerr)
    else:
        shutil.rmtree(base, onerror=lambda f, p, e: onerr(f, p, e[1]))
    return {"removed": not base.exists(), "errors": errors}


def run_control(out: Path, tree_base: Path) -> dict[str, object]:
    """S4: the five attempts, unconfined, same account, fresh tree. Expected: all five land."""
    tag = "s4-r1"
    paths = F.make_tree(tree_base / tag, tag)
    t = paths["T"]
    before = L.snapshot_tree(t)
    report = t / "_report.json"
    cp = F.hidden([sys.executable, "-I", "-B", str(Path(__file__).resolve().parent / "payload.py"), "--t", str(t),
                   "--out", str(report), "--mode", "control"], timeout=120)
    after = L.snapshot_tree(t)
    rep = json.loads(report.read_text(encoding="utf-8")) if report.exists() else None
    j = L.judge(rep, before, after, tag=tag)
    ok = bool(j["attempts_executed"]) and not j["disagreements"] and j["landed_count"] == len(P.ATTEMPTS)
    rec = {"state": "S4", "tag": tag, "rc": cp.returncode, "stderr": cp.stderr[-300:], "landed": j["landed"],
           "all_landed": ok, "judge": j, "s1_host": L.s1_effects(before, after), "report": rep,
           "cleanup": remove_tree(paths["base"]), "finished": now_iso()}
    (out / f"launch-{tag}.json").write_text(json.dumps(rec, indent=1), encoding="utf-8")
    return rec


def capture_acls(sub: Path, t: Path, tools: dict[str, Path]) -> dict[str, dict[str, object]]:
    """ACLs of T/sub, T, the toolchain root and the container interpreter at one moment."""
    return {"sub": F.acl_capture(sub), "t": F.acl_capture(t), "toolchain": F.acl_capture(tools["toolchain"]),
            "python": F.acl_capture(tools["python"])}


def record_acl_comparison(rec: dict[str, object], before: dict[str, dict[str, object]], after: dict[str, dict[str, object]]) -> None:
    """Write the before and after captures and every restored-or-not comparison into a launch record."""
    rec["acl_before"] = {"sub": before["sub"], "t": before["t"]}
    rec["acl_after"] = {"sub": after["sub"], "t": after["t"]}
    rec["toolchain_acl_before"], rec["toolchain_acl_after"] = before["toolchain"], after["toolchain"]
    rec["python_acl_before"], rec["python_acl_after"] = before["python"], after["python"]
    rec["acl_parse_ok"] = all(x["parse_ok"] for pair in (before, after) for x in pair.values())
    rec["toolchain_acl_unchanged"] = F.same_acl(after["toolchain"]["sddl"], before["toolchain"]["sddl"])  # type: ignore[arg-type]
    rec["python_acl_unchanged"] = F.same_acl(after["python"]["sddl"], before["python"]["sddl"])  # type: ignore[arg-type]
    rec["t_acl_unchanged"] = F.same_acl(after["t"]["sddl"], before["t"]["sddl"])  # type: ignore[arg-type]
    rec["deny_ace_cleanup"] = {
        "deny_aces_before": before["sub"]["deny_aces"], "deny_aces_after": after["sub"]["deny_aces"],
        "sddl_after_equals_before": F.same_acl(after["sub"]["sddl"], before["sub"]["sddl"]),  # type: ignore[arg-type]
        "sddl_text_identical": after["sub"]["sddl"] == before["sub"]["sddl"]}


def watcher(t: Path, sub: Path, proc: subprocess.Popen[str], cap: dict[str, object], toolchain: Path | None = None) -> None:
    """Wait for the payload's ready flag, capture the ACL of T\\sub while the container runs, then release it."""
    t0 = time.perf_counter()
    while time.perf_counter() - t0 < 60 and proc.poll() is None:
        if (t / P.READY).exists():
            cap["during"] = F.acl_capture(sub)
            cap["during_t"] = F.acl_capture(t)
            cap["during_dacl_restore"] = F.dir_listing(F.mxc_state_dir())
            if toolchain is not None:
                cap["during_toolchain"] = F.acl_capture(toolchain)
            cap["during_at"] = now_iso()
            cap["process_running_at_capture"] = proc.poll() is None
            try:
                (t / P.GO).write_bytes(b"go\n")
                cap["go_written"] = True
            except OSError as exc:
                cap["go_written"] = repr(exc)
            return
        time.sleep(0.02)
    cap["during"] = None
    cap["note"] = "ready flag not seen before the process exited or 60 s passed"


def host_prep_stop(dry_stdout: str, rec: dict[str, object]) -> str | None:
    """Record the host-prep subcommands the dry-run names; the stop text when any is not in effect (host prep is never run here)."""
    hp = F.host_prep_status(dry_stdout)
    rec["host_prep"] = hp
    missing = [h["subcommand"] for h in hp if not h["in_effect"]]
    rec["host_prep_required"] = missing
    if not missing:
        return None
    return (f"STOP: HOST-PREP-REQUIRED: the launcher's dry-run recommends {missing} (elevated, persistent, changes the host) and its "
            "effect is not in place; this harness never runs host prep; nothing was launched")


def run_smoke(exe: Path, tools: dict[str, Path], out: Path, tree_base: Path, s0_tier: str | None,
              allow_dacl: bool, keep_tree: bool, variant: str = "fx-a") -> dict[str, object]:
    """One launch of the import-only smoke payload under the measured policy shape, on a throwaway tree."""
    tag = "smoke-r1"
    cid = f"mxcfx-{uuid.uuid4().hex[:12]}"
    paths = F.make_tree(tree_base / tag, tag)
    base, t = paths["base"], paths["T"]
    payload_dir = base / "payload"
    payload_dir.mkdir()
    for name in ("payload.py", "smoke_payload.py"):
        shutil.copyfile(Path(__file__).resolve().parent / name, payload_dir / name)
    report = t / "_smoke.json"
    cfg = F.policy(variant, cid, t, payload_dir, tools["toolchain"], tools["python"], report, script="smoke_payload.py")
    cfg_path = base / "policy.json"
    cfg_path.write_text(json.dumps(cfg, indent=1), encoding="utf-8")
    env = launch_env()
    rec: dict[str, object] = {"state": "SMOKE", "variant": variant, "tag": tag, "container_id": cid, "launcher": str(exe), "config": cfg,
                              "started": now_iso(), "state_before": mxc_state(), "launched": False, "ok": False,
                              "privileges_enabled": F.enabled_guarded()}
    acls_before = capture_acls(paths["sub"], t, tools)
    dry = F.hidden([str(exe), str(cfg_path), "--dry-run"], env=env)
    rec["dry_run_rc"] = dry.returncode
    rec["dry_run"] = {"rc": dry.returncode, "stdout": dry.stdout.strip(), "stderr": dry.stderr.strip()}
    sel = re.search(r"selected isolation tier:\s*(\S+)", dry.stdout)
    tier = sel.group(1) if sel else None
    rec["dry_run_selected_tier"] = tier
    stop: str | None = None
    if dry.returncode != 0:
        stop = "STOP: dry-run rejected the smoke policy; see the record"
    elif tier != s0_tier or (tier != F.TIER_1 and not allow_dacl):
        rec["tier_mismatch"] = {"tag": tag, "dry_run_tier": tier, "s0_tier": s0_tier, "reason": "smoke dry-run tier differs from S0 or is not base-container"}
        stop = f"STOP: smoke dry-run tier {tier} differs from the S0 tier {s0_tier} or is not {F.TIER_1}"
    elif (hp_stop := host_prep_stop(dry.stdout, rec)) is not None:
        stop = hp_stop
    elif rec["privileges_enabled"]:
        stop = f"STOP: guarded privileges enabled in the launching token: {rec['privileges_enabled']}"
    else:
        logf = out / f"mxc-{tag}.log"
        t0 = time.perf_counter()
        try:
            cp = subprocess.run([str(exe), str(cfg_path), "--log-file", str(logf)], env=env, text=True, capture_output=True,
                                timeout=180, creationflags=F.CREATE_NO_WINDOW | F.BELOW_NORMAL)
            rec["launch"] = {"exit_code": cp.returncode, "stdout": cp.stdout.strip()[-3000:], "stderr": cp.stderr.strip()[-3000:]}
        except subprocess.TimeoutExpired:
            rec["launch"] = {"timeout": True}
        rec["launch"]["wall_secs"] = round(time.perf_counter() - t0, 3)  # type: ignore[index]
        rec["launched"] = True
        rec["mxc_log_tail"] = logf.read_text(encoding="utf-8", errors="replace")[-4000:] if logf.exists() else ""
        rep = None
        if report.exists():
            try:
                rep = json.loads(report.read_text(encoding="utf-8"))
            except (OSError, ValueError) as exc:
                rec["report_error"] = repr(exc)
        rec["report"] = rep
        rec["ok"] = bool(rep and rep.get("ok"))
        record_acl_comparison(rec, acls_before, capture_acls(paths["sub"], t, tools))
        rec["state_changed_by_run"] = state_changes(rec["state_before"], mxc_state(), cid)  # type: ignore[arg-type]
        lau = rec["launch"]
        if rep is not None and not rep.get("ok"):
            rec["cause"] = "payload-import-failure"
            why = f"the import-only payload ran and a step failed: {rep.get('steps')}"
        elif lau.get("timeout"):  # type: ignore[union-attr]
            rec["cause"] = "launcher-timeout"
            why = "the launcher did not return inside its timeout (no payload verdict)"
        elif rep is None:
            rec["cause"] = "no-report"
            why = (f"no report came back (launcher exit code {lau.get('exit_code')}): the launcher failed, or the payload died "  # type: ignore[union-attr]
                   "before writing it; see launch.stderr and the MXC log")
        else:
            rec["cause"] = None
            why = ""
        left = S.state_left(rec) if variant == "fx-c" else ([f"MXC state changed: {rec['state_changed_by_run']}"] if rec["state_changed_by_run"] else [])
        if left:
            stop = f"STOP: STOPPED-STATE-CHANGE: the smoke launch left host state changed: {left}; no S2 run was made"
        elif not rec["ok"]:
            stop = f"STOP: CONTAINER-PAYLOAD-BROKEN: {why}; no S2 run was made"
    rec["cleanup"] = {"tree_kept": True, "path": str(base)} if (keep_tree or (stop and rec["launched"])) else remove_tree(base)
    rec["stop"] = stop
    rec["finished"] = now_iso()
    (out / f"launch-{tag}.json").write_text(json.dumps(rec, indent=1), encoding="utf-8")
    return rec


def run_launch(variant: str, i: int, exe: Path, tools: dict[str, Path], out: Path, tree_base: Path, s0_tier: str | None,
               allow_dacl: bool, keep_tree: bool, dry_only: bool) -> dict[str, object]:
    tag = f"{variant}-r{i}"
    cid = f"mxcfx-{uuid.uuid4().hex[:12]}"
    paths = F.make_tree(tree_base / tag, tag)
    base, t, sub = paths["base"], paths["T"], paths["sub"]
    payload_dir = base / "payload"
    payload_dir.mkdir()
    shutil.copyfile(Path(__file__).resolve().parent / "payload.py", payload_dir / "payload.py")
    report = t / "_report.json"
    cfg = F.policy(variant, cid, t, payload_dir, tools["toolchain"], tools["python"], report)
    cfg_path = base / "policy.json"
    cfg_path.write_text(json.dumps(cfg, indent=1), encoding="utf-8")
    env = launch_env()
    rec: dict[str, object] = {"state": "S2", "fixture": variant, "tag": tag, "container_id": cid, "launcher": str(exe),
                              "config": cfg, "started": now_iso(), "machine": F.machine_conditions(),
                              "state_before": mxc_state()}
    before = L.snapshot_tree(t)
    rec["tree_before"] = before
    acls_before = capture_acls(sub, t, tools)
    rec["acl_before"] = {"sub": acls_before["sub"], "t": acls_before["t"]}
    rec["toolchain_acl_before"], rec["python_acl_before"] = acls_before["toolchain"], acls_before["python"]
    rec["privileges"] = F.token_privileges()
    rec["privileges_enabled"] = F.enabled_guarded()
    dry = F.hidden([str(exe), str(cfg_path), "--dry-run"], env=env)
    rec["dry_run_rc"] = dry.returncode
    rec["dry_run"] = {"rc": dry.returncode, "stdout": dry.stdout.strip(), "stderr": dry.stderr.strip()}
    sel = re.search(r"selected isolation tier:\s*(\S+)", dry.stdout)
    tier = sel.group(1) if sel else None
    rec["dry_run_selected_tier"] = tier
    rec["launched"] = False
    rec["payload_present"] = False
    rec["judge"] = None
    stop: str | None = None
    if dry.returncode != 0:
        rec["launch"] = {"skipped": "dry-run rejected the config"}
        stop = "STOP: dry-run rejected the policy; see the record (the host-prep step is not run by this harness)"
    elif tier != s0_tier:
        label = "expected AppContainer DACL tier" if variant == "fx-c" else "S0 tier"
        rec["launch"] = {"skipped": f"dry-run tier differs from the {label}"}
        stop = f"STOP: dry-run tier {tier} differs from the {label} {s0_tier}"
        rec["tier_mismatch"] = {"tag": tag, "dry_run_tier": tier, "s0_tier": s0_tier, "reason": f"dry-run tier differs from the {label}"}
    elif tier != F.TIER_1 and not allow_dacl:
        rec["launch"] = {"skipped": "not base-container"}
        stop = f"STOP: tier {tier} is not {F.TIER_1}; a Tier 2/3 run needs a separate review and --allow-dacl-tier"
        rec["tier_mismatch"] = {"tag": tag, "dry_run_tier": tier, "s0_tier": s0_tier, "reason": f"tier is not {F.TIER_1}; --allow-dacl-tier not given"}
    elif (hp_stop := host_prep_stop(dry.stdout, rec)) is not None:
        rec["launch"] = {"skipped": "host prep required and not in effect"}
        stop = hp_stop
    elif rec["privileges_enabled"]:
        rec["launch"] = {"skipped": "guarded privileges enabled"}
        stop = f"STOP: guarded privileges enabled in the launching token: {rec['privileges_enabled']}"
    elif dry_only:
        rec["launch"] = {"skipped": "--dry-only"}
    else:
        logf = out / f"mxc-{tag}.log"
        cap: dict[str, object] = {}
        t0 = time.perf_counter()
        proc = subprocess.Popen([str(exe), str(cfg_path), "--log-file", str(logf)], env=env, text=True,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                creationflags=F.CREATE_NO_WINDOW | F.BELOW_NORMAL)
        th = threading.Thread(target=watcher, args=(t, sub, proc, cap, tools["toolchain"]), daemon=True)
        th.start()
        try:
            so, se = proc.communicate(timeout=300)
            launch: dict[str, object] = {"exit_code": proc.returncode, "stdout": so.strip()[-3000:], "stderr": se.strip()[-3000:]}
        except subprocess.TimeoutExpired:
            proc.kill()
            launch = {"timeout": True}
        th.join(timeout=5)
        launch["wall_secs"] = round(time.perf_counter() - t0, 3)
        rec["launch"], rec["acl_during"] = launch, cap
        rec["launched"] = True
        rec["mxc_log_tail"] = logf.read_text(encoding="utf-8", errors="replace")[-4000:] if logf.exists() else ""
        after = L.snapshot_tree(t)
        rec["tree_after"] = after
        rep = None
        if report.exists():
            try:
                rep = json.loads(report.read_text(encoding="utf-8"))
            except (OSError, ValueError) as exc:
                rec["report_error"] = repr(exc)
        rec["payload"], rec["payload_present"] = rep, rep is not None
        record_acl_comparison(rec, acls_before, capture_acls(sub, t, tools))
        rec["state_after"] = mxc_state()
        rec["state_changed_by_run"] = state_changes(rec["state_before"], rec["state_after"], cid)  # type: ignore[arg-type]
        during = cap.get("during") or {}
        rec["deny_ace_cleanup"] |= {"deny_aces_during": during.get("deny_aces"),  # type: ignore[operator]
                                    "deny_ace_observed_during": bool(during.get("deny_aces"))}
        if variant == "fx-c":
            rec["toolchain_acl_during"] = cap.get("during_toolchain")
            rec["dacl_restore_dir"] = {"before": rec["state_before"]["mxc_state_dir"], "during": cap.get("during_dacl_restore"),  # type: ignore[index]
                                       "after": rec["state_after"]["mxc_state_dir"]}
        j = L.judge(rep, before, after, tag=tag)
        rec["judge"] = j
        if rep is not None:
            rec["s1_host"] = L.s1_effects(before, after)
        if j["landed_count"] > 0 or j["sub_changes"]:
            stop = (f"STOP: FAIL condition met (T/sub changed: {j['sub_changes']}; "
                    f"container report {'present' if rep is not None else 'absent'})")
        elif variant == "fx-c" and (left := S.state_left(rec)):
            stop = f"STOP: STOPPED-STATE-CHANGE: host state left changed by the launch: {left} (a launch with no report included)"
        elif rep is None and j["read_errors"]:
            stop = (f"STOP: no container report and the host could not read {[e['path'] for e in j['read_errors']]} "
                    "(instrument blind; T/sub changes seen on readable evidence: none); see the record")
        elif rep is None:
            stop = "STOP: no container report (payload never ran, was killed before reporting, or the launcher failed or timed out; T/sub unchanged, host reads clean); see the record"
        elif j["read_errors"] or j["layout_ok"] is not True:
            stop = "STOP: the host could not read what it judged (instrument blind)"
        elif not all(rec["s1_host"].values()):  # type: ignore[union-attr]
            stop = "STOP: control S1 did not land (instrument blind)"
        elif j["disagreements"]:
            stop = "STOP: container report and tree disagree (instrument blind)"
        elif not rec["acl_parse_ok"]:
            stop = "STOP: an ACL contains an ACE type this probe does not parse (instrument blind)"
        elif variant == "fx-c" and not rec["deny_ace_cleanup"]["deny_ace_observed_during"]:  # type: ignore[index]
            stop = ("STOP: no DENY ACE was observed on T/sub during the run (instrument blind: the AppContainer DACL "
                    "enforcement was not shown)")
    if not rec["launched"]:
        rec["state_after"] = mxc_state()
        rec["state_changed_by_run"] = {}
    if not stop and rec["launched"]:
        if rec["state_changed_by_run"]:
            stop = "STOP: MXC state changed by the run"
        elif (rec["deny_ace_cleanup"]["deny_aces_after"] != 0  # type: ignore[index]
              or not rec["deny_ace_cleanup"]["sddl_after_equals_before"]):  # type: ignore[index]
            stop = "STOP: a DENY ACE or ACL change was left on T/sub"
        elif not rec["toolchain_acl_unchanged"]:
            stop = "STOP: toolchain ACL changed"
    if keep_tree or (stop and rec["launched"]):
        rec["cleanup"] = {"tree_kept": True, "path": str(base), "reason": "stop after launch" if stop else "--keep-tree"}
    else:
        rec["cleanup"] = remove_tree(base)
    rec["finished"] = now_iso()
    rec["stop"] = stop
    (out / f"launch-{tag}.json").write_text(json.dumps(rec, indent=1), encoding="utf-8")
    return rec


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--runs", type=int, default=3)
    ap.add_argument("--s5", action="store_true", help="also run fx-b (allowDaclMutation false); Tier 2/3 only")
    ap.add_argument("--launcher", choices=("v100", "main"), default="v100")
    ap.add_argument("--variant", choices=("fx-a", "fx-c"), default="fx-a",
                    help="fx-c: leastPrivilege true, serviced by the AppContainer DACL tier; requires --allow-dacl-tier")
    ap.add_argument("--v100-launcher", type=Path, required=True)
    ap.add_argument("--main-launcher", type=Path, required=True)
    ap.add_argument("--container-python", type=Path, required=True)
    ap.add_argument("--toolchain", type=Path, required=True)
    ap.add_argument("--tree-root", type=Path, default=F.TREE_ROOT, help="parent of the per-run trees (default C:/mxc-fx)")
    ap.add_argument("--keep-tree", action="store_true")
    ap.add_argument("--dry-only", action="store_true")
    ap.add_argument("--allow-dacl-tier", action="store_true", help="permit a launch on a tier other than base-container")
    ap.add_argument("--out-root", type=Path, default=None, help="override the raw-output root (still refused inside a git tree)")
    a = ap.parse_args(argv)
    root = a.out_root or data_root()
    if a.variant == "fx-c" and not a.allow_dacl_tier:
        print("REFUSED: --variant fx-c runs on the AppContainer DACL tier and requires --allow-dacl-tier")
        return 2
    try:
        F.assert_outside_git(root, "output directory")
        for pth in (a.v100_launcher, a.main_launcher, a.container_python, a.toolchain):
            if not pth.exists():
                raise F.GuardError(f"{pth} does not exist")
        batch = next_batch_dir(root)
        tree_base = a.tree_root / batch.name
        if tree_base.exists():
            raise F.GuardError(f"{tree_base} already exists")
        vol = F.assert_local_ntfs(tree_base)
        F.assert_outside_git(tree_base, "tree")
    except F.GuardError as exc:
        print(f"REFUSED: {exc}")
        return 2
    batch.mkdir(parents=True)
    try:
        token = F.secure_token()
    except F.GuardError as exc:
        print(f"REFUSED: {exc}")
        return 2
    tools = {"v100": a.v100_launcher, "main": a.main_launcher, "python": a.container_python, "toolchain": a.toolchain}
    exe = tools[a.launcher]
    info = {"v100": F.launcher_info(tools["v100"]), "main": F.launcher_info(tools["main"])}
    s0 = {k: F.s0_record(v) for k, v in info.items()}
    s0_tier = s0[a.launcher]["tier"]
    differs = any(s0["v100"][f] != s0["main"][f] for f in ("tier", "fs_deny_advertised", "needs_dacl_augmentation"))
    s5_applicable = s0_tier != F.TIER_1 and a.variant == "fx-a"
    expected_tier = F.TIER_3 if a.variant == "fx-c" else s0_tier
    host_ev_start = F.host_prep_evidence() | {"at": now_iso()}
    tc_tree_start = None if a.dry_only else F.icacls_save(tools["toolchain"], batch / "toolchain-acl-start.txt") | {"at": now_iso()}
    header = {"started": now_iso(), "batch": batch.name, "launcher_used": a.launcher, "variant": a.variant, "expected_tier": expected_tier, "launchers": info, "s0": s0,
              "s0_differs_between_launchers": differs, "tree_volume": vol, "machine_start": F.machine_conditions(),
              "host_interpreter": F.interpreter_info(Path(sys.executable)), "host_python_version": sys.version,
              "container_interpreter": F.interpreter_info(tools["python"]), "toolchain_dir": str(tools["toolchain"]),
              "sub_layout": {P.MARKER: "S3 read target and S2 append target", P.DELETE_ME: "S2 delete target",
                             P.RENAME_SRC: "S2 rename source", "T/" + P.MARKER: "S1 append target"},
              "host_prep_evidence": {"start": host_ev_start, "end": None},
              "host_prep_ran": F.host_prep_observed(host_ev_start), "toolchain_tree_acl_start": tc_tree_start,
              "ui_lockdown": False, "ui_policy": F.UI_POLICY, "ui_lockdown_note": F.UI_LOCKDOWN_NOTE, "token_privileges": token, "security_suite": F.security_suite(), "mxc_state_dir": str(F.mxc_state_dir()), "mxc_state_start": mxc_state(),
              "s5": {"requested": a.s5, "applicable": s5_applicable,
                     "note": None if (s5_applicable or not a.s5) else "S5 not applicable on Tier 1"},
              "options": {"variant": a.variant, "runs": a.runs, "dry_only": a.dry_only, "allow_dacl_tier": a.allow_dacl_tier}}
    (batch / "header.json").write_text(json.dumps(header, indent=1), encoding="utf-8")
    print(json.dumps({"s0": s0, "s0_differs_between_launchers": differs, "s5": header["s5"]}), flush=True)
    rc = 0
    if s0_tier != F.TIER_1 and not a.allow_dacl_tier:
        print(f"STOP: S0 tier {s0_tier} is not {F.TIER_1}; a Tier 2/3 run needs a separate review and --allow-dacl-tier")
        rc = 5
    try:
        if not rc and not a.dry_only:
            c = run_control(batch, tree_base)
            print(json.dumps({"S4_all_landed": c["all_landed"]}), flush=True)
            if not c["all_landed"]:
                print("STOP: control S4 did not land all five attempts (instrument blind)")
                rc = 3
        if not rc and not a.dry_only:
            sm = run_smoke(exe, tools, batch, tree_base, expected_tier, a.allow_dacl_tier, a.keep_tree, a.variant)
            print(json.dumps({"smoke_ok": sm["ok"], "tier": sm["dry_run_selected_tier"], "stop": sm["stop"]}), flush=True)
            if sm["stop"]:
                print(sm["stop"])
                rc = 6
        variants = [] if rc else [a.variant] * a.runs + (["fx-b"] * a.runs if (a.s5 and s5_applicable) else [])
        counts: dict[str, int] = {}
        for v in variants:
            counts[v] = counts.get(v, 0) + 1
            r = run_launch(v, counts[v], exe, tools, batch, tree_base, expected_tier, a.allow_dacl_tier, a.keep_tree, a.dry_only)
            print(json.dumps({"tag": r["tag"], "dry_run_rc": r["dry_run_rc"], "tier": r["dry_run_selected_tier"],
                              "launched": r["launched"], "landed_count": (r["judge"] or {}).get("landed_count"),  # type: ignore[union-attr]
                              "stop": r["stop"]}), flush=True)
            if r["stop"]:
                print(r["stop"])
                rc = 4
                break
    finally:
        for d in (tree_base, a.tree_root):
            try:
                d.rmdir()
            except OSError:
                pass
    header["finished"] = now_iso()
    header["machine_end"] = F.machine_conditions()
    header["mxc_state_end"] = mxc_state()
    host_ev_end = F.host_prep_evidence() | {"at": now_iso()}
    header["host_prep_evidence"]["end"] = host_ev_end  # type: ignore[index]
    header["host_prep_ran"] = F.host_prep_observed(host_ev_start, host_ev_end)
    if not a.dry_only:
        tc_tree_end = F.icacls_save(tools["toolchain"], batch / "toolchain-acl-end.txt") | {"at": now_iso()}
        cmp_ = F.compare_icacls_saves(batch / "toolchain-acl-start.txt", batch / "toolchain-acl-end.txt")
        if not (tc_tree_start or {}).get("saved") or not tc_tree_end["saved"] or (tc_tree_start or {}).get("rc") or tc_tree_end["rc"]:
            cmp_["unchanged"] = None
        header["toolchain_tree_acl_end"] = tc_tree_end
        (batch / "batch-record.json").write_text(json.dumps({
            "state": "BATCH", "variant": a.variant, "tag": "batch", "toolchain_tree_unchanged": cmp_["unchanged"],
            "toolchain_tree_differences": cmp_["differences"], "toolchain_tree_compare": cmp_,
            "start": tc_tree_start, "end": tc_tree_end}, indent=1), encoding="utf-8")
    (batch / "header.json").write_text(json.dumps(header, indent=1), encoding="utf-8")
    if not a.dry_only:
        v = S.verdict(S.load(batch), expected_tier)
        (batch / "summary.json").write_text(json.dumps(v, indent=1), encoding="utf-8")
        print(f"VERDICT: {v['verdict']}")
        if v["verdict"] == "STOPPED-STATE-CHANGE" and not rc:
            rc = 4
    return rc


if __name__ == "__main__":
    sys.exit(main())
