### 2026-07-13 — The question you only ask once

*Plain summary: shipped the C2-inc-2 PARKED-HONEST → redispatch-proposal limb —
`shared/fleet/coord_redispatch.py` stages ONE approval-gated redispatch proposal per
new parked run into the born-encrypted `proposal_store`, target re-derived through the
#848 SG ruler, with a built-but-unwired execution-time re-validation seam (ADR-039
§2.12.4). DORMANT. The load-bearing design call is the dedup grain: evidence identity =
run, and decided evidence is never re-asked. No new lesson; one non-obvious catch worth
keeping.*

This limb looked like pure assembly — every piece existed. `parse_summary` already
classifies a run's SUMMARY into per-task results; the proposal store already dedups on
a fingerprint and encrypts its payload; `evaluate_dor` already shows exactly how to
re-derive a target from a trusted repo id and refuse through the SG ruler. What the
assembly surfaced was a semantics question none of the pieces answered alone: *what is
the identity of a redispatch ask?*

The fingerprint doctrine (ADR-039 §2.12.5) says class + target + evidence hash, but the
evidence grain was mine to pick, and the two candidates behave differently in exactly
the corner the store's own semantics create. The store deliberately lets a terminal
(APPROVED/REJECTED) proposal *not* suppress a fresh draft — "a recurrence after a
decision is new work." Correct doctrine — but the coordinator's realistic consumer is a
heartbeat re-reading the *latest run's* SUMMARY every cycle, which means the same
parked run keeps re-presenting as if it were a recurrence. Under either naive grain
("per run" or "per task"), the cycle after an operator rejection would re-stage the
identical ask, forever, until a new run happened to displace the old one. A rejected
proposal that resurrects every cycle is precisely the wall-of-stale-asks §2.12.5 exists
to prevent — and it would have shipped invisible, because the limb is dormant and
nothing exercises it until go-live.

The resolution has two halves. The grain: evidence identity is the parked run's stable
identity — `run_id + task + result`, never a timestamp — so a re-read maps to the same
fingerprint and a genuinely new park (including an approved redispatch parking again)
mints a new one. And the history check: the cycle asks the store for the fingerprint's
*full* history, not just its active row, and refuses to re-stage evidence that already
carries a terminal decision. That needed one read-only addition to the merged store
(`find_by_fingerprint`, the any-status sibling of the active-only query) — an
extension I weighed against the "reuse it, do not rebuild" instruction and took,
because the alternative was a caller-side seen-set file duplicating state the store
already holds; the sanctioned-API rule (§2.1 item 10) governs *writes*, and this adds
none. "A recurrence after a decision is new work" now reads as *new evidence*, never
*the old evidence re-read* — the store keeps its doctrine, the limb supplies the
discrimination.

Two smaller pieces earned their keep. The Lead Architect's review of my gate sharpened
the fragility I'd half-seen: the limb keys on the literal `"PARKED"` across a module
boundary, and a dormant limb whose trigger word drifts detects nothing — silently —
until go-live. The lock is a source-introspection test that extracts every return
literal from `dispatch._classify_result` and fails unless the set exactly equals the
limb's eligible ∪ excluded declaration; a future rename or a brand-new result word
breaks the build instead of the capability. (The same review caught that the
`TaskOutcome.result` docstring still omitted `TIMEOUT` — it predated #757 — fixed in
the same change.) And the TOCTOU requirement (§2.12.4) is built as a *seam*, not a
hook: `revalidate_for_execution` re-derives the target from the proposal's own
structured `repo_id` payload field and re-runs the ruler at `phase="EXECUTION"`,
tested against a world that turns hostile between staging and execution — but nothing
wires it, because the approve→execute path itself is C3/C5 territory. Building the
pure function now costs a dozen lines; forgetting it at wiring time would cost the
boundary.

Posture notes, briefly: the payload (goal text, task text, evidence pointers) is
content-bearing, so it rides the store's existing born-encryption — the opposite call
from the stall limb's plaintext seen-set, both instances of the same §2.13 item 2 test,
which is exactly how a precedent should behave on its second application. No new
crypto, no DECISION_REGISTER row, no new timeouts. The SG refusal is fail-closed and
sits in front of the store (a refused cycle provably never reaches `add_draft`); store
faults are fail-soft and self-retrying (a fault means no proposal was written, so the
next cycle naturally re-stages). C2 stays deterministic end to end — the proposal text
is composed by code from structured run facts; no model drafts anything here.

**Next:** the last #844 limb — promote the stop-doomed-fast patterns from
`tools/dispatch_harness/monitor.py` into driver-integrated checks in
`swap_driver`/`swap_ops`, built DORMANT behind a `[coordinator]` flag so it automerges
like the rest. That limb closes #844, and C3 (the heartbeat) begins with a design
checkpoint.

*(commits `950a70a8` (the C2 redispatch limb — new `shared/fleet/coord_redispatch.py`
+48 tests, the read-only `find_by_fingerprint` in `shared/coordinator/proposal_store.py`
+2 tests, the `TIMEOUT` docstring fix in `shared/fleet/dispatch.py`) + `7834c43c`
(the two review nits: any-literal lock regex, EXECUTION-phase assert); independent
author≠verifier review MERGE-READY-WITH-NITS — all 10 claims CONFIRMED, both nits
applied same-session; standing gate 7867 passed / 0 skipped / 0 failed, elevated +
LOCALAPPDATA-redirected — measured at `950a70a8` (4:39) and re-confirmed identically
at the nit-fix tip `7834c43c` (4:17); the 7810-baseline's 7 environmental port-5001
skips returned as passes with the app down, +50 new tests. DORMANT — no live
caller.)*
