# Parallel standing gate (#1707), runs of 2026-10-08

`scripts/run_standing_gate.py` runs the standing selection as concurrent pytest processes over disjoint groups of
whole files. The files here are the runner's own output for every run, in order, kept because the early failures are
the evidence for the fixes.

| file | groups | tree | result | wall clock |
|---|---|---|---|---|
| 01 | 4 | primary, before the order fix | 13253 passed | 730.3 s |
| 02 | 6 | primary, before the order fix | 1 failed (a canary test: the launcher bridge test left the egress door's URL adjudicator registered) | 677.6 s |
| 03 | 3 | primary, before the order fix | 13253 passed | 704.1 s |
| 04-06 | 3 | primary, files kept in collection order | 1 failed each run (the same leak, found by tracing) | 866.9, 850.4, 877.0 s |
| 07 | 3 | worktree with the fixture fix | 5 failed (environmental), 26 skipped, 13238 passed | 809.6 s |
| 08-10 | 3 | primary at `dda7e90a` | 13288 passed, three consecutive | 848.7, 894.6, 894.1 s |
| 11 | 5 | primary | 13288 passed | 767.9 s |
| 12-14 | 6 | primary | 13288 passed, three consecutive | 704.3, 700.8, 708.6 s |
| 15 | n/a | the tracing run that named the leaking test | `pollution_tracer.py` is the pytest plugin used | n/a |

Conditions: Intel Core Ultra 7 258V (Lunar Lake, 8 cores), Windows 11 Pro, elevated, app down, `LOCALAPPDATA`
redirected, `scripts/gate_weights.json` from two idle real-checkout durations logs. These runs were NOT started by
the idle-gated timing instrument, so the operator may have been at the machine for some of them; the sequential
figure of the same code (`c5b83a31`, 13253 tests) from the instrument is 1448.0 s. The "x7" in the result line of 08-14
is 6 (or 3) parallel groups plus the serial tail. Wall clock includes the single collection pass (about 40 s).

What the early runs found: files had been ordered alphabetically inside a group, which put a test that leaves the
egress door's URL adjudicator registered in front of canary tests that expect it clear; the sequential order had
hidden this because a later file cleared it. Files now keep their collection order inside a group, and the leaking
fixture restores what it found.

Not measured: temperature or background scanner state, runs with the operator verifiably away, more than 6 groups.
Two of the three files that bind real ports appear in the selection; the serial tail holds them.
