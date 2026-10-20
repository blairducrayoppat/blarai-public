---
title: "Adversarial review, round 4: machine account SID scrub and the hf_publish preflight SID rule (#1799)"
date: 2026-10-16
review_of: "9be732bd on feat/scrub-account-sid (fix 92714005 for round-3 R1/R2, disposition 9be732bd)"
reviewer: independent subagent (author != verifier)
---

# Round 4: machine account SID scrub (#1799), at `9be732bd`

**Verdict: FAIL, on two findings.** Round-3 R1 and R2 are closed. Over 210,000 fuzzed inputs, no input exists where
`scrub_bytes` changes the bytes and `find_sid_hits` stays silent. Every R1 shape also fails `--dir --check` and clears through the
real entry point. The two blocking findings are elsewhere:

- (1) The new preflight line turns a clean refusal of a damaged gzip file into an uncaught traceback. This is a regression in the
  publish entry point.
- (2) A rewriting `--dir` run still changes evidence files without writing its record when a later file cannot be decoded, so the
  disposition row `f5 | FIXED` is not true for that path.

Neither finding leaks a SID. Both fail closed (exit 1), and each has one correct fix.

## Findings

1. **MEDIUM (blocker): a regression in `hf_publish.py preflight`. A gzip file with a damaged deflate body crashes the preflight.**
   - Where: `scripts/hf_publish.py:516` now calls `_il.find_sid_hits(raw)` before the UTF-8 check at line 521. `find_sid_hits` reaches
     `sid_rewrite_would_change` (`scripts/identity_lock.py:127`) and `views` (`:212`). Both catch only `(OSError, EOFError)`, and a
     damaged deflate stream raises `zlib.error`, which is neither.
   - Cost: the preflight that every dataset upload runs (`cmd_preflight` / `plan` / `upload`) dies with a traceback. It no longer
     prints its list of problems, so the publisher sees a stack trace instead of the other refusals.
   - Prose: the `sid_rewrite_would_change` docstring says "a gzip member that does not decompress ... is reported as changed: the
     lock fails closed there". That is false for this input.
   - Reproduced: a folder with one `a.json` = `gzip.compress(b"abc")[:10] + b"\xff"*20 + trailer`.
     - At `9be732bd`, `hf_publish.py preflight --dir pfbad` gives `zlib.error: Error -3 while decompressing data: invalid block type`, exit 1.
     - At `2095375c` (the scripts extracted to scratch), the same folder gives `FAIL a.json: not valid UTF-8 (binary or other encoding)`
       and `preflight: 1 problem(s)`, exit 1.
   - The same input also crashes `scrub_public_identifiers.py --dir --check`, through `container_problems:231` and `views`. That
     crash predates this change: rounds 1-3 did not try a damaged deflate body, only trailing bytes and truncation, which raise
     `OSError`/`EOFError`.
   - Incidence: 0 gzip files among the 1079 files under `%USERPROFILE%/blarai-research-data`.

2. **MEDIUM (blocker): a rewriting `--dir` run still changes files without writing its log. F5 is reopened for this path.**
   - Where: `scripts/scrub_public_identifiers.py:513` calls `scrub_bytes`. Its UTF-16 branch at `:193` decodes strictly and its gzip
     branch at `:183` does not catch `zlib.error`, so either exception kills the walk. Files earlier in the sorted walk have already
     been rewritten, and the log at `:540` is never written.
   - Cost: the same as round-1 F5. An evidence folder is changed in place with nothing that ties the result to the pre-scrub bytes.
     Re-running the scrub crashes again at the same file, so it cannot be completed either.
   - The fix's own lock already treats these inputs as unreadable. `sid_rewrite_would_change` returns True, so the check side fails
     closed. The rewrite side has no matching guard.
   - Reproduced: harness `ep.py`. Each folder holds `a.txt` (a plain SID) and one unreadable file sorted after it:

     | unreadable file | `--dir --check` | `--dir --log X` | `a.txt` after | log written |
     |---|---|---|---|---|
     | `z.bin` = 20 NUL bytes + `\x01` | exit 1, 2 findings | exit 1, `UnicodeDecodeError` traceback | `S-1-5-21-__MACHINE__-1001` | **no** |
     | `z.txt` = UTF-16 BOM + lone surrogate | exit 1, 2 findings | exit 1, `UnicodeDecodeError` traceback | rewritten | **no** |
     | `z.gz` = damaged deflate | exit 1, `zlib.error` traceback | exit 1, `zlib.error` traceback | rewritten | **no** |

   - The behaviour predates `92714005` (`scrub_bytes` is unchanged), but the disposition certifies `f5 ... FIXED a413c579` for the
     whole class.
   - Incidence: 0 undecodable UTF-16 files among 1079 files (5 look like UTF-16, and all 5 decode).

