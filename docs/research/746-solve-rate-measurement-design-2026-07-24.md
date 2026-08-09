---
title: "#746 §9 measurement design: does plan-time research grounding move the solve rate?"
status: proposal
area: research
---

# Measurement design for #746's "does research move the solve rate?" DoD line

**Plain summary:** there is no existing methodology for this measurement anywhere in the repo —
the DoD line just names the question. Having now traced the actual code paths and the fleet's
real capability profile, a naive before/after A/B on the current battery card set would very
likely show nothing either way, for reasons that have nothing to do with whether research
grounding works. This document names why, and proposes what to measure instead.

## What was verified before designing anything

**1. Only five of the eight cards ever reach the code path research grounding touches.**
Traced `shared/fleet/acceptance.py::generate_plan` directly: `research_grounding`/`research_index`
thread into the real `decompose_request(...)` call only in the `else:` branch taken when
`decomposition_override is None`. Battery cards with a registered arm builder
(`battery_plans._PLAN_BUILDERS = {"B1", "B2", "B4"}`) always pass a non-`None` override and
therefore **never reach `decompose_request` at all** — grounding is structurally inert for them,
by construction, regardless of the flag. Every other card (B3, B5, B6, B7, B8, both web cards)
has no registered builder, passes `override=None`, and DOES flow through the grounded path.

This is confirmed by reading `_is_card_driven`'s own docstring (an author self-correction caught
in pre-merge review): the FIRST predicate tried for a *different* flag (`advanced_intake`) was
"`decomposition_override is not None`" and it was wrong for exactly this reason — it under-covers
five real cards. `research_grounding`'s gate uses the narrower, override-only test (not
`_is_card_driven`), so — unlike `advanced_intake` — it is NOT self-suppressed for card-driven
dispatch in general, only for the three cards with builders.

**Consequence:** every card used in tonight's validation windows (B2, B4 — the lean-diagnostic
pair) is one of the three that can NEVER show a grounding effect. Any "before/after" run on B2
or B4 measures nothing about #746, structurally, no matter how many times it's run.

**2. Even the five reachable cards almost certainly won't show an effect with the CURRENT
docset**, per tonight's #1101 measurement: the fleet's entire generated-code corpus across 97
real files shows exactly 3 distinct third-party modules (`pytest`, `hypothesis`,
`setuptools` — two of which are harness-injected, not coder-chosen), because every generated
project skeleton mandates `dependencies = []`. Read B6's and B7's actual goals (inventory
manager with CSV export; three Node CLI utilities) — both are squarely within a 30B model's
native stdlib/vanilla-JS knowledge. Nothing in either goal creates a plausible scenario where
plan-time docs about a third-party library would change what gets planned or built. The docset's
whole value proposition (library-API depth) has no live use case on any of the five
grounding-reachable cards as they're currently written.

**So a naive A/B here has two independent reasons to show a null result that have nothing to do
with whether grounding works**: (a) picking the wrong card family entirely (B1/B2/B4 structurally
can't show it), and (b) even the right family's current goals don't create a scenario the
docset's content addresses.

## What this means for the measurement

**Recommendation: do not run a before/after solve-rate A/B on the current battery set.** A clean
null result would be uninterpretable — it wouldn't distinguish "grounding doesn't help" from
"nothing here needed grounding to begin with," and a battery run costs 1–2.5 GPU-hours of real
wall-clock per arm, which is too expensive an instrument to spend on a comparison that can't
actually discriminate.

**Two honest paths forward, in order of how directly they follow from what's measured:**

1. **Run the DoD's OWN cheaper, more tractable alternative first.** #746's design already names
   a scoped-down validation that doesn't need a statistical A/B at all: *"a live demo where the
   tester hits an error code and the deterministic lookup resolves it OFFLINE."* This tests the
   REACTIVE half of #746 (the coder's `search_docs` tool, already merged and 19/19 tested) against
   a single, deliberately-chosen scenario — an error a 30B coder is plausibly unfamiliar with,
   where the deterministic-first lookup path can be observed directly rather than inferred
   statistically. This is buildable now, costs one interactive session (no overnight window
   needed), and directly exercises code that's already live in the repo (dormant, opt-in).
2. **If a genuine solve-rate A/B is still wanted**, it needs a PURPOSE-BUILT card first — one of
   the five grounding-reachable cards (B3/B5/B6/B7/B8), or a new one, whose goal genuinely
   requires knowledge outside a 30B model's native training (a moderately obscure library API, a
   documented gotcha/error class the docset actually covers) — not a retrofit of an existing
   stdlib-only card. Given the zero-third-party-deps skeleton mandate applies fleet-wide today,
   this also requires deciding (a decision already flagged to the LA on #1101, not re-decided
   here) whether the fleet's skeleton policy itself should ever allow a card to declare a real
   dependency — without that, no card can exercise the docset's actual content no matter how it's
   designed.
   - If/when such a card exists: run it N≥3 times per arm (grounding on/off), same card, same
     complexity band, on a night with no other instrument change riding along (this repo's own
     one-variable-per-run discipline) — single-run noise is real (tonight's B4 windows show two
     independent PARKED-HONEST results on an unrelated defect, underscoring how much variance one
     run alone carries). Compare plan/decomposition quality (the dispatch-quality-ledger's six
     standing dimensions) alongside final solve/park, since a grounding effect could show up in
     scope fidelity or assumption quality before it shows up in a binary pass/fail.

## What was NOT done here

No battery window was launched for this. No card was built. This is a design document only,
produced by reading the actual `acceptance.py`/`decompose.py`/`battery_plans.py` code paths and
cross-referencing tonight's #1101 measurement — not a live experiment. The recommendation (run
the cheaper reactive-tool demo first) is a technical judgment, offered for review, not a decision
requiring the LA's sign-off — building either path still needs someone's hands, which is why this
stays a proposal rather than an executed measurement tonight.
