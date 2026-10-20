---
title: "Research pre-flight lock: four independent review rounds, finding disposition"
status: closed
area: reviews
date: 2026-10-15
---

# Research pre-flight lock: review disposition

**Subject:** branch `feat/research-preflight` (BlarAI worktree) at `bf585851`, and branch `fix/number-patterns-widen` of the sibling repository
`windows-containment-evidence` at `44fe7a8`. Four independent adversarial reviews on 2026-10-15, each by a reviewer who had not seen the previous
round's author work: round 1 at `25fa58b4` (FAIL, 1 blocker, 3 high), round 2 at `d872ef8c` (FAIL, 1 high), round 3 at `470e8e6c` (FAIL, 1 high),
round 4 at `22447ac3` (FAIL, 1 high, the stale generated rules corpus). The reviews are `research-preflight-review-round1-2026-10-15.md` to
`research-preflight-review-round4-2026-10-15.md` in this folder. Finding names below are R1-n for round 1 (numbered as in its list of fifteen), R2-n, R3-n and R4-n.

**Fix commits, BlarAI:** `25fa58b4` (the lock, baseline and tests as first delivered), `d872ef8c` (round 1 fixes), `470e8e6c` (round 2 fixes), `22447ac3` (round 3
fixes), `bf585851` (round 4 fix: the rules corpus regenerated, one checklist sentence).

