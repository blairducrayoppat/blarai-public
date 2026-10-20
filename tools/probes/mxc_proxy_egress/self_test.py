"""Self-test for the MXC loopback-proxy egress probe. Runs without MXC, non-elevated, no real container.

What this measures: that the probe's instruments and verdict logic behave as specified, using synthetic records
and a fake launcher that stands in for wxc-exec (fenced, open, refusing, proxy-blind, timing-out, stray-connection
and launch-refusing modes). Every detection has a toggle check: with that detection disabled, the synthetic record
it exists for is not flagged, which proves the check can see it.
Checks: forwarding proxy forwards, logs and default-denies; listeners log run tags, bind loopback only and
exclusively; summarise gives HOLD / FAIL / REFUSED / REFUSED-AT-LAUNCH / INSTRUMENT-BLIND on synthetic records
(including timeouts that are not refusals, unexplained connections at or after the launch start, failed unfenced controls
and a non-measurable LAN peer); the output-path guard refuses a git tree; launch.ps1 refuses a mismatched hash, a
missing hash file, a missing line and a missing file, and passes its own hash on; the arm-B precondition refuses
when the probe flag is false or absent; the state snapshot carries firewall, loopback-exemption, WinHTTP-proxy and
WFP entries and a change in it stops the batch; the harness end to end against the fake launcher; fixtures fx-a
and fx-b carry identical measured state; the probe files carry no numbered references and no operator account name.

How to run: python -I self_test.py        (prints PASS/FAIL per check; exit code non-zero on any FAIL)
What it writes: temporary folders under the system temp directory only, removed at the end. It binds 127.0.0.1
only, ports 18110, 18111 and 18113, and connects nowhere else (the 1.1.1.1 destination and the LAN peer are
remapped to a local stand-in listener).

Token modes: launch.ps1 -Token standard refuses an elevated or non-Medium token (dry or live) and passes
`--token standard` on; the default mode refuses a non-elevated live run and passes `--token elevated`; run_probe.py
refuses standard mode from an elevated token and records the token (mode, IsUserAnAdmin, elevation, integrity SID,
groups summary) in the header and in run, control and dry-run records; summarise gives INSTRUMENT-BLIND for a
standard-mode record whose token is elevated, never HOLD without a passing B2 positive control, never HOLD on a
direct attempt (B3, B4(i), B4(ii)) whose report is empty, absent or does not show it ran and its outcome code, and
never HOLD when the payload's own recorded token is not an AppContainer token.

Launch classification: REFUSED and REFUSED-AT-LAUNCH need MXC's own `policy_validation` error envelope (JSON `code`)
plus a rejection message; a backend_error, an OS error, a panic or keyword text alone is INSTRUMENT-BLIND
(LAUNCH-FAILED, NOT ANSWERED). The AppContainer mapping snapshot compares every mapping not carrying a known foreign
prefix (another tool's self-test profiles) by SID and name and records the foreign count and total.

NOT MEASURED: any build other than the one(s) run; behaviour on a host whose --probe reports
host-loopback ingress unsupported (the earlier 26200.9457 condition); an identity-scoped proxy (allowedProxyPeer); the
session-isolation backend; UDP, ICMP or DNS egress under the proxy policy; host-to-container ingress; nono under
MXC; anything about the fork or any other sandbox. This self-test does not exercise MXC at all: a PASS here says
the instrument works, not that any launcher holds.
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import net_payload  # noqa: E402
import run_probe  # noqa: E402
import summarise  # noqa: E402
from proxy import ForwardingProxy, ProbeListener  # noqa: E402

PWSH = Path("C:/Program Files/PowerShell/7/pwsh.exe")
STAND_IN_PORT = 18113
RESULTS: list[tuple[str, bool, str]] = []
START, END, INSIDE, BEFORE, AFTER = ("2026-10-15T15:00:00.000-04:00", "2026-10-15T15:00:10.000-04:00",
                                     "2026-10-15T15:00:05.000-04:00", "2026-10-15T14:59:00.000-04:00",
                                     "2026-10-15T15:00:12.000-04:00")


POLICY_ENVELOPE = '{{"code":"policy_validation","message":"{msg}"}}'
AC_TOKEN = {"user_sid": "S-1-5-21-1-2-3-1001", "is_appcontainer": True, "appcontainer_sid": "S-1-15-2-1-2-3-4-5-6-7",
            "integrity_sid": "S-1-16-4096", "elevated": False}


def check(name: str, ok: bool, detail: str = "") -> None:
    RESULTS.append((name, bool(ok), detail))
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail and not ok else ""), flush=True)


# ------------------------------------------------------------------ synthetic records

def syn(tag: str = "T1", *, b2: int = 3, b3_hit: bool = False, b4i_conn: bool = False, b4ii_conn: bool = False,
        dry_rc: int = 0, host_ok: bool = True, with_payload: bool = True, stray: str | None = None,
        container_only_connect: bool = False, b3_err: int | None = 10013, b4i_err: int | None = 10013,
        b4ii_err: int | None = 10013, gw_port: int = 80, pre_c: bool = True, post_c: bool = True,
        pre_gw: bool = True, post_gw: bool = True, launch_exit: int = 0, arm: str = "B", state: str = "B1",
        stderr: str = "launch said no", launch_timeout: bool = False, changed: bool = False,
        mxc_log: str = "log tail", started_flag: bool | None = None, token: dict | None = None,
        dry_stderr: str = POLICY_ENVELOPE.format(msg="policy refused text")) -> dict:
    mk = lambda k, i: f"{tag}-{k}-{i}"  # noqa: E731
    proxy_log = [{"marker": mk("b2", i), "outcome": "forwarded", "status": 200, "ts": INSIDE} for i in range(1, b2 + 1)]
    target_log = [{"marker": mk("b2", i), "ts": INSIDE} for i in range(1, b2 + 1)]
    if b3_hit:
        target_log.append({"marker": mk("b3", 1), "ts": INSIDE})
    if stray == "inside":
        target_log.append({"marker": "", "ts": INSIDE, "bytes": 0})
    elif stray == "after":
        target_log.append({"marker": "", "ts": AFTER, "bytes": 0})
    elif stray == "before":
        target_log.append({"marker": "", "ts": BEFORE, "bytes": 0})
    refusal = lambda code: {"connected": False, "error": "PermissionError" if code else "TimeoutError", "winerror": code}  # noqa: E731
    payload = None
    if with_payload:
        payload = {"b2": [{"status": 200} for _ in range(b2)],
                   "b3": {"connected": True} if (b3_hit or container_only_connect) else refusal(b3_err),
                   "b4i": {"connected": True} if b4i_conn else (refusal(b4i_err) if gw_port else {"skipped": "no gateway port"}),
                   "b4ii": {"connected": True} if b4ii_conn else refusal(b4ii_err),
                   "token": AC_TOKEN if token is None else token}
    launch = {"exit_code": launch_exit, "started": START, "ended": END, "stderr_tail": stderr, "stdout_tail": ""}
    if launch_timeout:
        launch = {"timeout": True, "started": START}
    return {"arm": arm, "state": state, "tag": tag, "state_changed_by_run": {"x": [1, 2]} if changed else {}, "dry_run": {"rc": dry_rc, "stdout": "", "stderr": dry_stderr},
            "launch": launch, "payload": payload, "target_log": target_log, "proxy_log": proxy_log,
            "gateway": {"port": gw_port}, "mxc_log_tail": mxc_log, "mxc_log_full_text_has_process_start": started_flag,
            "unfenced_pre": {"c": {"connected": pre_c}, "gw": {"connected": pre_gw}},
            "unfenced_post": {"c": {"connected": post_c}, "gw": {"connected": post_gw}},
            "host_control": {"target": host_ok, "proxy": True}}


def verdict(rec: dict, **kw: object) -> str:
    return summarise.judge_run(rec, **kw)["verdict"]  # type: ignore[arg-type]


def test_instruments() -> None:
    lock, tlog, plog = threading.Lock(), [], []
    target = ProbeListener("target", "127.0.0.1", 18111, tlog, lock)
    proxy = ForwardingProxy(18110, {18111}, plog, lock)
    try:
        r = net_payload.http_via_proxy("127.0.0.1", 18110, "127.0.0.1", 18111, "RUN9-b2-1")
        check("proxy forwards a request to the allowlisted target", r.get("status") == 200 and "listener-target-ok" in str(r.get("body")), str(r))
        check("proxy logs the forwarded request with its run tag",
              any(e["marker"] == "RUN9-b2-1" and e["outcome"] == "forwarded" and e["status"] == 200 for e in plog), str(plog))
        check("second listener logs the proxied request with its run tag", any(e["marker"] == "RUN9-b2-1" for e in tlog), str(tlog))
        d = net_payload.tcp_probe("127.0.0.1", 18111, "RUN9-b3-1")
        check("listener logs a direct connect with its run tag", d.get("connected") is True and any(e["marker"] == "RUN9-b3-1" for e in tlog), str(d))
        denied = net_payload.http_via_proxy("127.0.0.1", 18110, "127.0.0.1", 18999, "RUN9-b2-2")
        check("proxy refuses a non-allowlisted target (default deny)", denied.get("status") == 403 and plog[-1]["outcome"] == "refused-target", str(denied))
    finally:
        proxy.close()
        target.close()
    for label, build in (("listener", lambda h: ProbeListener("x", h, 18111, [], threading.Lock())),
                         ("proxy", lambda h: ForwardingProxy(18110, set(), [], threading.Lock(), host=h))):
        try:
            build("0.0.0.0")
            ok = False
        except ValueError:
            ok = True
        check(f"{label} refuses to bind a non-loopback address", ok)

    def squatter(port: int) -> socket.socket:
        s = socket.socket()
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind(("127.0.0.1", port))
        s.listen(1)
        return s

    for label, port, build in (("proxy", 18110, lambda: ForwardingProxy(18110, set(), [], threading.Lock())),
                               ("listener", 18111, lambda: ProbeListener("x", "127.0.0.1", 18111, [], threading.Lock()))):
        sq = squatter(port)
        try:
            built = build()
            built.close()
            ok = False
        except OSError:
            ok = True
        finally:
            sq.close()
        check(f"{label} refuses a port already held by a SO_REUSEADDR socket (exclusive bind)", ok)
    sq = squatter(18110)
    try:
        plain = ThreadingHTTPServer(("127.0.0.1", 18110), BaseHTTPRequestHandler)
        plain.server_close()
        sees = True
    except OSError:
        sees = False
    finally:
        sq.close()
    check("TOGGLE: a default http.server co-binds on top of the same squatter (the exclusive bind is load-bearing)", sees)


def test_summarise() -> None:
    check("synthetic HOLD record -> HOLD", verdict(syn()) == "HOLD", str(summarise.judge_run(syn())))
    check("synthetic B3 listener hit -> FAIL", verdict(syn(b3_hit=True)) == "FAIL")
    check("synthetic B4(i) container connect to the LAN peer -> FAIL", verdict(syn(b4i_conn=True)) == "FAIL")
    check("synthetic B4(ii) 1.1.1.1:443 connect -> FAIL", verdict(syn(b4ii_conn=True)) == "FAIL")
    check("container-reported B3 connect with no listener log -> FAIL", verdict(syn(container_only_connect=True)) == "FAIL")
    check("FAIL outranks a missing B2", verdict(syn(b3_hit=True, b2=0)) == "FAIL")
    for label, kw in (("B3 hit", dict(b3_hit=True)), ("B4(i) connect", dict(b4i_conn=True)), ("B4(ii) connect", dict(b4ii_conn=True))):
        check(f"TOGGLE: FAIL detection disabled -> synthetic {label} NOT flagged FAIL", verdict(syn(**kw), detect_fail=False) != "FAIL")  # type: ignore[arg-type]
    check("B2 missing -> INSTRUMENT-BLIND", verdict(syn(b2=0)) == "INSTRUMENT-BLIND")
    check("B2 only 2 of 3 -> INSTRUMENT-BLIND", verdict(syn(b2=2)) == "INSTRUMENT-BLIND")
    check("no payload report (launch exit 0) -> INSTRUMENT-BLIND", verdict(syn(with_payload=False)) == "INSTRUMENT-BLIND")
    check("failed listener host control -> INSTRUMENT-BLIND", verdict(syn(host_ok=False)) == "INSTRUMENT-BLIND")
    check("dry-run refusal -> REFUSED", verdict(syn(dry_rc=1, with_payload=False)) == "REFUSED")
    # unexplained connection in the launch window
    inside = summarise.judge_run(syn(stray="inside"))
    check("untagged listener connection inside the launch window -> INSTRUMENT-BLIND (never HOLD)",
          inside["verdict"] == "INSTRUMENT-BLIND" and any("unexplained" in r for r in inside["reasons"]), str(inside))
    check("untagged listener connection before the launch (host control period) is outside the window -> HOLD", verdict(syn(stray="before")) == "HOLD")
    check("untagged connection AFTER the launch ended (listeners still open) -> INSTRUMENT-BLIND", verdict(syn(stray="after")) == "INSTRUMENT-BLIND")
    check("TOGGLE: untagged-connection check disabled -> synthetic late stray NOT blind", verdict(syn(stray="after"), disable=["untagged"]) == "HOLD")
    check("launcher timeout with a clean payload -> INSTRUMENT-BLIND", verdict(syn(launch_timeout=True)) == "INSTRUMENT-BLIND")
    check("TOGGLE: timeout check disabled -> synthetic launcher timeout NOT blind", verdict(syn(launch_timeout=True), disable=["timeout"]) == "HOLD")
    nz = summarise.judge_run(syn(launch_exit=7))
    check("non-zero launcher exit with a payload report: verdict unchanged (HOLD), exit code recorded and flagged",
          nz["verdict"] == "HOLD" and nz["launcher_nonzero_exit"] == 7 and nz["launch_exit_code"] == 7, str(nz))
    check("untagged connection plus a container-reported B3 connect -> FAIL", verdict(syn(stray="inside", container_only_connect=True)) == "FAIL")
    check("TOGGLE: untagged-connection check disabled -> synthetic stray connection NOT blind", verdict(syn(stray="inside"), disable=["untagged"]) == "HOLD")
    # timeouts are not refusals
    for label, kw in (("B4(ii)", dict(b4ii_err=None)), ("B4(i)", dict(b4i_err=None)), ("B3", dict(b3_err=None))):
        check(f"{label} timeout (no enforcement code) -> INSTRUMENT-BLIND", verdict(syn(**kw)) == "INSTRUMENT-BLIND")  # type: ignore[arg-type]
    check("a different Windows error code (10060) is not the enforcement code -> INSTRUMENT-BLIND", verdict(syn(b4ii_err=10060)) == "INSTRUMENT-BLIND")
    check("TOGGLE: enforcement-code check disabled -> synthetic B4(ii) timeout NOT blind", verdict(syn(b4ii_err=None), disable=["nonenforcement"]) == "HOLD")
    # unfenced controls around the launch
    check("unfenced 1.1.1.1:443 failed before the launch -> INSTRUMENT-BLIND", verdict(syn(pre_c=False)) == "INSTRUMENT-BLIND")
    check("unfenced 1.1.1.1:443 failed after the launch -> INSTRUMENT-BLIND", verdict(syn(post_c=False)) == "INSTRUMENT-BLIND")
    check("TOGGLE: unfenced-control check disabled -> synthetic failed control NOT blind", verdict(syn(post_c=False), disable=["unfenced"]) == "HOLD")
    nm = summarise.judge_run(syn(gw_port=0))
    check("no reachable LAN-peer port -> B4(i) NOT-MEASURABLE, INSTRUMENT-BLIND, never HOLD",
          nm["verdict"] == "INSTRUMENT-BLIND" and any("NOT-MEASURABLE" in r for r in nm["reasons"]), str(nm))
    check("LAN-peer unfenced connect failed after the launch -> NOT-MEASURABLE, never HOLD", verdict(syn(post_gw=False)) == "INSTRUMENT-BLIND")
    check("TOGGLE: with the unfenced check disabled a skipped B4(i) is NOT blind", verdict(syn(gw_port=0), disable=["unfenced"]) == "HOLD")
    # refusal at launch
    refusal_text = POLICY_ENVELOPE.format(msg="launch refused: policy not supported by this launcher")
    true_ref = syn(with_payload=False, launch_exit=3, b2=0, stderr=refusal_text)
    ran_failed = syn(with_payload=False, launch_exit=3, b2=3, stderr=refusal_text)
    stray_failed = syn(with_payload=False, launch_exit=3, b2=0, stderr=refusal_text, stray="inside")
    ral = summarise.judge_run(true_ref)
    check("true refusal (exit non-zero, no payload, no traffic, refusal text) -> REFUSED-AT-LAUNCH with the launch's own text",
          ral["verdict"] == "REFUSED-AT-LAUNCH" and any("policy not supported" in r for r in ral["reasons"]), str(ral))
    check("launched-then-failed (same exit, same text, 3 run-tagged forwards in the logs) -> INSTRUMENT-BLIND", verdict(ran_failed) == "INSTRUMENT-BLIND")
    check("launched-then-failed (untagged connection in the window, no tagged traffic) -> INSTRUMENT-BLIND", verdict(stray_failed) == "INSTRUMENT-BLIND")
    started_log = "process created (PID: 4242)\n" + '{"event":"mxc.ProcessExited","exit_code":1}'
    dead = syn(with_payload=False, launch_exit=1, b2=0, stderr="OSError: [Errno 22] Invalid argument", mxc_log=started_log)
    dd = summarise.judge_run(dead)
    check("launched workload that died before any traffic (MXC log shows the process created), stderr says 'Invalid' -> INSTRUMENT-BLIND",
          dd["verdict"] == "INSTRUMENT-BLIND" and any("MXC log shows the process started: True" in r for r in dd["reasons"]), str(dd))
    dead_env = syn(with_payload=False, launch_exit=1, b2=0, stderr=POLICY_ENVELOPE.format(msg="policy not supported"), mxc_log=started_log)
    check("a policy_validation envelope beside a log that shows the process created -> INSTRUMENT-BLIND (it ran)", verdict(dead_env) == "INSTRUMENT-BLIND")
    check("TOGGLE: MXC-log check disabled -> that launched workload is wrongly REFUSED-AT-LAUNCH",
          verdict(dead_env, disable=["mxc_log"]) == "REFUSED-AT-LAUNCH")
    check("process start seen only in the full log (tail cut) -> INSTRUMENT-BLIND",
          verdict(syn(with_payload=False, launch_exit=1, b2=0, stderr=refusal_text, started_flag=True)) == "INSTRUMENT-BLIND")
    check("refusal text but an empty MXC log (cannot show the process never started) -> INSTRUMENT-BLIND",
          verdict(syn(with_payload=False, launch_exit=1, b2=0, stderr=refusal_text, mxc_log="")) == "INSTRUMENT-BLIND")
    envelope = syn(with_payload=False, launch_exit=1, b2=0, stderr='{"code":"policy_validation","message":"network proxy not allowed"}')
    check("MXC's own policy_validation error code counts as a refusal even without the wording -> REFUSED-AT-LAUNCH", verdict(envelope) == "REFUSED-AT-LAUNCH")
    # H1: keyword text alone, or any other MXC error code, is never a result
    for label, err in (("backend_error 'invalid parameter'", '{"code":"backend_error","message":"failed to create AppContainer profile: invalid parameter"}'),
                       ("'Invalid handle (os error 6)'", "Error: Invalid handle (os error 6)"),
                       ("a Rust panic containing 'requires'", "thread 'main' panicked at src/x.rs: requires a valid token"),
                       ("backend_error whose message says 'validation failed'", '{"code":"backend_error","message":"validation failed"}'),
                       ("policy_validation beside a backend_error", '{"code":"policy_validation","message":"unsupported"} {"code":"backend_error","message":"x"}'),
                       ("a policy_validation envelope whose message is not a rejection", POLICY_ENVELOPE.format(msg="ok"))):
        rr = summarise.judge_run(syn(with_payload=False, launch_exit=1, b2=0, stderr=err))
        check(f"launch failure: {label} -> INSTRUMENT-BLIND (LAUNCH-FAILED, NOT ANSWERED), not REFUSED-AT-LAUNCH",
              rr["verdict"] == "INSTRUMENT-BLIND" and any("LAUNCH-FAILED" in r for r in rr["reasons"]), str(rr))
    check("a policy_validation envelope in the MXC log (not stderr) also counts when the process never started",
          verdict(syn(with_payload=False, launch_exit=1, b2=0, stderr="", mxc_log='[1] ' + POLICY_ENVELOPE.format(msg="network proxy not supported"))) == "REFUSED-AT-LAUNCH")
    backend = syn(with_payload=False, launch_exit=1, b2=0, stderr='{"code":"backend_error","message":"invalid parameter requires refused"}')
    check("TOGGLE: with the code test replaced by keyword matching the backend_error launch failure WOULD read refused",
          summarise.REFUSAL_TEXT.search(json.dumps(backend["launch"])) is not None and verdict(backend) == "INSTRUMENT-BLIND")
    check("three backend_error launch failures in a batch -> batch INSTRUMENT-BLIND, never REFUSED-AT-LAUNCH",
          summarise.judge_batch([dict(backend, tag=f"K{i}") for i in range(3)], None)["groups"]["B/B1"]["verdict"] == "INSTRUMENT-BLIND")
    nonpolicy_dry = summarise.judge_run(syn(dry_rc=1, with_payload=False, dry_stderr='{"code":"backend_error","message":"access is denied"}'))
    check("dry-run exit non-zero with a backend_error (not a policy rejection) -> INSTRUMENT-BLIND, not REFUSED",
          nonpolicy_dry["verdict"] == "INSTRUMENT-BLIND" and "LAUNCH-FAILED" in nonpolicy_dry["reasons"][0], str(nonpolicy_dry))
    check("dry-run exit non-zero with plain keyword text and no envelope -> INSTRUMENT-BLIND, not REFUSED",
          verdict(syn(dry_rc=1, with_payload=False, dry_stderr="error: policy refused, invalid, requires")) == "INSTRUMENT-BLIND")
    # M2: every direct-attempt state must positively show it ran and its outcome code
    for key in ("b3", "b4i", "b4ii"):
        for label, val in (("empty", {}), ("absent", "ABSENT"), ("no connected flag", {"target": "x"}),
                           ("not connected and no code", {"connected": False})):
            rec = syn()
            if val == "ABSENT":
                del rec["payload"][key]
            else:
                rec["payload"][key] = val
            rv = summarise.judge_run(rec)
            check(f"{key} report {label} -> INSTRUMENT-BLIND, never HOLD",
                  rv["verdict"] == "INSTRUMENT-BLIND" and any(f"payload report for {'B4(i)' if key == 'b4i' else key.upper().replace('B4II', 'B4(ii)')}" in r for r in rv["reasons"]), str(rv))
    skipped = syn()
    skipped["payload"]["b4i"] = {"skipped": "no gateway port"}
    check("b4i with a skipped reason is still NOT-MEASURABLE (blind), not a missing attempt",
          any("NOT-MEASURABLE" in r for r in summarise.judge_run(dict(skipped, gateway={"port": 0}))["reasons"]))
    # M3: the container's own token
    for label, tk in (("not an AppContainer token", dict(AC_TOKEN, is_appcontainer=False, appcontainer_sid=None, integrity_sid="S-1-16-8192")),
                      ("is_appcontainer unreadable", dict(AC_TOKEN, is_appcontainer=None))):
        tv = summarise.judge_run(syn(token=tk))
        check(f"payload token {label} -> INSTRUMENT-BLIND (a confined-launch claim the record cannot show), never HOLD",
              tv["verdict"] == "INSTRUMENT-BLIND" and any("token" in r for r in tv["reasons"]), str(tv))
    nt = syn()
    del nt["payload"]["token"]
    check("payload with no token record -> INSTRUMENT-BLIND", verdict(nt) == "INSTRUMENT-BLIND")
    check("an unconfined payload that REACHES the listener is still FAIL (token check never hides a reach)",
          verdict(syn(b3_hit=True, token=dict(AC_TOKEN, is_appcontainer=False))) == "FAIL")
    denied = summarise.judge_run(syn(with_payload=False, launch_exit=1, b2=0, stderr="CreateProcess failed: Access is denied."))
    check("an unclassifiable launch failure is INSTRUMENT-BLIND and its stderr is in the reasons",
          denied["verdict"] == "INSTRUMENT-BLIND" and any("Access is denied" in r for r in denied["reasons"]), str(denied))
    check("non-zero exit with unrecognisable text and no traffic -> INSTRUMENT-BLIND",
          verdict(syn(with_payload=False, launch_exit=3, b2=0, stderr="exit 3")) == "INSTRUMENT-BLIND")
    check("TOGGLE: ran-evidence check disabled -> the launched-then-failed record is wrongly REFUSED-AT-LAUNCH",
          verdict(ran_failed, disable=["ran_evidence"]) == "REFUSED-AT-LAUNCH")
    check("TOGGLE: refused-at-launch check disabled -> the true refusal falls to INSTRUMENT-BLIND",
          verdict(true_ref, disable=["refused_at_launch"]) == "INSTRUMENT-BLIND")
    # batches
    ctl_ok = {"tag": "C1", "target_log": [{"marker": "C1-b5a-1"}], "b5b": {"connected": True}, "b5c": {"connected": True}}
    holds = [syn(f"R{i}") for i in range(3)]
    grp = lambda runs, ctl=ctl_ok, **kw: summarise.judge_batch(runs, ctl, **kw)["groups"]["B/B1"]  # noqa: E731
    check("batch of 3 HOLD + passing controls -> HOLD", grp(holds)["verdict"] == "HOLD")
    check("batch HOLD with a failed unfenced control -> INSTRUMENT-BLIND", grp(holds, dict(ctl_ok, b5c={"connected": False}))["verdict"] == "INSTRUMENT-BLIND")
    check("batch HOLD with the LAN-peer control failed -> INSTRUMENT-BLIND", grp(holds, dict(ctl_ok, b5b={"connected": False}))["verdict"] == "INSTRUMENT-BLIND")
    check("batch with one FAIL -> FAIL", grp(holds[:2] + [syn("R9", b3_hit=True)])["verdict"] == "FAIL")
    nm_batch = grp([syn(f"N{i}", gw_port=0) for i in range(3)])
    check("batch with B4(i) not measurable -> INSTRUMENT-BLIND and flagged, never HOLD", nm_batch["verdict"] == "INSTRUMENT-BLIND" and nm_batch["b4i_not_measurable"] is True)
    refused = [syn(f"A{i}", dry_rc=1, with_payload=False, arm="A", state="A1") for i in range(3)]
    check("batch of 3 REFUSED -> REFUSED", summarise.judge_batch(refused, ctl_ok)["groups"]["A/A1"]["verdict"] == "REFUSED")
    ral3 = [syn(f"L{i}", with_payload=False, launch_exit=3, b2=0, stderr=refusal_text) for i in range(3)]
    check("batch of 3 REFUSED-AT-LAUNCH -> REFUSED-AT-LAUNCH", grp(ral3)["verdict"] == "REFUSED-AT-LAUNCH")
    sc = grp([syn("S0"), syn("S1"), syn("S2", changed=True)])
    check("batch whose last run changed host state -> STOPPED-STATE-CHANGE, never HOLD",
          sc["verdict"] == "STOPPED-STATE-CHANGE" and sc["state_changed_runs"] == ["S2"], str(sc))
    check("the same batch with no state change -> HOLD", grp([syn("S0"), syn("S1"), syn("S2")])["verdict"] == "HOLD")
    nzb = grp([syn("Z0", launch_exit=7), syn("Z1"), syn("Z2")])
    check("batch flags runs with a non-zero launcher exit without changing the verdict",
          nzb["verdict"] == "HOLD" and nzb["launcher_nonzero_exit_runs"] == ["Z0"], str(nzb))
    check("batch of 2 HOLD of 3 expected -> INCOMPLETE", grp(holds[:2])["verdict"] == "INCOMPLETE")


def test_port_preflight() -> None:
    """Uses an ephemeral loopback port, never the probe's own ports."""
    sq = socket.socket()
    sq.bind(("127.0.0.1", 0))
    sq.listen(1)
    port = sq.getsockname()[1]
    try:
        problems = run_probe.check_ports_free([port])
        check("port pre-flight names the holder's process id in plain words",
              len(problems) == 1 and f"process id {os.getpid()}" in problems[0] and "already in use" in problems[0] and "Traceback" not in problems[0], str(problems))
    finally:
        sq.close()
    free = socket.socket()
    free.bind(("127.0.0.1", 0))
    fport = free.getsockname()[1]
    free.close()
    check("port pre-flight passes for a free port", run_probe.check_ports_free([fport]) == [])


