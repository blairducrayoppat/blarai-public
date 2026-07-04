---
sprint_id: 18
sprint_name: "The Pre-Gate Sweep"
scr_version: 1
status: "CLOSING — C1/C2/C4/C6 MET (agent-run green); C3 PARTIAL (escalated, #632); C5 = the independent production-posture SWAGR (runs at this close); C7 = this close."
tracking_task: 631
authored_by: "Sprint-18 execution Orchestrator"
authored_on: "2026-06-08"
predecessor_sprint: 17
main_head_at_close: "see git log --oneline main (close-artifact commits on sprint18/close, merged at close)"
---

# Sprint 18 SCR — "The Pre-Gate Sweep"

## 1. Outcome

Sprint 18 makes the real BlarAI system **end-to-end automation-verifiable under
production posture with the model loaded** — the last build/verification wave
before the #612 capstone phase and the #598 air-gap sign-off. Six of seven
criteria are MET with agent-run green; one (C3) is **PARTIAL** because the work
*verified a premise to be false* (the AO→router wiring it was meant to test does
not exist) — surfaced, ticketed (#632), and carried forward as an LA architecture
decision, not papered over.

The headline: the §5.1 production-posture verification that the #598 gate needs is
now a **scripted run the fleet executes itself**, not a manual boot-and-click
marathon. C1 proved it — gateway → real AO over **production mTLS**
(`dev_mode=False`) → real Qwen3-14B → real PGOV → streamed response, green on the
Arc 140V, agent-run, no operator terminal time. This sprint is the proof of the
#629 automate-first reframe: **the agent ran every tier itself, including the
model-loaded @hardware tiers.** The LA's only touches were the comprehension gate
and this close.

The air-gap stayed welded throughout; nothing here changed runtime egress.

## 2. Criteria scorecard (SDV §4)

| # | Criterion | Disposition | Evidence |
|---|---|---|---|
| **C1** | Model-loaded prompt round-trip, production posture (GAP-5/§5.1) | **MET** | `tests/harness/test_model_loaded_round_trip.py` agent-run GREEN: `dev_mode=False`, per-boot-minted mTLS, `require_signed_manifest=true` (detached `.sig` verified), real PGOV approved, real STREAM_TOKEN. Load 18.4 s / first-token 3.10 s / total 3.59 s. |
| **C2** | IPC-routing regression lock, model-loaded (GAP-6/§5.1) | **MET** | `test_prompt_round_trip_host_mode.py::TestPromptRoundTripModelLoaded` agent-run GREEN: real-model port resolution, no "Unsupported message type" misroute. Total 2.97 s. |
| **C3** | Semantic-router cross-service path (GAP-8) | **PARTIAL** (Auditor-blessed; do not re-score) | `test_real_router_and_ao_turn_cross_service` (renamed, MINOR-1) agent-run GREEN (real bge-small classify 6.4 ms → CONVERSATIONAL; real AO turn 4.9 s). **Verified the AO never calls `SemanticRouter` in a turn** — the wiring C3 targeted does not exist. Test proves the *adjacent* router→AO path + documents the gap. **LA-DECIDED 2026-06-08: built-ahead → DEFERRED** (not a security control; parked until the first skill-dispatch handler, #577). Tracking #632. |
| **C4** | TUI against a real gateway (GAP-9) | **MET** | `tests/integration/test_tui_real_gateway.py` (slow) GREEN 4/4 in-worktree and re-confirmed on main under `-m slow`: `BlarAIApp` → real `TransportGateway` → real AO (stub-GPU), streaming render + PGOV approved-path + session persistence over the real seam. |
| **C5** | Production-posture SWAGR sweep (§5.1 gate criterion) | **PENDING (this close)** | The independent Auditor SWAGR runs at this close, model **opus**, adversarial, **conducted in production posture (`dev_mode=False`)** so it satisfies §5.1. Verdict appended to this SCR §9 + reconciled into SECURITY_ROADMAP §5.1. |
| **C6** | #630 test-teardown leak fix | **MET (closed)** | merged `f6193d1`; process-tree teardown (4 harness files + `tests/harness/process_tree.py`) + fail-loud port-5001 detector (root `conftest.py`) + 5 verdict unit tests. Deterministic **2342/0** reproduced twice from main without a manual process-kill. Vikunja #630 closed. |
| **C7** | Close hygiene | **MET (this SCR)** | gate green + deterministic baseline; perf captured; fragments folded (lessons 87–90); SCR + ledger + this scorecard; §5.1 reconciled; #631 closed at the LA close-confirm. |

## 3. The merge-gate record

Serial merge-gate, branch-guarded (`branch==main` + toplevel `C:/Users/mrbla/BlarAI`)
before every main-tree merge; `--no-ff`; targeted `git add`; no destructive git;
the standing gate re-run by the Orchestrator from main at each merge (never trusted
from a builder summary).

| Stream | Crit | Build SHA | Merge SHA | Gate after |
|---|---|---|---|---|
| P (#630 teardown) | C6 | `5698936` (+`2c1f373`) | `f6193d1` | **2342/0** (from main; the deterministic baseline) |
| O (TUI real-gateway) | C4 | `b59c246` | `798c8a1` | 2342/0 (113 deselected) + C4 `-m slow` 4/4 |
| M (model-loaded round-trip) | C1,C2 | `e51119d` | `b1d7c96` | 2342/0 |
| N (router cross-service) | C3 | `a57a634` | `be75335` | 2342/0 |
| C1 path-fix | C1 | `e3dbee0` | `dedf341` | (test-config fix; @hardware) |

Final standing gate from main after all merges: **`2342 passed / 0 skipped / 0
failed / 113 deselected`** (deselected up 5 from the new @hardware/@slow tests in
the gate paths; the passing baseline is unchanged). P first established the clean
deterministic baseline; the worktree builders showed the expected ~2320/22
model-absence skip-shift (semantic_router embedding model absent in worktrees —
NOT the port-5001 leak; the skip-signature disambiguation the guide called out).

## 4. Gate-honesty: the model-loaded tiers (committed ≠ done until green)

The @hardware tiers (C1/C2/C3) cannot be verified in a model-absent worktree;
their first green is an **agent-run on the dev box** (Arc 140V, real Qwen3-14B
8.03 GB), run serially (one model in VRAM at a time, separate processes so the GPU
frees between tiers). All green:

- **C1** PASS — production posture, PGOV-approved. **C2** PASS — no misroute under
  real load. **C3** PASS (test) — real router ONNX + real AO turn. + sprint12
  trusted/untrusted turns PASS.
- Community-grade perf captured: `PERFORMANCE_LOG.md` (2026-06-08 entry) +
  `docs/performance/sprint18_model_loaded_roundtrip_2026-06-08.json` (with the
  mandatory `not_measured` block per lesson 33). Env: Intel Core Ultra 7 258V /
  Arc 140V (driver 32.0.101.8826), OpenVINO 2026.1.0 / GenAI 2026.1.0.0.

**Pre-flight verified before committing to the production tiers** (as the model was
pre-flighted): the production security material is provisioned — `certs/` mTLS
material, the detached `manifest.json.sig`/`.pub`, the TPM-sealed DEK keystore — so
the `dev_mode=False` boot verifies rather than fail-closes for absence.

## 5. Scope reconciliation (SECURITY_ROADMAP §5.1)

§5.1 ("Production-posture SWAGR verification — Tiers 1–3 complete and independently
SWAGR-verified in `dev_mode=false`, real certs/keys") is the criterion this sprint
closes. The path: C1/C2 prove the model-loaded production round-trip green
(agent-run), and **C5 — the independent production-posture Auditor SWAGR run at
this close — is the §5.1 verification itself**. On a STRONG/ALIGNED verdict, §5.1
flips from REMAINING to DONE in `docs/security/SECURITY_ROADMAP_air_gap_removal.md`
(the summary table line 263 + the §5.1 checkbox). After §5.1, only the #612
capstone phase (gate-phase 6) and the §5.12 LA sign-off (phase 7) remain before the
#598 GO/NO-GO — both governance acts, not builds.

## 6. Carry-forwards

- **#632 (NEW)** — the AO→router wiring decision surfaced by C3 (built-ahead vs
  integration-gap). Not a build this sprint; an LA architecture call.
- **#615 / #106-remainder** — the VM-occupant deployment round-trip (Python ≥3.12)
  + the runtime per-adjudication re-verification + copy-on-write — a separate
  forward-hardening track (SDV §3/§5), gate-vs-fast-follow scoping is an LA call at
  #598 planning.
- **GAP-10 (dispatcher↔WinUI), GAP-11 (voice E2E), GAP-13 (PA real-model classify)**
  — real but lower-urgency, post-sweep.
- **C6 GUI-harness teardown live-verify** — the tree-kill fix is code-correct + the
  determinism is restored; a full GUI-harness-run-then-gate confirmation rides on
  the next @winui+@hardware dev-machine GUI run (the #621 deferred tier, out of C6
  scope).
- **#607** audit retention (open LA decision); egress enforcement (**#556**,
  post-gate).

## 7. Decisions / findings of record

- **C3 finding (verified):** the semantic router is not wired into the live AO
  turn. Grep of all non-test runtime source confirms no `SemanticRouter.classify()`
  call in `services/assistant_orchestrator/src/`. Recorded on #632 with the
  built-ahead-vs-gap options + a recommendation (built-ahead, consistent with the
  current 2-use-case operational scope and the network-facing-future roadmap).
- **C1 path-fix (`dedf341`):** C1 first fail-closed at boot with
  `AO_CFG_KGM_PATH_NOT_FOUND` — the production signed-manifest gate correctly
  refusing to start because the test's `tmp_path` config used relative model paths
  the AO resolved (from the config's own location) under a dir with no weights. Fix:
  absolute paths in the test config. **The real system behaved correctly; the test
  pointed the path wrong** — a gate-works-before-the-round-trip-does data point
  (lesson 88).
- **Write-path hazard recurrence (lesson 89):** stream M wrote its two test files
  into the main checkout first (reference paths from a brief, correct for reading,
  leaked into writes); caught at collection, recovered non-destructively. The
  worktree-cwd hazard is now known to bite the *write path*, not only the branch.

## 8. Close checklist (C7 / DEC-15)

- [x] All streams merged under the serial branch-guarded gate; deterministic 2342/0 from main.
- [x] Model-loaded @hardware tiers agent-run GREEN (C1/C2/C3); community-grade perf captured.
- [x] Journal fragments folded → BUILD_JOURNAL (lessons 87–90); fragments removed.
- [x] SCR (this doc) + ledger entry (`docs/ledger/20260608_*_sprint18_scr_pre-gate-sweep.md`).
- [x] C3 finding ticketed (#632); #630 (C6) closed.
- [x] Independent production-posture Auditor SWAGR (C5 = §5.1) — **STRONG_ALIGNMENT, 0C / 0M / 5 MINOR**; verdict §9, dispositions §10.
- [x] SECURITY_ROADMAP §5.1 reconciled to **DONE (verification limb)** — QUALIFIED-YES, two qualifications recorded.
- [x] CLAUDE.md baseline + sprint state updated (2342/0, 113 deselected; model-loaded tiers; §5.1 verification DONE).
- [ ] #631 closed at the LA close-confirm (touch #2).

## 9. Independent SWAGR verdict

**STRONG_ALIGNMENT — 0 CRITICAL / 0 MAJOR / 5 MINOR.** Conducted by an independent
Auditor (model opus, adversarial), in production posture (`dev_mode=False`). The
Auditor **independently reproduced** the load-bearing claims, not just read them:

- **Standing gate reproduced:** `2342 passed / 0 skipped / 0 failed / 113 deselected`
  (no port-5001 skip-shift; the C6 detector recorded free→free and passed silently).
- **C1 reproduced in production posture:** PASS — `dev_mode=False`, real Qwen3-14B,
  real `CERT_REQUIRED` mTLS, `require_signed_manifest=true` reaching the verified
  detached `manifest.json.sig`. Genuinely ran (did not skip into a PASS).
- **C3 PARTIAL confirmed honest both directions** — independently grep-verified zero
  `SemanticRouter.classify()` in `services/assistant_orchestrator/src/`; #632 verified
  to exist and rigorous.
- **§5.1 determination: QUALIFIED-YES** — the production-posture verification limb is
  satisfied + reproduced; §5.1 flipped REMAINING→DONE in SECURITY_ROADMAP **with the
  two qualifications recorded** (C1-anchored; scopes the verification criterion only,
  NOT whole-ladder — #598 still gates on #612 / §5.12 / #106-remainder / egress / #607).

Report: `docs/sprints/sprint_18/Strategic_Work_Analysis_and_Gap_Report_Sprint_18.md`.

## 10. MINOR dispositions (all 5, at close)

| # | Finding | Disposition |
|---|---|---|
| MINOR-1 | C3 test name `test_real_router_invoked_inside_ao_turn` asserts the premise the test falsifies (router is *adjacent to*, not *inside*, the AO turn) | **APPLIED at close** — renamed → `test_real_router_and_ao_turn_cross_service` (LA decided built-ahead/deferred 2026-06-08; #632). |
| MINOR-2 | Port-leak detector has a theoretical full-suite-only false-fire edge (TIME_WAIT / racy @hardware teardown); clean gate empirically safe | **Watch; fix-if-fires** — the clean gate is free→free silent-pass (verified twice + by the SWAGR). Add a settle/poll only if it ever fires. |
| MINOR-3 | §5.1 production-posture evidence is C1-anchored (one composed mTLS path) | **Recorded inline** in SECURITY_ROADMAP §5.1 qualification (a); a `dev_mode=False` boot-cascade tier is a forward, non-gate-blocking strengthener. |
| MINOR-4 | §5.1 DONE must scope the *verification* limb, not whole-ladder tier-completion | **Heeded** — the §5.1 reconcile explicitly scopes DONE to the verification criterion and reaffirms #598 still gates on #612 / §5.12 / #106 / egress / #607. |
| MINOR-5 | `coverage_audit.md` GAP-8 wording now known-false (its AO→router premise) | **APPLIED at close** — GAP-8 annotated in `docs/sprints/sprint_16/coverage_audit.md` with the verified finding (router not wired; built-ahead/deferred; #632). |

None block the close; the LA may re-triage at the #632 disposition.
