# MXC loopback-proxy egress probe, standard-token mode: post-run review of the live batch (#1799)

Reviewer: independent adversarial reviewer. I did not write the harness and did not run the batch. Date 2026-10-16,
05:50-06:10 -04:00. Read-only: no probe, self-test, MXC launch or wrapper job was started.
Under review: raw folder `%USERPROFILE%\blarai-research-data\mxc-proxy-egress\run-20261016-1\` (header, control,
six run records, summary, `staging\` cfg/logs/payload), the console `q3-live-console.txt` beside it, and the code at
worktree `BlarAI-worktrees/q3-standard-token`, branch `feat/1799-standard-token`, HEAD `1c6638aa`.

## Answer: ANSWERED-HOLD, both arms, 3 of 3 runs each

From a standard token (Medium integrity, not elevated, Administrators deny-only), both launchers accepted the
case-1 policy (`networkProxy` http://127.0.0.1:18110, no `allowedProxyPeer`, ingress allow, hostLoopback allow,
egress deny). In every run the container reached the target only through the proxy (B2 3 of 3), and every direct
attempt (B3 loopback listener, B4(i) gateway 10.0.10.1:80, B4(ii) 1.1.1.1:443) was refused with WinError 10013, while
the same account's unconfined process reached all three destinations before and after each launch. The controls
passed and the instrument could have seen a leak, on the right token. Scope is the stated one: these two launcher
builds, this host (26200.9711), TCP only, this policy.

No finding below can turn the HOLD into a FAIL or a refusal. Finding 1 is about the console, not the answer.

## Per-check table (from the raw records, not from batch-summary.json)

| Check | Record fields | Value | Pass |
|---|---|---|---|
| Header token is a standard token | `batch-header.token`: `mode`, `is_user_an_admin`, `elevated`, `elevation_type`, `integrity_sid`, `groups.administrators` | standard, false, false, limited, S-1-16-8192 (Medium), deny-only | yes |
| Same token in every record | `token` in `control-b5.json` and all 6 run records; `machine_start`/`machine_end.integrity_sid` | identical to the header in all 7; Medium at start and end | yes |
| Console token | `q3-live-console.txt` `whoami /groups` | Medium Mandatory Level; BUILTIN\Administrators and S-1-5-114 "Group used for deny only" | yes |
| Harness hashes equal the approved hashes | `batch-header.harness_sha256` (4 files), `launch_ps1_sha256`, `launch_ps1_sha256_as_passed_by_launcher` vs `APPROVED_SHA256.txt` | 5 of 5 equal (run_probe 2da4097b, net_payload 13b73036, proxy 8ed0f6fc, summarise 56bc14f7, launch.ps1 b243519b) | yes |
| Files on disk now | `sha256sum` of the 9 files at HEAD `1c6638aa` and of `staging\payload\net_payload.py` | all 9 equal the approval file; staged payload equals 13b73036; no `__pycache__` in the probe folder | yes |
| Approval precedes the run | approval file line 1 / header `started` | approved 2026-10-16T07:58:03Z (03:58 -04:00); batch 05:48:34.620 to 05:49:11.934 -04:00 | yes |
| Arm meaning (README) | `launchers.A`, `launchers.B`, `arm_commits`, run `arm`/`state`/`fixture` | A: `wxc-exec.exe` sha256 aa444c0f..., Authenticode Valid Microsoft, designated v1.0.0, state A1 = fx-a. B: sha256 e951922b..., NotSigned, commit 525d0f25 from the known-build table, `--probe` `baseContainerSupportsIdentitylessLoopbackProxy: true` (precondition met), state B1 = fx-b. Same launcher hashes as run-20261015-1 and -3 | yes |
| Policy is the case-1 policy | `policy_as_submitted.network`, `.runtimeConfig` in all 6 | egress default deny, ingress default allow, hostLoopback allow, networkProxy http://127.0.0.1:18110, no allowedProxyPeer, no egress rules | yes |
| Dry run accepted | `dry_run.rc`, `.stderr`, `.stdout` | rc 0, stderr empty, "Dry run completed. Result: validation passed", 6 of 6 | yes |
| Container actually ran confined | `payload.token` | `is_appcontainer: true`, AppContainer SID S-1-15-2-... (a different one per run), integrity S-1-16-4096 (Low), `elevated: false`, 6 of 6 | yes |
| MXC started the process; no MXC error | `launch.exit_code`, `launch.timeout`, `mxc_log_full_text_has_process_start`, `verdict.mxc_error_codes` | exit 0, no timeout, process start true, error codes [] in 6 of 6 | yes |
| B5 unfenced controls reached their targets (batch) | `control-b5.b5a` + `target_log` entry `ctl-054835-b5a-1`; `b5b`; `b5c` | b5a connected and logged by the target listener; b5b 10.0.10.1:80 connected; b5c 1.1.1.1:443 connected; `judgement.ok` true | yes |
| Unfenced controls around every launch | `unfenced_pre.c/.gw`, `unfenced_post.c/.gw` | connected true, all 24 | yes |
| Listeners worked before each launch | `host_control.target`, `.proxy` | true / true, 6 of 6 | yes |
| B2 through the proxy 3 of 3 | `payload.b2[*].status`; `proxy_log` run-tagged `forwarded`/200; `target_log` run-tagged b2 markers | 3 / 3 / 3 in every run (18 requests, all three logs agree) | yes |
| Direct attempts refused with the enforcement code | `payload.b3`, `.b4i`, `.b4ii`: `connected`, `error`, `winerror` | false, PermissionError, 10013 for all 18 attempts, 0.002-0.027 s each (an active refusal, not a timeout) | yes |
| B3 did not reach the listener | run-tagged b3 markers in `target_log`; `verdict.b3_listener_hits` | none; 0 in 6 of 6 | yes |
| No stray traffic | non-host-control `target_log`/`proxy_log` entries outside the run's b2 markers | none in 6 of 6 | yes |
| Not a HOLD by silence | B2 bytes reached the second listener in every run; unfenced reach before and after each launch | the network path existed and the container's stack worked | yes |
| No state change | `state_changed_by_run`; `snapshot_before` vs `snapshot_after` | `{}` in 6 of 6; every snapshot key equal (ACLs, AppContainer mappings 218/218 with foreign 0, ProcessSandboxes absent, firewall rules and profiles, loopback exemptions none, WinHTTP direct). WFP filter count `unreadable: not elevated`: NOT MEASURED (finding 3) | yes, except WFP |
| Run count | `batch-summary.groups`, header `runs_per_arm`, folder listing | 3 + 3 runs, n_expected 3, no `aborted-*.json`, no `arm-*-refused.json` | yes |
| Summary agrees with the records | `summarise.py` re-run on a scratch copy | byte-identical `batch-summary.json` (HOLD / HOLD, controls ok) | yes |

MXC's own launch log, all 6 runs: `mxc.NetworkPolicyApplied` with `enforcement_mode: capabilities`,
`default_policy: block`, `proxy_port: 18110`, `firewall_rules_created: 0`, `firewall_applied: false`, `status: success`,
the same lines as the elevated batches.

## Findings

1. **MEDIUM** (costs: the console cannot be cited as a witness of this batch; if the batch had printed a STOP or a
   REFUSED, the console would not show it either) · `q3-live-console.txt`; `_tools/run_nonelevated.ps1:17` · **The
   console capture is incomplete.** The file holds `whoami /groups`, `VERIFIED: all probe files match the approved
   hashes.` and `PROBE_EXIT=0`, and nothing that `run_probe.py` printed. A normal-completion run prints at least nine
   lines (`token mode: standard; elevated: False` at `run_probe.py:684`, the B5 line at `:766`, six per-run verdict
   lines at `:789`, the closing verdict map at `:803`). There is also no `CMD_EXIT_ZERO`/`CMD_EXIT_NONZERO` line, so
   either the command line omitted that suffix (the round-2 review prescribed it; the README's version does not
   carry it) or cmd never reached it. The file's LastWriteTime is 05:48:26 (created 05:48:25), eight seconds before
   the header's `started`, although its last line can only be written after `run_probe.py` returned (05:49:12).
   The same wrapper did capture `run_probe.py` output in the round-2 dry run (`q3-r2-review\dry1-console.txt` holds
   `token mode: standard; elevated: False`, three dry-run lines, `PROBE_EXIT=0`, `CMD_EXIT_ZERO`), so the loss is not
   the wrapper's normal behaviour. The wrapper returning at about 05:48:54 (the lead's observation; I did not see
   that output) means its polling loop saw the task leave `Running` while the batch had 18 s left: its copy of the
   console was a mid-batch snapshot, and it unregistered the task and stopped enforcing `-TimeoutSec` while
   `run_probe.py` was still running (the same exposure as round-2 finding 3).
   **Mechanism: not established (hypothesis).** I did not reproduce it: that needs a wrapper launch, which this
   review was told not to make. **Validity: not affected.** The answer is read from the raw records, and completion
   is shown by them independently of the console: `batch-header.finished`/`machine_end` are written only on the
   normal-completion path (`run_probe.py:800-801`, after the last run, which returns early on FAIL, state change or
   port abort); the summary holds 3 + 3 runs; no `aborted-*.json` or `arm-*-refused.json` exists; and
   `PROBE_EXIT=0` with `dry_run_only: false` can only follow the `return 0` at `run_probe.py:804`. No lingering
   `run_probe.py`, `wxc-exec` or task cmd for this console was running at 05:55.
   **Incidence:** 1 of 1 live runs through this wrapper; 0 of 1 dry runs.

2. **LOW** · `tools/probes/mxc_proxy_egress/README.md:61` (approved hash 843ea4e6) · **The README's unattended-run
   command contains control characters.** `grep -P` with `cat -A` shows `<home>^Hlarai-research-data` twice (BS where
   `\b` was), `PowerShell^G\pwsh.exe` (BEL where `\7` was), `<worktree>^Iools` (TAB where `\t` was), and
   `_toolsun_nonelevated.ps1` (`\r` lost). Copied as written, it does not run, and it lacks the
   `&& echo CMD_EXIT_ZERO || echo CMD_EXIT_NONZERO` suffix that finding 1 shows is needed to tell a completed cmd
   from one that died. The round-2 review's version of the command is correct. **Reproduced:**
   `grep -nP "[\x00-\x08\x0b-\x1f]" README.md | cat -A` at `1c6638aa`.

3. **LOW** (costs: a summary line that reads as "no state changed" when a field was not recorded or not readable) ·
   `summarise.py:370`; `batch-summary.json` · **Absence reads as "no change".** `judge_batch` takes
   `r.get("state_changed_by_run")`, so a run record with no `state_changed_by_run` key counts as unchanged.
   **Reproduced:** a scratch copy of this batch with the key removed from `run-B-B1-r2` still summarises B/B1 HOLD
   with `state_changed_runs: []`. **Incidence: 0 of 6** (every record carries `{}`). Separately, the summary's
   `state_changed_runs: []` does not carry the header's `unreadable_under_this_token: ["wfp_mxc_filters"]`, so the
   one file people act on presents the WFP state as clean when it was not measured. MXC's own log reports
   `firewall_rules_created: 0` in every run, which bounds that gap but is MXC's own claim, not a measurement.
   `ProcessSandboxes` reads `<absent>` because `reg_list` returns `<absent>` for any non-zero `reg query` exit; the key
   is truly absent here (a read-only `reg query` of the parent shows no such subkey), so this has no effect now, but
   the code cannot tell "absent" from "unreadable".

4. **LOW, hypothesis** · `run_probe.py:532` (`unfenced`) and `:88` (`CONTAINER_PY`) · **The unfenced controls run a
   different interpreter path from the container.** B5 and the per-launch controls run from `C:\Python314\python.exe`;
   the container runs `C:\blarai-spike-1740\toolchain\Python314\python.exe` (same sha256, different path). Bitdefender
   Firewall was present (16 processes, `firewall_product` lists it) and per-application firewalls key on the path, so
   nothing in this batch shows that the container's interpreter path is not blocked by a third-party rule, which
   would also produce WinError 10013. Against it: run-20261015-1 (Bitdefender uninstalled, Security Center McAfee
   only) gave the same 10013 on all three direct attempts in 6 of 6 runs with the same container path; MXC's log says
   it enforces by capabilities; and B3 (refused) against B2 (allowed) is a split on the same address that no
   path-based rule makes. The HOLD stands; the record should not claim that this batch alone attributes the refusal
   to MXC.

5. **INFO** · for whoever writes up the comparison with run-20261015-1..3 · Between the elevated batches and this
   one, the token, all four harness files (`run_probe` 979c21d5 to 2da4097b, `net_payload` 372b812c to 13b73036,
   `proxy` 9057ef74 to 8ed0f6fc, `summarise` 78ee0b40 to 56bc14f7) and the Bitdefender process set (14 to 16) all
   changed; launcher hashes and Windows build did not. "The same result under a standard token" is true at the
   level of verdicts and error codes; it is not an isolated token effect.

## Attacked and could not break

- **Recomputation:** `summarise.py` re-run (`python -I -B`, no MXC) on a scratch copy of the raw folder gives a
  byte-identical `batch-summary.json`.
- **Discriminating split, same corpus, same invocation:** in scratch copies, B4(ii) `connected: true` in one B run
  -> B/B1 FAIL; container `is_appcontainer: false` -> INSTRUMENT-BLIND; `unfenced_post.c` not connected ->
  INSTRUMENT-BLIND; B5 `b5c` not connected -> both groups INSTRUMENT-BLIND; the unmodified copy -> HOLD/HOLD. The
  verdict logic moves with the evidence on this batch's real records.
- **Hold by silence:** B2 bytes reached the second listener in every run and the unfenced reach held before and after
  every launch, so 10013 is a refusal on a working path, not an absent network.
- **Wrong token:** all seven records and the console carry Medium, not elevated, Administrators deny-only; the
  container ran as a Low-integrity AppContainer in 6 of 6.
- **Shared-pool neighbour:** the run folder is fresh (its header is the only one); the per-run AppContainer SIDs
  differ; `appcontainer_foreign_count` 0 before and after every run, so no other tool's `mxcfx-` profiles were
  present at the snapshot points. Other agents' MXC self-tests were running at 05:55; none of their processes
  predate 05:51, and no stray listener or proxy traffic appears in any run.
- **Stale approval:** the files on disk now, the header hashes and the approval file agree for all nine approved
  files; the approval predates the batch by 1 h 50 min.

## Merge read

Nothing here blocks citing run-20261016-1 as ANSWERED-HOLD for both arms from a standard token, within the stated
scope. Before the record is published: do not cite the console as showing the per-run output (finding 1); state that
the WFP filter state was not measured under this token (finding 3); do not claim the refusal is attributed to MXC by
this batch alone (finding 4). Findings 1 (wrapper early return and lost output) and 2 (corrupted README command)
need a ticket or a fix before the next unattended run through this wrapper.

What I ran, all at HEAD `1c6638aa`, read-only on the raw folder: Python extraction of every run, control and header
field listed above; `sha256sum` of the nine approved files and the staged payload; `summarise.py` on six scratch
copies under the session scratchpad; `reg query` of the HKCU CurrentVersion key; a `Win32_Process` listing. No suite
was run: `self_test.py` and the standing gate were not run, by instruction (machine kept quiet for two other
reviewers).
