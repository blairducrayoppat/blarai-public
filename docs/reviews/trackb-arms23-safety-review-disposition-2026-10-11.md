---
title: "Track B arms 2 and 3 scripts: independent safety review, finding disposition"
status: closed
area: reviews
date: 2026-10-11
---

# Track B arms 2 and 3 scripts: safety review disposition

**Subject:** branch `feat/trackb-arms-2-3` at `aab46664` (the arm 2 and arm 3 scripts as first delivered), reviewed by an independent agent on 2026-10-11 after arms 2 and
3a had run live. Verdict of the review: RUN LIVE AFTER FIXES; arms 2 and 3a acceptable, arm 3b not. Eleven findings, numbered as in the review's list.

**Fix commits:** `02cb0953` (scripts: ordering, admin-only folder rule, pinned wrapped script, proof binding, post-reboot semantics, idle gate), `123a80d2`
(documentation, the corrected bundle test and the banked results), `aa3b46e7` (check-then-use fixes) and, after a second independent review of `cfd7eb8c` (verdict merge after fixes),
`dff6f0cb` (the findings below marked second review) plus 2d991233. Every fix has self-tests (92 bundle tests pass at `dff6f0cb`, including every script's
`-SelfTest` under PowerShell 7 and Windows PowerShell 5.1); none of the fixed 3b paths has been exercised against a real task scheduler, a real restart or the real engine.
Rows F3, F5, S1 and S4 were marked FIXED earlier and were incomplete (the wrapped script's text was still evaluated before any check and from a user-writable default path; ancestors of
the script folder were not checked); they are re-dispositioned below with the later commit.

## Disposition

Finding 1 has two parts: the false statement (fixed) and whether a forced restart of the operator's machine is acceptable (his decision, recorded as a deferral with an observable
predicate, not made here). Finding 6's fallback is code that depends on a snippet compiled and run only in a later live step; it is covered by compile and parse tests, not run.

