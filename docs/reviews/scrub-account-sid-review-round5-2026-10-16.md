---
title: "Adversarial review, round 5: machine account SID scrub and the hf_publish preflight SID rule (#1799)"
date: 2026-10-16
review_of: "77f2b9ba on feat/scrub-account-sid (fixes 1660035a and be088050 for round-4 R4-1 to R4-6, disposition 77f2b9ba)"
reviewer: independent subagent (author != verifier)
---

# Round 5: machine account SID scrub (#1799), at `77f2b9ba`

**Verdict: FAIL, on two findings.** The round-4 decode and decompress crashes are closed: no damaged gzip, undecodable UTF-16 or
odd-length NUL binary crashes any path, and over 1,000,000 fuzzed inputs (with truncation, odd bytes, flipped bytes and lone
surrogates added) produce no exception and no lock/rewrite gap. The invariant the fix states is wider than what it guards, though:

- (1) A rewriting `--dir` run still rewrites files and then dies without its log, when a later file cannot be **written** (a
  read-only file) or its **name** cannot be encoded. The pre-pass checks only whether content decodes. The `f5` and `r4-2` rows
  say FIXED, and the pre-pass comment says "a run never rewrites some files and then stops"; neither is true.
- (2) The preflight still prints a SID-carrying file name in full on one path, the size-cap refusal. The `r4-5` row and the
  docstring ("shown as `file #n` on every line") are not true for it.

## Findings

1. **MEDIUM (blocker): a rewriting `--dir` run changes files and then crashes without a log, on a read-only file or an unencodable
   file name. F5 / R4-2 are reopened for these paths.**
   - Where: `scripts/scrub_public_identifiers.py:506-517`. The pre-pass asks only `il.unreadable_reason(data)`. The main loop then
     calls `p.write_bytes(new)` at `:533` and `rel_name.encode("utf-8")` at `:520`, and neither is guarded. Files earlier in the
     sorted walk are already rewritten, and the log at `:560` is never reached.
   - Cost: the same as round-1 F5. An evidence folder is changed in place with no record tying it to the pre-scrub bytes. A
     read-only file is an ordinary input: copies from read-only media, archive extractions and some sync clients set the
     attribute.
   - Reproduced: `r5/crash2.py`. Each folder holds `a.txt` (a foreign SID) and one file sorted after it:

     | second file | `--dir --check` | `--dir --log X` | `a.txt` after | log written |
     |---|---|---|---|---|
     | `z.txt`, read-only, carries a SID | exit 1, 2 findings | exit 1, `PermissionError` traceback | **rewritten** | **no** |
     | `z\udc80.txt` (lone surrogate in the name) | exit 1, `UnicodeEncodeError` traceback | exit 1, `UnicodeEncodeError` traceback | **rewritten** | **no** |
     | `z.txt` with read denied (`icacls /deny`) | exit 1, `PermissionError` traceback | exit 1, `PermissionError` traceback | unchanged | **no** |

   - The read-only crash predates this fix: the same folder at `9be732bd` (scripts extracted to scratch) rewrites `a.txt` and
     raises `PermissionError`. But round 4 asked for one invariant ("never raised mid-walk"), and the new comment and the
     disposition certify it for the whole class.
   - Incidence: 0 read-only files and 0 surrogate-named files among 1096 files under `%USERPROFILE%/blarai-research-data`.
   - Shape of the fix (one correct fix, not a decision): the pre-pass must also prove each file can be read, written and named. An
     `OSError` or `UnicodeEncodeError` becomes a named finding that refuses the run. Lock it with a read-only fixture next to the
     existing unreadable ones.

2. **MEDIUM (blocker): the preflight prints a SID-carrying file name in full on the size-cap path. R4-5 is incomplete.**
   - Where: `scripts/hf_publish.py:515-518`. The size-cap branch appends `f"{rel}: {size} bytes exceeds cap ..."` and `continue`s
     before line 525 records the name in `sid_named`, so the replacement loop at `:580` never redacts it.
   - Cost: the live machine's SID in a file name reaches the console, agent transcripts and any review that quotes preflight output,
     which is what R4-5 set out to stop.
   - Reproduced: `r5/crash2.py` case `oversize_sid_name`: `acl-<foreign SID>.csv` of 8,000,004 bytes with `--max-bytes 1000` gives
     `FAIL acl-<SID>.csv: 8000004 bytes exceeds cap 1000` with every sub-authority printed (`echoes_sub=True`).
   - The new test `test_preflight_never_prints_a_sid_carried_by_a_file_name` uses `{}` files, so it never reaches this branch.

