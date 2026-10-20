# Research pre-flight lock: adversarial review, round 3 (2026-10-15)

Reviewer: independent (not the author, not the round-1 or round-2 reviewer). Report only; nothing was fixed.

Tested at:
- BlarAI worktree `%USERPROFILE%/BlarAI-worktrees/research-preflight`, branch `feat/research-preflight`, commit `470e8e6c`
  (on `d872ef8c`, `25fa58b4`); working tree clean apart from the untracked round-1 and round-2 reviews.
- `%USERPROFILE%/windows-containment-evidence`, branch `fix/number-patterns-widen`, commit `f4ae730` (on `d08272e`), against
  `main` (`40a73e6`).
- BlarAI `main` is `2168ec96`, which IS the branch's merge base: main has not moved since the branch was cut, so there is no
  conflict to find and `git merge-tree` is trivial. The post-merge question is therefore not "does new main content pass" but
  "which merge shape is used" (finding R3-1).

Notation: "H" stands for the hash character. "The opt-in key" stands for the front-matter key and log-marker word the lock
parses; this file writes neither literally. A three-digit tracker number inside a file name is written `NNN`. Round-3
harnesses: `%USERPROFILE%/AppData/Local/Temp/claude/C--Users-__USER__-BlarAI/91386bce-adf7-42bc-9468-33ce534c1d6d/scratchpad/r3/`
(`clone/`, `ev/`, `shallow.py`; the attack harness is in the sibling folder `tracker-r3/` as `tracker_attack3.py` with its output `tracker_attack3.txt` and a copy `tracker_shallow.py`, because `r3/attack3.py` was overwritten by another review's fixture during this round); round-2 harnesses in `.../scratchpad/r2/` (`fresh.py`, `stale.py`,
`addnames.py`, `grow2.py`) were re-run unchanged against `470e8e6c`.

## Verdict: FAIL (0 BLOCKER, 1 HIGH)

## Round-2 findings, re-tested

