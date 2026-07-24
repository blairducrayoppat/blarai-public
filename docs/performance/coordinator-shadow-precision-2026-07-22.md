# Coordinator shadow-precision report — re-shadow window, 2026-07-22

**Ticket:** #855 (scope item 3 — measured graduation). **Status: measurement only.**
Graduation to live output is a separate Lead Architect ceremony; nothing in this
report flips anything.

**Machine-readable twin:** `coordinator_shadow_precision_2026-07-22.json` (same
directory). **Prior report:** 2026-07-18 (#855 c.2200/c.2201, graded HOLD by the LA
c.2208). This is the first report over the **re-shadow window** — the period since the
#946 verdict-integrity guard went live in shadow on 2026-07-19.

---

## The one-paragraph version

The coordinator's **decisions** are still perfect: every board move it decided in the
window — seven distinct decisions across seven real runs — was correct, as were its one
stall flag and its one (benign) tripwire note. The **guard around its words** now has
its first live record, and that record is instructive in both directions: the guard
**missed the one genuinely false statement** that crossed it ("acceptance tests
passed", on a run whose acceptance exam had failed 4 of 6 tests — accepted on 3
cycles), and its **only firing was a false alarm** — it suppressed an accurate sentence
because that sentence contained the words "complete successfully" inside a negation
("did **not** complete successfully"). Both failures live in the same shallow layer
(the phrase-matching lexicon); the structural layers underneath — the deterministic
headline, the verdict echo — held on all 34 guarded cycles, so no false claim was ever
the digest's claim of record. On these numbers the guard's catch rate is **0 of 1** and
its false-refusal rate is **1 in 34 cycles (~3%)**: exactly the measurement the
re-shadow window existed to produce, and not yet a record that earns graduation.

## Window and sample

| | |
|---|---|
| Journal population | 330 entries, 2026-07-15T02:02Z → 2026-07-22T23:40Z (digest 202 · board_move 126 · stall_comment 1 · tripwire_alarm 1) |
| Graded window | seq 156 (2026-07-19T19:01:57Z, start of the graded set — a chosen boundary; the journal's restart signature sits at seq 154, 18:31Z, after the #946 merge) → seq 330 |
| Entries graded | **175** (91 digests, 82 board-move effects, 1 stall comment, 1 tripwire) — full in-window population, no sampling |
| Distinct board decisions | 7 · Guarded prose cycles **34** · Distinct drafted statements **10** (9 accepted + 1 rejected) |
| Accrual | healthy — 321 (13:34 local, c.2365) → 330 at dump |

Read via the sanctioned API (`build_shadow_journal`, real LOCALAPPDATA — the c.2240
precedent). Ground truth: each run's `scorecard.json` under
`agentic-setup/state/fleet-runs/`, re-read tonight, and the transition rule re-derived
through `shared/fleet/coord_lifecycle.resolve_board_transition` (the locked forged-Done
discipline), not from memory.

## Deterministic layer — 100% again

All seven distinct decisions correct: three GREEN runs → Done (20260721-172005,
20260722-122919, 20260722-140757); parked-task run → Ready (20260719-233631); three
honest parks without a parked task (oracle failed or not-run) → In Progress
(20260719-002208, 20260720-235311, 20260721-111715). The stall comment (task 914,
age 3.9d — verified against the ticket's creation time) and the single tripwire entry
(drafting-deferred, explicitly `machinery_health: false`) were both correct. **0 false
stalls, 0 false tripwires.** This matches the 07-18 report's 7/7 — the deterministic
ruler has now been perfect across both windows.

## Guard layer — the first live record, and it points both ways

**The miss (catch rate 0/1).** On 20260719-002208-bd — verdict PARKED-HONEST, job
oracle **FAILED** (4 of 6 tests) — the model drafted *"All features were successfully
merged **and acceptance tests passed** … finished with all components merged **and
tested**."* The guard accepted it, on three separate cycles. The statement opened with
the correct verdict echo ("INCOMPLETE: …"), so layers 1–2 passed it; layer 3's
success-claim lexicon knows "completed successfully" but not **evidence-field claims**
("acceptance tests passed"). This is the same optimistic-drift fingerprint the 07-18
report measured — the 14B asserting the exact thing the scorecard denies — in a wording
one lexicon entry away from the golden case that was locked. The lexicon is add-only by
design and grows via golden cases; this instance is its first live growth candidate.

**The false refusal (1/34 cycles, ~3%).** The guard's only firing rejected an accurate
sentence: *"the overall run did **not** complete successfully"* on 20260721-111715-bd
(honest park). Match: `claim:completed-successfully` — negation-blind, exactly the
false-refusal class the #946 reviewer predicted (c.2219) and the module docstring
deliberately prices toward refusal ("a dropped-but-true sentence costs one cycle's
color; a published-but-false one costs operator trust"). Fail-safe direction held: the
deterministic headline stood alone. This is the documented posture working as designed
— and now it has a measured price.

**What held structurally, every cycle:** verdict echo correct on all 10 distinct
drafted statements (including the rejected draft's correct INCOMPLETE echo); no
model text ever displaced a deterministic headline; the rejected draft was journaled
raw (provenance intact). Headlines were 7/7 consistent with their deliberately coarse
contract. Two quality notes on accepted prose, neither a false success: 20260720-235311's
"did not complete all planned tasks" (×12) is mechanism-wrong — all six tasks merged;
the acceptance *exam* failed — and 20260719-233631's first variant said "has completed"
inside a correct PARKED frame.

## Coverage — what the coordinator never saw

Harvest is **latest-finished-run-only per cycle** (`snapshot.latest_run`) and depends
on app uptime. Four finished runs were never graded in-window: 20260721-184705 (GREEN),
20260721-230126 (GREEN), 20260722-002149 (GREEN), and 20260722-165617 — a PARKED run,
i.e. the guard's most valuable prose class, still unsampled. One anomaly is recorded
without diagnosis: the 23:25Z/23:40Z cycles harvested 20260722-140757-bd although
20260722-165617-bd had already finished. PARKED-run prose remains under-sampled
(c.2220's caveat stands).

## Not measured

Stall recall on a quiet board (fixture-proven only); guard behavior on negated failure
words over GREEN runs (predicted class, no live instance yet); prose for the four
unharvested runs; threshold adequacy — the graduation threshold remains deliberately
unconfigured and per c.2337 should be **pre-specified before the next grading window**,
not chosen after seeing its data.

## Where this leaves graduation (decision: Lead Architect, at ceremony)

The measurement itself argues nothing is ready to flip: a guard whose live catch record
is 0-for-1 has not yet demonstrated the property graduation depends on. **[PROPOSED]**
recommendation with alternatives, for the ceremony: (a) land the add-only lexicon fix
for the measured miss (a defect with one correct fix — being shipped separately with
both live failures as golden cases, marking a new guard sub-window); (b) decide the
negation trade-off explicitly — keeping the refusal bias now has a measured price
(~3% of cycles / 1 accurate statement dropped) and loosening it is a quality/security
posture call that is yours, not a session's; (c) extend the guarded shadow window until
it has accumulated enough real false-claim instances to state a catch rate with more
than one sample, with the threshold pre-specified. Alternative: graduate
actions-only (deterministic layer is 14/14 across both windows) while words stay
shadowed — same option the 07-18 report offered, now with stronger action-side and
weaker word-side evidence.
