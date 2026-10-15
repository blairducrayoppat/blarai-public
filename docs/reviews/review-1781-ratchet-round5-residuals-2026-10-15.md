# Review: #1781, round-5 residuals of the identity ratchet (2026-10-15)

VERDICT: FAIL at 7c179900 (fix c864df44). One new fail-open in the legacy-shape skip (R1-1); the disposition and journal overclaim two locks (R1-2). Both fixes are small. R5-2 to R5-5 hold under execution; every new lock fails when its fix is reverted.

Reviewed `fix/1781-ratchet-round5-residuals` at 7c179900, off main fc5d2383 (current main; `git log -1 main` = fc5d2383). Read every byte of `git diff fc5d2383 7c179900` (10 files) and the "# Round 5 (2026-10-15)" section of `docs/reviews/review-1765-public-identifier-scrub-2026-10-14.md`. Execution ran in scratch clones under the reviewer's scratchpad: `r1781` (branch tip; local main rebuilt as 3e8fa63e fast-forwarded to `feat/1765-scrub-public-identifiers` 22231122) and `rmerge` (fc5d2383 with this branch merged `--no-ff`). The worktree was only read, apart from this file and one `--check` run. LOCALAPPDATA redirected for every pytest run. The payload was never executed. The operator name appears here only as `__USER__`.

## Findings, most severe first

### R1-1. MEDIUM. The legacy skip is a shape test, so a list-shaped version on main now reaches the silent FIRST_LANDING path
`scripts/scrub_public_identifiers.py:196-201` (`_is_legacy_list_shape`) and `:237-238`. The docstring says the skip is for "a version that predates the ratchet's counts", but the predicate is only "`files` is a list": no era bound, no element check. When every version in main's window is list-shaped (or deleted), `versions` is empty and the function falls through to the `--diff-filter=A` test; a branch that deletes and re-adds the baseline then gets FIRST_LANDING, which `ratchet_violations` treats as silent. Before this change, the same history was "not a readable baseline", a finding. It costs a silent pass of a grown baseline. Reaching it needs a main whose window holds only list-shaped versions, which main's own gate would also break on (`load_user_baseline` raises on a list).
Reproduced (fixture `atk1.py`): main commits `{"files": []}`; branch `git rm` the baseline, then re-adds `{"files": {"docs/new.md": 9}}`.
- branch script: `reference_baseline` -> `(None, 'the baseline first lands in this history; nothing earlier to compare with')`; `ratchet_violations(..., [], ...)` -> `[]`.
- main fc5d2383 script, same history: `(None, '77434b23e5:... is not a readable baseline')` -> `['ratchet: the branch comparison did not run: ...']`.
Also skipped as "legacy" though it is no historical schema: `{"files": [{"a": 1}]}` (main: not readable; branch: skipped, reference read from the other versions).
Incidence: 0. Main's first-parent window holds only dict versions (557 entries).
The same overclaim is in prose: the journal fragment says "any other unreadable version still fails closed", and the docstring says "the one silent case is FIRST_LANDING: ... the reference predates it". In this case the reference does not predate it.
Fix: skip a list-shaped version only when its elements are all strings and no dict-shaped version older than it is read. If the loop reads no dict version but skipped a list version, return the reason "main carries only legacy list-shape baselines" (a finding), never fall through to FIRST_LANDING. Correct the fragment and docstring sentences to match.

### R1-2. LOW. The disposition and journal say the R5-4 mutant fails 6 of 6 profiles; it fails 3 of 6
`docs/reviews/1781-ratchet-round5-residuals-disposition-2026-10-15.md` (R5-4 row), `docs/journal_fragments/2026-10-15_1781-ratchet-round5-residuals.md` ("fails all six"). The mutant (`{os.environ["USERPROFILE"]}{argv_tail("")}` in `payload_command`) breaks only the three profiles that end in a backslash. The other three reach the payload intact, so they cannot fail. The lock is sound and the record overstates it.
Reproduced (byte-preserving mutation in `r1781`): `3 failed, 11 passed`. The failures are `[C:\Users\someone\]`, `[C:\]` and `[C:\Users\someone\\]`.
Fix: write "fails the 3 trailing-backslash profiles of 6" in both places.

