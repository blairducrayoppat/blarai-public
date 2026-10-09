# Standing test gate run time on a Lunar Lake laptop (2026-10-07)

Wall-clock and per-test-file time of a Python test suite (13,000 tests) on four source trees, run
back to back on one idle machine, to tell "the code got slower" from "the machine got slower". This is a
software test-suite measurement, CPU and process-spawn bound; it is not an OpenVINO inference measurement.

## Files

- `runs.csv`: one row per timed run (`arm`, `rep`, `wall_ms`, `passed`, `failed`, `total`).
- `per_file_ms.csv`: summed setup, call and teardown milliseconds per test file per run
  (`suite` is the directory, `case_id` the file name without `.py`).
- `summary.json`: conditions, per-arm statistics, sampler facts (idle seconds, power source, CPU) and notes.

## Conditions

Intel Core Ultra 7 258V (Lunar Lake), 31.32 GB, Windows 11 Pro 10.0.26200, Python 3.11.9, pytest 8.4.2,
git 2.55.0.windows.1. A run started only after 15 minutes of keyboard and mouse idle, on AC power, CPU under
15 %, no other test runner; it would have been voided on any input, any non-AC sample, an intruding runner or a
5-minute silent log. No run was voided. Predictions were written before each run.

## Result

The older tree (703.0 s and 693.0 s) and the newer tree (1631.7 s and 1687.2 s) were run alternately: 2.3 to
2.4 times apart, against run-to-run spreads of 1.4 % and 3.4 %. Twelve test files for git-hook tooling account
for 884 s of the 954 s difference; one hook-installer run started 76 git processes. Batching them (same checks,
same installed result) moved the same worktree to 1371.5 s and 1419.9 s.

## Not measured

Variance across days, CPU temperature and background scanner state, the slow test tier, and a real-checkout run
before the fix under the same instrument. Two runs per arm is a minimum, not a variance study. The
real-checkout arm runs 26 more tests than the worktree arms and is not comparable to them.

License: CC-BY-4.0.
