"""Verdicts for the MXC loopback-proxy egress probe: per run, per (arm, state) batch, and the output-path guard.

What this measures: nothing; it turns the raw run records into one of HOLD / FAIL / REFUSED / REFUSED-AT-LAUNCH /
INSTRUMENT-BLIND.

Per run (judge_run), in this order:
  INSTRUMENT-BLIND   (first) the record's token mode is `standard` but its recorded token is elevated, not Medium
                     integrity, or unreadable: the run is not a statement about a standard token.
  REFUSED            the dry-run exited non-zero AND MXC's own structured error says the policy was rejected (see
                     REFUSED-AT-LAUNCH for the test); the exact text is in the record. A non-zero dry-run without
                     that is INSTRUMENT-BLIND (LAUNCH-FAILED, NOT ANSWERED).
  FAIL               a run-tagged direct connect reached the second loopback listener (B3), or the container
                     connected to the LAN peer (B4(i)) or to 1.1.1.1:443 (B4(ii)), or the container reports a B3
                     connect that no listener logged (conservative: a connect that succeeded is a reach).
  REFUSED-AT-LAUNCH  the dry-run accepted but the launch itself exited non-zero with no payload report, a
                     non-empty MXC log with no `process created` and no `ProcessExited` event (MXC never started the
                     process), no run-tagged or in-window entry in the proxy log or any listener log, and MXC's own
                     error envelope (JSON with `code`) in the launch's stderr, stdout or MXC log whose code is
                     `policy_validation` (every envelope found; a `backend_error` or any other code beside it
                     disqualifies) AND whose message reads as a rejection; those tails are the reasons, verbatim.
                     Keyword text alone never makes a result: an OS error, a panic or a backend_error whose wording
                     contains "invalid" or "requires" is a failed launch, not a refusal. A non-zero exit with any
                     sign the workload ran or started is INSTRUMENT-BLIND.
  INSTRUMENT-BLIND   the instrument cannot support a HOLD: payload report missing or incomplete, a listener failed
                     its pre-launch host control, B2 did not pass, an unexplained listener or proxy connection
                     after the launch started, a launcher timeout, a B3/B4 not-connected result whose error code is not
                     the enforcement code (a timeout is not a refusal), a direct attempt (B3, B4(i), B4(ii)) whose
                     payload report does not positively show it ran and what code came back, a payload whose own
                     recorded token is not an AppContainer token (or not recorded), an unfenced 1.1.1.1:443 control that did not
                     connect both before and after the launch, or no LAN peer port that the unfenced control could
                     reach (B4(i) NOT-MEASURABLE, never HOLD).
  HOLD               none of the above: B2 passed, B3, B4(i) and B4(ii) each failed with the enforcement code.
                     A HOLD needs, for each of B3, B4(i) and B4(ii), a report showing the attempt ran and its outcome
                     code (an empty or code-less report is no attempt, hence INSTRUMENT-BLIND), a payload token record
                     showing an AppContainer token, a passing B2 positive control (3 of 3 with bytes at the target) and, at batch
                     level, passing unfenced controls (B5).
A refusal is a result whatever the token mode: the dry-run's or the launch's exact text is carried in the reasons and
the record's `token` says under which token it was given. A launch with no payload report and no MXC policy_validation
envelope is INSTRUMENT-BLIND (LAUNCH-FAILED, NOT ANSWERED).
B2 passes only if all three run-tagged requests appear in the proxy log (forwarded, status 200), in the second
listener's log, and as status 200 in the container's report. Enforcement code: WinError 10013 only.
Per batch (judge_batch), in this order: FAIL if any run FAILed; else STOPPED-STATE-CHANGE (never HOLD) when any
run's before/after snapshot differed; else REFUSED / REFUSED-AT-LAUNCH if all runs were; else INSTRUMENT-BLIND if
any run was blind or any unfenced control (B5) failed; else INCOMPLETE below the expected run count; else HOLD if
all runs HOLD; otherwise MIXED (stated, never rounded into one of the others). The expected run count is the
batch header's runs_per_arm (the standalone summariser reads it too); a batch below 3 runs is flagged
`below_spec_n`.

How to run: `python -I summarise.py <output-folder>` rewrites batch-summary.json inside that folder from the
run-*.json and control-b5.json records already there. run_probe.py calls the same functions.
What it writes: batch-summary.json in the given folder only; it refuses a folder inside a git working tree.

NOT MEASURED: any build other than the one(s) run; under a standard token, the WFP filter count (unreadable); behaviour on a host
whose --probe reports host-loopback ingress unsupported (the earlier 26200.9457 condition); an identity-scoped proxy (allowedProxyPeer); the session-isolation
backend; UDP, ICMP or DNS egress under the proxy policy; host-to-container ingress (the doc's own open limitation);
nono under MXC; anything about the fork or any other sandbox. A verdict is a statement about the runs recorded, on
that build, with that policy, and nothing wider.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable
from xml.etree import ElementTree

Rec = dict[str, Any]
B2_EXPECTED = 3
ENFORCEMENT_CODES = frozenset({10013})
CHECKS = frozenset({"fail", "untagged", "nonenforcement", "unfenced", "refused_at_launch", "ran_evidence", "timeout", "mxc_log"})
PROCESS_STARTED = re.compile(r"process created|ProcessExited")
SPEC_N = 3
REFUSAL_TEXT = re.compile(r"refus|reject|not supported|unsupported|not allowed|disallow|requires|invalid|validation failed", re.I)
MXC_ERROR_CODES = frozenset({"malformed_request", "unsupported_containment", "unsupported_phase", "backend_unavailable",
                             "malformed_id", "stale_id", "not_provisioned", "not_started", "already_started",
                             "already_stopped", "policy_validation", "backend_error"})
POLICY_CODE = "policy_validation"


def mxc_errors(*texts: Any) -> list[tuple[str, str]]:
    """(code, message) of every MXC error envelope found in the texts: a JSON object, anywhere in the text, whose
    `code` (top level or under `error`) is one of MXC's documented error codes. Free text is never an envelope."""
    dec, found = json.JSONDecoder(), []

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            code = node.get("code")
            if isinstance(code, str) and code in MXC_ERROR_CODES:
                found.append((code, str(node.get("message", ""))))
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    for text in texts:
        t, i = str(text or ""), 0
        while (i := t.find("{", i)) != -1:
            try:
                obj, end = dec.raw_decode(t, i)
            except ValueError:
                i += 1
                continue
            walk(obj)
            i = end
    return found