### R1-3. LOW. The R5-2 claim check compares strings, so an equivalent glob fails it
`tests/security/test_doctrine_rules.py:225`. `(word + "/**") not in rule.paths` rejects `docs/**/*`, which `doctrine_rules.glob_to_regex` matches on exactly the same paths as `docs/**` (probed: `docs/a.md`, `docs/reviews/x.md`, `docs/a/b/c.json`). The cost is a misleading "a narrower glob" failure on a legitimate frontmatter edit. Incidence: 0 (identity.md uses `docs/**`).
Fix: ask the delivery matcher itself. For each claimed directory, require `dr.path_matches(rule, f"{word}/x.md")` and `dr.path_matches(rule, f"{word}/a/b/x.md")`.

### R1-4. LOW (already on main, not introduced here). A top-level JSON list or `null` baseline in the window crashes the reader
`scripts/scrub_public_identifiers.py:189-193`. `_parse_baseline` does not catch `TypeError`, so `["a"]` or `null` raises instead of returning "not a readable baseline". It fails loud, not open. Main's script does the same.
Reproduced: `C ["a"] -> CRASH TypeError` and `C null -> CRASH TypeError`, with both scripts.
Fix: add `TypeError` to the `except` tuple.

## Attacked and not broken

- R5-1 fast-forward scenario. In `r1781`, with main fast-forwarded through 373e9685, main's script gives `(None, '373e968585:... is not a readable baseline')`. The branch script reads 557 entries and an empty reason (window: fe2e2dbd 557, ec11efd6 557, d51d7c72 558, 373e9685 LIST).
- A list version newer than dict versions (`{a:1}`, then a LIST version, then `{a:1,z:4}`): the reference is `{a:1}` and the growth stays visible.
- Other unreadable shapes stay findings: `{"files": {"a": "x"}}`, a string, a missing key, `null` files.
- R5-3: a 3 -> 5 raise reads "added to the baseline on this branch". Equal (3/3) and lowered (2/3) read "main dropped this file".
- R5-4: `payload_command` is the only builder. `run_arm.main` calls it at line 337, and the source scanner still covers an inline rebuild.
- R5-5: the HONEST LIMIT matches the code. The identity.md bullet is an imperative with a reason clause and `(#1781)`, no story. Corpus and gaps regenerated: 175 rules, 149 without enforcement.
- Toggle-offs, byte-preserving, each restored and checked with `cmp`. Legacy skip off fails `test_toggle_legacy_list_baseline...`. The fork condition off fails `test_toggle_main_dropped_message...`. The prefix match restored fails `test_delivery_claim_check_fires_when_a_surface_is_narrowed_to_a_subdirectory`. The payload mutant fails 3 tests.

## Runs

| what | where | result |
|---|---|---|
| test_no_host_identity_in_tree, test_containment_arm_launchers, test_doctrine_rules, test_doctrine_freshness | `r1781` at 7c179900, about 01:35 local, other agents testing | 166 passed in 184 s |
| test_rules_corpus | `r1781` | 40 passed |
| `scrub_public_identifiers.py --check` | worktree at 7c179900 / `rmerge` (`--no-ff` into fc5d2383) | 0 findings in 4,006 files, exit 0 / the same |
| verify_disposition.py | branch disposition | PASS 5/5 (the form only; R1-2 is in the row text) |

Not run: the full standing gate, any arm or payload, anything elevated.

## Merge read

Block on R1-1: this change introduces a fail-open in a fail-closed control, and the fix is a few lines plus a fixture. Block on R1-2: the disposition is the record the merge cites. R1-3 and R1-4 do not block; each fails loud or false-fails, never open. Merge with `--no-ff`.

# Round 2 (2026-10-15)

VERDICT: PASS at b0ecf677 (fix 4837ffac, disposition b0ecf677). R1-1 to R1-4 hold when run, and each fix's named lock fails with that fix reverted. Every list-shape path to FIRST_LANDING now ends in a named finding. Two LOW findings remain (R2-1, R2-2); neither touches the ratchet's verdict, and neither blocks.

Reviewed: `git diff 69c4db3d b0ecf677` (6 files), every byte. Execution ran in scratch clones: `tip` (b0ecf677, with a local `main` at fc5d2383) and `merge` (fc5d2383 with the branch merged `--no-ff`, merge 6c8a1396). LOCALAPPDATA was redirected for every pytest run, and mutations were byte-preserving and restored, checked with `cmp`. The worktree was only read, apart from this append and one `--check`.

