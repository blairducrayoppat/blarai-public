# Pre-run adversarial review, round 3: MXC loopback-proxy egress probe

- Reviewed: branch `feat/mxc-proxy-egress`, commit `25210ef3` (round-2 fixes on top of `05333c62`), `tools/probes/mxc_proxy_egress/`. The working tree matched HEAD at review time (`git diff HEAD` empty for the folder; `launch.cmd` is `w/crlf` per `.gitattributes`, as in round 2).
- Spec: CASE_1_mxc-loopback-proxy_2026-10-15.md (v2), read only. MXC source read at `C:/blarai-spike-1740-mxc/build-main-20261015/src-main/mxc-525d0f25.../src`. Prior record: `docs/research/windows-containment-comparison-2026-10/mxc-1406-probe/` (raw run records and the 23 MXC launch logs under `C:/blarai-spike-1740-mxc/logs` and `.../probe1406/logs`).
- Reviewer: independent; did not write the code and did not do rounds 1 or 2; fixed nothing. Finished 2026-10-15 16:04 -04:00 (20:04 UTC).
- **Verdict: PASS.** No BLOCKER or HIGH. One MEDIUM (finding 1), which I recommend fixing before the live run (one predicate), but which does not block. Approval file written (hashes at the end).

## What I ran (all through `run_nonelevated.ps1`; every output file opens with `whoami /groups` showing `Medium Mandatory Level` and `BUILTIN\Administrators ... Group used for deny only`)

Scratch: `%TEMP%/claude/.../scratchpad/r3mxcproxy/`. I did not use the round-2 folder's fixtures: its `attack2.py` now belongs to another reviewer's case-2 harness (it imports `mxc_denied_subtree`), so the round-2 attacks were rebuilt here.

1. `python -I self_test.py`: **107 PASS, 0 FAIL**.
2. `run_probe.py --out <scratch>\dryout --arms A,B,B0 --dry-run-only`: `elevated: False`; all three `dry_rc 0`; header `arm_commits` B `525d0f25...` and B0 `70fc7d52`, both "from the known-build table (launcher sha256 matched)"; gateway `10.0.10.1`, port 80; MXC state dir empty after the three dry-runs.
3. `attack3.py`: verdict fixtures against `summarise.judge_run` / `judge_batch`, built from the self-test's own `syn()`.
4. `e2e3.py`: the round-2 end-to-end attacks re-run through `run_probe.main` with the self-test's fake launcher, plus two new fake modes (`ranfailed`, `deadstart`).
5. `launchtest.py`: `launch.ps1` on a temp copy with a stub `run_probe.py`, using the REAL elevation detection (no `-SelfTestElevation`), and a forged `__pycache__` entry behind a hash-approved source.
6. Read-only checks: launcher sha256s against `build.log` files; MXC source greps (launch-path messages, error envelope, WFP calls, token privileges); regex scan of every banked MXC launch log.
7. certutil hashes of the eight probe files (non-elevated), cross-checked with `sha256sum`; `launch.ps1 -VerifyOnly` against the written approval file: `VERIFIED`, exit 0.

No container was launched. Nothing bound a non-loopback address. Nothing ran elevated.

## Round-2 findings