def test_port_held_between_runs() -> None:
    """Written for the case where a port is taken after the batch started; it runs the harness end to end, which binds the
    probe's own ports, so it must not be run while a live run may be in progress or pending."""
    with tempfile.TemporaryDirectory() as t:
        td = Path(t)
        saved = (run_probe.TOOLCHAIN, run_probe.CONTAINER_PY, dict(run_probe.LAUNCHERS), run_probe.gateway_ip,
                 run_probe.GATEWAY_PORTS, run_probe.check_ports_free)
        calls = {"n": 0}

        def flaky(ports):
            calls["n"] += 1
            return [] if calls["n"] <= 2 else ["port 18110 on 127.0.0.1 is already in use by process id 4242. Close that program and start the run again; nothing was started."]

        run_probe.TOOLCHAIN, run_probe.CONTAINER_PY = td / "toolchain", Path(sys.executable)
        run_probe.gateway_ip = lambda: "127.0.0.1"  # type: ignore[assignment]
        run_probe.GATEWAY_PORTS = (STAND_IN_PORT,)
        run_probe.check_ports_free = flaky  # type: ignore[assignment]
        stand = ProbeListener("standin", "127.0.0.1", STAND_IN_PORT, [], threading.Lock())
        try:
            rc, text, out = run_harness(td, "B", "fenced", runs=3)
            aborted = json.loads((out / "aborted-B-r2.json").read_text(encoding="utf-8")) if (out / "aborted-B-r2.json").exists() else {}
            check("port taken between runs: the run is recorded ABORTED-PORT-HELD naming the pid, the batch stops, exit 3, no traceback",
                  rc == 3 and aborted.get("verdict") == "ABORTED-PORT-HELD" and "process id 4242" in text and "Traceback" not in text
                  and len(list(out.glob("run-B-B1-*.json"))) == 1, f"rc={rc} {text[-300:]}")
        finally:
            stand.close()
            (run_probe.TOOLCHAIN, run_probe.CONTAINER_PY, _, run_probe.gateway_ip, run_probe.GATEWAY_PORTS,
             run_probe.check_ports_free) = saved  # type: ignore[assignment]
            run_probe.LAUNCHERS.clear()
            run_probe.LAUNCHERS.update(saved[2])


