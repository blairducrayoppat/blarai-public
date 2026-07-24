---
title: "Coder Fleet — Measured Capability Assessment"
status: living (run-2 + nightly slots updated as results land)
area: research
date: 2026-07-21
author: evening-watch session, LA-directed
companion: advanced-intake-design-sketch-2026-07-21.md
---

# BlarAI Coder Fleet — Measured Capability Assessment (2026-07-21)

**Plain summary:** what the local coding agent can reliably build today, by
language and complexity, grounded in the measured record — the battery archive
(49 usable runs across 8 cards), the dispatch-quality ledger, three supervised
end-to-end tests, and today's before/after instrument experiment. Written the
evening B4 recorded its first GREEN in history.

## 1. What was measured, and what this is not

Evidence base (all read on disk, not from summaries):

- The **battery archive**: 49 usable runs reconstructed from per-task git
  history across cards B1–B7 (#989 c.2299 method — commits attributed to tasks
  via agent markers, lines added excluding caches, wave order from each run's
  `swap-progress.log`).
- **`docs/quality/dispatch-quality-ledger.md`** — six-dimension graded rows for
  every signal-bearing run since 2026-07-14.
- **Three supervised end-to-end tests** (operator present): Blair's Lab static
  site (2026-07-14), Bill Splitter web tool ×2 (2026-07-15 aborted by a Windows
  restart; 2026-07-21 completed).
