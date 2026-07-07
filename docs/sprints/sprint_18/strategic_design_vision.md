---
sprint_id: 18
sprint_name: "The Pre-Gate Sweep"
sdv_version: 1
status: "READY FOR EXECUTION — scope is roadmap-settled (SECURITY_ROADMAP §4 step 5; coverage_audit.md burn-down). No open LA forks. Scope checkpoint = the execution session's comprehension gate (guide-reviewed + LA-confirmed); no separate sign-off ceremony, per the minimal-involvement directive."
tracking_task: 631
authored_by: "LA-guide session (Sprint-17 reviewer / Sprint-18 planner)"
authored_on: "2026-06-08"
predecessor_sprint: 17
gate: "#598 air-gap GO/NO-GO — the #612 capstone phase (6) then the sign-off (7) follow THIS sprint"
baked_decisions:
  - "Scope = the pre-gate automation sweep (GAP-5/6/8/9 model-loaded + the §5.1 production-posture SWAGR)"
  - "Automate-first (#629): the agent runs ALL tiers itself, including the model-loaded @hardware tiers — NO LA terminal time except the two governance confirms"
  - "#630 test-teardown leak IS in this sprint (a deterministic gate baseline is foundational to the sweep)"
  - "#615 deployment round-trip + #106 runtime-reverify/CoW = a separate forward-hardening track, NOT this sprint"
---

# Sprint 18 SDV — "The Pre-Gate Sweep"

## 1. Mission

Make the real BlarAI system **end-to-end automation-verifiable under production posture with the model
loaded** — so the #598 gate's **§5.1 production-posture verification is a scripted audit the fleet runs
itself**, not the manual boot-and-click marathon it would otherwise be. This is the **last build/
verification wave** before the #612 capstone phase and the #598 sign-off. The air-gap stays UP throughout;
nothing here changes runtime egress.

## 2. Where this sits — the #598 scorecard (SECURITY_ROADMAP §5, post-Sprint-17)

