"""Dataset-card section for the NEP-0005 half-set study (#1771), rendered from the built tables.

Used by ``build_nep0005_dataset.py``. Counts, ranges and pass tallies are computed from the table rows: they come
from ``_q`` selections over the same rows that are written to the CSV files. The figures that are not (read from the run
records, or typed from the run notes) are listed in the section's own provenance sentence, and nowhere else. The prose
around the figures states what the rows show and names what they do not. Lines are wrapped under the publisher's cap.
"""

from __future__ import annotations

import re
import textwrap
from datetime import datetime

WRAP = 112
HEADING_TEXT = "NEP-0005 half-set study: Windows Filtering Platform loopback fence (config `nep0005_halfset`)"
SRT_WIN_PIN = "24eb39e94a6de386e83d126c52317d8e0fa49522"
MATRIX_SCRIPTS_PATH = "docs/research/containment-evidence-2026-10-05/nep0005-open-questions/scripts/"
# A commit id other than the upstream pin: a run of 7 to 40 hex characters with a digit and a letter, any case, bounded
# by non-hex characters (so ``commit716fd87a`` and ``716fd87a_x`` match; a longer hex run such as a sha256 does not) and
# not the digits of a ``0x`` status code. The pin is compared lower-cased. Shapes that also match and are refused (the
# renderer raises): a seven-letter-and-digit word such as ``decade1``, a number such as ``1e10ab7``, an abbreviated pin.
_COMMIT_ID = re.compile(r"(?<![0-9a-fA-F])(?<!0x)(?=[0-9a-fA-F]*\d)(?=[0-9a-fA-F]*[a-fA-F])[0-9a-fA-F]{7,40}(?![0-9a-fA-F])")


def refuse_commit_ids(text: str) -> str:
    """Return ``text`` unchanged, or raise ValueError when it carries a commit id other than ``SRT_WIN_PIN``."""
    found = sorted({m.group(0) for m in _COMMIT_ID.finditer(text) if m.group(0).lower() != SRT_WIN_PIN})
    if found:
        raise ValueError(f"the card section cites a commit id that a public reader cannot resolve: {found}")
    return text


def _q(rows: list[dict], **want) -> list[dict]:
    return [r for r in rows if all(r.get(k) == v for k, v in want.items())]


def _tally(rows: list[dict], key: str) -> str:
    seen: dict = {}
    for r in rows:
        seen[r.get(key)] = seen.get(r.get(key), 0) + 1
    return ", ".join(f"{'(none)' if k is None else k} (x{v})" for k, v in sorted(seen.items(), key=lambda kv: str(kv[0])))


def _of(n_ok: int, n: int) -> str:
    return f"{n_ok} of {n}"


def _para(text: str, indent: str = "") -> str:
    return "\n".join(textwrap.wrap(text, WRAP, initial_indent=indent, subsequent_indent=" " * len(indent),
                                   break_long_words=False, break_on_hyphens=False))


