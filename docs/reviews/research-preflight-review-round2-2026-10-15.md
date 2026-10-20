# Research pre-flight lock: adversarial review, round 2 (2026-10-15)

Reviewer: independent (not the author, not the round-1 reviewer). Report only; nothing was fixed.

Tested at:
- BlarAI worktree `%USERPROFILE%/BlarAI-worktrees/research-preflight`, branch `feat/research-preflight`, commit `d872ef8c`
  (round-1 fixes on `25fa58b4`; working tree clean apart from the untracked round-1 review).
- `%USERPROFILE%/windows-containment-evidence`, branch `fix/number-patterns-widen`, commit `d08272e` (on `4f10187`, `2bd95ed`),
  against `main` (`40a73e6`).

Notation: "H" stands for the hash character (`H1786` is a hash followed by those digits). "The opt-in key" stands for the
front-matter key and log-marker word the lock parses; this file writes neither literally. Round-2 harnesses live in
`%USERPROFILE%/AppData/Local/Temp/claude/C--Users-__USER__-BlarAI/91386bce-adf7-42bc-9468-33ce534c1d6d/scratchpad/r2/`
(`grow2.py`, `stale.py`, `fresh.py`, `addnames.py`, `ev/`); round-1 harnesses in `.../scratchpad/rt/` were re-run unchanged.

## Verdict: FAIL (0 BLOCKER, 1 HIGH)

## Round-1 findings, re-tested

| # | Round-1 finding | Fixed? | Evidence (at `d872ef8c` / `d08272e`) |
|---|---|---|---|
| 1 | Sanitiser deletes upstream refs before the local rule | Yes | Local rule now runs before the reference rule. Re-sanitising the private 9P source with main's and the branch's sanitiser gives byte-identical trees (`diff -r` clean), both `{'tracker': 27, 'fixture': 1262, 'local': 375}`, equal to the published marker counts. Self-test gains the listed-upstream case. Residual: finding R2-9. |
| 2 | Hand-grown baseline passes; bad ref fails open | Yes, on branches | `grow2.py`: grown baseline on a branch off a main that holds the baseline makes `test_real_index_passes_check_against_main` FAIL; `--reference-ref no-such-ref` exits 2. Toggle test present. Residual: finding R2-4. |
| 3 | Reference glued to a word is spared | Yes | `probe.py`: `BlarAIH1786`, `ticketH1786`, `issueH1786`, `PRH1786`, `x_H1786` each count 1. |
| 4 | Name rule blind to 2000-2099 | Yes | `run_2001.py`, `2050_probe/` now findings; 14 banked names listed; PREFLIGHT section 3 states the remaining limits. New cost: finding R2-1. |
| 5 | `H` number followed by letter/underscore unseen | Yes (BlarAI lock) | `H1786a`, `H1786_fix` count 1. The evidence repository still spares them: finding R2-6. |
| 6 | Malformed opt-in fails silently | Partly | All six round-1 forms now parse (`probe2.py`: each 1). Still silent: underscore spelling of the key (R2-3), UTF-16 file (R2-8). New false positive: R2-2. |
| 7 | `## ` inside a fence ends the entry | Yes for uniform fences | backtick and tilde fences handled; mixed fence characters still break it: R2-7. |
| 8 | Baseline read from the working copy | Yes | `unstaged.py`: untracked baseline no longer allows the finding (`exceeds the allowed 0`). |
| 9 | PREFLIGHT overstates | Yes | Section 2 now describes the local-first order and the 2000-plus name limit; `leak_gate.py --staged`/`--tree` given; section 3 states the date rule, its limits and the full scope list. |
| 10 | Evidence docstring/commit stale; five digits | Yes | Rules 5-6 rewritten; `d08272e` message corrects the range; sanitiser and gate both take three to five digits; self-test plants `H23456`. |
| 11 | CSS colour / ordinal false positive | Accepted | Recorded as a known fail-closed false positive in the lock docstring and PREFLIGHT section 3. |
| 12 | Printed paths unmasked | Yes | `out.py`: `y_NNNN`, `x_NNNN`; `test_masked_paths` and `test_check_output_masks_every_long_run`. |
| 13 | gzip/UTF-16/ANSI readings unlocked | Yes | Three new tests plant one case each. |
| 14 | Top-level probe files out of scope | Accepted | LA-fixed scope; recorded in docstring and PREFLIGHT. |
| 15 | Path rule refuses version/port numbers; docstring | Yes | Docstring now says the trade-off holds "in content"; path rule unchanged (fails closed). |

