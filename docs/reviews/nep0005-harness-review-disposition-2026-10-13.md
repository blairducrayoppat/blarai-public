---
title: "NEP-0005 open-questions halfset harness: independent review, finding disposition"
status: closed
area: reviews
date: 2026-10-13
---

# halfset harness review disposition (#1763)

**Subject:** the `halfset` Rust harness under `docs/research/containment-evidence-2026-10-05/nep0005-open-questions/harness/`, reviewed in three rounds on 2026-10-12 by an
independent agent (round 1 FAIL: D-H1 to D-H8; round 2 PASS: R2-1 to R2-3; round 3 PASS, no new findings). Review files (kept in the main checkout's `docs/reviews/`):
`review-nep0005-harness-1763-2026-10-12.md`, `review-nep0005-harness-rev2-1763-2026-10-12.md`, `review-nep0005-harness-rev3-1763-2026-10-12.md`.

**Fix commit:** `481713ee` carries every fix: the harness was first committed there, already at the round 3 state. Checked on disk: `halfset.rs` at that commit hashes to
`e0d560fcb24b...`, the value round 3 reviewed; README.md and tests/refusals.ps1 equal the round 3 hashes (`6ddc176d`, `a2c52341`). Fix evidence below names the function or file read
in that commit. No live run of the harness against the real engine is claimed by this record.

## Disposition

The round 1 incident (four persistent filters left in sublayer S1 by a reviewer's probe) is a machine state, not a code defect; its removal is recorded as its own row because
nothing in the repository shows it was done.

```disposition
D-H1-no-arming-interlock-on-mutating-subcommands | FIXED | 481713ee halfset.rs require_armed (called by install, delete-filter, delete-sublayer and uninstall before the first engine open) and check_proof (the proof must name this exe's sha256 and the embedded source hash, checks_failed 0, within 24 h); the shipped build has no toggle for it; refusals.ps1 asserts exit 12 for each mutating subcommand without a valid token
D-H2-install-cannot-produce-the-n1-row-and-selftest-locks-the-refusal | FIXED | 481713ee halfset.rs emit_eng carries write_attempted on every engine error (false in the precheck phases); harness README guard 4 states that harness install and delete-filter cannot record a write verdict for a token denied enumeration and routes the N1 add and delete verdicts to the matrix direct adder and deleter; the guard itself is kept
D-H3-refusals-pass-not-bound-to-the-source-tested | FIXED | 481713ee halfset.rs embeds EMBEDDED_RS_SHA256 (option_env) and prints it in --version; refusals.ps1 S.* rows compare it with the sha256 of the halfset.rs beside the suite for both exes; build records bind the exe hashes
D-H4-parse-guid-accepts-unbalanced-braces | FIXED | 481713ee halfset.rs selftest rows sublayer_unbalanced_braces_parse_to_S1 pin the three forms, and harness README line 77 states the behaviour
D-H5-delete-sublayer-emptiness-refusal-untested | FIXED | 481713ee halfset.rs delete_sublayer_checked now calls guard_sublayer_empty (the same function the fake-source selftest rows exercise)
D-H6-trace-file-failure-labelled-engine-error | FIXED | 481713ee halfset.rs classify maps trace_open_failed to exit 13 trace_failed (selftest row asserts it); README exit table lists 13 as the engine was not touched
D-H7-module-doc-overclaims-guard-order | FIXED | 481713ee halfset.rs module doc (lines 7 to 12) now says the sublayer, SID and arming guards run before the first engine open and that the empty-sublayer guard and stop sweep run after a read-only enumeration
D-H8-enum-all-ours-ignores-sublayer | FIXED | 481713ee halfset.rs the all-ours enumeration calls forbid_extra with only all-ours allowed, so --sublayer is exit 2; refusals.ps1 A.usage.all_ours_rejects rows
R2-1-suite-not-armed-rows-reach-the-real-engine-if-the-code-under-test-is-wrong | FIXED | 481713ee tests/refusals.ps1 Test-Refused routes every shipped-exe mutating row through the TraceIsDirectory switch (trace variable set to a directory, exit 13 before any engine open, 13 against the wanted 12 is a bypass); round 3 confirmed with the toggle exe and the interlock off that all twenty rows fail as 13 against 12
R2-2-uninstall-reports-write-attempted-false-after-the-write | FIXED | 481713ee halfset.rs delete_sublayer_checked takes a write_attempted parameter; cmd_delete_sublayer passes false and cmd_uninstall passes true after lib_uninstall has run
R2-3-readme-does-not-say-what-the-interlock-is-not | FIXED | 481713ee harness README line 62 states the interlock gates intent not authority, the proof inputs are public, and checks_failed 0 is an unverified claim so a proof is not evidence a self-test ran
R3-nit-toggle-exe-rows-keep-the-file-trace-form | REJECTED | The rows that run the toggle exe with a mutating subcommand keep the file trace on purpose: that build can never open the engine, and reaching its entry point is the thing being asserted.
Builder-open-point-3-precheck-bypass-for-n1 | REJECTED | The reviewer showed no precheck bypass can help: install_filters itself enumerates before its first add, so a token that cannot enumerate never reaches an add through srt-win; the guard order stays and D-H2 records the limit.
Builder-open-point-4-precheck-and-install-race | REJECTED | The window between the precheck session and install_filters own session cannot be closed through srt-win's public API, is bounded to srt-win tagged filters under S1 S2 S3 and needs a concurrent elevated writer; harness README line 79 records it as a residual and the matrix runs with the fleet paused.
Builder-open-point-9-ale-only-emptiness-check | REJECTED | The emptiness check enumerates the two ALE layers only, and the engine FWP_E_IN_USE on the sublayer delete is handled as a second refusal (exit 5), so a filter at another layer cannot be deleted past; a filter there under S1 S2 S3 would be foreign anyway.
R2-nit-self-hash-time-of-check-gap | REJECTED | The reviewer ruled it out of scope: whoever can swap the exe file between the hash and the run can write a correct proof directly, so it adds nothing against a deliberate actor and nothing against an accident.
Builder-open-point-6-null-enum-template-for-all-ours | FIXED | Ran live with the code at 716fd87a (harness unchanged since 481713ee): the sweep that runs `enum --all-ours` read the real engine in every record of the halfset, ours and n1 phases (the halfset results file under the arm3b-out nep5-run-halfset folder carries 114 references; every sweep reports unreadable false and foreign none), so the null enum template works on this build; recorded in the matrix run record AS_RUN and claim rows C12 to C21.
Incident-S1-holds-four-persistent-filters-left-by-the-round-1-probe | FIXED | Removed live on 2026-10-13 at 07:56 by the matrix pre-cleanup in commit 481713ee (`halfset uninstall` on sublayer S1, exit 0, srt_win_tagged_deleted 4, absent_after true); the pre-clean sweeps and netsh exports before (S1 4 filters, 8 srt-win hits) and after (S1 0 filters, sublayer absent, 0 hits) are in the first taskcheck results file under the arm3b-out nep5-run folder; the final -Check read exit 20 everything absent; recorded on #1763 comments 4078 and 4088.
```

## Honest limit of this record

The verifier checks the form of this record, not whether a fix is right. FIXED here means the diff in `481713ee` was read for the named function and the reviewer's round 2 and
round 3 attacks did not break it; the interlock has not been seen working against the real engine. The two live-state items that were open at writing were closed by the 2026-10-13 live runs (rows above).
