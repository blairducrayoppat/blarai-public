# Disposition — independent adversarial review of the parallel standing gate (#1707)

**Review:** independent adversarial-reviewer session (did not author the runner), against `e200fc79`. It ran the
runner against 17 fake trees, mutated it fifteen ways, reproduced a port-detector failure with an external holder,
and checked the one-fixture change in `launcher/tests/test_guest_parser_bridge.py` against main's copy. Verdict:
block on the silent skip and the fixed-port collision, and on the missing doctrine update.
**Author of the runner and of this disposition:** this session.
**Outcome:** every finding resolved in `a1b4650a` (runner and tests) and the adoption commit (doctrine); one
search the reviewer could not finish is ticketed with a predicate.

```disposition
P1 a file pytest skips while collecting (module-level importorskip) was dropped from the count and from the groups, so the parallel gate printed 0 skipped where the sequential gate prints 1 | FIXED | a1b4650a - collect reads the -rs SKIPPED lines, assigns the file to a group and adds its skip to the expected total; tests test_a_module_skipped_at_collection_is_assigned_counted_and_reported_as_skipped and test_parse_collect_reads_the_skipped_module_from_the_rs_lines
P2 the two integration files that bind the real ports 5001 and 5000 landed in different groups, so one could skip because the other held the port and the root conftest port-leak detector could fail a group that saw the port held at its end | FIXED | a1b4650a - SERIAL_TAIL files leave the parallel groups and run alone afterwards; tests test_serial_files_leave_the_parallel_groups_and_run_in_a_tail_of_their_own and test_the_real_fixed_port_binders_are_in_the_tail
P3 a teardown error beside a passed test was reported as a dropped test with exit 3 and a false sentence | FIXED | a1b4650a - combine accepts passed+failed+skipped+xfailed+xpassed <= expected <= that sum + errors, and exits 1 on an error; tests test_a_teardown_error_beside_a_passed_test_is_an_error_not_a_dropped_test, test_a_fixture_setup_error_is_an_error_exit_not_a_dropped_test and test_combine_accepts_an_error_that_overlaps_a_pass_and_refuses_a_real_shortfall
P4 eight mutations of the runner survived the tests (rc ignored, summary first-match, collect total first-match, errors out of the count, group markers dropped, per-group directory dropped, collect exit code unchecked, longest-first off) | FIXED | a1b4650a - tests added for each (test_a_non_zero_group_exit_fails_the_run_even_when_the_counts_are_clean, the summary tests, test_the_groups_apply_the_selection_markers_so_deselected_tests_never_run, test_a_collection_error_stops_the_run_before_any_group_starts, test_a_heavy_file_sits_alone_so_the_groups_balance); a sweep of sixteen mutations now fails a test on every one, the per-group directory claim having been removed because the root conftest isolates user data
P5 a summary-shaped line printed after pytest's own summary replaced the real counts | FIXED | a1b4650a - the summary pattern is anchored to a line that starts with '=' and the last such line wins; tests test_a_summary_shaped_text_after_the_real_line_does_not_replace_it and test_an_inner_pytest_summary_printed_by_a_test_never_beats_the_final_line
P6 no timeout and no cleanup of sibling groups on an interrupt or a failed start | FIXED | a1b4650a - GATE_TIMEOUT_S (two hours) with a kill and a failing exit, and a finally block that kills any group still running; test_a_group_that_hangs_is_killed_and_the_run_fails
P7 TEST_GOVERNANCE section 1 still said parallel groups were not adopted and the runner cited a section that did not describe it | FIXED | the adoption commit on docs/1707-adopt - section 1 gains the fast form and rule 10, rule 9 and the stamp are updated, and the testing rule file carries the fast form
P8 the runner's docstring claimed per-group LOCALAPPDATA isolation, but the root conftest overrides it | FIXED | a1b4650a - the claim is removed and the docstring names the conftest as the source of isolation
P9 a corrupt or partial weights file raised a raw traceback, and files with no banked weight were estimated ten times too high | FIXED | a1b4650a - load_weights raises a named error for an unreadable file and returns no weights for an absent one; the unweighted estimate is 0.02 s per test; test_a_weights_file_that_exists_but_is_not_one_is_a_named_error
P10 the reviewer's systematic search for other state shared between concurrently running groups did not report before the review closed | DEFERRED | #1709 blocked-by: #1709 closed - an audit of the selected tests for fixed temp names, repo-relative writes, named mutexes, unscoped process kills and other fixed ports, with a disposition record and three further clean parallel runs; seven consecutive clean parallel runs at 3, 5 and 6 groups exist but cannot rule out a rare collision
```

## Findings the review returned CLEAN

- The one-fixture change in `launcher/tests/test_guest_parser_bridge.py`: paired in one process with the two
  canary files it passes 76 tests, and main's copy of the file fails two of them; re-registering a previously
  registered callable is safe, and no test in the file expects the door to stay registered.
- Collection parsing of parametrised ids with `::`, unicode and line breaks; deterministic, disjoint, complete,
  order-preserving groups on the real 480-file collection for 1, 2, 3, 4 and 6 groups; command-line length
  (22,878 characters at one group, limit 32,767); hidden windows; closed log handles.