| # | Round-2 finding | Status at `470e8e6c` / `f4ae730` | Evidence |
|---|---|---|---|
| R2-1 | Five benchmark harnesses write names the lock refuses | Fixed (by a version exemption, not by changing the writers) | `r2/fresh.py`: `kv_cache_sweep_ov<ver>_<ts>` and `vlm_perf_ov<ver>_<ts>` now `[]`. The five writers' format (`ov{safe_ov}_{ts}` with `safe_ov = version.split("-")[0].replace(".", "_")`) read at `benchmark_kv_cache_sweep.py:527-529`, `benchmark_prefill.py:142-144`, `benchmark_prefix_caching_ab.py:1248-1250`, `benchmark_spec_decode_ab.py:753-755`, `vlm_perf.py:111-113`; all pass. Residual: the lock test hard-codes the formats instead of reading the writers (R3-7); the exemption is a cheap masquerade for 2000-2099 (R3-5). |
| R2-2 | Prose mention of the key fails the gate | Fixed | `r2/stale.py`: the round-1 review, a journal fragment, a TEST_GOVERNANCE sentence, lower-case prose and a `.txt` note all `ok (0 finding(s))`. `opt_in_status()` on the untracked round-1 and round-2 reviews: `(False, [])`. New cost on other shapes: R3-4. |
| R2-3 | Underscore spelling of the key silently unscoped; test mandated it | Fixed | `test_key_spellings_between_the_words_all_parse` (hyphen, underscore, space, nothing, mixed case) passes; the malformed table now asserts the indented-underscore form fails. Residual of the same class: R3-3. |
| R2-4 | Reference is main's tip, not the merge base; growth on main invisible; blank ref message | Fixed on a branch and on a `--no-ff` main | `r2/stale.py`: stale branch, untouched baseline, against main: `ok`. `r2/grow2.py`: grown baseline on a branch FAILS; grown baseline landed on main FAILS; `--reference-ref no-such-ref` prints `the reference 'no-such-ref' does not resolve ...` (exit 2). But: a fast-forward landing of THIS branch turns main red (R3-1, reproduced independently by `r2/grow2.py` line "1 gate after merge (main=tip): FAILED"); a depth-1 clone is fail-open (R3-6). |
| R2-5 | Three-digit tracker numbers in names unseen; docstring said none | Partly fixed | Docstring first paragraph and REMAINING LIMITS, and PREFLIGHT section 3, now record the limit. The writer `scripts/measure_807_stage5_reembed.py:299` still writes `pgov_stage5_reembed_NNN_...` and is unchanged; `r2/fresh.py` B still `[]`. Recorded, open; not re-raised as a new finding. |
| R2-6 | Evidence gate and sanitiser spare `H` numbers glued to a letter or underscore | Fixed | `r3/ev/raw3`: sanitised output `a a end`, `b _fix end` (`{'tracker': 2}`); `leak_gate.py --tree` on the raw tree: `HIT ... tracker-ref` x2; on the sanitised tree `0 hit(s)`. Self-test carries both forms. |
| R2-7 | Mixed fence characters end an entry early | Fixed | `r2/fresh.py` E: `tracker-ref x1 ... line(s) [7]` (was `[]`); E2 (four backticks nesting three) still right; F (unclosed fence) still fails closed. |
| R2-8 | UTF-16 or `.mdx` opt-in silently unscoped | Recorded, not fixed | `r2/fresh.py` D (UTF-16LE) and H (`.mdx`) still `[]`; the limit is now in the docstring REMAINING LIMITS and PREFLIGHT section 3. Accepted as a recorded limit at LOW. |
| R2-9 | Unlisted bare upstream number removed; gate blind to the loss | Fixed (documented) | `sanitize.py` docstring rule 6 and PREFLIGHT section 2 name the re-count against the marker's per-file `tracker` count; the marker already records that count per file and rule. 9P: `{'tracker': 27, 'fixture': 1262, 'local': 375}` on main and branch. |
| R2-10 | Short hash and HHMM in names refused | Fixed (documented) | Docstring KNOWN FAIL-CLOSED FALSE POSITIVES and PREFLIGHT section 3; `r2/fresh.py` C and J still refuse (as documented). |
| R2-11 | Test module docstring described the round-1 lock | Fixed, one overclaim left | WHAT IS LOCKED now lists five patterns' worth of controls, readings, reference, fences, masking. Residual overclaim in R3-7. |
| R2-12 | `--add-existing-names` with a moved base ref admits a new name | Fixed | `r2/addnames.py`: `--base-ref HEAD --add-existing-names` -> `needs --base-ref to be main's tip or the merge base with main, not 'HEAD'` (exit 1); default base -> `findings in a file not tracked at main`. But the flag's legitimate output is now always refused by the gate (R3-2). |

## Findings

### R3-1. HIGH: a fast-forward landing of this branch turns main's standing gate red, and nothing tells the merger to use `--no-ff`

