# MXC loopback-proxy egress probe

What it measures: with `runtimeConfig.networkProxy` set to a loopback proxy the run controls (no `allowedProxyPeer`,
`ingress.default` allow, `ingress.hostLoopback` allow, `egress.default` deny, no egress rules), whether each launcher
accepts the policy, and if so whether non-proxy egress from inside the container is blocked. Launchers: arm A the
signed v1.0.0, arm B a main build (refused unless its `--probe` reports `baseContainerSupportsIdentitylessLoopbackProxy`
true), optional arm B0 an older main build.

Per run (separate launcher invocation, preceded by `--dry-run`): B2 three HTTP requests through a stdlib forwarding
proxy to a second loopback listener (instrument control); B3 a direct connect to that listener; B4(i) a connect-only
attempt to the default gateway on a port an unfenced pre-check reached; B4(ii) a connect-only attempt to 1.1.1.1:443.
B5: the same connects from an unconfined process on the same account, once per batch and again immediately before and
after every launch. B2 and B3 are judged from host-side listener logs (run tag required); B4 from the container's error
code, where only WinError 10013 counts as a refusal. No listener is bound on a non-loopback address.

Verdicts: HOLD, FAIL, REFUSED, REFUSED-AT-LAUNCH, INSTRUMENT-BLIND (rules in `summarise.py`). A B4(i) with no reachable
LAN-peer port is recorded NOT-MEASURABLE and is never a HOLD. On any FAIL the harness prints `STOP: FAIL condition met`
and runs nothing further. Any change in the before/after state snapshot (ACLs, registry mappings, firewall rules for the
two interpreters, firewall profiles, loopback exemptions, WinHTTP proxy, MXC-named WFP filter count when readable) also
stops the batch.

Reading a reach: the policy document states that an identity-less loopback proxy "opens both host-loopback
directions", so a B3 reach is to be read against that text. For B4(i) the networking document says: "Private-network
traffic remains available in both directions when `ingress.default` is `"allow"`", while also saying that on an
enforcing BaseContainer path per-container WFP "blocks direct public and private destinations". The two sentences
disagree about exactly the B4(i) destination. The harness still STOPs on any B3 or B4 reach; the operator reads the
reach against both document sentences before any routing decision.

Token modes (`--token elevated|standard`, default elevated; `launch.ps1 -Token ...`): `elevated` is the mode of the
earlier records: `launch.ps1` refuses a live run unless elevated, `--dry-run-only` may run without it. `standard`
refuses any run, dry or live, unless the process token is not elevated and is Medium integrity (S-1-16-8192); an
elevated or non-Medium token is refused with the reason, and `run_probe.py` repeats the check (exit 2, nothing
written). The mode, IsUserAnAdmin, the token's elevation flag and type, its integrity SID and a `whoami /groups`
summary (mandatory label, Administrators group state, group count) are recorded in the batch header and in every
run, control and dry-run record. A run record in standard mode whose recorded token is elevated or not Medium is
INSTRUMENT-BLIND. Each batch needs a fresh output folder. Arm B needs `--arm-b-commit` (arm B0 `--arm-b0-commit`)
unless the launcher's sha256 is in the known-build table.

Steps that need elevation: the only step found that reads state a non-elevated token cannot read is the WFP filter
count (`netsh wfp show filters`). Under a standard token it is recorded as `unreadable: not elevated`, listed under
`unreadable` in each snapshot and under `unreadable_under_this_token` in the header, and is NOT MEASURED: an equal
before/after value of an unreadable entry says nothing about it. The proxy and target listeners bind loopback ports
above 1023, the firewall, registry (HKCU), ACL, loopback-exemption, WinHTTP and netstat reads are plain-user reads,
and the harness runs no cleanup or host-prep step that needs elevation. Whether MXC itself accepts and runs the
policy from a standard token is the measured question. A refusal at `--dry-run` or at launch is a result ONLY when
MXC's own error envelope (JSON with `code`) says `policy_validation` and its message reads as a rejection (and, at
launch, the MXC log shows no process created and no workload traffic reached the listeners); the exact text is kept
with the token record. Every other failure (a `backend_error`, an OS error, a panic, no output, wording such as
"invalid" or "requires" with no `policy_validation` envelope) is LAUNCH-FAILED, NOT ANSWERED, recorded as
INSTRUMENT-BLIND. A HOLD needs B2 (the positive control) 3 of 3 with bytes at the target, passing unfenced controls
(B5), a report for each of B3, B4(i) and B4(ii) that shows the attempt ran and its outcome code, and a payload token
record showing an AppContainer token. The payload records its own token (user SID, IsAppContainer, AppContainer SID,
integrity SID, elevation) in every run record, so the record shows what the container ran as.

State snapshot and shared accounts: the AppContainer mappings are compared by identity (SID and profile name), leaving
out profiles created by another tool's self-test (prefix `mxcfx-`, listed in `run_probe.FOREIGN_AC_PREFIXES`). The
total and the foreign count are recorded (`appcontainer_total`, `appcontainer_foreign_count`) but never compared. A
profile this probe's launch leaves behind, or any mapping that no known prefix explains, still stops the batch.

