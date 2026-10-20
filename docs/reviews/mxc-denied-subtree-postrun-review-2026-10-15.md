# MXC denied subtree: post-run review and pre-push confirmation (2026-10-15)

Independent adversarial reviewer; built none of it. Report only, no fixes made.

**Verdict: PASS** (pre-push for the evidence bundle). No finding changes the HOLD, any measured figure, or the sanitised bundle's
safety. Two MEDIUM record-wording findings (register) and one MEDIUM machine-readable absence-as-value (BlarAI performance JSON)
should be fixed before the register text is used in a post or the JSON is uploaded; none of them is in the evidence bundle.

## Anchors

- Raw: `blarai-research-data/mxc-denied-subtree/run-20261015-2/` (11 files) and `run-20261015-1/` (5 files), read only.
- Harness reviewed at `b1cb40e3` via `git show` (the worktree HEAD has since moved to `261737de`, which commits the fx-c variant
  on top of the records commit `4b92aa8a`; the fx-c code was not reviewed).
- Records: BlarAI `feat/mxc-denied-subtree` at `4b92aa8a` (unchanged at `261737de`).
- Evidence repo `feat/mxc-denied-subtree` at `2d2fca41f92b9cc9d36bb89396f38a10e7de3c39`, working tree clean.
- Register §5 "#2125 case 2" (line 141) and, because it cites case 2, "#2125 case 1" (line 140); spec CASE_2 v1.

## Pre-push conditions

| | Condition | Answer | Evidence |
|---|---|---|---|
| a | HOLD or plain refusal, never FAIL | **YES (HOLD)** | `summary.json` verdict HOLD, `changes` [], `blind_reasons` []; re-derived independently below |
| b | raw-first rule | **N/A** | applies to case 3 only |
| c | re-count sanitised vs raw matches | **YES** | own script: 11/11 files, identical JSON structure, 749 non-string leaves compared, 0 differences; every sha256 list identical; PSEC strings identical; bare numbers identical except the three disclosed rewrites (launcher time 1686 to 1,686 twice, Bitdefender version to "30.0.33 build 162"), all named in PROVENANCE |

## HOLD re-derived from raw (own script, not the summariser)

- S0: both launchers `--probe` tier `base-container`, `needsDaclAugmentation` false, `baseContainerSupportsDenyPaths` true;
  `dry_run_selected_tier` base-container 3/3; launcher log `selected isolation tier: base-container` 3/3.
- S1: `s1_host` create/append true in 3/3; payload ok, winerror null.
- S2: payload `s2` ok false, winerror 5 for all five attempts in each run = 15/15; judge `landed_count` 0, `disagreements` [],
  `read_errors` []; snapshot entries for `sub` and `sub/*` identical before/after in every run (the only changed paths are in T:
  `_report.json`, `go.flag`, `ready.flag`, `marker.txt`, `s1_new.txt`); tree errors [] both sides.
- S3: read_marker and list_sub ok false, winerror 5, 3/3.
- S4: 5/5 landed, 6 sub changes, unconfined read and listing ok.
- Smoke: 5/5 steps ok.
- ACL: `T\sub` and `T` captured before, during (`process_running_at_capture` true, `go_written` true, during_at inside each run
  window) and after; 5 ACEs, all type A, deny 0 in all 18 captures; SDDL identical across the three captures.
- MXC state: `state_changed_by_run` {} 3/3; header start == end (218 AppContainer keys; ProcessSandbox key `<absent>` both;
  dacl-restore dir empty both). Toolchain ACL unchanged 3/3.
- Policy as logged by the launcher: `denied_paths` [T\sub], `fallback.allow_dacl_mutation` resolved **true**, tier base-container,
  `PSEC 1.0, 312 bytes` in all 4 logs.
- Run 1 (non-result): ui `{"disable": true}`, exit 1, `_ctypes` DLL init failure, `attempts_executed` false, sub unchanged.

## Findings (most severe first)

1. **MEDIUM** (register line 140, case-1 entry, cites case 2) — "the logged PSEC version follows the policy, not the host: on the
   same host on 10-15 the three case-2 launches, a different policy, logged PSEC 1.0" is contradicted by the same entry (the
   proxy policy logged PSEC 1.0 on 26200.9457 under main `70fc7d52` and 1.1 on 26200.9711), and the case-2 count is 4 launches,
   not 3. Cost: the case-1 lesson inverted, a causal claim from two policies on one host. Reproduced: four `PSEC 1.0, 312 bytes`
   lines in `mxc-{fx-a-r1,r2,r3,smoke-r1}.log`. Fix text: "(the logged PSEC version is a per-launch reading: on 10-15 on the same
   host the four case-2 launches, a different policy, logged PSEC 1.0, and on 10-11 on 26200.9457 the same proxy policy shape
   logged PSEC 1.0 under a different main build; which of policy, launcher build or Windows build sets it is not isolated)".
2. **MEDIUM** (register line 141) — "consistent with MXC's documentation of Tier 1 native enforcement when PSEC advertises deny
   support" says PSEC advertised deny support; `PSE_SUPPORT_FS_DENY` was never read, the evidence is the launcher's derived flag
   `baseContainerSupportsDenyPaths`, source-checked for the main build only, and the BlarAI record says the vendor document was
   not re-read for this record. Fix text: "(consistent with MXC's documentation of Tier 1 as native enforcement with no host
   filesystem change; the launcher's `baseContainerSupportsDenyPaths` flag was true, and PSEC's own `PSE_SUPPORT_FS_DENY` bit
   was not read)".
