# Research pre-flight lock: adversarial review, round 1 (2026-10-15)

Reviewer: independent (not the author). Report only; nothing was fixed.

Tested at:
- BlarAI worktree `%USERPROFILE%/BlarAI-worktrees/research-preflight`, branch `feat/research-preflight`, commit `25fa58b4`
  (working tree clean; the PREFLIGHT file on disk equals the committed one).
- `%USERPROFILE%/windows-containment-evidence`, branch `fix/number-patterns-widen`, commits `2bd95ed` and `4f10187` against `main` (`40a73e6`).

Notation: "H" below stands for the hash character, so `H1786` means a hash followed by those digits. This file carries no tracker
reference. Scratch harnesses live in
`%USERPROFILE%/AppData/Local/Temp/claude/C--Users-__USER__-BlarAI/91386bce-adf7-42bc-9468-33ce534c1d6d/scratchpad/rt/` (BlarAI lock)
and `.../scratchpad/ev/` (evidence repository).

## Verdict: FAIL (1 BLOCKER, 3 HIGH)

## Findings

### 1. BLOCKER: the widened sanitiser deletes upstream references before the local rule can rewrite them; the 9P counts change

- File: `windows-containment-evidence/tools/sanitize.py`, `TRACKER_REF_RE` (commit `4f10187`).
- What is wrong: the reference rule was widened from the 1NNN range to every bare three- or four-digit `H` number. Rule 5
  (tracker) runs before rule 8 (local replacements), so a bare upstream issue number that the local file maps to its
  `owner/repo` form is now deleted first. The sanitiser's own docstring (rule 5) still says other bare numbers "are left for the
  gate to refuse and a person to resolve, because a bare number can as well be an upstream issue"; the code now does the opposite.
- Reproduction (re-sanitise the private 9P source with main's sanitiser and with the branch's, same local file):
  ```
  python <main copy>/tools/sanitize.py %USERPROFILE%/BlarAI/docs/research/nono-9p-failclosed-control-2026-10-14 .../ev/9p-main
    -> replacements: {'tracker': 27, 'fixture': 1262, 'local': 375}      (equals the published .sanitized marker)
  python tools/sanitize.py  <same source> .../ev/9p-branch
    -> replacements: {'tracker': 399, 'fixture': 1262, 'local': 3}
  grep -m1 '"ref":' 9p-main/runs/run2-piped-*.json    ->  "ref": "nolabs-ai/nono<H><4 digits> step 4",   (as published)
  grep -m1 '"ref":' 9p-branch/runs/run2-piped-*.json  ->  "ref": " step 4",
  ```
  run2 shrinks from 391022 to 384182 characters; 360 records in run2 lose their upstream citation. `leak_gate.py --tree` reports
  the same two hits on both outputs, so the gate cannot see the loss.
- Cost: the next bundle sanitised with this branch silently loses every bare upstream reference and its marker counts no longer
  match the raw re-count. The PREFLIGHT rule "every figure re-counted after sanitising equals the raw count" would catch it only if
  someone re-counts the references, and the gate passes it.
- Not affected: the already-published bundles. Re-sanitising each published folder gives identical counts and identical content
  on main and on the branch (wfp-sid-block 1, nep0005-halfset 1, 9P 4; all four from re-blanking the already-blank tracker field).
- Fix: keep the documented contract. The sanitiser removes only numbers it can know are internal (the local file's
  `tracker_numbers` list, plus the old 1NNN range if that is still wanted) and leaves every other bare `H` number for the gate to
  refuse. Add a self-test case: a bare upstream number mapped by a local replacement comes out as `owner/repo` plus the number.

### 2. HIGH: a hand-grown baseline passes the gate; the reference control is not wired and fails open on a bad ref

- File: `tests/security/test_research_files_carry_no_tracker_numbers.py`, `test_real_index_passes_check` (runs `--check` with no
  `--reference-ref`); `scripts/research_tracker_lock.py`, `check()` (a `git show` failure is swallowed as "baseline not at the ref").
- What is wrong: the only thing that stops the baseline from growing is `--reference-ref`, and nothing in the gate passes it.
  Any ref that does not resolve is treated as "the baseline is new", so `--reference-ref` with a typo passes too.