def policy_rejection(*texts: Any) -> tuple[bool, list[tuple[str, str]]]:
    """True only when MXC's own structured error says the POLICY was rejected: every envelope found carries code
    `policy_validation` (a backend_error or any other code beside it disqualifies) and at least one message reads as a
    rejection. Keyword text without a `policy_validation` envelope never qualifies. Also returns the envelopes found."""
    errs = mxc_errors(*texts)
    ok = bool(errs) and all(c == POLICY_CODE for c, _ in errs) and any(REFUSAL_TEXT.search(m) for _, m in errs)
    return ok, errs


def direct_attempt_problems(payload: Rec) -> list[str]:
    """Why the payload report does not positively show each direct attempt (B3, B4(i), B4(ii)) ran and what came
    back. An attempt shows it ran with a boolean `connected` and, when not connected, an error name or code; B4(i)
    may instead carry a non-empty `skipped` reason (the harness then reports it NOT-MEASURABLE). Empty or absent
    reports are no attempt."""
    out = []
    for key, label in (("b3", "B3"), ("b4i", "B4(i)"), ("b4ii", "B4(ii)")):
        r = payload.get(key)
        if not r:
            out.append(f"payload report for {label} is {'absent' if r is None else 'empty'}: no direct attempt was recorded")
        elif key == "b4i" and isinstance(r.get("skipped"), str) and r["skipped"]:
            continue
        elif not isinstance(r.get("connected"), bool):
            out.append(f"payload report for {label} has no connected true/false: the attempt is not shown to have run")
        elif r["connected"] is False and "winerror" not in r and "error" not in r:
            out.append(f"payload report for {label} says not connected but carries no outcome code")
    return out


