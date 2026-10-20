# Research pre-flight lock: adversarial review, round 4 (2026-10-15)

Reviewer: independent (not the author, not the reviewer of rounds 1 to 3). Report only; nothing was fixed.

Tested at:
- BlarAI worktree `%USERPROFILE%/BlarAI-worktrees/research-preflight`, branch `feat/research-preflight`, commit `22447ac3`
  (on `470e8e6c`, `d872ef8c`, `25fa58b4`); working tree clean apart from the untracked round-1 to round-3 reviews.
- BlarAI `main` is `2168ec96`, still the merge base: main has not moved since the branch was cut.
- `%USERPROFILE%/windows-containment-evidence`, branch `fix/number-patterns-widen`, commit `44fe7a8` (on `f4ae730`), against
  `main` (`40a73e6`). During this round another session switched that checkout to a different branch; every evidence-repository
  result below was produced in a scratch clone checked out at `44fe7a8` (and one at `40a73e6`), never in the shared checkout.

Notation: "H" stands for the hash character. "The opt-in key" stands for the front-matter key and log-marker word the lock
parses; this file writes neither literally. A tracker number inside a file name is written `NNN` or `NNNN`. Round-4 harnesses
are in `%USERPROFILE%/AppData/Local/Temp/claude/C--Users-__USER__-BlarAI/91386bce-adf7-42bc-9468-33ce534c1d6d/scratchpad/r4/`:
`tracker_attack3.py` (the round-3 attack, copied unchanged) with output `attack3_at_22447ac3.txt`; `r4_attack.py` with output
`r4_attack.txt`; `mut.py` (writer mutations); `hook_ff.py` (fast-forward against the installed git hooks); `ev/run9p.py`
(9P byte identity); scratch clones `clone/` (no-ff merge `07a044cc`, then branch `simff` for the fast-forward), `ctl/`
(a detached worktree of that clone at `2168ec96`, the control), `hookclone/` (hooks installed), `shallow1/`, `emptyrepo/`,
`nocheck2/`, `ev/evbr` and `ev/evmain`.

## Verdict: FAIL (0 BLOCKER, 1 HIGH)

The one HIGH is new in this round and is one regeneration command from fixed: the doctrine edit left the generated rules
corpus stale, so `tests/security/test_rules_corpus.py` fails on the branch and on the merged main (R4-1). Every round-3
finding is fixed or recorded as a limit.

## Round-3 findings, re-tested at `22447ac3` / `44fe7a8`