def test_guard_and_fixtures() -> None:
    inside = HERE / "should_not_exist_out"
    refused = False
    try:
        summarise.refuse_git_path(inside)
    except SystemExit as exc:
        refused = "inside the git working tree" in str(exc)
    check("output-path guard refuses a path inside a git working tree", refused)
    with tempfile.TemporaryDirectory() as td:
        ok = True
        try:
            summarise.refuse_git_path(Path(td) / "a" / "b")
        except SystemExit:
            ok = False
        check("output-path guard accepts a path outside every git tree", ok)
    try:
        rc = run_probe.main(["--out", str(inside), "--dry-run-only"])
        check("harness main refuses an in-tree --out before creating anything", False, f"returned {rc}")
    except SystemExit:
        check("harness main refuses an in-tree --out before creating anything", not inside.exists())
    for flag, expect in ((True, True), (False, False), (None, False)):
        probes = {} if flag is None else {run_probe.PROXY_FLAG: flag}
        check(f"arm-B precondition with flag {flag!r} -> {'allowed' if expect else 'refused'}",
              run_probe.check_arm_b_precondition({"probes": probes})[0] is expect)
    check("arm-B precondition refuses an unparsed probe", run_probe.check_arm_b_precondition({"unparsed": "x"})[0] is False)
    known = next(iter(run_probe.KNOWN_BUILDS))
    kc = run_probe.KNOWN_BUILDS[known]
    check("arm commit: a given 40-hex commit is used", run_probe.resolve_arm_commit("zz", "a" * 40)[0] == "a" * 40)
    check("arm commit: a short prefix is refused", run_probe.resolve_arm_commit(known, "5")[0] is None)
    check("arm commit: an over-long string is refused", run_probe.resolve_arm_commit("zz", "a" * 44)[0] is None)
    check("arm commit: non-hex text is refused", run_probe.resolve_arm_commit("zz", "g" * 40)[0] is None)
    check("known-build table holds full 40-hex commits only", all(len(v) == 40 for v in run_probe.KNOWN_BUILDS.values()))
    check("arm commit: from the known-build table when the sha256 matches", run_probe.resolve_arm_commit(known, None)[0] == kc)
    check("arm commit: neither given nor known -> refused", run_probe.resolve_arm_commit("zz", None)[0] is None)
    check("arm commit: a given commit contradicting the table -> refused", run_probe.resolve_arm_commit(known, "deadbeef" * 5)[0] is None)
    a = run_probe.fixture("fx-a", "cmd", Path("W"), Path("P"))
    b = run_probe.fixture("fx-b", "cmd", Path("W"), Path("P"))
    check("fx-a and fx-b are identical", a == b)
    check("fixture state: proxy set, no allowedProxyPeer, ingress allow, hostLoopback allow, egress deny, no rules",
          a["runtimeConfig"] == {"networkProxy": "http://127.0.0.1:18110"} and "allowedProxyPeer" not in json.dumps(a)
          and a["network"] == {"egress": {"default": "deny"}, "ingress": {"default": "allow", "hostLoopback": "allow"}})
    with tempfile.TemporaryDirectory() as td:
        snap = run_probe.snapshot([Path(td)], Path(td), [Path(sys.executable)])
        need = {"firewall_rules_for_interpreters", "firewall_profiles", "loopback_exempt", "winhttp_proxy", "wfp_mxc_filters"}
        check("snapshot carries firewall rules, profiles, loopback exemptions, WinHTTP proxy and WFP count", need <= set(snap), str(set(snap)))
        check("snapshot reads the firewall profiles (not 'unreadable')", isinstance(snap["firewall_profiles"], list) and len(snap["firewall_profiles"]) >= 1, str(snap["firewall_profiles"]))