def container_token_problem(payload: Rec) -> str | None:
    """None only when the payload recorded its own token and it is an AppContainer token. A confined launch whose
    workload did not run as an AppContainer (or did not say what it ran as) is not a statement about confinement."""
    t = payload.get("token")
    if not isinstance(t, dict) or "is_appcontainer" not in t:
        return "the container's own token was not recorded in the payload report"
    if t.get("is_appcontainer") is not True:
        return (f"the payload ran with a token that is not an AppContainer token (is_appcontainer="
                f"{t.get('is_appcontainer')!r}, integrity={t.get('integrity_sid')!r}, user={t.get('user_sid')!r})")
    return None


def refuse_git_path(path: Path) -> None:
    """Raise SystemExit unless `path` is outside every git working tree (fail-closed if git cannot answer)."""
    probe = path.resolve()
    while not probe.exists() and probe != probe.parent:
        probe = probe.parent
    base = probe if probe.is_dir() else probe.parent
    try:
        cp = subprocess.run(["git", "-C", str(base), "rev-parse", "--show-toplevel"], capture_output=True,
                            text=True, timeout=30, check=False)
    except (OSError, subprocess.SubprocessError) as exc:
        raise SystemExit(f"REFUSED: cannot determine whether {path} is inside a git working tree ({exc!r})")
    if cp.returncode == 0:
        raise SystemExit(f"REFUSED: output path {path} is inside the git working tree {cp.stdout.strip()}")
    if "not a git repository" not in cp.stderr.lower():
        raise SystemExit(f"REFUSED: git could not classify {path}: {cp.stderr.strip()[:200]}")


def _kind(marker: str, tag: str) -> str | None:
    m = re.fullmatch(re.escape(tag) + r"-(b\d[a-z]*)-\d+", marker or "")
    return m.group(1) if m else None


def _tagged(entries: list[Rec], tag: str) -> list[Rec]:
    return [e for e in entries if str(e.get("marker", "")).startswith(tag + "-")]


def _ts(value: Any) -> datetime | None:
    try:
        return datetime.fromisoformat(str(value))
    except ValueError:
        return None


def _in_window(entry: Rec, launch: Rec) -> bool:
    """True when the entry is stamped at or after the launch start (the listeners stay open until the run record is
    taken); unknowable timestamps count as inside."""
    start, at = _ts(launch.get("started")), _ts(entry.get("ts"))
    if start is None or at is None:
        return True
    return at >= start


def mxc_process_started(log_text: str) -> bool:
    """True when MXC's own log shows it created the process or saw it exit (the workload was launched)."""
    return bool(PROCESS_STARTED.search(log_text or ""))


def _workload_ran(rec: Rec, tag: str) -> bool:
    """Any run-tagged entry, or any non-host-control entry at or after the launch start, in the proxy or target log."""
    launch = rec.get("launch") or {}
    for e in (rec.get("target_log") or []) + (rec.get("proxy_log") or []):
        if str(e.get("marker", "")).startswith(tag + "-"):
            return True
        if not str(e.get("marker", "")).startswith("host-control-") and _in_window(e, launch):
            return True
    return False


def _refused(probe: Rec) -> bool:
    return probe.get("connected") is False and probe.get("winerror") in ENFORCEMENT_CODES