| R2 # | Round-2 finding | Status at 25210ef3 | Evidence |
|---|---|---|---|
| 1 | HIGH: REFUSED-AT-LAUNCH for runs whose own record shows the container ran; lock mandated it | **Fixed for every shape with host-side traffic.** Residual: finding 1 below (no-traffic shapes) | `attack3.py`: A3 true refusal -> `REFUSED-AT-LAUNCH`; A1 (3 tagged B2 forwards, refusal text) -> `INSTRUMENT-BLIND` "(launch exit 3; workload ran: True)"; A2 (untagged in window) -> `INSTRUMENT-BLIND`. `e2e3.py` `ranfailed`: run `INSTRUMENT-BLIND`, 3 tagged forwards, batch `INSTRUMENT-BLIND`. The self-test lock now carries the A1/A3 split on the same refusal text, plus a toggle. |
| 2 | MEDIUM: batch-summary says HOLD when the last run changed state | **Fixed** | `e2e3.py`: state change in the 6th snapshot -> rc 4, `STOP: changed state`, batch `STOPPED-STATE-CHANGE`, `state_changed_runs: ['B-B1-r3-...']`, run verdicts `HOLD x3`. |
| 3 | MEDIUM (escalation): B4(i) reach routing; arm-A FAIL ends the evening before arm B | **Documented, not decided.** README now quotes both networking.md sentences for B4(i). The harness still returns 5 on the first FAIL, so an arm-A FAIL means arm B does not run in that invocation. | Read. Still the spec owner's decision; carried below. |
| 4 | MEDIUM (escalation): elevation | **Decided and enforced:** live runs refused unless elevated; `--dry-run-only` allowed. Residual: findings 3 and 4 below | `launchtest.py`, real detection, non-elevated: `--arms A` -> exit 1 "REFUSED: a live run must be launched elevated"; `--dry-run-only` -> starts; abbreviated `--dry-run-o` -> refused (the safe direction). The not-measured lists do not name "a non-elevated launcher" (round 2 asked for it): finding 8. |
| 5 | LOW: 10013-only rule may blind the evening | **Unchanged, as stated** | `ENFORCEMENT_CODES = frozenset({10013})`. Still cannot hide a FAIL (FAIL precedes every BLIND rule). |
| 6 | LOW: untagged connection after `launch.ended` ignored | **Fixed** | `_in_window` is now `at >= start`. Self-test `stray="after"` -> BLIND, with toggle. Host-control entries are excluded by marker prefix and each run has fresh listeners, so the rule cannot blind the next run's controls (finding "could not break" below). |
| 7 | LOW: reused `--out` merges attempts | **Fixed** | `e2e3.py`: second batch into the same folder -> rc 2, "already holds a batch header; each batch needs a fresh output folder"; folder still holds only the first batch's 3 records. |
| 8 | LOW: arm provenance constant; B0 none | **Fixed** (residuals: finding 7) | `KNOWN_BUILDS`: `e951922b...` -> `525d0f25...` matches `build-main-20261015/build.log`; `3cf91a45...` -> `70fc7d52` matches `build1406/build.log` (source dir `mxc-70fc7d52c4ff...`). A contradicting commit refuses the arm (self-test). |
| 9 | LOW: gateway and port selection narrow | **Unchanged, as stated** | `gateway_ip` / `GATEWAY_PORTS` untouched. Incidence here 0 (10.0.10.1:80 reached). |
| 10 | LOW: non-zero launcher exit not surfaced with a payload | **Fixed** | `e2e3.py` `exit7`: batch HOLD with `launcher_nonzero_exit_runs` listing all 3 tags; run carries `launcher_nonzero_exit: 7`. |

## Findings, most severe first

### 1. MEDIUM: REFUSED-AT-LAUNCH still fires on a launched workload that died before sending any traffic, because the refusal regex reads the workload's own stderr
`summarise.py:53` (`REFUSAL_TEXT`), `:151-154`.