## Findings

### R2-1. HIGH: five live benchmark harnesses write record names the lock now refuses

- File: `scripts/research_tracker_lock.py` `_is_year_of_date()` / `name_number_hits()`; writers
  `scripts/benchmark_kv_cache_sweep.py:529`, `scripts/benchmark_prefill.py:144`, `scripts/benchmark_prefix_caching_ab.py:1250`,
  `scripts/benchmark_spec_decode_ab.py:755`, `scripts/vlm_perf.py:113`.
- What is wrong: each harness names its record `docs/performance/<name>_ov<version with dots as underscores>_<timestamp>.json`;
  the version's year followed by `_2` is not a date, so every new record from these harnesses is a name finding, and the
  writers were not changed.
- Scenario: the next prefill or KV-cache sweep run writes its record, the performance rule requires committing it at the time,
  and the standing gate goes red on an ordinary measurement. The only remedy offered is a hand rename, every run.
- Reproduced (`r2/fresh.py`):
  ```
  A harness name kv_cache_sweep_ov<ver>: ["docs/performance/kv_cache_sweep_ovNNNN_2_1_0_2026-10-15_12-00-00.json: pattern 'name-number' in the file's own name"]
  A harness name vlm_perf_ov<ver>:       ["docs/performance/vlm_perf_ovNNNN_2_1_0_2026-10-15_12-00-00.json: pattern 'name-number' in the file's own name"]
  ```
- Incidence: 14 of the 204 banked performance JSON names have this form (all 14 now baselined); 5 writers produce it.
- Fix: in the same change, the five writers drop the version from the file name (it is already recorded in the JSON content);
  add a lock test that builds each writer's output name from its format string and asserts the lock passes it.

### R2-2. MEDIUM: any prose mention of the opt-in key word in a tracked document is a gate failure

- File: `scripts/research_tracker_lock.py` `scan_index()` (`names_scope_word` branch) and `malformed_log_lines()`.
- What is wrong: the word itself anywhere in any tracked `.md`/`.markdown`/`.txt`/`.rst` file (case-insensitive) that is not
  opted in is a finding, so ordinary documents that discuss the lock fail.
- Scenario: the round-1 review on disk, committed as the disposition record, fails the gate; so does the journal fragment for
  this ship, a TEST_GOVERNANCE row, or a PERFORMANCE_LOG sentence describing which entries are marked.
- Reproduced (`r2/stale.py`, staged in a clone of `d872ef8c`):
  ```
  round-1 review staged:             (1, ["docs/reviews/r1.md: pattern 'malformed-opt-in' ..."])
  journal fragment discussing lock   (1, [... 'malformed-opt-in' ...])
  plain mention in TEST_GOVERNANCE   (1, [... 'malformed-opt-in' ...])
  lower-case word in prose           (1, [... 'malformed-opt-in' ...])
  a .txt note                        (1, [... 'malformed-opt-in' ...])
  ```
- Incidence: 1 of 1 review documents written for this branch (the untracked round-1 review) would fail on commit; 0 tracked
  files today.
- Fix: only a KEY-SHAPED line counts as malformed: a line, outside a fenced code block, that starts (after indentation) with
  the key word followed by optional spaces and a colon, or with `<!--` followed by the key word. Prose and inline-code
  mentions pass. Keep the round-1 typo forms as tests.