def judge_run(rec: Rec, detect_fail: bool = True, disable: Iterable[str] = ()) -> Rec:
    """Verdict for one run record.

    `detect_fail=False` and `disable` (names from CHECKS) exist only so a self-test can prove each detection is
    load-bearing: with it off, the synthetic record that the detection exists for is not flagged.
    """
    off = set(disable) | ({"fail"} if not detect_fail else set())
    tag = str(rec["tag"])
    dry = rec.get("dry_run") or {}
    tok = rec.get("token") or {}
    out: Rec = {"verdict": None, "reasons": [], "token_mode": tok.get("mode")}
    if tok.get("mode") == "standard":
        if tok.get("is_user_an_admin") or tok.get("elevated") is not False or tok.get("integrity_sid") != "S-1-16-8192":
            out.update(verdict="INSTRUMENT-BLIND",
                       reasons=[f"token mode is standard but the recorded token is not a non-elevated Medium token "
                                f"(IsUserAnAdmin={tok.get('is_user_an_admin')}, elevated={tok.get('elevated')}, "
                                f"integrity={tok.get('integrity_sid')})"])
            return out
    if dry.get("rc") != 0:
        dry_text = (dry.get("stderr") or dry.get("stdout") or "").strip()
        rejected, errs = policy_rejection(dry.get("stderr"), dry.get("stdout"))
        if rejected:
            out["verdict"] = "REFUSED"
            out["reasons"].append(f"dry-run rc={dry.get('rc')}: {dry_text[:300]}")
        else:
            out["verdict"] = "INSTRUMENT-BLIND"
            out["reasons"].append(f"LAUNCH-FAILED, NOT ANSWERED: dry-run rc={dry.get('rc')} without an MXC policy_validation "
                                  f"rejection (MXC error codes seen: {sorted({c for c, _ in errs}) or 'none'}): {dry_text[:300]}")
        return out
    payload = rec.get("payload") or {}
    launch = rec.get("launch") or {}
    target, proxy = _tagged(rec.get("target_log") or [], tag), _tagged(rec.get("proxy_log") or [], tag)
    b3_hits = [e for e in target if _kind(str(e.get("marker")), tag) == "b3"]
    b3p, b4ip, b4ii = payload.get("b3") or {}, payload.get("b4i") or {}, payload.get("b4ii") or {}
    out["b3_listener_hits"] = len(b3_hits)
    out["b3_container"] = {k: b3p.get(k) for k in ("connected", "error", "winerror") if k in b3p}
    out["b4i_container"] = {k: b4ip.get(k) for k in ("connected", "error", "winerror", "skipped") if k in b4ip}
    out["b4ii_container"] = {k: b4ii.get(k) for k in ("connected", "error", "winerror") if k in b4ii}
    fails: list[str] = []
    if b3_hits:
        fails.append(f"B3: {len(b3_hits)} run-tagged direct hit(s) on the second loopback listener")
    if b4ip.get("connected") is True:
        fails.append("B4(i): container connected to the LAN peer")
    if b4ii.get("connected") is True:
        fails.append("B4(ii): container connected to 1.1.1.1:443")
    if b3p.get("connected") is True and not b3_hits:
        fails.append("B3: container reports a connect that no listener logged")
    if "fail" not in off and fails:
        out.update(verdict="FAIL", reasons=fails)
        return out
    out["launch_exit_code"] = launch.get("exit_code")
    if payload and launch.get("exit_code") not in (None, 0):
        out["launcher_nonzero_exit"] = launch.get("exit_code")
    mxc_codes = sorted({c for c, _ in mxc_errors(launch.get("stderr_tail"), launch.get("stdout_tail"), rec.get("mxc_log_tail"))})
    out["mxc_error_codes"] = mxc_codes
    log_full = rec.get("mxc_log_full_text_has_process_start")
    started = bool(log_full) if log_full is not None else mxc_process_started(str(rec.get("mxc_log_tail", "")))
    log_present = bool(str(rec.get("mxc_log_tail", "")).strip())
    out["mxc_process_started"] = started
    if ("refused_at_launch" not in off and not payload and launch.get("exit_code") not in (None, 0)
            and "timeout" not in launch and policy_rejection(launch.get("stderr_tail"), launch.get("stdout_tail"),
                                                             rec.get("mxc_log_tail"))[0]
            and ("mxc_log" in off or (log_present and not started))
            and ("ran_evidence" in off or not _workload_ran(rec, tag))):
        out.update(verdict="REFUSED-AT-LAUNCH",
                   reasons=[f"launch exit_code={launch.get('exit_code')}",
                            f"stderr: {str(launch.get('stderr_tail', ''))[:600]}",
                            f"stdout: {str(launch.get('stdout_tail', ''))[:300]}",
                            f"mxc log tail: {str(rec.get('mxc_log_tail', ''))[-400:]}"])
        return out
    blind: list[str] = []
    hc = rec.get("host_control") or {}
    for name in ("target", "proxy"):
        if hc.get(name) is not True:
            blind.append(f"host control for the {name} listener did not succeed")
    if "timeout" not in off and launch.get("timeout"):
        blind.append("the launch timed out: the container may have outlived the launcher")
    if not payload:
        blind.append("LAUNCH-FAILED, NOT ANSWERED: accepted by the dry-run but no payload report was produced"
                     + (f" (launch exit {launch.get('exit_code')}; MXC error codes seen: {mxc_codes or 'none'}; "
                        f"host-side traffic seen: {_workload_ran(rec, tag)}; "
                        f"MXC log shows the process started: {started}; log present: {log_present}; "
                        f"stderr: {str(launch.get('stderr_tail', ''))[:300]})"
                        if launch.get("exit_code") not in (None, 0) else ""))
    else:
        if "b2" not in payload:
            blind.append("payload report lacks b2")
        blind.extend(direct_attempt_problems(payload))
        if (problem := container_token_problem(payload)):
            blind.append(problem)
    b2_payload = [r for r in (payload.get("b2") or []) if r.get("status") == 200]
    b2_proxy = {e["marker"] for e in proxy if _kind(str(e.get("marker")), tag) == "b2"
                and e.get("outcome") == "forwarded" and e.get("status") == 200}
    b2_target = {e["marker"] for e in target if _kind(str(e.get("marker")), tag) == "b2"}
    out["b2"] = {"container_200": len(b2_payload), "proxy_log": len(b2_proxy), "second_listener_log": len(b2_target)}
    if not (len(b2_payload) == len(b2_proxy) == len(b2_target) == B2_EXPECTED):
        blind.append(f"B2 control not 3 of 3 (container {len(b2_payload)}, proxy log {len(b2_proxy)}, "
                     f"second listener {len(b2_target)})")
    if "untagged" not in off and launch.get("started"):
        stray = [e for e in (rec.get("target_log") or []) + (rec.get("proxy_log") or [])
                 if not str(e.get("marker", "")).startswith("host-control-")
                 and _kind(str(e.get("marker")), tag) != "b2" and _in_window(e, launch)]
        stray = [e for e in stray if e not in b3_hits]
        if stray:
            blind.append(f"{len(stray)} unexplained listener/proxy connection(s) at or after the launch start "
                         f"(first: {json.dumps(stray[0])[:200]})")
    if "nonenforcement" not in off and payload:
        for label, probe in (("B3", b3p), ("B4(i)", b4ip), ("B4(ii)", b4ii)):
            if label == "B4(i)" and b4ip.get("skipped"):
                continue
            if probe and not _refused(probe):
                blind.append(f"{label} not reached but the error is not the enforcement code "
                             f"(error={probe.get('error')}, winerror={probe.get('winerror')}): a timeout or an "
                             f"unreachable is not a refusal")
    gw = rec.get("gateway") or {}
    pre, post = rec.get("unfenced_pre") or {}, rec.get("unfenced_post") or {}
    if "unfenced" not in off and payload:
        if not ((pre.get("c") or {}).get("connected") is True and (post.get("c") or {}).get("connected") is True):
            blind.append("unfenced 1.1.1.1:443 control did not connect both before and after the launch")
        if (not gw.get("port") or b4ip.get("skipped") or not (pre.get("gw") or {}).get("connected") is True
                or not (post.get("gw") or {}).get("connected") is True):
            blind.append("B4(i) NOT-MEASURABLE: no LAN-peer port that the unfenced control reached both before "
                         "and after the launch")
    if blind:
        out.update(verdict="INSTRUMENT-BLIND", reasons=blind)
        return out
    if b3_hits or fails:
        out.update(verdict="UNCLASSIFIED", reasons=fails or ["B3/B4 outcome not a clean refusal"])
        return out
    out.update(verdict="HOLD", reasons=["B2 3 of 3; B3, B4(i), B4(ii) each refused with the enforcement code"])
    return out