- **What is wrong:** the gate is "exit non-zero, no payload, no host-side traffic, and `refus|reject|not supported|unsupported|requires|invalid|validation failed` anywhere in stderr, stdout or the MXC log tail". wxc-exec runs the child in `STDIO mode: passthrough` (MXC log, banked 10-11 runs), so `launch.stderr_tail` is mostly the payload's and Python's own output. The regex therefore judges "did the launcher refuse?" from text the workload printed.
- **The direct discriminator is on disk and unused.** A launched run's MXC log carries `process created (PID: N)` and `{"event":"mxc.ProcessExited",...,"exit_code":N}` (every one of the 23 banked launch logs). On error, wxc-exec prints a JSON envelope whose `code` is `policy_validation` only for `FailurePhase::Rejected` and `backend_error` otherwise (`script_runner.rs:102-120`, `models.rs:1151-1193`). The harness reads neither.
- **Failure scenario:** arm B is accepted; under the new PSEC 1.1 path the container's Python fails at start, or the payload's B2 cannot reach the proxy, B3/B4 are refused, and the report write fails, so no host log line exists. If that output contains one of the words (for example `OSError: [Errno 22] Invalid argument`, or a start-up error naming an "invalid" value), all three runs read REFUSED-AT-LAUNCH: "main does not yet do what its doc says", a public plain measurement per the spec, while MXC's own log says the process was created and exited 1.
- **Reproduced:**
  - Synthetic (`attack3.py`), MXC log tail containing `process created (PID: 4242)` and `mxc.ProcessExited exit_code 1`:
    - Python EINVAL traceback -> `REFUSED-AT-LAUNCH`
    - start-up failure text containing "invalid" -> `REFUSED-AT-LAUNCH`
    - same with `PermissionError: [Errno 13] Permission denied` -> `INSTRUMENT-BLIND` (the outcome flips on the child's wording).
  - End to end (`e2e3.py`, fake mode `deadstart`: the "container" prints `Failed to find real location of python.exe` / `OSError: [Errno 22] Invalid argument` and exits 1 with no traffic): `rc 0 | batch REFUSED-AT-LAUNCH ['REFUSED-AT-LAUNCH', 'REFUSED-AT-LAUNCH', 'REFUSED-AT-LAUNCH']`.
- **The lock over-certifies.** Self-test check "container ran then the launcher failed with refusal-like text and no report: INSTRUMENT-BLIND" passes only because its fake container sent B2 traffic first (mode `crash` allows the proxy port). No fixture covers a launched workload with no host traffic.
- **Incidence:** 0. No failed launch is banked, and the regex has 0 hits across all 23 banked MXC launch logs (`probe1406/logs`, `logs/E*`), so the MXC side does not trip it on a clean launch. The risk is the child's text plus the no-traffic shape.
- **Mitigation already present:** the RAL reasons carry the stderr verbatim (first 600 chars), so a reader of the reasons would see a Python traceback.
- **Why not blocking:** a narrow shape (no traffic and a matching word), the reasons expose it, and the spec puts review and the register before anything public. **Recommended before the run:** forbid REFUSED-AT-LAUNCH when the MXC log tail contains `process created (PID` or `mxc.ProcessExited`, with a fixture for the no-traffic launched shape and its toggle.

### 2. LOW: the hash binding does not bind what Python executes (`__pycache__`)
`launch.ps1:47-53, :74`.

- `launch.ps1` hashes the four `.py` sources, then runs `python -I run_probe.py`, which imports `summarise`, `proxy` and `net_payload` from `HERE`. CPython uses a timestamp-validated `.pyc` from `__pycache__` when the source's mtime and size match its header, without reading the source. `__pycache__` already exists in the folder (ignored by git).
- **Reproduced** (`launchtest.py`, temp copy): a `summarise` pyc compiled from a same-length edit (`ENFORCEMENT_CODES = frozenset({10060})`), source restored with its original mtime: source hash still approved -> `True`; `launch.ps1 -VerifyOnly` -> `VERIFIED`; `python -I` imports -> `frozenset({10060})`.
- **Cost:** needs a deliberate forgery or a same-second, same-size edit, so the accidental incidence is near zero. But the README's "refuses to start unless the four probe files match" reads as "the approved code is what runs", and it is not. Options: run with `-X pycache_prefix=<empty temp dir>` or delete `__pycache__` before start.

### 3. LOW: `-SelfTestElevation elevated` is a live bypass of the elevation refusal, and the real detection is never exercised by the self-test
`launch.ps1:24, :63-64`; `self_test.py:321-328`.

- Any operator invocation can pass it (`launch.cmd -SelfTestElevation elevated --arms A`). **Reproduced** (`launchtest.py`, non-elevated): exit 0, probe started with `--arms A`.
- The batch header records the true `elevated` from `IsUserAnAdmin`, so a bypassed run is visible in the record, not hidden. Hence LOW.
- All three self-test elevation checks pass the override, so the `IsInRole` branch is untested there. I tested it directly instead: non-elevated live args are refused, and `--dry-run-only` is allowed.

### 4. LOW: the elevated-only snapshot path is untested, and its WFP count cannot see the filters that enforce this case
`run_probe.py:279-290`.

- **Live runs now always take this path.** Since `launch.ps1` refuses non-elevated live runs, every live snapshot runs `netsh wfp show filters`. No self-test, dry-run or reviewer run has executed that branch: the self-test and `--dry-run-only` are non-elevated, and `--dry-run-only` takes no snapshot.
- **Two hypotheses (not run):**
  - a `netsh` stall past 180 s raises an uncaught `TimeoutExpired`, which would lose that run's record, including the launch evidence if it happens in `snapshot_after`;
  - the dump is written into the MXC state directory (`MXC_DACL_STATE_DIR`), which `wxc-exec` scans for orphaned state on every start (`recover_orphaned_state`). The file is deleted after a successful read, but a failed `netsh` that leaves a file behind would be seen by the next snapshot and by MXC.
- **The count is blind to the enforcing filters.** MXC adds no WFP filters itself: there is no `Fwpm*` call anywhere in the source, and banked launches log `"enforcement_mode":"capabilities","firewall_rules_created":0`. The OS creates the per-container filters, under OS-chosen names; MXC's learning-mode code names a "Tessera" sublayer `{7B1E9A2C-...}` for them. A name match on `mxc|wxc` will very likely read 0 before and after every run. That is a readable number that certifies nothing (hypothesis: I cannot read WFP non-elevated).
- **Spec gap.** The spec's per-run "WFP filter list for the container's session" is not captured and is not in any NOT MEASURED list.
- **Suggestion:** before the evening, run one elevated `snapshot()` pair by hand, or count filters in that sublayer.

### 5. LOW: a real launch-time refusal whose wording misses the regex is INSTRUMENT-BLIND, and the BLIND reasons omit the text
`summarise.py:166-171`.

- `attack3.py`, with no traffic:
  - `CreateProcessInSecurityEnvironment failed: ... Access is denied.` gives `INSTRUMENT-BLIND`, and the stderr is not among the reasons;
  - an envelope `{"code":"policy_validation", ...}` whose message lacks the words gives `INSTRUMENT-BLIND`;
  - "The data is invalid." gives `REFUSED-AT-LAUNCH`.
- So the label follows Windows' wording of the HRESULT, not MXC's own classification.
- **This is the fail-closed direction:** BLIND, never a false HOLD. The real MXC launch-time rejection texts I found (`PSEC_INGRESS_UNSUPPORTED_MSG` "...requires Process Security Environment contract version 1.1..." and "...schema version is not supported") both match (`N4` -> `REFUSED-AT-LAUNCH`).
- **Cost:** a night's answer becomes BLIND, and the operator must open the raw record to see why.

### 6. LOW: a reach that lands in the next run's listener is BLIND, not FAIL
`summarise.py:130, :184-191`.

- A prior run's tagged B3 marker (`B-B1-r1-...-b3-1`) arriving after this run's launch start is an "unexplained connection", so the run is `INSTRUMENT-BLIND` (`attack3.py` N5).
- The reach is from a container, but neither run calls it FAIL.
- It needs a prior run whose container outlived a 300 s launcher timeout (that run is itself BLIND by the timeout rule), so the incidence is near zero. The raw record keeps the line.

### 7. LOW: arm-commit residuals
`run_probe.py:150-160`; batch header.

- **A one-character prefix passes as a match.** `resolve_arm_commit(<B sha>, "5")` returns `('5', 'given on the command line (matches the known-build table)')`. The recorded commit is then `5`, and the basis line says it matches the table.
- **An over-long string passes too.** `525d0f25...cbbd93ffff` is accepted as given.
- **Arm A has no release tag.** Nothing in the header says `v1.0.0`; the spec's ENVIRONMENT asks for "MXC release tag for arm A". The header carries the signed sha256 `aa444c0f...` and `Valid|CN=Microsoft Corporation`.
- **B0's commit is abbreviated** in the table: `70fc7d52`, where the full id is `70fc7d52c4ff2852c7be16da1c0666c8d6811e63`.

### 8. LOW: prose that outlived its code
- **Precedence in the `summarise.py` docstring (lines 24-26).** It lists STOPPED-STATE-CHANGE after HOLD, as if it came after REFUSED. The code checks it second, right after FAIL: three REFUSED runs with one state change give `STOPPED-STATE-CHANGE` (`attack3.py` N7). The code's order is the safer one, so the docstring is the thing that is wrong.
- **"During the launch window".** `run_probe.py:13-14` ("any unexplained listener connection during the launch window blinds the run") and the self-test docstring line 9 still say this. The rule is now "at or after the launch start".
- **NOT MEASURED lists.** None of them (five docstrings and the README) names "a non-elevated launcher", although round 2 finding 4 asked for it and the 10-11 record lists it.
- **Elevation reason.** The `launch.ps1` refusal text gives "the filter writes the containment needs are privileged". MXC itself writes no filters on this path (finding 4); the doc's sentence is the source of that claim. The prior-record reason (10-11 was elevated) stands on its own.

### 9. LOW: `--runs 1` yields a batch HOLD, and the standalone summariser disagrees with the harness
`run_probe.py:545`; `summarise.py:280`.

- **The harness judges against `--runs`.** It passes `args.runs` as `n_expected`, so `--runs 1` writes HOLD for one run, while the spec fixes n = 3.
- **The standalone summariser uses the default of 3.** `python -I summarise.py <folder>` rewrites the same `batch-summary.json` as `INCOMPLETE` (`attack3.py` N9).
- The `runs` count is in the summary, so this is visible, but two tools write different verdicts into one file.

## Escalations carried (spec owner, not harness blocks)
- **B4(i) routing and arm order (round 2 finding 3):** a gateway reach is still a FAIL that returns 5 and ends the invocation, so in an `A,B` batch an arm-A FAIL means arm B does not run. The spec says case 1 runs both arms. The operator can start `--arms B` separately, but the spec owner should say whether that is intended before the evening.

## Token question: SeBackup and SeRestore under an elevated console
- **Neither privilege is enabled by any code on the launch path.**
  - In the harness, `run_probe.py` makes no `AdjustTokenPrivileges` call, and `sddl_of` reads the DACL only (`DACL_SECURITY_INFORMATION`, no backup semantics). Python's stdlib enables no privileges.
  - `launch.ps1` and `launch.cmd` call nothing that enables a privilege.
  - In MXC (source grep, 525d0f25), the only `AdjustTokenPrivileges` is in `wxc-host-prep` (`null_device/privileges.rs`), and it enables `SeSecurityPrivilege` only. The harness never invokes host prep (`host_prep.run_by_harness: false`). `wxc-exec` enables nothing.
- **Elevated tokens hold them disabled.** By Windows default, an elevated administrator token holds SeBackup and SeRestore present but disabled. I could not observe the elevated token, because this review was constrained to the non-elevated runner.
- **They do not matter for this case.** Its subject is network: WFP enforcement is keyed to the container's identity, and holding (let alone enabling) file-backup privileges does not bypass it. They would matter to a filesystem case, not this one.
- **Not measured:** the token privileges of the container child when launched from an elevated `wxc-exec`. The header records `elevated` as one boolean. Recording `whoami /priv` of the launching process in the batch header would close that gap.

## Attacked and could not break
- **REFUSED-AT-LAUNCH with any host-side trace.** Tagged forwards, an untagged in-window entry, or a late untagged entry each force `INSTRUMENT-BLIND` (synthetic and end to end). A true no-traffic refusal with MXC's own rejection text gives `REFUSED-AT-LAUNCH`.
- **The unbounded late-entry rule cannot blind the next run's controls.**
  - Each run builds fresh listeners with empty logs.
  - Host-control lines (`host-control-*`, including the proxied host-control request, whose marker header is forwarded) are excluded by prefix and precede the launch anyway.
  - The B5 control is judged without the window.
  - Nothing the harness itself does after the launch touches a loopback listener: `unfenced_post` goes to 1.1.1.1 and the gateway only.
- **STOPPED-STATE-CHANGE precedence:** FAIL with a state change stays FAIL (N8). A state change outranks REFUSED, REFUSED-AT-LAUNCH, BLIND and HOLD. The harness prints STOP and returns 4, and the file says the same.
- **Dry-runs and the snapshot:** dry-runs leave the MXC state directory empty, so the snapshot's `state_dir` key does not trip on a dry-run.
- **Elevation refusal:** the real detection refuses non-elevated live args; an abbreviated `--dry-run-o` (which argparse would accept as the flag) is refused rather than let through; `--dry-run-only` passes.
- **Output-folder reuse:** refused (rc 2).
- **Known-build table:** both entries match the build logs on disk. A contradicting commit refuses the arm.
- **Banked MXC launch logs:** 0 regex hits across 23 logs, so a clean MXC launch does not trip the refusal regex by itself.
- **Hygiene:** the self-test hygiene check passes. This review adds no account name, path with it, or numbered reference.

## Merge / run read
- **Not blocking:** findings 1 to 9.
- **Fix before the run (small):**
  - Finding 1: one predicate on the MXC log (`process created (PID` / `mxc.ProcessExited`), plus a no-traffic launched fixture and its toggle. It is the one remaining path to a false public "refused".
  - Finding 4: one hand-run elevated `snapshot()` pair, because the evening is the first time that code runs.
- **Fix when convenient:** findings 2, 3, 7 and 8 (the pyc prefix, the self-test override, commit and tag provenance, and prose).
- **For the spec owner:** the carried B4(i) and arm-order escalation.
- **The approval below covers 25210ef3 as is.** If finding 1 is fixed, the hashes change and the folder needs a new approval.

Suites I ran, at 25210ef3, non-elevated (Medium integrity): `self_test.py` 107/0; `--dry-run-only` (A, B, B0); `attack3.py`; `e2e3.py`; `launchtest.py`; certutil hashing; `launch.ps1 -VerifyOnly` against the approval file (VERIFIED, exit 0).

Approval file written: `%USERPROFILE%/blarai-research-data/mxc-proxy-egress/APPROVED_SHA256.txt`, header `approved 2026-10-15T20:04:01Z commit 25210ef3 reviewer non-elevated round 3`, eight files (`__pycache__` not hashed):

```
51e13dfc323f35467f93301eb95ad011332fb0465b610e595c4f92769030f555  README.md
20182abc95f3b3740ee32eeb855d2832cd1d63acaa6919d7f34648470140845f  launch.cmd
d94e93d8bb53065c11bc54423802dd10dd311748d80e0a944c02e11c7e635a03  launch.ps1
372b812c4f770305a5495c650af3a4ad58297278b64c69a201b8d8bfdeaf6b21  net_payload.py
9057ef74f8d877ec2ccf15990c75ada7e27b9cf84369ce3d1a712f85fbf8e814  proxy.py
979c21d546af264702ea9df8ca1f2b9f25ad038d9f1425019c85a1e4aa945879  run_probe.py
1211e7b379d27e6521f7a823105d3cdcef2706c90f2f7fc56f447670e7691362  self_test.py
78ee0b4090fe060f6ab065f8bd3a3076ef678aabc51809e932b633de798ec706  summarise.py
```
