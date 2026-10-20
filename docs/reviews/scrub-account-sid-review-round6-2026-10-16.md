---
title: "Adversarial review, round 6: machine account SID scrub and the hf_publish preflight SID rule (#1799)"
date: 2026-10-16
review_of: "0b3ce271 on feat/scrub-account-sid (fix 79dfb1f3 for round-5 R5-1 to R5-8, disposition 62cd9ddb and 0b3ce271)"
reviewer: independent subagent (author != verifier)
---

# Round 6: machine account SID scrub (#1799), at `0b3ce271`

**Verdict: PASS. No finding blocks.**

Every round-5 finding is closed through the real entry points:

- No input crashes any of the three paths.
- A rewriting `--dir` refuses unreadable, unwritable or unnameable files before writing, and rolls back a failed write.
- Each new branch has a test that fails when the branch is removed (15 of 15 mutants killed).
- The UTF-32 detection changes no result on the real research data or the banked exports.

Two LOW residuals and three INFO notes remain, listed below. None leaks a SID, and every one fails closed except finding 1,
which predates the branch and needs only a disposition wording change.

## Findings

1. **LOW: BOM-less UTF-32 that is not mostly ASCII still passes the preflight and `--dir --check`. The `r5-5 FIXED` row
   overstates the fix.**
   - Mechanism: the new detection (`scripts/identity_lock.py`, `looks_utf16`) wants 95% NUL bytes in the three high bytes of each
     four. Each character above U+00FF puts one non-NUL byte in those three, so text with more than about 15% such characters is
     not read as UTF-32. It then falls to the UTF-16 rule and is mis-decoded.
   - Reproduced (`r5/u32edge.py`): a `README.md` in UTF-32-LE without a BOM holding Cyrillic text and a full foreign SID gives
     `preflight: CLEAN` (exit 0), `--dir --check` with 0 findings, and a rewrite that changes nothing. This is the same at
     `77f2b9ba`.
   - In-process (`r5/r6.py`): `u32le_cjk_heavy` gives `enc=utf-16-be lock=False changed=False`. With a BOM, or with mostly ASCII
     text, the same SID is caught and cleared.
   - The module docstring states the 95% rule, but the HONEST LIMIT list does not name the consequence.
   - Incidence: 0 UTF-32 files among 1098 research-data files.
   - Remedy: one line in HONEST LIMIT, and narrower wording on the `r5-5` row. This is not a code fix.

2. **LOW: the UTF-32 side effect. An int32-array binary with one value outside the Unicode range now refuses a whole rewriting
   `--dir` run.**
   - Reproduced (`r5/u32edge.py`): `labels.bin` holds 2,000 small int32 values, one `-1`, then 100 more. A rewriting run gives
     `labels.bin: unreadable: wide-character ... does not decode`, and `run refused`. The other files in the folder, including a
     SID in `a.txt`, are left unrewritten (exit 1, log written). At `77f2b9ba` the same folder was rewritten (exit 0).
   - The same array without the `-1` decodes and passes as before.
   - It fails closed, with a named reason, and the remedy is to move the file out.
   - Real-data measurement, as requested: `--dir --check` at `77f2b9ba` and at `0b3ce271` over the whole research-data tree and
     over `hf-export/mxc_denied_subtree` and `hf-export/mxc_proxy_egress`:
     - research-data tree: 330 findings at both commits, 0 unreadable at either, identical lines.
     - each export folder: 0 findings at both commits.
     - `looks_utf16` gives a different answer for 0 of the 1098 files.
   - The false-positive rate on the folders this scrub serves is 0. I would not block on a shape that has not appeared.

3. **INFO: in `--check` mode a refusal prints `run refused: 1 problem(s) stopped the rewrite, so nothing was rewritten`.**
   - A check never rewrites. The line is counted as a finding, so the closing `N finding(s)` reads one higher than the number of
     problem files (`gz5_no_sid`: 1 problem, `2 finding(s)`).
   - Exit code and detail are correct.

4. **INFO: UTF-16-LE text with a BOM whose first character is U+0000 is read as UTF-32-LE (`FF FE 00 00`).**
   - It is reported unreadable, so it fails closed (`r5/r6.py` `u16le_bom_then_nul`: `unreadable=True`).

5. **INFO: a rewriting `--dir` run now holds the old and new bytes of every changed file in memory until the write phase.**
   - The research-data tree is 164 MB, so this is no concern there. It is noted for multi-GB folders.

## Round-5 findings at `0b3ce271`

| finding | status | evidence |
|---|---|---|
| R5-1 rewrite then crash, no log | **closed** | `r5/crash2.py`: read-only `z.txt`, lone-surrogate name and read-denied file each give exit 1, no traceback, `a.txt` untouched, log written. `r5/r6.py` rollback: with the third write in the run failing (simulated `PermissionError`), `a.txt` and `m.txt` are restored byte-for-byte, the log records `write failed ... restored`, `Rewrote 0 file(s)` |
| R5-2 size-cap line prints a SID name | **closed** | `oversize_sid_name`: `FAIL file #0: 8000004 bytes exceeds cap 1000`, no sub-authority |
| R5-3 preflight tracebacks | **closed** | permission-denied `could not be checked (PermissionError); refused`; surrogate name `file #0: could not be checked (UnicodeEncodeError)`; JSON and JSONL 200,000 deep `could not be checked (RecursionError)`; each keeps the rest of the list |
| R5-4 depth-cap SID label | **closed** | SID-free 5-deep gzip: preflight `unreadable (nesting depth)`, no SID line; `--dir --check` no `identifier present`. A SID 5 deep still refuses the run |
| R5-5 UTF-32 | **closed for BOM and ASCII-dominant text** | finding 1 for the residual. The CLI refuses BOM, LE and BE without BOM, SID after 4 KB, and gzip(UTF-32). The lock and the rewrite agree, and no sub-authority is left after the rewrite |
| R5-6 ML / MJ | **closed** | N12 and N11 below are killed |
| R5-7 | DEFERRED, predicate valid | #1800 exists on the board and its description carries the fix and its test |
| R5-8 double count | **closed** | the dedup is locked (N9 killed); finding 3 is a different line |

