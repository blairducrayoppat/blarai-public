---
title: "NEP-0005 open-questions branch: pre-merge diff review, finding disposition"
status: closed
area: reviews
date: 2026-10-13
---

# Pre-merge diff review disposition (#1763)

**Subject:** branch `feat/1763-nep0005-open-questions` at `f2e01bf6` against main `30c83c86`. The review focused on two things not covered by the earlier reviews: the evidence-bundle test's SID-scan exemption (a gate edit made in `2f1c90d2`), and the documentation commits `2f1c90d2` and `39e4ab14`.

**Review:** one independent Opus agent, read-only, plus the bundle test run. Verdict: FAIL, one blocking finding. Review file: `docs/reviews/review-nep0005-branch-premerge-1763-2026-10-13.md`.

**Fix commits:** `5a6ce53b` (round 1) and `cf133b0b` (round 2, verdict PASS, four low items). It changes:
- the bundle test;
- the bundle README;
- `SPEC.md`;
- claim C16;
- `AS_RUN.md`.

## Disposition

```disposition
P1-sid-scan-exemption-is-a-whole-folder | FIXED | 5a6ce53b test_containment_evidence_bundle.py SID_SCAN_EXEMPT now lists four exact files, each with the exact full SIDs it may carry (the test account's, and the harness's mock RID 1272); every other SID in those files and these SIDs anywhere else fail the scan; SPEC.md (prose) no longer carries the SID; the fabricated 9-9-9 domain the old exemption had hidden joins the allowed fabricated domains beside 1-2-3; 98 tests pass
P2-narrowness-test-proves-only-the-folder | FIXED | 5a6ce53b test_sid_scan_exemption_is_narrow pins the four-file list and the allowed SID set, and plants SIDs in eleven cases: the listed SID in a listed file passes; the mock SID in the wrong listed file, the operator's RID 1001, a foreign domain, and the listed SID in SPEC.md, runs/ data, a new script, srtcli/, a sibling folder and the top level all fail; the full-tree assertion is its own test again
P3-public-push-duty-lives-only-in-a-comment | FIXED | 5a6ce53b the bundle README has a "Not yet scrubbed" section naming the four files and the rewrite needed before any public push of nep0005-open-questions/; the NEP-0005 evidence write-up (unposted) already names the same duty
P4-module-docstring-claims-a-and-g-false | FIXED | 5a6ce53b the docstring's (a) names the exact exemption and its expiry at the public push, and (g) says the self-test tables cover the listed scripts and that the NEP-0005 scripts are not among them (their self-tests need the admin-only live folder)
P5-c16-unresolvable-check-not-in-saved-data | FIXED | 5a6ce53b claim C16 says the harness's SID guard refuses a stale SID that resolves (halfset.rs guard_install_sid, self-test rows sid_stale_mapped_refused and sid_stale_unknown_refused), so the run proceeding implies the check passed, and that the check's own result is not in the saved data
P6-as-run-lacks-hashes-for-cited-files | FIXED | 5a6ce53b AS_RUN's file table gives bytes and sha256 for results-summary.json and exports-manifest.json (both LF as committed)
Q1-full-sid-pattern-misses-appended-and-prefixed-shapes | FIXED | cf133b0b FULL_SID_RE reads the whole token with every sub-authority; a token is accepted only as an exact listed SID or as an allowed domain with at most one relative id; cases for an appended -1001 and an allowed domain followed by the real domain's numbers both fail
Q2-older-blind-spots-and-readme-overstatement | FIXED | cf133b0b the scan is case-insensitive (lowercase case added); the README now states what the scan does not see (no prefix, split across lines, UTF-16) instead of claiming every real domain; tokens with fewer than three numbers are skipped as naming no domain, with a case
Q3-readme-says-all-four-files-hash-bound | FIXED | cf133b0b the README says three files are hash-bound and refusals.ps1 must match the SID compiled into halfset.rs
Q4-spec-nested-backticks | FIXED | cf133b0b SPEC.md line 14 reads as plain text with one code span
```