# ---------------------------------------------------------------- variant 4: WFP capture analysis

WFP_VERDICTS = ("CAPABILITY-ONLY-SUPPORTED", "FILTERS-PRESENT", "INSTRUMENT-BLIND")


def decode_wfp(raw: bytes) -> str:
    return raw.decode("utf-16" if raw[:2] in (b"\xff\xfe", b"\xfe\xff") else "utf-8-sig", errors="replace")


def wfp_filters(xml_text: str) -> dict[str, Rec]:
    """Filters of a `netsh wfp show filters` document, keyed by filterKey: name, layer, action and the full text of
    the filter (every condition value is text in the document, so a SID is found by string search). Raises ValueError
    for a document that is not a filter list."""
    try:
        root = ElementTree.fromstring(xml_text.lstrip("\ufeff").encode("utf-8"))
    except ElementTree.ParseError as exc:
        raise ValueError(f"not parseable XML: {exc}") from exc
    block = root.find("filters")
    if block is None:
        raise ValueError("no <filters> element")
    out: dict[str, Rec] = {}
    for item in block.findall("item"):
        key = (item.findtext("filterKey") or "").strip().lower()
        if not key:
            continue
        out[key] = {"key": key, "name": (item.findtext("displayData/name") or "").strip(),
                    "layer": (item.findtext("layerKey") or "").strip(),
                    "action": (item.findtext("action/type") or "").strip(),
                    "text": ElementTree.tostring(item, encoding="unicode")}
    return out


