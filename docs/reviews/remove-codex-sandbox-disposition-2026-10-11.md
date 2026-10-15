# Disposition: removal of the Codex Windows sandbox leftovers (#1743)

Independent reviews of `tools/operator/remove_codex_sandbox.ps1` ran six rounds on branch `feat/1743-remove-codex-sandbox`: the first review with its inventory skeptic (against `59e82de7`), then reviews of `353b91e7`, `62ef99c6`, `ed929e42`, `024c4b1f` and `b607ac44`. Every finding is listed once. Commits cited are on that branch. The row names the round and the finding in the reviewer's own order.

What is not known: the access-entry stage (stage 2) has never been applied to the real machine; its behaviour there is established by fixtures and by a read-only simulation of 410k BlarAI objects, about 212k Temp objects and 3.3k C:\ovms objects, not by a real run.

```disposition
round 1 B1 blocker: a WFP or user-rights export that produced no file skipped its check silently and left the plan digest unchanged | FIXED | 353b91e7 each export must give a recognisable file or the check counts as not run and raises a finding; later predicates and garbage-export cases in b607ac44 and f33873ea
round 1 S1 secedit lists local accounts by name so the SID-only search could not see them | FIXED | 353b91e7 the search covers SIDs, account and group names and the needles
round 1 S2 rewriting a root list drops other principals' stale inherited entries, undisclosed and not undoable | FIXED | 024c4b1f superseded: each object's own list is edited through one handle, nothing is re-derived, every object is recorded and restorable exactly
round 1 S3 PASS certified more than it measured (four root lists only; a cut-short scan passed) | FIXED | 353b91e7 the apply and verify read every object and a cut-short or unreadable scan cannot certify
round 1 S4 no disclosure that running Codex again re-adds entries and accounts | FIXED | 353b91e7 plan text and header say so
round 1 N1 readonly capability SID and account SIDs not scanned | FIXED | 353b91e7 scanned; a hit on a SID the script does not remove refuses before any change
round 1 N2 firewall scope compared by substring | FIXED | 353b91e7 whole-SID comparison, made exact (one allow entry, any principal form) in f33873ea
round 1 N3 undo line for a firewall rule lost RemotePort | FIXED | 353b91e7 RemotePort and LocalPort kept, dangling-account warning added
round 1 N4 launcher window closed on a cancelled UAC prompt and never showed the exit code | FIXED | 353b91e7 catch, pause and -HoldOpen; reworked in 024c4b1f and f33873ea
round 1 N5 the reviewer's own probe function named Rd deleted a tracked file through the built-in alias | REJECTED | not a defect of the branch: the reviewer restored the file; a static test now fails if any function in the script shares a name with a built-in alias (353b91e7)
round 1 skeptic owner O:BA of C:\ovms could make a full-descriptor write fail non-elevated | FIXED | 353b91e7 only the access section is written and the script requires elevation; a fixture with Administrators as owner is applied and its owner checked unchanged
round 1 skeptic C:\ovms permanently stops inheriting | FIXED | 024c4b1f no folder's inheritance setting is changed any more; verified by a self-test case
round 1 skeptic Temp holds live files and may be partly propagated | FIXED | 024c4b1f the final read-back of every object catches a partial result and stops before the irreversible steps
round 2 H1 Temp root loses a non-Codex inherited entry on 195k objects, result PASS | FIXED | 62ef99c6 kept as explicit entries; fully replaced in 024c4b1f by editing each object's own list so nothing is dropped
round 2 H2 final scan could not finish in the default time and ended FAIL after irreversible deletions | FIXED | 62ef99c6 irreversible steps moved after a certifying read-back and a string-level comparison; 024c4b1f measured 114 s against 368 s on 410k objects
round 2 M3 explicit Codex entries below the roots not refused before any change | FIXED | 62ef99c6 refused at the snapshot
round 2 M4 self-test owner probe picked the same owner as the host | FIXED | 62ef99c6 the probe picks a different owner
round 2 M5 static lock certified less than implied (five planted removals passed) | FIXED | 62ef99c6 structural parse; 024c4b1f and b607ac44 planted twins; f33873ea 126 tests with every planted single-line removal caught
round 2 L6 -HoldOpen did not hold on an unhandled error | FIXED | 62ef99c6 try, catch and finally around the whole entry block
round 2 L7 -DryRun parameter was never read | FIXED | 62ef99c6 combining it with another mode is refused
round 2 L8 undo of the C:\ovms inheritance stop was not exact | FIXED | 024c4b1f no inheritance stop exists any more
round 2 L9 unreadable objects were not refused at snapshot time | FIXED | 62ef99c6 refused at the snapshot
round 3 H1 removing the entry from C:\ovms re-inherits from C:\ and gains Authenticated Users Modify on 3290 objects | FIXED | 024c4b1f nothing is re-derived; the ovms-shaped self-test folder keeps its entries and gains none
round 3 M2 the elevated apply trusted preserve and snapshot files that ordinary processes could write | FIXED | 024c4b1f baseline kept in memory, backup folders created SYSTEM and Administrators only with hash-bound snapshots
round 3 M3 the keep-step write followed a junction planted after the snapshot | FIXED | 024c4b1f every write is by handle with the final path, link and hard-link names checked; swapped-in link refused with the outside object untouched
round 3 M4 killing the run and re-running hid the first run's losses | FIXED | 024c4b1f an unfinished earlier apply must be resumed from its own hash-checked snapshot
round 3 L5 static lock missed the new safety logic (8 of 8 mutants survived) | FIXED | 024c4b1f behavioural subset and broken-copy twins in the gate; f33873ea extended
round 3 L6 prose said the keep step leaves access unchanged | FIXED | 024c4b1f header and plan text rewritten to what the code does
round 3 L7 objects missing at read-back never counted; scratch folder swappable | FIXED | 024c4b1f missing objects counted in the report; export scratch folder protected
stage 1 review F1 a lower-case -Stage gave an empty plan and a false PASS | FIXED | b607ac44 any letter case accepted, unknown refused, an empty plan refused for apply and verify
stage 1 review F2 closing PASS lines claimed more than stage 1 did | FIXED | b607ac44 stage-scoped sentences that state what was not examined
stage 1 review F3 the rule scope check ignored shorthand principals and deny entries | FIXED | b607ac44 exactly one allow entry for the pinned SID in any form
stage 1 review F4 failed reads looked like already gone | FIXED | b607ac44 only not found reads as absent; other failures are thrown or raise a not-checked finding
stage 1 review F5 the admin-only scratch folder for exports | FIXED | 024c4b1f created protected in one call, refused if pre-existing or linked
stage 1 review F6 the digest was not bound to the script | FIXED | b607ac44 the plan digest includes the script hash; f33873ea over line-ending-normalised bytes
stage 1 review F7 the static lock missed twelve of thirteen identity-check removals | FIXED | b607ac44 planted twins for each; f33873ea identity checks turned into functions driven by behavioural cases
stage 1 review F9 header and self-test time text | FIXED | b607ac44 and f33873ea
review of b607ac44 M1 a stop at the account steps left CodexSandboxOffline enabled with the loopback block gone | FIXED | f33873ea both accounts are disabled first (reversible, recorded in the undo note), then rules, values, deletions
review of b607ac44 M2 the self-test went red after stage 1 because a check drove the real account | FIXED | f33873ea the check uses a fixture spec in real-mode shape and never names or reads a real object
review of b607ac44 M3 37 of 40 single-line stage 1 disablements stayed green | FIXED | f33873ea every finding class, identity check, step check, verdict and verify report is a behavioural case on states built in memory; 43 reviewer-style mutants all caught
review of b607ac44 M4 the launcher hash handover is checked by the file it protects | FIXED | f33873ea claim reworded; the recommended run path is a protected copy under C:\ProgramData\blarai-operator\run-1743 with the hash printed before and after
review of b607ac44 M5 -RestoreAcl on the real spec was not gated | FIXED | f33873ea refused for the real spec until the access-entry stage is reviewed
review of b607ac44 M6 the script hash changes with the line endings of the checkout | FIXED | f33873ea the hash is over bytes with CRLF turned into LF, in the script, the launcher and the tests
review of b607ac44 L7 other group memberships, tasks by SID or group, services run as the accounts | FIXED | f33873ea three new findings with behavioural cases
review of b607ac44 L8 header prose, mistyped -Stage exit code | FIXED | f33873ea header rewritten; a mistyped -Stage exits 2 and is tested
review of b607ac44 L9 the undo note after a killed run did not name the earlier folders | FIXED | f33873ea every earlier folder of the same plan is named
review of b607ac44 L10 the backup root's parent was writable by the user | FIXED | f33873ea the default root is under the protected C:\ProgramData\blarai-operator
operations: two self-test runs overlapped and deleted each other's fixtures | FIXED | 024c4b1f every object of a run carries a random token and cleanup touches only its own
hard links: 36 model files under BlarAI\models\qwen3-14b\openvino-int4-gpu are hard links to C:\Users\mrbla\blarai-wt-1616-accuracy\models | FIXED | f33873ea LA decision 2026-10-11 (chat): that one folder is allowed for the other names of a hard-linked file, subtree only, every name still has to be inside an allowlisted folder; pinned in Get-RealSpec as LinkRoots (new spec pin), with a toggle test and a look-alike-sibling refusal
stage 2 on the real machine: the apply has only been simulated read-only | DEFERRED | #1743 blocked-by: removal of the acl-stage-blocked lock (Test-Gate 'acl-stage-blocked' in tools/operator/remove_codex_sandbox.ps1) after the LA's go
double-click launcher: the UAC and Enter flow was not run interactively | DEFERRED | #1743 blocked-by: the LA's first double-click run of tools/operator/remove_codex_sandbox.cmd recorded on #1743
huge snapshots, a full disk and paths over 260 characters were not exercised | DEFERRED | #1743 blocked-by: the `Test-Gate 'acl-stage-blocked'` lock removed from tools/operator/remove_codex_sandbox.ps1, since only the access-entry stage writes snapshots
restore on the real machine | DEFERRED | #1743 blocked-by: removal of the restore-real-blocked lock (Test-Gate 'restore-real-blocked' in tools/operator/remove_codex_sandbox.ps1)
```
