# ADR-037 — The Grading & Integration Machinery (a governed subsystem)

**Status:** ACCEPTED 2026-07-11 (LA-authored mandate — "really mature the grading and integration
machinery… thorough, proactive, mature not minimal," in-chat 2026-07-11; reviewed at the QUALITY-program
readback; whole-document ratified by the LA in-chat 2026-07-11, "I approve of the ADR-037 document,"
#825 c.1759). The §Decision-3 tampering-downgrade verdict authority (#832) was ratified ahead of the
whole (verbatim at c.1733, quoted below); §Decision-10's model-conditioning determinism collision stays a
separate open decision pending #835-A1 data. This ADR does not change any
live behavior; it makes the accreted machinery a *designed, governed* thing and records the doctrine every
QUALITY-program builder (#819–#837) must build against.
**Deciders:** Lead Architect (blarai); Orchestrator (facilitation).
**Builds on:** ADR-035 (the Acceptance Layer — criteria tiers build/behavior/smoke/visual/human; "never
rubber-stamp an unrun check"; honest ecosystem coverage), ADR-034 (the model-swap driver — the detached,
NEVER-ZERO teardown host the gates run under), ADR-033 §Am.3 (dispatch asset generation), and the
agentic-setup fleet gate (`verify-project.ps1` + the per-task best-of-N mechanic).
**Relates to:** Vikunja **#825** (this ADR) inside the QUALITY program **#819–#837**; the two founding
incidents — the **B5** design-review misclassification (#772, lesson 222) and the **B2** leniency drift
(#837 seed audit); the b5class verdict work (#740 c.1710/c.1717) live in `compute_job_verdict` /
`compute_flat_verdict`; lesson **221** (the window/budget-pair composition discipline); lesson **222**
(positive controls). **Grounded in six design dossiers** (`docs/handoffs/*-20260711.md`:
`failure-taxonomy`, `research-external-grading`, `research-oracle-adequacy`, `research-grading-adversarial`,
`research-green-audit`, `research-model-profiles`) — these are **citations, not the decision**; the ADR
records what the project decides, the dossiers record the evidence and the field survey behind it.

## Context

BlarAI's headless-coding dispatch (ADR-034/035, live since 2026-06-30) turns an operator's natural-language
goal into merged, graded code with **zero human interventions per job**. The thing standing between "the
coder merged something" and "the operator can trust it" is a *grading and integration machinery* — a ladder
of gates that decides one of four verdicts and refuses to bank an unearned win. That machinery grew as
accreted scripts across #690/#744/#748/#757/#758/#740: correct in the parts, never written down as a whole.
The project's standing rule is that **locked architecture earns an ADR**; two overnight battery runs
(2026-07-09, 2026-07-11) and a dedicated six-dossier research pass made the machinery legible enough — and
important enough — to govern.

The headline from those two nights is worth stating plainly, because it frames every decision below:
**the honesty layer is holding — FALSE-DONE = 0 and interventions = 0 both nights — and what is leaking is
capability, concentrated in the grading-and-integration machinery itself, not in the coder model and not in
false confidence** (`failure-taxonomy-20260711.md`). Jobs that should be GREEN park honestly because the
*oracle* is wrong, or the *import contract* between merged tasks drifts, or the *web verifier* is blind to
runtime state. So this ADR governs a subsystem that is already **honest** and must now become **more
capable and self-auditing** without ever trading the honesty away.

Two design pressures shape the whole subsystem and recur in every decision:

- **The grader is a 14B and the coder is a 30B-A3B, on one box** (LA "Small-Model Consciousness" principle,
  #740 c.1721). A lone small model is a *noisy judge*, so the machinery is **deterministic-first**: model
  judgment is admitted only in narrow, rubric-scored, ensembled, grammar-constrained forms, and never in the
  honesty-critical path. The compensating strength — free local iteration — is exploited deliberately: the
  subsystem prefers *more cheap narrow attempts* (retries, best-of-N, extra deterministic passes) over
  *fewer clever ones*.
- **No fixed grader stays valid as the coder improves** ("Verification Horizon," arXiv 2606.26300). Every
  verifier trades off **{scalability, faithfulness, robustness}** and typically achieves two of three;
  verification must **co-evolve** with capability. The subsystem therefore treats grading quality as a
  *measured, standing* concern (the #827 trend, the #837 leniency review), not a one-time build.

## Decision

The grading & integration machinery is adopted as a **governed subsystem** with the constitution, gate
ladder, verdict semantics, oracle lifecycle, and honesty invariants recorded below. Everything here is
**doctrine a builder must not silently drift from**; a change to any of it is an ADR amendment, not a
refactor.

### 1. The honesty invariants — the subsystem's constitution

FALSE-DONE = 0 is the **measured** state today; this ADR makes it the **contract**. The invariants, numbered
so a future session can cite them:

1. **Done means graded-green, never claimed-green.** A job reports GREEN **only** when its job oracle
   `passed`; an unrun or red oracle can never be GREEN, and **flat mode (a <2-task decompose that runs no
   job oracle) can never be GREEN by construction** (`compute_job_verdict` / `compute_flat_verdict`).
2. **FALSE-DONE = 0 is enforced, not hoped.** The runner cross-check rewrites GREEN→FALSE-DONE whenever a
   GREEN carries `oracle_status != "passed"` or rides a negative-catch rig (`battery.cross_check`).
3. **Degraded instruments never upgrade a verdict** — the *ok-flag class*. `ok=None` means *could-not-run*
   and is recorded honestly as UNVERIFIED, never an implied pass (`real_run_wave_gate`); an unknown
   design-review token is ignored (fail-conservative); the guest-oracle certificate is *advisory, never a
   gate*. An honest not-run always beats a lying green.
4. **A GREEN names its coverage.** A GREEN asserts only the objective (behavior/smoke) criteria the oracle
   actually checked; any uncovered objective criterion is disclosed (`oracle_coverage: k/n`, uncovered ids
   listed) and the verdict renders as `GREEN (partial-coverage: cX ungraded)`, never a bare GREEN
   (`research-oracle-adequacy-20260711.md` §5). *(PLANNED — #826/#832; the measured baseline is 4/6, §6.)*
5. **GREEN quality is advisory-only.** A quality band never changes a verdict — the scorecard schema
   hard-codes `GREEN → attribution: ""` and closes the verdict enum, so a band *physically cannot* be
   expressed as one; it lives only under the open `evidence` object. Deterministic signals rank **above**
   model judgment because the judge is small (`research-green-audit-20260711.md`).
6. **The one sanctioned verdict-authority extension is deterministic and integrity-only** — the §Decision-3
   tampering-downgrade (#832). No model ever changes a verdict.
7. **The grader is audited, not trusted.** Both directions of grader error are measured: *well-posedness*
   (the oracle must not reject valid work) and *discrimination* (the oracle must actually reject invalid
   work). FALSE-DONE = 0 audits the *claim*; the discrimination gates audit the *grader* (§Decision-5).
8. **Mid-run oracle repair toward passing is forbidden** (§Decision-4). Relaxing the grader to pass the
   work in front of it is the FALSE-DONE hazard in its most seductive form.
9. **No model in the honesty-critical path.** No model judges whether a model cheated; every honesty-load
   -bearing decision is a deterministic AST/regex/exit-code check. Model judgment is confined to *advisory*
   surfaces (the GREEN-quality jury) that the schema forbids from gating.
10. **Abstention and UNCLASSIFIED are first-class honest outputs.** A jury that disagrees abstains
    (`uncertain`, never a guessed middling pass); a failure the classifier cannot place is UNCLASSIFIED
    residue, and a rising UNCLASSIFIED rate is the instrument's own health alarm — surfaced, never silenced.

### 2. The gate ladder

Every gate the fleet runs, each with what it **PROVES**, what it structurally **CANNOT prove**, its
**failure semantics** (park / stall / fix-cycle), its **(window, budget)** pair, and its position in the
**2-of-3 {scalability, faithfulness, robustness}** frame. Definitions, stated once: *scalability* = runs
cheaply at nightly volume on one box, no model-in-the-loop, no farm; *faithfulness* = a pass corresponds to
the goal actually being met; *robustness* = the verdict resists gaming, noise, and drift. The
**(window, budget)** discipline is **lesson 221**: a watchdog *window* must be provably longer than the
longest legitimately-silent phase it observes, or that phase must heartbeat — audit the pair as a unit
whenever either moves. Each gate's mandatory **small-model-fit** note lives in §Decision-7. Build status is
LIVE / STAGED / PLANNED as of authoring (the full split is §Decision-11).

The ladder runs bottom-to-top per task, then per wave, then once on the integrated whole:

| # | Gate | Proves | Cannot prove | Failure semantics | (window, budget) | 2-of-3 | Status |
|---|------|--------|--------------|-------------------|------------------|--------|--------|
| G1 | **Per-task build/test gate** (fleet `verify-project.ps1` + `pytest`/`npm test`, per worktree) | the changed task compiles and its own tests pass | that the *integrated whole* works; that the task's tests are adequate | **fix-cycle** — bounded reflections, then the task PARKS (BUILD) | idle circuit-breaker **240 s**; per-task ceiling **14400 s** (#757) | scalability + robustness | LIVE |
| G2 | **Static pre-gate** (`ruff --select F` / `node --check`) — fail-fast before the expensive spend | no undefined names / syntax errors reach grading | anything behavioral | **fix-cycle**, fail-soft if the tool is absent | rides G1's budget | scalability + robustness | PLANNED (#831) |
| G3 | **Wave integration gate** (`real_run_wave_gate` — full `verify` + full `pytest -x`/`npm test` on the **integrated main**) | no cross-module regression across everything merged so far (the field's PASS_TO_PASS discipline) | correctness on inputs the suite never tries; a coder-owned exec environment (conftest/ini) is trusted | `ok=False` → wave **fails** → job PARKS (BUILD); `ok=None` → honest UNVERIFIED | verify **660 s** / tests **600 s** | scalability + faithfulness | LIVE |
| G4 | **Import-contract / layout enforcement** (one canonical layout; symbol-level probe: `getattr` each contract export, assert `__file__` under the plan path, clean-env recipe) | the oracle's imports resolve to the promised modules/callables at the promised paths | that a resolvable symbol behaves | **fix-cycle** on drift, else PARKS (the B6/B7 seam) | rides the wave budget | scalability + robustness | PLANNED (#822) |
| G5 | **Behavior smoke / runtime-error channel** (web design-verify: protocol-layer console/`pageerror` read + a positive DOM-delta smoke) | the assembled web app *does the thing* and throws no runtime error; flags literal `undefined`/`NaN` in rendered text | look-and-feel quality (the operator's eyeball owns that) | fix-cycle inside the design loop; honest not-run on capture failure | design-loop iterations bounded (cap) | faithfulness + robustness | PLANNED (#823) |
| G6 | **Wave-final executability floor** (language-agnostic "the composed system boots" — import the declared entrypoint + `--help`/no-op) | the integrated app *starts* (gives Node/.NET a behavioral floor they lack) | that it computes correctly | fail-soft to honest `executability: not-run` when no entrypoint is declared | rides the wave budget | scalability + faithfulness | PLANNED (#830) |
| G7 | **Wave-final job oracle** (`real_run_job_oracle` — spec-blind, cross-model, authored **before** any implementation, seeded protected #748, **restore-before-grade** so plan bytes always win) | the integrated whole satisfies the objective (behavior/smoke) criteria the oracle asserts | the criteria it **didn't** assert (coverage); whether it discriminates a subtly-wrong impl; a conftest-gamed execution environment | `passed`→feeds GREEN; `failed`→PARK (BUILD); machinery failure→honest `not-run`→STALLED (VERIFY) | grade **600 s** (runner-pinned `pytest==9.1.1`/`hypothesis==6.155.7`) | scalability + robustness *(faithfulness bounded — §Decision-5/6)* | LIVE |
| G8 | **Oracle QA** (well-posedness — collectable, spec-valid strategies, no interactive-IO, no invented contracts; the non-vacuity floor; regenerate-exhausted as a tallied class) | the oracle is **well-posed** — it won't reject valid work for a defect of its own | that the oracle is **adequate** (that is G9/G10) | validated at **plan time**, before the coder exists → bounded regenerate (2), then honest `not-run` | plan-time, off the run's critical path | scalability + faithfulness | PLANNED (#821) |
| G9 | **Oracle discrimination + adequacy** (the FAIL-TO-PASS baseline: assert every acceptance test **fails on the empty skeleton**; the criterion→assertion coverage matrix; bounded offline deterministic-operator mutation) | the oracle actually **rejects** invalid work; every objective criterion traces to a real assertion | absolute completeness (mutation is bounded/sampled) | vacuous assertion → `oracle_defect` → regenerate; survivor → advisory `covered-weak`; uncoverable → `oracle_coverage: partial` (never blocks) | offline / GREEN-only pass | faithfulness + robustness | PLANNED (#821/#826/#828) |
| G10 | **Flake differential** (one hermetic re-run in a clean sub-env on a *parking* failure) | a verdict flip means the **grader** is flaky, not the coder wrong | anything about correctness | flip → `NON_DETERMINISTIC` → routes as oracle/harness defect, not a coder park | one extra grade run | scalability + robustness | PLANNED (#829) |
| G11 | **Guest-oracle certificate** (#744 — the same oracle re-run in a NIC-less Alpine guest; agreement matrix: `agree` / `DIVERGENCE`) | substrate/network-independent corroboration of the host oracle verdict | env-independence (it snapshots the *same* tree incl. any coder conftest — §Decision-5) | **advisory** — `DIVERGENCE` is the datum; the certificate is evidence, never a gate | service-readiness wait **90 s** (#744) inside the **10800 s** run budget | faithfulness + robustness | STAGED (built; live-verify 2026-07-11) |
| G12 | **FALSE-DONE cross-check** (`battery.cross_check` — the meta-gate) | no GREEN banks while its oracle isn't `passed` or while it carries a rig | that a `passed` oracle is *adequate* or *un-gamed* (it audits the claim, not the goal) | GREEN + bad oracle_status/rig → **rewrite to FALSE-DONE (VERIFY)**; else pass-through | trivial (two-property check) | scalability + robustness | LIVE |
| G13 | **Earned-GREEN audit** (#832 — deterministic AST/regex tampering-fingerprint scan + coverage disclosure, before a GREEN is accepted) | a GREEN's winning tree carries **no grader-tampering fingerprint**; discloses `oracle_coverage` | craft quality (that is G15) | tampering match → **downgrade GREEN→PARKED-HONEST**, quoting file:line (§Decision-3) | close-of-battery pass | scalability + robustness | PLANNED (#832) |
| G14 | **Standing failure classifier** (#827 — deterministic taxonomy at battery close; ORACLE-DEFECT / INTEGRATION-SEAM / BLIND-FIX-LOOP / DECOMPOSE-DOWNGRADE / HARNESS / UNCLASSIFIED) | night-over-night *where quality is lost*; surfaces new leak classes as UNCLASSIFIED | nothing about a single verdict (advisory) | **never** changes a verdict/attribution; UNCLASSIFIED-rate is its health metric | close-of-battery pass | scalability + faithfulness | PLANNED (#827) |
| G15 | **GREEN-quality audit** (#837 — deterministic archetype-regression floor + craft lints, then a diverse-jury rubric scorer; the operator "what you got" card) | leniency drift (fragile / regressed / unrunnable / unusable GREENs) | correctness the oracle already owns | **advisory band only** — never gates; an archetype regression forces a Layer-2 pass | close-of-battery; jury within one 14B swap | scalability + faithfulness *(robustness bounded — juror noise → calibration)* | PLANNED (#837) |
| G16 | **Reap / settle guard** (the swap driver's NEVER-ZERO teardown + the out-of-band budget watchdog + the #817 fail-loud Hyper-V sentinel + the fleet-aware port-5001 leak detector) | the run was **valid** — it ran, settled, and freed the box; nothing stranded, no live peer killed | that the work is right (it is a run-validity gate, not a correctness gate) | wedge → tree-kill the child → STALLED (HARNESS); a leaked AO → fail-loud | doom window **240 s**, composed *under* the 600 s verify/oracle budgets (lesson 221); run budget **10800 s**; ceiling **14400 s** | scalability + robustness | LIVE |

Reading the ladder: the lower gates (G1–G3) are **scalable + robust** and sacrifice **faithfulness** (a
per-task or per-suite pass is not the goal met) — restored upward by G6/G7. The job oracle (G7) is the one
gate that reaches for all three, and *precisely because it does*, its residual gap — **faithfulness that is
asserted, not proven** (partial coverage, no discrimination baseline) — is the subsystem's top-severity
hazard. That gap is the Verification-Horizon "no silver bullet" point in miniature, and it is exactly what
the discrimination dual (§Decision-5, G8–G10) and the coverage rule (§Decision-6) exist to close. The
meta-gates (G12–G16) each cleanly sacrifice one axis and name the ticket that restores it.

### 3. Verdict taxonomy doctrine

Four verdicts, computed purely from evidence (`compute_job_verdict` / `compute_flat_verdict`). This codifies
the b5class ruling as doctrine:

- **GREEN — machine-verified done.** Requires ALL of: not cancelled/stopped, every task `merged`, no failed
  wave gate, and the job oracle `passed`. GREEN is the *only* verdict that asserts the work is done, and it
  is never minted from anything short of a passed oracle. Its `attribution` is empty by schema.
- **PARKED-HONEST — a valid run that fell short; it BANKS.** A verification *success*: the run ran validly
  and produced an honest, measured outcome below GREEN — work parked/blocked, a gate or oracle **failed on
  built code** (BUILD), the operator cancelled (HARNESS), or the VLM design review **ended in a measured
  outcome** on an otherwise-valid tree (cap-reached = bar measured-and-missed, or clean = reviewer satisfied;
  VERIFY — #740 c.1710/c.1717). A PARKED-HONEST run is a *good night's data*: it banks toward the campaign,
  it is the operator's eyeball/park queue, and it is never a failure of the machinery.
- **STALLED — the run itself was invalid; it BLOCKS.** The measurements are not trustworthy: the budget
  watchdog fired, the run died mid-task or never started (HARNESS), or **everything merged but the oracle
  never ran** — *merged-but-unverifiable is exactly the FALSE-DONE class*, so it must never be GREEN and is
  honestly STALLED (VERIFY: the oracle was missing, not the build). Flat mode's all-merged run is the
  canonical STALLED (no oracle to prove the whole). STALLED does not bank — an invalid measurement is not
  data.
- **FALSE-DONE — a claimed-done that wasn't; it rewrites GREEN only.** The runner cross-check
  (`battery.cross_check`) rewrites **GREEN→FALSE-DONE** when a GREEN carries `oracle_status != "passed"` or
  rides a negative-catch rig (B8). It never touches a non-GREEN verdict. FALSE-DONE = 0 is the subsystem's
  headline honesty metric.

**Fail-conservative rules, load-bearing:**

- The **ok-flag class** (invariant 3): a degraded instrument never upgrades a verdict. `ok=None`
  (could-not-run) is UNVERIFIED, not a pass; an unknown `design_review_ending` token is ignored; the design
  -review signal can *never mint GREEN and never demotes one* — it only reclasses *within* non-GREEN. The
  guest certificate is advisory-only.
- The **design-review reclass** (b5class / #740) moves a merged-but-unverifiable run from STALLED to
  PARKED-HONEST **only** when a real critique measured the design bar — a valid run's measured outcome banks
  instead of burning as run-invalid, while STALLED stays reserved for harness/run-invalid classes (budget
  kills, crashes, wedges) which the signal never touches.

**The one sanctioned verdict-authority extension — the tampering-downgrade (#832), LA-ratified.** A
deterministic scan may **downgrade a GREEN to PARKED-HONEST** when the winning tree carries
grader-tampering fingerprints. This is the *only* place anything other than the pure evidence-driven
computation may move a verdict, and it moves it *conservatively* (GREEN→PARKED, never the reverse). The LA
approval, verbatim (2026-07-11, #832 c.1733):

> "I approve of your action: downgrade a GREEN to PARKED-HONEST when the winning tree carries grader-tampering
> fingerprints — a coder-authored conftest hooking the test runner, hardcoded oracle answers, and similar
> shapes. a tampering fingerprint is integrity evidence rather than a quality opinion, and the downgrade
> fails conservative. Every match quotes file and line so it's human-adjudicable in seconds."

The boundary is exact and permanent: a **tampering fingerprint is integrity evidence**, deterministic and
quotable to file:line; it is *not* a quality opinion. A **quality band is a quality opinion** and stays
advisory forever (§Decision-7). No model ever exercises this authority. Any future move to let a *quality*
band gate is a separate LA decision, escalated with a recommendation — never adopted silently.

### 4. Oracle lifecycle — and the mid-run-repair rejection

The job oracle's life, authorship → validation → seeding → grading → evidence:

1. **Authorship (model, from spec).** The 14B writes the job-level, **spec-blind** oracle from the goal
   criteria *before any implementation exists* (`generate_job_acceptance_oracle`), fail-closed to `("","")`
   (honest `not-run`) when there is no python/node target, no behavior/smoke criteria, or no declared
   contract to import (a guessed oracle fails every job and teaches nothing).
2. **Validation (#821 classes).** Before seeding, deterministic passes check the oracle is well-posed
   (collectable, spec-valid Hypothesis strategies, no interactive-IO-under-pytest, imports ⊆ declared
   contract, non-vacuity floor) **and** — the dual — that it *discriminates* (fails on the empty skeleton;
   every objective criterion traces to an assertion). *(PLANNED — G8–G10.)*
3. **Seeding (protected).** The validated oracle is committed guard-wrapped into the target repo before
   wave 1 (#748), so every best-of-N worktree **codes toward** the same protected spec — but the seeded copy
   is inert in per-task/wave gates (a module-level `pytest.skip` for python; a hoisting-proof `node:test`
   skip with the body line-commented for node).
4. **Grading (restore-before-grade).** At the final integrated tree, the **plan-carried bytes are written
   over whatever is on disk** and graded (`real_run_job_oracle`), then the tree is restored. The oracle
   bytes are captured into the driver's in-memory closure at startup, *before the coder runs* — so a merged
   edit to the seeded oracle, or a rewrite of the swap-state, cannot change what the grader executes ("plan
   bytes ALWAYS win"). This is a genuinely strong protection and is kept.
5. **Evidence.** The verdict carries `oracle_status` (passed/failed/not-run), the coverage stamp
   (`oracle_coverage: k/n`, §Decision-6), the guest agreement (agree/DIVERGENCE), and — for a non-GREEN —
   the failure class (#827). Every machinery failure is an honest `not-run`, never an implied pass.

**Explicit REJECTION — mid-run oracle repair toward passing.** When the grader fails the work in front of
it, the machinery **must not** relax the oracle to make it pass. This is the FALSE-DONE hazard in its most
seductive form: the oracle is the one thing whose *own* correctness the honesty layer cannot cross-check
(FALSE-DONE=0 compares the oracle's claim to the oracle's result — both blind to the criterion it never
asserted). The only sanctioned repair is **pre-seed regeneration of defect classes** — an oracle that fails
*its own* validation (collection error, ill-posed strategy, invented contract, uncovered criterion) is
regenerated, bounded, with the exact defect named, **before** it is seeded and before any grading happens.
Repair is: *pre-seed only, defect-classes only, never semantic relaxation, never after the coder's work is
in hand.* A future session must not drift across this line — writing it down is the control.

### 5. The well-posedness / discrimination duality

The subsystem's organizing duality (`research-external-grading-20260711.md` §0;
`research-oracle-adequacy-20260711.md`):

- **WELL-POSEDNESS** — the oracle must **not reject valid work**. This is the top *frequency* lever from our
  own data (~3–4 parks/night are ill-posed oracles), and it is where the program is already aimed
  (#821/#826, and #829's fail-to-pass baseline as its amendment).
- **DISCRIMINATION** — the oracle must **actually reject invalid work**. This is the *severity* lever: a
  vacuous oracle banks a false GREEN as silently as an ill-posed one parks a valid one, and it is the **one
  class FALSE-DONE=0 structurally cannot catch, because the oracle itself is the thing lying.** The field
  named it in 2026 — AgentLens's "**Lucky Pass Problem**" (arXiv 2605.12925) — and formalized the fix —
  Nexus execution-grounding (arXiv 2510.26423). Our checks: the fail-to-pass baseline (#829), the mutation
  score (#828), the executability floor (#830).

The honest statement the duality forces: **FALSE-DONE = 0 protects neither axis — it audits the CLAIM; the
duality's gates audit the GRADER.** The exposure of the discrimination gap *grows exactly as well-posedness
succeeds*: every validity fix that converts a park into a green enlarges the set of greens whose coverage
and discrimination nobody checked. So the discrimination dual is not optional hardening — it is structural,
and it sequences *after* the well-posedness gates land (it reuses their oracle-QA module and contract AST).

### 6. The false-completeness rule — a GREEN names its coverage

Measured on both battery nights: **both banked GREENs (B2 text-stats) graded 4 of 6 test-tier criteria** —
real wins, partially verified, previously *silent about it* (`research-oracle-adequacy-20260711.md` §1). The
concrete hole: B2's smoke criterion c7 ("must not crash on empty or invalid input") had **zero** oracle
coverage, yet the operator-facing report printed "[verified]" for it, because `criterion_status` maps a
whole-suite pass to per-criterion VERIFIED (`acceptance.py`). The anti-rubber-stamp report rubber-stamped
the one criterion nothing asserted.

The rule: **a GREEN is only as verified as its oracle's coverage, and the subsystem never implies more.**
Every job stamps `oracle_coverage: k/n` into its evidence; a partial-coverage GREEN renders as
`GREEN (partial-coverage: c7 ungraded)`, never a bare GREEN; full coverage stamps `oracle_coverage: full`.
The enforcement is a **grammar-declared, AST-verified traceability matrix** — the oracle emits a
`criterion_id → [test]` map whose schema `required` keys are exactly the objective criterion ids (the model
*cannot forget a key it must emit*), and a deterministic AST pass verifies each declared test really
exercises the criterion's contract surface. This is the **mirror image of #826** (oracle→spec soundness):
together they are a bidirectional matrix — #826 says "the oracle demands nothing the spec didn't ask,"
adequacy says "the oracle checks everything the spec did ask." Full coverage is the target; honest
partial-stamping is the floor. Coverage joins the standing trend (#827). *(PLANNED — #826/#832; measured
baseline 4/6.)*

### 7. The GREEN-quality doctrine — advisory forever, deterministic-first

Grader error has a second direction the whole prior program ignored: **leniency** — work that banks GREEN
but is fragile, ugly, unmaintainable, or unusable by a non-technical operator who cannot read code
(`research-green-audit-20260711.md`). Its founding evidence is the **B2 leniency drift** — the *same* job
banked GREEN seven nights running while its tokenizer quality **degraded monotonically**: the 07-07 GREEN
handled `"don't"` / `"well-known"` intact, the 07-11 GREEN *silently drops them*, and all three scored an
identical unqualified GREEN because the oracle's one sample contains no apostrophe or hyphen. This is the
**second founding incident of the subsystem, beside the B5 design-review misclassification** — B5 proved
the machinery could convict a working app (false red, lesson 222); B2 proves it can bless a worsening one
(false green, drift). Both are grading-*validity* failures, opposite signs.

The doctrine:

- **GREEN quality is ADVISORY-only territory** — a band never changes a verdict, and the schema *enforces*
  it (invariant 5). A working-but-plain job is still working; turning craft into a gate would manufacture
  PARKED/FALSE-DONE noise and lean on a small-model taste-judge too noisy to gate on.
- **The deterministic Layer-1 floor ranks above model judgment** — *because the judge is small*. An
  archetype-regression probe (diff each GREEN's real-input behavior against the last archived GREEN of the
  same job) plus craft lints (dead scaffold? skeleton README? any runnable entry?) plus advisory ruff would
  *by itself* have caught the B2 drift, with zero model risk. This layer carries as much as it can before a
  model is ever consulted.
- **The only sanctioned model-judgment form is a diverse jury** — not one 14B verdict but a small jury of
  *diverse* lenses (different rubric framings / seeds / a second local model), majority-per-field, **honest
  abstention on disagreement**, compact enum rubrics, grammar-constrained emission, and a band **computed by
  a deterministic formula** over the scored fields (the model answers narrow observations; a formula renders
  the judgment). This is the literature-backed rescue of a small judge (Judge-Panel Finite-Calibration
  Regime Map, arXiv 2606.01034), and it cashes the fleet's cheap-local-iteration strength (a jury is N cheap
  overnight calls).
- **Calibration is adopted as MEASUREMENT now.** The jury is measured against the one ground truth that
  matters — the operator's own accept/reject when he tries a GREEN in his hands — reporting agreement rate /
  Spearman. Measuring the auditor is a safe adopt (it changes nothing about banking) and answers the
  reflexive question *who audits the GREEN-audit?* **Any move to give a quality band authority over banking
  is a separate LA decision, escalated with the calibrated-jury design as the recommendation — never adopted
  silently.**

### 8. Small-Model Consciousness (mandatory — every gate carries a small-model-fit note)

The subsystem is designed for a **14B planner/grader/oracle-author and a 30B-A3B coder on one box**, and is
permanently conscious of what that means (#740 c.1721). The house rules: **deterministic-first** grading
(model judgment only in narrow, rubric-scored, ensemble-checked, abstaining forms); **grammar-constrained
structured emission** wherever the model authors machinery inputs (oracles, criteria, coverage maps —
proven on this pipeline's #718/#743 emissions); **context-budget discipline** on everything surfaced to the
coder (compact + positionally stable); **single-focus fix-cycle instructions** (name one uncovered
criterion, ask for one test — never a broad critique a small model half-acts on); and the strength column —
**free local iteration favors more cheap narrow attempts** (retries, best-of-N, extra deterministic passes)
over fewer clever ones. Every gate carries a **small-model-fit** note, per LA mandate:

- **G1 per-task gate** — EXCELLENT: deterministic; and it *helps* the small coder by shortening the fix
  loop (an exact "undefined name" beats a 2am collection error).
- **G2 static pre-gate** — EXCELLENT: deterministic; cheap exact signal over cleverness.
- **G3 wave integration** — EXCELLENT: pure execution, no model in the loop.
- **G4 import-contract probe** — EXCELLENT: `getattr` + `__file__` + exit code; closes the small model's
  cheapest evasion (a stub module that merely resolves).
- **G5 behavior smoke / console** — GOOD: protocol-layer capture is *specifically* small-model-safe (the
  page's own small-model code cannot suppress a CDP event, unlike an in-page hook); the DOM-delta smoke
  catches the exact gradient reflex (cosmetic-hide) a small coder trips into.
- **G6 executability floor** — EXCELLENT: deterministic "does it boot," no judge.
- **G7 job oracle** — EXCELLENT at grade time (pure execution); the *authorship* is the small model's
  most-damaged role (greedy 14B — §Decision-10 / #834), so authorship gets grammar-forced structure +
  bounded narrow regeneration.
- **G8/G9 oracle QA + discrimination** — EXCELLENT: AST/collect/mutation are machine verdicts; the model
  only *emits* a mapping a deterministic pass then *disposes*.
- **G10 flake differential** — EXCELLENT: deterministic, and it cashes the cheap-retries strength (in a
  temperature=0 fleet a flip is near-certainly a harness bug).
- **G11 guest certificate** — GOOD: an independent deterministic re-run; no model.
- **G12 FALSE-DONE cross-check** — EXCELLENT: a two-property deterministic check.
- **G13 earned-GREEN audit** — EXCELLENT *only as an AST/regex fingerprint scan* — never an LLM reviewer
  (the one a lazy build would wrongly reach a model for; called out in #832).
- **G14 failure classifier** — EXCELLENT: deterministic taxonomy pattern-match; locked model-free so it
  cannot become a new FALSE-DONE vector.
- **G15 GREEN-quality audit** — GOOD *only in the constrained, juried form* — this lever *only exists
  because of the small-model lens* (a frontier judge wouldn't need a jury; a 14B does); open-ended 14B code
  review is the textbook anti-pattern (rejected, §Decision-10 R-model).
- **G16 reap/settle guard** — EXCELLENT: deterministic, fail-loud, identity-plus-liveness (lesson 216/221).

### 9. Co-evolution doctrine + the quarterly grading/leniency review

No fixed grader stays valid as the coder improves (Verification Horizon, arXiv 2606.26300) — so grading
quality is a **standing, measured** concern, not a one-time build. Two instruments make co-evolution real:

- **The #827 standing failure classifier is the trend instrument.** Tonight's hand-analysis becomes a
  nightly deterministic classifier at battery close, carrying per-class counts and the **night-over-night
  trend** ("oracle-defect parks: n2=3 → n3=?"). Its **UNCLASSIFIED rate is the health metric** — a rising
  rate means a new leak class the taxonomy doesn't name, surfaced loudly for a human pass. This is how the
  program's *effect* is measured and how new failure classes surface themselves.
- **The quarterly grading / leniency review** pairs with the existing `LESSONS.md` quarterly consolidation.
  It reads the accumulated `green_audit` bands + `failure_class` trends, looks for drift (the B2 three-night
  slide is the archetype), and applies **a mirror of the project's third-instance rule into grading: a craft
  or grading miss that recurs a third time promotes from an advisory finding to a deterministic Layer-1
  gate** (e.g. "scaffold placeholder must be removed" graduates from advisory lint to a hard check). This is
  how advisory findings *compound into controls* without ever gating on a model's taste — the same
  discipline that governs the lessons surface, mirrored one domain over.

### 10. Model-profile direction (#834) + the variable taxonomy

The harness today branches on task **complexity** and is essentially blind to model **architecture and
family** (`research-model-profiles-20260711.md`). The sharpest symptom: the planner/oracle-author 14B runs
**greedy** (`temperature=0, do_sample=False`), which Qwen's own model card warns against ("causes
degradation and endless repetitions") — a family-conditioned setting masquerading as the universal
"deterministic = temperature=0" standard, feeding the single most-damaged role in the battery (oracle
authorship). This ADR **records the direction, and flags the doctrine collision as an LA decision, not a
defect fix**: whether "deterministic" is redefined per-model (low-temp + fixed seed for a Qwen3-dense;
accept a routing-noise floor + canonicalize-before-diff for an MoE) edits a written CLAUDE.md standard and
is the LA's call, informed by the #835 A/B (greedy vs low-temp on our substrate).

The build is **boring by design** (#834): one `model-profiles.json` beside `fleet-driver.json`, two tables
(`models` = stable per-model attributes; `call_sites` = per-role policy overlay), **fail-soft, dormant by
default** (nothing reads it until each consumer adopts a field in its own reviewed change), plus an
anti-drift gate test asserting agreement with `opencode.json`'s overlapping fields (the
`test_winui_passthrough_allowlist` SSOT pattern). The **variable taxonomy** the machinery may branch on —
the concrete answer to "what variables are involved": `role` (the cross-cutting selector) · `arch`
(dense|moe) · `active_params` · `total_params` · `family` · `tool_call_format` · `thinking_mode` ·
`grammar_support` · `quant` · `serving_backend` (kept **separate** from `arch` though 1:1-confounded today) ·
`determinism_need_per_call_site` · `context_budget` · `cost_profile` · `resident_gb`. The dense-vs-MoE
cluster (arch/active_params/total_params/cost_profile) genuinely needs different paths — our own #769 data
shows the 14B-dense and 30B-MoE have *mirror-image* cost profiles (dense = cheap prefill / expensive decode;
MoE = the inverse) — but the exact *values* (how much wider best-of-N for an MoE, whether OVMS's
temperature-only sampling even reaches the MoE's routing-diversity upside) are **not knowable without our
own A/B** (#835), so profile-driven branches ship with fail-soft defaults and are *tuned by* measurement,
never guessed.

## Already exceeds practice (verified in live code — do not rebuild)

The honest denominator: several external "best practices" we already match or exceed, and — notably — our
core oracle architecture is a **named 2026 frontier pattern**. Recorded so future sessions don't rebuild
what exists (`research-external-grading-20260711.md` §1):

| External practice | Our equivalent (live) | Standing |
|---|---|---|
| **Contract-driven adversarial / independence-based verification** (arXiv 2605.25665) — one agent implements from a contract while a **separate** agent writes tests from the same contract *without seeing the implementation* | **Exactly our design** — the cross-model, **spec-blind** oracle the 14B authors from criteria *before* any implementation exists, seeded protected + restore-before-grade (`real_run_job_oracle`); the 30B never authors the tests that grade it | **Already exceeds** — we built the pattern a 2026 paper now names; also our anti-leakage defense (rejection R5) |
| **PASS_TO_PASS / full-suite regression guard** (SWE-bench) | `real_run_wave_gate` runs the **full** suite on the **integrated** main, not just the changed task | **Already present** (G3) — do not re-propose |
| **Commit expected behavior before acting** (Devin TDD-style pre-assertion) | the oracle is frozen from goal-criteria before the coder runs | **Already present** |
| **Bound the fix loop** (Aider `--max-reflections`) | fix-cycle caps + 240 s idle circuit-breakers + turn-caps | **Already present** (G1) |
| **Per-instance isolation** (OpenHands Docker) | per-candidate git worktrees + detached swap driver + dormant NIC-less guest-oracle VM (#744) | **Already present** (rejection R3) |

The steer: the program (#819–#837) correctly attacks *oracle well-posedness* and *integration seams*; what
the field's 2026 frontier adds — and our program was already reaching for — is the one thing FALSE-DONE=0
cannot catch: **proof that the oracle discriminates** (§Decision-5). We built the independence pattern before
the field named it; we should now close the discrimination dual it implies.

## Per-language gate-coverage matrix (a documented known-asymmetry)

Gate coverage is deliberately uneven by ecosystem, and the subsystem states it up front rather than implying
uniformity (ADR-035's honest-coverage rule; `research-green-audit-20260711.md` §2). **python > node/web >
.NET-build-only:**

| Gate | python | node / web | .NET / WinUI |
|------|--------|------------|--------------|
| Build / compile | ✅ `compileall` (syntax) | ✅ `npm run build` *if* a script | ✅ `dotnet build` |
| Behavior tests (gating) | ✅ `pytest` (blocks merge) | ✅ `npm test` *if* a script | ❌ **none — build-only** |
| Job oracle (spec-blind) | ✅ `tests/test_job_acceptance.py` | ✅ `acceptance.job.test.mjs` | ❌ |
| Property-based | ⚠️ Hypothesis if the coder wrote `@given` | ❌ no analog | ❌ |
| Mutation / adequacy | ⚠️ advisory (python-only, planned #828) | ❌ | ❌ |
| Executability floor | (planned #830) | (planned #830 — its first closer) | (planned #830) |
| Visual / design | n/a | ⚠️ VLM loop — eyeball, advisory | (WinUI eyeball) |

The asymmetry is honest, not hidden: `BEHAVIOR_GATED_ECOSYSTEMS = {python, node}` and **.NET is
build-only** — a clean .NET report means "it compiled," not "the math is right" (ADR-035). Node/web get no
mutation and no property layer; **.NET/WinUI is the weakest — build-only, no behavior ever executed** — and
desktop GUI is a natural operator ask, so it is the largest latent leniency surface. The
**executability-smoke floor (#830) is the matrix's first leveller**, and the GREEN-audit's deterministic
Layer-1 (#837) is built ecosystem-agnostic to partially close the rest. Named as a standing asymmetry so the
next capability decision weighs it.

## PLANNED-vs-BUILT honesty (as of authoring, main @ 706c6972)

Every mechanism above is marked LIVE / STAGED / PLANNED so this ADR never overclaims what runs. The split:

- **LIVE** (verified in live code at 706c6972): the per-task fleet gate (G1), the static-import posture of
  the wave gate, the **wave integration gate** (G3, `real_run_wave_gate`), the **spec-blind cross-model job
  oracle** with seed (#748) + restore-before-grade (G7, `real_run_job_oracle` / `real_seed_job_oracle`), the
  **FALSE-DONE cross-check** (G12, `battery.cross_check`), the full **verdict taxonomy** incl. the b5class
  design-review reclass (G3/G7 verdicts, `compute_job_verdict` / `compute_flat_verdict`, #740 c.1710/c.1717
  landed today), the **design loop** (VLM critic + bounded iterations), the **reap/settle guard** (G16 —
  NEVER-ZERO teardown + budget watchdog + #817 fail-loud Hyper-V sentinel landed today + the fleet-aware
  port-5001 leak detector), and the oracle-authoring path (`generate_job_acceptance_oracle`, fail-closed).
- **STAGED** (built, dormant knob, live-verify in flight): the **guest-oracle certificate** (G11, #744) —
  the executor, the agreement matrix, and the service-readiness wait are built; the knob is dormant and the
  first live in-guest proof was scheduled for the 2026-07-11 battery.
- **PLANNED** (wave A/B — ticketed, **not** in code at authoring; confirmed absent: `oracle_qa.py`,
  clean-env grading flags, `oracle_coverage`/`green_audit` fields, `model-profiles.json`): the static
  pre-gate (G2/#831), import-contract/layout enforcement + clean-env grading (G4/#822), behavior-smoke /
  console channel (G5/#823), executability floor (G6/#830), oracle QA well-posedness + non-vacuity floor
  (G8/#821), discrimination + coverage matrix + mutation (G9/#821/#826/#828), flake differential (G10/#829),
  earned-GREEN tampering audit + coverage disclosure (G13/#832), standing failure classifier (G14/#827),
  GREEN-quality audit + "what you got" card (G15/#837), and the model-profile manifest (§Decision-10/#834).

Sequencing note: the discrimination/coverage gates (G9) reuse the well-posedness module (G8) and the #826
contract AST, so they land *after* #821/#826; #827/#832's evidence-stamp shapes land *after* #821/#822 so the
new evidence fields exist to classify on.

## Consequences

- The subsystem is now **legible and governed**: a builder for any of #819–#837 has one place that says what
  each gate proves, what verdict its failure yields, and which honesty invariant it must not break. A change
  to the doctrine is an ADR amendment, not a quiet refactor.
- **The honesty contract is explicit.** FALSE-DONE = 0 is no longer a measured coincidence but a numbered
  constitution (§Decision-1); the coverage rule (§Decision-6) makes it an *honest* zero (a GREEN discloses
  what it proved); the tampering-downgrade (§Decision-3) is the single, LA-ratified, deterministic exception
  to pure evidence-driven verdicts.
- **The discrimination gap is named as the top-severity hazard** and sequenced — the one class FALSE-DONE=0
  cannot catch now has an owner (§Decision-5, G8–G10), and its exposure is understood to *grow* as
  well-posedness succeeds.
- **GREEN quality gets a standing auditor** (§Decision-7/G15) that is advisory-forever by schema, so the B2
  drift class becomes visible without ever manufacturing PARKED noise or leaning on a noisy judge to gate.
- **The machinery is designed to co-evolve** (§Decision-9): the #827 trend and the quarterly leniency review
  are the instruments that keep a small-model grader valid as the coder improves, with the third-instance
  rule mirrored into grading so advisory findings compound into deterministic gates.
- **Model-awareness is a recorded direction, not a silent behavior change** (§Decision-10): the greedy-oracle
  -author collision is surfaced to the LA (it edits a written standard) rather than "fixed," and the profile
  manifest ships dormant and measured-before-tuned.
- **Costs accepted, named:** the discrimination and adequacy gates add nightly compute (bounded, offline,
  GREEN-only) and plan-time regeneration rounds; the guest certificate spends a VM window; the GREEN-quality
  jury spends a 14B swap per GREEN. All are affordable while GREENs are rare (~1/night) and all are
  deliberately kept *off* the coder's critical path.

## Rejected alternatives (on the record — rejections are governance value)

Grading practices the subsystem **explicitly rejects**, each with cause (`research-external-grading` §4 +
`research-oracle-adequacy` §4 + `research-model-profiles` §2). Nearly every rejection is the small-model lens
doing its job — the frontier's judge-heavy answers are exactly what a 14B/30B single box cannot afford:

| # | Rejected | Reason |
|---|----------|--------|
| R1 | Full / LLM-based mutation in the nightly critical path (STING's LLM-mutation half) | cost + a model in the grading loop competing with the 30B for the one GPU; keep the bounded, offline, **deterministic-operator** audit only (#828) |
| R2 | Quarantine database with per-sprint SLA (Google/Meta-scale flaky management) | wrong scale — our oracles are ephemeral/single-use, nothing to quarantine across nights; keep the lightweight re-run detector (#829) |
| R3 | Docker-per-instance isolation (OpenHands/SWE-bench) | redundant — worktrees + detached driver + NIC-less guest VM already isolate; flips zero classes |
| R4 | Human-in-the-loop per-job blocking review (Devin) | defeats interventions=0; the human step already exists at the right grain (the LA's program-level live-verify) |
| R5 | Solution-leakage detection (SWE-bench+ SoluLeakDetector) | structurally N/A — our oracle is cross-model, spec-blind, authored before any implementation exists; there is no solution to mirror |
| R6 | Trajectory / process-reward-model grading as a banking signal (SWE-TRACE/TRACE) | a PRM is frontier-judge/training-heavy, the wrong tier for a 14B on one box; deterministic outcome gates buy most of its safety far cheaper |
| R7 | Multi-agent LLM oracle deliberation as-is (Nexus's 4-agent loop / CANDOR full pipeline) | too heavy and nondeterministic on one box; **adopt the deterministic kernel** (execution-grounding against a reference), reject the agent swarm |
| R8 | Pairwise position-bias swapping apparatus for the critic (as a blocker) | topology mismatch — our critic judges a single response, not a pair; keep rubric + jury + agreement measurement, reject the swap apparatus |
| R9 | Contamination-free / live benchmark machinery (SWE-bench-Live) | not our problem — our goals are operator cards / net-new code, not memorized public issues |
| R-model | LLM-judge adequacy / a holistic "delight" judge over the whole repo / gating on a quality band | puts the same small model that wrote the under-covering oracle back in the honesty-critical path, nondeterministic; the constrained rubric + deterministic lints + regression probe capture the value at bounded, ensembled cost — genuine "delight" stays the operator's eyeball |

Two further rejections carried from the verdict/oracle doctrine itself: **mid-run oracle repair toward
passing** (§Decision-4 — the FALSE-DONE hazard) and **model authority over any verdict** (§Decision-1/3 —
only the deterministic integrity-downgrade may move a GREEN).

## References

- **This ADR / program:** Vikunja **#825** (QUALITY-7, ADR-037) inside **#819–#837** (the QUALITY program);
  the b5class verdict work (#740 c.1710/c.1717); the #832 tampering-downgrade LA approval (c.1733); Small-Model
  Consciousness (#740 c.1721).
- **Live code (main @ 706c6972):** `shared/fleet/swap_ops.py` (`real_run_wave_gate`, `real_seed_job_oracle`,
  `real_run_job_oracle`, guest-oracle executor); `shared/fleet/swap_driver.py` (`compute_job_verdict`,
  `compute_flat_verdict`, the NEVER-ZERO teardown); `shared/fleet/acceptance.py` (tier taxonomy
  `OBJECTIVE_TIERS`/`HUMAN_TIERS`/`TEST_TIERS`, `BEHAVIOR_GATED_ECOSYSTEMS`, `generate_job_acceptance_oracle`,
  `criterion_status`, `extract_job_oracle`); `tools/dispatch_harness/battery.py` (`cross_check`,
  `read_guest_oracle_certificate`, `guest_agreement`); `shared/timeout_registry.py` (the (window, budget)
  taxonomy).
- **Design dossiers (citations, `docs/handoffs/*-20260711.md`):** `failure-taxonomy` (the two-night failure
  ranking; FALSE-DONE=0 / interventions=0); `research-external-grading` (the field survey; the duality thesis;
  the already-exceeds table; the rejections); `research-oracle-adequacy` (the 4/6 coverage baseline; the
  traceability matrix); `research-grading-adversarial` (the environment-gamed-GREEN channel; the tampering
  fingerprints behind #832); `research-green-audit` (the B2 leniency drift; the GREEN-quality doctrine);
  `research-model-profiles` (the greedy-14B collision; the variable taxonomy; the manifest).
- **External literature (frontier-2026):** Meta-Engineering Harnesses / independence-based verification
  (arXiv 2605.25665); AgentLens "Lucky Pass Problem" (2605.12925); Nexus execution-grounding (2510.26423);
  Verification Horizon — no silver bullet for coding-agent rewards (2606.26300); Judge-Panel
  Finite-Calibration Regime Map (2606.01034); STING mutation-guided oracle adequacy (2604.01518); SWE-bench+
  weak-tests/leakage (2410.06992). Established roots: SWE-bench Verified (F→P invariant); mutation testing;
  Hypothesis health-checks; Aider lint/test loop; Google flaky-test detection.
- **Prior ADRs:** ADR-035 (Acceptance Layer — criteria tiers, honest ecosystem coverage, never-rubber-stamp),
  ADR-034 (model-swap driver — the NEVER-ZERO teardown host), ADR-033 §Am.3 (dispatch asset generation).
- **Lessons:** 221 (window/budget-pair composition), 222 (positive controls — the B5 false-red), 216
  (identity-plus-liveness recovery).
