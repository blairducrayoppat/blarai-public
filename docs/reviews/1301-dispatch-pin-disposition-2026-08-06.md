---
title: "#1301 dispatch-scripts pin — independent review disposition"
status: evidence
area: governance
date: 2026-08-06
---

# Disposition — independent review of `fix/1181a-pin-dispatch-scripts` @ `794de269`

Reviewer: an independent session that did not author the branch and fixed nothing
(author != verifier). Verdict: **REFUSE** — 3 BLOCKING / 5 SHOULD-FIX.

Every load-bearing claim was then re-verified against source by the session banking it,
rather than carried on the reviewer's word. `dispatch.py:1110`, the guarded/bare asymmetry
between `swap_ops.py:3742-3745` and `swap_ops.py:3977`, the two unchanged real-root gate
tests on `main`, and the cross-repo absence all confirmed verbatim. A review is evidence
only to the extent someone checked it.

## Why every row below is DEFERRED rather than FIXED

**The branch is unmerged and currently INERT.** Its writer half is not on `agentic-setup`
`main` (`git grep BLARAI_FLEET_SCRIPTS_DIR main -- scripts/` returns nothing) and
`state/fleet-swap/pins` does not exist on disk. Nothing on the box reads a pin declaration
today, so none of these findings describes a live defect. They describe what happens the
moment the sibling half lands.

That is what makes the predicate below the right one: these findings do not become urgent
on a date, they become urgent when a specific, observable thing appears on disk. Until then
the correct action is that the branch does not merge — which is a gate, not a delay.

The second reason is scheduling and it is named honestly: these are edits to the live
dispatch path, and this disposition is written 2 h 15 m before a 23:00 nightly battery that
runs that path. A dispatch-path change wants a soak window.

```disposition
B1 BLOCKING build_default_config() resolves scripts_dir off the operator's REAL state root and psutil-probes live pin declarations, so during any pinned run the unchanged compiled-in-fallback assertion at tests/integration/test_fleet_dispatch.py:423 goes False, and two further sites (shared/tests/test_fleet_dedup_guard.py:113, tests/integration/test_smoke_contract.py:402) silently RETARGET or SKIP instead of failing | DEFERRED | #1301 - blocked-by: the file `C:/Users/mrbla/agentic-setup/state/fleet-swap/pins` existing on disk, or the symbol `BLARAI_FLEET_SCRIPTS_DIR` appearing under `scripts/` on agentic-setup `main` - either one arms this finding, and neither is true today
B2 BLOCKING the PRIMARY refusal lock at shared/fleet/swap_ops.py:3977 (the path entrypoint.py actually uses) has no test proving it BLOCKS - every occurrence of scripts_pin_violation in the suite is the empty case or a monkeypatch target, so deleting lines 3977-3982 leaves the suite green, violating security_by_design principle 12 | DEFERRED | #1301 - blocked-by: the absence of a test asserting `execute_swap_dispatch` returns ok=False on a pin mismatch - observable by deleting shared/fleet/swap_ops.py:3977-3982 on the branch and watching the suite stay green
B3 BLOCKING the corrupt-declaration guard was applied at shared/fleet/swap_ops.py:3742-3745 but not at the bare call in swap_ops.py:3977, and the raise actually escapes earlier still from build_default_config at services/assistant_orchestrator/src/entrypoint.py:3749, which sits OUTSIDE that handler's own try: at line 3773 - so FleetScriptsDirUnavailable propagates past a docstring promising fail-closed and the operator-facing refusal is never produced | DEFERRED | #1301 - blocked-by: entrypoint.py:3749 sitting outside the try: block at entrypoint.py:3773 - observable by reading those two line numbers on the branch
S4 SHOULD-FIX shared/fleet/dispatch.py:251 classifies any line containing the unanchored substring "not started" as REFUSED before every other class, so a genuine coder result reading `PARKED - the build had not started when the budget expired` misclassifies as REFUSED and lands in REDISPATCH_EXCLUDED_RESULTS | DEFERRED | #1301 - blocked-by: the unanchored `if "not started" in low:` at shared/fleet/dispatch.py:251 - observable by reading that line, and the refusal text is self-generated so an anchored form is available
S5 SHOULD-FIX shared/fleet/dispatch.py:135 documents the result contract as a six-value enum (MERGED, PARKED, BLOCKED, NOTHING, TIMEOUT, UNKNOWN) while REFUSED was added to the vocabulary and to coord_redispatch.RECOGNIZED_RESULTS but NOT to the docstring that owns the contract, violating authority_first (what a return value MEANS lives in its own docstring) | DEFERRED | #1301 - blocked-by: the string `REFUSED` being absent from the result docstring at shared/fleet/dispatch.py:135 while present in shared/fleet/coord_redispatch.py RECOGNIZED_RESULTS - observable by grepping both
S6 SHOULD-FIX shared/fleet/swap_ops.py:3752 writes SUMMARY.txt via runs_dir_for(config, str(spec.get("run_id", ""))), so a spec missing run_id writes into the fleet-runs ROOT of the operator's live state directory where read_summary will never find it | DEFERRED | #1301 - blocked-by: the unguarded `spec.get("run_id", "")` default at shared/fleet/swap_ops.py:3752 - observable by reading that line
S7 SHOULD-FIX shared/fleet/dispatch.py:37 imports psutil at module level - the only module-level psutil import in shipped code, where shared/fleet/proc_tree.py:62 and conftest.py:238 both import lazily with explicit absent-psutil fallbacks - and dispatch.py is imported at module level by services/ui_gateway/src/transport.py:70, so the gateway now hard-requires psutil at import where it did not before | DEFERRED | #1301 - blocked-by: the module-level `import psutil` at shared/fleet/dispatch.py:37 - observable by reading that line and comparing with the lazy form at shared/fleet/proc_tree.py:62
S8 SHOULD-FIX the ambiguity lock ships no OFF toggle - test_two_live_runs_pinning_different_trees_is_REFUSED proves it blocks, but test_two_live_runs_pinning_the_SAME_tree_agree is a different scenario rather than the lock disabled, unlike test_the_scoping_lock_has_teeth and test_the_corrupt_declaration_lock_has_teeth which are proper toggles | DEFERRED | #1301 - blocked-by: the absence of a disabled-lock case in services/assistant_orchestrator/tests/test_fleet_dir_resolution.py alongside the two named has_teeth toggles - observable by grepping that file for the toggle pattern
```

