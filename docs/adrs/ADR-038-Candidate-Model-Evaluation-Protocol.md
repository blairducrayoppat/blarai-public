# ADR-038 — The Candidate-Model Evaluation Protocol (how we judge a replacement, apples-to-apples)

**Status:** ACCEPTED 2026-07-11 (LA-ratified in-chat, verbatim "yes to all" — the four policy calls D1–D4
and the immediate frozen-split ratification are DECIDED and locked here as policy, not proposed; Vikunja
**#838** c.1744, quoted below). The **time-sensitive control this ADR ratifies — the frozen/dev split marker
on the battery cards + the contamination tripwire — ships with this ticket** (the ADR is docs; the marker is
the one small mechanism). Everything else here is protocol doctrine a future evaluation must build against.
**Deciders:** Lead Architect (blarai); Orchestrator (facilitation).
**Builds on:** ADR-037 (the Grading & Integration Machinery — the honesty invariants, the gate ladder, the
oracle lifecycle, the verdict taxonomy, and Small-Model Consciousness this protocol reuses wholesale;
**this ADR is that machinery pointed at a new question — not "did the coder do the job" but "is this
candidate model better than the incumbent"**), ADR-035 (the Acceptance Layer — the criteria tiers and the
never-rubber-stamp rule), ADR-034 (the model-swap driver — the containment the candidate runs inside).
**Relates to:** Vikunja **#834** (model-profiles manifest — the *adapter-config* layer §Decision-1 names,
the thing that makes a clean swap a data change), **#835** (the greedy-vs-low-temp A/B — the **first instance
of the swap-one-variable discipline** §Decision-3 generalizes), **#821** (the oracle-QA layer — the
model-blind referee §Decision-4 leans on, landed `shared/fleet/oracle_qa.py`), **#832/#837** (the honesty
layer that grades the candidate un-gameably, §Decision-5), **#816** (environment self-capture) + **#778** (the
thermal sign-flip lesson) behind the reproducibility rule (§Decision-6), and the QUALITY program **#819–#837**
that made this evaluation *possible* by producing a model-independent measurement of the exact artifacts a
candidate would author. Grounded in the same six 2026-07-11 design dossiers as ADR-037 (`docs/handoffs/
*-20260711.md`) — **citations, not the decision**; the co-evolution / "Verification Horizon" framing
(arXiv 2606.26300) is this ADR's swap-time twin, and the frontier *contamination* concern (r1extern R9 —
rejected as heavy nightly machinery) is adopted here at a **light grain** as the frozen/dev split.

## Context

The operator asked the forward-looking question the whole grading-maturation program quietly enables:
*"we are doing model-specific refinements that are critical, but how will we test future candidates for
replacing the models we use today? How do I safely judge apples-to-apples replacement candidates?"* (#838,
2026-07-11). BlarAI runs a **14B planner/oracle-author/grader and a 30B-A3B coder on one box** (ADR-037's
Small-Model Consciousness), plus a critic and a vision model — distinct **roles**, not one monolithic
"the model." One day a better local model will exist for one of those seats. The answer to "should we swap
it in" is not a vibe and not a single GREEN count; it is a **protocol** and a **governance discipline**.