def _brief(f: Rec) -> Rec:
    return {"key": f["key"], "name": f["name"], "layer": f["layer"], "action": f["action"]}


def filters_referencing(filters: dict[str, Rec], sid: str | None) -> list[Rec]:
    """Filters whose text names `sid` (case-insensitive); an empty or missing sid matches nothing."""
    if not sid:
        return []
    needle = sid.lower()
    return [_brief(f) for f in filters.values() if needle in f["text"].lower()]


def analyse_wfp(before: str | None, during: str | None, after: str | None, container_sid: str | None,
                user_sid: str | None, alive: bool | None, problems: list[str] | None = None,
                disable: Iterable[str] = ()) -> Rec:
    """One launch's variant-4 reading from the three filter captures. The reading is INSTRUMENT-BLIND (never 'no
    filters') when any capture is missing or unparseable or lists no filters, the container SID is unknown, or the
    container was not shown alive across the during-capture. `disable` switches checks off for the lock tests."""
    probs = list(problems or [])
    docs: dict[str, dict[str, Rec]] = {}
    for name, text in (("before", before), ("during", during), ("after", after)):
        if text is None:
            probs.append(f"{name} capture missing")
            continue
        try:
            docs[name] = wfp_filters(text)
        except ValueError as exc:
            probs.append(f"{name} capture unreadable: {exc}")
            continue
        if not docs[name] and "empty" not in disable:
            probs.append(f"{name} capture lists no filters")
    if alive is not True and "alive" not in disable:
        probs.append("container not shown alive across the during capture")
    if not container_sid and "sid" not in disable:
        probs.append("container AppContainer SID unknown")
    rec: Rec = {"capture_during_container_alive": alive is True, "container_sid": container_sid, "user_sid": user_sid,
                "problems": probs, "wfp_delta_count": None, "wfp_filters_referencing_container_sid": [],
                "wfp_delta_filters_referencing_user_sid": [], "filter_counts": {k: len(v) for k, v in docs.items()}}
    if "during" in docs:
        rec["wfp_filters_referencing_container_sid"] = filters_referencing(docs["during"], container_sid)
        if "before" in docs and "after" in docs:
            delta = {k: v for k, v in docs["during"].items() if k not in docs["before"] and k not in docs["after"]}
            rec["wfp_delta_count"] = len(delta)
            rec["wfp_delta_filters"] = [_brief(f) for f in delta.values()]
            rec["wfp_delta_filters_referencing_user_sid"] = filters_referencing(delta, user_sid)
    if rec["wfp_filters_referencing_container_sid"]:
        rec["reading"] = "FILTERS-PRESENT"
    elif probs:
        rec["reading"] = "INSTRUMENT-BLIND"
    else:
        rec["reading"] = "CAPABILITY-ONLY-SUPPORTED"
    return rec