- File: `scripts/research_tracker_lock.py:212` `reference_baseline()` (main-line branch: pointwise minimum over the last 20
  baseline versions on HEAD's first-parent line); `tests/security/test_research_files_carry_no_tracker_numbers.py`
  `test_real_index_passes_check_against_main`.
- What is wrong: the baseline ROSE inside this branch (`25fa58b4` lists `tracker-ref: 2` for
  `docs/performance/llamacpp_vs_openvino_NNN_2026-07-10.json`; `d872ef8c` and `470e8e6c` list 4, after the round-1 rule that
  counts word-glued references), so if the branch lands as a fast-forward all three versions sit on main's first-parent line,
  the minimum is 2, and main's own baseline "rose against the reference".
- Scenario: main has not moved since the fork (`2168ec96` = merge base), so a plain `git merge feat/research-preflight` on main
  fast-forwards. The post-merge gate fails on main, and stays failing until 20 more baseline versions land or someone edits a
  banked performance record to remove two references. Main's history shows direct first-parent commits are routine
  (`c8e19a4d`, `b73a2dd6`, `033d4dc6` ...), and `merge.ff` is unset in repo and global config. The only `--no-ff` rule in
  doctrine (`.claude/rules/identity.md`) names the identity ratchet's three files, not this lock's; the lock docstring,
  PREFLIGHT and the test say nothing.
- Reproduced (scratch clone of the real repo, `r3/clone`):
  ```
  git switch -c simff 2168ec96 ; git merge --ff-only feat/research-preflight       -> 470e8e6c
  research_tracker_lock.py --check --reference-ref simff
    docs/performance/llamacpp_vs_openvino_NNN_2026-07-10.json: baseline count for 'tracker-ref' rose against the reference
    research tracker lock: FAIL (1 finding(s))
  pytest ...test_research_files_carry_no_tracker_numbers.py -k real   -> 1 failed, 3 passed
  git log --first-parent -- scripts/research_tracker_baseline.json   -> 470e8e6c d872ef8c 25fa58b4
  ```
  Control, same clone: `git merge --no-ff` -> merge `de23e530`; `--check --reference-ref main` -> `ok (0 finding(s))`; the full
  targeted file on that merged main: 176 passed. Detached HEAD at the merged main: `ok`.
- Incidence: this merge only (the rise happened while the baseline was new on the branch; `write_baseline` cannot raise an
  existing baseline, so later branches do not recreate it).
- Fix: land this branch with `git merge --no-ff`, and add `scripts/research_tracker_baseline.json` and
  `scripts/research_tracker_lock.py` to the doctrine's `--no-ff` landing rule (the one that already names the identity ratchet's
  files) in the same change, so the requirement is where the merger reads it.

### R3-2. MEDIUM: the output `--add-existing-names` exists to produce is refused by the gate, on the branch and on main

- File: `scripts/research_tracker_lock.py:558` `write_baseline()` (the flag) against `reference_violations()` and
  `reference_baseline()` (names must be in the merge-base version on a branch, in EVERY version of the window on main).
- What is wrong: the flag's sole purpose is to list name findings of already-banked files after a rule newly catches them, which
  by construction adds a name the reference version lacks, so `--check --reference-ref main` (the gate) always fails it; on main
  it keeps failing until 20 baseline versions have passed.
- Scenario: the next tightening of the name rule (rounds 1 and 2 each tightened it; this branch itself needed the 14-name case)
  is written with the documented tool, `--check` passes, and the gate goes red with "baseline gained a name entry"; the only way
  through is renaming banked records, which neither the docstring nor PREFLIGHT says.
- Reproduced (`tracker-r3/tracker_attack3.py` A; main holds a baseline that predates a name finding):
  ```
  write --add-existing-names --base-ref main:          (0, ['baseline written: 0 content file(s), 1 name file(s)'])
  branch: --check:                                     (0, ['research tracker lock: ok (0 finding(s))'])
  branch: --check --reference-ref main (the gate):     (1, ['tools/probes/a/run_NNNN.py: baseline gained a name entry against the reference', ...FAIL])
  main after --no-ff merge: --check --reference-ref main: (1, [... 'baseline gained a name entry against the reference', ...FAIL])
  ```
  `test_write_baseline_names_need_the_flag_once_a_baseline_exists` exercises the flag but never runs the gate's reference on
  its output, so the suite certifies a path the gate refuses.
- Incidence: 0 today (no baseline on main yet); certain at the next name-rule tightening.
- Fix: `reference_violations()` accepts a name entry missing from the reference when the path was tracked at the reference
  commit (a banked file newly caught), and refuses it only for a path new since the reference; add a test that runs
  `--check --reference-ref main` on the flag's output on a branch and on a `--no-ff` main.

