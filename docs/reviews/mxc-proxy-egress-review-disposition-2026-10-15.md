---
title: "MXC loopback-proxy egress probe: pre-run review rounds 1 to 3 and the post-run review, finding disposition"
status: closed
area: reviews
date: 2026-10-15
---

# MXC loopback-proxy egress probe: review disposition

**Subject:** the probe `tools/probes/mxc_proxy_egress/` on branch `feat/mxc-proxy-egress` and the records made from its two live batches. Four independent reviews, all in this folder:
`mxc-proxy-egress-prerun-review-round1-2026-10-15.md` (at `490c2bcd`, verdict FAIL, one HIGH), `...-round2-...` (at `05333c62`, FAIL, one HIGH), `...-round3-...` (at `25210ef3`, PASS, one MEDIUM) and
`mxc-proxy-egress-postrun-review-2026-10-15.md` (at `572e2421`, FAIL on one HIGH in the records; the measurement itself, HOLD for both arms in both conditions, was re-derived from raw and confirmed).

**Fix commits (BlarAI):** `05333c62` (round 1), `25210ef3` (round 2; the harness the live batches used), `32112e95` (round 3), `7a350732` and `16caf3af` (port pre-flight, then before every run),
`9b4d8c21` and `572e2421` (the first versions of the records), `ea2ccbe1` (post-run record fixes).
**Evidence repository** (`windows-containment-evidence`, branch `feat/mxc-proxy-egress`; a repository this verifier does not know, so its commits are named here and not in the block): `fa4302a` and `89a8606` (the bundle, then condition 2),
`c8824b3` (post-run record fixes: the launcher-logged PSEC version, the unisolated cause, operator-only facts marked, the self-test warning in the probe index).
**Tickets:** #1794 (pre-existing: the evidence repository's leak gate and the public mirror's address), #1795 (filed here: the research-tracker lock entry boundary), #1796 (filed here: the policy-hash question).