Unattended run (from a non-elevated shell; do not use launch-standard.cmd, it ends in `pause`):
`pwsh -NoProfile -File <home>\blarai-research-data\_tools\run_nonelevated.ps1 -CommandLine "set BLARAI_PROBE_PYTHON=C:\Python314\python.exe && \"C:\Program Files\PowerShell\7\pwsh.exe\" -NoProfile -NonInteractive -ExecutionPolicy Bypass -File <worktree>\tools\probes\mxc_proxy_egress\launch.ps1 -Token standard --arms A,B --runs 3 && echo CMD_EXIT_ZERO || echo CMD_EXIT_NONZERO" -OutFile <home>\blarai-research-data\mxc-proxy-egress\q3-live-console.txt -TimeoutSec 3000`.
The wrapper waits for a completion marker the task writes last and prints `exit=<cmd errorlevel>`, or `exit=TIMEOUT` (task stopped): take the outcome from the
`PROBE_EXIT=<n>` line that launch.ps1 prints last (absent = the script never reached an exit) and, for the answer, from
`batch-summary.json` in the run folder. Run it when no other MXC or AppContainer work is running on the account.

How to run: `launch.cmd` (run as administrator; or `pwsh -File launch.ps1 [probe args]`) for the elevated mode,
`launch-standard.cmd` (double-click from Explorer or a normal shell, never as administrator; or
`pwsh -File launch.ps1 -Token standard [probe args]`) for the standard mode; both refuse to start unless the four probe files
match `<sha256>  <filename>` lines in `APPROVED_SHA256.txt` under the research-data folder. `python -I self_test.py`
runs the self-test (no MXC, non-elevated).

Writes: raw records only under the output folder (default `<home>/blarai-research-data/mxc-proxy-egress/run-<date>-<n>`);
a folder inside a git working tree is refused.

Not measured: any build other than the one(s) run; the WFP filter count under a standard token (unreadable) and the WFP filter
list of the container's session (only an MXC-named filter count is taken); behaviour on a host whose `--probe` reports host-loopback ingress
unsupported (the earlier 26200.9457 condition); an identity-scoped proxy (`allowedProxyPeer`); the session-isolation
backend; UDP, ICMP or DNS egress under the proxy policy; host-to-container ingress (the doc's own open limitation);
nono under MXC; anything about the fork or any other sandbox; IPv6; HTTPS or CONNECT through the proxy.

## Variant 4: WFP filter and state capture (`--wfp-capture`)

What it measures: whether a launch adds Windows Filtering Platform (WFP) filters keyed to the container's identity. The fork team's reading
is capability-only: the AppContainer holds no network capabilities and MXC adds no SID-keyed filters. Per launch the harness takes
`netsh wfp show filters` and `netsh wfp show state` (a) before, (b) DURING, (c) after, raw XML under `<out>/wfp/`.

During-launch sync: the payload (`net_payload.py --hold-ready R --hold-release X`) finishes its probes, writes R (its pid, time,
token), then waits for X to exist (at most 100 s). The harness waits for R, checks the payload pid (`tasklist`) and the launcher process
are alive and X is absent, captures, checks the same again, and only then writes X. `capture_during_container_alive` is true only if both
checks hold. The container's AppContainer SID comes from the payload's own token record. A failed capture, a launch that never reached
the hold point, an unknown SID, or a payload that timed out unreleased makes that run INSTRUMENT-BLIND, never "no filters".

Per run (`wfp` in the run record): `wfp_delta_count` (filters in the during dump but in neither the before nor the after dump, by
filterKey), `wfp_filters_referencing_container_sid` (name, layer, action of every during-dump filter whose text names the container
SID), `wfp_delta_filters_referencing_user_sid`, `capture_during_container_alive`, `reading`.

Positive control (once per batch, before the first launch, `wfp-control.json`): a temporary outbound block rule keyed to a synthetic
package SID is created with `New-NetFirewallRule -Package`, captured, found by the same analysis, removed in `finally`, removal
verified by `Get-NetFirewallRule`, and a second capture confirms the SID is gone. Without all of that the batch reading is
INSTRUMENT-BLIND. The rule name is printed in `wfp-control.json`; if removal is not verified the record says to remove it by hand.

Group verdict (`variant4_wfp.verdict` in `batch-summary.json`): CAPABILITY-ONLY-SUPPORTED (no during-dump filter names any launch's
container SID, control found, every launch captured alive), FILTERS-PRESENT (list with run tags), INSTRUMENT-BLIND (reasons listed).
The egress verdict logic (HOLD/FAIL/...) is unchanged. `batch-summary.json` also carries `unreadable_under_this_token`, and a run
record without `state_changed_by_run` makes its group INCOMPLETE (never "no change").

Run (elevated; refused with `-Token standard`, with `--dry-run-only`, or from a non-elevated process):
`pwsh -NoProfile -File <worktree>\tools\probes\mxc_proxy_egress\launch.ps1 --arms A,B --runs 3 --wfp-capture`

Not measured: filters the netsh dump does not list; filters created and removed between captures; a container SID the payload did not
report; whether the host-created release file is visible to the container under MXC's ACLs (if not, the payload times out unreleased and
the run reads INSTRUMENT-BLIND); that `-Package` produces an `ALE_PACKAGE_ID` filter on this build (the control tests it live; the
self-test uses fixtures only); the egress questions of the main probe. Capture adds up to a few minutes of wall time per launch.
