# Standing-gate run time, control experiment (#1699), 2026-10-07

What this is: wall-clock and per-file time of BlarAI's standing test gate on two source trees, run
alternately on one idle machine, to separate "the code got slower" from "the machine got slower".

## Conditions (every timing run)

- Hardware: Intel Core Ultra 7 258V (Lunar Lake), 32 GB LPDDR5X (31.32 GB usable), Windows 11 Pro 10.0.26200.
- Python 3.11.9 (the repository's runtime venv), pytest 8.4.2, `-p no:cacheprovider --durations=0 -rfs`,
  default `addopts` of the repository; `LOCALAPPDATA` redirected to a fresh directory per run; elevated.
- Selection: `shared/ services/ launcher/ tests/integration/ tests/security/ -m "not hardware and not winui and not slow"`.
- Started by `scripts/gate_timing_runner.py` only when keyboard and mouse input had been idle for at
  least 15 minutes, on AC power, CPU below 15 %, no other pytest alive. The runner samples idle seconds,
  power source and CPU every 10 s (`*.samples.csv`) and would have voided a run on any input, any non-AC
  sample, an intruding test runner or a 5-minute silent log. No run was voided.
- Both trees ran as git worktrees under `BlarAI-worktrees/` with no gitignored assets (no model weights),
  so some tests fail or skip for environmental reasons in both arms (below).

## Runs

| run | tree | started (-04:00) | idle at start | wall clock | pytest | result |
|---|---|---|---|---|---|---|
| 1 | old `3be0e22e` (2026-09-22) | 17:07:04 | 993 s | 703.0 s | 690.57 s | 7 failed, 12049 passed, 30 skipped, 133 deselected |
| 2 | new `ca4fab46` (main before #1703) | 17:22:05 | 1894 s | 1631.7 s | 1619.97 s | 5 failed, 13148 passed, 26 skipped, 620 deselected |
| 3 | old `3be0e22e` | 17:52:04 | 3693 s | 693.0 s | 682.97 s | 6 failed, 12050 passed, 30 skipped, 133 deselected |
| 4 | new `ca4fab46` | 18:07:04 | 4593 s | 1687.2 s | 1667.64 s | 5 failed, 13148 passed, 26 skipped, 620 deselected |

Repeatability: old arm 703.0 / 693.0 s (1.4 % apart); new arm 1631.7 / 1687.2 s (3.4 % apart). The arms
differ by 2.3 to 2.4 times, an order of magnitude more than either spread. Both arms ran back to back on
the same machine, so the difference is the code, not the box.

## Where the difference is

Mean summed test time per run (setup + call + teardown from the `--durations=0` section; tests under
5 ms are omitted, so the sums sit 2 to 5 % under the pytest wall clock): old 651 s, new 1605 s, a net
difference of 954 s. `per_file_summary.json` lists it per file. The twelve test files for the git-hook
tooling added by #1690 account for about 884 s of it: `test_git_update_consent.py` 275 s,
`test_git_swap_and_handshake.py` 197 s, `test_git_install_hardening.py` 141 s, then eight files between
10 and 54 s and one under 10 s. None of them exist in the old tree.

Profile of the cause (single install on this machine, not a gate run): one run of
`scripts/install_git_hooks.py` took 2.8 s and started 75 git processes at about 36 ms each in the author's single profile (the reviewer's matched, interleaved pair, median of 8: 3.05 s and 76 processes before, 0.97 s and 18 after) (36 file
hashes, 22 blob reads, 11 repeated common-directory lookups). Most of those tests install a fresh
repository once or twice per test.

## Environmental failures and skips (same classes in both arms)

Five failures in both arms: three tests that need the 14B model directory and two that follow relative
links to a sibling `devplatform` checkout, both absent from a worktree. The old arm adds
`test_the_refresh_date_does_not_trail_main` (an old tree's ROADMAP date trails the live main, by design of
the control) and, on run 1 only, `test_graduation_reset_stamps_current_mode_immediately` (an `os.replace`
"Access is denied" on a pytest temporary file; it did not recur on run 3). Skips are missing-model and
missing-docset-index skips. Counts reconcile to the selected totals (12086 and 13179).

## Not measured

- A real-checkout timing run on an idle box: the real-checkout figures in `correctness_runs/` were taken
  while the operator was at the machine (1559 s, 1661 s) and are not timing figures.
- Variance across days, thermal state of the CPU, antivirus scan state (the per-process start cost looks
  scanner-sensitive but this was not isolated), and the slow tier (612 tests deselected from the gate).
- Two runs per arm is the minimum the plan called for, not a variance estimate for the new arm.

## Files

`timing_runs/` the four logs (gzip), samples, `state.json`, `ticks.log`, the predictions written before
the first run, and notes. `correctness_runs/` three `--durations=0` runs taken with the operator present.
`per_file_summary.json` is produced by `scripts/gate_duration_report.py --arm old=run01-old.log.gz,run03-old.log.gz --arm new=run02-new.log.gz,run04-new.log.gz --top 14`.
`post_fix_runs/ticks.log` and `timing_runs/ticks.log` are the runner's own logs. `timing_runs/predictions.txt` and `post_fix_runs/predictions_both_plans.txt` are
the prediction files as they stood at the start of each plan; the first plan's prediction time is established by `notes.txt` (written 17:19, quoting it)
and by the runner having waited from 15:47 until 17:07 without starting.