3. **LOW-MEDIUM: the lock's fail-closed UTF-16 branch has no test, and a one-line regression of it silently brings back an R1-class
   pass.**
   - Where: `scripts/identity_lock.py:135`, `except UnicodeError: return True`.
   - Mutation M6 (in a scratch copy) changes it to `return False`. The result is 3 failed / 507 passed, the same as the baseline's 3
     environmental failures, so no test sees it.
   - The branch matters: for `%41` + SID, or a doubly escaped `\\n` + SID, encoded as UTF-16 with a trailing odd byte, the views arm is
     False and only this branch fires (`rewrite_arm=True views_arm=False`, measured at `9be732bd`). Under M6 these files pass
     `--dir --check`.
   - Mutation M7 (depth cap `_depth >= 4 or` changed to `_depth < 4 and`) also survives. That one is still covered in practice:
     `container_problems` reports "gzip nested deeper than four" in `--dir` and in tree `SID_SCOPE`, and the preflight refuses
     non-UTF-8 files.
   - Incidence: 0.

4. **LOW: SID-free files get a false SID label.**
   - Because of the fail-closed branch, any file that `looks_utf16` (40% or more NUL bytes in the first 4 KiB) but does not decode is
     reported as a SID. Examples: an odd-length NUL-heavy binary, or UTF-16 with a lone surrogate.
   - `--dir --check` reports it as `identifier present`. The preflight reports `machine/domain account SID (S-1-5-21-...) in the
     content`, but only when the file is also valid UTF-8, since NUL bytes are valid UTF-8. The operator is told to look for a SID
     that is not there.
   - Reproduced: `z.bin` in finding 2 gives `FAIL z.bin: identifier present`. The probe `corrupt.py` gives
     `nul_heavy_binary_odd | find_sid_hits=True`.
   - Incidence: 0 of 1079 research-data files, and 0 of 4094 tracked files (tree `--check`: 0 findings).

5. **LOW (predates this change): the preflight prints a SID-carrying file name in full.**
   - Where: `scripts/hf_publish.py:519` and every other FAIL line build their message from `rel`. `--dir` redacts such a name to
     `file #n` (`scrub_public_identifiers.py:500`), but the preflight does not.
   - Reproduced: `pfep.py` cases `live_in_name` and `foreign_in_dir_name` print the sub-authorities on their FAIL lines
     (`echoes_subauthority=True`). The live machine's SID went to this reviewer's console. It is not written anywhere in this record.
   - Cost: agent transcripts and any review that quotes preflight output carry the machine SID. A tracked copy would be caught by
     `test_no_machine_sid_domain_in_tree.py`.

6. **INFO: a host name glued before a SID.**
   - For `<host>S-1-5-21-...`, `find_sid_hits` is False, while `scrub_bytes` with the host rule on rewrites the SID: the host rewrite
     to `__HOST__` creates the boundary.
   - This is a SID-lock/rewrite disagreement, but every check path also runs the host lock, so the file never passes. It is not a
     defect today. The property test runs `host=None` and cannot see this case.

7. **INFO: test prose.**
   - The docstring of `test_sid_rule_toggle_the_refusal_comes_from_the_sid_rule` (`tests/integration/test_hf_publish.py:1237`) is
     garbled ("the plain, UTF-16 BOM-less and gzip(UTF-16)-free cases").
   - The test isolates the SID label. It does not show that the file would be accepted with the rule off. With both SID rules off,
     the gzip and UTF-16 files are still refused as non-UTF-8 or invalid JSON.
   - The preflight docstring's claim that it reads "the escaped shapes the rewrite clears" is locked only indirectly, through the
     `find_sid_hits` tests. No preflight test uses a `%41` or ANSI shape. It works through the CLI (`pfep.py`:
     `foreign_pct41_csv`, `foreign_u0053_csv` and `foreign_ansi_csv` each give 1 SID finding).

## Round 1-3 re-verification at `9be732bd`

| finding | status | evidence |
|---|---|---|
| f1 lock encoding coverage | holds | mutation M10 (rewrite arm dropped from `find_sid_hits`) gives +45 failures |
| f2 `--dir` SID in names, gzip, zip | holds | `reverify.py`: file name, folder name, gzip and zip member each give `--check` exit 1. The gzip SID clears, with the log written |
| f3 SID_SCOPE covers tracked files | holds | `test_sid_scope_names_tracked_files` passes in the worktree |
| f3b deferred | predicate valid | the cited test id `test_dir_check_fires_before_and_is_silent_after[utf16_bom]` exists and passes |
| f4 rewrite raw vs lock views | holds | fuzz: 0 gaps |
| f5 `--dir` rewrites without a record | **reopened for a crash path** | finding 2 |
| f6 letter-glued SID deferred | behaviour unchanged | `<user>S-1-5-21-...`: lock False, rewrite 0 (consistent, as documented) |
| n1 / r1 lock narrower than the rewrite | **closed** | fuzz seeds 1 and 7, 60,000 + 150,000 inputs: payload shapes (escaped first letter, escaped dash or digit, JSON/percent/ANSI prefixes, random soup) under 0-3 JSON, percent or ANSI encodings and 0-3 containers (gzip, UTF-16 LE/BE with and without a BOM, UTF-8 BOM, nested). Result: `(changed, lock silent)` = **0**, and the lock never fires after a changing rewrite. Entry point: all 7 R1 shapes give `--dir --check` exit 1, then rewrite exit 0, then `--check` exit 0, with no sub-authority left |
| r2 property lock overclaims | **closed** | the property now uses `scrub_bytes` across 9 containers. M8 (UTF-16 branch removed) gives +63 failures and M9 (gzip branch removed) gives +35. Reverting `identity_lock.py` to `2095375c` (M1) fails all property and toggle tests |
| n2 tree file-name rules | holds | covered by the suite (60+ tests pass) |
| n3 test mandates a spare | holds | the glued-letter test still accepts either outcome |
| n4 deferred | predicate valid | not re-attacked |
| n5 `--dir` without `--log` outside a checkout | holds | exit 1 with the message |
| n6 disposition record | `verify_disposition.py`: PASS, 15 ok / 0 unjustified | the form passes. The f5 row is untrue for finding 2 |

