# MXC loopback-proxy egress probe, standard-token mode: pre-run review, round 2 (#1799)

Reviewer: independent adversarial reviewer. I did not write this code and did not do round 1. Date 2026-10-16,
02:10-04:00 -04:00.
Under review: worktree `BlarAI-worktrees/q3-standard-token`, branch `feat/1799-standard-token`, HEAD `1c6638aa`. The
fixes are in `1c6638aa`; `b2b159fb` is the round-1 review file. HEAD was `1c6638aa` and the probe folder was clean
(no `__pycache__`) at the start and at the end.

## Verdict: PASS (no BLOCKER, no HIGH). Three MEDIUM findings, none blocking. Approval file written (see the end).

## What I ran
Probe-touching runs were non-elevated, through `_tools/run_nonelevated.ps1`. Every runner job printed
`Mandatory Label\Medium Mandatory Level  Label  S-1-16-8192` and `BUILTIN\Administrators ... Group used for deny only`.
Pure-function drivers ran in my own elevated (High) shell; the elevated refusal checks also ran there.

| Run | Result |
|---|---|
| `self_test.py` run 1, non-elevated, 03:42-03:50 | **206 PASS, 0 FAIL**, CMD_EXIT_ZERO. No other `self_test.py` or `run_probe.py` was running at the start. |
| `self_test.py` run 2, non-elevated, 03:50-03:56 | **206 PASS, 0 FAIL**, CMD_EXIT_ZERO. No other `self_test.py` or `run_probe.py` was running at the start. |
| Waiting for a quiet machine, 02:19-02:41 | Other agents' `self_test.py` processes were present the whole time (PIDs 20552, 18052, 5764). By 03:42 none were left, so both runs above were on a quiet machine. The builder's `FileNotFoundError(2)` did not recur. |
| Dry run: `launch.ps1 -Token standard -ApprovedFile <scratch> --dry-run-only --arms A,B,B0 --out <scratch>\dry1` | VERIFIED; A, B and B0 all `dry_rc 0`, `validation passed`; PROBE_EXIT=0. Header token: Medium, limited, administrators deny-only; `unreadable_under_this_token: ['wfp_mxc_filters']`. Header `harness_sha256` equals the four files at `1c6638aa`. B=`525d0f25`, B0=`70fc7d52` from the known-build table. |
| `launch.ps1` attacks, elevated shell | `-Token standard -VerifyOnly` -> REFUSED (non-elevated needed), PROBE_EXIT=1. `--launch-sha256 abc` -> REFUSED, PROBE_EXIT=1. `-Token standard --token elevated` -> pwsh binding error and no PROBE_EXIT line (fails closed, as documented). Approval file with one byte changed -> REFUSED hash mismatch. `--out` inside a git tree -> REFUSED, nothing created. |
| `drv/attack.py`, `drv/attack2.py`: real MXC refusal bytes and synthetic records through `summarise.judge_run` | findings 1, 2, 4, 5 |
| Runner time-limit test: `python -c "time.sleep(150)"` with `-TimeoutSec 15` | finding 3 |