def test_launch_ps1() -> None:
    if not PWSH.exists():
        check("launch.ps1 tests (pwsh present)", False, str(PWSH))
        return
    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        names = ("run_probe.py", "net_payload.py", "proxy.py", "summarise.py")
        for n in names:
            shutil.copy(HERE / n, d / n)
        shutil.copy(HERE / "launch.ps1", d / "launch.ps1")
        good = "\n".join(f"{run_probe.sha256_of(d / n)}  {n}" for n in names) + "\n"

        def run(approved: Path, *extra: str, env: dict | None = None) -> subprocess.CompletedProcess[str]:
            return subprocess.run([str(PWSH), "-NoProfile", "-File", str(d / "launch.ps1"), "-ApprovedFile", str(approved), *extra],
                                  capture_output=True, text=True, timeout=120, creationflags=0x08000000, check=False,
                                  env={**os.environ, **(env or {})})

        ap = d / "APPROVED.txt"
        ap.write_text(good, encoding="utf-8")
        r = run(ap, "-VerifyOnly")
        check("launch.ps1 verifies matching hashes (VerifyOnly)", r.returncode == 0 and "VERIFIED" in r.stdout, r.stdout + r.stderr)
        ap.write_text(good.replace(good[:8], "00000000", 1), encoding="utf-8")
        r = run(ap, "-VerifyOnly")
        check("launch.ps1 refuses a mismatched hash", r.returncode == 1 and "hash mismatch" in r.stdout, r.stdout + r.stderr)
        r = run(d / "no_such_approved.txt", "-VerifyOnly")
        check("launch.ps1 refuses a missing approved-hash file", r.returncode == 1 and "approved-hash file missing" in r.stdout, r.stdout + r.stderr)
        ap.write_text("\n".join(good.splitlines()[1:]) + "\n", encoding="utf-8")
        r = run(ap, "-VerifyOnly")
        check("launch.ps1 refuses a file with no approved line", r.returncode == 1 and "no approved hash" in r.stdout, r.stdout + r.stderr)
        # stub probe: launch.ps1 must pass its own sha256 on
        (d / "run_probe.py").write_text("import sys\nprint('ARGV', sys.argv[1:])\nprint('PYC', sys.flags.dont_write_bytecode, bool(sys.pycache_prefix))\n", encoding="utf-8")
        stub_env = {"BLARAI_PROBE_PYTHON": sys.executable, "BLARAI_PROBE_SELFTEST": "1"}
        good2 = "\n".join(f"{run_probe.sha256_of(d / n)}  {n}" for n in names) + "\n"
        ap.write_text(good2, encoding="utf-8")
        r = run(ap, "-SelfTestElevation", "elevated", "--arms", "A", env=stub_env)
        check("launch.ps1 prints PROBE_EXIT=0 on a clean exit", r.returncode == 0 and "PROBE_EXIT=0" in r.stdout, r.stdout + r.stderr)
        own = run_probe.sha256_of(d / "launch.ps1")
        check("launch.ps1 starts the probe and passes its own sha256 and the probe args",
              r.returncode == 0 and f"--launch-sha256', '{own}'" in r.stdout and "'--arms', 'A'" in r.stdout, r.stdout + r.stderr)
        r = run(ap, "-SelfTestElevation", "standard", "--arms", "A", env=stub_env)
        check("launch.ps1 refuses a live run when not elevated and says why", r.returncode == 1 and "elevated" in r.stdout and "ARGV" not in r.stdout, r.stdout + r.stderr)
        check("launch.ps1 prints PROBE_EXIT=1 on a refusal", "PROBE_EXIT=1" in r.stdout, r.stdout)
        r = run(ap, "-SelfTestElevation", "elevated", "-out", str(d / "o ut"), "--arms", "A", env=stub_env)
        check("launch.ps1 passes -out DIR through as --out DIR (no ambiguous-parameter failure)",
              r.returncode == 0 and "'--out'" in r.stdout and "o ut" in r.stdout, r.stdout + r.stderr)
        r = run(ap, "-SelfTestElevation", "elevated", "--out", str(d / "o2"), "--arms", "A", env=stub_env)
        check("launch.ps1 given `--out DIR` passes exactly one --out DIR on (the -out alias catches it; no ambiguity error)",
              r.returncode == 0 and r.stdout.count("'--out'") == 1 and "o2" in r.stdout, r.stdout + r.stderr)
        r = run(ap, "-SelfTestElevation", "elevated", "--launch-sha256", "x", "--arms", "A", env=stub_env)
        check("launch.ps1 refuses --launch-sha256 in the probe args (set by the launcher)",
              r.returncode == 1 and "ARGV" not in r.stdout and "PROBE_EXIT=1" in r.stdout, r.stdout + r.stderr)
        r = run(ap, "-SelfTestElevation", "standard", "-SelfTestIntegrity", "medium", "--token", "standard", "--arms", "A", env=stub_env)
        check("launch.ps1 binds `--token` to its own -Token (never a second --token for the probe): exactly one --token reaches it",
              r.returncode == 0 and r.stdout.count("'--token'") == 1 and "'--token', 'standard'" in r.stdout, r.stdout + r.stderr)
        r = run(ap, "-SelfTestElevation", "elevated", "--token", "x", "--arms", "A", env=stub_env)
        check("launch.ps1 given an invalid `--token x` fails closed: nothing starts, no PROBE_EXIT=0",
              r.returncode != 0 and "ARGV" not in r.stdout and "PROBE_EXIT=0" not in r.stdout, r.stdout + r.stderr)
        r = run(ap, "-VerifyOnly", "-Token", "standard", "-SelfTestElevation", "elevated", "-SelfTestIntegrity", "high", env=stub_env)
        check("launch.ps1 -VerifyOnly -Token standard checks the token too (elevated -> refused)",
              r.returncode == 1 and "NON-elevated" in r.stdout, r.stdout + r.stderr)
        r = run(ap, "-VerifyOnly", "-Token", "standard", "-SelfTestElevation", "standard", "-SelfTestIntegrity", "medium", env=stub_env)
        check("launch.ps1 -VerifyOnly -Token standard accepts a non-elevated Medium token and starts nothing",
              r.returncode == 0 and "VERIFY-ONLY" in r.stdout and "ARGV" not in r.stdout, r.stdout + r.stderr)
        pyc_before = {p.name for p in Path(tempfile.gettempdir()).glob("mxc-probe-pyc-*")}
        run(ap, "-SelfTestElevation", "elevated", "--arms", "A", env=stub_env)
        check("launch.ps1 removes the pycache folder it created after the launch",
              {p.name for p in Path(tempfile.gettempdir()).glob("mxc-probe-pyc-*")} <= pyc_before)
        r = run(ap, "-SelfTestElevation", "standard", "--dry-run-only", env=stub_env)
        check("launch.ps1 allows --dry-run-only without elevation", r.returncode == 0 and "--dry-run-only" in r.stdout, r.stdout + r.stderr)
        r = run(ap, "-Token", "standard", "-SelfTestElevation", "elevated", "-SelfTestIntegrity", "high", "--arms", "A", env=stub_env)
        check("launch.ps1 -Token standard refuses an elevated token (live) and says why",
              r.returncode == 1 and "NON-elevated" in r.stdout and "ARGV" not in r.stdout, r.stdout + r.stderr)
        r = run(ap, "-Token", "standard", "-SelfTestElevation", "elevated", "-SelfTestIntegrity", "high", "--dry-run-only", env=stub_env)
        check("launch.ps1 -Token standard refuses an elevated token even for --dry-run-only",
              r.returncode == 1 and "NON-elevated" in r.stdout and "ARGV" not in r.stdout, r.stdout + r.stderr)
        r = run(ap, "-Token", "standard", "-SelfTestElevation", "standard", "-SelfTestIntegrity", "high", "--arms", "A", env=stub_env)
        check("launch.ps1 -Token standard refuses a non-elevated token that is not Medium integrity",
              r.returncode == 1 and "Medium-integrity" in r.stdout and "ARGV" not in r.stdout, r.stdout + r.stderr)
        r = run(ap, "-Token", "standard", "-SelfTestElevation", "standard", "-SelfTestIntegrity", "medium", "--arms", "A", env=stub_env)
        check("launch.ps1 -Token standard starts a LIVE run from a non-elevated Medium token and passes --token standard on",
              r.returncode == 0 and "'--token', 'standard'" in r.stdout and "'--arms', 'A'" in r.stdout, r.stdout + r.stderr)
        r = run(ap, "-SelfTestElevation", "elevated", "--arms", "A", env=stub_env)
        check("launch.ps1 default mode passes --token elevated on (the mode of the earlier elevated record)",
              r.returncode == 0 and "'--token', 'elevated'" in r.stdout, r.stdout + r.stderr)
        check("launch-standard.cmd exists, calls launch.ps1 with -Token standard and does not ask for elevation",
              "-Token standard" in (HERE / "launch-standard.cmd").read_text(encoding="ascii")
              and "-Token" not in (HERE / "launch.cmd").read_text(encoding="ascii"))
        check("launch.ps1 runs the probe with -I -B and a fresh pycache prefix", "PYC 1 True" in run(ap, "-SelfTestElevation", "elevated", env=stub_env).stdout)
        r = run(ap, "-SelfTestElevation", "elevated", "--arms", "A", env={"BLARAI_PROBE_PYTHON": sys.executable})
        real_elevated = run_probe.is_elevated()
        check("launch.ps1 ignores -SelfTestElevation without the self-test environment variable (real detection applies)",
              (r.returncode == 0) == real_elevated, r.stdout + r.stderr)
        (d / "__pycache__").mkdir()
        (d / "__pycache__" / "summarise.cpython-314.pyc").write_bytes(b"x")
        r = run(ap, "-SelfTestElevation", "elevated", "--arms", "A", env=stub_env)
        check("launch.ps1 refuses to start when a compiled Python file is present in the probe folder",
              r.returncode == 1 and "compiled Python files" in r.stdout and "ARGV" not in r.stdout, r.stdout + r.stderr)
        shutil.rmtree(d / "__pycache__")
        ap.write_text(good2, encoding="utf-8")
        (d / "proxy.py").unlink()
        r = run(ap, "-VerifyOnly")
        check("launch.ps1 refuses a missing probe file", r.returncode == 1 and "file missing: proxy.py" in r.stdout, r.stdout + r.stderr)


# ------------------------------------------------------------------ end to end against a fake launcher

