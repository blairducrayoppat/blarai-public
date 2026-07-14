### 2026-07-13 — The second watchdog, and the name of the kill

*Plain summary: shipped the LAST C2-inc-2 limb — the stop-doomed-fast patterns from
the dispatch harness's `monitor.py` promoted into driver-integrated checks:
`shared/fleet/doom_check.py` (a `DoomWatchdog` sibling of `BudgetWatchdog`) wired
into `swap_driver`/`swap_ops`, DORMANT behind `[coordinator].swap_doom_checks_enabled`.
This closes #844. Two catches worth keeping: the arming condition is structural
(child-registered), and the shared stop event would have silently mislabeled doom
kills as budget-timeouts — the #757 lesson re-applied at a new stop source.*

The swap-path limb was the one the whole increment had been sequenced around — it
touches `swap_driver`/`swap_ops`, the live model-swap machinery the nightly battery
runs — and the design that made it safe to land was recognizing that the driver
already contains the exact shape the promotion needs. The budget watchdog is an
out-of-band daemon with three load-bearing properties earned across #670/#757/#758:
per-run instances (never globals), a stop that joins unbounded only after `finished`
is set, and an abort made structurally inert at teardown entry so a late fire can
never act during the 14B restore. The doom watchdog is that pattern's sibling, not a
new invention: same thread idiom, same `request_stop`/`abort` wiring through the same
`_CurrentChild` holder — which means every teardown guarantee the budget watchdog
earned, the doom watchdog inherits for free. The interesting judgment was what NOT
to copy from the harness. `monitor.py`'s predicate carries four rules for inferring
run state from outside a process it doesn't own — SUMMARY-vs-terminal-phase (#686),
run-id-scoped phase trust. The driver needs none of them: it *is* the phase owner
and it *knows* when a task child is in flight. What remains is the predicate's core —
no watched-artifact advance, no coder CPU, two confirming samples, the registered
240 s grace — plus one condition the harness could never have: the check only ARMS
while a run-fleet child is actually registered. Only the live run-task path
registers one; the driver's own phases (loads, wave gates, critic, design, teardown)
never do. The night-20260709 B4 false-doom — a verify gate read as a dead run — was
fixed in the harness by widening a grace window and a process-name list; at the
driver's vantage that failure class is closed *structurally*, which is the whole
argument for the promotion.

The second catch is the one I nearly shipped wrong. The doom stop rides the same
per-run stop event the budget watchdog sets — correct reuse; the CODE loop already
honors it at task boundaries. But everything downstream of that event *names the
budget*: the driver's stop tuple says "the overall run budget elapsed," and the #757
honest-kill relabel — built precisely so a tree-killed task never reads as a
mystery — writes "the overall run budget elapsed mid-task" into the task detail.
Wire the doom watchdog naively and every doom kill would be reported as a budget
timeout: a *mislabeled* kill, which is the exact diagnostic-cycle burner #757
existed to close, reintroduced at a new stop source while the module doc cites the
lesson. So the watchdog records `fired`, the driver's stop labeling discriminates
(`doom-stop`, its own outcome word and message), and the relabel — factored out of
its closure into a pure, unit-tested function — names the true killer in the task
detail. Both detail families deliberately keep the `TIMED OUT` prefix so the
cumulative SUMMARY still round-trips to `TIMEOUT` (#686's shape-divergence class);
the honesty lives in *which* killer the text names, not in inventing a new result
word for the parser.

The promotion also settled a drift risk. The harness and the driver must never
disagree about what "the run is doing work" means, so the process-name list and CPU
threshold moved to `doom_check.py` as their single source of truth — every B4 scar
(`uv`/`ruff`/`git`) intact, values byte-identical — and `monitor.py` now imports
them back. Dormancy is triple: the TOML flag ships false, the dispatch spec doesn't
carry the key at all (absent resolves to None, the #744 fail-closed spec pattern —
a pre-#844 spec re-read after a crash recovery behaves identically), and the
driver's parameter defaults to None — with the existing exact-call-list tests plus
a new byte-identical lock proving the legacy path unchanged. `DOOM_STALL_GRACE_S`
registered in the timeout registry in the same change, in named lockstep with the
harness's `stall_grace_s` — one physical quantity, two vantages, changed together.

**Next:** #844 closes with this limb — C2 lifecycle coordination is fully landed
(inc-1 decision core + six inc-2 limbs, every one dormant behind `[coordinator]`).
C3 (#845, the heartbeat — BlarAI's first autonomous wake) begins with a design
checkpoint brought to the Lead Architect, not with code.

*(commit `b824c88c` — the C2 swap-doom-checks limb; new `shared/fleet/doom_check.py`
(+40 tests in `shared/tests/test_doom_check.py`), `DoomWatchdog` lifecycle +
doom-aware `_stop_labels` in `swap_driver.py`, `is_child_registered` +
`relabel_unexplained_kill` + `build_doom_watchdog` + `run_swap` wiring in
`swap_ops.py`, the `swap_doom_checks_enabled` flag in `shared/coordinator/config.py`
+ `default.toml` (+1 test, 2 extended), the registry entry in `timeout_registry.py`
(+1 parametrized gate case), the constant re-point in
`tools/dispatch_harness/monitor.py`; +42 gate tests total (the commit body's "+43"
overcounted by one — the measured delta is authoritative); independent
author≠verifier review MERGE-READY — all 10 claims CONFIRMED, 0 refuted, the
byte-identical dormant path verified against `git show main:` at every stop site,
2 informational notes (go-live is deliberately NOT a TOML-only flip — the spec
writer must thread the flag, recorded on #844); standing gate 7909 passed /
0 skipped / 0 failed, elevated + LOCALAPPDATA-redirected, 5:47. DORMANT —
triple-gated, byte-identical legacy path.)*
