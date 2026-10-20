# MXC loopback-proxy egress probe, standard-token mode: pre-run review (#1799)

Reviewer: independent adversarial reviewer (did not write the code). Date 2026-10-16, 00:37-01:15 -04:00.
Under review: worktree `BlarAI-worktrees/q3-standard-token`, branch `feat/1799-standard-token`, HEAD `cb23eb17`
(parent main `c412af4d`), folder `tools/probes/mxc_proxy_egress/`. HEAD and folder state confirmed clean at start and end.

## Verdict: FAIL (one HIGH). No approval file written.

The token-mode gate itself is sound: it is checked in `launch.ps1` and again in `run_probe.py` from the real token,
and a forged self-test override cannot get an elevated process past the second check. Standard mode reads every
snapshot field that case 1 read, except the WFP count, which is declared unreadable. The HIGH is in the verdict path
that standard mode makes likely: a launch failure that is not a policy refusal can be labelled REFUSED-AT-LAUNCH,
which the LA rule counts as a result.

## What I ran (all probe-touching runs non-elevated through `_tools/run_nonelevated.ps1`)

Token of every runner job (from the runner's own `whoami /groups`): `Mandatory Label\Medium Mandatory Level  Label
S-1-16-8192`; `groups_summary()` under the runner: `administrators: deny-only`, `elevation_type: limited`,
`IsUserAnAdmin: False`. My own interactive shell is High (S-1-16-12288), so I used it only for pure-function drivers
and the elevated toggle tests.

| Run | Result |
|---|---|
| `self_test.py` run 1 (non-elevated) | **152 PASS, 5 FAIL** |
| `self_test.py` run 2 (non-elevated) | **151 PASS, 6 FAIL** (a different set of failing checks) |
| Control: the same self-test with only `run_probe.REG_AC_MAPPINGS` pointed at an absent key (scratch wrapper `drv/st_control.py`; no probe file changed) | **157 PASS, 0 FAIL** (finding 4) |
| `snapdiff.py`: `run_probe.snapshot()` taken 9 times, 10 s apart, non-elevated, with no MXC launch of mine | only `appcontainer_mappings` changed: 218 -> 219 -> 218 -> 219 ... |
| `acwatch.ps1`: HKCU AppContainer\Mappings watched for 60 s | `mxcfx-*` profiles created and deleted every 3-5 s; the live process list at the time showed the `mxc_denied_subtree` self-test (another agent) |
| Standard-mode `--dry-run-only --arms A,B,B0` (`run_probe.py --token standard`, `--out` in scratch) | dry-run rc 0 for all three, stderr empty; header token Medium/limited/deny-only; `unreadable_under_this_token: ['wfp_mxc_filters']`; harness hashes equal the files at `cb23eb17`; arm B/B0 commits come from the known-build table |
| `launch.ps1 -Token standard` (scratch approved file, stub python) | `VERIFIED`, then the stub received `--launch-sha256 aed6c88d... --token standard --arms A,B --runs 3` |
| `launch.ps1 -Token standard` from the elevated shell | `REFUSED: -Token standard needs a NON-elevated token` (exit 1), with and without `-SelfTestElevation standard` |
| Same, with `BLARAI_PROBE_SELFTEST=1 -SelfTestElevation standard -SelfTestIntegrity medium` (a forged override) | launch.ps1 passes, then `run_probe.py` refuses: `REFUSED: --token standard requires a non-elevated Medium-integrity token ... IsUserAnAdmin=True, elevated=True` (exit 2); no output folder written |
| `attack.py`, `attack2.py`, `attack3.py`: synthetic records through the real `summarise.judge_run` / `judge_batch` | findings 1-2 and the not-broken list |

Scratch: `%USERPROFILE%\AppData\Local\Temp\claude\q3-review\` (drivers under `drv\`, outputs `selftest1.txt`,
`selftest2.txt`, `selftest_control.txt`, `snapdiff.txt`, `dry2\`).

## Findings

### 1. HIGH: a launch failure that is not a policy refusal reads REFUSED-AT-LAUNCH (a result)
`summarise.py:69` (`REFUSAL_TEXT`), `:185-194`.
- **What is wrong:** with no payload, no host traffic and a non-empty MXC log that never says `process created`, any
  of `refus|reject|not supported|unsupported|requires|invalid|validation failed` anywhere in the launcher's stderr,
  stdout or log tail makes the run REFUSED-AT-LAUNCH. MXC's own error envelope already separates the cases: `code`
  is `policy_validation` only for a rejected policy and `backend_error` otherwise (round-3 review finding 1, citing
  `script_runner.rs:102-120`). The verdict ignores that and judges from free text.
- **Why it matters now:** under a standard token the likely failure is a backend step that needs privilege
  (AppContainer profile, ACL, filter set-up), not a policy rejection. Its message can easily contain "invalid" or
  "requires". The LA rule says a crash or launch failure is LAUNCH-FAILED, NOT ANSWERED; this path labels it a
  refusal, and the label is what reaches STATUS.md and the fork team (nono #2125).
- **Reproduced** (`drv/attack2.py`, `drv/attack3.py`; standard-mode Medium token, no payload, exit 1, MXC log
  without `process created`):
  - `{"code":"backend_error","message":"failed to create AppContainer profile: invalid parameter"}` -> `REFUSED-AT-LAUNCH`; three such runs -> batch `REFUSED-AT-LAUNCH`
  - `Error: Invalid handle (os error 6)` -> `REFUSED-AT-LAUNCH`
  - `thread 'main' panicked at src/x.rs: requires a valid token` -> `REFUSED-AT-LAUNCH`
  - `{"code":"backend_error","message":"Access is denied. (os error 5)"}` -> `INSTRUMENT-BLIND` (the regex misses it, so the label depends on wording)
- **Contradicts its own prose:** the README and the summarise docstring both say "a launch with no payload report and
  no refusal text is INSTRUMENT-BLIND (launch failed, not answered)". The "refusal text" rule is a word list that a
  backend error or a panic matches.
- **Incidence:** 0 in the banked case-1 runs (all 12 launches were accepted and ran). No standard-token launch has
  been banked yet, which is the population this applies to.
- **Cost:** a false "MXC refuses this policy from a standard token" answer. The verbatim stderr in `reasons` lets a
  careful reader catch it, but the batch label does not.

### 2. MEDIUM: an empty B4(i) report gives HOLD, and the HOLD reason says B4(i) was refused
`summarise.py:212-214` (the new empty-report guard covers `b3` and `b4ii` only), `:231-247`, `:254`.
- **Reproduced** (`drv/attack.py`): the baseline Medium-token HOLD record with `payload["b4i"] = {}` ->
  `HOLD`, reason "B2 3 of 3; B3, B4(i), B4(ii) each refused with the enforcement code". The same with `b3 = {}` ->
  `INSTRUMENT-BLIND` (guarded). So an absent attempt is reported as a confident refusal.
- **Reachability:** the hash-bound `net_payload.py` always writes a `tcp_probe` record or `{"skipped": ...}` for
  b4i, so the real payload cannot produce `{}`. The new b3/b4ii guard is equally unreachable from the real payload.
  So this is the same guard with one key missing, not a live path. The self-test lock "empty B3 and B4(ii) reports ->
  never HOLD" is accurate as written, but the brief asked about "a direct B3/B4 attempt that never executed".
- **Cost if reached:** a HOLD without a B4(i) attempt. Not blocking on its own.

### 3. MEDIUM: the payload never records the container's own token
`net_payload.py:84-100` (writes b2/b3/b4i/b4ii, env_proxy and timings only).
- The brief asked for the container payload's token "where possible". It is not recorded, so a standard-token record
  cannot show that the workload ran in an AppContainer below the Medium parent. An unconfined fallback could not
  produce a HOLD (B3 to the loopback listener would connect, which is FAIL), so this cannot fake the answer. It does
  leave the record unable to show what the container was. Recording `whoami /groups` or the token's AppContainer
  flag and integrity SID from inside the payload would close it.
- **Reproduced:** read only (no live launch was allowed).

### 4. MEDIUM: shared-pool state makes the snapshot guard, and so the self-test, flaky while other MXC agents run; the unattended run is exposed to the same thing
`run_probe.py:101-102`, `:413` (`appcontainer_mappings` = count of every HKCU AppContainer mapping for the user).
- **The self-test counts differ (152/5 vs 151/6) because of this.** Every failing check in both runs is a batch that
  hit `STOPPED-STATE-CHANGE` (`state_changed_runs: ["B-B1-r1-004337"]` in run 1, `["B-B1-r2-005245"]` in run 2), or a
  check further down that depended on that batch. `snapdiff.py` shows the count moving 218 <-> 219 with no MXC launch
  of mine, and `acwatch.ps1` shows `mxcfx-*` profiles created and deleted every 3-5 s by the `mxc_denied_subtree`
  self-test, which was running at the same time. Control run with the count neutralised: see the line at the end of this finding.
- **The live run inherits this.** If any other agent creates or deletes an AppContainer during a run (the other probe
  agents do so tonight), that run stops with exit 4 and STOPPED-STATE-CHANGE: the answer is lost, though no false
  HOLD can result. In the other direction it can miss things: a count cannot see one profile leaked by this run while
  a neighbour removes another. Before the unattended run the orchestrator must make sure no other MXC or AppContainer
  work is running (the denied-subtree and redirector self-tests and probes).
- **Control result:** the same self-test, non-elevated, at the same hash and with the neighbour still running, but
  with only the AppContainer-mapping key pointed at an absent key (`drv/st_control.py`): **157 PASS, 0 FAIL**. So the
  5 and 6 failures come from the neighbour's AppContainer churn, not from the code under review. This is one control
  run against two failing runs, together with the mechanism watched directly (`acwatch.ps1`).

### 5. MEDIUM (harness, outside the commit): the runner always reports `exit=0`
`_tools/run_nonelevated.ps1` (reports `LastTaskResult` of `conhost --headless`, not of the command).
- **Reproduced:** `launch.ps1 -ApprovedFile C:\nonexistent.txt -VerifyOnly` printed `REFUSED ... approved-hash file
  missing` and the runner printed `exit=0`. A pwsh parameter-binding failure also gave `exit=0`. The orchestrator must
  not read the runner's `exit=` as the probe's outcome. Appending `&& echo PROBE_EXIT_ZERO || echo PROBE_EXIT_NONZERO`
  to the command line works: it printed `PROBE_EXIT_NONZERO` for the refused case. The answer itself always comes
  from `batch-summary.json`, never from the exit line.

### 6. LOW: `--out` (and `--token`) cannot be passed through `launch.ps1`
`launch.ps1:30-38` (`ValueFromRemainingArguments`).
- **Reproduced:** `launch.ps1 -Token standard ... --dry-run-only --arms A,B,B0 --out <dir>` -> `Parameter cannot be
  processed because the parameter name 'out' is ambiguous. Possible matches include: -OutVariable -OutBuffer.`
  (PowerShell strips the dashes). `--` is not an end-of-parameters marker under `-File` either. It fails closed
  (nothing runs), but the README says probe args pass through. The unattended run must use the default output folder.

### 7. LOW: `-VerifyOnly` does not check the token
`launch.ps1:69` exits before the token checks at `:72-88`. So "`launch.ps1 -Token standard -VerifyOnly` accepts it"
proves the hashes only, not the token gate. The token gate was proven separately above (stub run non-elevated passes;
elevated is refused).

### 8. LOW: state left behind
Every launch creates `%TEMP%\mxc-probe-pyc-<guid>` and never removes it (36 present in this account's Temp now).
The approved hash file is not affected. If the runner's `ExecutionTimeLimit` kills the task, it ends conhost. Whether
the python child and its listeners survive is not tested (hypothesis); if they do, the next attempt is refused
`ABORTED-PORT-HELD`, which fails closed.

### 9. INFO: the banked standard-token dry run is not at `cb23eb17`
`blarai-research-data/mxc-proxy-egress/q3-dryrun-20261016/batch-header.json` records `net_payload.py 1f066d12...`
and `proxy.py 1be18433...`, which are the parent `c412af4d` blobs; at `cb23eb17` they are `82d07f98...` (on disk,
CRLF) and `8ed0f6fc...`. The differences are docstring-only, but that folder is not a dry run of the reviewed tree.
My dry run (`dry2`) is at `cb23eb17` and agrees: all three arms accepted.

### 10. INFO: no visible window, hypothesis for the container
Everything the harness starts uses `CREATE_NO_WINDOW`, and the runner uses `conhost --headless`. The workload
console under wxc-exec passthrough can only be confirmed by a live launch, which I was not allowed to run.

## Attacked and not broken
- **Token gate is unforgeable in both places.** Real detection in launch.ps1 refuses elevated with and without
  `-SelfTestElevation`. The env-gated override gets past launch.ps1 only, and `run_probe.py` refuses from the real
  token (exit 2, nothing written). Each run, control and dry-run record carries its own token read. In `judge_run` a
  standard-mode record whose token is elevated, non-Medium or unreadable is INSTRUMENT-BLIND before any other rule.
- **No HOLD without the controls.** B2 at 2/3, 0/3 or 6/3 gives INSTRUMENT-BLIND. So does a missing payload, a missing
  B5 record or a failed B5 control (batch level). A timeout instead of 10013, or a b4i record with no `connected`
  key, also gives INSTRUMENT-BLIND.
- **A real direct connect reaching its listener is FAIL.** A tagged listener hit is FAIL even when the payload says
  refused (`attack.py` 6). A payload `connected: true` with no hit is FAIL. FAIL precedes every BLIND rule.
- **Standard mode skips nothing else.** Firewall rules, profiles, product, HKCU sandbox mappings, ACLs,
  loopback-exempt and WinHTTP read the same values as the case-1 elevated record (`run-20261015-3`): same two python
  rules, `LoopbackExempt ... OK.`, `Direct access`. Only `wfp_mxc_filters` is `unreadable: not elevated`, and it is
  listed.
- **Port and output guards.** A fresh output folder is required, a git-tree output is refused, and a held port is
  refused before every run. No neighbour probe binds 18110/18111. The only other users are copies of this probe in
  the other worktree.

Not tested: any live MXC launch (forbidden by the brief). The mixed-token batch (`attack.py` 4: one elevated-mode
record in a batch gives HOLD with `token_modes: ['elevated','standard']`) cannot be produced by `run_probe.py`, which
writes every record with the same `--token`. It is noted rather than reported.

## Merge read
Block on finding 1: restrict REFUSED-AT-LAUNCH to MXC's `policy_validation` envelope, or require it, and send
everything else with no payload to INSTRUMENT-BLIND or a named LAUNCH-FAILED. Add a `backend_error` fixture with a
toggle. Finding 2 is a one-key widening of the new guard. Finding 3 would make a standard-token record able to say
what the container was. Findings 4 and 5 are run-procedure conditions, not code blocks: quiesce the other MXC agents
and judge from the records.

## How to run unattended (once a fixed tree is approved)
Precondition: no other MXC, AppContainer or self-test work running (finding 4), and ports 18110/18111 free. Then:

```
pwsh -NoProfile -File C:\Users\%USERNAME%\blarai-research-data\_tools\run_nonelevated.ps1 -CommandLine "\"C:\Program Files\PowerShell\7\pwsh.exe\" -NoProfile -NonInteractive -ExecutionPolicy Bypass -File C:\Users\%USERNAME%\BlarAI-worktrees\q3-standard-token\tools\probes\mxc_proxy_egress\launch.ps1 -Token standard --arms A,B --runs 3 && echo PROBE_EXIT_ZERO || echo PROBE_EXIT_NONZERO" -OutFile C:\Users\%USERNAME%\blarai-research-data\mxc-proxy-egress\q3-live-console.txt -TimeoutSec 3000
```

Do not use `launch-standard.cmd` unattended (it ends in `pause`), and do not pass `--out` (finding 6). The output
folder is the next `run-YYYYMMDD-n` under `blarai-research-data\mxc-proxy-egress`. Read the answer from that folder's
`batch-summary.json` and the `S-1-16-8192` line at the top of the console file, never from the runner's `exit=`
line. If the console file is empty, the runner's wait loop raced: read the run folder directly.

Suites run: `self_test.py` x2 plus one control, all at `cb23eb17`, non-elevated through the runner. The standing gate
was not run (it is not in scope for a research-probe folder outside the gate).