FAKE_LAUNCHER = r'''
import json, os, runpy, shlex, socket, sys
args = sys.argv[1:]
mode = os.environ.get("FAKE_MODE", "fenced")
if args == ["--probe"]:
    print(json.dumps({"tier": "base-container", "probes": {"baseContainerSupportsIdentitylessLoopbackProxy": os.environ.get("FAKE_FLAG", "true") == "true"}}))
    sys.exit(0)
cfg = json.load(open(args[0], encoding="utf-8"))
if "--dry-run" in args:
    if mode == "refuse":
        print(json.dumps({"code": "policy_validation", "message": "policy refused by the fake launcher"}), file=sys.stderr)
        sys.exit(1)
    sys.exit(0)
logpath = args[args.index("--log-file") + 1] if "--log-file" in args else None
def write_log(text):
    if logpath:
        open(logpath, "w", encoding="utf-8").write(text)
if mode == "launchrefuse":
    write_log("policy rejected before any process was created")
    print(json.dumps({"code": "policy_validation", "message": "launch refused by the fake launcher"}), file=sys.stderr)
    sys.exit(3)
write_log("process created (PID: 1)")
if mode == "deadstart":
    print("OSError: [Errno 22] Invalid argument", file=sys.stderr)
    sys.exit(1)
toks = [t.strip('"') for t in shlex.split(cfg["process"]["commandLine"], posix=False)]
proxy_port = int(cfg["runtimeConfig"]["networkProxy"].rsplit(":", 1)[1])
target_port = int(toks[toks.index("--target-port") + 1])
orig = socket.create_connection
if mode == "stray":
    orig(("127.0.0.1", target_port), timeout=3).close()
def patched(addr, *a, **k):
    host, port = addr
    if mode == "open":
        return orig(addr, *a, **k)
    if mode in ("fenced", "stray", "crash", "exit7", "plaintoken") and port == proxy_port:
        return orig(addr, *a, **k)
    if mode == "timeout" and port == proxy_port:
        return orig(addr, *a, **k)
    if mode == "timeout":
        raise TimeoutError("timed out")
    raise OSError(0, "fake fence", None, 10013)
socket.create_connection = patched
sys.argv = [toks[2]] + toks[3:]
code = 0
try:
    runpy.run_path(toks[2], run_name="__main__")
except SystemExit as e:
    code = e.code or 0
outp = toks[toks.index("--out") + 1]
if mode != "crash" and os.path.exists(outp) and mode != "plaintoken":
    rec = json.load(open(outp, encoding="utf-8"))
    rec["token"] = {"user_sid": "S-1-5-21-1-2-3-1001", "is_appcontainer": True, "appcontainer_sid": "S-1-15-2-1-2-3-4-5-6-7",
                    "integrity_sid": "S-1-16-4096", "elevated": False}
    json.dump(rec, open(outp, "w", encoding="utf-8"))
if mode == "crash":
    os.unlink(toks[toks.index("--out") + 1])
    print("error: request refused: payload crashed", file=sys.stderr)
    sys.exit(1)
if mode == "exit7":
    sys.exit(7)
sys.exit(code)
'''


def run_harness(td: Path, arm: str, mode: str, flag: str = "true", runs: int = 3, commit: str | None = "a" * 40,
                out: Path | None = None, extra_args: list[str] | None = None) -> tuple[int, str, Path]:
    fake_py = td / "fake_wxc.py"
    fake_py.write_text(FAKE_LAUNCHER, encoding="utf-8")
    bat = td / "fake_wxc.bat"
    bat.write_text(f'@echo off\r\n"{sys.executable}" "{fake_py}" %*\r\n', encoding="ascii")
    out = out or td / f"out-{arm}-{mode}-{flag}-{len(list(td.glob('out-*')))}"
    run_probe.LAUNCHERS[arm] = bat
    os.environ.update(FAKE_MODE=mode, FAKE_FLAG=flag)
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        extra = ["--arm-b-commit" if arm == "B" else "--arm-b0-commit", commit] if (commit and arm in ("B", "B0")) else []
        rc = run_probe.main(["--out", str(out), "--arms", arm, "--runs", str(runs), *extra, *(extra_args or [])])
    return rc, buf.getvalue(), out


def group(out: Path, key: str) -> dict:
    return json.loads((out / "batch-summary.json").read_text(encoding="utf-8"))["groups"][key]


def test_end_to_end() -> None:
    stand_log: list = []
    stand = ProbeListener("standin", "127.0.0.1", STAND_IN_PORT, stand_log, threading.Lock())
    orig_probe = net_payload.tcp_probe

    def remap(host: str, port: int, marker: str | None, timeout: float = 5.0) -> dict:
        if host == "1.1.1.1":
            return orig_probe("127.0.0.1", STAND_IN_PORT, marker, timeout)
        return orig_probe(host, port, marker, timeout)

    net_payload.tcp_probe = remap  # type: ignore[assignment]
    saved = (run_probe.TOOLCHAIN, run_probe.CONTAINER_PY, dict(run_probe.LAUNCHERS), run_probe.gateway_ip,
             run_probe.GATEWAY_PORTS, run_probe.snapshot)
    run_probe.gateway_ip = lambda: "127.0.0.1"  # type: ignore[assignment]
    run_probe.GATEWAY_PORTS = (STAND_IN_PORT,)
    try:
        with tempfile.TemporaryDirectory() as t:
            td = Path(t)
            run_probe.TOOLCHAIN, run_probe.CONTAINER_PY = td / "toolchain", Path(sys.executable)
            rc, text, out = run_harness(td, "B", "fenced")
            g = group(out, "B/B1")
            s = json.loads((out / "batch-summary.json").read_text(encoding="utf-8"))
            check("end to end, fenced fake launcher: batch HOLD over 3 runs", rc == 0 and g["verdict"] == "HOLD" and g["runs"] == 3, text[-600:] + json.dumps(s)[:500])
            check("end to end: unfenced control B5 passed", s["controls"]["ok"] is True, json.dumps(s["controls"]))
            rec = json.loads(sorted(out.glob("run-B-B1-*.json"))[0].read_text(encoding="utf-8"))
            check("run record carries policy, dry-run, launch, logs, machine, snapshots, unfenced pre/post; no ticket field",
                  all(k in rec for k in ("policy_as_submitted", "dry_run", "launch", "proxy_log", "target_log", "machine",
                                         "snapshot_before", "snapshot_after", "unfenced_pre", "unfenced_post"))
                  and "lan_log" not in rec and "ticket" not in rec and "windows_build" in rec["machine"], str(list(rec)))
            token_end_to_end(td)
            h = json.loads((out / "batch-header.json").read_text(encoding="utf-8"))
            check("batch header records arm-B commit, interpreter hashes, launch.ps1 hash, firewall product, gateway, scope note, host prep",
                  h["arm_commits"]["B"]["commit"] == "a" * 40 and h["arm_commits"]["A"]["release_tag"] == "v1.0.0" and "token_privileges" in h and len(h["interpreters"]["host"]["sha256"]) == 64
                  and len(h["interpreters"]["container"]["sha256"]) == 64 and len(h["launch_ps1_sha256"]) == 64
                  and "firewall_product" in h and "gateway" in h and "B" in h["scope_notes"] and "host_prep" in h, str(list(h)))
            check("batch header says whether --probe reports a PSEC version (false for the fake) and asserts none itself",
                  h["launchers"]["B"]["probe_reports_psec_version"] is False and "PSEC" not in json.dumps(h["scope_notes"]))
            rc, text, out = run_harness(td, "B", "open")
            runs = sorted(out.glob("run-B-B1-*.json"))
            check("end to end, open fake launcher: prints STOP line, returns 5, stops after the first FAIL",
                  rc == 5 and "STOP: FAIL condition met" in text and len(runs) == 1
                  and json.loads(runs[0].read_text(encoding="utf-8"))["verdict"]["verdict"] == "FAIL", f"rc={rc} runs={len(runs)} {text[-400:]}")
            rc, text, out = run_harness(td, "A", "refuse")
            r0 = json.loads(sorted(out.glob("run-A-A1-*.json"))[0].read_text(encoding="utf-8"))
            check("end to end, refusing launcher: batch REFUSED with the exact text and no launch",
                  group(out, "A/A1")["verdict"] == "REFUSED" and "policy refused by the fake launcher" in r0["dry_run"]["stderr"]
                  and r0["dry_run"]["rc"] == 1 and r0["launch"].get("skipped"))
            rc, text, out = run_harness(td, "B", "launchrefuse")
            r0 = json.loads(sorted(out.glob("run-B-B1-*.json"))[0].read_text(encoding="utf-8"))
            check("end to end, dry-run accepted but launch refused: batch REFUSED-AT-LAUNCH with the launch's own stderr",
                  group(out, "B/B1")["verdict"] == "REFUSED-AT-LAUNCH" and any("launch refused by the fake launcher" in x for x in r0["verdict"]["reasons"]),
                  json.dumps(r0["verdict"])[:400])
            rc, text, out = run_harness(td, "B", "deadstart")
            r0 = json.loads(sorted(out.glob("run-B-B1-*.json"))[0].read_text(encoding="utf-8"))
            check("end to end, the process was created but died before any traffic with 'Invalid' in stderr: INSTRUMENT-BLIND, not REFUSED-AT-LAUNCH",
                  r0["verdict"]["verdict"] == "INSTRUMENT-BLIND" and r0["mxc_log_full_text_has_process_start"] is True
                  and group(out, "B/B1")["verdict"] == "INSTRUMENT-BLIND", json.dumps(r0["verdict"])[:400])
            rc, text, out = run_harness(td, "B", "plaintoken")
            check("end to end, fenced but the payload's own token is not an AppContainer token: batch INSTRUMENT-BLIND, never HOLD",
                  group(out, "B/B1")["verdict"] == "INSTRUMENT-BLIND", json.dumps(group(out, "B/B1")))
            rc, text, out = run_harness(td, "B", "blind")
            check("end to end, proxy path blocked (B2 cannot pass): batch INSTRUMENT-BLIND", group(out, "B/B1")["verdict"] == "INSTRUMENT-BLIND")
            rc, text, out = run_harness(td, "B", "timeout")
            check("end to end, direct connects time out instead of being refused: batch INSTRUMENT-BLIND (a timeout is not a refusal)",
                  group(out, "B/B1")["verdict"] == "INSTRUMENT-BLIND", json.dumps(group(out, "B/B1")))
            rc, text, out = run_harness(td, "B", "stray")
            r0 = json.loads(sorted(out.glob("run-B-B1-*.json"))[0].read_text(encoding="utf-8"))
            check("end to end, an untagged connection to the second listener during the launch: run INSTRUMENT-BLIND, never HOLD",
                  r0["verdict"]["verdict"] == "INSTRUMENT-BLIND" and any("unexplained" in x for x in r0["verdict"]["reasons"]), json.dumps(r0["verdict"])[:400])
            counter = iter(range(10_000))
            run_probe.snapshot = lambda *a, **k: {"n": next(counter)}  # type: ignore[assignment]
            rc, text, out = run_harness(td, "B", "fenced")
            check("end to end, any change between the before and after snapshot stops the batch (STOP, exit 4) and the summary agrees",
                  rc == 4 and "STOP: changed state" in text and len(list(out.glob("run-B-B1-*.json"))) == 1
                  and group(out, "B/B1")["verdict"] == "STOPPED-STATE-CHANGE", f"rc={rc} {text[-300:]}")
            counter = iter(range(10_000))
            run_probe.snapshot = lambda *a, **k: {"n": 0 if next(counter) < 5 else 1}  # type: ignore[assignment]
            rc, text, out = run_harness(td, "B", "fenced")
            run_probe.snapshot = saved[5]  # type: ignore[assignment]
            check("end to end, state change only in the LAST run: exit 4 and the summary says STOPPED-STATE-CHANGE, not HOLD",
                  rc == 4 and len(list(out.glob("run-B-B1-*.json"))) == 3 and group(out, "B/B1")["verdict"] == "STOPPED-STATE-CHANGE",
                  f"rc={rc} {json.dumps(group(out, 'B/B1'))}")
            rc, text, out = run_harness(td, "B", "crash")
            r0 = json.loads(sorted(out.glob("run-B-B1-*.json"))[0].read_text(encoding="utf-8"))
            check("end to end, container ran then the launcher failed with refusal-like text and no report: INSTRUMENT-BLIND, not REFUSED-AT-LAUNCH",
                  r0["verdict"]["verdict"] == "INSTRUMENT-BLIND" and group(out, "B/B1")["verdict"] == "INSTRUMENT-BLIND", json.dumps(r0["verdict"])[:400])
            rc, text, out = run_harness(td, "B", "exit7")
            r0 = json.loads(sorted(out.glob("run-B-B1-*.json"))[0].read_text(encoding="utf-8"))
            check("end to end, launcher exit 7 with a clean payload: HOLD, exit code recorded and flagged in the summary",
                  group(out, "B/B1")["verdict"] == "HOLD" and r0["launch"]["exit_code"] == 7
                  and len(group(out, "B/B1")["launcher_nonzero_exit_runs"]) == 3, json.dumps(group(out, "B/B1"))[:300])
            rc, text, out = run_harness(td, "B", "fenced", runs=1)
            before = json.loads((out / "batch-summary.json").read_text(encoding="utf-8"))
            with contextlib.redirect_stdout(io.StringIO()):
                summarise.main([str(out)])
            after = json.loads((out / "batch-summary.json").read_text(encoding="utf-8"))
            check("single-run batch: the standalone summariser agrees with the harness (HOLD for 1 expected run, flagged below the spec count)",
                  before["groups"] == after["groups"] and after["groups"]["B/B1"]["verdict"] == "HOLD" and after["below_spec_n"] is True and after["n_expected"] == 1,
                  json.dumps(after)[:300])
            rc2, text2, _ = run_harness(td, "B", "fenced", runs=1, out=out)
            check("a second batch into an output folder that already holds a batch header is refused",
                  rc == 0 and rc2 == 2 and "fresh output folder" in text2, text2[-200:])
            rc, text, out = run_harness(td, "B", "fenced", commit=None)
            check("arm B with no commit and an unknown launcher sha256: refused, nothing runs",
                  (out / "arm-B-refused.json").exists() and not list(out.glob("run-*.json")) and "known-build" in text, text[-300:])
            bat_sha = run_probe.sha256_of(td / "fake_wxc.bat")
            run_probe.KNOWN_BUILDS[bat_sha] = "b" * 40
            rc, text, out = run_harness(td, "B", "fenced", commit=None, runs=1)
            h = json.loads((out / "batch-header.json").read_text(encoding="utf-8"))
            check("arm B with no commit but a launcher sha256 in the known-build table: runs, basis recorded from the table",
                  rc == 0 and h["arm_commits"]["B"]["commit"] == "b" * 40 and "known-build table" in h["arm_commits"]["B"]["basis"], text[-300:])
            rc, text, out = run_harness(td, "B", "fenced", commit="c" * 40, runs=1)
            check("arm B with a commit that contradicts the known-build table: refused",
                  (out / "arm-B-refused.json").exists() and not list(out.glob("run-*.json")), text[-300:])
            del run_probe.KNOWN_BUILDS[bat_sha]
            rc, text, out = run_harness(td, "B", "fenced", flag="false")
            refusal = out / "arm-B-refused.json"
            check("end to end, arm B with the proxy flag false: refused, recorded, no run records",
                  refusal.exists() and not list(out.glob("run-*.json")) and "REFUSED" in text
                  and run_probe.PROXY_FLAG in json.loads(refusal.read_text(encoding="utf-8"))["reason"], text[-300:])
            run_probe.LAUNCHERS["B"] = td / "absent" / "wxc-exec.exe"
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                run_probe.main(["--out", str(td / "out-absent"), "--arms", "B", "--runs", "1"])
            check("arm B with the launcher file absent: refused cleanly",
                  (td / "out-absent" / "arm-B-refused.json").exists() and "absent" in buf.getvalue())
    finally:
        net_payload.tcp_probe = orig_probe  # type: ignore[assignment]
        (run_probe.TOOLCHAIN, run_probe.CONTAINER_PY, _, run_probe.gateway_ip, run_probe.GATEWAY_PORTS,
         run_probe.snapshot) = saved  # type: ignore[assignment]
        run_probe.LAUNCHERS.clear()
        run_probe.LAUNCHERS.update(saved[2])
        stand.close()


