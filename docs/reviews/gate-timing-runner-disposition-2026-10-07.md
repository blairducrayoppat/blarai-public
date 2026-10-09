# Disposition — independent adversarial review of the gate timing runner (#1699)

**Review:** two rounds by an independent adversarial-reviewer session (did not author the code),
round 1 against `79ea675f`, round 2 against `a88f7f56`. Round 1 blocked the merge on three
findings that each produced a false CLEAN reading or a silently dead instrument.
**Author of the runner and of this disposition:** this session.
**Outcome:** every finding resolved in `a88f7f56` or `0cc957e0` or the commit that carries this
record; three round-2 items are recorded as accepted limits with the observable that would change that.

```disposition
R1-1 a run on battery was recorded CLEAN because power was enforced only on a reading taken about 21 s before the process started, and the baseline passed to the void check was the reading at the start | FIXED | a88f7f56 - execute() re-reads AC and idle immediately before Popen and refuses unless AC is True; void_reason now requires AC at every sample; tests test_battery_at_the_start_though_ac_at_the_probe_is_refused_by_execute and test_power_lost_mid_run_voids_it
R1-2 input in the roughly 50 s around the start was never detected because the void test compared idle with elapsed minus a 30 s grace | FIXED | a88f7f56 - void_reason(idle_s, elapsed_s, idle0_s, ...) voids when idle falls below idle0 + elapsed - 2 s, with idle0 read just before the process starts; tests test_input_a_moment_after_the_start_voids_the_run_and_requeues_it and test_input_between_the_tick_probe_and_the_start_is_caught_at_the_start
R1-3 a lock file whose pid was reused by a long-lived process disabled the instrument silently and permanently | FIXED | a88f7f56 - take_lock is O_EXCL holding pid plus process start time, a reused pid is taken over and a live holder is logged; test_a_lock_whose_pid_was_reused_is_taken_over_and_a_live_holder_is_respected
R1-4 any process whose command line mentioned the word pytest counted as a test runner, including Claude tool shells | FIXED | a88f7f56 - is_pytest_cmdline matches what executes; narrowed again in 0cc957e0 to the executable or its first script argument or -m pytest; test_a_test_runner_is_what_executes_not_a_word_in_the_arguments
R1-5 under pythonw every tick crash was invisible | FIXED | a88f7f56 - tick() catches BaseException and writes the traceback to ticks.log; test_a_crash_in_the_tick_is_written_to_the_log_with_its_traceback
R1-6 a dead tick orphaned the gate and the next tick reported the orphan as dead while it kept running | FIXED | a88f7f56 - gate_pid and gate_ctime persisted, reap_dead_running kills the orphan tree when pid and start time match; tests test_a_dead_tick_leaves_an_orphaned_gate_that_the_next_tick_kills and test_a_reused_gate_pid_is_not_killed
R1-7 MAX_VOIDS was off by one and the test locked the wrong number | FIXED | a88f7f56 - requeue stops at exactly MAX_VOIDS and logs that the plan was abandoned; test_requeue_stops_exactly_at_the_cap
R1-8 parse_summary only worked because the repository addopts cancel the runner's -q | FIXED | a88f7f56 - -q dropped from the gate command so the summary line is printed at default verbosity
R1-9 the tests certified the pure functions and nothing drove tick, execute, the lock or the reaper | FIXED | a88f7f56 - Scene-based end-to-end tick tests with a scripted clock and a two-second fake gate; extended in 0cc957e0 with stall, intruder, cannot-start and missing-state cases
R1-10 requeue appended, so alternation was lost after the first void | FIXED | a88f7f56 - the repeat is inserted directly after the voided run; test_a_voided_run_is_repeated_next_so_the_alternation_holds
R2-1 taskkill opened a visible console window on the operator's screen under the pythonw task | FIXED | 0cc957e0 - CREATE_NO_WINDOW on kill_tree
R2-2 an exception between the RUNNING save and Popen left the entry RUNNING with no gate pid and burned the void cap with a misleading reason | FIXED | 0cc957e0 - Popen is guarded and the run is voided with the exception text; test_a_gate_that_cannot_start_is_voided_with_the_cause
R2-3 an empty lock file was treated as stale | FIXED | 0cc957e0 - an empty lock younger than 5 s is a tick mid-write and is respected; test_an_empty_fresh_lock_is_a_tick_mid_write_not_a_stale_lock
R2-4 a missing state directory crashed before the try and left no trace under pythonw | FIXED | 0cc957e0 - tick creates the directory and logs the cause; the registration script refuses a StateDir without state.json; test_a_missing_state_is_logged_not_silent
R2-5 other_test_runners takes about 7 s per call on this box so the effective sample period was far above SAMPLE_S | FIXED | 0cc957e0 - the process scan runs every INTRUDER_SCAN_S (60 s) and the docstring states the real cadence
R2-6 matcher edges: any argument whose basename was pytest matched, and -mpytest did not | FIXED | 0cc957e0 - only the executable or its first argument or -m pytest or -mpytest match; three added cases in the parametrized test
R2-M24 the lock for R1-1 exercised the tick probe, not execute(), so removing the re-read stayed green | FIXED | 0cc957e0 - test_battery_at_the_start_though_ac_at_the_probe_is_refused_by_execute
R2-M29 gate_pid persistence was unlocked at the seam, and the per-run LOCALAPPDATA redirect had no assertion | FIXED | 0cc957e0 - the clean end-to-end test asserts gate_pid, gate_ctime and the la-run directory
R2-M30 mid-run intruders and stalls were covered only as pure functions | FIXED | 0cc957e0 - test_another_test_runner_appearing_mid_run_voids_the_run and test_a_silent_log_voids_the_run_as_a_stall
R2-M16 dropping /T from taskkill survived because the orphan test's process had no children | FIXED | feat/1699-timing-runner (tests/security/test_gate_timing_runner.py, the tip commit that carries this record) - the orphan test now spawns a grandchild and asserts it dies
R2-M19c the same_process guard on the recorded gate pid had no test in the dangerous direction | FIXED | 0cc957e0 - test_a_reused_gate_pid_is_not_killed
```

## Accepted limits (stated, not deferred)

- A run can still be voided by a stray test runner started by another Claude session during the
  window; that is the intended behaviour and costs a repeat, bounded by `MAX_VOIDS`.
- The idle clock is the interactive session's. Remote input or a service holding the session
  awake without input does not register as input; the 15-minute idle precondition and the
  samples.csv record of idle seconds are what a reader can check afterwards.