## The preflight's SID policy and published data

- Refusing every `S-1-5-21-a-b-c`, not only the live domain, is not new. The `_SID` regex at `hf_publish.py:349` already refused
  every such value at `2095375c`. The new rule adds the gzip, UTF-16 and escaped shapes.
- Through the CLI (`pfep.py`), each of these gives 1-2 SID findings: the live SID, a foreign SID, lower case, `%41`, `S`, ANSI,
  a doubly encoded JSON record, a SID in `README.md`, a SID in a file name, a SID in a folder name, and a domain SID without a
  relative ID.
- These give 0 SID findings: `S-1-5-21-__MACHINE__-1001`, `S-1-16-*`, `S-1-15-2-*`, `S-1-15-3-*`, `S-1-5-32-544`, `S-1-5-18` and
  `S-1-5-80-*`. The test `test_preflight_passes_the_scrubbed_placeholder_and_the_generic_sids` exits 0 with `preflight: CLEAN`.
- Existing data, preflight at `9be732bd` against `2095375c`, with `allow_keys=()` and `("detail",)`:
  - `hf-export/mxc_denied_subtree`: 22 problems at both commits, 0 of them SID findings.
  - `hf-export/mxc_proxy_egress`: 25 at both, 0 SID.
  - `qwen35-9b-int8-2026-10-04`: 1378 / 1339 at both, 0 SID.
  - `qwen35-phase1-2026-10-04`: 1811 / 1756 at both, 0 SID.

  Every count is identical across the two commits, so this change refuses nothing new. The non-SID problems are column-schema
  refusals that predate it; they are outside this review. The in-repo lock `test_the_published_qwen35_datasets_preflight_clean`
  passes in the worktree.

## Attacked and could not break

- Lock against rewrite agreement: 210,000 fuzzed inputs, and the entry point on every R1 shape. Escaped first letters (`S`,
  `\x53`, either case) and escaped dashes or digits, inside nested JSON, percent encoding, ANSI codes, gzip, UTF-16 and gzip of
  UTF-16.
- The damaged-gzip shapes that raise `OSError`/`EOFError` (trailing bytes, truncation, bad CRC, magic only): the lock reports True,
  and `container_problems` reports the member.
- False positives on real data: 0 new SID refusals across 4 banked export folders; tree `--check` gives 0 findings in 4094 files;
  0 lock-only hits in 1079 research-data files.
- Refusals never echo the sub-authorities of a SID in file content (the content-path lines carry no value).

## What was run

- Hash `9be732bd`, worktree `%USERPROFILE%/BlarAI-worktrees/scrub-account-sid`, the primary checkout's `.venv` (Python 3.11.9),
  LOCALAPPDATA redirected to the reviewer's scratchpad, bash.
- In the worktree:
  - `tests/security/test_machine_sid_scrub.py`, `tests/integration/test_hf_publish.py` and
    `tests/security/test_no_machine_sid_domain_in_tree.py`: 516 passed.
  - `tests/security/test_no_host_identity_in_tree.py` and `tests/security/test_disposition_discipline.py`: 91 passed.
  - `scrub_public_identifiers.py --check`: 0 findings, exit 0.
- Mutations: in a `git archive` copy of `9be732bd` in scratch, with `--noconftest`. The baseline there has 3 environmental failures
  (no git repository, no banked qwen35 data), and every mutant count is relative to them. The standing gate was not run (brief).
- Harnesses, all in the reviewer's scratchpad `r4/`:
  - `fuzz.py`, `corrupt.py` and `ep.py`: the fuzz, the damaged-input probes and the `--dir` crash folders.
  - `pfep.py` and `pf.py`: the preflight CLI cases and the old-against-new run on the export folders.
  - `reverify.py`: the round 1-3 re-verification through the entry points.
  - `mut.py`: the mutation runs.

## Merge read

Block on findings 1 and 2.

- Finding 1 is a regression that this change introduced in the publish entry point: catch `zlib.error` wherever gzip is
  decompressed, and lock it with a damaged-deflate fixture.
- Finding 2 makes the record's `f5 FIXED` row untrue: the rewrite needs the same unreadable-input guard its lock has, reported as a
  finding, never raised mid-walk.

Lock finding 3 (a test for undecodable UTF-16 carrying `%41` + SID) in the same change. Findings 4-7 do not block.