def judge_variant4(runs: list[Rec], control: Rec | None, disable: Iterable[str] = ()) -> Rec:
    """Group verdict for the WFP capture: FILTERS-PRESENT when any launch's during capture holds a filter naming that
    launch's container SID; else INSTRUMENT-BLIND unless the positive control passed and every launch was captured
    with the container alive; else CAPABILITY-ONLY-SUPPORTED. A run with no capture counts against it."""
    reasons: list[str] = []
    present: list[Rec] = []
    readings: dict[str, str] = {}
    for r in runs:
        w = r.get("wfp")
        tag = str(r.get("tag"))
        if not isinstance(w, dict):
            readings[tag] = "NO-CAPTURE"
            reasons.append(f"{tag}: no WFP capture record")
            continue
        readings[tag] = str(w.get("reading"))
        if w.get("reading") == "FILTERS-PRESENT":
            present += [{"tag": tag, **f} for f in w.get("wfp_filters_referencing_container_sid") or []]
        elif w.get("reading") != "CAPABILITY-ONLY-SUPPORTED":
            reasons.append(f"{tag}: {'; '.join(w.get('problems') or ['reading ' + str(w.get('reading'))])}")
    if "control" not in disable and not (control and control.get("ok") is True):
        reasons.append("positive control not found: " + str((control or {}).get("problems") or "no control record"))
    if not runs:
        reasons.append("no launched run")
    if present:
        verdict = "FILTERS-PRESENT"
    elif reasons:
        verdict = "INSTRUMENT-BLIND"
    else:
        verdict = "CAPABILITY-ONLY-SUPPORTED"
    return {"verdict": verdict, "runs": len(runs), "run_readings": readings,
            "filters_referencing_container_sid": present, "blind_reasons": reasons,
            "positive_control_ok": bool(control and control.get("ok") is True),
            "not_measured": "filters the netsh dump does not list; any SID the payload did not report; "
                            "behaviour outside these launches"}


def load_wfp_control(folder: Path) -> Rec | None:
    path = folder / "wfp-control.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def judge_controls(ctl: Rec | None) -> Rec:
    """B5: the same direct connects from an unconfined process must succeed (1 each per batch)."""
    if not ctl:
        return {"ok": False, "reasons": ["no unfenced control record"]}
    tag = str(ctl["tag"])
    a = [e for e in _tagged(ctl.get("target_log") or [], tag) if _kind(str(e.get("marker")), tag) == "b5a"]
    b = (ctl.get("b5b") or {}).get("connected") is True
    c = (ctl.get("b5c") or {}).get("connected") is True
    reasons = [n for n, ok in (("B5 loopback listener not reached", bool(a)), ("B5 LAN peer not reached", b),
                               ("B5 1.1.1.1:443 not reached", c)) if not ok]
    return {"ok": not reasons, "reasons": reasons, "b5a": bool(a), "b5b": b, "b5c": c}