- Reproduction (`.../scratchpad/rt/grow.py`, run in a clone of the branch): raise one listed count by 1, add a new
  `docs/performance/new_rec_2026-10-15.json` holding one `H` reference and list it in the baseline, add a matching finding to the
  listed file, stage and commit:
  ```
  A grown baseline, --check:          (0, ['research tracker lock: ok (0 finding(s))'])
  B gate tests on grown commit:       3 passed, 89 deselected
  C --reference-ref HEAD~1:           (1, [... rose against the reference ... x2, 'FAIL (2 finding(s))'])
  D --reference-ref no-such-ref:      (0, ['research tracker lock: ok (0 finding(s))'])
  ```
- Cost: the central promise ("a new in-scope file carries zero; counts only fall") is undone by a one-line JSON edit, and the
  standing gate certifies the result.
- Fix: the gate test runs `--check --reference-ref` against the merge base with main (or reads the last N versions of the baseline,
  as the identity lock does). A ref that does not resolve raises `LockError` (exit 2); only "the path is absent at a ref that does
  resolve" counts as a new baseline. Add a toggle test that drives the CLI with a grown baseline and asserts exit 1.

### 3. HIGH: a reference glued to a word is spared, which covers the commonest written forms

- File: `scripts/research_tracker_lock.py`, `scan_bytes()` (the "glued to an ordinary word" branch).
- What is wrong: any `H` number directly preceded by a letter, digit or underscore is skipped unless the text before it is an
  `owner/repo` slug.
- Reproduction (`.../scratchpad/rt/probe.py`, each text as the only line of `tools/probes/alpha/run.py`, counts from `scan_index`):
  ```
  "see BlarAI<H>1786 here"   {}      "ticket<H>1786"   {}      "fixed in issue<H>1786"   {}
  "PR<H>1786"                {}      "x_<H>1786"       {}
  ```
- Incidence: in the whole current scope (204 performance JSON, 17 probe-directory files, the PREFLIGHT file) only 3 word-glued
  instances exist, all upstream-shaped. Treating glue as a finding would cost almost nothing on the banked corpus.
- Fix: a reference glued to a word is a finding; the only glue that passes is an allowlisted slug (already handled by
  `_UPSTREAM_TAIL_RE`). Move `word<H>N` from the clean-twin table to the findings table.

### 4. HIGH: the name rule is blind to 2000 to 2099 and will soon miss most new tracker numbers; the PREFLIGHT file does not say so

- File: `scripts/research_tracker_lock.py`, `_is_year_or_date()`; `docs/research/PREFLIGHT_RESEARCH_COMMIT.md` section 3.
- What is wrong: every four-digit run from 2000 to 2099 in a name is treated as a year. Measured from `git log main` subjects, the
  tracker went from 1000 (2026-07-20) to 1787 (2026-10-15), about 9 a day, so it reaches 2000 in about three and a half weeks.
  From then on the name rule certifies about a hundred tickets' worth of names clean. The evidence repository's gate made the
  opposite call: a plain year with no month after it is refused.
- Reproduction (`.../scratchpad/rt/probe2.py`):
  ```
  NAME tools/probes/alpha/run_2001.py   {}
  NAME tools/probes/2050_probe/x.py     {}
  NAME tools/probes/alpha/run_17860.py  {}     (five digits, also unseen)
  ```
- Incidence (`.../scratchpad/rt/years.py`): of the 222 runs from 2000 to 2099 in banked names, 18 have no month after them (the
  OpenVINO version forms `2026.4`, `ov2026_1`, `ov2026_2_1`). Those 18 could be listed as name entries in the new baseline.
- Fix: use the evidence gate's rule (a number from 1900 to 2099 is a date only when a separator and a month 01 to 12 follow it)
  and list the 18 banked names. The PREFLIGHT file states whatever limit remains, with its date.

### 5. MEDIUM: an `H` number followed by a letter or underscore is unseen

- File: `scripts/research_tracker_lock.py`, `_PATTERN_RES["tracker-ref"]`: the `\b` after the digits.
- Reproduction (`probe.py`): `"<H>1786a"` gives `{}`; `"<H>1786_fix"` gives `{}`; `"<H>178600"` gives `{}`.
- Fix: replace `\b` with `(?![0-9])`. The six-digit case can stay a recorded limit.

### 6. MEDIUM: a malformed opt-in fails silently, so the author believes a file is locked when it is not

- File: `scripts/research_tracker_lock.py`, `marked_entries()` (exact-line marker) and `has_tracker_free_front_matter()`.
- Reproduction (`probe2.py`; each planted text has a hidden `H1786`):
  ```
  LOG marker trailing space           OUT OF SCOPE
  LOG marker indented                 OUT OF SCOPE
  FM blank line first                 OUT OF SCOPE
  FM '--- ' trailing space            OUT OF SCOPE
  FM fm trailing comment              OUT OF SCOPE
  FM fm uppercase key                 OUT OF SCOPE
  ```