3. **MEDIUM** (BlarAI `docs/performance/mxc_denied_subtree_2026-10-15.json`, `machine.mxc_state.process_sandboxes` [1, 1]) —
   the raw value is `["<absent>"]` at start and end; the count of the sentinel list is published as one sandbox key present.
   Absence rendered as a value; affects the dataset, not the bundle. Fix: `"process_sandboxes_key": ["<absent>", "<absent>"]`.
4. **LOW** (register line 141) — "(both v1.0.0 and the main build `525d0f25`)" states the second launcher's commit as fact; this
   batch's header records no commit, the attribution is by equal sha256 to the case-1 record. Fix text: "(both v1.0.0 and a main
   build whose sha256 equals case 1's `525d0f25` build)".
5. **LOW** (register line 141) — "UI lockdown off (with it on, Python's ctypes failed to load inside the container: ...)" reads
   causal; the records say the UI setting is the recorded difference, not an isolated cause. Fix text: "UI lockdown off (the
   first attempt, with it on, stopped when the container's Python could not load ctypes; the harness also changed between the
   attempts, so the cause is not isolated)".
6. **LOW** (register line 141) — STATUS "post-run review, sanitised bundle and publication still to run" is stale (bundle exists
   at `2d2fca4`; this review done); "Blair launching from an elevated console" is operator-only (raw records elevation, not who
   launched). Fix text: "Blair launching (per Blair) from an elevated console (elevation recorded true at start and end)"; update
   STATUS at push.
7. **LOW** (`PERFORMANCE_LOG.md` entry, plain summary) — "the sandbox chose its first tier, the one where Windows itself
   enforces the deny" states the mechanism as fact; the same entry's Not-measured says no kernel-level evidence was taken. Fix
   text: "the sandbox chose its first tier, the one the vendor documents as enforced natively by Windows".
8. **LOW** (evidence `README.md` Results table, row "run verdict | HOLD | HOLD | HOLD") — the raw holds no per-run verdict; the
   summariser emits only a batch verdict. Fix: delete the row (the batch verdict line below already states HOLD), or label it
   "no change and all checks clean (derived; the harness has a batch verdict only)".
9. **LOW** (harness `summarise.py` at `b1cb40e3`, `"ui_lockdown": False`) — a constant, not read from the records; true here,
   but it would read "false" for a batch run with lockdown on. No effect on this batch. Fix: derive from each record's
   `config.ui`.
10. **LOW** (all records) — `fallback.allowDaclMutation` is described as "absent (the launcher's default)" without the value; the
    launcher's own log shows it resolved to `true`. Fix text: append "(resolved `true` in the launcher's log)".

## Sanitisation

- `python tools/leak_gate.py --tracked`: 218 files, 0 hits. `--tree evidence/2026-10-15-mxc-denied-subtree`: 13 files, 0 hits.
  `--tree tools/probes/mxc-denied-subtree`: 9 files, 0 hits.
- Own grep over bundle, probe copy and PROVENANCE (account, host name, `S-1-5-21` raw domains, `S-1-15-2` raw RIDs, home paths,
  private IPv4, MAC, GUID, `#NNN` tracker refs, internal number, case/issue numbers, campaign words): 0 hits. SIDs appear only as
  `S-1-5-21-X-X-X-<RID>` and `S-1-15-2-X<n>`; the probe copy's only `S-1-15-2` value is the self-test's synthetic SID.
- Probe copy sha256 of all eight files equals the approved list in the performance JSON.
- `C:\mxc-fx` is published as `~\mxc-fx`: the spec asks for that mapping and the README says so; noted, not a finding.
- BlarAI worktree at `261737de`: `scrub_public_identifiers.py --check` 0 findings (4105 files); `research_tracker_lock.py --check
  --reference-ref main` ok, 0 findings; `verify_disposition.py` PASS 35/35.

## Attacked and could not break

- HOLD leniency: the summariser blocks HOLD on any sub change, any landed attempt, any report/host disagreement, any non-5 code,
  missing S1, missing or partial S4, absent smoke, tier mismatch, deny ACE left behind or MXC state change; all clean in raw.
- "During" ACL capture timing: taken while the container process was running, after the go signal, for `T\sub` and `T`.
- PSEC as a host property: the case-2 records (performance log, JSON, journal, README) state it per launch only.
- Not measured states Tier 2/3 not exercised in every record and the register.
- Non-result run 1: not sanitised or copied, described identically in every record, figures match raw (started 16:16:45.616).
- Figures in the performance log, JSON, journal, README, PROVENANCE: all checked against raw (counts, codes, totalDenials 9,
  wall times 2.744/2.648/2.649 s, 218 keys, privileges, security suite, timestamps, distinct containerIds); none wrong.

## Not done

No pytest, no self-test, no launch. The fx-c variant at `261737de` was not reviewed. `captureDenials` output files (outside the
raw folder) were not read, so the 9-vs-7 denial count remains unreconciled, as the records say.