After Sprint 17, every §5 gate criterion is DONE / DECIDED / DORMANT / PARTIAL **except three**:
- **§5.1 production-posture SWAGR (all tiers)** — REMAINING → **this sprint's core** (C5).
- **§5.13 capstone (#612)** — REMAINING → gate-phase 6, **after** this sprint.
- **§5.12 explicit LA sign-off** — REMAINING → phase 7, the final act.

This sprint closes **§5.1**. After it, the only things standing between the codebase and the air-gap
decision are the **#612 capstone** (the LA's informed risk deep-dive) and the **sign-off** itself —
both governance acts, not builds. Sprint 18 is the last sprint that *writes code/tests* before the gate.

## 3. Decisions BAKED — builders never stop to ask

- **Scope = the automation sweep.** GAP-5/6/8/9 (model-loaded end-to-end coverage) + the §5.1 production-
  posture SWAGR. Per the coverage_audit.md burn-down (§"Sprint 18 (pre-gate sweep)").
- **Automate-first (#629).** The agent runs **every** tier itself, including the model-loaded @hardware
  tiers — the dev box has the GPU (Arc 140V), the real Qwen3-14B, and shell access. There is **no "LA on-
  chip session."** The model-loaded green runs are agent-run, surfacing only results. A step reaches the LA
  **only if proven** to need human hands (none are expected this sprint).
- **#630 is IN.** The test-teardown process leak (the port-5001 skip-shift the guide caught at the Sprint-17
  close) is fixed here — a deterministic gate baseline is foundational to a *trustworthy* automation sweep.
- **#615 + #106-remainder are OUT.** The #615 VM-occupant deployment round-trip (needs the runtime moved to
  Python ≥3.12) and #106's runtime per-adjudication re-verification + copy-on-write are forward hardening on
  a separate track — not gate-automation, not this sprint. (Their gate-vs-fast-follow scoping is an LA call
  at #598 planning.)

## 4. Success criteria (the SWAGR audits against these)

| # | Criterion | Gap / Gate ref | Verification | Tier |
|---|---|---|---|---|
| **C1** | **Model-loaded prompt round-trip (production posture)** — gateway → AO with real Qwen3-14B loaded → prompt → real PGOV output validation → response, over production mTLS (not the GPU stub) | GAP-5 / §5.1 | @hardware tier, **agent-run green** on the dev box; evidence captured (community-grade per testing-data rule) | hw (agent-run) |
| **C2** | **IPC routing regression lock, model-loaded** — extend `test_prompt_round_trip_host_mode.py` with a real-model `@hardware` scenario asserting correct gateway→AO port resolution + no "Unsupported message type" misroute (the ISS-10 class) under real load | GAP-6 / §5.1 | @hardware, agent-run | hw (agent-run) |
| **C3** | **Semantic-router cross-service path** — the real bge-small router invoked *inside a real AO turn* (not in isolation), proving the AO→router wiring | GAP-8 | @hardware, agent-run | hw (agent-run) |
| **C4** | **TUI against a real gateway** — `BlarAIApp` → real `TransportGateway` → real AO (stub-GPU acceptable), exercising streaming render + PGOV display + session persistence over the real seam | GAP-9 | slow-marked integration, green in the standing gate | gate/slow |
| **C5** | **Production-posture SWAGR sweep (§5.1)** — the independent Auditor verifies **all tiers in production-mode posture** (`dev_mode=False`, real security material), confirming the composed system is gate-ready. This SWAGR *is* the §5.1 gate criterion, doing double duty as the sprint close audit | §5.1 (gate) | the close SWAGR, explicitly conducted in production posture across the tier ladder | audit |
| **C6** | **#630 test-teardown leak fix** — the WinUI harness + boot-cascade teardowns terminate their spawned AO/backend/app child processes (process-group kill / port-listener sweep); add a session-scoped autouse fixture that **fails LOUD** if an AO instance is left on loopback 5001 at teardown, so a leak surfaces as a *failure*, not a silent skip-shift | #630 | the gate baseline is **deterministic** (clean 2342/0 reproducible without a manual process-kill); the leak-detector fixture green | gate |
| **C7** | **Close hygiene** — standing gate green + the new tiers; deterministic baseline; SCR + independent Auditor SWAGR + ledger land; §5.1 reconciled in SECURITY_ROADMAP; #631 closed | — | gate re-run by the Orchestrator + reproduced by the Auditor | gate |

## 5. Scope / out-of-scope

**In:** C1–C7.
**Out (named so nothing silently slips):** #615 VM-occupant deployment round-trip + the runtime Python ≥3.12
move (separate forward sprint); #106 runtime per-adjudication re-verification + CoW protection (forward
FUT-04 — note: a full per-adjudication re-hash of the 14B weights exceeds the 500ms budget, so it needs a
sampled/mmap design, not a naive re-hash); **GAP-10** (dispatcher↔WinUI named-pipe), **GAP-11** (voice
E2E), **GAP-13** (PA real-model classify) — real but lower-urgency, post-sweep; the **#612 capstone** (its
own gate-phase 6, after this); the **#598 sign-off** (§5.12, phase 7); **#607** audit retention (open LA
decision); egress enforcement (**#556**, post-gate). The air-gap stays welded.

## 6. The parallel wave — disjoint working sets

Worktree builders write the test files concurrently; the **model-loaded @hardware tiers EXECUTE serially**
(one 14B model fits the Arc 140V VRAM at a time — the build is parallel, the green runs are one-model-at-a-
time on the single GPU).

| Stream | Criterion | Working set (verified disjoint) | Start |
|---|---|---|---|
| **P — #630 teardown leak fix** | C6 | `tests/harness/` teardowns + a new session-scoped autouse leak-detector fixture (`tests/conftest.py` or `tests/harness/conftest.py`) | **first** (a clean deterministic baseline underpins every other stream's gate run) |
| **M — model-loaded round-trip + routing** | C1, C2 | `tests/harness/` (new model-loaded scenario) + `tests/integration/test_prompt_round_trip_host_mode.py` (add `@hardware` scenario) | immediately (build); execute after P lands |
| **N — router cross-service** | C3 | `tests/harness/` (extend `test_sprint12_real_model.py` or a new file) | immediately (build) |
| **O — TUI real-gateway** | C4 | `tests/integration/` (new `slow` file wiring `BlarAIApp` + real `TransportGateway` against the stub-AO) | immediately |

**Coordination (assign, don't race):** `tests/harness/` — M + N add **distinct** files; P edits teardowns/
conftest. `tests/integration/` — C2 extends the existing round-trip file, C4 adds a new file. Branch-guard
(`branch==main` + toplevel) before EVERY main-tree merge — the worktree-cwd-branch hazard bit this project.

## 7. Automate-first (#629) — NO LA terminal time

This is the first sprint authored under the #629 reframe, and it is the proof of it. **The agent runs every
tier itself.** The model-loaded @hardware tiers (C1/C2/C3) run on the dev box under the agent's shell —
load the model, run the tier, capture evidence, surface the result. There is **no one-command-at-a-time LA
session.** The LA's only two touches this sprint:
1. **Confirm the comprehension gate** (via the guide) before the wave dispatches.
2. **Confirm the close.**
A step is escalated to the LA **only** if the agent can *prove* it needs human hands (an elevation the
shell cannot obtain, a physical action) — and none are anticipated. The agent never routes a runnable test
to the operator.

## 8. Gate-honesty conditions (non-negotiable)

- **Committed ≠ done until green.** The model-loaded tiers (C1/C2/C3) are `@hardware`; their first green is
  an **agent-run** on the dev box — they ship with that green captured (community-grade evidence to
  `docs/performance/` + `PERFORMANCE_LOG.md` where they emit timings), not merely written.
- **The baseline must be deterministic.** C6 is a precondition for an honest sweep: until the port-5001 leak
  is fixed, the standing gate's pass/skip split is order/timing-dependent (the guide's independent 2333/9 vs
  the polluted 2342/0). The clean baseline is **2342 selected / 0 failed**; C6 makes it reproduce *without* a
  manual process-kill, and makes a future leak fail loud.
- **The §5.1 SWAGR is conducted in production posture** (`dev_mode=False`, real security material) — a SWAGR
  run in dev posture does NOT satisfy §5.1.
- **The standing gate** is re-run by the Orchestrator at every merge and reproduced by the Auditor — never
  trusted from a builder summary.

## 9. Merge-gate + the close (DEC-15)

- **Merge gate:** review each builder's diff against its criterion + **re-run the gate yourself** with the
  `.venv` python; branch-guard before every main-tree merge; `--no-ff`, keep branches; no destructive git;
  never pytest against the live `%LOCALAPPDATA%` (the root `conftest.py` redirects it); pass EVERY field on
  `update_task` (#625).
- **The close:** fold journal fragments → `BUILD_JOURNAL.md`; author the SCR
  (`docs/sprints/sprint_18/strategic_completion_report.md`); run the **independent Auditor SWAGR** (manual
  spawn, model opus, adversarial — the Sprint-15/16/17 pattern; **conducted in production posture to satisfy
  §5.1**); ledger entry in `docs/ledger/`; reconcile SECURITY_ROADMAP §5.1; close **#631**. Carry forward the
  forward-hardening track (#615 deployment, #106 remainder) + the lower-urgency gaps.

## 10. Scope checkpoint (minimal-LA governance)

No separate SDV sign-off ceremony. The scope checkpoint is the **execution session's comprehension gate**:
it reads this SDV + the coverage audit, presents its understanding + planned wave, the **guide session
reviews it** and hands the LA a paste-ready confirm/correct. The LA's touches this sprint: confirm the gate
(via the guide), and confirm the close. Everything else — including every model-loaded green run — is the
agent's.

**Refs:** `docs/sprints/sprint_16/coverage_audit.md` (GAP-5/6/8/9); SECURITY_ROADMAP §5.1/§4; #630, #629,
#600, #620; the Sprint-17 SDV + SCR + SWAGR (the wave pattern). **Tracking:** #631.
