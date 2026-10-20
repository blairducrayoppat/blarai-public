# Pre-run adversarial review, round 2: MXC loopback-proxy egress probe

- Reviewed: branch `feat/mxc-proxy-egress`, commit `05333c62` (round-1 fixes on top of `490c2bcd`), `tools/probes/mxc_proxy_egress/`. The working tree matched HEAD at review time (sha256 of every file taken from disk; `git diff HEAD` empty).
- Spec: CASE_1_mxc-loopback-proxy_2026-10-15.md (v2), read-only. Run-day re-reads: `%USERPROFILE%/blarai-research-data/run-day-rereads-2026-10-15.md`. Prior record: `docs/research/windows-containment-comparison-2026-10/mxc-1406-probe/README.md`. MXC source read at `C:/blarai-spike-1740-mxc/build-main-20261015/src-main/mxc-525d0f25.../src`.
- Reviewer: independent; did not write the code and did not do round 1; fixed nothing. Review finished 2026-10-15 15:40 -04:00 (19:40 UTC).
- **Verdict: FAIL.** One HIGH finding (1). No approval file was written.

## What I ran (all through `run_nonelevated.ps1`; every output file opens with `whoami /groups` showing `Medium Mandatory Level` and `BUILTIN\Administrators ... Group used for deny only`)

1. `C:\Python314\python.exe -I self_test.py`: **82 PASS, 0 FAIL**, exit 0 (finished 15:31 -04:00).
2. `run_probe.py --out <scratch>\dryout --arms A,B,B0 --dry-run-only`: all three arms `dry_rc 0`, "Dry run completed. Result: validation passed", `selected isolation tier: base-container`. Header: `elevated false`; gateway `10.0.10.1`, port selected `80`; firewall product `McAfee|266240`; host and container interpreter sha256 recorded; `arm_b_commit 525d0f25...`; scope notes A `IngressHostLoopbackAllow=True, IdentitylessLoopbackProxy=None`, B and B0 `True, True`; arm B launcher sha256 `e951922b...` (equals the hash `build.log` prints for the 525d0f25 build).
3. A state probe calling `run_probe.snapshot()` twice, `gateway_ip()`, `pick_gateway_port()` and `firewall_state()` non-elevated: snapshot readable (rules, profiles, loopback exemptions "OK.", WinHTTP "Direct access", WFP `unreadable: not elevated`), **identical across two calls**; one default route (Wi-Fi, 10.0.10.1).
4. Verdict fixtures against `summarise.judge_run` built from the self-test's own `syn()` (`attack2.py`), and two end-to-end variants through `run_probe.main` with the self-test's fake launcher (`e2e_ran_failed.py`, `e2e_state.py`). Scratch: `%TEMP%/claude/.../scratchpad/r2/`.
5. A loopback-only rebind test: four back-to-back `Instruments()` constructions with 113 to 121 TIME_WAIT sockets on 1811x present; every exclusive bind succeeded.
6. Read-only: python firewall rules before and after all of the above: both `Python|False|Inbound|Allow`, unchanged.

No container was launched. Nothing bound a non-loopback address.

## Round-1 findings