Notes on how rows are numbered: `R1-n`, `R2-n`, `R3-n` are the findings of the three pre-run rounds by their own numbers, `R3-esc` and `R3-tok` the round-3 escalation and token question, `P-n` the post-run review's findings.
The self-tests: 47 checks at `490c2bcd`, 82 at `05333c62`, 107 at `25210ef3`, 122 at `32112e95`. `7a350732` and `16caf3af` each added a self-test check that has NOT been run (the self-test binds the probe's loopback ports and a standing gate or a live run was pending); they are written, parse, and the pre-flight function itself was checked by hand on an ephemeral port.

```disposition
R1-1-lan-listener-prompt-and-confound-high | FIXED | 05333c62 the LAN listener and every non-loopback bind removed, B4(i) is a connect-only attempt to the default gateway judged from the container error code, listeners refuse non-loopback hosts, firewall state added to the snapshot
R1-2-dead-uplink-manufactures-a-hold | FIXED | 05333c62 only WinError 10013 counts as a refusal, a timeout blinds the run, unfenced 1.1.1.1:443 control before and after every launch
R1-3-untagged-listener-hits-ignored-and-a-lock-mandated-it | FIXED | 05333c62 an unexplained listener connection blinds the run and the old self-test lock was replaced by one asserting it
R1-4-launch-refusal-reported-as-instrument-blind | FIXED | 05333c62 REFUSED-AT-LAUNCH verdict with the launch own stderr; tightened in 25210ef3 and 32112e95
R1-5-host-no-longer-the-host-the-scope-sentence-describes | FIXED | 05333c62 the scope sentence reworded, scope notes computed from the --probe flags; the policy question for the spec owner was escalated and is recorded in R3-esc
R1-6-environment-fields-not-recorded | FIXED | 05333c62 arm commit, interpreter and launch.ps1 hashes, firewall product and profiles, host prep and gateway in the batch header
R1-7-hash-binding-narrower-than-it-reads | FIXED | 05333c62 launch.ps1 passes its own sha256 and the harness records it; the remaining gap (compiled files) was R3-2 fixed in 32112e95
R1-8-launch-cmd-line-endings-disagree-with-gitattributes | FIXED | 05333c62 working copy stored per its CRLF attribute
R1-9-proxy-co-binds-a-reuseaddr-squatter | FIXED | 05333c62 exclusive bind on the proxy and the listeners with self-test squatter checks
R1-10-host-changes-not-snapshotted | FIXED | 05333c62 firewall rules for both interpreters, profiles, loopback exemptions, WinHTTP proxy and the MXC-named WFP count added to the snapshot
R2-1-refused-at-launch-for-runs-that-launched-high | FIXED | 25210ef3 needs no sign the workload ran, true refusal versus launched-then-failed pair on the same fixtures with toggles
R2-2-batch-summary-says-hold-after-a-state-change | FIXED | 25210ef3 STOPPED-STATE-CHANGE batch verdict, console exit code and summary agree
R2-3-b4i-reach-routing-and-arm-order | REJECTED | The rule that any direct reach stops the whole batch is the Lead Architect rule, kept deliberately: a reach is a possible hole and a harness that decided whether documented behaviour excuses it would decide a question it does not own. The README now quotes both document sentences for the operator to read before routing; both batches here ended in HOLD so the stop never fired, and the arms can be run in separate invocations.
R2-4-elevation-question | FIXED | 25210ef3 live runs are launched elevated and launch.ps1 refuses otherwise, dry-run-only allowed; the elevation is recorded in every record
R2-5-ten-thirteen-only-rule-may-blind-the-evening | REJECTED | The rule cannot hide a FAIL because every reach signal is judged before any blind rule, and it errs toward INSTRUMENT-BLIND with the code recorded rather than toward a false verdict; widening the accepted codes would trade that guarantee for convenience. It held on all twelve live runs, which all gave the code 10013.
R2-6-late-untagged-connection-ignored | FIXED | 25210ef3 the stray-connection check covers every entry at or after the launch start, and a launcher timeout blinds the run
R2-7-reused-output-folder-merges-attempts | FIXED | 25210ef3 a folder that already holds a batch header is refused
R2-8-arm-provenance-is-a-constant | FIXED | 25210ef3 arm commit required or taken from a known-build table keyed by launcher sha256; hardened to 40 hex in 32112e95
R2-9-gateway-and-port-selection-narrow | REJECTED | The selection falls back to a non-measurable verdict and never to a hold when no gateway port answers, so narrowness fails closed; the specification asks for one LAN or public destination and B4(ii) at 1.1.1.1:443 already satisfies it. Incidence was zero: the default route was single and port 80 answered in both batches.
R2-10-nonzero-exit-with-payload-not-surfaced | FIXED | 25210ef3 the launcher exit code is always recorded and flagged per run and per group with no verdict change
R3-1-refused-at-launch-fires-on-a-launched-workload-that-died-silently | FIXED | 32112e95 requires a non-empty MXC log with no process created and no ProcessExited event, with a no-traffic launched fixture and toggle
R3-2-hash-binding-does-not-bind-pycache | FIXED | 32112e95 launch.ps1 refuses a folder holding compiled Python files and runs Python with -I -B and a fresh pycache prefix
R3-3-selftest-elevation-override-is-a-live-bypass | FIXED | 32112e95 the override is honoured only with the self-test environment variable, real detection otherwise
R3-4-elevated-snapshot-path-untested-and-wfp-count-blind | FIXED | 32112e95 netsh timeout caught and the dump written outside the MXC state directory; the live batches ran the elevated path and read the count as zero; ea2ccbe1 the records state the container WFP filters were not read
R3-5-launch-refusal-wording-misses-the-pattern-and-blind-reasons-omit-text | FIXED | 32112e95 MXC own policy_validation error code counts and the launch stderr is in the blind reasons
R3-6-reach-landing-in-next-runs-listener-is-blind-not-fail | REJECTED | It needs a prior run whose container outlived a three hundred second launcher timeout, and that run is itself blind by the timeout rule; the later marker blinds the next run, which is the fail-closed direction, and the raw record keeps the line. Making it a FAIL would label a stale marker as a fresh reach.
R3-7-arm-commit-residuals | FIXED | 32112e95 commits must be 40 hex and equal the known-build entry, arm A records release tag v1.0.0, the table holds the full B0 commit
R3-8-prose-that-outlived-its-code | FIXED | 32112e95 precedence in the docstring, launch-window wording, NOT MEASURED lists and the elevation reason corrected
R3-9-runs-one-batch-verdict-disagrees-between-harness-and-summariser | FIXED | 32112e95 the standalone summariser reads runs_per_arm from the header and flags a batch below the specification count
R3-esc-b4i-routing-and-arm-order-carried | REJECTED | Same decision as R2-3: the stop on any direct reach is the Lead Architect rule, arms can be started separately, and the question is moot for these batches because both ended in HOLD.
R3-tok-token-privileges-of-the-elevated-launcher | FIXED | 32112e95 the batch header records whoami /priv of the launching process
P-1-launcher-logged-psec-version-omitted-high | FIXED | ea2ccbe1 the perf JSON, log entry and fragment state that all twelve launches logged PSEC 1.1 and the 2026-10-11 launches logged PSEC 1.0, that --probe prints no PSEC field, and add the PSEC 1.0-only path to not measured; the evidence README carries the same (evidence repository commit named above)
P-2-lock-marker-scopes-over-older-entries | DEFERRED | #1795 blocked-by: scripts/research_tracker_lock.py entry boundary uses the entry's own heading level (feat/research-preflight)
P-3-preflight-runs-once-at-batch-start | FIXED | 16caf3af the pre-flight runs before every run, a held port records ABORTED-PORT-HELD naming the pid and stops the batch; ea2ccbe1 the records say the real control is not running the self-test beside a live run
P-4-evidence-leak-gate-blind-to-private-ipv4 | DEFERRED | #1794 blocked-by: evidence repo tools/leak_gate.py private-IPv4 rule
P-5-public-mirror-already-publishes-the-lan-address | DEFERRED | #1794 blocked-by: #1794
P-6-causation-overstated-in-fragment-and-log | FIXED | ea2ccbe1 fragment and log say the cause of the changed acceptance is not isolated (build, harness and proxy port changed, security software ruled out), matching the README
P-7-no-disposition-record-for-the-review-rounds | FIXED | feat/mxc-proxy-egress this record and the four review files, verified by scripts/verify_disposition.py
P-8-operator-only-facts-read-as-recorded | FIXED | ea2ccbe1 Defender real-time protection and the service name marked per the operator in the log entry; the evidence README the same
P-9-internal-folder-name-number-in-the-perf-json | FIXED | ea2ccbe1 the perf JSON no longer carries the number inside the toolchain and MXC folder names
P-10-winerror-10048-not-in-raw | FIXED | ea2ccbe1 marked as from the console output the operator pasted in the perf JSON, log entry, fragment and the evidence README
P-11-bitdefender-process-count-changed-between-attempts | FIXED | ea2ccbe1 seventeen processes at the aborted attempt against fourteen during the batch noted in the perf JSON and log entry; the evidence README the same
P-12-mxc-enforcement-mode-line-omitted | FIXED | ea2ccbe1 the records state enforcement mode capabilities and zero firewall rules created as observed in the launcher logs, and that the container WFP filters were not read
P-13-selftest-binds-live-ports-but-docs-say-it-changes-nothing | FIXED | ea2ccbe1 the performance log entry and fragment name the clash; the evidence repository probe index and bundle README now say never to run it beside a live run (evidence repository commit named above)
P-14-status-notes-use-approximate-times | REJECTED | The status file is a raw working note kept outside every repository, read only and never published, and the published records already use the raw timestamps; the bundle README now says the notes give approximate times, which is all the finding asks for.
P-15-policy-hash-may-confirm-a-guessed-account-name | DEFERRED | #1796 blocked-by: #1796
```

## Reading the table

- Every FIXED row names a commit; rows whose fix is in the evidence repository name the BlarAI commit that carries the matching record and point to the evidence repository commits listed above.
- The three DEFERRED rows with `blocked-by` predicates are all outside this branch: #1795 is closed when `python scripts/research_tracker_lock.py --check` run against this branch reports nothing on `PERFORMANCE_LOG.md` outside the marked entry; #1794 when the evidence repository gate flags a private IPv4 address in a fixture file and the public mirror's address is dealt with; #1796 when the policy-hash question is answered or the field is blanked.
- The post-run review's checklist items 6 (disposition record) and 3 (the lock) are rows P-7 and P-2.
- Self-tests written and not run in the fixing commits: the pre-flight check on an ephemeral port (`7a350732`) and the port-held-between-runs case (`16caf3af`). The first was exercised by hand; the second awaits a quiet machine.
