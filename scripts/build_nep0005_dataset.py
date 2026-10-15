"""Build the NEP-0005 half-set study tables for the public Hugging Face dataset (#1771).

Reads the sanitised run records of the study under ``docs/research/containment-evidence-2026-10-05/`` and writes
CSV tables, ``manifest.json`` and ``CARD_SECTION.md`` to ``--out`` (default: ``<study>/hf-export/``). The output
is a pure function of the input bytes: no clock, no random, no environment, sorted file order, LF line endings.

Tables (one row per state per pass unless noted):

* ``nep5_state_passes.csv``   the 45 matrix records (R0-R7, O1-O6, N1; three passes each)
* ``nep5_probes.csv``         every account connect of the matrix, before the filters and with the state in place
* ``nep5_n1_passes.csv``      the non-elevated add and delete verdicts of N1
* ``nep5_phases.csv``         one row per run file: times, exit code, session restore
* ``srtcli_states.csv``       srt-win's own command line: the four half-set states per build and pass
* ``srtcli_commands.csv``     the plain re-install and the ``--force`` restore after each state
* ``srtcli_cycles.csv``       install, positive control and post-uninstall direct checks, per build and pass
* ``arm2_hold_samples.csv``   the 120 once-a-minute probes of the 7,200 s hold
* ``arm_runs.csv``            arm 2 hold, arm 3a, the refused and the successful arm 3b arming and the post-restart check

Free text is never copied: harness stdout, command lines, error text, environment values, paths and the srt-win
message text are all dropped; the cells are enumerated words, counts, codes, timestamps and hashes
(``hf_publish.NEP5_COLUMNS`` carries the reason for each column). Message text is reduced to substring flags.
Every source file is hashed after LF normalisation and listed in the manifest with where its expected value comes from:
the five phase files against ``results-summary.json``, ``results-summary.json`` and ``srtcli-results-summary.json``
against the sha256 ``AS_RUN.md`` records for them, and the arm 2 and arm 3 records against ``PINNED_SHA256``. A mismatch
aborts the build. ``AS_RUN.md`` is the root of trust for those two hashes and has no pin of its own: ``AS_RUN_ANCHORS``
names the one row each hash is read from (the ``results-summary.json`` table row; the ``srtcli-results-summary.json``
"Repository copy" sentence), a missing row or a second matching row stops the build, and the manifest's ``hash_anchor``
records ``AS_RUN.md``'s sha256, its size and the line each value was read from. Anyone who edits a summary file and
``AS_RUN.md`` together defeats this comparison; the edit shows in the diff of ``AS_RUN.md``. ``--out`` may be absent,
empty or hold only files of a previous build.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
STUDY = REPO / "docs" / "research" / "containment-evidence-2026-10-05"
NEP = STUDY / "nep0005-open-questions" / "runs"
ARM2 = STUDY / "arm2-hold" / "runs"
ARM3 = STUDY / "arm3-persist" / "runs"
DEFAULT_OUT = STUDY / "hf-export"
SCHEMA = "nep0005-halfset-export-v1"  # equals hf_publish.NEP5_SCHEMA (a test holds them together)
# The table the dataset viewer shows first for the config (the study's headline); hf_publish.py plan reads it from the manifest.
HF_DEFAULT_DATA_FILE = "srtcli_states.csv"

# Source records with no hash anywhere else in the study: sha256 of the LF-normalised bytes, by file name.
# pinned 2026-10-14 from the committed files
PINNED_SHA256 = {
    "hold-on-20261011-144844.json": "123643dac8898a59775444a9ede4fcea1b65ead77fe0433b8377612925eb2473",
    "arm3a-20261011-165130.json": "3bd8a590f493d703f79c29d1821deeab780fdd2fb8e5148b2b610d1f1823cce5",
    "arm3b-post-reboot-result-20261012-150113.json": "0c92b0e2a19da87ce49af21f3b3c4379d827c2c0005725551a5ec2c6ed68eb89",
    "arm3b-arm-refused-20261012-143857.json": "8fea4048b3abc68a5215915dd244b8a3eb9a6086b0fe9b41ee93ec20db4d48c6",
    "arm3b-armed-20261012-144923.json": "b8d300374d9ed8e930f0e49146f7168ba0b06325894f719a8db39a7c453cf6bf",
}

PHASE_FILES = {  # phase word -> (results-summary files key, file name)
    "halfset": ("halfset", "halfset-20261013-104631.json"),
    "ours": ("ours", "ours-20261013-104930.json"),
    "n1": ("n1", "n1-20261013-105127.json"),
    "taskcheck-first": ("taskcheck_first", "taskcheck-first-20261013-102658.json"),
    "taskcheck-second": ("taskcheck_second", "taskcheck-20261013-104554.json"),
}
MATRIX_PHASES = ("halfset", "ours", "n1")


class BuildError(RuntimeError):
    pass


def _lf_bytes(path: Path) -> bytes:
    return path.read_bytes().replace(b"\r\n", b"\n")


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _load(path: Path) -> dict:
    return json.loads(_lf_bytes(path).decode("utf-8"))


def _cell(v) -> str:
    if v is None:
        return ""
    if isinstance(v, bool):
        return "True" if v else "False"
    return str(v)


def _csv(columns: list[str], rows: list[dict]) -> bytes:
    buf = io.StringIO(newline="")
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(columns)
    for r in rows:
        extra = set(r) - set(columns)
        if extra:
            raise BuildError(f"row carries columns outside the table: {sorted(extra)}")
        w.writerow([_cell(r.get(c)) for c in columns])
    return buf.getvalue().encode("utf-8")


def _count(rows, key, value) -> int:
    return sum(1 for r in rows if r.get(key) == value)


# --------------------------------------------------------------------------------------------- matrix

STATE_COLUMNS = [
    "state_id", "phase", "pass_no", "record_class", "started", "finished", "srt_status_word",
    "s1_filters", "s2_filters", "s3_filters", "our_keys_state", "attempt_status", "attempt_code",
    "acct_before_open", "acct_during_open", "acct_during_blocked", "op_outside_ok", "op_before_ok", "op_during_ok",
    "probe_ms_min", "probe_ms_max", "wd_connects", "wd_failures", "removal_ok", "sweep_after_clean",
    "provider_present_after", "filters_left_after", "export_hits_total", "export_after_sha256",
]
PROBE_COLUMNS = ["state_id", "pass_no", "probe_when", "target", "result", "win32", "probe_ms"]
N1_COLUMNS = ["pass_no", "add_class", "add_code", "add_phase", "add_filter_present_after",
              "delete_class", "delete_code", "delete_phase", "delete_filter_still_present"]
PHASE_COLUMNS = ["phase", "source_file", "started", "finished", "exit_code", "records", "passes",
                 "task_restored", "definition_matches", "reprovision_exit", "files_left"]
_STATUS_RE = re.compile(r"^(?P<word>\w+)(?::\s*\w+)?\s*(?P<code>0x[0-9A-Fa-f]+)?")


def _attempt(add: dict) -> tuple[str, str]:
    d = add.get("Detail") or add
    attempts = d.get("Attempts") or []
    if len(attempts) > 1:
        raise BuildError(f"more than one add attempt in a record ({len(attempts)}); the table holds one")
    if not attempts:
        return "", ""
    status = str(attempts[0].get("status", ""))
    word = status.split(":", 1)[0].strip().split(" ", 1)[0]
    m = re.search(r"0x[0-9A-Fa-f]{8}", status)
    return word, m.group(0) if m else ""


def _target(row: dict) -> str:
    return f"{row['family']}:{row['port']}"


def matrix_rows(records_by_phase: dict[str, list[dict]]) -> tuple[list[dict], list[dict], list[dict]]:
    states: list[dict] = []
    probes: list[dict] = []
    n1: list[dict] = []
    for phase in MATRIX_PHASES:
        for r in records_by_phase[phase]:
            s = r["steps"]
            ctl = s.get("control") or {}
            dur = s.get("during") or {}
            before = (ctl.get("account") or {}).get("Rows") or []
            during = (dur.get("account") or {}).get("Rows") or []
            after = s.get("sweep_after") or {}
            subl = after.get("sublayers") or {}
            enum = (s.get("readings") or {}).get("enum") or {}
            wd = s.get("watchdog") or {}
            att_status, att_code = _attempt(s.get("add") or {})
            ms = [x["ms"] for x in during]
            exp = after.get("export") or {}
            states.append({
                "state_id": r["state"], "phase": phase, "pass_no": r["pass"], "record_class": r["class"],
                "started": r["started"], "finished": r["finished"],
                "srt_status_word": (s.get("readings") or {}).get("status_word"),
                "s1_filters": (enum.get("S1") or {}).get("n"), "s2_filters": (enum.get("S2") or {}).get("n"),
                "s3_filters": (enum.get("S3") or {}).get("n"),
                "our_keys_state": ((s.get("readings") or {}).get("our_keys") or {}).get("state"),
                "attempt_status": att_status or None, "attempt_code": att_code or None,
                "acct_before_open": _count(before, "result", "connected") if before else None,
                "acct_during_open": _count(during, "result", "connected") if during else None,
                "acct_during_blocked": _count(during, "result", "blocked") if during else None,
                "op_outside_ok": sum(1 for x in ctl["operator_outside"] if x) if "operator_outside" in ctl else None,
                "op_before_ok": sum(1 for x in (ctl.get("operator_loopback") or {}).get("Rows", []) if x["ok"]) if ctl else None,
                "op_during_ok": sum(1 for x in (dur.get("operator_loopback") or {}).get("Rows", []) if x["ok"]) if dur else None,
                "probe_ms_min": min(ms) if ms else None, "probe_ms_max": max(ms) if ms else None,
                "wd_connects": wd.get("connects"), "wd_failures": wd.get("failures"),
                "removal_ok": (s.get("removal") or {}).get("ok"), "sweep_after_clean": after.get("clean"),
                "provider_present_after": after.get("provider_present"),
                "filters_left_after": sum(len((subl.get(k) or {}).get("filter_keys") or []) for k in ("S1", "S2", "S3")),
                "export_hits_total": (exp.get("hits") or {}).get("total"),
                "export_after_sha256": (exp.get("sha256") or "").lower() or None,
            })
            for when, rows in (("before", before), ("during", during)):
                for x in rows:
                    probes.append({"state_id": r["state"], "pass_no": r["pass"], "probe_when": when,
                                   "target": _target(x), "result": x["result"], "win32": x["win32"], "probe_ms": x["ms"]})
            if phase == "n1":
                a, d = s["n1_add"], s["n1_delete"]
                n1.append({
                    "pass_no": r["pass"], "add_class": a["class"], "add_code": a["code"], "add_phase": a["direct"]["phase"],
                    "add_filter_present_after": a["filter_present_after"],
                    "delete_class": d["class"], "delete_code": d["code"], "delete_phase": d["direct"]["phase"],
                    "delete_filter_still_present": d["filter_still_present"],
                })
    return states, probes, n1


def _session_exit(d: dict, fname: str) -> dict:
    """The session-end block of a phase file: at the top level, else the one every record carries in its steps.
    Records that carry one must agree; none found is an error (never a default)."""
    if "session_exit" in d:
        return d["session_exit"]
    found = [r["steps"]["session_exit"] for r in d["records"] if "session_exit" in r["steps"]]
    if not found:
        raise BuildError(f"{fname}: no session_exit at the top level or in any record's steps")

    def key(x: dict) -> tuple:
        return (x["TaskRestored"], x["DefinitionMatches"], x["Reprovision"]["ExitCode"], tuple(x["Files"]["Left"]))

    if len({key(x) for x in found}) != 1:
        raise BuildError(f"{fname}: the session_exit blocks of its records disagree")
    return found[0]


def phase_rows(docs: dict[str, dict]) -> list[dict]:
    out = []
    for phase, (_, fname) in PHASE_FILES.items():
        d = docs[phase]
        se = _session_exit(d, fname)
        out.append({
            "phase": phase, "source_file": fname, "started": d["started"], "finished": d["finished"],
            "exit_code": d["exit_code"], "records": len(d["records"]), "passes": d["passes"],
            "task_restored": se["TaskRestored"], "definition_matches": se["DefinitionMatches"],
            "reprovision_exit": se["Reprovision"]["ExitCode"], "files_left": len(se["Files"]["Left"]),
        })
    return out


# --------------------------------------------------------------------------------------------- srt-win CLI

SRTSTATE_COLUMNS = ["build", "pass_no", "state_id", "srt_status_word", "filters", "has_block_v4", "has_block_v6",
                    "has_permit_v4", "has_permit_v6", "verify_v4_out", "verify_v6_out", "verify_v4_in", "verify_v6_in",
                    "host_check_stock_ts", "host_check_patched_ts"]
SRTCMD_COLUMNS = ["build", "pass_no", "state_id", "step", "exit_code", "ms", "said_installed", "said_already_installed",
                  "said_no_changes", "said_port_range_unknown", "said_filters"]
CYCLE_COLUMNS = ["build", "pass_no", "windows_version", "exe_sha256", "driver_sha256", "install_exit", "install_ms",
                 "ambient_paths", "control_srt_win_hits", "control_s1_hits", "uninstall_clean", "uninstall_exit",
                 "uninstall_ms", "footprint_items_present", "store_dir_present", "store_dir_has_deny_ace", "store_dir_deny_rid",
                 "enum_s1_after", "enum_s2_after", "enum_s3_after", "sweep_count", "wfp_srt_win_hits", "wfp_s1_hits",
                 "wfp_s2_hits", "wfp_s3_hits", "wfp_default_hits", "user_rights_sid_hits", "acl_entries", "acl_sid_hits",
                 "acl_changed"]


_DENY_ACE = re.compile(r"\(D;[^)]*\)")
_DENY_RID = re.compile(r"-(\d+)\)\Z")


def _deny_rid(sddl: str) -> str | None:
    """The relative identifier (last SID component) of the one deny entry of an access list; never the domain."""
    aces = _DENY_ACE.findall(sddl)
    if not aces:
        return None
    if len(aces) != 1:
        raise BuildError(f"{len(aces)} deny entries in a store folder access list; the table holds one identifier")
    m = _DENY_RID.search(aces[0])
    if not m:
        raise BuildError("deny entry of the store folder access list has no relative identifier")
    return m.group(1)


# The srt-win driver ran the in-range ``wfp verify`` only in these states. There the keys are required (a miss raises);
# in every other state they must be absent (a value the table would otherwise drop raises).
IN_RANGE_VERIFY_STATES = frozenset({"F", "HP", "HP-after-reinstall"})


def _in_range(x: dict) -> dict:
    keys = ("verify_v4_in_range", "verify_v6_in_range")
    if x["state"] in IN_RANGE_VERIFY_STATES:
        return {"verify_v4_in": x[keys[0]], "verify_v6_in": x[keys[1]]}
    if any(k in x for k in keys):
        raise BuildError(f"state {x['state']} carries an in-range verify result the table would drop")
    return {"verify_v4_in": None, "verify_v6_in": None}


def srtcli_rows(summary: dict) -> tuple[list[dict], list[dict], list[dict]]:
    states, cmds, cycles = [], [], []
    for b in summary["builds"]:
        build = b["build"]
        for x in b["states"]:
            roles = set(x["roles_present"])
            states.append({
                "build": build, "pass_no": x["pass"], "state_id": x["state"], "srt_status_word": x["srt_status"],
                "filters": x["filters"], "has_block_v4": "block-v4" in roles, "has_block_v6": "block-v6" in roles,
                "has_permit_v4": "permit-v4" in roles, "has_permit_v6": "permit-v6" in roles,
                "verify_v4_out": x["verify_v4_out"], "verify_v6_out": x["verify_v6_out"],
                **_in_range(x),
                "host_check_stock_ts": x["host_check_stock_ts"], "host_check_patched_ts": x["host_check_patched_ts"],
            })
        for step, key in (("reinstall", "reinstalls"), ("restore_force", "restores_force")):
            for x in b[key]:
                said = x.get("srt_win_said", "")
                m = re.search(r"filters=(\d+)", said)
                cmds.append({
                    "build": build, "pass_no": x["pass"], "state_id": x["state"], "step": step, "exit_code": x["exit"],
                    "ms": x["ms"],
                    "said_installed": "installed (" in said.replace("already installed (", "") if said else None,
                    "said_already_installed": "already installed" in said if said else None,
                    "said_no_changes": "no changes" in said if said else None,
                    "said_port_range_unknown": "port_range=<unknown>" in said if said else None,
                    "said_filters": m.group(1) if m else None,
                })
        by_pass_install = {x["pass"]: x for x in b["install"]}
        by_pass_ctl = {x["pass"]: x for x in b["export_positive_controls"]}
        for u in b["after_uninstall"]:
            p = u["pass"]
            fp, ex, acl = u["footprint"], u["wfp_state_export"], u["acl"]
            cycles.append({
                "build": build, "pass_no": p, "windows_version": b["windows_build"],
                "exe_sha256": b["exe_sha256"].lower(), "driver_sha256": b["driver_sha256"].lower(),
                "install_exit": by_pass_install[p]["exit"], "install_ms": by_pass_install[p]["ms"],
                "ambient_paths": by_pass_install[p]["ambient_paths"],
                "control_srt_win_hits": by_pass_ctl[p]["srt_win"], "control_s1_hits": by_pass_ctl[p]["s1"],
                "uninstall_clean": u["clean"], "uninstall_exit": u["uninstall_exit"], "uninstall_ms": u["uninstall_ms"],
                "footprint_items_present": sum(1 for v in fp.values() if v), "store_dir_present": fp["store_dir"],
                "store_dir_has_deny_ace": "(D;" in u["store_dir_sddl"],
                "store_dir_deny_rid": _deny_rid(u["store_dir_sddl"]),
                "enum_s1_after": u["enum_counts_s1_s2_s3"][0], "enum_s2_after": u["enum_counts_s1_s2_s3"][1],
                "enum_s3_after": u["enum_counts_s1_s2_s3"][2], "sweep_count": u["sweep_count"],
                "wfp_srt_win_hits": ex["srt_win"], "wfp_s1_hits": ex["s1"], "wfp_s2_hits": ex["s2"],
                "wfp_s3_hits": ex["s3"], "wfp_default_hits": ex["default_sublayer"],
                "user_rights_sid_hits": u["user_rights_sid_hits"], "acl_entries": acl["entries"],
                "acl_sid_hits": acl["sid_hits"], "acl_changed": acl["changed"],
            })
    return states, cmds, cycles


# --------------------------------------------------------------------------------------------- arms 2 and 3

SAMPLE_COLUMNS = ["run_id", "sample_n", "t", "offset_s", "outcome", "error_code", "probe_ms"]
ARM_COLUMNS = ["arm", "run_id", "source_file", "started", "finished", "exit_code", "windows_build", "bitdefender_processes",
               "uptime_h", "filter_set", "hold_seconds", "samples_expected", "samples_blocked", "samples_open",
               "wd_connects", "wd_failures", "objects_existed_s", "uptime_s", "reboot_confirmed", "fence_state",
               "all_persistent", "probe_blocked", "probe_error_code", "removal_verified", "guard_refused_after_removal"]


def _build_word(env: dict) -> str:
    return env["windows_build"].split(" ", 1)[0]


def arm_rows(hold: dict, a3a: dict, a3b: dict, refused: dict, armed: dict) -> tuple[list[dict], list[dict]]:
    samples = [{"run_id": hold["run_id"], "sample_n": x["n"], "t": x["t"], "offset_s": x["offset_s"],
                "outcome": x["outcome"], "error_code": x["error_code"], "probe_ms": x["probe_ms"]}
               for x in hold["samples"]]
    st, ds = hold["sample_stats"], hold["decision_inputs"]
    wd2 = hold["steps"]["watchdog"]
    runs = [{
        "arm": "arm2", "run_id": hold["run_id"], "source_file": "hold-on-20261011-144844.json",
        "started": hold["started"], "finished": hold["finished"], "exit_code": hold["exit_code"],
        "windows_build": _build_word(hold["env"]), "bitdefender_processes": len(hold["env"]["bitdefender_processes"]),
        "uptime_h": hold["env"]["uptime_hours"], "filter_set": hold["filter_set"], "hold_seconds": hold["hold_seconds"],
        "samples_expected": ds["SamplesExpected"], "samples_blocked": st["blocked"], "samples_open": st["open"],
        "wd_connects": wd2["connects"], "wd_failures": wd2["failures"],
        "objects_existed_s": hold["steps"]["filters_stood_seconds"], "removal_verified": ds["RemovalVerified"],
    }]
    s = a3a["steps"]
    runs.append({
        "arm": "arm3a", "run_id": a3a["run_id"], "source_file": "arm3a-20261011-165130.json",
        "started": a3a["started"], "finished": a3a["finished"], "exit_code": a3a["exit_code"],
        "windows_build": _build_word(a3a["env"]), "bitdefender_processes": len(a3a["env"]["bitdefender_processes"]),
        "uptime_h": a3a["env"]["uptime_hours"], "wd_connects": s["watchdog"]["connects"],
        "wd_failures": s["watchdog"]["failures"], "objects_existed_s": s["objects_existed_seconds"],
        "fence_state": s["fence_during"]["State"], "all_persistent": s["fence_during"]["AllPersistent"],
        "probe_blocked": s["account_under_fence"]["run"]["outbound_probe"]["blocked"],
        "probe_error_code": s["account_under_fence"]["run"]["outbound_probe"]["probe"]["error_code"],
        "removal_verified": a3a["decision_inputs"]["RemovalVerified"],
        "guard_refused_after_removal": a3a["decision_inputs"]["GuardRefusedAfterRemoval"],
    })
    s = a3b["steps"]
    pr = s["account_probe_under_fence"]["run"]["outbound_probe"]
    runs.append({
        "arm": "arm3b", "run_id": a3b["run_id"], "source_file": "arm3b-post-reboot-result-20261012-150113.json",
        "started": a3b["started"], "finished": a3b["finished"], "exit_code": a3b["exit_code"],
        "windows_build": _build_word(s["env"]), "bitdefender_processes": len(s["env"]["bitdefender_processes"]),
        "uptime_h": s["env"]["uptime_hours"], "objects_existed_s": s["objects_existed_seconds"],
        "uptime_s": s["uptime_seconds"], "reboot_confirmed": s["reboot_confirmed"],
        "fence_state": s["fence_state_at_start"]["State"], "all_persistent": s["fence_state_at_start"]["AllPersistent"],
        "probe_blocked": pr["blocked"], "probe_error_code": pr["probe"]["error_code"],
        "removal_verified": a3b["decision_inputs"]["RemovalVerified"],
        "guard_refused_after_removal": a3b["decision_inputs"]["GuardRefusedAfterRemoval"],
    })
    runs.append({
        "arm": "arm3b-arming-refused", "source_file": "arm3b-arm-refused-20261012-143857.json",
        "finished": refused["finished"], "exit_code": refused["exit_code"],
        "fence_state": refused["steps"]["fence_before"]["State"],
    })
    runs.append({"arm": "arm3b-armed", "source_file": "arm3b-armed-20261012-144923.json", "started": armed["armed_at"]})
    order = ("arm2", "arm3a", "arm3b-arming-refused", "arm3b-armed", "arm3b")
    runs.sort(key=lambda r: order.index(r["arm"]))
    return samples, runs


# --------------------------------------------------------------------------------------------- build

AS_RUN_FILE = "nep0005-open-questions/runs/AS_RUN.md"  # under STUDY; the manifest's ``hash_anchor`` names it
AS_RUN_ANCHORS = {  # summary file -> (pattern of the one AS_RUN.md row its expected sha256 is read from, what the row is)
    "results-summary.json": (
        r"\| `results-summary\.json` \| [\d,]+ \| `([0-9a-f]{64})`",
        "the table row whose first cell is the file name, then its byte count, then its sha256"),
    "srtcli-results-summary.json": (
        r"`srtcli-results-summary\.json` \(\d+ bytes, sha256 `([0-9a-f]{64})`",
        "the 'Repository copy' sentence: the file name, its byte count and its sha256"),
}


def _recorded_in_as_run() -> tuple[dict[str, str], dict]:
    """The sha256 values AS_RUN.md records for the two summary files, read from the one row each anchor matches, and the
    anchor record for the manifest (AS_RUN.md's own hash and size and the line each value was read from). No row, or more
    than one row (whatever their values), stops the build: AS_RUN.md is the run's own record and carries no pin of its own."""
    data = _lf_bytes(NEP / "AS_RUN.md")
    text = data.decode("utf-8")
    out: dict[str, str] = {}
    lines: dict[str, int] = {}
    for name, (pat, _) in AS_RUN_ANCHORS.items():
        found = list(re.finditer(pat, text))
        if not found:
            raise BuildError(f"AS_RUN.md records no sha256 for {name}")
        if len(found) > 1:
            where = ", ".join(str(text.count("\n", 0, m.start()) + 1) for m in found)
            raise BuildError(f"AS_RUN.md has {len(found)} rows for {name} (lines {where}); exactly one is required")
        out[name] = found[0].group(1)
        lines[name] = text.count("\n", 0, found[0].start()) + 1
    anchor = {"file": AS_RUN_FILE, "bytes": len(data), "sha256": _sha(data),
              "rows": {name: {"line": lines[name], "row_is": AS_RUN_ANCHORS[name][1]} for name in AS_RUN_ANCHORS}}
    return out, anchor


def build(out: Path) -> dict[str, bytes]:
    files: dict[str, bytes] = {}
    sources: list[dict] = []

    def src(path: Path, origin: str, expect: str | None) -> dict:
        data = _lf_bytes(path)
        h = _sha(data)
        if expect is None:
            raise BuildError(f"{path.name}: no expected sha256")
        if h != expect:
            raise BuildError(f"{path.name}: sha256 {h} differs from the recorded {expect}")
        try:
            shown = path.relative_to(STUDY).as_posix()
        except ValueError:
            shown = path.name
        sources.append({"file": shown, "bytes": len(data), "sha256": h, "sha256_origin": origin})
        return json.loads(data.decode("utf-8"))

    as_run, as_run_anchor = _recorded_in_as_run()

    def from_as_run(name: str) -> str:
        return f"AS_RUN.md line {as_run_anchor['rows'][name]['line']} records this value (compared at build; see hash_anchor)"

    pinned = "pinned in scripts/build_nep0005_dataset.py (2026-10-14, from the committed files)"
    rs = src(NEP / "results-summary.json", from_as_run("results-summary.json"), as_run["results-summary.json"])
    docs: dict[str, dict] = {}
    for phase, (key, fname) in PHASE_FILES.items():
        docs[phase] = src(NEP / fname, f"results-summary.json files.{key}.sanitised_sha256 (compared at build)",
                          rs["files"][key]["sanitised_sha256"])
    records_by_phase = {p: docs[p]["records"] for p in MATRIX_PHASES}
    srt = src(NEP / "srtcli-results-summary.json", from_as_run("srtcli-results-summary.json"), as_run["srtcli-results-summary.json"])
    hold, a3a, a3b, refused, armed = (
        src(base / name, pinned, PINNED_SHA256[name]) for base, name in (
            (ARM2, "hold-on-20261011-144844.json"), (ARM3, "arm3a-20261011-165130.json"),
            (ARM3, "arm3b-post-reboot-result-20261012-150113.json"), (ARM3, "arm3b-arm-refused-20261012-143857.json"),
            (ARM3, "arm3b-armed-20261012-144923.json")))
    sources.sort(key=lambda s: s["file"])

    states, probes, n1 = matrix_rows(records_by_phase)
    srt_states, srt_cmds, srt_cycles = srtcli_rows(srt)
    samples, runs = arm_rows(hold, a3a, a3b, refused, armed)
    tables = {
        "nep5_state_passes.csv": (STATE_COLUMNS, states),
        "nep5_probes.csv": (PROBE_COLUMNS, probes),
        "nep5_n1_passes.csv": (N1_COLUMNS, n1),
        "nep5_phases.csv": (PHASE_COLUMNS, phase_rows(docs)),
        "srtcli_states.csv": (SRTSTATE_COLUMNS, srt_states),
        "srtcli_commands.csv": (SRTCMD_COLUMNS, srt_cmds),
        "srtcli_cycles.csv": (CYCLE_COLUMNS, srt_cycles),
        "arm2_hold_samples.csv": (SAMPLE_COLUMNS, samples),
        "arm_runs.csv": (ARM_COLUMNS, runs),
    }
    outputs = []
    for name in sorted(tables):
        cols, rows = tables[name]
        files[name] = _csv(cols, rows)
        outputs.append({"file": name, "rows": len(rows), "sha256": _sha(files[name])})

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import nep0005_card_section as card  # noqa: E402

    files["CARD_SECTION.md"] = card.render(tables, srt, hold, a3a, a3b, rs).encode("utf-8")
    outputs.append({"file": "CARD_SECTION.md", "rows": None, "sha256": _sha(files["CARD_SECTION.md"])})
    outputs.sort(key=lambda o: o["file"])

    manifest = {
        "kind": "nep0005-hf-export-manifest",
        "schema": SCHEMA,
        "ticket": "#1771",
        "built_by": "scripts/build_nep0005_dataset.py",
        "hf_default_data_file": HF_DEFAULT_DATA_FILE,
        "cited_repository_paths": [card.MATRIX_SCRIPTS_PATH.rstrip("/")],
        "hash_anchor": as_run_anchor,
        "sources": sources,
        "outputs": outputs,
        "row_counts": {o["file"]: o["rows"] for o in outputs if o["rows"] is not None},
    }
    files["manifest.json"] = (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode("utf-8")
    for data in files.values():  # no output file cites a commit of the unpublished history
        card.refuse_commit_ids(data.decode("utf-8"))
    return files


def write(out: Path, files: dict[str, bytes]) -> None:
    out.mkdir(parents=True, exist_ok=True)
    stray = sorted(p.name for p in out.iterdir() if p.name not in files)
    if stray:
        raise BuildError(f"{out} holds files this build does not write: {stray}")
    for name, data in files.items():
        (out / name).write_bytes(data)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = ap.parse_args(argv)
    try:
        files = build(args.out)
        write(args.out, files)
    except (BuildError, KeyError) as e:
        print(f"build_nep0005_dataset: refused: {e}", file=sys.stderr)
        return 1
    for name in sorted(files):
        print(f"{name}: {len(files[name])} bytes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