The tension that shapes every decision below: **model-specific tuning and model-portability pull against each
other.** The program is *right now* doing critical model-specific refinement (the greedy-14B oracle-author
collision, #834/#835; profile-driven paths, #834). If that optimization leaks into the **evaluation** path,
the harness overfits to today's incumbent and every future challenger is judged on a track shaped for the
model it is trying to replace. That is the frontier "contamination" hazard (r1extern R9) and it is the
swap-time face of the Verification-Horizon rule ADR-037 §Decision-9 already adopted: *no fixed grader stays
valid as capability changes.* The protective move is cheap, and it is **time-sensitive** — every day of
tuning that iterates against the undifferentiated battery cards silently contaminates the future test. So the
one mechanism this ADR builds is the split that stops that clock today.

The enabler is worth stating plainly, because it is *why now*: a naive "which model gets more GREENs" eval is
**gameable** — a candidate that reward-hacks the grader would be crowned, not caught. The mature machinery
(#819–#837) changes that. The oracle-QA layer (#821) is a **model-blind** judge of the exact artifact a
planner/oracle-author candidate authors; the honesty layer (FALSE-DONE cross-check, #832 tampering scan, #837
GREEN-audit) grades the candidate's *output* by the same un-gameable rules it grades the incumbent's. The
grading-maturation program did not just harden nightly runs — **it produced a model-independent instrument, and
that instrument is what makes an apples-to-apples model comparison possible at all.**

## Decision

BlarAI adopts the **candidate-model evaluation protocol** below. The four policy calls D1–D4 are **LA-DECIDED**
(#838 c.1744, "yes to all"); the immediate **frozen-split is RATIFIED and in force**; the split marker + the
contamination tripwire **ship with this ticket**. Everything here is doctrine a future evaluation MUST NOT
silently drift from; a change is an ADR amendment, not a refactor.

### 1. Two kinds of configuration — adapter (levels the field) vs optimization (the contamination hazard)

The load-bearing distinction the whole protocol rests on. Config is not one thing:

- **ADAPTER config — per-model, correct-for-each, and it LEVELS the field.** Tool-call format, thinking-strip,
  sampling policy, grammar support, context budget — the settings a model needs to *function at all*. The
  **#834 model-profiles manifest IS this layer.** A candidate gets its own adapter values so it can run;
  giving a challenger its correct tool-parser is **fairness, not a thumb on the scale.** Both incumbent and
  candidate always get their adapter config set correctly — that is a precondition of a fair comparison, never
  a form of tuning one model.
- **OPTIMIZATION config — the hazard if it leaks into the judge.** Prompt phrasings, retry counts, task grain
  that were tuned *because THIS model responds to them*. In the evaluation path these must be either
  **re-tuned per candidate** (fair, expensive) or **held model-neutral** — and the evaluation **declares which**,
  every time. Optimization config silently carried from the incumbent is exactly how the track gets shaped for
  the incumbent.

This distinction is what makes "swap one variable, hold everything else" (§Decision-3) *operable*: the
"everything else" that is held is the **optimization** config (identical for both), while the **adapter** config
is set correctly-per-model on both sides. #835 is the first live instance — greedy vs low-temp is an *adapter*
change measured with optimization held.

### 2. The FROZEN model-neutral eval set — **D4** (the single most protective piece)

The train/test split applied to the harness itself. Today's battery cards (`evals/battery/B*.json`) are
undifferentiated — the same cards the fleet measures against are the cards a tuning session would iterate
against. That is a contaminated test in the making. The split:

- **A DEV/TUNING set** — grow it freely, iterate prompts / profiles / task grain against it as much as
  model-specific refinement demands. Tuning happens **here and only here.**
- **A FROZEN EVAL set** — locked, versioned, model-neutral, used **ONLY** for candidate comparison + regression,
  **NEVER tuned against.** Measurement-only. Running the frozen cards for measurement is exactly the battery's
  job today; **freezing changes nothing about how the battery runs tonight** — it changes what may *edit* those
  cards and what may *tune against* them.

**D4 — the DECIDED growth policy (verbatim, c.1744):** *born-frozen-XOR-born-dev never crossing; frozen cards
add-only + immutable + versioned + never-tuned-attested; quarterly refresh authors fresh hard cards + retires
trivially-passed ones; a contamination tripwire fails loud if a frozen card's fingerprint appears in a
tuning-run log.* Reading it as mechanism:

- **Born-frozen XOR born-dev, never crossing.** A card is authored as one class or the other and never
  migrates. Enforced structurally by the marker this ADR ships (§ below): the id namespace and the
  `card_class` field must agree, or the card is invalid.
- **Add-only + immutable + versioned.** A frozen card is never edited in place (an edit is a silent
  re-baselining that breaks comparability with every prior run). New hard cards are *added*; the set is
  versioned so a run names the frozen-set version it measured against.
- **Quarterly refresh (co-evolution).** Tied to the existing `LESSONS.md` quarterly consolidation and ADR-037
  §Decision-9's grading review: each quarter authors fresh *hard* cards and retires trivially-passed ones, so
  the test co-evolves with capability (the Verification-Horizon rule at swap time). Retiring is not editing —
  a retired card is marked retired, its bytes preserved for historical comparability.
- **A contamination tripwire (the gate that makes the rule real).** *A rule without a gate is a defect*
  (ADR-037's discipline). A deterministic, fail-loud check refuses any tuning/dev run whose manifest references
  a frozen card's identity (its id or its sandbox repo). This is the enforcement of "MEASUREMENT-ONLY on frozen
  cards; tuning happens on dev."

**The immediate ratification, IN FORCE (c.1744):** today's battery cards **become the seed FROZEN eval set**;
all model-specific prompt/profile tuning routes to a separate DEV set. This costs nothing today and protects
every future comparison — and it is why the marker is time-sensitive rather than a later phase.

**The mechanism this ADR ships** (`tools/dispatch_harness/battery.py`, dormant-safe): a `card_class:
"frozen" | "dev"` field on the battery-card schema; the eight existing cards **stamped `frozen`** (the seed set,
byte-behavior-identical — the battery loads and dispatches them exactly as before); a **born-frozen-XOR-born-dev
consistency lock** (a `B<n>` id is frozen, a `D<n>` id is dev — the field and the id namespace must agree,
absent defaults to frozen so an unstamped card is measurement-only by fail-safe); a **separate dev-card loader**
over `evals/battery/dev/D*.json` (the mechanism for authoring dev cards apart from the frozen battery); and the
**contamination tripwire** `assert_no_frozen_in_tuning(manifest)` — deterministic, fail-loud, naming every
offending frozen id/repo. It is **dormant-safe by construction**: nothing on tonight's battery path calls the
tripwire (the frozen cards ARE the measurement), and the dev namespace is invisible to the frozen `B*.json`
glob and to the production plan-override resolver. The tripwire wires into the #835 A/B tuning harness (and any
future model-specific tuning run) when that harness lands.

### 3. Role-at-a-time swap — the attributable delta

*"Is model X better"* is unanswerable monolithically because the fleet uses models in **distinct roles**
(planner/decompose, oracle-author, coder, critic, vision). The protocol swaps a candidate into **ONE role**,
keeps the incumbent in **all others**, and measures the delta — so a movement in the numbers is *attributable*
to that seat, not confounded across five. This is the deeper form of the r5models A2 confound and the
generalization of #835's swap-one-variable A/B (which swaps one *setting* in one seat; this swaps one *model*
in one seat). Adapter config is set correctly for the candidate in its seat (§Decision-1); optimization config
is held per §Decision-8.

### 4. The model-blind referee for an oracle-authoring candidate — the oracle-QA layer (#821)

The circularity a planner/oracle-author evaluation must solve: if candidate X is evaluated in the
**oracle-author** seat, the thing being graded (oracle quality) is *authored by X itself* — so X cannot be its
own judge. The resolution is the QUALITY program's deliverable: the **deterministic oracle-QA layer** (#821,
landed `shared/fleet/oracle_qa.py`) is a **model-blind** judge of oracle output — well-posedness (collectable,
spec-valid strategies, no invented contract), the criterion→test traceability/coverage matrix, and the
FAIL-TO-PASS discrimination baseline. It runs the *same* deterministic AST/collect/execute checks on X's oracle
that it runs on the incumbent's, with no model in the honesty-critical path. **This is precisely why the grading
maturation is the enabler:** it produces a model-independent measurement of the exact artifact a planner
candidate would author, so the oracle-author seat — otherwise the hardest to judge (§Decision-9) — becomes
refereeable.

### 5. Un-gameable by construction — the honesty layer grades the candidate

A candidate's output is banked or parked by the **same honesty layer** that grades the incumbent: the
FALSE-DONE cross-check (a GREEN whose oracle did not pass is rewritten FALSE-DONE, ADR-037 §Decision-1), the
#832 tampering-fingerprint scan (a candidate that hooks the test runner or hardcodes oracle answers is
**downgraded**, quoting file:line — integrity evidence, not a quality opinion), and the #837 GREEN-quality
audit. A naive "more GREENs wins" eval rewards a model that games the grader; **routing the candidate through
the un-gameable machinery means a reward-hacking candidate is CAUGHT, not crowned.** This is the honesty
contract of ADR-037 §Decision-1 doing double duty — it protects the nightly run *and* it makes the model
comparison robust. It is also the hard floor under D1's bar (§Decision-7): an honesty-gate failure disqualifies
regardless of capability.

