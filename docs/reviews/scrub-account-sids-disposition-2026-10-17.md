---
title: "Disposition - independent review of the account-SID scrub (#1793)"
date: 2026-10-17
review_of: "docs/reviews/scrub-account-sids-review-2026-10-17.md: round 1 (commit 2734b8b8) at ea657719, round 2 (commit b86e1f4d) at 9620b00c"
reviewer: independent (the author did not write the review; the fixes below are re-reviewed by the reviewer side)
---

# Disposition - account-SID scrub review (2026-10-17)

Fixes land in 6474a81f. Each mutant the review named survives no longer: M2, M9, M10, M18, M23 and M24, plus two
container-reader mutants (check() and the gate scan reading raw bytes only), each fail tests in
`tests/security/test_account_sid_scrub.py` (2 to 13 failures per mutant, mutation run at 6474a81f).

A-1 was found by the author during the fix, not by the review. Round-2 fixes land in fe25afc8; the mutation run at fe25afc8
kills C1, C2, C3, C5, C9, C10, C14, C15, C16, the zero-padding arm (C17) and the short-sub-authority filter (C18), each with
1 or 2 failures, and the round-1 mutants still die.

```disposition
F1-fixture-real-sub-authorities | FIXED | 6474a81f, fe25afc8 - the four values are invented and share no sub-authority with the live account SID (6474a81f). The lock in its final form (fe25afc8, rows R2-1 and R2-2): test_no_long_sub_authority_of_the_live_account_sid_is_in_any_tracked_file reads the token's Microsoft-account / Entra ID SIDs at test time and fails on any sub-authority of 8 digits or more in any view of any tracked file; under a token without such a SID it skips with that reason (named in docs/TEST_GOVERNANCE.md §1). It fires on the ea657719 copy of the test file and on a planted part; nothing was found in the branch tree, its commit messages, or the binary, hex, reg-hex and base64 forms
F2-hf-name-refusal-and-redaction-unlocked | FIXED | 6474a81f - test_hf_preflight_refuses_a_sid_named_file_and_never_prints_the_name, per SID kind: the refusal line is present, every line reads file #0, no line carries the SID; mutants M23 and M24 each fail 2 tests
F3-containers-outside-sid-scope | FIXED | 6474a81f - identity_lock.account_sid_container_problems opens gzip, bzip2, xz, zip and tar nested to 16 under a 256 MiB bound and fails closed on damage, truncation, trailing bytes, encryption, deeper nesting and other formats; check(), the tree-mode residual and skip paths and the gate tree scan use it; 10 container shapes and 5 unreadable ones outside every scope are tested with clean twins
F4-M2-entra-arm | FIXED | 6474a81f - the fail-closed shapes run for both SID kinds and assert the rewrite arm does not read them, so the Entra arm of ACCOUNT_SID_RE alone carries the fully percent-encoded Entra case (3 failures under M2)
F4-M9-ignorecase | FIXED | 6474a81f - percent_whole_lowercase is seen only by the case-insensitive views regex (2 failures under M9)
F4-M10-gzip-recursion | FIXED | 6474a81f - gzip_percent_letter_before and test_inside_gzip_the_lock_reads_what_only_the_rewrite_reads isolate the rewrite predicate's gzip recursion (3 failures under M10)
F4-M18-tree-residual | FIXED | 6474a81f - test_tree_mode_a_shape_the_rewrite_cannot_clear_exits_1_and_names_the_file drives main() and reads the hand-edit section of the log (3 failures under M18)
F4-M16-zip-member-name-arm | REJECTED | Equivalent in effect for --dir mode only: a zip in a --dir run is reported as an archive and the run exits 1 whatever the member name carries, so removing that arm changes the message, never the exit. The round-1 version of this row also claimed F3's tests covered member names in tree mode; they planted the SID in member bodies only (round 2, R2-3, mutant C5). That claim is withdrawn here and the tree-mode name arm is now tested: see R2-3.
F4-M20-unreadable-path-arm | REJECTED | Near-dead by construction: an unreadable gzip or UTF-16 file yields no decoded view carrying the SID, so the added arm on the unreadable path rarely changes the outcome, and that path already reports every unreadable file it meets as skipped and exits 1 whenever any identifier class applies.
F5-unstated-limits | FIXED | 6474a81f, fe25afc8 - rule 5 in scripts/scrub_public_identifiers.py and the scripts/hf_publish.py docstring name the binary SID and its hex:01 registry-export form, the SID glued after a letter or digit, and the bare sub-authority digits; rule 5 states that the digits are held only for sub-authorities of 8 digits or more of the live account, and only when the token carries such a SID (fe25afc8, rows R2-1 and R2-2)
A-1-old-fixture-in-branch-history | FIXED | 49db6013 - per the lead's decision on #1793 (2026-10-17), fix/scrub-account-sids-land was cut from main b95eb780 and carries one squashed commit of the final tree; 602d414d and ea657719 are not its ancestors, its 83 files and its message carry no sub-authority of the live account SID of any length, and its tree equals fix/scrub-account-sids at 521d55c1; fix/scrub-account-sids stays as the audit record, never pushed and never deleted; history was not rewritten
R2-1-lock-fails-under-a-local-account | FIXED | fe25afc8 - test_no_long_sub_authority_of_the_live_account_sid_is_in_any_tracked_file runs and fails closed when the token carries a Microsoft-account or Entra ID SID and calls pytest.skip("no account SID in this token ...") otherwise; test_under_a_local_account_the_lock_skips_with_its_reason drives it with a local account's whoami output; no digest of a sub-authority is pinned
R2-2-short-sub-authorities-and-remedy-text | FIXED | fe25afc8 - only sub-authorities of LONG_SUBAUTHORITY_DIGITS (8) or more digits are matched; the toggle plants the two 5-digit fixture values as a pid and a port and asserts no hit (mutant C18 fails 2 tests); the failure text says to scrub the identifier with scripts/scrub_public_identifiers.py, or to stop and report a coincidental number in evidence without editing the record
R2-3-archive-member-names-tree-mode | FIXED | fe25afc8 - test_tree_mode_an_archive_member_named_after_the_sid_fails_check_the_gate_scan_and_the_scrub for a zip and a tar (mutant C5 fails 2 tests)
R2-4-C1-C3-C10-masking-arms | FIXED | fe25afc8 - test_a_container_is_opened_by_its_magic_alone_and_by_its_suffix_alone: bzip2, xz and tar named run.dat, and a zip with leading bytes named pack.zip, each isolated from the plain reading (C1, C2, C3 and C10 fail 1 test each)
R2-4-C9-utf16-arm | FIXED | fe25afc8 - test_undecodable_utf16_outside_every_scope_fails_closed (C9 fails 1 test)
R2-4-C14-C16-size-bounds | FIXED | fe25afc8 - test_the_size_bounds_fail_closed lowers ACCOUNT_CONTAINER_MAX_BYTES and asserts the bzip2, zip and tar bounds report over the size, and that a stream under the bound reads clean (C14 and C16 fail 1 test each)
R2-4-C15-sid-scope-filter | FIXED | fe25afc8 - test_inside_sid_scope_check_still_reports_an_account_sid_in_a_container plants a bzip2 carrying an Entra ID SID inside SID_SCOPE through check() (C15 fails 1 test)
R2-4-C11-encrypted-member-check | REJECTED | Equivalent: an encrypted zip member makes zipfile raise RuntimeError on read, which _zip_members already maps to an unreadable finding, so removing the explicit flag check changes only the message text and never turns an unreadable archive into a clean one.
R2-5-gzip-zero-padding | FIXED | fe25afc8 - zero bytes after the last gzip member end the stream, as gzip.decompress reads it; any other trailing bytes still fail closed; test_a_gzip_with_trailing_zero_padding_is_read_like_gzip_decompress covers clean, SID-bearing and junk-trailing cases (C17 fails 1 test)
```
