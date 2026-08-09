# Coherence-Gate (S3 slice E) Go-Live Runbook

<!-- doc-rot gate (#994): the config flag gating this ceremony. Live posture is read from services/assistant_orchestrator/config/default.toml, never from this doc. -->
<!-- Gating-flag: [fleet_dispatch].advanced_intake_coherence_gate -->

> ## STATUS: EXECUTED 2026-07-29 — via the batched S3 ceremony, not this runbook's own steps.
>
> The flag went live as one of the four switches of the batched D/E/F/G ceremony
> (`advanced_intake_s3_batched_ceremony.md`; decision row in `docs/DECISION_REGISTER.md`,
> demo evidence on #1069). The steps below were superseded by that batch and are kept as
> the slice's reference material — the "why" section, the demo shapes, and the reversal
> note remain accurate. Live posture is read from `default.toml`, never from this file.

**Flip → boot → drive one real intake → confirm the plan is coherent → confirm a
contradicting plan is refused → evidence.** This is the LA-present ceremony that takes the
coherence gate from dormant to live. Written for the Lead Architect (non-developer-friendly).
Everything here is **reversible**: flipping the flag back to `false` and restarting fully
restores the prior behaviour, because the change only affects how a plan is written and
whether it is offered — nothing already built or shipped is touched.

## Why this exists — the plan that argued with itself

On 2026-07-22 a real dispatch (goal: *"a web page to track daily water intake, with a button
to add a glass and a running total"*) produced a plan whose assumptions said **"Assumed a
reset button is not needed"** while its acceptance criteria said **"The web page includes a
reset button to reset the daily water intake counter to zero."** One document told the coder
both that a capability was out of scope and that it was a graded requirement. The same plan
also invented two features the goal never mentioned (a daily goal with progress, and
historical data).

Both halves have the same cause: the assumptions and the criteria were written by two
separate model calls that never saw each other's output, so there was no place for the
disagreement to be noticed.

## What this ceremony makes live

Two things, and the second is the one with teeth.

1. **Single-pass authoring.** The acceptance criteria and the product assumptions are written
   in ONE model call whose prompt carries both jobs. The scope decision is made once, in one
   context, so the model cannot rule a capability out in one block and require it in the
   other. The same prompt carries a **scope anchor** — assert only behaviours the request
   names — which is the other half of the same defect.
2. **A deterministic contradiction gate.** After authoring, the assumptions and criteria are
   parsed and the plan is **refused** when a criterion requires a capability an assumption
   ruled out, or the reverse. The refusal names the two statements that disagree, in the
   model's own words, and enqueues nothing.

The prompt is the quality half; the gate is the guarantee half. If a future model regresses,
a self-contradicting plan of the kind it can see still cannot be offered.

**This is a capability change** — a dispatch that could previously only be *planned* can now
be *refused* at plan time — which is why it is a ceremony rather than a proven-defaults flip.

## What it does NOT do

- It does **not** edit a plan to reconcile it. Deciding which half of a disagreement was
  wrong is your judgement, not a rule; the plan is declined and you re-dispatch.
- It does **not** widen the elicitation interview, derive an oracle import contract, or make
  the plan-time coverage check blocking. Those are separate, and unbuilt.
- It **never runs for a battery or headless card dispatch**. A card *is* the spec, frozen so
  that different nights stay comparable, so it is suppressed exactly as the S1 rulers are.
- It requires `advanced_intake = true` as well. On its own this key does nothing.

## What can go wrong, in BOTH directions — read this before you flip it

An earlier draft of this section listed only what the gate MISSES. That was the wrong half of
the picture to give you, because this control can also **refuse a plan that was perfectly
fine**, and that is the outcome you would actually feel.

**It can refuse a good plan, and there is a known way it still does.** The gate reads ordinary
English with patterns, and a pattern can be wrong. When it is, you lose the plan: you are told
which two sentences it thinks disagree, nothing is built, and you dispatch again.

Three such faults have been found. **Two are fixed and locked with tests:**

- an ordinary two-clause sentence — *"a reset button would be useful, but it is not needed for
  a first version"* — was refused **because of the comma**, which stopped the pattern reaching
  the words before it;
- *"the app launches without an error message"* was read as banning error messages, when it is
  just describing a clean launch.

**The third is still present, and you would be flipping this on with it in place (#1096).**
When a sentence says a feature is not wanted in one *place* or one *form*, the gate hears it
as not wanted at all:

- *"The user data is not stored on a server"*, alongside an assumption that the user data
  stays in the browser;
- *"The reset button is not shown on the print view"*.

Both plans are perfectly consistent. Both are refused. This is not a regression — it has been
there since the first version of this feature — and it is disclosed rather than fixed because
the fix means changing the matching logic, and logic changes stacked in consecutive fix rounds
are what has been introducing fresh faults on this tree. #1096 carries it, with a definition
of done that forbids buying the fix by refusing more plans elsewhere.

The test sets measure **zero** wrong refusals across 30 plans and that number is real — but it
was measured on plans that happen not to contain the third shape, which is exactly how that
shape survived two independent reviews. Read "zero" as *none left that we knew how to look
for*, never as *impossible*.

**It misses more than it catches.** It only sees disagreements about a capability named in
**two or more words** ("reset button", "dark mode toggle"). Every one of the ten commonest
one-word features — history, search, undo, login, pagination, notifications, autosave,
printing, charts, sorting — escapes completely. It also misses *"the reset button is not shown
until an entry exists"* (#1095), which does require a reset button. Measured across **both**
test sets it caught **22 of 36** planted contradictions, about 61%. A single test set read 14
of 16 and made it look like 88%; the two-set figure is the honest one.

**It decides contradiction, not correctness.** Two statements that agree with each other and
are both wrong about what you asked for pass cleanly.

It is a floor against a plan arguing with itself, not a proof of a good spec.

## What is ALREADY BUILT (verify, don't build)

- `shared/fleet/coherence.py` — `check_coherence`, the deterministic gate, plus the refusal
  text the operator reads.
- `shared/fleet/acceptance.py` — `_COAUTHORED_TEMPLATE` and `_coauthor_spec` (the single
  authoring pass), and the gate's one call site inside `generate_plan`, which runs only when
  `advanced_intake` **and** `coherence_gate` are both true and the dispatch is not card-driven.
- The gate ships with the review findings of 2026-07-23 as regression tests
  (`shared/tests/test_coherence_gate.py`), including the comma case and the
  launches-without-an-error-message case above.
- `services/assistant_orchestrator/src/entrypoint.py` — the resolved property
  `fleet_dispatch_advanced_intake_coherence_gate_enabled` (validate-not-coerce: only an
  explicit boolean `true` enables it).

## The ceremony

1. **Flip.** `advanced_intake_coherence_gate = false → true` in `default.toml`, on a feature
   branch, with this runbook, the DECISION record, and a journal entry in the same change.
2. **Gate.** Standing gate green on the branch and re-measured on merged main.
3. **Merge.** The flip IS the go-live.
4. **Boot** the assistant so the resolved config carries the flag.
5. **Live-verify — the coherent case.** Drive one real intake through the running assistant
   (the water-tracker goal is the natural choice, since it is the measured defect) and
   confirm the plan card's assumptions and criteria do not contradict each other, and that no
   criterion asserts a feature the goal never asked for.
6. **Live-verify — the refusal.** Drive an intake whose goal deliberately invites the
   contradiction, and confirm that if the model produces one, the dispatch is declined with
   the two disagreeing statements named. If no contradiction is produced, record that the
   refusal path was not exercised live rather than claiming it was.
7. **Live-verify — which emitter actually wrote the spec.** Everything above was built and
   tested against a FAKE model, so the ceremony is the first time the real 14B writes a
   co-authored spec. Two things to check, because tests cannot:
   - the plan carries **both** assumptions and criteria and they read as one document —
     if the assumptions look re-asked, the grammar-constrained emission was judged unusable
     and the run silently fell back to the old two-call path (harmless for quality, but the
     single-context guarantee is lost for that plan, and a run of them is a signal the prompt
     or the schema needs work);
   - the criteria stay inside the goal — the **scope anchor** is the half of this slice with
     no deterministic backstop at all, so the only evidence it works is what you read here.
8. **Evidence** — the live plan (and any refusal text) captured to the #1054 ticket, including
   an honest note of any step above that could not be exercised.

## Reversal — fully sufficient, no residue

Flip `advanced_intake_coherence_gate = false` in `default.toml` and restart the assistant.
Authoring returns to the two-call path and no gate runs. Because the change acts only at plan
time, no built artifact, no shipped dispatch, and no stored spec is altered by the reversal.
There is no key to destroy and no allowlist to empty; the flag is the whole surface.