MEDIUM = {"is_user_an_admin": False, "elevated": False, "elevation_type": "limited",
          "integrity_sid": "S-1-16-8192", "integrity_name": "Medium"}
HIGH = {"is_user_an_admin": True, "elevated": True, "elevation_type": "full",
        "integrity_sid": "S-1-16-12288", "integrity_name": "High"}


class _FakeKey:
    def __init__(self, tree: dict, path: str) -> None:
        self.tree, self.path = tree, path

    def __enter__(self) -> "_FakeKey":
        return self

    def __exit__(self, *exc: object) -> None:
        return None


class _FakeWinreg:
    """winreg stand-in: a flat {sid: moniker | None} mapping table under the AppContainer key. `None` = no Moniker value."""
    HKEY_CURRENT_USER = 1

    def __init__(self, table: dict | None) -> None:
        self.table = table

    def OpenKey(self, parent: object, sub: str) -> _FakeKey:  # noqa: N802
        if self.table is None:
            raise FileNotFoundError(sub)
        if isinstance(parent, _FakeKey):
            if sub not in self.table:
                raise FileNotFoundError(sub)
            return _FakeKey(self.table, sub)
        return _FakeKey(self.table, "")

    def EnumKey(self, key: _FakeKey, i: int) -> str:  # noqa: N802
        keys = sorted(key.tree)
        if i >= len(keys):
            raise OSError("no more")
        return keys[i]

    def QueryValueEx(self, key: _FakeKey, name: str) -> tuple[str, int]:  # noqa: N802
        if key.tree[key.path] is None:
            raise FileNotFoundError(name)
        return key.tree[key.path], 1


def test_appcontainer_attribution() -> None:
    saved = run_probe.winreg
    base = {"S-1-15-2-1": "microsoft.windows.cortana", "S-1-15-2-2": "windowsworkload.x"}
    try:
        def snap_of(table: dict | None) -> dict:
            run_probe.winreg = _FakeWinreg(table)  # type: ignore[assignment]
            own, foreign, total = run_probe.appcontainer_mappings()
            return {"appcontainer_mappings": own, "appcontainer_foreign_count": foreign, "appcontainer_total": total, "other": 1}

        before = snap_of(base)
        check("AppContainer snapshot lists the non-foreign mappings by SID and name and counts the rest",
              before["appcontainer_mappings"] == ["S-1-15-2-1 microsoft.windows.cortana", "S-1-15-2-2 windowsworkload.x"]
              and before["appcontainer_foreign_count"] == 0 and before["appcontainer_total"] == 2, str(before))
        churn = snap_of({**base, "S-1-15-2-9": "mxcfx-denied-1234", "S-1-15-2-8": "mxcfx-redir-77"})
        check("a foreign tool's mxcfx-* profiles appearing during a run do NOT change the compared state",
              run_probe.state_changes(before, churn) == {}, str(run_probe.state_changes(before, churn)))
        check("the foreign churn is recorded (foreign count and total), not silently ignored",
              churn["appcontainer_foreign_count"] == 2 and churn["appcontainer_total"] == 4, str(churn))
        leftover = snap_of({**base, "S-1-15-2-7": "mxc-proxy-probe-run1"})
        check("a profile this probe's launch leaves behind (no foreign prefix) changes the state -> reported",
              list(run_probe.state_changes(before, leftover)) == ["appcontainer_mappings"], str(run_probe.state_changes(before, leftover)))
        gone = snap_of({"S-1-15-2-1": "microsoft.windows.cortana"})
        check("a removed non-foreign mapping changes the state too", "appcontainer_mappings" in run_probe.state_changes(before, gone))
        check("a mapping with no Moniker value is compared by SID and reads as unreadable-name, not skipped",
              snap_of({**base, "S-1-15-2-6": None})["appcontainer_mappings"][-1].endswith("<unreadable>"))
        check("an absent AppContainer key is recorded as <absent>/unreadable", snap_of(None)["appcontainer_mappings"] == ["<absent>"]
              and snap_of(None)["appcontainer_total"] == "unreadable")
        check("TOGGLE: with the foreign prefix list emptied the same foreign churn WOULD change the state",
              (setattr(run_probe, "FOREIGN_AC_PREFIXES", ()) or True) and run_probe.state_changes(before, snap_of({**base, "S-1-15-2-9": "mxcfx-denied-1234"})) != {})
    finally:
        run_probe.winreg = saved  # type: ignore[assignment]
        run_probe.FOREIGN_AC_PREFIXES = ("mxcfx-",)
    check("recorded-only fields (foreign count, total) never appear in the state-change dict",
          run_probe.state_changes({"appcontainer_total": 1, "a": 1}, {"appcontainer_total": 2, "a": 1}) == {})


def test_token_modes() -> None:
    pr = run_probe.token_mode_problem
    check("token_mode_problem: standard accepts a non-elevated Medium token", pr("standard", MEDIUM) is None)
    check("token_mode_problem: standard refuses an elevated High token", pr("standard", HIGH) is not None)
    check("token_mode_problem: standard refuses a non-elevated token whose integrity is not Medium",
          pr("standard", dict(MEDIUM, integrity_sid="S-1-16-4096")) is not None)
    check("token_mode_problem: standard refuses a token whose elevation could not be read (None is not a pass)",
          pr("standard", dict(MEDIUM, elevated=None)) is not None and pr("standard", dict(MEDIUM, integrity_sid=None)) is not None)
    check("token_mode_problem: elevated mode is not enforced here (launch.ps1 owns it)", pr("elevated", MEDIUM) is None)
    live = run_probe.token_info()
    check("token_info reads IsUserAnAdmin, elevation, type and integrity SID of this process",
          isinstance(live["is_user_an_admin"], bool) and isinstance(live["elevated"], bool)
          and live["elevation_type"] in ("default", "full", "limited") and str(live["integrity_sid"]).startswith("S-1-16-"), str(live))
    grp = run_probe.groups_summary()
    check("groups_summary reports the mandatory label, the Administrators state and a group count",
          grp["integrity_label"] is not None and grp["administrators"] in ("absent", "deny-only", "enabled") and grp["group_count"] > 0, str(grp))
    check("unreadable_keys lists a string read that failed and a list read that failed, not a readable value",
          run_probe.unreadable_keys({"a": "unreadable: not elevated", "b": ["<unreadable: error 5>"], "c": 7, "d": ["ok"]}) == ["a", "b"])
    # summarise
    def tokrec(tok: dict, mode: str = "standard", **kw: object) -> dict:
        return dict(syn(**kw), token=dict(tok, mode=mode))  # type: ignore[arg-type]

    v = summarise.judge_run(tokrec(MEDIUM))
    check("standard-mode record with a Medium token and full controls -> HOLD, mode carried", v["verdict"] == "HOLD" and v["token_mode"] == "standard", str(v))
    v = summarise.judge_run(tokrec(HIGH))
    check("TOGGLE contrast: the same record with an elevated token under standard mode -> INSTRUMENT-BLIND, never HOLD",
          v["verdict"] == "INSTRUMENT-BLIND" and any("not a non-elevated Medium" in r for r in v["reasons"]), str(v))
    check("standard-mode record with an unreadable token -> INSTRUMENT-BLIND",
          summarise.judge_run(tokrec(dict(MEDIUM, elevated=None)))["verdict"] == "INSTRUMENT-BLIND")
    check("elevated-mode record with a High token is not penalised (case-one mode)", summarise.judge_run(tokrec(HIGH, "elevated"))["verdict"] == "HOLD")
    check("a standard-mode dry-run refusal under an elevated token is not reported as REFUSED",
          summarise.judge_run(tokrec(HIGH, dry_rc=1, with_payload=False))["verdict"] == "INSTRUMENT-BLIND")
    ref = summarise.judge_run(tokrec(MEDIUM, dry_rc=1, with_payload=False))
    check("a standard-mode dry-run refusal under a Medium token is REFUSED with the exact text and the mode",
          ref["verdict"] == "REFUSED" and "refused text" in ref["reasons"][0] and ref["token_mode"] == "standard", str(ref))
    # never HOLD without the positive control or an attempt that reached the payload
    check("B2 failed (2 of 3) -> never HOLD", verdict(tokrec(MEDIUM, b2=2)) != "HOLD")
    check("B2 absent (0 of 3) -> never HOLD", verdict(tokrec(MEDIUM, b2=0)) != "HOLD")
    check("no payload report (launch produced nothing) -> never HOLD", verdict(tokrec(MEDIUM, with_payload=False)) != "HOLD")
    check("launch crashed with no payload and no refusal text -> INSTRUMENT-BLIND (launch failed, not answered)",
          verdict(tokrec(MEDIUM, with_payload=False, launch_exit=-1073741819, stderr="", mxc_log="")) == "INSTRUMENT-BLIND")
    empty = tokrec(MEDIUM)
    empty["payload"] = dict(empty["payload"], b3={}, b4ii={})
    ev = summarise.judge_run(empty)
    check("empty B3 and B4(ii) reports (no direct attempt recorded) -> INSTRUMENT-BLIND, never HOLD",
          ev["verdict"] == "INSTRUMENT-BLIND" and any("empty" in r for r in ev["reasons"]), str(ev))
    ctl_ok = {"tag": "C1", "target_log": [{"marker": "C1-b5a-1"}], "b5b": {"connected": True}, "b5c": {"connected": True}}
    runs = [tokrec(MEDIUM, tag=f"R{i}") for i in range(3)]
    for label, ctl in (("failed B5 controls", dict(ctl_ok, b5c={"connected": False})), ("no B5 control record", None)):
        g = summarise.judge_batch(runs, ctl)["groups"]["B/B1"]
        check(f"batch of Medium-token HOLD runs with {label} -> INSTRUMENT-BLIND, never HOLD", g["verdict"] == "INSTRUMENT-BLIND", str(g))
    g = summarise.judge_batch(runs, ctl_ok)["groups"]["B/B1"]
    check("batch of Medium-token HOLD runs with passing controls -> HOLD and carries token_modes", g["verdict"] == "HOLD" and g["token_modes"] == ["standard"], str(g))
    # harness refusal (nothing is started, so no listeners are needed)
    saved_ti = run_probe.token_info
    try:
        with tempfile.TemporaryDirectory() as t:
            out = Path(t) / "refused-out"
            buf = io.StringIO()
            run_probe.token_info = lambda: dict(HIGH)  # type: ignore[assignment]
            with contextlib.redirect_stdout(buf):
                rc = run_probe.main(["--out", str(out), "--arms", "A", "--token", "standard", "--dry-run-only"])
            check("run_probe --token standard from an elevated token is refused (exit 2), nothing written",
                  rc == 2 and "REFUSED" in buf.getvalue() and not out.exists(), buf.getvalue())
    finally:
        run_probe.token_info = saved_ti  # type: ignore[assignment]