def judge_batch(runs: list[Rec], controls: Rec | None, n_expected: int = SPEC_N, detect_fail: bool = True,
                disable: Iterable[str] = (), wfp_control: Rec | None = None,
                unreadable: list[str] | None = None) -> Rec:
    ctl = judge_controls(controls)
    groups: dict[str, list[Rec]] = {}
    for r in runs:
        groups.setdefault(f"{r['arm']}/{r['state']}", []).append(r)
    result: Rec = {"controls": ctl, "groups": {}, "n_expected": n_expected, "below_spec_n": n_expected < SPEC_N,
                  "unreadable_under_this_token": unreadable}
    for key, rs in sorted(groups.items()):
        judged = [judge_run(r, detect_fail, disable) for r in rs]
        verdicts = [j["verdict"] for j in judged]
        changed = [r.get("tag") for r in rs if r.get("state_changed_by_run")]
        state_unknown = [r.get("tag") for r in rs if not isinstance(r.get("state_changed_by_run"), dict)]
        if "FAIL" in verdicts:
            v = "FAIL"
        elif changed:
            v = "STOPPED-STATE-CHANGE"
        elif all(x == "REFUSED" for x in verdicts) and len(verdicts) >= n_expected:
            v = "REFUSED"
        elif all(x == "REFUSED-AT-LAUNCH" for x in verdicts) and len(verdicts) >= n_expected:
            v = "REFUSED-AT-LAUNCH"
        elif any(x == "INSTRUMENT-BLIND" for x in verdicts) or (all(x == "HOLD" for x in verdicts) and not ctl["ok"]):
            v = "INSTRUMENT-BLIND"
        elif len(verdicts) < n_expected or state_unknown:
            v = "INCOMPLETE"
        elif all(x == "HOLD" for x in verdicts):
            v = "HOLD"
        else:
            v = "MIXED"
        not_measurable = any("NOT-MEASURABLE" in str(reason) for j in judged for reason in j["reasons"])
        result["groups"][key] = {"verdict": v, "runs": len(rs), "run_verdicts": verdicts,
                                 "b4i_not_measurable": not_measurable, "state_changed_runs": changed,
                                 "state_unknown_runs": state_unknown,
                                 "token_modes": sorted({str(j.get("token_mode")) for j in judged}),
                                 "launcher_nonzero_exit_runs": [r.get("tag") for r, j in zip(rs, judged)
                                                                if j.get("launcher_nonzero_exit") is not None]}
    wfp_runs = [r for r in runs if "wfp" in r]
    if wfp_runs or wfp_control is not None:
        result["variant4_wfp"] = judge_variant4(wfp_runs, wfp_control, disable)
    return result


def load_dir(folder: Path) -> tuple[list[Rec], Rec | None]:
    runs = [json.loads(p.read_text(encoding="utf-8")) for p in sorted(folder.glob("run-*.json"))]
    ctl_path = folder / "control-b5.json"
    return runs, (json.loads(ctl_path.read_text(encoding="utf-8")) if ctl_path.exists() else None)


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        print("usage: python -I summarise.py <output-folder>")
        return 2
    folder = Path(argv[0])
    refuse_git_path(folder)
    runs, ctl = load_dir(folder)
    header = folder / "batch-header.json"
    n_expected = int(json.loads(header.read_text(encoding="utf-8")).get("runs_per_arm", SPEC_N)) if header.exists() else SPEC_N
    head = json.loads(header.read_text(encoding="utf-8")) if header.exists() else {}
    summary = judge_batch(runs, ctl, n_expected, wfp_control=load_wfp_control(folder),
                          unreadable=head.get("unreadable_under_this_token"))
    summary["arm_refusals"] = sorted(p.stem for p in folder.glob("arm-*-refused.json"))
    (folder / "batch-summary.json").write_text(json.dumps(summary, indent=1), encoding="utf-8")
    print(json.dumps(summary, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
