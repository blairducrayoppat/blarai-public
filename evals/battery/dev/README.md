# Dev / tuning battery cards (`evals/battery/dev/`)

This directory holds **DEV cards** — the tuning surface for model-specific refinement.
It is the counterpart to the **FROZEN** eval set (`evals/battery/B*.json`), and the
split is the train/test split applied to the harness itself (ADR-038 §2 / D4).

## The rule (ADR-038 D4 — LA-decided 2026-07-11, #838 c.1744)

- **FROZEN cards (`B*.json`, one level up) are MEASUREMENT-ONLY.** They are locked,
  versioned, model-neutral, and used **only** for candidate comparison + regression.
  **Never tune against a frozen card** — every day of tuning that iterates against the
  cards a future candidate is judged on silently contaminates that comparison.
- **DEV cards (`D*.json`, here) are the tuning surface.** Iterate prompts, profiles,
  and task grain against them as freely as refinement demands.
- **Born-frozen XOR born-dev, never crossing.** A card is authored as one class or the
  other and never migrates. A frozen card is never edited in place (add-only + immutable
  + versioned); the quarterly grading review (ADR-037 §Decision-9) authors fresh *hard*
  frozen cards and retires trivially-passed ones (co-evolution).

## Authoring a dev card

1. Id in the **dev namespace**: `D<n>` (`D1`, `D2`, …) — never `B<n>`.
2. Set **`"card_class": "dev"`** explicitly (a `D<n>` card that omits it fails
   validation — dev cards self-declare; they never inherit `frozen`).
3. Same `battery-card/v1` schema as a frozen card otherwise (sandbox `battery-<slug>`
   repo pin, `expected_outcome`, etc. — see `tools/dispatch_harness/battery.py::validate_card`).
4. Load them with `battery.load_dev_cards()` (the frozen `load_cards()` globs `B*.json`
   only and never sees this directory).

## The contamination tripwire

`battery.assert_no_frozen_in_tuning(manifest_tokens)` is the fail-loud gate that makes
"MEASUREMENT-ONLY on frozen cards" real (a rule without a gate is a defect). Any tuning
run must call it at its head with the ids/repos it touched; it raises
`FrozenContaminationError` naming every frozen card id or sandbox repo that leaked into
the tuning manifest. It is dormant until a tuning harness (e.g. the #835 A/B) calls it,
so it changes nothing about the nightly measurement battery.