## What the review could NOT verify, carried forward rather than buried

- Whether an outer guard in the AO message loop replies when `_handle_execute_request`
  raises. The reviewer confirmed `entrypoint.py:3749` sits outside the `try:` at 3773 and
  located the dispatcher at 3382-3383, but did not trace the dispatcher's own caller. **If
  there is no per-request guard, a corrupt pin leaves the WinUI app waiting on an
  `EXECUTE_RESULT` that never arrives** — a worse operator experience than a refusal.
- BLOCKING 1 against the real `C:/Users/mrbla/agentic-setup`. Reproduced in a temp tree of
  identical shape keyed to a genuinely running pid. The reviewer deliberately did not write
  into live fleet state (#758), which was the correct call.
- Whether `psutil.create_time()` can raise `AccessDenied` for a recycled pid on this box.
  The code comment claims measured-not-to-occur; the `except (psutil.AccessDenied, OSError)`
  arm exists, so the author considered it reachable.
- A full standing-gate run on the branch. Three directly affected files only: 137 passed.
- The agentic-side `verify-fleet-scripts-pinning.ps1`, which the Python tests cite as the
  seam keeping `_declare` honest against `Publish-ScriptsPin`.

## The finding worth keeping beyond this branch

`git merge-tree` reports **no conflicts** across the 127-commit gap, and the real drift is
invisible to it. `tests/integration/test_smoke_contract.py:402` only began resolving
`scripts_dir` off the real root in `5f8be4c3` / `20a021f5` — commits that landed on `main`
*after* this branch was written. A third pin-sensitive call site grew underneath the branch
while a textual merge check stayed clean the whole time.

**A conflict-free merge is not evidence that a branch is still correct.** For a branch this
far behind, the question is not "does it apply" but "did the thing it assumes about the
world change" — and only reading the callers answers that.