Scratch: `%USERPROFILE%\AppData\Local\Temp\claude\q3-r2-review\` (drivers under `drv\`; `selftest1.txt`,
`selftest2.txt`, `dry1\`, `dry1-console.txt`, `killtest.txt`).

## Round-1 findings re-verified at 1c6638aa

| # | Round-1 finding | Status | Evidence |
|---|---|---|---|
| H1 | A launch failure that was not a policy refusal read REFUSED-AT-LAUNCH | **FIXED** | A real-shape `{"error":{"code":"backend_error","message":"... requires ... invalid"}}` -> INSTRUMENT-BLIND "LAUNCH-FAILED, NOT ANSWERED". A `policy_validation` envelope beside a `backend_error` code -> BLIND. Keyword text with no envelope -> BLIND. Over-strict side effect: finding 1. |
| M2 | `b4i={}` -> HOLD | **FIXED** | `b4i={}` -> BLIND "payload report for B4(i) is empty". Absent -> BLIND. `{"connected":false}` with no code -> BLIND. `skipped:""` -> BLIND. |
| M3 | The container's token was not recorded | **FIXED** (read; no live launch allowed) | `net_payload.token_report()` runs and reads its fields (High shell: `is_appcontainer False`, `S-1-16-12288`, `elevated True`). A payload with no token, or with `is_appcontainer` not True -> BLIND. A banked base-container run (phase2 arm E2, 26200.9457) shows an S-1-15-2 AppContainer SID at Low integrity inside the container, so a real run should pass this check. |
| M4 | The AppContainer mapping count was tripped by other probes' `mxcfx-*` churn | **FIXED** | Mappings are now compared by `<sid> <moniker>`. Only `mxcfx-*` is excluded. This probe sets no `containerId`, so MXC names its profile `CLI` (`appcontainer_runner.rs:1322`); its own leftovers stay compared and are not hidden. Read live: 218 mappings, 0 foreign, identical over 8 reads 5 s apart. A Windows store-app update is a non-`mxcfx` change and still stops a batch: answer lost, never a false HOLD. Hypothesis, not tested: a neighbour that also launches with MXC's default `CLI` name gets the same SID, so it would mask or trip this probe's own `CLI` entry. |
| M5 | The runner prints exit=0 regardless | **FIXED in launch.ps1; the runner is unchanged** | Every exit made by `launch.ps1` prints `PROBE_EXIT=<n>`; seen in every case above. The runner still prints `exit=0`, or `exit=267014` on its time limit. Judge from PROBE_EXIT and `batch-summary.json`. |
| L6 | `--out` could not be passed through | **FIXED** | The dry run with `--out <scratch>\dry1` wrote there. `--token` is bound to -Token; `--launch-sha256` is refused. |
| L7 | `-VerifyOnly` did not check the token | **FIXED** | An elevated shell with `-Token standard -VerifyOnly` -> REFUSED. Non-elevated -> VERIFY-ONLY accepted (approval section). |
| L8 | pyc folders were left in Temp | **FIXED for new runs** | The count of `%TEMP%\mxc-probe-pyc-*` stayed at 36 across my dry run, so the folder is removed in `finally`. The 36 old folders are still there. |
| I9 | The banked dry run used the parent's files | **SUPERSEDED** | My dry run at `1c6638aa` (above). |

## New findings

### 1. MEDIUM: a genuine MXC policy refusal reads "LAUNCH-FAILED, NOT ANSWERED". A lost answer, never a false one.
`summarise.py` `policy_rejection` (`REFUSAL_TEXT` message gate) and the `dry.get("rc") != 0` branch of `judge_run`;
the self-test fake launcher at `self_test.py:548`.
- **Dry run.** MXC does not print the JSON envelope for a `--dry-run` refusal. In the `525d0f25` source, `wxc/src/main.rs` calls
  `handle_dry_run_exit`, which prints `Dry run completed. Result: validation failed: <msg>` to stdout and exits. That
  happens before `emit_backend_error_envelope`. A parser rejection goes through `Request error\nConfiguration parse error: ...`
  on stderr, again with no envelope. The REAL banked refusals
  (`docs/research/windows-containment-comparison-2026-10/mxc-1406-probe/raw/run-L-off-a-r1-132518.json`,
  `run-L-off-b-r1-132522.json`) fed as the dry run of a standard-mode record -> **INSTRUMENT-BLIND "LAUNCH-FAILED, NOT
  ANSWERED ... MXC error codes seen: none"**. The `525d0f25` dry-run shape gives the same result. So REFUSED cannot be
  reached from MXC's real dry-run output. The locks "dry-run refusal -> REFUSED" and "end to end, refusing launcher: batch
  REFUSED" pass only because the fake launcher prints a `{"code":"policy_validation",...}` envelope that MXC never
  prints at a dry run. Those locks overclaim.
- **Launch.** The real launch envelope is `{"error":{"code":"policy_validation","message":...}}` on stderr, and it parses.
  But the second gate (the message must match `REFUSAL_TEXT`) drops real `ScriptResponse::rejected` messages from the
  process-container runners. Each of these -> **INSTRUMENT-BLIND**:
  - "network.ingress.default='allow' cannot be combined with denied network egress on the AppContainer fallback ..."
  - "... allowedProxyPeer ... cannot be combined with network.ingress.hostLoopback='allow' ..."
  - "... cannot be combined with processContainer.leastPrivilege because it does not support LPAC tokens"
  - "The supplied `process.env` cannot launch a Windows process container because it is missing ..."
  - "ProcessContainer does not support caller-controlled PTY spawning"

  Messages that contain "not supported" or "requires" do read REFUSED-AT-LAUNCH.
- **Cost:** MXC saying no is reported as "not answered", and the label claims the launch failed when MXC actually
  answered. No false HOLD or FAIL can come from this. Under a standard token the dry run is largely independent of the
  token: `base_container_runner.rs` validate returns early for a dry run. So a dry-run refusal specific to this mode
  is unlikely.
- **Reproduced:** `drv/attack.py` sections A and B.
- **Incidence:** 0 in case 1 (all accepted); 6 of 6 banked dry-run refusals from #1406 (2 shapes x 3) would read BLIND.
- **What would close it:** accept MXC's own fixed dry-run forms (`Result: validation failed:`, and
  `Configuration parse error:` after `Request error`) as its structured refusal. Treat the `policy_validation` code alone
  as the discriminator at launch, because it is MXC's own: `FailurePhase::Rejected` is the only phase mapped to it. Point
  the fake launcher at real bytes.

### 2. MEDIUM: a real direct reach reads INSTRUMENT-BLIND, not FAIL, when the record's own token fails the standard check
`summarise.py` `judge_run`: the standard-token test runs first and returns before the FAIL rules.
- **Reproduced** (`drv/attack.py` section F): a B3 run-tagged hit on the second listener, or a B4(i) connect, in a
  standard-mode record whose record token is unreadable (`elevated None`), elevated, or absent -> INSTRUMENT-BLIND. The
  only reason given is the token, so the hit is not mentioned in the verdict at all. A token that is not a dict ->
  AttributeError (finding 4).
- **Not broken:** every malformed PAYLOAD token (missing key, None, not an AppContainer, a string) with a B3 hit or a
  B4(ii) connect -> **FAIL**.
- **Reachability:** close to zero. `token_record` reads this process's own token, which does not change, and
  `run_probe.py` refuses at start unless it is non-elevated and Medium. It would need the ctypes read to fail
  mid-batch.
- **Cost:** the brief's rule "a real direct reach must read FAIL in every path" is not met on this path. A reach would
  surface as "not answered" with the escape visible only in the raw `target_log`.
- **Fix shape:** run the FAIL rules before the token gate, or carry the hit into the reasons.

### 3. MEDIUM (harness, outside the commit): the runner's time limit leaves the command's processes running
`_tools/run_nonelevated.ps1` (`ExecutionTimeLimit` ends `conhost --headless`, not its process tree).
- **Reproduced:** `-CommandLine "python -c time.sleep(150) && echo CMD_EXIT_ZERO || echo CMD_EXIT_NONZERO" -TimeoutSec 15`.
  The runner returned after 24 s with `exit=267014`. The python process (PID 4536) was still alive afterwards. I stopped
  it by hand, and the surviving `cmd` then wrote `CMD_EXIT_NONZERO` into the output file.
- **Cost for the live run:** if the 3000 s limit is hit, `run_probe.py` and any `wxc-exec` keep running unattended
  with ports 18110 and 18111 held. The console file then has no PROBE_EXIT line, and a later attempt is refused
  ABORTED-PORT-HELD (fails closed).
- **Reachability:** a normal A,B x3 run takes minutes. The run's own bounds (dry run 600 s, launch 300 s, per run)
  can only add up to more than 3000 s if several of them hang.
- **Rule for the run:** a missing PROBE_EXIT line means check for a live `run_probe.py` before doing anything else.

### 4. LOW: `judge_run` raises AttributeError on a record token or attempt report that is not a dict
`summarise.py` (`tok.get`, and `r.get` in `direct_attempt_problems`). In `run_one` the verdict is computed before
`run-<tag>.json` is written, so a crash there loses the raw record of that run.
- **Reproduced:** `drv/attack.py` F (token `"x"`) and G (`b3` = `[1]`).
- **Reachability:** none from the hash-bound `net_payload.py`, which always writes dicts.

### 5. INFO: the container-token check accepts `is_appcontainer: true` with any integrity level
A payload token `{"is_appcontainer": true, "integrity_sid": "S-1-16-8192"}` -> HOLD (`drv/attack2.py`). Windows
cannot produce that combination (AppContainer tokens are Low integrity), so this is noted, not counted.

## Attacked and not broken
- **H1's own shapes:** `backend_error` with refusal words, OS errors and panics with no envelope, keyword text, and a
  `policy_validation` beside a `backend_error` all read BLIND. A real-shape (`{"error":{...}}`) `policy_validation`
  whose message says "not supported" or "requires", with an MXC log showing no process start -> REFUSED-AT-LAUNCH.
- **MXC log contents:** `525d0f25` telemetry events carry no `code` key, so the log cannot inject or veto an envelope.
- **No HOLD without the controls or the attempts:** an empty or absent B3, B4(i) or B4(ii); a `connected` that is not
  a bool; a not-connected result with no code; a timeout code; no container token, or one that is not an AppContainer
  token. Every one of these -> BLIND.
- **The token gate:** launch.ps1 refuses an elevated token for `-Token standard`, and for `-VerifyOnly` too.
  `--token`, `--launch-sha256` and a git-tree `--out` all fail closed.
- **The hash gate:** a one-byte change in the approval file -> REFUSED.
- **Visible windows:** none during my dry run or either self-test run.

## Merge read
Not blocking. Finding 1 should be fixed before this record becomes the citable answer on whether MXC refuses this
from a standard token. Finding 2 is a near-unreachable conflict with the stated rule. Finding 3 is a run-procedure
condition. None of the three can produce a false HOLD or a false refusal.

Suites run: `self_test.py` twice, non-elevated, at `1c6638aa`, on a quiet machine (206/0 and 206/0). I ran the
standard-token dry run myself. The standing gate was not run (this folder is outside it).

## Unattended run command
Preconditions: no other MXC, AppContainer or self-test work running; ports 18110 and 18111 free.

```
pwsh -NoProfile -File %USERPROFILE%\blarai-research-data\_tools\run_nonelevated.ps1 -CommandLine "\"C:\Program Files\PowerShell\7\pwsh.exe\" -NoProfile -NonInteractive -ExecutionPolicy Bypass -File %USERPROFILE%\BlarAI-worktrees\q3-standard-token\tools\probes\mxc_proxy_egress\launch.ps1 -Token standard --arms A,B --runs 3 && echo CMD_EXIT_ZERO || echo CMD_EXIT_NONZERO" -OutFile %USERPROFILE%\blarai-research-data\mxc-proxy-egress\q3-live-console.txt -TimeoutSec 3000
```

Read the outcome from `PROBE_EXIT=` and the run folder's `batch-summary.json`, never from the runner's `exit=` line.
If there is no PROBE_EXIT line, check for a live `run_probe.py` (finding 3).
