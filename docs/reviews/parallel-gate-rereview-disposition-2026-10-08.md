# Disposition — second round of the independent review of the parallel standing gate (#1707)

**Review:** the same independent adversarial-reviewer session, run against `c2215194`. It re-ran its attack trees,
mutated the runner twenty-two ways and read the fixes for new problems. Verdict: nothing blocks; the two blocking
findings of round one are closed by reproduction, and it listed the follow-ups below.
**Author of the runner and of this disposition:** this session. Fixes are in `feat/1707-followups`.

```disposition
Q1 a group whose files were all skipped at collection exits pytest 5 and the run exits 1 with no sentence naming why | FIXED | feat/1707-followups (scripts/run_standing_gate.py group_rc_ok) - exit 5 is accepted when the group's own counts show no failure and no error, and any other non-zero exit with clean counts is named in a GATE line; tests test_a_serial_tail_whose_files_are_all_skipped_at_collection_is_not_a_failure, test_a_group_that_exits_non_zero_with_clean_counts_is_named and test_which_group_exit_codes_are_acceptable
Q2 the result line counted the serial tail as a group, so a 6-group run printed x7 where rule 10 and the stamp say 6 | FIXED | feat/1707-followups - the line prints (parallel x6 + serial tail); tests test_the_result_line_names_the_parallel_groups_and_flags_the_serial_tail_separately and test_the_line_of_a_real_run_with_a_tail_says_the_group_count_asked_for
Q3 parse_collect truncates a path that contains a space, and a trailer without a deselected count makes the total cross-check void | DEFERRED | #1710 blocked-by: #1710 closed - reproductions and the fix shape are on the ticket; neither is reachable in the current selection (no spaces in test paths; 620 deselected keeps the N/M trailer)
Q4 a package-level skip in an __init__.py is counted once per test file in the package and produces a false exit 3 | DEFERRED | #1710 blocked-by: #1710 closed - fail-loud rather than lenient, and no skipping __init__.py exists in the selection
Q5 GATE_TIMEOUT_S is not registered in shared/timeout_registry.py although the testing rule says new timeouts register | FIXED | feat/1707-followups (shared/timeout_registry.py) - registered as a budget with its rationale and review trigger; tests/integration/test_timeout_registry.py cross-checks it against the live constant and passes
Q6 SERIAL_TAIL presence was not verified on disk, so a renamed fixed-port file would silently rejoin the parallel groups | FIXED | feat/1707-followups - test_every_serial_tail_file_exists_in_the_repository
Q7 the union check accepts one dropped test per unrelated teardown error | REJECTED | argued: an error always forces exit 1, so the case can never produce a clean exit; it is a message-fidelity limit and the docstring of combine states it
Q8 two mutants survived: longest-first balancing off, and the kill of a timed-out group's process | FIXED | feat/1707-followups - test_the_heavy_file_sits_alone_wherever_it_is_in_the_collection_order and test_a_timed_out_group_leaves_no_process_behind; a sweep of the new fixes fails a test on all seven mutations
Q9 a summary-shaped line printed after pytest's own full-width summary still replaces the counts | REJECTED | argued: the union check and the group exit code are the backstops, the reviewer showed both hold (exit 3), and no such line exists in the real group logs
Q10 the reviewer's search for other state shared between concurrent groups never returned | DEFERRED | #1709 blocked-by: #1709 closed - already ticketed after round one with the categories to cover
```
