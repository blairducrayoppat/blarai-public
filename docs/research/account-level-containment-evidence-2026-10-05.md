# Account-level containment on Windows 11: the evidence and its limits (2026-10-05)

Status: evidence record, not a proof and not a decision. Author: a Claude session for the Lead Architect (LA). Nothing in
BlarAI's runtime changes because of this document. Every raw-data file cited is in `docs/research/containment-evidence-2026-10-05/`.

## 1. Outcome in plain language

On this one laptop, in these runs, an outbound IPv4 TCP port 443 connect from a dedicated low-privilege account failed
while a raw Windows Filtering Platform (WFP, the packet-filter layer inside Windows) block keyed to that account stood
(windows of at most about 5 s in three runs and about 127 s in one, in a dynamic session that vanishes when the operator's
script exits). It failed even though Bitdefender owns the firewall on this machine and had made the ordinary Windows
Firewall rule do nothing. Separately, a throwaway account was denied all 8 tested reads of the operator's secret folders and
all 4 specified outside-write targets, but it DID write to two other targets, `C:\Windows\Temp` and `B:\models` (#1692), and
it could run an AI model on the Intel Arc 140V graphics chip while another account (the operator) made a
loopback request to it. In that run the confined account was the listener, so the loopback permit filter was never
exercised. What it does not show is in section 6. The largest gaps: the direction a product needs (the confined account
calling a model server over loopback while blocked) was tested only against a stub listener and with no run lacking the
permit; no reboot test; no speed comparison; no test of the real 14B-model pipeline; and the account that runs the coder
today can still write to the operator's `projects` folder (#1678), so the file claim is contradicted for it. The negative
results in section 4 show why file-level and text-level controls keep being bypassed, which is why account-level controls
were tried.

## 2. Claims table

Status words: OBSERVED n of n (the stated check was run n times and passed n), STATIC (read from a listing or code, not
exercised), NOT ESTABLISHED (not measured, or measured and not shown), CONTRADICTED (the data shows the opposite). Paths are repository-relative.

| Claim | Evidence | Conditions observed under | What was NOT tested | Status | Raw data path | Reproduction command |
|---|---|---|---|---|---|---|
| C1 A raw WFP BLOCK filter keyed to the dedicated account `blarai-coder` is enforced while Bitdefender owns filtering | Per run: operator baseline 6 of 6 connects OK (1.1.1.1:443, 8.8.8.8:443); coder baseline `outbound_blocked=False` (egress open); 4 filters added in one transaction; coder `outbound_blocked=True`, `sid_is_coder=True`, operator watchdog 3 of 3 OK; after engine close the objects are gone AND coder egress is open again (so the block is attributable to the filters). `outbound_blocked` is true when the connect does not complete in 5000 ms or throws: ANY failure counts, defined in agentic-setup `coder-containment-probe.ps1` (in its scripts folder; not bundled). `secret_reads_denied: true` in these files is vacuous (empty path list). Exit 0 each run. Vikunja #1671 c.3873, corrected by c.3891 and c.3894 | One machine, Windows 11 Pro 10.0.26200, elevated Windows PowerShell 5.1, Bitdefender processes bdagent/bdntwrk/bdredline/bdservicehost/bduserhost running, firewall profiles on, BFE and mpssvc running; dynamic WFP session; filters stood AT MOST about 5.1 to 5.4 s (filters-added to the post-removal result read; engine close is not timestamped); the during-block result was read about 3.2 s after the filters were added (a read time, not the probe time); each reading is one TCP connect | Reboot persistence (filters were dynamic by design); IPv6 destinations (v6 filters were added, never probed); UDP, DNS, ports other than 443; Bitdefender update or restart during a block; other antivirus; a real coder dispatch under the block; any hold longer than about 5 s; the filters are fail-open on the operator script's exit (dynamic session) | OBSERVED 3 of 3 | `docs/research/containment-evidence-2026-10-05/wfp-spike/result-20261004-235941.json`, `docs/research/containment-evidence-2026-10-05/wfp-spike/result-20261005-000002.json`, `docs/research/containment-evidence-2026-10-05/wfp-spike/result-20261005-000028.json`, `docs/research/containment-evidence-2026-10-05/wfp-spike/live-run-console.txt` | elevated: `.\wfp-coder-egress-spike.ps1 -Live -HoldSeconds 100` (needs the account, the task and agentic-setup helpers; see `docs/research/containment-evidence-2026-10-05/README.md`) |
| C1b While the block stood, a loopback connect made BY the account to a stub listener succeeded (the account as client; not shown to be caused by the permit filter) | `loopback_ok=True` during the block in all three runs: HTTP 200 from `127.0.0.1:8000/v3/models`, connect made by the coder-account probe; all four filters are outbound-connect only (ALE_AUTH_CONNECT V4/V6) | The listener was a stub started by the operator script (`loopback_stub_started=true`), not the real model server (c.3891). No run lacked the permit filter, so the permit may simply be unused (the spike README says so) | A run without the permit (the arm that would show it matters); the real model server in this direction; sustained or streamed traffic | OBSERVED 3 of 3 (stub listener); the permit's role NOT ESTABLISHED | `docs/research/containment-evidence-2026-10-05/wfp-spike/result-20261004-235941.json` (`steps.coder_during`), `docs/research/containment-evidence-2026-10-05/wfp-spike/README.md` (Interop risks) | same as C1 |
| C2a A dedicated account cannot read the operator's secret paths | July: `verify-coder-containment.ps1` check 2, `blarai-coder` denied on the secret paths, PASS (Vikunja #775 c.1654, 2026-07-10). 2026-10-05 pre-flight: `.ssh`, `.git-credentials`, `AppData\Local\BlarAI`, `.aws`, `.azure` carry no allow entry for the coder (denial by absence of an allow, no deny entry). Spike account `blarai-spike`: 8 of 8 reads denied (operator profile, `.ssh`, `.git-credentials`, BlarAI folder, research data) | July: one run (n=1), raw output only on the ticket, not in this repo. Pre-flight read-only, shell not elevated. Spike: Test A run 2 and Test B pass; Test A run 1 reported "not denied" because the probe read PowerShell's wrapper exception type (probe bug, found and fixed, c.3896); in that run the message text of 7 of 8 reads already said access denied | An account with extra group membership; an elevated or administrator-level process; a handle opened before the ACL existed; a service started under the account | OBSERVED 1 of 1 (July, ticket only) and 2 of 2 (spike, after probe fix); STATIC (ACL listing) | `docs/research/containment-evidence-2026-10-05/preflight/775-preflight-2026-10-05.md`, `docs/research/containment-evidence-2026-10-05/confined-model-spike/runs/testA-20261005-155954.json`, `docs/research/containment-evidence-2026-10-05/confined-model-spike/runs/testB-20261005-160210.json`, `docs/research/containment-evidence-2026-10-05/confined-model-spike/runs/testA-20261005-155840.json` (the failed first run, kept) | spike: `Run-Spike-AsAdmin.cmd` then `spike-wfp.ps1 -TestA`; coder: `verify-coder-containment.ps1 -AcceptedEgressGap` (agentic-setup, not bundled) |
| C2b The throwaway account was denied the 4 specified outside-write targets (System32, operator profile root, its own `bin`, drive root) but could write `C:\Windows\Temp` and `B:\models`; it is NOT shown unable to write outside its own folders | Spike account: 4 of 4 specified outside writes denied in each of 2 runs; positive controls (its `work` folder, its config, model config read) allowed; writes to `C:\Windows\Temp` and `B:\models` allowed | Spike account only. Informational writes ALLOWED: `C:\Windows\Temp` and `B:\models` (see C6f) | The real `blarai-coder` account: it holds Modify on all of the operator's `projects` folder (#1678) and `C:\blarai-fleet` is Modify for Authenticated Users (pre-flight), so for the coder this claim is FALSE today | OBSERVED 2 of 2 for the 4 specified targets (spike account); CONTRADICTED as a general claim (two writable targets) and for `blarai-coder` today | `docs/research/containment-evidence-2026-10-05/confined-model-spike/runs/testA-20261005-155954.json`, `docs/research/containment-evidence-2026-10-05/confined-model-spike/runs/testB-20261005-160210.json`, `docs/research/containment-evidence-2026-10-05/preflight/775-preflight-2026-10-05.md` | as C2a |
| C3a A restricted, non-interactive, non-elevated batch account can load a model on the Arc 140V iGPU through OpenVINO GenAI | Token check: spike SID, not admin, session 0, not interactive, medium integrity. Qwen3.5-4B-int8 loaded on device GPU and generated 64 tokens twice per run; load 24.8 s, 17.2 s, 33.7 s | 3 runs, 2026-10-05; OpenVINO 2026.4.0, GenAI 2026.4.0.0-3407, Python 3.11.9; one GPU driver (32.0.101.8831, from Vikunja #1689 c.3896, not recorded in the run files); free RAM about 19.5 GB; builders also loading the CPU, thermal state not recorded | Other drivers; the 14B INT4 plus draft pipeline; MTP, prefix cache, speculative decoding; any prompt other than one short question; speed (C6a) | OBSERVED 3 of 3 | `docs/research/containment-evidence-2026-10-05/confined-model-spike/runs/testA-20261005-155840.json`, `docs/research/containment-evidence-2026-10-05/confined-model-spike/runs/testA-20261005-155954.json`, `docs/research/containment-evidence-2026-10-05/confined-model-spike/runs/testB-20261005-160210.json` | `spike-wfp.ps1 -TestA` (needs an OpenVINO venv and model; edit paths in `spike-lib.ps1`) |
| C3b While the block stood, the confined account acting as the LISTENER served a model completion to the operator, and the account's own outbound connect to 1.1.1.1:443 failed | Test B: the operator connected to `127.0.0.1:49580` and got HTTP 200, `model_loaded=true`, 32 tokens, about 7.7 s; the account's own probe to 1.1.1.1:443 failed with WinError 10013 inside the task and mid-hold; operator watchdog 94 of 94 connects OK; removal verified, operator connect OK after. The account's egress being open WITHOUT the filters comes from the earlier Test A runs (connected at 15:58 and 15:59), not from an arm inside Test B | n=1 run. Filters stood about 127 s. Bitdefender running (interplay not isolated). Because the filters are outbound-connect only, the inbound loopback flow never passed through them: this does NOT test the permit filter | The account as CLIENT of a real model server over loopback while blocked; a run without the permit; repeat runs; streaming; concurrent clients; listener restarts | OBSERVED 1 of 1 (as listener); the client direction NOT ESTABLISHED | `docs/research/containment-evidence-2026-10-05/confined-model-spike/runs/testB-20261005-160210.json`, `docs/research/containment-evidence-2026-10-05/confined-model-spike/runs/testA-20261005-155954.json` (the open-egress control) | `spike-wfp.ps1 -TestB -BlockMaxSeconds 420 -ServeHoldSeconds 60` |
| C4 File-level and text-level controls are bypassable (negative results kept, section 4) | Reviews: fused coder leg rounds 1 to 3 (forged result, junction swap after the check, check-then-use residual, ACL gate holes) and the #1690 text guard (24+ bypasses over four rounds, ADR-043) | Reproduced in temp sandboxes with doubles; the real coder task, accounts and ACLs were not touched; two findings are reasoned, not raced (section 4) | The real coder account running the real task; a wildcard-path finding (not traceable in the review files, so not claimed) | OBSERVED (individual findings reproduced; see section 4) | `docs/research/containment-evidence-2026-10-05/reviews/code-review-775-fused-leg-2026-10-05.md`, `docs/research/containment-evidence-2026-10-05/reviews/code-review-1690-rules-tooling-2026-10-05.md`, `docs/adrs/ADR-043-Commit-Protection-Layers.md` | read the reports; the probe scripts lived in the reviewers' scratchpads and are not bundled |
| C5 The coder-egress gap was accepted on 2026-07-10; the new evidence shows it is closable but does not close it | c.1653: Bitdefender owns filtering, the Windows Firewall per-SID block is inert (bisect-proven), the LA accepted the gap with named re-visit triggers. Today the rule is still present and inert (pre-flight) and every WFP coder baseline shows `outbound_blocked=False` | Gap documented-not-enforced; the `-AcceptedEgressGap` mode turns verify check 1 into a warning | A persistent, fail-closed filter set (#1682, not built); the fused coder leg is not flipped (`containment=off`); whether the LA reopens the gap (c.3893: #1671 is evidence, not a trigger he named) | STATIC (history); gap closed: NOT ESTABLISHED | `docs/research/containment-evidence-2026-10-05/preflight/775-preflight-2026-10-05.md`, `docs/research/containment-evidence-2026-10-05/wfp-spike/result-20261004-235941.json` (`steps.coder_baseline`) | read Vikunja #775 c.1653 and c.3893 |
| C6a Speed of the confined server matches an unconfined one | Confined account 3.7 to 8.5 tok/s (`tok_per_s_tpot`, output tokens per decode time; by wall clock `tok_per_s_wall` 3.66 to 7.73) across 3 runs (6 generations); operator in-process control 4.5 to 4.8 tok/s (`tok_per_s_tpot`; wall 3.89 to 4.49), run later | Not cold-gated, builders loading the CPU, thermal state unrecorded; the spread inside the confined account alone is about 2.3x | Any ratio. Needs the repo's cold-GPU gate (thermal zone at or below 72 C per generation) | NOT ESTABLISHED | `docs/research/containment-evidence-2026-10-05/confined-model-spike/runs/control/control-inproc.json`, `docs/research/containment-evidence-2026-10-05/confined-model-spike/runs/testA-20261005-155954.json` | none yet; a cold-gated A/B is required |
| C6b Persistent WFP filters survive a reboot and fail closed | Not tested; the spikes used dynamic sessions that vanish on exit | n/a | Persistent provider and filters, boot ordering against BFE, fail-closed on absence | NOT ESTABLISHED | none (not tested); design only in `docs/research/containment-evidence-2026-10-05/wfp-spike/README.md` | none yet (#1682) |
| C6c The block covers IPv6, UDP, DNS and other ports | Not tested (v6 block filters were installed but never probed) | n/a | All of them | NOT ESTABLISHED | `docs/research/containment-evidence-2026-10-05/wfp-spike/wfp-coder-egress-spike.ps1` (filter definitions only) | none yet |
| C6d Other antivirus products and other GPU drivers | Not tested: one antivirus (Bitdefender), one driver (32.0.101.8831) | n/a | A Defender-only machine; other Intel or non-Intel drivers | NOT ESTABLISHED | none (not tested) | none yet |
| C6e The 14B plus draft pipeline, MTP and streaming work in the confined account | Not tested: only the 4B INT8, one prompt, 64 tokens | n/a | About 17 GB In-Use for the 14B; streaming | NOT ESTABLISHED | none (not tested) | none yet |
| C6f Model weights cannot be altered by the confined account | Contradicted for the research models: `B:\models` inherits Authenticated Users: Modify and the spike account wrote there (#1692) | Spike account, `B:\models` only; the production model tree was not surveyed | The production tree's ACL; signed manifests cover production loads only | CONTRADICTED | `docs/research/containment-evidence-2026-10-05/confined-model-spike/runs/testA-20261005-155954.json` (`informational_writes`) | none yet (#1692) |
| C6g The permit filter is what allows loopback under the block, and the confined account can call a real model server over loopback while blocked | Not tested: no run without the permit; the client direction was exercised only against a stub (C1b); in Test B the account was the listener (C3b) | n/a | A permit-off arm; the confined account as client of OVMS or a GenAI server | NOT ESTABLISHED | none (not tested); stub only in `docs/research/containment-evidence-2026-10-05/wfp-spike/result-20261004-235941.json` | none yet |

## 3. What the numbers rest on

- C1 per run: baseline 6 of 6 operator connects, 3 watchdog checks and 2 operator-during connects all OK, coder blocked,
  removal verified (`steps.removal_engine_check`: provider, sublayer and filters absent) and coder egress open again after.
  The three result files differ in clock fields, uptime (18.94 h, 18.95 h, 18.96 h), every connect latency and the filter
  ids (407213-16, 407217-20, 407221-24). Three runs inside about 57 seconds (23:59:31.0 to 00:00:28.3) on one machine are a
  repeat, not independent replications.
- Source disagreement: the result files record `hold_seconds: 100` (the requested cap); the filters actually stood about 5
  s at most (timestamps give 5.13, 5.35 and 5.13 s from filters-added to the post-removal read; engine close is not
  timestamped), as Vikunja #1671 c.3891 states. Read the timestamps, not the cap; both durations in this document are
  upper bounds.
- C3: the runs differ: Test A run 1 loaded in 24.8 s, run 2 in 17.2 s, Test B in 33.7 s. Vikunja #1689 c.3896 quotes 7.8
  to 8.5 tok/s, which is Test A run 2 only; the full range is 3.7 to 8.5 tok/s.
- The confined-model scripts were CHANGED AFTER the runs (hardening, about 16:44 to 16:50; the runs were 15:57 to 16:03). The results
  come from the as-run versions in `docs/research/containment-evidence-2026-10-05/confined-model-spike/as-run/` (SHA-256 in `docs/research/containment-evidence-2026-10-05/confined-model-spike/as-run/MANIFEST.sha256`),
  recovered from the first bundle commit with the fabricated test SIDs restored; the current versions are in `post-run-hardened/`. The
  line changes between them are generated in `docs/research/containment-evidence-2026-10-05/CHANGES.md`. Test A run 1 (15:57:30) ran an even earlier
  `spike-run-test.ps1` (before the inner-exception classifier fix) that no longer exists; run 2 (15:59:14) and Test B ran the bundled one.
  All six scripts' `-SelfTest` pass for both sets in PowerShell 7 and 5.1.
- Corrections that apply: #1671 c.3873 called the result a re-visit trigger on #775; c.3893 and c.3894 retract that. The
  loopback in C1b is a stub and the permit's role was not tested. #1689 c.3896 says the control ran "at the same time";
  in the raw data it started at 16:02:18.9, after Test B finished at 16:02:10.7 (corrected on the ticket in
  comment 3897). "Enforces" means the observed result of these runs, not general enforcement.

## 4. Negative and adversarial results (kept visible)

Fused coder leg (`docs/research/containment-evidence-2026-10-05/reviews/code-review-775-fused-leg-2026-10-05.md`; tracked
as Vikunja #1691). Every probe ran against temp roots with doubles; none touched the real account, task, ACLs or firewall.

- Forged result (round 1, L1, reproduced): the check that the coder's SID matches compared a field the result file wrote
  about itself. A third party wrote a result carrying the coder's SID and the dispatch accepted it (`ACCEPTED result:
  ExitCode=0`). Looser variants (wrong job id, `ok` as the string "false") were accepted too. Round 2 reports it fixed by
  binding the result to id, kind, boolean `ok`, file owner and creation time, and could not break it.
- Check-then-use swap (round 2, M1, reproduced): the workdir was link-checked once before the coder ran; the coder, which
  can delete and recreate its folder, swapped it for a junction to another repository and the operator-side
  `git add -A` staged a file in that other repository. Round 3 (6905e03) reports M1 fixed for check-time and pre-call swaps.
- Residual (round 3, N1, reproduced in a temp sandbox): verify, swap the worktree for a junction, then run the hardened
  git command: the victim's file landed in the agent worktree's index (the victim repository was untouched). A 35 s random
  race gave 31 calls passed and 391 refused, no leak. This blocks the flip. Whether a coder-owned process can outlive the
  task is a hypothesis; the real task was not run.
- ACL gate holes (M3, reproduced): an inherit-only Everyone full-control entry passed the gate; owners and the parent
  folder were not checked. Round 3 reports it fixed.
- Hard links and link-following deletes (M2): the round-3 review reports M2 FIXED (a held-handle read; exclusive prompt creation); the part it did not race is the junction under `prompts\` or `logs\`. Reasoned bounds, NOT raced: a hard link to a secret needs a handle the
  secret's ACL denies; a link-following delete needs a junction swap after the check. The reviewer rates both low.
- Lock gaps: three mutants survived the lint (N2) and two fingerprint-coverage mutants survived (N3) in round 3.
- Issue found in review of our own spike scripts (same check-then-use and link class, found by an automated review after the
  spike ran): `spike-cleanup.ps1`, run elevated by the operator, deleted `C:\blarai-spike` and the account's profile with
  `Remove-Item -Recurse`, trees the account could write, so a planted junction, symlink or hard link there could have made the
  operator delete data behind it. The same review class covered wildcard and link targets for `icacls`, `secedit` files left in
  `%TEMP%` (which carries a foreign write entry on this machine), and the operator parsing result files the account wrote.
  Fixed in commit `e87c4b71`: a no-follow delete that removes links as links and refuses hard links to outside names,
  guarded `icacls` targets, a private temp directory, a strict reader (no link, size cap, integer loopback port) and a
  self-test that fails if a script puts the password on a command line (the password already went only to
  `Register-ScheduledTask -Password`, never a process command line, printed or logged). Self-tests drive real junctions, hard
  links and symlinks; run under Windows PowerShell 5.1 and 7. Mutation check: a delete that enters links and a delete without
  the hard-link refusal both fail the self-test. Measured limit: on this build (5.1.26100.9444) plain
  `Remove-Item -Recurse` did NOT follow the junction in the test, so that form is not caught by the self-test; the lock covers
  the no-follow behaviour, not a claim about older builds. The leftover spike profile folder holds real system junctions
  (`-DryRun` lists them as links that would be removed as links). Not run live: the fixed cleanup has not been applied to the
  real leftover profile.

Text guard (`docs/research/containment-evidence-2026-10-05/reviews/code-review-1690-rules-tooling-2026-10-05.md`, a copy from the unmerged branch `feat/1690-install-hardening` at `22efaac9`,
`docs/adrs/ADR-043-Commit-Protection-Layers.md`). The guard reads command text; git and the shell read something else.

- Round 1 reproduced forms that passed the guard yet staged or committed: `git add -u`, `--al`, `git stage -A`, `:/*`,
  `GIT_DIR=...` in the environment, `git checkout - && git commit`, `symbolic-ref`, and `merge --no-commit` followed by a
  commit that real git made a single-parent commit on main (N3, N4, P1, P2).
- ADR-043 records the result: over four review rounds a reviewer and a seeded fuzzer (4000+ variants) found 24+ ways
  around the text guard, each fixed and locked; the ADR keeps the guard for staging only and moves control of commits on
  main into git itself. The reviewer's seed-31337 run (2034 variants) found 0 bypasses, but its oracle judges only blanket
  staging and commit-on-main, so it certifies nothing about the ref-moving routes.

What this shows: controls that read paths, strings or self-reported fields, and must be re-run at the moment of use, leave
a gap an adversary can reach (the swap, the forged field, the alternative spelling). A control the operating system applies
to the account's token (an ACL, a WFP user-id condition) showed no such gap in the cases tried. But the negative results
above were found in the operator-side code around the account, so the account boundary holds only if the operator's own
code never follows the account's links or trusts its files.

## 5. Reproduction and what the bundle holds

`docs/research/containment-evidence-2026-10-05/README.md` gives the run order. The self-tests (`-SelfTest`, `-DryRun`)
change nothing. `-Live` and `-Apply` create accounts, ACLs, a scheduled task and WFP objects: elevated, LA present, cleanup
scripts ready. The WFP script needs agentic-setup helper scripts that are not bundled; the confined-model scripts need an
OpenVINO GenAI 2026.4 venv and a model directory whose paths are set in `spike-lib.ps1`. The confined-model scripts come in two sets (as-run and post-run-hardened, section 3). Result files are sanitised (see `docs/research/containment-evidence-2026-10-05/CHANGES.md` for the exact per-file changes; user
and machine names, SID domain parts, model text cut to 100 characters); their numbers are unchanged.

## 6. Limits (what this does not establish)

- One machine, one antivirus (Bitdefender), one GPU driver (32.0.101.8831), Windows 11 Pro 10.0.26200, elevated Windows
  PowerShell 5.1, IPv4 TCP connects to 1.1.1.1:443 (and 8.8.8.8:443 for the operator baseline). Nothing else was probed.
- n is 3 for C1 and C3a, 1 for C3b and for the July check. Windows were short: about 5 s (C1) and about 127 s (C3b).
- No reboot, no persistence, no speed ratio, no 14B pipeline, no streaming, no concurrent clients (C6a to C6e). The filters
  existed only in a dynamic session held by the operator's elevated script: when it exits or dies the block is gone (fail-open).
- Untested direction (C6g): the confined account as a client of a real model server over loopback while blocked, and any run
  without the permit filter.
- Account-level confinement of the coder is not in force today (`containment=off`). The `blarai-coder` account still has
  Modify on `projects` (#1678); `C:\blarai-fleet` is writable by every local account (#1686); `B:\models` is writable by
  every local account (#1692).
- The July check 2 raw output exists only on Vikunja #775 c.1654. The earlier Windows Firewall per-SID rule is evidence of
  failure, not of enforcement (c.1653).

## 7. What this does and does not give a product

What the observations are consistent with: Windows (the account's token, an ACL or a WFP user-id condition), not a program
that must cooperate, refused an outbound IPv4 TCP 443 connect from a dedicated account while the filters stood (about 5 s
and 127 s windows, dynamic session), and denied the spike account 8 of 8 tested reads and 4 of 4 specified outside-write targets (while writes to `C:\Windows\Temp` and `B:\models` succeeded, #1692). They do not show
that a product could rely on this: the file result does not hold for the real `blarai-coder` account today (C2b) or for the
model directory (C6f), the filters are not persistent, and the confined-client direction is untested (C6g). It would not give
per-action semantic governance (what the code chooses to do inside its allowed folders and loopback ports), would not
constrain anything outside the account, and an administrator-level or kernel-level adversary is out of scope. An account boundary is a permission layer on a
shared kernel, not a virtual machine: it is not an escape-proof sandbox, and where code may be hostile a VM is the stronger
boundary. That is why the claim here rests on ADR-045 and the design overview, which bound it to one dimension on one
machine, and not on how any other project describes its own approach.

## 8. Relation to ADR-042

`docs/adrs/ADR-042-Runtime-Governance-Venture-Cancelled-Capabilities-Retained.md` records that the cancelled venture rested
on a measured finding: every enforcement seam a third party can reach on Windows is cooperative, and the one
non-cooperative seam tried then (a per-process firewall rule) failed silently under a third-party security product. This
evidence is new for ONE dimension: network egress and file access for a dedicated account, where a raw WFP block was
enforced under that same kind of product and the spike account was denied the 4 specified outside-write targets and 8 secret reads (writes to `C:\Windows\Temp` and `B:\models` succeeded; the real coder account is not confined today). It says nothing about the other dimensions the study measured
(shell commands as opaque strings, hook crash behaviour, agent-runtime hooks). Whether anything reopens is the LA's
decision and is not assumed here; ADR-042 says there is no condition under which the venture resumes by default.
