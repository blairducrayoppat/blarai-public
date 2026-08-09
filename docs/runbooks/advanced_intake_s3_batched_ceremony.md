# Advanced-Intake S3 — the Batched D/E/F/G Go-Live Ceremony

<!-- doc-rot gate (#994): the config flags gating this ceremony. Live posture is read from services/assistant_orchestrator/config/default.toml, never from this doc. -->
<!-- Gating-flag: [fleet_dispatch].advanced_intake_bad_input_floor [fleet_dispatch].advanced_intake_coherence_gate [fleet_dispatch].advanced_intake_coverage_gate [fleet_dispatch].advanced_intake_criteria_revise -->

> ## STATUS: EXECUTED 2026-07-29.
>
> The four S3 sub-flags are `true` in
> `services/assistant_orchestrator/config/default.toml` (see the flip commit for the
> in-chat confirmation record; decision row in `docs/DECISION_REGISTER.md`; demo
> evidence on #1069). Live posture is read from `default.toml`, never from this file.

**One sitting, four switches, one real dispatch, your decision on each.** This is the
LA-present ceremony you decided on #1069 (c.2512): the S3 authoring redesign goes live as
ONE batched event across its four dormant slices — never four separate evenings — and the
ceremony gates only the switch-on, never the build, the review, the merge or the tests,
all of which happened while the flags stayed false. Written for the Lead Architect
(non-developer-friendly). Everything here is **reversible**: any flag back to `false` plus
a restart fully restores the prior behaviour — these slices act only at plan/revise time
and never touch anything already built.

## The four switches, in one sentence each

| flag | slice | what `true` does |
|---|---|---|
| `advanced_intake_bad_input_floor` | D (#1044) | every python exam gains machine-injected malformed-input checks — a build that only ever worked on the happy path now fails an exam it used to pass |
| `advanced_intake_coherence_gate` | E (#1054) | criteria + assumptions are written in ONE pass, and a plan that argues with itself is refused with the two disagreeing sentences named |
| `advanced_intake_coverage_gate` | F (#1069) | the exam's import list is pinned to the plan's declared parts; a surviving gap BLOCKS approval — "the system won't let you sign something it couldn't check" — with revise and reject open and a gap-closing revision re-opening approve |
| `advanced_intake_criteria_revise` | G (#1055) | criteria/scope feedback on a pending plan actually edits the judged checklist; automatic (machine-checked) criteria stay keep-only and the card says so |

Each needs the already-live `advanced_intake` front as well; each alone does nothing.
**Each is independently yours to decline** — the batch is one sitting, not one vote. A
declined flag simply stays `false`; nothing else changes.

## Preconditions (verify, don't build)

1. All four slices MERGED on main, each merged dormant with its independent pre-merge
   review and its regression locks (D/E: `546146e4` era; F/G: the 2026-07-28 overnight
   merges — SHAs on #1069's comments).
2. Standing gate green on current main (`docs/TEST_GOVERNANCE.md` §1 figure).
3. The battery's nightly window is not imminent (the ceremony restarts the assistant;
   never inside the 23:00 window — runbook `battery_cadence_and_targeted_runs.md` Rule 1).
4. This file's banner said NOT YET PERFORMED and the doc-rot gate was green (the two
   surfaces agreed) — checked pre-flip; the banner above records the execution.

## The ceremony

1. **Decide.** For each of the four rows above: live, or stays dormant. Slice F is the one
   you already ratified in principle (#1069 c.2461/c.2512); the other three you approved as
   builds — this is where each becomes reachable.
2. **Flip.** The chosen flags `false → true` in `default.toml`, on a feature branch, with
   this runbook's banner updated to EXECUTED (naming which flags flipped), the DECISION
   record row, and a journal entry — one change.
3. **Gate.** Standing gate green on the branch; re-run on merged main.
4. **Merge LIVE** (the flip IS the go-live) and **boot** the assistant.
5. **Live-verify, one real dispatch per behaviour** (the session driving it announces each
   step; you witness):
   - a multi-part python ask → the plan card's exam carries bad-input checks (D) and the
     plan reads coherently (E);
   - a deliberately gapped plan (the driving session can stage one) → the card renders
     BLOCKED, approve is refused with the gap named, a revise that drops the uncovered
     part re-opens approve (F) — and this gapped run is TIMED cold: F's repair round
     adds one authoring+QA pass to the worst-case PLAN sequence, and the 720-second
     PLAN budget's registry review line asks for a re-measurement on exactly this
     shape (#1152; S3-F review F8);
   - criteria feedback on a pending plan → the judged checklist changes, the automatic
     checks report "protected" (G).
6. **Evidence** — each card captured to #1069; the four member tickets (#1043/#1044/#1054/
   #1055) close citing the commits that retired their classes, per the predicate.

## Reversal (RE-WELD) — per flag, fully sufficient

Any flag back to `false` in `default.toml`, restart. D/E/F act only at plan time; G only
at revise time; no built artifact, shipped dispatch, or stored spec is altered by a
reversal. The next plan (or revise) is byte-identical to the pre-go-live behaviour of that
slice, with the other three unaffected — the flags are independent in both directions.

## What stays exactly as it is, live or not

The quick `/dispatch` path's warn-loud coverage disclosure and its rationale; battery and
headless card dispatches (every slice self-suppresses — the card IS the instrument); the
task-revise wall (the acceptance-tests task is never editable); and the `advanced_intake`
front itself, which this ceremony neither re-decides nor extends.