- Fix: any line carrying `research-scope` that does not resolve to a valid scope is itself a finding ("malformed opt-in").

### 7. MEDIUM: a `## ` line inside a fenced code block ends the marked entry; the rest of the entry is not scanned

- File: `scripts/research_tracker_lock.py`, `marked_entries()`.
- Reproduction (`probe2.py`): the marker, then `## Entry`, then a bash fence whose first line is `## build step`, then a leaked
  `H1786` after the fence. Result: `LOG ## inside fence 0`.
- Cost: shell comments that start with `## ` are ordinary in performance-log command blocks.
- Fix: skip lines inside ``` or ~~~ fences when looking for the next heading.

### 8. MEDIUM: the baseline is read from the working copy, not the index

- File: `scripts/research_tracker_lock.py`, `load_baseline()` (`root / BASELINE_PATH`). The module docstring says that scope is
  read "in the git INDEX (never the working copy, so an unstaged edit cannot hide a finding)". For the allowance, the opposite holds.
- Reproduction (`.../scratchpad/rt/unstaged.py`): commit a probe file holding one `H` reference, then write an untracked baseline
  that allows it:
  ```
  index holds baseline? False
  check with unstaged/untracked baseline: []
  ```
- Fix: read the baseline blob from the index (`git cat-file` on its index sha), the same way the content is read.

### 9. MEDIUM: the PREFLIGHT file overstates what the locks and the sanitiser do

- File: `docs/research/PREFLIGHT_RESEARCH_COMMIT.md`.
  - Section 2 says the sanitiser replaced "every tracker number and every fixture name carrying one". It does not: a number from
    2000 up inside a name is not rewritten and not refused in content (the gate docstring says so), and on this branch it
    deletes upstream references (finding 1).
  - Section 2 gives `python tools/leak_gate.py` over the staged files. That command exits with
    `error: one of the arguments --staged --tracked --tree --message --self-test is required`. It should read `--staged`.
  - Section 3 says a NAME carrying "a four-digit tracker number" is refused, without the 2000 to 2099 limit (finding 4).
  - Section 3's scope list says "journal fragments whose front matter carries" the opt-in. The code covers any tracked `.md`,
    `.markdown`, `.txt` or `.rst` file with that front matter. The code's wider scope is the safe direction; the text should match it.
- Checked and clean: the file carries no tracker reference (it is in the lock's scope and `--check` passes), and it says nothing
  about who a measurement is for, why it was run or where it will be posted. Section 4 states the rule against doing so. Section
  9's "private route" names a process, not an audience.
- Fix: correct the four sentences.

### 10. MEDIUM: the evidence repository's docstring and commit message no longer match its code

- `tools/sanitize.py` module docstring, rules 5 and 6, still describe `H1NNN`, `S1NNN-` and `p1NNN-` only, and still promise that
  other bare numbers are left for the gate.
- Commit `4f10187` says "rewrite four- and five-digit ... reference forms". `TRACKER_REF_RE` (sanitiser) and the gate's `tracker-ref`
  both take three or four digits. A five-digit `H` number survives the sanitiser and passes the gate: in the planted run below,
  `five <H>23456 end` stayed in the output and the gate reported only the path hit. The BlarAI lock takes three to five digits,
  so the two controls disagree.
- Reproduction: `.../scratchpad/ev/raw` planted bundle; `python tools/sanitize.py <raw> <out>`, then `python tools/leak_gate.py --tree <out>`
  gives `HIT run-2406/x.json:0 path:tracker-number` and `1 hit(s)`.
- Also confirmed, and recorded in the gate docstring with the date: `schema probe-2406-proof-v1` in content stays and is not seen.
- Fix: correct the docstring and the commit description in the next commit. Take three to five digits in both patterns, or record
  the five-digit limit with its date.

### 11. LOW: CSS colours and ordinals are tracker references

- `"body { color: <H>333; }"` and `"rank (<H>100 of 200)"` each count 1. Incidence of CSS-shaped matches in the current scope: 0.
  The cost is a refused commit on a probe that writes HTML. Fix: none required; record it as a known false positive.

### 12. LOW: `--check` output prints numbers that the mask does not cover

- `mask_numbers` masks only what the name rule flags, so path segments from 2000 to 2099 and five-digit runs print as they are.
- Reproduction (`.../scratchpad/rt/out.py`): `tools/probes/y_<5 digits>/b.py: pattern 'tracker-ref' x1 exceeds the allowed 0 ...`,
  which shows the same digits that matched in the content.
- Fix: mask every run of four or more digits that is not a full date.

### 13. LOW: the gzip, UTF-16 and ANSI readings are claimed but not locked in this test file

- The module docstring lists them; the test docstring claims "the readings ... hide nothing" but plants only JSON escapes, HTML
  entities and percent-encoding. They work when run (`probe.py`: gzip 1, UTF-16 LE with BOM 1, UTF-16 BE without BOM 1). No test
  here fails if `identity_lock.views` drops one.
- Fix: add one planted case per reading.

### 14. LOW: top-level probe files are out of scope

- 8 of the 10 tracked top-level `tools/probes/*.py` files carry references, and a new top-level probe escapes the lock entirely.
- This matches the LA-fixed scope ("tools/probes/<name>/"), so it is reported, not counted against the verdict.
- Fix, if wanted: a new top-level probe file (not tracked at the base ref) is a finding that says "use a probe directory".

### 15. LOW: the evidence gate's widened path rule refuses version, port and build numbers in names

- `PATH_NUMBER_RE` matches `2026` in a `2026.4` folder, and any number from 3000 to 9999 (ports, builds). This fails closed.
  Incidence in the tracked tree is 0 (`--tracked`: 153 files, 0 hits).
- The docstring gives "a 2026.4 folder would read as a tracker number" as the reason `tracker-in-name` was not widened. The path
  rule already refuses that folder name, so the stated trade-off holds for content only.
- Fix: none required; make the docstring sentence say "in content".

## What I attacked and could not break

- The index is the subject for content: an unstaged clean-up does not hide a staged finding, and an unstaged finding does not
  create one (the author's tests, re-run).
- Missing git gives exit 2; a directory that is not a repository gives exit 2.
- Ratchet: a gone baselined file fails, a file renamed into scope starts at zero, a count below the baseline fails until
  lowered, and `--write-baseline` refuses to raise or to add.
- Upstream exemption: these all came back as findings, as they should: lookalike slugs (`evil-microsoft/mxc`,
  `notmicrosoft/mxc`, `microsoft/mxc/` followed by the number), a slug on the previous line, a slug followed by text and then
  `H` and a number, a second number after `slug PR <H>N and`, a comma list after the slug, and a non-breaking space. Allowed forms
  pass, including tabs and a lower-case `pr`.
- Readings: JSON `\u0023`, double-encoded `\u0026#35;`, HTML entities, percent, gzip, UTF-16 LE with BOM and BE without BOM,
  UTF-16 inside JSON.
- Performance log: a CRLF marker, two markers, a marker with no heading (runs to the end of the file), a `##Entry` heading with no
  space, and an H1 inside the entry. A marker quoted in a code block widens the scope (fails closed).
- Front matter: CRLF, BOM, quoted value, `...` closer, no closer, and a second key are all seen.
- Fixture and session forms: the listed lengths and separators, the case rules, and the gluing refusals behave as the docstring
  says.
- Real index: `--check` exits 0, both bare and with `--reference-ref main`. The test file is collected by the standing selection
  (`pytest tests/security/ --collect-only -q -m "not hardware and not winui and not slow"` includes the module; 92 tests).
- Evidence repository: `--self-test` gives 0 failures; `--tracked` checks 153 files with 0 hits. Planted 2xxx fixture, session and
  reference forms are rewritten by the sanitiser (`fx-a`, `FX_marker`, `SXXXX-`, reference removed), and a `run-2406` folder is
  refused by the gate. The published bundles re-sanitise identically on main and on the branch.

## Suites run

- `LOCALAPPDATA=<temp> python -m pytest tests/security/test_research_files_carry_no_tracker_numbers.py -q`: 92 passed, at `25fa58b4`.
- `python scripts/research_tracker_lock.py --check` and `--check --reference-ref main`: ok, at `25fa58b4`.
- Collection check as above, at `25fa58b4`.
- Evidence repository at `4f10187`: `python tools/leak_gate.py --self-test` (0 failures) and `--tracked` (153 files, 0 hits).
- The standing gate was not run.

## Merge read

Block on 1 (data loss in the sanitiser, invisible to the gate), 2 (the ratchet can grow with the gate green), 3 (the commonest
written reference forms pass) and 4 (the name rule goes blind within weeks while the checklist says otherwise). Findings 5 to 10
are one-line or text fixes and belong in the same round. Findings 11 to 15 do not block.