| # | Round-1 finding | Fixed? | Evidence (at 05333c62) |
|---|---|---|---|
| 1 | HIGH: LAN listener raises a firewall prompt; confound invisible to B5 | **Fixed** | No non-loopback bind in any file (`bind(` only in proxy.py:51, :71 and self_test.py:128, all 127.0.0.1); `ProbeListener` and `ForwardingProxy` raise `ValueError` on any other host (self-test checks pass). B4(i) is now connect-only to the default gateway on a port an unfenced pre-check reached. Interpreter firewall rules are in `snapshot()`. Python firewall rules unchanged across the self-test and dry-run. |
| 2 | MEDIUM: dead uplink manufactures a HOLD | **Fixed** | `b4ii` 10060 and `b4ii` timeout with no code: both INSTRUMENT-BLIND (`attack2.py`). Unfenced 1.1.1.1:443 and gateway connects run before and after every launch (run_probe.py:385, :396). |
| 3 | MEDIUM: untagged hits ignored; lock mandated it | **Fixed** (residual: finding 6 below) | Untagged entry inside the launch window with a refused payload: INSTRUMENT-BLIND; the old lock is replaced by self_test.py:171-176 with a toggle. |
| 4 | MEDIUM: launch refusal reported as BLIND | **Fixed as specified, but the new predicate is too loose**: finding 1 below | `launch.exit_code 1`, no payload: REFUSED-AT-LAUNCH. |
| 5 | MEDIUM: host is no longer the PSEC 1.0-only host | **Harness half fixed**; escalation half not verifiable from disk | NOT MEASURED line reworded in all five docstrings and the README; `scope_notes` computed from the `--probe` flags (dry-run output above); README carries the policy-doc reading note for a B3 reach. Source confirms: `psec_1_0_proxy_loopback_workaround` (base_container_runner.rs:434) engages only when PSEC 1.1 is unsupported, so on this host the run measures the PSEC 1.1 path, not the 10-11 path. |
| 6 | LOW: ENVIRONMENT fields missing | **Partly fixed** | Arm-B commit, interpreter sha256, launch.ps1 sha256, firewall product and profiles, host prep, gateway, `probe_reports_psec_version` now in the header. Residual: finding 8 below. |
| 7 | LOW: hash binding narrower than it reads | **Fixed** (record-only, as designed) | launch.ps1 passes its own sha256 (`--launch-sha256`); run_probe.py also hashes launch.ps1; self-test check passes. `#` comment lines are skipped (launch.ps1:37). |
| 8 | LOW: launch.cmd line endings | **Fixed** | `git ls-files --eol`: `i/lf w/crlf attr/text eol=crlf`. The HEAD blob converted to CRLF hashes to `20182abc...`, the same as the file on disk, so the approved hash reproduces from a fresh checkout. |
| 9 | LOW: proxy co-binds a SO_REUSEADDR squatter | **Fixed** | `ExclusiveHTTPServer` (allow_reuse_address False + SO_EXCLUSIVEADDRUSE) and `exclusive_socket()`; self-test squatter checks pass for both, with a toggle showing a default http.server co-binds. TIME_WAIT does not block the next run's exclusive bind (item 5 above). |
| 10 | LOW: host changes not snapshotted | **Fixed** | Loopback exemptions, WinHTTP proxy, firewall rules for both interpreters, profiles, MXC-named WFP count (labelled `unreadable: not elevated` when not elevated); readable and stable non-elevated (item 3 above). |

## Findings, most severe first