## Mutations at `0b3ce271`

Run on a `git archive` copy (`r5/mut6.py`, `r5/mut6_table.py`), with a `-k` selection of 278 tests from the two files. The
baseline has 2 environmental failures (no banked qwen35 data from scratch). Each mutant's count is relative to that baseline.

| mutant | extra failures |
|---|---|
| N1: writability probe removed | +1 |
| N2: rollback removed | +2 |
| N3: unencodable-name refusal removed | +1 |
| N4: preflight shows an unencodable name | +1 |
| N5: `RecursionError` not caught | +2 |
| N6: `OSError` not caught | +1 |
| N7: BOM-less UTF-32 detection removed | +6 |
| N8: UTF-32 BOMs removed | +2 |
| N9: dedup removed | +1 |
| N10: depth cap removed from `scrub_bytes` | +1 |
| N11 (MJ): depth cap removed from `unreadable_reason` | +2 |
| N12 (ML): stage prints a SID-bearing name | +2 |
| N13: lock depth cap labels a SID again | +2 |
| N14: read error not refused | +1 |
| N15: preflight name redaction off | +5 |

All 15 are killed.

## Fuzz at `0b3ce271`

- `r5/fuzz6.py`: the round-5 generator and corruption, with UTF-32 LE/BE containers added, with and without BOM, optionally
  gzipped. Seeds 1, 7, 11 and 19, 300,000 inputs each: **1,200,000 inputs**.
- Properties, each with 0 violations: P1 no exception; P2 rewrite changes ⇒ lock fires; P3 unreadable ⇒ unchanged; P4 the
  `77f2b9ba` lock fires ⇒ the new lock or the unreadable reason fires; P5 rewrite unreadable ⇒ the reason is set.
- Against the older `9be732bd` lock, P4 has 31 hits out of 1.2 M. All are byte-flipped UTF-32-BE, where `9be732bd` failed closed on
  a mis-detected UTF-16 decode. The flip had broken the SID, and the correctly decoded UTF-32 holds no SID shape, so these are not
  lost signals.

## Banked export folders

Preflight at `77f2b9ba` and at `0b3ce271`, comparing exact problem lists (`r5/pfdiff.py`) with `allow_keys=()` and
`("detail",)`:

| folder | problems at both commits | only old / only new | unreadable |
|---|---|---|---|
| `hf-export/mxc_denied_subtree` | 22 | 0 / 0 | 0 |
| `hf-export/mxc_proxy_egress` | 25 | 0 / 0 | 0 |
| `qwen35-9b-int8-2026-10-04` | 1378 and 1339 | 0 / 0 | 0 |
| `qwen35-phase1-2026-10-04` | 1811 and 1756 | 0 / 0 | 0 |

## Attacked and could not break

- Every crash input from rounds 4 and 5 through `--dir --check`, the rewriting `--dir` and the preflight.
- Rollback after a mid-run write failure.
- A directory junction inside the folder: the walk follows it and refuses the SID behind it (`r5/r6.py` `junction`).
- Redaction on every preflight path, including size-cap and unencodable names.
- Rounds 1-4: `r4/reverify.py` (every R1 shape, F2 name, folder, gzip and zip, N5) and `r4/pfep.py` (no sub-authority echoed;
  placeholder and generic SIDs pass) hold.
- `verify_disposition.py`: PASS, 31 ok / 0 unjustified.

**Not tested:**
- A subdirectory the walk cannot list. `icacls /deny (RD)` did not bite for the owning account.
- A true symlinked directory, which needs elevation. Python 3.11 `rglob` does not descend symlinked directories, so a symlink in a
  folder would hide its contents from both checks. This is a hypothesis; I did not run it.

## What was run

- Hash `0b3ce271`, worktree `%USERPROFILE%/BlarAI-worktrees/scrub-account-sid`, the primary checkout's `.venv` (Python 3.11.9),
  LOCALAPPDATA redirected to the reviewer's scratchpad, bash, all foreground.
- In the worktree:
  - `tests/security/test_machine_sid_scrub.py`, `test_no_machine_sid_domain_in_tree.py` and `test_disposition_discipline.py`:
    295 passed.
  - `tests/integration/test_hf_publish.py` and `tests/security/test_no_host_identity_in_tree.py`: 359 passed.
  - Total **654 passed**, 0 failed.
- `verify_disposition.py`: PASS. The standing gate was not run (brief).
- Harnesses, in the reviewer's scratchpad `r5/`: `crash.py`, `crash2.py`, `r6.py`, `u32edge.py`, `census6.py`, `fuzz6.py`,
  `mut6.py` and `pfdiff.py`.

## Merge read

**Mergeable from this review's side.**

- Finding 1 needs a sentence, not code: name non-ASCII BOM-less UTF-32 in HONEST LIMIT and narrow the `r5-5` row. It can land with
  the merge.
- Finding 2 measured 0 on real data and fails closed with a named reason.
- Findings 3-5 are INFO.