| # | Round-3 finding | Status | Evidence |
|---|---|---|---|
| R3-1 | Fast-forward landing turns main red; nothing tells the merger to use `--no-ff` | Fixed | `.claude/rules/identity.md:19` names `scripts/research_tracker_baseline.json` and `scripts/research_tracker_lock.py` in the `--no-ff` landing rule; PREFLIGHT section 6 and the lock docstring LANDING paragraph say the same; `test_fast_forward_landing_fails_and_no_ff_landing_passes` locks both the behaviour and the doctrine line. Scratch clone of the real repository: `git merge --no-ff --no-edit feat/research-preflight` on main gives `07a044cc`; `--check --reference-ref main` `ok (0 finding(s))` exit 0; the targeted file 181 passed. Fast-forward on `simff` (`2168ec96` then `--ff-only` to `22447ac3`): `llamacpp_vs_openvino_NNN_2026-07-10.json: baseline count for 'tracker-ref' rose against the reference`, FAIL, exit 1; `-k real` 1 failed, 3 passed. Round 3's premise was partly wrong: see R4-4 (two structural layers already refuse a fast-forward of main in the real checkout). |
| R3-2 | `--add-existing-names` output refused by the gate | Fixed | `reference_violations()` (`scripts/research_tracker_lock.py:552`) admits a name entry whose path was tracked at the reference commit. `tracker_attack3.py` A at `22447ac3`: branch `--check --reference-ref main` `ok`; main after a `--no-ff` merge `ok` (both FAILED at `470e8e6c`). Wrong-spare probes (`r4_attack.py`): F, an ungated direct commit on main that adds a NEW name-number file and its name entry: `baseline gained a name entry against the reference`, FAIL; the new test `test_a_genuinely_new_name_entry_is_still_refused` covers the branch side. |
| R3-3 | Misspelt key, plural key, TOML front matter silently unscoped | Recorded, not fixed | Lock docstring REMAINING LIMITS and PREFLIGHT section 3 now name all three. `tracker_attack3.py` B unchanged: all four `[]`, valid control still a finding. Zero incidence. Accepted as a recorded limit at LOW. |
| R3-4 | Ordinary documents fail as malformed opt-ins | Recorded, not fixed | Lock docstring names the three shapes as fail-closed; PREFLIGHT section 3 now gives the full key-shaped definition (the `<!--` form, the front-matter form, and "a line that opens with the key words and a colon in ordinary text is"). `tracker_attack3.py` C unchanged: all six still `malformed-opt-in`. Fails closed; zero incidence. |
| R3-5 | Version exemption spares tracker numbers 2000 to 2099; unrecorded | Recorded, not fixed | Lock docstring VERSION RULE ("NOT narrow in RANGE"), PREFLIGHT section 3, and the evidence gate docstring (`tools/leak_gate.py`, commit `44fe7a8`) all record it. `tracker_attack3.py` D unchanged (four masquerades `[]`, two controls findings). |
| R3-6 | Shallow clone weakens the reference; empty index reads `ok` | Fixed | Depth-1 clone of the merged main (`is-shallow-repository` true, 4068 files): `--check --reference-ref main` -> `cannot run: this is a shallow clone ...` exit 2; plain `--check` still `ok` (by design: no history needed). Fresh empty repository: `cannot run: the index holds no probe, performance or checklist file ...` exit 2; clone with `--no-checkout` (index 0 files): same, exit 2. Two new tests lock both. |
| R3-7 | Prose outlived code; harness-name lock was a hand copy | Fixed, one residual | DATE RULE sentence now defers to the VERSION RULE; PREFLIGHT key-shaped definition complete. The harness test now reads each writer's `outpath` f-string from source and fails when it is missing (mutations M3, `_` to `-` before the timestamp, and M4, dots kept, each fail it). Residual: the version VALUE is still supplied by hand (R4-2). |
| R3-8 | Round-1 and round-2 review files carry the account name | Fixed | `identity_lock.count_user_hits()` on rounds 1, 2, 3: 0, 0, 0; a case-insensitive grep for the account name: 0, 0, 0. With all three staged in the merged scratch clone: `scrub_public_identifiers.py --check` `0 finding(s) in 4071 tracked files`, exit 0. |

## Review files under `docs/reviews/`: in scope?

`docs/reviews/` is not a scope root of the research-tracker lock (`path_kind()` scopes only `tools/probes/<name>/...`,
`docs/performance/*.json` and the PREFLIGHT file). A `.md` there is read only for the opt-in: opted in, it is scanned; carrying a
key-shaped line without parsing, it is a `malformed-opt-in` finding; otherwise it is out of scope. `opt_in_status()` on rounds 1,
2, 3 and this file: `(False, [])`. Hash-and-digits references in the four files: 0. With rounds 1 to 3 staged in the merged clone,
`--check --reference-ref main`: `ok (0 finding(s))`. They are in scope of the identity ratchet (every tracked file), which they
pass (R3-8 row).

## Findings

### R4-1. HIGH: the doctrine edit left the generated rules corpus stale; the standing gate fails on the branch and on merged main

- File: `.claude/rules/identity.md:19` (edited) against `docs/governance/rules-corpus.yaml:808-813` (record
  `identity_hygiene.land-any-branch-touching`, still the old text and its old `text_sha256`), checked by
  `tests/security/test_rules_corpus.py` and `scripts/extract_rules_corpus.py --check`.
- What is wrong: the corpus is generated from CLAUDE.md and `.claude/rules/`, and the gate requires the committed corpus to equal
  a fresh extraction; the branch changed a rule line without regenerating it.
- Scenario: the branch merges, the post-merge standing gate on main reports 2 failures in `tests/security/` (the bar is 0 failed),
  and main stays red until someone regenerates the corpus in a follow-up.
- Reproduced (discriminating split, same command, same venv):
  ```
  worktree 22447ac3:  scripts/extract_rules_corpus.py --check   -> stale: ['rules-corpus.yaml'] ... exit 1
                      pytest tests/security/test_rules_corpus.py -> 2 failed, 38 passed
                        FAILED ...::test_committed_corpus_equals_a_fresh_extraction
                        FAILED ...::test_toggle_edited_rule_changes_output_and_fails_committed_check
  merged main 07a044cc (scratch clone):  --check exit 1;  pytest -> 2 failed, 38 passed
  main 2168ec96 (ctl, control):          --check exit 0;  pytest -> 40 passed
  ```
- Why nobody saw it: the agreed targeted selection (`-k "tracker or identity or public_snapshot or doctrine"`) does not select
  `test_rules_corpus.py`, and round 3 ran the same selection. The edit touches doctrine, so the doctrine-adjacent suites that
  read `.claude/rules/` or the corpus belong in the targeted run.