3. **MEDIUM: the preflight still dies with a traceback on three kinds of unreadable input, and loses its problem list.**
   - Where: `scripts/hf_publish.py:515-519` (`p.stat()` and `p.read_bytes()` are unguarded), `:525` (`rel.encode("utf-8")`), and
     `:560` / `:572` (`json.loads` catches only `JSONDecodeError`).
   - Reproduced: `r5/crash.py` and `r5/crash2.py`:
     - A permission-denied file gives `PermissionError`.
     - A lone surrogate in a file name gives `UnicodeEncodeError`.
     - `.json` or `.jsonl` nested 200,000 deep gives `RecursionError: maximum recursion depth exceeded while decoding a JSON array`.
   - The docstring now says unreadable input "is a named finding, never an exception, and the rest of the problem list is still
     produced". The brief's invariant names "any decode error". All three predate this branch (the `RecursionError` reproduces at
     `9be732bd`), and all three fail closed (exit 1). None leaks anything.
   - The same `PermissionError` and `UnicodeEncodeError` crash `--dir --check` (finding 1 table).
   - Incidence: 0.

4. **LOW: a SID-free gzip nested five deep is still labelled a SID. R4-4 is incomplete.**
   - Where: `scripts/identity_lock.py:133`, `return _depth >= GZIP_MAX_DEPTH or ...`. At the depth cap the lock returns True
     whatever the content, while `unreadable_reason` already names the file as unreadable.
   - Reproduced: `r5/crash2.py` case `gz5_no_sid` (`b"hello world\n"` gzipped five times):
     - The preflight prints both `unreadable: gzip nested deeper than four` and `machine/domain account SID (S-1-5-21-...) in the content`.
     - `--dir --check` prints `z.gz: identifier present`.
   - Cost: the operator is sent looking for a SID that is not there, which is what the `r4-4` row says is fixed. It fails closed.

5. **MEDIUM-LOW (wrong spare, predates this branch): a SID in UTF-32 text without a BOM passes the preflight and `--dir --check`.**
   - Mechanism: `looks_utf16` reads UTF-32-LE ASCII (75% NUL bytes) as UTF-16-LE. It decodes without error into
     `S\0-\01\0...`, so neither the rewrite arm nor the views see the SID, and `unreadable_reason` is None. The bytes are valid
     UTF-8, so the preflight's non-UTF-8 refusal does not fire either.
   - Reproduced: a `README.md` written with `.encode("utf-32-le")` carrying a full foreign SID. The preflight prints
     `preflight: CLEAN`, exit 0, both at `77f2b9ba` and at `9be732bd`. `--dir --check` gives 0 findings, exit 0. The host name in
     UTF-32-LE is not seen by `find_hits` either (`host utf32le seen: False`, `utf16le seen: True`).
   - With a BOM (`FF FE 00 00`), `--dir --check` and the rewrite still certify the folder (0 findings). The preflight refuses it
     only as non-UTF-8.
   - The module's HONEST LIMIT list does not name UTF-32.
   - Incidence: 0 UTF-32 BOM files among 1096 research-data files. A no-BOM UTF-32 file needs a deliberate encoder call.
   - Not a blocker for this branch, but it needs a disposition row: either a view or unreadable reason that covers UTF-32, or a
     named HONEST LIMIT line plus a ticket with an observable predicate.