def token_end_to_end(td: Path) -> None:
    """Called from test_end_to_end, inside its stand-in listener and remaps."""
    saved_ti = run_probe.token_info
    try:
        run_probe.token_info = lambda: dict(MEDIUM)  # type: ignore[assignment]
        rc, text, out = run_harness(td, "A", "fenced", runs=1, extra_args=["--token", "standard"])
        h = json.loads((out / "batch-header.json").read_text(encoding="utf-8"))
        rec = json.loads(next(out.glob("run-A-A1-*.json")).read_text(encoding="utf-8"))
        ctl = json.loads((out / "control-b5.json").read_text(encoding="utf-8"))
        need = {"mode", "is_user_an_admin", "elevated", "elevation_type", "integrity_sid", "integrity_name", "groups"}
        check("batch header, run record and control record carry the token mode, IsUserAnAdmin, integrity SID and groups summary",
              rc == 0 and h["token_mode"] == "standard" and need <= set(h["token"]) and need <= set(rec["token"])
              and need <= set(ctl["token"]) and rec["token"]["mode"] == "standard" and rec["token"]["integrity_sid"] == "S-1-16-8192",
              text[-300:] + str(set(rec.get("token", {}))))
        check("header lists what this token could not read; the snapshot carries the same list",
              isinstance(h["unreadable_under_this_token"], list) and isinstance(rec["snapshot_before"]["unreadable"], list))
        rc, text, out = run_harness(td, "A", "fenced", runs=1, extra_args=["--token", "standard", "--dry-run-only"])
        dr = json.loads(next(out.glob("dryrun-A-A1.json")).read_text(encoding="utf-8"))
        check("dry-run-only record carries the token mode and integrity SID",
              dr["token"]["mode"] == "standard" and dr["token"]["integrity_sid"] == "S-1-16-8192")
    finally:
        run_probe.token_info = saved_ti  # type: ignore[assignment]


# ------------------------------------------------------------------ variant 4: WFP capture and F3

CSID = "S-1-15-2-1-2-3-4-5-6-7"
USID = "S-1-5-21-9-8-7-1001"


def wfp_item(key: str, name: str = "n", layer: str = "FWPM_LAYER_ALE_AUTH_CONNECT_V4",
             action: str = "FWP_ACTION_BLOCK", sid: str | None = None) -> str:
    cond = (f"<filterCondition numItems=\"1\"><item><fieldKey>FWPM_CONDITION_ALE_PACKAGE_ID</fieldKey>"
            f"<conditionValue><type>FWP_SID</type><sid>{sid}</sid></conditionValue></item></filterCondition>"
            if sid else "<filterCondition/>")
    return (f"<item><filterKey>{{{key}}}</filterKey><displayData><name>{name}</name></displayData>"
            f"<layerKey>{layer}</layerKey>{cond}<action><type>{action}</type></action></item>")


def wfp_doc(*items: str) -> str:
    return "<?xml version=\"1.0\" encoding=\"UTF-8\"?><wfpdiag><filters>" + "".join(items) + "</filters></wfpdiag>"


BASE = (wfp_item("aaaa0001"), wfp_item("aaaa0002", sid="S-1-0-0"))


def test_wfp_analysis() -> None:
    plain = wfp_doc(*BASE)
    with_c = wfp_doc(*BASE, wfp_item("bbbb0001", "mxc-filter", sid=CSID))
    with_u = wfp_doc(*BASE, wfp_item("bbbb0002", "user-filter", sid=USID))
    a = summarise.analyse_wfp(plain, with_c, plain, CSID, USID, True)
    check("variant 4: delta filter naming the container SID -> FILTERS-PRESENT with layer, action, name, delta count 1",
          a["reading"] == "FILTERS-PRESENT" and a["wfp_delta_count"] == 1
          and a["wfp_filters_referencing_container_sid"] == [{"key": "{bbbb0001}", "name": "mxc-filter",
                                                              "layer": "FWPM_LAYER_ALE_AUTH_CONNECT_V4",
                                                              "action": "FWP_ACTION_BLOCK"}], json.dumps(a)[:400])
    b = summarise.analyse_wfp(plain, wfp_doc(*BASE, wfp_item("cccc0001")), plain, CSID, USID, True)
    check("variant 4: unrelated delta, no filter naming the container SID -> CAPABILITY-ONLY-SUPPORTED, delta count 1",
          b["reading"] == "CAPABILITY-ONLY-SUPPORTED" and b["wfp_delta_count"] == 1, json.dumps(b)[:300])
    c = summarise.analyse_wfp(plain, plain, plain, CSID, USID, True)
    check("variant 4: no delta -> CAPABILITY-ONLY-SUPPORTED with delta count 0",
          c["reading"] == "CAPABILITY-ONLY-SUPPORTED" and c["wfp_delta_count"] == 0)
    d = summarise.analyse_wfp(plain, plain, plain, CSID, USID, False)
    check("variant 4: container not alive at capture -> INSTRUMENT-BLIND, never 'no filters'",
          d["reading"] == "INSTRUMENT-BLIND" and d["capture_during_container_alive"] is False)
    check("TOGGLE: alive check off -> the same not-alive capture reads CAPABILITY-ONLY (the check is what blinds it)",
          summarise.analyse_wfp(plain, plain, plain, CSID, USID, False, disable=("alive",))["reading"] == "CAPABILITY-ONLY-SUPPORTED")
    e = summarise.analyse_wfp(plain, None, plain, CSID, USID, True, ["during filters: netsh rc=1"])
    check("variant 4: failed during capture -> INSTRUMENT-BLIND", e["reading"] == "INSTRUMENT-BLIND" and e["problems"])
    f = summarise.analyse_wfp(plain, "<wfpdiag><filters/></wfpdiag>", plain, CSID, USID, True)
    check("variant 4: empty during dump -> INSTRUMENT-BLIND", f["reading"] == "INSTRUMENT-BLIND")
    check("TOGGLE: empty check off -> an empty during dump reads CAPABILITY-ONLY",
          summarise.analyse_wfp(plain, "<wfpdiag><filters/></wfpdiag>", plain, CSID, USID, True, disable=("empty",))["reading"] == "CAPABILITY-ONLY-SUPPORTED")
    g = summarise.analyse_wfp(plain, plain, plain, None, USID, True)
    check("variant 4: container SID unknown -> INSTRUMENT-BLIND", g["reading"] == "INSTRUMENT-BLIND")
    h = summarise.analyse_wfp(plain, with_u, plain, CSID, USID, True)
    check("variant 4: a delta filter naming only the user SID is listed apart and does not count as a container filter",
          h["reading"] == "CAPABILITY-ONLY-SUPPORTED" and len(h["wfp_delta_filters_referencing_user_sid"]) == 1)
    utf16 = summarise.decode_wfp(("\ufeff" + plain).encode("utf-16"))
    check("variant 4: UTF-16 netsh output decodes and parses", len(summarise.wfp_filters(utf16)) == 2)
    try:
        summarise.wfp_filters("not xml")
        ok = False
    except ValueError:
        ok = True
    check("variant 4: unparseable dump raises ValueError (becomes a BLIND reason)", ok)


def wrec(tag: str, reading_kw: dict) -> dict:
    plain = wfp_doc(*BASE)
    during = reading_kw.pop("during", plain)
    r = syn(tag)
    r["wfp"] = summarise.analyse_wfp(plain, during, plain, CSID, USID, reading_kw.pop("alive", True), **reading_kw)
    return r


def test_variant4_group() -> None:
    ok_ctl = {"ok": True, "problems": []}
    bad_ctl = {"ok": False, "problems": ["analysis found no filter naming the control SID"]}
    plain = wfp_doc(*BASE)
    with_c = wfp_doc(*BASE, wfp_item("bbbb0001", "mxc-filter", sid=CSID))
    clean = [wrec("R1", {}), wrec("R2", {}), wrec("R3", {})]
    v = lambda runs, ctl, **kw: summarise.judge_variant4(runs, ctl, **kw)["verdict"]  # noqa: E731
    check("variant 4 group: no container-SID filter, control found, all captures alive -> CAPABILITY-ONLY-SUPPORTED",
          v(clean, ok_ctl) == "CAPABILITY-ONLY-SUPPORTED")
    check("variant 4 group: positive control not found -> INSTRUMENT-BLIND",
          v(clean, bad_ctl) == "INSTRUMENT-BLIND" and v(clean, None) == "INSTRUMENT-BLIND")
    check("TOGGLE: control requirement off -> the same batch reads CAPABILITY-ONLY (the control is what blinds it)",
          v(clean, bad_ctl, disable=("control",)) == "CAPABILITY-ONLY-SUPPORTED")
    check("variant 4 group: one launch not alive at capture -> INSTRUMENT-BLIND",
          v([wrec("R1", {}), wrec("R2", {"alive": False})], ok_ctl) == "INSTRUMENT-BLIND")
    check("variant 4 group: a run with no wfp record is never read as clean -> INSTRUMENT-BLIND",
          v(clean[:2] + [syn("R3")], ok_ctl) == "INSTRUMENT-BLIND")
    hit = summarise.judge_variant4([wrec("R1", {"during": with_c}), wrec("R2", {})], ok_ctl)
    check("variant 4 group: any filter naming a container SID -> FILTERS-PRESENT, listed with its run tag",
          hit["verdict"] == "FILTERS-PRESENT" and hit["filters_referencing_container_sid"][0]["tag"] == "R1"
          and hit["filters_referencing_container_sid"][0]["layer"], json.dumps(hit)[:300])
    check("variant 4 group: FILTERS-PRESENT holds even when the control failed (an observed filter is an observation)",
          v([wrec("R1", {"during": with_c})], bad_ctl) == "FILTERS-PRESENT")
    batch = summarise.judge_batch(clean, ctl_ok(), 3, wfp_control=ok_ctl, unreadable=["wfp_mxc_filters"])
    check("batch summary carries variant4_wfp verdict and the egress verdict logic is unchanged",
          batch["variant4_wfp"]["verdict"] == "CAPABILITY-ONLY-SUPPORTED" and batch["groups"]["B/B1"]["verdict"] == "HOLD",
          json.dumps(batch)[:300])
    check("batch summary without wfp runs carries no variant4_wfp",
          "variant4_wfp" not in summarise.judge_batch([syn("R1"), syn("R2"), syn("R3")], ctl_ok(), 3))