### R3-3. LOW: an opt-in with a misspelt key, or TOML front matter, silently leaves the file unscoped

- File: `scripts/research_tracker_lock.py:117` `_KEY_SHAPED_RE`, `:285` `_front_matter_span()`, `opt_in_status()`.
- What is wrong: key-shape needs the exact two words and a colon, and front-matter lines are inspected only for the key word, so
  a typo in the key itself, a plural key outside a front matter, or a `+++` TOML block is neither opted in nor malformed: the
  round-1 finding-6 class (the author believes the file is locked; it is not).
- Reproduced (`tracker-r3/tracker_attack3.py` B; each body carries `H1406`):
  ```
  key misspelt (missing letter) in --- front matter   []
  key plural, outside front matter                     []
  TOML front matter (+++, key = "value")              []
  ---- opener and misspelt key                         []
  fm control (valid)                                   ["docs/research/n.md: pattern 'tracker-ref' x1 exceeds the allowed 0 at line(s) [4]"]
  ```
- Incidence: 0 tracked files.
- Fix: also treat as key-shaped any line, inside a leading `---` or `+++` block or at the start of a line outside a fence,
  that carries the VALUE word (tracker and free with `-`, `_`, a space or nothing between) and did not parse as the opt-in.

### R3-4. LOW: ordinary documents fail as malformed opt-ins (key-shaped false positives)

- File: `scripts/research_tracker_lock.py:117` `_KEY_SHAPED_RE` (the two words with a space allowed, then a colon, any value)
  and `opt_in_status()` (any front-matter line naming the words).
- What is wrong: the space spelling makes the plain English phrase a key, so a line opening "Research scope: ..." is a gate
  failure in any tracked `.md`/`.txt`/`.rst`, as are a front-matter title or tag naming the words, a 4-space indented code
  block in Markdown and an `.rst` code-block (rst has no backtick fences).
- Reproduced (`tracker-r3/tracker_attack3.py` C), each a `malformed-opt-in` finding:
  ```
  'Research scope: GPU decode only.' line (.md)      line(s) [3]
  front matter 'title: Research scope of the decode study'   line(s) [2]
  front matter 'tags: [<key>]'                        line(s) [2]
  4-space indented code block in .md                  line(s) [3]
  .rst code-block example                             line(s) [3]
  'Research Scope: Lunar Lake only' (.txt)            line(s) [1]
  ```
