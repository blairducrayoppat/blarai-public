---
title: "#1223 / #1244 independent review — disposition"
status: reference
area: testing
---

# #1223 / #1244 — independent review disposition (2026-08-05)

The review that was owed on 2026-07-30 and never delivered. Both merges — `4776eb15`
(#1223 instrument registry) and `6192049c` + `1431f1ed` (#1244 ruff measured-zero and its
hotfix) — shipped with **no independent read**: two review agents were dispatched that
night, neither reported, and the author verified their own work. That gap stood for six
days.

Run 2026-08-05 by an independent reviewer that did not author either merge. Read-only
throughout. The two highest findings were **re-confirmed by the merging session against
the code on disk** before being recorded here — an agent's finding is a hypothesis until
someone reads the lines.

**Honest limit on this record.** The reviewer could not run `pytest` (a standing gate was
occupying the checkout), so every finding below is derived from reading code and git
history, not from executing a failing case. Findings marked CONFIRMED were traced line by
line; the two marked PLAUSIBLE have a confirmed *mechanism* and an untraced *consequence*.
No finding here has been reproduced by a red test. That is the next actor's first job on
each ticket, and a fix that does not first produce the failing case is not evidence.

```disposition
regression probe: two empty results are "comparable" -> measured=True | DEFERRED | blocked-by: #1269
per-card audit fault dropped with no counter; audited==0 renders mute | DEFERRED | blocked-by: #1270
hotfix incomplete: layer1.py:208 argv-stdout unguarded, fails OPEN    | DEFERRED | blocked-by: #1269
RegressionFinding.measured read-site count recorded as 8, actually 11 | FIXED    | docs/july-close-0805 — corrected here and on #1251
47193a5e commit message overstates its own blast radius              | FIXED    | docs/july-close-0805 — corrected here and on #1270
card.py renders unmeasured identically to measured-and-clean          | DEFERRED | blocked-by: #1270
card.render() has no production reader; its docstrings claim it does  | DEFERRED | blocked-by: #1271
swap_ops.py:1073 discards the return code; verify FAIL -> "none"      | DEFERRED | blocked-by: #1272
swap_ops.py:2144 blank text -> node smoke reports ok=True             | DEFERRED | blocked-by: #1272
oracle_qa/oracle_mutation set child PYTHONIOENCODING, parent uses locale | DEFERRED | blocked-by: #1272
instrument_registry.py:461 counts=() names two keys that do not exist | DEFERRED | blocked-by: #1271
toggle-proofs: 28 tests, gate-enforced seam-drives-real-entrypoint    | REJECTED | not a defect — strongest part of the merge
all 11 instruments reachable on the production path                   | REJECTED | not a defect — verified live, see note
```

## The finding that matters most

`layer1.py`: a probe that produced **nothing** is stamped `measured=True, "no behaviour
change vs the last archived GREEN"`. `run_probe` returns `[]` rather than the
`could-not-run` sentinel when stdout is empty; `_diff_probe` then compares `[]` against
`[]`, where `any()` over an empty sequence is `False` and `0 != 0` is `False`, so neither
guard fires and the pair is declared comparable.

The operator KPI consequently reads `regressed=0 (not-measured=0)` — and
`not-measured` is the field #1223 added so exactly this could not happen.

**The registry cannot see it.** The born-unmeasured invariant is enforced on the
DECLARATION (`layer1.py:264`, cross-checked at `instrument_registry.py:273`) and never on
runtime ASSIGNMENT. That is the class one level up from itself: a control that checks the
shape of a thing rather than the value it takes.

## Two records corrected rather than argued

- **"read at 8 sites"** (recorded on #1251 and in `BUILD_JOURNAL.md`) is **11**. `git blame`
  shows 8 was accurate after `da6a033c` and went stale when `d32db471` added three more —
  **both inside merge `4776eb15`**, so the figure was already wrong when it was written
  down. The merging session's own recount of 9 was also wrong. Three counts, three
  different numbers, none of them from a script.
- **`47193a5e`'s commit message overstates its own defect.** It claims the `None.strip()`
  raise "would have blanked the ENTIRE green-quality stage." It would not: `run_ruff_advisory`
  sits inside `audit_greens`' per-card handler at `__init__.py:425-440`, so one smart quote
  drops one card and continues. Not amended — no history rewrites — corrected here and on #1270.

## Scope note recorded so the deferrals are not read as wider than they are

`evals/battery/green_quality/` holds **one** probe set (`B2.json`) against **eight** battery
cards. The regression instrument runs on all eight nightly and honestly measures nothing on
seven. So #1269's live blast radius today is B2 alone — which lowers its urgency and raises
the urgency of fixing it *before* probe sets are added, since every new one inherits the
fail-open.

## Why these are DEFERRED and not FIXED tonight

Each names a ticket a later session can observe, and none is waiting on a decision. They
were not fixed in this session because it found them at low remaining context after four
merges, and a rushed fail-open fix in the honesty instrument — merged without its own
independent read — reproduces the exact failure this document records. That is a reason,
and it is written here so it can be judged rather than assumed. **#1269 and #1270 are the
top of the queue**, above #1250 and #1251, because they are live fail-opens rather than
structural improvements.