## Round-1 fixes, re-verified

| finding | holds? | evidence |
|---|---|---|
| R1-1 | yes | The round-1 repro (main `{"files": []}`, branch deletes and re-adds `{"docs/new.md": 9}`) now reads "main carries only legacy list-shape baselines" and is a finding. With the `if skipped_legacy` return disabled, `test_toggle_list_shape_never_reaches_first_landing...` fails on the FIRST_LANDING reason. With the string-element check removed, the same test fails on `{"files": [{"a": 1}]}`. |
| R1-2 | yes | The R5-4 row and the fragment now say 3 of 6. |
| R1-3 | yes, with a lenient spare (R2-1) | `test_delivery_claim_check_accepts_an_equivalent_glob` passes. Restoring the exact-string test fails it. The narrowed `docs/reviews/**` lock still fails. |
| R1-4 | yes | `["a"]` and `null` read as "not a readable baseline". With `TypeError` removed, the R1-1 test fails with `TypeError` at `scrub_public_identifiers.py:191`. |

Hunt for any other path to FIRST_LANDING or a silent skip (fixture `atk3.py`):
- A main whose window holds only legacy versions (two string lists), then branch deletes and re-adds: finding.
- Legacy, then a deletion on main, then the branch adds: finding.
- Legacy, deletion, legacy, deletion: finding.
- Main never carried a baseline: FIRST_LANDING, the legitimate case.
- These list shapes between two dict versions are each "not a readable baseline": `["a", {"b":1}]`, `["a", 1]`, `[null]`, `[["a"]]`, a top-level string, `5`.
- `{"files": []}` between two dict versions is skipped, and the reference comes from the dict versions.

Window flush: an ungated growth on main followed by 19 list-shape versions makes the growth the reference. The same holds with 19 dict versions that carry the growth (F2 reproduced). This is the R5-5 horizon, reachable only by a fast-forward, so it is not new; before #1781 a list filler failed closed, now it costs the same as a dict filler.

## Round-2 findings

### R2-1. LOW. The claim check probes only files named `x.md`, so a glob limited to Markdown passes
`tests/security/test_doctrine_rules.py:225`. The test asks `dr.path_matches` about `docs/x.md` and `docs/a/b/x.md` only. The docstring says "matched, at any depth", which overclaims what two paths with one basename can test.
- Reproduced: with identity.md's `docs/**` swapped to `docs/**/*.md`, drift is `[]`, yet the rule does not deliver on `docs/data.json`.
- With `docs/**/x.md`, drift is also `[]`, and the rule delivers on almost nothing.
- Incidence: 0 (identity.md uses `docs/**`).
- Fix: require `dr.path_matches(rule, p)` for every tracked file under the claimed directory (`git ls-files <dir>/`). This checks the claim against the files that exist, not against a chosen name.

### R2-2. LOW. The journal fragment still describes the R5-2 check that R1-3 replaced
`docs/journal_fragments/2026-10-15_1781-ratchet-round5-residuals.md`, second paragraph. "it now requires `docs/**` itself" was true at c864df44. Since 4837ffac the check asks the matcher. The R5-2 disposition row cites c864df44, so it stands as history. The fragment describes the current state, so it is stale.
- Fix: change the sentence to say the check asks the delivery matcher whether every path under the directory is delivered.

## Runs (round 2)

| what | where | result |
|---|---|---|
| the four suites + test_rules_corpus | `tip`, 01:54 local, other agents testing | 206 passed, 2 failed. The two failures (`test_ratchet_holds_on_the_tree`, `test_check_mode_is_clean_on_the_tree`) read "main does not resolve", because the fresh clone had no local `main`; this is fail-closed by design. With `main` added at fc5d2383 both pass (2 passed in 86 s). |
| `--check` | worktree at b0ecf677; `merge` (`--no-ff` into fc5d2383, current main) | 0 findings in 4,008 files, exit 0, on both |
| verify_disposition.py | round-5 residuals 5/5; round-1 4/4 | PASS, PASS |

Not run: the full standing gate, any arm or payload, anything elevated.

## Merge read (round 2)

Nothing blocks. R2-1 is a lenient spare in a doctrine test, and R2-2 is one stale sentence; both are cheap to fix before merging. Merge with `--no-ff`.
