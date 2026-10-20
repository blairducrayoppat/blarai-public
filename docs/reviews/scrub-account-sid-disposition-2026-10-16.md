---
title: "Disposition — adversarial reviews, rounds 1 to 5, machine account SID scrub (#1799)"
date: 2026-10-16
review_of: "47ef9daa, 69b5a97b, f40444c4, 9be732bd and 77f2b9ba on feat/scrub-account-sid"
reviewer: independent subagents (author != verifier); records scrub-account-sid-review-2026-10-16.md, scrub-account-sid-review-round2-2026-10-16.md, scrub-account-sid-review-round3-2026-10-16.md, scrub-account-sid-review-round4-2026-10-16.md and scrub-account-sid-review-round5-2026-10-16.md
---

# Disposition — machine account SID scrub reviews (2026-10-16)

Round 1 fixes: `a413c579`, `69b5a97b`. Round 2 fixes: `b889f070` (N1, N3), `14e2747d` (N2, N5). Round 3 fixes: 92714005 (R1, R2; N1 reopened, the round-2 fix covered plain bytes only). Round 4 fixes: `1660035a, be088050` (R4-1 to R4-6; F5 reopened for the crash path). Round 5 fixes: `79dfb1f3` (R5-1 to R5-8; F5, R4-2, R4-4 and R4-5 reopened for the paths round 5 found).

```disposition
f1-lock-encoding-coverage-not-locked | FIXED | a413c579
f2-dir-passes-sid-in-names-and-compressed-containers | FIXED | a413c579
f3-sid-scope-covers-zero-tracked-files | FIXED | a413c579
f3b-sid-outside-sid-scope-utf16-unreadable-by-the-tree-test | DEFERRED | #1799 blocked-by: a later push of a folder or tracked file outside SID_SCOPE carrying a UTF-16 SID, which scrub_public_identifiers.py --dir --check refuses (tests/security/test_machine_sid_scrub.py::test_dir_check_fires_before_and_is_silent_after[utf16_bom]); tree files outside SID_SCOPE stay guarded only by tests/security/test_no_machine_sid_domain_in_tree.py.
f4-rewrite-reads-raw-bytes-lock-reads-views | FIXED | a413c579
f5-dir-rewrites-without-a-record | FIXED | a413c579 (reopened by round 4 R4-2 and round 5 R5-1; 79dfb1f3 stages every rewrite, proves read, write, decode and name for every file before writing, and rolls back a failed write)
f6-sid-glued-after-a-letter-neither-flagged-nor-rewritten | DEFERRED | #1799 blocked-by: no producer found; observable when a --dir --check run on a folder carrying a letter-glued SID is refused (tests/security/test_machine_sid_scrub.py::test_a_sid_glued_after_a_letter_is_never_rewritten_into_a_wrong_value documents the current behaviour without forbidding the fix).
n1-lock-narrower-than-the-rewrite | FIXED | 92714005 (reopened by round 3 R1; b889f070 closed plain bytes only)
r1-lock-narrower-than-the-rewrite-inside-gzip-and-utf16 | FIXED | 92714005
r2-property-lock-overclaims-and-cannot-see-r1 | FIXED | 92714005
n2-tree-mode-file-name-sid-rules-unlocked | FIXED | 14e2747d
n3-test-mandates-a-spare | FIXED | b889f070
n4-lock-matches-the-sid-string-not-the-sub-authorities | DEFERRED | #1799 blocked-by: a later push of a folder containing a truncated, line-wrapped, binary, hex or base64 SID shape that scrub_public_identifiers.py --dir --check refuses; run-20261016-1 census shows 0 incidence of these shapes (live-domain value scan in --dir is the closing design).
n5-dir-without-log-outside-a-checkout-crashes | FIXED | 14e2747d
n6-no-disposition-record | FIXED | feat/scrub-account-sid
r4-1-preflight-and-check-crash-on-a-damaged-deflate-body | FIXED | 1660035a
r4-2-dir-rewrite-changes-files-then-crashes-without-a-log | FIXED | 79dfb1f3 (1660035a covered undecodable content only; reopened by R5-1)
r4-3-unreadable-utf16-branch-untested | FIXED | 1660035a
r4-4-unreadable-input-labelled-as-a-sid | FIXED | 79dfb1f3 (1660035a missed the gzip depth cap; reopened by R5-4)
r4-5-preflight-prints-a-sid-carrying-file-name | FIXED | 79dfb1f3 (1660035a missed the size-cap line; reopened by R5-2)
r4-6-garbled-toggle-test-docstring | FIXED | 1660035a
r5-1-dir-rewrite-writes-then-dies-on-a-read-only-file-or-unencodable-name | FIXED | 79dfb1f3
r5-2-preflight-size-cap-line-prints-a-sid-name | FIXED | 79dfb1f3
r5-3-preflight-raises-on-permission-unencodable-name-and-deep-json | FIXED | 79dfb1f3
r5-4-sid-free-gzip-past-the-depth-cap-labelled-a-sid | FIXED | 79dfb1f3
r5-5-utf32-text-passes-lock-and-preflight | FIXED | 79dfb1f3
r5-6-mutants-ml-and-mj-survive | FIXED | 79dfb1f3
r5-7-preflight-email-pattern-quadratic-on-long-runs | DEFERRED | #1800 blocked-by: #1800 (the preflight e-mail pattern in hf_publish._SECRET_PATTERNS is replaced by a linear-time form)
r5-8-refused-run-counts-one-file-twice | FIXED | 79dfb1f3
r4-7-host-name-glued-before-a-sid-lock-rewrite-gap | REJECTED | every check path also runs the host lock, so the file never passes; the SID lock disagreeing with a rewrite that runs the host rule first creates no passing file (reviewer finding 6 is INFO and agrees)
r4-8-preflight-escaped-sid-shapes-locked-only-indirectly | REJECTED | the preflight reads them through identity_lock.find_sid_hits, which tests/security/test_machine_sid_scrub.py drives per shape against the rewrite; a second per-shape copy in test_hf_publish.py would duplicate that lock (reviewer finding 7 is INFO)
```
