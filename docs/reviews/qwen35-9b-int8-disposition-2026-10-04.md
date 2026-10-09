# Disposition - #1665 9B INT8 arc: three independent reviews (F1-F11 and N1-N8, G1-G14, H1-H7)

**Reviews (all by an independent reviewer on Opus, who ran the code; none wrote a fix):**
`docs/reviews/code-review-1665-9b-int8-2026-10-04.md` (round 1: 2 blocking, 9 should-fix, 8 notes),
`docs/reviews/code-review-1665-9b-int8-round2-2026-10-04.md` (round 2: 2 blocking, 6 should-fix, 6 notes),
`docs/reviews/code-review-1665-9b-int8-round3-2026-10-04.md` (round 3 verification of the round-2 fixes: one blocking,
which was the missing record this file closes; 4 should-fix, 3 notes). Round 3's statement was NOT MERGE-READY until
this record and H1-H4 existed.
**Author of the work and of this disposition:** the session on #1665 (fixes written by Sonnet builders under its
direction). The reviewers did not write fixes.

```disposition
F1 hf_publish passes a dash-leading --path-in-repo to hf upload as an option (could delete the public dataset) | FIXED | 51457339 - option-shaped and non-allowlisted target values are refused before any subprocess, hf positionals follow a literal --; locked in tests/integration/test_hf_publish.py and confirmed by round 3 (db75cd77 closes the trailing-newline variant)
F2 MTP on vs off outputs are not byte-identical (2 of 366 calls, 9B) and the compare instrument checked one run | FIXED | d6579057 - the compare covers every pinned run and every shared suite; fad4c32b retracts the Phase 1 claim in place (4B recomputed 1 of 377) in the verdict, README, journal fragment and PERFORMANCE_LOG; ticket comments 3855 and 3866 carry the correction
F3 the dataset builder output fails the publisher's own preflight and only a blanket exemption passed it | FIXED | d6579057 - builder output passes preflight with no exemption; 710ba8a6 rebuilds both dataset folders clean; round 3 re-ran preflight on both
F4 preflight is a key-name blocklist and misses secrets, e-mail and generated text under other keys | FIXED | 51457339 - secret, e-mail and identity detection and a wider key set; db75cd77 and 710ba8a6 add list, CSV, file-type, file-name and JSON-escape coverage, key-length, per-file budgets and commit-text scanning; 78 tests and mutants killed
F5 no test covers the MTP witness flag for a non-4B quality job | FIXED | d6579057 - the campaign command builder is locked for every size and 14B; mutation-checked
F6 the TTFT summary reports a 4B agreement key for data with no 4B arm | FIXED | 06f12936 - the agreement keys follow the sizes present
F7 the speed summary's MTP acceptance rows carry no arm name | FIXED | 06f12936 - rows carry the arm
F8 the speed summary notes claim what the data does not hold | FIXED | 06f12936 - notes are computed from the arms that ran, with a lock; 1f71663c names the 14B runtime per divergent cell
F9 a 9B dataset build drops files silently and defaults into the published 4B folder | FIXED | d6579057 - dropped files are named and the per-size files copied; db75cd77 refuses a non-empty --out; 48502237 copies the pre-top-up summary
F10 the 9B-vs-14B quality compare is narrower than Phase 1's and not labelled by runtime | FIXED | d6579057 - the compare covers every shared suite and records each side's runtime or says it is not recorded
F11 the publisher agent's rules cite fields that do not exist and its boundary is prose only | FIXED | 176a4984 - cites the real summary keys and names where it stops; 0aafe702 follows up; the tool-level limits are enforced by hf_publish itself (no token argument, allowlisted targets)
N1 _validate_target accepted C:evil, a//b and ./x | FIXED | 51457339 - strict allowlist regex; db75cd77 anchors it with fullmatch and refuses a trailing newline
N2 the A10+ invocations are dropped by the glob and --sizes is not de-duplicated | FIXED | db75cd77 - the glob accepts two-digit invocations; 710ba8a6 de-duplicates --sizes and rejects an empty list
N3 the TTFT analyser docstring says rows carry no runtime label | FIXED | 06f12936 - docstring corrected
N4 repeat blocks report failing_in_every_run over a single run | FIXED | 710ba8a6 - one-run blocks carry single_run and a note; Phase 1 outputs unchanged apart from the new key
N5 conversation and answer-quality denominators are misstated | FIXED | 0aafe702 - denominators stated as measured (20 of 21 evaluated plus one tool-call case; answer quality over its 38)
N6 the token-rejecting test certifies only --token | FIXED | 710ba8a6 - token and identity text in message, config and path-in-repo is refused before any subprocess
N7 mutants M5 and M8 survived all tests | FIXED | db75cd77 locks M5; 710ba8a6 extracts models_meta and locks M8
N8 hf_publish hard-codes a C:/Users home path in repo code the public mirror carries | FIXED | 51457339 - the path comes from Path.home()
G1 the Policy Agent recommendations rested on an unchecked premise (live requests carry arguments under the rejected key args) | FIXED | 0aafe702 - the deterministic-DENY-on-rejection recommendation and the keep-the-14B-because-it-refuses-on-the-marker reasoning are withdrawn in place in the verdict, log, READMEs, summaries and journal fragment; tickets 1673 and 1665 carry the retraction (comments 3865 and 3866) and the live-path trace is ticket 1674; round 3 grepped the whole branch and found every remaining hit inside a visible retraction
G2 the retracted claims are still on the public Hugging Face cards and the committed 4B folder fails preflight | FIXED | 0aafe702 - both dataset folders rebuilt preflight-clean with the claims corrected, corrected root-card text in docs/research/hf-root-card-correction-2026-10-04.md; the live cards are replaced in the upload step of this ship (ticket 1665 comment records the upload commit)
G3 Policy Agent outputs byte-identical across 3 runs hashes only the parsed label and confidence | FIXED | 0aafe702 - reworded everywhere to parsed label and confidence identical in 3 of 3 runs, raw text not compared; ticket comment 3868
G4 the cold-gate exclusion uses one of two readings of 72 C before every generation | FIXED | db75cd77 - --strict-start-temp adds the stricter reading as a sensitivity (9B MTP on ao-long n 9 to 5, ratio 2.173 to 2.295, headline ratios do not move); 710ba8a6 corrects the start range to 72.9-81.9 C with denominators (38 of 154; 4B 36 of 69); ticket comments 3868 and 3869; every document carries the post-hoc disclosure
G5 preflight lets generated text through by key name, container shape and file type | FIXED | db75cd77 - lists, bare strings, CSV allowlist, nested READMEs, file types, file names and JSON escapes; 710ba8a6 closes H3's remaining shapes
G6 the builder can still write into a committed dataset | FIXED | db75cd77 - a non-empty or file --out is refused (exit 2)
G7 the Jev note's evidence does not trace to the rows and keeps the retracted framing | FIXED | 0aafe702 - recomputed and corrected in place; 710ba8a6 limits the population to the 6 informative rows (probability 0.3999-0.7119, all below 0.75); ticket 1672 comment 3867 and the follow-up carry the correction
G8 there is no disposition record for the arc | FIXED | docs/reviews/qwen35-9b-int8-disposition-2026-10-04.md - this record, verified by scripts/verify_disposition.py before the merge
G9 one more MTP on-vs-off divergence exists outside the pinned runs | FIXED | 0aafe702 - listed (1 of 192 for the 9B, 0 of 195 for the 4B) in the documents
G10 the MTP acceptance total comes from the cumulative counter and heat rows report accepted equal to drafted | FIXED | 0aafe702 - per-row sums 3445 of 4635 over 265 and 2680 of 3870 over the 180 measured rows stated; ticket comment 3868
G11 wording mismatches in the identity and runtime notes | FIXED | 1f71663c - the note names which 14B runtime each divergent cell belongs to, with a lock
G12 the target regexes accept a trailing newline and the printer crashes on text the console cannot print | FIXED | db75cd77 - fullmatch, backslashreplace on stdout; locked
G13 surviving mutants and the unmeasured-gate row locked in the direction called a defect | REJECTED | the surviving mutants are fixed (db75cd77 added their locks); for a cold row with no cold_wait record the analyser keeps the row because older data predates the field and excluding it would change the committed Phase 1 output; incidence is zero in both datasets (all 154 and 69 kept rows carry a measured start temperature) and the summary reports how many kept rows started above the limit; failing closed on missing evidence is the right default for a control and the wrong one for a retrospective analyser whose job is to report what it was given
G14 prompt identity holds within each model but 5 of 13 model-judged cases carry a rejected schema | FIXED | 0aafe702 - disclosed in the verdict and READMEs (cases 004, 005, 007, 011, 013; the 4B, 9B and 14B all DENY 004, 005 and 011)
H1 the strict-gate dropped rows started at 72.9-81.9 C, not 76.9, and 36 cold rows is 36 of 69 | FIXED | 710ba8a6 - range recomputed from raw rows and corrected with denominators in every document; ticket comment 3869
H2 the Jev count included harmless controls as wrong ALLOWs | FIXED | 710ba8a6 - population limited to informative rows with the definition stated; the corrected text is posted on ticket 1672
H3 preflight passes generated text as a JSON key and in CSV cells beyond the header and by chunking | FIXED | 710ba8a6 - key-length cap, per-column CSV check, per-file free-text budgets; mutants killed
H4 commit message, config and path-in-repo are not scanned for e-mail, token or identity strings | FIXED | 710ba8a6 - scanned in _validate_target before any subprocess; locked
H5 the 4B folder cannot be regenerated by its builder | FIXED | 710ba8a6 - the builder computes the recomputed on-vs-off compare itself (1 of 377)
H6 the Vikunja draft says nothing was posted and 36 cold rows lacks the 69 | FIXED | 710ba8a6 - the draft lists comments 3865-3868 and ticket 1674 as posted and states 36 of 69
H7 Qwen3.5 ignores the marker stands unqualified in the main text | FIXED | 710ba8a6 - qualified everywhere: evaluation prompt, two cases plus V4, not shown live
```

## Notes for the reader

- The live-path trace of how argument-bearing requests reach the Policy Agent is ticket #1674; nothing in this
  arc claims the model path is or is not live.
- The branch gate figure is a WORKTREE figure: it is not the baseline in `docs/TEST_GOVERNANCE.md` section 1.