```disposition
F1a-restart-is-forced-and-the-docs-and-test-said-it-was-not | FIXED | 02cb0953 (script headers) and 123a80d2 DESIGN, READMEs, script headers and the bundle test now state that a timeout above 0 implies /f; the test asserts the argument list and every document's disclosure, with a toggle test
F1b-whether-to-accept-a-forced-restart-of-the-operators-machine | DEFERRED | #1682 blocked-by: the file arm3b-restart-decision.json in the admin-only script folder (and a comment on #1682) recording the Lead Architect's decision; dff6f0cb makes spike-arm3b-arm.ps1 -Live and the elevated wrapper refuse without it
F2-window-between-the-add-and-the-cleanup-tasks | FIXED | 02cb0953 both cleanup tasks are registered before the add; the arm state is written first without filters_added_at; self-tests assert the order (store empty at registration) and the old exception-after-add case
F3-system-and-elevated-tasks-run-scripts-from-a-writable-folder | FIXED | dff6f0cb (02cb0953 was incomplete: owners, ancestor delete rights and links were not checked) Test-AdminOnlyFolder gates the wrapper (register and inner), the 3a dead-man and the 3b arming script; the SYSTEM tasks pin the wrapped script hash; read-only check confirmed C:/ProgramData/BlarAI/trackb-live passes and the user's repo folder fails
F4-post-reboot-removal-verification-depended-on-the-network | FIXED | 02cb0953 removal is verified by the engine reading ABSENT, attempts are bounded (3) and expire (24 h), a down network and a repeat run are exit 4, an unrecorded add is exit 4
F5-the-proof-did-not-cover-the-security-descriptor-code | FIXED | dff6f0cb (02cb0953 was incomplete: a forged 999-check proof with failed checks passed, and the proof could sit in a user-writable folder; now refused) the proof binds the wrapped #1671 script hash and the evidence of a real run (checks run and passed, sibling results); a proof with 0 checks or a one-token edit of the wrapped script is refused; the proof sits beside the scripts
F6-every-automatic-removal-path-depended-on-parsing-the-wrapped-script | FIXED | 02cb0953 Invoke-ManualRollback (self-contained C#) is the fallback in -Remove, post-reboot and veto when the wrapped script is missing, changed or unparseable; output parsing is tested, the snippet is compile-checked and was not run
F7-idle-gate-does-not-check-the-session | FIXED | 02cb0953 Test-InteractiveSession: session 0 or a non-interactive process reads as unreadable and the gate refuses
F8-two-short-windows-where-input-is-absorbed | FIXED | 02cb0953 one input baseline, read at the idle gate, runs through the countdown and the pending-restart watch; a test shows input before the countdown aborts at once
F9-watchdog-claims-overstated | FIXED | 123a80d2 DESIGN section 2 item 5 states that 3a has no watchdog tick during an export and that 3b has none after the add
F10-toast-shown-only-means-the-helper-exited-zero | FIXED | 02cb0953 the module comments state that the toast result is one visible channel, not proof it was seen, and that the gate refuses when neither toast nor window exists; the limit itself cannot be removed from inside the script
F11-record-says-not-run-but-the-builders-live-check-and-remove-are-not-recorded | FIXED | 123a80d2 ARMS_HANDOFF (arm 3a limits) and the evidence document section 3 record the builder's elevated -Check and -Remove (four absent keys queried, four deletes returned not found, nothing added)
S1-wrapped-script-hashed-then-parsed-from-the-path-again | FIXED | dff6f0cb (aa3b46e7 read the bytes once but still evaluated them before any pin or folder check) Import-WfpHelpers does one ReadAllBytes and hashes, parses and evaluates those bytes; the proof is compared with the hash of what was imported (-WrappedSha256); a bundle test forbids ParseFile and a second read
S2-libraries-hashed-for-the-proof-but-dot-sourced-from-the-path | FIXED | aa3b46e7 Get-VerifiedLibBlock reads each library once, records the hash of those bytes and runs a scriptblock built from them; the proof and the code-set id use the recorded hashes
S3-system-tasks-ran-whatever-the-folder-held-at-startup-after-the-hash-at-arming | FIXED | aa3b46e7 the tasks carry -CodeSetId and -WfpSha256 and refuse any other code set before using the wrapped script, falling back to the self-contained rollback
S4-system-and-elevated-writes-into-user-writable-output-folders-through-links | FIXED | dff6f0cb (aa3b46e7 did not cover reparse points in ancestors of the script folder) Assert-PlainOutputPath and Write-JsonGuarded refuse reparse points and hard-linked targets for every record, export and log; the arming script and the dead-man require the output or state folder to be admin-only; the proof is trusted only from an admin-only place
N1-wrapper-checks-the-folder-acl-then-runs-the-script-later | REJECTED | The window needs a principal that can change an administrator-only folder, who could already run elevated code directly, and the check is repeated at registration and again in the inner process, so it adds no attacker capability.
N2-the-entry-script-cannot-hash-itself-before-it-runs | REJECTED | PowerShell reads the entry file before any of its code can run, so a self-hash would hash text already executed; the control is the admin-only folder plus the code-set id, which includes the entry script, checked at task start.
N3-arm-state-json-read-by-the-system-tasks-from-the-output-folder | REJECTED | It is parsed as data only (dates compared, strings never executed or used as paths) and the folder is now required admin-only, so a planted file cannot reach code.
R2-1-wrapped-script-text-evaluated-before-any-hash-or-proof-check-from-a-user-writable-default-path | FIXED | dff6f0cb Import-WfpHelpers gates (pinned hash or admin-only folder) before any read as code; the default -WfpScript is the copy beside the scripts in all four entry scripts; -SelfTest alone may evaluate the repository copy; self-tests prove an unpinned file in a non-admin folder and a wrong pin are refused with nothing evaluated; a bundle test checks the order and the default
R2-2-arm-3a-ran-the-pre-fix-scripts-and-the-record-did-not-say-so | FIXED | 2d991233 adds arm3-persist/runs/AS_RUN.md (live-copy hashes against aab46664, files changed since, the explicit admin-only -WfpScript and -NoDeadManTask as supplied by the lead) and corrects the evidence document row C10a and ARMS_HANDOFF
R2-3-admin-only-check-missed-non-admin-owners-ancestor-delete-rights-and-links | FIXED | dff6f0cb Test-AdminOnlyFolder with injectable providers; eleven fabricated-descriptor and attribute cases (parent owned by the operator, parent granting Users delete, delete plus add-subfolder, links) fail, ProgramData-style create-only ancestors still pass; the real trackb-live folder still passes
R2-4-proof-accepted-implausible-check-counts-and-failed-checks-and-a-proof-beside-the-scripts-in-a-user-folder | FIXED | dff6f0cb Test-RollbackProof refuses failed_checks and a count above the self-test's check sites; Test-ProofLocation always requires an admin-only folder; the proof records the hash of the bytes the self-test read (no second read); tests with toggles
R2-5-the-later-check-exit-20-after-3a-had-no-banked-file-and-the-journal-gave-the-wrong-time-for-the-accidental-check-and-remove | FIXED | 2d991233 banks arm3-persist/runs/post-3a-verification.txt (the reviewer's -Check at 16:52:29, source named) and corrects the journal fragment to before the live runs (about 14:21)
R2-6-false-console-message-claiming-a-dead-man-task-when-it-is-off | FIXED | dff6f0cb the ROLLBACK FACT line names the dead-man task only when -DeadManTask is on
R2-7-bitdefender-signal-reported-as-three-folders-and-the-start-time-not-compared | FIXED | 2d991233 lists all five folders, states that the 14:42 values predate the hold start 14:48:56, notes the two-hour pattern and keeps the signal weak in the evidence document, handoff, performance log and JSON
R2-8-arm-1-and-arms-2-3a-used-two-different-accounts-of-the-same-name | FIXED | 2d991233 states relative ids 1011 (arm 1) and 1271 (arms 2 and 3a) in the evidence document, handoff and performance log
```


## Follow-up: automated commit scan, same day (rows S1 to S4, N1 to N3 in the block above)

The scan on `02cb0953` reported four issues and named one: a time-of-check/time-of-use gap in `spike-persist-lib.ps1` (the proof hash checked, the file read again later).
It overlaps review findings 3 (SYSTEM tasks and writable paths) and 5 (proof coverage); my own diff review for the same class found the rest. Fixes are in `aa3b46e7`.

The rows S1 to S4 and N1 to N3 are in the single disposition block above.

## Honest limit of this record

The verifier checks the form of this record, not whether a fix is right. The restart decision (F1b) is the only open item that blocks arm 3b; the others are fixed in code that
has only run against fakes. "FIXED" for F2 to F8 means the self-tests pass and the desk review of the live paths found no further defect; it does not mean the live 3b flow has been seen working.