- Incidence: 0 tracked lines (`git grep -i -E "^[ \t]*research[-_ ]?scope[ \t]*:"` over `.md/.txt/.rst/.markdown` finds only
  PREFLIGHT's own opt-in). Fails closed; cost is a refused commit with a message that says "the scope word is present".
- Fix: a line is key-shaped only when the value after the colon begins with the value word (tracker and free, any separator),
  and inside front matter only when the text before the colon is the key; a 4-space-indented line is not key-shaped.

### R3-5. LOW: the version exemption lets a tracker number from 2000 to 2099 pass in a name, and this limit is not recorded

- File: `scripts/research_tracker_lock.py:123` `_VERSION_AFTER_RE` / `_VERSION_OV_RE`, `_is_version()`;
  `windows-containment-evidence/tools/leak_gate.py:155` (same patterns).
- What is wrong: a tracker number of 2000-2099 written before `.` and a digit, or after `ov`/`openvino` and before `_` and a
  digit, is a "version", passes, and prints unmasked; REMAINING LIMITS records the equivalent date masquerade but not this one,
  and the VERSION RULE's "Nothing looser" reads as if no tracker number can use it.
- Reproduced (`tracker-r3/tracker_attack3.py` D; evidence gate on `r3/ev/raw3`):
  ```
  tools/probes/fix_2045.1/run.py                   []
  docs/performance/rec_2045.0_2026-10-15.json      []
  docs/performance/rec_ov2045_1_2026-10-15.json    []
  docs/performance/rec_openvino2045_9.json         []
  control rec_2045_2026-10-15.json                 name-number finding
  control rec_1845.1.json                          name-number finding
  evidence leak_gate --tree with runs/fix_2045.1/ and rec_ov2045_1.json: 0 path hits
  ```
  Exactly as narrow as claimed in SHAPE (`ov1406_2`, `run_2026`, `2026_2`, `xov2026_2`, `1845.1` stay findings), but not in
  RANGE: it spares the whole 2000-2099 tracker range at the cost of one `.0` or an `ov` prefix.
- Incidence: 0 (the tracker is below 2000 today; it will cross it).
- Fix: record it in REMAINING LIMITS (lock docstring and the evidence gate docstring) and PREFLIGHT section 3: "a tracker number
  from 2000 to 2099 written as a version (`NNNN.<digit>`, `ov<NNNN>_<digit>`) reads as a version and is not seen".

### R3-6. LOW: a shallow clone silently weakens the main-line reference, and the CLI says `ok` for an empty index

- File: `scripts/research_tracker_lock.py:212-223` `reference_baseline()` (the "(shallow clone?)" error is only reached when
  `merge-base --is-ancestor` errors) and `check()` (no non-empty-scope guard; the guard lives only in the test file).
- What is wrong: in a depth-1 clone of a main that carries an ungated growth, HEAD is trivially an ancestor of main, the window
  holds one version (the grown one), and the reference passes; and `--check` on a repository whose index is empty (a failed
  checkout) or has no research files prints `ok (0 finding(s))`.
- Reproduced (`tracker-r3/tracker_shallow.py`, then by hand):
  ```
  full clone, grown main, --reference-ref grownmain:  FAIL ('rose against the reference')
  depth-1 clone (core.longpaths), is-shallow=true, 4068 files in index, --reference-ref main:  ok (0 finding(s))  exit 0
  clone whose checkout failed (index 0 files), --check:   ok (0 finding(s))  exit 0
  fresh empty git repo, --check:                          ok (0 finding(s))  exit 0
  ```
- Incidence: 0 (the gate runs in the real checkout, where `test_real_scope_is_not_empty` covers the empty case).
- Fix: `reference_baseline()` raises LockError when `git rev-parse --is-shallow-repository` is `true`; `check()` raises when the
  scan finds none of the probe, perf and preflight kinds, so the CLI and the test agree.

### R3-7. LOW: prose that outlived the code, and one lock that certifies more than it tests

- `scripts/research_tracker_lock.py:22-23` (DATE RULE) still says "Every other four-digit run is a finding: ... a version form
  (``2026.4``) ... included", which the VERSION RULE a few lines below now contradicts (`2026.4` passes; masked output prints it).
- `docs/research/PREFLIGHT_RESEARCH_COMMIT.md` section 3 defines key-shaped as "the key word and a colon at the start of a line,
  outside a code fence", omitting the two other key-shaped forms the code enforces (the `<!--` form and any front-matter line
  naming the words), so an author reading it cannot predict R3-4's front-matter refusals.
- `tests/security/test_research_files_carry_no_tracker_numbers.py:18` claims "the five benchmark harnesses' own name formats pass",
  but `HARNESS_NAMES` (`:717`) is a hand copy; a writer that changes its format (for example keeping the build suffix) is not
  seen. Round 2's fix asked for the names to be built from the writers.
- Reproduced: read against behaviour (`tracker-r3/tracker_attack3.py` D shows `2026.4`-shaped names passing).
- Fix: rewrite the DATE RULE sentence to defer to the VERSION RULE; give PREFLIGHT the full key-shaped definition; have the test
  extract each writer's f-string (`ov{safe_ov}_{ts}`) from the five scripts' source and fail when one is not found.

### R3-8. LOW: the round-1 and round-2 review files carry the operator's account name; committing them as the disposition record fails the identity ratchet