- Incidence: 1 record.
- Fix (for the author): run `python scripts/extract_rules_corpus.py` and commit the regenerated corpus (and `rules-gaps.md` if it
  changes) on the branch; re-run `test_rules_corpus.py`.

### R4-2. LOW: the harness-name lock reads the writers' file-name template but still invents the version value

- File: `tests/security/test_research_files_carry_no_tracker_numbers.py:729-756` (`_OUTPATH_RE`, `writer_name_format()`,
  `test_each_harness_name_format_passes_and_a_tracker_in_its_place_fails`).
- What is wrong: the test substitutes the literal `2026_2_1_0` for `{safe_ov}` and checks only that `replace(".", "_")` appears
  somewhere in the source, so a writer that changes how it derives `safe_ov` (for example drops `.split("-")[0]` and keeps the
  build suffix) still passes; the module docstring's "the five benchmark harnesses' own name formats, read from their source,
  pass" claims more than that.
- Reproduced (`mut.py`, scratch clone, each mutation reverted after its run):
  ```
  M1 kv_cache_sweep drops split("-")[0]               -> 5 passed
  M2 vlm_perf keeps the build suffix as underscores   -> 5 passed
  M3 vlm_perf "-" instead of "_" before the timestamp -> 1 failed, 4 passed
  M4 prefill keeps the dots                           -> 1 failed, 4 passed
  ```
- Cost: fail-closed. A writer change of the M1/M2 kind produces names the lock may refuse; the refusal arrives at the first commit
  of a real record, not in the suite.
- Incidence: 0 (all five writers today use `split("-")[0].replace(".", "_")`).

### R4-3. LOW: PREFLIGHT still says banked files "may only fall"; a banked file's name entry can now be added

- File: `docs/research/PREFLIGHT_RESEARCH_COMMIT.md:54`.
- What is wrong: the R3-2 fix admits a NEW name entry for a path already tracked at the reference, which the line "files already
  banked are frozen in the lock's baseline and may only fall" no longer describes; the lock docstring states the admission,
  PREFLIGHT does not.
- Reproduced: by reading against behaviour (`tracker_attack3.py` A: the name list grows by one entry and the reference passes).
- Incidence: 1 sentence.

### R4-4. INFO: round 3's fast-forward premise; the doctrine line is a third layer, not the first

- The real checkout's `core.hooksPath` points at the installed BlarAI git hooks; `scripts/hooks/reference_transaction.py` refuses
  every update of main that is not a `--no-ff` merge or a companion-only commit, and the session's PreToolUse `git_rules_guard`
  refuses a non-`--no-ff` `git merge` on main before it runs.
- Reproduced: in `hookclone/` (hooks installed with `scripts/install_git_hooks.py --repo .`), the shell call `git merge
  feat/research-preflight` on main was refused by `git_rules_guard` ("`git merge` on main must be `git merge --no-ff <branch>`");
  the same merge driven from Python (`hook_ff.py`) gives `fatal: in 'prepared' phase, update aborted by the reference-transaction
  hook`, main still `2168ec96`, and the merged files left staged in the scratch working tree (the hook's own message tells the
  operator to run `git reset --merge`).
- Consequence: R3-1's "a plain merge fast-forwards today" holds only in a clone without the hooks (my `clone/`, round 3's `r3/clone`).
  The doctrine line remains worth having for such clones and for the reason it gives. Round 3's incidence "this merge only" was
  also understated: `r4_attack.py` E, a branch that lowers a banked count and then restores it, passes the gate on the branch at
  both commits and turns main red after `--ff-only` (passes after `--no-ff`). Moot under the hooks.
- The rule-delivery hook (`scripts/hooks/rules_inject.py` `select()`) delivers `identity.md` for
  `python scripts/research_tracker_lock.py ...` but for no form of `git merge ... feat/research-preflight` (result `[]`); immaterial
  while the structural layers refuse the fast-forward.

### R4-5. INFO: an environmental failure seen only in the worktree, not caused by this branch

- `tests/security/test_doc_pointers_and_banners.py` (2 tests) fails in the worktree: `docs/adrs/ADR-013-...md` L35 and L142 link to
  `../../../devplatform/...`, which resolves from the real checkout (the target exists under `%USERPROFILE%/devplatform`) and not
  from `%USERPROFILE%/BlarAI-worktrees/research-preflight`. The branch does not touch ADR-013. Recorded so the next reviewer does
  not chase it; not a finding against this branch.

