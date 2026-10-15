---
title: "NEP-0005 srt-win command-line run: banking review (claims, summary, logs and the NEP-0005 evidence write-up (unposted)), finding disposition"
status: closed
area: reviews
date: 2026-10-13
---

# srt-win command-line run banking review disposition (#1763)

**Subject:** the banking diff `7097fbec..63ca29aa` on `feat/1763-nep0005-open-questions`, which contains:
- claims C20 and C22 to C26;
- `runs/srtcli-results-summary.json`;
- the AS_RUN section;
- the PERFORMANCE_LOG entry and its JSON;
- the journal fragment and FIELD_NOTES;
- the review disposition;
- the NEP-0005 evidence write-up (unposted).

**Reviewer:** an independent Opus agent, read-only, checking against the raw records and snapshots. Round 1 returned FAIL with 13 findings; none blocked the merge on its own. Review file: `docs/reviews/review-nep0005-srtcli-banking-1763-2026-10-13.md`.

**Fix commits:** `52ff190b` (round 1 findings B1 to B13) and `0dac5d2c` (round 2, verdict PASS: three text items and the exporter's reproducibility).

## Disposition

```disposition
B1-thirteen-stamped-folders-is-eleven | FIXED | 52ff190b C25, the NEP-0005 evidence write-up (unposted) and FIELD_NOTES say srt-win stamped the 11 of its 13 targets that exist here (the two FxsTmp folders are absent); the driver snapshots the same 11
B2-store-folder-six-of-six-overstated | FIXED | 52ff190b C25, the NEP-0005 evidence write-up (unposted), PERFORMANCE_LOG and AS_RUN: created by the first install from absent (1 of 1), removed by no uninstall (7 of 7 including the first cycle), the counted runs began with it present; AS_RUN names the 17:03 dry run as the point it read absent
B3-c23-quote-not-in-cited-summary | FIXED | 52ff190b Export-SrtcliSummary.ps1 keeps every srt-win line of each re-install (srt_win_said joined with " / "); summary regenerated with LF bytes, its hash re-recorded in AS_RUN; C23 cites the field
B4-c26-conditions-name-the-wrong-run | FIXED | 52ff190b C26 conditions name the first-cycle run (16:39:32 to 16:42:24, driver as committed at 70b9c877; its file hash is in AS_RUN), the scratch before-snapshot and the later cycles separately
B5-draft-b-open-without-loopback-qualifier | FIXED | 52ff190b Draft B says the account can connect to a loopback listener on that family and that real IPv6 egress was not measured
B6-draft-a-opening-is-a-design-verdict | FIXED | 52ff190b Draft A's thanks now lists what was read before measuring, without calling it a design judgement
B7-timing-ranges-miss-measured-values | FIXED | 52ff190b the table in the NEP-0005 evidence write-up (unposted) uses the measured min-max (install 1.41-1.73 s, uninstall 1.34-1.57 s, repair or restore 1.09-1.57 s, early-out or refusal 0.10-0.11 s); comment 4101 corrected on the ticket
B8-creator-owner-split-and-most-hidden | FIXED | 52ff190b C26, PERFORMANCE_LOG and the NEP-0005 evidence write-up (unposted) give 5 made inherit-only and 2 dropped, and Draft A gives 563 / 7 / 7 instead of "most"
B9-uninstall-cadence-after-pass-3 | FIXED | 52ff190b PERFORMANCE_LOG method: uninstall and direct checks after every pass, three per build
B10-four-deny-logon-rights-not-read-while-installed | FIXED | 52ff190b C25 and the NEP-0005 evidence write-up (unposted) say the rights were read only after uninstall and that "four" comes from user.rs LOGON_DENIALS
B11-disposition-ids-and-f13 | FIXED | 52ff190b the review disposition explains its labels for the unnumbered round 4 and round 6 items and records F13 as FIXED by the sanitising exporter, matching the review's ACCEPTED-pending-banking
B12-as-run-names-changed-deploy-script | FIXED | 52ff190b AS_RUN names the deploy script as it stood at 7097fbec and the later removal of its -BuildRoot default
B14-r2-1-driver-snapshots-11-not-13 | FIXED | 0dac5d2c C25 and row B1 say the snapshot covers the 11 targets that exist (the loop skips missing folders); ticket comment 4102 is corrected by the merge comment on #1763
B15-r2-2-exporter-header-says-first-line-only | FIXED | 0dac5d2c Export-SrtcliSummary.ps1 header names srt-win's own lines about each re-install as kept
B16-r2-3-fragment-creator-owner-wording | FIXED | 0dac5d2c the journal fragment gives the 5 inherit-only and 2 dropped split
B17-r2-note-exporter-not-byte-deterministic | FIXED | 0dac5d2c keys sorted ordinally and the kinds table ordered; two separate processes wrote identical bytes, whose hash is recorded in AS_RUN with the note that the exporter reproduces them
B13-field-notes-culture-wording | FIXED | 52ff190b FIELD_NOTES says the DateTime is turned back into text with no zone marker and parsed as local time
```