- File: `docs/reviews/research-preflight-review-round1-2026-10-15.md`, `...-round2-2026-10-15.md` (untracked).
- What is wrong: both write home paths with the account name; a new file carrying it fails `scrub_public_identifiers.py --check`
  and the identity lock in the gate.
- Reproduced: `identity_lock.count_user_hits()` on the two files: 5 and 4.
- Incidence: 2 of the 2 earlier review files for this branch.
- Fix: before staging them, write `%USERPROFILE%` (or `__USER__`) for the account name by hand, as this file does.

## What I attacked and could not break

- Merge with main: main is the merge base; the `--no-ff` merge passes `--check --reference-ref main` and all 176 targeted tests
  on the merged tip; a detached HEAD at the merged main passes; the worktree passes (branch path).
- Baseline honesty: at the branch the reference check is vacuous (no baseline at the merge base), so its honesty rests on
  regeneration: `--write-baseline --base-ref 2168ec96` in a clone at `470e8e6c` rewrites the committed file with no content diff
  (117 content files, 14 name files).
- Branch reference: a stale branch whose main lowered a count passes; a branch growth fails; a growth landed on a `--no-ff` main
  fails; an unresolved ref exits 2 and names itself.
- Version exemption shape: `ov1406_2`, `run_2026`, `2026_2`, `xov2026_2`, `ov2026-2`, `1845.1`, `ov2026` (no underscore-digit)
  are all findings in both the lock and the evidence gate; the a-2 / a-8 offsets cannot borrow an `ov` from a different run
  (the run would not be standalone).
- Fences: tilde around backticks, four backticks around three, info strings with a backtick (not a fence), unclosed fences (fail
  closed), a marker inside a fence (fails closed by widening).
- Key-shaped: prose, inline code, list items, blockquotes and fenced examples pass; the six round-1 typo forms and the BOM-before
  marker still fail closed.
- Evidence repository at `f4ae730`: `--self-test` 0 failures; `--tracked` 153 files, 0 hits; the 9P source re-sanitised with
  main's (`40a73e6`) and the branch's sanitiser gives byte-identical trees (`diff -r` clean), both
  `{'tracker': 27, 'fixture': 1262, 'local': 375}`, and the `runs/` files are byte-identical to the published folder (the README
  differs only by the hand edit PROVENANCE records).

## Suites run (all at `470e8e6c` unless stated)

- `LOCALAPPDATA=<scratch> .venv python -m pytest tests/security/test_research_files_carry_no_tracker_numbers.py -q`: 176 passed.
- `LOCALAPPDATA=<scratch> .venv python -m pytest tests/security/ -m "not hardware and not winui and not slow" -q -k "tracker or identity or public_snapshot or doctrine"`:
  512 passed, 2862 deselected (377 s).
- `scripts/research_tracker_lock.py --check` and `--check --reference-ref main` in the worktree: `ok (0 finding(s))`, exit 0.
- Scratch merges of the real repository: `--no-ff` merge `de23e530`: targeted file 176 passed; fast-forward to `470e8e6c`:
  `-k real` 1 failed, 3 passed.
- Evidence repository at `f4ae730`: `tools/leak_gate.py --self-test` (0 failures), `--tracked` (153 files, 0 hits), 9P re-sanitise
  byte identity (above).
- The standing gate was not run.

## Merge read

Block on R3-1 until the landing is `git merge --no-ff` and the requirement is written where the merger reads it: a plain merge
fast-forwards today and leaves main red for up to 20 baseline versions. R3-2 should land in this change or carry a deferral
with an observable predicate (the next name-rule tightening), because the suite currently certifies a tool path the gate
refuses. R3-3 to R3-8 do not block: R3-4 and R3-6 fail closed or are covered by the test in the real checkout, R3-3 and R3-5
are unrecorded wrong spares with zero incidence today, R3-7 is prose, and R3-8 is a staging step for the review files.
