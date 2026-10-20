# Review: #1786 volume-serial identity lock (adversarial, independent)

Branch `fix/volume-serial-lock` at `d366b5ea` (commits 3209b08a, db3120c4, 1f490c0f, d366b5ea; diff `677f9344..d366b5ea`). Merge simulated as `git merge --no-ff` into main `a92fef81` in a scratch clone (merge commit 457184fa there, never pushed). Reviewer did not write or fix any code. No serial, account name or host name appears here; live serial checks were run in-process and print only verdicts.

**Verdict: FAIL** (one blocker: merged main fails `--check` and the tree lock).

## Findings, most severe first

1. **BLOCKER: the merge into current main fails `--check` (exit 1) and will fail `test_tree_is_clean`.** `tools/probes/nono_9p_failclosed_control.py:1944` (landed with #1755 at 34759bca, after this branch's base) has a self-test fixture `" Volume Serial Number is <synthetic dashed serial>"`. The value is not this machine's serial, but the header rule fires on any machine's serial by design. Reproduced: in the merged clone, `python scripts/scrub_public_identifiers.py --check` gives `FAIL tools/probes/nono_9p_failclosed_control.py: volume serial present (a 'Volume Serial Number is' header)` and `1 finding(s) in 4057 tracked files` (exit 1, 139 s). Incidence 1 file. The journal fragment's "--check reads 0" holds only at 677f9344. **Fix:** in the merge, write the fixture's serial as the placeholder `XXXX-XXXX`. `dir_entry_lines` drops the header line either way, so the #1755 self-test assertion is unchanged. Then re-run `--check` on the merge.

2. **MEDIUM: the `0x` hex form is missed by both the lock and the rewrite, and that is the form `fsutil` and Python `hex()` print.** `scripts/identity_lock.py` `_SERIAL_HEX8_RE`/`_SERIAL_DASHED_RE`/`serial_res`. The `(?<![0-9A-Za-z])` lookbehind treats the `x` of `0x` as glue. The module docstring says the serial is "printed by dir, vol and fsutil", but fsutil's `Volume Serial Number : 0x<hex8>` passes both rules. Reproduced with the live serial: `0x<live lower>`, `0X<live upper>` and `hex(serial)` all return `[]`, and scrub count=0. Incidence in the merged tree: 0 files. **Fix:** accept an optional `0[xX]` prefix as a token boundary in the dashed/hex8 find regexes and in `serial_res`, add `0x` shapes to `SERIAL_LIVE_SHAPES`, and correct the docstring's fsutil claim or add the fsutil header shape (`Volume Serial Number\s*:\s*0x<hex8>`) to the header rule.

3. **LOW: the lock is weaker than the rewrite on zero-padded decimals.** `_SERIAL_DEC_RE` caps at 10 digits but `serial_res` accepts `0*`. With this machine's serial (10 decimal digits), `0<decimal>` is missed by the lock, while the rewrite clears it. That holds for about 77% of the 32-bit space. Synthetic serials also show: signed-int32 decimal is missed for serials >= 2**31; unpadded hex / dashed-unpadded is missed for serials < 0x10000000. Neither applies to this machine (incidence 0). **Fix:** make the decimal find regex `0*[0-9]{1,10}` to match the rewrite, and list the signed and unpadded forms in the honest limit.

4. **LOW: header rule misses that the honest limit does not name.** These shapes all return `[]`: a non-breaking space inside the label, a line break between `is` and the serial, and the fsutil `:` shape. Localised labels (German, French, Spanish) also return `[]`, but those are documented. Reproduced via `scratchpad/probe1786.py`. **Fix:** use `\s` in place of `[ \t]` in `SERIAL_HEADER_RE` (that covers NBSP once decoded, and newline) and name the remaining shapes in the honest limit.

5. **LOW (lock gap): two call sites can be removed with no test failing.** (a) In `verify_community_scrub.apply_subs`, reverting the `rewrite_serials` line leaves 8/8 passing (reproduced). (b) The in-place scrub `main()` serial path (serials passed to `scrub_bytes`, the serial residual check, the serial file-name list): no #1786 test calls `scrub.main` with a serial planted. The pre-existing main() tests are at lines 363-467, and none plants one. Revert NOT RUN (dropped for time), so this is a hypothesis from the call graph. **Fix:** add one `scrub.main([...])` test on a scratch repo that plants a header and a live serial and asserts the rewrite, the log count and the residual; and one verifier test where `apply_subs` must clear a header.

6. **LOW: `test_published_datasets_still_preflight_clean` claims more than it checks.** It filters to serial hits only, so another preflight rule regressing on those datasets would still pass it. Measured directly: a full `hf_publish.preflight` on qwen35_small_2026-10-04, qwen35_small_9b_2026-10-04 and the containment-evidence hf-export gives 0 hits at 1x and 20x max_bytes, in the merged tree. **Fix:** assert `preflight(...) == []`, or rename the test to say serial-only.

7. **LOW: a failing test can print the live serial into pytest output.** Two assertions, when they fail, echo text that carries it: `assert body in src.read_text(...)` (rotation test) and `... and "XXXX-XXXX" in out` (export test). Gate logs land in %TEMP%, not the tree, but they are sometimes banked. Planted fixtures also stay in pytest's basetemp. **Fix:** compare `_carries(...)` sets / booleans with a fixed message, never the planted text.

## Digest strength (attack 1)
Digests are computed in memory from the live read and never pinned or written. Every hit message names a rule, never the value. `hf_publish._serial_digests` is an in-process `lru_cache`. I found no write of a digest to disk or logs. The only leak path found is finding 7.

## Fail-closed (attack 1)
Each consumer refuses on empty: `live_volume_serials()` returning empty refuses at hf preflight, the export scrub, the verifier, phase1, rotate_log, `check()` and the scrub's `main()`. Toggle-reverting the empty-guards in the hf preflight and in `check()` failed named tests. An unreadable GetVolumeInformationW on every volume gives an empty set, which then refuses. On a machine with no fixed volume, the same.

## Call-site reverts (attack 3), scratch clone at d366b5ea
Each revert made a named test fail:
- hf content: 3 failed
- hf file name: 1
- hf fail-closed: 1
- export rewrite: 1
- verifier residual: 1
- phase1 rewrite: 1
- phase1 post-check: 1
- rotate_log: 2
- check() content: 1
- check() name: 1
- check() unreadable: 1
- scrub_text header rewrite: 1
- decimal rule: 1
- upper() case rule: 1
- views: 2

These reverts failed no test: the verifier `apply_subs` rewrite. NOT RUN: the scrub `main()` serial path (finding 5).

## Wall time (attack 6): `tests/security/test_no_host_identity_in_tree.py` alone, same box, other agents active
| run | tree | tests | wall |
|---|---|---|---|
| 1 | 677f9344 | 48 | 175 s (a `--check` ran concurrently for part of it) |
| 2 | d366b5ea | 71 | 226 s |
| 3 | 677f9344 | 48 | 114 s |
| 4 | d366b5ea | 71 | 188 s |

n=2 per arm on a noisy box. The serial rules add roughly 40-75 s, about +30-65%. That is within the box's known variance, so read it as an estimate, not a measurement.

## Attacked and could not break
- The live serial in these forms is found: dashed upper and lower, bare hex in either case, decimal, the JSON `\n` and `-` escapes, a percent-escaped dash, an HTML-entity dash, UTF-16 with and without BOM, gzip, and underscore glue.
- No false positive on the placeholder, on prose ("is printed by", "is a 32-bit", "is 8 hex digits"), on git SHAs, or on dates.
- The foreign twins stay clean.
- The rewrite is idempotent.
- `git merge --no-ff` onto a92fef81 has no textual conflicts.

## Not run
- The launcher, doctrine, nep0005 and doc-pointer suites, and the full hf_publish/export/phase1 suites, on the merge (the team lead stood these down; the standing gate on the merge covers them).
- The scrub `main()` revert.

# Round 2 (2026-10-15)

Tested at `19a6b5fa` (fix pass 9593cf97 merge of main 21226e13, a7f4d16d findings 1-7, 19a6b5fa redact_serials), in a scratch clone. Main is `21226e13`, already an ancestor of the branch, so `git merge --no-ff` of main reports "Already up to date" and the merged tree is the branch tree. No serial, account or host name is written here. Live checks print verdicts only.

**Verdict: PASS.** Round-1 findings 1-7 are closed. Two LOW findings are new; neither blocks.

## Round-1 findings: closed, each with a revert that fails a named test (scratch clone, the file restored after each)
| R1 | fix | revert | named test that fails |
|---|---|---|---|
| 1 | #1755 fixture reads `XXXX-XXXX`; `find_serial_hits` on the file = set(); `--check` **0 findings in 4063 tracked files, exit 0**; `nono_9p_failclosed_control.py --self-test` **1275 checks, 0 failed, 1 skipped** (pty, not on this host) | (header rule shown firing on a synthetic serial in round 1) | test_tree_is_clean (round 1 reproduction) |
| 2 | 0x prefix in find regexes and in serial_res; fsutil `:` header | prefix out of find regexes / out of serial_res / fsutil alternative out | 3 failed (test_toggle_live_serial_shape x2, test_redact_serials_...) / 1 (test_rewrite_replaces_every_serial_form) / 3 (test_toggle_header_with_a_foreign_serial x2, test_rewrite_...) |
| 3 | `0*` in `_SERIAL_DEC_RE`; signed/unpadded named in the honest limit | `0*` out | test_toggle_live_serial_shape_is_found... (1) |
| 4 | `_WS = \s or NBSP` | back to `[ \t]` | test_toggle_header_with_a_foreign_serial_is_found (2: line-break and NBSP cases) |
| 5 | verifier apply_subs test; scrub.main tests | apply_subs rewrite out / serials not passed to scrub_bytes / residual check out / name list out | test_verifier_apply_subs_clears_a_header_and_a_live_serial / test_scrub_main_rewrites_a_planted_serial... / test_scrub_main_reports_a_serial_it_cannot_rewrite... / same |
| 6 | published-dataset test asserts the full preflight is empty | not reverted | (round 1: full preflight 0 hits on all three) |
| 7 | `PYTEST_DONT_REWRITE` in both new modules' docstrings (the first statement, which is where pytest reads it); every assert is a plain condition with a fixed message | 13 reverts run; output scanned for the live serial by digest | the assertion text leaked nothing in any revert (but see R2-1) |

redact_serials (19a6b5fa): reverting it in `check()` fails test_check_output_never_prints_a_serial_a_file_name_carries; in the scrub.main log, fails test_scrub_main_reports...; the encoded-form fallback, fails test_redact_serials_replaces_every_live_form....

## New findings
**R2-1 LOW: a failing test_scrub_main_reports_a_serial_it_cannot_rewrite_and_a_serial_in_a_file_name prints the live serial into pytest output, through git, not through an assertion.**
- Where: `tests/security/test_volume_serial_lock.py:81`. `_commit` runs `git add -A` without capturing output.
- What happens: on this checkout git warns "in the working copy of 'docs/s/run-<live dashed serial>.txt', LF will be replaced by CRLF" on stderr. pytest captures that and shows it only when the test fails.
- Reproduced: I reverted the scrub.main name list (and, separately, the log redaction). The test failed, and its output carried the live serial by digest. My locator printed that line with the serial redacted. With the test passing, nothing is shown.
- Cost: whenever this test fails for any reason, the serial lands in the gate log in %TEMP%.
- Fix: pass `capture_output=True` to both `subprocess.run` calls in `_commit` (and give `check=True` a fixed message), or set `-c core.autocrlf=false`.

**R2-2 LOW: no test guards the redaction in the hf preflight.**
- Where: `scripts/hf_publish.py:560`.
- Reproduced: reverting `_il.redact_serials(h, ...)` to `h` leaves test_serial_call_sites.py 18/18 passing.
- Fix: one test plants a file whose name carries the live serial, calls `preflight()`, and asserts (plain condition, fixed message) that no returned line trips `find_serial_hits` and that one line carries `XXXX-XXXX`.

## Does redact_serials leak anything itself
- It returns placeholders, or a fixed notice. It never returns a digest, an index into the serial set or a partial value.
- The `tracked file #N` that `check()` adds is an index into the tracked-file list. It locates the file, not the serial: someone who can read the tree already has the name, and a report read without the tree learns nothing from N.
- With no digests it redacts only header serials. That case arises only when the serials are unreadable, and every caller already fails closed then.

## Not run
- The full standing gate. The team lead assigns it to the merge.
- The pty half of the #1755 self-test, which needs WSL.