## Doctrine register of the `.claude/rules/identity.md` edit

The edit adds one parenthetical file list to an existing rule; the rule stays an imperative with a one-clause reason ("a
fast-forward puts every intermediate baseline version on main's reference line ...") and an operational ticket pointer, with no
incident story. `tests/security/test_doctrine_freshness.py` and `tests/security/test_doctrine_rules.py` pass in the worktree
(287 passed together with the targeted file). The rule now covers a lock that is not an identity control, inside the
`identity_hygiene` block; the reason clause fits both locks. Not a finding. The register is fine; the generated corpus is not
(R4-1).

## PREFLIGHT against the code

Matches on: the five content and name patterns, the date and version rules with the range limit, the key-shaped definition (the
three forms `opt_in_status()` enforces), every REMAINING LIMIT the docstring lists, the scope by path, the `--reference-ref`
requirement and the `--no-ff` landing. Diverges on: R4-3. Not stated in PREFLIGHT, stated in the docstring (acceptable for a
checklist): the shallow-clone and empty-index exit 2.

## What I attacked and could not break

- Name admission: a new path is refused on the branch and on the main line (F); admission is keyed on the path being tracked at
  the reference commit (merge base on a branch; the oldest baseline version of the window on the main line), so it cannot admit a
  file the reference never had. A single-version window admits every name (G), which is no change from round 3: with one version
  there is nothing to compare.
- Shallow guard: depth-1 clone with `--reference-ref` exits 2 naming the cause; plain `--check` in it still works.
- Empty-index guard: empty repository and `--no-checkout` clone both exit 2; the real index and the merged main pass.
- Landing: `--no-ff` merged main passes `--check --reference-ref main` and the full targeted file (181 passed); the fast-forward
  control fails as documented.
- Evidence repository at `44fe7a8` (clone): `tools/leak_gate.py --self-test` 0 failures; `--tracked` 153 files, 0 hits. 9P raw
  source (BlarAI `b04ee32d`) re-sanitised with main's (`40a73e6`) and the branch's sanitiser: byte-identical trees (4 files), both
  `{'tracker': 27, 'fixture': 1262, 'local': 375}`; both `runs/` files byte-identical to the published folder; `README.md` and the
  `.sanitized` marker differ from the published folder, as PROVENANCE records (hand edit); the raw sanitised README carries 2
  `tracker-word` hits that the published, hand-edited README does not (published folder: 0 hits).

## Suites run (all at `22447ac3` unless stated; LOCALAPPDATA redirected to a scratch folder; project `.venv`, Python 3.11.9)

- `pytest tests/security/ -m "not hardware and not winui and not slow" -q -k "tracker or identity or public_snapshot or doctrine"`:
  517 passed, 2862 deselected (702 s).
- `pytest tests/security/test_doctrine_freshness.py tests/security/test_doctrine_rules.py tests/security/test_research_files_carry_no_tracker_numbers.py`: 287 passed.
- `pytest tests/security/test_rules_corpus.py`: 2 failed, 38 passed (R4-1); at `2168ec96`: 40 passed; at merged `07a044cc`: 2 failed.
- Governance-adjacent sweep (`test_handoff_discipline`, `test_rules_corpus`, `test_acs_vocabulary_alignment`,
  `test_auditability_screen_reads_the_card`, `test_claim_register_row12_tls_blindspot`, `test_doc_pointers_and_banners`,
  `test_git_rules_guard`): 4 failed (2 R4-1, 2 R4-5), 227 passed.
- `scripts/research_tracker_lock.py --check --reference-ref main` in the worktree: `ok (0 finding(s))` exit 0.
- `scripts/scrub_public_identifiers.py --check` in the worktree: `0 finding(s) in 4068 tracked files` exit 0.
- Scratch merge of the real repository: `--no-ff` merge `07a044cc`: lock `ok`, targeted file 181 passed; fast-forward: lock FAIL,
  `-k real` 1 failed.
- Evidence repository at `44fe7a8`: self-test, tracked scan, 9P byte identity (above).
- The standing gate was not run.

## Merge read

Block on R4-1: the branch as it stands fails `tests/security/test_rules_corpus.py`, which is in the standing gate, and would carry
that failure onto main. The fix is to regenerate the corpus on the branch and re-run that file; nothing in the lock itself needs to
change. R4-2 and R4-3 do not block (fail-closed test residual; one stale sentence). R4-4 and R4-5 are information. Land with
`git merge --no-ff` (the installed hooks will refuse anything else).