6. **LOW: two new branches have no lock.** These are mutations run in a `git archive` copy of `77f2b9ba` (`r5/mut5.py`, `-k`
   selection over the unreadable, preflight, `--dir` and toggle tests: 174 tests, 2 environmental baseline failures):
   - ML: the pre-pass prints the raw name instead of `file #n` for a SID-named unreadable file. It **survives** (2 failed = the
     baseline). The real code does redact: `r5/misc.py` prints `FAIL file #1: unreadable ...` with no sub-authority. But no test
     plants a SID-named unreadable file in a rewriting run.
   - MJ: the `GZIP_MAX_DEPTH` check in `unreadable_reason` is removed. It **survives**. The docstring's "or nests deeper than
     `GZIP_MAX_DEPTH`" is unlocked.
   - Every other mutant is killed:

     | mutant | extra failures |
     |---|---|
     | MA: preflight unreadable line removed | +4 |
     | MB: pre-pass removed | +4 |
     | MC: refused guard removed | +4 |
     | MD: `zlib.error` dropped from `READ_ERRORS` | +5 |
     | ME: `scrub_bytes` UTF-16 decode unguarded | +3 |
     | MF: preflight name redaction removed | +3 |
     | MG: `utf16_problem` dropped from `container_problems` | +4 |
     | MH: unreadable gzip labelled a SID | +4 |
     | MI: unreadable UTF-16 labelled a SID | +5 |
     | MK: tree rewrite stops reporting unreadable files | +2 |
     | MM: `views` drops `zlib.error` | +5 |

     The R4-3 toggle (`test_unreadable_utf16_toggle_without_the_branch_the_hidden_sid_passes`) bites: it is among the MI failures,
     and MG kills the fail-closed test.