### 1. HIGH: REFUSED-AT-LAUNCH is returned for runs whose own record proves the container launched, and the self-test lock certifies it
`summarise.py:133-140`; `self_test.py:192-194` and `:209-210` (fixtures built by `syn(with_payload=False, launch_exit=3)`, which carry three run-tagged B2 forwards in the proxy log and the second listener's log).

- **What is wrong:** the verdict needs only "no payload report and launch exit code non-zero". It never checks for evidence that the workload ran: run-tagged entries in the proxy log or the second listener's log, or any unexplained connection inside the launch window.
- **Failure scenario:** MXC accepts and launches. The payload sends its three B2 requests through the proxy (logged, forwarded, 200), then dies before writing its report, and wxc-exec propagates a non-zero exit. The batch reports REFUSED-AT-LAUNCH: "the launcher refused this policy at runtime". That is the A1/B1 answer the spec treats as a plain, publishable measurement, and it contradicts the run's own logs. The same shape answers "refused" when the container's Python fails to start under the policy. That is a workload failure inside an accepted container, not an MXC refusal.
- **The lenient direction too:** the only evidence of a B4(i) or B4(ii) reach is the payload report, because those destinations have no listener. A reach followed by a lost report and a non-zero exit is classified REFUSED-AT-LAUNCH, not INSTRUMENT-BLIND. With an untagged connection on the second listener inside the window (fixture A2), the verdict is still REFUSED-AT-LAUNCH.
- **The lock mandates the defect.** The self-test's REFUSED-AT-LAUNCH fixture is itself a record in which the container ran (3 B2 forwards). Its passing certifies the wrong verdict.
- **Reproduced:**
  - Synthetic (`attack2.py`):
    - `A1 launch exit 1, NO payload, but 3 run-tagged B2 forwards in proxy+target logs -> REFUSED-AT-LAUNCH`
    - `A2 ... untagged connection on target listener inside window -> REFUSED-AT-LAUNCH`
  - End to end through `run_probe.main` (`e2e_ran_failed.py`, the self-test's fake launcher with the payload run and its report removed, exit 1):
    - `run verdict: REFUSED-AT-LAUNCH ['launch exit_code=1', 'stderr: Traceback: payload crashed']`
    - `proxy_log tagged forwards in that run: 3`
    - batch `{'B/B1': {'verdict': 'REFUSED-AT-LAUNCH', 'runs': 3, ...}}`
- **Discriminating split this needs:** a true launch refusal with no traffic (A3) gives REFUSED-AT-LAUNCH, while a launched-then-failed run (A1, A2) gives INSTRUMENT-BLIND, on the same corpus. Today both give REFUSED-AT-LAUNCH.
- **Incidence:** 0 (no live runs). A crashing payload is unlikely (every probe catches OSError), but a non-starting container Python is an ordinary first-run shape under a new policy on a new PSEC path.
- **Cost when it fires:** a false "refused" answer to the spec's primary question, eligible for the public record. The reasons carry the stderr, but the batch line people act on says REFUSED-AT-LAUNCH.

### 2. MEDIUM: batch-summary.json says HOLD when the last run changed host state
`run_probe.py:516-525`. `judge_run` and `judge_batch` never read `state_changed_by_run`.

- The summary is written before the state-change check. A change in run 3 of 3 therefore leaves `batch-summary.json` at HOLD (3 of 3) while the harness prints `STOP: changed state` and returns 4. In runs 1 and 2 the same change gives INCOMPLETE, which is safe.
- **Reproduced** (`e2e_state.py`, the snapshot enables an interpreter firewall rule only in the 6th snapshot):
  - `rc 4 | printed: ['STOP: changed state; see the record']`
  - `batch-summary.json: {'B/B1': {'verdict': 'HOLD', 'runs': 3, ...}}`
  - last run `verdict: HOLD | state_changed_by_run: {'firewall_rules_for_interpreters': [['Python|False|...'], ['Python|True|...']]}`
- **Cost:** the file read later says HOLD on a batch whose last run had the round-1 confound (an interpreter firewall rule flipping). The STOP line exists only in the console transcript.

### 3. MEDIUM (escalate to the orchestrator and LA, not a harness block on its own): a B4(i) reach is documented behaviour by one networking.md sentence, yet it is a FAIL that stops the whole batch
`summarise.py:124-125`; `run_probe.py:520-522`; the README's reading note covers B3 only.

- `networking.md` (re-read on disk, run-day file §1b): "The containment boundary is the absence of direct internet capability. Private-network traffic remains available in both directions when `ingress.default` is `"allow"`." The same document also says WFP "blocks direct public and private destinations" on an enforcing BaseContainer path. The two sentences conflict for exactly the B4(i) destination (10.0.10.1:80).
- Arm A runs first by default and passes `--dry-run` on this host. If arm A run 1 reaches the gateway:
  - the harness prints STOP, returns 5 and arm B never runs;
  - the spec routes the result to MSRC as "a hole in MXC's egress scoping".
- The README already gives B3 an operator-read caution for documented behaviour. B4(i) has the same shape and no note.
- **Reproduced:** no (needs a container). This rests on the code path (read) and the doc text (on disk); the outcome itself is a hypothesis.
- **Decision for the spec owner:** whether a gateway reach routes to MSRC, and whether a FAIL in arm A may end the evening before arm B. The spec says case 1 runs both arms regardless.

### 4. MEDIUM (escalate; the brief's elevation question): elevation is recorded, but launches are untested non-elevated, and the 10-11 evidence was elevated
- **Recording works.** `batch-header.json` `elevated` and every run's `machine.elevated` come from `IsUserAnAdmin()`. It read `false` under the runner; I did not run elevated, so the `true` branch is not exercised here.
- **What the dry-run shows.** All three launchers pass `--dry-run` non-elevated with tier base-container. Dry-run is validation only and says nothing about whether WFP filters are installed at launch.
- **What the source shows.** The UAC-prompting WinHTTP shim (`proxy_coordinator.rs:129-153`, `ShellExecuteExW("runas")`) is started only from `appcontainer_runner.rs:1604-1606`; the BaseContainer runner never starts it. So no UAC prompt is expected on the base-container tier. If a launch fell to the AppContainer tier, a screen-taking UAC prompt would appear mid-run (hypothesis).
- **What the docs and the prior record say.** networking.md says "Both WFP filter writes and per-container WinHTTP proxy configuration require a privileged context". The 10-11 record ran from an "elevated console" and lists "a non-elevated launcher" as not tested.
- **Risk.** `launch.cmd` started by double-click runs non-elevated. A FAIL from a non-elevated run could reflect an unmet privilege precondition rather than a hole, and the harness neither prints the elevation at start nor qualifies a FAIL with it.
- **Decision before the run:** which elevation the run uses. Then state it in the not-measured list.

### 5. LOW: the 10013-only rule cannot hide a FAIL, but it may blind the whole evening
`summarise.py:49, :94-95, :168-175`.

- **It cannot hide a FAIL.** Every reach signal (container `connected: True`, a run-tagged listener entry, a container-reported connect with no listener entry) is judged before any BLIND rule. 10061, 10060 and 10051 each mean no handshake completed: `A4 B3 10061 -> INSTRUMENT-BLIND`, `A5 B4(ii) 10051 -> INSTRUMENT-BLIND`. So nothing reachable is classified BLIND instead of FAIL, except through a lost payload (finding 1).
- **The empirical basis is the old path.** "10013 only" rests on the 10-11 record: the PSEC 1.0 workaround path, elevated. This host takes the PSEC 1.1 path. If loopback blocking there comes from AppContainer loopback isolation, or the launch is non-elevated, the code may differ.
- **On B3 specifically.** The B2 control proves the listener was up. A 10061 on B3 is therefore attributable to enforcement, and round 1's fix text allowed it. The author chose the stricter rule.
- **Cost:** an evening of INSTRUMENT-BLIND, recorded with the code. This is not a false verdict.

### 6. LOW: an untagged connection after `launch.ended`, while the listeners are still open, is ignored
`summarise.py:86-91, :160-167`.

- The listeners stay up through `unfenced_post` and the log reads. An untagged entry 2 s after `ended` gives HOLD (`A6`).
- This combines with the launcher-timeout path, where a clean payload plus `launch.timeout` gives HOLD (`A8`). After `TimeoutExpired`, the container may outlive the killed wxc-exec. The fixture result is reproduced; the container surviving is a hypothesis.
- The round-1 window was defined this way; the entries remain in the raw record.

### 7. LOW: reusing an `--out` folder merges an earlier attempt into the batch and overwrites its header
`run_probe.py:444-448, :516`; `summarise.load_dir` globs `run-*.json`.

- **Reproduced** (`e2e_state.py` part b): a `blind` invocation followed by a `fenced` invocation into the same `--out` gives `runs: 6, run_verdicts: [BLIND, HOLD, BLIND, HOLD, BLIND, HOLD]`.
- The second header replaced the first, so three of the records are described by a header that is not theirs.
- With an earlier HOLD attempt and a later partial attempt, the merged batch can read HOLD.
- The default output path auto-increments, so this needs an explicit reused `--out`. A non-empty `--out` is not refused.

### 8. LOW: arm provenance is a constant, and B0 has none
`run_probe.py:75, :437, :468`.

- `arm_b_commit` is the argparse default. It is not derived from or bound to the binary, and the one field serves both B and B0.
- B0 (`build1406`, the 70fc7d52 build per the prior record) gets no commit field.
- **Incidence today:** 0. Arm B's sha256 `e951922b...` equals the hash `build.log` reports for the 525d0f25 source tree.

### 9. LOW: gateway and port selection are narrow
`run_probe.py:288-303`.

- `Sort-Object RouteMetric` ignores the interface metric.
- An on-link first route (`NextHop 0.0.0.0`, the usual VPN shape) returns None without trying the next route.
- Only TCP 80, 443 and 53 are candidates.
- On a network where none answer, every run and the B5 control are INSTRUMENT-BLIND. B4(ii) alone satisfies the spec's "one LAN or public destination", and the selected port is not printed at start.
- **Incidence here:** 0 (one default route; 10.0.10.1:80 reached).

### 10. LOW: a non-zero launcher exit is not surfaced once a payload exists
`summarise.py:133`. Exit 7 with a clean payload gives HOLD, and the exit code is not among the reasons (`A7`).

## Attacked and could not break
- **No non-loopback bind.** Both constructors refuse other hosts, and the self-test checks this. The self-test's own "no code path binds" check (self_test.py:449-451) is only a string grep, narrower than its name; the constructor guards are the real lock.
- **Exclusive binding.** It refuses REUSEADDR squatters. TIME_WAIT does not block the next run's bind (4 consecutive rebinds with 113 to 121 TIME_WAIT sockets present).
- **Snapshot.** Readable non-elevated and stable across two consecutive calls, so it does not stop the batch spuriously on an idle host. The self-test toggle stops the batch on change.
- **FAIL precedence.** A run-tagged B3 hit outside the window is still FAIL (`A10`). An untagged entry with an unparseable timestamp counts as inside (`A11`). Mixed timezone offsets compare correctly (`A12`). A gateway pre-control that was skipped while a port is recorded gives NOT-MEASURABLE, never HOLD (`A13`).
- **Unfenced controls before and after every launch.** A missing gateway port blinds both the run and the batch (self-test plus fixtures).
- **Arm-B precondition.** Reads the real `--probe` path. Arm A is reported as `IdentitylessLoopbackProxy=None` and is correctly not gated.
- **launch.ps1.** Refuses a mismatch, a missing file, a missing line and a missing approved file. It skips `#` lines and passes its own hash (self-test).
- **Hygiene.** The self-test hygiene check passes. No identifier was added by this review.

## Merge / run read
- **Block the live run on finding 1.** The fix is one predicate: REFUSED-AT-LAUNCH only when neither log holds a run-tagged or in-window entry, else INSTRUMENT-BLIND. The self-test lock must change with it, and the round needs the A1/A3 discriminating split shown.
- **Fix before the run (small, and the summary line is the one people act on):** finding 2.
- **Escalate before the run (the spec owner decides):**
  - finding 3: B4(i) routing, and whether a FAIL in arm A stops arm B;
  - finding 4: which elevation the run uses.
- **Not blocking:** findings 5 to 10.

Suites I ran, at 05333c62, non-elevated (Medium integrity): `self_test.py` 82/0; `--dry-run-only` (A, B, B0), which includes `--probe` and the batch header; the snapshot and gateway probe; verdict fixtures (`attack2.py`); two end-to-end variants through `run_probe.main`; the exclusive-rebind test; the firewall-rule re-read.

Approval file: **not written** (verdict FAIL).
