<!-- Gating-flag: [fleet_dispatch].advanced_intake_interview_voice [fleet_dispatch].advanced_intake_interview_playback [fleet_dispatch].advanced_intake_assets_pipeline -->

# Runbook — interview-maturation go-live (#1165), wave 1

> **STATUS: EXECUTED 2026-07-29 (LA-present).** Three flags live: `advanced_intake_interview_voice`
> (M1), `advanced_intake_interview_playback` (M4), `advanced_intake_assets_pipeline` (M5).
> Evidence: flip commit on this branch; `docs/DECISION_REGISTER.md` row of the same date;
> #1165 c.2663-onward; merged-main gate 9621 passed / 0 failed pre-flip.
> This banner points at evidence; it never asserts a witness.

## What this ceremony covered — and what it did not

LIVE now: the novice-voiced interview questions + Phase-0 preamble + the whole-reply
"I don't know" hatch (M1); the plan card's two playback questions + plain-words correction
routing into the bounded revise path (M4); the `assets/` + `assets/reference/` folder
contract, one plan-time enumeration into `spec.operator_assets`, the card acknowledgment,
the web machine-tier use floor and the droppable operator-tier visual criterion (M5).

NOT built, therefore NOT live: M2 (the interview's own assets QUESTION), M3 (propose-and-veto
plus the extras axis), M6 (reference-screenshot emulation — `assets/reference/` is seeded and
excluded from the manifest, but nothing reads it yet). The operator must place files himself
and the interview will not ask about them until M2 ships.

## Preconditions (all held at execution)

1. All three slices merged to `main` with independent review + fix-verification + disposition
   records (`docs/reviews/1165-m{1,4,5}-*-disposition-2026-07-29.md`, each machine-verified).
2. Merged-main full standing gate green: 9621 passed / 0 failed / 7 skipped (live-app class).
3. Each flag shipped dormant and was flipped by the ceremony, not by a build.
4. The three shipped-posture pins in `services/assistant_orchestrator/tests/test_plan_handler.py`
   inverted in the SAME commit — a silent revert to dormant now fails the gate.

## The flip

`services/assistant_orchestrator/config/default.toml`, `[fleet_dispatch]`: each key set
`true` with a `# GO-LIVE 2026-07-29 (#1165 <slice>, LA-present ceremony)` comment.
Restart the assistant so the AO re-resolves config (config is read at start, never hot).

## Live-verify (the LA drives; script of record on #1165)

The drive exercises all three slices in one sitting: an `advanced` dispatch on a project with
files in `assets/`, the "I don't know" hatch on one axis, then a plain-words correction typed
at the plan card with no verb. Expect: the preamble, life-worded questions, the assumption
recorded on the card, "Working from your assets folder: …", the two playback questions, and a
revised card carrying the correction.

## Reversal

Per-flag: set the key back to `false`, restart. That slice's prior behaviour returns
byte-identically (plan/render-time only; no stored record, parked question or scaffold
altered). Reverting M5 leaves any already-created `assets/` folders in place, harmlessly.