**Fix commits, evidence repository (full ids):** `2bd95ed5057a4cf5424f7857ca65c95de4874033` (gate patterns widened), `4f10187efb03738bc59ff9386e394233e0c24001` (sanitiser
widened), `d08272eb8b1614b4e558dbe6efa9b5274ad93e0f` (round 1 fixes), `f4ae730a54b2c3ba341edf6bd6674387fce707d1` (round 2 fixes), `44fe7a8b2d95ac8345c794adc66cbbcd724b83be`
(round 3 record). The verifier resolves only the repositories on its allowlist, which does not include the evidence repository, so rows that
rest on its commits cite the first six characters of the id (shorter than the verifier's seven-character minimum, so it does not try to resolve them in BlarAI); each of the five ids above
was resolved with `git rev-parse` in the evidence repository on the date of this record. Those rows also name the file the commit changed.

## Disposition

R2-1 was fixed by a different means than the reviewer proposed: a version exemption in the name rule instead of renaming the five writers' output. Round 3 re-ran
the writers' formats against it and accepted it; the exemption's range limit (R3-5) is recorded. R3-1 is fixed in three places (doctrine line, checklist, test); round 4
(R4-4) found two structural layers already refuse a fast-forward of main in the real checkout, so the doctrine line is the third layer. The rows marked REJECTED are
recorded limits or information items, each with its argument and where the limit is written down.

```disposition
R1-1-sanitiser-deletes-upstream-references-before-the-local-rule | FIXED | d872ef8c and evidence repo d08272 (tools/sanitize.py) local replacements now run before the reference rule; the private 9P source re-sanitises byte-identical to main (round 2 verified), with a self-test case for a listed upstream number
R1-2-hand-grown-baseline-passes-and-a-bad-reference-fails-open | FIXED | d872ef8c the gate test runs the check against a reference, an unresolved ref exits 2 and names itself, a toggle test grows the baseline and expects failure; reference narrowed to the merge base by 470e8e6c
R1-3-reference-glued-to-a-word-is-spared | FIXED | d872ef8c a number glued to a word is a finding; only an allowlisted owner/repo slug passes
R1-4-name-rule-blind-to-2000-2099 | FIXED | d872ef8c the date rule needs a separator and a month 01 to 12, fourteen banked names listed; 470e8e6c adds the version exemption and PREFLIGHT section 3 states the remaining limits
R1-5-number-followed-by-letter-or-underscore-unseen | FIXED | d872ef8c the BlarAI lock takes a reference followed by a letter or underscore; the evidence repository's own copy of this rule is R2-6
R1-6-malformed-opt-in-fails-silently | FIXED | d872ef8c all six reviewed malformed forms now fail closed; the residual spellings found later are R2-3, R2-8 and R3-3
R1-7-heading-inside-a-fence-ends-the-marked-entry | FIXED | d872ef8c fences are skipped when looking for the next heading; 470e8e6c closes a fence only on its own character and length
R1-8-baseline-read-from-the-working-copy | FIXED | d872ef8c the baseline blob is read from the index; an untracked baseline no longer allows a finding
R1-9-checklist-overstates-what-the-locks-and-sanitiser-do | FIXED | d872ef8c docs/research/PREFLIGHT_RESEARCH_COMMIT.md corrected in all four sentences, the leak gate command given with its required flag
R1-10-evidence-docstring-and-commit-message-no-longer-match-the-code | FIXED | evidence repo d08272 (tools/sanitize.py docstring rules 5 and 6 rewritten, three to five digits in both patterns, self-test plants a five-digit number) and d872ef8c for the BlarAI side
R1-11-css-colours-and-ordinals-are-tracker-references | REJECTED | A bare three-digit number after the hash character cannot be told from a tracker number without a context rule that would also pass real references; the rule fails closed, the incidence in scope is zero, and the shape is recorded as a known false positive in the lock docstring and in checklist section 3 (d872ef8c).
R1-12-check-output-prints-numbers-the-mask-does-not-cover | FIXED | d872ef8c every run of four or more digits that is not a full date is masked in printed paths; tests test_masked_paths and test_check_output_masks_every_long_run
R1-13-gzip-utf16-and-ansi-readings-claimed-but-not-locked | FIXED | d872ef8c one planted case per reading in the test module
R1-14-top-level-probe-files-are-out-of-scope | REJECTED | The scope was fixed by the Lead Architect as the probe directories under tools/probes, the banked performance JSON and the checklist; widening it is a scope decision, not a defect, and the limit is written in the lock docstring and the checklist (d872ef8c).
R1-15-evidence-path-rule-refuses-version-port-and-build-numbers | FIXED | d872ef8c the docstring now says the trade-off holds for content only; the path rule stays as it was because it fails closed and the tracked tree has zero hits
R2-1-five-benchmark-harnesses-write-names-the-lock-refuses | FIXED | 470e8e6c a 2000 to 2099 run before a dot and a digit, or after ov or openvino and before an underscore and a digit, reads as a version; fourteen name entries leave the baseline; round 3 ran the five writers' name formats and all passed
R2-2-prose-mention-of-the-opt-in-key-is-a-gate-failure | FIXED | 470e8e6c only a key-shaped line counts as malformed; the reviews, a fragment and a governance sentence naming the word all pass
R2-3-underscore-spelling-of-the-key-silently-unscoped | FIXED | 470e8e6c the key may be spelled with a hyphen, underscore, space or nothing; test_key_spellings_between_the_words_all_parse
R2-4-reference-is-mains-tip-not-the-merge-base | FIXED | 470e8e6c merge base on a branch, the minimum of the last twenty baseline versions on main, an unresolved ref named; 22447ac3 adds the landing rule and its test
R2-5-three-digit-tracker-numbers-in-names-are-unseen | REJECTED | A rule on three-digit runs in names would refuse the hardware forms arc140v and uc0NN that the reviewer counted, while tracker numbers below 1000 predate 2026-07-20 and three-digit references in content are already findings; the limit (nine banked names, one live writer) is recorded with the date 2026-10-15 in the lock docstring and checklist section 3 (470e8e6c).
R2-6-evidence-gate-and-sanitiser-spare-numbers-glued-to-a-letter | FIXED | evidence repo f4ae73 (tools/leak_gate.py and tools/sanitize.py) the trailing word boundary became a not-followed-by-digit test in both patterns; round 3 re-ran the planted forms: removed by the sanitiser and refused by the gate
R2-7-fence-of-the-other-character-closes-a-fence | FIXED | 470e8e6c a fence closes only on its own character and at least its length
R2-8-utf16-or-mdx-document-carrying-the-opt-in-is-unscoped | REJECTED | The lock reads the opt-in only to widen scope beyond its three fixed roots, none of which depend on it, and no tracked file is affected; the limit is recorded with the date 2026-10-15 in the lock docstring and checklist section 3 (470e8e6c), and round 3 accepted it at LOW.
R2-9-unlisted-bare-upstream-number-removed-gate-cannot-see-the-loss | FIXED | 470e8e6c checklist section 2 and the sanitiser docstring (evidence repo d08272, tools/sanitize.py) require re-counting against the marker's per-file tracker count, which the sanitiser already prints
R2-10-short-hashes-and-hhmm-times-in-names-are-refused | FIXED | 470e8e6c both shapes added to the known fail-closed false positives in the lock docstring and checklist section 3; no code change was asked
R2-11-test-module-docstring-describes-the-round-1-lock | FIXED | 470e8e6c WHAT IS LOCKED rewritten to the five patterns, readings, reference, opt-in parsing, fences and masking
R2-12-add-existing-names-with-a-moved-base-ref-admits-a-new-name | FIXED | 470e8e6c the flag accepts only main's tip or the merge base as its base ref; the CLI refuses any other
R3-1-fast-forward-landing-turns-mains-gate-red | FIXED | 22447ac3 the no-ff landing rule in .claude/rules/identity.md names the baseline and the script, the checklist and lock docstring say the same, test_fast_forward_landing_fails_and_no_ff_landing_passes locks both; bf585851 regenerates the rules corpus that edit changed
R3-2-add-existing-names-output-refused-by-the-gate | FIXED | 22447ac3 a name entry for a path already tracked at the reference passes, a path new since the reference is refused, test_a_genuinely_new_name_entry_is_still_refused
R3-3-misspelt-key-or-toml-front-matter-silently-unscoped | REJECTED | Zero tracked files are affected and the three shapes (a typo in the key, a plural key outside a front matter, a TOML block) cannot be told from ordinary text without false positives on every document that discusses the lock; the limit is recorded with the date 2026-10-15 in the lock docstring and checklist section 3 (22447ac3).
R3-4-ordinary-documents-fail-as-malformed-opt-ins | REJECTED | The refusal fails closed, zero tracked lines are affected, the message names the scope word, and loosening the key-shape test is the opposite of R3-3; the three shapes are recorded as fail-closed false positives in the lock docstring and the full key-shaped definition is in checklist section 3 (22447ac3).
R3-5-version-exemption-spares-tracker-numbers-2000-to-2099 | FIXED | 22447ac3 and evidence repo 44fe7a (tools/leak_gate.py) the range limit is written into the lock docstring VERSION RULE, the checklist and the evidence gate docstring, as the reviewer asked; incidence is zero until the tracker crosses 2000
R3-6-shallow-clone-weakens-the-reference-and-empty-index-reads-ok | FIXED | 22447ac3 a shallow clone with a reference and an index holding no probe, performance or checklist file both exit 2 naming the cause; two new tests
R3-7-prose-outlived-the-code-and-a-lock-certifies-more-than-it-tests | FIXED | 22447ac3 the date rule sentence defers to the version rule, the checklist carries the full key-shaped definition, the harness test reads each writer's name template from its source and fails when one is missing; the residual is R4-2
R3-8-round-1-and-2-reviews-carry-the-operators-account-name | FIXED | feat/research-preflight the account name was replaced by hand with the home-folder variable in the review files before they were staged in the commit that carries this record; count_user_hits reads 0 on all four and scrub_public_identifiers.py --check exits 0
R4-1-doctrine-edit-left-the-generated-rules-corpus-stale | FIXED | bf585851 docs/governance/rules-corpus.yaml regenerated with scripts/extract_rules_corpus.py; test_rules_corpus.py passes again
R4-2-harness-name-lock-still-invents-the-version-value | REJECTED | The test now reads each writer's name template from source and fails on the two template mutations; a change in how a writer derives the version fails closed at that writer's first committed record, all five writers use the same derivation today, and the incidence is zero (round 4, mutations M1 and M2 pass only because the derivation is unchanged in practice).
R4-3-checklist-says-banked-files-may-only-fall | FIXED | bf585851 docs/research/PREFLIGHT_RESEARCH_COMMIT.md now states that a name entry may be added for a path already banked
R4-4-rounds-three-fast-forward-premise-the-doctrine-line-is-a-third-layer | REJECTED | Information item: the installed reference-transaction hook and the shell merge guard already refuse a fast-forward of main in the real checkout, so the doctrine line is the third layer, which is the point of defence in depth; it stays for clones without the hooks and nothing in the lock needs to change.
R4-5-environmental-failure-seen-only-in-the-worktree | REJECTED | Information item: two tests in test_doc_pointers_and_banners.py fail only because ADR-013 links resolve to the sibling devplatform folder from the real checkout and not from a worktree; the branch does not touch that ADR, and the standing gate in the real checkout is where the figure is taken.
```

## Honest limit of this record

The verifier checks the form of this record, not whether a fix is right. Rows that rest on evidence-repository commits cite a six-character id that the verifier does not resolve;
the five full ids in the header were resolved by hand. R3-3, R3-4, R2-5, R2-8 and R1-14 are accepted limits of the lock, written in its docstring with the date, and each can be
reopened by a later review; none has an incidence in the tracked tree today. The standing gate was not run by any of the four reviewers; the figure for this branch is taken separately.