def render(tables: dict, srt: dict, hold: dict, a3a: dict, a3b: dict, rs: dict) -> str:
    rows = {name: r for name, (_, r) in tables.items()}
    sp, pr, n1 = rows["nep5_state_passes.csv"], rows["nep5_probes.csv"], rows["nep5_n1_passes.csv"]
    ph, ss = rows["nep5_phases.csv"], rows["srtcli_states.csv"]
    sc, cy = rows["srtcli_commands.csv"], rows["srtcli_cycles.csv"]
    smp, runs = rows["arm2_hold_samples.csv"], rows["arm_runs.csv"]
    cyc = [r for r in sp if r["state_id"] != "N1"]
    during = _q(pr, probe_when="during")
    before = _q(pr, probe_when="before")
    states_m = sorted({r["state_id"] for r in sp})
    ms = [r["probe_ms"] for r in during]
    stock_cmds = _q(sc, build="stock")
    ports = sorted({r["target"].split(":")[1] for r in pr}, key=int)
    ports_text = ", ".join(ports[:-1]) + " and " + ports[-1]
    n_targets = len({r["target"] for r in pr})
    hold_ms = [r["probe_ms"] for r in smp]
    out: list[str] = []
    w = out.append

    def tgt(state: str, *, result: str) -> str:
        sel = [r for r in during if r["state_id"] == state and r["result"] == result]
        return ", ".join(sorted({r["target"] for r in sel})) or "none"

    def uniq_passes(state: str, key: str) -> str:
        return _tally(_q(sp, state_id=state), key)

    def verify_text(sel: list[dict]) -> str:
        """The out-of-range verify tallies and, where the driver ran it for the state, the in-range ones beside them."""
        text = f"verify v4 out {_tally(sel, 'verify_v4_out')}, v6 out {_tally(sel, 'verify_v6_out')}"
        if any(r.get("verify_v4_in") is not None or r.get("verify_v6_in") is not None for r in sel):
            text += f", v4 in range {_tally(sel, 'verify_v4_in')}, v6 in range {_tally(sel, 'verify_v6_in')}"
        return text

    w(f"## {HEADING_TEXT}")
    w("")
    w(_para("This section holds the data behind a set of claims about how a half-installed Windows Filtering Platform "
            "(WFP) set reports, whether a plain re-install repairs it, and what a standard (non-administrator) token can "
            "change. Every count, range and tally below is computed from the CSV tables in this folder by the script that "
            "built them (`scripts/build_nep0005_dataset.py`), except these. Read from the run records, not the tables: "
            f"the {hold['hold_seconds']} s hold length and the exit code of the stopped first cycle. "
            "Typed from the run notes: the machine and Windows description, the pinned srt-win commit, the permit range, "
            "the probe address 1.1.1.1:443, the 600 s restart delay, the -04:00 offset and the pre-registered design. "
            "On this machine, under these conditions, and nothing wider. The tables hold counts, codes, enumerated "
            "words, timestamps and hashes. They hold no program output text, no path and no name."))
    w("")
    w("### Setup and methodology")
    w("")
    w("- Machine: Intel Core Ultra 7 258V (Lunar Lake) laptop, 31.3 GB; the Intel Arc 140V iGPU is present and unused here.")
    w("- Windows 11 Pro 10.0.26200, display version 25H2, build 26200.9457 (arm tables record `windows_build`).")
    w("- OpenVINO, GenAI, GPU driver and model: not applicable. No model runs in this study.")
    w(_para("Pinned source: the srt-win library of anthropics/sandbox-runtime at commit "
            f"{SRT_WIN_PIN} (not a model revision). Matrix scripts: `{MATRIX_SCRIPTS_PATH}` "
            "(repository-relative path; the public snapshot carries the same files).", "- "))
    w(_para(f"Matrix (`nep5_state_passes.csv`, `nep5_probes.csv`, `nep5_n1_passes.csv`): {len(states_m)} states "
            f"({', '.join(states_m)}), three passes each, {len(sp)} records. R-states use srt-win's library on test sublayer "
            "S1; O-states use our own filter objects on test sublayer S2; R7 puts our unlabelled block in S3; N1 is the "
            f"account's own standard token calling the engine directly. Per cycle the account connects to {n_targets} loopback "
            f"targets (v4 and v6 on ports {ports_text}; the permit range is 60080-60089) before any filter and with "
            "the state in place; every state is added and removed by key in the same pass.", "- "))
    w(_para(f"srt-win's own command line (`srtcli_states.csv`, `srtcli_commands.csv`, `srtcli_cycles.csv`): two counted "
            f"runs (stock and patched build), {len(_q(cy, build='stock'))} passes each; per pass the full set F, then the IPv6 block deleted "
            "(H6), the IPv4 block deleted (H4) and both loopback permits deleted (HP), each followed by a plain "
            "`srt-win install` and a `--force` restore, then an uninstall with direct checks. A first cycle that stopped "
            f"on its access-list check (exit {srt['first_cycle']['exit']}) is not in these tables.", "- "))
    w(_para(f"Arms 2 and 3 (`arm2_hold_samples.csv`, `arm_runs.csv`): the {hold['hold_seconds']} s hold with one probe a "
            "minute, the persistent set added and removed (arm 3a) and the post-restart check (arm 3b); the probe is the "
            "account's connect to 1.1.1.1:443 through its scheduled task.", "- "))
    w("")
    w("Tables (rows; the manifest carries the sha256 of each and of every source file):")
    w("")
    w("| Table | Rows | One row is |")
    w("|---|---|---|")
    for name, what in (
        ("nep5_state_passes.csv", "one state in one pass"),
        ("nep5_probes.csv", "one account connect (before or during)"),
        ("nep5_n1_passes.csv", "one N1 pass"),
        ("nep5_phases.csv", "one run file"),
        ("srtcli_states.csv", "one half-set state in one pass of one build"),
        ("srtcli_commands.csv", "one re-install or restore after a state"),
        ("srtcli_cycles.csv", "one install/uninstall cycle of one build"),
        ("arm2_hold_samples.csv", "one once-a-minute probe of the hold"),
        ("arm_runs.csv", "one arm run record"),
    ):
        w(f"| `{name}` | {len(rows[name])} | {what} |")
    w("")
    w("### Conditions")
    w("")
    w(_para(f"Every matrix target is a loopback listener on 127.0.0.1 or [::1]; probe time per connect {min(ms)} to {max(ms)} ms. "
            f"The matrix probes ran through an interactive logon of the test account, not the batch logon of its scheduled "
            f"task. Each state stood for seconds. The three passes of a state ran back to back on one boot. "
            f"Matrix run files: " + "; ".join(f"{r['phase']} {r['started'][11:19]} to {r['finished'][11:19]} (-04:00), exit "
                                              f"{r['exit_code']}" for r in ph[:3]) + ".", "- "))
    w(_para("Bitdefender: not recorded during the matrix and the srt-win command-line runs. Bitdefender processes at "
            f"start: arm 2 {_q(runs, arm='arm2')[0]['bitdefender_processes']}, arm 3a {_q(runs, arm='arm3a')[0]['bitdefender_processes']}; "
            "the arm 3b post-restart check "
            f"records {_q(runs, arm='arm3b')[0]['bitdefender_processes']}. Other machine load: not recorded.", "- "))
    w(_para(f"Account and operator controls: before any filter the account connected to {_of(len(_q(before, result='connected')), len(before))} "
            f"targets; the operator connected {_of(sum(r['op_before_ok'] for r in cyc), n_targets * len(cyc))} loopback targets before and "
            f"{_of(sum(r['op_during_ok'] for r in cyc), n_targets * len(cyc))} during, with {sum(r['wd_failures'] for r in cyc)} "
            "watchdog failures. After every record, removal by key read back ok "
            f"({_of(len(_q(sp, removal_ok=True, sweep_after_clean=True)), len(sp))} records: sweep clean), "
            f"provider present after: {len(_q(sp, provider_present_after=True))}, filters left: "
            f"{sum(r['filters_left_after'] for r in sp)}, export marker hits: {sum(r['export_hits_total'] for r in sp)}.", "- "))
    w("")
    w("### Findings, with the rows that carry them")
    w("")
    w(_para("Each line names its table and filter. A figure is a tally over the rows shown, nothing more. "
            "Passes are repeats on one machine, not independent samples."))
    w("")
    w("**Half-set reporting (srt-win's library, `nep5_state_passes.csv` and `nep5_probes.csv`, during rows)**")
    w("")
    for st, label in (("R2", "IPv4 block deleted"), ("R3", "IPv6 block deleted"), ("R4", "both blocks deleted"),
                      ("R5", "both permits deleted")):
        recs = _q(sp, state_id=st)
        w(_para(f"{st} ({label}): status word {uniq_passes(st, 'srt_status_word')}; filters in S1 {uniq_passes(st, 's1_filters')}; "
                f"targets connected {tgt(st, result='connected')}; targets blocked {tgt(st, result='blocked')} "
                f"({len(recs)} passes).", "- "))
    w(_para(f"R6 (full set keyed to a SID that resolves to no account): status word {uniq_passes('R6', 'srt_status_word')}; "
            f"count of {n_targets} targets the account connected to, per pass: {uniq_passes('R6', 'acct_during_open')}.", "- "))
    w(_para(f"R7 (our unlabelled block in S3, S1 empty): status word {uniq_passes('R7', 'srt_status_word')}; "
            f"count of {n_targets} targets the account was blocked on, per pass: {uniq_passes('R7', 'acct_during_blocked')}.", "- "))
    w("")
    w("**Exact-port permit, refusals and the standard token (same tables; `nep5_n1_passes.csv`)**")
    w("")
    w(_para(f"O4 (administrator-added permit for one exact port beside both blocks): connected {tgt('O4', result='connected')}; "
            f"blocked {tgt('O4', result='blocked')} ({len(_q(sp, state_id='O4'))} passes). Says nothing about who may add a permit.", "- "))
    w(_para(f"O5 (block that names no provider): attempt {uniq_passes('O5', 'attempt_status')}; blocked {tgt('O5', result='blocked')}. "
            f"O6 (filter naming a missing sublayer): attempt {uniq_passes('O6', 'attempt_status')} with code "
            f"{uniq_passes('O6', 'attempt_code')}; count of {n_targets} targets the account connected to, per pass: {uniq_passes('O6', 'acct_during_open')}.", "- "))
    w(_para(f"N1 (account's own standard token, direct single calls): add {_tally(n1, 'add_class')} with code "
            f"{_tally(n1, 'add_code')} (filter present afterwards: {_tally(n1, 'add_filter_present_after')}); delete "
            f"{_tally(n1, 'delete_class')} with code {_tally(n1, 'delete_code')} (test filter still present: "
            f"{_tally(n1, 'delete_filter_still_present')}); {len(n1)} passes. A delegated non-administrator was not tested.", "- "))
    w("")
    w("**srt-win's own command line (`srtcli_states.csv`, `srtcli_commands.csv`)**")
    w("")
    for st, label in (("H6", "IPv6 block deleted"), ("H4", "IPv4 block deleted"), ("HP", "both permits deleted")):
        for b in ("stock", "patched"):
            sel = _q(ss, build=b, state_id=st)
            w(_para(f"{b} build, {st} ({label}), {len(sel)} passes: status word {_tally(sel, 'srt_status_word')}; "
                    f"filters {_tally(sel, 'filters')}; {verify_text(sel)}; "
                    f"host check (stock TypeScript) {_tally(sel, 'host_check_stock_ts')}, "
                    f"(patched) {_tally(sel, 'host_check_patched_ts')}.", "- "))
    for b in ("stock", "patched"):
        for st in ("H6", "H4", "HP"):
            sel = _q(sc, build=b, state_id=st, step="reinstall")
            w(_para(f"{b} build, plain `install` after {st}: exit {_tally(sel, 'exit_code')}; message flags: "
                    f"'already installed' {_tally(sel, 'said_already_installed')}, 'no changes' {_tally(sel, 'said_no_changes')}, "
                    f"'port_range=<unknown>' {_tally(sel, 'said_port_range_unknown')}, filters printed "
                    f"{_tally(sel, 'said_filters')}; state read afterwards ({st}-after-reinstall): status "
                    f"{_tally(_q(ss, build=b, state_id=st + '-after-reinstall'), 'srt_status_word')}, filters "
                    f"{_tally(_q(ss, build=b, state_id=st + '-after-reinstall'), 'filters')}, "
                    f"{verify_text(_q(ss, build=b, state_id=st + '-after-reinstall'))}.", "- "))
    force = [r for r in sc if r["step"] == "restore_force"]
    w(_para(f"`install --force` after a state: exit {_tally(force, 'exit_code')} over {len(force)} restores "
            f"({_tally(force, 'build')}).", "- "))
    w(_para(f"Uninstall (`srtcli_cycles.csv`, {len(cy)} cycles): direct checks clean {_of(len(_q(cy, uninstall_clean=True)), len(cy))}; "
            f"the store folder remained {_of(len(_q(cy, store_dir_present=True)), len(cy))} with a deny entry in its access list "
            f"{_of(len(_q(cy, store_dir_has_deny_ace=True)), len(cy))}; other install footprint items remaining: "
            f"{sum(r['footprint_items_present'] - int(bool(r['store_dir_present'])) for r in cy)}; engine export hits after "
            f"uninstall for srt-win, S1, S2, S3 and the default sublayer: "
            f"{sum(r['wfp_srt_win_hits'] + r['wfp_s1_hits'] + r['wfp_s2_hits'] + r['wfp_s3_hits'] + r['wfp_default_hits'] for r in cy)} in total.", "- "))
    w("")
    w("**Hold and persistence (`arm2_hold_samples.csv`, `arm_runs.csv`)**")
    w("")
    a2 = _q(runs, arm="arm2")[0]
    w(_para(f"Arm 2: filters stood {a2['objects_existed_s']} s; {a2['samples_blocked']} of {a2['samples_expected']} probes "
            f"refused, {a2['samples_open']} connected; error codes {_tally(smp, 'error_code')}; the operator watchdog made "
            f"{a2['wd_connects']} connects with {a2['wd_failures']} failures; Bitdefender processes at start: "
            f"{a2['bitdefender_processes']}; sample offsets {smp[0]['offset_s']} to {smp[-1]['offset_s']} s.", "- "))
    r3a, r3b = _q(runs, arm="arm3a")[0], _q(runs, arm="arm3b")[0]
    w(_para(f"Arm 3a: set present and persistent ({r3a['fence_state']}, all persistent {r3a['all_persistent']}) for "
            f"{r3a['objects_existed_s']} s; account probe refused ({r3a['probe_error_code']}); absence gate refused after removal: "
            f"{r3a['guard_refused_after_removal']}. No restart in 3a.", "- "))
    w(_para(f"Arm 3b: restart confirmed {r3b['reboot_confirmed']}; at {r3b['uptime_s']} s of uptime the set read "
            f"{r3b['fence_state']} (all persistent {r3b['all_persistent']}); account probe refused ({r3b['probe_error_code']}); "
            f"removal verified {r3b['removal_verified']}. That the restart was the issued command is inferred from the 600 s "
            "timing, not recorded.", "- "))
    refused, armed = _q(runs, arm="arm3b-arming-refused")[0], _q(runs, arm="arm3b-armed")[0]
    gap_min = round((datetime.fromisoformat(armed["started"]) - datetime.fromisoformat(refused["finished"])).total_seconds() / 60)
    w(_para(f"Arm 3b arming (`arm_runs.csv`): the first arming attempt finished {refused['finished'][:10]} "
            f"{refused['finished'][11:19]} (exit {refused['exit_code']}, fence {refused['fence_state']} before it); the run that "
            f"armed the set started {armed['started'][11:19]}, {gap_min} minutes later; the post-restart row above reads the "
            f"set {r3b['fence_state']}.", "- "))
    w("")
    w("### Pre-registered limits")
    w("")
    w(_para("The design in the study's `SPEC.md` (first committed before the matrix ran) fixed: three passes per state; "
            "the state list above; loopback listeners only, outside the permit range plus one inside it, on both families; "
            "the account, three test sublayers and one provider as the only objects any script may touch; a clean "
            "direct sweep before every add and after every removal, with a stop on anything else. The scripts were revised "
            "after that commit and before the run; the hashes the run's rollback proof recorded are in `runs/AS_RUN.md`. "
            "Three passes on one machine are repeats, not a variance estimate: 'identical' means identical across those "
            "three.", "- "))
    w("")
    w("### Not measured")
    w("")
    for item in (
        f"Anything beyond loopback: no internet address, no other host, no UDP, no DNS, no ports other than {ports_text} in the matrix.",
        "Real IPv6 egress for any state; another machine or another Windows build.",
        "Persistence or time in the matrix: each state stood seconds; arms 2 and 3 cover the hold and one restart, for one filter shape.",
        "A restart with a half-set in place.",
        "The batch logon of the account's scheduled task under the matrix states (the matrix used an interactive logon).",
        "A delegated non-administrator (the Network Configuration Operators row was not run); a non-elevated `wfp status`.",
        "Traffic a Windows service sends for the account (BITS as LocalSystem, SMB and WebDAV redirectors, out-of-process COM).",
        "The Bitdefender state during the matrix and the command-line runs, and other machine load.",
        "Engine access list or security-descriptor dumps; file ownership; exports while a state stood.",
        "AppContainer and Microsoft Execution Container results are not in these tables.",
        f"Speed: each hold probe took {min(hold_ms)} to {max(hold_ms)} ms (`probe_ms` in `arm2_hold_samples.csv`); this is not a latency measurement.",
    ):
        w(_para(item, "- "))
    w("")
    w("### Licence")
    w("")
    w("Data in this section: CC-BY-4.0 (cc-by-4.0).")
    w("")
    return refuse_commit_ids("\n".join(out))