### R2-3. MEDIUM: the key spelt with an underscore silently leaves the file unscoped, and a test mandates it

- File: `scripts/research_tracker_lock.py` `_SCOPE_WORD_RE`; `tests/security/test_research_files_carry_no_tracker_numbers.py`
  `test_malformed_opt_in_fails_closed` (the underscore case asserts `got is None`).
- What is wrong: the scope-word search matches only the hyphenated spelling, so the commonest YAML-key spelling (underscore)
  is neither opted in nor malformed: the author believes the file is locked and it is not. This is round-1 finding 6's class.
- Reproduced: the author's own test case (`"---\n<key with underscore>: tracker-free\n---\n"` yields no result for the file).
- Fix: the scope-word regex takes `-`, `_`, a space or nothing between the two words; flip that test to assert malformed.

### R2-4. MEDIUM: the reference is main's tip, not the merge base: a stale branch fails, and growth that reaches main is invisible

- File: `tests/security/test_research_files_carry_no_tracker_numbers.py` `test_real_index_passes_check_against_main`;
  `scripts/research_tracker_lock.py` `check()`.
- What is wrong (a): when main lowers a count (the ratchet working), every branch forked before that, which never touched the
  baseline, now reads as "rose against the reference".
- What is wrong (b): on main itself the reference is the commit under test, so a grown baseline that lands on main (a merge
  whose branch gate was not run) passes the post-merge gate and becomes the new reference.
- Reproduced (`r2/stale.py`, `r2/grow2.py`):
  ```
  stale branch, untouched baseline, --reference-ref main: (1, ["...llamacpp_vs_openvino_NNN_...: baseline count for 'tracker-ref' rose against the reference", 'FAIL (1 finding(s))'])
  same, against merge-base:                               (0, ['ok (0 finding(s))'])
  B grown on main, gate on main:                          4 passed
  ```
- Also seen: in a single-branch clone (no local `main`) the gate test fails with exit 2 and the message
  `git rev-parse failed: ` (blank; `--quiet` suppresses stderr). Fail-closed, but the message does not name the ref.
- Fix: the gate test compares against `git merge-base HEAD main` when HEAD is not main, and against every baseline version on
  main's first-parent history (the identity lock reads the last 20) when it is; the LockError names the unresolved ref.

### R2-5. MEDIUM: three-digit tracker numbers in names are unseen; a live writer emits one; the docstring says names carry none

- File: `scripts/research_tracker_lock.py` module docstring, first paragraph ("no file or folder NAME embeds one") vs
  `_NUM4_RE` (four digits only); writer `scripts/measure_807_stage5_reembed.py:299`.
- What is wrong: content `H` references of three digits are findings, but the same number in a name is not, and neither the
  docstring's REMAINING LIMITS nor PREFLIGHT section 3 records it.
- Reproduced (`r2/fresh.py`): `B 3-digit tracker in name (writer measure_807): []`.
- Incidence: 9 banked in-scope performance names carry a three-digit tracker number (the `hybrid_vs_vector`, `llamacpp_*`,
  `mem_reclaim_*`, `pgov_stage5_reembed_*` and `preference_contradiction` records); the hardware forms `arc140v` and `uc0NN` would
  be false positives for a three-digit rule.
- Fix: record the limit (three-digit numbers in names are not seen, with the date and the banked count) in the docstring and
  PREFLIGHT section 3, correct the first paragraph, and change the `measure_807` writer to drop the number from its name.

### R2-6. MEDIUM: the evidence repository's gate and sanitiser spare `H` numbers followed by a letter or underscore

- File: `windows-containment-evidence/tools/leak_gate.py` `TRACKER_RES["tracker-ref"]` and `tools/sanitize.py`
  `TRACKER_REF_RE` (both end in `\b`).
- What is wrong: `H2894a` and `H2895_fix` survive the sanitiser and pass the gate, while the BlarAI lock (fixed in round 1)
  refuses them; the public repository's last control is the more lenient one.
