### 2026-07-10 — Teaching the fleet to grade its own homework, without letting it change the answer key

*Plain summary: built the #793 M3 fleet lesson-candidate miner in agentic-setup
(branch `feat/793-lesson-miner`, `8fdefaf`) — a post-pass, report-only miner that
reads the coder fleet's dispatch scorecards and proposes UNTRUSTED AGENTS.md
instruction deltas behind a verification harness (model proposes, deterministic
ruler disposes), DORMANT until a golden-set quality gate proves it. Nothing
self-modifies; landing is M4's job.*

M3 is the coder-fleet half of the Learning Loops program (#770): the fleet already
records what happens on every dispatch — scorecards with the verdict/attribution
vocabulary, oracle results, guest certificates, campaign history — and the miner
turns that exhaust into *proposed* improvements to the coder's instruction file.
The whole design tension is in one sentence of the study's §4.3 register: a
14B-class consolidator is the *exposed* case for semantic drift (Memory Contagion:
weaker models propagate evaluator bias cross-temporally). The LA overrode the
recommendation anyway — D-5(b), the miner must be local from day one — and told us
to harness it "just like we do the coder." So the harness is the product, not the
model call. The model may *select and count* evidence; it may never paraphrase it,
and it decides nothing.

That made the load-bearing control a mechanical one: every evidence quote a
candidate cites must **byte-match** its source scorecard as a verbatim substring, or
the candidate dies and is reported dropped. It is the P2 rule (verbatim, never
14B-summarized) extended to Loop 2, and it is deterministic — no classifier, no
judgment, no way for a smaller model's confident paraphrase to survive. The rest of
the ruler runs only on byte-verified candidates: recurrence ≥3 distinct runs,
diversity ≥2 distinct jobs/eras (one pathological run cannot mint a lesson), novelty
against the existing lessons, a forbidden-class lint, and the LA-approved
removals-as-removals lint (a proposed delta must *delete* a rule, never append a
"stop doing X" negation of a still-present one — the accretion anti-pattern he named
watching LLM-maintained documents rot). Nothing is silently capped: every drop
carries its stage and reason into the file.

Two judgment calls are worth keeping. The first is a **polarity inversion I only saw
because the swap driver taught it to us first.** The miner must not run mid-dispatch,
so it reads the same `state/fleet-swap/current.json` the boot reconciler reads — but
with the *opposite* fail-direction. The reconciler (lesson 216, #758) fails
"driver-not-alive ⇒ recover," because stranding a genuinely-crashed swap forever is
the worse outcome for *it*. The miner fails the other way — unsure ⇒ assume live ⇒
refuse — because stepping on a running dispatch (and fighting the 30B for the GPU) is
the worse outcome for *it*. Same state machine, same driver-liveness probe, inverted
polarity, and the reason is entirely about which mistake costs more. I wrote the
guard's fail-closed direction deliberately and tested both edges.

The second is that the **forbidden-class lint is over-broad on purpose, and I have
the receipt.** Running the harness over 113 real runs (via a recorded replay so the
GPU stayed reserved), a perfectly legitimate candidate — "several jobs parked at
BUILD, the coder stops short of the finish line" — got dropped because its prose
mentioned the "acceptance oracle." That is not a bug. A keyword lint that drops *any*
candidate touching the verify gate / secret scan / FALSE-DONE cross-check will
over-drop legitimate mentions; the rejected alternative (a semantic classifier
deciding which mentions "really" weaken a control) is exactly the fuzzy judgment
that must not sit on the self-modification write path. Conservative-and-reported
beats clever-and-silent here; M4 can refine the boundary with the operator in the
loop. I reworded the probe to show a genuine real-data survivor too, so both edges
are on the record.

Surfacing stays dormant by construction (D-5/D-6): the candidates file is always
written, but the one-line Vikunja pointer that would put a pass in front of the
operator is *built and withheld* behind a single config flag until the golden-set
gate is judged acceptable — the C12 auditable-single-flip pattern. The golden set
(`lm_golden.py`) is that gate's substrate: seeded fixtures whose known-correct
outcomes fire each stage — a non-recurrent kill, a forbidden-class kill, a
paraphrase-drift kill, a negate-by-append kill, plus non-novel and malformed — against
one candidate that must survive. 11/11 gate checks, 17 unit tests, and
`scripts/verify-lesson-miner.ps1` wires it into the repo's verify convention.

**Proposed lesson (recurrence of the #758 driver-alive class, lesson 216):** *the
same state file read by two consumers can need opposite fail-closed polarities — the
safe direction is a property of the reader's worst outcome, not of the file.* The
swap reconciler fails toward recovery; the lesson-miner, reading the identical
record, fails toward refusal. When reusing a liveness/phase signal in a new consumer,
re-derive the fail-direction from scratch; do not inherit the source's polarity.
(If the curator judges this a new class rather than a 216 tally, it is the
polarity-is-purpose-dependent lesson.)

**Next:** the coordinator runs the first REAL mining pass in a post-swap GPU window
(`start-llm.ps1 -Model qwen3-14b`, then `python tools/lesson_miner/lesson_miner.py
--real`), reads the candidates file, and — only if the golden gate is judged
acceptable — flips `surfacing_dormant` to False to let the D-6 pointer post. Landing
any delta is M4's separate gate chain (deterministic verify → A/B golden-dispatch →
operator card); the ADR-022 taxonomy entry formalizes D-5..D-7 when that gate is built.