- **Today's A/B**: run `20260721-172005-bd` (pre-fix) and run
  `20260721-184705-bd` (with the #989 scope ceiling), plus tonight's 23:00
  nightly as the fresh-sandbox baseline.

This is **not** an external benchmark. Every app is sandbox-scale (hundreds to
~2,000 lines), per-card sample sizes are small (n=4–15), and the grading
instrument itself was under repair until this week — which is exactly why the
per-card numbers below carry attribution notes. §6 lists what has never been
measured at all.

## 2. The system under test, in one paragraph

A 30-billion-parameter local coding model (the "coder") runs on the machine's
own graphics card, swapped in place of the resident assistant model for the
duration of a job. A 14-billion-parameter orchestrator decomposes a
plain-language ask into a dependency-ordered task graph; each task builds in a
fresh isolated workspace with a "context pack" describing what earlier tasks
built; integration gates run between waves; a seeded, protected job-level exam
grades the final integrated app; and an isolated clean-room copy of the exam
(in the guest virtual machine) must agree before a pass is trusted. The
machinery's verdicts are honesty-first: a run that cannot verify its work parks
honestly (PARKED-HONEST) rather than claiming success.

## 3. Evidence: the battery cards

| Card | App (language) | Grain | Measured reliability | Attribution notes |
|---|---|---|---|---|
| B1 | Expense CLI (Python) | ~3 tasks | GREEN 07-14 and 07-15; retired to on-demand as a reliable passer | Wave-1 share 47.8% vs 33–50% split — borderline, at baseline |
| B2 | Text-stats CLI (Python) | 4 modules, 1:1 contract | **GREEN in every valid night, 15-run history**; clean scope (24.9% wave-1 share vs 25% even split) | The anchor card; guest clean-room agreement routine |
| B3 | Web multi-page (Node/web) | 5 tasks | Undetermined — excluded: tasks measured 40–85 min each vs the run envelope | Harness envelope, not coder signal |
| B4 | Flashcards CLI (Python) | 6 modules, 6 waves | **First GREEN in recorded history 2026-07-21** (run `20260721-172005-bd`, 6/6 gates, guest agree, 4,790 s). Before that: 7 consecutive nights parked | The 7 parks were the *exam's* fault (oracle called a module it never imported — #1008); attribution flipped BUILD→VERIFY on 07-20, the first honest night |
| B5 | Habit tracker (Node/web) | 4 tasks | No clean coder signal — recent failures are run-budget starvation (the #927 class) | Rejoins 07-22 via daytime validation (#969 c.2347) |
| B6 | Inventory CLI (Python, longest ~2.2 h) | 6–8 tasks | GREEN 07-14 (8/8 tasks) and 07-15; retired as a reliable passer | Produced the single cleanest scope run in the dataset (0.0% excess wave-1) |
| B7 | Utility trio (Node) | 3 modules, 1:1 contract | GREEN since the 07-14 layout fix; clean scope (15.0% wave-1 vs 33% split) | Node-side job grading still partial (#894 deferred) |
| B8 | Negative carrier | — | Never dispatched (rig-injection seam in build) | — |

**The load-bearing pattern (measured, #989 c.2299):** wave-1 scope discipline —
and downstream build quality — is predicted by **exam contract coverage**, not
by language, task count, or app size. Every card whose exam names one module
per task (B2, B7, early-B6) builds cleanly; every card with a contract gap
(B4, B5, late-B6) sprawls. B6 flipped from 0% to 44% excess purely because its
contract shape changed. Today closed the loop live: B4's repaired 1:1 exam
(#1008) removed its wave-1 sprawl **before** the #989 code fix ever executed
(run-1: wave-1 authored exactly its contract, +168 of 1,018 build lines, 16.5%
vs 20% even split).

## 4. Evidence: supervised end-to-end tests (operator-graded)

| Test | Outcome | What it proved | What it exposed |
|---|---|---|---|
| Blair's Lab static site (07-14, run `20260714-191219-bd`) | STALLED, attribution HARNESS; ticket stayed open | No-change detector + clean-workspace retry recovered two empty first attempts; nothing empty was merged | Scaffold-fit defect (#886): a server+fetch skeleton seeded onto a "one file, no build step" ask — operator saw a broken page the machinery never questioned; ~80 min burned on empty retries |
| Bill Splitter r1 (07-15, `20260715-081634-bd`) | ABORTED (Windows auto-restart) | Swap reconciler recovered the stranded state on relaunch | Environmental, not coder signal |
| Bill Splitter r2 (07-21, `20260721-111715-bd`) | PARKED-HONEST [BUILD] — target outcome class achieved | Best plan card on record (1-task grain); both waves built and merged; executability floor caught a real user-facing failure; machinery refused verified-done; coordinator drafted-nothing-acted-nothing | **The delivery seam**: page references `/src/validation.mjs`, served root doesn't expose it — logic exists, imports resolve, user gets nothing. Third instance of the class. Fix-cycle efficacy 0/1 on a serving-layer boot error |

## 5. Competence statements (the honest envelope)

**Reliably competent today** — expect it to succeed most runs, verified
honestly:

- **Python, simple apps** (single-purpose CLI, file/data processing, small
  libraries with tests): the strongest evidence class. B1/B2/B6 pass at will.
- **Python, complex-at-tested-scale** (multi-module apps, ~4–8 modules,
  dependency waves, ~1,000–2,000 lines): proven today end-to-end (B4 GREEN:
  6 modules, per-module tests, integration gates, passing exam, 80 minutes,
  unattended) — *provided the exam contract is clean (1:1)*, which the
  card-authored exam now guarantees for B4 and the advanced intake (companion
  doc) would guarantee everywhere.
- **Node utility code, simple**: B7-class passes consistently; grading depth is
  thinner than Python's.

**Conditionally competent** — builds the logic, needs a named gap closed:

- **Browser-delivered web apps**: the coder writes correct logic and passes
  integration, but *delivery to a running page* is the reliability gap (3
  measured instances of logic-exists-user-gets-nothing). The executability
  floor now catches it honestly; #1025 is the structural fix. Until then:
  expect one eyeball-and-fix pass.
- **Interactive console programs (Python)**: an intermittent testability
  ceiling (input()-driven code is hard for the coder to make testable). 07-19
  proved it clears on best-of-N variance; a scaffold rule would raise the
  floor.

**Not yet competent / not trustworthy:**

- **C#/WinUI**: "compiled" is the current verification depth (the CS0246
  leniency class). A clean report means it builds, not that it works.
- **Anything whose acceptance cannot be machine-checked** (aesthetics, feel):
  built, then honestly marked "judge for yourself" — by design, not a defect.

**Cross-cutting costs (measured):** a job run costs 1.5–3 h of exclusive
box time (the assistant is swapped out throughout); empty first attempts cost
~9 min each before the retry machinery recovers them; critique cycles run
13–15 min/round on interactive fronts.

## 6. What has never been measured (do not extrapolate)

Large or pre-existing codebases (all runs start near-empty); databases,
network services, async/concurrent systems; apps beyond ~2,000 lines or ~8
tasks; long jobs (>~3 h envelope) since the #904 trim; security-sensitive
code; sustained maintenance (edit-an-old-app) work; human-UX quality beyond
the design-critique's advisory pass. Per-card n remains small; single-run
results (including today's records) are read as points, not trends.

## 7. The differentiator worth protecting

Across every failure in this record, the machinery **told the truth**: open
tickets stayed open, parks were honest, a broken exam was eventually charged
to the exam and not the coder, and the one false-GREEN pressure path measured
(guest-oracle divergence) triggers a red-alert banner. The reliability of the
*claim* currently exceeds the raw capability — the right foundation to build
capability on.

## 8. Ranked levers (by measured leverage)

1. **Specification/contract quality** — proven decisive twice this week
   (#1008 exam repair removed B4's defect expression; the c.2299 predictor).
   → the advanced intake (companion doc).
2. **Delivery-floor checks for web targets** (#1025) — converts the web class
   from conditional to reliable.
3. **Budget coherence for multi-wave jobs** (#927/#790 chain) — unlocks B5/B3
   class measurement.
4. **Scaffold-fit + interactive-I/O rules** (#886, ledger 07-18) — removes the
   two known scaffold-origin failure modes.
5. **#989 scope ceiling + plan-time coverage check** — the guardrail for every
   card whose contract is *not* clean. Run-2 status: **[UPDATED 2026-07-21
   ~20:4x — see #989 c.2349 chain and the run-2 ledger row for the verdict;
   waves 1–4 passed in-contract at authoring time, ceiling verified in the
   root task's production prompt.]**
6. **[PROPOSED] Wire the existing #746 docset substrate into the coder
   path** — the corpus, index, lookup, and a purpose-built plan-grounding
   renderer all exist (`shared/research/`) and nothing in the coder path
   consumes them. A wiring task, not a build. See §9(d).

## 9. Why a harness cannot decompose *everything* — and what it can

This section records the capability-boundary discussion of 2026-07-21 evening,
grounded against the measured record and the front-path source read at commit
`efb7f17e`. It exists so future planning starts from an honest claim instead of
either optimism ("just decompose harder") or pessimism ("a 30-billion-parameter
local model can't build real software").

### (a) The harness is the bigger lever — already proven

Everything that improved this month improved with **no model change**:

- B4's first GREEN in recorded history (2026-07-21) came from repairing the
  exam contract (#1008) and the instrument (#1001), not from a better coder.
- Retry-until-verified converts *reliability* into *wall-clock*: empty first
  attempts cost ~9 minutes each and are then recovered by the clean-workspace
  retry machinery (§4, Blair's Lab row) — a per-attempt success rate becomes a
  near-certain eventual success, paid for in time, which the overnight window
  supplies for free.
- The 2026-07-19 interactive-input clearance showed the same shape: a
  capability that failed intermittently cleared on best-of-N variance — more
  attempts, same model.

The corollary is NOT "the harness can deliver anything given enough time."
Three walls do not fall to retries.

### (b) The three walls

**Wall 1 — correct decomposition presupposes whole-system understanding, and
wrong plans fail QUIETLY.** A plan is itself an output of a bounded model. When
it is wrong, nothing crashes: the tasks build, the gates pass, and the defect
is that the *shape* of the work was wrong. Measured instances: the first Bill
Splitter front (run `20260715-081634-bd`) planned a multi-task decomposition
for what the 2026-07-21 re-front proved is a one-task job (its 1-task plan
card is the best on record); the scaffold-fit defect (#886) seeded a
server-and-fetch skeleton onto a "one file, no build step" ask and the
machinery never questioned it; the check-realism class (quality-ledger
dimension 2) is a plan *manufacturing* verifiability it cannot deliver. Every
one of these passed its own checks. Retries do not help, because the retry
criterion is the plan's own wrong exam.

**Wall 2 — verification is the binding constraint, not generation.** The coder
generated working modules for seven consecutive B4 nights while the *exam* was
broken (the oracle imported a module it never declared — #1008): the constraint
on measured capability was the checker, not the builder. The general form is
the who-checks-the-checker gap (#1015): every mechanical gate is itself an
artifact that can be wrong, and a wrong gate converts real capability into
false failure (B4) or real failure into false success (the guest-oracle
divergence class, §7). Capability grows only as fast as trustworthy
verification grows.

**Wall 3 — coordination information outgrows bounded contexts.** Each task
builds in isolation with a context pack — a hard-capped ~1,200-character
interface card (`shared/fleet/context_pack.py:42`) carrying its dependencies'
declared contracts and as-built file lists and signatures, nothing more. That
cap is a feature at the tested scale (an over-stuffed prompt degrades a small
coder) and a wall at larger scale: as a job grows, the information a task
needs about the REST of the system grows past what any bounded card can carry,
and no amount of retrying a single task recovers knowledge the pack never
contained. The battery's evidence base tops out at ~8 tasks and ~2,000 lines
(§6) — beyond that, coordination, not generation, is the untested variable.

### (c) The honest claim

What the system can reliably deliver is the intersection of three properties:

1. **Specifiable precisely** — the ask can be pinned to named artifacts,
   behaviors, and acceptance criteria (the §8 lever-1 evidence: contract
   quality predicts build quality across all 8 cards).
2. **Mechanically verifiable at every seam** — each piece AND the integrated
   whole can be checked by a runnable exam whose own correctness is protected
   (card-authored exams, guest clean-room agreement).
3. **Decomposable into bounded pieces whose coordination fits the model** —
   the task graph's interface cards stay within what a small coder can hold.

That is a LARGE class: it covers, today, multi-module Python applications to
~2,000 lines with per-module tests and integration gates, and the walls it
excludes are named, not vague — aesthetics and feel (fails property 2,
honestly marked judge-for-yourself), novel whole-system architecture (fails
property 1 — specifying it precisely IS the unsolved work), and
beyond-tested-scale coordination (fails property 3, §6). The advanced intake
(companion document) attacks property 1 directly; #1025 attacks property 2
for web delivery; property 3 is bounded by model scale and is the one wall
this harness rides rather than removes (as local models improve, the same
machinery carries bigger pieces — the envelope policy in
`shared/fleet/decompose.py:40-63`).

### (d) [PROPOSED] The unwired lever: local corpora exist on both sides of the gap — nothing connects them to the coder

*(Correction record: an earlier draft of this subsection claimed no local
knowledge corpus exists. The LA challenged that on 2026-07-21 evening and he
was right — it was wrong twice over. Re-verified on disk at `efb7f17e`;
everything below is what the source actually shows.)*

**What exists, verified:**

1. **The assistant's knowledge corpus** — the UC-002/003 operator-ingested,
   approval-gated, born-encrypted knowledge bank
   (`services/assistant_orchestrator/config/default.toml:155-181`), with its
   embedding retrieval hosted on the NPU (neural processing unit)
   (`default.toml:136-153`), serving the ASSISTANT's conversational
   retrieval tools. It holds the operator's ingested personal knowledge, not
   API (application programming interface) references.
2. **A developer-documentation corpus AND its full retrieval stack** — the
   #746 research substrate, slice 1 (`shared/research/`): an LA-approved,
   SHA-256-pinned docset corpus staged at `models/docsets/` (Python 3.11
   official docs, pytest, Hypothesis, MDN/JavaScript, Node — manifest at
   `docs/research/docset-manifest-2026-07.json`, approval line "LA-approved
   2026-07-05"), a self-contained SQLite index built from it
   (`docset_index.py` — zero network input/output, locked by the repo-wide
   egress scan), exact-symbol plus BM25 text lookup (`lookup.py` —
   deterministic, standard-library SQLite on the CPU, so it contends with
   neither the GPU coder nor the NPU), and a purpose-built plan-time
   grounding renderer (`plan_grounding.ground_goal` — a ≤1,200-character
   block deliberately mirroring the context-pack cap).

**What remains true (the actual gap):** the CODER path consumes neither.
Nothing outside `shared/research/` and its own tests imports the substrate,
and `plan_grounding.py:24-29` names its own integration seam and stops short
of it by design: "the integration point is `shared/fleet/decompose.py` …
Nothing imports this module yet; wiring it is the integrator's explicit,
reviewable step." Independently checked from the fleet side: a grep of
`shared/fleet/*.py` for knowledge/retrieval/corpus/embedding terms returns
only incidental English in comments, and a coder task's production prompt
contains exactly: task instruction + exam contract + module interface +
as-built dependency pack + the #989 scope ceiling
(`shared/fleet/swap_driver.py:1970-2029`). No documentation excerpt has ever
ridden one. The context pack itself is structurally incapable of carrying
reference prose (`shared/fleet/context_pack.py:1-34` — contract plus paths
and signatures only).

**The lever, restated (smaller than a build — a wiring task plus one
staging knob):**

1. **Wire the existing substrate in** — first at the seam its own docstring
   names (plan-time grounding into `decompose_request`, so the 14B plans
   against real API names instead of recalled approximations), then, as a
   separate increment, at task-compose time in the swap driver (a bounded
   grounding block beside the context pack, so each coder task gets the
   reference knowledge relevant to ITS slice — the Wall-3 supply side).
2. **Corpus breadth is a staging decision, not a build** — adding a docset
   is a manifest extension + re-stage + index rebuild, operator-approved by
   construction (the manifest carries the approval line). Curated exemplars
   (house-idiom examples) would be a new corpus CLASS worth its own staging
   decision; API references are already covered.
3. **Out of scope unless separately proposed:** feeding the assistant's
   personal-knowledge corpus (item 1 above) into coder prompts. Nothing in
   this analysis calls for it.

**Design consideration to carry (flagged, not decided):** a documentation
excerpt entering a coder prompt is third-party TEXT gaining prompt presence.
The context pack's S2 posture is deliberately stricter (paths and signatures
only — no prose from any built file may ride a prompt), while a grounding
block carries excerpts by design. The #746 corpus is hash-pinned and
LA-approved, which settles integrity and provenance — but "approved for
indexing" and "approved to ride model prompts" are different claims, and the
wiring design must make the second one explicit (block provenance-tagged,
capped, instruction-inert per the standing validate-before-trust principle).
Retrieval into coder prompts crosses no NEW trust boundary only if that
approval is made explicit, not assumed.

## Evidence pointers

Run dirs under `agentic-setup/state/fleet-runs/`; scorecards under
`agentic-setup/state/battery/`; archived sandboxes under
`.../battery/<stamp>/repos-archived/`; graded rows in
`docs/quality/dispatch-quality-ledger.md`; the #989 analysis chain in ticket
#989 c.2283/c.2299/c.2304/c.2333/c.2344–c.2349; the exam-repair arc #1008;
end-to-end records #877 c.1902–c.2341.