### 6. Safe = contained + reproducible — never a production swap

A candidate is evaluated inside the battery's existing containment, **never** by swapping it into the
production seat:

- **Contained.** The candidate runs under the same isolation the battery already enforces — worktree isolation,
  the ACP restricted-account (#775), the sandbox `battery-<slug>` repo pin (a candidate eval NEVER targets an
  operator repo), and the dormant-by-default flags. A production swap to "try the new model live" is out of
  scope and off the table.
- **Reproducible.** A "win" must be a *model* win, not a thermal or environment artifact. The run **self-captures
  its environment** (#816 — the box-state-as-code checklist + env self-capture) and pins a **fixed seed policy**,
  so a measured delta is attributable to the candidate and not to a warm-vs-cold GPU or a driver drift. The
  **#778 thermal sign-flip lesson** is the named reason a single run is never enough — a margin must **repeat**
  before it counts (D1).

### 7. The replacement bar — **D1** (three-tier, safe-biased, declared in advance)

**D1 — the DECIDED bar (verbatim, c.1744):** *three-tier, safe-biased — DISQUALIFY on any honesty-gate failure
regardless of capability (honesty is a gate, never a tradeable score); KEEP INCUMBENT on ties/within-noise/
any-other-regression; REPLACE only on honesty-held + role-primary win repeating across ≥2 frozen-set runs +
zero regression elsewhere.* The three tiers, made operable:

1. **DISQUALIFY (honesty is a gate, never a score).** Any honesty-gate failure — one FALSE-DONE, a tampering
   fingerprint, an un-caught reward-hack — disqualifies the candidate **regardless of capability.** A
   more-capable-but-less-honest model is *more dangerous*, so honesty can never be traded against capability.
2. **KEEP INCUMBENT (the safe-biased default).** A tie, a within-noise win, or **any** secondary-metric or
   other-role regression keeps the incumbent. Switching cost and known-good status win every marginal call —
   the burden of proof is on the challenger, asymmetrically.
3. **REPLACE (only when decisively, repeatably, cleanly better).** The candidate holds **every** honesty gate
   AND beats the incumbent's **role-primary** metric by a margin that **repeats across ≥2 frozen-set runs**
   (the #778 thermal-sign-flip guard) AND **regresses nothing else.**

And — **the bar is declared in advance.** No moving goalposts: the incumbent stays until the challenger clears
a **pre-registered** bar on the **frozen** set. Declaring the bar before the run, on a set that cannot be tuned,
is what makes the comparison honest rather than a post-hoc rationalization.

### 8. Neutral-vs-retune — **D2** (two phases split by config type)

**D2 — the DECIDED protocol (verbatim, c.1744):** *two phases split by config type. Adapter config
(tool-format/thinking-strip/sampling/grammar) always correct-per-model. Optimization config held
neutral+identical in Phase 1 (equal-footing); Phase 2 grants a bounded declared tuning budget on the DEV set
only (never frozen) for a challenger clearing/nearing the bar, then re-measure on frozen.* Operable:

- **Always, both phases:** adapter config set correctly per model (§Decision-1) — functioning is not tuning.
- **PHASE 1 — equal footing.** Optimization config held **neutral and identical** for incumbent and candidate.
  This is the true apples-to-apples comparison — no unequal-effort thumb on the scale.
- **PHASE 2 — realism, only if warranted.** For a challenger that clears or nears the bar in Phase 1, a
  **bounded, declared** tuning budget is granted **on the DEV set only** (never the frozen set), then the
  candidate is **re-measured on frozen.** This answers "but the new model would be tuned in production too"
  without letting tuning contaminate the judge and without an unequal-effort advantage. The budget is bounded
  and declared so Phase 2 cannot become an open-ended search for a configuration that happens to win.

### 9. Role priority — **D3** (coder-first on-ramp, oracle-author/planner the prize)

**D3 — the DECIDED priority (verbatim, c.1744):** *coder-first as the on-ramp (deterministic model-blind oracle
= cleanest fair comparison, validates the protocol cheaply), oracle-author/planner as the priority prize (where
quality bleeds, the realistic upgrade path, the hardest to judge). #835 A1 half-seeds the oracle-author seat.*

- **Coder-first — the on-ramp.** The coder seat is the **cleanest fair comparison**: a deterministic,
  model-blind job oracle grades both the incumbent's and the candidate's code by identical rules. It validates
  the whole protocol cheaply before the harder seat.
- **Oracle-author/planner — the prize.** This is **where quality bleeds** (ADR-037's greedy-14B oracle-author
  finding), the **realistic upgrade path** (the 14B is swappable; the 30B coder substrate is more locked), and
  the **hardest to judge** (the oracle-authoring circularity §Decision-4's referee exists to break). Build
  coder-first, extend to oracle-author immediately; **#835 A1 half-seeds the oracle-author seat** already.

## The mechanism, in code (what ships with this ticket)

Docs aside, the one time-sensitive control is small and lands now (`tools/dispatch_harness/battery.py` +
`evals/battery/`):

- **`card_class` field** on the `battery-card/v1` schema: `"frozen" | "dev"`, absent ⇒ `frozen` (fail-safe —
  an unstamped card is measurement-only, never a tuning card).
- **The eight seed cards stamped `frozen`** (B1–B8) — the ratified seed FROZEN eval set, byte-behavior-identical
  to today (the battery loads/validates/dispatches them unchanged).
- **The born-frozen-XOR-born-dev lock**: a `B<n>` id must be `frozen`; a `D<n>` id must be `dev`; the field and
  the id namespace must agree or the card fails validation. This is D4's "never crossing," enforced structurally.
- **A dev-card loader** (`load_dev_cards`, over `evals/battery/dev/D*.json`) — the separate authoring surface for
  tuning cards. The frozen battery's `B*.json` glob and the production plan-override resolver never see it, so
  the split adds zero risk to tonight's run.
- **The contamination tripwire** `assert_no_frozen_in_tuning(manifest, ...)` + `frozen_fingerprints(...)` —
  deterministic and **fail-loud**: any frozen card id or sandbox repo appearing in a tuning/dev-run manifest
  raises, naming every offender. Dormant until the #835 tuning harness (or any model-specific tuning run) calls
  it at its head; the gate test proves it fires on a simulated frozen-in-tuning-log.

Dormant-safe is the whole point: **stamping the cards frozen must not change what the battery does tonight** —
frozen IS the battery's job. The marker governs what may *edit* and *tune against* the cards, not how they run.

## PLANNED-vs-BUILT honesty (as of authoring, main @ ~6be0662b)

- **SHIPS with this ticket (built + gate-tested):** the `card_class` marker, the eight-card frozen stamp, the
  born-frozen-XOR-born-dev consistency lock, the dev-card loader, and the contamination tripwire — all in
  `tools/dispatch_harness/battery.py`, dormant-safe.
- **RATIFIED + IN FORCE (governance, not code):** today's battery cards are the seed FROZEN eval set; all
  model-specific tuning routes to a separate DEV set (a standing enforcement note for #835 and any future
  tuning: **MEASUREMENT-ONLY on frozen cards; tuning happens on dev**).
- **PLANNED (the evaluation harness itself — future tickets, not in this change):** the role-at-a-time swap
  runner, the Phase-1/Phase-2 driver, the pre-registered-bar scorer, the D1 replace/keep/disqualify decision,
  and the first real coder-seat candidate eval. #835 (the A/B program) is the first instance of the
  swap-one-variable discipline and half-seeds the oracle-author seat; #834 (profiles) is the adapter-config
  layer that makes a clean swap a data change. The referee (#821) and the honesty layer (#832/#837) this
  protocol leans on are already landed or in the QUALITY-program wave.

## Consequences

- **The future test is protected today.** The single most time-sensitive risk — model-specific tuning silently
  contaminating the cards a future candidate is judged on — is closed by a small, dormant-safe marker + a
  fail-loud tripwire, in force from this change. Every day of tuning from here iterates on dev, not on the
  frozen judge.
- **A model comparison is now a designed thing, not a vibe.** The protocol says exactly what to swap (one role),
  what to hold (optimization config), what to set correctly (adapter config), what referees the hardest seat
  (the model-blind oracle-QA layer), what makes it un-gameable (the honesty layer), and what bar clears a
  replacement (D1, declared in advance). A future session has one place that says how to judge a challenger.
- **The grading-maturation program's payoff is named.** #819–#837 was justified as nightly-run hardening; this
  ADR records its second dividend — it is the instrument that makes apples-to-apples model evaluation possible.
- **Safe-biased asymmetry is explicit.** The burden of proof sits on the challenger: honesty is a gate not a
  score, ties keep the incumbent, and a win must repeat. A more-capable-but-less-honest model is correctly
  treated as the more dangerous one.
- **Costs accepted, named.** A candidate eval spends battery nights (contained, reproducible, off the production
  seat); Phase 2 spends a bounded dev-set tuning budget; the quarterly refresh spends authoring effort to keep
  the frozen set hard. All are affordable because a model swap is rare and the protection is cheap.

## Rejected alternatives (on the record)

| # | Rejected | Reason |
|---|----------|--------|
| R1 | **"Which model gets more GREENs" as the bar** | gameable — a reward-hacking candidate wins; the honesty layer (§Decision-5) + the un-tuned frozen set (§Decision-2) are what make the count meaningful |
| R2 | **One undifferentiated card set for both tuning and judging** | contaminates the future test — the exact hazard D4 closes; the split costs nothing and is time-sensitive |
| R3 | **Monolithic "is model X better"** | unanswerable + unattributable across five roles; the role-at-a-time swap (§Decision-3) is what makes a delta mean something |
| R4 | **Holding adapter config neutral too (fully identical config both sides)** | that is *unfairness*, not fairness — a candidate denied its correct tool-parser/sampling can't function; adapter config is levelling, only optimization config is held (§Decision-1) |
| R5 | **A production swap to "try the new model live"** | uncontained + irreproducible + risks the operator's live stack; evaluation stays inside the battery containment (§Decision-6) |
| R6 | **Replace on any win / on a single run** | ignores switching cost + the #778 thermal sign-flip; the safe-biased bar keeps the incumbent on ties and requires a repeating margin (D1) |
| R7 | **A model judging the candidate (LLM-as-judge for the oracle-author seat)** | puts a model back in the honesty-critical path (ADR-037 invariant 9); the deterministic oracle-QA layer (#821) is the model-blind referee (§Decision-4) |
| R8 | **Heavy nightly contamination-free benchmark machinery** (r1extern R9, SWE-bench-Live class) | wrong scale for one box — the *principle* is adopted at a light grain (the frozen/dev split + tripwire), the machinery is not |
| R9 | **Post-hoc bar (decide "better" after seeing the run)** | a moving goalpost; the bar is pre-registered on the frozen set before the run (D1) |

## References

- **This ADR / program:** Vikunja **#838** (QUALITY-18, ADR-038) — the LA's forward-looking question
  (2026-07-11), the coordinator recommendations (c.1740), and the LA decision (c.1744, "yes to all", quoted
  verbatim in §Decision-2/7/8/9); inside the QUALITY program **#819–#837**.
- **Live code (this change):** `tools/dispatch_harness/battery.py` (`card_class` validation, the
  born-frozen-XOR-born-dev lock, `load_dev_cards`, `frozen_fingerprints`, `assert_no_frozen_in_tuning` +
  `FrozenContaminationError`); `evals/battery/B*.json` (the eight seed cards, stamped `frozen`);
  `evals/battery/dev/README.md` (the dev-card authoring convention); `tests/integration/test_battery_runner.py`
  (the split + tripwire locks).
- **Builds-on code:** `shared/fleet/oracle_qa.py` (#821 — the model-blind referee); `tools/dispatch_harness/
  battery.py::cross_check` + `tools/dispatch_harness/scorecard.py` (the FALSE-DONE honesty layer, #832/#837);
  `shared/fleet/swap_ops.py` / `swap_driver.py` (the swap driver + verdict computation, ADR-034/037).
- **Related tickets:** **#834** (model-profiles = the adapter-config layer), **#835** (the A/B = the first
  swap-one-variable instance; A1 half-seeds the oracle-author seat), **#816** (env self-capture), **#778** (the
  thermal sign-flip lesson), **#748** (seed-protected oracle).
- **Prior ADRs:** ADR-037 (the Grading & Integration Machinery — the honesty invariants / gate ladder / oracle
  lifecycle / verdict taxonomy / Small-Model Consciousness this protocol reuses), ADR-035 (Acceptance Layer),
  ADR-034 (model-swap driver / containment).
- **External literature:** Verification Horizon — no fixed grader stays valid as capability changes (arXiv
  2606.26300, this ADR's swap-time twin); the frontier contamination concern (r1extern R9 / SWE-bench-Live
  class) adopted at a light grain. Design dossiers: `docs/handoffs/*-20260711.md` (citations, not sources).