- Reproduced (`r2/ev/raw2`, sanitise then `leak_gate.py --tree`): output keeps `a H2894a end` and `b H2895_fix end`; the gate
  reports only `HIT runs/x.json:7 tracker-ref` (the word-glued line) and `1 hit(s)`. Unless the number is in the local file's
  `tracker_numbers` list, nothing sees it.
- Incidence: 0 in the evidence tree (`grep -rE 'H[0-9]{3,5}[A-Za-z_]'` over evidence, docs, tools: no text hits).
- Fix: replace `\b` with `(?![0-9])` in both patterns (the sanitiser then removes, the gate refuses); add both forms to the
  self-test refuse list.

### R2-7. LOW: a fence of the other character inside a fence closes it; a later `## ` ends the entry early

- File: `scripts/research_tracker_lock.py` `marked_entries()` / `_FENCE_RE` (toggles on any ``` or ~~~ line).
- Reproduced (`r2/fresh.py`): marker, `## Entry`, `~~~markdown`, a ``` line, `## step`, `~~~`, then a leaked `H1786`:
  `E tilde fence containing backticks: []`. (A four-backtick fence nesting three-backtick lines happens to come out right.)
  An unclosed fence widens the entry to the end of the file (fails closed: `F unclosed fence widens` reports an older entry).
- Fix: track the opening fence's character and length; close only on the same character with at least that length (CommonMark).

### R2-8. LOW: a UTF-16 (or `.mdx`) document carrying the opt-in is silently unscoped

- File: `scripts/research_tracker_lock.py` `has_tracker_free_front_matter()` (UTF-8 decode) and `names_scope_word()` (raw bytes);
  `FRONT_MATTER_SUFFIXES`.
- Reproduced (`r2/fresh.py`): `D UTF-16LE fragment w/ BOM: []` against `D UTF-8 control: [... 'tracker-ref' x1 ...]`;
  `H .mdx opt-in: []`. Windows PowerShell 5.1 redirection writes UTF-16LE.
- Fix: run the front-matter parse and the scope-word search over every `identity_lock.views` reading; a text file whose
  suffix is not in the list but whose front matter carries the key is malformed.

### R2-9. LOW: an unlisted bare upstream number is now removed by contract; the gate cannot see the loss

- File: `windows-containment-evidence/tools/sanitize.py` docstring rule 6 and the new self-test ("an unlisted one is removed").
- What is wrong: round 1 asked to keep the old contract (leave unlisted numbers for the gate); the author changed the contract to
  removal and documented it. Privacy-safe, but an upstream citation the local file does not list disappears and the gate
  passes; only the marker's tracker count and the PREFLIGHT re-count rule stand between it and a published record that lost a
  citation.
- Reproduced (`r2/ev/raw2`): `e bare upstream H2125 end` comes out `e bare upstream end`; gate does not report it.
- Fix: the sanitiser prints, per file, the count of bare references it removed, so the re-count rule in PREFLIGHT section 2
  has a figure to compare; no code-path change needed beyond the summary line.

### R2-10. LOW: short commit hashes and HHMM times in names are refused

- Reproduced (`r2/fresh.py`): `probe_v2_<ver>-49-ab1234cd5e_2026-10-15.json` and `rec_2026-10-15_1406.json` are name findings.
- Incidence: 3 banked names carry a hash with a four-digit run (all baselined). Fails closed.
- Fix: none required; add both shapes to the known false positives in the docstring and PREFLIGHT section 3.

### R2-11. LOW: the test module docstring describes the round-1 lock

- File: `tests/security/test_research_files_carry_no_tracker_numbers.py`, module docstring "WHAT IS LOCKED".
- What is wrong: it says "each of the four patterns" (there are five), lists two readings (five are now tested), and omits the
  reference control, opt-in parsing, fence boundaries and masking that the file now locks.
- Fix: rewrite the list to match the tests.

### R2-12. LOW: `--add-existing-names` with a moved `--base-ref` admits a new name

- File: `scripts/research_tracker_lock.py` `write_baseline()`.
- Reproduced (`r2/addnames.py`): after committing a new `run_<4 digits>.py` on a branch,
  `--write-baseline --base-ref HEAD --add-existing-names` exits 0 and lists it; plain `--check` passes; `--check --reference-ref main`
  FAILS (`baseline gained a name entry against the reference`). With the default base (`main`) it is refused.
- So the gate catches it; the tool's docstring promise ("names of files already tracked at the base ref") holds only for an
  honest base ref.
- Fix: `--add-existing-names` takes names only for files tracked at `main` (or at the merge base), whatever `--base-ref` is.

## What I attacked and could not break

- Baseline creation: `scripts/research_tracker_baseline.json` is absent on `main` (`git show main:...` fails; no commit on main
  touches it), so the 2 -> 4 rise for the `llamacpp_vs_openvino` record is initial creation. The 4 are real: one tracker field
  and three word-glued upstream forms now counted by the round-1 finding-3 rule. `write_baseline(root, "main")` regenerates
  the committed file exactly (`committed == regenerated vs main: True`); no listed path is untracked at main; no research file
  changed between main and the branch.
- `--add-existing-names` with the default base cannot admit a file new since main (`findings in a file not tracked at main`), and
  content counts cannot be raised through it with any base ref.
- The real index passes `--check` both bare and with `--reference-ref main`; the scope is non-empty (204 performance, 17 probe,
  1 checklist).
- Date rule: `run_2001`, `2050_probe`, `ov2026_1`, `ov_2026.4.0`, `2026-13-01`, `1999` plain, `1015`, `1906_<date>` are findings;
  `YYYY-MM`, `YYYY_MM_DD`, `YYYY.MM.DD`, `YYYYMMDD`, timestamped names pass, as the docstring says.
- Masking: five-digit runs, version years and month-day runs print as `NNNN`; dates and compact dates print as written; no
  matched content digits appear in `--check` output.
- Opt-in parsing: CRLF, BOM, leading blank lines, trailing spaces, upper case, quoted values, trailing comments, `...` closer all
  parse; key outside the front matter, value typo, missing colon, key after the closer, front matter not first are malformed;
  a BOM before the log marker is malformed (fails closed).
- Evidence repository: the 9P re-sanitise is byte-identical to main's; re-sanitising each of the three published folders gives
  content byte-identical to the published files on both main and the branch (only the `.sanitized` marker is rewritten);
  `--self-test` 0 failures; `--tracked` 153 files, 0 hits; five-digit `H` numbers are removed and refused.

## Suites run

- `LOCALAPPDATA=<temp> .venv python -m pytest tests/security/test_research_files_carry_no_tracker_numbers.py -q`: 144 passed, at `d872ef8c`.
- `LOCALAPPDATA=<temp> .venv python -m pytest tests/security/ -m "not hardware and not winui and not slow" -q -k "tracker or identity or public_snapshot"`:
  375 passed, 2967 deselected, at `d872ef8c`.
- `python scripts/research_tracker_lock.py --check` and `--check --reference-ref main`: ok, at `d872ef8c`.
- Evidence repository at `d08272e`: `tools/leak_gate.py --self-test` (0 failures), `--tracked` (153 files, 0 hits).
- The standing gate was not run.

## Merge read

Block on R2-1: the lock as written turns the next run of five standing benchmark harnesses into a red gate, and the fix (drop the
version from the writers' file names) belongs in this change. R2-2 to R2-6 are one-line or few-line fixes that should land in the
same round: R2-2 will fail this branch's own disposition record and journal fragment as soon as they name the key; R2-3 is the
round-1 silent-opt-in class still open and locked by a test; R2-4 is a false positive on every stale branch; R2-5 is an
unrecorded wrong spare with a live writer; R2-6 makes the public gate weaker than the private lock. R2-7 to R2-12 do not block.