7. **LOW (predates this branch, outside #1799): the preflight's e-mail pattern is quadratic on long runs without an `@`.**
   - The pattern `[A-Za-z0-9._%+-]+@...` takes 2.8 s on 60,000 characters of `a1b2c3d4` and 11.1 s on 120,000.
   - A 6 MB line of `%25` did not finish the preflight within 600 s; `cProfile` puts 99% of the time in that one `search`.
   - Inputs under the 50 MB cap can hang the publish preflight for hours. It fails closed (nothing uploads) but nothing reports.
   - Incidence: not measured beyond the banked folders, which finish.
   - Needs a ticket, not this branch.

8. **INFO: a refused rewrite run counts one unreadable file twice.** The pre-pass line and `container_problems` both report it,
   so the closing `N finding(s)` overstates the record. Example (`r5/misc.py`): 2 distinct problems and the `run refused` line
   print as `4 finding(s)`.

## Round 1-4 re-verification at `77f2b9ba`

| finding | status | evidence |
|---|---|---|
| r4-1 damaged deflate crashes preflight and `--dir --check` | closed | damaged deflate, truncated header (3 bytes), magic only, oversized FEXTRA, unterminated FNAME, bad method byte, and gzip of a damaged gzip: every path exits 1 with a named `unreadable` line and no traceback; the preflight keeps its full list |
| r4-2 rewrite crashes mid-walk without a log | **closed for undecodable content; open for unwritable files and unencodable names** | finding 1 |
| r4-3 UTF-16 fail-closed branch untested | closed | toggle bites (MI, MG) |
| r4-4 unreadable labelled a SID | **closed except the depth cap** | finding 4 |
| r4-5 preflight prints a SID-bearing name | **closed except the size-cap path** | finding 2; `pfep.py` `live_in_name` and `foreign_in_dir_name` now print `file #0` (`echoes_subauthority=False`) |
| r4-6 garbled docstring | closed | the test text now states what it isolates |
| r4-7, r4-8 REJECTED | arguments hold | not re-attacked beyond `pfep.py`: the `%41`, `S` and ANSI shapes give 1 SID finding each |
| f1-f4, n1-n6, r1, r2 | hold | `r4/reverify.py`: all 7 R1 shapes and the F2 name, folder, gzip and zip cases give `--check` 1, then rewrite, then `--check` 0 with no sub-authority left. `N5` exits 1 with the message |
| f5 | **reopened** | finding 1 |
| fuzz: rewrite changes bytes ⇒ check flags | holds | `r5/fuzz5.py`, seeds 1, 3, 7, 11 and 19, 1,005,000 inputs (round-4 generator plus corruption), checking that **none** of these occur: (P1) an exception from `scrub_bytes`, `find_sid_hits`, `unreadable_reason` or `container_problems`; (P2) the rewrite changes the bytes and the lock is silent; (P3) a file named unreadable is changed by the rewrite; (P4) the round-4 lock fired, the new lock is silent, and no unreadable reason is set; (P5) the rewrite reports unreadable but `unreadable_reason` does not. Result: **0 of each**. P4 shows that moving undecodable input from the SID label to the unreadable label lost no signal |

## Banked export folders

Preflight at `9be732bd` and at `77f2b9ba`, comparing the exact problem lists (`r5/pfdiff.py`) with `allow_keys=()` and
`("detail",)`:

| folder | problems at both commits | only old / only new | unreadable |
|---|---|---|---|
| `hf-export/mxc_denied_subtree` (the 16:49 re-export) | 22 | 0 / 0 | 0 |
| `hf-export/mxc_proxy_egress` | 25 | 0 / 0 | 0 |
| `qwen35-9b-int8-2026-10-04` | 1378 and 1339 | 0 / 0 | 0 |
| `qwen35-phase1-2026-10-04` | 1811 and 1756 | 0 / 0 | 0 |

There are no intended changes on real data and no unintended ones.

## Attacked and could not break

- Every decode and decompress shape tried, alone, nested and inside zip members: truncated or damaged headers, damaged deflate,
  gzip of gzip, gzip of undecodable UTF-16, gzip five deep, zero-byte files, a lone high or low surrogate in UTF-16 LE and BE,
  odd-length NUL binaries, UTF-16 with a hidden `%41` SID and an odd byte. None raises, each is named, and a rewriting run
  refuses before writing and writes its log.
- Lock against rewrite agreement under corruption (1,005,000 inputs, 0 gaps).
- Huge lines in the scrub: a 5 MB line of backslashes and a 6 MB line of `%25` finish `--dir --check` and the rewrite, and clear
  the SID.
- Redaction in the pre-pass (real code), in `--dir` and on the preflight's main path.
- `verify_disposition.py`: PASS, 23 ok / 0 unjustified. The form passes. The `f5`, `r4-2`, `r4-4` and `r4-5` rows are untrue
  for the paths in findings 1, 2 and 4.

## What was run

- Hash `77f2b9ba`, worktree `%USERPROFILE%/BlarAI-worktrees/scrub-account-sid`, the primary checkout's `.venv` (Python 3.11.9),
  LOCALAPPDATA redirected to the reviewer's scratchpad, bash, all foreground.
- In the worktree:
  - `tests/security/test_machine_sid_scrub.py`, `tests/integration/test_hf_publish.py`,
    `tests/security/test_no_machine_sid_domain_in_tree.py`, `tests/security/test_no_host_identity_in_tree.py` and
    `tests/security/test_disposition_discipline.py`: **629 passed** in 507 s.
  - `scrub_public_identifiers.py --check`: 0 findings in 4095 tracked files.
  - `verify_disposition.py docs/reviews/scrub-account-sid-disposition-2026-10-16.md`: PASS.
- Not run: the standing gate (per the brief). The mutation runs used a `-k` selection, not the full two files.
- Harnesses, in the reviewer's scratchpad `r5/`:
  - `crash.py` and `crash2.py`: the crash inputs through all three entry points.
  - `fuzz5.py`: the fuzz.
  - `mut5.py`: the mutations.
  - `pfdiff.py`: the export comparison.
  - `misc.py`: the pre-pass redaction, UTF-32 and the incidence census.
  - `hang.py` and `hang2.py`: the regex profile.

  The round-4 `r4/` harnesses were re-run as well.

## Merge read

Block on findings 1 and 2. Both make disposition rows untrue, and each has one correct fix:

- Finding 1: the pre-pass must prove each file is readable, writable and nameable, and refuse the run with a named finding
  otherwise. Lock it with a read-only fixture.
- Finding 2: record `sid_named` before the size-cap `continue`, and lock it with an oversize SID-named file.

Fix finding 3 in the same change, since it is the same invariant: catch `OSError` / `UnicodeEncodeError` per file and
`RecursionError` in the JSON parse. Correct the `r4-4` row, or the depth-cap label (finding 4). Give finding 5 a disposition row,
with a covered view or a named HONEST LIMIT plus a ticket. Add locks for ML and MJ (finding 6). Ticket finding 7 separately.
Finding 8 does not block.