def ctl_ok() -> dict:
    tag = "ctl-1"
    return {"tag": tag, "target_log": [{"marker": f"{tag}-b5a-1", "ts": INSIDE}], "b5b": {"connected": True},
            "b5c": {"connected": True}}


def test_f3() -> None:
    runs = [syn("R1"), syn("R2"), syn("R3")]
    plain = summarise.judge_batch(runs, ctl_ok(), 3, unreadable=["wfp_mxc_filters"])
    check("F3: records carrying state_changed_by_run {} -> HOLD (control for the missing-key case)",
          plain["groups"]["B/B1"]["verdict"] == "HOLD", json.dumps(plain["groups"])[:300])
    missing = [dict(r) for r in runs]
    del missing[1]["state_changed_by_run"]
    res = summarise.judge_batch(missing, ctl_ok(), 3, unreadable=["wfp_mxc_filters"])
    g = res["groups"]["B/B1"]
    check("F3: a record without state_changed_by_run is never read as 'no change' -> INCOMPLETE, run listed",
          g["verdict"] == "INCOMPLETE" and g["state_unknown_runs"] == ["R2"], json.dumps(g)[:300])
    check("F3: batch summary carries the header's unreadable_under_this_token list",
          res["unreadable_under_this_token"] == ["wfp_mxc_filters"] and plain["unreadable_under_this_token"] == ["wfp_mxc_filters"])
    with tempfile.TemporaryDirectory() as t:
        d = Path(t)
        (d / "batch-header.json").write_text(json.dumps({"runs_per_arm": 3, "unreadable_under_this_token": ["x"]}), encoding="utf-8")
        for i, r in enumerate(runs):
            (d / f"run-{i}.json").write_text(json.dumps(r), encoding="utf-8")
        (d / "control-b5.json").write_text(json.dumps(ctl_ok()), encoding="utf-8")
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            summarise.main([str(d)])
        out = json.loads((d / "batch-summary.json").read_text(encoding="utf-8"))
    check("F3: summarise.py's own main also writes the header's unreadable list", out["unreadable_under_this_token"] == ["x"])


def test_hold_and_refusals() -> None:
    with tempfile.TemporaryDirectory() as t:
        td = Path(t)
        ready, release = td / "ready.json", td / "release"
        res: dict = {"token": {"x": 1}}
        th = threading.Thread(target=lambda: net_payload.hold_for_release(ready, release, 10, res))
        th.start()
        waited = 0.0
        while not ready.exists() and waited < 5:
            time.sleep(0.05)
            waited += 0.05
        info = json.loads(ready.read_text(encoding="utf-8"))
        still_held = th.is_alive()
        release.write_text("r", encoding="utf-8")
        th.join(5)
        check("hold point: ready file carries the pid and token; payload stays held until release, then records released",
              info["pid"] == os.getpid() and info["token"] == {"x": 1} and still_held and res["hold"]["released"] is True, str(res))
        res2: dict = {}
        net_payload.hold_for_release(td / "r2.json", td / "never", 0.3, res2)
        check("hold point: with no release the hold times out and records released False", res2["hold"]["released"] is False, str(res2))
        res3: dict = {}
        net_payload.hold_for_release(td / "nodir" / "r.json", td / "x", 0.1, res3)
        check("hold point: an unwritable ready file is recorded, not skipped", res3["hold"]["ready_written"] is False)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = run_probe.main(["--out", str(td / "o1"), "--wfp-capture", "--token", "standard"])
        check("--wfp-capture is refused with --token standard (exit 2, nothing written)",
              rc == 2 and "REFUSED" in buf.getvalue() and not (td / "o1").exists(), buf.getvalue()[:200])
        saved = run_probe.is_elevated
        run_probe.is_elevated = lambda: True  # type: ignore[assignment]
        try:
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                rc = run_probe.main(["--out", str(td / "o2"), "--wfp-capture", "--dry-run-only"])
            check("--wfp-capture is refused with --dry-run-only", rc == 2 and "REFUSED" in buf.getvalue())
        finally:
            run_probe.is_elevated = saved  # type: ignore[assignment]
        if saved():
            check("(self-test ran elevated: the non-elevated refusal check skipped)", True)
        else:
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                rc = run_probe.main(["--out", str(td / "o3"), "--wfp-capture"])
            check("--wfp-capture is refused when the process is not elevated", rc == 2 and "REFUSED" in buf.getvalue())


def test_wfp_end_to_end() -> None:
    """Whole capture path with the real hold-point sync, a fake launcher and fake netsh: the container-SID filter
    appears only DURING the launch in one mode, never in the other."""
    plain = wfp_doc(*BASE)
    present = wfp_doc(*BASE, wfp_item("bbbb0001", "mxc-filter", sid="S-1-15-2-1-2-3-4-5-6-7"))
    state: dict = {"mode": "clean", "calls": []}

    def fake_netsh(kind: str, target: Path) -> tuple[bool, str]:
        target.parent.mkdir(parents=True, exist_ok=True)
        state["calls"].append((kind, target.name))
        use_present = state["mode"] == "hit" and "-during-" in target.name and kind == "filters"
        target.write_text(present if use_present else plain, encoding="utf-8")
        return True, "ok"

    saved = (run_probe.netsh_capture, run_probe.is_elevated, run_probe.wfp_mxc_filter_count, run_probe.positive_control,
             run_probe.TOOLCHAIN, run_probe.CONTAINER_PY, dict(run_probe.LAUNCHERS), run_probe.gateway_ip,
             run_probe.GATEWAY_PORTS)
    run_probe.netsh_capture = fake_netsh  # type: ignore[assignment]
    run_probe.is_elevated = lambda: True  # type: ignore[assignment]
    run_probe.wfp_mxc_filter_count = lambda scratch: 0  # type: ignore[assignment]
    run_probe.positive_control = lambda out: {"ok": True, "problems": []}  # type: ignore[assignment]
    run_probe.gateway_ip = lambda: "127.0.0.1"  # type: ignore[assignment]
    run_probe.GATEWAY_PORTS = (STAND_IN_PORT,)
    stand_log: list = []
    stand = ProbeListener("standin", "127.0.0.1", STAND_IN_PORT, stand_log, threading.Lock())
    orig_probe = net_payload.tcp_probe
    net_payload.tcp_probe = lambda host, port, marker, timeout=5.0: orig_probe(  # type: ignore[assignment]
        "127.0.0.1" if host == "1.1.1.1" else host, STAND_IN_PORT if host == "1.1.1.1" else port, marker, timeout)
    try:
        with tempfile.TemporaryDirectory() as t:
            td = Path(t)
            run_probe.TOOLCHAIN, run_probe.CONTAINER_PY = td / "toolchain", Path(sys.executable)
            real_alive = run_probe.pid_alive
            for mode, want in (("clean", "CAPABILITY-ONLY-SUPPORTED"), ("hit", "FILTERS-PRESENT"),
                               ("clean-notalive", "INSTRUMENT-BLIND")):
                state["mode"] = mode.split("-")[0]
                run_probe.pid_alive = (lambda pid: False) if mode == "clean-notalive" else real_alive  # type: ignore[assignment]
                rc, text, out = run_harness(td, "B", "fenced", runs=1, extra_args=["--wfp-capture"])
                s = json.loads((out / "batch-summary.json").read_text(encoding="utf-8"))
                rec = json.loads(sorted(out.glob("run-B-B1-*.json"))[0].read_text(encoding="utf-8"))
                w = rec["wfp"]
                check(f"wfp end to end ({mode}): variant4 verdict {want}; alive at capture; per-run fields recorded",
                      s["variant4_wfp"]["verdict"] == want
                      and w["capture_during_container_alive"] is (mode != "clean-notalive")
                      and "wfp_delta_count" in w and "wfp_filters_referencing_container_sid" in w
                      and w["capture"]["alive_before_capture"] is (mode != "clean-notalive")
                      and w["capture"]["alive_after_capture"] is (mode != "clean-notalive"),
                      json.dumps(s["variant4_wfp"])[:400] + text[-300:])
                check(f"wfp end to end ({mode}): raw filters and state XML saved for before, during and after",
                      len(list((out / "wfp").glob("*-filters.xml"))) == 3 and len(list((out / "wfp").glob("*-state.xml"))) == 3,
                      str(sorted(p.name for p in (out / "wfp").glob("*"))))
                check(f"wfp end to end ({mode}): payload was released by the host (not timed out)",
                      rec["payload"]["hold"]["released"] is True, str(rec["payload"].get("hold")))
    finally:
        run_probe.pid_alive = real_alive  # type: ignore[assignment]
        stand.close()
        net_payload.tcp_probe = orig_probe  # type: ignore[assignment]
        (run_probe.netsh_capture, run_probe.is_elevated, run_probe.wfp_mxc_filter_count, run_probe.positive_control,
         run_probe.TOOLCHAIN, run_probe.CONTAINER_PY, _l, run_probe.gateway_ip, run_probe.GATEWAY_PORTS) = saved  # type: ignore[assignment]
        run_probe.LAUNCHERS.update(_l)


def test_hygiene() -> None:
    bad: list[str] = []
    for p in sorted(HERE.glob("*")):
        if p.suffix not in (".py", ".ps1", ".cmd", ".md"):
            continue
        text = p.read_text(encoding="utf-8")
        for m in re.finditer(r"#\d|\bp\d+-|" + "mr" + "bla", text, re.I):
            bad.append(f"{p.name}: {m.group(0)!r}")
    check("probe files carry no hash-digit refs, p<digits>- fixture names or operator account name", not bad, "; ".join(bad[:5]))
    src = (HERE / "run_probe.py").read_text(encoding="utf-8") + (HERE / "proxy.py").read_text(encoding="utf-8")
    check("no code path binds a listener on a non-loopback address (no lan_ip, no 0.0.0.0 bind)",
          "def lan_ip" not in src and "bind((\"0.0.0.0\"" not in src and "LAN_PORT" not in src)


def main() -> int:
    for fn in (test_instruments, test_summarise, test_port_preflight, test_guard_and_fixtures, test_port_held_between_runs, test_launch_ps1, test_appcontainer_attribution, test_token_modes, test_end_to_end, test_wfp_analysis, test_variant4_group, test_f3, test_hold_and_refusals, test_wfp_end_to_end, test_hygiene):
        try:
            fn()
        except Exception as exc:  # noqa: BLE001 - a crashed check is a FAIL, never a skip
            check(f"{fn.__name__} ran to completion", False, repr(exc))
    failed = [r for r in RESULTS if not r[1]]
    print(f"\n{len(RESULTS) - len(failed)} PASS, {len(failed)} FAIL")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
