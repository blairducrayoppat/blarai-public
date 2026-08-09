# Advanced-Intake Interview (S2) Go-Live Runbook

<!-- doc-rot gate (#994): the config flag gating this ceremony. Live posture is read from services/assistant_orchestrator/config/default.toml, never from this doc. -->
<!-- Gating-flag: [fleet_dispatch].advanced_intake_interview -->

> ## STATUS: EXECUTED 2026-07-29.
>
> `[fleet_dispatch] advanced_intake_interview` is `true` in
> `services/assistant_orchestrator/config/default.toml` (see the flip commit for the
> in-chat confirmation record; decision row in `docs/DECISION_REGISTER.md`; live-verify
> evidence on #1031). The §6 memory question is settled there: `advanced` DEFERS to
> remembered answers, with `/dispatch forget <project>` as the fresh-interview escape.
> Live posture is read from `default.toml`, never from this file.

**Decide the memory question → flip → boot → drive one `advanced` intake → confirm the
fuller interview + the record tags → evidence.** This is the LA-present ceremony that
takes the S2 elicitation interview from dormant to live. Written for the Lead Architect
(non-developer-friendly). Everything here is **reversible**: the flag back to `false` plus
a restart fully restores today's behaviour — the token stops parsing and the next dispatch
is byte-identical to the pre-go-live front.

## What this ceremony makes live

Typing `/dispatch advanced <project> | <what to build>` (or `advanced new <name> | …`)
runs the FULLER requirements interview: the five quick questions' decision areas plus
three more — **content** (what real text/items/data it should hold — the question whose
absence let a build invent placeholder projects), **edge cases** (what should happen on
odd or wrong input, in your words), and **non-goals** (what this first version should NOT
include). Still one screenful at most, still one plain-language reply, still
"just decide for me" with the chosen defaults shown on the card. Each recorded answer is
tagged on the run's record with the decision area it covered.

A normal `/dispatch` stays byte-identical; the only quick-path change is one hint line on
big asks naming the `advanced` form. Nobody is ever interviewed without asking.

## Preconditions (verify, don't build)

1. S2 merged on main (dormant), its independent design review + code review dispositions
   on record, standing gate green.
2. `[fleet_dispatch].clarify = true` (the interview rides the clarify stage — with it
   off, `advanced` asks nothing and says "No further questions").
3. `advanced_intake = true` (the live front; the interview requires it as well).

## The one decision this ceremony settles (design §6)

**What does `advanced` do on a project that already has remembered answers?** Project
memory (#1120/#1124, its own LA-held ceremony) suppresses all questions once a project
has banked answers. As built, `advanced` DEFERS to memory and says so honestly — one
notice line naming `/dispatch forget <project>` as the fresh-interview escape. The
alternative (the token overrides the suppression; fresh answers supersede banked ones) is
buildable if you prefer it. Settled at the 2026-07-29 ceremony: DEFER, as built (see
`docs/DECISION_REGISTER.md`).

## The ceremony

1. **Decide** the memory question above.
2. **Flip.** `advanced_intake_interview = false → true` in `default.toml`, on a feature
   branch, with this runbook's banner updated to EXECUTED, the DECISION record row, and a
   journal entry — one change.
3. **Gate.** Standing gate green on the branch; re-run on merged main.
4. **Merge LIVE** (the flip IS the go-live) and **boot** the assistant.
5. **Live-verify, witnessed:** one `/dispatch advanced <project> | <a deliberately vague
   goal>` → the fuller interview renders (content/edge/non-goal questions among them);
   answer in one reply → the plan card shows your words; approve or reject; the run
   record carries the axis tags. Then one NORMAL `/dispatch` → today's behaviour,
   unchanged.
6. **Evidence** — the interview transcript + card captured to #1031.

## Reversal (RE-WELD) — fully sufficient, no residue

Flip `advanced_intake_interview = false` and restart. The token stops parsing, the marker
is inert text, the eight-axis vocabulary is unreachable, and no stored record or parked
question is altered — a pre-reversal intake record simply keeps its truthful labels.
